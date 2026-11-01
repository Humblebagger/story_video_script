"""助手智能体：create_react_agent + pre_model_hook（拼系统提示、裁剪历史、补全被打断的工具调用）。"""
from pathlib import Path
from typing import Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import create_react_agent

from assistant import store
from assistant.tools import TOOLS
from server import novels

HISTORY = 20                  # 发给模型的最近消息数（存档保留全量）
RECURSION_LIMIT = 25          # 约 12 次工具调用
PROMPT = (Path(__file__).resolve().parent.parent / "prompts" / "assistant.md").read_text(encoding="utf-8")
LANG = {"zh": "简体中文", "en": "English"}


def trim(messages: list) -> list:
    """最近 HISTORY 条，并从前面丢到第一条是用户消息为止（不以孤立的工具结果开头）。"""
    cut = list(messages[-HISTORY:])
    while cut and not isinstance(cut[0], HumanMessage):
        cut.pop(0)
    return cut


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
    return create_react_agent(model, TOOLS, pre_model_hook=_pre_model, checkpointer=checkpointer)


class NullModel(BaseChatModel):
    """只读历史时占位（读存档不需要模型，也不该因为没配密钥而失败）：不会被调用。"""
    @property
    def _llm_type(self) -> str:
        return "null"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, *a, **k):
        raise RuntimeError("NullModel 不应被调用")


def run_config(user_id: str, nid: str, where: Optional[dict], lang: str, callbacks: Optional[list] = None) -> dict:
    cfg = {"configurable": {**store.THREAD, "user_id": user_id, "novel_id": nid,
                            "where": dict(where or {}), "lang": lang},
           "recursion_limit": RECURSION_LIMIT}
    if callbacks:
        cfg["callbacks"] = callbacks
    return cfg
