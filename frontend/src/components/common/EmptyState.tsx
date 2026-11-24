/** 空状态：图标 + 一句话 + 主按钮（可选），淡入上浮 */
import type { ReactNode } from 'react'
import { motion } from 'motion/react'
import { useMotionPresets } from '@/motion'
import { cn } from '@/lib/utils'

export function EmptyState({ icon, title, hint, action, compact = false }: {
  icon?: ReactNode; title: string; hint?: string; action?: ReactNode; compact?: boolean
}) {
  const m = useMotionPresets()
  return (
    <motion.div {...m.enter} data-testid="empty-state"
                role="status"
                className={cn('empty-state', compact && 'is-compact')}>
      {icon && <div className="empty-state__icon" aria-hidden>{icon}</div>}
      <div className="empty-state__copy">
        <p className="empty-state__title">{title}</p>
        {hint && <p className="empty-state__hint">{hint}</p>}
      </div>
      {action && <div className="empty-state__action">{action}</div>}
    </motion.div>
  )
}
