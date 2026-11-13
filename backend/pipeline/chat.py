"""LangChain 聊天模型工厂、用量回调，与模型输出的 JSON 提取。

取代改造前的 llm.py：传输重试交给 Runnable 的 with_retry，用量统计交给
callback handler，但 thinking 降级与截断诊断这两条实测补偿必须自己留着
（见 docs/specs/2026-10-10-langchain-langgraph-refactor-design.md §6）。
模型接口错误一律经 llm_error 映射为带代码的 LLMError（用户文案统一称「AI 服务」）。
"""
import json
import logging
import re
from typing import List, Optional

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.runnables import RunnableLambda

from server.messages import UserError, compact
from .config import Settings

log = logging.getLogger("pipeline.chat")


class LLMError(UserError, RuntimeError):
    """模型服务调用失败（spec 子计划 4 C）。

    str() 是给用户的中文兜底：统一称「AI 服务」，不含模型名、厂商名与接口原文。
    hint 是给开发看的排查细节（环境变量名、状态码、请求 id、脱敏后的原文摘要），只进日志、
    转换调试日志与命令行。needs_ref：原因只在服务器上（请求被拒却说不清为什么），调用方要记参考编号。
    没有代码的 LLMError（测试替身等）行为与改造前一致。"""
    hint: str = ""
    needs_ref: bool = False

    @classmethod
    def coded(cls, code: str, /, *, hint: str = "", needs_ref: bool = False, **params) -> "LLMError":
        e = cls.of(code, **params)
        e.hint, e.needs_ref = hint, needs_ref
        return e


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
        hint = "未安装 langchain-anthropic：pip install -r requirements.txt"
        log.warning("模型服务没有配置：%s", hint)  # i18n: internal
        raise LLMError.coded("llm.not_configured", hint=hint)
    if not settings.api_key:
        hint = "未配置 ANTHROPIC_API_KEY（写入 .env 或环境变量）"
        log.warning("模型服务没有配置：%s", hint)  # i18n: internal
        raise LLMError.coded("llm.not_configured", hint=hint)
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


_MIDSTREAM_TRANSIENT = {"overloaded_error", "api_error", "rate_limit_error"}


class _StreamInterrupted(Exception):
    """流式中途的瞬时 event: error。SDK 以 HTTP 200 的 APIStatusError 抛出，类型上与 401、400 无法区分，
    换成这个类型，with_retry 才能只按类型重试它。original 是原异常，映射时取它。"""

    def __init__(self, original: BaseException) -> None:
        super().__init__(str(original))
        self.original = original


def _midstream_transient(e: BaseException) -> bool:
    import anthropic
    return (isinstance(e, anthropic.APIStatusError) and e.status_code == 200
            and _status_info(e)[1] in _MIDSTREAM_TRANSIENT)


def _transient_errors() -> tuple:
    """可重试的瞬时故障——with_retry 与耗尽后的 LLMError 包装共用这一个来源。

    主清单是 langchain_core 的 Model*Error（is_retryable=True 的四类）：langchain_anthropic 抛出的异常
    同时继承它们，529（AnthropicOverloadedError）属于 ModelAPIError，自然在内。
    SDK 类型留作兜底：流式中途的错误、测试替身直接抛的异常没有经过包装。anthropic 1.13 把 529 单列为
    OverloadedError，它不是 InternalServerError 的子类，必须单列，否则未包装的 529 一次都不重试。
    httpx2 的原生传输异常照旧（Ruling-6 的护栏：anthropic 1.13 起 SDK 跑在 httpx2 上）。
    流式中途的瞬时 event: error 由 _StreamInterrupted 承接。
    """
    import anthropic
    import httpx2
    from langchain_core.exceptions import (ModelAPIError, ModelConnectionError,
                                           ModelRateLimitError, ModelTimeoutError)
    return (ModelRateLimitError, ModelAPIError, ModelConnectionError, ModelTimeoutError,
            anthropic.APIConnectionError, anthropic.InternalServerError,
            anthropic.OverloadedError, anthropic.RateLimitError,
            httpx2.HTTPError, _StreamInterrupted)


# 先按原文特征（只看请求类错误），再按响应体错误类型，最后按 HTTP 状态。流式中途的 event: error
# 由 SDK 以 HTTP 200 的 APIStatusError 抛出，只能靠错误类型，所以类型排在状态之前。
_BY_TYPE = {"authentication_error": "llm.auth", "permission_error": "llm.access_denied",
            "not_found_error": "llm.model_unavailable", "request_too_large": "llm.too_long",
            "rate_limit_error": "llm.busy", "overloaded_error": "llm.busy",
            "api_error": "llm.unavailable", "billing_error": "llm.balance"}
_BY_STATUS = {401: "llm.auth", 402: "llm.balance", 403: "llm.access_denied", 404: "llm.model_unavailable",
              413: "llm.too_long", 429: "llm.busy", 529: "llm.busy"}
_BLOCKED = re.compile(r"(?i)content\s*exists?\s*risk|content[\s_-]*(filter|policy|moderation)|safety|sensitive")
_TOO_LONG = re.compile(r"(?i)context[\s_-]*(length|window)|maximum context|too long|exceeds?.{0,40}tokens?")
# Anthropic 风格网关的余额不足是 400 + invalid_request_error（设计审查 I3）
_BALANCE = re.compile(r"(?i)credit balance|insufficient (balance|credit|funds)|余额不足")
# 输出上限配置错误（max_tokens 超出模型允许值）：是配置问题，不能叫用户「缩短内容」（设计审查 M2）
_MAX_TOKENS = re.compile(r"(?i)max_tokens")


def _status_info(e) -> tuple:
    """(HTTP 状态, 错误类型, 原文, 请求 id)：原文优先取响应体里的 error.message。"""
    body = getattr(e, "body", None)
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, dict):
        etype, raw = str(err.get("type") or ""), str(err.get("message") or "")
    else:
        etype, raw = "", str(getattr(e, "message", "") or e)
    return getattr(e, "status_code", None), etype, raw, getattr(e, "request_id", None)


def _status_code(status, etype: str, raw: str) -> str:
    if status in (400, 413, 422) or etype == "invalid_request_error":
        if _BLOCKED.search(raw):
            return "llm.content_blocked"
        if _BALANCE.search(raw):
            return "llm.balance"
        if _MAX_TOKENS.search(raw):
            return "llm.model_unavailable"
        if _TOO_LONG.search(raw):
            return "llm.too_long"
    if etype in _BY_TYPE:
        return _BY_TYPE[etype]
    if status in _BY_STATUS:
        return _BY_STATUS[status]
    if isinstance(status, int) and status >= 500:
        return "llm.unavailable"
    return "llm.bad_request"


def llm_error(e: BaseException) -> Optional["LLMError"]:
    """模型接口异常 → 带友好代码的 LLMError；不认识的异常返回 None（调用方当意外处理）。
    原文脱敏后写 pipeline.chat 的 WARNING 日志（状态、类型、请求 id），hint 里留一份摘要。"""
    if isinstance(e, LLMError):
        return e
    if isinstance(e, _StreamInterrupted):
        e = e.original
    import anthropic
    import httpx2
    from langchain_core.exceptions import (ContextOverflowError, ModelAPIError, ModelAuthenticationError,
                                           ModelConnectionError, ModelNotFoundError,
                                           ModelPermissionDeniedError, ModelRateLimitError,
                                           ModelTimeoutError)
    from render.providers.base import scrub_secrets   # 放函数里：pipeline 导入时不依赖 render
    status = etype = rid = None
    raw = str(e)
    if isinstance(e, anthropic.APIStatusError):
        status, etype, raw, rid = _status_info(e)
    # 先按 LangChain 的厂商无关分类（langchain_anthropic 抛出的异常同时继承它们，设计审查 M4），
    # 认不出的再按 SDK 的类型、响应体错误类型与状态码细分。注意顺序：超时是连接错误的子类，要先判。
    if isinstance(e, ContextOverflowError):
        code = "llm.too_long"
    elif isinstance(e, ModelAuthenticationError):
        code = "llm.auth"
    elif isinstance(e, ModelPermissionDeniedError):
        code = "llm.access_denied"
    elif isinstance(e, ModelNotFoundError):
        code = "llm.model_unavailable"
    elif isinstance(e, ModelRateLimitError):
        code = "llm.busy"
    elif isinstance(e, (ModelTimeoutError, anthropic.APITimeoutError, httpx2.TimeoutException)):
        code = "llm.timeout"
    elif isinstance(e, (ModelConnectionError, anthropic.APIConnectionError, httpx2.HTTPError)):
        code = "llm.connect_failed"
    elif isinstance(e, anthropic.APIStatusError):
        # ModelInvalidRequestError（400 的余额、审核、内容太长要看原文）与 ModelAPIError（529 与 5xx 要分开）
        # 都需要细分，交给状态与原文判定
        code = _status_code(status, etype, raw)
    elif isinstance(e, ModelAPIError):
        code = "llm.unavailable"     # 厂商无关的 5xx 类错误（没有 SDK 状态可细分）
    else:
        return None
    # 状态、类型、请求 id、原文先拼成完整文本再整体脱敏、再截断：类型与请求 id 也来自对端，不能漏过脱敏
    detail = scrub_secrets(f"status={status or '-'} type={etype or '-'} request_id={rid or '-'}：{raw}")
    log.warning("模型服务错误 code=%s %s", code, detail[:600])  # i18n: internal
    return LLMError.coded(code, needs_ref=(code == "llm.bad_request"),
                          hint=f"{type(e).__name__} {detail[:400]}")


class ChatInvoker:
    """模型调用的唯一入口：组合 bind_tools / with_retry，并承接 thinking 降级。

    Runnable 的组合顺序有讲究：必须先 bind_tools 再 with_retry——反过来的话
    with_retry 返回的 RunnableRetry 上没有 bind_tools。
    """

    def __init__(self, settings: Settings, *, model: Optional[str] = None,
                 chat=None, usage: Optional[UsageCallback] = None, log=print) -> None:
        self._settings = settings
        self._model_name = model
        self._log = log
        self.usage = usage or UsageCallback()
        self._model = chat if chat is not None else build_chat_model(
            settings, model=model)
        self._injected = chat is not None
        self._no_thinking = None     # 去掉 thinking 的备用模型，懒构造
        self._thinking_rejected = False

    def usage_totals(self) -> dict:
        return self.usage.usage_totals()

    def _runnable(self, model, tools, max_tokens=None):
        runnable = model.bind_tools(tools, parallel_tool_calls=False) if tools else model
        if max_tokens:
            # 推理块的预算也算在 max_tokens 里，开着 thinking 时要把它加回去，
            # 否则 budget_tokens >= max_tokens 会被服务端直接 400
            thinking = (None if self._thinking_rejected
                        else _thinking_param(self._settings.thinking))
            budget = (thinking or {}).get("budget_tokens", 0)
            runnable = runnable.bind(max_tokens=max_tokens + budget)

        def call(messages, config):
            try:
                return runnable.invoke(messages, config)
            except Exception as e:
                if _midstream_transient(e):
                    raise _StreamInterrupted(e) from e
                raise

        # 中途出错时这一次的输出 token 已经花了（用量回调收不到 on_llm_end，不计入账本），
        # 但转换按批串行，这一批失败就是整个版本失败，重放一次远比整章重转便宜。次数与连接类故障共用 transport_retries。
        return RunnableLambda(call, name="chat_call").with_retry(
            retry_if_exception_type=_transient_errors(),
            stop_after_attempt=self._settings.transport_retries + 1,
            wait_exponential_jitter=True,
        )

    def invoke(self, messages, tools=None, max_tokens=None):
        """调模型，返回 AIMessage。瞬时传输故障由 with_retry 指数退避重试；
        其余接口错误映射为带代码的 LLMError（spec 子计划 4 C），原文只进日志。

        max_tokens 覆盖本次调用的输出上限（缺省用 settings.max_tokens）。
        """
        try:
            return self._invoke_once(messages, tools, max_tokens)
        except LLMError:
            raise
        except Exception as e:
            mapped = llm_error(e)
            if mapped is None:
                raise
            raise mapped from e

    def _invoke_once(self, messages, tools=None, max_tokens=None):
        import anthropic
        config = {"callbacks": [self.usage]}
        model = self._no_thinking if (self._thinking_rejected
                                      and self._no_thinking is not None) else self._model
        try:
            return self._invoke_wrapped(model, tools, messages, config, max_tokens)
        except anthropic.BadRequestError as e:
            if self._thinking_rejected or "thinking" not in str(e).lower() \
                    or _thinking_param(self._settings.thinking) is None:
                raise
            # 网关不认这个参数：退回默认行为，但要说一声——推理块会重新开始烧预算
            self._log(f"服务端不接受 thinking 参数（{str(e)[:120]}），"
                      "改用模型默认行为重试")
            self._no_thinking = self._model if self._injected else build_chat_model(
                replace_thinking(self._settings), model=self._model_name)
            self._thinking_rejected = True
            return self._invoke_wrapped(self._no_thinking, tools, messages, config,
                                       max_tokens)

    def _invoke_wrapped(self, model, tools, messages, config, max_tokens=None):
        """with_retry 耗尽后把原始传输异常转成 LLMError，让 CLI 打一行干净的失败。"""
        try:
            return self._runnable(model, tools, max_tokens).invoke(messages,
                                                                   config=config)
        except _transient_errors() as e:
            inner = llm_error(e) or LLMError.coded("llm.unavailable", hint=type(e).__name__)
            # _StreamInterrupted 在 llm_error 里取 original 再映射
            raise LLMError.coded("llm.gave_up", hint=inner.hint, retries=self._settings.transport_retries,
                                 cause=compact(inner.as_msg())) from e

    def text(self, msg) -> str:
        """AIMessage → 正文文本。撞 max_tokens 时按原因分别报错。"""
        return message_text(msg, self._settings)


def replace_thinking(settings: Settings) -> Settings:
    """复制一份关掉 thinking 的配置（降级重试用）。"""
    from dataclasses import replace
    return replace(settings, thinking="auto")


def message_text(msg, settings: Settings) -> str:
    """AIMessage → 正文；撞 max_tokens 抛 LLMError。"""
    return check_truncation(msg, settings)


def is_truncated(msg) -> bool:
    return (msg.response_metadata or {}).get("stop_reason") == "max_tokens"


def check_truncation(msg, settings: Settings) -> str:
    """只检查截断，不要求有正文；返回正文（可能为空）。

    修复路径的回复可以只有 tool_call、没有正文，所以不能直接用 message_text 的
    「要正文」语义——但截断诊断必须共用：LangChain 会把被截断的流式工具参数
    用 parse_partial_json 补成合法 tool_call，不查 stop_reason 就会静默应用残缺补丁。
    """
    content = msg.content
    if isinstance(content, str):
        text, thinking_chars = content, 0
    else:
        blocks = [b for b in content if isinstance(b, dict)]
        text = "".join(b.get("text", "") for b in blocks
                       if b.get("type") == "text")
        thinking_chars = sum(len(b.get("thinking", "") or "") for b in blocks
                             if b.get("type") == "thinking")
    if not is_truncated(msg):
        return text
    out_tokens = (msg.usage_metadata or {}).get("output_tokens", 0)
    if not text.strip() and thinking_chars:
        # 这条路径以前会被报成「输出膨胀」，把人引去调小批长——没用，
        # 因为一个字正文都没产出，膨胀的是推理块不是产物
        hint = (f"模型把全部 {out_tokens} 个输出 token 花在推理块上"
                f"（{thinking_chars} 字思考），没产出任何正文：{settings.model} 是推理模型。"
                "把 STORYBOARD_THINKING 设为 disabled 关掉推理块，或换非推理模型；"
                "调小 STORYBOARD_BATCH_CHARS 对这种情况无效。")
        log.warning("模型输出被截断：%s", hint)  # i18n: internal
        raise LLMError.coded("llm.truncated", hint=hint)
    hint = (f"输出被 max_tokens={settings.max_tokens} 截断——"
            "调大 STORYBOARD_MAX_TOKENS 或调小 STORYBOARD_BATCH_CHARS 后重试")
    log.warning("模型输出被截断：%s", hint)  # i18n: internal
    raise LLMError.coded("llm.truncated", hint=hint)


def extract_json(text: str) -> dict:
    """容错提取：剥掉可能的代码块围栏，取首个 '{' 到末个 '}' 之间解析。"""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("输出中找不到 JSON 对象")  # i18n: llm
    return json.loads(t[start:end + 1])
