/** 出片（视频生成）在画布上的纯计算：段在时间轴上的位置、横条文字与样式、总览主按钮、
 *  确认清单、轮询间隔、前置检查。useFilm 与画布组件只吃这里的结果；单测见 tests/film-lane.test.ts。 */
import { fmtClock } from './timeline'
import type { TShot, Timeline } from './timeline'
import type { FilmAttempt, FilmClip, FilmSession } from './types'

export const IN_FLIGHT: FilmClip['state'][] = ['queued', 'running', 'downloading']
/** 「出片」页签开着且有段在跑时 5 秒轮询一次，否则 30 秒 */
export const POLL_FAST_MS = 5000
export const POLL_SLOW_MS = 30000

export interface ClipSpan { clip: FilmClip; start: number; end: number }

/** 段横跨它所含的镜头（按可播时长的时间轴）；镜头已不在分镜里的段不画 */
export function clipSpans(tl: Timeline, s: FilmSession): ClipSpan[] {
  const byId = new Map(tl.shots.map((x) => [x.id, x]))
  const out: ClipSpan[] = []
  for (const clip of s.clips) {
    const shots = clip.shots.map((id) => byId.get(id)).filter((x): x is TShot => !!x)
    if (!shots.length) continue
    out.push({ clip, start: Math.min(...shots.map((x) => x.start)), end: Math.max(...shots.map((x) => x.end)) })
  }
  return out.sort((p, q) => p.start - q.start)
}

/** 时刻 t 所在的段 */
export function spanAt(spans: ClipSpan[], t: number): ClipSpan | undefined {
  return spans.find((s) => s.start <= t && t < s.end)
}

/** 播放头在段内的偏移（秒）：视频从这里开始播 */
export const clipOffset = (span: ClipSpan, t: number) => Math.max(0, t - span.start)

export const inFlight = (c: FilmClip) => IN_FLIGHT.includes(c.state)

/** 采用的那一次（成功且有文件）；没有就 null */
export function chosenAttempt(c: FilmClip): FilmAttempt | null {
  const a = c.chosen === null ? undefined : c.attempts[c.chosen]
  return a && a.state === 'succeeded' && a.file ? a : null
}

export type LaneKind = 'planned' | 'busy' | 'done' | 'failed' | 'stale'

/** 横条样式：未出片 / 排队与生成中（含下载）/ 已完成 / 失败 / 过期 */
export function laneKind(c: FilmClip): LaneKind {
  if (inFlight(c)) return 'busy'
  if (c.state === 'done' || c.state === 'failed' || c.state === 'stale') return c.state
  return 'planned'
}

const shortId = (id: string) => id.replace(/^E\d+-/, '')
const yuan = (n: number) => `¥${n.toFixed(2)}`

/** 横条上的文字（画的时候再按宽度截断）；now 为毫秒时间戳 */
export function laneText(c: FilmClip, now: number): string {
  switch (laneKind(c)) {
    case 'busy': {
      const since = c.queued_at ? Math.max(0, (now - Date.parse(c.queued_at)) / 1000) : 0
      return `生成中 · 已等 ${fmtClock(since)}`
    }
    case 'done':
      return `${shortId(c.id)} · 第 ${(c.chosen ?? 0) + 1} 次 · ${yuan(chosenAttempt(c)?.cost_cny ?? 0)}`
    case 'failed':
      return c.error ?? '失败'
    case 'stale':
      return '已过期 · 仍可播放旧版'
    default:
      return `${shortId(c.id)} · ${c.duration}s · 约 ${yuan(c.estimate_cny)}`
  }
}

/** 横条悬停说明：所含镜头、被裁的参考图、截断、待核对、错误原文 */
export function laneTitle(c: FilmClip): string {
  const lines = [`${c.id} · ${c.shots.join('、')} · ${c.duration}s`]
  if (c.dropped_refs.length) lines.push(`⚠ 参考图超出名额被裁：${c.dropped_refs.join('、')}`)
  if (c.truncated) lines.push('✂ 超出单段上限，尾部被截断')
  if (c.uncertain) lines.push('厂商那边可能还有这一段的任务，请到控制台核对')
  if (c.error) lines.push(c.error)
  return lines.join('\n')
}

/** 批量「出剩余各段」的范围：未出片或失败，且不是待核对的（与服务端 _remaining 一致） */
export const remainingClips = (s: FilmSession) =>
  s.clips.filter((c) => (c.state === 'planned' || c.state === 'failed') && !c.uncertain)

export type MainAction =
  | { kind: 'try'; clip: FilmClip }
  | { kind: 'rest'; count: number; cny: number }
  | { kind: 'none' }

/** 总览主按钮：还没有任何一段出成功过 → 先试一段（试段在跑时什么都不提供）（选中的段能出就试它）；否则出剩余各段 */
export function mainAction(s: FilmSession, selected: string | null): MainAction {
  const rest = remainingClips(s)
  if (!rest.length) return { kind: 'none' }
  if (!s.clips.some((c) => c.attempts.some((a) => a.state === 'succeeded'))) {
    // 试段已排队但还没出结果：不能再提供第二次付费试段
    if (s.clips.some(inFlight)) return { kind: 'none' }
    return { kind: 'try', clip: rest.find((c) => c.id === selected) ?? rest[0] }
  }
  return { kind: 'rest', count: rest.length, cny: s.remaining_cny }
}

/** 批量确认框：各段时长与费用、合计、已花、在跑预留、执行后累计与上限 */
export function batchSummary(s: FilmSession) {
  const rows = remainingClips(s).map((c) => ({ id: c.id, duration: c.duration, cny: c.estimate_cny }))
  const total = s.remaining_cny
  const after = Math.round((s.spent_cny + s.reserved_cny + total) * 100) / 100
  return { rows, total, spent: s.spent_cny, reserved: s.reserved_cny, after,
           budget: s.budget_cny, over: after > s.budget_cny + 1e-9 }
}

/** 单段出片要不要先弹确认：预估超过确认线（默认 20 元） */
export const needsConfirm = (c: FilmClip, s: FilmSession) => c.estimate_cny > s.confirm_over_cny

/** 下一次轮询隔多久 */
export function pollDelay(s: FilmSession | null, tabOpen: boolean): number {
  return s && tabOpen && s.clips.some(inFlight) ? POLL_FAST_MS : POLL_SLOW_MS
}

/** 前置检查：缺参考图的资产、参考图被裁的段、被截断的段 */
export function precheck(s: FilmSession) {
  return {
    missing: [...new Set(s.clips.flatMap((c) => c.missing_refs))].sort(),
    trimmed: s.clips.filter((c) => c.dropped_refs.length).map((c) => c.id),
    truncated: s.clips.filter((c) => c.truncated).map((c) => c.id),
  }
}

/** 首帧来源的中文说明 */
export function firstFrameText(c: FilmClip): string {
  const f = c.first_frame
  if (!f) return '不带首帧'
  if (f.startsWith('keyframe:')) {
    return `关键帧 ${f.slice('keyframe:'.length)}${c.frame_mode === 'ref' ? '（占第一个参考位）' : ''}`
  }
  if (f.startsWith('relay:')) return `接力上一段（${f.slice('relay:'.length)}）的尾帧`
  return f
}
