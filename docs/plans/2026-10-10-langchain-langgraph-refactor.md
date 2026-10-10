# LangChain / LangGraph 改造实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `langchain` 分支上，把后端 LLM 调用层与单批重试循环改造成 LangChain + LangGraph 实现，确定性审查链路与对外产物结构保持不变。

**Architecture:** `llm.py` 的 `LLMClient` 换成 `chat.py`（`ChatAnthropic` 工厂 + `UsageCallback` + `ChatInvoker` 薄壳）；`convert.py` 的 `_convert_batch` for 循环换成 `graph.py` 的 `StateGraph`（generate → check → plan_repair → repair_agent ⇄ tools → finalize）；`repair.py` 的 `{"tool": ...}` 文本协议换成 `tools.py` 的 6 个 `@tool` + `ToolNode`，工具通过 `InjectedState` 读 doc、通过 `Command` 写回 doc。`verification` / `validate` / `quality` / `splitter` / `source_units` / `manifest` 一行不改。

**Tech Stack:** Python 3.12、`langchain-anthropic>=1.7,<2`、`langgraph>=1.2,<2`、`anthropic>=0.120,<2`、`jsonschema`、`fastapi`、`uvicorn`。测试沿用仓库现有写法：`tests/pipeline/test_offline.py` 单个 `main()` + `assert` + `print("… ✓")`，**不引入 pytest**。

**设计依据:** `docs/specs/2026-10-10-langchain-langgraph-refactor-design.md`（§6 的四条踩坑补偿对应 Task 4 / Task 5 / Task 2 / Task 2）。

---

## 文件结构

| 文件 | 责任 | 动作 |
|---|---|---|
| `backend/pipeline/chat.py` | 聊天模型工厂、用量回调、thinking 降级、截断诊断、`extract_json` | 新建（取代 `llm.py`） |
| `backend/pipeline/tools.py` | 6 个修复工具的 `@tool` 声明，`InjectedState` 读状态、`Command` 写状态 | 新建 |
| `backend/pipeline/graph.py` | `BatchState`、各节点、条件边、`build_batch_graph`、`run_batch`、`_check_batch`、`_log_report` | 新建 |
| `backend/pipeline/errors.py` | `ConversionError`（从 `convert.py` 挪出，解 `graph.py` ↔ `convert.py` 循环依赖） | 新建 |
| `backend/pipeline/llm.py` | — | 删除（Task 10） |
| `backend/pipeline/convert.py` | 只剩外壳：归一化 / 切批 / 续批块 / 合并 / 终检 / manifest | 修改 |
| `backend/pipeline/review.py` | 首参从鸭子类型换成 `ChatInvoker` | 修改 |
| `backend/tests/pipeline/fakes.py` | `FakeChat`（`BaseChatModel` 测试替身），取代 `MockLLM` / `UsageMockLLM` | 新建 |
| `backend/tests/pipeline/test_offline.py` | 注入点换成 `FakeChat`，补图与补偿的用例 | 修改 |
| `backend/requirements.txt` | 依赖 | 修改 |
| `README.md`、`backend/.env.example` | 文档 | 修改（Task 10） |

**不应出现在本次 diff 里**：`verification.py`、`validate.py`、`quality.py`、`splitter.py`、`source_units.py`、`manifest.py`、`prompt.py`、`schema/`、`prompts/`、`repair.py` 的工具实现函数、`server/`、`frontend/`。

---

### Task 0: 环境升级与干净基线

本任务不改任何产品代码。目的是先证明「Python 3.12 + 现有代码」是绿的，这样后面测试一红就一定是改造引入的。

**Files:**
- Modify: `backend/requirements.txt`

- [ ] **Step 1: 装 Python 3.12**

```bash
brew install python@3.12
/opt/homebrew/bin/python3.12 -V
```

Expected: `Python 3.12.x`

- [ ] **Step 2: 重建 venv（当前是 3.9.6，LangChain 1.x 跑不起来）**

```bash
cd backend
rm -rf .venv
/opt/homebrew/bin/python3.12 -m venv .venv
.venv/bin/python -V
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
```

Expected: `Python 3.12.x`，安装无报错

- [ ] **Step 3: 跑干净基线（改造前的代码，新解释器）**

Run: `cd backend && .venv/bin/python tests/pipeline/test_offline.py`
Expected: 最后一行 `ALL PASS`，退出码 0

如果这里就红了，**先停下**修 3.12 兼容问题并单独提交，不要和改造混在一起。

- [ ] **Step 4: 写入新依赖**

把 `backend/requirements.txt` 改成：

```
anthropic>=0.120,<2
langchain-anthropic>=1.7,<2
langgraph>=1.2,<2
jsonschema>=4.0
fastapi>=0.115
uvicorn>=0.30
```

```bash
cd backend && .venv/bin/pip install -q -r requirements.txt
```

Expected: 安装无报错（`langchain-anthropic` 会把 `anthropic` 升到 0.120+）

- [ ] **Step 5: 导入路径一次性验证**

这一步把计划里所有有风险的 import 路径和字段名一次验完，后面各任务就不必再怀疑。

```bash
cd backend && .venv/bin/python - <<'PY'
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.tools import tool, InjectedToolCallId
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, InjectedState
from langgraph.types import Command
m = ChatAnthropic(api_key="x", model="claude-sonnet-5",
                  anthropic_api_url="https://example.invalid", max_tokens=16)
assert m.anthropic_api_url == "https://example.invalid", m.anthropic_api_url
print("imports ok；自定义端点字段是 anthropic_api_url")
PY
```

Expected: `imports ok；自定义端点字段是 anthropic_api_url`

若某个 import 报 `ImportError`，按报错调整后续任务里的 import 行——**不要**改成猜测的路径硬写。
特别注意：`ChatAnthropic` 的自定义端点字段是 `anthropic_api_url`（环境变量 `ANTHROPIC_API_URL`），
**不是** `base_url`；本项目的配置项仍叫 `ANTHROPIC_BASE_URL`，由 `chat.py` 显式转接。

- [ ] **Step 6: 提交**

```bash
git add backend/requirements.txt
git commit -m "环境：升到 Python 3.12，依赖换成 langchain-anthropic + langgraph"
```

---

### Task 1: 测试替身 `FakeChat`

改造后注入点从「带 `complete(system, messages) -> str` 的对象」变成 `BaseChatModel`。
自己写替身而不用 `langchain_core` 的 fake 工具类：接口完全可控，顺带把 `BaseChatModel`
的最小实现契约（`_generate` / `_llm_type` / `bind_tools`）学一遍。

**Files:**
- Create: `backend/tests/pipeline/fakes.py`
- Test: `backend/tests/pipeline/test_fakes.py`

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/pipeline/test_fakes.py`：

```python
#!/usr/bin/env python3
"""FakeChat 测试替身自身的测试。用法: python3 tests/pipeline/test_fakes.py"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from fakes import FakeChat


@tool
def dummy(x: int) -> int:
    """给 bind_tools 用的空工具。"""
    return x


def main() -> int:
    # 1. 字符串排队返回，并记录收到的消息
    chat = FakeChat(responses=["第一条", "第二条"])
    assert chat.invoke([HumanMessage("甲")]).content == "第一条"
    assert chat.invoke([HumanMessage("乙")]).content == "第二条"
    assert [m[0].content for m in (r["messages"] for r in chat.requests)] == ["甲", "乙"]
    print("FakeChat: 排队返回 + 记录请求 ✓")

    # 2. 预设 AIMessage 原样返回（修复用例要带 tool_calls）
    msg = AIMessage(content="", tool_calls=[
        {"name": "validation_list", "args": {}, "id": "call_1"}])
    chat2 = FakeChat(responses=[msg])
    out = chat2.invoke([HumanMessage("丙")])
    assert out.tool_calls[0]["name"] == "validation_list"
    print("FakeChat: 透传带 tool_calls 的 AIMessage ✓")

    # 3. bind_tools 可用，且绑定的工具名进得了调用记录
    chat3 = FakeChat(responses=["好"])
    bound = chat3.bind_tools([dummy])
    assert bound.invoke([HumanMessage("丁")]).content == "好"
    assert chat3.requests[-1]["kwargs"]["tool_names"] == ["dummy"]
    print("FakeChat: bind_tools 记录工具名 ✓")

    # 4. usage_metadata 用字符数替身，且 input_tokens 是含缓存的总和
    chat4 = FakeChat(responses=["输出"])
    u = chat4.invoke([HumanMessage("输入文本")]).usage_metadata
    assert u["output_tokens"] == 2 and u["input_tokens"] == 4
    assert u["input_token_details"] == {"cache_read": 0, "cache_creation": 0}
    print("FakeChat: usage_metadata 形状与 langchain 约定一致 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python tests/pipeline/test_fakes.py`
Expected: FAIL，`ModuleNotFoundError: No module named 'fakes'`

- [ ] **Step 3: 写实现**

创建 `backend/tests/pipeline/fakes.py`：

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/bin/python tests/pipeline/test_fakes.py`
Expected: `ALL PASS`

- [ ] **Step 5: 提交**

```bash
git add backend/tests/pipeline/fakes.py backend/tests/pipeline/test_fakes.py
git commit -m "测试：BaseChatModel 替身 FakeChat"
```

---

### Task 2: `chat.py` — 模型工厂与用量回调

对应 spec §6 补偿 3（token 归因）与补偿 4（自定义端点）。

**Files:**
- Create: `backend/pipeline/chat.py`
- Test: `backend/tests/pipeline/test_chat.py`

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/pipeline/test_chat.py`：

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python tests/pipeline/test_chat.py`
Expected: FAIL，`ModuleNotFoundError: No module named 'pipeline.chat'`

- [ ] **Step 3: 写实现**

创建 `backend/pipeline/chat.py`：

```python
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
        import httpx
        runnable = model.bind_tools(tools) if tools else model
        return runnable.with_retry(
            retry_if_exception_type=(httpx.HTTPError,
                                     anthropic.APIConnectionError,
                                     anthropic.InternalServerError,
                                     anthropic.RateLimitError),
            stop_after_attempt=self._settings.transport_retries + 1,
            wait_exponential_jitter=True,
        )

    def invoke(self, messages, tools=None):
        """调模型，返回 AIMessage。瞬时传输故障由 with_retry 指数退避重试。"""
        import anthropic
        config = {"callbacks": [self.usage]}
        model = self._no_thinking if self._thinking_rejected else self._model
        try:
            return self._runnable(model, tools).invoke(messages, config=config)
        except anthropic.BadRequestError as e:
            if self._thinking_rejected or "thinking" not in str(e).lower() \
                    or _thinking_param(self._settings.thinking) is None:
                raise
            # 网关不认这个参数：退回默认行为，但要说一声——推理块会重新开始烧预算
            self._thinking_rejected = True
            self._log(f"服务端不接受 thinking 参数（{str(e)[:120]}），"
                      "改用模型默认行为重试")
            self._no_thinking = self._model if self._injected else build_chat_model(
                replace_thinking(self._settings))
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/bin/python tests/pipeline/test_chat.py`
Expected: `ALL PASS`

- [ ] **Step 5: 提交**

```bash
git add backend/pipeline/chat.py backend/tests/pipeline/test_chat.py
git commit -m "chat.py：ChatAnthropic 工厂与用量回调"
```

---

### Task 3: 网关 `tool_calls` 风险探针

spec §10 把「第三方网关对 `bind_tools` 的支持度」列为本次改造最大的未验证风险。
在写完整张图之前先用最小脚本验掉它，别等图写完才发现要回退。
**本脚本会产生真实 API 调用费用，且不进测试套件。**

**Files:**
- Create: `backend/tools/probe_tool_calls.py`

- [ ] **Step 1: 写探针脚本**

创建 `backend/tools/probe_tool_calls.py`：

```python
#!/usr/bin/env python3
"""探针：验证当前配置的模型/网关是否支持原生 tool_calls。

会产生真实 API 费用。用法: .venv/bin/python tools/probe_tool_calls.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

from pipeline.chat import ChatInvoker
from pipeline.config import load_settings


@tool
def validation_list() -> list:
    """列出当前分镜产物的全部校验失败条目。"""
    return [{"code": "shot_missing_asset", "where": "E01S003"}]


def main() -> int:
    settings = load_settings()
    print(f"模型 {settings.model}，端点 {settings.base_url or '官方'}")
    chat = ChatInvoker(settings)
    msg = chat.invoke(
        [HumanMessage("先用 validation_list 工具看看有哪些校验失败条目。")],
        tools=[validation_list])
    print(f"stop_reason={msg.response_metadata.get('stop_reason')}")
    print(f"tool_calls={msg.tool_calls}")
    if not msg.tool_calls:
        print("\n不支持原生 tool_calls（或模型没选择调用）。"
              "按 spec §10 的兜底：修复阶段退回自研文本协议，图结构保留。")
        return 1
    print("\n支持原生 tool_calls，可按计划用 bind_tools + ToolNode。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 对官方端点跑一次**

Run: `cd backend && .venv/bin/python tools/probe_tool_calls.py`
Expected: 打印出非空 `tool_calls`，退出码 0

- [ ] **Step 3: 对实际在用的网关端点跑一次**

```bash
cd backend && STORYBOARD_MODEL=<网关上的模型名> ANTHROPIC_BASE_URL=<网关地址> \
  .venv/bin/python tools/probe_tool_calls.py
```

Expected: 二者之一，都要**把结论记下来**：
- 非空 `tool_calls` → 按 Task 6/7 原计划做
- 空 `tool_calls` 或报错 → **停下来向用户汇报**，按 spec §10 兜底：Task 6/7 的
  `repair_agent` 节点改回自研文本协议解析（`repair.apply_tool_call`），图结构与
  其余任务不变

- [ ] **Step 4: 提交**

```bash
git add backend/tools/probe_tool_calls.py
git commit -m "探针：验证网关的原生 tool_calls 支持"
```

---

### Task 4: thinking 降级重试（补偿 1）

**Files:**
- Modify: `backend/tests/pipeline/test_chat.py`

- [ ] **Step 1: 写失败测试**

在 `test_chat.py` 的 `main()` 里，`print("\nALL PASS")` 之前插入：

```python
    # 5. 网关不认 thinking 参数：摘掉重试一次，别让兼容性问题变成硬失败
    import anthropic
    import httpx

    def picky(messages):
        raise anthropic.BadRequestError(
            "thinking: unsupported parameter",
            response=httpx.Response(400, request=httpx.Request("POST", "http://x")),
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
    def other_400(messages):
        raise anthropic.BadRequestError(
            "credit balance too low",
            response=httpx.Response(400, request=httpx.Request("POST", "http://x")),
            body=None)

    try:
        ChatInvoker(Settings(api_key="k", thinking="2000"),
                    chat=FakeChat(responses=[other_400]),
                    log=logs.append).invoke([HumanMessage("x")])
        raise AssertionError("与 thinking 无关的 400 应原样抛出")
    except anthropic.BadRequestError:
        pass
    print("chat: 无关的 400 不被降级逻辑吞掉 ✓")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python tests/pipeline/test_chat.py`
Expected: FAIL（`FakeChat` 注入时 `_no_thinking` 为 `None`，或降级分支未触发）

- [ ] **Step 3: 修实现**

`chat.py` 的 `ChatInvoker.invoke` 里，降级分支取备用模型的那行改为先赋值再使用，
确保注入替身时复用同一个对象：

```python
            self._no_thinking = self._model if self._injected else build_chat_model(
                replace_thinking(self._settings))
            self._thinking_rejected = True
            return self._runnable(self._no_thinking, tools).invoke(
                messages, config=config)
```

并把方法开头取模型的那行改为：

```python
        model = self._no_thinking if (self._thinking_rejected
                                      and self._no_thinking is not None) else self._model
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/bin/python tests/pipeline/test_chat.py`
Expected: `ALL PASS`

- [ ] **Step 5: 提交**

```bash
git add backend/pipeline/chat.py backend/tests/pipeline/test_chat.py
git commit -m "chat.py：网关拒 thinking 参数时降级重试"
```

---

### Task 5: 截断诊断（补偿 2）

改造前这条诊断在 `test_offline.py` 里有用例（搜 `推理模型诊断`），本任务把它迁到
新的消息层上。

**Files:**
- Modify: `backend/tests/pipeline/test_chat.py`

- [ ] **Step 1: 写失败测试**

在 `test_chat.py` 的 `main()` 里，`print("\nALL PASS")` 之前插入：

```python
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
        assert "推理块" in str(e) and "60664" in str(e)
        assert "STORYBOARD_THINKING" in str(e)
        assert "调小 STORYBOARD_BATCH_CHARS 对这种情况无效" in str(e)
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
        assert "推理" not in str(e) and "STORYBOARD_MAX_TOKENS" in str(e)
    print("chat: 普通截断报另一套话 ✓")

    # 9. 正常结束时原样返回正文
    inv4 = ChatInvoker(Settings(api_key="k"), chat=FakeChat(responses=["正文"]))
    assert inv4.text(inv4.invoke([HumanMessage("x")])) == "正文"
    print("chat: 正常结束原样返回正文 ✓")
```

- [ ] **Step 2: 跑测试确认失败或通过**

Run: `cd backend && .venv/bin/python tests/pipeline/test_chat.py`
Expected: 若 Task 2 的 `message_text` 已完整实现，这里直接 PASS——那也要把测试留下，
它是补偿 2 的回归护栏。若 FAIL，按报错补齐 `message_text` 的分支。

- [ ] **Step 3: 提交**

```bash
git add backend/tests/pipeline/test_chat.py backend/pipeline/chat.py
git commit -m "chat.py：截断诊断区分推理块烧光与普通截断"
```

---

### Task 6: `tools.py` — 6 个修复工具

**Files:**
- Create: `backend/pipeline/tools.py`
- Test: `backend/tests/pipeline/test_tools.py`

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/pipeline/test_tools.py`：

```python
#!/usr/bin/env python3
"""修复工具的单元测试。用法: python3 tests/pipeline/test_tools.py"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from langgraph.types import Command

from pipeline import repair, tools
from pipeline.verification import VerificationReport

DOC = {
    "meta": {"work_title": "药"},
    "coverage": {"total_units": 1},
    "source": {"units": [{"id": "u0001", "text": "秋天的后半夜。"}]},
    "assets": {"characters": [{"id": "C01", "name": "老栓"}]},
    "episodes": [{"id": "E01", "shots": [{"id": "E01S001", "action": "旧"}]}],
}


def main() -> int:
    # 1. 工具清单与改造前的自研协议一一对应
    assert {t.name for t in tools.REPAIR_TOOLS} == set(repair.ALLOWED_TOOLS)
    print("tools: 6 个工具与 repair.ALLOWED_TOOLS 对齐 ✓")

    # 2. 每个工具都有中文 docstring（它就是喂给模型的工具说明）
    for t in tools.REPAIR_TOOLS:
        assert t.description and any("一" <= c <= "鿿"
                                     for c in t.description), \
            f"{t.name} 缺中文说明"
    print("tools: 工具说明齐备 ✓")

    # 3. doc 不在模型可见的参数表里（36KB 文档必须靠 InjectedState 注入）
    for t in tools.REPAIR_TOOLS:
        schema = t.args_schema.model_json_schema()
        assert "state" not in schema.get("properties", {}), \
            f"{t.name} 把 state 暴露给模型了"
        assert "doc" not in schema.get("properties", {}), \
            f"{t.name} 把 doc 暴露给模型了"
    print("tools: state/doc 对模型不可见 ✓")

    # 4. json_patch 产出 Command，把补丁后的 doc 写回状态
    patched = tools.json_patch.func(
        patch=[{"op": "replace", "path": "/episodes/0/shots/0/action",
                "value": "新"}],
        tool_call_id="call_1",
        state={"doc": DOC, "structured": VerificationReport()})
    assert isinstance(patched, Command)
    assert patched.update["doc"]["episodes"][0]["shots"][0]["action"] == "新"
    assert patched.update["patch_applied"] is True
    assert DOC["episodes"][0]["shots"][0]["action"] == "旧", "不许原地改入参"
    print("tools: json_patch 用 Command 写回新 doc ✓")

    # 5. 锁定前缀照旧拦住（/coverage 与 /meta 是后处理结果，模型不得改）
    try:
        tools.json_patch.func(
            patch=[{"op": "replace", "path": "/coverage/total_units", "value": 99}],
            tool_call_id="call_1",
            state={"doc": DOC, "structured": VerificationReport()})
        raise AssertionError("/coverage 必须锁定")
    except repair.RepairError:
        pass
    print("tools: /coverage 与 /meta 仍然锁定 ✓")

    # 6. task_done 标记收工
    done = tools.task_done.func(tool_call_id="call_1")
    assert isinstance(done, Command) and done.update["task_done"] is True
    print("tools: task_done 标记收工 ✓")

    # 7. 只读工具直接复用 repair.py 的实现
    assert tools.source_read.func(unit_ids=["u0001"],
                                  state={"doc": DOC})[0]["id"] == "u0001"
    assert tools.asset_get.func(asset_ids=["C01"],
                                state={"doc": DOC})[0]["name"] == "老栓"
    print("tools: 只读工具复用 repair.py 实现 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python tests/pipeline/test_tools.py`
Expected: FAIL，`ModuleNotFoundError: No module named 'pipeline.tools'`

- [ ] **Step 3: 写实现**

创建 `backend/pipeline/tools.py`：

```python
"""修复阶段的工具声明。

工具实现一律复用 repair.py——那里的约束（只允许 add/remove/replace、
/coverage 与 /meta 前缀锁定、模型拿不到文件系统或任意代码执行）是审计过的，
本模块只负责把它们包成 LangChain 工具。

关键设计点：doc 有 36KB，绝不能让模型当参数传。用 InjectedState 让运行时把
状态塞进来，模型只看得见 unit_ids / asset_ids / patch 这几个小参数。
"""
import copy
from typing import Annotated, Any

from langchain_core.tools import InjectedToolCallId, tool
from langchain_core.messages import ToolMessage
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from . import repair


@tool
def source_read(unit_ids: list[str],
                state: Annotated[dict, InjectedState]) -> list[dict]:
    """按句子编号读取冻结的原文句单元，确认画面有没有原文依据。例：["u0001"]。"""
    return repair.source_read(state["doc"], unit_ids)


@tool
def asset_get(asset_ids: list[str],
              state: Annotated[dict, InjectedState]) -> list[dict]:
    """按资产编号读取资产卡（角色 C / 场景 S / 道具 P / 设定图 A）。例：["C01"]。"""
    return repair.asset_get(state["doc"], asset_ids)


@tool
def validation_list(state: Annotated[dict, InjectedState]) -> list[dict]:
    """列出当前产物的全部校验失败条目，每条含位置与原因。"""
    return repair.validation_list(state["structured"])


@tool
def coverage_query(state: Annotated[dict, InjectedState]) -> dict:
    """查询原文覆盖率统计：哪些句单元还没有镜头覆盖。"""
    return repair.coverage_query(state["structured"])


@tool
def json_patch(patch: list[dict],
               tool_call_id: Annotated[str, InjectedToolCallId],
               state: Annotated[dict, InjectedState]) -> Command:
    """提交受限 JSON Patch 修正产物。只允许 add/remove/replace；
    /coverage 与 /meta 前缀锁定（它们是程序重算的结果，不接受模型改写）。"""
    doc = repair.apply_tool_call(copy.deepcopy(state["doc"]),
                                 {"tool": "json_patch", "patch": patch})
    return Command(update={
        "doc": doc,
        "patch_applied": True,
        "messages": [ToolMessage(f"补丁已应用（{len(patch)} 项），即将重新校验",
                                 tool_call_id=tool_call_id)],
    })


@tool
def task_done(tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """声明本轮修复完成，交回程序重新校验。"""
    return Command(update={
        "task_done": True,
        "messages": [ToolMessage("本轮修复结束，重新校验",
                                 tool_call_id=tool_call_id)],
    })


REPAIR_TOOLS = [source_read, asset_get, validation_list, coverage_query,
                json_patch, task_done]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/bin/python tests/pipeline/test_tools.py`
Expected: `ALL PASS`

若 `repair.apply_tool_call` 的签名与这里的调用不符（它期望的 payload 形状），
以 `repair.py` 现有实现为准调整本模块，**不要**改 `repair.py`。

- [ ] **Step 5: 提交**

```bash
git add backend/pipeline/tools.py backend/tests/pipeline/test_tools.py
git commit -m "tools.py：修复工具改成 @tool + InjectedState + Command"
```

---

### Task 7: `errors.py` + `graph.py` 骨架（generate / check / finalize）

先跑通「一次就过」与「硬失败 → 回喂重写 → 再校验」两条路径，修复循环留给 Task 8。

**Files:**
- Create: `backend/pipeline/errors.py`
- Create: `backend/pipeline/graph.py`
- Test: `backend/tests/pipeline/test_graph.py`

- [ ] **Step 1: 挪 `ConversionError`**

创建 `backend/pipeline/errors.py`：

```python
"""流水线异常。单独成模块是为了让 graph.py 与 convert.py 都能用而不互相 import。"""


class ConversionError(RuntimeError):
    def __init__(self, msg: str, report: str = ""):
        super().__init__(msg)
        self.report = report
```

在 `backend/pipeline/convert.py` 里删掉 `class ConversionError` 的定义，改为在 import 区加：

```python
from .errors import ConversionError
```

`from .convert import ConversionError` 的三个现有调用方（`__main__.py`、`server/app.py`、
`tests/pipeline/test_offline.py`）因此不用改。

- [ ] **Step 2: 跑基线确认挪动无副作用**

Run: `cd backend && .venv/bin/python tests/pipeline/test_offline.py`
Expected: `ALL PASS`

- [ ] **Step 3: 提交**

```bash
git add backend/pipeline/errors.py backend/pipeline/convert.py
git commit -m "ConversionError 挪进 errors.py，解图与编排器的循环依赖"
```

- [ ] **Step 4: 写失败测试**

创建 `backend/tests/pipeline/test_graph.py`：

```python
#!/usr/bin/env python3
"""单批图的测试。用法: python3 tests/pipeline/test_graph.py"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakes import FakeChat
from pipeline.chat import ChatInvoker
from pipeline.config import Settings
from pipeline.convert import ConvertParams
from pipeline.errors import ConversionError
from pipeline.graph import build_batch_graph, run_batch

YAO = ROOT / "tests" / "real_text_yao"


def _fixture():
    """取《药》归档的批 1 作为「一次就过」的输入与产物。"""
    import re
    text = (YAO / "input_batch1.txt").read_text(encoding="utf-8")
    m = re.search(r"^章节：.*$", text, flags=re.M)
    batch = text[m.end():] if m else text
    return batch, (YAO / "output_batch1.json").read_text(encoding="utf-8")


def main() -> int:
    batch, archived = _fixture()
    params = ConvertParams(work_title="药", chapter="全文（1919）",
                           narration_mode="selective")
    settings = Settings(api_key="k", max_retries=0, normalize_input=False,
                        freeze_source_units=False)

    # 1. 一次就过：图跑完，result 是产物，没有降级警告
    with tempfile.TemporaryDirectory() as d:
        records = []
        logs = []
        chat = ChatInvoker(settings, chat=FakeChat(responses=[archived]),
                           log=logs.append)
        graph = build_batch_graph(chat=chat, review_chat=chat, settings=settings,
                                  params=params, workdir=Path(d),
                                  attempt_records=records, log=logs.append)
        doc, warnings = run_batch(graph, user="【小说原文】" + batch,
                                  batch_text=batch, idx=1, frozen_units=None)
        assert doc == json.loads(archived), "一次就过时产物应与归档一致"
        assert warnings == []
        assert [r["status"] for r in records] == ["passed"]
        assert records[0]["mode"] == "generate" and records[0]["attempt"] == 1
        assert records[0]["usage"]["output"] > 0, "token 要归到这次尝试上"
        print("graph: 一次就过 → result + attempt_records ✓")

    # 2. 首次输出不是 JSON：记 unparseable，重试一次后通过
    with tempfile.TemporaryDirectory() as d:
        records = []
        logs = []
        s2 = Settings(api_key="k", max_retries=1, normalize_input=False,
                      freeze_source_units=False, repair_mode="rewrite")
        chat = ChatInvoker(s2, chat=FakeChat(responses=["我不输出 JSON", archived]),
                           log=logs.append)
        graph = build_batch_graph(chat=chat, review_chat=chat, settings=s2,
                                  params=params, workdir=Path(d),
                                  attempt_records=records, log=logs.append)
        doc, warnings = run_batch(graph, user="【小说原文】" + batch,
                                  batch_text=batch, idx=1, frozen_units=None)
        assert doc == json.loads(archived)
        assert [r["status"] for r in records] == ["unparseable", "passed"]
        print("graph: 不可解析 → 重试 → 通过 ✓")

    # 3. 重试耗尽且无合法候选：抛 ConversionError，失败报告落盘
    with tempfile.TemporaryDirectory() as d:
        records = []
        chat = ChatInvoker(settings, chat=FakeChat(responses=["坏输出"]),
                           log=lambda _: None)
        graph = build_batch_graph(chat=chat, review_chat=chat, settings=settings,
                                  params=params, workdir=Path(d),
                                  attempt_records=records, log=lambda _: None)
        try:
            run_batch(graph, user="u", batch_text=batch, idx=7, frozen_units=None)
            raise AssertionError("重试耗尽应抛 ConversionError")
        except ConversionError as e:
            assert e.report
            assert (Path(d) / "batch7_failure_report.txt").exists()
        print("graph: 重试耗尽 → ConversionError + 报告落盘 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: 跑测试确认失败**

Run: `cd backend && .venv/bin/python tests/pipeline/test_graph.py`
Expected: FAIL，`ModuleNotFoundError: No module named 'pipeline.graph'`

- [ ] **Step 6: 写实现**

创建 `backend/pipeline/graph.py`。本步只连 `generate → check → finalize`，
`plan_repair` / `repair_agent` / `tools` 三个节点在 Task 8 接上。

```python
"""单批转换的状态图：生成 → 校验 →（修复）→ 重试/择优降级。

对应改造前 convert.py 里 _convert_batch 的 for 循环。校验节点不调 LLM，
它只是把现有的确定性审查链路（verification / validate / quality / review）
原样串起来。
"""
import json
from pathlib import Path
from typing import Annotated, Any, List, Optional, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from . import quality, repair, review, validate, verification
from .chat import LLMError, extract_json
from .config import Settings
from .errors import ConversionError
from .prompt import load_system_prompt

_REPORT_LOG_LINES = 60
_MAX_TOOL_STEPS = 8          # 与改造前 `for _ in range(8)` 等价


class BatchState(TypedDict):
    """单批转换的状态。

    messages 用 add_messages reducer 累加；其余字段由节点整体覆写。
    每批一个实例，批号/原文/冻结句单元都在这里，而 settings / workdir /
    attempt_records 这些跨批不变的东西由 build_batch_graph 闭包持有。
    """
    messages: Annotated[List[AnyMessage], add_messages]
    user: str
    batch_text: str
    idx: int
    frozen_units: Optional[list]
    attempt: int
    mode: str                 # "generate" | "patch"
    doc: Optional[dict]
    report: str
    structured: Any
    candidates: list
    tool_steps: int
    patch_applied: bool
    task_done: bool
    usage_mark: Optional[dict]
    result: Optional[dict]
    warnings: List[str]


def _log_report(log, report: str, workdir: Path, idx: int, attempt: int) -> None:
    """把校验/质量门的失败原因逐行打进日志。

    用户看不到工作目录，光说"未通过"等于没说；报告可能很长，
    截断后指向落盘的完整报告，不让日志被单个批次淹掉。
    """
    lines = report.strip().splitlines()
    if not lines:
        log("  （校验器未给出细节）")
        return
    for line in lines[:_REPORT_LOG_LINES]:
        log(f"  {line}")
    if len(lines) > _REPORT_LOG_LINES:
        path = workdir / f"batch{idx}_attempt{attempt}_report.txt"
        try:
            path.write_text(report + "\n", encoding="utf-8")
            log(f"  …还有 {len(lines) - _REPORT_LOG_LINES} 行，完整报告见 {path}")
        except OSError:
            log(f"  …还有 {len(lines) - _REPORT_LOG_LINES} 行未显示")


def _check_batch(doc: dict, batch_text: str, settings: Settings,
                 workdir: Path, idx: int, attempt: int,
                 review_chat, log, frozen_units=None):
    """结构校验 → 质量门 → 可选评审。返回 (是否通过, 硬失败?, 报告, 择优键, 结构化报告)。

    从 convert.py 原样搬来，逻辑未改：硬失败（schema/lint/保真不过）的产物合同
    已破坏，不可交付；软失败（密度门/评审分不过）的产物合法可用，仅质量不达标，
    择优键（越大越接近达标）供重试耗尽后降级交付时挑最优一版。
    """
    # coverage 是后处理结果，不信任模型声明。先计算再覆写，然后从干净状态复验。
    probe = verification.verify_document(
        doc, frozen_units=frozen_units, original_text=batch_text)
    verification.recompute_coverage_field(doc, probe.coverage)
    structured = verification.verify_document(
        doc, frozen_units=frozen_units, original_text=batch_text)

    tmp = workdir / f"batch{idx}_attempt{attempt}.json"
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    if not structured.ok:
        return False, True, structured.render(), None, structured
    lint_ok, lint_out = validate.run_lint(tmp)
    fid_ok, fid_out = validate.run_fidelity(tmp, batch_text, workdir)
    if not (lint_ok and fid_ok):
        return (False, True, lint_out.strip() + "\n" + fid_out.strip(), None,
                structured)

    gate_ok, gate_report, ratio = quality.narration_density_gate(
        doc, settings.narration_density_max)
    if not gate_ok:
        return False, False, gate_report, (1, -ratio), structured

    # 时长必须够念完旁白与台词，否则成片时要么截断语音、要么被迫拉长镜头，
    # 按名义时长做的预算当场失准。排在密度门之后择优（它已多过一道门）。
    fit_ok, fit_report, over = quality.speech_fit_gate(
        doc, settings.speech_overflow_max, settings.speech_cps)
    if not fit_ok:
        return False, False, fit_report, (2, -over), structured

    if settings.review_enabled and review_chat is not None:
        rev_ok, rev_report, overall = review.run_review(
            review_chat, batch_text, doc, settings.review_min_score,
            settings.review_dimension_min, settings.semantic_fidelity_min)
        if rev_ok is None:
            log(f"批 {idx} {rev_report}")
            return False, False, rev_report, (3, -1.0), structured
        else:
            log(rev_report.splitlines()[0])
            if not rev_ok:
                # 评审失败排在前两道门之后择优（它已多过两道门）
                return False, False, rev_report, (3, overall), structured
    return True, False, structured.render(), None, structured


def build_batch_graph(*, chat, review_chat, settings: Settings, params,
                      workdir: Path, attempt_records: list, log=print):
    """编译单批状态图。跨批不变的依赖由闭包持有，不进状态。"""
    system = load_system_prompt()

    def _record(state: BatchState, status: str, used_tools: list,
                structured=None, report: str = "") -> None:
        after = chat.usage_totals()
        before = state.get("usage_mark") or {}
        usage = ({k: after[k] - before.get(k, 0) for k in after}
                 if before else None)
        rec = {"batch": state["idx"], "attempt": state["attempt"],
               "mode": state["mode"], "status": status,
               "report": report, "tools": used_tools, "usage": usage}
        if structured is not None:
            rec["verification"] = structured.to_dict()
        attempt_records.append(rec)

    def generate(state: BatchState) -> dict:
        """整份输出：文本 JSON 协议 + 容错解析。"""
        messages = [SystemMessage(content=[{
            # 22KB 系统提示词每批都发，缓存标记丢了等于每批多付一次全价
            "type": "text", "text": system,
            "cache_control": {"type": "ephemeral"}}])] + list(state["messages"])
        mark = chat.usage_totals()
        msg = chat.invoke(messages)
        try:
            raw = chat.text(msg)
        except LLMError:
            raise
        try:
            doc = extract_json(raw)
        except ValueError as e:
            return {"messages": [msg], "doc": None, "usage_mark": mark,
                    "report": f"输出无法解析为 JSON：{e}"}
        return {"messages": [msg], "doc": doc, "usage_mark": mark, "report": ""}

    def check(state: BatchState) -> dict:
        """确定性审查。本节点不调 LLM（评审阶段除外，由 settings 显式开启）。"""
        attempt = state["attempt"] + 1
        idx = state["idx"]
        if state["doc"] is None:
            report = state["report"] or "输出无法解析为 JSON"
            log(f"批 {idx} 第 {attempt} 次生成：{report}")
            _record({**state, "attempt": attempt}, "unparseable", [],
                    report=report)
            # 没有可打补丁的底稿，下一轮只能整份重写
            return {"attempt": attempt, "mode": "generate", "report": report}

        doc = state["doc"]
        quality.apply_meta_overrides(doc, params)
        ok, hard, report, key, structured = _check_batch(
            doc, state["batch_text"], settings, workdir, idx, attempt,
            review_chat, log, state["frozen_units"])
        _record({**state, "attempt": attempt},
                "passed" if ok else ("hard_failed" if hard else "soft_failed"),
                [], structured=structured, report=report)
        if ok:
            log(f"批 {idx} 校验通过（第 {attempt} 次生成）")
            return {"attempt": attempt, "report": report,
                    "structured": structured, "result": doc}
        candidates = list(state["candidates"])
        if not hard:
            candidates.append((key, attempt, doc, report))
        log(f"批 {idx} 第 {attempt} 次生成未通过"
            f"{'校验' if hard else '质量门'}，原因如下：")
        _log_report(log, report, workdir, idx, attempt)
        return {"attempt": attempt, "report": report, "structured": structured,
                "candidates": candidates}

    def finalize(state: BatchState) -> dict:
        """重试耗尽：有合法候选就择优降级交付，否则落盘报告并抛错。"""
        idx = state["idx"]
        if state["candidates"] and not settings.strict:
            key, best_attempt, doc, report = max(state["candidates"],
                                                 key=lambda c: c[0])
            log(f"批 {idx} 软质量门重试耗尽，择优降级交付第 {best_attempt} 次生成"
                f"（产物结构合法、逐字保真；--strict 可改为直接失败）")
            warning = (f"批 {idx} 软质量门重试 {settings.max_retries} 次后仍未达标，"
                       f"择优交付第 {best_attempt} 次生成"
                       f"（共 {len(state['candidates'])} 个合法候选）。"
                       f"产物结构合法、逐字保真，仅转换质量未达阈值：\n{report}")
            return {"result": doc, "warnings": [warning]}
        (workdir / f"batch{idx}_failure_report.txt").write_text(
            state["report"] + "\n", encoding="utf-8")
        raise ConversionError(
            f"批 {idx} 重试 {settings.max_retries} 次后仍未通过校验"
            f"（已通过批次与失败报告保留在 {workdir}）", state["report"])

    def route_after_check(state: BatchState) -> str:
        if state["result"] is not None:
            return END
        if state["attempt"] > settings.max_retries:
            return "finalize"
        return "plan_repair"

    def plan_repair(state: BatchState) -> dict:
        """占位：Task 8 接上受限补丁路径。当前一律整份重写。"""
        idx, attempt = state["idx"], state["attempt"]
        log(f"批 {idx} 回喂校验报告重新输出整份"
            f"（{attempt + 1}/{settings.max_retries + 1}）…")
        return {"mode": "generate", "tool_steps": 0, "patch_applied": False,
                "task_done": False,
                "messages": [HumanMessage(
                    "你的输出未通过自动校验，报告如下：\n\n" + state["report"] +
                    "\n\n请修正全部问题后重新输出完整 JSON"
                    "（只输出一个 JSON 对象，不要解释文字，不要代码块标记）。")]}

    builder = StateGraph(BatchState)
    builder.add_node("generate", generate)
    builder.add_node("check", check)
    builder.add_node("plan_repair", plan_repair)
    builder.add_node("finalize", finalize)
    builder.add_edge(START, "generate")
    builder.add_edge("generate", "check")
    builder.add_conditional_edges("check", route_after_check,
                                  {END: END, "finalize": "finalize",
                                   "plan_repair": "plan_repair"})
    builder.add_edge("plan_repair", "generate")
    builder.add_edge("finalize", END)
    return builder.compile()


def run_batch(graph, *, user: str, batch_text: str, idx: int,
              frozen_units=None, recursion_limit: Optional[int] = None):
    """跑一批，返回 (产物, 质量警告列表)。警告非空即降级交付。"""
    state: BatchState = {
        "messages": [HumanMessage(user)], "user": user,
        "batch_text": batch_text, "idx": idx, "frozen_units": frozen_units,
        "attempt": 0, "mode": "generate", "doc": None, "report": "",
        "structured": verification.VerificationReport(), "candidates": [],
        "tool_steps": 0, "patch_applied": False, "task_done": False,
        "usage_mark": None, "result": None, "warnings": [],
    }
    final = graph.invoke(state, config={"recursion_limit": recursion_limit or 200})
    return final["result"], final["warnings"]
```

- [ ] **Step 7: 跑测试确认通过**

Run: `cd backend && .venv/bin/python tests/pipeline/test_graph.py`
Expected: `ALL PASS`

- [ ] **Step 8: 提交**

```bash
git add backend/pipeline/graph.py backend/tests/pipeline/test_graph.py
git commit -m "graph.py：单批状态图骨架（生成/校验/择优降级）"
```

---

### Task 8: 图的修复循环（`repair_agent` ⇄ `tools`）

**Files:**
- Modify: `backend/pipeline/graph.py`
- Modify: `backend/tests/pipeline/test_graph.py`

- [ ] **Step 1: 写失败测试**

在 `test_graph.py` 的 `main()` 里，`print("\nALL PASS")` 之前插入：

```python
    # 4. 硬失败 → 受限补丁修复 → 通过
    from langchain_core.messages import AIMessage
    bad = json.loads(archived)
    bad["episodes"][0]["shots"][0]["action"] = ""      # 造一个 schema 不过的产物

    # 先验证这个造假产物真的硬失败——否则后面整个用例是空跑，测不到修复路径
    with tempfile.TemporaryDirectory() as d:
        from pipeline.graph import _check_batch
        ok, hard, rep_text, _, _ = _check_batch(
            json.loads(json.dumps(bad)), batch, settings, Path(d), 99, 1,
            None, lambda _: None, None)
        assert not ok and hard, \
            f"造假产物没有硬失败，换一种改法（如删掉必填字段）：{rep_text[:200]}"

    with tempfile.TemporaryDirectory() as d:
        records, logs = [], []
        s4 = Settings(api_key="k", max_retries=1, normalize_input=False,
                      freeze_source_units=False, repair_mode="patch")
        good_action = json.loads(archived)["episodes"][0]["shots"][0]["action"]
        responses = [
            json.dumps(bad, ensure_ascii=False),
            # 修复轮第一步：先看校验条目
            AIMessage(content="", tool_calls=[
                {"name": "validation_list", "args": {}, "id": "c1"}]),
            # 第二步：提交补丁
            AIMessage(content="", tool_calls=[
                {"name": "json_patch", "id": "c2", "args": {"patch": [
                    {"op": "replace", "path": "/episodes/0/shots/0/action",
                     "value": good_action}]}}]),
        ]
        chat = ChatInvoker(s4, chat=FakeChat(responses=responses), log=logs.append)
        graph = build_batch_graph(chat=chat, review_chat=chat, settings=s4,
                                  params=params, workdir=Path(d),
                                  attempt_records=records, log=logs.append)
        doc, warnings = run_batch(graph, user="【小说原文】" + batch,
                                  batch_text=batch, idx=1, frozen_units=None)
        assert doc == json.loads(archived), "打完补丁应与归档一致"
        assert [r["status"] for r in records] == ["hard_failed", "passed"]
        assert records[1]["mode"] == "patch"
        assert records[1]["tools"] == ["validation_list", "json_patch"], \
            "用过哪些工具要进清单，不然修复过程没法审计"
        assert any("受限 JSON Patch 修复" in line for line in logs)
        print("graph: 硬失败 → 补丁修复 → 通过，工具轨迹入清单 ✓")

    # 5. 工具步数超上限：记为失败，不让单轮修复无限打转
    with tempfile.TemporaryDirectory() as d:
        records, logs = [], []
        s5 = Settings(api_key="k", max_retries=1, normalize_input=False,
                      freeze_source_units=False, repair_mode="patch")
        spin = AIMessage(content="", tool_calls=[
            {"name": "validation_list", "args": {}, "id": "c1"}])
        chat = ChatInvoker(s5, chat=FakeChat(
            responses=[json.dumps(bad, ensure_ascii=False)] + [spin] * 12),
            log=logs.append)
        graph = build_batch_graph(chat=chat, review_chat=chat, settings=s5,
                                  params=params, workdir=Path(d),
                                  attempt_records=records, log=logs.append)
        try:
            run_batch(graph, user="u", batch_text=batch, idx=2, frozen_units=None)
        except ConversionError:
            pass
        assert any("8 个工具步骤" in r["report"] for r in records), \
            "超过 8 步要明说，与改造前 for _ in range(8) 等价"
        print("graph: 单轮修复超 8 步即中断 ✓")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python tests/pipeline/test_graph.py`
Expected: FAIL，第 4 项断言 `[r["status"] for r in records]` 不等于
`["hard_failed", "passed"]`（当前 `plan_repair` 一律走重写）

- [ ] **Step 3: 写实现**

在 `graph.py` 顶部 import 区补上：

```python
from langgraph.prebuilt import ToolNode

from .tools import REPAIR_TOOLS
```

把 `plan_repair` 整体替换为下面这版，并新增 `repair_agent` 节点与路由：

```python
    def plan_repair(state: BatchState) -> dict:
        """按 repair_mode 拼下一轮消息。有底稿就打补丁，否则整份重写。"""
        idx, attempt = state["idx"], state["attempt"]
        reset = {"tool_steps": 0, "patch_applied": False, "task_done": False,
                 "used_tools": []}
        if state["doc"] is not None and settings.repair_mode == "patch":
            log(f"批 {idx} 进入受限 JSON Patch 修复"
                f"（{attempt + 1}/{settings.max_retries + 1}）…")
            return {**reset, "mode": "patch", "messages": [
                # 重置这一轮的对话：底稿 + 校验报告 + 工具契约
                AIMessage(content=json.dumps(state["doc"], ensure_ascii=False)),
                HumanMessage(repair.repair_request(state["structured"],
                                                   state["report"])),
            ]}
        # rewrite 模式，或首次输出就没解析出 JSON（没有可打补丁的底稿）
        log(f"批 {idx} 回喂校验报告重新输出整份"
            f"（{attempt + 1}/{settings.max_retries + 1}）…")
        return {**reset, "mode": "generate", "messages": [HumanMessage(
            "你的输出未通过自动校验，报告如下：\n\n" + state["report"] +
            "\n\n请修正全部问题后重新输出完整 JSON"
            "（只输出一个 JSON 对象，不要解释文字，不要代码块标记）。")]}

    def repair_agent(state: BatchState) -> dict:
        """修复代理：带工具调模型。每轮算一个工具步骤，上限与改造前一致。"""
        steps = state["tool_steps"] + 1
        if steps > _MAX_TOOL_STEPS:
            report = f"修复工具调用无效：单轮修复超过 {_MAX_TOOL_STEPS} 个工具步骤"
            log(f"批 {state['idx']} {report}")
            # 丢掉底稿，让 check 记一次 unparseable 并转入下一次尝试
            return {"doc": None, "report": report, "tool_steps": steps}
        mark = state["usage_mark"] or chat.usage_totals()
        msg = chat.invoke(list(state["messages"]), tools=REPAIR_TOOLS)
        if not msg.tool_calls:
            report = "修复工具调用无效：模型没有发起任何工具调用"
            log(f"批 {state['idx']} {report}")
            return {"messages": [msg], "doc": None, "report": report,
                    "tool_steps": steps, "usage_mark": mark}
        return {"messages": [msg], "tool_steps": steps, "usage_mark": mark,
                "used_tools": state.get("used_tools", [])
                + [c["name"] for c in msg.tool_calls]}

    def route_after_repair(state: BatchState) -> str:
        if state["doc"] is None:
            return "check"
        return "tools"

    def route_after_tools(state: BatchState) -> str:
        # json_patch / task_done 用 Command 置了标记，说明这一轮修复产出了新底稿
        if state["patch_applied"] or state["task_done"]:
            return "check"
        return "repair_agent"
```

`BatchState` 里补一个字段（紧跟 `tool_steps`）：

```python
    used_tools: List[str]
```

`_record` 里把工具轨迹写进清单——把它的 `used_tools` 形参去掉，改为从状态取：

```python
    def _record(state: BatchState, status: str, structured=None,
                report: str = "") -> None:
        after = chat.usage_totals()
        before = state.get("usage_mark") or {}
        usage = ({k: after[k] - before.get(k, 0) for k in after}
                 if before else None)
        rec = {"batch": state["idx"], "attempt": state["attempt"],
               "mode": state["mode"], "status": status,
               "report": report, "tools": list(state.get("used_tools") or []),
               "usage": usage}
        if structured is not None:
            rec["verification"] = structured.to_dict()
        attempt_records.append(rec)
```

`check` 里两处 `_record(...)` 调用同步去掉第三个实参（原来的 `[]`）:

```python
            _record({**state, "attempt": attempt}, "unparseable", report=report)
...
        _record({**state, "attempt": attempt},
                "passed" if ok else ("hard_failed" if hard else "soft_failed"),
                structured=structured, report=report)
```

`check` 的返回里追加清空工具轨迹（下一次尝试重新计）：`check` 有**三个** `return`
（unparseable / 通过 / 未通过），三个返回的字典里都要加 `"used_tools": []`。

`run_batch` 的初始状态补 `"used_tools": []`。

图的装配改为：

```python
    builder = StateGraph(BatchState)
    builder.add_node("generate", generate)
    builder.add_node("check", check)
    builder.add_node("plan_repair", plan_repair)
    builder.add_node("repair_agent", repair_agent)
    builder.add_node("tools", ToolNode(REPAIR_TOOLS))
    builder.add_node("finalize", finalize)
    builder.add_edge(START, "generate")
    builder.add_edge("generate", "check")
    builder.add_conditional_edges("check", route_after_check,
                                  {END: END, "finalize": "finalize",
                                   "plan_repair": "plan_repair"})
    builder.add_conditional_edges(
        "plan_repair", lambda s: "repair_agent" if s["mode"] == "patch" else "generate",
        {"repair_agent": "repair_agent", "generate": "generate"})
    builder.add_conditional_edges("repair_agent", route_after_repair,
                                  {"tools": "tools", "check": "check"})
    builder.add_conditional_edges("tools", route_after_tools,
                                  {"check": "check", "repair_agent": "repair_agent"})
    builder.add_edge("finalize", END)
    return builder.compile()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/bin/python tests/pipeline/test_graph.py`
Expected: `ALL PASS`

- [ ] **Step 5: 提交**

```bash
git add backend/pipeline/graph.py backend/tests/pipeline/test_graph.py
git commit -m "graph.py：接上 repair_agent 与 ToolNode 修复循环"
```

---

### Task 9: `convert.py` 与 `review.py` 接线

**Files:**
- Modify: `backend/pipeline/convert.py`
- Modify: `backend/pipeline/review.py`
- Modify: `backend/tests/pipeline/test_offline.py`

- [ ] **Step 1: 改 `review.py` 的首参**

`backend/pipeline/review.py`：import 区把

```python
from .llm import extract_json
```

改为

```python
from .chat import extract_json
```

`run_review` 的函数体里，调用那一行从

```python
        raw = llm.complete(REVIEW_SYSTEM, [{"role": "user", "content": user}])
```

改为

```python
        raw = chat.text(chat.invoke([SystemMessage(REVIEW_SYSTEM),
                                     HumanMessage(user)]))
```

签名首参 `llm` 改名为 `chat`，并在 import 区加：

```python
from langchain_core.messages import HumanMessage, SystemMessage
```

docstring 里补一句：`chat 是 chat.ChatInvoker；评审是一次性打分，不入图。`

- [ ] **Step 2: 改 `convert.py`**

删掉这些现在属于 `graph.py` 的东西：`_check_batch`、`_log_report`、`_usage_snapshot`、
`_usage_delta`、`_convert_batch`、`_REPORT_LOG_LINES` 常量，以及
`from .llm import extract_json`、对 `quality` / `repair` / `review` / `validate` 的
import（`validate` 仍被合并与终检用到，**保留**）。

import 区改为（保留原有其它 import）：

```python
from . import validate, verification
from .chat import ChatInvoker
from .config import Settings, load_settings
from .errors import ConversionError
from .graph import build_batch_graph, run_batch
from .manifest import build_manifest, finish_manifest, sum_usage
from .prompt import build_user_message
from .source_units import build_frozen_units, manifest_units, prompt_units
from .splitter import normalize_source_text, split_batches
```

（`load_system_prompt` 现在由 `graph.py` 负责加载，`convert.py` 不再需要它。）

`convert_text` 里构造客户端那段改为：

```python
    if llm is None:
        chat = ChatInvoker(settings, log=log)
    else:
        # 注入的 BaseChatModel（含测试替身）：共用一个用量回调，账才是一本
        chat = ChatInvoker(settings, chat=llm, log=log)
    review_chat = chat
    if settings.review_enabled and settings.review_model \
            and settings.review_model != settings.model and llm is None:
        # 评审用另一档模型时单独建一个，但共用同一个 UsageCallback
        review_chat = ChatInvoker(settings, model=settings.review_model,
                                  usage=chat.usage, log=log)
```

删掉 `system = load_system_prompt()` 那一行，并在 `log(f"输入 {len(text)} 字符 …")`
之后、批次循环之前插入建图：

```python
    graph = build_batch_graph(chat=chat, review_chat=review_chat,
                             settings=settings, params=params, workdir=workdir,
                             attempt_records=attempt_records, log=log)
```

注意 `attempt_records = run_manifest["attempts"]` 这一行要挪到建图之前。

批次循环里调用那两行从

```python
        doc, batch_warnings = _convert_batch(llm, system, user, batch, params,
                                             settings, workdir, i, review_llm, log,
                                             expected_units, attempt_records)
```

改为

```python
        doc, batch_warnings = run_batch(graph, user=user, batch_text=batch,
                                        idx=i, frozen_units=expected_units)
```

`convert_text` 的 docstring 里，`llm` 那一句改为：

```
    llm 可注入任何 BaseChatModel（测试用 FakeChat）。
```

- [ ] **Step 3: 改 `test_offline.py` 的注入点**

import 区：

```python
from pipeline.convert import ConvertParams, convert_text
```

（`_REPORT_LOG_LINES` 已挪到 `graph.py`，改成 `from pipeline.graph import _REPORT_LOG_LINES`。）

加上：

```python
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fakes import FakeChat
```

删掉 `class MockLLM` 与 `class UsageMockLLM`，把文件里所有 `MockLLM([...])` /
`UsageMockLLM([...])` 换成 `FakeChat(responses=[...])`。

断言里读取请求的地方要跟着换，因为记录结构变了，且**消息列表的形状不一样**：
改造前 `messages` 不含 system，改造后 `generate` 节点会在最前面塞一条 `SystemMessage`。
直接按下标取会取错，所以在 `test_offline.py` 里加这两个辅助函数，断言一律走它们：

```python
from langchain_core.messages import HumanMessage


def user_msg(chat, i: int) -> str:
    """第 i 次请求里的**首条** HumanMessage——即 build_user_message 拼出的用户消息。"""
    humans = [m for m in chat.requests[i]["messages"]
              if isinstance(m, HumanMessage)]
    assert humans, f"第 {i} 次请求里没有 HumanMessage"
    return humans[0].content


def last_human(chat, i: int) -> str:
    """第 i 次请求里的**末条** HumanMessage——即回喂的校验报告或工具结果。"""
    humans = [m for m in chat.requests[i]["messages"]
              if isinstance(m, HumanMessage)]
    assert humans, f"第 {i} 次请求里没有 HumanMessage"
    return humans[-1].content
```

对照表：

| 改造前 | 改造后 |
|---|---|
| `mock.calls[1][0]["content"]`（续批参数，第 100/301/308 行附近） | `user_msg(chat, 1)` |
| `mock5.calls[0][0]["content"]`（零宽字符断言） | `user_msg(chat, 0)` |
| `mock_rw.calls[1][-1]["content"]`（回喂的报告） | `last_human(chat, 1)` |
| `len(mock2.calls) == 2` / `len(mock_tools.calls) == 3` | `len(chat2.requests) == 2` / `== 3` |
| `mock.usage_totals()` | 不再需要（用量由 `UsageCallback` 统计，断言改看 manifest 的 `usage`） |

注意 `last_human` 在 patch 模式下取到的是 `repair.repair_request(...)` 的工具契约文本，
在 rewrite 模式下取到的才是「请修正全部问题后重新输出完整 JSON」那段——
原测试第 229 行断言的是 rewrite 模式，用 `last_human` 正确。

删掉第 1018 行附近那段直接构造 `llm_mod.LLMClient.__new__(...)` 的用例——
它测的是补偿 1 与补偿 2，已由 `test_chat.py` 的第 5–9 项覆盖。

- [ ] **Step 4: 跑全部测试**

```bash
cd backend
.venv/bin/python tests/pipeline/test_fakes.py
.venv/bin/python tests/pipeline/test_chat.py
.venv/bin/python tests/pipeline/test_tools.py
.venv/bin/python tests/pipeline/test_graph.py
.venv/bin/python tests/pipeline/test_offline.py
```

Expected: 五个都 `ALL PASS`

- [ ] **Step 5: 确认纯函数模块没被动过**

```bash
cd /Users/lu/my_work_space/projects/idea/story_video_script
git diff --stat main -- backend/pipeline/verification.py backend/pipeline/validate.py \
  backend/pipeline/quality.py backend/pipeline/splitter.py \
  backend/pipeline/source_units.py backend/pipeline/manifest.py \
  backend/pipeline/prompt.py backend/schema backend/prompts
```

Expected: 无输出（spec §3 要求这些文件不进 diff）

- [ ] **Step 6: 提交**

```bash
git add backend/pipeline/convert.py backend/pipeline/review.py \
  backend/tests/pipeline/test_offline.py
git commit -m "编排器接线：单批循环换成 LangGraph 图"
```

---

### Task 10: 清理与文档

**Files:**
- Delete: `backend/pipeline/llm.py`
- Modify: `README.md`
- Modify: `backend/.env.example`

- [ ] **Step 1: 确认 `llm.py` 已无引用**

```bash
cd /Users/lu/my_work_space/projects/idea/story_video_script
grep -rn "pipeline.llm\|from .llm\|LLMClient" backend --include='*.py' | grep -v '\.venv'
```

Expected: 无输出

- [ ] **Step 2: 删除**

```bash
git rm backend/pipeline/llm.py
```

- [ ] **Step 3: 跑全部测试**

```bash
cd backend
for t in fakes chat tools graph offline; do .venv/bin/python tests/pipeline/test_$t.py || break; done
```

Expected: 五个都 `ALL PASS`

- [ ] **Step 4: 更新文档**

`README.md` 里：
- 把后端模块表中 `pipeline/llm.py` 一行替换为三行：`pipeline/chat.py`（模型工厂与用量回调）、
  `pipeline/graph.py`（单批状态图）、`pipeline/tools.py`（修复工具）
- 离线回归那一节补上新增的四个测试文件的运行命令
- Python 版本要求写成 3.12

`backend/.env.example` 里：`ANTHROPIC_BASE_URL` 的注释补一句
「转接到 ChatAnthropic 的 anthropic_api_url」。

- [ ] **Step 5: 提交**

```bash
git add -A README.md backend/.env.example backend/pipeline/llm.py
git commit -m "清理：删除 llm.py，文档对齐新模块布局"
```

---

### Task 11: 真实端到端验收

**Files:** 无（只跑，不改）

- [ ] **Step 1: 对一份真实输入跑通**

```bash
cd backend && .venv/bin/python -m pipeline convert \
  --input tests/real_text_yao/input_full.txt \
  --work-title 药 --chapter '全文（1919）' \
  --out /tmp/yao_langchain.json
```

Expected: 三层校验（schema / lint / 逐字保真）全过，退出码 0

- [ ] **Step 2: 与 `main` 分支产物对照**

```bash
cd /Users/lu/my_work_space/projects/idea/story_video_script
git stash list   # 确认工作区干净
python3 - <<'PY'
import json
a = json.load(open("/tmp/yao_langchain.json"))
print("镜头数", sum(len(e["shots"]) for e in a["episodes"]))
print("句单元", len(a["source"]["units"]))
print("usage 字段", sorted(a.get("meta", {}).keys())[:5])
PY
```

Expected: 镜头数与句单元数与归档 `tests/real_text_yao/output_merged.json` 同量级；
产物结构可被前端消费（spec §9 验收标准 3）

- [ ] **Step 3: 核对验收标准**

逐条确认 spec §9：

1. 五个测试文件全绿，且 `verification.py` / `quality.py` 等纯函数模块未进 diff
2. 真实输入在本分支产出通过三层校验的产物
3. manifest 的 `usage` / `attempts` 字段结构与 `main` 一致
4. §6 四条补偿：补偿 1 → `test_chat.py` 第 5–6 项；补偿 2 → 第 7–9 项；
   补偿 3 → 第 2–3 项；补偿 4 → 第 4 项

- [ ] **Step 4: 提交验收记录**

把实跑结论追加到 `docs/specs/2026-10-10-langchain-langgraph-refactor-design.md`
末尾的「验收记录」小节（新增），然后：

```bash
git add docs/specs/2026-10-10-langchain-langgraph-refactor-design.md
git commit -m "验收记录：LangChain / LangGraph 改造实跑结论"
```

---

## 学习路径提示

按任务顺序做下来，覆盖的框架概念依次是：

| 任务 | 概念 |
|---|---|
| 1 | `BaseChatModel` 的最小实现契约（`_generate` / `_llm_type` / `bind_tools`） |
| 2 | `Runnable` 组合、`BaseCallbackHandler`、`usage_metadata` 的标准化形状 |
| 2/4 | `with_retry` 的异常过滤与退避；为什么 `with_fallbacks` 在这里不够用（它只按异常类型匹配，会把无关的 400 一起降级） |
| 6 | `@tool`、`args_schema`、`InjectedState`、`InjectedToolCallId`、`Command` 写状态 |
| 7 | `StateGraph`、`TypedDict` 状态、`add_messages` reducer、条件边、闭包 vs 状态的边界 |
| 8 | `ToolNode`、工具循环、`recursion_limit` 与自己维护步数上限的区别 |
