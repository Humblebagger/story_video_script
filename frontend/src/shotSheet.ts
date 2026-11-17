/** 拉片表与片段卡镜头标签的纯计算：按集分组、提示词格的合并行数、运镜文字、镜头小标签。
 *  不依赖 React；单测见 tests/shot-sheet.test.ts（设计 docs/specs/2026-11-17-shot-breakdown-sheet-design.md）。 */
import { CAMERA_ANGLE, CAMERA_MOVEMENT, SHOT_SIZE, label } from './labels'
import type { Episode, FilmClip, FilmSession, Shot, Storyboard } from './types'

export interface SheetRow {
  shot: Shot
  /** 这一镜所在的出片段；没有出片规划为 null */
  clip: FilmClip | null
  /** 提示词格占几行；0 = 并进上面那一格，这一行不渲染提示词格 */
  span: number
}
export interface SheetGroup { ep: Episode; rows: SheetRow[] }

/** 每集一组、每镜一行；同一集内相邻且同属一段（或同为未规划）的镜头合并提示词格 */
export function sheetGroups(doc: Storyboard, film: FilmSession | null | undefined): SheetGroup[] {
  // 一镜出现在多段里时取第一段（与 shotFocus.clipForShot 一致）
  const byShot = new Map<string, FilmClip>()
  for (const c of film?.clips ?? []) for (const id of c.shots) if (!byShot.has(id)) byShot.set(id, c)
  return (doc.episodes ?? []).map((ep) => {
    const rows: SheetRow[] = []
    let head: SheetRow | null = null
    for (const shot of ep.shots ?? []) {
      const clip = byShot.get(shot.id) ?? null
      if (head && head.clip === clip) {
        head.span += 1
        rows.push({ shot, clip, span: 0 })
      } else {
        head = { shot, clip, span: 1 }
        rows.push(head)
      }
    }
    return { ep, rows }
  })
}

/** 「推 / 仰拍」；只有其一就只写其一，都没有为空串 */
export function cameraText(shot: Shot): string {
  return [label(CAMERA_MOVEMENT, shot.camera?.movement), label(CAMERA_ANGLE, shot.camera?.angle)]
    .filter(Boolean).join(' / ')
}

/** E01-SH003 → SH003；没有 - 就原样 */
export const shortShotId = (id: string) => id.slice(id.lastIndexOf('-') + 1)

/** 片段卡上的镜头小标签：「SH003 特写·推」 */
export function shotTag(shot: Shot): string {
  const spec = [label(SHOT_SIZE, shot.shot_size), label(CAMERA_MOVEMENT, shot.camera?.movement)]
    .filter(Boolean).join('·')
  return spec ? `${shortShotId(shot.id)} ${spec}` : shortShotId(shot.id)
}

export function shotsById(doc: Storyboard): Map<string, Shot> {
  const out = new Map<string, Shot>()
  for (const ep of doc.episodes ?? []) for (const s of ep.shots ?? []) out.set(s.id, s)
  return out
}

/** 一段里每个镜头的小标签；分镜里找不到的镜头只写短镜号 */
export function clipShotTags(shotIds: string[], byId: Map<string, Shot>): string[] {
  return shotIds.map((id) => {
    const s = byId.get(id)
    return s ? shotTag(s) : shortShotId(id)
  })
}

export const TAG_MAX = 3

/** 最多显示 max 个，其余折叠成 +more */
export function foldTags(tags: string[], max = TAG_MAX): { shown: string[]; more: number } {
  return { shown: tags.slice(0, max), more: Math.max(0, tags.length - max) }
}

export const PROMPT_FOLD_CHARS = 60

/** 提示词要不要「展开」按钮：超过 60 字或超过 3 行（不量 DOM，测试环境没有布局） */
export function needsFold(text: string): boolean {
  return text.length > PROMPT_FOLD_CHARS || text.split('\n').length > 3
}
