import { useState } from 'react'
import { JOB_STATUS, label } from '../labels'
import type { JobSummary, Novel, NovelSummary } from '../types'
import { JobProgress } from './JobProgress'

interface Props {
  novels: NovelSummary[]
  /** 当前打开的小说（含章节列表）；其余小说只显示标题 */
  novel: Novel | null
  chapterId: string | null
  /** 仍在后台跑的任务：关掉页面也不会停，这里可以随时点回去看进度 */
  running: JobSummary[]
  activeJobId: string | null
  loading: boolean
  onOpenNovel: (nid: string) => void
  onOpenChapter: (cid: string) => void
  onOpenJob: (job: JobSummary) => void
  onNewChapter: () => void
}

/** 侧栏：小说（总会话）→ 章节（二级会话）。章节上标出采用版与在跑的转换 */
export function NovelSidebar({
  novels, novel, chapterId, running, activeJobId, loading,
  onOpenNovel, onOpenChapter, onOpenJob, onNewChapter,
}: Props) {
  const [query, setQuery] = useState('')
  const q = query.trim().toLowerCase()
  const shown = q ? novels.filter((n) => n.title.toLowerCase().includes(q)) : novels
  const liveChapter = new Set(running.map((j) => j.chapter_id).filter(Boolean))

  return (
    <aside className="hist">
      <div className="hist__head">
        <h2>小说</h2>
      </div>

      {!!running.length && (
        <ul className="hist__list hist__list--run">
          {running.map((j) => (
            <li
              key={j.id}
              className={`hrun hrun--live${j.id === activeJobId ? ' is-on' : ''}`}
              onClick={() => onOpenJob(j)}
            >
              <div className="hrun__top">
                <span className="dot dot--live" />
                <b className="hrun__title">{j.work_title || '转换中'}</b>
              </div>
              {j.chapter && <p className="hrun__chapter">{j.chapter}</p>}
              {j.progress
                ? <JobProgress progress={j.progress} compact />
                : <p className="hrun__last">{j.last_log ?? '排队中…'}</p>}
            </li>
          ))}
        </ul>
      )}

      {novels.length > 5 && (
        <input className="hist__search" value={query} placeholder="搜索小说"
               onChange={(e) => setQuery(e.target.value)} />
      )}
      {loading && <p className="hist__empty">读取中…</p>}
      {!loading && !novels.length && (
        <p className="hist__empty">
          还没有小说。<br />
          一部小说是一个总会话：长期记住资产库、人物状态、主线剧情与创作限制；
          每一章是其中的一次转换。
        </p>
      )}

      <ul className="hist__list">
        {shown.map((n) => {
          const open = novel?.id === n.id
          return (
            <li key={n.id} className={`hnovel${open ? ' is-open' : ''}`}>
              <div className={`hrun${open && !chapterId ? ' is-on' : ''}`}
                   onClick={() => onOpenNovel(n.id)}>
                <div className="hrun__top">
                  <b className="hrun__title">{n.title}</b>
                </div>
                <div className="hrun__meta">
                  <span>{n.chapters} 章 · 已采用 {n.adopted}</span>
                  <span>{Object.values(n.asset_counts).reduce((a, b) => a + b, 0)} 张卡</span>
                </div>
              </div>
              {open && novel && (
                <ul className="hchap">
                  {novel.chapters.map((c) => {
                    const v = c.versions.find((x) => x.id === c.adopted_version)
                    return (
                      <li key={c.id}
                          className={`hchap__item${c.id === chapterId ? ' is-on' : ''}`}
                          onClick={() => onOpenChapter(c.id)}>
                        <span className="hchap__title">{c.title}</span>
                        {liveChapter.has(c.id)
                          ? <span className="tag tag--nar">转换中…</span>
                          : v
                            ? <span className="tag" title={`采用版 ${v.id}`}>✓ 采用 v{
                                c.versions.length - c.versions.indexOf(v)}</span>
                            : c.latest_status
                              ? <span className="tag tag--ghost">{label(JOB_STATUS, c.latest_status)}</span>
                              : <span className="tag tag--ghost">未转换</span>}
                      </li>
                    )
                  })}
                  <li className="hchap__item hchap__item--new" onClick={onNewChapter}>＋ 新章节</li>
                </ul>
              )}
            </li>
          )
        })}
      </ul>
    </aside>
  )
}
