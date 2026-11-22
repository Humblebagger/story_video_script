#!/usr/bin/env python3
"""出片线程：提交 → 轮询 → 下载、瞬时错误重试、厂商失败、并发上限、接力顺序、分镜改动不提交、
下载校验、重启续跑不重复提交。用法: python3 tests/render/test_runner.py
"""
import copy
import json
import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
os.environ["STORYBOARD_VIDEO_PROVIDER"] = "fake"
os.environ["STORYBOARD_DATA_DIR"] = tempfile.mkdtemp()   # 错误记录写临时目录，不碰真实 backend/data（在导入 render/server 之前）
# 测试不读真实的 backend/.env：load_settings 里的 _load_dotenv 换成空操作（脚本独占进程，无需还原）
import pipeline.config as _pipeline_config  # noqa: E402
_pipeline_config._load_dotenv = lambda *_a, **_k: None

from render import compose, providers, session as sess  # noqa: E402
from render.providers import base  # noqa: E402
from render.providers.fake import FakeVideo  # noqa: E402
from render.runner import Runner  # noqa: E402
from server import error_refs  # noqa: E402

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


class _LogGrab(logging.Handler):
    """挂在某个 logger 上收日志文字与记录（测试不读真实日志配置）。"""
    def __init__(self, name):
        super().__init__(logging.DEBUG)
        self.lines, self.records = [], []
        self._lg = logging.getLogger(name)

    def emit(self, rec):
        self.records.append(rec)
        self.lines.append(rec.getMessage())

    def __enter__(self):
        self._lg.addHandler(self)
        return self

    def __exit__(self, *a):
        self._lg.removeHandler(self)


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
    assert c["error_msg"]["code"] == "film.submit.unavailable" and c["error_msg"]["params"]["retries"] == 3
    assert c["error_msg"]["params"]["cause"]["code"], c["error_msg"]
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
    assert c["state"] == "failed" and "意外错误" in c["error"] and len(c["attempts"]) == 1
    assert "ValueError" not in c["error"] and "坏了" not in c["error"]
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
    assert c["error"].startswith("提交时连接中断，不确定生成服务是否已受理：这一段可能已计费，请联系管理员核对后再重做")
    assert "控制台" not in c["error"] and "ReadTimeout" not in c["error"] and set(c["error_msg"]["params"]) == {"cause"}
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
    assert c["error_msg"]["code"] == "film.submit.interrupted"
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
        assert c["state"] == "running" and not c.get("uncertain") and c["error"] == "厂商暂时不可达，正在重试：未知原因"
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
    # 用真正会发图的段：首帧与参考位并用（frame_with_refs=True）、有风格图占一个参考位，接力段首帧 + 风格图 = 2 张
    import dataclasses
    real_caps = fake._caps
    fake._caps = dataclasses.replace(real_caps, frame_with_refs=True)
    current["style"] = {"source": "data:image/png;base64,AAAA", "hash": "h1"}
    rootI = data / "users" / "u" / "novels" / "n" / "chapters" / "c" / "render" / "img"
    sI = sess.build(rootI, doc, owner=dict(OWNER, vid="img"), patch={"budget_cny": 100000}, keyframes={},
                    style=current["style"])
    by_id = {c["id"]: c for c in sI["clips"]}
    pairs = [(by_id[c["first_frame"][6:]], c) for c in sI["clips"]
             if (c["first_frame"] or "").startswith("relay:") and c["style"] == "used"]
    assert len(pairs) >= 3, pairs
    costs, by_tid = [], {}
    real_cost = fake.cost
    fake.cost = lambda st, req: (costs.append((st.status, req.images)), by_tid.__setitem__(st.task_id, (st.status, req.images)), real_cost(st, req))[2]
    (prev1, nxt1), (_, nxt2), (_, nxt3) = pairs[0], pairs[2], pairs[4] if len(pairs) > 4 else pairs[3]
    nxt3_prev = [p for p, n in pairs if n["id"] == nxt3["id"]][0]

    # 16a. 前一段出完、尾帧在：后一段首帧 + 风格图都发出，张数 = 参考位 + 1 且不为 0
    sess.queue_run(rootI, [prev1["id"], nxt1["id"]])
    rn = quick()
    rn.watch(rootI)
    drain_runner(rn)
    a = clip(rootI, nxt1["id"])["attempts"][-1]
    sent = fake.submitted[-1]
    assert sent.first_frame and len(sent.refs) == 1, (sent.first_frame is None, len(sent.refs))
    assert a["images"] == len(sent.refs) + 1 == 2
    assert ("succeeded", 2) in costs, costs
    assert a["images"] == compose.image_count(by_id[nxt1["id"]]), "尾帧在时与预估一致"

    # 16b. 接力段的上一段没出过（没有尾帧）：不发首帧，只算风格图那一张，比预估少一张
    before = len(fake.submitted)
    sess.queue_run(rootI, [nxt2["id"]])
    rn = quick()
    rn.watch(rootI)
    drain_runner(rn)
    assert len(fake.submitted) == before + 1
    sent = fake.submitted[-1]
    assert sent.first_frame is None and len(sent.refs) == 1
    a = clip(rootI, nxt2["id"])["attempts"][-1]
    assert a["images"] == 1 < compose.image_count(by_id[nxt2["id"]]) == 2, a
    assert ("succeeded", 1) in costs, costs

    # 16c. 失败结算 + 重出：每次尝试各记各的张数，计费桩取最后一次尝试的；重启后张数仍在、仍带给 cost
    fake.fail_with = "OutputVideoSensitiveContentDetected: 审核未通过"
    sess.queue_run(rootI, [nxt3["id"]])
    rn = quick()
    rn.watch(rootI)
    drain_runner(rn)
    c3 = clip(rootI, nxt3["id"])
    assert c3["state"] == "failed" and c3["attempts"][-1]["images"] == 1   # 上一段没出过，没有首帧
    assert by_tid[c3["attempts"][-1]["task_id"]] == ("failed", 1), by_tid
    fake.fail_with = None
    # 先让上一段出完，再重出：新一次尝试带首帧 + 风格图 = 2 张；提交后“重启”，新 Runner 接着查并下载
    sess.queue_run(rootI, [nxt3_prev["id"]])
    rn = quick()
    rn.watch(rootI)
    drain_runner(rn)
    sess.queue_run(rootI, [nxt3["id"]])
    rn = quick()
    rn.watch(rootI)
    rn.tick()                                  # 只提交
    c3 = clip(rootI, nxt3["id"])
    assert c3["state"] == "running" and len(c3["attempts"]) == 2
    assert [x.get("images") for x in c3["attempts"]] == [1, 2]
    again = quick()
    assert again.recover(data) >= 1
    drain_runner(again)
    c3 = clip(rootI, nxt3["id"])
    assert c3["state"] == "done" and c3["attempts"][-1]["images"] == 2
    tid3 = c3["attempts"][-1]["task_id"]
    assert by_tid[tid3] == ("succeeded", 2), by_tid       # recover 还会接手别的残留会话，只看这一段的任务
    # 旧会话的尝试没有 images：桩里是 None
    raw = sess.load(rootI)
    old = next(c for c in raw["clips"] if c["id"] == nxt3["id"])
    old["attempts"][-1].pop("images")
    assert Runner._stub(raw, old).images is None
    fake.cost = real_cost
    fake._caps = real_caps
    current["style"] = None
    print("16. 尝试记张数、计费桩带张数 ✓")

    # 17. 错误带代码：提交不明、查询放弃、重试提示、厂商失败、普通异常
    # 这一例的会话放在配置的数据目录下，才能验证 <data> 替换与用户解析
    r17 = Path(os.environ["STORYBOARD_DATA_DIR"]) / "users" / "a1b2c3d4e5f6" / "novels" / "n" / "chapters" / "c" / "render" / "coded1"
    i17 = [x["id"] for x in sess.build(r17, doc, owner=dict(OWNER, vid="coded1"), patch={"budget_cny": 100000}, keyframes={})["clips"]]
    sess.queue_run(r17, [i17[0]])
    real_submit17 = fake.submit

    def submit_amb17(req):
        raise base.AmbiguousSubmit.of("film.provider.submit_cut")

    fake.submit = submit_amb17
    rn = quick()
    rn.watch(r17)
    rn.tick()
    c = clip(r17, i17[0])
    assert c["error_msg"] == {"code": "film.submit.ambiguous", "params": {
        "cause": {"code": "film.provider.submit_cut", "params": {}}}}, c["error_msg"]
    assert c["attempts"][-1]["error_msg"]["code"] == "film.submit.ambiguous"
    assert "请联系管理员核对后再重做" in c["error"] and "控制台" not in c["error"]
    assert c["error"].endswith("（网络中断）") and c["error"].count("提交时连接中断") == 1, c["error"]

    def submit_crash17(req):
        raise ValueError("坏了")

    fake.submit = submit_crash17
    sess.queue_run(r17, [i17[0]])
    rn = quick()
    rn.watch(r17)
    with _LogGrab("render.runner") as g:
        rn.tick()
    c = clip(r17, i17[0])
    assert c["error_msg"]["code"] == "film.submit.crashed" and c["error_msg"]["params"] == {} and len(c["error_msg"]["ref"]) == 8, c["error_msg"]
    rec17 = error_refs.find(c["error_msg"]["ref"])
    assert rec17 and "ValueError" in rec17["detail"] and i17[0] in rec17["detail"], rec17
    assert rec17["where"].startswith("submit <data>/") and i17[0] in rec17["where"], rec17["where"]
    assert rec17["user_id"] == "a1b2c3d4e5f6" and str(r17) not in rec17["detail"] and "<data>" in rec17["detail"], rec17
    assert "Traceback" in rec17["detail"]
    errs = [r for r in g.records if r.levelno == logging.ERROR]
    assert len(errs) == 1 and errs[0].exc_info is None, g.lines
    assert "root=<data>/users/a1b2c3d4e5f6/" in errs[0].getMessage() and i17[0] in errs[0].getMessage(), g.lines
    assert "Traceback" in errs[0].getMessage() and os.environ["STORYBOARD_DATA_DIR"] not in errs[0].getMessage(), g.lines
    assert "ValueError" in errs[0].getMessage() and "submit_crash17" in errs[0].getMessage(), g.lines   # 类型、原文、栈位置保留

    # 日志脱敏：直接异常与带 __cause__ 的链里的密钥、Bearer 凭据都不出现，落盘的报错也没有
    fake._key = "sk-SYNTH-KEY-12345"

    def submit_leak17(req):
        try:
            raise OSError("inner Bearer SECRET_TOKEN with sk-SYNTH-KEY-12345")
        except OSError as inner:
            raise RuntimeError("outer sk-SYNTH-KEY-12345 Bearer SECRET_TOKEN") from inner

    fake.submit = submit_leak17
    sess.queue_run(r17, [i17[0]])
    rn = quick()
    rn.watch(r17)
    with _LogGrab("render.runner") as g:
        rn.tick()
    text = "\n".join(g.lines)
    assert "RuntimeError" in text and "OSError" in text and "submit_leak17" in text, text
    assert "SECRET_TOKEN" not in text and "sk-SYNTH-KEY-12345" not in text, text
    assert all(r.exc_info is None for r in g.records)
    c = clip(r17, i17[0])
    blob = json.dumps(c, ensure_ascii=False)
    assert "SECRET_TOKEN" not in blob and "sk-SYNTH-KEY-12345" not in blob
    del fake._key

    # 共用脱敏帮手：runner 的 _scrub_secrets 与 app 的合成日志走同一个函数（TTS 环境密钥、实例密钥、Bearer 都抹）
    from render import runner as _rn
    from render.providers import base as _base
    os.environ["VOLC_TTS_API_KEY"], os.environ["VOLC_TTS_ACCESS_KEY"] = "tt1", "ak"
    try:
        probe = "Bearer TOK x tt1 y ak z inst9 w"
        inst = type("P", (), {"_key": "inst9"})()
        for out in (_rn._scrub_secrets(probe, inst), _base.scrub_secrets(probe, ["inst9"])):
            assert out == "Bearer *** x *** y *** z *** w", out
    finally:
        del os.environ["VOLC_TTS_API_KEY"], os.environ["VOLC_TTS_ACCESS_KEY"]

    # 短密钥也要抹掉：厂商对象的 _key 与环境里的厂商密钥都只有几个字符
    fake._key = "xyz"
    os.environ["ARK_API_KEY"], os.environ["MINIMAX_API_KEY"] = "ab1", "q9"

    def submit_short17(req):
        raise RuntimeError("leak xyz and ab1 and q9 end")

    fake.submit = submit_short17
    sess.queue_run(r17, [i17[0]])
    rn = quick()
    rn.watch(r17)
    with _LogGrab("render.runner") as g:
        rn.tick()
    text = "\n".join(g.lines)
    assert "RuntimeError" in text and "leak *** and *** and *** end" in text, text
    del fake._key

    # 位置字段（会话目录）里带环境密钥：整行日志都不能出现，不只是堆栈部分
    os.environ["ARK_API_KEY"] = str(r17)
    fake._key = "inst-in-clip"

    def submit_root17(req):
        raise RuntimeError("boom")

    fake.submit = submit_root17
    sess.queue_run(r17, [i17[0]])
    rn = quick()
    rn.watch(r17)
    with _LogGrab("render.runner") as g:
        rn.tick()
    errs = [r.getMessage() for r in g.records if r.levelno == logging.ERROR]
    assert errs and "RuntimeError" in errs[0] and "提交异常" in errs[0], g.lines
    assert not any(str(r17) in x for x in g.lines), g.lines
    del fake._key
    os.environ["ARK_API_KEY"] = os.environ["MINIMAX_API_KEY"] = ""

    def submit_reject17(req):
        raise base.ProviderError.of("film.vendor.auth")

    fake.submit = submit_reject17
    sess.queue_run(r17, [i17[0]])
    rn = quick()
    rn.watch(r17)
    with _LogGrab("render.runner") as g:
        rn.tick()
    warns = [r for r in g.records if r.levelno == logging.WARNING]
    assert any(str(r17) in r.getMessage() and i17[0] in r.getMessage() and "film.vendor.auth" in r.getMessage()
               for r in warns), g.lines
    fake.submit = real_submit17

    # 查询一直失败：重试提示带嵌套原因，放弃时 cause 是内层错误的紧凑消息
    now17 = [0.0]
    r18, i18 = fresh("coded2")
    sess.queue_run(r18, [i18[0]])
    rn = Runner(builder, sleep=lambda s: None, clock=lambda: now17[0],
                poll_give_up_sec=100, download_give_up_sec=100)
    rn.watch(r18)
    rn.tick()
    real_poll17 = fake.poll

    def poll_err17(tid):
        raise base.ProviderError.of("film.fake.no_task", id=tid)

    fake.poll = poll_err17
    now17[0] = 1
    rn.tick()
    c = clip(r18, i18[0])
    assert c["state"] == "running" and c["error_msg"]["code"] == "film.provider.retrying"
    assert c["error_msg"]["params"]["cause"]["code"] == "film.fake.no_task"
    now17[0] = 101
    with _LogGrab("render.runner") as g:
        rn.tick()
    tid18 = clip(r18, i18[0])["attempts"][-1]["task_id"]
    assert any(str(r18) in x and i18[0] in x and tid18 in x for x in g.lines), g.lines
    c = clip(r18, i18[0])
    assert c["state"] == "failed" and c["error_msg"]["code"] == "film.poll.gave_up"
    assert c["error_msg"]["params"]["cause"]["code"] == "film.fake.no_task"
    assert c["attempts"][-1]["error_msg"]["code"] == "film.poll.gave_up"
    fake.poll = real_poll17

    # 厂商报的失败终态：代码原样落到尝试与段
    fake.fail_with = "审核未通过"
    r19, i19 = fresh("coded3")
    sess.queue_run(r19, [i19[0]])
    rn = quick()
    rn.watch(r19)
    for _ in range(5):
        rn.tick()
    c = clip(r19, i19[0])
    assert c["state"] == "failed" and c["error"] == "审核未通过"
    assert c["error_msg"] == {"code": "film.fake.failed", "params": {"detail": {"t": "vendor", "text": "审核未通过"}}}
    assert c["attempts"][-1]["error_msg"] == c["error_msg"]
    fake.fail_with = None
    print("17. 错误带代码与嵌套原因 ✓")

    # 18. 没有代码的异常（可能带厂商接口地址）：原因只说「未知原因」，原文只进日志
    real_submit18 = fake.submit
    r20, i20 = fresh("unknown_cause")
    sess.queue_run(r20, [i20[0]])
    calls18 = []

    def submit_amb18(req):
        calls18.append(1)
        raise base.AmbiguousSubmit("boom https://api.minimax.cn/v1")

    fake.submit = submit_amb18
    try:
        rn = quick()
        rn.watch(r20)
        with _LogGrab("render.runner") as g18:
            rn.tick()
            rn.tick()
    finally:
        fake.submit = real_submit18
    c = clip(r20, i20[0])
    assert len(calls18) == 1 and c["state"] == "failed" and c["uncertain"] is True, c
    assert c["error_msg"]["code"] == "film.submit.ambiguous", c["error_msg"]
    assert c["error_msg"]["params"] == {"cause": {"code": "film.vendor.unknown_cause", "params": {}}}, c["error_msg"]
    assert "boom" not in c["error"] and "minimax" not in c["error"] and c["error"].endswith("（未知原因）"), c["error"]
    assert any("boom" in x for x in g18.lines), g18.lines

    # 19. 外层中文兜底与改造前一致：不被参数截断、KeyError 的引号保留、轮询放弃保留完整原文
    r21, i21 = fresh("fallback")
    sess.queue_run(r21, [i21[0]])
    long_raw = "长" * 500

    def submit_long(req):
        raise ValueError(long_raw)

    fake.submit = submit_long
    rn = quick()
    rn.watch(r21)
    rn.tick()
    fake.submit = real_submit18
    c = clip(r21, i21[0])
    assert c["error"].startswith("提交时出现意外错误，请重试；仍失败请联系管理员") and "参考编号" in c["error"], c["error"]   # 异常原文不再进界面
    assert c["error_msg"]["code"] == "film.submit.crashed" and c["error_msg"]["params"] == {} and len(c["error_msg"]["ref"]) == 8, c["error_msg"]

    r22, i22 = fresh("fallback2")
    sess.queue_run(r22, [i22[0]])

    def request_keyerror(r, s_, c_):
        raise KeyError("缺字段")

    rn = Runner(request_keyerror, sleep=lambda s: None, max_parallel=4)
    rn.watch(r22)
    rn.tick()
    c = clip(r22, i22[0])
    assert c["error"] == "组装请求失败：未知原因", c["error"]
    assert c["error_msg"]["params"]["cause"] == {"code": "film.vendor.unknown_cause", "params": {}}

    now19 = [0.0]
    r23, i23 = fresh("fallback3")
    sess.queue_run(r23, [i23[0]])
    rn = Runner(builder, sleep=lambda s: None, clock=lambda: now19[0],
                poll_give_up_sec=100, download_give_up_sec=100)
    rn.watch(r23)
    rn.tick()
    real_poll19 = fake.poll

    def poll_long(tid):
        raise base.ProviderError(long_raw)

    fake.poll = poll_long
    now19[0] = 1
    rn.tick()
    assert clip(r23, i23[0])["error"] == "厂商暂时不可达，正在重试：未知原因"
    now19[0] = 101
    rn.tick()
    c = clip(r23, i23[0])
    assert c["error"] == "多次查询都失败，已放弃；请联系管理员核对这个任务：未知原因", c["error"]
    assert c["error_msg"]["params"]["cause"] == {"code": "film.vendor.unknown_cause", "params": {}}
    fake.poll = real_poll19
    print("18. 未知原因与中文兜底 ✓")

    # 19. 提交意外异常 + 状态写回也失败：stderr 与日志里没有密钥，也没有原异常链；段仍停在「提交中」
    import contextlib
    import io
    r24 = Path(os.environ["STORYBOARD_DATA_DIR"]) / "users" / "a1b2c3d4e5f6" / "novels" / "n" / "chapters" / "c" / "render" / "wbfail"
    i24 = [x["id"] for x in sess.build(r24, doc, owner=dict(OWNER, vid="wbfail"), patch={"budget_cny": 100000}, keyframes={})["clips"]]
    sess.queue_run(r24, [i24[0]])
    fake._key = "sk-SYNTH-WB-98765"
    real_submit24, real_sf24 = fake.submit, sess.submit_failed

    def submit_leak24(req):
        raise RuntimeError("vendor said sk-SYNTH-WB-98765 Bearer WBTOKEN")

    def sf_boom24(*a, **kw):
        raise OSError(f"disk full {r24}/session.json")

    fake.submit, sess.submit_failed = submit_leak24, sf_boom24
    rn = quick()
    rn.watch(r24)
    fmt24 = logging.Formatter("%(message)s")
    err24 = io.StringIO()
    try:
        with _LogGrab("render.runner") as g, _LogGrab("server.errors") as g2, contextlib.redirect_stderr(err24):
            rn.tick()
    finally:
        fake.submit, sess.submit_failed = real_submit24, real_sf24
        fake._key = ""
    logs24 = "\n".join(fmt24.format(r) + (("\n" + fmt24.formatException(r.exc_info)) if r.exc_info else "")
                       for r in g.records + g2.records)
    allout = err24.getvalue() + "\n" + logs24
    assert "sk-SYNTH-WB-98765" not in allout and "WBTOKEN" not in allout, allout
    assert "vendor said" not in err24.getvalue() and "Traceback" not in err24.getvalue(), err24.getvalue()
    assert os.environ["STORYBOARD_DATA_DIR"] not in allout and "<data>" in logs24, allout
    assert "写回失败" in logs24 and all(r.exc_info is None for r in g.records + g2.records), logs24
    assert clip(r24, i24[0])["state"] == "queued" and sess.load(r24)["clips"] is not None
    print("19. 提交异常后写回失败：不泄露密钥与异常链 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
