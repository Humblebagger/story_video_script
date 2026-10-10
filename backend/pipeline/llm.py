"""LLM 客户端（Anthropic Messages API，流式）与模型输出的 JSON 提取。"""
import json
import re
import time
from typing import List

from .config import Settings


class LLMError(RuntimeError):
    pass


def _thinking_param(mode: str):
    """配置值 → Anthropic thinking 参数。auto 表示不发这个参数。"""
    mode = (mode or "disabled").strip().lower()
    if mode in ("auto", "", "default"):
        return None
    if mode.isdigit():
        return {"type": "enabled", "budget_tokens": int(mode)}
    return {"type": "disabled"}


class LLMClient:
    def __init__(self, settings: Settings):
        try:
            import anthropic
        except ImportError:
            raise LLMError("未安装 anthropic SDK：pip install -r requirements.txt")
        if not settings.api_key:
            raise LLMError("未配置 ANTHROPIC_API_KEY（写入 .env 或环境变量）")
        import httpx
        kwargs = {"api_key": settings.api_key}
        if settings.base_url:
            kwargs["base_url"] = settings.base_url
        self._client = anthropic.Anthropic(**kwargs)
        self._settings = settings
        # 逐次调用的用量流水。标定「受限补丁 vs 整份重写」到底省不省 token 时，
        # 只有这份账是实测的；不记就只能靠推断。
        self.calls: List[dict] = []
        self._thinking = _thinking_param(settings.thinking)
        # 有些网关不认 thinking 参数；被拒一次就记下来，之后不再发
        self._thinking_rejected = False
        self._bad_request = anthropic.BadRequestError
        # 瞬时故障：网络中断/服务端掐流（实测 DeepSeek 流式中途断连）、超时、5xx、限流
        self._transient_exc = (httpx.HTTPError,
                               anthropic.APIConnectionError,
                               anthropic.InternalServerError,
                               anthropic.RateLimitError)

    def complete(self, system: str, messages: List[dict]) -> str:
        """system + messages → 模型完整文本输出。瞬时传输故障指数退避重试；
        确定性错误（max_tokens 截断、4xx）不重试直接抛。"""
        s = self._settings
        last_exc = None
        for attempt in range(s.transport_retries + 1):
            if attempt:
                wait = min(2 ** attempt, 30)
                print(f"LLM 传输故障（{last_exc!r}），{wait}s 后重试"
                      f"（{attempt}/{s.transport_retries}）…", flush=True)
                time.sleep(wait)
            try:
                return self._stream_once(system, messages)
            except self._transient_exc as e:
                last_exc = e
        raise LLMError(f"LLM 传输重试 {s.transport_retries} 次后仍失败：{last_exc!r}")

    def _stream_once(self, system: str, messages: List[dict]) -> str:
        """单次流式调用。长输出走流式，系统提示词打缓存标记。"""
        s = self._settings
        kwargs = {
            "model": s.model,
            "max_tokens": s.max_tokens,
            "temperature": s.temperature,
            "system": [{"type": "text", "text": system,
                        "cache_control": {"type": "ephemeral"}}],
            "messages": messages,
        }
        if self._thinking and not self._thinking_rejected:
            kwargs["thinking"] = self._thinking
        try:
            parts, final = self._collect(kwargs)
        except self._bad_request as e:
            if "thinking" not in str(e).lower() or "thinking" not in kwargs:
                raise
            # 网关不认这个参数：退回默认行为，但要说一声——推理块会重新开始烧预算
            self._thinking_rejected = True
            kwargs.pop("thinking")
            print(f"服务端不接受 thinking 参数（{str(e)[:120]}），"
                  "改用模型默认行为重试", flush=True)
            parts, final = self._collect(kwargs)
        usage = getattr(final, "usage", None)
        self.calls.append({
            "input": int(getattr(usage, "input_tokens", 0) or 0),
            "output": int(getattr(usage, "output_tokens", 0) or 0),
            "cache_read": int(getattr(usage, "cache_read_input_tokens", 0) or 0),
            "cache_write": int(getattr(usage, "cache_creation_input_tokens", 0) or 0),
        })
        text = "".join(parts)
        if final.stop_reason == "max_tokens":
            thinking_chars = sum(len(getattr(b, "thinking", "") or "")
                                 for b in (final.content or []))
            if not text.strip() and thinking_chars:
                # 这条路径以前会被报成「输出膨胀」，把人引去调小批长——没用，
                # 因为一个字正文都没产出，膨胀的是推理块不是产物
                raise LLMError(
                    f"模型把全部 {self.calls[-1]['output']} 个输出 token 花在推理块上"
                    f"（{thinking_chars} 字思考），没产出任何正文：{s.model} 是推理模型。"
                    "把 STORYBOARD_THINKING 设为 disabled 关掉推理块，或换非推理模型；"
                    "调小 STORYBOARD_BATCH_CHARS 对这种情况无效。")
            raise LLMError(
                f"输出被 max_tokens={s.max_tokens} 截断——"
                "调大 STORYBOARD_MAX_TOKENS 或调小 STORYBOARD_BATCH_CHARS 后重试")
        return text

    def _collect(self, kwargs: dict):
        with self._client.messages.stream(**kwargs) as stream:
            parts = list(stream.text_stream)
            final = stream.get_final_message()
        return parts, final

    def usage_totals(self) -> dict:
        """累计用量快照。转换器按前后差值把 token 归到具体那一次尝试上。"""
        total = {"calls": len(self.calls), "input": 0, "output": 0,
                 "cache_read": 0, "cache_write": 0}
        for record in self.calls:
            for key in ("input", "output", "cache_read", "cache_write"):
                total[key] += record[key]
        return total


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
