import { useState } from 'react'
import { Search, ShieldCheck } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useI18n } from '@/i18n/core'
import { errValue, formatMsg } from '@/i18n/serverMsg'
import type { MsgLike } from '@/i18n/serverMsg'
import type { SafetyBlockRow } from '../../types'
import { adminSafetyBlocks, adminSafetyRelease } from './api'
import { when } from './format'
import { Empty, ErrorBar, Segmented, TableSkeleton } from './LoadState'
import { PageHead, RefreshButton } from './PageHead'
import { useLoad } from './useLoad'

type Status = 'blocked' | 'released' | 'all'

/** 内容拦截：被内容限制拦下的记录（最近的在前），可按状态筛、按编号查、放行。列表含摘录，每次查看都记审计。 */
export function SafetyTab() {
  const { t, locale } = useI18n()
  const [status, setStatus] = useState<Status>('blocked')
  const [q, setQ] = useState('')
  const [ref, setRef] = useState('')
  const [arming, setArming] = useState<string | null>(null)
  const [fail, setFail] = useState<MsgLike>(null)
  const { data, error, reload } = useLoad(
    () => adminSafetyBlocks(ref ? { ref } : status === 'all' ? {} : { status }), [status, ref])
  const c = (k: string) => t(`admin.safety.cols.${k}` as 'admin.safety.cols.time')
  const code = (key: string) => formatMsg({ code: key, params: {} }, locale)
  const release = async (id: string) => {
    setArming(null); setFail(null)
    try { await adminSafetyRelease(id); reload() } catch (e) { setFail(errValue(e)) }
  }
  const action = (r: SafetyBlockRow) => {
    if (r.status === 'released') return <span>{t('admin.safety.released', { by: r.released_by ?? '—' })}</span>
    if (!r.releasable) return <span className="text-muted-foreground">{t('admin.safety.refused')}</span>
    if (arming === r.id) {
      return (
        <span className="adm__bar">
          <Button size="sm" variant="destructive" type="button" onClick={() => { void release(r.id) }}>{t('admin.safety.confirm')}</Button>
          <Button size="sm" variant="outline" type="button" onClick={() => setArming(null)}>{t('admin.safety.cancel')}</Button>
        </span>
      )
    }
    return <Button size="sm" variant="outline" type="button" onClick={() => setArming(r.id)}>{t('admin.safety.release')}</Button>
  }
  const row = (r: SafetyBlockRow) => (
    <tr key={r.id} className="adm__row" data-testid={`safety-row-${r.id}`}>
      <td data-label={c('time')}>{when(r.last_at)}</td>
      <td data-label={c('user')}>{r.username ?? r.user_id ?? '—'}</td>
      <td data-label={c('where')}>{r.novel_title ?? t('admin.deleted')} / {r.chapter_title ?? t('admin.deleted')}{r.clip_id ? ` · ${r.clip_id}` : ''}</td>
      <td data-label={c('stage')}>{t(`admin.safety.stage.${r.stage}` as 'admin.safety.stage.convert')}</td>
      <td data-label={c('category')}>{code(`safety.category.${r.category}`)}</td>
      <td data-label={c('reason')}>{r.reason_code ? code(r.reason_code) : r.reason || t('admin.safety.cleared')}</td>
      <td className="adm__json adm__cell--wide" data-label={c('excerpt')}>{r.excerpt || t('admin.safety.cleared')}</td>
      <td className="is-num" data-label={c('hits')}>{r.hits}</td>
      <td className="adm__mono" data-label={c('ref')}>{r.id}</td>
      <td data-label={c('action')}>{action(r)}</td>
    </tr>
  )
  let body
  if (error) body = <ErrorBar error={error} onRetry={reload} />
  else if (!data) body = <TableSkeleton />
  else if (!data.length) body = <Empty tone="blue" icon={<ShieldCheck aria-hidden />}
                                     title={t('admin.safety.empty')} hint={t('admin.safety.emptyHint')} />
  else body = (
    <table className="adm__table adm__table--cards">
      <thead>
        <tr>
          <th>{c('time')}</th><th>{c('user')}</th><th>{c('where')}</th><th>{c('stage')}</th><th>{c('category')}</th>
          <th>{c('reason')}</th><th>{c('excerpt')}</th><th>{c('hits')}</th><th>{c('ref')}</th><th>{c('action')}</th>
        </tr>
      </thead>
      <tbody>{data.map(row)}</tbody>
    </table>
  )
  return (
    <section className="adm__sec">
      <PageHead title={t('admin.nav.pages.safety')} hint={t('admin.safety.hint')}>
        <RefreshButton label={t('admin.safety.refresh')} onClick={reload} />
      </PageHead>
      <form className="adm__bar" onSubmit={(e) => { e.preventDefault(); setRef(q.trim()) }}>
        <Segmented label={t('admin.safety.filter.label')} value={status} testId="safety-status"
                   onChange={(v) => { setRef(''); setQ(''); setStatus(v as Status) }}
                   items={[
                     ['blocked', t('admin.safety.filter.blocked')],
                     ['released', t('admin.safety.filter.released')],
                     ['all', t('admin.safety.filter.all')],
                   ]} />
        <Input className="adm__search h-9 w-64" value={q} onChange={(e) => setQ(e.target.value)}
               placeholder={t('admin.safety.placeholder')} aria-label={t('admin.safety.lookup')} />
        <Button size="sm" type="submit"><Search aria-hidden />{t('admin.safety.lookup')}</Button>
      </form>
      {fail && <p role="alert" className="text-sm text-destructive">{formatMsg(fail, locale)}</p>}
      {body}
    </section>
  )
}
