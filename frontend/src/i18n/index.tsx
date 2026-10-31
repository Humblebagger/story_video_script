/** 中英双语：useI18n() 取 t / locale / setLocale；translate() 是纯函数（测试与非组件代码用）。
 *  没有 I18nProvider 时默认中文（测试直接渲染组件即为中文）。语言选择存在本机；首次按浏览器语言。 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { I18nContext, KEY, detectLocale, translate } from './core'
import type { Ctx, Locale } from './core'

/** 只导出组件（避免热更新警告）；useI18n / translate / LOCALES / 类型都从 '@/i18n/core' 取。 */
export function I18nProvider({ children, initial }: { children: ReactNode; initial?: Locale }) {
  const [locale, set] = useState<Locale>(() => initial ?? detectLocale())
  const setLocale = useCallback((l: Locale) => {
    try { localStorage.setItem(KEY, l) } catch { /* 只在本页生效 */ }
    set(l)
  }, [])
  // <html lang> 跟着当前语言（首次与每次切换）
  useEffect(() => { document.documentElement.lang = locale === 'zh' ? 'zh-CN' : 'en' }, [locale])
  const value = useMemo<Ctx>(() => ({ locale, setLocale, t: (k, v) => translate(locale, k, v) }), [locale, setLocale])
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}
