#!/usr/bin/env python3
"""探针：验证当前配置的模型/网关是否支持原生 tool_calls。

会产生真实 API 费用。用法: .venv/bin/python tools/probe_tool_calls.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

from pipeline.chat import ChatInvoker
from pipeline.config import load_settings


@tool
def validation_list() -> list:
    """列出当前分镜产物的全部校验失败条目。"""
    return [{"code": "shot_missing_asset", "where": "E01S003"}]


def main() -> int:
    settings = load_settings()
    print(f"模型 {settings.model}，端点 {settings.base_url or '官方'}")
    chat = ChatInvoker(settings)
    msg = chat.invoke(
        [HumanMessage("先用 validation_list 工具看看有哪些校验失败条目。")],
        tools=[validation_list])
    print(f"response_metadata={msg.response_metadata}")
    print(f"usage_metadata={msg.usage_metadata}")
    print(f"tool_calls={msg.tool_calls}")
    if not msg.tool_calls:
        print("\n不支持原生 tool_calls（或模型没选择调用）。"
              "按 spec §10 的兜底：修复阶段退回自研文本协议，图结构保留。")
        return 1
    print("\n支持原生 tool_calls，可按计划用 bind_tools + ToolNode。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
