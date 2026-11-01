import { Inbox, RefreshCw } from 'lucide-react'
import { EmptyState } from '@/components/common/EmptyState'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/i18n/core'
import { adminJobs } from '../../api'
import { int, when } from './format'
import { ErrorBar, TableSkeleton } from './LoadState'
import { useLoad } from './useLoad'

const clock = (s: number | null) =>
  (s == null ? '—' : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`)

/** 任务：运行中（内存任务表）与近 7 天失败（磁盘上的版本）。 */
export function JobsTab() {
  const { t } = useI18n()
  const { data, error, reload } = useLoad(adminJobs, [])
  if (error) return <ErrorBar error={error} onRetry={reload} />
  if (!data) return <section className="adm__sec"><TableSkeleton /></section>
  const rc = (k: string) => t(`admin.jobs.runningCols.${k}` as 'admin.jobs.runningCols.user')
  const fc = (k: string) => t(`admin.jobs.failedCols.${k}` as 'admin.jobs.failedCols.user')
  return (
    <section className="adm__sec">
      <div className="adm__bar">
        <h3 className="text-base font-semibold">{t('admin.jobs.running')}</h3>
        <Button size="sm" variant="outline" onClick={reload}>
          <RefreshCw aria-hidden />{t('admin.jobs.refresh')}
        </Button>
      </div>
      {data.running.length === 0 ? (
        <EmptyState icon={<Inbox aria-hidden />} title={t('admin.jobs.noRunning')} />
      ) : (
        <table className="adm__table">
          <thead>
            <tr>
              <th>{rc('user')}</th><th>{rc('novelChapter')}</th><th>{rc('status')}</th>
              <th>{rc('start')}</th><th className="is-num">{rc('elapsed')}</th><th className="is-num">{rc('chars')}</th>
            </tr>
          </thead>
          <tbody>
            {data.running.map((j) => (
              <tr key={j.id}>
                <td>{j.username ?? '—'}</td><td>{j.work_title ?? '—'} / {j.chapter ?? '—'}</td>
                <td><Badge variant="secondary">{j.status}</Badge></td>
                <td>{when(j.created_at)}</td><td className="is-num">{clock(j.elapsed_sec)}</td>
                <td className="is-num">{int(j.chars)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <h3 className="text-base font-semibold">{t('admin.jobs.failed')}</h3>
      {data.failed.length === 0 ? (
        <EmptyState icon={<Inbox aria-hidden />} title={t('admin.jobs.noFailed')} />
      ) : (
        <table className="adm__table">
          <thead>
            <tr>
              <th>{fc('user')}</th><th>{fc('novelChapter')}</th><th>{fc('start')}</th>
              <th className="is-num">{fc('chars')}</th><th className="is-num">{fc('attempts')}</th><th>{fc('error')}</th>
            </tr>
          </thead>
          <tbody>
            {data.failed.map((j) => (
              <tr key={j.id}>
                <td>{j.username ?? '—'}</td>
                <td>{j.novel_title ?? t('admin.deleted')} / {j.chapter_title ?? '—'}</td>
                <td>{when(j.created_at)}</td><td className="is-num">{int(j.chars)}</td>
                <td className="is-num">{j.attempts}</td>
                <td>
                  <details className="adm__err-detail">
                    <summary>{j.error.slice(0, 40)}{j.error.length > 40 ? '…' : ''}</summary>
                    <pre>{j.error}</pre>
                  </details>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}
