#!/usr/bin/env python3
"""chat.py 的单元测试（不调真实 API）。用法: python3 tests/pipeline/test_chat.py"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from langchain_core.messages import AIMessage, HumanMessage
from fakes import FakeChat
from pipeline.chat import ChatInvoker, LLMError, UsageCallback, extract_json
from pipeline.config import Settings


def main() -> int:
    # 1. extract_json 容错：代码块围栏、前后噪声
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('废话{"a": 2}废话') == {"a": 2}
    try:
        extract_json("没有对象")
        raise AssertionError("找不到 JSON 应抛 ValueError")
    except ValueError:
        pass
    print("chat: extract_json 容错提取 ✓")

    # 2. UsageCallback 的账本结构必须和改造前 LLMClient.usage_totals() 同形
    usage = UsageCallback()
    chat = FakeChat(responses=["产出"])
    ChatInvoker(Settings(api_key="k"), chat=chat, usage=usage).invoke(
        [HumanMessage("输入")])
    assert set(usage.usage_totals()) == {
        "calls", "input", "output", "cache_read", "cache_write"}
    assert usage.usage_totals() == {"calls": 1, "input": 2, "output": 2,
                                    "cache_read": 0, "cache_write": 0}
    print("chat: 用量账本字段与改造前同形 ✓")

    # 3. langchain 的 input_tokens 含缓存，要还原成「未缓存输入」才和 main 的账可比
    cached = AIMessage(content="x", response_metadata={"stop_reason": "end_turn"},
                       usage_metadata={"input_tokens": 1000, "output_tokens": 5,
                                       "total_tokens": 1005,
                                       "input_token_details": {"cache_read": 900,
                                                               "cache_creation": 50}})
    usage2 = UsageCallback()
    ChatInvoker(Settings(api_key="k"), chat=FakeChat(responses=[cached]),
                usage=usage2).invoke([HumanMessage("x")])
    assert usage2.usage_totals() == {"calls": 1, "input": 50, "output": 5,
                                     "cache_read": 900, "cache_write": 50}, \
        "input 必须是扣掉 cache_read/cache_creation 后的未缓存输入"
    print("chat: input_tokens 还原成未缓存输入，账与 main 可比 ✓")

    # 4. 自定义端点转接到 anthropic_api_url（字段名不是 base_url）
    from pipeline.chat import build_chat_model
    m = build_chat_model(Settings(api_key="k", base_url="https://gw.invalid"))
    assert m.anthropic_api_url == "https://gw.invalid"
    print("chat: ANTHROPIC_BASE_URL → anthropic_api_url ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
