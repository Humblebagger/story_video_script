"""助手的操作工具（spec §7）：生成分镜、出片、配音合成先出确认卡，用户点确认才执行；导出不花钱，直接放下载按钮。

确认：服务端先算预估，interrupt(卡) 暂停这一轮；用户点按钮后接口用 Command(resume={中断编号: {decision, card}})
接着跑，card 是接口从存档里取的那张（不信前端）。恢复时工具从头重跑：按当前位置重算整张卡，章节或版本、
要出的段、金额与要点与用户确认的卡有一样对不上就不执行，报错，由助手再调一次工具出新卡；执行一律按用户看到的那张卡。每次调用只中断一次：多次中断时恢复会按顺序重放旧回答，
重放时的重算可能已经不同，用户最后的「取消」会被前面的「确认」盖掉。
被恢复的那次调用（configurable.resume_tool_call）不管金额多少都先取回答，免得「恢复时变免费」跳过用户的取消。
执行函数在 server/app.py（与接口同一份：鉴权、验证门、上限、确认金额都一样），由 app 在导入时填进 ops——
本包不能反过来导入 app（循环导入）。
"""
from typing import Annotated, Callable, Optional

from fastapi import HTTPException
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolCallId, ToolException
from langgraph.types import interrupt

from assistant.tools import LIVE, ToolError, _chapters, _ctx, _tool, resolve_chapter
from server import summary
from server.messages import money, msg, ref

# 名字 → app 里的执行函数：start_version / film_quote / film_run / compose_quote / compose_start / export_check
ops: dict = {}


def _op(name: str, *args):
    """调 app 里的执行函数；HTTPException 变成工具报错：带代码的保留代码（界面按语言渲染），正文给模型。"""
    try:
        return ops[name](*args)
    except HTTPException as e:
        d = e.detail
        if isinstance(d, dict) and d.get("code"):
            raise ToolError.from_msg(d)
        raise ToolException(d.get("message", str(d)) if isinstance(d, dict) else str(d))


def _where(config: RunnableConfig, chapter: Optional[str]) -> tuple:
    uid, nid, where = _ctx(config)
    return uid, nid, resolve_chapter(_chapters(uid, nid), chapter, where.get("chapter_id"))


def _version(ch: dict) -> str:
    vid = summary._pick_version(ch)
    if not vid:
        raise ToolError.of("assistant.tool.no_version", chapter=ch["title"])
    return vid


def _card(tool_call_id: str, action: str, ch: dict, vid: Optional[str], quote: dict) -> dict:
    return {"tool_call_id": tool_call_id, "action": action, "chapter_id": ch["id"], "chapter": ch["title"],
            "version_id": vid, **quote}


def _same(a: dict, b: dict) -> bool:
    """预估与卡一致：金额（都没有，或相差不到 1e-6 元）、要点与要出的段都相同。"""
    if (a["amount"] is None) != (b["amount"] is None):
        return False
    if a["amount"] is not None and abs(a["amount"] - b["amount"]) > 1e-6:
        return False
    return a["detail"] == b["detail"] and a.get("clips") == b.get("clips")


def _money(q: dict):
    return ref("assistant.tool.model_cost") if q["amount"] is None else money(q["amount"])


def _target(c: dict) -> str:
    return c["chapter"] + (f" {c['version_id']}" if c.get("version_id") else "")


def _ask(fresh_card: Callable[[], dict]) -> tuple:
    """出卡等用户确认 → (是否确认, 用户确认或取消的那张卡)。fresh_card() 按当前位置重算整张卡（章节、版本、预估）：
    确认后再算一遍，章节或版本、要出的段、金额与要点有一样对不上就不执行（报错，由助手再出新卡）。
    执行一律用返回的那张卡（用户看到的）。"""
    card = fresh_card()
    answer = interrupt(card) or {}
    seen = answer.get("card") or card
    if answer.get("decision") != "approve":
        return False, seen
    fresh = fresh_card()
    if (fresh["chapter_id"], fresh["version_id"]) != (seen["chapter_id"], seen["version_id"]):
        raise ToolError.of("assistant.tool.target_changed", before=_target(seen), after=_target(fresh))
    if not _same(fresh, seen):
        clips = (msg("assistant.tool.clips_changed", before=list(seen["clips"]), after=list(fresh["clips"]))
                 if fresh.get("clips") != seen.get("clips") else "")
        raise ToolError.of("assistant.tool.quote_changed", before=_money(seen), after=_money(fresh),
                           detail_before=str(seen["detail"]), detail_after=str(fresh["detail"]), clips=clips)
    return True, seen


def _resuming(config: RunnableConfig, tool_call_id: str) -> bool:
    """这次调用是不是正被恢复的那次（resume 接口在 configurable 里标明）。"""
    return (config.get("configurable") or {}).get("resume_tool_call") == tool_call_id


def _result(text: str, card: dict, outcome: str, task: Optional[dict] = None) -> tuple:
    return text, {"card": card, "outcome": outcome, "task": task}


@_tool(response_format="content_and_artifact")
def generate_storyboard(config: RunnableConfig, tool_call_id: Annotated[str, InjectedToolCallId],
                        chapter: Optional[str] = None):
    """把一章原文生成分镜（新版本，分钟级任务）。会花模型费用：先给用户一张确认卡，用户点确认才开始。chapter 可写编号、「第三章」或标题片段，缺省为当前章。"""

    def fresh_card() -> dict:
        uid, nid, ch = _where(config, chapter)
        if not ch.get("chars"):
            raise ToolError.of("assistant.tool.no_text", chapter=ch["title"])
        if ch.get("latest_status") in LIVE:
            raise ToolError.of("assistant.tool.job_running", chapter=ch["title"])
        return _card(tool_call_id, "generate_storyboard", ch, None, {
            "amount": None, "currency": "usd",
            "detail": {"chars": ch["chars"], "archived": bool(ch.get("adopted_version"))}})

    uid, nid, _ = _ctx(config)
    ok, card = _ask(fresh_card)
    if not ok:
        return _result("用户取消了，没有生成", card, "rejected")
    r = _op("start_version", {"id": uid}, nid, card["chapter_id"], {}, False)
    task = {"kind": "job", "chapter_id": card["chapter_id"], "version_id": r["version_id"], "job_id": r["job_id"]}
    return _result(f"已开始生成「{card['chapter']}」的分镜，进度在任务卡上", card, "approved", task)


@_tool(response_format="content_and_artifact")
def film_run(config: RunnableConfig, tool_call_id: Annotated[str, InjectedToolCallId],
             chapter: Optional[str] = None, clip_ids: Optional[list[str]] = None):
    """出片（视频生成）。clip_ids 缺省为这一章所有没出或失败的段，也可以点名几段重做。会花钱：先给用户一张带金额（元）的确认卡，用户点确认才开始。要求用户已在出片那一步选好厂商与档位。chapter 缺省为当前章。"""
    uid, nid, _ = _ctx(config)
    user, ids = {"id": uid}, (clip_ids or None)

    def fresh_card() -> dict:
        ch = _where(config, chapter)[2]
        vid = _version(ch)
        q = _op("film_quote", user, nid, ch["id"], vid, ids)
        # clips：要出的段钉在卡上，执行就出这几段（不在执行时重新挑「剩余各段」）；detail 给界面显示段数
        return _card(tool_call_id, "film_run", ch, vid, {"amount": q["amount"], "currency": "cny",
                                                         "detail": {"clips": len(q["clips"])}, "clips": q["clips"]})

    ok, card = _ask(fresh_card)
    if not ok:
        return _result("用户取消了，没有出片", card, "rejected")
    _op("film_run", user, nid, card["chapter_id"], card["version_id"], list(card["clips"]), card["amount"])
    return _result(f"已开始出「{card['chapter']}」的 {card['detail']['clips']} 段，进度在任务卡上", card, "approved",
                   {"kind": "film", "chapter_id": card["chapter_id"], "version_id": card["version_id"]})


@_tool(response_format="content_and_artifact")
def compose(config: RunnableConfig, tool_call_id: Annotated[str, InjectedToolCallId],
            chapter: Optional[str] = None, draft: bool = True):
    """配音并合成整章成片。draft=true（默认）时还没出视频的段用关键帧补位。配音要花钱时先给用户一张带金额（元）的确认卡；不花钱（配音都已缓存或不需要配音）就直接开始。chapter 缺省为当前章。"""
    uid, nid, _ = _ctx(config)
    user = {"id": uid}

    def fresh_card() -> dict:
        ch = _where(config, chapter)[2]
        vid = _version(ch)
        q = _op("compose_quote", user, nid, ch["id"], vid, draft)
        return _card(tool_call_id, "compose", ch, vid,
                     {"amount": q["amount"], "currency": "cny", "detail": {"chars": q["chars"], "draft": draft}})

    card = fresh_card()
    outcome = "done"
    if card["amount"] > 0 or _resuming(config, tool_call_id):
        ok, card = _ask(fresh_card)
        if not ok:
            return _result("用户取消了，没有合成", card, "rejected")
        outcome = "approved"
    _op("compose_start", user, nid, card["chapter_id"], card["version_id"], draft, card["amount"] or None)
    return _result(f"已开始合成「{card['chapter']}」，进度在任务卡上", card, outcome,
                   {"kind": "compose", "chapter_id": card["chapter_id"], "version_id": card["version_id"]})


@_tool(response_format="content_and_artifact")
def export_fcpxml(config: RunnableConfig, tool_call_id: Annotated[str, InjectedToolCallId],
                  chapter: Optional[str] = None):
    """导出剪辑工程（FCPXML 工程包，给达芬奇 / Final Cut 用）。不花钱：检查能导出后在回答下方放一个下载按钮。要求成片已合成且没过期。chapter 缺省为当前章。"""
    uid, nid, ch = _where(config, chapter)
    vid = _version(ch)
    _op("export_check", {"id": uid}, nid, ch["id"], vid)
    card = _card(tool_call_id, "export_fcpxml", ch, vid, {"amount": None, "currency": None, "detail": {}})
    return _result("已在回答下方放了「下载剪辑工程」按钮", card, "done",
                   {"kind": "export", "chapter_id": ch["id"], "version_id": vid})


TOOLS = [generate_storyboard, film_run, compose, export_fcpxml]
ACTIONS = tuple(t.name for t in TOOLS)
