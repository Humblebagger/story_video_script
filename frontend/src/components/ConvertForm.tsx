import { useCallback, useRef, useState } from 'react'
import { NARRATION_MODE } from '../labels'
import { ChapterPicker } from './ChapterPicker'
import {
  ART_STYLES, COLOR_TONES, STYLE_PREFIXES, TARGET_PLATFORMS, TTS_VOICES,
} from '../presets'
import type {
  AspectRatio, Assets, ConvertRequest, LibraryWork, NarrationMode,
} from '../types'
import { AssetLibraryPicker } from './AssetLibraryPicker'
import { SelectOrCustom } from './SelectOrCustom'

/** 默认值与 backend/pipeline/convert.py 的 ConvertParams 逐字对齐 */
const DEFAULTS: Omit<ConvertRequest, 'text' | 'seed_assets' | 'use_library' | 'import_assets'> = {
  work_title: '未命名作品',
  chapter: '全文',
  style_prefix: '电影感写实风格，自然光影',
  art_style: 'realistic',
  color_tone: '自然色调',
  aspect_ratio: '9:16',
  target_platform: '抖音',
  narration_mode: 'selective',
  tts_voice: 'male_mature',
  strict: false,
}

const RATIOS: AspectRatio[] = ['9:16', '16:9', '1:1', '4:3']

interface Props {
  disabled: boolean
  works: LibraryWork[]
  onSubmit: (payload: ConvertRequest) => void
}

export function ConvertForm({ disabled, works, onSubmit }: Props) {
  /** source 是整篇原文，selection 是本次实际要转换的那一段 */
  const [source, setSource] = useState('')
  const [selection, setSelection] = useState('')
  const [p, setP] = useState(DEFAULTS)
  const [useLibrary, setUseLibrary] = useState(true)
  /** 只钉了一部分卡时的显式资产库；整部沿用时为 null（后端据 use_library 自行取库） */
  const [seedAssets, setSeedAssets] = useState<Assets | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const set = <K extends keyof typeof p>(k: K, v: (typeof p)[K]) =>
    setP((prev) => ({ ...prev, [k]: v }))

  const loadFile = async (f: File) => {
    setSource(await f.text())
    if (p.work_title === DEFAULTS.work_title) {
      set('work_title', f.name.replace(/\.[^.]+$/, ''))
    }
  }

  // ChapterPicker 的 effect 依赖它，必须稳定，否则会反复触发
  const pick = useCallback((t: string) => setSelection(t), [])

  const chars = selection.trim().length
  // 后端默认 2500 字一批，据此估算批数，让用户对耗时有预期
  const batches = Math.max(1, Math.ceil(chars / 2500))
  const partial = chars > 0 && chars < source.trim().length

  return (
    <form
      className="form"
      onSubmit={(e) => {
        e.preventDefault()
        if (selection.trim()) {
          onSubmit({
            ...p, text: selection, use_library: useLibrary, import_assets: true,
            ...(seedAssets ? { seed_assets: seedAssets } : {}),
          })
        }
      }}
    >
      <div className="form__text">
        <div className="form__textbar">
          <label>小说原文</label>
          <span className="form__count">
            {source.length ? `全文 ${source.trim().length} 字` : '尚未载入'}
          </span>
          <button
            type="button"
            className="btn btn--sm btn--ghost"
            onClick={() => fileRef.current?.click()}
          >
            读取 .txt
          </button>
          <input
            ref={fileRef}
            type="file"
            accept=".txt,text/plain"
            hidden
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) void loadFile(f)
              e.target.value = ''
            }}
          />
        </div>
        <textarea
          value={source}
          onChange={(e) => setSource(e.target.value)}
          placeholder="粘贴整篇/整章小说原文……转换为忠实分镜 IR：每个镜头可溯源到原文句子，系统补的画面全部显式标记。"
          spellCheck={false}
        />
      </div>

      {source.trim() && (
        <div className="form__pick">
          <ChapterPicker source={source} onChange={pick} />
          <p className={`form__sel${chars ? '' : ' is-empty'}`}>
            {chars
              ? <>本次转换 <b>{chars}</b> 字 · 预计 <b>{batches}</b> 批
                  {partial && <span className="form__partial">（全文的一部分）</span>}</>
              : '当前未选中任何内容'}
          </p>
        </div>
      )}

      <AssetLibraryPicker
        works={works}
        workTitle={p.work_title}
        useLibrary={useLibrary}
        onToggle={setUseLibrary}
        onPickWork={(t) => set('work_title', t)}
        onPin={setSeedAssets}
      />

      <div className="form__grid">
        <Field label="作品名">
          <input value={p.work_title} onChange={(e) => set('work_title', e.target.value)} />
        </Field>
        <Field label="章节">
          <input value={p.chapter} onChange={(e) => set('chapter', e.target.value)} />
        </Field>

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

      <div className="form__foot">
        <label className="check" title="软质量门（旁白密度/评审分）重试耗尽时直接失败，而非择优降级交付">
          <input
            type="checkbox"
            checked={p.strict}
            onChange={(e) => set('strict', e.target.checked)}
          />
          严格模式：质量不达标即失败（默认择优降级交付并附质量报告）
        </label>
        <button className="btn" type="submit" disabled={disabled || !chars}>
          开始转换
        </button>
      </div>
    </form>
  )
}

function Field({ label, wide, children }: {
  label: string; wide?: boolean; children: React.ReactNode
}) {
  return (
    <label className={`field${wide ? ' field--wide' : ''}`}>
      <span>{label}</span>
      {children}
    </label>
  )
}
