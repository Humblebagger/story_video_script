/** 管理后台的显示格式：金额两位小数美元，token 千分位，时间到分钟（UTC 原样）。 */
export const usd = (n: number | null | undefined) => (n == null ? '—' : `$${n.toFixed(2)}`)
export const usd4 = (n: number | null | undefined) => (n == null ? '—' : `$${n.toFixed(4)}`)
export const int = (n: number | null | undefined) => (n == null ? '—' : n.toLocaleString('en-US'))
export const day = (iso?: string | null) => (iso ? iso.slice(0, 10) : '—')
export const when = (iso?: string | null) => (iso ? iso.slice(0, 16).replace('T', ' ') : '—')
export const PURPOSE: Record<string, string> = { convert: '转换', digest: '章后整理' }
export const ACTION: Record<string, string> = {
  disable: '停用', enable: '启用', set_cap: '设月上限', reset_password: '重置密码',
  grant_admin: '设为管理员', revoke_admin: '取消管理员', update_pricing: '修改价格表',
}
export const errText = (e: unknown) => (e instanceof Error ? e.message : String(e))
