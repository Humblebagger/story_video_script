# 工作台改版 3：章节工作台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 章节页改成专业工作台：
- **章节头部**：所有步骤共用，带预估、已花、上限三格金额。
- **「检查修改」默认视图**：新的「镜头」三栏视图（镜头列表、选中镜头的编辑、预览）。
- **导入原文、生成分镜、下载**：换成居中卡片版式。
- **画布**：顶部加一行精简的章节头部。
- **资产分区**：按类别显示缩略图网格。

**Architecture:**
- **纯函数**：可单测的逻辑全部放进新模块 `src/shotFocus.ts`（拍平镜头、按检查结果标镜头、找镜头所在片段、过滤、上下切换、景别色）和 `src/lib/assetThumb.ts`（资产卡缩略图来源）。
- **关键帧图**：新钩子 `useShotImages(version, reloadKey)` 只读已上传的关键帧图，不请求出图提示词。
- **三栏视图**：新组件 `ShotFocusView` 由 `StoryboardView` 渲染，成为第一个、也是默认的视图页签。原「分镜」卡片视图改名「卡片」，保留为第二项。
- **章节头部**：新组件 `ChapterHeader` 由 `ChapterWorkflow` 渲染。画布里的精简头部通过 React Context 送进 `TimelineCanvas`：分镜视图元素由 App 创建，但渲染在 `ChapterWorkflow` 的子树里，所以能读到它提供的 Context。
- **资产分区**：`NovelAssets` 在传了 `kind` 时改为「缩略图网格 ↔ 单卡编辑」两态。

**Tech Stack:** React 19、TS 6、Tailwind v4、shadcn（Radix）、motion、lucide-react、happy-dom。

**Spec:** `docs/specs/2026-11-01-workspace-redesign-design.md` 第 8 节、第 10 节，第 11 节第 3 条，第 13 节。

---

## 全局约束

- **提交**：
  - 只 `git add` 具体文件，不用 `git add -A` / `git commit -a`。
  - 提交信息用中文、写成描述式，**不带任何 Claude 署名**（不要 `Co-Authored-By`、不要 `Claude-Session`）。
- **前端检查**（在 `frontend/` 下执行），每个任务结束都要过：
  - `npm test`：全部套件 `ALL PASS`。现有 15 套，Task 1 起是 16 套。
  - `npm run lint`：0 error，warning 不超过 5 个。
  - `npx vite build`：成功。
- **不改后端**。
- **逻辑不变**：
  - 不改 `workflow.ts` 里 `currentStep`、`stepStates`、`primaryFor` 的判定。
  - 不改 `useChapterFlow`、`useFilm`、`useCompose`、`useKeyframes`、`useJob` 的行为。
  - 不改 `api.ts` 已有函数。
  - 编辑、保存、撤销仍走 `StoryboardView` 现有的 `onChange` / `onSave`，以及 `ChapterWorkflow` 的 `UnsavedBar`。
- **双语**：
  - 所有新文字进 `zh.ts`，`en.ts` 同步，键结构一致（类型会强制）。
  - 源码里注释以外不许有中文（foundation 测试会全量扫描）。
  - 测试固定用中文。
- **样式**：
  - 只用已有设计变量；样式表里用到的变量必须有定义（foundation 测试会检查）。
  - 需要类名的样式放进新文件 `src/styles/chapter.css`，在 `app.css` 里按 `layer(components)` 引入，放在 `workspace.css` 之后。
  - 编号、镜头 ID、时长、金额一律用 `font-mono tabular-nums`。
  - 状态显示用 `StatusPill`。
- **动效**：
  - 沿用 `useMotionPresets()`。
  - 三栏视图切换镜头时，中栏和右栏用 `m.enter` 淡入（`key` 设为镜头 ID）。
  - 系统开了「减少动态效果」时不位移。
- **测试钩子**：保留现有测试用到的类名和 `data-testid`（`grep -ohE "querySelector(All)?\('[^']+'\)" tests/*.tsx` 复查）。尤其是这几个：
  - `.shot`、`.shot .chip`、`.tabs__btn`、`.stats`、`.sb__head .stats`；
  - `[data-testid="primary-action"]`、`primary-reason`、`primary-fix`；
  - `.lib__search`、`.lib__add input`、`.lib__add select`；
  - `#storyboard-save`。
- **不碰**：`docs/specs/2026-10-27-commercialization-design-contract.md`，不读 `backend/.env`。

## 实施裁定

1. **视图页签**：
   - `StoryboardView` 的 `Tab` 改为 `'focus' | 'cards' | 'assets' | 'source' | 'render' | 'json'`。
   - 中文文案依次是「镜头 / 卡片 / 资产 / 原文 / 渲染 / JSON」，英文是 `Shots / Cards / Assets / Source / Render / JSON`。
   - 新增可选属性 `defaultTab?: Tab`，默认 `'focus'`。
   - 原 `'shots'` 视图（`EpisodeView` 列表）改名 `'cards'`，内容不变。
   - 从画布「跳回镜头」（`jumpShot`）改为切到 `'focus'` 并选中那一镜，不再滚动卡片列表。
2. **三栏视图里的编辑态**：
   - 中栏的 `ShotCard` 固定 `editing={!preview}`，不跟随 `StoryboardView` 顶部的「编辑」开关，因为这一栏本来就是编辑区。
   - 卡片视图仍跟随开关。
   - 分批预览（`preview`）时中栏只读。
3. **三栏视图要的额外数据**：`StoryboardView` 新增两个可选属性，都由 App 传：
   - `report?: VerificationReport | null`：App 现有的 `verification`，用来给镜头标红点。
   - `film?: FilmSession | null`：`flow.film`，用来在右栏切到成片段。
   - 两个都没有时，三栏视图照常可用，只是没有红点、没有成片段切换。
4. **红点规则**：
   - `Finding.object_path` 形如 `/episodes/<i>/shots/<j>/…` 时归到那一镜。
   - `critical`、`high` 级标红点（`data-issue="hard"`），其余级标黄点（`data-issue="soft"`）。
   - 同一镜既有硬问题又有软问题时按硬问题算。
   - 指不到镜头的检查结果不标。
5. **右栏预览**：
   - **关键帧**：有关键帧图就显示图，没有就显示景别色块，上面写镜头 ID。
   - **成片段**：只有当这一镜所在片段的采用那次尝试（`attempts[chosen]`）有 `file` 时，才出现「关键帧 / 成片段」分段切换。切到成片段时，用 `filmFileUrl` 取 blob URL 放进 `<video controls>`；换镜头或卸载时 revoke。
   - **原文句子**：`shot.source.unit_refs` 每一条用 `idx.unitText(id)` 显示，前面是等宽句子 ID。点一句调用现有的 `pickUnit`，跳到「原文」页签并定位。
   - **底部通栏主按钮**：
     - 有未保存修改（`dirty`）且 `canSave` 时写「保存修改」，调用 `onSave`，正在保存时禁用。
     - 否则写「在画布中查看」，打开画布（与顶部「画布」按钮同一个动作）。
6. **键盘**：
   - 焦点在左栏列表里时，上下键切换选中的镜头（跳过被折叠的集），`Home` / `End` 跳到首尾。
   - 列表用 `role="listbox"`，每项是 `role="option"`，带 `aria-selected`。
   - 焦点在输入框里时不拦截按键。
7. **窄屏**：
   - **小于 1100px**：右栏挪到中栏下方，纯 CSS 实现。
   - **小于 760px**：用 `useMedia('(max-width: 759px)')` 判断。只显示列表，点一项进入「编辑」态，只显示中栏和右栏，顶部有「← 镜头列表」返回。
8. **章节头部的数字**：
   - **编号**：`EP·03` 的编号是这一章在 `novel.chapters` 里的序号加一，补齐两位，与左栏章节卡片一致。
   - **状态行**：
     - 镜头数：取正在看的分镜 `doc`，没打开分镜时取版本的 `shots`。
     - 时长：`doc` 各镜 `playableSeconds`（`timeline.ts`）之和，用 `fmtDuration`（`lib/fmt.ts`）格式化。没有 `doc` 时不显示时长。
     - 步骤：`StatusPill` 显示当前步骤名（`flow.steps.<cur>`）。生成中用 `tone="live"`，其他用 `tone="idle"`。
   - **三格金额**：都来自 `flow.film`（出片会话）。
     - 预估：各段 `estimate_cny` 之和。
     - 已花：`spent_cny`。
     - 上限：`budget_cny`。
     - 没有出片会话时，三格都显示「—」，下方一行小字「出片时才会花钱」。
     - 格式用 `lib/fmt.ts` 的 `cny`。
9. **画布里的精简头部**：
   - 新建 `ChapterHeadContext`（`src/components/workflow/chapterHead.ts`），值是 `ReactNode | null`。
   - `ChapterWorkflow` 用 `<ChapterHeader compact … />` 作为 Provider 的值，包住整个工作区。
   - `TimelineCanvas` 用 `useContext` 读这个值，有值就放在画布顶部标题栏里（在现有标题左侧）。
   - 拿不到 Context（单测、本地 JSON）时什么都不加。
10. **导入原文、生成分镜、下载三步的版式**：
    - 工作区包一层 `<div className="chap-card">`：居中，最大宽度 880px。
    - 主按钮放进卡片右下角：`PrimaryBar` 新增 `inline?: boolean`。`inline` 时不用 `fixed` 定位，改为卡片底部右对齐的一行，原因提示和「去修复」放在按钮左边。
    - `ChapterWorkflow` 在这三步传 `inline`，检查修改、出片、配音合成三步保持原来的固定右下角。
    - `data-testid` 不变。
11. **资产分区缩略图网格**：
    - `NovelAssets` 传了 `kind` 时，默认显示网格 `[data-testid="asset-grid"]`。每张卡是 `[data-testid="asset-tile"]` 按钮，内容：
      - 缩略图：`assetThumb(card)` 有 URL 就显示图；没有就是这一类的渐变色块加名字首字。
      - 名字、等宽 ID。
      - 一行小字：别名数，以及服装数或形态数，没有就不写。
    - 点卡片进入单卡编辑：渲染 `AssetsView`，只传这一张卡；顶部「← 全部角色」（按类别）返回网格。
    - 新建卡片后直接进入新卡的编辑。
    - 搜索框在网格态过滤网格。
    - 「保存」按钮、未保存计数、删除逻辑不变。
    - 没传 `kind`（全部类别）时保持原样。
    - 渐变色块用 CSS 变量：`--thumb-characters` 等四个新变量，定义在 `chapter.css` 的 `:root` 和 `.dark` 里，按 foundation 测试要求定义齐。
    - 概览页的主要人物头像改用同一个 `assetThumb`。

## 文件结构

| 文件 | 职责 |
|---|---|
| `frontend/src/shotFocus.ts` | 新建：三栏视图的纯函数 |
| `frontend/src/lib/assetThumb.ts` | 新建：资产卡缩略图 URL（参考图里第一个可直接显示的） |
| `frontend/src/useShotImages.ts` | 新建：读已上传的关键帧图（blob URL，卸载时回收） |
| `frontend/src/components/ShotFocusView.tsx` | 新建：镜头三栏视图 |
| `frontend/src/components/StoryboardView.tsx` | 修改：页签改为六项、默认「镜头」，新增 `defaultTab`、`report`、`film` |
| `frontend/src/components/workflow/ChapterHeader.tsx` | 新建：章节头部（完整版、精简版） |
| `frontend/src/components/workflow/chapterHead.ts` | 新建：`ChapterHeadContext` |
| `frontend/src/components/workflow/ChapterWorkflow.tsx` | 修改：头部、Context、三步卡片版式、`PrimaryBar inline` |
| `frontend/src/components/workflow/PrimaryBar.tsx` | 修改：`inline` |
| `frontend/src/components/TimelineCanvas.tsx` | 修改：顶部读 `ChapterHeadContext` |
| `frontend/src/components/NovelAssets.tsx` | 修改：`kind` 时网格与单卡编辑两态 |
| `frontend/src/components/NovelOverview.tsx` | 修改：头像用 `assetThumb` |
| `frontend/src/App.tsx` | 修改：给 `StoryboardView` 传 `report`、`film` |
| `frontend/src/styles/chapter.css`、`app.css`、`i18n/zh.ts`、`en.ts` | 新建、修改 |
| `frontend/tests/chapter.test.tsx`、`package.json` | 新建第 16 套测试并加进 `npm test` |
| `frontend/tests/flow.test.tsx`、`real-doc.test.tsx`、`workflow-ui.test.tsx`、`workspace.test.tsx` | 修改：页签改名、默认视图变化、主按钮位置的断言同步 |

---

### Task 1: 纯函数与关键帧图钩子

**Files:**
- Create: `frontend/src/shotFocus.ts`、`frontend/src/lib/assetThumb.ts`、`frontend/src/useShotImages.ts`
- Create: `frontend/tests/chapter.test.tsx`；Modify: `frontend/package.json`（`test` 脚本末尾追加这一套，写法与 `workspace` 那套一样）

- [ ] **Step 1: 先写失败测试**（`chapter.test.tsx` 第一段，结构照抄 `tests/workflow.test.ts` 的 `must` 写法）：

```ts
import { assetThumb } from '../src/lib/assetThumb'
import { clipForShot, filterShots, flatShots, shotIssues, stepShot } from '../src/shotFocus'
import type { FilmSession, Shot, Storyboard, VerificationReport } from '../src/types'

const shot = (id: string, o: Partial<Shot> = {}) =>
  ({ id, duration_sec: 3, shot_size: 'medium', action: `${id} 的画面`, source: { unit_refs: [], derivation: 'explicit' }, ...o }) as Shot
const doc = {
  episodes: [
    { id: 'E01', shots: [shot('SH001'), shot('SH002', { narration: { text: '康大叔推门' } as Shot['narration'] })] },
    { id: 'E02', shots: [shot('SH003')] },
  ],
} as unknown as Storyboard

const rows = flatShots(doc)
must(rows.map((r) => r.shot.id).join() === 'SH001,SH002,SH003', '按集顺序拍平')
must(rows[2].ep === 'E02', '记下所在集')

const report = { status: 'failed', findings: [
  { rule_id: 'a', severity: 'high', object_path: '/episodes/0/shots/1/action', message: '' },
  { rule_id: 'b', severity: 'low', object_path: '/episodes/0/shots/1', message: '' },
  { rule_id: 'c', severity: 'medium', object_path: '/episodes/1/shots/0/dialogue/0', message: '' },
  { rule_id: 'd', severity: 'critical', object_path: '/source/units/3', message: '' },
] } as VerificationReport
const issues = shotIssues(report, doc)
must(issues.get('SH002') === 'hard', '同镜有硬有软按硬')
must(issues.get('SH003') === 'soft', '中低级是软问题')
must(!issues.has('SH001') && issues.size === 2, '指不到镜头的不标')
must(shotIssues(null, doc).size === 0, '没报告时为空')

const film = { clips: [
  { id: 'K1', shots: ['SH001', 'SH002'], chosen: 0, attempts: [{ file: 'clips/K1-0.mp4' }] },
  { id: 'K2', shots: ['SH003'], chosen: null, attempts: [] },
] } as unknown as FilmSession
must(clipForShot(film, 'SH002')?.file === 'clips/K1-0.mp4', '找到片段与采用的文件')
must(clipForShot(film, 'SH003')?.file === null, '没采用时文件为 null')
must(clipForShot(film, 'SH999') === null && clipForShot(null, 'SH001') === null, '找不到为 null')

must(stepShot(rows, 'SH001', 1) === 'SH002' && stepShot(rows, 'SH003', 1) === 'SH003', '下一镜到底不动')
must(stepShot(rows, 'SH001', -1) === 'SH001', '上一镜到顶不动')
must(stepShot(rows, 'SH002', 'end') === 'SH003' && stepShot(rows, 'SH002', 'home') === 'SH001', 'Home / End')
must(stepShot(rows, 'SH003', -1, new Set(['E01'])) === 'SH003', '跳过折叠的集')

must(filterShots(rows, 'sh003').length === 1, '按 ID 不分大小写')
must(filterShots(rows, '推门').map((r) => r.shot.id).join() === 'SH002', '按旁白文字')
must(filterShots(rows, '  ').length === 3, '空查询不过滤')

must(assetThumb({ id: 'C01', name: '华', reference_images: [{ uri: 'refs/a.png' }, { uri: 'https://x/a.png' }] }) === 'https://x/a.png', '取第一个可直接显示的')
must(assetThumb({ id: 'C01', name: '华' }) === null, '没有图为 null')
console.log('chapter: ALL PASS')
```

- [ ] **Step 2: 跑一下，确认失败**：`cd frontend && npm run typecheck`，报模块不存在。
- [ ] **Step 3: 实现**：

```ts
// src/shotFocus.ts
/** 镜头三栏视图的纯逻辑：拍平、标检查结果、找所在片段、过滤与上下切换。 */
import type { FilmSession, Severity, Shot, ShotSize, Storyboard, VerificationReport } from './types'

export interface ShotRow { ep: string; shot: Shot }

export function flatShots(doc: Storyboard): ShotRow[] {
  return (doc.episodes ?? []).flatMap((e) => e.shots.map((shot) => ({ ep: e.id, shot })))
}

const HARD: Severity[] = ['critical', 'high']

/** 检查结果归到镜头：/episodes/<i>/shots/<j>/… 才算；硬问题盖过软问题 */
export function shotIssues(report: VerificationReport | null | undefined, doc: Storyboard) {
  const out = new Map<string, 'hard' | 'soft'>()
  for (const f of report?.findings ?? []) {
    const m = /^\/episodes\/(\d+)\/shots\/(\d+)(\/|$)/.exec(f.object_path)
    const id = m && doc.episodes?.[Number(m[1])]?.shots?.[Number(m[2])]?.id
    if (!id) continue
    if (HARD.includes(f.severity)) out.set(id, 'hard')
    else if (!out.has(id)) out.set(id, 'soft')
  }
  return out
}

/** 这一镜所在的出片段，以及采用那次的文件（没采用或没文件为 null） */
export function clipForShot(film: FilmSession | null | undefined, shotId: string) {
  const clip = film?.clips.find((c) => c.shots.includes(shotId))
  if (!clip) return null
  const file = clip.chosen === null ? null : clip.attempts[clip.chosen]?.file ?? null
  return { clip, file }
}

/** 上下切换；collapsed 里的集整体跳过；到头不动 */
export function stepShot(rows: ShotRow[], id: string, dir: 1 | -1 | 'home' | 'end',
                         collapsed: Set<string> = new Set()) {
  const open = rows.filter((r) => !collapsed.has(r.ep))
  if (!open.length) return id
  if (dir === 'home') return open[0].shot.id
  if (dir === 'end') return open[open.length - 1].shot.id
  const i = open.findIndex((r) => r.shot.id === id)
  if (i < 0) return open[0].shot.id
  return open[Math.max(0, Math.min(open.length - 1, i + dir))].shot.id
}

export function filterShots(rows: ShotRow[], query: string) {
  const q = query.trim().toLowerCase()
  if (!q) return rows
  return rows.filter(({ shot: s }) => [s.id, s.action, s.narration?.text, ...(s.dialogue ?? []).map((d) => d.text)]
    .some((v) => typeof v === 'string' && v.toLowerCase().includes(q)))
}

/** 景别色块的色相：越远越冷、越近越暖 */
export const SIZE_HUE: Record<ShotSize, number> = {
  extreme_wide: 210, wide: 200, full: 185, medium: 160,
  medium_close: 45, close_up: 25, extreme_close_up: 10, insert: 280,
}
```

```ts
// src/lib/assetThumb.ts
/** 资产卡的缩略图：参考图里第一个浏览器能直接显示的地址（http(s)、data:、站内绝对路径）；没有为 null */
export function assetThumb(card: { reference_images?: { uri?: string }[] }): string | null {
  return card.reference_images?.find((r) => r.uri && /^(https?:|data:|\/)/.test(r.uri))?.uri ?? null
}
```

  `src/useShotImages.ts`：`useShotImages(version: VersionRef | null | undefined, reloadKey: unknown) → Record<shotId, blobUrl>`。
  - 读取写法照抄 `useKeyframes.ts` 里读图那一段：`listKeyframes`，再逐个 `keyframeUrl`，`gone` 标志防竞态，卸载或依赖变化时 revoke 全部。
  - 依赖是 `nid`、`cid`、`vid` 和 `reloadKey`。
  - 读失败时静默返回空表，不报错。三栏视图只是看图，出图的报错归画布管。
  - 文件头注释说明：不请求出图提示词，与 `useKeyframes` 的区别就在这里。
- [ ] **Step 4:** `npm test` 全过（16 套），lint 与 build 通过。
- [ ] **Step 5: 提交**

```bash
git add frontend/src/shotFocus.ts frontend/src/lib/assetThumb.ts frontend/src/useShotImages.ts frontend/tests/chapter.test.tsx frontend/package.json
git commit -m "章节工作台的纯逻辑：镜头拍平、检查结果归到镜头、找镜头所在出片段、过滤与上下切换、景别色；资产卡缩略图来源；只读关键帧图的钩子；新增 chapter 测试套件"
```

---

### Task 2: 镜头三栏视图组件 `ShotFocusView`

**Files:**
- Create: `frontend/src/components/ShotFocusView.tsx`、`frontend/src/styles/chapter.css`
- Modify: `frontend/src/styles/app.css`（引入 `chapter.css`）、`frontend/src/i18n/zh.ts`、`en.ts`
- Test: `frontend/tests/chapter.test.tsx`（第二段）

组件接口：

```ts
interface Props {
  doc: Storyboard
  idx: Index                       // StoryboardView 里已有的 buildIndex(doc)
  report?: VerificationReport | null
  film?: FilmSession | null
  version?: VersionRef | null      // 读关键帧图、成片段
  imagesKey?: unknown              // 画布关上后加一，重读关键帧图
  readOnly: boolean                // 分批预览
  dirty: boolean
  saving: boolean
  canSave: boolean
  /** 外部要求选中的镜头（画布跳回）；变化时选中它 */
  focusShot?: string | null
  onShotChange: (episodeId: string, shotId: string, patch: Partial<Shot>) => void
  onPickUnit: (unitId: string) => void
  onSave: () => void
  onOpenCanvas: () => void
}
```

- [ ] **Step 1: 先写失败测试**（第二段，直接渲染 `ShotFocusView`，包在 `I18nProvider` 里，用 Task 1 的 `doc`，给 `SH002` 加 `source.unit_refs: ['U1']`，`idx` 用 `buildIndex(doc)`，`doc.source.units` 放一句 `U1`）：
  - **左栏**：
    - 有 3 个 `[role="option"]`，按集分组：有两个集标题按钮，写着「E01」「E02」。
    - 默认选中第一镜，`aria-selected="true"`。
    - 传了上面的 `report` 后，`SH002` 那一项带 `[data-issue="hard"]`，`SH003` 那一项带 `[data-issue="soft"]`。
  - **点选**：
    - 点 `SH002` 后，中栏的 `.shot` 只有 1 个，`id` 为 `shot-SH002`。
    - 右栏 `[data-testid="focus-source"]` 里有 `U1` 和那句原文。
    - 右栏的景别色块 `[data-testid="focus-frame"]` 写着 `SH002`。
  - **键盘**：在列表上按 `ArrowDown` 选中 `SH003`，按 `Home` 回到 `SH001`。先点集标题「E01」折叠后，从 `SH003` 按 `ArrowUp` 停在 `SH003`。
  - **搜索**：搜索框输入「推门」后，只剩 1 项。
  - **主按钮**：
    - `dirty={false}` 时，`[data-testid="focus-primary"]` 写「在画布中查看」，点了调用 `onOpenCanvas`。
    - 重渲染成 `dirty canSave` 时写「保存修改」，点了调用 `onSave`。
    - `saving` 时禁用。
  - **编辑**：在中栏的画面描述框输入文字，`onShotChange` 收到 `('E01', 'SH002', { action: … })`。
  - **成片段**：给 `film` 传 Task 1 的片段时，`SH001` 出现 `[data-testid="focus-media"]` 分段控件；`SH003` 没有。
  - **外部定位**：`focusShot="SH003"` 时选中 `SH003`。
- [ ] **Step 2: 实现**：
  - **布局**：三列网格 `grid-template-columns: 280px minmax(0,1fr) 320px`，类名 `.focus`；三栏分别是 `.focus__list`、`.focus__main`、`.focus__side`。
    - 小于 1100px 时：`grid-template-columns: 280px minmax(0,1fr)`，右栏放到第二列中栏下面。
    - 小于 760px 时：按实施裁定 7 切成列表态、编辑态两态。
  - **左栏**：
    - 顶部是搜索框，下面按集分组。集标题是按钮，含折叠箭头、集 ID（等宽）、镜头数；点了折叠或展开，折叠状态记在 `collapsed: Set<string>`。
    - 每项（高 44px）：
      - 缩略图 40×24：关键帧图，或者用 `SIZE_HUE` 画的 `hsl(h 55% 50% / .35)` 色块。
      - 等宽镜头 ID。
      - 来源标签：沿用 `.deriv deriv--<derivation>` 的类名和 `label(DERIVATION, …)` 文案。
      - 右侧是等宽时长（`playableSeconds` 保留 1 位小数，加 `s`）。
      - 有问题时加小圆点：`data-issue`，红色 `--destructive`，黄色 `--warning`。
    - 选中项用 `--ui-accent` 底，左边加 `--primary` 竖条。
    - 选中项变化时 `scrollIntoView({ block: 'nearest' })`；环境没有这个方法就跳过。
    - 键盘按实施裁定 6，用 `stepShot`。
  - **中栏**：
    - 标题行：`E01-SH012 · 中景 · 推 · 4.0s`，取镜头 ID、`label(SHOT_SIZE, …)`、`label(CAMERA_MOVEMENT, shot.camera?.movement)`、`duration_sec`，没有的项省略。
    - 下面是 `<ShotCard shot idx editing={!readOnly} onPickUnit onChange={(p) => onShotChange(ep, id, p)} />`。
    - 用 `motion.div key={shot.id} {...m.enter}` 包住。
  - **右栏**：
    - 关键帧图（`useShotImages(version, imagesKey)`）或者景别色块 `[data-testid="focus-frame"]`，比例按 `doc.meta.video.aspect_ratio`，缺省 16:9。
    - 成片段切换 `[data-testid="focus-media"]`，按实施裁定 5。
    - 原文句子 `[data-testid="focus-source"]`，没有引用时写「这一镜没有引用原文（系统补充）」。
    - 底部通栏主按钮 `[data-testid="focus-primary"]`。
  - **选中状态**：
    - `selected` 初始为第一镜。
    - `focusShot` 变化时设为它。
    - doc 里找不到当前选中的镜头时（被删、换版本），回到第一镜。
    - 过滤后选中项不在结果里时，不改选中，中栏照常显示。
  - **新增文案**（`board.focus.*`）：`search`、`listAria`、`noSource`、`frame`、`clip`、`saveEdits`、`openCanvas`、`backToList`、`epCount`（「{n} 镜」）。
- [ ] **Step 3:** 测试全过，三项检查全过。
- [ ] **Step 4: 提交**

```bash
git add frontend/src/components/ShotFocusView.tsx frontend/src/styles/chapter.css frontend/src/styles/app.css frontend/src/i18n/zh.ts frontend/src/i18n/en.ts frontend/tests/chapter.test.tsx
git commit -m "镜头三栏视图组件：左栏按集分组的镜头列表（缩略图、来源、时长、检查红点、搜索、折叠、上下键切换），中栏选中镜头的完整编辑，右栏关键帧或成片段、原文出处与通栏主按钮，窄屏改上下或列表与编辑两态"
```

---

### Task 3: 把三栏视图接进分镜视图，成为默认页签

**Files:**
- Modify: `frontend/src/components/StoryboardView.tsx`、`frontend/src/App.tsx`、`frontend/src/i18n/zh.ts`、`en.ts`
- Test: `frontend/tests/flow.test.tsx`、`real-doc.test.tsx`、`workflow-ui.test.tsx`（受默认视图影响的断言），`chapter.test.tsx`（第三段）

- [ ] **Step 1: 先写失败测试**（第三段，渲染 `StoryboardView`，用 Task 1 的 `doc` 加上 `meta`）：
  - `.tabs__btn` 的文字依次是「镜头 卡片 资产 原文 渲染 JSON」。
  - 默认是「镜头」：存在 `.focus`，`.shot` 只有 1 个。
  - 点「卡片」后，`.shot` 有 3 个。
  - `defaultTab="cards"` 时一开始就是卡片视图。
- [ ] **Step 2: 实现**：
  - **`StoryboardView`**：
    - 按实施裁定 1 改 `Tab` 和 `TABS`，`useState<Tab>(defaultTab ?? 'focus')`。
    - `focus` 页签渲染 `ShotFocusView`，传入：
      - `idx`、`report`、`film`、`version`；
      - `imagesKey`：新的计数，`closeCanvas` 时加一；
      - `readOnly={!!preview}`、`dirty`、`saving`；
      - `canSave={canSave && !preview}`；
      - `focusShot`；
      - `onShotChange={changeShot}`、`onPickUnit={pickUnit}`、`onSave`、`onOpenCanvas={() => setCanvas(true)}`。
    - `jumpShot` 改为 `setTab('focus')` 并设置 `focusShot`。原来滚动卡片的那段 effect，只在 `tab === 'cards'` 时生效。
    - `focusShot` 交给 `ShotFocusView` 之后不再清空，由 `ShotFocusView` 自己比对变化。
  - **i18n**：`board.tabs` 改为 `{ focus, cards, assets, source, render, json }`，中文「镜头 / 卡片 / 资产 / 原文 / 渲染 / JSON」，英文 `Shots / Cards / Assets / Source / Render / JSON`。原 `shots` 键删除，引用处全改。
  - **`App`**：
    - `StoryboardView` 加 `report={verification}`。
    - 加 `film={flow.film}`。`flow` 是 App 里 `useChapterFlow` 的返回值；没打开章节时为 `null`。
- [ ] **Step 3: 同步旧测试**：
  - **`real-doc.test.tsx`**：
    - 两处只读态、编辑态渲染 `StoryboardView` 的地方，加 `defaultTab="cards"`。这两段测的是卡片视图的完整渲染。
    - 英文页签断言改成 `'Shots Cards Assets Source Render JSON'`。
  - **`flow.test.tsx`**：
    - 原来按文字「分镜」找页签的地方，改成「卡片」。
    - 依赖全部镜头卡片的步骤，先点「卡片」页签。
    - 只改到能过为止，不删断言。
  - **`workflow-ui.test.tsx`**：同上。
  - 把改了哪些断言、为什么改写进报告。
- [ ] **Step 4:** 测试全过，三项检查全过。
- [ ] **Step 5: 提交**

```bash
git commit -m "分镜视图改为六个页签，默认是镜头三栏视图：原分镜卡片视图改名卡片保留为第二项；画布跳回镜头改为在三栏视图里选中；三栏视图拿到检查报告与出片会话，用于红点与成片段预览"
```

---

### Task 4: 章节头部与画布里的精简头部

**Files:**
- Create: `frontend/src/components/workflow/ChapterHeader.tsx`、`frontend/src/components/workflow/chapterHead.ts`
- Modify: `frontend/src/components/workflow/ChapterWorkflow.tsx`、`frontend/src/components/TimelineCanvas.tsx`、`frontend/src/i18n/zh.ts`、`en.ts`、`frontend/src/styles/chapter.css`
- Test: `frontend/tests/chapter.test.tsx`（第四段）、`workflow-ui.test.tsx`

组件接口：

```ts
// ChapterHeader.tsx
export function ChapterHeader(props: {
  num: number                      // 1 起
  title: string
  shots: number | null
  seconds: number | null           // 可播总时长
  step: StepId
  live: boolean                    // 生成中
  film: FilmSession | null
  compact?: boolean
}): JSX.Element

// chapterHead.ts
export const ChapterHeadContext = createContext<ReactNode | null>(null)
```

- [ ] **Step 1: 先写失败测试**（第四段，直接渲染 `ChapterHeader`）：
  - `num={3}` 显示「EP·03」，标题「第三章」。
  - 状态行有「45 镜」「4:45」和步骤名「检查修改」。
  - `film=null` 时，`[data-testid="cost-tile"]` 有 3 个，内容都是「—」，并且有「出片时才会花钱」。
  - `film` 有两段 `estimate_cny` 2.5 和 2.94、`spent_cny` 3.66、`budget_cny` 20 时，三格依次是「¥5.44」「¥3.66」「¥20.00」。
  - `compact` 时只有一行 `[data-testid="chapter-head-compact"]`，内容是编号、标题、已花 / 上限（「¥3.66 / ¥20.00」）。没有出片会话时省略金额。
  - 渲染一个读取 `ChapterHeadContext` 的小组件，包在 `<ChapterHeadContext.Provider value={<span id="x" />}>` 里，能读到这个节点。确认 Context 可用。
- [ ] **Step 2: 实现**：
  - **`ChapterHeader`**：
    - 完整版两行。左边是编号徽章（等宽、`--ui-accent` 底）、大号标题，加一行状态小字：镜头数 · 约时长 · `StatusPill` 步骤名。右边是三格金额：小字标签「预估 / 已花 / 上限」，下面等宽大字。
    - 宽度不够（小于 760px）时，三格换到第二行。
  - **`ChapterWorkflow`**：
    - 在步骤条与版本条那一节之前，渲染完整版头部。编号用 `novel.chapters.findIndex(…) + 1`，镜头数与时长按实施裁定 8 计算。`film` 用 `ready ? flow.film : null`，与 `input.film` 一致；`step` 用 `cur`，`live` 用 `converting`。
    - 整个返回值包进 `<ChapterHeadContext.Provider value={<ChapterHeader compact … />}>`。
  - **`TimelineCanvas`**：`const head = useContext(ChapterHeadContext)`，在画布顶部标题栏最左侧渲染 `{head}`；`head` 为 `null` 时不变。
  - **新增文案**：`flow.head.estimate`、`spent`、`cap`、`noFilm`、`shots`（「{n} 镜」）、`about`（「约 {d}」）。
- [ ] **Step 3:** `workflow-ui.test.tsx` 补一条断言：渲染 `ChapterWorkflow` 后有 `[data-testid="chapter-head"]`，写着章节标题。测试全过，三项检查全过。
- [ ] **Step 4: 提交**

```bash
git commit -m "章节头部：编号、标题、镜头数与时长、当前步骤，右侧预估、已花、上限三格（没有出片会话时说明出片时才花钱）；画布顶部加一行精简头部"
```

---

### Task 5: 导入原文、生成分镜、下载三步改成卡片版式

**Files:**
- Modify: `frontend/src/components/workflow/ChapterWorkflow.tsx`、`frontend/src/components/workflow/PrimaryBar.tsx`、`frontend/src/styles/chapter.css`
- Test: `frontend/tests/workflow-ui.test.tsx`

- [ ] **Step 1: 先写失败测试**（`workflow-ui.test.tsx`，沿用现有渲染 `ChapterWorkflow` 的夹具）：
  - 停在「导入原文」时，`[data-testid="primary-action"]` 在 `.chap-card` 里面，祖先上没有 `fixed` 类。
  - 切到「检查修改」后，`[data-testid="primary-action"]` 不在 `.chap-card` 里。
  - 「生成分镜」「下载」同理各断言一次。
- [ ] **Step 2: 实现**：
  - **`PrimaryBar`** 加 `inline?: boolean`：
    - `inline` 时，外层改成 `mt-2 flex items-center justify-end gap-3`，不加 `fixed` 和 `pointer-events-none`。原因提示放在按钮左边，用同样的 `motion` 进出。
    - 其余不变。
  - **`ChapterWorkflow`**：
    - `import`、`storyboard`、`download` 三步的工作区包进 `.chap-card`：`max-width: 880px; margin-inline: auto; width: 100%`，内部 `flex flex-col gap-4`。
    - 这三步的 `PrimaryBar inline` 放在 `.chap-card` 的末尾。
    - 其他步骤仍在根节点末尾渲染固定版。
    - 同一时刻只渲染一个 `PrimaryBar`。
  - `storyboard` 步骤里 `{!doc && storyboard}` 那段复验报告放在卡片下面，不进卡片。
- [ ] **Step 3:** 测试全过，三项检查全过。
- [ ] **Step 4: 提交**

```bash
git commit -m "导入原文、生成分镜、下载三步改为居中卡片版式，主按钮放进卡片右下角；检查修改、出片、配音合成仍用右下角固定主按钮"
```

---

### Task 6: 资产分区的缩略图网格

**Files:**
- Modify: `frontend/src/components/NovelAssets.tsx`、`frontend/src/components/NovelOverview.tsx`、`frontend/src/styles/chapter.css`、`frontend/src/i18n/zh.ts`、`en.ts`
- Test: `frontend/tests/chapter.test.tsx`（第五段）、`flow.test.tsx`（资产分区相关步骤）

- [ ] **Step 1: 先写失败测试**（第五段，直接渲染 `NovelAssets kind="characters"`，3 张角色卡，其中 1 张有 `https://` 参考图；`upsertMemoryCard` 用 `fetch` 打桩，写法照抄 `workspace.test.tsx` 的打桩方式）：
  - 有 `[data-testid="asset-grid"]`，里面 3 个 `[data-testid="asset-tile"]`。有图那张里有 `img`，另外两张没有 `img`，显示首字。
  - 搜索框输入第二张卡的名字后，只剩 1 张。
  - 点第一张卡后网格消失，出现单卡编辑（`AssetsView` 渲染出这张卡的 ID）和「← 全部角色」。点返回，网格回来。
  - 新建一张卡（填名字、点新增）后直接进入新卡的编辑。
  - 不传 `kind` 时没有 `asset-grid`，保持原样。
- [ ] **Step 2: 实现**：
  - **`NovelAssets`**：新增状态 `open: string | null`，表示单卡编辑的卡 ID。`kind` 存在且 `open` 为 `null` 时渲染网格，否则渲染 `AssetsView`，只传 `{ [kind]: [那张卡] }`。
    - 网格每张卡按实施裁定 11 渲染：`button`，带 `aria-label={card.name}`。
    - 网格响应式：`grid-template-columns: repeat(auto-fill, minmax(160px, 1fr))`；缩略图区比例 4:3。
    - 渐变色块：`background: linear-gradient(135deg, var(--thumb-<kind>), color-mix(in oklab, var(--thumb-<kind>) 40%, var(--card)))`，四个变量在 `chapter.css` 的浅色、深色两套里定义。
    - `key={section}` 已由上层保证换类别时重置，这里不用再处理。
  - **`NovelOverview`**：`Avatar` 改用 `assetThumb(c)`。
  - **新增文案**：`assets.grid.back`（「← 全部{kind}」）、`aliases`（「{n} 个别名」）、`variants`（「{n} 套服装」或「{n} 种形态」，按类别分两个键）、`gridAria`。
- [ ] **Step 3: `flow.test.tsx`**：资产分区里直接操作卡片编辑框的步骤，先点对应的 `[data-testid="asset-tile"]` 进入单卡编辑。只改到能过为止，在报告里列出改了哪些。测试全过，三项检查全过。
- [ ] **Step 4: 提交**

```bash
git commit -m "资产分区改为缩略图网格：参考图或类别渐变色块、名字与编号、别名与服装形态数，点开进入单卡编辑、新建后直接编辑；概览页人物头像共用同一个缩略图来源"
```

---

## 自查记录

- **规格覆盖**：
  - 8.1 章节头部：Task 4。
  - 8.2 三栏视图：Task 1、2、3。
  - 8.3 画布加精简头部：Task 4。
  - 8.4 三步版式：Task 5。
  - 资产页缩略图：Task 6。
  - 第 10 节等宽字、`StatusPill`、缩略图兜底色块、每屏一个主按钮：分布在 Task 2、4、6。
  - 第 13 节三栏视图的测试要求（选中后中右栏跟随、编辑后出现未保存提示、上下键切换）：Task 2、3。未保存提示条由 `ChapterWorkflow` 的 `UnsavedBar` 负责，Task 2 测 `onShotChange` 被调用，Task 3 在 flow 里沿用原有的未保存断言。
- **类型一致**：
  - `ShotRow`、`stepShot`、`clipForShot`、`shotIssues`、`assetThumb`、`useShotImages`：在 Task 1 定义，Task 2、6 使用。
  - `ChapterHeadContext`：在 Task 4 定义并使用。
  - `defaultTab`、`report`、`film`：在 Task 3 定义，App 传入。
