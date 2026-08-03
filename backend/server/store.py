"""转换历史的落盘存储。

转换是分钟级、要花 API 费用的任务，产物不能只活在内存里（进程重启即清空）。
每条完成的转换写成 runs/<id>.json 一个文件：无需数据库、可直接备份/传阅/手工检视。
另提供跨转换的资产库聚合——续写同一部小说的下一章时沿用已有 C/S/P/A 卡，防跨章角色漂移。
"""
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pipeline.config import ROOT

RUNS_DIR = Path(os.environ.get("STORYBOARD_RUNS_DIR", ROOT / "runs"))

# id 来自 URL 路径，必须限死字符集，避免 ../ 之类的路径穿越
_ID_RE = re.compile(r"^[0-9a-zA-Z_-]{1,64}$")


def _path(run_id: str) -> Path:
    if not _ID_RE.match(run_id):
        raise ValueError(f"非法的记录 ID：{run_id!r}")
    return RUNS_DIR / f"{run_id}.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def save(run_id: str, status: str, params: dict, result: dict,
         quality_report: Optional[str] = None) -> dict:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
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
    tmp = _path(run_id).with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    tmp.replace(_path(run_id))
    return record


def get(run_id: str) -> Optional[dict]:
    path = _path(run_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def update_result(run_id: str, result: dict) -> Optional[dict]:
    """保存人工编辑后的分镜（呈现层可改，溯源锁死由前端保证）。"""
    record = get(run_id)
    if record is None:
        return None
    record["result"] = result
    record["edited_at"] = now_iso()
    tmp = _path(run_id).with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    tmp.replace(_path(run_id))
    return record


def delete(run_id: str) -> bool:
    path = _path(run_id)
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


def list_runs() -> list:
    if not RUNS_DIR.exists():
        return []
    out = []
    for path in RUNS_DIR.glob("*.json"):
        try:
            out.append(_summarize(json.loads(path.read_text(encoding="utf-8"))))
        except (json.JSONDecodeError, OSError):
            continue   # 损坏或正在写入的文件不该拖垮整个列表
    out.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return out


_KINDS = ("characters", "locations", "props", "creatures")


def asset_library() -> list:
    """按作品聚合历史资产卡，供新转换沿用。

    同一作品的同 ID 卡以最新一次转换为准；不跨作品合并——不同小说的 C01 各是各的。
    """
    by_work: dict = {}
    for path in RUNS_DIR.glob("*.json") if RUNS_DIR.exists() else []:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        doc = record.get("result") or {}
        title = (doc.get("meta") or {}).get("title") \
            or (record.get("params") or {}).get("work_title")
        if not title:
            continue
        entry = by_work.setdefault(title, {
            "work_title": title, "updated_at": "", "runs": 0,
            "assets": {k: {} for k in _KINDS},
        })
        entry["runs"] += 1
        created = record.get("created_at") or ""
        newer = created >= entry["updated_at"]
        if newer:
            entry["updated_at"] = created
        for kind in _KINDS:
            for card in (doc.get("assets") or {}).get(kind) or []:
                cid = card.get("id")
                if not cid:
                    continue
                # 新记录覆盖旧记录的同 ID 卡；旧记录只补充缺失的卡
                if newer or cid not in entry["assets"][kind]:
                    entry["assets"][kind][cid] = card

    out = []
    for entry in by_work.values():
        assets = {k: sorted(v.values(), key=lambda c: c.get("id", ""))
                  for k, v in entry["assets"].items()}
        out.append({
            "work_title": entry["work_title"],
            "updated_at": entry["updated_at"],
            "runs": entry["runs"],
            "counts": {k: len(v) for k, v in assets.items()},
            "assets": {k: v for k, v in assets.items() if v},
        })
    out.sort(key=lambda e: e["updated_at"], reverse=True)
    return out
