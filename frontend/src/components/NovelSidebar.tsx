import { useState } from 'react'
import { Plus } from 'lucide-react'
import { useI18n } from '@/i18n/core'
import { JOB_STATUS, label } from '../labels'
import type { JobSummary, Novel, NovelSummary } from '../types'
import { JobProgress } from './JobProgress'
import { EmptyState } from './common/EmptyState'
import { Badge } from './ui/badge'
import { Button } from './ui/button'
import { Skeleton } from './ui/skeleton'

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
  /** 书架为空时的引导按钮：和外壳里「新建小说」同一个入口 */
  onNewNovel: () => void
}

/** 侧栏：小说（总会话）→ 章节（二级会话）。章节上标出采用版与在跑的转换 */
export function NovelSidebar({
  novels, novel, chapterId, running, activeJobId, loading,
  onOpenNovel, onOpenChapter, onOpenJob, onNewChapter, onNewNovel,
}: Props) {
  const { t } = useI18n()
  const [query, setQuery] = useState('')
  const q = query.trim().toLowerCase()
  const shown = q ? novels.filter((n) => n.title.toLowerCase().includes(q)) : novels
  const liveChapter = new Set(running.map((j) => j.chapter_id).filter(Boolean))

  return (
    <aside className="hist">
      <div className="hist__head">
        <h2>{t('shell.shelf.title')}</h2>
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
                <b className="hrun__title">{j.work_title || t('shell.shelf.converting')}</b>
              </div>
              {j.chapter && <p className="hrun__chapter">{j.chapter}</p>}
              {j.progress
                ? <JobProgress progress={j.progress} compact />
                : <p className="hrun__last">{j.last_log ?? t('shell.shelf.queued')}</p>}
            </li>
          ))}
        </ul>
      )}

      {novels.length > 5 && (
        <input className="hist__search" value={query} placeholder={t('shell.shelf.search')}
               aria-label={t('shell.shelf.search')}
               onChange={(e) => setQuery(e.target.value)} />
      )}
      {loading && (
        <div className="flex flex-col gap-2" data-testid="shelf-loading" role="status" aria-label={t('common.loading')}>
          {[0, 1, 2].map((i) => <Skeleton key={i} className="h-8" />)}
        </div>
      )}
      {!loading && !novels.length && (
        <EmptyState title={t('shell.shelf.emptyTitle')}
                    action={<Button size="sm" onClick={onNewNovel}><Plus />{t('shell.newNovel')}</Button>} />
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
                  <span>{t('shell.shelf.chapterStats', { chapters: n.chapters, adopted: n.adopted })}</span>
                  <span>{t('shell.shelf.cards', { n: Object.values(n.asset_counts).reduce((a, b) => a + b, 0) })}</span>
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
                          ? <Badge variant="secondary" className="bg-accent text-accent-foreground">{t('shell.shelf.chapterConverting')}</Badge>
                          : v
                            ? <Badge variant="secondary" title={t('shell.shelf.adoptedTitle', { id: v.id })}>{
                                t('shell.shelf.adopted', { n: c.versions.length - c.versions.indexOf(v) })}</Badge>
                            : c.latest_status
                              ? <Badge variant="outline" className="border-dashed text-muted-foreground">{label(JOB_STATUS, c.latest_status)}</Badge>
                              : <Badge variant="outline" className="border-dashed text-muted-foreground">{t('shell.shelf.notConverted')}</Badge>}
                      </li>
                    )
                  })}
                  <li className="hchap__item hchap__item--new" onClick={onNewChapter}>{t('shell.shelf.newChapter')}</li>
                </ul>
              )}
            </li>
          )
        })}
      </ul>
    </aside>
  )
}
