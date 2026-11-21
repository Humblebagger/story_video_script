/** 右侧面板：两个页签：动态、助手。动态为在跑的任务（任意小说）与最近完成的结果；助手页签只在进了小说后出现。
 *  宽屏时挤压主区，窄屏（< 1100px）盖在主区上方（样式见 workspace.css）。Esc 或「关闭」收起。 */
import { useEffect, useRef, useState } from 'react'
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
import { taskName, taskWait } from '@/filmTasks'
import { cny } from '@/lib/fmt'
import type { MsgKey } from '@/i18n/core'
import type { FilmTask, JobStatus, JobSummary } from '@/types'

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
const FILM_TONE: Record<FilmTask['state'], Tone> = {
  queued: 'live', running: 'live', downloading: 'live', done: 'ok', failed: 'err', cancelled: 'idle', late: 'warn',
}

/** 本人的出片任务：在跑的、最近结束的，以及这份列表是什么时候取回的（毫秒时间戳，等待时长从它接着走） */
export interface FilmActivity { live: FilmTask[]; ended: FilmTask[]; at: number }

export function ActivityPanel({ running, done, onOpen, onOpenDone, onClose, tab = 'activity', onTab, assistant, film, onOpenFilm }: {
  running: JobSummary[]
  done: DoneJob[]
  /** 出片任务（没有就不显示）；点一条回到画布上的那一段，play 为 true 时顺便打开播放 */
  film?: FilmActivity
  onOpenFilm?: (t: FilmTask, play: boolean) => void
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
  const filmLive = film?.live ?? []
  const filmEnded = film?.ended ?? []
  /** 有出片任务在跑时每秒走一次，等待时长跟着动 */
  const [now, setNow] = useState(() => Date.now())
  const ticking = filmLive.length > 0
  useEffect(() => {
    if (!ticking) return
    setNow(Date.now())
    const id = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [ticking])
  const filmState = (tk: FilmTask) => t(`activity.film.state.${tk.state}` as MsgKey)
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
        {!running.length && !done.length && !filmLive.length && !filmEnded.length && (
          <EmptyState icon={<BellRing className="size-5" />} title={t('activity.empty')} hint={t('activity.emptyHint')} />
        )}
        {!!filmLive.length && (
          <section>
            {!running.length && <h3 className="activity__title">{t('activity.running')}</h3>}
            <ul className="space-y-2">
              {filmLive.map((tk) => (
                <li key={tk.id} data-testid="activity-film-running" className="activity__item">
                  <p className="truncate text-sm font-medium">{taskName(tk)}</p>
                  <div className="flex items-center justify-between gap-2">
                    <StatusPill tone={FILM_TONE[tk.state]}>{filmState(tk)}</StatusPill>
                    <Button variant="outline" size="sm" onClick={() => onOpenFilm?.(tk, false)}>{t('activity.view')}</Button>
                  </div>
                  <p className="text-xs tabular-nums text-muted-foreground">{taskWait(tk, film?.at ?? now, now)}</p>
                </li>
              ))}
            </ul>
          </section>
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
        {!!filmEnded.length && (
          <section>
            {!done.length && <h3 className="activity__title">{t('activity.done')}</h3>}
            <ul className="space-y-2">
              {filmEnded.map((tk) => (
                <li key={tk.id} data-testid="activity-film-done" className="activity__item activity__item--click">
                  <button type="button" className="block w-full text-left"
                          onClick={() => onOpenFilm?.(tk, tk.state === 'done' || tk.state === 'late')}>
                    <p className="truncate text-sm">{taskName(tk)}</p>
                    <div><StatusPill tone={FILM_TONE[tk.state]}>{filmState(tk)}</StatusPill></div>
                    {tk.state === 'late' && tk.cost_cny != null && (
                      <p className="text-xs text-muted-foreground">{t('activity.film.late', { cost: cny(tk.cost_cny) })}</p>
                    )}
                  </button>
                </li>
              ))}
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
