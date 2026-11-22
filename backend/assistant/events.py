"""LangGraph 流 → SSE 事件；存档 → 界面历史。

事件（spec §5）：token {text} / tool_start {id,name,args} / tool_end {id,ok,summary,msg?} / goto {chapter_id,step} /
confirm {卡, id} / action {tool_call_id, action, outcome, card?, task?, error?, error_msg?}（outcome 在历史里撤销过的修改为 undone）/
notice {code, params, message}（步数上限等不属于回答的提示）/ done {} / error {消息对象：code, params, message, ref?}。
tool_end 失败时带 msg?（工具报错的消息对象）；error / summary 仍是中文兜底。
操作工具不发 tool_start / tool_end（用卡片表示）。文字只从 messages 流取（逐字），工具起止从 updates 流取，避免重复。
"""
import json
from pathlib import Path
from typing import Iterator, Optional

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langgraph.errors import GraphRecursionError

from assistant.actions import ACTIONS
from assistant.edits import EDITS
from pipeline.chat import llm_error
from server import error_refs, public
from server.messages import compact, msg as make_msg   # stream 里的 msg 是消息块，别名免得遮住

CARD_TOOLS = ACTIONS + EDITS    # 出卡片的工具：不发 tool_start / tool_end，历史里进 cards

def text_of(msg) -> str:
    c = msg.content
    if isinstance(c, str):
        return c
    return "".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")


def _hide(text: str, hide: Optional[str]) -> str:
    """隐去服务器目录：原写法与 resolve 后的写法都换掉（macOS 上 /var 与 /private/var 是同一处）。"""
    if not hide:
        return text
    for r in sorted({hide, str(Path(hide).resolve())}, key=len, reverse=True):
        text = text.replace(r, "…")
    return text


def _hide_deep(v, hide: Optional[str]):
    """消息对象里的字符串（含嵌套参数）一律隐去服务器目录。"""
    if isinstance(v, str):
        return _hide(v, hide)
    if isinstance(v, list):
        return [_hide_deep(x, hide) for x in v]
    if isinstance(v, dict):
        return {k: _hide_deep(x, hide) for k, x in v.items()}
    return v


def error_msg(e: BaseException, user_id: Optional[str] = None, where: str = "assistant") -> dict:
    """一轮出错 → error 事件的消息对象（spec 子计划 4 D）：
    模型服务错误按 llm.* 映射；needs_ref 的（llm.bad_request）保留代码并带参考编号（设计审查 I2）；其余带编号的 assistant.crashed。"""
    mapped = llm_error(e)
    if mapped is not None and error_refs.expected(mapped):
        m = mapped.as_msg()
    elif mapped is not None and mapped.code:
        m = error_refs.unexpected(e, mapped.code, user_id=user_id, where=where)
    else:
        m = error_refs.unexpected(e, "assistant.crashed", user_id=user_id, where=where)
    return public.public_msg(m)       # 出口统一：旧码归一、原文打码、保留编号


def _ui(m: dict) -> dict:
    """界面用的消息对象：code、params，加顶层参考编号 ref（不是嵌套原因，不能丢）。"""
    out = compact(m)
    if m.get("ref"):
        out["ref"] = m["ref"]
    return out


def _tool_msg(m: ToolMessage) -> Optional[dict]:
    """失败的工具结果里带的消息对象（ToolError 经 graph._with_artifact 放进 artifact）；旧存档、无代码的报错为 None。"""
    a = m.artifact if m.status == "error" else None
    e = a.get("error") if isinstance(a, dict) else None
    return _ui(e) if isinstance(e, dict) and e.get("code") else None


def _public_tool(m: ToolMessage, hide: Optional[str], failed: Optional[bool] = None) -> tuple:
    """工具结果 → (给界面的中文文字, 消息对象或 None)，一律过普通用户出口（历史与流式共用）：
    失败的：有代码按登记表归一（旧厂商码换成中性码），没有代码的换通用失败文案，保留参考编号；
    film_status 的旧结果：pending[].error 里的厂商词打码。对话正文不经这里。"""
    if m.status == "error" if failed is None else failed:
        a = m.artifact if isinstance(m.artifact, dict) else {}
        raw = a.get("error") if isinstance(a.get("error"), dict) else None      # 无代码但带 ref 的也交给出口（保留合法编号）
        pm = public.public_msg(raw)
        return _hide(pm["message"], hide), _hide_deep(_ui(pm), hide)
    text = text_of(m)
    if m.name == "film_status":
        try:
            d = json.loads(text)
            for row in ((d.get("session") or {}).get("pending") or []):
                if isinstance(row.get("error"), str):
                    row["error"] = public.redact(row["error"])
            text = json.dumps(d, ensure_ascii=False)
        except (ValueError, AttributeError, TypeError):      # 截断得无法解析（tools._dump 的「（已截断）」）：不回退原文
            m = make_msg("assistant.tool.truncated")
            return m["message"], compact(m)
    return _hide(text, hide), None


def tool_end_data(m: ToolMessage, hide: Optional[str]) -> dict:
    """tool_end 事件的数据（流式与历史同一份）。"""
    text, em = _public_tool(m, hide)
    return {"id": m.tool_call_id, "ok": m.status != "error", "summary": text[:200], **({"msg": em} if em else {})}


def _failed(m: dict) -> dict:
    """失败条目：error 留中文兜底（旧前端、给模型的同一句话），error_msg 给界面按语言渲染。"""
    return {"error": m["message"], "error_msg": _ui(m)}


def action_view(m: ToolMessage, hide: Optional[str] = None) -> dict:
    """操作工具的结果 → action 事件 / 历史里的卡。报错（或没有 artifact）算没做成。"""
    if m.status == "error" or not m.artifact:
        text, em = _public_tool(m, hide, True)
        return {"tool_call_id": m.tool_call_id, "action": m.name, "outcome": "failed",
                "error": text[:300], "error_msg": em}
    a = m.artifact
    return {"tool_call_id": m.tool_call_id, "action": m.name, "outcome": a["outcome"],
            "card": a.get("card"), "task": a.get("task")}


def confirm_view(it) -> dict:
    """待确认的卡：中断的原值加上中断编号（恢复时用它）。"""
    return {**it.value, "id": it.id}


def stream(agent, config: dict, payload, hide: Optional[str] = None,
           user_id: Optional[str] = None, where: str = "assistant") -> Iterator[dict]:
    """跑一轮，逐个产出事件。payload 是用户的文字，或恢复用的 Command。客户端断开时调用方停止迭代即可。"""
    inp = {"messages": [HumanMessage(payload)]} if isinstance(payload, str) else payload
    try:
        for mode, chunk in agent.stream(inp, config, stream_mode=["messages", "updates"]):
            if mode == "messages":
                msg, meta = chunk
                if meta.get("langgraph_node") == "agent" and isinstance(msg, (AIMessage, AIMessageChunk)):
                    t = text_of(msg)
                    if t:
                        yield {"event": "token", "data": {"text": t}}
                continue
            for node, update in chunk.items():
                if node == "__interrupt__":
                    for it in update:
                        yield {"event": "confirm", "data": confirm_view(it)}
                    continue
                for m in (update or {}).get("messages") or []:
                    if node == "agent" and isinstance(m, AIMessage):
                        for tc in m.tool_calls or []:
                            if tc["name"] not in CARD_TOOLS:
                                yield {"event": "tool_start", "data": {"id": tc["id"], "name": tc["name"], "args": tc["args"]}}
                    elif node == "tools" and isinstance(m, ToolMessage):
                        if m.name in CARD_TOOLS:
                            yield {"event": "action", "data": action_view(m, hide)}
                            continue
                        ok = m.status != "error"
                        yield {"event": "tool_end", "data": tool_end_data(m, hide)}
                        if ok and m.name == "goto" and m.artifact:
                            yield {"event": "goto", "data": m.artifact}
    except GraphRecursionError:
        yield {"event": "notice", "data": make_msg("assistant.too_many_steps")}
    except Exception as e:  # 模型、网关、存档出错：给用户一条报错，不抛到 SSE 外面
        yield {"event": "error", "data": _hide_deep(error_msg(e, user_id, where), hide)}
        return
    yield {"event": "done", "data": {}}


def sse(ev: dict) -> str:
    return f"event: {ev['event']}\ndata: {json.dumps(ev['data'], ensure_ascii=False)}\n\n"


def history(agent, config: dict, hide: Optional[str] = None, undone: Optional[set] = None) -> list:
    """存档 → [{role, text, tools?, goto?}]：一条用户消息之后、下一条用户消息之前的都算一条助手回答。
    同一回答里几条 AI 消息的文字用空行隔开；没有结果的工具调用（被停掉、步骤超限）标成失败「（已中断）」，
    免得界面上一直转圈。操作工具不进 tools，进 cards：待确认的带中断编号，被停掉没结果的标失败「（已中断）」。"""
    snap = agent.get_state(config)
    msgs = snap.values.get("messages") or []
    waiting = {it.value.get("tool_call_id"): it for it in getattr(snap, "interrupts", ())}
    out: list = []
    cur = None
    for m in msgs:
        if isinstance(m, HumanMessage):
            out.append({"role": "user", "text": text_of(m)})
            cur = None
            continue
        if cur is None:
            cur = {"role": "assistant", "text": "", "tools": [], "goto": [], "cards": []}
            out.append(cur)
        if isinstance(m, AIMessage):
            t = text_of(m)
            if t:
                cur["text"] += ("\n\n" if cur["text"] else "") + t
            for tc in m.tool_calls or []:
                if tc["name"] in CARD_TOOLS:
                    it = waiting.get(tc["id"])
                    cur["cards"].append(
                        {"tool_call_id": tc["id"], "action": tc["name"], "outcome": "pending", "card": confirm_view(it)}
                        if it else {"tool_call_id": tc["id"], "action": tc["name"], "outcome": "failed",
                                    **_failed(make_msg("assistant.interrupted"))})
                else:
                    cur["tools"].append({"id": tc["id"], "name": tc["name"], "args": tc["args"], "ok": None, "summary": ""})
        elif isinstance(m, ToolMessage):
            if m.name in CARD_TOOLS:
                view = action_view(m, hide)
                if undone and view["outcome"] == "approved" and m.tool_call_id in undone:
                    view["outcome"] = "undone"
                cur["cards"] = [view if c["tool_call_id"] == m.tool_call_id else c for c in cur["cards"]]
                continue
            for t in cur["tools"]:
                if t["id"] == m.tool_call_id:
                    d = tool_end_data(m, hide)
                    t["ok"], t["summary"] = d["ok"], d["summary"]
                    if "msg" in d:
                        t["msg"] = d["msg"]
            if m.status != "error" and m.name == "goto" and m.artifact:
                cur["goto"].append(m.artifact)
    for entry in out:
        for t in entry.get("tools") or []:
            if t["ok"] is None:
                m = make_msg("assistant.interrupted")
                t["ok"], t["summary"], t["msg"] = False, m["message"], compact(m)
    return out
