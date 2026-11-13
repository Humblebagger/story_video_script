/** 后端消息对象的渲染（设计 docs/specs/2026-11-13-backend-i18n-design.md §3、§6）。
 *  文案在 zh.ts / en.ts 的 srv 节点，路径与后端代码一致；后端代码清单由 tests/srv-codes.test.ts 核对。
 *  缺译回落：当前语言 → 中文 → message → 代码名。 */
import { currentLocale, lookupKey, translate } from './core'
import type { Locale } from './core'

export interface ServerMsg { code: string; params?: Record<string, unknown>; message?: string }
export type MsgLike = string | ServerMsg | null | undefined

const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v)
export const isServerMsg = (v: unknown): v is ServerMsg => isObj(v) && typeof v.code === 'string' && !('t' in v)

function value(v: unknown, l: Locale): string {
  if (v === null || v === undefined) return ''
  if (Array.isArray(v)) return v.map((x) => value(x, l)).join(translate(l, 'common.listSep'))
  if (isObj(v)) {
    if (v.t === 'money') return `¥${Number(v.cny).toFixed(2)}`
    if (v.t === 'ref') return render({ code: String(v.code) }, l)
    if (v.t === 'vendor') return String(v.text ?? '')
    if (isServerMsg(v)) return render(v, l)
    return ''
  }
  return String(v)
}

function render(m: ServerMsg, l: Locale): string {
  const key = `srv.${m.code}`
  const tpl = lookupKey(l, key) ?? lookupKey('zh', key)
  if (tpl === undefined) return m.message ?? m.code
  const ps = m.params ?? {}
  return tpl.replace(/\{(\w+)\}/g, (all, k: string) => (k in ps ? value(ps[k], l) : all))
}

/** 字符串原样；消息对象按语言渲染；带 message 的旧对象取 message */
export function formatMsg(m: unknown, locale: Locale = currentLocale()): string {
  if (m === null || m === undefined) return ''
  if (typeof m === 'string') return m
  if (isServerMsg(m)) return render(m, locale)
  if (isObj(m) && typeof m.message === 'string') return m.message
  return String(m)
}

/** 异常 → 存进状态的错误值：接口错误保留原始 detail（渲染时再按语言格式化），其它取 message */
export function errValue(e: unknown): MsgLike {
  if (isObj(e) && 'detail' in e && (e as { name?: unknown }).name === 'ApiError') {
    const d = (e as { detail: unknown }).detail
    if (typeof d === 'string' || isServerMsg(d)) return d
    if (isObj(d) && typeof d.message === 'string') return d.message
    return (e as unknown as Error).message
  }
  return e instanceof Error ? e.message : String(e)
}

/** 会话里的段、尝试、自由节点：有 error_msg 按代码，没有（旧数据、未改造的模块）原样显示 error */
export function itemError(x: { error?: string | null; error_msg?: ServerMsg | null }, locale?: Locale): string {
  return x.error_msg ? formatMsg(x.error_msg, locale) : (x.error ?? '')
}
