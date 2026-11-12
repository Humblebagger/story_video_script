# 前端路由设计（React Router，普通路径）

日期：2026-11-12　分支：langchain　状态：待设计审查

## 1. 背景与目标

现状：前端没有路由，导航全靠 `App.tsx` 里的状态（`novel` / `chapter` / `section` / `adminOpen`）和组件内状态（`ChapterWorkflow` 的 `view` 步骤、`StoryboardView` 的 `tab` 与 `canvas`、`TimelineCanvas` 的 `view`）。地址栏永远是 `/`，刷新回首页、前进后退不可用、不能收藏或分享某一章。

目标：用户在应用里的「位置」完整体现在 URL 上，刷新、前进后退、直接打开链接都回到同一位置。

用户已定：
- 普通路径（history 模式），不用 `#`。
- 引入 React Router。
- 记到「画布和视图」这一层：首页、管理后台、小说分区、章节步骤与分镜页签、出片画布开关、画布视图（时间轴 / 节点图）。选中的镜头、画布侧栏页签、动态面板、助手面板等临时状态不进 URL。

**推翻前置条款**：`2026-10-31-frontend-redesign-design.md` §路由「不引入路由库，沿用状态切换」与 `2026-11-01-workspace-redesign-design.md` 同名条款，本设计起作废。理由：产品要对外上架，刷新丢位置、前进后退失效不可接受；手写路由要自己处理 history、拦截离开、深链接加载，等于重造 React Router。

## 2. 选型

- 包：`react-router`（v7 起合一的包，不再装 `react-router-dom`）。实施时用 npm 上当前稳定大版本并锁定确切版本，核对 `peerDependencies` 含 React 19；与 Vite 无耦合（只用库模式，不用其框架模式 / 插件）。
- 模式：**data router**（`createBrowserRouter` + `<RouterProvider>`），不用 `<BrowserRouter>` 声明式。
  - 理由一：离开拦截要用 `useBlocker`，它只在 data router 下可用（§7）。
  - 理由二：测试用 `createMemoryRouter` 带 `initialEntries` 起在任意深链接（§11）。
  - **不用 loader / action**：数据加载仍由现有 App 代码按路由参数驱动（§5）。不用 loader 是为了控制改动面：现有加载有竞态保护（`openChapterId`）、任务附着、版本选择等逻辑，搬进 loader 是另一次重构，本次不做。

## 3. 路由表

| 路径 | 显示 | 对应现有状态 |
|---|---|---|
| `/` | 未登录：着陆页 Landing；已登录：书架 ShelfHome（含新建小说） | `novel=null, chapter=null` |
| `/admin` | 管理后台 AdminView | `adminOpen=true` |
| `/novels/:nid` | 规范化跳转（replace）到默认分区：有 `proposed` 生命周期事件 → `memory`，否则 `overview` | 沿用 `openNovel` 的默认分区规则 |
| `/novels/:nid/:section` | 小说页某分区；`section ∈ SECTIONS`（overview, chapters, characters, locations, props, creatures, memory, constraints, settings） | `section` |
| `/novels/:nid/chapters/:cid` | 章节工作流，步骤取「该做的那一步」（`currentStep`），不改 URL | `chapter`, `view=cur` |
| `/novels/:nid/chapters/:cid/:step` | 章节某步骤；`step ∈ STEPS`（import, storyboard, review, render, compose, download） | `ChapterWorkflow.view` |
| 同上 + `?tab=focus\|cards\|assets\|source\|render\|json` | 分镜视图页签；缺省 `focus` 不写 | `StoryboardView.tab` |
| `/novels/:nid/chapters/:cid/canvas` | 章节工作流 + 出片画布打开 | `StoryboardView.canvas=true` |
| 同上 + `?view=graph` | 画布显示节点图；缺省时间轴不写 | `TimelineCanvas.view` |
| `*` | 404 页（壳内，一句说明 + 「回到书架」） | — |

说明：
- `/novels/:nid/chapters`（分区「章节」）与 `/novels/:nid/chapters/:cid`（某一章）层级自然嵌套，不冲突。
- 路由里不出现以 `/api` 开头的路径（开发代理占用）。
- 版本（`docVid`）不进 URL：章节打开时仍按「在跑的任务 → 采用版 → 最新版」选。从任务提示、版本条打开指定版本时，通过导航的 `state: { vid?, jobId? }` 传（history state 刷新仍在，分享链接不带）。
- 画布打开时 `canvasPanel='film'`（`openFilm` 那条路径）属于侧栏页签，不进 URL。
- 非法值（`section`/`step`/`tab`/`view` 不在枚举里）→ replace 到去掉该段的上级地址，不报错。

## 4. URL 是导航的唯一真相

- `novel` / `chapter` 的「打开哪一个」、`section`、`adminOpen`、步骤、页签、画布开关、画布视图**都从 URL 读**，不再各自 `useState`。
- 现有所有导航入口（`openNovel`、`openChapter`、`gotoSection`、`newNovel`、`onToggleAdmin`、`ProjectSwitcher`、`ChapterCrumb`、`ProjectNav`、`NovelSidebar`、`ShelfHome`、`NovelPage.onOpenChapter`、`openJob`、`openFromToast`、助手 `onGoto`、`Stepper` 点击、`StoryboardView` 页签与画布按钮、`TimelineCanvas` 切换）改为 `navigate(...)`。组件本身仍收回调 props，`navigate` 只在 App / 路由层调用，避免大批组件依赖路由上下文（§11 测试便利）。
- `novel` / `chapter` 对象（服务端数据）仍是 App 状态，由 URL 参数驱动加载（§5）。
- `ChapterWorkflow` 的「跟步」（完成一步自动跳到下一步）与「助手请求某步」改为写 URL（replace，§8）。
- `StoryboardView` 在「无章节」场景（打开本地 JSON、分批预览）没有地址可写：`tab` / `canvas` / `view` 改为**受控可选**——父级给了值就受控（章节场景，来自 URL），没给就退回组件内状态（本地 JSON 场景，行为与现在一致）。`TimelineCanvas.view` 同理。

## 5. 深链接加载顺序

App 内一个以 `(nid, cid)` 为键的加载 effect，替代 `openNovel` / `openChapter` 的加载部分：

1. 未登录 → 不加载，走 §6。
2. `nid` 变化 → `getNovel(nid)`；`novel` 先置空并显示加载态（壳与侧栏骨架），避免闪出上一本小说。
3. 有 `cid` → 与 `getNovel` 并行 `getChapter(nid, cid)`；成功后沿用现有逻辑：写 `lastChapter`、`openChapterId.current = cid`、附着在跑任务或 `openVersion`（`state.vid` 优先）。
4. 竞态：参数在请求途中又变了 → 丢弃迟到结果（沿用 `openChapterId` 守卫，给小说加同类守卫）。
5. `/novels/:nid`（无分区）在小说加载完后 replace 到默认分区。
6. `section` 只换分区不重新取小说；进章节→回分区时沿用 `gotoSection` 里的 `reloadOpen(novel.id)`。

失败去向（`ApiError.status`）：
- 404 小说 → toast「这本小说不存在或已删除」，replace 到 `/`。
- 404 章节 → toast「这一章不存在或已删除」，replace 到 `/novels/:nid/chapters`。
- 403（别人的小说）→ 与 404 同样处理，不泄露存在性。
- 401 → 走 §6 失效流程，URL 保留。
- 网络错误 / 5xx → 原地显示现有 alert，不跳转（服务恢复后刷新可回来）。
- 应用内删除小说 / 章节（`NovelPage.onDeleted`、`removeChapter`）→ 删除成功后 replace 到 `/` / `/novels/:nid/chapters`，不留指向已删资源的历史项。

## 6. 登录与权限

- **未登录访问任意非 `/` 路径**：不改 URL，渲染着陆页并自动打开登录框（`firstRun` 时为注册框）。登录成功淡出后，应用直接按当前 URL 渲染，即「回到原路径」，无需 `?from=`。
- **token 过期**（`onUnauthorized`）：`resetSignedOut` 清空数据，但**不改 URL**；着陆页 + 登录框（`expired` 提示）。重新登录后回到同一位置。换了账号且资源不属于新账号 → 按 §5 的 403/404 回首页。
- **主动退出**：清空后 `navigate('/', { replace: true })`，避免下一个人登录后落在上一个人的地址。
- **`/admin` 非管理员**：replace 到 `/` + toast「需要管理员权限」。`user` 来自缓存时先渲染，`me()` 回来角色变了再按此规则处理。
- 顶栏「管理后台」开关：进入为 push `/admin`；「返回」为回到进入前的位置（有应用内历史就 `navigate(-1)`，否则 `/`）。

## 7. 未保存修改的拦截

- `anyDirty = dirty || textDirty` 时，`useBlocker` 拦截所有**会离开当前章节或版本**的导航（点链接、程序 `navigate`、浏览器后退前进）。只改 `?tab=` / `?view=` 或开关画布（同一章同一版本）不拦。
- 被拦时复用现有 `useConfirm` 的离开确认文案：确认 → `blocker.proceed()` 并 `clearWork()`；取消 → `blocker.reset()`。
- 现有各入口里的 `confirmLeave()`：凡已改成 `navigate` 的入口**去掉**，由 blocker 统一问，避免问两次。**保留**不改 URL 的场景：同一章内切换版本（`onOpenVersion`、提示里「同一章打开新版本」）、`openLocal`、`newChapter` 等。
- `beforeunload`（关标签页 / 刷新）保持不变。

## 8. 前进后退语义

| 动作 | 方式 |
|---|---|
| 书架 ↔ 小说、切小说、进 / 出管理后台 | push |
| 用户点分区、点章节、点步骤条 | push |
| 打开出片画布 | push |
| 关闭画布 | 有应用内上一项且它就是本章非画布地址 → `navigate(-1)`；否则 replace 到 `/novels/:nid/chapters/:cid` |
| 画布内 时间轴 ↔ 节点图 | replace |
| 分镜页签 `?tab=` | replace |
| 跟步自动前进、助手跳步、规范化（默认分区、非法值） | replace |
| 失败回退（404 / 403 / 无权限） | replace |

「应用内上一项」判定：`location.key !== 'default'`，且进入画布时在 `state` 里记 `fromChapter: true`。

## 9. lastChapter

保留。它服务概览页「继续」按钮（「上次在这本书里看到哪一章」），与 URL 职责不同。写入时机不变（章节加载成功时）。

## 10. 页面标题

由路由层统一设置 `document.title`，格式 `<页面> · <小说> — Inkreel`：
- `/`：`BRAND.title`（不变）
- `/admin`：`管理后台 — Inkreel`
- 小说分区：`<分区名> · <小说名> — Inkreel`
- 章节：`<章节名> · <小说名> — Inkreel`；画布：`出片画布 · <章节名> — Inkreel`
- 404：`页面不存在 — Inkreel`

文案走 i18n（中英）。`main.tsx` 里的一次性 `document.title = BRAND.title` 留作首屏默认。

## 11. 部署要求

- 静态托管必须配置「找不到的路径一律返回 `index.html`」（SPA fallback），否则直接打开 `/novels/...` 或在深链接上刷新会 404。常见写法：Nginx `try_files $uri /index.html;`；Netlify `_redirects` 写 `/* /index.html 200`；Vercel / Cloudflare Pages 用各自的 rewrite 或 SPA 模式。
- Vite 开发服务器与 `vite preview` 默认已做此回退，本地无需改。
- `vite.config.ts` 的 `base` 保持默认 `/`（资源用绝对路径），否则深链接下 JS/CSS 会按相对路径解析而 404。
- 后端不托管前端，无需改动。README 的部署段补一句 SPA fallback 要求。

## 12. 测试策略

- 渲染根：抽出 `routes`（路由配置数组）与 `AppRoot`（`<RouterProvider>` 外壳），`main.tsx` 用 `createBrowserRouter(routes)`，测试用 `createMemoryRouter(routes, { initialEntries })`。
- `tests/flow.test.tsx`（唯一直接渲染 `<App />` 的测试）改为用 memory router 渲染，`initialEntries: ['/']`，原有断言不变；断言里依赖「点击后出现某界面」的部分不受影响。
- 其余组件级测试（workspace / chapter / canvas / graph-view / film 等）：组件仍收回调 props，不依赖路由上下文，原则上不改。`StoryboardView` / `TimelineCanvas` 改为受控可选后，不传新 props 时行为与现在一致，测试应原样通过。
- 新增 `tests/routing.test.tsx`（注册进 `package.json` 的 test 脚本），桩后端 + memory router：
  1. 深链接 `/novels/n1/chapters/c1/canvas?view=graph` → 直接显示该章节画布、节点图视图。
  2. `/novels/n1` → replace 到 `/novels/n1/overview`（有 proposed 时到 `memory`）。
  3. 非法 `section` / `step` / `tab` / `view` → 规范化到上级地址。
  4. 不存在的 `nid` / `cid`（桩返回 404）→ toast + 回 `/` / `/novels/n1/chapters`。
  5. 未登录打开深链接 → 着陆页 + 登录框；登录后停在原深链接。
  6. 非管理员 `/admin` → 回 `/`。
  7. `dirty` 时点侧栏另一章或 `router.navigate(-1)` → 出现离开确认；取消后 URL 不变，确认后离开。
  8. 画布内切节点图 → URL 变 `?view=graph` 且历史长度不增（replace）。
  9. 关闭画布 → 回到章节地址。
  10. 标题随位置变化。
- 验收另需浏览器人工确认：真实刷新、前进后退、新标签页打开复制的链接。

## 13. 实施顺序

1. 引入依赖；抽 `routes` + `AppRoot`；所有路径先都渲染现有 App（行为不变）；`flow.test` 改用 memory router。全绿后提交。
2. 顶层：`/`、`/admin`、`/novels/:nid/:section`；`openNovel` / `gotoSection` / `newNovel` / 管理后台开关 / 退出改 `navigate`；加载 effect 与失败去向（小说级）；404 页。
3. 章节：`/novels/:nid/chapters/:cid[/:step]` 与 `?tab=`；`openChapter` 及所有调用方改 `navigate`（版本、任务经 `state`）；`ChapterWorkflow` 步骤受控；跟步与助手跳步 replace。
4. 画布：`/canvas` 与 `?view=`；`StoryboardView` / `TimelineCanvas` 受控可选；`openFilmN` 改为导航到画布（打开时侧栏仍切出片页）；关闭语义。
5. `useBlocker` 拦截、去掉重复 `confirmLeave`；登录回原路径与 token 过期保持 URL；`document.title`。
6. `tests/routing.test.tsx`；README 部署说明。

每步单独提交，每步跑全量前端测试、lint、build。

## 14. 风险

- **App.tsx 改动面大**（886 行，导航与加载交织）：按 §13 分步，每步行为可验证；加载逻辑原样搬进 effect，不顺手重构。
- **双重确认或漏确认**：blocker 与残留 `confirmLeave` 并存会问两次，漏掉会丢修改；§12 第 7 条覆盖。
- **跟步写 URL 造成循环**：URL→`view`→跟步→写 URL。跟步只在「该做的步」前进时写一次且用 replace；写入值等于当前值时不导航。
- **加载竞态**：快速连点章节或连按后退，迟到的响应覆盖新位置；靠 §5 的守卫。
- **StrictMode 双调用**：加载 effect 必须可重入（取消标记），避免开发模式下重复附着任务。
- **助手桥接**：`requestStep` / `cancelStep` 现在靠「先登记再打开」，改成导航后，登记与挂载时序要保持；保留桥接，只把 `openChapter` 换成 `navigate`。
- **本地 JSON / 分批预览 / 无章节任务面板**没有地址：留在 `/`，刷新会丢（与现在一致），本次不处理。
- **部署忘配 fallback**：深链接直接 404；在 README 和上线检查里写明。
