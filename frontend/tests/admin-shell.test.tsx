/** 运营后台改版的界面回归：公共小组件、概览卡片、各页标题行与筛选、导航外框（地址、计数、收起、窄屏、中英文）。
 *  用桩后端代替 /admin 接口；时间都相对当前时刻生成，「近 7 天」的统计才有数。
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
const NOW = Date.now()
const ago = (days: number) => new Date(NOW - days * 86400000).toISOString()
const calls: string[] = []
/** 让某个接口失败（值是路径前缀），用来验证「拿不到就省略」 */
const failing = new Set<string>()
/** 概览接口的可调字段 */
const ov = { failed_7d: 3, unpriced_models: ['mystery'] as string[] }
// 近 30 天每日金额：最近 7 天每天 1 美元，更早每天 0.5 美元（合计 18.5）
const daily = Array.from({ length: 30 }, (_, i) => ({ day: ago(29 - i).slice(0, 10), cost_usd: i >= 23 ? 1 : 0.5 }))
const userRow = (id: string, extra: Record<string, unknown>) => ({
  id: `u-${id}`, username: id, role: 'user', disabled: false, created_at: ago(40), last_seen_at: ago(1),
  has_password: true, monthly_cap_usd: null, novels: 1, chapters: 1, versions: 1, month_cost_usd: 1, ...extra })
const users = [
  userRow('root', { role: 'admin' }),
  userRow('bob', { created_at: ago(2) }),
  userRow('amy', { created_at: ago(10), disabled: true, last_seen_at: null }),
]
const usageRow = (label: string, extra: Record<string, unknown>) => ({
  key: label, label, calls: 1, input: 10, output: 20, cache_read: 0, cache_write: 0, chars: 100,
  cost_usd: 0, unpriced: 0, records: 1, ...extra })
g.fetch = async (url: string, init?: { method?: string; body?: string }) => {
  const path = String(url).replace(/^\/api/, '')
  const method = init?.method ?? 'GET'
  calls.push(`${method} ${path}`)
  const json = (data: unknown) => ({ ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(data)),
                                     text: async () => JSON.stringify(data) })
  const err = (status: number, detail: unknown) => ({
    ok: false, status, text: async () => JSON.stringify({ detail }), json: async () => ({ detail }) })
  if ([...failing].some((p) => path.startsWith(p))) {
    return err(500, { code: 'common.internal', params: {}, message: '服务器出了点问题，请稍后再试' })
  }
  if (path === '/admin/overview') return json({ users: 3, active_7d: 2, tokens_30d: 1234567, cost_30d: 18.5,
    running: 2, failed_7d: ov.failed_7d, daily, unpriced_models: ov.unpriced_models })
  if (path === '/admin/users') return json({ users })
  if (path === '/admin/jobs') return json({
    running: [{ id: 'j1', user_id: 'u-bob', username: 'bob', status: 'running', work_title: '药', chapter: '第一章',
                chars: 4000, created_at: ago(0.01), elapsed_sec: 75 },
              { id: 'j2', user_id: 'u-bob', username: 'bob', status: 'queued', work_title: '药', chapter: '第二章',
                chars: 3000, created_at: ago(0.01), elapsed_sec: 5 }],
    failed: [1, 2, 3].map((n) => ({ id: `v${n}`, user_id: 'u-amy', username: 'amy', novel_title: '孔乙己',
      chapter_title: `第 ${n} 回`, created_at: ago(n), chars: 900, attempts: 3, error: `失败原因 ${n}` })) })
  if (path.startsWith('/admin/usage')) {
    const q = new URL('http://x' + path).searchParams
    const group = q.get('group')
    return json({ group, days: Number(q.get('days')), per_k_chars: { n: 2, mean: 0.75, p90: 3 }, unpriced_models: ov.unpriced_models,
      rows: group === 'model' ? [
        usageRow('claude-sonnet-5', { calls: 30, cost_usd: 13.5 }),
        usageRow('other-model', { calls: 10, cost_usd: 4.5 }),
        usageRow('mystery', { calls: 2, unpriced: 2, records: 2 }),
      ] : [usageRow(group === 'user' ? 'bob' : ago(0).slice(0, 10), { calls: 42, cost_usd: 18 })] })
  }
  if (path === '/admin/errors') return json({ errors: [1, 2, 20].map((n) => ({
    ref: `REF0000${n}`, at: ago(n), user_id: 'u-bob', username: 'bob', code: 'common.internal', params: {}, where: 'GET /novels' })) })
  if (path === '/admin/audit') return json({ audit: [
    { at: ago(1), admin: 'root', action: 'disable', target: 'amy', before: { disabled: false }, after: { disabled: true } }] })
  if (path === '/admin/pricing') return json({ currency: 'USD', updated_at: null,
    models: { 'claude-sonnet-5': { input: 2, output: 10, cache_read: 0.2, cache_write: 2.5 } } })
  throw new Error(`桩后端未实现的路径: ${method} ${path}`)
}

const { act } = await import('react')
const { createRoot } = await import('react-dom/client')
import type { ReactNode } from 'react'

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }
const container = win.document.createElement('div')
win.document.body.appendChild(container)
let root = createRoot(container as unknown as HTMLElement)
const settle = async (ms = 30) => {
  await act(async () => { await new Promise((r) => setTimeout(r, ms)) })
}
const text = () => container.textContent ?? ''
const byId = (id: string) => container.querySelector(`[data-testid="${id}"]`)
/** 某个 data-testid 节点的文字；不存在返回 null */
const textOf = (id: string) => byId(id)?.textContent ?? null
const hrefOf = (id: string) => byId(id)?.querySelector('a')?.getAttribute('href') ?? null
const button = (label: string) => {
  const b = [...container.querySelectorAll('button')].find((x) => (x.textContent ?? '').trim() === label)
  if (!b) throw new Error(`✗ 找不到按钮「${label}」`)
  return b as unknown as HTMLButtonElement
}
// cancelable：链接的点击要能被 preventDefault 拦下，否则 happy-dom 会真的去跳转
const click = async (el: unknown) => {
  await act(async () => {
    (el as EventTarget).dispatchEvent(new win.MouseEvent('click', { bubbles: true, cancelable: true }) as unknown as Event)
  })
  await settle()
}
const remount = async (node: ReactNode) => {
  await act(async () => { root.unmount() })
  root = createRoot(container as unknown as HTMLElement)
  await act(async () => { root.render(node) })
  await settle()
}

// 1. 公共小组件：标题行、数字卡片、分布卡片、空状态、后台内部链接
{
  const { AdminNavContext } = await import('../src/components/admin/navContext')
  const { PageHead, RefreshButton } = await import('../src/components/admin/PageHead')
  const { StatCard, DistCard } = await import('../src/components/admin/StatCard')
  const { Empty } = await import('../src/components/admin/LoadState')
  const log: string[] = []
  await remount(
    <AdminNavContext.Provider value={(to, replace) => { log.push(`${replace ? 'replace' : 'push'} ${to}`) }}>
      <PageHead title="页名" hint="一行说明">
        <RefreshButton label="刷新" onClick={() => { log.push('refresh') }} />
      </PageHead>
      <StatCard id="a" label="失败" value="3" sub="最近一次 10-01" bad to="/admin/jobs?state=failed" action="去处理" />
      <StatCard id="b" label="用户" value="5" />
      <DistCard id="d" title="分布" empty="暂无数据" note="备注" to="/admin/users" action="查看"
                rows={[{ label: '正常', value: '2', share: 2 / 3 }, { label: '已停用', value: '1', share: 1 / 3 }]} />
      <DistCard id="e" title="空分布" empty="暂无数据" rows={[]} />
      <Empty title="还没有记录" hint="以后会出现在这里" />
    </AdminNavContext.Provider>)
  must(container.querySelector('h2')!.textContent === '页名' && text().includes('一行说明'), '标题行：页名与说明')
  await click(button('刷新'))
  must(log.join() === 'refresh', '标题行右侧的刷新按钮')
  const a = byId('stat-a')!
  must(['失败', '3', '最近一次 10-01', '去处理'].every((s) => a.textContent!.includes(s)), `数字卡片内容，实为 ${a.textContent}`)
  must(a.querySelector('b')!.className.includes('text-destructive'), 'bad 的数字标红')
  must(hrefOf('stat-a') === '/admin/jobs?state=failed', '行动链接是真链接')
  await click(a.querySelector('a')!)
  must(log[log.length - 1] === 'push /admin/jobs?state=failed', `点链接走后台内部跳转，实为 ${log}`)
  const b = byId('stat-b')!
  must(!b.querySelector('a') && !b.querySelector('.adm__sub'), '没给副标题和链接就不渲染')
  const fills = [...byId('dist-d')!.querySelectorAll('.adm__dist-fill')].map((el) => el.getAttribute('style') ?? '')
  must(fills.length === 2 && fills[0].includes('67%') && fills[1].includes('33%'), `占比条宽度，实为 ${fills}`)
  must(textOf('dist-d')!.includes('备注') && hrefOf('dist-d') === '/admin/users', '分布卡片的备注与链接')
  must(textOf('dist-e')!.includes('暂无数据'), '没有行时显示空文字')
  must((container.querySelector('.adm__emptycard [data-testid="empty-state"]')?.textContent ?? '').includes('还没有记录'), '空状态带卡片底')
  console.log('1. 公共小组件 ✓')
}

// 英文用例要用的语言工具（下面各组共用）
const { I18nProvider } = await import('../src/i18n')
const { setCurrentLocale } = await import('../src/i18n/core')

// 2. 运营概览：卡片的副标题与行动链接、近 14 天趋势、分布卡片、未定价提醒可点
{
  const { Overview } = await import('../src/components/admin/Overview')
  const { when } = await import('../src/components/admin/format')
  await remount(<Overview />)
  must(container.querySelector('h2')!.textContent === '运营概览', '页名')
  must(textOf('stat-users')!.includes('近 7 天新增 1') && hrefOf('stat-users') === '/admin/users', `用户卡，实为 ${textOf('stat-users')}`)
  must(textOf('stat-active')!.includes('占全部用户 67%'), `活跃卡，实为 ${textOf('stat-active')}`)
  must(textOf('stat-cost')!.includes('$18.50') && textOf('stat-cost')!.includes('近 7 天 $7.00')
       && !!byId('stat-cost')!.querySelector('[data-testid="sparkline"]') && hrefOf('stat-cost') === '/admin/usage',
       `金额卡，实为 ${textOf('stat-cost')}`)
  must(textOf('stat-failed')!.includes(`最近一次 ${when(ago(1))}`) && textOf('stat-failed')!.includes('去处理')
       && hrefOf('stat-failed') === '/admin/jobs?state=failed', `失败卡，实为 ${textOf('stat-failed')} ${hrefOf('stat-failed')}`)
  must(byId('stat-failed')!.querySelector('b')!.className.includes('text-destructive'), '有失败时数字标红')
  must(textOf('stat-running')!.includes('其中排队 1') && hrefOf('stat-running') === '/admin/jobs?state=running', `运行中卡，实为 ${textOf('stat-running')}`)
  must(textOf('stat-tokens')!.includes('1,234,567') && textOf('stat-tokens')!.includes('30 天调用 42 次'), `token 卡，实为 ${textOf('stat-tokens')}`)
  must(byId('trend')!.querySelectorAll('.adm__chart circle').length === 14 && textOf('trend')!.includes('近 14 天每日金额'), '趋势图 14 个点')
  must(['排队中1', '运行中1', '近 7 天失败3'].every((s) => textOf('dist-jobs')!.includes(s)), `任务状态分布，实为 ${textOf('dist-jobs')}`)
  must(['正常2', '已停用1', '其中管理员 1 人'].every((s) => textOf('dist-users')!.includes(s)), `用户状态分布，实为 ${textOf('dist-users')}`)
  must(['claude-sonnet-5$13.50', 'other-model$4.50', 'mystery未定价'].every((s) => textOf('dist-models')!.includes(s))
       && hrefOf('dist-models') === '/admin/usage?group=model', `按模型分布，实为 ${textOf('dist-models')}`)
  const alert = byId('unpriced-alert')!
  must(alert.tagName === 'A' && alert.getAttribute('href') === '/admin/usage?group=model' && alert.textContent!.includes('mystery'),
       '未定价提醒是指向用量页的链接')
  console.log('2. 运营概览：副标题 / 行动链接 / 趋势 / 分布 / 未定价提醒 ✓')
}

// 2b. 拿不到就省略：某份数据取不到时，只少掉依赖它的副标题与分布卡片，其余照常
{
  const { Overview } = await import('../src/components/admin/Overview')
  failing.add('/admin/users')
  await remount(<Overview />)
  must(!text().includes('近 7 天新增') && !byId('dist-users') && !!byId('dist-jobs') && !!byId('dist-models')
       && textOf('stat-users')!.includes('3'), '用户列表取不到：没有新增副标题与用户分布')
  failing.clear(); failing.add('/admin/jobs')
  await remount(<Overview />)
  must(!text().includes('最近一次') && !text().includes('其中排队') && !byId('dist-jobs') && !!byId('dist-users'),
       '任务取不到：没有最近一次、排队数与任务分布')
  failing.clear(); failing.add('/admin/usage')
  await remount(<Overview />)
  must(!text().includes('30 天调用') && !byId('dist-models') && !!byId('dist-users'), '按模型用量取不到：没有调用次数与模型分布')
  failing.clear(); failing.add('/admin/users'); failing.add('/admin/jobs'); failing.add('/admin/usage')
  await remount(<Overview />)
  must(!container.querySelector('[data-testid^="dist-"]') && container.querySelectorAll('[data-testid^="stat-"]').length === 6,
       '三份都取不到：没有分布区，六张数字卡仍在')
  failing.clear()
  ov.failed_7d = 0; ov.unpriced_models = []
  await remount(<Overview />)
  must(!byId('unpriced-alert') && !byId('stat-failed')!.querySelector('b')!.className.includes('text-destructive'),
       '没有未定价模型就没有提醒条；没有失败不标红')
  ov.failed_7d = 3; ov.unpriced_models = ['mystery']
  console.log('2b. 拿不到就省略 ✓')
}

// 2c. 概览刷新按钮把四份数据都重新取一遍；英文文案
{
  const { Overview } = await import('../src/components/admin/Overview')
  await remount(<Overview />)
  calls.length = 0
  await click(button('刷新'))
  must(['GET /admin/overview', 'GET /admin/users', 'GET /admin/jobs', 'GET /admin/usage?group=model&days=30']
    .every((c) => calls.includes(c)), `刷新应重新请求四份数据，实为 ${calls}`)
  await remount(<I18nProvider initial="en"><Overview /></I18nProvider>)
  must(container.querySelector('h2')!.textContent === 'Dashboard' && textOf('stat-users')!.includes('1 new in the last 7 days')
       && textOf('stat-failed')!.includes('Review') && textOf('dist-users')!.includes('1 of them are admins'), `英文概览，实为 ${textOf('stat-users')}`)
  await act(async () => { root.unmount() })
  root = createRoot(container as unknown as HTMLElement)
  setCurrentLocale('zh')
  console.log('2c. 概览刷新 / 英文 ✓')
}

// 3. 用户、错误、审计三页：统一的标题行（页名 + 刷新）与空状态
{
  const { Users } = await import('../src/components/admin/Users')
  const { ErrorsTab } = await import('../src/components/admin/ErrorsTab')
  const { AuditTab } = await import('../src/components/admin/AuditTab')
  const me = { id: 'u-root', username: 'root', created_at: '', role: 'admin' as const }
  const pages: [string, string, () => ReactNode][] = [
    ['用户', 'GET /admin/users', () => <Users me={me} />],
    ['错误', 'GET /admin/errors', () => <ErrorsTab />],
    ['审计', 'GET /admin/audit', () => <AuditTab />],
  ]
  for (const [name, req, page] of pages) {
    await remount(page())
    must(container.querySelector('.adm__pagehead h2')?.textContent === name, `「${name}」页的标题行`)
    const n = calls.filter((c) => c === req).length
    await click(button('刷新'))
    must(calls.filter((c) => c === req).length === n + 1, `「${name}」页的刷新应重新请求`)
    // 读取失败：标题行还在，下面是错误条
    failing.add(req.slice(4))
    await remount(page())
    must(container.querySelector('.adm__pagehead h2')?.textContent === name && text().includes('服务器出了点问题')
         && !!container.querySelector('.adm__errbar'), `「${name}」页读取失败时标题行仍在`)
    failing.clear()
  }
  console.log('3. 用户 / 错误 / 审计：标题行、刷新、读取失败 ✓')
}

// 4. 任务页：筛选（全部 / 运行中 / 失败）；可由外面控制，也可自己记
{
  const { JobsTab } = await import('../src/components/admin/JobsTab')
  await remount(<JobsTab />)
  must(container.querySelector('.adm__pagehead h2')?.textContent === '任务', '任务页标题行')
  must(!!byId('jobs-running') && !!byId('jobs-failed') && button('全部').getAttribute('aria-pressed') === 'true', '默认两张表都在')
  await click(button('失败'))
  must(!byId('jobs-running') && !!byId('jobs-failed') && !text().includes('1:15'), '自己记筛选：只看失败')
  await click(button('运行中'))
  must(!!byId('jobs-running') && !byId('jobs-failed') && text().includes('1:15'), '自己记筛选：只看运行中')
  // 受控：state 由外面给，点筛选只回调，不自己变
  const asked: (string | null)[] = []
  await remount(<JobsTab state="failed" onState={(s) => { asked.push(s) }} />)
  must(!byId('jobs-running') && !!byId('jobs-failed') && button('失败').getAttribute('aria-pressed') === 'true', '受控：state=failed 只显示失败')
  await click(button('运行中'))
  await click(button('全部'))
  must(asked.join() === 'running,' && asked[1] === null, `受控：点筛选回调 running 与 null，实为 ${JSON.stringify(asked)}`)
  must(!byId('jobs-running'), '受控：外面不改 state，显示不变')
  await remount(<JobsTab state={null} onState={() => {}} />)
  must(!!byId('jobs-running') && !!byId('jobs-failed'), '受控：state=null 是全部')
  console.log('4. 任务页筛选 ✓')
}

// 5. 用量页：分组与天数可由外面控制
{
  const { UsageTab } = await import('../src/components/admin/UsageTab')
  const asked: string[] = []
  calls.length = 0
  await remount(<UsageTab group="model" days={7} onQuery={(group, days) => { asked.push(`${group}/${days}`) }} />)
  must(container.querySelector('.adm__pagehead h2')?.textContent === '用量与花费', '用量页标题行')
  must(calls.includes('GET /admin/usage?group=model&days=7') && !calls.includes('GET /admin/usage?group=user&days=30'),
       `受控：按传入的分组与天数请求，实为 ${calls}`)
  must(button('按模型').getAttribute('aria-pressed') === 'true' && button('7 天').getAttribute('aria-pressed') === 'true', '受控：选中项跟着传入值')
  await click(button('按天'))
  await click(button('90 天'))
  must(asked.join() === 'day/7,model/90', `受控：改分组、改天数各回调一次，实为 ${asked}`)
  must(button('按模型').getAttribute('aria-pressed') === 'true', '受控：外面不改就不变')
  console.log('5. 用量页受控的分组与天数 ✓')
}

// ===== 追加点：后面的任务把新用例插在这一行上面 =====

await act(async () => { root.unmount() })
console.log('\nALL PASS')
