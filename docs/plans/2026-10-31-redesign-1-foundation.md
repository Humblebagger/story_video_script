# 前端改版 1：底座 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为改版打好底座：Tailwind v4 + shadcn/ui + motion + lucide 接进项目；深浅两套主题（跟随系统、可手动切换）；中英双语语言包框架；品牌配置 Inkreel ／ 墨卷；通用组件（统一的花钱确认对话框、「?」解释、浮动提示、空状态）；新的应用外壳（可收起的侧边栏、顶栏、主题与语言切换）。

**Architecture:** Tailwind 与现有 `index.css` 共存（旧页面暂时照旧，后续子计划逐页迁移）；shadcn 组件代码放 `src/components/ui/`；主题靠 `<html class="dark">` 切换，旧 CSS 的深色变量同步改成跟这个 class 走；语言包是两个 TS 对象，中文为准生成类型，`I18nProvider` 放在 `main.tsx`，没有 Provider 时默认中文（测试直接渲染组件即为中文）。

**Tech Stack:** React 19、TypeScript 6、Vite 8、Tailwind CSS 4.3、shadcn（CLI 4.x，Radix 组件）、motion 14、lucide-react、@fontsource-variable/inter 与 geist-mono（字体本地打包，不走外网）、happy-dom 测试。

**Spec:** `docs/specs/2026-10-31-frontend-redesign-design.md` 第 0、1、3、6、7（子计划 1）、8 节。

---

## 全局约束

- 提交只 `git add` 具体文件（`package-lock.json` 要一起提交），不用 `git add -A` / `git commit -a`；提交信息中文，**不带任何 Claude 署名**。
- 命令在 `frontend/` 下执行。每个任务结束：`npm test`（类型检查 + 全部测试套件，每套 `ALL PASS`）、`npm run lint`（0 error，不新增 warning）、`npx vite build`（能出包）。
- 逻辑模块（`api.ts`、`useFilm.ts`、`useCompose.ts`、`useJob.ts`、`useKeyframes.ts`、`timeline.ts`、`film.ts`、`compose.ts` 等）不改行为。
- 现有测试里依赖的文字与 class 名本计划内保持不变（尤其 `管理`、`返回书架`、`退出`、`新建小说`、用户名显示、`.login__tab`），测试固定用中文。
- 不碰后端，不碰 `docs/specs/2026-10-27-commercialization-design-contract.md`。
- 动效统一遵守：150–400ms、缓出；`prefers-reduced-motion` 时去掉位移只留淡入淡出（用 `src/motion.ts` 的预设）。

## 文件结构

| 文件 | 职责 |
|---|---|
| `package.json`、`package-lock.json` | 新依赖 |
| `vite.config.ts`、`tsconfig.app.json` | Tailwind 插件、`@/` 路径别名 |
| `components.json` | shadcn 配置 |
| `src/styles/app.css` | Tailwind 入口、字体、深浅两套设计变量、品牌渐变 |
| `src/lib/utils.ts` | `cn()`（shadcn 生成） |
| `src/components/ui/*` | shadcn 组件（CLI 生成） |
| `src/index.css` | 修改：深色变量从系统媒体查询改为跟 `.dark` class |
| `src/main.tsx` | 修改：引入 app.css、字体，套 `I18nProvider`、`Toaster`、`TooltipProvider`，启动时应用主题 |
| `src/theme.ts` | 新建：主题偏好读写、应用到 `<html>`、跟随系统、`useTheme()` |
| `src/i18n/zh.ts`、`src/i18n/en.ts`、`src/i18n/index.tsx` | 新建：语言包与 `useI18n()`、`translate()` |
| `src/brand.ts`、`src/components/brand/Logo.tsx` | 新建：产品名、定位语、标志 |
| `src/motion.ts` | 新建：动效预设（进场、列表依次进场、页面切换），自动尊重减少动态效果 |
| `src/components/common/*` | 新建：`MoneyConfirm`、`Help`、`EmptyState`、`ThemeToggle`、`LangToggle` |
| `src/components/shell/AppShell.tsx` | 新建：应用外壳 |
| `src/App.tsx` | 修改：用 `AppShell` 替换旧顶栏与布局外层 |
| `index.html`、`public/favicon.svg` | 修改：标题与图标 |
| `tests/foundation.test.tsx` | 新建：主题、语言包、外壳、通用组件 |

---

### Task 1: 依赖、Tailwind、shadcn、设计变量

**Files:** `package.json`、`package-lock.json`、`vite.config.ts`、`tsconfig.app.json`、`components.json`、`src/styles/app.css`、`src/lib/utils.ts`、`src/components/ui/*`、`src/index.css`、`src/main.tsx`

- [ ] **Step 1: 装依赖**

```bash
npm install tailwindcss@^4.3 @tailwindcss/vite@^4.3 motion@^14 lucide-react class-variance-authority clsx tailwind-merge tw-animate-css @fontsource-variable/inter @fontsource-variable/geist-mono
```

- [ ] **Step 2: Vite 插件与路径别名**

Replace `frontend/vite.config.ts` with:

```ts
import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// 开发期把 /api 代理到本地转换服务，避免跨源；生产用 VITE_API_BASE 直连
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    proxy: {
      '/api': {
        target: process.env.VITE_API_TARGET ?? 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ''),
      },
    },
  },
})
```

In `tsconfig.app.json` `compilerOptions`, add:

```json
    "baseUrl": ".",
    "paths": { "@/*": ["./src/*"] },
```

Also add the same `baseUrl`/`paths` to the root `tsconfig.json` `compilerOptions` (create the key if missing) — the shadcn CLI reads the root file to resolve the alias.

- [ ] **Step 3: 设计变量与 Tailwind 入口**

Create `frontend/src/styles/app.css`:

```css
/* Inkreel 设计变量：深浅两套。Tailwind 主题映射到这些变量，shadcn 组件直接用。
 * 品牌：墨色底 + 琥珀到品红的一道渐变；每屏最多一种强调。 */
@import "tailwindcss";
@import "tw-animate-css";

@custom-variant dark (&:where(.dark, .dark *));

:root {
  --radius: 0.75rem;
  --background: oklch(0.985 0.003 80);
  --foreground: oklch(0.2 0.012 270);
  --card: oklch(1 0 0);
  --card-foreground: oklch(0.2 0.012 270);
  --popover: oklch(1 0 0);
  --popover-foreground: oklch(0.2 0.012 270);
  --primary: oklch(0.24 0.02 270);
  --primary-foreground: oklch(0.985 0.003 80);
  --secondary: oklch(0.955 0.006 80);
  --secondary-foreground: oklch(0.24 0.02 270);
  --muted: oklch(0.955 0.006 80);
  --muted-foreground: oklch(0.5 0.012 270);
  --accent: oklch(0.95 0.02 60);
  --accent-foreground: oklch(0.3 0.06 50);
  --destructive: oklch(0.58 0.2 27);
  --success: oklch(0.6 0.13 155);
  --warning: oklch(0.72 0.15 75);
  --border: oklch(0.91 0.006 80);
  --input: oklch(0.91 0.006 80);
  --ring: oklch(0.7 0.14 55);
  --brand-from: oklch(0.78 0.16 70);
  --brand-to: oklch(0.62 0.24 340);
  --sidebar: oklch(0.975 0.004 80);
  --sidebar-foreground: oklch(0.24 0.02 270);
  --sidebar-border: oklch(0.91 0.006 80);
  --sidebar-accent: oklch(0.94 0.008 80);
  --sidebar-accent-foreground: oklch(0.2 0.012 270);
}

.dark {
  --background: oklch(0.155 0.012 275);
  --foreground: oklch(0.95 0.006 80);
  --card: oklch(0.195 0.014 275);
  --card-foreground: oklch(0.95 0.006 80);
  --popover: oklch(0.21 0.014 275);
  --popover-foreground: oklch(0.95 0.006 80);
  --primary: oklch(0.95 0.006 80);
  --primary-foreground: oklch(0.18 0.014 275);
  --secondary: oklch(0.25 0.014 275);
  --secondary-foreground: oklch(0.95 0.006 80);
  --muted: oklch(0.24 0.012 275);
  --muted-foreground: oklch(0.7 0.012 275);
  --accent: oklch(0.3 0.04 40);
  --accent-foreground: oklch(0.92 0.06 70);
  --destructive: oklch(0.66 0.19 25);
  --success: oklch(0.72 0.13 155);
  --warning: oklch(0.8 0.14 80);
  --border: oklch(1 0 0 / 9%);
  --input: oklch(1 0 0 / 12%);
  --ring: oklch(0.75 0.15 60);
  --brand-from: oklch(0.82 0.15 72);
  --brand-to: oklch(0.68 0.23 345);
  --sidebar: oklch(0.175 0.013 275);
  --sidebar-foreground: oklch(0.92 0.006 80);
  --sidebar-border: oklch(1 0 0 / 7%);
  --sidebar-accent: oklch(0.24 0.014 275);
  --sidebar-accent-foreground: oklch(0.95 0.006 80);
}

@theme inline {
  --font-sans: "Inter Variable", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", system-ui, sans-serif;
  --font-mono: "Geist Mono Variable", ui-monospace, "SF Mono", Menlo, monospace;
  --radius-sm: calc(var(--radius) - 4px);
  --radius-md: calc(var(--radius) - 2px);
  --radius-lg: var(--radius);
  --radius-xl: calc(var(--radius) + 4px);
  --color-background: var(--background);
  --color-foreground: var(--foreground);
  --color-card: var(--card);
  --color-card-foreground: var(--card-foreground);
  --color-popover: var(--popover);
  --color-popover-foreground: var(--popover-foreground);
  --color-primary: var(--primary);
  --color-primary-foreground: var(--primary-foreground);
  --color-secondary: var(--secondary);
  --color-secondary-foreground: var(--secondary-foreground);
  --color-muted: var(--muted);
  --color-muted-foreground: var(--muted-foreground);
  --color-accent: var(--accent);
  --color-accent-foreground: var(--accent-foreground);
  --color-destructive: var(--destructive);
  --color-success: var(--success);
  --color-warning: var(--warning);
  --color-border: var(--border);
  --color-input: var(--input);
  --color-ring: var(--ring);
  --color-brand-from: var(--brand-from);
  --color-brand-to: var(--brand-to);
  --color-sidebar: var(--sidebar);
  --color-sidebar-foreground: var(--sidebar-foreground);
  --color-sidebar-border: var(--sidebar-border);
  --color-sidebar-accent: var(--sidebar-accent);
  --color-sidebar-accent-foreground: var(--sidebar-accent-foreground);
}

@layer base {
  * { @apply border-border outline-ring/50; }
  body { @apply bg-background text-foreground font-sans antialiased; }
}

/* 品牌渐变：文字与细线用，克制 */
@utility text-brand {
  background-image: linear-gradient(100deg, var(--brand-from), var(--brand-to));
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
@utility bg-brand {
  background-image: linear-gradient(100deg, var(--brand-from), var(--brand-to));
}
```

- [ ] **Step 4: shadcn 配置与组件**

Create `frontend/components.json`:

```json
{
  "$schema": "https://ui.shadcn.com/schema.json",
  "style": "new-york",
  "rsc": false,
  "tsx": true,
  "tailwind": { "config": "", "css": "src/styles/app.css", "baseColor": "neutral", "cssVariables": true, "prefix": "" },
  "aliases": { "components": "@/components", "utils": "@/lib/utils", "ui": "@/components/ui", "lib": "@/lib", "hooks": "@/hooks" },
  "iconLibrary": "lucide"
}
```

Then generate the components (non-interactive; answer "no" to overwriting `app.css` if asked — our variables are the source of truth):

```bash
npx shadcn@4 add button card badge input label textarea separator skeleton tooltip dialog alert-dialog dropdown-menu tabs sonner progress scroll-area --yes
```

After generation: if the CLI rewrote `src/styles/app.css`, restore it from Step 3 (`git diff src/styles/app.css` must show only Step 3 content). If `src/components/ui/sonner.tsx` imports `next-themes`, replace that import and its `useTheme()` call with our theme (Task 2 adds `useTheme` from `@/theme`; until then pass `theme="system"`), and `npm uninstall next-themes` if it was installed. `src/lib/utils.ts` must export `cn()`.

- [ ] **Step 5: 旧 CSS 的深色跟 class 走、入口引入**

In `src/index.css`, replace the line `@media (prefers-color-scheme: dark) {` and its matching closing `}` so the block becomes `:root.dark { … }` (same variables inside, one less nesting level). Keep everything else.

Replace `src/main.tsx` with:

```tsx
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '@fontsource-variable/inter'
import '@fontsource-variable/geist-mono'
import './styles/app.css'
import './index.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
```

（Task 2–3 再往这里加主题与语言。）

- [ ] **Step 6: 验证**

Run: `npm test 2>&1 | grep -c "ALL PASS" ; npm run lint 2>&1 | tail -2 ; npx vite build 2>&1 | tail -3`
Expected: `9`; lint 0 errors; build succeeds. If a test suite fails because Tailwind's preflight is pulled into the SSR test build, report it — the suites must still pass (they don't assert styles).

- [ ] **Step 7: 提交**

```bash
git add package.json package-lock.json vite.config.ts tsconfig.app.json tsconfig.json components.json src/styles/app.css src/lib src/components/ui src/index.css src/main.tsx
git commit -m "改版底座：接入 Tailwind v4、shadcn/ui 组件、motion、lucide 与本地字体；深浅两套设计变量与品牌渐变；旧样式的深色改为跟随 dark class"
```

---

### Task 2: 主题（跟随系统 / 浅色 / 深色）

**Files:** Create `src/theme.ts`、`src/components/common/ThemeToggle.tsx`；Modify `src/main.tsx`、`src/components/ui/sonner.tsx`

- [ ] **Step 1: `src/theme.ts`**

```ts
/** 主题：跟随系统 / 浅色 / 深色。偏好存在本机（读写失败就当跟随系统），实际深浅写到 <html class="dark">。
 *  旧样式（index.css）与 shadcn 组件都看这个 class。 */
import { useSyncExternalStore } from 'react'

export type ThemePref = 'system' | 'light' | 'dark'
const KEY = 'inkreel.theme'
const listeners = new Set<() => void>()

export function readPref(): ThemePref {
  try {
    const v = localStorage.getItem(KEY)
    return v === 'light' || v === 'dark' ? v : 'system'
  } catch {
    return 'system'
  }
}

const systemDark = () =>
  typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-color-scheme: dark)').matches

/** 偏好 → 实际深浅 */
export const resolve = (pref: ThemePref): 'light' | 'dark' =>
  pref === 'system' ? (systemDark() ? 'dark' : 'light') : pref

export function applyTheme(pref: ThemePref = readPref()): void {
  const dark = resolve(pref) === 'dark'
  document.documentElement.classList.toggle('dark', dark)
  document.documentElement.style.colorScheme = dark ? 'dark' : 'light'
}

export function setPref(pref: ThemePref): void {
  try {
    if (pref === 'system') localStorage.removeItem(KEY)
    else localStorage.setItem(KEY, pref)
  } catch { /* 存不了就只在本页生效 */ }
  applyTheme(pref)
  listeners.forEach((l) => l())
}

/** 启动时调用一次：应用偏好，并在「跟随系统」时跟着系统变 */
export function initTheme(): void {
  applyTheme()
  window.matchMedia?.('(prefers-color-scheme: dark)').addEventListener?.('change', () => {
    if (readPref() === 'system') {
      applyTheme('system')
      listeners.forEach((l) => l())
    }
  })
}

function subscribe(l: () => void) {
  listeners.add(l)
  return () => listeners.delete(l)
}

/** 组件里用：当前偏好、实际深浅、改偏好 */
export function useTheme() {
  const pref = useSyncExternalStore(subscribe, readPref, () => 'system' as ThemePref)
  return { pref, resolved: resolve(pref), setPref }
}
```

- [ ] **Step 2: `ThemeToggle`**

Create `src/components/common/ThemeToggle.tsx`:

```tsx
/** 主题切换：一个图标按钮，下拉选跟随系统 / 浅色 / 深色 */
import { Monitor, Moon, Sun } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuRadioGroup, DropdownMenuRadioItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useI18n } from '@/i18n'
import { useTheme } from '@/theme'
import type { ThemePref } from '@/theme'

export function ThemeToggle() {
  const { pref, resolved, setPref } = useTheme()
  const { t } = useI18n()
  const Icon = pref === 'system' ? Monitor : resolved === 'dark' ? Moon : Sun
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label={t('theme.label')} data-testid="theme-toggle">
          <Icon className="size-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuRadioGroup value={pref} onValueChange={(v) => setPref(v as ThemePref)}>
          <DropdownMenuRadioItem value="system">{t('theme.system')}</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="light">{t('theme.light')}</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="dark">{t('theme.dark')}</DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
```

（`useI18n` 在 Task 3 建；本任务先建 `src/i18n/index.tsx` 的最小桩不可取——请把 Task 2 与 Task 3 视为一组：先做 Task 3 的 Step 1–3 再回来写 ThemeToggle，或在同一次提交里一起完成。）

- [ ] **Step 3: 启动时应用、sonner 用我们的主题**

In `src/main.tsx`, add `import { initTheme } from './theme'` and call `initTheme()` before `createRoot(...)`.

In `src/components/ui/sonner.tsx`, make the `theme` prop come from `useTheme().resolved` (import `useTheme` from `@/theme`).

- [ ] **Step 4: 验证与提交**（与 Task 3 一起，见 Task 3 Step 6）

---

### Task 3: 语言包框架（中 / 英）

**Files:** Create `src/i18n/zh.ts`、`src/i18n/en.ts`、`src/i18n/index.tsx`、`src/components/common/LangToggle.tsx`；Modify `src/main.tsx`

- [ ] **Step 1: 中文语言包（本计划用到的键）**

Create `src/i18n/zh.ts`:

```ts
/** 中文语言包：键的结构以这里为准（英文包必须一一对应）。插值写 {name}。 */
export const zh = {
  brand: {
    name: '墨卷',
    tagline: '从文字到成片',
  },
  common: {
    cancel: '取消',
    close: '关闭',
    retry: '重试',
    loading: '读取中…',
    help: '这是什么？',
  },
  theme: { label: '主题', system: '跟随系统', light: '浅色', dark: '深色' },
  lang: { label: '语言' },
  shell: {
    newNovel: '新建小说',
    openLocal: '打开本地 JSON',
    admin: '管理',
    backToShelf: '返回书架',
    logout: '退出',
    collapse: '收起侧边栏',
    expand: '展开侧边栏',
    serviceDown: '服务未连通',
    noKey: '未配置密钥',
    signedInAs: '已登录：{name}',
  },
  money: {
    total: '合计',
    spent: '已花',
    reserved: '在跑预留',
    after: '执行后累计',
    budget: '上限',
    over: '会超过上限，服务端会拒绝：先在设置里调高上限。',
    changed: '金额已变为 {amount}，请重新确认。',
    rateNote: '费率依据：{note}。实际以厂商控制台账单为准。',
    rateUnknown: '厂商未注明',
  },
}
```

- [ ] **Step 2: 英文语言包**

Create `src/i18n/en.ts`:

```ts
import type { Messages } from './index'

/** English messages: must mirror zh.ts key for key (the type checker enforces it). */
export const en: Messages = {
  brand: {
    name: 'Inkreel',
    tagline: 'From ink to reel',
  },
  common: {
    cancel: 'Cancel',
    close: 'Close',
    retry: 'Retry',
    loading: 'Loading…',
    help: 'What is this?',
  },
  theme: { label: 'Theme', system: 'System', light: 'Light', dark: 'Dark' },
  lang: { label: 'Language' },
  shell: {
    newNovel: 'New novel',
    openLocal: 'Open local JSON',
    admin: 'Admin',
    backToShelf: 'Back to library',
    logout: 'Sign out',
    collapse: 'Collapse sidebar',
    expand: 'Expand sidebar',
    serviceDown: 'Service unreachable',
    noKey: 'API key not set',
    signedInAs: 'Signed in as {name}',
  },
  money: {
    total: 'Total',
    spent: 'Spent',
    reserved: 'Reserved (running)',
    after: 'After this',
    budget: 'Budget',
    over: 'This exceeds your budget and will be rejected. Raise the budget in settings first.',
    changed: 'The amount is now {amount}. Please confirm again.',
    rateNote: 'Pricing basis: {note}. Your provider console bill is authoritative.',
    rateUnknown: 'not stated by the provider',
  },
}
```

- [ ] **Step 3: `src/i18n/index.tsx`**

```tsx
/** 中英双语：useI18n() 取 t / locale / setLocale；translate() 是纯函数（测试与非组件代码用）。
 *  没有 I18nProvider 时默认中文（测试直接渲染组件即为中文）。语言选择存在本机；首次按浏览器语言。 */
import { createContext, useCallback, useContext, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { en } from './en'
import { zh } from './zh'

type Widen<T> = { [K in keyof T]: T[K] extends string ? string : Widen<T[K]> }
export type Messages = Widen<typeof zh>
type Paths<T, P extends string = ''> = {
  [K in keyof T & string]: T[K] extends string ? `${P}${K}` : Paths<T[K], `${P}${K}.`>
}[keyof T & string]
export type MsgKey = Paths<Messages>
export type Locale = 'zh' | 'en'
export const LOCALES: { id: Locale; label: string }[] = [{ id: 'zh', label: '中文' }, { id: 'en', label: 'English' }]

const PACKS: Record<Locale, Messages> = { zh, en }
const KEY = 'inkreel.locale'

export function translate(locale: Locale, key: MsgKey, vars?: Record<string, string | number>): string {
  let node: unknown = PACKS[locale]
  for (const part of key.split('.')) node = (node as Record<string, unknown> | undefined)?.[part]
  const text = typeof node === 'string' ? node : key
  return vars ? text.replace(/\{(\w+)\}/g, (m, k: string) => (k in vars ? String(vars[k]) : m)) : text
}

export function detectLocale(): Locale {
  try {
    const v = localStorage.getItem(KEY)
    if (v === 'zh' || v === 'en') return v
  } catch { /* 读不到就按浏览器 */ }
  const lang = typeof navigator !== 'undefined' ? navigator.language : 'zh'
  return lang.toLowerCase().startsWith('zh') ? 'zh' : 'en'
}

interface Ctx {
  locale: Locale
  setLocale: (l: Locale) => void
  t: (key: MsgKey, vars?: Record<string, string | number>) => string
}
const I18nContext = createContext<Ctx>({
  locale: 'zh', setLocale: () => {}, t: (k, v) => translate('zh', k, v),
})

export function I18nProvider({ children, initial }: { children: ReactNode; initial?: Locale }) {
  const [locale, set] = useState<Locale>(() => initial ?? detectLocale())
  const setLocale = useCallback((l: Locale) => {
    try { localStorage.setItem(KEY, l) } catch { /* 只在本页生效 */ }
    document.documentElement.lang = l === 'zh' ? 'zh-CN' : 'en'
    set(l)
  }, [])
  const value = useMemo<Ctx>(() => ({ locale, setLocale, t: (k, v) => translate(locale, k, v) }), [locale, setLocale])
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export const useI18n = () => useContext(I18nContext)
```

（若 oxlint 报「组件文件同时导出非组件」的 react-refresh warning，按它的建议把 `translate`、`detectLocale`、类型挪到 `src/i18n/core.ts`，`index.tsx` 从那里再导出；不要新增 warning。）

- [ ] **Step 4: `LangToggle`**

Create `src/components/common/LangToggle.tsx`:

```tsx
/** 语言切换：图标按钮 + 下拉选中文 / English */
import { Languages } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuRadioGroup, DropdownMenuRadioItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { LOCALES, useI18n } from '@/i18n'
import type { Locale } from '@/i18n'

export function LangToggle() {
  const { locale, setLocale, t } = useI18n()
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label={t('lang.label')} data-testid="lang-toggle">
          <Languages className="size-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuRadioGroup value={locale} onValueChange={(v) => setLocale(v as Locale)}>
          {LOCALES.map((l) => <DropdownMenuRadioItem key={l.id} value={l.id}>{l.label}</DropdownMenuRadioItem>)}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
```

- [ ] **Step 5: 套 Provider**

In `src/main.tsx`, wrap `<App />`:

```tsx
import { I18nProvider } from './i18n'
import { Toaster } from './components/ui/sonner'
import { TooltipProvider } from './components/ui/tooltip'
…
  <StrictMode>
    <I18nProvider>
      <TooltipProvider delayDuration={200}>
        <App />
        <Toaster position="bottom-right" />
      </TooltipProvider>
    </I18nProvider>
  </StrictMode>,
```

- [ ] **Step 6: 验证与提交（Task 2 + 3）**

Run: `npm test 2>&1 | grep -c "ALL PASS" ; npm run lint 2>&1 | tail -2 ; npx vite build 2>&1 | tail -2`
Expected: `9`; 0 errors; build ok.

```bash
git add src/theme.ts src/i18n src/components/common/ThemeToggle.tsx src/components/common/LangToggle.tsx src/components/ui/sonner.tsx src/main.tsx
git commit -m "改版底座：主题（跟随系统/浅色/深色，存本机）与中英语言包框架（中文为准的键类型、插值、按浏览器语言、存本机），主题与语言切换按钮"
```

---

### Task 4: 品牌与动效预设

**Files:** Create `src/brand.ts`、`src/components/brand/Logo.tsx`、`src/motion.ts`；Modify `index.html`、`public/favicon.svg`

- [ ] **Step 1: `src/brand.ts`**

```ts
/** 品牌：产品名与定位语在语言包里（brand.name / brand.tagline），这里放不随语言变的部分。改名只改这里和语言包。 */
export const BRAND = {
  /** 英文名（标题、元信息） */
  id: 'Inkreel',
  /** 浏览器标签页标题 */
  title: 'Inkreel — From ink to reel',
}
```

- [ ] **Step 2: 标志**

Create `src/components/brand/Logo.tsx`:

```tsx
/** 标志：一枚带品牌渐变的胶片格（墨滴变胶片），加名字。size 控制图形边长。 */
import { useI18n } from '@/i18n'
import { cn } from '@/lib/utils'

export function LogoMark({ size = 24, className }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden className={className}>
      <defs>
        <linearGradient id="inkreel-g" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="var(--brand-from)" />
          <stop offset="1" stopColor="var(--brand-to)" />
        </linearGradient>
      </defs>
      <rect x="3" y="3" width="26" height="26" rx="8" fill="url(#inkreel-g)" />
      <path d="M16 8c3.5 4.2 5.5 7.3 5.5 10a5.5 5.5 0 0 1-11 0c0-2.7 2-5.8 5.5-10Z" fill="white" fillOpacity=".92" />
      <rect x="7" y="7" width="2" height="3" rx=".6" fill="white" fillOpacity=".55" />
      <rect x="7" y="22" width="2" height="3" rx=".6" fill="white" fillOpacity=".55" />
      <rect x="23" y="7" width="2" height="3" rx=".6" fill="white" fillOpacity=".55" />
      <rect x="23" y="22" width="2" height="3" rx=".6" fill="white" fillOpacity=".55" />
    </svg>
  )
}

export function Logo({ className, compact }: { className?: string; compact?: boolean }) {
  const { t } = useI18n()
  return (
    <span className={cn('inline-flex items-center gap-2 font-semibold tracking-tight', className)}>
      <LogoMark />
      {!compact && <span>{t('brand.name')}</span>}
    </span>
  )
}
```

- [ ] **Step 3: 标题与图标**

In `index.html`: `<title>Inkreel — From ink to reel</title>`, keep `lang="zh-CN"`.
Replace `public/favicon.svg` with the same mark using fixed colors (no CSS vars):

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#f2b13c"/><stop offset="1" stop-color="#d63b8f"/></linearGradient></defs><rect x="3" y="3" width="26" height="26" rx="8" fill="url(#g)"/><path d="M16 8c3.5 4.2 5.5 7.3 5.5 10a5.5 5.5 0 0 1-11 0c0-2.7 2-5.8 5.5-10Z" fill="#fff" fill-opacity=".92"/></svg>
```

- [ ] **Step 4: 动效预设 `src/motion.ts`**

```ts
/** 动效预设：150–400ms、缓出；系统开了「减少动态效果」时去掉位移，只留淡入淡出。
 *  组件里用 useMotionPresets() 取，传给 motion 组件的 initial / animate / exit / transition。 */
import { useReducedMotion } from 'motion/react'
import type { Transition } from 'motion/react'

export const EASE_OUT: [number, number, number, number] = [0.22, 1, 0.36, 1]
export const DUR = { fast: 0.15, base: 0.24, slow: 0.4 }

export function presets(reduced: boolean) {
  const t = (d: number, delay = 0): Transition => ({ duration: d, ease: EASE_OUT, delay })
  return {
    /** 进场：淡入 + 上移 8px */
    enter: {
      initial: { opacity: 0, y: reduced ? 0 : 8 },
      animate: { opacity: 1, y: 0 },
      exit: { opacity: 0, y: reduced ? 0 : -4 },
      transition: t(DUR.base),
    },
    /** 列表第 i 项依次进场（间隔 40ms，最多 10 项后不再延迟） */
    item: (i: number) => ({
      initial: { opacity: 0, y: reduced ? 0 : 10 },
      animate: { opacity: 1, y: 0 },
      transition: t(DUR.base, Math.min(i, 10) * 0.04),
    }),
    /** 弹出：淡入 + 0.97 → 1 */
    pop: {
      initial: { opacity: 0, scale: reduced ? 1 : 0.97 },
      animate: { opacity: 1, scale: 1 },
      exit: { opacity: 0, scale: reduced ? 1 : 0.98 },
      transition: t(DUR.fast),
    },
  }
}

export function useMotionPresets() {
  return presets(!!useReducedMotion())
}
```

- [ ] **Step 5: 验证与提交**

Run the Task 1 Step 6 checks. Then:

```bash
git add src/brand.ts src/components/brand/Logo.tsx src/motion.ts index.html public/favicon.svg
git commit -m "改版底座：品牌 Inkreel／墨卷（标志、标签页标题、图标）与动效预设（缓出、依次进场、弹出，自动尊重减少动态效果）"
```

---

### Task 5: 通用组件（花钱确认、「?」解释、空状态）

**Files:** Create `src/components/common/MoneyConfirm.tsx`、`src/components/common/Help.tsx`、`src/components/common/EmptyState.tsx`

- [ ] **Step 1: `MoneyConfirm`（全站统一的花钱确认对话框）**

```tsx
/** 花钱前的确认（全站统一）：标题、可选的明细行、合计加粗、已花 / 在跑预留 / 执行后累计 / 上限、
 *  金额变了的提示、超上限的拦截、费率依据。确认按钮上写金额。出片与合成在子计划 4 换成它。 */
import type { ReactNode } from 'react'
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { useI18n } from '@/i18n'

export const yuan = (n: number) => `¥${n.toFixed(2)}`

export interface MoneyConfirmProps {
  open: boolean
  title: string
  /** 合计（本次要花的） */
  cny: number
  spent: number
  reserved?: number
  budget: number
  /** 服务端重算后金额变了 */
  changed?: boolean
  rateNote?: string
  /** 确认按钮的动作词，如「确认出片」 */
  action: string
  /** 额外拦截（未保存、验证门没过）：为 true 时确认按钮禁用 */
  blocked?: boolean
  busy?: boolean
  /** 明细（如批量出片的各段）、警告 */
  children?: ReactNode
  onConfirm: () => void
  onCancel: () => void
}

export function MoneyConfirm(p: MoneyConfirmProps) {
  const { t } = useI18n()
  const after = Math.round((p.spent + (p.reserved ?? 0) + p.cny) * 100) / 100
  const over = after > p.budget + 1e-9
  return (
    <AlertDialog open={p.open} onOpenChange={(o) => { if (!o) p.onCancel() }}>
      <AlertDialogContent data-testid="money-confirm">
        <AlertDialogHeader>
          <AlertDialogTitle>{p.title}</AlertDialogTitle>
          <AlertDialogDescription asChild>
            <div className="space-y-3 text-sm">
              {p.changed && <p className="text-destructive">{t('money.changed', { amount: yuan(p.cny) })}</p>}
              {p.children}
              <div className="rounded-lg border bg-muted/40 p-3">
                <div className="flex items-baseline justify-between">
                  <span>{t('money.total')}</span>
                  <b className="text-2xl font-semibold tabular-nums text-foreground">{yuan(p.cny)}</b>
                </div>
                <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-muted-foreground tabular-nums">
                  <span>{t('money.spent')} {yuan(p.spent)}</span>
                  {!!p.reserved && <span>{t('money.reserved')} {yuan(p.reserved)}</span>}
                  <span>{t('money.after')} {yuan(after)}</span>
                  <span>{t('money.budget')} {yuan(p.budget)}</span>
                </div>
              </div>
              {over && <p className="text-destructive">{t('money.over')}</p>}
              <p className="text-xs text-muted-foreground">
                {t('money.rateNote', { note: p.rateNote || t('money.rateUnknown') })}
              </p>
            </div>
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
          <AlertDialogAction disabled={p.busy || over || p.blocked}
                             onClick={(e) => { e.preventDefault(); p.onConfirm() }}>
            {p.action}（{yuan(p.cny)}）
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
```

- [ ] **Step 2: `Help`（「?」解释）**

```tsx
/** 「?」：鼠标移上或键盘聚焦时显示一句解释（概念不用内部术语） */
import { CircleHelp } from 'lucide-react'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useI18n } from '@/i18n'

export function Help({ text }: { text: string }) {
  const { t } = useI18n()
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button type="button" aria-label={t('common.help')} data-help={text}
                className="inline-flex size-4 items-center justify-center rounded-full text-muted-foreground hover:text-foreground focus-visible:outline-2">
          <CircleHelp className="size-3.5" />
        </button>
      </TooltipTrigger>
      <TooltipContent className="max-w-64">{text}</TooltipContent>
    </Tooltip>
  )
}
```

- [ ] **Step 3: `EmptyState`**

```tsx
/** 空状态：图标 + 一句话 + 主按钮（可选），淡入上浮 */
import type { ReactNode } from 'react'
import { motion } from 'motion/react'
import { useMotionPresets } from '@/motion'

export function EmptyState({ icon, title, hint, action }: {
  icon?: ReactNode; title: string; hint?: string; action?: ReactNode
}) {
  const m = useMotionPresets()
  return (
    <motion.div {...m.enter} data-testid="empty-state"
                className="mx-auto flex max-w-sm flex-col items-center gap-3 py-16 text-center">
      {icon && <div className="flex size-12 items-center justify-center rounded-2xl bg-muted text-muted-foreground">{icon}</div>}
      <p className="text-base font-medium">{title}</p>
      {hint && <p className="text-sm text-muted-foreground">{hint}</p>}
      {action}
    </motion.div>
  )
}
```

- [ ] **Step 4: 验证与提交**

Run the Task 1 Step 6 checks, then:

```bash
git add src/components/common/MoneyConfirm.tsx src/components/common/Help.tsx src/components/common/EmptyState.tsx
git commit -m "改版底座：全站统一的花钱确认对话框（合计加粗、已花/预留/累计/上限、金额变动与超上限、费率依据）、「?」解释与空状态组件"
```

---

### Task 6: 应用外壳

**Files:** Create `src/components/shell/AppShell.tsx`；Modify `src/App.tsx`（替换 `if (!user) …` 之后 `return` 的外层：旧 `<header className="top">…</header>` 与 `.shell` 外壳）

- [ ] **Step 1: `AppShell`**

```tsx
/** 应用外壳：左侧可收起的侧边栏（标志、新建小说、小说列表插槽、管理入口、账号与退出）+ 顶栏（面包屑、服务状态、
 *  打开本地 JSON、语言与主题）+ 内容区（切换时淡入上移）。文字全部走语言包。
 *  测试依赖的按钮文字：「管理」「返回书架」「退出」「新建小说」，以及用户名可见。 */
import { useState } from 'react'
import type { ReactNode } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { FileJson, LogOut, PanelLeftClose, PanelLeftOpen, Plus, Shield } from 'lucide-react'
import { Logo } from '@/components/brand/Logo'
import { LangToggle } from '@/components/common/LangToggle'
import { ThemeToggle } from '@/components/common/ThemeToggle'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useI18n } from '@/i18n'
import { cn } from '@/lib/utils'
import { useMotionPresets } from '@/motion'

export interface AppShellProps {
  username: string
  isAdmin: boolean
  adminOpen: boolean
  onToggleAdmin: () => void
  onLogout: () => void
  onNewNovel: () => void
  onOpenLocal: () => void
  /** 面包屑（小说名 / 章节 / 版本），空则只显示产品名 */
  crumbs: string[]
  /** 服务状态：down 为连不上；model 为当前模型；noKey 为没配密钥 */
  service: { down: boolean; model?: string; noKey?: boolean }
  /** 侧边栏中部（小说列表） */
  sidebar: ReactNode
  /** 内容区的切换键：变了就播一次进场动画 */
  viewKey: string
  children: ReactNode
}

export function AppShell(p: AppShellProps) {
  const { t } = useI18n()
  const m = useMotionPresets()
  const [collapsed, setCollapsed] = useState(false)
  return (
    <div className="flex min-h-screen bg-background text-foreground" data-testid="app-shell">
      <aside className={cn('sticky top-0 flex h-screen shrink-0 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground transition-[width] duration-200 ease-out',
                           collapsed ? 'w-16' : 'w-72')}>
        <div className="flex h-14 items-center justify-between px-3">
          <Logo compact={collapsed} />
          <Button variant="ghost" size="icon" aria-label={collapsed ? t('shell.expand') : t('shell.collapse')}
                  onClick={() => setCollapsed((v) => !v)}>
            {collapsed ? <PanelLeftOpen className="size-4" /> : <PanelLeftClose className="size-4" />}
          </Button>
        </div>
        <div className="px-3 pb-2">
          <Button className="w-full justify-start gap-2" onClick={p.onNewNovel} title={t('shell.newNovel')}>
            <Plus className="size-4" />{!collapsed && t('shell.newNovel')}
          </Button>
        </div>
        <div className={cn('min-h-0 flex-1 overflow-y-auto px-2', collapsed && 'invisible')}>{p.sidebar}</div>
        <div className="space-y-1 border-t border-sidebar-border p-3">
          {p.isAdmin && (
            <Button variant="ghost" className="w-full justify-start gap-2" onClick={p.onToggleAdmin}>
              <Shield className="size-4" />{collapsed ? null : (p.adminOpen ? t('shell.backToShelf') : t('shell.admin'))}
            </Button>
          )}
          <div className="flex items-center gap-2 rounded-lg px-2 py-1.5" title={t('shell.signedInAs', { name: p.username })}>
            <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-brand text-xs font-semibold text-white">
              {p.username.slice(0, 1).toUpperCase()}
            </span>
            {!collapsed && <span className="min-w-0 flex-1 truncate text-sm">{p.username}</span>}
            <Button variant="ghost" size="sm" className="gap-1.5 text-muted-foreground" onClick={p.onLogout}>
              <LogOut className="size-3.5" />{!collapsed && t('shell.logout')}
            </Button>
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b bg-background/80 px-5 backdrop-blur supports-[backdrop-filter]:bg-background/60">
          <nav className="min-w-0 flex-1 truncate text-sm text-muted-foreground" aria-label="breadcrumb">
            {p.crumbs.length
              ? p.crumbs.map((c, i) => (
                <span key={i}>
                  {i > 0 && <span className="mx-2 opacity-50">/</span>}
                  <span className={i === p.crumbs.length - 1 ? 'text-foreground' : ''}>{c}</span>
                </span>
              ))
              : <span className="text-foreground">{t('brand.name')}</span>}
          </nav>
          {p.service.down
            ? <Badge variant="destructive">{t('shell.serviceDown')}</Badge>
            : p.service.model && (
              <Badge variant="outline" className="font-mono text-xs font-normal">
                {p.service.model}{p.service.noKey && <span className="ml-1 text-destructive">· {t('shell.noKey')}</span>}
              </Badge>
            )}
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="icon" aria-label={t('shell.openLocal')} onClick={p.onOpenLocal}>
                <FileJson className="size-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>{t('shell.openLocal')}</TooltipContent>
          </Tooltip>
          <LangToggle />
          <ThemeToggle />
        </header>
        <AnimatePresence mode="wait">
          <motion.main key={p.viewKey} {...m.enter} className="min-w-0 flex-1 px-6 py-6">
            {p.children}
          </motion.main>
        </AnimatePresence>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: 接进 `App.tsx`**

In `src/App.tsx`:
- Import `AppShell` from `./components/shell/AppShell`.
- Replace the returned JSX after `const converting = …` with:

```tsx
  return (
    <>
      <input
        ref={fileRef}
        type="file"
        accept=".json,application/json"
        hidden
        onChange={(e) => {
          const f = e.target.files?.[0]
          if (f) void openLocal(f)
          e.target.value = ''
        }}
      />
      <AppShell
        username={user.username}
        isAdmin={user.role === 'admin'}
        adminOpen={adminOpen && user.role === 'admin'}
        onToggleAdmin={() => setAdminOpen((v) => !v)}
        onLogout={logout}
        onNewNovel={newNovel}
        onOpenLocal={() => fileRef.current?.click()}
        crumbs={adminOpen && user.role === 'admin' ? []
          : [novel?.title, chapter?.title, docVid ?? undefined].filter((x): x is string => !!x)}
        service={{ down: svcDown, model: svc?.model, noKey: !!svc && !svc.api_key_configured }}
        viewKey={adminOpen ? 'admin' : `${novel?.id ?? ''}/${chapter?.id ?? ''}`}
        sidebar={adminOpen && user.role === 'admin' ? null : (
          <NovelSidebar
            novels={novels}
            novel={novel}
            chapterId={chapter?.id ?? null}
            running={running}
            activeJobId={job?.id ?? null}
            loading={novelsLoading}
            onOpenNovel={(nid) => void openNovel(nid)}
            onOpenChapter={(cid) => void openChapter(cid)}
            onOpenJob={openJob}
            onNewNovel={newNovel}
            onNewChapter={() => void newChapter()}
          />
        )}
      >
        {adminOpen && user.role === 'admin' ? (
          <AdminView me={user} onBack={() => setAdminOpen(false)} />
        ) : (
          <div className="main">
            {/* 原 <main className="main"> 里的全部内容原样搬到这里（NewNovelForm、NovelPage、ChapterPage、
                error/alert、JobPanel、VerificationPanel、StoryboardView），一行不改 */}
          </div>
        )}
      </AppShell>
    </>
  )
```

  Move the children of the old `<main className="main">…</main>` verbatim into that `<div className="main">`. Check the actual field names on `novel` / `chapter` (`title` or `name`) in `src/types.ts` and use the real ones for `crumbs`. If `NovelSidebar` already renders its own 「新建小说」 button, keep it (the shell button duplicates it; Task 7's test only needs at least one).

- [ ] **Step 3: 旧样式冲突**

`index.css` 的 `.shell`、`.top*`、`.who*` 规则不再用到：删掉这些选择器（只删这几组），其余保留。`.main` 若带有与新外壳冲突的宽度/内边距，改为 `max-width: 1200px; margin: 0 auto;` 一类不冲突的写法，并在报告里写明改了什么。

- [ ] **Step 4: 验证**

Run: `npm test 2>&1 | grep -E "ALL PASS|✗" ; npm run lint 2>&1 | tail -2`
Expected: nine `ALL PASS`, no `✗`. If `flow.test.tsx` fails, fix the cause in the shell first (keep the button texts and the visible username); only adjust a test assertion when the plan deliberately changed that behavior, and list each such change in the report.

- [ ] **Step 5: 提交**

```bash
git add src/components/shell/AppShell.tsx src/App.tsx src/index.css
git commit -m "改版底座：新的应用外壳（可收起侧边栏：标志、新建小说、小说列表、管理入口、账号与退出；顶栏：面包屑、服务状态、打开本地 JSON、语言与主题；内容区切换淡入）"
```

---

### Task 7: 底座测试、回归与验收准备

**Files:** Create `tests/foundation.test.tsx`；Modify `package.json`（test 脚本）

- [ ] **Step 1: 测试**

Create `tests/foundation.test.tsx`:

```tsx
/** 改版底座：语言包键一致与插值、主题偏好与 dark class、外壳（语言切换后文字变英文、收起侧边栏、管理入口与退出回调）、
 *  花钱确认（合计、累计、超上限禁用、金额变了提示）、动效预设在减少动态效果时不位移。跑法：npm test */
import { Window } from 'happy-dom'

const win = new Window({ url: 'http://localhost:5173' })
const g = globalThis as Record<string, unknown>
for (const k of ['window', 'document', 'navigator', 'location', 'HTMLElement', 'Element', 'Node', 'Event',
                 'CustomEvent', 'KeyboardEvent', 'MouseEvent', 'PointerEvent', 'getComputedStyle',
                 'localStorage', 'sessionStorage', 'matchMedia', 'ResizeObserver', 'DOMRect']) {
  Object.defineProperty(g, k, {
    value: (win as unknown as Record<string, unknown>)[k], writable: true, configurable: true,
  })
}
g.IS_REACT_ACT_ENVIRONMENT = true

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }

const { zh } = await import('../src/i18n/zh')
const { en } = await import('../src/i18n/en')
const { translate } = await import('../src/i18n')
const { presets } = await import('../src/motion')
const theme = await import('../src/theme')

// 1. 语言包：键一致（运行时再比一遍，防类型被 as 绕过）、插值、缺键回落为键名
const keys = (o: object, p = ''): string[] => Object.entries(o).flatMap(([k, v]) =>
  typeof v === 'string' ? [`${p}${k}`] : keys(v as object, `${p}${k}.`))
must(JSON.stringify(keys(zh).sort()) === JSON.stringify(keys(en).sort()), '中英文语言包的键必须一致')
must(translate('en', 'shell.signedInAs', { name: 'amy' }) === 'Signed in as amy', '英文插值')
must(translate('zh', 'shell.signedInAs', { name: 'amy' }) === '已登录：amy', '中文插值')
must(translate('zh', 'brand.name') === '墨卷' && translate('en', 'brand.name') === 'Inkreel', '品牌名')
console.log('1. 语言包 ✓')

// 2. 主题：偏好存本机，实际深浅写到 <html class="dark">
theme.setPref('dark')
must(win.document.documentElement.classList.contains('dark') && theme.readPref() === 'dark', '深色')
theme.setPref('light')
must(!win.document.documentElement.classList.contains('dark') && theme.readPref() === 'light', '浅色')
theme.setPref('system')
must(theme.readPref() === 'system' && win.localStorage.getItem('inkreel.theme') === null, '跟随系统不存值')
console.log('2. 主题 ✓')

// 3. 动效：减少动态效果时不位移
must(presets(true).enter.initial.y === 0 && presets(false).enter.initial.y === 8, '进场位移')
must(presets(true).item(3).initial.y === 0 && presets(true).pop.initial.scale === 1, '列表与弹出')
console.log('3. 动效预设 ✓')

const { act } = await import('react')
const { createRoot } = await import('react-dom/client')
const { I18nProvider, useI18n } = await import('../src/i18n')
const { AppShell } = await import('../src/components/shell/AppShell')
const { MoneyConfirm } = await import('../src/components/common/MoneyConfirm')
const { TooltipProvider } = await import('../src/components/ui/tooltip')

const container = win.document.createElement('div')
win.document.body.appendChild(container)
const root = createRoot(container as unknown as HTMLElement)
const settle = async (ms = 30) => { await act(async () => { await new Promise((r) => setTimeout(r, ms)) }) }
const body = () => win.document.body.innerHTML
const button = (text: string) => {
  const b = [...win.document.querySelectorAll('button')].find((x) => (x.textContent ?? '').includes(text))
  if (!b) throw new Error(`✗ 找不到按钮「${text}」`)
  return b as unknown as HTMLButtonElement
}
const click = async (el: Element) => {
  await act(async () => { el.dispatchEvent(new win.MouseEvent('click', { bubbles: true }) as unknown as Event) })
  await settle()
}

// 4. 外壳：中文文字、管理入口与退出回调、收起侧边栏；切到英文后文字跟着变
const log: string[] = []
let setLoc: (l: 'zh' | 'en') => void = () => {}
function Grab() { setLoc = useI18n().setLocale; return null }
function Host() {
  return (
    <I18nProvider initial="zh">
      <TooltipProvider>
        <Grab />
        <AppShell username="amy" isAdmin adminOpen={false} onToggleAdmin={() => log.push('admin')}
                  onLogout={() => log.push('logout')} onNewNovel={() => log.push('new')} onOpenLocal={() => {}}
                  crumbs={['药', '第一章']} service={{ down: false, model: 'claude-x', noKey: true }}
                  sidebar={<p>书架内容</p>} viewKey="a">
          <p>内容区</p>
        </AppShell>
      </TooltipProvider>
    </I18nProvider>
  )
}
await act(async () => { root.render(<Host />) })
await settle()
must(body().includes('墨卷') && body().includes('amy') && body().includes('药') && body().includes('第一章'),
  '外壳显示品牌、用户与面包屑')
must(body().includes('未配置密钥') && body().includes('书架内容') && body().includes('内容区'), '服务状态与插槽')
await click(button('管理'))
await click(button('新建小说'))
await click(button('退出'))
must(log.join(',') === 'admin,new,logout', `外壳按钮回调：${log}`)
await click(win.document.querySelector('button[aria-label="收起侧边栏"]')!)
must(!!win.document.querySelector('button[aria-label="展开侧边栏"]'), '收起侧边栏')
await act(async () => { setLoc('en') })
await settle()
must(body().includes('Inkreel') && body().includes('Sign out') && body().includes('API key not set'),
  '切到英文后外壳文字变英文')
console.log('4. 应用外壳 ✓')

// 5. 花钱确认：合计、执行后累计、超上限时确认禁用、金额变了提示
let confirmed = 0
function Money({ cny, changed }: { cny: number; changed?: boolean }) {
  return (
    <I18nProvider initial="zh">
      <MoneyConfirm open title="出剩余 3 段" cny={cny} spent={10} reserved={5} budget={100} changed={changed}
                    rateNote="假厂商" action="确认出片" onConfirm={() => { confirmed += 1 }} onCancel={() => {}} />
    </I18nProvider>
  )
}
await act(async () => { root.render(<Money cny={20} />) })
await settle()
must(body().includes('¥20.00') && body().includes('执行后累计 ¥35.00') && body().includes('费率依据：假厂商'),
  '合计与累计')
await click(button('确认出片（¥20.00）'))
must(confirmed === 1, '确认回调')
await act(async () => { root.render(<Money cny={90} changed />) })
await settle()
must(body().includes('金额已变为 ¥90.00') && body().includes('会超过上限') && button('确认出片（¥90.00）').disabled,
  '超上限禁用、金额变了提示')
console.log('5. 花钱确认 ✓')

await act(async () => { root.unmount() })
console.log('\nALL PASS')
```

In `package.json`, append to the `test` script:

```
 && vite build --ssr tests/foundation.test.tsx --outDir .ssrout --logLevel error && node .ssrout/foundation.test.js
```

If a happy-dom global used by Radix is missing (`matchMedia`, `ResizeObserver`, `PointerEvent`, `DOMRect`), polyfill minimally at the top of the test (e.g. `g.matchMedia ??= () => ({ matches: false, addEventListener() {}, removeEventListener() {} })`) and note it in the report. Keep every assertion.

- [ ] **Step 2: 全量回归**

Run: `npm test 2>&1 | grep -c "ALL PASS" ; npm run lint 2>&1 | tail -2 ; npx vite build 2>&1 | tail -3`
Expected: `10`; 0 errors; build ok.

- [ ] **Step 3: 提交**

```bash
git add tests/foundation.test.tsx package.json
git commit -m "改版底座测试：语言包键一致与插值、主题偏好、动效在减少动态效果时不位移、应用外壳（中英切换、收起、入口回调）、花钱确认（累计、超上限禁用、金额变动）"
```

- [ ] **Step 4: 验收准备（控制者做）**

控制者启动后端（`STORYBOARD_VIDEO_PROVIDER=fake STORYBOARD_TTS_PROVIDER=fake`）与 `npm run dev`，请用户看：登录后的外壳（侧边栏收起展开、深浅主题切换、中英切换、面包屑），注意旧页面内容区此时还是旧样式（子计划 3–4 再换）。
