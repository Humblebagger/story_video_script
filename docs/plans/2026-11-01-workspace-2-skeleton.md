# 工作台改版 2：工作台骨架 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 打开一部小说后，界面改成专业工作台：
- **顶栏**：项目切换器、章节切换、步骤条、费用表、任务铃铛。
- **左栏**：这部小说的项目导航（带数量）和章节进度卡片。
- **主区**：默认是小说概览页。
- **右侧**：可收起的动态面板。
- **后端**：加一个只读汇总接口，供费用和进度使用。

**Architecture:**
- **后端**：在 `server/app.py` 加 `GET /novels/{nid}/summary`，汇总逻辑放进新模块 `server/summary.py`，可单测。
- **前端汇总数据**：`useNovelSummary(nid)` 拉取汇总；纯函数 `chapterStage()` 用汇总推算每章停在哪一步。
- **左栏切换**：`AppShell` 的左栏插槽按状态切换。没打开小说时是 `NovelSidebar`（书架列表）；打开后是新的 `ProjectNav`。
- **小说页**：「小说页」的内容由 App 持有的 `section` 状态决定，原来的页签条去掉，改由左栏导航切换。
- **步骤条上移**：步骤条用 React portal 渲染进顶栏中间的插槽，状态仍归 `ChapterWorkflow`，逻辑不动。
- **动态面板**：数据来自现有的 `running` 任务列表和任务结果，不加后端接口。

**Tech Stack:** FastAPI（Python 3.12）、React 19、TS 6、Tailwind v4、shadcn（Radix）、motion、lucide-react、happy-dom。

**Spec:** `docs/specs/2026-11-01-workspace-redesign-design.md` 第 2、3、4、6、7、9、10 节，第 11 节第 2 条，第 13 节。

---

## 全局约束

- **提交**：只 `git add` 具体文件，不用 `git add -A` / `git commit -a`。提交信息用中文、写成描述式，**不带任何 Claude 署名**（不要 `Co-Authored-By`、不要 `Claude-Session`）。
- **前端检查**（在 `frontend/` 下执行），每个任务结束都要过：
  - `npm test`：14 套全部 `ALL PASS`。
  - `npm run lint`：0 error，warning 不超过 5 个。
  - `npx vite build`：成功。
- **后端检查**（在 `backend/` 下执行）：`.venv/bin/python tests/server/test_summary.py` 通过；`tests/server/test_novels.py`、`test_usage.py`、`test_render.py` 照常通过。
- **逻辑不变**：
  - 不改现有接口的行为。
  - 不改 `workflow.ts` 里 `currentStep` / `stepStates` 的判定。
  - 不改 `useChapterFlow`、`useFilm`、`useCompose`、`useJob`、`api.ts` 已有函数的行为（只新增 `getNovelSummary`）。
- **双语**：
  - 所有新文字进 `zh.ts`，`en.ts` 同步，键结构一致。
  - 源码里注释以外不许有中文（foundation 测试会全量扫描）。
  - 测试固定用中文。
- **样式**：
  - 只用新设计变量；样式表里用到的变量必须有定义，foundation 测试会检查。
  - 需要类名的样式放进新文件 `src/styles/workspace.css`，在 `app.css` 里按 `layer(components)` 引入，位置放在其他 components 引入之后。
  - 等宽字体（`font-mono tabular-nums`）用于这些地方：编号、时长、金额、字数、镜头数。
  - 状态统一用 `StatusPill`（`src/components/common/StatusPill.tsx`）。
- **动效**：沿用 `useMotionPresets()`。动态面板从右侧滑入，时长 240ms；进度细线的宽度变化过渡 300ms。系统开了「减少动态效果」时不位移。
- **测试钩子**：
  - 保留现有测试用到的类名和 `data-testid`。`grep -ohE "querySelector(All)?\('[^']+'\)" tests/*.tsx` 可以复查。
  - 左栏从小说列表换成项目导航之后，`flow.test` 里「在侧栏找小说、找章节」的步骤要改成新的入口：项目切换器，以及 `ProjectNav` 里的章节卡片。
- **不碰**：`docs/specs/2026-10-27-commercialization-design-contract.md`，不读 `backend/.env`。

## 实施裁定

1. **汇总接口的字段**：规格第 9 节写的是 `film_cny` / `tts_cny` 分开，但出片会话只有一个合计的 `spent_cny`（出片和配音都记在里面）。所以接口字段改为：

   ```json
   { "cost": { "llm_usd": 0.4, "render_cny": 3.66, "budget_cny": 40.0 },
     "chapters": [ { "id": "c1", "version": "v…", "shots": 45, "duration_s": 285.0,
                     "film": { "done": 9, "total": 9, "failed": 0, "running": 0 },
                     "final": "fresh",
                     "cost": { "llm_usd": 0.12, "render_cny": 1.2, "budget_cny": 20.0 } } ] }
   ```

   - `final` 取值 `none`、`busy`、`fresh`、`stale`。`stale` 来自会话里已存的状态，**不重算指纹**（重算太重），所以可能滞后，打开那一章时才会刷新。
   - `version` 选章节当前看的版本：有采用版用采用版，否则用最新一个成功的版本，都没有就是 `null`。
   - `duration_s` 按 `render.compose.playable` 逐镜求和，与画布的「可播时长」一致。读不到就是 `null`。
   - `llm_usd` 用 `pricing.cost` 按用量记录里的 `novel_id` 和章节字段汇总；用量记录里没有章节字段时，章节级的 `llm_usd` 为 `null`。写之前先看 `usage.record` 的字段。
2. **左栏章节卡片停在哪一步**：用纯函数 `chapterStage(ch: ChapterSummary, s: ChapterSum | undefined, converting: boolean): StepId` 推算，和 `currentStep` 的顺序一致：
   1. 没有原文（`chars === 0`）→ `import`。
   2. 生成中，或没有成功的版本 → `storyboard`。
   3. 版本状态是 `draft_invalid` → `review`。左栏看不到「未保存」，这一项当作已通过。
   4. 没有出片会话，或 `film.done < film.total` → `render`。
   5. `final` 不是 `fresh` → `compose`。
   6. 其余 → `download`。

   打开章节后，顶栏步骤条仍用精确的 `currentStep`。左栏只是概览，两者短暂不一致可以接受。
3. **步骤条上移**：
   - `AppShell` 在顶栏中间放一个空的 `<div id="topbar-center">`，用 `TopbarSlotContext` 把这个元素提供出去。
   - `ChapterWorkflow` 用 `createPortal(<Stepper …/>, slot)` 把步骤条渲染进去；拿不到插槽时（例如单测）在原位渲染。
   - 原来章节页顶部那一条去掉。
4. **小说页分区**：
   - App 新增状态 `section: Section`，取值 `'overview' | 'chapters' | 'characters' | 'locations' | 'props' | 'creatures' | 'memory' | 'constraints' | 'settings'`，打开小说时默认 `'overview'`。
   - `NovelPage` 改为按 `section` 渲染对应内容，不再自带页签条：
     - `memory`：主线剧情、章节摘要和人物状态上下排在一页（原来的「剧情」「人物状态」两个页签）。
     - `characters` / `locations` / `props` / `creatures`：渲染 `NovelAssets`，传入 `kind`，只显示这一类卡片。
     - `chapters`：渲染「原文与章节」页（见 Task 5）。
     - `settings`：沿用子计划 1 的设置页。
   - 有人物状态待确认时，打开小说默认停在 `memory`，沿用原来跳到人物状态页签的行为。
5. **项目切换器**：
   - 用 shadcn `DropdownMenu`：顶部一个搜索框（`Input`，`onKeyDown` 时 `stopPropagation`，免得菜单的打字定位抢走输入），中间是最近 8 部小说，底部「＋ 新建小说」（回到书架）和「全部小说」（回到书架）。
   - 没打开小说时，顶栏左侧只显示产品名，不显示切换器。
6. **侧栏收起**：沿用 `AppShell` 现有的收起逻辑。收起时 `ProjectNav` 只显示图标和章节编号方块，名字放进 `Tooltip`。
7. **费用表的数据**：
   - 小说层显示 `cost.llm_usd` 和 `cost.render_cny`，按「¥3.66 · $0.40」的格式；章节层显示该章的同名字段。
   - 点开浮层（`Popover`）看三行：大模型（美元）、出片与配音（人民币）、上限。
   - 汇总接口失败或还在读时显示「—」，不报错。
   - 只在打开小说时显示费用表。
8. **动态面板**：
   - 状态 `activityOpen` 放在 App，铃铛切换开关。面板宽 320px，在主区右侧，挤压主区而不是盖在上面；窄屏（<1100px）时改成盖在主区上方的抽屉。
   - 「在跑」用 App 现有的 `running` 列表；「最近完成」在 App 里记下 `running` 中消失的任务（任务结束后再调一次 `getJob` 拿状态），最多 20 条，只存在内存。
   - 点「查看」走 App 现有的 `openJob`。

## 文件结构

| 文件 | 职责 |
|---|---|
| `backend/server/summary.py` | 新建：小说汇总（花费、各章镜头、时长、出片、成片状态） |
| `backend/server/app.py` | 修改：`GET /novels/{nid}/summary` |
| `backend/tests/server/test_summary.py` | 新建 |
| `frontend/src/api.ts`、`types.ts` | 修改：`getNovelSummary`、`NovelSummaryData` / `ChapterSum` 类型 |
| `frontend/src/useNovelSummary.ts` | 新建：拉取与刷新（打开小说、任务结束、出片或合成后） |
| `frontend/src/workflow.ts` | 修改：新增纯函数 `chapterStage` |
| `frontend/src/components/shell/AppShell.tsx` | 修改：顶栏三段式、插槽 Context、右侧面板插槽 |
| `frontend/src/components/shell/ProjectSwitcher.tsx` | 新建 |
| `frontend/src/components/shell/CostMeter.tsx` | 新建 |
| `frontend/src/components/shell/ActivityPanel.tsx` | 新建 |
| `frontend/src/components/shell/ProjectNav.tsx` | 新建：项目导航与章节卡片 |
| `frontend/src/components/NovelOverview.tsx` | 新建：概览页 |
| `frontend/src/components/ChaptersPage.tsx` | 新建：原文与章节页 |
| `frontend/src/components/NovelPage.tsx` | 修改：按 `section` 渲染，去掉页签条与章节网格 |
| `frontend/src/components/NovelAssets.tsx` | 修改：支持 `kind` 过滤 |
| `frontend/src/components/workflow/ChapterWorkflow.tsx` | 修改：步骤条 portal |
| `frontend/src/App.tsx` | 修改：`section`、`activityOpen`、最近完成、左栏切换、传汇总 |
| `frontend/src/styles/workspace.css`、`app.css`、`i18n/zh.ts`、`en.ts` | 新建、修改 |
| `frontend/tests/workspace.test.tsx`、`package.json` | 新建一套测试（第 15 套）并加进 `npm test` |
| `frontend/tests/flow.test.tsx`、`foundation.test.tsx` | 修改：入口变化同步 |

---

### Task 1: 后端汇总接口

**Files:** Create `backend/server/summary.py`、`backend/tests/server/test_summary.py`；Modify `backend/server/app.py`

- [ ] **Step 1: 先写测试**。`test_summary.py` 的结构照抄 `tests/server/test_novels.py` 开头（临时数据目录、`U` 用户、`batch_doc`），场景如下：
  1. 新建一部小说、两章：第一章有一个成功版本并采用；第二章只有原文。
     - `summary.novel_summary(U, nid)` 返回 2 个章节。
     - 第一章的 `shots` 等于文档里镜头数之和，`version` 是采用版。
     - 第二章 `version is None`，`shots is None`，`film is None`，`final == "none"`。
  2. 给第一章的采用版写一个出片会话：直接用 `render.session` 的 `_save`，或者调 `session.build` 生成会话，再改 `spent_cny = 1.2`，3 个段中 2 个 `done`。
     - 第一章 `film == {"done": 2, "total": 3, "failed": 0, "running": 0}`。
     - `cost.render_cny == 1.2`，总计也是 1.2。
  3. 在用量文件里写两条记录（`usage.record`）：`novel_id=nid`，再加一条别的小说的。
     - `cost.llm_usd` 只计这部小说的那条，按当前价格表；价格表没有这个模型时为 `0`，并在 `unpriced` 字段里列出模型名。
  4. 会话里 `final = {"state": "done", …}` 时，`final == "fresh"`；状态为 `queued` 或 `running` 时为 `"busy"`。打开 `render/session.py` 的 `finish_compose`，看成片过期时会话里留下什么标记，按它映射成 `"stale"`，没有这种标记就不出现 `stale`。
  5. 别的用户读这部小说：抛 `novels` 模块现有的「找不到」异常。接口层翻成 404，与其他小说接口一致。

- [ ] **Step 2:** 运行，预期 `ModuleNotFoundError: server.summary`。

- [ ] **Step 3: 实现 `summary.py`**：
  - **`novel_summary(user_id, nid) -> dict`**：
    - 读小说和各章：用 `novels` 模块的公开函数，或同包内的 `_chapters` / `_load_chapter`。
    - 各章按「实施裁定 1」选版本。
    - 读版本文档：用 `novels.get_version`。
    - 算 `shots` 和 `duration_s`：遍历 `episodes[].shots[]`，`duration_s` 用 `render.compose.playable(shot)` 求和。
    - 读出片会话：用 `novels.render_dir` 加 `render.session.load`。读到损坏文件（`Corrupt`）时当作没有。
    - `film` 按段的 `state` 计数：
      - `done`：等于 `done`。
      - `failed`：等于 `failed`。
      - `running`：属于 `IN_FLIGHT`（看 `render/session.py` 里的常量）。
      - `total`：段数。
  - **`render_cny` / `budget_cny`**：取自会话的 `spent_cny` / `budget_cny`，没有会话时为 `None`；小说层对非 `None` 的值求和，全是 `None` 时为 `None`。
  - **`llm_usd`**：
    - 用 `usage.read(user_id=user_id)` 过滤出 `novel_id == nid` 的记录，再用 `pricing.cost(row, pricing.load())` 求和，`None` 当 0。
    - 这些记录里有价格表没有的模型时，把模型名列进返回的 `unpriced: [...]`。
    - 章节级：用量记录有章节字段时按章汇总，没有就是 `None`（实施裁定 1）。

- [ ] **Step 4: 接口**。在 `app.py` 的小说接口段落里（`novels_get` 附近）加：

```python
@app.get("/novels/{nid}/summary")
def novels_summary(nid: str, user: dict = Depends(novel_user)):
    """概览、费用表、左栏章节卡片用：花费与各章进度汇总（只读，读会话不重算指纹）。"""
    return _novel_call(summary.novel_summary, user["id"], nid)
```

  文件顶部用 `from server import summary`，导入写法与 `novels` 一致。

- [ ] **Step 5:** 跑 `test_summary.py`，以及 `test_novels.py`、`test_usage.py`、`test_render.py`，全部通过。

- [ ] **Step 6: 提交**

```bash
git add backend/server/summary.py backend/server/app.py backend/tests/server/test_summary.py
git commit -m "新增小说汇总接口：各章当前版本的镜头数、可播时长、出片段计数与成片状态，小说与各章的大模型花费和出片配音已花、上限（只读，不重算指纹）"
```

---

### Task 2: 前端汇总数据与 `chapterStage`

**Files:**
- Modify: `frontend/src/api.ts`（`getNovelSummary(nid)`，写法同 `getNovel`）、`frontend/src/types.ts`（`NovelSummaryData`、`ChapterSum`，字段与实施裁定 1 的 JSON 一致，加 `unpriced: string[]`）
- Create: `frontend/src/useNovelSummary.ts`
- Modify: `frontend/src/workflow.ts`（`chapterStage`）
- Create: `frontend/tests/workspace.test.tsx`；Modify: `frontend/package.json`（`test` 脚本末尾追加这一套）

- [ ] **Step 1: 先写失败测试**（`workspace.test.tsx` 第一段）。结构照抄 `tests/workflow.test.ts`，用纯函数断言 `chapterStage` 的 6 种结果，以及「生成中」优先于其他情况：

```ts
const ch = (o: Partial<ChapterSummary> = {}): ChapterSummary => ({
  id: 'c1', title: '第一章', order: 1, adopted_version: null, legacy_numbering: false,
  chars: 100, versions: [], latest_status: null, digest: null, ...o })
const ok = { id: 'v1', status: 'succeeded', created_at: null, shots: 3 } as VersionSummary
const sum = (o: Partial<ChapterSum> = {}): ChapterSum => ({
  id: 'c1', version: 'v1', shots: 3, duration_s: 30,
  film: { done: 3, total: 3, failed: 0, running: 0 }, final: 'fresh', cost: null, ...o })
must(chapterStage(ch({ chars: 0 }), undefined, false) === 'import', '没原文')
must(chapterStage(ch(), undefined, false) === 'storyboard', '没版本')
must(chapterStage(ch({ versions: [ok] }), sum(), true) === 'storyboard', '生成中')
must(chapterStage(ch({ versions: [{ ...ok, status: 'draft_invalid' }] }), sum(), false) === 'review', '检查没过')
must(chapterStage(ch({ versions: [ok] }), sum({ film: null }), false) === 'render', '没出片会话')
must(chapterStage(ch({ versions: [ok] }), sum({ film: { done: 1, total: 3, failed: 0, running: 0 } }), false) === 'render', '还有段')
must(chapterStage(ch({ versions: [ok] }), sum({ final: 'stale' }), false) === 'compose', '成片过期')
must(chapterStage(ch({ versions: [ok] }), sum(), false) === 'download', '都完成')
```

  `VersionSummary` 实际的字段以 `types.ts` 为准，按实际字段构造。

- [ ] **Step 2: 实现**：
  - `chapterStage` 的版本选择与后端一致：先找采用版，否则取最新一个成功的版本（`succeeded` 或 `completed_with_warnings`），以 `ADOPTABLE` 或现有判定为准。
  - `useNovelSummary(nid, refreshKey)`：返回 `{ data, reload }`。`nid` 或 `refreshKey` 变化时重新拉取；失败时 `data` 保持 `null`，不报错。
- [ ] **Step 3:** 测试全过，三项检查全过。
- [ ] **Step 4: 提交**

```bash
git commit -m "前端接入小说汇总：接口与类型、useNovelSummary、按汇总推算章节所在步骤的纯函数 chapterStage；新增 workspace 测试套件"
```

---

### Task 3: 顶栏（项目切换器、步骤条上移、费用表、铃铛）

**Files:**
- Create: `src/components/shell/ProjectSwitcher.tsx`、`CostMeter.tsx`
- Modify: `src/components/shell/AppShell.tsx`、`src/components/workflow/ChapterWorkflow.tsx`、`src/App.tsx`、`src/i18n/zh.ts`、`en.ts`、`src/styles/workspace.css`、`src/styles/app.css`
- Test: `tests/workspace.test.tsx`、`tests/foundation.test.tsx`（外壳断言）、`tests/flow.test.tsx`、`tests/workflow-ui.test.tsx`（步骤条位置）

- [ ] **Step 1: 先写失败测试**（`workspace.test.tsx` 第二段，直接渲染组件）：
  - **ProjectSwitcher**：传入 3 部小说、当前是「药」，触发按钮显示「药」和小字「9:16 · 写实」。打开后：
    - 有 3 个小说项、一个搜索框和「＋ 新建小说」。
    - 搜索「洪」只剩 1 项。
    - 点某一项调用 `onOpen(id)`，点「＋ 新建小说」调用 `onNew()`。
  - **CostMeter**：
    - 汇总里有 `{ llm_usd: 0.4, render_cny: 3.66, budget_cny: 40 }` 时，文字是「¥3.66 · $0.40」。
    - `data` 为 `null` 时显示「—」。
    - 打开浮层后有三行明细。
  - **AppShell**：渲染时传入 `topCenter` 插槽的消费者，断言 `#topbar-center` 存在；在 `TopbarSlotContext` 里用 portal 渲染的内容出现在顶栏里。
- [ ] **Step 2: 实现**：
  - **AppShell 顶栏**：高 56px，三段式（`grid-cols-[1fr_auto_1fr]`）。
    - 左：侧栏开关、标志、`projectSwitcher` 插槽（App 传入；没打开小说时为空，显示产品名）、`chapterCrumb` 插槽。
    - 中：`#topbar-center`。
    - 右：`costMeter` 插槽、铃铛按钮（`Bell` 图标加计数徽标，数字等于在跑任务数，0 时不显示徽标，点了调 `onToggleActivity`）、语言、主题、账号菜单。
    - **账号菜单**是新的 `DropdownMenu`：用户名、当前模型（原来顶栏的模型徽章挪到这里）、服务状态、管理后台（仅管理员）、退出。
    - 测试依赖的「管理」「退出」按钮文字，保留在菜单项里，或者保留在侧栏底部，看现有测试怎么找。
    - 服务连不上时，铃铛左边显示红色 `StatusPill tone="err"`（「服务未连通」）。
  - **章节切换（`chapterCrumb`）**：在章节里时显示「/ 第三章 ▾」，下拉是本小说的章节列表，点了调 `openChapter`。
  - **ChapterWorkflow**：步骤条按实施裁定 3 portal 到顶栏中间。顶栏宽度不够（<900px）时，`Stepper` 显示紧凑形态（只有当前步「③ 检查修改 ▾」，下拉选步骤）；`Stepper` 已经支持就沿用，不支持就加一个 `compact` 属性。
  - **App**：把 `projectSwitcher`、`chapterCrumb`、`costMeter`、`onToggleActivity`、`runningCount` 传给 `AppShell`。`useNovelSummary(novel?.id, summaryKey)` 的 `summaryKey` 在以下时机加一：任务结束、`ChapterWorkflow` 的出片或合成刷新（`useChapterFlow.reload`）、采用版本、删除版本。
- [ ] **Step 3:** 测试全过（flow、foundation、workflow-ui 里涉及顶栏、步骤条位置的断言同步改），三项检查全过。
- [ ] **Step 4: 提交**

```bash
git commit -m "顶栏改成工作台三段式：项目切换器（搜索、最近、新建）、章节切换、步骤条移到顶栏中间、费用表浮层明细、任务铃铛与计数、账号菜单收纳模型与服务状态"
```

---

### Task 4: 左栏项目导航 `ProjectNav` 与小说页分区

**Files:**
- Create: `src/components/shell/ProjectNav.tsx`
- Modify: `src/App.tsx`（`section` 状态；打开小说时左栏用 `ProjectNav`，否则用 `NovelSidebar`）、`src/components/NovelPage.tsx`（按 `section` 渲染，去掉页签条和章节网格页签）、`src/components/NovelAssets.tsx`（`kind?: AssetKind`）、`src/i18n/zh.ts`、`en.ts`、`src/styles/workspace.css`
- Test: `tests/workspace.test.tsx`、`tests/flow.test.tsx`

- [ ] **Step 1: 先写失败测试**（`workspace.test.tsx` 第三段，直接渲染 `ProjectNav`）：
  - **导航项**：共 9 个导航项（概览、原文与章节、角色、场景、道具、生物、剧情与记忆、创作限制、设置）。
    - 资产数量取自 `novel.memory.assets` 各类的长度。
    - 数量为 0 的项带 `data-empty`，但仍可点。
    - 有 2 条待确认的人物状态时，「剧情与记忆」上有提示点 `[data-testid="nav-badge"]`。
  - **点导航项**：调用 `onSection('characters')`，当前项带 `aria-current="page"`。
  - **章节卡片**：每章一张卡片 `[data-testid="chapter-card"]`，内容是编号「01」、标题、`chapterStage` 对应的步骤名，以及进度细线。
    - 进度细线的宽度：完成步数 ÷ 6。`download` 算 6/6，`render` 算 3/6，以此类推。
    - 当前章节带 `aria-current`。
    - 生成中的章节有 `[data-tone="live"]`。
    - 点卡片调用 `onOpenChapter(id)`。
  - **新章节与搜索**：章节标题旁的「＋」调用 `onNewChapter()`。章节超过 8 个时出现搜索框，输入后过滤。
- [ ] **Step 2: 实现**：
  - **ProjectNav 布局**：
    - 上半是导航项，每项是图标、名字，右边是等宽的数量。图标：概览 `LayoutDashboard`、原文与章节 `BookText`、角色 `Users`、场景 `MapPin`、道具 `Package`、生物 `PawPrint`、剧情与记忆 `ScrollText`、创作限制 `ShieldAlert`、设置 `Settings2`。
    - 当前项用 `--ui-accent` 底，左边加 `--primary` 竖条。
    - 下半是章节卡片列表：编号方块用等宽字，状态行用 `StatusPill` 或辅助色小字，加时长，底部 2px 进度细线，宽度过渡 300ms。
    - 收起态见实施裁定 6。
  - **NovelPage**：
    - 删掉页签条和 `ChaptersTab`。
    - 按 `section` 渲染，见实施裁定 4；`chapters` 分区在 Task 5 之前先渲染一个占位，Task 5 替换掉。
    - 每个分区顶部有统一的标题行：分区名，右边放这个分区的主操作。例如资产分区是「＋ 新卡片」，沿用 `NovelAssets` 里的新建入口。
  - **NovelAssets**：传入 `kind` 时只显示这一类，新建卡片时默认就是这一类，隐藏分类选择。
  - **App**：
    - 打开小说时，`section` 默认是 `'overview'`；有人物状态待确认时，默认是 `'memory'`。
    - 打开章节时，左栏仍是 `ProjectNav`，高亮当前章节，主区是 `ChapterWorkflow`。
    - 在章节里点导航项，会离开章节（未保存时走 `confirmLeave`），回到小说层的那个分区。
- [ ] **Step 3:** `flow.test` 改入口：原来点侧栏小说标题的地方，改为在书架卡片（`[data-testid="shelf-card"]`）或项目切换器里打开；原来点侧栏章节的地方，改为点 `[data-testid="chapter-card"]`。测试全过，三项检查全过。
- [ ] **Step 4: 提交**

```bash
git commit -m "打开小说后左栏改成项目导航：概览、原文与章节、角色场景道具生物、剧情与记忆、创作限制、设置（带数量与待确认提示）和章节进度卡片；小说页改按分区渲染，资产按类别分页，去掉页签条与章节网格"
```

---

### Task 5: 概览页 `NovelOverview` 与「原文与章节」页

**Files:**
- Create: `src/components/NovelOverview.tsx`、`src/components/ChaptersPage.tsx`
- Modify: `src/components/NovelPage.tsx`（`overview`、`chapters` 分区接上）、`src/App.tsx`（「继续」用到的最近章节）、`src/i18n/zh.ts`、`en.ts`、`src/styles/workspace.css`
- Test: `tests/workspace.test.tsx`

- [ ] **Step 1: 先写失败测试**（第四段，直接渲染 `NovelOverview`，构造 novel 和 summary）：
  - 标题、参数小字（「9:16 · 写实 · 择要旁白 · 男声·沉稳」），以及更多菜单里的「删除小说」。删除仍走 `useConfirm`。
  - 6 张数字卡 `[data-testid="stat"]`：章节、已采用、镜头（各章 `shots` 求和，`null` 不计）、资产卡（四类之和）、已成片（`final === 'fresh'` 的章数，写成「1/6」）、累计花费（「¥3.66 · $0.40」）。
  - 「继续」按钮写「继续：第三章 · 检查修改」，点了调用 `onOpenChapter('c3')`。
    - 选哪一章：优先 `lastChapterId`（App 记住的最近打开的章节，本机 `localStorage` 按小说存，读写包 try/catch）。
    - 没有记录时，取第一个还没到 `download` 的章节。
    - 全部完成时，按钮写「全部完成」，并且不能点。
  - 故事梗概：显示 `plot.outline` 的前 4 行；为空时显示「还没有主线剧情」加「去填写」按钮，点了调用 `onSection('memory')`。
  - 主要人物：按出场章节数取前 5 个角色。出场章节数从各章的 `plot.chapters` 摘要或资产卡上的出处字段算，以 `types.ts` 里实际有的字段为准；都没有就按资产卡顺序取前 5 个，并在报告里说明。
    - 头像：有参考图就显示（参考图读取方式以 `ReferenceImage` 字段为准，读不到就用首字），否则用首字圆头像。
  - 章节进度：每章一行 `[data-testid="progress-row"]`，6 个小格（完成、当前、未到三种样式）、步骤名、时长（等宽）；点一行调用 `onOpenChapter`。
  - 待处理：有待确认的人物状态时，显示「2 条人物状态待确认 → 去确认」；有 `final === 'stale'` 的章节时，显示「第一章的成片内容改过，需要重新合成 → 去处理」。
  - **ChaptersPage**：章节列表是表格式的行（编号、标题、字数、版本数、步骤、操作），带「＋ 新章节」和「导入整本 .txt」。导入走 `NewNovelComposer` 同样的 `parseChapters` 拆分，再逐章 `createChapter`（App 里新增 `importChapters(chapters)`，复用 `submitNovel` 里建章的那段循环）。测试断言行数，以及点「＋ 新章节」触发回调。
- [ ] **Step 2: 实现**：
  - **布局**：最宽 1080px。
    - **页头**：大标题（24px、600）、参数小字，右边是「继续」主按钮和更多菜单。
    - **数字卡**：`grid-cols-2 md:grid-cols-3 xl:grid-cols-6`，数字用等宽字 22px。
    - **梗概和人物**：两栏，`lg:grid-cols-[2fr_1fr]`。
    - **章节进度**：放在卡片里。
    - **待处理**：放在 `--warning` 左竖条的提示条里。
    - 进场依次淡入，用 `m.item(i)`。
  - **删除小说**：从原 `NovelPage` 的标题区搬过来，保留 `DropdownMenu modal={false}`，并用 `setTimeout` 延后打开确认框。
- [ ] **Step 3:** 测试全过，三项检查全过。
- [ ] **Step 4: 提交**

```bash
git commit -m "小说概览页：继续按钮直达最近章节的当前步骤、六张数字卡、故事梗概与主要人物、章节进度六格、待处理事项；原文与章节页：章节表格、新章节与导入整本"
```

---

### Task 6: 右侧动态面板 `ActivityPanel`

**Files:**
- Create: `src/components/shell/ActivityPanel.tsx`
- Modify: `src/components/shell/AppShell.tsx`（右侧面板插槽、开关、窄屏抽屉）、`src/App.tsx`（`activityOpen`、`recentDone`）、`src/i18n/zh.ts`、`en.ts`、`src/styles/workspace.css`
- Test: `tests/workspace.test.tsx`

- [ ] **Step 1: 先写失败测试**（第五段，直接渲染 `ActivityPanel`）：
  - **在跑**：传入 2 个在跑任务，有 2 个 `[data-testid="activity-running"]`。每项显示「小说名 · 章节」、进度条（`JobProgress` 或 `Progress`）、剩余时间（`fmtEta`）、最后一行日志（等宽字），以及「查看」按钮，点了调用 `onOpen(job)`。
  - **最近完成**：传入 3 条，有 3 个 `[data-testid="activity-done"]`，状态用 `StatusPill`：成功 `ok`、告警 `warn`、失败 `err`。
  - **空状态**：两边都空时，显示 `EmptyState`「没有在跑的任务」。
  - **预留**：顶部的页签只有「任务」一个，作为 Agent 预留位，不做第二个页签。
  - **关闭**：「关闭」按钮调用 `onClose()`；按 Esc 也关闭（面板获得焦点时）。
- [ ] **Step 2: 实现**：
  - **面板**：用 `motion.aside` 从右侧滑入，持续 240ms；减少动态效果时只淡入。
  - **App 记录最近完成**：在 `watchJobs` 里比较前后两次 `running`，消失的任务调一次 `getJob` 拿最终状态，放进 `recentDone` 最前面，最多保留 20 条。
  - **铃铛计数**：等于 `running.length`。有新完成的任务、而面板没开时，铃铛上加一个小圆点，打开面板后清掉。
- [ ] **Step 3:** 测试全过，三项检查全过。
- [ ] **Step 4: 提交**

```bash
git commit -m "右侧动态面板：在跑任务的进度、剩余时间与最新日志，最近完成的结果（成功、告警、失败），铃铛计数与新完成提示，窄屏改抽屉"
```

---

## 自查记录

- **规格覆盖**：
  - 第 2 节（书架与工作台两种左栏）：Task 4。
  - 第 3 节（顶栏）：Task 3。
  - 第 4 节（项目导航）：Task 4。
  - 第 6 节（概览）：Task 5。
  - 第 7 节（动态面板）：Task 6。
  - 第 9 节（汇总接口）：Task 1、2。
  - 第 10 节（等宽字、`StatusPill`、进度线动效）：Task 3–6。
  - 第 13 节（项目导航、概览「继续」、动态面板、汇总接口的测试）：Task 1–6。
  - 章节网格页签取消：Task 4。
- **已知差异**：
  - 费用字段合并成 `render_cny`（实施裁定 1）。
  - `stale` 不重算，可能滞后（实施裁定 1）。
  - 左栏的步骤用汇总推算（实施裁定 2）。
- **类型一致**：
  - `ChapterSum`、`NovelSummaryData`、`chapterStage` 在 Task 2 定义，Task 3–5 使用。
  - `Section` 在 Task 4 定义，Task 5 使用。
  - `TopbarSlotContext` 在 Task 3 定义。
