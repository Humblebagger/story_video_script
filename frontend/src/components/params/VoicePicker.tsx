import { Check } from 'lucide-react'
import { useI18n } from '@/i18n/core'
import type { MsgKey } from '@/i18n/core'
import { cn } from '@/lib/utils'
import { TTS_VOICES } from '../../presets'
import type { NovelParams } from '../../types'

interface Props { value: NovelParams; onChange: (next: NovelParams) => void }

export function VoicePicker({ value, onChange }: Props) {
  const { t } = useI18n()
  return (
    <div role="radiogroup" aria-label={t('params.voice')} className="flex w-64 flex-col gap-0.5">
      {TTS_VOICES.map((v) => {
        const on = value.tts_voice === v.value
        return (
          <button key={v.value} type="button" role="radio" aria-checked={on} data-voice={v.value}
                  onClick={() => onChange({ ...value, tts_voice: v.value })}
                  className={cn('flex items-center gap-2 rounded-md px-2 py-1.5 text-left outline-none transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring/50',
                                on && 'bg-accent')}>
            <span className="min-w-0 flex-1">
              <span className="block text-sm font-medium">{v.label}</span>
              <span className="block text-xs text-muted-foreground">{t(`params.voiceDesc.${v.value}` as MsgKey)}</span>
            </span>
            {on && <Check className="size-4 text-primary" />}
          </button>
        )
      })}
    </div>
  )
}
