#!/usr/bin/env python3
"""FakeChat 测试替身自身的测试。用法: python3 tests/pipeline/test_fakes.py"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from fakes import FakeChat


@tool
def dummy(x: int) -> int:
    """给 bind_tools 用的空工具。"""
    return x


def main() -> int:
    # 1. 字符串排队返回，并记录收到的消息
    chat = FakeChat(responses=["第一条", "第二条"])
    assert chat.invoke([HumanMessage("甲")]).content == "第一条"
    assert chat.invoke([HumanMessage("乙")]).content == "第二条"
    assert [m[0].content for m in (r["messages"] for r in chat.requests)] == ["甲", "乙"]
    print("FakeChat: 排队返回 + 记录请求 ✓")

    # 2. 预设 AIMessage 原样返回（修复用例要带 tool_calls）
    msg = AIMessage(content="", tool_calls=[
        {"name": "validation_list", "args": {}, "id": "call_1"}])
    chat2 = FakeChat(responses=[msg])
    out = chat2.invoke([HumanMessage("丙")])
    assert out.tool_calls[0]["name"] == "validation_list"
    print("FakeChat: 透传带 tool_calls 的 AIMessage ✓")

    # 3. bind_tools 可用，且绑定的工具名进得了调用记录
    chat3 = FakeChat(responses=["好"])
    bound = chat3.bind_tools([dummy])
    assert bound.invoke([HumanMessage("丁")]).content == "好"
    assert chat3.requests[-1]["kwargs"]["tool_names"] == ["dummy"]
    print("FakeChat: bind_tools 记录工具名 ✓")

    # 4. usage_metadata 用字符数替身，且 input_tokens 是含缓存的总和
    chat4 = FakeChat(responses=["输出"])
    u = chat4.invoke([HumanMessage("输入文本")]).usage_metadata
    assert u["output_tokens"] == 2 and u["input_tokens"] == 4
    assert u["input_token_details"] == {"cache_read": 0, "cache_creation": 0}
    print("FakeChat: usage_metadata 形状与 langchain 约定一致 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
