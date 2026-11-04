"""LangGraph 流 → SSE 事件；存档 → 界面历史。

事件（spec §5）：token {text} / tool_start {id,name,args} / tool_end {id,ok,summary} / goto {chapter_id,step} /
confirm {卡, id} / action {tool_call_id, action, outcome, card?, task?, error?} / done {} / error {message}。
操作工具不发 tool_start / tool_end（用卡片表示）。文字只从 messages 流取（逐字），工具起止从 updates 流取，避免重复。
"""
import json
from pathlib import Path
from typing import Iterator, Optional

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langgraph.errors import GraphRecursionError

from assistant.actions import ACTIONS

TOO_MANY = "步骤太多，先停在这里。可以换个更具体的问法再问我。"
INTERRUPTED = "（已中断）"


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


def action_view(m: ToolMessage, hide: Optional[str] = None) -> dict:
    """操作工具的结果 → action 事件 / 历史里的卡。报错（或没有 artifact）算没做成。"""
    if m.status == "error" or not m.artifact:
        return {"tool_call_id": m.tool_call_id, "action": m.name, "outcome": "failed",
                "error": _hide(text_of(m), hide)[:300]}
    a = m.artifact
    return {"tool_call_id": m.tool_call_id, "action": m.name, "outcome": a["outcome"],
            "card": a.get("card"), "task": a.get("task")}


def confirm_view(it) -> dict:
    """待确认的卡：中断的原值加上中断编号（恢复时用它）。"""
    return {**it.value, "id": it.id}


def stream(agent, config: dict, payload, hide: Optional[str] = None) -> Iterator[dict]:
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
                            if tc["name"] not in ACTIONS:
                                yield {"event": "tool_start", "data": {"id": tc["id"], "name": tc["name"], "args": tc["args"]}}
                    elif node == "tools" and isinstance(m, ToolMessage):
                        if m.name in ACTIONS:
                            yield {"event": "action", "data": action_view(m, hide)}
                            continue
                        ok = m.status != "error"
                        yield {"event": "tool_end", "data": {"id": m.tool_call_id, "ok": ok,
                                                             "summary": _hide(text_of(m), hide)[:200]}}
                        if ok and m.name == "goto" and m.artifact:
                            yield {"event": "goto", "data": m.artifact}
    except GraphRecursionError:
        yield {"event": "token", "data": {"text": TOO_MANY}}
    except Exception as e:  # 模型、网关、存档出错：给用户一条报错，不抛到 SSE 外面
        yield {"event": "error", "data": {"message": _hide(f"助手出错：{e}", hide)[:300]}}
        return
    yield {"event": "done", "data": {}}


def sse(ev: dict) -> str:
    return f"event: {ev['event']}\ndata: {json.dumps(ev['data'], ensure_ascii=False)}\n\n"


def history(agent, config: dict, hide: Optional[str] = None) -> list:
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
                if tc["name"] in ACTIONS:
                    it = waiting.get(tc["id"])
                    cur["cards"].append(
                        {"tool_call_id": tc["id"], "action": tc["name"], "outcome": "pending", "card": confirm_view(it)}
                        if it else {"tool_call_id": tc["id"], "action": tc["name"], "outcome": "failed",
                                    "error": INTERRUPTED})
                else:
                    cur["tools"].append({"id": tc["id"], "name": tc["name"], "args": tc["args"], "ok": None, "summary": ""})
        elif isinstance(m, ToolMessage):
            if m.name in ACTIONS:
                view = action_view(m, hide)
                cur["cards"] = [view if c["tool_call_id"] == m.tool_call_id else c for c in cur["cards"]]
                continue
            for t in cur["tools"]:
                if t["id"] == m.tool_call_id:
                    t["ok"] = m.status != "error"
                    t["summary"] = _hide(text_of(m), hide)[:200]
            if m.status != "error" and m.name == "goto" and m.artifact:
                cur["goto"].append(m.artifact)
    for entry in out:
        for t in entry.get("tools") or []:
            if t["ok"] is None:
                t["ok"], t["summary"] = False, INTERRUPTED
    return out
