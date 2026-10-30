import { adminAudit } from '../../api'
import { ACTION, when } from './format'
import { useLoad } from './useLoad'

const show = (v: Record<string, unknown> | null) => (v ? JSON.stringify(v) : '—')

/** 审计：管理操作记录，最新在前。 */
export function AuditTab() {
  const { data, error, reload } = useLoad(adminAudit, [])
  const bar = (
    <div className="adm__bar">
      <button className="btn btn--sm btn--ghost" onClick={reload}>刷新</button>
    </div>
  )
  let body
  if (error) body = <p className="adm__err">{error}</p>
  else if (!data) body = <p className="adm__empty">加载中…</p>
  else if (!data.length) body = <p className="adm__empty">还没有管理操作</p>
  else body = (
    <table className="adm__table">
      <thead><tr><th>时间</th><th>管理员</th><th>操作</th><th>对象</th><th>之前</th><th>之后</th></tr></thead>
      <tbody>
        {data.map((a, i) => (
          <tr key={i}>
            <td>{when(a.at)}</td><td>{a.admin}</td><td>{ACTION[a.action] ?? a.action}</td>
            <td>{a.target ?? '—'}</td><td>{show(a.before)}</td><td>{show(a.after)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
  return <section className="adm__sec">{bar}{body}</section>
}
