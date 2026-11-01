"""小说汇总（只读）：花费与各章进度，供概览、费用表、左栏章节卡片使用。

成片状态取自会话里已存的 final，不重算指纹，所以「过期」不在这里判断（会话不存这个标记）。
"""
from typing import Optional

from render import compose, session
from server import novels, pricing, usage


def _pick_version(chapter: dict) -> Optional[str]:
    """采用版优先，否则最新一个可采用的版本（_version_summaries 已按时间倒序）。"""
    if chapter.get("adopted_version"):
        return chapter["adopted_version"]
    for v in chapter.get("versions") or []:
        if v.get("status") in novels.ADOPTABLE:
            return v["id"]
    return None


def _doc_stats(doc: dict) -> tuple:
    shots = 0
    seconds = 0.0
    for ep in doc.get("episodes") or []:
        for shot in ep.get("shots") or []:
            shots += 1
            seconds += compose.playable(shot)
    return shots, round(seconds, 2)


def _film(s: Optional[dict]) -> Optional[dict]:
    if not s:
        return None
    clips = s.get("clips") or []
    return {"done": sum(1 for c in clips if c.get("state") == "done"),
            "total": len(clips),
            "failed": sum(1 for c in clips if c.get("state") == "failed"),
            "running": sum(1 for c in clips if c.get("state") in session.IN_FLIGHT)}


def _final(s: Optional[dict]) -> str:
    state = ((s or {}).get("final") or {}).get("state")
    if state in session.COMPOSE_BUSY:
        return "busy"
    if state == "done":
        return "fresh"
    return "none"


def _sum(values) -> Optional[float]:
    vals = [v for v in values if v is not None]
    return round(sum(vals), 4) if vals else None


def novel_summary(user_id: str, nid: str) -> dict:
    novel = novels.get_novel(user_id, nid)      # 不存在或不属于该用户则抛 NotFound
    table = pricing.load()
    rows = [r for r in usage.read(user_id=user_id) if r.get("novel_id") == nid]
    by_chapter = {}
    for r in rows:
        by_chapter.setdefault(r.get("chapter_id"), []).append(r)

    def llm(rs: list) -> float:
        return round(sum(pricing.cost(r, table) or 0.0 for r in rs), 6)

    chapters = []
    for ch in novel["chapters"]:
        cid = ch["id"]
        vid = _pick_version(ch)
        shots = duration = film = sess = None
        final = "none"
        if vid:
            try:
                doc = novels.get_version(user_id, nid, cid, vid).get("result") or {}
                if doc.get("episodes"):
                    shots, duration = _doc_stats(doc)
            except novels.NotFound:
                vid = None
        if vid:
            try:
                sess = session.load(novels.render_dir(user_id, nid, cid, vid))
            except (session.Corrupt, novels.NotFound):
                sess = None
            film = _film(sess)
            final = _final(sess)
        chapters.append({
            "id": cid, "version": vid, "shots": shots, "duration_s": duration,
            "film": film, "final": final,
            "cost": {"llm_usd": llm(by_chapter.get(cid, [])),
                     "render_cny": (sess or {}).get("spent_cny"),
                     "budget_cny": (sess or {}).get("budget_cny")}})
    return {
        "cost": {"llm_usd": llm(rows),
                 "render_cny": _sum(c["cost"]["render_cny"] for c in chapters),
                 "budget_cny": _sum(c["cost"]["budget_cny"] for c in chapters)},
        "unpriced": usage.unpriced_models(rows, table),
        "chapters": chapters,
    }
