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


def save(user_id: str, run_id: str, status: str, params: dict, result: dict,
         quality_report: Optional[str] = None) -> dict:
    runs_dir(user_id).mkdir(parents=True, exist_ok=True)
    record = {
        "id": run_id,
        "created_at": now_iso(),
        "edited_at": None,
        "status": status,
        "params": params,
        "quality_report": quality_report,
        "result": result,
    }
    # 先写临时文件再原子替换：避免读到写了一半的 JSON
    tmp = _path(user_id, run_id).with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    tmp.replace(_path(user_id, run_id))
    return record


def get(user_id: str, run_id: str) -> Optional[dict]:
    path = _path(user_id, run_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def update_result(user_id: str, run_id: str, result: dict) -> Optional[dict]:
    """保存人工编辑后的分镜（呈现层可改，溯源锁死由前端保证）。"""
    record = get(user_id, run_id)
    if record is None:
        return None
    record["result"] = result
    record["edited_at"] = now_iso()
    tmp = _path(user_id, run_id).with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    tmp.replace(_path(user_id, run_id))
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
