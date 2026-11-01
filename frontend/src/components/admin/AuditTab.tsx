import { Inbox, RefreshCw } from 'lucide-react'
import { EmptyState } from '@/components/common/EmptyState'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/i18n/core'
import { adminAudit } from '../../api'
import { ACTION, when } from './format'
import { ErrorBar, TableSkeleton } from './LoadState'
import { useLoad } from './useLoad'

const show = (v: Record<string, unknown> | null) => (v ? JSON.stringify(v) : '—')

/** 审计：管理操作记录，最新在前。 */
export function AuditTab() {
  const { t } = useI18n()
  const { data, error, reload } = useLoad(adminAudit, [])
  const bar = (
    <div className="adm__bar">
      <Button size="sm" variant="outline" onClick={reload}>
        <RefreshCw aria-hidden />{t('admin.audit.refresh')}
      </Button>
    </div>
  )
  const c = (k: string) => t(`admin.audit.cols.${k}` as 'admin.audit.cols.time')
  let body
  if (error) body = <ErrorBar error={error} onRetry={reload} />
  else if (!data) body = <TableSkeleton />
  else if (!data.length) {
    body = <EmptyState icon={<Inbox aria-hidden />} title={t('admin.audit.empty')} hint={t('admin.audit.emptyHint')} />
  } else body = (
    <table className="adm__table">
      <thead>
        <tr><th>{c('time')}</th><th>{c('admin')}</th><th>{c('action')}</th><th>{c('target')}</th><th>{c('before')}</th><th>{c('after')}</th></tr>
      </thead>
      <tbody>
        {data.map((a, i) => (
          <tr key={i}>
            <td>{when(a.at)}</td><td>{a.admin}</td>
            <td><Badge variant="secondary">{ACTION[a.action] ?? a.action}</Badge></td>
            <td>{a.target ?? '—'}</td><td className="adm__json">{show(a.before)}</td><td className="adm__json">{show(a.after)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
  return <section className="adm__sec">{bar}{body}</section>
}
