# 管理后台设计

日期：2026-10-29 · 分支：langchain

## 0. 决定

| 决定 | 内容 |
|---|---|
| 背景 | 收费暂缓，先面向海外，先做基础体系；管理后台优先于 Google 登录（后者降为最低） |
| 范围 | 用户列表与详情、token 消耗与费用、任务监控、用户管理操作（停用、上限、重置密码、角色） |
| 管理员 | `users.json` 的 `role` 字段；首个管理员用命令行设，之后可在后台授予或取消 |
| 用量存储 | 追加写的流水账 `usage.jsonl`，在每次模型调用落账；上线时从已有版本记录补导一次 |
| 计价 | 价格表 `pricing.json`，美元；金额按查询时的价格表现算 |
| 隐私 | 管理员只看元数据（标题、数量、用量、状态、报错），不看小说原文与分镜内容 |
| 不做 | 删除用户、查看原文、实时推送、出片费用（出片上线后作为新用途记进同一流水账） |

## 1. 权限

- `users.json` 每个用户增加 `role: "admin" | "user"`，缺省视为 `user`。
- 首个管理员：`cd backend && .venv/bin/python -m server.admin promote <用户名>`（同模块提供 `demote`、`list`）。
- 后台可把他人设为或取消管理员。约束：
  - 不能取消自己的管理员、不能停用自己；
  - 系统至少保留一个未停用的管理员，违反时拒绝（400）。
- 后端新增依赖 `admin_user`：在 `current_user` 之上要求 `role == "admin"`，否则 403。所有 `/admin/*` 接口都用它。
- `/auth/me` 返回 `role`，前端据此显示「管理」入口。前端隐藏只是体验，权限以后端为准。

## 2. 数据

### 2.1 `data/usage.jsonl`（追加写）

每次落账一行：

```json
{"at": "2026-10-29T08:00:00+00:00", "user_id": "a1b2c3d4e5f6",
 "novel_id": "n_…", "chapter_id": "c_…", "version_id": "43d0…",
 "purpose": "convert", "model": "claude-sonnet-5", "ok": true,
 "calls": 6, "input": 52000, "output": 61000, "cache_read": 30000, "cache_write": 9000,
 "chars": 4584}
```

- `purpose`：`convert`（一次转换，含其中的修复与评审调用）、`digest`（采用版本后的章后整理）。以后出片加 `render`。
- 落账时机：
  - 转换：`_execute` 结束时，成功和失败都记。用量取 `manifest["usage"]`；为空时用 `manifest_mod.sum_usage(manifest["attempts"])` 现算。评审若用另一个模型，按模型拆成两行。
  - 章后整理：`run_digest` 那次调用结束后记一行，`chars` 为 0。
- 写入：进程内锁 + 以追加模式写一行并 `flush`；单行 JSON 不跨行。读取时跳过解析失败的行（容忍崩溃时写了半行）。
- 删除版本、删除小说不影响流水账。

### 2.2 补导历史

`python -m server.admin backfill-usage`：扫描 `data/users/*/novels/*/chapters/*/versions/*.json` 与旧 `runs/*.json`，有 `manifest.usage` 或 `manifest.attempts` 的生成 `purpose=convert` 记录，`at` 取版本 `created_at`。用 `(user_id, version_id, purpose)` 去重，重复执行安全。没有用量信息的老版本跳过并在输出里计数。

### 2.3 `data/pricing.json`

```json
{"currency": "USD",
 "models": {"claude-sonnet-5": {"input": 2.0, "output": 10.0, "cache_read": 0.2, "cache_write": 2.5}},
 "updated_at": "…", "note": "每百万 token 单价"}
```

- 不存在时用内置默认表（`server/pricing.py`）。
- 没有单价的模型：金额显示「未定价」，不计入合计，概览页提示有未定价模型。
- 金额 = Σ(token × 单价 / 1e6)，查询时现算；改了价格表，历史金额随之重算，页面注明「按当前价格表估算」。
- 后台可编辑价格表，修改写审计。

### 2.4 `users.json` 新增字段

| 字段 | 含义 |
|---|---|
| `role` | `admin` / `user` |
| `disabled` | `true` 时 `verify_token` 返回空（现有 token 立即失效），`authenticate` 报「账号已停用」 |
| `monthly_cap_usd` | 每月花费上限，`null` 表示不限 |
| `last_seen_at` | 最近一次请求时间；同一用户 10 分钟内最多写一次（进程内记录上次写入时刻） |

### 2.5 `data/admin_audit.jsonl`（追加写）

```json
{"at": "…", "admin_id": "…", "admin": "lu", "action": "disable",
 "target_id": "…", "target": "bob", "before": {"disabled": false}, "after": {"disabled": true}}
```

`action`：`disable`、`enable`、`set_cap`、`reset_password`、`grant_admin`、`revoke_admin`、`update_pricing`。重置密码只记动作，不记密码。

## 3. 用户管理操作

| 操作 | 接口 | 效果与约束 |
|---|---|---|
| 停用 / 启用 | `PATCH /admin/users/{id}` `{disabled}` | 立即生效；已在跑的任务跑完；不能停用自己；不能停用最后一个管理员 |
| 每月上限 | `PATCH /admin/users/{id}` `{monthly_cap_usd}` | 提交转换（`POST …/versions`）时，若当月（UTC 自然月）已花 ≥ 上限，返回 429「本月用量已达上限，请联系管理员」；不打断进行中的任务 |
| 重置密码 | `POST /admin/users/{id}/password` `{password}` | 复用注册的密码规则；无密码账号借此设上密码 |
| 角色 | `PATCH /admin/users/{id}` `{role}` | 不能改自己；至少保留一个管理员 |

`PATCH` 一次只允许改一个字段，便于审计与回显。

## 4. 接口

| 方法 | 路径 | 返回 |
|---|---|---|
| GET | `/admin/overview` | 用户总数、7 天活跃数、近 30 天 token 与金额、运行中任务数、7 天失败数、近 30 天按天金额序列、是否有未定价模型 |
| GET | `/admin/users?q=&sort=&order=` | 用户行：id、用户名、角色、停用、注册、最近活跃、小说数、章节数、版本数、本月金额、上限 |
| GET | `/admin/users/{id}` | 上面一行 + 登录方式 + 最近 50 条用量记录（含小说、章节标题）+ 近 30 天按天金额 |
| PATCH | `/admin/users/{id}` | 更新后的用户行 |
| POST | `/admin/users/{id}/password` | `{ok: true}` |
| GET | `/admin/usage?group=user\|day\|model&days=7\|30\|90` | 分组汇总：calls、四类 token、金额、字数；另附每千字成本均值与 P90（仅 `purpose=convert` 且成功的记录） |
| GET | `/admin/usage.csv?days=` | 明细 CSV（每条流水一行，附金额） |
| GET | `/admin/jobs` | 运行中任务（内存任务表）+ 近 7 天失败的版本（磁盘）：用户、小说与章节标题、开始时间、耗时、字数、尝试轮数、报错前 300 字 |
| GET | `/admin/audit?limit=200` | 审计记录，最新在前 |
| GET / PUT | `/admin/pricing` | 价格表 |

统计数量（小说、章节、版本数）从 `novels` 模块现有的读取函数取，不读原文字段。标题来自小说、章节元数据。

## 5. 前端

- 右上角在用户名前给管理员加「管理」按钮；点开后主区域换成 `AdminView`，再点「返回」回到书架。
- `AdminView` 五个页签：

| 页签 | 内容 |
|---|---|
| 概览 | 数字卡片（用户、7 天活跃、30 天 token、30 天金额、运行中、7 天失败）；近 30 天每天金额折线图（手写 SVG）；有未定价模型时提示 |
| 用户 | 表格，可搜索用户名、点表头排序；点一行展开详情：基本信息、操作（停用/启用、设上限、重置密码、设为/取消管理员，带确认）、最近用量记录、按天金额小图 |
| 用量 | 分组切换（用户 / 天 / 模型）、时间范围（7 / 30 / 90 天）、汇总表、每千字成本（均值、P90）、导出 CSV；价格表查看与编辑 |
| 任务 | 运行中与近期失败两张表，报错可展开 |
| 审计 | 列表 |

- 数据刷新：概览页打开时每 30 秒刷新；其他页签进入时拉取，提供「刷新」按钮。
- 文件：`components/admin/AdminView.tsx`（页签框架）与每个页签一个文件、`components/admin/LineChart.tsx`、`api.ts` 增加 `admin*` 函数、`types.ts` 增加对应类型。
- 金额显示两位小数美元；token 用千分位。

## 6. 后端模块

| 文件 | 职责 |
|---|---|
| `server/usage.py` | 流水账写入、读取（按时间范围过滤）、分组汇总、每千字成本 |
| `server/pricing.py` | 默认价格表、读写 `pricing.json`、单条记录计价 |
| `server/audit.py` | 审计写入与读取 |
| `server/admin.py` | 管理逻辑（用户行组装、操作与约束）+ 命令行入口（`promote`、`demote`、`list`、`backfill-usage`） |
| `server/auth.py` | `role`、`disabled`、`monthly_cap_usd`、`last_seen_at`；`set_password`、`set_fields` |
| `server/app.py` | `admin_user` 依赖、`/admin/*` 路由、`_execute` 与章后整理处落账、提交转换处检查月上限 |

## 7. 测试

| 层 | 内容 |
|---|---|
| `tests/server/test_usage.py` | 落账与读取、坏行容忍、按用户/天/模型汇总、计价与未定价、每千字成本均值与 P90、补导去重 |
| `tests/server/test_admin.py` | `TestClient`：非管理员 403；用户列表与详情不含原文字段；停用后 token 立即 401 且不能登录；不能停用自己、不能移除最后一个管理员；月上限触发 429；重置密码后能用新密码登录；每个操作都写审计；价格表读写；命令行 `promote` |
| `tests/server/test_novels.py` 等 | 回归 |
| 前端 `tests/admin.test.tsx` | 桩后端：非管理员不显示「管理」；概览卡片与折线图渲染；用户表排序与搜索；停用操作带确认并刷新行；用量分组切换；失败任务展开报错 |
