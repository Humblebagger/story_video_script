"""助手智能体：create_react_agent + pre_model_hook（拼系统提示、裁剪历史、补全被打断的工具调用）。"""
from pathlib import Path
from typing import Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import create_react_agent

from assistant import actions, edits, store
from assistant.tools import TOOLS
from server import novels

ALL_TOOLS = TOOLS + actions.TOOLS + edits.TOOLS
CANCELLED = "用户没有确认，发了新消息；这个操作已取消"

HISTORY = 20                  # 发给模型的最近消息数（存档保留全量）
RECURSION_LIMIT = 37          # 约 12 次工具调用（pre_model_hook 自成一个节点，每轮工具循环占 3 步）
PROMPT = (Path(__file__).resolve().parent.parent / "prompts" / "assistant.md").read_text(encoding="utf-8")
LANG = {"zh": "简体中文", "en": "English"}


def trim(messages: list) -> list:
    """最近 HISTORY 条，并从前面丢到第一条是用户消息为止（不以孤立的工具结果开头）。
    本轮工具调用多到最近 HISTORY 条里没有用户消息时，从本轮的用户消息起整轮保留（否则模型只收到系统提示）。"""
    start = max(0, len(messages) - HISTORY)
    while start < len(messages) and not isinstance(messages[start], HumanMessage):
        start += 1
    if start == len(messages):
        start = next((i for i in range(len(messages) - 1, -1, -1) if isinstance(messages[i], HumanMessage)), 0)
    return list(messages[start:])


def close_dangling(messages: list) -> list:
    """上一轮在工具执行前被停掉时，工具调用后面没有结果：补一条「（已中断）」，只补在发给模型的输入里。"""
    answered = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}
    out = []
    for m in messages:
        out.append(m)
        if isinstance(m, AIMessage):
            for tc in m.tool_calls or []:
                if tc["id"] not in answered:
                    out.append(ToolMessage("（已中断）", tool_call_id=tc["id"], name=tc["name"]))
    return out


def system_text(user_id: str, nid: str, where: dict, lang: str) -> str:
    parts = [PROMPT, "", f"回答语言：{LANG.get(lang, LANG['zh'])}。"]
    try:
        novel = novels.get_novel(user_id, nid)
    except novels.NotFound:
        return "\n".join(parts)
    parts.append(f"当前小说：《{novel['title']}》。")
    ch = next((c for c in novel["chapters"] if c["id"] == where.get("chapter_id")), None)
    if ch:
        parts.append(f"用户正在看：{ch['title']}（编号 {ch['id']}）"
                     + (f"，版本 {where['version_id']}" if where.get("version_id") else "")
                     + (f"，步骤 {where['step']}" if where.get("step") else "") + "。")
    else:
        parts.append("用户正在看：小说概览。")
    return "\n".join(parts)


def _pre_model(state: dict, config: RunnableConfig) -> dict:
    c = config.get("configurable") or {}
    sys_msg = SystemMessage(system_text(c["user_id"], c["novel_id"], c.get("where") or {}, c.get("lang", "zh")))
    return {"llm_input_messages": [sys_msg] + close_dangling(trim(state["messages"]))}


def build_agent(model, checkpointer):
    """一次只调一个工具（parallel_tool_calls=False）：每步最多一个操作，确认卡始终一张一张出、好推理，
    模型也不能在同一步里连发两个花钱的操作。create_react_agent 接受已绑定工具的模型。"""
    return create_react_agent(model.bind_tools(ALL_TOOLS, parallel_tool_calls=False), ALL_TOOLS,
                              pre_model_hook=_pre_model, checkpointer=checkpointer)


def pending(agent, config: dict) -> list:
    """存档里待确认的卡（LangGraph 的中断）。"""
    return list(agent.get_state(config).interrupts)


def cancel_pending(agent, config: dict) -> int:
    """有待确认的卡时用户发了新消息：给每张卡补一条「已取消」的工具结果（不调模型），新消息照常开新的一轮。"""
    its = pending(agent, config)
    if not its:
        return 0
    msgs = [ToolMessage(CANCELLED, tool_call_id=it.value["tool_call_id"], name=it.value["action"],
                        artifact={"card": it.value, "outcome": "rejected", "task": None}) for it in its]
    agent.update_state(config, {"messages": msgs}, as_node="tools")
    return len(msgs)


class NullModel(BaseChatModel):
    """只读历史时占位（读存档不需要模型，也不该因为没配密钥而失败）：不会被调用。"""
    @property
    def _llm_type(self) -> str:
        return "null"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, *a, **k):
        raise RuntimeError("NullModel 不应被调用")


def run_config(user_id: str, nid: str, where: Optional[dict], lang: str, callbacks: Optional[list] = None,
               resume_tool_call: Optional[str] = None) -> dict:
    cfg = {"configurable": {**store.THREAD, "user_id": user_id, "novel_id": nid,
                            "where": dict(where or {}), "lang": lang, "resume_tool_call": resume_tool_call},
           "recursion_limit": RECURSION_LIMIT}
    if callbacks:
        cfg["callbacks"] = callbacks
    return cfg
