"""LangChain 聊天模型工厂、用量回调，与模型输出的 JSON 提取。

取代改造前的 llm.py：传输重试交给 Runnable 的 with_retry，用量统计交给
callback handler，但 thinking 降级与截断诊断这两条实测补偿必须自己留着
（见 docs/specs/2026-10-10-langchain-langgraph-refactor-design.md §6）。
"""
import json
import re
from typing import Any, List, Optional

from langchain_core.callbacks import BaseCallbackHandler

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


class UsageCallback(BaseCallbackHandler):
    """逐次调用的用量流水。

    字段与改造前 LLMClient.usage_totals() 逐字同形——manifest.sum_usage 和前端
    消费方都读这个结构，改了形状等于破坏对外产物。
    """

    def __init__(self) -> None:
        self.calls: List[dict] = []

    def on_llm_end(self, response, **kwargs) -> None:
        for gen_list in response.generations:
            for gen in gen_list:
                usage = getattr(getattr(gen, "message", None),
                                "usage_metadata", None) or {}
                details = usage.get("input_token_details") or {}
                cache_read = int(details.get("cache_read") or 0)
                cache_write = int(details.get("cache_creation") or 0)
                # langchain 的 input_tokens 是「所有输入类型之和」（含缓存读写），
                # 而改造前记的是 Anthropic 原始 input_tokens（不含缓存）。
                # 不扣回去，manifest 里的 input 会凭空膨胀，和 main 分支的账没法比。
                self.calls.append({
                    "input": max(0, int(usage.get("input_tokens") or 0)
                                 - cache_read - cache_write),
                    "output": int(usage.get("output_tokens") or 0),
                    "cache_read": cache_read,
                    "cache_write": cache_write,
                })

    def usage_totals(self) -> dict:
        """累计用量快照。图按节点前后差值把 token 归到具体那一次尝试上。"""
        total = {"calls": len(self.calls), "input": 0, "output": 0,
                 "cache_read": 0, "cache_write": 0}
        for record in self.calls:
            for key in ("input", "output", "cache_read", "cache_write"):
                total[key] += record[key]
        return total


def build_chat_model(settings: Settings, *, model: Optional[str] = None):
    """Settings → 配好的 ChatAnthropic。"""
    try:
        from langchain_anthropic import ChatAnthropic
    except ImportError:
        raise LLMError("未安装 langchain-anthropic：pip install -r requirements.txt")
    if not settings.api_key:
        raise LLMError("未配置 ANTHROPIC_API_KEY（写入 .env 或环境变量）")
    kwargs: dict = {
        "model": model or settings.model,
        "max_tokens": settings.max_tokens,
        "temperature": settings.temperature,
        "api_key": settings.api_key,
        # 重试统一交给 with_retry，SDK 自己再退避一层会让等待时间翻倍且不可观测
        "max_retries": 0,
        # 改造前刻意走流式：22KB 提示词 + 最多 32000 输出 token，单次阻塞请求
        # 在网关上有超时风险。stream_usage 保证流式聚合后仍拿得到 usage。
        "streaming": True,
        "stream_usage": True,
    }
    if settings.base_url:
        # 字段名是 anthropic_api_url，不是 base_url（环境变量仍沿用 ANTHROPIC_BASE_URL）
        kwargs["anthropic_api_url"] = settings.base_url
    thinking = _thinking_param(settings.thinking)
    if thinking:
        kwargs["thinking"] = thinking
    return ChatAnthropic(**kwargs)


class ChatInvoker:
    """模型调用的唯一入口：组合 bind_tools / with_retry，并承接 thinking 降级。

    Runnable 的组合顺序有讲究：必须先 bind_tools 再 with_retry——反过来的话
    with_retry 返回的 RunnableRetry 上没有 bind_tools。
    """

    def __init__(self, settings: Settings, *, model: Optional[str] = None,
                 chat=None, usage: Optional[UsageCallback] = None, log=print) -> None:
        self._settings = settings
        self._log = log
        self.usage = usage or UsageCallback()
        self._model = chat if chat is not None else build_chat_model(
            settings, model=model)
        self._injected = chat is not None
        self._no_thinking = None     # 去掉 thinking 的备用模型，懒构造
        self._thinking_rejected = False

    def usage_totals(self) -> dict:
        return self.usage.usage_totals()

    def _runnable(self, model, tools):
        import anthropic
        import httpx2
        runnable = model.bind_tools(tools) if tools else model
        return runnable.with_retry(
            # anthropic 1.13 起 SDK 跑在 httpx2 上；httpx(0.28) 只是 langchain-core
            # 传递带入的，本调用路径永不抛它的异常。写错这一行，传输重试会静默失效，
            # 而它正是为实测到的网关流式中途断连而建。
            # APITimeoutError 是 APIConnectionError 的子类，无需单列。
            retry_if_exception_type=(anthropic.APIConnectionError,
                                     anthropic.InternalServerError,
                                     anthropic.RateLimitError,
                                     httpx2.HTTPError),
            stop_after_attempt=self._settings.transport_retries + 1,
            wait_exponential_jitter=True,
        )

    def invoke(self, messages, tools=None):
        """调模型，返回 AIMessage。瞬时传输故障由 with_retry 指数退避重试。"""
        import anthropic
        config = {"callbacks": [self.usage]}
        model = self._no_thinking if (self._thinking_rejected
                                      and self._no_thinking is not None) else self._model
        try:
            return self._runnable(model, tools).invoke(messages, config=config)
        except anthropic.BadRequestError as e:
            if self._thinking_rejected or "thinking" not in str(e).lower() \
                    or _thinking_param(self._settings.thinking) is None:
                raise
            # 网关不认这个参数：退回默认行为，但要说一声——推理块会重新开始烧预算
            self._log(f"服务端不接受 thinking 参数（{str(e)[:120]}），"
                      "改用模型默认行为重试")
            self._no_thinking = self._model if self._injected else build_chat_model(
                replace_thinking(self._settings))
            self._thinking_rejected = True
            return self._runnable(self._no_thinking, tools).invoke(
                messages, config=config)

    def text(self, msg) -> str:
        """AIMessage → 正文文本。撞 max_tokens 时按原因分别报错。"""
        return message_text(msg, self._settings)


def replace_thinking(settings: Settings) -> Settings:
    """复制一份关掉 thinking 的配置（降级重试用）。"""
    from dataclasses import replace
    return replace(settings, thinking="auto")


def message_text(msg, settings: Settings) -> str:
    content = msg.content
    if isinstance(content, str):
        text, thinking_chars = content, 0
    else:
        blocks = [b for b in content if isinstance(b, dict)]
        text = "".join(b.get("text", "") for b in blocks
                       if b.get("type") == "text")
        thinking_chars = sum(len(b.get("thinking", "") or "") for b in blocks
                             if b.get("type") == "thinking")
    if (msg.response_metadata or {}).get("stop_reason") != "max_tokens":
        return text
    out_tokens = (msg.usage_metadata or {}).get("output_tokens", 0)
    if not text.strip() and thinking_chars:
        # 这条路径以前会被报成「输出膨胀」，把人引去调小批长——没用，
        # 因为一个字正文都没产出，膨胀的是推理块不是产物
        raise LLMError(
            f"模型把全部 {out_tokens} 个输出 token 花在推理块上"
            f"（{thinking_chars} 字思考），没产出任何正文：{settings.model} 是推理模型。"
            "把 STORYBOARD_THINKING 设为 disabled 关掉推理块，或换非推理模型；"
            "调小 STORYBOARD_BATCH_CHARS 对这种情况无效。")
    raise LLMError(
        f"输出被 max_tokens={settings.max_tokens} 截断——"
        "调大 STORYBOARD_MAX_TOKENS 或调小 STORYBOARD_BATCH_CHARS 后重试")


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
