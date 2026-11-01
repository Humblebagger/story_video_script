"""按脚本逐条回复的假聊天模型（实施裁定 2）：驱动 create_react_agent，不调真实模型。"""
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class ScriptedChat(BaseChatModel):
    script: list
    seen: list = []          # 每次调用收到的消息列表（含系统提示）

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(list(messages))
        msg = self.script.pop(0) if self.script else AIMessage(content="（脚本已用完）")
        return ChatResult(generations=[ChatGeneration(message=msg)])


def call(name: str, args: dict, id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": id}])
