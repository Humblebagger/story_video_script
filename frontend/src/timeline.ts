/** 时间轴画布的布局计算（纯函数，单测覆盖；渲染组件只吃这里的结果）。
 *
 *  横轴是视频时间，按**可播时长**累计：max(duration_sec, 念完旁白台词所需)——
 *  与后端渲染计价（pipeline/quality.py speech_seconds）同一口径，否则画布上的时间
 *  和真正渲染出来的片子对不上。
 */
import type { MusicSegment, Mood, Shot, ShotCharacter, Storyboard } from './types'

/** 中文 TTS 语速（字/秒），与后端 DEFAULT_SPEECH_CPS 一致 */
export const SPEECH_CPS = 4.5

export interface TShot {
  id: string
  episodeId: string
  /** 全章顺序（跨集连续） */
  index: number
  start: number
  end: number
  /** 分镜里写的时长 */
  nominal: number
  /** 可播时长：念不完旁白台词时比 nominal 长 */
  playable: number
  shot: Shot
}

export interface Segment {
  key: string
  label: string
  start: number
  end: number
}

export interface MusicBand extends Segment {
  mood?: Mood
  intensity?: MusicSegment['intensity']
}

export interface CharNode {
  shotId: string
  /** 节点画在镜头中点 */
  t: number
  start: number
  end: number
  /** 角色本镜的动作；没有就退回镜头的画面描述 */
  action: string
  fromShotAction: boolean
  expression?: string
  position?: string
  outfit?: string
}

export interface CharLane {
  ref: string
  name: string
  nodes: CharNode[]
}

export interface SpeechSeg {
  shotId: string
  kind: 'narration' | 'dialogue'
  start: number
  end: number
  text: string
  who?: string
}

export interface Timeline {
  total: number
  shots: TShot[]
  episodes: Segment[]
  scenes: Segment[]
  characters: CharLane[]
  speech: SpeechSeg[]
  music: MusicBand[]
}

export function speechSeconds(shot: Shot, cps = SPEECH_CPS): number {
  const n = (shot.narration?.text ?? '').length
    + (shot.dialogue ?? []).reduce((a, d) => a + (d.text ?? '').length, 0)
  return n ? n / cps : 0
}

export function playableSeconds(shot: Shot, cps = SPEECH_CPS): number {
  return Math.max(shot.duration_sec || 0, speechSeconds(shot, cps))
}

/** 同一镜头内旁白与台词的时间先后：按 narration.order，缺省旁白在前；按字数分配时长 */
function speechOf(t: TShot, names: Record<string, string>, cps: number): SpeechSeg[] {
  const { shot } = t
  const narr = shot.narration?.text
    ? [{ kind: 'narration' as const, text: shot.narration.text }] : []
  const lines = (shot.dialogue ?? []).filter((d) => d.text).map((d) => ({
    kind: 'dialogue' as const, text: d.text,
    who: names[d.character_ref ?? ''] ?? d.character_ref,
  }))
  const order = shot.narration?.order === 'after_dialogue'
    ? [...lines, ...narr] : [...narr, ...lines]
  const out: SpeechSeg[] = []
  let at = t.start
  for (const s of order) {
    const end = Math.min(t.end, at + s.text.length / cps)
    out.push({ shotId: shot.id, start: at, end, ...s })
    at = end
  }
  return out
}

/** 连续且 key 相同的镜头并成一段（场景条） */
function runs(shots: TShot[], key: (s: TShot) => string | undefined,
              label: (k: string) => string): Segment[] {
  const out: Segment[] = []
  for (const s of shots) {
    const k = key(s)
    if (!k) continue
    const last = out[out.length - 1]
    if (last && last.key === k && Math.abs(last.end - s.start) < 1e-9) last.end = s.end
    else out.push({ key: k, label: label(k), start: s.start, end: s.end })
  }
  return out
}

export function buildTimeline(doc: Storyboard, cps = SPEECH_CPS): Timeline {
  const assets = doc.assets ?? {}
  const names: Record<string, string> = {}
  for (const c of [...(assets.characters ?? []), ...(assets.creatures ?? [])]) names[c.id] = c.name
  const places: Record<string, string> = {}
  for (const l of assets.locations ?? []) places[l.id] = l.name

  const shots: TShot[] = []
  const episodes: Segment[] = []
  const music: MusicBand[] = []
  let t = 0
  for (const ep of doc.episodes ?? []) {
    const epStart = t
    const mine: TShot[] = []
    for (const shot of ep.shots ?? []) {
      const playable = playableSeconds(shot, cps)
      const ts: TShot = { id: shot.id, episodeId: ep.id, index: shots.length, start: t,
                          end: t + playable, nominal: shot.duration_sec || 0, playable, shot }
      shots.push(ts)
      mine.push(ts)
      t += playable
    }
    episodes.push({ key: ep.id, label: ep.title ? `${ep.id} ${ep.title}` : ep.id,
                    start: epStart, end: t })
    const byId = Object.fromEntries(mine.map((s) => [s.id, s]))
    for (const [i, seg] of (ep.music?.curve ?? []).entries()) {
      const from = byId[seg.from_shot ?? ''] ?? mine[0]
      const to = byId[seg.to_shot ?? ''] ?? mine[mine.length - 1]
      if (!from || !to || to.end <= from.start) continue
      music.push({ key: `${ep.id}-m${i}`, label: seg.note ?? '', start: from.start, end: to.end,
                   mood: seg.mood, intensity: seg.intensity })
    }
  }

  const lanes = new Map<string, CharLane>()
  for (const s of shots) {
    for (const c of s.shot.characters ?? [] as ShotCharacter[]) {
      if (!c.ref) continue
      if (!lanes.has(c.ref)) lanes.set(c.ref, { ref: c.ref, name: names[c.ref] ?? c.ref, nodes: [] })
      lanes.get(c.ref)!.nodes.push({
        shotId: s.id, t: (s.start + s.end) / 2, start: s.start, end: s.end,
        action: c.action || s.shot.action, fromShotAction: !c.action,
        expression: c.expression, position: c.position, outfit: c.outfit,
      })
    }
  }

  return {
    total: t,
    shots,
    episodes,
    scenes: runs(shots, (s) => s.shot.location_ref, (k) => places[k] ? `${k} ${places[k]}` : k),
    characters: [...lanes.values()],
    speech: shots.flatMap((s) => speechOf(s, names, cps)),
    music,
  }
}

/** 时刻 t 所在镜头的序号；超出两端时夹到首/末镜 */
export function shotIndexAt(tl: Timeline, t: number): number {
  if (!tl.shots.length) return -1
  let lo = 0
  let hi = tl.shots.length - 1
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1
    if (tl.shots[mid].start <= t) lo = mid
    else hi = mid - 1
  }
  return lo
}

/** 一条连线（镜头顺序或某角色的动作顺序）在时刻 t 点亮了多少：0（未到）… 1（已过） */
export function litFraction(from: number, to: number, t: number): number {
  if (t <= from) return 0
  if (t >= to || to <= from) return 1
  return (t - from) / (to - from)
}

export function fmtClock(sec: number): string {
  const s = Math.max(0, Math.floor(sec))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}
