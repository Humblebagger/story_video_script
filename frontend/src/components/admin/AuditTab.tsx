import { adminAudit } from '../../api'
import { ACTION, when } from './format'
import { useLoad } from './useLoad'

const show = (v: Record<string, unknown> | null) => (v ? JSON.stringify(v) : '—')

/** 审计：管理操作记录，最新在前。 */
export function AuditTab() {
  const { data, error } = useLoad(adminAudit, [])
  if (error) return <p className="adm__err">{error}</p>
  if (!data) return <p className="adm__empty">加载中…</p>
  if (!data.length) return <p className="adm__empty">还没有管理操作</p>
  return (
    <section className="adm__sec">
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
    </section>
  )
}
