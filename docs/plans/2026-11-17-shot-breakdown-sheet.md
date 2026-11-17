# 拉片表与片段卡镜头标签 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 分镜视图新增只读的「拉片表」页签（每镜一行、按集分组，地址 `?tab=sheet`），并在出片节点图的片段卡上逐镜列出「镜号 景别·运镜」小标签，让用户看得到已有的镜号、景别、运镜数据。

**Architecture:**
- 纯前端，数据全部来自 `StoryboardView` 与 `NodeGraph` 已有的属性（`doc`、`film`、`version`），不改后端、schema、接口，也不改 `App.tsx`。
- 计算与界面分开：新文件 `frontend/src/shotSheet.ts` 放纯函数（分组、提示词格的 `rowSpan`、运镜文字、镜头小标签、折叠），新组件 `frontend/src/components/ShotSheet.tsx` 只管渲染。
- 拉片表的跳转复用 `StoryboardView` 现有的 `jumpShot`；关键帧图复用 `useShotImages`；片段卡标签由 `NodeGraph` 算好后以 `tags` 属性传给 `ClipCard`。

**Tech Stack:** React 19、TypeScript、Vite 8、happy-dom；测试是 `vite build --ssr` 构建后交给 node 跑的脚本，断言用文件内的 `must` / `eq`（仓库**没有** vitest 和 testing-library，不要引入）。

**Spec:** `docs/specs/2026-11-17-shot-breakdown-sheet-design.md`。下文用「§n」引用它的章节。

---

## 全局约束（每个 Task 都必须遵守）

- **只改本计划列出的文件**。不改后端（`backend/` 下任何文件）、不改 schema、不改 `frontend/src/App.tsx`。
- **不碰的文件与服务**：
  - 不读、不打印 `backend/.env`；
  - 不运行任何 smoke 脚本，不调用付费服务或真实大模型；
  - 不启动前后端服务，不向 5173 / 8000 端口发请求；
  - 不动、不提交 `docs/specs/2026-10-27-commercialization-design-contract.md`（未跟踪文件，保持原样）。
- **提交规则**：
  - 只 `git add <具体文件>`，禁止 `git add -A`、`git commit -a`、`git add -N`、`git stash`；
  - 提交信息用中文、描述性写法，**不得带 `Co-Authored-By`、`Claude-Session` 等任何署名尾行**；
  - 不 push。
- **每个 Task 提交前都要通过**（在 `frontend/` 目录下）：
  - `npm test` 退出码为 0；
  - `npm run lint` 为 0 error，警告恰好是基线的 5 条（`VerificationPanel.tsx`、`CardPicker.tsx`、`timeline.ts`、`ParamsForm.tsx`、`App.tsx` 各一条），**不得增加**；
  - `npm run build` 成功（「Some chunks are larger than 500 kB」是既有提示，不算失败）。
- **film.test 已知偶发卡死**：`tests/film.test.tsx` 在改动前就有小概率 CPU 自旋不退出，或报「✗ 预览窗里播视频」。遇到时单独重跑判定：`npx vite build --ssr tests/film.test.tsx --outDir .ssrout-x --logLevel error && timeout 60 node .ssrout-x/film.test.js`，然后删掉 `.ssrout-x`。单独重跑能 `ALL PASS` 就不算本任务失败，在报告里注明。本计划不修它。
- **普通用户界面不得出现模型或供应商名**：新代码只读 `clip.id`、`clip.duration`、`clip.prompt`、`clip.shots`，不读 `FilmSession.provider`、`model`、`options`。
- **不顺手重构**：不改与本功能无关的行为与文案。
- 代码块里的内容照抄即可，它们已在仓库的一份临时副本上整套跑通（`npm test`、`npm run lint`、`npm run build`）。如果照抄后某一步的结果与本计划写的「Expected」不符，先核对是否抄漏，再报告，不要自行改设计。

## 先读这一节：仓库里与本任务有关的事实

- **测试怎么跑**。`frontend/package.json` 的 `test` 脚本是一长串 `vite build --ssr tests/x --outDir .ssrout --logLevel error && node .ssrout/x.js`，前面先跑 `npm run typecheck`（`tsc -b --force`，只检查 `src`，不检查 `tests`）。**新增的测试文件必须追加到这串脚本末尾，否则 `npm test` 不会跑它。**
  - 单独跑一个测试（在 `frontend/` 下）：`npx vite build --ssr tests/<文件名> --outDir .ssrout --logLevel error && node .ssrout/<去掉扩展名>.js`
  - 通过的标志是最后打印 `ALL PASS` 且退出码为 0；失败是抛出 `✗ …` 的错误。
  - `.ssrout` 已在 `.gitignore` 里。
- **界面测试的写法**。文件开头用 happy-dom 造一个 `Window` 并把 `window`、`document` 等挂到 `globalThis`，再 `await import` React 与被测组件，用 `createRoot` + `act` 渲染，用 `container.querySelector` 断言。没有 `I18nProvider` 时界面是中文；包一层 `<I18nProvider initial="en">` 是英文。
- **双语文案**。`frontend/src/i18n/zh.ts` 是基准，`en.ts` 的类型是 `Messages`（由 `zh.ts` 推出），两边键必须一一对应，否则 `tsc` 报错。组件里用 `const { t } = useI18n()`。
- **枚举标签**。`frontend/src/labels.ts` 的 `SHOT_SIZE`、`CAMERA_MOVEMENT`、`CAMERA_ANGLE`、`DIALOGUE_TYPE` 是按当前语言取值的表；`label(表, 值)` 找不到时原样返回该值，值为空返回空串。纯函数测试里用 `setCurrentLocale('en')` 切语言。
- **`StoryboardView` 已经有拉片表需要的全部数据**（`frontend/src/components/StoryboardView.tsx`）：
  - `doc`、`idx`（`buildIndex(doc)`，`idx.assetName(id)` 把资产 id 换成名字）；
  - `film?: FilmSession | null`（`App.tsx` 传的是 `flow.film`）、`version?: VersionRef | null`；
  - 组件内状态 `imagesKey`（画布关上时加一，让关键帧图重取）；
  - 函数 `jumpShot(shotId)`：记下要定位的镜头，受控时调用上层的 `onJumpShot()`（`App` 一次 `replace` 到不带 `?tab=` 的地址），非受控时 `setTab('focus')`。拉片表点行直接用它。
- **地址里的页签**。`frontend/src/paths.ts` 的 `TABS` 是 `?tab=` 的合法值清单，`parseLocation` 与 `chapterPath` 都靠它；加进 `'sheet'` 就够了。
- **片段卡**。`frontend/src/components/NodeGraph.tsx` 有 `doc` 属性；它渲染 `frontend/src/components/NodeCards.tsx` 的 `ClipCard`，后者目前只拿到 `clip`（`clip.shots` 是镜头 id 数组），拿不到镜头数据。卡片高度是 `frontend/src/nodeGraph.ts` 的常量 `CARD_H`，卡片 `overflow: auto`，内容超高会出滚动条。
- **镜头 id 的样子**：`E01-SH003`。片段 id 的样子：`E01-C01`。

## 文件结构

| 文件 | 职责 | 任务 |
|---|---|---|
| `frontend/src/shotSheet.ts`（新） | 纯函数：`sheetGroups`、`cameraText`、`shortShotId`、`shotTag`、`shotsById`、`clipShotTags`、`foldTags`、`needsFold` | 1 |
| `frontend/tests/shot-sheet.test.ts`（新） | 上面纯函数的单测 | 1 |
| `frontend/src/components/ShotSheet.tsx`（新） | 拉片表组件 | 2 |
| `frontend/tests/sheet-view.test.tsx`（新） | 拉片表界面测试（Task 2 单独渲染组件，Task 3 追加接进 `StoryboardView` 的用例） | 2、3 |
| `frontend/src/i18n/zh.ts`、`frontend/src/i18n/en.ts` | 新增 `board.tabs.sheet`、`board.sheet.*` | 2 |
| `frontend/src/styles/storyboard.css` | 文件末尾追加 `.sheet*` | 2 |
| `frontend/src/components/StoryboardView.tsx` | `Tab`、`TABS` 加 `'sheet'`，渲染 `<ShotSheet>` | 3 |
| `frontend/src/paths.ts` | `TABS` 加 `'sheet'` | 3 |
| `frontend/tests/paths.test.ts`、`frontend/tests/chapter.test.tsx`、`frontend/tests/real-doc.test.tsx` | 页签相关断言 | 3 |
| `frontend/src/components/NodeCards.tsx` | `ClipCard` 新增 `tags` 属性并渲染 | 4 |
| `frontend/src/components/NodeGraph.tsx` | 建镜头索引，把标签传给 `ClipCard` | 4 |
| `frontend/src/nodeGraph.ts` | `CARD_H` 208 → 252 | 4 |
| `frontend/src/styles/nodegraph.css` | 文件末尾追加 `.ngv__shots`、`.ngv__shot` | 4 |
| `frontend/tests/graph-view.test.tsx` | 片段卡标签用例 | 4 |
| `frontend/package.json` | `test` 脚本追加两个新测试 | 1、2 |

---

### Task 1: 纯函数 `shotSheet.ts`

分组、提示词格合并行数、运镜文字、镜头小标签、折叠。Task 2 与 Task 4 都依赖它。对应 §3.2、§3.4、§3.5、§4。

**Files:**
- Create: `frontend/src/shotSheet.ts`
- Create: `frontend/tests/shot-sheet.test.ts`
- Modify: `frontend/package.json`（`scripts.test` 末尾）

- [ ] **Step 1: 写失败的测试**

新建 `frontend/tests/shot-sheet.test.ts`，内容：

```ts
/** 拉片表与片段卡镜头标签的纯计算：分组与提示词格合并、运镜文字、镜头小标签、折叠。
 *  界面由 sheet-view.test.tsx 与 graph-view.test.tsx 覆盖。跑法：npm test */
import { setCurrentLocale } from '../src/i18n/core'
import {
  cameraText, clipShotTags, foldTags, needsFold, sheetGroups, shortShotId, shotTag, shotsById,
} from '../src/shotSheet'
import type { FilmClip, FilmSession, Shot, Storyboard } from '../src/types'

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }
const eq = (a: unknown, b: unknown, msg: string) =>
  must(JSON.stringify(a) === JSON.stringify(b), `${msg}\n  得到 ${JSON.stringify(a)}\n  期望 ${JSON.stringify(b)}`)

const shot = (id: string, over: Partial<Shot> = {}): Shot => ({
  id, duration_sec: 3, shot_size: 'medium', action: `${id} 的画面`,
  source: { unit_refs: [], derivation: 'explicit' }, ...over,
})
const s1 = shot('E01-SH001', { shot_size: 'extreme_wide', camera: { movement: 'static', angle: 'high' } })
const s2 = shot('E01-SH002', { shot_size: 'close_up', camera: { movement: 'push_in', angle: 'low' } })
const s3 = shot('E01-SH003')
const s4 = shot('E01-SH004', { shot_size: 'wide', camera: { movement: 'pan' } })
const doc = {
  episodes: [
    { id: 'E01', title: '第一集', shots: [s1, s2, s3, s4] },
    { id: 'E02', shots: [shot('E02-SH001'), shot('E02-SH002')] },
  ],
} as unknown as Storyboard

const clip = (id: string, shots: string[], over: Partial<FilmClip> = {}): FilmClip => ({
  id, episode: 'E01', shots, duration: 8, truncated: false, prompt: `${id} 的提示词`, refs: [], dropped_refs: [],
  missing_refs: [], first_frame: null, frame_mode: null, fingerprint: 'fp', estimate_cny: 8,
  attempts: [], chosen: null, mute_native: false, uncertain: false, error: null, state: 'planned', ...over,
})
const session = (clips: FilmClip[]): FilmSession => ({
  provider: 'fake', model: 'fake-1', resolution: '720p', audio_mode: 'tts_all', budget_cny: 200,
  confirm_over_cny: 20, spent_cny: 0, clips, orphaned: [], counts: {}, reserved_cny: 0, uncertain_count: 0,
  remaining_cny: 0,
  options: { providers: ['fake'], models: {}, resolutions: ['720p'], cny_per_sec: {}, max_clip_sec: 10,
             max_refs: 3, audio_modes: ['tts_all'], rate_note: '' },
} as unknown as FilmSession)

const spans = (doc_: Storyboard, film: FilmSession | null) =>
  sheetGroups(doc_, film).map((g) => g.rows.map((r) => r.span))
const clips = (doc_: Storyboard, film: FilmSession | null) =>
  sheetGroups(doc_, film).map((g) => g.rows.map((r) => r.clip?.id ?? null))

// 1. 没有出片会话：每集一组、每镜一行，整集并成一格「未规划」
{
  const g = sheetGroups(doc, null)
  eq(g.map((x) => x.ep.id), ['E01', 'E02'], '每集一组')
  eq(g.map((x) => x.rows.map((r) => r.shot.id)),
     [['E01-SH001', 'E01-SH002', 'E01-SH003', 'E01-SH004'], ['E02-SH001', 'E02-SH002']], '每镜一行，顺序不变')
  eq(spans(doc, null), [[4, 0, 0, 0], [2, 0]], '没有会话时每集一格')
  eq(clips(doc, null), [[null, null, null, null], [null, null]], '没有会话时都没有段')
  eq(spans(doc, undefined as unknown as null), [[4, 0, 0, 0], [2, 0]], 'undefined 等同没有会话')
  console.log('1. 没有出片会话 ✓')
}

// 2. 有会话：同段相邻的镜头合并；未规划的相邻镜头也合并；合并不跨集
{
  const film = session([clip('E01-C01', ['E01-SH001', 'E01-SH002']), clip('E01-C02', ['E01-SH003'])])
  eq(spans(doc, film), [[2, 0, 1, 1], [2, 0]], '同段相邻合并')
  eq(clips(doc, film), [['E01-C01', 'E01-C01', 'E01-C02', null], [null, null]], '每镜所在的段')
  const tail = session([clip('E01-C01', ['E01-SH004', 'E02-SH001'])])
  eq(spans(doc, tail), [[3, 0, 0, 1], [1, 1]], '同一段跨集时两集各成一格')
  console.log('2. 合并提示词格 ✓')
}

// 3. 同一段的镜头不相邻：各自成格
{
  const film = session([clip('E01-C01', ['E01-SH001', 'E01-SH003']), clip('E01-C02', ['E01-SH002'])])
  eq(spans(doc, film), [[1, 1, 1, 1], [2, 0]], '不相邻不合并')
  eq(clips(doc, film)[0], ['E01-C01', 'E01-C02', 'E01-C01', null], '段照旧对上')
  console.log('3. 不相邻不合并 ✓')
}

// 4. 一镜出现在两段里取第一段；没有集的分镜是空表
{
  const film = session([clip('E01-C01', ['E01-SH001']), clip('E01-C02', ['E01-SH001', 'E01-SH002'])])
  eq(clips(doc, film)[0], ['E01-C01', 'E01-C02', null, null], '取第一段')
  eq(sheetGroups({} as unknown as Storyboard, film), [], '没有集')
  console.log('4. 重复与空 ✓')
}

// 5. 运镜文字与镜头小标签（中文）
{
  eq(shortShotId('E01-SH003'), 'SH003', '短镜号')
  eq(shortShotId('s1'), 's1', '没有 - 原样')
  eq(cameraText(s1), '固定 / 俯拍', '运镜 / 角度')
  eq(cameraText(s4), '摇', '只有运镜')
  eq(cameraText(shot('x', { camera: { angle: 'pov' } })), '主观视角', '只有角度')
  eq(cameraText(s3), '', '没有 camera 为空串')
  eq(shotTag(s2), 'SH002 特写·推', '景别·运镜')
  eq(shotTag(s3), 'SH003 中景', '没有运镜只写景别')
  eq(shotTag(shot('E01-SH009', { shot_size: 'weird' as never })), 'SH009 weird', '不认识的枚举原样显示')
  const byId = shotsById(doc)
  eq(byId.size, 6, '镜头索引')
  eq(shotsById({} as unknown as Storyboard).size, 0, '没有集时索引为空')
  eq(clipShotTags(['E01-SH001', 'E01-SH099', 'E01-SH004'], byId), ['SH001 大远景·固定', 'SH099', 'SH004 远景·摇'],
     '找不到的镜头只写短镜号')
  eq(clipShotTags([], byId), [], '空段')
  console.log('5. 运镜文字与小标签 ✓')
}

// 6. 折叠
{
  eq(foldTags(['a', 'b', 'c']), { shown: ['a', 'b', 'c'], more: 0 }, '恰好 3 个不折叠')
  eq(foldTags(['a', 'b', 'c', 'd', 'e']), { shown: ['a', 'b', 'c'], more: 2 }, '5 个折叠成 +2')
  eq(foldTags([]), { shown: [], more: 0 }, '空')
  must(!needsFold('字'.repeat(60)) && needsFold('字'.repeat(61)), '超过 60 字要展开按钮')
  must(!needsFold('a\nb\nc') && needsFold('a\nb\nc\nd'), '超过 3 行要展开按钮')
  console.log('6. 折叠 ✓')
}

// 7. 英文
{
  setCurrentLocale('en')
  eq(cameraText(s1), 'Static / High angle', '英文运镜 / 角度')
  eq(shotTag(s2), 'SH002 Close-up·Push in', '英文小标签')
  setCurrentLocale('zh')
  eq(shotTag(s2), 'SH002 特写·推', '切回中文')
  console.log('7. 英文 ✓')
}

console.log('\nALL PASS')
```

- [ ] **Step 2: 跑测试，确认失败**

在 `frontend/` 下运行：

```bash
npx vite build --ssr tests/shot-sheet.test.ts --outDir .ssrout --logLevel error && node .ssrout/shot-sheet.test.js
```

Expected: 构建失败，报找不到 `../src/shotSheet`（Could not resolve "../src/shotSheet"），退出码非 0。

- [ ] **Step 3: 写实现**

新建 `frontend/src/shotSheet.ts`，内容：

```ts
/** 拉片表与片段卡镜头标签的纯计算：按集分组、提示词格的合并行数、运镜文字、镜头小标签。
 *  不依赖 React；单测见 tests/shot-sheet.test.ts（设计 docs/specs/2026-11-17-shot-breakdown-sheet-design.md）。 */
import { CAMERA_ANGLE, CAMERA_MOVEMENT, SHOT_SIZE, label } from './labels'
import type { Episode, FilmClip, FilmSession, Shot, Storyboard } from './types'

export interface SheetRow {
  shot: Shot
  /** 这一镜所在的出片段；没有出片规划为 null */
  clip: FilmClip | null
  /** 提示词格占几行；0 = 并进上面那一格，这一行不渲染提示词格 */
  span: number
}
export interface SheetGroup { ep: Episode; rows: SheetRow[] }

/** 每集一组、每镜一行；同一集内相邻且同属一段（或同为未规划）的镜头合并提示词格 */
export function sheetGroups(doc: Storyboard, film: FilmSession | null | undefined): SheetGroup[] {
  // 一镜出现在多段里时取第一段（与 shotFocus.clipForShot 一致）
  const byShot = new Map<string, FilmClip>()
  for (const c of film?.clips ?? []) for (const id of c.shots) if (!byShot.has(id)) byShot.set(id, c)
  return (doc.episodes ?? []).map((ep) => {
    const rows: SheetRow[] = []
    let head: SheetRow | null = null
    for (const shot of ep.shots ?? []) {
      const clip = byShot.get(shot.id) ?? null
      if (head && head.clip === clip) {
        head.span += 1
        rows.push({ shot, clip, span: 0 })
      } else {
        head = { shot, clip, span: 1 }
        rows.push(head)
      }
    }
    return { ep, rows }
  })
}

/** 「推 / 仰拍」；只有其一就只写其一，都没有为空串 */
export function cameraText(shot: Shot): string {
  return [label(CAMERA_MOVEMENT, shot.camera?.movement), label(CAMERA_ANGLE, shot.camera?.angle)]
    .filter(Boolean).join(' / ')
}

/** E01-SH003 → SH003；没有 - 就原样 */
export const shortShotId = (id: string) => id.slice(id.lastIndexOf('-') + 1)

/** 片段卡上的镜头小标签：「SH003 特写·推」 */
export function shotTag(shot: Shot): string {
  const spec = [label(SHOT_SIZE, shot.shot_size), label(CAMERA_MOVEMENT, shot.camera?.movement)]
    .filter(Boolean).join('·')
  return spec ? `${shortShotId(shot.id)} ${spec}` : shortShotId(shot.id)
}

export function shotsById(doc: Storyboard): Map<string, Shot> {
  const out = new Map<string, Shot>()
  for (const ep of doc.episodes ?? []) for (const s of ep.shots ?? []) out.set(s.id, s)
  return out
}

/** 一段里每个镜头的小标签；分镜里找不到的镜头只写短镜号 */
export function clipShotTags(shotIds: string[], byId: Map<string, Shot>): string[] {
  return shotIds.map((id) => {
    const s = byId.get(id)
    return s ? shotTag(s) : shortShotId(id)
  })
}

export const TAG_MAX = 3

/** 最多显示 max 个，其余折叠成 +more */
export function foldTags(tags: string[], max = TAG_MAX): { shown: string[]; more: number } {
  return { shown: tags.slice(0, max), more: Math.max(0, tags.length - max) }
}

export const PROMPT_FOLD_CHARS = 60

/** 提示词要不要「展开」按钮：超过 60 字或超过 3 行（不量 DOM，测试环境没有布局） */
export function needsFold(text: string): boolean {
  return text.length > PROMPT_FOLD_CHARS || text.split('\n').length > 3
}
```

- [ ] **Step 4: 跑测试，确认通过**

```bash
npx vite build --ssr tests/shot-sheet.test.ts --outDir .ssrout --logLevel error && node .ssrout/shot-sheet.test.js
```

Expected: 依次打印 `1. 没有出片会话 ✓` 到 `7. 英文 ✓`，最后 `ALL PASS`，退出码 0。

- [ ] **Step 5: 把新测试接进 `npm test`**

编辑 `frontend/package.json`，在 `scripts.test` 那一行的末尾，把

```
&& node .ssrout/assistant.test.js"
```

改成

```
&& node .ssrout/assistant.test.js && vite build --ssr tests/shot-sheet.test.ts --outDir .ssrout --logLevel error && node .ssrout/shot-sheet.test.js"
```

（只动这一行末尾，其余不变。）

- [ ] **Step 6: 全量检查**

在 `frontend/` 下运行：

```bash
npm test && npm run lint && npm run build
```

Expected: `npm test` 最后一段是 shot-sheet 的 `ALL PASS`，退出码 0；lint 0 error、5 条警告；build 成功。

- [ ] **Step 7: 提交**

在仓库根目录运行：

```bash
git add frontend/src/shotSheet.ts frontend/tests/shot-sheet.test.ts frontend/package.json
git commit -m "拉片表的纯计算 shotSheet.ts：按集分组、同集相邻同段镜头合并提示词格（未规划的相邻镜头也合并）、运镜 / 角度文字、片段卡镜头小标签与超过 3 个的折叠、提示词是否需要展开按钮；补单测并接进 npm test"
```

---

### Task 2: 拉片表组件 `ShotSheet`（含文案与样式）

组件单独可渲染、可测；这一步还不接进页签（Task 3 做）。对应 §3.2 到 §3.7。

**Files:**
- Create: `frontend/tests/sheet-view.test.tsx`
- Create: `frontend/src/components/ShotSheet.tsx`
- Modify: `frontend/src/i18n/zh.ts`（`board.tabs` 那一行）
- Modify: `frontend/src/i18n/en.ts`（`board.tabs` 那一行）
- Modify: `frontend/src/styles/storyboard.css`（文件末尾追加）
- Modify: `frontend/package.json`（`scripts.test` 末尾）

- [ ] **Step 1: 写失败的测试**

新建 `frontend/tests/sheet-view.test.tsx`，内容：

```tsx
/** 拉片表的界面回归：每镜一行、按集分组；各列文字；视频提示词按片段合并单元格；
 *  无关键帧与无出片规划的占位；提示词展开 / 收起；点行跳转；中英文。
 *  分组与合并的纯计算由 shot-sheet.test.ts 覆盖。跑法：npm test
 */
import { Window } from 'happy-dom'

const win = new Window({ url: 'http://localhost:5173' })
const g = globalThis as Record<string, unknown>
for (const k of ['window', 'document', 'navigator', 'location', 'HTMLElement',
                 'Element', 'Node', 'Event', 'CustomEvent', 'KeyboardEvent', 'getComputedStyle',
                 'localStorage', 'sessionStorage', 'PointerEvent', 'MouseEvent', 'matchMedia', 'ResizeObserver', 'DOMRect',
                 'MutationObserver']) {
  Object.defineProperty(g, k, {
    value: (win as unknown as Record<string, unknown>)[k],
    writable: true, configurable: true,
  })
}
g.IS_REACT_ACT_ENVIRONMENT = true
g.requestAnimationFrame = (cb: (t: number) => void) =>
  setTimeout(() => cb(performance.now()), 16) as unknown as number
g.cancelAnimationFrame = (id: number) => clearTimeout(id)

import type { FilmClip, FilmSession, Shot, Storyboard } from '../src/types'

/* ---------- 夹具：两集六镜，E01 的前三镜有出片规划 ---------- */
const shot = (id: string, over: Partial<Shot> = {}): Shot => ({
  id, duration_sec: 3, shot_size: 'medium', action: `${id} 的画面`,
  source: { unit_refs: [], derivation: 'explicit' }, ...over,
})
const doc = {
  meta: { schema_version: '0.5', title: '药', fidelity_mode: 'faithful', style: { style_prefix: '' },
          video: { aspect_ratio: '16:9' }, narration: { mode: 'narrated' } },
  source: { work_title: '药', units: [] },
  assets: { characters: [{ id: 'C01', name: '老栓' }, { id: 'C02', name: '华大妈' }] },
  episodes: [
    { id: 'E01', title: '黎明', shots: [
      shot('E01-SH001', { duration_sec: 5, shot_size: 'extreme_wide', camera: { movement: 'static', angle: 'high' },
                          action: '乌蓝的天色下，丁字街空无一人', atmosphere: '万籁俱寂',
                          narration: { text: '秋天的后半夜，月亮下去了' } }),
      shot('E01-SH002', { duration_sec: 3.5, shot_size: 'close_up', camera: { movement: 'push_in', angle: 'low' },
                          action: '老栓接过洋钱',
                          dialogue: [{ type: 'dialogue', text: '小栓的爹，你就去么？', character_ref: 'C02' },
                                     { type: 'inner_monologue', text: '这给谁治病的呀', character_ref: 'C01' }] }),
      shot('E01-SH003', { duration_sec: 4, action: '老栓走上大街' }),
      shot('E01-SH004', { duration_sec: 2, shot_size: 'wide', camera: { movement: 'pan' }, action: '街上黑沉沉的' }),
    ] },
    { id: 'E02', shots: [
      shot('E02-SH001', { duration_sec: 6, shot_size: 'full', camera: { movement: 'track', angle: 'eye_level' } }),
      shot('E02-SH002', { shot_size: 'insert', camera: { movement: 'static' } }),
    ] },
  ],
} as unknown as Storyboard

const LONG = '大远景，俯拍，固定机位。乌蓝的天色下，丁字街空无一人，屋脊只剩剪影；'
  + '随后切到特写，仰拍，缓慢推近：老栓接过洋钱，抖抖地装进衣袋，又在外面按了两下。'
const clip = (id: string, shots: string[], over: Partial<FilmClip> = {}): FilmClip => ({
  id, episode: 'E01', shots, duration: 8, truncated: false, prompt: 'p', refs: [], dropped_refs: [],
  missing_refs: [], first_frame: null, frame_mode: null, fingerprint: 'fp', estimate_cny: 8,
  attempts: [], chosen: null, mute_native: false, uncertain: false, error: null, state: 'planned', ...over,
})
const film = {
  provider: 'fake', model: 'fake-1', resolution: '720p', audio_mode: 'tts_all', budget_cny: 200,
  confirm_over_cny: 20, spent_cny: 0, orphaned: [], counts: {}, reserved_cny: 0, uncertain_count: 0, remaining_cny: 0,
  clips: [
    clip('E01-C01', ['E01-SH001', 'E01-SH002'], { duration: 8.5, prompt: LONG }),
    clip('E01-C02', ['E01-SH003'], { duration: 4, prompt: '中景，老栓走上大街' }),
  ],
  options: { providers: ['fake'], models: { 'fake-1': { label: '假厂商' } }, resolutions: ['720p'], cny_per_sec: {},
             max_clip_sec: 10, max_refs: 3, audio_modes: ['tts_all'], rate_note: '假厂商：不联网、不花钱' },
} as unknown as FilmSession

/* ---------- 桩后端：只有 E01-SH001 有关键帧 ---------- */
const K = '/novels/n1/chapters/c1/versions/v1/keyframes'
g.fetch = async (url: string) => {
  const path = String(url).replace(/^\/api/, '')
  if (path === K) return { ok: true, status: 200, json: async () => ({ shots: ['E01-SH001'] }) }
  if (path === `${K}/E01-SH001`) {
    return { ok: true, status: 200, blob: async () => new Blob(['x'], { type: 'image/png' }) }
  }
  throw new Error(`桩后端未实现的路径: ${path}`)
}
const version = { nid: 'n1', cid: 'c1', vid: 'v1' }

const { act } = await import('react')
const { createRoot } = await import('react-dom/client')
const { I18nProvider } = await import('../src/i18n')
const { setCurrentLocale } = await import('../src/i18n/core')
const { buildIndex } = await import('../src/resolve')
const { ShotSheet } = await import('../src/components/ShotSheet')

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }
const container = win.document.createElement('div')
win.document.body.appendChild(container)
const root = createRoot(container as unknown as HTMLElement)
const settle = async (ms = 50) => {
  await act(async () => { await new Promise((r) => setTimeout(r, ms)) })
}
const click = async (el: Element) => {
  await act(async () => {
    el.dispatchEvent(new win.MouseEvent('click', { bubbles: true }) as unknown as Event)
  })
  await settle()
}
const qa = (sel: string) => [...container.querySelectorAll(sel)] as unknown as HTMLElement[]
const row = (id: string) => {
  const el = container.querySelector(`tr[data-shot="${id}"]`)
  if (!el) throw new Error(`✗ 拉片表里找不到 ${id}`)
  return el as unknown as HTMLElement
}
/** 这一行第 i 个单元格的文字（0 镜号、1 关键帧、2 景别、3 运镜、4 画面、5 台词、6 提示词） */
const cell = (id: string, i: number) => row(id).querySelectorAll('td')[i]?.textContent ?? ''
const promptCell = (id: string) => row(id).querySelector('td.sheet__promptcell') as unknown as HTMLElement | null

const idx = buildIndex(doc)
const jumps: string[] = []
const sheet = (f: FilmSession | null, v: typeof version | null = version) =>
  <ShotSheet doc={doc} idx={idx} film={f} version={v} imagesKey={0} onJump={(id) => jumps.push(id)} />

// 1. 行数与分组：每镜一行，每集一个标题行（集号、标题、镜头数）
await act(async () => { root.render(sheet(film)) })
await settle()
must(qa('tr[data-shot]').length === 6, `每镜一行：${qa('tr[data-shot]').length}`)
must(qa('tr[data-shot]').map((r) => r.getAttribute('data-shot')).join() ===
     'E01-SH001,E01-SH002,E01-SH003,E01-SH004,E02-SH001,E02-SH002', '行按分镜顺序')
const eps = qa('tr.sheet__ep').map((r) => r.textContent ?? '')
must(eps.length === 2 && eps[0].includes('E01') && eps[0].includes('黎明') && eps[0].includes('4 镜')
     && eps[1].includes('E02') && eps[1].includes('2 镜'), `集标题行：${eps.join(' | ')}`)
must(qa('tbody').length === 2 && qa('tbody')[0].querySelectorAll('tr[data-shot]').length === 4, '每集一个 tbody')
must(qa('thead th').map((x) => x.textContent).join('|') === '镜号|关键帧|景别|运镜 / 角度|画面|台词 / 旁白|视频提示词', '七列表头')
must(container.querySelector('.sheet__wrap')?.getAttribute('aria-label') === '拉片表', '滚动容器有名字')
console.log('1. 行数与分组 ✓')

// 2. 各列文字
must(cell('E01-SH001', 0).includes('E01-SH001') && cell('E01-SH001', 0).includes('5s'), '镜号与时长')
must(cell('E01-SH002', 0).includes('3.5s'), '时长保留一位小数')
must(cell('E01-SH001', 2) === '大远景' && cell('E01-SH001', 3) === '固定 / 俯拍', '景别与运镜 / 角度')
must(cell('E01-SH002', 2) === '特写' && cell('E01-SH002', 3) === '推 / 仰拍', '推 / 仰拍')
must(cell('E01-SH003', 3) === '—' && cell('E01-SH004', 3) === '摇', '没有运镜显示 —，只有运镜只写运镜')
must(cell('E01-SH001', 4).includes('乌蓝的天色下，丁字街空无一人') && cell('E01-SH001', 4).includes('万籁俱寂'), '画面与氛围')
must(!row('E01-SH003').querySelector('.sheet__atmo'), '没有氛围不显示小字')
must(cell('E01-SH001', 5).includes('旁白') && cell('E01-SH001', 5).includes('秋天的后半夜，月亮下去了'), '旁白')
must(cell('E01-SH002', 5).includes('华大妈') && cell('E01-SH002', 5).includes('小栓的爹，你就去么？')
     && cell('E01-SH002', 5).includes('老栓') && cell('E01-SH002', 5).includes('内心独白'), '台词带说话人与类型')
must(row('E01-SH002').querySelectorAll('.chip').length === 1, '普通台词不带类型标签')
must(cell('E01-SH003', 5) === '—', '没有台词与旁白显示 —')
console.log('2. 各列文字 ✓')

// 3. 视频提示词：同段相邻的镜头合并；未规划占位；不出现模型与厂商名
must(promptCell('E01-SH001')?.getAttribute('rowspan') === '2', '同段两镜合并成一格')
must(promptCell('E01-SH002') === null, '被合并的行没有提示词格')
must((promptCell('E01-SH001')?.textContent ?? '').includes('E01-C01 · 8.5s')
     && (promptCell('E01-SH001')?.textContent ?? '').includes(LONG), '提示词格有片段号、时长与提示词')
must(promptCell('E01-SH003')?.getAttribute('rowspan') === '1'
     && (promptCell('E01-SH003')?.textContent ?? '').includes('中景，老栓走上大街'), '单镜的段')
must(promptCell('E01-SH004')?.textContent === '未规划', '不在任何段里的镜头显示未规划')
must(promptCell('E02-SH001')?.getAttribute('rowspan') === '2' && promptCell('E02-SH001')?.textContent === '未规划'
     && promptCell('E02-SH002') === null, '整集未规划合并成一格')
must(qa('td.sheet__promptcell').length === 4, '共四个提示词格')
const text = container.textContent ?? ''
must(!text.includes('fake') && !text.includes('假厂商'), '界面不出现模型或厂商名')
console.log('3. 视频提示词合并与未规划 ✓')

// 4. 关键帧：有图的显示图，其余占位
must(!!row('E01-SH001').querySelector('img.sheet__thumb'), '有关键帧的显示缩略图')
must(qa('.sheet__thumb--empty').length === 5 && qa('.sheet__thumb--empty').every((x) => x.textContent === '无图'),
     '没有关键帧的显示「无图」')
console.log('4. 关键帧缩略图与占位 ✓')

// 5. 展开 / 收起：长提示词才有按钮；点它不跳转
must(!promptCell('E01-SH003')?.querySelector('.sheet__more'), '短提示词没有展开按钮')
const more = () => promptCell('E01-SH001')!.querySelector('.sheet__more') as unknown as HTMLButtonElement
must(more().textContent === '展开' && more().getAttribute('aria-expanded') === 'false', '长提示词有展开按钮')
await click(more())
must(promptCell('E01-SH001')!.querySelector('.sheet__prompt')!.classList.contains('is-open')
     && more().textContent === '收起' && more().getAttribute('aria-expanded') === 'true', '点开显示全文')
await click(more())
must(!promptCell('E01-SH001')!.querySelector('.sheet__prompt')!.classList.contains('is-open'), '再点收起')
await click(promptCell('E01-SH001')!)
must(jumps.length === 0, '点提示词格与展开按钮都不跳转')
console.log('5. 展开与收起 ✓')

// 6. 点行跳转：点单元格、点镜号按钮都只报一次这一镜
await click(row('E01-SH003').querySelectorAll('td')[4])
must(jumps.join() === 'E01-SH003', `点行跳到这一镜：${jumps.join()}`)
await click(row('E01-SH002').querySelector('button.sheet__id')!)
must(jumps.join() === 'E01-SH003,E01-SH002', `点镜号按钮只报一次：${jumps.join()}`)
console.log('6. 点行跳转 ✓')

// 7. 没有出片会话、没有版本：每集一格未规划，全部无图
await act(async () => { root.render(sheet(null, null)) })
await settle()
must(qa('td.sheet__promptcell').length === 2 && qa('td.sheet__promptcell').every((x) => x.textContent === '未规划'),
     '没有会话时每集一格未规划')
must(promptCell('E01-SH001')?.getAttribute('rowspan') === '4', '整集合并')
must(qa('img.sheet__thumb').length === 0 && qa('.sheet__thumb--empty').length === 6, '没有版本时全部无图')
console.log('7. 没有会话与版本 ✓')

// 8. 英文：表头、枚举、占位都是英文；镜头正文原样
await act(async () => { root.render(<I18nProvider initial="en">{sheet(film, null)}</I18nProvider>) })
await settle()
must(qa('thead th').map((x) => x.textContent).join('|')
     === 'Shot|Keyframe|Size|Movement / Angle|Action|Lines / Narration|Video prompt', '英文表头')
must(cell('E01-SH001', 2) === 'Extreme wide' && cell('E01-SH001', 3) === 'Static / High angle', '英文景别与运镜')
must(promptCell('E01-SH004')?.textContent === 'Not planned', '英文未规划')
must(qa('.sheet__thumb--empty')[0].textContent === 'No image', '英文无图')
must(more().textContent === 'Show more', '英文展开')
must(cell('E01-SH001', 5).includes('Narration') && cell('E01-SH002', 5).includes('Inner monologue'), '英文旁白与台词类型')
must((qa('tr.sheet__ep')[0].textContent ?? '').includes('Shots: 4'), '英文镜头数')
must(!/[一-鿿]/.test(container.querySelector('thead')?.textContent ?? ''), '表头无中文')
must(cell('E01-SH001', 4).includes('乌蓝的天色下'), '镜头正文原样')
await act(async () => { root.render(sheet(film, null)) })
setCurrentLocale('zh')
console.log('8. 英文 ✓')

await act(async () => { root.unmount() })
console.log('\nALL PASS')
```

说明：
- 夹具是两集六镜，出片会话只规划了 E01 的前三镜（`E01-C01` 含两镜、提示词超过 60 字；`E01-C02` 含一镜、提示词很短）。
- 桩后端只回答关键帧清单与 `E01-SH001` 那一张图；其他路径抛错，所以组件不能多发请求。
- 会话里故意带了 `fake`、`假厂商` 字样，用例 3 断言它们不出现在界面上。

- [ ] **Step 2: 跑测试，确认失败**

在 `frontend/` 下运行：

```bash
npx vite build --ssr tests/sheet-view.test.tsx --outDir .ssrout --logLevel error && node .ssrout/sheet-view.test.js
```

Expected: 构建失败，报找不到 `../src/components/ShotSheet`，退出码非 0。

- [ ] **Step 3: 加中文文案**

编辑 `frontend/src/i18n/zh.ts`，把这一行（在 `board:` 里，全文件唯一）

```ts
    tabs: { focus: '镜头', cards: '卡片', assets: '资产', source: '原文', render: '渲染', json: 'JSON' },
```

替换成

```ts
    tabs: { focus: '镜头', cards: '卡片', sheet: '拉片表', assets: '资产', source: '原文', render: '渲染', json: 'JSON' },
    sheet: {
      aria: '拉片表',
      col: {
        shot: '镜号', frame: '关键帧', size: '景别', camera: '运镜 / 角度', action: '画面', voice: '台词 / 旁白',
        prompt: '视频提示词',
      },
      noFrame: '无图',
      unplanned: '未规划',
      more: '展开',
      less: '收起',
      jump: '在镜头视图中打开',
    },
```

- [ ] **Step 4: 加英文文案**

编辑 `frontend/src/i18n/en.ts`，把这一行（全文件唯一）

```ts
    tabs: { focus: 'Shots', cards: 'Cards', assets: 'Assets', source: 'Source', render: 'Render', json: 'JSON' },
```

替换成

```ts
    tabs: { focus: 'Shots', cards: 'Cards', sheet: 'Breakdown', assets: 'Assets', source: 'Source', render: 'Render', json: 'JSON' },
    sheet: {
      aria: 'Shot breakdown',
      col: {
        shot: 'Shot', frame: 'Keyframe', size: 'Size', camera: 'Movement / Angle', action: 'Action',
        voice: 'Lines / Narration', prompt: 'Video prompt',
      },
      noFrame: 'No image',
      unplanned: 'Not planned',
      more: 'Show more',
      less: 'Show less',
      jump: 'Open in Shots view',
    },
```

说明：`board.tabs.sheet` 这一步就加上，页签本身到 Task 3 才出现（`StoryboardView` 的 `TABS` 还没有 `'sheet'`），所以现有测试不受影响。集标题行的镜头数与旁白前缀复用现成的 `board.ep.count`、`shot.narrator`，不新增。

- [ ] **Step 5: 写组件**

新建 `frontend/src/components/ShotSheet.tsx`，内容：

```tsx
/** 拉片表：每镜一行、按集分组的只读总表（设计 docs/specs/2026-11-17-shot-breakdown-sheet-design.md §3）。
 *  列：镜号与时长、关键帧、景别、运镜 / 角度、画面、台词 / 旁白、视频提示词。
 *  视频提示词取出片会话里这一镜所在的段，同一集内相邻的同段镜头合并成一格；点行跳到镜头视图。
 *  分组与合并的计算在 shotSheet.ts；关键帧图与镜头视图共用 useShotImages（只读已上传的图）。 */
import { useMemo, useState } from 'react'
import { useI18n } from '@/i18n/core'
import { cn } from '@/lib/utils'
import { DIALOGUE_TYPE, label, SHOT_SIZE } from '../labels'
import type { Index } from '../resolve'
import { cameraText, needsFold, sheetGroups } from '../shotSheet'
import type { FilmSession, Storyboard, VersionRef } from '../types'
import { useShotImages } from '../useShotImages'

interface Props {
  doc: Storyboard
  idx: Index
  /** 出片会话：没有时提示词列显示「未规划」 */
  film?: FilmSession | null
  /** 产物所属的章节版本：取关键帧图用；没有就都显示「无图」 */
  version?: VersionRef | null
  /** 变了就重取关键帧图（画布关上时） */
  imagesKey?: unknown
  /** 点一行：跳到镜头视图并选中这一镜 */
  onJump: (shotId: string) => void
}

const COLS = ['shot', 'frame', 'size', 'camera', 'action', 'voice', 'prompt'] as const
const DASH = '—'
const sec = (n: unknown) => (typeof n === 'number' ? `${Number(n.toFixed(1))}s` : '')

export function ShotSheet({ doc, idx, film = null, version = null, imagesKey, onJump }: Props) {
  const { t } = useI18n()
  const groups = useMemo(() => sheetGroups(doc, film), [doc, film])
  const urls = useShotImages(version, imagesKey)
  /** 展开了提示词的段 */
  const [open, setOpen] = useState<Set<string>>(new Set())
  const toggle = (clipId: string) => setOpen((prev) => {
    const next = new Set(prev)
    if (next.has(clipId)) next.delete(clipId); else next.add(clipId)
    return next
  })
  const [w, h] = (doc.meta?.video?.aspect_ratio ?? '16:9').split(':').map(Number)
  const thumb = {
    className: cn('sheet__thumb', h > w && 'sheet__thumb--tall'),
    style: { aspectRatio: w > 0 && h > 0 ? `${w} / ${h}` : '16 / 9' },
  }

  return (
    <div className="sheet">
      <div className="sheet__wrap" role="region" aria-label={t('board.sheet.aria')} tabIndex={0}>
        <table className="sheet__table">
          <thead>
            <tr>
              {COLS.map((c) => (
                <th key={c} scope="col" className={`sheet__col-${c}`}>{t(`board.sheet.col.${c}`)}</th>
              ))}
            </tr>
          </thead>
          {groups.map(({ ep, rows }) => (
            <tbody key={ep.id}>
              <tr className="sheet__ep">
                <th colSpan={COLS.length} scope="rowgroup">
                  <span className="sheet__ep-id">{ep.id}</span>
                  {ep.title && <span className="sheet__ep-title">{ep.title}</span>}
                  <span className="sheet__ep-n">{t('board.ep.count', { n: rows.length })}</span>
                </th>
              </tr>
              {rows.map(({ shot: s, clip, span }) => {
                const voiced = !!s.dialogue?.length || !!s.narration?.text
                const opened = !!clip && open.has(clip.id)
                return (
                  <tr key={s.id} className="sheet__row" data-shot={s.id} onClick={() => onJump(s.id)}>
                    <td>
                      {/* 点击冒泡到行上；按钮只为了键盘能聚焦、回车能跳 */}
                      <button type="button" className="sheet__id" title={t('board.sheet.jump')}>{s.id}</button>
                      <span className="sheet__dur">{sec(s.duration_sec)}</span>
                    </td>
                    <td>
                      {urls[s.id]
                        ? <img {...thumb} src={urls[s.id]} alt="" />
                        : <span {...thumb} className={cn(thumb.className, 'sheet__thumb--empty')}>{t('board.sheet.noFrame')}</span>}
                    </td>
                    <td>{label(SHOT_SIZE, s.shot_size) || DASH}</td>
                    <td>{cameraText(s) || DASH}</td>
                    <td>
                      <p className="sheet__action">{s.action}</p>
                      {s.atmosphere && <p className="sheet__atmo">{s.atmosphere}</p>}
                    </td>
                    <td>
                      {(s.dialogue ?? []).map((d, i) => (
                        <p key={i} className="sheet__line">
                          {d.character_ref && <b>{idx.assetName(d.character_ref)}</b>}
                          {d.type && d.type !== 'dialogue' && <span className="chip">{label(DIALOGUE_TYPE, d.type)}</span>}
                          <span>{d.text}</span>
                        </p>
                      ))}
                      {s.narration?.text && (
                        <p className="sheet__line sheet__line--nar">
                          <b>{t('shot.narrator')}</b>
                          <span>{s.narration.text}</span>
                        </p>
                      )}
                      {!voiced && DASH}
                    </td>
                    {span > 0 && (
                      // 提示词格可能跨几镜，点它跳哪一镜有歧义：不参与跳转
                      <td className="sheet__promptcell" rowSpan={span} onClick={(e) => e.stopPropagation()}>
                        {clip ? (
                          <>
                            <p className="sheet__clip">{clip.id} · {sec(clip.duration)}</p>
                            <p className={cn('sheet__prompt', opened && 'is-open')}>{clip.prompt}</p>
                            {needsFold(clip.prompt) && (
                              <button type="button" className="sheet__more" aria-expanded={opened}
                                      onClick={() => toggle(clip.id)}>
                                {t(opened ? 'board.sheet.less' : 'board.sheet.more')}
                              </button>
                            )}
                          </>
                        ) : <span className="sheet__none">{t('board.sheet.unplanned')}</span>}
                      </td>
                    )}
                  </tr>
                )
              })}
            </tbody>
          ))}
        </table>
      </div>
    </div>
  )
}
```

- [ ] **Step 6: 加样式**

在 `frontend/src/styles/storyboard.css` **文件末尾**追加（前面空一行）：

```css
/* ---------- 拉片表（ShotSheet.tsx）：每镜一行的只读总表 ----------
 * 窄屏时表格在 .sheet__wrap 里横向滚动，页面本身不滚；表头在容器内吸顶。 */
.sheet { min-width: 0; padding: 16px 20px 20px; }
.sheet__wrap {
  max-width: 100%;
  max-height: calc(100vh - 96px);
  overflow: auto;
  border: 1px solid var(--border);
  border-radius: var(--ui-radius);
  background: var(--card);
}
.sheet__table { width: 100%; min-width: 1080px; border-collapse: separate; border-spacing: 0; font-size: 13px; line-height: 1.6; }
.sheet__table th, .sheet__table td { padding: 8px 10px; border-bottom: 1px solid var(--border); text-align: left; vertical-align: top; }
.sheet__table thead th {
  position: sticky; top: 0; z-index: 1;
  background: var(--ui-muted); color: var(--ui-muted-foreground);
  font-size: 12px; font-weight: 500; white-space: nowrap;
}
.sheet__col-shot { width: 108px; }
.sheet__col-frame { width: 116px; }
.sheet__col-size { width: 88px; }
.sheet__col-camera { width: 124px; }
.sheet__col-voice { width: 22%; }
.sheet__col-prompt { width: 280px; }
.sheet__ep th { background: var(--background); font-weight: 600; }
.sheet__ep th > span + span { margin-left: 10px; }
.sheet__ep-id { font-family: var(--font-mono); font-variant-numeric: tabular-nums; }
.sheet__ep-n { font-size: 12px; font-weight: 400; color: var(--ui-muted-foreground); }
.sheet__row { cursor: pointer; }
.sheet__row:hover > td:not(.sheet__promptcell) { background: var(--ui-muted); }
.sheet__id {
  display: block; border: 0; padding: 0; background: none; color: inherit; cursor: pointer;
  font-family: var(--font-mono); font-variant-numeric: tabular-nums; font-size: 12px; white-space: nowrap;
}
.sheet__id:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; border-radius: 4px; }
.sheet__dur, .sheet__clip {
  font-family: var(--font-mono); font-variant-numeric: tabular-nums; font-size: 12px; color: var(--ui-muted-foreground);
}
.sheet__thumb { display: block; width: 96px; border-radius: 4px; object-fit: cover; background: var(--ui-muted); }
.sheet__thumb--tall { width: 54px; }
.sheet__thumb--empty { display: grid; place-items: center; font-size: 11px; color: var(--ui-muted-foreground); }
.sheet__action, .sheet__atmo, .sheet__line, .sheet__clip, .sheet__prompt { margin: 0; overflow-wrap: anywhere; }
.sheet__atmo { margin-top: 2px; font-size: 12px; color: var(--ui-muted-foreground); }
.sheet__line + .sheet__line { margin-top: 4px; }
.sheet__line > b { margin-right: 6px; font-weight: 600; }
.sheet__line > .chip { margin-right: 6px; vertical-align: middle; }
.sheet__line--nar > b { font-size: 12px; font-weight: 500; color: var(--ui-muted-foreground); }
.sheet__promptcell { cursor: default; border-left: 1px solid var(--border); }
.sheet__prompt {
  display: -webkit-box; overflow: hidden; -webkit-line-clamp: 3; -webkit-box-orient: vertical;
  font-size: 12px; white-space: pre-wrap;
}
.sheet__prompt.is-open { display: block; overflow: visible; -webkit-line-clamp: unset; }
.sheet__more {
  margin-top: 4px; border: 0; padding: 0; background: none; cursor: pointer;
  font-size: 12px; color: var(--primary);
}
.sheet__more:hover { text-decoration: underline; }
.sheet__none { font-size: 12px; color: var(--ui-muted-foreground); }
```

- [ ] **Step 7: 跑测试，确认通过**

```bash
npx vite build --ssr tests/sheet-view.test.tsx --outDir .ssrout --logLevel error && node .ssrout/sheet-view.test.js
```

Expected: 依次打印 `1. 行数与分组 ✓` 到 `8. 英文 ✓`，最后 `ALL PASS`，退出码 0。

- [ ] **Step 8: 把新测试接进 `npm test`**

编辑 `frontend/package.json`，在 `scripts.test` 那一行的末尾，把

```
&& node .ssrout/shot-sheet.test.js"
```

改成

```
&& node .ssrout/shot-sheet.test.js && vite build --ssr tests/sheet-view.test.tsx --outDir .ssrout --logLevel error && node .ssrout/sheet-view.test.js"
```

- [ ] **Step 9: 全量检查**

在 `frontend/` 下运行：

```bash
npm test && npm run lint && npm run build
```

Expected: `npm test` 退出码 0，最后一段是 sheet-view 的 `ALL PASS`；lint 0 error、5 条警告；build 成功。

- [ ] **Step 10: 提交**

在仓库根目录运行：

```bash
git add frontend/src/components/ShotSheet.tsx frontend/tests/sheet-view.test.tsx frontend/src/i18n/zh.ts frontend/src/i18n/en.ts frontend/src/styles/storyboard.css frontend/package.json
git commit -m "拉片表组件 ShotSheet：每镜一行、按集分组，列出镜号与时长、关键帧缩略图、景别、运镜 / 角度、画面与氛围、台词 / 旁白、所在片段的视频提示词（同段相邻镜头合并单元格，默认截 3 行可展开，没有规划显示未规划）；点行回报镜头 id；补中英文案、样式与界面测试，暂未接进页签"
```

---

### Task 3: 接进页签与地址

`StoryboardView` 的页签加「拉片表」，地址 `?tab=sheet`，点行跳到镜头视图。对应 §3.1、§3.6。

**Files:**
- Modify: `frontend/tests/paths.test.ts`
- Modify: `frontend/tests/sheet-view.test.tsx`（文件末尾）
- Modify: `frontend/tests/chapter.test.tsx`（一行）
- Modify: `frontend/tests/real-doc.test.tsx`（一行）
- Modify: `frontend/src/components/StoryboardView.tsx`
- Modify: `frontend/src/paths.ts`（一行）

- [ ] **Step 1: 写失败的测试（地址）**

编辑 `frontend/tests/paths.test.ts`。

把这一行

```ts
console.log('3. 章节、步骤、页签、画布 ✓')
```

替换成

```ts
eq(ch('/novels/n1/chapters/c1/review', '?tab=sheet'),
   { loc: { kind: 'chapter', nid: 'n1', cid: 'c1', step: 'review', tab: 'sheet', canvas: false, view: 'timeline' }, fix: null }, '拉片表页签')
eq(ch('/novels/n1/chapters/c1/import', '?tab=sheet').fix, '/novels/n1/chapters/c1/import', '拉片表页签也只在 review/render/compose 有意义')
console.log('3. 章节、步骤、页签、画布 ✓')
```

再把这一行

```ts
console.log('4. 拼地址 ✓')
```

替换成

```ts
eq(chapterPath('n1', 'c1', { step: 'render', tab: 'sheet' }), '/novels/n1/chapters/c1/render?tab=sheet', '拉片表页签写进地址')
console.log('4. 拼地址 ✓')
```

- [ ] **Step 2: 写失败的测试（接进分镜视图）**

编辑 `frontend/tests/sheet-view.test.tsx`。文件最后两行现在是

```tsx
await act(async () => { root.unmount() })
console.log('\nALL PASS')
```

在这两行**之间**插入下面这一整块（即保留 `await act(async () => { root.unmount() })`，后面空一行接这一块，再空一行接 `console.log('\nALL PASS')`）：

```tsx
/* ---------- 接进分镜视图：页签、跳到镜头视图 ---------- */
{
  const { StoryboardView } = await import('../src/components/StoryboardView')
  const box = win.document.createElement('div')
  win.document.body.appendChild(box)
  const q = (sel: string) => [...box.querySelectorAll(sel)] as unknown as HTMLElement[]
  const tabOn = () => q('.tabs__btn').find((b) => b.getAttribute('aria-pressed') === 'true')?.textContent
  const base = { doc, canSave: false, dirty: false, saving: false, film, version, onChange: () => {}, onSave: () => {} }

  // 9. 非受控：页签顺序；点「拉片表」显示表；点行回到镜头视图并选中这一镜
  const root1 = createRoot(box as unknown as HTMLElement)
  await act(async () => { root1.render(<StoryboardView {...base} />) })
  await settle()
  must(q('.tabs__btn').map((b) => b.textContent).join(' ') === '镜头 卡片 拉片表 资产 原文 渲染 JSON', '拉片表在卡片与资产之间')
  must(q('.sheet').length === 0 && q('.focus').length === 1, '默认还是镜头视图')
  await click(q('.tabs__btn').find((b) => b.textContent === '拉片表')!)
  must(tabOn() === '拉片表' && q('tr[data-shot]').length === 6 && q('.focus').length === 0, '点页签显示拉片表')
  must(!!box.querySelector('tr[data-shot="E01-SH001"] img.sheet__thumb'), '拉片表里取到关键帧图')
  must((box.querySelector('tr[data-shot="E01-SH001"] td.sheet__promptcell')?.textContent ?? '').includes('E01-C01'),
       '出片会话传进了拉片表')
  await click(box.querySelector('tr[data-shot="E01-SH003"]')!)
  must(tabOn() === '镜头' && q('.sheet').length === 0 && q('.focus').length === 1, '点行回到镜头视图')
  must(box.querySelector('.focus__item[aria-selected="true"]')?.getAttribute('data-shot') === 'E01-SH003',
       '镜头视图选中这一镜')
  await act(async () => { root1.unmount() })
  console.log('9. 页签与跳转（非受控） ✓')

  // 10. defaultTab=sheet 一开始就是拉片表；分批预览时也能看
  const root2 = createRoot(box as unknown as HTMLElement)
  await act(async () => { root2.render(<StoryboardView {...base} defaultTab="sheet" preview={{ done: 1, total: 2 }} />) })
  await settle()
  must(tabOn() === '拉片表' && q('tr[data-shot]').length === 6, '预览时拉片表照常显示')
  await act(async () => { root2.unmount() })
  console.log('10. defaultTab 与预览 ✓')

  // 11. 受控：页签由上层给；点行只调用 onJumpShot，页签不自己变
  const tabs: string[] = []
  let jumped = 0
  const root3 = createRoot(box as unknown as HTMLElement)
  await act(async () => {
    root3.render(<StoryboardView {...base} tab="sheet" onTab={(tb) => tabs.push(tb)} onJumpShot={() => { jumped += 1 }} />)
  })
  await settle()
  must(tabOn() === '拉片表' && q('tr[data-shot]').length === 6, '受控时按上层给的页签显示拉片表')
  await click(box.querySelector('tr[data-shot="E01-SH002"]')!)
  must(jumped === 1 && tabs.length === 0 && tabOn() === '拉片表', `受控时只调用 onJumpShot：${jumped} / ${tabs.join()}`)
  await act(async () => { root3.unmount() })
  console.log('11. 跳转（受控） ✓')
}
```

说明：这一块直接渲染 `StoryboardView`，复用文件上面的 `doc`、`film`、`version`、桩后端、`click`、`settle`、`must`。跳到镜头视图后 `ShotFocusView` 也会取关键帧，走的是同一个桩路径。

- [ ] **Step 3: 更新两处页签清单断言**

编辑 `frontend/tests/chapter.test.tsx`，把

```ts
  must(qa('.tabs__btn').map((b) => b.textContent).join(' ') === '镜头 卡片 资产 原文 渲染 JSON', '六个页签')
```

替换成

```ts
  must(qa('.tabs__btn').map((b) => b.textContent).join(' ') === '镜头 卡片 拉片表 资产 原文 渲染 JSON', '七个页签')
```

编辑 `frontend/tests/real-doc.test.tsx`，把

```ts
  must(tabs === 'Shots Cards Assets Source Render JSON', `英文视图切换：${tabs}`)
```

替换成

```ts
  must(tabs === 'Shots Cards Breakdown Assets Source Render JSON', `英文视图切换：${tabs}`)
```

（`chapter.test.tsx` 后面用 `qa('.tabs__btn')[1]` 点「卡片」，下标 1 没变，不用改。）

- [ ] **Step 4: 跑测试，确认失败**

在 `frontend/` 下运行：

```bash
npx vite build --ssr tests/paths.test.ts --outDir .ssrout --logLevel error && node .ssrout/paths.test.js
```

Expected: 抛出 `✗ 拉片表页签`（解析结果的 `tab` 是 `focus`、`fix` 非空）。

```bash
npx vite build --ssr tests/sheet-view.test.tsx --outDir .ssrout --logLevel error && node .ssrout/sheet-view.test.js
```

Expected: 前 8 项通过，然后抛出 `✗ 拉片表在卡片与资产之间`。

- [ ] **Step 5: 地址认得 `sheet`**

编辑 `frontend/src/paths.ts`，把

```ts
export const TABS = ['focus', 'cards', 'assets', 'source', 'render', 'json'] as const satisfies readonly Tab[]
```

替换成

```ts
export const TABS = ['focus', 'cards', 'sheet', 'assets', 'source', 'render', 'json'] as const satisfies readonly Tab[]
```

（这时 `tsc` 会报 `'sheet'` 不属于 `Tab`，下一步修。）

- [ ] **Step 6: `StoryboardView` 加页签并渲染拉片表**

编辑 `frontend/src/components/StoryboardView.tsx`，三处：

(a) 把

```tsx
export type Tab = 'focus' | 'cards' | 'assets' | 'source' | 'render' | 'json'

const TABS: Tab[] = ['focus', 'cards', 'assets', 'source', 'render', 'json']
```

替换成

```tsx
export type Tab = 'focus' | 'cards' | 'sheet' | 'assets' | 'source' | 'render' | 'json'

const TABS: Tab[] = ['focus', 'cards', 'sheet', 'assets', 'source', 'render', 'json']
```

(b) 把

```tsx
import { ShotFocusView } from './ShotFocusView'
```

替换成

```tsx
import { ShotFocusView } from './ShotFocusView'
import { ShotSheet } from './ShotSheet'
```

(c) 把

```tsx
      {tab === 'assets' && (
```

替换成

```tsx
      {tab === 'sheet' && (
        <ShotSheet doc={doc} idx={idx} film={film} version={version} imagesKey={imagesKey} onJump={jumpShot} />
      )}
      {tab === 'assets' && (
```

说明：`film`、`version`、`imagesKey`、`idx`、`jumpShot` 都是这个组件里已有的；`App.tsx` 不用改。页签按钮的文字来自 `t(`board.tabs.${id}`)`，`board.tabs.sheet` 已在 Task 2 加好。

- [ ] **Step 7: 跑测试，确认通过**

在 `frontend/` 下逐条运行：

```bash
npx vite build --ssr tests/paths.test.ts --outDir .ssrout --logLevel error && node .ssrout/paths.test.js
npx vite build --ssr tests/sheet-view.test.tsx --outDir .ssrout --logLevel error && node .ssrout/sheet-view.test.js
npx vite build --ssr tests/chapter.test.tsx --outDir .ssrout --logLevel error && node .ssrout/chapter.test.js
npx vite build --ssr tests/real-doc.test.tsx --outDir .ssrout --logLevel error && node .ssrout/real-doc.test.js
```

Expected:
- paths：`1.` 到 `5.` 全部 ✓，`ALL PASS`；
- sheet-view：`1.` 到 `8.`，再 `9. 页签与跳转（非受控） ✓`、`10. defaultTab 与预览 ✓`、`11. 跳转（受控） ✓`，`ALL PASS`；
- chapter：最后 `chapter: ALL PASS`；
- real-doc：最后 `ALL PASS`（中间打印的 React `act(...)` 提示是既有的，不算失败）。

- [ ] **Step 8: 全量检查**

```bash
npm test && npm run lint && npm run build
```

Expected: `npm test` 退出码 0；lint 0 error、5 条警告；build 成功。

- [ ] **Step 9: 提交**

在仓库根目录运行：

```bash
git add frontend/src/components/StoryboardView.tsx frontend/src/paths.ts frontend/tests/paths.test.ts frontend/tests/sheet-view.test.tsx frontend/tests/chapter.test.tsx frontend/tests/real-doc.test.tsx
git commit -m "分镜视图新增「拉片表」页签：排在卡片与资产之间，地址 ?tab=sheet（只在 review / render / compose 有效）；点一行跳到镜头视图并选中这一镜，受控时交给上层的 onJumpShot；分批预览时照常可看；更新页签清单断言并补路由与跳转测试"
```

---

### Task 4: 片段卡的镜头小标签

出片画布节点图的剧本段卡片，标题行下面逐镜列出「SH003 特写·推」，超过 3 个折叠成 `+N`，悬停整行看全部。对应 §4、§5.3。

**Files:**
- Modify: `frontend/tests/graph-view.test.tsx`
- Modify: `frontend/src/components/NodeCards.tsx`
- Modify: `frontend/src/components/NodeGraph.tsx`
- Modify: `frontend/src/nodeGraph.ts`（一个常量）
- Modify: `frontend/src/styles/nodegraph.css`（文件末尾追加）

- [ ] **Step 1: 写失败的测试**

编辑 `frontend/tests/graph-view.test.tsx`。找到这一行注释（全文件唯一）：

```tsx
// ---------- Esc：没选中时放行给画布关闭，选中后第一下只取消选中（NodeGraph 单独渲染） ----------
```

在它**前面**插入下面这一整块（块后空一行，再接上面那行注释）：

```tsx
// ---------- 片段卡的镜头小标签：镜号、景别、运镜；超过 3 个折叠成 +N（NodeGraph 单独渲染） ----------
{
const { NodeGraph } = await import('../src/components/NodeGraph')
const { I18nProvider } = await import('../src/i18n')
const { setCurrentLocale } = await import('../src/i18n/core')

const mk = (n: number, size: string, movement?: string) => ({
  id: `E01-SH00${n}`, duration_sec: 3, shot_size: size, camera: movement ? { movement } : undefined, action: 'a',
  source: { unit_refs: [], derivation: 'explicit' },
})
const tagDoc = { assets: {}, episodes: [{ id: 'E01', shots: [
  mk(1, 'wide', 'static'), mk(2, 'close_up', 'push_in'), mk(3, 'medium'), mk(4, 'full', 'pan'),
  mk(5, 'insert', 'track'), mk(6, 'extreme_close_up', 'follow'), mk(7, 'medium_close', 'handheld'),
] }] } as unknown as Storyboard
const mkClip = (id: string, shots: string[]) => ({
  id, episode: 'E01', shots, duration: 5, truncated: false, prompt: 'p', refs: [],
  dropped_refs: [], missing_refs: [], first_frame: null, frame_mode: null, fingerprint: 'fp', estimate_cny: 5,
  attempts: [], chosen: null, mute_native: false, uncertain: false, error: null, state: 'planned',
})
const session = {
  provider: 'fake', model: 'fake-1', resolution: '720p', audio_mode: 'tts_all', budget_cny: 200,
  confirm_over_cny: 20, spent_cny: 0, free: [], orphaned: [], counts: {}, reserved_cny: 0, uncertain_count: 0,
  remaining_cny: 0,
  clips: [
    mkClip('E01-C1', ['E01-SH001', 'E01-SH002', 'E01-SH003']),
    mkClip('E01-C2', ['E01-SH004', 'E01-SH005', 'E01-SH006', 'E01-SH007', 'E01-SH099']),
    mkClip('E01-C3', []),
  ],
  options: { providers: ['fake'], models: {}, resolutions: ['720p'], cny_per_sec: {}, max_clip_sec: 10,
             max_refs: 3, audio_modes: ['tts_all'], rate_note: '' },
} as unknown as FilmSession
const film = { session, busy: false, error: null, files: {}, ensure: () => {}, createFree: async () => {} } as unknown as Film

const container = win.document.createElement('div')
win.document.body.appendChild(container)
const root = createRoot(container as unknown as HTMLElement)
const graph = <NodeGraph film={film} doc={tagDoc} styleUrl={null} kfUrls={{}}
                         selected={null} blocked={null} onSelect={() => {}} onOpenAssets={() => {}} onOpenFilm={() => {}} />
const tagsOf = (id: string) => container.querySelector(`[data-node="${id}"] [data-testid="clip-shots"]`)
const texts = (id: string) => [...(tagsOf(id)?.querySelectorAll('.ngv__shot') ?? [])].map((x) => x.textContent)

await act(async () => { root.render(graph) })
must(texts('E01-C1').join('|') === 'SH001 远景·固定|SH002 特写·推|SH003 中景', `逐镜标签：${texts('E01-C1').join('|')}`)
must(!tagsOf('E01-C1')?.querySelector('.ngv__shot--more'), '恰好 3 个不折叠')
must(texts('E01-C2').join('|') === 'SH004 全景·摇|SH005 插入镜·移|SH006 大特写·跟|+2', `超过 3 个折叠：${texts('E01-C2').join('|')}`)
must(tagsOf('E01-C2')?.getAttribute('title')
     === 'SH004 全景·摇\nSH005 插入镜·移\nSH006 大特写·跟\nSH007 中近景·手持\nSH099', '悬停提示列出全部，找不到的镜头只写短镜号')
must(!!container.querySelector('[data-node="E01-C3"]') && !tagsOf('E01-C3'), '没有镜头的段不显示标签行')
console.log('片段卡镜头标签 ✓')

await act(async () => { root.render(<I18nProvider initial="en">{graph}</I18nProvider>) })
must(texts('E01-C1').join('|') === 'SH001 Wide·Static|SH002 Close-up·Push in|SH003 Medium', `英文标签：${texts('E01-C1').join('|')}`)
await act(async () => { root.render(graph) })
setCurrentLocale('zh')
console.log('片段卡镜头标签（英文） ✓')
await act(async () => { root.unmount() })
}
```

说明：
- 这一块复用文件顶层已有的 `win`、`act`、`createRoot`、`must` 和类型 `Film`、`FilmSession`、`Storyboard`；块内的 `container`、`root`、`film`、`session` 是花括号里的局部变量，不会和文件其他部分冲突。
- 三个片段：`E01-C1` 恰好 3 镜（不折叠，其中 `SH003` 没有运镜）；`E01-C2` 有 5 镜，最后一个 `E01-SH099` 在分镜里不存在；`E01-C3` 没有镜头。

- [ ] **Step 2: 跑测试，确认失败**

在 `frontend/` 下运行：

```bash
npx vite build --ssr tests/graph-view.test.tsx --outDir .ssrout --logLevel error && node .ssrout/graph-view.test.js
```

Expected: 打印到 `graph-view integration: PASS` 之后，抛出 `✗ 逐镜标签：`（卡片上还没有标签）。

- [ ] **Step 3: `ClipCard` 接收并渲染 `tags`**

编辑 `frontend/src/components/NodeCards.tsx`，三处：

(a) 把

```tsx
import type { AssetRole } from '../nodeGraph'
```

替换成

```tsx
import type { AssetRole } from '../nodeGraph'
import { foldTags } from '../shotSheet'
```

(b) 把

```tsx
export function ClipCard({ clip: c, s, film, blocked, hot, fallback, onDerive }: {
  clip: FilmClip; s: FilmSession; film: Film; blocked: string | null; hot: boolean
```

替换成

```tsx
export function ClipCard({ clip: c, s, film, blocked, hot, fallback, tags, onDerive }: {
  clip: FilmClip; s: FilmSession; film: Film; blocked: string | null; hot: boolean
  /** 这一段每个镜头的小标签（「SH003 特写·推」），由 NodeGraph 按分镜算好 */
  tags: string[]
```

(c) 在 `ClipCard` 函数体里，把

```tsx
  const redo = c.attempts.some((a) => a.state === 'succeeded')
  return (
    <>
      <header className="ngv__head">
        <b>{c.id}</b><span className="ngv__dim">{c.duration}s</span>
        <StatusPill tone={TONE[c.state]}>{inFlight(c) ? laneText(c, Date.now()) : label(FILM_STATE, c.state)}</StatusPill>
        {c.uncertain && <StatusPill tone="warn">{t('graph.uncertainTag')}</StatusPill>}
      </header>
```

替换成

```tsx
  const redo = c.attempts.some((a) => a.state === 'succeeded')
  const fold = foldTags(tags)
  return (
    <>
      <header className="ngv__head">
        <b>{c.id}</b><span className="ngv__dim">{c.duration}s</span>
        <StatusPill tone={TONE[c.state]}>{inFlight(c) ? laneText(c, Date.now()) : label(FILM_STATE, c.state)}</StatusPill>
        {c.uncertain && <StatusPill tone="warn">{t('graph.uncertainTag')}</StatusPill>}
      </header>
      {tags.length > 0 && (
        <p className="ngv__shots" data-testid="clip-shots" title={tags.join('\n')}>
          {fold.shown.map((x) => <span key={x} className="ngv__shot">{x}</span>)}
          {fold.more > 0 && <span className="ngv__shot ngv__shot--more">+{fold.more}</span>}
        </p>
      )}
```

说明：`+N` 是语言无关的符号，不走文案表。`title` 用换行分隔，一行一个标签。`FreeCard` 不动。

- [ ] **Step 4: `NodeGraph` 算标签并传下去**

编辑 `frontend/src/components/NodeGraph.tsx`，三处：

(a) 把

```tsx
import { edgePath, fitView, layoutGraph, related } from '../nodeGraph'
```

替换成

```tsx
import { edgePath, fitView, layoutGraph, related } from '../nodeGraph'
import { clipShotTags, shotsById } from '../shotSheet'
```

(b) 把

```tsx
  const [view, setView] = useState({ scale: 1, x: 24, y: 24 })
```

替换成

```tsx
  /** 镜头 id → 镜头：片段卡上的镜头小标签用 */
  const shots = useMemo(() => shotsById(doc), [doc])
  const [view, setView] = useState({ scale: 1, x: 24, y: 24 })
```

（这一行在提前返回 `if (!s || !graph)` 之前，hook 顺序不受影响；不要挪到后面去。）

(c) 把

```tsx
                <ClipCard clip={n.clip} s={s} film={film} blocked={blocked} hot={hot}
```

替换成

```tsx
                <ClipCard clip={n.clip} s={s} film={film} blocked={blocked} hot={hot}
                          tags={clipShotTags(n.clip.shots, shots)}
```

说明：标签文字在渲染时算、不放进 `useMemo`，因为枚举标签按当前语言取值，切语言后要跟着变。

- [ ] **Step 5: 加高剧本段卡片**

编辑 `frontend/src/nodeGraph.ts`，把

```ts
/** 剧本段卡高；自由节点卡带编辑项，更高 */
export const CARD_H = 208
```

替换成

```ts
/** 剧本段卡高（含最多两行镜头小标签）；自由节点卡带编辑项，更高 */
export const CARD_H = 252
```

说明：多出的 44px = 两行标签 40px + 一个 4px 行距。`tests/node-graph.test.ts` 用的是常量本身，不用改。`FREE_H` 不动。

- [ ] **Step 6: 加样式**

在 `frontend/src/styles/nodegraph.css` **文件末尾**追加：

```css
/* 片段卡的镜头小标签：最多两行（英文标签长，会折行），再多就藏起来；全部写在这一行的 title 里 */
.ngv__shots { display: flex; flex: none; flex-wrap: wrap; gap: 4px; max-height: 40px; margin: 0; overflow: hidden; }
.ngv__shot {
  min-width: 0; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  padding: 0 6px; border-radius: 999px; background: var(--ui-muted); color: var(--ui-muted-foreground);
  font-size: 11px; line-height: 18px;
}
```

- [ ] **Step 7: 跑测试，确认通过**

在 `frontend/` 下逐条运行：

```bash
npx vite build --ssr tests/graph-view.test.tsx --outDir .ssrout --logLevel error && node .ssrout/graph-view.test.js
npx vite build --ssr tests/node-graph.test.ts --outDir .ssrout --logLevel error && node .ssrout/node-graph.test.js
```

Expected:
- graph-view：`graph-view integration: PASS` 之后是 `片段卡镜头标签 ✓`、`片段卡镜头标签（英文） ✓`，再是原有的两项 Esc 用例，最后 `ALL PASS`；
- node-graph：`1.` 到 `6.` 全部 ✓，`ALL PASS`。

- [ ] **Step 8: 全量检查**

```bash
npm test && npm run lint && npm run build
```

Expected: `npm test` 退出码 0；lint 0 error、5 条警告；build 成功。

- [ ] **Step 9: 提交**

在仓库根目录运行：

```bash
git add frontend/src/components/NodeCards.tsx frontend/src/components/NodeGraph.tsx frontend/src/nodeGraph.ts frontend/src/styles/nodegraph.css frontend/tests/graph-view.test.tsx
git commit -m "出片节点图的片段卡逐镜列出小标签（镜号 景别·运镜）：超过 3 个折叠成 +N，悬停整行看全部；分镜里找不到的镜头只写短镜号，没有镜头的段不显示；NodeGraph 按分镜建索引后把标签传给 ClipCard，剧本段卡片加高到 252；补节点图测试"
```

---

### Task 5: 总验收

不写新代码；确认四个任务合在一起满足 spec，并把自动测试测不到的项目列给验收人。

**Files:** 无改动。

- [ ] **Step 1: 全量命令再跑一遍**

在 `frontend/` 下运行：

```bash
npm test && npm run lint && npm run build
```

Expected: `npm test` 退出码 0，输出里 `shot-sheet`、`sheet-view` 两段都有 `ALL PASS`；lint 0 error、恰好 5 条警告；build 成功。

- [ ] **Step 2: 确认没有越界改动**

在仓库根目录运行：

```bash
git status --short
git diff --stat 4d85961..HEAD -- backend frontend/src/App.tsx
git log --format='%h %s%n%b' -4 | grep -inE "co-authored|claude|codex" ; echo "署名检查结束"
```

Expected:
- `git status --short` 只剩 `?? docs/specs/2026-10-27-commercialization-design-contract.md`；
- 第二条没有输出（后端与 `App.tsx` 没被改）；
- 第三条只打印「署名检查结束」（提交信息里没有署名行）。

- [ ] **Step 3: 对照 spec 自查**

逐条核对，全部应为「是」：

| spec | 检查 |
|---|---|
| §3.1 | 页签顺序是 镜头、卡片、拉片表、资产、原文、渲染、JSON；`?tab=sheet` 可解析、可拼出 |
| §3.2 | 七列齐全；缺省显示「—」「无图」「未规划」 |
| §3.3 | 每集一个标题行，含集号、标题、镜头数 |
| §3.4 | 同集相邻同段合并；未规划的相邻镜头合并；不跨集 |
| §3.5 | 长提示词有「展开 / 收起」，短的没有 |
| §3.6 | 点行跳到镜头视图并选中；点提示词格不跳 |
| §4 | 片段卡有标签；3 个不折叠，5 个显示 3 个加 `+2`；`title` 是全部 |
| §2 | 界面不出现模型或供应商名；没有图片提示词列、没有导出 |

- [ ] **Step 4: 在报告里列出待目视确认的项目**

下面几项 happy-dom 没有布局，自动测试测不到。**不要为此启动服务**，在任务报告里原样列出，交给功能验收时在浏览器里看：

1. 窄屏（宽度小于 1080px）时，拉片表只在表格容器内横向滚动，页面本身没有横向滚动条。
2. 向下滚动时表头吸顶，集标题行不遮挡内容。
3. 提示词默认截到 3 行，点「展开」后完整显示。
4. 竖画幅（9:16）章节的关键帧缩略图是竖的，行高没有被撑得过高。
5. 节点图的片段卡：中文一行标签、英文两行标签时，卡片内都不出现滚动条，按钮行没有被挤出卡片。
6. 深色主题下表头、悬停行、标签的底色与文字对比正常。

这一步没有提交。

---

## 实施裁定（写计划时定下的，实现时不要改）

1. **测试框架**：任务说明里提到的 vitest + testing-library 在本仓库不存在。沿用现有的 `vite build --ssr` + node 脚本写法，不新增依赖。
2. **`App.tsx` 不改**：`StoryboardView` 已经收到 `film`（`flow.film`）与 `version`，拉片表直接用。
3. **未规划的相邻镜头也合并成一格**：没有出片会话时每集只有一格「未规划」，而不是每行一格。
4. **展开按钮靠字数判定**（超过 60 字或超过 3 行），不量 DOM。
5. **提示词格不参与点行跳转**：它可能跨多镜。
6. **片段卡加高**：`CARD_H` 208 → 252，标签行最多两行。英文标签长（如 `SH003 Medium close-up·Push in`），一行放不下三个。
7. **`+N` 不走文案表**：符号加数字，中英文相同。
8. **关键帧图**：拉片表自己调用 `useShotImages`，与镜头视图同一个 hook；两个视图不同时挂载，不会重复请求。
9. **不加搜索、筛选、排序、导出、图片提示词列**（spec §2 非目标）。
