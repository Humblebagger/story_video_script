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

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
