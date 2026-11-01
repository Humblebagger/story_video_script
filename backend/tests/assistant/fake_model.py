"""按脚本逐条回复的假聊天模型（实施裁定 2）：驱动 create_react_agent，不调真实模型。"""
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult


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


class SlowStreamChat(ScriptedChat):
    """逐块流式输出、块与块之间睡 delay 秒：模拟真实模型生成到一半（测试关闭流时事件循环不被卡住）。"""
    chunks: list = ["第一块", "第二块"]
    delay: float = 1.0

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        import time
        self.seen.append(list(messages))
        for i, t in enumerate(self.chunks):
            if i:
                time.sleep(self.delay)
            chunk = ChatGenerationChunk(message=AIMessageChunk(content=t))
            if run_manager:
                run_manager.on_llm_new_token(t, chunk=chunk)
            yield chunk


def call(name: str, args: dict, id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": id}])
