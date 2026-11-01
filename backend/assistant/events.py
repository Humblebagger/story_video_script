"""LangGraph 流 → SSE 事件；存档 → 界面历史。

事件（spec §5）：token {text} / tool_start {id,name,args} / tool_end {id,ok,summary} / goto {chapter_id,step} /
done {} / error {message}。文字只从 messages 流取（逐字），工具起止从 updates 流取，避免重复。
"""
import json
from typing import Iterator, Optional

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langgraph.errors import GraphRecursionError

TOO_MANY = "步骤太多，先停在这里。可以换个更具体的问法再问我。"


def text_of(msg) -> str:
    c = msg.content
    if isinstance(c, str):
        return c
    return "".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")


def _hide(text: str, hide: Optional[str]) -> str:
    return text.replace(hide, "…") if hide else text


def stream(agent, config: dict, text: str, hide: Optional[str] = None) -> Iterator[dict]:
    """跑一轮，逐个产出事件。客户端断开时调用方停止迭代即可（生成器被关闭，LangGraph 随之停）。"""
    try:
        for mode, chunk in agent.stream({"messages": [HumanMessage(text)]}, config,
                                        stream_mode=["messages", "updates"]):
            if mode == "messages":
                msg, meta = chunk
                if meta.get("langgraph_node") == "agent" and isinstance(msg, (AIMessage, AIMessageChunk)):
                    t = text_of(msg)
                    if t:
                        yield {"event": "token", "data": {"text": t}}
                continue
            for node, update in chunk.items():
                for m in (update or {}).get("messages") or []:
                    if node == "agent" and isinstance(m, AIMessage):
                        for tc in m.tool_calls or []:
                            yield {"event": "tool_start", "data": {"id": tc["id"], "name": tc["name"], "args": tc["args"]}}
                    elif node == "tools" and isinstance(m, ToolMessage):
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


def history(agent, config: dict) -> list:
    """存档 → [{role, text, tools?, goto?}]：一条用户消息之后、下一条用户消息之前的都算一条助手回答。"""
    msgs = agent.get_state(config).values.get("messages") or []
    out: list = []
    cur = None
    for m in msgs:
        if isinstance(m, HumanMessage):
            out.append({"role": "user", "text": text_of(m)})
            cur = None
            continue
        if cur is None:
            cur = {"role": "assistant", "text": "", "tools": [], "goto": []}
            out.append(cur)
        if isinstance(m, AIMessage):
            cur["text"] += text_of(m)
            for tc in m.tool_calls or []:
                cur["tools"].append({"id": tc["id"], "name": tc["name"], "args": tc["args"], "ok": None, "summary": ""})
        elif isinstance(m, ToolMessage):
            for t in cur["tools"]:
                if t["id"] == m.tool_call_id:
                    t["ok"] = m.status != "error"
                    t["summary"] = text_of(m)[:200]
            if m.status != "error" and m.name == "goto" and m.artifact:
                cur["goto"].append(m.artifact)
    return out
