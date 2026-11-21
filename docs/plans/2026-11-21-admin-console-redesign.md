# 运营后台结构与外观改造 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把管理后台从「一排页签按钮、只有一个地址」改成「左侧分组导航 + 右侧内容、每页有自己的地址」的运营后台：总览换成带副标题与行动链接的数字卡片、近 14 天趋势图和分布小卡片，其余五页统一标题行与空 / 加载 / 错误的样子；功能不变。

**Architecture:**
- 纯前端，不新增也不修改后端接口；所有数字来自 `frontend/src/api.ts` 里现有的 `admin*` 函数，拿不到的就不显示。
- 地址仍由 `frontend/src/paths.ts` 的 `parseLocation` 解析（一条通配路由不变）：`Loc` 的后台分支带上页与筛选，新增 `adminPath` 拼规范地址。
- 后台独立成一屏：`App.tsx` 在「地址是后台且用户是管理员」时渲染 `AdminView`，否则照旧渲染 `AppShell`（`AppShell.tsx` 不改）。`AdminView` 不碰路由，页与筛选从属性进来，跳转通过 `onNav(to, replace?)` 回调出去。
- 计算与界面分开：`components/admin/derive.ts` 放纯函数（副标题、分布、导航计数），界面拆成小组件（`PageHead`、`StatCard`、`AdminNav`…）。
- 任务页的筛选、用量页的分组与天数做成「可受控」：外框传值就听外框的（写进地址），不传就用组件内状态（现有测试的用法不变）。

**Tech Stack:** React 19、TypeScript、Vite 8、react-router 8（只在 `App.tsx` 用）、Tailwind 4 加 `styles/admin.css`、lucide-react、happy-dom；测试是 `vite build --ssr` 构建后交给 node 跑的脚本，断言用文件内的 `must` / `eq`（仓库**没有** vitest 和 testing-library，不要引入）。

**Spec:** `docs/specs/2026-11-21-admin-console-redesign-design.md`。下文用「§n」引用它的章节。

---

## 全局约束（每个 Task 都必须遵守）

- **只改本计划列出的文件**。不改后端（`backend/` 下任何文件）、不新增接口、不改 `frontend/src/api.ts`、`frontend/src/types.ts`、`frontend/src/components/shell/AppShell.tsx`。
- **不碰的文件与服务**：
  - 不读、不打印 `backend/.env`；
  - 不运行任何 smoke 脚本，不调用付费服务或真实大模型；
  - 不启动前后端服务，不向 5173 / 8000 端口发请求；
  - 不动、不提交 `docs/specs/2026-10-27-commercialization-design-contract.md`（未跟踪文件，保持原样）。
- **提交规则**：
  - 只 `git add <具体文件>`，禁止 `git add -A`、`git commit -a`、`git add -N`、`git stash`；
  - 提交信息用中文、描述性写法，**不得带 `Co-Authored-By`、`Claude-Session` 等任何署名尾行**；
  - 不 push。
- **每个 Task 提交前**：跑完该 Task 里列出的每一条命令并得到写明的结果，再在 `frontend/` 下跑一次 `npm run lint`，必须是 0 error、警告恰好是基线的 5 条（`VerificationPanel.tsx`、`CardPicker.tsx`、`timeline.ts`、`ParamsForm.tsx`、`App.tsx` 各一条），**不得增加**。整串 `npm test` 与 `npm run build` 放在 Task 9 跑（整串要几分钟）；Task 9 发现问题就修好后单独再提交一次。
- **film.test 已知偶发卡死**：`tests/film.test.tsx` 在改动前就有小概率 CPU 自旋不退出，或报「✗ 预览窗里播视频」。遇到时单独重跑判定：`npx vite build --ssr tests/film.test.tsx --outDir .ssrout-x --logLevel error && timeout 60 node .ssrout-x/film.test.js`，然后删掉 `.ssrout-x`。单独重跑能 `ALL PASS` 就不算本任务失败，在报告里注明。本计划不修它。
- **管理员才能看模型名**：后台是管理员页，用量页、用户详情、概览的未定价提醒与按模型分布照旧显示模型名。**不要**把这些内容带到产品外壳或任何普通用户能看到的界面。
- **现有功能不变**：用户的停用 / 角色 / 上限 / 重置密码、用量的导出与价格表、任务的调试日志、错误的查找与详情、审计，行为与文案都不改，只换外框与排版。不顺手重构。
- **不加新统计、不加新模块**：spec §5.4 列出的「拿不到所以不显示」的数字，不要想办法补。
- 代码块里的内容照抄即可，它们已在仓库的一份临时副本上按 Task 顺序整套跑通（每个 Task 的失败与通过、最后的 `npm test`、`npm run lint`、`npm run build`）。如果照抄后某一步的结果与本计划写的「Expected」不符，先核对是否抄漏，再报告，不要自行改设计。

## 先读这一节：仓库里与本任务有关的事实

- **测试怎么跑**。`frontend/package.json` 的 `test` 脚本是一长串 `vite build --ssr tests/x --outDir .ssrout --logLevel error && node .ssrout/x.js`，前面先跑 `npm run typecheck`（`tsc -b --force`）。**类型检查只覆盖 `src`，不检查 `tests`** —— 测试文件里的类型错误不会让任何命令失败，所以「确认失败」的步骤都是真的去跑测试，而不是跑类型检查。**新增的测试文件必须追加到这串脚本末尾，否则 `npm test` 不会跑它。**
  - 单独跑一个测试（在 `frontend/` 下）：`npx vite build --ssr tests/<文件名> --outDir .ssrout --logLevel error && node .ssrout/<去掉扩展名>.js`
  - 通过的标志是最后打印 `ALL PASS` 且退出码为 0；失败是抛出 `✗ …` 的错误，或构建报 `Module not found` / `Missing export`。
  - `.ssrout` 已在 `.gitignore` 里。
- **界面测试的写法**。文件开头用 happy-dom 造一个 `Window` 并把 `window`、`document` 等挂到 `globalThis`，把 `fetch` 换成桩后端，再 `await import` React 与被测组件，用 `createRoot` + `act` 渲染，用 `container.querySelector` 断言。没有 `I18nProvider` 时界面是中文；包一层 `<I18nProvider initial="en">` 是英文，用完要 `setCurrentLocale('zh')` 改回来。
- **点链接要用可取消的事件**。新测试里的 `click` 用 `new win.MouseEvent('click', { bubbles: true, cancelable: true })`：后台内部链接是真的 `<a href>`，靠 `preventDefault` 拦下默认跳转；事件不可取消的话 happy-dom 会真的去跳转。
- **文案**。`frontend/src/i18n/zh.ts` 与 `en.ts` 的键必须一一对应：`Messages` 类型从 `zh` 推出来，`en` 少键或多键 `npm run typecheck` 会报错。组件里用 `const { t } = useI18n()` 取文案，`t('admin.nav.pages.users')`；带变量写成 `t('admin.overview.newIn7d', { n: 3 })`，文案里用 `{n}` 占位。键是动态拼的（如 `` t(`admin.nav.pages.${id}`) ``）时，`id` 的类型必须是字面量联合，TypeScript 才认。
- **后台现在的样子**。`frontend/src/components/admin/AdminView.tsx` 用一排按钮切六个页签（`Overview`、`Users`、`UsageTab`、`JobsTab`、`AuditTab`、`ErrorsTab`），渲染在产品外壳 `AppShell` 的内容区里；地址只有 `/admin`。各页用同目录的 `useLoad(fn, deps, everyMs?)` 取数，返回 `{ data, error, reload }`；`LoadState.tsx` 有 `TableSkeleton`、`ErrorBar`、`Segmented`；`format.ts` 有 `usd`、`int`、`when`、`day`。
- **路由**。`frontend/src/routes.tsx` 只有一条通配路由，位置由 `App.tsx` 调 `parseLocation(location.pathname, location.search)` 得到 `{ loc, fix }`；`fix` 非空时 `App` 会 `replace` 到它（这段逻辑已有，不用改）。`App.tsx` 里的 `go(to, { replace })` 是带离开拦截的跳转函数。
- **后台接口返回什么**（只读，不要改）：
  - `adminOverview()` → `{ users, active_7d, tokens_30d, cost_30d, running, failed_7d, daily: { day, cost_usd }[]（30 天，升序）, unpriced_models: string[] }`
  - `adminUsers()` → `AdminUserRow[]`（`created_at`、`role`、`disabled`…）
  - `adminJobs()` → `{ running: { status: 'queued' | 'running', … }[], failed: { created_at, … }[]（近 7 天，时间倒序） }`
  - `adminUsage(group, days)` → `{ rows: { label, calls, cost_usd, unpriced, records, … }[], … }`
  - `adminErrors()` → `ErrorRefRow[]`（最近 200 条，带 `at`）
- **lint**。`npm run lint` 用 oxlint；`react/only-export-components` 是警告：一个 `.tsx` 文件既导出组件又导出函数或非常量就会多一条警告。所以纯函数放 `.ts`（`derive.ts`、`navContext.ts`），`.tsx` 只导出组件与类型。数组里的 JSX 要有 `key`（`react/jsx-key`）。
- **样式**。后台的类名规则在 `frontend/src/styles/admin.css`（`.adm__*`），其余用 Tailwind 工具类。颜色用现成的 CSS 变量：`--card`、`--border`、`--background`、`--foreground`、`--ui-muted`、`--ui-muted-foreground`、`--primary`、`--destructive`、`--warning`、`--ring`。

## 怎么读下面的步骤

- 「新建 `路径`，内容如下（整份文件）」：创建这个文件，内容就是代码块里的全部。标题里写了「整份替换」的，是把已有文件的内容全部换成代码块里的。
- 「在 `路径` 里找到下面这段（这段在文件里只出现一次）… 整段替换为」：第一个代码块是文件里现有的原文（连缩进、空行一起），第二个代码块是替换后的内容。找不到原文时不要凭感觉改，先核对前面的步骤是否做完。
- 「整段删掉」：把第一个代码块里的内容从文件里删掉。
- `frontend/package.json` 的那两步：要找的原文是 `test` 脚本那一长行的**结尾**（从 ` && vite build --ssr tests/…` 起，到这一行结尾的双引号为止），做法是在结尾的双引号前面接上新测试的两条命令。
- 所有命令都从仓库根目录执行（命令自己会 `cd frontend`）。
- 「Expected: FAIL」的步骤是在确认测试确实先失败；看到写明的那种失败就继续，不要去「修」它。

## 文件一览

| 文件 | 变化 | 在哪个 Task |
| --- | --- | --- |
| `frontend/src/paths.ts` | 改：后台页与筛选、`adminPath`、`parseLocation` | 1 |
| `frontend/src/components/admin/derive.ts` | 新：纯计算 | 2 |
| `frontend/src/components/admin/navContext.ts` | 新：内部跳转的上下文 | 3 |
| `frontend/src/components/admin/AdminLink.tsx` | 新：后台内部链接 | 3 |
| `frontend/src/components/admin/PageHead.tsx` | 新：标题行、刷新按钮 | 3 |
| `frontend/src/components/admin/StatCard.tsx` | 新：数字卡片、分布卡片 | 3 |
| `frontend/src/components/admin/LoadState.tsx` | 改：统一空状态 `Empty`、错误条加卡片底 | 3 |
| `frontend/src/styles/admin.css` | 改：外框、导航、卡片等样式 | 3、8 |
| `frontend/src/components/admin/Overview.tsx` | 整份替换 | 4 |
| `frontend/src/i18n/zh.ts`、`frontend/src/i18n/en.ts` | 改：文案 | 4、5、6、8 |
| `frontend/src/components/admin/Users.tsx`、`ErrorsTab.tsx` | 改：标题行、空状态 | 5 |
| `frontend/src/components/admin/AuditTab.tsx` | 整份替换 | 5 |
| `frontend/src/components/admin/JobsTab.tsx` | 整份替换：筛选 | 6 |
| `frontend/src/components/admin/UsageTab.tsx` | 改：可受控的分组与天数 | 6 |
| `frontend/src/components/admin/AdminNav.tsx` | 新：侧栏与窄屏顶栏 | 7 |
| `frontend/src/components/admin/AdminView.tsx` | 整份替换：外框 | 8 |
| `frontend/src/App.tsx` | 改：渲染外框、返回产品、标题 | 8 |
| `frontend/tests/paths.test.ts` | 改 | 1 |
| `frontend/tests/admin-derive.test.ts` | 新 | 2 |
| `frontend/tests/admin-shell.test.tsx` | 新，之后每个 Task 追加 | 3 – 8 |
| `frontend/tests/admin.test.tsx` | 改三处 | 4、8 |
| `frontend/tests/routing.test.tsx`、`frontend/tests/flow.test.tsx` | 改 | 8 |
| `frontend/package.json` | 改：`test` 脚本末尾追加两个新测试 | 2、3 |

---

### Task 1: 后台子页的地址（paths.ts）

**Files:**
- 修改：`frontend/src/paths.ts`
- 测试：`frontend/tests/paths.test.ts`

- [ ] **Step 1: 写失败的测试（一）：引入 `adminPath`**

在 `frontend/tests/paths.test.ts` 里找到下面这段（这段在文件里只出现一次）：

```ts
import { chapterPath, novelPath, parseLocation, passState } from '../src/paths'
```

整段替换为：

```ts
import { adminPath, chapterPath, novelPath, parseLocation, passState } from '../src/paths'
```

- [ ] **Step 2: 写失败的测试（二）：`/admin` 的位置带上页与筛选**

在 `frontend/tests/paths.test.ts` 里找到下面这段（这段在文件里只出现一次）：

```ts
eq(parseLocation('/admin'), { loc: { kind: 'admin' }, fix: null }, '/admin 是后台')
```

整段替换为：

```ts
const adm = (page: string, o: Record<string, unknown> = {}) =>
  ({ kind: 'admin', page, state: null, group: 'user', days: 30, ...o })
eq(parseLocation('/admin'), { loc: adm('overview'), fix: null }, '/admin 是后台的运营概览')
```

- [ ] **Step 3: 写失败的测试（三）：各页地址、筛选参数、规范化**

在 `frontend/tests/paths.test.ts` 里找到下面这段（这段在文件里只出现一次）：

```ts
console.log('1. 顶层 ✓')
```

整段替换为：

```ts
console.log('1. 顶层 ✓')

// 1b. 后台各页与筛选
for (const page of ['users', 'usage', 'jobs', 'errors', 'audit']) {
  eq(parseLocation(`/admin/${page}`), { loc: adm(page), fix: null }, `/admin/${page} 是后台的一页`)
}
eq(parseLocation('/admin/overview'), { loc: adm('overview'), fix: '/admin' }, '概览的规范地址是 /admin')
eq(parseLocation('/admin/'), { loc: adm('overview'), fix: '/admin' }, '尾斜杠规范化')
eq(parseLocation('/admin/users/u1').loc, { kind: 'notFound' }, '后台页下面没有更深的路径')
eq(parseLocation('/admin/jobs', '?state=failed'), { loc: adm('jobs', { state: 'failed' }), fix: null }, '任务页按失败筛选')
eq(parseLocation('/admin/jobs', '?state=running'), { loc: adm('jobs', { state: 'running' }), fix: null }, '任务页按运行中筛选')
eq(parseLocation('/admin/jobs', '?state=bogus'), { loc: adm('jobs'), fix: '/admin/jobs' }, '非法筛选值去掉')
eq(parseLocation('/admin/users', '?state=failed'), { loc: adm('users'), fix: '/admin/users' }, '别的页不认 state')
eq(parseLocation('/admin/usage', '?group=model&days=7'), { loc: adm('usage', { group: 'model', days: 7 }), fix: null }, '用量页分组与天数')
eq(parseLocation('/admin/usage', '?days=7&group=model').fix, '/admin/usage?group=model&days=7', '参数顺序规范化')
eq(parseLocation('/admin/usage', '?group=user&days=30'), { loc: adm('usage'), fix: '/admin/usage' }, '缺省值不写进地址')
eq(parseLocation('/admin/usage', '?days=15'), { loc: adm('usage'), fix: '/admin/usage' }, '非法天数去掉')
eq(adminPath(), '/admin', '缺省是概览')
eq(adminPath('jobs', { state: 'failed' }), '/admin/jobs?state=failed', '任务筛选地址')
eq(adminPath('jobs', { state: null }), '/admin/jobs', '全部任务不带参数')
eq(adminPath('usage', { group: 'model' }), '/admin/usage?group=model', '用量分组地址')
eq(adminPath('usage', { group: 'user', days: 90 }), '/admin/usage?days=90', '用量天数地址')
eq(adminPath('users', { state: 'failed', group: 'model' }), '/admin/users', '别的页不带筛选参数')
console.log('1b. 后台各页与筛选 ✓')
```

- [ ] **Step 4: 跑测试，确认失败**

Run（在仓库根目录）：

```bash
cd frontend && npx vite build --ssr tests/paths.test.ts --outDir .ssrout --logLevel error && node .ssrout/paths.test.js
```

Expected: FAIL —— 构建报错：`adminPath` 在 `src/paths.ts` 里是 `Missing export`。

- [ ] **Step 5: 实现（一）：后台页与筛选的取值**

在 `frontend/src/paths.ts` 里找到下面这段（这段在文件里只出现一次）：

```ts
export type CanvasView = 'timeline' | 'graph'
```

整段替换为：

```ts
export type CanvasView = 'timeline' | 'graph'

/** 后台的页（/admin 是运营概览，其余是 /admin/<页>） */
export const ADMIN_PAGES = ['overview', 'users', 'usage', 'jobs', 'errors', 'audit'] as const
export type AdminPage = (typeof ADMIN_PAGES)[number]
/** 任务页的筛选（?state=）；null 为全部 */
export const JOB_STATES = ['running', 'failed'] as const
export type JobState = (typeof JOB_STATES)[number]
/** 用量页的分组（?group=，缺省 user）与天数（?days=，缺省 30） */
export const USAGE_GROUPS = ['user', 'day', 'model'] as const
export type UsageGroup = (typeof USAGE_GROUPS)[number]
export const USAGE_DAYS = [7, 30, 90] as const
export type UsageDays = (typeof USAGE_DAYS)[number]
```

- [ ] **Step 6: 实现（二）：`Loc` 的后台分支带上页与筛选**

在 `frontend/src/paths.ts` 里找到下面这段（这段在文件里只出现一次）：

```ts
  | { kind: 'admin' }
```

整段替换为：

```ts
  /** state 只在任务页有意义，group / days 只在用量页有意义；其它页取缺省值 */
  | { kind: 'admin'; page: AdminPage; state: JobState | null; group: UsageGroup; days: UsageDays }
```

- [ ] **Step 7: 实现（三）：`adminPath`**

在 `frontend/src/paths.ts` 里找到下面这段（这段在文件里只出现一次）：

```ts
/** replace 时透传的 state：去掉一次性的 vid / jobId / force */
```

整段替换为：

```ts
/** 后台地址：缺省值（概览页、全部任务、按用户、30 天）不写进地址 */
export function adminPath(page: AdminPage = 'overview', o: {
  state?: JobState | null; group?: UsageGroup | null; days?: UsageDays | null
} = {}): string {
  const p = page === 'overview' ? '/admin' : `/admin/${page}`
  const q = new URLSearchParams()
  if (page === 'jobs' && o.state) q.set('state', o.state)
  if (page === 'usage' && o.group && o.group !== 'user') q.set('group', o.group)
  if (page === 'usage' && o.days && o.days !== 30) q.set('days', String(o.days))
  const s = q.toString()
  return s ? `${p}?${s}` : p
}

/** replace 时透传的 state：去掉一次性的 vid / jobId / force */
```

- [ ] **Step 8: 实现（四）：`parseLocation` 解析后台子页**

在 `frontend/src/paths.ts` 里找到下面这段（这段在文件里只出现一次）：

```ts
  if (parts[0] === 'admin') return parts.length === 1 ? { loc: { kind: 'admin' }, fix: null } : notFound
```

整段替换为：

```ts
  if (parts[0] === 'admin') {
    if (parts.length > 2) return notFound
    const page = parts[1] ?? 'overview'
    if (!isIn(ADMIN_PAGES, page)) return notFound
    const q = new URLSearchParams(search)
    const state: JobState | null = page === 'jobs' && isIn(JOB_STATES, q.get('state')) ? (q.get('state') as JobState) : null
    const group: UsageGroup = page === 'usage' && isIn(USAGE_GROUPS, q.get('group')) ? (q.get('group') as UsageGroup) : 'user'
    const n = Number(q.get('days'))
    const days: UsageDays = page === 'usage' && (USAGE_DAYS as readonly number[]).includes(n) ? (n as UsageDays) : 30
    const canon = adminPath(page, { state, group, days })
    const here = pathname + (search && search !== '?' ? search : '')
    return { loc: { kind: 'admin', page, state, group, days }, fix: canon === here ? null : canon }
  }
```

- [ ] **Step 9: 跑类型检查与路由纯函数测试，确认通过**

Run（在仓库根目录）：

```bash
cd frontend && npm run typecheck && npx vite build --ssr tests/paths.test.ts --outDir .ssrout --logLevel error && node .ssrout/paths.test.js
```

Expected: 类型检查无输出错误；测试逐行打印到 `1b. 后台各页与筛选 ✓`，最后一行 `ALL PASS`。

- [ ] **Step 10: 跑路由集成测试，确认没有带坏**

Run（在仓库根目录）：

```bash
cd frontend && npx vite build --ssr tests/routing.test.tsx --outDir .ssrout --logLevel error && node .ssrout/routing.test.js
```

Expected: 最后一行 `ALL PASS`（`/admin` 仍然能打开旧的后台，App 只看 `loc.kind`）。

- [ ] **Step 11: 提交**

```bash
git add frontend/src/paths.ts frontend/tests/paths.test.ts
git commit -m "后台子页的地址：/admin 是运营概览，其余五页是 /admin/users、usage、jobs、errors、audit；任务页认 ?state=running|failed，用量页认 ?group= 与 ?days=；缺省值、非法值、乱序参数规范化到 adminPath 拼出的地址；更深的路径是 404；补路由纯函数测试"
```

---

### Task 2: 后台的纯计算（derive.ts）

**Files:**
- 新建：`frontend/src/components/admin/derive.ts`
- 测试：`frontend/tests/admin-derive.test.ts`（新建）
- 修改：`frontend/package.json`

- [ ] **Step 1: 写失败的测试**

新建 `frontend/tests/admin-derive.test.ts`，内容如下（整份文件）：

```ts
/** 后台纯计算：近 7 天判断、用户与任务统计、按模型占比、导航计数（设计 docs/specs/2026-11-21-admin-console-redesign-design.md §5、§6）。 */
import { badgeText, jobStats, modelShare, NAV_GROUPS, navCounts, sumLast, userStats, within } from '../src/components/admin/derive'
import { ADMIN_PAGES } from '../src/paths'
import type { AdminJobs, AdminOverview, AdminUserRow, ErrorRefRow, UsageGroupRow } from '../src/types'

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }
const eq = (a: unknown, b: unknown, msg: string) =>
  must(JSON.stringify(a) === JSON.stringify(b), `${msg}\n  得到 ${JSON.stringify(a)}\n  期望 ${JSON.stringify(b)}`)

const NOW = Date.parse('2026-11-21T12:00:00+00:00')
const ago = (days: number) => new Date(NOW - days * 86400000).toISOString()

// 1. 近 N 天
must(within(ago(6.9), 7, NOW) && within(ago(7), 7, NOW) && !within(ago(7.1), 7, NOW), '7 天以内含边界')
must(!within(null, 7, NOW) && !within(undefined, 7, NOW) && !within('', 7, NOW) && !within('不是时间', 7, NOW), '缺失或解析不了算不在')
must(within('2026-11-20T08:00:00+00:00', 7, NOW), '带时区的 ISO 时间')
console.log('1. 近 N 天 ✓')

// 2. 用户统计
const user = (extra: Partial<AdminUserRow>): AdminUserRow => ({
  id: 'u', username: 'u', role: 'user', disabled: false, created_at: ago(40), last_seen_at: null, has_password: true,
  monthly_cap_usd: null, novels: 0, chapters: 0, versions: 0, month_cost_usd: 0, ...extra })
eq(userStats([user({ role: 'admin' }), user({ created_at: ago(2) }), user({ created_at: ago(3), disabled: true }),
              user({ created_at: null })], NOW),
   { total: 4, newIn7d: 2, normal: 3, disabled: 1, admins: 1 }, '用户统计')
eq(userStats([], NOW), { total: 0, newIn7d: 0, normal: 0, disabled: 0, admins: 0 }, '没有用户')
console.log('2. 用户统计 ✓')

// 3. 任务统计
const running = (status: string) => ({ id: 'j', user_id: 'u', username: null, status, work_title: null, chapter: null,
  chars: null, created_at: null, elapsed_sec: null })
const failed = (at: string) => ({ id: 'v', user_id: 'u', username: null, novel_title: null, chapter_title: null,
  created_at: at, chars: 0, attempts: 1, error: '' })
const jobs: AdminJobs = { running: [running('running'), running('queued'), running('queued')], failed: [failed(ago(1)), failed(ago(3))] }
eq(jobStats(jobs), { queued: 2, running: 1, failed: 2, lastFailedAt: ago(1) }, '任务统计：排队 / 运行中 / 失败 / 最近一次')
eq(jobStats({ running: [], failed: [] }), { queued: 0, running: 0, failed: 0, lastFailedAt: null }, '没有任务')
console.log('3. 任务统计 ✓')

// 4. 最近 n 天金额
const daily = [1, 2, 3, 4].map((v, i) => ({ day: `2026-11-${18 + i}`, cost_usd: v }))
must(sumLast(daily, 2) === 7 && sumLast(daily, 10) === 10 && sumLast([], 7) === 0, '最近 n 天合计')
console.log('4. 最近 n 天金额 ✓')

// 5. 按模型占比
const row = (label: string, extra: Partial<UsageGroupRow>): UsageGroupRow => ({
  key: label, label, calls: 1, input: 0, output: 0, cache_read: 0, cache_write: 0, chars: 0,
  cost_usd: 0, unpriced: 0, records: 1, ...extra })
const share = modelShare([row('small', { cost_usd: 1, calls: 5 }), row('mystery', { unpriced: 3, records: 3, calls: 3 }),
                          row('big', { cost_usd: 3, calls: 2 }), row('part', { cost_usd: 0, unpriced: 1, records: 4 })])
eq(share.rows.map((r) => [r.label, r.cost, r.share, r.unpriced]),
   [['big', 3, 0.75, false], ['small', 1, 0.25, false], ['part', 0, 0, false], ['mystery', 0, 0, true]],
   '金额高的在前，整行未定价的排最后；部分未定价不算整行未定价')
must(share.calls === 11, '调用次数合计')
const many = modelShare(['a', 'b', 'c', 'd'].map((l, i) => row(l, { cost_usd: 4 - i })), 2)
eq(many.rows.map((r) => [r.label, r.cost, r.count]), [['a', 4, 1], ['b', 3, 1], [null, 3, 2]], '超过 top 个的合并成一项')
must(Math.abs(many.rows[2].share - 0.3) < 1e-9, '合并项的占比')
eq(modelShare([]), { rows: [], calls: 0 }, '没有用量')
must(modelShare([row('free', {})]).rows[0].share === 0, '合计为 0 时占比为 0（不除以 0）')
console.log('5. 按模型占比 ✓')

// 6. 导航计数
const ov = (extra: Partial<AdminOverview>): AdminOverview => ({ users: 1, active_7d: 1, tokens_30d: 0, cost_30d: 0,
  running: 0, failed_7d: 0, daily: [], unpriced_models: [], ...extra })
const ref = (at: string): ErrorRefRow => ({ ref: 'R', at, user_id: null, username: null, code: 'common.internal', params: {}, where: '' })
eq(navCounts(ov({ failed_7d: 2, unpriced_models: ['a', 'b', 'c'] }), [ref(ago(1)), ref(ago(6)), ref(ago(8))], NOW),
   { jobs: 2, usage: 3, errors: 2 }, '失败数、未定价模型数、近 7 天错误数')
eq(navCounts(ov({}), [ref(ago(30))], NOW), {}, '为 0 的不出现')
eq(navCounts(null, null, NOW), {}, '数据还没到')
eq(navCounts(null, [ref(ago(1))], NOW), { errors: 1 }, '概览没到，错误数照常')
must(badgeText(7) === '7' && badgeText(99) === '99' && badgeText(100) === '99+', '徽标文字')
console.log('6. 导航计数 ✓')

// 7. 导航分组覆盖全部页，且每页只出现一次
eq(NAV_GROUPS.map((g) => g.id), ['overview', 'people', 'ops'], '三个分组')
eq(NAV_GROUPS.flatMap((g) => g.pages).sort(), [...ADMIN_PAGES].sort(), '分组里的页 = 全部后台页')
console.log('7. 导航分组 ✓')

console.log('\nALL PASS')
```

- [ ] **Step 2: 跑测试，确认失败**

Run（在仓库根目录）：

```bash
cd frontend && npx vite build --ssr tests/admin-derive.test.ts --outDir .ssrout --logLevel error && node .ssrout/admin-derive.test.js
```

Expected: FAIL —— 构建报找不到 `../src/components/admin/derive`（`Could not resolve`）。

- [ ] **Step 3: 实现**

新建 `frontend/src/components/admin/derive.ts`，内容如下（整份文件）：

```ts
/** 后台的纯计算：只用现有接口返回的数据推导副标题、分布与导航计数（不依赖 React；单测见 tests/admin-derive.test.ts）。 */
import type { AdminPage } from '../../paths'
import type { AdminJobs, AdminOverview, AdminUserRow, DailyCost, ErrorRefRow, UsageGroupRow } from '../../types'

const DAY_MS = 86400000

/** iso 时间是否在 now 之前的 days 天以内；缺失或解析不了算不在 */
export function within(iso: string | null | undefined, days: number, now: number): boolean {
  if (!iso) return false
  const at = Date.parse(iso)
  return Number.isFinite(at) && at >= now - days * DAY_MS
}

export interface UserStats { total: number; newIn7d: number; normal: number; disabled: number; admins: number }

/** 用户列表 → 近 7 天新增、正常 / 已停用、管理员人数 */
export function userStats(users: AdminUserRow[], now: number): UserStats {
  const disabled = users.filter((u) => u.disabled).length
  return {
    total: users.length,
    newIn7d: users.filter((u) => within(u.created_at, 7, now)).length,
    normal: users.length - disabled,
    disabled,
    admins: users.filter((u) => u.role === 'admin').length,
  }
}

export interface JobStats { queued: number; running: number; failed: number; lastFailedAt: string | null }

/** 任务接口 → 排队中 / 运行中 / 近 7 天失败；failed 已按时间倒序，第一条就是最近一次 */
export function jobStats(jobs: AdminJobs): JobStats {
  const queued = jobs.running.filter((j) => j.status === 'queued').length
  return {
    queued,
    running: jobs.running.length - queued,
    failed: jobs.failed.length,
    lastFailedAt: jobs.failed[0]?.created_at ?? null,
  }
}

/** 最近 n 天的金额合计（daily 按天升序，最后一项是今天） */
export const sumLast = (daily: DailyCost[], n: number) =>
  daily.slice(-n).reduce((sum, d) => sum + d.cost_usd, 0)

export interface ModelShare {
  /** label 为 null = 排在 top 之外的合并项，count 是合并了几个模型 */
  rows: { label: string | null; cost: number; share: number; unpriced: boolean; count: number }[]
  calls: number
}

/** 按模型的用量行 → 金额占比（金额高的在前，整行未定价的排最后；超过 top 个的合并成一项） */
export function modelShare(rows: UsageGroupRow[], top = 5): ModelShare {
  const whole = (r: UsageGroupRow) => r.records > 0 && r.unpriced === r.records
  const total = rows.reduce((sum, r) => sum + r.cost_usd, 0)
  const share = (cost: number) => (total > 0 ? cost / total : 0)
  const sorted = [...rows].sort((a, b) => Number(whole(a)) - Number(whole(b)) || b.cost_usd - a.cost_usd)
  const out: ModelShare['rows'] = sorted.slice(0, top).map((r) => (
    { label: r.label, cost: r.cost_usd, share: share(r.cost_usd), unpriced: whole(r), count: 1 }))
  const rest = sorted.slice(top)
  if (rest.length) {
    const cost = rest.reduce((sum, r) => sum + r.cost_usd, 0)
    out.push({ label: null, cost, share: share(cost), unpriced: false, count: rest.length })
  }
  return { rows: out, calls: rows.reduce((sum, r) => sum + r.calls, 0) }
}

/** 导航项旁的计数：任务 = 近 7 天失败；用量 = 未定价模型数；错误 = 近 7 天的错误记录数。为 0 或数据没到就没有这一项 */
export function navCounts(overview: AdminOverview | null, errors: ErrorRefRow[] | null,
                          now: number): Partial<Record<AdminPage, number>> {
  const out: Partial<Record<AdminPage, number>> = {}
  if (overview && overview.failed_7d > 0) out.jobs = overview.failed_7d
  if (overview && overview.unpriced_models.length > 0) out.usage = overview.unpriced_models.length
  const recent = errors ? errors.filter((e) => within(e.at, 7, now)).length : 0
  if (recent > 0) out.errors = recent
  return out
}

/** 计数徽标的文字：超过 99 写 99+ */
export const badgeText = (n: number) => (n > 99 ? '99+' : String(n))

/** 导航分组：总览 / 用户与用量 / 运行 */
export const NAV_GROUPS: { id: 'overview' | 'people' | 'ops'; pages: AdminPage[] }[] = [
  { id: 'overview', pages: ['overview'] },
  { id: 'people', pages: ['users', 'usage'] },
  { id: 'ops', pages: ['jobs', 'errors', 'audit'] },
]
```

- [ ] **Step 4: 跑测试，确认通过**

Run（在仓库根目录）：

```bash
cd frontend && npx vite build --ssr tests/admin-derive.test.ts --outDir .ssrout --logLevel error && node .ssrout/admin-derive.test.js
```

Expected: 打印 `1.` 到 `7.` 七行 ✓，最后一行 `ALL PASS`。

- [ ] **Step 5: 把新测试接进 `npm test`（`frontend/package.json` 的 `test` 脚本末尾）**

在 `frontend/package.json` 里找到下面这段（这段在文件里只出现一次）：

```json
 && vite build --ssr tests/sheet-view.test.tsx --outDir .ssrout --logLevel error && node .ssrout/sheet-view.test.js"
```

整段替换为：

```json
 && vite build --ssr tests/sheet-view.test.tsx --outDir .ssrout --logLevel error && node .ssrout/sheet-view.test.js && vite build --ssr tests/admin-derive.test.ts --outDir .ssrout --logLevel error && node .ssrout/admin-derive.test.js"
```

- [ ] **Step 6: 跑类型检查**

Run（在仓库根目录）：

```bash
cd frontend && npm run typecheck
```

Expected: 无错误输出。

- [ ] **Step 7: 提交**

```bash
git add frontend/src/components/admin/derive.ts frontend/tests/admin-derive.test.ts frontend/package.json
git commit -m "后台的纯计算 derive.ts：近 N 天判断、用户统计（近 7 天新增、正常 / 已停用、管理员数）、任务统计（排队 / 运行中 / 失败 / 最近一次失败）、最近 n 天金额、按模型的金额占比（前 5 个，其余合并）、导航计数与徽标文字、导航分组；补单测并接进 npm test"
```

---

### Task 3: 公共小组件与样式（标题行、数字卡片、分布卡片、空状态、内部链接）

**Files:**
- 新建：`frontend/src/components/admin/navContext.ts`、`AdminLink.tsx`、`PageHead.tsx`、`StatCard.tsx`（同目录）
- 修改：`frontend/src/components/admin/LoadState.tsx`、`frontend/src/styles/admin.css`、`frontend/package.json`
- 测试：`frontend/tests/admin-shell.test.tsx`（新建；后面的任务往里追加用例）

- [ ] **Step 1: 写失败的测试（新建测试文件：桩后端、工具函数、第 1 组用例）**

新建 `frontend/tests/admin-shell.test.tsx`，内容如下（整份文件）：

```tsx
/** 运营后台改版的界面回归：公共小组件、概览卡片、各页标题行与筛选、导航外框（地址、计数、收起、窄屏、中英文）。
 *  用桩后端代替 /admin 接口；时间都相对当前时刻生成，「近 7 天」的统计才有数。
 *
 *  跑法：npm test
 */
import { Window } from 'happy-dom'

const win = new Window({ url: 'http://localhost:5173' })
const g = globalThis as Record<string, unknown>
for (const k of ['window', 'document', 'navigator', 'location', 'HTMLElement',
                 'Element', 'Node', 'Event', 'CustomEvent', 'KeyboardEvent', 'getComputedStyle',
                 'localStorage', 'sessionStorage', 'PointerEvent', 'MouseEvent', 'matchMedia', 'ResizeObserver',
                 'DOMRect', 'MutationObserver']) {
  Object.defineProperty(g, k, {
    value: (win as unknown as Record<string, unknown>)[k],
    writable: true, configurable: true,
  })
}
g.IS_REACT_ACT_ENVIRONMENT = true
g.requestAnimationFrame = (cb: (t: number) => void) =>
  setTimeout(() => cb(performance.now()), 16) as unknown as number
g.cancelAnimationFrame = (id: number) => clearTimeout(id)

/* ---------- 桩后端 ---------- */
const NOW = Date.now()
const ago = (days: number) => new Date(NOW - days * 86400000).toISOString()
const calls: string[] = []
/** 让某个接口失败（值是路径前缀），用来验证「拿不到就省略」 */
const failing = new Set<string>()
/** 概览接口的可调字段 */
const ov = { failed_7d: 3, unpriced_models: ['mystery'] as string[] }
// 近 30 天每日金额：最近 7 天每天 1 美元，更早每天 0.5 美元（合计 18.5）
const daily = Array.from({ length: 30 }, (_, i) => ({ day: ago(29 - i).slice(0, 10), cost_usd: i >= 23 ? 1 : 0.5 }))
const userRow = (id: string, extra: Record<string, unknown>) => ({
  id: `u-${id}`, username: id, role: 'user', disabled: false, created_at: ago(40), last_seen_at: ago(1),
  has_password: true, monthly_cap_usd: null, novels: 1, chapters: 1, versions: 1, month_cost_usd: 1, ...extra })
const users = [
  userRow('root', { role: 'admin' }),
  userRow('bob', { created_at: ago(2) }),
  userRow('amy', { created_at: ago(10), disabled: true, last_seen_at: null }),
]
const usageRow = (label: string, extra: Record<string, unknown>) => ({
  key: label, label, calls: 1, input: 10, output: 20, cache_read: 0, cache_write: 0, chars: 100,
  cost_usd: 0, unpriced: 0, records: 1, ...extra })
g.fetch = async (url: string, init?: { method?: string; body?: string }) => {
  const path = String(url).replace(/^\/api/, '')
  const method = init?.method ?? 'GET'
  calls.push(`${method} ${path}`)
  const json = (data: unknown) => ({ ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(data)),
                                     text: async () => JSON.stringify(data) })
  const err = (status: number, detail: unknown) => ({
    ok: false, status, text: async () => JSON.stringify({ detail }), json: async () => ({ detail }) })
  if ([...failing].some((p) => path.startsWith(p))) {
    return err(500, { code: 'common.internal', params: {}, message: '服务器出了点问题，请稍后再试' })
  }
  if (path === '/admin/overview') return json({ users: 3, active_7d: 2, tokens_30d: 1234567, cost_30d: 18.5,
    running: 2, failed_7d: ov.failed_7d, daily, unpriced_models: ov.unpriced_models })
  if (path === '/admin/users') return json({ users })
  if (path === '/admin/jobs') return json({
    running: [{ id: 'j1', user_id: 'u-bob', username: 'bob', status: 'running', work_title: '药', chapter: '第一章',
                chars: 4000, created_at: ago(0.01), elapsed_sec: 75 },
              { id: 'j2', user_id: 'u-bob', username: 'bob', status: 'queued', work_title: '药', chapter: '第二章',
                chars: 3000, created_at: ago(0.01), elapsed_sec: 5 }],
    failed: [1, 2, 3].map((n) => ({ id: `v${n}`, user_id: 'u-amy', username: 'amy', novel_title: '孔乙己',
      chapter_title: `第 ${n} 回`, created_at: ago(n), chars: 900, attempts: 3, error: `失败原因 ${n}` })) })
  if (path.startsWith('/admin/usage')) {
    const q = new URL('http://x' + path).searchParams
    const group = q.get('group')
    return json({ group, days: Number(q.get('days')), per_k_chars: { n: 2, mean: 0.75, p90: 3 }, unpriced_models: ov.unpriced_models,
      rows: group === 'model' ? [
        usageRow('claude-sonnet-5', { calls: 30, cost_usd: 13.5 }),
        usageRow('other-model', { calls: 10, cost_usd: 4.5 }),
        usageRow('mystery', { calls: 2, unpriced: 2, records: 2 }),
      ] : [usageRow(group === 'user' ? 'bob' : ago(0).slice(0, 10), { calls: 42, cost_usd: 18 })] })
  }
  if (path === '/admin/errors') return json({ errors: [1, 2, 20].map((n) => ({
    ref: `REF0000${n}`, at: ago(n), user_id: 'u-bob', username: 'bob', code: 'common.internal', params: {}, where: 'GET /novels' })) })
  if (path === '/admin/audit') return json({ audit: [
    { at: ago(1), admin: 'root', action: 'disable', target: 'amy', before: { disabled: false }, after: { disabled: true } }] })
  if (path === '/admin/pricing') return json({ currency: 'USD', updated_at: null,
    models: { 'claude-sonnet-5': { input: 2, output: 10, cache_read: 0.2, cache_write: 2.5 } } })
  throw new Error(`桩后端未实现的路径: ${method} ${path}`)
}

const { act } = await import('react')
const { createRoot } = await import('react-dom/client')
import type { ReactNode } from 'react'

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }
const container = win.document.createElement('div')
win.document.body.appendChild(container)
let root = createRoot(container as unknown as HTMLElement)
const settle = async (ms = 30) => {
  await act(async () => { await new Promise((r) => setTimeout(r, ms)) })
}
const text = () => container.textContent ?? ''
const byId = (id: string) => container.querySelector(`[data-testid="${id}"]`)
/** 某个 data-testid 节点的文字；不存在返回 null */
const textOf = (id: string) => byId(id)?.textContent ?? null
const hrefOf = (id: string) => byId(id)?.querySelector('a')?.getAttribute('href') ?? null
const button = (label: string) => {
  const b = [...container.querySelectorAll('button')].find((x) => (x.textContent ?? '').trim() === label)
  if (!b) throw new Error(`✗ 找不到按钮「${label}」`)
  return b as unknown as HTMLButtonElement
}
// cancelable：链接的点击要能被 preventDefault 拦下，否则 happy-dom 会真的去跳转
const click = async (el: unknown) => {
  await act(async () => {
    (el as EventTarget).dispatchEvent(new win.MouseEvent('click', { bubbles: true, cancelable: true }) as unknown as Event)
  })
  await settle()
}
const remount = async (node: ReactNode) => {
  await act(async () => { root.unmount() })
  root = createRoot(container as unknown as HTMLElement)
  await act(async () => { root.render(node) })
  await settle()
}

// 1. 公共小组件：标题行、数字卡片、分布卡片、空状态、后台内部链接
{
  const { AdminNavContext } = await import('../src/components/admin/navContext')
  const { PageHead, RefreshButton } = await import('../src/components/admin/PageHead')
  const { StatCard, DistCard } = await import('../src/components/admin/StatCard')
  const { Empty } = await import('../src/components/admin/LoadState')
  const log: string[] = []
  await remount(
    <AdminNavContext.Provider value={(to, replace) => { log.push(`${replace ? 'replace' : 'push'} ${to}`) }}>
      <PageHead title="页名" hint="一行说明">
        <RefreshButton label="刷新" onClick={() => { log.push('refresh') }} />
      </PageHead>
      <StatCard id="a" label="失败" value="3" sub="最近一次 10-01" bad to="/admin/jobs?state=failed" action="去处理" />
      <StatCard id="b" label="用户" value="5" />
      <DistCard id="d" title="分布" empty="暂无数据" note="备注" to="/admin/users" action="查看"
                rows={[{ label: '正常', value: '2', share: 2 / 3 }, { label: '已停用', value: '1', share: 1 / 3 }]} />
      <DistCard id="e" title="空分布" empty="暂无数据" rows={[]} />
      <Empty title="还没有记录" hint="以后会出现在这里" />
    </AdminNavContext.Provider>)
  must(container.querySelector('h2')!.textContent === '页名' && text().includes('一行说明'), '标题行：页名与说明')
  await click(button('刷新'))
  must(log.join() === 'refresh', '标题行右侧的刷新按钮')
  const a = byId('stat-a')!
  must(['失败', '3', '最近一次 10-01', '去处理'].every((s) => a.textContent!.includes(s)), `数字卡片内容，实为 ${a.textContent}`)
  must(a.querySelector('b')!.className.includes('text-destructive'), 'bad 的数字标红')
  must(hrefOf('stat-a') === '/admin/jobs?state=failed', '行动链接是真链接')
  await click(a.querySelector('a')!)
  must(log[log.length - 1] === 'push /admin/jobs?state=failed', `点链接走后台内部跳转，实为 ${log}`)
  const b = byId('stat-b')!
  must(!b.querySelector('a') && !b.querySelector('.adm__sub'), '没给副标题和链接就不渲染')
  const fills = [...byId('dist-d')!.querySelectorAll('.adm__dist-fill')].map((el) => el.getAttribute('style') ?? '')
  must(fills.length === 2 && fills[0].includes('67%') && fills[1].includes('33%'), `占比条宽度，实为 ${fills}`)
  must(textOf('dist-d')!.includes('备注') && hrefOf('dist-d') === '/admin/users', '分布卡片的备注与链接')
  must(textOf('dist-e')!.includes('暂无数据'), '没有行时显示空文字')
  must((container.querySelector('.adm__emptycard [data-testid="empty-state"]')?.textContent ?? '').includes('还没有记录'), '空状态带卡片底')
  console.log('1. 公共小组件 ✓')
}

// ===== 追加点：后面的任务把新用例插在这一行上面 =====

await act(async () => { root.unmount() })
console.log('\nALL PASS')
```

- [ ] **Step 2: 跑测试，确认失败**

Run（在仓库根目录）：

```bash
cd frontend && npx vite build --ssr tests/admin-shell.test.tsx --outDir .ssrout --logLevel error && node .ssrout/admin-shell.test.js
```

Expected: FAIL —— 构建报找不到 `../src/components/admin/navContext`（`Could not resolve`）。

- [ ] **Step 3: 实现（一）：后台内部跳转的上下文**

新建 `frontend/src/components/admin/navContext.ts`，内容如下（整份文件）：

```ts
import { createContext } from 'react'

/** 后台内部跳转：to 是 adminPath() 拼出的地址；replace 为 true 时不留历史（改筛选用） */
export type AdminNavFn = (to: string, replace?: boolean) => void

/** AdminView 提供；没有提供者时（单独渲染某一页）AdminLink 就是普通链接 */
export const AdminNavContext = createContext<AdminNavFn | null>(null)
```

- [ ] **Step 4: 实现（二）：后台内部链接**

新建 `frontend/src/components/admin/AdminLink.tsx`，内容如下（整份文件）：

```tsx
import { useContext } from 'react'
import type { ComponentProps, MouseEvent } from 'react'
import { AdminNavContext } from './navContext'

/** 后台内部链接：真链接（可在新标签页打开），普通左键点击走前端路由。 */
export function AdminLink({ to, onClick, ...rest }: { to: string } & Omit<ComponentProps<'a'>, 'href'>) {
  const nav = useContext(AdminNavContext)
  const click = (e: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(e)
    if (!nav || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return
    e.preventDefault()
    nav(to)
  }
  return <a href={to} onClick={click} {...rest} />
}
```

- [ ] **Step 5: 实现（三）：标题行与刷新按钮**

新建 `frontend/src/components/admin/PageHead.tsx`，内容如下（整份文件）：

```tsx
import type { ReactNode } from 'react'
import { RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'

/** 后台每一页的标题行：左边页名（可带一行说明），右边操作。 */
export function PageHead({ title, hint, children }: { title: string; hint?: string; children?: ReactNode }) {
  return (
    <div className="adm__pagehead">
      <div className="min-w-0">
        <h2 className="text-lg font-semibold">{title}</h2>
        {hint && <p className="adm__note">{hint}</p>}
      </div>
      {children && <div className="adm__bar">{children}</div>}
    </div>
  )
}

export function RefreshButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <Button size="sm" variant="outline" type="button" onClick={onClick}>
      <RefreshCw aria-hidden />{label}
    </Button>
  )
}
```

- [ ] **Step 6: 实现（四）：数字卡片与分布卡片**

新建 `frontend/src/components/admin/StatCard.tsx`，内容如下（整份文件）：

```tsx
import type { ReactNode } from 'react'
import { ArrowRight } from 'lucide-react'
import { Card } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import { AdminLink } from './AdminLink'

/** 数字卡片：标签、大数字、副标题（拿不到就不传）、行动链接。 */
export function StatCard({ id, label, value, sub, bad, to, action, children }: {
  id: string; label: string; value: string; sub?: string | null; bad?: boolean
  to?: string; action?: string; children?: ReactNode
}) {
  return (
    <Card className="adm__card gap-1 px-4 py-3" data-testid={`stat-${id}`}>
      <span className="text-xs text-muted-foreground">{label}</span>
      <b className={cn('font-mono text-2xl font-semibold tabular-nums', bad && 'text-destructive')}>{value}</b>
      {sub && <span className="adm__sub">{sub}</span>}
      {children}
      {to && action && (
        <AdminLink to={to} className="adm__go">{action}<ArrowRight size={12} aria-hidden /></AdminLink>
      )}
    </Card>
  )
}

export interface DistRow { label: string; value: string; share: number }

/** 分布小卡片：每行一个标签、一个数和一条占比条（share 取 0 到 1）。 */
export function DistCard({ id, title, rows, empty, note, to, action }: {
  id: string; title: string; rows: DistRow[]; empty: string; note?: string | null; to?: string; action?: string
}) {
  return (
    <Card className="adm__card gap-2 px-4 py-3" data-testid={`dist-${id}`}>
      <h3 className="text-sm font-semibold">{title}</h3>
      {rows.length === 0 && <p className="adm__note">{empty}</p>}
      {rows.map((r) => (
        <div key={r.label} className="adm__dist">
          <span className="min-w-0 truncate" title={r.label}>{r.label}</span>
          <span className="font-mono tabular-nums">{r.value}</span>
          <span className="adm__dist-track" aria-hidden>
            <span className="adm__dist-fill" style={{ width: `${Math.round(Math.min(Math.max(r.share, 0), 1) * 100)}%` }} />
          </span>
        </div>
      ))}
      {note && <p className="adm__note">{note}</p>}
      {to && action && (
        <AdminLink to={to} className="adm__go">{action}<ArrowRight size={12} aria-hidden /></AdminLink>
      )}
    </Card>
  )
}
```

- [ ] **Step 7: 实现（五）：`LoadState.tsx` 的引入**

在 `frontend/src/components/admin/LoadState.tsx` 里找到下面这段（这段在文件里只出现一次）：

```tsx
/** 后台各页共用的加载骨架与错误条。 */
import { Button } from '@/components/ui/button'
```

整段替换为：

```tsx
/** 后台各页共用的加载骨架、错误条与空状态。 */
import { Inbox } from 'lucide-react'
import { EmptyState } from '@/components/common/EmptyState'
import { Button } from '@/components/ui/button'
```

- [ ] **Step 8: 实现（六）：错误条加卡片底，新增统一的空状态 `Empty`**

在 `frontend/src/components/admin/LoadState.tsx` 里找到下面这段（这段在文件里只出现一次）：

```tsx
    <div className="flex items-center gap-3 py-3 text-sm text-destructive">
      <span className="adm__err">{formatMsg(error, locale)}</span>
      <Button size="sm" variant="outline" onClick={onRetry}>{t('common.retry')}</Button>
    </div>
  )
}
```

整段替换为：

```tsx
    <div className="adm__errbar flex items-center gap-3 px-4 py-3 text-sm text-destructive">
      <span className="adm__err">{formatMsg(error, locale)}</span>
      <Button size="sm" variant="outline" onClick={onRetry}>{t('common.retry')}</Button>
    </div>
  )
}

/** 空状态：各页统一用这一个（收件箱图标 + 一句话 + 可选的说明），带卡片底。 */
export function Empty({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="adm__emptycard">
      <EmptyState icon={<Inbox aria-hidden />} title={title} hint={hint} />
    </div>
  )
}
```

- [ ] **Step 9: 样式（一）：内容区在外框里撑满剩余宽度**

在 `frontend/src/styles/admin.css` 里找到下面这段（这段在文件里只出现一次）：

```css
.adm { max-width: 1180px; margin: 0 auto; padding: 18px 22px 40px; }
```

整段替换为：

```css
.adm { flex: 1; min-width: 0; width: 100%; max-width: 1180px; margin: 0 auto; padding: 22px 26px 48px; }
```

- [ ] **Step 10: 样式（二）：表头不折行**

在 `frontend/src/styles/admin.css` 里找到下面这段（这段在文件里只出现一次）：

```css
.adm__table th { font-size: 12px; font-weight: 600; color: var(--ui-muted-foreground); background: var(--ui-muted); }
```

整段替换为：

```css
.adm__table th {
  font-size: 12px; font-weight: 600; white-space: nowrap; color: var(--ui-muted-foreground); background: var(--ui-muted);
}
```

- [ ] **Step 11: 样式（三）：把文件末尾的减弱动效规则换成下面整段（新样式 + 扩充后的减弱动效规则）**

在 `frontend/src/styles/admin.css` 里找到下面这段（这段在文件里只出现一次）：

```css

@media (prefers-reduced-motion: reduce) {
  .adm__card, .adm__row { transition: none; }
}
```

整段替换为：

```css

/* ---------- 运营后台改版：外框、导航、标题行、数字卡片、分布卡片 ---------- */

/* 外框：左侧分组导航（窄屏为顶部一条）+ 右侧内容 */
.adm-shell { display: flex; min-height: 100vh; background: var(--background); color: var(--foreground); }
.adm-shell.is-narrow { flex-direction: column; }
.adm-shell.is-narrow .adm { padding: 16px 14px 40px; overflow-x: auto; }
.adm-side {
  position: sticky; top: 0; display: flex; flex: none; flex-direction: column; gap: 6px;
  width: 232px; height: 100vh; padding: 12px 10px; overflow-y: auto;
  background: var(--card); border-right: 1px solid var(--border); transition: width 200ms ease-out;
}
.adm-shell.is-collapsed .adm-side { width: 60px; align-items: center; }
.adm-side__head {
  display: flex; align-items: center; justify-content: space-between; gap: 8px; min-height: 36px; padding-left: 8px;
}
.adm-shell.is-collapsed .adm-side__head { padding-left: 0; }
.adm-side__foot {
  display: flex; align-items: center; gap: 2px; margin-top: auto; padding-top: 8px; border-top: 1px solid var(--border);
}
.adm-shell.is-collapsed .adm-side__foot { flex-direction: column; }
.adm-shell.is-collapsed .adm-side__user { display: none; }
.adm-nav { display: flex; flex-direction: column; gap: 12px; margin-top: 8px; }
.adm-nav__group { display: flex; flex-direction: column; gap: 2px; }
.adm-nav__title {
  margin: 0; padding: 0 10px 2px; font-size: 11px; font-weight: 600; letter-spacing: 0.04em;
  color: var(--ui-muted-foreground);
}
.adm-nav__item {
  position: relative; display: flex; align-items: center; gap: 10px; padding: 7px 10px; border-radius: 8px;
  font-size: 14px; color: var(--ui-muted-foreground); text-decoration: none;
  transition: background-color 150ms ease-out, color 150ms ease-out;
}
.adm-nav__item:hover { background: var(--ui-muted); color: var(--foreground); }
.adm-nav__item.is-on { background: var(--ui-muted); color: var(--foreground); font-weight: 600; }
.adm-nav__item:focus-visible { outline: 2px solid var(--ring); outline-offset: 1px; }
.adm-nav__badge {
  min-width: 20px; padding: 0 6px; border-radius: 999px; font-size: 11px; font-weight: 600; line-height: 18px;
  text-align: center; font-variant-numeric: tabular-nums; color: #fff; background: var(--destructive);
}
.adm-nav__badge.is-warn { color: oklch(0.25 0.05 75); background: var(--warning); }
.adm-shell.is-collapsed .adm-nav__badge {
  position: absolute; top: -2px; right: -4px; min-width: 16px; padding: 0 4px; font-size: 10px; line-height: 16px;
}
.adm-top {
  position: sticky; top: 0; z-index: 20; display: flex; align-items: center; gap: 8px; padding: 8px 12px;
  background: var(--card); border-bottom: 1px solid var(--border);
}
.adm-top__select {
  flex: 1; min-width: 0; height: 36px; padding: 0 10px; font-size: 14px; color: var(--foreground);
  background: var(--background); border: 1px solid var(--border); border-radius: 8px;
}

/* 每页的标题行：左边页名，右边操作 */
.adm__pagehead { display: flex; flex-wrap: wrap; align-items: flex-end; justify-content: space-between; gap: 10px 16px; }

/* 数字卡片的副标题与行动链接 */
.adm__sub { font-size: 12px; color: var(--ui-muted-foreground); }
.adm__go {
  display: inline-flex; align-items: center; align-self: flex-start; gap: 4px; margin-top: auto; padding-top: 6px;
  font-size: 12px; font-weight: 500; color: var(--primary); text-decoration: none;
}
.adm__go:hover { text-decoration: underline; }
.adm__warn--link {
  display: flex; align-items: center; justify-content: space-between; gap: 12px; color: inherit; text-decoration: none;
}
.adm__warn--link:hover { background: color-mix(in oklch, var(--warning) 14%, var(--ui-muted)); }
.adm__chartcard .adm__chart { border: none; border-radius: 0; background: none; }

/* 分布卡片：标签、数字、占比条 */
.adm__dist { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 2px 10px; font-size: 13px; }
.adm__dist-track { grid-column: 1 / -1; height: 4px; overflow: hidden; border-radius: 999px; background: var(--ui-muted); }
.adm__dist-fill { display: block; height: 100%; border-radius: 999px; background: var(--primary); }

/* 空状态与错误条：和表格一样的卡片底 */
.adm__emptycard, .adm__errbar {
  background: var(--card); border: 1px solid var(--border); border-radius: calc(var(--ui-radius) + 2px);
}

@media (prefers-reduced-motion: reduce) {
  .adm__card, .adm__row, .adm-side, .adm-nav__item { transition: none; }
}
```

- [ ] **Step 12: 跑测试，确认通过**

Run（在仓库根目录）：

```bash
cd frontend && npx vite build --ssr tests/admin-shell.test.tsx --outDir .ssrout --logLevel error && node .ssrout/admin-shell.test.js
```

Expected: 打印 `1. 公共小组件 ✓`，最后一行 `ALL PASS`。

- [ ] **Step 13: 把新测试接进 `npm test`（`frontend/package.json` 的 `test` 脚本末尾）**

在 `frontend/package.json` 里找到下面这段（这段在文件里只出现一次）：

```json
 && vite build --ssr tests/sheet-view.test.tsx --outDir .ssrout --logLevel error && node .ssrout/sheet-view.test.js && vite build --ssr tests/admin-derive.test.ts --outDir .ssrout --logLevel error && node .ssrout/admin-derive.test.js"
```

整段替换为：

```json
 && vite build --ssr tests/sheet-view.test.tsx --outDir .ssrout --logLevel error && node .ssrout/sheet-view.test.js && vite build --ssr tests/admin-derive.test.ts --outDir .ssrout --logLevel error && node .ssrout/admin-derive.test.js && vite build --ssr tests/admin-shell.test.tsx --outDir .ssrout --logLevel error && node .ssrout/admin-shell.test.js"
```

- [ ] **Step 14: 跑类型检查与后台原有测试，确认没有带坏**

Run（在仓库根目录）：

```bash
cd frontend && npm run typecheck && npx vite build --ssr tests/admin.test.tsx --outDir .ssrout --logLevel error && node .ssrout/admin.test.js
```

Expected: 类型检查无错误；后台原有测试最后一行 `ALL PASS`。

- [ ] **Step 15: 提交**

```bash
git add frontend/src/components/admin/navContext.ts frontend/src/components/admin/AdminLink.tsx frontend/src/components/admin/PageHead.tsx frontend/src/components/admin/StatCard.tsx frontend/src/components/admin/LoadState.tsx frontend/src/styles/admin.css frontend/tests/admin-shell.test.tsx frontend/package.json
git commit -m "后台公共小组件：标题行 PageHead 与刷新按钮、数字卡片 StatCard（副标题、行动链接、标红）、分布卡片 DistCard（占比条）、统一空状态 Empty、内部链接 AdminLink（真链接，左键走前端跳转）；错误条加卡片底；补外框、导航、卡片的样式；新建 admin-shell 测试并接进 npm test"
```

---

### Task 4: 运营概览改版（副标题、行动链接、14 天趋势、分布卡片）

**Files:**
- 修改（整份替换）：`frontend/src/components/admin/Overview.tsx`
- 修改：`frontend/src/i18n/zh.ts`、`frontend/src/i18n/en.ts`、`frontend/tests/admin.test.tsx`
- 测试：`frontend/tests/admin-shell.test.tsx`

- [ ] **Step 1: 写失败的测试：在 `frontend/tests/admin-shell.test.tsx` 追加第 2 组用例**

在 `frontend/tests/admin-shell.test.tsx` 里找到下面这段（这段在文件里只出现一次）：

```tsx
// ===== 追加点：后面的任务把新用例插在这一行上面 =====
```

整段替换为：

```tsx
// 英文用例要用的语言工具（下面各组共用）
const { I18nProvider } = await import('../src/i18n')
const { setCurrentLocale } = await import('../src/i18n/core')

// 2. 运营概览：卡片的副标题与行动链接、近 14 天趋势、分布卡片、未定价提醒可点
{
  const { Overview } = await import('../src/components/admin/Overview')
  const { when } = await import('../src/components/admin/format')
  await remount(<Overview />)
  must(container.querySelector('h2')!.textContent === '运营概览', '页名')
  must(textOf('stat-users')!.includes('近 7 天新增 1') && hrefOf('stat-users') === '/admin/users', `用户卡，实为 ${textOf('stat-users')}`)
  must(textOf('stat-active')!.includes('占全部用户 67%'), `活跃卡，实为 ${textOf('stat-active')}`)
  must(textOf('stat-cost')!.includes('$18.50') && textOf('stat-cost')!.includes('近 7 天 $7.00')
       && !!byId('stat-cost')!.querySelector('[data-testid="sparkline"]') && hrefOf('stat-cost') === '/admin/usage',
       `金额卡，实为 ${textOf('stat-cost')}`)
  must(textOf('stat-failed')!.includes(`最近一次 ${when(ago(1))}`) && textOf('stat-failed')!.includes('去处理')
       && hrefOf('stat-failed') === '/admin/jobs?state=failed', `失败卡，实为 ${textOf('stat-failed')} ${hrefOf('stat-failed')}`)
  must(byId('stat-failed')!.querySelector('b')!.className.includes('text-destructive'), '有失败时数字标红')
  must(textOf('stat-running')!.includes('其中排队 1') && hrefOf('stat-running') === '/admin/jobs?state=running', `运行中卡，实为 ${textOf('stat-running')}`)
  must(textOf('stat-tokens')!.includes('1,234,567') && textOf('stat-tokens')!.includes('30 天调用 42 次'), `token 卡，实为 ${textOf('stat-tokens')}`)
  must(byId('trend')!.querySelectorAll('.adm__chart circle').length === 14 && textOf('trend')!.includes('近 14 天每日金额'), '趋势图 14 个点')
  must(['排队中1', '运行中1', '近 7 天失败3'].every((s) => textOf('dist-jobs')!.includes(s)), `任务状态分布，实为 ${textOf('dist-jobs')}`)
  must(['正常2', '已停用1', '其中管理员 1 人'].every((s) => textOf('dist-users')!.includes(s)), `用户状态分布，实为 ${textOf('dist-users')}`)
  must(['claude-sonnet-5$13.50', 'other-model$4.50', 'mystery未定价'].every((s) => textOf('dist-models')!.includes(s))
       && hrefOf('dist-models') === '/admin/usage?group=model', `按模型分布，实为 ${textOf('dist-models')}`)
  const alert = byId('unpriced-alert')!
  must(alert.tagName === 'A' && alert.getAttribute('href') === '/admin/usage?group=model' && alert.textContent!.includes('mystery'),
       '未定价提醒是指向用量页的链接')
  console.log('2. 运营概览：副标题 / 行动链接 / 趋势 / 分布 / 未定价提醒 ✓')
}

// 2b. 拿不到就省略：某份数据取不到时，只少掉依赖它的副标题与分布卡片，其余照常
{
  const { Overview } = await import('../src/components/admin/Overview')
  failing.add('/admin/users')
  await remount(<Overview />)
  must(!text().includes('近 7 天新增') && !byId('dist-users') && !!byId('dist-jobs') && !!byId('dist-models')
       && textOf('stat-users')!.includes('3'), '用户列表取不到：没有新增副标题与用户分布')
  failing.clear(); failing.add('/admin/jobs')
  await remount(<Overview />)
  must(!text().includes('最近一次') && !text().includes('其中排队') && !byId('dist-jobs') && !!byId('dist-users'),
       '任务取不到：没有最近一次、排队数与任务分布')
  failing.clear(); failing.add('/admin/usage')
  await remount(<Overview />)
  must(!text().includes('30 天调用') && !byId('dist-models') && !!byId('dist-users'), '按模型用量取不到：没有调用次数与模型分布')
  failing.clear(); failing.add('/admin/users'); failing.add('/admin/jobs'); failing.add('/admin/usage')
  await remount(<Overview />)
  must(!container.querySelector('[data-testid^="dist-"]') && container.querySelectorAll('[data-testid^="stat-"]').length === 6,
       '三份都取不到：没有分布区，六张数字卡仍在')
  failing.clear()
  ov.failed_7d = 0; ov.unpriced_models = []
  await remount(<Overview />)
  must(!byId('unpriced-alert') && !byId('stat-failed')!.querySelector('b')!.className.includes('text-destructive'),
       '没有未定价模型就没有提醒条；没有失败不标红')
  ov.failed_7d = 3; ov.unpriced_models = ['mystery']
  console.log('2b. 拿不到就省略 ✓')
}

// 2c. 概览刷新按钮把四份数据都重新取一遍；英文文案
{
  const { Overview } = await import('../src/components/admin/Overview')
  await remount(<Overview />)
  calls.length = 0
  await click(button('刷新'))
  must(['GET /admin/overview', 'GET /admin/users', 'GET /admin/jobs', 'GET /admin/usage?group=model&days=30']
    .every((c) => calls.includes(c)), `刷新应重新请求四份数据，实为 ${calls}`)
  await remount(<I18nProvider initial="en"><Overview /></I18nProvider>)
  must(container.querySelector('h2')!.textContent === 'Dashboard' && textOf('stat-users')!.includes('1 new in the last 7 days')
       && textOf('stat-failed')!.includes('Review') && textOf('dist-users')!.includes('1 of them are admins'), `英文概览，实为 ${textOf('stat-users')}`)
  await act(async () => { root.unmount() })
  root = createRoot(container as unknown as HTMLElement)
  setCurrentLocale('zh')
  console.log('2c. 概览刷新 / 英文 ✓')
}

// ===== 追加点：后面的任务把新用例插在这一行上面 =====
```

- [ ] **Step 2: 跑测试，确认失败**

Run（在仓库根目录）：

```bash
cd frontend && npx vite build --ssr tests/admin-shell.test.tsx --outDir .ssrout --logLevel error && node .ssrout/admin-shell.test.js
```

Expected: FAIL —— 打印 `1. 公共小组件 ✓` 之后抛错（旧概览没有 `h2`，报 `Cannot read properties of null`）。

- [ ] **Step 3: 中文文案（一）：导航分组、页名、计数说明**

在 `frontend/src/i18n/zh.ts` 里找到下面这段（这段在文件里只出现一次）：

```ts
    tabs: { overview: '概览', users: '用户', usage: '用量', jobs: '任务', audit: '审计', errors: '错误记录' },
```

整段替换为：

```ts
    tabs: { overview: '概览', users: '用户', usage: '用量', jobs: '任务', audit: '审计', errors: '错误记录' },
    nav: {
      label: '后台导航', collapse: '收起导航', expand: '展开导航',
      groups: { overview: '总览', people: '用户与用量', ops: '运行' },
      pages: { overview: '运营概览', users: '用户', usage: '用量与花费', jobs: '任务', errors: '错误', audit: '审计' },
      counts: { jobs: '近 7 天失败 {n} 个', usage: '{n} 个模型未定价', errors: '近 7 天 {n} 条错误记录' },
    },
```

- [ ] **Step 4: 中文文案（二）：概览的副标题、行动链接、分布**

在 `frontend/src/i18n/zh.ts` 里找到下面这段（这段在文件里只出现一次）：

```ts
    overview: {
      users: '用户', active7d: '7 天活跃', tokens30d: '30 天 token', cost30d: '30 天金额',
      running: '运行中任务', failed7d: '7 天失败',
      unpriced: '未定价模型：{models}（不计入金额，可在「用量」页编辑价格表）',
      daily: '近 30 天每日金额',
      note: '金额按当前价格表估算。',
    },
```

整段替换为：

```ts
    overview: {
      users: '用户', active7d: '7 天活跃', tokens30d: '30 天 token', cost30d: '30 天金额',
      running: '运行中任务', failed7d: '7 天失败',
      newIn7d: '近 7 天新增 {n}', activeShare: '占全部用户 {pct}%', cost7d: '近 7 天 {amount}',
      lastFailed: '最近一次 {time}', queued: '其中排队 {n}', calls30d: '30 天调用 {n} 次',
      goUsers: '查看用户', goUsage: '查看用量', goFailed: '去处理', goRunning: '查看任务', goModels: '查看全部',
      unpriced: '未定价模型：{models}（不计入金额，点这里去「用量与花费」页编辑价格表）',
      trend: '近 14 天每日金额',
      refresh: '刷新',
      note: '金额按当前价格表估算。',
      dist: {
        jobs: '任务状态', users: '用户状态', models: '30 天金额 · 按模型',
        queued: '排队中', running: '运行中', failed: '近 7 天失败', normal: '正常', disabled: '已停用',
        admins: '其中管理员 {n} 人', other: '其他 {n} 个模型', empty: '暂无数据',
        jobsNote: '只统计排队、运行中与近 7 天失败的任务。',
      },
    },
```

- [ ] **Step 5: 英文文案（一）**

在 `frontend/src/i18n/en.ts` 里找到下面这段（这段在文件里只出现一次）：

```ts
    tabs: { overview: 'Overview', users: 'Users', usage: 'Usage', jobs: 'Jobs', audit: 'Audit', errors: 'Errors' },
```

整段替换为：

```ts
    tabs: { overview: 'Overview', users: 'Users', usage: 'Usage', jobs: 'Jobs', audit: 'Audit', errors: 'Errors' },
    nav: {
      label: 'Admin navigation', collapse: 'Collapse navigation', expand: 'Expand navigation',
      groups: { overview: 'Overview', people: 'Users & usage', ops: 'Operations' },
      pages: { overview: 'Dashboard', users: 'Users', usage: 'Usage & cost', jobs: 'Jobs', errors: 'Errors', audit: 'Audit' },
      counts: { jobs: '{n} failed in the last 7 days', usage: '{n} unpriced models', errors: '{n} errors in the last 7 days' },
    },
```

- [ ] **Step 6: 英文文案（二）**

在 `frontend/src/i18n/en.ts` 里找到下面这段（这段在文件里只出现一次）：

```ts
    overview: {
      users: 'Users', active7d: 'Active (7d)', tokens30d: 'Tokens (30d)', cost30d: 'Cost (30d)',
      running: 'Running jobs', failed7d: 'Failed (7d)',
      unpriced: 'Unpriced models: {models} (not counted in cost; edit the price table on the Usage tab)',
      daily: 'Daily cost, last 30 days',
      note: 'Cost is estimated from the current price table.',
    },
```

整段替换为：

```ts
    overview: {
      users: 'Users', active7d: 'Active (7d)', tokens30d: 'Tokens (30d)', cost30d: 'Cost (30d)',
      running: 'Running jobs', failed7d: 'Failed (7d)',
      newIn7d: '{n} new in the last 7 days', activeShare: '{pct}% of all users', cost7d: 'Last 7 days: {amount}',
      lastFailed: 'Latest: {time}', queued: '{n} queued', calls30d: '{n} calls in 30 days',
      goUsers: 'View users', goUsage: 'View usage', goFailed: 'Review', goRunning: 'View jobs', goModels: 'View all',
      unpriced: 'Unpriced models: {models} (not counted in cost; click to edit the price table under Usage & cost)',
      trend: 'Daily cost, last 14 days',
      refresh: 'Refresh',
      note: 'Cost is estimated from the current price table.',
      dist: {
        jobs: 'Job status', users: 'User status', models: 'Cost by model (30d)',
        queued: 'Queued', running: 'Running', failed: 'Failed (7d)', normal: 'Active', disabled: 'Disabled',
        admins: '{n} of them are admins', other: '{n} other models', empty: 'No data yet',
        jobsNote: 'Counts queued, running and last-7-day failed jobs only.',
      },
    },
```

- [ ] **Step 7: 实现：把 `frontend/src/components/admin/Overview.tsx` 整份替换**

把 `frontend/src/components/admin/Overview.tsx` 的内容全部换成下面这份（整份文件）：

```tsx
import { ArrowRight } from 'lucide-react'
import { adminJobs, adminOverview, adminUsage, adminUsers } from '../../api'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useI18n } from '@/i18n/core'
import type { MsgLike } from '@/i18n/serverMsg'
import { adminPath } from '../../paths'
import type { AdminOverview } from '../../types'
import { AdminLink } from './AdminLink'
import { jobStats, modelShare, sumLast, userStats } from './derive'
import { int, usd, when } from './format'
import { LineChart } from './LineChart'
import { ErrorBar } from './LoadState'
import { PageHead, RefreshButton } from './PageHead'
import { Sparkline } from './Sparkline'
import { DistCard, StatCard } from './StatCard'
import type { DistRow } from './StatCard'
import { useLoad } from './useLoad'

export interface Loaded<T> { data: T | null; error: MsgLike; reload: () => void }

/** 运营概览：数字卡片（副标题与行动链接）、近 14 天趋势、分布小卡片。
 *  shared 由外框传入（外框要用同一份数据算导航计数）；单独渲染时自己取，每 30 秒刷新。 */
export function Overview({ shared }: { shared?: Loaded<AdminOverview> }) {
  return shared ? <OverviewBody {...shared} /> : <OverviewSelf />
}

function OverviewSelf() {
  return <OverviewBody {...useLoad(adminOverview, [], 30000)} />
}

function OverviewBody({ data, error, reload }: Loaded<AdminOverview>) {
  const { t } = useI18n()
  // 副标题与分布要用的三份现有数据；哪份没取到，依赖它的那几处就不显示
  const users = useLoad(adminUsers, [])
  const jobs = useLoad(adminJobs, [])
  const byModel = useLoad(() => adminUsage('model', 30), [])
  const refresh = () => { reload(); users.reload(); jobs.reload(); byModel.reload() }
  const head = (
    <PageHead title={t('admin.nav.pages.overview')} hint={t('admin.overview.note')}>
      <RefreshButton label={t('admin.overview.refresh')} onClick={refresh} />
    </PageHead>
  )
  if (error) return <section className="adm__sec">{head}<ErrorBar error={error} onRetry={reload} /></section>
  if (!data) {
    return (
      <section className="adm__sec" aria-busy="true">
        {head}
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-[112px]" />)}
        </div>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Skeleton className="h-[112px]" /><Skeleton className="h-[112px]" />
          <Skeleton className="col-span-2 h-[168px]" />
        </div>
      </section>
    )
  }
  const us = users.data ? userStats(users.data, Date.now()) : null
  const js = jobs.data ? jobStats(jobs.data) : null
  const ms = byModel.data ? modelShare(byModel.data.rows) : null
  const pct = (part: number, total: number) => (total > 0 ? part / total : 0)

  const jobRows: DistRow[] = js ? [
    { label: t('admin.overview.dist.queued'), value: int(js.queued), share: pct(js.queued, js.queued + js.running + js.failed) },
    { label: t('admin.overview.dist.running'), value: int(js.running), share: pct(js.running, js.queued + js.running + js.failed) },
    { label: t('admin.overview.dist.failed'), value: int(js.failed), share: pct(js.failed, js.queued + js.running + js.failed) },
  ] : []
  const userRows: DistRow[] = us ? [
    { label: t('admin.overview.dist.normal'), value: int(us.normal), share: pct(us.normal, us.total) },
    { label: t('admin.overview.dist.disabled'), value: int(us.disabled), share: pct(us.disabled, us.total) },
  ] : []
  const modelRows: DistRow[] = ms ? ms.rows.map((r) => ({
    label: r.label ?? t('admin.overview.dist.other', { n: r.count }),
    value: r.unpriced ? t('admin.usage.unpricedCell') : usd(r.cost),
    share: r.share,
  })) : []

  return (
    <section className="adm__sec">
      {head}
      {data.unpriced_models.length > 0 && (
        <AdminLink to={adminPath('usage', { group: 'model' })} className="adm__warn adm__warn--link" data-testid="unpriced-alert">
          <span>{t('admin.overview.unpriced', { models: data.unpriced_models.join(t('common.listSep')) })}</span>
          <ArrowRight size={14} aria-hidden />
        </AdminLink>
      )}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard id="users" label={t('admin.overview.users')} value={int(data.users)}
                  sub={us ? t('admin.overview.newIn7d', { n: us.newIn7d }) : null}
                  to={adminPath('users')} action={t('admin.overview.goUsers')} />
        <StatCard id="active" label={t('admin.overview.active7d')} value={int(data.active_7d)}
                  sub={data.users > 0 ? t('admin.overview.activeShare', { pct: Math.round((data.active_7d / data.users) * 100) }) : null}
                  to={adminPath('users')} action={t('admin.overview.goUsers')} />
        <StatCard id="cost" label={t('admin.overview.cost30d')} value={usd(data.cost_30d)}
                  sub={data.daily.length > 0 ? t('admin.overview.cost7d', { amount: usd(sumLast(data.daily, 7)) }) : null}
                  to={adminPath('usage')} action={t('admin.overview.goUsage')}>
          <Sparkline values={data.daily.map((d) => d.cost_usd)} />
        </StatCard>
        <StatCard id="failed" label={t('admin.overview.failed7d')} value={int(data.failed_7d)} bad={data.failed_7d > 0}
                  sub={js?.lastFailedAt ? t('admin.overview.lastFailed', { time: when(js.lastFailedAt) }) : null}
                  to={adminPath('jobs', { state: 'failed' })} action={t('admin.overview.goFailed')} />
      </div>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard id="running" label={t('admin.overview.running')} value={int(data.running)}
                  sub={js ? t('admin.overview.queued', { n: js.queued }) : null}
                  to={adminPath('jobs', { state: 'running' })} action={t('admin.overview.goRunning')} />
        <StatCard id="tokens" label={t('admin.overview.tokens30d')} value={int(data.tokens_30d)}
                  sub={ms ? t('admin.overview.calls30d', { n: int(ms.calls) }) : null}
                  to={adminPath('usage')} action={t('admin.overview.goUsage')} />
        <Card className="adm__card adm__chartcard col-span-2 gap-2 px-4 py-3" data-testid="trend">
          <h3 className="text-sm font-semibold">{t('admin.overview.trend')}</h3>
          <LineChart height={120} label={t('admin.overview.trend')}
                     points={data.daily.slice(-14).map((d) => ({ label: d.day.slice(5), value: d.cost_usd }))} />
        </Card>
      </div>
      {(js || us || ms) && (
        <div className="grid gap-3 md:grid-cols-3">
          {js && (
            <DistCard id="jobs" title={t('admin.overview.dist.jobs')} rows={jobRows} empty={t('admin.overview.dist.empty')}
                      note={t('admin.overview.dist.jobsNote')}
                      to={adminPath('jobs')} action={t('admin.overview.goRunning')} />
          )}
          {us && (
            <DistCard id="users" title={t('admin.overview.dist.users')} rows={userRows} empty={t('admin.overview.dist.empty')}
                      note={t('admin.overview.dist.admins', { n: us.admins })}
                      to={adminPath('users')} action={t('admin.overview.goUsers')} />
          )}
          {ms && (
            <DistCard id="models" title={t('admin.overview.dist.models')} rows={modelRows} empty={t('admin.overview.dist.empty')}
                      to={adminPath('usage', { group: 'model' })} action={t('admin.overview.goModels')} />
          )}
        </div>
      )}
    </section>
  )
}
```

- [ ] **Step 8: 原有测试跟着改一处：趋势图从 30 天改成 14 天**

在 `frontend/tests/admin.test.tsx` 里找到下面这段（这段在文件里只出现一次）：

```tsx
must(container.querySelectorAll('.adm__chart circle').length === 30, '折线图 30 个点')
```

整段替换为：

```tsx
must(container.querySelectorAll('.adm__chart circle').length === 14, '趋势图近 14 天，14 个点')
```

- [ ] **Step 9: 跑测试，确认通过**

Run（在仓库根目录）：

```bash
cd frontend && npx vite build --ssr tests/admin-shell.test.tsx --outDir .ssrout --logLevel error && node .ssrout/admin-shell.test.js
```

Expected: 打印到 `2c. 概览刷新 / 英文 ✓`，最后一行 `ALL PASS`。

- [ ] **Step 10: 跑类型检查与后台原有测试**

Run（在仓库根目录）：

```bash
cd frontend && npm run typecheck && npx vite build --ssr tests/admin.test.tsx --outDir .ssrout --logLevel error && node .ssrout/admin.test.js
```

Expected: 类型检查无错误；后台原有测试最后一行 `ALL PASS`。

- [ ] **Step 11: 提交**

```bash
git add frontend/src/components/admin/Overview.tsx frontend/src/i18n/zh.ts frontend/src/i18n/en.ts frontend/tests/admin.test.tsx frontend/tests/admin-shell.test.tsx
git commit -m "运营概览改版：首行四张卡（用户、7 天活跃、30 天金额加趋势线、7 天失败）与第二行（运行中、30 天 token、近 14 天趋势图），每张卡带副标题与行动链接（失败 → /admin/jobs?state=failed 等）；分布区列任务状态、用户状态、30 天金额按模型；副标题与分布取自现有的用户、任务、按模型用量三个接口，哪份取不到就省略对应内容；未定价提醒条可点到按模型的用量页；补导航与概览的中英文案；原有测试的折线图点数改为 14"
```

---

### Task 5: 用户、错误、审计三页统一标题行与空状态

**Files:**
- 修改：`frontend/src/components/admin/Users.tsx`、`ErrorsTab.tsx`；整份替换 `AuditTab.tsx`（同目录）
- 修改：`frontend/src/i18n/zh.ts`、`frontend/src/i18n/en.ts`
- 测试：`frontend/tests/admin-shell.test.tsx`

- [ ] **Step 1: 写失败的测试：在 `frontend/tests/admin-shell.test.tsx` 追加第 3 组用例**

在 `frontend/tests/admin-shell.test.tsx` 里找到下面这段（这段在文件里只出现一次）：

```tsx
// ===== 追加点：后面的任务把新用例插在这一行上面 =====
```

整段替换为：

```tsx
// 3. 用户、错误、审计三页：统一的标题行（页名 + 刷新）与空状态
{
  const { Users } = await import('../src/components/admin/Users')
  const { ErrorsTab } = await import('../src/components/admin/ErrorsTab')
  const { AuditTab } = await import('../src/components/admin/AuditTab')
  const me = { id: 'u-root', username: 'root', created_at: '', role: 'admin' as const }
  const pages: [string, string, () => ReactNode][] = [
    ['用户', 'GET /admin/users', () => <Users me={me} />],
    ['错误', 'GET /admin/errors', () => <ErrorsTab />],
    ['审计', 'GET /admin/audit', () => <AuditTab />],
  ]
  for (const [name, req, page] of pages) {
    await remount(page())
    must(container.querySelector('.adm__pagehead h2')?.textContent === name, `「${name}」页的标题行`)
    const n = calls.filter((c) => c === req).length
    await click(button('刷新'))
    must(calls.filter((c) => c === req).length === n + 1, `「${name}」页的刷新应重新请求`)
    // 读取失败：标题行还在，下面是错误条
    failing.add(req.slice(4))
    await remount(page())
    must(container.querySelector('.adm__pagehead h2')?.textContent === name && text().includes('服务器出了点问题')
         && !!container.querySelector('.adm__errbar'), `「${name}」页读取失败时标题行仍在`)
    failing.clear()
  }
  console.log('3. 用户 / 错误 / 审计：标题行、刷新、读取失败 ✓')
}

// ===== 追加点：后面的任务把新用例插在这一行上面 =====
```

- [ ] **Step 2: 跑测试，确认失败**

Run（在仓库根目录）：

```bash
cd frontend && npx vite build --ssr tests/admin-shell.test.tsx --outDir .ssrout --logLevel error && node .ssrout/admin-shell.test.js
```

Expected: FAIL —— 报 `✗ 「用户」页的标题行`。

- [ ] **Step 3: 中文文案：用户页的刷新**

在 `frontend/src/i18n/zh.ts` 里找到下面这段（这段在文件里只出现一次）：

```ts
      search: '搜索用户名',
```

整段替换为：

```ts
      search: '搜索用户名', refresh: '刷新',
```

- [ ] **Step 4: 英文文案**

在 `frontend/src/i18n/en.ts` 里找到下面这段（这段在文件里只出现一次）：

```ts
      search: 'Search username',
```

整段替换为：

```ts
      search: 'Search username', refresh: 'Refresh',
```

- [ ] **Step 5: 用户页（一）：引入标题行**

在 `frontend/src/components/admin/Users.tsx` 里找到下面这段（这段在文件里只出现一次）：

```tsx
import { ErrorBar, TableSkeleton } from './LoadState'
```

整段替换为：

```tsx
import { ErrorBar, TableSkeleton } from './LoadState'
import { PageHead, RefreshButton } from './PageHead'
```

- [ ] **Step 6: 用户页（二）：加载中、读取失败时也有标题行**

在 `frontend/src/components/admin/Users.tsx` 里找到下面这段（这段在文件里只出现一次）：

```tsx
  if (error) return <ErrorBar error={error} onRetry={reload} />
  if (!data) return <section className="adm__sec"><TableSkeleton /></section>

  const needle = q.trim().toLowerCase()
```

整段替换为：

```tsx
  const pageHead = (
    <PageHead title={t('admin.nav.pages.users')}>
      <RefreshButton label={t('admin.users.refresh')} onClick={reload} />
    </PageHead>
  )
  if (error) return <section className="adm__sec">{pageHead}<ErrorBar error={error} onRetry={reload} /></section>
  if (!data) return <section className="adm__sec">{pageHead}<TableSkeleton /></section>

  const needle = q.trim().toLowerCase()
```

- [ ] **Step 7: 用户页（三）：正文最上面放标题行**

在 `frontend/src/components/admin/Users.tsx` 里找到下面这段（这段在文件里只出现一次）：

```tsx
    <section className="adm__sec">
      <div className="relative max-w-[260px]">
```

整段替换为：

```tsx
    <section className="adm__sec">
      {pageHead}
      <div className="relative max-w-[260px]">
```

- [ ] **Step 8: 错误页（一）：引入**

在 `frontend/src/components/admin/ErrorsTab.tsx` 里找到下面这段（这段在文件里只出现一次）：

```tsx
import { Inbox, RefreshCw, Search } from 'lucide-react'
import { EmptyState } from '@/components/common/EmptyState'
```

整段替换为：

```tsx
import { Search } from 'lucide-react'
```

- [ ] **Step 9: 错误页（二）：引入**

在 `frontend/src/components/admin/ErrorsTab.tsx` 里找到下面这段（这段在文件里只出现一次）：

```tsx
import { ErrorBar, TableSkeleton } from './LoadState'
```

整段替换为：

```tsx
import { Empty, ErrorBar, TableSkeleton } from './LoadState'
import { PageHead, RefreshButton } from './PageHead'
```

- [ ] **Step 10: 错误页（三）：统一的空状态**

在 `frontend/src/components/admin/ErrorsTab.tsx` 里找到下面这段（这段在文件里只出现一次）：

```tsx
  else if (!data.length) body = <EmptyState icon={<Inbox aria-hidden />} title={t('admin.errors.empty')} hint={t('admin.errors.emptyHint')} />
```

整段替换为：

```tsx
  else if (!data.length) body = <Empty title={t('admin.errors.empty')} hint={t('admin.errors.emptyHint')} />
```

- [ ] **Step 11: 错误页（四）：标题行放页名与刷新，查找表单留在下面**

在 `frontend/src/components/admin/ErrorsTab.tsx` 里找到下面这段（这段在文件里只出现一次）：

```tsx
    <section className="adm__sec">
      <form className="adm__bar" onSubmit={(e) => { e.preventDefault(); void lookup() }}>
        <Input className="adm__search h-9 w-64" value={q} onChange={(e) => setQ(e.target.value)}
               placeholder={t('admin.errors.placeholder')} aria-label={t('admin.errors.lookup')} />
        <Button size="sm" type="submit"><Search aria-hidden />{t('admin.errors.lookup')}</Button>
        <Button size="sm" variant="outline" type="button" onClick={reload}><RefreshCw aria-hidden />{t('admin.errors.refresh')}</Button>
      </form>
```

整段替换为：

```tsx
    <section className="adm__sec">
      <PageHead title={t('admin.nav.pages.errors')}>
        <RefreshButton label={t('admin.errors.refresh')} onClick={reload} />
      </PageHead>
      <form className="adm__bar" onSubmit={(e) => { e.preventDefault(); void lookup() }}>
        <Input className="adm__search h-9 w-64" value={q} onChange={(e) => setQ(e.target.value)}
               placeholder={t('admin.errors.placeholder')} aria-label={t('admin.errors.lookup')} />
        <Button size="sm" type="submit"><Search aria-hidden />{t('admin.errors.lookup')}</Button>
      </form>
```

- [ ] **Step 12: 审计页：把 `frontend/src/components/admin/AuditTab.tsx` 整份替换**

把 `frontend/src/components/admin/AuditTab.tsx` 的内容全部换成下面这份（整份文件）：

```tsx
import { Badge } from '@/components/ui/badge'
import { useI18n } from '@/i18n/core'
import { adminAudit } from '../../api'
import { ACTION, when } from './format'
import { Empty, ErrorBar, TableSkeleton } from './LoadState'
import { PageHead, RefreshButton } from './PageHead'
import { useLoad } from './useLoad'

const show = (v: Record<string, unknown> | null) => (v ? JSON.stringify(v) : '—')

/** 审计：管理操作记录，最新在前。 */
export function AuditTab() {
  const { t } = useI18n()
  const { data, error, reload } = useLoad(adminAudit, [])
  const c = (k: string) => t(`admin.audit.cols.${k}` as 'admin.audit.cols.time')
  let body
  if (error) body = <ErrorBar error={error} onRetry={reload} />
  else if (!data) body = <TableSkeleton />
  else if (!data.length) body = <Empty title={t('admin.audit.empty')} hint={t('admin.audit.emptyHint')} />
  else body = (
    <table className="adm__table">
      <thead>
        <tr><th>{c('time')}</th><th>{c('admin')}</th><th>{c('action')}</th><th>{c('target')}</th><th>{c('before')}</th><th>{c('after')}</th></tr>
      </thead>
      <tbody>
        {data.map((a, i) => (
          <tr key={i}>
            <td>{when(a.at)}</td><td>{a.admin}</td>
            <td><Badge variant="secondary">{ACTION[a.action] ?? a.action}</Badge></td>
            <td>{a.target ?? '—'}</td><td className="adm__json">{show(a.before)}</td><td className="adm__json">{show(a.after)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
  return (
    <section className="adm__sec">
      <PageHead title={t('admin.nav.pages.audit')}>
        <RefreshButton label={t('admin.audit.refresh')} onClick={reload} />
      </PageHead>
      {body}
    </section>
  )
}
```

- [ ] **Step 13: 跑测试，确认通过**

Run（在仓库根目录）：

```bash
cd frontend && npx vite build --ssr tests/admin-shell.test.tsx --outDir .ssrout --logLevel error && node .ssrout/admin-shell.test.js
```

Expected: 打印 `3. 用户 / 错误 / 审计：标题行、刷新、读取失败 ✓`，最后一行 `ALL PASS`。

- [ ] **Step 14: 跑类型检查与后台原有测试**

Run（在仓库根目录）：

```bash
cd frontend && npm run typecheck && npx vite build --ssr tests/admin.test.tsx --outDir .ssrout --logLevel error && node .ssrout/admin.test.js
```

Expected: 类型检查无错误；后台原有测试最后一行 `ALL PASS`。

- [ ] **Step 15: 提交**

```bash
git add frontend/src/components/admin/Users.tsx frontend/src/components/admin/ErrorsTab.tsx frontend/src/components/admin/AuditTab.tsx frontend/src/i18n/zh.ts frontend/src/i18n/en.ts frontend/tests/admin-shell.test.tsx
git commit -m "用户、错误、审计三页统一标题行：页名在左、刷新在右（用户页新增刷新），加载中与读取失败时标题行也在；空状态改用统一的 Empty；错误页的查找表单留在标题行下面；补界面测试"
```

---

### Task 6: 任务页按状态筛选，用量页的分组与天数可由地址控制

**Files:**
- 修改（整份替换）：`frontend/src/components/admin/JobsTab.tsx`
- 修改：`frontend/src/components/admin/UsageTab.tsx`、`frontend/src/i18n/zh.ts`、`frontend/src/i18n/en.ts`
- 测试：`frontend/tests/admin-shell.test.tsx`

两页都按「可受控」的写法改：外面传了值就听外面的（外框在 Task 8 把地址里的筛选传进来），不传就自己记状态 —— 所以 `tests/admin.test.tsx` 里不带参数的 `<JobsTab />`、`<UsageTab />` 行为不变。

- [ ] **Step 1: 写失败的测试：在 `frontend/tests/admin-shell.test.tsx` 追加第 4、5 组用例**

在 `frontend/tests/admin-shell.test.tsx` 里找到下面这段（这段在文件里只出现一次）：

```tsx
// ===== 追加点：后面的任务把新用例插在这一行上面 =====
```

整段替换为：

```tsx
// 4. 任务页：筛选（全部 / 运行中 / 失败）；可由外面控制，也可自己记
{
  const { JobsTab } = await import('../src/components/admin/JobsTab')
  await remount(<JobsTab />)
  must(container.querySelector('.adm__pagehead h2')?.textContent === '任务', '任务页标题行')
  must(!!byId('jobs-running') && !!byId('jobs-failed') && button('全部').getAttribute('aria-pressed') === 'true', '默认两张表都在')
  await click(button('失败'))
  must(!byId('jobs-running') && !!byId('jobs-failed') && !text().includes('1:15'), '自己记筛选：只看失败')
  await click(button('运行中'))
  must(!!byId('jobs-running') && !byId('jobs-failed') && text().includes('1:15'), '自己记筛选：只看运行中')
  // 受控：state 由外面给，点筛选只回调，不自己变
  const asked: (string | null)[] = []
  await remount(<JobsTab state="failed" onState={(s) => { asked.push(s) }} />)
  must(!byId('jobs-running') && !!byId('jobs-failed') && button('失败').getAttribute('aria-pressed') === 'true', '受控：state=failed 只显示失败')
  await click(button('运行中'))
  await click(button('全部'))
  must(asked.join() === 'running,' && asked[1] === null, `受控：点筛选回调 running 与 null，实为 ${JSON.stringify(asked)}`)
  must(!byId('jobs-running'), '受控：外面不改 state，显示不变')
  await remount(<JobsTab state={null} onState={() => {}} />)
  must(!!byId('jobs-running') && !!byId('jobs-failed'), '受控：state=null 是全部')
  console.log('4. 任务页筛选 ✓')
}

// 5. 用量页：分组与天数可由外面控制
{
  const { UsageTab } = await import('../src/components/admin/UsageTab')
  const asked: string[] = []
  calls.length = 0
  await remount(<UsageTab group="model" days={7} onQuery={(group, days) => { asked.push(`${group}/${days}`) }} />)
  must(container.querySelector('.adm__pagehead h2')?.textContent === '用量与花费', '用量页标题行')
  must(calls.includes('GET /admin/usage?group=model&days=7') && !calls.includes('GET /admin/usage?group=user&days=30'),
       `受控：按传入的分组与天数请求，实为 ${calls}`)
  must(button('按模型').getAttribute('aria-pressed') === 'true' && button('7 天').getAttribute('aria-pressed') === 'true', '受控：选中项跟着传入值')
  await click(button('按天'))
  await click(button('90 天'))
  must(asked.join() === 'day/7,model/90', `受控：改分组、改天数各回调一次，实为 ${asked}`)
  must(button('按模型').getAttribute('aria-pressed') === 'true', '受控：外面不改就不变')
  console.log('5. 用量页受控的分组与天数 ✓')
}

// ===== 追加点：后面的任务把新用例插在这一行上面 =====
```

- [ ] **Step 2: 跑测试，确认失败**

Run（在仓库根目录）：

```bash
cd frontend && npx vite build --ssr tests/admin-shell.test.tsx --outDir .ssrout --logLevel error && node .ssrout/admin-shell.test.js
```

Expected: FAIL —— 打印到 `3. …✓` 之后报 `✗ 任务页标题行`。

- [ ] **Step 3: 中文文案：任务筛选**

在 `frontend/src/i18n/zh.ts` 里找到下面这段（这段在文件里只出现一次）：

```ts
      running: '运行中', failed: '近 7 天失败', refresh: '刷新',
```

整段替换为：

```ts
      running: '运行中', failed: '近 7 天失败', refresh: '刷新',
      filter: { label: '按状态筛选', all: '全部', running: '运行中', failed: '失败' },
```

- [ ] **Step 4: 英文文案**

在 `frontend/src/i18n/en.ts` 里找到下面这段（这段在文件里只出现一次）：

```ts
      running: 'Running', failed: 'Failed in the last 7 days', refresh: 'Refresh',
```

整段替换为：

```ts
      running: 'Running', failed: 'Failed in the last 7 days', refresh: 'Refresh',
      filter: { label: 'Filter by status', all: 'All', running: 'Running', failed: 'Failed' },
```

- [ ] **Step 5: 任务页：把 `frontend/src/components/admin/JobsTab.tsx` 整份替换**

把 `frontend/src/components/admin/JobsTab.tsx` 的内容全部换成下面这份（整份文件）：

```tsx
import { useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/i18n/core'
import { errValue, failHead, formatMsg, itemError } from '@/i18n/serverMsg'
import type { MsgLike } from '@/i18n/serverMsg'
import { adminJobDebug, adminJobs } from '../../api'
import type { JobState } from '../../paths'
import { int, when } from './format'
import { Empty, ErrorBar, Segmented, TableSkeleton } from './LoadState'
import { PageHead, RefreshButton } from './PageHead'
import { useLoad } from './useLoad'

const clock = (s: number | null) =>
  (s == null ? '—' : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`)

type DebugState = Record<string, { lines?: string[]; err?: MsgLike }>
type Filter = JobState | 'all'

/** 任务：运行中（内存任务表）与近 7 天失败（磁盘上的版本）。
 *  state / onState 由外框从地址传入（?state=running|failed，null 为全部）；不传时筛选是组件内状态。 */
export function JobsTab({ state, onState }: { state?: JobState | null; onState?: (s: JobState | null) => void } = {}) {
  const { t, locale } = useI18n()
  const { data, error, reload } = useLoad(adminJobs, [])
  const [own, setOwn] = useState<JobState | null>(null)
  const filter: Filter = (state !== undefined ? state : own) ?? 'all'
  const setFilter = (f: Filter) => {
    const next = f === 'all' ? null : f
    if (onState) onState(next)
    else setOwn(next)
  }
  /** 点开的调试日志：按任务 id 存结果或错误（错误存原始值，切语言跟着变） */
  const [debug, setDebug] = useState<DebugState>({})
  const toggleDebug = async (id: string, userId: string) => {
    if (debug[id]) { setDebug(({ [id]: _, ...rest }) => rest); return }
    try {
      const r = await adminJobDebug(id, userId)
      setDebug((d) => ({ ...d, [id]: { lines: r.lines } }))
    } catch (e) {
      setDebug((d) => ({ ...d, [id]: { err: errValue(e) } }))
    }
  }
  const debugBtn = (j: { id: string; user_id: string }) => (
    <Button size="sm" variant="outline" onClick={() => void toggleDebug(j.id, j.user_id)}>{t('admin.jobs.debug')}</Button>
  )
  const debugBody = (id: string) => {
    const d = debug[id]
    if (!d) return null
    return d.lines
      ? <pre>{d.lines.length ? d.lines.join('\n') : t('admin.jobs.debugEmpty')}</pre>
      : <pre>{formatMsg(d.err, locale)}</pre>
  }
  const head = (
    <PageHead title={t('admin.nav.pages.jobs')}>
      <Segmented label={t('admin.jobs.filter.label')} value={filter} onChange={setFilter}
                 items={[['all', t('admin.jobs.filter.all')], ['running', t('admin.jobs.filter.running')],
                         ['failed', t('admin.jobs.filter.failed')]]} />
      <RefreshButton label={t('admin.jobs.refresh')} onClick={reload} />
    </PageHead>
  )
  if (error) return <section className="adm__sec">{head}<ErrorBar error={error} onRetry={reload} /></section>
  if (!data) return <section className="adm__sec">{head}<TableSkeleton /></section>
  const rc = (k: string) => t(`admin.jobs.runningCols.${k}` as 'admin.jobs.runningCols.user')
  const fc = (k: string) => t(`admin.jobs.failedCols.${k}` as 'admin.jobs.failedCols.user')
  return (
    <section className="adm__sec">
      {head}
      {filter !== 'failed' && (
        <>
          <h3 className="text-base font-semibold">{t('admin.jobs.running')}</h3>
          {data.running.length === 0 ? (
            <Empty title={t('admin.jobs.noRunning')} />
          ) : (
            <table className="adm__table" data-testid="jobs-running">
              <thead>
                <tr>
                  <th>{rc('user')}</th><th>{rc('novelChapter')}</th><th>{rc('status')}</th>
                  <th>{rc('start')}</th><th className="is-num">{rc('elapsed')}</th><th className="is-num">{rc('chars')}</th><th />
                </tr>
              </thead>
              <tbody>
                {data.running.map((j) => (
                  <tr key={j.id}>
                    <td>{j.username ?? '—'}</td><td>{j.work_title ?? '—'} / {j.chapter ?? '—'}</td>
                    <td><Badge variant="secondary">{j.status}</Badge></td>
                    <td>{when(j.created_at)}</td><td className="is-num">{clock(j.elapsed_sec)}</td>
                    <td className="is-num">{int(j.chars)}</td>
                    <td>{debugBtn(j)}{debugBody(j.id)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
      {filter !== 'running' && (
        <>
          <h3 className="text-base font-semibold">{t('admin.jobs.failed')}</h3>
          {data.failed.length === 0 ? (
            <Empty title={t('admin.jobs.noFailed')} />
          ) : (
            <table className="adm__table" data-testid="jobs-failed">
              <thead>
                <tr>
                  <th>{fc('user')}</th><th>{fc('novelChapter')}</th><th>{fc('start')}</th>
                  <th className="is-num">{fc('chars')}</th><th className="is-num">{fc('attempts')}</th><th>{fc('error')}</th>
                </tr>
              </thead>
              <tbody>
                {data.failed.map((j) => {
                  const reason = formatMsg(failHead(j.error_msg ?? j.error), locale)
                  const text = itemError(j, locale)
                  return (
                    <tr key={j.id}>
                      <td>{j.username ?? '—'}</td>
                      <td>{j.novel_title ?? t('admin.deleted')} / {j.chapter_title ?? '—'}</td>
                      <td>{when(j.created_at)}</td><td className="is-num">{int(j.chars)}</td>
                      <td className="is-num">{j.attempts}</td>
                      <td>
                        <details className="adm__err-detail">
                          <summary>{reason.slice(0, 40)}{reason.length > 40 ? '…' : ''}</summary>
                          <pre>{text}</pre>
                        </details>
                        {debugBtn(j)}{debugBody(j.id)}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </>
      )}
    </section>
  )
}
```

说明：和原文件相比只有四处不同 —— 多了 `state` / `onState` 两个可选属性与筛选状态；最上面换成标题行（页名 + 筛选分段控件 + 刷新）；两张表各自包在 `filter !== ...` 的条件里并带 `data-testid`；空状态改用 `Empty`。失败行里原来叫 `head` 的局部变量改名 `reason`（避免和标题行的 `head` 重名）。调试日志、失败原因的渲染原样保留。

- [ ] **Step 6: 用量页（一）：引入**

在 `frontend/src/components/admin/UsageTab.tsx` 里找到下面这段（这段在文件里只出现一次）：

```tsx
import { Download, Inbox, RefreshCw } from 'lucide-react'
import { EmptyState } from '@/components/common/EmptyState'
```

整段替换为：

```tsx
import { Download } from 'lucide-react'
```

- [ ] **Step 7: 用量页（二）：分组与天数的取值改用 `paths.ts` 里的那一份**

在 `frontend/src/components/admin/UsageTab.tsx` 里找到下面这段（这段在文件里只出现一次）：

```tsx
import type { UsageGroupRow } from '../../types'
import { errText, int, usd, usd4 } from './format'
import { ErrorBar, Segmented, TableSkeleton } from './LoadState'
import { useLoad } from './useLoad'

type Group = 'user' | 'day' | 'model'
const GROUPS: Group[] = ['user', 'day', 'model']
const RANGES = [7, 30, 90]
```

整段替换为：

```tsx
import { USAGE_DAYS, USAGE_GROUPS } from '../../paths'
import type { UsageDays, UsageGroup } from '../../paths'
import type { UsageGroupRow } from '../../types'
import { errText, int, usd, usd4 } from './format'
import { Empty, ErrorBar, Segmented, TableSkeleton } from './LoadState'
import { PageHead, RefreshButton } from './PageHead'
import { useLoad } from './useLoad'
```

- [ ] **Step 8: 用量页（三）：可受控的分组与天数**

在 `frontend/src/components/admin/UsageTab.tsx` 里找到下面这段（这段在文件里只出现一次）：

```tsx
/** 用量：分组汇总、每千字成本、导出 CSV；下面是价格表。 */
export function UsageTab() {
  const { t } = useI18n()
  const [group, setGroup] = useState<Group>('user')
  const [days, setDays] = useState(30)
  const { data, error, reload } = useLoad(() => adminUsage(group, days), [group, days])
```

整段替换为：

```tsx
/** 用量与花费：分组汇总、每千字成本、导出 CSV；下面是价格表。
 *  group / days / onQuery 由外框从地址传入（?group=、?days=）；不传时是组件内状态。 */
export function UsageTab(p: {
  group?: UsageGroup; days?: UsageDays; onQuery?: (group: UsageGroup, days: UsageDays) => void
} = {}) {
  const { t } = useI18n()
  const [own, setOwn] = useState<{ group: UsageGroup; days: UsageDays }>({ group: 'user', days: 30 })
  const group = p.group ?? own.group
  const days = p.days ?? own.days
  const query = (g: UsageGroup, d: UsageDays) => {
    if (p.onQuery) p.onQuery(g, d)
    else setOwn({ group: g, days: d })
  }
  const { data, error, reload } = useLoad(() => adminUsage(group, days), [group, days])
```

- [ ] **Step 9: 用量页（四）：标题行放页名、导出、刷新；分组与天数留在下面一行**

在 `frontend/src/components/admin/UsageTab.tsx` 里找到下面这段（这段在文件里只出现一次）：

```tsx
    <section className="adm__sec">
      <div className="adm__bar">
        <Segmented items={GROUPS.map((g) => [g, t(`admin.usage.groups.${g}`)] as [Group, string])}
                   value={group} onChange={setGroup} />
        <Segmented items={RANGES.map((d) => [d, t('admin.usage.days', { n: d })] as [number, string])}
                   value={days} onChange={setDays} />
        <Button size="sm" variant="outline" onClick={() => void exportCsv()}>
          <Download aria-hidden />{t('admin.usage.exportCsv')}
        </Button>
        <Button size="sm" variant="outline" onClick={reload}>
          <RefreshCw aria-hidden />{t('admin.usage.refresh')}
        </Button>
      </div>
```

整段替换为：

```tsx
    <section className="adm__sec">
      <PageHead title={t('admin.nav.pages.usage')}>
        <Button size="sm" variant="outline" onClick={() => void exportCsv()}>
          <Download aria-hidden />{t('admin.usage.exportCsv')}
        </Button>
        <RefreshButton label={t('admin.usage.refresh')} onClick={reload} />
      </PageHead>
      <div className="adm__bar">
        <Segmented items={USAGE_GROUPS.map((g) => [g, t(`admin.usage.groups.${g}`)] as [UsageGroup, string])}
                   value={group} onChange={(g) => query(g, days)} />
        <Segmented items={USAGE_DAYS.map((d) => [d, t('admin.usage.days', { n: d })] as [UsageDays, string])}
                   value={days} onChange={(d) => query(group, d)} />
      </div>
```

- [ ] **Step 10: 用量页（五）：统一的空状态**

在 `frontend/src/components/admin/UsageTab.tsx` 里找到下面这段（这段在文件里只出现一次）：

```tsx
            <EmptyState icon={<Inbox aria-hidden />} title={t('admin.usage.empty')} />
```

整段替换为：

```tsx
            <Empty title={t('admin.usage.empty')} />
```

- [ ] **Step 11: 跑类型检查与测试，确认通过**

Run（在仓库根目录）：

```bash
cd frontend && npm run typecheck && npx vite build --ssr tests/admin-shell.test.tsx --outDir .ssrout --logLevel error && node .ssrout/admin-shell.test.js
```

Expected: 类型检查无错误；打印 `4. 任务页筛选 ✓`、`5. 用量页受控的分组与天数 ✓`，最后一行 `ALL PASS`。

- [ ] **Step 12: 跑后台原有测试**

Run（在仓库根目录）：

```bash
cd frontend && npx vite build --ssr tests/admin.test.tsx --outDir .ssrout --logLevel error && node .ssrout/admin.test.js
```

Expected: 最后一行 `ALL PASS`（不带参数的任务页、用量页行为不变）。

- [ ] **Step 13: 提交**

```bash
git add frontend/src/components/admin/JobsTab.tsx frontend/src/components/admin/UsageTab.tsx frontend/src/i18n/zh.ts frontend/src/i18n/en.ts frontend/tests/admin-shell.test.tsx
git commit -m "任务页加按状态筛选（全部 / 运行中 / 失败），用量页的分组与天数可由外面控制：外面传值就听外面的并回调，不传就自己记；两页换成统一的标题行与空状态；分组与天数的取值改用 paths.ts 的那一份；补界面测试"
```

---

### Task 7: 导航组件（左侧分组导航与窄屏下拉）

**Files:**
- 新建：`frontend/src/components/admin/AdminNav.tsx`
- 测试：`frontend/tests/admin-shell.test.tsx`

这一步只做导航组件本身，还不接进外框（Task 8 接）。左上角标题与「返回产品」的文字到 Task 8 才改，所以这里的测试从语言包取这两段文字，不写死。

- [ ] **Step 1: 写失败的测试：在 `frontend/tests/admin-shell.test.tsx` 追加第 6 组用例**

在 `frontend/tests/admin-shell.test.tsx` 里找到下面这段（这段在文件里只出现一次）：

```tsx
// ===== 追加点：后面的任务把新用例插在这一行上面 =====
```

整段替换为：

```tsx
// 6. 导航组件：分组、当前页、计数徽标、收起形态、窄屏下拉
{
  const { AdminNavContext } = await import('../src/components/admin/navContext')
  const { AdminSidebar, AdminTopNav } = await import('../src/components/admin/AdminNav')
  const { zh } = await import('../src/i18n/zh')
  const { en } = await import('../src/i18n/en')
  const log: string[] = []
  const nav = (to: string) => { log.push(to) }
  const counts = { jobs: 3, errors: 120, usage: 1 }
  const side = (collapsed: boolean) => (
    <AdminNavContext.Provider value={nav}>
      <AdminSidebar page="jobs" counts={counts} onBack={() => { log.push('back') }} tools={<i>工具</i>}
                    collapsed={collapsed} onToggle={() => { log.push('toggle') }} />
    </AdminNavContext.Provider>)
  await remount(side(false))
  must(container.querySelector('h1')!.textContent === zh.admin.title, '左上角标题')
  must([...container.querySelectorAll('.adm-nav__title')].map((e) => e.textContent).join() === '总览,用户与用量,运行', '三个分组')
  const links = () => [...container.querySelectorAll('.adm-nav__item')]
  must(links().map((a) => a.getAttribute('href')).join() === '/admin,/admin/users,/admin/usage,/admin/jobs,/admin/errors,/admin/audit',
       `六个导航项的地址，实为 ${links().map((a) => a.getAttribute('href'))}`)
  must(links().map((a) => a.querySelector('span')!.textContent).join() === '运营概览,用户,用量与花费,任务,错误,审计', '导航项名字')
  must(links().filter((a) => a.getAttribute('aria-current') === 'page').length === 1
       && byId('admin-nav-jobs')!.getAttribute('aria-current') === 'page' && byId('admin-nav-jobs')!.className.includes('is-on'), '当前页高亮')
  must(textOf('admin-count-jobs') === '3' && textOf('admin-count-errors') === '99+' && textOf('admin-count-usage') === '1'
       && !byId('admin-count-users') && !byId('admin-count-overview') && !byId('admin-count-audit'), '计数徽标：有数才显示，超过 99 写 99+')
  must(byId('admin-count-jobs')!.getAttribute('title') === '近 7 天失败 3 个'
       && byId('admin-count-usage')!.className.includes('is-warn'), '计数的说明与提醒色')
  await click(byId('admin-nav-users')!)
  await click(byId('admin-back')!)
  await click(byId('admin-nav-toggle')!)
  must(log.join() === '/admin/users,back,toggle', `点导航项、返回产品、收起，实为 ${log}`)
  must(byId('admin-back')!.textContent === zh.admin.back && text().includes('工具'), '返回产品链接与工具区')
  await remount(side(true))
  must(!container.querySelector('h1') && container.querySelectorAll('.adm-nav__title').length === 0, '收起：不显示标题与分组名')
  must(links().length === 6 && links().every((a) => !a.querySelector('span:not(.adm-nav__badge)')), '收起：导航项只剩图标')
  must(byId('admin-nav-errors')!.getAttribute('aria-label') === '错误' && byId('admin-back')!.getAttribute('aria-label') === zh.admin.back
       && byId('admin-nav-toggle')!.getAttribute('aria-label') === '展开导航', '收起：图标带名字')
  must(textOf('admin-count-jobs') === '3', '收起：计数还在')
  // 窄屏：顶部一条 + 下拉
  log.length = 0
  await remount(
    <AdminTopNav page="jobs" counts={counts} onBack={() => { log.push('back') }} tools={<i>工具</i>}
                 onPage={(id) => { log.push(`page ${id}`) }} />)
  const select = byId('admin-nav-select') as unknown as HTMLSelectElement
  must(select.value === 'jobs', '下拉选中当前页')
  must([...select.querySelectorAll('optgroup')].map((o) => o.getAttribute('label')).join() === '总览,用户与用量,运行', '下拉按分组')
  must([...select.querySelectorAll('option')].map((o) => o.textContent).join() === '运营概览,用户,用量与花费（1）,任务（3）,错误（99+）,审计',
       `下拉选项带计数，实为 ${[...select.querySelectorAll('option')].map((o) => o.textContent)}`)
  await act(async () => {
    select.value = 'audit'
    select.dispatchEvent(new win.Event('change', { bubbles: true }) as unknown as Event)
  })
  await click(byId('admin-back')!)
  must(log.join() === 'page audit,back', `下拉换页与返回，实为 ${log}`)
  await remount(<I18nProvider initial="en">{side(false)}</I18nProvider>)
  must(links().map((a) => a.querySelector('span')!.textContent).join() === 'Dashboard,Users,Usage & cost,Jobs,Errors,Audit'
       && byId('admin-back')!.textContent === en.admin.back, '英文导航')
  await act(async () => { root.unmount() })
  root = createRoot(container as unknown as HTMLElement)
  setCurrentLocale('zh')
  console.log('6. 导航组件：分组 / 当前页 / 计数 / 收起 / 窄屏下拉 / 英文 ✓')
}

// ===== 追加点：后面的任务把新用例插在这一行上面 =====
```

- [ ] **Step 2: 跑测试，确认失败**

Run（在仓库根目录）：

```bash
cd frontend && npx vite build --ssr tests/admin-shell.test.tsx --outDir .ssrout --logLevel error && node .ssrout/admin-shell.test.js
```

Expected: FAIL —— 构建报找不到 `../src/components/admin/AdminNav`（`Could not resolve`）。

- [ ] **Step 3: 实现**

新建 `frontend/src/components/admin/AdminNav.tsx`，内容如下（整份文件）：

```tsx
import type { ReactNode } from 'react'
import {
  ArrowLeft, ChartColumn, LayoutDashboard, ListChecks, PanelLeftClose, PanelLeftOpen, ScrollText, TriangleAlert, Users,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/i18n/core'
import { cn } from '@/lib/utils'
import { adminPath } from '../../paths'
import type { AdminPage } from '../../paths'
import { AdminLink } from './AdminLink'
import { badgeText, NAV_GROUPS } from './derive'

const ICONS: Record<AdminPage, LucideIcon> = {
  overview: LayoutDashboard, users: Users, usage: ChartColumn, jobs: ListChecks, errors: TriangleAlert, audit: ScrollText,
}

export interface AdminNavProps {
  page: AdminPage
  /** 导航项旁的计数；没有这一项就不显示 */
  counts: Partial<Record<AdminPage, number>>
  onBack: () => void
  /** 语言、主题切换与当前账号 */
  tools: ReactNode
}

/** 计数的说明文字（徽标的 title，也给读屏用） */
function useCountLabel() {
  const { t } = useI18n()
  return (page: AdminPage, n: number) =>
    (page === 'jobs' || page === 'errors' || page === 'usage' ? t(`admin.nav.counts.${page}`, { n }) : String(n))
}

/** 宽屏：左侧分组导航，可收起成只有图标的窄条。 */
export function AdminSidebar({ page, counts, onBack, tools, collapsed, onToggle }: AdminNavProps & {
  collapsed: boolean; onToggle: () => void
}) {
  const { t } = useI18n()
  const countLabel = useCountLabel()
  const toggleLabel = collapsed ? t('admin.nav.expand') : t('admin.nav.collapse')
  return (
    <aside className="adm-side" data-testid="admin-sidebar">
      <div className="adm-side__head">
        {!collapsed && <h1 className="truncate text-sm font-semibold">{t('admin.title')}</h1>}
        <Button variant="ghost" size="icon" aria-label={toggleLabel} title={toggleLabel} aria-expanded={!collapsed}
                data-testid="admin-nav-toggle" onClick={onToggle}>
          {collapsed ? <PanelLeftOpen className="size-4" /> : <PanelLeftClose className="size-4" />}
        </Button>
      </div>
      <Button variant="ghost" size={collapsed ? 'icon' : 'sm'} className={collapsed ? '' : 'justify-start gap-2'}
              aria-label={collapsed ? t('admin.back') : undefined} title={collapsed ? t('admin.back') : undefined}
              data-testid="admin-back" onClick={onBack}>
        <ArrowLeft aria-hidden className="size-4" />{!collapsed && t('admin.back')}
      </Button>
      <nav className="adm-nav" aria-label={t('admin.nav.label')}>
        {NAV_GROUPS.map((g) => (
          <div key={g.id} className="adm-nav__group">
            {!collapsed && <p className="adm-nav__title">{t(`admin.nav.groups.${g.id}`)}</p>}
            {g.pages.map((id) => {
              const Icon = ICONS[id]
              const name = t(`admin.nav.pages.${id}`)
              const n = counts[id]
              return (
                <AdminLink key={id} to={adminPath(id)} data-testid={`admin-nav-${id}`}
                           className={cn('adm-nav__item', page === id && 'is-on')}
                           aria-current={page === id ? 'page' : undefined}
                           aria-label={collapsed ? name : undefined} title={collapsed ? name : undefined}>
                  <Icon aria-hidden className="size-4 shrink-0" />
                  {!collapsed && <span className="min-w-0 flex-1 truncate">{name}</span>}
                  {n !== undefined && (
                    <span className={cn('adm-nav__badge', id === 'usage' && 'is-warn')} data-testid={`admin-count-${id}`}
                          title={countLabel(id, n)} aria-label={countLabel(id, n)}>
                      {badgeText(n)}
                    </span>
                  )}
                </AdminLink>
              )
            })}
          </div>
        ))}
      </nav>
      <div className="adm-side__foot">{tools}</div>
    </aside>
  )
}

/** 窄屏：顶部一条，导航变成下拉框（计数写在选项文字里）。 */
export function AdminTopNav({ page, counts, onBack, tools, onPage }: AdminNavProps & { onPage: (page: AdminPage) => void }) {
  const { t } = useI18n()
  return (
    <header className="adm-top" data-testid="admin-topnav">
      <Button variant="ghost" size="icon" aria-label={t('admin.back')} title={t('admin.back')}
              data-testid="admin-back" onClick={onBack}>
        <ArrowLeft aria-hidden className="size-4" />
      </Button>
      <h1 className="shrink-0 text-sm font-semibold">{t('admin.title')}</h1>
      <select className="adm-top__select" aria-label={t('admin.nav.label')} data-testid="admin-nav-select"
              value={page} onChange={(e) => onPage(e.target.value as AdminPage)}>
        {NAV_GROUPS.map((g) => (
          <optgroup key={g.id} label={t(`admin.nav.groups.${g.id}`)}>
            {g.pages.map((id) => (
              <option key={id} value={id}>
                {t(`admin.nav.pages.${id}`)}
                {counts[id] !== undefined ? t('common.paren', { text: badgeText(counts[id]) }) : ''}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
      <div className="flex shrink-0 items-center">{tools}</div>
    </header>
  )
}
```

- [ ] **Step 4: 跑类型检查与测试，确认通过**

Run（在仓库根目录）：

```bash
cd frontend && npm run typecheck && npx vite build --ssr tests/admin-shell.test.tsx --outDir .ssrout --logLevel error && node .ssrout/admin-shell.test.js
```

Expected: 类型检查无错误；打印 `6. 导航组件：分组 / 当前页 / 计数 / 收起 / 窄屏下拉 / 英文 ✓`，最后一行 `ALL PASS`。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/components/admin/AdminNav.tsx frontend/tests/admin-shell.test.tsx
git commit -m "后台导航组件 AdminNav：宽屏是左侧分组导航（总览 / 用户与用量 / 运行），每项是真链接，当前页高亮，旁边显示计数徽标（超过 99 写 99+，未定价用提醒色），可收起成只有图标的窄条；窄屏是顶部一条加下拉框，计数写在选项文字里；左上角标题与返回产品按钮；补界面测试，暂未接进外框"
```

---

### Task 8: 外框接进应用：后台独立成一屏，每页有自己的地址

**Files:**
- 修改（整份替换）：`frontend/src/components/admin/AdminView.tsx`
- 修改：`frontend/src/App.tsx`、`frontend/src/i18n/zh.ts`、`frontend/src/i18n/en.ts`、`frontend/src/styles/admin.css`
- 测试：`frontend/tests/admin-shell.test.tsx`、`frontend/tests/admin.test.tsx`、`frontend/tests/routing.test.tsx`、`frontend/tests/flow.test.tsx`

`AdminView` 的属性变了（页与筛选从地址来），`App.tsx` 必须同一步改，否则类型检查过不了，所以这一任务比较大，按顺序做完再跑测试。改完后后台不再套在产品外壳（`AppShell`）里，而是自己占满一屏。

- [ ] **Step 1: 写失败的测试（一）：在 `frontend/tests/admin-shell.test.tsx` 追加第 7 组用例**

在 `frontend/tests/admin-shell.test.tsx` 里找到下面这段（这段在文件里只出现一次）：

```tsx
// ===== 追加点：后面的任务把新用例插在这一行上面 =====
```

整段替换为：

```tsx
// 7. 外框：每个地址打开对应的页；导航与卡片链接改地址；筛选写进地址；计数、收起、窄屏
{
  const { useState } = await import('react')
  const { AdminView } = await import('../src/components/admin/AdminView')
  const { parseLocation } = await import('../src/paths')
  const me = { id: 'u-root', username: 'root', created_at: '', role: 'admin' as const }
  const log: string[] = []
  let here = ''
  let back = 0
  /** 代替 App：地址放在状态里，用 parseLocation 解析后交给外框 */
  function Host({ start }: { start: string }) {
    const [url, setUrl] = useState(start)
    here = url
    const [pathname, query] = url.split('?')
    const { loc } = parseLocation(pathname, query ? `?${query}` : '')
    if (loc.kind !== 'admin') return <p>不是后台地址</p>
    return (
      <AdminView me={me} page={loc.page} jobState={loc.state} usageGroup={loc.group} usageDays={loc.days}
                 onNav={(to, replace) => { log.push(`${replace ? 'replace' : 'push'} ${to}`); setUrl(to) }}
                 onBack={() => { back++ }} />
    )
  }
  const open = async (url: string) => { log.length = 0; await remount(<Host start={url} />) }
  const h2 = () => container.querySelector('.adm__pagehead h2')?.textContent
  const current = () => container.querySelector('.adm-nav__item[aria-current="page"]')?.getAttribute('data-testid')

  for (const [url, name, id] of [['/admin', '运营概览', 'overview'], ['/admin/users', '用户', 'users'],
    ['/admin/usage', '用量与花费', 'usage'], ['/admin/jobs', '任务', 'jobs'], ['/admin/errors', '错误', 'errors'],
    ['/admin/audit', '审计', 'audit']]) {
    await open(url)
    must(h2() === name && current() === `admin-nav-${id}`, `${url} 应打开「${name}」，实为 ${h2()} / ${current()}`)
    must(container.querySelectorAll('.adm__pagehead').length === 1 && !!byId('admin-sidebar'), `${url}：一个标题行、左侧导航`)
  }
  console.log('7a. 六个地址各自打开对应的页 ✓')

  await open('/admin')
  must(textOf('admin-count-jobs') === '3' && textOf('admin-count-errors') === '2' && textOf('admin-count-usage') === '1'
       && !byId('admin-count-users'), `导航计数：失败 3、近 7 天错误 2、未定价 1，实为 ${textOf('admin-count-jobs')}/${textOf('admin-count-errors')}/${textOf('admin-count-usage')}`)
  must(calls.filter((c) => c === 'GET /admin/overview').length >= 1 && text().includes('30 天金额'), '概览页用外框那份概览数据')
  await click(byId('stat-failed')!.querySelector('a')!)
  must(here === '/admin/jobs?state=failed' && log.join() === 'push /admin/jobs?state=failed', `「去处理」跳到失败任务，实为 ${here}`)
  must(h2() === '任务' && !byId('jobs-running') && !!byId('jobs-failed') && button('失败').getAttribute('aria-pressed') === 'true',
       '带筛选打开任务页：只显示失败')
  await click(button('全部'))
  must(here === '/admin/jobs' && log[log.length - 1] === 'replace /admin/jobs' && !!byId('jobs-running'), `改筛选是 replace，实为 ${log}`)
  await click(button('运行中'))
  must(here === '/admin/jobs?state=running' && !byId('jobs-failed'), '筛选写进地址')
  await click(byId('admin-nav-usage')!)
  must(here === '/admin/usage' && log[log.length - 1] === 'push /admin/usage' && h2() === '用量与花费', '点导航项是 push')
  await click(button('按模型'))
  await click(button('7 天'))
  must(here === '/admin/usage?group=model&days=7' && log[log.length - 1] === 'replace /admin/usage?group=model&days=7'
       && calls.includes('GET /admin/usage?group=model&days=7'), `用量的分组与天数写进地址，实为 ${here}`)
  await click(byId('admin-nav-overview')!)
  await click(byId('unpriced-alert')!)
  must(here === '/admin/usage?group=model' && button('按模型').getAttribute('aria-pressed') === 'true', `未定价提醒跳到按模型的用量页，实为 ${here}`)
  await click(byId('admin-nav-overview')!)
  await click(byId('stat-running')!.querySelector('a')!)
  must(here === '/admin/jobs?state=running' && !!byId('jobs-running') && !byId('jobs-failed'), '「查看任务」跳到运行中')
  await click(byId('admin-back')!)
  must(back === 1, '返回产品回调')
  console.log('7b. 计数 / 卡片链接带筛选 / 筛选写进地址 / 返回 ✓')

  // 没有待处理的数：不显示徽标
  ov.failed_7d = 0; ov.unpriced_models = []
  await open('/admin/audit')
  must(!byId('admin-count-jobs') && !byId('admin-count-usage') && textOf('admin-count-errors') === '2', '为 0 的计数不显示')
  ov.failed_7d = 3; ov.unpriced_models = ['mystery']
  // 概览接口失败：导航照常，只是没有来自它的计数；概览页显示错误条
  failing.add('/admin/overview')
  await open('/admin')
  must(!byId('admin-count-jobs') && !!byId('admin-nav-jobs') && text().includes('服务器出了点问题'), '概览取不到：没有任务计数，页内是错误条')
  failing.clear()

  // 收起与展开；记在 localStorage
  await open('/admin/users')
  const shell = () => byId('admin-shell')!.className
  must(!shell().includes('is-collapsed') && container.querySelector('h1')?.textContent === '运营后台', '默认展开')
  await click(byId('admin-nav-toggle')!)
  must(shell().includes('is-collapsed') && !container.querySelector('h1') && textOf('admin-count-jobs') === '3'
       && win.localStorage.getItem('inkreel.admin.navCollapsed') === '1', '收起：窄条、计数还在、记住')
  await open('/admin/users')
  must(shell().includes('is-collapsed'), '重新打开仍是收起')
  await click(byId('admin-nav-toggle')!)
  must(!shell().includes('is-collapsed') && win.localStorage.getItem('inkreel.admin.navCollapsed') === '0', '再点展开')

  // 窄屏：顶部下拉
  const wide = win.matchMedia
  ;(win as unknown as { matchMedia: unknown }).matchMedia = () => ({ matches: true, addEventListener() {}, removeEventListener() {} })
  g.matchMedia = win.matchMedia
  await open('/admin/jobs?state=failed')
  must(!byId('admin-sidebar') && !!byId('admin-topnav') && shell().includes('is-narrow') && h2() === '任务', '窄屏：没有侧栏，顶部一条')
  const select = byId('admin-nav-select') as unknown as HTMLSelectElement
  must(select.value === 'jobs', '窄屏下拉选中当前页')
  await act(async () => {
    select.value = 'errors'
    select.dispatchEvent(new win.Event('change', { bubbles: true }) as unknown as Event)
  })
  await settle()
  must(here === '/admin/errors' && h2() === '错误', `窄屏下拉换页，实为 ${here}`)
  ;(win as unknown as { matchMedia: unknown }).matchMedia = wide
  g.matchMedia = wide
  console.log('7c. 计数为 0 不显示 / 收起 / 窄屏下拉 ✓')

  // 英文
  log.length = 0
  await remount(<I18nProvider initial="en"><Host start="/admin/jobs?state=failed" /></I18nProvider>)
  must(container.querySelector('h1')?.textContent === 'Admin console' && h2() === 'Jobs' && byId('admin-back')!.textContent === 'Back to app'
       && button('Failed').getAttribute('aria-pressed') === 'true'
       && byId('admin-count-jobs')!.getAttribute('title') === '3 failed in the last 7 days', '英文外框')
  await act(async () => { root.unmount() })
  root = createRoot(container as unknown as HTMLElement)
  setCurrentLocale('zh')
  console.log('7d. 英文外框 ✓')
}

// ===== 追加点：后面的任务把新用例插在这一行上面 =====
```

- [ ] **Step 2: 写失败的测试（二）：`frontend/tests/routing.test.tsx` 的桩后端补上后台其余接口**

在 `frontend/tests/routing.test.tsx` 里找到下面这段（这段在文件里只出现一次）：

```tsx
  if (path === '/admin/overview' && method === 'GET') {
    return json({ users: 2, active_7d: 1, tokens_30d: 0, cost_30d: 0, running: 0, failed_7d: 0, daily: [], unpriced_models: [] })
  }
```

整段替换为：

```tsx
  if (path === '/admin/overview' && method === 'GET') {
    return json({ users: 2, active_7d: 1, tokens_30d: 0, cost_30d: 0, running: 0, failed_7d: 0, daily: [], unpriced_models: [] })
  }
  if (path === '/admin/users' && method === 'GET') return json({ users: [] })
  if (path === '/admin/jobs' && method === 'GET') return json({ running: [], failed: [] })
  if (path === '/admin/usage' && method === 'GET') {
    return json({ group: 'user', days: 30, rows: [], per_k_chars: { n: 0, mean: null, p90: null }, unpriced_models: [] })
  }
  if (path === '/admin/errors' && method === 'GET') return json({ errors: [] })
  if (path === '/admin/audit' && method === 'GET') return json({ audit: [] })
  if (path === '/admin/pricing' && method === 'GET') return json({ currency: 'USD', updated_at: null, models: {} })
```

- [ ] **Step 3: 写失败的测试（三）：`frontend/tests/routing.test.tsx` 的后台用例（标题文字改为「运营后台」，并新增一组）**

在 `frontend/tests/routing.test.tsx` 里找到下面这段（这段在文件里只出现一次）：

```tsx
  must(a.here() === '/' && !a.has('管理后台'), `普通用户不能停在后台，实际 ${a.here()}`)
  await a.done()
  const b = await boot('/admin', 'root')
  must(b.here() === '/admin' && b.has('管理后台'), '管理员可以直接打开后台')
  await b.done()
}
console.log('6. 非管理员 /admin → 回首页 ✓')
```

整段替换为：

```tsx
  must(a.here() === '/' && !a.has('运营后台'), `普通用户不能停在后台，实际 ${a.here()}`)
  await a.done()
  const b = await boot('/admin', 'root')
  must(b.here() === '/admin' && b.has('运营后台'), '管理员可以直接打开后台')
  await b.done()
}
console.log('6. 非管理员 /admin → 回首页 ✓')

// 后台每页有独立地址：深链接（等于刷新）、导航、后退、筛选、不规范地址、返回产品
{
  const h2 = (x: { q: (sel: string) => HTMLElement | null }) => x.q('.adm__pagehead h2')?.textContent
  const a = await boot('/admin/jobs?state=failed', 'root')
  must(a.here() === '/admin/jobs?state=failed' && h2(a) === '任务', `深链接到带筛选的任务页，实际 ${a.here()} / ${h2(a)}`)
  must(button(a.container, '失败')?.getAttribute('aria-pressed') === 'true', '筛选取自地址')
  must(doc.title === '任务 · 运营后台 — Inkreel', `后台页的标题，实际 ${doc.title}`)
  must(!a.q('[data-testid="app-shell"]') && !!a.q('[data-testid="admin-shell"]'), '后台是独立的一屏，不套产品外壳')
  await click(a.q('[data-testid="admin-nav-users"]')!)
  must(a.here() === '/admin/users' && a.router.state.historyAction === 'PUSH' && h2(a) === '用户', `点导航换页是 push，实际 ${a.here()}`)
  await act(async () => { await a.router.navigate(-1) })
  await settle()
  must(a.here() === '/admin/jobs?state=failed' && h2(a) === '任务', `后退回到上一页并带着筛选，实际 ${a.here()}`)
  await click(button(a.container, '全部')!)
  must(a.here() === '/admin/jobs' && a.router.state.historyAction === 'REPLACE', `改筛选是 replace，实际 ${a.here()}`)
  await a.done()
  const b = await boot('/admin/overview', 'root')
  must(b.here() === '/admin' && h2(b) === '运营概览', `/admin/overview 规范化到 /admin，实际 ${b.here()}`)
  await b.done()
  const c = await boot('/admin/usage?days=7&group=model&x=1', 'root')
  must(c.here() === '/admin/usage?group=model&days=7' && h2(c) === '用量与花费', `乱序与多余参数规范化，实际 ${c.here()}`)
  await c.done()
  const d = await boot('/admin/nope', 'root')
  must(!!d.q('[data-testid="not-found"]'), '后台下面不存在的页是 404')
  await d.done()
  const e = await boot('/admin/users', 'alice')
  must(e.here() === '/' && !e.has('运营后台'), `普通用户打不开后台子页，实际 ${e.here()}`)
  await e.done()
  // 返回产品：回到进后台之前在产品里的那一页（后台里翻过页也一样）
  const f = await boot('/novels/n1/props', 'root')
  await act(async () => { await f.router.navigate('/admin') })
  await settle(150)
  await click(f.q('[data-testid="admin-nav-audit"]')!)
  must(f.here() === '/admin/audit', `先在后台里换一页，实际 ${f.here()}`)
  await click(f.q('[data-testid="admin-back"]')!)
  await settle(150)
  must(f.here() === '/novels/n1/props' && !!f.q('[data-testid="app-shell"]'), `返回产品回到进后台之前的页，实际 ${f.here()}`)
  await f.done()
  const k = await boot('/admin/errors', 'root')
  await click(k.q('[data-testid="admin-back"]')!)
  await settle(150)
  must(k.here() === '/', `直接打开后台时返回产品回首页，实际 ${k.here()}`)
  await k.done()
}
console.log('后台各页独立地址 / 后退 / 筛选 / 规范化 / 返回产品 ✓')
```

- [ ] **Step 4: 写失败的测试（四）：`frontend/tests/routing.test.tsx` 另一处标题文字**

在 `frontend/tests/routing.test.tsx` 里找到下面这段（这段在文件里只出现一次）：

```tsx
  must(a.here() === '/admin' && a.has('管理后台'), 'me() 确认是管理员后留在后台')
```

整段替换为：

```tsx
  must(a.here() === '/admin' && a.has('运营后台'), 'me() 确认是管理员后留在后台')
```

- [ ] **Step 5: 写失败的测试（五）：`frontend/tests/flow.test.tsx` 的管理入口用例跟着新文字**

在 `frontend/tests/flow.test.tsx` 里找到下面这段（这段在文件里只出现一次）：

```tsx
must(has('管理后台') && !!btn('返回书架'), '点「管理」应进入后台')
await click(btn('返回书架')!)
must(!has('管理后台') && !!btn('管理'), '「返回书架」应回到书架')
await click(btn('管理')!)
must(has('管理后台'), '再次进入后台')
await act(async () => { notifyUnauthorized() })     // 后台开着时登录失效
await settle(50)
must(has('login__tab') && !has('管理后台'), '401 后应回到登录页')
must(has('登录已过期'), '401 后登录框应带过期提示')
await loginAs('bob', 'pw654321')
must(has('bob') && !has('管理后台') && !btn('管理') && !btn('返回书架'),
     '401 后换普通用户登录，不能落进后台，也不该有「管理」入口')
```

整段替换为：

```tsx
must(has('运营后台') && !!btn('返回产品'), '点「管理」应进入后台')
await click(btn('返回产品')!)
must(!has('运营后台') && !!btn('管理'), '「返回产品」应回到书架')
await click(btn('管理')!)
must(has('运营后台'), '再次进入后台')
await act(async () => { notifyUnauthorized() })     // 后台开着时登录失效
await settle(50)
must(has('login__tab') && !has('运营后台'), '401 后应回到登录页')
must(has('登录已过期'), '401 后登录框应带过期提示')
await loginAs('bob', 'pw654321')
must(has('bob') && !has('运营后台') && !btn('管理') && !btn('返回产品'),
     '401 后换普通用户登录，不能落进后台，也不该有「管理」入口')
```

- [ ] **Step 6: 原有测试跟着改（一）：`frontend/tests/admin.test.tsx` 第 7 组（页签框架 → 外框）**

在 `frontend/tests/admin.test.tsx` 里找到下面这段（这段在文件里只出现一次）：

```tsx
// 7. 页签框架：五个页签可切换，返回回调
let back = 0
await remount(<AdminView me={me} onBack={() => { back++ }} />)
for (const t of ['概览', '用户', '用量', '任务', '审计', '错误记录']) button(t)
must(text().includes('30 天金额'), '默认在概览')
await click(button('审计'))
must(text().includes('管理员') && text().includes('之前') && text().includes('之后'), '切到审计')
await click(button('返回'))
must(back === 1, '返回回调')
console.log('7. 页签框架 / 返回 ✓')
```

整段替换为：

```tsx
// 7. 外框：左侧导航六项，按传入的页显示内容，返回回调（地址、计数、收起等见 tests/admin-shell.test.tsx）
let back = 0
const frame = (page: 'overview' | 'audit') => (
  <AdminView me={me} page={page} jobState={null} usageGroup="user" usageDays={30}
             onNav={() => {}} onBack={() => { back++ }} />)
const navNames = () => [...container.querySelectorAll('.adm-nav__item')].map((a) => a.querySelector('span')!.textContent)
await remount(frame('overview'))
must(navNames().join() === '运营概览,用户,用量与花费,任务,错误,审计', `导航六项，实为 ${navNames()}`)
must(text().includes('30 天金额'), '概览页')
await remount(frame('audit'))
must(text().includes('管理员') && text().includes('之前') && text().includes('之后'), '审计页')
await click(button('返回产品'))
must(back === 1, '返回回调')
console.log('7. 外框 / 返回 ✓')
```

- [ ] **Step 7: 原有测试跟着改（二）：`frontend/tests/admin.test.tsx` 第 9 组**

在 `frontend/tests/admin.test.tsx` 里找到下面这段（这段在文件里只出现一次）：

```tsx
// 9. 英文：页签文字
await remount(<I18nProvider initial="en"><AdminView me={me} onBack={() => {}} /></I18nProvider>)
const tabNames = [...container.querySelectorAll('.tabs__btn')].map((b) => b.textContent)
must(tabNames.join(' ') === 'Overview Users Usage Jobs Audit Errors', `英文页签，实为 ${tabNames.join(' ')}`)
must(text().includes('Active (7d)'), '英文概览')
```

整段替换为：

```tsx
// 9. 英文：导航文字
await remount(<I18nProvider initial="en">{frame('overview')}</I18nProvider>)
must(navNames().join() === 'Dashboard,Users,Usage & cost,Jobs,Errors,Audit', `英文导航，实为 ${navNames()}`)
must(text().includes('Active (7d)'), '英文概览')
```

- [ ] **Step 8: 原有测试跟着改（三）**

在 `frontend/tests/admin.test.tsx` 里找到下面这段（这段在文件里只出现一次）：

```tsx
console.log('9. 英文页签 ✓')
```

整段替换为：

```tsx
console.log('9. 英文导航 ✓')
```

- [ ] **Step 9: 原有测试跟着改（四）：文件末尾那一次渲染**

在 `frontend/tests/admin.test.tsx` 里找到下面这段（这段在文件里只出现一次）：

```tsx
await remount(<AdminView me={me} onBack={() => {}} />)
```

整段替换为：

```tsx
await remount(frame('overview'))
```

- [ ] **Step 10: 跑测试，确认失败**

Run（在仓库根目录）：

```bash
cd frontend && npx vite build --ssr tests/admin-shell.test.tsx --outDir .ssrout --logLevel error && node .ssrout/admin-shell.test.js
```

Expected: FAIL —— 报 `✗ /admin 应打开「运营概览」，实为 运营概览 / undefined`（旧外框没有新导航）。

- [ ] **Step 11: 中文文案（一）：标题改「运营后台」，返回改「返回产品」，删掉不再用的页签文字**

在 `frontend/src/i18n/zh.ts` 里找到下面这段（这段在文件里只出现一次）：

```ts
    title: '管理后台',
    back: '返回',
    tabsLabel: '后台页签',
    tabs: { overview: '概览', users: '用户', usage: '用量', jobs: '任务', audit: '审计', errors: '错误记录' },
```

整段替换为：

```ts
    title: '运营后台',
    back: '返回产品',
```

- [ ] **Step 12: 中文文案（二）：浏览器标题**

在 `frontend/src/i18n/zh.ts` 里找到下面这段（这段在文件里只出现一次）：

```ts
    title: { admin: '管理后台', canvas: '出片画布', notFound: '页面不存在' },
```

整段替换为：

```ts
    title: { admin: '运营后台', canvas: '出片画布', notFound: '页面不存在' },
```

- [ ] **Step 13: 英文文案**

在 `frontend/src/i18n/en.ts` 里找到下面这段（这段在文件里只出现一次）：

```ts
    title: 'Admin console',
    back: 'Back',
    tabsLabel: 'Admin sections',
    tabs: { overview: 'Overview', users: 'Users', usage: 'Usage', jobs: 'Jobs', audit: 'Audit', errors: 'Errors' },
```

整段替换为：

```ts
    title: 'Admin console',
    back: 'Back to app',
```

- [ ] **Step 14: 外框：把 `frontend/src/components/admin/AdminView.tsx` 整份替换**

把 `frontend/src/components/admin/AdminView.tsx` 的内容全部换成下面这份（整份文件）：

```tsx
import { useEffect, useState } from 'react'
import { LangToggle } from '@/components/common/LangToggle'
import { ThemeToggle } from '@/components/common/ThemeToggle'
import { cn } from '@/lib/utils'
import { adminErrors, adminOverview } from '../../api'
import type { User } from '../../auth'
import { adminPath } from '../../paths'
import type { AdminPage, JobState, UsageDays, UsageGroup } from '../../paths'
import { AdminSidebar, AdminTopNav } from './AdminNav'
import { AuditTab } from './AuditTab'
import { navCounts } from './derive'
import { ErrorsTab } from './ErrorsTab'
import { JobsTab } from './JobsTab'
import { AdminNavContext } from './navContext'
import type { AdminNavFn } from './navContext'
import { Overview } from './Overview'
import { UsageTab } from './UsageTab'
import { useLoad } from './useLoad'
import { Users } from './Users'

export interface AdminViewProps {
  me: User
  /** 当前页与筛选都来自地址（paths.ts 的 parseLocation） */
  page: AdminPage
  jobState: JobState | null
  usageGroup: UsageGroup
  usageDays: UsageDays
  /** 后台内部跳转（上层改地址） */
  onNav: AdminNavFn
  /** 返回产品 */
  onBack: () => void
}

const NARROW = '(max-width: 767px)'
const COLLAPSE_KEY = 'inkreel.admin.navCollapsed'

/** 窄屏（< 768px）：导航改成顶部下拉；跟着窗口宽度变 */
function useNarrow() {
  const [narrow, setNarrow] = useState(() => typeof window !== 'undefined' && !!window.matchMedia?.(NARROW).matches)
  useEffect(() => {
    const mq = window.matchMedia?.(NARROW)
    if (!mq?.addEventListener) return
    const sync = () => setNarrow(mq.matches)
    mq.addEventListener('change', sync)
    return () => mq.removeEventListener('change', sync)
  }, [])
  return narrow
}

const readCollapsed = () => {
  try { return localStorage.getItem(COLLAPSE_KEY) === '1' } catch { return false }
}

/** 运营后台的外框：左侧分组导航（窄屏为顶部下拉）+ 右侧内容。只给管理员看；权限以后端为准。 */
export function AdminView(p: AdminViewProps) {
  // 概览数据放在外框：导航计数与概览页共用一份，每 30 秒刷新
  const overview = useLoad(adminOverview, [], 30000)
  const errors = useLoad(adminErrors, [], 60000)
  const counts = navCounts(overview.data, errors.data, Date.now())
  const narrow = useNarrow()
  const [collapsed, setCollapsed] = useState(readCollapsed)
  const toggle = () => setCollapsed((v) => {
    try { localStorage.setItem(COLLAPSE_KEY, v ? '0' : '1') } catch { /* 存不了就只在本次有效 */ }
    return !v
  })
  const tools = (
    <>
      <LangToggle /><ThemeToggle />
      <span className="adm-side__user min-w-0 truncate text-xs text-muted-foreground">{p.me.username}</span>
    </>
  )
  return (
    <AdminNavContext.Provider value={p.onNav}>
      <div className={cn('adm-shell', narrow && 'is-narrow', !narrow && collapsed && 'is-collapsed')} data-testid="admin-shell">
        {narrow
          ? <AdminTopNav page={p.page} counts={counts} onBack={p.onBack} tools={tools}
                         onPage={(id) => p.onNav(adminPath(id))} />
          : <AdminSidebar page={p.page} counts={counts} onBack={p.onBack} tools={tools}
                          collapsed={collapsed} onToggle={toggle} />}
        <main className="adm">
          {p.page === 'overview' && <Overview shared={overview} />}
          {p.page === 'users' && <Users me={p.me} />}
          {p.page === 'usage' && (
            <UsageTab group={p.usageGroup} days={p.usageDays}
                      onQuery={(group, days) => p.onNav(adminPath('usage', { group, days }), true)} />
          )}
          {p.page === 'jobs' && (
            <JobsTab state={p.jobState} onState={(state) => p.onNav(adminPath('jobs', { state }), true)} />
          )}
          {p.page === 'errors' && <ErrorsTab />}
          {p.page === 'audit' && <AuditTab />}
        </main>
      </div>
    </AdminNavContext.Provider>
  )
}
```

- [ ] **Step 15: 样式：删掉旧页签框架的 `.adm__head`**

在 `frontend/src/styles/admin.css` 里找到下面这段（这段在文件里只出现一次）：

```css
.adm__head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
```

整段删掉。

- [ ] **Step 16: `App.tsx`（一）：后台位置**

在 `frontend/src/App.tsx` 里找到下面这段（这段在文件里只出现一次）：

```tsx
  const adminOpen = loc.kind === 'admin'
```

整段替换为：

```tsx
  /** 当前在后台：页与筛选都在里面；不在后台为 null */
  const adminLoc = loc.kind === 'admin' ? loc : null
```

- [ ] **Step 17: `App.tsx`（二）：浏览器标题带上后台的页名 —— 取出当前页**

在 `frontend/src/App.tsx` 里找到下面这段（这段在文件里只出现一次）：

```tsx
  const canvasKey = loc.kind === 'chapter' && loc.canvas
  useEffect(() => {
```

整段替换为：

```tsx
  const canvasKey = loc.kind === 'chapter' && loc.canvas
  const adminPage = loc.kind === 'admin' ? loc.page : null
  useEffect(() => {
```

- [ ] **Step 18: `App.tsx`（三）：标题文字**

在 `frontend/src/App.tsx` 里找到下面这段（这段在文件里只出现一次）：

```tsx
    if (loc.kind === 'admin') title = `${t('route.title.admin')} — ${brand}`
```

整段替换为：

```tsx
    if (adminPage) title = `${t(`admin.nav.pages.${adminPage}`)} · ${t('route.title.admin')} — ${brand}`
```

- [ ] **Step 19: `App.tsx`（四）：标题这个 effect 的依赖加上 `adminPage`**

在 `frontend/src/App.tsx` 里找到下面这段（这段在文件里只出现一次）：

```tsx
  }, [loc.kind, nid, cid, sectionKey, canvasKey, novel, chapter, t])
```

整段替换为：

```tsx
  }, [loc.kind, nid, cid, sectionKey, canvasKey, adminPage, novel, chapter, t])
```

- [ ] **Step 20: `App.tsx`（五）：「返回产品」回到进后台之前的页**

在 `frontend/src/App.tsx` 里找到下面这段（这段在文件里只出现一次）：

```tsx
  const leaveAdmin = () => {
    if (location.key !== 'default') navigate(-1)
    else navigate('/', { replace: true })
  }
```

整段替换为：

```tsx
  /** 进后台之前在产品里的地址（记下是谁的）：后台内部翻页会留下历史，「返回产品」不能靠后退 */
  const lastProduct = useRef<{ uid: string | null; path: string }>({ uid: null, path: '/' })
  useEffect(() => {
    if (loc.kind !== 'admin') lastProduct.current = { uid: user?.id ?? null, path: location.pathname + location.search }
  }, [loc.kind, location.pathname, location.search, user?.id])
  const leaveAdmin = () => {
    const last = lastProduct.current
    navigate(user && last.uid === user.id ? last.path : '/')
  }
```

- [ ] **Step 21: `App.tsx`（六）：在后台时渲染外框，否则才渲染产品外壳（`<AppShell` 这一大段不用重排缩进）**

在 `frontend/src/App.tsx` 里找到下面这段（这段在文件里只出现一次）：

```tsx
      <AppShell
        username={user.username}
        isAdmin={user.role === 'admin'}
        adminOpen={adminOpen && user.role === 'admin'}
        onToggleAdmin={() => { if (adminOpen) leaveAdmin(); else void enterAdmin() }}
```

整段替换为：

```tsx
      {adminLoc && user.role === 'admin' ? (
        <AdminView me={user} page={adminLoc.page} jobState={adminLoc.state}
                   usageGroup={adminLoc.group} usageDays={adminLoc.days}
                   onNav={(to, replace) => { go(to, { replace }) }} onBack={leaveAdmin} />
      ) : (
      <AppShell
        username={user.username}
        isAdmin={user.role === 'admin'}
        adminOpen={false}
        onToggleAdmin={enterAdmin}
```

- [ ] **Step 22: `App.tsx`（七）：产品外壳里不再需要判断「是否在后台」—— 项目切换器**

在 `frontend/src/App.tsx` 里找到下面这段（这段在文件里只出现一次）：

```tsx
        projectSwitcher={shown && !(adminOpen && user.role === 'admin') ? (
```

整段替换为：

```tsx
        projectSwitcher={shown ? (
```

- [ ] **Step 23: `App.tsx`（八）：章节切换**

在 `frontend/src/App.tsx` 里找到下面这段（这段在文件里只出现一次）：

```tsx
        chapterCrumb={shown && chapter && !(adminOpen && user.role === 'admin') ? (
```

整段替换为：

```tsx
        chapterCrumb={shown && chapter ? (
```

- [ ] **Step 24: `App.tsx`（九）：费用表**

在 `frontend/src/App.tsx` 里找到下面这段（这段在文件里只出现一次）：

```tsx
        costMeter={shown && !(adminOpen && user.role === 'admin')
```

整段替换为：

```tsx
        costMeter={shown
```

- [ ] **Step 25: `App.tsx`（十）：助手入口**

在 `frontend/src/App.tsx` 里找到下面这段（这段在文件里只出现一次）：

```tsx
        onOpenAssistant={shown && !(adminOpen && user.role === 'admin')
```

整段替换为：

```tsx
        onOpenAssistant={shown
```

- [ ] **Step 26: `App.tsx`（十一）：内容区切换键**

在 `frontend/src/App.tsx` 里找到下面这段（这段在文件里只出现一次）：

```tsx
        viewKey={adminOpen ? 'admin' : `${novel?.id ?? ''}/${chapter?.id ?? ''}`}
```

整段替换为：

```tsx
        viewKey={`${novel?.id ?? ''}/${chapter?.id ?? ''}`}
```

- [ ] **Step 27: `App.tsx`（十二）：侧边栏**

在 `frontend/src/App.tsx` 里找到下面这段（这段在文件里只出现一次）：

```tsx
        sidebar={adminOpen && user.role === 'admin' ? null : shown ? (
```

整段替换为：

```tsx
        sidebar={shown ? (
```

- [ ] **Step 28: `App.tsx`（十三）：产品外壳的内容区只剩产品页面**

在 `frontend/src/App.tsx` 里找到下面这段（这段在文件里只出现一次）：

```tsx
        {adminOpen && user.role === 'admin' ? (
          <AdminView me={user} onBack={leaveAdmin} />
        ) : (
          <div className="main">
```

整段替换为：

```tsx
          <div className="main">
```

- [ ] **Step 29: `App.tsx`（十四）：收尾的括号跟着挪到 `</AppShell>` 后面**

在 `frontend/src/App.tsx` 里找到下面这段（这段在文件里只出现一次）：

```tsx
          </div>
        )}
      </AppShell>
```

整段替换为：

```tsx
          </div>
      </AppShell>
      )}
```

- [ ] **Step 30: 跑类型检查，确认通过**

Run（在仓库根目录）：

```bash
cd frontend && npm run typecheck
```

Expected: 无错误输出。

- [ ] **Step 31: 跑外框测试**

Run（在仓库根目录）：

```bash
cd frontend && npx vite build --ssr tests/admin-shell.test.tsx --outDir .ssrout --logLevel error && node .ssrout/admin-shell.test.js
```

Expected: 打印 `7a.` 到 `7d.` 四行 ✓，最后一行 `ALL PASS`。

- [ ] **Step 32: 跑后台原有测试**

Run（在仓库根目录）：

```bash
cd frontend && npx vite build --ssr tests/admin.test.tsx --outDir .ssrout --logLevel error && node .ssrout/admin.test.js
```

Expected: 最后一行 `ALL PASS`。

- [ ] **Step 33: 跑路由集成测试**

Run（在仓库根目录）：

```bash
cd frontend && npx vite build --ssr tests/routing.test.tsx --outDir .ssrout --logLevel error && node .ssrout/routing.test.js
```

Expected: 打印 `后台各页独立地址 / 后退 / 筛选 / 规范化 / 返回产品 ✓` 与 `ALL PASS`，没有 `✗`。

- [ ] **Step 34: 跑主流程测试**

Run（在仓库根目录）：

```bash
cd frontend && npx vite build --ssr tests/flow.test.tsx --outDir .ssrout --logLevel error && node .ssrout/flow.test.js
```

Expected: 打印 `12b. 管理入口 → 管理员进出后台 / 401 后换普通用户不落进后台 ✓` 与 `ALL PASS`，没有 `✗`。

- [ ] **Step 35: 提交**

```bash
git add frontend/src/components/admin/AdminView.tsx frontend/src/App.tsx frontend/src/i18n/zh.ts frontend/src/i18n/en.ts frontend/src/styles/admin.css frontend/tests/admin-shell.test.tsx frontend/tests/admin.test.tsx frontend/tests/routing.test.tsx frontend/tests/flow.test.tsx
git commit -m "运营后台外框接进应用：后台独立成一屏（左侧分组导航 + 右侧内容，窄屏为顶部下拉），不再套产品外壳；每页有自己的地址，页与筛选从地址解析后传给外框，导航是 push、改筛选是 replace；导航计数取自概览（近 7 天失败、未定价模型数）与错误记录（近 7 天条数），概览数据与概览页共用；收起状态记在本地；标题改为「运营后台」，返回改为「返回产品」并回到进后台之前的页；浏览器标题带页名；更新后台、路由、主流程测试并补外框用例"
```

---

### Task 9: 全量验收

**Files:**
- 不改文件（除非这一步发现问题）

- [ ] **Step 1: 跑全部测试（要几分钟）**

Run（在仓库根目录）：

```bash
cd frontend && npm test
```

Expected: 退出码 0，最后一行 `ALL PASS`；整段输出里一共 27 个 `ALL PASS`（原有 25 个测试加 `admin-derive`、`admin-shell`），没有 `✗`。整串任何一个测试失败都会中途停下。`film.test` 偶发卡死的处理见「全局约束」。

- [ ] **Step 2: 跑 lint**

Run（在仓库根目录）：

```bash
cd frontend && npm run lint
```

Expected: 退出码 0，0 条 error，警告恰好是基线的 5 条（`VerificationPanel.tsx`、`CardPicker.tsx`、`ParamsForm.tsx` 的 `only-export-components`，`timeline.ts` 的 `no-control-regex`，`App.tsx` 的 `exhaustive-deps`）；多出任何一条都要回去修。

- [ ] **Step 3: 跑构建**

Run（在仓库根目录）：

```bash
cd frontend && npm run build
```

Expected: 退出码 0，输出里有 `✓ built in …`。「Some chunks are larger than 500 kB」是既有提示，不算失败。

- [ ] **Step 4: 确认工作区干净**

Run（在仓库根目录）：

```bash
git status --short
```

Expected: 只剩一行 `?? docs/specs/2026-10-27-commercialization-design-contract.md`（这份文件不属于本计划，不要动、不要提交）；`frontend/.ssrout`、`frontend/dist` 已被忽略，不会出现。

---
## 自查记录（写计划时已做，执行时不用重复）

**Spec 覆盖：**

| Spec 章节 | 落在哪个 Task |
| --- | --- |
| §3.1 后台独立成一屏、语言与主题切换放进导航 | 8（`AdminView.tsx`、`App.tsx`） |
| §3.2 三个分组六项、真链接、当前页高亮、标题与返回产品 | 7（`AdminNav.tsx`）、8（文案改名） |
| §3.2 可收起并记住、窄屏顶部下拉 | 7（两种形态）、8（宽窄判断、`localStorage`） |
| §3.3 导航计数的三个数字、为 0 不显示、99+、提醒色 | 2（`navCounts`、`badgeText`）、7（徽标）、8（取数与共用概览数据） |
| §3.4 各页地址、筛选参数、规范化、404 | 1 |
| §3.4 导航 push、改筛选 replace、返回产品、浏览器标题、非管理员 | 8（`App.tsx` 与路由集成测试） |
| §4.1 标题行（六页） | 3（`PageHead`）、4（概览）、5（用户 / 错误 / 审计）、6（任务 / 用量） |
| §4.2 表格、统一空状态、错误条卡片底 | 3（`Empty`、样式）、5、6（换用 `Empty`） |
| §4.3 任务筛选、用量分组与天数可受控 | 6（组件）、8（外框把地址传进去） |
| §5.1 – §5.3 概览布局、四份数据、每个数字的来源、行动链接、未定价提醒可点 | 2（计算）、4（界面） |
| §5.4 拿不到就不显示；补充数据失败时省略 | 4（测试 2b 逐份验证） |
| §6 组件与文件 | 见上面的「文件一览」 |
| §7 测试 | 每个 Task 的测试步骤；Task 9 全量 |

**占位符：** 没有 TBD / TODO / 「同上」之类的步骤；每个改代码的步骤都给了完整的原文与替换后的内容，每条命令都写了预期结果。

**命名一致：** `AdminPage`、`JobState`、`UsageGroup`、`UsageDays`、`adminPath`（Task 1）在 Task 2、6、7、8 里用的是同一组名字；`AdminNavFn`、`AdminNavContext`（Task 3）在 Task 7、8 里一致；`AdminView` 的属性 `page`、`jobState`、`usageGroup`、`usageDays`、`onNav`、`onBack`（Task 8）与 `App.tsx`、三个测试文件里的用法一致；`JobsTab` 的 `state` / `onState`、`UsageTab` 的 `group` / `days` / `onQuery`（Task 6）与 Task 8 的 `AdminView` 一致；测试用的 `data-testid`（`stat-*`、`dist-*`、`trend`、`unpriced-alert`、`jobs-running`、`jobs-failed`、`admin-shell`、`admin-sidebar`、`admin-topnav`、`admin-nav-*`、`admin-count-*`、`admin-nav-toggle`、`admin-nav-select`、`admin-back`）在组件与测试里拼写一致。
