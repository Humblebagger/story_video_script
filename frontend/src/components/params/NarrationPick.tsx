import { Clapperboard, Mic } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { useI18n } from '@/i18n/core'
import { cn } from '@/lib/utils'
import { NARRATION_MODE } from '../../labels'
import type { NovelParams } from '../../types'

interface Props { value: NovelParams; onChange: (next: NovelParams) => void }

/** 旁白解说（selective / original_text / condensed）与剧情演绎（none）二选一 */
export function NarrationPick({ value, onChange }: Props) {
  const { t } = useI18n()
  const mode = value.narration_mode
  const narrated = mode !== 'none'
  const sub = mode === 'original_text' || mode === 'condensed'
  const cards = [
    { on: narrated, icon: <Mic className="size-4" />, key: 'narrated', next: sub ? mode : 'selective' as const },
    { on: !narrated, icon: <Clapperboard className="size-4" />, key: 'acted', next: 'none' as const },
  ]
  return (
    <div role="radiogroup" aria-label={t('params.narration')} className="grid grid-cols-2 gap-2">
      {cards.map((c) => (
        <button key={c.key} type="button" role="radio" aria-checked={c.on} data-narration={c.key}
                onClick={() => onChange({ ...value, narration_mode: c.next })}
                className={cn('flex flex-col gap-1 rounded-xl border-2 p-3 text-left outline-none transition-colors hover:border-ring focus-visible:ring-2 focus-visible:ring-ring/50',
                              c.on ? 'border-primary' : 'border-border')}>
          <span className="flex items-center gap-1.5 text-sm font-semibold">
            {c.icon}{t(`params.narr.${c.key}` as 'params.narr.narrated')}
            {c.key === 'narrated' && c.on && sub && (
              <Badge variant="secondary" data-narration-sub>{NARRATION_MODE[mode]}</Badge>
            )}
          </span>
          <span className="text-xs text-muted-foreground">{t(`params.narr.${c.key}Desc` as 'params.narr.narratedDesc')}</span>
        </button>
      ))}
    </div>
  )
}
