#!/usr/bin/env python3
"""出片线程的内容检查：在 begin_submit 之前问回调；等待时本轮跳过且段仍排队、没有新尝试；
拦截或不可用时段失败且不提交；回调自己出错也不放行；不传回调时行为不变；待检查集合。
用法: python3 tests/render/test_safety_runner.py"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
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
    gate.lookup = lambda text, ctx: state["r"]
    gate.classify_async = lambda text, ctx: queued_texts.append((text, ctx["stage"], ctx["clip_id"])) or True
    try:
        sess_now = sess.load(root)
        item = clip(root, a)
        assert app_mod._render_safety(root, sess_now, item) == "wait"
        assert queued_texts == [(item["prompt"], "video", a)]
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
        app_mod._render_runner._checking.add(Runner._check_key(OWNER, q))
    try:
        view = app_mod._film_view(s3)
    finally:
        with app_mod._render_runner._guard:
            app_mod._render_runner._checking.clear()
    flags = {c["id"]: c.get("safety_checking") for c in view["clips"]}
    assert flags[q] is True and sum(1 for f in flags.values() if f) == 1, flags
    print("7. app 接线与视图标注 ✓")
    # 7b. 同一段每轮都来问：只交一次分类
    state["r"] = None
    queued_texts.clear()
    gate.lookup, gate.classify_async = lambda text, ctx: state["r"], \
        (lambda text, ctx: queued_texts.append(1) or True)
    try:
        app_mod._safety_asked.clear()
        for _ in range(3):
            assert app_mod._render_safety(root, sess.load(root), clip(root, a)) == "wait"
        assert len(queued_texts) == 1, queued_texts
    finally:
        gate.lookup, gate.classify_async = real_lookup, real_async
        app_mod._safety_asked.clear()
    print("7b. 只交一次分类 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
