/** ② 生成分镜：原文字数 +「修改原文」、本次的旁白模式与严格模式、生成中的进度入口。
 *  生成按钮是右下角主按钮，参数状态在 ChapterWorkflow 里。 */
import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/i18n/core'
import { NARRATION_MODE, label } from '@/labels'
import type { NarrationMode, Novel } from '@/types'

export function GenerateStep({ novel, chars, mode, strict, converting, onMode, onStrict, onEditSource, onOpenJob }: {
  novel: Novel
  /** 已保存原文的字数 */
  chars: number
  mode: NarrationMode | ''
  strict: boolean
  converting: boolean
  onMode: (m: NarrationMode | '') => void
  onStrict: (v: boolean) => void
  onEditSource: () => void
  /** 本章在跑的任务；没有就不显示「查看进度」 */
  onOpenJob?: () => void
}) {
  const { t } = useI18n()
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-3 text-[13px] text-muted-foreground">
        <span>{t('flow.source.chars', { n: chars })}</span>
        <Button size="sm" variant="ghost" onClick={onEditSource}>{t('flow.source.edit')}</Button>
      </div>
      <div className="chap__convert">
        <label className="field">
          <span>{t('flow.chapter.narration')}</span>
          <select value={mode} onChange={(e) => onMode(e.target.value as NarrationMode | '')}>
            <option value="">{t('flow.chapter.narrationInherit', {
              mode: label(NARRATION_MODE, novel.params.narration_mode ?? 'selective') })}</option>
            {Object.entries(NARRATION_MODE).map(([v, n]) => <option key={v} value={v}>{n}</option>)}
          </select>
        </label>
        <label className="check" title={t('flow.chapter.strictHint')}>
          <input type="checkbox" checked={strict} onChange={(e) => onStrict(e.target.checked)} />
          {t('flow.chapter.strict')}
        </label>
      </div>
      {converting && (
        <div role="status" className="flex items-center gap-3 text-sm">
          <Loader2 className="size-4 animate-spin motion-reduce:animate-none text-brand-to" aria-hidden />
          <span>{t('flow.primary.generating')}</span>
          {onOpenJob && <Button size="sm" variant="outline" onClick={onOpenJob}>{t('flow.progress')}</Button>}
        </div>
      )}
    </div>
  )
}
