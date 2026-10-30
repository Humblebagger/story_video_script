import { adminJobs } from '../../api'
import { int, when } from './format'
import { useLoad } from './useLoad'

const clock = (s: number | null) =>
  (s == null ? '—' : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`)

/** 任务：运行中（内存任务表）与近 7 天失败（磁盘上的版本）。 */
export function JobsTab() {
  const { data, error, reload } = useLoad(adminJobs, [])
  if (error) return <p className="adm__err">{error}</p>
  if (!data) return <p className="adm__empty">加载中…</p>
  return (
    <section className="adm__sec">
      <div className="adm__bar">
        <h3 className="adm__h">运行中</h3>
        <button className="btn btn--sm btn--ghost" onClick={reload}>刷新</button>
      </div>
      {data.running.length === 0 ? <p className="adm__empty">没有运行中的任务</p> : (
        <table className="adm__table">
          <thead><tr><th>用户</th><th>小说 / 章节</th><th>状态</th><th>开始</th><th>已运行</th><th>字数</th></tr></thead>
          <tbody>
            {data.running.map((j) => (
              <tr key={j.id}>
                <td>{j.username ?? '—'}</td><td>{j.work_title ?? '—'} / {j.chapter ?? '—'}</td>
                <td>{j.status}</td><td>{when(j.created_at)}</td><td>{clock(j.elapsed_sec)}</td>
                <td>{int(j.chars)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <h3 className="adm__h">近 7 天失败</h3>
      {data.failed.length === 0 ? <p className="adm__empty">没有失败的任务</p> : (
        <table className="adm__table">
          <thead><tr><th>用户</th><th>小说 / 章节</th><th>开始</th><th>字数</th><th>尝试</th><th>报错</th></tr></thead>
          <tbody>
            {data.failed.map((j) => (
              <tr key={j.id}>
                <td>{j.username ?? '—'}</td>
                <td>{j.novel_title ?? '（已删除）'} / {j.chapter_title ?? '—'}</td>
                <td>{when(j.created_at)}</td><td>{int(j.chars)}</td><td>{j.attempts}</td>
                <td>
                  <details className="adm__err-detail">
                    <summary>{j.error.slice(0, 40)}{j.error.length > 40 ? '…' : ''}</summary>
                    <pre>{j.error}</pre>
                  </details>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}
