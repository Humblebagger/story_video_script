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

    # 9. 查询已确认成功、下载持续瞬时失败：结果与费用先记在那次尝试上，到期按已知费用结算为失败（恰记一次、放预留、不采用）
    def transient_dl(_st, _dest):
        raise base.TransientError.of("film.fake.throttled")

    def stuck_download(cid):
        """放弃一次、让它查到成功但下载一直瞬时失败；返回 (任务 id, 结算前的 spent)。"""
        spent_ = sess.load(root)["spent_cny"]
        tid_ = abandon(cid)
        fake.download = transient_dl
        for _ in range(8):
            runner.tick()
        att_ = clip(root, cid)["attempts"][-1]
        assert att_["state"] == "abandoned" and att_.get("known_cost_cny", 0) > 0, att_
        assert sess.load(root)["spent_cny"] == spent_, "到期前不入账"
        return tid_, spent_

    c9 = ids[2]
    tid, spent = stuck_download(c9)
    now[0] += 101
    runner.tick()
    fake.download = real_download
    att = clip(root, c9)["attempts"][-1]
    assert att["state"] == "failed" and att["error_msg"]["code"] == "film.download.keeps_failing", att
    assert att["cost_cny"] == att["known_cost_cny"] > 0
    assert sess.load(root)["spent_cny"] == round(spent + att["cost_cny"], 2), "费用恰记一次"
    assert clip(root, c9)["chosen"] is None and sess.view(sess.load(root))["reserved_cny"] == 0
    runner.tick()
    runner.tick()
    assert sess.load(root)["spent_cny"] == round(spent + att["cost_cny"], 2) and runner.watching() == []
    print("9. 查询成功、下载持续瞬时失败 → 按已知费用结算 ✓")

    # 10. 下载瞬时失败之后查询才永久失效：已知费用不丢
    c10 = ids[3]
    tid, spent = stuck_download(c10)

    def gone_poll(_tid):
        raise base.ProviderError.of("film.fake.no_task", id=_tid)

    fake.poll = gone_poll
    now[0] += 101
    runner.tick()
    fake.poll, fake.download = real_poll, real_download
    att = clip(root, c10)["attempts"][-1]
    assert att["state"] == "failed" and att["cost_cny"] == att["known_cost_cny"] > 0, att
    assert sess.load(root)["spent_cny"] == round(spent + att["cost_cny"], 2)
    assert runner.watching() == [] and clip(root, c10)["chosen"] is None
    print("10. 下载瞬时失败后查询失效：已知费用不丢 ✓")

    # 11. 厂商实例建不起来（如密钥被撤）：同样计时，到期写「无法确认」收尾，不再盯
    c11 = ids[4]
    spent = sess.load(root)["spent_cny"]
    tid = abandon(c11)

    def boom():
        raise base.ProviderError.of("film.fake.unknown_model")

    providers.register("fake", boom)
    try:
        runner.tick()
        assert clip(root, c11)["attempts"][-1]["state"] == "abandoned" and runner.watching() == [root]
        now[0] += 101
        runner.tick()
    finally:
        providers.register("fake", lambda: fake)
    att = clip(root, c11)["attempts"][-1]
    assert att["state"] == "failed" and att["error_msg"]["code"] == "film.cancel.lost", att
    assert sess.load(root)["spent_cny"] == spent and sess.view(sess.load(root))["reserved_cny"] == 0
    assert runner.watching() == []
    print("11. 厂商实例建不起来也按期放弃 ✓")

    # 12. 旧轮询的重试错误不写回已取消 / 已重排队的条目
    c12 = ids[5]
    sess.queue_run(root, [c12])
    runner.watch(root)
    runner.tick()
    assert clip(root, c12)["state"] == "running"
    for requeue in (False, True):
        calls = []

        def racing_poll(_tid, _requeue=requeue):
            if not calls:                    # 第一次查询时请求线程插进来取消（或再重排队）；之后每次重试都抛错
                t_, _ = sess.cancel_target(root, c12)
                sess.cancel(root, c12, t_)
                if _requeue:
                    sess.queue_run(root, [c12])
            calls.append(1)
            raise base.TransientError.of("film.fake.throttled")

        fake.poll = racing_poll
        runner._poll(root, fake, sess.load(root), clip(root, c12))
        fake.poll = real_poll
        assert calls and clip(root, c12)["error"] is None, (requeue, clip(root, c12)["error"])
        if not requeue:
            sess.queue_run(root, [c12])
            runner.tick()
            assert clip(root, c12)["state"] == "running"
        else:
            runner.tick()
    drain()
    print("12. 旧轮询的错误不污染当前条目 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
