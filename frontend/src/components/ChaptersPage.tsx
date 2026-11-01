import { useRef } from 'react'
import { FileUp } from 'lucide-react'
import { motion } from 'motion/react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
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

  const pickFile = (f: File | undefined) => {
    if (!f) return
    if (!/\.txt$/i.test(f.name) && f.type !== 'text/plain') { notice.err(t('composer.onlyTxt')); return }
    f.text().then((text) => {
      const list = splitChapters(text, f.name.replace(/\.txt$/i, '') || t('composer.firstChapter'))
      if (list.length) onImport(list)
    }, () => notice.err(t('composer.readFail')))
  }

  return (
    <div className="mx-auto flex w-full max-w-[1080px] flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
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
        <Card className="gap-0 p-0">
          <div className="chtable__head" role="row">
            <span>{t('chaptersPage.col.no')}</span>
            <span>{t('chaptersPage.col.title')}</span>
            <span className="text-right">{t('chaptersPage.col.chars')}</span>
            <span className="text-right">{t('chaptersPage.col.versions')}</span>
            <span>{t('chaptersPage.col.step')}</span>
            <span />
          </div>
          {chapters.map((c, i) => {
            const stage = chapterStage(c, sums.get(c.id), false)
            const dur = fmtDuration(sums.get(c.id)?.duration_s)
            return (
              <motion.div key={c.id} className="chtable__row" data-testid="chapter-row" role="row" {...m.item(i)}
                          onClick={() => onOpenChapter(c.id)}>
                <span className="font-mono text-xs text-muted-foreground tabular-nums">{String(i + 1).padStart(2, '0')}</span>
                <span className="min-w-0 truncate text-sm font-medium">{c.title}</span>
                <span className="text-right font-mono text-xs tabular-nums">{c.chars}</span>
                <span className="text-right font-mono text-xs tabular-nums">{c.versions.length}</span>
                <span className="text-xs">
                  {t(`flow.steps.${stage}` as MsgKey)}
                  {dur && <span className="ml-2 font-mono text-muted-foreground tabular-nums">{dur}</span>}
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
        </Card>
      )}
    </div>
  )
}
