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

    # 10. 迟到的拦截结果不能覆盖放行（同一文本两个检查交错：先拦、放行、后拦）
    first = store.record_block("竞争文本", category="sexual", reason="a", ctx=CTX)
    store.release(first, "root")
    n_rows = len(store.list_blocks())
    assert store.record_block("竞争文本", category="sexual", reason="b", ctx=CTX) is None, "已放行：返回 None 让调用方放行"
    assert store.record_block("竞争文本", category="unspecified", reason_code=store.REFUSED, ctx=CTX,
                              cache=False) is None
    assert len(store.list_blocks()) == n_rows, "不新增记录"
    v = store.get_verdict(text_hash("竞争文本"))
    assert v["verdict"] == "pass" and v["released"] is True, "放行仍然有效"
    store.set_pass(text_hash("竞争文本"))
    assert store.get_verdict(text_hash("竞争文本"))["released"] is True
    real_write = store._write
    print("10. 迟到结果不覆盖放行 ✓")

    # 11. 放行的写入顺序与失败恢复：先结论缓存后记录；任一写失败内存从盘上重载；重试能补完
    def failing(nth):
        calls = {"n": 0}

        def w(path, data):
            calls["n"] += 1
            if calls["n"] == nth:
                raise OSError("disk full")
            return real_write(path, data)
        return w
    rid1 = store.record_block("恢复文本一", category="drugs", reason="x", ctx=CTX)
    store._write = failing(1)                      # 第一次写（结论缓存）失败
    try:
        must_raise(OSError, store.release, rid1, "root")
    finally:
        store._write = real_write
    assert store.find_block(rid1)["status"] == "blocked" and store.get_verdict(text_hash("恢复文本一"))["verdict"] == "block"
    store._write = failing(2)                      # 第二次写（记录）失败：放行已写进结论缓存
    try:
        must_raise(OSError, store.release, rid1, "root")
    finally:
        store._write = real_write
    assert store.find_block(rid1)["status"] == "blocked", "内存已从盘上重载，记录仍是未放行"
    assert store.get_verdict(text_hash("恢复文本一"))["released"] is True, "盘上结论已是放行"
    assert store.release(rid1, "root")["status"] == "released", "重试补完"
    store._reset_for_test()
    assert store.find_block(rid1)["status"] == "released" and store.get_verdict(text_hash("恢复文本一"))["released"]
    # 重复放行已放行的记录：结论缺失时补写
    with store._lock:
        del store._verdicts_data()[text_hash("恢复文本一")]
    assert store.release(rid1, "root")["status"] == "released"
    store._reset_for_test()
    assert store.get_verdict(text_hash("恢复文本一"))["released"] is True, "重复放行也把结论落盘"
    # 写拦截记录失败：不留半截内存状态
    rows_before = len(store.list_blocks())
    store._write = failing(1)
    try:
        must_raise(OSError, store.record_block, "写失败文本", category="drugs", reason="x", ctx=CTX)
    finally:
        store._write = real_write
    assert len(store.list_blocks()) == rows_before and store.get_verdict(text_hash("写失败文本")) is None
    print("11. 放行顺序与失败恢复 ✓")

    # 12. 加载对账：记录已放行而结论缓存不是放行通过 → 补写并落盘
    rid2 = store.record_block("对账文本", category="drugs", reason="x", ctx=CTX)
    with store._lock:
        row = next(r for r in store._blocks_data() if r["id"] == rid2)
        row.update(status="released", released_by="root", released_at=row["at"])
        store._save_blocks()                        # 只写记录，结论缓存仍是 block
    store._reset_for_test()
    v = store.get_verdict(text_hash("对账文本"))
    assert v["verdict"] == "pass" and v["released"] is True
    import json as _json
    on_disk = _json.loads(store.VERDICTS_FILE.read_text(encoding="utf-8"))
    assert on_disk[text_hash("对账文本")]["released"] is True, "对账结果落盘"
    print("12. 加载对账 ✓")

    # 13. 命中缓存拦截（touch_block）也触发到期清理
    rid3 = store.record_block("清理文本", category="drugs", reason="理由", ctx=CTX)
    old3 = (datetime.now(timezone.utc) - timedelta(days=91)).isoformat(timespec="seconds")
    with store._lock:
        next(r for r in store._blocks_data() if r["id"] == rid3)["at"] = old3
        store._save_blocks()
    store._last_cleanup = -1e9
    store.touch_block(rid3)
    row3 = next(r for r in store.list_blocks() if r["id"] == rid3)
    assert row3["excerpt"] == "" and row3["reason"] == "", "只命中缓存、没有新记录，也要清理"
    print("13. touch_block 触发清理 ✓")

    # 14. 并发：同 hash 并发 record_block 合并成一条、hits 累计；不同 hash 各一条；重载一致；线程异常传回主线程
    errors = []

    def run(fn):
        def inner():
            try:
                fn()
            except BaseException as e:  # noqa: BLE001
                errors.append(e)
        return inner
    same_ids, barrier = [], threading.Barrier(8)

    def same():
        barrier.wait()
        same_ids.append(store.record_block("并发同文", category="sexual", reason="r", ctx=CTX))

    def diff(i):
        def f():
            barrier.wait()
            store.record_block(f"并发异文{i}", category="drugs", reason="r", ctx=CTX)
        return f
    ts = [threading.Thread(target=run(same)) for _ in range(4)] + \
         [threading.Thread(target=run(diff(i))) for i in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    if errors:
        raise errors[0]
    assert len(set(same_ids)) == 1 and len(same_ids) == 4
    store._reset_for_test()
    assert store.find_block(same_ids[0])["hits"] == 4
    assert sum(1 for r in store.list_blocks() if r["excerpt"].startswith("并发异文")) == 4
    assert all(store.get_verdict(text_hash(f"并发异文{i}"))["verdict"] == "block" for i in range(4))
    print("14. 并发拦截记录 ✓")

    # 15. 对账补写失败不吞（I3）：失败 → 恢复 → 重复放行 → 重载
    rid4 = store.record_block("对账失败文本", category="drugs", reason="x", ctx=CTX)
    with store._lock:
        row = next(r for r in store._blocks_data() if r["id"] == rid4)
        row.update(status="released", released_by="root", released_at=row["at"])
        store._save_blocks()                        # 记录已放行，结论缓存仍是 block
    store._reset_for_test()
    store._write = (lambda path, data: (_ for _ in ()).throw(OSError("disk full")))
    try:
        must_raise(OSError, store.get_verdict, text_hash("对账失败文本"))
    finally:
        store._write = real_write
    assert _json.loads(store.VERDICTS_FILE.read_text(encoding="utf-8"))[text_hash("对账失败文本")]["verdict"] == "block"
    assert store.get_verdict(text_hash("对账失败文本"))["released"] is True, "恢复后重新对账"
    writes = []
    store._write = lambda path, data: (writes.append(path), real_write(path, data))[1]
    try:
        assert store.release(rid4, "root")["status"] == "released"
    finally:
        store._write = real_write
    assert store.VERDICTS_FILE in writes, "重复放行也要写一次结论缓存"
    store._reset_for_test()
    assert _json.loads(store.VERDICTS_FILE.read_text(encoding="utf-8"))[text_hash("对账失败文本")]["released"] is True
    print("15. 对账补写失败 ✓")

    # 16. 生成模型拒答是已发生的事件：放行后仍写不可放行记录、不碰结论缓存（I4）；预检查迟到结果仍受保护
    rid5 = store.record_block("放行后拒答", category="sexual", reason="x", ctx=CTX)
    store.release(rid5, "root")
    assert store.record_block("放行后拒答", category="unspecified", reason_code=store.REFUSED, ctx=CTX,
                              cache=False) is None, "预检查口径：受放行保护"
    aid = store.record_block("放行后拒答", category="unspecified", reason_code=store.REFUSED, ctx=CTX,
                             cache=False, audit=True)
    assert aid and aid != rid5 and store.find_block(aid)["releasable"] is False
    assert store.record_block("放行后拒答", category="unspecified", reason_code=store.REFUSED, ctx=CTX,
                              cache=False, audit=True) == aid and store.find_block(aid)["hits"] == 2, "同文合并"
    assert store.get_verdict(text_hash("放行后拒答"))["released"] is True, "放行不被碰"
    print("16. 生成拒答审计记录 ✓")

    # 17. release / purge 也触发到期清理（B1-6）
    for trigger in ("release", "purge"):
        rid6 = store.record_block(f"清理{trigger}", category="drugs", reason="理由", ctx=dict(CTX, novel_id="n77"))
        old6 = (datetime.now(timezone.utc) - timedelta(days=91)).isoformat(timespec="seconds")
        other = store.record_block(f"待放行{trigger}", category="drugs", reason="r", ctx=dict(CTX, novel_id="n78"))
        with store._lock:
            next(r for r in store._blocks_data() if r["id"] == rid6)["at"] = old6
            store._save_blocks()
        store._last_cleanup = -1e9
        if trigger == "release":
            store.release(other, "root")
        else:
            store.purge("a" * 12, "n78")
        assert next(r for r in store.list_blocks() if r["id"] == rid6)["excerpt"] == "", trigger
    print("17. release/purge 触发清理 ✓")

    # 18. 读取错误不当空数据（I4）：补写失败 → 重读失败 → 恢复 → 重复放行 → 重载
    rid7 = store.record_block("读失败文本", category="drugs", reason="x", ctx=CTX)
    with store._lock:
        row = next(r for r in store._blocks_data() if r["id"] == rid7)
        row.update(status="released", released_by="root", released_at=row["at"])
        store._save_blocks()
    store._reset_for_test()
    store._write = lambda path, data: (_ for _ in ()).throw(OSError("disk full"))
    try:
        must_raise(OSError, store.get_verdict, text_hash("读失败文本"))     # 对账补写失败
    finally:
        store._write = real_write
    real_read = store._read
    store._read = lambda path, default: (_ for _ in ()).throw(OSError("io error"))
    try:
        must_raise(OSError, store.get_verdict, text_hash("读失败文本"))     # 重读失败：不能把空 blocks 当真
        must_raise(OSError, store.find_block, rid7)
    finally:
        store._read = real_read
    assert store.find_block(rid7)["status"] == "released", "恢复后重读到真实记录"
    assert store.get_verdict(text_hash("读失败文本"))["released"] is True
    assert store.release(rid7, "root")["status"] == "released"
    store._reset_for_test()
    assert _json.loads(store.VERDICTS_FILE.read_text(encoding="utf-8"))[text_hash("读失败文本")]["released"] is True
    # 文件不存在才是空；损坏的 JSON 上抛
    assert real_read(store.DIR / "不存在.json", []) == []
    bad = store.DIR / "坏.json"
    bad.write_text("{坏", encoding="utf-8")
    must_raise(OSError, real_read, bad, {})
    print("18. 读取错误不当空数据 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        _TMP.cleanup()
    sys.exit(code)
