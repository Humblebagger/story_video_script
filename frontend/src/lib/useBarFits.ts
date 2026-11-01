/** 顶栏中间插槽放不放得下完整步骤条：按顶栏实际宽度量，而不是按视口断点。
 *
 *  顶栏是「左 1fr / 中 auto / 右 1fr」三栏，步骤条要居中就得两边各让出较宽那侧的宽度。
 *  完整形态的宽度只在完整形态下量得到，量到就记下；紧凑形态下拿记下的值比对，
 *  这样不会在两种形态之间来回跳。环境没有 ResizeObserver（如单测）时恒为放得下。
 */
import { useLayoutEffect, useRef, useState } from 'react'

export function useBarFits(slot: HTMLElement | null): boolean {
  const [fits, setFits] = useState(true)
  const fullWidth = useRef(0)
  useLayoutEffect(() => {
    const header = slot?.parentElement
    if (!slot || !header || typeof ResizeObserver === 'undefined') return
    const check = () => {
      if (fits) fullWidth.current = slot.scrollWidth
      const [left, , right] = Array.from(header.children) as HTMLElement[]
      const cs = getComputedStyle(header)
      const pad = (parseFloat(cs.paddingLeft) || 0) + (parseFloat(cs.paddingRight) || 0)
      const gap = parseFloat(cs.columnGap) || 0
      const side = Math.max(left?.scrollWidth ?? 0, right?.scrollWidth ?? 0)
      const room = header.clientWidth - pad - 2 * gap - 2 * side
      setFits(fullWidth.current <= room)
    }
    check()
    const ro = new ResizeObserver(check)
    ro.observe(header)
    for (const el of Array.from(header.children)) ro.observe(el)
    return () => ro.disconnect()
  }, [slot, fits])
  return fits
}
