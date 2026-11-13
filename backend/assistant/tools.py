"""助手的只读工具。身份（user_id / novel_id）与当前位置从 RunnableConfig 读，由服务端注入，模型改不了。

返回 JSON 文本，给模型看；条数与长度都有上限，免得一次塞爆上下文。出错抛 ToolException（带代码的是 ToolError），
ToolNode 会把它变成 status=error 的 ToolMessage，对话不中断。
"""
import json
import re
from typing import Callable, Optional

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import ToolException, tool

from render import session
from server import auth, novels, summary
from server.library import KINDS
from server.messages import UserError, ref

MAX_CHARS = 4000
MAX_ITEMS = 20
STEPS = ("import", "storyboard", "review", "render", "compose", "download")
LIVE = ("queued", "running")

# 在跑的任务表在 server/app.py 的内存里；由 app 在导入时设置（不放进 config，免得存档要序列化它）
jobs_source: Callable[[str], list] = lambda user_id: []


class ToolError(UserError, ToolException):
    """带代码的工具报错（spec 子计划 4 D）：str() 是给模型的中文兜底，与改造前一字不差；
    消息对象由 graph._with_artifact 放进 ToolMessage.artifact 给界面。仍是 ToolException，原有 except 照样接住。"""


def _tool_error_text(e: ToolException) -> str:
    """工具报错 → 给模型的正文。带代码的 ToolError 再抛出去，交给 ToolNode 的包装补上 artifact
    （LangChain 的工具在报错时不带 artifact）；普通 ToolException 照旧只有正文。"""
    if isinstance(e, ToolError):
        raise e
    return e.args[0] if e.args else "Tool execution error"


def _tool(fn=None, **kwargs):
    """@tool（可带 response_format 等参数），并让 ToolException 变成 error 结果而不是中断整轮；带代码的 ToolError 交给 ToolNode 的包装补 artifact。"""
    def wrap(f):
        t = tool(**kwargs)(f) if kwargs else tool(f)
        t.handle_tool_error = _tool_error_text
        return t
    return wrap(fn) if fn is not None else wrap


def _ctx(config: RunnableConfig) -> tuple:
    c = config.get("configurable") or {}
    return c["user_id"], c["novel_id"], c.get("where") or {}


def _dump(obj) -> str:
    """工具结果的唯一出口（模型、存档、历史看到的都是它）：隐去服务器目录（片段报错、任务日志里可能带）。"""
    from assistant.events import _hide
    s = _hide(json.dumps(obj, ensure_ascii=False), str(auth.DATA_DIR))
    if len(s) > MAX_CHARS:
        tail = "（已截断）"
        s = s[:MAX_CHARS - len(tail)] + tail
    return s


def _cap(items: list) -> tuple:
    return items[:MAX_ITEMS], max(0, len(items) - MAX_ITEMS)


def _novel(user_id: str, nid: str) -> dict:
    try:
        return novels.get_novel(user_id, nid)
    except novels.NotFound:
        raise ToolError.of("novel.not_found")


def _chapters(user_id: str, nid: str) -> list:
    return sorted(_novel(user_id, nid)["chapters"], key=lambda c: c.get("order") or 0)


_CN = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def _cn_num(s: str) -> Optional[int]:
    """一到九十九的中文数字。"""
    if not s or any(ch not in _CN and ch != "十" for ch in s):
        return None
    if "十" not in s:
        return _CN[s] if len(s) == 1 else None
    tens, _, ones = s.partition("十")
    t = _CN.get(tens, None) if tens else 1
    o = _CN.get(ones, None) if ones else 0
    return None if t is None or o is None else t * 10 + o


def resolve_chapter(chapters: list, ref_: Optional[str], default_id: Optional[str]) -> dict:
    """章节编号 / 第N章 / 纯数字（序号）/ 标题片段 → 章节摘要；不给 ref 时取当前章。解析不出来时列候选。"""
    def fail(code: str, **params):
        listing = "；".join(f"{c['id']} {c['title']}" for c in chapters)
        raise ToolError.of(code, options=listing or ref("assistant.tool.no_chapters"), **params)

    ref_ = (ref_ or "").strip()
    if not ref_:
        hit = next((c for c in chapters if c["id"] == default_id), None)
        return hit or fail("assistant.tool.pick_chapter")
    hit = next((c for c in chapters if c["id"] == ref_), None)
    if hit:
        return hit
    m = re.fullmatch(r"第?\s*([0-9]+|[零一二两三四五六七八九十]+)\s*章?", ref_)
    if m:
        n = int(m.group(1)) if m.group(1).isdigit() else _cn_num(m.group(1))
        if n and 1 <= n <= len(chapters):
            return chapters[n - 1]
        fail("assistant.tool.no_such_chapter", n=m.group(1))
    found = [c for c in chapters if ref_ in c["title"]]
    if len(found) == 1:
        return found[0]
    fail("assistant.tool.ambiguous_chapter", text=ref_)


def _session(user_id: str, nid: str, cid: str, vid: Optional[str]) -> Optional[dict]:
    if not vid:
        return None
    try:
        return session.load(novels.render_dir(user_id, nid, cid, vid))
    except (session.Corrupt, novels.NotFound):
        return None


def _stage(ch: dict, sess: Optional[dict]) -> str:
    """与前端 chapterStage（frontend/src/workflow.ts）同一套规则（实施裁定 8），只用于给模型的文字。"""
    if not ch.get("chars"):
        return "import"
    versions = ch.get("versions") or []
    if ch.get("latest_status") in LIVE:
        return "storyboard"
    v = (next((x for x in versions if x["id"] == ch.get("adopted_version")), None)
         or next((x for x in versions if x.get("status") in novels.ADOPTABLE), None)
         or next((x for x in versions if x.get("status") == "draft_invalid"), None))
    if not v:
        return "storyboard"
    if v.get("status") == "draft_invalid" or v.get("verification_status") == "failed":
        return "review"
    film = summary._film(sess)
    if not film or film["total"] <= 0 or film["done"] < film["total"]:
        return "render"
    return "download" if summary._final(sess) == "fresh" else "compose"


def _doc(user_id: str, nid: str, ch: dict) -> tuple:
    vid = summary._pick_version(ch)
    if not vid:
        return None, {}
    try:
        return vid, novels.get_version(user_id, nid, ch["id"], vid).get("result") or {}
    except novels.NotFound:
        return None, {}


@_tool
def novel_overview(config: RunnableConfig) -> str:
    """这部小说的总览：标题、各章（编号、标题、所在步骤、镜头数、时长、出片进度、成片状态）和总花费。"""
    uid, nid, _ = _ctx(config)
    novel = _novel(uid, nid)
    whole = summary.novel_summary(uid, nid)
    sums = {c["id"]: c for c in whole["chapters"]}
    out = []
    for ch in sorted(novel["chapters"], key=lambda c: c.get("order") or 0):
        s = sums.get(ch["id"]) or {}
        sess = _session(uid, nid, ch["id"], s.get("version"))
        out.append({"id": ch["id"], "title": ch["title"], "stage": _stage(ch, sess),
                    "shots": s.get("shots"), "duration_s": s.get("duration_s"),
                    "film": s.get("film"), "final": s.get("final", "none")})
    items, more = _cap(out)
    return _dump({"title": novel["title"], "chapters": items, "more": more,
                  "cost": whole["cost"]})


@_tool
def chapter_status(config: RunnableConfig, chapter: Optional[str] = None) -> str:
    """一章的状态：版本列表（编号、状态、时间、镜头数）、采用的版本、所在步骤、章后整理状态。chapter 可写编号、「第三章」或标题片段，缺省为当前章。"""
    uid, nid, where = _ctx(config)
    ch = resolve_chapter(_chapters(uid, nid), chapter, where.get("chapter_id"))
    vid = summary._pick_version(ch)
    sess = _session(uid, nid, ch["id"], vid)
    versions, more = _cap([{"id": v["id"], "status": v.get("status"), "created_at": v.get("created_at"),
                            "shots": v.get("shots")} for v in ch.get("versions") or []])
    return _dump({"id": ch["id"], "title": ch["title"], "stage": _stage(ch, sess),
                  "adopted_version": ch.get("adopted_version"), "versions": versions, "more": more,
                  "digest": (ch.get("digest") or {}).get("status"), "film": summary._film(sess)})


@_tool
def shots_get(config: RunnableConfig, chapter: Optional[str] = None,
              shot_ids: Optional[list[str]] = None) -> str:
    """一章（采用版或最新可用版）的镜头要点：编号、所属集、景别、时长、画面、旁白、台词。一次最多 20 个；shot_ids 缺省取前 20 个。"""
    uid, nid, where = _ctx(config)
    ch = resolve_chapter(_chapters(uid, nid), chapter, where.get("chapter_id"))
    vid, doc = _doc(uid, nid, ch)
    if not vid:
        raise ToolError.of("assistant.tool.no_version", chapter=ch["title"])
    rows = []
    for ep in doc.get("episodes") or []:
        for s in ep.get("shots") or []:
            if shot_ids and s.get("id") not in shot_ids:
                continue
            rows.append({"id": s.get("id"), "episode": ep.get("id"), "shot_size": s.get("shot_size"),
                         "duration_sec": s.get("duration_sec"), "action": s.get("action"),
                         "narration": (s.get("narration") or {}).get("text"),
                         "dialogue": [{"character_ref": d.get("character_ref"), "text": d.get("text")}
                                      for d in s.get("dialogue") or []]})
    items, more = _cap(rows)
    return _dump({"chapter": ch["title"], "version": vid, "shots": items, "more": more})


@_tool
def assets_find(config: RunnableConfig, query: Optional[str] = None, kind: Optional[str] = None) -> str:
    """查资产卡（角色 characters、场景 locations、道具 props、生物 creatures）：按名字、别名或编号匹配 query，可按 kind 过滤。最多 20 张。"""
    uid, nid, _ = _ctx(config)
    if kind and kind not in KINDS:
        raise ToolError.of("assistant.tool.bad_kind", options=", ".join(KINDS))
    assets = _novel(uid, nid)["memory"]["assets"]
    q = (query or "").strip().lower()
    rows = []
    for k in KINDS:
        if kind and k != kind:
            continue
        for c in assets.get(k) or []:
            names = [c.get("id") or "", c.get("name") or ""] + list(c.get("aliases") or [])
            if q and not any(q in n.lower() for n in names):
                continue
            notes = c.get("persona_notes") or c.get("description") or c.get("visual_prompt") or ""
            rows.append({"id": c.get("id"), "kind": k, "name": c.get("name"),
                         "aliases": c.get("aliases") or [], "notes": notes[:200]})
    items, more = _cap(rows)
    return _dump({"assets": items, "more": more})


@_tool
def plot_get(config: RunnableConfig) -> str:
    """主线剧情与各章梗概。"""
    uid, nid, _ = _ctx(config)
    novel = _novel(uid, nid)
    plot = novel["memory"].get("plot") or {}
    titles = {c["id"]: c["title"] for c in novel["chapters"]}
    chapters, more = _cap([{"chapter": titles.get(s.get("chapter_id"), s.get("chapter_id")),
                            "synopsis": s.get("synopsis")} for s in plot.get("chapters") or []])
    return _dump({"outline": (plot.get("outline") or "")[:2000], "chapters": chapters, "more": more})


@_tool
def film_status(config: RunnableConfig, chapter: Optional[str] = None) -> str:
    """一章的出片与合成状态：各段计数、没出完或失败的段（含原因、预估金额）、已花与上限（元）、成片状态。"""
    uid, nid, where = _ctx(config)
    ch = resolve_chapter(_chapters(uid, nid), chapter, where.get("chapter_id"))
    vid = summary._pick_version(ch)
    s = _session(uid, nid, ch["id"], vid)
    if not s:
        return _dump({"chapter": ch["title"], "version": vid, "session": None})
    pending, more = _cap([{"id": c["id"], "state": c["state"], "error": c.get("error"),
                           "estimate_cny": c.get("estimate_cny"), "uncertain": bool(c.get("uncertain"))}
                          for c in s.get("clips") or [] if c.get("state") != "done"])
    return _dump({"chapter": ch["title"], "version": vid,
                  "session": {"counts": summary._film(s), "pending": pending, "more": more,
                              "spent_cny": s.get("spent_cny"), "budget_cny": s.get("budget_cny"),
                              "final": summary._final(s)}})


@_tool
def jobs_running(config: RunnableConfig) -> str:
    """这部小说正在跑的任务（生成分镜等）：章节、进度百分比、最新一行日志。"""
    uid, nid, _ = _ctx(config)
    rows = []
    for j in jobs_source(uid):
        if j.get("novel_id") != nid or j.get("status") not in LIVE:
            continue
        p = j.get("progress") or {}
        pct = round(100 * p["done_chars"] / p["total_chars"]) if p.get("total_chars") else None
        rows.append({"id": j["id"], "chapter": j.get("chapter"), "status": j["status"],
                     "percent": pct, "last_log": j.get("last_log")})
    items, more = _cap(rows)
    return _dump({"jobs": items, "more": more})


@_tool(response_format="content_and_artifact")
def goto(config: RunnableConfig, step: str, chapter: Optional[str] = None):
    """在回答下方放一个跳转按钮，让用户自己去那一步操作。step 取 import / storyboard / review / render / compose / download；chapter 缺省为当前章。没有副作用。"""
    uid, nid, where = _ctx(config)
    if step not in STEPS:
        raise ToolError.of("assistant.tool.bad_step", options=", ".join(STEPS))
    ch = resolve_chapter(_chapters(uid, nid), chapter, where.get("chapter_id"))
    return f"已在回答下方放了「{ch['title']} · {step}」的跳转按钮", {"chapter_id": ch["id"], "step": step}


TOOLS = [novel_overview, chapter_status, shots_get, assets_find, plot_get, film_status, jobs_running, goto]
