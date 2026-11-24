
/** 每一步右下角固定的主按钮：写明动作和金额；不能点时上方写原因并给「去修复」。 */
import { AnimatePresence, motion } from 'motion/react'
import { ArrowRight, Wrench } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/i18n/core'
import { primaryArgs } from '@/lib/fmt'
import { useMotionPresets } from '@/motion'
import type { Fix, Primary } from '@/workflow'


export function PrimaryBar({ primary, busy, inline, onRun, onFix }: {
  primary: Primary
  busy?: boolean
  /** 放进卡片底部右对齐的一行（不用固定定位）；原因提示在按钮左边 */
  inline?: boolean
  onRun: () => void
  onFix: (fix: Fix) => void
}) {
  const { t } = useI18n()
  const m = useMotionPresets()
  if (primary.action === 'none') return null
  const text = t(primary.label, primaryArgs(primary))
  return (
    <div data-primary-bar className={inline ? 'mt-2 flex flex-wrap items-center justify-end gap-3'
                           : 'primary-bar pointer-events-none fixed bottom-6 right-6 z-30 flex max-w-sm flex-col items-end gap-2 max-md:inset-x-0 max-md:bottom-0 max-md:right-0 max-md:max-w-none max-md:items-stretch max-md:border-t max-md:border-border/70 max-md:bg-background/95 max-md:px-3 max-md:pb-[calc(0.75rem+env(safe-area-inset-bottom))] max-md:pt-3 max-md:shadow-[0_-18px_44px_-34px_rgba(0,0,0,0.38)] max-md:backdrop-blur-xl'}>
      <AnimatePresence>
        {primary.blocked && (
          <motion.div {...m.enter} role="status" data-testid="primary-reason"
                      className={`${inline ? '' : 'pointer-events-auto '}flex items-center gap-3 rounded-lg border bg-card px-3 py-2 text-sm shadow-lg max-md:max-w-none max-md:justify-between`}>
            <span>{t(primary.blocked.reason)}</span>
            {(primary.blocked.fix.step || primary.blocked.fix.target || primary.blocked.fix.openFilm) && (
              <Button size="sm" variant="outline" className="gap-1.5" data-testid="primary-fix"
                      onClick={() => onFix(primary.blocked!.fix)}>
                <Wrench className="size-3.5" />{t('flow.fix')}
              </Button>
            )}
          </motion.div>
        )}
      </AnimatePresence>
      <Button size="lg" data-testid="primary-action"
              className={inline ? 'gap-2'
                : 'pointer-events-auto gap-2 shadow-lg max-md:w-full max-md:justify-center max-md:shadow-none'}
              disabled={!!primary.blocked || busy} onClick={onRun}>
        {text}<ArrowRight className="size-4" />
      </Button>
    </div>
  )
}
