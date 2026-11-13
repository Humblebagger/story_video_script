# 后端双语 子计划 2：配音、合成与导出（含方舟错误映射、面向最终用户的文案）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 配音（TTS 厂商、音色）、合成（进度、报告、失败原因）、导出（README、文件名）这条链路上，后端给用户看的文字全部改为消息对象，前端按界面语言渲染；同时补上子计划 1 验收留下的两处缺口：方舟错误码友好映射、开发者口吻的文案改写为面向最终用户。

**Architecture:** 沿用子计划 1 的基础设施（`server/messages.py` 的 `register`/`msg`/`money`/`vendor`/`compact`/`UserError`/`to_detail`/`cause_of`，`render/session.py` 的 `set_error`/`copy_error`，前端 `i18n/serverMsg.ts` 的 `formatMsg`/`errValue`/`itemError`，`srv` 文案节点，`srv-codes` 与 ast 扫描两道校验）。本子计划只是把更多模块接上，不新增基础设施。唯一新机制：合成状态 `final` 增加 `step_msg`、`error_msg` 两个字段（与段上的 `error_msg` 同形），旧字段 `step`、`error` 保留作中文兜底。

**Tech Stack:** Python 3.12、httpx `MockTransport`、`unittest` 风格的 `assertLogs` 等价写法（本仓库测试是脚本式：用 `logging.Handler` 子类收集即可）、React 19 + TypeScript、Vite SSR 构建跑前端测试。

**Spec:** `docs/specs/2026-11-13-backend-i18n-design.md`（§9 子计划 2 原范围 + 文末「子计划 2 范围补充」A、B 两节，提交 dcdba2e）。本计划与 spec 冲突时以 spec 为准；spec 没写的细节见文末「实施裁定」。

---

## 全局约束（每个 Task 都必须遵守）

- 不读、不打印 `backend/.env`；密钥不进日志、报错、session.json、消息参数。新加的 `logging` 调用里同样不得出现密钥（厂商原文先 `scrub`）。
- 不调用任何付费厂商；不运行 `backend/render/smoke.py`、`backend/render/smoke_tts.py`、`backend/assistant/smoke.py`；不向运行中的 5173 / 8000 服务发请求。
- 测试绝不联网、不读真实 `.env`：厂商测试用 `httpx.MockTransport`；涉及 `from_env` 的用例先把 `_load_dotenv` 换成空操作（照 `tests/render/test_seedance.py` 现有写法）；接口测试把 `app._tts` 换成假 TTS。
- 不动 `docs/specs/2026-10-27-commercialization-design-contract.md`（未跟踪文件）。
- git：只 `git add` 具体文件，禁止 `git add -A` / `git commit -a` / `git add -N`；提交信息中文、描述性；不带任何 `Co-Authored-By` 或署名行；不 push。
- 改了登记表就运行 `cd backend && .venv/bin/python -m server.messages --write`，把 `backend/server/messages_codes.json` 一起提交。
- 每个 Task 结束时必须全部通过：
  - 后端（在 `backend/` 下）：
    `for t in tests/pipeline/test_*.py tests/server/test_*.py tests/render/test_*.py tests/assistant/test_*.py; do .venv/bin/python $t || break; done`
    每个脚本打印 `ALL PASS`，循环里没有任何一个失败（不要只看最后一行：用 `fail=0; for …; do .venv/bin/python $t >/dev/null || { echo FAIL $t; fail=1; }; done; echo fail=$fail`）。
  - 前端（在 `frontend/` 下）：`npm test` 退出码 0（直接检查 `$?`，不要接管道）；`npm run lint` 0 error、warning 不多于基线 5 条；`npm run build` 成功。
  - 已知既有问题：`frontend/tests/film.test.tsx` 偶发 CPU 自旋卡死（与本计划无关）。遇到时单独重跑判定：
    `npx vite build --ssr tests/film.test.tsx --outDir /tmp/i18n-film --logLevel error && timeout 60 node /tmp/i18n-film/film.test.js`，
    通过即可，然后把 `npm test` 里 film 之后的测试逐个跑完；临时输出不要留在仓库里。
- 中文兜底：spec B 节列出的代码按 spec 改文案；其余代码的中文兜底尽量与现在一字不差（模板 + 参数渲染结果等于原字符串），现有断言中文的测试大多不用改。不得不变的地方写在各 Task 的「文字变化」里。
- 英文文案由实现者初拟，风格照子计划 1 的 `en.ts` `srv` 节点（7d0d369 之后）：厂商名「Volcengine Ark」「MiniMax」「Doubao TTS」；冒号后半角空格。

## 范围边界

- **本子计划改**：
  - 后端：
    - `render/providers/seedance.py`（错误映射）、`minimax.py`、`fake.py`、`base.py`（仅 B 节文案与日志）；
    - `render/providers/tts_base.py`、`tts_volc.py`、`fake.py` 的 `FakeTts`、`providers/__init__.py` 的 `get_tts`；
    - `render/voice.py`、`render/mix.py`、`render/export_fcpxml.py`；
    - `render/session.py` 的合成部分（`COMPOSE_INTERRUPTED`、`_fail_interrupted_compose`、`begin_compose`、`compose_progress`、`compose_done`、`compose_failed`）与 `settings` 校验里的 `film.settings.no_model`；
    - `render/runner.py`（仅 `film.submit.crashed` 改参数、写日志）；
    - `server/app.py`：`_render_ctx`（去掉 `structured` 开关）、`_legacy_render_call`（删除）、`_tts`、`_session_or_404`、`render_voices`、`render_voices_put`、`_compose_preview`、`_NO_FFMPEG`、`_EXPORT_REASONS`、`_compose_blockers`、`_compose_quote`、`_compose_start`、`_export_check`、`render_compose_get`、`render_export`、`_compose_worker`、`render_compose_post`、`render_bgm_put`、`render_bgm_delete`；
    - `server/messages.py` 登记表、`messages_codes.json`；
    - `tests/server/test_i18n_scan.py` 的 `MODULES`。
  - 前端：`i18n/zh.ts`、`en.ts`（`srv` 节点与 `compose.ffmpegHint`）、`types.ts`、`api.ts`（导出带 `lang`）、`compose.ts`、`components/ComposePanel.tsx`，以及显示配音费率说明、说话人名的地方。
- **不改（后续子计划）**：账号、小说、管理（子计划 3）；验证门 `_render_gate`/`_gate_status`、转换任务、助手（子计划 4）；验证报告（子计划 5）。助手调用 `_compose_start` 的路径只要求不坏（错误形状变化见实施裁定 R6）。
- 关键帧（`render/keyframes.py`、`/render/keyframes`）不在范围内。

## 文件结构

| 文件 | 本计划的改动 |
|---|---|
| `backend/server/messages.py` | 新登记 `film.ark.*`（6 个映射代码）、`tts.*`、`voice.*`、`compose.*`、`export.*`、`rate.volc_tts`、`rate.fake_tts`；按 spec B 改现有代码文案与参数 |
| `backend/render/providers/seedance.py` | `_ARK_CODES` 映射表、`_ark_code()`、`_reject`/`_call` 429 分支/`poll` 走映射；`logging` 记原文 |
| `backend/render/providers/minimax.py`、`fake.py`、`runner.py`、`session.py` | spec B 的参数调整与日志 |
| `backend/render/providers/tts_base.py`、`tts_volc.py`、`fake.py`、`__init__.py` | TTS 错误带代码；`BilledError.of` 可用；`rate_note` 改消息对象；`get_tts` 未知名抛带代码的 `KeyError` 子类 |
| `backend/render/voice.py` | `VoiceError` 混入 `UserError`；失败条带 `error_msg`；说话人名改代码 |
| `backend/render/mix.py` | `MixError` 混入 `UserError`；进度 `say()` 收消息对象；报告 `alignment`/`warning` 改消息对象 |
| `backend/render/export_fcpxml.py` | `ExportError` 混入 `UserError`；`readme(lang=)`；`export(lang=)` 与文件名 |
| `backend/render/session.py` | 合成状态 `step_msg`/`error_msg`；合成 `Conflict`/`BudgetExceeded` 带代码 |
| `backend/server/app.py` | 上列接口改用 `_render_call`/`to_detail`/`msg`；`?lang` |
| `backend/tests/render/test_seedance.py` 等 | 见各 Task |
| `frontend/src/compose.ts`、`ComposePanel.tsx`、`types.ts`、`api.ts` | 合成进度、失败、报告、费率说明、说话人名用 `formatMsg`；导出带 `lang` |
| `frontend/tests/compose.test.tsx`、`server-msg.test.ts` | 代码渲染与切换语言用例 |

---

### Task 1: 方舟错误码友好映射（spec A）

**Files:**
- Modify: `backend/render/providers/seedance.py`（`_reject` 约 :60-75、`_call` 约 :115-140、`poll` 约 :163-182）
- Modify: `backend/server/messages.py`（`film.ark.*` 段）、`backend/server/messages_codes.json`
- Modify: `frontend/src/i18n/zh.ts`、`en.ts`（`srv.film.ark`）
- Test: `backend/tests/render/test_seedance.py`

- [ ] **Step 1: 写失败测试**（`test_seedance.py` 末尾、`ALL PASS` 之前新增一节；照文件里现有的 `MockTransport` 夹具写法）

  覆盖（每条断言 `e.code` 与 `str(e)`，不联网）：
  1. 提交返回 401 `{"error":{"code":"AuthenticationError","message":"The API key ... sk-test..."}}` → `ProviderError`，`code == "film.ark.auth"`，`str(e)` 是新中文兜底，**不含**密钥与厂商原文。
  2. 403 `AccountOverdueError` → `film.ark.overdue`；403 `AccessDenied` → `film.ark.access_denied`；403 `InvalidAccountStatus` → `film.ark.access_denied`。
  3. 404 `InvalidEndpointOrModel.NotFound`、404 `InvalidEndpointOrModel.ModelIDAccessDisabled`、404 `ModelNotOpen` → `film.ark.model_unavailable`。
  4. 403 `QuotaExceeded` → `film.ark.quota`。
  5. **429 `SetLimitExceeded`**（提交与查询各一次）→ `ProviderError`（不是 `TransientError`、不是 `AmbiguousSubmit`），`code == "film.ark.limit_paused"`。
  6. 429 `RateLimitExceeded.EndpointRPMExceeded`、429 `ServerOverloaded`、429 `RequestBurstTooFast`、429 无 JSON → 仍是 `TransientError`，`code == "film.ark.throttled"`。
  7. 400 `SensitiveContentDetected.Violence`、400 `InputTextSensitiveContentDetected`、400 `InputImageSensitiveContentDetected`、400 `InputTextRiskDetection` → `film.ark.input_moderated`。
  8. 400 `SensitiveContentDetected.PolicyViolation`、400 `InputTextSensitiveContentDetected.PolicyViolation` → `film.ark.copyright`（全名优先于族名）。
  9. `poll` 返回 `{"status":"failed","error":{"code":"OutputVideoSensitiveContentDetected","message":"..."}}` → `TaskState.error_msg["code"] == "film.ark.output_moderated"`，`TaskState.error` 等于该代码的中文兜底；`OutputAudioSensitiveContentDetected` 同。
  10. 未映射：400 `InvalidParameter` 带 message → 仍是 `film.provider.rejected`，vendor 参数为脱敏原文（与现在一致）；400 无 code 无 message 的 JSON → `film.provider.rejected`/`http_rejected` 行为不变；401 非 JSON 体 → `film.ark.auth`（HTTP 回落）；403 非 JSON 体 → `film.ark.access_denied`；418 非 JSON 体 → `film.provider.http_rejected`。
  11. 日志：命中映射时，`logging.getLogger("render.providers.seedance")` 收到一条 WARNING，内容含方舟 code 与 HTTP 状态，**不含**测试密钥。收集写法：

  ```python
  class _Grab(logging.Handler):
      def __init__(self):
          super().__init__()
          self.lines = []
      def emit(self, rec):
          self.lines.append(rec.getMessage())

  grab = _Grab()
  lg = logging.getLogger("render.providers.seedance")
  lg.addHandler(grab)
  try:
      ...  # 触发 401
  finally:
      lg.removeHandler(grab)
  assert any("AuthenticationError" in x and "401" in x for x in grab.lines), grab.lines
  assert not any(KEY in x for x in grab.lines)
  ```

- [ ] **Step 2: 运行确认失败**：`cd backend && .venv/bin/python tests/render/test_seedance.py`，应在新增节失败（`KeyError: film.ark.auth` 或断言不等）。

- [ ] **Step 3: 登记代码**（`messages.py` 的 `film.ark.*` 段；中文以 spec A 表为准）

  ```python
  register("film.ark.auth", "视频服务（方舟）鉴权失败，请联系管理员")
  register("film.ark.overdue", "视频服务（方舟）账户欠费，暂时无法出片，请联系管理员")
  register("film.ark.access_denied", "视频服务（方舟）拒绝访问，请联系管理员")
  register("film.ark.model_unavailable", "所选的视频档位暂时不可用（模型未开通），请换一个档位或联系管理员")
  register("film.ark.limit_paused", "视频服务（方舟）已达到用量上限并暂停，请联系管理员")
  register("film.ark.quota", "视频服务（方舟）额度已用尽，请联系管理员")
  register("film.ark.input_moderated", "这一段的画面描述或参考图没通过内容审核：改写描述或换参考图后重试")
  register("film.ark.copyright", "这一段的描述可能涉及版权限制：改写后重试")
  register("film.ark.output_moderated", "生成的视频没通过内容审核：调整这一段的描述后重试")
  ```
  `film.ark.throttled` 的文案改动放在 Task 2（B 节统一改），本 Task 只改映射。

- [ ] **Step 4: 实现映射**（`seedance.py`）

  ```python
  import logging
  log = logging.getLogger("render.providers.seedance")

  # 方舟错误码 → 我们的代码（官方错误码页 https://www.volcengine.com/docs/82379/1299023）。
  # 先全名、再族名（第一个「.」之前）；Input*/Output* + SensitiveContentDetected 按前缀归类。
  _ARK_EXACT = {
      "SensitiveContentDetected.PolicyViolation": "film.ark.copyright",
      "InputTextSensitiveContentDetected.PolicyViolation": "film.ark.copyright",
  }
  _ARK_FAMILY = {
      "AuthenticationError": "film.ark.auth", "InvalidSubscription": "film.ark.auth",
      "AccountOverdueError": "film.ark.overdue",
      "AccessDenied": "film.ark.access_denied", "InvalidAccountStatus": "film.ark.access_denied",
      "InvalidEndpointOrModel": "film.ark.model_unavailable", "ModelNotOpen": "film.ark.model_unavailable",
      "SetLimitExceeded": "film.ark.limit_paused",
      "QuotaExceeded": "film.ark.quota",
      "SensitiveContentDetected": "film.ark.input_moderated",
      "InputTextRiskDetection": "film.ark.input_moderated",
  }
  _ARK_HTTP = {401: "film.ark.auth", 403: "film.ark.access_denied"}
  _ARK_THROTTLE = ("RateLimitExceeded", "ServerOverloaded", "RequestBurstTooFast")


  def _ark_code(code) -> Optional[str]:
      if not isinstance(code, str) or not code:
          return None
      if code in _ARK_EXACT:
          return _ARK_EXACT[code]
      fam = code.split(".", 1)[0]
      if fam in _ARK_FAMILY:
          return _ARK_FAMILY[fam]
      if fam.endswith("SensitiveContentDetected"):
          if fam.startswith("Input"):
              return "film.ark.input_moderated"
          if fam.startswith("Output"):
              return "film.ark.output_moderated"
      return None


  def _err_body(r: httpx.Response) -> Optional[dict]:
      """响应体里的 error 对象；不是 JSON 或没有为 None。"""
      try:
          j = r.json()
      except ValueError:
          return None
      err = (j or {}).get("error") if isinstance(j, dict) else None
      return err if isinstance(err, dict) else None


  def _mapped(our: str, status, err: dict, key: str) -> ProviderError:
      parts = [str(x) for x in (err.get("code"), err.get("message")) if x]
      log.warning("方舟错误 HTTP %s：%s", status, scrub(": ".join(parts), key))  # i18n: internal
      return ProviderError.of(our)
  ```

  - `_reject(r, key)`：先 `err = _err_body(r)`；`our = _ark_code((err or {}).get("code")) or (None if err and (err.get("code") or err.get("message")) else _ARK_HTTP.get(r.status_code))`；`our` 有值就 `return _mapped(our, r.status_code, err or {}, key)`；否则走现有逻辑（不改）。
  - `_call` 的 429 分支：`err = _err_body(r)`；`our = _ark_code((err or {}).get("code"))`；若 `our` 存在且 `our != "film.ark.throttled"`（即命中非限流映射，如 `SetLimitExceeded`）→ `raise _mapped(our, 429, err, self._key)`；否则照旧 `raise TransientError.of("film.ark.throttled")`。`_ARK_THROTTLE` 族不进 `_ARK_FAMILY`，自然落到瞬时分支；保留 `_ARK_THROTTLE` 常量只用于注释与测试可读性（或删去，二选一，保持简洁）。
  - `poll` 的 `failed` 分支：先 `our = _ark_code(err.get("code"))`；命中时 `m = msg(our)`，并 `log.warning`（同 `_mapped` 的内容，状态写 `task`）；未命中走现有逻辑。命中时 `error = m["message"]`（中文兜底改为映射文案，见 spec A「中文兜底」）。

- [ ] **Step 5: 前端文案**：`zh.ts`、`en.ts` 的 `srv.film.ark` 下加 9 个键。zh 与登记的中文一字不差（`srv-codes` 会校验）；en 示例：
  - `auth`: `'The video service (Volcengine Ark) rejected our credentials. Please contact the administrator.'`
  - `overdue`: `'The video service (Volcengine Ark) account is overdue, so clips can't be generated right now. Please contact the administrator.'`
  - `access_denied`: `'The video service (Volcengine Ark) denied access. Please contact the administrator.'`
  - `model_unavailable`: `'The selected video tier isn't available right now (model not activated). Pick another tier or contact the administrator.'`
  - `limit_paused`: `'The video service (Volcengine Ark) hit its usage limit and is paused. Please contact the administrator.'`
  - `quota`: `'The video service (Volcengine Ark) has used up its quota. Please contact the administrator.'`
  - `input_moderated`: `'This segment's description or reference images didn't pass content review. Rewrite the description or swap the references, then retry.'`
  - `copyright`: `'This segment's description may raise copyright concerns. Rewrite it and retry.'`
  - `output_moderated`: `'The generated video didn't pass content review. Adjust this segment's description and retry.'`

- [ ] **Step 6: 生成 JSON、跑全部校验**（见全局约束）。
- [ ] **Step 7: 提交**：`git add backend/render/providers/seedance.py backend/server/messages.py backend/server/messages_codes.json backend/tests/render/test_seedance.py frontend/src/i18n/zh.ts frontend/src/i18n/en.ts`，提交信息示例：「方舟错误码映射为友好代码：鉴权、欠费、拒绝访问、模型未开通、用量上限、额度、输入与输出审核、版权各有文案，SetLimitExceeded 这一个 429 不再重试，原文脱敏后进日志；未映射的照旧带厂商原文」。

---

### Task 2: 面向最终用户的文案（spec B，视频厂商与出片部分）

**Files:**
- Modify: `backend/server/messages.py`、`messages_codes.json`
- Modify: `backend/render/providers/seedance.py`、`minimax.py`、`fake.py`、`backend/render/session.py`（`film.settings.no_model` 调用点）、`backend/render/runner.py`（`film.submit.crashed` 调用点）、`backend/render/providers/base.py`（若 `submit_cut`/`download_connect` 在此构造）
- Modify: `frontend/src/i18n/zh.ts`、`en.ts`
- Test: `backend/tests/render/test_seedance.py`、`test_minimax.py`、`test_providers.py`、`test_session.py`、`test_runner.py`、`backend/tests/server/test_messages.py`、`frontend/tests/server-msg.test.ts`

- [ ] **Step 1: 列出调用点**：`cd backend && grep -rn "film.ark.no_key\|film.minimax.no_key\|film.minimax.invalid_key\|film.minimax.insufficient_balance\|film.minimax.moderated\|unknown_model\|film.settings.no_model\|film.minimax.bad_resolution\|connect_failed\|film.provider.submit_cut\|film.provider.download_connect\|film.submit.crashed\|not_json\|no_task_id\|film.ark.throttled" render server tests`。每个调用点都要在本 Task 里改到。

- [ ] **Step 2: 改测试为新期望（先失败）**：
  - 现有断言这些代码 `params` 的用例改为新参数（例如 `connect_failed` 不再有 `kind`，`unknown_model` 不再有 `model`）。
  - 新增日志断言（复用 Task 1 的 `_Grab` 写法，挂在对应模块 logger 上）：
    - `Seedance.from_env()` 无密钥（`_load_dotenv` 换空操作、清掉 `ARK_API_KEY`）→ `film.ark.no_key`，日志含 `ARK_API_KEY`；MiniMax 同理含 `MINIMAX_API_KEY`。
    - Seedance 未知档位 → `film.ark.unknown_model`，日志含档位 id；MiniMax、fake、`film.settings.no_model` 同理（settings 的日志含 provider 与 model）。
    - 连接失败（`MockTransport` 抛 `httpx.ConnectError`）→ `connect_failed`，日志含 `ConnectError`。
    - runner 提交时意外异常 → `film.submit.crashed`，日志含异常类名与原因。
  - `test_messages.py`：断言这些代码的参数清单（如 `dump_codes()["film.ark.connect_failed"]["params"] == []`）。
  - `frontend/tests/server-msg.test.ts`：新增「旧会话带多余参数」用例：`formatMsg({code:'film.ark.connect_failed', params:{kind:'ConnectError'}}, 'en')` 渲染为新英文模板，不报错、不出现 `{kind}`。

- [ ] **Step 3: 改登记表**（中文照 spec B 表；没列出的保持不变）：

  ```python
  register("film.ark.no_key", "视频服务（方舟）还没有配置，请联系管理员")
  register("film.minimax.no_key", "视频服务（MiniMax）还没有配置，请联系管理员")
  register("film.minimax.invalid_key", "视频服务（MiniMax）鉴权失败，请联系管理员")
  register("film.minimax.insufficient_balance", "视频服务（MiniMax）账户余额不足，暂时无法出片，请联系管理员")
  register("film.minimax.moderated", "这一段的画面描述或参考图没通过内容审核：改写描述或换参考图后重试")
  register("film.ark.unknown_model", "所选的视频档位已不可用，请在出片设置里重新选择")
  register("film.minimax.unknown_model", "所选的视频档位已不可用，请在出片设置里重新选择")
  register("film.fake.unknown_model", "所选的视频档位已不可用，请在出片设置里重新选择")
  register("film.settings.no_model", "所选的视频档位已不可用，请在出片设置里重新选择")
  register("film.minimax.bad_resolution", "这个档位不支持 {resolution}，可选：{options}")
  register("film.ark.connect_failed", "连接视频服务（方舟）失败，稍后自动重试")
  register("film.minimax.connect_failed", "连接视频服务（MiniMax）失败，稍后自动重试")
  register("film.provider.submit_cut", "提交时连接中断，结果不明")
  register("film.provider.download_connect", "下载视频时连接失败")
  register("film.submit.crashed", "提交时出现意外错误，请重试；仍失败请联系管理员")
  register("film.ark.not_json", "视频服务（方舟）返回了无法识别的响应")
  register("film.minimax.not_json", "视频服务（MiniMax）返回了无法识别的响应")
  register("film.ark.no_task_id", "视频服务（方舟）受理了请求却没有返回任务编号")
  register("film.minimax.no_task_id", "视频服务（MiniMax）受理了请求却没有返回任务编号")
  register("film.ark.throttled", "视频服务（方舟）繁忙，稍后自动重试")
  ```

- [ ] **Step 4: 改调用点并写日志**：每个模块顶部 `log = logging.getLogger("<模块点分路径>")`（`render.providers.seedance`、`render.providers.minimax`、`render.providers.fake`、`render.session`、`render.runner`）。被拿掉的参数改写进 `log.warning(...)`，再 `raise X.of(code)`。日志文字是内部文字，行尾加 `# i18n: internal`（防扫描器误报；`log.warning` 本身不是出口，但带中文 f-string 时保险起见加上）。
  - `film.submit.crashed`：runner 现在的 `traceback` 输出保留；新增的 `log.warning` 只写 `kind` 与 `cause` 的原文（已脱敏的那份）。
  - **文字变化**：以上代码的中文兜底按 spec 改变，相关测试的中文断言同步改。

- [ ] **Step 5: 前端文案**：`zh.ts` 对应键改为与登记一致；`en.ts` 同步（示例：`no_key` → `'The video service (Volcengine Ark) isn't set up yet. Please contact the administrator.'`；`unknown_model` 系列 → `'The selected video tier is no longer available. Pick another one in film settings.'`；`connect_failed` → `'Couldn't reach the video service (MiniMax). Retrying shortly.'`；`submit.crashed` → `'Something went wrong while submitting. Please retry; if it keeps failing, contact the administrator.'`）。`srv-codes` 会校验占位符与参数一致，删掉的 `{kind}`/`{model}`/`{provider}`/`{cause}` 在 zh、en 两边都要去掉。

- [ ] **Step 6: 跑全部校验并提交**：只 add 上面列出的文件。提交信息示例：「出片报错改为面向最终用户：未配置、鉴权、余额、审核、档位失效、连接失败、意外异常等文案不再出现环境变量名、异常类名与内部档位 id，这些细节改写进后端日志；补日志断言与旧会话多余参数的渲染用例」。

---

### Task 3: 配音厂商与音色（TTS、voice、音色接口）

**Files:**
- Modify: `backend/render/providers/tts_base.py`（`BilledError`、拼接参数不一致）、`tts_volc.py`、`fake.py`（`FakeTts`）、`providers/__init__.py`（`get_tts`）
- Modify: `backend/render/voice.py`（`VoiceError`、`speakers`、`synthesize` 失败条）
- Modify: `backend/server/app.py`：`_tts`、`_session_or_404`、`render_voices`、`render_voices_put`
- Modify: `backend/server/messages.py`、`messages_codes.json`
- Modify: `backend/tests/server/test_i18n_scan.py`（`MODULES` 加 `render/providers/tts_base.py`、`render/providers/tts_volc.py`、`render/voice.py`，app 函数集合加 `_tts`、`_session_or_404`、`render_voices`、`render_voices_put`）
- Modify: `frontend/src/types.ts`（`VoicesInfo.rate_note: MsgLike`、`VoiceSpeaker.name: MsgLike`）、`compose.ts`（`speakerName`）、`ComposePanel.tsx`（费率说明、说话人名）、`zh.ts`、`en.ts`
- Test: `backend/tests/render/test_tts.py`、`test_tts_volc.py`、`test_voice.py`、`backend/tests/server/test_render.py`、`frontend/tests/compose.test.tsx`

- [ ] **Step 1: 写失败测试**：
  - `test_tts_volc.py`：
    - 无密钥构造 → `ProviderError`，`code == "tts.volc.no_key"`，`str(e)` 为「配音服务还没有配置，请联系管理员」；日志（`render.providers.tts_volc`）含 `VOLC_TTS_API_KEY`。
    - 429/5xx → `TransientError` `tts.volc.unavailable`（params `status`）。
    - 4xx JSON 带 code/message → `ProviderError` `tts.volc.rejected`，params `code`（字符串化）与 `detail`（vendor，脱敏）；4xx 无 message → `tts.volc.rejected_http`（params `status`）。
    - 流中非 JSON / 非对象 / 合成失败码 / 音频无法解码 / 中途断开 / 不完整 → `BilledError`，各自代码（见 Step 3），`billed_cny` 不变。
    - 连接失败 → `TransientError` `tts.volc.connect_failed`（无参数，日志含异常类名）。
  - `test_tts.py`（`FakeTts`、`tts_base`）：`fail_with="x"` → `ProviderError` 且 `code == "tts.fake.failed"`（params `detail` 为 vendor("x")）；限流 → `tts.fake.throttled`；未知音色 → `tts.unknown_voice`（params `voice`）；`concat_wavs` 参数不一致 → `tts.concat_mismatch`；`get_tts("nope")` → 抛 `KeyError` 子类，`code == "tts.unknown_provider"`，`except KeyError` 照样接得住；`FakeTts.rate_note == {"code": "rate.fake_tts", "params": {}}`，`VolcTts.rate_note == {"code": "rate.volc_tts", "params": {}}`。
  - `test_voice.py`：会话目录不存在 → `VoiceError` `film.session.dir_gone`（R3）；`synthesize` 失败条除 `error`（中文兜底，与现在一致）外多一个 `error_msg`（`cause_of(e)` 的结果：带代码时为 `{code, params}`，否则 vendor）；`speakers(doc)[NARRATION]["name"] == {"code": "voice.narrator", "params": {}}`，角色名仍是字符串。
  - `test_render.py`：`/voices` 在 TTS 未配置时 422 的 detail 是消息对象（`code == "tts.volc.no_key"`）；`PUT /voices` 未知音色 422 → `{code: "tts.unknown_voice_list", params: {voices: [...]}}`；没有会话 404 → `film.session.none`（R3）；`speakers[].name` 对旁白为消息对象、未标说话人（空 key）为 `{"code": "voice.unlabeled", ...}`。
  - `compose.test.tsx`：英文界面下费率说明、旁白名、未标说话人显示英文；`speakerName` 对消息对象调用 `formatMsg`。

- [ ] **Step 2: 运行确认失败。**

- [ ] **Step 3: 登记代码**（中文兜底与现有字符串一字不差，B 节要求改的除外）：

  ```python
  register("rate.volc_tts", "2026-10 火山引擎豆包语音合成 2.0 后付费刊例价（3 元/万字符），未经账单核对")
  register("rate.fake_tts", "假配音：不联网、不花钱，金额只用于演示")
  register("tts.unknown_provider", "未知的配音厂商：{name}")
  register("tts.unknown_voice", "未知的音色：{voice}")
  register("tts.unknown_voice_list", "没有这个音色：{voices}")
  register("tts.concat_mismatch", "拼接的语音片段参数不一致")
  register("tts.fake.failed", "{detail}")
  register("tts.fake.throttled", "假的限流")
  register("tts.volc.no_key", "配音服务还没有配置，请联系管理员")
  register("tts.volc.unavailable", "豆包语音暂时不可用（HTTP {status}）")
  register("tts.volc.rejected", "豆包语音拒绝了请求（{code}）：{detail}")
  register("tts.volc.rejected_http", "豆包语音拒绝了请求（HTTP {status}）")
  register("tts.volc.not_json", "豆包语音返回的不是 JSON")
  register("tts.volc.not_object", "豆包语音返回的不是 JSON 对象")
  register("tts.volc.failed", "豆包语音合成失败（{code}）")
  register("tts.volc.failed_detail", "豆包语音合成失败（{code}）：{detail}")
  register("tts.volc.bad_audio", "豆包语音返回的音频无法解码")
  register("tts.volc.cut", "豆包语音中途断开")
  register("tts.volc.connect_failed", "连接豆包语音失败，稍后自动重试")
  register("tts.volc.incomplete", "豆包语音没有返回完整的音频")
  register("voice.narrator", "旁白")
  register("voice.unlabeled", "（未标说话人）")
  ```
  - `{voices}` 传列表，`_zh_value` 用「、」连接，与原 `'、'.join(bad)` 一致。
  - **文字变化**：`tts.volc.no_key`、`tts.volc.connect_failed`、`tts.volc.cut`（去掉异常类名，类名进日志）按 spec B 改；其余与现在一致。

- [ ] **Step 4: 实现**：
  - `tts_base.BilledError` 继承的 `ProviderError` 已混入 `UserError`（`render/providers/base.py:17`），不用再改类定义。构造写 `BilledError.of(code, billed_cny, **params)`：`UserError.of` 以 `cls(message, *args)` 构造，`__init__(message, billed_cny)` 正好接住，`e.billed_cny` 保留。`VolcTts._billed(message, text)` 改为 `_billed(code, text, **params)`，内部调用上面的写法。
  - `get_tts`：在 `providers/__init__.py` 定义 `class UnknownTts(UserError, KeyError)`，`raise UnknownTts.of("tts.unknown_provider", name=name)`。注意 `KeyError.__str__` 会给 `args[0]` 加引号——`to_detail` 走 `as_msg()`，不受影响；`_raw_text` 已处理 KeyError。
  - `rate_note` 改为 `{"code": "rate.volc_tts", "params": {}}` / `{"code": "rate.fake_tts", "params": {}}`（与视频厂商同形，直接放类属性）。
  - `voice.speakers`：旁白 `name` 为 `compact(msg("voice.narrator"))`。`render_voices` 里 `"（未标说话人）"` 兜底改为 `compact(msg("voice.unlabeled"))`。
  - `voice.synthesize` 失败条：`failed.append({**line, "error": str(e), "error_msg": cause_of(e)})`。
  - `app._tts`：`except KeyError as e` 与 `except ProviderError as e` 都改 `raise HTTPException(422, detail=to_detail(e))`。
  - `app._session_or_404`：改 `detail=msg("film.session.none")`（R3）。
  - `render_voices_put`：未知音色 `detail=msg("tts.unknown_voice_list", voices=bad)`；`_legacy_render_call(render_session.set_voices, …)` 改 `_render_call(...)`。
  - 前端：`types.ts` 两处类型改 `MsgLike`；`speakerName` 返回 `formatMsg(name)`（name 为字符串时原样）；`ComposePanel.tsx:111` 的 `v.rate_note || …` 改为 `v.rate_note ? formatMsg(v.rate_note) : t('money.rateUnknown')`；`ComposePanel.tsx:253` 的 `rateNote` 若组件已接受 `MsgLike`（子计划 1 的 `MoneyConfirm`）则直接传对象。
  - `zh.ts`/`en.ts` 加 `srv.tts.*`、`srv.voice.*`、`srv.rate.volc_tts`、`srv.rate.fake_tts`。en 示例：`voice.narrator` → `'Narrator'`，`voice.unlabeled` → `'(no speaker)'`，`tts.volc.no_key` → `'The voice service isn't set up yet. Please contact the administrator.'`。

- [ ] **Step 5: 去掉本 Task 范围内的 `# i18n: todo(2)`**：`render/providers/fake.py:85`、`:100`、`:105`、`:107`，`render/providers/__init__.py:121`。`grep -n "todo(2)" render/providers` 应为空。
- [ ] **Step 6: 跑全部校验并提交**（只 add 本 Task 列出的文件）。提交信息示例：「配音厂商与音色接口带代码：豆包语音与假配音的报错、未知音色与厂商、费率说明、旁白与未标说话人改为消息对象；未配置提示不再出现环境变量名；合成失败条附 error_msg；前端费率说明与说话人名按界面语言渲染」。

---

### Task 4: 合成过程（mix 与会话里的合成状态）

**Files:**
- Modify: `backend/render/mix.py`（`MixError`、`compose` 的 `say`、报告）
- Modify: `backend/render/session.py`（`COMPOSE_INTERRUPTED`、`_fail_interrupted_compose`、`begin_compose`、`compose_progress`、`compose_done`、`compose_failed`）
- Modify: `backend/server/messages.py`、`messages_codes.json`
- Modify: `backend/tests/server/test_i18n_scan.py`（`MODULES` 加 `render/mix.py`）
- Test: `backend/tests/render/test_mix.py`、`test_mix_e2e.py`（若断言了中文 step/报告）、`test_session.py`

- [ ] **Step 1: 写失败测试**：
  - `test_mix.py`：
    - `run()` 失败 → `MixError` `compose.ffmpeg_failed`，params `what`（嵌套消息，如 `compose.step.normalize` 带 `id`）与 `rc`；`e.stderr` 不变。
    - 非草稿缺视频 → `compose.no_video`（params `id`）；缺音色 → `compose.missing_voices`（params `speakers`：列表，空 key 换成 `compact(msg("voice.unlabeled"))`）；有语音条失败 → `compose.lines_failed`（params `items`：最多 5 条，每条 `{"code": "compose.line_failed", "params": {"id": …, "cause": <失败条的 error_msg>}}`）；`VoiceError` → `MixError` `compose.voice_failed`，params `cause` 为 `film.session.dir_gone` 的紧凑消息（R4）。
    - `progress` 回调收到的是消息对象（`{code, params, message}`），依次为 `compose.step.voice`（`n`）、`compose.step.normalize`（`id`）、`compose.step.concat`（`id`）、`compose.step.mix`（`id`）。
    - 报告 `alignment == {"code": "compose.alignment", "params": {}}`；`dialogue_native` 时 `warning == {"code": "compose.warning_native", "params": {}}`。
  - `test_session.py`：
    - `begin_compose` 正在合成 → `Conflict` `compose.busy`；音色改过 → `Conflict` `compose.voices_changed`（`expected_cny` 仍为 None）；有段在跑 → `compose.clips_busy`；超预算 → `BudgetExceeded` `compose.over_budget`（params `budget`、`spent`、`cost` 为 `money(...)`；中文兜底与原字符串一字不差：`超出上限 ¥{budget:g}…` 注意原文 `budget` 用 `:g` 而 `money` 统一两位小数——**文字变化**：预算显示由 `¥200` 变为 `¥200.00`，测试同步改）。
    - `begin_compose` 后 `final["step"] == "开始"` 且 `final["step_msg"] == {"code": "compose.step.start", "params": {}}`；`compose_progress(root, m)` 写 `step`（中文兜底）与 `step_msg`；`compose_done` 写 `step_msg` 为 `compose.step.done`、`error_msg` 为 None。
    - `compose_failed(root, err, detail)`：`err` 为消息对象或带代码异常时经 `set_error(final, err)` 写入 `error` 与 `error_msg`；为字符串时只写 `error`（旧行为）。
    - `recover_compose` 把进行中的合成标失败：`final["error_msg"] == {"code": "compose.interrupted", "params": {}}`，`error` 为原中文。

- [ ] **Step 2: 运行确认失败。**

- [ ] **Step 3: 登记**（中文兜底与现在一致，除注明的预算格式）：

  ```python
  register("compose.interrupted", "合成时服务中断，请重新合成（已合成的配音与已规整的片段会复用）")
  register("compose.busy", "正在合成，等它结束再合成")
  register("compose.voices_changed", "音色刚被改过，请重新确认金额")
  register("compose.clips_busy", "有段在排队或生成中，等它们结束再合成")
  register("compose.over_budget", "超出上限 {budget}：已花 {spent}，本次配音约 {cost}")
  register("compose.step.start", "开始")
  register("compose.step.voice", "配音 {n} 条")
  register("compose.step.normalize", "规整 {id}")
  register("compose.step.concat", "拼接 {id}")
  register("compose.step.mix", "混音 {id}")
  register("compose.step.done", "完成")
  register("compose.ffmpeg_failed", "{what} 失败（ffmpeg 退出码 {rc}）")
  register("compose.no_video", "{id} 还没有可用的视频；打开「草稿合成」可用关键帧补位")
  register("compose.missing_voices", "还有说话人没选音色：{speakers}")
  register("compose.line_failed", "{id}：{cause}")
  register("compose.lines_failed", "有语音条合成失败，为免成片漏句已停止合成：{items}")
  register("compose.voice_failed", "{cause}")
  register("compose.alignment", "段内镜头切换时刻由视频模型决定，台词按计划镜头起点放置，属近似对齐")
  register("compose.warning_native", "台词由视频模型生成，不保证逐字")
  ```
  - **文字变化**：
    - `compose.ffmpeg_failed`：原文 `f"{what}失败"` 里 `what` 带尾空格（`"规整 E01-C01 "`），现在 `{what} 失败`，渲染结果相同（尾空格移进模板）。
    - `compose.lines_failed` 的 `{items}` 是列表，`_zh_value` 用「、」连接，原文用「；」。**改为「、」**，测试同步（或在实施裁定 R5 允许的范围内保持原分隔：二者择一，选「、」以免给 `_zh_value` 加特例）。
    - 预算金额两位小数（见上）。

- [ ] **Step 4: 实现**：
  - `class MixError(UserError, Exception)`，`__init__(self, message, stderr="")` 不变，`.of(code, stderr, **params)` 可用（`stderr` 走位置参数）。
  - `compose()` 里 `say(msg("compose.step.voice", n=len(lines)))` 等；`run(cmd, what)` 的 `what` 改收消息对象（`compact(msg("compose.step.normalize", id=c["id"]))`），失败时 `MixError.of("compose.ffmpeg_failed", stderr, what=what, rc=r.returncode)`。
  - 报告 `alignment`/`warning` 写 `compact(msg(...))`。`mix_report.json` 里存的就是对象（旧报告是字符串，前端两种都认，见 Task 5）。
  - `session.py`：
    - 删除 `COMPOSE_INTERRUPTED` 常量（或保留为 `msg("compose.interrupted")` 的调用，不再是中文字面量）；`_fail_interrupted_compose` 用 `set_error(f, msg("compose.interrupted"))`。
    - `begin_compose` 的三个 `Conflict` 与 `BudgetExceeded` 改 `.of(...)`；音色改过写 `Conflict.of("compose.voices_changed")`（R11，`e.expected_cny` 默认即 None）。
    - `final` 初值加 `"step_msg": compact(msg("compose.step.start"))`、`"error_msg": None`；`step` 仍写中文兜底。
    - `compose_progress(root, step)`：`step` 可为消息对象或字符串；对象时 `f["step"] = step["message"]`、`f["step_msg"] = compact(step)`；字符串时只写 `step`、`step_msg = None`。
    - `compose_done`：`step="完成"` 改为写 `compose.step.done` 的兜底与 `step_msg`，`set_error(f, None)`。
    - `compose_failed(root, error, detail="")`：`set_error(f, error)`（`set_error` 已兼容消息对象、带代码异常、字符串）。
  - 去掉 `session.py:30/647/681/683/685/687-689/711` 的 `# i18n: todo(2)`；`grep -n "todo(2)" render/session.py` 应为空。

- [ ] **Step 5: 跑全部校验并提交**。提交信息示例：「合成过程带代码：进度、失败原因、报告的对齐说明与原声提示改为消息对象，会话的合成状态新增 step_msg 与 error_msg（旧字段保留中文兜底），合成前的冲突与超预算带代码；ffmpeg 失败的环节名用嵌套消息」。

---

### Task 5: 合成与音色接口、前端合成面板

**Files:**
- Modify: `backend/server/app.py`：`_render_ctx`（删 `structured`）、删除 `_legacy_render_call`、`_compose_preview`、`_NO_FFMPEG`、`_EXPORT_REASONS`、`_compose_blockers`、`_compose_quote`、`_compose_start`、`_export_check`、`render_compose_get`、`_compose_worker`、`render_compose_post`、`render_bgm_put`、`render_bgm_delete`
- Modify: `backend/server/messages.py`、`messages_codes.json`
- Modify: `backend/tests/server/test_i18n_scan.py`（app 函数集合加上述函数）
- Modify: `frontend/src/types.ts`（`FinalState.step_msg?`、`error_msg?`；`MixReport.alignment: MsgLike`、`warning?: MsgLike`）、`compose.ts`（`finalText`）、`components/ComposePanel.tsx`（报告 :207、失败原因）、`zh.ts`/`en.ts`（`srv.compose.*`、`compose.ffmpegHint`）
- Test: `backend/tests/server/test_render.py`（含 14b 改写）、`frontend/tests/compose.test.tsx`

- [ ] **Step 1: 写失败测试**：
  - `test_render.py` **14b 改写**（原「合成与音色接口仍返回字符串」）：标题改为「14b. 合成与音色接口返回消息对象」，断言：
    - `POST R2/compose`（v2 无分镜）→ 422，`detail["code"] == "film.session.no_storyboard"`；`_compose_quote(user, nid, cid, "v2", True)` 同。
    - `PUT R2/voices` 无会话 → 404，`detail["code"] == "film.session.none"`。
    - `PUT R15/voices` 会话文件坏 → 500，`detail["code"] == "film.session.corrupt_admin"`。
  - 新增用例：
    - 合成确认金额对不上 → 409，`detail == {code: "compose.confirm_cny", params: {cost: money(...)}, message: …, expected_cny: <float>}`（`expected_cny` 与消息同层，前端 `conflictCny` 照读）。
    - 没 ffmpeg（把 `render_mix.tools` 换成返回 None）→ 422 `compose.no_ffmpeg`；导出时没 ffmpeg → 503 `export.no_ffmpeg`。
    - 缺音色 → 422 `compose.missing_voices`；非草稿缺视频 → 422 `compose.no_video_count`（params `n`）。
    - 合成中再合成 → 409 `compose.busy`。
    - 导出原因：`none`/`stale`/`no_timeline`/`busy` → 409，`code` 分别为 `export.none`、`export.stale`、`export.no_timeline`、`export.busy`。
    - BGM：未知集 404 `compose.bgm.no_episode`（params `episode`）；类型不对 422 `compose.bgm.bad_type`；空或过大 422 `compose.bgm.too_big`。
    - `_compose_worker`：`MixError` 带代码 → 会话 `final.error_msg["code"]` 等于它，`final.error` 为中文兜底且已 `_hide_root`；意外异常 → `final.error_msg == compact(msg("compose.crashed", kind=…, cause=vendor(…)))`（R7），`traceback` 仍打印。
  - `compose.test.tsx`：
    - `finalText`：运行中有 `step_msg` 时英文界面显示英文步骤；只有 `step` 字符串（旧数据）时原样显示；失败时 `error_msg` 优先，旧数据显示 `error`。
    - 报告 `alignment` 为对象时英文渲染；为字符串（旧报告）时原样。
    - `compose.ffmpegHint` 新文案（zh、en 都不含 `brew`）。

- [ ] **Step 2: 运行确认失败。**

- [ ] **Step 3: 登记**：

  ```python
  register("compose.confirm_cny", "本次配音约 {cost}，请确认金额后再合成")
  register("compose.no_ffmpeg", "服务器缺少视频处理组件 ffmpeg，暂时无法合成，请联系管理员")
  register("compose.no_video_count", "{n} 段还没有可用的视频；打开「草稿合成」可用关键帧补位")
  register("compose.crashed", "合成异常：{kind}: {cause}")
  register("compose.bgm.no_episode", "没有这一集：{episode}")
  register("compose.bgm.bad_type", "BGM 只支持 mp3、wav、m4a、aac")
  register("compose.bgm.too_big", "BGM 文件为空或超过 30MB")
  register("export.none", "还没有合成好的成片")
  register("export.stale", "成片已过期，请先重新合成")
  register("export.no_timeline", "这份成片是旧版合成的，重新合成一次即可导出（会复用已有配音与规整结果，不花钱）")
  register("export.busy", "正在合成，完成后再导出")
  register("export.no_ffmpeg", "服务器缺少视频处理组件 ffmpeg，暂时无法导出，请联系管理员")
  ```
  - **文字变化**：`compose.no_ffmpeg`、`export.no_ffmpeg` 按 spec B 改（安装命令只留在 README 的部署说明里，`grep -n "brew install ffmpeg" README.md` 确认 README 已有，没有就在部署段补一行）。`compose.crashed` 见 R7。

- [ ] **Step 4: 实现**：
  - `_render_ctx` 删 `structured` 参数，统一 `detail=msg("film.session.no_storyboard")`；所有调用点去掉 `structured=False`。
  - 删除 `_legacy_render_call`，调用点改 `_render_call`（`Conflict` 的 409 带 `expected_cny`，形状由 `to_detail(e, expected_cny=e.expected_cny)` 给出，与出片接口一致）。
  - `_NO_FFMPEG`、`_EXPORT_REASONS` 改为代码表：`_EXPORT_REASONS = {"none": "export.none", …}`，抛 `HTTPException(409, detail=msg(_EXPORT_REASONS[reason]))`。
  - `_compose_blockers`：缺音色时 `speakers` 参数同 Task 4（空 key 用 `voice.unlabeled` 嵌套消息）。
  - `_compose_start` 409：`detail={**msg("compose.confirm_cny", cost=money(p["tts_cny"])), "expected_cny": p["tts_cny"]}`。
  - `_compose_worker.failed(err, detail)`：`err` 为异常时先取 `e.as_msg()`；对消息对象的 `message` 与 `params` 里的字符串、vendor 文本做 `_hide_root`（spec §5.2「`_hide_root` 对 params 一并脱敏」；若子计划 1 已有递归脱敏的帮手函数则复用，`grep -n "_hide_root" server/app.py`）；然后 `render_session.compose_failed(root, m, _hide_root(detail))`。
  - 前端：
    - `finalText`：`step` 显示 `f.step_msg ? formatMsg(f.step_msg) : (f.step || tr('compose.stepStart'))`；失败显示 `itemError(f) || tr('compose.unknownReason')`（`itemError` 已实现 `error_msg` 优先、回落 `error`）。
    - `ComposePanel.tsx:207` 的 `r.alignment` 与 warning 改 `formatMsg(...)`（字符串原样）。
    - 合成接口的错误展示照子计划 1 的 `ApiError.detail` + `formatMsg` 方式（`grep -n "errValue\|formatMsg" src/components/ComposePanel.tsx` 看已有用法，没有就照 `FilmPanel.tsx` 改）。
    - `compose.ffmpegHint`（zh、en）改为与 `compose.no_ffmpeg` 同义的面向用户文案。
  - 去掉 `server/app.py:846`、`:875` 的 `# i18n: todo(2)`（随 `structured` 分支与 `_legacy_render_call` 一起消失）。

- [ ] **Step 5: 跑全部校验并提交**。提交信息示例：「合成、音色、BGM 与导出前置检查接口返回消息对象：去掉旧的字符串边界（_legacy_render_call 与 structured 开关），确认金额 409 照旧附重算金额，缺 ffmpeg 改为面向用户的说法；前端合成进度、失败原因与报告按界面语言渲染，旧会话与旧报告的中文原样显示；14b 改为断言代码」。

---

### Task 6: 导出剪辑工程（README 按语言、文件名、导出报错）

**Files:**
- Modify: `backend/render/export_fcpxml.py`（`ExportError`、`readme`、`export`）
- Modify: `backend/server/app.py`：`render_export`（`lang` 查询参数、`ExportError` 走 `to_detail`）
- Modify: `backend/server/messages.py`、`messages_codes.json`
- Modify: `backend/tests/server/test_i18n_scan.py`（`MODULES` 加 `render/export_fcpxml.py`；app 函数集合加 `render_export`）
- Modify: `frontend/src/api.ts`（`exportFcpxml` 带 `lang`）、调用处
- Test: `backend/tests/render/test_export_fcpxml.py`、`backend/tests/server/test_render.py`、`frontend/tests/compose.test.tsx`（或 `film.test.tsx` 中现有的导出用例）

- [ ] **Step 1: 写失败测试**：
  - `test_export_fcpxml.py`：
    - `readme(tl, title)`（不带 `lang`）与现在逐字相同（中英并排）。
    - `readme(tl, title, lang="zh")` 只有中文段、没有 `----` 分隔；`lang="en"` 只有英文段。占位段、补拍素材两类附加行在单语时也出现。
    - `export(root, title=…, tools=…, lang="en")` 产出 `export/<safe>.en.zip`，包里 README 是英文；`lang=None` 产出 `export/<safe>.zip`（与现在一致）；两种语言先后导出互不覆盖。
    - 报错带代码：旧版成片 → `export.no_timeline`；产物缺失 → `export.missing_file`（params `file`）；预渲染配音失败 → `export.voice_prerender`（params `line`），`e.stderr` 不变。
  - `test_render.py`：`GET …/export.zip?lang=en` 的 `Content-Disposition` 文件名以 `.en.zip` 结尾；`?lang=fr` 视同不带（文件名 `.zip`，README 中英并排）；`ExportError` → 409 消息对象，`_hide_root` 后 params 里不含会话目录。
  - 前端：`exportFcpxml` 请求路径带 `?lang=<当前界面语言>`（在已有的 fetch 桩里断言 URL）。

- [ ] **Step 2: 运行确认失败。**

- [ ] **Step 3: 登记**：

  ```python
  register("export.voice_prerender", "预渲染配音 {line} 失败")
  register("export.missing_file", "合成产物缺失（{file}），请重新合成")
  ```
  `export.no_timeline` 已在 Task 5 登记，直接复用。`export_fcpxml.py:86` 的内部 `ValueError` 行尾加 `# i18n: internal`（spec §8 点名）。

- [ ] **Step 4: 实现**：
  - `class ExportError(UserError, Exception)`，`__init__(msg, stderr="")` 不变。
  - `readme(timeline, title, extras=(), lang=None)`：现有 `zh`、`en` 两个列表照旧构造；`lang == "zh"` 返回 `"\n".join(zh) + "\n"`，`"en"` 同理，其它返回原并排格式。README 的中英文就写在这里（它是下载文件内容，不走 `srv` 节点，spec §7）。
  - `export(root, *, title, tools, lang=None)`：`lang` 只认 `"zh"`/`"en"`，其它当 None；文件名 `f"{safe}.{lang}.zip" if lang else f"{safe}.zip"`；`mkstemp` 前缀同步。
  - `render_export(..., lang: Optional[str] = None)`：校验同上，传给 `export`；`except ExportError as e: raise HTTPException(409, detail=<对 to_detail(e) 做 _hide_root 的结果>)`。
  - 前端 `exportFcpxml(nid, cid, vid)` 内部取当前语言（`currentLocale()`，照 `serverMsg.ts` 的用法），请求 `…/export.zip?lang=${locale}`。

- [ ] **Step 5: 跑全部校验并提交**。提交信息示例：「导出剪辑工程按界面语言生成 README，文件名带语言避免中英并发导出互相覆盖，不带语言时保持中英并排与原文件名；导出报错带代码」。

---

### Task 7: 收尾核对

**Files:**
- Modify（如需要）：`backend/tests/server/test_i18n_scan.py`、`README.md`、`backend/server/messages_codes.json`

- [ ] **Step 1: 标记清零**：`cd backend && grep -rn "i18n: todo(2)" --include="*.py" .` 输出为空（spec 计划清单中的 16 处：`server/app.py:846`、`:875`；`render/providers/fake.py:85`、`:100`、`:105`、`:107`；`render/session.py:30`、`:647`、`:681`、`:683`、`:685`、`:687`、`:688`、`:689`、`:711`；`render/providers/__init__.py:121`）。
- [ ] **Step 2: 扫描范围核对**：`test_i18n_scan.py` 的 `MODULES` 至少包含 `render/mix.py`、`render/voice.py`、`render/export_fcpxml.py`、`render/providers/tts_base.py`、`render/providers/tts_volc.py`，app 函数集合包含 Task 3、5、6 列出的全部函数；扫描 `ALL PASS`。
- [ ] **Step 3: 残留中文核对**（扫描器只看错误出口，这里补看其它给用户的字段）：`grep -n '"[^"]*[一-龥]' render/mix.py render/voice.py render/export_fcpxml.py render/providers/tts_*.py`，逐条确认只剩：README 文本（`readme()` 内）、`compose.py` 给模型的提示词、音色显示名（`tts_volc.VOICES`，见 R8）、注释与日志。
- [ ] **Step 4: 开发者口吻核对**：`grep -n "backend/.env\|_API_KEY\|brew install\|apt install" server/messages.py ../frontend/src/i18n/zh.ts ../frontend/src/i18n/en.ts` 输出为空。
- [ ] **Step 5: 代码表最新**：`.venv/bin/python -m server.messages --write && git diff --exit-code server/messages_codes.json`。
- [ ] **Step 6: 全部校验**（全局约束里的整套）。
- [ ] **Step 7: 有改动才提交**（只 add 改到的文件）。提交信息示例：「子计划 2 收尾：清零 todo(2) 标记，扫描覆盖配音、合成与导出模块」。

---

## 实施裁定

- **R1 方舟原文去向**：命中映射时界面不带厂商原文，原文只进日志（与 MiniMax 已知错误码一致，spec A）。不新增「技术详情」字段；以后要在界面上给管理员看原文，再单独设计。
- **R2 映射匹配顺序**：全名 → 族名（第一个「.」之前）→ `Input*`/`Output*` + `SensitiveContentDetected` 前缀 → 无 code 时 HTTP 401/403 回落 → 原有 `rejected`/`http_rejected`。有 code 但没命中时不做 HTTP 回落（厂商原文更准）。
- **R3 复用已有代码**：没有会话的 404 复用子计划 1 已登记的 `film.session.none`「还没有出片会话」；会话目录不存在复用 `film.session.dir_gone`（与 `voice.py` 原文一字不差），**不登记** `voice.session_gone`。
- **R4 包装异常**：`VoiceError` 在 `mix.compose` 里被转成 `MixError` 时，用 `MixError.of("compose.voice_failed", cause=cause_of(e))`；`compose.voice_failed` 模板就是 `{cause}`，中文兜底与原 `str(e)` 相同。
- **R5 列表分隔符**：列表参数统一由 `_zh_value` 用「、」连接，不为个别代码加分隔符参数。因此 `compose.lines_failed` 的中文兜底分隔符由「；」变为「、」，测试同步改。
- **R6 助手调用合成**：助手经 `assistant/actions.py:25` 的 `_op` 调 `_compose_quote`/`_compose_start`/`_export_check`，已对 dict 形状的 detail 取 `message`（中文兜底）给模型，所以错误改成消息对象后不用改助手。助手测试必须保持通过。
- **R7 合成意外异常**：`compose.crashed` 保留 `kind` 与 `cause`（与 spec B 对出片 `film.submit.crashed` 的处理不同）。理由：合成在用户自己的机器 / 服务器上跑 ffmpeg，意外异常多是环境问题，失败原因面板下方本就有 ffmpeg 输出给排查用；如果验收认为也应改为面向用户的说法，作为后续小改，不阻塞本子计划。`cause` 用 `vendor(_hide_root(str(e)))`。
- **R8 音色显示名**：`tts_volc.VOICES` 的「云舟 2.0」等是厂商给的音色名（专有名），不翻译，不登记代码。`FakeTts` 的「假男声」「假女声」同理（只在开发用的假厂商里出现）。
- **R9 合成状态字段**：`final` 新增 `step_msg`、`error_msg`，旧字段 `step`、`error` 继续写中文兜底；旧会话没有新字段时前端原样显示旧字段。指纹不受影响（`fingerprint` 不读这些字段，实现时 `grep -n "def compose_fingerprint" -A20 render/mix.py` 确认）。
- **R10 报告字段**：`mix_report.json` 的 `alignment`/`warning` 存 `{code, params}`（不带 `message`，与 `error_msg` 同形）；前端对字符串（旧报告）原样显示。
- **R11 `Conflict` 的 `expected_cny`**：`compose.voices_changed` 必须保持 `e.expected_cny is None`（前端据此判断要重新取报价）。`UserError.of(code, *args, **params)` 以 `cls(message, *args)` 构造，所以写 `Conflict.of("compose.voices_changed")`（`expected_cny` 取默认 None）；需要金额时用位置参数 `Conflict.of(code, cny, **params)`，**不要**把 `expected_cny=` 当关键字传给 `.of`（会被当成消息参数而报错）。
- **R12 日志**：新加的 `logging.getLogger(...)` 不改全局日志配置；uvicorn 默认会把 WARNING 打到 stderr，进 `backend.log`。日志文字里出现中文的行尾加 `# i18n: internal`。
- **R13 英文文案**：实现者初拟；所有新 en 键不得出现 `.env`、环境变量名、`brew`、异常类名占位。
