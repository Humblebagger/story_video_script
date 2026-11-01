import { createContext, useContext } from 'react'
/** 语言包的纯部分：类型、translate、detectLocale（无组件，供 index.tsx 与测试使用） */
import { en } from './en'
import { zh } from './zh'

type Widen<T> = { [K in keyof T]: T[K] extends string ? string : Widen<T[K]> }
export type Messages = Widen<typeof zh>
type Paths<T, P extends string = ''> = {
  [K in keyof T & string]: T[K] extends string ? `${P}${K}` : Paths<T[K], `${P}${K}.`>
}[keyof T & string]
export type MsgKey = Paths<Messages>
export type Locale = 'zh' | 'en'
export const LOCALES: { id: Locale; label: string }[] = [{ id: 'zh', label: '中文' }, { id: 'en', label: 'English' }]

const PACKS: Record<Locale, Messages> = { zh, en }
export const KEY = 'inkreel.locale'

export function translate(locale: Locale, key: MsgKey, vars?: Record<string, string | number>): string {
  const lookup = (l: Locale) => {
    let node: unknown = PACKS[l]
    for (const part of key.split('.')) node = (node as Record<string, unknown> | undefined)?.[part]
    return typeof node === 'string' ? node : undefined
  }
  // 缺译：先回落中文（中文为准），再回落键名
  const text = lookup(locale) ?? lookup('zh') ?? key
  return vars ? text.replace(/\{(\w+)\}/g, (m, k: string) => (k in vars ? String(vars[k]) : m)) : text
}

/** 模块级当前语言：给非组件代码（labels、compose、film…）用。I18nProvider 渲染时同步设置；没有 Provider 时为中文。 */
let current: Locale = 'zh'
export const currentLocale = () => current
export function setCurrentLocale(l: Locale) { current = l }
export const tr = (key: MsgKey, vars?: Record<string, string | number>) => translate(current, key, vars)

/** 枚举标签表：属性是 getter，按当前语言取值；Object.keys / entries 照常可用 */
export function localized<K extends string>(zhMap: Record<K, string>, enMap: Record<K, string>): Record<K, string> {
  const out = {} as Record<K, string>
  for (const k of Object.keys(zhMap) as K[]) {
    Object.defineProperty(out, k, { enumerable: true, get: () => (current === 'en' ? enMap[k] : zhMap[k]) })
  }
  return out
}

export function detectLocale(): Locale {
  try {
    const v = localStorage.getItem(KEY)
    if (v === 'zh' || v === 'en') return v
  } catch { /* 读不到就按浏览器 */ }
  const lang = typeof navigator !== 'undefined' ? navigator.language : 'zh'
  return lang.toLowerCase().startsWith('zh') ? 'zh' : 'en'
}

export interface Ctx {
  locale: Locale
  setLocale: (l: Locale) => void
  t: (key: MsgKey, vars?: Record<string, string | number>) => string
}
export const I18nContext = createContext<Ctx>({
  locale: 'zh', setLocale: () => {}, t: (k, v) => translate('zh', k, v),
})


export const useI18n = () => useContext(I18nContext)
