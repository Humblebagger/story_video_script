#!/usr/bin/env python3
"""出片线程的内容检查：在 begin_submit 之前问回调；等待时本轮跳过且段仍排队、没有新尝试；
拦截或不可用时段失败且不提交；回调自己出错也不放行；不传回调时行为不变；待检查集合。
用法: python3 tests/render/test_safety_runner.py"""
import json
import os
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tests" / "pipeline"))
import _noenv  # noqa: E402,F401  测试不读真实 .env
os.environ["STORYBOARD_VIDEO_PROVIDER"] = "fake"
os.environ["STORYBOARD_DATA_DIR"] = tempfile.mkdtemp()
import pipeline.config as _pipeline_config  # noqa: E402
_pipeline_config._load_dotenv = lambda *_a, **_k: None

from render import compose, providers, session as sess  # noqa: E402
from render.providers.fake import FakeVideo  # noqa: E402
from render.runner import Runner  # noqa: E402
from safety import gate  # noqa: E402
from fakes import FakeChat  # noqa: E402
from pipeline.chat import ChatInvoker  # noqa: E402
from pipeline.config import Settings  # noqa: E402

YAO = ROOT / "tests" / "real_text_yao" / "output_merged.json"
OWNER = {"user_id": "u", "nid": "n", "cid": "c", "vid": "v"}


def clip(root, cid):
    return next(c for c in sess.load(root)["clips"] if c["id"] == cid)


def main() -> int:
    doc = json.loads(YAO.read_text(encoding="utf-8"))
    fake = FakeVideo()
    providers.register("fake", lambda: fake)
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name) / "users" / "u" / "novels" / "n" / "chapters" / "c" / "render" / "v"
    s = sess.build(root, doc, owner=OWNER, patch={"budget_cny": 100000}, keyframes={})
    firsts = [c["id"] for c in s["clips"] if c["id"].endswith("-C01")]
    assert len(firsts) >= 3, "夹具至少要有三集的首段（互不接力）"
    a, b, c3 = firsts[:3]

    def builder(r, sess_now, c):
        return compose.request_for(doc, sess_now, c, keyframes={}, relay_frame=sess.relay_frame(r, sess_now, c),
                                   caps=fake.caps(sess_now["model"]), rewrite=fake.rewrite_prompt, style=None)

    answers, asked = {}, []

    def check(r, sess_now, c):
        asked.append((c["id"], c["prompt"], sess_now["owner"]["user_id"]))
        out = answers.get(c["id"], "pass")
        if isinstance(out, Exception):
            raise out
        return out

    runner = Runner(builder, sleep=lambda _s: None, max_parallel=4, safety_check=check)

    # 1. 等待：本轮跳过，段仍排队、没有追加尝试；待检查集合里有它；回调拿到的是会话里存的提示词
    answers[a] = "wait"
    sess.queue_run(root, [a])
    runner.watch(root)
    runner.tick()
    ca = clip(root, a)
    assert ca["state"] == "queued" and ca["attempts"] == [], ca
    assert asked[-1] == (a, ca["prompt"], "u")
    assert runner.is_checking(OWNER, a) and not runner.is_checking(OWNER, b)
    assert runner.watching() == [root], "排队的段还要盯"
    print("1. 等待时跳过 ✓")

    # 2. 下一轮有了结论：通过 → 提交；待检查集合清掉
    answers[a] = "pass"
    runner.tick()
    assert clip(root, a)["state"] == "running" and not runner.is_checking(OWNER, a)
    print("2. 通过后提交 ✓")

    # 3. 拦截：段失败、消息带类别与编号、没有追加尝试（没有提交、不花钱）
    answers[b] = gate.blocked_error("sexual", "AB12CD34")
    sess.queue_run(root, [b])
    runner.watch(root)
    runner.tick()
    cb = clip(root, b)
    assert cb["state"] == "failed" and cb["attempts"] == [] and not cb.get("uncertain"), cb
    assert cb["error_msg"] == {"code": "safety.blocked", "ref": "AB12CD34",
                               "params": {"category": {"t": "ref", "code": "safety.category.sexual"}}}
    print("3. 拦截 ✓")

    # 4. 不可用、回调自己出错：都不放行
    answers[c3] = gate.unavailable_error()
    sess.queue_run(root, [c3])
    runner.watch(root)
    runner.tick()
    cc = clip(root, c3)
    assert cc["state"] == "failed" and cc["error_msg"]["code"] == "safety.unavailable" and cc["attempts"] == []
    answers[c3] = RuntimeError("boom")
    sess.queue_run(root, [c3])
    runner.watch(root)
    runner.tick()
    cc = clip(root, c3)
    assert cc["state"] == "failed" and cc["error_msg"]["code"] == "safety.unavailable" and cc["attempts"] == []
    print("4. 不可用与回调出错 ✓")

    # 5. 被拦的段重新排队后放行（管理员放行的情形）：正常提交
    answers[b] = "pass"
    sess.queue_run(root, [b])
    runner.watch(root)
    runner.tick()
    assert clip(root, b)["state"] == "running"
    print("5. 放行后重做 ✓")

    # 6. 不传回调：行为与以前一致
    tmp2 = tempfile.TemporaryDirectory()
    root2 = Path(tmp2.name) / "users" / "u" / "novels" / "n" / "chapters" / "c" / "render" / "v"
    s2 = sess.build(root2, doc, owner=OWNER, patch={"budget_cny": 100000}, keyframes={})
    plain = Runner(builder, sleep=lambda _s: None)
    sess.queue_run(root2, [s2["clips"][0]["id"]])
    plain.watch(root2)
    plain.tick()
    assert clip(root2, s2["clips"][0]["id"])["state"] == "running" and not plain.is_checking(OWNER, a)
    print("6. 不传回调 ✓")

    # 7. app 的接线：未知 → 排队分类并返回 wait；有结论后按结论；视图标注 safety_checking
    os.environ["STORYBOARD_SAFETY"] = "1"
    os.environ["STORYBOARD_RENDER_RUNNER"] = "0"
    from server import app as app_mod
    queued_texts = []
    real_lookup, real_async = gate.lookup, gate.classify_async
    state = {"r": None}
    seen_waiters = []
    gate.lookup = lambda text, ctx, waiter=None: seen_waiters.append(waiter) or state["r"]
    gate.classify_async = lambda text, ctx, waiter=None: queued_texts.append((text, ctx["stage"], ctx["clip_id"])) or True
    try:
        sess_now = sess.load(root)
        item = clip(root, a)
        assert app_mod._render_safety(root, sess_now, item) == "wait"
        assert queued_texts == [(item["prompt"], "video", a)] and seen_waiters[-1] == ("u", "n", "c", "v", a), seen_waiters
        state["r"] = ("pass",)
        assert app_mod._render_safety(root, sess_now, item) == "pass"
        state["r"] = ("block", "AB12CD34", "drugs")
        try:
            app_mod._render_safety(root, sess_now, item)
            raise AssertionError("应抛 SafetyBlocked")
        except gate.SafetyBlocked as e:
            assert e.ref == "AB12CD34"
        state["r"] = ("unavailable",)
        try:
            app_mod._render_safety(root, sess_now, item)
            raise AssertionError("应抛 SafetyUnavailable")
        except gate.SafetyUnavailable:
            pass
    finally:
        gate.lookup, gate.classify_async = real_lookup, real_async
        os.environ["STORYBOARD_SAFETY"] = "0"
    assert app_mod._render_runner.safety_check is app_mod._render_safety
    tmp3 = tempfile.TemporaryDirectory()
    root3 = Path(tmp3.name) / "users" / "u" / "novels" / "n" / "chapters" / "c" / "render" / "v"
    s3 = sess.build(root3, doc, owner=OWNER, patch={"budget_cny": 100000}, keyframes={})
    q = s3["clips"][0]["id"]
    s3 = sess.queue_run(root3, [q])
    with app_mod._render_runner._guard:
        app_mod._render_runner._checking[Runner._check_key(OWNER, q)] = "x"
    try:
        view = app_mod._film_view(s3)
    finally:
        with app_mod._render_runner._guard:
            app_mod._render_runner._checking.clear()
    flags = {c["id"]: c.get("safety_checking") for c in view["clips"]}
    assert flags[q] is True and sum(1 for f in flags.values() if f) == 1, flags
    print("7. app 接线与视图标注 ✓")
    # 7b. 同一段每轮都来问：用真实 gate，只分类一次，之后拿到结论（等待者键是 (用户, 作品, 版本, 片段)，没有重提逻辑）
    started, go, made = threading.Event(), threading.Event(), []

    def slow_pass(_m):
        started.set()
        assert go.wait(10)
        return json.dumps({"blocked": False, "category": None, "reason": ""})

    def make():
        made.append(1)
        return ChatInvoker(Settings(api_key="k", transport_retries=0), chat=FakeChat(responses=[slow_pass]))
    real_make = gate._make_chat
    gate._make_chat = make
    os.environ["STORYBOARD_SAFETY"] = "1"
    try:
        item = clip(root, a)
        assert not hasattr(app_mod, "_safety_asked"), "不再有重提绕行逻辑"
        for _ in range(3):
            assert app_mod._render_safety(root, sess.load(root), item) == "wait"
            if len(made) == 1:
                assert started.wait(10)
        assert len(made) == 1, made
        go.set()
        for _ in range(500):
            if not gate.pending():
                break
            __import__("time").sleep(0.01)
        assert app_mod._render_safety(root, sess.load(root), item) == "pass" and len(made) == 1
    finally:
        gate._make_chat = real_make
        os.environ["STORYBOARD_SAFETY"] = "0"
    print("7b. 只分类一次 ✓")

    # 8. 检查绑定快照（I1）：检查通过之后、begin_submit 之前正文被改并重新排队 → 不提交未检查的文本，下一轮重新检查
    tmp4 = tempfile.TemporaryDirectory()
    root4 = Path(tmp4.name) / "users" / "u" / "novels" / "n" / "chapters" / "c" / "render" / "v"
    sess.build(root4, doc, owner=OWNER, patch={"budget_cny": 100000}, keyframes={})
    t4 = firsts[0]
    asked4, flag = [], {"done": False}

    def check4(r, sn, c):
        asked4.append(c["prompt"])
        if not flag["done"]:
            flag["done"] = True
            with sess.mutate(r) as s2:
                next(x for x in sess.items(s2) if x["id"] == c["id"])["prompt"] = "未检查的新文本"
        return "pass"
    n_sub = len(fake.submitted)
    runner4 = Runner(builder, sleep=lambda _s: None, max_parallel=4, safety_check=check4)
    sess.queue_run(root4, [t4])
    runner4.watch(root4)
    runner4.tick()
    c4 = clip(root4, t4)
    assert len(fake.submitted) == n_sub and c4["state"] == "queued" and c4["attempts"] == [], c4
    assert all("未检查的新文本" not in str(r.prompt) for r in fake.submitted[n_sub:])
    runner4.tick()
    assert asked4[1] == "未检查的新文本", "下一轮对新文本重新检查"
    print("8. 检查绑定快照 ✓")

    # 9. 取消、移除会话时检查标记与等待登记一并清掉（M1）
    forgot = []
    tmp5 = tempfile.TemporaryDirectory()
    root5 = Path(tmp5.name) / "users" / "u" / "novels" / "n" / "chapters" / "c" / "render" / "v"
    sess.build(root5, doc, owner=OWNER, patch={"budget_cny": 100000}, keyframes={})
    runner5 = Runner(builder, sleep=lambda _s: None, max_parallel=4, safety_check=lambda *_a: "wait",
                     safety_forget=forgot.append)
    sess.queue_run(root5, [t4])
    runner5.watch(root5)
    runner5.tick()
    assert runner5.is_checking(OWNER, t4)
    sess.cancel(root5, t4)
    runner5.tick()
    assert not runner5.is_checking(OWNER, t4) and forgot == [("u", "n", "c", "v", t4)], forgot
    sess.queue_run(root5, [t4])
    runner5.watch(root5)
    runner5.tick()
    assert runner5.is_checking(OWNER, t4)
    runner5._forget(root5)
    assert not runner5.is_checking(OWNER, t4) and len(forgot) == 2
    runner5.release_checks(OWNER)          # 空操作也安全
    print("9. 检查标记随取消与移除清掉 ✓")

    # 10. 回调与作废互斥（第五轮）：回调进行中 release 要等回调结束；结束后标记清掉、forget 收到键
    forgot10 = []
    tmp6 = tempfile.TemporaryDirectory()
    root6 = Path(tmp6.name) / "users" / "u" / "novels" / "n" / "chapters" / "c" / "render" / "v"
    sess.build(root6, doc, owner=OWNER, patch={"budget_cny": 100000}, keyframes={})
    t6 = firsts[1]
    key6 = ("u", "n", "c", "v", t6)
    started10, go10 = threading.Event(), threading.Event()

    def check10(r, sn, c):
        started10.set()
        assert go10.wait(10)
        return "wait"
    runner6 = Runner(builder, sleep=lambda _s: None, max_parallel=4, safety_check=check10,
                     safety_forget=forgot10.append)
    sess.queue_run(root6, [t6])
    runner6.watch(root6)
    th = threading.Thread(target=runner6.tick)
    th.start()
    assert started10.wait(10)
    rel = threading.Thread(target=runner6.release_checks, args=(OWNER, {t6}))
    rel.start()
    rel.join(0.3)
    assert rel.is_alive() and forgot10 == [], "回调进行中，作废要等它结束（生命周期锁）"
    go10.set()
    th.join(10)
    rel.join(10)
    assert forgot10 == [key6] and not runner6.is_checking(OWNER, t6), forgot10
    print("10. 回调与作废互斥 ✓")

    # 11. 接口层：自由节点重跑作废旧登记；批量出片只作废 queue_run 实际迁移到 queued 的段
    calls = []
    runner_app = app_mod._render_runner
    real_forget, real_free_ctx, real_free_queue = runner_app.safety_forget, app_mod._free_ctx, app_mod.render_free.queue
    real_render_ctx, real_style = app_mod._render_ctx, app_mod._style_for
    tmp7 = tempfile.TemporaryDirectory()
    root7 = Path(tmp7.name) / "users" / "u" / "novels" / "n" / "chapters" / "c" / "render" / "v"
    sess.build(root7, doc, owner=OWNER, patch={"budget_cny": 100000}, keyframes={})
    runner_app.safety_forget = calls.append
    app_mod._free_ctx = lambda *_a, **_k: (root7, None)
    app_mod.render_free.queue = lambda r, _ctx, _fid, _e=None: sess.load(r)
    app_mod._render_ctx = lambda *_a: (root7, doc, {}, OWNER)
    app_mod._style_for = lambda *_a: None
    try:
        app_mod.render_free_run("n", "c", "v", "F1", None, user={"id": "u"})
        assert calls == [("u", "n", "c", "v", "F1")], calls
        waiting = firsts[2]
        sess.queue_run(root7, [waiting])                # 这一段已在排队等检查，与本次批量无关
        targets, total = sess.run_quote(sess.load(root7), None)
        want = {("u", "n", "c", "v", c["id"]) for c in targets}
        assert ("u", "n", "c", "v", waiting) not in want and want
        del calls[:]
        app_mod._film_run({"id": "u"}, "n", "c", "v", None, total)
        assert set(calls) == want and len(calls) == len(want), calls
    finally:
        runner_app.safety_forget, app_mod._free_ctx, app_mod.render_free.queue = real_forget, real_free_ctx, real_free_queue
        app_mod._render_ctx, app_mod._style_for = real_render_ctx, real_style
    print("11. 接口层只作废本次排队的 ✓")

    # 12. 迁移与作废在同一生命周期临界区（第五轮）：真实 gate + 假模型，经接口函数走
    from safety import store
    from safety.text import normalize, text_hash
    U = {"id": "u"}
    cur = {}
    replies = []

    def make12():
        return ChatInvoker(Settings(api_key="k", transport_retries=0), chat=FakeChat(responses=[replies.pop(0)]))

    def ok_reply():
        return json.dumps({"blocked": False, "category": None, "reason": ""})

    def new_root():
        t = tempfile.TemporaryDirectory()
        cur["tmp"] = t
        cur["root"] = Path(t.name) / "users" / "u" / "novels" / "n" / "chapters" / "c" / "render" / "v"
        sess.build(cur["root"], doc, owner=OWNER, patch={"budget_cny": 100000}, keyframes={})
        return cur["root"]

    def fresh(cid):
        p = clip(cur["root"], cid)["prompt"]
        with store._lock:
            store._verdicts_data().pop(text_hash(normalize(p)), None)

    def idle():
        for _ in range(500):
            if not gate.pending():
                return
            __import__("time").sleep(0.01)
        raise AssertionError("分类任务没跑完")

    def quote(cid):
        return sess.run_quote(sess.load(cur["root"]), [cid])[1]

    saved = (app_mod._render_runner, app_mod._render_ctx, app_mod._style_for, app_mod.novels.render_dir,
             gate._make_chat, sess.queue_run)
    runner8 = Runner(builder, sleep=lambda _s: None, max_parallel=4, safety_check=app_mod._render_safety,
                     safety_forget=gate.forget)
    app_mod._render_runner = runner8
    app_mod._render_ctx = lambda *_a: (cur["root"], doc, {}, OWNER)
    app_mod._style_for = lambda *_a: None
    app_mod.novels.render_dir = lambda *_a: cur["root"]
    gate._make_chat = make12
    os.environ["STORYBOARD_SAFETY"] = "1"
    try:
        # 12a. queue 之后、release 之前 runner 想登记检查：被挡到 release 之后，本轮终态不被删除
        r8 = new_root()
        x = firsts[0]
        fresh(x)
        replies[:] = ["坏输出"]
        queued, go = threading.Event(), threading.Event()
        real_q = saved[5]

        def q_wrap(*a, **k):
            out = real_q(*a, **k)
            queued.set()
            assert go.wait(10)
            return out
        sess.queue_run = q_wrap
        runner8.watch(r8)
        total = quote(x)
        t_run = threading.Thread(target=app_mod._film_run, args=(U, "n", "c", "v", [x], total))
        t_run.start()
        assert queued.wait(10)
        tk = threading.Thread(target=runner8.tick)
        tk.start()
        tk.join(0.5)
        idle()
        go.set()
        t_run.join(10)
        tk.join(10)
        sess.queue_run = real_q
        idle()
        runner8.tick()
        cx = clip(r8, x)
        assert cx["state"] == "failed" and cx["error_msg"]["code"] == "safety.unavailable" and replies == [], (cx["state"], replies)
        gate.forget(("u",), prefix=True)
        # 12b. 出片线程读到快照之后、写回之前，这一段被取消；它的检查报错 → 保持已取消，不变成 failed
        r8 = new_root()
        x2, y2 = firsts[0], firsts[1]
        sess.queue_run(r8, [x2])
        sess.queue_run(r8, [y2])
        asked12 = []

        def cb12b(r, sn, c):
            asked12.append(c["id"])
            if c["id"] == x2:
                app_mod._film_cancel(U, "n", "c", "v", y2)     # 同一轮 tick 里，y2 的快照已读过
                return "wait"
            raise gate.unavailable_error()
        runner8.safety_check = cb12b
        runner8.watch(r8)
        runner8.tick()
        cy = clip(r8, y2)
        assert cy["state"] == "planned" and not cy.get("error_msg"), (cy["state"], cy.get("error_msg"))
        assert asked12 == [x2], asked12
        runner8.safety_check = app_mod._render_safety
        gate.forget(("u",), prefix=True)
        # 12c. 旧回调在取消并重新排队之后才登记 → 不可能：取消与重排要等回调结束；旧回调的登记随后作废，新一轮重新分类
        r8 = new_root()
        x3 = firsts[2]
        fresh(x3)
        replies[:] = ["坏输出", ok_reply()]
        s3, g3 = threading.Event(), threading.Event()

        def cb12c(r, sn, c):
            s3.set()
            assert g3.wait(10)
            return app_mod._render_safety(r, sn, c)
        runner8.safety_check = cb12c
        total = quote(x3)
        sess.queue_run(r8, [x3])
        runner8.watch(r8)
        tk = threading.Thread(target=runner8.tick)
        tk.start()
        assert s3.wait(10)

        def cancel_and_rerun():
            app_mod._film_cancel(U, "n", "c", "v", x3)
            app_mod._film_run(U, "n", "c", "v", [x3], total)
        t_cr = threading.Thread(target=cancel_and_rerun)
        t_cr.start()
        t_cr.join(0.3)
        assert t_cr.is_alive(), "回调进行中，取消与重排要等它结束"
        g3.set()
        tk.join(10)
        t_cr.join(10)
        runner8.safety_check = app_mod._render_safety
        idle()                                        # 旧回调登记的任务：不可用，但票据已作废
        runner8.tick()                                # 新一轮：重新登记、重新分类（通过）
        idle()
        runner8.tick()
        cx3 = clip(r8, x3)
        assert cx3["state"] == "running" and replies == [], (cx3["state"], cx3.get("error_msg"), replies)
        gate.forget(("u",), prefix=True)
        # 12d. 迁移失败（金额对不上、不能取消）不 release
        r8 = new_root()
        spy = []
        runner8.safety_forget = spy.append
        try:
            app_mod._film_run(U, "n", "c", "v", [firsts[0]], quote(firsts[0]) + 1)
            raise AssertionError("应 409")
        except app_mod.HTTPException as e:
            assert e.status_code == 409
        try:
            app_mod._film_cancel(U, "n", "c", "v", firsts[0])
            raise AssertionError("应 409")
        except app_mod.HTTPException as e:
            assert e.status_code == 409
        assert spy == [], spy
        runner8.safety_forget = gate.forget
    finally:
        (app_mod._render_runner, app_mod._render_ctx, app_mod._style_for, app_mod.novels.render_dir,
         gate._make_chat, sess.queue_run) = saved
        os.environ["STORYBOARD_SAFETY"] = "0"
    print("12. 迁移与作废同一临界区 ✓")

    # 13. 提交凭据是实际检查过的那份快照（终审 1）：tick 读到 A → 检查前改成 B（检查的是 B）→ 提交前改回 A：不提交
    tmp9 = tempfile.TemporaryDirectory()
    root9 = Path(tmp9.name) / "users" / "u" / "novels" / "n" / "chapters" / "c" / "render" / "v"
    sess.build(root9, doc, owner=OWNER, patch={"budget_cny": 100000}, keyframes={})
    x9, y9 = firsts[0], firsts[1]
    A9 = clip(root9, y9)["prompt"]
    B9 = A9 + "（检查过的改写）"

    def set_prompt(r, cid, text):
        with sess.mutate(r) as s2:
            next(x for x in sess.items(s2) if x["id"] == cid)["prompt"] = text
    checks13 = []

    def cb13(r, sn, c):
        checks13.append((c["id"], c["prompt"]))
        if c["id"] == x9:
            set_prompt(r, y9, B9)                       # 取消、编辑、重排：y9 的 tick 快照仍是 A
            return "wait"
        return "pass"
    real_begin = sess.begin_submit

    def begin13(r, cid, h=None):
        if cid == y9:
            set_prompt(r, y9, A9)                       # 检查之后、提交之前又改回 A
        return real_begin(r, cid, h)
    runner9 = Runner(builder, sleep=lambda _s: None, max_parallel=4, safety_check=cb13)
    sess.queue_run(root9, [x9, y9])
    runner9.watch(root9)
    n_sub = len(fake.submitted)
    sess.begin_submit = begin13
    try:
        runner9.tick()
    finally:
        sess.begin_submit = real_begin
    assert (y9, B9) in checks13 and (y9, A9) not in checks13, checks13
    c9 = clip(root9, y9)
    assert len(fake.submitted) == n_sub and c9["state"] == "queued" and c9["attempts"] == [], \
        "检查的是 B，提交时是 A：不提交"
    print("13. 提交凭据是检查过的快照 ✓")

    # 14. 自由节点：检查正文 + 引用资产名称（终审 2）；检查时的名称映射作为凭据随快照交给 request_builder
    import copy
    from render import compose as compose_mod
    cards = doc["assets"]["characters"]
    aid = cards[0]["id"]
    free = {"id": "F01", "prompt": "雨夜街头", "refs": [aid], "first_frame": None, "duration": 4.0}
    s14 = {"owner": OWNER}
    bad_doc = copy.deepcopy(doc)
    bad_doc["assets"]["characters"][0]["name"] = "含有 child porn 的名字"
    real_get_version, real_make = app_mod.novels.get_version, gate._make_chat
    cur_doc = {"d": bad_doc}
    app_mod.novels.get_version = lambda *_a: {"result": cur_doc["d"]}
    gate._make_chat = lambda: (_ for _ in ()).throw(RuntimeError("测试不调模型"))
    os.environ["STORYBOARD_SAFETY"] = "1"
    seen14 = []
    real_lookup = gate.lookup
    try:
        try:
            app_mod._render_safety(None, s14, free)
            raise AssertionError("资产名称违规应被拦下")
        except gate.SafetyBlocked:
            pass
        cur_doc["d"] = doc
        gate.lookup = lambda text, ctx, waiter=None: seen14.append(text) or ("pass",)
        out = app_mod._render_safety(None, s14, free)
        name0 = cards[0]["name"]
        assert seen14[-1] == compose_mod.free_check_text(free, {aid: name0}) and name0 in seen14[-1], seen14
        assert out == ("pass", {aid: name0}), out
    finally:
        app_mod.novels.get_version, gate._make_chat, gate.lookup = real_get_version, real_make, real_lookup
        os.environ["STORYBOARD_SAFETY"] = "0"
    # runner 把凭据随快照交给 request_builder
    tmp10 = tempfile.TemporaryDirectory()
    root10 = Path(tmp10.name) / "users" / "u" / "novels" / "n" / "chapters" / "c" / "render" / "v"
    sess.build(root10, doc, owner=OWNER, patch={"budget_cny": 100000}, keyframes={})
    got_proof = []

    def builder14(r, sn, c):
        got_proof.append(c.get("safety_proof"))
        return builder(r, sn, c)
    runner10 = Runner(builder14, sleep=lambda _s: None, max_parallel=4,
                      safety_check=lambda *_a: ("pass", {"C01": "检查时的名字"}))
    sess.queue_run(root10, [firsts[0]])
    runner10.watch(root10)
    runner10.tick()
    assert got_proof == [{"C01": "检查时的名字"}] and clip(root10, firsts[0])["state"] == "running", got_proof
    # _render_request 把凭据交给 request_for_free（names=）
    captured = {}
    real_rff = app_mod.render_compose.request_for_free
    real_kf, real_style2, real_tail = app_mod._keyframe_paths, app_mod._style_for, app_mod.render_free.tail_frame
    app_mod.render_compose.request_for_free = lambda *a, **k: captured.update(k) or ("req", None)
    app_mod.novels.get_version = lambda *_a: {"result": doc}
    app_mod._keyframe_paths = lambda *_a: {}
    app_mod._style_for = lambda *_a: None
    app_mod.render_free.tail_frame = lambda *_a: None
    try:
        sess_v = {"owner": OWNER, "provider": "fake", "model": "fake-1"}
        app_mod._render_request(None, sess_v, dict(free, safety_proof={aid: "凭据名"}))
        assert captured.get("names") == {aid: "凭据名"}, captured
    finally:
        app_mod.render_compose.request_for_free = real_rff
        app_mod.novels.get_version, app_mod._keyframe_paths = real_get_version, real_kf
        app_mod._style_for, app_mod.render_free.tail_frame = real_style2, real_tail
    print("14. 自由节点检查资产名称、凭据随快照 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
