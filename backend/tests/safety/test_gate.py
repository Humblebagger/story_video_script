#!/usr/bin/env python3
"""判定入口：顺序（缓存含放行 → 词表 → 模型）、拦截结论缓存、不可用、模型拒答不缓存、记账、
开关、出片线程用的 lookup / classify_async。只用 FakeChat。用法: python3 tests/safety/test_gate.py"""
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tests" / "pipeline"))
import _noenv  # noqa: E402,F401  测试不读真实 .env

_TMP = tempfile.TemporaryDirectory()
os.environ["STORYBOARD_DATA_DIR"] = _TMP.name     # 必须在导入 server.* / safety.* 之前
os.environ["ANTHROPIC_BASE_URL"] = "http://127.0.0.1:9"
os.environ["STORYBOARD_SAFETY"] = "1"             # _noenv 缺省关掉；本测试要开着

from fakes import FakeChat  # noqa: E402
from pipeline.chat import ChatInvoker, LLMError  # noqa: E402
from pipeline.config import Settings  # noqa: E402
from safety import blocklist, gate, store  # noqa: E402
from safety.text import text_hash  # noqa: E402
from server import usage  # noqa: E402

CTX = {"stage": "convert", "user_id": "a" * 12, "novel_id": "n1", "chapter_id": "c1", "version_id": "v1"}
CALLS = []


def script(*responses):
    """之后的每次分类调用依次用这些回复；CALLS 记下调用次数。"""
    queue = list(responses)

    def make():
        CALLS.append(1)
        return ChatInvoker(Settings(api_key="k", transport_retries=0), chat=FakeChat(responses=[queue.pop(0)]))
    gate._make_chat = make


def reply(blocked, category=None, reason=""):
    return json.dumps({"blocked": blocked, "category": category, "reason": reason}, ensure_ascii=False)


def refuse(_messages):
    raise LLMError.coded("llm.content_blocked")


def must_raise(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc as e:
        return e
    raise AssertionError(f"应抛 {exc.__name__}")


def wait_idle():
    for _ in range(500):
        if not gate.pending():
            return
        time.sleep(0.01)
    raise AssertionError("分类任务没跑完")


def main() -> int:
    # 1. 通过：写缓存，同文本第二次不调模型；记一条 safety 用量
    script(reply(False))
    assert gate.check_sync("他推门进屋。", CTX) is None and len(CALLS) == 1
    assert gate.check_sync(" 他推门进屋。\r\n", CTX) is None and len(CALLS) == 1, "规范化后同文本走缓存"
    rows = [r for r in usage.read() if r["purpose"] == "safety"]
    assert len(rows) == 1 and rows[0]["user_id"] == "a" * 12 and rows[0]["novel_id"] == "n1" and rows[0]["ok"]
    assert gate.check_sync("  ", CTX) is None and len(CALLS) == 1, "空文本不检查"
    print("1. 通过与缓存、记账 ✓")

    # 2. 拦截：异常带类别引用与编号；结论缓存，重复提交同一编号、次数加一、不再调模型
    script(reply(True, "sexual", "露骨描写"))
    e = must_raise(gate.SafetyBlocked, gate.check_sync, "违规正文甲", CTX)
    m = e.as_msg()
    assert m["code"] == "safety.blocked" and m["params"]["category"] == {"t": "ref", "code": "safety.category.sexual"}
    assert m["ref"] == e.ref and f"（参考编号 {e.ref}）" in m["message"] and "色情" in m["message"]
    n = len(CALLS)
    e2 = must_raise(gate.SafetyBlocked, gate.check_sync, "违规正文甲", CTX)
    assert e2.ref == e.ref and len(CALLS) == n and store.find_block(e.ref)["hits"] == 2
    assert store.find_block(e.ref)["reason"] == "露骨描写" and store.find_block(e.ref)["excerpt"] == "违规正文甲"
    print("2. 拦截与结论缓存 ✓")

    # 3. 放行后同文本通过；改一个字重新检查
    store.release(e.ref, "root")
    assert gate.check_sync("违规正文甲", CTX) is None and len(CALLS) == n
    script(reply(False))
    assert gate.check_sync("违规正文乙", CTX) is None and len(CALLS) == n + 1
    print("3. 放行 ✓")

    # 4. 词表命中不调模型，理由是词表的代码；放行条目先于词表
    n = len(CALLS)
    e = must_raise(gate.SafetyBlocked, gate.check_sync, "含有 child porn 的文本", CTX)
    row = store.find_block(e.ref)
    assert len(CALLS) == n and row["category"] == "minor_sexual" and row["reason_code"] == "safety.reason.blocklist"
    store.release(e.ref, "root")
    assert gate.check_sync("含有 child porn 的文本", CTX) is None and len(CALLS) == n, "放行盖过词表"
    print("4. 词表与顺序 ✓")

    # 5. 不可用：不缓存；下次重新调模型
    script("不是 JSON", reply(False))
    n = len(CALLS)
    e = must_raise(gate.SafetyUnavailable, gate.check_sync, "待定文本", CTX)
    assert e.as_msg()["code"] == "safety.unavailable" and store.get_verdict(text_hash("待定文本")) is None
    assert gate.check_sync("待定文本", CTX) is None and len(CALLS) == n + 2
    assert [r["ok"] for r in usage.read() if r["purpose"] == "safety"][-2:] == [False, True]
    print("5. 不可用 ✓")

    # 6. 模型拒答：unspecified 拦截、不写结论缓存、每次都重新问、记录合并
    script(refuse, refuse)
    e = must_raise(gate.SafetyBlocked, gate.check_sync, "被拒文本", CTX)
    assert e.as_msg()["params"]["category"]["code"] == "safety.category.unspecified"
    assert store.get_verdict(text_hash("被拒文本")) is None and store.find_block(e.ref)["releasable"] is False
    e2 = must_raise(gate.SafetyBlocked, gate.check_sync, "被拒文本", CTX)
    assert e2.ref == e.ref and store.find_block(e.ref)["hits"] == 2
    print("6. 模型拒答 ✓")

    # 7. lookup / classify_async：未知返回 None；排队一次；跑完后 lookup 给结论
    vctx = dict(CTX, stage="video", clip_id="E01-C01")
    assert gate.lookup("他推门进屋。", vctx) == ("pass",)
    assert gate.lookup("新提示词", vctx) is None
    started, go = threading.Event(), threading.Event()

    def hold(_m):
        started.set()
        assert go.wait(10), "测试没放行分类任务"
        return reply(True, "drugs", "制毒方法")
    script(hold)
    n = len(CALLS)
    assert gate.classify_async("新提示词", vctx) is True
    assert started.wait(10), "首个分类任务应已开始"
    assert gate.pending() == 1 and gate.lookup("新提示词", vctx) is None
    assert gate.classify_async("新提示词", vctx) is False, "同一 hash 同时只排一个"
    go.set()
    wait_idle()
    r = gate.lookup("新提示词", vctx)
    assert r[0] == "block" and r[2] == "drugs" and len(CALLS) == n + 1
    assert store.find_block(r[1])["stage"] == "video" and store.find_block(r[1])["clip_id"] == "E01-C01"
    assert gate.lookup("含有 child porn 的另一段", vctx)[0] == "block", "词表在 lookup 里就拦"
    print("7. 异步分类 ✓")

    # 8. 异步不可用：lookup 报一次 unavailable，之后回到未知
    script("坏输出")
    assert gate.classify_async("又一条提示词", vctx) is True
    wait_idle()
    assert gate.lookup("又一条提示词", vctx) == ("unavailable",)
    assert gate.lookup("又一条提示词", vctx) is None
    assert gate.lookup("又一条提示词", vctx, "w") is None, "另一个等待者没登记过，不会读到别人的结论"
    print("8. 异步不可用 ✓")

    # 8b. 异步模型拒答：不进结论缓存，但每个等待者都读到同编号的 unspecified 拦截；读完清掉，再检查重新分类
    started, go = threading.Event(), threading.Event()

    def hold_refuse(_m):
        started.set()
        assert go.wait(10)
        raise LLMError.coded("llm.content_blocked")
    script(hold_refuse)
    assert gate.classify_async("被拒的提示词", vctx, "a") is True and started.wait(10)
    assert gate.classify_async("被拒的提示词", vctx, "b") is False, "第二个等待者"
    for _ in range(3):      # 同一等待者每轮重复调用：不重复登记
        assert gate.classify_async("被拒的提示词", vctx, "a") is False
    go.set()
    wait_idle()
    assert store.get_verdict(text_hash("被拒的提示词")) is None
    ra, rb = gate.lookup("被拒的提示词", vctx, "a"), gate.lookup("被拒的提示词", vctx, "b")
    assert ra[0] == "block" and ra[2] == "unspecified" and ra == rb, (ra, rb)
    assert store.find_block(ra[1])["releasable"] is False
    assert gate.lookup("被拒的提示词", vctx, "a") is None and gate.lookup("被拒的提示词", vctx, "b") is None, \
        "各自读完即清，旧结论不再返回"
    script(reply(False))
    n = len(CALLS)
    assert gate.classify_async("被拒的提示词", vctx, "a") is True
    wait_idle()
    assert gate.lookup("被拒的提示词", vctx, "a") == ("pass",) and len(CALLS) == n + 1, "重新分类"
    print("8b. 异步模型拒答 ✓")

    # 9. 开关关掉：一律通过、不调模型、不查词表
    os.environ["STORYBOARD_SAFETY"] = "0"
    try:
        n = len(CALLS)
        assert gate.check_sync("含有 child porn 的第三段", CTX) is None
        assert gate.lookup("随便什么", vctx) == ("pass",) and len(CALLS) == n
    finally:
        os.environ["STORYBOARD_SAFETY"] = "1"
    print("9. 开关 ✓")

    # 10. 分条检查：每条单独查缓存，只有没缓存的拼成一次分类；通过后每条都记通过；拦截记拼接摘录
    n = len(CALLS)
    script(reply(False))
    gate.check_items_sync(["条目甲", "条目乙", "条目甲", "  "], CTX)
    assert len(CALLS) == n + 1
    assert store.get_verdict(text_hash("条目甲"))["verdict"] == "pass" and store.get_verdict(text_hash("条目乙"))["verdict"] == "pass"
    gate.check_items_sync(["条目甲", "条目乙"], CTX)
    assert len(CALLS) == n + 1, "全部有缓存：零次调用"
    seen = []
    gate._make_chat = lambda: ChatInvoker(Settings(api_key="k", transport_retries=0), chat=FakeChat(
        responses=[lambda m: (seen.append(m[-1].content), reply(False))[1]]))
    gate.check_items_sync(["条目甲", "条目丙", "条目丁"], CTX)
    assert len(seen) == 1 and "条目丙" in seen[0] and "条目丁" in seen[0] and "条目甲" not in seen[0], seen
    assert "条目丙\n\n条目丁" in seen[0]
    script(reply(True, "sexual", "露骨"))
    try:
        gate.check_items_sync(["条目甲", "条目戊", "条目己"], CTX)
        raise AssertionError("应拦截")
    except gate.SafetyBlocked:
        pass
    assert store.get_verdict(text_hash("条目戊")) is None or store.get_verdict(text_hash("条目戊"))["verdict"] != "pass"
    try:
        gate.check_items_sync(["正常", "含有 child porn 的条目"], CTX)
        raise AssertionError("词表应拦")
    except gate.SafetyBlocked:
        pass
    print("10. 分条检查 ✓")

    # 11. 迟到的拦截结果不覆盖放行：两个检查同时分类，先拦、放行、后拦 → 后一个按通过处理
    s1, g1, s2, g2 = (threading.Event() for _ in range(4))

    def slow(started, go):
        def f(_m):
            started.set()
            assert go.wait(10)
            return reply(True, "sexual", "露骨")
        return f
    script(slow(s1, g1), slow(s2, g2))
    out = {}

    def run(name):
        try:
            gate.check_sync("并发竞争文本", CTX)
            out[name] = "pass"
        except gate.SafetyBlocked as e:
            out[name] = e
        except BaseException as e:  # noqa: BLE001
            out[name] = e
    t1 = threading.Thread(target=run, args=("a",))
    t1.start()
    assert s1.wait(10)
    t2 = threading.Thread(target=run, args=("b",))
    t2.start()
    assert s2.wait(10)
    g1.set()
    t1.join(10)
    assert isinstance(out["a"], gate.SafetyBlocked), out
    store.release(out["a"].ref, "root")
    g2.set()
    t2.join(10)
    assert out["b"] == "pass", out
    assert len([r for r in store.list_blocks() if r["excerpt"] == "并发竞争文本"]) == 1
    assert store.get_verdict(text_hash("并发竞争文本"))["released"] is True
    print("11. 迟到结果不覆盖放行 ✓")

    # 12. 存储写盘失败：同步检查、分条检查、lookup 都按不可用处理（SafetyUnavailable），不是 OSError
    real_write = store._write

    def disk_full(path, data):
        raise OSError("disk full")
    store._write = disk_full
    try:
        must_raise(gate.SafetyUnavailable, gate.check_sync, "含有 child porn 的磁盘满", CTX)          # 词表命中记录失败
        script(reply(False))
        must_raise(gate.SafetyUnavailable, gate.check_sync, "磁盘满的正常文本", CTX)                     # 写通过结论失败
        script(reply(False))
        must_raise(gate.SafetyUnavailable, gate.check_items_sync, ["磁盘满条目甲", "磁盘满条目乙"], CTX)
        assert gate.lookup("含有 child porn 的磁盘满二", vctx) == ("unavailable",)
    finally:
        store._write = real_write
    script(reply(False))
    assert gate.check_sync("磁盘满的正常文本", CTX) is None, "恢复后能正常检查"
    print("12. 存储失败按不可用处理 ✓")

    # 13. 等待者身份（I2）：单个片段跨多轮 tick 只算一个等待者；失败后重试重新分类，旧结论不返回
    started, go = threading.Event(), threading.Event()

    def hold_refuse2(_m):
        started.set()
        assert go.wait(10)
        raise LLMError.coded("llm.content_blocked")
    script(hold_refuse2)
    w1 = ("u", "v", "E01-C01")
    assert gate.lookup("多轮提示词", vctx, w1) is None
    assert gate.classify_async("多轮提示词", vctx, w1) is True and started.wait(10)
    for _ in range(3):                                 # 后面几轮 tick：lookup 仍未知、classify_async 不重复登记
        assert gate.lookup("多轮提示词", vctx, w1) is None
        assert gate.classify_async("多轮提示词", vctx, w1) is False
    go.set()
    wait_idle()
    first = gate.lookup("多轮提示词", vctx, w1)
    assert first[0] == "block" and first[2] == "unspecified"
    assert gate.lookup("多轮提示词", vctx, w1) is None, "同一个片段只算一个等待者，读一次就没了（旧代结论不残留）"
    script(reply(False))                               # 用户重试：新一代检查，重新分类
    n = len(CALLS)
    assert gate.lookup("多轮提示词", vctx, w1) is None and gate.classify_async("多轮提示词", vctx, w1) is True
    wait_idle()
    assert gate.lookup("多轮提示词", vctx, w1) == ("pass",) and len(CALLS) == n + 1
    # 两个片段共享同一 hash：各读一次同一结论，一次分类
    started, go = threading.Event(), threading.Event()

    def hold_unavail(_m):
        started.set()
        assert go.wait(10)
        return "坏输出"
    script(hold_unavail)
    n = len(CALLS)
    wa, wb = ("u", "v", "E01-C02"), ("u", "v", "E01-C03")
    assert gate.classify_async("共享提示词", vctx, wa) is True and started.wait(10)
    assert gate.classify_async("共享提示词", vctx, wb) is False
    go.set()
    wait_idle()
    assert len(CALLS) == n + 1
    assert gate.lookup("共享提示词", vctx, wa) == ("unavailable",) and gate.lookup("共享提示词", vctx, wb) == ("unavailable",)
    assert gate.lookup("共享提示词", vctx, wa) is None and gate.lookup("共享提示词", vctx, wb) is None
    # 片段 a 读完后重试 → 新一代；片段 b 的未读结论不受影响（这里 b 也已读完，改测未读情形）
    script(hold_unavail)
    started.clear()
    go.clear()
    assert gate.classify_async("共享提示词", vctx, wa) is True and gate.classify_async("共享提示词", vctx, wb) is False
    assert started.wait(10)
    go.set()
    wait_idle()
    assert gate.lookup("共享提示词", vctx, wa) == ("unavailable",)
    script(reply(False))
    assert gate.classify_async("共享提示词", vctx, wa) is True      # a 读完后重试，开始新一代
    wait_idle()
    assert gate.lookup("共享提示词", vctx, wb) == ("unavailable",), "b 还没读的上一代结论不被 a 的重试吞掉"
    print("13. 等待者身份 ✓")

    # 14. 批量检查合并文本的缓存（I1）：重复拦截零新增分类；放行后分类器不可用仍通过
    script(reply(True, "drugs", "x"))
    batch = ["批量甲", "批量乙"]
    e1 = must_raise(gate.SafetyBlocked, gate.check_items_sync, batch, CTX)
    n = len(CALLS)
    e2 = must_raise(gate.SafetyBlocked, gate.check_items_sync, batch, CTX)
    assert e2.ref == e1.ref and len(CALLS) == n, "合并文本命中拦截缓存，不再分类"
    store.release(e1.ref, "root")
    gate._make_chat = lambda: (_ for _ in ()).throw(RuntimeError("分类器不可用"))
    assert gate.check_items_sync(batch, CTX) is None, "放行后不调分类器也通过"
    assert store.get_verdict(text_hash("批量甲"))["verdict"] == "pass" and store.get_verdict(text_hash("批量乙"))["verdict"] == "pass"
    print("14. 批量合并文本缓存 ✓")

    assert blocklist.match("含有 child porn 的第三段") == "minor_sexual"
    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        _TMP.cleanup()
    sys.exit(code)
