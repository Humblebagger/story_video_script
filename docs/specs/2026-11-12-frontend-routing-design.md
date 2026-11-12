# 前端路由设计（React Router，普通路径）

日期：2026-11-12　分支：langchain　状态：设计审查后修订（见文末「审查修订记录」）

## 1. 背景与目标

现状：前端没有路由，导航全靠状态。
- `App.tsx` 里的状态：`novel` / `chapter` / `section` / `adminOpen`。
- 组件内状态：`ChapterWorkflow` 的 `view` 步骤，`StoryboardView` 的 `tab` 与 `canvas`，`TimelineCanvas` 的 `view`。

所以地址栏永远是 `/`，刷新回首页，前进后退不可用，也不能收藏或分享某一章。

目标：用户在应用里的「位置」完整体现在 URL 上，刷新、前进后退、直接打开链接都回到同一位置。

用户已定：
- 普通路径（history 模式），不用 `#`。
- 引入 React Router。
- 记到「画布和视图」这一层：首页、管理后台、小说分区、章节步骤与分镜页签、出片画布开关、画布视图（时间轴 / 节点图）。
- 临时状态不进 URL：选中的镜头、画布侧栏页签、动态面板、助手面板。
- **版本号不进 URL**，**管理后台页签不进 URL**（已决）。

**推翻前置条款**：`2026-10-31-frontend-redesign-design.md` §路由「不引入路由库，沿用状态切换」与 `2026-11-01-workspace-redesign-design.md` 的同名条款，自本设计起作废。理由如下：
- 产品要对外上架，刷新丢位置、前进后退失效不可接受。
- 手写路由要自己处理 history、离开拦截、深链接加载，等于重造 React Router。

## 2. 选型

- **包**：`react-router@8.5.1`，锁定确切版本，不再装 `react-router-dom`。
  - 它只提供 ESM，要求 Node ≥ 22.22，peer 依赖 `react` / `react-dom` ≥ 19.2.7。本机是 Node 26.4、React 19.2.8，满足。
  - 与 Vite 无耦合：只用库模式，不用框架模式和插件。
- **入口**：
  - `createBrowserRouter`、`createMemoryRouter`、各种 hooks、`Link` 都取自 `react-router`。
  - `RouterProvider` 取自 `react-router/dom`（DOM 版，内部用 `flushSync`）。`main.tsx` 与测试都从这里取。
- **模式**：用 data router（`createBrowserRouter` + `<RouterProvider>`），不用声明式的 `<BrowserRouter>`。
  - 理由一：离开拦截要用 `useBlocker`，它只在 data router 下可用（§7）。
  - 理由二：测试可以用 `createMemoryRouter` 起在任意深链接，再用 `router.navigate` 驱动（§12）。
  - **不用 loader / action**：数据加载仍由现有 App 代码按路由参数驱动（§5）。现有加载带着竞态保护、任务附着、版本选择等逻辑，搬进 loader 是另一次重构，本次不做。

## 3. 路由表

| 路径 | 显示 |
|---|---|
| `/` | 未登录：着陆页；已登录：书架（含新建小说） |
| `/admin` | 管理后台（页签不进 URL） |
| `/novels/:nid` | 小说加载完后 replace 到默认分区：有 `proposed` 生命周期事件时为 `memory`，否则为 `overview` |
| `/novels/:nid/:section` | 小说某分区，`section ∈ SECTIONS`（9 个） |
| `/novels/:nid/chapters/:cid` | 章节工作流，**无步骤段**：步骤为组件内状态（§4.2） |
| `/novels/:nid/chapters/:cid/:step` | 章节某步骤，`step ∈ STEPS`（import, storyboard, review, render, compose, download） |
| 上一行 + `?tab=…` | 分镜视图页签（focus, cards, assets, source, render, json），只在 review / render / compose 有意义；`focus` 为缺省值，不写进 URL |
| `/novels/:nid/chapters/:cid/:step/canvas` | 该步骤上打开出片画布，`step ∈ review / render / compose`；`?tab=` 保留 |
| 上一行 + `?view=graph` | 画布显示节点图；时间轴为缺省值，不写进 URL |
| `*` | 404 页（在应用外壳内，一句说明加「回到书架」） |

### 说明

- `/novels/:nid/chapters` 是「章节」分区，`/novels/:nid/chapters/:cid` 是某一章，两者自然嵌套，不冲突。
- 不能有以 `/api` 开头的路由，开发代理占用了这个前缀。
- **非法值**：`section` / `step` / `tab` / `view` 不在枚举里时，replace 到去掉该段的上级地址，不报错。
- **画布为什么写成 `/:step/canvas`**：画布挂在 `StoryboardView` 里，而 `StoryboardView` 只在 review / render / compose 三步、并且已经有分镜内容（`doc`）时挂载（`ChapterWorkflow.tsx:281-299`）。
  - 写成路径子段，刷新时能还原「画布底下是哪一步、哪个页签」，关闭画布时去掉 `/canvas` 一段即可，层级清楚。
  - `?canvas=1` 也能表达，但会和 `tab` / `view` 混在同一层，「画布只在这三步存在」的约束表达不出来。
- **画布无法挂载时规范化**：当前不能打开画布（还没有版本、分镜内容为空、正在看分批预览、或步骤不在这三步）时，replace 到 `/novels/:nid/chapters/:cid`。

## 4. URL 与状态

### 4.1 由 URL 驱动的部分

以下几项从 URL 读，不再各自 `useState`：
- 当前打开的是哪本小说、哪一章；
- `section`、`adminOpen`；
- 步骤（URL 带步骤段时）、页签、画布开关、画布视图。

`novel` / `chapter` 对象是服务端数据，仍是 App 状态，按 URL 参数加载（§5）。

`navigate` 只在 App / 路由层调用。组件仍收回调 props，这样大部分组件测试不依赖路由上下文。

**受控可选**：`ChapterWorkflow` 的步骤、`StoryboardView` 的 `tab` / `canvas`、`TimelineCanvas` 的 `view` 都改成「受控可选」：父级给了值就受控，没给就退回组件内状态，行为与现在一致。
- 不给值的场景：打开本地 JSON、看分批预览、组件级测试（`workflow-ui.test`、`canvas.test` 等直接渲染组件）。
- `flow.test` 里给值。

### 4.2 章节步骤（无步骤段 vs 有步骤段）

**URL 无步骤段**（`/chapters/:cid`）：步骤是组件内状态，完全沿用现有行为（`ChapterWorkflow.tsx:127-130`、`163-192`）：
- 初值取当前该做的那一步 `cur`；
- 只往前跟，不把视图往回拉；
- 有未保存修改时不跟；
- 不写 URL。

**URL 有步骤段**（`/chapters/:cid/:step`）：等同于助手请求了这一步（`asked`）。
- 首次落地（包括换版本后的落地）时，URL 的步骤优先于自动跟步（`followCur`），停在 URL 指定的那一步。
- 之后出片状态前进触发自动跟步时，用 replace 改写 URL 里的步骤，规则与无步骤段时相同：只往前、不往回拉、有未保存修改时不跟。

**步骤入口与历史方式**：

| 入口 | 位置 | 导航 |
|---|---|---|
| 步骤条点击 | Stepper | push `/:step` |
| 主按钮「去某一步」（goto） | `ChapterWorkflow.tsx:211` | push `/:goto` |
| 主按钮「出片」（openFilm） | `:214` | push `/:view/canvas`；当前步不在 review / render / compose 时用 `compose` |
| 修复提示（fix） | `:229-234` | 有 `f.step` 时 push `/:f.step`，带 `f.openFilm` 时 push `/:f.step/canvas`；高亮目标仍下一帧执行 |
| ⑥「回到画布重新合成」（recompose） | `:236-240` | 一次 push `/compose/canvas`；画布由 URL 受控打开，不再用 `nextFrame(openFilm)` 的计数技巧 |
| 「改原文」（onEditSource） | `:267` | push `/import` |
| 空态「去第 5 步」 | `:287` | push `/compose` |
| 空态「去第 2 步」 | `:294` | push `/storyboard` |
| 助手跳步 | `App.tsx` 的 `onGoto` → `requestStep` | 跨章节时 push `/chapters/:cid/:step`；同章节时 replace |
| 自动跟步（URL 有步骤段时） | `ChapterWorkflow.tsx:163-192` | replace |

### 4.3 分镜页签与画布内的入口

| 入口 | 位置 | 导航 |
|---|---|---|
| 页签切换 | StoryboardView | replace `?tab=` |
| 点原文单元（pickUnit） | `StoryboardView.tsx:91` | replace `?tab=source`；定位哪个单元（`focusUnit`）仍是组件状态 |
| 打开画布 | StoryboardView 按钮、`openFilm` | push `/:step/canvas` |
| 画布内 时间轴 ↔ 节点图 | TimelineCanvas | replace `?view=` |
| 关闭画布 | onClose | 见 §8 |
| 从画布跳回某个镜头（jumpShot） | `StoryboardView.tsx:96-100` | **一次** replace 到 `/:step?tab=focus`（去掉 `/canvas`，页签设为 `focus`）；定位哪个镜头（`focusShot`）仍是组件状态。不用「先后退一步再 replace」两步走 |

## 5. 加载、同址再打开与失败去向

### 5.1 加载

App 内用一个以 `(nid, cid)` 为键的加载 effect，替代 `openNovel` / `openChapter` 里的加载部分。

1. 未登录时不加载，走 §6。
2. `(nid, cid)` 变化时，**先 `clearWork()`**（清掉 doc、任务、预览、复验结果），再发请求。
   - 原因：防止旧 doc 经 `!inWorkflow && board`（`App.tsx:875`）在新位置上闪现。
3. `nid` 变化时调 `getNovel(nid)`，并把 `novel` 先置空。
4. 有 `cid` 时，`getChapter(nid, cid)` 与第 3 步并行。成功后沿用现有逻辑：
   - 写 `lastChapter`，设 `openChapterId.current = cid`；
   - 附着在跑的任务，或调 `openVersion`。`state.jobId` / `state.vid` 优先，见 §5.3。
5. `/novels/:nid`（无分区）在小说加载完后 replace 到默认分区。
6. 只换 `section` 不重新取小说。从章节回到分区时，沿用 `gotoSection` 里的 `reloadOpen(novel.id)`。

### 5.2 加载途中显示什么

URL 已经指向新位置、数据还没到时（`novel?.id ≠ nid`，或 `chapter?.id ≠ cid`）：
- 主区显示加载骨架，侧栏和顶栏也只显示骨架；
- 不渲染旧的小说页、旧的章节工作流、旧的分镜；
- 各类按钮不可用。

### 5.3 竞态守卫

迟到的响应一律丢弃：响应回来时，URL 当前的 `nid` / `cid` 已经不是发请求时的值，就不落地。

**所有 `setNovel` 都要过守卫**，用一个 `openNovelId` ref，与 `openChapterId` 对称：
- 加载 effect；
- `reloadOpen`（`App.tsx:132`）；
- `importChapters`（`:487`）；
- `newChapter`（`:499`）；
- `submitNovel`（`:453`）。

`setChapter` 继续用现有的 `openChapterId` 守卫。

### 5.4 同址再打开

目标地址等于当前地址时，**不导航**，直接执行原来的动作：
- 正在看的这一章，又被要求附着某个任务：直接 `attach`；
- 要求打开某一版：直接 `openVersion`；
- 要求重置：`clearWork`。

涉及的场景：
- 在生成中的章节里，点左栏同一章的章节卡回到任务面板（`App.tsx:382-405`、`flow.test.tsx:580-581`）；
- 从任务提示打开同一章（`:436-442`）；
- 同一章内切换版本（`:811`）。

**`state.vid` / `state.jobId` 的定位**：它们只是「跨地址导航」时的一次性参数。加载 effect 消费后，立即 `navigate(当前地址, { replace: true, state: 去掉 vid 和 jobId 后的 state })`，保证刷新、后退时不会再触发（§8 的 state 透传规则同样适用）。

### 5.5 失败去向

按 `ApiError.status` 分：
- **小说 404**：toast「这本小说不存在或已删除」，replace 到 `/`。
- **章节 404**：toast「这一章不存在或已删除」，replace 到 `/novels/:nid/chapters`。
- **403**（别人的小说）：与 404 同样处理，不泄露资源是否存在。
- **401**：走 §6 的失效流程，URL 保留。
- **网络错误 / 5xx**：原地显示现有的 alert，不跳转，服务恢复后刷新即可回来。

应用内删除小说或章节（`NovelPage.onDeleted`、`removeChapter`）成功后，replace 到 `/` 或 `/novels/:nid/chapters`。

**其它不改 URL 的入口**：`openLocal`（打开本地 JSON，`App.tsx:609-623`）在章节内调用时，先 `navigate('/', { state: { force: true } })` 再摆出本地 doc。本地 doc 只能在 `/` 上看。

## 6. 登录与权限

**未登录访问任意非 `/` 路径**：
- 不改 URL，渲染着陆页并自动打开登录框；`firstRun` 时打开注册框。
- 登录成功、首页淡出后，应用直接按当前 URL 渲染，即「回到原路径」，不需要 `?from=`。
- 用户自己关掉登录框后，停在着陆页，不再自动弹出（按 URL 记一次「已自动弹过」）。

**token 过期**（`onUnauthorized`）：
- `resetSignedOut` 清空数据，但**不改 URL**；显示着陆页和带过期提示的登录框。
- 重新登录后回到同一位置。
- 换了账号且资源不属于新账号时，按 §5.5 的 403 / 404 回首页；停在 `/admin` 的普通用户按下面的规则回 `/`（`flow.test` 12b 继续成立）。

**主动退出**：清空后 `navigate('/', { replace: true, state: { force: true } })`，避免下一个人登录后落在上一个人的地址上。退出本来就不需要确认（`App.tsx:641`）。

**`/admin` 非管理员**：replace 到 `/` 并 toast「需要管理员权限」。`user` 来自缓存时先按缓存渲染，`me()` 返回后角色变了再按此规则处理。

**管理后台（语义变化，已裁定）**：
- 现在后台是工作区上的一层开关，关掉就回到原来的小说和章节，工作区内存不丢。
- 改成路由后，**进入 `/admin` 就是离开工作区**：有未保存修改时由 blocker 确认，进入后 doc 等工作数据清空。
- 后台的「返回」以及浏览器后退，会回到之前的地址，并按 §5 重新加载那本小说和那一章。
- 进入用 push `/admin`。「返回」时，有应用内历史就 `navigate(-1)`，否则 replace 到 `/`。

## 7. 未保存修改的拦截

- 未保存状态 `anyDirty = dirty || textDirty` 写进一个 ref，**blocker 的判定函数读这个 ref**，不读闭包里的值。
- 拦截范围：有未保存修改时，所有**离开当前章节**（`nid` / `cid` 变化，或离开章节层）的导航都拦，包括点链接、程序里的 `navigate`、浏览器后退前进。
- 不拦：同一章内只改 `?tab=` / `?view=`、开关画布、切换步骤。这些不丢修改：doc 在 App 状态里，原文草稿在 `ChapterWorkflow` 里，它们都不随这些变化卸载。
- **跳过拦截**：带 `state.force === true` 的程序性跳转一律放行。包括：
  - 主动退出与 token 过期后的回退；
  - 删除后的跳转；
  - 加载失败的回退、规范化、非管理员回退；
  - `openLocal`。
- **被拦时**：复用现有 `useConfirm` 的离开确认。确认后先 `clearWork()` 再 `blocker.proceed()`；取消则 `blocker.reset()`。
- **着陆页分支**：没有挂 `confirmUi`（`App.tsx:655-668`），而未登录时 `anyDirty` 必为假（`resetSignedOut` 已清空），所以不会进入需要确认的状态。
- **`confirmLeave()` 的去留**：凡是已改成 `navigate` 的入口都去掉，由 blocker 统一询问，避免问两次。保留不改 URL 的场景：同一章内切换版本（`onOpenVersion`、提示里「同一章打开新版本」）、同址再打开（§5.4）、`newChapter`。
- `beforeunload`（关标签页、刷新）保持不变。

## 8. 前进后退语义

| 动作 | 方式 |
|---|---|
| 书架 ↔ 小说、切换小说、进入管理后台 | push |
| 用户点分区、点章节、点步骤入口（§4.2） | push |
| 打开出片画布 | push |
| 关闭画布 | 进入画布时在 `state` 里记了 `fromChapter: true`，且 `location.key !== 'default'` 时 `navigate(-1)`；否则 replace 到 `/:step`，保留 `?tab=` |
| 画布内 时间轴 ↔ 节点图、分镜页签、pickUnit、jumpShot | replace |
| 自动跟步、同章节内的助手跳步、规范化 | replace |
| 失败回退（404 / 403 / 无权限）、消费 `state.vid` / `state.jobId` | replace |

**state 透传规则**：所有 replace 都透传当前的 `location.state`，只去掉已消费的键，保证画布上的 `fromChapter` 在切换视图、页签之后仍在。push 时按需构造新的 `state`。

## 9. lastChapter

保留。它服务概览页的「继续」按钮（这本书上次看到哪一章），与 URL 职责不同。写入时机不变，仍在章节加载成功时写。

## 10. 页面标题

由路由层统一设置 `document.title`，格式为 `<页面> · <小说> — Inkreel`：

| 位置 | 标题 |
|---|---|
| `/` | `BRAND.title`（不变） |
| `/admin` | `管理后台 — Inkreel` |
| 小说分区 | `<分区名> · <小说名> — Inkreel` |
| 章节 | `<章节名> · <小说名> — Inkreel` |
| 画布 | `出片画布 · <章节名> — Inkreel` |
| 404 | `页面不存在 — Inkreel` |

- 文案走 i18n，中英文都有。
- 数据加载中时只显示分区名或 `Inkreel`，不显示上一本小说的名字。

## 11. 部署要求

- 静态托管必须配置「找不到的路径一律返回 `index.html`」（SPA fallback），否则直接打开 `/novels/...` 或在深链接上刷新会 404。常见写法：
  - Nginx：`try_files $uri /index.html;`
  - Netlify：`_redirects` 里写 `/* /index.html 200`
  - Vercel、Cloudflare Pages：用各自的 rewrite 或 SPA 模式。
- Vite 开发服务器与 `vite preview` 默认已做这个回退，本地无需改。
- `vite.config.ts` 的 `base` 保持默认 `/`，让资源走绝对路径，否则深链接下 JS / CSS 会按相对路径解析而 404。
- 后端不托管前端，不需要改。README 的部署段补一句 SPA fallback 的要求。

## 12. 测试策略

### 12.1 渲染根

- 抽出 `routes`（路由配置数组），以及 `AppRoot({ router })` 外壳：外壳**接收 router 实例**，再渲染 `<RouterProvider router={router} />`。
- `main.tsx` 传 `createBrowserRouter(routes)`；测试传 `createMemoryRouter(routes, { initialEntries })`，并持有 router 实例，用来调 `router.navigate(...)` 和读 `router.state`。

### 12.2 现有测试

- `tests/flow.test.tsx` 是唯一直接渲染 `<App />` 的测试，改用 memory router 渲染，`initialEntries: ['/']`，原有断言不变。
  - 第 2 到 4 步保留各入口处的 `confirmLeave`（§13），所以 8b（`flow.test.tsx:706-710`）的离开确认继续成立；第 5 步换成 blocker 后，它仍应通过。
  - 12b（`:969-974`）依靠 §6「过期保留 URL」和「非管理员离开 `/admin`」继续成立。
- 其余组件级测试（workspace / chapter / canvas / graph-view / film / workflow-ui 等）：组件是受控可选的，不传新 props 时行为不变，应原样通过。

### 12.3 新增 `tests/routing.test.tsx`

注册进 `package.json` 的 test 脚本，用桩后端加 memory router：
1. 深链接 `/novels/n1/chapters/c1/render/canvas?view=graph`：直接显示该章节、渲染步骤上的画布、节点图视图。
2. `/novels/n1`：replace 到 `/novels/n1/overview`；有 `proposed` 事件时到 `memory`。断言 `router.state.historyAction === 'REPLACE'`。
3. 非法的 `section` / `step` / `tab` / `view`，以及在不能开画布时访问 `/canvas`：规范化到上级地址。
4. 不存在的 `nid` / `cid`（桩返回 404）：出 toast，回到 `/` 或 `/novels/n1/chapters`。
5. 未登录打开深链接：显示着陆页和登录框，登录后停在原深链接；关掉登录框后不再自动弹出。
6. 非管理员访问 `/admin`：回 `/`。
7. 有未保存修改时点侧栏另一章，或调 `router.navigate(-1)`：出现离开确认；取消后 URL 不变，确认后离开。带 `force` 的退出不确认。
8. 画布内切到节点图：URL 变成 `?view=graph`，且 `historyAction === 'REPLACE'`；`state.fromChapter` 仍在。
9. 关闭画布：回到原步骤和原 `tab`。jumpShot 一次 replace 到 `?tab=focus`。
10. 同址再打开：在生成中的章节里点左栏同一章，回到任务面板，URL 不变。
11. 页面标题随位置变化。

### 12.4 浏览器人工确认

真实刷新、前进后退、在新标签页打开复制的链接。

## 13. 实施顺序

每步单独提交，每步都跑全量前端测试、lint 和 build。

1. **搭外壳，行为不变**：引入依赖；抽出 `routes` 与 `AppRoot({ router })`；所有路径先都渲染现有 App；`flow.test` 改用 memory router。全绿后提交。
2. **顶层路由**：
   - `/`、`/admin`、`/novels/:nid/:section`、404 页。
   - `openNovel` / `gotoSection` / `newNovel` / 管理后台开关改成 `navigate`；退出改成 replace 并带 `force`。
   - 小说级的加载 effect、`openNovelId` 守卫、失败去向。
   - **未登录时不加载、token 过期保留 URL**（改 `resetSignedOut` 不动 URL，保证 `flow.test` 12b 通过）。
   - 入口处的 `confirmLeave` **暂时保留**。
3. **章节路由**：
   - `/chapters/:cid[/:step]`、`?tab=`；`openChapter` 及所有调用方改成 `navigate`。
   - 同址再打开（§5.4）、`state` 的消费与透传。
   - `ChapterWorkflow` 步骤改为受控可选，§4.2 的全部入口。
   - `confirmLeave` 继续暂时保留。
4. **画布路由**：
   - `/:step/canvas` 与 `?view=`；`StoryboardView` / `TimelineCanvas` 改为受控可选。
   - `openFilm`、recompose、jumpShot、pickUnit 的导航；关闭画布的语义；不能开画布时的规范化。
5. **拦截、标题与收尾**：`useBlocker`（读 ref，`force` 放行），去掉重复的 `confirmLeave`；关掉登录框后不再弹出；`document.title`；`openLocal` 的 `navigate('/')`。
6. **测试与文档**：`tests/routing.test.tsx`；README 部署说明。

## 14. 风险

- **App.tsx 改动面大**（886 行，导航与加载交织）：按 §13 分步，每步行为都能验证。加载逻辑原样搬进 effect，不顺手重构。
- **双重确认或漏确认**：blocker 与残留的 `confirmLeave` 并存会问两次，漏掉会丢修改。第 2 到 4 步保留旧确认、第 5 步一次性切换，由 §12.3 第 7 条覆盖。
- **自动跟步写 URL 造成循环**：URL → 步骤 → 跟步 → 写 URL。只在步骤真的前进时写、用 replace，写入值等于当前值时不导航。
- **加载竞态**：快速连点章节、连按后退时，迟到的响应会覆盖新位置。靠 §5.3 的守卫，以及先 `clearWork` 加骨架。
- **StrictMode 双调用**：加载 effect 必须可重入（用取消标记），避免开发模式下重复附着任务，或重复消费 `state` 导致 replace 两次。
- **助手桥接**：`requestStep` / `cancelStep` 现在靠「先登记再打开」。改成导航后要保持登记与挂载的先后；桥接保留，只把 `openChapter` 换成 `navigate`。
- **管理后台语义变化**：进后台会丢工作区内存（§6）。由 blocker 兜底未保存的修改，其余靠重新加载。
- **没有地址的场景**：本地 JSON、分批预览、不挂在章节上的任务面板，都留在 `/`，刷新会丢，与现在一致，本次不处理。
- **部署忘配 fallback**：深链接会直接 404。在 README 和上线检查里写明。

## 审查修订记录（Fable 设计审查，2026-11-12）

| 编号 | 问题 | 处理 |
|---|---|---|
| C1 | 同址再打开失效 | 新增 §5.4：目标地址等于当前地址时不导航，直接 attach / openVersion / clearWork；`state.vid` / `jobId` 定为跨地址导航的一次性参数，消费后 replace 清掉 |
| C2 | 画布路径丢步骤 | 选 `/chapters/:cid/:step/canvas`（step ∈ review / render / compose），保留 `?tab=`。理由：画布只挂在这三步，用路径子段能还原底下的步骤与页签，关闭时去掉一段即可；`?canvas=1` 表达不了这个约束。无版本、doc 为空、分批预览时规范化回章节地址；关闭回原步骤与页签（§3、§8） |
| C3 | 无步骤语义 | 新增 §4.2：无步骤段时步骤是组件内状态，沿用初值 cur、只往前跟、有未保存修改时不跟，不写 URL；有步骤段时等同助手 asked，首次落地优先于 followCur。补全 goto、openFilm、fix、recompose、onEditSource、两个空态按钮、助手跳步、自动跟步的 push / replace |
| I1 | blocker 拦程序性跳转 | §7：blocker 读 ref；退出、过期、删除后跳转、失败回退、规范化、openLocal 都带 `state.force` 放行；写明着陆页分支没有 confirmUi 且不会处于 dirty，退出本来就不确认 |
| I2 | 管理后台 | §6 采纳裁定：进入 `/admin` 即离开工作区，有未保存修改时由 blocker 确认，后退回章节重新加载；在 spec 里明示这是语义变化，风险列入 §14 |
| I3 | 迟到的 setNovel | §5.3：用 `openNovelId` 守卫覆盖 reloadOpen、importChapters、newChapter、submitNovel 和加载 effect；§5.1 规定 (nid, cid) 变化时先 clearWork；新增 §5.2 写明加载途中显示骨架、不渲染旧内容 |
| I4 | state 残留 | §5.4：消费后 replace 清掉；§8：所有 replace 透传 `location.state`，保留 `fromChapter` |
| I5 | jumpShot / pickUnit | §4.3：jumpShot 一次 replace 到 `/:step?tab=focus`，pickUnit replace 到 `?tab=source`，都列入入口表 |
| I6 | 实施顺序 | §13：第 2 步就做「未登录不加载、过期保留 URL」（保证 flow.test 12b）；第 2 到 4 步保留入口处的 confirmLeave（保证 flow.test 8b），第 5 步统一换成 blocker |
| Minor | 版本与入口 | §2 改为 react-router@8.5.1（只有 ESM，Node ≥ 22.22，peer react ≥ 19.2.7，本机满足），写明 `RouterProvider` 取自 `react-router/dom` |
| Minor | REPLACE 断言 | §12.3 用 `router.state.historyAction === 'REPLACE'` 断言 replace |
| Minor | 测试驱动导航 | §12.1：`AppRoot` 接收 router 实例，测试可以 `router.navigate` |
| Minor | 组件测试 | §4.1：ChapterWorkflow 步骤改为受控可选，workflow-ui.test、flow.test 直接渲染照常 |
| Minor | 登录框反复弹 | §6：未登录深链接关掉登录框后停在着陆页，不重复弹 |
| Minor | openLocal | §5.5：在章节内调用时先 `navigate('/')`（带 force） |
| 已决 | 开放问题 | 版本号不进 URL、管理后台页签不进 URL，记入 §1 与 §3 |
