/** 右侧面板：两个页签：任务、助手。任务页是本人的任务队列（任意小说）：进行中的与已结束的，
 *  转换、出片片段、成片合成都在这里；助手页签只在进了小说后出现。
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
import { clockText, endedItems, jobWhere, taskWait, taskWhere } from '@/filmTasks'
import { cny } from '@/lib/fmt'
import { hintForMsg, useTierHint, useTtsHint, useWithHint } from '../../adminHints'
import type { MsgKey } from '@/i18n/core'
import type { FilmTask, JobStatus, JobSummary } from '@/types'

/** 已结束的一条转换任务：刚结束的由应用记下，其余来自 /jobs（带结束时间与失败原因） */
export interface DoneJob {
  id: string
  status: JobStatus
  work_title: string | null
  chapter: string | null
  novel_id?: string | null
  chapter_id?: string | null
  finished_at?: string | null
  /** 失败原因（消息对象或文字）；不能给普通用户看的为 null */
  error_msg?: unknown
  /** 所属的小说或章节已删除 */
  deleted?: boolean
}

const TONE: Partial<Record<JobStatus, Tone>> = {
  succeeded: 'ok', completed_with_warnings: 'warn', failed: 'err', draft_invalid: 'warn',
}
const FILM_TONE: Record<FilmTask['state'], Tone> = {
  queued: 'live', running: 'live', downloading: 'live', done: 'ok', failed: 'err', cancelled: 'idle', late: 'warn',
}

/** 本人的出片与合成任务：进行中的、已结束的，以及这份列表是什么时候取回的（毫秒时间戳，等待时长从它接着走） */
export interface FilmActivity { live: FilmTask[]; ended: FilmTask[]; at: number }

export function ActivityPanel({
  running, done, onOpen, onOpenDone, onClose, tab = 'activity', onTab, assistant, film, onOpenFilm, onCancelFilm,
}: {
  running: JobSummary[]
  done: DoneJob[]
  /** 出片与合成任务（没有就不显示）；点一条回到它所在的位置，play 为 true 时顺便打开播放 */
  film?: FilmActivity
  onOpenFilm?: (t: FilmTask, play: boolean) => void
  /** 取消一条进行中的出片任务（确认框由上层弹）；不给就没有取消入口 */
  onCancelFilm?: (t: FilmTask) => void
  onOpen: (j: JobSummary) => void
  onOpenDone?: (j: DoneJob) => void
  onClose: () => void
  /** 当前页签；没有 assistant 时只显示「任务」 */
  tab?: 'activity' | 'assistant'
  onTab?: (t: 'activity' | 'assistant') => void
  /** 助手页签的内容（进了小说才有） */
  assistant?: ReactNode
}) {
  const { t, locale } = useI18n()
  const tierHint = useTierHint()
  const ttsHint = useTtsHint()
  const withHint = useWithHint()
  const reduced = !!useReducedMotion()
  const ref = useRef<HTMLElement>(null)
  useEffect(() => { ref.current?.focus({ preventScroll: true }) }, [])
  const showAssistant = tab === 'assistant' && !!assistant
  const filmLive = film?.live ?? []
  const ended = endedItems(done, film?.ended ?? [])
  /** 有出片任务在跑时每秒走一次，等待时长跟着动 */
  const [now, setNow] = useState(() => Date.now())
  const ticking = filmLive.length > 0
  useEffect(() => {
    if (!ticking) return
    setNow(Date.now())
    const id = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [ticking])
  /** 状态药丸上的字：合成有自己的说法，其余按出片的状态 */
  const filmState = (tk: FilmTask) => (tk.kind === 'compose' && tk.state !== 'queued'
    ? t(`activity.compose.${tk.state === 'done' ? 'done' : tk.state === 'failed' ? 'failed' : 'running'}`)
    : t(`activity.film.state.${tk.state}` as MsgKey))
  /** 定位行：小说 › 章节 › 片段与镜号。窄了截断，悬停看全称 */
  const where = (text: string, strong = false) => (
    <p className={`truncate text-sm${strong ? ' font-medium' : ''}`} title={text} data-testid="activity-where">{text}</p>
  )
  const endedAt = (iso: string | null | undefined) => {
    const text = clockText(iso)
    return text ? <span className="text-xs tabular-nums text-muted-foreground">{text}</span> : null
  }
  const reason = (failed: boolean, err: unknown, tier?: string | null) => {
    if (!failed) return null
    return (
      <p className="activity__log" data-testid="activity-reason">
        {err ? withHint(formatMsg(err, locale), hintForMsg(err, tierHint(tier), ttsHint)) : t('activity.failedHint')}
      </p>
    )
  }
  const jobBody = (j: DoneJob) => (
    <>
      {where(jobWhere(j))}
      <div className="flex items-center justify-between gap-2">
        <StatusPill tone={TONE[j.status] ?? 'idle'}>{label(JOB_STATUS, j.status)}</StatusPill>
        {endedAt(j.finished_at)}
      </div>
      {reason(j.status === 'failed', j.error_msg)}
    </>
  )
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
        {!running.length && !filmLive.length && !ended.length && (
          <EmptyState icon={<BellRing className="size-5" />} title={t('activity.empty')} hint={t('activity.emptyHint')} />
        )}
        {(!!running.length || !!filmLive.length) && (
          <section data-testid="queue-running">
            <h3 className="activity__title">{t('activity.running')}</h3>
            <ul className="space-y-2">
              {running.map((j) => {
                const p = j.progress
                const pct = p ? Math.min(100, Math.round((p.done_chars / (p.total_chars || 1)) * 100)) : 0
                return (
                  <li key={j.id} data-testid="activity-running" className="activity__item">
                    {where(jobWhere(j), true)}
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
              {filmLive.map((tk) => (
                <li key={tk.id} data-testid="activity-film-running" className="activity__item">
                  {where(taskWhere(tk), true)}
                  <div className="flex items-center justify-between gap-2">
                    <StatusPill tone={FILM_TONE[tk.state]}>{filmState(tk)}</StatusPill>
                    <span className="flex items-center gap-1">
                      {tk.cancel && onCancelFilm && (
                        <Button variant="ghost" size="sm" data-testid="activity-film-cancel" onClick={() => onCancelFilm(tk)}>
                          {t(tk.cancel === 'free' ? 'film.cancel.free' : 'film.cancel.paid')}
                        </Button>
                      )}
                      <Button variant="outline" size="sm" onClick={() => onOpenFilm?.(tk, false)}>{t('activity.view')}</Button>
                    </span>
                  </div>
                  <p className="text-xs tabular-nums text-muted-foreground">{taskWait(tk, film?.at ?? now, now)}</p>
                  {!!tk.step && <p className="activity__log">{formatMsg(tk.step, locale)}</p>}
                </li>
              ))}
            </ul>
          </section>
        )}
        {!!ended.length && (
          <section data-testid="queue-ended">
            <h3 className="activity__title">{t('activity.done')}</h3>
            <ul className="space-y-2">
              {ended.map((it) => {
                if (it.job) {
                  const j = it.job
                  return (
                    <li key={`job-${j.id}`} data-testid="activity-done"
                        className={`activity__item${onOpenDone ? ' activity__item--click' : ''}`}>
                      {onOpenDone
                        ? <button type="button" className="block w-full text-left" onClick={() => onOpenDone(j)}>{jobBody(j)}</button>
                        : jobBody(j)}
                    </li>
                  )
                }
                const tk = it.task
                const play = tk.kind !== 'compose' && (tk.state === 'done' || tk.state === 'late')
                return (
                  <li key={`task-${tk.id}`} data-testid="activity-film-done" className="activity__item activity__item--click">
                    <button type="button" className="block w-full text-left" onClick={() => onOpenFilm?.(tk, play)}>
                      {where(taskWhere(tk))}
                      <div className="flex items-center justify-between gap-2">
                        <StatusPill tone={FILM_TONE[tk.state]}>{filmState(tk)}</StatusPill>
                        {endedAt(tk.ended_at)}
                      </div>
                      {tk.state === 'late' && tk.cost_cny != null && (
                        <p className="text-xs text-muted-foreground">{t('activity.film.late', { cost: cny(tk.cost_cny) })}</p>
                      )}
                      {reason(tk.state === 'failed', tk.error, tk.tier)}
                    </button>
                  </li>
                )
              })}
            </ul>
          </section>
        )}
        </>)}
      </div>
    </motion.aside>
  )
}
