# 后端双语 子计划 3：账号、小说与管理后台（含错误参考编号）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 账号（注册、登录、权限）、小说（小说、章节、版本、长期记忆、关键帧与风格图）、管理后台（用户、用量、价格表）这几条链路上，后端给用户看的报错全部改为消息对象，前端按界面语言渲染、切换语言后跟着变；版本失败原因与章后整理失败原因可以按代码存储与显示；新增错误参考编号：意外失败时用户看到一个 8 位编号，管理员在后台按编号查到脱敏后的完整记录。

**Architecture:** 沿用子计划 1、2 的基础设施（`server/messages.py` 的 `register`/`msg`/`compact`/`UserError`/`to_detail`/`cause_of`，`render/session.py` 的 `set_error`/`copy_error`，`render/providers/base.py` 的 `scrub_secrets`，前端 `i18n/serverMsg.ts` 的 `formatMsg`/`errValue`/`itemError`，`srv` 文案节点，`srv-codes` 与 ast 扫描两道校验）。新机制只有一处：错误参考编号。
- `messages.with_ref` 给消息对象加顶层 `ref` 字段，并在中文兜底末尾附编号；
- 新模块 `server/error_refs.py` 负责生成编号、写 `DATA_DIR/error_refs.jsonl`（保留最近 1000 条）与 `server.errors` 日志；
- `app.py` 加一个纯 ASGI 中间件（注册在 CORS 之内），把没接住的异常变成带编号的 500；
- `formatMsg` 遇到顶层 `ref` 时附「参考编号」；
- 管理后台新增「错误记录」页签。

**Tech Stack:** Python 3.12、FastAPI 0.143 / Starlette 1.7（`TestClient`）、脚本式测试（`logging.Handler` 子类收集日志）、React 19 + TypeScript、Vite SSR 构建跑前端测试。

**Spec:** `docs/specs/2026-11-13-backend-i18n-design.md`（§9 子计划 3 原范围 + 文末「子计划 3 范围补充」A–D 四节）。本计划与 spec 冲突时以 spec 为准；spec 没写的细节见文末「实施裁定」。

---

## 全局约束（每个 Task 都必须遵守）

- 不读、不打印 `backend/.env`；密钥不进日志、报错、错误记录、session.json、章节与版本记录、消息参数。新加的 `logging` 调用与错误记录一律先 `scrub_secrets`。
- 不调用任何付费厂商；不运行 `backend/render/smoke.py`、`backend/render/smoke_tts.py`、`backend/assistant/smoke.py`；不向运行中的 5173 / 8000 服务发请求。
- 测试绝不联网、不读真实 `.env`：接口测试用 `TestClient` 或直接调用 app 里的函数；数据目录一律是临时目录（`STORYBOARD_DATA_DIR` 在导入 `server.*` 之前设好，照 `tests/server/test_novels.py` 现有写法）；涉及 `from_env` 的用例先把 `_load_dotenv` 换成空操作（照 `tests/render/test_seedance.py` 现有写法）。
- 不动 `docs/specs/2026-10-27-commercialization-design-contract.md`（未跟踪文件）。
- git：只 `git add` 具体文件，禁止 `git add -A` / `git commit -a` / `git add -N`；提交信息中文、描述性；不带任何 `Co-Authored-By` 或署名行；不 push。
- 改了登记表就运行 `cd backend && .venv/bin/python -m server.messages --write`，把 `backend/server/messages_codes.json` 一起提交。登记了新代码的 Task 必须同时在 `zh.ts`、`en.ts` 的 `srv` 节点加上对应键（`srv-codes` 会校验键齐全、中文一字不差、占位符一致）。
- 每个 Task 结束时必须全部通过：
  - 后端（在 `backend/` 下）：
    `for t in tests/pipeline/test_*.py tests/server/test_*.py tests/render/test_*.py tests/assistant/test_*.py; do .venv/bin/python $t || break; done`
    每个脚本打印 `ALL PASS`，循环里没有任何一个失败（不要只看最后一行：用 `fail=0; for …; do .venv/bin/python $t >/dev/null || { echo FAIL $t; fail=1; }; done; echo fail=$fail`）。
  - 前端（在 `frontend/` 下）：`npm test` 退出码 0（直接检查 `$?`，不要接管道）；`npm run lint` 0 error、warning 不多于基线 5 条；`npm run build` 成功。
  - 已知既有问题：`frontend/tests/film.test.tsx` 偶发 CPU 自旋卡死（与本计划无关）。遇到时单独重跑判定：
    `npx vite build --ssr tests/film.test.tsx --outDir /tmp/i18n-film --logLevel error && timeout 60 node /tmp/i18n-film/film.test.js`，
    通过即可，然后把 `npm test` 里 film 之后的测试逐个跑完；临时输出不要留在仓库里。
- 中文兜底：除 spec「子计划 3 范围补充」C 节列出的「文字变化」外，代码的中文兜底与现在一字不差（模板 + 参数渲染结果等于原字符串），现有断言中文的测试大多不用改。不得不变的地方写在各 Task 的「文字变化」里。
- 英文文案由实现者初拟，风格照子计划 1、2 的 `en.ts` `srv` 节点：冒号后半角空格；不出现 `.env`、环境变量名、异常类名、内部枚举值。

## 范围边界

- **本子计划改**：
  - 后端：
    - `server/auth.py`、`server/novels.py`、`server/library.py`、`server/admin.py`、`server/usage.py`、`server/pricing.py`、`server/store.py`（仅白名单标记）；
    - 新增 `server/error_refs.py`；
    - `server/messages.py`（登记表、`with_ref`）、`messages_codes.json`；
    - `render/session.py`（仅 `set_error` 保留 `ref`）、`render/runner.py`（仅提交意外异常接上编号）；
    - `server/app.py`：见下方「调用点清单」；
    - `tests/server/test_i18n_scan.py`（`MODULES`、`SINK_NAME`）。
  - 前端：`i18n/serverMsg.ts`、`zh.ts`、`en.ts`、`types.ts`、`api.ts`、`App.tsx`、`useJob.ts`、`useKeyframes.ts`、`components/auth/AuthDialog.tsx`、`NovelPage.tsx`、`NovelOverview.tsx`、`NovelAssets.tsx`、`CanvasPanels.tsx`、`params/StyleImageField.tsx`、`RenderView.tsx`、`TimelineCanvas.tsx`、`workflow/VersionBar.tsx`、`components/admin/*`（含新增 `ErrorsTab.tsx`）。
- **不改（后续子计划）**：job 接口、转换任务进度与失败、quality_report、验证门 `_render_gate`、「分镜结构不完整」（`render_plan` 与 `render_keyframes` 里的两处）、助手接口（含 `_assistant_db`、`assistant_undo`）→ 子计划 4；验证报告 → 子计划 5；豆包语音 4xx 映射 → 后续事项。`JobPanel` 的 `job.error`、`useJob` 轮询错误的内容属于子计划 4，本计划只把 `useJob` 的错误状态类型改成 `MsgLike`（字符串照样显示）。

## 调用点清单（`server/app.py`）

| 函数 | 现状 | 处置 | Task |
|---|---|---|---|
| 模块级 | 纯文本 500「Internal Server Error」 | 新增 `_ErrorRefMiddleware`，注册在 CORS 之内 → `500 {detail: common.internal + ref}` | 1 |
| `_compose_worker` | 意外异常 `log.error` 脱敏堆栈 + `compose.crashed` | 改走 `error_refs.record(...)`，`failed()` 保留 `ref` | 1 |
| `current_user` | 401「未登录或登录已过期」 | `msg("auth.unauthenticated")` | 2 |
| `admin_user` | 403「需要管理员权限」 | `msg("auth.admin_only")` | 2 |
| `register` | `AuthError` → 400 `str(e)`；回填资产库的两条 `print` | `to_detail(e)`；`print` 行尾 `# i18n: internal` | 2 |
| `login` | `AuthError` → 401 `str(e)` | `to_detail(e)` | 2 |
| `novel_user` | 迁移日志两条 `print` | 行尾 `# i18n: internal` | 3 |
| `_novel_call` | 404/409/422 `str(e)` | 一律 `to_detail(e)` | 3 |
| `_clean_params` | 422「未知的制作参数：[…]」 | `msg("novel.unknown_params", keys=sorted(unknown))` | 3 |
| `_start_version` | 422「本章还没有原文」、429「本月用量已达上限」 | `msg("chapter.no_text")`、`msg("usage.monthly_cap")` | 3 |
| `memory_asset_upsert` | 422「卡片 id 与路径不一致：…」 | `msg("novel.asset.id_mismatch", got=…, want=…)` | 3 |
| `render_plan` | `find_version` 的 `ValueError` → 400 `str(e)`；404「版本不存在」；422「分镜结构不完整」 | 400 `to_detail(e)`（`NovelError` 带 `novel.bad_id`）；404 `msg("chapter.version.not_found")`；422 留给子计划 4，行尾 `# i18n: todo(4)` | 3 |
| keyframes_* / style_image_* / lifecycle_* / plot_* / constraints_* / versions_* / chapters_* / novels_* | 都经 `_novel_call` | 随 `_novel_call` 一起变，不单独改 | 3 |
| `_run_digest` | `set_digest_state(..., error=repr(e)[:300])` | `error_refs.unexpected(e, "chapter.digest.failed", …)` 经 `set_error` 写 `error`/`error_msg` | 4 |
| `chapters_digest` | 422「章后整理已关闭（STORYBOARD_CHAPTER_DIGEST=0）」 | `msg("chapter.digest.off")`，变量名写进 `log.warning` | 4 |
| `_admin_call` | 404/400 `str(e)` | `to_detail(e)` | 6 |
| `admin_usage`、`admin_usage_csv` | 422「days 只能是 7、30、90」 | `msg("admin.bad_days")` | 6 |
| `admin_pricing_put` | `ValueError` → 400 `str(e)` | `to_detail(e)`（`PricingError` 带代码） | 6 |
| 新增 `admin_errors`、`admin_error_get` | — | `GET /admin/errors`、`GET /admin/errors/{ref}` | 6 |
| `_style_for`、`_keyframe_paths` | 内部吞掉 `NotFound` | 不改 | — |
| `_render_gate`、`render_keyframes`、`get_job*`、`_assistant_*`、`assistant_*` | — | 子计划 4 | — |

## 文件结构

| 文件 | 本计划的改动 |
|---|---|
| `backend/server/error_refs.py`（新） | 编号生成、记录写盘与裁剪、`record`/`record_exc`/`unexpected`/`recent`/`find`/`user_of_root` |
| `backend/server/messages.py` | `with_ref`；登记 `common.*`、`auth.*`、`novel.*`、`chapter.*`、`usage.*`、`admin.*`、`library.*` |
| `backend/render/session.py` | `set_error` 保留 `ref` |
| `backend/render/runner.py` | 提交意外异常经 `error_refs.record` |
| `backend/server/auth.py`、`novels.py`、`library.py`、`admin.py`、`usage.py`、`pricing.py`、`store.py` | 异常类混入 `UserError`、raise 带代码；内部 raise 标 `# i18n: internal` |
| `backend/server/app.py` | 见调用点清单 |
| `backend/tests/server/test_error_refs.py`（新） | 编号、记录、裁剪、脱敏、500 中间件 |
| `backend/tests/server/test_admin.py`、`test_novels.py`、`test_keyframes.py`、`test_style_image.py`、`test_usage.py`、`test_messages.py`、`test_compose.py`、`tests/render/test_session.py`、`test_runner.py` | 见各 Task |
| `frontend/src/i18n/serverMsg.ts` | `ServerMsg.ref`、附编号、`errText` |
| `frontend/src/App.tsx`、`useJob.ts`、`useKeyframes.ts` 与各组件 | 错误存 `MsgLike`，渲染时 `formatMsg` |
| `frontend/src/components/admin/ErrorsTab.tsx`（新） | 错误记录页签 |
| `frontend/tests/server-msg.test.ts`、`landing.test.tsx`、`flow.test.tsx`、`canvas.test.tsx`、`chapter.test.tsx`、`admin.test.tsx` | 见各 Task |

---

### Task 1: 错误参考编号（记录、500 兜底、持久化保留编号、前端附编号）

**Files:**
- Create: `backend/server/error_refs.py`
- Modify: `backend/server/messages.py`（`with_ref`；登记 `common.internal`）、`backend/server/messages_codes.json`
- Modify: `backend/render/session.py`（`set_error`）
- Modify: `backend/render/runner.py`（`_submit` 的 `except Exception` 分支，约 :291-296）
- Modify: `backend/server/app.py`（导入、`_ErrorRefMiddleware` 与注册位置、`_compose_worker`）
- Modify: `backend/tests/server/test_i18n_scan.py`（`MODULES` 加 `"server/error_refs.py": None`）
- Modify: `frontend/src/i18n/serverMsg.ts`、`zh.ts`、`en.ts`（`common.refSuffix`、`srv.common.internal`）
- Test: `backend/tests/server/test_error_refs.py`（新）、`backend/tests/render/test_session.py`、`backend/tests/render/test_runner.py`、`backend/tests/server/test_compose.py`、`backend/tests/server/test_messages.py`、`frontend/tests/server-msg.test.ts`

- [ ] **Step 1: 写失败测试**

  `backend/tests/server/test_error_refs.py`（新文件，脚本式，末尾打印 `ALL PASS`）：

  ```python
  #!/usr/bin/env python3
  """错误参考编号：编号格式、记录脱敏与截断、裁剪、查找、接口 500 兜底。用法: python3 tests/server/test_error_refs.py"""
  import json
  import logging
  import os
  import sys
  import tempfile
  from pathlib import Path

  ROOT = Path(__file__).resolve().parent.parent.parent
  sys.path.insert(0, str(ROOT))

  _TMP = tempfile.TemporaryDirectory()
  os.environ["STORYBOARD_DATA_DIR"] = _TMP.name          # 必须在导入 server.* 之前
  KEY = "sk-ark-test-0123456789"
  os.environ["ARK_API_KEY"] = KEY                         # 只为验证脱敏；测试不联网

  from server import auth, error_refs, messages as M  # noqa: E402


  class _Grab(logging.Handler):
      def __init__(self):
          super().__init__()
          self.lines = []

      def emit(self, rec):
          self.lines.append(rec.getMessage())


  def part_ref():
      r = error_refs.new_ref()
      assert len(r) == 8 and set(r) <= set(error_refs.ALPHABET), r
      assert not set("ILOU") & set(error_refs.ALPHABET)
      assert error_refs.normalize(" k7q2-m9xd ") == "K7Q2M9XD"
      assert error_refs.user_of_root(auth.DATA_DIR / "users" / "a1b2c3d4e5f6" / "novels" / "n1") == "a1b2c3d4e5f6"
      assert error_refs.user_of_root("/tmp/elsewhere") is None
      # with_ref：顶层 ref，中文兜底附编号；compact 不带 ref
      m = M.with_ref(M.msg("common.internal"), "K7Q2M9XD")
      assert m["ref"] == "K7Q2M9XD" and m["message"].endswith("（参考编号 K7Q2M9XD）"), m
      assert "ref" not in M.compact(m)
      print("1. 编号格式 / normalize / user_of_root / with_ref ✓")


  def part_record():
      grab = _Grab()
      lg = logging.getLogger("server.errors")
      lg.addHandler(grab)
      try:
          try:
              raise RuntimeError(f"boom {KEY} Authorization: Bearer abc.def")
          except RuntimeError as e:
              m = error_refs.unexpected(e, user_id="a1b2c3d4e5f6", where="GET /novels")
      finally:
          lg.removeHandler(grab)
      assert m["code"] == "common.internal" and m["params"] == {} and len(m["ref"]) == 8
      row = error_refs.find(m["ref"].lower())
      assert row and row["user_id"] == "a1b2c3d4e5f6" and row["where"] == "GET /novels"
      assert row["code"] == "common.internal" and "RuntimeError" in row["detail"] and "Traceback" in row["detail"]
      dump = json.dumps(row) + "\n".join(grab.lines)
      assert KEY not in dump and "abc.def" not in dump, "记录与日志不得含密钥或 Bearer 凭据"
      assert any(m["ref"] in x for x in grab.lines)
      # 截断
      ref = error_refs.record("common.internal", "x" * (error_refs.DETAIL_MAX + 500))
      assert len(error_refs.find(ref)["detail"]) == error_refs.DETAIL_MAX
      # 额外密钥（厂商对象持有的）
      ref = error_refs.record("common.internal", "key=zz-extra-secret", secrets_extra=["zz-extra-secret"])
      assert "zz-extra-secret" not in error_refs.find(ref)["detail"]
      # 指定 logger：写到调用方的 logger（runner、app 现有的日志断言依赖这一点）
      g2 = _Grab()
      other = logging.getLogger("render.runner")
      other.addHandler(g2)
      try:
          ref = error_refs.record("common.internal", "提交异常 root=R clip=E01", logger=other)
      finally:
          other.removeHandler(g2)
      assert any(ref in x and "clip=E01" in x for x in g2.lines)
      print("2. 记录：脱敏 / 截断 / 额外密钥 / 指定 logger / 查找不分大小写 ✓")


  def part_trim():
      old_max = error_refs.MAX_ROWS
      error_refs.MAX_ROWS = 5
      try:
          refs = [error_refs.record("common.internal", f"n{i}") for i in range(12)]
          rows = error_refs.recent(100)
          assert len(rows) <= 2 * error_refs.MAX_ROWS, len(rows)
          assert rows[0]["ref"] == refs[-1], "最新在前"
          assert error_refs.find(refs[-1]) and error_refs.find(refs[0]) is None, "超过上限后最旧的被裁掉"
      finally:
          error_refs.MAX_ROWS = old_max
      # 坏行容忍
      with open(error_refs._file(), "a", encoding="utf-8") as f:
          f.write("{坏行\n")
      assert error_refs.recent(1)
      print("3. 裁剪到上限 / 最新在前 / 坏行跳过 ✓")


  def part_api():
      from fastapi.testclient import TestClient
      from server import app as app_mod, novels

      u = auth.register("erruser", "secret1")
      tok = auth.issue_token(u["id"])
      orig = novels.list_novels

      def boom(user_id):
          raise RuntimeError(f"disk on fire {KEY}")

      novels.list_novels = boom
      try:
          c = TestClient(app_mod.app)
          r = c.get("/novels", headers={"Authorization": f"Bearer {tok}", "Origin": "http://localhost:5173"})
      finally:
          novels.list_novels = orig
      assert r.status_code == 500, r.text
      d = r.json()["detail"]
      assert d["code"] == "common.internal" and d["params"] == {} and len(d["ref"]) == 8, d
      assert d["ref"] in d["message"] and KEY not in r.text and "RuntimeError" not in r.text
      assert r.headers.get("access-control-allow-origin"), "500 也要带 CORS 头，跨源前端才读得到 detail"
      row = error_refs.find(d["ref"])
      assert row["user_id"] == u["id"] and row["where"] == "GET /novels" and KEY not in row["detail"]
      # HTTPException 不经过中间件：照旧
      assert c.get("/novels").status_code == 401
      print("4. 接口 500：消息对象带编号 / CORS 头 / 记录带用户与位置 / 不含密钥 ✓")


  def main() -> int:
      part_ref()
      part_record()
      part_trim()
      part_api()
      print("\nALL PASS")
      return 0


  if __name__ == "__main__":
      sys.exit(main())
  ```

  其它测试：
  - `tests/render/test_session.py`：`set_error(obj, with_ref(msg("film.submit.crashed"), "K7Q2M9XD"))` 后 `obj["error_msg"] == {"code": "film.submit.crashed", "params": {}, "ref": "K7Q2M9XD"}`，`obj["error"]` 以「（参考编号 K7Q2M9XD）」结尾；`copy_error` 后目标同样带 `ref`；不带 `ref` 的消息写出的 `error_msg` 里**没有** `ref` 键（与现在一致）。
  - `tests/render/test_runner.py`：子计划 2 已有的「提交意外异常」用例改为另外断言：段的 `error_msg["code"] == "film.submit.crashed"` 且有 8 位 `ref`；`error_refs.find(ref)` 的 `detail` 含 root、段 id 与异常类名；`render.runner` logger 收到的 ERROR 记录仍含 root、段 id 与堆栈（`record(..., logger=log)` 保证）。
  - `tests/server/test_compose.py`：子计划 2 已有的「合成意外异常」用例另外断言 `final["error_msg"]["ref"]` 存在，`error_refs.find(...)["detail"]` 含异常类名，`final["error"]` 不含异常类名但含编号。
  - `tests/server/test_messages.py`：`with_ref` 对已带 `ref` 的消息再调用一次时**替换**编号、不重复附加（`message` 里只出现一次「参考编号」）。
  - `frontend/tests/server-msg.test.ts` 新增一节：
    ```ts
    // 8. 参考编号：顶层 ref 附在渲染结果后；兜底 message 已带编号时不重复；嵌套原因不附
    const internal = { code: 'common.internal', params: {}, message: '服务器出了点问题，请稍后重试；仍失败请联系管理员（参考编号 K7Q2M9XD）', ref: 'K7Q2M9XD' }
    must(formatMsg(internal, 'zh') === '服务器出了点问题，请稍后重试；仍失败请联系管理员（参考编号 K7Q2M9XD）', '中文附编号')
    must(formatMsg(internal, 'en').endsWith(' (reference K7Q2M9XD)'), '英文附编号')
    const unreg = { code: 'x.not.registered', message: '兜底（参考编号 AB12CD34）', ref: 'AB12CD34' }
    must(formatMsg(unreg, 'en') === '兜底（参考编号 AB12CD34）', '缺译回落的 message 已带编号，不重复')
    must(itemError({ error: 'x', error_msg: { code: 'common.internal', params: {}, ref: 'K7Q2M9XD' } }, 'en').includes('K7Q2M9XD'), '持久化的 error_msg 也附编号')
    must(errValue(new ApiError('m', 500, internal)) === internal, 'errValue 保留带编号的 detail')
    ```

- [ ] **Step 2: 运行确认失败**：`cd backend && .venv/bin/python tests/server/test_error_refs.py` 应报 `ModuleNotFoundError: server.error_refs` 或 `AttributeError: with_ref`。

- [ ] **Step 3: `messages.py`**（放在 `cause_of` 之后、登记表之前；`common.internal` 紧跟 `common.unknown` 登记）

  ```python
  REF_SUFFIX_ZH = "（参考编号 {ref}）"     # 与前端 zh.common.refSuffix 一致


  def with_ref(m: dict, ref: str) -> dict:
      """给消息对象加参考编号：顶层 ref（不进 params），中文兜底末尾附编号。已有编号时替换。"""
      base = m.get("message") or render_zh(m["code"], m.get("params") or {})
      old = m.get("ref")
      if old:
          base = base.replace(REF_SUFFIX_ZH.format(ref=old), "")
      return {**m, "message": base + REF_SUFFIX_ZH.format(ref=ref), "ref": ref}
  ```
  ```python
  register("common.internal", "服务器出了点问题，请稍后重试；仍失败请联系管理员")
  ```

- [ ] **Step 4: `server/error_refs.py`**（完整代码）

  ```python
  """错误参考编号（设计 docs/specs/2026-11-13-backend-i18n-design.md「子计划 3 范围补充」B）。

  意外失败时给用户一个 8 位编号；同一编号的完整记录（脱敏后的堆栈、位置、用户）写进
  DATA_DIR/error_refs.jsonl（保留最近 MAX_ROWS 条）与日志，管理后台按编号查。
  只记堆栈或原文，不记请求体、请求头、查询串、局部变量。
  """
  import json
  import logging
  import os
  import secrets
  import tempfile
  import threading
  import traceback
  from pathlib import Path
  from typing import Optional

  from render.providers.base import scrub_secrets
  from server import auth, usage
  from server.messages import msg, with_ref
  from server.store import now_iso

  log = logging.getLogger("server.errors")

  ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"      # 32 个：去掉易混的 I L O U
  REF_LEN = 8
  MAX_ROWS = 1000                                    # 保留最近这么多条；超过两倍时整体裁剪
  DETAIL_MAX = 8000

  _lock = threading.Lock()
  _rows: dict = {}                                   # 文件路径 → 当前行数（首次写时数一遍）


  def _file() -> Path:
      return auth.DATA_DIR / "error_refs.jsonl"


  def new_ref() -> str:
      return "".join(secrets.choice(ALPHABET) for _ in range(REF_LEN))


  def normalize(ref) -> str:
      """用户转述的编号：忽略大小写、空格与连字符。"""
      return "".join(ch for ch in str(ref or "").upper() if ch.isalnum())


  def user_of_root(root) -> Optional[str]:
      """DATA_DIR/users/<uid>/… → uid（后台线程只有会话目录时用）；不是这种路径时 None。"""
      parts = Path(str(root)).parts
      for i, p in enumerate(parts[:-1]):
          if p == "users" and len(parts[i + 1]) == 12:
              return parts[i + 1]
      return None


  def _trim_locked(path: Path) -> None:
      keep = path.read_text(encoding="utf-8").splitlines()[-MAX_ROWS:]
      fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".error_refs.")
      try:
          with os.fdopen(fd, "w", encoding="utf-8") as f:
              f.write("\n".join(keep) + "\n")
          os.replace(tmp, path)
      except OSError:
          Path(tmp).unlink(missing_ok=True)
          raise


  def record(code: str, detail, *, params: Optional[dict] = None, user_id: Optional[str] = None,
             where: str = "", secrets_extra=(), logger: Optional[logging.Logger] = None) -> str:
      """记一条，返回编号。detail 先脱敏再截断；同一内容写一条 ERROR 日志（logger 缺省为 server.errors）。
      写盘失败只记日志，编号照常返回：记账不能拖垮报错本身。"""
      ref = new_ref()
      clean = scrub_secrets(str(detail), secrets_extra)[:DETAIL_MAX]
      where = scrub_secrets(str(where or ""), secrets_extra)
      (logger or log).error("ref=%s code=%s user=%s where=%s\n%s", ref, code, user_id or "-", where, clean)
      row = {"ref": ref, "at": now_iso(), "user_id": user_id, "code": code,
             "params": params or {}, "where": where, "detail": clean}
      try:
          with _lock:
              path = _file()
              path.parent.mkdir(parents=True, exist_ok=True)
              key = str(path)
              if key not in _rows:
                  _rows[key] = sum(1 for _ in open(path, encoding="utf-8")) if path.exists() else 0
              with open(path, "a", encoding="utf-8") as f:
                  usage.ensure_line_start(path, f)
                  f.write(json.dumps(row, ensure_ascii=False) + "\n")
              _rows[key] += 1
              if _rows[key] > 2 * MAX_ROWS:
                  _trim_locked(path)
                  _rows[key] = MAX_ROWS
      except OSError:
          log.exception("错误记录写盘失败 ref=%s", ref)  # i18n: internal
      return ref


  def record_exc(e: BaseException, code: str, *, context: str = "", **kw) -> str:
      """异常 → 一条记录（完整堆栈，含 __cause__/__context__ 链）。context 是放在堆栈前的定位文字。"""
      tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
      return record(code, f"{context}\n{tb}" if context else tb, **kw)


  def unexpected(e: BaseException, code: str = "common.internal", **kw) -> dict:
      """意外异常 → 带编号的消息对象。code 的模板不得有参数（这类文案只说「出了问题、联系管理员」）。"""
      return with_ref(msg(code), record_exc(e, code, **kw))


  def _read() -> list:
      path = _file()
      if not path.exists():
          return []
      rows = []
      with open(path, encoding="utf-8") as f:
          for line in f:
              try:
                  rows.append(json.loads(line))
              except ValueError:
                  continue
      return rows


  def recent(limit: int = 200) -> list:
      return list(reversed(_read()))[:limit]


  def find(ref) -> Optional[dict]:
      want = normalize(ref)
      return next((r for r in reversed(_read()) if r.get("ref") == want), None) if want else None
  ```
  - 导入顺序自检：`cd backend && .venv/bin/python -c "import server.error_refs"` 与 `.venv/bin/python -c "import render.runner"` 在全新解释器里都不报循环导入。若 `render.providers` 包的 `__init__` 导致循环，把 `from render.providers.base import scrub_secrets` 挪进 `record` 函数体内（并在行尾注释说明原因）。

- [ ] **Step 5: `render/session.py` 的 `set_error`** 保留 `ref`：

  ```python
      if m:
          params = m.get("params") or {}
          obj["error"] = m.get("message") or render_zh(m["code"], params)
          obj["error_msg"] = {"code": m["code"], "params": params, **({"ref": m["ref"]} if m.get("ref") else {})}
  ```
  `copy_error` 已整体复制 `error_msg`，不用改。

- [ ] **Step 6: runner 提交意外异常**（`render/runner.py` `_submit` 的 `except Exception` 分支）：

  ```python
          except Exception as e:
              ref = error_refs.record_exc(e, "film.submit.crashed", context=f'提交异常 root={root} clip={c["id"]}',  # i18n: internal
                                          user_id=error_refs.user_of_root(root), where=f'submit {root} {c["id"]}',
                                          secrets_extra=[getattr(provider, "_key", "")], logger=log)
              sess.submit_failed(root, c["id"], with_ref(msg("film.submit.crashed"), ref))
              return False
  ```
  顶部加 `from server import error_refs`、`from server.messages import … with_ref`。原来的两行（`tb = …`、`log.error(…)`）删掉：`record_exc` 已在同一个 logger 写出同样脱敏的堆栈。

- [ ] **Step 7: `app.py`**

  - 导入：`from fastapi.responses import FileResponse, JSONResponse, StreamingResponse`；`from server import error_refs`；`from server.messages import … with_ref`。
  - 中间件（类定义与注册都放在 `app = FastAPI(...)` 之后、`app.add_middleware(CORSMiddleware, …)` **之前**；Starlette 后加的在外层，先加的这个就在 CORS 之内）：

    ```python
    def _uid_of(scope) -> Optional[str]:
        """500 记录里的用户：按 Authorization 头解析，取不到就 None（不能让它挡住报错）。"""
        try:
            h = dict(scope.get("headers") or []).get(b"authorization", b"").decode("latin-1")
            token = h[7:] if h.lower().startswith("bearer ") else ""
            u = auth.verify_token(token) if token else None
            return u["id"] if u else None
        except Exception:  # noqa: BLE001
            return None


    class _ErrorRefMiddleware:
        """路由里没接住的异常 → 500 + 带参考编号的消息对象（spec 子计划 3 B）。
        注册在 CORS 之内，500 也带 CORS 头；响应已开始（流式中途）时不接管，照旧抛出。
        HTTPException 由内层 ExceptionMiddleware 处理，不会到这里。"""

        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return
            started = False

            async def _send(message):
                nonlocal started
                if message["type"] == "http.response.start":
                    started = True
                await send(message)

            try:
                await self.app(scope, receive, _send)
            except Exception as e:  # noqa: BLE001
                if started:
                    raise
                m = error_refs.unexpected(e, user_id=_uid_of(scope), logger=log,
                                          where=f'{scope.get("method", "")} {scope.get("path", "")}')
                await JSONResponse({"detail": m}, status_code=500)(scope, receive, send)


    app.add_middleware(_ErrorRefMiddleware)      # 必须在 CORSMiddleware 之前注册（见类注释）
    ```
  - `_compose_worker`：
    - `failed()` 重建消息时保留 `ref`：`m = _hide_root_deep({"code": …, "params": …, "message": …, **({"ref": m["ref"]} if m.get("ref") else {})}, root)`。
    - `except Exception as e` 分支：删掉 `tb = …` 与 `log.error(…)` 两行，改为
      ```python
      ref = error_refs.record_exc(e, "compose.crashed", context=f"合成异常 root={root}",  # i18n: internal
                                  user_id=error_refs.user_of_root(root), where=f"compose {root}", logger=log)
      try:
          failed(with_ref(msg("compose.crashed"), ref))
      ```
      内层 `except Exception as e2` 的写回失败日志保持不变。

- [ ] **Step 8: 前端**
  - `serverMsg.ts`：
    ```ts
    export interface ServerMsg { code: string; params?: Record<string, unknown>; message?: string; ref?: string }

    /** 顶层参考编号：附在渲染结果后；结果里已有编号（缺译回落到已附编号的 message）就不重复 */
    function withRef(text: string, ref: unknown, l: Locale): string {
      if (typeof ref !== 'string' || !ref || text.includes(ref)) return text
      return text + translate(l, 'common.refSuffix', { ref })
    }
    ```
    `formatMsg` 里 `if (isServerMsg(m)) return withRef(render(m, locale), m.ref, locale)`；`render` 与 `value` 不改（嵌套原因不附编号）。另加：
    ```ts
    /** toast 等即时显示：弹出时按当前语言格式化 */
    export const errText = (e: unknown, locale?: Locale): string => formatMsg(errValue(e), locale)
    ```
  - `zh.ts`：`common.refSuffix: '（参考编号 {ref}）'`（与后端 `REF_SUFFIX_ZH` 一致）；`srv.common.internal: '服务器出了点问题，请稍后重试；仍失败请联系管理员'`。
  - `en.ts`：`common.refSuffix: ' (reference {ref})'`；`srv.common.internal: 'Something went wrong on the server. Please try again; if it keeps failing, contact the administrator.'`。

- [ ] **Step 9: 生成 JSON、跑全部校验**（见全局约束）。
- [ ] **Step 10: 提交**：`git add backend/server/error_refs.py backend/server/messages.py backend/server/messages_codes.json backend/render/session.py backend/render/runner.py backend/server/app.py backend/tests/server/test_error_refs.py backend/tests/server/test_i18n_scan.py backend/tests/server/test_messages.py backend/tests/render/test_session.py backend/tests/render/test_runner.py backend/tests/server/test_compose.py frontend/src/i18n/serverMsg.ts frontend/src/i18n/zh.ts frontend/src/i18n/en.ts frontend/tests/server-msg.test.ts`，提交信息示例：「新增错误参考编号：接口里没接住的异常改为带编号的 500 消息对象（中间件注册在 CORS 之内），出片提交与合成的意外异常也带编号；完整记录脱敏后写进 error_refs.jsonl（保留最近 1000 条）与日志，前端在消息后附参考编号」。

---

### Task 2: 账号（auth 与登录注册、权限守门）

**Files:**
- Modify: `backend/server/auth.py`、`backend/server/app.py`（`current_user`、`admin_user`、`register`、`login`）
- Modify: `backend/server/messages.py`、`messages_codes.json`
- Modify: `backend/tests/server/test_i18n_scan.py`（`MODULES` 加 `"server/auth.py": None`；app 函数集合加 `current_user`、`admin_user`、`register`、`login`）
- Modify: `frontend/src/components/auth/AuthDialog.tsx`、`zh.ts`、`en.ts`
- Test: `backend/tests/server/test_admin.py`（`part_auth` :46、`part_api` :236）、`frontend/tests/landing.test.tsx`（或 `grep -ln "AuthDialog\|/auth/login" tests/` 里覆盖登录弹窗的那个）

- [ ] **Step 1: 写失败测试**
  - `test_admin.py`：
    - `part_auth`：:46 改为 `assert e.code == "auth.disabled" and str(e) == "账号已停用"`；另加：注册非法用户名 → `auth.bad_username`；短密码 → `auth.password_short`，`e.params == {"min": 6}`；重名 → `auth.username_taken`；密码错 → `auth.bad_credentials`；`auth.set_password("ffffffffffff", "secret1")` → `auth.user_not_found`。
    - `part_api`：:236 改为 `r.json()["detail"]["code"] == "auth.disabled"`；未登录 `/admin/overview` → 401 `detail["code"] == "auth.unauthenticated"`；普通用户 → 403 `auth.admin_only`；`/auth/register` 重名 → 400 `auth.username_taken`。
  - 前端登录弹窗测试：桩后端对 `/auth/login` 返回 `401 {"detail": {"code": "auth.bad_credentials", "params": {}, "message": "用户名或密码不正确"}}`；中文界面提交后提示为「用户名或密码不正确」；切到英文（照该文件现有的 `setLocale` 抓取写法）后同一条提示变成英文；桩返回字符串 detail 时原样显示。

- [ ] **Step 2: 运行确认失败。**

- [ ] **Step 3: 登记**（中文与现在一字不差）：

  ```python
  # 账号
  register("auth.unauthenticated", "未登录或登录已过期")
  register("auth.admin_only", "需要管理员权限")
  register("auth.bad_username", "用户名需为 2–32 位的中英文、数字、下划线、点或连字符")
  register("auth.password_short", "密码至少 {min} 位")
  register("auth.username_taken", "用户名已被占用")
  register("auth.disabled", "账号已停用")
  register("auth.bad_credentials", "用户名或密码不正确")
  register("auth.user_not_found", "用户不存在")
  ```

- [ ] **Step 4: 实现**
  - `auth.py`：`from server.messages import UserError`；`class AuthError(UserError, Exception)`。各 raise 改 `.of(...)`：`AuthError.of("auth.password_short", min=MIN_PASSWORD)` 等。
    - `user_dir` 的「非法的用户 ID」：行尾 `# i18n: internal`（只来自签过名的 token 与目录名）。
    - `update_user` 的 `ValueError(f"不允许修改：…")`：行尾 `# i18n: internal`（只有 admin.py 以白名单字段调用）。
    - `_adopt_legacy_runs` 的 `print`：行尾 `# i18n: internal`。
  - `app.py`：
    - `current_user`：`raise HTTPException(401, detail=msg("auth.unauthenticated"))`。
    - `admin_user`：`raise HTTPException(403, detail=msg("auth.admin_only"))`。
    - `register`、`login`：`raise HTTPException(400 / 401, detail=to_detail(e))`。`register` 里两条资产库回填的 `print` 行尾 `# i18n: internal`。
  - 前端 `AuthDialog.tsx`：`const [error, setError] = useState<MsgLike>(null)`；`catch (err) { setError(errValue(err)) }`；渲染 `{error && <p role="alert" …>{formatMsg(error, locale)}</p>}`（`locale` 取自 `useI18n()`，让切换语言触发重渲染）。
  - `zh.ts`/`en.ts` 加 `srv.auth.*`。en 示例：`unauthenticated` → `'You're not signed in, or your session has expired.'`；`admin_only` → `'Administrator access required.'`；`bad_username` → `'Usernames must be 2–32 characters: letters (including Chinese), digits, underscores, dots or hyphens.'`；`password_short` → `'Passwords must be at least {min} characters.'`；`username_taken` → `'That username is already taken.'`；`disabled` → `'This account has been disabled.'`；`bad_credentials` → `'Incorrect username or password.'`；`user_not_found` → `'User not found.'`。

- [ ] **Step 5: 跑全部校验并提交**。`git add backend/server/auth.py backend/server/app.py backend/server/messages.py backend/server/messages_codes.json backend/tests/server/test_admin.py backend/tests/server/test_i18n_scan.py frontend/src/components/auth/AuthDialog.tsx frontend/src/i18n/zh.ts frontend/src/i18n/en.ts frontend/tests/landing.test.tsx`（登录弹窗测试若在别的文件，换成实际文件）。提交信息示例：「账号报错带代码：注册、登录、停用、未登录与无管理员权限改为消息对象，登录弹窗按界面语言渲染并随切换语言更新」。

---

### Task 3: 小说、章节、版本与长期记忆（后端）

**Files:**
- Modify: `backend/server/novels.py`、`backend/server/library.py`、`backend/server/store.py`（仅标记）
- Modify: `backend/server/app.py`（`novel_user`、`_novel_call`、`_clean_params`、`_start_version`、`memory_asset_upsert`、`render_plan`）
- Modify: `backend/server/messages.py`、`messages_codes.json`
- Modify: `backend/tests/server/test_i18n_scan.py`：
  - `MODULES` 加 `"server/novels.py": None`、`"server/library.py": None`、`"server/store.py": None`；
  - app 函数集合加 `novel_user`、`_novel_call`、`_clean_params`、`_start_version`、`memory_asset_upsert`、`render_plan`；
  - `SINK_NAME` 补 `Busy`：`r"(Error|Exception|Submit|Conflict|NotFound|Corrupt|Exceeded|Invalid|Stale|Busy)$"`，自检用例加一条 `('class Busy(Exception): pass\nraise Busy("中文")\n', 1)`。
- Modify: `frontend/src/i18n/zh.ts`、`en.ts`（`srv.novel`、`srv.chapter`、`srv.library`、`srv.usage.monthly_cap`、`srv.common.image_too_big`）
- Test: `backend/tests/server/test_novels.py`（:85、:229 及新增）、`test_keyframes.py`、`test_style_image.py`、`test_admin.py`（:276 月上限）、`backend/tests/server/test_messages.py`

- [ ] **Step 1: 写失败测试**
  - `test_novels.py`：
    - :85 改为 `assert e.code == "chapter.text_locked" and "锁定" in str(e)`；:229 改为 `assert e.status_code == 422 and e.detail["code"] == "novel.title_taken" and e.detail["params"] == {"title": "药"}`。
    - 新增（直接调存储层，断言 `e.code`、关键 `params`）：
      - 空标题 → `novel.empty_title`；不存在的小说 → `NotFound` `novel.not_found`；非法 id（`"../x"`）→ `NovelError` `novel.bad_id`，`params == {"id": "../x"}`，`str(e) == "非法的 ID：../x"`；
      - 章节：空标题 → `chapter.empty_title`；不存在 → `chapter.not_found`；
      - 版本：不存在 → `chapter.version.not_found`；删采用版 → `chapter.version.adopted_delete`；采用失败版本 → `chapter.version.not_adoptable`（`params == {}`，中文不含状态值）；后面章节已接着编号 → `chapter.version.later_adopted`，`params["names"]` 是列表、`str(e)` 里点名那一章（原 :110 断言保留）；
      - 版本还有片段在出 → `Busy`，`code == "chapter.version.busy"`，`isinstance(e, novels.NovelError)` 仍成立；
      - 资产卡：未知类别 → `novel.asset.unknown_kind`；没 id → `novel.asset.no_id`；没名称 → `novel.asset.no_name`；删不存在的 → `novel.asset.not_found`；
      - 生命周期：没有的角色 → `novel.lifecycle.unknown_character`；未知类型 → `novel.lifecycle.unknown_type`（`params["options"]` 是列表，`str(e)` 与原文一字不差）；未知状态 → `novel.lifecycle.unknown_status`；不存在 → `novel.lifecycle.not_found`；
      - 摘要过长 → `chapter.synopsis_too_long`（`params` 有 `max`、`len`）；限制没写规则 → `novel.constraint.no_text`；不存在 → `novel.constraint.not_found`；没有采用版时 `digest_input` → `chapter.no_adopted`。
    - 接口层（`_novel_call` 包着的路由，照 :220-:370 现有写法直接调 app 函数）：404 / 409 / 422 的 `e.detail` 都是消息对象（`code` 分别为 `novel.not_found`、`chapter.version.busy` 或测试里方便构造的 409、`novel.empty_title`）；`_clean_params({"bogus": 1, "zzz": 2})` → 422 `novel.unknown_params`，`params["keys"] == ["bogus", "zzz"]`；`memory_asset_upsert` id 不一致 → 422 `novel.asset.id_mismatch`；`_start_version` 本章无原文 → 422 `chapter.no_text`；`render_plan` 的 `run_id="../x"` → 400 `novel.bad_id`，不存在的 `run_id` → 404 `chapter.version.not_found`。
  - `test_keyframes.py`：类型不对 → 422 `chapter.keyframe.bad_type`；过大 → 422 `common.image_too_big`（`params == {"mb": 8}`）；没有的镜头 → 404 `chapter.keyframe.no_shot`（`params["shot"]`）；取不存在的关键帧 → 404 `chapter.keyframe.not_found`。
  - `test_style_image.py`：类型不对 → `novel.style.bad_type`；过大 → `common.image_too_big`；没有风格图 → 404 `novel.style.not_found`；别人的小说 → 404 `novel.not_found`。
  - `test_admin.py` :276：`r.status_code == 429 and r.json()["detail"]["code"] == "usage.monthly_cap"`。
  - `test_novels.py` 或新开一节测 `library`：`create_work(U, " ")` → `LibraryError`（仍是 `ValueError`），`code == "library.empty_title"`；`upsert_card` 三条与 `delete_card` 未知类别 → `novel.asset.*`。
  - `test_messages.py`：`dump_codes()["novel.unknown_params"]["params"] == ["keys"]`、`dump_codes()["chapter.version.not_adoptable"]["params"] == []`。

- [ ] **Step 2: 运行确认失败。**

- [ ] **Step 3: 登记**

  ```python
  register("common.image_too_big", "图片为空或超过 {mb}MB")
  # 小说与长期记忆
  register("novel.bad_id", "非法的 ID：{id}")
  register("novel.not_found", "小说不存在")
  register("novel.empty_title", "小说标题不能为空")
  register("novel.title_taken", "《{title}》已存在")
  register("novel.unknown_params", "未知的制作参数：{keys}")
  register("novel.asset.unknown_kind", "未知的资产类别：{kind}")
  register("novel.asset.no_id", "资产卡必须带 id")
  register("novel.asset.no_name", "资产卡必须有名称")
  register("novel.asset.not_found", "资产卡不存在")
  register("novel.asset.id_mismatch", "卡片 id 与路径不一致：{got} != {want}")
  register("novel.lifecycle.unknown_character", "资产库里没有角色 {id}")
  register("novel.lifecycle.unknown_type", "未知的状态类型：{type}（可选 {options}）")
  register("novel.lifecycle.unknown_status", "未知的状态：{status}")
  register("novel.lifecycle.not_found", "生命周期记录不存在")
  register("novel.constraint.no_text", "限制必须写明规则（text）")
  register("novel.constraint.not_found", "限制不存在")
  register("novel.style.bad_type", "风格参考图只收 PNG / JPEG / WebP 图片")
  register("novel.style.not_found", "这部小说还没有风格参考图")
  # 章节、版本、关键帧
  register("chapter.not_found", "章节不存在")
  register("chapter.empty_title", "章节标题不能为空")
  register("chapter.text_locked", "本章已有采用版，原文已锁定；要改原文请新建章节")
  register("chapter.no_text", "本章还没有原文")
  register("chapter.no_adopted", "本章还没有采用版")
  register("chapter.synopsis_too_long", "每章摘要不超过 {max} 字（现在 {len} 字）")
  register("chapter.version.not_found", "版本不存在")
  register("chapter.version.adopted_delete", "这是本章的采用版，先采用别的版本再删")
  register("chapter.version.busy", "这个版本还有片段在出，等出完或失败后再删")
  register("chapter.version.not_adoptable", "这个版本还不能采用：只有转换成功、且人工编辑后仍通过复验的版本可以")
  register("chapter.version.later_adopted", "后面的章节（{names}）已经接着本章的编号转换过，"
                                            "本章不能再换采用版；要换，先删掉或重转后面的章节")
  register("chapter.keyframe.bad_type", "关键帧只收 PNG / JPEG / WebP 图片")
  register("chapter.keyframe.no_shot", "这个版本里没有镜头 {shot}")
  register("chapter.keyframe.not_found", "这个镜头还没有关键帧")
  # 用量
  register("usage.monthly_cap", "本月用量已达上限，请联系管理员")
  # 旧资产库
  register("library.empty_title", "作品名不能为空")
  ```
  - **文字变化**：
    - `novel.bad_id`、`novel.asset.id_mismatch`：原文用 `{x!r}`（带引号），现在不带引号。
    - `novel.unknown_params`：原文是 Python 列表写法 `['a', 'b']`，现在列表参数由 `_zh_value` 用「、」连接。
    - `chapter.version.not_adoptable`：原文带内部状态值（「这个版本的状态是 failed，不能采用（…）」），现在不带（spec C）。
    - 其余与原文一致：`names`、`options` 传列表，`_zh_value` 用「、」连接，与原 `'、'.join(...)` 相同。

- [ ] **Step 4: 实现**
  - `novels.py`：
    - `from server.messages import UserError`；`class NovelError(UserError, ValueError)`、`class NotFound(UserError, LookupError)`；`Busy(NovelError)` 不变。
    - 逐个 raise 改 `.of(...)`，例如：
      - `_check_id`：`raise NovelError.of("novel.bad_id", id=str(value))`；
      - `adopt_version` 两处：`raise NovelError.of("chapter.version.not_adoptable")`；`raise NovelError.of("chapter.version.later_adopted", names=[c["title"] for c in later])`；
      - `_check_lifecycle_fields`：`raise NovelError.of("novel.lifecycle.unknown_type", type=kind, options=list(LIFECYCLE_TYPES))`；
      - 关键帧与风格图大小：`raise NovelError.of("common.image_too_big", mb=KEYFRAME_MAX_BYTES // 1024 // 1024)`；
      - `assistant_db` 的「小说不存在」：`NotFound.of("novel.not_found")`（文字相同，助手侧照旧拿 `str(e)`）。
    - 扫描结果（Step 5）必须为零。
  - `library.py`：`from server.messages import UserError`；新增 `class LibraryError(UserError, ValueError): """旧资产库的输入错误（仍是 ValueError，现有 except 照样接住）。"""`；`create_work` → `LibraryError.of("library.empty_title")`；`upsert_card`、`delete_card` 的三条 → `LibraryError.of("novel.asset.unknown_kind", kind=kind)` 等（R5）。
  - `store.py` `_path`：行尾 `# i18n: internal`（R6）。
  - `app.py`：
    - `novel_user` 两条 `print` 行尾 `# i18n: internal`。
    - `_novel_call`：三个分支都 `raise HTTPException(<状态>, detail=to_detail(e))`。
    - `_clean_params`：`raise HTTPException(422, detail=msg("novel.unknown_params", keys=sorted(unknown)))`。
    - `_start_version`：`detail=msg("chapter.no_text")`；`detail=msg("usage.monthly_cap")`。
    - `memory_asset_upsert`：`detail=msg("novel.asset.id_mismatch", got=str(card.get("id")), want=card_id)`。
    - `render_plan`：`except ValueError as e: raise HTTPException(400, detail=to_detail(e))`；`raise HTTPException(404, detail=msg("chapter.version.not_found"))`；「分镜结构不完整」那行行尾 `# i18n: todo(4)`。
  - 助手不受影响：`assistant/actions.py:25` 的 `_op` 对 dict 形状的 detail 取 `message`（中文兜底）给模型；`assistant_undo` 照旧 `str(e)`（子计划 4 再改）。助手测试必须保持通过。
  - `zh.ts`/`en.ts`：`srv.common.image_too_big`、`srv.novel.*`、`srv.chapter.*`（含 `version`、`keyframe` 子节点）、`srv.usage.monthly_cap`、`srv.library.empty_title`。en 示例：
    - `novel.title_taken` → `'"{title}" already exists.'`
    - `novel.unknown_params` → `'Unknown production settings: {keys}'`
    - `chapter.text_locked` → `'This chapter has an adopted version, so its source text is locked. Create a new chapter to change the text.'`
    - `chapter.version.not_adoptable` → `'This version can't be adopted yet. Only versions that converted successfully and still pass re-verification after edits can be adopted.'`
    - `chapter.version.later_adopted` → `'Later chapters ({names}) were converted continuing this chapter's numbering, so this chapter can't switch versions. Delete or reconvert those chapters first.'`
    - `chapter.version.busy` → `'Clips from this version are still generating. Delete it after they finish or fail.'`
    - `common.image_too_big` → `'The image is empty or larger than {mb} MB.'`
    - `usage.monthly_cap` → `'You've reached this month's usage limit. Please contact the administrator.'`

- [ ] **Step 5: 跑扫描**：`cd backend && .venv/bin/python tests/server/test_i18n_scan.py` 打印 `ALL PASS`（novels、library、store 全文件，app 上列函数）。
- [ ] **Step 6: 生成 JSON、跑全部校验并提交**。`git add backend/server/novels.py backend/server/library.py backend/server/store.py backend/server/app.py backend/server/messages.py backend/server/messages_codes.json backend/tests/server/test_novels.py backend/tests/server/test_keyframes.py backend/tests/server/test_style_image.py backend/tests/server/test_admin.py backend/tests/server/test_messages.py backend/tests/server/test_i18n_scan.py frontend/src/i18n/zh.ts frontend/src/i18n/en.ts`。提交信息示例：「小说、章节、版本与长期记忆报错带代码：存储层异常混入 UserError，接口统一 to_detail；未知制作参数、本章无原文、月上限、卡片 id 不一致、渲染任务包的版本 id 改为消息对象；扫描补上 Busy」。

---

### Task 4: 持久化失败（章后整理失败带编号、版本 error_msg 就绪）

**Files:**
- Modify: `backend/server/app.py`（`_run_digest`、`chapters_digest`）
- Modify: `backend/server/novels.py`（`create_version`、`update_version_state`）
- Modify: `backend/server/messages.py`、`messages_codes.json`
- Modify: `backend/tests/server/test_i18n_scan.py`（app 函数集合加 `_run_digest`、`chapters_digest`）
- Modify: `frontend/src/types.ts`（`DigestState.error_msg?: ServerMsg | null`、`VersionRecord.error_msg?: ServerMsg | null`）、`components/workflow/VersionBar.tsx`、`App.tsx`（:503 失败版本提示）、`zh.ts`/`en.ts`（`srv.chapter.digest.*`、`flow.digest.off`）
- Test: `backend/tests/server/test_novels.py`（章后整理段，约 :200-:260）、`frontend/tests/chapter.test.tsx`（或 `grep -ln "digest" tests/` 里覆盖 VersionBar 的那个）、`frontend/tests/flow.test.tsx`

- [ ] **Step 1: 写失败测试**
  - `test_novels.py`：
    - 章后整理失败：把 `app_mod._digest_chat` 换成会抛 `RuntimeError("model exploded sk-…")` 的桩（照现有 FakeChat 的替换写法），等 `chapter["digest"]["status"] == "failed"`；断言：
      - `d["error_msg"]["code"] == "chapter.digest.failed"`，`d["error_msg"]["params"] == {}`，`len(d["error_msg"]["ref"]) == 8`；
      - `d["error"]` 以 `chapter.digest.failed` 的中文兜底开头、含编号，**不含** `RuntimeError` 与密钥；
      - `error_refs.find(ref)` 的 `detail` 含 `RuntimeError`、`where` 以 `digest ` 开头、`user_id == U`。
    - 开关关闭：`load_settings` 桩的 `chapter_digest=False` 时 `chapters_digest` → 422 `detail["code"] == "chapter.digest.off"`；`app` logger（`render.app`）收到含 `STORYBOARD_CHAPTER_DIGEST` 的 WARNING。
    - 版本：`create_version` 后记录里有 `"error_msg": None`；`update_version_state(..., "failed", error="x", error_msg={"code": "common.internal", "params": {}})` 后读回两个字段都在；不传 `error_msg` 时不动它。
  - 前端：
    - VersionBar：`chapter.digest = {status: 'failed', at, error: '旧中文', error_msg: {code: 'chapter.digest.failed', params: {}, ref: 'K7Q2M9XD'}}` 时，英文界面显示英文原因与「reference K7Q2M9XD」；只有 `error` 时原样显示；`flow.digest.off` 的中英文都不含 `STORYBOARD_CHAPTER_DIGEST`。
    - App：打开一个 `status: 'failed'` 且带 `error_msg` 的版本，提示条按代码渲染（旧数据只有 `error` 时取第一行，与现在一致）。

- [ ] **Step 2: 运行确认失败。**

- [ ] **Step 3: 登记**

  ```python
  register("chapter.digest.off", "章后整理功能没有开启，请联系管理员")
  register("chapter.digest.failed", "章后整理没有完成，可以稍后重跑；仍失败请联系管理员")
  ```
  - **文字变化**：`chapter.digest.off` 去掉环境变量名（spec C）；章后整理失败原因不再是 `repr(e)`。

- [ ] **Step 4: 实现**
  - `_run_digest` 的 `except Exception as e`：
    ```python
    except Exception as e:  # 网络/解析/章节被删——都只是这一步没做成
        fields: dict = {}
        render_session.set_error(fields, error_refs.unexpected(
            e, "chapter.digest.failed", user_id=user_id, where=f"digest {nid}/{cid}", logger=log))
        try:
            novels.set_digest_state(user_id, nid, cid, "failed", **fields)
        except (OSError, ValueError, LookupError):
            pass
    ```
  - `chapters_digest`：`log.warning("章后整理已关闭（STORYBOARD_CHAPTER_DIGEST=0），拒绝手动重跑 user=%s novel=%s chapter=%s", user["id"], nid, cid)  # i18n: internal`，再 `raise HTTPException(422, detail=msg("chapter.digest.off"))`。
  - `novels.create_version`：`record` 加 `"error_msg": None`；`update_version_state` 的字段循环加 `"error_msg"`。产出点（`app._execute` 写 `error=`）**不在本 Task**，留给子计划 4（spec 子计划 3 A「持久化错误」）。
  - 前端：
    - `VersionBar.tsx`：`failed: t('flow.digest.failed', { reason: itemError(d, locale) || t('flow.digest.unknown') })`（`itemError` 已是 `error_msg` 优先、回落 `error`）。
    - `App.tsx` :502-504：`t('app.versionFailed', { msg: v.error_msg ? formatMsg(v.error_msg) : (v.error ?? '').split('\n')[0] })`。Task 5 会把这里改为结构化提示条，这一步先保证按代码渲染。
    - `flow.digest.off`：zh `'未开启，可在小说页手动补'`，en `'not enabled; fill in manually on the novel page'`。
    - `srv.chapter.digest.*` 中英文。en 示例：`off` → `'Chapter digest isn't enabled. Please contact the administrator.'`；`failed` → `'The chapter digest didn't finish. Rerun it later; if it keeps failing, contact the administrator.'`。

- [ ] **Step 5: 跑全部校验并提交**。`git add backend/server/app.py backend/server/novels.py backend/server/messages.py backend/server/messages_codes.json backend/tests/server/test_novels.py backend/tests/server/test_i18n_scan.py frontend/src/types.ts frontend/src/components/workflow/VersionBar.tsx frontend/src/App.tsx frontend/src/i18n/zh.ts frontend/src/i18n/en.ts frontend/tests/chapter.test.tsx frontend/tests/flow.test.tsx`（按实际改到的测试文件调整）。提交信息示例：「章后整理失败改为带参考编号的消息对象，不再把 Python 异常原文存进章节；关闭开关的提示不再出现环境变量名；版本记录可存 error_msg（产出点留给子计划 4），失败版本与章后整理状态按代码渲染」。

---

### Task 5: 前端：小说相关错误按界面语言渲染

**Files:**
- Modify: `frontend/src/App.tsx`（`msg` 助手、`alert` 状态、:1135-:1136 两处渲染）
- Modify: `frontend/src/useJob.ts`（错误状态改 `MsgLike`）
- Modify: `frontend/src/useKeyframes.ts`、`components/TimelineCanvas.tsx`（:1068）
- Modify: `frontend/src/components/NovelPage.tsx`、`NovelOverview.tsx`、`NovelAssets.tsx`、`CanvasPanels.tsx`、`params/StyleImageField.tsx`、`RenderView.tsx`
- Test: `frontend/tests/flow.test.tsx`、`canvas.test.tsx`、`shelf.test.tsx`（按 `grep -ln "<组件名>" tests/` 找实际覆盖的文件）

- [ ] **Step 1: 列出调用点**：`cd frontend && grep -rnE "e instanceof Error \? e\.message|err instanceof Error \? err\.message|const (msg|err) = \(e: unknown\)" src | grep -v "src/lib/assistantSession\|components/assistant\|components/admin"`。每一处都要在本 Task 或 Task 6 里改到（admin 留给 Task 6；`styleImages.ts` 是本机存储报错，不是接口错误，不改）。

- [ ] **Step 2: 写失败测试**
  - App 提示条（`flow.test.tsx`，照该文件 :209 起的桩后端写法）：`GET /novels/{nid}/chapters/{cid}` 返回 `404 {"detail": {"code": "chapter.not_found", "params": {}, "message": "章节不存在"}}`，中文界面提示条含「章节不存在」；切到英文后同一条提示变成 `chapter.not_found` 的英文，且整句的前缀（`app.err.chapter`）也是英文。
  - 提交转换：`POST …/versions` 返回 `422 {"detail": {"code": "chapter.no_text", …}}`，`app.err.submit` 提示在切换语言后跟着变。
  - toast：小说页某个操作失败（`grep -n "notice.log\|noticeLog" tests/*.tsx` 找到读 toast 的现有写法）时，toast 描述是按当前语言渲染的文字，不是中文兜底：英文界面下 `PUT …/memory/assets/…` 返回 `novel.asset.no_name` 时，toast 里是英文。
  - 画布侧栏（`canvas.test.tsx`）：保存限制返回 `novel.constraint.no_text`，提示在切换语言后跟着变。
  - 关键帧上传（`canvas.test.tsx` 或覆盖 TimelineCanvas 的文件）：`PUT …/keyframes/S01` 返回 `chapter.keyframe.bad_type`，提示在切换语言后跟着变。
  - 所有用例另加：结构化 detail 不能显示成 `[object Object]`（照 flow.test.tsx:1197 的写法）。

- [ ] **Step 3: 运行确认失败。**

- [ ] **Step 4: 实现**
  - `App.tsx`：
    - 顶部 `const msg = (e: unknown) => errText(e)`（从 `serverMsg` 导入 `errText`）：所有 `notice.err(...)` 里的 `msg(e)` 不用逐个改，弹出时就按当前语言格式化。
    - 页面提示条改为存「文案键 + 错误值」，渲染时再拼：
      ```ts
      /** 页面提示条：存文案键与错误值，渲染时按当前语言拼（切换语言后跟着变） */
      type AlertState = { key?: MsgKey; err?: MsgLike }
      const [alert, setAlert] = useState<AlertState | null>(null)
      const alertText = (a: AlertState) => (a.key ? t(a.key, { msg: formatMsg(a.err, locale) }) : formatMsg(a.err, locale))
      ```
      各 `setAlert` 改写：
      - `setAlert(msg(e))` → `setAlert({ err: errValue(e) })`（:189、:1125）；
      - `setAlert(t('app.err.preview', { msg: msg(e) }))` → `setAlert({ key: 'app.err.preview', err: errValue(e) })`，`app.err.version`、`app.err.chapter`、`app.err.createNovel` 同理；
      - `f.t('app.err.novel', { msg: msg(nr.reason) })` → `{ key: 'app.err.novel', err: errValue(nr.reason) }`，`app.err.chapter` 同理；
      - Task 4 写的失败版本提示 → `setAlert(v.status === 'failed' ? { key: 'app.versionFailed', err: v.error_msg ?? (v.error ?? '').split('\n')[0] } : { key: 'app.versionEmpty' })`；
      - `setAlert(t('app.savedInvalid'))` → `setAlert({ key: 'app.savedInvalid' })`。
      渲染：`{alert && <p className="alert">{alertText(alert)}</p>}`；`{error && <p className="alert">{t('app.err.submit', { msg: formatMsg(error, locale) })}</p>}`。`app.versionEmpty`、`app.savedInvalid` 没有 `{msg}` 占位，多传的 `msg` 被忽略。`locale` 取自 `useI18n()`。
    - `grep -n "setAlert(" src/App.tsx` 改完后不得再有字符串参数（`null` 除外）。
  - `useJob.ts`：`const [error, setError] = useState<MsgLike>(null)`，两处 `setError(e instanceof Error ? …)` 改 `setError(errValue(e))`。`grep -rn "useJob(" src` 找到所有使用处，渲染处用 `formatMsg`。
  - `useKeyframes.ts`：错误状态改为 `{ key: 'keyframes.promptFailed' | 'keyframes.readFailed' | 'keyframes.uploadFailed' | 'keyframes.deleteFailed'; err: MsgLike } | null`，四处 `setError(tr(...))` 改为 `setError({ key: '…', err: errValue(e) })`。`TimelineCanvas.tsx:1068` 渲染 `t(kf.error.key, { error: formatMsg(kf.error.err, locale) })`；`grep -rn "\.error" src | grep -i "kf\.\|keyframe"` 确认没有别的使用处。
  - `NovelPage.tsx`、`NovelOverview.tsx`、`NovelAssets.tsx`、`StyleImageField.tsx`：本地的 `err`（或内联的 `e instanceof Error ? …`）换成 `errText`（toast，弹出时格式化即可）。
  - `CanvasPanels.tsx`：提示条改存 `{ what: string; err: MsgLike }`，渲染 `t('canvas.panel.failedWith', { what: a.what, error: formatMsg(a.err, locale) })`（`what` 是调用方传入的已翻译动作名，见 R9）。
  - `RenderView.tsx`：`const [err, setErr] = useState<MsgLike>(null)`；`setErr(errValue(e))`；渲染 `formatMsg(err, locale)`。验证门（`e.verification`）的处理不变。

- [ ] **Step 5: 跑全部校验并提交**。`git add` 本 Task 改到的源文件与测试文件（逐个列出，不用通配）。提交信息示例：「小说、章节、版本、资产、记忆、关键帧与风格图的接口报错改为存消息对象：页面提示条存文案键与错误值，渲染时按当前语言拼；提交转换、关键帧、画布侧栏、渲染任务包的错误切换语言后跟着变；toast 弹出时按当前语言格式化」。

---

### Task 6: 管理后台（admin、usage、pricing 带代码；错误记录接口与页签）

**Files:**
- Modify: `backend/server/admin.py`、`backend/server/usage.py`、`backend/server/pricing.py`
- Modify: `backend/server/app.py`（`_admin_call`、`admin_usage`、`admin_usage_csv`、`admin_pricing_put`；新增 `admin_errors`、`admin_error_get`）
- Modify: `backend/server/messages.py`、`messages_codes.json`
- Modify: `backend/tests/server/test_i18n_scan.py`：
  - `MODULES` 加 `"server/admin.py": None`、`"server/usage.py": None`、`"server/pricing.py": None`；
  - app 函数集合加 `_admin_call`、`admin_usage`、`admin_usage_csv`、`admin_pricing_put`、`admin_errors`、`admin_error_get`。
- Modify: `frontend/src/api.ts`（`adminErrors`、`adminErrorRef`）、`types.ts`（`ErrorRefRow`；`AdminJobs.failed[].error_msg?`）
- Modify: `frontend/src/components/admin/AdminView.tsx`、`format.ts`、`useLoad.ts`、`LoadState.tsx`、`JobsTab.tsx`、`Users.tsx`、`UsageTab.tsx`；Create: `ErrorsTab.tsx`
- Modify: `frontend/src/i18n/zh.ts`、`en.ts`（`srv.admin.*`、`srv.usage.bad_group`、`admin.tabs.errors`、`admin.errors.*`）
- Test: `backend/tests/server/test_admin.py`、`test_usage.py`、`frontend/tests/admin.test.tsx`

- [ ] **Step 1: 写失败测试**
  - `test_admin.py`：
    - `part_admin`：:143 改为 `assert e.code == "admin.last_admin"`；另加：一次改两项 → `admin.one_field`；`disabled` 非布尔 → `admin.bad_disabled`；停用自己 → `admin.self_disable`；未知角色 → `admin.bad_role`；改自己角色 → `admin.self_role`；负月上限 → `admin.bad_cap`；未知字段 → `admin.bad_field`（`params == {"field": "x"}`）；不存在的用户 → `admin.NotFound` 且 `code == "auth.user_not_found"`。
    - `reset_password` 短密码 → `AdminError` 且 `code == "auth.password_short"`、`params == {"min": 6}`（下层代码原样保留）；`usage_report("bogus", …)` → `AdminError` `usage.bad_group`。
    - `jobs_view` 的失败条带 `error_msg`（版本记录里有就原样给，没有为 None）。
    - `part_api`：`/admin/users/ffffffffffff` → 404 `auth.user_not_found`；`group=bogus` → 400 `usage.bad_group`；`days=5` → 422 `admin.bad_days`（`usage.csv` 同）；坏价格表 → 400 `admin.pricing.bad_price`；空价格表 → `admin.pricing.empty`。
    - 错误记录接口：先 `error_refs.record("common.internal", "boom", user_id=<bob 的 id>, where="GET /x")`；`GET /admin/errors` → `{"errors": [...]}`，第一条 `ref` 相同、`username == "bob"`、有 `detail`；`GET /admin/errors/<ref 小写、带连字符>` → 同一条；不存在 → 404 `admin.error_ref.not_found`（`params["ref"]` 为规范化后的编号）；普通用户 → 403 `auth.admin_only`；`limit` 超出 1–1000 → 422（FastAPI 校验）。
  - `test_usage.py`：`pricing.save({"models": {}})` → `PricingError`（仍是 `ValueError`），`code == "admin.pricing.empty"`；`{"models": {"m": "x"}}` → `admin.pricing.bad_row`（`params == {"name": "m"}`）；负单价 → `admin.pricing.bad_price`（`params` 有 `name`、`key`）；`usage.aggregate(rows, "bogus", table)` → `UsageError` `usage.bad_group`。
  - `admin.test.tsx`（照文件里现有的桩后端写法）：
    - 读取失败：`/admin/overview` 返回 `500 {"detail": {"code": "common.internal", "params": {}, "message": "…（参考编号 K7Q2M9XD）", "ref": "K7Q2M9XD"}}`，错误条显示中文与编号；切到英文后错误条变成英文、编号仍在。
    - 操作失败 toast：停用自己返回 `400 admin.self_disable` 时，toast 按当前语言渲染。
    - 任务页：失败条带 `error_msg` 时英文界面显示英文；只有 `error` 时原样显示。
    - 错误记录页签：点「错误记录」后请求 `GET /admin/errors`，表格显示编号、用户、说明（按代码渲染）、位置；在查找框输入 `k7q2-m9xd` 回车 → 请求 `GET /admin/errors/k7q2-m9xd`，显示那一条的 `detail`；查不到时显示 `admin.error_ref.not_found` 的文案。

- [ ] **Step 2: 运行确认失败。**

- [ ] **Step 3: 登记**（中文与现在一字不差，除注明的）：

  ```python
  # 管理后台
  register("admin.one_field", "一次只能修改一项")
  register("admin.bad_disabled", "disabled 必须是 true 或 false")
  register("admin.self_disable", "不能停用自己")
  register("admin.last_admin", "至少保留一个管理员")
  register("admin.bad_role", "角色只能是 admin 或 user")
  register("admin.self_role", "不能修改自己的角色")
  register("admin.bad_cap", "月上限必须是非负数，或留空表示不限")
  register("admin.bad_field", "不支持修改 {field}")
  register("admin.bad_days", "days 只能是 7、30、90")
  register("admin.pricing.empty", "价格表必须包含至少一个模型")
  register("admin.pricing.bad_row", "模型 {name} 的单价格式不对")
  register("admin.pricing.bad_price", "模型 {name} 的 {key} 单价必须是非负数")
  register("admin.error_ref.not_found", "没有这个参考编号：{ref}")
  register("usage.bad_group", "不支持的分组：{group}")
  ```
  - **文字变化**：`admin.pricing.bad_row` 原文 `{name!r}` 带引号，现在不带。

- [ ] **Step 4: 实现**
  - `admin.py`：
    - `from server.messages import UserError`；`class AdminError(UserError, Exception)`；`NotFound(AdminError)` 不变。
    - 各 raise 改 `.of(...)`；`_user`：`raise NotFound.of("auth.user_not_found")`。
    - 下层带代码的异常原样换成 `AdminError`（R4）：
      ```python
      def _as_admin(e: Exception) -> AdminError:
          """下层（auth、usage）带代码的异常换成 AdminError（400），代码与参数不变；没带代码的照旧取原文。"""
          if isinstance(e, UserError) and e.code:
              return AdminError.of(e.code, **e.params)
          return AdminError(str(e))
      ```
      `reset_password`、`usage_report` 里 `raise AdminError(str(e))` 改 `raise _as_admin(e) from e`。
    - `jobs_view` 失败条加 `"error_msg": v.get("error_msg")`。
    - `main()` 里所有 `print` 行尾 `# i18n: internal`（运维命令行，保持中文）。
  - `usage.py`：`class UsageError(UserError, ValueError)`；`aggregate` 抛 `UsageError.of("usage.bad_group", group=group)`。
  - `pricing.py`：`class PricingError(UserError, ValueError)`；`_validate` 三处：`PricingError.of("admin.pricing.empty")`、`PricingError.of("admin.pricing.bad_row", name=str(name))`、`PricingError.of("admin.pricing.bad_price", name=name, key=k)`。
  - `app.py`：
    - `_admin_call`：`raise HTTPException(404 / 400, detail=to_detail(e))`。
    - `admin_usage`、`admin_usage_csv`：`detail=msg("admin.bad_days")`。
    - `admin_pricing_put`：`raise HTTPException(400, detail=to_detail(e))`。
    - 新增：
      ```python
      def _with_username(rows: list) -> list:
          names = {u["id"]: u["username"] for u in auth.list_users_safe()}
          return [{**r, "username": names.get(r.get("user_id"))} for r in rows]


      @app.get("/admin/errors")
      def admin_errors(limit: int = Query(200, ge=1, le=1000), user: dict = Depends(admin_user)):
          return {"errors": _with_username(error_refs.recent(limit))}


      @app.get("/admin/errors/{ref}")
      def admin_error_get(ref: str, user: dict = Depends(admin_user)):
          row = error_refs.find(ref)
          if row is None:
              raise HTTPException(404, detail=msg("admin.error_ref.not_found", ref=error_refs.normalize(ref)))
          return _with_username([row])[0]
      ```
  - 前端：
    - `format.ts`：`export { errText } from '@/i18n/serverMsg'`（删掉本地的 `e.message` 版本），`Users.tsx`、`UsageTab.tsx` 的 toast 自动按当前语言格式化。
    - `useLoad.ts`：`const [error, setError] = useState<MsgLike>(null)`；`setError(errValue(e))`。
    - `LoadState.tsx`：`ErrorBar({ error }: { error: MsgLike; … })`，渲染 `formatMsg(error, locale)`（`locale` 取自 `useI18n()`）。
    - `JobsTab.tsx`：失败原因 `const text = itemError(j, locale)`，summary 与 `<pre>` 都用 `text`。
    - `types.ts`：
      ```ts
      export interface ErrorRefRow {
        ref: string; at: string; user_id: string | null; username: string | null
        code: string; params: Record<string, unknown>; where: string; detail: string
      }
      ```
      `AdminJobs.failed[]` 加 `error_msg?: ServerMsg | null`。
    - `api.ts`：
      ```ts
      export async function adminErrors(): Promise<ErrorRefRow[]> {
        return (await req<{ errors: ErrorRefRow[] }>('/admin/errors')).errors
      }

      export function adminErrorRef(ref: string) {
        return req<ErrorRefRow>(`/admin/errors/${encodeURIComponent(ref.trim())}`)
      }
      ```
    - `AdminView.tsx`：`type Tab = … | 'errors'`，`TABS` 末尾加 `'errors'`，`{tab === 'errors' && <ErrorsTab />}`。
    - `ErrorsTab.tsx`（新）：
      ```tsx
      import { useState } from 'react'
      import { Inbox, RefreshCw, Search } from 'lucide-react'
      import { EmptyState } from '@/components/common/EmptyState'
      import { Button } from '@/components/ui/button'
      import { useI18n } from '@/i18n/core'
      import { errValue, formatMsg } from '@/i18n/serverMsg'
      import type { MsgLike } from '@/i18n/serverMsg'
      import { adminErrorRef, adminErrors } from '../../api'
      import type { ErrorRefRow } from '../../types'
      import { when } from './format'
      import { ErrorBar, TableSkeleton } from './LoadState'
      import { useLoad } from './useLoad'

      /** 错误记录：意外失败的参考编号（最新在前），可按编号查找；detail 已在服务端脱敏。 */
      export function ErrorsTab() {
        const { t, locale } = useI18n()
        const { data, error, reload } = useLoad(adminErrors, [])
        const [q, setQ] = useState('')
        const [hit, setHit] = useState<ErrorRefRow | null>(null)
        const [miss, setMiss] = useState<MsgLike>(null)
        const c = (k: string) => t(`admin.errors.cols.${k}` as 'admin.errors.cols.time')
        const explain = (r: ErrorRefRow) => formatMsg({ code: r.code, params: r.params }, locale)
        const lookup = async () => {
          setHit(null); setMiss(null)
          if (!q.trim()) return
          try { setHit(await adminErrorRef(q)) } catch (e) { setMiss(errValue(e)) }
        }
        const row = (r: ErrorRefRow) => (
          <tr key={r.ref}>
            <td>{when(r.at)}</td><td>{r.username ?? r.user_id ?? '—'}</td>
            <td className="adm__mono">{r.ref}</td><td>{explain(r)}</td><td className="adm__mono">{r.where || '—'}</td>
            <td>
              <details className="adm__err-detail">
                <summary>{t('admin.errors.detail')}</summary>
                <pre>{r.detail}</pre>
              </details>
            </td>
          </tr>
        )
        const head = (
          <thead>
            <tr><th>{c('time')}</th><th>{c('user')}</th><th>{c('ref')}</th><th>{c('what')}</th><th>{c('where')}</th><th>{c('detail')}</th></tr>
          </thead>
        )
        let body
        if (error) body = <ErrorBar error={error} onRetry={reload} />
        else if (!data) body = <TableSkeleton />
        else if (!data.length) body = <EmptyState icon={<Inbox aria-hidden />} title={t('admin.errors.empty')} hint={t('admin.errors.emptyHint')} />
        else body = <table className="adm__table">{head}<tbody>{data.map(row)}</tbody></table>
        return (
          <section className="adm__sec">
            <form className="adm__bar" onSubmit={(e) => { e.preventDefault(); void lookup() }}>
              <input className="adm__search" value={q} onChange={(e) => setQ(e.target.value)}
                     placeholder={t('admin.errors.placeholder')} aria-label={t('admin.errors.lookup')} />
              <Button size="sm" type="submit"><Search aria-hidden />{t('admin.errors.lookup')}</Button>
              <Button size="sm" variant="outline" type="button" onClick={reload}><RefreshCw aria-hidden />{t('admin.errors.refresh')}</Button>
            </form>
            {miss && <p role="alert" className="text-sm text-destructive">{formatMsg(miss, locale)}</p>}
            {hit && <table className="adm__table">{head}<tbody>{row(hit)}</tbody></table>}
            {body}
          </section>
        )
      }
      ```
      `adm__search`、`adm__mono` 若样式表里没有，照 `Users.tsx` 搜索框与 `AuditTab` 的 `adm__json` 现有样式补两条（`grep -n "adm__" src/styles/*.css`）。
    - `zh.ts`：`admin.tabs.errors: '错误记录'`；`admin.errors: { refresh: '刷新', lookup: '查找', placeholder: '输入用户报来的参考编号', empty: '还没有错误记录', emptyHint: '意外失败会带参考编号记在这里（保留最近 1000 条）。', detail: '详情', cols: { time: '时间', user: '用户', ref: '参考编号', what: '说明', where: '位置', detail: '详情' } }`；`srv.admin.*`、`srv.usage.bad_group`。en 对应：`tabs.errors: 'Errors'`、`placeholder: 'Reference reported by the user'`、`emptyHint: 'Unexpected failures are logged here with a reference (latest 1,000 kept).'` 等；`srv.admin.error_ref.not_found` → `'No error with reference {ref}.'`；`srv.admin.last_admin` → `'At least one administrator must remain.'`；`srv.admin.bad_days` → `'days must be 7, 30 or 90.'`。

- [ ] **Step 5: 跑全部校验并提交**。`git add backend/server/admin.py backend/server/usage.py backend/server/pricing.py backend/server/app.py backend/server/messages.py backend/server/messages_codes.json backend/tests/server/test_admin.py backend/tests/server/test_usage.py backend/tests/server/test_i18n_scan.py frontend/src/api.ts frontend/src/types.ts frontend/src/components/admin/AdminView.tsx frontend/src/components/admin/ErrorsTab.tsx frontend/src/components/admin/format.ts frontend/src/components/admin/useLoad.ts frontend/src/components/admin/LoadState.tsx frontend/src/components/admin/JobsTab.tsx frontend/src/components/admin/Users.tsx frontend/src/components/admin/UsageTab.tsx frontend/src/i18n/zh.ts frontend/src/i18n/en.ts frontend/tests/admin.test.tsx`（加上补了样式的 css 文件，如有）。提交信息示例：「管理后台报错带代码：用户操作、用量分组、统计天数与价格表校验改为消息对象，下层账号与用量错误转成管理错误时保留原代码；新增错误记录接口与页签，可按参考编号查到脱敏后的完整记录；后台读取错误、操作提示与失败任务原因按界面语言渲染」。

---

### Task 7: 收尾核对

**Files:**
- Modify（如需要）：`backend/tests/server/test_i18n_scan.py`、`backend/server/messages_codes.json`

- [ ] **Step 1: 扫描范围核对**：`test_i18n_scan.py` 的 `MODULES` 至少包含：
  - 全文件：`server/auth.py`、`server/novels.py`、`server/library.py`、`server/admin.py`、`server/usage.py`、`server/pricing.py`、`server/store.py`、`server/error_refs.py`；
  - app 函数集合：Task 2、3、4、6 列出的全部函数。

  `SINK_NAME` 含 `Busy`。扫描打印 `ALL PASS`。
- [ ] **Step 2: 零命中复核**（不依赖 `MODULES` 是否写全，直接扫七个模块与清单里的 app 函数；输出必须为空。改动前的基线是 79 处，另有 `Busy` 1 处当时扫不到）：

  ```bash
  cd backend && .venv/bin/python - <<'PY'
  import importlib.util
  spec = importlib.util.spec_from_file_location("scan", "tests/server/test_i18n_scan.py")
  m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
  for rel in ["server/auth.py", "server/novels.py", "server/library.py", "server/admin.py",
              "server/usage.py", "server/pricing.py", "server/store.py", "server/error_refs.py"]:
      for h in m.scan(rel, None):
          print(h)
  funcs = {"current_user", "admin_user", "register", "login", "novel_user", "_novel_call", "_clean_params",
           "_run_digest", "_start_version", "chapters_digest", "memory_asset_upsert", "render_plan",
           "_admin_call", "admin_usage", "admin_usage_csv", "admin_pricing_put", "admin_errors", "admin_error_get"}
  for h in m.scan("server/app.py", funcs):
      print(h)
  PY
  ```
- [ ] **Step 3: 标记核对**：`cd backend && grep -rn "i18n: todo(3)" server render` 为空；`grep -n "i18n: todo(4)" server/app.py` 只有 `render_plan` 里「分镜结构不完整」那一处是本计划加的（实施前先 `grep` 一次记下基线，确认本计划只新增这一处）。
- [ ] **Step 4: 面向最终用户**：
  - `grep -n "STORYBOARD_\|backend/.env\|_API_KEY" server/messages.py ../frontend/src/i18n/zh.ts ../frontend/src/i18n/en.ts` 输出为空；
  - `grep -n "repr(e)" server/app.py` 不再出现在 `_run_digest` 里。
- [ ] **Step 5: 错误记录不进 git**：`git status --short` 里不得出现 `error_refs.jsonl`（测试只写临时目录；`data/` 已在 `.gitignore`，`git check-ignore backend/data/error_refs.jsonl` 确认）。
- [ ] **Step 6: 代码表最新**：`.venv/bin/python -m server.messages --write && git diff --exit-code server/messages_codes.json`。
- [ ] **Step 7: 全部校验**（全局约束里的整套）。
- [ ] **Step 8: 有改动才提交**（只 add 改到的文件）。提交信息示例：「子计划 3 收尾：扫描覆盖账号、小说、管理与错误记录模块并清零」。

---

## 实施裁定

- **R1 编号放在哪**：裁定：消息对象顶层 `ref`，中文兜底末尾附「（参考编号 X）」，前端 `formatMsg` 对顶层 `ref` 附 `common.refSuffix`，结果里已有编号就不重复——理由：与代码无关、嵌套原因不受影响；旧前端、`ApiError.message` 和未改造的显示处也能看到编号——若错的代价：放进 `params` 的方案要给每个可能带编号的代码改模板。改回去只动 `with_ref` 与 `withRef` 两个函数，数据里多出的 `ref` 字段无害。
- **R2 500 兜底用中间件**：裁定：纯 ASGI 中间件，注册在 CORS 之内，不用 `@app.exception_handler(Exception)`——理由：后者在最外层的 ServerErrorMiddleware 里运行，响应不带 CORS 头，跨源前端读不到 detail；而且它会再抛一次，让 uvicorn 打出未脱敏的堆栈——若错的代价：若某个 Starlette 升级改变了中间件顺序，500 会丢 CORS 头，前端退回显示「Failed to fetch」。`test_error_refs.py` 第 4 节断言了 CORS 头，升级时会被发现。
- **R3 哪些失败带编号**：裁定：只有 `common.internal`、`chapter.digest.failed`、`film.submit.crashed`、`compose.crashed` 四类意外失败带编号；4xx 业务错误、配置类、厂商映射类不带——理由：编号只在「用户自己解决不了、原因只在服务器上」时有用；厂商映射类的日志已带请求 id、档位与原文——若错的代价：管理员反映厂商类错误也想按编号查时，在对应的失败写入点加一次 `record` + `with_ref` 即可，数据形状不变。
- **R4 下层错误的代码不丢**：裁定：admin 把 auth、usage 带代码的异常转成 `AdminError` 时用 `AdminError.of(e.code, **e.params)`，状态码仍是 400——理由：原来的 `AdminError(str(e))` 会把代码丢掉，前端只能显示中文兜底——若错的代价：同一句话在两个状态码下出现（auth 的 `auth.user_not_found` 在 admin 里是 400 而不是 404），与现在行为一致，不影响前端。
- **R5 library 复用 novel.asset 代码**：裁定：`library.upsert_card`/`delete_card` 的三条复用 `novel.asset.*`，只为「作品名不能为空」登记 `library.empty_title`——理由：文字完全相同，资产库已并进小说长期记忆，目前没有接口调用这些函数——若错的代价：以后旧资产库接回接口、需要不同文案时，再拆出 `library.asset.*`，前端加三个键。
- **R6 内部 raise 不登记代码**：裁定：`auth.user_dir`（用户 id 来自签过名的 token 与目录名）、`auth.update_user` 的字段白名单（只有 admin.py 以白名单字段调用）、`store._path`（只被迁移代码以目录里的文件名调用）标 `# i18n: internal`，不登记——理由：这些 raise 没有用户输入能触发；真触发了说明是程序错误，会被 R2 的中间件兜成带编号的 500——若错的代价：某条路径其实能被用户输入触发时，用户看到的是「服务器出了点问题（参考编号）」而不是具体原因，管理员按编号能查到原文。
- **R7 版本 error_msg 只做存储与显示**：裁定：子计划 3 只给版本记录加 `error_msg` 字段、存储层接受它、前端按它渲染；`app._execute` 写失败原因的产出点留给子计划 4——理由：版本失败原因全部来自转换任务路径（ConversionError、LLM 异常、其它运行期异常），与 job 进度、quality_report 在同一处，拆开改会让 `_execute` 改两次——若错的代价：子计划 4 交付前，失败版本仍只有中文 `error`，显示与现在一致。
- **R8 章后整理开关文案**：裁定：`chapter.digest.off` 写「章后整理功能没有开启，请联系管理员」，变量名进 `log.warning`；前端 `flow.digest.off` 同步去掉变量名——理由：spec 子计划 2 B 节原则，最终用户不认识环境变量——若错的代价：开发者在界面上看不到开关名，要看日志或 README。
- **R9 提示条里的动作名**：裁定：App 提示条存「文案键 + 错误值」，切换语言后整句都跟着变；画布侧栏 `CanvasPanels` 的提示条只存调用方已翻译好的动作名 `what` 与错误值，切换语言后错误部分跟着变、动作名保持原语言——理由：`what` 由多个调用方传入已翻译的字符串，改成键要动所有调用方，收益小——若错的代价：切换语言的那一刻，侧栏旧提示里会短暂出现中英混排，下一次操作就恢复。
- **R10 toast 不存值**：裁定：toast（`notice.err`）在弹出时用 `errText(e)` 按当前语言格式化，不随之后的切换语言重渲染（spec §6）——理由：toast 几秒后消失，没有「已显示的错误」需要跟着变——若错的代价：无。
- **R11 错误记录的上限与并发**：裁定：保留最近 1000 条，行数超过 2000 时整体重写为最后 1000 条；只在单进程内加锁——理由：服务是单进程部署（`STORYBOARD_SERVER_WORKERS` 是线程池），与 `usage.jsonl`、`admin_audit.jsonl` 的做法一致——若错的代价：以后改成多进程部署时，裁剪可能丢掉另一进程刚写的一行（只是丢一条记录，不影响用户看到的编号）。那时再改用文件锁。
- **R12 记录写盘失败**：裁定：`record` 写盘失败只记 `log.exception`，编号照常返回给用户——理由：报错本身不能被记账拖垮；同一内容已经写进日志，按编号在日志里 grep 仍能找到——若错的代价：管理后台查不到那一条，要去翻日志。
- **R13 runner 与合成的日志位置**：裁定：`record(..., logger=log)` 让堆栈写进调用方原来的 logger（`render.runner`、`render.app`），不改到 `server.errors`——理由：子计划 2 已有断言「`render.runner` 收到含 root、段 id 与堆栈的 ERROR」，日志排查习惯也不变——若错的代价：按 logger 名过滤 `server.errors` 的人会漏掉这两类，`ref=` 前缀仍能 grep 到。
- **R14 文字变化范围**：裁定：只有 spec C 节列出的几条中文兜底变化（`repr` 引号、列表连接、内部状态值、环境变量名、`repr(e)`、500 纯文本）；`admin.bad_days`、`admin.bad_disabled` 里的 `days`、`disabled` 是接口参数名，管理后台界面用下拉与开关挡住了，保持原文——理由：避免无谓改动现有文字——若错的代价：直接调接口的人看到参数名，本来就是给他看的。
- **R15 pydantic 422 不处理**：裁定：请求体校验失败的 422（`detail` 是列表）不在本次改，前端照旧显示原始响应文字——理由：登录、注册、重置密码的输入框已挡住空值，其余接口由前端构造请求体，用户触发不到——若错的代价：直接调接口时看到 FastAPI 的英文校验信息。

## 自查记录

- **覆盖 spec 子计划 3 A 节**：七个模块 → Task 2（auth）、3（novels、library、store）、6（admin、usage、pricing）。app 调用点见清单，每行都标了 Task。version.error → Task 4（存储与显示；产出点见 R7）。章后整理失败 → Task 4。前端显示处：登录 → Task 2；App、useJob、小说页、概览、资产、画布侧栏、风格图、关键帧、渲染任务包 → Task 5；VersionBar → Task 4；管理后台 → Task 6。
- **覆盖 B 节**：with_ref、记录、500 中间件、set_error 保留 ref、runner 与合成的意外异常、formatMsg → Task 1；章后整理 → Task 4；管理接口与页签 → Task 6。
- **覆盖 C、D 节**：代码在 Task 1–4、6 登记；文字变化逐条写在各 Task 的「文字变化」里；ast 扫描 → Task 2、3、4、6 逐步加，Task 7 复核。
- **名称一致**：后端 `error_refs.record`/`record_exc`/`unexpected`/`recent`/`find`/`normalize`/`user_of_root`、`messages.with_ref`/`REF_SUFFIX_ZH`；前端 `errText`、`withRef`、`common.refSuffix`、`ErrorRefRow`、`adminErrors`/`adminErrorRef`、`admin.errors.*`。各 Task 引用一致。
- **扫描基线**：七个模块加上清单里的 app 函数，改动前共 79 处命中，另有 `Busy` 1 处当时扫不到（`novels.py:419`）。Task 7 Step 2 复核为零。
