/** 管理后台的界面回归：概览、用户（排序/搜索/操作）、用量、任务、审计，以及入口。
 *  用桩后端代替 /admin 接口。
 *
 *  跑法：npm test
 */
import { Window } from 'happy-dom'

const win = new Window({ url: 'http://localhost:5173' })
const g = globalThis as Record<string, unknown>
for (const k of ['window', 'document', 'navigator', 'location', 'HTMLElement',
                 'Element', 'Node', 'Event', 'CustomEvent', 'KeyboardEvent', 'getComputedStyle',
                 'localStorage', 'sessionStorage', 'PointerEvent', 'MouseEvent', 'matchMedia', 'ResizeObserver',
                 'DOMRect', 'MutationObserver']) {
  Object.defineProperty(g, k, {
    value: (win as unknown as Record<string, unknown>)[k],
    writable: true, configurable: true,
  })
}
g.IS_REACT_ACT_ENVIRONMENT = true
g.requestAnimationFrame = (cb: (t: number) => void) =>
  setTimeout(() => cb(performance.now()), 16) as unknown as number
g.cancelAnimationFrame = (id: number) => clearTimeout(id)

/* ---------- 桩后端 ---------- */
const calls: string[] = []
let slowMs = 0
let failOverview = false
let failPatch = false
const REF = { ref: 'K7Q2M9XD', at: '2026-10-30T09:00:00+00:00', user_id: 'u-bob', username: 'bob',
  code: 'common.internal', params: {}, where: 'GET /novels' }
const daily = Array.from({ length: 30 }, (_, i) => ({
  day: `2026-10-${String(i + 1).padStart(2, '0')}`, cost_usd: i === 29 ? 4.5 : 0 }))
const users = [
  { id: 'u-root', username: 'root', role: 'admin', disabled: false, created_at: '2026-10-01T00:00:00+00:00',
    last_seen_at: '2026-10-30T08:00:00+00:00', has_password: true, monthly_cap_usd: null,
    novels: 0, chapters: 0, versions: 0, month_cost_usd: 0 },
  { id: 'u-bob', username: 'bob', role: 'user', disabled: false, created_at: '2026-10-05T00:00:00+00:00',
    last_seen_at: null, has_password: true, monthly_cap_usd: 5,
    novels: 2, chapters: 3, versions: 4, month_cost_usd: 4.5 },
  { id: 'u-amy', username: 'amy', role: 'user', disabled: false, created_at: '2026-10-09T00:00:00+00:00',
    last_seen_at: null, has_password: false, monthly_cap_usd: null,
    novels: 1, chapters: 1, versions: 1, month_cost_usd: 9 },
]
g.fetch = async (url: string, init?: { method?: string; body?: string }) => {
  const path = String(url).replace(/^\/api/, '')
  const method = init?.method ?? 'GET'
  calls.push(`${method} ${path}${init?.body ? ' ' + init.body : ''}`)
  const json = (data: unknown) => ({ ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(data)),
                                     text: async () => JSON.stringify(data) })
  const err = (status: number, detail: unknown) => ({
    ok: false, status, text: async () => JSON.stringify({ detail }), json: async () => ({ detail }) })
  if (path === '/admin/overview' && failOverview) return err(500, {
    code: 'common.internal', params: {}, message: '服务器出了点问题，请稍后再试（参考编号 K7Q2M9XD）', ref: 'K7Q2M9XD' })
  if (path === '/admin/errors') return json({ errors: [REF] })
  const em = path.match(/^\/admin\/errors\/(.+)$/)
  if (em) {
    const norm = decodeURIComponent(em[1]).replace(/-/g, '').toUpperCase()
    return norm === 'K7Q2M9XD' ? json({ ...REF, detail: 'Traceback: boom' }) : err(404, {
      code: 'admin.error_ref.not_found', params: { ref: norm }, message: `没有这个参考编号：${norm}` })
  }
  if (path === '/admin/overview') await new Promise((r) => setTimeout(r, slowMs))
  if (path === '/admin/overview') return json({ users: 3, active_7d: 1, tokens_30d: 1234567,
    cost_30d: 13.5, running: 1, failed_7d: 2, daily, unpriced_models: ['mystery'] })
  if (path === '/admin/users') return json({ users })
  const m = path.match(/^\/admin\/users\/([^/]+)(\/password)?$/)
  if (m && method === 'GET') {
    const u = users.find((x) => x.id === m[1])!
    return json({ user: u, daily, recent: [{ at: '2026-10-30T08:00:00+00:00', user_id: u.id,
      novel_id: 'n1', chapter_id: 'c1', version_id: 'v1', purpose: 'convert', model: 'claude-sonnet-5',
      ok: true, calls: 3, input: 1000, output: 2000, cache_read: 0, cache_write: 0, chars: 4000,
      novel_title: '药', chapter_title: '第一章', cost_usd: 0.02 }] })
  }
  if (m && method === 'PATCH' && failPatch) return err(400, {
    code: 'admin.self_disable', params: {}, message: '不能停用自己' })
  if (m && method === 'PATCH') {
    const u = users.find((x) => x.id === m[1])!
    Object.assign(u, JSON.parse(init!.body!))
    return json(u)
  }
  if (m && m[2] && method === 'POST') {
    const { password } = JSON.parse(init!.body!)
    return password.length < 6 ? err(400, '密码至少 6 位') : json({ ok: true })
  }
  if (path.startsWith('/admin/usage.csv')) return json('at,user_id\n')
  if (path.startsWith('/admin/usage')) {
    const group = new URL('http://x' + path).searchParams.get('group')
    return json({ group, days: 30, per_k_chars: { n: 2, mean: 0.75, p90: 3 }, unpriced_models: [],
      rows: [{ key: 'u-bob', label: group === 'user' ? 'bob' : group === 'model' ? 'claude-sonnet-5' : '2026-10-30',
               calls: 3, input: 1000, output: 2000, cache_read: 0, cache_write: 0, chars: 4000,
               cost_usd: 4.5, unpriced: 0, records: 1 },
             { key: 'u-amy', label: group === 'user' ? 'amy' : group === 'model' ? 'mystery' : '2026-10-29',
               calls: 2, input: 10, output: 20, cache_read: 0, cache_write: 0, chars: 100,
               cost_usd: 0, unpriced: 2, records: 2 },
             { key: 'u-free', label: group === 'user' ? 'free' : group === 'model' ? 'free-model' : '2026-10-28',
               calls: 1, input: 5, output: 5, cache_read: 0, cache_write: 0, chars: 50,
               cost_usd: 0, unpriced: 0, records: 1 }] })
  }
  if (path === '/admin/jobs') return json({
    running: [{ id: 'j1', username: 'bob', status: 'running', work_title: '药', chapter: '第一章',
                chars: 4000, created_at: '2026-10-30T08:00:00+00:00', elapsed_sec: 75 }],
    failed: [{ id: 'v9', username: 'amy', novel_title: '孔乙己', chapter_title: '一',
               created_at: '2026-10-29T08:00:00+00:00', chars: 900, attempts: 3,
               error: 'schema 校验失败：缺少 episodes' },
              { id: 'v10', username: 'amy', novel_title: '孔乙己', chapter_title: '二',
                created_at: '2026-10-28T08:00:00+00:00', chars: 10, attempts: 1,
                error: '没有可用的模型', error_msg: { code: 'usage.monthly_cap', params: {}, message: '本月用量已达上限，请联系管理员' } }] })
  if (path.startsWith('/admin/audit')) return json({ audit: [
    { at: '2026-10-30T09:00:00+00:00', admin: 'root', action: 'disable', target: 'bob',
      before: { disabled: false }, after: { disabled: true } },
    { at: '2026-10-30T09:05:00+00:00', admin: 'root', action: 'view_error_ref', target: 'bob',
      before: null, after: { ref: 'K7Q2M9XD' } }] })
  if (path === '/admin/pricing' && method === 'GET') return json({ currency: 'USD', updated_at: null,
    models: { 'claude-sonnet-5': { input: 2, output: 10, cache_read: 0.2, cache_write: 2.5 } } })
  if (path === '/admin/pricing' && method === 'PUT') {
    const t = JSON.parse(init!.body!)
    return t.models ? json({ ...t, currency: 'USD', updated_at: 'now' }) : err(400, '价格表必须包含至少一个模型')
  }
  throw new Error(`桩后端未实现的路径: ${method} ${path}`)
}

const { act } = await import('react')
const { createRoot } = await import('react-dom/client')
const { Overview } = await import('../src/components/admin/Overview')
const { Users } = await import('../src/components/admin/Users')
const { UsageTab } = await import('../src/components/admin/UsageTab')
const { JobsTab } = await import('../src/components/admin/JobsTab')
const { AuditTab } = await import('../src/components/admin/AuditTab')
const { ErrorsTab } = await import('../src/components/admin/ErrorsTab')
const { AdminView } = await import('../src/components/admin/AdminView')
const { notice } = await import('../src/lib/notice')
const { I18nProvider } = await import('../src/i18n')
const { useI18n } = await import('../src/i18n/core')
const { setCurrentLocale } = await import('../src/i18n/core')
import type { ReactNode } from 'react'

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }
const container = win.document.createElement('div')
win.document.body.appendChild(container)
let root = createRoot(container as unknown as HTMLElement)
const settle = async (ms = 30) => {
  await act(async () => { await new Promise((r) => setTimeout(r, ms)) })
}
const text = () => container.textContent ?? ''
const button = (label: string) => {
  const b = [...container.querySelectorAll('button')].find((x) => (x.textContent ?? '').includes(label))
  if (!b) throw new Error(`✗ 找不到按钮「${label}」`)
  return b as unknown as HTMLButtonElement
}
const click = async (el: Element) => {
  await act(async () => { el.dispatchEvent(new win.MouseEvent('click', { bubbles: true }) as unknown as Event) })
  await settle()
}
const confirmDialog = () => win.document.body.querySelector('[data-testid="confirm-dialog"]')
async function answer(ok: boolean) {
  const btn = win.document.body.querySelector<HTMLElement>(`[data-testid="${ok ? 'confirm-ok' : 'confirm-cancel'}"]`)
  must(!!btn, '应弹出确认框')
  await click(btn!)
}
const lastNotice = () => notice.log[notice.log.length - 1]
const type = async (el: Element, value: string) => {
  await act(async () => {
    const input = el as unknown as HTMLInputElement
    const setter = Object.getOwnPropertyDescriptor(win.HTMLInputElement.prototype, 'value')!.set!
    setter.call(input, value)
    input.dispatchEvent(new win.Event('input', { bubbles: true }) as unknown as Event)
  })
  await settle()
}
const remount = async (node: ReactNode) => {
  await act(async () => { root.unmount() })
  root = createRoot(container as unknown as HTMLElement)
  await act(async () => { root.render(node) })
  await settle()
}

// 1. 概览：六张卡片、未定价提示、折线图
await remount(<Overview />)
for (const s of ['用户', '7 天活跃', '30 天 token', '30 天金额', '运行中任务', '7 天失败']) {
  must(text().includes(s), `概览应有「${s}」`)
}
must(text().includes('1,234,567') && text().includes('$13.50'), '数字与金额格式')
must(text().includes('mystery'), '应提示未定价模型')
must(container.querySelectorAll('.adm__chart circle').length === 30, '折线图 30 个点')
console.log('1. 概览：卡片 / 格式 / 未定价提示 / 折线图 ✓')

// 2. 用户：默认按注册时间倒序；点表头按本月金额排序；搜索
const me = { id: 'u-root', username: 'root', created_at: '', role: 'admin' as const }
await remount(<Users me={me} />)
const names = () => [...container.querySelectorAll('tbody tr.adm__row td:first-child')].map((td) => td.textContent)
must(names().join(',') === 'amy,bob,root', `默认注册倒序，实为 ${names()}`)
await click(button('本月金额'))
must(names().join(',') === 'amy,bob,root', '本月金额降序')
await click(button('本月金额'))
must(names().join(',') === 'root,bob,amy', '再点升序')
await type(container.querySelector('.adm__search')!, 'bo')
must(names().join(',') === 'bob', '搜索过滤')
must(text().includes('$5.00') && text().includes('$4.50'), '上限与本月金额')
console.log('2. 用户：排序 / 搜索 / 金额 ✓')

// 3. 详情与操作：停用带确认、改上限、重置密码（失败提示）、自己不能停用
await click(container.querySelector('tbody tr.adm__row')!)
must(text().includes('药 / 第一章') && text().includes('转换'), '详情显示最近用量与标题')
await click(button('停用'))
must((confirmDialog()?.textContent ?? '').includes('停用'), '停用应先确认')
must(!calls.some((c) => c.startsWith('PATCH /admin/users/u-bob {"disabled"')), '确认前不发请求')
await answer(false)
must(!calls.some((c) => c.startsWith('PATCH /admin/users/u-bob {"disabled"')), '取消后不发请求')
await click(button('停用'))
await answer(true)
must(calls.some((c) => c === 'PATCH /admin/users/u-bob {"disabled":true}'), '应请求停用')
must(!!container.querySelector('tbody tr.adm__row .adm__bad'), '列表刷新为已停用（该行显示已停用）')
await type(container.querySelector('input[placeholder^="月上限"]')!, '')
await click(button('设上限'))
must(calls.some((c) => c === 'PATCH /admin/users/u-bob {"monthly_cap_usd":null}'), '空上限 = 不限')
await type(container.querySelector('input[type=password]')!, 'goodpass1')
await click(button('重置密码'))
await answer(true)
must(calls.some((c) => c.startsWith('POST /admin/users/u-bob/password')), '应请求重置密码')
await type(container.querySelector('.adm__search')!, 'root')
await click(container.querySelector('tbody tr.adm__row')!)
must(button('停用').disabled && button('取消管理员').disabled, '自己不能停用、不能改自己的角色')
must(text().includes('不能停用自己'), '应说明原因')
console.log('3. 详情 / 停用确认 / 上限不限 / 重置密码 / 自己受限 ✓')

// 3b. 月上限输入校验：非数字、负数不发请求，并给出提示
await type(container.querySelector('.adm__search')!, 'bob')
await click(container.querySelector('tbody tr.adm__row')!)
const patches = () => calls.filter((c) => c.startsWith('PATCH /admin/users/u-bob')).length
const hint = '请输入不小于 0 的金额'
const before = patches()
await type(container.querySelector('input[placeholder^="月上限"]')!, 'abc')
await click(button('设上限'))
must(patches() === before, '非数字上限不应请求')
must(lastNotice().kind === 'err' && lastNotice().msg.includes(hint), '非数字应提示')
await type(container.querySelector('input[placeholder^="月上限"]')!, '-5')
await click(button('设上限'))
must(patches() === before, '负数上限不应请求')
must(lastNotice().kind === 'err' && lastNotice().msg.includes(hint), '负数应提示')
console.log('3b. 月上限非数字 / 负数拒绝 ✓')

// 4. 用量：默认按用户；切分组与范围会重新请求；每千字成本；价格表保存
await remount(<UsageTab />)
must(calls.includes('GET /admin/usage?group=user&days=30'), '默认按用户、30 天')
must(text().includes('bob') && text().includes('$0.7500') && text().includes('$3.0000'), '每千字成本')
await click(button('按模型'))
must(calls.includes('GET /admin/usage?group=model&days=30') && text().includes('claude-sonnet-5'), '切到按模型')
await click(button('7 天'))
must(calls.includes('GET /admin/usage?group=model&days=7'), '切到 7 天')
await click(button('保存价格表'))
must(calls.some((c) => c.startsWith('PUT /admin/pricing')) && lastNotice().kind === 'ok' && lastNotice().msg === '已保存', '价格表保存')
const area = container.querySelector('textarea')!
await act(async () => {
  const setter = Object.getOwnPropertyDescriptor(win.HTMLTextAreaElement.prototype, 'value')!.set!
  setter.call(area, '{not json')
  area.dispatchEvent(new win.Event('input', { bubbles: true }) as unknown as Event)
})
await settle()
await click(button('保存价格表'))
must(text().includes('不是合法的 JSON'), '非法 JSON 提示')
console.log('4. 用量：分组 / 范围 / 每千字成本 / 价格表保存与校验 ✓')

// 4b. 价格表：非有限或负数的单价不发请求，并给出提示
const setPricing = async (value: string) => {
  await act(async () => {
    const el = container.querySelector('textarea')!
    const setter = Object.getOwnPropertyDescriptor(win.HTMLTextAreaElement.prototype, 'value')!.set!
    setter.call(el, value)
    el.dispatchEvent(new win.Event('input', { bubbles: true }) as unknown as Event)
  })
  await settle()
}
const puts = () => calls.filter((c) => c.startsWith('PUT /admin/pricing')).length
const putsBefore = puts()
const priceHint = '单价必须是不小于 0 的有限数字'
const badPrice = (n: string) => `{"models":{"m":{"input":${n},"output":1,"cache_read":0,"cache_write":0}}}`
await setPricing(badPrice('-1'))
await click(button('保存价格表'))
must(puts() === putsBefore && text().includes(priceHint), '负数单价应拒绝并提示')
await setPricing(badPrice('1e400'))
await click(button('保存价格表'))
must(puts() === putsBefore && text().includes(priceHint), '溢出为 Infinity 的单价应拒绝并提示')
console.log('4b. 价格表：负数 / 溢出单价拒绝 ✓')

// 4c. 用量：刷新重新请求；整行未定价显示「未定价」而非 $0.00
const usageReqs = () => calls.filter((c) => c.startsWith('GET /admin/usage?group=model&days=7')).length
const reqsBefore = usageReqs()
await click(button('刷新'))
must(usageReqs() === reqsBefore + 1, '刷新应重新请求用量')
const mysteryRow = [...container.querySelectorAll('tbody tr')].find((tr) => (tr.textContent ?? '').includes('mystery'))
must(!!mysteryRow && mysteryRow.textContent!.includes('未定价') && !mysteryRow.textContent!.includes('$0.00'),
     '整行未定价应显示「未定价」')
must(text().includes('另有 2 条未定价') === false, '整行未定价不应再显示「另有」提示')
const freeRow = [...container.querySelectorAll('tbody tr')].find((tr) => (tr.textContent ?? '').includes('free-model'))
must(!!freeRow && freeRow.textContent!.includes('$0.00') && !freeRow.textContent!.includes('未定价'),
     '已定价但金额为 $0.00 的行应显示 $0.00 而非「未定价」')
console.log('4c. 用量：刷新重新请求 / 整行未定价显示「未定价」✓')

// 5. 任务：运行中与失败两表，报错可展开
await remount(<JobsTab />)
must(text().includes('1:15') && text().includes('孔乙己') && text().includes('schema 校验失败'), '任务两表')
console.log('5. 任务：运行中（已运行 1:15）/ 近期失败报错 ✓')

// 6. 审计
await remount(<AuditTab />)
must(text().includes('停用') && text().includes('root') && text().includes('bob'), '审计列表')
const auditReqs = () => calls.filter((c) => c === 'GET /admin/audit').length
const auditBefore = auditReqs()
await click(button('刷新'))
must(auditReqs() === auditBefore + 1, '审计刷新应重新请求')
console.log('6. 审计 / 刷新 ✓')

// 7. 页签框架：五个页签可切换，返回回调
let back = 0
await remount(<AdminView me={me} onBack={() => { back++ }} />)
for (const t of ['概览', '用户', '用量', '任务', '审计', '错误记录']) button(t)
must(text().includes('30 天金额'), '默认在概览')
await click(button('审计'))
must(text().includes('管理员') && text().includes('之前') && text().includes('之后'), '切到审计')
await click(button('返回'))
must(back === 1, '返回回调')
console.log('7. 页签框架 / 返回 ✓')

// 8. 加载骨架屏、30 天金额迷你折线
slowMs = 80
await act(async () => { root.unmount() })
root = createRoot(container as unknown as HTMLElement)
await act(async () => { root.render(<Overview />) })
must(container.querySelectorAll('[data-slot="skeleton"]').length >= 6, '加载中应显示骨架屏')
must(!text().includes('加载中'), '不再显示「加载中…」文字')
slowMs = 0
await settle(150)
must(container.querySelectorAll('[data-slot="skeleton"]').length === 0, '加载完骨架屏消失')
must(container.querySelectorAll('[data-testid="sparkline"] path').length >= 1, '30 天金额卡里有迷你折线')
console.log('8. 骨架屏 / 迷你折线 ✓')

// 9. 英文：页签文字
await remount(<I18nProvider initial="en"><AdminView me={me} onBack={() => {}} /></I18nProvider>)
const tabNames = [...container.querySelectorAll('.tabs__btn')].map((b) => b.textContent)
must(tabNames.join(' ') === 'Overview Users Usage Jobs Audit Errors', `英文页签，实为 ${tabNames.join(' ')}`)
must(text().includes('Active (7d)'), '英文概览')
await act(async () => { root.unmount() })
root = createRoot(container as unknown as HTMLElement)
setCurrentLocale('zh')
console.log('9. 英文页签 ✓')

// 10. 读取失败：错误条按语言渲染，编号保留
let setLoc: (l: 'zh' | 'en') => void = () => {}
function Grab() { setLoc = useI18n().setLocale; return null }
failOverview = true
await remount(<I18nProvider initial="zh"><Grab /><Overview /></I18nProvider>)
must(text().includes('服务器出了点问题') && text().includes('K7Q2M9XD'), `错误条中文与编号，实为 ${text()}`)
await act(async () => { setLoc('en') })
await settle()
must(text().includes('Something went wrong on the server') && text().includes('K7Q2M9XD') && !text().includes('服务器'),
     `切英文后错误条英文、编号仍在，实为 ${text()}`)
failOverview = false
console.log('10. 读取失败错误条按语言渲染 ✓')

// 11. 操作失败 toast 按当前语言渲染
await remount(<I18nProvider initial="en"><Users me={me} /></I18nProvider>)
await type(container.querySelector('.adm__search')!, 'amy')
await click(container.querySelector('tbody tr.adm__row')!)
failPatch = true
await click(button('Disable'))
await answer(true)
must(lastNotice().kind === 'err' && lastNotice().msg === 'You can’t disable yourself', `toast 英文，实为 ${lastNotice().msg}`)
failPatch = false
console.log('11. 操作失败 toast 按语言 ✓')

// 12. 任务页：error_msg 按语言，只有 error 原样
await remount(<I18nProvider initial="en"><JobsTab /></I18nProvider>)
must(text().includes('You’ve reached this month’s usage limit') && !text().includes('没有可用的模型'), '失败条英文 error_msg')
must(text().includes('schema 校验失败'), '只有 error 的原样显示')
console.log('12. 任务页失败原因 ✓')

// 13. 错误记录页签：列表无详情请求；展开才取；按编号查找；查不到；审计动作名
setCurrentLocale('zh')
calls.length = 0
await remount(<I18nProvider initial="zh"><ErrorsTab /></I18nProvider>)
must(calls.join('|') === 'GET /admin/errors', `只请求列表，实为 ${calls}`)
must(text().includes('K7Q2M9XD') && text().includes('bob') && text().includes('GET /novels')
     && text().includes('服务器出了点问题'), '表格列')
must(!text().includes('Traceback'), '列表不带详情')
const det = container.querySelector('details')! as unknown as HTMLDetailsElement
await act(async () => { det.open = true; det.dispatchEvent(new win.Event('toggle') as unknown as Event) })
await settle()
must(calls.includes('GET /admin/errors/K7Q2M9XD') && text().includes('Traceback: boom'), '展开才取详情')
calls.length = 0
await type(container.querySelector('.adm__search')!, 'k7q2-m9xd')
await act(async () => {
  container.querySelector('form')!.dispatchEvent(new win.Event('submit', { bubbles: true, cancelable: true }) as unknown as Event)
})
await settle()
must(calls.join('|') === 'GET /admin/errors/k7q2-m9xd', `查找请求，实为 ${calls}`)
must(container.querySelectorAll('table').length === 2 && text().includes('Traceback: boom'), '命中那一条带详情')
await type(container.querySelector('.adm__search')!, 'zzzz-zzzz')
await act(async () => {
  container.querySelector('form')!.dispatchEvent(new win.Event('submit', { bubbles: true, cancelable: true }) as unknown as Event)
})
await settle()
must(text().includes('没有这个参考编号：ZZZZZZZZ'), '查不到的提示')
await remount(<I18nProvider initial="en"><AuditTab /></I18nProvider>)
must(text().includes('View error details'), '审计动作名英文')
setCurrentLocale('zh')
await remount(<AuditTab />)
must(text().includes('查看错误详情'), '审计动作名中文')
console.log('13. 错误记录页签 ✓')

await remount(<AdminView me={me} onBack={() => {}} />)


await act(async () => { root.unmount() })
console.log('\nALL PASS')
