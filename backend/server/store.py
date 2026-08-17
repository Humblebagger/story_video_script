"""转换历史的落盘存储（按用户隔离）。

转换是分钟级、要花 API 费用的任务，产物不能只活在内存里（进程重启即清空）。
每条完成的转换写成 data/users/<user_id>/runs/<id>.json 一个文件：
无需数据库、可直接备份/传阅/手工检视，且用户之间天然互不可见。

资产卡的统一管理见 library.py——那是独立于任何一次转换的一等实体。
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from server.auth import user_dir

# id 来自 URL 路径，必须限死字符集，避免 ../ 之类的路径穿越
_ID_RE = re.compile(r"^[0-9a-zA-Z_-]{1,64}$")


def runs_dir(user_id: str) -> Path:
    return user_dir(user_id) / "runs"


def _path(user_id: str, run_id: str) -> Path:
    if not _ID_RE.match(run_id):
        raise ValueError(f"非法的记录 ID：{run_id!r}")
    return runs_dir(user_id) / f"{run_id}.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write(user_id: str, run_id: str, record: dict) -> None:
    runs_dir(user_id).mkdir(parents=True, exist_ok=True)
    tmp = _path(user_id, run_id).with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    tmp.replace(_path(user_id, run_id))


def save(user_id: str, run_id: str, status: str, params: dict,
         result: Optional[dict], quality_report: Optional[str] = None,
         manifest: Optional[dict] = None, verification: Optional[dict] = None,
         error: Optional[str] = None) -> dict:
    runs_dir(user_id).mkdir(parents=True, exist_ok=True)
    record = {
        "id": run_id,
        "created_at": now_iso(),
        "edited_at": None,
        "status": status,
        "params": params,
        "quality_report": quality_report,
        "verification": verification,
        "manifest": manifest,
        "error": error,
        "result": result,
    }
    _write(user_id, run_id, record)
    return record


def get(user_id: str, run_id: str) -> Optional[dict]:
    path = _path(user_id, run_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def update_result(user_id: str, run_id: str, result: dict, *,
                  verification: Optional[dict] = None,
                  status: Optional[str] = None,
                  frozen_units: Optional[list] = None) -> Optional[dict]:
    """保存人工编辑后的分镜及服务端复验结果。"""
    record = get(user_id, run_id)
    if record is None:
        return None
    record["result"] = result
    record["edited_at"] = now_iso()
    if verification is not None:
        record["verification"] = verification
    if status is not None:
        record["status"] = status
    if frozen_units and not ((record.get("manifest") or {}).get("scope") or {}).get("units"):
        record["manifest"] = {
            "version": 1,
            "state": "legacy_scope_frozen_on_edit",
            "scope": {"frozen": True, "units": frozen_units},
        }
    _write(user_id, run_id, record)
    return record


def update_state(user_id: str, run_id: str, status: str, **fields) -> Optional[dict]:
    """Atomically update a persisted run without changing its creation identity."""
    record = get(user_id, run_id)
    if record is None:
        return None
    record["status"] = status
    for key in ("result", "quality_report", "manifest", "verification", "error"):
        if key in fields:
            record[key] = fields[key]
    _write(user_id, run_id, record)
    return record


def delete(user_id: str, run_id: str) -> bool:
    path = _path(user_id, run_id)
    if not path.exists():
        return False
    path.unlink()
    return True


def _summarize(record: dict) -> dict:
    doc = record.get("result") or {}
    episodes = doc.get("episodes") or []
    return {
        "id": record.get("id"),
        "created_at": record.get("created_at"),
        "edited_at": record.get("edited_at"),
        "status": record.get("status"),
        "work_title": (doc.get("meta") or {}).get("title")
                      or (record.get("params") or {}).get("work_title"),
        "chapter": (doc.get("source") or {}).get("chapter")
                   or (record.get("params") or {}).get("chapter"),
        "units": len((doc.get("source") or {}).get("units") or []),
        "episodes": len(episodes),
        "shots": sum(len(e.get("shots") or []) for e in episodes),
        "has_quality_report": bool(record.get("quality_report")),
        "verification_status": (record.get("verification") or {}).get("status"),
    }


def list_runs(user_id: str) -> list:
    d = runs_dir(user_id)
    if not d.exists():
        return []
    out = []
    for path in d.glob("*.json"):
        try:
            out.append(_summarize(json.loads(path.read_text(encoding="utf-8"))))
        except (json.JSONDecodeError, OSError):
            continue   # 损坏或正在写入的文件不该拖垮整个列表
    out.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return out
