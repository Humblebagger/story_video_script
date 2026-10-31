#!/usr/bin/env python3
"""出片线程：提交 → 轮询 → 下载、瞬时错误重试、厂商失败、并发上限、接力顺序、分镜改动不提交、
下载校验、重启续跑不重复提交。用法: python3 tests/render/test_runner.py
"""
import copy
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
os.environ["STORYBOARD_VIDEO_PROVIDER"] = "fake"

from render import compose, providers, session as sess  # noqa: E402
from render.providers.fake import FakeVideo  # noqa: E402
from render.runner import Runner  # noqa: E402

YAO = ROOT / "tests" / "real_text_yao" / "output_merged.json"
OWNER = {"user_id": "u", "nid": "n", "cid": "c", "vid": "v"}


def clip(root, cid):
    return next(c for c in sess.load(root)["clips"] if c["id"] == cid)


def main() -> int:
    doc = json.loads(YAO.read_text(encoding="utf-8"))
    current = {"doc": doc}
    fake = FakeVideo()
    providers.register("fake", lambda: fake)
    tmp = tempfile.TemporaryDirectory()
    data = Path(tmp.name)
    root = data / "users" / "u" / "novels" / "n" / "chapters" / "c" / "render" / "v"
    s = sess.build(root, doc, owner=OWNER, patch={"budget_cny": 100000}, keyframes={})
    ids = [c["id"] for c in s["clips"]]
    firsts = [c["id"] for c in s["clips"] if c["id"].endswith("-C01")]

    def builder(r, sess_now, c):
        return compose.request_for(current["doc"], sess_now, c, keyframes={},
                                   relay_frame=sess.relay_frame(r, sess_now, c),
                                   caps=fake.caps(sess_now["model"]), rewrite=fake.rewrite_prompt)

    slept = []
    runner = Runner(builder, sleep=slept.append, max_parallel=2)

    def drain(limit=200):
        for _ in range(limit):
            if not runner.watching():
                return
            runner.tick()
        raise AssertionError("没跑完")

    # 1. 一段走完：提交 → running → downloading → done，然后不再盯这个会话
    sess.queue_run(root, [ids[0]])
    runner.watch(root)
    runner.tick()
    assert clip(root, ids[0])["state"] == "running"
    runner.tick()
    assert clip(root, ids[0])["state"] == "downloading"
    runner.tick()
    c = clip(root, ids[0])
    assert c["state"] == "done" and (root / c["attempts"][0]["file"]).exists()
    assert runner.watching() == []
    print("1. 一段走完 ✓")

    # 2. 瞬时错误：重试 3 次内成功不算新尝试；3 次都失败记失败
    fake.transient_submits = 2
    sess.queue_run(root, [firsts[1]])
    runner.watch(root)
    runner.tick()
    c = clip(root, firsts[1])
    assert c["state"] == "running" and len(c["attempts"]) == 1 and slept == [1, 2]
    drain()
    fake.transient_submits = 3
    sess.queue_run(root, [firsts[2]])
    runner.watch(root)
    runner.tick()
    c = clip(root, firsts[2])
    assert c["state"] == "failed" and "已重试 3 次" in c["error"]
    fake.transient_submits = 0
    print("2. 瞬时错误重试 ✓")

    # 3. 厂商明确失败：原因原样、不计费
    spent = sess.load(root)["spent_cny"]
    fake.fail_with = "OutputVideoSensitiveContentDetected: 审核未通过"
    sess.queue_run(root, [firsts[2]])
    runner.watch(root)
    drain()
    c = clip(root, firsts[2])
    assert c["state"] == "failed" and c["error"] == fake.fail_with
    assert sess.load(root)["spent_cny"] == spent
    fake.fail_with = None
    print("3. 厂商失败 ✓")

    # 4. 并发上限：同时最多 2 段在跑
    sess.queue_run(root, [firsts[2], firsts[3]])
    sess.queue_run(root, [ids[1]])
    runner.watch(root)
    before = len(fake.submitted)
    runner.tick()
    assert len(fake.submitted) - before == 2
    assert sum(1 for c in sess.load(root)["clips"] if c["state"] == "running") == 2
    drain()
    print("4. 并发上限 ✓")

    # 5. 接力：上一段在跑时下一段等；上一段完成后带尾帧提交
    nxt = next(c for c in sess.load(root)["clips"] if c["first_frame"] == f"relay:{ids[1]}")
    third = next(c for c in sess.load(root)["clips"] if c["first_frame"] == f"relay:{nxt['id']}")
    sess.queue_run(root, [nxt["id"], third["id"]])
    runner.watch(root)
    before = len(fake.submitted)
    runner.tick()
    assert len(fake.submitted) - before == 1 and clip(root, third["id"])["state"] == "queued"
    assert fake.submitted[-1].first_frame.startswith("data:image/jpeg;base64,")
    drain()
    assert clip(root, third["id"])["attempts"][-1]["first_frame_used"] == f"relay:{nxt['id']}"
    print("5. 接力顺序 ✓")

    # 6. 排队后分镜改了：不提交，退回待确认
    target = ids[0]
    sess.queue_run(root, [target])
    edited = copy.deepcopy(doc)
    edited["episodes"][0]["shots"][0]["action"] += "（改）"
    current["doc"] = edited
    runner.watch(root)
    before = len(fake.submitted)
    runner.tick()
    c = clip(root, target)
    assert len(fake.submitted) == before and c["state"] == "stale" and "已改动" in c["error"]
    assert len(c["attempts"]) == 1, "撤回了这次尝试"
    current["doc"] = doc
    print("6. 分镜改动不提交 ✓")

    # 7. 下载到的不是视频：记失败，生成费用照记
    spent = sess.load(root)["spent_cny"]
    real_download = fake.download

    def broken(st, dest):
        files = real_download(st, dest)
        files["video"].write_bytes(b"<html>expired</html>")
        return files

    fake.download = broken
    sess.queue_run(root, [ids[1]])
    runner.watch(root)
    drain()
    c = clip(root, ids[1])
    assert c["state"] == "failed" and "不是可播放的视频" in c["error"]
    assert sess.load(root)["spent_cny"] > spent
    fake.download = real_download
    print("7. 下载校验 ✓")

    # 8. 重启续跑：已有任务 id 的接着查，不重复提交
    sess.queue_run(root, [ids[1]])
    runner.watch(root)
    runner.tick()
    assert clip(root, ids[1])["state"] == "running"
    before = len(fake.submitted)
    again = Runner(builder, sleep=slept.append)
    assert again.recover(data) == 1 and again.watching() == [root]
    for _ in range(10):
        again.tick()
    assert clip(root, ids[1])["state"] == "done" and len(fake.submitted) == before
    print("8. 重启续跑 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
