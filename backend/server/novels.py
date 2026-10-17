"""小说级会话：小说（总会话，长期记忆）→ 章节（二级会话）→ 版本（每次转换，短期记忆）。

对应 Agent 的会话模型：小说是「用户实体」，承载跨章不变的长期记忆（资产库、制作参数、
编号接续、人物生命周期、主线剧情、创作限制）；章节是「一次提问」，
它的每次转换是一个版本，版本记录就是此前 store.py 的 run 记录（日志/尝试/清单/产物）。

只有章节的**采用版**进入长期记忆。存储沿用「一个 JSON 一个文件、按用户隔离」：

    data/users/<uid>/novels/<nid>/novel.json
    data/users/<uid>/novels/<nid>/chapters/<cid>/chapter.json
    data/users/<uid>/novels/<nid>/chapters/<cid>/versions/<vid>.json

设计见 docs/specs/2026-10-12-novel-sessions-and-timeline-canvas-design.md。
"""
import json
import re
import secrets
import shutil
import threading
from pathlib import Path
from typing import Optional

from server.auth import user_dir
from server.library import KINDS, _merge_card
from pipeline.novel_memory import LIFECYCLE_TYPES, SYNOPSIS_MAX, NovelContext
from server.store import now_iso

# id 来自 URL 路径，必须限死字符集，避免 ../ 之类的路径穿越
_ID_RE = re.compile(r"^[0-9a-zA-Z_-]{1,64}$")
# 可被采用、进入长期记忆的版本状态。draft_invalid（人工改坏了）与失败的不行
ADOPTABLE = ("succeeded", "completed_with_warnings")
_MIGRATED = ".migrated"

_lock = threading.RLock()


class NovelError(ValueError):
    """业务规则不满足（名称重复、原文已锁定、不能采用……）。"""


class NotFound(LookupError):
    pass


# ---------- 路径与读写 ----------

def novels_dir(user_id: str) -> Path:
    return user_dir(user_id) / "novels"


def _check_id(value: str) -> str:
    if not _ID_RE.match(value or ""):
        raise NovelError(f"非法的 ID：{value!r}")
    return value


def _novel_dir(user_id: str, nid: str) -> Path:
    return novels_dir(user_id) / _check_id(nid)


def _chapter_dir(user_id: str, nid: str, cid: str) -> Path:
    return _novel_dir(user_id, nid) / "chapters" / _check_id(cid)


def _version_path(user_id: str, nid: str, cid: str, vid: str) -> Path:
    return _chapter_dir(user_id, nid, cid) / "versions" / f"{_check_id(vid)}.json"


def _read(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    tmp.replace(path)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(5)}"


def _empty_memory() -> dict:
    return {
        "assets": {k: [] for k in KINDS},
        # 资产卡来自哪一章的哪个版本、是否被人改过——换采用版时据此撤回。
        # 来源记在卡片之外：卡片要原样注入【已有资产库】，schema 不允许多余字段
        "asset_origin": {k: {} for k in KINDS},
        "numbering": {"next_unit": 1, "next_para": 1, "next_episode": 1},
        "lifecycle": [],
        "plot": {"outline": "", "chapters": []},
        "constraints": [],
    }


# ---------- 小说 ----------

def _load_novel(user_id: str, nid: str) -> dict:
    novel = _read(_novel_dir(user_id, nid) / "novel.json")
    if novel is None:
        raise NotFound("小说不存在")
    memory = novel.setdefault("memory", _empty_memory())
    for key, value in _empty_memory().items():
        memory.setdefault(key, value)     # 第 1、2 阶段建的小说没有后加的几项
    return novel


def _save_novel(user_id: str, novel: dict) -> None:
    novel["updated_at"] = now_iso()
    _write(_novel_dir(user_id, novel["id"]) / "novel.json", novel)


def _all_novels(user_id: str) -> list:
    root = novels_dir(user_id)
    if not root.exists():
        return []
    out = []
    for d in root.iterdir():
        n = _read(d / "novel.json") if d.is_dir() else None
        if n:
            out.append(n)
    return out


def create_novel(user_id: str, title: str, params: Optional[dict] = None) -> dict:
    """新建总会话。标题在同一用户下唯一——它是这部小说在界面上的名字，
    重名的两部小说没法区分。"""
    title = (title or "").strip()
    if not title:
        raise NovelError("小说标题不能为空")
    with _lock:
        if any(n["title"] == title for n in _all_novels(user_id)):
            raise NovelError(f"《{title}》已存在")
        now = now_iso()
        novel = {"id": _new_id("n"), "title": title, "created_at": now,
                 "updated_at": now, "params": dict(params or {}),
                 "memory": _empty_memory()}
        _write(_novel_dir(user_id, novel["id"]) / "novel.json", novel)
    return novel


def _chapters(user_id: str, nid: str) -> list:
    root = _novel_dir(user_id, nid) / "chapters"
    if not root.exists():
        return []
    out = [c for c in (_read(d / "chapter.json") for d in root.iterdir() if d.is_dir())
           if c]
    out.sort(key=lambda c: (c.get("order", 0), c.get("created_at") or ""))
    return out


def _chapter_summary(user_id: str, nid: str, chapter: dict) -> dict:
    versions = _version_summaries(user_id, nid, chapter["id"])
    return {
        "id": chapter["id"], "title": chapter["title"], "order": chapter["order"],
        "adopted_version": chapter.get("adopted_version"),
        "legacy_numbering": chapter.get("legacy_numbering", False),
        "chars": len(chapter.get("text") or ""),
        "versions": versions,
        "latest_status": versions[0]["status"] if versions else None,
        "digest": chapter.get("digest"),
    }


def list_novels(user_id: str) -> list:
    out = []
    for n in _all_novels(user_id):
        chapters = _chapters(user_id, n["id"])
        assets = (n.get("memory") or {}).get("assets") or {}
        out.append({
            "id": n["id"], "title": n["title"], "updated_at": n.get("updated_at"),
            "chapters": len(chapters),
            "adopted": sum(1 for c in chapters if c.get("adopted_version")),
            "asset_counts": {k: len(assets.get(k) or []) for k in KINDS},
        })
    out.sort(key=lambda x: x.get("updated_at") or "", reverse=True)
    return out


def get_novel(user_id: str, nid: str) -> dict:
    novel = _load_novel(user_id, nid)
    memory = {k: v for k, v in novel["memory"].items() if k != "asset_origin"}
    return {**novel, "memory": memory,
            "chapters": [_chapter_summary(user_id, nid, c) for c in _chapters(user_id, nid)]}


def update_novel(user_id: str, nid: str, *, title: Optional[str] = None,
                 params: Optional[dict] = None) -> dict:
    with _lock:
        novel = _load_novel(user_id, nid)
        if title is not None:
            title = title.strip()
            if not title:
                raise NovelError("小说标题不能为空")
            if any(n["title"] == title and n["id"] != nid
                   for n in _all_novels(user_id)):
                raise NovelError(f"《{title}》已存在")
            novel["title"] = title
        if params is not None:
            novel["params"] = dict(params)
        _save_novel(user_id, novel)
    return novel


def delete_novel(user_id: str, nid: str) -> None:
    with _lock:
        d = _novel_dir(user_id, nid)
        if not (d / "novel.json").exists():
            raise NotFound("小说不存在")
        shutil.rmtree(d)


# ---------- 章节 ----------

def _load_chapter(user_id: str, nid: str, cid: str) -> dict:
    chapter = _read(_chapter_dir(user_id, nid, cid) / "chapter.json")
    if chapter is None:
        raise NotFound("章节不存在")
    return chapter


def _save_chapter(user_id: str, nid: str, chapter: dict) -> None:
    chapter["updated_at"] = now_iso()
    _write(_chapter_dir(user_id, nid, chapter["id"]) / "chapter.json", chapter)


def create_chapter(user_id: str, nid: str, title: str, text: str = "",
                   order: Optional[int] = None) -> dict:
    title = (title or "").strip()
    if not title:
        raise NovelError("章节标题不能为空")
    with _lock:
        _load_novel(user_id, nid)
        existing = _chapters(user_id, nid)
        if order is None:
            order = max((c["order"] for c in existing), default=0) + 1
        now = now_iso()
        chapter = {"id": _new_id("c"), "novel_id": nid, "title": title,
                   "order": int(order), "text": text or "", "created_at": now,
                   "updated_at": now, "adopted_version": None}
        _save_chapter(user_id, nid, chapter)
    return chapter


def get_chapter(user_id: str, nid: str, cid: str) -> dict:
    chapter = _load_chapter(user_id, nid, cid)
    return {**chapter, "versions": _version_summaries(user_id, nid, cid)}


def update_chapter(user_id: str, nid: str, cid: str, *, title: Optional[str] = None,
                   text: Optional[str] = None, order: Optional[int] = None) -> dict:
    with _lock:
        chapter = _load_chapter(user_id, nid, cid)
        if text is not None and text != chapter.get("text"):
            # 采用版的句单元就是从这份原文切出来的，原文一改，长期记忆里的编号与
            # 证据全都对不上了
            if chapter.get("adopted_version"):
                raise NovelError("本章已有采用版，原文已锁定；要改原文请新建章节")
            chapter["text"] = text
        if title is not None:
            if not title.strip():
                raise NovelError("章节标题不能为空")
            chapter["title"] = title.strip()
        if order is not None:
            chapter["order"] = int(order)
        _save_chapter(user_id, nid, chapter)
    return chapter


def delete_chapter(user_id: str, nid: str, cid: str) -> None:
    with _lock:
        chapter = _load_chapter(user_id, nid, cid)
        novel = _load_novel(user_id, nid)
        if chapter.get("adopted_version"):
            _retract(novel, cid)
        _retract_digest(novel, cid, chapter_deleted=True)
        shutil.rmtree(_chapter_dir(user_id, nid, cid))
        _recompute_numbering(user_id, novel)
        _save_novel(user_id, novel)


# ---------- 版本 ----------

def _version_summaries(user_id: str, nid: str, cid: str) -> list:
    root = _chapter_dir(user_id, nid, cid) / "versions"
    if not root.exists():
        return []
    out = []
    for path in root.glob("*.json"):
        v = _read(path)
        if not v:
            continue
        doc = v.get("result") or {}
        episodes = doc.get("episodes") or []
        out.append({
            "id": v["id"], "created_at": v.get("created_at"),
            "edited_at": v.get("edited_at"), "status": v.get("status"),
            "units": len((doc.get("source") or {}).get("units") or []),
            "episodes": len(episodes),
            "shots": sum(len(e.get("shots") or []) for e in episodes),
            "has_quality_report": bool(v.get("quality_report")),
            "verification_status": (v.get("verification") or {}).get("status"),
        })
    out.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return out


def create_version(user_id: str, nid: str, cid: str, vid: str, params: dict,
                   input_text: str) -> dict:
    """新开一次转换。原文快照进版本：章节原文在采用前可以改，版本得记住自己转的是哪份。"""
    with _lock:
        _load_chapter(user_id, nid, cid)
        record = {
            "id": _check_id(vid), "novel_id": nid, "chapter_id": cid,
            "created_at": now_iso(), "edited_at": None, "status": "queued",
            "params": params, "input_text": input_text,
            "quality_report": None, "verification": None, "manifest": None,
            "error": None, "result": None,
        }
        _write(_version_path(user_id, nid, cid, vid), record)
    return record


def get_version(user_id: str, nid: str, cid: str, vid: str) -> dict:
    v = _read(_version_path(user_id, nid, cid, vid))
    if v is None:
        raise NotFound("版本不存在")
    return v


def find_version(user_id: str, vid: str) -> Optional[dict]:
    """只知道版本 id 时（渲染任务包按 run_id 取冻结证据）找到它。"""
    _check_id(vid)
    for path in novels_dir(user_id).glob(f"*/chapters/*/versions/{vid}.json"):
        v = _read(path)
        if v:
            return v
    return None


def update_version_state(user_id: str, nid: str, cid: str, vid: str, status: str,
                         **fields) -> dict:
    """转换线程写回进度与结果（与 store.update_state 同形）。"""
    with _lock:
        v = get_version(user_id, nid, cid, vid)
        v["status"] = status
        for key in ("result", "quality_report", "manifest", "verification", "error"):
            if key in fields:
                v[key] = fields[key]
        _write(_version_path(user_id, nid, cid, vid), v)
    return v


def update_version_result(user_id: str, nid: str, cid: str, vid: str, result: dict,
                          *, verification: dict, status: str,
                          frozen_units: Optional[list] = None) -> dict:
    """保存人工编辑后的产物及服务端复验结果。

    清单里没有冻结句单元的版本（迁移来的旧记录、测试替身），在第一次编辑时把
    编辑前的句单元固化进清单——否则下一次复验只能拿「上次保存的产物」当证据，
    改坏一次之后就再也验不回来（与 store.update_result 同一处理）。
    """
    with _lock:
        v = get_version(user_id, nid, cid, vid)
        if frozen_units and not ((v.get("manifest") or {}).get("scope") or {}).get("units"):
            v["manifest"] = {**(v.get("manifest") or {}), "version": 1,
                             "state": "legacy_scope_frozen_on_edit",
                             "scope": {"frozen": True, "units": frozen_units}}
        v["result"] = result
        v["edited_at"] = now_iso()
        v["verification"] = verification
        v["status"] = status
        _write(_version_path(user_id, nid, cid, vid), v)
        chapter = _load_chapter(user_id, nid, cid)
        if chapter.get("adopted_version") == vid:
            # 采用版被人改过：资产卡与编号以改后的产物为准重新写入长期记忆
            novel = _load_novel(user_id, nid)
            _retract(novel, cid)
            if status in ADOPTABLE:
                _absorb(novel, cid, vid, result)
            _recompute_numbering(user_id, novel)
            _save_novel(user_id, novel)
    return v


def delete_version(user_id: str, nid: str, cid: str, vid: str) -> None:
    with _lock:
        chapter = _load_chapter(user_id, nid, cid)
        if chapter.get("adopted_version") == vid:
            raise NovelError("这是本章的采用版，先采用别的版本再删")
        path = _version_path(user_id, nid, cid, vid)
        if not path.exists():
            raise NotFound("版本不存在")
        path.unlink()


# ---------- 采用：版本 → 长期记忆 ----------

def _absorb(novel: dict, cid: str, vid: str, doc: dict) -> dict:
    """把一个版本的资产卡并进长期记忆，并记下来源。返回 {新增, 合并}。"""
    memory = novel["memory"]
    origin = memory.setdefault("asset_origin", {k: {} for k in KINDS})
    added = merged = 0
    for kind in KINDS:
        incoming = ((doc or {}).get("assets") or {}).get(kind) or []
        lst = memory["assets"].setdefault(kind, [])
        by_id = {c.get("id"): i for i, c in enumerate(lst)}
        for card in incoming:
            card_id = card.get("id")
            if not card_id:
                continue
            if card_id in by_id:
                # 已有的卡（前面章节或人工建的）只做追加式合并，来源不改
                lst[by_id[card_id]] = _merge_card(lst[by_id[card_id]], card)
                merged += 1
            else:
                lst.append(card)
                origin.setdefault(kind, {})[card_id] = {
                    "chapter_id": cid, "version_id": vid, "edited": False}
                added += 1
        lst.sort(key=lambda c: c.get("id", ""))
    return {"added": added, "merged": merged}


def _retract(novel: dict, cid: str) -> int:
    """撤回某章采用版写入长期记忆的资产卡：只撤它**新建**且之后没被人改过的卡。

    合并进已有卡的追加内容（新服装、新别名）撤不干净——那张卡同时承载着别的章节
    与人工编辑，宁可留着多余的服装，也不能误删。
    """
    memory = novel["memory"]
    origin = memory.setdefault("asset_origin", {k: {} for k in KINDS})
    removed = 0
    for kind in KINDS:
        owned = {card_id for card_id, o in (origin.get(kind) or {}).items()
                 if o.get("chapter_id") == cid and not o.get("edited")}
        if not owned:
            continue
        before = memory["assets"].get(kind) or []
        memory["assets"][kind] = [c for c in before if c.get("id") not in owned]
        removed += len(before) - len(memory["assets"][kind])
        for card_id in owned:
            origin[kind].pop(card_id, None)
    return removed


def _max_ids(doc: dict) -> tuple:
    units = (doc.get("source") or {}).get("units") or []
    unit = max((int(u["id"][1:]) for u in units
                if re.fullmatch(r"u\d+", u.get("id") or "")), default=0)
    para = max((int(u.get("para") or 0) for u in units), default=0)
    ep = max((int(e["id"][1:]) for e in doc.get("episodes") or []
              if re.fullmatch(r"E\d+", e.get("id") or "")), default=0)
    return unit, para, ep


def _recompute_numbering(user_id: str, novel: dict) -> None:
    """编号接续从所有采用版重新算（取最大编号 +1），不做增量——增量在换采用版、
    删章节时都要倒推，重算永远对。"""
    unit = para = ep = 0
    for chapter in _chapters(user_id, novel["id"]):
        vid = chapter.get("adopted_version")
        if not vid:
            continue
        v = _read(_version_path(user_id, novel["id"], chapter["id"], vid))
        if not v or not v.get("result"):
            continue
        u, p, e = _max_ids(v["result"])
        unit, para, ep = max(unit, u), max(para, p), max(ep, e)
    novel["memory"]["numbering"] = {"next_unit": unit + 1, "next_para": para + 1,
                                    "next_episode": ep + 1}


def start_numbering(user_id: str, nid: str, cid: str) -> Optional[dict]:
    """转换某章时的起始编号：排在它前面的各章采用版的最大编号 +1。

    不能直接用 memory.numbering（那是全书末尾）：重转已采用的最后一章时，
    它得从自己原来的起点编，而不是接在自己后面。前面没有采用章节则返回 None。
    """
    chapter = _load_chapter(user_id, nid, cid)
    unit = para = ep = 0
    found = False
    for c in _chapters(user_id, nid):
        if c["id"] == cid or c["order"] >= chapter["order"] or not c.get("adopted_version"):
            continue
        v = _read(_version_path(user_id, nid, c["id"], c["adopted_version"]))
        if not v or not v.get("result"):
            continue
        found = True
        u, p, e = _max_ids(v["result"])
        unit, para, ep = max(unit, u), max(para, p), max(ep, e)
    if not found:
        return None
    return {"next_unit": unit + 1, "next_para": para + 1, "next_episode": ep + 1}


def adopt_version(user_id: str, nid: str, cid: str, vid: str) -> dict:
    """把某个版本设为本章采用版，写入长期记忆。

    只有「最后一个已采用的章节」能换采用版：后面的章节是接着这一章的编号转出来的，
    这一章换了版本，后面的编号就对不上了。旧数据迁移来的章节编号本就不接续，不受此限。
    """
    with _lock:
        novel = _load_novel(user_id, nid)
        chapter = _load_chapter(user_id, nid, cid)
        v = get_version(user_id, nid, cid, vid)
        if v.get("status") not in ADOPTABLE or not v.get("result"):
            raise NovelError(f"这个版本的状态是 {v.get('status')}，不能采用"
                             "（只有转换成功、且人工编辑后仍通过复验的版本可以）")
        if chapter.get("adopted_version") == vid:
            return {"chapter_id": cid, "adopted_version": vid, "added": 0, "merged": 0,
                    "retracted": 0, "changed": False}
        later = [c for c in _chapters(user_id, nid)
                 if c["order"] > chapter["order"] and c.get("adopted_version")
                 and not c.get("legacy_numbering")]
        if later and not chapter.get("legacy_numbering"):
            names = "、".join(c["title"] for c in later)
            raise NovelError(f"后面的章节（{names}）已经接着本章的编号转换过，"
                             "本章不能再换采用版；要换，先删掉或重转后面的章节")
        retracted = 0
        if chapter.get("adopted_version"):
            retracted = _retract(novel, cid)
            _retract_digest(novel, cid)
        counts = _absorb(novel, cid, vid, v["result"])
        chapter["adopted_version"] = vid
        _save_chapter(user_id, nid, chapter)
        _recompute_numbering(user_id, novel)
        _save_novel(user_id, novel)
    return {"chapter_id": cid, "adopted_version": vid, "retracted": retracted,
            "changed": True, **counts}


# ---------- 长期记忆：资产卡人工维护 ----------

def get_memory(user_id: str, nid: str) -> dict:
    memory = _load_novel(user_id, nid)["memory"]
    return {k: v for k, v in memory.items() if k != "asset_origin"}


def seed_assets(user_id: str, nid: str) -> Optional[dict]:
    """转换时注入【已有资产库】；空库返回 None（与 library.seed_for 同口径）。"""
    assets = {k: v for k, v in _load_novel(user_id, nid)["memory"]["assets"].items() if v}
    return assets or None


def upsert_asset(user_id: str, nid: str, kind: str, card: dict) -> dict:
    if kind not in KINDS:
        raise NovelError(f"未知的资产类别：{kind}")
    card_id = (card or {}).get("id")
    if not card_id:
        raise NovelError("资产卡必须带 id")
    if not (card.get("name") or "").strip():
        raise NovelError("资产卡必须有名称")
    with _lock:
        novel = _load_novel(user_id, nid)
        lst = novel["memory"]["assets"].setdefault(kind, [])
        for i, existing in enumerate(lst):
            if existing.get("id") == card_id:
                lst[i] = card
                break
        else:
            lst.append(card)
        lst.sort(key=lambda c: c.get("id", ""))
        origin = novel["memory"].setdefault("asset_origin", {k: {} for k in KINDS})
        if card_id in origin.get(kind, {}):
            # 人改过的卡不再随换采用版撤回
            origin[kind][card_id]["edited"] = True
        _save_novel(user_id, novel)
    return card


def delete_asset(user_id: str, nid: str, kind: str, card_id: str) -> None:
    if kind not in KINDS:
        raise NovelError(f"未知的资产类别：{kind}")
    with _lock:
        novel = _load_novel(user_id, nid)
        lst = novel["memory"]["assets"].get(kind) or []
        rest = [c for c in lst if c.get("id") != card_id]
        if len(rest) == len(lst):
            raise NotFound("资产卡不存在")
        novel["memory"]["assets"][kind] = rest
        novel["memory"].setdefault("asset_origin", {}).get(kind, {}).pop(card_id, None)
        _save_novel(user_id, novel)


# ---------- 长期记忆：人物生命周期、主线剧情、创作限制 ----------

def _retract_digest(novel: dict, cid: str, chapter_deleted: bool = False) -> None:
    """撤回某章章后整理写入的东西：模型提议的、还没被人确认的生命周期记录，
    和模型写的本章摘要。人确认过的、人手写的保留——除非章节本身被删了。"""
    memory = novel["memory"]

    def keep(e):
        if (e.get("since") or {}).get("chapter_id") != cid:
            return True
        if chapter_deleted:
            return False
        return e.get("origin") == "user" or e.get("status") == "confirmed"
    memory["lifecycle"] = [e for e in memory["lifecycle"] if keep(e)]
    memory["plot"]["chapters"] = [
        s for s in memory["plot"]["chapters"]
        if s.get("chapter_id") != cid or (not chapter_deleted and s.get("origin") == "user")]


def _character_ids(novel: dict) -> set:
    return {c.get("id") for c in novel["memory"]["assets"].get("characters") or []}


def _check_lifecycle_fields(novel: dict, character_id, kind) -> None:
    if character_id not in _character_ids(novel):
        raise NovelError(f"资产库里没有角色 {character_id}")
    if kind not in LIFECYCLE_TYPES:
        raise NovelError(f"未知的状态类型：{kind}（可选 {'、'.join(LIFECYCLE_TYPES)}）")


def add_lifecycle(user_id: str, nid: str, *, character_id: str, type: str,
                  detail: str = "", chapter_id: Optional[str] = None,
                  unit_ref: Optional[str] = None, evidence_quote: str = "") -> dict:
    """人手动添加一条（origin=user，直接视为已确认）。"""
    with _lock:
        novel = _load_novel(user_id, nid)
        _check_lifecycle_fields(novel, character_id, type)
        if chapter_id:
            _load_chapter(user_id, nid, chapter_id)
        entry = {"id": _new_id("l"), "character_id": character_id, "type": type,
                 "detail": (detail or "").strip(),
                 "since": {"chapter_id": chapter_id, "unit_ref": unit_ref},
                 "evidence_quote": evidence_quote or "", "origin": "user",
                 "status": "confirmed", "written_by": None}
        novel["memory"]["lifecycle"].append(entry)
        _save_novel(user_id, novel)
    return entry


def update_lifecycle(user_id: str, nid: str, lid: str, *, status: Optional[str] = None,
                     type: Optional[str] = None, detail: Optional[str] = None) -> dict:
    """确认 / 驳回 / 修改。"""
    if status is not None and status not in ("proposed", "confirmed", "rejected"):
        raise NovelError(f"未知的状态：{status}")
    with _lock:
        novel = _load_novel(user_id, nid)
        entry = next((e for e in novel["memory"]["lifecycle"] if e["id"] == lid), None)
        if entry is None:
            raise NotFound("生命周期记录不存在")
        if type is not None:
            _check_lifecycle_fields(novel, entry["character_id"], type)
            entry["type"] = type
        if detail is not None:
            entry["detail"] = detail.strip()
        if status is not None:
            entry["status"] = status
        _save_novel(user_id, novel)
    return entry


def delete_lifecycle(user_id: str, nid: str, lid: str) -> None:
    with _lock:
        novel = _load_novel(user_id, nid)
        rest = [e for e in novel["memory"]["lifecycle"] if e["id"] != lid]
        if len(rest) == len(novel["memory"]["lifecycle"]):
            raise NotFound("生命周期记录不存在")
        novel["memory"]["lifecycle"] = rest
        _save_novel(user_id, novel)


def set_outline(user_id: str, nid: str, outline: str) -> dict:
    with _lock:
        novel = _load_novel(user_id, nid)
        novel["memory"]["plot"]["outline"] = (outline or "").strip()
        _save_novel(user_id, novel)
    return novel["memory"]["plot"]


def set_synopsis(user_id: str, nid: str, cid: str, synopsis: str) -> dict:
    """人改某章摘要：标 origin=user，之后不再被章后整理自动覆盖。"""
    text = (synopsis or "").strip()
    if len(text) > SYNOPSIS_MAX:
        raise NovelError(f"每章摘要不超过 {SYNOPSIS_MAX} 字（现在 {len(text)} 字）")
    with _lock:
        novel = _load_novel(user_id, nid)
        _load_chapter(user_id, nid, cid)
        chapters = [s for s in novel["memory"]["plot"]["chapters"]
                    if s.get("chapter_id") != cid]
        entry = {"chapter_id": cid, "synopsis": text, "origin": "user"}
        if text:
            chapters.append(entry)
        novel["memory"]["plot"]["chapters"] = chapters
        _save_novel(user_id, novel)
    return entry


def _clean_constraint(body: dict, base: Optional[dict] = None) -> dict:
    c = dict(base or {})
    for key in ("text", "negative_prompt", "keywords", "enabled"):
        if body.get(key) is not None:
            c[key] = body[key]
    c["text"] = str(c.get("text") or "").strip()
    if not c["text"]:
        raise NovelError("限制必须写明规则（text）")
    c["negative_prompt"] = str(c.get("negative_prompt") or "").strip()
    keywords = c.get("keywords") or []
    if isinstance(keywords, str):
        keywords = keywords.replace("，", ",").split(",")
    c["keywords"] = [k.strip() for k in keywords if str(k).strip()]
    c["enabled"] = bool(c.get("enabled", True))
    return c


def add_constraint(user_id: str, nid: str, body: dict) -> dict:
    with _lock:
        novel = _load_novel(user_id, nid)
        entry = {"id": _new_id("k"), **_clean_constraint(body)}
        novel["memory"]["constraints"].append(entry)
        _save_novel(user_id, novel)
    return entry


def update_constraint(user_id: str, nid: str, kid: str, body: dict) -> dict:
    with _lock:
        novel = _load_novel(user_id, nid)
        lst = novel["memory"]["constraints"]
        for i, c in enumerate(lst):
            if c["id"] == kid:
                lst[i] = {"id": kid, **_clean_constraint(body, c)}
                _save_novel(user_id, novel)
                return lst[i]
    raise NotFound("限制不存在")


def delete_constraint(user_id: str, nid: str, kid: str) -> None:
    with _lock:
        novel = _load_novel(user_id, nid)
        rest = [c for c in novel["memory"]["constraints"] if c["id"] != kid]
        if len(rest) == len(novel["memory"]["constraints"]):
            raise NotFound("限制不存在")
        novel["memory"]["constraints"] = rest
        _save_novel(user_id, novel)


def novel_context(user_id: str, nid: str, cid: str) -> NovelContext:
    """转换某章时注入的长期记忆：只取排在它前面的章节已确定的事（重转前面的章节时，
    不能让它「知道」后面章节才发生的死亡），加上全书梗概与启用中的限制。"""
    novel = _load_novel(user_id, nid)
    memory = novel["memory"]
    chapter = _load_chapter(user_id, nid, cid)
    earlier = sorted((c for c in _chapters(user_id, nid)
                      if c["id"] != cid and c["order"] < chapter["order"]),
                     key=lambda c: c["order"])
    titles = {c["id"]: c["title"] for c in earlier}
    lifecycle = []
    for e in memory["lifecycle"]:
        since = (e.get("since") or {}).get("chapter_id")
        if e.get("status") != "confirmed" or (since and since not in titles):
            continue
        lifecycle.append({**e, "since": {**(e.get("since") or {}),
                                         "chapter_title": titles.get(since, "")}})
    synopses = {s["chapter_id"]: s["synopsis"] for s in memory["plot"]["chapters"]}
    return NovelContext(
        lifecycle=lifecycle,
        names={c.get("id"): c.get("name", "") for c in
               memory["assets"].get("characters") or []},
        outline=memory["plot"].get("outline") or "",
        synopses=[(c["title"], synopses[c["id"]]) for c in earlier
                  if synopses.get(c["id"])],
        constraints=[c for c in memory["constraints"] if c.get("enabled", True)],
    )


def digest_input(user_id: str, nid: str, cid: str) -> tuple:
    """章后整理的输入：(采用版 id, 本章句单元, 角色卡名单)。没有采用版时抛 NovelError。"""
    chapter = _load_chapter(user_id, nid, cid)
    vid = chapter.get("adopted_version")
    if not vid:
        raise NovelError("本章还没有采用版")
    doc = get_version(user_id, nid, cid, vid).get("result") or {}
    units = [{"id": u["id"], "text": u.get("text", "")}
             for u in (doc.get("source") or {}).get("units") or []]
    characters = _load_novel(user_id, nid)["memory"]["assets"].get("characters") or []
    return vid, units, [{"id": c.get("id"), "name": c.get("name", "")} for c in characters]


def set_digest_state(user_id: str, nid: str, cid: str, status: str, **fields) -> None:
    """章节上记一下章后整理走到哪：running / done / failed / off。"""
    with _lock:
        chapter = _load_chapter(user_id, nid, cid)
        chapter["digest"] = {"status": status, "at": now_iso(), **fields}
        _save_chapter(user_id, nid, chapter)


def record_digest(user_id: str, nid: str, cid: str, vid: str, proposals: list,
                  synopsis: str, dropped: list) -> dict:
    """章后整理的结果写进长期记忆。期间换了采用版就作废（结果属于旧版本）。"""
    with _lock:
        chapter = _load_chapter(user_id, nid, cid)
        if chapter.get("adopted_version") != vid:
            return {"stale": True}
        novel = _load_novel(user_id, nid)
        memory = novel["memory"]
        _retract_digest(novel, cid)
        # 人已经确认过的同一角色同一类型不再重复提议
        settled = {(e["character_id"], e["type"]) for e in memory["lifecycle"]
                   if e.get("status") in ("confirmed", "rejected")
                   and (e.get("since") or {}).get("chapter_id") == cid}
        added = 0
        for p in proposals:
            if (p["character_id"], p["type"]) in settled:
                continue
            memory["lifecycle"].append({
                "id": _new_id("l"), "character_id": p["character_id"], "type": p["type"],
                "detail": p.get("detail", ""),
                "since": {"chapter_id": cid, "unit_ref": p["unit_ref"]},
                "evidence_quote": p["evidence_quote"], "origin": "model",
                "status": "proposed",
                "written_by": {"chapter_id": cid, "version_id": vid}})
            added += 1
        user_written = any(s.get("chapter_id") == cid and s.get("origin") == "user"
                           for s in memory["plot"]["chapters"])
        if synopsis and not user_written:
            memory["plot"]["chapters"].append(
                {"chapter_id": cid, "synopsis": synopsis, "origin": "model"})
        _save_novel(user_id, novel)
        chapter["digest"] = {"status": "done", "at": now_iso(), "version_id": vid,
                             "proposed": added, "dropped": dropped,
                             "synopsis_kept_user": bool(synopsis and user_written)}
        _save_chapter(user_id, nid, chapter)
    return chapter["digest"]


# ---------- 旧数据迁移 ----------

def _reconstruct_text(doc: dict) -> str:
    """旧转换记录没存原文：用句单元按段落拼回（段内直接相连，段间换行）。"""
    lines, para, buf = [], None, []
    for u in (doc.get("source") or {}).get("units") or []:
        if para is not None and u.get("para") != para:
            lines.append("".join(buf))
            buf = []
        para = u.get("para")
        buf.append(u.get("text") or "")
    if buf:
        lines.append("".join(buf))
    return "\n".join(lines)


def migrate_legacy(user_id: str) -> dict:
    """把旧的扁平转换记录与资产库归到 小说 → 章节 → 版本 下。幂等：做过就不再做。

    旧文件（runs/*.json、library.json）原样保留不删，迁移只读不写它们。
    """
    from server import library, store   # 延迟导入：避免模块级依赖成环

    marker = novels_dir(user_id) / _MIGRATED
    with _lock:
        if marker.exists():
            return {"migrated": False}
        by_title: dict = {}
        for summary in store.list_runs(user_id):
            record = store.get(user_id, summary["id"])
            if not record:
                continue
            doc = record.get("result") or {}
            params = record.get("params") or {}
            title = ((doc.get("meta") or {}).get("title") or params.get("work_title")
                     or "未命名作品")
            chapter = ((doc.get("source") or {}).get("chapter") or params.get("chapter")
                       or "全文")
            by_title.setdefault(title, {}).setdefault(chapter, []).append(record)

        works = {w["work_title"] for w in library.list_works(user_id)}
        stats = {"novels": 0, "chapters": 0, "versions": 0}
        existing = {n["title"]: n for n in _all_novels(user_id)}
        for title in sorted(set(by_title) | works):
            novel = existing.get(title) or create_novel(user_id, title)
            stats["novels"] += title not in existing
            chapters = by_title.get(title, {})
            for order, (chapter_title, records) in enumerate(
                    sorted(chapters.items(),
                           key=lambda kv: min(r.get("created_at") or "" for r in kv[1])),
                    1):
                records.sort(key=lambda r: r.get("created_at") or "")
                latest_doc = next((r["result"] for r in reversed(records)
                                   if r.get("result")), {})
                ch = create_chapter(user_id, novel["id"], chapter_title,
                                    _reconstruct_text(latest_doc), order)
                ch["legacy_numbering"] = True     # 旧数据每章都从 u0001 起编，不接续
                ch["text_reconstructed"] = True
                _save_chapter(user_id, novel["id"], ch)
                stats["chapters"] += 1
                for r in records:
                    params = {k: v for k, v in (r.get("params") or {}).items()
                              if k not in ("work_title", "chapter")}
                    v = {**r, "novel_id": novel["id"], "chapter_id": ch["id"],
                         "params": params, "input_text": None, "legacy_run": True}
                    _write(_version_path(user_id, novel["id"], ch["id"], r["id"]), v)
                    stats["versions"] += 1
                # 最近一次可采用的版本设为采用版；资产以库里的为准（下面整体导入），
                # 这里只登记采用关系
                adoptable = [r for r in records
                             if r.get("status") in ADOPTABLE and r.get("result")]
                if adoptable:
                    ch["adopted_version"] = adoptable[-1]["id"]
                    _save_chapter(user_id, novel["id"], ch)
                legacy_params = {k: v for k, v in (records[-1].get("params") or {}).items()
                                 if k not in ("work_title", "chapter")}
            novel = _load_novel(user_id, novel["id"])
            if not novel.get("params") and chapters:
                novel["params"] = legacy_params      # 最近一章的制作参数作小说默认值
            work = library.get_work(user_id, title)
            if work:
                # 旧资产库是用户维护过的版本，整体作为长期记忆的资产底子（来源标记为人工）
                for kind in KINDS:
                    for card in work.get("assets", {}).get(kind) or []:
                        lst = novel["memory"]["assets"].setdefault(kind, [])
                        if not any(c.get("id") == card.get("id") for c in lst):
                            lst.append(card)
                    novel["memory"]["assets"][kind] = sorted(
                        novel["memory"]["assets"].get(kind) or [],
                        key=lambda c: c.get("id", ""))
            else:
                for ch in _chapters(user_id, novel["id"]):
                    if ch.get("adopted_version"):
                        v = get_version(user_id, novel["id"], ch["id"], ch["adopted_version"])
                        _absorb(novel, ch["id"], ch["adopted_version"], v.get("result"))
            _recompute_numbering(user_id, novel)
            _save_novel(user_id, novel)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(now_iso() + "\n", encoding="utf-8")
    return {"migrated": True, **stats}
