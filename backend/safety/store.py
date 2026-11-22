"""结论缓存与拦截记录（spec §2.4）。

verdicts.json：文本 hash → 结论（pass / block）。全站共享：只按文本 hash，不分用户。
blocks.json：拦截记录（管理员在后台看、放行）。
两份都是整份 JSON、原子写；一把模块级锁管读改写；内存里留一份，进程内只读盘一次。
"""
import json
import logging
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional

from safety import blocklist
from safety.categories import POLICY_VERSION
from safety.text import excerpt, text_hash
from server import error_refs
from server.auth import DATA_DIR
from server.messages import UserError
from server.store import now_iso

DIR = DATA_DIR / "safety"
VERDICTS_FILE = DIR / "verdicts.json"
BLOCKS_FILE = DIR / "blocks.json"
MAX_VERDICTS = 20000
KEEP_DAYS = 90
CLEANUP_EVERY_SEC = 24 * 3600
REFUSED = "safety.reason.model_refused"       # 底层模型服务拒绝：只记不缓存，放行无效

log = logging.getLogger("safety.store")
_lock = threading.RLock()
_verdicts: Optional[dict] = None
_blocks: Optional[list] = None
_last_cleanup = 0.0


class StoreError(UserError, ValueError):
    """后台操作不成立（409）。"""


class NotFound(UserError, LookupError):
    """没有这条拦截记录（404）。"""


def policy() -> str:
    """当前策略版本：系统提示版本 + 词表文件 hash。"""
    return f"{POLICY_VERSION}:{blocklist.file_hash()}"


def _read(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def _load() -> None:
    """两份文件一起读进内存，并对账：记录已放行而结论缓存里不是放行通过的，补成放行通过。"""
    global _verdicts, _blocks
    if _verdicts is not None and _blocks is not None:
        return
    v = _read(VERDICTS_FILE, {})
    b = _read(BLOCKS_FILE, [])
    _verdicts = v if isinstance(v, dict) else {}
    _blocks = b if isinstance(b, list) else []
    fixed = False
    for r in _blocks:
        if r.get("status") != "released" or r.get("reason_code") == REFUSED:
            continue
        cur = _verdicts.get(r["hash"])
        if not (cur and cur.get("verdict") == "pass" and cur.get("released")):
            _verdicts[r["hash"]] = {"verdict": "pass", "released": True, "policy": policy(),
                                    "at": r.get("released_at") or now_iso()}
            fixed = True
    if fixed:
        try:
            _write(VERDICTS_FILE, _verdicts)
        except OSError as e:     # 内存里已是对的；盘上下次写结论时一并带上
            log.warning("结论缓存对账补写失败：%r", e)  # i18n: internal


def _verdicts_data() -> dict:
    _load()
    return _verdicts


def _blocks_data() -> list:
    _load()
    return _blocks


@contextmanager
def _txn():
    """持锁的一次修改：任何一步失败（含写盘）就丢掉内存状态、下次从盘上重读，不留半截。"""
    global _verdicts, _blocks
    with _lock:
        try:
            yield
        except BaseException:
            _verdicts, _blocks = None, None
            raise


def _save_verdicts() -> None:
    _write(VERDICTS_FILE, _verdicts_data())


def _save_blocks() -> None:
    _write(BLOCKS_FILE, _blocks_data())


def _reset_for_test() -> None:
    """丢掉内存里的那份，下次从盘上重新读（测试用）。"""
    global _verdicts, _blocks
    with _lock:
        _verdicts, _blocks = None, None


def _evict(data: dict) -> None:
    plain = sorted((k for k, v in data.items() if not v.get("released")), key=lambda k: data[k].get("at") or "")
    for k in plain[:max(0, len(plain) - MAX_VERDICTS)]:
        del data[k]


def get_verdict(h: str) -> Optional[dict]:
    """这个 hash 的有效结论；策略版本对不上的当作没有（放行过的永不失效）。"""
    with _lock:
        v = _verdicts_data().get(h)
        if v is None or not (v.get("released") or v.get("policy") == policy()):
            return None
        return dict(v)


def set_pass(h: str) -> None:
    with _txn():
        data = _verdicts_data()
        if (data.get(h) or {}).get("released"):
            return
        data[h] = {"verdict": "pass", "policy": policy(), "at": now_iso()}
        _evict(data)
        _save_verdicts()


def _view(row: dict) -> dict:
    return {**row, "releasable": row.get("reason_code") != REFUSED}


def record_block(text, *, category: str, ctx: dict, reason: str = "", reason_code: Optional[str] = None,
                 cache: bool = True) -> str:
    """记一次拦截，返回编号。同一文本（且同为未放行）再次被拦：返回原编号，次数加一。
    cache=False：只写记录，不写结论缓存（模型拒答用，见 REFUSED）。
    该文本已被管理员放行（迟到的分类结果）：不覆盖、不记录，返回 None，调用方按通过处理。"""
    h = text_hash(text)
    with _txn():
        if (_verdicts_data().get(h) or {}).get("released"):
            return None
        rows = _blocks_data()
        row = next((r for r in rows if r["hash"] == h and r["status"] == "blocked"
                    and (r.get("reason_code") == REFUSED) == (reason_code == REFUSED)), None)
        now = now_iso()
        if row is not None:
            row["hits"] = int(row.get("hits") or 1) + 1
            row["last_at"] = now
        else:
            row = {"id": error_refs.new_ref(), "at": now, "last_at": now, "hits": 1,
                   "user_id": ctx.get("user_id"), "novel_id": ctx.get("novel_id"),
                   "chapter_id": ctx.get("chapter_id"), "version_id": ctx.get("version_id"),
                   "clip_id": ctx.get("clip_id"), "stage": ctx.get("stage"), "category": category,
                   "reason": str(reason or "")[:80], "reason_code": reason_code,
                   "excerpt": excerpt(text), "hash": h, "status": "blocked",
                   "released_by": None, "released_at": None}
            rows.append(row)
        _save_blocks()
        if cache:
            data = _verdicts_data()
            data[h] = {"verdict": "block", "block_id": row["id"], "category": category,
                       "policy": policy(), "at": now}
            _evict(data)
            _save_verdicts()
        bid = row["id"]
    _cleanup_quietly()
    return bid


def touch_block(block_id: str) -> None:
    """命中已缓存的拦截结论：次数加一、更新最近时间。"""
    with _txn():
        row = next((r for r in _blocks_data() if r["id"] == block_id), None)
        if row is not None:
            row["hits"] = int(row.get("hits") or 1) + 1
            row["last_at"] = now_iso()
            _save_blocks()
    _cleanup_quietly()


def find_block(block_id) -> Optional[dict]:
    want = error_refs.normalize(block_id)
    with _lock:
        row = next((r for r in _blocks_data() if r["id"] == want), None)
        return _view(row) if row else None


def list_blocks(status: Optional[str] = None, days: Optional[int] = None, ref: Optional[str] = None) -> list:
    """拦截记录，最近一次被拦的在前。"""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds") if days else None
    want = error_refs.normalize(ref) if ref else None
    with _lock:
        rows = [_view(r) for r in _blocks_data()
                if (status is None or r["status"] == status)
                and (since is None or (r.get("last_at") or r["at"]) >= since)
                and (want is None or r["id"] == want)]
    rows.sort(key=lambda r: r.get("last_at") or r["at"], reverse=True)
    return rows


def count_blocked() -> int:
    with _lock:
        return sum(1 for r in _blocks_data() if r["status"] == "blocked")


def release(block_id, admin_name: str) -> dict:
    """放行：记录改 released，结论缓存里这个 hash 改为通过且永不失效。重复放行原样返回。"""
    want = error_refs.normalize(block_id)
    with _txn():
        row = next((r for r in _blocks_data() if r["id"] == want), None)
        if row is None:
            raise NotFound.of("admin.safety.not_found", ref=want)
        if row.get("reason_code") == REFUSED:
            raise StoreError.of("admin.safety.not_releasable")
        data = _verdicts_data()
        cur = data.get(row["hash"]) or {}
        now = row.get("released_at") if row["status"] == "released" else None
        now = now or now_iso()
        # 先写结论缓存（放行通过），再写记录：中途失败时放行已生效，重试能补完记录
        if not (cur.get("verdict") == "pass" and cur.get("released")):
            data[row["hash"]] = {"verdict": "pass", "released": True, "policy": policy(), "at": now}
            _save_verdicts()
        if row["status"] != "released":
            row.update(status="released", released_by=admin_name, released_at=now)
            _save_blocks()
        return _view(row)


def cleanup(now: Optional[datetime] = None) -> int:
    """早于 90 天的记录清空摘录与理由（记录本身留着供统计）。返回清了几条。"""
    global _last_cleanup
    cutoff = ((now or datetime.now(timezone.utc)) - timedelta(days=KEEP_DAYS)).isoformat(timespec="seconds")
    n = 0
    with _txn():
        for r in _blocks_data():
            if r["at"] < cutoff and (r.get("excerpt") or r.get("reason")):
                r["excerpt"], r["reason"] = "", ""
                n += 1
        if n:
            _save_blocks()
        _last_cleanup = time.monotonic()
    return n


def maybe_cleanup() -> None:
    """距上次清理超过一天就再清一次（仓库没有定时器，挂在写记录的路上）。"""
    if time.monotonic() - _last_cleanup >= CLEANUP_EVERY_SEC:
        cleanup()


def _cleanup_quietly() -> None:
    """写拦截记录之后顺带做到期清理；清理本身失败不影响已经成功的写入。"""
    try:
        maybe_cleanup()
    except OSError as e:
        log.warning("拦截记录清理失败：%r", e)  # i18n: internal


def purge(user_id: str, novel_id: Optional[str] = None, chapter_id: Optional[str] = None) -> int:
    """用户删了作品或章节：对应记录的摘录与理由清空。返回清了几条。"""
    n = 0
    with _txn():
        for r in _blocks_data():
            if r.get("user_id") != user_id or (novel_id and r.get("novel_id") != novel_id) \
                    or (chapter_id and r.get("chapter_id") != chapter_id):
                continue
            if r.get("excerpt") or r.get("reason"):
                r["excerpt"], r["reason"] = "", ""
                n += 1
        if n:
            _save_blocks()
    return n
