import { localized } from '@/i18n/core'
import { enAdmin } from './messages.en'
import { zhAdmin } from './messages.zh'

/** 管理后台的显示格式：金额两位小数美元，token 千分位，时间到分钟（UTC 原样）。 */
export const usd = (n: number | null | undefined) => (n == null ? '—' : `$${n.toFixed(2)}`)
export const usd4 = (n: number | null | undefined) => (n == null ? '—' : `$${n.toFixed(4)}`)
export const int = (n: number | null | undefined) => (n == null ? '—' : n.toLocaleString('en-US'))
export const day = (iso?: string | null) => (iso ? iso.slice(0, 10) : '—')
export const when = (iso?: string | null) => (iso ? iso.slice(0, 16).replace('T', ' ') : '—')
/** 本地时区的 MM-DD HH:MM（总览「最近一次」，设计 §5.3）；缺失或解析不了写 — */
export const monthDayTime = (iso?: string | null) => {
  const d = iso ? new Date(iso) : null
  if (!d || Number.isNaN(d.getTime())) return '—'
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}
export const PURPOSE: Record<string, string> = localized<string>(zhAdmin.purpose, enAdmin.purpose)
export const ACTION: Record<string, string> = localized<string>(zhAdmin.action, enAdmin.action)
export { errText } from '@/i18n/serverMsg'
