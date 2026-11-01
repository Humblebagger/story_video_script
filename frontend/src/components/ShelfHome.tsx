import { useRef, useState } from 'react'
import { motion } from 'motion/react'
import { Plus } from 'lucide-react'
import { useI18n } from '@/i18n/core'
import { ago } from '@/lib/ago'
import { useMotionPresets } from '@/motion'
import { swatchFor } from '../styleLook'
import type { JobSummary, NovelParams, NovelSummary } from '../types'
import { StatusPill } from './common/StatusPill'
import { Help } from './common/Help'
import { DEFAULT_PARAMS } from './ParamsForm'
import { NewNovelComposer } from './NewNovelComposer'
import type { ComposerHandle, NewNovel } from './NewNovelComposer'
import { StylePicker } from './params/StylePicker'

interface Props {
  novels: NovelSummary[]
  running: JobSummary[]
  disabled: boolean
  onSubmit: (n: NewNovel) => void
  onOpenNovel: (id: string) => void
}

/** 书架首页：大标题与说明、新建主卡片、画面风格（与主卡片共用参数）、最近的小说 */
export function ShelfHome({ novels, running, disabled, onSubmit, onOpenNovel }: Props) {
  const { t } = useI18n()
  const m = useMotionPresets()
  const [params, setParams] = useState<NovelParams>(DEFAULT_PARAMS)
  const composer = useRef<ComposerHandle>(null)
  const liveIds = new Set(running.map((j) => j.novel_id).filter(Boolean))

  return (
    <div className="mx-auto flex w-full max-w-[1080px] flex-col gap-8 pb-10 pt-[8vh]">
      <motion.header className="flex flex-col items-center gap-2 text-center" {...m.enter}>
        <h1 className="text-[28px] font-semibold">{t('shelf.home.heading')}</h1>
        <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
          {t('shelf.home.sub')}<Help text={t('shelf.home.hint')} />
        </p>
      </motion.header>
      <NewNovelComposer ref={composer} disabled={disabled} onSubmit={onSubmit}
                        params={params} onParamsChange={setParams} />
      <section className="mx-auto flex w-full max-w-[760px] flex-col gap-3">
        <h2 className="text-sm font-semibold">{t('shelf.home.styles')}</h2>
        <StylePicker value={params} onChange={setParams} onCustom={() => composer.current?.openMore()} />
      </section>
      {novels.length > 0 && (
        <section className="flex flex-col gap-3" data-testid="shelf-recent">
          <h2 className="text-sm font-semibold">{t('shelf.home.recent')}</h2>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
            {novels.map((n, i) => (
              <motion.button key={n.id} type="button" data-testid="shelf-card" {...m.item(i)}
                             onClick={() => onOpenNovel(n.id)}
                             className="shelf-card flex flex-col overflow-hidden rounded-xl border bg-card text-left outline-none focus-visible:ring-2 focus-visible:ring-ring/50">
                <span className="shelf-card__cover relative block h-24 w-full" style={{ background: swatchFor(n.id) }}>
                  <span className="absolute bottom-2 left-3 z-10 text-[28px] font-semibold leading-none text-white">
                    {[...n.title][0] ?? ''}
                  </span>
                  {liveIds.has(n.id) && (
                    <StatusPill tone="live" className="absolute right-2 top-2 z-10 bg-background/80">{t('shelf.home.live')}</StatusPill>
                  )}
                </span>
                <span className="flex flex-col gap-0.5 p-3">
                  <span className="truncate text-sm font-medium">{n.title}</span>
                  <span className="text-xs text-muted-foreground">
                    {t('shelf.home.stats', { chapters: n.chapters, adopted: n.adopted, ago: ago(n.updated_at) })}
                  </span>
                </span>
              </motion.button>
            ))}
            <motion.button type="button" data-testid="shelf-new" {...m.item(novels.length)}
                           onClick={() => composer.current?.focusTitle()}
                           className="shelf-card flex min-h-[140px] flex-col items-center justify-center gap-1 rounded-xl border border-dashed text-sm text-muted-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring/50">
              <Plus className="size-5" />{t('shelf.home.newCard')}
            </motion.button>
          </div>
        </section>
      )}
    </div>
  )
}
