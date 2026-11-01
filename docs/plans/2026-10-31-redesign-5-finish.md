# 前端改版 5：收尾（管理后台、小说页与外壳换装、危险确认、新手引导与空状态、英文全译、删除 index.css）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把改版收尾：管理后台、小说页各页签、新建小说表单、分段选取、任务面板、侧边栏换成新视觉；删除、覆盖这类危险操作统一走确认对话框；加 3–4 个可跳过的新手提示和空状态；转瞬即逝的结果提示改成 toast、加载一律骨架屏；界面上所有硬编码文字进语言包并补齐英文；最后删除 `src/index.css`。功能与交互不变。

**Architecture:** 非组件模块（`labels.ts`、`compose.ts`、`film.ts` 等）的文字用新加的 `tr()`，它读模块级「当前语言」（由 `I18nProvider` 同步设置）；枚举标签表用 `localized(zh, en)` 包成按当前语言取值的对象，调用方不用改。危险确认用 `useConfirm()` 钩子，返回 `[ask, ui]`：组件自己把 `ui` 渲染出来，`await ask({...})` 拿到真假，因此不需要全局 Provider，单测直接渲染组件也能用。旧 `index.css` 按区域搬进新样式文件（`admin.css`、`novel.css`、`shell.css`、`controls.css`），最后剩下的元素基础规则并进 `app.css` 的 `@layer base`，再删文件。英文覆盖用一个静态检查兜底：`src/` 里除注释和 `i18n/zh.ts` 外不许出现中文字符，各任务逐步把自己的文件加进检查名单，最后一个任务改成全量检查。

**Tech Stack:** React 19、TS 6、Tailwind v4、shadcn（Radix）、motion、lucide-react、sonner、happy-dom。

**Spec:** `docs/specs/2026-10-31-frontend-redesign-design.md` 第 1 节（国际化、组件层）、第 4.4 节（新手引导、空状态）、第 5 节（管理后台、全局反馈）、第 6 节（动效）、第 7 节第 5 条、第 8 节。

---

## 全局约束

- 提交只 `git add` 具体文件，不用 `git add -A` / `git commit -a`；提交信息用中文、按仓库的描述式写法，**不带任何 Claude 署名**（不要 `Co-Authored-By`、不要 `Claude-Session`）。
- 命令在 `frontend/` 下执行。每个任务结束都要过三项：
  - `npm test`：全部 13 套 `ALL PASS`。
  - `npm run lint`：0 error，不新增 warning（现有 6 个）。
  - `npx vite build`：成功。
- **功能与交互不变**：
  - 不改 `api.ts` 的请求行为、`edit.ts`、`resolve.ts`、`timeline.ts`、`timelineOps.ts`、`useFilm.ts`、`useCompose.ts`、`useKeyframes.ts`、`useJob.ts`、`workflow.ts` 的逻辑。
  - 这些文件里给用户看的文字可以改成 `tr()` / `t()`。
- **测试**：
  - 测试固定用中文。不包 `I18nProvider` 时默认中文；模块级当前语言默认 `'zh'`。
  - 测试里断言的中文字面量随语言包调整。
  - 测试钩子类名保留，`grep -ohE "querySelector(All)?\('[^']+'\)" tests/*.tsx` 可复查。这次涉及的区域包括：`adm__row adm__search adm__chart adm__bad hnovel hrun hchap__item lib__search cpick cpick__wrap form__text cons__item tabs__btn is-on vchip login__field`。
  - `.login__field` 已在子计划 2 改掉；如果测试里还有，以测试实际为准。
- **样式文件规则**：
  - 新文件在 `src/styles/app.css` 里用 `@import "./xxx.css" layer(components);` 引入，位置放在已有的四个 import 之后。
  - 新文件**不许引用旧变量**：`--bg --panel --panel-2 --text --muted --faint --line --line-2 --accent --accent-soft --explicit --inferred --transition --danger --warn-bg --radius --mono`。
  - 只用 shadcn / 品牌变量和 `--tone-*`、`--font-mono`。可用变量的清单见子计划 4 的全局约束（`docs/plans/2026-10-31-redesign-4-workbench.md`）。
- **视觉基调**同子计划 4：
  - 卡片：1px `--border` 描边，`--card` 底，圆角 `calc(var(--ui-radius) + 2px)`。
  - 悬停只抬描边色，加极轻阴影。
  - 字号只用三级：标题 15–16px 600、正文 14px、辅助 12px `--muted-foreground`。
  - 每屏最多一种强调色。
  - 动效 150–400ms 缓出，减少动态效果时不位移。
- **语言包**：
  - 新键加在 `src/i18n/zh.ts`，`en.ts` 同步加，键结构必须一致（类型和 foundation 测试都会查）。
  - 插值写 `{name}`。
  - 英文要地道、简短，面向海外创作者，不逐字直译。术语对照：
    - 分镜 → storyboard
    - 镜头 → shot
    - 集 → episode
    - 原文 → source text
    - 完整性检查 → integrity check
    - 出片 → render
    - 配音合成 → voice & mix
    - 成片 → final cut
    - 资产卡 → asset card
    - 长期记忆 → story memory
    - 采用此版 → use this version
- 后端返回的错误文字是中文，不在本计划范围（后端不改），原样显示。
- 不碰后端，不碰 `docs/specs/2026-10-27-commercialization-design-contract.md`，不读 `backend/.env`。

## 实施裁定

1. **非组件文字用模块级当前语言**。`App` 本身调用 `useI18n()`，代码里没有 `memo`，所以切换语言时整棵树会重渲染，`tr()` 和 `localized()` 取到的都是新语言。如果以后有组件用 `useMemo` 缓存了翻译后的文字，依赖里要带上 `locale`。
2. **`useConfirm` 不用全局 Provider**，而是返回 `[ask, ui]`。
   - 原因：管理后台、画布等单测直接渲染组件，没有 App 外壳。
   - 测试里原来的 `g.confirm = …` 桩改成在 `document.body` 里找 `[data-testid="confirm-dialog"]`，再点确认或取消。
3. **`confirmLeave`（离开前确认有未保存修改）改成异步**：`confirmLeave(): Promise<boolean>`。
   - 调用处 `if (!(await confirmLeave())) return`。
   - `beforeunload` 仍是浏览器原生提示，不动。
4. **管理后台用户表**已经支持排序和搜索，本计划只换装：
   - 表头排序改成图标，搜索框改成 shadcn `Input`。
   - 概览卡片加迷你折线图。概览接口只给每日金额，所以「30 天金额」卡用 `data.daily` 画迷你折线，其他卡只显示数字。
5. **`.btn` 全部换成 shadcn `Button`**（31 处），对照规则：

   | 旧写法 | 新写法 |
   |---|---|
   | `btn` | `Button` |
   | `btn--sm` | `size="sm"` |
   | `btn--ghost` | `variant="ghost"`，有描边的用 `variant="outline"` |
   | `btn--danger` | `variant="destructive"` |

   `.tag` 换 `Badge variant="secondary"`。`.field`、`.check`、`.vchip`、`.cons`、`.alert`、`.empty`、`.tabs` 这些类名有测试钩子或多处共用，搬进 `controls.css` 用新变量重写，保留类名。
6. **新手引导**做成「按目标出现」的独立提示，不做强制的分步向导：
   - 每条提示有一个 id 和一个目标选择器 `[data-tour="…"]`。
   - 目标在页面上、且这条没看过，才显示。
   - 一次只显示一条，按「知道了」或「跳过全部」关掉。
   - 看过的 id 存在 `localStorage` 的 `inkreel.tour`（JSON 数组）里。
   - 测试环境默认关闭：`tourEnabled()` 在 `navigator.userAgent` 含 `HappyDOM` 时返回 false，`Tour` 允许传 `force` 打开它测试自己。这样不干扰现有 13 套测试。
7. **toast 与内联提示的分工**：
   - 转瞬即逝的结果（「已停用该账号」「已保存」「已复制」「采用成功」等）改成 `toast.success` / `toast.error`。
   - 跟输入框绑在一起的校验错误、需要用户读完再处理的长说明，仍留在原位。
   - 测试里断言这类提示文字的地方改成断言 toast：sonner 渲染在 `<Toaster>` 里，单测没挂它。要把 `toast` 包一层 `src/lib/notice.ts` 的 `notice.ok(msg)` / `notice.err(msg)`，内部调 sonner，并把最后几条记进 `notice.log`（只在测试读）。
8. **静态中文检查**放在 `tests/foundation.test.tsx` 里（node 读文件）：
   - 去掉 `/* … */`、`{/* … */}` 和行内 `// …`（`//` 前面要是行首或空白，避免误伤网址）之后，在剩下的文本里找 `[一-鿿]`。
   - Task 1 建立名单 `I18N_FILES`，之后每个任务把自己翻译完的文件加进去。
   - Task 8 把名单换成「`src/` 下全部 `.ts` / `.tsx`，排除 `src/i18n/zh.ts`」。`src/i18n/core.ts` 里语言菜单的「中文」两个字是有意保留的，加进白名单。

## 文件结构

| 文件 | 职责 |
|---|---|
| `src/i18n/core.ts` | 修改：模块级当前语言、`tr()`、`localized()` |
| `src/i18n/index.tsx` | 修改：Provider 同步设置当前语言 |
| `src/i18n/zh.ts`、`en.ts` | 修改：各任务新增的键 |
| `src/labels.ts`、`presets.ts`、`compose.ts`、`film.ts`、`api.ts`、`chapters.ts`、`useKeyframes.ts`、`types.ts` 等非组件模块 | 修改：文字走 `tr()` / `localized()` |
| `src/lib/notice.ts` | 新建：toast 封装（带测试可读的记录） |
| `src/components/common/ConfirmDialog.tsx` | 新建：`useConfirm()` 与危险确认对话框 |
| `src/components/common/Tour.tsx`、`src/tour.ts` | 新建：新手提示与「看过」记录 |
| `src/styles/admin.css`、`novel.css`、`shell.css`、`controls.css` | 新建：从 `index.css` 搬来并用新变量重写 |
| `src/index.css` | 逐任务删段，Task 8 删除文件 |
| `src/components/admin/*` | 修改：换装、骨架屏、toast、确认、英文 |
| `src/components/NovelPage.tsx`、`NovelAssets.tsx`、`NewNovelForm.tsx`、`ParamsForm.tsx`、`CardPicker.tsx`、`SelectOrCustom.tsx`、`JobPanel.tsx`、`JobProgress.tsx` | 修改：换装、确认、英文 |
| `src/components/NovelSidebar.tsx`、`src/App.tsx` | 修改：换装、骨架屏、空状态、确认、英文 |
| `src/components/StoryboardView.tsx`、`EpisodeView.tsx`、`ShotCard.tsx`、`AssetsView.tsx`、`SourceView.tsx`、`RenderView.tsx`、`VerificationPanel.tsx` | 修改：英文 |
| `src/components/TimelineCanvas.tsx`、`CanvasPanels.tsx`、`FilmPanel.tsx`、`ComposePanel.tsx` | 修改：英文、确认 |
| `tests/*.test.tsx` | 修改：随确认框、toast、文字同步；新增引导、确认、语言测试 |

---

### Task 1: 非组件文字的国际化底座

**Files:**
- Modify: `src/i18n/core.ts`、`src/i18n/index.tsx`
- Modify: `src/labels.ts`、`src/presets.ts`、`src/compose.ts`、`src/film.ts`、`src/api.ts`、`src/chapters.ts`、`src/useKeyframes.ts`、`src/useFilm.ts`、`src/useCompose.ts`、`src/edit.ts`、`src/resolve.ts`、`src/types.ts`、`src/theme.ts`、`src/auth.ts`、`src/notify.ts`、`src/main.tsx`
- Modify: `src/i18n/zh.ts`、`src/i18n/en.ts`
- Test: `tests/foundation.test.tsx`

- [ ] **Step 1: 写失败测试**。在 `tests/foundation.test.tsx` 末尾（`ALL PASS` 之前）加：

```tsx
// 非组件文字：tr / localized 跟着当前语言走
const core = await import('../src/i18n/core')
const labels = await import('../src/labels')
core.setCurrentLocale('en')
must(labels.label(labels.SHOT_SIZE, 'wide') === 'Wide', '枚举标签（英文）')
must(core.tr('common.cancel') === 'Cancel', 'tr（英文）')
must(Object.keys(labels.SHOT_SIZE).includes('close_up'), 'localized 可枚举')
core.setCurrentLocale('zh')
must(labels.label(labels.SHOT_SIZE, 'wide') === '远景', '枚举标签（中文）')

// 英文语言包里不许有中文
const cjk = /[一-鿿]/
const leaves = (o: unknown, p = ''): [string, string][] => typeof o === 'string' ? [[p, o]]
  : Object.entries(o as Record<string, unknown>).flatMap(([k, v]) => leaves(v, p ? `${p}.${k}` : k))
const bad = leaves(en).filter(([, v]) => cjk.test(v))
must(!bad.length, `英文包含中文：${bad.slice(0, 5).map(([k]) => k).join(', ')}`)

// 静态检查：名单里的源文件除注释外不许有中文（Task 8 改成全量）
const fs = await import('node:fs')
const path = await import('node:path')
const SRC = path.resolve(import.meta.dirname ?? '.', '../src')
const I18N_FILES = [
  'labels.ts', 'presets.ts', 'compose.ts', 'film.ts', 'api.ts', 'chapters.ts', 'useKeyframes.ts',
  'useFilm.ts', 'useCompose.ts', 'edit.ts', 'resolve.ts', 'types.ts', 'theme.ts', 'auth.ts', 'notify.ts', 'main.tsx',
]
const stripComments = (s: string) => s
  .replace(/\{\/\*[\s\S]*?\*\/\}/g, '').replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|\s)\/\/.*$/gm, '$1')
for (const f of I18N_FILES) {
  const hits = stripComments(fs.readFileSync(path.join(SRC, f), 'utf8')).split('\n')
    .map((l, i) => [i + 1, l] as const).filter(([, l]) => cjk.test(l))
  must(!hits.length, `${f} 还有硬编码中文：第 ${hits.slice(0, 3).map(([n]) => n).join('、')} 行`)
}
```

注意：`.ssrout` 里跑的是打包后的文件，`import.meta.dirname` 指向 `.ssrout`，所以 `../src` 正好是 `frontend/src`。如果实际不对，就改用 `process.cwd()` + `'src'`（`npm test` 在 `frontend/` 下执行）。以能跑通为准，并在报告里写明用的是哪种。

- [ ] **Step 2:** 跑 `npm test`，预期 foundation 失败在 `setCurrentLocale is not a function`。

- [ ] **Step 3: 实现底座**。在 `src/i18n/core.ts` 里加：

```ts
/** 模块级当前语言：给非组件代码（labels、compose、film…）用。I18nProvider 渲染时同步设置；没有 Provider 时为中文。 */
let current: Locale = 'zh'
export const currentLocale = () => current
export function setCurrentLocale(l: Locale) { current = l }
export const tr = (key: MsgKey, vars?: Record<string, string | number>) => translate(current, key, vars)

/** 枚举标签表：属性是 getter，按当前语言取值；Object.keys / entries 照常可用 */
export function localized<K extends string>(zh: Record<K, string>, en: Record<K, string>): Record<K, string> {
  const out = {} as Record<K, string>
  for (const k of Object.keys(zh) as K[]) {
    Object.defineProperty(out, k, { enumerable: true, get: () => (current === 'en' ? en[k] : zh[k]) })
  }
  return out
}
```

在 `src/i18n/index.tsx` 的 `I18nProvider` 函数体里、`useState` 之后、`return` 之前，同步调用 `setCurrentLocale(locale)`。这里故意在渲染阶段同步设置，不放进 effect：子组件在同一轮渲染里就要读到新语言。

- [ ] **Step 4: 改 `labels.ts`**：
  - 每张 `Record<…, string>` 表改成 `localized({ …中文… }, { …英文… })`，导出名和类型不变。
  - `APPEARANCE_FIELDS`、`VOICE_FIELDS` 改成函数 `appearanceFields()`、`voiceFields()`，返回按当前语言的数组，调用方同步改。
  - `fmtDuration`、`fmtEta` 走 `tr()`，新键放在 `zh.ts` 的 `time` 下：`time.minSec: '{m} 分 {s} 秒'`、`time.sec: '{s} 秒'`、`time.lessThanMin: '不到 1 分钟'`、`time.aboutMin: '约 {m} 分钟'`。英文对应：
    - `{m}m {s}s`
    - `{s}s`
    - `under a minute`
    - `about {m} min`

  英文枚举用影视行业常用叫法，例如：
  - `extreme_wide: 'Extreme wide'`
  - `close_up: 'Close-up'`
  - `push_in: 'Push in'`
  - `dutch: 'Dutch angle'`
  - `fade_to_black: 'Fade to black'`
  - `explicit: 'From source'`
  - `inferred: 'Added'`
  - `transition: 'Transition'`

  `JOB_STATUS` 的写法：`running: 'Generating'`、`draft_invalid: 'Draft failed check'`。

- [ ] **Step 5: 其余非组件模块**：把 Files 里每个文件给用户看的中文改成 `tr('…')`，新键按模块分组：`labels`、`presets`、`compose`、`film`、`api`、`chapters`、`keyframes`、`edit`。
  - `compose.ts` / `film.ts` 的拦截原因保持现有中文原意，子计划 4 改过的「说人话」措辞照抄进 `zh.ts`。
  - `presets.ts` 里给大模型的预设文本（会发给后端、写进分镜的内容）**不翻译**。只翻译下拉里显示给人看的名字：把显示名和取值拆开，显示名走 `tr`。
  - 判断一个字符串是给人看的还是给模型的：看它最后去哪。进 `fetch` 请求体或写进分镜文档的，不译。

- [ ] **Step 6:** `npm test`、`npm run lint`、`npx vite build` 全过。中文断言应该全部不变，因为测试默认中文。

- [ ] **Step 7: 提交**

```bash
git add src/i18n/core.ts src/i18n/index.tsx src/i18n/zh.ts src/i18n/en.ts src/labels.ts src/presets.ts src/compose.ts src/film.ts src/api.ts src/chapters.ts src/useKeyframes.ts src/useFilm.ts src/useCompose.ts src/edit.ts src/resolve.ts src/types.ts src/theme.ts src/auth.ts src/notify.ts src/main.tsx tests/foundation.test.tsx
git commit -m "非组件文字进语言包：模块级当前语言与 tr、枚举标签表按语言取值、时长与拦截原因等英文；英文包不含中文与源码硬编码中文的静态检查"
```

只 add 实际改动的文件。上面列出但没改的文件不要 add。

---

### Task 2: 统一危险确认 `useConfirm` 与 toast 封装

**Files:**
- Create: `src/components/common/ConfirmDialog.tsx`、`src/lib/notice.ts`
- Modify: `src/App.tsx`（第 268、430、448 行的 `confirm`）、`src/components/CanvasPanels.tsx:115`、`src/components/NovelAssets.tsx:91`、`src/components/NovelPage.tsx:56,287,374`、`src/components/admin/Users.tsx:99`
- Modify: `src/i18n/zh.ts`、`en.ts`（`confirm` 分组）
- Test: `tests/foundation.test.tsx`、`tests/admin.test.tsx`、`tests/canvas.test.tsx`、`tests/flow.test.tsx`

- [ ] **Step 1: 写 `ConfirmDialog.tsx`**

```tsx
/** 危险操作的确认（删除、覆盖、停用…）：全站统一。用法：
 *    const [ask, confirmUi] = useConfirm()
 *    if (!(await ask({ title, body, action, danger: true }))) return
 *    …  并在 JSX 里渲染 {confirmUi}
 *  不需要全局 Provider：单测直接渲染组件也能用。花钱的确认用 MoneyConfirm，不用它。 */
import { useCallback, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { buttonVariants } from '@/components/ui/button'
import { useI18n } from '@/i18n/core'

export interface ConfirmOpts {
  title: string
  body?: ReactNode
  /** 确认按钮文字，默认「确定」 */
  action?: string
  /** 红色确认按钮（删除、停用） */
  danger?: boolean
}

export function useConfirm(): [(o: ConfirmOpts) => Promise<boolean>, ReactNode] {
  const { t } = useI18n()
  const [opts, setOpts] = useState<ConfirmOpts | null>(null)
  const [open, setOpen] = useState(false)
  const resolver = useRef<((v: boolean) => void) | null>(null)
  const settle = (v: boolean) => {
    resolver.current?.(v)
    resolver.current = null
    setOpen(false) // opts 留着，关闭动画期间内容不消失
  }
  const ask = useCallback((o: ConfirmOpts) => new Promise<boolean>((res) => {
    resolver.current?.(false) // 上一个还没答就来新的：旧的当取消
    resolver.current = res
    setOpts(o)
    setOpen(true)
  }), [])
  const ui = opts && (
    <AlertDialog open={open} onOpenChange={(o) => { if (!o) settle(false) }}>
      <AlertDialogContent data-testid="confirm-dialog">
        <AlertDialogHeader>
          <AlertDialogTitle>{opts.title}</AlertDialogTitle>
          {opts.body && <AlertDialogDescription className="whitespace-pre-line">{opts.body}</AlertDialogDescription>}
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel data-testid="confirm-cancel" onClick={() => settle(false)}>{t('common.cancel')}</AlertDialogCancel>
          <AlertDialogAction data-testid="confirm-ok"
                             className={opts.danger ? buttonVariants({ variant: 'destructive' }) : undefined}
                             onClick={() => settle(true)}>
            {opts.action ?? t('confirm.ok')}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
  return [ask, ui]
}
```

如果 `buttonVariants` 没从 `button.tsx` 导出，就导出它（shadcn 默认导出）。`confirm.ok` 的中文是「确定」，英文是 `Confirm`。

- [ ] **Step 2: 写 `src/lib/notice.ts`**

```ts
/** 转瞬即逝的结果提示（右下角 toast）。log 只给测试读：单测没挂 <Toaster>。 */
import { toast } from 'sonner'

const log: { kind: 'ok' | 'err'; msg: string }[] = []
export const notice = {
  ok(msg: string, description?: string) { log.push({ kind: 'ok', msg }); toast.success(msg, { description }) },
  err(msg: string, description?: string) { log.push({ kind: 'err', msg }); toast.error(msg, { description }) },
  log,
}
```

- [ ] **Step 3: 替换 8 处 `confirm`**。文案放进 `zh.ts` 的 `confirm` 分组（英文同步），各处把原来的长句拆成「标题 + 说明」：

| 位置 | title | body | action |
|---|---|---|---|
| App 删版本 | 删除这个版本？ | 该操作不可撤销。 | 删除（danger） |
| App 删章节 | 删除「{title}」？ | 它的全部版本会删掉；写进长期记忆的资产卡、摘要与人物状态会一并撤回。 | 删除（danger） |
| App 离开确认 | 有未保存的修改 | 离开后这些修改会丢失。 | 离开（danger） |
| NovelPage 删小说 | 删除《{title}》？ | 全部章节、版本与长期记忆都会删掉，不可撤销。 | 删除（danger） |
| NovelPage 删限制 | 删除这条限制？ | — | 删除（danger） |
| NovelPage 删记录 | 删除这条记录？ | — | 删除（danger） |
| NovelAssets 删资产卡 | 删除资产卡 {id}？ | 已有分镜若引用了它，那份分镜再检查会报「引用不存在的资产」。 | 删除（danger） |
| CanvasPanels 未保存就重新生成 | 先不保存直接生成？ | 本版有未保存的修改，生成完成后画布会换成新版本。 | 直接生成 |
| admin Users | 确定要{label}？ | — | {label}（停用时 danger） |

  - `App.confirmLeave` 改成 `async () => !(dirty || textDirty) || ask({...})`，所有调用处改成 `await`。调用处在事件处理函数里的，把那个函数改成 `async`。
  - `NovelPage.tsx:287,374` 现在写的是 `onClick={() => confirm(...) && …}`，改成 `onClick={async () => { if (await ask({...})) … }}`。
  - 每个组件在根元素内渲染 `{confirmUi}`。
  - admin `Users.tsx` 的 `act` 成功后 `setMsg('已…')` 改成 `notice.ok(…)`，失败改成 `notice.err(errText(e))`，`adm__msg` 段删掉。

- [ ] **Step 4: 改测试**。删掉 `g.confirm = …` 桩，改用一个小助手（放在各测试文件里，按文件现有的 `click` / `act` 写法）：

```tsx
const confirmDialog = () => win.document.body.querySelector('[data-testid="confirm-dialog"]')
async function answer(ok: boolean) {
  const btn = win.document.body.querySelector<HTMLElement>(`[data-testid="${ok ? 'confirm-ok' : 'confirm-cancel'}"]`)
  must(!!btn, '应弹出确认框')
  await click(btn!)
}
```

  - `admin.test.tsx:170` 的 `confirms.some(… '停用')` 改成：确认框标题含「停用」，`answer(true)` 之后才发 PATCH。再加一条：先 `answer(false)`，断言没发请求。
  - `admin.test.tsx` 里断言 `adm__msg` 文字的地方改成断言 `notice.log` 的最后一条。
  - `canvas.test.tsx:339` 的 `asked` 改成：确认框出现、标题对，`answer(true)` 后 `onConvert` 被调用。
  - `flow.test.tsx:40` 的 `g.confirm = () => true`：
    - 找到真正触发确认的步骤（删版本、删章节、删小说、离开未保存），在那之后 `await answer(true)`。
    - 至少一处验证 `answer(false)` 不删除。
    - `grep -n "删除\|离开" tests/flow.test.tsx` 可以找到这些步骤。
  - `foundation.test.tsx` 加 `useConfirm` 的单测：渲染一个用它的小组件，点按钮后确认框出现，取消得到 `false`、确定得到 `true`；连续两次 `ask` 时第一次得到 `false`。

- [ ] **Step 5:** `grep -rnE "\bconfirm\(" src` 只剩 `useConfirm` / `MoneyConfirm` 相关。三项检查全过。

- [ ] **Step 6: 提交**（只 add 实际改动的文件）

```bash
git commit -m "危险操作统一确认对话框：删除版本、章节、小说、限制、记录、资产卡，离开未保存与画布里不保存直接生成，管理后台停用与改角色；结果提示改成右下角 toast"
```

---

### Task 3: 管理后台换装与英文

**Files:**
- Create: `src/styles/admin.css`；Modify: `src/styles/app.css`（import）、`src/index.css`（删掉 `/* ---------- 管理后台 ---------- */` 到文件末尾那段）
- Modify: `src/components/admin/AdminView.tsx`、`Overview.tsx`、`Users.tsx`、`UsageTab.tsx`、`JobsTab.tsx`、`AuditTab.tsx`、`LineChart.tsx`、`format.ts`
- Create: `src/components/admin/Sparkline.tsx`
- Modify: `src/i18n/zh.ts`、`en.ts`（`admin` 分组）
- Test: `tests/admin.test.tsx`、`tests/foundation.test.tsx`（`I18N_FILES` 加入 admin 下全部文件）

- [ ] **Step 1: 在 `admin.test.tsx` 里写失败断言**（先写断言，再动实现）：
  - 加载中显示骨架屏：`[data-slot="skeleton"]` 存在。shadcn 的 `skeleton.tsx` 带不带 `data-slot`，以实际为准；没有就给 `Skeleton` 加上。
  - 概览「30 天金额」卡里有 `[data-testid="sparkline"] path`。
  - 用 `<I18nProvider initial="en">` 渲染 `AdminView`，页签文字是 `Overview Users Usage Jobs Audit`。

- [ ] **Step 2: `Sparkline.tsx`**：
  - 内联 SVG，宽 100% 高 32，没有坐标轴。
  - 折线 `stroke: var(--primary)`，下方用同色 12% 透明度的面积填充。
  - 只有一个点时画一条水平线。
  - 带 `aria-hidden`。

- [ ] **Step 3: 换装**：
  - **AdminView**：
    - 标题用正文三级里的「标题」字号。
    - 「返回」用 `Button variant="ghost" size="sm"`，加 `ArrowLeft` 图标。
    - 页签改成和分镜视图一样的分段控件：`inline-flex rounded-lg bg-muted p-1`，每个按钮 `aria-pressed`，并保留 `tabs__btn` 和 `is-on` 类作测试钩子。照抄 `StoryboardView.tsx:186-202` 的写法。
  - **Overview**：
    - 卡片网格 `grid-cols-2 md:grid-cols-3 lg:grid-cols-6`，用 shadcn `Card`。
    - 数字用 22px 等宽、`tabular-nums`，标签 12px 辅助色。
    - 「30 天金额」卡下方放 `Sparkline`。
    - 「7 天失败」大于 0 时数字用 `--destructive`。
    - 未定价模型的提示用 `--warning` 左竖条。
    - 大折线图 `LineChart` 换新变量。
  - **Users**：
    - 搜索框改成 shadcn `Input`，左边放 `Search` 图标，保留 `adm__search` 类。
    - 表头排序用 `ArrowUp` / `ArrowDown` / `ArrowUpDown` 图标，并带 `aria-sort`。
    - 行悬停用 `--ui-muted` 底，展开的行左边加 2px `--primary` 竖条。
    - 角色和状态用 `Badge`：管理员 `default`，用户 `secondary`，已停用 `destructive`（保留 `adm__bad` 类）。
    - 金额列右对齐、`tabular-nums`。
    - 详情区的操作按钮用 `Button size="sm" variant="outline"`，停用用 `destructive`。
    - 输入框用 `Input`。
  - **UsageTab**：分组和时间范围改成分段控件，导出和刷新用 `Button variant="outline" size="sm"`，配图标 `Download`、`RefreshCw`。价格表编辑区用 `Textarea`，等宽字体。
  - **JobsTab、AuditTab**：同样的表格样式，状态用 `Badge`。
  - **加载**：所有 `加载中…` 改成 `<Skeleton>`：
    - 表格页：5 行，每行 `h-9`。
    - 概览：6 张卡大小的骨架，加一块图表高度的骨架。
  - **空数据**：用 `EmptyState`（图标 `Inbox`）加一句提示，例如「这段时间没有用量」「没有在跑的任务」「还没有审计记录」。
  - **错误**：错误文字用 `--destructive`，旁边放「重试」按钮，调用 `reload`。
- [ ] **Step 4: 英文**：
  - admin 下所有文字进 `zh.ts` 的 `admin` 分组。
  - `format.ts` 的 `PURPOSE` 用 `localized`。
  - `when` / `day` 的日期格式按 `currentLocale()` 选 `zh-CN` 或 `en-US`，看现有实现。
  - `LineChart` 的默认 `label` 走 `tr`。
- [ ] **Step 5: 样式**：`admin.css` 只保留表格、图表这类需要类名的规则，并改用新变量。从 `index.css` 删掉整段管理后台的旧规则。
- [ ] **Step 6:** 三项检查全过（`admin.test.tsx` 里中文断言随新文案调整）。
- [ ] **Step 7: 提交**

```bash
git commit -m "管理后台换装：分段页签、数字卡与 30 天金额迷你折线、表格排序图标与角色状态徽章、骨架屏加载、空状态与重试；后台文字全部进语言包并补英文"
```

---

### Task 4: 小说页各页签、新建小说表单、分段选取、任务面板换装与英文

**Files:**
- Create: `src/styles/novel.css`；Modify: `src/styles/app.css`、`src/index.css`。从 `index.css` 删掉这几段：
  - 「转换表单」
  - 旧表单控件给框的规则
  - 「章节 / 分段选取」
  - 「预设下拉」
  - 「历史资料卡」
  - 「钉卡」
  - 「任务面板」
  - 「进度」
  - 「资产库管理页」
  - 「搜索」
  - 「小说 → 章节导航」
  - 「小说页」
  - 「章节页」

  先 `grep -n "^/\* ---" src/index.css` 定位行号。
- Modify: `src/components/NovelPage.tsx`、`NovelAssets.tsx`、`NewNovelForm.tsx`、`ParamsForm.tsx`、`CardPicker.tsx`、`SelectOrCustom.tsx`、`JobPanel.tsx`、`JobProgress.tsx`
- Modify: `src/i18n/zh.ts`、`en.ts`（`novel`、`job`、`params`、`assets` 分组；已有的 `novel` 分组在原处扩充）
- Test: `tests/flow.test.tsx`、`tests/foundation.test.tsx`（`I18N_FILES` 加入这 8 个文件）

- [ ] **Step 1: 失败测试**。在 `flow.test.tsx` 里，用英文渲染一次小说页（看 flow 测试怎么挂 App；App 外面包 `<I18nProvider initial="en">`，或者用 foundation 里切语言的办法），断言页签文字含 `Chapters`，且「新章节」按钮的文字是英文。
- [ ] **Step 2: 换装**：
  - **NovelPage**：
    - 页签沿用新分段控件，保留 `tabs__btn` / `is-on`。
    - 主线剧情、创作限制、人物状态、摘要各区用 `Card`。
    - 列表项悬停抬描边；删除按钮用 `Button variant="ghost" size="icon"` 加 `Trash2` 图标和 `aria-label`。
    - 「删除小说」放进标题右边的 `DropdownMenu`（`MoreHorizontal` 图标），菜单项用红字。
  - **NovelAssets**：
    - 资产卡和分镜视图的资产卡同外观：分类图标照抄 `AssetsView.tsx` 里的图标映射，别重写一份；能导出的话就从 `AssetsView` 导出复用。
    - 搜索框用 `Input` 加 `Search` 图标，保留 `lib__search`。
    - 没有资产卡时用 `EmptyState`：「还没有资产卡，生成并采用一章分镜后会自动建立」。
  - **NewNovelForm、ParamsForm、SelectOrCustom**：表单用 `Label` + `Input` / `Textarea`，原生 `select` 套上新外观的类（`controls.css` 里的 `.field select`，Task 8 统一，这里先在 `novel.css` 写好）。提交按钮用 `Button`。
  - **CardPicker（钉卡）**：选中的卡用 `--primary` 描边和 `Check` 图标，保留 `cpick` / `cpick__wrap`。
  - **JobPanel、JobProgress**：
    - 进度条：已完成批次实心，正在跑的批次脉动；减少动态效果时不脉动，只保留透明度。
    - 日志最后一行用等宽辅助色。
    - 剩余时间用 `fmtEta`。
  - **结果提示**：`run()` 里的成功和失败提示改成 `notice.ok` / `notice.err`（失败的 `alert` 段删掉）。表单校验错误留在原位。
- [ ] **Step 3: 英文**：这 8 个文件的文字全部进语言包。
- [ ] **Step 4:** 三项检查全过。
- [ ] **Step 5: 提交**

```bash
git commit -m "小说页换装：分段页签与分区卡片、资产卡同分镜外观与空状态、表单与预设下拉、钉卡选中态、任务进度条；删除小说移进更多菜单；结果提示改 toast；这些页面文字补英文"
```

---

### Task 5: 侧边栏、外壳残留与 App 文字

**Files:**
- Create: `src/styles/shell.css`；Modify: `src/styles/app.css`、`src/index.css`（删掉「布局」「历史记录侧栏」「新外壳里小说列表」这几段，以及 `.svc`、`.main` 相关规则；`.main` 的窄屏规则一并搬走）
- Modify: `src/components/NovelSidebar.tsx`、`src/App.tsx`
- Modify: `src/i18n/zh.ts`、`en.ts`（`shell`、`app` 分组）
- Test: `tests/flow.test.tsx`、`tests/foundation.test.tsx`（`I18N_FILES` 加 `components/NovelSidebar.tsx`、`App.tsx`）

- [ ] **Step 1: 失败测试**（`flow.test.tsx`）：
  - 书架为空时，侧栏里有 `[data-testid="empty-state"]`，并带「新建小说」按钮。
  - 小说列表读取中显示 `Skeleton`，不再是「读取中…」文字。
- [ ] **Step 2: NovelSidebar**：
  - 小说项（保留 `hnovel` / `hrun` / `hchap__item` / `is-open`）悬停用 `--ui-muted` 底，当前项用 `--ui-accent` 底加 `--primary` 左竖条。
  - 生成中的小圆点用 `--primary` 加缓慢脉动（减少动态效果时不动）。
  - 删除按钮悬停才出现：`opacity-0 group-hover:opacity-100 focus-visible:opacity-100`。
  - 读取中显示 3 条 `Skeleton h-8`。
  - 书架空时显示 `EmptyState`：「还没有小说，从导入第一章开始」，按钮「新建小说」。按钮回调用侧栏现有的新建入口。
- [ ] **Step 3: App.tsx**：剩余文字全部进语言包，包括 `'删除这个版本？…'`（Task 2 已改）、保存提示、采用结果、错误提示等。转瞬即逝的提示改成 `notice`；画布上需要的提示（`bench.notice`）保持原样。
- [ ] **Step 4: 样式**：`shell.css` 用新变量重写搬来的规则。
- [ ] **Step 5:** 三项检查全过。
- [ ] **Step 6: 提交**

```bash
git commit -m "侧边栏换装：当前项竖条、生成中脉动圆点、悬停才出现的删除、骨架屏读取与空书架引导；App 剩余文字进语言包并补英文，结果提示改 toast"
```

---

### Task 6: 分镜区英文

**Files:**
- Modify: `src/components/StoryboardView.tsx`、`EpisodeView.tsx`、`ShotCard.tsx`、`AssetsView.tsx`、`SourceView.tsx`、`RenderView.tsx`、`VerificationPanel.tsx`
- Modify: `src/i18n/zh.ts`、`en.ts`（`board`、`shot`、`assets`、`source`、`renderPack`、`verify` 分组）
- Test: `tests/foundation.test.tsx`（`I18N_FILES` 加这 7 个）；`tests/real-doc.test.tsx` 或 `edit-validity.test.tsx` 加一条英文渲染断言

- [ ] **Step 1: 失败测试**：用 `<I18nProvider initial="en">` 渲染 `StoryboardView`（用 `real-doc.test.tsx` 现有的真实文档夹具），断言：
  - 视图切换文字为 `Shots Assets Source Render JSON`。
  - 统计卡有 `Coverage`。
  - 镜头卡的景别标签是英文，例如 `Wide`。
- [ ] **Step 2:** 这 7 个文件的文字全部进语言包。
  - 分镜文档里的内容（画面描述、台词、人物名）是用户数据，不译。
  - `TABS` 这类模块级常量数组改成在组件里用 `t()` 生成，或者存键名、渲染时再 `t()`。
- [ ] **Step 3:** 三项检查全过。
- [ ] **Step 4: 提交**

```bash
git commit -m "分镜区文字进语言包并补英文：总览、镜头卡、编辑说明、资产卡、原文溯源、渲染任务包、完整性检查"
```

---

### Task 7: 画布、出片与配音合成英文

**Files:**
- Modify: `src/components/TimelineCanvas.tsx`、`CanvasPanels.tsx`、`FilmPanel.tsx`、`ComposePanel.tsx`
- Modify: `src/i18n/zh.ts`、`en.ts`（`canvas`、`film`、`compose` 分组；`flow.chapter` 里重复的键直接复用，不另起）
- Test: `tests/foundation.test.tsx`（`I18N_FILES` 加这 4 个）；`tests/canvas.test.tsx` 加一条英文渲染断言

- [ ] **Step 1: 失败测试**：用英文渲染画布，断言侧栏页签文字是英文，底部工具条按钮的 `aria-label` 或 `title` 是英文。
- [ ] **Step 2:** 这 4 个文件的文字全部进语言包，包括 `title`、`aria-label`、SVG `<title>`、快捷键说明。
  - 金额格式 `¥x.xx` 不变（厂商按人民币计价）。
  - `MoneyConfirm` 的 `action`、`title` 走 `t()`。
  - `CanvasPanels` 已经在用 `flow.chapter.*` 的同义文案，改成直接用那些键。
- [ ] **Step 3:** 三项检查全过。
- [ ] **Step 4: 提交**

```bash
git commit -m "时间轴画布、出片与配音合成文字进语言包并补英文：泳道、工具条、快捷键说明、侧栏各页、花钱确认"
```

---

### Task 8: 通用控件迁移，删除 index.css

**Files:**
- Create: `src/styles/controls.css`
- Modify: `src/styles/app.css`：删掉 `@import "../index.css" layer(legacy);`；`@layer` 声明去掉 `legacy`；元素基础规则并进 `@layer base`
- Delete: `src/index.css`
- Modify: 所有还在用 `className="btn…"` 或 `tag` 的组件（`grep -rn "\bbtn\b\|\"tag\b\|tag " src/components src/App.tsx` 定位）
- Test: `tests/foundation.test.tsx`

- [ ] **Step 1: 失败测试**（`foundation.test.tsx`）：
  - `fs.existsSync(path.join(SRC, 'index.css')) === false`。
  - `src/styles/*.css` 里没有任何旧变量名（用全局约束里的清单写成正则，匹配 `var\(--(bg|panel|panel-2|text|muted|faint|line|line-2|accent|accent-soft|explicit|inferred|transition|danger|warn-bg|radius|mono)\)`）。
  - `src/` 下不再有 `className` 里含独立单词 `btn` 的地方。
  - 把 `I18N_FILES` 换成「递归列出 `src/` 下全部 `.ts` / `.tsx`，排除 `i18n/zh.ts`」，白名单只留 `i18n/core.ts` 的 `'中文'` 这一处：对 core.ts 先把 `'中文'` 字面量去掉再检查。
- [ ] **Step 2: `.btn` → `Button`**：按「实施裁定 5」的对照表全部替换，`.tag` 换成 `Badge variant="secondary"`。
- [ ] **Step 3: `controls.css`**：
  - 从 `index.css` 剩余部分搬来 `.tabs` / `.tabs__btn`、`.field`（含其中的 `select`、`input`、`textarea`）、`.check`、`.vchip`、`.cons`（小说页约束清单）、`.alert`、`.empty`、`.stat`（如果还在 index.css）和 `.main` 窄屏规则，用新变量重写。
  - 搬之前，先 `grep -rn "<类名>" src` 确认每条规则还有人用，没人用的直接删。
- [ ] **Step 4: 元素基础规则**：`index.css` 开头的 `* { box-sizing }`、`body`、`h1–h6`、`p`、`button, input…` 这些规则并进 `app.css` 的 `@layer base`。
  - `body` 的背景和文字色改用 `--background` / `--foreground`（`app.css` 已有的就不重复）。
  - 字体沿用 `var(--font-sans)`，中文回落系统字体。
  - 旧的 `:root` / `:root.dark` 变量块整体删除。
- [ ] **Step 5: 补齐漏网的中文**：全量静态检查找到的硬编码中文（`ui/*.tsx` 里 shadcn 自带的 `sr-only` 文字、`workflow/ChapterWorkflow.tsx` 等）全部进语言包。
- [ ] **Step 6: 删除 `src/index.css`**。三项检查全过。再在浏览器里粗看一遍（`npm run dev` 已经在 5173 上跑），确认深浅两套主题下没有元素丢了样式。代理看不了页面，就 `grep` 每个删掉的类名，确认组件里已经不用了。
- [ ] **Step 7: 提交**

```bash
git add -u src/index.css
git commit -m "删除旧样式表 index.css：按钮全换 Button、标签换 Badge，页签、表单项、勾选、版本条、约束清单与提示搬进 controls.css 并改用新变量，元素基础规则并入 app.css；源码全量无硬编码中文"
```

（`git add -u src/index.css` 只登记这一个文件的删除，其余改动的文件逐个 `git add`。）

---

### Task 9: 新手引导与完成度收尾

**Files:**
- Create: `src/tour.ts`、`src/components/common/Tour.tsx`
- Modify: `src/App.tsx`（挂 `<Tour />`）、`src/components/shell/AppShell.tsx`（新建小说按钮加 `data-tour="new-novel"`）、`src/components/NovelPage.tsx`（新章节按钮加 `data-tour="import"`）、`src/components/workflow/Stepper.tsx`（根元素加 `data-tour="steps"`）、`src/components/NovelSidebar.tsx` 或 `ChapterWorkflow.tsx`（生成进度入口加 `data-tour="progress"`）
- Modify: `src/i18n/zh.ts`、`en.ts`（`tour` 分组）
- Test: `tests/foundation.test.tsx`

- [ ] **Step 1: 写失败测试**（`foundation.test.tsx`）：

```tsx
const tour = await import('../src/tour')
const { Tour } = await import('../src/components/common/Tour')
localStorage.removeItem('inkreel.tour')
const host = win.document.createElement('div')
host.innerHTML = '<button data-tour="new-novel">新建</button>'
win.document.body.appendChild(host)
// 挂 <Tour force />，按项目现有的 root.render + act 写法
must(!!win.document.body.querySelector('[data-testid="tour-tip"]'), '目标在页面上就显示提示')
// 点「知道了」
must(tour.seen().includes('new-novel'), '看过的记进本机')
must(!win.document.body.querySelector('[data-testid="tour-tip"]'), '看过的不再显示')
// 再放一个 data-tour="import" 目标，点「跳过全部」→ seen() 包含全部 4 个 id
must(!tour.tourEnabled(), '测试环境默认不开引导')
```

- [ ] **Step 2: `src/tour.ts`**：

```ts
/** 新手提示：按目标出现、一次一条、看过的存在本机。 */
export const TOUR = ['new-novel', 'import', 'steps', 'progress'] as const
export type TourId = (typeof TOUR)[number]
const KEY = 'inkreel.tour'

export function seen(): TourId[] {
  try { return JSON.parse(localStorage.getItem(KEY) ?? '[]') as TourId[] } catch { return [] }
}
export function markSeen(ids: readonly TourId[]) {
  try { localStorage.setItem(KEY, JSON.stringify([...new Set([...seen(), ...ids])])) } catch { /* 只在本页生效 */ }
}
/** 测试环境（happy-dom）不开，免得挡住现有用例 */
export const tourEnabled = () => typeof navigator === 'undefined' || !/HappyDOM/i.test(navigator.userAgent)
```

- [ ] **Step 3: `Tour.tsx`**：
  - **轮询**：每 800ms，以及窗口 `resize` 时，找第一条「没看过、目标在 DOM 里且可见」的提示。可见的判断：`getBoundingClientRect` 宽高大于 0。
  - **位置**：渲染一张浮动卡片，用 `createPortal` 挂到 `document.body`，`data-testid="tour-tip"`，`role="dialog"`，`aria-live="polite"`。卡片放在目标下方 8px，放不下就放上方，水平方向夹在视口内、留 16px 边距。
  - **内容**：
    - 一行标题加一句话。
    - 右下角是「知道了」（主按钮），左下角是「跳过全部」（ghost 按钮）。
    - 右上角是进度「1 / 4」，按 `TOUR` 里的顺序算。
  - **高亮**：目标元素加 `data-tour-on` 属性，`app.css` 里给它一圈 `--primary` 的 2px 外描边和柔和光晕。关掉提示时去掉属性。
  - **动效**：进场缩放 0.96 到 1 加淡入（`useMotionPresets` 里已有的预设就用它）；减少动态效果时只淡入。
  - **快捷键**：按 Esc 等于「知道了」。
  - **开关**：没传 `force` 且 `!tourEnabled()` 时什么都不渲染。
- [ ] **Step 4: 文案**（`tour` 分组，中文；英文同步，写得像产品引导，简短）：
  - `new-novel`：「从这里开始」——「新建一部小说，把第一章原文贴进来。」
  - `import`：「一章一章导入」——「每章单独生成分镜，前面章节的人物和设定会自动沿用。」
  - `steps`：「跟着步骤走」——「顶部的步骤条会停在该做的那一步，主按钮就在右下角。」
  - `progress`：「生成要几分钟」——「可以离开去做别的，侧栏的圆点和右下角的提示会在完成时告诉你。」
- [ ] **Step 5: 挂载**：
  - 在 `App.tsx` 登录后的外壳里渲染 `<Tour />`。首页和登录对话框不显示。
  - 给四个目标加 `data-tour` 属性。`progress` 加在侧栏生成中小说的圆点上：只有在生成时才出现，正好对应「看进度」。
- [ ] **Step 6: 空状态补漏**：
  - 搜索没有结果时，侧栏和资产库都显示「没有匹配的…」加「清空搜索」按钮。
  - `DownloadStep` 和 `GenerateStep` 已经有空状态的，不动。
  - `grep -rn "暂无\|还没有\|empty" src/components` 确认没有漏掉的裸文字空状态。
- [ ] **Step 7:** 三项检查全过。
- [ ] **Step 8: 提交**

```bash
git commit -m "新手引导：新建小说、导入章节、步骤条、看进度四条可跳过的提示，按目标出现、一次一条、看过的存在本机；搜索无结果的空状态"
```

---

## 自查记录

- **规格覆盖**：
  - 管理后台的排序、搜索、卡片和迷你折线：Task 3。
  - 新手引导：Task 9。
  - 空状态：Task 3、4、5、9。
  - toast：Task 2–5。
  - 骨架屏：Task 3、5。
  - 危险操作确认：Task 2。
  - 英文补齐：Task 1、3–8。
  - 删除 `index.css`：Task 8。
  - 测试和 lint 要求：每个任务都过三项检查。
  - 「减少动态效果」：Task 4、5、9 都写明了降级方式。
- **类型一致**：
  - `useConfirm` 返回 `[ask, ui]`，Task 2 定义，Task 3 的 admin 沿用。
  - `notice.ok` / `notice.err` / `notice.log` 在 Task 2 定义，Task 3–5 使用。
  - `tr`、`localized`、`setCurrentLocale`、`currentLocale` 在 Task 1 定义。
  - `TOUR`、`seen`、`markSeen`、`tourEnabled` 在 Task 9 内部自洽。
- **顺序依赖**：
  - Task 8 必须在 3–7 之后，因为它要做全量检查，并且要等各区域已经搬走。
  - Task 9 要在 Task 8 之后，因为 `data-tour-on` 的样式写在 `app.css`，引导的目标元素也要先换装完。
