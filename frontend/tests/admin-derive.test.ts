/** 后台纯计算：近 7 天判断、用户与任务统计、按模型占比、导航计数（设计 docs/specs/2026-11-21-admin-console-redesign-design.md §5、§6）。 */
import { badgeText, jobStats, modelShare, NAV_GROUPS, navCounts, sumLast, userStats, within } from '../src/components/admin/derive'
import { monthDayTime } from '../src/components/admin/format'
import { ADMIN_PAGES } from '../src/paths'
import type { AdminJobs, AdminOverview, AdminUserRow, ErrorRefRow, UsageGroupRow } from '../src/types'

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }
const eq = (a: unknown, b: unknown, msg: string) =>
  must(JSON.stringify(a) === JSON.stringify(b), `${msg}\n  得到 ${JSON.stringify(a)}\n  期望 ${JSON.stringify(b)}`)

const NOW = Date.parse('2026-11-21T12:00:00+00:00')
const ago = (days: number) => new Date(NOW - days * 86400000).toISOString()

// 1. 近 N 天
must(within(ago(6.9), 7, NOW) && within(ago(7), 7, NOW) && !within(ago(7.1), 7, NOW), '7 天以内含边界')
must(!within(null, 7, NOW) && !within(undefined, 7, NOW) && !within('', 7, NOW) && !within('不是时间', 7, NOW), '缺失或解析不了算不在')
must(within('2026-11-20T08:00:00+00:00', 7, NOW), '带时区的 ISO 时间')
console.log('1. 近 N 天 ✓')

// 2. 用户统计
const user = (extra: Partial<AdminUserRow>): AdminUserRow => ({
  id: 'u', username: 'u', role: 'user', disabled: false, created_at: ago(40), last_seen_at: null, has_password: true,
  monthly_cap_usd: null, novels: 0, chapters: 0, versions: 0, month_cost_usd: 0, ...extra })
eq(userStats([user({ role: 'admin' }), user({ created_at: ago(2) }), user({ created_at: ago(3), disabled: true }),
              user({ created_at: null })], NOW),
   { total: 4, newIn7d: 2, normal: 3, disabled: 1, admins: 1 }, '用户统计')
eq(userStats([], NOW), { total: 0, newIn7d: 0, normal: 0, disabled: 0, admins: 0 }, '没有用户')
console.log('2. 用户统计 ✓')

// 3. 任务统计
const running = (status: string) => ({ id: 'j', user_id: 'u', username: null, status, work_title: null, chapter: null,
  chars: null, created_at: null, elapsed_sec: null })
const failed = (at: string) => ({ id: 'v', user_id: 'u', username: null, novel_title: null, chapter_title: null,
  created_at: at, chars: 0, attempts: 1, error: '' })
const jobs: AdminJobs = { running: [running('running'), running('queued'), running('queued')], failed: [failed(ago(1)), failed(ago(3))] }
eq(jobStats(jobs), { queued: 2, running: 1, failed: 2, lastFailedAt: ago(1) }, '任务统计：排队 / 运行中 / 失败 / 最近一次')
eq(jobStats({ running: [], failed: [] }), { queued: 0, running: 0, failed: 0, lastFailedAt: null }, '没有任务')
console.log('3. 任务统计 ✓')

// 4. 最近 n 天金额
const daily = [1, 2, 3, 4].map((v, i) => ({ day: `2026-11-${18 + i}`, cost_usd: v }))
must(sumLast(daily, 2) === 7 && sumLast(daily, 10) === 10 && sumLast([], 7) === 0, '最近 n 天合计')
console.log('4. 最近 n 天金额 ✓')

// 5. 按模型占比
const row = (label: string, extra: Partial<UsageGroupRow>): UsageGroupRow => ({
  key: label, label, calls: 1, input: 0, output: 0, cache_read: 0, cache_write: 0, chars: 0,
  cost_usd: 0, unpriced: 0, records: 1, ...extra })
const share = modelShare([row('small', { cost_usd: 1, calls: 5 }), row('mystery', { unpriced: 3, records: 3, calls: 3 }),
                          row('big', { cost_usd: 3, calls: 2 }), row('part', { cost_usd: 0, unpriced: 1, records: 4 })])
eq(share.rows.map((r) => [r.label, r.cost, r.share, r.unpriced]),
   [['big', 3, 0.75, false], ['small', 1, 0.25, false], ['part', 0, 0, false], ['mystery', 0, 0, true]],
   '金额高的在前，整行未定价的排最后；部分未定价不算整行未定价')
must(share.calls === 11, '调用次数合计')
const many = modelShare(['a', 'b', 'c', 'd'].map((l, i) => row(l, { cost_usd: 4 - i })), 2)
eq(many.rows.map((r) => [r.label, r.cost, r.count]), [['a', 4, 1], ['b', 3, 1], [null, 3, 2]], '超过 top 个的合并成一项')
must(Math.abs(many.rows[2].share - 0.3) < 1e-9, '合并项的占比')
eq(modelShare([]), { rows: [], calls: 0 }, '没有用量')
must(modelShare([row('free', {})]).rows[0].share === 0, '合计为 0 时占比为 0（不除以 0）')
console.log('5. 按模型占比 ✓')

// 6. 导航计数
const ov = (extra: Partial<AdminOverview>): AdminOverview => ({ users: 1, active_7d: 1, tokens_30d: 0, cost_30d: 0,
  running: 0, failed_7d: 0, daily: [], unpriced_models: [], ...extra })
const ref = (at: string): ErrorRefRow => ({ ref: 'R', at, user_id: null, username: null, code: 'common.internal', params: {}, where: '' })
eq(navCounts(ov({ failed_7d: 2, unpriced_models: ['a', 'b', 'c'] }), [ref(ago(1)), ref(ago(6)), ref(ago(8))], NOW),
   { jobs: 2, usage: 3, errors: 2 }, '失败数、未定价模型数、近 7 天错误数')
eq(navCounts(ov({}), [ref(ago(30))], NOW), {}, '为 0 的不出现')
eq(navCounts(null, null, NOW), {}, '数据还没到')
eq(navCounts(null, [ref(ago(1))], NOW), { errors: 1 }, '概览没到，错误数照常')
must(badgeText(7) === '7' && badgeText(99) === '99' && badgeText(100) === '99+', '徽标文字')
console.log('6. 导航计数 ✓')

// 7. 导航分组覆盖全部页，且每页只出现一次
eq(NAV_GROUPS.map((g) => g.id), ['overview', 'people', 'ops'], '三个分组')
eq(NAV_GROUPS.flatMap((g) => g.pages).sort(), [...ADMIN_PAGES].sort(), '分组里的页 = 全部后台页')
console.log('7. 导航分组 ✓')

// 8. 「最近一次」时间：本地时区的 MM-DD HH:MM（期望值用 Date 本地 getter 独立拼出）
const p2 = (n: number) => String(n).padStart(2, '0')
for (const iso of ['2026-11-21T03:05:00Z', '2026-01-02T23:59:30+00:00', '2026-12-31T16:30:00Z']) {
  const d = new Date(iso)
  eq(monthDayTime(iso), `${p2(d.getMonth() + 1)}-${p2(d.getDate())} ${p2(d.getHours())}:${p2(d.getMinutes())}`, `本地时间 ${iso}`)
}
eq(monthDayTime(null), '—', '缺失')
eq(monthDayTime('不是时间'), '—', '解析不了')
console.log('8. 最近一次时间格式 ✓')

console.log('\nALL PASS')
