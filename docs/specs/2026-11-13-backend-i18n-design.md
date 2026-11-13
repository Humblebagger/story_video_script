# 后端对用户文字统一中英双语 设计

日期：2026-11-13　状态：待审查

## 1. 目标与已决事项

- 后端产出、会出现在界面或下载文件里的文字全部做成中英双语。
- 只给大模型看的提示词、内部日志、代码注释不动。
- 机制：
  - 后端返回「代码 + 参数」，例如 `{"code": "minimax.insufficient_balance", "params": {...}}`；
  - 写进会话文件、任务记录的也是代码 + 参数；
  - 前端按当前界面语言渲染，文案集中在 `frontend/src/i18n/zh.ts` 与 `en.ts`；
  - 切换语言后，已存的失败原因跟着变。
- 下载文件（导出包 README 等）由后端按请求语言生成。

## 2. 现状调研

### 2.1 后端会到达用户的中文（按模块，raise/HTTPException 含中文字面量的行数）

| 模块 | 数量 | 主要类别 |
|---|---|---|
| server/app.py | 48 处 HTTPException + 48 处 raise | 接口错误（未登录、无权限、job 不存在、未知参数、本章无原文、月上限、验证门……） |
| server/novels.py | 25 | 接口错误（NovelError/NotFound/Busy 经 app 转成 400/404/409） |
| server/auth.py | 10 | 接口错误（AuthError：注册登录） |
| server/admin.py | 8 | 接口错误（AdminError/NotFound） |
| server/library.py、pricing.py、store.py、usage.py | 5、3、1、1 | 接口错误 |
| render/session.py | 9 + 3 处写 error | 接口错误 + **持久化错误**（`INTERRUPTED_SUBMIT`、「超出单章上限，没有提交」写进 session.json 的段与尝试） |
| render/free.py | 17 + 1 | 接口错误（FreeInvalid 等）+ 持久化错误 |
| render/runner.py | 1 | 持久化错误（提交结果不明提示，含 `console_name`） |
| render/compose.py | 9 | Stale/FreeInvalid（落成段错误或接口 422） |
| render/providers/minimax.py、seedance.py、fake.py、tts_volc.py、tts_base.py、`__init__` | 25、15、5、3、1、2 | ProviderError/AmbiguousSubmit 文案，经 runner **持久化**进尝试；`rate_note`（说明文字）、`console_name` |
| render/mix.py、voice.py、export_fcpxml.py | 5、1、6 | 接口错误 + 合成报告 `warning`（说明文字）+ 导出 README（**下载文件**，已同时写中英两段） |
| assistant/edits.py、actions.py、tools.py、graph.py | 30、5、5、1 | UndoError 等经接口到用户；工具返回给模型的文字（见 §2.3） |
| pipeline/repair.py、convert.py、review.py、chat.py、prompt.py、novel_memory.py | 14、4、3、3、1、1 | 多数给模型或进 job 失败报告（见 §2.3） |

合计约 330 处。另有说明文字和下载文件：`rate_note`（每家厂商一段）、`console_name`、合成报告 `warning`、导出 README（已是中英两段并排）、`mix_report.json` 的 notes 已是结构化（kind/speed），不用改。

### 2.2 前端如何显示后端错误

- `frontend/src/api.ts` 的 `send()`：取响应 JSON 的 `detail`。
  - 字符串原样当 message；
  - 对象取 `detail.message`（`app.py:709` 验证门已用这种结构）；
  - `ApiError` 保留原始 `detail`。
- 会话里的错误：段与尝试的 `error`、自由节点的 `error`，由 `FilmPanel.tsx`、`NodeCards.tsx`、`ComposePanel.tsx` 直接显示字符串。
- i18n 核心 `frontend/src/i18n/core.ts`：
  - `translate(locale, key, vars)` 用 `{name}` 插值；
  - 缺译先回落中文、再回落键名；
  - `MsgKey` 由 `zh.ts` 结构推导，编译期校验键存在；
  - 非组件代码用 `tr()`。
- 已有语言传递：助手接口 body 带 `lang`（`app.py:1540`，只收 zh/en，缺省 zh）。其它请求不带语言。

### 2.3 pipeline 与助手里哪些不动

- 给模型的：
  - `pipeline/prompt.py`、`repair.py` 的补丁错误（回喂模型重试）；
  - `review.py` 的审查提示；
  - 助手工具返回给 LangGraph 的文字。

  这些不动。
- 会到用户的：
  - 转换失败 `ConversionError`：经 `app.py:277` 写进 `job["error"]`，前端任务面板显示；
  - `LLMError`：模型调用失败；
  - 助手撤销 `UndoError`、确认卡标题与按钮：由后端产出的卡片字段。

  这些都在范围内。
- 验证报告（lint/保真的逐条问题）：既回喂模型，又在验证面板展示。
  - 本次给每条加 `code` 与 `params`，界面用代码渲染；
  - 回喂模型的仍是原中文文字，同一处生成两份，互不影响。

## 3. 载荷格式

### 3.1 用户消息对象

```json
{"code": "film.minimax.insufficient_balance", "params": {"console": "minimax"}, "message": "MiniMax 账户余额不足……"}
```

- `code`：必填，见 §4 命名规则。
- `params`：可选，值只允许字符串或数字。
- `message`：中文兜底文字，后端照旧生成。作用有三：
  1. 旧前端或缺译时显示；
  2. 写日志；
  3. 测试失败时便于阅读。

  前端有翻译时不用它。

### 3.2 HTTP 错误

- `detail` 一律为上面的对象，`HTTPException(status, detail=msg(...))`。
- 已有带附加字段的（验证门 `verification`）照放在同一对象里。
- 兼容规则：前端遇到字符串 `detail`，按旧逻辑原样显示，这是滚动升级期和遗漏点的兜底。

### 3.3 持久化错误

- 会话文件的段、尝试、自由节点，以及任务记录 `job`：
  - 新增字段 `error_code`、`error_params`；
  - `error` 字段保留，写中文兜底文字。
- 读取时：
  - 有 `error_code` 就按代码渲染；
  - 没有（旧数据）就原样显示 `error`。
- 不迁移旧文件。

### 3.4 说明文字

- `rate_note`、`console_name`、合成报告 `warning` 改为代码 + 参数：
  - `rate_note` → `{"code": "rate.minimax", "params": {...}}`；
  - `console_name` → 代码 `console.ark` / `console.minimax`。
- 视图接口里的对应字段换成对象；前端渲染。

## 4. 代码命名与参数

- 格式：`<域>.<子域>.<名称>`，小写下划线。
  - 域：`auth`、`novel`、`chapter`、`admin`、`usage`、`library`、`job`、`film`（出片会话、段、自由节点、厂商）、`tts`、`compose`、`export`、`assistant`、`verify`、`common`。
  - 厂商错误放在 `film.<provider>.<name>`，跨厂商通用的放在 `film.provider.<name>`（如 `film.provider.ambiguous_submit`）。
- 后端代码清单集中在一个模块：`backend/server/messages.py`。
  - 为每个代码登记：代码名、参数名列表、中文兜底模板。
  - 后端只能用登记过的代码；`msg()` 遇到未登记代码就抛错，测试能发现。
- 参数插值与前端一致，用 `{name}`。数字由前端按语言格式化（金额沿用现有 `money.*`）。
- 前端文案放在 `zh.ts`/`en.ts` 的新顶层节点 `srv`，结构与代码路径一致，例如 `srv.film.minimax.insufficient_balance`。这样能沿用 `MsgKey` 编译期检查。

## 5. 后端怎么改

### 5.1 公共函数

`messages.py` 提供：
- `msg(code, **params) -> dict`：返回 §3.1 对象，`message` 由中文模板插值。
- `UserError(Exception)`：带 `code`、`params`，`str(e)` 为中文兜底。

### 5.2 现有异常类

以下这些类改为继承或包含 `UserError` 的字段（构造时传 `code`/`params`），`str()` 行为不变，现有 `except` 分支不受影响：
- `ProviderError`、`TransientError`、`AmbiguousSubmit`、`BilledError`；
- `SessionError` 及其子类、`FreeInvalid`、`Stale`；
- `NovelError`/`NotFound`/`Busy`、`AuthError`、`AdminError`；
- `MixError`、`VoiceError`、`ExportError`、`UndoError`、`ConversionError`、`LLMError`。

### 5.3 接口转换

`app.py` 里把 `HTTPException(code, str(e))` 统一换成 `HTTPException(code, detail=to_detail(e))`。
- 带 `code` 的异常取代码；
- 不带的（遗漏点）用 `common.unknown` 加 `message=str(e)`，前端显示兜底文字。

### 5.4 持久化写入

- `session.py` 记失败的函数改为接收异常或 `msg` 对象，同时写 `error`/`error_code`/`error_params`。
- 涉及：`settle`、提交中断、超出上限、`free` 的失败。
- runner 抓到的厂商异常直接传进去。

### 5.5 厂商原文

- 厂商返回的原始错误文字（已经过 `scrub` 脱敏、截 300 字）作为参数 `vendor` 附带，不翻译。
- 前端在译文后面原样显示，形如「余额不足（厂商原文：…）」。

## 6. 前端怎么改

- 新增 `frontend/src/i18n/serverMsg.ts`，提供 `formatMsg(m: {code, params?, message?} | string | null | undefined): string`：
  - 字符串原样返回；
  - 对象按 `srv.<code>` 查译文并插值；
  - 缺译回落顺序：中文译文 → `message` → 代码名。
- `api.ts`：`ApiError.message` 改为 `formatMsg(detail)`，所有 toast 和行内错误自动走新路径。
- 会话错误显示处（FilmPanel、NodeCards、ComposePanel、任务面板、助手卡片）改为调用 `formatMsg({code: error_code, params: error_params, message: error})`。
- `rate_note`、`console_name`、合成 `warning` 同样用 `formatMsg`。

## 7. 下载文件按语言生成

- 前端所有下载请求加查询参数 `?lang=zh|en`，取当前界面语言。缺省为 `zh`，非法值按 `zh`。
- 涉及：导出剪辑工程 zip、生产包、字幕、合成报告下载。
- 导出 README：
  - 现在中英两段并排；
  - 改为按 `lang` 只出对应语言一段，标题行与条目按语言给出；
  - `lang` 缺省时保留两段并排，兼容旧链接。
- `mix_report.json` 为结构化数据，不翻译。

## 8. 助手面板

- 模型回复：已按 `lang` 让模型用对应语言作答，不变。
- 后端产出的卡片字段改为代码 + 参数，前端渲染。卡片包括：
  - 确认卡标题、对比卡标签；
  - 撤销结果、任务卡状态文字；
  - 「金额对不上」等恢复失败原因。
- 助手工具返回给模型的文字不动。
- 同一事件既要给模型又要给界面时，分别生成。

## 9. 测试

- 后端：
  - 断言错误的 `code`（和关键 `params`），不再断言中文文字；
  - 现有断言中文的用例按模块随子计划改掉；
  - 每个子计划补「本模块所有抛错点都带代码」的检查：用 `ast` 扫本模块，`raise X("…")` 或 `HTTPException(…, "…")` 带字符串字面量的计为遗漏，清零为止。
- 代码清单一致性：新增自动校验 `tests/i18n/check_codes`，跑在前端 `npm test` 里。
  - 后端导出 `messages.py` 的代码清单为 JSON，即 `backend/server/messages_codes.json`。生成脚本在后端测试里校验清单是最新的。
  - 前端测试读这份 JSON，逐个确认 `zh.ts` 和 `en.ts` 的 `srv.*` 都有对应键，参数名一致（模板里出现的 `{x}` 都在参数列表里）。
- 前端：
  - `formatMsg` 单测，覆盖字符串、对象、缺译回落、厂商原文附带；
  - 各显示处至少一条用代码渲染的用例；
  - 切到英文后已存错误跟着变。

## 10. 子计划与实施顺序

1. **基础设施 + 出片与厂商**
   - `messages.py`、`UserError`、`to_detail`、`formatMsg`、`api.ts`、代码清单与一致性校验；
   - `render/` 下的 session、free、runner、compose、各厂商（含 MiniMax、Seedance、TTS），以及 rate_note、console_name、持久化错误字段；
   - 出片相关前端显示。

   用户刚接 MiniMax，先做这一块。
2. **配音合成与导出**：mix、voice、export_fcpxml、合成报告 warning、下载 `?lang`、README 按语言生成。
3. **账号、小说与管理**：auth、novels、library、admin、usage、pricing、store，以及 app.py 中对应接口的错误。
4. **转换任务与验证**：ConversionError、LLMError、job 错误、验证报告逐条加代码（回喂模型的文字不变）。
5. **助手面板**：edits、actions、tools、graph 里到达界面的文字与卡片字段。

每个子计划独立可交付：
- 没改到的模块仍返回字符串 `detail`，前端兜底显示；
- 一致性校验只检查已登记的代码。

## 11. 风险

- **漏改点**：抛错点分散。用 §9 的 `ast` 扫描逐模块清零，`to_detail` 对未带代码的异常兜底显示中文。
- **持久化字段增加**：`session.json` 体积略增。旧数据不迁移，只在显示时兼容。
- **指纹与过期判断**：错误字段不进片段指纹（现状如此），不会让已出片段变过期。实现时要确认不改动 `fingerprint` 的输入。
- **测试改动量大**：现有大量断言中文文字的用例要改成断言代码，按子计划随模块改，避免一次性大改。
- **英文质量**：译文由实现者初拟。上线海外前建议用户或母语者过一遍 `en.ts` 的 `srv` 节点。

## 12. 开放问题

1. 验证报告逐条翻译（子计划 4）条目多、技术性强，海外首发是否必须？
   - 建议：保留在范围内，排在后面；
   - 若想缩短工期，可先只翻译汇总句和问题类型，逐条细节暂显示中文。
2. 导出 README 在 `lang` 缺省时保留中英并排（兼容旧链接）。是否改为缺省英文？
   - 建议：保持并排。
