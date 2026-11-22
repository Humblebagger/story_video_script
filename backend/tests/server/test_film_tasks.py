#!/usr/bin/env python3
"""出片的取消接口与任务列表接口：只看得到本人的；排队中 / 生成中 / 最近结束 / 取消后才出结果；
不带厂商与档位；还没提交的本地取消、厂商确认取消、不等了；不能取消的情况；自由节点。

全程临时数据目录 + 假厂商，不联网、不花钱。用法: python3 tests/server/test_film_tasks.py
"""
import copy
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import _noenv  # noqa: E402,F401  测试不读真实 .env

_TMP = tempfile.TemporaryDirectory()
os.environ["STORYBOARD_DATA_DIR"] = _TMP.name     # 必须在导入 server.* 之前

# 测试不读真实的 backend/.env：load_settings 里的 _load_dotenv 换成空操作（脚本独占进程，无需还原）
import pipeline.config as _pipeline_config  # noqa: E402
_pipeline_config._load_dotenv = lambda *_a, **_k: None
os.environ["STORYBOARD_VIDEO_PROVIDER"] = "fake"
os.environ["STORYBOARD_RENDER_RUNNER"] = "0"     # 不起后台线程，测试里手动 tick

from fastapi.testclient import TestClient  # noqa: E402
from server.messages import msg, with_ref  # noqa: E402
from render import providers, session as render_session  # noqa: E402
from render.providers import base as render_video_base  # noqa: E402
from render.providers.fake import FakeVideo  # noqa: E402
from server import app as app_mod  # noqa: E402
from server import auth, novels, public  # noqa: E402

FAKE = FakeVideo(polls_to_finish=2)
providers.register("fake", lambda: FAKE)
DOC = json.loads((ROOT / "tests" / "real_text_yao" / "output_merged.json").read_text(encoding="utf-8"))


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
    runner = app_mod._render_runner
    runner.sleep = lambda _s: None
    c = TestClient(app_mod.app)
    alice = auth.register("alice", "secret1")["id"]
    bob = auth.register("bob", "secret2")["id"]
    H = {"Authorization": f"Bearer {auth.issue_token(alice)}"}
    HB = {"Authorization": f"Bearer {auth.issue_token(bob)}"}
    nid = novels.create_novel(alice, "药")["id"]
    cid = novels.create_chapter(alice, nid, "第一章", text="原文")["id"]
    novels.create_version(alice, nid, cid, "v1", {}, "原文")
    novels.update_version_state(alice, nid, cid, "v1", "succeeded", result=copy.deepcopy(DOC))
    R = f"/novels/{nid}/chapters/{cid}/versions/v1/render"
    root = novels.render_dir(alice, nid, cid, "v1")
    tasks = lambda h=H: c.get("/render/tasks", headers=h).json()["tasks"]  # noqa: E731

    # 1. 要登录；没有出片会话时是空的；视图带通常时长
    assert c.get("/render/tasks").status_code == 401
    assert tasks() == []
    s = c.post(R + "/session", headers=H, json={"budget_cny": 100000}).json()
    assert s["options"]["typical_sec"] == [60, 180]
    x = s["clips"][0]["id"]
    assert tasks() == [], "只是建了会话：没有任务"
    print("1. 登录与空列表 ✓")

    # 2. 排队中：本人看得到（章节、片段、已等、通常时长），别人看不到；不带厂商与档位
    r = c.post(R + f"/clips/{x}/run", headers=H, json={})
    assert r.status_code == 200, r.text
    (t,) = tasks()
    assert t["id"] == f"v1:{x}" and t["item_id"] == x and t["kind"] == "clip" and t["state"] == "queued"
    assert (t["novel_id"], t["chapter_id"], t["version_id"]) == (nid, cid, "v1")
    assert (t["work_title"], t["chapter"]) == ("药", "第一章")
    assert t["typical_sec"] == [60, 180] and isinstance(t["elapsed_sec"], int) and t["elapsed_sec"] >= 0
    assert t["ended_at"] is None and t["cost_cny"] is None
    assert tasks(HB) == [], "别人的任务看不到"
    raw = c.get("/render/tasks", headers=H).text
    assert "fake" not in raw and "provider" not in raw and "model" not in raw, raw
    print("2. 排队中、只对本人可见、不带厂商 ✓")

    # 3. 还没提交就取消：不找厂商、不花钱，回到未出片；任务列表里记「已取消」
    assert c.post(R + f"/clips/{x}/cancel", headers=HB).status_code == 404, "别人不能取消"
    r = c.post(R + f"/clips/{x}/cancel", headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["cancel_outcome"] == "dequeued" and pick(r.json(), x)["state"] == "planned"
    assert FAKE.cancel_calls == [] and FAKE.submitted == [] and r.json()["spent_cny"] == 0
    (t,) = tasks()
    assert t["state"] == "cancelled" and t["ended_at"] and t["id"] == f"v1:{x}"
    print("3. 还没提交的取消 ✓")

    # 4. 已提交、厂商取消不了：不等了。这一段立即放开；那次按预估占着预留；结果回来后列表里多一条「取消后才出结果」
    c.post(R + f"/clips/{x}/run", headers=H, json={})
    runner.tick()
    assert tasks()[0]["state"] == "running"
    r = c.post(R + f"/clips/{x}/cancel", headers=H)
    assert r.status_code == 200, r.text
    s = r.json()
    tid = render_session.load(root)["clips"][0]["attempts"][-1]["task_id"]       # 厂商任务号（视图里只有短键）
    assert pick(s, x)["attempts"][-1]["task_id"] == public.task_key(tid) != tid
    assert s["cancel_outcome"] == "abandoned" and FAKE.cancel_calls == [tid]
    assert pick(s, x)["state"] == "planned" and pick(s, x)["attempts"][-1]["state"] == "abandoned"
    assert s["reserved_cny"] == pick(s, x)["estimate_cny"] and runner.watching() == [root]
    assert [t["state"] for t in tasks()] == ["cancelled"]
    drain()
    s = c.get(R + "/session", headers=H).json()
    att = pick(s, x)["attempts"][-1]
    assert att["state"] == "succeeded" and att["late"] is True and s["spent_cny"] == att["cost_cny"] > 0
    assert pick(s, x)["chosen"] is None and pick(s, x)["state"] == "planned" and s["reserved_cny"] == 0
    late = [t for t in tasks() if t["state"] == "late"]
    assert len(late) == 1 and late[0]["id"] == f"v1:{x}:{public.task_key(tid)}" and late[0]["cost_cny"] == att["cost_cny"]
    assert late[0]["item_id"] == x
    print("4. 不等了 → 后来出了结果 ✓")

    # 5. 已提交、厂商确认取消：那次记「已取消」，不计费，不用再盯
    FAKE.cancel_ok = True
    c.post(R + f"/clips/{x}/run", headers=H, json={})
    runner.tick()
    spent = s["spent_cny"]
    r = c.post(R + f"/clips/{x}/cancel", headers=H)
    assert r.status_code == 200 and r.json()["cancel_outcome"] == "cancelled", r.text
    assert pick(r.json(), x)["attempts"][-1]["state"] == "cancelled" and r.json()["spent_cny"] == spent
    runner.tick()
    assert runner.watching() == []
    FAKE.cancel_ok = False
    print("5. 厂商确认取消 ✓")

    # 6. 不能取消的情况：不在跑 409、没有这一段 404、正在提交 409、已经在取回 409
    r = c.post(R + f"/clips/{x}/cancel", headers=H)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "film.cancel.not_running", r.text
    assert c.post(R + "/clips/E99-C99/cancel", headers=H).status_code == 404
    c.post(R + f"/clips/{x}/run", headers=H, json={})
    render_session.begin_submit(root, x)
    r = c.post(R + f"/clips/{x}/cancel", headers=H)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "film.cancel.submitting", r.text
    render_session.submit_failed(root, x, msg("film.provider.failed"))
    c.post(R + f"/clips/{x}/run", headers=H, json={})
    runner.tick()
    runner.tick()
    runner.tick()
    assert pick(c.get(R + "/session", headers=H).json(), x)["state"] == "downloading"
    r = c.post(R + f"/clips/{x}/cancel", headers=H)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "film.cancel.finished", r.text
    drain()
    done = [t for t in tasks() if t["id"] == f"v1:{x}"]
    assert len(done) == 1 and done[0]["state"] == "done" and done[0]["elapsed_sec"] >= 0
    print("6. 不能取消的情况 ✓")

    # 7. 自由节点同一套
    c.post(R + "/free", headers=H, json={})
    c.patch(R + "/free/F01", headers=H, json={"prompt": "空镜：河面"})
    r = c.post(R + "/free/F01/run", headers=H, json={})
    assert r.status_code == 200, r.text
    live = [t for t in tasks() if t["ended_at"] is None]
    assert [(t["item_id"], t["kind"], t["state"]) for t in live] == [("F01", "free", "queued")]
    assert tasks()[0]["item_id"] == "F01", "在跑的排在最近结束的前面"
    r = c.post(R + "/free/F01/cancel", headers=H)
    assert r.status_code == 200 and r.json()["cancel_outcome"] == "dequeued", r.text
    assert pick(r.json(), "F01")["state"] == "planned"
    print("7. 自由节点 ✓")

    # 8. 厂商建不起来（密钥被撤、配置变了）：取消照常落账、返回 200 与取消结局，后台跟踪一致
    def broken():
        raise render_video_base.ProviderError.of("film.settings.no_model")

    c.post(R + f"/clips/{x}/run", headers=H, json={})                 # 排队中，还没提交
    runner.tick()                                                     # 提交并跑起来
    assert pick(c.get(R + "/session", headers=H).json(), x)["state"] == "running"
    try:
        providers.register("fake", broken)
        r = c.post(R + f"/clips/{x}/cancel", headers=H)
        assert r.status_code == 200, r.text
        assert r.json()["cancel_outcome"] == "abandoned"
        need = {"resolutions": list, "cny_per_sec": dict, "max_clip_sec": (int, float),
                "max_refs": (int, float), "first_frame": bool, "frame_with_refs": bool, "audio_modes": list,
                "rate_note": (str, dict), "typical_sec": list}
        o = r.json()["options"]
        assert isinstance(o.get("tiers"), list)
        assert all(isinstance(o.get(k), ty) for k, ty in need.items()) and not {"providers", "models", "default_note"} & set(o), o
        assert o["tiers"] == [] and o["resolutions"] == []
        s = render_session.load(root)
        assert pick(s, x)["state"] == "done" and pick(s, x)["attempts"][-1]["state"] == "abandoned"
        assert runner.watching() == [root], "不等了的那次仍要盯"
        # 本地排队取消：没有厂商调用，也不能因视图失败而报错
        s = render_session.queue_run(root, [x]) and render_session.load(root)
        assert pick(s, x)["state"] == "queued"
        r = c.post(R + f"/clips/{x}/cancel", headers=H)
        assert r.status_code == 200 and r.json()["cancel_outcome"] == "dequeued", r.text
        assert pick(render_session.load(root), x)["state"] == "done" and runner.watching() == [root]
        # 厂商未注册（配置指向不存在的厂商）：同样结构完整
        with render_session.mutate(root) as ms:
            ms["provider"] = "no-such-vendor"
        v = render_session.view(render_session.load(root), True)       # 会话层的完整视图仍带厂商清单
        assert all(isinstance(v["options"].get(k), ty) for k, ty in {"providers": list, "models": dict, **need}.items()), v["options"]
        with render_session.mutate(root) as ms:
            ms["provider"] = "fake"
    finally:
        providers.register("fake", lambda: FAKE)
    drain()
    print("8. 厂商建不起来时取消仍成功 ✓")

    # 10. 取消种类校验（expect）：确认框打开期间状态迁移，服务端在锁内按实际种类判定，对不上 409 且什么都不动
    calls = len(FAKE.cancel_calls)
    c.post(R + f"/clips/{x}/run", headers=H, json={})                 # 排队中：可真取消
    r = c.post(R + f"/clips/{x}/cancel", headers=H, json={"expect": "paid"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "film.cancel.kind_changed", r.text
    assert pick(render_session.load(root), x)["state"] == "queued"
    assert c.post(R + f"/clips/{x}/cancel", headers=H, json={"expect": "bogus"}).status_code == 422
    runner.tick()                                                     # 确认框开着时：已提交、生成中
    assert pick(c.get(R + "/session", headers=H).json(), x)["state"] == "running"
    r = c.post(R + f"/clips/{x}/cancel", headers=H, json={"expect": "free"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "film.cancel.kind_changed", r.text
    assert "厂商" not in r.text and "fake" not in r.text
    s = render_session.load(root)
    assert pick(s, x)["state"] == "running" and pick(s, x)["attempts"][-1]["state"] == "running"
    assert len(FAKE.cancel_calls) == calls, "种类不符不得请厂商取消"
    r = c.post(R + f"/clips/{x}/cancel", headers=H, json={"expect": "paid"})
    assert r.status_code == 200 and r.json()["cancel_outcome"] == "abandoned", r.text
    drain()
    c.post(R + f"/clips/{x}/run", headers=H, json={})
    r = c.post(R + f"/clips/{x}/cancel", headers=H, json={"expect": "free"})
    assert r.status_code == 200 and r.json()["cancel_outcome"] == "dequeued", r.text
    r = c.post(R + "/free/F01/cancel", headers=H, json={"expect": "paid"})   # 自由节点同一套（不在跑也先判 409）
    assert r.status_code in (409,), r.text
    c.post(R + "/free/F01/run", headers=H, json={})
    r = c.post(R + "/free/F01/cancel", headers=H, json={"expect": "paid"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "film.cancel.kind_changed", r.text
    assert c.post(R + "/free/F01/cancel", headers=H, json={"expect": "free"}).status_code == 200
    print("10. 取消种类校验 ✓")

    # 11. 服务端时间：会话视图与任务列表都带 server_now（带时区），供浏览器校准时钟
    from datetime import datetime
    for raw in (c.get(R + "/session", headers=H).json()["server_now"],
                c.get("/render/tasks", headers=H).json()["server_now"]):
        assert datetime.fromisoformat(raw).utcoffset() is not None, raw
    print("11. server_now ✓")

    # 9. 任务列表不带厂商、档位、签名地址、密钥：在跑、完成、取消后才出结果三种响应都查，并核对字段白名单
    SENT = {"vendor": "zz-vendor-sentinel", "model": "zz-model-sentinel",
            "url": "https://cdn.example.test/v.mp4?X-Amz-Signature=zz-sig-sentinel", "key": "sk-zz-key-sentinel"}
    orig = render_session.load(root)
    orig = (orig["provider"], orig["model"])
    with render_session.mutate(root) as s:
        s["provider"] = SENT["vendor"]
        s["model"] = SENT["model"]
        s["_secret"] = SENT["key"]
        for it in render_session.items(s):
            for a in it["attempts"]:
                a.update(video_url=SENT["url"], last_frame_url=SENT["url"])
                a["billing"] = {"provider": SENT["vendor"], "model": SENT["model"], "resolution": "720p",
                                "duration": 4.0, "estimate_cny": 4.0}
        s["clips"][2].update(ended_at=render_session._now(), ended_as="done")     # 最近完成
        s["clips"][1]["state"] = "running"
        s["clips"][1]["queued_at"] = render_session._now()
        s["clips"][1]["attempts"] = [{"task_id": "t-run", "state": "running", "cost_cny": 0.0, "file": None,
                                      "last_frame": None, "error": None, "error_msg": None,
                                      "at": render_session._now(), "fingerprint": None, "first_frame_used": None,
                                      "video_url": SENT["url"],
                                      "billing": {"provider": SENT["vendor"], "model": SENT["model"]}}]
    raw = c.get("/render/tasks", headers=H).text
    got = {t["state"] for t in tasks()}
    assert {"running", "done", "late"} <= got, got
    for v in SENT.values():
        assert v not in raw, v
    allowed = {"id", "novel_id", "chapter_id", "version_id", "work_title", "chapter", "item_id", "kind", "state",
               "elapsed_sec", "typical_sec", "ended_at", "cost_cny", "cancel", "error", "step", "shot_ids"}
    for t in tasks():
        assert set(t) <= allowed, set(t) - allowed
    print("9. 任务列表不泄露厂商、地址、密钥 ✓")

    # 以下几项接在哨兵测试之后：先把会话还原成正常的厂商与模型，去掉哨兵地址
    with render_session.mutate(root) as s:
        s["provider"], s["model"] = orig
        s.pop("_secret", None)
        for it in render_session.items(s):
            for a in it["attempts"]:
                a.pop("video_url", None)
                a.pop("last_frame_url", None)
            if it["state"] in render_session.IN_FLIGHT:
                it["state"] = "planned"

    # 12. 取消种类：还没提交是 free，已提交是 paid；结束的没有
    z = c.get(R + "/session", headers=H).json()["clips"][2]["id"]
    row = lambda iid: next(t for t in tasks() if t["id"] == f"v1:{iid}")  # noqa: E731
    c.post(R + f"/clips/{z}/run", headers=H, json={})
    assert row(z)["cancel"] == "free" and row(z)["error"] is None and row(z)["step"] is None
    sess_z = pick(c.get(R + "/session", headers=H).json(), z)
    assert row(z)["shot_ids"] == sess_z["shots"] and len(sess_z["shots"]) >= 1, "带上这一段含哪些镜头"
    runner.tick()
    assert row(z)["state"] == "running" and row(z)["cancel"] == "paid"
    FAKE.cancel_ok = True
    assert c.post(R + f"/clips/{z}/cancel", headers=H).json()["cancel_outcome"] == "cancelled"
    FAKE.cancel_ok = False
    assert row(z)["state"] == "cancelled" and row(z)["cancel"] is None
    print("12. 取消种类 ✓")

    # 13. 失败原因：能给普通用户看的才给；带厂商原话或厂商名的不给（列表里只写失败）
    def fail_with(err):
        with render_session.mutate(root) as ss:
            cz = next(k for k in ss["clips"] if k["id"] == z)
            cz["state"] = "failed"
            if isinstance(err, dict) and "error_msg" in err:        # 旧数据：直接写成存档里的样子
                cz.update(err)
            else:
                render_session.set_error(cz, err)
            render_session._ended(cz, "failed")
        return row(z)

    t = fail_with(msg("film.download.not_playable"))
    assert t["state"] == "failed" and t["error"]["code"] == "film.download.not_playable" and t["error"]["message"]
    # 旧代码归一：带厂商名的旧代码经出口换成中性代码，文字里没有厂商词
    t = fail_with({"error": "余额不足（MiniMax）", "error_msg": {"code": "film.minimax.insufficient_balance", "params": {}}})
    assert t["error"]["code"] == "film.vendor.balance" and not public.find_vendor_words(t["error"]), t["error"]
    # 只有文字、没有代码：通用文案；什么都没有：null
    t = fail_with("视频服务（MiniMax）超时")
    assert t["error"]["code"] == "common.failed_generic" and not public.find_vendor_words(t["error"]), t["error"]
    assert fail_with("fake-1 不可用")["error"]["code"] == "common.failed_generic"
    assert fail_with(None)["error"] is None
    with render_session.mutate(root) as ss:
        cz = next(k for k in ss["clips"] if k["id"] == z)
        cz["error_msg"] = {"code": "film.download.not_playable", "params": {"detail": {"t": "vendor", "text": "x"}}}
        cz["error"] = "下载的文件不能播放"
    assert row(z)["error"]["code"] == "film.download.not_playable" and not public.find_vendor_words(row(z)["error"]), "厂商原话被丢弃"
    print("13. 失败原因 ✓")

    # 14. 成片合成也在队列里：合成中带步骤、不能取消、没有通常时长；结束后带结局与失败原因；一个版本只有一条
    render_session.begin_compose(root, fingerprint="fp", tts_cny=0.0, draft=True)
    t = row("compose")
    assert (t["kind"], t["item_id"], t["state"]) == ("compose", "compose", "running")
    assert t["step"]["code"] == "compose.step.start" and t["cancel"] is None and t["typical_sec"] is None
    assert isinstance(t["elapsed_sec"], int) and t["ended_at"] is None and tasks()[0]["id"] == "v1:compose"
    assert t["shot_ids"] == [] and (t["work_title"], t["chapter"]) == ("药", "第一章")
    assert tasks(HB) == []
    render_session.compose_failed(root, msg("compose.interrupted"))
    t = row("compose")
    assert t["state"] == "failed" and t["ended_at"] and t["error"]["code"] == "compose.interrupted" and t["step"] is None
    render_session.begin_compose(root, fingerprint="fp", tts_cny=0.0, draft=True)
    render_session.compose_done(root, ["final/a.mp4"], "ok")
    assert [(t["state"], t["error"]) for t in tasks() if t["kind"] == "compose"] == [("done", None)]
    print("14. 成片合成 ✓")

    # 15. 已结束的最多返回这么多条，最新的在前
    ended = [t for t in tasks() if t["ended_at"]]
    assert len(ended) >= 3 and [t["ended_at"] for t in ended] == sorted((t["ended_at"] for t in ended), reverse=True)
    app_mod.FILM_RECENT_MAX = 2
    assert [t["id"] for t in tasks() if t["ended_at"]] == [t["id"] for t in ended[:2]]
    app_mod.FILM_RECENT_MAX = 30
    print("15. 已结束的条数上限 ✓")

    # 16. 转换任务（/jobs）带结束时间与失败原因；同样不带厂商名
    job = {"id": "jb1", "user_id": alice, "status": "queued", "log": [], "progress": {}, "created_at": "2026-11-21T00:00:00+00:00"}

    def boom(*_a, **_k):
        job["status"] = "failed"
        render_session.set_error(job, msg("compose.interrupted"))
        raise RuntimeError("x")

    saved = app_mod._execute
    app_mod._execute = boom
    try:
        app_mod._run_version_job(job, alice, nid, cid, "原文", type("P", (), {"work_title": "药"})(), False)
    except RuntimeError:
        pass
    finally:
        app_mod._execute = saved
    assert job.get("finished_at"), "转换结束（哪怕抛异常）都记结束时间"
    app_mod._jobs["jb1"] = job
    (j,) = [x for x in c.get("/jobs", headers=H).json()["jobs"] if x["id"] == "jb1"]
    assert j["finished_at"] == job["finished_at"] and j["error_msg"]["code"] == "compose.interrupted"
    render_session.set_error(job, "大模型（MiniMax）超时")
    (j,) = [x for x in c.get("/jobs", headers=H).json()["jobs"] if x["id"] == "jb1"]
    assert j["error_msg"] is None
    print("16. 转换任务的结束时间与失败原因 ✓")

    # 16b. 参考编号：通过筛选的消息保留合法的顶层 ref，其它内部字段不放行（/jobs 与 /render/tasks 都是）
    job["status"] = "failed"
    render_session.set_error(job, with_ref(msg("compose.interrupted"), "AB12CD"))
    job["error_msg"]["internal_path"] = "/srv/x"
    (j,) = [x for x in c.get("/jobs", headers=H).json()["jobs"] if x["id"] == "jb1"]
    assert j["error_msg"]["ref"] == "AB12CD" and "internal_path" not in j["error_msg"], j["error_msg"]
    with render_session.mutate(root) as ss:
        cz = next(k for k in ss["clips"] if k["id"] == z)
        render_session.set_error(cz, with_ref(msg("film.download.not_playable"), "EF34GH"))
        cz["error_msg"]["internal_path"] = "/srv/y"
    assert row(z)["error"]["ref"] == "EF34GH" and "internal_path" not in row(z)["error"], row(z)["error"]
    print("16b. 失败原因保留参考编号 ✓")

    # 16c. 保留窗口：超过十分钟但不足一天的还在，超过一天的不在（片段、迟到结果、合成都一样）
    def ago(sec):
        return (datetime.now(timezone.utc) - timedelta(seconds=sec)).isoformat(timespec="seconds")

    def set_clip(iid, **kv):
        with render_session.mutate(root) as ss:
            next(k for k in ss["clips"] + ss["free"] if k["id"] == iid).update(kv)

    def late_row():
        return [t for t in tasks() if t["state"] == "late"]

    def set_late(settled):
        with render_session.mutate(root) as ss:
            att = next(k for k in ss["clips"] if k["id"] == x)["attempts"]
            for a in att:
                if a.get("late"):
                    a["settled_at"] = settled

    for age, shown in ((700, True), (86400 - 60, True), (86400 + 60, False)):
        set_clip(z, state="failed", ended_as="failed", ended_at=ago(age))
        assert any(t["id"] == f"v1:{z}" for t in tasks()) is shown, f"片段结束 {age} 秒前"
        set_late(ago(age))
        assert bool(late_row()) is shown, f"迟到结果 {age} 秒前"
    # 旧文件修改时间：先留一条 700 秒前结束、应当可见的记录；会话文件一天前就没改过、也没人盯着 → 整个会话不读
    set_clip(z, state="failed", ended_as="failed", ended_at=ago(700))
    assert any(t["id"] == f"v1:{z}" for t in tasks()), "700 秒前结束的应当可见"
    app_mod._render_runner._forget(root)
    os.utime(root / "session.json", (time.time() - 90000, time.time() - 90000))
    assert app_mod._render_runner.watching() == [] and not any(t["item_id"] == z for t in tasks())
    set_clip(z, state="failed", ended_as="failed", ended_at=ago(700))   # 重新写会话，文件时间刷新
    assert any(t["id"] == f"v1:{z}" for t in tasks())
    print("16c. 保留窗口（片段、迟到结果、旧文件时间）✓")

    # 合成：步骤文字里的厂商名过滤；结束后同一窗口
    with render_session.mutate(root) as ss:
        ss["final"] = {}
    render_session.begin_compose(root, fingerprint="fp2", tts_cny=0.0, draft=True)
    assert row("compose")["step"]["code"] == "compose.step.start"
    with render_session.mutate(root) as ss:
        ss["final"]["step"], ss["final"]["step_msg"] = "正在向 MiniMax 提交", None
    assert row("compose")["state"] == "running" and row("compose")["step"] is None, "步骤没有代码时为 null"
    with render_session.mutate(root) as ss:
        ss["final"]["step"] = "视频服务 fake-1 合成"
    assert row("compose")["step"] is None, "会话的模型名也算"
    render_session.compose_done(root, ["final/a.mp4"], "ok")
    for age, shown in ((700, True), (86400 + 60, False)):
        with render_session.mutate(root) as ss:
            ss["final"]["finished_at"] = ago(age)
        assert any(t["id"] == "v1:compose" for t in tasks()) is shown, f"合成结束 {age} 秒前"
    print("16d. 合成的保留窗口与步骤过滤 ✓")

    # 16e. 列表里的取消种类：提交中、下载中为 null；已提交为 paid；自由节点同一套
    set_clip(z, state="queued", ended_at=None, ended_as=None, queued_at=ago(5), attempts=[{"state": "submitting"}])
    assert row(z)["cancel"] is None, "提交中不能取消"
    set_clip(z, state="downloading", attempts=[{"state": "running", "task_id": "t1"}])
    assert row(z)["state"] == "downloading" and row(z)["cancel"] is None, "下载中不能取消"
    set_clip(z, state="running", attempts=[{"state": "running", "task_id": "t1"}])
    assert row(z)["cancel"] == "paid"
    set_clip(z, state="planned", attempts=[])
    assert any(k["id"] == "F01" for k in render_session.load(root)["free"])
    set_clip("F01", state="queued", queued_at=ago(5), ended_at=None, ended_as=None, attempts=[])
    assert row("F01")["kind"] == "free" and row("F01")["cancel"] == "free"
    set_clip("F01", state="queued", attempts=[{"state": "submitting"}])
    assert row("F01")["cancel"] is None
    set_clip("F01", state="downloading", attempts=[{"state": "running", "task_id": "t2"}])
    assert row("F01")["cancel"] is None
    set_clip("F01", state="running", attempts=[{"state": "running", "task_id": "t2"}])
    assert row("F01")["cancel"] == "paid"
    set_clip("F01", state="planned", attempts=[])
    print("16e. 列表里的取消种类 ✓")

    # 17. 名字取现在的：小说、章节改名后队列跟着变；章节删掉后转换任务留原名并标已删除，出片任务随会话一起消失
    job.update(novel_id=nid, chapter_id=cid, work_title="旧书名", chapter="旧章名")
    novels.update_novel(alice, nid, title="药（修订）")
    novels.update_chapter(alice, nid, cid, title="第一章 华老栓")
    (j,) = [x for x in c.get("/jobs", headers=H).json()["jobs"] if x["id"] == "jb1"]
    assert (j["work_title"], j["chapter"], j["deleted"]) == ("药（修订）", "第一章 华老栓", False)
    assert {(t["work_title"], t["chapter"]) for t in tasks()} == {("药（修订）", "第一章 华老栓")}
    novels.delete_chapter(alice, nid, cid)
    (j,) = [x for x in c.get("/jobs", headers=H).json()["jobs"] if x["id"] == "jb1"]
    assert (j["work_title"], j["chapter"], j["deleted"]) == ("药（修订）", "旧章名", True)
    assert tasks() == [], "章节删了，它的出片任务不再出现（不报错）"
    del app_mod._jobs["jb1"]
    print("17. 现在的名字与已删除 ✓")

    # 18. 转换执行前的读取失败（排队期间章节或小说被删）：任务转为失败、带登记过的原因与结束时间，不重建已删除的目录
    for what in ("chapter", "novel"):
        n2 = novels.create_novel(alice, "书" + what)["id"]
        c2 = novels.create_chapter(alice, n2, "第一章", text="原文")["id"]
        novels.create_version(alice, n2, c2, "jq-" + what, {}, "原文")
        jq = {"id": "jq-" + what, "user_id": alice, "status": "queued", "log": [], "debug_log": [], "progress": {},
              "created_at": "2026-11-21T00:00:01+00:00", "novel_id": n2, "chapter_id": c2,
              "work_title": "书" + what, "chapter": "第一章"}
        app_mod._jobs[jq["id"]] = jq
        if what == "chapter":
            novels.delete_chapter(alice, n2, c2)
        else:
            novels.delete_novel(alice, n2)
        app_mod._run_version_job(jq, alice, n2, c2, "原文", type("P", (), {"work_title": "x"})(), False)
        (j,) = [x for x in c.get("/jobs", headers=H).json()["jobs"] if x["id"] == jq["id"]]
        assert j["status"] == "failed" and j["finished_at"] and j["deleted"] is True, (what, j)
        assert j["error_msg"] and j["error_msg"]["code"] and j["error_msg"]["code"].endswith("not_found"), j["error_msg"]
        assert not [x for x in c.get("/jobs", headers=H).json()["jobs"]
                    if x["status"] in ("queued", "running") and x["id"] == jq["id"]], "不计入进行中"
        assert not novels._chapter_dir(alice, n2, c2).exists(), "不重建已删除的目录"
        if what == "novel":
            assert not novels._novel_dir(alice, n2).exists()
        del app_mod._jobs[jq["id"]]
    print("18. 排队期间删除章节或小说 ✓")

    # 18b. 真实 _execute 的初始化失败（置 running 之后、进 try 之前）：任务也要收尾为失败，不能停在进行中
    for what in ("deleted", "settings"):
        n2 = novels.create_novel(alice, "初始化" + what)["id"]
        c2 = novels.create_chapter(alice, n2, "第一章", text="原文")["id"]
        novels.create_version(alice, n2, c2, "ji-" + what, {}, "原文")
        ji = {"id": "ji-" + what, "user_id": alice, "status": "queued", "log": [], "debug_log": [], "progress": {},
              "created_at": "2026-11-21T00:00:02+00:00", "novel_id": n2, "chapter_id": c2,
              "work_title": "初始化" + what, "chapter": "第一章"}
        app_mod._jobs[ji["id"]] = ji
        real_ctx, real_ls = novels.novel_context, app_mod.load_settings
        if what == "deleted":      # 前置读取都完成后、首次状态落盘前，章节被删 → persist 抛 NotFound
            def ctx_then_delete(*a, **k):
                r = real_ctx(*a, **k)
                novels.delete_chapter(alice, n2, c2)
                return r
            novels.novel_context = ctx_then_delete
        else:                      # 配置解析异常
            def bad_settings(*a, **k):
                raise ValueError("配置坏了")
            app_mod.load_settings = bad_settings
        try:
            try:
                app_mod._run_version_job(ji, alice, n2, c2, "原文", type("P", (), {"work_title": "x"})(), False)
            except Exception:
                pass
        finally:
            novels.novel_context, app_mod.load_settings = real_ctx, real_ls
        (j,) = [x for x in c.get("/jobs", headers=H).json()["jobs"] if x["id"] == ji["id"]]
        assert j["status"] == "failed" and j["finished_at"] and j["error_msg"] and j["error_msg"]["code"], (what, j)
        assert not [x for x in c.get("/jobs", headers=H).json()["jobs"]
                    if x["status"] in ("queued", "running") and x["id"] == ji["id"]], "不计入进行中"
        if what == "deleted":
            assert not novels._chapter_dir(alice, n2, c2).exists(), "不重建已删除的目录"
        del app_mod._jobs[ji["id"]]
    print("18b. 初始化失败也收尾为失败 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
