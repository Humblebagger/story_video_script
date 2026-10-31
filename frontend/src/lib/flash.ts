/** 每个元素当前的去高亮定时器：1.5 秒内再定位一次时重新计时，不被上一次的定时器提前收掉 */
const timers = new WeakMap<Element, number>()

/** 「去修复」：滚到目标元素并高亮 1.5 秒（减少动态效果时直接跳过去） */
export function flashTarget(id: string) {
  const el = document.getElementById(id)
  if (!el) return
  const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  el.scrollIntoView?.({ block: 'center', behavior: reduced ? 'auto' : 'smooth' })
  el.classList.add('fix-flash')
  const prev = timers.get(el)
  if (prev !== undefined) window.clearTimeout(prev)
  timers.set(el, window.setTimeout(() => { el.classList.remove('fix-flash'); timers.delete(el) }, 1500))
}
