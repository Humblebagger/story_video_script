# 后端双语 子计划 1：基础设施 + 出片与视频厂商 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 出片（视频生成）这条链路上，后端给用户看的文字全部改为「代码 + 参数 + 中文兜底」的消息对象，前端按当前界面语言渲染；同时把消息登记、前端渲染、代码一致性校验、ast 扫描这套基础设施搭好，后面 4 个子计划照着用。

**Architecture:** 后端新增 `backend/server/messages.py` 集中登记代码与中文兜底模板，提供 `msg()`、带类型参数（`money`/`ref`/`vendor`/嵌套原因）、`UserError` mixin（`.of()` 构造带代码的异常、`str()` 不变）、`to_detail()`。视频厂商、出片会话、自由节点、runner 抛错与持久化都带上代码；会话里的段 / 尝试 / 自由节点新增单字段 `error_msg`，经 `set_error`/`copy_error` 统一写入。`app.py` 只改出片接口的调用点。前端新增 `i18n/serverMsg.ts` 的 `formatMsg`，文案放在 `zh.ts`/`en.ts` 顶层 `srv` 节点，出片相关显示处改用它。

**Tech Stack:** Python 3.12（ast 扫描）、httpx `MockTransport`（已有厂商测试）、React 19 + TypeScript、Vite SSR 构建跑前端测试。

**Spec:** `docs/specs/2026-11-13-backend-i18n-design.md`（3e731a7，已过 Opus 设计审查并修订）。本计划只做 spec §9 的子计划 1。本计划与 spec 冲突时以 spec 为准；spec 没写的细节见文末「实施裁定」。

---

## 全局约束（每个 Task 都必须遵守）

- 不读、不打印 `backend/.env`；密钥不进日志、报错、session.json、消息参数。
- 不调用任何付费厂商；不运行 `backend/render/smoke.py`、`backend/assistant/smoke.py`；不向运行中的 5173 / 8000 服务发请求。
- 测试绝不联网、不读真实 `.env`（厂商接口照现有测试用 `httpx.MockTransport` / 假厂商）。
- 不动 `docs/specs/2026-10-27-commercialization-design-contract.md`（未跟踪文件）。
- git：只 `git add` 具体文件，禁止 `git add -A` / `git commit -a` / `git add -N`；提交信息中文、描述性；不带任何 `Co-Authored-By` 或署名行；不 push。
- 每个 Task 结束时必须全部通过：
  - 后端（在 `backend/` 下）：
    `for t in tests/pipeline/test_*.py tests/server/test_*.py tests/render/test_*.py tests/assistant/test_*.py; do .venv/bin/python $t || break; done`
    每个脚本打印 `ALL PASS`。
  - 前端（在 `frontend/` 下）：`npm test` 退出码 0；`npm run lint` 0 error、warning 不多于基线 5 条；`npm run build` 成功。
  - 已知既有问题：`frontend/tests/film.test.tsx` 偶发 CPU 自旋卡死（与本计划无关）。遇到时单独重跑判定：
    `npx vite build --ssr tests/film.test.tsx --outDir /tmp/i18n-film --logLevel error && timeout 60 node /tmp/i18n-film/film.test.js`，
    通过即可；临时输出不要留在仓库里。
- 中文兜底文字尽量与现在一字不差（模板 + 参数渲染出来要和原来的字符串相同），这样现有断言中文的测试大多不用改。不得不变的地方见各 Task 的「文字变化」。

## 范围边界（本子计划之外保持字符串兜底）

- **本子计划改**：
  - `backend/server/messages.py`（新）、`backend/server/messages_codes.json`（生成）；
  - `backend/render/providers/base.py`、`fake.py`、`seedance.py`、`minimax.py`，以及 `providers/__init__.py` 里视频厂商的部分；
  - `backend/render/session.py`（出片部分）、`free.py`、`runner.py`、`compose.py`（`FreeInvalid` 与内部 ValueError）；
  - `backend/server/app.py` 里出片接口：`_render_ctx`、`_render_call`、`render_session_post/get/patch`、`_film_quote`、`_film_run`、`render_clip_*`、`render_run_all`、`_free_ctx`、`render_free_*`、`render_file`；
  - 前端：`i18n/serverMsg.ts`（新）、`i18n/core.ts`、`zh.ts`/`en.ts` 的 `srv` 节点、`api.ts`、`types.ts`、`film.ts`、`useFilm.ts`、`FilmPanel.tsx`、`NodeCards.tsx`、`NodeGraph.tsx`、`common/MoneyConfirm.tsx`。
- **不改（后续子计划）**：
  - 子计划 2：合成（`session.py` 里 `begin_compose`、`compose_progress`、`compose_done`、`compose_failed`、`_fail_interrupted_compose`、`COMPOSE_INTERRUPTED`、合成相关的 `Conflict`/`BudgetExceeded`）、mix、voice、TTS 厂商（含 `providers/__init__.py` 的 `get_tts` 与 TTS 的 `rate_note`）、export、`_tts`、`render_voices*`、`render_compose*`、`render_export`。
  - 子计划 3：账号、小说、管理。
  - 子计划 4：验证门（`_render_gate`、`_gate_status` 的 message）、转换任务、助手。
  - 这些位置若被本子计划的扫描文件覆盖，行尾加 `# i18n: todo(2)`（或对应子计划号）豁免。
- 关键帧（`render/keyframes.py`、`/render/keyframes`）不在 spec 子计划 1 清单里，保持原样。

## 文件结构

| 文件 | 职责 |
|---|---|
| `backend/server/messages.py`（新） | 代码登记表（代码 → 中文兜底模板，参数名取自模板占位符）；`msg`、`money`、`ref`、`vendor`、`compact`、`render_zh`、`UserError`、`cause_of`、`to_detail`；`python -m server.messages --write` 导出 JSON |
| `backend/server/messages_codes.json`（生成，入库） | `{code: {"params": [...], "zh": "..."}}`，前端校验读它 |
| `backend/tests/server/test_messages.py`（新） | 登记规则、渲染、`UserError`、`to_detail`、JSON 最新 |
| `backend/tests/server/test_i18n_scan.py`（新） | ast 扫描：本子计划模块里，错误出口不得出现中文字面量 |
| `frontend/src/i18n/serverMsg.ts`（新） | `formatMsg`、`errValue`、`itemError`、类型 |
| `frontend/tests/server-msg.test.ts`（新） | `formatMsg` 单测 |
| `frontend/tests/srv-codes.test.ts`（新） | 后端代码清单 ↔ `zh.srv` / `en.srv` 键与参数 |

---

### Task 1: 后端消息登记与异常基础设施

**Files:**
- Create: `backend/server/messages.py`
- Create: `backend/server/messages_codes.json`（由命令生成）
- Create: `backend/tests/server/test_messages.py`
- Create: `backend/tests/server/test_i18n_scan.py`

本 Task 不改任何现有行为，只登记 `common.unknown`。

- [ ] **Step 1: 写失败的测试 `backend/tests/server/test_messages.py`**

```python
#!/usr/bin/env python3
"""后端消息登记：代码、参数、中文兜底、带类型参数、异常 mixin、to_detail。用法: python3 tests/server/test_messages.py"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from server import messages as M  # noqa: E402


def must_raise(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc as e:
        return e
    raise AssertionError(f"应抛 {exc.__name__}")


class Boom(M.UserError, ValueError):
    pass


class Conf(M.UserError, ValueError):
    def __init__(self, message, expected_cny=None):
        super().__init__(message)
        self.expected_cny = expected_cny


def main() -> int:
    reg = M._REG.copy()
    try:
        # 1. 登记：参数取自模板占位符；重复、叶子与前缀冲突都拒绝
        M.register("t.a.leaf", "第 {n} 段：{why}")
        assert M._REG["t.a.leaf"] == (("n", "why"), "第 {n} 段：{why}")
        must_raise(ValueError, M.register, "t.a.leaf", "x")
        must_raise(ValueError, M.register, "t.a", "x")            # t.a 是 t.a.leaf 的前缀
        must_raise(ValueError, M.register, "t.a.leaf.more", "x")  # t.a.leaf 已是叶子

        # 2. msg：未登记、缺参数、多参数都抛；渲染中文兜底
        must_raise(KeyError, M.msg, "t.nope")
        must_raise(ValueError, M.msg, "t.a.leaf", n=1)
        must_raise(ValueError, M.msg, "t.a.leaf", n=1, why="x", extra=2)
        m = M.msg("t.a.leaf", n=3, why="断网")
        assert m == {"code": "t.a.leaf", "params": {"n": 3, "why": "断网"}, "message": "第 3 段：断网"}

        # 3. 带类型的值：金额、代码引用、厂商原文、列表、嵌套原因
        M.register("t.money", "本次约 {amount}")
        assert M.msg("t.money", amount=M.money(12.3))["message"] == "本次约 ¥12.30"
        M.register("t.place", "控制台")
        M.register("t.go", "请到{where}核对")
        assert M.msg("t.go", where=M.ref("t.place"))["message"] == "请到控制台核对"
        must_raise(KeyError, M.ref, "t.nope")
        v = M.vendor("x" * 500)
        assert v == {"t": "vendor", "text": "x" * 300}
        M.register("t.list", "可选：{options}")
        assert M.msg("t.list", options=["720p", "1080p"])["message"] == "可选：720p、1080p"
        inner = M.msg("t.money", amount=M.money(1))
        outer = M.msg("t.a.leaf", n=1, why=M.compact(inner))
        assert outer["params"]["why"] == {"code": "t.money", "params": {"amount": {"t": "money", "cny": 1.0}}}
        assert outer["message"] == "第 1 段：本次约 ¥1.00"

        # 4. UserError：.of() 构造带代码的异常，str() 是中文兜底，额外位置参数照传
        e = Boom.of("t.a.leaf", n=2, why="限流")
        assert isinstance(e, ValueError) and str(e) == "第 2 段：限流" and e.code == "t.a.leaf"
        assert e.as_msg() == {"code": "t.a.leaf", "params": {"n": 2, "why": "限流"}, "message": "第 2 段：限流"}
        c = Conf.of("t.money", 7.5, amount=M.money(7.5))
        assert c.expected_cny == 7.5 and str(c) == "本次约 ¥7.50"
        assert Boom("旧写法").as_msg() is None                    # 没带代码

        # 5. cause_of：带代码 → 紧凑消息；不带 → 厂商原文
        assert M.cause_of(e) == {"code": "t.a.leaf", "params": {"n": 2, "why": "限流"}}
        assert M.cause_of(RuntimeError("raw")) == {"t": "vendor", "text": "raw"}

        # 6. to_detail：带代码 → 消息对象（附加字段同层）；不带代码 → 字符串（与现在一致）
        assert M.to_detail(e) == e.as_msg()
        assert M.to_detail(c, expected_cny=7.5)["expected_cny"] == 7.5
        assert M.to_detail(Boom("旧写法")) == "旧写法"
        assert M.to_detail(Conf("旧写法"), expected_cny=None) == {"message": "旧写法", "expected_cny": None}

        # 7. common.unknown 的模板只是 {message}
        assert M._REG["common.unknown"][1] == "{message}"
    finally:
        M._REG.clear()
        M._REG.update(reg)

    # 8. 导出的 JSON 与登记表一致（改了登记要跑 python -m server.messages --write）
    on_disk = json.loads(M.CODES_FILE.read_text(encoding="utf-8"))
    assert on_disk == M.dump_codes(), "messages_codes.json 过期：cd backend && .venv/bin/python -m server.messages --write"

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 运行，确认失败**

Run: `cd backend && .venv/bin/python tests/server/test_messages.py`
Expected: `ModuleNotFoundError: No module named 'server.messages'`

- [ ] **Step 3: 实现 `backend/server/messages.py`**

```python
"""后端对用户文字的消息对象（设计 docs/specs/2026-11-13-backend-i18n-design.md §3–§5）。

每个代码登记一条中文兜底模板，参数名取自模板里的 {name}。后端返回、持久化的都是
{code, params, message}：前端按代码与当前语言渲染（文案在 frontend/src/i18n 的 srv 节点），
message 是中文兜底，给旧前端、日志与测试阅读。登记表导出到 messages_codes.json，前端测试核对。

参数值允许：字符串、数字、列表、嵌套消息 {code, params}（内层原因）、
金额 {"t":"money","cny":…}、代码引用 {"t":"ref","code":…}、厂商原文 {"t":"vendor","text":…}。
"""
import json
import re
import sys
from pathlib import Path
from typing import Any, Optional

CODES_FILE = Path(__file__).with_name("messages_codes.json")
VENDOR_MAX = 300
_PH = re.compile(r"\{(\w+)\}")
_REG: dict = {}          # code → (参数名元组, 中文模板)


def register(code: str, zh: str) -> None:
    if code in _REG:
        raise ValueError(f"重复登记：{code}")  # i18n: internal
    for other in _REG:
        if other.startswith(code + ".") or code.startswith(other + "."):
            raise ValueError(f"{code} 与 {other} 一个是另一个的前缀")  # i18n: internal
    _REG[code] = (tuple(dict.fromkeys(_PH.findall(zh))), zh)


def money(cny: float) -> dict:
    return {"t": "money", "cny": round(float(cny), 2)}


def ref(code: str) -> dict:
    if code not in _REG:
        raise KeyError(code)
    return {"t": "ref", "code": code}


def vendor(text: Any) -> dict:
    """厂商或系统原文：原样显示、不翻译。调用方先脱敏（如 minimax.scrub），这里只截断。"""
    return {"t": "vendor", "text": str(text)[:VENDOR_MAX]}


def compact(m: dict) -> dict:
    """消息对象 → 只留 code、params（嵌进别的消息当原因时用）。"""
    return {"code": m["code"], "params": m.get("params") or {}}


def _zh_value(v: Any) -> str:
    if isinstance(v, list):
        return "、".join(_zh_value(x) for x in v)
    if isinstance(v, dict):
        t = v.get("t")
        if t == "money":
            return f"¥{float(v['cny']):.2f}"
        if t == "ref":
            return _REG[v["code"]][1]
        if t == "vendor":
            return str(v.get("text", ""))
        if "code" in v:
            return v.get("message") or render_zh(v["code"], v.get("params") or {})
        return ""
    return "" if v is None else str(v)


def render_zh(code: str, params: dict) -> str:
    tpl = _REG[code][1]
    return _PH.sub(lambda m: _zh_value(params[m.group(1)]) if m.group(1) in params else m.group(0), tpl)


def msg(code: str, **params) -> dict:
    if code not in _REG:
        raise KeyError(code)
    want = set(_REG[code][0])
    if set(params) != want:
        raise ValueError(f"{code} 的参数应为 {sorted(want)}，实际 {sorted(params)}")  # i18n: internal
    return {"code": code, "params": params, "message": render_zh(code, params)}


class UserError:
    """混入现有异常类：带代码与参数，str() 仍是中文兜底（原有 except 链、日志、测试不受影响）。"""
    code: Optional[str] = None
    params: dict = {}

    @classmethod
    def of(cls, code: str, *args, **params):
        m = msg(code, **params)
        e = cls(m["message"], *args)
        e.code, e.params = code, m["params"]
        return e

    def as_msg(self) -> Optional[dict]:
        if not self.code:
            return None
        text = self.args[0] if self.args else str(self)
        return {"code": self.code, "params": self.params, "message": text}


def cause_of(e: BaseException) -> dict:
    """异常 → 可嵌进外层消息的原因：带代码的给紧凑消息，其它给原文（截断）。"""
    m = e.as_msg() if isinstance(e, UserError) else None
    return compact(m) if m else vendor(e.args[0] if isinstance(e, KeyError) and e.args else e)


def to_detail(e: BaseException, **extra) -> Any:
    """HTTPException 的 detail：带代码 → 消息对象（附加字段同层）；不带代码 → 与现在一致。"""
    m = e.as_msg() if isinstance(e, UserError) else None
    if m:
        return {**m, **extra}
    text = e.args[0] if isinstance(e, KeyError) and e.args else str(e)
    return {"message": text, **extra} if extra else text


def dump_codes() -> dict:
    return {c: {"params": list(p), "zh": z} for c, (p, z) in sorted(_REG.items())}


# ---------- 登记表（按域分组；改动后运行 python -m server.messages --write） ----------

register("common.unknown", "{message}")


if __name__ == "__main__":
    if "--write" in sys.argv:
        CODES_FILE.write_text(json.dumps(dump_codes(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {CODES_FILE}")
```

后续 Task 往「登记表」段落追加 `register(...)`。登记必须在模块导入时完成（后端各模块 `from server.messages import ...` 时登记表已齐全）。

- [ ] **Step 4: 生成 JSON 并跑测试**

Run:
```bash
cd backend && .venv/bin/python -m server.messages --write && .venv/bin/python tests/server/test_messages.py
```
Expected: `ALL PASS`

- [ ] **Step 5: 写 ast 扫描 `backend/tests/server/test_i18n_scan.py`**

扫描规则（spec §8）：在「已改造模块」里，下列「错误出口」不得出现中文字面量（含 f-string、拼接、引用了含中文的模块级常量）；行尾带 `# i18n: internal`、`# i18n: llm`、`# i18n: todo(N)` 的语句豁免（检查该语句起止行的任一行）。

- 错误出口：
  - 调用名（`Name` 或 `Attribute` 的末段）匹配 `(Error|Exception|Submit|Conflict|NotFound|Corrupt|Exceeded|Invalid|Stale)$`，或是 `HTTPException`、`note_error`、`submit_failed`、`download_failed`、`TaskState` 的调用：检查全部实参；
  - 任意调用里的关键字参数 `error`、`detail`、`message`、`step`；
  - 赋值目标是下标 `x["error"]`（含元组解包里对应位置）。

```python
#!/usr/bin/env python3
"""已改造模块里，给用户的错误出口不得再写中文字面量（spec §8）。用法: python3 tests/server/test_i18n_scan.py

逐子计划把模块加进 MODULES；app.py 只扫列出的函数。豁免：行尾 # i18n: internal / llm / todo(N)。
"""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CJK = re.compile(r"[\u4e00-\u9fff]")
MARK = re.compile(r"#\s*i18n:\s*(internal|llm|todo\(\d\))")
SINK_NAME = re.compile(r"(Error|Exception|Submit|Conflict|NotFound|Corrupt|Exceeded|Invalid|Stale)$")
SINK_CALLS = {"HTTPException", "note_error", "submit_failed", "download_failed", "TaskState"}
SINK_KW = {"error", "detail", "message", "step"}

# 子计划 1 清零的模块；值为 None 表示全文件，集合表示只扫这些函数
MODULES: dict = {}


def _cjk_consts(tree: ast.Module) -> set:
    out = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(n, ast.Constant) and isinstance(n.value, str)
                                                and CJK.search(n.value) for n in ast.walk(node.value)):
            out |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    return out


def _has_cjk(node, consts: set) -> bool:
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and CJK.search(n.value):
            return True
        if isinstance(n, ast.Name) and n.id in consts:
            return True
    return False


def _name(func) -> str:
    return func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""


def _sinks(node):
    """(子节点, 描述) 迭代：只产出错误出口里的值。"""
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            name = _name(n.func)
            if name in SINK_CALLS or SINK_NAME.search(name):
                for a in n.args:
                    yield a, name
                for k in n.keywords:
                    yield k.value, f"{name}({k.arg}=)"
            else:
                for k in n.keywords:
                    if k.arg in SINK_KW:
                        yield k.value, f"{name}({k.arg}=)"
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                pairs = (zip(t.elts, n.value.elts) if isinstance(t, ast.Tuple) and isinstance(n.value, ast.Tuple)
                         else [(t, n.value)])
                for tgt, val in pairs:
                    if (isinstance(tgt, ast.Subscript) and isinstance(tgt.slice, ast.Constant)
                            and tgt.slice.value == "error"):
                        yield val, '["error"] ='


def scan(rel: str, funcs) -> list:
    path = ROOT / rel
    src = path.read_text(encoding="utf-8")
    lines = src.splitlines()
    tree = ast.parse(src)
    consts = _cjk_consts(tree)
    roots = [tree] if funcs is None else [n for n in ast.walk(tree)
                                          if isinstance(n, ast.FunctionDef) and n.name in funcs]
    hits = []
    for root in roots:
        for val, where in _sinks(root):
            if not _has_cjk(val, consts):
                continue
            span = lines[val.lineno - 1:(val.end_lineno or val.lineno)]
            stmt = lines[val.lineno - 1]
            if any(MARK.search(x) for x in span) or MARK.search(stmt):
                continue
            hits.append(f"{rel}:{val.lineno} {where}: {stmt.strip()[:100]}")
    return sorted(set(hits))


def main() -> int:
    # 扫描器自检：能抓到四种写法，豁免注释有效
    probe = ROOT / "tests" / "server" / "_i18n_probe.py"
    probe.write_text('X = "中文"\n'
                     'def f(e):\n'
                     '    raise ValueError("中文")\n'
                     '    raise ValueError(f"中{e}")\n'
                     '    c["error"] = X\n'
                     '    a.update(error="错")\n'
                     '    raise ValueError("内部")  # i18n: internal\n', encoding="utf-8")
    try:
        got = scan("tests/server/_i18n_probe.py", None)
        assert len(got) == 4, got
    finally:
        probe.unlink()

    bad = []
    for rel, funcs in MODULES.items():
        bad += scan(rel, funcs)
    assert not bad, "这些错误出口还写着中文：\n" + "\n".join(bad)
    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Run: `cd backend && .venv/bin/python tests/server/test_i18n_scan.py` → `ALL PASS`（`MODULES` 还是空的，只跑自检）。

- [ ] **Step 6: 全量后端测试，提交**

```bash
cd backend && for t in tests/pipeline/test_*.py tests/server/test_*.py tests/render/test_*.py tests/assistant/test_*.py; do .venv/bin/python $t || break; done
cd .. && git add backend/server/messages.py backend/server/messages_codes.json backend/tests/server/test_messages.py backend/tests/server/test_i18n_scan.py
git commit -m "后端双语基础设施：新增消息登记模块（代码、中文兜底模板、金额 / 代码引用 / 厂商原文 / 嵌套原因参数、UserError 混入类、to_detail），导出代码清单 JSON；新增错误出口中文字面量的 ast 扫描测试"
```

---

### Task 2: 前端渲染与代码一致性校验

**Files:**
- Modify: `frontend/src/i18n/core.ts`（导出 `lookupKey`）
- Create: `frontend/src/i18n/serverMsg.ts`
- Modify: `frontend/src/i18n/zh.ts`、`frontend/src/i18n/en.ts`（顶层加 `srv` 节点）
- Create: `frontend/tests/server-msg.test.ts`、`frontend/tests/srv-codes.test.ts`
- Modify: `frontend/package.json`（`test` 脚本串加两条）

- [ ] **Step 1: 写失败的测试 `frontend/tests/server-msg.test.ts`**

```ts
/** 后端消息对象的渲染：字符串原样、代码按语言、带类型参数、嵌套原因、缺译回落。跑法：npm test */
import { formatMsg, itemError, errValue } from '../src/i18n/serverMsg'
import { ApiError } from '../src/api'

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }

// 1. 字符串 / 空值
must(formatMsg('原样') === '原样', '字符串原样')
must(formatMsg(null) === '' && formatMsg(undefined) === '', '空值为空串')

// 2. common.unknown 的模板是 {message}
const unk = { code: 'common.unknown', params: { message: 'raw' }, message: 'raw' }
must(formatMsg(unk, 'zh') === 'raw' && formatMsg(unk, 'en') === 'raw', 'common.unknown 原样')

// 3. 缺译：没有这个代码 → message → 代码名
must(formatMsg({ code: 'x.not.registered', message: '兜底' }, 'en') === '兜底', '缺译用 message')
must(formatMsg({ code: 'x.not.registered' }, 'en') === 'x.not.registered', '没有 message 用代码名')

// 4. 带类型参数与嵌套：用 common.unknown 的 {message} 占位验证
const wrap = (v: unknown) => ({ code: 'common.unknown', params: { message: v } })
must(formatMsg(wrap({ t: 'money', cny: 3 }) as never, 'en') === '¥3.00', '金额')
must(formatMsg(wrap({ t: 'vendor', text: 'HTTP 500' }) as never, 'en') === 'HTTP 500', '厂商原文')
must(formatMsg(wrap(['a', 'b']) as never, 'zh') === 'a、b', '列表中文用顿号')
must(formatMsg(wrap(['a', 'b']) as never, 'en') === 'a, b', '列表英文用逗号')
must(formatMsg(wrap({ code: 'common.unknown', params: { message: 'inner' } }) as never, 'en') === 'inner', '嵌套原因')

// 5. 旧数据：有 error_msg 按代码，没有就原样 error
must(itemError({ error: '旧中文', error_msg: null }) === '旧中文', '旧数据原样')
must(itemError({ error: '中文', error_msg: { code: 'common.unknown', params: { message: 'new' } } }, 'en') === 'new',
  '有 error_msg 按代码')

// 6. errValue：ApiError 取 detail（对象原样保留，渲染时再格式化），其它取 message
const api = new ApiError('m', 409, { code: 'common.unknown', params: { message: 'd' }, message: 'd' })
must(typeof errValue(api) === 'object', 'ApiError 保留 detail 对象')
must(errValue(new Error('plain')) === 'plain', '普通错误取 message')

console.log('\nALL PASS')
```

- [ ] **Step 2: 写失败的测试 `frontend/tests/srv-codes.test.ts`**

```ts
/** 后端代码清单（backend/server/messages_codes.json）↔ 前端 srv 文案：键齐全、无多余、占位符都是登记过的参数、
 *  中文文案与后端兜底一字不差。跑法：npm test（在 frontend/ 下运行） */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { zh } from '../src/i18n/zh'
import { en } from '../src/i18n/en'

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }
type Codes = Record<string, { params: string[]; zh: string }>
const codes = JSON.parse(readFileSync(resolve(process.cwd(), '../backend/server/messages_codes.json'), 'utf-8')) as Codes

const leaves = (node: unknown, prefix = ''): Record<string, string> => {
  const out: Record<string, string> = {}
  for (const [k, v] of Object.entries(node as Record<string, unknown>)) {
    const p = prefix ? `${prefix}.${k}` : k
    if (typeof v === 'string') out[p] = v
    else Object.assign(out, leaves(v, p))
  }
  return out
}
const zhSrv = leaves((zh as unknown as { srv: unknown }).srv)
const enSrv = leaves((en as unknown as { srv: unknown }).srv)
const holes = (s: string) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1])

for (const [code, { params, zh: zhText }] of Object.entries(codes)) {
  must(code in zhSrv, `zh 缺 srv.${code}`)
  must(code in enSrv, `en 缺 srv.${code}`)
  must(zhSrv[code] === zhText, `zh srv.${code} 与后端兜底不一致：${zhSrv[code]} ≠ ${zhText}`)
  for (const h of holes(enSrv[code])) must(params.includes(h), `en srv.${code} 的 {${h}} 不是登记过的参数`)
  for (const p of params) must(holes(enSrv[code]).includes(p), `en srv.${code} 漏了参数 {${p}}`)
}
for (const k of Object.keys(zhSrv)) must(k in codes, `zh 多余的 srv.${k}（后端没登记）`)
console.log(`\n${Object.keys(codes).length} codes`)
console.log('\nALL PASS')
```

把两条加进 `package.json` 的 `test` 脚本串（放在 `tests/graph-view.test.tsx` 那一条之后，同样的写法）：
```
&& vite build --ssr tests/server-msg.test.ts --outDir .ssrout --logLevel error && node .ssrout/server-msg.test.js && vite build --ssr tests/srv-codes.test.ts --outDir .ssrout --logLevel error && node .ssrout/srv-codes.test.js
```

Run: `cd frontend && npm test` → Expected: 构建失败，找不到 `../src/i18n/serverMsg`。

- [ ] **Step 3: `core.ts` 导出 `lookupKey`**

在 `translate` 之前加，`translate` 内部改用它：

```ts
/** 按点分路径取文案（不存在返回 undefined）；serverMsg 用它判断缺译 */
export function lookupKey(locale: Locale, key: string): string | undefined {
  let node: unknown = PACKS[locale]
  for (const part of key.split('.')) node = (node as Record<string, unknown> | undefined)?.[part]
  return typeof node === 'string' ? node : undefined
}
```
`translate` 里的 `lookup(l)` 换成 `lookupKey(l, key)`，行为不变。

- [ ] **Step 4: 实现 `frontend/src/i18n/serverMsg.ts`**

```ts
/** 后端消息对象的渲染（设计 docs/specs/2026-11-13-backend-i18n-design.md §3、§6）。
 *  文案在 zh.ts / en.ts 的 srv 节点，路径与后端代码一致；后端代码清单由 tests/srv-codes.test.ts 核对。
 *  缺译回落：当前语言 → 中文 → message → 代码名。 */
import { currentLocale, lookupKey, translate } from './core'
import type { Locale } from './core'

export interface ServerMsg { code: string; params?: Record<string, unknown>; message?: string }
export type MsgLike = string | ServerMsg | null | undefined

const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v)
export const isServerMsg = (v: unknown): v is ServerMsg => isObj(v) && typeof v.code === 'string' && !('t' in v)

function value(v: unknown, l: Locale): string {
  if (v === null || v === undefined) return ''
  if (Array.isArray(v)) return v.map((x) => value(x, l)).join(translate(l, 'common.listSep'))
  if (isObj(v)) {
    if (v.t === 'money') return `¥${Number(v.cny).toFixed(2)}`
    if (v.t === 'ref') return render({ code: String(v.code) }, l)
    if (v.t === 'vendor') return String(v.text ?? '')
    if (isServerMsg(v)) return render(v, l)
    return ''
  }
  return String(v)
}

function render(m: ServerMsg, l: Locale): string {
  const key = `srv.${m.code}`
  const tpl = lookupKey(l, key) ?? lookupKey('zh', key)
  if (tpl === undefined) return m.message ?? m.code
  const ps = m.params ?? {}
  return tpl.replace(/\{(\w+)\}/g, (all, k: string) => (k in ps ? value(ps[k], l) : all))
}

/** 字符串原样；消息对象按语言渲染；带 message 的旧对象取 message */
export function formatMsg(m: unknown, locale: Locale = currentLocale()): string {
  if (m === null || m === undefined) return ''
  if (typeof m === 'string') return m
  if (isServerMsg(m)) return render(m, locale)
  if (isObj(m) && typeof m.message === 'string') return m.message
  return String(m)
}

/** 异常 → 存进状态的错误值：接口错误保留原始 detail（渲染时再按语言格式化），其它取 message */
export function errValue(e: unknown): MsgLike {
  if (isObj(e) && 'detail' in e && (e as { name?: unknown }).name === 'ApiError') {
    const d = (e as { detail: unknown }).detail
    if (typeof d === 'string' || isServerMsg(d)) return d
    if (isObj(d) && typeof d.message === 'string') return d.message
    return (e as unknown as Error).message
  }
  return e instanceof Error ? e.message : String(e)
}

/** 会话里的段、尝试、自由节点：有 error_msg 按代码，没有（旧数据、未改造的模块）原样显示 error */
export function itemError(x: { error?: string | null; error_msg?: ServerMsg | null }, locale?: Locale): string {
  return x.error_msg ? formatMsg(x.error_msg, locale) : (x.error ?? '')
}
```

- [ ] **Step 5: `zh.ts`/`en.ts` 顶层加 `srv` 节点**

两个文件末尾（`resolve` 节点之后）加：
```ts
  srv: {
    common: { unknown: '{message}' },
  },
```
后续 Task 每登记一个后端代码，就在两边 `srv` 下按点分路径加一条：zh 与后端模板一字不差；en 为自然的英文，占位符相同。

- [ ] **Step 6: 跑前端检查，提交**

```bash
cd frontend && npm test && npm run lint && npm run build
cd .. && git add frontend/src/i18n/core.ts frontend/src/i18n/serverMsg.ts frontend/src/i18n/zh.ts frontend/src/i18n/en.ts frontend/tests/server-msg.test.ts frontend/tests/srv-codes.test.ts frontend/package.json
git commit -m "前端双语渲染基础：新增 formatMsg（代码按界面语言渲染，金额、代码引用、厂商原文、列表、嵌套原因，缺译回落中文、兜底文字、代码名）、errValue、itemError；中英语言包加 srv 节点；新增后端代码清单与前端文案一致性测试"
```

---

### Task 3: 视频厂商层（基类、假厂商、Seedance、MiniMax、注册表）

**Files:**
- Modify: `backend/render/providers/base.py`、`fake.py`、`seedance.py`、`minimax.py`、`__init__.py`
- Modify: `backend/server/messages.py`（登记）、`backend/server/messages_codes.json`（重新生成）
- Modify: `frontend/src/i18n/zh.ts`、`en.ts`（`srv.film.*`、`srv.console.*`、`srv.rate.*`）
- Modify: `backend/tests/server/test_i18n_scan.py`（`MODULES` 加入厂商文件）
- Test: `backend/tests/render/test_providers.py`、`test_seedance.py`、`test_minimax.py`

- [ ] **Step 1: 写失败的测试（追加，不删现有断言）**

现有断言中文子串的用例保留（中文兜底不变，它们照样通过）。新增代码断言：

`test_minimax.py` 末尾新增一节「10. 错误带代码」：
- 402 → `ProviderError`，`e.code == "film.minimax.insufficient_balance"`；401 → `film.minimax.invalid_key`；提交时 422 + 1026 → `film.minimax.moderated`；
- 任务 failed 且 error.code 1026 的 `poll()` → `st.error_msg["code"] == "film.minimax.moderated"`，`st.error` 仍为原中文；
- 任务 cancelled → `st.error_msg["code"] == "film.provider.task_cancelled"`；
- 未知业务错误 → `film.provider.rejected`，`params["detail"]["t"] == "vendor"`，且回显的密钥不在 `params` 的任何字符串里；
- 断线 → `AmbiguousSubmit`，`code == "film.provider.submit_cut"`；
- 坏 data URI 的参考图 → `film.minimax.corrupt_image`，`params["label"] == {"code": "film.minimax.label_ref", "params": {"id": "<asset_id>"}}`；
- 地址过期且重查失败 → `film.minimax.url_expired`；
- `MiniMax.rate_note == {"code": "rate.minimax", "params": {}}`、`MiniMax.console_name == "console.minimax"`。

`test_seedance.py` 新增：没配密钥 → `film.ark.no_key`；429 → `TransientError` 且 `code == "film.ark.throttled"`；任务 expired → `st.error_msg["code"] == "film.ark.task_expired"`；`rate_note` 与 `console_name` 同上（`rate.ark`、`console.ark`）。

`test_providers.py` 新增：`get_video("nope")` 抛 `KeyError` 且 `e.code == "film.provider.unknown"`、`e.args[0] == "未知的视频厂商：nope"`；`FakeVideo().rate_note["code"] == "rate.fake"`。

Run: `cd backend && .venv/bin/python tests/render/test_minimax.py` → Expected: `AttributeError: 'ProviderError' object has no attribute 'code'`（或断言失败）。

- [ ] **Step 2: 基类 `base.py`**

```python
from server.messages import UserError

class ProviderError(UserError, Exception): ...
class TransientError(UserError, Exception): ...
class AmbiguousSubmit(UserError, Exception): ...
```
（docstring 不变）`TaskState` 加字段：
```python
    error: Optional[str] = None     # 中文兜底（含厂商原文）
    error_msg: Optional[dict] = None  # {code, params}：前端按代码渲染
```
`VideoProvider` 协议里 `rate_note: str` 改为 `rate_note: dict   # 消息对象 {code, params}`，加 `console_name: str   # 代码，如 console.ark`。

- [ ] **Step 3: 登记代码（追加到 `messages.py` 登记表）**

模板必须与现在的字符串一字不差（`{x}` 处原来是什么值，现在就传什么参数）。`options` 一律传字符串列表（中文兜底用「、」连接，与原来的 `'、'.join(...)` 相同）。

```python
# 控制台名与费率说明（厂商属性，前端按代码渲染）
register("console.generic", "厂商控制台")
register("console.ark", "方舟控制台")
register("console.minimax", "MiniMax 开放平台")
register("rate.fake", "假厂商：不联网、不花钱，金额只用于演示")
register("rate.ark", "2026-10 方舟官方刊例价（2.0 为 46、fast 为 37、mini 为 23 元/百万 token，"
                     "token ≈ 秒 × 宽 × 高 × 24 / 1024），未经账单核对")
register("rate.minimax", "2026-11 MiniMax 官方刊例价（H3 768P 0.50、2K 0.80 元/秒，Highspeed、Lite 见档位；"
                         "每段前 5 张参考图免费，超出另计），未经账单核对")
# 厂商通用
register("film.provider.unknown", "未知的视频厂商：{name}")
register("film.provider.failed", "厂商返回失败")
register("film.provider.generation_failed", "生成失败")
register("film.provider.task_cancelled", "任务已取消")
register("film.provider.rejected", "{detail}")
register("film.provider.http_rejected", "HTTP {status}：{detail}")
register("film.provider.submit_cut", "提交时连接中断：{kind}")
register("film.provider.download_retry", "下载暂时失败（HTTP {status}）")
register("film.provider.download_failed", "下载失败（HTTP {status}）")
register("film.provider.download_connect", "下载连接失败：{kind}")
# 假厂商
register("film.fake.unknown_model", "未知的档位：{model}")
register("film.fake.throttled", "假的限流")
register("film.fake.no_task", "任务不存在：{id}")
# 方舟 Seedance
register("film.ark.no_key", "没有配置方舟密钥：在 backend/.env 写 ARK_API_KEY=…")
register("film.ark.unknown_model", "未知的 Seedance 档位：{model}")
register("film.ark.connect_failed", "连接方舟失败：{kind}")
register("film.ark.throttled", "方舟限流（HTTP 429）")
register("film.ark.http_ambiguous", "方舟返回 HTTP {status}")
register("film.ark.unavailable", "方舟暂时不可用（HTTP {status}）")
register("film.ark.not_json", "方舟返回的不是 JSON")
register("film.ark.no_task_id", "方舟受理了请求却没有返回任务 id")
register("film.ark.task_expired", "任务超时")
register("film.ark.no_result_url", "方舟没有返回结果地址")
register("film.ark.download_failed", "下载失败（HTTP {status}）：结果地址 24 小时内有效")
# MiniMax
register("film.minimax.insufficient_balance", "MiniMax 账户余额不足（1008），充值后重新出这一段")
register("film.minimax.invalid_key", "MiniMax 密钥无效（1004），检查 MINIMAX_API_KEY")
register("film.minimax.moderated", "内容被 MiniMax 审核拦下（1026）：改写这一段的画面描述或换参考图后重试")
register("film.minimax.url_expired", "结果地址已过期且重新查询失败；任务只能在 7 天内查询")
register("film.minimax.label_first", "首帧")
register("film.minimax.label_ref", "参考图 {id}")
register("film.minimax.bad_image", "{label} 不是可用的图片地址")
register("film.minimax.unsupported_format", "{label} 的格式 {mime} MiniMax 不支持（只收 JPG、PNG、WEBP、HEIC、HEIF）")
register("film.minimax.corrupt_image", "{label} 的图片数据损坏")
register("film.minimax.image_too_big", "{label} 有 {mb}MB，超过 MiniMax 单张 30MB 上限")
register("film.minimax.no_key", "没有配置 MiniMax 密钥：在 backend/.env 写 MINIMAX_API_KEY=…")
register("film.minimax.unknown_model", "未知的 MiniMax 档位：{model}")
register("film.minimax.connect_failed", "连接 MiniMax 失败：{kind}")
register("film.minimax.throttled", "MiniMax 限流或过载（HTTP {status}）")
register("film.minimax.http_ambiguous", "MiniMax 返回 HTTP {status}")
register("film.minimax.unavailable", "MiniMax 暂时不可用（HTTP {status}）")
register("film.minimax.not_json", "MiniMax 返回的不是 JSON")
register("film.minimax.bad_resolution", "{model} 不支持 {resolution}，可选：{options}")
register("film.minimax.prompt_too_long", "提示词超出 MiniMax 上限 {max} 字（当前 {len} 字）")
register("film.minimax.lite_needs_ratio", "MiniMax H3 Lite 的参考生视频必须明确画幅，不支持 adaptive")
register("film.minimax.bad_ratio", "MiniMax 不支持画幅 {ratio}，可选：{options}")
register("film.minimax.request_too_big", "请求体约 {mb}MB，超过 MiniMax 上限：减少参考图或换小一些的图")
register("film.minimax.no_task_id", "MiniMax 受理了请求却没有返回任务 id")
register("film.minimax.no_result_url", "MiniMax 没有返回结果地址")
```
（实现时逐条对照厂商文件的现有字符串核对；若有本表漏掉的出口，按同样规则补登记——ast 扫描会报出来。）

- [ ] **Step 4: 改厂商文件**

规则：
- `raise ProviderError(f"…")` → `raise ProviderError.of("<code>", <参数>)`；`TransientError`、`AmbiguousSubmit` 同理。
- 带格式化的数字照原格式先转成字符串再传，如 `mb=f"{len(raw) / 1048576:.1f}"`、`status=r.status_code`。
- `{kind}` 传 `type(e).__name__`。
- 厂商原文一律 `vendor(scrub(text, self._key))`（MiniMax）或 `vendor(text)`（Seedance：原样，不含密钥）。
- 类属性：
  ```python
  console_name = "console.minimax"        # Seedance: "console.ark"
  rate_note = {"code": "rate.minimax", "params": {}}   # Seedance: rate.ark；Fake: rate.fake
  ```
  `rate_note` 用 `compact(msg("rate.x"))` 也可以，但类属性在导入时求值，登记必须先完成——`messages.py` 的登记在其模块导入时完成，厂商模块 `from server.messages import ...` 之后即可用；为免顺序问题，直接写字面量 dict，测试校验它是登记过的代码。
- **MiniMax**：
  - 删除 `MSG` 与 `EXPIRED_MSG` 常量；新增
    ```python
    _KNOWN = {"1008": "film.minimax.insufficient_balance", "1004": "film.minimax.invalid_key",
              "1026": "film.minimax.moderated"}
    ```
  - `_reject`：
    ```python
    def _reject(code, msg_text, status=None, body: str = "", secret: str = "") -> ProviderError:
        key = code if code in _KNOWN else _HTTP_CODE.get(status)
        if key in _KNOWN:
            return ProviderError.of(_KNOWN[key])
        text = "：".join(str(x) for x in (code, msg_text) if x)
        if text:
            return ProviderError.of("film.provider.rejected", detail=vendor(scrub(text, secret)))
        return ProviderError.of("film.provider.http_rejected", status=status, detail=vendor(scrub(body, secret)))
    ```
    （参数名 `msg` 改为 `msg_text`，避免遮住 `server.messages.msg`。）中文兜底：`rejected` 渲染为原文，`http_rejected` 为 `HTTP {status}：{原文}`，与原来一致。
  - `_check_image(uri, label)` 的 `label` 改为嵌套消息：调用处传 `compact(msg("film.minimax.label_first"))` 或 `compact(msg("film.minimax.label_ref", id=ref.asset_id))`。
  - `poll()` 失败分支同时填 `error` 与 `error_msg`：
    ```python
    if raw == "cancelled":
        m = msg("film.provider.task_cancelled")
    else:
        err = t.get("error") if isinstance(t.get("error"), dict) else {}
        code = _code(err.get("code") or err.get("type"), err.get("message"))
        text = scrub("：".join(str(x) for x in (code, err.get("message")) if x), self._key)
        m = (msg(_KNOWN[code]) if code in _KNOWN
             else msg("film.provider.rejected", detail=vendor(text)) if text
             else msg("film.provider.generation_failed"))
    error, error_msg = m["message"], compact(m)
    ```
  - `download` 的过期重查失败 → `ProviderError.of("film.minimax.url_expired")`。
- **Seedance** `poll()` 失败分支：有 `code/message` → `film.provider.rejected`（`vendor(text)`）；否则 `expired` → `film.ark.task_expired`，`cancelled` → `film.provider.task_cancelled`，其它 → `film.provider.generation_failed`。同样填 `error` 与 `error_msg`。
- **Fake**：`ProviderError.of("film.fake.unknown_model", model=model)`、`TransientError.of("film.fake.throttled")`、`ProviderError.of("film.fake.no_task", id=task_id)`；Fake 的 TaskState 若有失败分支同理填 `error_msg`。`FakeTTS` 属子计划 2，不改（它在 `fake.py` 里，相应行尾加 `# i18n: todo(2)`）。
- **注册表** `providers/__init__.py`：
  ```python
  class UnknownProvider(UserError, KeyError):
      """未注册的厂商名（继承 KeyError：原有 except KeyError 不变）。"""
  ...
  raise UnknownProvider.of("film.provider.unknown", name=name)
  ```
  `get_tts` 的 `KeyError` 行尾加 `# i18n: todo(2)`。
  注意 `KeyError` 的 `str(e)` 带引号；现有代码用 `e.args[0]` 取文字（`session._provider`、`app._tts`），`.of()` 把中文兜底放在 `args[0]`，行为不变。

- [ ] **Step 5: 前端文案**

`zh.ts` 的 `srv` 下加 `console`、`rate`、`film.provider`、`film.fake`、`film.ark`、`film.minimax`，zh 文字与 Step 3 模板一字不差；`en.ts` 同结构写英文。示例：
```ts
// en.ts
console: { generic: 'the provider console', ark: 'Volcano Ark console', minimax: 'MiniMax Open Platform' },
rate: {
  fake: 'Fake provider: offline and free; amounts are for demo only',
  ark: 'Volcano Ark list price, 2026-10 (2.0: 46, fast: 37, mini: 23 CNY per million tokens; tokens ≈ seconds × width × height × 24 / 1024), not yet checked against a bill',
  minimax: 'MiniMax list price, 2026-11 (H3 768P 0.50, 2K 0.80 CNY/s; Highspeed and Lite per tier; first 5 reference images per clip free, extra ones billed), not yet checked against a bill',
},
// film.minimax.insufficient_balance: 'MiniMax balance is too low (1008). Top up, then generate this clip again'
// film.minimax.label_ref: 'reference image {id}'  ……
```

- [ ] **Step 6: 扫描清零**

`test_i18n_scan.py` 的 `MODULES` 加：
```python
MODULES = {
    "render/providers/base.py": None,
    "render/providers/fake.py": None,
    "render/providers/seedance.py": None,
    "render/providers/minimax.py": None,
    "render/providers/__init__.py": None,
}
```

- [ ] **Step 7: 重新生成 JSON，跑全部测试，提交**

```bash
cd backend && .venv/bin/python -m server.messages --write
for t in tests/pipeline/test_*.py tests/server/test_*.py tests/render/test_*.py tests/assistant/test_*.py; do .venv/bin/python $t || break; done
cd ../frontend && npm test && npm run lint && npm run build
cd .. && git add backend/render/providers/base.py backend/render/providers/fake.py backend/render/providers/seedance.py backend/render/providers/minimax.py backend/render/providers/__init__.py backend/server/messages.py backend/server/messages_codes.json backend/tests/server/test_i18n_scan.py backend/tests/render/test_providers.py backend/tests/render/test_seedance.py backend/tests/render/test_minimax.py frontend/src/i18n/zh.ts frontend/src/i18n/en.ts
git commit -m "视频厂商的报错带代码：基类异常混入 UserError，任务状态新增 error_msg；假厂商、方舟、MiniMax 的报错、任务失败原因、费率说明与控制台名改为登记过的代码（中文兜底不变，厂商原文脱敏后作原文参数）；补中英文案与代码断言，厂商文件纳入错误出口扫描"
```

受影响的现有测试：`test_minimax.py`、`test_seedance.py`、`test_providers.py` 里读 `rate_note`/`console_name` 字符串的断言（若有）改为读代码；`MSG`/`EXPIRED_MSG` 若被测试引用，改为断言 `e.code`。其余中文子串断言保持。

---

### Task 4: 出片会话、自由节点、编排与 runner

**Files:**
- Modify: `backend/render/session.py`、`free.py`、`compose.py`、`runner.py`
- Modify: `backend/server/messages.py`、`messages_codes.json`
- Modify: `frontend/src/i18n/zh.ts`、`en.ts`
- Modify: `backend/tests/server/test_i18n_scan.py`
- Test: `backend/tests/render/test_session.py`、`test_free.py`、`test_runner.py`、`test_free_runner.py`、`test_free_compose.py`

- [ ] **Step 1: 写失败的测试**

`test_session.py` 新增一节「错误对象持久化」：
1. `set_error(d, None)` 清空 `error` 与 `error_msg`；`set_error(d, msg(...))` 写中文兜底与紧凑消息；`set_error(d, SessionError.of(...))` 同；`set_error(d, "旧字符串")` 写字符串、`error_msg` 为 None；`copy_error(dst, src)` 两个字段都复制。
2. 超上限的段：`begin_submit` 后 `c["error_msg"]["code"] == "film.submit.over_budget"`，`c["error"]` 仍含「超出单章上限」。
3. 提交中断恢复：构造 `submitting` 尝试后 `recover(root)`，段与尝试的 `error_msg["code"] == "film.submit.interrupted"`。
4. **重建保留**：失败段（有 `error_msg`）在 `build(..., patch={})` 重建后，`error_msg` 不丢（覆盖 session.py:217 复制点）。
5. **清空**：失败后重出成功（`downloaded`），段的 `error` 与 `error_msg` 都为 None。
6. `queue_run` 超确认线抛 `Conflict`，`e.code == "film.run.confirm"`，`e.params["amount"] == {"t":"money","cny": <total>}`，`e.expected_cny == total`。
7. `resolve_settings` 未知分辨率 → `e.code == "film.settings.bad_resolution"`，`params["options"]` 是列表。

`test_runner.py` 新增：
1. 提交时 `AmbiguousSubmit`（用假厂商打桩抛 `AmbiguousSubmit.of("film.provider.submit_cut", kind="ReadTimeout")`）→ 段 `error_msg == {"code": "film.submit.ambiguous", "params": {"console": {"t": "ref", "code": "console.generic"}, "cause": {"code": "film.provider.submit_cut", "params": {"kind": "ReadTimeout"}}}}`（假厂商没有 `console_name` 时用 `console.generic`；有就用它的代码）。
2. 查询一直失败到放弃 → `error_msg["code"] == "film.poll.gave_up"`，`params["cause"]` 是内层错误的紧凑消息。
3. 瞬时失败正在重试 → `note_error` 写入 `film.provider.retrying` 且嵌套原因。
4. 任务失败（`TaskState.error_msg` 有代码）→ 尝试与段的 `error_msg` 等于厂商给的代码。
5. 厂商抛不带代码的普通异常 → `film.submit.crashed`，`params["cause"]["t"] == "vendor"`。

`test_free.py` 新增：重复参考 → `e.code == "film.free.dup_ref"`；时长越界 → `film.free.bad_duration`；正在生成时删除 → `film.free.busy_delete`。`test_free_compose.py` 新增：风格图删了 → `compose.FreeInvalid`，`e.code == "film.free_invalid.style_gone"`。

Run: `cd backend && .venv/bin/python tests/render/test_session.py` → Expected: `AttributeError: module 'render.session' has no attribute 'set_error'`。

- [ ] **Step 2: 登记代码**

```python
# 出片会话
register("film.session.corrupt", "出片会话文件损坏：{path}，已保留原文件，请检查后再操作")
register("film.session.corrupt_admin", "出片记录文件已损坏，原文件已备份，请联系管理员处理")
register("film.session.dir_gone", "出片会话目录已不存在（版本可能已删除）")
register("film.session.none", "还没有出片会话")
register("film.session.none_pick", "还没有出片会话：先到出片那一步选好厂商与档位")
register("film.session.no_storyboard", "这个版本还没有分镜产物")
register("film.file.not_found", "文件不存在")
register("film.clip.not_found", "没有这一段：{id}")
register("film.settings.unknown", "未知的出片设置：{keys}")
register("film.settings.no_model", "{provider} 没有档位 {model}")
register("film.settings.bad_resolution", "这个档位不支持 {resolution}，可选：{options}")
register("film.settings.bad_audio", "未知的声音模式：{mode}")
register("film.settings.no_native_audio", "这家厂商不出原声，可选：全部配音、静音")
register("film.build.no_shots", "这个版本的分镜没有镜头，无法切段")
register("film.build.in_flight", "有段在排队或生成中，等它们结束再改设置")
register("film.build.incomplete", "分镜结构不完整，无法切段：{detail}")
register("film.run.composing", "正在合成，等它结束再出片")
register("film.run.busy", "{id} 已在排队或生成中")
register("film.run.nothing", "没有要出的段")
register("film.run.confirm", "本次约 {amount}，请确认金额后再出片")
register("film.run.changed", "预估金额已变为 {amount}，请重新确认")
register("film.budget.exceeded", "超出单章上限 ¥{budget}：已花 {spent}，在跑预留 {reserved}，本次约 {total}")
register("film.choose.busy", "这一段正在生成，等它结束再换")
register("film.choose.not_success", "只能采用成功的那几次")
register("film.submit.interrupted", "提交时服务中断，不确定厂商是否已受理；请到厂商控制台核对后再重做")
register("film.submit.over_budget", "超出单章上限，没有提交")
register("film.submit.stale", "分镜或关键帧已改动，没有提交；请确认后重新出这一段")
register("film.submit.build_failed", "组装请求失败：{cause}")
register("film.submit.ambiguous", "提交时连接中断，不确定厂商是否已受理：请到{console}核对，确认没有生成再重做（{cause}）")
register("film.submit.unavailable", "厂商暂时不可用（已重试 {retries} 次）：{cause}")
register("film.submit.crashed", "提交异常：{kind}: {cause}")
register("film.provider.retrying", "厂商暂时不可达，正在重试：{cause}")
register("film.poll.gave_up", "多次查询都失败，已放弃；请到厂商控制台核对这个任务：{cause}")
register("film.download.keeps_failing", "下载一直失败，结果地址即将过期：{cause}")
register("film.download.not_playable", "下载到的文件不是可播放的视频")
# 自由节点
register("film.free.not_found", "没有这个自由节点：{id}")
register("film.free.dup_ref", "参考里有重复的资产")
register("film.free.no_style", "这部小说还没有风格图")
register("film.free.unknown_asset", "分镜里没有这个资产：{id}")
register("film.free.no_ref_image", "{name}（{id}）没有可用的参考图")
register("film.free.over_refs", "参考超出当前厂商上限（{need} / {max}）")
register("film.free.no_first_frame", "当前厂商不支持指定首帧")
register("film.free.no_keyframe", "镜头 {shot} 还没有关键帧")
register("film.free.self_tail", "不能用自己的尾帧作首帧")
register("film.free.no_tail", "{id} 还没有可用的尾帧")
register("film.free.bad_first_frame", "看不懂的首帧来源：{src}")
register("film.free.bad_duration", "时长要在 1 到 {max} 秒之间")
register("film.free.prompt_too_long", "提示词不能超过 {max} 字")
register("film.free.empty_prompt", "先写提示词再生成")
register("film.free.bad_fields", "不能改这些字段：{keys}")
register("film.free.busy_edit", "这个节点正在生成，等它结束再改")
register("film.free.target_duration", "挂靠某一段的节点时长跟随那一段，不能单独改")
register("film.free.busy_delete", "这个节点正在生成，等它结束再删")
register("film.free.tail_in_use", "{id} 用它的尾帧作首帧，先改掉那边")
register("film.free.composing", "正在合成，等它结束再生成")
register("film.free.confirm", "本次约 {amount}，请确认金额后再生成")
register("film.free.busy_choose", "这个节点正在生成，等它结束再换")
register("film.free_invalid.empty_prompt", "提示词是空的")
register("film.free_invalid.style_gone", "风格图已删除，请从参考里去掉它")
register("film.free_invalid.no_ref_image", "{id} 没有可用的参考图了")
register("film.free_invalid.keyframe_gone", "首帧用的关键帧没了：{shot}")
register("film.free_invalid.tail_gone", "首帧用的尾帧找不到了：{id}")
```
参数约定：
- `amount`/`spent`/`reserved`/`total` 传 `money(x)`；`budget` 传 `f"{s['budget_cny']:g}"`（保留原来的 `¥20` 写法）。
- `max`（时长）传 `f"{caps.max_clip_sec:g}"`；`need`、`max`（参考数）、`retries` 传整数。
- `keys` 传 `sorted(unknown)`（列表）。
- `cause` 一律 `cause_of(e)`；`detail`（结构不完整）传 `vendor(e)`；`kind` 传 `type(e).__name__`。
- `console` 传 `ref(getattr(provider, "console_name", "") or "console.generic")`。

- [ ] **Step 3: `session.py`**

1. 异常类混入：
   ```python
   from server.messages import UserError, compact, cause_of, money, msg, ref, vendor, render_zh

   class SessionError(UserError, ValueError): ...   # 其余子类不变（自动继承 mixin）
   ```
   `Conflict.__init__(self, message, expected_cny=None)` 签名不变；用 `Conflict.of("film.run.confirm", total, amount=money(total))` 构造（`.of()` 把额外位置参数原样传给 `__init__`）。
2. 删除 `INTERRUPTED_SUBMIT` 常量（改用 `msg("film.submit.interrupted")`）。`COMPOSE_INTERRUPTED` 属子计划 2，原样保留并在定义行与使用行尾加 `# i18n: todo(2)`。
3. 新增：
   ```python
   def set_error(obj: dict, err) -> None:
       """写给用户看的失败原因：error 为中文兜底，error_msg 为 {code, params}（前端按语言渲染）。
       err：None（清空）/ 消息对象（dict 带 code）/ 带代码的异常 / 字符串（未改造的模块、旧写法）。"""
       if err is None:
           obj["error"], obj["error_msg"] = None, None
           return
       m = err.as_msg() if isinstance(err, UserError) else err if isinstance(err, dict) and err.get("code") else None
       if m:
           params = m.get("params") or {}
           obj["error"] = m.get("message") or render_zh(m["code"], params)
           obj["error_msg"] = {"code": m["code"], "params": params}
       else:
           obj["error"], obj["error_msg"] = str(err), None


   def copy_error(dst: dict, src: dict) -> None:
       dst["error"], dst["error_msg"] = src.get("error"), src.get("error_msg")
   ```
4. **所有写 `error` 的地方都改走 `set_error`/`copy_error`**（包括写 `None` 的清空点，否则旧的 `error_msg` 会残留）。逐个核对：
   - `_row`/重建处（约 :212 清空、:217 继承旧段失败 → `copy_error(row, old)`）；
   - `queue_run` 排队清空（:401）；
   - `begin_submit` 的中断（:436–437，尝试与段都写 `msg("film.submit.interrupted")`）、超上限（:441，`film.submit.over_budget`）；
   - `submit_failed(root, clip_id, error, ...)`：参数 `error` 接受消息对象或字符串，尝试与段都 `set_error`；
   - `poll_update`：失败时
     ```python
     err = ({"code": st.error_msg["code"], "params": st.error_msg.get("params") or {}, "message": st.error}
            if st.error_msg else (st.error or msg("film.provider.failed")))
     a["state"], a["cost_cny"] = "failed", cost
     set_error(a, err)
     ...
     c["state"] = "failed"
     copy_error(c, a)
     ```
   - `note_error(root, clip_id, err)`：`set_error(_item(s, clip_id), err)`；
   - `downloaded`（:555 清空）、`download_failed`（:562–564）、`recover`（:599–600 → 尝试 `set_error(a, msg(...))`，段 `copy_error(c, a)`）；
   - 自由节点相关的同类写点（`_deliver` 若复制错误）。
   完成后用 `grep -n '"error"\|error=' render/session.py render/free.py` 自查，除合成部分（加 `# i18n: todo(2)`）外都应走这两个函数。
5. `raise` 全部换成 `.of()`，参数见 Step 2。`_provider`：
   ```python
   except KeyError as e:
       raise (SessionError.of(e.code, **e.params) if getattr(e, "code", None) else SessionError(e.args[0]))
   except base.ProviderError as e:
       raise (SessionError.of(e.code, **e.params) if e.code else SessionError(str(e)))
   ```
   （转抛时保留原代码与参数。）
6. `view()`：`"rate_note": getattr(provider, "rate_note", None)`（已是消息对象）。
7. 合成相关（`begin_compose`、`compose_progress`、`compose_done`、`compose_failed`、`_fail_interrupted_compose`）原样不动，涉及中文的行尾加 `# i18n: todo(2)`。

- [ ] **Step 4: `free.py`、`compose.py`**

- `free.py`：全部 `raise sess.XxxError(f"…")` → `.of("film.free.*" 或复用 "film.run.busy"/"film.run.changed"/"film.budget.exceeded"/"film.choose.not_success", …)`；状态写入（:203 排队清空、:215 采用后回到完成）改为 `sess.set_error(n, None)`。
- `compose.py`：
  ```python
  class Stale(UserError, Exception): ...
  class FreeInvalid(UserError, Exception): ...
  ```
  `FreeInvalid` 的抛出点改用 `film.free_invalid.*`，与 `free.py` 同文的复用 `film.free.no_first_frame`、`film.free.bad_first_frame`、`film.free.over_refs`。`build_clips` 里 `raise ValueError(f"未知的声音模式：…")` 是内部校验（声音模式在 `resolve_settings` 已校验），行尾加 `# i18n: internal`。提示词正文里的中文（【首帧】、角色参考……）是发给厂商的，不在扫描出口里，不动。

- [ ] **Step 5: `runner.py`**

```python
from server.messages import cause_of, compact, msg, ref

def _transient(...):
    ...
    sess.note_error(root, c["id"], msg("film.provider.retrying", cause=cause_of(e)))

# _poll 放弃：
m = msg("film.poll.gave_up", cause=cause_of(e))
st = base.TaskState(a["task_id"], "failed", error=m["message"], error_msg=compact(m))

# _download：
sess.download_failed(root, c["id"], msg("film.download.keeps_failing", cause=cause_of(e)), cost)
sess.download_failed(root, c["id"], e, cost)                    # ProviderError：带代码的异常直接传
sess.download_failed(root, c["id"], msg("film.download.not_playable"), cost)

# _submit：
sess.submit_failed(root, c["id"], msg("film.submit.stale"), stale=True)
sess.submit_failed(root, c["id"], e)                            # FreeInvalid
sess.submit_failed(root, c["id"], msg("film.submit.build_failed", cause=cause_of(e)))
where = getattr(provider, "console_name", "") or "console.generic"
sess.submit_failed(root, c["id"], msg("film.submit.ambiguous", console=ref(where), cause=cause_of(e)),
                   uncertain=True)
sess.submit_failed(root, c["id"], msg("film.submit.unavailable", retries=self.retries, cause=cause_of(e)))
sess.submit_failed(root, c["id"], e)                            # ProviderError
sess.submit_failed(root, c["id"], msg("film.submit.crashed", kind=type(e).__name__, cause=cause_of(e)))
```
`download_failed(root, clip_id, error, cost)` 的 `error` 同样接受消息对象 / 异常 / 字符串，内部 `set_error`。`print(...)` 是运维日志，不动。

- [ ] **Step 6: 前端文案 + 扫描**

`zh.ts`/`en.ts` 的 `srv.film` 下加 `session`、`file`、`clip`、`settings`、`build`、`run`、`budget`、`choose`、`submit`、`poll`、`download`、`free`、`free_invalid`，以及 `provider.retrying`（与 Task 3 的 `provider` 合并到同一节点）。

`test_i18n_scan.py` 的 `MODULES` 加：
```python
    "render/session.py": None,
    "render/free.py": None,
    "render/compose.py": None,
    "render/runner.py": None,
```

- [ ] **Step 7: 重新生成 JSON，跑全部测试，提交**

```bash
cd backend && .venv/bin/python -m server.messages --write
for t in tests/pipeline/test_*.py tests/server/test_*.py tests/render/test_*.py tests/assistant/test_*.py; do .venv/bin/python $t || break; done
cd ../frontend && npm test && npm run lint && npm run build
cd .. && git add backend/render/session.py backend/render/free.py backend/render/compose.py backend/render/runner.py backend/server/messages.py backend/server/messages_codes.json backend/tests/server/test_i18n_scan.py backend/tests/render/test_session.py backend/tests/render/test_free.py backend/tests/render/test_runner.py backend/tests/render/test_free_runner.py backend/tests/render/test_free_compose.py frontend/src/i18n/zh.ts frontend/src/i18n/en.ts
git commit -m "出片会话、自由节点与 runner 的报错带代码：会话错误改为 error 加单字段 error_msg，经 set_error、copy_error 统一写入与复制（重建、尝试转段、恢复、清空都不丢）；runner 的内层原因改为嵌套 cause，提交不明提示引用厂商控制台代码；补中英文案与持久化、嵌套原因用例，相关模块纳入错误出口扫描"
```

**文字变化**（中文兜底与原来不同，现有断言若依赖需改）：
- `film.settings.unknown`：原来是 `['a', 'b']` 的列表字面写法，现在是 `a、b`。
- 其余模板均保持一字不差。

受影响的现有测试：`test_session.py:156`（「超出单章上限」子串仍成立，不改）；`test_runner.py`、`test_free_runner.py`、`test_minimax.py` 里断言 `c["error"]` 中文子串的仍成立（兜底不变）。若有测试 `import sess.INTERRUPTED_SUBMIT`，改为断言 `error_msg["code"]`。

---

### Task 5: 出片接口与前端显示

**Files:**
- Modify: `backend/server/app.py`（只改范围边界里列出的出片函数）
- Modify: `backend/tests/server/test_i18n_scan.py`
- Test: `backend/tests/server/test_render.py`、`test_render_free.py`
- Modify: `frontend/src/types.ts`、`film.ts`、`useFilm.ts`、`components/FilmPanel.tsx`、`components/NodeCards.tsx`、`components/NodeGraph.tsx`、`components/common/MoneyConfirm.tsx`
- Test: `frontend/tests/film.test.tsx`（追加一节）

- [ ] **Step 1: 写失败的后端测试**

`test_render.py` 新增：
1. 没有会话时 `GET …/render/session` → 404，`detail == {"code": "film.session.none", "params": {}, "message": "还没有出片会话"}`。
2. 超确认线出片 → 409，`detail["code"] == "film.run.confirm"`，`detail["expected_cny"]` 等于重算金额，`detail["params"]["amount"]["t"] == "money"`。
3. 改设置用未知分辨率 → 422，`detail["code"] == "film.settings.bad_resolution"`。
4. 取不存在的文件 → 404，`detail["code"] == "film.file.not_found"`。
5. 会话视图 `options.rate_note == {"code": "rate.fake", "params": {}}`。

`test_render_free.py` 新增：重复参考建自由节点 → 422，`detail["code"] == "film.free.dup_ref"`。

Run: `cd backend && .venv/bin/python tests/server/test_render.py` → Expected: 断言失败（detail 还是字符串）。

- [ ] **Step 2: `app.py` 出片调用点**

```python
from server.messages import msg, to_detail

def _render_call(fn, *args, **kwargs):
    """把出片会话的业务异常翻成 HTTP 状态码；带代码的给消息对象（spec §3.2）。"""
    try:
        return fn(*args, **kwargs)
    except render_session.NotFound as e:
        raise HTTPException(404, detail=to_detail(e))
    except render_session.Conflict as e:
        raise HTTPException(409, detail=to_detail(e, expected_cny=e.expected_cny))
    except render_session.Corrupt:
        raise HTTPException(500, detail=msg("film.session.corrupt_admin"))
    except render_session.SessionError as e:
        raise HTTPException(422, detail=to_detail(e))
```
- `to_detail` 对不带代码的异常返回与现在一样的形状（字符串；`Conflict` 为 `{"message", "expected_cny"}`），所以合成那些还没改造的 `Conflict` 照旧。
- `_render_ctx` 的「这个版本还没有分镜产物」→ `HTTPException(422, detail=msg("film.session.no_storyboard"))`。
- `render_session_get`、`render_session_patch`、`_free_ctx` 的「还没有出片会话」→ `msg("film.session.none")`；`_film_quote` 的 → `msg("film.session.none_pick")`。
- `render_file` 的「文件不存在」→ `msg("film.file.not_found")`。
- `_gate_status` 里同样的「这个版本还没有分镜产物」是验证门结果（子计划 4），行尾加 `# i18n: todo(4)`；`_render_gate` 不动。
- 助手经 `assistant/actions.py::_op` 调 `_film_quote`/`_film_run`：它对 dict detail 取 `message`，给模型的仍是中文，无需改。

`test_i18n_scan.py` 的 `MODULES` 加：
```python
    "server/app.py": {"_render_ctx", "_render_call", "render_session_post", "render_session_get",
                      "render_session_patch", "_film_quote", "_film_run", "render_clip_run", "render_run_all",
                      "render_clip_chosen", "render_clip_patch", "_free_ctx", "render_free_create",
                      "render_free_patch", "render_free_delete", "render_free_run", "render_free_chosen",
                      "render_file"},
```

- [ ] **Step 3: 写失败的前端测试**

`frontend/tests/film.test.tsx` 追加一节「10g. 后端错误按界面语言渲染」：
1. 构造会话，某段 `error: '内容被 MiniMax 审核拦下（1026）：…', error_msg: { code: 'film.minimax.moderated', params: {} }`，另一段只有旧的 `error: '旧中文原因'`（无 `error_msg`）。
2. 中文界面渲染出片面板段详情：第一段显示中文译文，第二段显示「旧中文原因」。
3. 切到英文（按该文件已有的切换语言写法），第一段显示 `en.srv.film.minimax.moderated` 的英文，第二段仍是「旧中文原因」。
4. `options.rate_note = { code: 'rate.fake', params: {} }` 时确认框的费率依据显示对应语言文字。
5. 接口 409 返回 `{code: 'film.run.changed', params: {amount: {t:'money', cny: 6}}, message: '…', expected_cny: 6}` 时，`conflictCny` 仍取到 6（回归）；出片失败 422 返回 `{code:'film.run.nothing', …}` 时面板错误条显示对应语言文字，切换语言后跟着变。

Run: `cd frontend && npm test` → Expected: 10g 失败。

- [ ] **Step 4: 前端改动**

- `types.ts`：
  - `import type { ServerMsg, MsgLike } from './i18n/serverMsg'`；
  - `FilmAttempt`、`FilmClip`、`FilmFreeNode` 加 `error_msg?: ServerMsg | null`（可选，现有测试夹具不用改）；
  - `FilmSession.options.rate_note: MsgLike`。
- `film.ts`：`c.error ?? tr('film.failed')` → `itemError(c) || tr('film.failed')`；`if (c.error) lines.push(c.error)` → `const e = itemError(c); if (e) lines.push(e)`。
- `useFilm.ts`：
  - `const [error, setError] = useState<MsgLike>(null)`；
  - `const msg = (e: unknown) => …` 删去，`fail` 里 `setError(errValue(e))`；
  - 验证门分支 `setGate(e.message)` 不变（子计划 4）；
  - `readClipFailed` 是前端模板包裹后端错误：`setError(tr('film.readClipFailed', { error: formatMsg(errValue(e)) }))`（即时格式化，见实施裁定 5）；
  - 返回值类型里 `error: MsgLike`。
- `FilmPanel.tsx`：`const { t, locale } = useI18n()`；
  - `{film.error && <p …>{formatMsg(film.error, locale)}</p>}`；
  - 段详情、自由节点详情的 `c.error`/`n.error` → `itemError(c, locale)`（条件也用它的结果）；
  - 尝试列表若显示 `a.error`，同样改。
- `NodeCards.tsx`：`c.error`/`n.error` 的显示与 `title` 都换成 `itemError(x, locale)`。
- `NodeGraph.tsx`：`film.error` → `formatMsg(film.error, locale)`。
- `MoneyConfirm.tsx`：`rateNote?: MsgLike`；显示 `t('money.rateNote', { note: formatMsg(p.rateNote, locale) || t('money.rateUnknown') })`。`ComposePanel` 传的 TTS `rate_note` 仍是字符串，`formatMsg` 原样返回，不用改。

- [ ] **Step 5: 全部检查，提交**

```bash
cd backend && .venv/bin/python -m server.messages --write
for t in tests/pipeline/test_*.py tests/server/test_*.py tests/render/test_*.py tests/assistant/test_*.py; do .venv/bin/python $t || break; done
cd ../frontend && npm test && npm run lint && npm run build
cd .. && git add backend/server/app.py backend/server/messages.py backend/server/messages_codes.json backend/tests/server/test_i18n_scan.py backend/tests/server/test_render.py backend/tests/server/test_render_free.py frontend/src/types.ts frontend/src/film.ts frontend/src/useFilm.ts frontend/src/components/FilmPanel.tsx frontend/src/components/NodeCards.tsx frontend/src/components/NodeGraph.tsx frontend/src/components/common/MoneyConfirm.tsx frontend/tests/film.test.tsx
git commit -m "出片接口返回带代码的错误对象（409 照旧附重算金额），未改造的异常仍返回原来的字符串；前端出片面板、节点图卡片、确认框的费率依据改为按界面语言渲染，错误状态保存原始 detail，切换语言后已显示的错误跟着变；旧会话里只有中文的失败原因照原样显示"
```

受影响的现有测试：`tests/server/test_render.py`、`test_render_free.py`、`test_assistant_ops.py` 里断言 `r.json()["detail"]` 为某个中文字符串的，改为断言 `["detail"]["code"]`（或 `["detail"]["message"]` 含原中文）。前端 `film.test.tsx` 里若有夹具把 `rate_note` 设为字符串，保持可用（`formatMsg` 原样返回）。

---

## 实施裁定

1. **TTS 不在本子计划**：spec §9 修订后把 TTS 厂商（含 `get_tts` 与 TTS 的 `rate_note`）归到子计划 2；本计划只做视频厂商。`fake.py` 里的 `FakeTTS`、`providers/__init__.py` 的 `get_tts` 行尾标 `# i18n: todo(2)`。
2. **参数名取自模板**：登记只写模板，参数名从 `{name}` 提取，不另写参数列表——避免两处不一致；`msg()` 要求实参集合与之完全相等。
3. **中文兜底保持原文**：模板设计成渲染结果与原字符串一字不差（`budget` 用 `:g` 预格式化成字符串，`options` 用列表、兜底用「、」连接）。现有断言中文子串的测试大多保留不改，新增用例断言代码。唯一的文字变化是 `film.settings.unknown` 的键列表写法。
4. **前端 zh 文案与后端兜底强制一致**：`srv-codes.test.ts` 校验 `zh.srv.<code>` 与后端模板完全相同，防止两边漂移；en 只校验占位符与参数名一致。
5. **前端自拼的包裹文案即时格式化**：如 `film.readClipFailed` 这类前端模板里嵌后端错误的，在出错时用当前语言格式化成字符串存起来，不做切语言跟随（少见、即时性强）。纯后端错误一律存原始值、渲染时格式化。
6. **`rate_note` 类属性写字面量 dict**：避免类定义求值时依赖登记顺序；测试断言它是登记过的代码。
7. **`console_name` 改为代码字符串**：runner 用 `ref(console_name)` 嵌进提示；不认识或没有时用 `console.generic`。
8. **嵌套原因只存紧凑形式**：`cause` 存 `{code, params}`（不带 message）；不带代码的异常存 `vendor` 原文（截断 300 字，MiniMax 原文先 `scrub`）。
9. **扫描器的出口定义**：异常类名后缀匹配 + `HTTPException`/`note_error`/`submit_failed`/`download_failed`/`TaskState` 调用 + 关键字 `error`/`detail`/`message`/`step` + `x["error"] =` 赋值。`print`、发给厂商的提示词正文、日志不算出口。`app.py` 只扫本子计划的出片函数。
10. **`set_error` 覆盖清空点**：所有写 `error=None` 的地方也必须走 `set_error(x, None)`，否则旧 `error_msg` 残留会让成功的段仍显示失败原因；Task 4 Step 1 的第 5 条用例守住它。
11. **`KeyError` 子类的文字**：`UnknownProvider` 继承 `KeyError`；中文兜底放在 `args[0]`，`to_detail`、`cause_of` 对 `KeyError` 取 `args[0]`（避免 `str()` 带引号）。
12. **验证门保持现状**：`_render_gate` 的 `{message, verification}` 与 `_gate_status` 的 message 属子计划 4；前端 `setGate(e.message)` 不改。
13. **助手链路不改**：`assistant/actions.py::_op` 对 dict detail 取 `message` 给模型，出片接口改成消息对象后给模型的仍是中文兜底。
14. **关键帧不在范围**：`render/keyframes.py` 与 `/render/keyframes` 不在 spec 子计划 1 清单，保持字符串。
