import { localized } from '@/i18n/core'
import { en } from '@/i18n/en'
import { zh } from '@/i18n/zh'

/** 管理后台的显示格式：金额两位小数美元，token 千分位，时间到分钟（UTC 原样）。 */
export const usd = (n: number | null | undefined) => (n == null ? '—' : `$${n.toFixed(2)}`)
export const usd4 = (n: number | null | undefined) => (n == null ? '—' : `$${n.toFixed(4)}`)
export const int = (n: number | null | undefined) => (n == null ? '—' : n.toLocaleString('en-US'))
export const day = (iso?: string | null) => (iso ? iso.slice(0, 10) : '—')
export const when = (iso?: string | null) => (iso ? iso.slice(0, 16).replace('T', ' ') : '—')
export const PURPOSE: Record<string, string> = localized<string>(zh.admin.purpose, en.admin.purpose)
export const ACTION: Record<string, string> = localized<string>(zh.admin.action, en.admin.action)
export const errText = (e: unknown) => (e instanceof Error ? e.message : String(e))
