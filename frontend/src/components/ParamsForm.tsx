import { FormField } from '@/components/ui/form-field'
import type { NovelParams } from '../types'

/** 默认值与 backend/pipeline/convert.py 的 ConvertParams 逐字对齐 */
export const DEFAULT_PARAMS: NovelParams = {
  style_prefix: '电影感写实风格，自然光影',
  art_style: 'realistic',
  color_tone: '自然色调',
  aspect_ratio: '9:16',
  target_platform: '抖音',
  narration_mode: 'selective',
  tts_voice: 'male_mature',
}

export function Field({ label, wide, children }: {
  label: string; wide?: boolean; children: React.ReactNode
}) {
  return (
    <FormField label={label} asLabel className={wide ? 'field field--wide' : 'field'}>
      {children}
    </FormField>
  )
}
