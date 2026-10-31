/** 「去修复」：滚到目标元素并高亮 1.5 秒（减少动态效果时直接跳过去） */
export function flashTarget(id: string) {
  const el = document.getElementById(id)
  if (!el) return
  const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  el.scrollIntoView?.({ block: 'center', behavior: reduced ? 'auto' : 'smooth' })
  el.classList.add('fix-flash')
  window.setTimeout(() => el.classList.remove('fix-flash'), 1500)
}
