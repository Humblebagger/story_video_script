import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { NumberField } from '@/components/ui/number-field'
import { useI18n } from '@/i18n/core'
import { notice } from '@/lib/notice'
import { adminPricing, adminSavePricing } from './api'
import { errText } from './format'
import { buildPayload, inferVendor, PRICE_KEYS, toDrafts, validateDrafts } from './pricing'
import type { DraftRow, PriceKey, RowErrors } from './pricing'
import type { PricingTable } from '../../types'

const COL: Record<PriceKey, 'input' | 'output' | 'cacheRead' | 'cacheWrite'> = {
  input: 'input', output: 'output', cache_read: 'cacheRead', cache_write: 'cacheWrite',
}

/** 价格表：默认只读；编辑态每格一个输入框，保存前就地校验。unpriced 是用量里出现但没定价的模型。 */
export function PricingEditor({ unpriced = [] }: { unpriced?: string[] }) {
  const { t } = useI18n()
  const [table, setTable] = useState<PricingTable | null>(null)
  const [rows, setRows] = useState<DraftRow[] | null>(null) // null = 只读
  const [errs, setErrs] = useState<Record<number, RowErrors>>({})
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    adminPricing().then(setTable).catch((e: unknown) => notice.err(errText(e)))
  }, [])

  const edit = (extra?: string) => {
    if (!table) return
    const base = rows ?? toDrafts(table.models)
    const next = extra === undefined ? base
      : [...base, blank(base, extra)]
    setRows(next)
    setErrs({})
  }
  const blank = (base: DraftRow[], name = ''): DraftRow => ({
    id: Math.max(-1, ...base.map((r) => r.id)) + 1, name, vendor: '',
    input: '', output: '', cache_read: '', cache_write: '',
  })
  const patch = (id: number, p: Partial<DraftRow>) =>
    setRows((rs) => rs && rs.map((r) => (r.id === id ? { ...r, ...p } : r)))

  const save = async () => {
    if (!rows) return
    const e = validateDrafts(rows)
    setErrs(e)
    if (Object.keys(e).length) return
    setBusy(true)
    try {
      setTable(await adminSavePricing(buildPayload(rows)))
      setRows(null)
      notice.ok(t('admin.usage.saved'))
    } catch (err) {
      notice.err(errText(err))
    } finally {
      setBusy(false)
    }
  }

  const missing = unpriced.filter((m) => !(rows ?? []).some((r) => r.name === m) && !(table && m in table.models))
  const errLabel = (e?: RowErrors['name']) =>
    e === 'empty' ? t('admin.usage.pricing.nameEmpty') : e === 'dup' ? t('admin.usage.pricing.nameDup') : ''

  return (
    <div className="adm__sec">
      <h3 className="text-base font-semibold">{t('admin.usage.pricingTitle')}</h3>
      <p className="adm__note">{t('admin.usage.pricing.unit')}</p>
      {missing.length > 0 && (
        <div className="adm__acts">
          {missing.map((m) => (
            <Button key={m} size="sm" variant="outline" onClick={() => edit(m)}>
              {t('admin.usage.pricing.addUnpriced', { model: m })}
            </Button>
          ))}
        </div>
      )}
      <table className="adm__table adm__pricing">
        <thead>
          <tr>
            <th>{t('admin.usage.pricing.name')}</th>
            <th>{t('admin.usage.pricing.vendor')}</th>
            {PRICE_KEYS.map((k) => (
              <th key={k} className="is-num">{t(`admin.usage.pricing.${COL[k]}`)}</th>
            ))}
            <th>{t('admin.usage.pricing.actions')}</th>
          </tr>
        </thead>
        <tbody>
          {rows === null && table && Object.entries(table.models).map(([name, p]) => {
            const inferred = p.vendor ? null : inferVendor(name)
            return (
              <tr key={name}>
                <td>{name}</td>
                <td>{p.vendor ? p.vendor : <span className="adm__dim">{inferred ?? '—'}</span>}</td>
                {PRICE_KEYS.map((k) => <td key={k} className="is-num">{p[k]}</td>)}
                <td />
              </tr>
            )
          })}
          {rows?.map((r) => {
            const e = errs[r.id] ?? {}
            return (
              <tr key={r.id} className="adm__prow">
                <td>
                  <Input value={r.name} aria-invalid={!!e.name} aria-label={t('admin.usage.pricing.name')}
                         onChange={(ev) => patch(r.id, { name: ev.target.value })} />
                  {e.name && <span className="adm__err">{errLabel(e.name)}</span>}
                </td>
                <td>
                  <Input value={r.vendor} placeholder={inferVendor(r.name) ?? ''}
                         aria-label={t('admin.usage.pricing.vendor')}
                         onChange={(ev) => patch(r.id, { vendor: ev.target.value })} />
                </td>
                {PRICE_KEYS.map((k) => (
                  <td key={k} className="is-num">
                    <NumberField className="ui-number" min={0} step="any" value={r[k]} aria-invalid={!!e[k]}
                           aria-label={t(`admin.usage.pricing.${COL[k]}`)}
                           onChange={(ev) => patch(r.id, { [k]: ev.target.value })} />
                    {e[k] && <span className="adm__err">{t('admin.usage.badPrice')}</span>}
                  </td>
                ))}
                <td>
                  <Button size="sm" variant="ghost"
                          onClick={() => setRows((rs) => rs && rs.filter((x) => x.id !== r.id))}>
                    {t('admin.usage.pricing.remove')}
                  </Button>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <div className="adm__acts">
        {rows === null ? (
          <Button size="sm" disabled={!table} onClick={() => edit()}>{t('admin.usage.pricing.edit')}</Button>
        ) : (
          <>
            <Button size="sm" variant="outline" disabled={busy}
                    onClick={() => setRows((rs) => rs && [...rs, blank(rs)])}>
              {t('admin.usage.pricing.add')}
            </Button>
            <Button size="sm" disabled={busy} onClick={() => void save()}>{t('admin.usage.savePricing')}</Button>
            <Button size="sm" variant="outline" disabled={busy}
                    onClick={() => { setRows(null); setErrs({}) }}>
              {t('admin.usage.pricing.cancel')}
            </Button>
          </>
        )}
      </div>
    </div>
  )
}
