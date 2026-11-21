#!/usr/bin/env python3
"""出片线程与「不等了」：厂商后来完成 → 下载、记费、不自动采用；与重出并行；厂商后来失败 / 取消；
查询一直失败到期限放弃；下载失败照记生成费；改了设置仍按提交时的设置记费；重启后接着盯。

全程临时目录 + 假厂商，不联网、不花钱。用法: python3 tests/render/test_cancel_runner.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
os.environ["STORYBOARD_VIDEO_PROVIDER"] = "fake"
os.environ["STORYBOARD_DATA_DIR"] = tempfile.mkdtemp()   # 错误记录写临时目录（在导入 render/server 之前）
# 测试不读真实的 backend/.env：load_settings 里的 _load_dotenv 换成空操作（脚本独占进程，无需还原）
import pipeline.config as _pipeline_config  # noqa: E402
_pipeline_config._load_dotenv = lambda *_a, **_k: None

from render import compose, providers, session as sess  # noqa: E402
from render.providers import base  # noqa: E402
from render.providers.fake import FakeVideo  # noqa: E402
from render.runner import Runner  # noqa: E402

YAO = ROOT / "tests" / "real_text_yao" / "output_merged.json"
OWNER = {"user_id": "u", "nid": "n", "cid": "c", "vid": "v"}


def clip(root, cid):
    return next(c for c in sess.load(root)["clips"] if c["id"] == cid)


def main() -> int:
    doc = json.loads(YAO.read_text(encoding="utf-8"))
    fake = FakeVideo(polls_to_finish=3)
    providers.register("fake", lambda: fake)
    tmp = tempfile.TemporaryDirectory()
    data = Path(tmp.name)
    root = data / "users" / "u" / "novels" / "n" / "chapters" / "c" / "render" / "v"
    build = lambda **patch: sess.build(root, doc, owner=OWNER, patch=patch, keyframes={})  # noqa: E731
    s = build(budget_cny=100000)
    ids = [c["id"] for c in s["clips"] if c["id"].endswith("-C01")] + [c["id"] for c in s["clips"]]
    ids = list(dict.fromkeys(ids))                   # 各集第一段在前：它们不等接力

    def builder(r, sess_now, c):
        return compose.request_for(doc, sess_now, c, keyframes={}, relay_frame=sess.relay_frame(r, sess_now, c),
                                   caps=fake.caps(sess_now["model"]), rewrite=fake.rewrite_prompt, style=None)

    now = [0.0]
    runner = Runner(builder, sleep=lambda _s: None, clock=lambda: now[0], abandoned_give_up_sec=100)

    def drain(limit=50):
        for _ in range(limit):
            if not runner.watching():
                return
            runner.tick()
        raise AssertionError("没跑完")

    def abandon(cid):
        """排队 → 出片线程提交 → 用户不等了。返回任务 id。"""
        sess.queue_run(root, [cid])
        runner.watch(root)
        runner.tick()
        assert clip(root, cid)["state"] == "running"
        tid, _ = sess.cancel_target(root, cid)
        sess.cancel(root, cid, tid)
        runner.watch(root)
        return tid

    # 1. 不等了之后厂商照常完成：接着查、下载、记费；段不动、不自动采用；之后不再盯这个会话
    a = ids[0]
    tid = abandon(a)
    runner.tick()
    runner.tick()
    assert clip(root, a)["attempts"][-1]["state"] == "abandoned" and runner.watching() == [root], "厂商还在跑：接着盯"
    runner.tick()
    c = clip(root, a)
    att = c["attempts"][-1]
    assert att["state"] == "succeeded" and att["late"] is True and (root / att["file"]).exists()
    assert att["cost_cny"] > 0 and sess.load(root)["spent_cny"] == att["cost_cny"]
    assert c["state"] == "planned" and c["chosen"] is None
    assert runner.watching() == []
    cost = att["cost_cny"]
    print("1. 厂商照常完成：记费、不自动采用 ✓")

    # 2. 不等了之后马上重出：两次并行推进，旧的那次落账为 late，新的那次正常采用
    tid = abandon(a)
    sess.queue_run(root, [a])
    runner.watch(root)
    drain()
    c = clip(root, a)
    states = [(x["state"], bool(x.get("late"))) for x in c["attempts"]]
    assert states == [("succeeded", True), ("succeeded", True), ("succeeded", False)], states
    assert c["state"] == "done" and c["chosen"] == 2
    assert sess.load(root)["spent_cny"] == round(cost * 3, 2)
    print("2. 与重出并行 ✓")

    # 3. 厂商后来报失败：照实记，不计费
    b = ids[1]
    spent = sess.load(root)["spent_cny"]
    tid = abandon(b)
    fake.fail_with = "OutputVideoSensitiveContentDetected: 审核未通过"
    drain()
    fake.fail_with = None
    att = clip(root, b)["attempts"][-1]
    assert att["state"] == "failed" and att["error"] == "OutputVideoSensitiveContentDetected: 审核未通过"
    assert sess.load(root)["spent_cny"] == spent and clip(root, b)["state"] == "planned"
    print("3. 厂商后来失败 ✓")

    # 4. 厂商那边后来变成已取消：记「已取消」
    tid = abandon(b)
    fake.tasks[tid]["cancelled"] = True
    drain()
    att = clip(root, b)["attempts"][-1]
    assert att["state"] == "cancelled" and att["error_msg"]["code"] == "film.provider.task_cancelled"
    print("4. 厂商后来取消 ✓")

    # 5. 查询一直失败：到期限放弃，记失败并说明无法确认是否计费；不再盯
    tid = abandon(b)
    real_poll = fake.poll

    def down(_tid):
        raise base.TransientError.of("film.fake.throttled")

    fake.poll = down
    runner.tick()
    assert clip(root, b)["attempts"][-1]["state"] == "abandoned" and clip(root, b)["error"] is None, "不往段上写重试提示"
    now[0] += 101
    runner.tick()
    fake.poll = real_poll
    att = clip(root, b)["attempts"][-1]
    assert att["state"] == "failed" and att["error_msg"]["code"] == "film.cancel.lost"
    assert runner.watching() == []
    print("5. 查询一直失败 → 放弃 ✓")

    # 6. 生成成功但下载被拒：生成费照记，那次记失败
    spent = sess.load(root)["spent_cny"]
    tid = abandon(b)
    real_download = fake.download

    def refuse(_st, _dest):
        raise base.ProviderError.of("film.provider.download_failed", status=404)

    fake.download = refuse
    drain()
    fake.download = real_download
    att = clip(root, b)["attempts"][-1]
    assert att["state"] == "failed" and att["error_msg"]["code"] == "film.provider.download_failed"
    assert att["cost_cny"] > 0 and sess.load(root)["spent_cny"] == round(spent + att["cost_cny"], 2)
    print("6. 下载失败照记生成费 ✓")

    # 7. 不等了之后改了分辨率：仍按提交时的分辨率记费
    spent = sess.load(root)["spent_cny"]
    tid = abandon(b)
    build(resolution="480p")
    drain()
    att = clip(root, b)["attempts"][-1]
    assert att["state"] == "succeeded" and att["billing"]["resolution"] == "720p"
    secs = base.request_seconds(att["billing"]["duration"], fake.caps("fake-1"))
    assert att["cost_cny"] == round(secs * 1.0, 2), "720p 是 1 元/秒，480p 是 0.5 元/秒"
    assert sess.load(root)["spent_cny"] == round(spent + att["cost_cny"], 2)
    build(resolution="720p")
    print("7. 按提交时的设置记费 ✓")

    # 8. 进程重启：只有待结算尝试的会话也要续上
    tid = abandon(b)
    fresh = Runner(builder, sleep=lambda _s: None)
    assert fresh.recover(data) == 1 and fresh.watching() == [root]
    for _ in range(10):
        if not fresh.watching():
            break
        fresh.tick()
    assert fresh.watching() == [] and clip(root, b)["attempts"][-1]["state"] == "succeeded"
    assert tid
    print("8. 重启后接着盯 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
