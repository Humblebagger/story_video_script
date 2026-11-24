import { ArrowRight, MoreHorizontal, Trash2 } from 'lucide-react'
import { motion } from 'motion/react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useConfirm } from '@/components/common/ConfirmDialog'
import { useI18n } from '@/i18n/core'
import { errText } from '@/i18n/serverMsg'
import type { MsgKey } from '@/i18n/core'
import { assetThumb } from '@/lib/assetThumb'
import { costText, fmtDuration } from '@/lib/fmt'
import { notice } from '@/lib/notice'
import { cn } from '@/lib/utils'
import { useMotionPresets } from '@/motion'
import { deleteNovel } from '../api'
import { useStyleImage } from '../useStyleImage'
import { label, NARRATION_MODE } from '../labels'
import { ART_STYLES, TTS_VOICES } from '../presets'
import type { Section } from '../section'
import type { CharacterAsset, Novel, NovelSummaryData } from '../types'
import { mainCharacters } from '../mainCharacters'
import { chapterStage, STEPS } from '../workflow'
import type { StepId } from '../workflow'

interface Props {
  novel: Novel
  summary: NovelSummaryData | null
  /** 最近打开的章节（App 记在本机）；没有就取第一个还没做完的 */
  lastChapterId?: string | null
  onOpenChapter: (cid: string) => void
  onSection: (s: Section) => void
  onDeleted: () => void
}

const err = errText
const OUTLINE_LINES = 4
const STAT_TONES = ['rose', 'blue', 'violet', 'clay', 'slate', 'sand'] as const
const AVATAR_TONES = ['rose', 'blue', 'sand', 'violet'] as const

function Avatar({ c, tone }: { c: CharacterAsset; tone: (typeof AVATAR_TONES)[number] }) {
  const uri = assetThumb(c)
  return (
    <span className="ovw__avatar" data-testid="avatar" data-tone={tone} aria-hidden>
      {uri ? <img src={uri} alt="" /> : (c.name || c.id).slice(0, 1)}
    </span>
  )
}

/** 小说概览：继续、六张数字卡、故事梗概与主要人物、章节进度、待处理事项 */
export function NovelOverview({ novel, summary, lastChapterId, onOpenChapter, onSection, onDeleted }: Props) {
  const { t } = useI18n()
  const m = useMotionPresets()
  const styleUrl = useStyleImage(novel.id, novel.style_image?.hash)
  const [ask, confirmUi] = useConfirm()

  const remove = async () => {
    if (!(await ask({ title: t('confirm.novel.title', { title: novel.title }), body: t('confirm.novel.body'),
      action: t('confirm.delete'), danger: true }))) return
    void deleteNovel(novel.id).then(onDeleted)
      .catch((e) => notice.err(t('novel.failed', { what: t('novel.deleteNovel') }), err(e)))
  }

  const chapters = [...novel.chapters].sort((a, b) => a.order - b.order)
  const sums = new Map((summary?.chapters ?? []).map((c) => [c.id, c]))
  const stageOf = (id: string): StepId => {
    const c = chapters.find((x) => x.id === id)!
    return chapterStage(c, sums.get(id), false)
  }

  // 「继续」：最近打开的章节；没有记录取第一个还没到下载的章节；每章都到了下载就是全部完成
  const unfinished = chapters.find((c) => stageOf(c.id) !== 'download')
  const allDone = chapters.length > 0 && !unfinished
  const next = chapters.find((c) => c.id === lastChapterId) ?? unfinished

  const p = novel.params
  const artShort = (v?: string) => {
    const l = ART_STYLES.find((a) => a.value === v)?.label
    return l ? l.split(' ')[0] : v
  }
  const meta = [
    p.aspect_ratio, artShort(p.art_style),
    p.narration_mode ? label(NARRATION_MODE, p.narration_mode) : null,
    TTS_VOICES.find((v) => v.value === p.tts_voice)?.label ?? p.tts_voice,
  ].filter(Boolean).join(' · ')

  const assets = novel.memory.assets
  const assetCount = (['characters', 'locations', 'props', 'creatures'] as const)
    .reduce((n, k) => n + (assets[k]?.length ?? 0), 0)
  const shots = summary?.chapters.reduce((n, c) => n + (c.shots ?? 0), 0) ?? 0
  const finished = summary?.chapters.filter((c) => c.final === 'fresh').length ?? 0
  const dash = '—'
  const stats: [string, string][] = [
    [t('overview.stat.chapters'), String(chapters.length)],
    [t('overview.stat.adopted'), String(chapters.filter((c) => c.adopted_version).length)],
    [t('overview.stat.shots'), summary ? String(shots) : dash],
    [t('overview.stat.assets'), String(assetCount)],
    [t('overview.stat.finished'), summary ? `${finished}/${chapters.length}` : dash],
    [t('overview.stat.cost'), costText(summary?.cost)],
  ]

  const outline = novel.memory.plot.outline.split('\n').map((l) => l.trim()).filter(Boolean).slice(0, OUTLINE_LINES)
  const mains = mainCharacters(novel)
  const pending = novel.memory.lifecycle.filter((e) => e.status === 'proposed').length
  const stale = chapters.filter((c) => sums.get(c.id)?.final === 'stale')
  let i = 0

  return (
    <div className="ovw mx-auto flex w-full max-w-[1080px] flex-col gap-6">
      {confirmUi}
      <motion.header className="flex flex-wrap items-start gap-3" {...m.item(i++)}>
        <div className="min-w-0 flex-1">
          <h2 className="ovw__title" data-testid="ovw-title">{novel.title}</h2>
          <p className="mt-1 text-sm text-muted-foreground" data-testid="ovw-meta">{meta}</p>
        </div>
        <div className="ovw__head-actions">
          {chapters.length === 0 ? (
            <Button data-testid="ovw-continue" onClick={() => onSection('chapters')}>{t('overview.import')}</Button>
          ) : (
            <Button data-testid="ovw-continue" disabled={allDone}
                    onClick={() => next && onOpenChapter(next.id)}>
              <span className="ovw__continue-label">
                {allDone ? t('overview.allDone')
                  : t('overview.continue', { chapter: next!.title, step: t(`flow.steps.${stageOf(next!.id)}` as MsgKey) })}
              </span>
            </Button>
          )}
          <DropdownMenu modal={false}>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" aria-label={t('novel.more')}>
                <MoreHorizontal aria-hidden />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem variant="destructive" onSelect={() => { setTimeout(() => void remove(), 0) }}>
                <Trash2 aria-hidden />{t('novel.deleteNovel')}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </motion.header>

      {(pending > 0 || stale.length > 0) && (
        <motion.div className="flex flex-col gap-2" data-testid="ovw-pending" {...m.item(i++)}>
          {pending > 0 && (
            <div className="ovw__alert">
              <span className="min-w-0 flex-1 text-sm">{t('nav.pending', { n: pending })}</span>
              <Button size="sm" variant="ghost" onClick={() => onSection('memory')}>
                {t('overview.goConfirm')}<ArrowRight aria-hidden />
              </Button>
            </div>
          )}
          {stale.map((c) => (
            <div key={c.id} className="ovw__alert">
              <span className="min-w-0 flex-1 text-sm">{t('overview.stale', { title: c.title })}</span>
              <Button size="sm" variant="ghost" onClick={() => onOpenChapter(c.id)}>
                {t('overview.goHandle')}<ArrowRight aria-hidden />
              </Button>
            </div>
          ))}
        </motion.div>
      )}

      <motion.div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6" {...m.item(i++)}>
        {stats.map(([k, v], n) => {
          const [costMain, costAlt] = v.split(' · ')
          const splitCost = n === 5 && !!costAlt
          return (
            <Card key={k} data-testid="stat" data-tone={STAT_TONES[n]} className="ovw__stat gap-1 p-4">
              <span className="ovw__stat-label text-xs text-muted-foreground">{k}</span>
              <span className={cn('ovw__stat-value font-mono text-[22px] font-semibold tabular-nums leading-tight',
                                  splitCost && 'ovw__stat-value--cost')}>
                {splitCost ? (
                  <>
                    <span>{costMain}</span>
                    <span className="sr-only"> · </span>
                    <span className="ovw__stat-sub">{costAlt}</span>
                  </>
                ) : v}
              </span>
            </Card>
          )
        })}
      </motion.div>

      <motion.div className="grid grid-cols-1 gap-4 lg:grid-cols-[2fr_1fr]" {...m.item(i++)}>
        <Card className="ovw__panel gap-3 p-5" data-tone="blue" data-testid="ovw-outline">
          <div className="flex items-center justify-between gap-3">
            <h3 className="text-sm font-medium">{t('overview.outline')}</h3>
            {novel.style_image && (
              <button type="button" className="ovw__style" data-testid="ovw-style"
                      aria-label={t('style.ref.aria')} onClick={() => onSection('settings')}>
                {styleUrl && <img src={styleUrl} alt="" />}
              </button>
            )}
          </div>
          {outline.length ? (
            <div className="flex flex-col gap-1.5 text-sm leading-relaxed">
              {outline.map((l, k) => <p key={k} data-testid="outline-line">{l}</p>)}
            </div>
          ) : (
            <div className="ovw__outline-empty">
              <span className="ovw__outline-mark" aria-hidden>STORY / OUTLINE</span>
              <p className="text-sm text-muted-foreground">{t('overview.noOutline')}</p>
              <Button size="sm" variant="outline" onClick={() => onSection('memory')}>{t('overview.fillIn')}</Button>
            </div>
          )}
        </Card>
        <Card className="ovw__panel gap-3 p-5" data-tone="rose" data-testid="ovw-mains">
          <h3 className="text-sm font-medium">{t('overview.mains')}</h3>
          {mains.length === 0 && <p className="text-sm text-muted-foreground">{t('overview.noMains')}</p>}
          <ul className="flex flex-col gap-2">
            {mains.map((c, n) => (
              <li key={c.id} data-testid="main-char" className="flex items-center gap-3">
                <Avatar c={c} tone={AVATAR_TONES[n % AVATAR_TONES.length]} />
                <span className="min-w-0 flex-1 truncate text-sm">{c.name}</span>
                <span className="font-mono text-xs text-muted-foreground tabular-nums">{c.id}</span>
              </li>
            ))}
          </ul>
        </Card>
      </motion.div>

      <motion.div {...m.item(i++)}>
        <Card className="ovw__panel gap-1 p-5" data-tone="sand" data-testid="ovw-progress">
          <h3 className="mb-2 text-sm font-medium">{t('overview.progress')}</h3>
          {chapters.length === 0 && <p className="text-sm text-muted-foreground">{t('novel.empty')}</p>}
          {chapters.map((c, k) => {
            const stage = stageOf(c.id)
            const at = stage === 'download' ? STEPS.length : STEPS.indexOf(stage)
            const dur = fmtDuration(sums.get(c.id)?.duration_s)
            return (
              <button key={c.id} type="button" className="ovw__row" data-testid="progress-row" data-stage={stage}
                      onClick={() => onOpenChapter(c.id)}>
                <span className="font-mono text-xs text-muted-foreground tabular-nums">{String(k + 1).padStart(2, '0')}</span>
                <span className="min-w-0 flex-1 truncate text-left text-sm" title={c.title}>{c.title}</span>
                <span className="ovw__cells" aria-hidden>
                  {STEPS.map((s, n) => (
                    <span key={s} data-testid="cell" data-state={n < at ? 'done' : n === at ? 'current' : 'todo'} />
                  ))}
                </span>
                <span className={cn('w-20 text-right text-xs text-muted-foreground')}>
                  {t(`flow.steps.${stage}` as MsgKey)}
                </span>
                <span className="w-12 text-right font-mono text-xs tabular-nums text-muted-foreground">{dur ?? dash}</span>
              </button>
            )
          })}
        </Card>
      </motion.div>
    </div>
  )
}
