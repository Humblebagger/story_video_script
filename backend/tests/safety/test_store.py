#!/usr/bin/env python3
"""结论缓存与拦截记录：通过与拦截、同文本合并计数、策略版本失效、放行、模型拒答不缓存且不可放行、
淘汰、90 天清理、按作品清空、并发写不丢。全程临时数据目录。用法: python3 tests/safety/test_store.py"""
import os
import sys
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import _noenv  # noqa: E402,F401  测试不读真实 .env

_TMP = tempfile.TemporaryDirectory()
os.environ["STORYBOARD_DATA_DIR"] = _TMP.name     # 必须在导入 server.* / safety.store 之前

from safety import blocklist, store  # noqa: E402
from safety.text import text_hash  # noqa: E402

CTX = {"stage": "convert", "user_id": "a" * 12, "novel_id": "n1", "chapter_id": "c1", "version_id": "v1"}


def must_raise(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc as e:
        return e
    raise AssertionError(f"应抛 {exc.__name__}")


def main() -> int:
    # 1. 通过：写入后查得到；没写过的查不到
    assert store.get_verdict(text_hash("甲")) is None
    store.set_pass(text_hash("甲"))
    assert store.get_verdict(text_hash("甲"))["verdict"] == "pass"
    print("1. 通过结论 ✓")

    # 2. 拦截：编号是 8 位参考编号；同文本再拦返回同一个编号、次数加一、不新增记录
    bid = store.record_block("乙" * 400, category="sexual", reason="露骨描写", ctx=CTX)
    assert len(bid) == 8 and bid.isalnum() and bid.upper() == bid, bid
    v = store.get_verdict(text_hash("乙" * 400))
    assert v == {**v, "verdict": "block", "block_id": bid, "category": "sexual"}
    assert store.record_block("乙" * 400, category="sexual", reason="露骨描写", ctx=CTX) == bid
    rows = store.list_blocks()
    assert len(rows) == 1 and rows[0]["hits"] == 2 and rows[0]["excerpt"] == "乙" * 300
    assert rows[0]["stage"] == "convert" and rows[0]["user_id"] == "a" * 12 and rows[0]["status"] == "blocked"
    print("2. 拦截记录与合并计数 ✓")

    # 3. 策略版本变了：普通结论失效；放行过的不失效
    real_hash = blocklist._HASH
    released = store.release(bid, "root")
    assert released["status"] == "released" and released["released_by"] == "root"
    assert store.get_verdict(text_hash("乙" * 400)) == {**store.get_verdict(text_hash("乙" * 400)),
                                                        "verdict": "pass", "released": True}
    blocklist._HASH = "changed00000"
    try:
        assert store.get_verdict(text_hash("甲")) is None, "词表变了，普通通过结论失效"
        assert store.get_verdict(text_hash("乙" * 400))["verdict"] == "pass", "放行的不失效"
    finally:
        blocklist._HASH = real_hash
    assert store.release(bid, "root")["status"] == "released", "重复放行是幂等的"
    e = must_raise(store.NotFound, store.release, "ZZZZZZZZ", "root")
    assert e.code == "admin.safety.not_found" and e.params == {"ref": "ZZZZZZZZ"}
    print("3. 策略版本与放行 ✓")

    # 4. 模型拒答：只写记录、不写结论缓存、不可放行
    rid = store.record_block("丙", category="unspecified", reason_code=store.REFUSED, ctx=CTX, cache=False)
    assert store.get_verdict(text_hash("丙")) is None
    assert store.find_block(rid)["releasable"] is False
    e = must_raise(store.StoreError, store.release, rid, "root")
    assert e.code == "admin.safety.not_releasable"
    assert store.record_block("丙", category="unspecified", reason_code=store.REFUSED, ctx=CTX, cache=False) == rid
    print("4. 模型拒答记录 ✓")

    # 5. 列表筛选：状态、天数、编号（易混字符归一）；未放行计数
    assert [r["id"] for r in store.list_blocks(status="released")] == [bid]
    assert [r["id"] for r in store.list_blocks(status="blocked")] == [rid]
    assert [r["id"] for r in store.list_blocks(ref=rid.lower())] == [rid]
    assert store.list_blocks(ref="ZZZZZZZZ") == [] and len(store.list_blocks(days=7)) == 2
    assert store.count_blocked() == 1
    print("5. 列表筛选 ✓")

    # 6. 90 天清理：摘录与理由清空，记录保留
    old = (datetime.now(timezone.utc) - timedelta(days=91)).isoformat(timespec="seconds")
    with store._lock:
        store._blocks_data()[0]["at"] = old
        store._save_blocks()
    assert store.cleanup() == 1
    cleaned = next(r for r in store.list_blocks() if r["at"] == old)
    assert cleaned["excerpt"] == "" and cleaned["reason"] == "" and cleaned["hits"] >= 1
    assert store.cleanup() == 0
    print("6. 90 天清理 ✓")

    # 7. 删除作品 / 章节时清空对应摘录与理由
    other = dict(CTX, novel_id="n2", chapter_id="c9")
    b2 = store.record_block("丁", category="drugs", reason="x", ctx=other)
    b3 = store.record_block("戊", category="drugs", reason="y", ctx=dict(other, chapter_id="c8"))
    assert store.purge("a" * 12, "n2", "c9") == 1
    assert store.find_block(b2)["excerpt"] == "" and store.find_block(b3)["excerpt"] == "戊"
    assert store.purge("a" * 12, "n2") == 1 and store.find_block(b3)["excerpt"] == ""
    assert store.purge("b" * 12, "n2") == 0
    print("7. 按作品清空 ✓")

    # 8. 淘汰：超过上限按最早淘汰，放行的不淘汰
    real_max = store.MAX_VERDICTS
    store.MAX_VERDICTS = 5
    try:
        for i in range(10):
            store.set_pass(text_hash(f"淘汰{i}"))
        with store._lock:
            data = store._verdicts_data()
        assert sum(1 for v in data.values() if not v.get("released")) <= 5
        assert store.get_verdict(text_hash("乙" * 400))["released"] is True
        assert store.get_verdict(text_hash("淘汰9")) is not None
    finally:
        store.MAX_VERDICTS = real_max
    print("8. 淘汰 ✓")

    # 9. 并发：两个线程同时写结论不丢条目；落盘后重新加载内容一致
    def writer(tag):
        for i in range(50):
            store.set_pass(text_hash(f"{tag}{i}"))
    ts = [threading.Thread(target=writer, args=(t,)) for t in ("并", "发")]
    [t.start() for t in ts]
    [t.join() for t in ts]
    store._reset_for_test()
    assert all(store.get_verdict(text_hash(f"{t}{i}")) for t in ("并", "发") for i in range(50))
    assert len(store.list_blocks()) == 4
    print("9. 并发写与重新加载 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        _TMP.cleanup()
    sys.exit(code)
