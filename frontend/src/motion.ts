/** 动效预设：150–400ms、缓出；系统开了「减少动态效果」时去掉位移，只留淡入淡出。
 *  组件里用 useMotionPresets() 取，传给 motion 组件的 initial / animate / exit / transition。 */
import { useReducedMotion } from 'motion/react'
import type { Transition } from 'motion/react'

export const EASE_OUT: [number, number, number, number] = [0.22, 1, 0.36, 1]
export const DUR = { fast: 0.15, base: 0.24, slow: 0.4 }

export function presets(reduced: boolean) {
  const t = (d: number, delay = 0): Transition => ({ duration: d, ease: EASE_OUT, delay })
  return {
    /** 进场：淡入 + 上移 8px */
    enter: {
      initial: { opacity: 0, y: reduced ? 0 : 8 },
      animate: { opacity: 1, y: 0 },
      exit: { opacity: 0, y: reduced ? 0 : -4 },
      transition: t(DUR.base),
    },
    /** 列表第 i 项依次进场（间隔 40ms，最多 10 项后不再延迟） */
    item: (i: number) => ({
      initial: { opacity: 0, y: reduced ? 0 : 10 },
      animate: { opacity: 1, y: 0 },
      transition: t(DUR.base, Math.min(i, 10) * 0.04),
    }),
    /** 弹出：淡入 + 0.97 → 1 */
    pop: {
      initial: { opacity: 0, scale: reduced ? 1 : 0.97 },
      animate: { opacity: 1, scale: 1 },
      exit: { opacity: 0, scale: reduced ? 1 : 0.98 },
      transition: t(DUR.fast),
    },
  }
}

export function useMotionPresets() {
  return presets(!!useReducedMotion())
}
