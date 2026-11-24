import { useRef } from 'react'
import { BookOpen, Clapperboard, FileUp, Type } from 'lucide-react'
import { motion } from 'motion/react'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/i18n/core'
import type { MsgKey } from '@/i18n/core'
import { fmtDuration } from '@/lib/fmt'
import { notice } from '@/lib/notice'
import { useMotionPresets } from '@/motion'
import { splitChapters } from '../chapters'
import type { Novel, NovelSummaryData } from '../types'
import { chapterStage } from '../workflow'

interface Props {
  novel: Novel
  summary: NovelSummaryData | null
  onOpenChapter: (cid: string) => void
  onNewChapter: () => void
  /** 导入整本：已按章节标记拆好，逐章新建 */
  onImport: (chapters: { title: string; text: string }[]) => void
  importing?: boolean
}

/** 原文与章节：章节表格（编号、标题、字数、版本数、步骤、操作）、新章节、导入整本 .txt */
export function ChaptersPage({ novel, summary, onOpenChapter, onNewChapter, onImport, importing }: Props) {
  const { t } = useI18n()
  const m = useMotionPresets()
  const fileRef = useRef<HTMLInputElement>(null)
  const sums = new Map((summary?.chapters ?? []).map((c) => [c.id, c]))
  const chapters = [...novel.chapters].sort((a, b) => a.order - b.order)
  const rows = chapters.map((c) => ({
    chapter: c,
    stage: chapterStage(c, sums.get(c.id), false),
  }))
  const finished = rows.filter((r) => r.stage === 'download').length
  const totalChars = chapters.reduce((n, c) => n + c.chars, 0)
  const stats = [
    {
      key: 'chapters',
      tone: 'blue',
      icon: BookOpen,
      label: t('overview.stat.chapters'),
      value: String(chapters.length),
    },
    {
      key: 'chars',
      tone: 'sand',
      icon: Type,
      label: t('chaptersPage.col.chars'),
      value: totalChars.toLocaleString(),
    },
    {
      key: 'finished',
      tone: 'rose',
      icon: Clapperboard,
      label: t('overview.stat.finished'),
      value: `${finished}/${chapters.length}`,
    },
  ]

  const pickFile = (f: File | undefined) => {
    if (!f) return
    if (!/\.txt$/i.test(f.name) && f.type !== 'text/plain') { notice.err(t('composer.onlyTxt')); return }
    f.text().then((text) => {
      const list = splitChapters(text, f.name.replace(/\.txt$/i, '') || t('composer.firstChapter'))
      if (list.length) onImport(list)
    }, () => notice.err(t('composer.readFail')))
  }

  return (
    <div className="chapters mx-auto flex w-full max-w-[1080px] flex-col gap-5">
      <div className="chapters__stats" aria-label={t('nav.chapters')}>
        {stats.map((s, i) => {
          const Icon = s.icon
          return (
            <article key={s.key} className="chapters__stat" data-tone={s.tone}>
              <span className="chapters__stat-top">
                <span className="chapters__stat-icon" aria-hidden><Icon /></span>
                <span className="chapters__stat-label">{s.label}</span>
                <span className="chapters__stat-index" aria-hidden>{String(i + 1).padStart(2, '0')}</span>
              </span>
              <b className="chapters__stat-value">{s.value}</b>
            </article>
          )
        })}
      </div>

      <div className="chapters__bar">
        <Button size="sm" data-testid="new-chapter" onClick={onNewChapter}>{t('novel.newChapter')}</Button>
        <Button size="sm" variant="outline" data-tour="import" data-testid="import-txt" disabled={importing}
                onClick={() => fileRef.current?.click()}>
          <FileUp aria-hidden />{t('chaptersPage.importWhole')}
        </Button>
        <input ref={fileRef} type="file" accept=".txt,text/plain" hidden data-testid="import-file"
               onChange={(e) => { pickFile(e.target.files?.[0]); e.target.value = '' }} />
        <p className="text-xs text-muted-foreground">{t('chaptersPage.importHint')}</p>
      </div>
      {chapters.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t('novel.empty')}</p>
      ) : (
        <div className="chtable">
          <div className="chtable__head" role="row">
            <span>{t('chaptersPage.col.no')}</span>
            <span>{t('chaptersPage.col.title')}</span>
            <span className="text-right">{t('chaptersPage.col.chars')}</span>
            <span className="text-right">{t('chaptersPage.col.versions')}</span>
            <span>{t('chaptersPage.col.step')}</span>
            <span />
          </div>
          {rows.map(({ chapter: c, stage }, i) => {
            const dur = fmtDuration(sums.get(c.id)?.duration_s)
            return (
              <motion.div key={c.id} className="chtable__row" data-testid="chapter-row" role="row"
                          data-stage={stage} data-empty={!c.chars || undefined} {...m.item(i)}
                          onClick={() => onOpenChapter(c.id)}>
                <span className="font-mono text-xs text-muted-foreground tabular-nums">{String(i + 1).padStart(2, '0')}</span>
                <span className="chtable__titlecell">
                  <span className="truncate text-sm font-medium">{c.title}</span>
                  <span className="chtable__sub" data-stage={stage}>
                    {t(`flow.steps.${stage}` as MsgKey)}
                    {dur && <span className="font-mono tabular-nums">{dur}</span>}
                  </span>
                </span>
                <span className="text-right font-mono text-xs tabular-nums">{c.chars}</span>
                <span className="text-right font-mono text-xs tabular-nums">{c.versions.length}</span>
                <span className="chtable__stage" data-stage={stage}>
                  <span className="chtable__stage-dot" aria-hidden />
                  <span>{t(`flow.steps.${stage}` as MsgKey)}</span>
                  {dur && <span className="chtable__dur font-mono tabular-nums">{dur}</span>}
                </span>
                <span className="text-right">
                  <Button size="sm" variant="ghost" data-testid="chapter-open"
                          onClick={(e) => { e.stopPropagation(); onOpenChapter(c.id) }}>
                    {t('chaptersPage.open')}
                  </Button>
                </span>
              </motion.div>
            )
          })}
        </div>
      )}
    </div>
  )
}
