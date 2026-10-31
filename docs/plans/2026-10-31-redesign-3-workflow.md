# 前端改版 3：章节工作流 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 章节页顶部一条六步步骤条（①导入原文 → ②生成分镜 → ③检查修改 → ④出片 → ⑤配音合成 → ⑥下载成片），进章节自动停在该做的一步；每步一个右下角主按钮（写明动作与金额），不能点时写原因并给「去修复」；未保存提示条；耗时任务完成用浮动提示通知；每步完成有打勾动画和一句结果；小说页加章节卡片网格。

**Architecture:** 判断「该做哪一步」写成纯函数 `src/workflow.ts`（`currentStep` / `stepStates` / 各步主按钮 `primaryFor`），单测覆盖。章节级用 `useChapterFlow` 只读地取出片会话与合成预览（不花钱的 GET）。界面拆成 `src/components/workflow/` 下的步骤条、主按钮、未保存提示条、各步工作区；③④⑤ 共用现有分镜视图，④⑤ 的主按钮打开画布并直接切到「出片」侧栏页（花钱的确认仍在出片面板里，不改）。现有逻辑模块（`api.ts`、`useFilm`、`useCompose`、`film.ts`、`compose.ts`、`timeline.ts`）不改行为。

**Tech Stack:** React 19、TS 6、Tailwind v4、shadcn、motion、lucide-react、sonner、happy-dom。

**Spec:** `docs/specs/2026-10-31-frontend-redesign-design.md` 第 4 节、第 5 节（小说页、章节页）、第 8 节。

---

## 全局约束

- 提交只 `git add` 具体文件，不用 `git add -A` / `git commit -a`；提交信息中文，**不带任何 Claude 署名**。
- 命令在 `frontend/` 下执行。每个任务结束：`npm test`（全部套件 `ALL PASS`）、`npm run lint`（0 error，不新增 warning；现有 6 个）、`npx vite build`。
- `useI18n`、`translate`、`MsgKey` 从 `@/i18n/core` 导入。**新写或搬动的界面文字一律进语言包**（`zh.ts` 与 `en.ts` 同步，`en` 类型是 `Messages`，缺键编译报错）。搬动的中文文案保持原字面（测试依赖），只有本计划明确改名的才改。
- 设计变量：shadcn 的 muted/accent/radius 叫 `--ui-*`，Tailwind 类名照常（`bg-muted`、`rounded-lg`）；旧样式在 `legacy` 层，工具类压过它。品牌渐变 `bg-brand` / `text-brand`，颜色 `success`、`warning`、`destructive`、`brand-from`、`brand-to`。
- 动效用 `@/motion` 的 `useMotionPresets()`、`DUR`、`EASE_OUT`；减少动态效果时不位移。
- 测试固定用中文。happy-dom 测试的全局变量照 `tests/foundation.test.tsx` 开头那段拷贝（`window`…`MutationObserver`）。
- 不碰后端，不碰 `docs/specs/2026-10-27-commercialization-design-contract.md`，不读 `backend/.env`。

## 实施裁定

1. **③「检查修改」不需要手动打勾**：版本生成成功、没有未保存修改、完整性检查没失败，就算完成（与 spec 4.1 第 3 条一致）。所以新版本生成完会直接停在 ④；③ 仍可点进去看。
2. **③④⑤ 共用分镜视图工作区**：④⑤ 不自动打开画布，主按钮「去出片…」「去配音合成…」才打开画布并切到「出片」侧栏页。花钱的确认（`MoneyConfirm` / 出片面板里的确认）不挪动。
3. **自动跳步**：进入章节时停在 `currentStep`；之后只有 `currentStep` **往后走**时才跟着跳（比如生成完成、出片会话读到了）；用户手点的步骤在 `currentStep` 不变时保持。
4. **改名（说人话）只改本计划碰到的界面**：章节工作区里「开始转换」→「生成分镜」、「重新转换（新版本）」→「重新生成（新版本）」、「转换中…」→「生成中…」；画布「任务」页、出片与合成面板的措辞留给子计划 4。
5. **章节级读出片状态只发 GET**：`getFilm`（404 = 还没有出片会话）、有成片时再 `getCompose(..., draft)` 取 `final.stale`。读取失败当「没有」，不弹错。画布关闭、版本切换、保存后重读。
6. **任务面板（`JobPanel`）留在 App 原位**：它可能附着在别的章节的任务上；②工作区在本章生成中时只显示一行进度和「查看进度」。
7. **外壳与侧栏重复的「新建小说」**：去掉侧栏里的「＋ 新小说」，保留外壳的「新建小说」。
8. **小说页默认页签改为新增的「章节」**（有待确认的人物状态时仍默认「人物生命周期」）。

## 文件结构

| 文件 | 职责 |
|---|---|
| `src/workflow.ts` | 新建：步骤定义、`stepDone`、`currentStep`、`stepStates`、`primaryFor`（纯函数） |
| `tests/workflow.test.ts` | 新建：纯函数单测 |
| `src/useChapterFlow.ts` | 新建：章节级只读取出片会话与成片是否过期 |
| `src/lib/flash.ts` | 新建：`flashTarget(id)` 滚到并高亮 1.5 秒 |
| `src/components/workflow/Stepper.tsx` | 新建：步骤条 |
| `src/components/workflow/PrimaryBar.tsx` | 新建：右下角主按钮 + 原因 + 去修复 |
| `src/components/workflow/UnsavedBar.tsx` | 新建：底部未保存提示条 |
| `src/components/workflow/SourceStep.tsx` | 新建：①原文（从 `ChapterPage` 搬） |
| `src/components/workflow/GenerateStep.tsx` | 新建：②生成参数与进度（从 `ChapterPage` 搬） |
| `src/components/workflow/VersionBar.tsx` | 新建：版本条与章后整理（从 `ChapterPage` 搬） |
| `src/components/workflow/DownloadStep.tsx` | 新建：⑥每集成片、字幕、合成报告 |
| `src/components/workflow/ChapterWorkflow.tsx` | 新建：章节页总装（标题、步骤条、版本条、各步工作区、主按钮） |
| `src/components/ChapterPage.tsx` | 删除（拆进上面几个文件） |
| `src/components/StoryboardView.tsx` | 修改：`openFilm` 信号、`onCanvasClose`、保存按钮 id |
| `src/components/TimelineCanvas.tsx` | 修改：`initialPanel` |
| `src/components/NovelPage.tsx` | 修改：新增「章节」页签（卡片网格） |
| `src/components/NovelSidebar.tsx` | 修改：去掉「＋ 新小说」 |
| `src/App.tsx` | 修改：接 `ChapterWorkflow`、未保存提示条与撤销、离开提醒、完成浮动提示 |
| `src/styles/app.css` | 修改：`.fix-flash` |
| `src/i18n/zh.ts`、`en.ts` | 修改：`flow.*`、`novel.*` |
| `tests/workflow-ui.test.tsx` | 新建：步骤条、主按钮、未保存提示条 |
| `tests/flow.test.tsx` | 修改：按步骤条导航、改名后的按钮 |
| `package.json` | 修改：test 脚本加两套 |

---

### Task 1: 步骤判断（纯函数）

**Files:** Create `src/workflow.ts`、`tests/workflow.test.ts`；Modify `package.json`

- [ ] **Step 1: 写测试** — Create `tests/workflow.test.ts`:

```ts
/** 章节工作流的纯计算：该做哪一步、各步状态、各步主按钮（动作、金额、拦截原因与修复目标）。跑法：npm test */
import { currentStep, primaryFor, stepStates, STEPS } from '../src/workflow'
import type { FlowInput } from '../src/workflow'
import type { ComposePreview, FilmClip, FilmSession, VersionSummary } from '../src/types'

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }

const ver = (status: VersionSummary['status'] = 'succeeded', extra: Partial<VersionSummary> = {}): VersionSummary => ({
  id: 'v1', created_at: null, edited_at: null, status, units: 10, episodes: 1, shots: 12,
  has_quality_report: false, ...extra,
})
const clip = (id: string, state: FilmClip['state'], extra: Partial<FilmClip> = {}) => ({
  id, state, shots: [`E01-${id}`], duration: 5, estimate_cny: 2.5, attempts: [], chosen: null,
  missing_refs: [], dropped_refs: [], truncated: false, uncertain: false, queued_at: null, error: null,
  first_frame: null, frame_mode: 'first', mute_native: false, ...extra,
}) as unknown as FilmClip
const film = (clips: FilmClip[], extra: Partial<FilmSession> = {}) => ({
  clips, budget_cny: 100, spent_cny: 0, reserved_cny: 0, remaining_cny: clips.length * 2.5, confirm_over_cny: 20,
  final: null, gate: { ok: true, message: null }, ...extra,
}) as unknown as FilmSession
const base: FlowInput = {
  hasText: true, textDirty: false, converting: false, version: ver(), dirty: false,
  verificationFailed: false, film: null, finalStale: false, compose: null,
}
const at = (p: Partial<FlowInput>) => currentStep({ ...base, ...p })

// 1. 按顺序取第一个没完成的步骤
must(STEPS.join() === 'import,storyboard,review,render,compose,download', '六步顺序')
must(at({ hasText: false, version: null }) === 'import', '没有原文 → ①')
must(at({ version: null }) === 'storyboard', '没有版本 → ②')
must(at({ version: ver('failed') }) === 'storyboard', '只有失败的版本 → ②')
must(at({ converting: true }) === 'storyboard', '生成中也停在 ②')
must(at({ dirty: true }) === 'review', '有未保存修改 → ③')
must(at({ verificationFailed: true }) === 'review', '完整性检查没过 → ③')
must(at({ version: ver('succeeded', { verification_status: 'failed' }) }) === 'review', '版本摘要里复验失败 → ③')
must(at({ film: null }) === 'render', '没有出片会话 → ④')
must(at({ film: film([clip('c1', 'done'), clip('c2', 'planned')]) }) === 'render', '还有段没出 → ④')
const done2 = film([clip('c1', 'done'), clip('c2', 'done')])
must(at({ film: done2 }) === 'compose', '都出好了、没有成片 → ⑤')
const finalDone = { state: 'done', files: ['final/E01.mp4'], report: null, error: null, detail: null }
must(at({ film: { ...done2, final: finalDone } as FilmSession, finalStale: true }) === 'compose', '成片过期 → ⑤')
must(at({ film: { ...done2, final: { ...finalDone, state: 'running' } } as FilmSession }) === 'compose', '合成中 → ⑤')
must(at({ film: { ...done2, final: finalDone } as FilmSession }) === 'download', '都完成 → ⑥')
console.log('1. currentStep ✓')

// 2. 各步状态：之前的打勾，当前高亮，之后的灰掉并说明先完成第几步
const st = stepStates({ ...base, film: null })
must(st.map((s) => s.state).join() === 'done,done,done,current,locked,locked', '状态序列')
must(st[5].needs === 4, '灰掉的步骤记着要先完成第几步（1 起）')
console.log('2. stepStates ✓')

// 3. 主按钮：动作、金额、拦截原因与修复目标
const p1 = primaryFor('import', { ...base, version: null, hasText: false })
must(p1.blocked?.reason === 'flow.block.noText' && p1.blocked.fix.target === 'chapter-source', '没原文：拦截并定位到原文框')
const p1b = primaryFor('import', { ...base, textDirty: true })
must(p1b.action === 'saveText' && !p1b.blocked, '原文改过：主按钮是保存原文')
must(primaryFor('import', base).action === 'goto' && primaryFor('import', base).goto === 'storyboard', '原文好了：去下一步')
const p2 = primaryFor('storyboard', { ...base, version: null, textDirty: true })
must(p2.blocked?.reason === 'flow.block.textDirty' && p2.blocked.fix.step === 'import', '原文没保存：拦截，修复去 ①')
must(primaryFor('storyboard', { ...base, version: null }).action === 'generate', '主按钮生成分镜')
must(primaryFor('storyboard', base).label === 'flow.primary.regenerate', '已有版本：重新生成')
must(primaryFor('storyboard', { ...base, converting: true }).blocked?.reason === 'flow.block.converting', '生成中不能再点')
must(primaryFor('review', { ...base, dirty: true }).action === 'save', '有修改：主按钮保存')
const p3 = primaryFor('review', { ...base, verificationFailed: true })
must(p3.blocked?.reason === 'flow.block.verify' && p3.blocked.fix.target === 'verification', '检查没过：定位到检查结果')
const p4 = primaryFor('render', { ...base, film: film([clip('c1', 'planned'), clip('c2', 'planned')]) })
must(p4.action === 'openFilm' && p4.label === 'flow.primary.tryOne' && p4.cny === 2.5, '没出过：先试一段（约 ¥2.50）')
const p4b = primaryFor('render', { ...base, film: film([clip('c1', 'done'), clip('c2', 'planned')], { remaining_cny: 2.5 }) })
must(p4b.label === 'flow.primary.renderRest' && p4b.count === 1 && p4b.cny === 2.5, '出过一段：出剩余 1 段')
must(primaryFor('render', base).label === 'flow.primary.startFilm', '没有会话：去出片（先切段，不花钱）')
const p4c = primaryFor('render', { ...base, dirty: true })
must(p4c.blocked?.reason === 'flow.block.dirty' && p4c.blocked.fix.target === 'storyboard-save', '没保存：定位到保存按钮')
const preview = { tts_cny: 0.18 } as ComposePreview
const p5 = primaryFor('compose', { ...base, film: done2, compose: preview })
must(p5.action === 'openFilm' && p5.label === 'flow.primary.compose' && p5.cny === 0.18, '去配音合成（约 ¥0.18）')
must(primaryFor('compose', { ...base, film: null }).blocked?.fix.step === 'render', '还没出片：修复去 ④')
must(primaryFor('download', base).action === 'none', '⑥没有主按钮动作（下载在工作区里）')
console.log('3. primaryFor ✓')

console.log('\nALL PASS')
```

- [ ] **Step 2: 加进 test 脚本** — In `package.json` `test` script, append:

```
 && vite build --ssr tests/workflow.test.ts --outDir .ssrout --logLevel error && node .ssrout/workflow.test.js
```

Run: `npm test 2>&1 | tail -3` → Expected: FAIL（`../src/workflow` 不存在）。

- [ ] **Step 3: 实现** — Create `src/workflow.ts`:

```ts
/** 章节工作流的纯计算：六步的完成判断、「该做的那一步」、各步状态、各步主按钮（动作、金额、拦截原因与修复目标）。
 *  界面只吃这里的结果；单测见 tests/workflow.test.ts。原因与按钮文字是语言包的键，界面再翻译。 */
import type { MsgKey } from './i18n/core'
import type { ComposePreview, FilmSession, VersionSummary } from './types'

export const STEPS = ['import', 'storyboard', 'review', 'render', 'compose', 'download'] as const
export type StepId = (typeof STEPS)[number]

const OK = ['succeeded', 'completed_with_warnings']

export interface FlowInput {
  /** 本章原文非空（按已保存的算） */
  hasText: boolean
  /** 原文框里有没保存的改动 */
  textDirty: boolean
  /** 本章有生成在跑 */
  converting: boolean
  /** 正在看的版本摘要；还没有版本为 null */
  version: VersionSummary | null
  /** 分镜有未保存的修改 */
  dirty: boolean
  /** 保存后复验没通过 */
  verificationFailed: boolean
  /** 出片会话：null = 还没有（或还没读到） */
  film: FilmSession | null
  /** 成片已过期（合成预览给的） */
  finalStale: boolean
  /** 合成预览（只用来显示配音金额）；没读到为 null */
  compose: ComposePreview | null
}

export function stepDone(id: StepId, f: FlowInput): boolean {
  switch (id) {
    case 'import': return f.hasText
    case 'storyboard': return !!f.version && OK.includes(f.version.status) && !f.converting
    case 'review': return stepDone('storyboard', f) && !f.dirty && !f.verificationFailed
      && f.version?.verification_status !== 'failed'
    case 'render': return !!f.film && f.film.clips.length > 0 && f.film.clips.every((c) => c.state === 'done')
    case 'compose': return f.film?.final?.state === 'done' && !f.finalStale
    case 'download': return false
  }
}

/** 按顺序取第一个没完成的步骤；前五步都完成就是 ⑥ */
export function currentStep(f: FlowInput): StepId {
  return STEPS.find((id) => !stepDone(id, f)) ?? 'download'
}

export interface StepState {
  id: StepId
  state: 'done' | 'current' | 'locked'
  /** 灰掉时：要先完成第几步（1 起） */
  needs?: number
}

export function stepStates(f: FlowInput): StepState[] {
  const cur = STEPS.indexOf(currentStep(f))
  return STEPS.map((id, i) => i < cur ? { id, state: 'done' }
    : i === cur ? { id, state: 'current' } : { id, state: 'locked', needs: cur + 1 })
}

export interface Fix {
  /** 切到哪一步 */
  step?: StepId
  /** 再滚到并高亮哪个元素（id） */
  target?: string
}

export interface Primary {
  action: 'saveText' | 'goto' | 'generate' | 'save' | 'openFilm' | 'none'
  label: MsgKey
  goto?: StepId
  cny?: number
  count?: number
  blocked?: { reason: MsgKey; fix: Fix }
}

const block = (p: Omit<Primary, 'blocked'>, reason: MsgKey, fix: Fix): Primary => ({ ...p, blocked: { reason, fix } })

/** 第 id 步右下角的主按钮 */
export function primaryFor(id: StepId, f: FlowInput): Primary {
  switch (id) {
    case 'import': {
      if (f.textDirty) return { action: 'saveText', label: 'flow.primary.saveText' }
      const p: Primary = { action: 'goto', goto: 'storyboard', label: 'flow.primary.next' }
      return f.hasText ? p : block(p, 'flow.block.noText', { step: 'import', target: 'chapter-source' })
    }
    case 'storyboard': {
      const p: Primary = { action: 'generate', label: f.version ? 'flow.primary.regenerate' : 'flow.primary.generate' }
      if (f.converting) return block({ ...p, label: 'flow.primary.generating' }, 'flow.block.converting', {})
      if (!f.hasText) return block(p, 'flow.block.noText', { step: 'import', target: 'chapter-source' })
      if (f.textDirty) return block(p, 'flow.block.textDirty', { step: 'import', target: 'chapter-source' })
      return p
    }
    case 'review': {
      if (f.dirty) return { action: 'save', label: 'flow.primary.save' }
      const p: Primary = { action: 'goto', goto: 'render', label: 'flow.primary.next' }
      if (!stepDone('storyboard', f)) return block(p, 'flow.block.noVersion', { step: 'storyboard' })
      if (f.verificationFailed || f.version?.verification_status === 'failed') {
        return block(p, 'flow.block.verify', { step: 'review', target: 'verification' })
      }
      return p
    }
    case 'render': {
      const s = f.film
      const rest = s ? s.clips.filter((c) => (c.state === 'planned' || c.state === 'failed') && !c.uncertain) : []
      const tried = !!s?.clips.some((c) => c.state === 'done')
      const p: Primary = !s ? { action: 'openFilm', label: 'flow.primary.startFilm' }
        : !rest.length ? { action: 'openFilm', label: 'flow.primary.viewFilm' }
        : tried ? { action: 'openFilm', label: 'flow.primary.renderRest', count: rest.length, cny: s.remaining_cny }
        : { action: 'openFilm', label: 'flow.primary.tryOne', cny: rest[0].estimate_cny }
      if (!stepDone('storyboard', f)) return block(p, 'flow.block.noVersion', { step: 'storyboard' })
      if (f.dirty) return block(p, 'flow.block.dirty', { step: 'review', target: 'storyboard-save' })
      if (f.verificationFailed || f.version?.verification_status === 'failed') {
        return block(p, 'flow.block.verify', { step: 'review', target: 'verification' })
      }
      return p
    }
    case 'compose': {
      const p: Primary = { action: 'openFilm', label: 'flow.primary.compose', cny: f.compose?.tts_cny }
      if (f.dirty) return block(p, 'flow.block.dirty', { step: 'review', target: 'storyboard-save' })
      if (!f.film) return block(p, 'flow.block.noFilm', { step: 'render' })
      return p
    }
    case 'download':
      return { action: 'none', label: 'flow.primary.next' }
  }
}
```

注意：`label` / `reason` 是 Task 3 才加的语言包键；本任务先在 `src/i18n/zh.ts` 与 `en.ts` 加上 Task 3 Step 1 里 `flow` 下的 **`primary` 与 `block` 两组**（照抄 Task 3 的文案），否则 `MsgKey` 类型不过。

Run: `npm test 2>&1 | grep -c "ALL PASS"` → Expected: `12`（原 11 + 本套）。lint、build 照常。

- [ ] **Step 4: 提交**

```bash
git add src/workflow.ts tests/workflow.test.ts package.json src/i18n/zh.ts src/i18n/en.ts
git commit -m "章节工作流纯计算：六步完成判断、该做的那一步、各步状态（先完成第几步）、各步主按钮（动作、金额、拦截原因与修复目标）"
```

---

### Task 2: 章节级读出片状态、定位高亮、画布直达出片页

**Files:** Create `src/useChapterFlow.ts`、`src/lib/flash.ts`；Modify `src/components/StoryboardView.tsx`、`src/components/TimelineCanvas.tsx`、`src/styles/app.css`

- [ ] **Step 1: `useChapterFlow`**

```ts
/** 章节页的只读出片状态：出片会话（404 = 还没有）与成片是否过期（有成片时才读合成预览）。
 *  只发 GET、不花钱；读取失败当「没有」，不弹错（出片面板里有完整的错误处理）。
 *  版本变了、调用 reload() 时重读；换版本时之前的响应丢弃。 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { getCompose, getFilm } from './api'
import type { ComposePreview, FilmSession, VersionRef } from './types'

export function useChapterFlow(version: VersionRef | null) {
  const { nid, cid, vid } = version ?? {}
  const [film, setFilm] = useState<FilmSession | null>(null)
  const [compose, setCompose] = useState<ComposePreview | null>(null)
  const gen = useRef(0)

  const reload = useCallback(async () => {
    const mine = ++gen.current
    if (!nid || !cid || !vid) { setFilm(null); setCompose(null); return }
    let s: FilmSession | null = null
    try { s = await getFilm(nid, cid, vid) } catch { s = null }
    if (gen.current !== mine) return
    setFilm(s)
    let p: ComposePreview | null = null
    if (s) {
      try { p = await getCompose(nid, cid, vid, s.final?.draft ?? true) } catch { p = null }
    }
    if (gen.current === mine) setCompose(p)
  }, [nid, cid, vid])

  useEffect(() => { void reload() }, [reload])

  return { film, compose, finalStale: !!compose?.final?.stale, reload }
}
```

- [ ] **Step 2: `flashTarget`** — Create `src/lib/flash.ts`:

```ts
/** 「去修复」：滚到目标元素并高亮 1.5 秒（减少动态效果时直接跳过去） */
export function flashTarget(id: string) {
  const el = document.getElementById(id)
  if (!el) return
  const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  el.scrollIntoView?.({ block: 'center', behavior: reduced ? 'auto' : 'smooth' })
  el.classList.add('fix-flash')
  window.setTimeout(() => el.classList.remove('fix-flash'), 1500)
}
```

In `src/styles/app.css` (inside `@layer components`, create the layer block if absent), add:

```css
  .fix-flash {
    outline: 2px solid var(--brand-to);
    outline-offset: 4px;
    border-radius: var(--ui-radius);
    transition: outline-color 0.3s ease-out;
  }
```

- [ ] **Step 3: 画布直达「出片」页** — `src/components/TimelineCanvas.tsx`:
  - `Props` 加 `/** 打开时停在哪个侧栏页 */ initialPanel?: PanelTab`；把 `type PanelTab` 改成 `export type PanelTab`。
  - `useState<PanelTab>('shot')` 改为 `useState<PanelTab>(initialPanel ?? 'shot')`（解构里加 `initialPanel`）。

- [ ] **Step 4: 分镜视图的信号** — `src/components/StoryboardView.tsx`:
  - `Props` 加：
    ```ts
    /** 每加一就打开画布并停在「出片」页（章节工作流 ④⑤ 的主按钮） */
    openFilm?: number
    /** 画布关上时（出片、合成可能改了状态，让上层重读） */
    onCanvasClose?: () => void
    ```
  - 加 `const [canvasPanel, setCanvasPanel] = useState<'film' | undefined>(undefined)`，以及
    ```ts
    useEffect(() => {
      if (!openFilm) return
      setCanvasPanel('film')
      setCanvas(true)
    }, [openFilm])
    ```
  - 关画布处统一走 `const closeCanvas = () => { setCanvas(false); setCanvasPanel(undefined); onCanvasClose?.() }`（`onClose` 用它；`jumpShot` 里的 `setCanvas(false)` 也换成它）。
  - `<TimelineCanvas … initialPanel={canvasPanel} />`。
  - 「保存修改」按钮加 `id="storyboard-save"`。

- [ ] **Step 5: 验证与提交** — `npm test`（12 个 ALL PASS）、lint、build。

```bash
git add src/useChapterFlow.ts src/lib/flash.ts src/styles/app.css src/components/StoryboardView.tsx src/components/TimelineCanvas.tsx
git commit -m "章节级只读出片状态（会话与成片是否过期）、「去修复」滚到并高亮、画布可直接停在出片页、分镜视图开画布信号与关闭回调"
```

---

### Task 3: 语言包、步骤条、主按钮、未保存提示条

**Files:** Modify `src/i18n/zh.ts`、`en.ts`；Create `src/components/workflow/Stepper.tsx`、`PrimaryBar.tsx`、`UnsavedBar.tsx`、`tests/workflow-ui.test.tsx`；Modify `package.json`

- [ ] **Step 1: 语言包** — `zh.ts` 加顶层 `flow`（`primary`、`block` 两组 Task 1 已加，保持一致）：

```ts
  flow: {
    steps: {
      import: '导入原文', storyboard: '生成分镜', review: '检查修改',
      render: '出片', compose: '配音合成', download: '下载成片',
    },
    stepsLabel: '章节进度',
    needs: '需要先完成第 {n} 步',
    goNeeded: '去第 {n} 步',
    fix: '去修复',
    primary: {
      saveText: '保存原文',
      next: '下一步',
      generate: '生成分镜',
      regenerate: '重新生成（新版本）',
      generating: '生成中…',
      save: '保存修改',
      startFilm: '去出片（先切段，不花钱）',
      tryOne: '先试一段（约 {amount}）',
      renderRest: '出剩余 {count} 段（约 {amount}）',
      viewFilm: '查看出片',
      compose: '去配音合成（配音约 {amount}）',
    },
    block: {
      noText: '还没有原文：先粘贴或读取本章原文',
      textDirty: '原文有没保存的修改：先保存原文',
      converting: '正在生成，完成后会自动停到下一步',
      noVersion: '还没有生成成功的分镜',
      verify: '完整性检查没通过：按检查结果修改后保存',
      dirty: '有未保存的修改：先保存',
      noFilm: '还没有出片：先完成第 4 步',
    },
    unsaved: '有未保存的修改',
    unsavedSave: '保存',
    unsavedUndo: '撤销',
    leave: '当前修改尚未保存，确定离开？',
    done: {
      storyboard: '分镜已生成，共 {shots} 镜',
      render: '所有段都出好了，下一步配音合成',
      compose: '成片已合成，可以下载了',
    },
    view: '查看',
    source: { chars: '本章原文 · {n} 字', edit: '修改原文' },
    progress: '查看进度',
  },
```

`en.ts` 同结构：

```ts
  flow: {
    steps: {
      import: 'Import text', storyboard: 'Storyboard', review: 'Review & edit',
      render: 'Render', compose: 'Voice & mix', download: 'Download',
    },
    stepsLabel: 'Chapter progress',
    needs: 'Finish step {n} first',
    goNeeded: 'Go to step {n}',
    fix: 'Fix it',
    primary: {
      saveText: 'Save text',
      next: 'Next',
      generate: 'Generate storyboard',
      regenerate: 'Regenerate (new version)',
      generating: 'Generating…',
      save: 'Save changes',
      startFilm: 'Start rendering (splitting is free)',
      tryOne: 'Try one clip (≈ {amount})',
      renderRest: 'Render {count} remaining (≈ {amount})',
      viewFilm: 'View render',
      compose: 'Voice & mix (voice ≈ {amount})',
    },
    block: {
      noText: 'No text yet: paste or load this chapter first',
      textDirty: 'The text has unsaved edits: save it first',
      converting: 'Generating — you’ll be moved to the next step when it’s done',
      noVersion: 'No successful storyboard yet',
      verify: 'Integrity check failed: fix the issues below and save',
      dirty: 'You have unsaved changes: save first',
      noFilm: 'Nothing rendered yet: finish step 4 first',
    },
    unsaved: 'You have unsaved changes',
    unsavedSave: 'Save',
    unsavedUndo: 'Undo',
    leave: 'You have unsaved changes. Leave anyway?',
    done: {
      storyboard: 'Storyboard ready — {shots} shots',
      render: 'All clips rendered. Next: voice & mix',
      compose: 'Final video is ready to download',
    },
    view: 'View',
    source: { chars: 'Chapter text · {n} chars', edit: 'Edit text' },
    progress: 'View progress',
  },
```

（金额没有时，界面把 `{amount}` 那半句去掉：`compose` 无金额时用 `flow.primary.compose` 的同一键、`amount` 传 `—`。插值占位符一律 `{name}`。）

- [ ] **Step 2: 步骤条** — Create `src/components/workflow/Stepper.tsx`:

```tsx
/** 章节页顶部的六步步骤条：已完成打勾（弹一下）、当前高亮、没到的灰掉；点灰掉的说明要先完成第几步并给直达按钮。
 *  view 是正在看的步骤（可以回看已完成的）。 */
import { useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { Check, Lock } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/i18n/core'
import type { MsgKey } from '@/i18n/core'
import { cn } from '@/lib/utils'
import { useMotionPresets } from '@/motion'
import { STEPS } from '@/workflow'
import type { StepId, StepState } from '@/workflow'

export function Stepper({ states, view, onView }: {
  states: StepState[]
  view: StepId
  onView: (id: StepId) => void
}) {
  const { t } = useI18n()
  const m = useMotionPresets()
  const [hint, setHint] = useState<StepState | null>(null)
  return (
    <nav aria-label={t('flow.stepsLabel')} className="relative">
      <ol className="flex flex-wrap items-center gap-1">
        {states.map((s, i) => (
          <li key={s.id} className="flex items-center gap-1">
            {i > 0 && <span aria-hidden className={cn('h-px w-4 md:w-8', s.state === 'locked' ? 'bg-border' : 'bg-brand')} />}
            <button type="button" data-step={s.id} aria-current={view === s.id ? 'step' : undefined}
                    aria-disabled={s.state === 'locked'}
                    onClick={() => (s.state === 'locked' ? setHint(hint?.id === s.id ? null : s) : (setHint(null), onView(s.id)))}
                    className={cn('flex items-center gap-2 rounded-full border px-3 py-1.5 text-sm transition-colors',
                                  view === s.id && 'border-transparent bg-foreground text-background',
                                  view !== s.id && s.state === 'current' && 'border-brand-to/60 text-foreground',
                                  view !== s.id && s.state === 'done' && 'text-foreground hover:bg-muted',
                                  s.state === 'locked' && 'text-muted-foreground opacity-60')}>
              <span className={cn('flex size-5 items-center justify-center rounded-full text-[11px] font-semibold',
                                  s.state === 'done' ? 'bg-success text-white' : 'bg-muted text-foreground')}>
                <AnimatePresence initial={false} mode="wait">
                  {s.state === 'done'
                    ? <motion.span key="ok" {...m.pop}><Check className="size-3" /></motion.span>
                    : s.state === 'locked'
                      ? <Lock key="lock" className="size-3" />
                      : <span key="n">{i + 1}</span>}
                </AnimatePresence>
              </span>
              {t(`flow.steps.${s.id}` as MsgKey)}
            </button>
          </li>
        ))}
      </ol>
      <AnimatePresence>
        {hint && (
          <motion.div {...m.enter} role="status" data-testid="step-hint"
                      className="absolute left-0 top-full z-20 mt-2 flex items-center gap-3 rounded-lg border bg-popover px-3 py-2 text-sm shadow-lg">
            {t('flow.needs', { n: hint.needs ?? 1 })}
            <Button size="sm" variant="outline"
                    onClick={() => { onView(STEPS[(hint.needs ?? 1) - 1]); setHint(null) }}>
              {t('flow.goNeeded', { n: hint.needs ?? 1 })}
            </Button>
          </motion.div>
        )}
      </AnimatePresence>
    </nav>
  )
}
```

- [ ] **Step 3: 主按钮** — Create `src/components/workflow/PrimaryBar.tsx`:

```tsx
/** 每一步右下角固定的主按钮：写明动作和金额；不能点时上方写原因并给「去修复」。 */
import { AnimatePresence, motion } from 'motion/react'
import { ArrowRight, Wrench } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/i18n/core'
import { useMotionPresets } from '@/motion'
import type { Fix, Primary } from '@/workflow'

const yuan = (n?: number) => (n === undefined ? '—' : `¥${n.toFixed(2)}`)

export function PrimaryBar({ primary, busy, onRun, onFix }: {
  primary: Primary
  busy?: boolean
  onRun: () => void
  onFix: (fix: Fix) => void
}) {
  const { t } = useI18n()
  const m = useMotionPresets()
  if (primary.action === 'none') return null
  const text = t(primary.label, { amount: yuan(primary.cny), count: primary.count ?? 0 })
  return (
    <div className="pointer-events-none fixed bottom-6 right-6 z-30 flex max-w-sm flex-col items-end gap-2">
      <AnimatePresence>
        {primary.blocked && (
          <motion.div {...m.enter} role="status" data-testid="primary-reason"
                      className="pointer-events-auto flex items-center gap-3 rounded-xl border bg-card px-3 py-2 text-sm shadow-lg">
            <span>{t(primary.blocked.reason)}</span>
            {(primary.blocked.fix.step || primary.blocked.fix.target) && (
              <Button size="sm" variant="outline" className="gap-1.5" data-testid="primary-fix"
                      onClick={() => onFix(primary.blocked!.fix)}>
                <Wrench className="size-3.5" />{t('flow.fix')}
              </Button>
            )}
          </motion.div>
        )}
      </AnimatePresence>
      <Button size="lg" data-testid="primary-action" className="pointer-events-auto gap-2 shadow-xl"
              disabled={!!primary.blocked || busy} onClick={onRun}>
        {text}<ArrowRight className="size-4" />
      </Button>
    </div>
  )
}
```

- [ ] **Step 4: 未保存提示条** — Create `src/components/workflow/UnsavedBar.tsx`:

```tsx
/** 底部固定的「有未保存的修改 · 保存 · 撤销」。保存仍是手动的；撤销 = 回到上次保存的样子。 */
import { AnimatePresence, motion } from 'motion/react'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/i18n/core'
import { useMotionPresets } from '@/motion'

export function UnsavedBar({ show, saving, onSave, onUndo }: {
  show: boolean
  saving: boolean
  onSave: () => void
  onUndo: () => void
}) {
  const { t } = useI18n()
  const m = useMotionPresets()
  return (
    <AnimatePresence>
      {show && (
        <motion.div {...m.enter} role="status" data-testid="unsaved-bar"
                    className="fixed bottom-6 left-1/2 z-30 flex -translate-x-1/2 items-center gap-3 rounded-full border bg-card px-4 py-2 text-sm shadow-xl">
          <span className="size-2 rounded-full bg-warning" aria-hidden />
          {t('flow.unsaved')}
          <Button size="sm" disabled={saving} onClick={onSave}>{t('flow.unsavedSave')}</Button>
          <Button size="sm" variant="ghost" disabled={saving} onClick={onUndo}>{t('flow.unsavedUndo')}</Button>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
```

（`-translate-x-1/2` 与 motion 的 `y` 位移会被 motion 的内联 `transform` 覆盖：把居中改为外层 `fixed inset-x-0 bottom-6 flex justify-center pointer-events-none` 包一层、内层 `pointer-events-auto`，motion 只作用于内层。实现时照此写。）

- [ ] **Step 5: 组件测试** — Create `tests/workflow-ui.test.tsx`（happy-dom 开头照抄 `tests/foundation.test.tsx` 的全局设置；`settle`/`click` 写法照抄 `tests/landing.test.tsx`）。断言：
  1. `Stepper`：给 `stepStates({...})`（当前 ④）渲染，`[data-step]` 6 个；前三个含勾（`svg` 且不显示数字）；点 `[data-step="compose"]` 不调用 `onView`，出现 `[data-testid="step-hint"]` 文字「需要先完成第 4 步」，点其中「去第 4 步」调用 `onView('render')`；点 `[data-step="review"]` 调用 `onView('review')`。
  2. `PrimaryBar`：`primaryFor('render', 没出过的两段会话)` 渲染出「先试一段（约 ¥2.50）」且可点，点击调 `onRun`；`primaryFor('review', {verificationFailed:true})` 渲染出原因「完整性检查没通过」、主按钮 `disabled`、点「去修复」调 `onFix({step:'review',target:'verification'})`；`action:'none'` 不渲染任何东西。
  3. `UnsavedBar`：`show` 为真时有「有未保存的修改」，点「保存」「撤销」各调一次回调；`show` 为假时 300ms 后不在。
  4. `flashTarget`：建一个 `id="x"` 的元素，调用后带 `fix-flash`，1600ms 后不带。

  每段末尾 `console.log('N. … ✓')`，最后 `ALL PASS`。`package.json` test 脚本再追加 `tests/workflow-ui.test.tsx` 一段（同 Task 1 写法）。

- [ ] **Step 6: 验证与提交** — `npm test`（13 个 ALL PASS）、lint、build。

```bash
git add src/i18n/zh.ts src/i18n/en.ts src/components/workflow/Stepper.tsx src/components/workflow/PrimaryBar.tsx src/components/workflow/UnsavedBar.tsx tests/workflow-ui.test.tsx package.json
git commit -m "章节工作流组件：六步步骤条（打勾动效、灰步说明先完成第几步并可直达）、右下角主按钮（动作与金额、原因与去修复）、未保存提示条；中英文案"
```

---

### Task 4: 各步工作区与章节页总装

**Files:** Create `src/components/workflow/SourceStep.tsx`、`GenerateStep.tsx`、`VersionBar.tsx`、`DownloadStep.tsx`、`ChapterWorkflow.tsx`；Delete `src/components/ChapterPage.tsx`；Modify `src/App.tsx`、`tests/flow.test.tsx`、`src/i18n/*`

这一步是搬家加重排，**不改任何业务行为**。把 `ChapterPage.tsx` 拆开：

- [ ] **Step 1: `SourceStep`（①）** — 章节标题输入框、删除章节、原文 `textarea`（加 `id="chapter-source"`）、字数与预计批数、读取 .txt、已采用版锁定原文的提示。**状态上提**：`title`/`text` 的本地编辑状态放在 `ChapterWorkflow` 里（`textDirty` 要给 `primaryFor` 用），`SourceStep` 只收 `title, text, locked, onTitle, onText, onDelete`。原「保存章节」按钮去掉（主按钮「保存原文」接管）。保留文字：「本章原文」「读取 .txt」「删除章节」「已有采用版，原文已锁定」、placeholder 里把「转换为忠实分镜 IR」改成「生成忠实分镜」。

- [ ] **Step 2: `GenerateStep`（②）** — 一行「本章原文 · N 字」+「修改原文」（切到 ①）；旁白模式下拉、严格模式勾选（原样搬，文字不变）；生成中时显示一行「生成中…」与「查看进度」（调 `onOpenJob(jobId)`；`jobId` 由 `ChapterWorkflow` 从 App 传入的 `running` 里找本章的那个）。生成按钮本身是右下角主按钮，工作区里不再放按钮；`ChapterWorkflow` 把 `mode`/`strict` 状态放在自己这里，主按钮 `generate` 动作调 `onConvert({ narration_mode?, strict })`。

- [ ] **Step 3: `VersionBar`** — 原样搬「版本」条（版本按钮、采用此版、删除此版、采用版说明）与章后整理那一段（含「重跑」）。显示在步骤条下方，②–⑥ 都显示（有版本时）。

- [ ] **Step 4: `DownloadStep`（⑥）** — 输入 `version: VersionRef`、`film: FilmSession`、`compose: ComposePreview | null`。用 `finalEpisodes(film.final?.files ?? [])`（`@/compose`）列每集一张卡：集号、「下载成片 mp4」「下载字幕 srt」按钮，再加一个「合成报告」按钮（`film.final.report` 有值时）。点按钮：`filmFileUrl(nid, cid, vid, path)` 拿 blob URL → 建 `<a download>` 点一下 → `URL.revokeObjectURL`。失败就在卡片下方显示原因。旁边次要按钮「回到画布重新合成」（调 `onOpenFilm`）。文字进语言包（`flow.download.*`：`title`「每集成片」、`mp4`「下载成片」、`srt`「下载字幕」、`report`「合成报告」、`recompose`「回到画布重新合成」、`failed`「下载失败：{reason}」；英文对应 "Episodes" / "Download video" / "Download subtitles" / "Mix report" / "Back to canvas to recompose" / "Download failed: {reason}"）。

- [ ] **Step 5: `ChapterWorkflow`** — props 与原 `ChapterPage` 相同，另加：`doc`、`docVid`、`dirty`、`saving`、`verificationFailed: boolean`、`running: JobSummary[]`、`onOpenJob`、`onSave`、`storyboard: ReactNode`（App 把现有 `VerificationPanel` + `StoryboardView` 作为一个节点传进来，`VerificationPanel` 外包 `<div id="verification">`）、`openFilm: () => void`、`flow: ReturnType<typeof useChapterFlow>`（App 里调用，因为 `StoryboardView` 的 `onCanvasClose` 要调它的 `reload`）。内部：
  - 组装 `FlowInput`：`hasText = chapter.text.trim().length > 0`，`textDirty`（同原 `ChapterPage` 的 `dirty` 计算），`version = chapter.versions.find(v => v.id === docVid) ?? null`，其余来自 props 与 `flow`。
  - `const cur = currentStep(input)`；`const [view, setView] = useState(cur)`；用 `useRef` 记上一次的 `cur`，**`cur` 往后走时** `setView(cur)`，并按新完成的那一步弹浮动提示（`toast.success(t('flow.done.storyboard', { shots: version.shots }))` 等，从 `sonner` 导入 `toast`；只在 storyboard / render / compose 三步完成时提示）。
  - 布局：标题行（小说名 + 章节标题 —— 标题输入框在 ① 里，这里只显示文字）、`Stepper`、`VersionBar`、按 `view` 渲染工作区：`import` → `SourceStep`；`storyboard` → `GenerateStep`；`review`/`render`/`compose` → `storyboard` 节点（没有 `doc` 时显示 `EmptyState`「还没有分镜」+ 去第 2 步）；`download` → `DownloadStep`（没有成片时 `EmptyState` + 去第 5 步）。工作区切换用 `useMotionPresets().enter`，以 `view` 作 key。
  - `PrimaryBar primary={primaryFor(view, input)}`；`onRun` 按 `action` 分派：`saveText` → `onSaveText`（与原保存逻辑相同的 patch）；`goto` → `setView(primary.goto)`；`generate` → `onConvert`；`save` → `onSave`；`openFilm` → `openFilm()`。`onFix(fix)`：有 `step` 先 `setView(step)`，有 `target` 再在下一帧（`requestAnimationFrame`，没有就 `setTimeout(0)`）调 `flashTarget(target)`。
  - 生成中 `GenerateStep` 时主按钮显示「生成中…」且禁用（`primaryFor` 已处理）。

- [ ] **Step 6: 接进 App** — `src/App.tsx`：
  - `const flowVersion = novel && chapter && docVid ? { nid: novel.id, cid: chapter.id, vid: docVid } : null`；`const flow = useChapterFlow(flowVersion)`（放在所有 early return 之前）；保存成功后调 `flow.reload()`。
  - `const [openFilmN, setOpenFilmN] = useState(0)`；`StoryboardView` 传 `openFilm={openFilmN}`、`onCanvasClose={() => void flow.reload()}`。
  - 把 `{novel && chapter && <ChapterPage …/>}` 换成 `<ChapterWorkflow …/>`，并把原来 App 下方渲染的 `VerificationPanel` + `StoryboardView` **在章节打开时**作为 `storyboard` 节点传给它（没有打开章节时——本地 JSON、分批预览——维持原位置渲染）。`JobPanel` 留在原位。
  - `verificationFailed = verification?.status === 'failed'`。
  - `git rm src/components/ChapterPage.tsx`。

- [ ] **Step 7: 更新流程测试** — `tests/flow.test.tsx`。只做因界面改动必须改的地方，每处保留原断言意图：
  - fetch 桩：`/film/` 路径一律返回 `err(404, '还没有出片会话')`（放在版本路由匹配之前），这样章节级读取得到「没有会话」。
  - 加帮手：`const goStep = (id: string) => click(container.querySelector(`[data-step="${id}"]`) as unknown as HTMLElement)`、`const primary = () => container.querySelector('[data-testid="primary-action"]') as unknown as HTMLButtonElement`。
  - 「开始转换」→ 先 `goStep('storyboard')`（新章节没有版本时本来就停在 ②，可省），点 `primary()`，断言文字「生成分镜」。「重新转换（新版本）」→ `goStep('storyboard')` 后点 `primary()`，断言文字「重新生成（新版本）」。
  - step 3 的 `has('本章原文')` 保留（②工作区有「本章原文 · N 字」）；`has('转换中…')` 改为 `has('生成中…')`。
  - 编辑原文再保存的步骤（若有，找「保存章节」）：先 `goStep('import')`，改完点 `primary()`（「保存原文」）。
  - step 6 打开章节后应停在 ④（没有出片会话）：加断言 `container.querySelector('[data-step="render"][aria-current="step"]')`，分镜、版本条断言不变。
  - 其余步骤需要看到分镜视图时，当前停在 ③/④ 都会显示，一般不用改；需要原文框时 `goStep('import')`。
  - 新增一段断言（放在 step 17 验证结果之后）：复验不通过时 `goStep('render')`，`[data-testid="primary-reason"]` 含「完整性检查没通过」，点 `[data-testid="primary-fix"]` 后停在 ③（`[data-step="review"][aria-current="step"]`）。

- [ ] **Step 8: 验证与提交** — `npm test`（13 个 ALL PASS）、lint、build。

```bash
git add src/components/workflow src/App.tsx tests/flow.test.tsx src/i18n/zh.ts src/i18n/en.ts
git rm -q --cached src/components/ChapterPage.tsx 2>/dev/null; git add -u src/components/ChapterPage.tsx
git commit -m "章节页改成六步工作流：步骤条与版本条在上，按步骤显示原文、生成、分镜、下载工作区，右下角主按钮接管保存原文、生成、保存、去出片与配音合成；进章节停在该做的一步，往后走时自动跟上并提示结果；流程测试按步骤导航"
```

---

### Task 5: 未保存提示条与撤销、离开提醒、完成通知

**Files:** Modify `src/App.tsx`、`tests/flow.test.tsx`

- [ ] **Step 1: 撤销基准** — App 加 `const savedDoc = useRef<Storyboard | null>(null)`：每次 `setDoc` 来自后端（打开版本、任务完成、保存成功、打开本地 JSON）时同步 `savedDoc.current = 那份 doc`；`onChange` 编辑不改它。`undo = () => { if (savedDoc.current) { setDoc(savedDoc.current); setDirty(false) } }`。
- [ ] **Step 2: 提示条** — 在 `AppShell` 内容区末尾渲染 `<UnsavedBar show={dirty && docVid !== null} saving={saving} onSave={save} onUndo={undo} />`。
- [ ] **Step 3: 离开提醒** — `useEffect`：`dirty` 为真时挂 `beforeunload`（`e.preventDefault(); e.returnValue = ''`），否则卸掉。`confirmLeave` 的提示文字改用 `t('flow.leave')`。
- [ ] **Step 4: 完成通知** — `announce` 里在原 `notify(...)` 之外加浮动提示：成功 `toast.success(标题, { description: who, action: { label: t('flow.view'), onClick: () => 打开那一章 } })`，失败 `toast.error(...)`。「打开那一章」：`j.novel_id && j.chapter_id` 时先 `openNovel(novel_id)` 再 `openChapter(chapter_id)`（沿用 App 里现有函数；若 `openChapter` 依赖已打开的小说，就按现有侧栏点击章节的同一路径调用），否则 `openJob(j.id)`。`announce` 用 ref 拿最新的打开函数，保持 `useCallback` 依赖不变。
- [ ] **Step 5: 测试** — `tests/flow.test.tsx` 在编辑并保存的步骤（step 8/9）里补：编辑后 `has('有未保存的修改')`；先点提示条里的「撤销」→ 内容回到原样、提示条消失；再改一次，点提示条的「保存」→ 保存成功、提示条消失（替换原来点「保存修改」那一下，或两者都测）。
- [ ] **Step 6: 验证与提交** — `npm test`、lint、build。

```bash
git add src/App.tsx tests/flow.test.tsx
git commit -m "未保存提示条（保存、撤销回到上次保存）、关页面前提醒、生成完成的浮动提示（可点回结果）"
```

---

### Task 6: 小说页章节卡片、去掉重复的新建入口

**Files:** Modify `src/components/NovelPage.tsx`、`src/components/NovelSidebar.tsx`、`src/App.tsx`、`src/i18n/*`、`tests/flow.test.tsx`

- [ ] **Step 1: 「章节」页签** — `NovelPage` 的 `Tab` 加 `'chapters'`，放第一个，文字「章节」；默认页签 `pending ? 'lifecycle' : 'chapters'`。新 props：`running: JobSummary[]`、`onNewChapter: () => void`（App 传现有 `newChapter`）。内容是卡片网格（`grid gap-4 sm:grid-cols-2 lg:grid-cols-3`），每章一张 `Card`（`@/components/ui/card`），整卡可点（`onOpenChapter`），依次进场（`useMotionPresets().item(i)`）：
  - 标题、字数、版本数；
  - 状态徽章（`Badge`）：本章在 `running` 里 →「生成中」（带 `animate-pulse` 小圆点）+ 下方 `Progress`（值 = `progress.done_chars / total_chars * 100`，没有进度时不显示）；`adopted_version` →「已采用」；`latest_status === 'failed'` →「失败」（destructive）；有版本 →「已生成」；否则「未生成」。
  - 最后一张虚线卡「＋ 新章节」调 `onNewChapter`。
  - 没有章节时用 `EmptyState`（`@/components/common/EmptyState`）：「还没有章节，从导入第一章开始」+ 按钮「＋ 新章节」。
  - 文字进语言包 `novel.*`（`chapters`「章节」、`chars`「{n} 字」、`versions`「{n} 个版本」、`status.{running,adopted,failed,generated,none}`、`newChapter`「＋ 新章节」、`empty`「还没有章节，从导入第一章开始」；英文对应）。
- [ ] **Step 2: 去掉侧栏「＋ 新小说」** — `NovelSidebar` 删掉那个按钮与 `onNewNovel` prop；App 调用处同步。
- [ ] **Step 3: 流程测试** — 依赖小说页默认页签的断言（打开小说后直接找「制作参数」内容的地方）先点「制作参数」页签；补一段：打开小说页默认是「章节」，卡片含章节标题与「已采用」，点卡片进入章节。
- [ ] **Step 4: 验证与提交** — `npm test`、lint、build。

```bash
git add src/components/NovelPage.tsx src/components/NovelSidebar.tsx src/App.tsx src/i18n/zh.ts src/i18n/en.ts tests/flow.test.tsx
git commit -m "小说页加「章节」卡片网格（状态徽章、生成中进度条、依次进场、新章节卡与空状态）；去掉侧栏重复的新建小说"
```

---

### Task 7: 回归与验收准备（控制者做）

- [ ] `npm test`（13 个 ALL PASS）、`npm run lint`（0 error、6 warning）、`npx vite build`。
- [ ] 确认本地服务在跑（假出片、假配音），请用户看：新建小说导入两章 → 小说页章节卡 → 进章节停在 ② → 生成（假模型需真实 key 时用已有小说）→ 自动停到 ④、步骤条打勾动效与「分镜已生成」提示 → 点灰掉的 ⑥ 看说明 → 改一处分镜看未保存提示条、撤销 → ④ 主按钮打开画布并停在「出片」→ 出片、合成后关画布 → 停到 ⑥ 下载。
