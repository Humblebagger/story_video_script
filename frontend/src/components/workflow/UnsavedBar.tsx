/** 底部固定的「有未保存的修改 · 保存 · 撤销」。保存仍是手动的；撤销 = 回到上次保存的样子。 */
import { AnimatePresence, motion } from 'motion/react'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/i18n/core'
import { useMotionPresets } from '@/motion'

export function UnsavedBar({ show, saving, onSave, onUndo }: {
  show: boolean
  saving: boolean
  onSave: () => void
  onUndo: () => void
}) {
  const { t } = useI18n()
  const m = useMotionPresets()
  return (
    // 外层只负责居中（不动画），motion 的 transform 只作用在内层
    <div className="unsaved-dock pointer-events-none fixed inset-x-0 z-30 flex justify-center">
      <AnimatePresence>
        {show && (
          <motion.div {...m.enter} role="status" data-testid="unsaved-bar"
                      className="pointer-events-auto flex items-center gap-3 rounded-lg border bg-card px-4 py-2 text-sm shadow-xl">
            <span className="size-2 rounded-full bg-warning" aria-hidden />
            {t('flow.unsaved')}
            <Button size="sm" disabled={saving} onClick={onSave}>{t('flow.unsavedSave')}</Button>
            <Button size="sm" variant="ghost" disabled={saving} onClick={onUndo}>{t('flow.unsavedUndo')}</Button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
