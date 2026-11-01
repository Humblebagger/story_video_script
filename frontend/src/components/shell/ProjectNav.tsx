/** 左栏项目导航：上半是小说层九个分区（带数量与待确认提示点），下半是章节进度卡片（编号、标题、所在步骤、时长、进度细线）。
 *  收起时只剩图标与章节编号方块，名字放进提示。 */
import { useState } from 'react'
import type { ComponentType, ReactNode } from 'react'
import {
  BookText, LayoutDashboard, MapPin, Package, PawPrint, Plus, ScrollText, Search, Settings2, ShieldAlert, Users,
} from 'lucide-react'
import { StatusPill } from '@/components/common/StatusPill'
import { Input } from '@/components/ui/input'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useI18n } from '@/i18n/core'
import type { MsgKey } from '@/i18n/core'
import type { Section } from '@/section'
import type { JobSummary, Novel, NovelSummaryData } from '@/types'
import { chapterStage, stageFraction } from '@/workflow'
import { useSidebarCollapsed } from './topbarSlot'

const ICON: Record<Section, ComponentType<{ className?: string }>> = {
  overview: LayoutDashboard, chapters: BookText, characters: Users, locations: MapPin, props: Package,
  creatures: PawPrint, memory: ScrollText, constraints: ShieldAlert, settings: Settings2,
}
const ORDER: Section[] = [
  'overview', 'chapters', 'characters', 'locations', 'props', 'creatures', 'memory', 'constraints', 'settings',
]
/** 章节多于这个数才出现搜索框 */
const SEARCH_FROM = 8

function fmtDuration(s: number | null | undefined): string | null {
  if (s == null || !(s > 0)) return null
  const n = Math.round(s)
  return `${Math.floor(n / 60)}:${String(n % 60).padStart(2, '0')}`
}

function Tip({ on, label, children }: { on: boolean; label: string; children: ReactNode }) {
  if (!on) return <>{children}</>
  return (
    <Tooltip>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent side="right">{label}</TooltipContent>
    </Tooltip>
  )
}

export function ProjectNav({ novel, section, chapterId, summary, running, onSection, onOpenChapter, onNewChapter }: {
  novel: Novel
  /** 当前高亮的分区；打开章节时传 null */
  section: Section | null
  chapterId: string | null
  summary: NovelSummaryData | null
  running: JobSummary[]
  onSection: (s: Section) => void
  onOpenChapter: (cid: string) => void
  onNewChapter: () => void
}) {
  const { t } = useI18n()
  const collapsed = useSidebarCollapsed()
  const [query, setQuery] = useState('')
  const assets = novel.memory.assets
  const count = (s: Section): number | null => {
    switch (s) {
      case 'chapters': return novel.chapters.length
      case 'characters': case 'locations': case 'props': case 'creatures': return (assets[s] ?? []).length
      case 'constraints': return novel.memory.constraints.length
      default: return null
    }
  }
  const pending = novel.memory.lifecycle.filter((e) => e.status === 'proposed').length
  const sums = new Map((summary?.chapters ?? []).map((c) => [c.id, c]))
  const live = new Set(running.map((j) => j.chapter_id).filter(Boolean))
  const chapters = [...novel.chapters].sort((a, b) => a.order - b.order)
  const q = query.trim().toLowerCase()
  const shown = chapters.map((c, i) => ({ c, i })).filter(({ c }) => !q || c.title.toLowerCase().includes(q))

  return (
    <nav className="pnav" aria-label={t('nav.label')} data-collapsed={collapsed ? '' : undefined}>
      <ul className="pnav__items">
        {ORDER.map((s) => {
          const Icon = ICON[s]
          const n = count(s)
          const name = t(`nav.${s}` as MsgKey)
          return (
            <li key={s}>
              <Tip on={collapsed} label={name}>
                <button type="button" className="pnav__item" data-testid="nav-item" data-section={s}
                        data-empty={n === 0 ? '' : undefined} aria-label={collapsed ? name : undefined}
                        aria-current={section === s ? 'page' : undefined} onClick={() => onSection(s)}>
                  <Icon className="pnav__icon size-4 shrink-0" />
                  {!collapsed && <span className="pnav__name">{name}</span>}
                  {s === 'memory' && pending > 0 && (
                    <span className="pnav__dot" data-testid="nav-badge" title={t('nav.pending', { n: pending })} />
                  )}
                  {!collapsed && n !== null && <span className="pnav__count font-mono tabular-nums">{n}</span>}
                </button>
              </Tip>
            </li>
          )
        })}
      </ul>

      <div className="pnav__chead">
        {!collapsed && <h3>{t('nav.chapterList')}</h3>}
        <Tip on={collapsed} label={t('nav.newChapter')}>
          <button type="button" className="pnav__add" data-testid="nav-new-chapter" aria-label={t('nav.newChapter')}
                  onClick={onNewChapter}>
            <Plus className="size-4" />
          </button>
        </Tip>
      </div>
      {!collapsed && chapters.length > SEARCH_FROM && (
        <div className="pnav__search">
          <Search className="size-3.5" aria-hidden />
          <Input value={query} placeholder={t('nav.searchChapters')} aria-label={t('nav.searchChapters')}
                 data-testid="nav-search" onChange={(e) => setQuery(e.target.value)} />
        </div>
      )}
      <ul className="pnav__chapters">
        {shown.map(({ c, i }) => {
          const generating = live.has(c.id)
          const sum = sums.get(c.id)
          const stage = chapterStage(c, sum, generating)
          const dur = fmtDuration(sum?.duration_s)
          const num = String(i + 1).padStart(2, '0')
          const stageName = t(`flow.steps.${stage}` as MsgKey)
          return (
            <li key={c.id}>
              <Tip on={collapsed} label={`${num} ${c.title}`}>
                <button type="button" className="pcard" data-testid="chapter-card" data-stage={stage}
                        aria-label={collapsed ? c.title : undefined}
                        aria-current={c.id === chapterId ? 'true' : undefined} onClick={() => onOpenChapter(c.id)}>
                  <span className="pcard__num font-mono tabular-nums">{num}</span>
                  {!collapsed && (
                    <span className="pcard__body">
                      <span className="pcard__title">{c.title}</span>
                      <span className="pcard__meta">
                        {generating
                          ? <StatusPill tone="live">{stageName}</StatusPill>
                          : <span className="pcard__stage">{stageName}</span>}
                        {dur && <span className="pcard__dur font-mono tabular-nums">{dur}</span>}
                      </span>
                    </span>
                  )}
                  <span className="pcard__bar" aria-hidden>
                    <span className="pcard__fill" data-testid="chapter-progress"
                          style={{ width: `${stageFraction(stage) * 100}%` }} />
                  </span>
                </button>
              </Tip>
            </li>
          )
        })}
        {!!q && !shown.length && <li className="pnav__none">{t('nav.noMatch')}</li>}
      </ul>
    </nav>
  )
}

