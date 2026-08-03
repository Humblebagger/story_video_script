/** 分镜的人工编辑：不可变更新 + 可编辑边界。
 *
 *  「剧情属于小说，呈现属于系统」——编辑权正好开在系统那一侧：
 *  可改的是怎么拍（景别/运镜/时长/画面描述/氛围/音效/转场/角色表演），
 *  锁死的是原文 units 文本、source.unit_refs、derivation 推导标记、台词与旁白文本。
 *  这样改完的产物依然通得过后端的 lint 与逐字保真校验，IR 的可校验性不失守。
 */
import type { Assets, Episode, Shot, Storyboard } from './types'

/** 锁死的字段：任何编辑路径都不得触碰，否则保真/溯源契约破坏 */
export const LOCKED_FIELDS = ['source', 'narration.text', 'dialogue[].text'] as const

/** 资产卡里锁死的字段：这些 ID 被镜头层跨引用，改了 lint 立刻报错
 *  （location_ref / prop_refs.ref+state / characters.ref+outfit / dialogue.character_ref） */
export const LOCKED_ASSET_FIELDS = [
  'assets[].id', 'characters[].outfits[].id', 'props[].states[].id',
] as const

export type AssetKind = 'characters' | 'locations' | 'props' | 'creatures'

/** 按 ID 就地更新一张资产卡（不可变） */
export function updateAsset(
  doc: Storyboard,
  kind: AssetKind,
  id: string,
  patch: Record<string, unknown>,
): Storyboard {
  const assets: Assets = doc.assets ?? {}
  const list = assets[kind] ?? []
  return {
    ...doc,
    assets: {
      ...assets,
      [kind]: list.map((c) => (c.id === id ? { ...c, ...patch } : c)),
    },
  }
}

/** 别名等以顿号/斜杠/逗号分隔的列表 */
export function splitAliases(v: string): string[] {
  return v.split(/[、,，/]/).map((s) => s.trim()).filter(Boolean)
}

export function updateShot(
  doc: Storyboard,
  episodeId: string,
  shotId: string,
  patch: Partial<Shot>,
): Storyboard {
  return {
    ...doc,
    episodes: doc.episodes.map((ep: Episode) =>
      ep.id !== episodeId ? ep : {
        ...ep,
        shots: ep.shots.map((s) => (s.id === shotId ? { ...s, ...patch } : s)),
      }),
  }
}

/** 把 "风声 / 犬吠" 这类输入切回数组；空串得到空数组而非 [''] */
export function splitList(v: string): string[] {
  return v.split('/').map((s) => s.trim()).filter(Boolean)
}
