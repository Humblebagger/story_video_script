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
    from fakes import FakeChat
    from pipeline.chat import ChatInvoker
    from pipeline.config import Settings
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

    # 10. 回调期间取消（第四轮 2）：显式取消一律作废登记；回调返回后生命周期已变，丢弃 wait 与失败写回
    forgot10 = []
    tmp6 = tempfile.TemporaryDirectory()
    root6 = Path(tmp6.name) / "users" / "u" / "novels" / "n" / "chapters" / "c" / "render" / "v"
    sess.build(root6, doc, owner=OWNER, patch={"budget_cny": 100000}, keyframes={})
    t6 = firsts[1]
    key6 = ("u", "n", "c", "v", t6)
    started10, go10, mode = threading.Event(), threading.Event(), {"out": "wait"}

    def check10(r, sn, c):
        started10.set()
        assert go10.wait(10)
        if isinstance(mode["out"], Exception):
            raise mode["out"]
        return mode["out"]
    runner6 = Runner(builder, sleep=lambda _s: None, max_parallel=4, safety_check=check10,
                     safety_forget=forgot10.append)
    sess.queue_run(root6, [t6])
    runner6.watch(root6)
    th = threading.Thread(target=runner6.tick)
    th.start()
    assert started10.wait(10)
    sess.cancel(root6, t6)
    runner6.release_checks(OWNER, {t6})                # 回调还没返回：_checking 里没有这个键
    assert forgot10 == [key6], forgot10
    go10.set()
    th.join(10)
    assert not runner6.is_checking(OWNER, t6), "取消之后回调才返回的 wait 不恢复标记"
    # 10b. 回调期间取消并重新排队（自由节点重跑同理），回调随后报不可用：失败不写回新一轮
    started10.clear()
    go10.clear()
    mode["out"] = gate.unavailable_error()
    sess.queue_run(root6, [t6])
    runner6.watch(root6)
    th = threading.Thread(target=runner6.tick)
    th.start()
    assert started10.wait(10)
    sess.cancel(root6, t6)
    sess.queue_run(root6, [t6])
    runner6.release_checks(OWNER, {t6})
    go10.set()
    th.join(10)
    c6 = clip(root6, t6)
    assert c6["state"] == "queued" and c6["attempts"] == [] and not c6.get("error_msg"), c6
    mode["out"] = "pass"
    runner6.tick()                                     # 新一轮重新检查，按新结论提交
    assert clip(root6, t6)["state"] == "running"
    print("10. 回调期间取消 ✓")

    # 11. 接口层：自由节点重跑作废旧登记；批量出片只作废 queue_run 实际迁移到 queued 的段
    calls = []
    runner_app = app_mod._render_runner
    real_release, real_free_ctx, real_free_queue = runner_app.release_checks, app_mod._free_ctx, app_mod.render_free.queue
    real_render_ctx, real_style = app_mod._render_ctx, app_mod._style_for
    tmp7 = tempfile.TemporaryDirectory()
    root7 = Path(tmp7.name) / "users" / "u" / "novels" / "n" / "chapters" / "c" / "render" / "v"
    sess.build(root7, doc, owner=OWNER, patch={"budget_cny": 100000}, keyframes={})
    runner_app.release_checks = lambda owner, ids=None: calls.append((dict(owner), None if ids is None else set(ids)))
    app_mod._free_ctx = lambda *_a, **_k: (root7, None)
    app_mod.render_free.queue = lambda r, _ctx, _fid, _e=None: sess.load(r)
    app_mod._render_ctx = lambda *_a: (root7, doc, {}, OWNER)
    app_mod._style_for = lambda *_a: None
    try:
        app_mod.render_free_run("n", "c", "v", "F1", None, user={"id": "u"})
        assert calls == [(OWNER, {"F1"})], calls
        waiting = firsts[2]
        sess.queue_run(root7, [waiting])                # 这一段已在排队等检查，与本次批量无关
        targets, total = sess.run_quote(sess.load(root7), None)
        want = {c["id"] for c in targets}
        assert waiting not in want and want
        app_mod._film_run({"id": "u"}, "n", "c", "v", None, total)
        assert calls[-1] == (OWNER, want), calls[-1]
    finally:
        runner_app.release_checks, app_mod._free_ctx, app_mod.render_free.queue = real_release, real_free_ctx, real_free_queue
        app_mod._render_ctx, app_mod._style_for = real_render_ctx, real_style
    print("11. 接口层只作废本次排队的 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
