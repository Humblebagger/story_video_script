#!/usr/bin/env python3
"""探针：验证当前配置的模型/网关是否支持原生 tool_calls（含流式参数拼接与 ToolMessage 往返）。

会产生真实 API 费用（2 次小调用）。用法: .venv/bin/python tools/probe_tool_calls.py
"""
import json
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
    """列出当前分镜产物的全部校验失败条目，每条含位置、原因与期望值。"""
    return [{"code": "SHOT-ACTION-EMPTY", "path": "/episodes/0/shots/0/action",
             "problem": "镜头动作为空", "expected": "老栓点灯"}]


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


def patch_complete(patch) -> bool:
    return bool(isinstance(patch, list) and patch and all(
        isinstance(p, dict) and {"op", "path", "value"} <= p.keys() for p in patch))


def main() -> int:
    settings = load_settings()
    print(f"模型 {settings.model}，端点 {'自定义网关' if settings.base_url else '官方端点'}")
    chat = ChatInvoker(settings)
    tools = [validation_list, json_patch]
    by_name = {t.name: t for t in tools}

    messages = [HumanMessage(
        "当前分镜产物有校验失败。先查清楚失败条目，再用 JSON Patch 修好它。")]
    ok = True
    for i in range(1, 4):
        label = f"call{i}"
        try:
            msg = chat.invoke(messages, tools=tools)
        except Exception as e:
            print(f"\n[{label}] 调用失败: {type(e).__name__}: {e}")
            return 1
        ok = report(label, msg) and ok
        print(f"[{label}] 选择的工具: {[c['name'] for c in msg.tool_calls]}")
        if not ok:
            return 1
        call = next((c for c in msg.tool_calls if c["name"] == "json_patch"), None)
        if call is not None:
            patch = call["args"].get("patch")
            if not patch_complete(patch):
                print(f"\njson_patch 参数不完整（流式分块拼接可疑）: {patch!r}")
                return 1
            print(f"\njson_patch 参数完整: {patch}")
            print("支持原生 tool_calls（含参数拼接与 ToolMessage 往返）。")
            return 0
        if not msg.tool_calls:
            print("\n模型既没有 tool_calls 也没调 json_patch。")
            return 1
        messages.append(msg)
        for c in msg.tool_calls:
            result = by_name[c["name"]].invoke(c["args"])
            messages.append(ToolMessage(
                content=json.dumps(result, ensure_ascii=False), tool_call_id=c["id"]))
    print("\n3 次调用用完仍未出现 json_patch。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
