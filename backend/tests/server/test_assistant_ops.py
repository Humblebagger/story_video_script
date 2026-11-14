#!/usr/bin/env python3
"""接口与助手共用的执行函数：出片预估（要会话、不改段状态、点名的段、在跑的段 409）、排队出片（金额不对 409）、
合成预估（缺音色 422、金额与预览一致、合成中 409）、导出检查（没成片 409）、转换本章（没原文 422、任务进表）。
假视频厂商 + 假 TTS，不联网、不花钱。用法: python3 tests/server/test_assistant_ops.py
"""
import copy
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
_TMP = tempfile.TemporaryDirectory()
os.environ["STORYBOARD_DATA_DIR"] = _TMP.name     # 必须在导入 server.* 之前

# 测试不读真实的 backend/.env：load_settings 里的 _load_dotenv 换成空操作（脚本独占进程，无需还原）
import pipeline.config as _pipeline_config  # noqa: E402
_pipeline_config._load_dotenv = lambda *_a, **_k: None
os.environ["STORYBOARD_VIDEO_PROVIDER"] = "fake"
os.environ["STORYBOARD_TTS_PROVIDER"] = "fake"
os.environ["STORYBOARD_RENDER_RUNNER"] = "0"

from fastapi import HTTPException  # noqa: E402
from render import providers, session as render_session  # noqa: E402
from render.providers.fake import FakeTts, FakeVideo  # noqa: E402
from server import app as app_mod  # noqa: E402
from server import auth, novels  # noqa: E402

providers.register("fake", lambda: FakeVideo())
providers.register_tts("fake", lambda: FakeTts())
DOC = json.loads((ROOT / "tests" / "real_text_yao" / "output_merged.json").read_text(encoding="utf-8"))


def status_of(fn, *args) -> tuple:
    try:
        fn(*args)
    except HTTPException as e:
        d = e.detail
        return e.status_code, d.get("message") if isinstance(d, dict) else str(d)
    raise AssertionError("应抛 HTTPException")


def main() -> int:
    user = auth.register("alice", "secret1")
    uid = user["id"]
    nid = novels.create_novel(uid, "药")["id"]
    cid = novels.create_chapter(uid, nid, "第一章", text="原文")["id"]
    empty = novels.create_chapter(uid, nid, "第二章", text="")["id"]
    novels.create_version(uid, nid, cid, "v1", {}, "原文")
    novels.update_version_state(uid, nid, cid, "v1", "succeeded", result=copy.deepcopy(DOC))
    root = novels.render_dir(uid, nid, cid, "v1")

    # 1. 出片预估：没会话 404；建会话后金额 = 剩余各段合计；不改段状态；点名的段只算这几段
    code, msg = status_of(app_mod._film_quote, user, nid, cid, "v1", None)
    assert code == 404 and "出片会话" in msg, msg
    s = app_mod.render_session_post(nid, cid, "v1", None, user)
    q = app_mod._film_quote(user, nid, cid, "v1", None)
    planned = [c for c in s["clips"] if c["state"] == "planned"]
    assert q["clips"] == [c["id"] for c in planned]
    assert q["amount"] == round(sum(c["estimate_cny"] for c in planned), 2)
    assert all(c["state"] == "planned" for c in render_session.load(root)["clips"]), "预估不改段状态"
    first = planned[0]["id"]
    one = app_mod._film_quote(user, nid, cid, "v1", [first])
    assert one["clips"] == [first] and one["amount"] == planned[0]["estimate_cny"]
    print("1. 出片预估 ✓")

    # 2. 排队出片：金额对不上 409；对上了排队；在跑的段再预估 409；剩余预估不含已排队的
    code, _ = status_of(app_mod._film_run, user, nid, cid, "v1", [first], one["amount"] + 1)
    assert code == 409
    v = app_mod._film_run(user, nid, cid, "v1", [first], one["amount"])
    assert next(c for c in v["clips"] if c["id"] == first)["state"] == "queued"
    code, msg = status_of(app_mod._film_quote, user, nid, cid, "v1", [first])
    assert code == 409 and "排队" in msg, msg
    assert first not in app_mod._film_quote(user, nid, cid, "v1", None)["clips"]
    print("2. 排队出片 ✓")

    # 3. 合成预估：缺音色 422；选好音色后金额与合成预览一致；合成中 409
    code, msg = status_of(app_mod._compose_quote, user, nid, cid, "v1", True)
    assert code == 422 and "音色" in msg, msg
    voices = app_mod.render_voices(nid, cid, "v1", user)
    app_mod.render_voices_put(nid, cid, "v1", app_mod.RenderVoicesBody(
        voices={k: "fake-male" for k in voices["missing"]}), user)
    p = app_mod.render_compose_get(nid, cid, "v1", True, user)
    q = app_mod._compose_quote(user, nid, cid, "v1", True)
    assert q == {"amount": p["tts_cny"], "chars": p["tts_chars"]}, q
    with render_session.mutate(root) as sess:
        sess["final"] = {"state": "running", "files": [], "report": None, "error": None, "detail": None}
    code, msg = status_of(app_mod._compose_quote, user, nid, cid, "v1", True)
    assert code == 409 and "合成" in msg, msg
    with render_session.mutate(root) as sess:
        sess["final"] = None
    print("3. 合成预估 ✓")

    # 4. 导出检查：还没有成片 409
    code, msg = status_of(app_mod._export_check, user, nid, cid, "v1")
    assert code == 409 and "成片" in msg, msg
    print("4. 导出检查 ✓")

    # 5. 转换本章：没原文 422；有原文时建版本、任务进表（后台转换换成空函数，不调模型）
    real = app_mod._run_version_job
    app_mod._run_version_job = lambda *a, **k: None
    try:
        code, _ = status_of(app_mod._start_version, user, nid, empty, {}, False)
        assert code == 422
        r = app_mod._start_version(user, nid, cid, {}, False)
        job = app_mod._jobs[r["job_id"]]
        assert job["novel_id"] == nid and job["chapter_id"] == cid and r["version_id"] == r["job_id"]
        assert novels.get_version(uid, nid, cid, r["version_id"])["status"] == "queued"
    finally:
        app_mod._run_version_job = real
    print("5. 转换本章 ✓")

    # 6. 复验与保存（接口与助手共用）：只复验不改版本；保存后状态与复验一致；改坏了照样保存、标草稿
    doc = copy.deepcopy(novels.get_version(uid, nid, cid, "v1")["result"])
    shot = doc["episodes"][0]["shots"][0]
    shot["action"] = "改过的画面"
    chk = app_mod._check_version_doc(user, nid, cid, "v1", doc)
    assert chk == {"ok": True, "warnings": []}, chk
    assert novels.get_version(uid, nid, cid, "v1")["result"]["episodes"][0]["shots"][0]["action"] != "改过的画面"
    r = app_mod._save_version_doc(user, nid, cid, "v1", doc)
    assert r["status"] in ("succeeded", "completed_with_warnings") and r["id"] == "v1"
    assert novels.get_version(uid, nid, cid, "v1")["result"]["episodes"][0]["shots"][0]["action"] == "改过的画面"
    bad = copy.deepcopy(doc)
    bad["episodes"][0]["shots"][0]["narration"]["text"] = "完全不是原文"
    bad["episodes"][0]["shots"][0]["narration"]["unit_refs"] = ["u99999"]   # 引用不存在的句单元：高危，才算不合格
    chk = app_mod._check_version_doc(user, nid, cid, "v1", bad)
    assert chk["ok"] is False and chk["warnings"] and len(chk["warnings"]) <= 5, chk
    assert all(w["code"] == "verify.finding" and _TMP.name not in json.dumps(w, ensure_ascii=False) for w in chk["warnings"])
    assert all(w["params"]["detail"]["code"].startswith("verify.rule.") and "t" not in w["params"]["detail"]
               for w in chk["warnings"]), "复验原因的 detail 是该条规则的消息对象（子计划 5）"
    assert any(w["params"]["detail"] == {"code": "verify.rule.REF-NARRATION-001", "params": {"unit": "u99999"}}
               for w in chk["warnings"]), chk["warnings"]
    assert app_mod._save_version_doc(user, nid, cid, "v1", bad)["status"] == "draft_invalid"
    app_mod._save_version_doc(user, nid, cid, "v1", doc)      # 改回去，免得影响后面
    print("6. 复验与保存 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
