/** 空状态：图标 + 一句话 + 主按钮（可选），淡入上浮 */
import type { ReactNode } from 'react'
import { motion } from 'motion/react'
import { useMotionPresets } from '@/motion'

export function EmptyState({ icon, title, hint, action }: {
  icon?: ReactNode; title: string; hint?: string; action?: ReactNode
}) {
  const m = useMotionPresets()
  return (
    <motion.div {...m.enter} data-testid="empty-state"
                className="mx-auto flex max-w-sm flex-col items-center gap-3 py-16 text-center">
      {icon && <div className="flex size-12 items-center justify-center rounded-2xl bg-muted text-muted-foreground">{icon}</div>}
      <p className="text-base font-medium">{title}</p>
      {hint && <p className="text-sm text-muted-foreground">{hint}</p>}
      {action}
    </motion.div>
  )
}
