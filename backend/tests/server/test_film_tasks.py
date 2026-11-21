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
from server.messages import msg  # noqa: E402
from render import providers, session as render_session  # noqa: E402
from render.providers import base as render_video_base  # noqa: E402
from render.providers.fake import FakeVideo  # noqa: E402
from server import app as app_mod  # noqa: E402
from server import auth, novels  # noqa: E402

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
    tid = pick(s, x)["attempts"][-1]["task_id"]
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
    assert len(late) == 1 and late[0]["id"] == f"v1:{x}:{tid}" and late[0]["cost_cny"] == att["cost_cny"]
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
        raise render_video_base.ProviderError.of("film.fake.unknown_model")

    c.post(R + f"/clips/{x}/run", headers=H, json={})                 # 排队中，还没提交
    runner.tick()                                                     # 提交并跑起来
    assert pick(c.get(R + "/session", headers=H).json(), x)["state"] == "running"
    try:
        providers.register("fake", broken)
        r = c.post(R + f"/clips/{x}/cancel", headers=H)
        assert r.status_code == 200, r.text
        assert r.json()["cancel_outcome"] == "abandoned"
        need = {"providers": list, "models": dict, "resolutions": list, "cny_per_sec": dict, "max_clip_sec": (int, float),
                "max_refs": (int, float), "first_frame": bool, "frame_with_refs": bool, "audio_modes": list,
                "rate_note": (str, dict), "typical_sec": list}
        o = r.json()["options"]
        assert all(isinstance(o.get(k), ty) for k, ty in need.items()) and "default_note" in o, o
        assert o["models"] == {} and o["resolutions"] == []
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
        v = render_session.view(render_session.load(root), True)
        assert all(isinstance(v["options"].get(k), ty) for k, ty in need.items()), v["options"]
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
               "elapsed_sec", "typical_sec", "ended_at", "cost_cny"}
    for t in tasks():
        assert set(t) <= allowed, set(t) - allowed
    print("9. 任务列表不泄露厂商、地址、密钥 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
