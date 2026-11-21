/** 运营后台的接口客户端：只随后台代码一起加载，不在主包里。权限以后端为准（非管理员调用一律 403）。
 *  账号菜单用的 adminService 留在 src/api.ts（产品外壳要用）。 */
import { jsonPost, req, send } from '../../api'
import type {
  AdminJobs, AdminOverview, AdminUserDetail, AdminUserRow, AuditEntry, ErrorRefRow, PricingTable, UsageReport,
} from '../../types'

export function adminOverview() {
  return req<AdminOverview>('/admin/overview')
}

export async function adminUsers(): Promise<AdminUserRow[]> {
  return (await req<{ users: AdminUserRow[] }>('/admin/users')).users
}

export function adminUser(id: string) {
  return req<AdminUserDetail>(`/admin/users/${encodeURIComponent(id)}`)
}

export function adminPatchUser(id: string,
  patch: { disabled: boolean } | { role: 'admin' | 'user' } | { monthly_cap_usd: number | null }) {
  return req<AdminUserRow>(`/admin/users/${encodeURIComponent(id)}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(patch),
  })
}

export function adminResetPassword(id: string, password: string) {
  return req<{ ok: boolean }>(`/admin/users/${encodeURIComponent(id)}/password`,
    jsonPost({ password }))
}

export function adminUsage(group: 'user' | 'day' | 'model', days: number) {
  return req<UsageReport>(`/admin/usage?group=${group}&days=${days}`)
}

export async function adminUsageCsv(days: number): Promise<string> {
  return (await send(`/admin/usage.csv?days=${days}`)).text()
}

/** 一次转换的调试日志（管理员；每次查看写审计） */
export const adminJobDebug = (vid: string, userId: string) =>
  req<{ id: string; user_id: string; lines: string[] }>(
    `/admin/jobs/${encodeURIComponent(vid)}/debug?user_id=${encodeURIComponent(userId)}`)

export function adminJobs() {
  return req<AdminJobs>('/admin/jobs')
}

export async function adminErrors(): Promise<ErrorRefRow[]> {
  return (await req<{ errors: ErrorRefRow[] }>('/admin/errors')).errors
}

export function adminErrorRef(ref: string) {
  return req<ErrorRefRow>(`/admin/errors/${encodeURIComponent(ref.trim())}`)
}

export async function adminAudit(): Promise<AuditEntry[]> {
  return (await req<{ audit: AuditEntry[] }>('/admin/audit')).audit
}

export function adminPricing() {
  return req<PricingTable>('/admin/pricing')
}

export function adminSavePricing(table: unknown) {
  return req<PricingTable>('/admin/pricing', {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(table),
  })
}
