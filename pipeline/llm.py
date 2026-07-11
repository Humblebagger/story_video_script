"""LLM 客户端（Anthropic Messages API，流式）与模型输出的 JSON 提取。"""
import json
import re
from typing import List

from .config import Settings


class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(self, settings: Settings):
        try:
            import anthropic
        except ImportError:
            raise LLMError("未安装 anthropic SDK：pip install -r requirements.txt")
        if not settings.api_key:
            raise LLMError("未配置 ANTHROPIC_API_KEY（写入 .env 或环境变量）")
        kwargs = {"api_key": settings.api_key}
        if settings.base_url:
            kwargs["base_url"] = settings.base_url
        self._client = anthropic.Anthropic(**kwargs)
        self._settings = settings

    def complete(self, system: str, messages: List[dict]) -> str:
        """system + messages → 模型完整文本输出。长输出走流式，系统提示词打缓存标记。"""
        s = self._settings
        with self._client.messages.stream(
            model=s.model,
            max_tokens=s.max_tokens,
            temperature=s.temperature,
            system=[{"type": "text", "text": system,
                     "cache_control": {"type": "ephemeral"}}],
            messages=messages,
        ) as stream:
            parts = list(stream.text_stream)
            final = stream.get_final_message()
        if final.stop_reason == "max_tokens":
            raise LLMError(
                f"输出被 max_tokens={s.max_tokens} 截断——"
                "调大 STORYBOARD_MAX_TOKENS 或调小 STORYBOARD_BATCH_CHARS 后重试")
        return "".join(parts)


def extract_json(text: str) -> dict:
    """容错提取：剥掉可能的代码块围栏，取首个 '{' 到末个 '}' 之间解析。"""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("输出中找不到 JSON 对象")
    return json.loads(t[start:end + 1])
