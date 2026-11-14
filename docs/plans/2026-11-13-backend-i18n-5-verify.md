# 后端双语 子计划 5：验证报告逐条（规则代码、质量门与评审报告）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 验证报告与质量报告的正文按界面语言显示：
- 验证面板的每条说明按 `verify.rule.<rule_id>` 渲染（23 条规则各给结构化参数）；
- 转换失败的报告（`job.failed_report`）与降级交付的质量报告（`job.quality.degraded`）正文由「一段原文」改为逐条消息，结构校验、旁白密度门、时长门、评审、解析失败都有中英文案；
- 回喂模型的文字（`Finding.message`、`render()`、质量门与评审的报告、修复请求）与改造前一字不差；
- 模型输出（评审意见）、jsonschema 原文、检查工具的子进程输出作为厂商原文原样显示。

**Architecture:** 沿用子计划 1–4 的基础设施：
- 后端：`server/messages.py` 的 `register`/`msg`/`compact`/`vendor`/`ref`/`REPORT_MAX`，`server/error_refs.py` 的 `scrub_text`，`pipeline/graph.py` 的 `_scrub_tree`；
- 前端：`i18n/serverMsg.ts` 的 `formatMsg`/`failHead`，`srv` 文案节点；
- 两道校验：`srv-codes` 与 ast 扫描。

新机制有三处：
- 参数类型 `lines`（`{"t":"lines","items":[…]}`）与 `messages.lines_of()`：逐条报告，前端逐项渲染、换行连接；
- `Finding.params` / `Finding.as_msg()` / `to_dict(shown=…)` 与 `VerificationReport.lines()`：同一条 finding 既有回喂模型的原文，又有给界面的消息对象；
- 出参 `lines_out`（照 `warnings_out`、`manifest_out` 的写法）：质量门、评审、`_check_batch` 在生成回喂模型的报告的同一处，把给用户的逐条消息追加进调用方的列表。

**Tech Stack:** Python 3.12、FastAPI 0.143（`TestClient`）、LangGraph 1.2、jsonschema、脚本式测试、React 19 + TypeScript、Vite SSR 构建跑前端测试。

**Spec:** `docs/specs/2026-11-13-backend-i18n-design.md`（§3.7、§8、§9 第 5 项 + 文末「子计划 5 范围补充」A–H 八节）。本计划与 spec 冲突时以 spec 为准；spec 没写的细节见文末「实施裁定」。

---

## 全局约束（每个 Task 都必须遵守）

- 不读、不打印 `backend/.env`；密钥不进日志、报错、错误记录、调试日志、章节与版本记录、消息参数。新加进消息参数的原文一律先脱敏（`scrub_secrets`、`graph._scrub_tree` 或 `error_refs.scrub_deep`）。
- 不调用任何付费厂商与模型服务；不运行 `backend/render/smoke.py`、`backend/render/smoke_tts.py`、`backend/assistant/smoke.py`；不向运行中的 5173 / 8000 服务发请求。
- 测试绝不联网、不读真实 `.env`：
  - 接口测试用 `TestClient` 或直接调用 app 里的函数；
  - 导入 `server.*`、`render.*`、`pipeline.*` 之前：
    - `STORYBOARD_DATA_DIR` 设为临时目录；
    - 把 `pipeline.config._load_dotenv` 换成空操作（照 `tests/server/test_novels.py` 现有写法）；
  - **模型调用一律打桩**：转换用 `FakeChat`（`tests/pipeline/fakes.py`）或替换 `app_mod.convert_text`；评审用本计划测试里的 `Stub`（只有 `invoke`/`text` 两个方法的替身）；模型接口的异常用 `anthropic.*Error(..., response=httpx2.Response(...), body=...)` 在本地构造，不发请求；
  - 新测试文件在导入前另设 `os.environ["ANTHROPIC_BASE_URL"] = "http://127.0.0.1:9"`、`os.environ["ANTHROPIC_API_KEY"] = "sk-test-not-real"` 作保险：万一漏了桩，请求也只会打到本机不可达端口，不会到达真实模型服务。
- 不动 `docs/specs/2026-10-27-commercialization-design-contract.md`（未跟踪文件）。
- git：
  - 只 `git add` 具体文件，禁止 `git add -A` / `git commit -a` / `git add -N`；
  - 提交信息中文、描述性，不带任何 `Co-Authored-By` 或署名行；
  - 不 push。
- 改了登记表就运行 `cd backend && .venv/bin/python -m server.messages --write`，把 `backend/server/messages_codes.json` 一起提交。登记了新代码的 Task 必须同时在 `zh.ts`、`en.ts` 的 `srv` 节点加上对应键（`srv-codes` 会校验键齐全、中文一字不差、占位符一致）。规则编号带连字符，`srv` 里写成带引号的键：`'SCHEMA-001': '…'`。
- 每个 Task 结束时必须全部通过：
  - 后端（在 `backend/` 下）：
    `fail=0; for t in tests/pipeline/test_*.py tests/server/test_*.py tests/render/test_*.py tests/assistant/test_*.py; do .venv/bin/python $t >/dev/null || { echo FAIL $t; fail=1; }; done; echo fail=$fail`
    输出 `fail=0`（每个脚本自己打印 `ALL PASS`；不要只看最后一行）。
  - 前端（在 `frontend/` 下）：
    - `npm test` 退出码 0（直接检查 `$?`，不要接管道）；
    - `npm run lint` 0 error、warning 不多于基线 5 条；
    - `npm run build` 成功。
  - 已知既有问题：`frontend/tests/film.test.tsx` 偶发 CPU 自旋卡死（与本计划无关）。遇到时：
    - 单独重跑判定：`npx vite build --ssr tests/film.test.tsx --outDir /tmp/i18n-film --logLevel error && timeout 60 node /tmp/i18n-film/film.test.js`，通过即可；
    - 然后把 `npm test` 里 film 之后的测试逐个跑完；
    - 临时输出不要留在仓库里。
- **回喂模型的文字一字不改**：`Finding.message`、`VerificationReport.render()`、`quality.narration_density_gate`/`speech_fit_gate` 与 `review.run_review` 返回的报告字符串、`repair.repair_request`、`validation_list` 工具结果、`plan_repair` 拼的回喂消息。本计划的特征测试（Task 2、3）在改动前先写好并通过，改动后必须照样通过。
- 中文兜底：原文本来是中文的三条规则（`ORDER-001`、`NOVEL-CONSTRAINT-001`、`NOVEL-LIFECYCLE-001`）模板与原文一字不差；其余新代码的中文是新写的说明，以本计划给出的为准。
- 英文文案由实现者按本计划给出的初稿落地，风格照现有 `en.ts` `srv` 节点：
  - 冒号后半角空格；
  - 不依赖单复数（照子计划 4 验收补修的写法：数量放在冒号后或括号里）；
  - 不出现 `.env`、环境变量名、异常类名、模型名或厂商名（DeepSeek、Claude、Anthropic 等）。

## 范围边界

- **本子计划改**：
  - 后端：
    - `pipeline/verification.py`（`Finding`、`VerificationReport.add/lines`、`tool_line`、23 条规则的参数）；
    - `pipeline/novel_memory.py`（`soft_findings` 两条规则）；
    - `pipeline/repair.py`（`validation_list` 用 `to_dict(shown=False)`；14 处 `RepairError` 标 `# i18n: llm`）；
    - `pipeline/quality.py`（两道门的 `lines_out`）、`pipeline/review.py`（`run_review` 的 `lines_out`）；
    - `pipeline/graph.py`（`_check_batch` 的 `lines_out`、`BatchState.shown`、`_shown`、`_report_param`、候选、`finalize`、`repair_agent`）、`pipeline/convert.py`（三处 `ConversionError` 带逐条）、`pipeline/errors.py`（`ConversionError.lines`）；
    - `server/messages.py`（`lines` 类型、`lines_of`、`LINES_MAX`、登记表）、`messages_codes.json`、`server/error_refs.py`（`scrub_deep`）；
    - `server/app.py`：`_execute`、`_check_version_doc`；
    - `tests/server/test_i18n_scan.py`（规则、`MODULES`）。
  - 前端：`i18n/serverMsg.ts`、`zh.ts`、`en.ts`、`types.ts`、`components/VerificationPanel.tsx`。
- **不改**：
  - 检查工具（`tools/lint_storyboard.py`、`check_fidelity.py`、`merge_storyboard.py`）的输出：原文原样显示（R6）；
  - 尝试记录 `manifest.attempts[].report`：照旧存原文（R12）；
  - 转换途中按规则代码发进度事件（子计划 4 R13 的可选项，spec 子计划 5 A）；
  - 提示词、`review.REVIEW_SYSTEM`、修复回喂的拼法；
  - 验证门 `verify.gate.blocked` 与编辑卡 `verify.finding` 的形状（只换 `detail` 的值）。

## 调用点清单

### 逐条规则（`pipeline/verification.py`、`pipeline/novel_memory.py`，Task 2）

| rule_id | 函数 | 级别 | 现在的 `message`（回喂模型，不改） | `params` |
|---|---|---|---|---|
| `SCHEMA-ENGINE-001` | `_validate_schema` | critical | `jsonschema is unavailable; structural verification cannot run` | — |
| `SCHEMA-001` | `_validate_schema` | high | `error.message` | `detail=vendor(error.message)` |
| `SOURCE-FROZEN-001` | `_validate_frozen_units` | critical | `model changed the deterministic source-unit count` | `expected=len(expected)`、`actual=len(actual)` |
| `SOURCE-FROZEN-002` | 同上 | critical | `model changed immutable source evidence` | `unit=exp.get("id", "")`、`field=key` |
| `SOURCE-WAIVER-001` | 同上 | high | `skipped source units require an explicit reviewable reason` | `unit=exp.get("id", "")` |
| `ID-UNIT-001` | `_validate_identity` | critical | `duplicate unit id {duplicate}` | `id=duplicate` |
| `ID-EPISODE-001` | 同上 | high | `duplicate episode id {duplicate}` | `id=duplicate` |
| `ID-SHOT-001` | 同上 | high | `duplicate shot id {duplicate}` | `id=duplicate` |
| `ID-ASSET-001` | 同上 | high | `duplicate asset id {duplicate}` | `id=duplicate` |
| `REF-UNIT-001` | `_validate_evidence` | high | `shot references unknown source unit {ref}` | `unit=ref` |
| `EVIDENCE-INFERENCE-001` | 同上 | high | `inferred shots require a concrete derivation note` | — |
| `EVIDENCE-SHOT-001` | 同上 | high | `non-transition shots require source evidence` | — |
| `EVIDENCE-RANGE-001` | 同上 | medium | `shot evidence should normally be 1-3 adjacent units` | — |
| `ORDER-001` | 同上 | medium | `镜头回跳到更早的原文（上一处 {prev_label} 引至 u{prev_number:04d}）` | `prev=prev_label`、`unit=f"u{prev_number:04d}"`；`message` 改由模板生成 |
| `FID-DIALOGUE-001` | 同上 | critical | `dialogue is not a verbatim excerpt of its cited source units` | — |
| `REF-NARRATION-001` | 同上 | high | `narration references unknown source unit {ref}` | `unit=ref` |
| `FID-NARRATION-001` | 同上 | medium | `narration text is not a direct excerpt of its cited source units` | — |
| `COVERAGE-001` | 同上 | critical | `source units are not carried by narration, dialogue, or visuals` | `n=len(failed)` |
| `COVERAGE-DECLARED-001` | 同上 | high | `declared coverage differs from deterministic coverage` | — |
| `COVERAGE-DECLARED-002` | 同上 | medium | `declared inferred ratio differs from deterministic result` | — |
| `FID-SOURCE-001` | `verify_document` | critical | `source units do not reconstruct the normalized input` | — |
| `NOVEL-CONSTRAINT-001` | `novel_memory.soft_findings` | medium | `镜头 {sid} 的画面描述含限制关键词「{'、'.join(hit)}」（限制：…），请人工确认是否违规` | `shot=sid`、`keywords=hit`、`constraint=c.get("text", "")`；`message` 改由模板生成 |
| `NOVEL-LIFECYCLE-001` | 同上 | medium | `镜头 {sid} 里出现了{state}的角色 {ref}{name}，…请人工确认是不是闪回` | `shot=sid`、`state=ref("verify.lifecycle.deceased"/"departed")`、`character=f"{ref}{name}"`；`message` 改由模板生成 |

### 报告来源（`pipeline/*`）

| 位置 | 现状 | 处置 | Task |
|---|---|---|---|
| `verification.Finding.to_dict` | 去空字段的字典 | 多一个 `msg`；`to_dict(shown=False)` 为旧形状 | 2 |
| `verification.VerificationReport.render` | 逐行原文 | 不改（回喂模型、调试日志、命令行） | — |
| 新增 `VerificationReport.lines()` | — | `verify.report.finding` 逐条 + `verify.report.coverage` + `verify.report.pass/fail` | 2 |
| 新增 `verification.tool_line(text)` | — | `verify.report.tool {text=vendor}` | 4 |
| `repair.validation_list` | `finding.to_dict()` | `finding.to_dict(shown=False)`（`# i18n: llm`） | 2 |
| `repair.py` 14 处 `raise RepairError(中文)` | 回喂模型，扫描未覆盖 | 行尾 `# i18n: llm`，`repair.py` 进 `MODULES` | 2 |
| `quality.narration_density_gate` | 返回 `(ok, 报告, 占比)` | 加 `lines_out`：`verify.quality.density`、`density_safe`/`density_bare`、`unit` | 3 |
| `quality.speech_fit_gate` | 返回 `(ok, 报告, 超时比例)` | 加 `lines_out`：`verify.quality.speech`、`speech_shot` | 3 |
| `review.run_review` 调用失败 | `[review] 评审服务不可用：{mapped}` | 加 `lines_out`：`verify.review.unavailable {cause}` | 3 |
| `review.run_review` 输出不可验证 | `[review] 评审输出不可验证（{e}）` | `verify.review.unverifiable` | 3 |
| `review.run_review` 打分 | `[review] 评审总分…`、意见逐行、门槛 | `verify.review.scored`、`issue`（厂商原文）/`no_issues`、`gates` | 3 |
| `graph._check_batch` | 返回 `(ok, hard, 报告, 择优键, 结构化报告)` | 加 `lines_out`；结构校验未过 → `structured.lines()`；lint/保真未过 → `tool_line`；通过时清空 | 4 |
| `graph.generate` / `check` 解析失败 | `report = "输出无法解析为 JSON…"` | `shown = verify.attempt.unparseable` | 4 |
| `graph.repair_agent` 两处 `repair_failed` | `report = "修复工具调用无效：…"` | `shown = verify.attempt.too_many_steps {max}` / `no_tool_call` | 4 |
| `graph.check` 候选 | `(key, attempt, doc, report)` | `(key, attempt, doc, report, shown)` | 4 |
| `graph.finalize` 降级警告 | `report=vendor(scrub_secrets(report), limit=REPORT_MAX)` | `report=_report_param(report, shown)` | 4 |
| `graph.finalize` `job.batch_failed` | `ConversionError.of(code, report, …)` | 第二个位置参数后加 `_scrub_tree(state["shown"])` | 4 |
| `convert.py` `job.merge_failed` | `ConversionError.of(code, out)` | 加 `[tool_line(out)]` | 4 |
| `convert.py` `job.final_verify_failed` | `ConversionError.of(code, final_report.render())` | 加 `final_report.lines()` | 4 |
| `convert.py` `job.final_check_failed` | `ConversionError.of(code, lint_out + "\n" + fid_out)` | 加 `[tool_line(…)]` | 4 |
| `errors.ConversionError` | `(msg, report="")` | `(msg, report="", lines=None)`，属性 `lines` | 1 |
| `__main__.py` | 打印 `render()`、`e.report`、质量报告中文兜底 | 不改（质量报告的中文兜底随之变成逐条中文） | — |

### `server/app.py`

| 函数 | 现状 | 处置 | Task |
|---|---|---|---|
| `_execute` | `report=vendor(error_refs.scrub_text(e.report), limit=REPORT_MAX)` | 有 `e.lines` 时 `report=lines_of(error_refs.scrub_deep(e.lines))`，否则照旧 | 5 |
| `_check_version_doc` | `detail=vendor(f.message)` | `detail=f.as_msg()` | 5 |
| `_render_gate` | 422 附加字段 `verification = report.to_dict()` | 不改代码；finding 自动带 `msg` | 5（测试） |
| `_reverify` / `_save_version_doc` / `versions_update` | 返回并保存 `report.to_dict()` | 不改代码；自动带 `msg` | 5（测试） |
| `versions_get`、`get_job`、`render_plan` | 透出已存的 `verification` | 不改；旧记录没有 `msg` | — |
| `_public_manifest` | 尝试记录 `report` 换路径占位 | 不改 | — |

### 显示处（前端）

| 显示处 | 文件 | 数据 | 处置 | Task |
|---|---|---|---|---|
| 保存后的验证面板 | `App.tsx`:947/952 → `VerificationPanel` | `version.verification`、`PUT` 返回的 `verification` | `FindingRow` 用 `findingText` | 0（代码）、6（测试） |
| 渲染前被拦 | `RenderView.tsx`:69 → `VerificationPanel origin="render"` | 422 附加字段 `verification`（`ApiError.verification`） | 同上 | 0、6 |
| 转换任务的验证面板 | `JobPanel.tsx`:77 | `job.verification` | 同上 | 0、6 |
| 转换失败区 | `JobPanel.tsx`:70 | `job.error_msg`（`job.failed_report`，`report` 为 `lines`） | `formatMsg` 认 `lines` | 0、6 |
| 质量报告 | `JobPanel.tsx`:26 | `job.quality_msg[]`（`job.quality.degraded`） | 同上 | 0、6 |
| 一行显示：版本提示条、助手任务卡、后台任务页 | `App.tsx`、`TaskCard.tsx`、`admin/JobsTab.tsx` | `failHead` 只取 `reason` | 不改；Task 0 测试守护 | 0 |
| 助手编辑卡的复验原因 | `assistant/ActionCard.tsx`:66 | `warnings[]` = `verify.finding {path, detail}` | 已走 `formatMsg`；`detail` 变成嵌套规则消息 | 6（测试） |
| 镜头问题标记 | `shotFocus.ts`:15 | 只读 `severity`、`object_path` | 不改 | — |
| 验证门提示（出片、合成、时间线） | `useFilm.ts`、`compose.ts`、`FilmPanel.tsx`、`TimelineCanvas.tsx` | `verify.gate.blocked` | 不改 | — |
| 管理后台调试日志 | `admin/JobsTab.tsx` | 原文 | 不改（只给管理员） | — |

## 文件结构

| 文件 | 本计划的改动 |
|---|---|
| `backend/server/messages.py` | `LINES_MAX`、`lines_of`、`_zh_value` 认 `lines`；登记 `common.more_lines` 与 `verify.*` |
| `backend/server/error_refs.py` | `scrub_deep` |
| `backend/pipeline/errors.py` | `ConversionError.lines` |
| `backend/pipeline/verification.py` | `Finding.params/code/as_msg/to_dict(shown=)`、`add(message="")`、`lines()`、`tool_line`、各规则参数 |
| `backend/pipeline/novel_memory.py`、`repair.py`、`quality.py`、`review.py`、`graph.py`、`convert.py` | 见调用点清单 |
| `backend/server/app.py` | `_execute`、`_check_version_doc` |
| `backend/tests/pipeline/test_verify_msgs.py`（新） | 规则逐条、回喂不变、`lines()`、质量门与评审 |
| `backend/tests/server/test_messages.py`、`test_error_refs.py`、`test_i18n_scan.py`、`test_jobs.py`、`test_assistant_ops.py`、`test_novels.py`，`backend/tests/pipeline/test_graph.py`、`test_offline.py` | 见各 Task |
| `frontend/src/i18n/serverMsg.ts`、`zh.ts`、`en.ts`、`types.ts`、`components/VerificationPanel.tsx` | `lines`、`findingText`、`srv.verify.*`、`Finding.msg` |
| `frontend/tests/server-msg.test.ts`、`workspace.test.tsx`、`flow.test.tsx`、`assistant.test.tsx` | 见 Task 0、6 |

---

### Task 0: 前端先行兼容（`lines` 参数类型、finding 的 `msg`）

后端 Task 2 给每条 finding 加 `msg`，Task 4 把报告参数从厂商原文换成 `lines`。现行前端遇到不认识的 `t` 渲染为空串：报告正文会消失，但不会崩（与子计划 4 的「对象当 React 子节点」不同）。仍然先做前端兼容，保证每个中间提交前后端一起跑时，界面上的信息不比现在少。

**Files:**
- Modify: `frontend/src/i18n/serverMsg.ts`（`value` 认 `lines`；新增 `findingText`）
- Modify: `frontend/src/types.ts`（`Finding.msg?: ServerMsg`）
- Modify: `frontend/src/components/VerificationPanel.tsx`（`FindingRow` 的说明文字）
- Test: `frontend/tests/server-msg.test.ts`

- [ ] **Step 1: 写失败测试**：`server-msg.test.ts` 顶部的导入加上 `findingText`（`import { formatMsg, itemError, errValue, failHead, findingText } from '../src/i18n/serverMsg'`），文件末尾 `ALL PASS` 之前加一节：
  ```ts
  // 子计划 5：报告参数的 lines 类型（逐项渲染、换行连接）；验证报告一条的说明（spec 子计划 5 C）
  {
    const wrapL = (items: unknown) => ({ code: 'common.unknown', params: { message: { t: 'lines', items } } })
    must(formatMsg(wrapL([{ code: 'common.unknown', params: { message: 'a' } }, { t: 'vendor', text: 'b' }, 'c']) as never, 'en') === 'a\nb\nc',
      'lines 逐项渲染、换行连接')
    must(formatMsg(wrapL([]) as never, 'zh') === '', '空 lines 为空串')
    must(formatMsg(wrapL('x') as never, 'zh') === '', 'items 不是数组时为空串')
    must(formatMsg({ code: 'common.unknown', params: { message: { t: 'future', x: 1 } } } as never, 'en') === '', '不认识的 t 为空串（不崩）')
    const reason = { code: 'job.batch_failed', params: { batch: 2, retries: 3 } }
    const failed = { code: 'job.failed_report', params: { reason, report: { t: 'lines', items: [
      { code: 'common.unknown', params: { message: 'L1' } }, { code: 'common.unknown', params: { message: 'L2' } }] } } }
    must(formatMsg(failed, 'en') === en.srv.job.failed_report.replace('{reason}', formatMsg(reason, 'en')).replace('{report}', 'L1\nL2'),
      'failed_report 里的 lines（英文）')
    must(formatMsg(failed, 'zh') === `${zh.srv.job.batch_failed.replace('{batch}', '2').replace('{retries}', '3')}\nL1\nL2`, 'failed_report 里的 lines（中文）')
    must(formatMsg(failHead(failed), 'zh') === formatMsg(reason, 'zh'), '一行显示仍只取原因')
    must(findingText({ message: 'old' }) === 'old', '旧 finding（没有 msg）显示 message')
    must(findingText({ message: 'old', msg: { code: 'x.not.registered', params: {} } }, 'en') === 'old', '缺译回落到 message，不显示代码名')
    must(findingText({ message: 'old', msg: { code: 'common.unknown', params: { message: 'new' } } }, 'en') === 'new', '有 msg 按代码渲染')
    console.log('子计划 5：lines / findingText ✓')
  }
  ```
- [ ] **Step 2: 运行确认失败**：`cd frontend && npm test`，`typecheck` 报 `findingText` 不存在。
- [ ] **Step 3: 实现**
  - `serverMsg.ts` 的 `value()`，`vendor` 那一行之后加：
    ```ts
        if (v.t === 'lines') return Array.isArray(v.items) ? v.items.map((x) => value(x, l)).join('\n') : ''
    ```
  - `serverMsg.ts` 末尾加：
    ```ts
    /** 验证报告一条的说明：有 msg（verify.rule.<rule_id>）按代码渲染，缺译回落到原 message；
     *  旧报告没有 msg，显示 message（spec 子计划 5 C、F） */
    export function findingText(f: { message?: string; msg?: ServerMsg | null }, locale: Locale = currentLocale()): string {
      if (!f.msg) return f.message ?? ''
      return formatMsg({ ...f.msg, message: f.message ?? f.msg.message }, locale)
    }
    ```
  - `types.ts` 的 `Finding`，`message: string` 之后加：
    ```ts
      /** 说明的消息对象（verify.rule.<rule_id>），界面按语言渲染；message 是回喂模型的原文。旧报告没有 */
      msg?: ServerMsg
    ```
  - `VerificationPanel.tsx`：
    - 导入加 `import { findingText } from '@/i18n/serverMsg'`；
    - `FindingRow` 里 `const { t } = useI18n()` 改为 `const { t, locale } = useI18n()`；
    - `<p className="vf__msg">{f.message}</p>` 改为 `<p className="vf__msg">{findingText(f, locale)}</p>`。
- [ ] **Step 4: 跑全部校验并提交**：
  ```bash
  git add frontend/src/i18n/serverMsg.ts frontend/src/types.ts frontend/src/components/VerificationPanel.tsx frontend/tests/server-msg.test.ts
  git commit -m "前端先行兼容子计划 5 的报告形状：消息参数认逐条类型 lines（逐项渲染、换行连接），验证面板的每条说明有消息对象就按代码渲染，缺译与旧报告显示原文"
  ```

---

### Task 1: 后端基础（`lines` 参数类型、`scrub_deep`、`ConversionError.lines`、扫描规则）

**Files:**
- Modify: `backend/server/messages.py`（`LINES_MAX`、`lines_of`、`_zh_value`；登记 `common.more_lines`）、`backend/server/messages_codes.json`
- Modify: `backend/server/error_refs.py`（`scrub_deep`）
- Modify: `backend/pipeline/errors.py`（`ConversionError.lines`）
- Modify: `backend/tests/server/test_i18n_scan.py`（`Finding(…)`、`report.add(…)` 出口与自检用例；`MODULES` 本 Task 不加模块）
- Modify: `frontend/src/i18n/zh.ts`、`en.ts`（`srv.common.more_lines`）
- Test: `backend/tests/server/test_messages.py`、`backend/tests/server/test_error_refs.py`、`backend/tests/pipeline/test_graph.py`

- [ ] **Step 1: 写失败测试**
  - `test_messages.py` 新增一节（放在子计划 4 那一节之后）：
    ```python
    # 子计划 5：逐条报告参数 lines（spec 子计划 5 C）
    L = M.lines_of([M.msg("common.unknown", message="a"), M.vendor("b"), "c"])
    assert L == {"t": "lines", "items": [{"code": "common.unknown", "params": {"message": "a"}},
                                         {"t": "vendor", "text": "b"}, "c"]}, "消息对象压成紧凑形，其余原样"
    assert M.render_zh("common.unknown", {"message": L}) == "a\nb\nc", "中文兜底换行连接"
    big = M.lines_of([M.msg("common.unknown", message=str(i)) for i in range(M.LINES_MAX + 7)])
    assert len(big["items"]) == M.LINES_MAX + 1 == 101
    assert big["items"][-1] == {"code": "common.more_lines", "params": {"n": 7}}
    assert M.render_zh("common.more_lines", {"n": 7}) == "…还有 7 行未显示"
    print("子计划 5：lines_of / 截断 / 中文兜底 ✓")
    ```
  - `test_error_refs.py` 新增 `part_scrub_deep()`，在 `main()` 末尾调用：
    ```python
    def part_scrub_deep():
        raw = f"{auth.DATA_DIR}/users/x key={LLM_KEY}"
        m = M.compact(M.msg("job.failed_report", reason=M.compact(M.msg("job.batch_failed", batch=1, retries=0)),
                            report=M.lines_of([M.msg("common.unknown", message=M.vendor(raw))])))
        out = error_refs.scrub_deep(m)
        blob = json.dumps(out, ensure_ascii=False)
        assert str(auth.DATA_DIR) not in blob and LLM_KEY not in blob and "<data>" in blob, blob
        assert out["code"] == "job.failed_report" and out["params"]["report"]["t"] == "lines"
        assert out["params"]["report"]["items"][0]["code"] == "common.unknown", "code 与 t 不动"
        assert m["params"]["report"]["items"][0]["params"]["message"]["text"] == raw, "不改调用方的对象"
        print("6. scrub_deep：字符串逐个脱敏，code 与 t 不动 ✓")
    ```
  - `test_graph.py` 第 3 节（`坏输出`）的 `except ConversionError as e:` 里先加一条，确认构造参数的形状（本 Task 只断言默认值，Task 4 再断言内容）：
    ```python
            assert isinstance(e.lines, list), "ConversionError 带逐条消息（spec 子计划 5 C）"
    ```
    同时在文件里任一处（如第 3 节之后）加：
    ```python
    e = ConversionError.of("job.merge_failed", "原文", [{"code": "common.unknown", "params": {"message": "x"}}])
    assert e.report == "原文" and e.lines == [{"code": "common.unknown", "params": {"message": "x"}}] and e.code == "job.merge_failed"
    assert ConversionError("无代码").lines == []
    ```
  - `test_i18n_scan.py` 的自检 `cases` 追加：
    ```python
        # 子计划 5：验证报告的两个出口（回喂模型的原文标 # i18n: llm；给界面的走代码）
        ('def f(r, x):\n    r.add("A", "high", "/", "中文")\n    report.add("A", "high", "/", f"中文{x}")\n', 1),
        ('def f(p):\n    Finding("A", "medium", p, "中文")\n', 1),
        ('def f(p):\n    report.add("A", "high", p, "english")\n    Finding("A", "medium", p, params={"x": 1})\n', 0),
        ('def f(p):\n    report.add("ORDER-001", "medium", p, "中文")  # i18n: llm\n', 0),
    ```
- [ ] **Step 2: 运行确认失败**：`cd backend && .venv/bin/python tests/server/test_messages.py` 报 `AttributeError: lines_of`；`test_error_refs.py` 报 `scrub_deep`；`test_graph.py` 报 `AttributeError: lines`；`test_i18n_scan.py` 报「自检用例 16 应命中 1 处，实际 0」。
- [ ] **Step 3: `messages.py`**
  - `REPORT_MAX` 下面加：
    ```python
    LINES_MAX = 100          # lines 参数（逐条报告）最多几项；超出的截掉，末尾补一项 common.more_lines
    ```
  - 模块文档字符串的参数类型一句补上「逐条报告 {"t":"lines","items":[…]}」。
  - `_zh_value` 的 `if t == "vendor": …` 之后加：
    ```python
            if t == "lines":
                return "\n".join(_zh_value(x) for x in v.get("items") or [])
    ```
  - `msg()` 之后加：
    ```python
    def lines_of(items, limit: int = LINES_MAX) -> dict:
        """逐条报告参数：前端逐项渲染、换行连接（spec 子计划 5 C）。
        消息对象压成 {code, params}；字符串与带类型的值（如厂商原文）原样。超过 limit 项截掉，末尾说还有几项。"""
        out = [compact(x) if isinstance(x, dict) and "code" in x and "t" not in x else x for x in items]
        if len(out) > limit:
            out = out[:limit] + [compact(msg("common.more_lines", n=len(out) - limit))]
        return {"t": "lines", "items": out}
    ```
  - 登记表 `common.internal` 之后加：`register("common.more_lines", "…还有 {n} 行未显示")`。
  - `.venv/bin/python -m server.messages --write`。
- [ ] **Step 4: `error_refs.py`**：`scrub_text` 之后加：
  ```python
  _KEEP_KEYS = ("code", "t")      # 消息对象的代码与参数类型标记：不是文字，不脱敏


  def scrub_deep(v):
      """消息对象（含嵌套消息、列表、lines、厂商原文）里的字符串逐个 scrub_text；code 与 t 不动，返回新对象。"""
      if isinstance(v, str):
          return scrub_text(v)
      if isinstance(v, list):
          return [scrub_deep(x) for x in v]
      if isinstance(v, dict):
          return {k: x if k in _KEEP_KEYS else scrub_deep(x) for k, x in v.items()}
      return v
  ```
- [ ] **Step 5: `pipeline/errors.py`**：
  ```python
  class ConversionError(UserError, RuntimeError):
      """转换失败。带代码的（ConversionError.of(code, report, lines, **params)）str() 是中文兜底、不含服务器路径。
      report 是校验报告原文（回喂模型的那份，不翻译；调试日志与命令行用）；
      lines 是同一份报告给用户看的逐条消息（spec 子计划 5 C），app 用它作 job.failed_report 的 report 参数，
      没有逐条时退回 report 原文。"""

      def __init__(self, msg: str, report: str = "", lines=None):
          super().__init__(msg)
          self.report = report
          self.lines = list(lines or [])
  ```
  （`UserError.of(code, *args, **params)` 把位置参数原样传给构造函数，所以 `of(code, report, lines, batch=…)` 不用改 `of`。）
- [ ] **Step 6: 扫描规则**（`test_i18n_scan.py`）
  - `SINK_CALLS` 加 `"Finding"`；
  - `_sinks` 的 `ast.Call` 分支里，`job["log"].append` 判断之后加：
    ```python
                if (isinstance(f, ast.Attribute) and f.attr == "add" and isinstance(f.value, ast.Name)
                        and f.value.id == "report"):
                    for a in n.args:
                        yield a, "report.add"
                    for k in n.keywords:
                        yield k.value, f"report.add({k.arg}=)"
    ```
    （只认名叫 `report` 的对象，`visual.add(ref)` 这类集合操作不算。）
  - 模块文档字符串补一句：「子计划 5 起还扫 `Finding(…)` 与 `report.add(…)`（验证报告的条目）」。
  - 核对：已在 `MODULES` 里的模块在新规则下仍为零命中（编写本计划时在仓库外的副本上跑过：零命中）。
- [ ] **Step 7: 前端文案**：
  - `zh.ts` 的 `srv.common` 加 `more_lines: '…还有 {n} 行未显示'`；
  - `en.ts` 的 `srv.common` 加 `more_lines: '…not shown: {n} more'`。
- [ ] **Step 8: 跑全部校验并提交**：
  ```bash
  git add backend/server/messages.py backend/server/messages_codes.json backend/server/error_refs.py backend/pipeline/errors.py \
    backend/tests/server/test_messages.py backend/tests/server/test_error_refs.py backend/tests/server/test_i18n_scan.py \
    backend/tests/pipeline/test_graph.py frontend/src/i18n/zh.ts frontend/src/i18n/en.ts
  git commit -m "子计划 5 基础：新增逐条报告参数类型 lines（超过 100 项截断并说明还有几行），消息对象整体脱敏 scrub_deep，转换失败异常可带逐条消息；扫描补上验证报告条目的两个出口"
  ```

---

### Task 2: 验证规则逐条（`verification.py`、软核查、修复回喂不变）

**Files:**
- Modify: `backend/pipeline/verification.py`、`backend/pipeline/novel_memory.py`、`backend/pipeline/repair.py`
- Modify: `backend/server/messages.py`（登记 `verify.rule.*`、`verify.severity.*`、`verify.lifecycle.*`、`verify.report.finding/coverage/pass/fail`）、`messages_codes.json`
- Modify: `backend/tests/server/test_i18n_scan.py`（`MODULES` 加 `"pipeline/verification.py": None`、`"pipeline/repair.py": None`、`"pipeline/novel_memory.py": {"soft_findings"}`）
- Modify: `frontend/src/i18n/zh.ts`、`en.ts`（`srv.verify.rule/severity/lifecycle/report`）
- Create: `backend/tests/pipeline/test_verify_msgs.py`
- Test: `backend/tests/pipeline/test_offline.py`、`test_novel_memory.py`（现有断言不改，应照样通过）

- [ ] **Step 1: 写测试**（新建 `backend/tests/pipeline/test_verify_msgs.py`）。第 1、3 节的原文断言在改动前就能通过（特征测试，守护回喂模型的文字），其余在改动前失败：
  ```python
  #!/usr/bin/env python3
  """验证报告逐条（spec 子计划 5）：每条规则的代码与参数、回喂模型的文字不变、给用户的逐条消息。
  不调模型、不联网。用法: python3 tests/pipeline/test_verify_msgs.py"""
  import copy
  import os
  import re
  import sys
  import tempfile
  from pathlib import Path

  ROOT = Path(__file__).resolve().parent.parent.parent
  sys.path.insert(0, str(ROOT))

  _TMP = tempfile.TemporaryDirectory()
  os.environ["STORYBOARD_DATA_DIR"] = _TMP.name           # 必须在导入 server.* / pipeline.* 之前
  os.environ["ANTHROPIC_BASE_URL"] = "http://127.0.0.1:9"  # 保险：漏了桩也到不了真实模型服务
  os.environ["ANTHROPIC_API_KEY"] = "sk-test-not-real"
  import pipeline.config as _pc  # noqa: E402
  _pc._load_dotenv = lambda *_a, **_k: None                # 不读真实的 backend/.env

  from pipeline import novel_memory as nm, repair, verification as V  # noqa: E402
  from server import messages as M  # noqa: E402


  def doc():
      """三句原文、三个镜头的最小分镜：结构不全只触发 SCHEMA-001，其余规则全过（第 0 节核对）。"""
      return {"meta": {"narration": {"mode": "original_text"}},
              "source": {"units": [{"id": "u0001", "text": "他推门。", "para": 1},
                                   {"id": "u0002", "text": "“走吧。”", "para": 1},
                                   {"id": "u0003", "text": "门外下雨。", "para": 2}]},
              "assets": {"characters": [], "locations": [], "props": [], "creatures": []},
              "episodes": [{"id": "E01", "shots": [
                  {"id": "E01-SH001", "source": {"unit_refs": ["u0001"], "derivation": "explicit"},
                   "narration": {"text": "他推门。", "unit_refs": ["u0001"]}},
                  {"id": "E01-SH002", "source": {"unit_refs": ["u0002"], "derivation": "explicit"},
                   "dialogue": [{"text": "走吧。"}]},
                  {"id": "E01-SH003", "source": {"unit_refs": ["u0003"], "derivation": "explicit"},
                   "narration": {"text": "门外下雨。", "unit_refs": ["u0003"]}}]}],
              "coverage": {"unmapped_units": [], "inferred_shot_ratio": 0}}


  def shot(d, i):
      return d["episodes"][0]["shots"][i]


  FROZEN = [{k: u[k] for k in ("id", "text", "para")} for u in doc()["source"]["units"]]

  # (规则, 改坏文档, verify_document 的额外参数, 期望的 params；None 表示单独断言)
  CASES = [
      ("SOURCE-FROZEN-001", lambda d: d["source"]["units"].pop(), {"frozen_units": FROZEN}, {"expected": 3, "actual": 2}),
      ("SOURCE-FROZEN-002", lambda d: d["source"]["units"][0].update(text="他推开门。"), {"frozen_units": FROZEN},
       {"unit": "u0001", "field": "text"}),
      ("SOURCE-WAIVER-001", lambda d: d["source"]["units"][2].update(skipped=True), {"frozen_units": FROZEN}, {"unit": "u0003"}),
      ("ID-UNIT-001", lambda d: d["source"]["units"][1].update(id="u0001"), {}, {"id": "u0001"}),
      ("ID-EPISODE-001", lambda d: d["episodes"].append(copy.deepcopy(d["episodes"][0])), {}, {"id": "E01"}),
      ("ID-SHOT-001", lambda d: shot(d, 1).update(id="E01-SH001"), {}, {"id": "E01-SH001"}),
      ("ID-ASSET-001", lambda d: d["assets"]["characters"].extend([{"id": "C01"}, {"id": "C01"}]), {}, {"id": "C01"}),
      ("REF-UNIT-001", lambda d: shot(d, 0)["source"]["unit_refs"].append("u0099"), {}, {"unit": "u0099"}),
      ("EVIDENCE-INFERENCE-001", lambda d: shot(d, 0)["source"].update(derivation="inferred"), {}, {}),
      ("EVIDENCE-SHOT-001", lambda d: shot(d, 0)["source"].update(unit_refs=[]), {}, {}),
      ("EVIDENCE-RANGE-001", lambda d: shot(d, 0)["source"].update(unit_refs=["u0001", "u0003"]), {}, {}),
      ("ORDER-001", lambda d: (shot(d, 0)["source"].update(unit_refs=["u0002"]),
                               shot(d, 1)["source"].update(unit_refs=["u0001"])), {}, {"prev": "E01-SH001", "unit": "u0002"}),
      ("FID-DIALOGUE-001", lambda d: shot(d, 1)["dialogue"][0].update(text="快走。"), {}, {}),
      ("REF-NARRATION-001", lambda d: shot(d, 0)["narration"]["unit_refs"].append("u0099"), {}, {"unit": "u0099"}),
      ("FID-NARRATION-001", lambda d: shot(d, 0)["narration"].update(text="他慢慢推门。"), {}, {}),
      ("COVERAGE-001", lambda d: shot(d, 2).pop("narration"), {}, {"n": 1}),
      ("COVERAGE-DECLARED-001", lambda d: d["coverage"].update(unmapped_units=["u0002"]), {}, {}),
      ("COVERAGE-DECLARED-002", lambda d: d["coverage"].update(inferred_shot_ratio=0.5), {}, {}),
      ("FID-SOURCE-001", lambda d: None, {"original_text": "完全不同的原文"}, {}),
      ("SCHEMA-001", lambda d: None, {}, None),
  ]

  # 改造前 message 的原文（回喂模型，不得改动）
  OLD_MESSAGES = {
      "REF-UNIT-001": "shot references unknown source unit u0099",
      "ORDER-001": "镜头回跳到更早的原文（上一处 E01-SH001 引至 u0002）",
      "COVERAGE-001": "source units are not carried by narration, dialogue, or visuals",
      "SOURCE-FROZEN-001": "model changed the deterministic source-unit count",
  }


  def main() -> int:
      # 0. 最小分镜只有结构问题，下面每条用例触发的都是它自己改坏的那一处
      assert {f.rule_id for f in V.verify_document(doc()).findings} <= {"SCHEMA-001"}

      # 1. 每条规则：代码、参数、存档形状；回喂模型的 message 不变
      seen = set()
      for rule, mutate, kw, params in CASES:
          d = doc()
          mutate(d)
          found = [f for f in V.verify_document(d, **kw).findings if f.rule_id == rule]
          assert found, f"{rule} 没有被触发"
          f = found[0]
          if rule in OLD_MESSAGES:
              assert f.message == OLD_MESSAGES[rule], (rule, f.message)
          assert f.as_msg() == {"code": f"verify.rule.{rule}", "params": f.params}
          if params is not None:
              assert f.params == params, (rule, f.params)
          out = f.to_dict()
          assert out["msg"] == f.as_msg() and "params" not in out, rule
          zh = M.render_zh(f"verify.rule.{rule}", f.params)
          assert zh and "{" not in zh, (rule, zh)
          seen.add(rule)
      sch = next(f for f in V.verify_document(doc()).findings if f.rule_id == "SCHEMA-001")
      assert sch.params == {"detail": {"t": "vendor", "text": sch.message[:M.VENDOR_MAX]}}, "jsonschema 原文作厂商原文参数"
      print("1. 20 条规则逐条：代码、参数、存档带 msg、回喂模型的原文不变 ✓")

      # 2. 结构校验组件缺失
      saved = sys.modules.get("jsonschema")
      sys.modules["jsonschema"] = None          # import jsonschema 会抛 ImportError
      try:
          eng = V.verify_document(doc()).findings[0]
      finally:
          if saved is None:
              sys.modules.pop("jsonschema", None)
          else:
              sys.modules["jsonschema"] = saved
      assert eng.rule_id == "SCHEMA-ENGINE-001" and eng.as_msg() == {"code": "verify.rule.SCHEMA-ENGINE-001", "params": {}}
      assert eng.message == "jsonschema is unavailable; structural verification cannot run"
      seen.add("SCHEMA-ENGINE-001")
      print("2. SCHEMA-ENGINE-001 ✓")

      # 3. 软核查两条：参数结构化；message 由中文模板生成，与改造前一字不差
      ctx = nm.NovelContext(lifecycle=[{"character_id": "C03", "type": "deceased"}], names={"C03": "小栓"},
                            constraints=[{"text": "不出现血腥画面", "keywords": ["血", "伤口"]}])
      s = {"id": "E01-SH001", "action": "地上一摊血", "characters": [{"ref": "C03", "action": "咳嗽"}],
           "source": {"unit_refs": ["u0001"]}}
      found = nm.soft_findings({"episodes": [{"shots": [s]}]}, ctx)
      con = next(f for f in found if f.rule_id == "NOVEL-CONSTRAINT-001")
      life = next(f for f in found if f.rule_id == "NOVEL-LIFECYCLE-001")
      assert con.message == "镜头 E01-SH001 的画面描述含限制关键词「血」（限制：不出现血腥画面），请人工确认是否违规"
      assert life.message == "镜头 E01-SH001 里出现了已死亡的角色 C03小栓，画面描述里没有回忆/梦境等标记，请人工确认是不是闪回"
      assert con.params == {"shot": "E01-SH001", "keywords": ["血"], "constraint": "不出现血腥画面"}
      assert life.params == {"shot": "E01-SH001", "state": {"t": "ref", "code": "verify.lifecycle.deceased"},
                             "character": "C03小栓"}
      seen |= {"NOVEL-CONSTRAINT-001", "NOVEL-LIFECYCLE-001"}
      print("3. 软核查：参数结构化，原文一字不差 ✓")

      # 4. 源码里的规则编号与登记表一一对应，且每条都有触发用例
      src = "".join((ROOT / "pipeline" / n).read_text(encoding="utf-8") for n in ("verification.py", "novel_memory.py"))
      in_src = set(re.findall(r'"([A-Z]+(?:-[A-Z]+)*-\d{3})"', src))
      registered = {c[len("verify.rule."):] for c in M.dump_codes() if c.startswith("verify.rule.")}
      assert in_src == registered and len(registered) == 23, sorted(in_src ^ registered)
      assert seen == registered, sorted(registered - seen)
      print("4. 23 条规则全部登记、全部有用例 ✓")

      # 5. 回喂修复模型：条目不带 msg / params，字段与顺序同改造前；修复请求里没有代码
      d = doc()
      shot(d, 0)["source"]["unit_refs"].append("u0099")
      r = V.verify_document(d)
      vl = repair.validation_list(r)
      old_keys = {"rule_id", "severity", "object_path", "message", "unit_refs", "evidence_quote", "expected",
                  "actual", "suggested_patch"}
      assert all(set(x) <= old_keys for x in vl), "回喂模型的条目不带 msg、params"
      ref_unit = next(x for x in vl if x["rule_id"] == "REF-UNIT-001")
      assert ref_unit == {"rule_id": "REF-UNIT-001", "severity": "high",
                          "object_path": "/episodes/0/shots/0/source/unit_refs",
                          "message": "shot references unknown source unit u0099", "unit_refs": ["u0099"]}
      assert list(ref_unit) == ["rule_id", "severity", "object_path", "message", "unit_refs"], "键序不变（JSON 逐字一致）"
      req = repair.repair_request(r)
      assert "verify.rule" not in req and '"msg"' not in req
      print("5. 回喂修复模型的内容与改造前一致 ✓")

      # 6. lines()：逐条 + 覆盖统计 + 末行；中文兜底
      ls = r.lines()
      line = next(x for x in ls if x["code"] == "verify.report.finding" and x["params"]["rule"] == "REF-UNIT-001")
      assert line["params"] == {"severity": {"t": "ref", "code": "verify.severity.high"}, "rule": "REF-UNIT-001",
                                "path": "/episodes/0/shots/0/source/unit_refs",
                                "detail": {"code": "verify.rule.REF-UNIT-001", "params": {"unit": "u0099"}}}
      assert ls[-2]["code"] == "verify.report.coverage" and ls[-1] == {"code": "verify.report.fail",
                                                                         "params": {"n": len(r.errors)}}
      assert len(ls) == len(r.findings) + 2
      txt = M.render_zh("common.unknown", {"message": M.lines_of(ls)})
      assert "严重 [REF-UNIT-001] /episodes/0/shots/0/source/unit_refs：镜头引用了不存在的原文句子 u0099" in txt, txt
      ok = V.VerificationReport()
      assert ok.lines() == [{"code": "verify.report.pass", "params": {}}], "没有条目、没有覆盖统计时只有一行通过"
      print("6. lines()：逐条、覆盖、末行 ✓")

      print("\nALL PASS")
      return 0


  if __name__ == "__main__":
      sys.exit(main())
  ```
- [ ] **Step 2: 运行确认失败**：`cd backend && .venv/bin/python tests/pipeline/test_verify_msgs.py`，第 1 节在 `as_msg` 处报 `AttributeError`（第 0 节与各条 `OLD_MESSAGES` 断言此时已过）。
- [ ] **Step 3: `verification.py`**
  - 导入：
    ```python
    from server.messages import compact, msg, ref, vendor
    ```
  - `Finding`：
    ```python
    @dataclass
    class Finding:
        rule_id: str
        severity: str
        object_path: str
        message: str = ""          # 回喂模型的原文（多为英文），不翻译；没给时由中文模板生成
        unit_refs: list[str] = field(default_factory=list)
        evidence_quote: str = ""
        expected: object = None
        actual: object = None
        suggested_patch: list[dict] = field(default_factory=list)
        params: dict = field(default_factory=dict)   # 给界面的参数，代码是 verify.rule.<rule_id>（spec 子计划 5 B）

        def __post_init__(self) -> None:
            # 代码未登记或参数与模板不符，在这里就抛错：每条规则的用例都会走到这一行
            m = msg(self.code, **self.params)
            if not self.message:
                # 原文本来是中文的几条（ORDER-001、NOVEL-*）：模板与旧写法一字不差，直接用它
                self.message = m["message"]

        @property
        def code(self) -> str:
            return f"verify.rule.{self.rule_id}"

        def as_msg(self) -> dict:
            return {"code": self.code, "params": dict(self.params)}

        def to_dict(self, *, shown: bool = True) -> dict:
            """shown=True：存档与接口用，多一个 msg 给界面按语言渲染。
            shown=False：回喂修复模型的形状，与改造前逐字一致（不含 msg、params）。"""
            out = {k: v for k, v in asdict(self).items()
                   if k != "params" and v not in (None, "", [], {})}
            if shown:
                out["msg"] = self.as_msg()
            return out
    ```
  - `VerificationReport.add` 的 `message: str` 改为 `message: str = ""`。
  - `VerificationReport` 在 `render` 之后加：
    ```python
        def lines(self) -> list[dict]:
            """render() 的逐条消息版，给用户看（spec 子计划 5 C）；render() 照旧回喂模型。"""
            out = [compact(msg("verify.report.finding", severity=ref(f"verify.severity.{f.severity}"),
                               rule=f.rule_id, path=f.object_path, detail=f.as_msg()))
                   for f in self.findings]
            cov = self.coverage
            if cov.get("selected"):
                out.append(compact(msg("verify.report.coverage", selected=len(cov.get("selected", [])),
                                       covered=len(cov.get("covered", [])), waived=len(cov.get("waived", [])),
                                       failed=len(cov.get("failed", [])))))
            out.append(compact(msg("verify.report.pass")) if self.ok
                       else compact(msg("verify.report.fail", n=len(self.errors))))
            return out
    ```
  - 各规则补 `params=`（按调用点清单；`message` 位置参数不动）：
    ```python
    report.add("SCHEMA-001", "high", path, error.message, params={"detail": vendor(error.message)})
    # _validate_frozen_units
    report.add(
        "SOURCE-FROZEN-001", "critical", "/source/units",
        "model changed the deterministic source-unit count",
        expected=len(expected), actual=len(actual),
        params={"expected": len(expected), "actual": len(actual)})
    report.add(
        "SOURCE-FROZEN-002", "critical", f"/source/units/{i}/{key}",
        "model changed immutable source evidence",
        unit_refs=[exp.get("id", "")],
        evidence_quote=exp.get("text", ""),
        expected=exp.get(key), actual=got.get(key),
        params={"unit": exp.get("id", ""), "field": key})
    report.add(
        "SOURCE-WAIVER-001", "high", f"/source/units/{i}/skip_reason",
        "skipped source units require an explicit reviewable reason",
        unit_refs=[exp.get("id", "")], evidence_quote=exp.get("text", ""),
        params={"unit": exp.get("id", "")})
    # _validate_identity：四条都加 params={"id": duplicate}
    # _validate_evidence
    report.add("REF-UNIT-001", "high", base + "/source/unit_refs",
               f"shot references unknown source unit {ref}", unit_refs=[ref], params={"unit": ref})
    report.add(
        "ORDER-001", "medium", base + "/source/unit_refs",
        params={"prev": prev_label, "unit": f"u{prev_number:04d}"},
        unit_refs=valid_refs, expected=f">= u{prev_number:04d}",
        actual=f"u{first:04d}")
    report.add("REF-NARRATION-001", "high", base + "/narration/unit_refs",
               f"narration references unknown source unit {ref}", unit_refs=[ref], params={"unit": ref})
    report.add("COVERAGE-001", "critical", "/coverage/unmapped_units",
               "source units are not carried by narration, dialogue, or visuals",
               unit_refs=failed, params={"n": len(failed)})
    ```
    其余（`SCHEMA-ENGINE-001`、`EVIDENCE-*`、`FID-*`、`COVERAGE-DECLARED-*`）没有参数，调用不改。
    注意 `_validate_evidence` 里循环变量叫 `ref`，与导入的 `messages.ref` 同名：函数内的 `ref` 是局部变量，会遮住导入的函数。本模块只在 `lines()` 里调用 `ref(…)`，不在 `_validate_evidence` 里，所以不冲突；不要把 `ref(…)` 调用挪进那个函数。
- [ ] **Step 4: `novel_memory.py`**：导入加 `from server.messages import ref`；`soft_findings` 两处改为：
  ```python
                  if hit:
                      found.append(Finding(
                          "NOVEL-CONSTRAINT-001", "medium", f"{path}/{key}",
                          params={"shot": sid, "keywords": hit, "constraint": c.get("text", "")},
                          unit_refs=list(refs)))
  ```
  ```python
              if entry and not marked:
                  state = ref("verify.lifecycle.deceased" if entry["type"] == "deceased"
                              else "verify.lifecycle.departed")
                  found.append(Finding(
                      "NOVEL-LIFECYCLE-001", "medium", f"{path}/characters",
                      params={"shot": sid, "state": state,
                              "character": f"{c.get('ref')}{ctx.names.get(c.get('ref'), '')}"},
                      unit_refs=list(refs)))
  ```
  （`message` 不再传，由中文模板生成，与原 f-string 一字不差：列表参数的中文兜底用「、」连接，代码引用渲染为「已死亡」「已永久离开」。）
- [ ] **Step 5: `repair.py`**：
  ```python
  def validation_list(report) -> list[dict]:
      # 回喂修复模型：与改造前逐字一致，不带给界面的 msg（spec 子计划 5 F）
      return [finding.to_dict(shown=False) for finding in report.findings]
  ```
  14 处 `raise RepairError(…)`（第 60、69、72、82、86、92、96、100、113、116、120、124、128、134 行）行尾加 `  # i18n: llm`（补丁错误回喂模型重试，spec §2.3）。
- [ ] **Step 6: 登记**（`messages.py`，接在 `verify.finding` 之后）：
  ```python
  # 验证报告逐条（子计划 5）：代码是 verify.rule.<rule_id>；回喂模型的是 Finding.message 原文，不走这里
  register("verify.rule.SCHEMA-ENGINE-001", "服务器缺少结构校验组件，无法校验分镜结构，请联系管理员")
  register("verify.rule.SCHEMA-001", "不符合分镜结构定义：{detail}")
  register("verify.rule.SOURCE-FROZEN-001", "原文句子数被改动：应为 {expected} 句，实际 {actual} 句")
  register("verify.rule.SOURCE-FROZEN-002", "原文句子 {unit} 的 {field} 被改动（原文证据不能修改）")
  register("verify.rule.SOURCE-WAIVER-001", "跳过原文句子 {unit} 时必须写明理由，方便审阅")
  register("verify.rule.ID-UNIT-001", "原文句子编号重复：{id}")
  register("verify.rule.ID-EPISODE-001", "分集编号重复：{id}")
  register("verify.rule.ID-SHOT-001", "镜头编号重复：{id}")
  register("verify.rule.ID-ASSET-001", "资产卡编号重复：{id}")
  register("verify.rule.REF-UNIT-001", "镜头引用了不存在的原文句子 {unit}")
  register("verify.rule.EVIDENCE-INFERENCE-001", "推断镜头必须写明具体的推断依据")
  register("verify.rule.EVIDENCE-SHOT-001", "除转场镜头外，每个镜头都要引用原文依据")
  register("verify.rule.EVIDENCE-RANGE-001", "一个镜头的原文依据通常应是 1–3 个相邻句子")
  register("verify.rule.ORDER-001", "镜头回跳到更早的原文（上一处 {prev} 引至 {unit}）")
  register("verify.rule.FID-DIALOGUE-001", "台词不是所引原文的逐字摘录")
  register("verify.rule.REF-NARRATION-001", "旁白引用了不存在的原文句子 {unit}")
  register("verify.rule.FID-NARRATION-001", "旁白文字不是所引原文的原句摘录")
  register("verify.rule.COVERAGE-001", "有 {n} 句原文没有被旁白、台词或画面承载")
  register("verify.rule.COVERAGE-DECLARED-001", "声明的未覆盖句子与程序算出的不一致")
  register("verify.rule.COVERAGE-DECLARED-002", "声明的推断镜头占比与程序算出的不一致")
  register("verify.rule.FID-SOURCE-001", "原文句子拼起来与归一化后的原文不一致")
  register("verify.rule.NOVEL-CONSTRAINT-001", "镜头 {shot} 的画面描述含限制关键词「{keywords}」（限制：{constraint}），请人工确认是否违规")
  register("verify.rule.NOVEL-LIFECYCLE-001", "镜头 {shot} 里出现了{state}的角色 {character}，"
                                              "画面描述里没有回忆/梦境等标记，请人工确认是不是闪回")
  register("verify.severity.critical", "致命")
  register("verify.severity.high", "严重")
  register("verify.severity.medium", "提醒")
  register("verify.severity.low", "提示")
  register("verify.lifecycle.deceased", "已死亡")
  register("verify.lifecycle.departed", "已永久离开")
  register("verify.report.finding", "{severity} [{rule}] {path}：{detail}")
  register("verify.report.coverage", "覆盖：选中 {selected} 句，已承载 {covered}，豁免 {waived}，未承载 {failed}")
  register("verify.report.pass", "通过")
  register("verify.report.fail", "未通过（{n} 条硬性问题）")
  ```
  `--write` 更新代码表。级别的中文与前端 `verify.severity` 现有文案一致。
- [ ] **Step 7: 前端文案**：`zh.ts` 的 `srv.verify` 改为（`gate`、`finding` 原样保留）：
  ```ts
      verify: {
        gate: { blocked: '分镜未通过独立验证，禁止进入付费渲染' },
        finding: '{path}: {detail}',
        rule: {
          'SCHEMA-ENGINE-001': '服务器缺少结构校验组件，无法校验分镜结构，请联系管理员',
          'SCHEMA-001': '不符合分镜结构定义：{detail}',
          'SOURCE-FROZEN-001': '原文句子数被改动：应为 {expected} 句，实际 {actual} 句',
          'SOURCE-FROZEN-002': '原文句子 {unit} 的 {field} 被改动（原文证据不能修改）',
          'SOURCE-WAIVER-001': '跳过原文句子 {unit} 时必须写明理由，方便审阅',
          'ID-UNIT-001': '原文句子编号重复：{id}',
          'ID-EPISODE-001': '分集编号重复：{id}',
          'ID-SHOT-001': '镜头编号重复：{id}',
          'ID-ASSET-001': '资产卡编号重复：{id}',
          'REF-UNIT-001': '镜头引用了不存在的原文句子 {unit}',
          'EVIDENCE-INFERENCE-001': '推断镜头必须写明具体的推断依据',
          'EVIDENCE-SHOT-001': '除转场镜头外，每个镜头都要引用原文依据',
          'EVIDENCE-RANGE-001': '一个镜头的原文依据通常应是 1–3 个相邻句子',
          'ORDER-001': '镜头回跳到更早的原文（上一处 {prev} 引至 {unit}）',
          'FID-DIALOGUE-001': '台词不是所引原文的逐字摘录',
          'REF-NARRATION-001': '旁白引用了不存在的原文句子 {unit}',
          'FID-NARRATION-001': '旁白文字不是所引原文的原句摘录',
          'COVERAGE-001': '有 {n} 句原文没有被旁白、台词或画面承载',
          'COVERAGE-DECLARED-001': '声明的未覆盖句子与程序算出的不一致',
          'COVERAGE-DECLARED-002': '声明的推断镜头占比与程序算出的不一致',
          'FID-SOURCE-001': '原文句子拼起来与归一化后的原文不一致',
          'NOVEL-CONSTRAINT-001': '镜头 {shot} 的画面描述含限制关键词「{keywords}」（限制：{constraint}），请人工确认是否违规',
          'NOVEL-LIFECYCLE-001': '镜头 {shot} 里出现了{state}的角色 {character}，画面描述里没有回忆/梦境等标记，请人工确认是不是闪回',
        },
        severity: { critical: '致命', high: '严重', medium: '提醒', low: '提示' },
        lifecycle: { deceased: '已死亡', departed: '已永久离开' },
        report: {
          finding: '{severity} [{rule}] {path}：{detail}',
          coverage: '覆盖：选中 {selected} 句，已承载 {covered}，豁免 {waived}，未承载 {failed}',
          pass: '通过',
          fail: '未通过（{n} 条硬性问题）',
        },
      },
  ```
  `en.ts` 同结构（`gate`、`finding` 原样保留）：
  ```ts
        rule: {
          'SCHEMA-ENGINE-001': 'The server is missing its structure checker, so the storyboard can’t be verified. Please contact the administrator.',
          'SCHEMA-001': 'Doesn’t match the storyboard schema: {detail}',
          'SOURCE-FROZEN-001': 'The number of source lines changed: expected {expected}, got {actual}',
          'SOURCE-FROZEN-002': 'Source line {unit}: “{field}” was changed (source evidence can’t be edited)',
          'SOURCE-WAIVER-001': 'Skipping source line {unit} needs a reason that can be reviewed',
          'ID-UNIT-001': 'Duplicate source line ID: {id}',
          'ID-EPISODE-001': 'Duplicate episode ID: {id}',
          'ID-SHOT-001': 'Duplicate shot ID: {id}',
          'ID-ASSET-001': 'Duplicate asset card ID: {id}',
          'REF-UNIT-001': 'The shot cites a source line that doesn’t exist: {unit}',
          'EVIDENCE-INFERENCE-001': 'Inferred shots need a concrete note on what they’re inferred from',
          'EVIDENCE-SHOT-001': 'Every shot except transitions must cite the source text',
          'EVIDENCE-RANGE-001': 'A shot’s evidence should usually be 1–3 adjacent source lines',
          'ORDER-001': 'The shot jumps back to earlier source text (the previous one, {prev}, cited up to {unit})',
          'FID-DIALOGUE-001': 'The dialogue isn’t a word-for-word excerpt of the cited source lines',
          'REF-NARRATION-001': 'The narration cites a source line that doesn’t exist: {unit}',
          'FID-NARRATION-001': 'The narration isn’t a direct excerpt of the cited source lines',
          'COVERAGE-001': 'Source lines not carried by narration, dialogue, or visuals: {n}',
          'COVERAGE-DECLARED-001': 'The declared uncovered lines differ from the computed result',
          'COVERAGE-DECLARED-002': 'The declared share of inferred shots differs from the computed result',
          'FID-SOURCE-001': 'The source lines don’t add up to the normalized input text',
          'NOVEL-CONSTRAINT-001': 'Shot {shot}: the visual description uses restricted terms “{keywords}” (rule: {constraint}). Please check whether it breaks the rule.',
          'NOVEL-LIFECYCLE-001': 'Shot {shot} shows {character}, who {state}, with no flashback or dream marker in the visuals. Please check whether it’s a flashback.',
        },
        severity: { critical: 'Critical', high: 'Severe', medium: 'Warning', low: 'Note' },
        lifecycle: { deceased: 'has died', departed: 'has left the story for good' },
        report: {
          finding: '{severity} [{rule}] {path}: {detail}',
          coverage: 'Coverage: {selected} selected, {covered} carried, {waived} waived, {failed} missing',
          pass: 'Passed',
          fail: 'Failed (blocking issues: {n})',
        },
  ```
- [ ] **Step 8: 扫描**：`MODULES` 加三项（见 Files）。改动前的基线：新规则下 `verification.py` 1 处（`ORDER-001`）、`novel_memory.soft_findings` 2 处；`repair.py` 现有规则下 14 处。本 Task 之后三者都为零：前两类的中文改由模板生成，`repair.py` 标 `# i18n: llm`。
- [ ] **Step 9: 跑全部校验并提交**（`test_offline.py` 第 1140 行附近「回跳」断言、`test_novel_memory.py` 第 5 节的 `message` 断言不改应照样通过）：
  ```bash
  git add backend/pipeline/verification.py backend/pipeline/novel_memory.py backend/pipeline/repair.py \
    backend/server/messages.py backend/server/messages_codes.json backend/tests/pipeline/test_verify_msgs.py \
    backend/tests/server/test_i18n_scan.py frontend/src/i18n/zh.ts frontend/src/i18n/en.ts
  git commit -m "验证报告逐条：23 条规则各带代码与结构化参数，存档与接口里的每条多一个消息对象供界面按语言渲染；回喂修复模型的条目与原文一字不改；新增逐条报告 lines()；修复补丁的报错标为回喂模型"
  ```

---

### Task 3: 质量门与评审的逐条（`quality.py`、`review.py`）

本 Task 只让三个函数多产出一份逐条消息，回喂模型的报告字符串不变；流水线还没接上它们（Task 4 接），所以降级警告此时仍是原文。

**Files:**
- Modify: `backend/pipeline/quality.py`（`narration_density_gate`、`speech_fit_gate` 的 `lines_out`）
- Modify: `backend/pipeline/review.py`（`run_review` 的 `lines_out`）
- Modify: `backend/server/messages.py`（登记 `verify.quality.*`、`verify.review.*`）、`messages_codes.json`
- Modify: `backend/tests/server/test_i18n_scan.py`（`MODULES` 加 `"pipeline/quality.py": None`；`review.py` 已在）
- Modify: `frontend/src/i18n/zh.ts`、`en.ts`（`srv.verify.quality`、`srv.verify.review`）
- Test: `backend/tests/pipeline/test_verify_msgs.py`（第 7–9 节）

- [ ] **Step 1: 写测试**：`test_verify_msgs.py` 的 `print("\nALL PASS")` 之前加三节。每节第一条断言（不带 `lines_out`）在改动前就能通过，是回喂模型文字的特征测试；带 `lines_out` 的在改动前报 `TypeError`。报告原文是编写本计划时在仓库外的副本上用现有代码跑出来的。
  ```python
      # 7. 旁白密度门：回喂模型的报告与改造前一字不差；逐条只有现象与清单
      import anthropic
      import httpx2
      from pipeline import quality, review

      def chatty(n=4):
          units = [{"id": f"u{i:04d}", "text": f"第{i}句动作描写。", "kind": "action"} for i in range(1, n + 1)]
          shots = [{"id": f"E01-SH{i:03d}", "duration_sec": 1,
                    "source": {"unit_refs": [u["id"]] if i % 2 else []},
                    "narration": {"text": u["text"] * 3, "unit_refs": [u["id"]]}} for i, u in enumerate(units, 1)]
          return {"meta": {"narration": {"mode": "selective"}}, "source": {"units": units},
                  "episodes": [{"id": "E01", "shots": shots}]}

      DENSITY = ("[quality] selective 模式下旁白占比 100%，超过阈值 60%——「能拍出来的不念」未执行（人工基准约 20%–35%）。\n"
                 "以下被旁白朗读的句子多为可拍内容，请逐句重新裁决，只保留画面承载不了的信息——"
                 "时间跳跃、人名身份交代、因果前史、心理核心语义、点题句。\n"
                 "已有镜头画面引用、可直接从 narration.unit_refs 中移除的：\n"
                 "  u0001 [action] 第1句动作描写。\n  u0003 [action] 第3句动作描写。\n"
                 "只靠旁白承载的（没有任何镜头的 source.unit_refs 引用它们）：若要移除，"
                 "须先把它加进呈现该内容的镜头的 source.unit_refs，否则就成了未覆盖：\n"
                 "  u0002 [action] 第2句动作描写。\n  u0004 [action] 第4句动作描写。")
      assert quality.narration_density_gate(chatty(), 0.6) == (False, DENSITY, 1.0)
      out = []
      assert quality.narration_density_gate(chatty(), 0.6, lines_out=out) == (False, DENSITY, 1.0)

      def unit(i):
          return {"code": "verify.quality.unit", "params": {"id": f"u{i:04d}", "kind": "action", "text": f"第{i}句动作描写。"}}
      assert out == [{"code": "verify.quality.density", "params": {"ratio": "100%", "max": "60%"}},
                     {"code": "verify.quality.density_safe", "params": {}}, unit(1), unit(3),
                     {"code": "verify.quality.density_bare", "params": {}}, unit(2), unit(4)], out
      out = []
      assert quality.narration_density_gate(chatty(), 1.0, lines_out=out)[0] and out == [], "通过时不写逐条"
      shown7 = []
      quality.narration_density_gate(chatty(), 0.6, lines_out=shown7)
      txt = M.render_zh("common.unknown", {"message": M.lines_of(shown7)})
      assert txt.startswith("旁白占比 100%，超过阈值 60%") and "请逐句重新裁决" not in txt, "给用户的没有给模型的操作指示"
      print("7. 旁白密度门：原文不变、逐条 ✓")

      # 8. 时长门
      SPEECH = ("[quality] 2/2 个镜头（100%）的时长不够念完自己的旁白与台词（按 4.5 字/秒），超过阈值 10%。\n"
                "名义总时长 2s，要让语音都念完实际需要 10.7s。\n"
                "上限 15s 以内的缺口程序会自动拉长 duration_sec；超出上限的镜头必须拆成多个镜头分担旁白，"
                "或把画面承载得了的句子从 narration.unit_refs 移除（不得改动旁白与台词文本、也不得改 source.unit_refs）：\n"
                "  E01-SH001 时长 1s，念完需 5.3s（缺 4.3s）\n  E01-SH002 时长 1s，念完需 5.3s（缺 4.3s）")
      assert quality.speech_fit_gate(chatty(2), 0.1) == (False, SPEECH, 1.0)
      out = []
      assert quality.speech_fit_gate(chatty(2), 0.1, lines_out=out) == (False, SPEECH, 1.0)

      def sh(i):
          return {"code": "verify.quality.speech_shot",
                  "params": {"shot": f"E01-SH{i:03d}", "have": "1", "need": "5.3", "gap": "4.3"}}
      assert out == [{"code": "verify.quality.speech", "params": {"over": 2, "total": 2, "ratio": "100%", "cps": "4.5",
                                                                  "max": "10%", "nominal": "2", "actual": "10.7"}},
                     sh(1), sh(2)], out
      print("8. 时长门：原文不变、逐条 ✓")

      # 9. 评审：回喂模型的报告不变；评审意见是厂商原文；调用失败的原因是映射后的 llm.*
      class Stub:
          """评审模型替身：invoke 返回脚本（raise_ 非空时抛它），text 原样返回。"""
          def __init__(self, raw="", raise_=None):
              self.raw, self.raise_ = raw, raise_

          def invoke(self, msgs):
              if self.raise_ is not None:
                  raise self.raise_
              return self.raw

          def text(self, m):
              return m

      LOW = ('{"scores":{"narration_selection":2,"shot_language":4,"asset_quality":4,"semantic_fidelity":3},'
             '"overall":3.2,"issues":[{"where":"E01-SH002","problem":"旁白重复画面","fix":"删掉旁白"}]}')
      REV_LOW = ("[review] 评审总分 3.2（阈值 3.5）：narration_selection 2；shot_language 4；asset_quality 4；semantic_fidelity 3\n"
                 "  [E01-SH002] 旁白重复画面 → 建议：删掉旁白\n"
                 "  未通过独立门槛：总分 3.2 < 3.5；低分维度：narration_selection；semantic_fidelity 3 < 4\n\n"
                 "请针对上述 issues 逐条修改后重新输出完整 JSON（只输出一个 JSON 对象）。")
      assert review.run_review(Stub(LOW), "原文", {"episodes": []}, 3.5) == (False, REV_LOW, 3.2)
      out = []
      assert review.run_review(Stub(LOW), "原文", {"episodes": []}, 3.5, lines_out=out) == (False, REV_LOW, 3.2)

      def dim(k, v):
          return {"code": "verify.review.dim_score",
                  "params": {"dim": {"t": "ref", "code": f"verify.review.dim.{k}"}, "score": v}}
      assert out == [
          {"code": "verify.review.scored", "params": {"overall": "3.2", "min": "3.5", "scores": [
              dim("narration_selection", 2), dim("shot_language", 4), dim("asset_quality", 4), dim("semantic_fidelity", 3)]}},
          {"code": "verify.review.issue", "params": {"where": {"t": "vendor", "text": "E01-SH002"},
                                                     "problem": {"t": "vendor", "text": "旁白重复画面"},
                                                     "fix": {"t": "vendor", "text": "删掉旁白"}}},
          {"code": "verify.review.gates", "params": {"gates": [
              {"code": "verify.review.gate.overall", "params": {"overall": "3.2", "min": "3.5"}},
              {"code": "verify.review.gate.weak",
               "params": {"dims": [{"t": "ref", "code": "verify.review.dim.narration_selection"}]}},
              {"code": "verify.review.gate.semantic", "params": {"score": 3, "min": 4}}]}}], out
      txt = M.render_zh("common.unknown", {"message": M.lines_of(out)})
      assert txt.startswith("评审总分 3.2（阈值 3.5）：旁白取舍 2、镜头语言 4、资产卡质量 4、语义忠实 3\n"), txt
      assert "请针对上述 issues" not in txt

      HIGH = '{"scores":{"narration_selection":5,"shot_language":5,"asset_quality":5,"semantic_fidelity":5},"overall":5,"issues":[]}'
      out = []
      ok_, rep, _ = review.run_review(Stub(HIGH), "原文", {"episodes": []}, 3.5, lines_out=out)
      assert ok_ is True and rep == ("[review] 评审总分 5.0（阈值 3.5）：narration_selection 5；shot_language 5；"
                                     "asset_quality 5；semantic_fidelity 5\n  无具体问题")
      assert [x["code"] for x in out] == ["verify.review.scored", "verify.review.no_issues"]

      out = []
      assert review.run_review(Stub('{"scores":{"x":5}}'), "原文", {"episodes": []}, 3.5, lines_out=out) == (
          None, "[review] 评审输出不可验证（scores 必须且只能包含 narration_selection, shot_language, asset_quality, "
                "semantic_fidelity）", None)
      assert out == [{"code": "verify.review.unverifiable", "params": {}}], "细节（对模型输出的格式检查）不给用户"

      req = httpx2.Request("POST", "http://127.0.0.1:9/v1/messages")
      e401 = anthropic.AuthenticationError(
          "x", body={"type": "error", "error": {"type": "authentication_error", "message": "bad key"}},
          response=httpx2.Response(401, request=req))
      out = []
      got = review.run_review(Stub(raise_=e401), "原文", {"episodes": []}, 3.5, lines_out=out)
      assert got[0] is None and got[1] == "[review] 评审服务不可用：AI 服务鉴权失败，请联系管理员", got
      assert out == [{"code": "verify.review.unavailable", "params": {"cause": {"code": "llm.auth", "params": {}}}}], out
      out = []
      review.run_review(Stub(raise_=RuntimeError("boom")), "原文", {"episodes": []}, 3.5, lines_out=out)
      assert out == [{"code": "verify.review.unavailable",
                      "params": {"cause": {"code": "verify.review.call_failed", "params": {}}}}], out
      print("9. 评审：原文不变、逐条、意见原样、失败原因映射 ✓")
  ```
- [ ] **Step 2: 运行确认失败**：`cd backend && .venv/bin/python tests/pipeline/test_verify_msgs.py`，第 7 节第二条断言报 `TypeError: … unexpected keyword argument 'lines_out'`。
- [ ] **Step 3: `quality.py`**
  - 导入：`from typing import List, Optional, Tuple`，`from server.messages import compact, msg`。
  - `narration_density_gate` 签名改为 `(doc: dict, max_ratio: float, lines_out: Optional[List[dict]] = None)`，文档字符串补一句「lines_out（可选）收同一份报告给用户看的逐条消息（spec 子计划 5 D）：只有现象与清单，没有给模型的操作指示」。`return False, report.rstrip("\n"), ratio` 之前加：
    ```python
        if lines_out is not None:
            def items(us):
                return [compact(msg("verify.quality.unit", id=u["id"], kind=u["kind"], text=u["text"][:30]))
                        for u in us[:40]]
            lines_out.append(compact(msg("verify.quality.density", ratio=f"{ratio:.0%}", max=f"{max_ratio:.0%}")))
            if safe:
                lines_out.extend([compact(msg("verify.quality.density_safe"))] + items(safe))
            if bare:
                lines_out.extend([compact(msg("verify.quality.density_bare"))] + items(bare))
    ```
  - `speech_fit_gate` 签名改为 `(doc: dict, max_overflow_ratio: float, cps: float = DEFAULT_SPEECH_CPS, lines_out: Optional[List[dict]] = None)`，文档字符串同样补一句。`return False, report, ratio` 之前加：
    ```python
        if lines_out is not None:
            lines_out.append(compact(msg("verify.quality.speech", over=len(over), total=total, ratio=f"{ratio:.0%}",
                                         cps=f"{cps:g}", max=f"{max_overflow_ratio:.0%}",
                                         nominal=f"{nominal:g}", actual=f"{actual:g}")))
            lines_out.extend(compact(msg("verify.quality.speech_shot", shot=sid, have=f"{have:g}",
                                         need=f"{need:.1f}", gap=f"{need - have:.1f}"))
                             for sid, have, need in over[:40])
    ```
  - 报告字符串的拼法一个字都不动。
- [ ] **Step 4: `review.py`**
  - 导入：`from server.messages import compact, msg, ref, vendor`。
  - 签名加 `lines_out: Optional[list] = None`（`Optional` 已导入），文档字符串补：「lines_out（可选）收同一份报告给用户看的逐条消息（spec 子计划 5 D）；评审意见是模型输出，作厂商原文参数原样显示；给模型的重试指示不进逐条」。函数开头 `out = lines_out if lines_out is not None else []`。
  - 调用失败分支，`return` 之前：
    ```python
            m = mapped.as_msg() if mapped is not None else None
            out.append(compact(msg("verify.review.unavailable",
                                   cause=compact(m) if m else compact(msg("verify.review.call_failed")))))
    ```
  - 输出不可验证分支，`return` 之前：`out.append(compact(msg("verify.review.unverifiable")))`。
  - 算完 `report` 之后、判断通过之前：
    ```python
        out.append(compact(msg("verify.review.scored", overall=f"{overall}", min=f"{min_score}",
                               scores=[compact(msg("verify.review.dim_score", dim=ref(f"verify.review.dim.{k}"), score=v))
                                       for k, v in scores.items()])))
        out.extend([compact(msg("verify.review.issue", where=vendor(i.get("where", "?")),
                                problem=vendor(i.get("problem", "")), fix=vendor(i.get("fix", ""))))
                    for i in issues] or [compact(msg("verify.review.no_issues"))])
    ```
  - 没过门槛时，在原 `gates` 列表旁边并行生成：
    ```python
        shown_gates = []
        if overall < min_score:
            shown_gates.append(compact(msg("verify.review.gate.overall", overall=f"{overall}", min=f"{min_score}")))
        if weak:
            shown_gates.append(compact(msg("verify.review.gate.weak", dims=[ref(f"verify.review.dim.{k}") for k in weak])))
        if not semantic_ok:
            shown_gates.append(compact(msg("verify.review.gate.semantic", score=scores["semantic_fidelity"], min=semantic_min)))
        out.append(compact(msg("verify.review.gates", gates=shown_gates)))
    ```
  - 评审意见不在这里脱敏：Task 4 的 `_report_param` 与 app 的 `scrub_deep` 统一处理（`vendor` 只截断 300 字）。
- [ ] **Step 5: 登记**（`messages.py`，接在 Task 2 的 `verify.report.*` 之后）：
  ```python
  register("verify.quality.density", "旁白占比 {ratio}，超过阈值 {max}：选择性旁白模式下，能拍出来的内容不该再念（人工基准约 20%–35%）")
  register("verify.quality.density_safe", "这些句子已有镜头画面承载，可以从旁白里拿掉：")
  register("verify.quality.density_bare", "这些句子只靠旁白承载（没有镜头画面引用它们）：")
  register("verify.quality.unit", "  {id} [{kind}] {text}")
  register("verify.quality.speech", "{over}/{total} 个镜头（{ratio}）的时长不够念完自己的旁白与台词（按 {cps} 字/秒），"
                                    "超过阈值 {max}；名义总时长 {nominal}s，全部念完实际需要 {actual}s")
  register("verify.quality.speech_shot", "  {shot} 时长 {have}s，念完需 {need}s（缺 {gap}s）")
  register("verify.review.unavailable", "评审服务不可用：{cause}")
  register("verify.review.call_failed", "调用出错")
  register("verify.review.unverifiable", "评审输出无法核验")
  register("verify.review.scored", "评审总分 {overall}（阈值 {min}）：{scores}")
  register("verify.review.dim_score", "{dim} {score}")
  register("verify.review.dim.narration_selection", "旁白取舍")
  register("verify.review.dim.shot_language", "镜头语言")
  register("verify.review.dim.asset_quality", "资产卡质量")
  register("verify.review.dim.semantic_fidelity", "语义忠实")
  register("verify.review.issue", "  [{where}] {problem} → 建议：{fix}")
  register("verify.review.no_issues", "  无具体问题")
  register("verify.review.gates", "  未通过独立门槛：{gates}")
  register("verify.review.gate.overall", "总分 {overall} < {min}")
  register("verify.review.gate.weak", "低分维度：{dims}")
  register("verify.review.gate.semantic", "语义忠实 {score} < {min}")
  ```
  `--write` 更新代码表。
- [ ] **Step 6: 前端文案**：`zh.ts` 的 `srv.verify` 里加（与上面登记的中文一字不差）：
  ```ts
        quality: {
          density: '旁白占比 {ratio}，超过阈值 {max}：选择性旁白模式下，能拍出来的内容不该再念（人工基准约 20%–35%）',
          density_safe: '这些句子已有镜头画面承载，可以从旁白里拿掉：',
          density_bare: '这些句子只靠旁白承载（没有镜头画面引用它们）：',
          unit: '  {id} [{kind}] {text}',
          speech: '{over}/{total} 个镜头（{ratio}）的时长不够念完自己的旁白与台词（按 {cps} 字/秒），超过阈值 {max}；名义总时长 {nominal}s，全部念完实际需要 {actual}s',
          speech_shot: '  {shot} 时长 {have}s，念完需 {need}s（缺 {gap}s）',
        },
        review: {
          unavailable: '评审服务不可用：{cause}',
          call_failed: '调用出错',
          unverifiable: '评审输出无法核验',
          scored: '评审总分 {overall}（阈值 {min}）：{scores}',
          dim_score: '{dim} {score}',
          dim: { narration_selection: '旁白取舍', shot_language: '镜头语言', asset_quality: '资产卡质量', semantic_fidelity: '语义忠实' },
          issue: '  [{where}] {problem} → 建议：{fix}',
          no_issues: '  无具体问题',
          gates: '  未通过独立门槛：{gates}',
          gate: { overall: '总分 {overall} < {min}', weak: '低分维度：{dims}', semantic: '语义忠实 {score} < {min}' },
        },
  ```
  `en.ts`：
  ```ts
        quality: {
          density: 'Narration covers {ratio} of the source, above the {max} limit: in selective mode, what the picture can show shouldn’t also be read aloud (hand-made storyboards: about 20%–35%)',
          density_safe: 'Already shown on screen, so they can come out of the narration:',
          density_bare: 'Carried only by the narration (no shot shows them):',
          unit: '  {id} [{kind}] {text}',
          speech: 'Shots too short for their narration and dialogue: {over} of {total} ({ratio}, at {cps} characters/s), above the {max} limit; nominal length {nominal}s, {actual}s needed to read everything',
          speech_shot: '  {shot}: {have}s long, needs {need}s ({gap}s short)',
        },
        review: {
          unavailable: 'Review unavailable: {cause}',
          call_failed: 'the call failed',
          unverifiable: 'The review output couldn’t be verified',
          scored: 'Review score {overall} (threshold {min}): {scores}',
          dim_score: '{dim} {score}',
          dim: { narration_selection: 'Narration choices', shot_language: 'Shot language', asset_quality: 'Asset cards', semantic_fidelity: 'Faithfulness' },
          issue: '  [{where}] {problem} → Suggestion: {fix}',
          no_issues: '  No specific issues',
          gates: '  Failed the independent thresholds: {gates}',
          gate: { overall: 'overall {overall} < {min}', weak: 'low-scoring: {dims}', semantic: 'faithfulness {score} < {min}' },
        },
  ```
- [ ] **Step 7: 扫描**：`MODULES` 加 `"pipeline/quality.py": None`（改动前基线 0 处）；`review.py` 新增的 `msg(…)` 调用不是出口，仍为零。
- [ ] **Step 8: 跑全部校验并提交**（`test_offline.py`、`test_chat.py` 里现有的质量门与评审断言不改应照样通过）：
  ```bash
  git add backend/pipeline/quality.py backend/pipeline/review.py backend/server/messages.py backend/server/messages_codes.json \
    backend/tests/pipeline/test_verify_msgs.py backend/tests/server/test_i18n_scan.py frontend/src/i18n/zh.ts frontend/src/i18n/en.ts
  git commit -m "旁白密度门、时长门与评审在生成回喂模型报告的同一处，另出一份给用户看的逐条消息：只有现象、清单与分数，评审意见作原文原样显示，调用失败的原因按 AI 服务的映射；回喂模型的报告一字不改"
  ```

---

### Task 4: 转换流水线带上逐条（`graph.py`、`convert.py`）

**Files:**
- Modify: `backend/pipeline/verification.py`（`tool_line`）
- Modify: `backend/pipeline/graph.py`、`backend/pipeline/convert.py`
- Modify: `backend/server/messages.py`（登记 `verify.report.tool`、`verify.attempt.*`）、`messages_codes.json`
- Modify: `frontend/src/i18n/zh.ts`、`en.ts`（`srv.verify.report.tool`、`srv.verify.attempt`）
- Test: `backend/tests/pipeline/test_graph.py`（第 3 节，新增 3c、3d、3e）、`backend/tests/pipeline/test_offline.py`（:369）

- [ ] **Step 1: 写失败测试**
  - `test_graph.py` 顶部导入加 `from server.messages import compact, msg`。
  - 第 3 节把 Task 1 加的 `assert isinstance(e.lines, list)` 改为：
    ```python
            assert e.lines == [{"code": "verify.attempt.unparseable", "params": {}}], e.lines
    ```
  - 第 3b 节之后加三节：
    ```python
    # 3c. 硬失败耗尽：失败报告带逐条（结构校验逐条 + 末行）；report 仍是回喂模型的 render() 原文
    bad0 = json.loads(archived)
    bad0["episodes"][0]["shots"][0].pop("action")
    with tempfile.TemporaryDirectory() as d:
        chat = ChatInvoker(settings, chat=FakeChat(responses=[json.dumps(bad0)]), log=lambda _: None)
        graph = build_batch_graph(chat=chat, review_chat=chat, settings=settings, params=params,
                                  workdir=Path(d), attempt_records=[], log=lambda _: None)
        try:
            run_batch(graph, user="u", batch_text=batch, idx=2, frozen_units=None)
            raise AssertionError("硬失败耗尽应抛 ConversionError")
        except ConversionError as e:
            codes = [x["code"] for x in e.lines]
            assert "verify.report.finding" in codes and codes[-1] == "verify.report.fail", codes
            assert any(x["params"].get("rule") == "SCHEMA-001" for x in e.lines)
            assert "[SCHEMA-001]" in e.report and "verify.rule" not in e.report, "report 仍是 render() 原文"
    print("graph: 硬失败的失败报告带逐条 ✓")

    # 3d. 软质量门耗尽降级：警告的 report 是 lines；尝试记录照旧存原文
    def fake_check(*a, lines_out=None, **kw):
        lines_out.append(compact(msg("verify.quality.density", ratio="80%", max="60%")))
        return False, False, "[quality] 原文报告", (0,), verification.VerificationReport()
    graph_mod._check_batch = fake_check
    try:
        with tempfile.TemporaryDirectory() as d:
            records = []
            chat = ChatInvoker(settings, chat=FakeChat(responses=[archived]), log=lambda _: None)
            graph = build_batch_graph(chat=chat, review_chat=chat, settings=settings, params=params,
                                      workdir=Path(d), attempt_records=records, log=lambda _: None)
            _, warns = run_batch(graph, user="u", batch_text=batch, idx=1, frozen_units=None)
            assert warns[0]["params"]["report"] == {"t": "lines", "items": [
                {"code": "verify.quality.density", "params": {"ratio": "80%", "max": "60%"}}]}, warns[0]
            assert "旁白占比 80%" in warns[0]["message"] and "原文报告" not in warns[0]["message"]
            assert records[0]["report"] == "[quality] 原文报告", "尝试记录照旧存原文（R12）"
    finally:
        graph_mod._check_batch = orig_check
    print("graph: 降级警告的报告是逐条 ✓")

    # 3e. 整章结构终检未过：ConversionError 带 final_report.lines()。只换掉 convert 模块里的引用，单批图照常校验
    import types
    import pipeline.convert as convert_mod
    real_v = convert_mod.verification

    def failing(doc, **kw):
        r = verification.VerificationReport()
        r.add("FID-SOURCE-001", "critical", "/source/units", "source units do not reconstruct the normalized input")
        return r
    convert_mod.verification = types.SimpleNamespace(verify_document=failing,
                                                     recompute_coverage_field=real_v.recompute_coverage_field)
    try:
        with tempfile.TemporaryDirectory() as d:
            try:
                convert_mod.convert_text(batch, params, settings=settings, llm=FakeChat(responses=[archived]),
                                         batches=[batch], workdir=Path(d), log=lambda _: None)
                raise AssertionError("终检未过应抛 ConversionError")
            except ConversionError as e:
                assert e.code == "job.final_verify_failed"
                assert e.lines[0]["params"]["detail"] == {"code": "verify.rule.FID-SOURCE-001", "params": {}}
                assert e.lines[-1] == {"code": "verify.report.fail", "params": {"n": 1}}
    finally:
        convert_mod.verification = real_v
    print("convert: 整章终检的失败报告带逐条 ✓")
    ```
    （`graph_mod`、`orig_check`、`verification` 在第 3b 节已导入并定义；3d 放在 3b 的 `finally` 之后。）
  - `test_offline.py` 第 369 行：
    ```python
        rep = warnings[0]["params"]["report"]
        assert rep["t"] == "lines" and rep["items"][0] == {"code": "verify.quality.density",
                                                            "params": {"ratio": "80%", "max": "60%"}}, rep
        assert "旁白占比 80%" in warnings[0]["message"]
    ```
    （`max` 是该用例 `Settings` 的默认 `narration_density_max=0.6`。）
- [ ] **Step 2: 运行确认失败**：`test_graph.py` 第 3 节 `e.lines == []`；`test_offline.py` 报 `KeyError: 't'` 不等于 `lines`。
- [ ] **Step 3: `verification.py`**：导入补 `REPORT_MAX` 与 `from render.providers.base import scrub_secrets`；模块末尾加：
  ```python
  def tool_line(text: str) -> dict:
      """检查工具（lint、保真、合并）的子进程输出：原文（中文）原样显示，外面一行按语言渲染的标题（计划 R6）。"""
      return compact(msg("verify.report.tool", text=vendor(scrub_secrets(text.strip()), limit=REPORT_MAX)))
  ```
- [ ] **Step 4: `graph.py`**
  - 导入：`from server.messages import REPORT_MAX, compact, lines_of, msg, vendor`。
  - `_scrub_tree` 之后加：
    ```python
    def _shown(code: str, /, **params) -> list:
        """一条给用户看的逐条消息（放进列表）。generate、repair_agent 里的局部变量 msg 是模型回复，
        遮住了 messages.msg，节点函数里一律经这里生成（计划 R11）。"""
        return [compact(msg(code, **params))]


    def _report_param(text: str, shown: list) -> dict:
        """降级警告与失败报告的 report 参数：有逐条消息用 lines（按界面语言渲染），没有（如测试替身直接给的字符串）
        退回报告原文。两种都先脱敏（spec 子计划 5 C、E）。"""
        if shown:
            return lines_of(_scrub_tree(shown))
        return vendor(scrub_secrets(text), limit=REPORT_MAX)
    ```
  - `BatchState` 在 `report: str` 下面加：`shown: List[dict]          # 同一份报告给用户看的逐条消息（report 是回喂模型的原文，spec 子计划 5 C）`。
  - `_check_batch` 签名末尾加 `lines_out=None`，文档字符串补「lines_out（可选）收同一份报告给用户看的逐条消息；全部通过时为空」。函数开头 `out = lines_out if lines_out is not None else []`，然后：
    ```python
        if not structured.ok:
            out.extend(structured.lines())
            return False, True, structured.render(), None, structured
        lint_ok, lint_out = validate.run_lint(tmp)
        fid_ok, fid_out = validate.run_fidelity(tmp, batch_text, workdir)
        if not (lint_ok and fid_ok):
            text = lint_out.strip() + "\n" + fid_out.strip()
            out.append(verification.tool_line(text))
            return False, True, text, None, structured

        gate_ok, gate_report, ratio = quality.narration_density_gate(
            doc, settings.narration_density_max, lines_out=out)
        …
        fit_ok, fit_report, over = quality.speech_fit_gate(
            doc, settings.speech_overflow_max, settings.speech_cps, lines_out=out)
        …
            rev_ok, rev_report, overall = review.run_review(
                review_chat, batch_text, doc, settings.review_min_score,
                settings.review_dimension_min, settings.semantic_fidelity_min, lines_out=out)
        …
        out.clear()          # 全部通过：评审通过时也写了逐条，不需要
        return True, False, structured.render(), None, structured
    ```
  - `check` 节点：
    - `repair_failed` 分支：`shown = list(state["shown"])`，返回值加 `"shown": shown`；
    - `state["doc"] is None` 分支：返回值加 `"shown": _shown("verify.attempt.unparseable")`；
    - 调 `_check_batch` 前 `shown: list = []`，调用末尾加 `lines_out=shown`；
    - 通过时返回值加 `"shown": []`；
    - `candidates.append((key, attempt, doc, report, shown))`；
    - 未通过时返回值加 `"shown": shown`。
  - `repair_agent` 两处 `repair_failed`：
    ```python
                return {"repair_failed": True, "report": report, "tool_steps": steps,
                        "shown": _shown("verify.attempt.too_many_steps", max=_MAX_TOOL_STEPS)}
    ```
    ```python
                return {"messages": [msg], "repair_failed": True, "report": report,
                        "tool_steps": steps, "shown": _shown("verify.attempt.no_tool_call")}
    ```
  - `finalize`：
    ```python
            key, best_attempt, doc, report, shown = max(state["candidates"], key=lambda c: c[0])
            …
            warning = msg("job.quality.degraded", batch=idx, retries=settings.max_retries,
                          attempt=best_attempt, candidates=len(state["candidates"]),
                          report=_report_param(report, shown))
            …
        raise ConversionError.of("job.batch_failed", state["report"], _scrub_tree(state["shown"]),
                                 batch=idx, retries=settings.max_retries)
    ```
  - `run_batch` 的初始状态加 `"shown": []`。
  - 回喂模型的 `plan_repair`（两种模式）仍只用 `state["report"]`，不改。
- [ ] **Step 5: `convert.py`**：
  ```python
          if not ok:
              raise ConversionError.of("job.merge_failed", out, [verification.tool_line(out)])
  …
      if not final_report.ok:
          …
          raise ConversionError.of("job.final_verify_failed", final_report.render(), final_report.lines())
      if not (lint_ok and fid_ok):
          …
          raise ConversionError.of("job.final_check_failed", lint_out + "\n" + fid_out,
                                   [verification.tool_line(lint_out + "\n" + fid_out)])
  ```
- [ ] **Step 6: 登记**：
  ```python
  register("verify.report.tool", "检查工具的输出（原文）：\n{text}")
  register("verify.attempt.unparseable", "输出无法解析为 JSON")
  register("verify.attempt.no_tool_call", "这轮修复没有发起任何工具调用")
  register("verify.attempt.too_many_steps", "这轮修复超过了 {max} 个工具步骤")
  ```
  `--write`。前端：
  - `zh.ts`：`srv.verify.report` 加 `tool: '检查工具的输出（原文）：\n{text}'`；`srv.verify` 加 `attempt: { unparseable: '输出无法解析为 JSON', no_tool_call: '这轮修复没有发起任何工具调用', too_many_steps: '这轮修复超过了 {max} 个工具步骤' }`；
  - `en.ts`：`tool: 'Checker output (original text):\n{text}'`；`attempt: { unparseable: 'The output couldn’t be parsed as JSON', no_tool_call: 'This repair round made no tool calls', too_many_steps: 'This repair round went over the limit of {max} tool steps' }`。
- [ ] **Step 7: 跑全部校验并提交**：
  ```bash
  git add backend/pipeline/verification.py backend/pipeline/graph.py backend/pipeline/convert.py \
    backend/server/messages.py backend/server/messages_codes.json backend/tests/pipeline/test_graph.py \
    backend/tests/pipeline/test_offline.py frontend/src/i18n/zh.ts frontend/src/i18n/en.ts
  git commit -m "转换流水线带上逐条报告：每次校验在生成回喂模型报告的同时留一份给用户的逐条消息，降级警告与批次失败、合并失败、整章终检失败的报告都改为逐条；检查工具的输出原样显示、外加一行按语言的标题；回喂模型与尝试记录照旧用原文"
  ```

---

### Task 5: 接口：失败报告、编辑卡复验原因、验证门与保存的回归

**Files:**
- Modify: `backend/server/app.py`（`_execute`、`_check_version_doc`；顶部从 `server.messages` 的导入加 `lines_of`）
- Modify: `backend/server/messages.py`（`verify.finding` 一行的注释）
- Test: `backend/tests/server/test_jobs.py`、`backend/tests/server/test_assistant_ops.py`、`backend/tests/server/test_novels.py`

- [ ] **Step 1: 写失败测试**
  - `test_jobs.py` 的 `part_execute` 里，现有「ConversionError 带报告」那一段之后加（那一段不带逐条，继续守护退回原文的分支）：
    ```python
        # 子计划 5：ConversionError 带逐条消息 → report 参数是 lines；逐条里的数据目录换成 <data>；不再用报告原文
        from server.messages import compact
        shown = [compact(msg("verify.report.tool", text=vendor(f"ERROR 路径 {auth.DATA_DIR}/users/x")))]
        job = new_job(nid, cid, "v_lines")
        v = run(job, fake_raise(ConversionError.of("job.batch_failed", "原文报告", shown, batch=1, retries=0)))
        rep = v["error_msg"]["params"]["report"]
        assert rep["t"] == "lines" and rep["items"][0]["code"] == "verify.report.tool", rep
        assert str(auth.DATA_DIR) not in json.dumps(rep, ensure_ascii=False)
        assert rep["items"][0]["params"]["text"]["text"] == "ERROR 路径 <data>/users/x"
        assert v["error"] == "批 1 重试 0 次后仍未通过校验\n检查工具的输出（原文）：\nERROR 路径 <data>/users/x", v["error"]
    ```
  - `test_jobs.py` 新增 `part_gate()`，在 `main()` 的 `part_execute(nid, cid)` 之后调用：
    ```python
    def part_gate():
        """验证门 422 的附加字段 verification：每条 finding 带 msg（spec 子计划 5 C）；名字与其余内容不变。"""
        from fastapi import HTTPException
        bad = {"source": {"units": []},
               "episodes": [{"id": "E01", "shots": [{"id": "E01-SH001", "source": {"unit_refs": ["u0099"]}}]}]}
        try:
            app_mod._render_gate(bad, None)
            raise AssertionError("应被验证门拦下")
        except HTTPException as e:
            fs = e.detail["verification"]["findings"]
            assert e.detail["code"] == "verify.gate.blocked" and e.detail["verification"]["status"] == "failed" and fs
            assert all(f["msg"]["code"] == "verify.rule." + f["rule_id"] and f["message"] for f in fs)
            assert any(f["msg"] == {"code": "verify.rule.REF-UNIT-001", "params": {"unit": "u0099"}} for f in fs)
        print("验证门：422 的逐条带消息对象 ✓")
    ```
  - `test_assistant_ops.py` 第 130 行之后加：
    ```python
    assert all(w["params"]["detail"]["code"].startswith("verify.rule.") and "t" not in w["params"]["detail"]
               for w in chk["warnings"]), "复验原因的 detail 是该条规则的消息对象（子计划 5）"
    assert any(w["params"]["detail"] == {"code": "verify.rule.REF-NARRATION-001", "params": {"unit": "u99999"}}
               for w in chk["warnings"]), chk["warnings"]
    ```
  - `test_novels.py` 第 543 行（`NOVEL-LIFECYCLE-001` 那条断言）之后加：
    ```python
        assert all(f["msg"]["code"] == "verify.rule." + f["rule_id"] for f in r["verification"]["findings"]), \
            "保存后返回的每条带消息对象"
        stored = novels.get_version(A["id"], anid, ch2["id"], v2)["verification"]
        assert stored["findings"] and all("msg" in f for f in stored["findings"]), "存进版本记录的同样带"
    ```
    （`A["id"]`、`anid`、`ch2`、`v2` 是该用例里已有的变量；以实际名字为准。）
- [ ] **Step 2: 运行确认失败**：`test_jobs.py` 报 `rep["t"] == "vendor"`；`test_assistant_ops.py` 报 `detail["code"]` 的 `KeyError`。`part_gate` 与 `test_novels.py` 的新断言此时已经能过（Task 2 已让 `to_dict()` 带 `msg`），它们是回归守护。
- [ ] **Step 3: `app.py`**
  - 导入：`from server.messages import REPORT_MAX, UserError, compact, lines_of, money, msg, ref, render_zh, to_detail, vendor, with_ref`。
  - `_execute` 的 `except (ConversionError, LLMError)` 分支：
    ```python
            m = e.as_msg()
            report = getattr(e, "report", "") or ""
            shown = getattr(e, "lines", None) or []
            if report or shown:
                # 逐条消息优先（按界面语言渲染，spec 子计划 5 C）；没有逐条的退回报告原文
                body = (lines_of(error_refs.scrub_deep(shown)) if shown
                        else vendor(error_refs.scrub_text(report), limit=REPORT_MAX))
                m = msg("job.failed_report", reason=compact(m), report=body)
    ```
  - `_check_version_doc`：
    ```python
        return {"ok": report.ok,
                "warnings": [_hide_root_deep(msg("verify.finding", path=f.object_path, detail=f.as_msg()),
                                             auth.DATA_DIR) for f in report.errors][:5]}
    ```
    文档字符串里「每条是 verify.finding 消息对象」补上「，detail 是该条规则的消息对象」。
- [ ] **Step 4: `messages.py`**：`register("verify.finding", …)` 行尾注释改为 `# 编辑卡的复验原因；detail 是该条规则的消息对象（子计划 5），旧存档里是厂商原文`。不改登记内容，代码表不变。
- [ ] **Step 5: 扫描**：`_execute`、`_check_version_doc` 已在 app 函数集合里，改动后仍为零。
- [ ] **Step 6: 跑全部校验并提交**：
  ```bash
  git add backend/server/app.py backend/server/messages.py backend/tests/server/test_jobs.py \
    backend/tests/server/test_assistant_ops.py backend/tests/server/test_novels.py
  git commit -m "接口改用逐条报告：转换失败的报告参数取逐条消息并整体脱敏，没有逐条时照旧用原文；助手编辑卡的复验原因改为该条规则的消息对象；补验证门与保存返回的逐条带消息对象的回归测试"
  ```

---

### Task 6: 前端各显示处的中英渲染测试

Task 0 已经改好代码，Task 2–4 补齐了文案。本 Task 在每个显示处补「按代码渲染、切换语言跟着变、旧数据照旧显示」的用例；发现渲染问题就地修。

**Files:**
- Test: `frontend/tests/workspace.test.tsx`（JobPanel：失败区、质量报告、任务验证面板）、`frontend/tests/flow.test.tsx`（保存后与渲染被拦的验证面板）、`frontend/tests/assistant.test.tsx`（编辑卡复验原因）
- Modify（仅当测试暴露问题时）：`frontend/src/components/JobPanel.tsx`、`VerificationPanel.tsx`、`assistant/ActionCard.tsx`

- [ ] **Step 1: 写测试**
  - `workspace.test.tsx` 的「7. 动态面板」里，`console.log('7. 动态面板 ✓')` 之前加：
    ```ts
      // 子计划 5：失败区与质量报告的逐条（lines）、任务验证面板的每条说明，按代码渲染并随语言变化；旧 finding 显示 message
      const line = { code: 'verify.report.finding', params: { severity: { t: 'ref', code: 'verify.severity.high' }, rule: 'REF-UNIT-001',
        path: '/episodes/0/shots/0/source/unit_refs', detail: { code: 'verify.rule.REF-UNIT-001', params: { unit: 'u0099' } } } }
      const failedL = { code: 'job.failed_report', params: { reason: { code: 'job.batch_failed', params: { batch: 2, retries: 3 } },
        report: { t: 'lines', items: [line, { code: 'verify.report.fail', params: { n: 1 } }] } } }
      await render(jwrap(h(JobPanel, { job: jobOf([], { status: 'failed', error: '旧中文', error_msg: failedL }), ...props })))
      must(q('.job__err')?.textContent === '批 2 重试 3 次后仍未通过校验\n严重 [REF-UNIT-001] /episodes/0/shots/0/source/unit_refs：'
        + '镜头引用了不存在的原文句子 u0099\n未通过（1 条硬性问题）', '失败区逐条（中文）：' + q('.job__err')?.textContent)
      await lang('en')
      const enLine = en.srv.verify.report.finding.replace('{severity}', en.srv.verify.severity.high).replace('{rule}', 'REF-UNIT-001')
        .replace('{path}', '/episodes/0/shots/0/source/unit_refs')
        .replace('{detail}', en.srv.verify.rule['REF-UNIT-001'].replace('{unit}', 'u0099'))
      must((q('.job__err')?.textContent ?? '').includes(enLine) && !(q('.job__err')?.textContent ?? '').includes('严重'),
        '失败区逐条切英文：' + q('.job__err')?.textContent)
      await lang('zh')
      const deg = { code: 'job.quality.degraded', params: { batch: 1, retries: 2, attempt: 2, candidates: 2,
        report: { t: 'lines', items: [{ code: 'verify.quality.density', params: { ratio: '80%', max: '60%' } }] } } }
      await render(jwrap(h(JobPanel, { job: jobOf([], { status: 'completed_with_warnings', quality_report: '旧', quality_msg: [deg] }), ...props })))
      must(qtxt().includes(zh.srv.verify.quality.density.replace('{ratio}', '80%').replace('{max}', '60%')), '质量报告逐条（中文）：' + qtxt())
      await lang('en')
      must(qtxt().includes(en.srv.verify.quality.density.replace('{ratio}', '80%').replace('{max}', '60%')) && !qtxt().includes('旁白占比'),
        '质量报告逐条切英文：' + qtxt())
      await lang('zh')
      const ver = { status: 'failed', coverage: {}, findings: [
        { rule_id: 'REF-UNIT-001', severity: 'high', object_path: '/episodes/0/shots/0/source/unit_refs',
          message: 'shot references unknown source unit u0099', unit_refs: ['u0099'],
          msg: { code: 'verify.rule.REF-UNIT-001', params: { unit: 'u0099' } } },
        { rule_id: 'ID-SHOT-001', severity: 'high', object_path: '/episodes', message: 'duplicate shot id E01-SH001' }] }
      await render(jwrap(h(JobPanel, { job: jobOf([], { status: 'failed', error: 'x', verification: ver }), ...props })))
      const vmsg = () => [...doc.querySelectorAll('.vf__msg')].map((x) => x.textContent ?? '')
      must(vmsg()[0] === '镜头引用了不存在的原文句子 u0099' && vmsg()[1] === 'duplicate shot id E01-SH001',
        '验证面板：有 msg 按代码，旧 finding 显示 message：' + vmsg().join('|'))
      await lang('en')
      must(vmsg()[0] === en.srv.verify.rule['REF-UNIT-001'].replace('{unit}', 'u0099') && vmsg()[1] === 'duplicate shot id E01-SH001',
        '验证面板切英文：' + vmsg().join('|'))
      await lang('zh')
    ```
  - `flow.test.tsx`：
    - `INVALID` 之后加一个带 `msg` 的版本：
      ```ts
      const INVALID_MSG = { ...INVALID, findings: [{ ...INVALID.findings[0], rule_id: 'FID-DIALOGUE-001',
        msg: { code: 'verify.rule.FID-DIALOGUE-001', params: {} } }] }
      ```
    - 现有「保存后 draft_invalid」（约 1277 行）与「渲染被拦」（约 1288–1294 行）两段之后，各照原样再走一遍，桩换成 `INVALID_MSG`：
      - 中文：`has(zh.srv.verify.rule['FID-DIALOGUE-001'])`，且没有 `'台词不是所引原文句的逐字摘录'`（`message` 不再显示）；
      - `await act(async () => { setLoc('en') })` 之后：`has(en.srv.verify.rule['FID-DIALOGUE-001'])`，再切回中文。
      - 渲染被拦这一段把 `blockNextRender` 的 422 桩改成可选报告：`let blockReport: unknown = INVALID`，桩里用 `verification: blockReport`，这一段前置 `blockReport = INVALID_MSG`、结束后还原。
    - 原有两段（`INVALID`，没有 `msg`）保持不动：守护旧报告显示 `message`。
  - `assistant.test.tsx` 约 430 行的 `diffCard.warnings` 里加第三条（嵌套规则消息）：
    ```ts
                       { code: 'verify.finding', params: { path: '/episodes/0/shots/0',
                         detail: { code: 'verify.rule.EVIDENCE-SHOT-001', params: {} } } }
    ```
    在现有「warnings 两条都显示」的断言旁边加：卡上有 `'/episodes/0/shots/0: ' + zh.srv.verify.rule['EVIDENCE-SHOT-001']`；照本文件现有的切英文写法切到英文后，有 `'/episodes/0/shots/0: ' + en.srv.verify.rule['EVIDENCE-SHOT-001']`，厂商原文那条「时长对不上」与旧字符串照旧显示。原有的条数断言（如果写死为 2）改为 3。
- [ ] **Step 2: 运行**：`cd frontend && npm test`。代码在 Task 0 已改，预期直接通过；若不通过，按失败信息修对应组件（不得改测试的期望去迁就实现）。
- [ ] **Step 3: 跑全部校验并提交**：
  ```bash
  git add frontend/tests/workspace.test.tsx frontend/tests/flow.test.tsx frontend/tests/assistant.test.tsx
  git commit -m "前端补验证报告逐条的显示测试：转换失败区、质量报告、任务与保存后的验证面板、渲染被拦的面板、助手编辑卡的复验原因，按代码渲染并随语言切换，旧报告照旧显示原文"
  ```
  （若 Step 2 修了组件，把改到的组件文件一起 `git add`。）

---

### Task 7: 收尾核对

**Files:**
- Modify（如需要）：`backend/tests/server/test_i18n_scan.py`、`backend/server/messages_codes.json`

- [ ] **Step 1: 扫描范围核对**：`test_i18n_scan.py` 的 `MODULES` 至少包含 `pipeline/verification.py`、`pipeline/quality.py`、`pipeline/repair.py`（全文件）、`pipeline/novel_memory.py`（`soft_findings`），以及原有的 `pipeline/review.py`、`pipeline/graph.py`、`pipeline/convert.py`、`pipeline/errors.py`；扫描打印 `ALL PASS`。
- [ ] **Step 2: 零命中复核**（不依赖 `MODULES` 是否写全；输出必须为空）：
  ```bash
  cd backend && .venv/bin/python - <<'PY'
  import importlib.util
  spec = importlib.util.spec_from_file_location("scan", "tests/server/test_i18n_scan.py")
  m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
  for rel in ["pipeline/verification.py", "pipeline/quality.py", "pipeline/repair.py", "pipeline/review.py",
              "pipeline/graph.py", "pipeline/convert.py", "pipeline/errors.py"]:
      for h in m.scan(rel, None):
          print(h)
  for h in m.scan("pipeline/novel_memory.py", {"soft_findings"}):
      print(h)
  for h in m.scan("server/app.py", {"_execute", "_check_version_doc", "_render_gate"}):
      print(h)
  PY
  ```
- [ ] **Step 3: 规则齐全**：`grep -o '"[A-Z]*\(-[A-Z]*\)*-[0-9]\{3\}"' pipeline/verification.py pipeline/novel_memory.py | sort -u | wc -l` 为 23，与 `messages_codes.json` 里 `verify.rule.` 开头的键数相同（`test_verify_msgs.py` 第 4 节已断言，这里人工再看一眼）。
- [ ] **Step 4: 回喂模型不变**：
  - `git diff <子计划 5 开始前的提交> -- backend/pipeline/quality.py backend/pipeline/review.py` 里，报告字符串的拼接行没有改动（只有新增的 `lines_out` 分支）；
  - `git diff … -- backend/pipeline/graph.py` 里 `plan_repair` 没有改动；
  - `test_verify_msgs.py` 第 5、7、8、9 节通过。
- [ ] **Step 5: 文案检查**：
  - `grep -in "deepseek\|claude\|anthropic" server/messages_codes.json ../frontend/src/i18n/zh.ts ../frontend/src/i18n/en.ts` 不得命中任何登记的文案与 `srv` 节点；
  - `grep -n "jsonschema\|STORYBOARD_" server/messages_codes.json` 为空（引擎缺失那条不写库名）；
  - 英文 `srv.verify` 节点里没有 `(s)` 式的单复数写法。
- [ ] **Step 6: 测试不碰真实数据目录与模型服务**：
  - 实施前记下 `ls -l backend/data/error_refs.jsonl backend/data/usage.jsonl 2>/dev/null`，跑完全部测试后再看一次：不存在的仍不存在，存在的大小与修改时间不变；
  - `test_verify_msgs.py` 设了临时 `STORYBOARD_DATA_DIR`、不可达的 `ANTHROPIC_BASE_URL`，桩掉了 `_load_dotenv`；评审只用 `Stub`。
- [ ] **Step 7: 代码表最新**：`.venv/bin/python -m server.messages --write && git diff --exit-code server/messages_codes.json`。
- [ ] **Step 8: 全部校验**（全局约束里的整套）。
- [ ] **Step 9: 有改动才提交**（只 add 改到的文件）。提交信息示例：「子计划 5 收尾：扫描覆盖验证、质量门、修复与软核查并清零，确认 23 条规则全部登记、回喂模型的文字未变」。

---

## 实施裁定

- **R1 finding 加 `msg`，不替换 `message`**：
  - 裁定：`Finding.to_dict()` 多一个 `msg: {code, params}`，`message` 照旧；`to_dict(shown=False)` 是回喂模型的旧形状。
  - 理由：`message` 是修复模型读的原文（`validation_list` 工具、`repair_request`），换掉会改变模型行为；追加字段旧前端忽略，旧报告没有 `msg` 时面板退回 `message`，不用迁移。
  - 若错的代价：版本记录里每条 finding 多几十字节。报告很长时（上百条）版本文件略大，可以接受。
- **R2 报告参数换成 `lines`，包装代码不变**（spec 子计划 5 C 的取舍）：
  - 裁定：`job.failed_report`、`job.quality.degraded` 的代码、参数名、模板都不变，只把 `report` 的值从厂商原文换成 `{"t":"lines","items":[…]}`。
  - 理由：
    - 报告由几种来源拼成，按行组织最贴近原样，也最好截断；
    - 子计划 4 R3 预留的就是这一步，`failHead`、`quality_msg` 的存法、一行显示的地方都不用改；
    - 列表类型已有「顿号/逗号连接」的语义，不能拿来表示换行，所以新增一种类型，而不是复用列表。
  - 若错的代价：旧前端（Task 0 之前）遇到 `lines` 渲染为空串，报告正文消失但不崩。前后端同仓同发，Task 0 先落地。
- **R3 用出参 `lines_out`，不改返回元组**：
  - 裁定：`narration_density_gate`、`speech_fit_gate`、`run_review`、`_check_batch` 加可选关键字参数 `lines_out`，把逐条消息追加进调用方的列表。
  - 理由：
    - 这几个函数的返回元组被现有测试直接解包（`test_offline.py`、`test_graph.py`、`test_chat.py` 十余处），`_check_batch` 还被测试整个替换成 `lambda *a, **kw`；出参让这些调用与替身都不用改；
    - 与本项目 `warnings_out`、`manifest_out`、`progress_out` 的写法一致；
    - spec 要求「同一处生成两份」：逐条消息就在拼报告字符串的同一个函数里生成。
  - 若错的代价：漏传 `lines_out` 的调用方拿不到逐条，降级与失败退回原文（`_report_param` 的兜底分支），信息不丢。
- **R4 原文本来是中文的三条，`message` 由模板生成**：
  - 裁定：`ORDER-001`、`NOVEL-CONSTRAINT-001`、`NOVEL-LIFECYCLE-001` 不再写中文 f-string，`Finding` 构造时用中文兜底填 `message`。
  - 理由：中文模板与原文一字不差（列表参数用「、」连接、代码引用渲染为「已死亡」），源码里也就没有中文字面量，扫描自然清零，不用标豁免；文字只写一处。
  - 若错的代价：以后改这三条的中文模板，回喂模型（`ORDER-001`）与旧前端看到的文字会一起变。`test_verify_msgs.py` 第 1、3 节的原文断言会先报出来。
- **R5 消息对象存紧凑形**：
  - 裁定：finding 的 `msg` 与 `lines` 的每项都是 `{code, params}`，不带 `message`。
  - 理由：`srv-codes` 保证每个代码都有中英文案，前端用不到 `message`；报告可能上百条，省掉中文兜底能少存一半。`findingText` 缺译时回落到 finding 自己的 `message`，不会显示代码名。
  - 若错的代价：只看原始 JSON 的人读不到中文。命令行与调试日志用的是 `render()` 原文，不受影响。
- **R6 检查工具的输出保持原文**：
  - 裁定：lint、保真、合并三个子进程的输出作为一项 `verify.report.tool {text}`，`text` 是厂商原文（脱敏、截断 6000 字），标题按语言渲染，正文仍是中文。
  - 理由：
    - 这三个工具是独立的命令行脚本，输出是给人和模型读的文字；要逐条翻译得先给它们加结构化输出，约 35 条文案，超出本子计划；
    - 实际触达用户的机会小：保真检查与 `FID-SOURCE-001` 重复，结构校验先跑，保真失败时结构校验已经失败、不会走到它；lint 与结构校验多数重叠，只多出 `music.curve`、道具状态、服装等少数检查，而 `music.curve` 的引用程序会先自动规整。
  - 若错的代价：英文界面在 lint 失败时看到一段中文。后续可以给 `tools/lint_storyboard.py` 加 `--json` 输出，再按条登记（见交付报告的开放问题）。
- **R7 数值预先格式化成字符串**：
  - 裁定：总分、阈值、秒数、字/秒、百分比在后端用与原报告相同的格式（`f"{x}"`、`:g`、`:.1f`、`:.0%`）转成字符串再作参数；计数（句数、镜头数、`n`）保持整数。
  - 理由：前端 `String(3.0)` 是 `"3"`，后端中文兜底是 `"3.0"`，不预先格式化两边会不一致；百分比与秒数的写法与原报告保持一致，用户对得上调试日志。
  - 若错的代价：英文界面里的小数点与百分号沿用中文写法（本来就是通用写法）。
- **R8 数据原样显示**：
  - 裁定：句子与镜头编号、JSON 路径、字段名（`SOURCE-FROZEN-002` 的 `text`/`para`）、句子类型（`action`/`description`/`dialogue`）、用户原文、用户写的限制、角色名都原样作参数，不翻译。
  - 理由：它们是数据或给开发看的标识；路径由验证面板另行翻成「集 / 镜」，失败报告里保留原路径便于对照。
  - 若错的代价：中文界面的失败报告里出现英文字段名与类型名（与现在相同）。
- **R9 评审的两类失败只说现象**：
  - 裁定：调用失败给 `verify.review.unavailable {cause}`，`cause` 是映射后的 `llm.*`（子计划 4 C），映射不出时 `verify.review.call_failed`；输出无法核验给 `verify.review.unverifiable`，不带细节。
  - 理由：调用失败的原文可能带模型名（子计划 4 E）；无法核验的细节是我们对模型 JSON 的格式检查（中文、给模型重试用），对用户没有意义，完整原文在调试日志里。
  - 若错的代价：用户看不到评审输出为什么无法核验，管理员要去调试日志查。
- **R10 旧报告不迁移**：
  - 裁定：版本记录、助手存档里的旧 `verification`、旧 `error_msg`、旧编辑卡都不改写。`verification_identity`（对 `to_dict()` 取哈希）多了 `msg` 后值会变，目前没有调用方，不处理。
  - 理由：旧数据都能显示（`message`、厂商原文），前端两种形状都认；产品还没上线。
  - 若错的代价：旧版本切到英文界面时，验证面板显示的是原来的英文规则说明、失败报告是原来的中文原文。以后若有人用 `verification_identity` 比对新旧报告，要先去掉 `msg`。
- **R11 节点里的 `msg` 被局部变量遮住**：
  - 裁定：`graph.py` 的节点函数里一律用模块级的 `_shown(code, **params)` 生成逐条消息，不直接调用 `msg(…)`。
  - 理由：`generate`、`repair_agent` 里有 `msg = chat.invoke(…)`，Python 会把整个函数里的 `msg` 当成局部变量，在赋值之前调用 `msg(…)` 会抛 `UnboundLocalError`。`finalize` 没有这个局部变量，照旧直接用 `msg`。
  - 若错的代价：无（只是写法约定）。`verification.py` 的 `_validate_evidence` 有同样的情形（循环变量 `ref` 遮住导入的 `messages.ref`），本计划只在 `lines()` 里调用 `ref(…)`，Task 2 Step 3 已注明。
- **R12 尝试记录照旧存原文**：
  - 裁定：`manifest.attempts[].report` 不改，`verification` 随 `to_dict()` 自动带 `msg`。
  - 理由：前端不显示尝试记录，它是审计用的出处证明，原文最有价值；普通用户视图里的主机路径已由 `_public_manifest` 换成占位。
  - 若错的代价：以后若在界面上展示尝试记录，要给每次尝试另存逐条消息。
- **R13 逐条最多 100 项**：
  - 裁定：`lines_of` 超过 100 项截掉，末尾补 `common.more_lines {n}`；每个厂商原文项照旧截断 300 字（检查工具输出 6000 字）。
  - 理由：原来整份报告上限 6000 字；旁白密度门两组各 40 句再加标题约 83 项，100 项能完整放下单个门的清单；结构校验上百条时，验证面板另有完整的结构化报告。
  - 若错的代价：报告极长时失败区只显示前 100 项，完整原文在调试日志与工作目录的失败报告文件里。
- **R14 `Finding` 构造时就校验参数**：
  - 裁定：`__post_init__` 调 `msg()`，代码未登记或参数不符直接抛错。
  - 理由：漏登记、漏参数在第一次触发那条规则时就暴露；`test_verify_msgs.py` 第 1–4 节让 23 条规则各触发一次，并核对源码里的规则编号与登记表一一对应。
  - 若错的代价：以后新加规则忘了登记，转换会在校验时抛错（走 `job.crashed` 带编号），而不是悄悄显示代码名。第 4 节的编号对照会在测试里先抓到。
- **R15 不按规则发进度事件**：
  - 裁定：转换途中仍只发「第 N 次生成未通过校验」这类事件（子计划 4 H），不把逐条消息放进进度。
  - 理由：失败与降级时报告里已有逐条；进度面板逐条刷屏反而难读。子计划 4 R13 把它列为「可以加回」，不是必须。
  - 若错的代价：用户在转换途中看不到每次重试的具体原因，要等结果。需要时在 `check` 节点里用 `shown` 发一条带 `lines` 参数的事件即可，数据已经现成。

## 自查记录

- **覆盖 spec 子计划 5 A 节**：
  - `verification.py` → Task 2（规则、`lines()`）、Task 4（`tool_line`）；`novel_memory.py`、`repair.py` → Task 2；`quality.py`、`review.py` → Task 3；`graph.py`、`convert.py` → Task 4；`errors.py`、`messages.py` 的 `lines`、`error_refs.scrub_deep` → Task 1；`app.py` → Task 5；
  - 前端 `serverMsg.ts`、`types.ts`、`VerificationPanel.tsx` → Task 0；`zh.ts`、`en.ts` → Task 1–4 各自登记时同步；
  - 「不在本子计划」三项写进范围边界与 R6、R12、R15。
- **覆盖 B 节**：23 条规则都在调用点清单的规则表里，参数与 spec 表一致；Task 2 的 `CASES`（20 条）加第 2 节（引擎缺失）、第 3 节（两条软核查）共 23 条，第 4 节核对源码与登记表。`ORDER-001`、`NOVEL-*` 的原文一字不差 → 第 1、3 节。
- **覆盖 C 节**：
  - 结构化报告的 `msg` → Task 2；`to_dict(shown=False)` 回喂不变 → Task 2 第 5 节；
  - `lines` 类型与 100 项截断 → Task 0（前端）、Task 1（后端）；
  - 「逐条消息怎样产生」表的九行：结构校验 → Task 2/4（`lines()`、`_check_batch`）；检查工具 → Task 4（`tool_line`）；密度门、时长门、评审 → Task 3，接入 → Task 4；解析失败、修复没产出 → Task 4（`verify.attempt.*`）；合并、整章终检 → Task 4；
  - 显示处表的每一行都在调用点清单的「显示处」里，测试在 Task 0（`failHead`、`formatMsg`）与 Task 6（JobPanel、验证面板三处、编辑卡）。
- **覆盖 D 节**：密度门的头行、两组标题、逐句（每组 40 句）与「不含操作指示」→ Task 3 第 7 节；时长门 → 第 8 节；评审五种情形（调用失败两种、无法核验、通过、未过门槛）→ 第 9 节；数值格式 → R7。
- **覆盖 E 节**：评审意见作厂商原文 → Task 3（`vendor`）与 Task 4（`_report_param` 的 `_scrub_tree`）、Task 5（`scrub_deep`）；jsonschema 原文 → Task 2；检查工具输出 → R6；数据原样 → R8。
- **覆盖 F 节**：
  - 旧报告：finding 没有 `msg` → Task 0 `findingText` 测试与 Task 6 验证面板第二条；`report` 是厂商原文 → Task 1 之后 `test_jobs.py` 现有用例、Task 4 第 3b 节（替身退回原文）；编辑卡的厂商原文 → Task 6 assistant 用例；
  - 旧前端 → Task 0 排在最前，R2；
  - 回喂模型 → Task 2 第 5 节、Task 3 第 7–9 节的特征断言、Task 4「`plan_repair` 不改」、Task 7 Step 4；
  - 中文兜底的文字变化 → Task 4 第 3d 节（`"原文报告" not in message`）、Task 5（`error` 的完整断言）；
  - `verification_identity` → R10。
- **覆盖 G 节**：后端各测试文件的增改都在对应 Task；ast 扫描的规则 → Task 1，模块 → Task 2、3，基线（新规则 3 处、`repair.py` 14 处、`quality.py` 0 处）→ Task 2 Step 8、Task 3 Step 7；前端四个测试文件 → Task 0、6。
- **覆盖 H 节**：`verify.rule.*`、`severity`、`lifecycle`、`report.finding/coverage/pass/fail` → Task 2；`quality.*`、`review.*` → Task 3；`report.tool`、`attempt.*` → Task 4；`common.more_lines` → Task 1。叶子与前缀：`verify.review.gates`/`gate.*`、`dim_score`/`dim.*`、`verify.finding`/`verify.report.finding` 逐个核对过，`register()` 的前缀检查也会在导入时报出。
- **中间提交前后端都能跑**：Task 0 先让前端认 `lines` 与 `msg`；Task 1 只加类型与基础函数；Task 2 只追加字段；Task 3 不接入流水线；Task 4 才改报告参数的形状；Task 5 只换接口里的取值。每个登记了代码的 Task 同时补 `zh.ts`、`en.ts`，`srv-codes` 每步都过。
- **名称一致**：后端 `lines_of`、`LINES_MAX`、`scrub_deep`、`_KEEP_KEYS`、`ConversionError.lines`、`Finding.params/code/as_msg/to_dict(shown=)`、`VerificationReport.lines`、`tool_line`、`lines_out`、`BatchState.shown`、`_shown`、`_report_param`；前端 `findingText`、`Finding.msg`。各 Task 引用一致。
- **扫描基线**（编写本计划时在仓库外的副本上跑的）：
  - 现有规则下：`verification.py` 0、`quality.py` 0、`novel_memory.soft_findings` 0、`repair.py` 14（全是 `RepairError`）；`novel_memory.py` 全文件另有 1 处（章后整理的 `ValueError`，不在本子计划，所以只扫 `soft_findings`）；
  - 加上 `Finding(…)`、`report.add(…)` 两个出口后：`verification.py` 1（`ORDER-001`）、`soft_findings` 2；已在 `MODULES` 里的模块仍为零。
- **特征断言的原文**：Task 3 第 7–9 节的报告字符串，是在仓库外的副本上用现有代码对同一份输入跑出来的，不是手写推测。
- **测试不碰真实模型**：新测试文件桩掉 `_load_dotenv`、设临时数据目录与不可达的 `ANTHROPIC_BASE_URL`；评审只用 `Stub`；模型接口异常在本地构造；转换用 `FakeChat`。
- **自查中发现并已改正**：
  - `graph.py` 的 `generate`、`repair_agent` 有局部变量 `msg`，直接调 `msg(…)` 会 `UnboundLocalError`，改为模块级 `_shown`（R11）；
  - `verification.py` 的 `_validate_evidence` 有循环变量 `ref`，`ref(…)` 只放在 `lines()` 里（R11、Task 2 Step 3）；
  - 消息函数原名 `lines()`，与 `app.py`、`graph.py` 里多处局部变量 `lines` 同名，改为 `lines_of()`，spec 同步改名；
  - `COVERAGE-001` 与 `NOVEL-CONSTRAINT-001` 的英文原稿用了 `line(s)`、`keyword(s)`，改为不依赖单复数的写法。
