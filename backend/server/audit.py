"""管理操作审计：追加写，最新在前读出。重置密码只记动作，不记密码。"""
import json
import threading
from typing import Optional

from server.auth import DATA_DIR
from server.store import now_iso

AUDIT_FILE = DATA_DIR / "admin_audit.jsonl"
_lock = threading.Lock()


def write(admin: dict, action: str, target: Optional[dict] = None,
          before: Optional[dict] = None, after: Optional[dict] = None) -> dict:
    row = {"at": now_iso(), "admin_id": admin["id"], "admin": admin["username"],
           "action": action,
           "target_id": (target or {}).get("id"), "target": (target or {}).get("username"),
           "before": before, "after": after}
    with _lock:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(AUDIT_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def read(limit: int = 200) -> list:
    if not AUDIT_FILE.exists():
        return []
    rows = []
    with open(AUDIT_FILE, encoding="utf-8") as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return list(reversed(rows))[:limit]
