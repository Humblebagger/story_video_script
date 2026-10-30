import { useEffect, useState } from 'react'
import { adminPricing, adminSavePricing, adminUsage, adminUsageCsv } from '../../api'
import type { UsageGroupRow } from '../../types'
import { errText, int, usd, usd4 } from './format'
import { useLoad } from './useLoad'

type Group = 'user' | 'day' | 'model'
const GROUPS: [Group, string][] = [['user', '按用户'], ['day', '按天'], ['model', '按模型']]
const RANGES = [7, 30, 90]

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

/** 用量：分组汇总、每千字成本、导出 CSV；下面是价格表。 */
export function UsageTab() {
  const [group, setGroup] = useState<Group>('user')
  const [days, setDays] = useState(30)
  const { data, error, reload } = useLoad(() => adminUsage(group, days), [group, days])
  const [csvErr, setCsvErr] = useState<string | null>(null)

  const exportCsv = async () => {
    setCsvErr(null)
    try {
      download(`usage-${days}d.csv`, await adminUsageCsv(days))
    } catch (e) {
      setCsvErr(errText(e))
    }
  }

  return (
    <section className="adm__sec">
      <div className="adm__bar">
        <div className="adm__seg">
          {GROUPS.map(([g, label]) => (
            <button key={g} className={group === g ? 'is-on' : ''} onClick={() => setGroup(g)}>{label}</button>
          ))}
        </div>
        <div className="adm__seg">
          {RANGES.map((d) => (
            <button key={d} className={days === d ? 'is-on' : ''} onClick={() => setDays(d)}>{d} 天</button>
          ))}
        </div>
        <button className="btn btn--sm btn--ghost" onClick={() => void exportCsv()}>导出 CSV</button>
        <button className="btn btn--sm btn--ghost" onClick={reload}>刷新</button>
        {csvErr && <span className="adm__err">{csvErr}</span>}
      </div>
      {error && <p className="adm__err">{error}</p>}
      {!data && !error && <p className="adm__empty">加载中…</p>}
      {data && (
        <>
          <p className="adm__kpi">
            每千字成本：均值 {usd4(data.per_k_chars.mean)} · P90 {usd4(data.per_k_chars.p90)}
            （{data.per_k_chars.n} 次成功转换）
          </p>
          {data.unpriced_models.length > 0 && (
            <p className="adm__warn">未定价模型：{data.unpriced_models.join('、')}（不计入金额）</p>
          )}
          <table className="adm__table">
            <thead>
              <tr>
                <th>{GROUPS.find(([g]) => g === data.group)?.[1].slice(1) ?? '分组'}</th>
                <th>调用</th><th>输入</th><th>输出</th><th>缓存读</th><th>缓存写</th>
                <th>原文字数</th><th>金额</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((r) => (
                <tr key={r.key}>
                  <td>{r.label}</td><td>{int(r.calls)}</td><td>{int(r.input)}</td>
                  <td>{int(r.output)}</td><td>{int(r.cache_read)}</td><td>{int(r.cache_write)}</td>
                  <td>{int(r.chars)}</td>
                  <td>{isUnpriced(r) ? '未定价' : usd(r.cost_usd)}{partUnpriced(r) ? `（另有 ${r.unpriced} 条未定价）` : ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="adm__note">金额按当前价格表估算。</p>
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
  const [raw, setRaw] = useState('')
  const [msg, setMsg] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    adminPricing().then((t) => setRaw(JSON.stringify({ models: t.models }, null, 2)))
      .catch((e: unknown) => setMsg(errText(e)))
  }, [])

  const save = async () => {
    let parsed: unknown
    try {
      parsed = JSON.parse(raw)
    } catch {
      setMsg('不是合法的 JSON')
      return
    }
    if (hasBadPrice(parsed)) {
      setMsg('单价必须是不小于 0 的有限数字')
      return
    }
    setBusy(true)
    setMsg(null)
    try {
      const t = await adminSavePricing(parsed)
      setRaw(JSON.stringify({ models: t.models }, null, 2))
      setMsg('已保存')
    } catch (e) {
      setMsg(errText(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="adm__sec">
      <h3 className="adm__h">价格表（美元 / 每百万 token）</h3>
      <textarea className="adm__pricing" value={raw} onChange={(e) => setRaw(e.target.value)} />
      <div className="adm__acts">
        <button className="btn btn--sm" disabled={busy} onClick={() => void save()}>保存价格表</button>
        {msg && <span className="adm__msg">{msg}</span>}
      </div>
    </div>
  )
}
