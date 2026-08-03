import { JOB_STATUS, label } from '../labels'
import type { HistorySummary, JobSummary } from '../types'

interface Props {
  runs: HistorySummary[]
  /** 仍在后台跑的任务：关掉页面也不会停，这里可以随时点回去看进度 */
  running: JobSummary[]
  activeId: string | null
  loading: boolean
  onOpen: (id: string) => void
  onOpenJob: (id: string) => void
  onDelete: (id: string) => void
  onNew: () => void
}

/** 后端存的是 UTC ISO，这里按本地时区显示 */
function fmtTime(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const now = new Date()
  const sameDay = d.toDateString() === now.toDateString()
  const t = d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  return sameDay ? `今天 ${t}` : `${d.getMonth() + 1}/${d.getDate()} ${t}`
}

export function HistoryPanel({
  runs, running, activeId, loading, onOpen, onOpenJob, onDelete, onNew,
}: Props) {
  return (
    <aside className="hist">
      <div className="hist__head">
        <h2>历史记录</h2>
        <button className="btn btn--sm" onClick={onNew}>＋ 新转换</button>
      </div>

      {!!running.length && (
        <ul className="hist__list hist__list--run">
          {running.map((j) => (
            <li
              key={j.id}
              className={`hrun hrun--live${j.id === activeId ? ' is-on' : ''}`}
              onClick={() => onOpenJob(j.id)}
            >
              <div className="hrun__top">
                <span className="dot dot--live" />
                <b className="hrun__title">{j.work_title || '转换中'}</b>
              </div>
              {j.chapter && <p className="hrun__chapter">{j.chapter}</p>}
              <p className="hrun__last">{j.last_log ?? '排队中…'}</p>
            </li>
          ))}
        </ul>
      )}

      {loading && <p className="hist__empty">读取中…</p>}
      {!loading && !runs.length && (
        <p className="hist__empty">
          还没有记录。<br />
          转换完成后会自动落盘到后端 <code>runs/</code>，服务重启也不丢。
        </p>
      )}

      <ul className="hist__list">
        {runs.map((r) => (
          <li
            key={r.id}
            className={`hrun${r.id === activeId ? ' is-on' : ''}`}
            onClick={() => onOpen(r.id)}
          >
            <div className="hrun__top">
              <b className="hrun__title">{r.work_title || '未命名'}</b>
              <button
                className="hrun__del"
                title="删除这条记录"
                onClick={(e) => { e.stopPropagation(); onDelete(r.id) }}
              >
                ×
              </button>
            </div>
            {r.chapter && <p className="hrun__chapter">{r.chapter}</p>}
            <div className="hrun__meta">
              <span>{fmtTime(r.created_at)}</span>
              <span>{r.units} 句 · {r.episodes} 集 · {r.shots} 镜</span>
            </div>
            <div className="hrun__tags">
              {r.status === 'completed_with_warnings' && (
                <span className="tag tag--warn">质量告警</span>
              )}
              {r.status === 'succeeded' && (
                <span className="tag">{label(JOB_STATUS, r.status)}</span>
              )}
              {r.edited_at && <span className="tag tag--edit">已编辑</span>}
            </div>
          </li>
        ))}
      </ul>
    </aside>
  )
}
