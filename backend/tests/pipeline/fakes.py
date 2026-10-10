"""离线测试用的 BaseChatModel 替身。

取代改造前的 MockLLM / UsageMockLLM：注入点已从鸭子类型 complete(system, messages)
变成 BaseChatModel，替身也必须是真的 BaseChatModel，否则测不到 Runnable 组合
（bind_tools / with_retry / callbacks）这条链路。
"""
from typing import Any, List, Optional

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field


def _chars(messages: List[BaseMessage]) -> int:
    """消息总字符数，当输入 token 的替身。"""
    total = 0
    for m in messages:
        c = m.content
        if isinstance(c, str):
            total += len(c)
        else:
            total += sum(len(b.get("text", "")) for b in c if isinstance(b, dict))
    return total


class FakeChat(BaseChatModel):
    """按顺序弹出 responses 里的预设回复。

    responses 每项可以是：
      - str：包成 stop_reason=end_turn 的 AIMessage，usage 用字符数替身
      - AIMessage：原样返回（修复用例用它带 tool_calls）
      - callable(messages) -> str | AIMessage：需要看输入再决定回什么时用
    """

    responses: List[Any] = Field(default_factory=list)
    requests: List[dict] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "fake-chat"

    def bind_tools(self, tools, **kwargs):
        # 替身不真的解析 schema，只把工具名透到调用记录里供断言
        names = [getattr(t, "name", getattr(t, "__name__", str(t))) for t in tools]
        return self.bind(tool_names=names, **kwargs)

    def _generate(self, messages: List[BaseMessage],
                  stop: Optional[List[str]] = None,
                  run_manager: Optional[CallbackManagerForLLMRun] = None,
                  **kwargs: Any) -> ChatResult:
        self.requests.append({"messages": list(messages), "kwargs": dict(kwargs)})
        if not self.responses:
            raise AssertionError("FakeChat 的预设回复已用尽，说明实际调用次数比预期多")
        item = self.responses.pop(0)
        if callable(item) and not isinstance(item, BaseMessage):
            item = item(messages)
        if isinstance(item, str):
            item = AIMessage(content=item,
                             response_metadata={"stop_reason": "end_turn"})
        if item.usage_metadata is None:
            text = item.content if isinstance(item.content, str) else ""
            inp = _chars(messages)
            item.usage_metadata = {
                "input_tokens": inp, "output_tokens": len(text),
                "total_tokens": inp + len(text),
                "input_token_details": {"cache_read": 0, "cache_creation": 0},
            }
        return ChatResult(generations=[ChatGeneration(message=item)])
