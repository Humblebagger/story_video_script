#!/usr/bin/env python3
"""chat.py 的单元测试（不调真实 API）。用法: python3 tests/pipeline/test_chat.py"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

os.environ["ANTHROPIC_BASE_URL"] = "http://127.0.0.1:9"    # 保险：漏了桩也到不了真实模型服务
SECRET = "sk-test-llm-secret-0123456789"
os.environ["ANTHROPIC_API_KEY"] = SECRET                   # 只为验证脱敏；所有调用都走 FakeChat
import pipeline.config as _pc
_pc._load_dotenv = lambda *_a, **_k: None

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

    # 5. 网关不认 thinking 参数：摘掉重试一次，别让兼容性问题变成硬失败
    import anthropic
    import httpx2

    def picky(messages):
        raise anthropic.BadRequestError(
            "thinking: unsupported parameter",
            response=httpx2.Response(400, request=httpx2.Request("POST", "http://x")),
            body=None)

    picky_chat = FakeChat(responses=[picky, "好"])
    logs = []
    inv = ChatInvoker(Settings(api_key="k", thinking="2000"), chat=picky_chat,
                      log=logs.append)
    assert inv.invoke([HumanMessage("x")]).content == "好"
    assert inv._thinking_rejected, "被拒过一次就别再发了"
    assert any("不接受 thinking" in line for line in logs), \
        "降级要说一声：推理块会重新开始烧预算"
    print("chat: 网关不认 thinking 则摘掉重试 ✓")

    # 6. 非 thinking 的 400 不许吞掉
    calls6 = []

    def other_400(messages):
        calls6.append(1)
        raise anthropic.BadRequestError(
            "credit balance too low",
            response=httpx2.Response(400, request=httpx2.Request("POST", "http://x")),
            body=None)

    inv6 = ChatInvoker(Settings(api_key="k", thinking="2000"),
                       chat=FakeChat(responses=[other_400]), log=logs.append)
    try:
        inv6.invoke([HumanMessage("x")])
        raise AssertionError("与 thinking 无关的 400 应抛 LLMError")
    except LLMError as e:
        assert e.code == "llm.balance" and isinstance(e.__cause__, anthropic.BadRequestError)
    assert not inv6._thinking_rejected and len(calls6) == 1, "不触发降级、不重试"
    print("chat: 无关的 400 不被降级逻辑吞掉，映射为友好代码 ✓")

    # 7. 预算全烧在推理块上：要点名是推理模型，并否掉「调小批长」这条错误建议
    burnt = AIMessage(
        content=[{"type": "thinking", "thinking": "嗯" * 3000}],
        response_metadata={"stop_reason": "max_tokens"},
        usage_metadata={"input_tokens": 100, "output_tokens": 60664,
                        "total_tokens": 60764,
                        "input_token_details": {"cache_read": 0,
                                                "cache_creation": 0}})
    inv2 = ChatInvoker(Settings(api_key="k", model="deepseek-v4-flash"),
                       chat=FakeChat(responses=[burnt]))
    msg2 = inv2.invoke([HumanMessage("x")])
    try:
        inv2.text(msg2)
        raise AssertionError("推理块烧光预算应抛 LLMError")
    except LLMError as e:
        assert e.code == "llm.truncated" and "deepseek" not in str(e).lower()
        assert "推理块" in e.hint and "60664" in e.hint and "STORYBOARD_THINKING" in e.hint
        assert "调小 STORYBOARD_BATCH_CHARS 对这种情况无效" in e.hint
    # 烧掉的 token 也要计入用量账
    assert inv2.usage_totals()["output"] == 60664
    print("chat: 推理块烧光预算要点名，并否掉错误建议 ✓")

    # 8. 正文出来了才是普通截断，报的是另一套话
    cut = AIMessage(content=[{"type": "text", "text": "{"}],
                    response_metadata={"stop_reason": "max_tokens"},
                    usage_metadata={"input_tokens": 10, "output_tokens": 1,
                                    "total_tokens": 11,
                                    "input_token_details": {"cache_read": 0,
                                                            "cache_creation": 0}})
    inv3 = ChatInvoker(Settings(api_key="k"), chat=FakeChat(responses=[cut]))
    try:
        inv3.text(inv3.invoke([HumanMessage("x")]))
        raise AssertionError("普通截断也要报错")
    except LLMError as e:
        assert e.code == "llm.truncated" and "推理" not in e.hint and "STORYBOARD_MAX_TOKENS" in e.hint \
            and "STORYBOARD" not in str(e)
    print("chat: 普通截断报另一套话 ✓")

    # 9. 正常结束时原样返回正文
    inv4 = ChatInvoker(Settings(api_key="k"), chat=FakeChat(responses=["正文"]))
    assert inv4.text(inv4.invoke([HumanMessage("x")])) == "正文"
    print("chat: 正常结束原样返回正文 ✓")

    # 10. 传输重试：瞬时断连自动重试，第 3 次成功（迁自 test_offline 第 10 节）
    attempts = []

    def flaky(messages):
        attempts.append(1)
        if len(attempts) < 3:
            raise anthropic.APIConnectionError(
                request=httpx2.Request("POST", "http://x"))
        return "ok"

    inv_r = ChatInvoker(Settings(api_key="k", transport_retries=2),
                        chat=FakeChat(responses=[flaky, flaky, flaky]))
    assert inv_r.invoke([HumanMessage("x")]).content == "ok"
    assert len(attempts) == 3, "断连 2 次后第 3 次应成功"
    print("chat: 传输重试——断连 2 次后第 3 次成功 ✓")

    # 11. thinking 配置三档映射（迁自 test_offline 第 22 节开头）
    from pipeline.chat import _thinking_param
    assert _thinking_param("disabled") == {"type": "disabled"}
    assert _thinking_param("auto") is None, "auto 表示不发这个参数（老网关兼容）"
    assert _thinking_param("1024") == {"type": "enabled", "budget_tokens": 1024}
    print("chat: thinking 配置三档映射 ✓")

    # 12. 传输重试也覆盖 httpx2 的原生传输异常（Ruling-6 的护栏）。
    #     复刻改造前第 10 节测的真实故障：网关流式中途掐断连接。
    #     元组里若漏了 httpx2.HTTPError，这一项会直接抛出而不是重试。
    raw_attempts = []

    def peer_closed(messages):
        raw_attempts.append(1)
        if len(raw_attempts) < 3:
            raise httpx2.RemoteProtocolError("peer closed connection")
        return "ok"

    inv_h = ChatInvoker(Settings(api_key="k", transport_retries=2),
                        chat=FakeChat(responses=[peer_closed] * 3))
    assert inv_h.invoke([HumanMessage("x")]).content == "ok"
    assert len(raw_attempts) == 3, "httpx2 传输异常也必须触发重试"
    print("chat: httpx2 原生断连同样重试 ✓")

    # 13. 保持流式（Ruling-7 的护栏）：改造前刻意走流式，长输出单次阻塞请求在网关上会超时
    m2 = build_chat_model(Settings(api_key="k"))
    assert m2.streaming is True and m2.stream_usage is True
    print("chat: 模型保持流式且流式带用量 ✓")
    try:
        build_chat_model(Settings(api_key=""))
        raise AssertionError("没有密钥应抛 LLMError")
    except LLMError as e:
        assert e.code == "llm.not_configured" and "ANTHROPIC_API_KEY" in e.hint and "ANTHROPIC" not in str(e)

    # 14. 传输重试耗尽：改造前抛干净的 LLMError，CLI 的 except LLMError 才会打一行
    #     「转换失败」而不是整屏 traceback。退避打桩成不睡，免得测试白等。
    import tenacity.nap
    real_time = tenacity.nap.time
    sleeps = []

    class _NoSleep:
        @staticmethod
        def sleep(seconds):
            sleeps.append(seconds)

    always_down_calls = []

    def always_down(messages):
        always_down_calls.append(1)
        raise anthropic.APIConnectionError(
            request=httpx2.Request("POST", "http://x"))

    tenacity.nap.time = _NoSleep
    try:
        try:
            ChatInvoker(Settings(api_key="k", transport_retries=2),
                        chat=FakeChat(responses=[always_down] * 3)).invoke(
                [HumanMessage("x")])
            raise AssertionError("重试耗尽应抛 LLMError")
        except LLMError as e:
            assert e.code == "llm.gave_up" and e.params["retries"] == 2
            assert e.params["cause"] == {"code": "llm.connect_failed", "params": {}}
            assert str(e) == "已重试 2 次仍失败：连接 AI 服务失败，请稍后重试；仍失败请联系管理员"
            assert isinstance(e.__cause__, anthropic.APIConnectionError)
    finally:
        tenacity.nap.time = real_time
    assert len(always_down_calls) == 3, "1 次首发 + 2 次重试"
    assert len(sleeps) == 2, "退避已打桩，没有真睡"
    print("chat: 传输重试耗尽转成 LLMError ✓")

    # 15. 确定性错误（LLMError）原样冒出，不被传输重试吞掉或重放
    det_calls = []

    def deterministic(messages):
        det_calls.append(1)
        raise LLMError("确定性错误")

    try:
        ChatInvoker(Settings(api_key="k", transport_retries=2),
                    chat=FakeChat(responses=[deterministic] * 3)).invoke(
            [HumanMessage("x")])
        raise AssertionError("LLMError 应原样冒出")
    except LLMError as e:
        assert str(e) == "确定性错误"
    assert len(det_calls) == 1, "确定性错误不应被重放"
    print("chat: 确定性错误不被重试重放 ✓")

    # 16. thinking 被拒后的回退重建必须保留 model 覆盖（评审 invoker 用的是评审模型）
    import pipeline.chat as chat_mod
    built = []
    real_build = chat_mod.build_chat_model

    def spy_build(settings, *, model=None):
        built.append(model)
        return real_build(settings, model=model)

    chat_mod.build_chat_model = spy_build
    try:
        inv16 = ChatInvoker(Settings(api_key="k", thinking="2000"),
                            model="review-model-x")     # 真实 ChatAnthropic，不联网
        assert inv16._model.model == "review-model-x"
        # 第一次 invoke 被网关拒 thinking；回退模型的调用打桩，不真发请求
        inv16._model = FakeChat(responses=[picky])
        orig_wrapped = inv16._invoke_wrapped
        fallback_models = []

        def fake_wrapped(model, tools, messages, config, max_tokens=None):
            if model is inv16._model:
                return orig_wrapped(model, tools, messages, config)
            fallback_models.append(model)
            return AIMessage(content="ok")

        inv16._invoke_wrapped = fake_wrapped
        inv16._log = lambda _: None
        inv16.invoke([HumanMessage("x")])
    finally:
        chat_mod.build_chat_model = real_build
    assert built == ["review-model-x", "review-model-x"], \
        f"回退重建丢了 model 覆盖：{built}"
    assert fallback_models and fallback_models[0].model == "review-model-x"
    print("chat: thinking 回退保留评审模型覆盖 ✓")

    # 17. 单次调用的输出上限覆盖（修复轮用）：开着 thinking 时要把推理预算加回去，
    #     否则 budget_tokens >= max_tokens 会被服务端 400
    fake17 = FakeChat(responses=["a", "b", "c"])
    inv17 = ChatInvoker(Settings(api_key="k", thinking="disabled"), chat=fake17)
    inv17.invoke([HumanMessage("x")], max_tokens=8000)
    inv17.invoke([HumanMessage("x")])
    assert fake17.requests[0]["kwargs"].get("max_tokens") == 8000
    assert "max_tokens" not in fake17.requests[1]["kwargs"], "不传就不覆盖"
    inv17t = ChatInvoker(Settings(api_key="k", thinking="1024"), chat=fake17)
    inv17t.invoke([HumanMessage("x")], max_tokens=8000)
    assert fake17.requests[2]["kwargs"].get("max_tokens") == 9024
    print("chat: 单次输出上限覆盖，thinking 预算另计 ✓")

    # 18. 模型服务错误映射（spec 子计划 4 C）：代码对；str() 不含模型名、厂商名与原文；日志有脱敏原文与请求 id
    import logging
    from pipeline.chat import llm_error
    req = httpx2.Request("POST", "http://127.0.0.1:9/v1/messages")

    def status_err(cls, status, etype="", text="boom"):
        body = {"type": "error", "error": {"type": etype, "message": text}}
        return cls(f"Error code: {status} - {body}", body=body,
                   response=httpx2.Response(status, request=req, headers={"request-id": "req_42"}))

    class _Grab(logging.Handler):
        def __init__(self):
            super().__init__()
            self.lines = []

        def emit(self, rec):
            self.lines.append(rec.getMessage())

    from langchain_anthropic import chat_models as _lca

    def _lc_wrap(e):
        """照 langchain_anthropic 的包装把 SDK 异常换成 Anthropic*Error（同时继承 LangChain 的 Model*Error）。"""
        cls = {anthropic.BadRequestError: _lca.AnthropicContextOverflowError,
               anthropic.OverloadedError: _lca.AnthropicOverloadedError}[type(e)]
        return cls(message=e.message, response=e.response, body=e.body)

    cases = [
        (status_err(anthropic.AuthenticationError, 401, "authentication_error", f"invalid x-api-key {SECRET}"), "llm.auth"),
        (status_err(anthropic.APIStatusError, 402, "", "Insufficient Balance"), "llm.balance"),
        (status_err(anthropic.PermissionDeniedError, 403, "permission_error"), "llm.access_denied"),
        (status_err(anthropic.NotFoundError, 404, "not_found_error", "Model Not Exist: deepseek-v4-flash"), "llm.model_unavailable"),
        (status_err(anthropic.BadRequestError, 400, "invalid_request_error", "Content Exists Risk"), "llm.content_blocked"),
        (status_err(anthropic.BadRequestError, 400, "invalid_request_error",
                    "This model's maximum context length is 131072 tokens"), "llm.too_long"),
        (status_err(anthropic.RequestTooLargeError, 413, "request_too_large"), "llm.too_long"),
        (status_err(anthropic.BadRequestError, 400, "invalid_request_error", "messages.0: bad role"), "llm.bad_request"),
        (status_err(anthropic.UnprocessableEntityError, 422, "", "Invalid Parameters"), "llm.bad_request"),
        (status_err(anthropic.RateLimitError, 429, "rate_limit_error"), "llm.busy"),
        (status_err(anthropic.OverloadedError, 529, "overloaded_error"), "llm.busy"),
        (status_err(anthropic.InternalServerError, 503, "", "Server Overloaded"), "llm.unavailable"),
        (status_err(anthropic.APIStatusError, 200, "overloaded_error", "Overloaded"), "llm.busy"),   # 流式中途的 event: error
        (anthropic.APITimeoutError(request=req), "llm.timeout"),
        (anthropic.APIConnectionError(request=req), "llm.connect_failed"),
        (httpx2.ReadError("peer closed"), "llm.connect_failed"),
        # 设计审查 I3：Anthropic 风格网关的余额不足是 400 + invalid_request_error
        (status_err(anthropic.BadRequestError, 400, "invalid_request_error",
                    "Your credit balance is too low to access the API"), "llm.balance"),
        # 设计审查 M2：输出上限配置错误不是「内容太长」，是配置有误
        (status_err(anthropic.BadRequestError, 400, "invalid_request_error",
                    "max_tokens: 32000 > 8192, which is the maximum allowed number of output tokens"),
         "llm.model_unavailable"),
        # 设计审查 M3：httpx2 的超时是 HTTPError 子类，要先判超时
        (httpx2.ReadTimeout("read timed out"), "llm.timeout"),
        # 设计审查 M4：langchain_anthropic 包装后的异常按 LangChain 的厂商无关分类先判
        (_lc_wrap(status_err(anthropic.BadRequestError, 400, "invalid_request_error",
                             "prompt is too long: 140000 tokens > 131072 maximum")), "llm.too_long"),
        (_lc_wrap(status_err(anthropic.OverloadedError, 529, "overloaded_error")), "llm.busy"),
    ]
    grab = _Grab()
    logging.getLogger("pipeline.chat").addHandler(grab)
    try:
        for exc, want in cases:
            m = llm_error(exc)
            assert m is not None and m.code == want, (type(exc).__name__, m and m.code, want)
            text = str(m)
            for bad in ("deepseek", "claude", "anthropic", "Content Exists", "Insufficient", SECRET):
                assert bad.lower() not in text.lower(), (want, text)
            assert m.needs_ref is (want == "llm.bad_request"), want
            assert SECRET not in m.hint
    finally:
        logging.getLogger("pipeline.chat").removeHandler(grab)
    dump = "\n".join(grab.lines)
    assert "req_42" in dump and "Content Exists Risk" in dump and SECRET not in dump, "日志留脱敏原文与请求 id"
    assert llm_error(RuntimeError("x")) is None
    same = LLMError("确定性错误")
    assert llm_error(same) is same
    print("chat: 模型服务错误映射表 / 不带模型名与原文 / 日志脱敏 ✓")
    # 19. 非瞬时错误：一次就映射，不重试；529（OverloadedError）按瞬时故障重试
    auth_calls = []

    def auth_fail(messages):
        auth_calls.append(1)
        raise status_err(anthropic.AuthenticationError, 401, "authentication_error", "bad key")

    try:
        ChatInvoker(Settings(api_key="k", transport_retries=2),
                    chat=FakeChat(responses=[auth_fail] * 3)).invoke([HumanMessage("x")])
        raise AssertionError("鉴权失败应抛 LLMError")
    except LLMError as e:
        assert e.code == "llm.auth" and isinstance(e.__cause__, anthropic.AuthenticationError)
    assert len(auth_calls) == 1, "鉴权失败不重试"
    over = []

    def overloaded_once(messages):
        over.append(1)
        if len(over) == 1:
            raise status_err(anthropic.OverloadedError, 529, "overloaded_error", "Overloaded")
        return "正文"

    tenacity.nap.time = _NoSleep
    try:
        inv_o = ChatInvoker(Settings(api_key="k", transport_retries=1),
                            chat=FakeChat(responses=[overloaded_once] * 2))
        assert inv_o.invoke([HumanMessage("x")]).content == "正文" and len(over) == 2, "529 要重试"
    finally:
        tenacity.nap.time = real_time
    print("chat: 非瞬时错误不重试 / 529 重试 ✓")
    # 20. 流式中途的瞬时错误（HTTP 200 + overloaded_error/api_error/rate_limit_error）重试，次数有上限；
    #     中途的非瞬时类型（如 authentication_error）不重试
    def mid(etype):
        return status_err(anthropic.APIStatusError, 200, etype, "stream broke")

    tenacity.nap.time = _NoSleep
    try:
        flaky = []

        def mid_once(messages):
            flaky.append(1)
            if len(flaky) == 1:
                raise mid("overloaded_error")
            return "正文"

        inv_m = ChatInvoker(Settings(api_key="k", transport_retries=2),
                            chat=FakeChat(responses=[mid_once] * 3))
        assert inv_m.invoke([HumanMessage("x")]).content == "正文" and len(flaky) == 2, "中途过载重试一次后成功"

        always = []

        def mid_always(messages):
            always.append(1)
            raise mid("api_error")

        try:
            ChatInvoker(Settings(api_key="k", transport_retries=2),
                        chat=FakeChat(responses=[mid_always] * 10)).invoke([HumanMessage("x")])
            raise AssertionError("一直中途出错应抛 llm.gave_up")
        except LLMError as e:
            assert e.code == "llm.gave_up" and e.params["retries"] == 2
            assert e.params["cause"] == {"code": "llm.unavailable", "params": {}}
        assert len(always) == 3, f"有界：1 次 + 重试 2 次，实际 {len(always)} 次"

        auth_mid = []

        def mid_auth(messages):
            auth_mid.append(1)
            raise mid("authentication_error")

        try:
            ChatInvoker(Settings(api_key="k", transport_retries=2),
                        chat=FakeChat(responses=[mid_auth] * 3)).invoke([HumanMessage("x")])
            raise AssertionError("中途鉴权错误应抛 LLMError")
        except LLMError as e:
            assert e.code == "llm.auth"
        assert len(auth_mid) == 1, "中途的非瞬时类型不重试"
    finally:
        tenacity.nap.time = real_time
    print("chat: 流式中途的瞬时错误有界重试 / 非瞬时不重试 ✓")
    # 21. 评审调用失败：报告里只有友好文案，原文进 pipeline.review 日志
    from pipeline.review import run_review
    bad_review = ChatInvoker(Settings(api_key="k", transport_retries=0),
                             chat=FakeChat(responses=[lambda m: (_ for _ in ()).throw(
                                 status_err(anthropic.AuthenticationError, 401, "authentication_error",
                                            "deepseek key invalid"))]))
    ok, rep, overall = run_review(bad_review, "原文", {"episodes": []}, 3.0)
    assert ok is None and overall is None and rep == "[review] 评审服务不可用：AI 服务鉴权失败，请联系管理员", rep
    assert "deepseek" not in rep and "401" not in rep, rep
    print("chat: 评审失败的报告不带原文 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
