"""助手对话存档与限流。

- 存档：LangGraph 的 SqliteSaver，每部小说一个文件（novels.assistant_db），thread_id 固定为 main。
- 每日上限：当天（UTC）purpose=assistant 的用量记录条数，每轮对话记一条（见 server/app.py）。
- 并发：同一部小说同时只跑一轮（进程内）。
"""
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, Optional

from langgraph.checkpoint.sqlite import SqliteSaver

from server import novels, usage

THREAD = {"thread_id": "main"}
PURPOSE = "assistant"
DEFAULT_DAILY = 200


def daily_limit() -> int:
    try:
        return max(0, int(os.environ.get("STORYBOARD_ASSISTANT_DAILY", DEFAULT_DAILY)))
    except ValueError:
        return DEFAULT_DAILY


def exists(user_id: str, nid: str) -> bool:
    return novels.assistant_db(user_id, nid).exists()


@contextmanager
def saver(user_id: str, nid: str) -> Iterator[SqliteSaver]:
    """打开这部小说的存档；用完即关（每个请求一个连接）。"""
    conn = sqlite3.connect(str(novels.assistant_db(user_id, nid)), check_same_thread=False)
    try:
        yield SqliteSaver(conn)
    finally:
        conn.close()


def clear(user_id: str, nid: str) -> None:
    """清空对话：删存档文件（含 SQLite 的附属文件）。没有也不报错。"""
    path = novels.assistant_db(user_id, nid)
    for suffix in ("", "-wal", "-shm", "-journal"):
        path.with_name(path.name + suffix).unlink(missing_ok=True)


def used_today(user_id: str, now: Optional[datetime] = None) -> int:
    now = now or datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return sum(1 for r in usage.read(since=start, user_id=user_id) if r.get("purpose") == PURPOSE)


_busy: set = set()
_busy_lock = threading.Lock()


def try_begin(user_id: str, nid: str) -> bool:
    with _busy_lock:
        if (user_id, nid) in _busy:
            return False
        _busy.add((user_id, nid))
        return True


def end(user_id: str, nid: str) -> None:
    with _busy_lock:
        _busy.discard((user_id, nid))
