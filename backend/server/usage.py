"""用量流水账：每次模型调用落一行，追加写，删版本不影响历史。

一行一条 JSON；读取时跳过解析失败的行（进程崩溃时可能写了半行）。
"""
import json
import math
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

from server import pricing
from server.auth import DATA_DIR
from server.store import now_iso

USAGE_FILE = DATA_DIR / "usage.jsonl"
TOKENS = ("calls", "input", "output", "cache_read", "cache_write")
_lock = threading.Lock()


def ensure_line_start(path, f) -> None:
    """上次崩溃可能留下没换行的残行；先补一个换行，新记录才不会被粘进去。"""
    if path.exists() and path.stat().st_size:
        with open(path, "rb") as r:
            r.seek(-1, 2)
            if r.read(1) != b"\n":
                f.write("\n")


def record(*, user_id: str, purpose: str, model: str, usage: dict, ok: bool,
           chars: int = 0, novel_id: Optional[str] = None,
           chapter_id: Optional[str] = None, version_id: Optional[str] = None,
           at: Optional[str] = None, mixed_models: Optional[list] = None) -> dict:
    row = {"at": at or now_iso(), "user_id": user_id, "novel_id": novel_id,
           "chapter_id": chapter_id, "version_id": version_id, "purpose": purpose,
           "model": model, "ok": bool(ok),
           **{k: int(usage.get(k) or 0) for k in TOKENS}, "chars": int(chars or 0)}
    if mixed_models:
        row["mixed_models"] = list(mixed_models)
    line = json.dumps(row, ensure_ascii=False) + "\n"
    with _lock:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(USAGE_FILE, "a", encoding="utf-8") as f:
            ensure_line_start(USAGE_FILE, f)
            f.write(line)
            f.flush()
    return row


def _when(row: dict) -> datetime:
    return datetime.fromisoformat(row["at"])


def read(since: Optional[datetime] = None, user_id: Optional[str] = None) -> list:
    if not USAGE_FILE.exists():
        return []
    out = []
    with open(USAGE_FILE, encoding="utf-8") as f:
        for line in f:
            try:
                row = json.loads(line)
                when = _when(row)
                if since is not None and when < since:
                    continue
            except (ValueError, KeyError, TypeError):
                continue
            if user_id is not None and row.get("user_id") != user_id:
                continue
            out.append(row)
    return out


_GROUPS = {"user": lambda r: r.get("user_id") or "",
           "day": lambda r: r["at"][:10],
           "model": lambda r: r.get("model") or ""}


def aggregate(rows: list, group: str, table: dict) -> list:
    if group not in _GROUPS:
        raise ValueError(f"不支持的分组：{group}")
    key = _GROUPS[group]
    buckets: dict = {}
    for r in rows:
        b = buckets.setdefault(key(r), {"key": key(r), **{k: 0 for k in TOKENS},
                                        "chars": 0, "cost_usd": 0.0, "unpriced": 0,
                                        "records": 0})
        for k in TOKENS:
            b[k] += r.get(k) or 0
        b["chars"] += r.get("chars") or 0
        b["records"] += 1
        c = pricing.cost(r, table)
        if c is None:
            b["unpriced"] += 1
        else:
            b["cost_usd"] += c
    out = list(buckets.values())
    if group == "day":
        out.sort(key=lambda b: b["key"])
    else:
        out.sort(key=lambda b: b["cost_usd"], reverse=True)
    return out


def per_k_chars(rows: list, table: dict) -> dict:
    """每千字成本：只算成功的转换、有字数、已定价的记录。P90 用最近秩法。"""
    vals = []
    for r in rows:
        if r.get("purpose") != "convert" or not r.get("ok") or not r.get("chars"):
            continue
        c = pricing.cost(r, table)
        if c is not None:
            vals.append(c / r["chars"] * 1000)
    if not vals:
        return {"n": 0, "mean": None, "p90": None}
    vals.sort()
    return {"n": len(vals), "mean": sum(vals) / len(vals),
            "p90": vals[math.ceil(0.9 * len(vals)) - 1]}


def month_start(now: Optional[datetime] = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def month_spent(user_id: str, table: dict, now: Optional[datetime] = None) -> float:
    total = 0.0
    for r in read(since=month_start(now), user_id=user_id):
        c = pricing.cost(r, table)
        total += c or 0.0
    return total


def daily_series(rows: list, days: int, table: dict, now: Optional[datetime] = None) -> list:
    """最近 days 天（含今天）每天的金额，没有记录的天补 0。"""
    now = now or datetime.now(timezone.utc)
    keys = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days - 1, -1, -1)]
    sums = {k: 0.0 for k in keys}
    for r in rows:
        k = r["at"][:10]
        if k in sums:
            sums[k] += pricing.cost(r, table) or 0.0
    return [{"day": k, "cost_usd": sums[k]} for k in keys]


def unpriced_models(rows: list, table: dict) -> list:
    return sorted({r.get("model") or "" for r in rows if pricing.cost(r, table) is None})
