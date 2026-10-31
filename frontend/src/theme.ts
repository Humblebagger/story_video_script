/** 主题：跟随系统 / 浅色 / 深色。偏好存在本机（读写失败就当跟随系统），实际深浅写到 <html class="dark">。
 *  旧样式（index.css）与 shadcn 组件都看这个 class。 */
import { useSyncExternalStore } from 'react'

export type ThemePref = 'system' | 'light' | 'dark'
const KEY = 'inkreel.theme'
const listeners = new Set<() => void>()

export function readPref(): ThemePref {
  try {
    const v = localStorage.getItem(KEY)
    return v === 'light' || v === 'dark' ? v : 'system'
  } catch {
    return 'system'
  }
}

const systemDark = () =>
  typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-color-scheme: dark)').matches

/** 偏好 → 实际深浅 */
export const resolve = (pref: ThemePref): 'light' | 'dark' =>
  pref === 'system' ? (systemDark() ? 'dark' : 'light') : pref

export function applyTheme(pref: ThemePref = readPref()): void {
  const dark = resolve(pref) === 'dark'
  document.documentElement.classList.toggle('dark', dark)
  document.documentElement.style.colorScheme = dark ? 'dark' : 'light'
}

export function setPref(pref: ThemePref): void {
  try {
    if (pref === 'system') localStorage.removeItem(KEY)
    else localStorage.setItem(KEY, pref)
  } catch { /* 存不了就只在本页生效 */ }
  applyTheme(pref)
  listeners.forEach((l) => l())
}

/** 启动时调用一次：应用偏好，并在「跟随系统」时跟着系统变 */
export function initTheme(): void {
  applyTheme()
  window.matchMedia?.('(prefers-color-scheme: dark)').addEventListener?.('change', () => {
    if (readPref() === 'system') {
      applyTheme('system')
      listeners.forEach((l) => l())
    }
  })
}

function subscribe(l: () => void) {
  listeners.add(l)
  return () => listeners.delete(l)
}

/** 组件里用：当前偏好、实际深浅、改偏好 */
export function useTheme() {
  const pref = useSyncExternalStore(subscribe, readPref, () => 'system' as ThemePref)
  return { pref, resolved: resolve(pref), setPref }
}
