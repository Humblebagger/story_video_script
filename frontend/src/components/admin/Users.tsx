import { Fragment, useState } from 'react'
import { useConfirm } from '@/components/common/ConfirmDialog'
import { useI18n } from '@/i18n/core'
import { notice } from '@/lib/notice'
import { adminPatchUser, adminResetPassword, adminUser, adminUsers } from '../../api'
import type { User } from '../../auth'
import type { AdminUserRow } from '../../types'
import { day, errText, int, PURPOSE, usd, when } from './format'
import { LineChart } from './LineChart'
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

  if (error) return <p className="adm__err">{error}</p>
  if (!data) return <p className="adm__empty">加载中…</p>

  const needle = q.trim().toLowerCase()
  const rows = data
    .filter((u) => u.username.toLowerCase().includes(needle))
    .sort((a, b) => (desc ? -1 : 1) * compare(a, b, sort))

  const head = (k: Key, label: string) => (
    <th>
      <button className="adm__sort" onClick={() => {
        if (sort === k) setDesc(!desc)
        else { setSort(k); setDesc(true) }
      }}>
        {label}{sort === k ? (desc ? ' ↓' : ' ↑') : ''}
      </button>
    </th>
  )

  return (
    <section className="adm__sec">
      <input className="adm__search" placeholder="搜索用户名" value={q}
             onChange={(e) => setQ(e.target.value)} />
      <table className="adm__table">
        <thead>
          <tr>
            {head('username', '用户名')}<th>角色</th><th>状态</th>
            {head('created_at', '注册')}{head('last_seen_at', '最近活跃')}
            {head('novels', '小说')}<th>章节</th>
            {head('month_cost_usd', '本月金额')}<th>月上限</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((u) => (
            <Fragment key={u.id}>
              <tr className={`adm__row${open === u.id ? ' is-open' : ''}`}
                  onClick={() => setOpen(open === u.id ? null : u.id)}>
                <td>{u.username}</td>
                <td>{u.role === 'admin' ? '管理员' : '用户'}</td>
                <td>{u.disabled ? <span className="adm__bad">已停用</span> : '正常'}</td>
                <td>{day(u.created_at)}</td>
                <td>{when(u.last_seen_at)}</td>
                <td>{int(u.novels)}</td>
                <td>{int(u.chapters)}</td>
                <td>{usd(u.month_cost_usd)}</td>
                <td>{u.monthly_cap_usd == null ? '不限' : usd(u.monthly_cap_usd)}</td>
              </tr>
              {open === u.id && (
                <tr>
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

  if (error) return <p className="adm__err">{error}</p>
  if (!data) return <p className="adm__empty">加载中…</p>
  const u = data.user
  const self = u.id === me.id

  const act = async (label: string, fn: () => Promise<unknown>, needConfirm = true, danger = false) => {
    if (needConfirm && !(await ask({ title: t('confirm.user.title', { label }), action: label, danger }))) return
    setBusy(true)
    try {
      await fn()
      notice.ok(`已${label}`)
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
        <dt>用户 ID</dt><dd>{u.id}</dd>
        <dt>密码登录</dt><dd>{u.has_password ? '已设置' : '未设置'}</dd>
        <dt>版本数</dt><dd>{int(u.versions)}</dd>
      </dl>
      <div className="adm__acts">
        <button className="btn btn--sm btn--ghost" disabled={busy || self}
                onClick={() => void act(u.disabled ? '启用该账号' : '停用该账号',
                  () => adminPatchUser(u.id, { disabled: !u.disabled }), true, !u.disabled)}>
          {u.disabled ? '启用' : '停用'}
        </button>
        <button className="btn btn--sm btn--ghost" disabled={busy || self}
                onClick={() => void act(u.role === 'admin' ? '取消管理员' : '设为管理员',
                  () => adminPatchUser(u.id, { role: u.role === 'admin' ? 'user' : 'admin' }))}>
          {u.role === 'admin' ? '取消管理员' : '设为管理员'}
        </button>
        <span className="adm__inline">
          <input placeholder="月上限（美元，空 = 不限）" value={cap}
                 onChange={(e) => setCap(e.target.value)} />
          <button className="btn btn--sm btn--ghost" disabled={busy}
                  onClick={() => {
                    const s = cap.trim()
                    const n = s === '' ? null : Number(s)
                    if (n !== null && (!Number.isFinite(n) || n < 0)) {
                      notice.err('请输入不小于 0 的金额，留空表示不限')
                      return
                    }
                    void act('修改月上限', () => adminPatchUser(u.id, { monthly_cap_usd: n }), false)
                  }}>
            设上限
          </button>
        </span>
        <span className="adm__inline">
          <input type="password" placeholder="新密码（至少 6 位）" value={pwd}
                 onChange={(e) => setPwd(e.target.value)} />
          <button className="btn btn--sm btn--ghost" disabled={busy || pwd.length < 6}
                  onClick={() => void act('重置密码',
                    () => adminResetPassword(u.id, pwd).then(() => setPwd('')))}>
            重置密码
          </button>
        </span>
      </div>
      {self && <p className="adm__note">不能停用自己，也不能修改自己的角色。</p>}
      <h4 className="adm__h">近 30 天每日金额</h4>
      <LineChart height={100}
                 points={data.daily.map((d) => ({ label: d.day.slice(5), value: d.cost_usd }))} />
      <h4 className="adm__h">最近用量</h4>
      <table className="adm__table adm__table--sm">
        <thead>
          <tr><th>时间</th><th>用途</th><th>小说 / 章节</th><th>模型</th><th>结果</th>
              <th>token</th><th>金额</th></tr>
        </thead>
        <tbody>
          {data.recent.map((r, i) => (
            <tr key={i}>
              <td>{when(r.at)}</td>
              <td>{PURPOSE[r.purpose] ?? r.purpose}</td>
              <td>{r.novel_title ?? '（已删除）'} / {r.chapter_title ?? '—'}</td>
              <td>{r.model}{r.mixed_models ? '（含评审模型，按转换模型估算）' : ''}</td>
              <td>{r.ok ? '成功' : '失败'}</td>
              <td>{int(r.input + r.output + r.cache_read + r.cache_write)}</td>
              <td>{usd(r.cost_usd)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
