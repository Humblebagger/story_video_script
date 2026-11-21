/** 播放窗口的焦点：记住点开它的按钮，关窗后还回去（窗口自己没有 trigger，Radix 默认回不去） */

/** 最近点开播放窗口的那个按钮：关窗后焦点还给它（窗口自己没有 trigger，Radix 默认回不去） */
let opener: HTMLElement | null = null
export const rememberOpener = (el: HTMLElement | null) => { opener = el }

/** 关窗后的落脚点：记下的播放按钮；它不在了就回退到这一段的卡片、侧栏播放按钮，最后是画布容器 */
export function restoreFocus(id: string | undefined) {
  const doc = document
  const sel = id ? `[data-node="${id.replace(/["\\]/g, '\\$&')}"]` : ''
  const el = (opener && opener.isConnected ? opener : null)
    ?? (sel ? doc.querySelector<HTMLElement>(`${sel} [data-testid="ngv-play"]`) : null)
    ?? doc.querySelector<HTMLElement>('[data-testid="clip-play"]')
    ?? (sel ? doc.querySelector<HTMLElement>(sel) : null)
    ?? doc.querySelector<HTMLElement>('[data-testid="node-graph"]')
  if (!el) return
  if (!el.matches('button, a, input, select, textarea, [tabindex]')) el.setAttribute('tabindex', '-1')
  el.focus({ preventScroll: true })
}
