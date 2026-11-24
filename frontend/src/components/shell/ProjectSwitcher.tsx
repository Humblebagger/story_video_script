/** 顶栏左侧的项目切换器与章节切换：下拉里有搜索框、最近的小说、新建与全部小说。 */
import { useState } from 'react'
import { ChevronDown } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { useI18n } from '@/i18n/core'
import type { NovelSummary } from '@/types'

const RECENT = 8

export function ProjectSwitcher({ novels, currentId, meta, onOpen, onNew, onAll }: {
  novels: NovelSummary[]
  currentId: string | null
  /** 触发按钮上的小字（比例 · 画风） */
  meta?: string
  onOpen: (id: string) => void
  onNew: () => void
  onAll?: () => void
}) {
  const { t } = useI18n()
  const [q, setQ] = useState('')
  const cur = novels.find((n) => n.id === currentId)
  const key = q.trim().toLowerCase()
  const shown = [...novels]
    .sort((a, b) => (b.updated_at ?? '').localeCompare(a.updated_at ?? ''))
    .filter((n) => !key || n.title.toLowerCase().includes(key))
    .slice(0, RECENT)
  return (
    <DropdownMenu onOpenChange={(o) => { if (!o) setQ('') }}>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" className="project-switcher h-auto min-w-0 max-w-64 gap-2 px-2 py-1"
                aria-label={t('shell.switcher.label')} data-testid="project-switcher">
          <span className="flex min-w-0 flex-col items-start text-left leading-tight">
            <span className="max-w-full truncate text-sm font-medium">{cur?.title ?? t('brand.name')}</span>
            {meta && <span className="project-switcher__meta max-w-full truncate font-mono text-[11px] font-normal text-muted-foreground">{meta}</span>}
          </span>
          <ChevronDown className="size-3.5 shrink-0 opacity-60" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-72">
        <div className="p-1">
          <Input value={q} placeholder={t('shell.switcher.search')} aria-label={t('shell.switcher.search')}
                 onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.stopPropagation()} />
        </div>
        <DropdownMenuLabel className="text-xs text-muted-foreground">{t('shell.switcher.recent')}</DropdownMenuLabel>
        {shown.length === 0 && <p className="px-2 py-1.5 text-sm text-muted-foreground">{t('shell.switcher.noMatch')}</p>}
        {shown.map((n) => (
          <DropdownMenuItem key={n.id} data-testid="switch-item" onSelect={() => onOpen(n.id)}
                            className={n.id === currentId ? 'bg-accent' : ''}>
            <span className="min-w-0 flex-1 truncate">{n.title}</span>
          </DropdownMenuItem>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={onNew}>{t('shell.switcher.newNovel')}</DropdownMenuItem>
        {onAll && <DropdownMenuItem onSelect={onAll}>{t('shell.switcher.all')}</DropdownMenuItem>}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/** 「/ 第三章 ▾」：下拉是本小说的章节列表 */
export function ChapterCrumb({ chapters, currentId, onOpen }: {
  chapters: { id: string; title: string }[]
  currentId: string
  onOpen: (id: string) => void
}) {
  const { t } = useI18n()
  const cur = chapters.find((c) => c.id === currentId)
  return (
    <span className="app-shell__chapter-crumb contents">
      <span aria-hidden className="text-muted-foreground opacity-50">/</span>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="sm" className="min-w-0 max-w-48 gap-1 px-2" aria-label={t('shell.chapterSwitch')}
                  data-testid="chapter-crumb">
            <span className="truncate">{cur?.title ?? ''}</span>
            <ChevronDown className="size-3.5 shrink-0 opacity-60" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="max-h-80 w-56 overflow-y-auto">
          {chapters.map((c) => (
            <DropdownMenuItem key={c.id} onSelect={() => onOpen(c.id)} className={c.id === currentId ? 'bg-accent' : ''}>
              <span className="truncate">{c.title}</span>
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
    </span>
  )
}
