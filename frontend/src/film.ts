/** 出片（视频生成）在画布上的纯计算：段在时间轴上的位置、横条文字与样式、总览主按钮、
 *  确认清单、轮询间隔、前置检查。useFilm 与画布组件只吃这里的结果；单测见 tests/film-lane.test.ts。 */
import { tr } from './i18n/core'
import { itemError } from './i18n/serverMsg'
import { fmtClock } from './timeline'
import type { TShot, Timeline } from './timeline'
import type { FilmAttempt, FilmClip, FilmClipState, FilmFreeNode, FilmSession } from './types'

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

export const inFlight = (c: { state: FilmClipState }) => IN_FLIGHT.includes(c.state)

/** 风格图占参考位时的 id（与后端 compose.STYLE_ID 一致） */
export const STYLE_REF = '__style__'

export const freeNodes = (s: FilmSession) => s.free ?? []

/** 剧本段或自由节点有在排队 / 生成中的 */
export const anyInFlight = (s: FilmSession) => s.clips.some(inFlight) || freeNodes(s).some(inFlight)

/** 采用的那一次（成功且有文件）；没有就 null */
export function chosenAttempt(c: { chosen: number | null; attempts: FilmAttempt[] }): FilmAttempt | null {
  const a = c.chosen === null ? undefined : c.attempts[c.chosen]
  return a && a.state === 'succeeded' && a.file ? a : null
}

/** 要播的那一次：点名第几次就播它；否则播采用的那次；没有采用就播最近成功的一次。没有可播的为 null */
export function playableAttempt(c: { chosen: number | null; attempts: FilmAttempt[] },
                                index?: number): { attempt: FilmAttempt; index: number } | null {
  const playable = (i: number | null | undefined) => {
    const a = i == null ? undefined : c.attempts[i]
    return a && a.state === 'succeeded' && a.file ? { attempt: a, index: i as number } : null
  }
  if (index !== undefined) return playable(index)
  const picked = playable(c.chosen)
  if (picked) return picked
  for (let i = c.attempts.length - 1; i >= 0; i--) {
    const hit = playable(i)
    if (hit) return hit
  }
  return null
}

/** 已等时长：「4 分 05 秒」 */
export function fmtWait(sec: number): string {
  const n = Math.max(0, Math.floor(sec))
  return tr('film.waitMin', { m: Math.floor(n / 60), s: String(n % 60).padStart(2, '0') })
}

/** 生成中那一行：已等多久 + 通常要多久（分钟：下限向下、上限向上取整）；超过上限换说法。只有时间，不带厂商或模型名 */
export function waitLine(sec: number, typical?: number[] | null): string {
  const wait = fmtWait(sec)
  if (!typical || typical.length < 2) return tr('film.waitOnly', { wait })
  const [lo, hi] = typical
  if (sec > hi) return tr('film.waitOver', { wait })
  return tr('film.wait', { wait, lo: Math.max(1, Math.floor(lo / 60)), hi: Math.max(1, Math.ceil(hi / 60)) })
}

/** 已等秒数：从排队那一刻算；now 为毫秒时间戳 */
export const waitedSec = (c: { queued_at?: string }, now: number) =>
  (c.queued_at ? Math.max(0, (now - Date.parse(c.queued_at)) / 1000) : 0)

/** 能不能取消：free 还没提交（不花钱）；paid 已提交（服务商可能仍扣费）；null 不能（不在跑、正在提交、已在取回） */
export function cancelKind(c: { state: FilmClipState; attempts: FilmAttempt[] }): 'free' | 'paid' | null {
  const last = c.attempts[c.attempts.length - 1]
  if (c.state === 'queued') return last?.state === 'submitting' ? null : 'free'
  if (c.state === 'running') return last?.task_id ? 'paid' : null
  return null
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
      return tr('film.busy', { wait: fmtClock(since) })
    }
    case 'done':
      return tr('film.done', { id: shortId(c.id), n: (c.chosen ?? 0) + 1, cost: yuan(chosenAttempt(c)?.cost_cny ?? 0) })
    case 'failed':
      return itemError(c) || tr('film.failed')
    case 'stale':
      return tr('film.stale')
    default:
      return tr('film.planned', { id: shortId(c.id), sec: c.duration, cost: yuan(c.estimate_cny) })
  }
}

/** 横条悬停说明：所含镜头、被裁的参考图、截断、待核对、错误原文 */
export function laneTitle(c: FilmClip): string {
  const lines = [`${c.id} · ${c.shots.join(tr('common.listSep'))} · ${c.duration}s`]
  if (c.dropped_refs.length) lines.push(tr('film.droppedRefs', { list: c.dropped_refs.join(tr('common.listSep')) }))
  if (c.truncated) lines.push(tr('film.truncated'))
  if (c.uncertain) lines.push(tr('film.uncertain'))
  const e = itemError(c)
  if (e) lines.push(e)
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
  // 自由节点复制进来的那次不算试段（它没按分镜出过）
  if (!s.clips.some((c) => c.attempts.some((a) => a.state === 'succeeded' && !a.free_id))) {
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

/** 下一次轮询隔多久：页签（或节点图）开着且有段或自由节点在跑时快 */
export function pollDelay(s: FilmSession | null, tabOpen: boolean): number {
  return s && tabOpen && anyInFlight(s) ? POLL_FAST_MS : POLL_SLOW_MS
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
export function firstFrameText(c: Pick<FilmClip, 'first_frame' | 'frame_mode'>): string {
  const f = c.first_frame
  if (!f) return tr('film.noFirstFrame')
  if (f.startsWith('keyframe:')) {
    return tr('film.keyframe', { id: f.slice('keyframe:'.length) }) + (c.frame_mode === 'ref' ? tr('film.keyframeRefSlot') : '')
  }
  if (f.startsWith('relay:')) return tr('film.relay', { id: f.slice('relay:'.length) })
  if (f.startsWith('tail:')) return tr('film.tail', { id: f.slice('tail:'.length) })
  return f
}

/** 自由节点要占几个参考位：参考图各一个；带首帧、又有参考图、厂商不能同用时首帧再占一个（与后端同规则） */
export function slotsNeeded(refs: string[], firstFrame: string | null, s: FilmSession): number {
  return refs.length + (firstFrame && refs.length && !s.options.frame_with_refs ? 1 : 0)
}

/** 可作「尾帧首帧」来源的：采用的那次有尾帧的段与自由节点 */
export function tailSources(s: FilmSession): string[] {
  return [...s.clips, ...freeNodes(s)].filter((x) => chosenAttempt(x)?.last_frame).map((x) => x.id)
}

/** 自由节点的某次尝试复制进挂靠段后，在那一段尝试里的下标；没有为 -1 */
export function copyIndex(s: FilmSession, node: FilmFreeNode, a: FilmAttempt): number {
  const t = s.clips.find((c) => c.id === node.target)
  return t ? t.attempts.findIndex((x) => x.free_id === node.id && x.task_id === a.task_id) : -1
}
