import { ArrowRight } from 'lucide-react'
import { adminJobs, adminOverview, adminUsage, adminUsers } from './api'
import { adminService } from '../../api'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useI18n } from '@/i18n/core'
import type { MsgLike } from '@/i18n/serverMsg'
import { adminPath } from '../../paths'
import type { AdminOverview } from '../../types'
import { AdminLink } from './AdminLink'
import { jobStats, modelShare, sumLast, userStats } from './derive'
import { int, monthDayTime, usd } from './format'
import { LineChart } from './LineChart'
import { ErrorBar } from './LoadState'
import { PageHead, RefreshButton } from './PageHead'
import { Sparkline } from './Sparkline'
import { DistCard, StatCard } from './StatCard'
import type { DistRow } from './StatCard'
import { useLoad } from './useLoad'

export interface Loaded<T> { data: T | null; error: MsgLike; reload: () => void }

/** 运营概览：数字卡片（副标题与行动链接）、近 14 天趋势、分布小卡片。
 *  shared 由外框传入（外框要用同一份数据算导航计数）；单独渲染时自己取，每 30 秒刷新。 */
export function Overview({ shared }: { shared?: Loaded<AdminOverview> }) {
  return shared ? <OverviewBody {...shared} /> : <OverviewSelf />
}

function OverviewSelf() {
  return <OverviewBody {...useLoad(adminOverview, [], 30000)} />
}

function OverviewBody({ data, error, reload }: Loaded<AdminOverview>) {
  const { t } = useI18n()
  // 副标题与分布要用的三份现有数据；哪份没取到，依赖它的那几处就不显示
  const users = useLoad(adminUsers, [])
  const jobs = useLoad(adminJobs, [])
  const byModel = useLoad(() => adminUsage('model', 30), [])
  const svc = useLoad(adminService, [])
  const refresh = () => { reload(); users.reload(); jobs.reload(); byModel.reload(); svc.reload() }
  const head = (
    <PageHead title={t('admin.nav.pages.overview')} hint={t('admin.overview.note')}>
      <RefreshButton label={t('admin.overview.refresh')} onClick={refresh} />
    </PageHead>
  )
  if (error) return <section className="adm__sec">{head}<ErrorBar error={error} onRetry={reload} /></section>
  if (!data) {
    return (
      <section className="adm__sec" aria-busy="true">
        {head}
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-[112px]" />)}
        </div>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Skeleton className="h-[112px]" /><Skeleton className="h-[112px]" />
          <Skeleton className="col-span-2 h-[168px]" />
        </div>
      </section>
    )
  }
  const us = users.data ? userStats(users.data, Date.now()) : null
  const js = jobs.data ? jobStats(jobs.data) : null
  const ms = byModel.data ? modelShare(byModel.data.rows) : null
  const film = svc.data?.film
  const pct = (part: number, total: number) => (total > 0 ? part / total : 0)

  const jobRows: DistRow[] = js ? [
    { label: t('admin.overview.dist.queued'), value: int(js.queued), share: pct(js.queued, js.queued + js.running + js.failed) },
    { label: t('admin.overview.dist.running'), value: int(js.running), share: pct(js.running, js.queued + js.running + js.failed) },
    { label: t('admin.overview.dist.failed'), value: int(js.failed), share: pct(js.failed, js.queued + js.running + js.failed) },
  ] : []
  const userRows: DistRow[] = us ? [
    { label: t('admin.overview.dist.normal'), value: int(us.normal), share: pct(us.normal, us.total) },
    { label: t('admin.overview.dist.disabled'), value: int(us.disabled), share: pct(us.disabled, us.total) },
  ] : []
  const modelRows: DistRow[] = ms ? ms.rows.map((r) => ({
    label: r.label ?? t('admin.overview.dist.other', { n: r.count }),
    value: r.unpriced ? t('admin.usage.unpricedCell') : usd(r.cost),
    share: r.share,
  })) : []

  return (
    <section className="adm__sec">
      {head}
      {data.unpriced_models.length > 0 && (
        <AdminLink to={adminPath('usage', { group: 'model' })} className="adm__warn adm__warn--link" data-testid="unpriced-alert">
          <span>{t('admin.overview.unpriced', { models: data.unpriced_models.join(t('common.listSep')) })}</span>
          <ArrowRight size={14} aria-hidden />
        </AdminLink>
      )}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard id="users" label={t('admin.overview.users')} value={int(data.users)}
                  sub={us ? t('admin.overview.newIn7d', { n: us.newIn7d }) : null}
                  to={adminPath('users')} action={t('admin.overview.goUsers')} />
        <StatCard id="active" label={t('admin.overview.active7d')} value={int(data.active_7d)}
                  sub={data.users > 0 ? t('admin.overview.activeShare', { pct: Math.round((data.active_7d / data.users) * 100) }) : null}
                  to={adminPath('users')} action={t('admin.overview.goUsers')} />
        <StatCard id="cost" label={t('admin.overview.cost30d')} value={usd(data.cost_30d)}
                  sub={data.daily.length > 0 ? t('admin.overview.cost7d', { amount: usd(sumLast(data.daily, 7)) }) : null}
                  to={adminPath('usage')} action={t('admin.overview.goUsage')}>
          <Sparkline values={data.daily.map((d) => d.cost_usd)} />
        </StatCard>
        <StatCard id="failed" label={t('admin.overview.failed7d')} value={int(data.failed_7d)} bad={data.failed_7d > 0}
                  sub={js?.lastFailedAt ? t('admin.overview.lastFailed', { time: monthDayTime(js.lastFailedAt) }) : null}
                  to={adminPath('jobs', { state: 'failed' })} action={t('admin.overview.goFailed')} />
      </div>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard id="running" label={t('admin.overview.running')} value={int(data.running)}
                  sub={js ? t('admin.overview.queued', { n: js.queued }) : null}
                  to={adminPath('jobs', { state: 'running' })} action={t('admin.overview.goRunning')} />
        <StatCard id="tokens" label={t('admin.overview.tokens30d')} value={int(data.tokens_30d)}
                  sub={ms ? t('admin.overview.calls30d', { n: int(ms.calls) }) : null}
                  to={adminPath('usage')} action={t('admin.overview.goUsage')} />
        <Card className="adm__card adm__chartcard col-span-2 gap-2 px-4 py-3" data-testid="trend">
          <h3 className="text-sm font-semibold">{t('admin.overview.trend')}</h3>
          <LineChart height={120} label={t('admin.overview.trend')}
                     points={data.daily.slice(-14).map((d) => ({ label: d.day.slice(5), value: d.cost_usd }))} />
        </Card>
      </div>
      {(js || us || ms) && (
        <div className="grid gap-3 md:grid-cols-3">
          {js && (
            <DistCard id="jobs" title={t('admin.overview.dist.jobs')} rows={jobRows} empty={t('admin.overview.dist.empty')}
                      note={t('admin.overview.dist.jobsNote')}
                      to={adminPath('jobs')} action={t('admin.overview.goRunning')} />
          )}
          {us && (
            <DistCard id="users" title={t('admin.overview.dist.users')} rows={userRows} empty={t('admin.overview.dist.empty')}
                      note={t('admin.overview.dist.admins', { n: us.admins })}
                      to={adminPath('users')} action={t('admin.overview.goUsers')} />
          )}
          {ms && (
            <DistCard id="models" title={t('admin.overview.dist.models')} rows={modelRows} empty={t('admin.overview.dist.empty')}
                      to={adminPath('usage', { group: 'model' })} action={t('admin.overview.goModels')} />
          )}
        </div>
      )}
      {film && (
        <Card className="adm__card gap-2 px-4 py-3" data-testid="film-routes">
          <h3 className="text-sm font-semibold">{t('admin.overview.filmRoutes.title')}</h3>
          <table className="adm__table">
            <thead>
              <tr>
                <th>{t('admin.overview.filmRoutes.tier')}</th><th>{t('admin.overview.filmRoutes.provider')}</th>
                <th>{t('admin.overview.filmRoutes.model')}</th><th>{t('admin.overview.filmRoutes.key')}</th>
              </tr>
            </thead>
            <tbody>
              {film.tiers.map((r) => (
                <tr key={r.id}>
                  <td className="adm__mono">{r.id}</td><td>{r.provider}</td><td className="adm__mono">{r.model}</td>
                  <td className={r.key_configured ? undefined : 'text-destructive'}>
                    {t(r.key_configured ? 'admin.overview.filmRoutes.keyOk' : 'admin.overview.filmRoutes.keyMissing')}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-xs text-muted-foreground">
            {t('admin.overview.filmRoutes.foot', {
              provider: film.default_provider, tts: film.tts.provider,
              ttsKey: t(film.tts.key_configured ? 'admin.overview.filmRoutes.keyOk' : 'admin.overview.filmRoutes.keyMissing'),
            })}
          </p>
        </Card>
      )}
    </section>
  )
}
