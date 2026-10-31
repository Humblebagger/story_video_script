
/** 章节页顶部的六步步骤条：已完成打勾（弹一下）、当前高亮、没到的灰掉；点灰掉的说明要先完成第几步并给直达按钮。
 *  view 是正在看的步骤（可以回看已完成的）。 */
import { useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { Check, Lock } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/i18n/core'
import type { MsgKey } from '@/i18n/core'
import { cn } from '@/lib/utils'
import { useMotionPresets } from '@/motion'
import { STEPS } from '@/workflow'
import type { StepId, StepState } from '@/workflow'

export function Stepper({ states, view, onView }: {
  states: StepState[]
  view: StepId
  onView: (id: StepId) => void
}) {
  const { t } = useI18n()
  const m = useMotionPresets()
  const [hint, setHint] = useState<StepState | null>(null)
  return (
    <nav aria-label={t('flow.stepsLabel')} className="relative">
      <ol className="flex flex-wrap items-center gap-1">
        {states.map((s, i) => (
          <li key={s.id} className="flex items-center gap-1">
            {i > 0 && <span aria-hidden className={cn('h-px w-4 md:w-8', s.state === 'locked' ? 'bg-border' : 'bg-brand')} />}
            <button type="button" data-step={s.id} aria-current={view === s.id ? 'step' : undefined}
                    aria-disabled={s.state === 'locked'}
                    onClick={() => (s.state === 'locked' ? setHint(hint?.id === s.id ? null : s) : (setHint(null), onView(s.id)))}
                    className={cn('flex items-center gap-2 rounded-full border px-3 py-1.5 text-sm transition-colors',
                                  view === s.id && 'border-transparent bg-foreground text-background',
                                  view !== s.id && s.state === 'current' && 'border-brand-to/60 text-foreground',
                                  view !== s.id && s.state === 'done' && 'text-foreground hover:bg-muted',
                                  s.state === 'locked' && 'text-muted-foreground opacity-60')}>
              <span className={cn('flex size-5 items-center justify-center rounded-full text-[11px] font-semibold',
                                  s.state === 'done' ? 'bg-success text-white' : 'bg-muted text-foreground')}>
                <AnimatePresence initial={false} mode="wait">
                  {s.state === 'done'
                    ? <motion.span key="ok" {...m.pop}><Check className="size-3" /></motion.span>
                    : s.state === 'locked'
                      ? <Lock key="lock" className="size-3" />
                      : <span key="n">{i + 1}</span>}
                </AnimatePresence>
              </span>
              {t(`flow.steps.${s.id}` as MsgKey)}
            </button>
          </li>
        ))}
      </ol>
      <AnimatePresence>
        {hint && (
          <motion.div {...m.enter} role="status" data-testid="step-hint"
                      className="absolute left-0 top-full z-20 mt-2 flex items-center gap-3 rounded-lg border bg-popover px-3 py-2 text-sm shadow-lg">
            {t('flow.needs', { n: hint.needs ?? 1 })}
            <Button size="sm" variant="outline"
                    onClick={() => { onView(STEPS[(hint.needs ?? 1) - 1]); setHint(null) }}>
              {t('flow.goNeeded', { n: hint.needs ?? 1 })}
            </Button>
          </motion.div>
        )}
      </AnimatePresence>
    </nav>
  )
}
