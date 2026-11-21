#!/usr/bin/env python3
"""出片取消（会话层）：还没提交的本地取消、提交中的不能取消、厂商确认取消、「不等了」（那次尝试留着、
计入预留、结果回来后记费且不自动采用）、状态变了要重试、结束标记、重启恢复、自由节点待结算时不能删。

全程临时目录 + 假厂商，不联网、不花钱。用法: python3 tests/render/test_cancel.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

os.environ["STORYBOARD_DATA_DIR"] = tempfile.mkdtemp()   # 数据目录用临时目录（必须在导入 server.*、render.* 之前）
# 测试不读真实的 backend/.env：load_settings 里的 _load_dotenv 换成空操作（脚本独占进程，无需还原）
import pipeline.config as _pipeline_config  # noqa: E402
_pipeline_config._load_dotenv = lambda *_a, **_k: None
os.environ["STORYBOARD_VIDEO_PROVIDER"] = "fake"

from render import free, providers, session as sess  # noqa: E402
from render.providers import base  # noqa: E402
from render.providers.fake import FakeVideo  # noqa: E402
from server.messages import msg  # noqa: E402

YAO = ROOT / "tests" / "real_text_yao" / "output_merged.json"
OWNER = {"user_id": "u", "nid": "n", "cid": "c", "vid": "v"}
FAKE = FakeVideo()
providers.register("fake", lambda: FAKE)


def must_raise(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc as e:
        return e
    raise AssertionError(f"应抛 {exc.__name__}")


def clip(root, cid):
    return next(c for c in sess.load(root)["clips"] if c["id"] == cid)


def request(root, snap):
    s = sess.load(root)
    return base.ClipRequest(prompt=snap["prompt"], model=s["model"], duration=snap["duration"],
                            resolution=s["resolution"])


def start(root, cid):
    """排队 → 提交 → 拿到任务 id（段进入 running）。返回 (任务 id, 请求)。"""
    sess.queue_run(root, [cid])
    snap = sess.begin_submit(root, cid)
    req = request(root, snap)
    tid = FAKE.submit(req)
    sess.submitted(root, cid, tid, None)
    return tid, req


def main() -> int:
    doc = json.loads(YAO.read_text(encoding="utf-8"))
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name) / "render" / "v"
    build = lambda **patch: sess.build(root, doc, owner=OWNER, patch=patch, keyframes={})  # noqa: E731
    s = build(budget_cny=100000)
    a, b, c3, d4 = [x["id"] for x in s["clips"][:4]]
    est = s["clips"][0]["estimate_cny"]

    # 1. 还没提交：本地取消，回到未出片，没有尝试记录、没花钱，记下「已取消」
    sess.queue_run(root, [a])
    assert sess.cancel_target(root, a) == (None, "fake")
    s = sess.cancel(root, a)
    c = clip(root, a)
    assert c["state"] == "planned" and c["attempts"] == [] and s["spent_cny"] == 0.0
    assert c["ended_as"] == "cancelled" and c["ended_at"]
    assert not sess.needs_runner(sess.load(root))
    print("1. 还没提交的本地取消 ✓")

    # 2. 正在提交（已追加「提交中」的尝试、还没拿到任务 id）：不能取消，稍后再试
    sess.queue_run(root, [a])
    snap = sess.begin_submit(root, a)
    e = must_raise(sess.Conflict, sess.cancel_target, root, a)
    assert e.code == "film.cancel.submitting"
    e = must_raise(sess.Conflict, sess.cancel, root, a)
    assert e.code == "film.cancel.submitting"
    req = request(root, snap)
    tid = FAKE.submit(req)
    sess.submitted(root, a, tid, None)
    assert sess.cancel_target(root, a) == (tid, "fake")
    print("2. 提交中不能取消 ✓")

    # 3. 状态在两步之间变了：任务 id 对不上就让用户再试一次，不改会话
    e = must_raise(sess.Conflict, sess.cancel, root, a, "other-task")
    assert e.code == "film.cancel.changed"
    e = must_raise(sess.Conflict, sess.cancel, root, a, None)
    assert e.code == "film.cancel.changed" and clip(root, a)["state"] == "running"
    print("3. 状态变了要重试 ✓")

    # 4. 厂商确认取消：那次尝试记「已取消」、不计费、不用再盯
    s = sess.cancel(root, a, tid, confirmed=True)
    c = clip(root, a)
    att = c["attempts"][-1]
    assert c["state"] == "planned" and c["ended_as"] == "cancelled" and c["error"] is None
    assert att["state"] == "cancelled" and att["cost_cny"] == 0.0 and att["cancelled_at"]
    assert att["error_msg"]["code"] == "film.provider.task_cancelled"
    assert sess.abandoned(s) == [] and not sess.needs_runner(s) and s["spent_cny"] == 0.0
    print("4. 厂商确认取消 ✓")

    # 5. 不等了：这一段立即放开；那次尝试留着（记下提交时的厂商、档位、分辨率、时长、预估），
    #    计入预留与上限，出片线程还要盯；不算「在跑」，所以可以改设置、可以重出
    tid, req = start(root, b)
    s = sess.cancel(root, b, tid)
    c = clip(root, b)
    att = c["attempts"][-1]
    assert c["state"] == "planned" and c["ended_as"] == "cancelled"
    assert att["state"] == "abandoned" and att["task_id"] == tid
    assert att["billing"] == {"provider": "fake", "model": "fake-1", "resolution": "720p",
                              "duration": c["duration"], "estimate_cny": c["estimate_cny"]}
    assert [(h["id"], x["task_id"]) for h, x in sess.abandoned(s)] == [(b, tid)]
    assert sess.needs_runner(s) and not sess.any_in_flight(s)
    assert sess.abandoned_cny(s) == c["estimate_cny"] and sess.view(s)["reserved_cny"] == c["estimate_cny"]
    assert sess.recover(root) is True, "重启后还有待结算的尝试：要接着盯"
    tight = build(budget_cny=round(c["estimate_cny"] * 1.5, 2))       # 不在跑：可以改设置
    assert clip(root, b)["attempts"][-1]["state"] == "abandoned"
    e = must_raise(sess.BudgetExceeded, sess.queue_run, root, [b])
    assert e.code == "film.budget.exceeded", "待结算的那次按预估占着上限"
    build(budget_cny=100000, resolution="480p")
    assert clip(root, b)["attempts"][-1]["billing"]["resolution"] == "720p", "记费按提交时的设置，不跟着后来的设置变"
    build(resolution="720p")
    assert tight["budget_cny"] > 0
    print("5. 不等了 ✓")

    # 6. 厂商后来还是生成完了：下载、记费、标 late，留作可采用的一次；不自动采用，段的状态不动
    st = FAKE.poll(tid)
    files = FAKE.download(st, sess.clip_dest(root, b, tid))
    cost = FAKE.cost(st, req)
    sess.settle_abandoned(root, tid, "succeeded", cost=cost, files=files)
    s = sess.load(root)
    c = clip(root, b)
    att = c["attempts"][-1]
    assert att["state"] == "succeeded" and att["late"] is True and att["cost_cny"] == cost > 0
    assert (root / att["file"]).exists() and att["settled_at"]
    assert c["state"] == "planned" and c["chosen"] is None, "不自动采用"
    assert s["spent_cny"] == cost and sess.abandoned(s) == [] and not sess.needs_runner(s)
    assert sess.view(s)["reserved_cny"] == 0
    s = sess.set_chosen(root, b, len(c["attempts"]) - 1)
    assert clip(root, b)["state"] == "done", "仍可采用"
    print("6. 结果回来：记费、可采用、不自动采用 ✓")

    # 7. 已有采用的段重出时不等了：回到原来的 done，采用不变；厂商后来报失败 / 取消 → 照实记，不计费
    tid2, _ = start(root, b)
    sess.cancel(root, b, tid2)
    c = clip(root, b)
    assert c["state"] == "done" and c["chosen"] == 0 and c["attempts"][-1]["state"] == "abandoned"
    spent = sess.load(root)["spent_cny"]
    sess.settle_abandoned(root, tid2, "failed", error=msg("film.provider.generation_failed"))
    att = clip(root, b)["attempts"][-1]
    assert att["state"] == "failed" and att["error_msg"]["code"] == "film.provider.generation_failed"
    assert sess.load(root)["spent_cny"] == spent and clip(root, b)["state"] == "done"
    tid3, _ = start(root, b)
    sess.cancel(root, b, tid3)
    sess.settle_abandoned(root, tid3, "cancelled", error=msg("film.provider.task_cancelled"))
    assert clip(root, b)["attempts"][-1]["state"] == "cancelled"
    sess.settle_abandoned(root, "no-such-task", "failed", error="x")      # 找不到就什么都不做
    print("7. 有采用的段、厂商后来失败或取消 ✓")

    # 8. 已经在取回、已经结束、不存在：不能取消
    tid4, req4 = start(root, c3)
    sess.poll_update(root, c3, FAKE.poll(tid4))
    assert clip(root, c3)["state"] == "downloading"
    assert must_raise(sess.Conflict, sess.cancel_target, root, c3).code == "film.cancel.finished"
    st4 = FAKE.poll(tid4)
    sess.downloaded(root, c3, FAKE.download(st4, sess.clip_dest(root, c3, tid4)), FAKE.cost(st4, req4))
    assert clip(root, c3)["ended_as"] == "done" and clip(root, c3)["ended_at"]
    assert must_raise(sess.Conflict, sess.cancel_target, root, c3).code == "film.cancel.not_running"
    assert must_raise(sess.Conflict, sess.cancel_target, root, d4).code == "film.cancel.not_running"
    must_raise(sess.NotFound, sess.cancel_target, root, "E99-C99")
    print("8. 不能取消的情况 ✓")

    # 9. 结束标记：失败也记（任务列表「最近结束」用）
    tid5, _ = start(root, d4)
    sess.poll_update(root, d4, base.TaskState(tid5, "failed", error="审核未通过"))
    assert clip(root, d4)["ended_as"] == "failed" and clip(root, d4)["ended_at"]
    print("9. 结束标记 ✓")

    # 10. 视图带通常时长（只是数字，不带厂商名）
    assert sess.view(sess.load(root))["options"]["typical_sec"] == [60, 180]
    print("10. 通常时长进视图 ✓")

    # 11. 自由节点：有一次待结算的尝试时不能删（删了那笔费用就没处记）
    with sess.mutate(root) as s:
        s["free"] = [{"id": "F01", "target": None, "target_shots": None, "target_lost": False, "prompt": "雨夜",
                      "refs": [], "first_frame": None, "duration": 4.0, "estimate_cny": 4.0, "state": "planned",
                      "error": None, "error_msg": None, "uncertain": False, "chosen": None,
                      "created_at": "2026-11-21T00:00:00+00:00",
                      "attempts": [{"task_id": "fake-x", "state": "abandoned", "cost_cny": 0.0, "file": None,
                                    "last_frame": None, "error": None, "error_msg": None,
                                    "at": "2026-11-21T00:00:00+00:00", "fingerprint": None, "first_frame_used": None,
                                    "billing": {"provider": "fake", "model": "fake-1", "resolution": "720p",
                                                "duration": 4.0, "estimate_cny": 4.0}}]}]
        s["free_seq"] = 1
    assert must_raise(sess.Conflict, free.delete, root, "F01").code == "film.free.pending_delete"
    sess.settle_abandoned(root, "fake-x", "failed", error=msg("film.cancel.lost"))
    s = free.delete(root, "F01")
    assert s["free"] == []
    assert est > 0
    print("11. 自由节点待结算时不能删 ✓")

    # 12. 结束标记跨重建保留：成功、失败、取消之后刷新会话（空 patch 的 build）时间与结局不变；重新排队后清空
    root2 = Path(tmp.name) / "render" / "v2"
    s2 = sess.build(root2, doc, owner=OWNER, patch={"budget_cny": 100000}, keyframes={})
    ok, bad, gone = [x["id"] for x in s2["clips"][:3]]
    tid, req = start(root2, ok)
    sess.poll_update(root2, ok, FAKE.poll(tid))
    st = FAKE.poll(tid)
    sess.downloaded(root2, ok, FAKE.download(st, sess.clip_dest(root2, ok, tid)), FAKE.cost(st, req))
    tid, _ = start(root2, bad)
    sess.poll_update(root2, bad, base.TaskState(tid, "failed", error="审核未通过"))
    sess.queue_run(root2, [gone])
    sess.cancel(root2, gone)
    before = {i: (clip(root2, i)["ended_at"], clip(root2, i)["ended_as"]) for i in (ok, bad, gone)}
    assert [v[1] for v in before.values()] == ["done", "failed", "cancelled"], before
    sess.build(root2, doc, owner=OWNER, patch={}, keyframes={}, allow_in_flight=True)
    after = {i: (clip(root2, i).get("ended_at"), clip(root2, i).get("ended_as")) for i in (ok, bad, gone)}
    assert after == before, (before, after)
    sess.queue_run(root2, [gone])
    assert "ended_at" not in clip(root2, gone) and "ended_as" not in clip(root2, gone)
    print("12. 结束标记跨重建保留、重排队清空 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
