import { useEffect, useState } from 'react'
import { Download } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { useI18n } from '@/i18n/core'
import { notice } from '@/lib/notice'
import { adminPricing, adminSavePricing, adminUsage, adminUsageCsv } from './api'
import { USAGE_DAYS, USAGE_GROUPS } from '../../paths'
import type { UsageDays, UsageGroup } from '../../paths'
import type { UsageGroupRow } from '../../types'
import { errText, int, usd, usd4 } from './format'
import { Empty, ErrorBar, Segmented, TableSkeleton } from './LoadState'
import { PageHead, RefreshButton } from './PageHead'
import { useLoad } from './useLoad'

function download(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8' }))
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  URL.revokeObjectURL(url)
}

/** 整行每条记录都未定价（unpriced 与 records 都是记录数）。 */
const isUnpriced = (r: UsageGroupRow) => r.records > 0 && r.unpriced === r.records
/** 部分记录未定价：金额是已定价部分的合计。 */
const partUnpriced = (r: UsageGroupRow) => r.unpriced > 0 && !isUnpriced(r)

/** 用量与花费：分组汇总、每千字成本、导出 CSV；下面是价格表。
 *  group / days / onQuery 由外框从地址传入（?group=、?days=）；不传时是组件内状态。 */
export function UsageTab(p: {
  group?: UsageGroup; days?: UsageDays; onQuery?: (group: UsageGroup, days: UsageDays) => void
} = {}) {
  const { t } = useI18n()
  const [own, setOwn] = useState<{ group: UsageGroup; days: UsageDays }>({ group: 'user', days: 30 })
  const group = p.group ?? own.group
  const days = p.days ?? own.days
  const query = (g: UsageGroup, d: UsageDays) => {
    if (p.onQuery) p.onQuery(g, d)
    else setOwn({ group: g, days: d })
  }
  const { data, error, reload } = useLoad(() => adminUsage(group, days), [group, days])

  const exportCsv = async () => {
    try {
      download(`usage-${days}d.csv`, await adminUsageCsv(days))
    } catch (e) {
      notice.err(errText(e))
    }
  }
  const th = (k: string, num = true) => (
    <th className={num ? 'is-num' : undefined}>{t(`admin.usage.cols.${k}` as 'admin.usage.cols.calls')}</th>
  )

  return (
    <section className="adm__sec">
      <PageHead title={t('admin.nav.pages.usage')}>
        <Button size="sm" variant="outline" onClick={() => void exportCsv()}>
          <Download aria-hidden />{t('admin.usage.exportCsv')}
        </Button>
        <RefreshButton label={t('admin.usage.refresh')} onClick={reload} />
      </PageHead>
      <div className="adm__bar">
        <Segmented items={USAGE_GROUPS.map((g) => [g, t(`admin.usage.groups.${g}`)] as [UsageGroup, string])}
                   value={group} onChange={(g) => query(g, days)} />
        <Segmented items={USAGE_DAYS.map((d) => [d, t('admin.usage.days', { n: d })] as [UsageDays, string])}
                   value={days} onChange={(d) => query(group, d)} />
      </div>
      {error && <ErrorBar error={error} onRetry={reload} />}
      {!data && !error && <TableSkeleton />}
      {data && (
        <>
          <p className="adm__kpi">
            {t('admin.usage.perK', {
              mean: usd4(data.per_k_chars.mean), p90: usd4(data.per_k_chars.p90), n: data.per_k_chars.n,
            })}
          </p>
          {data.unpriced_models.length > 0 && (
            <p className="adm__warn">
              {t('admin.usage.unpriced', { models: data.unpriced_models.join(t('common.listSep')) })}
            </p>
          )}
          {data.rows.length === 0 ? (
            <Empty title={t('admin.usage.empty')} />
          ) : (
            <table className="adm__table">
              <thead>
                <tr>
                  <th>{t(`admin.usage.groupCol.${data.group}` as 'admin.usage.groupCol.user')}</th>
                  {th('calls')}{th('input')}{th('output')}{th('cacheRead')}{th('cacheWrite')}
                  {th('chars')}{th('cost')}
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r) => (
                  <tr key={r.key}>
                    <td>{r.label}</td><td className="is-num">{int(r.calls)}</td><td className="is-num">{int(r.input)}</td>
                    <td className="is-num">{int(r.output)}</td><td className="is-num">{int(r.cache_read)}</td>
                    <td className="is-num">{int(r.cache_write)}</td>
                    <td className="is-num">{int(r.chars)}</td>
                    <td className="is-num">
                      {isUnpriced(r) ? t('admin.usage.unpricedCell') : usd(r.cost_usd)}
                      {partUnpriced(r) ? t('admin.usage.partUnpriced', { n: r.unpriced }) : ''}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="adm__note">{t('admin.usage.note')}</p>
        </>
      )}
      <PricingEditor />
    </section>
  )
}

/** 单价必须是有限的非负数：JSON 里的 1e400 会解析成 Infinity，序列化后变成 null。 */
function hasBadPrice(table: unknown): boolean {
  const models = (table as { models?: unknown } | null)?.models
  if (!models || typeof models !== 'object') return false
  return Object.values(models).some((m) => m && typeof m === 'object' &&
    Object.values(m).some((v) => typeof v === 'number' && !(Number.isFinite(v) && v >= 0)))
}

function PricingEditor() {
  const { t } = useI18n()
  const [raw, setRaw] = useState('')
  const [msg, setMsg] = useState<string | null>(null) // 跟输入框绑在一起的校验错误
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    adminPricing().then((p) => setRaw(JSON.stringify({ models: p.models }, null, 2)))
      .catch((e: unknown) => notice.err(errText(e)))
  }, [])

  const save = async () => {
    let parsed: unknown
    try {
      parsed = JSON.parse(raw)
    } catch {
      setMsg(t('admin.usage.badJson'))
      return
    }
    if (hasBadPrice(parsed)) {
      setMsg(t('admin.usage.badPrice'))
      return
    }
    setBusy(true)
    setMsg(null)
    try {
      const p = await adminSavePricing(parsed)
      setRaw(JSON.stringify({ models: p.models }, null, 2))
      notice.ok(t('admin.usage.saved'))
    } catch (e) {
      notice.err(errText(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="adm__sec">
      <h3 className="text-base font-semibold">{t('admin.usage.pricingTitle')}</h3>
      <Textarea className="adm__pricing min-h-[180px] font-mono text-[12.5px]" value={raw}
                onChange={(e) => setRaw(e.target.value)} />
      <div className="adm__acts">
        <Button size="sm" disabled={busy} onClick={() => void save()}>{t('admin.usage.savePricing')}</Button>
        {msg && <span className="adm__err">{msg}</span>}
      </div>
    </div>
  )
}
