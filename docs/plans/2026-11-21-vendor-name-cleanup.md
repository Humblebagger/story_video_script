# 普通用户界面与接口去掉服务商 / 模型名字 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 普通用户能拿到的一切（首屏打包产物含两份语言包、所有非 `/admin` 接口的响应）里不再出现任何厂商或模型标识；出片档位改用中性名字（引擎 A / B × 标准 / 快速 / 经济），映射表在后端；错误码改成中性命名空间并兼容已有会话里的旧代码；会话视图在出口过滤（不迁移 `session.json`）；管理员在后台仍能看到厂商、模型与厂商原话，并且在产品界面里中性名后面附带厂商名（数据只来自管理员专用接口）；三处自动守卫防回归。

**Architecture:**
- 一份词表 `backend/server/vendor_words.json`，后端出口打码、后端守卫、前端守卫共用。
- 新模块 `backend/server/public.py` 是「给普通用户的出口」：`public_msg`（旧代码归一、只留登记过的参数、原文打码、中文兜底重写）、`error_pair` / `scrub_errors`（没有代码的旧文字换通用文案）、`film_view`（会话视图去厂商与模型、尝试按白名单下发、厂商任务号换短键）。`render.session.view` 与存储都不动。
- 新模块 `backend/render/tiers.py` 是中性档位 ↔（厂商、厂商内档位）的映射表；接口层只收 `tier`，换算成 `provider` / `model` 再交给现有的 `session.build`。
- 错误码在源头就中性：厂商模块改抛 `film.vendor.*` / `film.input.*` / `tts.vendor.*`；厂商原话不再进消息，经 `base.vendor_reject` 写日志并记错误记录（管理员在后台按参考编号查）。旧代码从登记表删除，`messages.LEGACY` 是旧 → 新对照表。
- 前端：语言包的 `srv` 节点跟着登记表改；出片面板设置区只剩一个档位下拉；类型与测试夹具换成新视图形状。
- 管理员提示：`/admin/service` 带出片线路表；前端在角色确认为管理员后（沿用现有的那一次请求）把它放进 `adminHints` context，档位下拉、失败原因等处在中性文字后面加括号显示。厂商文字只来自接口数据，首屏代码与语言包里没有。
- 守卫：`frontend/tests/vendor-words.test.ts`（语言包，进 `npm test`）、`frontend/tests/vendor-bundle.check.mjs`（首屏打包产物，构建后跑）、`backend/tests/server/test_vendor_guard.py`（投毒会话 + 非管理路由清单）。

**Tech Stack:** 后端 Python 3.12、FastAPI、pydantic v2、脚本式测试（`.venv/bin/python tests/<目录>/test_x.py`，没有 pytest）；前端 React 19、TypeScript、Vite 8，测试是 `vite build --ssr` 构建后交给 node 跑的脚本，断言用文件内的 `must`（仓库**没有** vitest 和 testing-library）。

**Spec:** `docs/specs/2026-11-21-vendor-name-cleanup-design.md`。下文用「§n」引用它的章节，用「Rn」引用它 §3 的裁定。

---

## 全局约束（每个 Task 都必须遵守）

- **只改本计划列出的文件**，不顺手重构。
- **不碰的文件与服务**：
  - 不读、不打印 `backend/.env`；
  - 不运行 `render/smoke.py`、`render/smoke_tts.py`、`assistant/smoke.py`，不调用付费服务或真实大模型；测试里的厂商一律用桩（`FakeVideo`、`FakeTts` 或假 HTTP 层），**不得发真实网络请求**；
  - 不启动、不停止前后端服务，不向 5173 / 8000 端口发请求（用户正在使用）；
  - 不读取、不打印任何真实 `session.json` 里的 `video_url`（带签名）。测试里投毒用的地址是自己编的；
  - 不动、不提交、不 `git add` `docs/specs/2026-10-27-commercialization-design-contract.md`（未跟踪文件，保持原样）。
- **后端测试不得读到真实 `.env`**：本计划之后，凡是调到出片会话接口的测试都会走 `tiers.options()`，它会去建各家厂商对象（`from_env` 里有 `_load_dotenv`）。所有 `tests/server/*.py` 必须像 `tests/server/test_film_tasks.py` 开头那样，在导入 `server.*` 之前把 `pipeline.config._load_dotenv` 换成空操作。Task 5 第一步会逐个核对并补齐。
- **提交规则**：
  - 提交由协调者做；执行 Task 的人**不提交、不 `git add`**，每个 Task 结束时报告改了哪些文件；
  - 协调者提交时只 `git add <具体文件>`，禁止 `git add -A`、`git commit -a`、`git stash`；提交信息用中文、描述性写法，**不得带 `Co-Authored-By`、`Claude-Session` 等任何署名尾行**；不 push。
- **硬性规则**：新写的任何界面文字、登记的消息、接口字段、测试之外的字符串字面量里都不出现词表（§4）里的词。内部模块名、类名、日志、注释、测试不受限。后台（`frontend/src/components/admin/*`、`/admin/*` 接口）允许出现。
- **不对用户内容打码**（R12）：`public.redact` 只用于错误文字。不要把它用到分镜、提示词、小说正文、助手对话上（「方舟」「火山」「海螺」「豆包」是常用词）。
- **lint 基线**：`frontend/` 下 `npm run lint` 是 0 error、警告恰好 5 条（`VerificationPanel.tsx`、`CardPicker.tsx`、`timeline.ts`、`ParamsForm.tsx`、`App.tsx` 各一条），**不得增加**。
- **film.test 已知偶发卡死**：`tests/film.test.tsx` 有小概率 CPU 自旋不退出（既有问题）。某条命令里它超过 2 分钟不结束就终止那个 node 进程，单独重跑判定：`cd frontend && npx vite build --ssr tests/film.test.tsx --outDir .ssrout --logLevel error && timeout 100 node .ssrout/film.test.js`。重跑通过即算通过。
- **本计划代码块的性质**：新文件（`vendor_words.json`、`public.py`、`tiers.py`、三个守卫）给的是完整内容；对现有文件的修改给的是要点（改哪个函数、改成什么），不是逐字补丁。`public.py` 的核心函数已在仓库外的临时目录里对着现有登记表试跑过（打码、短键、旧代码归一、丢多余参数、缺参数换通用、会话视图过滤）；其余代码没有执行过。每个 Task 都按「先写失败的测试 → 看到红 → 实现 → 看到绿」走；实际代码与要点有出入时以测试与 spec 为准，偏离 spec 的地方要报告，不要自行改设计。

## 先读这一节：仓库里与本任务有关的事实

- **消息登记**：`backend/server/messages.py` 里 `register(code, 中文)`；`msg(code, **params)` 的参数必须与模板占位符一致；`UserError.of(code, **params)` 抛错。改完跑 `cd backend && .venv/bin/python -m server.messages --write` 重新生成 `backend/server/messages_codes.json`。前端 `src/i18n/zh.ts`、`en.ts` 的 `srv` 节点要逐条对应（中文一字不差、键不多不少），`frontend/tests/srv-codes.test.ts` 在查。登记时一个代码不能是另一个代码的前缀（按 `.` 分段）。
- **消息参数里的「原文」**：`vendor(text)` 产出 `{"t":"vendor","text":…}`，前端原样显示。名字叫 vendor，实际也用于校验报告、结构错误等系统原文；真正的厂商原话只出自 `render/providers/minimax.py`、`seedance.py`、`tts_volc.py`，以及 `cause_of(e)` 对没有代码的异常的回落。
- **中文扫描**：`backend/tests/server/test_i18n_scan.py` 扫已改造模块的错误出口里有没有未登记的中文；`server/app.py` 只扫名单里的函数，**新增函数名要加进名单**；新模块加进 `MODULES`；纯内部日志在行尾加 `# i18n: internal`。
- **出片三层**：`render/providers/`（厂商）→ `render/session.py`（会话，一个版本一份 `session.json`）→ `render/runner.py`（出片线程）。`server/app.py` 是接口，返回会话视图的地方现在都是 `_render_call(render_session.view, s)`，共 13 处。
- **会话里存什么**：顶层 `provider`、`model`、`resolution` 等设置；段 / 自由节点各有 `attempts[]`，尝试里有 `task_id`、`video_url`、`last_frame_url`、`usage`、取消时的 `billing` 快照等；错误是一对 `error`（中文兜底）+ `error_msg`（`{code, params[, ref]}`）。
- **错误记录**：`server/error_refs.py` 的 `record(code, detail, …)` 返回参考编号，写 `<数据目录>/error_refs.jsonl`；`with_ref(m, ref)` 把编号挂到消息上；后台「错误」页按编号查。
- **前端的失败原因**：`i18n/serverMsg.ts` 的 `itemError` 按 `error_msg.code` 取 `srv.<code>` 模板渲染；**模板缺失时回落到 `message`**——所以带厂商名的旧代码只要漏过出口，就会连中文兜底一起显示出来。出口归一是唯一防线。
- **后台在按需加载的块里**：`frontend/src/components/admin/*` 有自己的语言包（`messages.zh.ts` 的 `zhAdmin`、`messages.en.ts` 的 `enAdmin`）；`tests/admin-bundle.check.mjs` 查后台标识不在首屏文件里。`src/api.ts` 的 `adminService` 留在主包（账号菜单要用），只有管理员登录时才请求。
- **前端测试的跑法**：单个 `cd frontend && npx vite build --ssr tests/<名>.test.tsx --outDir .ssrout --logLevel error && node .ssrout/<名>.test.js`；全部 `npm test`（`package.json` 的 `test` 是一长串 `&&`，新测试接在末尾）。
- **后端测试的跑法**：`cd backend && .venv/bin/python tests/<目录>/test_<名>.py`，成功时最后一行是 `ALL PASS`。全套：`cd backend; for t in tests/pipeline/test_*.py tests/server/test_*.py tests/render/test_*.py tests/assistant/test_*.py; do .venv/bin/python $t || echo FAIL $t; done`。

## 文件总览

| 文件 | 动作 | 职责 |
|---|---|---|
| `backend/server/vendor_words.json` | 新建 | 词表（唯一出处） |
| `backend/server/public.py` | 新建 | 出口：词表正则、打码、短键、消息净化、会话视图过滤 |
| `backend/server/messages.py`、`messages_codes.json` | 改 | 新代码登记、旧代码删除、`LEGACY`、`canonical`、`public_cause` |
| `backend/render/providers/base.py` | 改 | `vendor_reject`、`record_reject` 钩子；协议去掉 `rate_note`、`console_name` |
| `backend/render/providers/minimax.py`、`seedance.py`、`tts_volc.py`、`tts_base.py`、`fake.py`、`__init__.py` | 改 | 改抛新代码；原话走 `vendor_reject` |
| `backend/render/runner.py`、`mix.py`、`voice.py` | 改 | `public_cause`；去掉控制台引用 |
| `backend/render/tiers.py` | 新建 | 档位映射表 |
| `backend/render/session.py` | 改 | 视图的 `rate_note`；`clip_dest` 用短键 |
| `backend/render/plan.py`、`backend/adapters/seedance.py` | 改 | 渲染任务包的中性档位与文字 |
| `backend/server/app.py` | 改 | `_film_view`、设置收 `tier`、任务列表、音色、合成预览、`/admin/service`、装钩子 |
| `backend/assistant/tools.py`、`actions.py` | 改 | `film_status` 的错误文字；工具说明里的「厂商」 |
| `backend/tests/server/test_public.py`、`test_vendor_guard.py`、`backend/tests/render/test_tiers.py` | 新建 | 出口、守卫、档位的测试 |
| `backend/tests/**`（现有若干） | 改 | 跟着新代码、新视图改断言（各 Task 列出） |
| `frontend/src/i18n/zh.ts`、`en.ts` | 改 | `srv` 节点同步；界面文案去厂商 |
| `frontend/src/types.ts`、`components/FilmPanel.tsx`、`ComposePanel.tsx`、`RenderView.tsx` | 改 | 类型、档位下拉、音色标题、任务包缺省档位 |
| `frontend/src/components/admin/Overview.tsx`、`messages.zh.ts`、`messages.en.ts` | 改 | 后台「出片线路」卡片 |
| `frontend/src/adminHints.tsx` | 新建 | 管理员提示的 context 与两个钩子（不含任何厂商字面量） |
| `frontend/src/App.tsx`、`components/NodeCards.tsx`、`NodeGraph.tsx`、`components/shell/ActivityPanel.tsx` | 改 | 提供提示数据；失败原因后面给管理员加括号 |
| `frontend/tests/vendor-words.test.ts`、`vendor-bundle.check.mjs` | 新建 | 语言包守卫、首屏产物守卫 |
| `frontend/tests/*.test.ts(x)`（现有若干）、`frontend/package.json` | 改 | 夹具与断言；`test` 脚本末尾接新测试 |

Task 1–3 做词表、出口函数与错误码；Task 4–5 做档位与接口出口；Task 6 做前端面板；Task 7 做渲染任务包；Task 8 做后台；Task 9 做产品界面里给管理员的厂商提示；Task 10 做守卫；Task 11 全量验收。**Task 5 做完到 Task 6 做完之间，真实运行的前端与后端对不上（前端还在读 `provider` / `options.models`）**，这两个 Task 要连着做完再给人用；测试各自用桩，不受影响。

---

### Task 1: 词表与出口函数

**Files:**
- Create: `backend/server/vendor_words.json`
- Create: `backend/server/public.py`
- Modify: `backend/server/messages.py`（`LEGACY`、`canonical`、`registered`、`params_of`，登记 `common.failed_generic`）
- Modify: `backend/server/messages_codes.json`（重新生成）
- Modify: `frontend/src/i18n/zh.ts`、`frontend/src/i18n/en.ts`（`srv.common.failed_generic` 各一条）
- Modify: `backend/tests/server/test_i18n_scan.py`（`MODULES` 加 `"server/public.py": None`）
- Test: `backend/tests/server/test_public.py`（新）

- [ ] **Step 1: 写失败的测试** `backend/tests/server/test_public.py`

脚本式，开头与 `tests/server/test_messages.py` 一样把 `backend/` 加进 `sys.path`。断言要点（每组打一行 `✓`，最后 `ALL PASS`）：

```python
from server import messages as M, public as P

# 1. 词表：大小写、短词边界、中文
assert P.redact("MiniMax says ARK; dark park; volces.com; 火山方舟") == "*** says ***; dark park; ***.com; ******"
assert P.find_vendor_words({"a": "film.ark.x", "b": ["Doubao"]}) == ["ark", "doubao"]
assert P.find_vendor_words({"a": "引擎 A · 标准", "b": "dark"}) == []

# 2. 短键：稳定、定长、空值
assert P.task_key(None) is None and P.task_key("") is None
assert P.task_key("cgt-1") == P.task_key("cgt-1") != P.task_key("cgt-2")
assert len(P.task_key("x")) == 17 and P.task_key("x").startswith("t") and "cgt" not in P.task_key("cgt-1")

# 3. public_msg：认不出的代码、缺参数 → 通用；编号保留；多余参数丢掉；原文打码；嵌套递归
g = P.public_msg({"code": "nope.x", "params": {}, "ref": "AB12CD"})
assert g["code"] == "common.failed_generic" and g["ref"] == "AB12CD" and "AB12CD" in g["message"]
assert P.public_msg({"code": "film.submit.unavailable", "params": {"retries": 3}})["code"] == "common.failed_generic"
m = P.public_msg({"code": "film.submit.unavailable", "message": "MiniMax 挂了",
                  "params": {"retries": 3, "extra": "Seedance", "cause": {"t": "vendor", "text": "POST https://api.minimax.cn 502"}}})
assert m["code"] == "film.submit.unavailable" and set(m["params"]) == {"retries", "cause"}
assert m["params"]["cause"] == {"t": "vendor", "text": "POST https://api.***.cn 502"} and not P.find_vendor_words(m)
assert P.public_msg(None)["code"] == "common.failed_generic"

# 4. error_pair：都没有 → (None, None)；只有文字 → 通用文案（不外放原文）
assert P.error_pair({"error": None, "error_msg": None}) == (None, None)
text, em = P.error_pair({"error": "KeyError: 'video_url' sk-live-1 https://cdn/x?X-Tos-Signature=zz", "error_msg": None})
assert em == {"code": "common.failed_generic", "params": {}} and "sk-live" not in text

# 5. scrub_errors：error 对、step 对（步骤没有代码时置空）、detail 打码、其它键不动
out = P.scrub_errors({"state": "failed", "step": "配音", "step_msg": None, "error": "x", "error_msg": None,
                      "detail": "ffmpeg … doubao", "files": ["a.mp4"]})
assert out["step"] is None and out["step_msg"] is None and out["error_msg"]["code"] == "common.failed_generic"
assert out["detail"] == "ffmpeg … ***" and out["files"] == ["a.mp4"]

# 6. film_view：去厂商与模型、尝试白名单、短键、选项
view = {"provider": "minimax", "model": "minimax-h3", "resolution": "768P",
        "clips": [{"id": "E01-C01", "state": "failed", "error": "x", "error_msg": None, "attempts": [
            {"task_id": "cgt-1", "state": "abandoned", "cost_cny": 0, "file": None, "last_frame": None, "error": None,
             "error_msg": None, "at": "t", "fingerprint": "f", "first_frame_used": None,
             "video_url": "https://x.volces.com/v.mp4?sig=1", "last_frame_url": "u", "usage": {"n": 1},
             "billing": {"provider": "minimax", "model": "minimax-h3"}, "known_cost_cny": 2, "future_field": "MiniMax"}]}],
        "free": [], "orphaned": [{"id": "o", "shots": [], "attempts": [], "chosen": None}], "final": None,
        "options": {"providers": ["minimax"], "models": {"minimax-h3": {"label": "MiniMax H3"}}, "resolutions": ["768P"],
                    "default_note": "minimax_key_missing", "rate_note": {"code": "x", "params": {}}}}
v = P.film_view(view, tier="a-standard", tiers=[{"id": "a-standard"}], rate_note={"code": "common.internal", "params": {}})
assert "provider" not in v and "model" not in v and v["tier"] == "a-standard"
a = v["clips"][0]["attempts"][0]
assert set(a) == set(P.ATTEMPT_KEYS) & set(a) | {"task_id", "error", "error_msg"} and a["task_id"] == P.task_key("cgt-1")
assert not {"video_url", "last_frame_url", "usage", "billing", "known_cost_cny", "future_field"} & set(a)
assert set(v["options"]) == {"resolutions", "rate_note", "tiers"} and not P.find_vendor_words(v)
assert view["provider"] == "minimax" and "video_url" in view["clips"][0]["attempts"][0], "不改入参"
```

- [ ] **Step 2: 运行，确认失败**

运行：`cd backend && .venv/bin/python tests/server/test_public.py`
预期：失败，`ImportError`（没有 `server.public`）。

- [ ] **Step 3: 词表** 新建 `backend/server/vendor_words.json`

```json
{
  "substr": ["minimax", "hailuo", "seedance", "doubao", "volcengine", "volces", "volc",
             "bytedance", "deepseek", "anthropic", "claude", "openai", "kling", "jimeng"],
  "word": ["ark", "gpt"],
  "cjk": ["海螺", "豆包", "方舟", "火山", "字节跳动", "即梦", "可灵", "深度求索"]
}
```

- [ ] **Step 4: `messages.py` 的四样小东西**

在 `dump_codes` 之前加：

```python
LEGACY: dict = {}     # 旧代码 → 新代码：已有会话与错误记录里的旧代码在出口处归一（Task 3 填表）


def canonical(code: str) -> str:
    return LEGACY.get(code, code)


def registered(code: str) -> bool:
    return code in _REG


def params_of(code: str) -> tuple:
    return _REG[code][0]
```

登记表的 `common.internal` 下面加一行：

```python
register("common.failed_generic", "没有成功，请重试；仍失败请联系管理员")
```

前端 `zh.ts` 的 `srv.common` 加 `failed_generic: '没有成功，请重试；仍失败请联系管理员'`，`en.ts` 加 `failed_generic: 'That didn\'t work. Please try again; if it keeps failing, contact the administrator.'`。

运行：`cd backend && .venv/bin/python -m server.messages --write`

- [ ] **Step 5: 新建 `backend/server/public.py`**（完整内容）

```python
"""给普通用户的出口：厂商词表、旧代码归一、消息对象与出片会话视图的净化（spec 2026-11-21-vendor-name-cleanup §4、§7）。
管理接口（/admin/*）不经过这里。打码只用于错误文字，不用于分镜、提示词、小说、对话等用户内容。"""
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Optional

from server import messages

WORDS_FILE = Path(__file__).with_name("vendor_words.json")
_W = json.loads(WORDS_FILE.read_text(encoding="utf-8"))
_ALTS = sorted([re.escape(w) for w in _W["substr"] + _W["cjk"]]
               + [rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])" for w in _W["word"]], key=len, reverse=True)
VENDOR_RE = re.compile("|".join(_ALTS), re.I)
MASK = "***"
GENERIC = "common.failed_generic"
_REF_RE = re.compile(r"[0-9A-Z]{1,16}")
# 尝试里可以给普通用户的字段（白名单：新增字段默认不下发）
ATTEMPT_KEYS = ("state", "cost_cny", "file", "last_frame", "at", "fingerprint", "first_frame_used",
                "style_ref", "free_id", "late", "cancelled_at", "settled_at", "images")


def redact(text) -> str:
    """错误文字里的厂商词换成 ***。"""
    return VENDOR_RE.sub(MASK, str(text))


def find_vendor_words(v) -> list:
    """任意 JSON 值里出现的厂商词（守卫测试用；只能用在不含用户内容的值上）。"""
    return sorted({m.group(0).lower() for m in VENDOR_RE.finditer(json.dumps(v, ensure_ascii=False))})


def task_key(task_id) -> Optional[str]:
    """厂商任务号 → 不可逆的短键。同一个任务号在会话视图与任务列表里得到同一个键。"""
    return "t" + hashlib.sha256(str(task_id).encode("utf-8")).hexdigest()[:16] if task_id else None


def _value(v: Any) -> Any:
    if isinstance(v, str):
        return redact(v)
    if isinstance(v, list):
        return [_value(x) for x in v]
    if isinstance(v, dict):
        t = v.get("t")
        if t == "money":
            return v
        if t == "ref":
            code = messages.canonical(str(v.get("code")))
            return {"t": "ref", "code": code} if messages.registered(code) else ""
        if t == "vendor":
            return {"t": "vendor", "text": redact(v.get("text", ""))}
        if t == "lines":
            return {"t": "lines", "items": [_value(x) for x in v.get("items") or []]}
        if isinstance(v.get("code"), str):
            m = public_msg(v)
            return {"code": m["code"], "params": m["params"]}
        return ""
    return v


def public_msg(m) -> dict:
    """消息对象 → 可以给普通用户的消息对象：旧代码归一、只留登记过的参数、文字里的厂商词打码、中文兜底重写。
    认不出的代码、缺参数的，一律换成通用失败文案（保留参考编号）。"""
    out = None
    if isinstance(m, dict) and isinstance(m.get("code"), str):
        code = messages.canonical(m["code"])
        src = m.get("params") if isinstance(m.get("params"), dict) else {}
        if messages.registered(code) and all(k in src for k in messages.params_of(code)):
            params = {k: _value(src[k]) for k in messages.params_of(code)}
            out = {"code": code, "params": params, "message": messages.render_zh(code, params)}
    if out is None:
        out = messages.msg(GENERIC)
    ref = m.get("ref") if isinstance(m, dict) else None
    if isinstance(ref, str) and _REF_RE.fullmatch(ref):
        out = messages.with_ref(out, ref)
    return out


def error_pair(obj: dict, text_key: str = "error", msg_key: str = "error_msg") -> tuple:
    """(中文兜底, {code, params[, ref]})；两样都没有时 (None, None)。只有文字、没有代码的不外放，换通用文案。"""
    m, text = obj.get(msg_key), obj.get(text_key)
    if not m and not text:
        return None, None
    pm = public_msg(m)
    return pm["message"], {k: pm[k] for k in ("code", "params", "ref") if k in pm}


def scrub_errors(v: Any) -> Any:
    """递归：带 error / error_msg 的字典把这一对换成净化后的；step / step_msg 同理（步骤没有代码时置空）；
    字符串型的 detail 打码。其它键原样。"""
    if isinstance(v, list):
        return [scrub_errors(x) for x in v]
    if not isinstance(v, dict):
        return v
    out = {k: scrub_errors(x) for k, x in v.items()}
    if "error" in v or "error_msg" in v:
        out["error"], out["error_msg"] = error_pair(v)
    if "step" in v or "step_msg" in v:
        out["step"], out["step_msg"] = error_pair(v, "step", "step_msg") if v.get("step_msg") else (None, None)
    if isinstance(v.get("detail"), str):
        out["detail"] = redact(v["detail"])
    return out


def _attempt(a: dict) -> dict:
    out = {k: a[k] for k in ATTEMPT_KEYS if k in a}
    out["task_id"] = task_key(a.get("task_id"))
    out["error"], out["error_msg"] = error_pair(a)
    return out


def _holder(c: dict) -> dict:
    out = scrub_errors({k: x for k, x in c.items() if k != "attempts"})
    out["attempts"] = [_attempt(a) for a in c.get("attempts") or []]
    return out


def film_view(view: dict, *, tier: Optional[str], tiers: list, rate_note: dict) -> dict:
    """出片会话视图（render.session.view 的结果）→ 给普通用户的：去掉厂商与模型，尝试按白名单留字段，
    任务号换短键，错误净化；档位用中性 id。不改入参，存储不动。"""
    out = {k: x for k, x in view.items() if k not in ("provider", "model")}
    out["tier"] = tier
    for key in ("clips", "free", "orphaned"):
        if key in view:
            out[key] = [_holder(c) for c in view.get(key) or []]
    if view.get("final"):
        out["final"] = scrub_errors(view["final"])
    opts = {k: x for k, x in (view.get("options") or {}).items()
            if k not in ("providers", "models", "default_note")}
    opts["rate_note"] = rate_note
    opts["tiers"] = tiers
    out["options"] = opts
    return out
```

`tests/server/test_i18n_scan.py` 的 `MODULES` 加 `"server/public.py": None`。

- [ ] **Step 6: 运行，确认通过**

运行：`cd backend && for t in tests/server/test_public.py tests/server/test_messages.py tests/server/test_i18n_scan.py; do .venv/bin/python $t || echo FAIL $t; done`
预期：三个都 `ALL PASS`，没有 `FAIL`。

运行：`cd frontend && npx vite build --ssr tests/srv-codes.test.ts --outDir .ssrout --logLevel error && node .ssrout/srv-codes.test.js`
预期：`ALL PASS`。

---

### Task 2: 登记中性错误码，厂商模块改用新代码，厂商原话进错误记录

这一步**只加不删**：旧代码仍在登记表里（Task 3 删），所以前后端的现有测试除了本 Task 点名的以外都不受影响。

**Files:**
- Modify: `backend/server/messages.py`、`backend/server/messages_codes.json`
- Modify: `backend/render/providers/base.py`、`minimax.py`、`seedance.py`、`tts_volc.py`、`fake.py`、`__init__.py`
- Modify: `backend/render/session.py`（`poll_update` 保留编号）
- Modify: `backend/server/app.py`（装 `record_reject` 钩子）
- Modify: `frontend/src/i18n/zh.ts`、`en.ts`（`srv` 节点新增）
- Test: `backend/tests/render/test_providers.py`、`test_minimax.py`、`test_seedance.py`、`test_tts_volc.py`、`backend/tests/server/test_messages.py`

- [ ] **Step 1: 写失败的测试**

`tests/render/test_providers.py` 末尾（`ALL PASS` 之前）加一组 `vendor_reject`：

```python
    # vendor_reject：消息不带原话；没装钩子没有编号；装了钩子带编号，钩子收到脱敏后的原话与厂商名
    base.record_reject = None
    with _LogGrab("render.providers.base") as g:
        m = base.vendor_reject("film.vendor.rejected", "bad prompt k-secret", who="minimax", secrets=("k-secret",))
    assert m["code"] == "film.vendor.rejected" and m["params"] == {} and "ref" not in m and "bad prompt" not in m["message"]
    assert any("bad prompt" in x and "minimax" in x for x in g.lines) and all("k-secret" not in x for x in g.lines)
    seen = []
    base.record_reject = lambda code, detail: (seen.append((code, detail)), "AB12CD34")[1]
    m = base.vendor_reject("film.vendor.rejected", "bad prompt k-secret", who="minimax", secrets=("k-secret",))
    assert m["ref"] == "AB12CD34" and "AB12CD34" in m["message"]
    assert seen == [("film.vendor.rejected", "minimax: bad prompt ***")]
    base.record_reject = lambda *_a: (_ for _ in ()).throw(OSError("disk"))     # 钩子出错不能挡住报错
    assert "ref" not in base.vendor_reject("film.vendor.rejected", "x", who="minimax")
    base.record_reject = None
    print("vendor_reject ✓")
```

`test_minimax.py`、`test_seedance.py`、`test_tts_volc.py`：把断言里的旧代码按下表换成新代码；原来断言「错误文字里有厂商原话」的地方改成断言「代码是 `film.vendor.rejected`（配音是 `tts.vendor.rejected` / `tts.vendor.failed`）、参数里没有 `detail`、中文兜底里没有原话、原话在日志里（用文件里已有的 `_LogGrab`）」。`test_messages.py` 第 105–112 行那一组把代码名换成新代码。

| 旧（厂商模块里现在抛的） | 新 |
|---|---|
| `film.ark.X`、`film.minimax.X`（X 为 `no_key`、`connect_failed`、`throttled`、`http_ambiguous`、`unavailable`、`not_json`、`no_task_id`、`no_result_url`） | `film.vendor.X` |
| `film.ark.auth`、`film.minimax.invalid_key` | `film.vendor.auth` |
| `film.ark.overdue`、`film.minimax.insufficient_balance` | `film.vendor.balance` |
| `film.ark.access_denied` / `limit_paused` / `quota` / `task_expired` / `copyright` / `output_moderated` / `output_copyright` | `film.vendor.` 同名 |
| `film.ark.model_unavailable` | `film.vendor.tier_unavailable` |
| `film.ark.input_moderated`、`film.minimax.moderated` | `film.vendor.input_moderated` |
| `film.ark.unknown_model`、`film.minimax.unknown_model`、`film.fake.unknown_model`、`film.provider.unknown` | `film.settings.no_model` |
| `film.ark.download_failed` | `film.provider.download_failed` |
| `film.minimax.url_expired` | `film.vendor.result_expired` |
| `film.minimax.bad_resolution` | `film.settings.bad_resolution` |
| `film.minimax.lite_needs_ratio` | `film.input.needs_ratio` |
| `film.minimax.` 的 `label_first`、`label_ref`、`bad_image`、`unsupported_format`、`corrupt_image`、`image_too_big`、`prompt_too_long`、`bad_ratio`、`request_too_big` | `film.input.` 同名 |
| `film.provider.rejected`、`film.provider.http_rejected` | `film.vendor.rejected`（真厂商）；`film.fake.failed {detail}`（假厂商） |
| `tts.volc.X`（`no_key`、`unavailable`、`rejected_http`、`not_json`、`failed`、`bad_audio`、`cut`、`connect_failed`、`incomplete`） | `tts.vendor.X` |
| `tts.volc.not_object` | `tts.vendor.not_json` |
| `tts.volc.rejected {code, detail}` | `tts.vendor.rejected`（无参数，带编号） |
| `tts.volc.failed_detail {code, detail}` | `tts.vendor.failed {code}`（原话走日志与错误记录） |
| `tts.unknown_provider {name}` | `tts.vendor.misconfigured` |

- [ ] **Step 2: 运行，确认失败**

运行：`cd backend && for t in tests/render/test_providers.py tests/render/test_minimax.py tests/render/test_seedance.py tests/render/test_tts_volc.py tests/server/test_messages.py; do .venv/bin/python $t || echo FAIL $t; done`
预期：五个都 `FAIL`（`AttributeError: vendor_reject`、`KeyError: 'film.vendor.…'` 之类）。

- [ ] **Step 3: 登记新代码**（`messages.py`，放在现有 `film.ark.*` 一组的上面；文案逐字照 spec §6.1）

```python
# ---- 生成服务侧的失败：中性命名，不带厂商名（spec vendor-name-cleanup §6.1） ----
register("film.vendor.no_key", "视频生成服务还没有配置，请联系管理员")
register("film.vendor.auth", "视频生成服务鉴权失败，请联系管理员")
register("film.vendor.balance", "视频生成服务账户余额不足，暂时无法出片，请联系管理员")
register("film.vendor.access_denied", "视频生成服务拒绝访问，请联系管理员")
register("film.vendor.limit_paused", "视频生成服务已达到用量上限并暂停，请联系管理员")
register("film.vendor.quota", "额度不足或排队已满，持续失败请联系管理员")
register("film.vendor.tier_unavailable", "所选的视频档位暂时不可用，请换一个档位或联系管理员")
register("film.vendor.connect_failed", "连接视频生成服务失败")
register("film.vendor.throttled", "视频生成服务繁忙")
register("film.vendor.http_ambiguous", "视频生成服务返回 HTTP {status}")
register("film.vendor.unavailable", "视频生成服务暂时不可用（HTTP {status}）")
register("film.vendor.not_json", "视频生成服务返回了无法识别的响应")
register("film.vendor.no_task_id", "视频生成服务受理了请求却没有返回任务编号")
register("film.vendor.no_result_url", "视频生成服务没有返回结果地址")
register("film.vendor.task_expired", "任务超时")
register("film.vendor.result_expired", "结果地址已过期且重新查询失败")
register("film.vendor.input_moderated", "这一段的画面描述或参考图没通过内容审核：改写描述或换参考图后重试")
register("film.vendor.copyright", "这一段的描述可能涉及版权限制：改写后重试")
register("film.vendor.output_moderated", "生成的视频没通过内容审核：调整这一段的描述后重试")
register("film.vendor.output_copyright", "生成的视频可能涉及版权限制：调整这一段的描述后重试")
register("film.vendor.rejected", "视频生成服务拒绝了这次请求，请重试；仍失败请联系管理员")
register("film.vendor.unknown_cause", "未知原因")
register("film.fake.failed", "{detail}")
# ---- 提交前的输入检查 ----
register("film.input.label_first", "首帧")
register("film.input.label_ref", "参考图 {id}")
register("film.input.bad_image", "{label} 不是可用的图片地址")
register("film.input.unsupported_format", "{label} 的格式 {mime} 不支持（只收 JPG、PNG、WEBP、HEIC、HEIF）")
register("film.input.corrupt_image", "{label} 的图片数据损坏")
register("film.input.image_too_big", "{label} 有 {mb}MB，超过单张图片的大小上限")
register("film.input.prompt_too_long", "提示词超出上限 {max} 字（当前 {len} 字）")
register("film.input.needs_ratio", "这个档位的参考生视频必须明确画幅，不支持自适应")
register("film.input.bad_ratio", "这个档位不支持画幅 {ratio}，可选：{options}")
register("film.input.request_too_big", "请求体约 {mb}MB，超过上限：减少参考图或换小一些的图")
```

配音一组（放在现有 `tts.volc.*` 上面）：

```python
register("tts.vendor.no_key", "配音服务还没有配置，请联系管理员")
register("tts.vendor.misconfigured", "配音服务配置有误，请联系管理员")
register("tts.vendor.unavailable", "配音服务暂时不可用（HTTP {status}）")
register("tts.vendor.rejected", "配音服务拒绝了这次请求，请重试；仍失败请联系管理员")
register("tts.vendor.rejected_http", "配音服务拒绝了请求（HTTP {status}）")
register("tts.vendor.not_json", "配音服务返回了无法识别的响应")
register("tts.vendor.failed", "配音合成失败（{code}）")
register("tts.vendor.bad_audio", "配音服务返回的音频无法解码")
register("tts.vendor.cut", "配音服务中途断开")
register("tts.vendor.connect_failed", "连接配音服务失败")
register("tts.vendor.incomplete", "配音服务没有返回完整的音频")
```

运行：`cd backend && .venv/bin/python -m server.messages --write`

前端 `zh.ts` 的 `srv.film` 下新增 `vendor: {…}`、`input: {…}` 两个节点与 `fake.failed`，`srv.tts` 下新增 `vendor: {…}`，中文与上面一字不差；`en.ts` 对应加英文（统一说 "the video generation service"、"the voice service"，例如 `balance: 'The video generation service account balance is too low, so clips can\'t be generated right now. Please contact the administrator.'`、`rejected: 'The video generation service rejected this request. Please try again; if it keeps failing, contact the administrator.'`、`unknown_cause: 'unknown cause'`、`needs_ratio: 'Reference-to-video on this tier needs an explicit aspect ratio; adaptive is not supported'`）。英文里的占位符必须与登记的参数一一对应（`srv-codes.test.ts` 会查）。

- [ ] **Step 4: `base.py` 的 `vendor_reject`**

文件头的导入补 `msg, with_ref`（`from server.messages import UserError, msg, with_ref`）。在 `try_cancel` 附近加：

```python
record_reject = None    # 由 server.app 装上：(code, detail) -> 参考编号。缺省不记（厂商模块的单元测试不碰数据目录）


def vendor_reject(code: str, raw, *, who: str, secrets=()) -> dict:
    """厂商说不清或我们不认识的拒绝：原话不给用户。脱敏后写日志；装了 record_reject 就记一条错误记录，
    消息带参考编号，管理员按编号在后台查到原话与厂商名。返回消息对象（code 的模板不得有参数）。"""
    detail = scrub_secrets(f"{who}: {raw}", secrets)[:2000]
    log.warning("%s", f"厂商拒绝 code={code} {detail}")  # i18n: internal
    m = msg(code)
    if record_reject is not None:
        try:
            m = with_ref(m, record_reject(code, detail))
        except Exception as e:  # noqa: BLE001  记不上不能挡住报错本身
            log.error("%s", scrub_secrets(f"厂商拒绝记录失败 {type(e).__name__}: {e}", secrets))  # i18n: internal
    return m
```

`TaskState` 不加字段：`error_msg` 本来就是字典，带上 `ref` 即可。

- [ ] **Step 5: 厂商模块改用新代码**

按 Step 1 的表逐个替换 `minimax.py`、`seedance.py`、`tts_volc.py`、`__init__.py` 里的代码名。四处不是单纯改名：

1. `minimax.py` 的 `_reject`（约第 127 行）与 `poll` 里的失败分支（约第 372 行）、`seedance.py` 的 `_reject`（约第 127 行）与 `poll` 的失败分支（约第 265 行）：原来 `ProviderError.of("film.provider.rejected", detail=vendor(text))` / `http_rejected` 的地方改成

   ```python
   return ProviderError.from_msg(base.vendor_reject("film.vendor.rejected", text or f"HTTP {status}", who="minimax", secrets=(secret,)))
   ```

   `poll` 里是 `m = base.vendor_reject(…)`，然后 `error, error_msg = m["message"], {k: m[k] for k in ("code", "params", "ref") if k in m}`。「中文兜底保持原样」的那几行（`e.args = …`、`_with_fallback(…, zh)`、`zh if zh and not our else …`）删掉：兜底不能再带原话。`who` 分别写 `"minimax"`、`"seedance"`。
2. `minimax.py` 抛 `throttled` 的地方不再传 `status`（新代码没有参数）；`image_too_big`、`unsupported_format` 的参数不变。
3. `tts_volc.py` 的 `_reject`（约第 85 行）与 `failed_detail`（约第 160 行）：有原话时走 `base.vendor_reject("tts.vendor.rejected", f"{code}: {msg}", who="volc", secrets=…)`（`failed_detail` 的那处仍要保留计费语义：用 `self._billed` 的同一个异常类，代码换成 `tts.vendor.failed`、参数只有 `code`，原话另外 `log.warning` 一行并在 `record_reject` 存在时记一条——直接调 `base.vendor_reject("tts.vendor.rejected", …)` 只取它的副作用即可）。`from render.providers import base` 若该文件还没有就补上。
4. `__init__.py`：`UnknownProvider.of("film.provider.unknown", name=name)` → `UnknownProvider.of("film.settings.no_model")`，前面加一行 `log.warning`（带 `name`，`# i18n: internal`）；`UnknownTts.of("tts.unknown_provider", name=name)` → `UnknownTts.of("tts.vendor.misconfigured")`，同样先写日志。文件头补 `import logging` 与 `log = logging.getLogger("render.providers")`。

`fake.py`：`film.provider.rejected` → `film.fake.failed`（参数仍是 `detail=vendor(self.fail_with)`）；`film.fake.unknown_model` → `film.settings.no_model`。

`session.py` 的 `poll_update`：组装 `err` 时把编号带上——

```python
            err = ({"code": st.error_msg["code"], "params": st.error_msg.get("params") or {}, "message": st.error,
                    **({"ref": st.error_msg["ref"]} if st.error_msg.get("ref") else {})}
                   if st.error_msg else (st.error or msg("film.provider.failed")))
```

`app.py`：在 `_render_runner = …` 之前装钩子——

```python
render_video_base.record_reject = lambda code, detail: error_refs.record(code, detail, where="vendor")
```

- [ ] **Step 6: 运行，确认通过**

运行：`cd backend && for t in tests/render/test_*.py tests/server/test_*.py; do .venv/bin/python $t || echo FAIL $t; done`
预期：没有 `FAIL`。别的测试里若还有断言旧代码或厂商原话的（`test_runner.py`、`test_cancel_runner.py`、`test_compose.py`、`test_voice.py`、`test_film_tasks.py`、`test_render.py` 里用假厂商 `fail_with` 的地方），按 Step 1 的表改断言；改完再跑到没有 `FAIL`。

运行：`cd frontend && npx vite build --ssr tests/srv-codes.test.ts --outDir .ssrout --logLevel error && node .ssrout/srv-codes.test.js`
预期：`ALL PASS`。

---

### Task 3: 删除旧代码、对照表、控制台与费率说明、原因不再带原文

**Files:**
- Modify: `backend/server/messages.py`、`messages_codes.json`
- Modify: `backend/render/providers/base.py`、`tts_base.py`、`minimax.py`、`seedance.py`、`tts_volc.py`、`fake.py`（去掉 `rate_note`、`console_name`）
- Modify: `backend/render/session.py`（视图的 `rate_note`）、`backend/render/runner.py`、`mix.py`、`voice.py`
- Modify: `backend/server/app.py`（音色接口的 `rate_note`）
- Modify: `frontend/src/i18n/zh.ts`、`en.ts`（`srv` 节点删除与改字）
- Modify: `frontend/tests/server-msg.test.ts`、`film.test.tsx`、`compose.test.tsx`（引用了被删的 `srv` 键）
- Test: `backend/tests/server/test_messages.py`、`test_public.py`、`backend/tests/render/test_runner.py`、`test_cancel_runner.py`、`test_mix.py`、`test_voice.py`、`test_session.py`

- [ ] **Step 1: 写失败的测试**

`test_messages.py` 加一组：

```python
    # 对照表：旧代码不在登记表、新代码在、新参数 ⊆ 旧参数（旧数据总能渲染）；全表没有厂商词
    from server import public as P
    OLD_PARAMS = {  # 删除前各旧代码的参数（只列有参数的；其余为空）
        "film.ark.http_ambiguous": ["status"], "film.ark.unavailable": ["status"], "film.ark.download_failed": ["status"],
        "film.minimax.http_ambiguous": ["status"], "film.minimax.unavailable": ["status"], "film.minimax.throttled": ["status"],
        "film.minimax.label_ref": ["id"], "film.minimax.bad_image": ["label"], "film.minimax.corrupt_image": ["label"],
        "film.minimax.unsupported_format": ["label", "mime"], "film.minimax.image_too_big": ["label", "mb"],
        "film.minimax.prompt_too_long": ["max", "len"], "film.minimax.bad_ratio": ["ratio", "options"],
        "film.minimax.request_too_big": ["mb"], "film.minimax.bad_resolution": ["resolution", "options"],
        "film.provider.rejected": ["detail"], "film.provider.http_rejected": ["status", "detail"],
        "film.provider.unknown": ["name"], "tts.unknown_provider": ["name"],
        "tts.volc.unavailable": ["status"], "tts.volc.rejected": ["code", "detail"], "tts.volc.rejected_http": ["status"],
        "tts.volc.failed": ["code"], "tts.volc.failed_detail": ["code", "detail"],
    }
    assert len(M.LEGACY) >= 60
    for old, new in M.LEGACY.items():
        assert not M.registered(old), f"{old} 应已删除"
        assert M.registered(new), f"{new} 没登记"
        assert set(M.params_of(new)) <= set(OLD_PARAMS.get(old, [])), (old, new)
    assert not [c for c in codes if c.startswith(("film.ark.", "film.minimax.", "tts.volc.", "console."))]
    hits = {c: P.find_vendor_words([c, v["zh"]]) for c, v in codes.items()}
    assert not {c: h for c, h in hits.items() if h}, "登记表里不得有厂商词"
    # public_cause：有代码给紧凑消息；没有代码不带原文
    e = ProviderError.of("film.vendor.throttled")
    assert M.public_cause(e) == {"code": "film.vendor.throttled", "params": {}}
    assert M.public_cause(RuntimeError("POST https://api.minimax.cn 502")) == {"code": "film.vendor.unknown_cause", "params": {}}
```

`test_public.py` 加一组（旧数据经出口后的样子）：

```python
    m = P.public_msg({"code": "film.minimax.insufficient_balance", "params": {}, "message": "视频服务（MiniMax）账户余额不足…"})
    assert m["code"] == "film.vendor.balance" and m["message"] == M.render_zh("film.vendor.balance", {})
    m = P.public_msg({"code": "film.provider.rejected", "params": {"detail": {"t": "vendor", "text": "MiniMax: bad"}}})
    assert m == M.msg("film.vendor.rejected")
    m = P.public_msg({"code": "film.submit.ambiguous", "params": {
        "console": {"t": "ref", "code": "console.minimax"}, "cause": {"code": "film.ark.connect_failed", "params": {"kind": "ConnectError"}}}})
    assert m["params"] == {"cause": {"code": "film.vendor.connect_failed", "params": {}}} and not P.find_vendor_words(m)
    m = P.public_msg({"code": "tts.volc.failed_detail", "params": {"code": "45000", "detail": {"t": "vendor", "text": "豆包…"}}})
    assert m["code"] == "tts.vendor.failed" and m["params"] == {"code": "45000"}
```

`test_runner.py`：提交不明（`AmbiguousSubmit`）的断言改成参数只有 `cause`、中文兜底含「请联系管理员核对」且不含「控制台」；用一个抛无代码异常的桩（如 `RuntimeError("boom https://api.minimax.cn")`）断言落进会话的 `error_msg.params.cause == {"code": "film.vendor.unknown_cause", "params": {}}`、`error` 文字里没有 `boom`，而 `render.runner` 的日志里有 `boom`。`test_session.py`：`view()["options"]["rate_note"] == {"code": "rate.video", "params": {}}`。

- [ ] **Step 2: 运行，确认失败**

运行：`cd backend && for t in tests/server/test_messages.py tests/server/test_public.py tests/render/test_runner.py tests/render/test_session.py; do .venv/bin/python $t || echo FAIL $t; done`
预期：四个都 `FAIL`。

- [ ] **Step 3: `messages.py`**

1. 删除这些 `register` 行：全部 `film.ark.*`、`film.minimax.*`、`tts.volc.*`，`film.provider.rejected`、`film.provider.http_rejected`、`film.provider.unknown`、`film.fake.unknown_model`、`tts.unknown_provider`、`console.generic / ark / minimax`、`rate.ark / minimax / fake / volc_tts / fake_tts`。
2. 新登记：

   ```python
   register("rate.video", "按公开刊例价估算，未经账单核对")
   register("rate.tts", "配音按字符计费，按公开刊例价估算，未经账单核对")
   ```

3. 改字不改码（spec §6.2，中文逐字照表）：`film.submit.ambiguous`（模板去掉 `{console}`）、`film.submit.interrupted`、`film.poll.gave_up`、`film.session.none_pick`、`film.settings.no_native_audio`、`film.free.over_refs`、`film.free.no_first_frame`。
4. 填 `LEGACY`（spec §6.3 的表逐行展开；两家都有的写两行）：

   ```python
   def _legacy() -> dict:
       out = {}
       same = ("no_key", "connect_failed", "throttled", "http_ambiguous", "unavailable", "not_json", "no_task_id", "no_result_url")
       for ns in ("film.ark", "film.minimax"):
           out.update({f"{ns}.{x}": f"film.vendor.{x}" for x in same})
           out[f"{ns}.unknown_model"] = "film.settings.no_model"
       out.update({f"film.ark.{x}": f"film.vendor.{x}" for x in
                   ("access_denied", "limit_paused", "quota", "task_expired", "input_moderated", "copyright",
                    "output_moderated", "output_copyright")})
       out.update({"film.ark.auth": "film.vendor.auth", "film.minimax.invalid_key": "film.vendor.auth",
                   "film.ark.overdue": "film.vendor.balance", "film.minimax.insufficient_balance": "film.vendor.balance",
                   "film.ark.model_unavailable": "film.vendor.tier_unavailable",
                   "film.ark.download_failed": "film.provider.download_failed",
                   "film.minimax.moderated": "film.vendor.input_moderated",
                   "film.minimax.url_expired": "film.vendor.result_expired",
                   "film.minimax.bad_resolution": "film.settings.bad_resolution",
                   "film.minimax.lite_needs_ratio": "film.input.needs_ratio",
                   "film.fake.unknown_model": "film.settings.no_model", "film.provider.unknown": "film.settings.no_model",
                   "film.provider.rejected": "film.vendor.rejected", "film.provider.http_rejected": "film.vendor.rejected",
                   "tts.volc.not_object": "tts.vendor.not_json", "tts.volc.failed_detail": "tts.vendor.failed",
                   "tts.unknown_provider": "tts.vendor.misconfigured",
                   "rate.ark": "rate.video", "rate.minimax": "rate.video", "rate.fake": "rate.video",
                   "rate.volc_tts": "rate.tts", "rate.fake_tts": "rate.tts"})
       out.update({f"film.minimax.{x}": f"film.input.{x}" for x in
                   ("label_first", "label_ref", "bad_image", "unsupported_format", "corrupt_image", "image_too_big",
                    "prompt_too_long", "bad_ratio", "request_too_big")})
       out.update({f"tts.volc.{x}": f"tts.vendor.{x}" for x in
                   ("no_key", "unavailable", "rejected", "rejected_http", "not_json", "failed", "bad_audio", "cut",
                    "connect_failed", "incomplete")})
       return out


   LEGACY.update(_legacy())
   ```

   这一段放在全部 `register` 之后（文件末尾、`if __name__ == "__main__"` 之前）。注意 `film.minimax.throttled` 旧参数是 `status`、新代码无参数，符合「新 ⊆ 旧」。
5. `cause_of` 下面加：

   ```python
   def public_cause(e: BaseException) -> dict:
       """异常 → 可嵌进给用户的消息的原因：带代码的给紧凑消息；没有代码的只说「未知原因」（原文由调用方写日志，
       里面可能有厂商接口地址）。出片与合成用它；转换管线仍用 cause_of。"""
       m = e.as_msg() if isinstance(e, UserError) else None
       return compact(m) if m else compact(msg("film.vendor.unknown_cause"))
   ```

运行：`cd backend && .venv/bin/python -m server.messages --write`

- [ ] **Step 4: 去掉控制台与厂商费率说明**

- `base.py` 的 `VideoProvider` 协议删 `rate_note`、`console_name` 两行；`tts_base.py` 的协议删 `rate_note`；`minimax.py`、`seedance.py`、`tts_volc.py`、`fake.py`（两个类）删这两个类属性。
- `session.py` 的 `view`：两处 `rate_note` 都改成 `compact(msg("rate.video"))`（厂商不可用的分支原来是空串，也改成它）。
- `app.py` 的 `render_voices`：两处返回里的 `rate_note` 改成 `compact(msg("rate.tts"))`（`provider` 字段留到 Task 5 再去）。
- `runner.py`：删 `_console_ref`；导入里去掉 `ref`、`cause_of`，加 `public_cause`；所有 `cause_of(e)` 换成 `public_cause(e)`；所有 `_coded(f"…{e}", code, …)` 换成 `msg(code, …)`（不再手拼带原文的中文兜底，`_coded` 函数随之删除），并在每处前面补一行 `log.warning("%s", _scrub_secrets(f'… root={root} clip={c["id"]} {type(e).__name__}: {e}', provider))  # i18n: internal`（已有日志的不重复加）；`film.submit.ambiguous` 的调用去掉 `console=where`。`film.poll.gave_up` 那处 `TaskState(…, error=m["message"], error_msg=compact(m))` 不变。
- `mix.py` 第 367 行、`voice.py` 第 183、185 行：`cause_of(e)` → `public_cause(e)`；`voice.py` 那两行的 `"error": str(e)` 改成 `"error": render_zh(m["code"], m["params"])`（`m = public_cause(e)`，补导入 `render_zh`），并先 `log.warning` 原文。

- [ ] **Step 5: 前端语言包与引用它的测试**

- `zh.ts`、`en.ts` 的 `srv` 节点：删 `console`、`rate.ark / minimax / fake / volc_tts / fake_tts`、`film.ark`、`film.minimax`、`film.provider.rejected / http_rejected / unknown`、`film.fake.unknown_model`、`tts.volc`、`tts.unknown_provider`；加 `rate.video`、`rate.tts`；Step 3 第 3 条的七条改字（英文同步：去掉 `{console}`，"ask the administrator to check" 的说法）。
- `tests/server-msg.test.ts` 第 74–82 行（旧会话多余参数的回归）：把 `film.ark.connect_failed` / `film.ark.unknown_model` 换成 `film.vendor.connect_failed` / `film.settings.no_model`，断言不变（多余参数不显示）。
- `tests/film.test.tsx` 第 498–509 行：`film.minimax.moderated` → `film.vendor.input_moderated`，夹具里的 `error` 文字换成不带厂商名的。
- `tests/compose.test.tsx` 里 3 处 `tts.volc.*` → `tts.vendor.*`。

- [ ] **Step 6: 运行，确认通过**

运行：`cd backend && for t in tests/pipeline/test_*.py tests/server/test_*.py tests/render/test_*.py tests/assistant/test_*.py; do .venv/bin/python $t || echo FAIL $t; done`
预期：没有 `FAIL`。仍有断言旧文案（「控制台」「厂商暂时不可用…：原文」）的测试按新文案改。

运行：`cd frontend && npm test`
预期：通过（`srv-codes`：语言包与登记表一致）。

运行：`cd backend && grep -nE "minimax|seedance|volc|方舟|豆包|火山|MiniMax|海螺" server/messages_codes.json | head`
预期：没有输出。

---

### Task 4: 档位映射表

**Files:**
- Create: `backend/render/tiers.py`
- Modify: `backend/server/messages.py`、`messages_codes.json`（`tier.*`）
- Modify: `frontend/src/i18n/zh.ts`、`en.ts`（`srv.tier`）
- Modify: `backend/tests/server/test_i18n_scan.py`（`MODULES` 加 `"render/tiers.py": None`）
- Test: `backend/tests/render/test_tiers.py`（新）

- [ ] **Step 1: 写失败的测试** `backend/tests/render/test_tiers.py`

开头照 `tests/render/test_providers.py`（`sys.path`、把 `pipeline.config._load_dotenv` 换成空操作）。要点：

```python
import os
os.environ.pop("MINIMAX_API_KEY", None); os.environ.pop("ARK_API_KEY", None)
os.environ["STORYBOARD_VIDEO_PROVIDER"] = "fake"
from render import providers, tiers
from render.providers import minimax, seedance
from render.providers.fake import FakeVideo
from server import messages as M, public as P

# 1. 双向换算；不认识的
assert tiers.resolve("a-standard") == ("minimax", "minimax-h3") and tiers.resolve("b-lite") == ("seedance", "seedance-2.0-mini")
assert tiers.tier_of("seedance", "seedance-2.0-fast") == "b-fast" and tiers.tier_of("minimax", "nope") is None
try: tiers.resolve("minimax-h3"); raise AssertionError("应抛 KeyError")
except KeyError: pass
# 2. 表与厂商模块对得上：每个组合都是那家真有的档位；每家的每个档位都在表里；id 不重复
for tid, p, m in tiers.TIERS:
    table = {"minimax": minimax.MODELS, "seedance": seedance.MODELS, "fake": {"fake-1": {}}}[p]
    assert m in table, (tid, p, m)
assert {m for _, p, m in tiers.TIERS if p == "minimax"} == set(minimax.MODELS)
assert {m for _, p, m in tiers.TIERS if p == "seedance"} == set(seedance.MODELS)
assert len({t for t, _, _ in tiers.TIERS}) == len(tiers.TIERS)
# 3. 显示名是登记过的消息，id 与显示名里没有厂商词
for tid, _, _ in tiers.TIERS:
    assert M.registered(tiers.label(tid)["code"]) and not P.find_vendor_words([tid, M.render_zh(tiers.label(tid)["code"], {})])
# 4. options：没配密钥的厂商不列；假厂商设为默认时列 demo；字段齐全
providers.register("fake", lambda: FakeVideo())
(o,) = tiers.options()
assert o["id"] == "demo" and o["resolutions"] == ["480p", "720p"] and o["default_resolution"] == "720p"
assert o["cny_per_sec"] == {"480p": 0.5, "720p": 1.0} and "tts_all" in o["audio_modes"] and o["label"] == tiers.label("demo")
# 5. 配了密钥（假值，不联网）就列出来
os.environ["MINIMAX_API_KEY"] = "k-test"
assert [x["id"] for x in tiers.options()] == ["a-standard", "a-fast", "a-lite", "demo"]
# 6. 后台表：带厂商与密钥状态
rows = {r["id"]: r for r in tiers.admin_table()}
assert rows["a-standard"] == {"id": "a-standard", "provider": "minimax", "model": "minimax-h3",
                              "vendor_label": minimax.MODELS["minimax-h3"]["label"], "key_configured": True}
assert rows["b-fast"]["vendor_label"] == seedance.MODELS["seedance-2.0-fast"]["label"] and rows["demo"]["vendor_label"] == "fake"
assert rows["b-fast"]["key_configured"] is False and rows["demo"]["key_configured"] is True
```

- [ ] **Step 2: 运行，确认失败**

运行：`cd backend && .venv/bin/python tests/render/test_tiers.py`
预期：失败，`ImportError`。

- [ ] **Step 3: 登记显示名**（`messages.py`，`rate.*` 附近）

```python
register("tier.a_standard", "引擎 A · 标准")
register("tier.a_fast", "引擎 A · 快速")
register("tier.a_lite", "引擎 A · 经济")
register("tier.b_standard", "引擎 B · 标准")
register("tier.b_fast", "引擎 B · 快速")
register("tier.b_lite", "引擎 B · 经济")
register("tier.demo", "演示（不联网、不花钱）")
```

重新生成 `messages_codes.json`。前端 `zh.ts` 的 `srv` 加 `tier: { a_standard: '引擎 A · 标准', … }`，`en.ts` 加 `tier: { a_standard: 'Engine A · Standard', a_fast: 'Engine A · Fast', a_lite: 'Engine A · Economy', b_standard: 'Engine B · Standard', b_fast: 'Engine B · Fast', b_lite: 'Engine B · Economy', demo: 'Demo (offline, free)' }`。

- [ ] **Step 4: 新建 `backend/render/tiers.py`**（完整内容）

```python
"""出片档位：给普通用户的中性 id ↔（厂商，厂商内档位）。映射只在这里；接口只收发中性 id，会话文件里仍存厂商与档位
（spec 2026-11-21-vendor-name-cleanup §5）。新增厂商或档位：在 TIERS 加一行，并在 server/messages.py 登记 tier.<id>。"""
from typing import Optional

from render import providers
from render.providers import base

# (档位 id, 厂商, 厂商内档位)；顺序即界面上的顺序
TIERS = (
    ("a-standard", "minimax", "minimax-h3"),
    ("a-fast", "minimax", "minimax-h3-highspeed"),
    ("a-lite", "minimax", "minimax-h3-lite"),
    ("b-standard", "seedance", "seedance-2.0"),
    ("b-fast", "seedance", "seedance-2.0-fast"),
    ("b-lite", "seedance", "seedance-2.0-mini"),
    ("demo", "fake", "fake-1"),
)


def label(tier_id: str) -> dict:
    return {"code": "tier." + tier_id.replace("-", "_"), "params": {}}


def resolve(tier_id: str) -> tuple:
    """中性 id → (厂商, 厂商内档位)；不认识抛 KeyError。"""
    for tid, p, m in TIERS:
        if tid == tier_id:
            return p, m
    raise KeyError(tier_id)


def tier_of(provider: Optional[str], model: Optional[str]) -> Optional[str]:
    """(厂商, 厂商内档位) → 中性 id；表里没有（下线了的档位、测试里临时注册的厂商）返回 None。"""
    return next((tid for tid, p, m in TIERS if (p, m) == (provider, model)), None)


def _has_key(provider: str) -> bool:
    return provider not in providers._KEY_ENV or providers._has_key(provider)


def options() -> list:
    """界面可选的档位：厂商在可选名单里（假厂商只在被设为默认时）、密钥已配、对象建得起来。
    每项带那一档的分辨率、缺省分辨率、每秒价格、可选的声音模式——换档时界面不用先应用就能把这些一起选好。"""
    from render import compose      # 放函数里：compose 不依赖本模块，避免导入环
    usable = set(providers.names())
    out = []
    for tid, p, m in TIERS:
        if p not in usable or not _has_key(p):
            continue
        try:
            caps = providers.get_video(p).caps(m)
        except (KeyError, base.ProviderError):
            continue
        res = list(caps.resolutions)
        out.append({"id": tid, "label": label(tid), "resolutions": res,
                    "default_resolution": "720p" if "720p" in res else res[0],
                    "cny_per_sec": dict(caps.cny_per_sec), "audio_modes": compose.audio_modes(caps)})
    return out


def _vendor_label(provider: str, model: str) -> str:
    """厂商自己的档位名：读各厂商模块的静态档位表，不建厂商对象、不需要密钥。只给管理员接口用。"""
    if provider == "minimax":
        from render.providers import minimax
        return minimax.MODELS[model]["label"]
    if provider == "seedance":
        from render.providers import seedance
        return seedance.MODELS[model]["label"]
    return provider


def admin_table() -> list:
    """给管理员：每个档位背后是谁、厂商自己怎么叫它、密钥配了没有。只在 /admin 接口里用。"""
    return [{"id": tid, "provider": p, "model": m, "vendor_label": _vendor_label(p, m), "key_configured": _has_key(p)}
            for tid, p, m in TIERS]
```

`test_i18n_scan.py` 的 `MODULES` 加 `"render/tiers.py": None`。

- [ ] **Step 5: 运行，确认通过**

运行：`cd backend && for t in tests/render/test_tiers.py tests/server/test_messages.py tests/server/test_i18n_scan.py; do .venv/bin/python $t || echo FAIL $t; done`
预期：没有 `FAIL`。

运行：`cd frontend && npx vite build --ssr tests/srv-codes.test.ts --outDir .ssrout --logLevel error && node .ssrout/srv-codes.test.js`
预期：`ALL PASS`。

---

### Task 5: 接口出口——会话视图、设置收档位、任务列表、音色、合成预览、助手工具、文件名

**Files:**
- Modify: `backend/server/app.py`
- Modify: `backend/render/session.py`（`clip_dest`）
- Modify: `backend/assistant/tools.py`（`film_status`）、`backend/assistant/actions.py`（`film_run` 的说明文字）
- Modify: `backend/tests/server/test_i18n_scan.py`（`app.py` 的函数名单加 `_film_view`、`_settings_patch`）
- Test: `backend/tests/server/test_render.py`、`test_render_free.py`、`test_film_tasks.py`、`test_compose.py`、`backend/tests/render/test_session.py`、`backend/tests/assistant/test_tools.py`

- [ ] **Step 1: 核对测试不读真实 `.env`**

运行：`cd backend && grep -L "_load_dotenv = lambda" tests/server/test_*.py`
预期：列出的每个文件，若它会请求 `/render/…session` 或其它返回会话视图的接口（`grep -l "render/session\|/run\|/cancel\|/free" <文件>`），就在导入 `server.*` 之前补上与 `tests/server/test_film_tasks.py` 第 22–24 行相同的三行。补完再跑一遍该文件确认仍 `ALL PASS`。

- [ ] **Step 2: 写失败的测试**

`tests/server/test_render.py`（开头已把假厂商设为默认）加一组，其余现有断言里读 `s["provider"]`、`s["model"]`、`options["providers"]`、`options["models"]`、`options["default_note"]`、尝试的 `video_url` 的地方按新形状改：

```python
    # 视图是给普通用户的：没有厂商与模型，档位是中性 id
    s = c.post(R + "/session", headers=H, json={"budget_cny": 1000}).json()
    assert "provider" not in s and "model" not in s and s["tier"] == "demo"
    assert [t["id"] for t in s["options"]["tiers"]] == ["demo"] and s["options"]["tiers"][0]["label"] == {"code": "tier.demo", "params": {}}
    assert not {"providers", "models", "default_note"} & set(s["options"])
    assert s["options"]["rate_note"] == {"code": "rate.video", "params": {}}
    # 设置只收 tier：不认识的 422；带 provider / model 的 422（不再接受）
    r = c.patch(R + "/session", headers=H, json={"tier": "nope"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "film.settings.no_model"
    assert c.patch(R + "/session", headers=H, json={"provider": "fake"}).status_code == 422
    assert c.patch(R + "/session", headers=H, json={"model": "fake-1"}).status_code == 422
    r = c.patch(R + "/session", headers=H, json={"tier": "demo", "resolution": "480p"})
    assert r.status_code == 200 and r.json()["tier"] == "demo" and r.json()["resolution"] == "480p"
    # 存储没变：会话文件里仍是厂商与档位
    raw = render_session.load(root)
    assert raw["provider"] == "fake" and raw["model"] == "fake-1"
    # 出一段之后：尝试只有白名单字段，任务号是短键，文件名用短键
    …（照文件里现有的出片流程跑到 done）
    a = clip["attempts"][-1]
    real = render_session.load(root)["clips"][0]["attempts"][-1]
    assert a["task_id"] == public.task_key(real["task_id"]) != real["task_id"]
    assert not {"video_url", "last_frame_url", "usage", "billing", "known_cost_cny"} & set(a)
    assert a["file"] == f'clips/{clip["id"]}.{a["task_id"]}.mp4'
```

`tests/server/test_film_tasks.py`：
- 取消后才出结果的那条：`id` 末尾是 `public.task_key(真实任务号)`；
- 「带厂商名的失败原因返回 null」那几条改成：经出口后给出中性代码（例如把段的 `error_msg` 写成旧的 `film.minimax.insufficient_balance`，任务列表里 `error.code == "film.vendor.balance"`、`error.message` 没有厂商词）；只有文字、没有代码的 → `error.code == "common.failed_generic"`；段上什么错误信息都没有 → `null`；
- 合成的 `step` 没有代码时为 `null`。

`tests/server/test_compose.py`：音色接口的响应没有 `provider` 键、`rate_note == {"code": "rate.tts", "params": {}}`。

`tests/render/test_session.py`：`clip_dest(root, "E01-C01", "cgt-1").name == "E01-C01." + public.task_key("cgt-1") + ".mp4"`。

`tests/assistant/test_tools.py`：把一段的 `error` 写成带厂商名的旧文字、`error_msg` 写成旧代码，`film_status` 的输出里没有厂商词（`public.find_vendor_words(json.loads(输出)["session"]["pending"]) == []`），且有中性的中文原因。

- [ ] **Step 3: 运行，确认失败**

运行：`cd backend && for t in tests/server/test_render.py tests/server/test_film_tasks.py tests/server/test_compose.py tests/render/test_session.py tests/assistant/test_tools.py; do .venv/bin/python $t || echo FAIL $t; done`
预期：五个都 `FAIL`。

- [ ] **Step 4: `app.py`**

导入补：`from pydantic import BaseModel, ConfigDict, Field`；`from render import tiers as render_tiers`；`from server import … public …`。

1. 设置请求体与换算（替换现有 `RenderSettingsBody`）：

   ```python
   class RenderSettingsBody(BaseModel):
       model_config = ConfigDict(extra="forbid")       # 厂商与厂商内档位不再从接口进来；带了就 422
       tier: Optional[str] = None                      # 中性档位 id（render/tiers.py）
       resolution: Optional[str] = None
       audio_mode: Optional[str] = None
       budget_cny: Optional[float] = Field(None, gt=0, le=100000)
       confirm_over_cny: Optional[float] = Field(None, ge=0, le=100000)


   def _settings_patch(body: Optional[RenderSettingsBody]) -> dict:
       """请求体 → 会话层的设置修改：档位 id 换成厂商与厂商内档位。"""
       patch = body.model_dump(exclude_none=True) if body else {}
       tier = patch.pop("tier", None)
       if tier is not None:
           try:
               patch["provider"], patch["model"] = render_tiers.resolve(tier)
           except KeyError:
               raise HTTPException(422, detail=msg("film.settings.no_model"))
       return patch
   ```

   `render_session_post`、`render_session_patch` 里的 `body.model_dump(exclude_none=True)` 换成 `_settings_patch(body)`。

2. 视图出口（放在 `_render_call` 下面）：

   ```python
   def _film_view(s: dict, lenient: bool = False) -> dict:
       """出片会话给界面的视图：会话层的完整视图过一遍普通用户出口（不带厂商、模型、厂商任务号、下载地址）。"""
       v = _render_call(render_session.view, s, lenient)
       return public.film_view(v, tier=render_tiers.tier_of(s.get("provider"), s.get("model")),
                               tiers=render_tiers.options(), rate_note=compact(msg("rate.video")))
   ```

   13 处 `_render_call(render_session.view, s)` / `(…, s, True)` 全部换成 `_film_view(s)` / `_film_view(s, True)`（`render_session_get` 之后挂 `gate`、`_film_cancel` 之后挂 `cancel_outcome` 的写法不变）。改完 `grep -n "render_session.view" server/app.py` 应只剩 `_film_view` 里那一处。

3. `_render_call` 的四个 `except` 分支与 `_tts`：`detail=to_detail(e, …)` 的结果若是带 `code` 的字典，过一遍出口再抛——加一个小函数：

   ```python
   def _public_detail(d):
       """HTTP 错误的 detail：带代码的消息过普通用户出口（旧代码归一、原文打码），附加字段（如 expected_cny）保留。"""
       if isinstance(d, dict) and d.get("code"):
           extra = {k: v for k, v in d.items() if k not in ("code", "params", "message", "ref")}
           return {**public.public_msg(d), **extra}
       return d
   ```

   `_render_call` 里写成 `detail=_public_detail(to_detail(e))`（409 分支是 `_public_detail(to_detail(e, expected_cny=e.expected_cny))`）；`_tts` 同理。

4. 任务列表：删除 `_VENDOR_WORDS` 常量，`_public_error` 里改用 `public.VENDOR_RE`（这个函数现在只给 `/jobs` 用，行为不变）。`_film_tasks` 里：
   - `"error": (_public_error(c, s.get("provider"), s.get("model")) if … else None)` → `"error": (_task_msg(c) if c["ended_as"] == "failed" else None)`；
   - 迟到结果的 `id`：`f'{row["id"]}:{public.task_key(a["task_id"])}'`；
   - 合成：`"step": _task_msg({"error_msg": f.get("step_msg")})`、`"error": _task_msg(f) if f["state"] == "failed" else None`；`names = …` 一行删掉。

   ```python
   def _task_msg(obj: dict) -> Optional[dict]:
       """任务队列里的失败原因或步骤：过普通用户出口。有代码按代码；只有文字的给通用文案；什么都没有为 None。"""
       text, m = public.error_pair(obj)
       return None if m is None else {**m, "message": text}
   ```

   `render_tasks` 的说明文字里「不能给普通用户看的为 null」改成「没有错误信息时为 null」。

5. 音色：`render_voices` 两处返回去掉 `"provider"` 键。
6. 合成预览：`render_compose_get` 返回前 `p["final"]`、`p["report"]` 过 `public.scrub_errors`（在 `_compose_preview` 末尾做，一处即可；`p` 里若有带 `error` / `error_msg` 的失败语音条列表，同样过一遍）。
7. `test_i18n_scan.py` 的 `app.py` 名单加 `"_film_view"`, `"_settings_patch"`, `"_public_detail"`, `"_task_msg"`。

- [ ] **Step 5: `session.py`、助手**

`clip_dest`：

```python
    from server import public                 # 放函数里：server 包依赖 render，不反过来在模块级导入
    return root / "clips" / f"{clip_id}.{public.task_key(task_id)}.mp4"
```

原来的 `safe = re.sub(…)` 一行删掉（短键只有字母数字）。说明文字改成「按任务号的短键命名（文件名不带厂商任务号）；已有文件不改名」。

`assistant/tools.py` 的 `film_status`：`"error": c.get("error")` → `"error": public.error_pair(c)[0]`（文件头 `from server import … public`）。`assistant/actions.py` 的 `film_run` 说明里「选好厂商与档位」→「选好档位」。

- [ ] **Step 6: 运行，确认通过**

运行：`cd backend && for t in tests/pipeline/test_*.py tests/server/test_*.py tests/render/test_*.py tests/assistant/test_*.py; do .venv/bin/python $t || echo FAIL $t; done`
预期：没有 `FAIL`。其余测试里读旧字段的断言（`test_render_free.py`、`test_cancel*.py` 经接口的部分、`test_assistant_ops.py`）按新形状改到全绿。直接调 `render_session.view` 的测试（`tests/render/`）不受影响——那是完整视图。

---

### Task 6: 前端——类型、出片面板的档位下拉、文案去厂商

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/components/FilmPanel.tsx`、`ComposePanel.tsx`
- Modify: `frontend/src/i18n/zh.ts`、`en.ts`
- Test: `frontend/tests/film.test.tsx`、`graph-view.test.tsx`、`compose.test.tsx`、`routing.test.tsx`、`film-lane.test.ts`、`node-graph.test.ts`、`sheet-view.test.tsx`、`shot-sheet.test.ts`、`landing.test.tsx`

- [ ] **Step 1: 写失败的测试**（`tests/film.test.tsx`）

夹具里的会话换成新形状：去掉 `provider`、`model`、`options.providers / models / default_note`，加

```ts
tier: 'demo',
options: { …, rate_note: { code: 'rate.video', params: {} },
  tiers: [
    { id: 'demo', label: { code: 'tier.demo', params: {} }, resolutions: ['480p', '720p'], default_resolution: '720p',
      cny_per_sec: { '480p': 0.5, '720p': 1 }, audio_modes: ['tts_all', 'all_native', 'silent'] },
    { id: 'a-fast', label: { code: 'tier.a_fast', params: {} }, resolutions: ['768P', '480P'], default_resolution: '768P',
      cny_per_sec: { '768P': 0.4, '480P': 0.26 }, audio_modes: ['tts_all', 'silent'] },
  ] },
```

把第 475–483 行的「10f. 缺省回落提示」整段换成档位下拉的断言：

```ts
// 10f. 设置区只有一个档位下拉：选项是中性名字；没有「厂商」下拉；摘要一行带档位名
{
  const sel = container.querySelector<HTMLSelectElement>('select[data-testid="film-tier"]')!
  must(!!sel && [...sel.options].map((o) => o.textContent).join('|') === `${zh.srv.tier.demo}|${zh.srv.tier.a_fast}`, '档位下拉的选项')
  must(container.querySelectorAll('.film__settings select').length === 3, '设置区只有档位、分辨率、声音三个下拉（没有厂商下拉）')
  must((container.querySelector('.film__settings summary')?.textContent ?? '').includes(zh.srv.tier.demo), '摘要带档位名')
  // 换到引擎 A · 快速：分辨率选项换成那一档的，当前 720p 不在其中 → 草稿取那一档的缺省 768P；声音模式不在其中 → 全部配音
  setV.call(sel, 'a-fast'); sel.dispatchEvent(new Event('change', { bubbles: true })); await tick()
  const res = container.querySelector<HTMLSelectElement>('select[data-testid="film-resolution"]')!
  must([...res.options].map((o) => o.value).join('|') === '768P|480P' && res.value === '768P', '换档带出分辨率')
  // 应用：请求体只有 tier / resolution / audio_mode 等，没有 provider、model
  …（点「应用设置」，取桩后端记下的最后一次 PATCH 请求体）
  must(body.tier === 'a-fast' && body.resolution === '768P' && !('provider' in body) && !('model' in body), '请求体用档位 id')
}
// 10g. 原档位已不可用（tier 为 null）：下拉停在占位项，摘要写「原档位已不可用」，其它功能照常
{
  film = { ...film!, tier: null }
  await rerender()
  must((container.querySelector('.film__settings summary')?.textContent ?? '').includes(zh.film.panel.tierGone), '摘要')
  must(container.querySelector<HTMLSelectElement>('select[data-testid="film-tier"]')!.value === '', '下拉占位')
}
```

（`setV`、`tick`、`rerender`、桩后端的写法沿用该文件里已有的。）

其余测试文件：会话夹具同样换成新形状（`provider: 'fake', model: 'fake-1'` → `tier: 'demo'`；`options.providers / models` → `options.tiers`；音色夹具去掉 `provider`）。`tests/landing.test.tsx` 加一句：FAQ「支持哪些模型」的回答渲染出来等于 `zh.landing.faq.models.a`（文案本身由 Task 9 的守卫查）。

- [ ] **Step 2: 运行，确认失败**

运行：`cd frontend && npm run typecheck; npx vite build --ssr tests/film.test.tsx --outDir .ssrout --logLevel error && timeout 100 node .ssrout/film.test.js`
预期：类型检查报错（`tier` 不在 `FilmSession` 上）或测试失败。

- [ ] **Step 3: 类型**（`types.ts`）

```ts
/** 出片档位：中性 id 与显示名（后端 render/tiers.py）；带这一档的可选分辨率、每秒价格、声音模式 */
export interface FilmTierOption {
  id: string
  label: MsgLike
  resolutions: string[]
  default_resolution: string
  cny_per_sec: Record<string, number>
  audio_modes: AudioMode[]
}
```

- `FilmSettings`：`provider?`、`model?` 换成 `tier?: string`。
- `FilmSession`：删 `provider`、`model`；加 `/** 当前档位（中性 id）；原档位已不可用时为 null */ tier: string | null`。`options`：删 `providers`、`models`、`default_note`；加 `tiers: FilmTierOption[]`。
- `FilmAttempt.task_id` 的注释改成「这次任务的短键（不是服务商的任务号）；还没提交为 null」。
- `VoicesInfo`：删 `provider`。
- 注释里出现的厂商名一并去掉（如 `default_note` 那两行随字段删除）。

- [ ] **Step 4: `FilmPanel.tsx` 的 `Settings`**

```tsx
function Settings({ s, film }: { s: FilmSession; film: Film }) {
  const { t, locale } = useI18n()
  const [draft, setDraft] = useState<FilmSettings>({})
  const val = <K extends 'resolution' | 'audio_mode' | 'budget_cny' | 'confirm_over_cny'>(k: K) => draft[k] ?? s[k]
  const tiers = s.options.tiers
  const tierId = draft.tier ?? s.tier ?? ''
  const tierName = (id: string | null) => {
    const x = tiers.find((o) => o.id === id)
    return x ? formatMsg(x.label, locale) : t('film.panel.tierGone')
  }
  // 草稿换了档位：分辨率、价格、声音模式的可选项取那一档的；没换就用会话当前的
  const picked = draft.tier && draft.tier !== s.tier ? tiers.find((o) => o.id === draft.tier) : undefined
  const resolutions = picked ? picked.resolutions : s.options.resolutions
  const prices = picked ? picked.cny_per_sec : s.options.cny_per_sec
  const audioModes = picked ? picked.audio_modes : s.options.audio_modes
  const pickTier = (id: string) => {
    const nt = tiers.find((o) => o.id === id)
    if (!nt) return
    setDraft({
      ...draft, tier: id,
      resolution: nt.resolutions.includes(val('resolution')) ? draft.resolution : nt.default_resolution,
      audio_mode: nt.audio_modes.includes(val('audio_mode')) ? draft.audio_mode : 'tts_all',
    })
  }
  …
      <summary>
        {t('film.panel.settingsSum', { tier: tierName(s.tier), res: s.resolution,
          audio: label(AUDIO_MODE, s.audio_mode), cap: yuan(s.budget_cny) })}
      </summary>
      <label className="field">
        <span>{t('film.panel.tier')}</span>
        <select data-testid="film-tier" value={tierId} onChange={(e) => pickTier(e.target.value)}>
          {s.tier === null && !draft.tier ? <option value="" disabled>{t('film.panel.tierGone')}</option> : null}
          {tiers.map((o) => <option key={o.id} value={o.id}>{formatMsg(o.label, locale)}</option>)}
        </select>
      </label>
      <label className="field">
        <span>{t('film.panel.resolution')}</span>
        <select data-testid="film-resolution" value={val('resolution')} onChange={(e) => setDraft({ ...draft, resolution: e.target.value })}>
          {resolutions.map((r) => {
            const price = prices[r]
            return <option key={r} value={r}>{`${r}${price !== undefined ? t('film.panel.resPrice', { price }) : ''}`}</option>
          })}
        </select>
      </label>
```

删除：原来的「厂商」下拉、`otherProvider` 分支与 `providerNote`、`default_note` 那一行。声音下拉的选项改用 `audioModes`。`<Settings key={…}>` 的 key 里 `s.provider, s.model` 换成 `s.tier`。`formatMsg` 从 `@/i18n/serverMsg` 导入（文件里若已有就不重复）。「应用设置」的启用条件、`film.saveSettings(draft)` 不变。

`ComposePanel.tsx` 第 91 行：`t('compose.panel.voicesSum', { provider: v.provider ?? '' })` → `t('compose.panel.voicesSum')`。

- [ ] **Step 5: 文案**（`zh.ts` / `en.ts`，非 `srv` 节点）

| 键 | 新中文 | 新英文 |
|---|---|---|
| `money.rateNote` | 费率依据：{note}。实际花费以结算为准。 | Pricing basis: {note}. Actual charges are settled afterwards. |
| `money.rateUnknown` | 未注明 | not stated |
| `landing.faq.cost.a` | 「按厂商刊例价估算」→「按公开刊例价估算」（其余不变） | 同义改写 |
| `landing.faq.models.a` | 分镜由大语言模型生成；出片与配音接入了多家视频生成与语音合成服务，在出片设置里按「引擎」与档位选择，我们会持续评估并更换更合适的服务。 | Storyboards are written by a large language model. Rendering and voice use several video-generation and speech services; you pick an engine and tier in the render settings, and we keep evaluating and swapping in better ones. |
| `flow.…uncertain`（第 409 行） | 有段结果不明：先到出片面板核对 | 同义 |
| `film.uncertain` | 生成服务那边可能还有这一段的任务，请联系管理员核对 | The generation service may still hold a task for this clip; please ask the administrator to check. |
| `film.panel.intro` | 按所选档位的能力把镜头切成段、组装提示词（不花钱）；先试一段，满意后再出剩余各段。 | 同义 |
| `film.panel.settingsSum` | 设置 · {tier} · {res} · {audio} · 上限 {cap} | Settings · {tier} · {res} · {audio} · cap {cap} |
| `film.panel.provider`、`film.panel.providerNote`、`film.panel.defaultNote` | **删除** | **删除** |
| `film.panel.tierGone`（新） | 原档位已不可用，请重选 | Previous tier is no longer available — pick another |
| `film.panel.uncertain` | {n} 段结果不明：生成服务那边可能还有任务在跑或已扣费，请联系管理员核对； 批量出片会跳过它们，确认没有生成再单独重做。 | 同义 |
| `film.panel.clipUncertain` | 这一段结果不明：生成服务那边可能还有任务在跑或已扣费，请联系管理员核对，确认没有生成再重做。 | 同义 |
| `graph.noSession`（第 1265 行） | 先在出片页签选好档位 | Pick a tier on the Render tab first |
| `graph.…overRefs`（第 1309 行） | 参考超出当前档位上限（{n} / {max}） | 同义 |
| `compose.panel.voicesSum` | 音色 | Voices |
| `compose.panel.voicesNote` | 不变（`{note}` 现在是中性的 `rate.tts`） | 不变 |

行号是 2026-11-21 的 `zh.ts`；`en.ts` 里是同名键。`MoneyConfirm.tsx` 不用改（它只渲染传进来的 `rateNote`）。

- [ ] **Step 6: 运行，确认通过**

运行：`cd frontend && npm test`
预期：通过。

运行：`cd frontend && npm run lint 2>&1 | tail -3`
预期：0 error，5 warnings。

运行：`cd frontend && grep -nE "provider|defaultNote|default_note" src/components/FilmPanel.tsx src/components/ComposePanel.tsx`
预期：没有输出。

---

### Task 7: 渲染任务包去厂商

**Files:**
- Modify: `backend/render/plan.py`、`backend/adapters/seedance.py`
- Modify: `backend/tests/render/golden_plan_yao.json`
- Modify: `frontend/src/components/RenderView.tsx`、`frontend/src/i18n/zh.ts`、`en.ts`
- Test: `backend/tests/pipeline/test_offline.py`、`backend/tests/render/test_compose.py`、`frontend/tests/flow.test.tsx`

- [ ] **Step 1: 写失败的测试**

`tests/pipeline/test_offline.py` 第 851 行附近：

```python
    assert {t["id"] for t in plan["tiers"]} == {"standard", "lite"}
    assert plan["estimate"]["model"] == "standard"
    from render import plan as plan_mod
    from server import public as P
    legacy = plan_mod.build_plan(doc, 15.0, None, "seedance-2.0-mini")      # 旧 id 照样接受，响应里是新 id
    assert legacy["estimate"]["model"] == "lite"
    probe = {k: plan[k] for k in ("estimate", "tiers")}                     # 不扫 clips / assets：那是用户的分镜内容
    assert not P.find_vendor_words(probe), P.find_vendor_words(probe)
    head = "\n".join(l for l in md.splitlines() if l.startswith("#") or "发给" in l)   # md：该测试里已有的生产包文本变量
    assert not P.find_vendor_words(head)
```

（`build_plan` 的参数顺序以 `render/plan.py` 的签名为准；`md` 用该测试里已有的 Markdown 变量名。）

`frontend/tests/flow.test.tsx`：桩后端里的 `'seedance-2.0'` / `'seedance-2.0-mini'` 换成 `'standard'` / `'lite'`，标签换成「标准档」「轻量档」，Markdown 标题换成「视频生成生产包」；第 1233–1237 行选档的断言相应改成 `'lite'`。

- [ ] **Step 2: 运行，确认失败**

运行：`cd backend && .venv/bin/python tests/pipeline/test_offline.py; cd ../frontend && npx vite build --ssr tests/flow.test.tsx --outDir .ssrout --logLevel error && node .ssrout/flow.test.js`
预期：后端失败（档位 id 断言）；前端失败（缺省档位仍是旧 id）。

- [ ] **Step 3: 后端**

`render/plan.py`：

```python
RATE_SOURCE = "2026-03 公开报道的资费，非官方定价页，未经账单核对"

TIERS = {
    "standard": {"label": "标准档", …其余字段不变…},
    "lite": {"label": "轻量档", …其余字段不变，caveat 里的「mini 的」改成「轻量档的」…},
}
DEFAULT_TIER = "standard"
LEGACY_TIERS = {"seedance-2.0": "standard", "seedance-2.0-mini": "lite"}    # 旧前端、旧书签里的 id
```

`estimate()` 开头加 `model = LEGACY_TIERS.get(model, model)`。模块说明与注释里的厂商名可以留（不对外）。`estimate` 的 `note` 里「用 STORYBOARD_RENDER_CNY_PER_SECOND 钉死即可」保留（环境变量名不是厂商名）。

`adapters/seedance.py` 的 `render_episode` 与它调用的概览函数里三处对外文字：

- `—— Seedance 2.0 生产包` → `—— 视频生成生产包`
- `把代码块整段发给 Seedance，` → `把代码块整段发给视频生成模型，`
- `## 二、Seedance 时间轴提示词（` → `## 二、时间轴提示词（`

命令行入口（`main`、输出文件名 `_seedance.md`）与模块说明不动。

金样 `tests/render/golden_plan_yao.json`：用一段一次性脚本做同样的字面替换（不要手改 1800 行的文件）：

```bash
cd backend && .venv/bin/python - <<'EOF'
import pathlib
p = pathlib.Path("tests/render/golden_plan_yao.json")
s = p.read_text(encoding="utf-8")
for a, b in [("Seedance 2.0 生产包", "视频生成生产包"), ("整段发给 Seedance，", "整段发给视频生成模型，"),
             ("二、Seedance 时间轴提示词", "二、时间轴提示词"), ("Seedance 2.0（标准）", "标准档"), ("Seedance 2.0 mini", "轻量档"),
             ('"seedance-2.0-mini"', '"lite"'), ('"seedance-2.0"', '"standard"'),
             ("2026-03 公开报道的方舟资费", "2026-03 公开报道的资费")]:
    s = s.replace(a, b)
p.write_text(s, encoding="utf-8")
EOF
grep -c -iE "seedance|方舟" tests/render/golden_plan_yao.json
```

预期：最后一行输出 `0`。若 `caveat` 的字面改了，金样里对应的那句也要一致——以 `tests/render/test_compose.py` 第 1 项「生产包快照不变」通过为准。

- [ ] **Step 4: 前端**

`RenderView.tsx`：第 43 行 `useState('seedance-2.0')` → `useState('standard')`；第 117 行的回落 `{ id: 'seedance-2.0', … }` → `{ id: 'standard', label: t('renderPack.tierDefault') }`；第 29 行注释里的「按方舟公开资费」改成「按公开资费」。`zh.ts` 的 `renderPack.tierDefault` → `'标准档'`，`en.ts` → `'Standard'`。

- [ ] **Step 5: 运行，确认通过**

运行：`cd backend && for t in tests/pipeline/test_offline.py tests/render/test_compose.py tests/server/test_render.py; do .venv/bin/python $t || echo FAIL $t; done`
预期：没有 `FAIL`。

运行：`cd frontend && npx vite build --ssr tests/flow.test.tsx --outDir .ssrout --logLevel error && node .ssrout/flow.test.js`
预期：`ALL PASS`。

---

### Task 8: 管理员可见——`/admin/service` 的出片线路与后台卡片

**Files:**
- Modify: `backend/server/app.py`（`admin_service`）
- Modify: `frontend/src/types.ts`（`AdminService`）
- Modify: `frontend/src/components/admin/Overview.tsx`、`messages.zh.ts`、`messages.en.ts`
- Test: `backend/tests/server/test_admin.py`、`frontend/tests/admin.test.tsx`

- [ ] **Step 1: 写失败的测试**

`tests/server/test_admin.py`（开头若没有把 `_load_dotenv` 换成空操作就先补）：

```python
    svc = c.get("/admin/service", headers=ADMIN).json()
    film = svc["film"]
    assert {r["id"] for r in film["tiers"]} >= {"a-standard", "b-fast"}
    row = next(r for r in film["tiers"] if r["id"] == "a-standard")
    assert row["provider"] == "minimax" and row["model"] == "minimax-h3" and isinstance(row["key_configured"], bool)
    assert row["vendor_label"] == "MiniMax H3"
    assert set(film) == {"default_provider", "fell_back", "tiers", "tts"} and set(film["tts"]) == {"provider", "key_configured"}
    assert c.get("/admin/service", headers=USER).status_code == 403
```

（`ADMIN`、`USER` 用该文件里已有的管理员与普通用户请求头。）

`frontend/tests/admin.test.tsx`：桩后端的 `/admin/service` 响应加 `film`（两行：`a-standard → minimax / minimax-h3 / 已配`、`b-fast → seedance / seedance-2.0-fast / 未配`），断言概览页出现「出片线路」卡片、两行里有 `minimax`、`seedance-2.0-fast`、「已配置」「未配置」。

- [ ] **Step 2: 运行，确认失败**

运行：`cd backend && .venv/bin/python tests/server/test_admin.py; cd ../frontend && npx vite build --ssr tests/admin.test.tsx --outDir .ssrout --logLevel error && node .ssrout/admin.test.js`
预期：两个都失败。

- [ ] **Step 3: 后端**

```python
@app.get("/admin/service")
def admin_service(user: dict = Depends(admin_user)):
    """底层模型与密钥是否配置（账号菜单只给管理员显示），以及出片线路：每个档位背后的厂商、厂商内档位与密钥状态。"""
    s = load_settings()
    review = s.review_model if s.review_enabled and s.review_model and s.review_model != s.model else None
    tts_name = render_providers.default_tts_name()
    try:
        render_providers.get_tts(tts_name)
        tts_ok = True
    except (KeyError, render_video_base.ProviderError):
        tts_ok = False
    return {"model": s.model, "review_model": review, "api_key_configured": bool(s.api_key),
            "film": {"default_provider": render_providers.default_video_name(),
                     "fell_back": render_providers.default_fell_back(),
                     "tiers": render_tiers.admin_table(),
                     "tts": {"provider": tts_name, "key_configured": tts_ok}}}
```

- [ ] **Step 4: 前端**

`types.ts` 的 `AdminService` 加可选字段（旧后端没有时卡片不显示）：

```ts
  film?: {
    default_provider: string
    fell_back: boolean
    tiers: { id: string; provider: string; model: string; vendor_label: string; key_configured: boolean }[]
    tts: { provider: string; key_configured: boolean }
  }
```

`components/admin/Overview.tsx`：`OverviewBody` 里再取一份 `const svc = useLoad(adminService, [])`（`adminService` 从 `'../../api'` 导入——它本来就在主包；`refresh` 里加 `svc.reload()`），在分布小卡片之后渲染一张 `Card`：标题 `t('admin.overview.filmRoutes.title')`，一张四列的表（档位 id、厂商、厂商内档位、密钥），密钥列显示 `t('admin.overview.filmRoutes.keyOk')` / `keyMissing`（未配置用 `text-destructive`），表下一行小字写缺省厂商与配音厂商。`svc.data?.film` 没有时不渲染这张卡片。样式沿用该文件里现有卡片与表格的类名，不新增 CSS。

`messages.zh.ts` 的 `overview` 节点加：

```ts
    filmRoutes: { title: '出片线路', tier: '档位', provider: '厂商', model: '厂商内档位', key: '密钥',
                  keyOk: '已配置', keyMissing: '未配置', foot: '新会话缺省用 {provider}；配音：{tts}（{ttsKey}）' },
```

`messages.en.ts` 对应加英文。厂商名只来自接口，不写进这两个文件。

- [ ] **Step 5: 运行，确认通过**

运行：`cd backend && .venv/bin/python tests/server/test_admin.py && .venv/bin/python tests/server/test_i18n_scan.py`
预期：都 `ALL PASS`。

运行：`cd frontend && npx vite build --ssr tests/admin.test.tsx --outDir .ssrout --logLevel error && node .ssrout/admin.test.js && npx vite build --ssr tests/admin-shell.test.tsx --outDir .ssrout --logLevel error && node .ssrout/admin-shell.test.js`
预期：都 `ALL PASS`。

---

### Task 9: 产品界面里给管理员显示厂商名（数据只来自 `/admin/service`）

spec §9.2。**硬约束**：这一 Task 新写的前端源码（`src/` 下、后台目录之外）与语言包里不得出现任何厂商字面量，也不得按档位 id 写死对应关系；括号里的文字只能是接口数据。测试文件里可以写厂商名（测试不进打包产物）。

**Files:**
- Create: `frontend/src/adminHints.tsx`
- Modify: `frontend/src/App.tsx`（提供 context）
- Modify: `frontend/src/components/FilmPanel.tsx`、`NodeCards.tsx`、`NodeGraph.tsx`、`ComposePanel.tsx`、`components/shell/ActivityPanel.tsx`
- Modify: `frontend/src/types.ts`（`FilmTask.tier`）
- Modify: `backend/server/app.py`（`_film_tasks` 的行加 `tier`）
- Test: `backend/tests/server/test_film_tasks.py`、`frontend/tests/film.test.tsx`、`film-tasks.test.tsx`、`compose.test.tsx`、`graph-view.test.tsx`、`routing.test.tsx`

- [ ] **Step 1: 写失败的测试**

后端 `tests/server/test_film_tasks.py`：每条任务（片段、自由节点、合成）都有 `tier`，假厂商会话下等于 `"demo"`；把会话文件里的 `model` 改成表里没有的值后为 `None`。文件里若有断言任务行键集合的地方（上一轮验收记录是 17 个字段），加上 `tier`。

前端用同一份提示数据（测试里可以写厂商名）：

```ts
const HINTS = {
  default_provider: 'minimax', fell_back: false,
  tiers: [
    { id: 'demo', provider: 'fake', model: 'fake-1', vendor_label: 'ZZ-Vendor Demo', key_configured: true },
    { id: 'a-fast', provider: 'minimax', model: 'minimax-h3-highspeed', vendor_label: 'MiniMax H3 Highspeed', key_configured: true },
  ],
  tts: { provider: 'zz-tts', key_configured: true },
}
```

`tests/film.test.tsx`（出片面板，直接渲染组件）——同一段界面渲染两遍：

```ts
// 11. 管理员提示：外面包 <AdminHintsProvider value={HINTS}> 时，档位下拉、摘要、失败原因后面有括号里的厂商字样；
//     value 为 null 时与普通用户一字不差
{
  const plain = await renderPanel(null)          // renderPanel：按该文件现有的挂载方式，多包一层 AdminHintsProvider
  must(!plain.includes('ZZ-Vendor') && !plain.includes('MiniMax'), '没有提示数据：不出现厂商字样')
  const admin = await renderPanel(HINTS)
  const opts = [...container.querySelectorAll<HTMLOptionElement>('select[data-testid="film-tier"] option')].map((o) => o.textContent)
  must(opts.join('|') === `${zh.srv.tier.demo}（ZZ-Vendor Demo）|${zh.srv.tier.a_fast}（MiniMax H3 Highspeed）`, 'H1 下拉选项')
  must((container.querySelector('.film__settings summary')?.textContent ?? '').includes(`${zh.srv.tier.demo}（ZZ-Vendor Demo）`), 'H2 摘要')
  // 一段失败，错误码 film.vendor.balance：原因后面带括号；错误码 film.submit.stale（不是生成服务侧的）：不带
  must(admin.includes(`${zh.srv.film.vendor.balance}（ZZ-Vendor Demo）`), 'H4 生成服务侧的失败带提示')
  must(admin.includes(zh.srv.film.submit.stale) && !admin.includes(`${zh.srv.film.submit.stale}（`), '别的失败不带')
  // 去掉括号后与普通用户看到的一样（提示只是附加）
  must(admin.replaceAll('（ZZ-Vendor Demo）', '').replaceAll('（MiniMax H3 Highspeed）', '') === plain, '提示只是附加')
}
```

`tests/graph-view.test.tsx`：片段卡与自由节点卡上的失败原因（H3）同样两遍。`tests/compose.test.tsx`：配音面板标题有提示时是 `${zh.compose.panel.voicesSum}（zz-tts）`、没有时是 `zh.compose.panel.voicesSum`；合成失败码 `tts.vendor.unavailable` 带「（zz-tts）」（H6、H7）。`tests/film-tasks.test.tsx`：任务面板里一条 `tier: 'demo'`、`error.code: 'film.vendor.balance'` 的失败条目，有提示时原因后面带「（ZZ-Vendor Demo）」，`tier: null` 或没有提示时不带；合成条目的 `tts.vendor.*` 失败带「（zz-tts）」（H5、H7）。

`tests/routing.test.tsx`（整个应用 + 桩后端；`/admin/service` 的桩响应加上 `film: HINTS`）：

```ts
// 管理员提示的整条链路。adminSvcCalls 是该文件已有的计数器
// a) 普通用户：打开一章的画布、展开出片设置、打开任务面板——全程 0 次 /admin/service，页面上没有提示字样
must(adminSvcCalls === 0 && !document.body.textContent!.includes('ZZ-Vendor'), '普通用户不请求、不显示')
// b) 管理员：me() 返回后请求恰好 1 次；档位下拉的选项带「（ZZ-Vendor Demo）」
must(adminSvcCalls === 1 && tierOptions().some((x) => x.endsWith('（ZZ-Vendor Demo）')), '管理员看得到')
// c) 来回切页面、重开面板不再请求（内存里那一份）
must(adminSvcCalls === 1, '不重复请求')
// d) 退出登录，再以普通用户登录、回到同一个画布：没有新的请求，页面上没有提示字样
must(adminSvcCalls === 1 && !document.body.textContent!.includes('ZZ-Vendor'), '退出后清空')
// e) /admin/service 失败（桩返回 500）的管理员：界面与普通用户一样，不报错
```

（登录、退出、打开画布的写法沿用该文件第 486–507 行与第 926 行附近的现有段落；`tierOptions()` 是读 `select[data-testid="film-tier"]` 各选项文字的小函数。）

- [ ] **Step 2: 运行，确认失败**

运行：`cd backend && .venv/bin/python tests/server/test_film_tasks.py; cd ../frontend && npm run typecheck`
预期：后端失败（没有 `tier`）；类型检查报错（没有 `adminHints` 模块）。

- [ ] **Step 3: 后端**

`_film_tasks` 里循环开头算一次 `tier = render_tiers.tier_of(s.get("provider"), s.get("model"))`，片段 / 自由节点的 `row` 与合成的 `row` 两个字典都加 `"tier": tier`。`render_tasks` 的说明文字补一句「tier：所在会话的中性档位 id」。

- [ ] **Step 4: 新建 `frontend/src/adminHints.tsx`**（完整内容）

```tsx
/** 管理员提示：产品界面里在中性名字后面给管理员看的厂商字样。
 *  数据只来自 /admin/service（角色确认为管理员后由 App 请求一次），只放在内存里，退出登录即清空。
 *  这个文件、以及所有用它的组件里都不写任何厂商名：显示的文字是接口给的原样字符串。
 *  没有数据（普通用户、请求失败、旧后端）时两个钩子都给 null，界面与普通用户完全一样。 */
import { createContext, useContext } from 'react'
import type { AdminService } from './types'

export type AdminHints = NonNullable<AdminService['film']> | null

const Ctx = createContext<AdminHints>(null)
export const AdminHintsProvider = Ctx.Provider

/** (档位 id) → 厂商自己的档位名；不是管理员、档位不在表里时为 null */
export function useTierHint(): (tier: string | null | undefined) => string | null {
  const h = useContext(Ctx)
  return (tier) => (tier ? h?.tiers.find((r) => r.id === tier)?.vendor_label ?? null : null)
}

/** 配音厂商名；不是管理员时为 null */
export function useTtsHint(): string | null {
  return useContext(Ctx)?.tts.provider ?? null
}

/** 失败原因该不该带提示、带哪一种：生成服务侧的（film.vendor.*）用档位的，配音服务侧的（tts.vendor.*）用配音的 */
export function hintFor(code: string | undefined, tierHint: string | null, ttsHint: string | null): string | null {
  if (!code) return null
  if (code.startsWith('film.vendor.')) return tierHint
  if (code.startsWith('tts.vendor.')) return ttsHint
  return null
}
```

（`film.vendor.` / `tts.vendor.` 是中性的错误码前缀，不是厂商词，守卫不会命中。）

- [ ] **Step 5: `App.tsx` 提供数据**

现有第 1248 行附近已有同一个条件（`svcInfo && user?.role === 'admin' && svcInfo.uid === user.id`）。算一个值并包住整棵界面树：

```tsx
const adminHints = svcInfo && user?.role === 'admin' && svcInfo.uid === user.id ? svcInfo.info.film ?? null : null
…
<AdminHintsProvider value={adminHints}> …原来返回的整棵树… </AdminHintsProvider>
```

核对第 520–530 行那个请求 `/admin/service` 的 effect：用户变成 `null`、换了账号、角色不是管理员时都要 `setSvcInfo(null)`（现有代码已有的不动，缺哪种补哪种）。不新增请求、不写任何浏览器存储。`npm run lint` 的 `App.tsx` 那一条基线警告不得变成两条。

- [ ] **Step 6: 各显示位置**

统一写法——取提示、有就加括号：

```tsx
const tierHint = useTierHint()
const { t } = useI18n()
const withHint = (text: string, hint: string | null) => (hint ? text + t('common.paren', { text: hint }) : text)
```

| spec 编号 | 文件与位置 | 改法 |
|---|---|---|
| H1 | `FilmPanel.tsx` `Settings` 的档位 `<option>` | `withHint(formatMsg(o.label, locale), tierHint(o.id))` |
| H2 | `FilmPanel.tsx` `Settings` 的 `tierName` | 找到档位时 `withHint(…, tierHint(id))`；「原档位已不可用」不加 |
| H3 | `NodeCards.tsx` 片段卡与自由节点卡渲染 `itemError(…)` 的地方（约第 197 行） | 卡片新增可选属性 `tier?: string \| null`，`NodeGraph.tsx` 传 `session.tier`；`withHint(itemError(c, locale), hintFor(c.error_msg?.code, tierHint(tier), null))` |
| H4 | `FilmPanel.tsx` `ClipDetail`、`FreeDetail` 与尝试表里渲染 `itemError(…)` 的地方（约第 268、346 行） | 同 H3，档位取 `s.tier` |
| H5、H7 | `ActivityPanel.tsx` 出片与合成条目的失败原因 | `withHint(原因文字, hintFor(task.error?.code, tierHint(task.tier), ttsHint))`；「点开查看原因」的占位不加 |
| H6 | `ComposePanel.tsx` 配音面板标题 | `withHint(t('compose.panel.voicesSum'), useTtsHint())` |
| H7 | `ComposePanel.tsx` 渲染合成失败原因的地方 | `withHint(…, hintFor(final.error_msg?.code, null, ttsHint))` |

`types.ts` 的 `FilmTask` 加 `/** 所在会话的中性档位 id；管理员提示用 */ tier?: string | null`。`common.paren` 两份语言包里已有，不新增文案键。

- [ ] **Step 7: 运行，确认通过**

运行：`cd backend && for t in tests/server/test_film_tasks.py tests/server/test_i18n_scan.py; do .venv/bin/python $t || echo FAIL $t; done`
预期：没有 `FAIL`。

运行：`cd frontend && npm test && npm run lint 2>&1 | tail -3`
预期：测试通过；0 error，5 warnings。

运行：`cd frontend && grep -nIiE "minimax|seedance|doubao|volc|hailuo" src/adminHints.tsx src/App.tsx src/components/FilmPanel.tsx src/components/NodeCards.tsx src/components/NodeGraph.tsx src/components/ComposePanel.tsx src/components/shell/ActivityPanel.tsx`
预期：没有输出（提示文字只来自接口）。

---

### Task 10: 自动守卫

**Files:**
- Create: `frontend/tests/vendor-words.test.ts`
- Create: `frontend/tests/vendor-bundle.check.mjs`
- Create: `backend/tests/server/test_vendor_guard.py`
- Modify: `frontend/package.json`（`test` 脚本末尾接 `vendor-words`）
- Modify: `frontend/tests/film-tasks.test.tsx`（第 215 行的自带词表改用共用词表）

守卫在这里应当**一写出来就是绿的**。哪一个红了，说明前面的 Task 漏了一处：按报出的位置回到对应 Task 的范围内修，不要为了过守卫改词表或加豁免。先做一次「变异验证」确认守卫真的在查（各 Step 里写了怎么做）。

- [ ] **Step 1: 语言包守卫** 新建 `frontend/tests/vendor-words.test.ts`（完整内容）

```ts
/** 普通用户的语言包里不得出现厂商或模型名（文案与键名都查）。词表与后端共用：backend/server/vendor_words.json。
 *  反向对照：后台的语言包与价格表工具里有这些词（证明扫描有效；后台允许）。跑法：npm test（在 frontend/ 下） */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { zh } from '../src/i18n/zh'
import { en } from '../src/i18n/en'

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }
const words = JSON.parse(readFileSync(resolve(process.cwd(), '../backend/server/vendor_words.json'), 'utf-8')) as
  { substr: string[]; word: string[]; cjk: string[] }
const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
export const VENDOR_RE = new RegExp(
  [...words.substr.map(esc), ...words.cjk.map(esc), ...words.word.map((w) => `(?<![a-z0-9])${esc(w)}(?![a-z0-9])`)]
    .sort((a, b) => b.length - a.length).join('|'), 'gi')

/** 叶子：路径 → 文案；路径本身（键名）也要查 */
const leaves = (node: unknown, prefix = ''): [string, string][] =>
  Object.entries(node as Record<string, unknown>).flatMap(([k, v]) => {
    const p = prefix ? `${prefix}.${k}` : k
    return typeof v === 'string' ? [[p, v] as [string, string]] : leaves(v, p)
  })

for (const [name, pack] of [['zh', zh], ['en', en]] as const) {
  const bad = leaves(pack).filter(([path, text]) => `${path}\n${text}`.match(VENDOR_RE))
  must(bad.length === 0, `${name} 语言包里有厂商或模型名：\n` + bad.slice(0, 20).map(([p, t]) => `  ${p}: ${t}`).join('\n'))
  console.log(`${name}: ${leaves(pack).length} 条，无厂商词 ✓`)
}

// 反向对照：后台的源码里确实有这些词（读源文件，不 import，免得把后台代码拉进这个测试的构建）
const admin = ['messages.zh.ts', 'messages.en.ts', 'pricing.ts']
  .map((f) => readFileSync(resolve(process.cwd(), 'src/components/admin', f), 'utf-8')).join('\n')
must(!!admin.match(VENDOR_RE), '反向对照失败：后台源码里应能扫到厂商词（扫描失效？）')
// 词表自检：短词只在独立成词时命中
must(!'dark park spark'.match(VENDOR_RE) && !!'film.ark.x'.match(VENDOR_RE) && !!'MiniMax'.match(VENDOR_RE), '词表规则')
console.log('\nALL PASS')
```

`package.json` 的 `test` 脚本末尾（`film-tasks` 之后）接：` && vite build --ssr tests/vendor-words.test.ts --outDir .ssrout --logLevel error && node .ssrout/vendor-words.test.js`。

`tests/film-tasks.test.tsx` 第 215 行：`/minimax|seedance|fake|假厂商/i.test(text)` 改成从 `./vendor-words.test` 之外的途径取词表——在该文件顶部照上面的写法读 `vendor_words.json` 组一个同样的正则（十行以内；不要 import `vendor-words.test.ts`，它一导入就会执行），断言改成 `must(!VENDOR_RE.test(text) && !/假厂商/.test(text), '面板里不出现厂商名')`。

运行：`cd frontend && npx vite build --ssr tests/vendor-words.test.ts --outDir .ssrout --logLevel error && node .ssrout/vendor-words.test.js`
预期：`ALL PASS`。

变异验证：临时把 `zh.ts` 的 `landing.faq.models.a` 末尾加上「Seedance」，重跑上面的命令，预期失败并指出 `landing.faq.models.a`；改回去，重跑通过。

- [ ] **Step 2: 首屏打包产物守卫** 新建 `frontend/tests/vendor-bundle.check.mjs`（完整内容）

```js
/** 构建产物检查：首屏下发的文件（index.html 引用的脚本、样式及其静态依赖）里没有厂商或模型名；
 *  按需加载的块（运营后台）里有。词表与后端共用。
 *  跑法（在 frontend/ 下，先 npm run build）：node tests/vendor-bundle.check.mjs。不进 npm test（它依赖 dist）。 */
import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

const dist = new URL('../dist/', import.meta.url).pathname
const read = (rel) => readFileSync(join(dist, rel), 'utf8')
const must = (cond, msg) => { if (!cond) { console.error('✗ ' + msg); process.exit(1) } }
const words = JSON.parse(readFileSync(new URL('../../backend/server/vendor_words.json', import.meta.url), 'utf8'))
const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
const RE = new RegExp(
  [...words.substr.map(esc), ...words.cjk.map(esc), ...words.word.map((w) => `(?<![a-z0-9])${esc(w)}(?![a-z0-9])`)]
    .sort((a, b) => b.length - a.length).join('|'), 'gi')

// 首屏文件：与 admin-bundle.check.mjs 同一算法
const html = read('index.html')
const eager = new Set([...html.matchAll(/(?:src|href)="\/?(assets\/[^"]+\.(?:js|css))"/g)].map((m) => m[1]))
const queue = [...eager].filter((f) => f.endsWith('.js'))
while (queue.length) {
  const src = read(queue.pop())
  for (const m of src.matchAll(/(?:from|import)\s*"\.\/([^"]+\.js)"/g)) {
    const file = `assets/${m[1]}`
    if (!eager.has(file)) { eager.add(file); queue.push(file) }
  }
}
must([...eager].some((f) => f.endsWith('.js')), `index.html 应引用入口脚本，实为 ${[...eager]}`)

const hits = (text) => [...text.matchAll(RE)].map((m) => `${m[0]} @ …${text.slice(Math.max(0, m.index - 40), m.index + 40).replace(/\s+/g, ' ')}…`)
for (const file of ['index.html', ...eager]) {
  const found = hits(read(file))
  must(found.length === 0, `首屏文件 ${file} 里有厂商或模型名（共 ${found.length} 处），前几处：\n  ` + found.slice(0, 8).join('\n  '))
}

// 反向对照：按需加载的块（后台）里确实有，证明扫描有效
const lazy = readdirSync(join(dist, 'assets')).map((f) => `assets/${f}`).filter((f) => f.endsWith('.js') && !eager.has(f))
must(lazy.length > 0 && lazy.some((f) => hits(read(f)).length > 0), '反向对照失败：按需加载的后台块里应能扫到厂商词')

console.log(`首屏文件 ${eager.size + 1} 个，无厂商词；按需加载的块 ${lazy.length} 个`)
console.log('\nALL PASS')
```

运行：`cd frontend && npm run build && node tests/admin-bundle.check.mjs && node tests/vendor-bundle.check.mjs`
预期：都 `ALL PASS`。（基线：改动前的首屏脚本里有 100 多处命中，全部来自语言包；第三方库里没有命中。Task 9 的管理员提示不改变这个结果：厂商文字在接口数据里，不在脚本里——这条检查通过正是它的验收。）

- [ ] **Step 3: 后端响应守卫** 新建 `backend/tests/server/test_vendor_guard.py`

开头照 `tests/server/test_film_tasks.py`（临时数据目录、`_load_dotenv` 换空操作、`STORYBOARD_RENDER_RUNNER=0`），另外：

```python
os.environ["STORYBOARD_VIDEO_PROVIDER"] = "minimax"      # 用真实的厂商名注册桩：守卫要在最像线上的条件下查
os.environ["STORYBOARD_TTS_PROVIDER"] = "volc"
os.environ["MINIMAX_API_KEY"] = "k-test-not-real"        # 假值，只为让档位表把它当成已配置；桩不联网
os.environ.pop("ARK_API_KEY", None)
…
from render.providers.fake import FakeTts, FakeVideo
from server import public as P


class StubMiniMax(FakeVideo):
    name = "minimax"
    default_model = "minimax-h3"

    def __init__(self):
        super().__init__(polls_to_finish=1)
        self.models = {k: {"label": f"MiniMax {k}"} for k in ("minimax-h3", "minimax-h3-highspeed", "minimax-h3-lite")}


class StubVolc(FakeTts):
    name = "volc"


VIDEO = StubMiniMax()
providers.register("minimax", lambda: VIDEO)
providers.register_tts("volc", lambda: StubVolc())
FORBIDDEN_KEYS = ("video_url", "last_frame_url", "billing", "known_cost_cny", "provider", "providers", "models", "default_note")
# usage 不在禁止名单里：转换清单的尝试记录里有同名的用量字段（合法）。出片尝试里的 usage 在第 5 步单独断言。
```

（`FakeVideo.caps` 按 `self.models` 判档位，所以要把 `models` 换成真实的档位名；若 `FakeVideo` / `FakeTts` 的构造或类属性与此不符，按它们的实际写法调整桩，目标只是「名字是真的、行为是假的」。）

检查函数：

```python
def clean(label, resp, *, content=False):
    """这次响应里没有厂商词、没有禁止的键。content=True：响应里有用户的分镜正文，只查键名与错误字段，不做全文扫词。"""
    assert resp.status_code < 500, (label, resp.status_code, resp.text[:300])
    body = resp.json()
    if not content:
        assert not P.find_vendor_words(body), (label, P.find_vendor_words(body))
    def walk(v, path="$"):
        if isinstance(v, dict):
            for k, x in v.items():
                assert k not in FORBIDDEN_KEYS, (label, f"{path}.{k}")
                assert not (k == "model" and isinstance(x, str)), (label, f"{path}.model")
                walk(x, f"{path}.{k}")
        elif isinstance(v, list):
            for i, x in enumerate(v):
                walk(x, f"{path}[{i}]")
    walk(body)
    SEEN.add(label)
```

步骤：

1. 注册普通用户 alice 与管理员（`auth` 里现有的建管理员方式，参照 `tests/server/test_admin.py`）；建小说、章节、版本（夹具用 `tests/real_text_yao/output_merged.json`——它是鲁迅《药》，不含词表里的词；测试开头先断言 `P.find_vendor_words(DOC) == []`，夹具以后换了会立刻提醒）。
2. 建会话、出一段到完成、再排一段（走完整流程，留下真实形状的尝试）。
3. **投毒**（`with render_session.mutate(root) as s:`）：
   - 某段：`state="failed"`，`error="视频服务（MiniMax）账户余额不足，暂时无法出片，请联系管理员"`，`error_msg={"code": "film.minimax.insufficient_balance", "params": {}}`，`ended_at=now`，`ended_as="failed"`；
   - 另一段：只有文字 `error="KeyError: 'video_url' Seedance sk-live-12345 https://x.volces.com/v.mp4?X-Tos-Signature=zz"`，`error_msg=None`，同样标结束；
   - 第三段的一次尝试：`video_url="https://x.volces.com/v.mp4?X-Tos-Signature=zz"`、`last_frame_url=…`、`usage={"model": "doubao-seedance-2-0"}`、`billing={"provider": "minimax", "model": "minimax-h3", "resolution": "768P", "duration": 5, "estimate_cny": 2.5}`、`known_cost_cny=2.5`、`error_msg={"code": "film.provider.rejected", "params": {"detail": {"t": "vendor", "text": "MiniMax: prompt rejected"}}}`、`error="MiniMax: prompt rejected"`、`state="failed"`；
   - 再加一次迟到成功的尝试：`task_id="cgt-doubao-seedance-0001"`、`state="succeeded"`、`late=True`、`settled_at=now`、`file` 指向一个存在的假文件；
   - `final={"state": "failed", "started_at": now, "finished_at": now, "step": "配音", "step_msg": None, "error": "豆包语音拒绝了请求（45000）：Doubao TTS quota", "error_msg": {"code": "tts.volc.rejected", "params": {"code": "45000", "detail": {"t": "vendor", "text": "Doubao TTS quota"}}}, "detail": "ffmpeg … volc"}`。
4. 以 alice 的身份逐个调用并 `clean(...)`：
   - `GET /openapi.json`（免登录，接口说明与请求体缺省值也算对外）、`GET /healthz`、`GET /auth/me`；
   - `GET {R}/session`、`PATCH {R}/session`（`{"tier": "a-fast"}`，以及一个 422 的 `{"tier": "nope"}`）、`POST {R}/session`；
   - `GET /render/tasks`、`GET /jobs`；
   - `GET {R}/voices`、`GET {R}/compose`；
   - `POST {R}/clips/{id}/run`（409 / 200 都要查响应体）、`POST {R}/clips/{id}/cancel`、`PUT {R}/clips/{id}/chosen`、`PATCH {R}/clips/{id}`；
   - `POST {R}/free`、`PATCH {R}/free/{fid}`、`POST {R}/free/{fid}/cancel`（409 的错误体）、`DELETE {R}/free/{fid}`；
   - `POST /render/plan`（`content=True` 查键名，另外单独对 `plan["estimate"]`、`plan["tiers"]` 做全文扫词）；
   - `GET /novels/{nid}/summary`、`GET /novels/{nid}`、`GET /novels/{nid}/chapters/{cid}`、`GET …/versions/v1`（后三个 `content=True`）。
5. 具体断言（不只是「没有词」）：会话视图里每一次尝试的键都在 `set(P.ATTEMPT_KEYS) | {"task_id", "error", "error_msg"}` 之内（所以没有 `usage`）；会话里那三段的 `error_msg.code` 分别是 `film.vendor.balance`、`common.failed_generic`（段）与 `film.vendor.rejected`（尝试）；`/render/tasks` 里迟到那条的 `id` 以 `P.task_key("cgt-doubao-seedance-0001")` 结尾；合成那条 `error.code == "tts.vendor.rejected"`、`step is None`。
6. 反向对照：`GET /admin/service`（管理员）里 `P.find_vendor_words(...)` 非空，`film.tiers` 每行有 `vendor_label`；同一接口 alice 得 403（普通用户拿不到管理员提示的数据）。`/render/tasks` 每行的 `tier` 是中性 id（在 `{t for t, _, _ in tiers.TIERS} | {None}` 里）。
7. **路由清单**：

   ```python
   COVERED = {…上面调过的每条路由的路径模板…}
   EXEMPT = {   # 不扫的理由写在后面：二进制、流式、或响应整体是用户内容且不含服务端生成的错误文字
       "/novels/{nid}/chapters/{cid}/versions/{vid}/render/files/{path:path}": "二进制文件",
       "/novels/{nid}/chapters/{cid}/versions/{vid}/render/export.zip": "二进制文件",
       …（助手的流式接口、关键帧与风格图的上传下载、记忆与大纲的增删改、认证的登录注册等，逐条写理由）
   }
   for r in app_mod.app.routes:
       path = getattr(r, "path", "")
       if not path or path.startswith("/admin") or path in ("/docs", "/redoc", "/docs/oauth2-redirect"):
           continue
       assert path in COVERED or path in EXEMPT, f"新接口 {path} 没有登记：加进守卫的调用，或写明豁免理由"
   assert COVERED <= SEEN_PATHS, "COVERED 里的每一条都真的调过"
   ```

   `SEEN_PATHS` 由 `clean` 的调用方传入路径模板累积（给 `clean` 加一个 `route` 参数）。豁免名单要逐条人工判断：**凡是会返回出片会话视图、任务、错误消息的接口都不能豁免**。

运行：`cd backend && .venv/bin/python tests/server/test_vendor_guard.py`
预期：`ALL PASS`。

变异验证：临时把 `app.py` 里任意一处 `_film_view(s)` 改回 `_render_call(render_session.view, s)`，重跑，预期失败并指出是哪个接口、哪个词或哪个键；改回去，重跑通过。

- [ ] **Step 4: 全部守卫再跑一遍**

运行：`cd backend && for t in tests/server/test_vendor_guard.py tests/server/test_public.py tests/server/test_messages.py tests/server/test_i18n_scan.py; do .venv/bin/python $t || echo FAIL $t; done`
预期：没有 `FAIL`。

运行：`cd frontend && npm test && npm run build && node tests/admin-bundle.check.mjs && node tests/vendor-bundle.check.mjs`
预期：全部通过。

---

### Task 11: 全量验收

**Files:** 无（只跑命令；发现问题回到对应 Task 的范围内修）。

- [ ] **Step 1: 后端全套**

运行：`cd backend; for t in tests/pipeline/test_*.py tests/server/test_*.py tests/render/test_*.py tests/assistant/test_*.py; do .venv/bin/python $t || echo FAIL $t; done`
预期：没有 `FAIL`。

- [ ] **Step 2: 前端全套**

运行：`cd frontend && npm test`
预期：通过，每个测试文件 `ALL PASS`（`film.test` 卡住时按全局约束里的办法单独重跑）。

运行：`cd frontend && npm run lint 2>&1 | tail -3`
预期：0 error，恰好 5 warnings。

运行：`cd frontend && npm run build && node tests/admin-bundle.check.mjs && node tests/vendor-bundle.check.mjs`
预期：都 `ALL PASS`。

- [ ] **Step 3: 静态复核**

运行：`cd backend && .venv/bin/python -m server.messages --write && git diff --stat server/messages_codes.json`
预期：没有差异（登记表与导出文件一致）。

运行：`cd frontend && grep -rnIiE "minimax|seedance|doubao|volc|deepseek|anthropic|claude|方舟|豆包|海螺|字节跳动" src --include="*.ts" --include="*.tsx" | grep -v "^src/components/admin/" | grep -v "^\S*:[0-9]*:\s*\(//\|/\?\*\)"`
预期：没有输出（非后台源码里除注释外不再有这些词；`types.ts` 的注释 Task 6 已清）。若 shell 对 `--include` 的通配符报「no matches found」，给两个 `--include` 的值加引号后重跑。

运行：`cd backend && grep -nE "render_session\.view" server/app.py`
预期：只有 `_film_view` 里的一处。

- [ ] **Step 4: 报告**

列出：改动的文件清单；每条验收命令的结果；偏离本计划或 spec 的地方及原因；spec §11 已知限制之外新发现的遗留问题。**不提交**——提交由协调者按全局约束里的规则做。需要用户在浏览器里目视确认的（协调者转达）：出片面板设置区的档位下拉与摘要一行（中英文）、换档后分辨率与声音模式是否跟着变、让一段因余额类原因失败后片段卡与任务面板上的原因文字、花钱确认框里的费率说明、配音面板标题、落地页 FAQ、渲染任务包页的档位名与下载的 Markdown 标题、后台概览的「出片线路」卡片；**以管理员登录**再看一遍出片面板的档位下拉与摘要、失败的片段卡、任务面板、配音面板标题——中性名后面应带括号里的厂商字样，退出后以普通用户登录不应再有；浏览器开发者工具的网络面板里，普通用户会话不应出现 `/admin/service` 请求。
