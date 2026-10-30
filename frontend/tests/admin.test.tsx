/** 管理后台的界面回归：概览、用户（排序/搜索/操作）、用量、任务、审计，以及入口。
 *  用桩后端代替 /admin 接口。
 *
 *  跑法：npm test
 */
import { Window } from 'happy-dom'

const win = new Window({ url: 'http://localhost:5173' })
const g = globalThis as Record<string, unknown>
for (const k of ['window', 'document', 'navigator', 'location', 'HTMLElement',
                 'Element', 'Node', 'Event', 'CustomEvent', 'getComputedStyle',
                 'localStorage', 'sessionStorage']) {
  Object.defineProperty(g, k, {
    value: (win as unknown as Record<string, unknown>)[k],
    writable: true, configurable: true,
  })
}
g.IS_REACT_ACT_ENVIRONMENT = true
const confirms: string[] = []
;(win as unknown as Record<string, unknown>).confirm = (m: string) => { confirms.push(m); return true }
g.confirm = (win as unknown as Record<string, unknown>).confirm

/* ---------- 桩后端 ---------- */
const calls: string[] = []
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
  const err = (status: number, detail: string) => ({
    ok: false, status, text: async () => JSON.stringify({ detail }), json: async () => ({ detail }) })
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
               cost_usd: 4.5, unpriced: 0 }] })
  }
  if (path === '/admin/jobs') return json({
    running: [{ id: 'j1', username: 'bob', status: 'running', work_title: '药', chapter: '第一章',
                chars: 4000, created_at: '2026-10-30T08:00:00+00:00', elapsed_sec: 75 }],
    failed: [{ id: 'v9', username: 'amy', novel_title: '孔乙己', chapter_title: '一',
               created_at: '2026-10-29T08:00:00+00:00', chars: 900, attempts: 3,
               error: 'schema 校验失败：缺少 episodes' }] })
  if (path.startsWith('/admin/audit')) return json({ audit: [
    { at: '2026-10-30T09:00:00+00:00', admin: 'root', action: 'disable', target: 'bob',
      before: { disabled: false }, after: { disabled: true } }] })
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
import type { ReactNode } from 'react'

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }
const container = win.document.createElement('div')
win.document.body.appendChild(container)
let root = createRoot(container as unknown as HTMLElement)
const settle = async (ms = 30) => {
  await act(async () => { await new Promise((r) => setTimeout(r, ms)) })
}
const has = (s: string) => container.innerHTML.includes(s)
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
must(confirms.some((c) => c.includes('停用')), '停用应先确认')
must(calls.some((c) => c === 'PATCH /admin/users/u-bob {"disabled":true}'), '应请求停用')
must(!!container.querySelector('tbody tr.adm__row .adm__bad'), '列表刷新为已停用（该行显示已停用）')
await type(container.querySelector('input[placeholder^="月上限"]')!, '')
await click(button('设上限'))
must(calls.some((c) => c === 'PATCH /admin/users/u-bob {"monthly_cap_usd":null}'), '空上限 = 不限')
await type(container.querySelector('input[type=password]')!, 'goodpass1')
await click(button('重置密码'))
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
must(text().includes(hint), '非数字应提示')
await type(container.querySelector('input[placeholder^="月上限"]')!, '-5')
await click(button('设上限'))
must(patches() === before, '负数上限不应请求')
must(text().includes(hint), '负数应提示')
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
must(calls.some((c) => c.startsWith('PUT /admin/pricing')) && text().includes('已保存'), '价格表保存')
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

// 5. 任务：运行中与失败两表，报错可展开
await remount(<JobsTab />)
must(text().includes('1:15') && text().includes('孔乙己') && text().includes('schema 校验失败'), '任务两表')
console.log('5. 任务：运行中（已运行 1:15）/ 近期失败报错 ✓')

// 6. 审计
await remount(<AuditTab />)
must(text().includes('停用') && text().includes('root') && text().includes('bob'), '审计列表')
console.log('6. 审计 ✓')

// @@NEXT@@

await act(async () => { root.unmount() })
console.log('\nALL PASS')
