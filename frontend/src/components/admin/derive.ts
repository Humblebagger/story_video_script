/** 后台的纯计算：只用现有接口返回的数据推导副标题、分布与导航计数（不依赖 React；单测见 tests/admin-derive.test.ts）。 */
import type { AdminPage } from '../../paths'
import type { AdminJobs, AdminOverview, AdminUserRow, DailyCost, ErrorRefRow, UsageGroupRow } from '../../types'

const DAY_MS = 86400000

/** iso 时间是否在 now 之前的 days 天以内；缺失或解析不了算不在 */
export function within(iso: string | null | undefined, days: number, now: number): boolean {
  if (!iso) return false
  const at = Date.parse(iso)
  return Number.isFinite(at) && at >= now - days * DAY_MS
}

export interface UserStats { total: number; newIn7d: number; normal: number; disabled: number; admins: number }

/** 用户列表 → 近 7 天新增、正常 / 已停用、管理员人数 */
export function userStats(users: AdminUserRow[], now: number): UserStats {
  const disabled = users.filter((u) => u.disabled).length
  return {
    total: users.length,
    newIn7d: users.filter((u) => within(u.created_at, 7, now)).length,
    normal: users.length - disabled,
    disabled,
    admins: users.filter((u) => u.role === 'admin').length,
  }
}

export interface JobStats { queued: number; running: number; failed: number; lastFailedAt: string | null }

/** 任务接口 → 排队中 / 运行中 / 近 7 天失败；failed 已按时间倒序，第一条就是最近一次 */
export function jobStats(jobs: AdminJobs): JobStats {
  const queued = jobs.running.filter((j) => j.status === 'queued').length
  return {
    queued,
    running: jobs.running.length - queued,
    failed: jobs.failed.length,
    lastFailedAt: jobs.failed[0]?.created_at ?? null,
  }
}

/** 最近 n 天的金额合计（daily 按天升序，最后一项是今天） */
export const sumLast = (daily: DailyCost[], n: number) =>
  daily.slice(-n).reduce((sum, d) => sum + d.cost_usd, 0)

export interface ModelShare {
  /** label 为 null = 排在 top 之外的合并项，count 是合并了几个模型 */
  rows: { label: string | null; cost: number; share: number; unpriced: boolean; count: number }[]
  calls: number
}

/** 按模型的用量行 → 金额占比（金额高的在前，整行未定价的排最后；超过 top 个的合并成一项） */
export function modelShare(rows: UsageGroupRow[], top = 5): ModelShare {
  const whole = (r: UsageGroupRow) => r.records > 0 && r.unpriced === r.records
  const total = rows.reduce((sum, r) => sum + r.cost_usd, 0)
  const share = (cost: number) => (total > 0 ? cost / total : 0)
  const sorted = [...rows].sort((a, b) => Number(whole(a)) - Number(whole(b)) || b.cost_usd - a.cost_usd)
  const out: ModelShare['rows'] = sorted.slice(0, top).map((r) => (
    { label: r.label, cost: r.cost_usd, share: share(r.cost_usd), unpriced: whole(r), count: 1 }))
  const rest = sorted.slice(top)
  if (rest.length) {
    const cost = rest.reduce((sum, r) => sum + r.cost_usd, 0)
    out.push({ label: null, cost, share: share(cost), unpriced: false, count: rest.length })
  }
  return { rows: out, calls: rows.reduce((sum, r) => sum + r.calls, 0) }
}

/** 导航项旁的计数：任务 = 近 7 天失败；用量 = 未定价模型数；错误 = 近 7 天的错误记录数。为 0 或数据没到就没有这一项 */
export function navCounts(overview: AdminOverview | null, errors: ErrorRefRow[] | null,
                          now: number): Partial<Record<AdminPage, number>> {
  const out: Partial<Record<AdminPage, number>> = {}
  if (overview && overview.failed_7d > 0) out.jobs = overview.failed_7d
  if (overview && overview.unpriced_models.length > 0) out.usage = overview.unpriced_models.length
  const recent = errors ? errors.filter((e) => within(e.at, 7, now)).length : 0
  if (recent > 0) out.errors = recent
  return out
}

/** 计数徽标的文字：超过 99 写 99+ */
export const badgeText = (n: number) => (n > 99 ? '99+' : String(n))

/** 导航分组：总览 / 用户与用量 / 运行 */
export const NAV_GROUPS: { id: 'overview' | 'people' | 'ops'; pages: AdminPage[] }[] = [
  { id: 'overview', pages: ['overview'] },
  { id: 'people', pages: ['users', 'usage'] },
  { id: 'ops', pages: ['jobs', 'errors', 'audit'] },
]
