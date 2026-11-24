/** 镜头三栏视图的纯逻辑：拍平、标检查结果、找所在片段、过滤与上下切换。 */
import type { FilmSession, Severity, Shot, ShotSize, Storyboard, VerificationReport } from './types'

export interface ShotRow { ep: string; shot: Shot }

export function flatShots(doc: Storyboard): ShotRow[] {
  return (doc.episodes ?? []).flatMap((e) => e.shots.map((shot) => ({ ep: e.id, shot })))
}

const HARD: Severity[] = ['critical', 'high']

/** 检查结果归到镜头：/episodes/<i>/shots/<j>/… 才算；硬问题盖过软问题 */
export function shotIssues(report: VerificationReport | null | undefined, doc: Storyboard) {
  const out = new Map<string, 'hard' | 'soft'>()
  for (const f of report?.findings ?? []) {
    const m = /^\/episodes\/(\d+)\/shots\/(\d+)(\/|$)/.exec(f.object_path)
    const id = m && doc.episodes?.[Number(m[1])]?.shots?.[Number(m[2])]?.id
    if (!id) continue
    if (HARD.includes(f.severity)) out.set(id, 'hard')
    else if (!out.has(id)) out.set(id, 'soft')
  }
  return out
}

/** 这一镜所在的出片段，以及采用那次的文件（没采用或没文件为 null） */
export function clipForShot(film: FilmSession | null | undefined, shotId: string) {
  const clip = film?.clips.find((c) => c.shots.includes(shotId))
  if (!clip) return null
  const file = clip.chosen === null ? null : clip.attempts[clip.chosen]?.file ?? null
  return { clip, file }
}

/** 上下切换；collapsed 里的集整体跳过；到头不动 */
export function stepShot(rows: ShotRow[], id: string, dir: 1 | -1 | 'home' | 'end',
                         collapsed: Set<string> = new Set()) {
  const open = rows.filter((r) => !collapsed.has(r.ep))
  if (!open.length) return id
  if (dir === 'home') return open[0].shot.id
  if (dir === 'end') return open[open.length - 1].shot.id
  const i = open.findIndex((r) => r.shot.id === id)
  if (i < 0) return open[0].shot.id
  return open[Math.max(0, Math.min(open.length - 1, i + dir))].shot.id
}

export function filterShots(rows: ShotRow[], query: string) {
  const q = query.trim().toLowerCase()
  if (!q) return rows
  return rows.filter(({ shot: s }) => [s.id, s.action, s.narration?.text, ...(s.dialogue ?? []).map((d) => d.text)]
    .some((v) => typeof v === 'string' && v.toLowerCase().includes(q)))
}

/** 景别色块的色相：越远越冷、越近越暖；避开绿色区间，整体落在雾蓝 / 灰紫 / 玫瑰 / 陶土。 */
export const SIZE_HUE: Record<ShotSize, number> = {
  extreme_wide: 214, wide: 205, full: 232, medium: 266,
  medium_close: 32, close_up: 20, extreme_close_up: 350, insert: 286,
}
