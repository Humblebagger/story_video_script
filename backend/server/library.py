"""用户的资产库：按作品收纳 C/S/P/A 卡，独立于任何一次转换。

为什么要独立存一份而不是每次从历史记录聚合：资产卡在这里是**一等实体**——
可以凭空新建、可以改、可以删，也可以把某次转换的产物「入库」。聚合视图做不到这些
（编辑后不知道该写回哪次转换）。

转换时从库里取出作为【已有资产库】注入，转换成功后再把新出现的卡并回库——
资产引用制的防漂移能力就此从批间、章间延伸到「这个用户的这部作品」整体。
"""
import json
import threading
from pathlib import Path
from typing import Optional

from server.auth import user_dir

KINDS = ("characters", "locations", "props", "creatures")

_lock = threading.RLock()


def _path(user_id: str) -> Path:
    return user_dir(user_id) / "library.json"


def _load(user_id: str) -> dict:
    path = _path(user_id)
    if not path.exists():
        return {"works": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"works": {}}
    data.setdefault("works", {})
    return data


def _save(user_id: str, data: dict) -> None:
    path = _path(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    tmp.replace(path)


def _now() -> str:
    from server.store import now_iso
    return now_iso()


def _empty_work(title: str) -> dict:
    return {"work_title": title, "updated_at": _now(),
            "assets": {k: [] for k in KINDS}}


def _summarize(work: dict) -> dict:
    return {
        "work_title": work["work_title"],
        "updated_at": work.get("updated_at"),
        "counts": {k: len(work["assets"].get(k) or []) for k in KINDS},
    }


def list_works(user_id: str) -> list:
    works = list(_load(user_id)["works"].values())
    works.sort(key=lambda w: w.get("updated_at") or "", reverse=True)
    return [_summarize(w) for w in works]


def get_work(user_id: str, title: str) -> Optional[dict]:
    work = _load(user_id)["works"].get(title)
    if work is None:
        return None
    return {**_summarize(work),
            "assets": {k: work["assets"].get(k) or [] for k in KINDS
                       if work["assets"].get(k)}}


def create_work(user_id: str, title: str) -> bool:
    """建一部空作品。返回 False 表示已存在。

    没有这个入口的话，资产库为空时就无处下手——作品只能由转换产生，
    而「先把人物场景设定好再去转换」恰恰是常见用法。
    """
    title = (title or "").strip()
    if not title:
        raise ValueError("作品名不能为空")
    with _lock:
        data = _load(user_id)
        if title in data["works"]:
            return False
        data["works"][title] = _empty_work(title)
        _save(user_id, data)
    return True


def upsert_card(user_id: str, title: str, kind: str, card: dict) -> dict:
    """新建或覆盖一张卡。card 必须带 id——镜头层靠 ID 引用资产。"""
    if kind not in KINDS:
        raise ValueError(f"未知的资产类别：{kind}")
    cid = (card or {}).get("id")
    if not cid:
        raise ValueError("资产卡必须带 id")
    if not (card.get("name") or "").strip():
        raise ValueError("资产卡必须有名称")

    with _lock:
        data = _load(user_id)
        work = data["works"].setdefault(title, _empty_work(title))
        lst = work["assets"].setdefault(kind, [])
        for i, existing in enumerate(lst):
            if existing.get("id") == cid:
                lst[i] = card
                break
        else:
            lst.append(card)
        lst.sort(key=lambda c: c.get("id", ""))
        work["updated_at"] = _now()
        _save(user_id, data)
    return card


def delete_card(user_id: str, title: str, kind: str, card_id: str) -> bool:
    if kind not in KINDS:
        raise ValueError(f"未知的资产类别：{kind}")
    with _lock:
        data = _load(user_id)
        work = data["works"].get(title)
        if not work:
            return False
        lst = work["assets"].get(kind) or []
        rest = [c for c in lst if c.get("id") != card_id]
        if len(rest) == len(lst):
            return False
        work["assets"][kind] = rest
        work["updated_at"] = _now()
        _save(user_id, data)
    return True


def delete_work(user_id: str, title: str) -> bool:
    with _lock:
        data = _load(user_id)
        if title not in data["works"]:
            return False
        del data["works"][title]
        _save(user_id, data)
    return True


def _merge_card(old: dict, new: dict) -> dict:
    """同 ID 卡合并：库中版本为准（可能已被人工编辑过），只做追加。

    与 prompt 里「已有角色出现新服装/新指称时追加，其余字段不改」同构——
    转换产出的新服装、新别名要收进来，但不能覆盖用户手改过的描述。
    """
    merged = dict(old)
    aliases = list(old.get("aliases") or [])
    for a in new.get("aliases") or []:
        if a not in aliases:
            aliases.append(a)
    if aliases:
        merged["aliases"] = aliases

    for key in ("outfits", "states"):
        old_list = old.get(key) or []
        if not (old_list or new.get(key)):
            continue
        seen = {x.get("id") for x in old_list}
        merged[key] = old_list + [x for x in (new.get(key) or [])
                                  if x.get("id") not in seen]
    # 库里缺的标量字段用新卡补齐（不覆盖已有值）
    for k, v in new.items():
        if k not in merged or merged[k] in (None, "", [], {}):
            merged[k] = v
    return merged


def import_assets(user_id: str, title: str, assets: dict) -> dict:
    """把一次转换的 assets 并入库。返回 {新增, 合并} 计数。"""
    added = merged = 0
    with _lock:
        data = _load(user_id)
        work = data["works"].setdefault(title, _empty_work(title))
        for kind in KINDS:
            incoming = (assets or {}).get(kind) or []
            if not incoming:
                continue
            lst = work["assets"].setdefault(kind, [])
            by_id = {c.get("id"): i for i, c in enumerate(lst)}
            for card in incoming:
                cid = card.get("id")
                if not cid:
                    continue
                if cid in by_id:
                    lst[by_id[cid]] = _merge_card(lst[by_id[cid]], card)
                    merged += 1
                else:
                    lst.append(card)
                    added += 1
            lst.sort(key=lambda c: c.get("id", ""))
        work["updated_at"] = _now()
        _save(user_id, data)
    return {"work_title": title, "added": added, "merged": merged}


def backfill_from_runs(user_id: str) -> list:
    """扫本人的历史记录，把其中的资产卡补进库。

    资产入库只在「新转换完成」时触发，所以早于该功能的转换、以及关掉
    import_assets 的转换，资产都不在库里——迁移过来的旧记录尤其如此。
    这里按作品把历史产物重新过一遍，缺什么补什么（同 ID 走追加式合并，
    不覆盖人工编辑），因此**重复执行是安全的**。
    """
    from server import store   # 延迟导入：避免与 store 的模块级依赖成环

    by_work: dict = {}
    for summary in store.list_runs(user_id):
        record = store.get(user_id, summary["id"])
        if not record:
            continue
        doc = record.get("result") or {}
        title = (doc.get("meta") or {}).get("title") \
            or (record.get("params") or {}).get("work_title")
        assets = doc.get("assets") or {}
        if not title or not any(assets.get(k) for k in KINDS):
            continue
        # 同一作品的多次转换按时间正序合并，新的覆盖不了已入库的人工编辑
        by_work.setdefault(title, []).append((summary.get("created_at") or "", assets))

    out = []
    for title, items in by_work.items():
        items.sort(key=lambda x: x[0])
        added = merged = 0
        for _, assets in items:
            r = import_assets(user_id, title, assets)
            added += r["added"]
            merged += r["merged"]
        out.append({"work_title": title, "added": added, "merged": merged})
    return out


def seed_for(user_id: str, title: str) -> Optional[dict]:
    """转换时取出作为【已有资产库】注入；库里没有这部作品则返回 None。"""
    work = _load(user_id)["works"].get(title)
    if not work:
        return None
    assets = {k: v for k, v in work["assets"].items() if v}
    return assets or None
