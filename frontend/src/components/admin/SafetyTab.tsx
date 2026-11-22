import { useState } from 'react'
import { Search } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useI18n } from '@/i18n/core'
import { errValue, formatMsg } from '@/i18n/serverMsg'
import type { MsgLike } from '@/i18n/serverMsg'
import type { SafetyBlockRow } from '../../types'
import { adminSafetyBlocks, adminSafetyRelease } from './api'
import { when } from './format'
import { Empty, ErrorBar, TableSkeleton } from './LoadState'
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
    <tr key={r.id} data-testid={`safety-row-${r.id}`}>
      <td>{when(r.last_at)}</td>
      <td>{r.username ?? r.user_id ?? '—'}</td>
      <td>{r.novel_title ?? t('admin.deleted')} / {r.chapter_title ?? t('admin.deleted')}{r.clip_id ? ` · ${r.clip_id}` : ''}</td>
      <td>{t(`admin.safety.stage.${r.stage}` as 'admin.safety.stage.convert')}</td>
      <td>{code(`safety.category.${r.category}`)}</td>
      <td>{r.reason_code ? code(r.reason_code) : r.reason || t('admin.safety.cleared')}</td>
      <td className="adm__json">{r.excerpt || t('admin.safety.cleared')}</td>
      <td>{r.hits}</td>
      <td className="adm__mono">{r.id}</td>
      <td>{action(r)}</td>
    </tr>
  )
  let body
  if (error) body = <ErrorBar error={error} onRetry={reload} />
  else if (!data) body = <TableSkeleton />
  else if (!data.length) body = <Empty title={t('admin.safety.empty')} hint={t('admin.safety.emptyHint')} />
  else body = (
    <table className="adm__table">
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
        <select className="adm-top__select" aria-label={t('admin.safety.filter.label')} data-testid="safety-status"
                value={status} onChange={(e) => { setRef(''); setQ(''); setStatus(e.target.value as Status) }}>
          <option value="blocked">{t('admin.safety.filter.blocked')}</option>
          <option value="released">{t('admin.safety.filter.released')}</option>
          <option value="all">{t('admin.safety.filter.all')}</option>
        </select>
        <Input className="adm__search h-9 w-64" value={q} onChange={(e) => setQ(e.target.value)}
               placeholder={t('admin.safety.placeholder')} aria-label={t('admin.safety.lookup')} />
        <Button size="sm" type="submit"><Search aria-hidden />{t('admin.safety.lookup')}</Button>
      </form>
      {fail && <p role="alert" className="text-sm text-destructive">{formatMsg(fail, locale)}</p>}
      {body}
    </section>
  )
}
