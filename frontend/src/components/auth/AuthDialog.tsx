/** 登录 / 注册对话框（原 LoginView 的逻辑）：页签切换；注册要输两次密码；全新部署时引导注册；
 *  错误显示在表单里；成功后回调 onDone。不走 portal：渲染在应用树里（测试能在容器里找到表单）。
 *  测试依赖：.login__tab、.login__field input、提交按钮 type=submit、「注册并进入」「第一个注册的账号」「两次输入的密码不一致」。 */
import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { X } from 'lucide-react'
import { login, register } from '@/api'
import { setSession } from '@/auth'
import type { User } from '@/auth'
import { LogoMark } from '@/components/brand/Logo'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useI18n } from '@/i18n/core'
import { errValue, formatMsg } from '@/i18n/serverMsg'
import type { MsgLike } from '@/i18n/serverMsg'
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
  const { t, locale } = useI18n()
  const m = useMotionPresets()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<MsgLike>(null)
  const registering = mode === 'register'
  // 密码打错一个字符，注册完就再也登不进去——所以注册必须二次确认
  const mismatch = registering && confirm.length > 0 && confirm !== password
  const ready = username.trim() && password && (!registering || confirm === password)

  const formRef = useRef<HTMLFormElement>(null)
  useEffect(() => { setConfirm(''); setError(null) }, [mode])
  // 关闭后清空输入与错误，下次打开是干净的
  useEffect(() => {
    if (!open) { setUsername(''); setPassword(''); setConfirm(''); setError(null) }
  }, [open])
  // 打开时记下原焦点，关闭后还回去
  useEffect(() => {
    if (!open) return
    const opener = document.activeElement as HTMLElement | null
    return () => { opener?.focus?.() }
  }, [open])
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !busy) { onClose(); return }
      if (e.key !== 'Tab') return
      // 焦点留在对话框内：Tab / Shift+Tab 首尾循环
      const form = formRef.current
      if (!form) return
      const items = [...form.querySelectorAll<HTMLElement>('button, input, [href], [tabindex]:not([tabindex="-1"])')]
        .filter((el) => !(el as HTMLButtonElement).disabled)
      if (items.length === 0) return
      const first = items[0], last = items[items.length - 1]
      const active = document.activeElement
      if (e.shiftKey && (active === first || !form.contains(active))) { e.preventDefault(); last.focus() }
      else if (!e.shiftKey && (active === last || !form.contains(active))) { e.preventDefault(); first.focus() }
    }
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
      setError(errValue(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <AnimatePresence>
      {open && (
        <motion.div key="auth" className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto p-4"
                    initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                    transition={{ duration: 0.18 }}>
          <div className="absolute inset-0 bg-background/60 backdrop-blur-md" onClick={() => !busy && onClose()} />
          <motion.form ref={formRef} {...m.pop} onSubmit={submit} role="dialog" aria-modal="true"
                       aria-label={registering ? t('auth.registerTitle') : t('auth.loginTitle')}
                       data-testid="auth-dialog"
                       className="login__box relative grid w-full max-w-3xl overflow-hidden rounded-[24px] border bg-card shadow-2xl md:grid-cols-[1.05fr_0.95fr]">
            <div className="login__visual" aria-hidden="true">
              <div className="login__vis-brand">
                <LogoMark size={31} />
                <span>{t('brand.name')}</span>
              </div>
              <div className="login__vis-main">
                <p className="login__kicker">{t('auth.sideKicker')}</p>
                <h2>{t('auth.sideTitle')}</h2>
                <p>{t('auth.sideBody')}</p>
              </div>
              <div className="login__stack">
                {[
                  ['blue', '01', t('auth.flowSource'), '78%'],
                  ['sand', '02', t('auth.flowShots'), '62%'],
                  ['violet', '03', t('auth.flowFilm'), '46%'],
                ].map(([tone, n, label, width]) => (
                  <div className="login__stackrow" data-tone={tone} key={n}>
                    <span>{n}</span><b>{label}</b><i style={{ width }} />
                  </div>
                ))}
              </div>
              <div className="login__vis-foot">{t('brand.tagline')}</div>
            </div>
            <div className="login__formpanel relative flex min-w-0 flex-col gap-4 p-6 sm:p-8">
              <button type="button" aria-label={t('common.close')} onClick={onClose} disabled={busy}
                      className="absolute right-3 top-3 rounded-md p-1 text-muted-foreground hover:text-foreground">
                <X className="size-4" />
              </button>
              <div className="login__formhead">
                <span className="login__mobilemark"><LogoMark size={30} /></span>
                <div>
                  <p className="login__kicker">{t('brand.tagline')}</p>
                  <h2>{registering ? t('auth.registerTitle') : t('auth.loginTitle')}</h2>
                </div>
              </div>
              {notice && <p className="rounded-lg bg-warning/15 px-3 py-2 text-sm">{notice}</p>}
              <div role="tablist" className="login__tabs grid grid-cols-2 rounded-lg bg-muted p-1">
                {(['login', 'register'] as const).map((k) => (
                  <button type="button" key={k} role="tab" aria-selected={mode === k} onClick={() => onMode(k)}
                          className={cn('login__tab rounded-md py-1.5 text-sm transition-colors',
                                        mode === k ? 'is-on font-medium' : 'text-muted-foreground hover:text-foreground')}>
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
                         aria-describedby={mismatch ? 'auth-mismatch' : undefined}
                         onChange={(e) => setConfirm(e.target.value)} />
                  {mismatch && <em id="auth-mismatch" role="alert" className="block text-xs not-italic text-destructive">{t('auth.mismatch')}</em>}
                </label>
              )}
              {error && <p role="alert" className="text-sm text-destructive">{formatMsg(error, locale)}</p>}
              <Button type="submit" className="w-full" disabled={busy || !ready}>
                {busy ? t('auth.wait') : registering ? t('auth.submitRegister') : t('auth.submitLogin')}
              </Button>
              <p className="text-center text-xs text-muted-foreground">{t('auth.tip')}</p>
            </div>
          </motion.form>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
