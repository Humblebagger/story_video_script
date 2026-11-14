# 后端对用户文字统一中英双语 设计

日期：2026-11-13
状态：已过设计审查（Opus），修订完毕；子计划 1、2、3、4 已交付；子计划 2、3、4、5 范围已补充（见文末）

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

## 子计划 2 范围补充（2026-11-13，子计划 1 验收后用户确认）

子计划 1 验收（Opus）留下两处缺口，用户同意并入子计划 2 一起做。§9 子计划 2 的原范围不变，另加下面两项。

### A. 方舟（Seedance）错误码友好映射

**现状**：
- `seedance._reject` 和 `poll` 把方舟的 `error.code` + `error.message` 原样拼起来，作为 `film.provider.rejected` 的 vendor 参数。用户看到的是英文厂商原文。
- `_call` 遇到 429 一律当瞬时错误重试。但方舟有一个 429 是不该重试的：`SetLimitExceeded`，即安全体验模式用量到顶、模型服务已暂停。现在遇到它会一直重试到放弃。其余 429（限流、过载、突增、`QuotaExceeded`）照旧重试。

**依据**：火山方舟官方错误码页 https://www.volcengine.com/docs/82379/1299023 （2026-11-13 用 curl 抓取核对）。参考页：
- https://www.volcengine.com/docs/82379/1099476
- BytePlus 版 https://docs.byteplus.com/docs/ModelArk/1299023

**映射表**：先按 `error.code` 全名匹配，再按第一个「.」之前的族名匹配，再按前缀 / 后缀规则（见表后）。都匹配不上时：
- 有 code 或 message：照旧走 `film.provider.rejected`，带脱敏后的厂商原文；
- 都没有：按 HTTP 状态回落（见表末）。

| 方舟 code（HTTP） | 含义（官方） | 我们的代码 | 中文兜底 | 可否重试 |
|---|---|---|---|---|
| `AuthenticationError`（401）、`InvalidSubscription`（401） | API Key 无效 / 订阅无效 | `film.ark.auth` | 视频服务（方舟）鉴权失败，请联系管理员 | 否 |
| `AccountOverdueError`（403）、`OperationDenied.ServiceOverdue` | 账号欠费 | `film.ark.overdue` | 视频服务（方舟）账户欠费，暂时无法出片，请联系管理员 | 否 |
| `AccessDenied`（403）、`InvalidAccountStatus`（403）、`OperationDenied.PermissionDenied` | 无权访问 / 账号异常 | `film.ark.access_denied` | 视频服务（方舟）拒绝访问，请联系管理员 | 否 |
| `InvalidEndpointOrModel` 族（404，含 `.NotFound`、`.ModelIDAccessDisabled`）、`ModelNotOpen`（404）、`OperationDenied.ServiceNotOpen`、`InvalidEndpoint.ClosedEndpoint` | 模型不存在、未开通、无权用或接入点已关闭 | `film.ark.model_unavailable` | 所选的视频档位暂时不可用（模型未开通），请换一个档位或联系管理员 | 否 |
| `SetLimitExceeded`（**429**） | 达到设定用量上限，模型服务已暂停 | `film.ark.limit_paused` | 视频服务（方舟）已达到用量上限并暂停，请联系管理员 | **否**（429 里唯一不重试的） |
| `QuotaExceeded` 族（**429**；官方页同名码还覆盖免费额度耗尽、排队任务过多、5 小时 / 周 / 月额度） | 额度不足或排队已满 | `film.ark.quota` | 额度不足或排队已满，持续失败请联系管理员 | **是**（429 与明确拒绝的 4xx 为 `TransientError`；5xx 与查询返回 failed 不在此列，见下） |
| `RateLimitExceeded` 族（429，含 `.EndpointRPMExceeded`、`.EndpointTPMExceeded`、`.EndpointFlexTPMExceeded`）、`ServerOverloaded`（429）、`RequestBurstTooFast`（429） | 限流、过载、突增 | `film.ark.throttled`（已有，改文案） | 视频服务（方舟）繁忙 | 是（瞬时） |
| `SensitiveContentDetected` 族（400，含 `.SevereViolation`、`.Violence`、`.PrivacyInformation`、`.DeepFake`）、`Input*SensitiveContentDetected` 族、`Input*RiskDetection`（按前缀 / 后缀） | 输入文本或图片可能违规 | `film.ark.input_moderated` | 这一段的画面描述或参考图没通过内容审核：改写描述或换参考图后重试 | 否 |
| 以 `.PolicyViolation` 结尾、族名不以 `Output` 开头（`SensitiveContentDetected.PolicyViolation`、`Input*…PolicyViolation`） | 输入可能涉及版权限制 | `film.ark.copyright` | 这一段的描述可能涉及版权限制：改写后重试 | 否 |
| 以 `.PolicyViolation` 结尾、族名以 `Output` 开头 | 生成结果可能涉及版权限制 | `film.ark.output_copyright` | 生成的视频可能涉及版权限制：调整这一段的描述后重试 | 否 |
| `Output*SensitiveContentDetected`、`Output*RiskDetection`（按前缀 / 后缀） | 生成结果没过审核 | `film.ark.output_moderated` | 生成的视频没通过内容审核：调整这一段的描述后重试 | 否 |

- **匹配顺序**：
  1. 全名（`OperationDenied.ServiceNotOpen`、`OperationDenied.ServiceOverdue`、`OperationDenied.PermissionDenied`、`InvalidEndpoint.ClosedEndpoint`）；`OperationDenied`、`InvalidEndpoint` 两个族的其它码不映射。
  2. 后缀 `.PolicyViolation`：族名以 `Output` 开头 → `output_copyright`，否则 → `copyright`。必须先于族名，否则族名会把它归到审核。
  3. 族名（第一个「.」之前）查表。
  4. 族名前缀 / 后缀：以 `SensitiveContentDetected` 或 `RiskDetection` 结尾时，`Output` 开头 → `output_moderated`，`Input` 开头或就是 `SensitiveContentDetected` → `input_moderated`。不必把每个变体都列出来。
- **HTTP 回落**：没有 code 时用。
  - 401 → `film.ark.auth`
  - 403 → `film.ark.access_denied`
  - 其它照旧：`film.provider.http_rejected`，带脱敏的响应体。
- **InvalidParameter、MissingParameter 不映射**：仍走 `film.provider.rejected` 带厂商原文。参数错误多半是我们的 bug，原文最有用。
- **作用范围**：
  - `_reject`（提交、查询的 4xx）；
  - `_call` 的 429 分支：先解析 code；`SetLimitExceeded` 抛 `ProviderError`；`QuotaExceeded` 抛 `TransientError.of("film.ark.quota")`；其余 429（含鉴权、审核等不该出现在 429 的码）一律照旧 `TransientError.of("film.ark.throttled")`。提交时 429 照旧可重试，因为方舟没有受理。
  - `QuotaExceeded` 在 429 与其它明确拒绝的 4xx（`_reject` 里命中时同样抛 `TransientError`）可重试；5xx 保持原行为（提交 `AmbiguousSubmit`、查询 `film.ark.unavailable`，不自动重提）；查询返回 `status=failed` 且 code 为 `QuotaExceeded` 仍是终态失败，`error_msg` 为 `film.ark.quota`，不重试不重提。可重试路径重试用尽后由 runner 的 `film.submit.unavailable` 嵌套它作原因。
  - `poll` 里 `status=failed` 的 `error.code`：输出审核这类错误多在这里出现。
- **原文去向**：命中映射时，界面只显示友好文案，不再带厂商原文。脱敏后的 `code: message` 写进后端日志，用 `logging.getLogger("render.providers.seedance").warning`。这样与 MiniMax 已知错误码不带原文的做法一致。
- **日志要能定位问题**：方舟的每条映射日志带上 HTTP 状态（查询失败写 `task`）、任务 id（查询时）、方舟请求 id（响应头 `X-Request-Id`，取不到写 `-`）、档位（提交时的 `model`）。runner 在段失败（`ProviderError`）时另记一条 WARNING，带会话目录（`root`）与段 id；`runner._submit` 的意外异常分支（runner.py:279 附近）用 `log.exception` 记完整堆栈。
- **中文兜底**：持久化的 `error` 字段改为映射后模板渲染出的中文，不再是厂商原文。未命中映射时保持原样。

### B. 面向最终用户的文案

产品要上架给别人用。最终用户不碰 `backend/.env`、不认识环境变量名、异常类名和内部档位 id。

**原则**：
- 界面文案只说发生了什么、用户能做什么（重试、换档位、改描述、联系管理员）。
- 开发细节（环境变量名、异常类名、内部 id）写进后端日志（`logging.getLogger(<模块>).warning`）。日志里同样不得出现密钥。

**受影响的代码与新文案**：
- 中文兜底一律改，英文同步改。
- 被拿掉的参数从模板里删除，登记表随之更新，`messages_codes.json` 重新生成。
- 前端 `srv` 节点同步改。

| 代码 | 现文案 | 新文案（中文兜底） | 拿掉的参数 → 去向 |
|---|---|---|---|
| `film.ark.no_key` | 没有配置方舟密钥：在 backend/.env 写 ARK_API_KEY=… | 视频服务（方舟）还没有配置，请联系管理员 | —（日志写明缺 `ARK_API_KEY`） |
| `film.minimax.no_key` | 没有配置 MiniMax 密钥：在 backend/.env 写 MINIMAX_API_KEY=… | 视频服务（MiniMax）还没有配置，请联系管理员 | —（日志写明缺 `MINIMAX_API_KEY`） |
| `film.minimax.invalid_key` | MiniMax 密钥无效（1004），检查 MINIMAX_API_KEY | 视频服务（MiniMax）鉴权失败，请联系管理员 | — |
| `film.minimax.insufficient_balance` | MiniMax 账户余额不足（1008），充值后重新出这一段 | 视频服务（MiniMax）账户余额不足，暂时无法出片，请联系管理员 | — |
| `film.minimax.moderated` | 内容被 MiniMax 审核拦下（1026）：… | 这一段的画面描述或参考图没通过内容审核：改写描述或换参考图后重试 | —（去掉厂商码 1026） |
| `film.ark.unknown_model`、`film.minimax.unknown_model`、`film.fake.unknown_model`、`film.settings.no_model` | 「未知的 X 档位：{model}」/「{provider} 没有档位 {model}」 | 所选的视频档位已不可用，请在出片设置里重新选择 | `model`、`provider` → 日志 |
| `film.minimax.bad_resolution` | {model} 不支持 {resolution}，可选：{options} | 这个档位不支持 {resolution}，可选：{options} | `model` → 删（与 `film.settings.bad_resolution` 同文） |
| `film.ark.connect_failed`、`film.minimax.connect_failed` | 连接 X 失败：{kind} | 连接视频服务（X）失败 | `kind` → 日志 |
| `film.provider.submit_cut` | 提交时连接中断：{kind} | 网络中断 | `kind` → 日志（它嵌在 `film.submit.ambiguous`「提交时连接中断，不确定……（{cause}）」里，不能再重复「提交时连接中断」） |
| `film.provider.download_connect` | 下载连接失败：{kind} | 下载视频时连接失败 | `kind` → 日志 |
| `film.submit.crashed` | 提交异常：{kind}: {cause} | 提交时出现意外错误，请重试；仍失败请联系管理员 | `kind`、`cause` → 日志（`log.exception`，带堆栈；现在 runner 这一支没有打印堆栈） |
| `film.ark.not_json`、`film.minimax.not_json` | X 返回的不是 JSON | 视频服务（X）返回了无法识别的响应 | — |
| `film.ark.no_task_id`、`film.minimax.no_task_id` | X 受理了请求却没有返回任务 id | 视频服务（X）受理了请求却没有返回任务编号 | — |
| `film.ark.throttled` | 方舟限流（HTTP 429） | 视频服务（方舟）繁忙 | — |
| 子计划 2 新登记的 TTS 未配置（原 `tts_volc` 的「在 backend/.env 写 VOLC_TTS_API_KEY…」） | — | 配音服务还没有配置，请联系管理员 | 日志写明需要的环境变量 |
| 合成 / 导出缺 ffmpeg（原 `app._NO_FFMPEG`「brew install ffmpeg…」、前端 `compose.ffmpegHint`） | — | 服务器缺少视频处理组件 ffmpeg，暂时无法合成，请联系管理员 | 安装命令留在 README，不进界面 |
| 合成意外异常（原 `app._compose_worker`「合成异常：{类名}: {原文}」） | — | 合成时出现意外错误，请重试；仍失败请联系管理员 | 类名与原文 → `log.exception` |

- **不重复「稍后自动重试」**：`throttled`、`connect_failed`、`quota` 会作为原因嵌进最终失败文案（`film.submit.unavailable`、`film.poll.gave_up`），那时已不再重试，所以这些文案只说现象。
- **保留不改**：
  - 文案里的 HTTP 状态码，如「暂时不可用（HTTP 503）」，作排查线索；
  - 自由节点、段、镜头的 id，这些是用户在界面上看得到的编号；
  - `rate.*` 费率依据。
- **测试**：
  - 断言新文案；
  - 对 `no_key`、`unknown_model`、`connect_failed`、`submit.crashed` 断言日志里有原细节（`assertLogs` 或等价写法）；
  - 断言日志和消息参数里都没有密钥。
- **兼容**：
  - 旧会话里存的是旧代码加旧参数。比如 `film.ark.connect_failed` 带 `kind`，现在模板里没有 `{kind}`，前端 `formatMsg` 照新模板渲染，多余参数忽略。这一点在 `server-msg.test.ts` 补用例。
  - 旧会话只有中文字符串的照原样显示。

### 修订记录

- 用户 2026-11-13 确认把以上 A、B 两项并入子计划 2（「可以」）。
- 子计划 1 的 Opus 验收结论为「有缺口可接受」，缺口即 A、B。
- 2026-11-13 Opus 设计审查（dcdba2e + bad9915）要求修改，已改：
  1. `QuotaExceeded` 按官方页为 429，含免费额度耗尽、排队任务过多、5 小时 / 周 / 月额度，改为可重试（`TransientError`），文案「额度不足或排队已满，持续失败请联系管理员」；429 里只有 `SetLimitExceeded` 不重试。
  2. 补映射：`OperationDenied.ServiceNotOpen`、`InvalidEndpoint.ClosedEndpoint` → `model_unavailable`；`OperationDenied.ServiceOverdue` → `overdue`；`OperationDenied.PermissionDenied` → `access_denied`；`Input*`/`Output*` + `RiskDetection` 按前缀 / 后缀；`*.PolicyViolation` 按后缀，`Output*` 另有 `film.ark.output_copyright`。
  3. 日志要能定位：方舟日志带任务 id、请求 id、档位；runner 段失败记会话目录与段 id；提交意外异常用 `log.exception`（原文「runner 已有 traceback 的保持」不实，已改）。
  4. 合成意外异常不再向用户显示异常类名（推翻计划的 R7）。
  5. `throttled`、`connect_failed` 去掉「稍后自动重试」；`submit_cut` 改为「网络中断」，避免嵌进 `film.submit.ambiguous` 后重复。

### 后续事项（不在子计划 2）

- **错误参考编号**：失败时给用户一个参考编号（与日志里的记录对应），方便用户报给管理员。放到子计划 3 的管理后台一起设计。
- **豆包语音 4xx 映射**：鉴权失败、余额不足等 4xx 映射为友好代码（与方舟同法）。子计划 2 只做未配置与通用拒绝，映射留作后续。

## 子计划 3 范围补充（2026-11-13，子计划 2 交付后）

§9 子计划 3 原范围是「auth、novels、library、admin、usage、pricing、store，以及对应接口和 version.error」。本节把范围落到具体调用点，并补上子计划 2「后续事项」推过来的错误参考编号。

### A. 范围

**后端模块**（凡是会到达用户的 raise 都带代码；异常类保留原基类、混入 `UserError`，见 §5.2）：

| 模块 | 异常类改法 | 说明 |
|---|---|---|
| `server/auth.py` | `AuthError(UserError, Exception)` | 注册、登录、停用、改密码、用户不存在。`user_dir` 的「非法的用户 ID」只来自签过名的 token 与目录名，标 `# i18n: internal`；`update_user` 的「不允许修改」只有 admin.py 用白名单字段调用，同样标 internal |
| `server/novels.py` | `NovelError(UserError, ValueError)`、`NotFound(UserError, LookupError)`；`Busy` 继承 `NovelError` | 小说、章节、版本、采用、资产卡、人物生命周期、摘要、创作限制、关键帧、风格参考图 |
| `server/library.py` | 新增 `LibraryError(UserError, ValueError)` | 目前没有接口直接调用（资产库已并进小说长期记忆），仍给代码，免得以后接回接口时漏掉。资产卡的三条与 novels 文字相同，复用 `novel.asset.*` |
| `server/admin.py` | `AdminError(UserError, Exception)`、`NotFound(AdminError)` | 下层（auth、usage）带代码的异常换成 `AdminError` 时**保留原代码与参数**，不再 `AdminError(str(e))` |
| `server/usage.py` | 新增 `UsageError(UserError, ValueError)` | 不支持的分组 |
| `server/pricing.py` | 新增 `PricingError(UserError, ValueError)` | 价格表校验 |
| `server/store.py` | 不改类 | 唯一的 raise（非法的记录 ID）只被迁移代码用目录里的文件名调用，标 `# i18n: internal` |

**`server/app.py` 调用点**（逐个列在计划的「调用点清单」里）：
- 守门：`current_user` 的 401、`admin_user` 的 403。
- 账号：`/auth/register`、`/auth/login`。
- 小说：`_novel_call`（404/409/422 一律 `to_detail(e)`）、`_clean_params`、`_start_version` 的「本章还没有原文」与月上限 429、`chapters_digest` 的「章后整理已关闭」、`memory_asset_upsert` 的卡片 id 不一致。
- 渲染任务包：`render_plan` 的 `run_id` 非法（400）与版本不存在（404）。同一函数里「分镜结构不完整」和验证门属于子计划 4，行尾标 `# i18n: todo(4)`。
- 管理：`_admin_call`、`admin_usage`/`admin_usage_csv` 的 `days` 校验、`admin_pricing_put`，以及新增的错误记录接口（见 C）。
- 章后整理失败（`_run_digest`）的持久化原因（见 B）。

**持久化错误**：
- **版本**：`version.error` 旁加 `error_msg`，与会话同形（§3.3）。`novels.create_version` 初值 `error_msg: None`，`update_version_state` 接受 `error_msg` 字段，管理后台失败任务列表一并返回。
  - 版本失败原因**只由转换任务路径产出**（`app._execute` 写 `error=`）。子计划 3 只做好存储与显示，产出点留给子计划 4。
  - 显示处：App.tsx 打开失败版本时的提示、管理后台「任务」页的失败列表。有 `error_msg` 按代码，没有就原样显示 `error`。
- **章后整理**：`chapter.digest.error` 现在存的是 `repr(e)[:300]`（Python 异常原文）。改为 `error`（中文兜底）加 `error_msg`（`chapter.digest.failed`，带参考编号），异常原文只进日志和错误记录。

**前端**：凡是显示上述接口错误的地方，都改为存 `errValue(e)`（或带代码的持久化字段），渲染时 `formatMsg`，切换语言后跟着变。toast 是即时的，弹出时 `formatMsg(errValue(e))` 即可。涉及：
- 登录注册弹窗；
- App.tsx 的页面提示条（改为存「文案键 + 错误值」，渲染时再拼）与提交转换的错误（`useJob.start`）；
- 小说页、小说概览、资产卡、画布侧栏（剧情、限制）、风格参考图、关键帧上传与删除、渲染任务包页；
- 章后整理状态（VersionBar）；
- 管理后台各页的读取错误条、操作 toast、任务页失败原因，以及新增的「错误记录」页签。

**不在本子计划**：
- job 接口（「job 不存在」、批次预览）、转换任务的进度、失败、quality_report、验证门、「分镜结构不完整」→ 子计划 4；
- 助手接口（含 `_assistant_db` 的「小说不存在」、撤销时转 `NovelError` 的 409）→ 子计划 4；
- 验证报告 → 子计划 5；
- 豆包语音 4xx 映射 → 仍是后续事项；
- `admin.py main()` 的命令行输出、启动与迁移时的 `print` → 运维看的，保持中文，行尾标 `# i18n: internal`；
- pydantic 校验失败的 422（`detail` 是列表）：前端已有的登录、密码等输入框先挡住了空值，不在本次改。

### B. 错误参考编号

**目的**：意外失败时，界面只说「出了点问题，请联系管理员」。用户把参考编号报给管理员，管理员在后台按编号找到那次失败的完整记录（堆栈、位置、哪个用户）。

**哪些失败带编号**（只给「用户自己解决不了、原因只在服务器上」的失败）：

| 场景 | 代码 | 何时产生 |
|---|---|---|
| 接口里没接住的异常（原来变成纯文本 500） | `common.internal` | 每次 |
| 章后整理失败（持久化在章节上） | `chapter.digest.failed` | 每次 |
| 出片提交时的意外异常（子计划 2 的 `film.submit.crashed`） | 沿用 | 每次 |
| 合成时的意外异常（子计划 2 的 `compose.crashed`） | 沿用 | 每次 |

后两项的代码与文案不变，只是把子计划 2 已有的 `log.error`（脱敏后的堆栈）改为经错误记录写出，并把编号带进持久化的 `error_msg`。

**不带编号**：
- 可预期的业务错误（4xx，如重名、未登录、原文已锁定）：用户看文案就能处理。
- 配置类与厂商映射类错误（如 `film.ark.no_key`、`film.ark.auth`、`usage.monthly_cap`）：原因确定，管理员看文案就知道去哪查，日志里已有明细。以后需要时可按同一套接口加，不改数据形状。

**数据形状**：消息对象顶层多一个可选字段 `ref`。
```json
{"code": "common.internal", "params": {}, "message": "服务器出了点问题，请稍后重试；仍失败请联系管理员（参考编号 K7Q2M9XD）", "ref": "K7Q2M9XD"}
```
- `ref` 只出现在顶层，不进 `params`，嵌套原因（`compact`）不带它。
- `message`（中文兜底）末尾附「（参考编号 X）」。这样旧前端、`ApiError.message`、还没改造的显示处也能看到编号。
- 持久化：`error_msg` 为 `{code, params, ref}`；`error` 为带编号的中文兜底。`session.set_error` 与 `copy_error` 保留 `ref`。
- 编号：8 位，取自 32 个字符（数字加大写字母，去掉 I、L、O、U），由 `secrets` 生成。查找时忽略大小写、空格与连字符，并按 Crockford 规则把 O 当 0、I/L 当 1，只留 0-9A-Z。

**存储**：`DATA_DIR/error_refs.jsonl`，追加写，一行一条：
```json
{"ref": "K7Q2M9XD", "at": "2026-11-13T08:00:00+00:00", "user_id": "a1b2c3d4e5f6", "code": "common.internal", "params": {}, "where": "GET /novels/n1", "detail": "Traceback …"}
```
- `user_id` 可为 null（取不到用户时）。用户名在读出时按 `user_id` 现查，不写进文件。
- `where`：接口是「方法 + 路径」（不含查询串），后台线程是「digest 小说 id/章节 id」「submit 会话目录」「compose 会话目录」。数据目录一律换成 `<data>`（如 `submit <data>/users/<uid>/novels/…`），不留主机上的绝对路径。
- `detail`：堆栈或原文。
  - 先 `scrub_secrets`。它抹掉：Bearer 凭据；`x-api-key` 头；环境里的厂商密钥、模型密钥 `ANTHROPIC_API_KEY`、token 签名密钥 `STORYBOARD_SECRET`；调用方给的额外密钥（如厂商对象持有的 key）。
  - 本子计划让 500 与章后整理（模型调用，密钥经 `x-api-key` 发出）这两条更宽的路径经过脱敏，所以 `SECRET_ENVS` 与 `scrub` 的规则一并补齐，原有日志也受益。
  - 数据目录换成 `<data>`。
  - 截断到 8000 字时保留头尾：链式异常的最后一行（最终异常）在末尾。
  - 不记请求体、请求头、查询串、局部变量。
- **上限**：保留最近 1000 条。行数超过 2000 时整体重写为最后 1000 条（临时文件 + `replace`，单进程内加锁）。服务是单进程部署（线程池并发），不考虑多进程同时写。
- **日志**：每条同时写一条 ERROR 日志，内容是同样脱敏后的 `ref`、`code`、`user`、`where` 与 `detail`。
  - 缺省写 `server.errors`（500 中间件、章后整理）。
  - 出片提交与合成的意外异常沿用子计划 2 原来的 logger（`render.runner`、`render.app`）。
  - 日志与记录都不得出现密钥。

**在哪里加编号**：
- **接口 500**：在 `app.py` 加一个纯 ASGI 中间件，接住路由里没处理的异常，记一条、返回 `500 {"detail": <common.internal 消息对象，带 ref>}`。
  - 中间件要注册在 CORS 之内（代码里写在 `CORSMiddleware` 的 `add_middleware` **之前**；Starlette 后加的在外层）。这样 500 响应也带 CORS 头，跨源的前端能读到 detail。
  - 响应已经开始（流式接口中途出错）时不接管，照旧抛出。
  - `HTTPException` 由内层的 ExceptionMiddleware 处理，不会走到这里。
  - 用户 id 从 `Authorization` 头按 `auth.verify_token` 解析，失败就记 null。解析与写盘放进 `anyio.to_thread.run_sync`，不卡事件循环。
- **后台线程**：在原来写失败的地方，调用 `error_refs.record_exc(...)` 拿到编号，再用 `with_ref(msg(code), ref)` 写入。章后整理里可预期的失败（带代码的 `UserError`，如章节在整理中途被删）直接写那个代码，不记编号、不占错误记录。

**管理后台**：
- 接口（都要管理员权限）：
  - `GET /admin/errors?limit=200`：最近记录的**摘要**，最新在前，带用户名，**不含 `detail`**；
  - `GET /admin/errors/{ref}`：单条，带 `detail`。找不到时 404 `admin.error_ref.not_found`。**每次查看写一条审计** `view_error_ref`，对象为记录所属用户，`after` 为 `{ref}`。
- 页签「错误记录」：
  - 顶部一个按编号查找的输入框，下面是最近记录表（时间、用户、编号、说明、位置）；
  - 展开某一行时才请求单条接口、显示脱敏后的 `detail`；
  - 说明按代码用当前界面语言渲染；
  - 审计页把 `view_error_ref` 显示为「查看错误详情」。
- **敏感面**：这是新增的一个查看入口。后台管理员是网页角色（`python -m server.admin promote` 就能授予），与能登录服务器看日志的运维不是同一群人。堆栈里的异常文字可能带用户输入的片段。所以：
  - 列表不给详情，详情逐条查看并留审计，符合商业化合约「排查问题……留访问日志」；
  - 记录里不存主机绝对路径；
  - 不记请求体与局部变量。

**前端显示**：
- `formatMsg` 遇到顶层带 `ref` 的消息对象，在渲染结果后附 `common.refSuffix`：中文「（参考编号 {ref}）」，英文「 (reference {ref})」。
- 若渲染结果已包含编号（缺译时回落到已带编号的 `message`），就不再重复附加。
- 嵌套原因里的消息对象不附编号。

**不采用的做法**：
- **编号放进 `params`**：每个可能带编号的代码都得在模板里留 `{ref}`，嵌套时也会被一起渲染。放顶层与代码无关，前端统一处理。
- **用 `@app.exception_handler(Exception)`**：Starlette 把它交给最外层的 ServerErrorMiddleware。它在 CORS 之外，响应不带 CORS 头，跨源前端读不到 detail；而且它处理完还会再抛一次，uvicorn 会把未脱敏的堆栈打进日志。
- **所有错误都带编号**：4xx 业务错误自带说明，编号只会增加噪音和写盘量。
- **用请求 id 或 UUID**：太长，用户口头或手抄转述时容易抄错。8 位、去掉易混字符就够。重复的概率在 1000 条的窗口里可以忽略。
- **存进 SQLite 或按天分文件**：与 `usage.jsonl`、`admin_audit.jsonl` 的做法不一致；1000 条的规模用 JSONL 足够。

**留给子计划 4**：转换任务 `_execute` 的通用异常分支（`except Exception`）、助手的 SSE `error` 事件，用同一套 `record_exc` / `with_ref` 接上。

### C. 代码命名（新登记）

按 §4 的域划分：
- `auth.*`：账号与权限。
- `novel.*`：小说本身，以及挂在小说上的长期记忆，子域有 `asset`、`lifecycle`、`constraint`、`style`。
- `chapter.*`：章节，以及挂在章节上的内容，子域有 `version`、`keyframe`、`digest`。
- `admin.*`：管理操作，子域有 `pricing`、`error_ref`。
- `usage.*`：用量。
- `library.*`：旧资产库。
- `common.*`：跨域，有 `internal`、`image_too_big`。

完整列表与中文兜底见计划。
- **面向最终用户**（沿用子计划 2 B 节原则）：
  - 不出现环境变量名。`chapter.digest.off` 只说「章后整理功能没有开启，请联系管理员」，`STORYBOARD_CHAPTER_DIGEST=0` 写进日志。前端 `flow.digest.off` 同步去掉变量名。
  - 不出现内部枚举值。「这个版本的状态是 {status}，不能采用」去掉 `status`。
  - 豁免：生命周期类型与状态、`admin.bad_role` 的可选值、`admin.bad_days`/`admin.bad_disabled` 的参数名保持原文。它们是接口取值，界面用下拉与开关挡住了，用户触发不到（计划 R14）。
- **文字变化**：以下几条的中文兜底与现在不完全相同，计划里逐条列出：
  - `repr` 引号去掉：`novel.bad_id`、`novel.asset.id_mismatch`、`admin.pricing.bad_row`；
  - 列表改用「、」连接：`novel.unknown_params`；
  - 去掉状态值：`chapter.version.not_adoptable`；
  - 不再出现环境变量名：`chapter.digest.off`；
  - 不再存 `repr(e)`：`chapter.digest.failed`；
  - 原来的纯文本「Internal Server Error」改为消息对象：`common.internal`。

### D. 测试补充

- 后端：
  - 各模块断言 `code` 与关键 `params`；
  - 中间件 500：detail 形状、`ref` 能在记录里找到、记录与日志里没有测试密钥（含模型密钥、签名密钥、`x-api-key` 头）、带 `Origin` 时响应有 CORS 头；
  - 错误记录：头尾截断、超过上限时裁剪、查找不区分大小写（含 Crockford 映射）、数据目录换成 `<data>`；
  - 管理接口：列表不含 `detail`，单条查看写审计；
  - 测试隔离：所有会走到错误记录的测试在导入前设临时数据目录（`tests/render/test_runner.py` 原来没设）；
  - `set_error` 保留 `ref`；
  - 章后整理失败：`error_msg` 带编号，`error` 里没有异常类名。
- ast 扫描：`MODULES` 加入上表七个模块与 `server/error_refs.py`（全文件），app 函数集合加入 A 节列出的函数。`SINK_NAME` 补上 `Busy`（novels 的 409 异常名不以 Error 结尾，现在扫不到）。扫描结果要清零。
- 前端：
  - `formatMsg` 附编号且不重复；
  - 登录错误、页面提示条、管理后台错误条在切换语言后跟着变；
  - 错误记录页签能按编号查找；
  - 失败版本与章后整理失败按 `error_msg` 渲染，旧数据显示 `error`。

### 设计审查修订记录（Opus，审 163c039，结论「有修改后通过」）

- **I1 测试隔离**：`tests/render/test_runner.py` 原来不设数据目录，runner 接上错误记录后会写进开发机真实的 `backend/data/error_refs.jsonl`。计划 Task 1 在该文件导入前设临时目录，并逐条改写会失败的五处精确断言（runner :568/:756/:757，compose :277/:439）。Task 7 改为核对真实数据目录没被写入。
- **I2 脱敏补齐**：`SECRET_ENVS` 补 `ANTHROPIC_API_KEY`、`STORYBOARD_SECRET`，`scrub` 补 `x-api-key` 头，并配测试（见 B「存储」）。
- **I3 可见范围**：列表接口不含 `detail`；单条查看写审计；`where` 与 `detail` 里的数据目录换成 `<data>`。更正了原稿「没有新增敏感面」的说法（见 B「管理后台」）。
- **Minor**：
  - 采纳的：
    - `App.tsx:966` 的画布 `notice` 列入计划；
    - `test_render.py:189`、`test_render_free.py:142` 改为断言代码；
    - `user_of_root` 改为相对 `DATA_DIR/users` 解析；
    - 截断保留头尾；
    - `normalize` 采用 Crockford 映射、只留 0-9A-Z；
    - 500 中间件与章后整理用 `server.errors`；
    - 列表去掉 `detail`，顺带解决响应体积；
    - `chapter.digest.failed` 去掉主语，VersionBar 有 `error_msg` 时不再套「失败（…）」；
    - 章后整理里可预期的失败不记编号；
    - 计数时用 `with open`；
    - 中间件里的阻塞操作放进线程。
  - 以豁免裁定处理的：内部枚举值（生命周期类型与状态、角色名）保持原文（计划 R14）。

## 子计划 4 追加需求（2026-11-13，用户）

- **不对普通用户透出底层模型**：项目底层大模型是 DeepSeek（经 Anthropic 兼容接口），普通用户界面与接口里不出现模型名或厂商名。已知透出点：
  1. `/healthz`（免登录）返回 `model`、`api_key_configured`，账号菜单显示「模型：…」；
  2. `GET /novels/{nid}/chapters/{cid}/versions/{vid}` 返回整条记录，`manifest` 含 `contracts.model` 与各次调用记录；
  3. 转换任务失败的 `job.error`、助手 503「助手暂不可用：{e}」带模型接口原文。
- 用户已决：管理后台（用量统计、价格表、CSV、错误记录）仍显示模型名；本项并入子计划 4 一起设计、审查、验收。

## 子计划 4 范围补充（2026-11-13，子计划 3 交付后）

§9 子计划 4 原范围是「转换任务（进度、调试日志、ConversionError/LLMError、quality_report、验证门）+ 助手（artifact、SSE 事件、notice、编辑卡 warnings、target 显示映射）」。本节把范围落到具体调用点，并补上三件事：
- 子计划 3 留下的版本 `error_msg` 产出点与 `_execute` 通用异常的参考编号；
- 模型服务错误的友好映射；
- 上一节「子计划 4 追加需求」：不对普通用户透出底层模型。

### A. 范围

**后端模块**（凡是会到达用户的报错与进度都带代码；异常类保留原基类、混入 `UserError`）：

| 模块 | 改法 | 说明 |
|---|---|---|
| `pipeline/errors.py` | `ConversionError(UserError, RuntimeError)`，`report` 照旧是第二个位置参数 | 四种失败各给代码（见 H）；`str(e)` 不再带服务器上的工作目录 |
| `pipeline/chat.py` | `LLMError(UserError, RuntimeError)`，另带 `hint`（开发细节）与 `needs_ref`；新增 `llm_error(e)` 映射函数 | 见 C |
| `pipeline/events.py`（新） | `make_say(log, on_event)` | 进度事件的唯一出口：给用户的消息对象，同时把中文兜底写进调试日志 |
| `pipeline/convert.py`、`pipeline/graph.py` | 新增 `on_event` 参数；面向用户的进度行改走 `say(code, …)` | 校验报告逐行、修复细节、合并与终检的工具输出、工作目录只进调试日志 |
| `pipeline/review.py` | 评审调用失败时报告里只写友好文案 | 现在把 `{type}: {e}` 原文写进报告，报告会进质量报告与界面 |
| `pipeline/__main__.py` | 命令行打印 `LLMError.hint` 与质量报告的中文兜底 | 开发用的命令行照旧看得到环境变量名 |
| `assistant/tools.py` | 新增 `ToolError(UserError, ToolException)`；`_tool` 的报错处理把 `ToolError` 交给 ToolNode 包装 | 见 D |
| `assistant/graph.py` | `ToolNode(..., wrap_tool_call=…)`：`ToolError` → `status=error` 的 ToolMessage，`artifact={"error": 消息对象}` | 正文仍是给模型的中文，与原来一字不差 |
| `assistant/actions.py`、`assistant/edits.py` | 全部 `ToolException`、`UndoError` 带代码；`_op` 把接口错误的消息对象原样带进 `ToolError` | 撤销成功的那句话也改为消息对象 |
| `assistant/events.py` | `error`、`notice`、中断、`tool_end`、失败卡带消息对象 | 见 D |
| `prompts/assistant.md` | 加一句：不说出底层模型或其提供方 | 见 E |
| `server/summary.py` | `unpriced` 由模型名列表改为布尔 | 见 E |
| `server/novels.py` | `update_version_state` 接受 `quality_msg`、`debug_log` | 存储 |

**`server/app.py` 调用点**（逐个列在计划的「调用点清单」里）：
- 转换：`_execute`、`_run_version_job`、`list_jobs`、`_jobs_view`、`get_job`、`get_job_partial`。
- 渲染任务包与验证门：`_render_gate`、`_gate_status`、`render_plan`（「分镜结构不完整」，现标 `# i18n: todo(4)`）、`render_keyframes`。
- 助手：`_assistant_db`、`assistant_clear`、`_assistant_ctx`、`_assistant_begin`、`_assistant_stream`、`_assistant_model_or_503`、`assistant_send`、`assistant_resume`、`assistant_undo`、`_check_version_doc`（编辑卡 warnings）。
- 不透出模型：`healthz`、`versions_get`、新增 `admin_service` 与 `admin_job_debug`。

**前端**：
- 转换：JobPanel（进度、失败、质量报告）、画布侧栏的任务行、侧栏与动态面板的 `last_log`、App 打开失败版本时的提示条、管理后台任务页（失败原因只取一行，另加「调试日志」）。
- 验证门：`useFilm` 的 `gate`、`compose.ts` 的阻断原因、FilmPanel 与 TimelineCanvas 的提示。
- 助手：`assistantSession`（`error`、`notice`、`tool_end`）、AssistantPanel、ActionCard（失败卡、warnings、diff target）、TaskCard（失败原因、合成步骤、下载报错）。
- 账号菜单：模型一行只给管理员。

**不在本子计划**：
- 验证报告逐条双语 → 子计划 5。本子计划只保证报告原文能作为参数带着走（`report` 参数、门的 `verification` 附加字段），不改报告本身。
- 豆包语音 4xx 映射 → 仍是后续事项。
- 给模型的文字：提示词、修复回喂的报告、`repair.py` 的补丁错误、工具结果正文。它们在扫描里以 `# i18n: llm` 豁免（工具报错正文由 `ToolError` 的中文兜底提供，与原文一字不差）。
- 出片厂商与视频档位名（方舟、MiniMax、档位标签）：这是用户自己选的产品选项，不属于「底层模型」，照旧显示。

### B. 转换任务的进度事件与调试日志

**两路输出**：
- **进度事件**：`job["log"]` 改为事件列表，每条 `{code, params, message, at}`。
  - `message` 是中文兜底（与 §3.1 一致）；`at` 是 ISO 时间。
  - `last_log`（`/jobs` 与助手的 `jobs_running`）取最后一条事件；给助手模型看的仍是它的中文兜底字符串。
  - 事件只覆盖用户关心的节点：资产库沿用、编号接续、长期记忆注入、分批、每批开始、校验通过或未过、自动修正、修复、降级交付、整章终检通过、软核查、自动采用、章后整理排队、落盘与写长期记忆的警告。完整清单见 H。
- **调试日志**：`job["debug_log"]`，字符串列表，原文、不翻译。
  - 内容：原来 `log` 收到的全部文字，外加 `LLMError.hint`、异常的 `repr`。包括校验报告逐行、修复细节、合并与终检的工具输出、工作目录、thinking 降级时的接口原文。
  - 每行进表前经 `error_refs.scrub_text`：抹掉密钥，数据目录换成 `<data>`。
  - 进度事件的中文兜底同时写进调试日志，所以调试日志是一份完整的时间线；命令行打印的也是它。

**调试日志只给管理员**（裁定，理由见计划 R2）：
- 普通用户的 `/jobs/{id}` 不返回 `debug_log`；版本记录的读取接口也不返回。
- 调试日志里有服务器的临时目录、接口原文（可能带模型名）、环境变量名，以及校验报告引用的用户原文片段。后台管理员与能登录服务器的运维不是同一群人（子计划 3 R16），所以按错误记录的同一原则处理：逐条查看并写审计。
- 存放位置：
  - 内存任务表里每个任务最多留 5000 行，超出丢最早的（任务表只增不删）；
  - 任务结束（成功或失败）时，把最后 400 行写进版本记录的 `debug_log`，服务重启后管理员仍能看到失败那次的经过。成功后自动采用、整理排队等几行产生得晚，再补落一次。
- 接口：`GET /admin/jobs/{vid}/debug?user_id=…`（管理员）。先查内存任务表，没有再读版本记录。找不到时 404 `admin.job.not_found`。每次查看写审计 `view_job_debug`，对象为任务所属用户。
- 管理后台任务页：运行中与失败的每一行都有「调试日志」按钮，点开时才请求。

**失败**（`_execute`）：
- `ConversionError`（带代码）：
  - 报告为空时，`error_msg` 就是它的消息对象；
  - 报告不为空时，`error_msg = job.failed_report {reason, report}`，模板为 `{reason}\n{report}`：
    - `reason` 是紧凑的原因消息；
    - `report` 是厂商原文类型参数（不翻译），先经 `scrub_text`，截断到 6000 字（`vendor(text, limit=…)` 新增 `limit` 参数）；
    - 中文兜底等于原来的 `f"{e}\n{e.report}"` 去掉工作目录。
  - 一行显示的地方（提示条、助手任务卡、后台失败列表）只取 `reason`，旧数据取 `error` 的第一行，与现在一致。
- `LLMError`（已映射、不需要编号）：`error_msg` 为它的代码，不带编号；`hint` 进调试日志。
- `needs_ref` 的 `LLMError`（`llm.bad_request`）：保留这个代码并带参考编号，`error_refs.unexpected(原异常, "llm.bad_request", user_id=…, where=…)`。用户看到的是「AI 服务拒绝了这次请求」，不是「意外错误」（设计审查 I2）。
- 其它异常、没有代码的 `ConversionError`：`error_refs.unexpected(e, "job.crashed", user_id=…, where="convert <nid>/<cid>/<vid>")`，带参考编号；堆栈进错误记录与 `server.errors` 日志。不再存 `repr(e)`。
- 写法统一用 `render_session.set_error(job, m)`，再把 `error`、`error_msg` 一起写进版本记录（子计划 3 R7 留下的产出点）。

**质量报告**：
- 降级交付的每批警告改为消息对象 `job.quality.degraded`，参数 `batch`、`retries`、`attempt`、`candidates`、`report`（厂商原文类型，同上）。
- 任务与版本记录新增 `quality_msg`（消息对象列表）。`quality_report` 字符串照旧，是各条中文兜底用空行连接，旧前端与 `has_quality_report` 不受影响。

**其它任务接口**：
- 「job 不存在」→ `job.not_found`，文字改为「任务不存在（服务重启会清空任务表）」；
- 「暂无已完成的批次可预览」→ `job.no_partial`。

**验证门与渲染任务包**：
- `_render_gate` 的 422 → `{**msg("verify.gate.blocked"), "verification": …}`。附加字段 `verification` 名字与内容不变，前端 `ApiError.verification` 照旧能取到。
- `_gate_status` 的 `message` 改为消息对象：
  - 没有分镜产物 → 复用 `film.session.no_storyboard`；
  - 门没过 → 门的消息对象，去掉 `verification`。
- `render_plan`、`render_keyframes` 的「分镜结构不完整」→ `film.plan.incomplete`、`film.keyframes.incomplete`，带 `detail`（厂商原文类型，与子计划 1 的 `film.build.incomplete` 同法）。

### C. 模型服务错误映射

**原则**（沿用子计划 2 B 节）：
- 界面文案统一称「AI 服务」，不出现模型名、厂商名、环境变量名、HTTP 原文。
- 原文脱敏后只进三处：
  - `pipeline.chat` 的 WARNING 日志：带 HTTP 状态、错误类型、请求 id（`request-id` 头，取不到写 `-`），原文截到 500 字；
  - `LLMError.hint`：进转换任务的调试日志与命令行；
  - 需要编号的那一类（`llm.bad_request`）的错误记录。

**判定顺序**（`llm_error(e)`）：
1. 已是 `LLMError` 原样返回；
2. 先按 langchain_core 的厂商无关分类（`langchain_anthropic` 抛出的异常同时继承它们）：
   - `ContextOverflowError` → `llm.too_long`；
   - `ModelAuthenticationError` → `llm.auth`；
   - `ModelPermissionDeniedError` → `llm.access_denied`；
   - `ModelNotFoundError` → `llm.model_unavailable`；
   - `ModelRateLimitError` → `llm.busy`；
   - `ModelTimeoutError` → `llm.timeout`；
   - `ModelConnectionError` → `llm.connect_failed`；
   - `ModelInvalidRequestError`（400）与 `ModelAPIError`（5xx、529）还要细分，落到第 4 步。
3. SDK 兜底：`APITimeoutError`、`httpx2.TimeoutException` → `llm.timeout`；其余 `APIConnectionError`、`httpx2.HTTPError` → `llm.connect_failed`。
4. `APIStatusError`：
   1. 先看状态码 400、413、422 或响应体错误类型 `invalid_request_error` 时的原文特征，按顺序：
      - 审核特征（如 `Content Exists Risk`、content filter / policy / moderation、safety、sensitive）→ `llm.content_blocked`；
      - 余额特征（credit balance、insufficient balance/credit/funds、余额不足）→ `llm.balance`。Anthropic 风格网关的余额不足走 400；
      - 原文含 `max_tokens`（输出上限配置超出模型允许值）→ `llm.model_unavailable`。这是配置问题，不能叫用户缩短内容；
      - 超长特征（context length、maximum context、too long、超出 token）→ `llm.too_long`；
   2. 再按响应体 `error.type` 查表；
   3. 最后按 HTTP 状态查表；
   4. 都没有命中：5xx → `llm.unavailable`，其余 → `llm.bad_request`。
5. 其它异常返回 `None`，由调用方当意外处理。

流式中途的 `event: error`（SDK 以 HTTP 200 的 `APIStatusError` 抛出）只能靠错误类型判定，所以错误类型排在状态码之前。

| 情形 | 判定 | 代码 | 中文兜底 | 英文要点 | 自动重试 | 用户能做的 |
|---|---|---|---|---|---|---|
| 未配置密钥 / 未装依赖 | `build_chat_model` | `llm.not_configured` | AI 服务还没有配置，请联系管理员 | The AI service isn't set up yet | 否 | 联系管理员 |
| 鉴权失败 | 401、`authentication_error` | `llm.auth` | AI 服务鉴权失败，请联系管理员 | couldn't authenticate | 否 | 联系管理员 |
| 余额不足 | 402、`billing_error` | `llm.balance` | AI 服务账户余额不足，暂时无法使用，请联系管理员 | account is out of credit | 否 | 联系管理员 |
| 拒绝访问 | 403、`permission_error` | `llm.access_denied` | AI 服务拒绝访问，请联系管理员 | access denied | 否 | 联系管理员 |
| 模型不存在或未开通 | 404、`not_found_error` | `llm.model_unavailable` | AI 服务配置有误，暂时无法使用，请联系管理员 | misconfigured | 否 | 联系管理员 |
| 内容太长 | 413、`request_too_large`、超长特征 | `llm.too_long` | 这次要处理的内容超出了 AI 服务单次能处理的长度；请缩短内容（助手对话可先清空）后重试，仍失败请联系管理员 | too long for one request | 否 | 缩短、清空对话 |
| 内容审核 | 审核特征 | `llm.content_blocked` | 内容没有通过 AI 服务的安全审核：请检查或改写相关内容后重试 | didn't pass the safety review | 否 | 改写内容 |
| 其它请求错误 | 其余 4xx | `llm.bad_request` | AI 服务拒绝了这次请求，请重试；仍失败请联系管理员 | rejected the request | 否 | 报参考编号（带 `ref`） |
| 限流、过载 | 429、529、`rate_limit_error`、`overloaded_error` | `llm.busy` | AI 服务繁忙，请稍后重试 | busy | 是 | 稍后重试 |
| 服务端错误 | 其余 5xx、`api_error` | `llm.unavailable` | AI 服务暂时不可用，请稍后重试 | temporarily unavailable | 是 | 稍后重试 |
| 超时 | `APITimeoutError`、`ModelTimeoutError`、`httpx2.TimeoutException` | `llm.timeout` | AI 服务响应超时，请稍后重试 | timed out | 是 | 稍后重试 |
| 连不上、中途断开 | `APIConnectionError`、`httpx2.HTTPError` | `llm.connect_failed` | 连接 AI 服务失败，请稍后重试；仍失败请联系管理员 | couldn't connect | 是 | 稍后重试 |
| 重试用尽 | 上面四类在转换里重试耗尽 | `llm.gave_up`（`retries`、`cause`） | 已重试 {retries} 次仍失败：{cause} | still failing after N retries | — | 稍后重试 |
| 输出被截断 | `stop_reason=max_tokens` | `llm.truncated` | AI 输出超出了长度上限，这次没有完成；请联系管理员调整转换设置 | output hit the length limit | 否 | 联系管理员 |

**重试与现有逻辑一致**：
- 转换与章后整理（`ChatInvoker`）：仍由 `with_retry` 按 `_transient_errors()` 重试。
  - 这份清单补上 `anthropic.OverloadedError`：anthropic 1.13 把 529 单列成这个类，它不再是 `InternalServerError` 的子类，现在 529 一次都不重试，与「5xx 都重试」的原意不符。
  - 重试耗尽 → `llm.gave_up`，`cause` 嵌套映射后的原因。
  - 非瞬时错误不重试，直接映射。
  - thinking 降级照旧排在映射之前：先接住 `BadRequestError` 里的 thinking 拒绝，降级重发；其余 400 才映射。
- 流式中途的 `event: error`（HTTP 200）：错误类型是 `overloaded_error`、`api_error`、`rate_limit_error` 的，在转换路径上重试，与连接类故障共用 `transport_retries` 的次数，耗尽为 `llm.gave_up`；其他类型直接映射（计划 R5，设计审查 I4）。
- 清单以 LangChain 的 `ModelRateLimitError`、`ModelAPIError`、`ModelConnectionError`、`ModelTimeoutError` 为主，SDK 类型与 httpx2 兜底（计划 R6）。
- 助手：模型由 SDK 自己重试（`max_retries=2`，覆盖 408/409/429/5xx 与连接错误），本子计划只映射，不加重试，也不包 `llm.gave_up`。

**截断与未配置**：原文里的环境变量名与操作建议（`STORYBOARD_THINKING`、`STORYBOARD_MAX_TOKENS`、`STORYBOARD_BATCH_CHARS`、`ANTHROPIC_API_KEY`、`pip install`）移进 `hint`，并记 WARNING 日志。命令行照旧打印它们。

**编号**：只有 `llm.bad_request` 带参考编号（`needs_ref=True`），带编号时代码仍是 `llm.bad_request`（转换、章后整理、助手一致）。原因只在服务器上，用户报编号，管理员在错误记录里能看到脱敏后的接口原文。其余映射类不带编号，与子计划 3 B 节「厂商映射类不带编号」一致。

**调用方**：
- `_execute`：见 B。
- `_run_digest`：带代码且不需要编号的 `LLMError` 走「可预期」分支，章节上显示映射后的文案，不记编号；`llm.bad_request` 保留代码并记编号。可预期的判断统一用新增的 `error_refs.expected(e)`：带代码，且不是 `needs_ref`。
- 助手：见 D。
- 评审：失败时报告写成「[review] 评审服务不可用：<映射后的中文兜底>」，原文进 `pipeline.review` 的 WARNING 日志。

### D. 助手事件与报错

**工具报错带消息对象**：
- `ToolError(UserError, ToolException)`：
  - `str()` 是给模型的中文兜底，与原来的报错文字一字不差；
  - 原来 `except ToolException` 的地方（`_ask_edit`、`undo`）照样接得住。
- 把消息对象带进 `ToolMessage.artifact` 的方法：
  - LangChain 的工具在报错时不带 artifact。所以 `_tool` 的报错处理遇到 `ToolError` 就把它再抛出去；
  - 由 `assistant/graph.py` 给 ToolNode 配的 `wrap_tool_call` 接住，生成 `ToolMessage(str(e), status="error", artifact={"error": 消息对象})`；
  - 普通 `ToolException` 照旧变成只有正文的报错；
  - `interrupt` 抛的 `GraphBubbleUp` 不经过这个分支。
- `_op` 遇到 detail 是消息对象的接口错误，用 `ToolError.from_msg(detail)` 保留代码与参数，不再只取 `message`。
- 存储层带代码的异常换成 `ToolError` 或 `UndoError` 时，用新增的 `messages.recast(cls, e)` 保留代码（同子计划 3 R4）。

**事件形状**（`events.py`；旧字段都保留，新增的字段旧前端会忽略）：

| 事件 | 数据 |
|---|---|
| `token`、`tool_start`、`goto`、`done` | 不变 |
| `tool_end` | `{id, ok, summary, msg?}`。`msg` 是失败时 artifact 里的消息对象；`summary` 照旧是正文前 200 字 |
| `confirm` | 卡不变；编辑卡的 `warnings` 由字符串改为消息对象列表 |
| `action` | `{tool_call_id, action, outcome, card?, task?, error?, error_msg?}`。失败时 `error` 照旧是正文，`error_msg` 是消息对象 |
| `notice`（新） | 消息对象。只用于「步骤太多」（`assistant.too_many_steps`），之后照常 `done`。原来混在 `token` 里，会被拼进回答正文 |
| `error` | 消息对象 `{code, params, message, ref?}`，`message` 字段仍在，旧前端照旧能取到文字 |

**`error` 事件**：
- 已映射的模型服务错误：`llm.*` 代码，不带编号；`llm.bad_request` 保留代码并带编号；
- 其余：`error_refs.unexpected(e, "assistant.crashed", user_id=…, where="assistant <nid>")`，带编号；
- `before`（发新消息前取消待确认的卡）出错时，同样处理；
- 原来的「助手出错：{e}」（带接口原文）不再出现。

**中断**：
- 历史里没有结果的工具调用：`summary` 仍写「（已中断）」，另加 `msg`；
- 被停掉的卡：`error` 仍写「（已中断）」，另加 `error_msg`；
- 代码都是 `assistant.interrupted`；
- 给模型补的那条「（已中断）」ToolMessage（`graph.close_dangling`）不变。

**编辑卡**：
- `warnings` 每条是 `verify.finding {path, detail}`，`detail` 是复验规则的中文原文（厂商原文类型）。子计划 5 把 `detail` 换成逐条规则的消息对象，这里的形状不用再改。
- diff `target` 的内部值不变（恢复时 `_ask_edit` 要比对 diff）。前端显示时按字段翻译：
  - `plot_edit` 中 `field=outline` 的那一行 → 「全书梗概」的译文；
  - `field=synopsis` 的那一行 → 「{章节标题} 梗概」的译文，章节标题取卡上的 `chapter`；
  - 其余行（镜头 id、资产卡「编号 名称」）是数据，原样显示。

**撤销**：
- `UndoError(UserError, Exception)` 全部带代码；接口的 409 改为 `to_detail(e)`，数据目录照旧隐去；
- 撤销成功时 `undo()` 返回消息对象，接口的 `message` 字段改为消息对象（前端目前不显示它）。

**接口**：
- 4xx 一律带代码（见 H），包括：`where`、`step`、`id/decision`、`tool_call_id` 不合法，消息为空或过长，每日上限 429，正在回答 409，确认卡已处理 409，撤销过、找不到修改。
- `_assistant_db` 的 404 复用 `novel.not_found`。
- 「助手暂不可用：{e}」（503）：
  - 未配置这类带代码的 `LLMError` → 503 带它的代码；
  - 其它异常 → 503 `assistant.unavailable`，带编号。

### E. 不对普通用户透出底层模型

**变的接口**（存储的数据不动；管理后台的用量、价格表、CSV、错误记录照旧显示模型名）：

| 接口 | 现在 | 改为 |
|---|---|---|
| `GET /healthz`（免登录） | `model`、`api_key_configured`、`users` | `{status, first_run}`。只留首页判断「全新部署先注册」要用的布尔，也不再透出用户数 |
| `GET /admin/service`（新，管理员） | — | `{model, review_model, api_key_configured}`。`review_model` 只在开了评审且与转换模型不同时给，否则为 null |
| 账号菜单 | 人人可见「当前模型：…」与「未配置密钥」 | 只有管理员可见，数据取自 `/admin/service`；「服务」状态一行人人照旧 |
| `GET …/versions/{vid}` | 整条记录，含 `manifest.contracts.model`、`debug_log` | 经 `_version_view`：去掉 `debug_log`，`manifest.contracts` 去掉 `model`、`review_model`，其余照旧 |
| `GET /jobs/{id}` | 整个任务（含 `manifest`） | 去掉 `debug_log`；`manifest` 同上处理 |
| `GET /novels/{nid}/summary` | `unpriced` 是没定价的模型名列表 | 布尔。前端没有用到它 |
| 转换、章后整理、助手的报错 | 接口原文、`repr(e)` | 见 C、D |
| 助手的回答 | 模型被问到时可能自报模型名 | `prompts/assistant.md` 加一句：不要说出所用的底层模型或其提供方，被问到时说你是本产品的创作助手（中文称「墨卷」，英文称 Inkreel） |

**逐一核对过、不用改的普通用户出口**（计划的调用点清单逐条列出）：
- `/auth/me`、小说与章节列表、版本摘要、`/jobs` 摘要、`/jobs/{id}/partial`（只有分镜文档）、`PUT` 版本（只回状态与验证）；
- 渲染任务包与人读生产包（只有视频档位）、出片会话（厂商与档位是用户自选项）；
- 导出剪辑工程 zip（README 只讲剪辑与素材）、分镜 IR 下载（前端用 `result` 生成，IR 不含模型字段）；
- 500 兜底（`common.internal` 不带原文）。

**测试守门**：
- 后端用一个特征模型名（`STORYBOARD_MODEL=secret-model-x9`）走一遍转换，逐个请求上表的普通用户接口，响应文字里都不得出现它；
- `/admin/service` 能看到它；
- `messages_codes.json` 与 `zh.ts`、`en.ts` 的 `srv` 节点不得出现 `deepseek`、`claude`、`anthropic`（不分大小写）。

### F. 兼容

- **旧任务与旧版本**：
  - 内存任务表重启即清空，不存在旧任务；
  - 旧版本记录没有 `error_msg`、`quality_msg`、`debug_log`，前端照旧显示 `error`（取第一行）与 `quality_report`；
  - 旧记录 `error` 里存的 `repr(e)` 可能带模型名或接口原文，不迁移（计划 R10）。
- **旧前端**：
  - `job.log`、`last_log`、编辑卡 `warnings`、`gate.message` 由字符串变成对象。现行前端把它们直接当 React 子节点渲染，遇到对象会整块崩溃。所以计划先做前端兼容（Task 0），两种形状都能渲染，之后才改后端形状，不做双写（设计审查 I1）；
  - `error` 事件、失败卡、`tool_end` 的旧字段都还在；
  - 新的 `notice` 事件旧前端忽略，「步骤太多」那句话不再显示，但回答照常结束。
- **助手旧存档**：
  - 没有 artifact 的失败 ToolMessage：失败卡与 `tool_end` 显示正文（中文）；
  - 编辑卡里字符串形式的 `warnings` 原样显示；
  - 待确认的旧卡照常恢复：`_ask_edit` 只比对 diff，warnings 改了形状不影响。
- **`/healthz` 字段变了**：首页的首次注册判断改读 `first_run`；没有别的调用方（部署探针只看 200）。
- **命令行**：`str(e)` 变成友好文案；排查细节由 `hint` 补打，环境变量名照旧可见。

### G. 测试补充

- 后端：
  - `test_chat.py`：
    - 映射表每一行一条（含流式中途的错误事件、400 余额、`max_tokens` 配置错误、httpx2 超时、LangChain 包装后的异常），断言代码、`str(e)` 不含模型名与原文、WARNING 日志里有脱敏原文且没有密钥；
    - `OverloadedError` 会被重试；流式中途的瞬时错误有界重试（调用次数恰为 1 + `transport_retries`），中途的非瞬时错误不重试；重试耗尽为 `llm.gave_up`；
    - 现有第 6 节（无关的 400）改为断言映射后的 `LLMError`、不降级；
    - 截断与未配置的 `hint` 里有环境变量名。
  - `test_graph.py`、`test_offline.py`：事件序列带代码；调试日志照旧有「原因如下」与逐行报告；`ConversionError` 带代码，`str(e)` 不含工作目录；降级警告是消息对象。
  - 新增 `tests/server/test_jobs.py`：
    - `_execute` 的五条路径：成功并降级、`ConversionError` 带报告、已映射的 `LLMError`、`needs_ref` 的 `LLMError`（`llm.bad_request` 带编号）、意外异常；
    - 版本记录的 `error_msg`、`quality_msg`、`debug_log`；
    - `/jobs/{id}` 不含 `debug_log`；
    - 管理员调试日志接口与审计；
    - E 节的特征模型名扫描。
  - `test_render.py`：验证门 422 的 `code` 与附加字段 `verification`；`gate.message` 是消息对象。
  - `test_assistant.py`、`tests/assistant/*`：
    - 接口 4xx 的代码；
    - 503 两种情况；
    - `error` 事件分别为映射与带编号；
    - `notice`；
    - 失败卡与 `tool_end` 的 `msg`；
    - 中断的 `msg`；
    - 编辑卡 `warnings` 的形状；
    - 撤销的代码；
    - 工具正文与原文一字不差（现有断言保留）。
  - `test_summary.py`：`unpriced` 为布尔。
  - 所有新测试在导入前桩掉 `pipeline.config._load_dotenv`、设临时 `STORYBOARD_DATA_DIR`，并把 `ANTHROPIC_BASE_URL` 设为不可达的本机地址作保险。模型调用一律用 FakeChat、脚本模型或打桩的 `convert_text`。
- ast 扫描：
  - `MODULES` 加入 A 节的 pipeline 与 assistant 模块，app 函数集合加入 A 节列出的函数；
  - 规则补三条：调用名 `say`、字典字面量里 `message`、`error`、`summary` 键的值、`job["log"].append(…)`；下标赋值的键补 `summary`、`message`。
  - 改动前的基线：上述模块与函数共 71 处，另有两处 `# i18n: todo(4)` 标记，加上新规则后多 3 处（`events.py`）。扫描结果要清零。
- 前端：
  - `formatMsg` 渲染 `job.failed_report`；一行显示的地方只取原因；
  - JobPanel 的事件、失败与质量报告在切换语言后跟着变；
  - 验证门提示按代码渲染；
  - 账号菜单对普通用户没有模型一行、对管理员有；
  - 首页首次注册读 `first_run`；
  - 助手的 `error`、`notice`、失败卡、`tool_end`、`warnings`、diff target 中英两种渲染，旧存档的字符串照旧显示；
  - 后台任务页的调试日志。

### H. 代码命名（新登记）

按 §4 的域划分，新增一个域 `llm`（模型服务，转换、章后整理与助手共用）：
- `job.*`：任务接口、失败（`job.batch_failed`、`job.merge_failed`、`job.final_verify_failed`、`job.final_check_failed`、`job.failed_report`、`job.crashed`）、`job.quality.degraded`、进度事件 `job.event.*`。
- `llm.*`：C 节表。
- `verify.*`：`verify.gate.blocked`、`verify.finding`（子计划 5 的 `verify.rule.*` 与它们不冲突）。
- `film.*`：`film.plan.incomplete`、`film.keyframes.incomplete`。
- `assistant.*`：接口（`assistant.busy`、`assistant.daily_limit`、`assistant.unavailable`、`assistant.crashed`、`assistant.too_many_steps`、`assistant.interrupted` 等）、工具报错 `assistant.tool.*`、改内容 `assistant.edit.*`、撤销 `assistant.undo.*`。
- `admin.job.not_found`。

完整列表与中文兜底见计划。

**文字变化**（其余代码的中文兜底与现在一字不差）：
- `job.not_found`：「job」改为「任务」；
- `job.batch_failed`：去掉「（已通过批次与失败报告保留在 {workdir}）」，工作目录进调试日志；
- `job.event.seed_assets`：「（模型须复用其 ID 与描述）」改为「（新分镜会沿用其编号与描述）」；
- `job.event.batch_start`：「调用 LLM…」改为「开始生成…」；
- `job.event.normalized`：去掉「（STORYBOARD_NORMALIZE_INPUT=0 关闭）」；
- `job.event.split`：去掉工作目录；
- `job.event.unparseable`、`job.event.repair_failed`：原来把报告原文接在后面，现在只说现象，报告进调试日志；
- `job.event.persist_failed`、`job.event.memory_failed`：去掉异常 `repr`；
- 全部 `llm.*`、`assistant.unavailable`、`assistant.crashed`、`job.crashed`：取代原来带接口原文或 `repr(e)` 的写法；
- 前端：`failHead`（一行显示只取失败原因）与兼容渲染先于后端改动落地（计划 Task 0）；
- `assistant.tool.quote_changed`：文字与原来相同，只是金额与要出的段改为参数。

### 修订记录

- 2026-11-13 子计划 3 交付后起草。用户已决：管理后台仍显示模型名（见上一节）。

### 设计审查修订记录

- 2026-11-13 独立设计审查（结论 approve with changes：0 Critical / 4 Important / 14 Minor），本节与计划同步修订：
  - I1 中间提交会让前端崩溃：F 节「旧前端」改写，计划新增 Task 0（前端先行兼容）。
  - I2 `llm.bad_request` 原先在主路径上被换成 `job.crashed` 或 `assistant.crashed`：B 节、C 节「编号」、D 节 `error` 事件改为保留代码并带编号。
  - I3 余额不足的 400 会被判成 `llm.bad_request`：C 节映射顺序加余额特征；G 节写明现有第 6 节要改。
  - I4 流式中途的瞬时错误原先不重试：按协调方裁定，转换路径有界重试，助手不重试；C 节「重试」改写。
  - Minor 中涉及本节的：
    - `max_tokens` 配置错误判为配置有误（M2）；
    - httpx2 超时（M3）；
    - 按 LangChain 的 `Model*Error` 分类（M4）；
    - 调试日志的内存上限与成功后补落（M5、M6）；
    - 提示词兼写 Inkreel（M14）。
  - 其余 Minor 只改计划，取舍见计划的「修订记录」与 R4、R7、R8、R10、R17。

## 子计划 5 范围补充（2026-11-14，子计划 4 交付后）

§9 子计划 5 原范围是「rule_id 作代码、结构化参数、验证面板渲染」。子计划 4 验收留下的缺口：英文界面里，评审失败那一行、质量报告正文、验证报告正文仍是中文（或原样的英文规则说明）。本节把范围落到每条规则与每个显示处，并更正 §3.7 的一处前提。

**§3.7 前提更正**：§3.7 写「回喂模型的仍是原来的中文 message」。实测 `verification.py` 的规则说明除 `ORDER-001` 外都是英文，`novel_memory.soft_findings` 的两条是中文。所以准确的说法是：
- 回喂模型的 `Finding.message` 与 `render()` 文字**一字不改**（多数是英文原文）；
- 给用户看的另由代码渲染：中文界面从此看到中文说明，英文界面看到英文说明；
- 原文是中文的三条（`ORDER-001`、`NOVEL-CONSTRAINT-001`、`NOVEL-LIFECYCLE-001`），中文模板与原文一字不差，`message` 直接由模板生成。

### A. 范围

**后端模块**：

| 模块 | 改法 | 说明 |
|---|---|---|
| `pipeline/verification.py` | `Finding` 加 `params`，构造时按 `verify.rule.<rule_id>` 校验参数；`as_msg()`；`to_dict()` 多一个 `msg` 字段，`to_dict(shown=False)` 是回喂模型的旧形状；`VerificationReport.lines()` | 23 条规则逐条给参数，见 B |
| `pipeline/novel_memory.py` | `soft_findings` 两条规则给参数，`message` 由中文模板生成 | 与原文一字不差 |
| `pipeline/repair.py` | `validation_list` 用 `to_dict(shown=False)`；14 处 `RepairError` 标 `# i18n: llm` | 回喂模型的内容与改造前逐字一致 |
| `pipeline/quality.py` | `narration_density_gate`、`speech_fit_gate` 加出参 `lines_out` | 回喂模型的报告文字不变，见 D |
| `pipeline/review.py` | `run_review` 加出参 `lines_out` | 评审意见原文作厂商原文参数，见 D、E |
| `pipeline/graph.py` | `_check_batch` 加出参 `lines_out`；`BatchState.shown`；候选带 `shown`；降级警告与 `job.batch_failed` 带逐条消息 | 见 C |
| `pipeline/convert.py` | `job.final_verify_failed`、`job.final_check_failed`、`job.merge_failed` 带逐条消息 | 见 C |
| `pipeline/errors.py` | `ConversionError(msg, report="", lines=None)`，新增属性 `lines` | `report` 照旧是原文 |
| `server/messages.py` | 新增参数类型 `lines` 与函数 `lines_of()`；`_zh_value` 认它；登记 `verify.*`、`common.more_lines` | 见 C、H |
| `server/error_refs.py` | `scrub_deep(v)` | 消息对象里的字符串逐个 `scrub_text` |
| `server/app.py` | `_execute` 优先用 `e.lines`；`_check_version_doc` 的 `detail` 换成逐条规则的消息对象 | 其余出口（门、保存、版本、任务）随 `to_dict()` 自动带上 `msg` |

**前端**：
- `i18n/serverMsg.ts`：`formatMsg` 认 `lines` 类型（逐项渲染、换行连接）；新增 `findingText(f)`。
- `types.ts`：`Finding.msg?: ServerMsg`。
- `components/VerificationPanel.tsx`：说明文字改用 `findingText`。
- `zh.ts`、`en.ts`：`srv.verify.*`、`srv.common.more_lines`。
- 其余显示处（JobPanel 的失败区与质量报告、助手编辑卡的复验原因）已经走 `formatMsg`，形状不用再改，只补测试。

**不在本子计划**：
- 检查工具（`tools/lint_storyboard.py`、`tools/check_fidelity.py`、`tools/merge_storyboard.py`）的子进程输出：保持原文（中文），作为厂商原文参数原样显示，外面包一行按语言渲染的标题（`verify.report.tool`）。理由见计划 R6。
- 转换途中按规则代码发进度事件（子计划 4 R13 提到的可选项）：不做，失败与降级时报告里已有逐条原因。
- 尝试记录（`manifest.attempts[].report`）：照旧存原文，前端不显示它，只作审计。它的 `verification` 随 `to_dict()` 自动带上 `msg`。

### B. 逐条规则

代码一律是 `verify.rule.<rule_id>`。「原文」一栏是现有 `message`，回喂模型，不改。中文模板与原文不同的，是新写的中文说明。

| rule_id | 位置 | 级别 | 参数 | 中文模板 | 原文（给模型） |
|---|---|---|---|---|---|
| `SCHEMA-ENGINE-001` | `_validate_schema` | critical | — | 服务器缺少结构校验组件，无法校验分镜结构，请联系管理员 | jsonschema is unavailable; … |
| `SCHEMA-001` | `_validate_schema` | high | `detail`（厂商原文：jsonschema 的 `error.message`，截断 300 字） | 不符合分镜结构定义：{detail} | `error.message` |
| `SOURCE-FROZEN-001` | `_validate_frozen_units` | critical | `expected`、`actual`（句数） | 原文句子数被改动：应为 {expected} 句，实际 {actual} 句 | model changed the deterministic source-unit count |
| `SOURCE-FROZEN-002` | 同上 | critical | `unit`、`field`（`id`/`text`/`para`，原样） | 原文句子 {unit} 的 {field} 被改动（原文证据不能修改） | model changed immutable source evidence |
| `SOURCE-WAIVER-001` | 同上 | high | `unit` | 跳过原文句子 {unit} 时必须写明理由，方便审阅 | skipped source units require … |
| `ID-UNIT-001` | `_validate_identity` | critical | `id` | 原文句子编号重复：{id} | duplicate unit id … |
| `ID-EPISODE-001` | 同上 | high | `id` | 分集编号重复：{id} | duplicate episode id … |
| `ID-SHOT-001` | 同上 | high | `id` | 镜头编号重复：{id} | duplicate shot id … |
| `ID-ASSET-001` | 同上 | high | `id` | 资产卡编号重复：{id} | duplicate asset id … |
| `REF-UNIT-001` | `_validate_evidence` | high | `unit` | 镜头引用了不存在的原文句子 {unit} | shot references unknown source unit … |
| `EVIDENCE-INFERENCE-001` | 同上 | high | — | 推断镜头必须写明具体的推断依据 | inferred shots require … |
| `EVIDENCE-SHOT-001` | 同上 | high | — | 除转场镜头外，每个镜头都要引用原文依据 | non-transition shots require … |
| `EVIDENCE-RANGE-001` | 同上 | medium | — | 一个镜头的原文依据通常应是 1–3 个相邻句子 | shot evidence should normally be … |
| `ORDER-001` | 同上 | medium | `prev`（上一镜的 id 或路径）、`unit`（如 `u0050`） | 镜头回跳到更早的原文（上一处 {prev} 引至 {unit}） | 与中文模板一字不差 |
| `FID-DIALOGUE-001` | 同上 | critical | — | 台词不是所引原文的逐字摘录 | dialogue is not a verbatim excerpt … |
| `REF-NARRATION-001` | 同上 | high | `unit` | 旁白引用了不存在的原文句子 {unit} | narration references unknown … |
| `FID-NARRATION-001` | 同上 | medium | — | 旁白文字不是所引原文的原句摘录 | narration text is not a direct excerpt … |
| `COVERAGE-001` | 同上 | critical | `n`（未承载句数；句子清单照旧在 `unit_refs`） | 有 {n} 句原文没有被旁白、台词或画面承载 | source units are not carried … |
| `COVERAGE-DECLARED-001` | 同上 | high | — | 声明的未覆盖句子与程序算出的不一致 | declared coverage differs … |
| `COVERAGE-DECLARED-002` | 同上 | medium | — | 声明的推断镜头占比与程序算出的不一致 | declared inferred ratio differs … |
| `FID-SOURCE-001` | `verify_document` | critical | — | 原文句子拼起来与归一化后的原文不一致 | source units do not reconstruct … |
| `NOVEL-CONSTRAINT-001` | `novel_memory.soft_findings` | medium | `shot`、`keywords`（列表）、`constraint`（用户写的限制原文） | 镜头 {shot} 的画面描述含限制关键词「{keywords}」（限制：{constraint}），请人工确认是否违规 | 与中文模板一字不差 |
| `NOVEL-LIFECYCLE-001` | 同上 | medium | `shot`、`state`（代码引用 `verify.lifecycle.deceased`/`departed`）、`character`（角色 id + 名称） | 镜头 {shot} 里出现了{state}的角色 {character}，画面描述里没有回忆/梦境等标记，请人工确认是不是闪回 | 与中文模板一字不差 |

规则：
- 参数是数据（编号、句数、路径、用户自己的原文与限制文字），用字符串或数字；外部库原文（jsonschema）用厂商原文类型。
- `Finding` 构造时就用 `msg()` 校验：代码未登记或参数不符直接抛错。所以漏登记、漏参数在第一条触发它的测试里就会暴露（G 节要求每条规则各有一条触发用例）。
- `Finding.evidence_quote`、`expected`、`actual`、`unit_refs`、`object_path` 照旧，由验证面板按现有方式显示，不进参数。

### C. 报告怎样到达界面，以及渲染形状的取舍

**两类形状**：
1. **结构化报告**（`VerificationReport.to_dict()`）：每条 finding 多一个 `msg: {code, params}`，其余字段不变。
2. **失败与降级的报告参数**（`job.failed_report` 与 `job.quality.degraded` 的 `report`）：值由厂商原文改为新参数类型 `lines`：

   ```json
   {"t": "lines", "items": [{"code": "verify.report.finding", "params": {…}}, {"code": "verify.quality.unit", "params": {…}}]}
   ```
   - 前端逐项渲染、用换行连接；后端中文兜底同样换行连接；
   - 每项是紧凑消息 `{code, params}`（也允许字符串与厂商原文）；
   - 最多 100 项，超出的截掉，末尾补一项 `common.more_lines {n}`。

**取舍**：
- 结构化报告选「每条 finding 带消息对象」，不另起一个只放消息的列表：
  - 验证面板本来就按 finding 逐条排版（级别徽标、位置、原文引文、期望与实际），每条只缺一句按语言渲染的说明；
  - 新字段是追加的，旧前端忽略；旧报告没有 `msg`，面板退回显示 `message`；
  - `message` 留着回喂模型，`to_dict(shown=False)` 去掉 `msg`，修复模型看到的与改造前逐字一致。
- 失败与降级选「包装代码不变，`report` 参数换成 `lines`」，不改成单条消息，也不在任务上另加 `findings` 字段：
  - 这份报告是几种来源拼起来的（结构校验、检查工具输出、旁白密度门、时长门、评审、解析失败），没有统一的 finding 结构，按行组织最贴近原样；
  - 包装代码、参数名、模板都不变，子计划 4 R3 预留的就是这一步；`failHead` 的一行显示、`job.failed_report` 的中文兜底形状、`quality_msg` 的存法都不用动；
  - 另加字段要同时改任务、版本记录、`quality_msg`、前端三处显示，收益只是少一种参数类型。
- `lines` 是 §3.1 参数类型表的新增一行。旧前端（Task 0 之前）遇到不认识的 `t` 渲染为空串，不会崩；计划仍先做前端兼容。

**逐条消息怎样产生**（「同一处生成两份」：回喂模型的原文与给用户的逐条消息在同一个函数里生成）：

| 报告来源 | 回喂模型的原文（不变） | 给用户的逐条（新） |
|---|---|---|
| 结构校验未过 | `VerificationReport.render()` | `VerificationReport.lines()`：每条 `verify.report.finding {severity, rule, path, detail}`（`severity` 是代码引用 `verify.severity.*`，`detail` 是该条规则的消息），有覆盖统计时一行 `verify.report.coverage`，末行 `verify.report.fail {n}` |
| 检查工具未过（lint、保真） | 工具输出原文 | 一项 `verify.report.tool {text}`，`text` 是厂商原文类型（脱敏、截断 6000 字） |
| 旁白密度门 | `[quality] selective 模式下旁白占比…` | `verify.quality.density`、两组标题与逐句 `verify.quality.unit`（见 D） |
| 时长门 | `[quality] N/M 个镜头…` | `verify.quality.speech` 与逐镜 `verify.quality.speech_shot` |
| 评审 | `[review] 评审总分…` | `verify.review.*`（见 D） |
| 输出无法解析 | `输出无法解析为 JSON：…` | `verify.attempt.unparseable` |
| 修复没产出新底稿 | `修复工具调用无效：…` | `verify.attempt.no_tool_call`、`verify.attempt.too_many_steps {max}` |
| 合并失败、整章终检（lint、保真）未过 | 工具输出原文 | 一项 `verify.report.tool` |
| 整章结构终检未过 | `final_report.render()` | `final_report.lines()` |

**显示处**（逐个列在计划的调用点清单里）：

| 显示处 | 数据 | 改法 |
|---|---|---|
| 验证面板：保存后（App）、渲染前被拦（RenderView）、转换任务（JobPanel） | `version.verification`、`PUT` 返回的 `verification`、422 附加字段 `verification`、`job.verification` | 说明文字用 `findingText`：有 `msg` 按代码，缺译或旧报告用 `message` |
| JobPanel 失败区 | `job.error_msg = job.failed_report` | 已走 `formatMsg`；`report` 变成 `lines` 后自动按语言渲染 |
| JobPanel 质量报告 | `job.quality_msg[]` = `job.quality.degraded` | 同上 |
| 一行显示（提示条、助手任务卡、后台任务页） | `failHead` 只取 `reason` | 不变 |
| 助手编辑卡的复验原因 | `verify.finding {path, detail}` | `detail` 由厂商原文换成该条规则的消息（子计划 4 D 已约定，形状不变） |
| 验证门提示（出片、合成） | `verify.gate.blocked` | 不变（只有一句话，没有逐条） |
| 管理后台调试日志 | 原文 | 不变（只给管理员，不翻译） |
| 命令行 | `render()`、`e.report` | 不变；质量报告打印的中文兜底随之变成逐条中文 |

### D. 质量门与评审报告的英文

- **旁白密度门**：
  - 头一行 `verify.quality.density {ratio, max}`（百分数预先格式化成字符串，如 `80%`）；
  - 两组标题 `verify.quality.density_safe`（已有画面承载、可移出旁白）、`verify.quality.density_bare`（只靠旁白承载）；
  - 每句 `verify.quality.unit {id, kind, text}`：`kind` 是 `action`/`description`/`dialogue` 原样显示，`text` 是用户自己的原文前 30 字；每组最多 40 句，与原文相同。
  - 原文里给模型的操作指示（「请逐句重新裁决」「须先把它加进…」）不进给用户的逐条，用户看的是现象与清单。
- **时长门**：`verify.quality.speech {over, total, ratio, cps, max, nominal, actual}` 一行，加每镜 `verify.quality.speech_shot {shot, have, need, gap}`，最多 40 镜；同样不含给模型的拆镜指示。
- **评审**：
  - 调用失败：`verify.review.unavailable {cause}`，`cause` 是映射后的 `llm.*` 消息（子计划 4 C），映射不出时为 `verify.review.call_failed`；
  - 输出无法核验：`verify.review.unverifiable`，不带细节（细节是我们对模型输出的格式检查，进调试日志）；
  - 打分：`verify.review.scored {overall, min, scores}`，`scores` 是 `verify.review.dim_score {dim, score}` 的列表，`dim` 是代码引用 `verify.review.dim.<维度>`；
  - 每条意见 `verify.review.issue {where, problem, fix}`，三个参数都是厂商原文类型（模型输出，不翻译），没有意见时 `verify.review.no_issues`；
  - 没过独立门槛：`verify.review.gates {gates}`，`gates` 是 `verify.review.gate.overall/weak/semantic` 的列表；
  - 回喂模型的「请针对上述 issues 逐条修改…」不进给用户的逐条。
- 数值（总分、阈值、秒数、字/秒）一律在后端预先格式化成字符串，前后端渲染与原报告的写法一致（计划 R7）。

### E. 保持原文、不翻译的部分

- **模型输出**：评审意见的 `where`、`problem`、`fix`。作为厂商原文参数，先经 `scrub_secrets`（`graph._scrub_tree`）与 `error_refs.scrub_deep` 脱敏，每项截断 300 字。界面原样显示，中文界面与英文界面都一样。子计划 4 E 节的要求照旧：这些文字可能带模型自报的名字，不额外过滤（R10 同理），但我们自己的文案与代码表里不得出现模型名。
- **外部库原文**：`SCHEMA-001` 的 jsonschema `error.message`（英文，常引用文档里的值）。
- **检查工具输出**：lint、保真、合并工具的子进程输出（中文）。见 A「不在本子计划」。
- **数据**：句子与镜头编号、JSON 路径、字段名（`text`、`para`）、`kind` 枚举、用户原文、用户写的创作限制、角色名。

### F. 兼容

- **旧报告**（版本记录里存的 `verification`、助手存档里的编辑卡、旧 `error_msg` 与 `quality_msg`）：都不迁移。
  - finding 没有 `msg`：面板显示 `message`（与现在相同，多数是英文原文）；
  - `report` 参数是厂商原文：照旧原样显示；
  - 编辑卡 `detail` 是厂商原文：照旧原样显示。
- **旧前端**：`msg` 字段忽略；`lines` 类型渲染为空串（报告正文消失，但不崩）。计划先做前端兼容（Task 0），之后才改后端形状。
- **回喂模型**：修复请求（`repair_request`）、`validation_list` 工具结果、整份重写的回喂、评审重试的回喂，与改造前逐字一致，由测试守护。
- **中文兜底的文字变化**：`job.failed_report` 与 `job.quality.degraded` 的 `message`（以及由它生成的 `error`、`quality_report` 字符串）从「原因 + 报告原文」变成「原因 + 逐条中文」；给模型的操作指示不再出现在里面。完整原文仍在调试日志与工作目录的失败报告文件里。
- **`verification_identity`**：对 `to_dict()` 取哈希，多了 `msg` 后哈希值会变。目前没有调用方，不处理。

### G. 测试补充

- 后端：
  - 新增 `tests/pipeline/test_verify_msgs.py`：
    - 23 条规则各一条触发用例，断言代码与参数；源码里出现的规则编号与登记的 `verify.rule.*` 一一对应；
    - 原文是中文的三条：`message` 与旧写法一字不差；
    - 回喂模型：`validation_list` 不含 `msg`/`params`，指定规则的条目与改造前的字典完全相等，`repair_request` 里没有 `verify.rule`；
    - `VerificationReport.lines()`：逐条、覆盖统计、末行；
    - 两道质量门与评审：回喂模型的报告与改造前一字不差（特征断言先于改动写好），逐条消息的代码与参数正确，评审意见是厂商原文；
  - `test_messages.py`：`lines_of()` 的截断与 `common.more_lines`、`_zh_value` 换行连接；
  - `test_error_refs.py`：`scrub_deep` 不动 `code` 与 `t`；
  - `test_graph.py`：硬失败的 `ConversionError.lines`、解析失败的 `verify.attempt.unparseable`、降级警告的 `report` 是 `lines`、桩掉 `_check_batch` 时退回厂商原文、整章结构终检失败带 `lines`；
  - `test_offline.py`：降级警告的断言由 `["text"]` 改为 `lines` 与中文兜底；
  - `test_jobs.py`：`_execute` 用 `e.lines` 生成 `report`，数据目录被替换；验证门 422 的 finding 带 `msg`；
  - `test_assistant_ops.py`：编辑卡复验原因的 `detail` 是 `verify.rule.*`；
  - `test_novels.py`：保存后返回的 finding 带 `msg`；
  - ast 扫描：`Finding(…)` 与 `report.add(…)` 加进出口规则；`MODULES` 加 `pipeline/verification.py`、`pipeline/quality.py`、`pipeline/repair.py`（全文件）与 `pipeline/novel_memory.py` 的 `soft_findings`。改动前的基线：新规则下 3 处（`ORDER-001` 与两条软核查），`repair.py` 现有规则下 14 处（标 `# i18n: llm`）。扫描结果要清零。
- 前端：
  - `server-msg.test.ts`：`lines` 渲染（中英、嵌套在 `job.failed_report` 里、`failHead` 仍只取原因）、未知 `t` 为空串、`findingText` 的三种回落；
  - `workspace.test.tsx`（JobPanel）：失败区与质量报告的 `lines` 中英渲染；任务验证面板的 finding 按代码渲染、旧 finding 显示 `message`；
  - `flow.test.tsx`：保存后与渲染被拦的验证面板切英文后跟着变；
  - `assistant.test.tsx`：编辑卡复验原因里嵌套规则消息的中英渲染，旧存档的厂商原文照旧显示。

### H. 代码命名（新登记）

全部在 `verify` 域（与子计划 4 的 `verify.gate.blocked`、`verify.finding` 不冲突），另加 `common.more_lines`：
- `verify.rule.<rule_id>`：B 节 23 条；
- `verify.severity.critical/high/medium/low`、`verify.lifecycle.deceased/departed`；
- `verify.report.finding/coverage/pass/fail/tool`；
- `verify.attempt.unparseable/no_tool_call/too_many_steps`；
- `verify.quality.density/density_safe/density_bare/unit/speech/speech_shot`；
- `verify.review.unavailable/call_failed/unverifiable/scored/dim_score/issue/no_issues/gates`、`verify.review.dim.<四个维度>`、`verify.review.gate.overall/weak/semantic`。

叶子与前缀已逐个核对：`verify.review.gates` 与 `verify.review.gate.*`、`verify.review.dim_score` 与 `verify.review.dim.*` 按「.」分段不构成前缀关系。规则编号里的连字符（`SCHEMA-001`）在 `srv` 节点里写成带引号的键。完整列表与中英文案见计划。

### 修订记录

- 2026-11-14 子计划 4 交付后起草。§3.7「回喂模型的仍是原来的中文 message」更正为「原文（多为英文）一字不改」。
