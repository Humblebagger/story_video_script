import { NARRATION_MODE } from '../labels'
import {
  ART_STYLES, COLOR_TONES, STYLE_PREFIXES, TARGET_PLATFORMS, TTS_VOICES,
} from '../presets'
import type { AspectRatio, NarrationMode, NovelParams } from '../types'
import { SelectOrCustom } from './SelectOrCustom'

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

const RATIOS: AspectRatio[] = ['9:16', '16:9', '1:1', '4:3']

interface Props {
  value: NovelParams
  onChange: (next: NovelParams) => void
}

/** 制作参数表单：小说级默认值。每章转换都用它（必要时按次覆写旁白模式） */
export function ParamsForm({ value: p, onChange }: Props) {
  const set = <K extends keyof NovelParams>(k: K, v: NovelParams[K]) =>
    onChange({ ...p, [k]: v })

  return (
    <div className="form__grid">
      <Field label="画面风格前缀" wide>
        <input
          value={p.style_prefix}
          list="style-prefixes"
          onChange={(e) => set('style_prefix', e.target.value)}
        />
        <datalist id="style-prefixes">
          {STYLE_PREFIXES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
        </datalist>
      </Field>

      <Field label="艺术风格">
        <SelectOrCustom
          value={p.art_style}
          options={ART_STYLES}
          onChange={(v) => set('art_style', v)}
          placeholder="风格分类标识，如 ukiyo_e"
        />
      </Field>
      <Field label="色调">
        <SelectOrCustom
          value={p.color_tone}
          options={COLOR_TONES}
          onChange={(v) => set('color_tone', v)}
          placeholder="描述整体色彩倾向"
        />
      </Field>
      <Field label="目标平台">
        <SelectOrCustom
          value={p.target_platform}
          options={TARGET_PLATFORMS}
          onChange={(v) => set('target_platform', v)}
        />
      </Field>

      <Field label="画幅">
        <select
          value={p.aspect_ratio}
          onChange={(e) => set('aspect_ratio', e.target.value as AspectRatio)}
        >
          {RATIOS.map((r) => <option key={r}>{r}</option>)}
        </select>
      </Field>
      <Field label="旁白模式">
        <select
          value={p.narration_mode}
          onChange={(e) => set('narration_mode', e.target.value as NarrationMode)}
        >
          {Object.entries(NARRATION_MODE).map(([v, n]) => (
            <option key={v} value={v}>{n}</option>
          ))}
        </select>
      </Field>
      <Field label="TTS 音色">
        <SelectOrCustom
          value={p.tts_voice}
          options={TTS_VOICES}
          onChange={(v) => set('tts_voice', v)}
          placeholder="音色标识"
        />
      </Field>
    </div>
  )
}

export function Field({ label, wide, children }: {
  label: string; wide?: boolean; children: React.ReactNode
}) {
  return (
    <label className={`field${wide ? ' field--wide' : ''}`}>
      <span>{label}</span>
      {children}
    </label>
  )
}
