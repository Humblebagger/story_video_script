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
  if (path === '/admin/safety/count') return json({ blocked: 0 })
  if (path.startsWith('/admin/safety/blocks')) return json({ blocks: [] })
  if (path === '/admin/errors') return json({ errors: [1, 2, 20].map((n) => ({
    ref: `REF0000${n}`, at: ago(n), user_id: 'u-bob', username: 'bob', code: 'common.internal', params: {}, where: 'GET /novels' })) })
  if (path === '/admin/audit') return json({ audit: [
    { at: ago(1), admin: 'root', action: 'disable', target: 'amy', before: { disabled: false }, after: { disabled: true } }] })
  if (path === '/admin/pricing') return json({ currency: 'USD', updated_at: null,
    models: { 'claude-sonnet-5': { input: 2, output: 10, cache_read: 0.2, cache_write: 2.5 } } })
  throw new Error(`桩后端未实现的路径: ${method} ${path}`)
}

await import('../src/components/admin/i18n')   // 后台文案不在主包里，单独渲染某一页要先挂上
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
const openSelect = async (el: Element) => {
  await click(el)
  return [...win.document.querySelectorAll<HTMLElement>('.sel__content[data-state="open"] .sel__item')]
}
const pickSelect = async (el: Element, value: string) => {
  const item = (await openSelect(el)).find((x) => x.getAttribute('data-value') === value)
  if (!item) throw new Error(`✗ 下拉里找不到 ${value}`)
  await click(item)
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
  const lf = new Date(ago(1)), pad = (n: number) => String(n).padStart(2, '0')
  const lastAt = `${pad(lf.getMonth() + 1)}-${pad(lf.getDate())} ${pad(lf.getHours())}:${pad(lf.getMinutes())}`
  await remount(<Overview />)
  must(container.querySelector('h2')!.textContent === '运营概览', '页名')
  must(textOf('stat-users')!.includes('近 7 天新增 1') && hrefOf('stat-users') === '/admin/users', `用户卡，实为 ${textOf('stat-users')}`)
  must(textOf('stat-active')!.includes('占全部用户 67%'), `活跃卡，实为 ${textOf('stat-active')}`)
  must(textOf('stat-cost')!.includes('$18.50') && textOf('stat-cost')!.includes('近 7 天 $7.00')
       && !!byId('stat-cost')!.querySelector('[data-testid="sparkline"]') && hrefOf('stat-cost') === '/admin/usage',
       `金额卡，实为 ${textOf('stat-cost')}`)
  must(textOf('stat-failed')!.includes(`最近一次 ${lastAt}`) && textOf('stat-failed')!.includes('去处理')
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

// 6. 导航组件：分组、当前页、计数徽标、收起形态、窄屏下拉
{
  const { AdminNavContext } = await import('../src/components/admin/navContext')
  const { AdminSidebar, AdminTopNav } = await import('../src/components/admin/AdminNav')
  const { zhAdmin } = await import('../src/components/admin/messages.zh')
  const { enAdmin } = await import('../src/components/admin/messages.en')
  const log: string[] = []
  const nav = (to: string) => { log.push(to) }
  const counts = { jobs: 3, errors: 120, usage: 1 }
  const side = (collapsed: boolean) => (
    <AdminNavContext.Provider value={nav}>
      <AdminSidebar page="jobs" counts={counts} onBack={() => { log.push('back') }} tools={<i>工具</i>}
                    collapsed={collapsed} onToggle={() => { log.push('toggle') }} />
    </AdminNavContext.Provider>)
  await remount(side(false))
  must(container.querySelector('h1')!.textContent === zhAdmin.title, '左上角标题')
  must([...container.querySelectorAll('.adm-nav__title')].map((e) => e.textContent).join() === '总览,用户与用量,运行', '三个分组')
  const links = () => [...container.querySelectorAll('.adm-nav__item')]
  must(links().map((a) => a.getAttribute('href')).join() === '/admin,/admin/users,/admin/usage,/admin/jobs,/admin/errors,/admin/safety,/admin/audit',
       `七个导航项的地址，实为 ${links().map((a) => a.getAttribute('href'))}`)
  must(links().map((a) => a.querySelector('span')!.textContent).join() === '运营概览,用户,用量与花费,任务,错误,内容拦截,审计', '导航项名字')
  must(links().filter((a) => a.getAttribute('aria-current') === 'page').length === 1
       && byId('admin-nav-jobs')!.getAttribute('aria-current') === 'page' && byId('admin-nav-jobs')!.className.includes('is-on'), '当前页高亮')
  must(textOf('admin-count-jobs') === '3' && textOf('admin-count-errors') === '99+' && textOf('admin-count-usage') === '1'
       && !byId('admin-count-users') && !byId('admin-count-overview') && !byId('admin-count-audit'), '计数徽标：有数才显示，超过 99 写 99+')
  must(byId('admin-count-jobs')!.getAttribute('title') === '近 7 天失败 3 个'
       && byId('admin-count-usage')!.className.includes('is-warn'), '计数的说明与提醒色')
  await click(byId('admin-nav-users')!)
  await click(byId('admin-back')!)
  await click(byId('admin-nav-toggle')!)
  must(log.join() === '/admin/users,back,toggle', `点导航项、返回产品、收起，实为 ${log}`)
  must(byId('admin-back')!.textContent === zhAdmin.back && text().includes('工具'), '返回产品链接与工具区')
  await remount(side(true))
  must(!container.querySelector('h1') && container.querySelectorAll('.adm-nav__title').length === 0, '收起：不显示标题与分组名')
  must(links().length === 7 && links().every((a) => !a.querySelector('span:not(.adm-nav__badge)')), '收起：导航项只剩图标')
  must(byId('admin-nav-errors')!.getAttribute('aria-label') === '错误' && byId('admin-back')!.getAttribute('aria-label') === zhAdmin.back
       && byId('admin-nav-toggle')!.getAttribute('aria-label') === '展开导航', '收起：图标带名字')
  must(textOf('admin-count-jobs') === '3', '收起：计数还在')
  // 窄屏：顶部一条 + 下拉
  log.length = 0
  await remount(
    <AdminTopNav page="jobs" counts={counts} onBack={() => { log.push('back') }} tools={<i>工具</i>}
                 onPage={(id) => { log.push(`page ${id}`) }} />)
  const select = byId('admin-nav-select')!
  must(select.textContent?.includes('任务（3）'), '下拉选中当前页')
  const items = await openSelect(select)
  must([...win.document.querySelectorAll('.sel__content[data-state="open"] .sel__group')].map((o) => o.textContent).join() === '总览,用户与用量,运行', '下拉按分组')
  must(items.map((o) => o.textContent).join() === '运营概览,用户,用量与花费（1）,任务（3）,错误（99+）,内容拦截,审计',
       `下拉选项带计数，实为 ${items.map((o) => o.textContent)}`)
  await click(items.find((o) => o.getAttribute('data-value') === 'audit')!)
  await click(byId('admin-back')!)
  must(log.join() === 'page audit,back', `下拉换页与返回，实为 ${log}`)
  await remount(<I18nProvider initial="en">{side(false)}</I18nProvider>)
  must(links().map((a) => a.querySelector('span')!.textContent).join() === 'Dashboard,Users,Usage & cost,Jobs,Errors,Blocked content,Audit'
       && byId('admin-back')!.textContent === enAdmin.back, '英文导航')
  await act(async () => { root.unmount() })
  root = createRoot(container as unknown as HTMLElement)
  setCurrentLocale('zh')
  console.log('6. 导航组件：分组 / 当前页 / 计数 / 收起 / 窄屏下拉 / 英文 ✓')
}

// 7. 外框：每个地址打开对应的页；导航与卡片链接改地址；筛选写进地址；计数、收起、窄屏
{
  const { useState } = await import('react')
  const { AdminView } = await import('../src/components/admin/AdminView')
  const { parseLocation } = await import('../src/paths')
  const me = { id: 'u-root', username: 'root', created_at: '', role: 'admin' as const }
  const log: string[] = []
  let here = ''
  let back = 0
  /** 代替 App：地址放在状态里，用 parseLocation 解析后交给外框 */
  function Host({ start }: { start: string }) {
    const [url, setUrl] = useState(start)
    here = url
    const [pathname, query] = url.split('?')
    const { loc } = parseLocation(pathname, query ? `?${query}` : '')
    if (loc.kind !== 'admin') return <p>不是后台地址</p>
    return (
      <AdminView me={me} page={loc.page} jobState={loc.state} usageGroup={loc.group} usageDays={loc.days}
                 onNav={(to, replace) => { log.push(`${replace ? 'replace' : 'push'} ${to}`); setUrl(to) }}
                 onBack={() => { back++ }} />
    )
  }
  const open = async (url: string) => { log.length = 0; await remount(<Host start={url} />) }
  const h2 = () => container.querySelector('.adm__pagehead h2')?.textContent
  const current = () => container.querySelector('.adm-nav__item[aria-current="page"]')?.getAttribute('data-testid')

  for (const [url, name, id] of [['/admin', '运营概览', 'overview'], ['/admin/users', '用户', 'users'],
    ['/admin/usage', '用量与花费', 'usage'], ['/admin/jobs', '任务', 'jobs'], ['/admin/errors', '错误', 'errors'], ['/admin/safety', '内容拦截', 'safety'],
    ['/admin/audit', '审计', 'audit']]) {
    await open(url)
    must(h2() === name && current() === `admin-nav-${id}`, `${url} 应打开「${name}」，实为 ${h2()} / ${current()}`)
    must(container.querySelectorAll('.adm__pagehead').length === 1 && !!byId('admin-sidebar'), `${url}：一个标题行、左侧导航`)
  }
  console.log('7a. 七个地址各自打开对应的页 ✓')

  await open('/admin')
  must(textOf('admin-count-jobs') === '3' && textOf('admin-count-errors') === '2' && textOf('admin-count-usage') === '1'
       && !byId('admin-count-users'), `导航计数：失败 3、近 7 天错误 2、未定价 1，实为 ${textOf('admin-count-jobs')}/${textOf('admin-count-errors')}/${textOf('admin-count-usage')}`)
  must(calls.filter((c) => c === 'GET /admin/overview').length >= 1 && text().includes('30 天金额'), '概览页用外框那份概览数据')
  await click(byId('stat-failed')!.querySelector('a')!)
  must(here === '/admin/jobs?state=failed' && log.join() === 'push /admin/jobs?state=failed', `「去处理」跳到失败任务，实为 ${here}`)
  must(h2() === '任务' && !byId('jobs-running') && !!byId('jobs-failed') && button('失败').getAttribute('aria-pressed') === 'true',
       '带筛选打开任务页：只显示失败')
  await click(button('全部'))
  must(here === '/admin/jobs' && log[log.length - 1] === 'replace /admin/jobs' && !!byId('jobs-running'), `改筛选是 replace，实为 ${log}`)
  await click(button('运行中'))
  must(here === '/admin/jobs?state=running' && !byId('jobs-failed'), '筛选写进地址')
  await click(byId('admin-nav-usage')!)
  must(here === '/admin/usage' && log[log.length - 1] === 'push /admin/usage' && h2() === '用量与花费', '点导航项是 push')
  await click(button('按模型'))
  await click(button('7 天'))
  must(here === '/admin/usage?group=model&days=7' && log[log.length - 1] === 'replace /admin/usage?group=model&days=7'
       && calls.includes('GET /admin/usage?group=model&days=7'), `用量的分组与天数写进地址，实为 ${here}`)
  await click(byId('admin-nav-overview')!)
  await click(byId('unpriced-alert')!)
  must(here === '/admin/usage?group=model' && button('按模型').getAttribute('aria-pressed') === 'true', `未定价提醒跳到按模型的用量页，实为 ${here}`)
  await click(byId('admin-nav-overview')!)
  await click(byId('stat-running')!.querySelector('a')!)
  must(here === '/admin/jobs?state=running' && !!byId('jobs-running') && !byId('jobs-failed'), '「查看任务」跳到运行中')
  await click(byId('admin-back')!)
  must(back === 1, '返回产品回调')
  console.log('7b. 计数 / 卡片链接带筛选 / 筛选写进地址 / 返回 ✓')

  // 没有待处理的数：不显示徽标
  ov.failed_7d = 0; ov.unpriced_models = []
  await open('/admin/audit')
  must(!byId('admin-count-jobs') && !byId('admin-count-usage') && textOf('admin-count-errors') === '2', '为 0 的计数不显示')
  ov.failed_7d = 3; ov.unpriced_models = ['mystery']
  // 概览接口失败：导航照常，只是没有来自它的计数；概览页显示错误条
  failing.add('/admin/overview')
  await open('/admin')
  must(!byId('admin-count-jobs') && !!byId('admin-nav-jobs') && text().includes('服务器出了点问题'), '概览取不到：没有任务计数，页内是错误条')
  failing.clear()

  // 收起与展开；记在 localStorage
  await open('/admin/users')
  const shell = () => byId('admin-shell')!.className
  must(!shell().includes('is-collapsed') && container.querySelector('h1')?.textContent === '运营后台', '默认展开')
  await click(byId('admin-nav-toggle')!)
  must(shell().includes('is-collapsed') && !container.querySelector('h1') && textOf('admin-count-jobs') === '3'
       && win.localStorage.getItem('inkreel.admin.navCollapsed') === '1', '收起：窄条、计数还在、记住')
  await open('/admin/users')
  must(shell().includes('is-collapsed'), '重新打开仍是收起')
  await click(byId('admin-nav-toggle')!)
  must(!shell().includes('is-collapsed') && win.localStorage.getItem('inkreel.admin.navCollapsed') === '0', '再点展开')

  // 窄屏：顶部下拉
  const wide = win.matchMedia
  ;(win as unknown as { matchMedia: unknown }).matchMedia = () => ({ matches: true, addEventListener() {}, removeEventListener() {} })
  g.matchMedia = win.matchMedia
  await open('/admin/jobs?state=failed')
  must(!byId('admin-sidebar') && !!byId('admin-topnav') && shell().includes('is-narrow') && h2() === '任务', '窄屏：没有侧栏，顶部一条')
  const select = byId('admin-nav-select')!
  must(select.textContent?.includes('任务'), '窄屏下拉选中当前页')
  await pickSelect(select, 'errors')
  must(here === '/admin/errors' && h2() === '错误', `窄屏下拉换页，实为 ${here}`)
  ;(win as unknown as { matchMedia: unknown }).matchMedia = wide
  g.matchMedia = wide
  console.log('7c. 计数为 0 不显示 / 收起 / 窄屏下拉 ✓')

  // 英文
  log.length = 0
  await remount(<I18nProvider initial="en"><Host start="/admin/jobs?state=failed" /></I18nProvider>)
  must(container.querySelector('h1')?.textContent === 'Admin console' && h2() === 'Jobs' && byId('admin-back')!.textContent === 'Back to app'
       && button('Failed').getAttribute('aria-pressed') === 'true'
       && byId('admin-count-jobs')!.getAttribute('title') === '3 failed in the last 7 days', '英文外框')
  await act(async () => { root.unmount() })
  root = createRoot(container as unknown as HTMLElement)
  setCurrentLocale('zh')
  console.log('7d. 英文外框 ✓')
}

// 8. 文案是后挂的：键的结构中英文一致；外框设浏览器标题
{
  const { zhAdmin } = await import('../src/components/admin/messages.zh')
  const { enAdmin } = await import('../src/components/admin/messages.en')
  const { zh } = await import('../src/i18n/zh')
  const { translate } = await import('../src/i18n/core')
  const { AdminView } = await import('../src/components/admin/AdminView')
  const keys = (o: object, p = ''): string[] => Object.entries(o).flatMap(([k, v]) =>
    (typeof v === 'string' ? [`${p}${k}`] : keys(v as object, `${p}${k}.`)))
  must(keys(zhAdmin).sort().join() === keys(enAdmin).sort().join() && keys(zhAdmin).length > 100, '后台文案中英文的键一一对应')
  must(!('admin' in zh), '主包的语言包里没有后台文案')
  must(translate('zh', 'admin.title') === '运营后台' && translate('en', 'admin.nav.pages.usage') === 'Usage & cost', '挂上后按键取得到')
  const me = { id: 'u-root', username: 'root', created_at: '', role: 'admin' as const }
  await remount(<AdminView me={me} page="audit" jobState={null} usageGroup="user" usageDays={30} onNav={() => {}} onBack={() => {}} />)
  must(win.document.title === '审计 · 运营后台 — Inkreel', `外框设浏览器标题，实为 ${win.document.title}`)
  console.log('8. 后台文案后挂 / 外框设标题 ✓')
}

// ===== 追加点：后面的任务把新用例插在这一行上面 =====

await act(async () => { root.unmount() })
console.log('\nALL PASS')
