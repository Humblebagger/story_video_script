# 后端对用户文字统一中英双语 设计

日期：2026-11-13
状态：已过设计审查（Opus），修订完毕，待写计划

## 1. 目标与已决事项

- 后端产出、会出现在界面或下载文件里的文字，全部做成中英双语。
- 只给大模型看的提示词、内部调试日志、代码注释不动。
- 机制：
  - 后端返回「消息对象」：代码 + 参数 + 中文兜底；
  - 写进会话文件、任务记录的也是消息对象；
  - 前端按当前界面语言渲染，文案集中在 `frontend/src/i18n/zh.ts` 与 `en.ts`；
  - 切换语言后，已存的失败原因跟着变。
- 下载文件（导出剪辑工程 zip 内的 README）由后端按请求语言生成。不带 `lang` 时继续中英并排。
- 验证报告逐条做双语，排在最后一个子计划。

## 2. 现状调研

### 2.1 后端会到达用户的中文（raise/HTTPException 含中文字面量的行数）

| 模块 | 数量 | 主要类别 |
|---|---|---|
| server/app.py | 48 处 HTTPException + 48 处 raise | 接口错误（未登录、无权限、job 不存在、未知参数、本章无原文、月上限、验证门……） |
| server/novels.py | 25 | 接口错误 |
| server/auth.py | 10 | 接口错误 |
| server/admin.py | 8 | 接口错误；version.error（:182） |
| server/library.py、pricing.py、store.py、usage.py | 5、3、1、1 | 接口错误；library/pricing 抛普通 ValueError（library.py:88、pricing.py:42） |
| render/session.py | 9，另有 3 处写 error | 接口错误；**持久化错误**（INTERRUPTED_SUBMIT、超出单章上限）；合成 step 进度文字（:654/:676） |
| render/free.py | 17 + 1 | 接口错误、持久化错误 |
| render/runner.py | 若干 | 持久化错误。拼接内层原因：:176 的「厂商暂时不可达，正在重试：{e}」、:198 的「多次查询都失败……{e}」、:246-248、:253；提交不明提示含 console_name |
| render/compose.py | 9 | Stale/FreeInvalid |
| render/providers/* | minimax 25、seedance 15、fake 5、tts_volc 3、tts_base 1、`__init__` 2 | ProviderError/AmbiguousSubmit 文案；TaskState.error（minimax.py:356-362）；rate_note；console_name |
| render/mix.py、voice.py、export_fcpxml.py | 5、1、6 | 接口错误；合成 step 文字（mix.py:361/405/414/418）；报告 warning（:367 拼内层）与 alignment（:378）；说话人名「旁白」「（未标说话人）」（voice.py:61）；导出 README |
| assistant/* | edits 30、actions 5、tools 5、graph 1；events.py | UndoError；SSE error 事件（events.py:88，app.py:1587）；TOO_MANY（events.py:86，混在 token 流里）与 INTERRUPTED；失败卡 error 与 tool_end summary（events.py:41-43/82）；编辑卡 diff target「全书梗概」（edits.py:277/287）与 warnings |
| pipeline/* | repair 14、convert 4、review 3、chat 3 等 | 多数给模型，见 §2.3；ConversionError 经 app.py:277 拼 report 进 job.error |

此外还有以下几处：
- **任务记录**：job.log/last_log 是转换进度（JobPanel 与任务列表展示）；quality_report（app.py:262，JobPanel 展示）。
- **验证门**：gate.message（app.py:946-954）。
- **带附加字段的 detail**：验证门 verification（app.py:709）、expected_cny（app.py:856，前端 conflictCny 在读）、tts_cny（app.py:1260）。

### 2.2 前端如何显示后端错误

- `api.ts` 的 `send()` 取 `detail`：字符串原样显示，对象取 `.message`。抛出 `ApiError` 时，`message` 已按当时语言定死。各组件的 `setError(e.message)` 存的也是字符串。
- 会话错误：FilmPanel、NodeCards、ComposePanel 直接显示 `error` 字符串。
- 版本错误：App.tsx:503 读取 version.error。
- 合成进度：前端 `compose.ts:55` 显示后端 step 文字。
- 合成报告：ComposePanel:207 显示 alignment。
- 助手确认卡：已结构化，标签由前端翻译（ActionCard.tsx:36），不需要改。
- i18n 核心 `core.ts`：
  - `translate` 用 `{name}` 插值；
  - 缺译时先回落中文，再回落键名；
  - en 包由 `Messages` 类型强制与 zh 结构一致。
- 已有语言传递：只有助手 body 的 `lang`（app.py:1540）。

### 2.3 不动的部分

- 给模型的文字：
  - `pipeline/prompt.py`；
  - `repair.py` 的补丁错误（回喂模型重试）；
  - `review.py` 的审查提示；
  - 助手工具返回给模型的 ToolMessage 文字。
- 字幕：内容是台词，不翻译。
- `mix_report.json` 的 notes：已经是结构化数据。
- 内部调试日志：转换过程的详细日志另存一份，不翻译（§3.6）。

## 3. 消息对象与载荷

### 3.1 消息对象

```json
{"code": "film.provider.retrying", "params": {"cause": {"code": "film.minimax.overloaded"}}, "message": "厂商暂时不可达，正在重试：MiniMax 服务繁忙"}
```

| 字段 | 说明 |
|---|---|
| `code` | 必填，规则见 §4 |
| `params` | 可选，值的类型见下 |
| `message` | 中文兜底，后端照旧生成。用于旧前端、缺译、日志和测试失败时阅读。前端只在没有译文时才用 |

`params` 的值允许以下几种类型（解决原因嵌套与金额问题）：

| 类型 | 写法 | 前端渲染 |
|---|---|---|
| 字符串、数字 | 原样 | 原样插值 |
| 嵌套消息 | `{"code":…,"params":…}` | 递归渲染，用于内层原因 |
| 列表 | `[…]` | 逐项渲染后，按语言用顿号或逗号连接 |
| 金额 | `{"t":"money","cny":12.3}` | 用现有 `money.*` 按语言格式化 |
| 代码引用 | `{"t":"ref","code":"console.minimax"}` | 渲染为该代码的译文，例如控制台名 |
| 厂商原文 | `{"t":"vendor","text":"…"}` | 原样显示，不翻译。后端写入前已经过 `scrub` 脱敏并截断到 300 字 |

前端靠 `t` 字段识别带类型的值；带 `code` 且没有 `t` 的对象就是嵌套消息。

### 3.2 HTTP 错误

- 已改造的接口：`detail` 为消息对象。原有的附加字段（`verification`、`expected_cny`、`tts_cny`）放在同一对象里，名字和含义都不变。
- 未改造的接口：继续返回字符串 `detail`，行为与现在一致。
- 前端遇到字符串 `detail` 原样显示。所以每个子计划可以只改自己的模块，独立交付（见 §5.3）。

### 3.3 持久化错误（单字段）

会话里的段、尝试、自由节点，以及任务记录 job、版本 version：
- 新增**一个字段** `error_msg`，内容为 `{code, params}`；
- `error` 字段保留，写中文兜底。

`session.py` 提供 `set_error(obj, msg_or_exc)` 和 `copy_error(dst, src)`，统一写入、复制 `error` 与 `error_msg`。需要改用它们的复制点：
- `session.py:217`：重建时继承旧段失败；
- `session.py:494`：尝试失败复制到段；
- `session.py:600`；
- `free`、`job` 的同类复制。

读取时有 `error_msg` 就按代码渲染，没有（旧数据）就原样显示 `error`。旧文件不迁移。

### 3.4 厂商任务状态

- `TaskState` 新增字段 `error_msg: Optional[dict]`。
- `error` 仍是中文兜底（含厂商原文）。

各环节的改法：
- **厂商**（minimax.py:356-362，seedance 同理）：任务失败时，`error_msg` 填代码；厂商原文作为 `vendor` 参数附带。
- **session**：`poll_update` 和 `note_error`（session.py:492/499）改为接收消息对象或字符串，通过 `set_error` 写入。
- **runner 拼内层原因**（:176/:198/:246-248/:253）：改为外层代码，外加 `cause` 嵌套消息。

### 3.5 说明文字与进度文字

以下几项改为消息对象，视图接口里对应的字段直接换成对象：
- **费率说明**：`rate_note` 为 `{code:"rate.minimax", params:{…}}`。
- **控制台名**：`console_name` 为代码引用 `console.ark`、`console.minimax`。
- **合成进度**：step 文字（session.py:654/676；mix.py:361/405/414/418）改为消息对象。前端 compose.ts:55 改用 `formatMsg`。
- **合成报告**：`warning` 与 `alignment` 改为消息对象。mix.py:367 的内层原因走 `cause`。
- **说话人名**：「旁白」「（未标说话人）」（voice.py:61）改为代码 `voice.narrator`、`voice.unlabeled`。存储里的说话人 id 不变，只在显示时翻译。
- **验证门**：gate.message（app.py:946-954）改为消息对象。

### 3.6 转换任务的进度与报告（子计划 4）

- **进度**：`job.log`/`last_log` 改为结构化事件列表 `[{code, params, at}]`。JobPanel 和任务列表用 `formatMsg` 渲染。
- **调试日志**：详细调试日志另存在 `job.debug_log`，不翻译，只给开发排查。
- **失败**：`ConversionError`、`LLMError` 带代码；app.py:277 原来是 `f"{e}\n{e.report}"`，改为 `error_msg` 加 `report` 参数。`report` 内是逐条验证结果，按 §3.7 渲染。
- **质量报告**：quality_report（app.py:262）的汇总句改为消息对象。

### 3.7 验证报告逐条（子计划 5）

- 每条 Finding 已有 `rule_id`（verification.py:22），直接用作代码，例如 `verify.rule.SCHEMA-001`；各规则的参数改为结构化。
- `SCHEMA-001` 的 jsonschema 原文，作为 `vendor` 类型参数原样显示。
- 回喂模型的仍是原来的中文 message。同一处生成两份，互不影响。

## 4. 代码命名与登记

- **命名格式**：`<域>.<子域>.<名称>`。
  - 域包括：`auth`、`novel`、`chapter`、`admin`、`usage`、`library`、`job`、`film`、`tts`、`compose`、`voice`、`export`、`assistant`、`verify`、`console`、`rate`、`common`。
  - 跨厂商的放在 `film.provider.*`，厂商专属的放在 `film.<provider>.*`。
- **叶子与前缀**：同一个代码不能既是叶子又是别的代码的前缀，否则 `srv` 对象树无法同时容纳字符串和子节点。登记时检查。
- **登记处**：集中在 `backend/server/messages.py`。
  - 每个代码登记三项：代码名、参数名列表、中文兜底模板。
  - `msg()` 遇到未登记的代码就抛错。
  - 登记表导出到 `backend/server/messages_codes.json`。后端测试校验这份 JSON 是最新的。
- **前端文案**：放在 `zh.ts`/`en.ts` 的顶层 `srv` 节点，路径与代码一致。
  - 代码是运行时从后端来的，`MsgKey` 的编译期检查管不到这里。正确性由 §9 的 JSON 校验保证。
  - en 与 zh 的结构一致性仍由 `Messages` 类型强制。
- **兜底代码**：`common.unknown` 的模板是 `{message}`，中英两种语言都直接显示原文。

## 5. 后端改法

### 5.1 公共函数

`messages.py` 提供：
- `msg(code, **params)`：返回消息对象。
- `UserError`：一个 mixin，带 `code`、`params`、`msg()` 三个属性。

### 5.2 异常类兼容

- **继承关系**：替换后的异常类继承原来的类型，同时混入 `UserError`。
  - 例如 library、pricing、usage 原本抛 `ValueError`，替换后的类仍是 `ValueError` 的子类。这样 app.py:158/741/1758/1832 的 `except ValueError` 照样接得住。
  - `ProviderError`、`SessionError` 及子类、`FreeInvalid`、`Stale`、`NovelError`、`AuthError`、`AdminError`、`MixError`、`VoiceError`、`ExportError`、`UndoError`、`ConversionError`、`LLMError` 一律只加 mixin。
  - 这些类的 `str()` 行为都不变。
- **脱敏**：`_hide_root(str(e))`（app.py:1299/1730）对 `params` 里的字符串一并做路径脱敏。

### 5.3 接口转换（逐子计划推进）

- 新增 `to_detail(e)`：
  - 异常带代码，就返回消息对象；
  - 不带代码，就**返回 `str(e)` 字符串**，和现在一样。
- 每个子计划只把**本模块**的调用点从 `HTTPException(s, str(e))` 改成 `HTTPException(s, detail=to_detail(e))`。未改的模块行为不变。

### 5.4 助手

- **确认卡**：已结构化，不改。
- **失败卡与 tool_end summary**：在 `_tool` 包装（tools.py:26）里截获带代码的异常，把消息对象写进 `ToolMessage.artifact`。ToolMessage 正文仍是给模型的中文。
  - 前端失败卡和 summary 优先读 `artifact` 渲染。
  - 历史从存档重建（events.py:101-143）时，同样读 `artifact`；旧存档没有 `artifact`，就显示原文字。
- **SSE 事件**：`error` 事件（events.py:88，app.py:1587）、`INTERRUPTED` 和 `TOO_MANY` 都改为事件里带消息对象。其中 `TOO_MANY` 原来混在 token 流里（events.py:86），改为单独的 `notice` 事件。
- **编辑卡**：
  - diff target 的内部值（如「全书梗概」，edits.py:277/287）**保持不变**，因为 `_ask_edit` 恢复时要比对它（edits.py:147），改了会让升级前没处理完的卡失效。前端显示时按已知值映射翻译。
  - 卡片 `warnings` 改为消息对象列表。

## 6. 前端改法

- **渲染入口**：新增 `frontend/src/i18n/serverMsg.ts`，提供 `formatMsg(m)`。
  - `m` 可以是字符串、消息对象或空值。
  - 递归处理嵌套消息、列表、`money`、`ref`、`vendor`。
  - 缺译时依次回落：中文译文 → `message` → 代码名。
- **ApiError**：保存原始 `detail`；`message` 只作兜底。
  - 组件不再存 `e.message` 字符串，改存 `e.detail`（或整个错误），渲染时调用 `formatMsg`。这样切换语言后，已经显示的错误也会跟着变。
  - toast 是即时的，在弹出时格式化即可。
- **显示处统一改用 `formatMsg`**：
  - 会话错误（FilmPanel、NodeCards、ComposePanel）；
  - 版本错误（App.tsx:503）；
  - 合成进度（compose.ts:55）与报告（ComposePanel:207）；
  - JobPanel 的进度与质量报告；
  - 助手失败卡与 summary；
  - rate_note、console_name、说话人名、验证门、验证面板。

## 7. 下载文件按语言生成

- **范围**：唯一需要按语言生成的下载是导出剪辑工程 zip。前端用 fetch 拿 blob（api.ts:453），没有 `<a href>` 直链。
  - 字幕是台词，不翻译。
  - 没有单独的「生产包、合成报告下载」接口，原稿写的这一条删去。
- **请求**：导出请求带 `?lang=zh|en`，取当前界面语言。缺省或非法值时 README 保持中英并排（已决）。
- **README**：带 `lang` 时只出对应语言的一段。
- **文件名**：export_fcpxml.py:238 现在固定写 `export/{safe}.zip`，中英两种语言并发导出会互相覆盖。改为 `export/{safe}.{lang}.zip`，不带 `lang` 时为 `export/{safe}.zip`。

## 8. 测试

- **后端断言**：断言 `code` 和关键 `params`，不再断言中文文字。现有断言中文的用例，随各子计划按模块改。
- **ast 扫描**：每个子计划用 ast 扫描本模块，以下情况计为遗漏：
  - `raise X(…)`、`HTTPException(…)`、`error=`、`note_error(…)`、`say(…)` 和报告字段赋值中，出现中文字面量、f-string、字符串拼接，或引用含中文的模块常量（INTERRUPTED_SUBMIT、_EXPORT_REASONS、TOO_MANY 等）。

  **白名单**：行尾注释 `# i18n: internal`（内部 ValueError，例如 export_fcpxml.py:86）和 `# i18n: llm`（回喂模型的文字）可以豁免。扫描结果要清零。
- **代码一致性**：新增 `frontend/tests/srv-codes.test.ts`，加入 package.json 的测试脚本串。它读取 `backend/server/messages_codes.json`，逐个确认：
  - `zh.ts` 的 `srv.*` 都有对应键；
  - 模板里出现的 `{x}` 都在参数列表里；
  - 没有多余的键。

  en 由类型保证与 zh 一致，不重复校验。
- **前端单测**：
  - `formatMsg`：字符串、各种参数类型、嵌套、缺译回落；
  - 各显示处至少各有一条用代码渲染的用例；
  - 切换到英文后，已存的错误和已显示的接口错误都跟着变。
- **持久化**：`set_error`/`copy_error` 在重建、尝试复制到段等路径上不丢 `error_msg`。

## 9. 子计划与实施顺序

1. **基础设施 + 出片与厂商**：
   - 基础设施：`messages.py`、`UserError`、`to_detail`、`formatMsg`、ApiError 改存 detail、`srv-codes` 校验。
   - 出片：render 下的 session、free、runner、compose；视频厂商（MiniMax、Seedance、fake）；TaskState.error_msg、set_error/copy_error、rate_note、console_name。
   - 前端：出片相关的显示处；app.py 中出片接口的调用点（含 expected_cny）。
2. **配音合成与导出**：
   - mix、voice、TTS 厂商；
   - 合成 step 与报告（warning、alignment）、说话人名；
   - export_fcpxml、`?lang`、README、导出文件名；
   - 对应接口（含 tts_cny）。
3. **账号、小说与管理**：auth、novels、library、admin、usage、pricing、store，以及对应接口和 version.error。
4. **转换任务与助手**：
   - 转换任务：job 进度改为结构化事件、debug_log、ConversionError/LLMError、quality_report、验证门 gate.message。
   - 助手：artifact、SSE 事件、notice、编辑卡 warnings、target 显示映射。
5. **验证报告逐条**：rule_id 作代码、结构化参数、验证面板渲染。

每个子计划可以独立交付：
- 未改的接口继续返回字符串，前端原样显示；
- 一致性校验只看已登记的代码。

## 10. 风险

- **漏改**：抛错点分散。靠 §8 的 ast 扫描（含白名单）逐个模块清零。未带代码的异常仍返回字符串，不会出现错误的译文。
- **持久化**：session.json 体积略增。旧数据不迁移，显示时兼容。
- **指纹**：错误字段不进片段指纹。实现时要确认 `fingerprint` 的输入没变，已出片段不会因此变成过期。
- **测试改动量大**：按子计划、按模块逐步改。
- **英文质量**：译文由实现者初拟，海外上线前建议用户或母语者过一遍 `srv` 节点。

## 11. 已决事项（原开放问题）

1. 验证报告逐条做双语，排在最后一个子计划（子计划 5）。
2. 导出 README 在不带 `lang` 时继续中英并排。

## 审查修订记录（Opus 设计审查）

- **C1**：§3.1 的 params 改为允许嵌套消息（cause）、列表、金额（`t:"money"`）、代码引用（`t:"ref"`）、厂商原文（`t:"vendor"`）。formatMsg 递归渲染，前端靠 `t` 字段识别。runner、mix、app.py:277 的内层原因都改走 `cause`。
- **C2**：§5.3 的 to_detail 对不带代码的异常返回字符串，每个子计划只改本模块的调用点。`common.unknown` 的模板改为 `{message}`。
- **C3**：§3.4 给 TaskState 加 `error_msg`。厂商、`poll_update`、`note_error` 改为接收消息对象。
- **I1**：§3.3 改为单字段 `error_msg`，新增 `set_error`/`copy_error`，在 session.py:217/494/600 等复制点使用，并补测试。
- **I2**：§2.1、§3.5、§3.6 补全遗漏项：合成 step 进度、alignment、说话人名、version.error、quality_report、job.log（改为结构化事件，调试日志另存）、验证门 gate.message、助手 SSE 的 error/TOO_MANY/INTERRUPTED、编辑卡 target 与 warnings、detail 附加字段 expected_cny 与 tts_cny。
- **I3**：§5.4 重写助手部分。确认卡不改；失败卡和 summary 走 ToolMessage.artifact，旧存档显示原字符串；diff target 内部值不变，只在前端显示时翻译。
- **I4**：§5.2 替换的异常类继承原类型并混入 UserError，`except ValueError` 不受影响；`_hide_root` 对 params 一并脱敏。
- **I5**：§7 更正为只有 export.zip 一个下载；字幕不翻译；删去不存在的「生产包、合成报告下载」接口；导出文件名带 lang，避免并发覆盖。
- **Minor**：
  - ApiError 改存 detail，渲染时再格式化；
  - ast 规则补上 f-string、拼接、模块常量和非 raise 写入，并加白名单注释；
  - §4 更正：srv 键不受 MsgKey 编译期检查，由 JSON 校验保证；JSON 校验以后端对 zh 和参数名为重点；
  - 测试文件改为 `frontend/tests/srv-codes.test.ts` 并加入测试脚本；
  - 规定代码不能既是叶子又是前缀；
  - 验证报告用 rule_id 作代码，SCHEMA-001 的 jsonschema 原文作 vendor 参数原样显示。
- **用户已决**：验证报告逐条做双语，排在最后；README 不带 lang 时继续中英并排。
- **子计划调整**：由原来的 5 个重排为现在的 5 个。job 进度并入子计划 4，与助手一起做；验证报告逐条单独作为子计划 5。
