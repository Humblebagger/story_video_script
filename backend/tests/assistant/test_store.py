#!/usr/bin/env python3
"""助手存档与限流：存档路径在小说目录下、别人的小说拿不到、清空删文件、每日计数按 UTC 当天、并发锁。
用法: python3 tests/assistant/test_store.py
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
_TMP = tempfile.TemporaryDirectory()
os.environ["STORYBOARD_DATA_DIR"] = _TMP.name     # 必须在导入 server.* 之前

from langchain_core.messages import HumanMessage  # noqa: E402
from assistant import store  # noqa: E402
from server import auth, novels, usage  # noqa: E402


def main() -> int:
    uid = auth.register("alice", "secret1")["id"]
    other = auth.register("bob", "secret1")["id"]
    nid = novels.create_novel(uid, "药")["id"]

    # 1. 路径在小说目录下；别人的小说抛 NotFound
    p = novels.assistant_db(uid, nid)
    assert p.name == "assistant.sqlite" and p.parent.name == nid
    try:
        novels.assistant_db(other, nid)
        raise AssertionError("别人的小说应抛 NotFound")
    except novels.NotFound:
        pass
    print("1. 存档路径与归属 ✓")

    # 2. 写一个检查点再读回；清空后文件不在
    assert not store.exists(uid, nid)
    with store.saver(uid, nid) as cp:
        from langgraph.graph import START, MessagesState, StateGraph
        g = StateGraph(MessagesState)
        g.add_node("noop", lambda s: {})
        g.add_edge(START, "noop")
        app = g.compile(checkpointer=cp)
        app.invoke({"messages": [HumanMessage("hi")]}, {"configurable": dict(store.THREAD)})
    assert store.exists(uid, nid)
    with store.saver(uid, nid) as cp:
        app = g.compile(checkpointer=cp)
        msgs = app.get_state({"configurable": dict(store.THREAD)}).values["messages"]
        assert [m.content for m in msgs] == ["hi"]
    store.clear(uid, nid)
    assert not store.exists(uid, nid)
    store.clear(uid, nid)        # 没有存档也不报错
    print("2. 存档读写与清空 ✓")

    # 3. 每日计数：只数 purpose=assistant、本人、UTC 当天
    now = datetime.now(timezone.utc)
    yesterday = (now - timedelta(days=1)).isoformat(timespec="seconds")
    z = {"calls": 0}
    usage.record(user_id=uid, purpose="assistant", model="m", usage=z, ok=True, novel_id=nid)
    usage.record(user_id=uid, purpose="assistant", model="m", usage=z, ok=False, novel_id=nid)
    usage.record(user_id=uid, purpose="assistant", model="m", usage=z, ok=True, at=yesterday)
    usage.record(user_id=uid, purpose="digest", model="m", usage=z, ok=True)
    usage.record(user_id=other, purpose="assistant", model="m", usage=z, ok=True)
    assert store.used_today(uid) == 2, store.used_today(uid)
    os.environ["STORYBOARD_ASSISTANT_DAILY"] = "7"
    assert store.daily_limit() == 7
    os.environ["STORYBOARD_ASSISTANT_DAILY"] = "abc"
    assert store.daily_limit() == 200
    del os.environ["STORYBOARD_ASSISTANT_DAILY"]
    assert store.daily_limit() == 200
    print("3. 每日计数与上限 ✓")

    # 4. 并发锁：同一部小说第二次 begin 失败，end 之后可再 begin
    assert store.try_begin(uid, nid)
    assert not store.try_begin(uid, nid)
    assert store.try_begin(uid, "another")
    store.end(uid, nid)
    store.end(uid, "another")
    assert store.try_begin(uid, nid)
    store.end(uid, nid)
    print("4. 并发锁 ✓")

    # 5. 租约：新锁不能抢，过期的锁可接管，end 幂等
    assert store.try_begin(uid, nid)
    store._busy[(uid, nid)] -= store.LEASE_SEC - 5
    assert not store.try_begin(uid, nid)
    store._busy[(uid, nid)] -= 10
    assert store.try_begin(uid, nid)
    assert not store.try_begin(uid, nid)
    store.end(uid, nid)
    store.end(uid, nid)
    assert store.try_begin(uid, nid)
    store.end(uid, nid)
    print("5. 租约 ✓")

    # 6. 凭据：迟到的 end（旧凭据）不放掉后来那一轮的锁
    old = store.try_begin(uid, nid)
    store.end(uid, nid, old)
    new = store.try_begin(uid, nid)
    assert new and new != old
    store.end(uid, nid, old)
    assert not store.try_begin(uid, nid), "旧凭据放掉了新锁"
    store.end(uid, nid, new)
    assert store.try_begin(uid, nid)
    store.end(uid, nid)
    print("6. 凭据 ✓")

    # 撤销记录：没有时为空；记两次只算一次；清空对话一并删掉
    assert store.undone(uid, nid) == set()
    store.mark_undone(uid, nid, "t1")
    store.mark_undone(uid, nid, "t1")
    store.mark_undone(uid, nid, "t2")
    assert store.undone(uid, nid) == {"t1", "t2"}
    store.clear(uid, nid)
    assert store.undone(uid, nid) == set()
    print("撤销记录 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
