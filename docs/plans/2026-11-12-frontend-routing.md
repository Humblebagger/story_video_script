# 前端路由 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 React Router（data router、普通路径）让用户在应用里的位置完整体现在 URL 上：刷新、前进后退、直接打开链接都回到同一位置，覆盖首页、管理后台、小说分区、章节步骤与分镜页签、出片画布开关及画布视图。

**Architecture:**
- 只有一条通配路由，元素是现有 `<App/>`。App 用纯函数 `parseLocation(pathname, search)` 把地址解析成位置 `Loc`，URL 是导航的唯一真相。
- 数据加载仍在 App 里，由一个以 `(nid, cid)` 为键的加载 effect 驱动，不用 loader 或 action。
- 组件仍只收回调 props。`ChapterWorkflow` 的步骤、`StoryboardView` 的页签与画布开关、`TimelineCanvas` 的视图改为「受控可选」：给了值就受控，没给就退回组件内状态。
- 离开拦截用 `useBlocker`，判定读 ref；程序性跳转带 `state.force` 放行。

**Tech Stack:** React 19.2.8、react-router 8.5.1（只有 ESM；`RouterProvider` 取自 `react-router/dom`）、Vite 8、happy-dom，测试用 `vite build --ssr` 构建后交给 node 跑。

**Spec:** `docs/specs/2026-11-12-frontend-routing-design.md`（f1ea39b，已过 Fable 设计审查并修订）。下文用「§n」引用它的章节。

---

## 全局约束（每个 Task 都必须遵守）

- **不碰的文件与服务**：
  - 不读、不打印 `backend/.env`；
  - 不调用任何付费厂商，不运行 `render/smoke.py`、`backend/assistant/smoke.py`，不向运行中的服务发送生成、出片或助手请求；
  - 不动 `docs/specs/2026-10-27-commercialization-design-contract.md`（未跟踪文件，保持原样）；
  - 不改后端（`backend/` 下任何文件）。
- **提交规则**：
  - 只 `git add` 具体文件，禁止 `git add -A`、`git commit -a`、`git add -N`；
  - 提交信息用中文、描述性写法，不得含任何 `Co-Authored-By`、Claude 或 Codex 署名行；
  - 不 push。
- **每个 Task 结束前都要通过**（在 `frontend/` 目录下）：
  - `npm test` 退出码为 0；
  - `npm run lint` 为 0 error，允许保留既有基线警告，但**不新增警告**；
  - `npm run build` 成功。
- **film.test 已知偶发卡死**：`tests/film.test.tsx` 在 HEAD 上就会复现，约 1/6～1/3 的概率在「11. 播成片」之前 CPU 自旋、不退出，或报「✗ 预览窗里播视频」。
  - 遇到时单独重跑判定：`npx vite build --ssr tests/film.test.tsx --outDir .ssrout-x --logLevel error && timeout 60 node .ssrout-x/film.test.js`，然后删掉 `.ssrout-x`。
  - 单独重跑能 `ALL PASS` 就不算本任务失败，在报告里注明即可。本计划不修它。
- **不顺手重构**：加载逻辑原样搬进 effect，不改动与路由无关的行为。

## 文件结构

| 文件 | 职责 |
|---|---|
| `frontend/src/paths.ts`（新） | 纯函数：`parseLocation`（地址 → 位置 + 规范化目标）、`novelPath` / `chapterPath`（位置 → 地址）、`NavState` 类型与 `passState`（replace 时透传 state）。不依赖 React |
| `frontend/src/routes.tsx`（新） | 只导出 `routes`：一条 `path: '*'` 路由，元素 `<App/>` |
| `frontend/src/AppRoot.tsx`（新） | 只导出 `AppRoot({ router })` 组件与 `AppRouter` 类型，渲染 `<RouterProvider>` |
| `frontend/src/components/NotFound.tsx`（新） | 404 页：一句说明加「回到书架」 |
| `frontend/src/main.tsx` | 改为 `createBrowserRouter(routes)` 加 `<AppRoot>` |
| `frontend/src/App.tsx` | 导航状态改由 URL 驱动；加载 effect；`go` 导航助手；守卫；blocker；标题 |
| `frontend/src/components/workflow/ChapterWorkflow.tsx` | 步骤改为受控可选（`step` / `onStep` / `onViewChange`）；`openFilm(step?)` |
| `frontend/src/components/StoryboardView.tsx` | 页签、画布、画布视图改为受控可选；`onJumpShot` |
| `frontend/src/components/TimelineCanvas.tsx` | 视图改为受控可选（`view` / `onView`） |
| `frontend/src/i18n/zh.ts`、`en.ts` | 新增 `route.*` 文案 |
| `frontend/tests/paths.test.ts`（新） | 纯函数单测 |
| `frontend/tests/routing.test.tsx`（新） | 用桩后端加 memory router 的路由集成测试，随 Task 2 到 6 逐步加用例 |
| `frontend/tests/flow.test.tsx` | 改用 memory router 渲染 |
| `frontend/package.json`、`package-lock.json` | 加 `react-router@8.5.1`（精确版本）；test 脚本串加入两个新测试 |
| `README.md` | 部署段补 SPA fallback 要求 |

---

### Task 1: 搭路由外壳，行为不变（§13 第 1 步）

**Files:**
- Create: `frontend/src/paths.ts`、`frontend/src/routes.tsx`、`frontend/src/AppRoot.tsx`、`frontend/tests/paths.test.ts`
- Modify: `frontend/src/main.tsx`、`frontend/tests/flow.test.tsx`（渲染部分，约 431-487 行）、`frontend/package.json`、`frontend/package-lock.json`

**受影响的现有测试**：只有 `flow.test.tsx` 直接渲染 `<App/>`，改用 memory router 后所有断言照旧。其余测试不受影响。

- [ ] **Step 1: 安装依赖（精确版本）**

```bash
cd frontend && npm install --save-exact react-router@8.5.1
```

Expected：`package.json` 的 dependencies 出现 `"react-router": "8.5.1"`（没有 `^`），`package-lock.json` 同步更新。不要装 `react-router-dom`。

- [ ] **Step 2: 先写纯函数单测 `frontend/tests/paths.test.ts`**

```ts
/** 路由纯函数：地址 ↔ 位置、非法值规范化（设计 docs/specs/2026-11-12-frontend-routing-design.md §3）。 */
import { chapterPath, novelPath, parseLocation, passState } from '../src/paths'

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }
const eq = (a: unknown, b: unknown, msg: string) =>
  must(JSON.stringify(a) === JSON.stringify(b), `${msg}\n  得到 ${JSON.stringify(a)}\n  期望 ${JSON.stringify(b)}`)

// 1. 顶层
eq(parseLocation('/'), { loc: { kind: 'home' }, fix: null }, '/ 是首页')
eq(parseLocation('/admin'), { loc: { kind: 'admin' }, fix: null }, '/admin 是后台')
eq(parseLocation('/nope').loc, { kind: 'notFound' }, '未知顶层路径是 404')
eq(parseLocation('/admin/x').loc, { kind: 'notFound' }, '/admin 下没有子路径')
console.log('1. 顶层 ✓')

// 2. 小说
eq(parseLocation('/novels/n1'), { loc: { kind: 'novel', nid: 'n1', section: null }, fix: null }, '无分区：section 为 null，等加载完再 replace')
eq(parseLocation('/novels/n1/memory'), { loc: { kind: 'novel', nid: 'n1', section: 'memory' }, fix: null }, '分区')
eq(parseLocation('/novels/n1/chapters'), { loc: { kind: 'novel', nid: 'n1', section: 'chapters' }, fix: null }, '章节分区不是某一章')
eq(parseLocation('/novels/n1/bogus'), { loc: { kind: 'novel', nid: 'n1', section: null }, fix: '/novels/n1' }, '非法分区规范化到上级')
console.log('2. 小说分区 ✓')

// 3. 章节
const ch = (p: string, s = '') => parseLocation(p, s)
eq(ch('/novels/n1/chapters/c1').loc,
   { kind: 'chapter', nid: 'n1', cid: 'c1', step: null, tab: 'focus', canvas: false, view: 'timeline' }, '无步骤段')
eq(ch('/novels/n1/chapters/c1/review', '?tab=cards'),
   { loc: { kind: 'chapter', nid: 'n1', cid: 'c1', step: 'review', tab: 'cards', canvas: false, view: 'timeline' }, fix: null }, '步骤加页签')
eq(ch('/novels/n1/chapters/c1/render/canvas', '?view=graph'),
   { loc: { kind: 'chapter', nid: 'n1', cid: 'c1', step: 'render', tab: 'focus', canvas: true, view: 'graph' }, fix: null }, '画布加节点图')
eq(ch('/novels/n1/chapters/c1/zzz').fix, '/novels/n1/chapters/c1', '非法步骤规范化到章节')
eq(ch('/novels/n1/chapters/c1/import/canvas').fix, '/novels/n1/chapters/c1', '画布只挂在 review/render/compose')
eq(ch('/novels/n1/chapters/c1/import', '?tab=cards').fix, '/novels/n1/chapters/c1/import', '页签只在 review/render/compose 有意义')
eq(ch('/novels/n1/chapters/c1/review', '?tab=zzz').fix, '/novels/n1/chapters/c1/review', '非法页签去掉')
eq(ch('/novels/n1/chapters/c1/review', '?tab=focus').fix, '/novels/n1/chapters/c1/review', 'focus 是缺省值不写进地址')
eq(ch('/novels/n1/chapters/c1/review', '?view=graph').fix, '/novels/n1/chapters/c1/review', '不在画布时 view 去掉')
eq(ch('/novels/n1/chapters/c1/review/canvas', '?view=timeline').fix, '/novels/n1/chapters/c1/review/canvas', 'timeline 是缺省值')
eq(ch('/novels/n1/chapters/c1/review/canvas', '?view=zzz').fix, '/novels/n1/chapters/c1/review/canvas', '非法 view 去掉')
eq(ch('/novels/n1/chapters/c1/review/other').loc, { kind: 'notFound' }, '画布位置只能是 canvas')
eq(ch('/novels/n1/chapters/c1/review/canvas/x').loc, { kind: 'notFound' }, '画布下没有子路径')
console.log('3. 章节、步骤、页签、画布 ✓')

// 4. 拼地址
eq(novelPath('n1'), '/novels/n1', '小说地址')
eq(novelPath('n1', 'props'), '/novels/n1/props', '分区地址')
eq(chapterPath('n1', 'c1'), '/novels/n1/chapters/c1', '章节地址')
eq(chapterPath('n1', 'c1', { step: 'compose', tab: 'assets', canvas: true, view: 'graph' }),
   '/novels/n1/chapters/c1/compose/canvas?tab=assets&view=graph', '完整画布地址')
eq(chapterPath('n1', 'c1', { step: 'download', tab: 'assets', canvas: true, view: 'graph' }),
   '/novels/n1/chapters/c1/download', '非画布步骤丢掉页签、画布与视图')
eq(chapterPath('a b', 'c/1'), '/novels/a%20b/chapters/c%2F1', 'id 要编码')
eq(parseLocation('/novels/a%20b/chapters/c%2F1').loc,
   { kind: 'chapter', nid: 'a b', cid: 'c/1', step: null, tab: 'focus', canvas: false, view: 'timeline' }, 'id 要解码')
console.log('4. 拼地址 ✓')

// 5. state 透传：replace 时去掉一次性的键
eq(passState({ fromChapter: true, panel: 'film', vid: 'v1', jobId: 'j1', force: true }), { fromChapter: true, panel: 'film' },
   '透传保留 fromChapter / panel，去掉 vid / jobId / force')
eq(passState(null), {}, '没有 state 时是空对象')
console.log('5. state 透传 ✓')

console.log('\nALL PASS')
```

- [ ] **Step 3: 跑一次，确认失败**

```bash
cd frontend && npx vite build --ssr tests/paths.test.ts --outDir .ssrout --logLevel error
```

Expected：构建失败，原因是解析不到 `../src/paths`。

- [ ] **Step 4: 写 `frontend/src/paths.ts`**

```ts
/** 前端路由的纯函数：地址 ↔ 位置（设计 docs/specs/2026-11-12-frontend-routing-design.md §3）。
 *  不依赖 React；单测见 tests/paths.test.ts。 */
import { SECTIONS } from './section'
import type { Section } from './section'
import { STEPS } from './workflow'
import type { StepId } from './workflow'
import type { Tab } from './components/StoryboardView'

export const TABS = ['focus', 'cards', 'assets', 'source', 'render', 'json'] as const satisfies readonly Tab[]
/** 画布只挂在这三步（StoryboardView 只在这三步挂载） */
export const CANVAS_STEPS = ['review', 'render', 'compose'] as const satisfies readonly StepId[]
export type CanvasView = 'timeline' | 'graph'

export type Loc =
  | { kind: 'home' }
  | { kind: 'admin' }
  /** section 为 null：地址里没有分区段，小说加载完再 replace 到默认分区 */
  | { kind: 'novel'; nid: string; section: Section | null }
  /** step 为 null：步骤是章节工作流的组件内状态（§4.2） */
  | { kind: 'chapter'; nid: string; cid: string; step: StepId | null; tab: Tab; canvas: boolean; view: CanvasView }
  | { kind: 'notFound' }

/** 路由 state：push 时按需构造；replace 时用 passState 透传 */
export interface NavState {
  /** 程序性跳转：离开拦截放行（§7） */
  force?: boolean
  /** 跨地址打开章节时的一次性参数：打开这一版 / 接上这个任务（§5.4） */
  vid?: string
  jobId?: string
  /** 画布是从章节页里打开的：关闭时可以后退（§8） */
  fromChapter?: boolean
  /** 打开画布时停在哪个侧栏页（只有「出片」） */
  panel?: 'film'
}

const enc = encodeURIComponent
const isIn = <T extends string>(list: readonly T[], v: string | null | undefined): v is T =>
  v != null && (list as readonly string[]).includes(v)

export const isCanvasStep = (s: StepId | null | undefined): s is (typeof CANVAS_STEPS)[number] =>
  isIn(CANVAS_STEPS, s ?? null)

export function novelPath(nid: string, section?: Section | null): string {
  return `/novels/${enc(nid)}${section ? `/${section}` : ''}`
}

export function chapterPath(nid: string, cid: string, o: {
  step?: StepId | null; tab?: Tab | null; canvas?: boolean; view?: CanvasView | null
} = {}): string {
  const board = isCanvasStep(o.step)
  let p = `/novels/${enc(nid)}/chapters/${enc(cid)}`
  if (o.step) p += `/${o.step}`
  const canvas = board && !!o.canvas
  if (canvas) p += '/canvas'
  const q = new URLSearchParams()
  if (board && o.tab && o.tab !== 'focus') q.set('tab', o.tab)
  if (canvas && o.view === 'graph') q.set('view', 'graph')
  const s = q.toString()
  return s ? `${p}?${s}` : p
}

/** replace 时透传的 state：去掉一次性的 vid / jobId / force */
export function passState(s: NavState | null | undefined): NavState {
  const rest: NavState = { ...(s ?? {}) }
  delete rest.vid
  delete rest.jobId
  delete rest.force
  return rest
}

const decode = (s: string) => { try { return decodeURIComponent(s) } catch { return s } }

/** 解析地址。fix 非空 = 地址不规范（非法值、缺省值写进了地址），应 replace 到 fix（§3） */
export function parseLocation(pathname: string, search = ''): { loc: Loc; fix: string | null } {
  const parts = pathname.split('/').filter(Boolean).map(decode)
  const notFound = { loc: { kind: 'notFound' } as Loc, fix: null }
  if (parts.length === 0) return { loc: { kind: 'home' }, fix: null }
  if (parts[0] === 'admin') return parts.length === 1 ? { loc: { kind: 'admin' }, fix: null } : notFound
  if (parts[0] !== 'novels' || parts.length < 2) return notFound
  const nid = parts[1]
  if (parts.length === 2) return { loc: { kind: 'novel', nid, section: null }, fix: null }
  if (parts.length === 3) {
    return isIn(SECTIONS, parts[2])
      ? { loc: { kind: 'novel', nid, section: parts[2] }, fix: null }
      : { loc: { kind: 'novel', nid, section: null }, fix: novelPath(nid) }
  }
  if (parts[2] !== 'chapters' || parts.length > 6) return notFound
  const cid = parts[3]
  const rawStep = parts[4] ?? null
  if (parts.length === 6 && parts[5] !== 'canvas') return notFound
  const base = { kind: 'chapter' as const, nid, cid, tab: 'focus' as Tab, canvas: false, view: 'timeline' as CanvasView }
  if (rawStep === null) {
    const loc: Loc = { ...base, step: null }
    const canon = chapterPath(nid, cid)
    return { loc, fix: search && search !== '?' ? canon : null }
  }
  if (!isIn(STEPS, rawStep)) return { loc: { ...base, step: null }, fix: chapterPath(nid, cid) }
  const wantsCanvas = parts.length === 6
  if (wantsCanvas && !isCanvasStep(rawStep)) return { loc: { ...base, step: null }, fix: chapterPath(nid, cid) }
  const q = new URLSearchParams(search)
  const tab: Tab = isCanvasStep(rawStep) && isIn(TABS, q.get('tab')) ? (q.get('tab') as Tab) : 'focus'
  const view: CanvasView = wantsCanvas && q.get('view') === 'graph' ? 'graph' : 'timeline'
  const loc: Loc = { ...base, step: rawStep, tab, canvas: wantsCanvas, view }
  const canon = chapterPath(nid, cid, { step: rawStep, tab, canvas: wantsCanvas, view })
  const here = pathname + (search && search !== '?' ? search : '')
  return { loc, fix: canon === here ? null : canon }
}
```

> 注：`here` 用调用方传进来的原始 `pathname` 比较。router 给的 `pathname` 是编码后的形式，`chapterPath` 也编码，两边一致。`/novels/n1/chapters/c1?tab=x`（无步骤段却带查询）规范化成去掉查询的地址。

- [ ] **Step 5: 跑单测，确认通过**

```bash
cd frontend && npx vite build --ssr tests/paths.test.ts --outDir .ssrout --logLevel error && node .ssrout/paths.test.js
```

Expected：`ALL PASS`。

- [ ] **Step 6: 写 `frontend/src/routes.tsx` 与 `frontend/src/AppRoot.tsx`**

两个文件分开写：同一个文件既导出组件又导出非组件，会触发 oxlint 的 `only-export-components` 警告。

`frontend/src/routes.tsx`：

```tsx
/** 路由配置：只有一条通配路由，位置由 App 用 parseLocation 解析（设计 §2：不用 loader/action，加载仍在 App） */
import type { RouteObject } from 'react-router'
import App from './App'

export const routes: RouteObject[] = [{ path: '*', element: <App /> }]
```

`frontend/src/AppRoot.tsx`：

```tsx
/** 应用根：接收 router 实例（浏览器用 createBrowserRouter，测试用 createMemoryRouter 并持有它来 navigate、读 state） */
import type { createBrowserRouter } from 'react-router'
import { RouterProvider } from 'react-router/dom'

export type AppRouter = ReturnType<typeof createBrowserRouter>

export function AppRoot({ router }: { router: AppRouter }) {
  return <RouterProvider router={router} />
}
```

> 如果 8.5.1 里 `createMemoryRouter` 与 `createBrowserRouter` 的返回类型不一致，导致 typecheck 报错，就把 `AppRouter` 改成 `import type { DataRouter } from 'react-router'`，以包里实际导出的名字为准，在报告里注明。

- [ ] **Step 7: 改 `frontend/src/main.tsx`**

把 `import App from './App.tsx'` 换成：

```tsx
import { createBrowserRouter } from 'react-router'
import { routes } from './routes'
import { AppRoot } from './AppRoot'
```

在 `initTheme()` 之后加一行 `const router = createBrowserRouter(routes)`，把 JSX 里的 `<App />` 换成 `<AppRoot router={router} />`，其余不动。`document.title = BRAND.title` 先保留，Task 5 再由路由层接管。

- [ ] **Step 8: `flow.test.tsx` 改用 memory router**

在约 433 行，把 `const { default: App } = await import('../src/App')` 换成：

```ts
const { createMemoryRouter } = await import('react-router')
const { routes } = await import('../src/routes')
const { AppRoot } = await import('../src/AppRoot')
const router = createMemoryRouter(routes, { initialEntries: ['/'] })
```

把约 487 行的 `await act(async () => { root.render(<App />) })` 换成 `await act(async () => { root.render(<AppRoot router={router} />) })`。其余不改。

- [ ] **Step 9: 把 paths.test 注册进 test 脚本**

在 `package.json` 的 `test` 脚本串里，紧跟 `node .ssrout/flow.test.js` 之后插入：

```
 && vite build --ssr tests/paths.test.ts --outDir .ssrout --logLevel error && node .ssrout/paths.test.js
```

- [ ] **Step 10: 全量验证**

```bash
cd frontend && npm test && npm run lint && npm run build
```

Expected：全部通过，lint 不新增警告。此时所有地址都渲染同一个 App，行为与改动前完全相同。

- [ ] **Step 11: 提交**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/paths.ts frontend/src/routes.tsx frontend/src/AppRoot.tsx frontend/src/main.tsx frontend/tests/paths.test.ts frontend/tests/flow.test.tsx
git commit -m "引入 react-router 8.5.1 搭路由外壳：一条通配路由渲染现有 App，入口改为 createBrowserRouter 加 AppRoot，新增地址与位置互转、非法值规范化的纯函数及单测，交互流程测试改用内存路由；行为不变"
```

---

### Task 2: 顶层路由（§13 第 2 步）

范围：
- `/`、`/admin`、`/novels/:nid[/:section]`、404 页；
- 小说级加载 effect、`openNovelId` 守卫、失败去向；
- 未登录不加载、token 过期保留 URL、未登录深链接自动弹一次登录框；
- 主动退出（replace 并带 force）、非管理员访问 `/admin`；
- `openLocal` 改成先回到 `/`。

入口处的 `confirmLeave` **全部保留**，Task 5 才换成 blocker。

章节在这一步仍是 App 状态（地址停在 `/novels/:nid/<section>`）。跨小说打开章节先换地址，再由加载 effect 接着打开章节（过渡做法，Task 3 删掉）。

**Files:**
- Create: `frontend/src/components/NotFound.tsx`、`frontend/tests/routing.test.tsx`
- Modify: `frontend/src/App.tsx`、`frontend/src/i18n/zh.ts`、`frontend/src/i18n/en.ts`、`frontend/package.json`（注册 routing.test）

**受影响的现有测试**：
- `flow.test.tsx`：
  - 12b（`:957-975`）：401 后 URL 仍是 `/admin`。bob 登录后按「非管理员离开 `/admin`」规则回到 `/`，断言照旧成立。
  - 8b（`:706-710`）：「新建小说」仍先走 `confirmLeave`，照旧成立。
  - 第 13 节「建完打开小说页」：`submitNovel` 改成导航后由加载 effect 取小说，断言照旧。
- `workspace.test.tsx` 等组件级测试不渲染 App，不受影响。

- [ ] **Step 1: 新增 i18n 文案**

在 `frontend/src/i18n/zh.ts` 的顶层对象里加 `route` 段（位置放在 `nav` 段之后）：

```ts
  route: {
    notFound: { title: '页面不存在', body: '这个地址没有对应的页面，可能链接有误或内容已删除。', back: '回到书架' },
    err: {
      novelGone: '这本小说不存在或已删除',
      chapterGone: '这一章不存在或已删除',
      adminOnly: '需要管理员权限',
    },
    title: { admin: '管理后台', canvas: '出片画布', notFound: '页面不存在' },
    loading: '加载中…',
  },
```

在 `frontend/src/i18n/en.ts` 对应位置加：

```ts
  route: {
    notFound: { title: 'Page not found', body: 'Nothing lives at this address. The link may be wrong or the content was deleted.', back: 'Back to shelf' },
    err: {
      novelGone: 'This novel does not exist or was deleted',
      chapterGone: 'This chapter does not exist or was deleted',
      adminOnly: 'Administrator access required',
    },
    title: { admin: 'Admin', canvas: 'Film canvas', notFound: 'Page not found' },
    loading: 'Loading…',
  },
```

- [ ] **Step 2: 写 `frontend/src/components/NotFound.tsx`**

```tsx
/** 404：地址解析不出页面时，在应用外壳里显示（§3） */
import { EmptyState } from '@/components/common/EmptyState'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/i18n/core'

export function NotFound({ onHome }: { onHome: () => void }) {
  const { t } = useI18n()
  return (
    <div data-testid="not-found">
      <EmptyState title={t('route.notFound.title')} hint={t('route.notFound.body')}
                  action={<Button variant="outline" onClick={onHome}>{t('route.notFound.back')}</Button>} />
    </div>
  )
}
```

> `EmptyState` 的 props 以 `components/common/EmptyState.tsx` 为准。如果 `icon` 是必填，就传 `<FileQuestion className="size-6" />`（来自 lucide-react）。

- [ ] **Step 3: 先写 routing.test 的骨架与本 Task 的用例（会失败）**

新建 `frontend/tests/routing.test.tsx`。脚手架如下：

```tsx
/** 路由集成：桩后端加内存路由，从任意深链接起步（设计 §12.3）。跑法：npm test */
import { Window } from 'happy-dom'

const win = new Window({ url: 'http://localhost:5173' })
const g = globalThis as Record<string, unknown>
for (const k of ['window', 'document', 'navigator', 'location', 'HTMLElement',
                 'Element', 'Node', 'Event', 'CustomEvent', 'getComputedStyle',
                 'localStorage', 'sessionStorage', 'KeyboardEvent', 'MouseEvent', 'matchMedia',
                 'ResizeObserver', 'MutationObserver']) {
  Object.defineProperty(g, k, { value: (win as unknown as Record<string, unknown>)[k], writable: true, configurable: true })
}
g.IS_REACT_ACT_ENVIRONMENT = true
g.IntersectionObserver ??= class { observe() {} unobserve() {} disconnect() {} takeRecords() { return [] } }
g.requestAnimationFrame ??= (cb: (t: number) => void) => setTimeout(() => cb(Date.now()), 16)
g.cancelAnimationFrame ??= (id: number) => clearTimeout(id)
g.Notification = class { static permission = 'denied'; static requestPermission = async () => 'denied' }

/* ---------- 桩后端：一个用户的一本小说、一章、一版 ---------- */
// 形状照抄 flow.test.tsx 的 StubVersion / StubChapter / StubNovel、vsum / chapterSummary / novelView 与 DOC、VERIFIED
//（:53-111、:128-159），复制过来，不抽公共模块
// …（这里粘贴上述类型、序列化函数、DOC、VERIFIED）…

const users: Record<string, { role?: 'admin' }> = { alice: {}, root: { role: 'admin' } }
const userOf = (name: string) => ({ id: name, username: name, created_at: '', ...users[name] })
let novel: StubNovel
function resetData() {
  novel = {
    id: 'n1', title: '药', params: { aspect_ratio: '9:16', art_style: 'realistic' }, updated_at: '',
    chapters: [{ id: 'c1', title: '第一章', order: 1, text: '他推门。', adopted_version: 'v1', digest: null,
                 versions: [{ id: 'v1', created_at: '', edited_at: null, status: 'succeeded',
                              result: JSON.parse(JSON.stringify(DOC)), verification: VERIFIED, error: null }] }],
    memory: { assets: {}, numbering: { next_unit: 2, next_para: 2, next_episode: 2 }, lifecycle: [],
              plot: { outline: '', chapters: [] }, constraints: [] },
  }
}
const unhandled = new Set<string>()
g.fetch = async (url: string, init?: { method?: string; body?: string; headers?: Record<string, string> }) => {
  const path = String(url).replace(/^\/api/, '').split('?')[0]
  const method = init?.method ?? 'GET'
  const json = (data: unknown) => ({ ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(data)) })
  const err = (status: number, detail: unknown) => ({ ok: false, status, statusText: '',
    text: async () => JSON.stringify({ detail }), json: async () => ({ detail }) })
  if (path === '/healthz') return json({ status: 'ok', model: 'stub', api_key_configured: true, users: 2 })
  if (path === '/auth/login' && method === 'POST') {
    const b = JSON.parse(init!.body!)
    return users[b.username] ? json({ token: `tok-${b.username}`, user: userOf(b.username) }) : err(401, '用户名或密码不正确')
  }
  const h = init?.headers?.Authorization ?? ''
  const who = h.startsWith('Bearer tok-') ? h.slice(11) : null
  if (!who || !users[who]) return { ok: false, status: 401, text: async () => '{"detail":"未登录"}', json: async () => ({ detail: '未登录' }) }
  if (path === '/auth/me') return json(userOf(who))
  if (path === '/jobs') return json({ jobs: [] })
  if (path === '/novels' && method === 'GET') return json({ novels: [{ id: novel.id, title: novel.title, updated_at: '', chapters: novel.chapters.length }] })
  const m = path.match(/^\/novels\/([^/]+)(?:\/chapters\/([^/]+)(?:\/versions\/([^/]+)(\/.*)?)?)?(\/summary)?$/)
  if (m && method === 'GET') {
    const [, nid, cid, vid, rest, summary] = m
    if (nid !== novel.id) return err(404, '小说不存在')
    if (summary) return err(404, 'stub')                                  // 费用表拿不到就不显示
    if (!cid) return json(novelView(novel))
    const c = novel.chapters.find((x) => x.id === cid)
    if (!c) return err(404, '章节不存在')
    if (!vid) return json(chapterView(c))
    const v = c.versions.find((x) => x.id === vid)
    if (!v) return err(404, '版本不存在')
    if (!rest) return json({ ...v, novel_id: nid, chapter_id: cid, params: {}, quality_report: null })
    if (rest === '/keyframes') return json({ shots: [] })
    return err(404, 'stub')                                              // 出片会话等：还没建
  }
  unhandled.add(`${method} ${path}`)
  return err(404, 'stub')
}

/* ---------- 驱动 ---------- */
const { act } = await import('react')
const { createRoot } = await import('react-dom/client')
const { createMemoryRouter } = await import('react-router')
const { routes } = await import('../src/routes')
const { AppRoot } = await import('../src/AppRoot')
const { setSession, clearSession } = await import('../src/auth')
type Router = ReturnType<typeof createMemoryRouter>

const doc = win.document as unknown as Document
const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }
const settle = async (ms = 80) => { await act(async () => { await new Promise((r) => setTimeout(r, ms)) }) }

/** 从某个地址起一个全新的应用；who 为空 = 未登录 */
async function boot(path: string, who?: string) {
  resetData()
  win.localStorage.clear()
  clearSession()
  if (who) setSession(`tok-${who}`, userOf(who))
  const container = doc.createElement('div')
  doc.body.appendChild(container)
  const root = createRoot(container)
  const router: Router = createMemoryRouter(routes, { initialEntries: [path] })
  await act(async () => { root.render(<AppRoot router={router} />) })
  await settle(150)
  const here = () => router.state.location.pathname + router.state.location.search
  const has = (s: string) => container.innerHTML.includes(s)
  const q = (sel: string) => container.querySelector(sel) as unknown as HTMLElement | null
  const done = async () => { await act(async () => { root.unmount() }); container.remove() }
  return { router, container, here, has, q, done }
}
const click = async (el: HTMLElement) => { await act(async () => { el.click() }); await settle() }
const button = (box: HTMLElement, text: string) =>
  [...box.querySelectorAll('button')].find((b) => (b.textContent ?? '').trim() === text) as unknown as HTMLElement | undefined

// ===== 用例（各 Task 往下追加，编号与设计 §12.3 对应）=====
```

本 Task 追加的用例：

```tsx
// §12.3-2 /novels/n1：加载完 replace 到默认分区
{
  const a = await boot('/novels/n1', 'alice')
  must(a.here() === '/novels/n1/overview', `无分区应落到概览，实际 ${a.here()}`)
  must(a.router.state.historyAction === 'REPLACE', '默认分区是 replace')
  await a.done()
}
// 有待确认的人物状态提议时到「剧情与记忆」
{
  const a = await boot('/novels/n1', 'alice')
  // 下一次取小说时生效；形状照 flow.test 的 adopt()（:181-186），NovelPage 渲染要用这些字段
  novel.memory.lifecycle.push({ id: 'l1', character_id: 'C01', type: 'deceased', detail: '病死',
    since: { chapter_id: 'c1', unit_ref: 'u0001' }, evidence_quote: '他推门。', origin: 'model',
    status: 'proposed', written_by: { chapter_id: 'c1', version_id: 'v1' } })
  await act(async () => { await a.router.navigate('/') })
  await settle()
  await act(async () => { await a.router.navigate('/novels/n1') })
  await settle(150)
  must(a.here() === '/novels/n1/memory', `有提议时应落到剧情与记忆，实际 ${a.here()}`)
  await a.done()
}
console.log('2. 小说无分区 → replace 到默认分区 ✓')

// §12.3-4（小说部分）不存在的小说：回首页
{
  const a = await boot('/novels/nope/overview', 'alice')
  must(a.here() === '/', `不存在的小说应回首页，实际 ${a.here()}`)
  must(a.router.state.historyAction === 'REPLACE', '失败回退是 replace')
  await a.done()
}
console.log('4a. 不存在的小说 → 回首页 ✓')

// 404 页
{
  const a = await boot('/what/ever', 'alice')
  must(!!a.q('[data-testid="not-found"]'), '未知地址显示 404 页')
  await click(button(a.container, '回到书架')!)
  must(a.here() === '/', '404 页「回到书架」回首页')
  await a.done()
}
console.log('404 页 ✓')

// §12.3-5 未登录打开深链接：着陆页加登录框；登录后停在原地址；关掉登录框后不再自动弹出
{
  const a = await boot('/novels/n1/props')
  must(a.here() === '/novels/n1/props', '未登录不改地址')
  must(!!doc.body.querySelector('[role="dialog"]'), '未登录深链接自动打开登录框')
  // 关掉再重新渲染（同一地址）不再自动弹出
  const close = doc.body.querySelector<HTMLElement>('[role="dialog"] [data-slot="dialog-close"], [role="dialog"] button[aria-label]')
  if (close) { await click(close); await settle(300) }
  await act(async () => { await a.router.navigate('/novels/n1/props', { replace: true }) })
  await settle()
  must(!doc.body.querySelector('[role="dialog"]'), '关掉后同一地址不再自动弹出')
  await a.done()
}
{
  const a = await boot('/novels/n1/props')
  // 在登录框里填 alice 登录（输入方式照 flow.test 的 loginAs：设值后派发 input 事件，再点提交）
  // …实现 loginAs(a, 'alice', 'pw')，桩后端对任意密码放行…
  await settle(600)                                                     // 首页淡出 ≤400ms
  must(a.here() === '/novels/n1/props' && a.has('道具'), `登录后应停在原深链接，实际 ${a.here()}`)
  await a.done()
}
console.log('5. 未登录深链接 → 登录后回到原地址，关掉后不重复弹 ✓')

// §12.3-6 非管理员访问 /admin：回首页
{
  const a = await boot('/admin', 'alice')
  must(a.here() === '/' && !a.has('管理后台'), `普通用户不能停在后台，实际 ${a.here()}`)
  await a.done()
  const b = await boot('/admin', 'root')
  must(b.here() === '/admin' && b.has('管理后台'), '管理员可以直接打开后台')
  await b.done()
}
console.log('6. 非管理员 /admin → 回首页 ✓')
```

文件末尾：

```tsx
if (unhandled.size) console.log('（桩后端未处理：' + [...unhandled].join('，') + '）')
console.log('\nALL PASS')
process.exit(0)
```

> 写 loginAs 时，照抄 flow.test 的写法：找到登录框里的用户名、密码输入框，用原型上的 value setter 设值再派发 `input` 事件（参考 flow.test 里的 `type()` 与 `loginAs()`），然后点提交按钮。关闭按钮的选择器以 `components/auth/AuthDialog.tsx` 的实际结构为准，必要时给关闭按钮加 `data-testid="auth-close"` 再用它。
>
> 桩后端在用例之间共享 `novel`。`boot` 会 `resetData()`，上面第二个 §12.3-2 用例是先 boot 再往桩里加提议，然后来回导航触发重新取小说。

在 `package.json` 的 test 脚本串里，紧跟 paths.test 之后注册：

```
 && vite build --ssr tests/routing.test.tsx --outDir .ssrout --logLevel error && node .ssrout/routing.test.js
```

跑一次，确认失败：

```bash
cd frontend && npx vite build --ssr tests/routing.test.tsx --outDir .ssrout --logLevel error && node .ssrout/routing.test.js
```

Expected：在第 2 条用例就失败（地址停在 `/novels/n1`）。

- [ ] **Step 4: App.tsx：引入路由、`go` 助手与位置派生**

imports 增加：

```ts
import { useLocation, useNavigate } from 'react-router'
import { ApiError } from './api'
import { NotFound } from './components/NotFound'
import { Skeleton } from './components/ui/skeleton'
import { chapterPath, novelPath, parseLocation, passState } from './paths'
import type { NavState } from './paths'
```

`chapterPath` 到 Task 3 才用到。lint 若报未使用，就本 Task 先不导入它。

在 `const [ask, confirmUi] = useConfirm()` 之后加：

```ts
  const location = useLocation()
  const navigate = useNavigate()
  const { loc, fix } = parseLocation(location.pathname, location.search)
  const navState = (location.state ?? null) as NavState | null
  /** 最新地址与 state：异步回调里读，不进依赖 */
  const hereRef = useRef('')
  hereRef.current = location.pathname + location.search
  const navStateRef = useRef<NavState | null>(null)
  navStateRef.current = navState
  /** 导航统一走这里（§5.4、§8）：
   *  - 目标等于当前地址时不导航，返回 false，调用方自己执行同址动作；
   *  - replace 透传当前 state（去掉一次性的键）；
   *  - force = 程序性跳转，离开拦截放行。 */
  const go = useCallback((to: string, o: { replace?: boolean; state?: NavState; force?: boolean } = {}) => {
    if (to === hereRef.current) return false
    const base = o.replace ? passState(navStateRef.current) : {}
    navigate(to, { replace: !!o.replace, state: { ...base, ...o.state, ...(o.force ? { force: true } : {}) } })
    return true
  }, [navigate])
  /** 当前地址指向的小说与章节（URL 是唯一真相） */
  const nid = loc.kind === 'novel' || loc.kind === 'chapter' ? loc.nid : null
  const adminOpen = loc.kind === 'admin'
  const section: Section = loc.kind === 'novel' && loc.section ? loc.section : 'overview'
```

删掉 `const [adminOpen, setAdminOpen] = useState(false)` 和 `const [section, setSection] = useState<Section>('overview')`。

在 `const openChapterId = useRef…` 附近加 `openNovelId` 与跨小说过渡用的 `pendingChapter`：

```ts
  /** 异步回来时 URL 可能已经换了小说：只认地址里的那一本（§5.3） */
  const openNovelId = useRef<string | null>(null)
  openNovelId.current = nid
  /** 第 2 步过渡：跨小说打开章节时先换地址，小说加载完再打开这一章（第 3 步删除） */
  const pendingChapter = useRef<{ cid: string; jobId?: string; vid?: string } | null>(null)
  /** 打开本地 JSON：先回到 /，到了再摆出来（§5.5） */
  const pendingLocal = useRef<Storyboard | null>(null)
  const chapterRef = useRef<Chapter | null>(null)
  chapterRef.current = chapter
```

`chapterRef` 和 `pendingChapter` 声明在 `chapter` 状态之后。

- [ ] **Step 5: 所有 `setNovel` 过守卫（§5.3）**

- `reloadOpen`：`if (nid) setNovel(await getNovel(nid))` 改为 `if (nid) { const n = await getNovel(nid); if (openNovelId.current === nid) setNovel(n) }`。
- `importChapters` 的 finally：`setNovel(await getNovel(nid))` 改为 `const n = await getNovel(nid); if (openNovelId.current === nid) setNovel(n)`。
- `newChapter`：`setNovel(await getNovel(novel.id))` 改为同样的守卫写法（Task 3 会整行删掉）。
- `submitNovel` 见 Step 8。

- [ ] **Step 6: 小说级加载 effect 与默认分区、非法地址、非管理员**

在 `onUnauthorized` 的 effect 之后加：

```ts
  // 非法值、缺省值写进了地址：规范化（§3），带 force 不被离开拦截挡住
  useEffect(() => {
    if (fix) navigate(fix, { replace: true, state: { ...passState(navStateRef.current), force: true } })
  }, [fix, navigate])

  /** 加载 effect 里要用的最新函数：放进 ref，effect 只按 (user, nid) 重跑 */
  // t 也从这里取：语言切换会换 t 的引用，不能让加载 effect 因此重跑（重跑会清空主区）
  const fns = useRef({ clearWork: () => {}, t,
                       openChapterIn: async (n: Novel, p: { cid: string; jobId?: string; vid?: string }) => { void n; void p } })
  fns.current.t = t
  const userId = user?.id
  // 按地址加载小说（§5.1）。第 3 步把章节也并进来
  useEffect(() => {
    if (!userId) return
    if (!nid) {
      if (novelRef.current || chapterRef.current) { fns.current.clearWork(); setNovel(null); setChapter(null) }
      const local = pendingLocal.current
      if (local) {
        pendingLocal.current = null
        fns.current.clearWork(); setDoc(local); savedDoc.current = local
      }
      return
    }
    if (novelRef.current?.id === nid && !pendingChapter.current) return
    let live = true
    if (novelRef.current?.id !== nid) { fns.current.clearWork(); setChapter(null); setNovel(null) }
    getNovel(nid).then((n) => {
      if (!live || openNovelId.current !== nid) return
      setNovel(n)
      const p = pendingChapter.current
      if (p) { pendingChapter.current = null; void fns.current.openChapterIn(n, p) }
    }).catch((e) => {
      if (!live) return
      if (e instanceof ApiError && (e.status === 404 || e.status === 403)) {
        toast.error(t('route.err.novelGone'))
        navigate('/', { replace: true, state: { force: true } })
      } else setAlert(t('app.err.novel', { msg: msg(e) }))
    })
    return () => { live = false }
  }, [userId, nid, navigate])

  // /novels/:nid 没有分区：小说加载完 replace 到默认分区（§3）
  useEffect(() => {
    if (loc.kind !== 'novel' || loc.section || novel?.id !== loc.nid) return
    const sec: Section = novel.memory.lifecycle.some((e) => e.status === 'proposed') ? 'memory' : 'overview'
    navigate(novelPath(loc.nid, sec), { replace: true, state: passState(navStateRef.current) })
  }, [loc, novel, navigate])

  // /admin 只给管理员（§6）；缓存用户的角色以 me() 回来的为准，所以依赖 role
  useEffect(() => {
    if (!user || loc.kind !== 'admin' || user.role === 'admin') return
    toast.error(t('route.err.adminOnly'))
    navigate('/', { replace: true, state: { force: true } })
  }, [user, loc.kind, navigate, t])

  // 未登录打开非首页的地址：自动弹一次登录框（每个地址只弹一次，用户关掉后不再弹）（§6）
  const prompted = useRef(new Set<string>())
  useEffect(() => {
    if (user || entering || loc.kind === 'home' || prompted.current.has(location.pathname)) return
    prompted.current.add(location.pathname)
    setAuth((a) => (a.open ? a : { open: true, mode: firstRun ? 'register' : 'login', expired: false }))
  }, [user, entering, loc.kind, location.pathname, firstRun])
```

注意事项：
- `loc` 对象每次渲染都是新的，作依赖会导致每次渲染都重跑。默认分区 effect 里改成依赖 `loc.kind`、`nid`、`loc.kind === 'novel' ? loc.section : null` 这几个标量，先算成局部常量再放进依赖数组。
- `firstRun` 定义在 `onUnauthorized` effect 之后，以上 effect 放在 `firstRun` 定义之后。
- 加载 effect 里的 `t(...)` 一律写成 `fns.current.t(...)`，`t` 不进依赖（裁定 16）。
- 这些 hooks 都必须在 `if (!user) return …` 提前返回之前。

在 `clearWork` 定义之后加一行 `fns.current.clearWork = clearWork`，在 `openChapterIn` 定义之后（Step 7）加 `fns.current.openChapterIn = openChapterIn`。

- [ ] **Step 7: 改导航入口（保留 `confirmLeave`）**

把现在的 `openChapter` 拆成两段：「在已加载的小说里打开某章」的 `openChapterIn`，和对外入口 `openChapter`。

```ts
  /** 在这本小说里打开某章（地址已经指向这本小说）：给了 vid 就开那一版；否则接上在跑的任务，再否则摆出采用版 */
  const openChapterIn = async (n: Novel, p: { cid: string; jobId?: string; vid?: string }): Promise<boolean> => {
    clearWork()
    try {
      const c = await getChapter(n.id, p.cid)
      if (openNovelId.current !== n.id) return false
      openChapterId.current = c.id
      writeLastChapter(n.id, c.id)
      setChapter(c)
      const live = p.vid ? undefined : p.jobId ?? running.find((j) => j.chapter_id === p.cid)?.id
      if (live) attach(live)
      else {
        const target = p.vid ?? c.adopted_version ?? c.versions[0]?.id
        if (target) void openVersion(n.id, p.cid, target)
      }
      return true
    } catch (e) {
      setAlert(t('app.err.chapter', { msg: msg(e) }))
      return false
    }
  }

  const openChapter = async (cid: string, nid0 = novel?.id, jobId?: string, vid?: string): Promise<boolean> => {
    if (!nid0 || !(await confirmLeave())) return false
    if (nid0 !== openNovelId.current || !novel) {
      // 第 2 步过渡：跨小说先换地址，小说加载完由加载 effect 打开这一章
      pendingChapter.current = { cid, jobId, vid }
      go(novelPath(nid0, 'chapters'))
      return true
    }
    return openChapterIn(novel, { cid, jobId, vid })
  }

  const openNovel = async (target: string) => {
    if (!(await confirmLeave())) return
    clearWork()
    setChapter(null)
    // 同一本：地址相同时不导航，默认分区 effect 也不会动，所以直接回到它的默认分区
    if (!go(novelPath(target)) && novel) {
      go(novelPath(target, novel.memory.lifecycle.some((e) => e.status === 'proposed') ? 'memory' : 'overview'))
    }
  }

  const gotoSection = async (sec: Section) => {
    if (chapter) {
      if (!(await confirmLeave())) return
      clearWork()
      setChapter(null)
      if (novel) void reloadOpen(novel.id)
    }
    if (novel) go(novelPath(novel.id, sec))
  }

  const newNovel = async () => {
    if (!(await confirmLeave())) return
    setActivityTab('activity')
    // 已经在 / 上（本地 JSON、无章节的任务面板）：同址不导航，直接清掉
    if (!go('/')) { clearWork(); setNovel(null); setChapter(null) }
  }

  const enterAdmin = async () => {
    if (!(await confirmLeave())) return
    go('/admin')
  }
  const leaveAdmin = () => {
    if (location.key !== 'default') navigate(-1)
    else navigate('/', { replace: true })
  }
```

说明：
- `openNovel` 里的 `go(novelPath(target))` 返回 false，只发生在地址恰好是无分区的 `/novels/:nid` 时（罕见）。
- 同一本小说在分区地址上，`go` 会 push 无分区地址，再由默认分区 effect replace，结果只多出一条历史记录。

其余调用点：
- AppShell 的 `onToggleAdmin={() => setAdminOpen((v) => !v)}` 改为 `onToggleAdmin={() => { if (adminOpen) leaveAdmin(); else void enterAdmin() }}`。
- `<AdminView me={user} onBack={() => setAdminOpen(false)} />` 改为 `onBack={leaveAdmin}`。
- NovelPage 的 `onDeleted={() => { setNovel(null); void refreshNovels() }}` 改为 `onDeleted={() => { navigate('/', { replace: true, state: { force: true } }); void refreshNovels() }}`。
- `viewKey={adminOpen ? 'admin' : …}` 保持（`adminOpen` 已改为派生值）。
- 删掉 `openChapter` 原来的 `setSection(...)` 两处，以及 `submitNovel` 里的 `setSection('overview')`。

- [ ] **Step 8: `submitNovel`、`openLocal`、退出与失效**

`submitNovel` 的 try 块改为：

```ts
      const created = await createNovel(n.title, n.params)
      const chapters = await createChapters(created.id, n.chapters)
      await refreshNovels()
      if (chapters.length) await openChapter(chapters[0].id, created.id)
      else go(novelPath(created.id, 'overview'))
```

`openLocal` 的成功分支（`clearWork()` 到 `savedDoc.current = …`）改为：

```ts
      const local = parsed as Storyboard      // 本地文件不入库，只能下载；只能在 / 上看
      if (go('/', { force: true })) pendingLocal.current = local
      else { clearWork(); setChapter(null); setNovel(null); setDoc(local); savedDoc.current = local }
```

`resetSignedOut`：删掉 `setAdminOpen(false)` 和行尾的 `setSection('overview')`，**不碰 URL**（过期时保留地址，§6）。

`logout`：

```ts
  const logout = () => {
    clearSession()
    resetSignedOut()
    setAuth({ open: false, mode: 'login', expired: false })
    navigate('/', { replace: true, state: { force: true } })
  }
```

- [ ] **Step 9: 主区渲染按位置分支**

`<div className="main">` 里：
- 在最前面插入：
  ```tsx
  {loc.kind === 'notFound' && <NotFound onHome={() => go('/')} />}
  {nid && novel?.id !== nid && (
    <div className="flex flex-col gap-3" data-testid="route-loading" aria-label={t('route.loading')}>
      <Skeleton className="h-8 w-1/3" /><Skeleton className="h-40 w-full" />
    </div>
  )}
  ```
- ShelfHome 条件从 `!novel && !doc && !job` 改为 `loc.kind === 'home' && !doc && !job`。
- NovelPage 条件从 `novel && !chapter` 改为 `novel && novel.id === nid && !chapter`。
- ChapterWorkflow 条件从 `novel && chapter` 改为 `novel && novel.id === nid && chapter`。

`sidebar`、`projectSwitcher`、`chapterCrumb`、`costMeter`、`onOpenAssistant` 里所有 `novel && …` 前面加上 `novel?.id === nid` 的判断，即加载途中不显示旧小说（§5.2）。做法：在 return 之前定义 `const shown = novel && novel.id === nid ? novel : null`，这些位置的 `novel` 改用 `shown`。`ProjectNav`、`NovelSidebar` 收到的 `novel` 也改用 `shown`。

- [ ] **Step 10: 跑 routing.test 与全量**

```bash
cd frontend && npx vite build --ssr tests/routing.test.tsx --outDir .ssrout --logLevel error && node .ssrout/routing.test.js
cd frontend && npm test && npm run lint && npm run build
```

Expected：routing.test 本 Task 的用例 `ALL PASS`，全量全绿。flow.test 失败时按「受影响的现有测试」逐条核对。

- [ ] **Step 11: 提交**

```bash
git add frontend/src/App.tsx frontend/src/components/NotFound.tsx frontend/src/i18n/zh.ts frontend/src/i18n/en.ts frontend/tests/routing.test.tsx frontend/package.json
git commit -m "顶层路由：首页、管理后台、小说分区与 404 页由地址驱动，打开小说、切分区、新建小说、进出后台改为导航；按地址加载小说并给所有 setNovel 加守卫，小说不存在或无权限回首页，无分区地址 replace 到默认分区，非管理员离开 /admin；未登录不加载、登录失效保留地址，未登录深链接自动弹一次登录框；退出与打开本地 JSON 先回到首页；新增路由集成测试"
```

---

### Task 3: 章节路由（§13 第 3 步）

范围：
- `/novels/:nid/chapters/:cid[/:step]`、`?tab=` 的解析（页签真正生效在 Task 4）；
- `openChapter` 及所有调用方改成导航；加载 effect 并入章节；
- 同址再打开（§5.4）；`state.vid` / `state.jobId` 消费后 replace 清掉；
- `ChapterWorkflow` 步骤改为受控可选，§4.2 的全部入口；助手跳步；删除章节后跳转。

`confirmLeave` 继续保留。删掉 Task 2 的 `pendingChapter` 过渡逻辑。

**Files:**
- Modify: `frontend/src/App.tsx`、`frontend/src/components/workflow/ChapterWorkflow.tsx`、`frontend/tests/routing.test.tsx`

**受影响的现有测试**：
- `flow.test.tsx` 第 4 节（`:579-582`）：在生成中的章节里点左栏同一章，走同址再打开，直接 attach 回到任务面板。
- `flow.test.tsx` 第 8b 节：照旧。
- `workflow-ui.test.tsx`：直接渲染 ChapterWorkflow、不传 `step` / `onStep`，组件内状态行为不变。其中 `:205` 的 `requestStep('c1', 'review')` 走的是桥接，桥接保留，照旧成立。
- `assistant.test.tsx`：只测桥接本身，不受影响。

- [ ] **Step 1: 在 routing.test 追加本 Task 的用例（先失败）**

```tsx
// §12.3-1（章节部分）深链接到章节的某一步
{
  const a = await boot('/novels/n1/chapters/c1/review', 'alice')
  must(a.here() === '/novels/n1/chapters/c1/review', `应停在原地址，实际 ${a.here()}`)
  must(!!a.q('[data-step="review"][aria-current="step"]'), '直接显示 ③')
  await a.done()
}
console.log('1a. 章节步骤深链接 ✓')

// §12.3-4（章节部分）不存在的章节：回这本小说的章节列表
{
  const a = await boot('/novels/n1/chapters/nope', 'alice')
  must(a.here() === '/novels/n1/chapters', `不存在的章节应回章节列表，实际 ${a.here()}`)
  await a.done()
}
console.log('4b. 不存在的章节 → 回章节列表 ✓')

// state.vid 是一次性参数：消费后 replace 清掉（§5.4）
{
  const a = await boot('/novels/n1/overview', 'alice')
  await act(async () => { await a.router.navigate('/novels/n1/chapters/c1', { state: { vid: 'v1' } }) })
  await settle(200)
  const st = a.router.state.location.state as { vid?: string } | null
  must(!st?.vid && a.router.state.historyAction === 'REPLACE', 'vid 消费后应被 replace 清掉')
  await a.done()
}
console.log('state 一次性参数消费 ✓')

// 点步骤条：push /:step；后退回到无步骤段
{
  const a = await boot('/novels/n1/chapters/c1', 'alice')
  await click(a.q('[data-step="review"]')!)
  must(a.here() === '/novels/n1/chapters/c1/review' && a.router.state.historyAction === 'PUSH', '步骤条是 push')
  await act(async () => { await a.router.navigate(-1) })
  await settle()
  must(a.here() === '/novels/n1/chapters/c1', '后退回到章节地址')
  await a.done()
}
console.log('步骤条 push / 后退 ✓')
```

> 选择器 `[data-step="review"]` 以 Stepper 实际渲染为准（flow.test 的 `goStep` 用的就是它）。

- [ ] **Step 2: ChapterWorkflow 步骤改为受控可选**

Props 增加（放在 `openFilm` 之前）：

```ts
  /** 地址里的步骤段（§4.2）：给了就停在这一步，并当作助手请求（首次落地优先于自动跟步）；null/不给 = 步骤是组件内状态 */
  step?: StepId | null
  /** 用户换步骤时 push、自动跟步时 replace（只在地址带步骤段时）；不给 = 只改组件内状态 */
  onStep?: (s: StepId, how: 'push' | 'replace') => void
  /** 实际显示的步骤（上层拼页签、画布地址用） */
  onViewChange?: (s: StepId) => void
```

解构里加上 `step = null, onStep, onViewChange`。

把 `const [view, setView] = useState<StepId>(cur)` 改为 `useState<StepId>(step ?? cur)`，并在它之后加：

```ts
  const stepRef = useRef<StepId | null>(step)
  stepRef.current = step
  /** 程序换步骤（自动跟步、换版本落地）：地址带步骤段时用 replace 同步地址；否则只改组件内状态 */
  const follow = (s: StepId) => {
    setView(s)
    if (stepRef.current && stepRef.current !== s) onStep?.(s, 'replace')
  }
  /** 用户换步骤（步骤条、主按钮、空态按钮、改原文）：受控时 push 地址，地址回来再切；不受控直接切 */
  const go = (s: StepId) => { if (onStep) onStep(s, 'push'); else setView(s) }
  useEffect(() => { onViewChange?.(view) }, [view, onViewChange])
```

在 `asked` 的定义之后加：

```ts
  // 地址里的步骤变了（点步骤条、后退前进、助手跳步）：切过去，并当作助手请求
  useEffect(() => {
    if (!step) return
    asked.current = step
    setView(step)
  }, [step])
```

跟步 effect（`:157-193`）里：
- `setView(want ?? followCur)` 改为 `follow(want ?? stepRef.current ?? followCur)`；
- `setView(followCur)` 改为 `follow(followCur)`。

`follow` 每次渲染都是新函数，effect 依赖列表不要加它；它只读 ref 和稳定的 `setView`。如果 oxlint 的 `exhaustive-deps` 警告新增，用 `useCallback` 包 `follow`（依赖 `onStep`），并加进依赖列表。

用户入口改用 `go`：
- `run` 里 `case 'goto': if (primary.goto) setView(primary.goto)` 改为 `go(primary.goto)`；
- `fix` 里 `if (f.step) setView(f.step)` 改为 `go(f.step)`；
- `recompose` 里 `setView('compose')` 改为 `go('compose')`。`nextFrame(openFilm)` 本 Task 先保留，Task 4 再改；
- GenerateStep 的 `onEditSource={() => setView('import')}` 改为 `go('import')`；
- download 空态按钮 `setView('compose')` 改为 `go('compose')`；
- default 空态按钮 `setView('storyboard')` 改为 `go('storyboard')`；
- Stepper 的 `onView={setView}` 改为 `onView={go}`。

助手桥接 `take()` 保留 `setView(s)` 原样（桥接只给组件级测试和同章请求用；App 不再调用 `requestStep`，见 Step 5）。

- [ ] **Step 3: App.tsx 加载 effect 并入章节（替换 Task 2 的版本）**

位置派生补上：

```ts
  const cid = loc.kind === 'chapter' ? loc.cid : null
```

`openChapterId.current = chapter?.id ?? null` 改为 `openChapterId.current = cid`，异步守卫只认地址里的那一章。

删掉 `pendingChapter` 及其所有使用，删掉 `openChapterIn`。把 Task 2 的加载 effect 整段替换为：

```ts
  const runningRef = useRef<JobSummary[]>([])
  runningRef.current = running
  // 按地址加载小说与章节（§5.1）：(nid, cid) 变了先清掉主区产物，迟到的响应一律丢弃（§5.3）
  useEffect(() => {
    if (!userId) return
    const f = fns.current
    f.clearWork()
    if (!nid) {
      setNovel(null); setChapter(null)
      const local = pendingLocal.current
      if (local) { pendingLocal.current = null; setDoc(local); savedDoc.current = local }
      return
    }
    if (novelRef.current?.id !== nid) setNovel(null)
    setChapter(null)
    let live = true
    const st = navStateRef.current
    void (async () => {
      const [nr, cr] = await Promise.allSettled([getNovel(nid), cid ? getChapter(nid, cid) : Promise.resolve(null)])
      if (!live) return
      const gone = (e: unknown) => e instanceof ApiError && (e.status === 404 || e.status === 403)
      if (nr.status === 'rejected') {
        if (gone(nr.reason)) { toast.error(t('route.err.novelGone')); navigate('/', { replace: true, state: { force: true } }) }
        else setAlert(t('app.err.novel', { msg: msg(nr.reason) }))
        return
      }
      setNovel(nr.value)
      if (!cid) return
      if (cr.status === 'rejected') {
        if (gone(cr.reason)) {
          toast.error(t('route.err.chapterGone'))
          navigate(novelPath(nid, 'chapters'), { replace: true, state: { force: true } })
        } else setAlert(t('app.err.chapter', { msg: msg(cr.reason) }))
        return
      }
      const c = cr.value!
      writeLastChapter(nid, c.id)
      setChapter(c)
      const liveJob = st?.vid ? undefined : st?.jobId ?? runningRef.current.find((j) => j.chapter_id === c.id)?.id
      if (liveJob) f.attach(liveJob)
      else {
        const target = st?.vid ?? c.adopted_version ?? c.versions[0]?.id
        if (target) void f.openVersion(nid, c.id, target)
      }
      // 一次性参数用完就清掉：刷新、后退时不会再接一次已结束的任务或打开已删的版本（§5.4）
      if (st?.vid || st?.jobId) navigate(hereRef.current, { replace: true, state: passState(st) })
    })()
    return () => { live = false }
  }, [userId, nid, cid, navigate])
```

`fns` 的类型与赋值改为 `{ clearWork, attach, openVersion, t }`：在 `openVersion` 定义之后写 `fns.current = { clearWork, attach, openVersion, t }`，初值给同形状的空函数。effect 里的 `t(...)` 写成 `f.t(...)`。

StrictMode 下这个 effect 会跑两遍：第一遍的 `live` 被 cleanup 置成 false，结果丢弃，不会重复 attach，也不会重复消费 state。

- [ ] **Step 4: 改 `openChapter`、同址再打开与各入口**

```ts
  /** 打开章节（§5.4）：跨地址就导航，vid / jobId 作一次性 state；目标就是地址里这一章时不导航，直接执行动作 */
  const openChapter = async (cidT: string, nidT = nid ?? undefined, jobId?: string, vid?: string,
                             o: { force?: boolean } = {}): Promise<boolean> => {
    if (!nidT) return false
    if (nidT === nid && cidT === cid) {
      // 同址再打开：换版本、接任务都会丢掉未保存的修改，所以照样确认（§7 保留项）
      if (vid) {
        if (!(await confirmLeave())) return false
        void openVersion(nidT, cidT, vid)
        return true
      }
      const live = jobId ?? running.find((j) => j.chapter_id === cidT)?.id
      if (live && job?.id !== live) {
        if (!(await confirmLeave())) return false
        clearWork(); attach(live)
      }
      return true
    }
    if (!o.force && !(await confirmLeave())) return false      // 第 5 步换成 blocker 后删掉这一行
    go(chapterPath(nidT, cidT), { state: { ...(jobId ? { jobId } : {}), ...(vid ? { vid } : {}) }, force: o.force })
    return true
  }
```

其余入口：
- `openFromToast.current` 简化为：
  ```ts
  openFromToast.current = (j) => {
    const { novel_id: n, chapter_id: c } = j
    if (n && c) void openChapter(c, n, j.status === 'failed' ? j.id : undefined, j.status === 'failed' ? undefined : j.id)
    else openJob(j as unknown as JobSummary)
  }
  ```
- `gotoSection`：改为
  ```ts
  const gotoSection = async (sec: Section) => {
    if (!nid) return
    if (chapter && !(await confirmLeave())) return
    go(novelPath(nid, sec))
  }
  ```
  离开章节时清空和重读小说都由加载 effect 完成。
- `openNovel`：`clearWork(); setChapter(null)` 两行删掉，由 effect 负责。
- `newNovel`：同址时的 `setChapter(null)`、`setNovel(null)` 保留（同址不会触发 effect）。
- `newChapter`：
  ```ts
  const newChapter = async () => {
    if (!novel || !(await confirmLeave())) return
    try {
      const c = await createChapter(novel.id, t('app.chapterDefault', { n: novel.chapters.length + 1 }))
      await refreshNovels()
      await openChapter(c.id, novel.id, undefined, undefined, { force: true })
      bumpSummary()
    } catch (e) {
      notice.err(t('app.err.createChapter', { msg: msg(e) }))
    }
  }
  ```
- `removeChapter` 成功分支：`clearWork(); setChapter(null); await reloadOpen(novel.id)` 改为 `navigate(novelPath(novel.id, 'chapters'), { replace: true, state: { force: true } })`，保留 `bumpSummary()` 与 `void refreshNovels()`。
- `submitNovel`：`openChapter(chapters[0].id, created.id)` 保留。现在它就是导航，在 `/` 上 `confirmLeave` 必然通过。

- [ ] **Step 5: ChapterWorkflow 接上地址；助手跳步**

```ts
  /** ChapterWorkflow 报上来的实际步骤（拼页签、画布地址用） */
  const viewRef = useRef<StepId | null>(null)
  const stepNav = useCallback((s: StepId, how: 'push' | 'replace') => {
    if (!nid || !cid) return
    // 在 ③④⑤ 之间切换时页签保留（分镜视图不重新挂载）；其它步骤不带页签
    go(chapterPath(nid, cid, { step: s, tab: loc.kind === 'chapter' ? loc.tab : null }), { replace: how === 'replace' })
  }, [nid, cid, go, loc.kind === 'chapter' ? loc.tab : null])
```

依赖里的条件表达式先算成局部常量 `const urlTab = loc.kind === 'chapter' ? loc.tab : null` 再放进去。从 `./workflow` 引入 `StepId` 类型。

ChapterWorkflow 传参增加：

```tsx
                step={loc.kind === 'chapter' ? loc.step : null}
                onStep={stepNav}
                onViewChange={(v) => { viewRef.current = v }}
```

`onViewChange` 用 `useCallback` 包成稳定引用，避免 ChapterWorkflow 的 effect 每次渲染都触发。

AssistantPanel 的 `onGoto` 改为（删掉 `requestStep` / `cancelStep` 的 import）：

```tsx
              onGoto={(g) => {
                if (!nid) return
                if (g.chapter_id === cid) { go(chapterPath(nid, cid, { step: g.step }), { replace: true }); return }
                void confirmLeave().then((ok) => {        // 第 5 步删掉这层确认
                  if (ok) go(chapterPath(nid, g.chapter_id, { step: g.step }))
                })
              }}
```

（`AssistantStep` 就是 `StepId`，见 `types.ts:922`。）

`ChapterCrumb`、`ProjectNav`、`NovelSidebar` 的 `onOpenChapter`，以及 `NovelPage` 的 `onOpenChapter`，都继续调 `openChapter(cid)`，签名兼容。

- [ ] **Step 6: 渲染条件**

- 加载骨架条件改为 `(nid && novel?.id !== nid) || (cid && chapter?.id !== cid)`，即章节加载途中不渲染旧章节（§5.2）。
- NovelPage 条件改为 `shown && loc.kind === 'novel'`。
- ChapterWorkflow 条件改为 `shown && chapter && chapter.id === cid`。
- `inWorkflow` 改为 `!!(shown && chapter && chapter.id === cid && !preview)`。

- [ ] **Step 7: 跑 routing.test、flow.test 与全量**

```bash
cd frontend && npm test && npm run lint && npm run build
```

Expected：全绿。重点看 flow.test 第 4 节：点同一章，回到任务面板。

- [ ] **Step 8: 提交**

```bash
git add frontend/src/App.tsx frontend/src/components/workflow/ChapterWorkflow.tsx frontend/tests/routing.test.tsx
git commit -m "章节路由：章节与步骤由地址驱动，加载 effect 按小说与章节并行取并丢弃迟到响应，章节不存在回章节列表；打开章节改为导航，同址再打开直接接任务或换版本不导航，版本号与任务号作一次性 state 用完即清；章节工作流步骤改为受控可选，步骤条、主按钮、空态、改原文 push，地址带步骤时自动跟步 replace，首次落地优先地址步骤；助手跨章 push、同章 replace；删除章节后回章节列表"
```

---

### Task 4: 画布路由（§13 第 4 步）

范围：
- `/:step/canvas` 与 `?view=`；
- `StoryboardView`（页签、画布、视图）与 `TimelineCanvas`（视图）改为受控可选；
- `openFilm`、fix、recompose、jumpShot、pickUnit 的导航；关闭画布的语义；不能开画布时的规范化；
- 删掉 App 里的 `openFilmN` 计数。

**Files:**
- Modify: `frontend/src/components/StoryboardView.tsx`、`frontend/src/components/TimelineCanvas.tsx`、`frontend/src/components/workflow/ChapterWorkflow.tsx`、`frontend/src/App.tsx`、`frontend/tests/routing.test.tsx`

**受影响的现有测试**：
- `canvas.test.tsx`、`graph-view.test.tsx`、`film.test.tsx`、`compose.test.tsx` 直接渲染 StoryboardView 或 TimelineCanvas，不传新 props，行为不变。
- `workflow-ui.test.tsx` 里传了 `openFilm`（`() => void`），与新签名 `(step?: StepId) => void` 兼容；不受控时 fix、recompose 走原路径。
- `flow.test.tsx` 里涉及「出片」「回到画布重新合成」的段落：现在由 URL 打开画布，断言照旧。如果某段依赖「同一帧打开」的时序，加一次 `settle()`，不改断言。

- [ ] **Step 1: 在 routing.test 追加用例（先失败）**

```tsx
// §12.3-1 深链接到渲染步骤上的画布，节点图视图
{
  const a = await boot('/novels/n1/chapters/c1/render/canvas?view=graph', 'alice')
  must(a.here() === '/novels/n1/chapters/c1/render/canvas?view=graph', `应停在原地址，实际 ${a.here()}`)
  must(!!a.q('.tlc'), '画布打开')
  must(!!a.q('[data-testid="node-graph"]'), '节点图视图')
  await a.done()
}
console.log('1b. 画布加节点图深链接 ✓')

// §12.3-3 不能开画布时规范化：章节没有版本
{
  const a = await boot('/novels/n1/overview', 'alice')
  novel.chapters[0].versions = []; novel.chapters[0].adopted_version = null
  await act(async () => { await a.router.navigate('/novels/n1/chapters/c1/review/canvas') })
  await settle(200)
  must(a.here() === '/novels/n1/chapters/c1', `没有版本时画布地址应规范化，实际 ${a.here()}`)
  await a.done()
}
console.log('3. 不能开画布 → 规范化 ✓')

// §12.3-8 画布内切节点图：replace，fromChapter 仍在
{
  const a = await boot('/novels/n1/chapters/c1/review', 'alice')
  const open = button(a.container, '时间轴画布') ?? a.q('[title*="画布"]')
  await click(open!)
  must(a.here() === '/novels/n1/chapters/c1/review/canvas' && a.router.state.historyAction === 'PUSH', '打开画布是 push')
  const graphBtn = [...a.container.querySelectorAll('.tlc__bar button')].find((b) => b.textContent === '节点图') as unknown as HTMLElement
  await click(graphBtn)
  must(a.here() === '/novels/n1/chapters/c1/review/canvas?view=graph', `切到节点图，实际 ${a.here()}`)
  must(a.router.state.historyAction === 'REPLACE', '切视图是 replace')
  must((a.router.state.location.state as { fromChapter?: boolean } | null)?.fromChapter === true, 'fromChapter 透传')
  // §12.3-9 关闭画布：回到原步骤
  await click(a.q('.tlc__close')!)
  await settle(200)
  must(a.here() === '/novels/n1/chapters/c1/review', `关闭画布回原步骤，实际 ${a.here()}`)
  await a.done()
}
console.log('8/9a. 画布视图 replace、关闭回原步骤 ✓')

// §12.3-9 jumpShot：一次 replace 到 /:step（页签 focus）
{
  const a = await boot('/novels/n1/chapters/c1/render/canvas?tab=cards', 'alice')
  const shot = a.q('.tlc__shot')!
  await act(async () => { shot.dispatchEvent(new win.MouseEvent('dblclick', { bubbles: true }) as unknown as Event) })
  await settle(200)
  must(a.here() === '/novels/n1/chapters/c1/render', `双击镜头跳回聚焦页签，实际 ${a.here()}`)
  must(a.router.state.historyAction === 'REPLACE', 'jumpShot 是一次 replace')
  await a.done()
}
console.log('9b. jumpShot ✓')
```

> 「时间轴画布」按钮的文案以 `board.canvas` 的中文为准（flow.test、film.test 里用的就是这个）。

- [ ] **Step 2: TimelineCanvas 视图受控可选**

Props（`TimelineCanvas.tsx:30-50` 的 interface）增加：

```ts
  /** 画布视图（受控可选，§4.1）：给了就受控，不给用组件内状态 */
  view?: 'timeline' | 'graph'
  onView?: (v: 'timeline' | 'graph') => void
```

解构里加 `view: viewProp, onView`。`:134` 改为：

```ts
  const [viewLocal, setViewLocal] = useState<'timeline' | 'graph'>('timeline')
  const view = viewProp ?? viewLocal
  const setView = (v: 'timeline' | 'graph') => { if (onView) onView(v); else setViewLocal(v) }
```

- [ ] **Step 3: StoryboardView 页签、画布、视图受控可选；jumpShot**

Props 增加：

```ts
  /** 页签（受控可选）：给了 onTab 就受控 */
  tab?: Tab
  onTab?: (t: Tab) => void
  /** 画布开关（受控可选）：给了 onCanvas 就受控；关闭时的重读、图片刷新照常 */
  canvasOpen?: boolean
  onCanvas?: (open: boolean) => void
  /** 画布打开时停在哪个侧栏页（受控时由上层给） */
  canvasPanel?: 'film'
  canvasView?: 'timeline' | 'graph'
  onCanvasView?: (v: 'timeline' | 'graph') => void
  /** 从画布跳回某个镜头（受控时由上层一次 replace 到 /:step，页签 focus）（§4.3） */
  onJumpShot?: () => void
```

函数体改动：

```ts
  const [tabLocal, setTabLocal] = useState<Tab>(defaultTab ?? 'focus')
  const tab = onTab ? (tabProp ?? 'focus') : tabLocal
  const setTab = (next: Tab) => { if (onTab) onTab(next); else setTabLocal(next) }
  const [canvasLocal, setCanvasLocal] = useState(false)
  const canvas = onCanvas ? !!canvasOpen : canvasLocal
  const [panelLocal, setPanelLocal] = useState<'film' | undefined>(undefined)
  const canvasPanel = onCanvas ? canvasPanelProp : panelLocal
  // openFilm 计数：只在不受控时用（受控时上层直接给地址）
  const seenOpenFilm = useRef(openFilm)
  useEffect(() => {
    if (!openFilm || openFilm === seenOpenFilm.current) return
    seenOpenFilm.current = openFilm
    setPanelLocal('film')
    setCanvasLocal(true)
  }, [openFilm])
  const [imagesKey, setImagesKey] = useState(0)
  // 画布从开到关（点关闭、浏览器后退都算）：刷新关键帧图，并让上层重读出片状态
  const wasOpen = useRef(canvas)
  useEffect(() => {
    if (wasOpen.current && !canvas) { setImagesKey((k) => k + 1); setPanelLocal(undefined); onCanvasClose?.() }
    wasOpen.current = canvas
  }, [canvas, onCanvasClose])
  const openCanvas = () => { if (onCanvas) onCanvas(true); else setCanvasLocal(true) }
  const closeCanvas = () => { if (onCanvas) onCanvas(false); else setCanvasLocal(false) }
```

- 解构里把 `tab` 重命名为 `tabProp`、`canvasPanel` 重命名为 `canvasPanelProp`，避免和局部变量重名。
- `onCanvasClose` 是 App 传的箭头函数，每次渲染都是新的，effect 会因此多跑，但只在开变关那一拍生效，无副作用。如果 lint 不满意，用 ref 存最新的 `onCanvasClose`。
- `pickUnit`：保持 `setFocusUnit(unitId); setTab('source')`，`setTab` 已是受控版。
- `jumpShot`：
  ```ts
  const jumpShot = (shotId: string) => {
    setFocusShot((prev) => ({ id: shotId, n: (prev?.n ?? 0) + 1 }))
    if (onJumpShot) onJumpShot()                      // 一次 replace：去掉 /canvas，页签回 focus
    else { closeCanvas(); setTab('focus') }
  }
  ```
- 两处 `onClick={() => setCanvas(true)}` / `onOpenCanvas={() => setCanvas(true)}` 改为 `openCanvas`。
- TimelineCanvas 传参增加 `view={onCanvasView ? canvasView : undefined}` 和 `onView={onCanvasView}`；`initialPanel={canvasPanel}` 保持。

- [ ] **Step 4: ChapterWorkflow：`openFilm(step?)`、fix、recompose**

- Props：`openFilm: () => void` 改为 `openFilm: (step?: StepId) => void`。
- `fix`：
  ```ts
  const fix = (f: Fix) => {
    // 受控且要开画布：一次 push 到 /:step/canvas；否则先换步骤再开
    if (f.step && !(f.openFilm && onStep)) go(f.step)
    if (f.openFilm) openFilm(f.step)
    const target = f.target
    if (target) nextFrame(() => flashTarget(target))
  }
  ```
- `recompose`：
  ```ts
  /** ⑥「回到画布重新合成」：受控时一次 push /compose/canvas；不受控时先回 ⑤ 挂上分镜视图，下一帧再开画布 */
  const recompose = () => {
    if (onStep) { openFilm('compose'); return }
    setView('compose')
    nextFrame(() => openFilm())
  }
  ```
- `run` 里 `case 'openFilm': openFilm(); break` 保持，由上层决定步骤。

- [ ] **Step 5: App.tsx 接上画布地址**

删掉 `openFilmN` 状态，以及 board 里的 `openFilm={openFilmN}`。加：

```ts
  /** 画布挂在哪一步：地址步骤是 ③④⑤ 就用它；否则用工作流实际步骤；都不是就 ⑤（§4.2 openFilm） */
  const boardStep = (): StepId => {
    if (loc.kind === 'chapter' && isCanvasStep(loc.step)) return loc.step
    return isCanvasStep(viewRef.current) ? viewRef.current : 'compose'
  }
  const openCanvas = (step: StepId = boardStep(), panel?: 'film') => {
    if (!nid || !cid) return
    go(chapterPath(nid, cid, { step, tab: urlTab, canvas: true }), { state: { fromChapter: true, ...(panel ? { panel } : {}) } })
  }
  const closeCanvas = () => {
    if (!nid || !cid || loc.kind !== 'chapter') return
    // 从章节里打开的：后退一步，视图和页签的 replace 不会把它弄丢；否则 replace 回原步骤与页签（§8）
    if (navState?.fromChapter && location.key !== 'default') navigate(-1)
    else go(chapterPath(nid, cid, { step: loc.step, tab: loc.tab }), { replace: true })
  }
  // 画布地址但画布挂不上（没有版本、分镜为空、在看分批预览）：等加载落定后规范化回章节地址（§3）
  const [versionLoading, setVersionLoading] = useState(false)
  const canvasStranded = loc.kind === 'chapter' && loc.canvas && chapter?.id === cid
    && !versionLoading && !job && (!doc || !docVid || !!preview)
  useEffect(() => {
    if (canvasStranded && nid && cid) navigate(chapterPath(nid, cid), { replace: true, state: { force: true } })
  }, [canvasStranded, nid, cid, navigate])
```

从 `./paths` 引入 `isCanvasStep`。`openVersion` 开头 `setVersionLoading(true)`，`try/catch` 之后加 `finally { if (openChapterId.current === cid) setVersionLoading(false) }`，这里的 `cid` 指 `openVersion` 的参数。

ChapterWorkflow 传参：`openFilm={() => setOpenFilmN((n) => n + 1)}` 改为 `openFilm={(s) => openCanvas(isCanvasStep(s) ? s : boardStep(), 'film')}`。

board 里的 StoryboardView 只在章节工作流里受控，本地 JSON 与分批预览不受控：

```tsx
          {...(inWorkflow && loc.kind === 'chapter' && nid && cid ? {
            tab: loc.tab,
            onTab: (tb: Tab) => go(chapterPath(nid, cid, { step: boardStep(), tab: tb, canvas: loc.canvas, view: loc.view }),
                                   { replace: true }),
            canvasOpen: loc.canvas,
            onCanvas: (open: boolean) => { if (open) openCanvas(); else closeCanvas() },
            canvasPanel: navState?.panel,
            canvasView: loc.view,
            onCanvasView: (v: 'timeline' | 'graph') =>
              go(chapterPath(nid, cid, { step: boardStep(), tab: loc.tab, canvas: true, view: v }), { replace: true }),
            onJumpShot: () => go(chapterPath(nid, cid, { step: boardStep() }), { replace: true }),
          } : {})}
```

从 `./components/StoryboardView` 引入 `Tab` 类型。

- [ ] **Step 6: 全量**

```bash
cd frontend && npm test && npm run lint && npm run build
```

Expected：全绿。film.test 偶发卡死按全局约束处理。

- [ ] **Step 7: 提交**

```bash
git add frontend/src/components/StoryboardView.tsx frontend/src/components/TimelineCanvas.tsx frontend/src/components/workflow/ChapterWorkflow.tsx frontend/src/App.tsx frontend/tests/routing.test.tsx
git commit -m "画布路由：出片画布挂在 review/render/compose 步骤下的 /canvas 地址，时间轴与节点图由 ?view 记录；分镜页签、画布开关、画布视图改为受控可选，章节里由地址驱动，本地 JSON 与分批预览照旧；出片、修复提示、回到画布重新合成一次 push 到画布地址，切视图、切页签、点原文单元、双击镜头跳回都用 replace；关闭画布能后退就后退，否则回原步骤与页签；画布挂不上时规范化回章节地址"
```

---

### Task 5: 离开拦截与页面标题（§13 第 5 步）

范围：
- `useBlocker`（判定读 ref，`force` 放行）；
- 去掉已改成导航的入口里重复的 `confirmLeave`；
- `document.title` 由路由层设置。

（未登录深链接只弹一次、`openLocal` 回 `/` 已在 Task 2 完成。）

**Files:**
- Modify: `frontend/src/App.tsx`、`frontend/src/main.tsx`、`frontend/tests/routing.test.tsx`

**受影响的现有测试**：
- `flow.test.tsx` 8b：「新建小说」改由 blocker 弹出同一个离开确认，文案相同，取消后留在原处。断言照旧。
- 其它离开确认的段落（若有）同理。

- [ ] **Step 1: routing.test 追加用例（先失败）**

```tsx
// §12.3-7 有未保存修改时离开当前章节：确认；取消留在原地，确认后离开；force 的退出不确认
{
  const a = await boot('/novels/n1/chapters/c1/import', 'alice')
  const ta = a.q('textarea')!
  const set = Object.getOwnPropertyDescriptor(win.HTMLTextAreaElement.prototype, 'value')!.set!
  await act(async () => { set.call(ta, '他推门。改'); ta.dispatchEvent(new win.Event('input', { bubbles: true }) as unknown as Event) })
  await settle()
  await act(async () => { void a.router.navigate('/novels/n1/overview') })
  await settle()
  const dlg = () => doc.body.querySelector('[data-testid="confirm-dialog"]')
  must((dlg()?.textContent ?? '').includes('有未保存的修改'), '离开前应确认')
  await click(doc.body.querySelector<HTMLElement>('[data-testid="confirm-cancel"]')!); await settle(300)
  must(a.here() === '/novels/n1/chapters/c1/import', '取消后地址不变')
  await act(async () => { void a.router.navigate('/novels/n1/overview') }); await settle()
  await click(doc.body.querySelector<HTMLElement>('[data-testid="confirm-ok"]')!); await settle(300)
  must(a.here() === '/novels/n1/overview', '确认后离开')
  await a.done()
}
{
  const a = await boot('/novels/n1/chapters/c1/import', 'alice')
  const ta = a.q('textarea')!
  const set = Object.getOwnPropertyDescriptor(win.HTMLTextAreaElement.prototype, 'value')!.set!
  await act(async () => { set.call(ta, '又改'); ta.dispatchEvent(new win.Event('input', { bubbles: true }) as unknown as Event) })
  await settle()
  // 同一章内换步骤不拦（§7）
  await act(async () => { void a.router.navigate('/novels/n1/chapters/c1/review') }); await settle()
  must(a.here() === '/novels/n1/chapters/c1/review' && !doc.body.querySelector('[data-testid="confirm-dialog"]'), '同章换步骤不拦')
  // 带 force 的程序性跳转放行
  await act(async () => { void a.router.navigate('/', { state: { force: true } }) }); await settle()
  must(a.here() === '/', 'force 放行')
  await a.done()
}
console.log('7. 离开拦截 ✓')

// §12.3-11 页面标题随位置变化
{
  const a = await boot('/novels/n1/props', 'alice')
  must(doc.title === '道具 · 药 — Inkreel', `分区标题，实际 ${doc.title}`)
  await act(async () => { void a.router.navigate('/novels/n1/chapters/c1/review/canvas') }); await settle(200)
  must(doc.title === '出片画布 · 第一章 — Inkreel', `画布标题，实际 ${doc.title}`)
  await act(async () => { void a.router.navigate('/nope') }); await settle()
  must(doc.title === '页面不存在 — Inkreel', `404 标题，实际 ${doc.title}`)
  await a.done()
}
console.log('11. 页面标题 ✓')
```

> 品牌短名是 `src/brand.ts` 的 `BRAND.id`（`Inkreel`）。

- [ ] **Step 2: blocker**

App.tsx 从 `react-router` 引入 `useBlocker`。在 `anyDirty` 定义之后加：

```ts
  // 有未保存修改时离开当前章节：统一在这里确认（§7）。判定读 ref，不读闭包；带 force 的程序性跳转放行
  const dirtyRef = useRef(false)
  dirtyRef.current = anyDirty
  const chapterKey = (pathname: string) => {
    const l = parseLocation(pathname).loc
    return l.kind === 'chapter' ? `${l.nid}/${l.cid}` : null
  }
  const blocker = useBlocker(({ currentLocation, nextLocation }) => {
    if (!dirtyRef.current || (nextLocation.state as NavState | null)?.force) return false
    const a = chapterKey(currentLocation.pathname)
    return !(a !== null && a === chapterKey(nextLocation.pathname))
  })
  useEffect(() => {
    if (blocker.state !== 'blocked') return
    void ask({ title: t('confirm.leave.title'), body: t('confirm.leave.body'), action: t('confirm.leave.action'), danger: true })
      .then((ok) => { if (ok) { clearWork(); blocker.proceed?.() } else blocker.reset?.() })
  }, [blocker, ask, t, clearWork])
```

`useBlocker` 与这个 effect 都必须在 `if (!user)` 提前返回之前。

着陆页分支没有 `confirmUi`，但未登录时 `anyDirty` 必为假（`resetSignedOut` 已清空 doc；ChapterWorkflow 卸载时把 `textDirty` 置回 false），不会进入 blocked。

- [ ] **Step 3: 去掉重复的 `confirmLeave`**

以下入口删掉 `confirmLeave`，改由 blocker 询问：
- `openNovel` 的 `if (!(await confirmLeave())) return`；
- `gotoSection` 的 `if (chapter && !(await confirmLeave())) return`；
- `newNovel` 的确认。同址分支（`!go('/')` 时直接清空）会丢掉本地 JSON 上的未保存编辑，要保留确认：
  ```ts
  if (!go('/')) { if (!(await confirmLeave())) return; clearWork(); setNovel(null); setChapter(null) }
  ```
- `enterAdmin` 的确认；
- `openChapter` 跨地址分支那一行 `if (!o.force && !(await confirmLeave())) return false`；
- AssistantPanel `onGoto` 跨章分支的 `confirmLeave().then(...)`，改为直接 `go(...)`。

保留（不改地址的场景）：
- 同址再打开里的两处；
- 两处 `onOpenVersion`；
- `newChapter` 开头（它随后带 force 导航）。

`openNovel` 在 Task 3 起已不再自己 `clearWork`。

- [ ] **Step 4: 页面标题**

`main.tsx` 删掉 `document.title = BRAND.title`（及因此不再使用的 `BRAND` import）。App.tsx 加：

```ts
  // 页面标题跟着位置走（§10）；加载中不显示上一本小说的名字
  useEffect(() => {
    const brand = BRAND.id
    const novelName = novel && novel.id === nid ? novel.title : null
    const chapterName = chapter && chapter.id === cid ? chapter.title : null
    const join = (head: string, tail: string | null) => (tail ? `${head} · ${tail} — ${brand}` : `${head} — ${brand}`)
    let title = BRAND.title
    if (loc.kind === 'admin') title = `${t('route.title.admin')} — ${brand}`
    else if (loc.kind === 'notFound') title = `${t('route.title.notFound')} — ${brand}`
    else if (loc.kind === 'novel') title = join(t(`nav.${loc.section ?? 'overview'}` as MsgKey), novelName)
    else if (loc.kind === 'chapter') {
      title = loc.canvas ? join(t('route.title.canvas'), chapterName)
        : chapterName ? join(chapterName, novelName) : brand
    }
    document.title = title
  }, [loc.kind, nid, cid, sectionKey, canvasKey, novel, chapter, t])
```

- `MsgKey` 从 `./i18n/core` 引入，写法照 `NodeCards.tsx:87`。
- `sectionKey` / `canvasKey` 是先算好的标量：`loc.kind === 'novel' ? loc.section : null`、`loc.kind === 'chapter' && loc.canvas`。
- `BRAND` 从 `./brand` 引入：`BRAND.id` 是品牌短名 `Inkreel`，`BRAND.title` 是首页标题。

- [ ] **Step 5: 全量**

```bash
cd frontend && npm test && npm run lint && npm run build
```

Expected：全绿，flow.test 8b 只弹一次确认。

- [ ] **Step 6: 提交**

```bash
git add frontend/src/App.tsx frontend/src/main.tsx frontend/tests/routing.test.tsx
git commit -m "离开拦截与页面标题：有未保存修改时离开当前章节统一由 useBlocker 询问，判定读 ref，同章换步骤、页签、视图不拦，带 force 的退出、删除、回退、规范化放行；去掉已改为导航的入口里重复的离开确认，同址换版本与新建章节保留；页面标题随位置变化，加载中不显示上一本小说"
```

---

### Task 6: 收尾测试与部署说明（§13 第 6 步）

范围：
- 补齐 §12.3 里前面没覆盖的用例：非法值规范化的集成验证、同址再打开；
- README 部署段写明 SPA fallback。

**Files:**
- Modify: `frontend/tests/routing.test.tsx`、`README.md`

**受影响的现有测试**：无。

- [ ] **Step 1: routing.test 追加**

```tsx
// §12.3-3 非法 section / step / tab / view：规范化到上级（replace）
for (const [from, to] of [
  ['/novels/n1/bogus', '/novels/n1/overview'],                                  // 先到 /novels/n1 再 replace 到默认分区
  ['/novels/n1/chapters/c1/zzz', '/novels/n1/chapters/c1'],
  ['/novels/n1/chapters/c1/review?tab=zzz', '/novels/n1/chapters/c1/review'],
  ['/novels/n1/chapters/c1/review/canvas?view=zzz', '/novels/n1/chapters/c1/review/canvas'],
] as const) {
  const a = await boot(from, 'alice')
  must(a.here() === to, `${from} 应规范化到 ${to}，实际 ${a.here()}`)
  must(a.router.state.historyAction === 'REPLACE', `${from} 规范化是 replace`)
  await a.done()
}
console.log('3b. 非法值规范化 ✓')

// §12.3-10 同址再打开：在章节里点左栏同一章，地址不变
{
  const a = await boot('/novels/n1/chapters/c1/review', 'alice')
  const before = a.router.state.location.key
  await click(a.q('[data-testid="chapter-card"]')!)
  must(a.here() === '/novels/n1/chapters/c1/review' && a.router.state.location.key === before, '同址不导航')
  await a.done()
}
console.log('10. 同址再打开不导航 ✓')
```

在生成中的章节里点同一章回到任务面板，由 flow.test 第 4 节覆盖。如果左栏章节卡片的 testid 不是 `chapter-card`，以 ProjectNav 实际为准。

- [ ] **Step 2: README 部署说明**

在 `README.md` 的前端开发段（`cd frontend && npm install && npm run dev` 附近）之后加一段：

```markdown
**部署前端（静态托管）**：前端用普通路径路由（如 `/novels/<id>/chapters/<id>/review/canvas`）。静态托管必须配置「找不到的路径一律返回 `index.html`」，否则直接打开深链接或在深链接上刷新会 404。常见写法：
- Nginx：`try_files $uri /index.html;`
- Netlify：`_redirects` 写 `/* /index.html 200`
- Vercel、Cloudflare Pages：用各自的 rewrite 或 SPA 模式

`vite.config.ts` 的 `base` 保持默认 `/`。`npm run dev` 与 `vite preview` 已自带这个回退。
```

- [ ] **Step 3: 全量**

```bash
cd frontend && npm test && npm run lint && npm run build
```

Expected：全绿。

- [ ] **Step 4: 提交**

```bash
git add frontend/tests/routing.test.tsx README.md
git commit -m "路由收尾：补非法分区、步骤、页签、视图规范化与同址再打开的集成用例；README 写明静态托管需配置未知路径回退 index.html"
```

- [ ] **Step 5: 浏览器人工确认清单（交给用户，§12.4）**

1. 在章节、分区、画布、节点图各处按 F5 刷新，都回到原位置。
2. 浏览器前进、后退：打开画布后后退回章节页；切节点图后后退不会一格一格退视图。
3. 复制画布地址，在新标签页打开，直接到画布。
4. 有未保存修改时点左栏别的章节、按后退：先确认；取消后修改还在。
5. 退出登录后地址回到 `/`；登录过期后重新登录，回到原地址。

---

## 实施裁定

对 spec 没定死、或实施中必然要选的细节，裁定如下。实施者照此执行，有异议在报告里提，不自行改。

| # | 裁定 | 理由 | 选错的代价 |
|---|---|---|---|
| 1 | **只有一条 `path: '*'` 路由**，位置由纯函数 `parseLocation` 解析，不用嵌套路由 | spec 已定 App 驱动加载、组件收回调；嵌套路由要把 App 拆成布局与多个子元素，改动面翻倍；纯函数好单测 | 以后要上 loader 时再拆，路径常量与解析可复用 |
| 2 | **「同址」按 (nid, cid) 判定**，不比较步骤、页签、画布 | §5.4 的场景都是「同一章」：点左栏同章时地址可能带着步骤段，按整串比较会误判为跨地址而重开 | 同章不同步骤时点章节卡不会跳回无步骤地址，与现状一致 |
| 3 | **同址再打开且没有任务、没有 vid 时什么都不做**；原来是重新读这一章、重开采用版 | 地址没变、内容已在眼前；原行为的副作用是丢掉正在看的非采用版 | 想回采用版要点版本条，一次点击 |
| 4 | **第 2 步跨小说打开章节用 `pendingChapter` 过渡**：先换到 `/novels/:nid/chapters`，小说加载完再打开章节；第 3 步删除 | 第 2 步章节还不在地址里，直接置章节状态会被小说加载 effect 的清空覆盖 | 过渡代码只存在一个提交内 |
| 5 | **`openLocal` 回 `/` 提前到第 2 步做**（spec 原列第 5 步） | 第 2 步起「地址指向某本小说但 novel 为空」会显示骨架，本地 JSON 不回 `/` 就看不到 | 无 |
| 6 | **未登录深链接只自动弹一次登录框，提前到第 2 步做** | 未登录处理整体在第 2 步，拆开反而要写两遍 | 无 |
| 7 | **画布挂不上时的规范化，等「章节已加载、没有版本在加载、没有附着任务」后才判定** | 深链接时 doc 还在路上，过早判定会把合法画布地址改掉 | 没有版本又挂着生成任务时，画布地址会保留到任务结束才规范化 |
| 8 | **从画布打开时 `panel: 'film'` 放在路由 state**（侧栏页签不进 URL）；刷新画布后侧栏回到「本镜」 | spec §1：侧栏页签是临时状态 | 刷新后要手动点「出片」页签 |
| 9 | **步骤在 ③④⑤ 之间切换时带上当前页签**，切到其它步骤时去掉 | 三步共用同一个分镜视图挂载（`ChapterWorkflow.tsx:325`），原行为就是页签保留 | 无 |
| 10 | **深链接首次加载时若任务列表还没取到，不自动附着在跑的任务**：章节页照常显示，「查看进度」按钮仍可点 | 加载 effect 不等待任务巡检；等它会拖慢所有深链接 | 刷新正在生成的章节时，要多点一次「查看进度」 |
| 11 | **App 不再调用 `requestStep` / `cancelStep`**：助手跳步直接导航到带步骤段的地址；桥接模块保留，供组件级测试和工作台内同章请求 | 地址带步骤段就等同助手请求（§4.2），再登记一遍是重复 | 若以后别处依赖 App 登记，要改回 |
| 12 | **新建章节先 `confirmLeave` 再带 force 导航** | 否则会先建出章节，确认取消后留下空章；先确认后 force 免得 blocker 再问一次 | 无 |
| 13 | **`openNovel` 对同一本小说**：push 无分区地址，再由默认分区 effect replace，结果多一条历史记录 | 复用默认分区逻辑，不写第二份「默认分区怎么算」 | 后退时多停一下同一本小说的分区页 |
| 14 | **routing.test 的桩后端从 flow.test 复制形状**，不抽公共模块 | 抽出 flow.test 的桩是一次独立重构，会动 1200 行的测试 | 两份桩形状将来可能漂移，桩更新时要两边改 |
| 15 | **routing.test 用例随 Task 2 到 6 逐步增加**，不等第 6 步一次写完（spec §13 把测试放在第 6 步） | TDD：每步先写失败用例；第 6 步只补剩余用例 | 无 |
| 16 | **加载 effect 只依赖 `(userId, nid, cid)` 与稳定的 `navigate`**，`clearWork`、`attach`、`openVersion`、`t` 都经 `fns` ref 取 | 这些引用不稳定（`t` 随语言切换而变），作依赖会让 effect 反复重跑、反复清空主区 | 无 |
| 17 | **film.test 偶发卡死不在本计划修**，遇到就单独重跑判定 | HEAD 上已复现，与路由无关 | 无 |
