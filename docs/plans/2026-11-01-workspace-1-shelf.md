# 工作台改版 1：书架与新建 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 没打开小说时，主区是「新建主卡片 + 风格卡片 + 最近小说网格」。主卡片以贴原文为主角，底部用胶囊浮层选画幅、风格、音色和更多参数，并带「旁白解说 / 剧情演绎」二选一。小说「设置」页改用同一套参数组件。新增全站统一的 `StatusPill` 状态标签。

**Architecture:**
- 参数控件拆成 `src/components/params/` 下的几个小组件，新建页和设置页共用：
  - `RatioPicker`、`StylePicker`（风格卡片）、`VoicePicker`、`NarrationPick`（二选一）、`MoreParams`（色调、平台、风格前缀、旁白细项）、`ParamChip`（胶囊外壳：Popover 触发按钮）。
- 风格色块和每种风格的默认前缀放在 `src/styleLook.ts`。
- 新建页组件 `NewNovelComposer` 替换 `NewNovelForm`；书架页 `ShelfHome` 由「主卡片 + 最近小说」组成。
- 发给后端的参数值与现在逐字一致，只换界面。

**Tech Stack:** React 19、TS 6、Tailwind v4、shadcn（Radix Popover）、motion、lucide-react、happy-dom。

**Spec:** `docs/specs/2026-11-01-workspace-redesign-design.md` 第 5 节、第 10 节（`StatusPill`、视觉规则）、第 11 节第 1 条、第 13 节。前置设计 `docs/specs/2026-10-31-frontend-redesign-design.md` 的设计变量、动效、双语规则继续有效。

---

## 全局约束

- **提交**：只 `git add` 具体文件，不用 `git add -A` / `git commit -a`。提交信息用中文、写成描述式，**不带任何 Claude 署名**（不要 `Co-Authored-By`、不要 `Claude-Session`）。
- **检查**：命令在 `frontend/` 下执行。每个任务结束都要过：
  - `npm test`：全部套件 `ALL PASS`。Task 3 起多一套 `shelf`，共 14 套。
  - `npm run lint`：0 error，warning 不超过现有的 5 个。
  - `npx vite build`：成功。
- **逻辑不变**：
  - 发给后端的 `NovelParams` 取值，以及 `createNovel` / `createChapter` 的调用顺序，都与现在一致。现有流程见 `App.tsx` 的 `submitNovel`。
  - `parseChapters` 不改。
- **双语**：
  - 所有新文字进 `src/i18n/zh.ts`，`en.ts` 同步，键结构一致。
  - foundation 测试会全量扫描 `src/`，注释以外不许有中文（含全角标点）。
  - 写进分镜、发给模型的预设取值（中文）用 `presets.ts` 里的 `P('中文取值', 'presets.…')` 形式，这一形式已在静态检查的白名单里。
  - 英文要简短地道。术语沿用：storyboard、shot、render、mix、story memory、integrity check。
- **样式**：
  - 只用新设计变量，不许用旧变量；样式表里用到的变量必须有定义，foundation 测试会检查。
  - 优先用 Tailwind 工具类；需要类名的复杂样式放进 `src/styles/shelf.css`，在 `app.css` 里按 `layer(components)` 引入，位置放在其他 components 引入之后。
  - 深浅两套主题都要好看。
- **动效**：
  - 进场用 `useMotionPresets()`：`enter`、`item(i)`、`pop`。
  - 浮层缩放加淡入。
  - 系统开了减少动态效果时不位移。
- **测试**：固定用中文。不包 `I18nProvider` 时默认中文；用英文渲染的测试结束后要 `setCurrentLocale('zh')`。
- **不碰**：后端、`docs/specs/2026-10-27-commercialization-design-contract.md`、`backend/.env`。

## 实施裁定

1. **旁白二选一与细项的映射**：
   - 「旁白解说」写入 `selective`，「剧情演绎」写入 `none`。
   - 细项在「更多」里选。当前值是 `original_text` 或 `condensed` 时，二选一显示为「旁白解说」，并加一个角标写明细项名。
2. **风格卡片与风格前缀联动**：
   - 选风格卡片时写入 `art_style`。
   - 只要用户还没手改过 `style_prefix`，就同时写入这种风格的默认前缀。默认前缀是中文，会发给模型，在 `styleLook.ts` 里用 `P()` 定义。
   - 手改判定：`style_prefix` 不等于任何一种风格的默认前缀，且不等于 `DEFAULT_PARAMS.style_prefix`。
3. **最近小说卡片的封面**：`NovelSummary` 里没有画风参数，所以封面色块按小说 id 的哈希从风格色块里挑一套，而不是按风格。这一处与规格第 5 节有出入，记为已知差异。
4. **NewNovelForm 的去留**：保留文件名太误导，删除 `NewNovelForm.tsx`，`NewNovel` 类型搬到 `NewNovelComposer.tsx`。`App.tsx` 改为引用新组件。
5. **小说页「章节」网格页签**：本计划不动，第 2 个子计划去掉。
6. **风格卡片可换成用户的图片**（用户 2026-11-01 定：默认用代码画色块，用户上传了图片就替换）：
   - 每张风格卡片悬停时右下角出现「换图」小按钮（图标 `ImagePlus`），选图后在浏览器里缩成最长边 320px 的 JPEG（`canvas.toBlob`，质量 0.85），以 data URL 存进 `localStorage` 的 `inkreel.styleImages`（`{ [artStyle]: dataUrl }`）。
   - 有图时卡片用图（`object-cover`），没图用色块；有图时多一个「恢复默认」小按钮。
   - 读写都包 `try/catch`；存不下（超配额）时 `notice.err` 提示并保持色块。
   - **只是卡片的显示图，不参与生成**：不上传后端、不进参数。「风格参考图」要后端支持，仍按规格第 11 节第 4 条以后做。
   - 实现放在 `src/styleImages.ts`（`getStyleImage(id)`、`setStyleImage(id, file)`、`clearStyleImage(id)`、`useStyleImages()` 订阅变化），由 Task 2 的 `StylePicker` 使用。

## 文件结构

| 文件 | 职责 |
|---|---|
| `src/components/ui/popover.tsx` | 新建：shadcn Popover（Radix） |
| `src/components/common/StatusPill.tsx` | 新建：状态标签（圆点 + 文字，语义色淡底） |
| `src/styleLook.ts` | 新建：各风格的色块 CSS 与默认风格前缀 |
| `src/styleImages.ts` | 新建：风格卡片的用户替换图（本机存储） |
| `src/components/params/ParamChip.tsx` | 新建：胶囊按钮 + Popover 外壳 |
| `src/components/params/RatioPicker.tsx` | 新建：4 个比例框 |
| `src/components/params/StylePicker.tsx` | 新建：风格卡片行 |
| `src/components/params/VoicePicker.tsx` | 新建：音色列表（带描述） |
| `src/components/params/NarrationPick.tsx` | 新建：旁白解说 / 剧情演绎二选一 |
| `src/components/params/MoreParams.tsx` | 新建：色调、平台、风格前缀、旁白细项 |
| `src/components/NewNovelComposer.tsx` | 新建：新建主卡片（替换 `NewNovelForm.tsx`） |
| `src/components/ShelfHome.tsx` | 新建：书架首页（标题 + 主卡片 + 风格卡片 + 最近小说） |
| `src/components/NovelPage.tsx` | 修改：`ParamsTab` 改用 params 组件，竖版设置表单 |
| `src/components/ParamsForm.tsx` | 修改：只保留 `DEFAULT_PARAMS`、`Field`；`ParamsForm` 组件删除（没有调用方以后） |
| `src/App.tsx` | 修改：主区没有小说时渲染 `ShelfHome` |
| `src/styles/shelf.css`、`src/styles/app.css` | 新建、修改 |
| `src/i18n/zh.ts`、`en.ts` | 修改：`shelf`、`composer`、`params` 分组 |
| `tests/shelf.test.tsx`、`package.json` | 新建一套测试并加进 `npm test` |

---

### Task 1: 底层零件（Popover、StatusPill、styleLook）

**Files:**
- Create: `src/components/ui/popover.tsx`、`src/components/common/StatusPill.tsx`、`src/styleLook.ts`
- Modify: `src/i18n/zh.ts`、`en.ts`
- Create: `tests/shelf.test.tsx`；Modify: `package.json`（`test` 脚本末尾加 `&& vite build --ssr tests/shelf.test.tsx --outDir .ssrout --logLevel error && node .ssrout/shelf.test.js`）

- [ ] **Step 1: `popover.tsx`**（shadcn 标准写法，Radix 从 `radix-ui` 包取，与 `dropdown-menu.tsx` 同一种 import 方式）：

```tsx
import * as React from "react"
import { Popover as PopoverPrimitive } from "radix-ui"
import { cn } from "@/lib/utils"

function Popover(props: React.ComponentProps<typeof PopoverPrimitive.Root>) {
  return <PopoverPrimitive.Root data-slot="popover" {...props} />
}
function PopoverTrigger(props: React.ComponentProps<typeof PopoverPrimitive.Trigger>) {
  return <PopoverPrimitive.Trigger data-slot="popover-trigger" {...props} />
}
function PopoverContent({ className, align = "start", sideOffset = 6, ...props }:
  React.ComponentProps<typeof PopoverPrimitive.Content>) {
  return (
    <PopoverPrimitive.Portal>
      <PopoverPrimitive.Content data-slot="popover-content" align={align} sideOffset={sideOffset}
        className={cn(
          "z-50 w-72 rounded-xl border bg-popover p-3 text-popover-foreground shadow-lg outline-hidden",
          "data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0",
          "data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95",
          className)} {...props} />
    </PopoverPrimitive.Portal>
  )
}
export { Popover, PopoverTrigger, PopoverContent }
```

  减少动态效果时不缩放：在 `app.css` 的 `@media (prefers-reduced-motion: reduce)` 段里（没有就新加），对 `[data-slot="popover-content"]` 设 `--tw-enter-scale: 1; --tw-exit-scale: 1`。

- [ ] **Step 2: `StatusPill.tsx`**

```tsx
/** 全站统一的状态标签：圆点 + 文字，底色是语义色 12% 透明度；进行中的圆点缓慢脉动 */
import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

export type Tone = 'ok' | 'live' | 'warn' | 'err' | 'idle'
const TONE: Record<Tone, string> = {
  ok: 'var(--success)', live: 'var(--primary)', warn: 'var(--warning)',
  err: 'var(--destructive)', idle: 'var(--ui-muted-foreground)',
}

export function StatusPill({ tone, children, className }: { tone: Tone; children: ReactNode; className?: string }) {
  return (
    <span data-slot="status-pill" data-tone={tone}
          className={cn('status-pill inline-flex h-5 items-center gap-1.5 rounded-full px-2 text-xs font-medium', className)}
          style={{ ['--pill' as string]: TONE[tone] }}>
      <span className="status-pill__dot size-1.5 rounded-full" aria-hidden />
      {children}
    </span>
  )
}
```

  `shelf.css` 里：
  - `.status-pill` 的底色是 `color-mix(in oklab, var(--pill) 12%, transparent)`，文字色是 `color-mix(in oklab, var(--pill) 85%, var(--foreground))`。
  - `.status-pill__dot` 用 `var(--pill)` 填色。
  - `[data-tone="live"] .status-pill__dot` 做 1.6s 透明度脉动，减少动态效果时不动。

  `--pill` 是在 TSX 里内联设置的变量，要加进 foundation 测试的 `inline` 白名单（`tests/foundation.test.tsx` 里 `new Set(['--mood'])` 那一行）。`--success`、`--warning`、`--ui-muted-foreground` 在 `app.css` 里已有定义，写之前 `grep` 核对一遍。

- [ ] **Step 3: `styleLook.ts`**：每种 `art_style` 一套色块，外加一个默认风格前缀。

```ts
/** 风格卡片的色块（代码画，不用图片）与选中时带出的默认风格前缀。
 *  前缀是中文、会发给模型，按预设惯例用 P() 写（取值不译，显示名走语言包）。 */
import type { Preset } from './presets'
import { tr } from './i18n/core'
import type { MsgKey } from './i18n/core'

const P = (value: string, key: MsgKey): Preset => ({ value, get label() { return tr(key) } })

export interface StyleLook { id: string; swatch: string; prefix: Preset }

export const STYLE_LOOKS: StyleLook[] = [
  { id: 'realistic', swatch: 'linear-gradient(135deg, oklch(0.62 0.03 60), oklch(0.38 0.03 50))',
    prefix: P('电影感写实风格，自然光影', 'presets.style.cinematic') },
  { id: 'cinematic', swatch: 'linear-gradient(135deg, oklch(0.55 0.1 220), oklch(0.7 0.14 60))',
    prefix: P('电影级调色，青橙对比，浅景深，宽银幕构图', 'presets.lookPrefix.cinematic') },
  { id: 'anime', swatch: 'linear-gradient(135deg, oklch(0.8 0.12 350), oklch(0.75 0.12 240))',
    prefix: P('日系动画风格，干净线条，通透高光，柔和配色', 'presets.lookPrefix.anime') },
  { id: 'ink_wash', swatch: 'radial-gradient(circle at 30% 30%, oklch(0.95 0.01 90), oklch(0.35 0 0))',
    prefix: P('中国水墨风格，留白，墨色浓淡渐变，宣纸质感', 'presets.lookPrefix.ink_wash') },
  { id: 'chinese_comic', swatch: 'linear-gradient(135deg, oklch(0.55 0.2 28), oklch(0.78 0.14 85))',
    prefix: P('国漫风格，厚涂上色，朱红与金色点缀，古风服饰细节', 'presets.lookPrefix.chinese_comic') },
  { id: 'oil_painting', swatch: 'linear-gradient(135deg, oklch(0.6 0.13 50), oklch(0.42 0.1 20))',
    prefix: P('古典油画风格，厚涂笔触，暖色光影', 'presets.lookPrefix.oil_painting') },
  { id: 'watercolor', swatch: 'linear-gradient(135deg, oklch(0.88 0.06 200), oklch(0.86 0.07 330))',
    prefix: P('水彩风格，淡彩晕染，纸张纹理，柔和边缘', 'presets.lookPrefix.watercolor') },
  { id: '3d_render', swatch: 'linear-gradient(135deg, oklch(0.75 0.12 280), oklch(0.6 0.15 200))',
    prefix: P('三维渲染风格，柔和全局光照，细腻材质', 'presets.lookPrefix.render3d') },
  { id: 'pixel_art', swatch: 'repeating-conic-gradient(oklch(0.7 0.15 150) 0 25%, oklch(0.55 0.15 260) 0 50%) 0 0 / 16px 16px',
    prefix: P('像素风格，低分辨率方块，复古游戏配色', 'presets.lookPrefix.pixel_art') },
]

export const lookOf = (artStyle: string) => STYLE_LOOKS.find((s) => s.id === artStyle)
/** 用户手改过前缀吗：不是任何一种风格的默认前缀，就算手改过 */
export const prefixTouched = (prefix: string) => !STYLE_LOOKS.some((s) => s.prefix.value === prefix)
/** 按 id 稳定地挑一套色块（最近小说的封面用） */
export const swatchFor = (id: string) =>
  STYLE_LOOKS[[...id].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7) % STYLE_LOOKS.length].swatch
```

  - 新的显示名键放在 `presets.lookPrefix.*`，中文就是前缀原文的简称，例如「电影级调色」；英文例如 "Cinematic grade"。
  - `styleLook.ts` 里 `P(` 开头的行要能被静态检查的白名单放过：把 `ALLOW` 里 `presets.ts` 那条规则也应用到 `styleLook.ts`，即加一条 `'styleLook.ts': /^\s*prefix: P\('[^']*', 'presets\./`。
  - `realistic` 的前缀必须等于 `DEFAULT_PARAMS.style_prefix`（`电影感写实风格，自然光影`）。这样新建小说的默认值不变，也不会被误判为手改过。

- [ ] **Step 4: 写 `tests/shelf.test.tsx` 的第一段**。结构照抄 `tests/workflow-ui.test.tsx` 开头的 happy-dom 和 `must` 写法，内容：
  - `STYLE_LOOKS` 的 id 覆盖 `ART_STYLES` 的全部取值。
  - `lookOf('realistic').prefix.value === DEFAULT_PARAMS.style_prefix`。
  - `prefixTouched(DEFAULT_PARAMS.style_prefix) === false`，`prefixTouched('自己写的') === true`。
  - `swatchFor('n1') === swatchFor('n1')`。
  - 渲染 `<StatusPill tone="live">生成中</StatusPill>`，断言 `[data-tone="live"]` 存在、文字对。
  - 最后打印 `ALL PASS`。

- [ ] **Step 5:** 跑三项检查，全部通过后提交：

```bash
git commit -m "书架改版底层零件：Popover、统一状态标签 StatusPill、风格色块与默认风格前缀；新增 shelf 测试套件"
```

---

### Task 2: 参数组件（params/）

**Files:**
- Create: `src/components/params/ParamChip.tsx`、`RatioPicker.tsx`、`StylePicker.tsx`、`VoicePicker.tsx`、`NarrationPick.tsx`、`MoreParams.tsx`、`src/styleImages.ts`
- Modify: `src/i18n/zh.ts`、`en.ts`（`params` 分组扩充）、`src/styles/shelf.css`
- Test: `tests/shelf.test.tsx`

所有组件的接口统一为 `{ value: NovelParams; onChange: (next: NovelParams) => void }`，只改自己负责的字段。`ParamChip` 例外。

- [ ] **Step 1: 先写失败测试**（`shelf.test.tsx` 第二段），逐个组件渲染并操作：
  - **RatioPicker**：有 4 个 `[data-ratio]` 按钮；点 `16:9` 之后 `onChange` 收到 `aspect_ratio: '16:9'`，其他字段不变。
  - **StylePicker**：
    - 有 9 张风格卡片和 1 张「自定义」。
    - 当前前缀是默认值时，点「动漫」，收到 `art_style: 'anime'` 和动漫的默认前缀。
    - 前缀改成 `'自己写的'` 以后，再点「水墨」，`art_style` 变了，前缀仍是 `'自己写的'`。
  - **NarrationPick**：
    - 点「剧情演绎」写入 `none`，点「旁白解说」写入 `selective`。
    - 值是 `condensed` 时，「旁白解说」处于选中态，并显示「压缩概述」角标。
  - **VoicePicker**：5 项；点第 3 项写入 `female_mature`。
  - **MoreParams**：改色调、平台、风格前缀输入框，分别写回对应字段；旁白细项可以选 4 种。
  - **风格卡片换图**（实施裁定 6）：
    - 对 `setStyleImage('anime', file)` 的结果，`getStyleImage('anime')` 是 `data:image/` 开头。happy-dom 没有 canvas 时，缩图步骤退化成直接读文件的 data URL，测试走这条路。
    - 之后 `StylePicker` 里「动漫」卡片显示 `img`；`clearStyleImage` 之后恢复色块。
    - `localStorage.setItem` 抛异常时不崩溃，并记一条 `notice.err`。

- [ ] **Step 2: 实现**：
  - **`ParamChip`**：`{ icon, label, value, children, testId }`。
    - 触发按钮高 32px、圆角 999px、`border` 加 `bg-background/60`，悬停时抬描边色。
    - 按钮内容是图标、小字 `label`（`text-muted-foreground`），再加粗写 `value`。
    - 点开是 `PopoverContent`，`children` 放在里面。
    - 加 `data-testid={testId}`。
  - **`RatioPicker`**：
    - 4 个按钮，每个里面画一个按比例缩放的小框（最长边 28px，`border-2`），下面写比例。
    - 选中的按钮 `--primary` 描边，并设 `aria-pressed`。
    - 每个按钮带 `data-ratio`。
  - **`StylePicker`**：
    - 横向一行，可以换行。每张卡片宽 112px：上面是高 64px 的色块（`style={{ background: look.swatch }}`，圆角），下面写名字（`ART_STYLES` 的 label）。
    - 选中时 2px `--primary` 外描边，右上角放 `Check` 图标。
    - 最后一张「自定义」，点了调用 `onCustom?.()`，由父组件打开「更多」并聚焦风格前缀。
    - 卡片依次进场用 `m.item(i)`。
    - 带属性 `compact?: boolean`：放在胶囊浮层里时用小卡片，宽 84px、色块高 44px，每行 3 张。
    - 换图与恢复默认按钮见实施裁定 6；`compact` 模式下不显示换图按钮（只在书架的风格区和设置页可换）。
  - **`VoicePicker`**：`TTS_VOICES` 列成单选列表，每项是名字加一句描述。描述键 `params.voiceDesc.<value>`，中文例如「男声 · 沉稳，适合正剧旁白」。
  - **`NarrationPick`**：
    - 两张并排的大卡片，各有图标（`Mic` 和 `Drama`，lucide 里没有 `Drama` 就用 `Clapperboard`）、标题和一行说明，`role="radio"`。
    - 外层 `role="radiogroup"`，并设 `aria-label`。
    - 角标规则见实施裁定 1。
  - **`MoreParams`**：竖排四项，从上到下：
    - 色调：沿用 `SelectOrCustom`。
    - 目标平台：沿用 `SelectOrCustom`。
    - 风格前缀：`Input`，下面列出 `STYLE_PREFIXES` 的小标签，点了填入。
    - 旁白细项：4 个单选，用 `NARRATION_MODE`。
    - 提供 `prefixRef?: React.Ref<HTMLInputElement>`，供「自定义」聚焦用。
- [ ] **Step 3:** 测试全过，三项检查全过。
- [ ] **Step 4: 提交**

```bash
git commit -m "参数组件：胶囊浮层外壳、比例框、风格卡片（选风格带出默认前缀，手改过的不覆盖）、音色列表、旁白解说与剧情演绎二选一、更多参数"
```

---

### Task 3: 新建主卡片 `NewNovelComposer`

**Files:**
- Create: `src/components/NewNovelComposer.tsx`；Delete: `src/components/NewNovelForm.tsx`
- Modify: `src/App.tsx`（import 改成新组件；暂时仍在原位置渲染，Task 4 再挪进书架页）、`src/i18n/zh.ts`、`en.ts`（`composer` 分组；`newNovel` 分组里不再用的键删掉）、`src/styles/shelf.css`
- Test: `tests/shelf.test.tsx`、`tests/flow.test.tsx`（原来按 `NewNovelForm` 的文字或选择器找元素的地方同步改）

- [ ] **Step 1: 先写失败测试**（`shelf.test.tsx` 第三段），渲染 `<NewNovelComposer disabled={false} onSubmit={spy} />`：
  - 标题为空时，主按钮 `[data-testid="composer-submit"]` 禁用，并显示「先给小说起个名字」。
  - 在原文框里粘贴两章（`第一章 甲\n正文一\n第二章 乙\n正文二`）后，出现 `[data-testid="chapter-chip"]` ×2，主按钮文字变成「创建并导入 2 章」。
  - 填上标题、点「剧情演绎」、在画幅胶囊里点 `16:9` 后提交：
    - `spy` 收到的 `params` 等于 `{ ...DEFAULT_PARAMS, aspect_ratio: '16:9', narration_mode: 'none' }`。
    - `chapters` 有 2 项，标题分别是「第一章 甲」「第二章 乙」，以 `parseChapters` 的实际输出为准。
  - **拖放导入**：
    - 在卡片上派发 `dragenter`，卡片带上 `data-drop="on"`。
    - 再派发 `drop`，`dataTransfer.files` 里放一个 `File(['第一章\n内容'], '我的小说.txt')`。之后标题自动变成「我的小说」，原文框里有内容。
    - happy-dom 的 `DataTransfer` 不好构造时，可以直接 `Object.defineProperty(ev, 'dataTransfer', { value: { files: [file], types: ['Files'] } })`。
  - 超过 4 章时，只显示 4 个标签加一个「+N」。

- [ ] **Step 2: 实现**，布局见规格第 5 节的示意图：
  - **外层**：`motion.section`，用 `m.enter`，最宽 760px、居中。
  - **卡片**：`rounded-2xl border bg-card shadow-sm`，深色主题加一圈很淡的品牌色光晕，用 `shelf.css` 里的 `.composer`。拖入时 `data-drop="on"`，描边换成 `--primary`，并盖一层半透明提示「松手导入 .txt」。
  - **标题行**：无边框大号输入（18px、600），占位文字「给小说起个名字」，带 `aria-label`。
  - **二选一**：`NarrationPick`。
  - **原文框**：`Textarea`，无边框、透明底，最小高 160px，随内容自动增高（最高 360px，之后滚动）。原文框带 `data-testid="composer-source"`，并保留 `form__text` 类作测试钩子，`flow.test` 在用。
  - **章节标签**：每个写「标题 · 1,234 字」，等宽数字；超过 4 个折叠成「+N」，点开显示全部。
  - **底栏**：上方一条细分隔线。
    - 左边是 4 个 `ParamChip`：
      - 画幅：浮层里放 `RatioPicker`。
      - 风格：浮层里放 `StylePicker compact`。
      - 音色：浮层里放 `VoicePicker`。
      - 更多：浮层里放 `MoreParams`。
    - 右边是「读取 .txt」（`ghost` 按钮，图标 `FileUp`）和主按钮（图标 `ArrowRight`）。
    - 标题为空时，主按钮左边写原因。
  - **提交**：沿用旧逻辑：原文识别不出章节标记时，整篇作为第一章；有章节就按章拆。
  - **键盘**：⌘/Ctrl+Enter 提交。
- [ ] **Step 3:** 删除 `NewNovelForm.tsx`，`App.tsx` 改引用。`grep -rn "NewNovelForm" src tests` 应该为空。
- [ ] **Step 4:** 测试全过，三项检查全过。
- [ ] **Step 5: 提交**

```bash
git commit -m "新建小说改成大输入卡片：无边框标题、旁白解说与剧情演绎二选一、可拖入 .txt、章节识别标签、底部画幅风格音色更多胶囊、⌘Enter 创建；删除旧表单"
```

---

### Task 4: 书架首页 `ShelfHome`

**Files:**
- Create: `src/components/ShelfHome.tsx`
- Modify: `src/App.tsx`（没打开小说、没打开文档、没跟踪任务时渲染 `ShelfHome`）、`src/i18n/zh.ts`、`en.ts`（`shelf` 分组）、`src/styles/shelf.css`
- Test: `tests/shelf.test.tsx`、`tests/flow.test.tsx`（注册后的首屏断言跟着改）

- [ ] **Step 1: 先写失败测试**（`shelf.test.tsx` 第四段），渲染 `ShelfHome`：
  - 首屏标题「新的故事，从哪一章开始？」存在；标题旁的帮助按钮（沿用 `Help` 组件）存在。
  - 主卡片下方有「画面风格」区，有 10 张卡片（9 种风格加「自定义」）。点「水彩」后，主卡片里风格胶囊的值变成「水彩」，说明两处共用同一份参数状态。
  - 传入 3 部小说时，有 `[data-testid="shelf-card"]` ×3，外加一张「＋ 新建」卡片。正在生成的那部卡片上有 `[data-tone="live"]`。
  - 点某张小说卡片，触发 `onOpenNovel(id)`。点「＋ 新建」，标题输入获得焦点。
  - 没有小说时，不显示「最近的小说」区。
- [ ] **Step 2: 实现**：
  - `ShelfHome` 的 props：`novels`、`running`（判断哪部在生成，用 `JobSummary` 里标识小说的字段，以 `types.ts` 为准）、`disabled`、`onSubmit`、`onOpenNovel`。
  - 参数状态提升到 `ShelfHome`。`NewNovelComposer` 改成受控组件：参数由外部传入和回写，标题和原文仍是自己的状态。
  - **页头**：
    - 上方留 8vh 空白。
    - 大标题 28px、600。
    - 副标题 14px 辅助色，旁边是 `Help`，悬停内容是原来那段「一部小说是一个总会话…」的说明。
  - **画面风格区**：小标题，下面是 `StylePicker`。点「自定义」时打开主卡片的「更多」浮层，并聚焦风格前缀。实现方式：`NewNovelComposer` 暴露 `openMore()`，用 `useImperativeHandle`。
  - **最近的小说**：小标题，下面是网格 `grid-cols-2 sm:grid-cols-3 lg:grid-cols-4`。
    - 每张卡片：上面是 96px 高的封面色块（`swatchFor(id)`，叠一层从下往上的暗色渐变），左下角是书名首字，字号 28px、白色。
    - 封面下面是书名（单行省略），再下面是「6 章 · 2 已采用 · 2 小时前」，时间用相对写法，键放在 `shelf.ago.*`。
    - 正在生成的，在封面右上角放 `StatusPill tone="live"`。
    - 最后一张是虚线框的「＋ 新建」卡片。
    - 卡片依次进场；悬停时抬描边，并上移 1px（减少动态效果时不位移）。
  - **App**：把原来的 `<NewNovelForm …/>` 换成 `<ShelfHome …/>`，传入现有的 `novels`、`running`、`openNovel`、`submitNovel`。`.main` 的最大宽度在书架页放宽到 1080px，看现有规则，不够就给书架单独加一个外层类。
- [ ] **Step 3:** 测试全过，`flow.test` 全过，三项检查全过。
- [ ] **Step 4: 提交**

```bash
git commit -m "书架首页：大标题与说明、新建主卡片、画面风格卡片与主卡片共用参数、最近的小说卡片网格（渐变封面、章节与采用数、相对时间、生成中标签、新建卡）"
```

---

### Task 5: 小说「设置」页改用同一套组件

**Files:**
- Modify: `src/components/NovelPage.tsx`（`ParamsTab`）、`src/components/ParamsForm.tsx`（删掉 `ParamsForm` 组件，只留 `DEFAULT_PARAMS` 和 `Field`；没人用 `Field` 的话也删）、`src/i18n/zh.ts`、`en.ts`、`tests/foundation.test.tsx`（`ALLOW` 里 `ParamsForm.tsx` 那条规则保留）
- Test: `tests/flow.test.tsx`（设置页的断言跟着改）、`tests/shelf.test.tsx`

- [ ] **Step 1: 先写失败测试**（`shelf.test.tsx` 第五段，直接渲染 `NovelPage`，`tab` 用参数页）：
  - 设置页有「画幅」「画面风格」「旁白」「音色」「更多」几个分区。
  - 改画幅后点保存，`updateNovel` 收到的 `params` 只有画幅变了。怎么桩 `api` 可以参考 `flow.test` 里的 `fetch` 桩写法；如果 `NovelPage` 要求的上下文太多，就把这一项放进 `flow.test` 现有的设置页段落。
- [ ] **Step 2: 实现**：竖版设置表单，最宽 720px，每一行是「左：标签加一句说明（240px）｜右：控件」，行与行之间用细分隔线。从上到下：
  - 小说标题：`Input`。
  - 画幅：`RatioPicker`。
  - 画面风格：`StylePicker`。
  - 旁白：`NarrationPick`。
  - 音色：`VoicePicker`。
  - 色调、平台、风格前缀：`MoreParams`，旁白细项也在里面。

  底部右侧放「保存」主按钮，只有改动过才能点，`run()` 的成功提示沿用现有的。
- [ ] **Step 3:** 测试全过，三项检查全过。
- [ ] **Step 4: 提交**

```bash
git commit -m "小说设置页改用新参数组件：竖版设置表单，画幅比例框、风格卡片、旁白二选一、音色列表与更多参数；删除旧参数表单"
```

---

## 自查记录

- **规格覆盖**（第 5 节）：
  - 主卡片：Task 3。
  - 二选一与细项：Task 2、3。
  - 拖放导入、章节标签：Task 3。
  - 胶囊浮层：Task 2、3。
  - 风格卡片和默认前缀：Task 1、2、4。
  - 最近小说：Task 4。
  - 设置页共用组件：Task 5。
  - `StatusPill`（第 10 节）：Task 1，在 Task 4 使用。
  - 测试（第 13 节）：二选一同步、拖入 .txt、标题为空、参数取值逐字一致，都在 Task 2–5。
- **已知差异**：封面按 id 哈希取色，不按风格（实施裁定 3）。
- **类型一致**：
  - `StyleLook`、`STYLE_LOOKS`、`lookOf`、`prefixTouched`、`swatchFor` 在 Task 1 定义，Task 2、4 使用。
  - params 组件统一用 `{ value: NovelParams, onChange }` 接口。
  - `NewNovel` 类型搬进 `NewNovelComposer.tsx`（实施裁定 4）。
