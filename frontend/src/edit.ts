/** 分镜的人工编辑：不可变更新 + 可编辑边界。
 *
 *  「剧情属于小说，呈现属于系统」——编辑权正好开在系统那一侧：
 *  可改的是怎么拍（景别/运镜/时长/画面描述/氛围/音效/转场/角色表演），
 *  锁死的是原文 units 文本、source.unit_refs、derivation 推导标记、台词与旁白文本。
 *  这样改完的产物依然通得过后端的 lint 与逐字保真校验，IR 的可校验性不失守。
 */
import type { CardOption } from './resolve'
import type { Assets, Episode, Shot, ShotBeat, Storyboard } from './types'

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

/* ---------- 挂卡：把资产引用挂到镜头上 ----------
 *
 *  形象锁定在本 IR 里靠引用完成，不靠往正文里写外貌——schema 对 characters 的原话是
 *  「只写资产引用+本镜头的状态，严禁重写外貌」。所以「@ 某张卡」的落点是下面这些
 *  结构化字段，而不是 action 正文里的一个 token。
 *
 *  下面几条规则与后端 lint 逐条对应，写在这一处，界面只调用不重述：
 *    - 角色卡有 outfits → 引用必须选中其一（lint 缺省按 'default' 找，找不到即报错）
 *    - 生物卡（A）挂进 characters[]，但不得带 outfit
 *    - 道具卡有 states → 必须填 state；没有 states → 不许填
 *    - 场景是单选，落在 location_ref
 */

export function isAttached(shot: Shot, card: CardOption): boolean {
  if (card.kind === 'locations') return shot.location_ref === card.id
  if (card.kind === 'props') return !!shot.prop_refs?.some((p) => p.ref === card.id)
  return !!shot.characters?.some((c) => c.ref === card.id)
}

/** 挂一张卡，返回可直接喂给 updateShot 的 patch；已挂过则返回空 patch（幂等） */
export function attachCard(shot: Shot, card: CardOption): Partial<Shot> {
  if (isAttached(shot, card)) return {}
  const first = card.variants[0]?.id
  switch (card.kind) {
    case 'locations':
      return { location_ref: card.id }
    case 'props':
      return { prop_refs: [...(shot.prop_refs ?? []),
                           first ? { ref: card.id, state: first } : { ref: card.id }] }
    case 'creatures':
      return { characters: [...(shot.characters ?? []), { ref: card.id }] }
    default:
      return { characters: [...(shot.characters ?? []),
                            first ? { ref: card.id, outfit: first } : { ref: card.id }] }
  }
}

/** 摘掉一张卡。垫图列表里若还留着它的 ID 一并清掉，避免垫一张画面里没有的卡 */
export function detachCard(shot: Shot, card: CardOption): Partial<Shot> {
  const patch: Partial<Shot> =
    card.kind === 'locations'
      ? { location_ref: undefined, location_angle: undefined }
      : card.kind === 'props'
        ? { prop_refs: (shot.prop_refs ?? []).filter((p) => p.ref !== card.id) }
        : { characters: (shot.characters ?? []).filter((c) => c.ref !== card.id) }
  const refs = shot.prompts?.reference_assets
  if (refs?.includes(card.id)) {
    Object.assign(patch, setReferenceAssets(shot, refs.filter((r) => r !== card.id)))
  }
  return patch
}

/** 改某个引用的变体：角色换服装、道具换形态 */
export function setVariant(shot: Shot, card: CardOption, variantId: string): Partial<Shot> {
  if (card.kind === 'props') {
    return { prop_refs: (shot.prop_refs ?? []).map((p) =>
      p.ref === card.id ? { ...p, state: variantId || undefined } : p) }
  }
  return { characters: (shot.characters ?? []).map((c) =>
    c.ref === card.id ? { ...c, outfit: variantId || undefined } : c) }
}

/* ---------- v0.5：镜头内阶段（beats）与负面约束 ----------
 *
 *  一条优秀的长镜头提示词，威力全在「同一个不切的镜头里，情绪与灯光分阶段推进」。
 *  action 只有一份时表达不了这件事，只能塞进一根字符串任下游去猜。
 *
 *  时长是这里唯一的硬约束：镜头有 duration_sec，各拍也有，两者必须自洽，
 *  否则下游按哪个走全凭猜——所以下面每个改动都顺手把镜头时长同步成各拍之和，
 *  而不是让用户自己去对账（lint 会因此报错）。 */

const DEFAULT_BEAT_SEC = 2

/** 各拍之和即镜头时长。浮点相加会积累误差，统一留一位小数 */
function withBeats(beats: ShotBeat[]): Partial<Shot> {
  if (!beats.length) return { beats: undefined }
  const total = Math.round(beats.reduce((a, b) => a + (b.duration_sec || 0), 0) * 10) / 10
  return { beats, duration_sec: total }
}

/** 拆出第一拍时把整镜的现有内容带进去，别让用户重打一遍 */
export function addBeat(shot: Shot): Partial<Shot> {
  const beats = shot.beats ?? []
  if (!beats.length) {
    // schema 要求至少两拍——只有一拍等于没分，所以一次给出两拍
    const half = Math.round((shot.duration_sec / 2) * 10) / 10
    return withBeats([
      { duration_sec: half, action: shot.action, ...(shot.atmosphere ? { lighting: shot.atmosphere } : {}) },
      { duration_sec: Math.round((shot.duration_sec - half) * 10) / 10, action: '' },
    ])
  }
  return withBeats([...beats, { duration_sec: DEFAULT_BEAT_SEC, action: '' }])
}

export function updateBeat(shot: Shot, i: number, patch: Partial<ShotBeat>): Partial<Shot> {
  return withBeats((shot.beats ?? []).map((b, j) => (j === i ? { ...b, ...patch } : b)))
}

/** 删到只剩一拍就整个撤掉分拍：一拍不成立，且镜头时长要还原 */
export function removeBeat(shot: Shot, i: number): Partial<Shot> {
  const rest = (shot.beats ?? []).filter((_, j) => j !== i)
  if (rest.length < 2) return { beats: undefined }
  return withBeats(rest)
}

export function setConstraints(list: string[]): Partial<Shot> {
  const clean = list.map((c) => c.trim()).filter(Boolean)
  return { constraints: clean.length ? clean : undefined }
}

/** 用了 v0.5 的字段就把版本号顶上去，别让产物自称 0.4 却带着 0.4 没有的字段 */
export function stampVersion(doc: Storyboard): Storyboard {
  const uses = doc.episodes.some((ep) =>
    ep.shots.some((s) => s.beats?.length || s.constraints?.length))
  if (!uses || doc.meta.schema_version === '0.5') return doc
  return { ...doc, meta: { ...doc.meta, schema_version: '0.5' } }
}

/** 垫图列表：空列表要把 reference_assets 整个去掉，prompts 空了也去掉，别留空壳 */
export function setReferenceAssets(shot: Shot, ids: string[]): Partial<Shot> {
  const rest = { ...shot.prompts }
  delete rest.reference_assets
  if (!ids.length) {
    return { prompts: Object.keys(rest).length ? rest : undefined }
  }
  return { prompts: { ...rest, reference_assets: ids } }
}
