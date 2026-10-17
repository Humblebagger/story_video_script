/** 画布上的编辑操作层（第一版画布只读，不暴露手势；操作层先建好并单测覆盖）。
 *
 *  画布上的任何改动都表达成一个操作，落到 edit.ts 的同一套不可变更新上——
 *  锁死字段的规则（原文、溯源、ID、台词旁白文本）自动沿用：这里根本没有改它们的操作。
 *  保存仍走 PUT …/versions/{vid} 整份复验。
 *  镜头顺序不开放：ORDER-001 不许讲述回跳，能合法挪动的空间很小。
 */
import { updateShot } from './edit'
import type { Shot, Storyboard } from './types'

/** 与后端 schema 的 duration_sec 取值范围一致 */
export const MIN_SHOT_SECONDS = 0.5
export const MAX_SHOT_SECONDS = 15

export type TimelineOp =
  | { kind: 'setDuration'; shotId: string; sec: number }
  | { kind: 'setCharacterAction'; shotId: string; ref: string; action: string }

function locate(doc: Storyboard, shotId: string): { episodeId: string; shot: Shot } | null {
  for (const ep of doc.episodes ?? []) {
    const shot = ep.shots.find((s) => s.id === shotId)
    if (shot) return { episodeId: ep.id, shot }
  }
  return null
}

/** 应用一个操作，返回新文档；操作指向不存在的镜头/角色时原样返回 */
export function applyOp(doc: Storyboard, op: TimelineOp): Storyboard {
  const hit = locate(doc, op.shotId)
  if (!hit) return doc
  if (op.kind === 'setDuration') {
    // 时长按 0.5s 取整再夹到 schema 范围内：拖动手势给的是连续值
    const sec = Math.min(MAX_SHOT_SECONDS,
                         Math.max(MIN_SHOT_SECONDS, Math.round(op.sec * 2) / 2))
    if (sec === hit.shot.duration_sec) return doc
    return updateShot(doc, hit.episodeId, op.shotId, { duration_sec: sec })
  }
  const chars = hit.shot.characters ?? []
  if (!chars.some((c) => c.ref === op.ref)) return doc
  const action = op.action.trim()
  return updateShot(doc, hit.episodeId, op.shotId, {
    characters: chars.map((c) => {
      if (c.ref !== op.ref) return c
      const { action: _drop, ...rest } = c
      return action ? { ...c, action } : rest
    }),
  })
}
