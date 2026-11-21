import { Fragment, useState } from 'react'
import { ArrowDown, ArrowUp, ArrowUpDown, Search } from 'lucide-react'
import { useConfirm } from '@/components/common/ConfirmDialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useI18n } from '@/i18n/core'
import { notice } from '@/lib/notice'
import { adminPatchUser, adminResetPassword, adminUser, adminUsers } from '../../api'
import type { User } from '../../auth'
import type { AdminUserRow } from '../../types'
import { day, errText, int, PURPOSE, usd, when } from './format'
import { LineChart } from './LineChart'
import { ErrorBar, TableSkeleton } from './LoadState'
import { PageHead, RefreshButton } from './PageHead'
import { useLoad } from './useLoad'

type Key = 'username' | 'created_at' | 'last_seen_at' | 'novels' | 'month_cost_usd'

function compare(a: AdminUserRow, b: AdminUserRow, k: Key): number {
  const x = a[k] ?? ''
  const y = b[k] ?? ''
  if (typeof x === 'number' && typeof y === 'number') return x - y
  return String(x).localeCompare(String(y))
}

/** 用户：表格（搜索、表头排序），点一行展开详情与操作。 */
export function Users({ me }: { me: User }) {
  const { data, error, reload } = useLoad(adminUsers, [])
  const [q, setQ] = useState('')
  const [sort, setSort] = useState<Key>('created_at')
  const [desc, setDesc] = useState(true)
  const [open, setOpen] = useState<string | null>(null)
  const { t } = useI18n()

  const pageHead = (
    <PageHead title={t('admin.nav.pages.users')}>
      <RefreshButton label={t('admin.users.refresh')} onClick={reload} />
    </PageHead>
  )
  if (error) return <section className="adm__sec">{pageHead}<ErrorBar error={error} onRetry={reload} /></section>
  if (!data) return <section className="adm__sec">{pageHead}<TableSkeleton /></section>

  const needle = q.trim().toLowerCase()
  const rows = data
    .filter((u) => u.username.toLowerCase().includes(needle))
    .sort((a, b) => (desc ? -1 : 1) * compare(a, b, sort))

  const head = (k: Key, label: string, num = false) => {
    const Icon = sort === k ? (desc ? ArrowDown : ArrowUp) : ArrowUpDown
    return (
      <th className={num ? 'is-num' : undefined}
          aria-sort={sort === k ? (desc ? 'descending' : 'ascending') : 'none'}>
        <button className="adm__sort" onClick={() => {
          if (sort === k) setDesc(!desc)
          else { setSort(k); setDesc(true) }
        }}>
          {label}<Icon size={12} aria-hidden className={sort === k ? 'opacity-100' : 'opacity-40'} />
        </button>
      </th>
    )
  }
  const c = (k: string) => t(`admin.users.cols.${k}` as 'admin.users.cols.username')

  return (
    <section className="adm__sec">
      {pageHead}
      <div className="relative max-w-[260px]">
        <Search size={14} aria-hidden className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
        <Input className="adm__search h-9 pl-8" placeholder={t('admin.users.search')} value={q}
               onChange={(e) => setQ(e.target.value)} />
      </div>
      <table className="adm__table">
        <thead>
          <tr>
            {head('username', c('username'))}<th>{c('role')}</th><th>{c('status')}</th>
            {head('created_at', c('created'))}{head('last_seen_at', c('lastSeen'))}
            {head('novels', c('novels'), true)}<th className="is-num">{c('chapters')}</th>
            {head('month_cost_usd', c('monthCost'), true)}<th className="is-num">{c('cap')}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((u) => (
            <Fragment key={u.id}>
              <tr className={`adm__row${open === u.id ? ' is-open' : ''}`}
                  onClick={() => setOpen(open === u.id ? null : u.id)}>
                <td>{u.username}</td>
                <td>
                  <Badge variant={u.role === 'admin' ? 'default' : 'secondary'}>
                    {u.role === 'admin' ? t('admin.users.roleAdmin') : t('admin.users.roleUser')}
                  </Badge>
                </td>
                <td>
                  {u.disabled
                    ? <Badge variant="destructive" className="adm__bad">{t('admin.users.disabled')}</Badge>
                    : <span className="text-muted-foreground">{t('admin.users.normal')}</span>}
                </td>
                <td>{day(u.created_at)}</td>
                <td>{when(u.last_seen_at)}</td>
                <td className="is-num">{int(u.novels)}</td>
                <td className="is-num">{int(u.chapters)}</td>
                <td className="is-num">{usd(u.month_cost_usd)}</td>
                <td className="is-num">{u.monthly_cap_usd == null ? t('admin.users.unlimited') : usd(u.monthly_cap_usd)}</td>
              </tr>
              {open === u.id && (
                <tr className="adm__detail-row">
                  <td colSpan={9}><UserDetail id={u.id} me={me} onChanged={reload} /></td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </section>
  )
}

function UserDetail({ id, me, onChanged }: { id: string; me: User; onChanged: () => void }) {
  const { data, error, reload } = useLoad(() => adminUser(id), [id])
  const [busy, setBusy] = useState(false)
  const { t } = useI18n()
  const [ask, confirmUi] = useConfirm()
  const [cap, setCap] = useState('')
  const [pwd, setPwd] = useState('')

  if (error) return <ErrorBar error={error} onRetry={reload} />
  if (!data) return <TableSkeleton />
  const u = data.user
  const self = u.id === me.id

  type ActKey = 'disable' | 'enable' | 'revoke' | 'grant' | 'cap' | 'reset'
  const act = async (key: ActKey, fn: () => Promise<unknown>, needConfirm = true, danger = false) => {
    const label = t(`admin.users.acts.${key}.label`)
    // 「修改月上限」不需要确认，也就没有 action 文案
    const action = key === 'cap' ? undefined : t(`admin.users.acts.${key}.action` as 'admin.users.acts.disable.action')
    if (needConfirm && !(await ask({ title: t('confirm.user.title', { label }), action, danger }))) return
    setBusy(true)
    try {
      await fn()
      notice.ok(t(`admin.users.acts.${key}.done`))
      reload()
      onChanged()
    } catch (e) {
      notice.err(errText(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="adm__detail" onClick={(e) => e.stopPropagation()}>
      {confirmUi}
      <dl className="adm__kv">
        <dt>{t('admin.users.userId')}</dt><dd>{u.id}</dd>
        <dt>{t('admin.users.passwordLogin')}</dt><dd>{u.has_password ? t('admin.users.pwdSet') : t('admin.users.pwdUnset')}</dd>
        <dt>{t('admin.users.versions')}</dt><dd>{int(u.versions)}</dd>
      </dl>
      <div className="adm__acts">
        <Button size="sm" variant={u.disabled ? 'outline' : 'destructive'} disabled={busy || self}
                onClick={() => void act(u.disabled ? 'enable' : 'disable',
                  () => adminPatchUser(u.id, { disabled: !u.disabled }), true, !u.disabled)}>
          {u.disabled ? t('admin.users.enable') : t('admin.users.disable')}
        </Button>
        <Button size="sm" variant="outline" disabled={busy || self}
                onClick={() => void act(u.role === 'admin' ? 'revoke' : 'grant',
                  () => adminPatchUser(u.id, { role: u.role === 'admin' ? 'user' : 'admin' }))}>
          {u.role === 'admin' ? t('admin.users.revokeAdmin') : t('admin.users.makeAdmin')}
        </Button>
        <span className="adm__inline">
          <Input className="h-8 w-56" placeholder={t('admin.users.capPlaceholder')} value={cap}
                 onChange={(e) => setCap(e.target.value)} />
          <Button size="sm" variant="outline" disabled={busy}
                  onClick={() => {
                    const s = cap.trim()
                    const n = s === '' ? null : Number(s)
                    if (n !== null && (!Number.isFinite(n) || n < 0)) {
                      notice.err(t('admin.users.capInvalid'))
                      return
                    }
                    void act('cap', () => adminPatchUser(u.id, { monthly_cap_usd: n }), false)
                  }}>
            {t('admin.users.setCap')}
          </Button>
        </span>
        <span className="adm__inline">
          <Input className="h-8 w-52" type="password" placeholder={t('admin.users.pwdPlaceholder')} value={pwd}
                 onChange={(e) => setPwd(e.target.value)} />
          <Button size="sm" variant="outline" disabled={busy || pwd.length < 6}
                  onClick={() => void act('reset',
                    () => adminResetPassword(u.id, pwd).then(() => setPwd('')))}>
            {t('admin.users.resetPwd')}
          </Button>
        </span>
      </div>
      {self && <p className="adm__note">{t('admin.users.selfNote')}</p>}
      <h4 className="text-sm font-semibold">{t('admin.users.daily')}</h4>
      <LineChart height={100}
                 points={data.daily.map((d) => ({ label: d.day.slice(5), value: d.cost_usd }))} />
      <h4 className="text-sm font-semibold">{t('admin.users.recent')}</h4>
      <table className="adm__table adm__table--sm">
        <thead>
          <tr>
            <th>{t('admin.users.recentCols.time')}</th><th>{t('admin.users.recentCols.purpose')}</th>
            <th>{t('admin.users.recentCols.novelChapter')}</th><th>{t('admin.users.recentCols.model')}</th>
            <th>{t('admin.users.recentCols.result')}</th>
            <th className="is-num">{t('admin.users.recentCols.tokens')}</th>
            <th className="is-num">{t('admin.users.recentCols.cost')}</th>
          </tr>
        </thead>
        <tbody>
          {data.recent.map((r, i) => (
            <tr key={i}>
              <td>{when(r.at)}</td>
              <td>{PURPOSE[r.purpose] ?? r.purpose}</td>
              <td>{r.novel_title ?? t('admin.deleted')} / {r.chapter_title ?? t('admin.empty')}</td>
              <td>{r.model}{r.mixed_models ? t('admin.users.mixedModels') : ''}</td>
              <td>
                <Badge variant={r.ok ? 'secondary' : 'destructive'}>
                  {r.ok ? t('admin.users.ok') : t('admin.users.fail')}
                </Badge>
              </td>
              <td className="is-num">{int(r.input + r.output + r.cache_read + r.cache_write)}</td>
              <td className="is-num">{usd(r.cost_usd)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
