"""助手的操作工具（spec §7）：生成分镜、出片、配音合成先出确认卡，用户点确认才执行；导出不花钱，直接放下载按钮。

确认：服务端先算预估，interrupt(卡) 暂停这一轮；用户点按钮后接口用 Command(resume={中断编号: {decision, card}})
接着跑，card 是接口从存档里取的那张（不信前端）。恢复时工具从头重跑：重算预估，与用户确认的卡对不上就不执行，
报「预估变了」，由助手再调一次工具出新卡。每次调用只中断一次：多次中断时恢复会按顺序重放旧回答，
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

from assistant.tools import LIVE, _chapters, _ctx, _tool, resolve_chapter
from server import summary

# 名字 → app 里的执行函数：start_version / film_quote / film_run / compose_quote / compose_start / export_check
ops: dict = {}


def _op(name: str, *args):
    """调 app 里的执行函数；HTTPException 的说明变成给模型看的工具报错。"""
    try:
        return ops[name](*args)
    except HTTPException as e:
        d = e.detail
        raise ToolException(d.get("message", str(d)) if isinstance(d, dict) else str(d))


def _where(config: RunnableConfig, chapter: Optional[str]) -> tuple:
    uid, nid, where = _ctx(config)
    return uid, nid, resolve_chapter(_chapters(uid, nid), chapter, where.get("chapter_id"))


def _version(ch: dict) -> str:
    vid = summary._pick_version(ch)
    if not vid:
        raise ToolException(f"{ch['title']} 还没有可用的分镜版本")
    return vid


def _card(tool_call_id: str, action: str, ch: dict, vid: Optional[str], quote: dict) -> dict:
    return {"tool_call_id": tool_call_id, "action": action, "chapter_id": ch["id"], "chapter": ch["title"],
            "version_id": vid, **quote}


def _same(a: dict, b: dict) -> bool:
    """预估与卡一致：金额（都没有，或相差不到 1e-6 元）与要点都相同。"""
    if (a["amount"] is None) != (b["amount"] is None):
        return False
    if a["amount"] is not None and abs(a["amount"] - b["amount"]) > 1e-6:
        return False
    return a["detail"] == b["detail"]


def _money(q: dict) -> str:
    return "按模型用量计费" if q["amount"] is None else f"¥{q['amount']:.2f}"


def _ask(card: dict, quote: Callable[[], dict]) -> tuple:
    """出卡等用户确认 → (是否确认, 用户确认或取消的那张卡)。确认后重算预估，对不上就不执行（报错，由助手再出新卡）。"""
    answer = interrupt(card) or {}
    seen = answer.get("card") or card
    if answer.get("decision") != "approve":
        return False, seen
    fresh = quote()
    if not _same(fresh, seen):
        raise ToolException(f"预估变了（{_money(seen)} → {_money(fresh)}，要点 {seen['detail']} → {fresh['detail']}），"
                            "没有执行；要的话我再出一张新卡")
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
    uid, nid, ch = _where(config, chapter)

    def quote() -> dict:
        cur = resolve_chapter(_chapters(uid, nid), ch["id"], None)
        if not cur.get("chars"):
            raise ToolException(f"{cur['title']} 还没有原文")
        if cur.get("latest_status") in LIVE:
            raise ToolException(f"{cur['title']} 正在生成分镜，等它跑完再说")
        return {"amount": None, "currency": "usd",
                "detail": {"chars": cur["chars"], "archived": bool(cur.get("adopted_version"))}}

    ok, card = _ask(_card(tool_call_id, "generate_storyboard", ch, None, quote()), quote)
    if not ok:
        return _result("用户取消了，没有生成", card, "rejected")
    r = _op("start_version", {"id": uid}, nid, ch["id"], {}, False)
    task = {"kind": "job", "chapter_id": ch["id"], "version_id": r["version_id"], "job_id": r["job_id"]}
    return _result(f"已开始生成「{ch['title']}」的分镜，进度在任务卡上", card, "approved", task)


@_tool(response_format="content_and_artifact")
def film_run(config: RunnableConfig, tool_call_id: Annotated[str, InjectedToolCallId],
             chapter: Optional[str] = None, clip_ids: Optional[list[str]] = None):
    """出片（视频生成）。clip_ids 缺省为这一章所有没出或失败的段，也可以点名几段重做。会花钱：先给用户一张带金额（元）的确认卡，用户点确认才开始。要求用户已在出片那一步选好厂商与档位。chapter 缺省为当前章。"""
    uid, nid, ch = _where(config, chapter)
    vid = _version(ch)
    user, ids = {"id": uid}, (clip_ids or None)

    def quote() -> dict:
        q = _op("film_quote", user, nid, ch["id"], vid, ids)
        return {"amount": q["amount"], "currency": "cny", "detail": {"clips": len(q["clips"])}}

    ok, card = _ask(_card(tool_call_id, "film_run", ch, vid, quote()), quote)
    if not ok:
        return _result("用户取消了，没有出片", card, "rejected")
    _op("film_run", user, nid, ch["id"], vid, ids, card["amount"])
    return _result(f"已开始出「{ch['title']}」的 {card['detail']['clips']} 段，进度在任务卡上", card, "approved",
                   {"kind": "film", "chapter_id": ch["id"], "version_id": vid})


@_tool(response_format="content_and_artifact")
def compose(config: RunnableConfig, tool_call_id: Annotated[str, InjectedToolCallId],
            chapter: Optional[str] = None, draft: bool = True):
    """配音并合成整章成片。draft=true（默认）时还没出视频的段用关键帧补位。配音要花钱时先给用户一张带金额（元）的确认卡；不花钱（配音都已缓存或不需要配音）就直接开始。chapter 缺省为当前章。"""
    uid, nid, ch = _where(config, chapter)
    vid = _version(ch)
    user = {"id": uid}

    def quote() -> dict:
        q = _op("compose_quote", user, nid, ch["id"], vid, draft)
        return {"amount": q["amount"], "currency": "cny", "detail": {"chars": q["chars"], "draft": draft}}

    card = _card(tool_call_id, "compose", ch, vid, quote())
    outcome = "done"
    if card["amount"] > 0 or _resuming(config, tool_call_id):
        ok, card = _ask(card, quote)
        if not ok:
            return _result("用户取消了，没有合成", card, "rejected")
        outcome = "approved"
    _op("compose_start", user, nid, ch["id"], vid, draft, card["amount"] or None)
    return _result(f"已开始合成「{ch['title']}」，进度在任务卡上", card, outcome,
                   {"kind": "compose", "chapter_id": ch["id"], "version_id": vid})


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
