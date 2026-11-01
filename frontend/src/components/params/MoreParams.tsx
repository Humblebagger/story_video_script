import { Input } from '@/components/ui/input'
import { useI18n } from '@/i18n/core'
import { cn } from '@/lib/utils'
import { NARRATION_MODE } from '../../labels'
import { COLOR_TONES, STYLE_PREFIXES, TARGET_PLATFORMS } from '../../presets'
import type { NarrationMode, NovelParams } from '../../types'
import { Field } from '../ParamsForm'
import { SelectOrCustom } from '../SelectOrCustom'

interface Props {
  value: NovelParams
  onChange: (next: NovelParams) => void
  prefixRef?: React.Ref<HTMLInputElement>
}

export function MoreParams({ value, onChange, prefixRef }: Props) {
  const { t } = useI18n()
  const set = <K extends keyof NovelParams>(k: K, v: NovelParams[K]) => onChange({ ...value, [k]: v })
  return (
    <div className="flex flex-col gap-4">
      <Field label={t('params.colorTone')}>
        <SelectOrCustom value={value.color_tone} options={COLOR_TONES}
                        onChange={(v) => set('color_tone', v)} placeholder={t('params.colorTonePh')} />
      </Field>
      <Field label={t('params.platform')}>
        <SelectOrCustom value={value.target_platform} options={TARGET_PLATFORMS}
                        onChange={(v) => set('target_platform', v)} />
      </Field>
      <Field label={t('params.stylePrefix')}>
        <Input ref={prefixRef} data-more="prefix" value={value.style_prefix}
               onChange={(e) => set('style_prefix', e.target.value)} />
        <span className="flex flex-wrap gap-1.5">
          {STYLE_PREFIXES.map((s) => (
            <button key={s.value} type="button" data-prefix-tag
                    onClick={() => set('style_prefix', s.value)}
                    className={cn('rounded-full border px-2 py-0.5 text-xs text-muted-foreground transition-colors hover:border-ring hover:text-foreground',
                                  value.style_prefix === s.value && 'border-primary text-foreground')}>
              {s.label}
            </button>
          ))}
        </span>
      </Field>
      <div className="flex flex-col gap-1.5 text-sm">
        <span id="more-narr-detail">{t('params.narrDetail')}</span>
        <div role="radiogroup" aria-labelledby="more-narr-detail" className="grid grid-cols-2 gap-1.5">
          {(Object.keys(NARRATION_MODE) as NarrationMode[]).map((k) => (
            <button key={k} type="button" role="radio" aria-checked={value.narration_mode === k} data-narr-mode={k}
                    onClick={() => set('narration_mode', k)}
                    className={cn('rounded-md border px-2 py-1.5 text-left text-xs outline-none transition-colors hover:border-ring focus-visible:ring-2 focus-visible:ring-ring/50',
                                  value.narration_mode === k && 'border-primary bg-accent')}>
              {NARRATION_MODE[k]}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
