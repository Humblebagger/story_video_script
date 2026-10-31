# 前端改版 2：首页与登录注册对话框 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 没登录时显示首页（顶栏、首屏、功能、流程、常见问题、结尾号召、页脚，中英双语、深浅主题），右上角「登录」「免费注册」打开登录注册对话框；登录成功淡出进入应用。

**Architecture:** `src/components/landing/` 下按段拆组件，文字全部走语言包；滚动进场用自写的 `Reveal`（没有 `IntersectionObserver` 的环境，如测试，直接显示不动画）；首屏的画布示意图用 div/SVG 画、跟主题与语言走、鼠标移动有轻微视差。登录注册改成 `AuthDialog`（逻辑沿用原 `LoginView`），**不走 portal、渲染在应用树里**（固定定位遮罩），这样现有测试仍能在容器里找到表单。

**Tech Stack:** React 19、TS 6、Tailwind v4、shadcn（新增 accordion）、motion、lucide-react、happy-dom。

**Spec:** `docs/specs/2026-10-31-frontend-redesign-design.md` 第 2 节、第 6 节、第 8 节。

---

## 全局约束

- 提交只 `git add` 具体文件，不用 `git add -A` / `git commit -a`；提交信息中文，**不带任何 Claude 署名**。
- 命令在 `frontend/` 下执行。每个任务结束：`npm test`（全部套件 `ALL PASS`）、`npm run lint`（0 error，不新增 warning）、`npx vite build`。
- `useI18n`、`translate` 从 `@/i18n/core` 导入；`I18nProvider` 从 `@/i18n`。设计变量里 shadcn 的 muted/accent/radius 叫 `--ui-*`（Tailwind 类名照常用 `bg-muted`、`bg-accent`、`rounded-lg`）。旧样式在 `legacy` 层，Tailwind 工具类会压过它。
- 测试固定用中文；没有 Provider 时 `useI18n` 默认中文。
- 动效：150–400ms 缓出；用 `@/motion` 的 `useMotionPresets()`；减少动态效果时不位移、不视差。首屏背景光斑是唯一允许的慢速循环动画，减少动态效果时停住。
- 不碰后端，不碰 `docs/specs/2026-10-27-commercialization-design-contract.md`。

## 实施裁定

1. **没有任何账号时（全新部署）自动打开注册对话框**；有账号时首页不自动弹出。
2. **登录失效（401）时回到首页并自动打开登录对话框**，提示「登录已过期，请重新登录」；主动退出只回到首页、不弹。
3. **对话框不走 portal**，渲染在 `App` 里，避免测试与焦点问题；视觉上仍是居中弹出加背景模糊。
4. 首页的锚点用 `id` + `scrollIntoView({ behavior: 'smooth' })`（减少动态效果时 `auto`），不加路由。

## 文件结构

| 文件 | 职责 |
|---|---|
| `src/i18n/zh.ts`、`src/i18n/en.ts` | 修改：加 `landing.*`、`auth.*` |
| `src/components/ui/accordion.tsx` | 新增（shadcn CLI） |
| `src/components/landing/Reveal.tsx` | 滚到时淡入上浮（可依次） |
| `src/components/landing/CanvasMock.tsx` | 首屏的时间轴画布示意图 |
| `src/components/landing/Landing.tsx` | 首页：顶栏、首屏、功能、流程、常见问题、结尾、页脚 |
| `src/components/auth/AuthDialog.tsx` | 登录注册对话框（原 `LoginView` 逻辑） |
| `src/components/LoginView.tsx` | 删除 |
| `src/App.tsx` | 修改：没登录时渲染 `Landing`；401 自动打开登录 |
| `tests/flow.test.tsx` | 修改：退出后先点首页「登录」再填表 |
| `tests/landing.test.tsx` | 新建 |
| `package.json` | 修改：test 脚本加 landing |

---

### Task 1: 语言包（首页与登录注册）

**Files:** Modify `src/i18n/zh.ts`、`src/i18n/en.ts`

- [ ] **Step 1: 中文**

In `src/i18n/zh.ts`, add these two top-level keys to the exported object (after `money`):

```ts
  landing: {
    nav: { features: '功能', workflow: '流程', faq: '常见问题' },
    signIn: '登录',
    signUp: '免费注册',
    eyebrow: '小说 → 分镜 → 成片',
    title: '从文字，到成片。',
    subtitle: '把小说章节变成可编辑的分镜，再一键出片、配音、合成。',
    start: '开始创作',
    seeFlow: '看看流程',
    mock: {
      shots: '镜头', frames: '画面', speech: '旁白 / 台词', film: '成片',
      line1: '秋天的后半夜，月亮下去了……', line2: '「小栓的爹，你就去么？」', rendered: '已出片', rendering: '生成中',
    },
    featuresTitle: '一条线，从章节走到成片',
    featuresSub: '每一步都看得见、改得了，花钱之前一定先确认。',
    features: {
      convert: { title: '小说转分镜', desc: '按章节读懂人物、场景与情节，拆成带景别、运镜、旁白与台词的镜头。' },
      check: { title: '完整性检查', desc: '独立校验每个镜头都有原文出处、台词逐字对得上，不编造剧情。' },
      canvas: { title: '时间轴画布', desc: '镜头、画面、语音、成片排在一条时间轴上，拖一拖就能改。' },
      render: { title: '一键出片', desc: '先试一段再批量出；每次花钱前列出金额，按版本设上限。' },
      voice: { title: '配音与合成', desc: '为每个角色选音色，自动对齐声画、压低 BGM、生成字幕。' },
      memory: { title: '长期记忆', desc: '人物、主线与创作限制跨章节保持一致，越写越懂你的故事。' },
    },
    workflowTitle: '四步出一集',
    steps: {
      import: { title: '导入章节', desc: '粘贴原文，自动按章节拆开。' },
      storyboard: { title: '生成分镜', desc: '几分钟得到完整分镜，并通过完整性检查。' },
      edit: { title: '画布上调整', desc: '改镜头、换画面、听语音节奏。' },
      film: { title: '出片与合成', desc: '出片、配音、合成，下载每集成片与字幕。' },
    },
    faqTitle: '常见问题',
    faq: {
      cost: { q: '费用怎么算？', a: '分镜按大模型实际用量计费；出片与配音按厂商刊例价估算。每次花钱前都会列出金额让你确认，并且每个版本有花费上限。' },
      models: { q: '支持哪些模型？', a: '分镜由大语言模型生成；出片目前接入字节跳动 Seedance，配音接入豆包语音，后续会加入更多厂商。' },
      privacy: { q: '我的小说会被别人看到吗？', a: '不会。每个账号的小说、分镜与资产库互相隔离，密码只以哈希形式保存。' },
      edit: { q: '生成的分镜能改吗？', a: '能。在时间轴画布上直接改镜头、旁白与台词，保存后再出片。' },
      export: { q: '能导出什么？', a: '分镜 JSON、每集的 mp4 成片与 srt 字幕，以及记录声画调整的合成报告。' },
    },
    ctaTitle: '把下一章，变成下一集。',
    ctaSub: '免费注册，几分钟后看到你的第一份分镜。',
    footer: '© 2026 Inkreel。保留所有权利。',
  },
  auth: {
    loginTitle: '欢迎回来',
    registerTitle: '创建账号',
    tabLogin: '登录',
    tabRegister: '注册',
    firstRun: '服务端还没有任何账号。第一个注册的账号会接管此前单用户时代的历史记录。',
    username: '用户名',
    usernameHint: '2–32 位，中英文、数字、下划线',
    password: '密码',
    passwordHint: '至少 6 位',
    confirm: '确认密码',
    confirmHint: '再输入一次',
    mismatch: '两次输入的密码不一致',
    submitLogin: '登录',
    submitRegister: '注册并进入',
    wait: '请稍候…',
    tip: '每个账号的小说与资产库互相隔离；密码以 PBKDF2 哈希存储，不保存明文。',
    expired: '登录已过期，请重新登录',
  },
```

- [ ] **Step 2: 英文**

In `src/i18n/en.ts`, add the same keys:

```ts
  landing: {
    nav: { features: 'Features', workflow: 'How it works', faq: 'FAQ' },
    signIn: 'Sign in',
    signUp: 'Sign up free',
    eyebrow: 'Novel → Storyboard → Film',
    title: 'From ink to reel.',
    subtitle: 'Turn novel chapters into editable storyboards — then render, voice and compose them in one flow.',
    start: 'Start creating',
    seeFlow: 'See how it works',
    mock: {
      shots: 'Shots', frames: 'Frames', speech: 'Narration / lines', film: 'Film',
      line1: 'Late autumn night; the moon had set…', line2: '“Are you going, father?”', rendered: 'Rendered', rendering: 'Rendering',
    },
    featuresTitle: 'One line from chapter to film',
    featuresSub: 'Every step is visible and editable — and nothing costs money until you confirm.',
    features: {
      convert: { title: 'Novel to storyboard', desc: 'Understands characters, places and plot per chapter, then breaks it into shots with framing, camera moves, narration and dialogue.' },
      check: { title: 'Integrity check', desc: 'An independent pass verifies every shot traces back to the source and every line is quoted verbatim — no invented plot.' },
      canvas: { title: 'Timeline canvas', desc: 'Shots, frames, voice and film on one timeline. Drag to adjust.' },
      render: { title: 'One-click render', desc: 'Try one clip, then render the rest. Every charge is itemized for you to confirm, with a per-version budget.' },
      voice: { title: 'Voice & compose', desc: 'Pick a voice per character; audio and picture are aligned, music is ducked, and subtitles are generated.' },
      memory: { title: 'Long-term memory', desc: 'Characters, plot and creative rules stay consistent across chapters.' },
    },
    workflowTitle: 'Four steps to an episode',
    steps: {
      import: { title: 'Import chapters', desc: 'Paste your text; chapters are split for you.' },
      storyboard: { title: 'Generate storyboard', desc: 'A complete storyboard in minutes, integrity-checked.' },
      edit: { title: 'Refine on the canvas', desc: 'Edit shots, swap frames, hear the pacing.' },
      film: { title: 'Render & compose', desc: 'Render, voice and compose; download each episode with subtitles.' },
    },
    faqTitle: 'Frequently asked questions',
    faq: {
      cost: { q: 'How much does it cost?', a: 'Storyboards are billed by actual model usage; rendering and voice are estimated from provider list prices. You confirm every charge first, and each version has a spending cap.' },
      models: { q: 'Which models are supported?', a: 'Storyboards are written by a large language model; rendering currently uses ByteDance Seedance and voice uses Doubao TTS, with more providers coming.' },
      privacy: { q: 'Can others see my novels?', a: 'No. Novels, storyboards and asset libraries are isolated per account, and passwords are stored only as hashes.' },
      edit: { q: 'Can I edit the storyboard?', a: 'Yes. Edit shots, narration and dialogue directly on the timeline canvas, save, then render.' },
      export: { q: 'What can I export?', a: 'Storyboard JSON, an mp4 and srt subtitles per episode, and a compose report of every audio/picture adjustment.' },
    },
    ctaTitle: 'Turn your next chapter into your next episode.',
    ctaSub: 'Sign up free and see your first storyboard in minutes.',
    footer: '© 2026 Inkreel. All rights reserved.',
  },
  auth: {
    loginTitle: 'Welcome back',
    registerTitle: 'Create your account',
    tabLogin: 'Sign in',
    tabRegister: 'Sign up',
    firstRun: 'This server has no accounts yet. The first account to sign up takes over history from the earlier single-user setup.',
    username: 'Username',
    usernameHint: '2–32 characters: letters, digits, underscore',
    password: 'Password',
    passwordHint: 'At least 6 characters',
    confirm: 'Confirm password',
    confirmHint: 'Type it again',
    mismatch: 'The passwords don’t match',
    submitLogin: 'Sign in',
    submitRegister: 'Sign up and continue',
    wait: 'Please wait…',
    tip: 'Each account’s novels and assets are isolated; passwords are stored as PBKDF2 hashes, never in plain text.',
    expired: 'Your session expired. Please sign in again.',
  },
```

- [ ] **Step 3: 验证与提交**

Run: `npm test 2>&1 | grep -c "ALL PASS" ; npm run lint 2>&1 | tail -2`
Expected: `10` (foundation's key-parity test covers the new keys); 0 errors.

```bash
git add src/i18n/zh.ts src/i18n/en.ts
git commit -m "首页与登录注册的中英文案：导航、首屏、功能、流程、常见问题、结尾号召、页脚、登录注册对话框"
```

---

### Task 2: 登录注册对话框

**Files:** Create `src/components/auth/AuthDialog.tsx`；Delete `src/components/LoginView.tsx`

- [ ] **Step 1: `AuthDialog`**

Create `src/components/auth/AuthDialog.tsx`:

```tsx
/** 登录 / 注册对话框（原 LoginView 的逻辑）：页签切换；注册要输两次密码；全新部署时引导注册；
 *  错误显示在表单里；成功后回调 onDone。不走 portal：渲染在应用树里（测试能在容器里找到表单）。
 *  测试依赖：.login__tab、.login__field input、提交按钮 type=submit、「注册并进入」「第一个注册的账号」「两次输入的密码不一致」。 */
import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { X } from 'lucide-react'
import { login, register } from '@/api'
import { setSession } from '@/auth'
import type { User } from '@/auth'
import { LogoMark } from '@/components/brand/Logo'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useI18n } from '@/i18n/core'
import { cn } from '@/lib/utils'
import { useMotionPresets } from '@/motion'

export type AuthMode = 'login' | 'register'

export function AuthDialog({ open, mode, firstRun, notice, onMode, onClose, onDone }: {
  open: boolean
  mode: AuthMode
  /** 服务端还没有任何账号 */
  firstRun: boolean
  /** 顶部提示（如登录已过期） */
  notice?: string | null
  onMode: (m: AuthMode) => void
  onClose: () => void
  onDone: (user: User) => void
}) {
  const { t } = useI18n()
  const m = useMotionPresets()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const registering = mode === 'register'
  // 密码打错一个字符，注册完就再也登不进去——所以注册必须二次确认
  const mismatch = registering && confirm.length > 0 && confirm !== password
  const ready = username.trim() && password && (!registering || confirm === password)

  useEffect(() => { setConfirm(''); setError(null) }, [mode])
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape' && !busy) onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, busy, onClose])

  const submit = async (e: { preventDefault: () => void }) => {
    e.preventDefault()
    if (!ready) return
    setBusy(true)
    setError(null)
    try {
      const fn = registering ? register : login
      const { token, user } = await fn(username.trim(), password)
      setSession(token, user)
      onDone(user)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <AnimatePresence>
      {open && (
        <motion.div key="auth" className="fixed inset-0 z-50 flex items-center justify-center p-4"
                    initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                    transition={{ duration: 0.18 }}>
          <div className="absolute inset-0 bg-background/60 backdrop-blur-md" onClick={() => !busy && onClose()} />
          <motion.form {...m.pop} onSubmit={submit} role="dialog" aria-modal="true"
                       aria-label={registering ? t('auth.registerTitle') : t('auth.loginTitle')}
                       data-testid="auth-dialog"
                       className="login__box relative w-full max-w-sm space-y-4 rounded-2xl border bg-card p-6 shadow-2xl">
            <button type="button" aria-label={t('common.close')} onClick={onClose} disabled={busy}
                    className="absolute right-3 top-3 rounded-md p-1 text-muted-foreground hover:text-foreground">
              <X className="size-4" />
            </button>
            <div className="flex flex-col items-center gap-2 pt-2 text-center">
              <LogoMark size={36} />
              <h2 className="text-xl font-semibold tracking-tight">
                {registering ? t('auth.registerTitle') : t('auth.loginTitle')}
              </h2>
            </div>
            {notice && <p className="rounded-lg bg-warning/15 px-3 py-2 text-sm">{notice}</p>}
            <div className="login__tabs grid grid-cols-2 rounded-lg bg-muted p-1">
              {(['login', 'register'] as const).map((k) => (
                <button type="button" key={k} onClick={() => onMode(k)}
                        className={cn('login__tab rounded-md py-1.5 text-sm transition-colors',
                                      mode === k ? 'is-on bg-background font-medium shadow-sm' : 'text-muted-foreground hover:text-foreground')}>
                  {k === 'login' ? t('auth.tabLogin') : t('auth.tabRegister')}
                </button>
              ))}
            </div>
            {firstRun && registering && <p className="text-sm text-muted-foreground">{t('auth.firstRun')}</p>}
            <label className="login__field block space-y-1.5">
              <span className="text-sm font-medium">{t('auth.username')}</span>
              <Input value={username} autoFocus autoComplete="username" placeholder={t('auth.usernameHint')}
                     onChange={(e) => setUsername(e.target.value)} />
            </label>
            <label className="login__field block space-y-1.5">
              <span className="text-sm font-medium">{t('auth.password')}</span>
              <Input type="password" value={password}
                     autoComplete={registering ? 'new-password' : 'current-password'}
                     placeholder={registering ? t('auth.passwordHint') : ''}
                     onChange={(e) => setPassword(e.target.value)} />
            </label>
            {registering && (
              <label className="login__field block space-y-1.5">
                <span className="text-sm font-medium">{t('auth.confirm')}</span>
                <Input type="password" value={confirm} autoComplete="new-password"
                       placeholder={t('auth.confirmHint')} aria-invalid={mismatch}
                       onChange={(e) => setConfirm(e.target.value)} />
                {mismatch && <em className="block text-xs not-italic text-destructive">{t('auth.mismatch')}</em>}
              </label>
            )}
            {error && <p className="text-sm text-destructive">{error}</p>}
            <Button type="submit" className="w-full" disabled={busy || !ready}>
              {busy ? t('auth.wait') : registering ? t('auth.submitRegister') : t('auth.submitLogin')}
            </Button>
            <p className="text-center text-xs text-muted-foreground">{t('auth.tip')}</p>
          </motion.form>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
```

`git rm src/components/LoginView.tsx` happens in Task 4 (App still imports it until then).

- [ ] **Step 2: 验证与提交**

Run: `npm test 2>&1 | grep -c "ALL PASS" ; npm run lint 2>&1 | tail -2 ; npx vite build 2>&1 | tail -2`
Expected: `10`; 0 errors; build ok.

```bash
git add src/components/auth/AuthDialog.tsx
git commit -m "登录注册对话框：页签切换、注册两次密码、全新部署引导、错误就地提示、Esc 与点遮罩关闭、弹出动效（沿用原登录逻辑）"
```

---

### Task 3: 首页

**Files:** Create `src/components/landing/Reveal.tsx`、`src/components/landing/CanvasMock.tsx`、`src/components/landing/Landing.tsx`、`src/components/ui/accordion.tsx`

- [ ] **Step 1: 折叠面板组件**

Run: `npx shadcn@4 add accordion --yes`. If it rewrites `src/styles/app.css` or installs `next-themes`/`cn`, revert those (`git checkout src/styles/app.css`, uninstall extras). If the generated file adds a lint warning, apply the same file-level `oxlint-disable` used in `button.tsx`.

- [ ] **Step 2: `Reveal`**

```tsx
/** 滚到时淡入上浮。没有 IntersectionObserver（测试环境）就直接显示；减少动态效果时只淡入。 */
import type { ReactNode } from 'react'
import { motion, useReducedMotion } from 'motion/react'
import { DUR, EASE_OUT } from '@/motion'

const canObserve = () => typeof window !== 'undefined' && 'IntersectionObserver' in window

export function Reveal({ children, delay = 0, className }: { children: ReactNode; delay?: number; className?: string }) {
  const reduced = !!useReducedMotion()
  if (!canObserve()) return <div className={className}>{children}</div>
  return (
    <motion.div className={className}
                initial={{ opacity: 0, y: reduced ? 0 : 16 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, margin: '-60px' }}
                transition={{ duration: DUR.slow, ease: EASE_OUT, delay }}>
      {children}
    </motion.div>
  )
}
```

- [ ] **Step 3: `CanvasMock`**

```tsx
/** 首屏的「时间轴画布」示意图：四条泳道（镜头 / 画面 / 语音 / 成片）+ 播放头，跟主题与语言走。
 *  鼠标在上面移动时整体轻微倾斜（视差）；减少动态效果时不动。纯装饰，对读屏隐藏。 */
import { motion, useMotionValue, useReducedMotion, useSpring, useTransform } from 'motion/react'
import { useI18n } from '@/i18n/core'

const SHOTS = [12, 18, 10, 22, 14, 16]

export function CanvasMock() {
  const { t } = useI18n()
  const reduced = !!useReducedMotion()
  const mx = useMotionValue(0)
  const my = useMotionValue(0)
  const rx = useSpring(useTransform(my, [-1, 1], [4, -4]), { stiffness: 120, damping: 18 })
  const ry = useSpring(useTransform(mx, [-1, 1], [-6, 6]), { stiffness: 120, damping: 18 })
  const total = SHOTS.reduce((a, b) => a + b, 0)
  return (
    <div aria-hidden className="mx-auto w-full max-w-4xl [perspective:1200px]"
         onMouseMove={(e) => {
           if (reduced) return
           const r = e.currentTarget.getBoundingClientRect()
           mx.set(((e.clientX - r.left) / r.width) * 2 - 1)
           my.set(((e.clientY - r.top) / r.height) * 2 - 1)
         }}
         onMouseLeave={() => { mx.set(0); my.set(0) }}>
      <motion.div style={reduced ? undefined : { rotateX: rx, rotateY: ry }}
                  className="relative overflow-hidden rounded-2xl border bg-card/80 p-4 shadow-2xl backdrop-blur">
        <div className="mb-3 flex items-center gap-1.5">
          <span className="size-2.5 rounded-full bg-destructive/70" />
          <span className="size-2.5 rounded-full bg-warning/70" />
          <span className="size-2.5 rounded-full bg-success/70" />
        </div>
        <div className="grid grid-cols-[88px_1fr] gap-x-3 gap-y-2 text-xs">
          <span className="self-center text-muted-foreground">{t('landing.mock.shots')}</span>
          <div className="flex gap-1">
            {SHOTS.map((w, i) => (
              <div key={i} style={{ flexGrow: w }}
                   className={`h-7 rounded-md border ${i === 2 ? 'border-transparent bg-brand text-white' : 'bg-secondary'} px-1.5 py-1 font-mono text-[10px]`}>
                SH{String(i + 1).padStart(3, '0')}
              </div>
            ))}
          </div>
          <span className="self-center text-muted-foreground">{t('landing.mock.frames')}</span>
          <div className="flex gap-1">
            {SHOTS.map((w, i) => (
              <div key={i} style={{ flexGrow: w, opacity: 0.55 + (i % 3) * 0.15 }}
                   className="h-12 rounded-md bg-gradient-to-br from-brand-from/40 to-brand-to/30" />
            ))}
          </div>
          <span className="self-center text-muted-foreground">{t('landing.mock.speech')}</span>
          <div className="flex gap-1">
            <div style={{ flexGrow: SHOTS[0] + SHOTS[1] }} className="truncate rounded-md bg-muted px-2 py-1 text-[11px]">{t('landing.mock.line1')}</div>
            <div style={{ flexGrow: total - SHOTS[0] - SHOTS[1] }} className="truncate rounded-md bg-muted px-2 py-1 text-[11px]">{t('landing.mock.line2')}</div>
          </div>
          <span className="self-center text-muted-foreground">{t('landing.mock.film')}</span>
          <div className="flex gap-1">
            <div style={{ flexGrow: SHOTS[0] + SHOTS[1] + SHOTS[2] }}
                 className="h-6 rounded-md bg-success/25 px-2 py-1 text-[10px] text-success">✓ {t('landing.mock.rendered')}</div>
            <div style={{ flexGrow: total - SHOTS[0] - SHOTS[1] - SHOTS[2] }}
                 className="h-6 rounded-md border border-dashed px-2 py-1 text-[10px] text-muted-foreground">{t('landing.mock.rendering')}…</div>
          </div>
        </div>
        <div className="pointer-events-none absolute bottom-3 top-12 w-px bg-brand-to" style={{ left: 'calc(88px + 2.75rem + 38%)' }} />
      </motion.div>
    </div>
  )
}
```

- [ ] **Step 4: `Landing`**

```tsx
/** 首页（没登录时）：顶栏（滚动后磨砂）、首屏（标题、按钮、慢速光斑背景、画布示意图）、功能 6 卡、流程 4 步、
 *  常见问题、结尾号召、页脚。右上角与按钮打开登录 / 注册对话框（由 App 管）。文字全部走语言包。 */
import { useEffect, useState } from 'react'
import { motion, useReducedMotion } from 'motion/react'
import {
  ArrowRight, BookOpenText, Clapperboard, Film, Layers, Mic, ShieldCheck, Sparkles,
} from 'lucide-react'
import { Logo } from '@/components/brand/Logo'
import { LangToggle } from '@/components/common/LangToggle'
import { ThemeToggle } from '@/components/common/ThemeToggle'
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '@/components/ui/accordion'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/i18n/core'
import type { MsgKey } from '@/i18n/core'
import { cn } from '@/lib/utils'
import { CanvasMock } from './CanvasMock'
import { Reveal } from './Reveal'

const FEATURES = [
  { id: 'convert', icon: BookOpenText }, { id: 'check', icon: ShieldCheck }, { id: 'canvas', icon: Layers },
  { id: 'render', icon: Clapperboard }, { id: 'voice', icon: Mic }, { id: 'memory', icon: Sparkles },
] as const
const STEPS = ['import', 'storyboard', 'edit', 'film'] as const
const FAQ = ['cost', 'models', 'privacy', 'edit', 'export'] as const

export function Landing({ onSignIn, onSignUp }: { onSignIn: () => void; onSignUp: () => void }) {
  const { t } = useI18n()
  const reduced = !!useReducedMotion()
  const [scrolled, setScrolled] = useState(false)
  useEffect(() => {
    const on = () => setScrolled(window.scrollY > 8)
    window.addEventListener('scroll', on, { passive: true })
    return () => window.removeEventListener('scroll', on)
  }, [])
  const go = (id: string) => document.getElementById(id)?.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth' })
  const k = (s: string) => s as MsgKey

  return (
    <div className="min-h-screen bg-background text-foreground" data-testid="landing">
      <header className={cn('fixed inset-x-0 top-0 z-40 transition-colors duration-200',
                            scrolled ? 'border-b bg-background/70 backdrop-blur-xl' : 'bg-transparent')}>
        <div className="mx-auto flex h-16 max-w-6xl items-center gap-6 px-6">
          <Logo className="text-base" />
          <nav className="hidden flex-1 items-center justify-center gap-7 text-sm text-muted-foreground md:flex">
            {(['features', 'workflow', 'faq'] as const).map((id) => (
              <button key={id} type="button" onClick={() => go(id)} className="transition-colors hover:text-foreground">
                {t(k(`landing.nav.${id}`))}
              </button>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-1 md:ml-0">
            <LangToggle />
            <ThemeToggle />
            <Button variant="ghost" size="sm" onClick={onSignIn} data-testid="landing-login">{t('landing.signIn')}</Button>
            <Button size="sm" onClick={onSignUp} data-testid="landing-register">{t('landing.signUp')}</Button>
          </div>
        </div>
      </header>

      <section className="relative overflow-hidden pb-24 pt-36">
        <div aria-hidden className="pointer-events-none absolute inset-0 -z-0">
          <motion.div className="absolute -top-32 left-1/2 h-[520px] w-[820px] -translate-x-1/2 rounded-full bg-brand opacity-20 blur-3xl"
                      animate={reduced ? undefined : { x: ['-52%', '-48%', '-52%'], y: [0, 24, 0] }}
                      transition={{ duration: 18, repeat: Infinity, ease: 'easeInOut' }} />
          <div className="absolute inset-0 opacity-[0.035] [background-image:radial-gradient(currentColor_1px,transparent_1px)] [background-size:3px_3px]" />
        </div>
        <div className="relative mx-auto max-w-6xl px-6 text-center">
          <Reveal>
            <p className="mb-5 inline-flex items-center gap-2 rounded-full border bg-card/60 px-3 py-1 text-xs text-muted-foreground backdrop-blur">
              <Film className="size-3.5" />{t('landing.eyebrow')}
            </p>
          </Reveal>
          <Reveal delay={0.05}>
            <h1 className="mx-auto max-w-3xl text-5xl font-semibold tracking-tight md:text-7xl">
              <span className="text-brand">{t('landing.title')}</span>
            </h1>
          </Reveal>
          <Reveal delay={0.1}>
            <p className="mx-auto mt-6 max-w-2xl text-lg text-muted-foreground">{t('landing.subtitle')}</p>
          </Reveal>
          <Reveal delay={0.15} className="mt-9 flex flex-wrap items-center justify-center gap-3">
            <Button size="lg" onClick={onSignUp} className="gap-2">{t('landing.start')}<ArrowRight className="size-4" /></Button>
            <Button size="lg" variant="outline" onClick={() => go('workflow')}>{t('landing.seeFlow')}</Button>
          </Reveal>
          <Reveal delay={0.25} className="mt-16"><CanvasMock /></Reveal>
        </div>
      </section>

      <section id="features" className="mx-auto max-w-6xl scroll-mt-20 px-6 py-24">
        <Reveal className="mx-auto max-w-2xl text-center">
          <h2 className="text-3xl font-semibold tracking-tight md:text-4xl">{t('landing.featuresTitle')}</h2>
          <p className="mt-4 text-muted-foreground">{t('landing.featuresSub')}</p>
        </Reveal>
        <div className="mt-14 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map(({ id, icon: Icon }, i) => (
            <Reveal key={id} delay={i * 0.05}>
              <div className="group h-full rounded-2xl border bg-card p-6 transition-all duration-200 hover:-translate-y-0.5 hover:border-brand-to/40 hover:shadow-lg">
                <div className="mb-4 flex size-10 items-center justify-center rounded-xl bg-muted text-foreground transition-colors group-hover:bg-brand group-hover:text-white">
                  <Icon className="size-5" />
                </div>
                <h3 className="font-semibold">{t(k(`landing.features.${id}.title`))}</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{t(k(`landing.features.${id}.desc`))}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </section>

      <section id="workflow" className="scroll-mt-20 border-y bg-muted/30 py-24">
        <div className="mx-auto max-w-6xl px-6">
          <Reveal className="text-center">
            <h2 className="text-3xl font-semibold tracking-tight md:text-4xl">{t('landing.workflowTitle')}</h2>
          </Reveal>
          <ol className="relative mt-14 grid gap-8 md:grid-cols-4">
            <div aria-hidden className="absolute left-0 right-0 top-5 hidden h-px bg-border md:block">
              <motion.div className="h-full origin-left bg-brand"
                          initial={{ scaleX: reduced ? 1 : 0 }} whileInView={{ scaleX: 1 }}
                          viewport={{ once: true }} transition={{ duration: 1.2, ease: 'easeOut' }} />
            </div>
            {STEPS.map((id, i) => (
              <Reveal key={id} delay={i * 0.15}>
                <li className="relative list-none">
                  <span className="relative z-10 flex size-10 items-center justify-center rounded-full border bg-background font-mono text-sm font-semibold">
                    {i + 1}
                  </span>
                  <h3 className="mt-4 font-semibold">{t(k(`landing.steps.${id}.title`))}</h3>
                  <p className="mt-1.5 text-sm text-muted-foreground">{t(k(`landing.steps.${id}.desc`))}</p>
                </li>
              </Reveal>
            ))}
          </ol>
        </div>
      </section>

      <section id="faq" className="mx-auto max-w-3xl scroll-mt-20 px-6 py-24">
        <Reveal className="text-center">
          <h2 className="text-3xl font-semibold tracking-tight md:text-4xl">{t('landing.faqTitle')}</h2>
        </Reveal>
        <Reveal className="mt-10">
          <Accordion type="single" collapsible className="w-full">
            {FAQ.map((id) => (
              <AccordionItem key={id} value={id}>
                <AccordionTrigger className="text-left">{t(k(`landing.faq.${id}.q`))}</AccordionTrigger>
                <AccordionContent className="text-muted-foreground">{t(k(`landing.faq.${id}.a`))}</AccordionContent>
              </AccordionItem>
            ))}
          </Accordion>
        </Reveal>
      </section>

      <section className="px-6 pb-24">
        <Reveal className="relative mx-auto max-w-5xl overflow-hidden rounded-3xl border bg-card px-8 py-16 text-center">
          <div aria-hidden className="absolute inset-x-0 -top-24 mx-auto h-48 w-2/3 rounded-full bg-brand opacity-20 blur-3xl" />
          <h2 className="relative text-3xl font-semibold tracking-tight md:text-4xl">{t('landing.ctaTitle')}</h2>
          <p className="relative mt-4 text-muted-foreground">{t('landing.ctaSub')}</p>
          <Button size="lg" className="relative mt-8 gap-2" onClick={onSignUp}>
            {t('landing.signUp')}<ArrowRight className="size-4" />
          </Button>
        </Reveal>
      </section>

      <footer className="border-t">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-6 py-8 text-sm text-muted-foreground">
          <Logo />
          <span>{t('landing.footer')}</span>
          <LangToggle />
        </div>
      </footer>
    </div>
  )
}
```

`MsgKey` must be exported from `@/i18n/core` (it is, per sub-plan 1). If template-literal keys fail typecheck despite the `as MsgKey` cast, keep the cast helper `k()` as written.

- [ ] **Step 5: 验证与提交**

Run: `npm test 2>&1 | grep -c "ALL PASS" ; npm run lint 2>&1 | tail -2 ; npx vite build 2>&1 | tail -2`
Expected: `10`; 0 errors; build ok.

```bash
git add src/components/ui/accordion.tsx src/components/landing package.json package-lock.json
git commit -m "首页：滚动磨砂顶栏（锚点、语言、主题、登录、免费注册）、首屏（渐变标题、慢速光斑、带视差的画布示意图）、功能六卡、流程四步与连线点亮、常见问题折叠、结尾号召与页脚；滚到时淡入上浮，尊重减少动态效果"
```

（`package.json`/`package-lock.json` only if the accordion CLI added a dependency.）

---

### Task 4: 接进 App，更新流程测试

**Files:** Modify `src/App.tsx`、`tests/flow.test.tsx`；Delete `src/components/LoginView.tsx`

- [ ] **Step 1: `App.tsx`**

- Replace `import { LoginView } from './components/LoginView'` with:

```tsx
import { AuthDialog } from './components/auth/AuthDialog'
import type { AuthMode } from './components/auth/AuthDialog'
import { Landing } from './components/landing/Landing'
import { translate } from './i18n/core'
```

- Next to the other `useState`s add:

```tsx
  /** 没登录时的登录注册对话框；expired 为登录失效后自动打开时的提示 */
  const [auth, setAuth] = useState<{ open: boolean; mode: AuthMode; expired: boolean }>(
    { open: false, mode: 'login', expired: false })
```

- Change the unauthorized effect to also open the login dialog:

```tsx
  // 登录态失效（token 过期或被撤销）→ 回首页并打开登录框
  useEffect(() => onUnauthorized(() => {
    setAdminOpen(false)
    setUser(null)
    setAuth({ open: true, mode: 'login', expired: true })
  }), [])
```

- Add an effect that opens registration on a fresh install (no accounts at all):

```tsx
  // 全新部署（服务端还没有任何账号）：首页直接打开注册
  const firstRun = (svc?.users ?? 0) === 0 && !!svc
  useEffect(() => {
    if (!user && firstRun) setAuth((a) => (a.open ? a : { open: true, mode: 'register', expired: false }))
  }, [user, firstRun])
```

  （放在 `if (!user)` 之前；`svc` 为 null 时不算全新部署。）

- In `logout`, add `setAuth({ open: false, mode: 'login', expired: false })`.

- Replace `if (!user) { return <LoginView … /> }` with:

```tsx
  if (!user) {
    return (
      <>
        <Landing onSignIn={() => setAuth({ open: true, mode: 'login', expired: false })}
                 onSignUp={() => setAuth({ open: true, mode: 'register', expired: false })} />
        <AuthDialog open={auth.open} mode={auth.mode} firstRun={firstRun}
                    notice={auth.expired ? translate('zh', 'auth.expired') : null}
                    onMode={(mode) => setAuth((a) => ({ ...a, mode }))}
                    onClose={() => setAuth((a) => ({ ...a, open: false }))}
                    onDone={(u) => { setAuth({ open: false, mode: 'login', expired: false }); setUser(u) }} />
      </>
    )
  }
```

  The `notice` should follow the UI language: replace `translate('zh', 'auth.expired')` with `t('auth.expired')` using `const { t } = useI18n()` at the top of `App` (import `useI18n` from `./i18n/core`; `App` is a component, so the hook is allowed). Use the hook version; the `translate` import is then unnecessary — drop it.

- `git rm src/components/LoginView.tsx`. Delete its now-unused `.login*` rules from `src/index.css` only if nothing else uses them (`grep -rn "login__" src` must show only AuthDialog's classes, which are hooks for tests and need no CSS).

- [ ] **Step 2: 流程测试**

`tests/flow.test.tsx` deliberately changes in three places (退出后回到首页、要先点「登录」才出表单):

(a) Right after the `btn` helper is defined (`const btn = (t: string) => …`), and before its first use, add a helper; also move/define it before step 12 if `btn` is defined later — define it near `findByText`:

```tsx
/** 退出后回到首页：先点右上角「登录」打开对话框 */
const openLogin = async () => {
  await click(container.querySelector('[data-testid="landing-login"]') as unknown as HTMLElement)
}
```

(b) Step 12: after `await click(findByText('button', '退出'))` add `await openLogin()` before `must(has('login__tab') && …)`.

(c) Step 12b: after the first `await click(findByText('button', '退出'))` (before `await loginAs('boss', …)`) add `await openLogin()`. The 401 case needs no change (the dialog opens itself).

(d) Step 15: after `await click(findByText('button', '退出'))` add `await openLogin()`.

Step 0 stays as is (fresh install opens registration automatically). The mismatch text, `注册并进入`, `.login__field input`, `.login__tab` and `button[type="submit"]` all still exist in `AuthDialog`.

- [ ] **Step 3: 验证与提交**

Run: `npm test 2>&1 | grep -E "ALL PASS|✗" ; npm run lint 2>&1 | tail -2 ; npx vite build 2>&1 | tail -2`
Expected: ten `ALL PASS`, no `✗`; 0 errors; build ok.

```bash
git add src/App.tsx src/index.css tests/flow.test.tsx
git rm --cached -q src/components/LoginView.tsx 2>/dev/null; git add -u src/components/LoginView.tsx
git commit -m "没登录时显示首页：右上角与按钮打开登录注册对话框，全新部署自动打开注册，登录失效回首页并打开登录框提示过期，主动退出只回首页；流程测试改为先点「登录」"
```

---

### Task 5: 首页测试

**Files:** Create `tests/landing.test.tsx`；Modify `package.json`

- [ ] **Step 1: 测试**

```tsx
/** 首页与登录注册对话框：中英文渲染、锚点与按钮、对话框页签与两次密码、全新部署引导文案、Esc 关闭、
 *  没有 IntersectionObserver 时内容直接可见。跑法：npm test */
import { Window } from 'happy-dom'

const win = new Window({ url: 'http://localhost:5173' })
const g = globalThis as Record<string, unknown>
for (const k of ['window', 'document', 'navigator', 'location', 'HTMLElement', 'Element', 'Node', 'Event',
                 'CustomEvent', 'KeyboardEvent', 'MouseEvent', 'PointerEvent', 'getComputedStyle',
                 'localStorage', 'sessionStorage', 'matchMedia', 'ResizeObserver', 'DOMRect', 'MutationObserver']) {
  Object.defineProperty(g, k, {
    value: (win as unknown as Record<string, unknown>)[k], writable: true, configurable: true,
  })
}
g.IS_REACT_ACT_ENVIRONMENT = true

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }
const { act, useState } = await import('react')
const { createRoot } = await import('react-dom/client')
const { I18nProvider } = await import('../src/i18n')
const { useI18n } = await import('../src/i18n/core')
const { Landing } = await import('../src/components/landing/Landing')
const { AuthDialog } = await import('../src/components/auth/AuthDialog')
type Mode = 'login' | 'register'

const container = win.document.createElement('div')
win.document.body.appendChild(container)
const root = createRoot(container as unknown as HTMLElement)
const settle = async (ms = 40) => { await act(async () => { await new Promise((r) => setTimeout(r, ms)) }) }
const html = () => win.document.body.innerHTML
const click = async (el: Element | null) => {
  if (!el) throw new Error('✗ 元素不存在')
  await act(async () => { el.dispatchEvent(new win.MouseEvent('click', { bubbles: true }) as unknown as Event) })
  await settle()
}
const q = (s: string) => win.document.querySelector(s)

let setLoc: (l: 'zh' | 'en') => void = () => {}
function Grab() { setLoc = useI18n().setLocale; return null }
function Host({ firstRun }: { firstRun: boolean }) {
  const [auth, setAuth] = useState<{ open: boolean; mode: Mode }>({ open: firstRun, mode: firstRun ? 'register' : 'login' })
  return (
    <I18nProvider initial="zh">
      <Grab />
      <Landing onSignIn={() => setAuth({ open: true, mode: 'login' })} onSignUp={() => setAuth({ open: true, mode: 'register' })} />
      <AuthDialog open={auth.open} mode={auth.mode} firstRun={firstRun}
                  onMode={(mode) => setAuth((a) => ({ ...a, mode }))} onClose={() => setAuth((a) => ({ ...a, open: false }))}
                  onDone={() => {}} />
    </I18nProvider>
  )
}

// 1. 中文首页：各段都在；对话框没开
await act(async () => { root.render(<Host firstRun={false} />) })
await settle()
for (const s of ['从文字，到成片。', '小说转分镜', '完整性检查', '四步出一集', '常见问题', '把下一章，变成下一集。', '免费注册']) {
  must(html().includes(s), `首页应有「${s}」`)
}
must(!!q('#features') && !!q('#workflow') && !!q('#faq'), '三个锚点')
must(!q('[data-testid="auth-dialog"]'), '有账号时首页不自动弹出')
console.log('1. 中文首页 ✓')

// 2. 右上角「登录」打开登录页签；切到注册出现确认密码；不一致时提交禁用
await click(q('[data-testid="landing-login"]'))
must(!!q('[data-testid="auth-dialog"]') && html().includes('欢迎回来'), '打开登录')
must(win.document.querySelectorAll('.login__field input').length === 2, '登录两个输入框')
const regTab = [...win.document.querySelectorAll('.login__tab')].find((b) => b.textContent === '注册')!
await click(regTab)
must(html().includes('创建账号') && win.document.querySelectorAll('.login__field input').length === 3, '注册三个输入框')
const setter = Object.getOwnPropertyDescriptor(win.HTMLInputElement.prototype, 'value')!.set!
const type = async (el: Element, text: string) => {
  await act(async () => {
    setter.call(el, text)
    el.dispatchEvent(new win.Event('input', { bubbles: true }) as unknown as Event)
  })
  await settle()
}
const [u, p, c] = [...win.document.querySelectorAll('.login__field input')]
await type(u, 'amy')
await type(p, 'pw123456')
await type(c, 'pw12345X')
must(html().includes('两次输入的密码不一致')
  && (q('button[type="submit"]') as unknown as HTMLButtonElement).disabled, '两次密码不一致拦截')
console.log('2. 登录注册页签与两次密码 ✓')

// 3. Esc 关闭
await act(async () => { win.dispatchEvent(new win.KeyboardEvent('keydown', { key: 'Escape' }) as unknown as Event) })
await settle(300)
must(!q('[data-testid="auth-dialog"]'), 'Esc 关闭对话框')
console.log('3. Esc 关闭 ✓')

// 4. 全新部署：一打开就是注册，并有引导文案
await act(async () => { root.render(<Host key="fresh" firstRun />) })
await settle()
must(!!q('[data-testid="auth-dialog"]') && html().includes('第一个注册的账号'), '全新部署自动打开注册并引导')
console.log('4. 全新部署引导 ✓')

// 5. 切到英文：首页与对话框都变英文
await act(async () => { setLoc('en') })
await settle()
for (const s of ['From ink to reel.', 'Integrity check', 'Four steps to an episode', 'Create your account', 'Sign up free']) {
  must(html().includes(s), `英文应有「${s}」`)
}
console.log('5. 英文首页 ✓')

await act(async () => { root.unmount() })
console.log('\nALL PASS')
```

In `package.json`, append to the `test` script:

```
 && vite build --ssr tests/landing.test.tsx --outDir .ssrout --logLevel error && node .ssrout/landing.test.js
```

If happy-dom lacks a global motion/Radix needs, polyfill minimally at the top and note it; keep every assertion.

- [ ] **Step 2: 全量回归**

Run: `npm test 2>&1 | grep -c "ALL PASS" ; npm run lint 2>&1 | tail -2 ; npx vite build 2>&1 | tail -3`
Expected: `11`; 0 errors; build ok.

- [ ] **Step 3: 提交**

```bash
git add tests/landing.test.tsx package.json
git commit -m "首页测试：中英文各段、锚点、登录注册页签与两次密码、Esc 关闭、全新部署引导"
```

- [ ] **Step 4: 验收准备（控制者做）**

控制者确认本地服务在跑（假厂商），请用户退出登录后看首页：滚动时顶栏磨砂、锚点平滑滚动、功能卡依次进场、流程连线点亮、常见问题展开、深浅与中英切换、登录注册对话框的动效。
