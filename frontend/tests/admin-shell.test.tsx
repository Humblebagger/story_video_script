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

// ===== 追加点：后面的任务把新用例插在这一行上面 =====

await act(async () => { root.unmount() })
console.log('\nALL PASS')
