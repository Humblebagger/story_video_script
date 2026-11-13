#!/usr/bin/env python3
"""出片接口：建会话与设置、关键帧作首帧、试段与出片线程推进、取文件、批量确认与上限、
过期与重做、采用、原声静音、删版本连带删除。

全程临时数据目录 + 假厂商，不联网、不花钱。用法: python3 tests/server/test_render.py
"""
import copy
import hashlib
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
os.environ["STORYBOARD_RENDER_RUNNER"] = "0"     # 不起后台线程，测试里手动 tick

from fastapi.testclient import TestClient  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from render import providers, session as render_session  # noqa: E402
from render.providers.fake import FAKE_MP4, FakeVideo  # noqa: E402
from server import app as app_mod  # noqa: E402
from server import auth, novels  # noqa: E402

FAKE = FakeVideo()
providers.register("fake", lambda: FAKE)
DOC = json.loads((ROOT / "tests" / "real_text_yao" / "output_merged.json").read_text(encoding="utf-8"))
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def drain(limit=3000):
    runner = app_mod._render_runner
    for _ in range(limit):
        if not runner.watching():
            return
        runner.tick()
    raise AssertionError("出片线程没跑完")


def pick(s, cid):
    return next(x for x in s["clips"] if x["id"] == cid)


def main() -> int:
    app_mod._render_runner.sleep = lambda _s: None
    c = TestClient(app_mod.app)
    user = auth.register("alice", "secret1")
    uid = user["id"]
    H = {"Authorization": f"Bearer {auth.issue_token(uid)}"}
    nid = novels.create_novel(uid, "药")["id"]
    cid = novels.create_chapter(uid, nid, "第一章", text="原文")["id"]
    novels.create_version(uid, nid, cid, "v1", {}, "原文")
    novels.update_version_state(uid, nid, cid, "v1", "succeeded", result=copy.deepcopy(DOC))
    R = f"/novels/{nid}/chapters/{cid}/versions/v1/render"

    # 1. 建会话：需要登录；默认设置；非法设置 422；没有分镜产物不能出片
    assert c.post(R + "/session").status_code == 401
    assert c.get(R + "/session", headers=H).status_code == 404
    r = c.post(R + "/session", headers=H, json={})
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["provider"] == "fake" and s["audio_mode"] == "tts_all" and "owner" not in s
    assert s["clips"] and all(x["state"] == "planned" for x in s["clips"])
    assert s["options"]["resolutions"] == ["480p", "720p"]
    assert c.patch(R + "/session", headers=H, json={"resolution": "4k"}).status_code == 422
    novels.create_version(uid, nid, cid, "v2", {}, "原文")
    r = c.post(f"/novels/{nid}/chapters/{cid}/versions/v2/render/session", headers=H, json={})
    assert r.status_code == 422, "没有分镜产物不能出片"
    print("1. 建会话 ✓")

    # 2. 上传关键帧后读取：该段改用关键帧作首帧
    second = s["clips"][1]
    shot = second["shots"][0]
    r = c.put(f"/novels/{nid}/chapters/{cid}/versions/v1/keyframes/{shot}", content=PNG,
              headers={**H, "Content-Type": "image/png"})
    assert r.status_code == 200, r.text
    s = c.get(R + "/session", headers=H).json()
    assert pick(s, second["id"])["first_frame"] == f"keyframe:{shot}"
    assert pick(s, second["id"])["frame_mode"] == "frame"
    print("2. 关键帧作首帧 ✓")

    # 3. 试段 → 出片线程推进 → done；取文件；路径穿越被拒
    r = c.post(R + f"/clips/{second['id']}/run", headers=H, json={})
    assert r.status_code == 200, r.text
    assert pick(r.json(), second["id"])["state"] == "queued"
    drain()
    assert FAKE.submitted[-1].first_frame.startswith("data:image/png;base64,")
    s = c.get(R + "/session", headers=H).json()
    done = pick(s, second["id"])
    assert done["state"] == "done" and s["spent_cny"] == done["attempts"][0]["cost_cny"] > 0
    f = c.get(R + "/files/" + done["attempts"][0]["file"], headers=H)
    assert f.status_code == 200 and f.content == FAKE_MP4
    assert c.get(R + "/files/clips/nope.mp4", headers=H).status_code == 404
    assert c.get(R + "/files/%2e%2e/%2e%2e/versions/v1.json", headers=H).status_code == 404
    print("3. 试段与取文件 ✓")

    # 4. 批量：必须带确认金额；不一致 409；超上限 422；在跑时不能改设置
    r = c.post(R + "/run", headers=H, json={})
    assert r.status_code == 409 and r.json()["detail"]["expected_cny"] > 0
    total = r.json()["detail"]["expected_cny"]
    assert c.post(R + "/run", headers=H, json={"expected_cny": total + 1}).status_code == 409
    assert c.post(R + "/run", headers=H, json={"expected_cny": total}).status_code == 422
    assert c.patch(R + "/session", headers=H, json={"budget_cny": 100000}).status_code == 200
    r = c.post(R + "/run", headers=H, json={"expected_cny": total})
    assert r.status_code == 200, r.text
    assert c.patch(R + "/session", headers=H, json={"resolution": "480p"}).status_code == 409
    drain()
    s = c.get(R + "/session", headers=H).json()
    assert s["counts"] == {"done": len(s["clips"])}, s["counts"]
    print("4. 批量确认与上限 ✓")

    # 5. 分镜改动 → 过期（旧视频仍在）；重做采用新的一次；可换回旧的（仍标过期）
    edited = copy.deepcopy(DOC)
    sh = next(x for ep in edited["episodes"] for x in ep["shots"] if x["id"] == shot)
    sh["action"] += "（改）"
    novels.update_version_result(uid, nid, cid, "v1", edited, verification={}, status="succeeded")
    s = c.get(R + "/session", headers=H).json()
    assert pick(s, second["id"])["state"] == "stale" and pick(s, second["id"])["chosen"] == 0
    assert all(x["state"] == "done" for x in s["clips"] if x["id"] != second["id"])
    r = c.post(R + f"/clips/{second['id']}/run", headers=H, json={})
    assert r.status_code == 200, r.text
    drain()
    st = pick(c.get(R + "/session", headers=H).json(), second["id"])
    assert st["state"] == "done" and st["chosen"] == 1 and len(st["attempts"]) == 2
    r = c.put(R + f"/clips/{second['id']}/chosen", headers=H, json={"attempt": 0})
    assert r.status_code == 200 and pick(r.json(), second["id"])["state"] == "stale"
    assert c.put(R + f"/clips/{second['id']}/chosen", headers=H, json={"attempt": 9}).status_code == 422
    print("5. 过期、重做与采用 ✓")

    # 6. 原声静音
    r = c.patch(R + f"/clips/{second['id']}", headers=H, json={"mute_native": True})
    assert r.status_code == 200 and pick(r.json(), second["id"])["mute_native"] is True
    assert c.patch(R + "/clips/E99-C01", headers=H, json={"mute_native": True}).status_code == 404
    print("6. 原声静音 ✓")

    # 6b. 会话文件损坏：改动类接口 500，原文件不被清零
    sp = novels.render_dir(uid, nid, cid, "v1") / "session.json"
    sp.write_text("{坏的", encoding="utf-8")
    r = c.patch(R + f"/clips/{second['id']}", headers=H, json={"mute_native": False})
    assert r.status_code == 500 and "损坏" in r.json()["detail"]["message"], r.text
    assert sp.read_text(encoding="utf-8") == "{坏的"
    print("6b. 会话损坏 500 ✓")

    # 7. 删版本：会话目录一并删除
    root = novels.render_dir(uid, nid, cid, "v1")
    assert (root / "session.json").exists()
    novels.delete_version(uid, nid, cid, "v1")
    assert not root.exists()
    print("7. 删版本连带删除 ✓")

    # ---------- 终审修复 ----------
    novels.create_version(uid, nid, cid, "v3", {}, "原文")
    novels.update_version_state(uid, nid, cid, "v3", "succeeded", result=copy.deepcopy(DOC))
    R3 = f"/novels/{nid}/chapters/{cid}/versions/v3/render"
    V3 = f"/novels/{nid}/chapters/{cid}/versions/v3"
    s = c.post(R3 + "/session", headers=H, json={}).json()
    n_clips = len(s["clips"])
    one = s["clips"][0]["id"]
    root3 = novels.render_dir(uid, nid, cid, "v3")

    # 8. 分镜被清空后读取：不重建、不把段挤进 orphaned
    novels.update_version_state(uid, nid, cid, "v3", "succeeded", result={"episodes": []})
    r = c.get(R3 + "/session", headers=H)
    assert r.status_code == 200, r.text
    assert len(r.json()["clips"]) == n_clips and not r.json()["orphaned"]
    assert len(render_session.load(root3)["clips"]) == n_clips
    novels.update_version_state(uid, nid, cid, "v3", "succeeded", result=copy.deepcopy(DOC))
    print("8. 分镜清空读取不清段 ✓")

    # 9. 待核对的段：界面能看到标记；单段点名重做清掉
    render_session.queue_run(root3, [one])
    render_session.begin_submit(root3, one)
    render_session.submit_failed(root3, one, "不确定", uncertain=True)
    s = c.get(R3 + "/session", headers=H).json()
    assert pick(s, one)["uncertain"] is True and s["uncertain_count"] == 1
    r = c.post(R3 + f"/clips/{one}/run", headers=H, json={})
    assert r.status_code == 200 and pick(r.json(), one)["uncertain"] is False, r.text
    print("9. 待核对标记与单段重做 ✓")

    # 10. 有片段在出时删版本 409，目录与版本都还在；出完后可删
    app_mod._render_runner.tick()
    assert pick(c.get(R3 + "/session", headers=H).json(), one)["state"] == "running"
    r = c.delete(V3, headers=H)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "chapter.version.busy", r.text
    assert (root3 / "session.json").exists() and novels.get_version(uid, nid, cid, "v3")
    drain()
    assert pick(c.get(R3 + "/session", headers=H).json(), one)["state"] == "done"
    r = c.delete(V3, headers=H)
    assert r.status_code == 200, r.text
    assert not root3.exists()
    print("10. 在出时不能删版本 ✓")

    # 11. 会话目录已删：写回抛 NotFound，且不把目录重新建出来（出片线程据此不再盯）
    s_old = {"version": 1, "clips": []}
    try:
        render_session._save(root3, s_old)
        raise AssertionError("应抛 NotFound")
    except render_session.NotFound:
        pass
    assert not root3.exists()
    try:
        render_session.clip_dest(root3, one, "t-1")
        raise AssertionError("应抛 NotFound")
    except render_session.NotFound:
        pass
    assert not root3.exists()
    print("11. 删掉的目录不被重建 ✓")

    # ---------- 画布出片（A2）接口补充 ----------

    # 12. 读取时报告验证门结果（只报告不拦）；可选项带费率依据
    novels.create_version(uid, nid, cid, "v9", {}, "原文")
    novels.update_version_state(uid, nid, cid, "v9", "succeeded", result=copy.deepcopy(DOC))
    R9 = f"/novels/{nid}/chapters/{cid}/versions/v9/render"
    assert c.post(R9 + "/session", headers=H, json={}).status_code == 200
    s = c.get(R9 + "/session", headers=H).json()
    assert s["gate"] == {"ok": True, "message": None}, s["gate"]
    assert s["options"]["rate_note"] == {"code": "rate.fake", "params": {}}, s["options"]
    real_gate = app_mod._render_gate

    def failing_gate(doc, record):
        raise HTTPException(422, detail={"message": "分镜未通过独立验证，禁止进入付费渲染",
                                         "verification": {"ok": False}})

    app_mod._render_gate = failing_gate
    try:
        r = c.get(R9 + "/session", headers=H)
        assert r.status_code == 200, "读取不被验证门拦下"
        assert r.json()["gate"] == {"ok": False, "message": "分镜未通过独立验证，禁止进入付费渲染"}
        assert c.post(R9 + "/run", headers=H, json={"expected_cny": 1}).status_code == 422
    finally:
        app_mod._render_gate = real_gate
    print("12. 读取报告验证门、费率依据 ✓")

    # 13. 上传风格图后建会话：段用上风格图；读取带回可重出计数
    novels.save_style_image(uid, nid, "image/png", PNG)
    R13 = f"/novels/{nid}/chapters/{cid}/versions/v13/render"
    novels.create_version(uid, nid, cid, "v13", {}, "原文")
    novels.update_version_state(uid, nid, cid, "v13", "succeeded", result=copy.deepcopy(DOC))
    s = c.post(R13 + "/session", headers=H, json={}).json()
    kinds = {x["style"] for x in s["clips"]}
    assert "used" in kinds and kinds <= {"used", "first_frame"}, kinds   # 首帧单用的段不带风格图
    assert s["style_outdated_count"] == 0
    g = c.get(R13 + "/session", headers=H).json()
    assert g["style_outdated_count"] == 0 and all(x["style_outdated"] is False for x in g["clips"])
    # _render_request（出片线程用）也带风格图：请求里恰有一个 style 参考，哈希是图的哈希
    sess13 = render_session.load(root13 := novels.render_dir(uid, nid, cid, "v13"))
    used13 = next(x for x in sess13["clips"] if x["style"] == "used")
    req13, _ = app_mod._render_request(root13, sess13, used13)
    assert req13.style_ref == hashlib.sha256(PNG).hexdigest()
    assert [r.role for r in req13.refs].count("style") == 1
    print("13. 风格图进会话、进请求 ✓")

    # 14. 出片接口的错误是带代码的消息对象（409 仍带重算金额）
    R14 = f"/novels/{nid}/chapters/{cid}/versions/v14/render"
    novels.create_version(uid, nid, cid, "v14", {}, "原文")
    novels.update_version_state(uid, nid, cid, "v14", "succeeded", result=copy.deepcopy(DOC))
    r = c.get(R14 + "/session", headers=H)
    assert r.status_code == 404 and r.json()["detail"] == {
        "code": "film.session.none", "params": {}, "message": "还没有出片会话"}, r.text
    assert c.post(R14 + "/session", headers=H, json={}).status_code == 200
    r = c.post(R14 + "/run", headers=H, json={})
    d = r.json()["detail"]
    assert r.status_code == 409 and d["code"] == "film.run.confirm" and d["expected_cny"] > 0, r.text
    assert d["params"]["amount"]["t"] == "money" and d["params"]["amount"]["cny"] == d["expected_cny"], d
    r = c.patch(R14 + "/session", headers=H, json={"resolution": "4k"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "film.settings.bad_resolution", r.text
    r = c.get(R14 + "/files/nope.mp4", headers=H)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "film.file.not_found", r.text
    s = c.get(R14 + "/session", headers=H).json()
    assert s["options"]["rate_note"] == {"code": "rate.fake", "params": {}}
    print("14. 出片接口错误带代码 ✓")

    # 14b. 合成与音色接口返回消息对象
    R2 = f"/novels/{nid}/chapters/{cid}/versions/v2/render"      # v2 没有分镜产物
    r = c.post(R2 + "/compose", headers=H, json={})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "film.session.no_storyboard", r.text
    try:
        app_mod._compose_quote(user, nid, cid, "v2", True)
        raise AssertionError("应当 422")
    except HTTPException as e:
        assert e.status_code == 422 and e.detail["code"] == "film.session.no_storyboard", e.detail
    real_tts, app_mod._tts = app_mod._tts, lambda: type("T", (), {"caps": type("C", (), {"voices": []})()})()
    r = c.put(R2 + "/voices", headers=H, json={"voices": {}})
    assert r.status_code == 404 and r.json()["detail"]["code"] == "film.session.none", r.text
    novels.create_version(uid, nid, cid, "v15", {}, "原文")
    R15 = f"/novels/{nid}/chapters/{cid}/versions/v15/render"
    sp15 = novels.render_dir(uid, nid, cid, "v15") / "session.json"
    sp15.parent.mkdir(parents=True, exist_ok=True)
    sp15.write_text("{坏的", encoding="utf-8")
    r = c.put(R15 + "/voices", headers=H, json={"voices": {}})
    app_mod._tts = real_tts
    assert r.status_code == 500 and r.json()["detail"]["code"] == "film.session.corrupt_admin", r.text
    print("14b. 合成与音色接口返回消息对象 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
