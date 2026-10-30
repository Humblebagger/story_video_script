# 管理后台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给管理员一个后台：看用户、看 token 消耗与费用、看任务、做停用/月上限/重置密码/角色操作，并留审计。

**Architecture:** 后端新增 `pricing`、`usage`（追加写流水账）、`audit`、`admin`（管理逻辑 + 命令行）四个模块；`auth.py` 增加 `role`、`disabled`、`monthly_cap_usd`、`last_seen_at`；`app.py` 在转换结束和章后整理处落账、提交转换处查月上限、提供 `/admin/*` 接口。前端新增 `components/admin/` 下的五个页签与手写 SVG 折线图，管理员在右上角进入。

**Tech Stack:** FastAPI + 文件存储（后端）；React 19 + Vite + TS、happy-dom 测试（前端）。

**Spec:** `docs/specs/2026-10-29-admin-console-design.md`

**全局约束**

- 分支 `langchain`；Python 用 `backend/.venv`（3.12）。
- 提交只 `git add` 具体文件，禁止 `git add -A` / `git commit -a`；提交信息**不得**带任何 Claude 署名。
- 不读、不打印 `backend/.env`。
- 后端测试是脚本式：`cd backend && .venv/bin/python tests/server/test_xxx.py`，以 `ALL PASS` 结尾。
- 前端测试：`cd frontend && npm test`（`tsc -b --force` 后逐个 `vite build --ssr` + `node`），每个套件以 `ALL PASS` 结尾。
- 管理接口与页面**不得**返回或显示小说原文（`text`、`input_text`）与分镜内容（`result`）。

**与 spec 的两处裁定**

1. **评审模型的用量拆分**：spec 说评审用另一模型时按模型拆成两行。实际上转换与评审共用一个 `UsageCallback`，attempt 记录里的用量不分模型，拆不出来。裁定：整笔记在转换模型名下，记录加 `mixed_models: [转换模型, 评审模型]`，后台详情里显示「含评审模型，金额按转换模型估算」。评审默认关闭，影响面小。Task 4 同步改 spec。
2. **失败任务的耗时**：版本记录没有结束时间，失败任务无法算耗时。裁定：运行中任务显示已运行时长，失败任务只显示开始时间。Task 4 同步改 spec。

**与 Google 登录计划的关系**：`docs/plans/2026-10-28-google-login.md` 尚未执行（优先级最低）。本计划先改 `auth.py`；之后执行 Google 计划时，它的 Task 2 要在本计划改过的 `_public`、`_now` 基础上合并（保留本计划新增的 `role`、`disabled` 字段）。

---

## 文件结构

| 文件 | 动作 | 职责 |
|---|---|---|
| `backend/server/pricing.py` | 新建 | 默认价格表、读写 `pricing.json`、单条记录计价 |
| `backend/server/usage.py` | 新建 | 流水账写入、读取、分组汇总、每千字成本、当月花费、按天序列 |
| `backend/server/audit.py` | 新建 | 审计写入与读取 |
| `backend/server/admin.py` | 新建 | 用户行组装、详情、操作与约束、任务、概览、CSV、历史补导；命令行入口 |
| `backend/server/novels.py` | 改 | 新增 `titles()`、`counts()` 两个只读元数据函数 |
| `backend/server/auth.py` | 改 | 新字段；停用校验；`touch_seen`、`get_user_raw`、`list_users_safe`、`update_user`、`set_password` |
| `backend/server/app.py` | 改 | `admin_user`；落账；月上限；`/admin/*` |
| `backend/tests/server/test_usage.py` | 新建 | 价格表与流水账 |
| `backend/tests/server/test_admin.py` | 新建 | 管理逻辑、命令行、接口 |
| `frontend/src/types.ts` | 改 | 管理后台类型 |
| `frontend/src/auth.ts` | 改 | `User.role` |
| `frontend/src/api.ts` | 改 | `admin*` 函数 |
| `frontend/src/components/admin/format.ts` | 新建 | 金额、数字、时间格式 |
| `frontend/src/components/admin/useLoad.ts` | 新建 | 拉取 + 可选定时刷新 |
| `frontend/src/components/admin/LineChart.tsx` | 新建 | 手写 SVG 折线图 |
| `frontend/src/components/admin/Overview.tsx` | 新建 | 概览页签 |
| `frontend/src/components/admin/Users.tsx` | 新建 | 用户页签与详情、操作 |
| `frontend/src/components/admin/UsageTab.tsx` | 新建 | 用量页签、CSV、价格表编辑 |
| `frontend/src/components/admin/JobsTab.tsx` | 新建 | 任务页签 |
| `frontend/src/components/admin/AuditTab.tsx` | 新建 | 审计页签 |
| `frontend/src/components/admin/AdminView.tsx` | 新建 | 页签框架 |
| `frontend/src/App.tsx` | 改 | 「管理」入口 |
| `frontend/src/index.css` | 改 | `.adm*` 样式 |
| `frontend/tests/admin.test.tsx` | 新建 | 后台界面回归 |
| `frontend/tests/flow.test.tsx` | 改 | 非管理员不显示「管理」 |
| `frontend/package.json` | 改 | 测试脚本 |
| `README.md`、`frontend/README.md`、`docs/specs/2026-10-29-admin-console-design.md` | 改 | 文档与裁定 |

---

### Task 1: 价格表与用量流水账

**Files:**
- Create: `backend/server/pricing.py`
- Create: `backend/server/usage.py`
- Test: `backend/tests/server/test_usage.py`

- [ ] **Step 1: 写失败测试**

Create `backend/tests/server/test_usage.py`:

```python
#!/usr/bin/env python3
"""价格表与用量流水账：落账、坏行容忍、分组汇总、计价、每千字成本、当月花费、按天序列。

全程使用临时数据目录。用法: python3 tests/server/test_usage.py
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

_TMP = tempfile.TemporaryDirectory()
os.environ["STORYBOARD_DATA_DIR"] = _TMP.name     # 必须在导入 server.* 之前

from server import pricing, usage  # noqa: E402

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
U1, U2 = "a" * 12, "b" * 12


def tok(i=0, o=0, cr=0, cw=0, calls=1):
    return {"calls": calls, "input": i, "output": o, "cache_read": cr, "cache_write": cw}


def must_raise(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc as e:
        return e
    raise AssertionError(f"应抛 {exc.__name__}")


def main() -> int:
    # 1. 价格表：默认表、计价、未定价、保存校验
    table = pricing.load()
    assert table["currency"] == "USD" and "claude-sonnet-5" in table["models"]
    row = {"model": "claude-sonnet-5", **tok(1_000_000, 1_000_000, 1_000_000, 1_000_000)}
    assert abs(pricing.cost(row, table) - (2.0 + 10.0 + 0.2 + 2.5)) < 1e-9
    assert pricing.cost({"model": "nope", **tok(5)}, table) is None
    must_raise(ValueError, pricing.save, {"models": {"m": {"input": -1, "output": 0,
                                                          "cache_read": 0, "cache_write": 0}}})
    must_raise(ValueError, pricing.save, {"models": {"m": {"input": 1}}})
    saved = pricing.save({"models": {"claude-sonnet-5": {"input": 3, "output": 15,
                                                         "cache_read": 0.3, "cache_write": 3.75}}})
    assert saved["currency"] == "USD" and saved["updated_at"]
    assert pricing.load()["models"]["claude-sonnet-5"]["input"] == 3
    table = pricing.load()
    print("1. 价格表：默认 / 计价 / 未定价 / 保存校验 ✓")

    # 2. 落账与读取；坏行跳过
    usage.record(user_id=U1, purpose="convert", model="claude-sonnet-5",
                 usage=tok(1_000_000, 0), ok=True, chars=4000,
                 novel_id="n1", chapter_id="c1", version_id="v1",
                 at="2026-10-30T08:00:00+00:00")
    usage.record(user_id=U1, purpose="convert", model="claude-sonnet-5",
                 usage=tok(0, 100_000), ok=False, chars=2000,
                 at="2026-10-29T08:00:00+00:00")
    usage.record(user_id=U2, purpose="digest", model="mystery", usage=tok(10, 10),
                 ok=True, at="2026-10-02T08:00:00+00:00")
    usage.record(user_id=U2, purpose="convert", model="claude-sonnet-5",
                 usage=tok(0, 200_000), ok=True, chars=1000,
                 at="2026-09-20T08:00:00+00:00", mixed_models=["claude-sonnet-5", "x"])
    with open(usage.USAGE_FILE, "a", encoding="utf-8") as f:
        f.write('{"broken": \n')
    rows = usage.read()
    assert len(rows) == 4, "坏行应跳过"
    assert rows[3]["mixed_models"] == ["claude-sonnet-5", "x"]
    assert len(usage.read(since=datetime(2026, 10, 1, tzinfo=timezone.utc))) == 3
    assert len(usage.read(user_id=U2)) == 2
    print("2. 落账 / 读取 / 时间与用户过滤 / 坏行容忍 ✓")

    # 3. 分组汇总：用户、天、模型；未定价单独计数、不计入金额
    by_user = {r["key"]: r for r in usage.aggregate(rows, "user", table)}
    assert by_user[U1]["calls"] == 2 and by_user[U1]["input"] == 1_000_000
    assert abs(by_user[U1]["cost_usd"] - (3.0 + 1.5)) < 1e-9
    assert by_user[U2]["unpriced"] == 1 and abs(by_user[U2]["cost_usd"] - 3.0) < 1e-9
    days = [r["key"] for r in usage.aggregate(rows, "day", table)]
    assert days == sorted(days), "按天升序"
    by_model = {r["key"]: r for r in usage.aggregate(rows, "model", table)}
    assert by_model["mystery"]["cost_usd"] == 0 and by_model["mystery"]["unpriced"] == 1
    must_raise(ValueError, usage.aggregate, rows, "bogus", table)
    print("3. 按用户 / 天 / 模型汇总，未定价不计金额 ✓")

    # 4. 每千字成本：只算成功的 convert、有字数、已定价
    pk = usage.per_k_chars(rows, table)
    # U1 成功一次：$3 / 4000 字 → $0.75/千字；U2 成功一次：$3 / 1000 字 → $3/千字
    assert pk["n"] == 2 and abs(pk["mean"] - 1.875) < 1e-9 and abs(pk["p90"] - 3.0) < 1e-9
    assert usage.per_k_chars([], table) == {"n": 0, "mean": None, "p90": None}
    print("4. 每千字成本均值与 P90 ✓")

    # 5. 当月花费与按天序列
    assert abs(usage.month_spent(U1, table, now=NOW) - 4.5) < 1e-9
    assert usage.month_spent(U2, table, now=NOW) == 0, "9 月的不算、未定价的不算"
    series = usage.daily_series(rows, 3, table, now=NOW)
    assert [d["day"] for d in series] == ["2026-10-28", "2026-10-29", "2026-10-30"]
    assert [round(d["cost_usd"], 2) for d in series] == [0, 1.5, 3.0]
    print("5. 当月花费 / 按天序列补零 ✓")

    # 6. 未定价模型列表
    assert usage.unpriced_models(rows, table) == ["mystery"]
    print("6. 未定价模型 ✓")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python tests/server/test_usage.py`
Expected: FAIL，`ImportError: cannot import name 'pricing' from 'server'`

- [ ] **Step 3: 实现 `backend/server/pricing.py`**

```python
"""价格表：每百万 token 的美元单价。

金额在查询时按当前价格表现算——改了价格，历史金额随之重算，页面注明「按当前价格表估算」。
默认价来自 2026-10 Anthropic 官方价目；走网关或用别的模型时在后台改。
"""
import copy
import json
from typing import Optional

from server.auth import DATA_DIR
from server.store import now_iso

PRICING_FILE = DATA_DIR / "pricing.json"
KEYS = ("input", "output", "cache_read", "cache_write")

DEFAULT = {
    "currency": "USD",
    "note": "每百万 token 单价（美元）",
    "updated_at": None,
    "models": {
        "claude-sonnet-5": {"input": 2.0, "output": 10.0, "cache_read": 0.2, "cache_write": 2.5},
        "claude-sonnet-5-5": {"input": 2.0, "output": 10.0, "cache_read": 0.2, "cache_write": 2.5},
        "claude-opus-5-5": {"input": 4.0, "output": 20.0, "cache_read": 0.2, "cache_write": 5.0},
        "claude-haiku-5-5": {"input": 0.1, "output": 0.5, "cache_read": 0.01, "cache_write": 0.125},
    },
}


def load() -> dict:
    if PRICING_FILE.exists():
        try:
            return json.loads(PRICING_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return copy.deepcopy(DEFAULT)


def _validate(table: dict) -> dict:
    models = table.get("models")
    if not isinstance(models, dict) or not models:
        raise ValueError("价格表必须包含至少一个模型")
    clean = {}
    for name, price in models.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(price, dict):
            raise ValueError(f"模型 {name!r} 的单价格式不对")
        row = {}
        for k in KEYS:
            v = price.get(k)
            if not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0:
                raise ValueError(f"模型 {name} 的 {k} 单价必须是非负数")
            row[k] = float(v)
        clean[name.strip()] = row
    return clean


def save(table: dict) -> dict:
    out = {"currency": "USD", "note": DEFAULT["note"], "updated_at": now_iso(),
           "models": _validate(table)}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = PRICING_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(PRICING_FILE)
    return out


def cost(row: dict, table: dict) -> Optional[float]:
    """一条用量记录的金额；模型没定价返回 None。"""
    price = (table.get("models") or {}).get(row.get("model") or "")
    if price is None:
        return None
    return sum((row.get(k) or 0) * price.get(k, 0) for k in KEYS) / 1e6
```

- [ ] **Step 4: 实现 `backend/server/usage.py`**

```python
"""用量流水账：每次模型调用落一行，追加写，删版本不影响历史。

一行一条 JSON；读取时跳过解析失败的行（进程崩溃时可能写了半行）。
"""
import json
import math
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

from server import pricing
from server.auth import DATA_DIR
from server.store import now_iso

USAGE_FILE = DATA_DIR / "usage.jsonl"
TOKENS = ("calls", "input", "output", "cache_read", "cache_write")
_lock = threading.Lock()


def record(*, user_id: str, purpose: str, model: str, usage: dict, ok: bool,
           chars: int = 0, novel_id: Optional[str] = None,
           chapter_id: Optional[str] = None, version_id: Optional[str] = None,
           at: Optional[str] = None, mixed_models: Optional[list] = None) -> dict:
    row = {"at": at or now_iso(), "user_id": user_id, "novel_id": novel_id,
           "chapter_id": chapter_id, "version_id": version_id, "purpose": purpose,
           "model": model, "ok": bool(ok),
           **{k: int(usage.get(k) or 0) for k in TOKENS}, "chars": int(chars or 0)}
    if mixed_models:
        row["mixed_models"] = list(mixed_models)
    line = json.dumps(row, ensure_ascii=False) + "\n"
    with _lock:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(USAGE_FILE, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
    return row


def _when(row: dict) -> datetime:
    return datetime.fromisoformat(row["at"])


def read(since: Optional[datetime] = None, user_id: Optional[str] = None) -> list:
    if not USAGE_FILE.exists():
        return []
    out = []
    with open(USAGE_FILE, encoding="utf-8") as f:
        for line in f:
            try:
                row = json.loads(line)
                when = _when(row)
            except (ValueError, KeyError, TypeError):
                continue
            if since is not None and when < since:
                continue
            if user_id is not None and row.get("user_id") != user_id:
                continue
            out.append(row)
    return out


_GROUPS = {"user": lambda r: r.get("user_id") or "",
           "day": lambda r: r["at"][:10],
           "model": lambda r: r.get("model") or ""}


def aggregate(rows: list, group: str, table: dict) -> list:
    if group not in _GROUPS:
        raise ValueError(f"不支持的分组：{group}")
    key = _GROUPS[group]
    buckets: dict = {}
    for r in rows:
        b = buckets.setdefault(key(r), {"key": key(r), **{k: 0 for k in TOKENS},
                                        "chars": 0, "cost_usd": 0.0, "unpriced": 0})
        for k in TOKENS:
            b[k] += r.get(k) or 0
        b["chars"] += r.get("chars") or 0
        c = pricing.cost(r, table)
        if c is None:
            b["unpriced"] += 1
        else:
            b["cost_usd"] += c
    out = list(buckets.values())
    if group == "day":
        out.sort(key=lambda b: b["key"])
    else:
        out.sort(key=lambda b: b["cost_usd"], reverse=True)
    return out


def per_k_chars(rows: list, table: dict) -> dict:
    """每千字成本：只算成功的转换、有字数、已定价的记录。P90 用最近秩法。"""
    vals = []
    for r in rows:
        if r.get("purpose") != "convert" or not r.get("ok") or not r.get("chars"):
            continue
        c = pricing.cost(r, table)
        if c is not None:
            vals.append(c / r["chars"] * 1000)
    if not vals:
        return {"n": 0, "mean": None, "p90": None}
    vals.sort()
    return {"n": len(vals), "mean": sum(vals) / len(vals),
            "p90": vals[math.ceil(0.9 * len(vals)) - 1]}


def month_start(now: Optional[datetime] = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def month_spent(user_id: str, table: dict, now: Optional[datetime] = None) -> float:
    total = 0.0
    for r in read(since=month_start(now), user_id=user_id):
        c = pricing.cost(r, table)
        total += c or 0.0
    return total


def daily_series(rows: list, days: int, table: dict, now: Optional[datetime] = None) -> list:
    """最近 days 天（含今天）每天的金额，没有记录的天补 0。"""
    now = now or datetime.now(timezone.utc)
    keys = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days - 1, -1, -1)]
    sums = {k: 0.0 for k in keys}
    for r in rows:
        k = r["at"][:10]
        if k in sums:
            sums[k] += pricing.cost(r, table) or 0.0
    return [{"day": k, "cost_usd": sums[k]} for k in keys]


def unpriced_models(rows: list, table: dict) -> list:
    return sorted({r.get("model") or "" for r in rows if pricing.cost(r, table) is None})
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && .venv/bin/python tests/server/test_usage.py`
Expected: 六段 ✓，`ALL PASS`

- [ ] **Step 6: 提交**

```bash
git add backend/server/pricing.py backend/server/usage.py backend/tests/server/test_usage.py
git commit -m "用量流水账与价格表：追加写 usage.jsonl、坏行容忍，按用户/天/模型汇总，美元价格表现算金额，每千字成本与当月花费"
```

---

### Task 2: 账号字段（角色、停用、月上限、最近活跃）

**Files:**
- Modify: `backend/server/auth.py`
- Test: `backend/tests/server/test_admin.py`（本任务先建文件，写第 1 段）

- [ ] **Step 1: 写失败测试**

Create `backend/tests/server/test_admin.py`:

```python
#!/usr/bin/env python3
"""管理后台：账号字段、管理逻辑与约束、审计、命令行、/admin 接口。

全程使用临时数据目录。用法: python3 tests/server/test_admin.py
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

_TMP = tempfile.TemporaryDirectory()
os.environ["STORYBOARD_DATA_DIR"] = _TMP.name     # 必须在导入 server.* 之前

from server import auth  # noqa: E402


def must_raise(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc as e:
        return e
    raise AssertionError(f"应抛 {exc.__name__}")


def part_auth():
    root = auth.register("root", "secret1")
    bob = auth.register("bob", "secret1")
    assert root["role"] == "user" and root["disabled"] is False, "新用户默认普通、未停用"

    # 角色、上限、停用
    auth.update_user(root["id"], role="admin")
    assert auth.get_user(root["id"])["role"] == "admin"
    auth.update_user(bob["id"], monthly_cap_usd=5.0)
    assert auth.get_user_raw(bob["id"])["monthly_cap_usd"] == 5.0
    must_raise(ValueError, auth.update_user, bob["id"], salt="x")
    tok = auth.issue_token(bob["id"])
    assert auth.verify_token(tok)["id"] == bob["id"]
    auth.update_user(bob["id"], disabled=True)
    assert auth.verify_token(tok) is None, "停用后现有 token 立即失效"
    e = must_raise(auth.AuthError, auth.authenticate, "bob", "secret1")
    assert str(e) == "账号已停用"
    must_raise(auth.AuthError, auth.authenticate, "bob", "wrong")
    auth.update_user(bob["id"], disabled=False)
    assert auth.verify_token(tok)["id"] == bob["id"]

    # 重置密码
    must_raise(auth.AuthError, auth.set_password, bob["id"], "123")
    auth.set_password(bob["id"], "newpass1")
    assert auth.authenticate("bob", "newpass1")["id"] == bob["id"]

    # 安全列表不含密码字段
    safe = auth.list_users_safe()
    assert all("password_hash" not in u and "salt" not in u for u in safe)
    assert {u["username"] for u in safe} == {"root", "bob"}
    assert all(u["has_password"] for u in safe)

    # 最近活跃：首次写入，10 分钟内不重复写
    auth.touch_seen(bob["id"])
    first = auth.get_user_raw(bob["id"])["last_seen_at"]
    assert first
    time.sleep(1.1)
    auth.touch_seen(bob["id"])
    assert auth.get_user_raw(bob["id"])["last_seen_at"] == first, "节流期内不写"
    print("1. 角色 / 上限 / 停用立即生效 / 重置密码 / 安全列表 / 最近活跃节流 ✓")
    return root, bob


def main() -> int:
    part_auth()
    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python tests/server/test_admin.py`
Expected: FAIL，`KeyError: 'role'`

- [ ] **Step 3: 实现**

在 `backend/server/auth.py` 中：

(a) 在 `_lock = threading.RLock()` 之后加：

```python
# 最近活跃：同一用户 10 分钟内最多写一次 users.json
SEEN_EVERY = 600
_seen_at: dict = {}
EDITABLE = ("role", "disabled", "monthly_cap_usd")
ROLES = ("admin", "user")
```

(b) 在 `_hash` 之前加：

```python
def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
```

并把 `register` 里的 `"created_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),` 改成 `"created_at": _now(),`。

(c) 替换 `_public`：

```python
def _public(u: dict) -> dict:
    return {"id": u["id"], "username": u["username"], "created_at": u["created_at"],
            "role": u.get("role") or "user", "disabled": bool(u.get("disabled"))}
```

(d) 替换 `authenticate`（停用账号在密码正确时才报「已停用」，密码错仍报「不正确」）：

```python
def authenticate(username: str, password: str) -> dict:
    users = _load_users()
    for u in users:
        if u["username"].lower() == (username or "").strip().lower():
            # compare_digest 防时序侧信道
            if u.get("password_hash") and hmac.compare_digest(
                    _hash(password or "", u["salt"]), u["password_hash"]):
                if u.get("disabled"):
                    raise AuthError("账号已停用")
                return _public(u)
            break
    raise AuthError("用户名或密码不正确")
```

(e) `verify_token` 最后一行 `return get_user(user_id)` 改为：

```python
    user = get_user(user_id)
    if user is None or user["disabled"]:
        return None      # 停用立即生效：token 自包含，但每次都回查用户
    return user
```

(f) 在 `issue_token` 之前加：

```python
def _safe(u: dict) -> dict:
    """给管理后台用的用户信息：去掉密码字段，补上 has_password。"""
    out = {k: v for k, v in u.items() if k not in ("salt", "password_hash")}
    out["role"] = u.get("role") or "user"
    out["disabled"] = bool(u.get("disabled"))
    out.setdefault("monthly_cap_usd", None)
    out.setdefault("last_seen_at", None)
    out["has_password"] = bool(u.get("password_hash"))
    return out


def get_user_raw(user_id: str) -> Optional[dict]:
    for u in _load_users():
        if u["id"] == user_id:
            return _safe(u)
    return None


def list_users_safe() -> list:
    return [_safe(u) for u in _load_users()]


def update_user(user_id: str, **fields) -> dict:
    """管理后台改账号字段；只允许 EDITABLE 里的键，约束在 admin.py 里检查。"""
    bad = set(fields) - set(EDITABLE)
    if bad:
        raise ValueError(f"不允许修改：{sorted(bad)}")
    with _lock:
        users = _load_users()
        u = next((x for x in users if x["id"] == user_id), None)
        if u is None:
            raise AuthError("用户不存在")
        u.update(fields)
        _save_users(users)
        return _safe(u)


def set_password(user_id: str, password: str) -> None:
    if len(password or "") < MIN_PASSWORD:
        raise AuthError(f"密码至少 {MIN_PASSWORD} 位")
    with _lock:
        users = _load_users()
        u = next((x for x in users if x["id"] == user_id), None)
        if u is None:
            raise AuthError("用户不存在")
        u["salt"] = secrets.token_hex(16)
        u["password_hash"] = _hash(password, u["salt"])
        _save_users(users)


def touch_seen(user_id: str) -> None:
    now = time.time()
    if now - _seen_at.get(user_id, 0) < SEEN_EVERY:
        return
    _seen_at[user_id] = now
    with _lock:
        users = _load_users()
        for u in users:
            if u["id"] == user_id:
                u["last_seen_at"] = _now()
                _save_users(users)
                return
```

- [ ] **Step 4: 跑测试确认通过，并防回归**

Run:
```bash
cd backend && .venv/bin/python tests/server/test_admin.py \
  && .venv/bin/python tests/server/test_novels.py \
  && .venv/bin/python tests/server/test_keyframes.py
```
Expected: 都以 `ALL PASS` 结束

- [ ] **Step 5: 提交**

```bash
git add backend/server/auth.py backend/tests/server/test_admin.py
git commit -m "账号字段：角色、停用（现有 token 立即失效）、月上限、最近活跃（10 分钟节流），管理用的安全用户列表与重置密码"
```

---

### Task 3: 审计、管理逻辑与命令行

**Files:**
- Create: `backend/server/audit.py`
- Create: `backend/server/admin.py`
- Modify: `backend/server/novels.py`（文件末尾加两个函数）
- Modify: `backend/tests/server/test_admin.py`

- [ ] **Step 1: 写失败测试**

在 `backend/tests/server/test_admin.py` 中：

(a) 导入行 `from server import auth  # noqa: E402` 改为：

```python
from server import admin, audit, auth, novels, pricing, usage  # noqa: E402
```

(b) 在 `def main()` 之前加：

```python
def part_admin(root, bob):
    me = auth.get_user_raw(root["id"])
    table = pricing.load()

    # 计数与标题：只读元数据
    nid = novels.create_novel(bob["id"], "药")["id"]
    cid = novels.create_chapter(bob["id"], nid, "第一章", text="原文很长")["id"]
    novels.create_version(bob["id"], nid, cid, "v1", {}, "原文很长")
    novels.update_version_state(bob["id"], nid, cid, "v1", "failed", error="E" * 500,
                                manifest={"attempts": [{"usage": {"calls": 2, "input": 10,
                                                                 "output": 20}}, {}],
                                          "contracts": {"model": "claude-sonnet-5"},
                                          "input": {"normalized_chars": 1234}})
    assert novels.counts(bob["id"]) == {"novels": 1, "chapters": 1, "versions": 1}
    assert novels.titles(bob["id"], nid, cid) == ("药", "第一章")
    assert novels.titles(bob["id"], "n_gone", None) == (None, None)

    usage.record(user_id=bob["id"], purpose="convert", model="claude-sonnet-5",
                 usage={"calls": 1, "input": 1_000_000}, ok=True, chars=2000,
                 novel_id=nid, chapter_id=cid, version_id="v0")

    # 用户行与详情：不含原文
    rows = {r["username"]: r for r in admin.user_rows(table)}
    b = rows["bob"]
    assert (b["novels"], b["chapters"], b["versions"]) == (1, 1, 1)
    assert abs(b["month_cost_usd"] - 2.0) < 1e-9
    d = admin.user_detail(bob["id"], table)
    assert d["recent"][0]["novel_title"] == "药" and d["recent"][0]["chapter_title"] == "第一章"
    assert abs(d["recent"][0]["cost_usd"] - 2.0) < 1e-9 and len(d["daily"]) == 30
    blob = json.dumps(d, ensure_ascii=False) + json.dumps(rows, ensure_ascii=False)
    assert "原文很长" not in blob, "后台不得返回原文"
    must_raise(admin.NotFound, admin.user_detail, "f" * 12, table)

    # 操作与约束
    must_raise(admin.AdminError, admin.patch_user, me, bob["id"], {"disabled": True, "role": "user"})
    must_raise(admin.AdminError, admin.patch_user, me, root["id"], {"disabled": True})
    must_raise(admin.AdminError, admin.patch_user, me, root["id"], {"role": "user"})
    must_raise(admin.AdminError, admin.patch_user, me, bob["id"], {"role": "boss"})
    must_raise(admin.AdminError, admin.patch_user, me, bob["id"], {"monthly_cap_usd": -1})
    must_raise(admin.AdminError, admin.patch_user, me, bob["id"], {"username": "x"})
    assert admin.patch_user(me, bob["id"], {"monthly_cap_usd": 3})["monthly_cap_usd"] == 3.0
    assert admin.patch_user(me, bob["id"], {"monthly_cap_usd": None})["monthly_cap_usd"] is None
    assert admin.patch_user(me, bob["id"], {"disabled": True})["disabled"] is True
    assert admin.patch_user(me, bob["id"], {"disabled": False})["disabled"] is False
    assert admin.patch_user(me, bob["id"], {"role": "admin"})["role"] == "admin"
    # bob 是管理员后由 bob 停用 root：root 不是最后一个管理员，可以
    bob_me = auth.get_user_raw(bob["id"])
    admin.patch_user(bob_me, root["id"], {"disabled": True})
    # 现在 bob 是唯一未停用的管理员；root（已停用）不能去掉 bob 的管理员——但 root 已停用、
    # 接口层根本进不来；这里直接验证「最后一个管理员」约束
    e = must_raise(admin.AdminError, admin._guard_last_admin, bob["id"])
    assert "至少保留一个管理员" in str(e)
    admin.patch_user(bob_me, root["id"], {"disabled": False})
    admin.reset_password(me, bob["id"], "another1")
    assert auth.authenticate("bob", "another1")["id"] == bob["id"]
    must_raise(admin.AdminError, admin.reset_password, me, bob["id"], "1")

    # 审计：每个成功操作都有一条，最新在前；重置密码不记密码
    log = audit.read(limit=100)
    actions = [a["action"] for a in log]
    assert actions[0] == "reset_password" and "another1" not in json.dumps(log)
    for want in ("set_cap", "disable", "enable", "grant_admin"):
        assert want in actions, want
    print("2. 计数与标题 / 用户行与详情不含原文 / 操作约束 / 审计 ✓")
    return nid, cid


def part_jobs_overview(root, bob, nid, cid):
    table = pricing.load()
    jobs = admin.jobs_view([{"id": "j1", "user_id": bob["id"], "status": "running",
                             "work_title": "药", "chapter": "第一章", "chars": 99,
                             "created_at": "2026-10-30T00:00:00+00:00"},
                            {"id": "j2", "user_id": bob["id"], "status": "succeeded",
                             "created_at": "2026-10-30T00:00:00+00:00"}])
    assert [j["id"] for j in jobs["running"]] == ["j1"] and jobs["running"][0]["username"] == "bob"
    f = jobs["failed"][0]
    assert f["id"] == "v1" and f["novel_title"] == "药" and f["attempts"] == 2
    assert f["chars"] == 1234 and len(f["error"]) == 300
    ov = admin.overview(table, running=1)
    assert ov["users"] == 2 and ov["running"] == 1 and ov["failed_7d"] == 1
    assert len(ov["daily"]) == 30 and ov["cost_30d"] > 0
    csv_text = admin.usage_csv(30, table)
    assert csv_text.splitlines()[0].startswith("at,user_id,username,purpose,model")
    assert ",bob," in csv_text
    rep = admin.usage_report("user", 30, table)
    assert rep["rows"][0]["label"] == "bob" and rep["per_k_chars"]["n"] == 1

    # 历史补导：从版本 manifest 生成记录，重复执行不重复
    r1 = admin.backfill_usage()
    assert r1["added"] == 1, r1
    r2 = admin.backfill_usage()
    assert r2["added"] == 0 and r2["existing"] == 1
    back = [r for r in usage.read() if r.get("version_id") == "v1"]
    assert back[0]["calls"] == 2 and back[0]["ok"] is False and back[0]["chars"] == 1234
    print("3. 任务（运行中 / 近期失败）/ 概览 / CSV / 用量报表 / 历史补导去重 ✓")


def part_cli():
    auth.register("carol", "secret1")
    assert admin.main(["promote", "carol"]) == 0
    assert auth.get_user_raw(next(u["id"] for u in auth.list_users_safe()
                                  if u["username"] == "carol"))["role"] == "admin"
    assert admin.main(["demote", "carol"]) == 0
    assert admin.main(["promote", "nobody"]) == 1
    assert admin.main(["list"]) == 0
    print("4. 命令行 promote / demote / list ✓")
```

(c) 把 `main()` 换成：

```python
def main() -> int:
    root, bob = part_auth()
    nid, cid = part_admin(root, bob)
    part_jobs_overview(root, bob, nid, cid)
    part_cli()
    print("\nALL PASS")
    return 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python tests/server/test_admin.py`
Expected: FAIL，`ImportError: cannot import name 'admin' from 'server'`

- [ ] **Step 3: `novels.py` 末尾加两个只读函数**

```python
# ---------- 管理后台用的只读元数据（不读原文、不读产物） ----------

def counts(user_id: str) -> dict:
    root = novels_dir(user_id)
    if not root.exists():
        return {"novels": 0, "chapters": 0, "versions": 0}
    return {"novels": sum(1 for _ in root.glob("*/novel.json")),
            "chapters": sum(1 for _ in root.glob("*/chapters/*/chapter.json")),
            "versions": sum(1 for _ in root.glob("*/chapters/*/versions/*.json"))}


def titles(user_id: str, nid: Optional[str], cid: Optional[str]) -> tuple:
    """(小说标题, 章节标题)；已删除或 id 非法返回 None。"""
    def title(path):
        data = _read(path)
        return data.get("title") if data else None
    try:
        novel = title(_novel_dir(user_id, nid) / "novel.json") if nid else None
        chapter = title(_chapter_dir(user_id, nid, cid) / "chapter.json") if nid and cid else None
    except (NovelError, ValueError):
        return None, None
    return novel, chapter
```

> `_check_id` 校验失败抛 `NovelError`（`ValueError` 的子类），由 `except` 接住。

- [ ] **Step 4: 实现 `backend/server/audit.py`**

```python
"""管理操作审计：追加写，最新在前读出。重置密码只记动作，不记密码。"""
import json
import threading
from typing import Optional

from server.auth import DATA_DIR
from server.store import now_iso

AUDIT_FILE = DATA_DIR / "admin_audit.jsonl"
_lock = threading.Lock()


def write(admin: dict, action: str, target: Optional[dict] = None,
          before: Optional[dict] = None, after: Optional[dict] = None) -> dict:
    row = {"at": now_iso(), "admin_id": admin["id"], "admin": admin["username"],
           "action": action,
           "target_id": (target or {}).get("id"), "target": (target or {}).get("username"),
           "before": before, "after": after}
    with _lock:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(AUDIT_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def read(limit: int = 200) -> list:
    if not AUDIT_FILE.exists():
        return []
    rows = []
    with open(AUDIT_FILE, encoding="utf-8") as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return list(reversed(rows))[:limit]
```

- [ ] **Step 5: 实现 `backend/server/admin.py`**

```python
"""管理后台的业务逻辑 + 命令行入口。

只读元数据：标题、数量、用量、状态、报错——不返回小说原文与分镜内容。
命令行：python -m server.admin promote|demote <用户名> / list / backfill-usage
"""
import csv
import io
import json
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

from pipeline.manifest import sum_usage
from server import audit, auth, novels, pricing, store, usage


class AdminError(Exception):
    """可预期的拒绝（400）。"""


class NotFound(AdminError):
    """目标不存在（404）。"""


PURPOSES = ("convert", "digest")
FAILED_DAYS = 7


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _user(user_id: str) -> dict:
    u = auth.get_user_raw(user_id)
    if u is None:
        raise NotFound("用户不存在")
    return u


def _row(u: dict, month_cost: float) -> dict:
    c = novels.counts(u["id"])
    return {"id": u["id"], "username": u["username"], "role": u["role"],
            "disabled": u["disabled"], "created_at": u.get("created_at"),
            "last_seen_at": u.get("last_seen_at"), "has_password": u["has_password"],
            "monthly_cap_usd": u.get("monthly_cap_usd"), **c,
            "month_cost_usd": month_cost}


def _month_costs(table: dict) -> dict:
    out: dict = {}
    for r in usage.read(since=usage.month_start()):
        out[r["user_id"]] = out.get(r["user_id"], 0.0) + (pricing.cost(r, table) or 0.0)
    return out


def user_rows(table: dict) -> list:
    costs = _month_costs(table)
    return [_row(u, costs.get(u["id"], 0.0)) for u in auth.list_users_safe()]


def user_detail(user_id: str, table: dict) -> dict:
    u = _user(user_id)
    rows = usage.read(user_id=user_id)
    recent = []
    for r in list(reversed(rows))[:50]:
        nt, ct = novels.titles(user_id, r.get("novel_id"), r.get("chapter_id"))
        recent.append({**r, "novel_title": nt, "chapter_title": ct,
                       "cost_usd": pricing.cost(r, table)})
    month = sum(pricing.cost(r, table) or 0.0 for r in rows
                if usage._when(r) >= usage.month_start())
    since = _now() - timedelta(days=30)
    return {"user": _row(u, month), "recent": recent,
            "daily": usage.daily_series([r for r in rows if usage._when(r) >= since],
                                        30, table)}


def _active_admins() -> list:
    return [u for u in auth.list_users_safe() if u["role"] == "admin" and not u["disabled"]]


def _guard_last_admin(user_id: str) -> None:
    """user_id 将失去管理权（降级或停用）时，系统里必须还有别的未停用管理员。"""
    others = [u for u in _active_admins() if u["id"] != user_id]
    if not others:
        raise AdminError("至少保留一个管理员")


def patch_user(admin_user: dict, user_id: str, body: dict) -> dict:
    if len(body) != 1:
        raise AdminError("一次只能修改一项")
    (field, value), = body.items()
    target = _user(user_id)
    self_edit = user_id == admin_user["id"]
    if field == "disabled":
        value = bool(value)
        if value and self_edit:
            raise AdminError("不能停用自己")
        if value and target["role"] == "admin":
            _guard_last_admin(user_id)
        action = "disable" if value else "enable"
    elif field == "role":
        if value not in auth.ROLES:
            raise AdminError("角色只能是 admin 或 user")
        if self_edit:
            raise AdminError("不能修改自己的角色")
        if value == "user" and target["role"] == "admin":
            _guard_last_admin(user_id)
        action = "grant_admin" if value == "admin" else "revoke_admin"
    elif field == "monthly_cap_usd":
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                raise AdminError("月上限必须是非负数，或留空表示不限")
            value = float(value)
        action = "set_cap"
    else:
        raise AdminError(f"不支持修改 {field}")
    before = {field: target.get(field)}
    auth.update_user(user_id, **{field: value})
    audit.write(admin_user, action, target, before, {field: value})
    return _row(_user(user_id), _month_costs(pricing.load()).get(user_id, 0.0))


def reset_password(admin_user: dict, user_id: str, password: str) -> None:
    target = _user(user_id)
    try:
        auth.set_password(user_id, password)
    except auth.AuthError as e:
        raise AdminError(str(e))
    audit.write(admin_user, "reset_password", target)


def _version_files():
    users_root = auth.DATA_DIR / "users"
    if not users_root.exists():
        return
    for udir in users_root.iterdir():
        if not udir.is_dir():
            continue
        for path in novels.novels_dir(udir.name).glob("*/chapters/*/versions/*.json"):
            try:
                yield udir.name, json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue


def jobs_view(memory_jobs: list) -> dict:
    names = {u["id"]: u["username"] for u in auth.list_users_safe()}
    now = _now()
    running = []
    for j in memory_jobs:
        if j.get("status") not in ("queued", "running"):
            continue
        started = j.get("created_at")
        elapsed = None
        if started:
            elapsed = int((now - datetime.fromisoformat(started)).total_seconds())
        running.append({"id": j["id"], "user_id": j.get("user_id"),
                        "username": names.get(j.get("user_id")), "status": j["status"],
                        "work_title": j.get("work_title"), "chapter": j.get("chapter"),
                        "chars": j.get("chars"), "created_at": started,
                        "elapsed_sec": elapsed})
    since = now - timedelta(days=FAILED_DAYS)
    failed = []
    for uid, v in _version_files():
        if v.get("status") != "failed" or not v.get("created_at"):
            continue
        if datetime.fromisoformat(v["created_at"]) < since:
            continue
        m = v.get("manifest") or {}
        nt, ct = novels.titles(uid, v.get("novel_id"), v.get("chapter_id"))
        failed.append({"id": v["id"], "user_id": uid, "username": names.get(uid),
                       "novel_title": nt, "chapter_title": ct,
                       "created_at": v["created_at"],
                       "chars": (m.get("input") or {}).get("normalized_chars")
                       or len(v.get("input_text") or ""),
                       "attempts": len(m.get("attempts") or []),
                       "error": (v.get("error") or "")[:300]})
    failed.sort(key=lambda x: x["created_at"], reverse=True)
    return {"running": running, "failed": failed}


def overview(table: dict, running: int) -> dict:
    now = _now()
    users = auth.list_users_safe()
    week = now - timedelta(days=7)
    active = sum(1 for u in users
                 if u.get("last_seen_at") and datetime.fromisoformat(u["last_seen_at"]) >= week)
    rows = usage.read(since=now - timedelta(days=30))
    tokens = sum(r.get(k) or 0 for r in rows
                 for k in ("input", "output", "cache_read", "cache_write"))
    cost = sum(pricing.cost(r, table) or 0.0 for r in rows)
    return {"users": len(users), "active_7d": active, "tokens_30d": tokens,
            "cost_30d": cost, "running": running,
            "failed_7d": len(jobs_view([])["failed"]),
            "daily": usage.daily_series(rows, 30, table, now=now),
            "unpriced_models": usage.unpriced_models(rows, table)}


def usage_report(group: str, days: int, table: dict) -> dict:
    rows = usage.read(since=_now() - timedelta(days=days))
    try:
        groups = usage.aggregate(rows, group, table)
    except ValueError as e:
        raise AdminError(str(e))
    names = {u["id"]: u["username"] for u in auth.list_users_safe()}
    for g in groups:
        g["label"] = names.get(g["key"], g["key"]) if group == "user" else g["key"]
    return {"group": group, "days": days, "rows": groups,
            "per_k_chars": usage.per_k_chars(rows, table),
            "unpriced_models": usage.unpriced_models(rows, table)}


CSV_FIELDS = ("at", "user_id", "username", "purpose", "model", "ok", "calls", "input",
              "output", "cache_read", "cache_write", "chars", "cost_usd")


def usage_csv(days: int, table: dict) -> str:
    names = {u["id"]: u["username"] for u in auth.list_users_safe()}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_FIELDS)
    for r in usage.read(since=_now() - timedelta(days=days)):
        c = pricing.cost(r, table)
        w.writerow([r["at"], r.get("user_id"), names.get(r.get("user_id"), ""),
                    r.get("purpose"), r.get("model"), r.get("ok"), r.get("calls"),
                    r.get("input"), r.get("output"), r.get("cache_read"),
                    r.get("cache_write"), r.get("chars"),
                    "" if c is None else f"{c:.6f}"])
    return buf.getvalue()


def backfill_usage() -> dict:
    """从已有版本记录补导转换用量；按 (user_id, version_id, purpose) 去重，重复执行安全。"""
    seen = {(r.get("user_id"), r.get("version_id"), r.get("purpose")) for r in usage.read()}
    added = existing = skipped = 0
    for uid, v in _version_files():
        key = (uid, v.get("id"), "convert")
        if key in seen:
            existing += 1
            continue
        m = v.get("manifest") or {}
        totals = m.get("usage") or (sum_usage(m["attempts"]) if m.get("attempts") else None)
        if not totals or not any(totals.get(k) for k in usage.TOKENS):
            skipped += 1
            continue
        usage.record(user_id=uid, purpose="convert",
                     model=(m.get("contracts") or {}).get("model") or "unknown",
                     usage=totals,
                     ok=v.get("status") in ("succeeded", "completed_with_warnings"),
                     chars=(m.get("input") or {}).get("normalized_chars")
                     or len(v.get("input_text") or ""),
                     novel_id=v.get("novel_id"), chapter_id=v.get("chapter_id"),
                     version_id=v.get("id"), at=v.get("created_at") or store.now_iso())
        seen.add(key)
        added += 1
    return {"added": added, "existing": existing, "skipped_no_usage": skipped}


def _find(username: str) -> Optional[dict]:
    return next((u for u in auth.list_users_safe()
                 if u["username"].lower() == username.lower()), None)


def main(argv: list) -> int:
    if not argv or argv[0] not in ("promote", "demote", "list", "backfill-usage"):
        print("用法: python -m server.admin promote|demote <用户名> | list | backfill-usage")
        return 2
    cmd = argv[0]
    if cmd == "list":
        for u in auth.list_users_safe():
            flag = " [停用]" if u["disabled"] else ""
            print(f"{u['id']}  {u['role']:5}  {u['username']}{flag}")
        return 0
    if cmd == "backfill-usage":
        print(backfill_usage())
        return 0
    if len(argv) < 2:
        print("缺少用户名")
        return 2
    u = _find(argv[1])
    if u is None:
        print(f"找不到用户：{argv[1]}")
        return 1
    if cmd == "demote" and u["role"] == "admin":
        try:
            _guard_last_admin(u["id"])
        except AdminError as e:
            print(e)
            return 1
    auth.update_user(u["id"], role="admin" if cmd == "promote" else "user")
    print(f"{u['username']} → {'admin' if cmd == 'promote' else 'user'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 6: 跑测试确认通过，并防回归**

Run:
```bash
cd backend && .venv/bin/python tests/server/test_admin.py \
  && .venv/bin/python tests/server/test_usage.py \
  && .venv/bin/python tests/server/test_novels.py
```
Expected: 都以 `ALL PASS` 结束

- [ ] **Step 7: 提交**

```bash
git add backend/server/audit.py backend/server/admin.py backend/server/novels.py backend/tests/server/test_admin.py
git commit -m "管理逻辑：用户行与详情（只读元数据）、停用/角色/月上限约束与审计、运行中与近期失败任务、概览、用量报表与 CSV、历史用量补导，命令行 promote/demote/list/backfill-usage"
```

---

### Task 4: 接口、落账与月上限

**Files:**
- Modify: `backend/server/app.py`
- Modify: `docs/specs/2026-10-29-admin-console-design.md`（两处裁定）
- Modify: `backend/tests/server/test_admin.py`

- [ ] **Step 1: 写失败测试**

在 `backend/tests/server/test_admin.py` 的 `def main()` 之前加：

```python
def part_api():
    from fastapi.testclient import TestClient
    from server import app as app_mod

    c = TestClient(app_mod.app)
    users = {u["username"]: u for u in auth.list_users_safe()}
    root_tok = auth.issue_token(users["root"]["id"])
    carol_tok = auth.issue_token(users["carol"]["id"])
    H = {"Authorization": f"Bearer {root_tok}"}

    # 权限：普通用户 403，未登录 401
    assert c.get("/admin/overview", headers={"Authorization": f"Bearer {carol_tok}"}).status_code == 403
    assert c.get("/admin/overview").status_code == 401
    assert c.get("/auth/me", headers=H).json()["role"] == "admin"

    # 只读接口
    assert c.get("/admin/overview", headers=H).json()["users"] == 3
    rows = c.get("/admin/users", headers=H).json()["users"]
    assert {r["username"] for r in rows} == {"root", "bob", "carol"}
    assert "原文很长" not in json.dumps(rows, ensure_ascii=False)
    bob_id = users["bob"]["id"]
    assert c.get(f"/admin/users/{bob_id}", headers=H).json()["user"]["username"] == "bob"
    assert c.get("/admin/users/ffffffffffff", headers=H).status_code == 404
    assert c.get("/admin/usage?group=day&days=7", headers=H).json()["group"] == "day"
    assert c.get("/admin/usage?group=bogus&days=7", headers=H).status_code == 400
    assert c.get("/admin/usage?group=user&days=5", headers=H).status_code == 422
    r = c.get("/admin/usage.csv?days=30", headers=H)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "failed" in c.get("/admin/jobs", headers=H).json()
    assert c.get("/admin/audit", headers=H).json()["audit"][0]["action"]

    # 操作：停用后对方 token 立即 401、不能登录；启用恢复
    carol_id = users["carol"]["id"]
    assert c.patch(f"/admin/users/{carol_id}", json={"disabled": True}, headers=H).status_code == 200
    assert c.get("/auth/me", headers={"Authorization": f"Bearer {carol_tok}"}).status_code == 401
    r = c.post("/auth/login", json={"username": "carol", "password": "secret1"})
    assert r.status_code == 401 and r.json()["detail"] == "账号已停用"
    c.patch(f"/admin/users/{carol_id}", json={"disabled": False}, headers=H)
    assert c.patch(f"/admin/users/{users['root']['id']}", json={"disabled": True},
                   headers=H).status_code == 400
    assert c.post(f"/admin/users/{carol_id}/password", json={"password": "freshpw1"},
                  headers=H).json() == {"ok": True}
    assert c.post("/auth/login", json={"username": "carol", "password": "freshpw1"}).status_code == 200

    # 价格表
    t = c.get("/admin/pricing", headers=H).json()
    t["models"]["mystery"] = {"input": 1, "output": 1, "cache_read": 0, "cache_write": 0}
    assert c.put("/admin/pricing", json=t, headers=H).status_code == 200
    assert "mystery" in c.get("/admin/pricing", headers=H).json()["models"]
    bad = {"models": {"m": {"input": -1}}}
    assert c.put("/admin/pricing", json=bad, headers=H).status_code == 400
    assert c.get("/admin/audit", headers=H).json()["audit"][0]["action"] == "update_pricing"

    # 月上限：上限 0 时提交转换被拒 429（不会真的启动转换）
    carol = auth.get_user_raw(carol_id)
    nid = novels.create_novel(carol_id, "孔乙己")["id"]
    cid = novels.create_chapter(carol_id, nid, "一", text="正文")["id"]
    c.patch(f"/admin/users/{carol_id}", json={"monthly_cap_usd": 0}, headers=H)
    carol_tok = auth.issue_token(carol_id)
    r = c.post(f"/novels/{nid}/chapters/{cid}/versions", json={},
               headers={"Authorization": f"Bearer {carol_tok}"})
    assert r.status_code == 429 and "本月用量已达上限" in r.json()["detail"], r.text
    assert carol["username"] == "carol"

    # 落账：章后整理调用后写一条 digest 记录
    from pipeline.chat import UsageCallback

    class FakeDigestChat:
        usage = UsageCallback()

        def usage_totals(self):
            return {"calls": 1, "input": 5, "output": 7, "cache_read": 0, "cache_write": 0}

    app_mod._record_chat_usage(carol_id, nid, cid, FakeDigestChat(), ok=True)
    last = usage.read(user_id=carol_id)[-1]
    assert last["purpose"] == "digest" and last["output"] == 7 and last["chapter_id"] == cid

    # 落账：转换结束（成功与失败都记；没有调用不记）
    job = {"id": "vx", "user_id": carol_id, "novel_id": nid, "chapter_id": cid,
           "version_id": "vx", "chars": 2}
    manifest = {"attempts": [{"usage": {"calls": 1, "input": 3, "output": 4}}],
                "contracts": {"model": "claude-sonnet-5"}, "input": {"normalized_chars": 2}}
    before = len(usage.read())
    app_mod._record_usage(job, manifest, ok=False)
    app_mod._record_usage(job, {"attempts": []}, ok=True)
    after = usage.read()
    assert len(after) == before + 1 and after[-1]["ok"] is False and after[-1]["input"] == 3
    print("5. 接口权限 / 只读接口 / 停用即时生效 / 重置密码 / 价格表 / 月上限 429 / 落账 ✓")
```

并在 `main()` 里 `part_cli()` 之后加一行 `part_api()`。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python tests/server/test_admin.py`
Expected: FAIL，第 5 段 `/admin/overview` 返回 404 而不是 403

- [ ] **Step 3: 实现**

在 `backend/server/app.py` 中：

(a) 导入：`from server import auth, library, novels, store` 改为

```python
from server import admin as admin_mod
from server import audit, auth, library, novels, pricing, store, usage
```

并在其他 `from pipeline...` 导入附近加 `from pipeline.manifest import sum_usage`。把 `from fastapi import Body, Depends, FastAPI, Header, HTTPException, Request` 改成：

```python
from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, Request, Response
```

(b) 替换 `current_user`，并在其后加 `admin_user`：

```python
def current_user(authorization: str = Header(default="")) -> dict:
    """所有业务接口的守门人：没有合法 token 就看不到任何数据。"""
    token = authorization[7:] if authorization.lower().startswith("bearer ") else ""
    user = auth.verify_token(token)
    if user is None:
        raise HTTPException(401, "未登录或登录已过期")
    auth.touch_seen(user["id"])
    return user


def admin_user(user: dict = Depends(current_user)) -> dict:
    """管理接口的守门人：前端隐藏入口只是体验，权限以这里为准。"""
    if user.get("role") != "admin":
        raise HTTPException(403, "需要管理员权限")
    return user
```

(c) 在 `def _execute(` 之前加落账函数：

```python
def _record_usage(job: dict, manifest: dict, ok: bool, settings=None) -> None:
    """一次转换落一行用量（成功、失败都记；一次模型调用都没有就不记）。

    评审与转换共用一个用量回调，分不出模型：评审换了模型时整笔记在转换模型名下，
    并标 mixed_models，后台据此提示「金额按转换模型估算」。
    """
    totals = sum_usage((manifest or {}).get("attempts") or [])
    if not totals.get("calls"):
        return
    model = ((manifest or {}).get("contracts") or {}).get("model") \
        or (settings.model if settings else load_settings().model)
    mixed = None
    if settings is not None and settings.review_enabled and settings.review_model \
            and settings.review_model != model:
        mixed = [model, settings.review_model]
    try:
        usage.record(user_id=job["user_id"], purpose="convert", model=model, usage=totals,
                     ok=ok, chars=((manifest or {}).get("input") or {}).get("normalized_chars")
                     or job.get("chars") or 0,
                     novel_id=job.get("novel_id"), chapter_id=job.get("chapter_id"),
                     version_id=job.get("version_id") or job.get("id"), mixed_models=mixed)
    except OSError as e:
        print(f"[usage] 落账失败：{e!r}", flush=True)


def _record_chat_usage(user_id: str, nid: str, cid: str, chat, ok: bool) -> None:
    totals_fn = getattr(chat, "usage_totals", None)
    if totals_fn is None:
        return
    totals = totals_fn()
    if not totals.get("calls"):
        return
    try:
        usage.record(user_id=user_id, purpose="digest", model=load_settings().model,
                     usage=totals, ok=ok, novel_id=nid, chapter_id=cid)
    except OSError as e:
        print(f"[usage] 落账失败：{e!r}", flush=True)
```

(d) 在 `_execute` 里落账三处：

- 成功分支：`job["persisted"] = save(...)` 那条语句之后加 `_record_usage(job, manifest, True, settings)`
- `except ConversionError as e:` 分支末尾（`save("failed", ...)` 之后）加 `_record_usage(job, manifest, False, settings)`
- `except Exception as e:` 分支末尾（`save("failed", ...)` 之后）加 `_record_usage(job, manifest, False, settings)`

(e) 替换 `_run_digest`：

```python
def _run_digest(user_id: str, nid: str, cid: str) -> None:
    """采用版本后的一次小调用：生命周期提议 + 本章摘要。失败只记在章节上，
    不影响已经采用的版本——这是锦上添花，人可以手动补。"""
    chat, ok = None, False
    try:
        vid, units, characters = novels.digest_input(user_id, nid, cid)
        chat = _digest_chat()
        proposals, synopsis, dropped = novel_memory.run_digest(chat, units, characters)
        novels.record_digest(user_id, nid, cid, vid, proposals, synopsis, dropped)
        ok = True
    except Exception as e:  # 网络/解析/章节被删——都只是这一步没做成
        try:
            novels.set_digest_state(user_id, nid, cid, "failed", error=repr(e)[:300])
        except (OSError, ValueError, LookupError):
            pass
    finally:
        if chat is not None:
            _record_chat_usage(user_id, nid, cid, chat, ok)
```

(f) 在 `versions_create` 里，`text = chapter.get("text") or ""` 的非空检查之后、`merged = ...` 之前加月上限检查：

```python
    raw = auth.get_user_raw(user["id"])
    cap = raw.get("monthly_cap_usd") if raw else None
    if cap is not None and usage.month_spent(user["id"], pricing.load()) >= cap:
        raise HTTPException(429, "本月用量已达上限，请联系管理员")
```

(g) 文件末尾（或 `/healthz` 之前）加管理接口：

```python
# ---------- 管理后台 ----------

class AdminPatch(BaseModel):
    disabled: Optional[bool] = None
    role: Optional[str] = None
    monthly_cap_usd: Optional[float] = None


class AdminPassword(BaseModel):
    password: str = Field(..., min_length=1)


def _admin_call(fn, *args):
    try:
        return fn(*args)
    except admin_mod.NotFound as e:
        raise HTTPException(404, str(e))
    except admin_mod.AdminError as e:
        raise HTTPException(400, str(e))


def _running_jobs() -> list:
    with _lock:
        return [dict(j) for j in _jobs.values()]


@app.get("/admin/overview")
def admin_overview(user: dict = Depends(admin_user)):
    running = sum(1 for j in _running_jobs() if j.get("status") in ("queued", "running"))
    return admin_mod.overview(pricing.load(), running)


@app.get("/admin/users")
def admin_users(user: dict = Depends(admin_user)):
    return {"users": admin_mod.user_rows(pricing.load())}


@app.get("/admin/users/{uid}")
def admin_user_detail(uid: str, user: dict = Depends(admin_user)):
    return _admin_call(admin_mod.user_detail, uid, pricing.load())


@app.patch("/admin/users/{uid}")
def admin_patch_user(uid: str, body: AdminPatch, user: dict = Depends(admin_user)):
    # 只取请求里真正带了的字段：「设为不限」要传 null，不能和「没传」混为一谈
    fields = body.model_dump(exclude_unset=True)
    return _admin_call(admin_mod.patch_user, user, uid, fields)


@app.post("/admin/users/{uid}/password")
def admin_reset_password(uid: str, body: AdminPassword, user: dict = Depends(admin_user)):
    _admin_call(admin_mod.reset_password, user, uid, body.password)
    return {"ok": True}


@app.get("/admin/usage")
def admin_usage(group: str = "user", days: int = Query(30),
                user: dict = Depends(admin_user)):
    if days not in (7, 30, 90):
        raise HTTPException(422, "days 只能是 7、30、90")
    return _admin_call(admin_mod.usage_report, group, days, pricing.load())


@app.get("/admin/usage.csv")
def admin_usage_csv(days: int = Query(30), user: dict = Depends(admin_user)):
    if days not in (7, 30, 90):
        raise HTTPException(422, "days 只能是 7、30、90")
    return Response(admin_mod.usage_csv(days, pricing.load()), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="usage-{days}d.csv"'})


@app.get("/admin/jobs")
def admin_jobs(user: dict = Depends(admin_user)):
    return admin_mod.jobs_view(_running_jobs())


@app.get("/admin/audit")
def admin_audit(limit: int = Query(200, ge=1, le=1000), user: dict = Depends(admin_user)):
    return {"audit": audit.read(limit)}


@app.get("/admin/pricing")
def admin_pricing(user: dict = Depends(admin_user)):
    return pricing.load()


@app.put("/admin/pricing")
def admin_pricing_put(table: dict = Body(...), user: dict = Depends(admin_user)):
    before = pricing.load()
    try:
        saved = pricing.save(table)
    except ValueError as e:
        raise HTTPException(400, str(e))
    audit.write(user, "update_pricing", None, {"models": before.get("models")},
                {"models": saved["models"]})
    return saved
```

> `Body`、`Optional`、`BaseModel`、`Field` 在 `app.py` 里已有导入。

(h) 同步 spec 两处裁定：在 `docs/specs/2026-10-29-admin-console-design.md` 第 2.1 节「落账时机 → 转换」那条里，把「评审若用另一个模型，按模型拆成两行」改为：「评审与转换共用一个用量回调、分不出模型：评审换了模型时整笔记在转换模型名下，并加 `mixed_models: [转换模型, 评审模型]`，后台提示金额按转换模型估算」。第 4 节 `/admin/jobs` 一行把「耗时」改为「运行中任务的已运行时长（失败任务没有结束时间，只给开始时间）」。

- [ ] **Step 4: 跑测试确认通过，并防回归**

Run:
```bash
cd backend && for t in tests/server/test_*.py; do .venv/bin/python $t || break; done
```
Expected: 每个文件 `ALL PASS`

- [ ] **Step 5: 提交**

```bash
git add backend/server/app.py backend/tests/server/test_admin.py docs/specs/2026-10-29-admin-console-design.md
git commit -m "管理接口：/admin 概览/用户/用量/CSV/任务/审计/价格表与停用、角色、月上限、重置密码；转换与章后整理结束落账，月上限超出时拒绝提交（429）"
```

---

### Task 5: 前端类型、接口与公共件

**Files:**
- Modify: `frontend/src/auth.ts`
- Modify: `frontend/src/types.ts`（文件末尾）
- Modify: `frontend/src/api.ts`（文件末尾）
- Create: `frontend/src/components/admin/format.ts`
- Create: `frontend/src/components/admin/useLoad.ts`
- Create: `frontend/src/components/admin/LineChart.tsx`

纯类型与工具，由 Task 6–9 的界面测试覆盖；本任务以类型检查为准。

- [ ] **Step 1: `auth.ts`**

`export interface User` 里 `created_at: string` 之后加：

```ts
  /** 管理员才显示「管理」入口；权限以后端为准 */
  role?: 'admin' | 'user'
```

- [ ] **Step 2: `types.ts` 末尾追加**

```ts
/* ---------- 管理后台 ---------- */

export interface AdminUserRow {
  id: string
  username: string
  role: 'admin' | 'user'
  disabled: boolean
  created_at: string | null
  last_seen_at: string | null
  has_password: boolean
  monthly_cap_usd: number | null
  novels: number
  chapters: number
  versions: number
  month_cost_usd: number
}

export interface UsageEntry {
  at: string
  user_id: string
  novel_id: string | null
  chapter_id: string | null
  version_id: string | null
  purpose: string
  model: string
  ok: boolean
  calls: number
  input: number
  output: number
  cache_read: number
  cache_write: number
  chars: number
  mixed_models?: string[]
}

export interface DailyCost {
  day: string
  cost_usd: number
}

export interface AdminUserDetail {
  user: AdminUserRow
  recent: (UsageEntry & { novel_title: string | null; chapter_title: string | null;
                          cost_usd: number | null })[]
  daily: DailyCost[]
}

export interface AdminOverview {
  users: number
  active_7d: number
  tokens_30d: number
  cost_30d: number
  running: number
  failed_7d: number
  daily: DailyCost[]
  unpriced_models: string[]
}

export interface UsageGroupRow {
  key: string
  label: string
  calls: number
  input: number
  output: number
  cache_read: number
  cache_write: number
  chars: number
  cost_usd: number
  unpriced: number
}

export interface UsageReport {
  group: 'user' | 'day' | 'model'
  days: number
  rows: UsageGroupRow[]
  per_k_chars: { n: number; mean: number | null; p90: number | null }
  unpriced_models: string[]
}

export interface AdminJobs {
  running: { id: string; username: string | null; status: string; work_title: string | null;
             chapter: string | null; chars: number | null; created_at: string | null;
             elapsed_sec: number | null }[]
  failed: { id: string; username: string | null; novel_title: string | null;
            chapter_title: string | null; created_at: string; chars: number;
            attempts: number; error: string }[]
}

export interface AuditEntry {
  at: string
  admin: string
  action: string
  target: string | null
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
}

export interface PricingTable {
  currency: string
  note?: string
  updated_at: string | null
  models: Record<string, { input: number; output: number; cache_read: number; cache_write: number }>
}
```

- [ ] **Step 3: `api.ts`**

在顶部 `import type {...} from './types'` 的列表里补上 `AdminJobs, AdminOverview, AdminUserDetail, AdminUserRow, AuditEntry, PricingTable, UsageReport`。文件末尾追加：

```ts
/* ---------- 管理后台 ---------- */

export function adminOverview() {
  return req<AdminOverview>('/admin/overview')
}

export async function adminUsers(): Promise<AdminUserRow[]> {
  return (await req<{ users: AdminUserRow[] }>('/admin/users')).users
}

export function adminUser(id: string) {
  return req<AdminUserDetail>(`/admin/users/${encodeURIComponent(id)}`)
}

export function adminPatchUser(id: string,
  patch: { disabled: boolean } | { role: 'admin' | 'user' } | { monthly_cap_usd: number | null }) {
  return req<AdminUserRow>(`/admin/users/${encodeURIComponent(id)}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(patch),
  })
}

export function adminResetPassword(id: string, password: string) {
  return req<{ ok: boolean }>(`/admin/users/${encodeURIComponent(id)}/password`,
    jsonPost({ password }))
}

export function adminUsage(group: 'user' | 'day' | 'model', days: number) {
  return req<UsageReport>(`/admin/usage?group=${group}&days=${days}`)
}

export async function adminUsageCsv(days: number): Promise<string> {
  return (await send(`/admin/usage.csv?days=${days}`)).text()
}

export function adminJobs() {
  return req<AdminJobs>('/admin/jobs')
}

export async function adminAudit(): Promise<AuditEntry[]> {
  return (await req<{ audit: AuditEntry[] }>('/admin/audit')).audit
}

export function adminPricing() {
  return req<PricingTable>('/admin/pricing')
}

export function adminSavePricing(table: unknown) {
  return req<PricingTable>('/admin/pricing', {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(table),
  })
}
```

- [ ] **Step 4: `components/admin/format.ts`**

```ts
/** 管理后台的显示格式：金额两位小数美元，token 千分位，时间到分钟（UTC 原样）。 */
export const usd = (n: number | null | undefined) => (n == null ? '—' : `$${n.toFixed(2)}`)
export const usd4 = (n: number | null | undefined) => (n == null ? '—' : `$${n.toFixed(4)}`)
export const int = (n: number | null | undefined) => (n == null ? '—' : n.toLocaleString('en-US'))
export const day = (iso?: string | null) => (iso ? iso.slice(0, 10) : '—')
export const when = (iso?: string | null) => (iso ? iso.slice(0, 16).replace('T', ' ') : '—')
export const PURPOSE: Record<string, string> = { convert: '转换', digest: '章后整理' }
export const ACTION: Record<string, string> = {
  disable: '停用', enable: '启用', set_cap: '设月上限', reset_password: '重置密码',
  grant_admin: '设为管理员', revoke_admin: '取消管理员', update_pricing: '修改价格表',
}
export const errText = (e: unknown) => (e instanceof Error ? e.message : String(e))
```

- [ ] **Step 5: `components/admin/useLoad.ts`**

```ts
import { useEffect, useState } from 'react'
import { errText } from './format'

/** 拉一次数据；everyMs 给了就定时刷新；reload() 手动刷新。 */
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[], everyMs?: number) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [tick, setTick] = useState(0)

  useEffect(() => {
    let alive = true
    fn().then((d) => { if (alive) { setData(d); setError(null) } })
      .catch((e: unknown) => { if (alive) setError(errText(e)) })
    return () => { alive = false }
    // fn 每次渲染都是新闭包，依赖由调用方给出
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick])

  useEffect(() => {
    if (!everyMs) return
    const t = window.setInterval(() => setTick((x) => x + 1), everyMs)
    return () => clearInterval(t)
  }, [everyMs])

  return { data, error, reload: () => setTick((x) => x + 1) }
}
```

- [ ] **Step 6: `components/admin/LineChart.tsx`**

```tsx
import { usd } from './format'

interface Props {
  points: { label: string; value: number }[]
  height?: number
  label?: string
}

/** 手写 SVG 折线图：纵轴 0 到最大值，只标首尾日期与最大值。 */
export function LineChart({ points, height = 140, label = '每日金额' }: Props) {
  if (!points.length) return <p className="adm__empty">暂无数据</p>
  const W = 640
  const P = { l: 52, r: 12, t: 12, b: 24 }
  const max = Math.max(...points.map((p) => p.value), 0) || 1
  const x = (i: number) =>
    P.l + (points.length === 1 ? 0 : (i * (W - P.l - P.r)) / (points.length - 1))
  const y = (v: number) => P.t + (1 - v / max) * (height - P.t - P.b)
  const d = points.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(p.value).toFixed(1)}`).join('')
  return (
    <svg className="adm__chart" viewBox={`0 0 ${W} ${height}`} role="img" aria-label={label}>
      <line className="adm__axis" x1={P.l} x2={W - P.r} y1={height - P.b} y2={height - P.b} />
      <text className="adm__tick" x={P.l - 6} y={P.t + 4} textAnchor="end">{usd(max)}</text>
      <text className="adm__tick" x={P.l - 6} y={height - P.b} textAnchor="end">$0</text>
      <path className="adm__line" d={d} fill="none" />
      {points.map((p, i) => (
        <circle key={p.label} className="adm__dot" cx={x(i)} cy={y(p.value)} r={2.5}>
          <title>{`${p.label} ${usd(p.value)}`}</title>
        </circle>
      ))}
      <text className="adm__tick" x={P.l} y={height - 6}>{points[0].label}</text>
      <text className="adm__tick" x={W - P.r} y={height - 6} textAnchor="end">
        {points[points.length - 1].label}
      </text>
    </svg>
  )
}
```

- [ ] **Step 7: 类型检查**

Run: `cd frontend && npx tsc -b --force`
Expected: 无输出、退出码 0（若项目的 lint 规则名不同导致 `eslint-disable` 注释报未知规则，删掉那行注释即可，`tsc` 不受影响）

- [ ] **Step 8: 提交**

```bash
git add frontend/src/auth.ts frontend/src/types.ts frontend/src/api.ts frontend/src/components/admin/format.ts frontend/src/components/admin/useLoad.ts frontend/src/components/admin/LineChart.tsx
git commit -m "管理后台前端基础：类型与 /admin 接口函数、金额与时间格式、拉取与定时刷新、手写 SVG 折线图"
```

---

### Task 6: 概览页签

**Files:**
- Create: `frontend/src/components/admin/Overview.tsx`
- Create: `frontend/tests/admin.test.tsx`
- Modify: `frontend/package.json`
- Modify: `frontend/src/index.css`（文件末尾）

- [ ] **Step 1: 写失败测试**

Create `frontend/tests/admin.test.tsx`:

```tsx
/** 管理后台的界面回归：概览、用户（排序/搜索/操作）、用量、任务、审计，以及入口。
 *  用桩后端代替 /admin 接口。
 *
 *  跑法：npm test
 */
import { Window } from 'happy-dom'

const win = new Window({ url: 'http://localhost:5173' })
const g = globalThis as Record<string, unknown>
for (const k of ['window', 'document', 'navigator', 'location', 'HTMLElement',
                 'Element', 'Node', 'Event', 'CustomEvent', 'getComputedStyle',
                 'localStorage', 'sessionStorage']) {
  Object.defineProperty(g, k, {
    value: (win as unknown as Record<string, unknown>)[k],
    writable: true, configurable: true,
  })
}
g.IS_REACT_ACT_ENVIRONMENT = true
const confirms: string[] = []
;(win as unknown as Record<string, unknown>).confirm = (m: string) => { confirms.push(m); return true }
g.confirm = (win as unknown as Record<string, unknown>).confirm

/* ---------- 桩后端 ---------- */
const calls: string[] = []
const daily = Array.from({ length: 30 }, (_, i) => ({
  day: `2026-10-${String(i + 1).padStart(2, '0')}`, cost_usd: i === 29 ? 4.5 : 0 }))
const users = [
  { id: 'u-root', username: 'root', role: 'admin', disabled: false, created_at: '2026-10-01T00:00:00+00:00',
    last_seen_at: '2026-10-30T08:00:00+00:00', has_password: true, monthly_cap_usd: null,
    novels: 0, chapters: 0, versions: 0, month_cost_usd: 0 },
  { id: 'u-bob', username: 'bob', role: 'user', disabled: false, created_at: '2026-10-05T00:00:00+00:00',
    last_seen_at: null, has_password: true, monthly_cap_usd: 5,
    novels: 2, chapters: 3, versions: 4, month_cost_usd: 4.5 },
  { id: 'u-amy', username: 'amy', role: 'user', disabled: false, created_at: '2026-10-09T00:00:00+00:00',
    last_seen_at: null, has_password: false, monthly_cap_usd: null,
    novels: 1, chapters: 1, versions: 1, month_cost_usd: 9 },
]
g.fetch = async (url: string, init?: { method?: string; body?: string }) => {
  const path = String(url).replace(/^\/api/, '')
  const method = init?.method ?? 'GET'
  calls.push(`${method} ${path}${init?.body ? ' ' + init.body : ''}`)
  const json = (data: unknown) => ({ ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(data)),
                                     text: async () => JSON.stringify(data) })
  const err = (status: number, detail: string) => ({
    ok: false, status, text: async () => JSON.stringify({ detail }), json: async () => ({ detail }) })
  if (path === '/admin/overview') return json({ users: 3, active_7d: 1, tokens_30d: 1234567,
    cost_30d: 13.5, running: 1, failed_7d: 2, daily, unpriced_models: ['mystery'] })
  if (path === '/admin/users') return json({ users })
  const m = path.match(/^\/admin\/users\/([^/]+)(\/password)?$/)
  if (m && method === 'GET') {
    const u = users.find((x) => x.id === m[1])!
    return json({ user: u, daily, recent: [{ at: '2026-10-30T08:00:00+00:00', user_id: u.id,
      novel_id: 'n1', chapter_id: 'c1', version_id: 'v1', purpose: 'convert', model: 'claude-sonnet-5',
      ok: true, calls: 3, input: 1000, output: 2000, cache_read: 0, cache_write: 0, chars: 4000,
      novel_title: '药', chapter_title: '第一章', cost_usd: 0.02 }] })
  }
  if (m && method === 'PATCH') {
    const u = users.find((x) => x.id === m[1])!
    Object.assign(u, JSON.parse(init!.body!))
    return json(u)
  }
  if (m && m[2] && method === 'POST') {
    const { password } = JSON.parse(init!.body!)
    return password.length < 6 ? err(400, '密码至少 6 位') : json({ ok: true })
  }
  if (path.startsWith('/admin/usage.csv')) return json('at,user_id\n')
  if (path.startsWith('/admin/usage')) {
    const group = new URL('http://x' + path).searchParams.get('group')
    return json({ group, days: 30, per_k_chars: { n: 2, mean: 0.75, p90: 3 }, unpriced_models: [],
      rows: [{ key: 'u-bob', label: group === 'user' ? 'bob' : group === 'model' ? 'claude-sonnet-5' : '2026-10-30',
               calls: 3, input: 1000, output: 2000, cache_read: 0, cache_write: 0, chars: 4000,
               cost_usd: 4.5, unpriced: 0 }] })
  }
  if (path === '/admin/jobs') return json({
    running: [{ id: 'j1', username: 'bob', status: 'running', work_title: '药', chapter: '第一章',
                chars: 4000, created_at: '2026-10-30T08:00:00+00:00', elapsed_sec: 75 }],
    failed: [{ id: 'v9', username: 'amy', novel_title: '孔乙己', chapter_title: '一',
               created_at: '2026-10-29T08:00:00+00:00', chars: 900, attempts: 3,
               error: 'schema 校验失败：缺少 episodes' }] })
  if (path.startsWith('/admin/audit')) return json({ audit: [
    { at: '2026-10-30T09:00:00+00:00', admin: 'root', action: 'disable', target: 'bob',
      before: { disabled: false }, after: { disabled: true } }] })
  if (path === '/admin/pricing' && method === 'GET') return json({ currency: 'USD', updated_at: null,
    models: { 'claude-sonnet-5': { input: 2, output: 10, cache_read: 0.2, cache_write: 2.5 } } })
  if (path === '/admin/pricing' && method === 'PUT') {
    const t = JSON.parse(init!.body!)
    return t.models ? json({ ...t, currency: 'USD', updated_at: 'now' }) : err(400, '价格表必须包含至少一个模型')
  }
  throw new Error(`桩后端未实现的路径: ${method} ${path}`)
}

const { act } = await import('react')
const { createRoot } = await import('react-dom/client')
const { Overview } = await import('../src/components/admin/Overview')
import type { ReactNode } from 'react'

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }
const container = win.document.createElement('div')
win.document.body.appendChild(container)
let root = createRoot(container as unknown as HTMLElement)
const settle = async (ms = 30) => {
  await act(async () => { await new Promise((r) => setTimeout(r, ms)) })
}
const has = (s: string) => container.innerHTML.includes(s)
const text = () => container.textContent ?? ''
const button = (label: string) => {
  const b = [...container.querySelectorAll('button')].find((x) => (x.textContent ?? '').includes(label))
  if (!b) throw new Error(`✗ 找不到按钮「${label}」`)
  return b as unknown as HTMLButtonElement
}
const click = async (el: Element) => {
  await act(async () => { el.dispatchEvent(new win.MouseEvent('click', { bubbles: true }) as unknown as Event) })
  await settle()
}
const type = async (el: Element, value: string) => {
  await act(async () => {
    const input = el as unknown as HTMLInputElement
    const setter = Object.getOwnPropertyDescriptor(win.HTMLInputElement.prototype, 'value')!.set!
    setter.call(input, value)
    input.dispatchEvent(new win.Event('input', { bubbles: true }) as unknown as Event)
  })
  await settle()
}
const remount = async (node: ReactNode) => {
  await act(async () => { root.unmount() })
  root = createRoot(container as unknown as HTMLElement)
  await act(async () => { root.render(node) })
  await settle()
}

// 1. 概览：六张卡片、未定价提示、折线图
await remount(<Overview />)
for (const s of ['用户', '7 天活跃', '30 天 token', '30 天金额', '运行中任务', '7 天失败']) {
  must(text().includes(s), `概览应有「${s}」`)
}
must(text().includes('1,234,567') && text().includes('$13.50'), '数字与金额格式')
must(text().includes('mystery'), '应提示未定价模型')
must(container.querySelectorAll('.adm__chart circle').length === 30, '折线图 30 个点')
console.log('1. 概览：卡片 / 格式 / 未定价提示 / 折线图 ✓')

// @@NEXT@@

await act(async () => { root.unmount() })
console.log('\nALL PASS')
```

> `// @@NEXT@@` 是后续任务插入测试段的位置标记（Task 7–9 在它之前插入）。

- [ ] **Step 2: 加进测试脚本并确认失败**

`frontend/package.json` 的 `test` 脚本末尾追加：

```
 && vite build --ssr tests/admin.test.tsx --outDir .ssrout --logLevel error && node .ssrout/admin.test.js
```

Run: `cd frontend && npm test`
Expected: FAIL，类型检查或构建报找不到 `../src/components/admin/Overview`

- [ ] **Step 3: 实现 `components/admin/Overview.tsx`**

```tsx
import { adminOverview } from '../../api'
import { int, usd } from './format'
import { LineChart } from './LineChart'
import { useLoad } from './useLoad'

/** 概览：几张数字卡片 + 近 30 天每日金额；打开时每 30 秒刷新。 */
export function Overview() {
  const { data, error } = useLoad(adminOverview, [], 30000)
  if (error) return <p className="adm__err">{error}</p>
  if (!data) return <p className="adm__empty">加载中…</p>
  const cards: [string, string][] = [
    ['用户', int(data.users)], ['7 天活跃', int(data.active_7d)],
    ['30 天 token', int(data.tokens_30d)], ['30 天金额', usd(data.cost_30d)],
    ['运行中任务', int(data.running)], ['7 天失败', int(data.failed_7d)],
  ]
  return (
    <section className="adm__sec">
      <div className="adm__cards">
        {cards.map(([k, v]) => (
          <div key={k} className="adm__card"><b>{v}</b><span>{k}</span></div>
        ))}
      </div>
      {data.unpriced_models.length > 0 && (
        <p className="adm__warn">
          未定价模型：{data.unpriced_models.join('、')}（不计入金额，可在「用量」页编辑价格表）
        </p>
      )}
      <h3 className="adm__h">近 30 天每日金额</h3>
      <LineChart points={data.daily.map((d) => ({ label: d.day.slice(5), value: d.cost_usd }))} />
      <p className="adm__note">金额按当前价格表估算。</p>
    </section>
  )
}
```

- [ ] **Step 4: 样式（`index.css` 末尾）**

```css
/* ---------- 管理后台 ---------- */

.adm { max-width: 1180px; margin: 0 auto; padding: 18px 22px 40px; }
.adm__head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.adm__head h2 { font-size: 18px; }
.adm__sec { display: flex; flex-direction: column; gap: 12px; padding: 16px 0; }
.adm__cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; }
.adm__card {
  display: flex; flex-direction: column; gap: 4px; padding: 12px 14px;
  background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius);
}
.adm__card b { font-size: 20px; font-family: var(--mono); }
.adm__card span { font-size: 12px; color: var(--muted); }
.adm__h { font-size: 14px; margin-top: 6px; }
.adm__note, .adm__empty { font-size: 12px; color: var(--faint); margin: 0; }
.adm__warn { font-size: 12.5px; background: var(--warn-bg); padding: 8px 10px; border-radius: 8px; margin: 0; }
.adm__err, .adm__bad { color: var(--danger); font-size: 12.5px; }
.adm__chart { width: 100%; height: auto; background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); }
.adm__axis { stroke: var(--line); }
.adm__line { stroke: var(--accent); stroke-width: 1.5; }
.adm__dot { fill: var(--accent); }
.adm__tick { font-size: 10.5px; fill: var(--faint); }
.adm__table { width: 100%; border-collapse: collapse; font-size: 12.5px; background: var(--panel); }
.adm__table th, .adm__table td { padding: 7px 10px; border-bottom: 1px solid var(--line-2); text-align: left; }
.adm__table th { font-weight: 600; color: var(--muted); background: var(--panel-2); }
.adm__table--sm { font-size: 12px; }
.adm__row { cursor: pointer; }
.adm__row:hover, .adm__row.is-open { background: var(--accent-soft); }
.adm__sort { border: none; background: none; padding: 0; font: inherit; color: inherit; cursor: pointer; }
.adm__search, .adm__inline input, .adm__pricing {
  border: 1px solid var(--line); border-radius: 6px; padding: 6px 8px; font: inherit; font-size: 12.5px;
  background: var(--panel); color: var(--text);
}
.adm__search { max-width: 260px; }
.adm__detail { display: flex; flex-direction: column; gap: 10px; padding: 8px 4px 14px; }
.adm__kv { display: grid; grid-template-columns: 90px 1fr; gap: 4px 10px; font-size: 12.5px; margin: 0; }
.adm__kv dt { color: var(--muted); }
.adm__kv dd { margin: 0; font-family: var(--mono); }
.adm__acts { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.adm__inline { display: inline-flex; gap: 6px; align-items: center; }
.adm__msg { font-size: 12.5px; margin: 0; }
.adm__bar { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
.adm__seg { display: inline-flex; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }
.adm__seg button { border: none; background: var(--panel); padding: 5px 12px; font-size: 12.5px; cursor: pointer; color: var(--muted); }
.adm__seg button.is-on { background: var(--accent-soft); color: var(--accent); font-weight: 600; }
.adm__kpi { font-size: 13px; margin: 0; }
.adm__pricing { width: 100%; min-height: 180px; font-family: var(--mono); }
.adm__err-detail summary { cursor: pointer; }
.adm__err-detail pre { white-space: pre-wrap; font-size: 11.5px; margin: 6px 0 0; }
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd frontend && npm test`
Expected: 全部套件 `ALL PASS`（`admin.test` 打印第 1 段 ✓）

- [ ] **Step 6: 提交**

```bash
git add frontend/src/components/admin/Overview.tsx frontend/tests/admin.test.tsx frontend/package.json frontend/src/index.css
git commit -m "管理后台概览：用户/活跃/token/金额/运行中/失败六张卡片、未定价模型提示、近 30 天每日金额折线图，每 30 秒刷新"
```

---

### Task 7: 用户页签（列表、详情、操作）

**Files:**
- Create: `frontend/src/components/admin/Users.tsx`
- Modify: `frontend/tests/admin.test.tsx`

- [ ] **Step 1: 写失败测试**

在 `admin.test.tsx` 中：

(a) 在 `const { Overview } = await import(...)` 下一行加：

```ts
const { Users } = await import('../src/components/admin/Users')
```

(b) 在 `// @@NEXT@@` 之前插入：

```tsx
// 2. 用户：默认按注册时间倒序；点表头按本月金额排序；搜索
const me = { id: 'u-root', username: 'root', created_at: '', role: 'admin' as const }
await remount(<Users me={me} />)
const names = () => [...container.querySelectorAll('tbody tr.adm__row td:first-child')].map((td) => td.textContent)
must(names().join(',') === 'amy,bob,root', `默认注册倒序，实为 ${names()}`)
await click(button('本月金额'))
must(names().join(',') === 'amy,bob,root', '本月金额降序')
await click(button('本月金额'))
must(names().join(',') === 'root,bob,amy', '再点升序')
await type(container.querySelector('.adm__search')!, 'bo')
must(names().join(',') === 'bob', '搜索过滤')
must(text().includes('$5.00') && text().includes('$4.50'), '上限与本月金额')
console.log('2. 用户：排序 / 搜索 / 金额 ✓')

// 3. 详情与操作：停用带确认、改上限、重置密码（失败提示）、自己不能停用
await click(container.querySelector('tbody tr.adm__row')!)
must(text().includes('药 / 第一章') && text().includes('转换'), '详情显示最近用量与标题')
await click(button('停用'))
must(confirms.some((c) => c.includes('停用')), '停用应先确认')
must(calls.some((c) => c === 'PATCH /admin/users/u-bob {"disabled":true}'), '应请求停用')
must(text().includes('已停用'), '列表刷新为已停用')
await type(container.querySelector('input[placeholder^="月上限"]')!, '')
await click(button('设上限'))
must(calls.some((c) => c === 'PATCH /admin/users/u-bob {"monthly_cap_usd":null}'), '空上限 = 不限')
await type(container.querySelector('input[type=password]')!, 'goodpass1')
await click(button('重置密码'))
must(calls.some((c) => c.startsWith('POST /admin/users/u-bob/password')), '应请求重置密码')
await type(container.querySelector('.adm__search')!, 'root')
await click(container.querySelector('tbody tr.adm__row')!)
must(button('停用').disabled && button('取消管理员').disabled, '自己不能停用、不能改自己的角色')
must(text().includes('不能停用自己'), '应说明原因')
console.log('3. 详情 / 停用确认 / 上限不限 / 重置密码 / 自己受限 ✓')
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npm test`
Expected: FAIL，找不到 `../src/components/admin/Users`

- [ ] **Step 3: 实现 `components/admin/Users.tsx`**

```tsx
import { Fragment, useState } from 'react'
import { adminPatchUser, adminResetPassword, adminUser, adminUsers } from '../../api'
import type { User } from '../../auth'
import type { AdminUserRow } from '../../types'
import { day, errText, int, PURPOSE, usd, when } from './format'
import { LineChart } from './LineChart'
import { useLoad } from './useLoad'

type Key = 'username' | 'created_at' | 'last_seen_at' | 'novels' | 'month_cost_usd'

function compare(a: AdminUserRow, b: AdminUserRow, k: Key): number {
  const x = a[k] ?? ''
  const y = b[k] ?? ''
  if (typeof x === 'number' && typeof y === 'number') return x - y
  return String(x).localeCompare(String(y))
}

/** 用户：表格（搜索、表头排序），点一行展开详情与操作。 */
export function Users({ me }: { me: User }) {
  const { data, error, reload } = useLoad(adminUsers, [])
  const [q, setQ] = useState('')
  const [sort, setSort] = useState<Key>('created_at')
  const [desc, setDesc] = useState(true)
  const [open, setOpen] = useState<string | null>(null)

  if (error) return <p className="adm__err">{error}</p>
  if (!data) return <p className="adm__empty">加载中…</p>

  const needle = q.trim().toLowerCase()
  const rows = data
    .filter((u) => u.username.toLowerCase().includes(needle))
    .sort((a, b) => (desc ? -1 : 1) * compare(a, b, sort))

  const head = (k: Key, label: string) => (
    <th>
      <button className="adm__sort" onClick={() => {
        if (sort === k) setDesc(!desc)
        else { setSort(k); setDesc(true) }
      }}>
        {label}{sort === k ? (desc ? ' ↓' : ' ↑') : ''}
      </button>
    </th>
  )

  return (
    <section className="adm__sec">
      <input className="adm__search" placeholder="搜索用户名" value={q}
             onChange={(e) => setQ(e.target.value)} />
      <table className="adm__table">
        <thead>
          <tr>
            {head('username', '用户名')}<th>角色</th><th>状态</th>
            {head('created_at', '注册')}{head('last_seen_at', '最近活跃')}
            {head('novels', '小说')}<th>章节</th>
            {head('month_cost_usd', '本月金额')}<th>月上限</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((u) => (
            <Fragment key={u.id}>
              <tr className={`adm__row${open === u.id ? ' is-open' : ''}`}
                  onClick={() => setOpen(open === u.id ? null : u.id)}>
                <td>{u.username}</td>
                <td>{u.role === 'admin' ? '管理员' : '用户'}</td>
                <td>{u.disabled ? <span className="adm__bad">已停用</span> : '正常'}</td>
                <td>{day(u.created_at)}</td>
                <td>{when(u.last_seen_at)}</td>
                <td>{int(u.novels)}</td>
                <td>{int(u.chapters)}</td>
                <td>{usd(u.month_cost_usd)}</td>
                <td>{u.monthly_cap_usd == null ? '不限' : usd(u.monthly_cap_usd)}</td>
              </tr>
              {open === u.id && (
                <tr>
                  <td colSpan={9}><UserDetail id={u.id} me={me} onChanged={reload} /></td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </section>
  )
}

function UserDetail({ id, me, onChanged }: { id: string; me: User; onChanged: () => void }) {
  const { data, error, reload } = useLoad(() => adminUser(id), [id])
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [cap, setCap] = useState('')
  const [pwd, setPwd] = useState('')

  if (error) return <p className="adm__err">{error}</p>
  if (!data) return <p className="adm__empty">加载中…</p>
  const u = data.user
  const self = u.id === me.id

  const act = async (label: string, fn: () => Promise<unknown>, ask = true) => {
    if (ask && !window.confirm(`确定要${label}？`)) return
    setBusy(true)
    setMsg(null)
    try {
      await fn()
      setMsg(`已${label}`)
      reload()
      onChanged()
    } catch (e) {
      setMsg(errText(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="adm__detail" onClick={(e) => e.stopPropagation()}>
      <dl className="adm__kv">
        <dt>用户 ID</dt><dd>{u.id}</dd>
        <dt>密码登录</dt><dd>{u.has_password ? '已设置' : '未设置'}</dd>
        <dt>版本数</dt><dd>{int(u.versions)}</dd>
      </dl>
      <div className="adm__acts">
        <button className="btn btn--sm btn--ghost" disabled={busy || self}
                onClick={() => void act(u.disabled ? '启用该账号' : '停用该账号',
                  () => adminPatchUser(u.id, { disabled: !u.disabled }))}>
          {u.disabled ? '启用' : '停用'}
        </button>
        <button className="btn btn--sm btn--ghost" disabled={busy || self}
                onClick={() => void act(u.role === 'admin' ? '取消管理员' : '设为管理员',
                  () => adminPatchUser(u.id, { role: u.role === 'admin' ? 'user' : 'admin' }))}>
          {u.role === 'admin' ? '取消管理员' : '设为管理员'}
        </button>
        <span className="adm__inline">
          <input placeholder="月上限（美元，空 = 不限）" value={cap}
                 onChange={(e) => setCap(e.target.value)} />
          <button className="btn btn--sm btn--ghost" disabled={busy}
                  onClick={() => void act('修改月上限', () => adminPatchUser(u.id,
                    { monthly_cap_usd: cap.trim() === '' ? null : Number(cap) }), false)}>
            设上限
          </button>
        </span>
        <span className="adm__inline">
          <input type="password" placeholder="新密码（至少 6 位）" value={pwd}
                 onChange={(e) => setPwd(e.target.value)} />
          <button className="btn btn--sm btn--ghost" disabled={busy || pwd.length < 6}
                  onClick={() => void act('重置密码',
                    () => adminResetPassword(u.id, pwd).then(() => setPwd('')))}>
            重置密码
          </button>
        </span>
      </div>
      {self && <p className="adm__note">不能停用自己，也不能修改自己的角色。</p>}
      {msg && <p className="adm__msg">{msg}</p>}
      <h4 className="adm__h">近 30 天每日金额</h4>
      <LineChart height={100}
                 points={data.daily.map((d) => ({ label: d.day.slice(5), value: d.cost_usd }))} />
      <h4 className="adm__h">最近用量</h4>
      <table className="adm__table adm__table--sm">
        <thead>
          <tr><th>时间</th><th>用途</th><th>小说 / 章节</th><th>模型</th><th>结果</th>
              <th>token</th><th>金额</th></tr>
        </thead>
        <tbody>
          {data.recent.map((r, i) => (
            <tr key={i}>
              <td>{when(r.at)}</td>
              <td>{PURPOSE[r.purpose] ?? r.purpose}</td>
              <td>{r.novel_title ?? '（已删除）'} / {r.chapter_title ?? '—'}</td>
              <td>{r.model}{r.mixed_models ? '（含评审模型，按转换模型估算）' : ''}</td>
              <td>{r.ok ? '成功' : '失败'}</td>
              <td>{int(r.input + r.output + r.cache_read + r.cache_write)}</td>
              <td>{usd(r.cost_usd)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npm test`
Expected: 全部 `ALL PASS`（`admin.test` 打印 1–3 段 ✓）

- [ ] **Step 5: 提交**

```bash
git add frontend/src/components/admin/Users.tsx frontend/tests/admin.test.tsx
git commit -m "管理后台用户页：搜索与表头排序，展开详情看最近用量与每日金额，停用/角色带确认，月上限可设不限，重置密码，自己不能停用或改角色"
```

---

### Task 8: 用量、任务、审计页签

**Files:**
- Create: `frontend/src/components/admin/UsageTab.tsx`
- Create: `frontend/src/components/admin/JobsTab.tsx`
- Create: `frontend/src/components/admin/AuditTab.tsx`
- Modify: `frontend/tests/admin.test.tsx`

- [ ] **Step 1: 写失败测试**

(a) 在 `const { Users } = ...` 下一行加：

```ts
const { UsageTab } = await import('../src/components/admin/UsageTab')
const { JobsTab } = await import('../src/components/admin/JobsTab')
const { AuditTab } = await import('../src/components/admin/AuditTab')
```

(b) 在 `// @@NEXT@@` 之前插入：

```tsx
// 4. 用量：默认按用户；切分组与范围会重新请求；每千字成本；价格表保存
await remount(<UsageTab />)
must(calls.includes('GET /admin/usage?group=user&days=30'), '默认按用户、30 天')
must(text().includes('bob') && text().includes('$0.7500') && text().includes('$3.0000'), '每千字成本')
await click(button('按模型'))
must(calls.includes('GET /admin/usage?group=model&days=30') && text().includes('claude-sonnet-5'), '切到按模型')
await click(button('7 天'))
must(calls.includes('GET /admin/usage?group=model&days=7'), '切到 7 天')
await click(button('保存价格表'))
must(calls.some((c) => c.startsWith('PUT /admin/pricing')) && text().includes('已保存'), '价格表保存')
const area = container.querySelector('textarea')!
await act(async () => {
  const setter = Object.getOwnPropertyDescriptor(win.HTMLTextAreaElement.prototype, 'value')!.set!
  setter.call(area, '{not json')
  area.dispatchEvent(new win.Event('input', { bubbles: true }) as unknown as Event)
})
await settle()
await click(button('保存价格表'))
must(text().includes('不是合法的 JSON'), '非法 JSON 提示')
console.log('4. 用量：分组 / 范围 / 每千字成本 / 价格表保存与校验 ✓')

// 5. 任务：运行中与失败两表，报错可展开
await remount(<JobsTab />)
must(text().includes('1:15') && text().includes('孔乙己') && text().includes('schema 校验失败'), '任务两表')
console.log('5. 任务：运行中（已运行 1:15）/ 近期失败报错 ✓')

// 6. 审计
await remount(<AuditTab />)
must(text().includes('停用') && text().includes('root') && text().includes('bob'), '审计列表')
console.log('6. 审计 ✓')
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npm test`
Expected: FAIL，找不到 `UsageTab`

- [ ] **Step 3: 实现 `components/admin/UsageTab.tsx`**

```tsx
import { useEffect, useState } from 'react'
import { adminPricing, adminSavePricing, adminUsage, adminUsageCsv } from '../../api'
import { errText, int, usd, usd4 } from './format'
import { useLoad } from './useLoad'

type Group = 'user' | 'day' | 'model'
const GROUPS: [Group, string][] = [['user', '按用户'], ['day', '按天'], ['model', '按模型']]
const RANGES = [7, 30, 90]

function download(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8' }))
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  URL.revokeObjectURL(url)
}

/** 用量：分组汇总、每千字成本、导出 CSV；下面是价格表。 */
export function UsageTab() {
  const [group, setGroup] = useState<Group>('user')
  const [days, setDays] = useState(30)
  const { data, error } = useLoad(() => adminUsage(group, days), [group, days])
  const [csvErr, setCsvErr] = useState<string | null>(null)

  const exportCsv = async () => {
    setCsvErr(null)
    try {
      download(`usage-${days}d.csv`, await adminUsageCsv(days))
    } catch (e) {
      setCsvErr(errText(e))
    }
  }

  return (
    <section className="adm__sec">
      <div className="adm__bar">
        <div className="adm__seg">
          {GROUPS.map(([g, label]) => (
            <button key={g} className={group === g ? 'is-on' : ''} onClick={() => setGroup(g)}>{label}</button>
          ))}
        </div>
        <div className="adm__seg">
          {RANGES.map((d) => (
            <button key={d} className={days === d ? 'is-on' : ''} onClick={() => setDays(d)}>{d} 天</button>
          ))}
        </div>
        <button className="btn btn--sm btn--ghost" onClick={() => void exportCsv()}>导出 CSV</button>
        {csvErr && <span className="adm__err">{csvErr}</span>}
      </div>
      {error && <p className="adm__err">{error}</p>}
      {!data && !error && <p className="adm__empty">加载中…</p>}
      {data && (
        <>
          <p className="adm__kpi">
            每千字成本：均值 {usd4(data.per_k_chars.mean)} · P90 {usd4(data.per_k_chars.p90)}
            （{data.per_k_chars.n} 次成功转换）
          </p>
          {data.unpriced_models.length > 0 && (
            <p className="adm__warn">未定价模型：{data.unpriced_models.join('、')}（不计入金额）</p>
          )}
          <table className="adm__table">
            <thead>
              <tr>
                <th>{GROUPS.find(([g]) => g === data.group)?.[1].slice(1) ?? '分组'}</th>
                <th>调用</th><th>输入</th><th>输出</th><th>缓存读</th><th>缓存写</th>
                <th>原文字数</th><th>金额</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((r) => (
                <tr key={r.key}>
                  <td>{r.label}</td><td>{int(r.calls)}</td><td>{int(r.input)}</td>
                  <td>{int(r.output)}</td><td>{int(r.cache_read)}</td><td>{int(r.cache_write)}</td>
                  <td>{int(r.chars)}</td>
                  <td>{usd(r.cost_usd)}{r.unpriced ? `（另有 ${r.unpriced} 条未定价）` : ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="adm__note">金额按当前价格表估算。</p>
        </>
      )}
      <PricingEditor />
    </section>
  )
}

function PricingEditor() {
  const [raw, setRaw] = useState('')
  const [msg, setMsg] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    adminPricing().then((t) => setRaw(JSON.stringify({ models: t.models }, null, 2)))
      .catch((e: unknown) => setMsg(errText(e)))
  }, [])

  const save = async () => {
    let parsed: unknown
    try {
      parsed = JSON.parse(raw)
    } catch {
      setMsg('不是合法的 JSON')
      return
    }
    setBusy(true)
    setMsg(null)
    try {
      const t = await adminSavePricing(parsed)
      setRaw(JSON.stringify({ models: t.models }, null, 2))
      setMsg('已保存')
    } catch (e) {
      setMsg(errText(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="adm__sec">
      <h3 className="adm__h">价格表（美元 / 每百万 token）</h3>
      <textarea className="adm__pricing" value={raw} onChange={(e) => setRaw(e.target.value)} />
      <div className="adm__acts">
        <button className="btn btn--sm" disabled={busy} onClick={() => void save()}>保存价格表</button>
        {msg && <span className="adm__msg">{msg}</span>}
      </div>
    </div>
  )
}
```

- [ ] **Step 4: 实现 `components/admin/JobsTab.tsx`**

```tsx
import { adminJobs } from '../../api'
import { int, when } from './format'
import { useLoad } from './useLoad'

const clock = (s: number | null) =>
  (s == null ? '—' : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`)

/** 任务：运行中（内存任务表）与近 7 天失败（磁盘上的版本）。 */
export function JobsTab() {
  const { data, error, reload } = useLoad(adminJobs, [])
  if (error) return <p className="adm__err">{error}</p>
  if (!data) return <p className="adm__empty">加载中…</p>
  return (
    <section className="adm__sec">
      <div className="adm__bar">
        <h3 className="adm__h">运行中</h3>
        <button className="btn btn--sm btn--ghost" onClick={reload}>刷新</button>
      </div>
      {data.running.length === 0 ? <p className="adm__empty">没有运行中的任务</p> : (
        <table className="adm__table">
          <thead><tr><th>用户</th><th>小说 / 章节</th><th>状态</th><th>开始</th><th>已运行</th><th>字数</th></tr></thead>
          <tbody>
            {data.running.map((j) => (
              <tr key={j.id}>
                <td>{j.username ?? '—'}</td><td>{j.work_title ?? '—'} / {j.chapter ?? '—'}</td>
                <td>{j.status}</td><td>{when(j.created_at)}</td><td>{clock(j.elapsed_sec)}</td>
                <td>{int(j.chars)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <h3 className="adm__h">近 7 天失败</h3>
      {data.failed.length === 0 ? <p className="adm__empty">没有失败的任务</p> : (
        <table className="adm__table">
          <thead><tr><th>用户</th><th>小说 / 章节</th><th>开始</th><th>字数</th><th>尝试</th><th>报错</th></tr></thead>
          <tbody>
            {data.failed.map((j) => (
              <tr key={j.id}>
                <td>{j.username ?? '—'}</td>
                <td>{j.novel_title ?? '（已删除）'} / {j.chapter_title ?? '—'}</td>
                <td>{when(j.created_at)}</td><td>{int(j.chars)}</td><td>{j.attempts}</td>
                <td>
                  <details className="adm__err-detail">
                    <summary>{j.error.slice(0, 40)}{j.error.length > 40 ? '…' : ''}</summary>
                    <pre>{j.error}</pre>
                  </details>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}
```

- [ ] **Step 5: 实现 `components/admin/AuditTab.tsx`**

```tsx
import { adminAudit } from '../../api'
import { ACTION, when } from './format'
import { useLoad } from './useLoad'

const show = (v: Record<string, unknown> | null) => (v ? JSON.stringify(v) : '—')

/** 审计：管理操作记录，最新在前。 */
export function AuditTab() {
  const { data, error } = useLoad(adminAudit, [])
  if (error) return <p className="adm__err">{error}</p>
  if (!data) return <p className="adm__empty">加载中…</p>
  if (!data.length) return <p className="adm__empty">还没有管理操作</p>
  return (
    <section className="adm__sec">
      <table className="adm__table">
        <thead><tr><th>时间</th><th>管理员</th><th>操作</th><th>对象</th><th>之前</th><th>之后</th></tr></thead>
        <tbody>
          {data.map((a, i) => (
            <tr key={i}>
              <td>{when(a.at)}</td><td>{a.admin}</td><td>{ACTION[a.action] ?? a.action}</td>
              <td>{a.target ?? '—'}</td><td>{show(a.before)}</td><td>{show(a.after)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}
```

- [ ] **Step 6: 跑测试确认通过**

Run: `cd frontend && npm test`
Expected: 全部 `ALL PASS`（`admin.test` 打印 1–6 段 ✓）

- [ ] **Step 7: 提交**

```bash
git add frontend/src/components/admin/UsageTab.tsx frontend/src/components/admin/JobsTab.tsx frontend/src/components/admin/AuditTab.tsx frontend/tests/admin.test.tsx
git commit -m "管理后台用量/任务/审计页：按用户/天/模型与 7/30/90 天汇总、每千字成本均值与 P90、导出 CSV、价格表编辑；运行中与近期失败任务；审计列表"
```

---

### Task 9: 后台入口

**Files:**
- Create: `frontend/src/components/admin/AdminView.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/tests/admin.test.tsx`
- Modify: `frontend/tests/flow.test.tsx`

- [ ] **Step 1: 写失败测试**

(a) `admin.test.tsx` 在 `const { AuditTab } = ...` 下一行加：

```ts
const { AdminView } = await import('../src/components/admin/AdminView')
```

在 `// @@NEXT@@` 之前插入：

```tsx
// 7. 页签框架：五个页签可切换，返回回调
let back = 0
await remount(<AdminView me={me} onBack={() => { back++ }} />)
for (const t of ['概览', '用户', '用量', '任务', '审计']) button(t)
must(text().includes('30 天金额'), '默认在概览')
await click(button('审计'))
must(text().includes('设为管理员') === false && text().includes('停用'), '切到审计')
await click(button('返回'))
must(back === 1, '返回回调')
console.log('7. 页签框架 / 返回 ✓')
```

(b) `flow.test.tsx`：在测试里第一次成功登录进入书架之后的位置（找到断言登录成功、显示用户名或书架的那一段，紧接其后）加：

```ts
must(![...container.querySelectorAll('button')].some((b) => b.textContent === '管理'),
     '普通用户不应看到「管理」入口')
```

> `flow.test.tsx` 里的断言函数名、容器变量名以该文件现有命名为准（若叫 `assert` / `root` 等，照改）。桩后端的 `user()` 不带 `role`，即普通用户。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npm test`
Expected: FAIL，找不到 `AdminView`

- [ ] **Step 3: 实现 `components/admin/AdminView.tsx`**

```tsx
import { useState } from 'react'
import type { User } from '../../auth'
import { AuditTab } from './AuditTab'
import { JobsTab } from './JobsTab'
import { Overview } from './Overview'
import { UsageTab } from './UsageTab'
import { Users } from './Users'

type Tab = 'overview' | 'users' | 'usage' | 'jobs' | 'audit'
const TABS: [Tab, string][] = [
  ['overview', '概览'], ['users', '用户'], ['usage', '用量'], ['jobs', '任务'], ['audit', '审计'],
]

/** 管理后台：只给管理员看（入口在右上角）；权限以后端为准。 */
export function AdminView({ me, onBack }: { me: User; onBack: () => void }) {
  const [tab, setTab] = useState<Tab>('overview')
  return (
    <div className="adm">
      <header className="adm__head">
        <h2>管理后台</h2>
        <button className="btn btn--sm btn--ghost" onClick={onBack}>返回</button>
      </header>
      <nav className="tabs">
        {TABS.map(([id, name]) => (
          <button key={id} className={`tabs__btn${tab === id ? ' is-on' : ''}`}
                  onClick={() => setTab(id)}>{name}</button>
        ))}
      </nav>
      {tab === 'overview' && <Overview />}
      {tab === 'users' && <Users me={me} />}
      {tab === 'usage' && <UsageTab />}
      {tab === 'jobs' && <JobsTab />}
      {tab === 'audit' && <AuditTab />}
    </div>
  )
}
```

- [ ] **Step 4: 接入 `App.tsx`**

- 加 `import { AdminView } from './components/admin/AdminView'`
- 在 `const [user, setUser] = ...` 之后加 `const [adminOpen, setAdminOpen] = useState(false)`
- `logout` 里加 `setAdminOpen(false)`
- 在 `<span className="who" ...>` 之前加：

```tsx
          {user.role === 'admin' && (
            <button className="btn btn--sm btn--ghost" onClick={() => setAdminOpen((v) => !v)}>
              {adminOpen ? '返回书架' : '管理'}
            </button>
          )}
```

- 把 `<div className="shell">` 整个元素（到它对应的 `</div>`）包进三元：

```tsx
      {adminOpen ? (
        <AdminView me={user} onBack={() => setAdminOpen(false)} />
      ) : (
        <div className="shell">
          {/* 原有内容不变 */}
        </div>
      )}
```

> 注意：只改包裹层，`shell` 内部的 JSX 原样保留，不要重排。

- [ ] **Step 5: 跑测试与构建**

Run: `cd frontend && npm test && npm run build`
Expected: 全部 `ALL PASS`（`admin.test` 打印 1–7 段 ✓，`flow.test` 通过新断言）；构建成功

- [ ] **Step 6: 提交**

```bash
git add frontend/src/components/admin/AdminView.tsx frontend/src/App.tsx frontend/tests/admin.test.tsx frontend/tests/flow.test.tsx
git commit -m "管理后台入口：管理员右上角「管理」进入五个页签的后台，普通用户看不到入口"
```

---

### Task 10: 文档与手动验证

**Files:**
- Modify: `README.md`
- Modify: `frontend/README.md`

- [ ] **Step 1: 根 `README.md`**

在「方式一」的 HTTP 服务说明之后加一段：

```markdown
**管理后台**：先指定管理员 `cd backend && .venv/bin/python -m server.admin promote <用户名>`，
该用户登录后右上角出现「管理」：概览、用户（停用/启用、月上限、重置密码、设为或取消管理员）、
用量（按用户/天/模型汇总，每千字成本，导出 CSV，价格表）、任务（运行中与近 7 天失败）、审计。
用量记在 `data/usage.jsonl`（转换与章后整理结束时落账，删版本不影响），金额按 `data/pricing.json`
（美元，后台可改）现算。已有版本的历史用量补导一次：`.venv/bin/python -m server.admin backfill-usage`。
管理员看不到小说原文与分镜内容。
```

- [ ] **Step 2: `frontend/README.md`**

文件末尾加：

```markdown
### 管理后台

`components/admin/`：`AdminView` 页签框架，`Overview`（每 30 秒刷新）、`Users`（搜索、排序、展开详情与操作）、
`UsageTab`（分组汇总、每千字成本、CSV、价格表）、`JobsTab`、`AuditTab`；`LineChart` 是手写 SVG。
只有 `/auth/me` 返回 `role: "admin"` 的用户看得到入口，权限以后端 `/admin/*` 的 403 为准。界面回归见 `tests/admin.test.tsx`。
```

- [ ] **Step 3: 全量回归**

Run:
```bash
cd backend && for t in tests/server/test_*.py; do .venv/bin/python $t || break; done
cd ../frontend && npm test && npm run build
```
Expected: 后端每个文件 `ALL PASS`；前端全部套件 `ALL PASS`；构建成功

- [ ] **Step 4: 提交**

```bash
git add README.md frontend/README.md
git commit -m "文档：管理后台的授权命令、各页签功能、用量与价格表的存放和历史补导"
```

- [ ] **Step 5: 手动验证（真实数据，不改代码）**

1. `cd backend && .venv/bin/python -m server.admin list`，找到自己的用户名，`promote` 它。
2. `.venv/bin/python -m server.admin backfill-usage`，记下输出的 added / skipped 数。
3. 启动后端与前端，登录 → 右上角「管理」：概览数字与折线图正常；用户页能看到自己与小说数；用量页按天有补导的记录。
4. 用另一个测试账号验证：设月上限 0 → 该账号提交转换被拒；停用 → 该账号立即被退回登录页；启用恢复。
5. 结果（成功或报错原文）记在本计划末尾。
