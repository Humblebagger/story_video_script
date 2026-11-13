/** 配音与合成在「出片」页签里的纯计算：能不能合成及原因、合成状态文字、成片按集分组、对齐说明、选曲参考、
 *  BGM 上传类型、按钮文字、什么时候重读预览。useCompose 与 ComposePanel 只吃这里的结果；单测见 tests/compose.test.tsx。 */
import { inFlight } from './film'
import { tr } from './i18n/core'
import { formatMsg } from './i18n/serverMsg'
import { INTENSITY, label, MOOD } from './labels'
import type { ComposePreview, FilmSession, FinalState, MixNote, MusicSegment, VoicesInfo } from './types'

/** 合成在跑时多久重读一次预览 */
export const COMPOSE_POLL_MS = 3000
export const ffmpegHint = () => tr('compose.ffmpegHint')
/** 文件选择框接受的类型 */
export const BGM_ACCEPT = 'audio/mpeg,audio/wav,audio/x-wav,audio/mp4,audio/x-m4a,audio/aac,.mp3,.wav,.m4a,.aac'

const yuan = (n: number) => `¥${n.toFixed(2)}`
const BGM_TYPES = ['audio/mpeg', 'audio/mp3', 'audio/wav', 'audio/x-wav', 'audio/wave', 'audio/mp4',
                   'audio/x-m4a', 'audio/aac']
const BGM_EXT: Record<string, string> = { mp3: 'audio/mpeg', wav: 'audio/wav', m4a: 'audio/mp4', aac: 'audio/aac' }

export const composing = (p: ComposePreview | null) =>
  !!p?.final && (p.final.state === 'queued' || p.final.state === 'running')

/** 出片会话里会改变合成预览的部分：变了才重读（已花金额、轮询时间这些不算） */
export function composeKey(s: FilmSession): string {
  return JSON.stringify([s.audio_mode, s.resolution, s.voices ?? {}, s.final?.state ?? null,
                         s.final?.finished_at ?? null, s.clips.map((c) => [c.id, c.state, c.chosen, c.mute_native])])
}

export const speakerName = (v: VoicesInfo | null, key: string) =>
  formatMsg(v?.speakers.find((x) => x.key === key)?.name) || key || tr('compose.noSpeaker')

/** 不能合成的原因（按要先处理的顺序）；空数组为可以合成 */
export function composeBlockers(p: ComposePreview, s: FilmSession, v: VoicesInfo | null,
                                o: { dirty: boolean; gate: string | null; draft: boolean }): string[] {
  const out: string[] = []
  if (o.dirty) out.push(tr('compose.blockDirty'))
  if (o.gate) out.push(tr('compose.blockGate', { gate: o.gate }))
  if (!p.tools) out.push(ffmpegHint())
  if (composing(p)) out.push(tr('compose.blockComposing'))
  if (s.clips.some(inFlight)) out.push(tr('compose.blockInFlight'))
  if (p.missing_voices.length) {
    out.push(tr('compose.blockVoices', {
      n: p.missing_voices.length, names: p.missing_voices.map((k) => speakerName(v, k)).join(tr('common.listSep')),
    }))
  }
  if (!o.draft && p.no_video.length) {
    out.push(tr('compose.blockNoVideo', { n: p.no_video.length }))
  }
  if (s.spent_cny + p.tts_cny > s.budget_cny + 1e-9) {
    out.push(tr('compose.blockBudget', { cost: yuan(p.tts_cny), budget: yuan(s.budget_cny) }))
  }
  return out
}

export function finalText(f: FinalState): string {
  if (f.state === 'queued' || f.state === 'running') return tr('compose.running', { step: f.step || tr('compose.stepStart') })
  if (f.state === 'failed') return tr('compose.failed', { error: f.error ?? tr('compose.unknownReason') })
  return f.stale ? tr('compose.stale') : tr('compose.fresh')
}

export interface FinalEpisode { episode: string; video?: string; srt?: string }

/** 成片文件按集分组（final/E01.mp4、final/E01.srt） */
export function finalEpisodes(files: string[]): FinalEpisode[] {
  const by = new Map<string, FinalEpisode>()
  for (const f of files) {
    const m = f.match(/^final\/(.+)\.(mp4|srt)$/)
    if (!m) continue
    const e = by.get(m[1]) ?? { episode: m[1] }
    if (m[2] === 'mp4') e.video = f
    else e.srt = f
    by.set(m[1], e)
  }
  return [...by.values()]
}

/** 报告里的声画对齐调整 */
export function noteText(n: MixNote): string {
  return n.kind === 'speedup' ? tr('compose.noteSpeedup', { shot: n.shot, speed: n.speed })
    : tr('compose.noteExtend', { shot: n.shot, speed: n.speed, sec: n.extend ?? 0 })
}

/** 分镜 music.curve 的一段：镜头范围 · 情绪 · 强度 · 说明 */
export function curveText(seg: MusicSegment): string {
  const range = seg.from_shot || seg.to_shot ? `${seg.from_shot ?? ''}–${seg.to_shot ?? ''}` : ''
  return [range, label(MOOD, seg.mood), seg.intensity ? INTENSITY[seg.intensity] : '', seg.note ?? '']
    .filter(Boolean).join(' · ')
}

/** 上传 BGM 用的 Content-Type：浏览器给的类型能认就用，否则按扩展名；都不认为 null */
export function bgmType(file: { name: string; type: string }): string | null {
  if (BGM_TYPES.includes(file.type)) return file.type
  return BGM_EXT[file.name.split('.').pop()?.toLowerCase() ?? ''] ?? null
}

export const composeLabel = (p: ComposePreview) =>
  p.tts_cny > 0 ? tr('compose.buttonPaid', { cost: yuan(p.tts_cny) }) : tr('compose.buttonFree')
