# 后端双语 子计划 5b：分镜检查（lint）结构化输出与逐条翻译 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 转换失败时，lint（`tools/lint_storyboard.py`）报的错误在英文界面也按语言显示：
- lint 加 `--json`：每条错误带规则名与结构化参数，同一次运行另给出与文本模式逐字相同的 `text`；
- 流水线（批内校验与整章终检）改读 `--json`，按条登记 `verify.lint.<rule>`（23 条），失败区逐条按界面语言渲染；
- 回喂修复模型的文字、调试日志、失败报告文件、命令行默认输出一字不变；
- 保真工具与合并工具保持原文（子计划 5 的按行拆分）。

**Architecture:** 沿用子计划 5 的基础设施，不新增参数类型：
- 后端：`server/messages.py` 的 `register`/`msg`/`compact`/`vendor`/`ref`/`VENDOR_MAX`；`pipeline/verification.py` 的 `tool_lines`；`graph._check_batch` 的出参 `lines_out`、`BatchState.shown`、`ConversionError.lines`、`lines_of` 的截断；
- 前端：`i18n/serverMsg.ts` 的 `formatMsg`（嵌套消息、列表分隔、代码引用都已支持），`srv` 文案节点；
- 两道校验：`srv-codes` 与 ast 扫描。

新东西只有三处：
- lint 的 `_item(rule, 原文, **params)` 与 `--json`：原 f-string 原样留在 lint 里（回喂模型），规则名与参数只给 JSON 读者；
- `validate.LintReport` / `run_lint_report`：跑一次 `--json`，`text` 回喂模型，`errors` 给界面；
- `verification.lint_lines` / `checker_lines`：结构化错误 → `verify.report.lint` 标题 + 每条 `verify.report.tool_error {text: verify.lint.<rule>}`；认不出时退回子计划 5 的按行拆分。

**Tech Stack:** Python 3.12、LangGraph 1.2、jsonschema、脚本式测试、React 19 + TypeScript、Vite SSR 构建跑前端测试。

**Spec:** `docs/specs/2026-11-13-backend-i18n-design.md` 文末「子计划 5b 范围补充（2026-11-14）」A–H 八节（以及「子计划 5 范围补充」A「不在本子计划」、C、E、F、G 与「后续：子计划 5b」）。本计划与 spec 冲突时以 spec 为准；spec 没写的细节见文末「实施裁定」。

**本计划里的代码怎么来的**：Task 0 的快照字面量与哈希、Task 1–3 的全部代码与测试，是编写本计划时在仓库外的副本（`git archive 71f72a8`）上实际跑过的：快照测试在未改动的代码上通过；按 Task 1–3 改完后，后端全套脚本测试 `fail=0`，前端 `typecheck`、`server-msg`、`srv-codes`、`workspace`、`edit-validity` 通过，`oxlint` 仍是 5 条 warning。

---

## 全局约束（每个 Task 都必须遵守）

（前 8 条照抄子计划 5 计划的全局约束，其后是本子计划的增补。）

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
  - 提交信息中文、描述性，不带任何 `Co-Authored-By`、`Claude-Session` 或署名行；
  - 不 push。
- 改了登记表就运行 `cd backend && .venv/bin/python -m server.messages --write`，把 `backend/server/messages_codes.json` 一起提交。登记了新代码的 Task 必须同时在 `zh.ts`、`en.ts` 的 `srv` 节点加上对应键（`srv-codes` 会校验键齐全、中文一字不差、占位符一致）。规则编号带连字符，`srv` 里写成带引号的键：`'SCHEMA-001': '…'`（本子计划的 `verify.lint.*` 规则名是小写下划线，不用引号）。
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
- 中文兜底：`verify.lint.*` 的中文以本计划给出的为准（与 lint 原文意思相同、措辞更通顺），英文以本计划给出的为准。风格照现有 `en.ts` `srv` 节点：冒号后半角空格；不依赖单复数（数量放括号里或冒号后）；不出现 `.env`、环境变量名、异常类名、模型名或厂商名（DeepSeek、Claude、Anthropic 等）。

**本子计划增补**：
- **回喂模型的文字一字不改**：lint 的文本输出（`run_lint`、`run_lint_report().text`）、`graph._check_batch` 返回的报告、`repair.repair_request`、`plan_repair` 拼的整份重写回喂、`ConversionError.report`、调试日志与失败报告文件。由 Task 0 的 `test_lint_feed_snapshot.py` 守护：它只用改动前就有的接口，在任何改动之前单独提交并通过，之后每个 Task 的全套校验都包含它。
- **快照文件不得修改**：`backend/tests/pipeline/feed_snapshot.py`、`test_llm_feed_snapshot.py`（子计划 5），以及本计划 Task 0 新增的 `lint_snapshot.py`、`test_lint_feed_snapshot.py`，在 Task 0 之后都不得再改。快照对不上说明实现改了回喂内容，要改的是实现。
- **lint 命令行默认（文本）输出逐字不变**；`tools/lint_storyboard.py` 里每条原 f-string 一字不改，只包进 `_item(…)`。
- 后端测试跑法补充：单个脚本 `cd backend && .venv/bin/python tests/pipeline/test_lint_json.py`；lint 相关测试会起子进程跑 `tools/lint_storyboard.py`，用的是同一个 `sys.executable`。
- `npm run lint` 的基线是 5 条 warning（`timeline.ts` no-control-regex、`ParamsForm.tsx` 与 `VerificationPanel.tsx` only-export-components、`App.tsx` exhaustive-deps 等既有项），不得新增。

## 范围边界

- **本子计划改**：
  - `backend/tools/lint_storyboard.py`（`_item`、`--json`、汇报改为先拼文本）；
  - `backend/pipeline/validate.py`（`LintReport`、`run_lint_report`；`run_lint` 不改）；
  - `backend/pipeline/verification.py`（`_lint_value`、`_lint_msg`、`lint_lines`、`checker_lines`）；
  - `backend/pipeline/graph.py`（`_check_batch` 里 lint 那一段）、`backend/pipeline/convert.py`（整章终检那一段）；
  - `backend/server/messages.py`（登记 25 个代码）、`messages_codes.json`；
  - 测试：新增 `tests/pipeline/lint_snapshot.py`、`test_lint_feed_snapshot.py`（Task 0）、`test_lint_json.py`、`test_lint_msgs.py`；改 `test_graph.py`（3f 节替身）、`test_offline.py`（替身）；
  - 前端：`src/i18n/zh.ts`、`en.ts`；测试 `tests/server-msg.test.ts`、`tests/workspace.test.tsx`。
- **不改**：
  - `tools/check_fidelity.py`、`tools/merge_storyboard.py` 与它们的输出处理（`tool_lines`）；
  - `validate.run_lint`（文本模式，仍供 `test_offline.py` 的口径对照与外部脚本用）；
  - lint 的 WARN 不登记、不显示；
  - `test_i18n_scan.py` 的 `MODULES`（lint 不加进扫描，见 R9）；
  - 提示词、`plan_repair`、`repair.repair_request`、`_log_report`、`_record`；
  - 前端组件代码（`JobPanel`、`admin/JobsTab`、`serverMsg.ts`）。

## 调用点清单

### lint 的 23 处 `errors.append`（`tools/lint_storyboard.py`，Task 1；代码与文案 Task 2）

行号是改动前的。参数名与 spec 子计划 5b B 节一致。

| 行 | rule | 参数（lint 里怎么取值） |
|---|---|---|
| 33 | `schema` | `path="/" + "/".join(map(str, e.absolute_path))`、`detail=e.message` |
| 51 | `ref_image_outfit` | `card=card["id"]`、`outfit=tag`、`options=sorted(outfit_ids)` |
| 59 | `ref_image_state` | `card=card["id"]`、`state=tag`、`options=sorted(state_ids)` |
| 67 | `asset_empty_constraint` | `card=card.get("id")` |
| 86 | `curve_shot` | `episode=ep.get("id")`、`shot=ref` |
| 89 | `curve_unit` | `episode=ep.get("id")`、`unit=ref` |
| 92 | `curve_reversed` | `episode=ep.get("id")`、`start=f`、`end=t` |
| 109 | `shot_unit` | `shot=sid`、`unit=ref` |
| 113 | `inferred_no_note` | `shot=sid` |
| 123 | `beats_duration` | `shot=sid`、`total=f"{total:g}"`、`duration=f"{dur:g}"` |
| 127 | `beat_no_action` | `shot=sid`、`beat=i` |
| 131 | `shot_empty_constraint` | `shot=sid` |
| 135 | `location_ref` | `shot=sid`、`location=loc` |
| 140 | `prop_ref` | `shot=sid`、`prop=ref` |
| 145 | `prop_state_required` | `shot=sid`、`prop=ref`、`options=sorted(state_ids)` |
| 147 | `prop_state_unknown` | `shot=sid`、`prop=ref`、`state=state`、`options=sorted(state_ids)` |
| 149 | `prop_state_unexpected` | `shot=sid`、`prop=ref` |
| 155 | `creature_outfit` | `shot=sid`、`creature=ref` |
| 158 | `character_ref` | `shot=sid`、`character=ref` |
| 163 | `outfit_unknown` | `shot=sid`、`character=ref`、`outfit=outfit`、`options=sorted(outfit_ids)` |
| 168 | `dialogue_character` | `shot=sid`、`character=cref` |
| 173 | `narration_unit` | `shot=sid`、`unit=ref` |
| 190 | `coverage_unmapped` | `n=len(unmapped)`、`units=unmapped` |

WARN 6 处（35、94、97、104、195、199 行）：`schema_unavailable`、`curve_gap`（`episode`、`shot=f`）、`curve_incomplete`（`episode`）、`shot_id_prefix`（`shot=sid`、`episode`）、`coverage_declared_units`（`actual=unmapped`）、`coverage_declared_ratio`（`declared`、`actual=actual_ratio`）。

### lint 输出的去向（`pipeline/*`）

| 位置 | 现状 | 处置 | Task |
|---|---|---|---|
| `validate.run_lint` | 文本模式，`(ok, stdout + stderr)` | 不改 | — |
| 新增 `validate.run_lint_report` | — | 跑一次 `--json`，返回 `LintReport(ok, text, errors)` | 1 |
| `graph._check_batch` | `run_lint`；报告 `lint_out.strip() + "\n" + fid_out.strip()`；逐条 `tool_lines(报告)` | `run_lint_report`；报告由 `lint.text` 照同样拼法拼出；逐条 `checker_lines(…)` | 3 |
| `graph.check` → `state["report"]` → `plan_repair` | 补丁 `repair_request(structured, report)`；重写「你的输出未通过自动校验…」 | 不改（报告逐字不变） | — |
| `graph._record`、`_log_report`、`finalize` 的失败报告文件 | 报告原文（`_record` 脱敏） | 不改 | — |
| `convert.py` 整章终检 | `run_lint`；`log(lint_out.strip())`；`ConversionError.of("job.final_check_failed", lint_out + "\n" + fid_out, tool_lines(…))` | `run_lint_report`；日志与报告用 `lint.text`；逐条 `checker_lines(…)` | 3 |
| `convert.py` 合并失败 | `tool_lines(out)` | 不改 | — |
| 新增 `verification.lint_lines` / `checker_lines` / `_lint_msg` / `_lint_value` | — | 见 Task 2 | 2 |

### 测试替身（Task 3）

| 文件 | 行（改动前） | 改法 |
|---|---|---|
| `tests/pipeline/test_offline.py` | 344 | `orig_lint = convert_mod.validate.run_lint_report` |
| 同上 | 352、420、436 | `convert_mod.validate.run_lint_report = lambda p: convert_mod.validate.LintReport(True, "PASS（打桩）")` |
| 同上 | 410、429、451、695 | `convert_mod.validate.run_lint_report = orig_lint` |
| 同上 | 661–662 | `convert_mod.validate.run_lint_report = lambda p: convert_mod.validate.LintReport(`（第二行不变） |
| 同上 | 680 | `convert_mod.validate.run_lint_report = lambda p: convert_mod.validate.LintReport(False, long_report)` |
| 同上 | 1124 | 不改（真的 `run_lint`，覆盖率三处口径对照） |
| `tests/pipeline/test_graph.py` | 221、242、243、258 | `run_lint` → `run_lint_report`；第二次调用返回 `validate_mod.LintReport(False, "ERROR lint 失败一条")` |

### 显示处（前端）

| 显示处 | 文件 | 数据 | 处置 | Task |
|---|---|---|---|---|
| 转换失败区 | `components/JobPanel.tsx` | `job.error_msg`（`job.failed_report`，`report` 是 `lines`） | 不改代码；`formatMsg` 渲染嵌套的 `verify.lint.*` | 3（测试） |
| 后台任务页展开的失败全文 | `admin/JobsTab.tsx` | `itemError(j)` 整段 | 同一个 `formatMsg`，不改；由 `server-msg.test.ts` 的失败报告用例覆盖 | 2（测试） |
| 一行显示（提示条、助手任务卡、后台摘要） | `App.tsx`、`TaskCard.tsx`、`admin/JobsTab.tsx` | `failHead` 只取原因 | 不改 | — |
| 质量报告、验证面板、编辑卡、验证门 | — | 不经 lint | 不涉及 | — |

## 文件结构

| 文件 | 本计划的改动 |
|---|---|
| `backend/tests/pipeline/lint_snapshot.py`（新，Task 0） | 改动前的快照：lint 文本输出、`_check_batch` 报告、两种修复模式的回喂；23 条规则的改坏文档 `CASES`、`warn_case`、`feed_doc` |
| `backend/tests/pipeline/test_lint_feed_snapshot.py`（新，Task 0） | 只用旧接口核对快照；导出 `PARAMS`、`dump`、`lint_text` 供新测试复用 |
| `backend/tools/lint_storyboard.py` | `_item`、`main(path, as_json=False)`、`--json`、用法多一行 |
| `backend/pipeline/validate.py` | `LintReport`、`run_lint_report` |
| `backend/tests/pipeline/test_lint_json.py`（新，Task 1） | `--json` 的规则名、参数、`text` 一致性、WARN、`run_lint_report`、命令行 |
| `backend/server/messages.py`、`messages_codes.json` | `verify.report.lint`、`verify.report.lint_none`、23 条 `verify.lint.*` |
| `backend/pipeline/verification.py` | `_LINT_LIST_MAX`、`_lint_value`、`_lint_msg`、`lint_lines`、`checker_lines` |
| `backend/tests/pipeline/test_lint_msgs.py`（新，Task 2；Task 3 追加两节） | 逐条消息、登记对应、回落、脱敏、组合、流水线接入 |
| `frontend/src/i18n/zh.ts`、`en.ts` | `srv.verify.report.lint/lint_none`、`srv.verify.lint.*` |
| `frontend/tests/server-msg.test.ts` | lint 逐条中英渲染、不混语言、旧报告兼容 |
| `backend/pipeline/graph.py`、`convert.py` | 改用 `run_lint_report` 与 `checker_lines` |
| `backend/tests/pipeline/test_graph.py`、`test_offline.py` | 替身改名 |
| `frontend/tests/workspace.test.tsx` | JobPanel 失败区的 lint 逐条中英渲染 |

---

### Task 0: lint 文本输出与回喂模型的快照（只用旧接口，在任何改动之前单独提交）

后面的 Task 会改 `tools/lint_storyboard.py` 的汇报方式与流水线读 lint 的方式，而「回喂模型的文字一字不改」是本子计划的硬性要求。本 Task 只新增测试与快照数据，**不改任何产品代码**，在未改动的代码上先跑通、单独提交；之后每个 Task 的全套校验都包含它。

快照里的字面量与哈希是编写本计划时在仓库外的副本（HEAD `71f72a8`）上用现有代码跑出来的，两个文件原样运行打印 `ALL PASS`，不是手写推测。改坏文档的 23 种情形各自只触发它那一种 `ERROR`（WARN 可能顺带出现）。

**Files:**
- Create: `backend/tests/pipeline/lint_snapshot.py`（数据与造数据的函数，不导入 pipeline，供三个测试共用）
- Create: `backend/tests/pipeline/test_lint_feed_snapshot.py`

- [ ] **Step 1: 新建 `backend/tests/pipeline/lint_snapshot.py`**（完整内容）：

```python
"""子计划 5b 改动前的快照：lint 的文本输出与它回喂模型的文字（在未改动的代码上跑出来的，不是手写）。
只放数据与造数据的函数，不导入 pipeline；test_lint_feed_snapshot.py 用旧接口核对，test_lint_msgs.py 复用。"""
import copy
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
YAO = ROOT / "tests" / "real_text_yao"
_BASE = json.loads((YAO / "output_batch1.json").read_text(encoding="utf-8"))


def base() -> dict:
    """《药》批 1 归档：lint、结构校验、保真全过。"""
    return copy.deepcopy(_BASE)


def batch_text() -> str:
    text = (YAO / "input_batch1.txt").read_text(encoding="utf-8")
    m = re.search(r"^章节：.*$", text, flags=re.M)
    return text[m.end():] if m else text


def shot(d, i=0, ep=0):
    return d["episodes"][ep]["shots"][i]


def card(d, kind, cid):
    return next(x for x in d["assets"][kind] if x["id"] == cid)


def curve(d):
    return d["episodes"][0]["music"]["curve"]


# (规则, 改坏文档)：每条只触发它自己这一种 ERROR（WARN 可能顺带出现）
CASES = [
    ("schema", lambda d: shot(d).update(shot_size="huge")),
    ("ref_image_outfit", lambda d: card(d, "characters", "C01").update(
        reference_images=[{"view": "front", "uri": "c.png", "outfit": "summer"}])),
    ("ref_image_state", lambda d: card(d, "props", "P01").update(
        reference_images=[{"view": "close_up", "uri": "p.png", "state": "melted"}])),
    ("asset_empty_constraint", lambda d: card(d, "characters", "C01").update(constraints=["  "])),
    ("curve_shot", lambda d: curve(d)[0].update(from_shot="E09-SH001")),
    ("curve_unit", lambda d: curve(d)[0].update(unit_refs=["u9999"])),
    ("curve_reversed", lambda d: curve(d)[0].update(from_shot="E01-SH010", to_shot="E01-SH001")),
    ("shot_unit", lambda d: shot(d)["source"]["unit_refs"].append("u9999")),
    ("inferred_no_note", lambda d: shot(d)["source"].update(derivation="inferred")),
    ("beats_duration", lambda d: shot(d).update(
        beats=[{"duration_sec": 2, "action": "推门"}, {"duration_sec": 2.5, "action": "抬头"}])),
    ("beat_no_action", lambda d: shot(d).update(
        beats=[{"duration_sec": 2.5, "action": "推门"}, {"duration_sec": 2.5, "action": " "}])),
    ("shot_empty_constraint", lambda d: shot(d).update(constraints=[""])),
    ("location_ref", lambda d: shot(d).update(location_ref="S99")),
    ("prop_ref", lambda d: shot(d).update(prop_refs=[{"ref": "P99"}])),
    ("prop_state_required", lambda d: shot(d).update(prop_refs=[{"ref": "P01"}])),
    ("prop_state_unknown", lambda d: shot(d).update(prop_refs=[{"ref": "P01", "state": "melted"}])),
    ("prop_state_unexpected", lambda d: shot(d).update(prop_refs=[{"ref": "P02", "state": "melted"}])),
    ("creature_outfit", lambda d: (
        d["assets"].setdefault("creatures", []).append({"id": "A01", "name": "乌鸦", "visual_prompt": "黑羽乌鸦"}),
        shot(d).update(characters=[{"ref": "A01", "outfit": "default"}]))),
    ("character_ref", lambda d: shot(d).update(characters=[{"ref": "C99"}])),
    ("outfit_unknown", lambda d: shot(d).update(characters=[{"ref": "C01", "outfit": "summer"}])),
    ("dialogue_character", lambda d: shot(d, 3)["dialogue"][0].update(character_ref="C99")),
    ("narration_unit", lambda d: shot(d)["narration"]["unit_refs"].append("u9999")),
    ("coverage_unmapped", lambda d: d["source"]["units"].append(
        {"id": "u0068", "text": "多出一句。", "para": 29, "kind": "action"})),
]


def warn_case(d):
    """只有 WARN、没有 ERROR：曲线缝隙、曲线没到最后一镜、镜头 ID 前缀、两项覆盖声明。"""
    curve(d)[1].update(from_shot="E01-SH012")
    curve(d).pop()
    d["episodes"][1]["shots"][1]["id"] = "E01-SH099"
    d["coverage"].update(unmapped_units=["u0001"], inferred_shot_ratio=0.5)


def feed_doc() -> dict:
    """结构校验与保真全过、只有 lint 报错（资产引用五条）：_check_batch 走到 lint 那一支。"""
    d = base()
    shot(d, 0).update(location_ref="S99")
    shot(d, 6).update(prop_refs=[{"ref": "P99"}])
    shot(d, 1).update(characters=[{"ref": "C99"}])
    shot(d, 2).update(characters=[{"ref": "C01", "outfit": "summer"}])
    shot(d, 3)["dialogue"][0].update(character_ref="C99")
    return d


SUMMARY = "旁白模式 selective；镜头 61 个（inferred 2 个，占比 0.03）；句子 67 个，已覆盖 67 个（旁白 9，台词承载 17，纯画面承载 43）。"

# 每种情形：(退出码, 文本输出的 sha256, 其中的 ERROR/WARN 行)
LINT = {
    "schema": (1, "908556b8bc6c845645f155cf3c43275c33abfa5144a77f9e5a57bda86914436b", ["ERROR [schema] episodes/0/shots/0/shot_size: 'huge' is not one of ['extreme_wide', 'wide', 'full', 'medium', 'medium_close', 'close_up', 'extreme_close_up', 'insert']"]),
    "ref_image_outfit": (1, "190301140218c6a975c742e1d9b21588d85f87ea6ea0991b4b4666530a68f6a6", ["ERROR [C01] 参考图标注的 outfit 'summer' 不存在（可选: ['default']）"]),
    "ref_image_state": (1, "b6eed9d380d8a28575ef81a01656c6e890b2faf9eb06bd09a7818e1f0aa0fc23", ["ERROR [P01] 参考图标注的 state 'melted' 不存在（可选: ['charred', 'fresh_bleeding', 'lotus_wrapped', 'paper_wrapped', 'split_open']）"]),
    "asset_empty_constraint": (1, "39dc9589257dc7d3e9950d2349adc6f8032cc6c309414733e4d49f8bb04d7d89", ["ERROR [C01] constraints 里有空约束项"]),
    "curve_shot": (1, "f9582cf6404dc5cf05e265e55683b1ea342cd6ab51dbd9e8122fbdd924420a17", ["WARN  [E01] music.curve 段落不连续（E01-SH011 之前有缝隙或重叠）", "ERROR [E01] music.curve 引用不存在于本集的镜头: E09-SH001"]),
    "curve_unit": (1, "be51e313d61ddef12494c243a74591609560e5c56108612f4638dd38fda8a3f6", ["ERROR [E01] music.curve.unit_refs 引用不存在的句子: u9999"]),
    "curve_reversed": (1, "20d944df03c1ea3cf32f6cdf68ce56f85f95dbd22c9e91a60fac5c2f4026bb4f", ["WARN  [E01] music.curve 段落不连续（E01-SH010 之前有缝隙或重叠）", "WARN  [E01] music.curve 段落不连续（E01-SH011 之前有缝隙或重叠）", "ERROR [E01] music.curve 区间倒序: E01-SH010 > E01-SH001"]),
    "shot_unit": (1, "79db6b47967928f07e4ecc9991eafe191bb63905b03c86aa5ae903a27b8a8338", ["ERROR [E01-SH001] source.unit_refs 引用不存在的句子: u9999"]),
    "inferred_no_note": (1, "e77eb4a8c52aec1130ab767980de7970c21f61614bdfb2c3329f36ccf86fea91", ["WARN  [coverage] inferred_shot_ratio 声明 0.03，实际 0.05", "ERROR [E01-SH001] derivation=inferred 但缺少 inference_note"]),
    "beats_duration": (1, "f2735227f9ae180ef2c35f04e2f064200e9a3fa7b366c30a6021f4b75967905d", ["ERROR [E01-SH001] beats 各拍时长之和 4.5s 与镜头 duration_sec 5s 不符"]),
    "beat_no_action": (1, "2fcbf60ea860daf385bdd71aa7e9d22528aa59ace24b6a5d379e0acbdc4f37a6", ["ERROR [E01-SH001] beats 第 2 拍缺少 action"]),
    "shot_empty_constraint": (1, "9908bda092549650785072c696be442082901b521d541228697e12699bbfb764", ["ERROR [E01-SH001] constraints 里有空约束项"]),
    "location_ref": (1, "e7d12f8a4724cdaad5e211521c1e9fd07237779b01b7f7a8de77fa67479e4a2f", ["ERROR [E01-SH001] location_ref 引用不存在的场景: S99"]),
    "prop_ref": (1, "8e0b7915e670f751681d81cbbbd99d8ec5be8a1cc829524dc4b66ea14919e2a0", ["ERROR [E01-SH001] prop_refs 引用不存在的道具: P99"]),
    "prop_state_required": (1, "dd5a99981febac48c266e445188567a3c07cb34342295820f69319a084c6cab2", ["ERROR [E01-SH001] 道具 P01 有状态集，引用必须填 state（可选: ['charred', 'fresh_bleeding', 'lotus_wrapped', 'paper_wrapped', 'split_open']）"]),
    "prop_state_unknown": (1, "e6f7d866c0b1a6372161d2a8637d00a453584838e1664be0a34fc41a38687823", ["ERROR [E01-SH001] 道具 P01 不存在 state 'melted'（可选: ['charred', 'fresh_bleeding', 'lotus_wrapped', 'paper_wrapped', 'split_open']）"]),
    "prop_state_unexpected": (1, "f2dc1a1fd73452f31dfe7e715e398674ea87ae41330df9aa6edff415ac1be72b", ["ERROR [E01-SH001] 道具 P02 无 states，引用不应填 state"]),
    "creature_outfit": (1, "0a4af08bf35c73d6f0711e4d987526121bdf485e2282904a529c24f2853c34e5", ["ERROR [E01-SH001] 生物 A01 引用不应填 outfit"]),
    "character_ref": (1, "0228e9ad74f8dcc96203b9d08a8791dff1a2bd57e05903b4fd35e2adc1d25a06", ["ERROR [E01-SH001] characters.ref 引用不存在的角色/生物: C99"]),
    "outfit_unknown": (1, "5ef650854cac3007f76af51a82bfc442f2d28054e22bad369d6d646ce841aeaf", ["ERROR [E01-SH001] 角色 C01 不存在 outfit 'summer'（可选: ['default']）"]),
    "dialogue_character": (1, "d92abf510e67c6a7288791ac47437ca5607d978228d73179b888eebaa81a0939", ["ERROR [E01-SH004] dialogue.character_ref 引用不存在的角色: C99"]),
    "narration_unit": (1, "a6cc0bd9dc0f9fefa64e9315932aa3841e09fccfd785a24469b4125b4b66d12f", ["ERROR [E01-SH001] narration.unit_refs 引用不存在的句子: u9999"]),
    "coverage_unmapped": (1, "65b5faf124c0713738912feaa9072d38b94c48bb4856da49e896135f90da3786", ["WARN  [coverage] 声明的 unmapped_units 与实际不符，实际: ['u0068']", "ERROR [coverage] 以下句子未被任何镜头旁白覆盖且未标 skipped: ['u0068']"]),
    "_warnings": (0, "a7df3165bd5a8e9e2fc47d0cf84a4c05c947a01f834c9c18b016381f097957c7", ["WARN  [E01] music.curve 段落不连续（E01-SH012 之前有缝隙或重叠）", "WARN  [E01] music.curve 未覆盖到本集最后一镜", "WARN  [E01-SH099] 镜头 ID 前缀与所属集 E02 不一致", "WARN  [coverage] 声明的 unmapped_units 与实际不符，实际: []", "WARN  [coverage] inferred_shot_ratio 声明 0.5，实际 0.03"]),
}
PASS_TEXT = f"\n{SUMMARY}\nPASS\n"
NO_JSONSCHEMA_TEXT = f"WARN  jsonschema 未安装，跳过结构校验（pip install jsonschema）\n\n{SUMMARY}\nPASS\n"

# feed_doc() 走 _check_batch：lint 未过时的报告（回喂模型、失败报告、尝试记录都用它）
FEED_REPORT = ("ERROR [E01-SH001] location_ref 引用不存在的场景: S99\n"
               "ERROR [E01-SH002] characters.ref 引用不存在的角色/生物: C99\n"
               "ERROR [E01-SH003] 角色 C01 不存在 outfit 'summer'（可选: ['default']）\n"
               "ERROR [E01-SH004] dialogue.character_ref 引用不存在的角色: C99\n"
               "ERROR [E01-SH007] prop_refs 引用不存在的道具: P99\n"
               f"\n{SUMMARY}\nFAIL（5 个错误）\n"
               "PASS 原文保真：67 个 unit 拼接后与原文逐字一致（1958 字符）")
FEED_SHA = {
    "repair_request": "5c1f7b09b4fb3f96c4a59af9657fba131883f4b28f86dadb49d100f3b71382f5",   # 补丁修复的回喂（= repair_request(structured, FEED_REPORT)）
    "rewrite": "4016c8d6af01aaebcc27f5edc8a977b000f1d6fb5e0398c3566bd4b94697725c",          # 整份重写的回喂
    "batch_failed": "35ed3b4c5a73aded462018e75ab9fbe2fd8d98b716c568b20c68b8312ef4f0d0",     # 重写模式重试耗尽时 ConversionError.report
}
```

- [ ] **Step 2: 新建 `backend/tests/pipeline/test_lint_feed_snapshot.py`**（完整内容）：

```python
#!/usr/bin/env python3
"""lint 的文本输出与它回喂模型的文字不得改动（spec 子计划 5b D）：只用子计划 5b 之前就有的接口，逐字核对 lint_snapshot 里的快照。
本文件在子计划 5b 的任何改动之前单独提交并通过，之后每个 Task 都必须照样通过。不调模型、不联网。
用法: python3 tests/pipeline/test_lint_feed_snapshot.py"""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

_TMP = tempfile.TemporaryDirectory()
os.environ["STORYBOARD_DATA_DIR"] = _TMP.name           # 必须在导入 server.* / pipeline.* 之前
os.environ["ANTHROPIC_BASE_URL"] = "http://127.0.0.1:9"  # 保险：漏了桩也到不了真实模型服务
os.environ["ANTHROPIC_API_KEY"] = "sk-test-not-real"
import pipeline.config as _pc  # noqa: E402
_pc._load_dotenv = lambda *_a, **_k: None                # 不读真实的 backend/.env

import lint_snapshot as SNAP  # noqa: E402
from fakes import FakeChat  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402
from pipeline import graph, repair, validate  # noqa: E402
from pipeline.chat import ChatInvoker  # noqa: E402
from pipeline.config import Settings  # noqa: E402
from pipeline.convert import ConvertParams  # noqa: E402
from pipeline.errors import ConversionError  # noqa: E402

LINT = ROOT / "tools" / "lint_storyboard.py"
PARAMS = ConvertParams(
    work_title="药", chapter="全文（1919）", style_prefix="民国江南小镇写实风格，电影感光影，青灰冷色调",
    art_style="realistic", color_tone="青灰冷色调，晨昏低饱和", aspect_ratio="9:16", target_platform="抖音",
    narration_mode="selective", tts_voice="male_mature")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def dump(doc: dict, d: str) -> Path:
    p = Path(d) / "doc.json"
    p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return p


def lint_text(doc: dict):
    """命令行默认（文本）模式：返回 (退出码, stdout, stderr)。"""
    with tempfile.TemporaryDirectory() as d:
        r = subprocess.run([sys.executable, str(LINT), str(dump(doc, d))], capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def main() -> int:
    # 1. 命令行文本输出逐字不变：23 条错误规则各一种情形，加只有 WARN、全部通过两种
    cases = SNAP.CASES + [("_warnings", SNAP.warn_case)]
    for rule, mutate in cases:
        d = SNAP.base()
        mutate(d)
        rc, out, err = lint_text(d)
        want_rc, want_sha, want_lines = SNAP.LINT[rule]
        got_lines = [ln for ln in out.splitlines() if ln.startswith(("ERROR", "WARN"))]
        assert (rc, got_lines, err) == (want_rc, want_lines, ""), (rule, rc, got_lines, err)
        assert sha(out) == want_sha, (rule, out)
    assert len(SNAP.CASES) == 23
    rc, out, err = lint_text(SNAP.base())
    assert (rc, out, err) == (0, SNAP.PASS_TEXT, ""), out
    print("1. 命令行文本输出逐字不变（23 条错误规则、只有 WARN、全过） ✓")

    # 2. 进程内调用：jsonschema 缺失时的 WARN 与汇总
    spec = importlib.util.spec_from_file_location("lint_storyboard_snap", LINT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    saved = sys.modules.get("jsonschema")
    sys.modules["jsonschema"] = None          # import jsonschema 会抛 ImportError
    buf = io.StringIO()
    try:
        with tempfile.TemporaryDirectory() as d, contextlib.redirect_stdout(buf):
            rc = mod.main(str(dump(SNAP.base(), d)))
    finally:
        if saved is None:
            sys.modules.pop("jsonschema", None)
        else:
            sys.modules["jsonschema"] = saved
    assert (rc, buf.getvalue()) == (0, SNAP.NO_JSONSCHEMA_TEXT), buf.getvalue()
    print("2. jsonschema 缺失时的输出不变 ✓")

    # 3. validate.run_lint：退出码与「stdout + stderr」原样
    for rule in ("location_ref", "coverage_unmapped"):
        d = SNAP.base()
        dict(SNAP.CASES)[rule](d)
        with tempfile.TemporaryDirectory() as w:
            ok, out = validate.run_lint(dump(d, w))
        assert ok is False and sha(out) == SNAP.LINT[rule][1], (rule, out)
    with tempfile.TemporaryDirectory() as w:
        assert validate.run_lint(dump(SNAP.base(), w)) == (True, SNAP.PASS_TEXT)
    print("3. run_lint 的返回不变 ✓")

    # 4. _check_batch：结构校验过、lint 未过时的报告与补丁修复请求逐字不变
    with tempfile.TemporaryDirectory() as w:
        ok, hard, report, key, structured = graph._check_batch(
            SNAP.feed_doc(), SNAP.batch_text(), Settings(), Path(w), 1, 1, None, lambda _: None)
    assert (ok, hard, key, structured.ok) == (False, True, None, True)
    assert report == SNAP.FEED_REPORT, report
    assert sha(repair.repair_request(structured, report)) == SNAP.FEED_SHA["repair_request"]
    print("4. _check_batch 的 lint 报告与修复请求不变 ✓")

    # 5. 整张图：两种修复模式真正发给模型的回喂，与重试耗尽时的失败报告
    bad = json.dumps(SNAP.feed_doc(), ensure_ascii=False)
    no_call = AIMessage(content="不调工具", response_metadata={"stop_reason": "end_turn"})
    for mode, second in (("rewrite", bad), ("patch", no_call)):
        settings = Settings(api_key="k", max_retries=1, normalize_input=False,
                            freeze_source_units=False, repair_mode=mode)
        fake = FakeChat(responses=[bad, second])
        with tempfile.TemporaryDirectory() as w:
            chat = ChatInvoker(settings, chat=fake, log=lambda _: None)
            g = graph.build_batch_graph(chat=chat, review_chat=None, settings=settings, params=PARAMS,
                                        workdir=Path(w), attempt_records=[], log=lambda _: None)
            try:
                graph.run_batch(g, user="【小说原文】" + SNAP.batch_text(), batch_text=SNAP.batch_text(),
                                idx=1, frozen_units=None)
                raise AssertionError("lint 未过、重试耗尽应抛 ConversionError")
            except ConversionError as e:
                fed = fake.requests[1]["messages"][-1].content
                if mode == "rewrite":
                    assert sha(fed) == SNAP.FEED_SHA["rewrite"], fed
                    assert sha(e.report) == SNAP.FEED_SHA["batch_failed"], e.report
                    assert SNAP.FEED_REPORT in fed
                else:
                    assert sha(fed) == SNAP.FEED_SHA["repair_request"], fed
    print("5. 两种修复模式的回喂与失败报告不变 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: 在未改动的代码上运行**：`cd backend && .venv/bin/python tests/pipeline/test_lint_feed_snapshot.py`，预期：
  ```
  1. 命令行文本输出逐字不变（23 条错误规则、只有 WARN、全过） ✓
  2. jsonschema 缺失时的输出不变 ✓
  3. run_lint 的返回不变 ✓
  4. _check_batch 的 lint 报告与修复请求不变 ✓
  5. 两种修复模式的回喂与失败报告不变 ✓

  ALL PASS
  ```
  若哪一条对不上：不要改快照去迁就，先查是不是仓库与 `71f72a8` 有差异（`git diff 71f72a8 -- backend/tools backend/schema backend/pipeline backend/tests/real_text_yao`），有差异就停下报告。
- [ ] **Step 4: 跑全部校验**（全局约束里的整套）。
- [ ] **Step 5: 单独提交**：
  ```bash
  git add backend/tests/pipeline/lint_snapshot.py backend/tests/pipeline/test_lint_feed_snapshot.py
  git commit -m "子计划 5b 先行快照：钉住 lint 文本输出（23 条错误规则、只有 WARN、全过、缺 jsonschema）、run_lint 返回、_check_batch 的 lint 报告与两种修复模式真正发给模型的回喂，改动前在未改的代码上采集"
  ```

---

### Task 1: lint 加 `--json`，流水线侧加 `run_lint_report`（还不接入）

**Files:**
- Modify: `backend/tools/lint_storyboard.py`（整文件替换为下面的内容）
- Modify: `backend/pipeline/validate.py`
- Test: `backend/tests/pipeline/test_lint_json.py`（新）

- [ ] **Step 1: 写失败测试** `backend/tests/pipeline/test_lint_json.py`（完整内容）：

```python
#!/usr/bin/env python3
"""分镜检查（lint）的 --json 输出（spec 子计划 5b B、C）：每条错误的规则名与参数、同一次运行的 text 与文本模式逐字相同、
WARN 的规则名、validate.run_lint_report、命令行默认输出不变。回喂模型的原文见 test_lint_feed_snapshot.py。
不调模型、不联网。用法: python3 tests/pipeline/test_lint_json.py"""
import ast
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

_TMP = tempfile.TemporaryDirectory()
os.environ["STORYBOARD_DATA_DIR"] = _TMP.name           # 必须在导入 server.* / pipeline.* 之前
os.environ["ANTHROPIC_BASE_URL"] = "http://127.0.0.1:9"  # 保险：漏了桩也到不了真实模型服务
os.environ["ANTHROPIC_API_KEY"] = "sk-test-not-real"
import pipeline.config as _pc  # noqa: E402
_pc._load_dotenv = lambda *_a, **_k: None                # 不读真实的 backend/.env

import lint_snapshot as SNAP  # noqa: E402
from pipeline import validate  # noqa: E402
from test_lint_feed_snapshot import dump, lint_text  # noqa: E402

LINT = ROOT / "tools" / "lint_storyboard.py"
OPTS_P01 = ["charred", "fresh_bleeding", "lotus_wrapped", "paper_wrapped", "split_open"]

# 每条错误规则 --json 给的 params（与 lint_snapshot.CASES 一一对应）
EXPECT_PARAMS = {
    "schema": {"path": "/episodes/0/shots/0/shot_size",
               "detail": "'huge' is not one of ['extreme_wide', 'wide', 'full', 'medium', 'medium_close', 'close_up', 'extreme_close_up', 'insert']"},
    "ref_image_outfit": {"card": "C01", "outfit": "summer", "options": ["default"]},
    "ref_image_state": {"card": "P01", "state": "melted", "options": OPTS_P01},
    "asset_empty_constraint": {"card": "C01"},
    "curve_shot": {"episode": "E01", "shot": "E09-SH001"},
    "curve_unit": {"episode": "E01", "unit": "u9999"},
    "curve_reversed": {"episode": "E01", "start": "E01-SH010", "end": "E01-SH001"},
    "shot_unit": {"shot": "E01-SH001", "unit": "u9999"},
    "inferred_no_note": {"shot": "E01-SH001"},
    "beats_duration": {"shot": "E01-SH001", "total": "4.5", "duration": "5"},
    "beat_no_action": {"shot": "E01-SH001", "beat": 2},
    "shot_empty_constraint": {"shot": "E01-SH001"},
    "location_ref": {"shot": "E01-SH001", "location": "S99"},
    "prop_ref": {"shot": "E01-SH001", "prop": "P99"},
    "prop_state_required": {"shot": "E01-SH001", "prop": "P01", "options": OPTS_P01},
    "prop_state_unknown": {"shot": "E01-SH001", "prop": "P01", "state": "melted", "options": OPTS_P01},
    "prop_state_unexpected": {"shot": "E01-SH001", "prop": "P02"},
    "creature_outfit": {"shot": "E01-SH001", "creature": "A01"},
    "character_ref": {"shot": "E01-SH001", "character": "C99"},
    "outfit_unknown": {"shot": "E01-SH001", "character": "C01", "outfit": "summer", "options": ["default"]},
    "dialogue_character": {"shot": "E01-SH004", "character": "C99"},
    "narration_unit": {"shot": "E01-SH001", "unit": "u9999"},
    "coverage_unmapped": {"n": 1, "units": ["u0068"]},
}
WARN_RULES = ["curve_gap", "curve_incomplete", "shot_id_prefix", "coverage_declared_units", "coverage_declared_ratio"]


def lint_json(doc: dict):
    """--json 模式：返回 (退出码, 解析后的 JSON, stderr)。"""
    with tempfile.TemporaryDirectory() as d:
        r = subprocess.run([sys.executable, str(LINT), "--json", str(dump(doc, d))], capture_output=True, text=True)
    return r.returncode, json.loads(r.stdout), r.stderr


def source_rules() -> dict:
    """源码里 errors.append / warnings.append 的规则名；每处都必须是 _item("规则名", …)。"""
    out = {"errors": [], "warnings": []}
    for node in ast.walk(ast.parse(LINT.read_text(encoding="utf-8"))):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "append"
                and isinstance(node.func.value, ast.Name) and node.func.value.id in out):
            arg = node.args[0]
            ok = (isinstance(arg, ast.Call) and getattr(arg.func, "id", "") == "_item"
                  and isinstance(arg.args[0], ast.Constant))
            assert ok, f"{node.func.value.id}.append 第 {node.lineno} 行没有用 _item(规则名, …)"
            out[node.func.value.id].append(arg.args[0].value)
    return out


def main() -> int:
    # 1. 23 条错误规则各一条触发用例：规则名、参数、原文；同一次运行的 text 与文本模式逐字相同
    assert [r for r, _ in SNAP.CASES] == list(EXPECT_PARAMS)
    for rule, mutate in SNAP.CASES:
        d = SNAP.base()
        mutate(d)
        rc, data, err = lint_json(d)
        want_rc, _sha, want_lines = SNAP.LINT[rule]
        assert (rc, err, data["version"], data["ok"]) == (want_rc, "", 1, False), (rule, rc, err)
        assert data["text"] == lint_text(d)[1], f"{rule}：--json 的 text 必须与文本模式逐字相同"
        assert [e["rule"] for e in data["errors"]] == [rule], (rule, data["errors"])
        e = data["errors"][0]
        assert e["params"] == EXPECT_PARAMS[rule], (rule, e["params"])
        assert "ERROR " + e["text"] in want_lines, (rule, e["text"])
        assert [w["text"] for w in data["warnings"]] == [ln[len("WARN  "):] for ln in want_lines if ln.startswith("WARN")]
    print("1. 23 条规则：规则名、参数、原文；text 与文本模式一致 ✓")

    # 2. 源码里 23 处 errors.append、6 处 warnings.append 都带规则名，错误规则与本文件的期望一一对应
    rules = source_rules()
    assert len(rules["errors"]) == 23 and sorted(rules["errors"]) == sorted(EXPECT_PARAMS), rules["errors"]
    assert sorted(rules["warnings"]) == sorted(WARN_RULES + ["schema_unavailable"]), rules["warnings"]
    print("2. 源码每处 append 都有规则名 ✓")

    # 3. WARN：带规则名；只有 WARN 时 ok 为真、errors 为空；jsonschema 缺失也有规则名
    d = SNAP.base()
    SNAP.warn_case(d)
    rc, data, _ = lint_json(d)
    assert (rc, data["ok"], data["errors"]) == (0, True, [])
    assert [w["rule"] for w in data["warnings"]] == WARN_RULES and data["text"] == lint_text(d)[1]
    spec = importlib.util.spec_from_file_location("lint_storyboard_json", LINT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    saved = sys.modules.get("jsonschema")
    sys.modules["jsonschema"] = None
    buf = io.StringIO()
    try:
        with tempfile.TemporaryDirectory() as w, contextlib.redirect_stdout(buf):
            assert mod.main(str(dump(SNAP.base(), w)), as_json=True) == 0
    finally:
        if saved is None:
            sys.modules.pop("jsonschema", None)
        else:
            sys.modules["jsonschema"] = saved
    data = json.loads(buf.getvalue())
    assert [w["rule"] for w in data["warnings"]] == ["schema_unavailable"] and data["text"] == SNAP.NO_JSONSCHEMA_TEXT
    assert buf.getvalue().isascii(), "--json 只输出 ASCII"
    print("3. WARN 的规则名 ✓")

    # 4. run_lint_report：text 与 run_lint 逐字相同；输出认不出时 errors 为 None，原样退回 stdout + stderr
    for rule in ("location_ref", "coverage_unmapped"):
        d = SNAP.base()
        dict(SNAP.CASES)[rule](d)
        with tempfile.TemporaryDirectory() as w:
            p = dump(d, w)
            r = validate.run_lint_report(p)
            assert (r.ok, r.text) == validate.run_lint(p) and [e["rule"] for e in r.errors] == [rule]
    with tempfile.TemporaryDirectory() as w:
        r = validate.run_lint_report(dump(SNAP.base(), w))
        assert r == validate.LintReport(True, SNAP.PASS_TEXT, [])
        bad = Path(w) / "bad.json"
        bad.write_text("{不是 JSON", encoding="utf-8")
        r = validate.run_lint_report(bad)
        assert r.ok is False and r.errors is None and (r.ok, r.text) == validate.run_lint(bad) and "Traceback" in r.text
    real_run = validate.subprocess.run

    class _Proc:
        returncode, stdout, stderr = 1, '{"errors": []}', "E"
    try:
        validate.subprocess.run = lambda *a, **k: _Proc()
        assert validate.run_lint_report(Path("x")) == validate.LintReport(False, '{"errors": []}E', None), "缺 text 时退回原文"
    finally:
        validate.subprocess.run = real_run
    print("4. run_lint_report 与 run_lint 一致、认不出时退回原文 ✓")

    # 5. 命令行：默认文本输出不带 JSON；参数不对时打印用法、退出码 2
    rc, out, _ = lint_text(SNAP.base())
    assert (rc, out) == (0, SNAP.PASS_TEXT)
    r = subprocess.run([sys.executable, str(LINT)], capture_output=True, text=True)
    assert r.returncode == 2 and "--json" in r.stdout
    r = subprocess.run([sys.executable, str(LINT), "--json"], capture_output=True, text=True)
    assert r.returncode == 2
    print("5. 命令行默认文本输出与用法 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 运行确认失败**：`cd backend && .venv/bin/python tests/pipeline/test_lint_json.py`，在第 1 节 `json.loads(r.stdout)` 处失败（现在的 lint 不认 `--json`：两个参数时打印用法、退出码 2，stdout 不是 JSON）。
- [ ] **Step 3: 实现 lint**：`backend/tools/lint_storyboard.py` 整文件替换为下面的内容。与原文件相比：
  - 每处 `errors.append(f"…")` / `warnings.append(f"…")` 改成 `…append(_item("规则名", f"…", 参数=…))`，**f-string 一字不改**（逐处对照调用点清单）；
  - 汇报段由逐行 `print` 改成先拼 `rows`、`text = "".join(r + "\n" for r in rows)`，默认 `sys.stdout.write(text)`，`--json` 时 `print(json.dumps({...,"text": text}, ensure_ascii=True, default=str))`；
  - `main(path, as_json=False)`；入口认 `--json`（位置不限）；`__doc__` 用法多一行。

```python
#!/usr/bin/env python3
"""NovelStoryboard v0.4 / v0.5 校验器。

用法: python3 tools/lint_storyboard.py <storyboard.json>
      python3 tools/lint_storyboard.py --json <storyboard.json>   （机器读：每条错误带规则名与参数）

两层检查:
  1. JSON Schema 结构校验（需要 pip install jsonschema，未安装则跳过并提示）
  2. 跨引用与忠实性检查（schema 表达不了的部分）:
     - 镜头引用的 unit / 角色 / 场景 / 道具 / outfit 必须真实存在
     - 镜头分了 beats，各拍时长之和必须等于镜头时长
     - inferred 镜头必须有 inference_note
     - 旁白覆盖率: 每个非 skipped 的 unit 必须被至少一个镜头的 narration 引用
     - coverage 字段与实际计算结果一致
"""
import json
import re
import sys
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema" / "storyboard.schema.json"


def _item(rule: str, text: str, **params) -> dict:
    """一条错误或警告。text 是文本模式打印的原文（转换流水线拿它回喂修复模型，一字不改）；
    rule 与 params 只给 --json 的读者（界面按规则翻译，见 spec 子计划 5b）。"""
    return {"rule": rule, "params": params, "text": text}


def main(path: str, as_json: bool = False) -> int:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    errors, warnings = [], []

    # ---- 1. JSON Schema 校验 ----
    try:
        import jsonschema
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema)
        for e in validator.iter_errors(doc):
            errors.append(_item("schema", f"[schema] {'/'.join(map(str, e.absolute_path))}: {e.message}",
                                path="/" + "/".join(map(str, e.absolute_path)), detail=e.message))
    except ImportError:
        warnings.append(_item("schema_unavailable", "jsonschema 未安装，跳过结构校验（pip install jsonschema）"))

    # ---- 2. 跨引用检查 ----
    units = {u["id"]: u for u in doc.get("source", {}).get("units", [])}
    chars = {c["id"]: c for c in doc.get("assets", {}).get("characters", [])}
    locs = {s["id"] for s in doc.get("assets", {}).get("locations", [])}
    props = {p["id"]: p for p in doc.get("assets", {}).get("props", [])}
    creatures = {a["id"] for a in doc.get("assets", {}).get("creatures", [])}

    # 设定图是「画师修正稿反过来约束后续每一帧」这条链的锚点，指错变体等于垫错衣服。
    # 这类引用 schema 表达不了（要跨到同一张卡的 outfits/states 里查），只能在这儿查。
    for card in chars.values():
        outfit_ids = {o["id"] for o in card.get("outfits", [])}
        for img in card.get("reference_images", []):
            tag = img.get("outfit")
            if tag and tag not in outfit_ids:
                errors.append(_item(
                    "ref_image_outfit",
                    f"[{card['id']}] 参考图标注的 outfit '{tag}' 不存在"
                    f"（可选: {sorted(outfit_ids) or '本卡无 outfits'}）",
                    card=card["id"], outfit=tag, options=sorted(outfit_ids)))
    for card in props.values():
        state_ids = {s["id"] for s in card.get("states", [])}
        for img in card.get("reference_images", []):
            tag = img.get("state")
            if tag and tag not in state_ids:
                errors.append(_item(
                    "ref_image_state",
                    f"[{card['id']}] 参考图标注的 state '{tag}' 不存在"
                    f"（可选: {sorted(state_ids) or '本卡无 states'}）",
                    card=card["id"], state=tag, options=sorted(state_ids)))

    for kind in ("characters", "locations", "props", "creatures"):
        for card in doc.get("assets", {}).get(kind, []):
            for c in card.get("constraints", []):
                if not (c or "").strip():
                    errors.append(_item("asset_empty_constraint", f"[{card.get('id')}] constraints 里有空约束项",
                                        card=card.get("id")))

    narrated_units = set()
    dialogue_covered = set()  # dialogue 类句子可由角色台词承载，无需旁白重读
    visual_covered = set()    # 出现在镜头 source.unit_refs 中即画面承载（selective/none 模式计入覆盖）
    narration_mode = doc.get("meta", {}).get("narration", {}).get("mode", "original_text")
    total_shots = inferred_shots = 0

    for ep in doc.get("episodes", []):
        # music 情绪曲线检查
        music = ep.get("music")
        if music:
            shot_ids = [s.get("id") for s in ep.get("shots", [])]
            pos = {sid: i for i, sid in enumerate(shot_ids)}
            prev_end = -1
            for seg in music.get("curve", []):
                f, t = seg.get("from_shot"), seg.get("to_shot")
                for ref in (f, t):
                    if ref not in pos:
                        errors.append(_item("curve_shot", f"[{ep.get('id')}] music.curve 引用不存在于本集的镜头: {ref}",
                                            episode=ep.get("id"), shot=ref))
                for ref in seg.get("unit_refs", []):
                    if ref not in units:
                        errors.append(_item("curve_unit", f"[{ep.get('id')}] music.curve.unit_refs 引用不存在的句子: {ref}",
                                            episode=ep.get("id"), unit=ref))
                if f in pos and t in pos:
                    if pos[f] > pos[t]:
                        errors.append(_item("curve_reversed", f"[{ep.get('id')}] music.curve 区间倒序: {f} > {t}",
                                            episode=ep.get("id"), start=f, end=t))
                    if pos[f] != prev_end + 1:
                        warnings.append(_item("curve_gap", f"[{ep.get('id')}] music.curve 段落不连续（{f} 之前有缝隙或重叠）",
                                              episode=ep.get("id"), shot=f))
                    prev_end = pos[t]
            if music.get("curve") and prev_end != len(shot_ids) - 1:
                warnings.append(_item("curve_incomplete", f"[{ep.get('id')}] music.curve 未覆盖到本集最后一镜",
                                      episode=ep.get("id")))

        for shot in ep.get("shots", []):
            sid = shot.get("id", "?")
            total_shots += 1

            if not shot.get("id", "").startswith(f"{ep.get('id', '')}-"):
                warnings.append(_item("shot_id_prefix", f"[{sid}] 镜头 ID 前缀与所属集 {ep.get('id')} 不一致",
                                      shot=sid, episode=ep.get("id")))

            src = shot.get("source", {})
            for ref in src.get("unit_refs", []):
                if ref not in units:
                    errors.append(_item("shot_unit", f"[{sid}] source.unit_refs 引用不存在的句子: {ref}",
                                        shot=sid, unit=ref))
                else:
                    visual_covered.add(ref)
            if src.get("derivation") == "inferred" and not src.get("inference_note"):
                errors.append(_item("inferred_no_note", f"[{sid}] derivation=inferred 但缺少 inference_note", shot=sid))
            if src.get("derivation") == "inferred":
                inferred_shots += 1

            # v0.5 镜头内阶段：分了拍，时长就必须对得上，否则下游按哪个走全凭猜
            beats = shot.get("beats")
            if beats is not None:
                total = sum(b.get("duration_sec") or 0 for b in beats)
                dur = shot.get("duration_sec") or 0
                if abs(total - dur) > 0.05:
                    errors.append(_item(
                        "beats_duration",
                        f"[{sid}] beats 各拍时长之和 {total:g}s 与镜头 duration_sec {dur:g}s 不符",
                        shot=sid, total=f"{total:g}", duration=f"{dur:g}"))
                for i, b in enumerate(beats, 1):
                    if not (b.get("action") or "").strip():
                        errors.append(_item("beat_no_action", f"[{sid}] beats 第 {i} 拍缺少 action", shot=sid, beat=i))

            for c in shot.get("constraints", []):
                if not (c or "").strip():
                    errors.append(_item("shot_empty_constraint", f"[{sid}] constraints 里有空约束项", shot=sid))

            loc = shot.get("location_ref")
            if loc and loc not in locs:
                errors.append(_item("location_ref", f"[{sid}] location_ref 引用不存在的场景: {loc}",
                                    shot=sid, location=loc))

            for pr in shot.get("prop_refs", []):
                ref = pr.get("ref") if isinstance(pr, dict) else pr
                if ref not in props:
                    errors.append(_item("prop_ref", f"[{sid}] prop_refs 引用不存在的道具: {ref}", shot=sid, prop=ref))
                    continue
                state = pr.get("state") if isinstance(pr, dict) else None
                state_ids = {s["id"] for s in props[ref].get("states", [])}
                if state_ids and not state:
                    errors.append(_item("prop_state_required",
                                        f"[{sid}] 道具 {ref} 有状态集，引用必须填 state（可选: {sorted(state_ids)}）",
                                        shot=sid, prop=ref, options=sorted(state_ids)))
                elif state_ids and state not in state_ids:
                    errors.append(_item("prop_state_unknown",
                                        f"[{sid}] 道具 {ref} 不存在 state '{state}'（可选: {sorted(state_ids)}）",
                                        shot=sid, prop=ref, state=state, options=sorted(state_ids)))
                elif not state_ids and state:
                    errors.append(_item("prop_state_unexpected", f"[{sid}] 道具 {ref} 无 states，引用不应填 state",
                                        shot=sid, prop=ref))

            for ch in shot.get("characters", []):
                ref = ch.get("ref")
                if ref in creatures:
                    if ch.get("outfit"):
                        errors.append(_item("creature_outfit", f"[{sid}] 生物 {ref} 引用不应填 outfit",
                                            shot=sid, creature=ref))
                    continue
                if ref not in chars:
                    errors.append(_item("character_ref", f"[{sid}] characters.ref 引用不存在的角色/生物: {ref}",
                                        shot=sid, character=ref))
                    continue
                outfit = ch.get("outfit", "default")
                outfit_ids = {o["id"] for o in chars[ref].get("outfits", [])}
                if outfit_ids and outfit not in outfit_ids:
                    errors.append(_item("outfit_unknown",
                                        f"[{sid}] 角色 {ref} 不存在 outfit '{outfit}'（可选: {sorted(outfit_ids)}）",
                                        shot=sid, character=ref, outfit=outfit, options=sorted(outfit_ids)))

            for d in shot.get("dialogue", []):
                cref = d.get("character_ref")
                if cref and cref not in chars:
                    errors.append(_item("dialogue_character", f"[{sid}] dialogue.character_ref 引用不存在的角色: {cref}",
                                        shot=sid, character=cref))

            narr = shot.get("narration", {})
            for ref in narr.get("unit_refs", []):
                if ref not in units:
                    errors.append(_item("narration_unit", f"[{sid}] narration.unit_refs 引用不存在的句子: {ref}",
                                        shot=sid, unit=ref))
                narrated_units.add(ref)

            if any(d.get("verbatim", True) for d in shot.get("dialogue", [])):
                for ref in src.get("unit_refs", []):
                    if units.get(ref, {}).get("kind") == "dialogue":
                        dialogue_covered.add(ref)

    # ---- 3. 覆盖率（口径随旁白模式）----
    # original_text: 每句必须被旁白朗读或台词承载（逐句朗读形态）
    # selective/condensed/none: 画面承载（source.unit_refs）同样算覆盖
    covered = narrated_units | dialogue_covered
    if narration_mode != "original_text":
        covered |= visual_covered
    unmapped = [uid for uid, u in units.items()
                if not u.get("skipped") and uid not in covered]
    if unmapped:
        errors.append(_item("coverage_unmapped", f"[coverage] 以下句子未被任何镜头旁白覆盖且未标 skipped: {unmapped}",
                            n=len(unmapped), units=unmapped))

    declared = doc.get("coverage", {})
    if declared:
        if sorted(declared.get("unmapped_units", [])) != sorted(unmapped):
            warnings.append(_item("coverage_declared_units", f"[coverage] 声明的 unmapped_units 与实际不符，实际: {unmapped}",
                                  actual=unmapped))
        if total_shots:
            actual_ratio = round(inferred_shots / total_shots, 2)
            if abs(declared.get("inferred_shot_ratio", 0) - actual_ratio) > 0.011:
                warnings.append(_item(
                    "coverage_declared_ratio",
                    f"[coverage] inferred_shot_ratio 声明 {declared.get('inferred_shot_ratio')}，实际 {actual_ratio}",
                    declared=declared.get("inferred_shot_ratio"), actual=actual_ratio))

    # ---- 汇报 ----
    # 文本与改造前逐行 print 的结果逐字相同；--json 把同一段文本放进 text 字段，
    # 转换流水线用它回喂修复模型，两种模式回喂的内容不会分叉（spec 子计划 5b D）
    rows = [f"WARN  {w['text']}" for w in warnings] + [f"ERROR {e['text']}" for e in errors]
    ratio = round(inferred_shots / total_shots, 2) if total_shots else 0
    visual_only = (visual_covered - narrated_units - dialogue_covered) & set(units)
    rows.append(f"\n旁白模式 {narration_mode}；镜头 {total_shots} 个（inferred {inferred_shots} 个，占比 {ratio}）；"
                f"句子 {len(units)} 个，已覆盖 {len(covered & set(units))} 个"
                f"（旁白 {len(narrated_units & set(units))}，台词承载 {len(dialogue_covered)}，纯画面承载 {len(visual_only)}）。")
    rows.append("PASS" if not errors else f"FAIL（{len(errors)} 个错误）")
    text = "".join(r + "\n" for r in rows)
    if as_json:
        # 只用 ASCII：不受子进程控制台编码影响；default=str 兜住模型写进编号里的怪值
        print(json.dumps({"version": 1, "ok": not errors, "errors": errors, "warnings": warnings, "text": text},
                         ensure_ascii=True, default=str))
    else:
        sys.stdout.write(text)
    return 0 if not errors else 1


if __name__ == "__main__":
    args = sys.argv[1:]
    as_json = "--json" in args
    paths = [a for a in args if a != "--json"]
    if len(paths) != 1:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(paths[0], as_json=as_json))
```

- [ ] **Step 4: 实现 `run_lint_report`**：`backend/pipeline/validate.py`
  - 导入改为：
    ```python
    import json
    import subprocess
    import sys
    from dataclasses import dataclass
    from pathlib import Path
    from typing import List, Optional, Tuple
    ```
  - 在 `run_lint` 之后、`run_fidelity` 之前插入（`run_lint` 本身不改）：

```python
@dataclass
class LintReport:
    """lint 一次 --json 运行的结果（spec 子计划 5b C、D）。
    text：与文本模式的「stdout + stderr」逐字相同，回喂模型、日志、失败报告只用它；
    errors：逐条错误 {rule, params, text}，只给界面翻译；拿不到结构化输出（崩溃、输出认不出）时为 None。"""
    ok: bool
    text: str
    errors: Optional[list] = None


def run_lint_report(json_path: Path) -> LintReport:
    proc = subprocess.run([sys.executable, str(_TOOLS / "lint_storyboard.py"), "--json", str(json_path)],
                          capture_output=True, text=True)
    ok = proc.returncode == 0
    try:
        data = json.loads(proc.stdout)
        text, errors = data["text"], data["errors"]
        if not isinstance(text, str) or not isinstance(errors, list):
            raise TypeError
    except (ValueError, KeyError, TypeError):
        # 没有 JSON（崩溃时 stdout 为空、只有 stderr 的回溯）：与文本模式一样原样拼起来
        return LintReport(ok, proc.stdout + proc.stderr)
    return LintReport(ok, text + proc.stderr, errors)
```

- [ ] **Step 5: 运行确认通过**：
  - `cd backend && .venv/bin/python tests/pipeline/test_lint_json.py`，预期 5 节各打一个 ✓，最后 `ALL PASS`；
  - `.venv/bin/python tests/pipeline/test_lint_feed_snapshot.py` 仍 `ALL PASS`（文本输出逐字不变）；
  - 人工核对：`git diff backend/tools/lint_storyboard.py | grep '^-' | grep -v '^---' | grep 'f"'` 列出的每一行被删的 f-string，都能在 `^+` 行里原样找到。
- [ ] **Step 6: 跑全部校验并提交**：
  ```bash
  git add backend/tools/lint_storyboard.py backend/pipeline/validate.py backend/tests/pipeline/test_lint_json.py
  git commit -m "lint 加 --json：每条错误与警告带规则名和结构化参数，同一次运行给出与文本模式逐字相同的 text；流水线侧新增 run_lint_report 读它，暂不接入；默认文本输出不变"
  ```

---

### Task 2: 登记 `verify.lint.*`，结构化错误转成逐条消息（还不接入）

**Files:**
- Modify: `backend/server/messages.py`、`backend/server/messages_codes.json`（生成）
- Modify: `backend/pipeline/verification.py`
- Modify: `frontend/src/i18n/zh.ts`、`frontend/src/i18n/en.ts`
- Test: `backend/tests/pipeline/test_lint_msgs.py`（新）、`frontend/tests/server-msg.test.ts`

- [ ] **Step 1: 写失败测试** `backend/tests/pipeline/test_lint_msgs.py`（完整内容；Task 3 再追加两节）：

```python
#!/usr/bin/env python3
"""分镜检查（lint）逐条（spec 子计划 5b B、C、E）：verify.lint.* 的代码与中文兜底、源码与登记一一对应、
认不出时退回原文、先脱敏再截断、与保真输出的组合、流水线接入。回喂模型的原文见 test_lint_feed_snapshot.py。
不调模型、不联网。用法: python3 tests/pipeline/test_lint_msgs.py"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

_TMP = tempfile.TemporaryDirectory()
os.environ["STORYBOARD_DATA_DIR"] = _TMP.name           # 必须在导入 server.* / pipeline.* 之前
os.environ["ANTHROPIC_BASE_URL"] = "http://127.0.0.1:9"  # 保险：漏了桩也到不了真实模型服务
os.environ["ANTHROPIC_API_KEY"] = "sk-test-not-real"
import pipeline.config as _pc  # noqa: E402
_pc._load_dotenv = lambda *_a, **_k: None                # 不读真实的 backend/.env

import lint_snapshot as SNAP  # noqa: E402
from pipeline import verification as V  # noqa: E402
from server import messages as M  # noqa: E402
from test_lint_json import EXPECT_PARAMS, lint_json, source_rules  # noqa: E402

ZH_P01 = "charred、fresh_bleeding、lotus_wrapped、paper_wrapped、split_open"
# 每条规则逐条消息（verify.report.tool_error 套 verify.lint.<rule>）的中文兜底
EXPECT_ZH = {
    "schema": "  不符合分镜结构定义（/episodes/0/shots/0/shot_size）：'huge' is not one of ['extreme_wide', 'wide', 'full', 'medium', 'medium_close', 'close_up', 'extreme_close_up', 'insert']",
    "ref_image_outfit": "  [C01] 参考图标注的 outfit「summer」不存在（可选：default）",
    "ref_image_state": f"  [P01] 参考图标注的 state「melted」不存在（可选：{ZH_P01}）",
    "asset_empty_constraint": "  [C01] constraints 里有空的约束项",
    "curve_shot": "  [E01] music.curve 引用了本集没有的镜头：E09-SH001",
    "curve_unit": "  [E01] music.curve.unit_refs 引用了不存在的句子：u9999",
    "curve_reversed": "  [E01] music.curve 区间倒序：E01-SH010 在 E01-SH001 之后",
    "shot_unit": "  [E01-SH001] source.unit_refs 引用了不存在的句子：u9999",
    "inferred_no_note": "  [E01-SH001] derivation=inferred 但缺少 inference_note",
    "beats_duration": "  [E01-SH001] beats 各拍时长之和 4.5s 与镜头 duration_sec 5s 不符",
    "beat_no_action": "  [E01-SH001] beats 第 2 拍缺少 action",
    "shot_empty_constraint": "  [E01-SH001] constraints 里有空的约束项",
    "location_ref": "  [E01-SH001] location_ref 引用了不存在的场景：S99",
    "prop_ref": "  [E01-SH001] prop_refs 引用了不存在的道具：P99",
    "prop_state_required": f"  [E01-SH001] 道具 P01 有状态集，引用时必须填 state（可选：{ZH_P01}）",
    "prop_state_unknown": f"  [E01-SH001] 道具 P01 没有 state「melted」（可选：{ZH_P01}）",
    "prop_state_unexpected": "  [E01-SH001] 道具 P02 没有状态集，引用时不应填 state",
    "creature_outfit": "  [E01-SH001] 生物 A01 的引用不应填 outfit",
    "character_ref": "  [E01-SH001] characters.ref 引用了不存在的角色或生物：C99",
    "outfit_unknown": "  [E01-SH001] 角色 C01 没有 outfit「summer」（可选：default）",
    "dialogue_character": "  [E01-SH004] dialogue.character_ref 引用了不存在的角色：C99",
    "narration_unit": "  [E01-SH001] narration.unit_refs 引用了不存在的句子：u9999",
    "coverage_unmapped": "  [coverage] 有 1 句原文没有被任何镜头的旁白覆盖，也没有标 skipped：u0068",
}
FAKE = "ark-" + "Q7v2" * 6                     # 假密钥（不是任何真实密钥）
ERRS = [{"rule": "location_ref", "params": {"shot": "E01-SH001", "location": "S99"}, "text": "t"}]


def zh(line: dict) -> str:
    return M.render_zh(line["code"], line["params"])


def main() -> int:
    # 1. 23 条规则各一条触发用例：逐条消息的代码与中文兜底；jsonschema 原文作厂商原文
    assert list(EXPECT_ZH) == list(EXPECT_PARAMS)
    for rule, mutate in SNAP.CASES:
        d = SNAP.base()
        mutate(d)
        _, data, _ = lint_json(d)
        lines = V.lint_lines(data["errors"])
        assert lines[0] == {"code": "verify.report.lint", "params": {}}
        assert lines[1]["code"] == "verify.report.tool_error" and lines[1]["params"]["text"]["code"] == f"verify.lint.{rule}"
        assert zh(lines[1]) == EXPECT_ZH[rule], (rule, zh(lines[1]))
    sch = V.lint_lines([{"rule": "schema", "params": EXPECT_PARAMS["schema"], "text": "x"}])[1]["params"]["text"]["params"]
    assert sch["detail"] == {"t": "vendor", "text": EXPECT_PARAMS["schema"]["detail"]}, "jsonschema 原文作厂商原文"
    print("1. 23 条规则的逐条消息与中文兜底 ✓")

    # 2. 源码里的错误规则名 ↔ 登记的 verify.lint.* 一一对应；WARN 不登记
    rules = source_rules()
    registered = sorted(c[len("verify.lint."):] for c in M._REG if c.startswith("verify.lint."))
    assert sorted(rules["errors"]) == registered and len(registered) == 23, (rules["errors"], registered)
    assert not set(rules["warnings"]) & set(registered)
    print("2. 源码规则名 ↔ 登记一一对应 ✓")

    # 3. WARN 不进给用户的逐条：lint 通过、保真通过时没有逐条
    d = SNAP.base()
    SNAP.warn_case(d)
    _, data, _ = lint_json(d)
    assert data["warnings"] and V.checker_lines(True, data["text"], data["errors"], True, "PASS") == []
    print("3. WARN 不进逐条 ✓")

    # 4. 认不出的一条：没登记的规则、参数对不上、形状不对，都退回该条原文（厂商原文）
    for item in ({"rule": "future_rule", "params": {}, "text": "[E01] 新规则"},
                 {"rule": "location_ref", "params": {"shot": "E01-SH001"}, "text": "[E01] 少参数"},
                 {"rule": "location_ref", "params": "坏", "text": "[E01] 坏参数"},
                 "裸字符串"):
        got = V.lint_lines([item])[1]["params"]["text"]
        want = item["text"] if isinstance(item, dict) else item
        assert got == {"t": "vendor", "text": want}, (item, got)
    print("4. 认不出的一条退回原文 ✓")

    # 5. 参数先脱敏再截断；列表最多 20 项；空的可选项写成「无」；布尔、小数、None 按文本写法
    os.environ["ARK_API_KEY"] = FAKE
    try:
        long_loc = "S" * 290 + FAKE                  # 密钥横跨 300 字的截断位置
        got = V.lint_lines([{"rule": "location_ref", "params": {"shot": "E01-SH001", "location": long_loc},
                             "text": "x"}])[1]["params"]["text"]["params"]["location"]
        assert FAKE[:6] not in got and got == ("S" * 290 + "***")[:300], got
        fb = V.lint_lines([{"rule": "nope", "params": {}, "text": "坏 " + FAKE}])[1]["params"]["text"]["text"]
        assert FAKE not in fb and "***" in fb
        d = SNAP.base()
        d["episodes"][0]["shots"][0]["location_ref"] = "S9" + FAKE
        _, data, _ = lint_json(d)
        assert FAKE in data["text"], "回喂模型的原文不脱敏（与 render() 相同，spec 子计划 5 F）"
        assert FAKE not in json.dumps(V.lint_lines(data["errors"]), ensure_ascii=False)
    finally:
        del os.environ["ARK_API_KEY"]
    d = SNAP.base()
    d["source"]["units"].extend({"id": f"u{i:04d}", "text": "多。", "para": 29, "kind": "action"} for i in range(68, 93))
    _, data, _ = lint_json(d)
    p = V.lint_lines(data["errors"])[1]["params"]["text"]["params"]
    assert p["n"] == 25 and p["units"] == [f"u{i:04d}" for i in range(68, 88)], p
    d = SNAP.base()
    next(c for c in d["assets"]["characters"] if c["id"] == "C06")["reference_images"] = [
        {"view": "front", "uri": "c.png", "outfit": "summer"}]
    _, data, _ = lint_json(d)
    line = V.lint_lines(data["errors"])[1]
    assert line["params"]["text"]["params"]["options"] == {"t": "ref", "code": "verify.report.lint_none"}
    assert zh(line) == "  [C06] 参考图标注的 outfit「summer」不存在（可选：无）", zh(line)
    assert V._lint_value(True) == "True" and V._lint_value(1.0) == "1.0" and V._lint_value(None) == "None"
    assert V._lint_value(3) == 3 and V._lint_value({"a": 1}) == '{"a": 1}'
    print("5. 先脱敏再截断、列表上限、可选项为空、值的写法 ✓")

    # 6. checker_lines：lint 有结构化错误就翻译；没有就和保真输出一起按行拆分（子计划 5 的做法）
    fid_fail = "FAIL 原文保真：unit 拼接与原文不一致\n  首个差异位置 3"
    assert V.checker_lines(False, "ERROR t", ERRS, True, "PASS") == V.lint_lines(ERRS)
    assert V.checker_lines(False, "ERROR t", ERRS, False, fid_fail) == V.lint_lines(ERRS) + V.tool_lines(fid_fail)
    assert V.checker_lines(False, "ERROR 原文一条\n", None, True, "PASS") == V.tool_lines("ERROR 原文一条")
    assert V.checker_lines(True, "PASS", None, False, fid_fail) == V.tool_lines(fid_fail)
    print("6. checker_lines 的四种组合 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 写前端失败测试**：`frontend/tests/server-msg.test.ts` 末尾 `console.log('\nALL PASS')` 之前加一节：

```ts
// 子计划 5b：分镜检查（lint）逐条按规则渲染，英文里没有中文，中文里没有英文模板；旧报告的原文照旧
{
  const CJK = /[\u4e00-\u9fff]/
  const lintRules = Object.keys(en.srv.verify.lint) as (keyof typeof en.srv.verify.lint)[]
  must(lintRules.length === 23 && lintRules.every((k) => k in zh.srv.verify.lint), 'verify.lint 中英各 23 条')
  for (const rule of lintRules) {
    const holes = [...zh.srv.verify.lint[rule].matchAll(/\{(\w+)\}/g)].map((m) => m[1])
    const params: Record<string, unknown> = {}
    for (const k of holes) params[k] = k === 'options' ? ['default', 'summer'] : k === 'detail' ? { t: 'vendor', text: "'huge' is not valid" } : k === 'n' || k === 'beat' ? 2 : `X-${k}`
    const line = { code: 'verify.report.tool_error', params: { text: { code: `verify.lint.${rule}`, params } } }
    const e = formatMsg(line, 'en'), z = formatMsg(line, 'zh')
    must(!CJK.test(e) && !e.includes('{') && e.startsWith('  '), `${rule} 英文不混中文、占位符都填上：${e}`)
    must(CJK.test(z) && !/refers to|doesn’t|isn’t/.test(z), `${rule} 中文不混英文模板：${z}`)
  }
  const none = { code: 'verify.lint.ref_image_outfit', params: { card: 'C06', outfit: 'summer', options: { t: 'ref', code: 'verify.report.lint_none' } } }
  must(formatMsg(none, 'en') === '[C06] A reference image is tagged with outfit “summer”, which doesn’t exist (options: none)', formatMsg(none, 'en'))
  must(formatMsg(none, 'zh') === '[C06] 参考图标注的 outfit「summer」不存在（可选：无）', formatMsg(none, 'zh'))
  const opts = { code: 'verify.lint.outfit_unknown', params: { shot: 'E01-SH001', character: 'C01', outfit: 'summer', options: ['default', 'night'] } }
  must(formatMsg(opts, 'en').endsWith('(options: default, night)') && formatMsg(opts, 'zh').endsWith('（可选：default、night）'), '可选项按语言的列表分隔')
  const report = { t: 'lines', items: [{ code: 'verify.report.lint', params: {} },
    { code: 'verify.report.tool_error', params: { text: { code: 'verify.lint.location_ref', params: { shot: 'E01-SH001', location: 'S99' } } } },
    { code: 'verify.report.tool_error', params: { text: { t: 'vendor', text: '[E01] 认不出的一条' } } }] }
  const failedLint = { code: 'job.failed_report', params: { reason: { code: 'job.batch_failed', params: { batch: 1, retries: 2 } }, report } }
  must(formatMsg(failedLint, 'en').endsWith(`${en.srv.verify.report.lint}\n  [E01-SH001] location_ref refers to a location that doesn’t exist: S99\n  [E01] 认不出的一条`),
    '失败报告里的 lint 逐条（英文），认不出的一条原文显示：' + formatMsg(failedLint, 'en'))
  must(formatMsg(failedLint, 'zh').endsWith('分镜检查发现的错误：\n  [E01-SH001] location_ref 引用了不存在的场景：S99\n  [E01] 认不出的一条'), formatMsg(failedLint, 'zh'))
  const old = { code: 'verify.report.tool_error', params: { text: { t: 'vendor', text: '[E01-SH001] location_ref 引用不存在的场景: L09' } } }
  must(formatMsg(old, 'en') === '  [E01-SH001] location_ref 引用不存在的场景: L09', '旧报告（子计划 5 的 tool_error 原文）照旧原样显示')
  console.log('子计划 5b：lint 逐条中英渲染、旧报告兼容 ✓')
}
```

- [ ] **Step 3: 运行确认失败**：
  - `cd backend && .venv/bin/python tests/pipeline/test_lint_msgs.py`：`AttributeError: module 'pipeline.verification' has no attribute 'lint_lines'`；
  - `cd frontend && npm test`：`typecheck` 报 `en.srv.verify.lint` 不存在。
- [ ] **Step 4: 登记代码**：`backend/server/messages.py` 里 `register("verify.report.tool_error", "  {text}")` 那一行之后插入：

```python
register("verify.report.lint", "分镜检查发现的错误：")
register("verify.report.lint_none", "无")
# 分镜检查（lint）逐条（子计划 5b）：代码是 verify.lint.<rule>，rule 与参数由 tools/lint_storyboard.py --json 给出；
# 回喂模型的是 lint 的文本原文，不走这里。逐条套在 verify.report.tool_error 里显示（text 是本条消息）
register("verify.lint.schema", "不符合分镜结构定义（{path}）：{detail}")
register("verify.lint.ref_image_outfit", "[{card}] 参考图标注的 outfit「{outfit}」不存在（可选：{options}）")
register("verify.lint.ref_image_state", "[{card}] 参考图标注的 state「{state}」不存在（可选：{options}）")
register("verify.lint.asset_empty_constraint", "[{card}] constraints 里有空的约束项")
register("verify.lint.curve_shot", "[{episode}] music.curve 引用了本集没有的镜头：{shot}")
register("verify.lint.curve_unit", "[{episode}] music.curve.unit_refs 引用了不存在的句子：{unit}")
register("verify.lint.curve_reversed", "[{episode}] music.curve 区间倒序：{start} 在 {end} 之后")
register("verify.lint.shot_unit", "[{shot}] source.unit_refs 引用了不存在的句子：{unit}")
register("verify.lint.inferred_no_note", "[{shot}] derivation=inferred 但缺少 inference_note")
register("verify.lint.beats_duration", "[{shot}] beats 各拍时长之和 {total}s 与镜头 duration_sec {duration}s 不符")
register("verify.lint.beat_no_action", "[{shot}] beats 第 {beat} 拍缺少 action")
register("verify.lint.shot_empty_constraint", "[{shot}] constraints 里有空的约束项")
register("verify.lint.location_ref", "[{shot}] location_ref 引用了不存在的场景：{location}")
register("verify.lint.prop_ref", "[{shot}] prop_refs 引用了不存在的道具：{prop}")
register("verify.lint.prop_state_required", "[{shot}] 道具 {prop} 有状态集，引用时必须填 state（可选：{options}）")
register("verify.lint.prop_state_unknown", "[{shot}] 道具 {prop} 没有 state「{state}」（可选：{options}）")
register("verify.lint.prop_state_unexpected", "[{shot}] 道具 {prop} 没有状态集，引用时不应填 state")
register("verify.lint.creature_outfit", "[{shot}] 生物 {creature} 的引用不应填 outfit")
register("verify.lint.character_ref", "[{shot}] characters.ref 引用了不存在的角色或生物：{character}")
register("verify.lint.outfit_unknown", "[{shot}] 角色 {character} 没有 outfit「{outfit}」（可选：{options}）")
register("verify.lint.dialogue_character", "[{shot}] dialogue.character_ref 引用了不存在的角色：{character}")
register("verify.lint.narration_unit", "[{shot}] narration.unit_refs 引用了不存在的句子：{unit}")
register("verify.lint.coverage_unmapped", "[coverage] 有 {n} 句原文没有被任何镜头的旁白覆盖，也没有标 skipped：{units}")
```

  然后 `cd backend && .venv/bin/python -m server.messages --write`。
- [ ] **Step 5: 前端文案**：
  - `frontend/src/i18n/zh.ts`：把 `srv.verify.report` 里的
    ```ts
            tool_error: '  {text}',
          },
    ```
    （`tool_error` 一行加上 `report` 节点的收尾）替换为：

```ts
        tool_error: '  {text}',
        lint: '分镜检查发现的错误：',
        lint_none: '无',
      },
      lint: {
        schema: '不符合分镜结构定义（{path}）：{detail}',
        ref_image_outfit: '[{card}] 参考图标注的 outfit「{outfit}」不存在（可选：{options}）',
        ref_image_state: '[{card}] 参考图标注的 state「{state}」不存在（可选：{options}）',
        asset_empty_constraint: '[{card}] constraints 里有空的约束项',
        curve_shot: '[{episode}] music.curve 引用了本集没有的镜头：{shot}',
        curve_unit: '[{episode}] music.curve.unit_refs 引用了不存在的句子：{unit}',
        curve_reversed: '[{episode}] music.curve 区间倒序：{start} 在 {end} 之后',
        shot_unit: '[{shot}] source.unit_refs 引用了不存在的句子：{unit}',
        inferred_no_note: '[{shot}] derivation=inferred 但缺少 inference_note',
        beats_duration: '[{shot}] beats 各拍时长之和 {total}s 与镜头 duration_sec {duration}s 不符',
        beat_no_action: '[{shot}] beats 第 {beat} 拍缺少 action',
        shot_empty_constraint: '[{shot}] constraints 里有空的约束项',
        location_ref: '[{shot}] location_ref 引用了不存在的场景：{location}',
        prop_ref: '[{shot}] prop_refs 引用了不存在的道具：{prop}',
        prop_state_required: '[{shot}] 道具 {prop} 有状态集，引用时必须填 state（可选：{options}）',
        prop_state_unknown: '[{shot}] 道具 {prop} 没有 state「{state}」（可选：{options}）',
        prop_state_unexpected: '[{shot}] 道具 {prop} 没有状态集，引用时不应填 state',
        creature_outfit: '[{shot}] 生物 {creature} 的引用不应填 outfit',
        character_ref: '[{shot}] characters.ref 引用了不存在的角色或生物：{character}',
        outfit_unknown: '[{shot}] 角色 {character} 没有 outfit「{outfit}」（可选：{options}）',
        dialogue_character: '[{shot}] dialogue.character_ref 引用了不存在的角色：{character}',
        narration_unit: '[{shot}] narration.unit_refs 引用了不存在的句子：{unit}',
        coverage_unmapped: '[coverage] 有 {n} 句原文没有被任何镜头的旁白覆盖，也没有标 skipped：{units}',
      },
```

  - `frontend/src/i18n/en.ts`：同一处替换为：

```ts
        tool_error: '  {text}',
        lint: 'Errors found by the storyboard check:',
        lint_none: 'none',
      },
      lint: {
        schema: 'Doesn’t match the storyboard schema ({path}): {detail}',
        ref_image_outfit: '[{card}] A reference image is tagged with outfit “{outfit}”, which doesn’t exist (options: {options})',
        ref_image_state: '[{card}] A reference image is tagged with state “{state}”, which doesn’t exist (options: {options})',
        asset_empty_constraint: '[{card}] constraints has an empty item',
        curve_shot: '[{episode}] music.curve refers to a shot that isn’t in this episode: {shot}',
        curve_unit: '[{episode}] music.curve.unit_refs refers to a source line that doesn’t exist: {unit}',
        curve_reversed: '[{episode}] music.curve range is reversed: {start} comes after {end}',
        shot_unit: '[{shot}] source.unit_refs refers to a source line that doesn’t exist: {unit}',
        inferred_no_note: '[{shot}] derivation is inferred, but inference_note is missing',
        beats_duration: '[{shot}] The beats add up to {total}s, but the shot’s duration_sec is {duration}s',
        beat_no_action: '[{shot}] Beat {beat} has no action',
        shot_empty_constraint: '[{shot}] constraints has an empty item',
        location_ref: '[{shot}] location_ref refers to a location that doesn’t exist: {location}',
        prop_ref: '[{shot}] prop_refs refers to a prop that doesn’t exist: {prop}',
        prop_state_required: '[{shot}] Prop {prop} has states, so the reference must set state (options: {options})',
        prop_state_unknown: '[{shot}] Prop {prop} has no state “{state}” (options: {options})',
        prop_state_unexpected: '[{shot}] Prop {prop} has no states, so the reference shouldn’t set state',
        creature_outfit: '[{shot}] Creature {creature}: the reference shouldn’t set outfit',
        character_ref: '[{shot}] characters.ref refers to a character or creature that doesn’t exist: {character}',
        outfit_unknown: '[{shot}] Character {character} has no outfit “{outfit}” (options: {options})',
        dialogue_character: '[{shot}] dialogue.character_ref refers to a character that doesn’t exist: {character}',
        narration_unit: '[{shot}] narration.unit_refs refers to a source line that doesn’t exist: {unit}',
        coverage_unmapped: '[coverage] Source lines not covered by any shot’s narration and not marked skipped ({n}): {units}',
      },
```

  （两处原文在各自文件里都只出现一次；替换后 `report` 节点多了 `lint`、`lint_none` 两个键，`verify` 节点在 `report` 之后多了 `lint` 子节点，原有的 `quality`、`review`、`attempt` 不动。）
- [ ] **Step 6: 实现**：`backend/pipeline/verification.py`
  - 导入行 `from server.messages import compact, msg, ref, vendor` 改为 `from server.messages import VENDOR_MAX, compact, msg, ref, vendor`；
  - 文件末尾（`tool_lines` 之后）追加：

```python
_LINT_LIST_MAX = 20     # lint 的列表参数（可选项、未覆盖句子）最多列几项；未覆盖句子另有总数 n


def _lint_value(v):
    """lint 参数 → 消息参数（spec 子计划 5b E）：字符串先脱敏再截断 300 字；整数原样；
    布尔、小数、None 按文本模式的写法转成字符串（前后端渲染一致）；列表逐项、最多 20 项；其它序列化后同字符串。"""
    if isinstance(v, bool) or v is None or isinstance(v, float):
        return str(v)
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        return scrub_secrets(v)[:VENDOR_MAX]
    if isinstance(v, list):
        return [_lint_value(x) for x in v[:_LINT_LIST_MAX]]
    return scrub_secrets(json.dumps(v, ensure_ascii=False, default=str))[:VENDOR_MAX]


def _lint_msg(item) -> dict:
    """lint 的一条错误 → verify.lint.<rule> 消息。规则没登记、参数与模板不符、形状不对时退回该条原文（厂商原文，脱敏）。"""
    try:
        params = {k: _lint_value(v) for k, v in item["params"].items()}
        if "detail" in params:                      # jsonschema 原文：与 SCHEMA-001 一样作厂商原文
            params["detail"] = vendor(params["detail"])
        if params.get("options") == []:
            params["options"] = ref("verify.report.lint_none")
        return compact(msg(f"verify.lint.{item['rule']}", **params))
    except (KeyError, TypeError, ValueError, AttributeError):
        text = item.get("text", "") if isinstance(item, dict) else item
        return vendor(scrub_secrets(str(text)))


def lint_lines(errors: list) -> list:
    """lint 的结构化错误 → 给用户看的逐条：标题 verify.report.lint，加每条一项 verify.report.tool_error，
    其 text 是嵌套的 verify.lint.<rule> 消息（认不出的一条退回原文）。"""
    return [compact(msg("verify.report.lint"))] + [
        compact(msg("verify.report.tool_error", text=_lint_msg(e))) for e in errors]


def checker_lines(lint_ok: bool, lint_text: str, lint_errors: Optional[list],
                  fid_ok: bool, fid_text: str) -> list:
    """lint 与保真未过时给用户的逐条（批内校验与整章终检共用，spec 子计划 5b C）。
    lint 有结构化错误就按条翻译；没有（崩溃、输出认不出、测试替身）就与保真输出一起按行拆分（tool_lines，同子计划 5）。"""
    out, raw = [], []
    if not lint_ok:
        if lint_errors:
            out.extend(lint_lines(lint_errors))
        else:
            raw.append(lint_text.strip())
    if not fid_ok:
        raw.append(fid_text.strip())
    if raw:
        out.extend(tool_lines("\n".join(raw)))
    return out
```

  注意：`_lint_msg` 里调用模块级的 `ref(…)`；本文件 `_validate_evidence` 里有同名循环变量，新函数里不要引入名叫 `ref` 的局部变量（子计划 5 R11）。
- [ ] **Step 7: 运行确认通过**：
  - `cd backend && .venv/bin/python tests/pipeline/test_lint_msgs.py`，预期第 1–6 节各一个 ✓、`ALL PASS`；
  - `cd frontend && npm test`：`server-msg` 打印「子计划 5b：lint 逐条中英渲染、旧报告兼容 ✓」，`srv-codes` 通过（代码数比改动前多 25）。
- [ ] **Step 8: 跑全部校验并提交**：
  ```bash
  git add backend/server/messages.py backend/server/messages_codes.json backend/pipeline/verification.py \
    backend/tests/pipeline/test_lint_msgs.py frontend/src/i18n/zh.ts frontend/src/i18n/en.ts frontend/tests/server-msg.test.ts
  git commit -m "登记分镜检查的 23 条逐条代码 verify.lint.* 与标题、可选项为空的写法，补中英文案；lint 的结构化错误转成逐条消息，参数先脱敏再截断，认不出的一条退回原文；暂不接入流水线"
  ```

---

### Task 3: 流水线接入：批内校验与整章终检读 `--json`，失败区按语言显示 lint 逐条

**Files:**
- Modify: `backend/pipeline/graph.py`（`_check_batch`）、`backend/pipeline/convert.py`（整章终检）
- Modify: `backend/tests/pipeline/test_graph.py`、`backend/tests/pipeline/test_offline.py`（替身）
- Test: `backend/tests/pipeline/test_lint_msgs.py`（追加第 7、8 节）、`frontend/tests/workspace.test.tsx`

- [ ] **Step 1: 写失败测试**：`backend/tests/pipeline/test_lint_msgs.py`
  - 导入行 `from pipeline import verification as V  # noqa: E402` 替换为：
    ```python
    from fakes import FakeChat  # noqa: E402
    from pipeline import graph, validate, verification as V  # noqa: E402
    from pipeline.chat import ChatInvoker  # noqa: E402
    from pipeline.config import Settings  # noqa: E402
    from pipeline.errors import ConversionError  # noqa: E402
    ```
  - `from test_lint_json import EXPECT_PARAMS, lint_json, source_rules  # noqa: E402` 之后加一行：
    ```python
    from test_lint_feed_snapshot import PARAMS as CONVERT_PARAMS  # noqa: E402
    ```
  - `main()` 里 `print("\nALL PASS")` 之前插入：

```python
    # 7. 流水线：_check_batch 的逐条按规则翻译、报告仍是原文；重试耗尽时 ConversionError.lines 同样
    shown = []
    with tempfile.TemporaryDirectory() as w:
        ok, hard, report, _, _ = graph._check_batch(SNAP.feed_doc(), SNAP.batch_text(), Settings(), Path(w), 1, 1,
                                                    None, lambda _: None, lines_out=shown)
    assert (ok, hard, report) == (False, True, SNAP.FEED_REPORT)
    codes = [x["params"]["text"]["code"] for x in shown[1:]]
    assert shown[0]["code"] == "verify.report.lint" and codes == [
        "verify.lint.location_ref", "verify.lint.character_ref", "verify.lint.outfit_unknown",
        "verify.lint.dialogue_character", "verify.lint.prop_ref"], codes
    settings = Settings(api_key="k", max_retries=0, normalize_input=False, freeze_source_units=False)
    with tempfile.TemporaryDirectory() as w:
        chat = ChatInvoker(settings, chat=FakeChat(responses=[json.dumps(SNAP.feed_doc(), ensure_ascii=False)]),
                           log=lambda _: None)
        g = graph.build_batch_graph(chat=chat, review_chat=None, settings=settings, params=CONVERT_PARAMS,
                                    workdir=Path(w), attempt_records=[], log=lambda _: None)
        try:
            graph.run_batch(g, user="原文", batch_text=SNAP.batch_text(), idx=1, frozen_units=None)
            raise AssertionError("应抛 ConversionError")
        except ConversionError as e:
            assert e.code == "job.batch_failed" and e.report == SNAP.FEED_REPORT
            assert e.lines == shown, e.lines
            text = M.render_zh("job.failed_report", {"reason": {"code": e.code, "params": e.params},
                                                      "report": M.lines_of(e.lines)})
            assert "ERROR" not in text and "location_ref 引用了不存在的场景：S99" in text, text
    print("7. 流水线：逐条按规则、报告与回喂仍是原文 ✓")

    # 8. 整章终检：lint 未过时用同一套逐条（批内那次用真的 lint，只让终检那次失败）
    import pipeline.convert as convert_mod
    real_lint = validate.run_lint_report
    calls = []

    def final_fails(path):
        calls.append(path)
        return real_lint(path) if len(calls) == 1 else validate.LintReport(False, "ERROR 原文\n", ERRS)
    validate.run_lint_report = final_fails
    try:
        archived = json.dumps(SNAP.base(), ensure_ascii=False)
        with tempfile.TemporaryDirectory() as w:
            try:
                convert_mod.convert_text(SNAP.batch_text(), CONVERT_PARAMS, settings=settings,
                                         llm=FakeChat(responses=[archived]), batches=[SNAP.batch_text()],
                                         workdir=Path(w), log=lambda _: None)
                raise AssertionError("终检 lint 未过应抛 ConversionError")
            except ConversionError as e:
                assert e.code == "job.final_check_failed" and e.report.startswith("ERROR 原文\n\n"), e.report
                assert e.lines == V.lint_lines(ERRS), e.lines
    finally:
        validate.run_lint_report = real_lint
    print("8. 整章终检的逐条 ✓")

```

- [ ] **Step 2: 写前端失败测试**：`frontend/tests/workspace.test.tsx` 的「7. 动态面板」里，`const deg = { code: 'job.quality.degraded', …` 那一行之前插入：

```tsx
  // 子计划 5b：lint 未过时失败区的逐条按规则渲染，英文里没有中文（数据是 ASCII 编号）
  const lintL = { code: 'job.failed_report', params: { reason: { code: 'job.batch_failed', params: { batch: 1, retries: 2 } },
    report: { t: 'lines', items: [{ code: 'verify.report.lint', params: {} },
      { code: 'verify.report.tool_error', params: { text: { code: 'verify.lint.location_ref', params: { shot: 'E01-SH001', location: 'S99' } } } },
      { code: 'verify.report.tool_error', params: { text: { code: 'verify.lint.outfit_unknown',
        params: { shot: 'E01-SH003', character: 'C01', outfit: 'summer', options: ['default'] } } } }] } } }
  await render(jwrap(h(JobPanel, { job: jobOf([], { status: 'failed', error: '旧中文', error_msg: lintL }), ...props })))
  must(q('.job__err')?.textContent === '批 1 重试 2 次后仍未通过校验\n分镜检查发现的错误：\n  [E01-SH001] location_ref 引用了不存在的场景：S99'
    + '\n  [E01-SH003] 角色 C01 没有 outfit「summer」（可选：default）', 'lint 逐条（中文）：' + q('.job__err')?.textContent)
  await lang('en')
  const enErr = q('.job__err')?.textContent ?? ''
  must(!/[\u4e00-\u9fff]/.test(enErr) && enErr.includes(en.srv.verify.report.lint)
    && enErr.endsWith('\n  [E01-SH003] Character C01 has no outfit “summer” (options: default)'), 'lint 逐条切英文、不混中文：' + enErr)
  await lang('zh')
```

  （这条前端用例在 Task 2 之后其实已经能过：它只依赖文案与 `formatMsg`。放在本 Task 是因为它对应「失败区」这个显示处。）
- [ ] **Step 3: 运行确认失败**：`cd backend && .venv/bin/python tests/pipeline/test_lint_msgs.py`，第 7 节断言 `shown[0]["code"] == "verify.report.lint"` 失败（现在是 `verify.report.tool`）。
- [ ] **Step 4: 接入 `graph._check_batch`**：把
  ```python
      lint_ok, lint_out = validate.run_lint(tmp)
      fid_ok, fid_out = validate.run_fidelity(tmp, batch_text, workdir)
      if not (lint_ok and fid_ok):
          text = lint_out.strip() + "\n" + fid_out.strip()
          out.extend(verification.tool_lines(text))
          return False, True, text, None, structured
  ```
  替换为：
  ```python
      lint = validate.run_lint_report(tmp)
      fid_ok, fid_out = validate.run_fidelity(tmp, batch_text, workdir)
      if not (lint.ok and fid_ok):
          # 回喂模型的仍是 lint 文本原文（与加 --json 之前逐字相同）；给用户的逐条按规则翻译（spec 子计划 5b D）
          text = lint.text.strip() + "\n" + fid_out.strip()
          out.extend(verification.checker_lines(lint.ok, lint.text, lint.errors, fid_ok, fid_out))
          return False, True, text, None, structured
  ```
- [ ] **Step 5: 接入 `convert.py` 整章终检**：
  - `lint_ok, lint_out = validate.run_lint(merged_path)` → `lint = validate.run_lint_report(merged_path)`；
  - `log(lint_out.strip())` → `log(lint.text.strip())`；
  - 把
    ```python
        if not (lint_ok and fid_ok):
            run_manifest["state"] = "failed"
            run_manifest["verification"] = final_report.to_dict()
            raise ConversionError.of("job.final_check_failed", lint_out + "\n" + fid_out,
                                     verification.tool_lines(lint_out + "\n" + fid_out))
    ```
    替换为：
    ```python
        if not (lint.ok and fid_ok):
            run_manifest["state"] = "failed"
            run_manifest["verification"] = final_report.to_dict()
            raise ConversionError.of("job.final_check_failed", lint.text + "\n" + fid_out,
                                     verification.checker_lines(lint.ok, lint.text, lint.errors, fid_ok, fid_out))
    ```
  - 注意 `convert_text` 里的 `text` 是整章原文，别和 `lint.text` 混用。合并失败（`job.merge_failed`）那段不改。
- [ ] **Step 6: 改测试替身**（按调用点清单「测试替身」表）：
  - `tests/pipeline/test_graph.py` 3f 节：
    ```python
        real_merge, real_lint, real_fid = validate_mod.run_merge, validate_mod.run_lint_report, validate_mod.run_fidelity
    ```
    ```python
                return real_lint(path) if len(calls) == 1 else validate_mod.LintReport(False, "ERROR lint 失败一条")
            validate_mod.run_lint_report = lint_final_fails
    ```
    ```python
            validate_mod.run_merge, validate_mod.run_lint_report, validate_mod.run_fidelity = real_merge, real_lint, real_fid
    ```
    其余断言（`e.report == "ERROR lint 失败一条\n"`、`e.lines` 是 `verify.report.tool` + 一条原文）不变：替身没有 `errors`，`checker_lines` 走原文拆分。
  - `tests/pipeline/test_offline.py`：
    - 344 行 `orig_lint = convert_mod.validate.run_lint_report`；
    - 352、420、436 行 `convert_mod.validate.run_lint_report = lambda p: convert_mod.validate.LintReport(True, "PASS（打桩）")`；
    - 410、429、451、695 行 `convert_mod.validate.run_lint_report = orig_lint`；
    - 661 行 `convert_mod.validate.run_lint_report = lambda p: convert_mod.validate.LintReport(`（下一行 `False, "FAIL: …")` 不变）；
    - 680 行 `convert_mod.validate.run_lint_report = lambda p: convert_mod.validate.LintReport(False, long_report)`；
    - 1124 行不改。
  - 改完 `grep -n "validate.run_lint\b" tests/pipeline/test_offline.py tests/pipeline/test_graph.py` 只剩 `test_offline.py` 的 1124 行。
- [ ] **Step 7: 运行确认通过**：
  - `.venv/bin/python tests/pipeline/test_lint_msgs.py`：第 1–8 节、`ALL PASS`；
  - `test_lint_feed_snapshot.py`、`test_llm_feed_snapshot.py`、`test_graph.py`、`test_offline.py` 全部 `ALL PASS`；
  - `cd frontend && npm test` 通过（`workspace: ALL PASS`）。
- [ ] **Step 8: 跑全部校验并提交**：
  ```bash
  git add backend/pipeline/graph.py backend/pipeline/convert.py backend/tests/pipeline/test_graph.py \
    backend/tests/pipeline/test_offline.py backend/tests/pipeline/test_lint_msgs.py frontend/tests/workspace.test.tsx
  git commit -m "转换流水线改读 lint 的 --json：批内校验与整章终检的失败区按规则逐条显示（中英随界面），回喂模型、日志与失败报告仍用 lint 文本原文；lint 与保真都未过时两段都列；测试替身改为 run_lint_report"
  ```

---

### Task 4: 收尾核对

**Files:**
- Modify（如需要）：`backend/server/messages_codes.json`

- [ ] **Step 1: 回喂模型不变**：
  - `test_lint_feed_snapshot.py`、`test_llm_feed_snapshot.py` 通过；
  - `git log --oneline -- backend/tests/pipeline/lint_snapshot.py backend/tests/pipeline/test_lint_feed_snapshot.py` 只有 Task 0 那一次提交；`git log --oneline 71f72a8.. -- backend/tests/pipeline/feed_snapshot.py backend/tests/pipeline/test_llm_feed_snapshot.py` 为空；
  - `git diff 71f72a8 -- backend/pipeline/graph.py` 只动了 `_check_batch` 里 lint 那几行，`plan_repair`、`_record`、`_log_report`、`finalize` 没有改动；`backend/pipeline/repair.py` 没有改动。
- [ ] **Step 2: lint 原文一字不改**：
  ```bash
  cd backend && .venv/bin/python - <<'PY'
  import re, subprocess
  old = subprocess.run(["git", "show", "71f72a8:backend/tools/lint_storyboard.py"], capture_output=True, text=True).stdout
  new = open("tools/lint_storyboard.py", encoding="utf-8").read()
  pat = re.compile(r'f"[^"\n]*"|"jsonschema 未安装[^"]*"')
  lost = [s for s in pat.findall(old) if s not in new]
  print("lost:", lost)
  PY
  ```
  输出 `lost: []`（旧文件里每个 f-string 与 jsonschema 那句都原样出现在新文件里）。
- [ ] **Step 3: 规则齐全**：`grep -c 'errors.append(_item(' tools/lint_storyboard.py` 为 23，`grep -c 'warnings.append(_item(' tools/lint_storyboard.py` 为 6；`grep -c '"verify.lint\.' server/messages_codes.json` 为 23（`test_lint_msgs.py` 第 2 节已断言，这里人工再看一眼）。
- [ ] **Step 4: 文案检查**：
  - `grep -in "deepseek\|claude\|anthropic" server/messages_codes.json` 不命中新登记的文案；
  - 英文 `srv.verify.lint` 与 `srv.verify.report.lint` 里没有 `(s)` 式的单复数写法、没有中文字符（`server-msg.test.ts` 已断言渲染结果）。
- [ ] **Step 5: 扫描**：`.venv/bin/python tests/server/test_i18n_scan.py` 通过（`graph.py`、`convert.py`、`verification.py` 在 `MODULES` 里，新代码没有中文出口字面量）。
- [ ] **Step 6: 测试不碰真实数据目录与模型服务**：实施前记下 `ls -l backend/data/error_refs.jsonl backend/data/usage.jsonl 2>/dev/null`，跑完全部测试后再看一次，不存在的仍不存在，存在的大小与修改时间不变。
- [ ] **Step 7: 代码表最新**：`.venv/bin/python -m server.messages --write && git diff --exit-code server/messages_codes.json`。
- [ ] **Step 8: 命令行人工看一眼**（与改动前的脚本逐字对比默认输出；临时脚本放在 `tools/` 下才找得到 schema，用完删掉）：
  ```bash
  cd backend && git show 71f72a8:backend/tools/lint_storyboard.py > tools/_lint_old.py \
    && diff <(.venv/bin/python tools/_lint_old.py examples/example_storyboard_suspense.json) \
            <(.venv/bin/python tools/lint_storyboard.py examples/example_storyboard_suspense.json) && echo SAME; rm -f tools/_lint_old.py
  ```
  预期打印 `SAME`，且 `git status` 里没有 `_lint_old.py`。
- [ ] **Step 9: 全部校验**（全局约束里的整套）。
- [ ] **Step 10: 有改动才提交**（只 add 改到的文件）。提交信息示例：「子计划 5b 收尾：核对 lint 原文与回喂快照未变、23 条规则全部登记」。

---

## 实施裁定

- **R1 一次运行同时产出文本与 JSON，回喂用文本**（spec 子计划 5b D）：
  - 裁定：lint 的汇报段先拼出整段文本 `text`；默认写到 stdout，`--json` 时放进 JSON 的 `text` 字段。流水线只跑一次 `--json`，回喂模型、日志、失败报告用 `LintReport.text`，界面用 `LintReport.errors`。
  - 理由：回喂与界面来自同一次检查、同一个字符串，没有第二份拼法；跑两次子进程会多一倍耗时，且两次结果理论上可以分叉；进程内 `import` 违背 `validate.py`「以子进程调用工具」的约定，lint 崩溃会拖垮转换进程。
  - 若错的代价：`--json` 的 stdout 只有一行 JSON，人工排查时不如文本好读；排查时直接跑默认模式即可。
- **R2 新增 `run_lint_report`，`run_lint` 原样保留**：
  - 裁定：`validate.run_lint` 一行不改（文本模式）；流水线两处调用改用 `run_lint_report`；现有测试里替换 `run_lint` 的替身同步改成替换 `run_lint_report`（调用点清单「测试替身」表）。
  - 理由：`run_lint` 仍有调用方（`test_offline.py` 的覆盖率三处口径对照、外部脚本），保持它与改动前逐字一致最省心；新函数返回带名字段的 `LintReport`，比在 `(ok, text)` 二元组上加出参或给字符串挂属性都直白。不沿用子计划 5 R3 的出参写法：那条的理由是「替身不用改」，这里替身无论哪种写法都得改（`lambda p:` 收不了新关键字参数）。
  - 若错的代价：测试替身改 14 行（`test_offline.py` 10 行、`test_graph.py` 4 行）；漏改的替身会让测试跑真的 lint，结果对不上时在该测试里就会暴露。
- **R3 原 f-string 留在 lint 里，界面模板只在 `messages.py` 与 `srv`**：
  - 裁定：`_item(rule, 原 f-string, **params)`；lint 不导入 `server.messages`，不知道代码与模板。
  - 理由：同 `ORDER-001`（子计划 5 R4）：回喂模型的文字只能来自它自己的 f-string，以后润色界面文案不会悄悄改掉模型输入；lint 也保持独立脚本、可以脱离后端单独使用。
  - 若错的代价：同一条错误的文字有两处（lint 原文、界面模板），措辞可能渐行渐远；语义由每条规则的测试（参数）钉住。
- **R4 逐条套在 `verify.report.tool_error` 里，标题另起 `verify.report.lint`**：
  - 裁定：每条 lint 错误是 `verify.report.tool_error {text: {code: "verify.lint.<rule>", params}}`；标题 `verify.report.lint`「分镜检查发现的错误：」。
  - 理由：`tool_error` 的模板只有缩进与 `{text}`，参数本来就允许嵌套消息，新旧报告共用一个代码，前端不用分辨；原标题「工具报告的错误（原文）：」的「原文」对已翻译的逐条不成立，所以标题换一个，保真与合并工具仍用原标题。
  - 若错的代价：`tool_error` 的 `text` 参数有两种类型（厂商原文、嵌套消息），读原始 JSON 的人要知道这一点。
- **R5 WARN 带规则名进 JSON，但不登记、不显示**：
  - 裁定：6 处 `warnings.append` 同样改成 `_item`，`--json` 的 `warnings` 带规则名与参数；不登记 `verify.lint.*`，`lint_lines` 只处理 `errors`。
  - 理由：失败区只列错误（子计划 5 C），lint 通过时没有逐条；先把规则名给出来，以后要显示只需登记加文案。登记了却不用的代码会让 `srv-codes` 要求写 6 条用不到的英文。
  - 若错的代价：以后显示 WARN 时要补 6 条登记与文案（测试第 2 节会提醒规则名与登记表的差集）。
- **R6 参数在流水线侧规范化，lint 给原始值**：
  - 裁定：lint 的 `params` 是原始值；`verification._lint_value` 负责：字符串先 `scrub_secrets` 再截断 300 字，整数原样，布尔/小数/`None` 转成与原文相同的字符串，列表最多 20 项，其它 `json.dumps` 后按字符串；`detail` 包成厂商原文；`options` 为空换成代码引用 `verify.report.lint_none`。
  - 理由：脱敏要用后端的密钥清单（`SECRET_ENVS`），lint 作为独立脚本不该依赖它；「先脱敏再截断」与子计划 5、规格例外的做法一致；前端 `String(1.0)` 是 `"1"`，后端中文兜底是 `"1.0"`，小数预先转成字符串两边才一致（子计划 5 R7）；时长在 lint 里已经按原文的 `:g` 格式化成字符串。
  - 若错的代价：`--json` 的直接读者（流水线之外）拿到的是未脱敏的原始值——与 lint 文本输出相同，本来就不脱敏。
- **R7 两级回落**：
  - 裁定：某一条认不出（规则没登记、参数与模板不符、`params` 不是字典、整条不是字典）时，这一项的 `text` 退回该条原文（`vendor(scrub_secrets(text))`），其余照常翻译；整份 JSON 认不出（崩溃、替身）时 `errors = None`，`checker_lines` 走子计划 5 的 `tool_lines` 按行拆分。
  - 理由：lint 以后新加规则而忘了登记，不应让转换因为一条显示文案抛错（`Finding` 构造时抛错是因为规则与测试同在一个模块，这里 lint 与登记表分属两处）；漏登记由 `test_lint_msgs.py` 第 2 节（源码规则名 ↔ 登记表）抓住。
  - 若错的代价：漏登记的规则在英文界面显示中文原文（与子计划 5 的现状相同），直到测试报出来。
- **R8 lint 与保真都未过时两段都列**：
  - 裁定：`checker_lines` 先列 lint 段（结构化或原文），再列保真段（`tool_lines`）。
  - 理由：子计划 5 的 `tool_lines(lint + 保真)` 在 lint 有 `ERROR` 行时只取 `ERROR` 行，保真的 `FAIL` 行与差异行会被丢掉；拆成两段之后不再有这个问题。这是对用户可见的行为变化（多显示了原本被丢的信息），回喂模型的报告不变。
  - 若错的代价：两段各带一个标题，失败区多一行。
- **R9 lint 不加进 ast 扫描**：
  - 裁定：`tools/lint_storyboard.py` 不进 `test_i18n_scan.py` 的 `MODULES`。
  - 理由：它的中文是命令行输出与回喂模型的原文，不是给界面的出口；扫描规则（`raise`、`HTTPException`、`say` 等出口）对它也不适用。漏登记由「源码规则名 ↔ 登记表」的测试守护，比扫描中文字面量更直接。
  - 若错的代价：无（lint 没有直接到达界面的出口）。
- **R10 `--json` 只输出 ASCII，带 `version: 1`**：
  - 裁定：`json.dumps(…, ensure_ascii=True, default=str)`；顶层 `{"version": 1, "ok", "errors", "warnings", "text"}`。
  - 理由：子进程的 stdout 按父进程的区域设置解码，纯 ASCII 不受控制台编码影响；`text` 经 JSON 往返后与文本模式的字符串完全相同（测试第 1 节逐条比对）。`version` 留给以后改形状时区分；`default=str` 兜住模型写进编号里的怪值（文本模式本来就用 `str()` 打印它们）。
  - 若错的代价：人工看 `--json` 输出时中文是 `\uXXXX`；需要看中文就跑默认模式。
- **R11 命令行用法多一行，校验输出逐字不变**：
  - 裁定：`__doc__` 加一行 `--json` 的写法（只在参数不对时打印）；`--json` 写在路径前后都行；只给路径时行为与改动前完全相同。
  - 理由：「lint 命令行默认的文本输出保持不变」指的是校验结果；用法说明不写新参数，人工使用时发现不了它。
  - 若错的代价：以前误把两个参数传给 lint（如 `lint a.json --json`）会打印用法退出 2，现在进入 JSON 模式。仓库里没有这样的调用。
- **R12 `schema` 规则照登记，路径加前导 `/`**：
  - 裁定：`schema` 的 `path` 参数是 `"/" + "/".join(…)`，`detail` 是厂商原文；原文里的路径照旧不带 `/`。
  - 理由：流水线里批内先跑的结构校验（`SCHEMA-001`）用同一份 schema，没过就不会走到 lint，所以这条在流水线里几乎不会出现；但整章终检与外部调用会用到，登记了不会漏译。路径写法与 `SCHEMA-001` 一致，失败报告里两种来源对得上。
  - 若错的代价：无。
- **R13 未覆盖句子最多列 20 个，总数另给**：
  - 裁定：`coverage_unmapped` 的 `units` 截到 20 项（`_LINT_LIST_MAX`），`n` 是 lint 算出的总数；英文「(… skipped ({n}): {units}」不依赖单复数。
  - 理由：一章几百句的稿子可能整批没覆盖，原文会打印整个列表（回喂模型需要），给用户看的逐条只要知道有多少、前几个是哪些；`lines_of` 的 6000 字预算按项计，一项几千字会把后面的错误挤掉。
  - 若错的代价：可选项列表（`options`）同样截到 20 项且不提示还有更多；实际的服装与道具状态远少于 20 个。

## 自查记录

- **覆盖 spec 子计划 5b**：
  - A 范围：lint → Task 1；`validate.py` → Task 1；`verification.py` → Task 2；`graph.py`、`convert.py` → Task 3；`messages.py`、`messages_codes.json`、`zh.ts`、`en.ts` → Task 2；「不在本子计划」五项写进范围边界与 R5、R9。
  - B 逐条规则：23 条都在调用点清单与 Task 1 的 lint 代码里，参数与 spec 表一致；中英模板在 Task 2 Step 4、5；WARN 6 条 → Task 1（规则名）、R5；参数约定 → R6、R12、R13。
  - C JSON 形状 → Task 1（lint 代码、`test_lint_json.py` 第 1、3 节）；`run_lint_report` → Task 1 Step 4、测试第 4 节；`lint_lines`/`checker_lines`、两级回落 → Task 2、R7、R8；显示处 → 调用点清单「显示处」、Task 2（`server-msg.test.ts`）、Task 3（`workspace.test.tsx`）。
  - D 回喂不变 → Task 0（先行快照，单独提交）、R1、Task 3 Step 4 的注释、Task 4 Step 1–2；一致性测试 → `test_lint_json.py` 第 1、4 节。
  - E 脱敏与截断 → Task 2 `_lint_value`/`_lint_msg`、`test_lint_msgs.py` 第 5 节（密钥横跨截断位置、回喂原文不脱敏）；后续 `_scrub_tree`/`scrub_deep` 沿用子计划 5，不改。
  - F 兼容：旧报告 → `server-msg.test.ts` 的旧 `tool_error` 用例（以及子计划 5 已有的 `admin.test.tsx` v12 用例照旧通过）；命令行 → `test_lint_json.py` 第 5 节、Task 4 Step 8、R11；`run_lint` 保留 → R2、`test_lint_json.py` 第 4 节；替身 → Task 3 Step 6；前端中间提交 → Task 2 登记与文案同一提交、Task 3 才产出。
  - G 测试：每条规则各一条触发用例 → `test_lint_json.py` 第 1 节（规则名与参数）+ `test_lint_msgs.py` 第 1 节（代码与中文）；回喂不变 → Task 0；中英渲染不混杂 → `server-msg.test.ts`（23 条英文无中文字符、中文无英文模板词）与 `workspace.test.tsx`；旧报告兼容 → `server-msg.test.ts`。
  - H 代码命名 → Task 2 Step 4；前缀关系由 `register()` 在导入时检查。
- **中间提交都能跑**：Task 0 只加测试；Task 1 lint 多一种模式、`run_lint_report` 无人调用；Task 2 只加登记、文案与纯函数；Task 3 才改流水线与替身。每个登记了代码的 Task 同时补 `zh.ts`、`en.ts`，`srv-codes` 每步都过。
- **名称一致**：`_item`、`main(path, as_json=False)`、`LintReport(ok, text, errors)`、`run_lint_report`、`_LINT_LIST_MAX`、`_lint_value`、`_lint_msg`、`lint_lines`、`checker_lines(lint_ok, lint_text, lint_errors, fid_ok, fid_text)`；代码 `verify.report.lint`、`verify.report.lint_none`、`verify.lint.<rule>`；测试 `lint_snapshot`（`SNAP`：`CASES`、`LINT`、`PASS_TEXT`、`NO_JSONSCHEMA_TEXT`、`FEED_REPORT`、`FEED_SHA`、`base`、`batch_text`、`warn_case`、`feed_doc`）、`test_lint_feed_snapshot`（`PARAMS`、`dump`、`lint_text`）、`test_lint_json`（`EXPECT_PARAMS`、`WARN_RULES`、`lint_json`、`source_rules`）、`test_lint_msgs`（`EXPECT_ZH`、`ERRS`）。各 Task 引用一致。
- **没有占位**：所有新文件给出完整内容；所有修改给出替换前后的代码；快照字面量与哈希是实测值。
- **测试不碰真实模型与数据**：新测试文件都设临时 `STORYBOARD_DATA_DIR`、不可达的 `ANTHROPIC_BASE_URL`，桩掉 `_load_dotenv`；转换只用 `FakeChat`；lint 子进程只读临时目录里的文档与仓库里的 schema。
- **自查中发现并已改正**：
  - 原想让 `run_lint` 加出参（照子计划 5 R3），但 `lambda p:` 替身收不了新关键字参数，替身无论如何都要改，改为新函数 `run_lint_report`（R2）；
  - 原想在 lint 与保真都失败时沿用 `tool_lines(lint + 保真)`，那样保真的 `FAIL` 行在 lint 有 `ERROR` 行时会被丢掉，改为两段（R8）；
  - `curve_reversed` 的参数原想叫 `from`/`to`，`from` 是 Python 关键字，`msg(code, from=…)` 写不出来，改为 `start`/`end`；
  - 生物卡的造数据最初少了 schema 必填的 `visual_prompt`，会顺带触发 `[schema]`，已补齐，23 种情形都只触发一条错误。
