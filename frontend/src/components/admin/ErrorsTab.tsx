import { useRef, useState } from 'react'
import { Search, TriangleAlert } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useI18n } from '@/i18n/core'
import { errValue, formatMsg } from '@/i18n/serverMsg'
import type { MsgLike } from '@/i18n/serverMsg'
import { ApiError } from '../../api'
import { adminErrorRef, adminErrors, adminSafetyBlocks } from './api'
import { adminPath } from '../../paths'
import type { ErrorRefRow } from '../../types'
import { AdminLink } from './AdminLink'
import { when } from './format'
import { Empty, ErrorBar, TableSkeleton } from './LoadState'
import { PageHead, RefreshButton } from './PageHead'
import { useLoad } from './useLoad'

/** 错误记录接口明确答复「没有这个编号」 */
const notFound = (e: unknown) => e instanceof ApiError && e.status === 404
  && (e.detail as { code?: unknown } | null)?.code === 'admin.error_ref.not_found'

/** 展开时才取 detail：单条接口每次查看都写审计，列表不带 detail */
function Detail({ r }: { r: ErrorRefRow }) {
  const { t, locale } = useI18n()
  const [text, setText] = useState<string | null>(r.detail ?? null)
  const [err, setErr] = useState<MsgLike>(null)
  const busy = useRef(false)
  const open = (e: { currentTarget: HTMLDetailsElement }) => {
    if (!e.currentTarget.open || text !== null || busy.current) return
    busy.current = true
    setErr(null)
    adminErrorRef(r.ref)
      .then((x) => { setText(x.detail ?? ''); setErr(null) })
      .catch((x) => setErr(errValue(x)))
      .finally(() => { busy.current = false })
  }
  return (
    <details className="adm__err-detail" onToggle={open}>
      <summary>{t('admin.errors.detail')}</summary>
      {err && text === null ? <p className="text-sm text-destructive">{formatMsg(err, locale)}</p> : <pre>{text ?? '…'}</pre>}
    </details>
  )
}

/** 错误记录：意外失败的参考编号（最新在前），可按编号查找；detail 已在服务端脱敏，展开时才取。 */
export function ErrorsTab() {
  const { t, locale } = useI18n()
  const { data, error, reload } = useLoad(adminErrors, [])
  const [q, setQ] = useState('')
  const [hit, setHit] = useState<ErrorRefRow | null>(null)
  const [miss, setMiss] = useState<MsgLike>(null)
  const [blockHit, setBlockHit] = useState<string | null>(null)
  const c = (k: string) => t(`admin.errors.cols.${k}` as 'admin.errors.cols.time')
  const explain = (r: ErrorRefRow) => formatMsg({ code: r.code, params: r.params }, locale)
  const lookup = async () => {
    setHit(null); setMiss(null); setBlockHit(null)
    if (!q.trim()) return
    try { setHit(await adminErrorRef(q)) } catch (e) {
      if (!notFound(e)) { setMiss(errValue(e)); return }       // 查询本身失败：照实显示，不转查
      // 错误记录里没有：用户报来的可能是内容拦截的编号，再查一次拦截记录
      let found
      try { found = await adminSafetyBlocks({ ref: q }) } catch (e2) { setMiss(errValue(e2)); return }   // 转查失败显示这次失败
      if (found.length) setBlockHit(found[0].id)
      else setMiss(errValue(e))
    }
  }
  const row = (r: ErrorRefRow) => (
    <tr key={r.ref}>
      <td>{when(r.at)}</td><td>{r.username ?? r.user_id ?? '—'}</td>
      <td className="adm__mono">{r.ref}</td><td>{explain(r)}</td><td className="adm__mono">{r.where || '—'}</td>
      <td><Detail r={r} /></td>
    </tr>
  )
  const head = (
    <thead>
      <tr><th>{c('time')}</th><th>{c('user')}</th><th>{c('ref')}</th><th>{c('what')}</th><th>{c('where')}</th><th>{c('detail')}</th></tr>
    </thead>
  )
  let body
  if (error) body = <ErrorBar error={error} onRetry={reload} />
  else if (!data) body = <TableSkeleton />
  else if (!data.length) body = <Empty tone="clay" icon={<TriangleAlert aria-hidden />}
                                     title={t('admin.errors.empty')} hint={t('admin.errors.emptyHint')} />
  else body = <table className="adm__table">{head}<tbody>{data.map(row)}</tbody></table>
  return (
    <section className="adm__sec">
      <PageHead title={t('admin.nav.pages.errors')}>
        <RefreshButton label={t('admin.errors.refresh')} onClick={reload} />
      </PageHead>
      <form className="adm__bar" onSubmit={(e) => { e.preventDefault(); void lookup() }}>
        <Input className="adm__search h-9 w-64" value={q} onChange={(e) => setQ(e.target.value)}
               placeholder={t('admin.errors.placeholder')} aria-label={t('admin.errors.lookup')} />
        <Button size="sm" type="submit"><Search aria-hidden />{t('admin.errors.lookup')}</Button>
      </form>
      {miss && <p role="alert" className="text-sm text-destructive">{formatMsg(miss, locale)}</p>}
      {blockHit && (
        <p className="text-sm" data-testid="errors-safety-hit">
          {t('admin.errors.safetyHit', { id: blockHit })}{' '}
          <AdminLink to={adminPath('safety')}>{t('admin.errors.safetyGo')}</AdminLink>
        </p>
      )}
      {hit && <table className="adm__table">{head}<tbody>{row(hit)}</tbody></table>}
      {body}
    </section>
  )
}
