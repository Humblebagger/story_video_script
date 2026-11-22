#!/usr/bin/env python3
"""分类器：通过、拦截、非法输出、类别不在表内、模型错误 → 不可用；模型拒答 → unspecified 拦截；
长文本逐段、任一段拦截即止。只用 FakeChat。用法: python3 tests/safety/test_classifier.py"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tests" / "pipeline"))
import _noenv  # noqa: E402,F401  测试不读真实 .env
os.environ["ANTHROPIC_BASE_URL"] = "http://127.0.0.1:9"    # 保险：漏了桩也到不了真实模型服务

from fakes import FakeChat  # noqa: E402
from pipeline.chat import ChatInvoker, LLMError  # noqa: E402
from pipeline.config import Settings  # noqa: E402
from safety import classifier  # noqa: E402


def invoker(*responses):
    fake = FakeChat(responses=list(responses))
    return ChatInvoker(Settings(api_key="k", transport_retries=0), chat=fake), fake


def reply(blocked, category=None, reason=""):
    return json.dumps({"blocked": blocked, "category": category, "reason": reason}, ensure_ascii=False)


def boom(code):
    def raise_it(_messages):
        raise LLMError.coded(code)
    return raise_it


def must_unavailable(*responses, text="正文"):
    chat, _ = invoker(*responses)
    try:
        classifier.classify(text, chat)
    except classifier.Unavailable:
        return
    raise AssertionError("应抛 Unavailable")


def main() -> int:
    # 1. 通过与拦截
    chat, fake = invoker(reply(False))
    v = classifier.classify("他推门。", chat)
    assert v.blocked is False and v.category is None
    sent = fake.requests[0]["messages"]
    assert "他推门。" in sent[-1].content and "minor_sexual" in sent[0].content, "系统提示带尺度表，正文在用户消息里"
    chat, _ = invoker(reply(True, "sexual", "露骨性描写"))
    v = classifier.classify("……", chat)
    assert (v.blocked, v.category, v.reason, v.refused) == (True, "sexual", "露骨性描写", False)
    chat, _ = invoker("```json\n" + reply(True, "drugs", "理" * 200) + "\n```")
    assert len(classifier.classify("……", chat).reason) == 80, "理由截到 80 字，代码块围栏能解析"
    print("1. 通过与拦截 ✓")

    # 2. 不可用：非法 JSON、类别不在表内、拦了却没类别、blocked 不是布尔、超时等模型错误
    must_unavailable("这不是 JSON")
    must_unavailable(reply(True, "violence", "x"))
    must_unavailable(reply(True, None, "x"))
    must_unavailable(reply(True, "unspecified", "x"))
    must_unavailable(json.dumps({"blocked": "yes", "category": None}))
    must_unavailable(json.dumps({"blocked": False, "category": None, "reason": None}))
    must_unavailable(json.dumps({"blocked": False, "category": None}))
    must_unavailable(json.dumps({"blocked": True, "category": "drugs"}))
    must_unavailable(reply(False, "not_valid"))
    must_unavailable(reply(False, "sexual"))
    must_unavailable(json.dumps({"blocked": False, "category": None, "reason": 5}))
    must_unavailable(json.dumps({"blocked": True, "category": "drugs", "reason": ["x"]}))
    must_unavailable(boom("llm.timeout"))
    must_unavailable(boom("llm.unavailable"))
    print("2. 不可用 ✓")

    # 3. 底层模型拒答 → unspecified 拦截
    chat, _ = invoker(boom("llm.content_blocked"))
    v = classifier.classify("……", chat)
    assert (v.blocked, v.category, v.refused) == (True, "unspecified", True)
    print("3. 模型拒答 ✓")

    # 4. 长文本按 6000 字切段逐段调用；任一段拦截即止
    long_text = "\n".join(["甲" * 5000, "乙" * 5000, "丙" * 5000])
    chat, fake = invoker(reply(False), reply(False), reply(False))
    assert classifier.classify(long_text, chat).blocked is False and len(fake.requests) == 3
    chat, fake = invoker(reply(False), reply(True, "extremism", "招募"), reply(False))
    v = classifier.classify(long_text, chat)
    assert v.category == "extremism" and len(fake.requests) == 2, "第二段拦下后不再调第三段"
    chat, fake = invoker()
    assert classifier.classify("   ", chat).blocked is False and fake.requests == [], "空文本不调模型"
    print("4. 长文本切段 ✓")

    # 5. make_chat：关 thinking、温度 0、输出上限 200、不重试、15 秒超时、非流式
    seen = {}
    real = classifier.ChatInvoker
    classifier.ChatInvoker = lambda settings, **kw: seen.update(settings=settings, **kw) or "invoker"
    real_ls = classifier.load_settings
    classifier.load_settings = lambda: Settings(api_key="k", thinking="8000", temperature=0.7, transport_retries=3)
    try:
        assert classifier.make_chat() == "invoker"
    finally:
        classifier.ChatInvoker, classifier.load_settings = real, real_ls
    s = seen["settings"]
    assert (s.thinking, s.temperature, s.max_tokens, s.transport_retries) == ("disabled", 0.0, 200, 0)
    assert seen["timeout"] == 15 and seen["streaming"] is False and seen["compat_retry"] is False
    print("5. 专用调用配置 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
