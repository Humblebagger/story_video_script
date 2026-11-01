import { adminOverview } from '../../api'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useI18n } from '@/i18n/core'
import { cn } from '@/lib/utils'
import { int, usd } from './format'
import { LineChart } from './LineChart'
import { ErrorBar } from './LoadState'
import { Sparkline } from './Sparkline'
import { useLoad } from './useLoad'

/** 概览：几张数字卡片 + 近 30 天每日金额；打开时每 30 秒刷新。 */
export function Overview() {
  const { t } = useI18n()
  const { data, error, reload } = useLoad(adminOverview, [], 30000)
  if (error) return <ErrorBar error={error} onRetry={reload} />
  if (!data) {
    return (
      <section className="adm__sec" aria-busy="true">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
          {Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-[76px]" />)}
        </div>
        <Skeleton className="h-[140px] w-full" />
      </section>
    )
  }
  const cards: { k: string; v: string; spark?: boolean; bad?: boolean }[] = [
    { k: t('admin.overview.users'), v: int(data.users) },
    { k: t('admin.overview.active7d'), v: int(data.active_7d) },
    { k: t('admin.overview.tokens30d'), v: int(data.tokens_30d) },
    { k: t('admin.overview.cost30d'), v: usd(data.cost_30d), spark: true },
    { k: t('admin.overview.running'), v: int(data.running) },
    { k: t('admin.overview.failed7d'), v: int(data.failed_7d), bad: data.failed_7d > 0 },
  ]
  return (
    <section className="adm__sec">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
        {cards.map((c) => (
          <Card key={c.k} className="adm__card gap-1 px-4 py-3">
            <b className={cn('font-mono text-[22px] font-semibold tabular-nums', c.bad && 'text-destructive')}>{c.v}</b>
            <span className="text-xs text-muted-foreground">{c.k}</span>
            {c.spark && <Sparkline values={data.daily.map((d) => d.cost_usd)} />}
          </Card>
        ))}
      </div>
      {data.unpriced_models.length > 0 && (
        <p className="adm__warn">
          {t('admin.overview.unpriced', { models: data.unpriced_models.join(t('common.listSep')) })}
        </p>
      )}
      <h3 className="text-base font-semibold">{t('admin.overview.daily')}</h3>
      <LineChart points={data.daily.map((d) => ({ label: d.day.slice(5), value: d.cost_usd }))} />
      <p className="adm__note">{t('admin.overview.note')}</p>
    </section>
  )
}
