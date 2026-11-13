# 后端对用户文字统一中英双语 设计

日期：2026-11-13
状态：已过设计审查（Opus），修订完毕；子计划 1、2 已交付；子计划 2、3 范围已补充（见文末）

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
