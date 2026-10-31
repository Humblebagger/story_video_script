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
  let node: unknown = PACKS[locale]
  for (const part of key.split('.')) node = (node as Record<string, unknown> | undefined)?.[part]
  const text = typeof node === 'string' ? node : key
  return vars ? text.replace(/\{(\w+)\}/g, (m, k: string) => (k in vars ? String(vars[k]) : m)) : text
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
