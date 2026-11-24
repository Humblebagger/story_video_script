/** ② 生成分镜：原文字数 +「修改原文」、本次的旁白模式与严格模式、生成中的进度入口。
 *  生成按钮是右下角主按钮，参数状态在 ChapterWorkflow 里。 */
import { AudioLines, FileText, Loader2, ShieldCheck } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { SelectMenu } from '@/components/ui/select'
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
    <div className="gen">
      <header className="gen__head">
        <div className="gen__head-text">
          <span className="gen__eyebrow" aria-hidden>SETUP / 02</span>
          <h2>{t('flow.setup.title')}</h2>
        </div>
        <span className="gen__ready">{t('flow.setup.ready')}</span>
      </header>
      <div className="gen__grid">
        <section className="gen__panel gen__panel--source">
          <span className="gen__panel-eyebrow"><FileText aria-hidden />SOURCE</span>
          <span className="gen__source-value">{chars.toLocaleString()}</span>
          <span className="gen__source-unit">{t('flow.setup.source')}</span>
          <p className="gen__panel-hint">{t('flow.setup.sourceHint')}</p>
          <Button size="sm" variant="outline" className="gen__edit" onClick={onEditSource}>
            {t('flow.source.edit')}
          </Button>
        </section>
        <div className="gen__panel gen__panel--mode">
          <span className="gen__panel-eyebrow"><AudioLines aria-hidden />NARRATION</span>
          <span className="gen__panel-label">{t('flow.chapter.narration')}</span>
          <SelectMenu
            className="ui-select"
            ariaLabel={t('flow.chapter.narration')}
            value={mode}
            onChange={(v) => onMode(v as NarrationMode | '')}
            options={[
              {
                value: '',
                label: t('flow.chapter.narrationInherit', {
                  mode: label(NARRATION_MODE, novel.params.narration_mode ?? 'selective'),
                }),
              },
              ...Object.entries(NARRATION_MODE).map(([v, n]) => ({ value: v, label: n })),
            ]}
          />
          <p className="gen__panel-hint">{t('flow.setup.modeHint')}</p>
        </div>
        <label className={`gen__panel gen__panel--strict${strict ? ' is-on' : ''}`}>
          <span className="gen__panel-eyebrow"><ShieldCheck aria-hidden />QUALITY</span>
          <span className="gen__check">
            <Checkbox checked={strict} onChange={(e) => onStrict(e.target.checked)} />
            <span>{t('flow.chapter.strict')}</span>
          </span>
          <p className="gen__panel-hint">{t('flow.setup.strictHint')}</p>
        </label>
      </div>
      {converting && (
        <div role="status" className="gen__live">
          <Loader2 className="size-4 animate-spin motion-reduce:animate-none text-brand-to" aria-hidden />
          <span className="min-w-0 flex-1">{t('flow.primary.generating')}</span>
          {onOpenJob && <Button size="sm" variant="outline" onClick={onOpenJob}>{t('flow.progress')}</Button>}
        </div>
      )}
    </div>
  )
}
