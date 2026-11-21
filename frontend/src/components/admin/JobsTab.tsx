import { useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/i18n/core'
import { errValue, failHead, formatMsg, itemError } from '@/i18n/serverMsg'
import type { MsgLike } from '@/i18n/serverMsg'
import { adminJobDebug, adminJobs } from '../../api'
import type { JobState } from '../../paths'
import { int, when } from './format'
import { Empty, ErrorBar, Segmented, TableSkeleton } from './LoadState'
import { PageHead, RefreshButton } from './PageHead'
import { useLoad } from './useLoad'

const clock = (s: number | null) =>
  (s == null ? '—' : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`)

type DebugState = Record<string, { lines?: string[]; err?: MsgLike }>
type Filter = JobState | 'all'

/** 任务：运行中（内存任务表）与近 7 天失败（磁盘上的版本）。
 *  state / onState 由外框从地址传入（?state=running|failed，null 为全部）；不传时筛选是组件内状态。 */
export function JobsTab({ state, onState }: { state?: JobState | null; onState?: (s: JobState | null) => void } = {}) {
  const { t, locale } = useI18n()
  const { data, error, reload } = useLoad(adminJobs, [])
  const [own, setOwn] = useState<JobState | null>(null)
  const filter: Filter = (state !== undefined ? state : own) ?? 'all'
  const setFilter = (f: Filter) => {
    const next = f === 'all' ? null : f
    if (onState) onState(next)
    else setOwn(next)
  }
  /** 点开的调试日志：按任务 id 存结果或错误（错误存原始值，切语言跟着变） */
  const [debug, setDebug] = useState<DebugState>({})
  const toggleDebug = async (id: string, userId: string) => {
    if (debug[id]) { setDebug(({ [id]: _, ...rest }) => rest); return }
    try {
      const r = await adminJobDebug(id, userId)
      setDebug((d) => ({ ...d, [id]: { lines: r.lines } }))
    } catch (e) {
      setDebug((d) => ({ ...d, [id]: { err: errValue(e) } }))
    }
  }
  const debugBtn = (j: { id: string; user_id: string }) => (
    <Button size="sm" variant="outline" onClick={() => void toggleDebug(j.id, j.user_id)}>{t('admin.jobs.debug')}</Button>
  )
  const debugBody = (id: string) => {
    const d = debug[id]
    if (!d) return null
    return d.lines
      ? <pre>{d.lines.length ? d.lines.join('\n') : t('admin.jobs.debugEmpty')}</pre>
      : <pre>{formatMsg(d.err, locale)}</pre>
  }
  const head = (
    <PageHead title={t('admin.nav.pages.jobs')}>
      <Segmented label={t('admin.jobs.filter.label')} value={filter} onChange={setFilter}
                 items={[['all', t('admin.jobs.filter.all')], ['running', t('admin.jobs.filter.running')],
                         ['failed', t('admin.jobs.filter.failed')]]} />
      <RefreshButton label={t('admin.jobs.refresh')} onClick={reload} />
    </PageHead>
  )
  if (error) return <section className="adm__sec">{head}<ErrorBar error={error} onRetry={reload} /></section>
  if (!data) return <section className="adm__sec">{head}<TableSkeleton /></section>
  const rc = (k: string) => t(`admin.jobs.runningCols.${k}` as 'admin.jobs.runningCols.user')
  const fc = (k: string) => t(`admin.jobs.failedCols.${k}` as 'admin.jobs.failedCols.user')
  return (
    <section className="adm__sec">
      {head}
      {filter !== 'failed' && (
        <>
          <h3 className="text-base font-semibold">{t('admin.jobs.running')}</h3>
          {data.running.length === 0 ? (
            <Empty title={t('admin.jobs.noRunning')} />
          ) : (
            <table className="adm__table" data-testid="jobs-running">
              <thead>
                <tr>
                  <th>{rc('user')}</th><th>{rc('novelChapter')}</th><th>{rc('status')}</th>
                  <th>{rc('start')}</th><th className="is-num">{rc('elapsed')}</th><th className="is-num">{rc('chars')}</th><th />
                </tr>
              </thead>
              <tbody>
                {data.running.map((j) => (
                  <tr key={j.id}>
                    <td>{j.username ?? '—'}</td><td>{j.work_title ?? '—'} / {j.chapter ?? '—'}</td>
                    <td><Badge variant="secondary">{j.status}</Badge></td>
                    <td>{when(j.created_at)}</td><td className="is-num">{clock(j.elapsed_sec)}</td>
                    <td className="is-num">{int(j.chars)}</td>
                    <td>{debugBtn(j)}{debugBody(j.id)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
      {filter !== 'running' && (
        <>
          <h3 className="text-base font-semibold">{t('admin.jobs.failed')}</h3>
          {data.failed.length === 0 ? (
            <Empty title={t('admin.jobs.noFailed')} />
          ) : (
            <table className="adm__table" data-testid="jobs-failed">
              <thead>
                <tr>
                  <th>{fc('user')}</th><th>{fc('novelChapter')}</th><th>{fc('start')}</th>
                  <th className="is-num">{fc('chars')}</th><th className="is-num">{fc('attempts')}</th><th>{fc('error')}</th>
                </tr>
              </thead>
              <tbody>
                {data.failed.map((j) => {
                  const reason = formatMsg(failHead(j.error_msg ?? j.error), locale)
                  const text = itemError(j, locale)
                  return (
                    <tr key={j.id}>
                      <td>{j.username ?? '—'}</td>
                      <td>{j.novel_title ?? t('admin.deleted')} / {j.chapter_title ?? '—'}</td>
                      <td>{when(j.created_at)}</td><td className="is-num">{int(j.chars)}</td>
                      <td className="is-num">{j.attempts}</td>
                      <td>
                        <details className="adm__err-detail">
                          <summary>{reason.slice(0, 40)}{reason.length > 40 ? '…' : ''}</summary>
                          <pre>{text}</pre>
                        </details>
                        {debugBtn(j)}{debugBody(j.id)}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </>
      )}
    </section>
  )
}
