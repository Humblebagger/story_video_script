# LangChain / LangGraph 改造设计

日期：2026-10-10　分支：`langchain`　状态：已评审通过

## 1. 目标与非目标

**目标**：把后端 LLM 调用层与单批重试循环，从自研实现改造成 LangChain + LangGraph
实现。首要动机是学习框架，因此宁可多暴露框架概念（Runnable、callbacks、StateGraph、
ToolNode、InjectedState），也不追求最小改动量。

**非目标**（明确不做）：

- 不动确定性审查链路。schema 校验、逐字保真、覆盖率、质量门全部留在纯 Python
  函数里。它们是产品价值所在，不能因为"框架里有个 LLM 评审节点"就挪进 LLM 手上。
- 不接 LangSmith。提示词与小说原文不外发，可观测性用本地回调实现。
- 不做多批并发。切批/汇总仍是串行纯函数，`Send` API 留给以后。
- 不在 `main` 上改。`main` 保留自研实现，两条分支可用同一份输入做 A/B 对照。

## 2. 决策记录

| # | 决策 | 结论 | 理由 |
|---|---|---|---|
| D1 | 旧实现去向 | 新建 `langchain` 分支，`main` 原样保留 | 保住唯一能跑的产线，同时留下 A/B 对照 |
| D2 | LangGraph 边界 | 只包单批内循环（`_convert_batch`） | 切批/汇总/manifest 是纯函数，包成节点只多一层壳 |
| D3 | 模型交互契约 | 混合：生成走文本 JSON，修复走原生 tool calling | 分镜 schema 36KB，塞进 `with_structured_output` 更脆且烧 token；6 个修复工具小而明确，正是 ToolNode 的典型场景 |
| D4 | Python 环境 | `brew install python@3.12`，重建 `backend/.venv` | LangChain 1.x / LangGraph 要求 ≥3.10；`Dockerfile` 早已是 `python:3.12-slim`，本地只是对齐 |
| D5 | 目录结构 | 原地替换，不新开 `pipeline/lc/` 子包 | 分支本身已是隔离层；再套一层会让 `convert.py` 出现两条平行路径 |
| D6 | 踩坑补偿 | 四条全保（见 §6） | 代码会比教科书写法脏，但那些坑是实测踩过的 |

## 3. 不动的模块

以下文件本次改造**不应出现在 diff 里**（除 import 调整）：

`verification.py`、`validate.py`、`quality.py`、`splitter.py`、`source_units.py`、
`manifest.py`、`prompt.py`、`schema/storyboard.schema.json`、
`prompts/novel_to_storyboard.md`、`repair.py` 中的工具实现函数
（`source_read` / `asset_get` / `validation_list` / `coverage_query` /
`apply_tool_call` 的补丁校验逻辑）。

`convert_text()` 的外壳同样不动：输入归一化、切批、冻结句单元、续批资产块、
批次落盘、合并、整章终检、manifest 收尾。

## 4. 改造的三块

| 现有 | 改造后 | 框架概念 |
|---|---|---|
| `pipeline/llm.py` 的 `LLMClient` | `pipeline/chat.py` | `ChatAnthropic`、`.with_retry()`、`BaseCallbackHandler` |
| `pipeline/convert.py` 的 `_convert_batch` for 循环 | `pipeline/graph.py` | `StateGraph`、条件边、`recursion_limit` |
| `repair.py` 的 `{"tool": ...}` 文本协议 | `pipeline/tools.py` | `@tool`、`bind_tools`、`ToolNode`、`InjectedState` |

### 4.1 `chat.py`

```python
def build_chat_model(settings: Settings) -> BaseChatModel
```

返回配好 `model` / `max_tokens` / `temperature` / `base_url` / `thinking` 的
`ChatAnthropic`，外面套 `.with_retry()` 承接瞬时传输故障
（`APIConnectionError` / `InternalServerError` / `RateLimitError` / `httpx.HTTPError`），
重试次数取 `settings.transport_retries`，指数退避。

system 提示词的 `cache_control: ephemeral` 缓存标记通过 `SystemMessage` 的
结构化 content block 保留——22KB 提示词每批都发，丢了缓存等于每批多付一次全价。

评审阶段的独立模型（`STORYBOARD_REVIEW_MODEL`）仍由同一个工厂构造：
`build_chat_model(replace(settings, model=settings.review_model))`，
与现在 `convert.py` 里构造第二个 `LLMClient` 的做法同形。两个模型共用同一个
`UsageCallback` 实例，保证评审调用的 token 也进同一本账。

`UsageCallback(BaseCallbackHandler)` 在 `on_llm_end` 里累计
`{input, output, cache_read, cache_write}`，并暴露与现有
`LLMClient.usage_totals()` **完全相同的字典结构**，使 `manifest.sum_usage` 与
`_usage_delta` 的前后差值归因逻辑一字不改。

### 4.2 `graph.py`

状态（`TypedDict`）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `messages` | `Annotated[list[AnyMessage], add_messages]` | 对话历史，修复轮由 reducer 累加 |
| `doc` | `dict \| None` | 当前底稿（上一次尝试的产物） |
| `batch_text` | `str` | 本批原文，保真校验的基准 |
| `idx` / `attempt` | `int` | 批号 / 第几次尝试 |
| `mode` | `"generate" \| "patch"` | 对应 `settings.repair_mode` 与"有无可打补丁的底稿" |
| `report` | `str` | 最近一次失败报告 |
| `structured` | `VerificationReport` | 最近一次结构化校验结果，修复工具要读 |
| `candidates` | `list[tuple]` | 软失败但结构合法的历次尝试，供择优降级 |
| `attempt_records` | `list[dict]` | 写进 manifest 的逐次尝试流水，字段与现在一致 |

节点与边：

```
                    ┌──────────┐
      ─────────────▶│ generate │  文本 JSON + 容错解析
     │              └────┬─────┘
     │                   ▼
     │              ┌──────────┐  纯函数节点，直接调现有 _check_batch
  rewrite 模式      │  check   │  → ok / hard_failed / soft_failed + 择优键
     │              └────┬─────┘
     │         ┌─────────┼──────────┐
     │      ok │   重试耗尽│      否则│
     │         ▼         ▼          ▼
     │       [END]  ┌─────────┐  ┌──────────────┐
     └──────────────│finalize │  │ plan_repair  │  按 mode 拼下一轮消息
                    └─────────┘  └──────┬───────┘
                   择优降级/抛错         │ patch 模式
                                        ▼
                                 ┌──────────────┐
                                 │ repair_agent │  bind_tools 出 tool_calls
                                 └──────┬───────┘
                                   ▲    ▼
                                   │ ┌───────┐
                                   └─│ tools │  ToolNode
                                     └───┬───┘
                            json_patch/task_done ──▶ 回 check
```

- `generate`：调模型输出整份 JSON，用容错解析（剥代码块围栏、取首 `{` 到末 `}`）得到 `doc`。
  解析失败记 `status: "unparseable"`，且因无底稿可打补丁，下一轮强制走 `generate`。
- `check`：**不调 LLM**。原样复用 `_check_batch(...)`，返回五元组
  `(ok, hard, report, key, structured)`。可选的 LLM 评审阶段仍在此节点内，
  由 `settings.review_enabled` 控制。
- `plan_repair`：`patch` 模式拼 `[user, assistant(当前doc), user(repair_request)]`；
  `rewrite` 模式追加"未通过自动校验，报告如下…重新输出完整 JSON"。
- `finalize`：`candidates` 非空且非 `strict` → 按择优键取最优一版降级交付并产出警告；
  否则落盘失败报告并抛 `ConversionError`。

择优键语义不变：`(1, -密度比)` < `(2, -超时比)` < `(3, 评审总分)`，越大越接近达标。

现有"单轮修复超过 8 个工具步骤"的上限，改由图的 `recursion_limit` 表达；
超限时与现在一样记为修复失败、进入下一次尝试。

### 4.3 `tools.py`

6 个 `@tool`，与 `repair.ALLOWED_TOOLS` 一一对应：
`source_read` / `asset_get` / `validation_list` / `coverage_query` /
`json_patch` / `task_done`。

**关键设计点**：工具要读当前 doc（36KB）和 `structured` 报告，但绝不能让模型
把它们当参数传。用 `InjectedState`：

```python
@tool
def source_read(unit_ids: list[str],
                state: Annotated[BatchState, InjectedState]) -> list[dict]:
    return repair.source_read(state["doc"], unit_ids)
```

模型只产出 `unit_ids` / `asset_ids` / `patch`，doc 与报告由运行时注入。

`json_patch` 保留 `repair.py` 现有的全部约束：只允许 `add` / `remove` / `replace`，
`/coverage` 与 `/meta` 前缀锁定（后处理结果与模型声明不可信，必须由程序重算）。
模型永远拿不到文件系统或任意代码执行。

## 5. 调用方改动

`convert.py` 里 `_convert_batch(...)` 的调用点替换为编译好的图：

```python
doc, batch_warnings = run_batch_graph(graph, state_in)
```

`run_review(llm, ...)` 的首参同样从鸭子类型换成 `BaseChatModel`；
它内部那次调用保持单次 `invoke`，不入图——评审是一次性打分，没有循环。

`convert_text()` 的 `llm=None` 注入口语义变化：原来注入"任何带
`complete(system, messages) -> str` 的对象"，改为注入 `BaseChatModel`。
这是本次改造唯一的对外接口变更，`server/app.py` 与 `pipeline/__main__.py`
不传 `llm`，故不受影响。

## 6. 四条踩坑补偿的对应实现

这些是现有 `llm.py` 里沉淀的实测补偿，改造后必须逐条有对应物：

1. **网关不认 `thinking` 参数 → 降级重试**。`ChatAnthropic` 无内建等价物。
   在 `chat.py` 保留一层包装：捕获 `BadRequestError` 且错误文本含 `thinking`
   时，去掉该参数重试一次，并打印一行说明（推理块会重新开始烧预算，必须让人知道）。
   被拒一次后本进程内不再发送。
2. **撞 `max_tokens` 且正文为空 → 报"推理块烧光预算"**。从
   `AIMessage.response_metadata["stop_reason"]` 与 content blocks 的
   `thinking` 字段重建该诊断。这条错误信息当初就是为了避免把人引向
   "调小 `STORYBOARD_BATCH_CHARS`"的死路（一个字正文都没产出时，膨胀的是推理块
   不是产物），退回成笼统的"输出被截断"等于把坑填回去。
3. **token 归因到每次尝试**。`UsageCallback` 累计 + 节点前后取差值，
   与现在 `_usage_delta(usage_before, _usage_snapshot(llm))` 语义一致，
   受限修复一轮内的多次调用仍一并计入该次尝试。
4. **`base_url` 走第三方网关**。`ChatAnthropic` 支持 `base_url`，配置项不变
   （`ANTHROPIC_BASE_URL`）。

## 7. 测试策略

- 纯函数测试（verification / quality / manifest / splitter / source_units）
  **一行不改**。它们不改还能全绿，正是分层正确的证据。
- LLM 相关测试的注入点从 `complete(system, messages) -> str` 的鸭子类型，
  换成 `BaseChatModel` 的 fake 实现（`GenericFakeChatModel` 子类），
  修复用例预设带 `tool_calls` 的 `AIMessage`。
- 补两个针对 §6 的单测：`thinking` 被拒后降级重试；`stop_reason == max_tokens`
  且正文为空时抛出带"推理块"字样的错误。
- 图本身补一个"硬失败 → 补丁修复 → 通过"的端到端离线用例，断言
  `attempt_records` 的 `mode` / `status` / `tools` 字段与改造前同形。

## 8. 环境与依赖

1. `brew install python@3.12`
2. 重建 `backend/.venv`（当前为 3.9.6，LangChain 1.x 跑不起来）
3. `backend/requirements.txt` 追加 `langchain`、`langchain-anthropic`、`langgraph`
4. `Dockerfile` 不改（已是 `python:3.12-slim`）

## 9. 验收标准

1. `backend/tests` 全绿，其中纯函数测试文件未被修改。
2. 同一份输入在 `main` 与 `langchain` 两条分支上都能产出通过三层校验
   （schema / lint / 逐字保真）的分镜 JSON。
3. manifest 的 `usage` 与 `attempts` 字段结构与 `main` 分支一致——前端
   `VerificationPanel` 等消费方不用改。
4. §6 四条补偿各有测试或实跑证据。

## 10. 风险与兜底

| 风险 | 影响 | 兜底 |
|---|---|---|
| 第三方网关（如 DeepSeek）对 `bind_tools` 的 `tool_calls` 支持不稳 | 修复阶段跑不通 | **本次改造最大的未验证风险**，需在分支上实测。兜底是修复阶段退回自研文本协议，图结构保留 |
| `recursion_limit` 与原"8 步"语义不完全等价 | 修复轮提前/延后中断 | 用离线用例固定步数边界行为 |
| LangChain 抽象吞掉错误细节 | 诊断信息变笼统，退回被框架掩盖的坑 | §6 的四条补偿全部带测试 |
| Python 3.12 下现有依赖行为变化 | 既有测试红 | 升级后先在 `main` 代码上跑一遍全量测试，确认是干净基线再动代码 |
