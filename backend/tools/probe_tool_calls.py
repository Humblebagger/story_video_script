#!/usr/bin/env python3
"""探针：验证当前配置的模型/网关是否支持原生 tool_calls（含流式参数拼接与 ToolMessage 往返）。

会产生真实 API 费用（2 次小调用）。用法: .venv/bin/python tools/probe_tool_calls.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tools import tool

from pipeline.chat import ChatInvoker
from pipeline.config import load_settings


@tool
def validation_list() -> list:
    """列出当前分镜产物的全部校验失败条目。"""
    return [{"code": "shot_missing_asset", "where": "E01S003"}]


@tool
def json_patch(patch: list[dict]) -> str:
    """提交 JSON Patch 修正产物。patch 是操作列表，每项含 op、path、value 三个键。"""
    return f"已应用 {len(patch)} 项"


def report(label, msg) -> bool:
    """打印一次调用的全部元数据；stop_reason 与 usage 缺失返回 False。"""
    print(f"[{label}] response_metadata={msg.response_metadata}")
    print(f"[{label}] usage_metadata={msg.usage_metadata}")
    print(f"[{label}] tool_calls={msg.tool_calls}")
    ok = True
    if not msg.response_metadata.get("stop_reason"):
        print(f"[{label}] 缺 stop_reason")
        ok = False
    usage = msg.usage_metadata
    if not usage or "input_token_details" not in usage:
        print(f"[{label}] usage_metadata 缺失或不含 input_token_details")
        ok = False
    return ok


def main() -> int:
    settings = load_settings()
    print(f"模型 {settings.model}，端点 {'自定义网关' if settings.base_url else '官方端点'}")
    chat = ChatInvoker(settings)
    tools = [validation_list, json_patch]

    messages = [HumanMessage(
        "把 /episodes/0/shots/0/action 的值替换成『老栓点灯』："
        "用 json_patch 工具提交一个 replace 操作。")]
    msg1 = chat.invoke(messages, tools=tools)
    ok = report("call1", msg1)

    call = next((c for c in msg1.tool_calls if c["name"] == "json_patch"), None)
    if call is None:
        print("\n第 1 次没有 json_patch 调用。")
        return 1
    patch = call["args"].get("patch")
    if not (isinstance(patch, list) and patch and all(
            isinstance(p, dict) and {"op", "path", "value"} <= p.keys() for p in patch)):
        print(f"\njson_patch 参数不完整（流式分块拼接可疑）: {patch!r}")
        return 1
    print(f"\njson_patch 参数完整: {patch}")

    messages += [msg1, ToolMessage(content="已应用 1 项", tool_call_id=call["id"])]
    try:
        msg2 = chat.invoke(messages, tools=tools)
    except Exception as e:  # 往返失败也是探针要报告的事实
        print(f"\nToolMessage 往返失败: {type(e).__name__}: {e}")
        return 1
    ok = report("call2", msg2) and ok
    if not ok:
        return 1
    print("\n支持原生 tool_calls（含参数拼接与 ToolMessage 往返）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
