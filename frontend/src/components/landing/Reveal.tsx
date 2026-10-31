/** 滚到时淡入上浮。没有 IntersectionObserver（测试环境）就直接显示；减少动态效果时只淡入。 */
import type { ReactNode } from 'react'
import { motion, useReducedMotion } from 'motion/react'
import { DUR, EASE_OUT } from '@/motion'

const canObserve = () => typeof window !== 'undefined' && 'IntersectionObserver' in window

export function Reveal({ children, delay = 0, className }: { children: ReactNode; delay?: number; className?: string }) {
  const reduced = !!useReducedMotion()
  if (!canObserve()) return <div className={className}>{children}</div>
  return (
    <motion.div className={className}
                initial={{ opacity: 0, y: reduced ? 0 : 16 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, margin: '-60px' }}
                transition={{ duration: DUR.slow, ease: EASE_OUT, delay }}>
      {children}
    </motion.div>
  )
}
