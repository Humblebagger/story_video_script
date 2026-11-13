#!/usr/bin/env python3
"""出片线程：提交 → 轮询 → 下载、瞬时错误重试、厂商失败、并发上限、接力顺序、分镜改动不提交、
下载校验、重启续跑不重复提交。用法: python3 tests/render/test_runner.py
"""
import copy
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
os.environ["STORYBOARD_VIDEO_PROVIDER"] = "fake"

from render import compose, providers, session as sess  # noqa: E402
from render.providers import base  # noqa: E402
from render.providers.fake import FakeVideo  # noqa: E402
from render.runner import Runner  # noqa: E402

YAO = ROOT / "tests" / "real_text_yao" / "output_merged.json"
OWNER = {"user_id": "u", "nid": "n", "cid": "c", "vid": "v"}


def clip(root, cid):
    return next(c for c in sess.load(root)["clips"] if c["id"] == cid)


def drain_runner(rn, limit=200):
    for _ in range(limit):
        if not rn.watching():
            return
        rn.tick()
    raise AssertionError("没跑完")


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
                                   caps=fake.caps(sess_now["model"]), rewrite=fake.rewrite_prompt,
                                   style=current.get("style"))

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

    # ---------- 修复轮 1 ----------
    def fresh(vid):
        r = data / "users" / "u" / "novels" / "n" / "chapters" / "c" / "render" / vid
        built = sess.build(r, doc, owner=dict(OWNER, vid=vid), patch={"budget_cny": 100000}, keyframes={})
        return r, [x["id"] for x in built["clips"]]

    def quick():
        return Runner(builder, sleep=lambda s: None, max_parallel=4)

    # 9. 失败隔离：一个会话的根目录没了，不拖累别的会话；某段 poll 抛普通异常，其它段照常推进
    r1, i1 = fresh("iso1")
    r2, i2 = fresh("iso2")
    sess.queue_run(r1, [i1[0]])
    sess.queue_run(r2, [i2[0]])
    rn = quick()
    rn.watch(r1)
    rn.watch(r2)
    shutil.rmtree(r1)
    before = len(fake.submitted)
    rn.tick()
    assert len(fake.submitted) == before + 1 and clip(r2, i2[0])["state"] == "running"
    assert r1 not in rn.watching()
    rn.watching() and drain_runner(rn)
    r3, i3 = fresh("iso3")
    i3 = [x for x in i3 if x.endswith("-C01")]
    sess.queue_run(r3, [i3[0], i3[1]])
    rn = quick()
    rn.watch(r3)
    rn.tick()
    bad = clip(r3, i3[0])["attempts"][-1]["task_id"]
    real_poll = fake.poll

    def poll_boom(tid):
        if tid == bad:
            raise RuntimeError("boom")
        return real_poll(tid)

    fake.poll = poll_boom
    rn.tick()
    assert clip(r3, i3[0])["state"] == "running" and clip(r3, i3[1])["state"] == "downloading"
    fake.poll = real_poll
    drain_runner(rn)
    print("9. 失败隔离 ✓")

    # 10. 提交抛意外异常：记失败、只有一次尝试、下一轮不重复提交
    r4, i4 = fresh("boom")
    sess.queue_run(r4, [i4[0]])
    real_submit = fake.submit

    def submit_boom(req):
        raise ValueError("坏了")

    fake.submit = submit_boom
    rn = quick()
    rn.watch(r4)
    rn.tick()
    c = clip(r4, i4[0])
    assert c["state"] == "failed" and "提交异常" in c["error"] and len(c["attempts"]) == 1
    fake.submit = real_submit
    before = len(fake.submitted)
    rn.tick()
    assert len(fake.submitted) == before and len(clip(r4, i4[0])["attempts"]) == 1
    print("10. 提交异常不重复提交 ✓")

    # 11. 丢失唤醒：收尾判断与 watch 互斥
    r5, i5 = fresh("race")
    rn = quick()
    rn.watch(r5)
    real_load = sess.load

    def racing_load(r):
        if sys._getframe(1).f_code.co_name == "_settle":
            sess.load = real_load
            sess.queue_run(r, [i5[0]])
            rn.watch(r)
        return real_load(r)

    sess.load = racing_load
    try:
        rn.tick()
    finally:
        sess.load = real_load
    assert r5 in rn.watching()
    print("11. 丢失唤醒 ✓")

    # 12. 瞬时错误不能无限重试：假时钟推过期限后放弃
    now = [0.0]
    r6, i6 = fresh("giveup")
    sess.queue_run(r6, [i6[0]])
    rn = Runner(builder, sleep=lambda s: None, clock=lambda: now[0],
                poll_give_up_sec=100, download_give_up_sec=100)
    rn.watch(r6)
    rn.tick()
    assert clip(r6, i6[0])["state"] == "running"

    def transient_poll(tid):
        raise base.TransientError("连不上")

    fake.poll = transient_poll
    rn.tick()
    c = clip(r6, i6[0])
    assert c["state"] == "running" and "正在重试" in c["error"]
    now[0] = 101
    rn.tick()
    c = clip(r6, i6[0])
    assert c["state"] == "failed" and "多次查询都失败" in c["error"]
    fake.poll = real_poll

    r7, i7 = fresh("giveup2")
    sess.queue_run(r7, [i7[0]])
    now[0] = 0
    rn = Runner(builder, sleep=lambda s: None, clock=lambda: now[0],
                poll_give_up_sec=100, download_give_up_sec=100)
    rn.watch(r7)
    rn.tick()
    rn.tick()
    assert clip(r7, i7[0])["state"] == "downloading"

    def transient_dl(st, dest):
        raise base.TransientError("下不动")

    fake.download = transient_dl
    rn.tick()
    c = clip(r7, i7[0])
    assert c["state"] == "downloading" and "正在重试" in c["error"]
    now[0] = 101
    rn.tick()
    c = clip(r7, i7[0])
    assert c["state"] == "failed" and "下载一直失败" in c["error"]
    fake.download = real_download
    print("12. 重试期限 ✓")

    # ---------- 终审修复 ----------
    # 13. 提交结果不明（AmbiguousSubmit）：只调一次、不重试，记失败并标待核对
    r8, i8 = fresh("ambiguous")
    sess.queue_run(r8, [i8[0]])
    calls = []

    def submit_ambiguous(req):
        calls.append(req)
        raise base.AmbiguousSubmit("提交时连接中断：ReadTimeout")

    fake.submit = submit_ambiguous
    rn = quick()
    rn.watch(r8)
    rn.tick()
    rn.tick()
    c = clip(r8, i8[0])
    assert len(calls) == 1, calls
    assert c["state"] == "failed" and c["uncertain"] is True and len(c["attempts"]) == 1
    assert c["error"].startswith("提交时连接中断，不确定厂商是否已受理：请到厂商控制台核对") and "ReadTimeout" in c["error"]
    # 厂商自报控制台名时用它
    r8b, i8b = fresh("ambiguous2")
    sess.queue_run(r8b, [i8b[0]])
    fake.console_name = "某某控制台"
    rn = quick()
    rn.watch(r8b)
    rn.tick()
    rn.tick()
    assert clip(r8b, i8b[0])["error"].startswith("提交时连接中断，不确定厂商是否已受理：请到某某控制台核对")
    del fake.console_name
    fake.submit = real_submit
    print("13. 提交结果不明不重试 ✓")

    # 14. 已提交但写回任务 id 失败：下一轮不再提交，转失败并标待核对
    r9, i9 = fresh("lostid")
    sess.queue_run(r9, [i9[0]])
    real_submitted = sess.submitted
    boom = [1]

    def submitted_once(*a, **kw):
        if boom:
            boom.pop()
            raise OSError("磁盘满了")
        return real_submitted(*a, **kw)

    sess.submitted = submitted_once
    before = len(fake.submitted)
    rn = quick()
    rn.watch(r9)
    try:
        rn.tick()
        rn.tick()
    finally:
        sess.submitted = real_submitted
    c = clip(r9, i9[0])
    assert len(fake.submitted) == before + 1, "只提交了一次"
    assert c["state"] == "failed" and c["uncertain"] is True and len(c["attempts"]) == 1
    assert c["error"] == sess.INTERRUPTED_SUBMIT
    print("14. 写回失败不重复提交 ✓")

    # 15. 查询抛 ProviderError 不等于任务失败：保持 running 到期限，之后失败并标待核对
    now[0] = 0
    r10, i10 = fresh("pollerr")
    sess.queue_run(r10, [i10[0]])
    rn = Runner(builder, sleep=lambda s: None, clock=lambda: now[0],
                poll_give_up_sec=100, download_give_up_sec=100)
    rn.watch(r10)
    rn.tick()
    assert clip(r10, i10[0])["state"] == "running"

    def provider_err_poll(tid):
        raise base.ProviderError("任务查询失败：InternalServiceError")

    fake.poll = provider_err_poll
    for t_ in (1, 50, 100):
        now[0] = t_
        rn.tick()
        c = clip(r10, i10[0])
        assert c["state"] == "running" and not c.get("uncertain") and "InternalServiceError" in c["error"]
    assert r10 in rn.watching()
    now[0] = 101
    rn.tick()
    c = clip(r10, i10[0])
    assert c["state"] == "failed" and c["uncertain"] is True and "多次查询都失败" in c["error"]
    assert sess.load(r10)["spent_cny"] == 0.0
    fake.poll = real_poll
    print("15. 查询出错不算失败、到期标待核对 ✓")

    # 风格图：请求带哈希，提交后写回最后一次尝试
    rootS = data / "users" / "u" / "novels" / "n" / "chapters" / "c" / "render" / "vs"
    current["style"] = {"source": "data:image/png;base64,AAAA", "hash": "h1"}
    sS = sess.build(rootS, doc, owner=OWNER, patch={"budget_cny": 100000}, keyframes={},
                    style=current["style"])
    sid = next(c["id"] for c in sS["clips"] if c["style"] == "used")
    req_s, _ = builder(rootS, sS, next(c for c in sS["clips"] if c["id"] == sid))
    assert req_s.style_ref == "h1"
    sess.queue_run(rootS, [sid])
    runner.watch(rootS)
    runner.tick()
    assert clip(rootS, sid)["attempts"][-1]["style_ref"] == "h1"
    drain()
    # 建会话后换图：记下的是提交时实际发出的那张，不算过期
    used = [c["id"] for c in sS["clips"] if c["style"] == "used"]
    assert len(used) >= 3, used
    sess.queue_run(rootS, [used[1]])
    runner.watch(rootS)
    current["style"] = {"source": "data:image/png;base64,BBBB", "hash": "h2"}
    runner.tick()
    c2 = clip(rootS, used[1])
    assert c2["attempts"][-1]["style_ref"] == "h2", c2["attempts"][-1]
    assert c2["state"] != "stale" and not c2.get("error"), c2
    drain()
    # 建会话后删图：提交时没有风格图，记 None，不拦
    sess.queue_run(rootS, [used[2]])
    runner.watch(rootS)
    current["style"] = None
    runner.tick()
    c3 = clip(rootS, used[2])
    assert c3["attempts"][-1]["style_ref"] is None and not c3.get("error"), c3
    drain()
    print("风格图写回尝试（含建会话后换图 / 删图）✓")

    # 16. 提交时算出实际张数写进尝试；计费时 _stub 把它带给 cost
    costs = []
    real_cost = fake.cost
    fake.cost = lambda st, req: (costs.append(req.images), real_cost(st, req))[1]
    r16, i16 = fresh("images")
    sess.queue_run(r16, [i16[0]])
    rn = quick()
    rn.watch(r16)
    for _ in range(5):
        rn.tick()
    a = clip(r16, i16[0])["attempts"][-1]
    sent = fake.submitted[-1]
    assert a["images"] == len(sent.refs) + (1 if sent.first_frame else 0)
    assert costs and costs[-1] == a["images"]
    fake.cost = real_cost
    print("16. 尝试记张数、计费桩带张数 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
