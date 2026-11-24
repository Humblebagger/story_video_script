import { useRef, useState } from 'react'
import { motion } from 'motion/react'
import { Plus, Sparkles } from 'lucide-react'
import { useI18n } from '@/i18n/core'
import { ago } from '@/lib/ago'
import { useMotionPresets } from '@/motion'
import type { JobSummary, NovelParams, NovelSummary } from '../types'
import { StatusPill } from './common/StatusPill'
import { Help } from './common/Help'
import { DEFAULT_PARAMS } from './ParamsForm'
import { NewNovelComposer } from './NewNovelComposer'
import type { ComposerHandle, NewNovel } from './NewNovelComposer'
import { StylePicker } from './params/StylePicker'
import { Button } from './ui/button'

interface Props {
  novels: NovelSummary[]
  running: JobSummary[]
  disabled: boolean
  onSubmit: (n: NewNovel) => void
  onOpenNovel: (id: string) => void
}

const coverTones = ['clay', 'blue', 'sand', 'violet'] as const
function coverTone(id: string) {
  // FNV-1a 再混一次低位：相邻或相似的 id 不容易落到同一种封面色。
  let hash = 2166136261
  for (const character of id) {
    hash ^= character.codePointAt(0)!
    hash = Math.imul(hash, 16777619)
  }
  hash ^= hash >>> 16
  hash = Math.imul(hash, 2246822507)
  hash ^= hash >>> 13
  return coverTones[(hash >>> 0) % coverTones.length]
}

/** 书架首页：大标题与说明、新建主卡片、画面风格（与主卡片共用参数）、最近的小说 */
export function ShelfHome({ novels, running, disabled, onSubmit, onOpenNovel }: Props) {
  const { t } = useI18n()
  const m = useMotionPresets()
  const [params, setParams] = useState<NovelParams>(DEFAULT_PARAMS)
  const composer = useRef<ComposerHandle>(null)
  const liveIds = new Set(running.map((j) => j.novel_id).filter(Boolean))

  return (
    <div className="shelf-home mx-auto flex w-full max-w-[1320px] flex-col gap-10 pb-10 pt-3 sm:pt-6">
      <motion.header className="flex flex-col gap-2" {...m.enter}>
        <h1 className="shelf-home__title">{t('shelf.home.heading')}</h1>
        <p className="flex items-center gap-1.5 text-sm text-muted-foreground sm:text-base">
          {t('shelf.home.sub')}<Help text={t('shelf.home.hint')} />
        </p>
      </motion.header>
      <NewNovelComposer className="max-w-none" ref={composer} disabled={disabled} onSubmit={onSubmit}
                        params={params} onParamsChange={setParams} />
      <section className="shelf-home__styles flex min-w-0 flex-col gap-3">
        <h2 className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">{t('shelf.home.styles')}</h2>
        <StylePicker className="flex-nowrap" aria-label={t('shelf.home.styles')} value={params} onChange={setParams} onCustom={() => composer.current?.openMore()} />
      </section>
      {novels.length > 0 && (
        <section className="flex flex-col gap-3" data-testid="shelf-recent">
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">{t('shelf.home.recent')}</h2>
            <Button type="button" variant="outline" size="sm" data-testid="shelf-new"
                    onClick={() => composer.current?.focusTitle()}>
              <Plus className="size-4" />{t('shelf.home.newCard')}
            </Button>
          </div>
          <div className="shelf-home__projects">
            {novels.map((n, i) => {
              const when = ago(n.updated_at)
              return (
              <motion.button key={n.id} type="button" data-testid="shelf-card" {...m.item(i)}
                             onClick={() => onOpenNovel(n.id)}
                             className="shelf-card group flex min-w-0 flex-col overflow-hidden rounded-xl bg-card text-left outline-none focus-visible:ring-2 focus-visible:ring-ring/50">
                <span data-cover-tone={coverTone(n.id)} className="shelf-card__cover relative flex aspect-video w-full items-end p-4">
                  <span className="absolute left-4 top-4 flex items-center gap-2 font-mono text-[10px] font-medium uppercase tracking-[0.2em]">
                    <Sparkles className="size-3" aria-hidden />{t('shelf.home.coverLabel')}
                  </span>
                  <span aria-hidden className="shelf-card__monogram relative z-10 text-6xl font-semibold leading-none tracking-tight">
                    {[...n.title][0] ?? ''}
                  </span>
                  <span aria-hidden className="relative z-10 mb-1 ml-auto font-mono text-xs tabular-nums">
                    {String(n.chapters).padStart(2, '0')} / CH
                  </span>
                  {liveIds.has(n.id) && (
                    <StatusPill tone="live" className="absolute right-2 top-2 z-10 bg-background/80">{t('shelf.home.live')}</StatusPill>
                  )}
                </span>
                <span className="flex w-full min-w-0 flex-1 flex-col gap-1 p-3">
                  <span className="line-clamp-2 break-words text-sm font-medium" title={n.title}>{n.title}</span>
                  <span className="text-xs text-muted-foreground">
                    {t('shelf.home.stats', { chapters: n.chapters, adopted: n.adopted })}
                  </span>
                  {when && <span className="mt-auto pt-2 text-xs text-muted-foreground">{when}</span>}
                </span>
              </motion.button>
              )
            })}
          </div>
        </section>
      )}
    </div>
  )
}
