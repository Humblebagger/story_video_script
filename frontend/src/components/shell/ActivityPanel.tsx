/** 右侧面板：两个页签：动态、助手。动态为在跑的任务（任意小说）与最近完成的结果；助手页签只在进了小说后出现。
 *  宽屏时挤压主区，窄屏（< 1100px）盖在主区上方（样式见 workspace.css）。Esc 或「关闭」收起。 */
import { useEffect, useRef } from 'react'
import type { ReactNode } from 'react'
import { motion } from 'motion/react'
import { BellRing, X } from 'lucide-react'
import { EmptyState } from '@/components/common/EmptyState'
import { StatusPill } from '@/components/common/StatusPill'
import type { Tone } from '@/components/common/StatusPill'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { useI18n } from '@/i18n/core'
import { formatMsg } from '@/i18n/serverMsg'
import { DUR, EASE_OUT } from '@/motion'
import { useReducedMotion } from 'motion/react'
import { fmtEta, JOB_STATUS, label } from '@/labels'
import type { JobStatus, JobSummary } from '@/types'

/** 最近完成的一条（只存在内存） */
export interface DoneJob {
  id: string
  status: JobStatus
  work_title: string | null
  chapter: string | null
  novel_id?: string | null
  chapter_id?: string | null
}

const TONE: Partial<Record<JobStatus, Tone>> = {
  succeeded: 'ok', completed_with_warnings: 'warn', failed: 'err', draft_invalid: 'warn',
}

export function ActivityPanel({ running, done, onOpen, onOpenDone, onClose, tab = 'activity', onTab, assistant }: {
  running: JobSummary[]
  done: DoneJob[]
  onOpen: (j: JobSummary) => void
  onOpenDone?: (j: DoneJob) => void
  onClose: () => void
  /** 当前页签；没有 assistant 时只显示「动态」 */
  tab?: 'activity' | 'assistant'
  onTab?: (t: 'activity' | 'assistant') => void
  /** 助手页签的内容（进了小说才有） */
  assistant?: ReactNode
}) {
  const { t, locale } = useI18n()
  const reduced = !!useReducedMotion()
  const ref = useRef<HTMLElement>(null)
  useEffect(() => { ref.current?.focus({ preventScroll: true }) }, [])
  const name = (j: { work_title: string | null; chapter: string | null }) =>
    [j.work_title || t('shell.shelf.converting'), j.chapter].filter(Boolean).join(' · ')
  const showAssistant = tab === 'assistant' && !!assistant
  return (
    <motion.aside ref={ref} tabIndex={-1} data-testid="activity-panel" className={`activity${showAssistant ? ' activity--wide' : ''}`}
                  aria-label={t('shell.activity')}
                  initial={reduced ? { opacity: 0 } : { opacity: 0, x: 48 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={reduced ? { opacity: 0 } : { opacity: 0, x: 48 }}
                  transition={{ duration: DUR.base, ease: EASE_OUT }}
                  onKeyDown={(e) => { if (e.key === 'Escape') { e.stopPropagation(); onClose() } }}>
      <div className="activity__head">
        <div role="tablist" className="activity__tabs">
          <button role="tab" aria-selected={!showAssistant} data-testid="activity-tab-activity"
                  className={`activity__tab${showAssistant ? ' activity__tab--off' : ''}`}
                  onClick={() => onTab?.('activity')}>{t('activity.tab')}</button>
          {assistant && (
            <button role="tab" aria-selected={showAssistant} data-testid="activity-tab-assistant"
                    className={`activity__tab${showAssistant ? '' : ' activity__tab--off'}`}
                    onClick={() => onTab?.('assistant')}>{t('assistant.tab')}</button>
          )}
        </div>
        <Button variant="ghost" size="icon" aria-label={t('activity.close')} onClick={onClose}>
          <X className="size-4" />
        </Button>
      </div>
      <div className="activity__body">
        {showAssistant ? assistant : (<>
        {!running.length && !done.length && (
          <EmptyState icon={<BellRing className="size-5" />} title={t('activity.empty')} hint={t('activity.emptyHint')} />
        )}
        {!!running.length && (
          <section>
            <h3 className="activity__title">{t('activity.running')}</h3>
            <ul className="space-y-2">
              {running.map((j) => {
                const p = j.progress
                const pct = p ? Math.min(100, Math.round((p.done_chars / (p.total_chars || 1)) * 100)) : 0
                return (
                  <li key={j.id} data-testid="activity-running" className="activity__item">
                    <p className="truncate text-sm font-medium">{name(j)}</p>
                    <Progress value={pct} className="h-1" />
                    <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
                      <span className="font-mono tabular-nums">
                        {p?.eta_sec != null ? t('job.etaShort', { t: fmtEta(p.eta_sec) }) : t('shell.shelf.queued')}
                      </span>
                      <Button variant="outline" size="sm" onClick={() => onOpen(j)}>{t('activity.view')}</Button>
                    </div>
                    {j.last_log && <p className="activity__log">{formatMsg(j.last_log, locale)}</p>}
                  </li>
                )
              })}
            </ul>
          </section>
        )}
        {!!done.length && (
          <section>
            <h3 className="activity__title">{t('activity.done')}</h3>
            <ul className="space-y-2">
              {done.map((j) => (
                <li key={j.id} data-testid="activity-done"
                    className={`activity__item${onOpenDone ? ' activity__item--click' : ''}`}>
                  {onOpenDone ? (
                    <button type="button" className="block w-full text-left" onClick={() => onOpenDone(j)}>
                      <p className="truncate text-sm">{name(j)}</p>
                      <div><StatusPill tone={TONE[j.status] ?? 'idle'}>{label(JOB_STATUS, j.status)}</StatusPill></div>
                    </button>
                  ) : (
                    <>
                      <p className="truncate text-sm">{name(j)}</p>
                      <div><StatusPill tone={TONE[j.status] ?? 'idle'}>{label(JOB_STATUS, j.status)}</StatusPill></div>
                    </>
                  )}
                </li>
              ))}
            </ul>
          </section>
        )}
        </>)}
      </div>
    </motion.aside>
  )
}
