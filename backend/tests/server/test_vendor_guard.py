#!/usr/bin/env python3
"""响应守卫：普通用户能调到的接口，响应里没有厂商或模型名、没有禁止的字段（视频地址、计费快照、厂商与档位名等）。
用真实的厂商名注册桩（名字是真的、行为是假的），再往会话文件里投毒（带厂商词的错误原文、签名地址、用量、旧错误代码），
逐个接口检查；最后核对路由清单：新增接口必须登记进守卫（调用它，或写明豁免理由）。
全程临时数据目录 + 桩，不联网、不花钱。用法: python3 tests/server/test_vendor_guard.py
"""
import copy
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import _noenv  # noqa: E402,F401  测试不读真实 .env

_TMP = tempfile.TemporaryDirectory()
os.environ["STORYBOARD_DATA_DIR"] = _TMP.name     # 必须在导入 server.* 之前

import pipeline.config as _pipeline_config  # noqa: E402
_pipeline_config._load_dotenv = lambda *_a, **_k: None
os.environ["STORYBOARD_VIDEO_PROVIDER"] = "minimax"      # 用真实的厂商名注册桩：守卫要在最像线上的条件下查
os.environ["STORYBOARD_TTS_PROVIDER"] = "volc"
os.environ["MINIMAX_API_KEY"] = "k-test-not-real"        # 假值，只为让档位表把它当成已配置；桩不联网
os.environ.pop("ARK_API_KEY", None)
os.environ["STORYBOARD_RENDER_RUNNER"] = "0"

from fastapi.testclient import TestClient  # noqa: E402
from render import plan as render_plan, providers, session as render_session, tiers  # noqa: E402
from render.providers.fake import FakeTts, FakeVideo  # noqa: E402
from server import app as app_mod  # noqa: E402
from server import auth, novels  # noqa: E402
from server import public as P  # noqa: E402


class StubMiniMax(FakeVideo):
    name = "minimax"
    default_model = "minimax-h3"

    def __init__(self):
        super().__init__(polls_to_finish=1)
        self.models = {k: {"label": f"MiniMax {k}"} for k in ("minimax-h3", "minimax-h3-highspeed", "minimax-h3-lite")}


class StubVolc(FakeTts):
    name = "volc"


VIDEO = StubMiniMax()
providers.register("minimax", lambda: VIDEO)
providers.register_tts("volc", lambda: StubVolc())
FORBIDDEN_KEYS = ("video_url", "last_frame_url", "billing", "known_cost_cny", "provider", "providers", "models", "default_note")
# usage 不在禁止名单里：转换清单的尝试记录里有同名的用量字段（合法）。出片尝试里的 usage 在第 5 步单独断言。
DOC = json.loads((ROOT / "tests" / "real_text_yao" / "output_merged.json").read_text(encoding="utf-8"))
SEEN: set = set()
SEEN_PATHS: set = set()
RT = "/novels/{nid}/chapters/{cid}/versions/{vid}/render"


def clean(label, resp, *, route=None, content=False, models=()):
    """这次响应里没有厂商词、没有禁止的键。content=True：响应里有用户的分镜正文，只查键名，不做全文扫词。"""
    assert resp.status_code < 500, (label, resp.status_code, resp.text[:300])
    body = resp.json()
    if not content:
        assert not P.find_vendor_words(body), (label, P.find_vendor_words(body))

    def walk(v, path="$"):
        if isinstance(v, dict):
            for k, x in v.items():
                assert k not in FORBIDDEN_KEYS, (label, f"{path}.{k}")
                # models：这个接口里 model 字段合法的取值（/render/plan 的 estimate.model 是估价费率档，如 standard，不是厂商模型）
                assert not (k == "model" and isinstance(x, str) and x not in models), (label, f"{path}.model")
                walk(x, f"{path}.{k}")
        elif isinstance(v, list):
            for i, x in enumerate(v):
                walk(x, f"{path}[{i}]")
    walk(body)
    SEEN.add(label)
    if route:
        SEEN_PATHS.add(route)
    return resp


def drain(limit=200):
    runner = app_mod._render_runner
    for _ in range(limit):
        if not runner.watching():
            return
        runner.tick()
    raise AssertionError("出片线程没跑完")


def pick(s, iid):
    return next(x for x in s["clips"] + s["free"] if x["id"] == iid)


def main() -> int:
    assert P.find_vendor_words(DOC) == [], "夹具里不应含词表里的词（换了夹具要重新审）"
    app_mod._render_runner.sleep = lambda _s: None
    c = TestClient(app_mod.app)
    alice = auth.register("alice", "secret1")["id"]
    boss = auth.register("boss", "secret2")["id"]
    auth.update_user(boss, role="admin")
    H = {"Authorization": f"Bearer {auth.issue_token(alice)}"}
    HA = {"Authorization": f"Bearer {auth.issue_token(boss)}"}
    nid = novels.create_novel(alice, "药")["id"]
    cid = novels.create_chapter(alice, nid, "第一章", text="原文")["id"]
    novels.create_version(alice, nid, cid, "v1", {}, "原文")
    novels.update_version_state(alice, nid, cid, "v1", "succeeded", result=copy.deepcopy(DOC))
    R = f"/novels/{nid}/chapters/{cid}/versions/v1/render"
    root = novels.render_dir(alice, nid, cid, "v1")

    # 1-2. 建会话、出一段到完成、再排一段（走完整流程，留下真实形状的尝试）
    s = c.post(R + "/session", headers=H, json={"budget_cny": 100000}).json()
    ids = [x["id"] for x in s["clips"]]
    assert len(ids) >= 4, ids
    a, b, d, e = ids[:4]
    assert c.post(R + f"/clips/{a}/run", headers=H, json={}).status_code == 200
    drain()
    assert pick(c.get(R + "/session", headers=H).json(), a)["state"] == "done"
    assert c.post(R + f"/clips/{b}/run", headers=H, json={}).status_code == 200

    # 3. 投毒：把各种带厂商词的原始数据写进会话文件
    now = render_session._now()
    fake_file = Path(root) / "clips" / "late.mp4"
    fake_file.parent.mkdir(parents=True, exist_ok=True)
    fake_file.write_bytes(b"x")
    sign = "https://x.volces.com/v.mp4?X-Tos-Signature=zz"
    with render_session.mutate(root) as s2:
        byid = {x["id"]: x for x in s2["clips"]}
        k1 = byid[d]
        k1.update(state="failed", error="视频服务（MiniMax）账户余额不足，暂时无法出片，请联系管理员",
                  error_msg={"code": "film.minimax.insufficient_balance", "params": {}}, ended_at=now, ended_as="failed")
        k2 = byid[e]
        k2.update(state="failed", error="KeyError: 'video_url' Seedance sk-live-12345 " + sign, error_msg=None,
                  ended_at=now, ended_as="failed")
        k3 = byid[a]
        k3["attempts"].append({
            "task_id": "cgt-x", "state": "failed", "video_url": sign, "last_frame_url": sign,
            "usage": {"model": "doubao-seedance-2-0"},
            "billing": {"provider": "minimax", "model": "minimax-h3", "resolution": "768P", "duration": 5, "estimate_cny": 2.5},
            "known_cost_cny": 2.5, "cost_cny": 0,
            "error_msg": {"code": "film.provider.rejected", "params": {"detail": {"t": "vendor", "text": "MiniMax: prompt rejected"}}},
            "error": "MiniMax: prompt rejected"})
        k3["attempts"].append({
            "task_id": "cgt-doubao-seedance-0001", "state": "succeeded", "late": True, "settled_at": now,
            "file": "clips/late.mp4", "cost_cny": 1.0, "video_url": sign})
        s2["final"] = {"state": "failed", "started_at": now, "finished_at": now, "step": "配音", "step_msg": None,
                       "error": "豆包语音拒绝了请求（45000）：Doubao TTS quota",
                       "error_msg": {"code": "tts.volc.rejected",
                                     "params": {"code": "45000", "detail": {"t": "vendor", "text": "Doubao TTS quota"}}},
                       "detail": "ffmpeg … volc"}
    raw = (Path(root) / "session.json").read_text(encoding="utf-8")
    assert "Seedance" in raw and "volces" in raw, "投毒确实写进去了"
    print("1-3. 会话与投毒 ✓")

    # 4. 逐个接口检查
    clean("openapi", c.get("/openapi.json"), route="/openapi.json")
    clean("healthz", c.get("/healthz"), route="/healthz")
    clean("me", c.get("/auth/me", headers=H), route="/auth/me")
    clean("session.get", c.get(R + "/session", headers=H), route=RT + "/session")
    clean("session.patch", c.patch(R + "/session", headers=H, json={"tier": "a-fast"}), route=RT + "/session")
    r = clean("session.patch.422", c.patch(R + "/session", headers=H, json={"tier": "nope"}), route=RT + "/session")
    assert r.status_code == 422
    # 带厂商字段的请求体被拒（422）；422 会回显请求里的输入，那是用户自己发的词，不算泄露，所以只看状态码
    assert c.patch(R + "/session", headers=H, json={"provider": "x"}).status_code == 422
    clean("session.post", c.post(R + "/session", headers=H, json={}), route=RT + "/session")
    clean("tasks", c.get("/render/tasks", headers=H), route="/render/tasks")
    # 转换任务（真实流程要调大模型，这里直接放一条已失败的任务进内存表，形状与 _start_version 建的一致）
    app_mod._jobs["jvg"] = {"id": "jvg", "user_id": alice, "status": "failed", "log": [], "debug_log": [], "result": None,
                            "quality_report": None, "quality_msg": None, "error": "转换失败", "error_msg": None,
                            "persisted": True, "created_at": "2026-01-01T00:00:00", "work_title": "药", "chapter": "第一章",
                            "chars": 2, "progress": {}, "partial": {"batches_done": 1}, "novel_id": nid,
                            "chapter_id": cid, "version_id": "jvg", "finished_at": "2026-01-01T00:01:00"}
    clean("jobs", c.get("/jobs", headers=H), route="/jobs")
    clean("job", c.get("/jobs/jvg", headers=H), route="/jobs/{job_id}")
    clean("job.partial", c.get("/jobs/jvg/partial", headers=H), route="/jobs/{job_id}/partial", content=True)
    clean("job.404", c.get("/jobs/nope", headers=H), route="/jobs/{job_id}")
    clean("novels", c.get("/novels", headers=H), route="/novels", content=True)
    clean("memory", c.get(f"/novels/{nid}/memory", headers=H), route="/novels/{nid}/memory", content=True)
    clean("assistant", c.get(f"/novels/{nid}/assistant", headers=H), route="/novels/{nid}/assistant", content=True)
    clean("keyframes", c.get(f"/novels/{nid}/chapters/{cid}/versions/v1/keyframes", headers=H),
          route="/novels/{nid}/chapters/{cid}/versions/{vid}/keyframes", content=True)
    clean("voices", c.get(R + "/voices", headers=H), route=RT + "/voices")
    clean("voices.put", c.put(R + "/voices", headers=H, json={"voices": {"x": "nope"}}), route=RT + "/voices")
    clean("compose", c.get(R + "/compose", headers=H), route=RT + "/compose")
    clean("compose.post", c.post(R + "/compose", headers=H, json={"draft": True}), route=RT + "/compose")
    sv = c.get(R + "/session", headers=H).json()
    c1 = sv["clips"][1]["id"]
    clean("run", c.post(R + f"/clips/{c1}/run", headers=H, json={}), route=RT + "/clips/{clip_id}/run")
    clean("run.again", c.post(R + f"/clips/{c1}/run", headers=H, json={}), route=RT + "/clips/{clip_id}/run")
    clean("run.all", c.post(R + "/run", headers=H, json={}), route=RT + "/run")
    clean("cancel", c.post(R + f"/clips/{c1}/cancel", headers=H), route=RT + "/clips/{clip_id}/cancel")
    clean("cancel.409", c.post(R + f"/clips/{a}/cancel", headers=H), route=RT + "/clips/{clip_id}/cancel")
    clean("chosen", c.put(R + f"/clips/{a}/chosen", headers=H, json={"attempt": 0}), route=RT + "/clips/{clip_id}/chosen")
    clean("chosen.bad", c.put(R + f"/clips/{a}/chosen", headers=H, json={"attempt": 9}), route=RT + "/clips/{clip_id}/chosen")
    clean("clip.patch", c.patch(R + f"/clips/{a}", headers=H, json={"mute_native": True}), route=RT + "/clips/{clip_id}")
    r = c.post(R + "/free", headers=H, json={})
    clean("free.post", r, route=RT + "/free")
    fid = r.json()["free"][-1]["id"]
    clean("free.patch", c.patch(R + f"/free/{fid}", headers=H, json={"prompt": "空镜：河面"}), route=RT + "/free/{fid}")
    clean("free.run", c.post(R + f"/free/{fid}/run", headers=H, json={}), route=RT + "/free/{fid}/run")
    clean("free.cancel", c.post(R + f"/free/{fid}/cancel", headers=H), route=RT + "/free/{fid}/cancel")
    clean("free.cancel.409", c.post(R + f"/free/{fid}/cancel", headers=H), route=RT + "/free/{fid}/cancel")
    clean("free.chosen", c.put(R + f"/free/{fid}/chosen", headers=H, json={"attempt": 0}), route=RT + "/free/{fid}/chosen")
    clean("free.delete", c.delete(R + f"/free/{fid}", headers=H), route=RT + "/free/{fid}")
    clean("bgm.delete", c.delete(R + "/bgm/1", headers=H), route=RT + "/bgm/{episode}")
    plan = clean("plan", c.post("/render/plan", headers=H, json={"result": DOC}), route="/render/plan", content=True, models=tuple(render_plan.TIERS))
    assert plan.status_code == 200, plan.text[:300]
    body = plan.json()["plan"]
    assert not P.find_vendor_words(body["estimate"]) and not P.find_vendor_words(body["tiers"]), "plan 的估价与档位里没有厂商词"
    clean("summary", c.get(f"/novels/{nid}/summary", headers=H), route="/novels/{nid}/summary")
    clean("novel", c.get(f"/novels/{nid}", headers=H), route="/novels/{nid}", content=True)
    clean("chapter", c.get(f"/novels/{nid}/chapters/{cid}", headers=H), route="/novels/{nid}/chapters/{cid}", content=True)
    clean("version", c.get(f"/novels/{nid}/chapters/{cid}/versions/v1", headers=H),
          route="/novels/{nid}/chapters/{cid}/versions/{vid}", content=True)
    print("4. 逐个接口 ✓")

    # 5. 具体断言
    sv = c.get(R + "/session", headers=H).json()
    allowed = set(P.ATTEMPT_KEYS) | {"task_id", "error", "error_msg"}
    n_att = 0
    for it in sv["clips"] + sv["free"]:
        for at in it["attempts"]:
            n_att += 1
            assert set(at) <= allowed, (it["id"], sorted(set(at) - allowed))
    assert n_att >= 3
    assert pick(sv, d)["error_msg"]["code"] == "film.vendor.balance", pick(sv, d)["error_msg"]
    assert pick(sv, e)["error_msg"]["code"] == "common.failed_generic", pick(sv, e)["error_msg"]
    rej = [at for at in pick(sv, a)["attempts"] if (at.get("error_msg") or {}).get("code")]
    assert [at["error_msg"]["code"] for at in rej] == ["film.vendor.rejected"], rej
    tasks = c.get("/render/tasks", headers=H).json()["tasks"]
    late = [t for t in tasks if t["state"] == "late"]
    assert len(late) == 1 and late[0]["id"].endswith(P.task_key("cgt-doubao-seedance-0001")), late
    comp = [t for t in tasks if t["kind"] == "compose"]
    assert len(comp) == 1 and comp[0]["state"] == "failed" and comp[0]["step"] is None
    assert comp[0]["error"]["code"] == "tts.vendor.rejected", comp[0]["error"]
    print("5. 具体断言 ✓")

    # 6. 反向对照：管理员接口里有厂商词，普通用户拿不到
    adm = c.get("/admin/service", headers=HA)
    assert adm.status_code == 200 and P.find_vendor_words(adm.json()), "反向对照：/admin/service 里应有厂商词"
    assert all(row.get("vendor_label") for row in adm.json()["film"]["tiers"])
    assert c.get("/admin/service", headers=H).status_code == 403
    legal = {t for t, _, _ in tiers.TIERS} | {None}
    assert tasks and all(t["tier"] in legal for t in tasks), [t["tier"] for t in tasks]
    print("6. 反向对照 ✓")

    # 7. 路由清单
    bin_ = "二进制文件"
    ui = "响应是用户自己的内容或只回显用户的输入，没有服务端生成的错误文字、出片会话、任务"
    EXEMPT = {
        RT + "/files/{path:path}": bin_,
        RT + "/export.zip": bin_,
        "/auth/register": "认证：只回账号字段，错误是登记过的认证消息，不涉及出片",
        "/auth/login": "同上",
        "/novels/{nid}/chapters": "新建章节：" + ui,
        "/novels/{nid}/chapters/{cid}/versions": "新建转换版本：只回任务号；转换任务本身在 /jobs 与 /jobs/{job_id} 里查",
        "/novels/{nid}/chapters/{cid}/versions/{vid}/adopt": "采纳版本：" + ui,
        "/novels/{nid}/chapters/{cid}/digest": "章节摘要：调大模型，输出是用户内容",
        "/novels/{nid}/memory/assets/{kind}/{card_id}": "资产卡增删：" + ui,
        "/novels/{nid}/memory/lifecycle": "记忆增删改：" + ui,
        "/novels/{nid}/memory/lifecycle/{lid}": "同上",
        "/novels/{nid}/memory/plot": "同上",
        "/novels/{nid}/memory/plot/chapters/{cid}": "同上",
        "/novels/{nid}/memory/constraints": "同上",
        "/novels/{nid}/memory/constraints/{kid}": "同上",
        "/render/keyframes": "关键帧批量生成：按分镜出图，响应是图片清单，不含出片会话与厂商字段",
        "/novels/{nid}/chapters/{cid}/versions/{vid}/keyframes/{shot_id}": "关键帧的上传、下载、删除：二进制或只回清单",
        "/novels/{nid}/style-image": "风格图的上传、下载、删除：二进制或只回清单",
        "/novels/{nid}/assistant/messages": "助手：流式输出（SSE），内容是模型对用户说的话",
        "/novels/{nid}/assistant/resume": "助手：流式输出",
        "/novels/{nid}/assistant/undo": "助手：撤销，回用户内容",
    }
    COVERED = set(SEEN_PATHS)
    assert not COVERED & set(EXEMPT), COVERED & set(EXEMPT)
    for r in app_mod.app.routes:
        path = getattr(r, "path", "")
        if not path or path.startswith("/admin") or path in ("/docs", "/redoc", "/docs/oauth2-redirect"):
            continue
        assert path in COVERED or path in EXEMPT, f"新接口 {path} 没有登记：加进守卫的调用，或写明豁免理由"
    print("7. 路由清单 ✓")
    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
