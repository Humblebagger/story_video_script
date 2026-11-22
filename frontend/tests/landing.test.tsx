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
// motion 的 whileInView / 动画帧要用这两个浏览器接口，happy-dom 没有全局版本：补最小桩
g.IntersectionObserver ??= class { observe() {} unobserve() {} disconnect() {} takeRecords() { return [] } }
g.requestAnimationFrame ??= (cb: (t: number) => void) => setTimeout(() => cb(Date.now()), 16)
g.cancelAnimationFrame ??= (id: number) => clearTimeout(id)

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
{
  const { zh } = await import('../src/i18n/zh')
  const trig = [...win.document.querySelectorAll('#faq button')].find((b) => b.textContent === zh.landing.faq.models.q)!
  await click(trig)
  must(html().includes(zh.landing.faq.models.a), 'FAQ「支持哪些模型」的回答渲染出来')
}
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

// 5b. 登录报错：消息对象按界面语言渲染，切换语言即时更新；字符串 detail 原样显示
let loginDetail: unknown = { code: 'auth.bad_credentials', params: {}, message: '用户名或密码不正确' }
g.fetch = async () => ({ ok: false, status: 401, statusText: '',
  text: async () => JSON.stringify({ detail: loginDetail }), json: async () => ({ detail: loginDetail }) })
await act(async () => { setLoc('zh') })
await settle()
await act(async () => { root.render(<Host key="err" firstRun={false} />) })
await settle()
await click(q('[data-testid="landing-login"]'))
{
  const [u2, p2] = [...win.document.querySelectorAll('.login__field input')]
  await type(u2, 'amy')
  await type(p2, 'wrongpw1')
  await click(q('button[type="submit"]'))
  must(q('[role="alert"]')?.textContent === '用户名或密码不正确', '中文界面显示登录错误')
  await act(async () => { setLoc('en') })
  await settle()
  must(q('[role="alert"]')?.textContent === 'Incorrect username or password', '切到英文后同一条提示变英文: ' + q('[role="alert"]')?.textContent)
  loginDetail = '原样的字符串'
  await click(q('button[type="submit"]'))
  must(q('[role="alert"]')?.textContent === '原样的字符串', '字符串 detail 原样显示')
}
console.log('5b. 登录错误按语言渲染 ✓')

// 6. 没有 IntersectionObserver：首页不抛错，内容在
await act(async () => { root.unmount() })
const savedIO = g.IntersectionObserver
delete g.IntersectionObserver
const root2 = createRoot(container as unknown as HTMLElement)
await act(async () => { root2.render(<I18nProvider initial="zh"><Landing onSignIn={() => {}} onSignUp={() => {}} /></I18nProvider>) })
must(!!q('[data-testid="landing"]') && html().includes('免费注册'), '没有 IntersectionObserver 时首页照常渲染')
g.IntersectionObserver = savedIO
console.log('6. 无 IntersectionObserver ✓')

await act(async () => { root2.unmount() })
console.log('\nALL PASS')
