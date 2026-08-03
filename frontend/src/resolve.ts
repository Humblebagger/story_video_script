/** 溯源索引：把 IR 里的引用（C/S/P/A 资产 ID、unit ID）解析成可读信息，
 *  并建立「原文句子 → 引用它的镜头」的反向索引——IR 的核心主张是每句可溯源，
 *  界面要能双向查证，而不是只把 JSON 铺开。 */
import type { Shot, SourceUnit, Storyboard } from './types'

export interface ShotRef {
  shot: Shot
  episodeId: string
}

export interface Index {
  assetName: (id: string) => string
  /** 编辑分镜时给「场景」下拉用 */
  locationOptions: { id: string; name: string }[]
  unit: (id: string) => SourceUnit | undefined
  unitText: (id: string) => string
  /** 原文句子 ID → 引用它的镜头（source.unit_refs 命中） */
  shotsByUnit: Map<string, ShotRef[]>
  /** 原文句子 ID → 被哪些镜头当作旁白念出 */
  narratedUnits: Set<string>
  allShots: ShotRef[]
  stats: {
    units: number
    shots: number
    episodes: number
    narratedRatio: number
    inferredRatio: number
    coveredRatio: number
    unmapped: string[]
  }
}

export function buildIndex(doc: Storyboard): Index {
  const names = new Map<string, string>()
  const a = doc.assets ?? {}
  for (const list of [a.characters, a.locations, a.props, a.creatures]) {
    for (const item of list ?? []) names.set(item.id, item.name)
  }

  const units = new Map<string, SourceUnit>()
  for (const u of doc.source?.units ?? []) units.set(u.id, u)

  const shotsByUnit = new Map<string, ShotRef[]>()
  const narratedUnits = new Set<string>()
  const allShots: ShotRef[] = []

  for (const ep of doc.episodes ?? []) {
    for (const shot of ep.shots ?? []) {
      const ref = { shot, episodeId: ep.id }
      allShots.push(ref)
      for (const uid of shot.source?.unit_refs ?? []) {
        const bucket = shotsByUnit.get(uid)
        if (bucket) bucket.push(ref)
        else shotsByUnit.set(uid, [ref])
      }
      for (const uid of shot.narration?.unit_refs ?? []) narratedUnits.add(uid)
    }
  }

  const unitCount = units.size
  const inferred = allShots.filter((s) => s.shot.source?.derivation === 'inferred').length
  // coverage.unmapped_units 由后端校验器算出；缺省时用反向索引现推，保证界面始终有数
  const unmapped = doc.coverage?.unmapped_units
    ?? [...units.keys()].filter((id) => !shotsByUnit.has(id))

  return {
    assetName: (id) => names.get(id) ?? id,
    locationOptions: (a.locations ?? []).map((l) => ({ id: l.id, name: l.name })),
    unit: (id) => units.get(id),
    unitText: (id) => units.get(id)?.text ?? `（未找到 ${id}）`,
    shotsByUnit,
    narratedUnits,
    allShots,
    stats: {
      units: unitCount,
      shots: allShots.length,
      episodes: doc.episodes?.length ?? 0,
      narratedRatio: unitCount ? narratedUnits.size / unitCount : 0,
      inferredRatio: doc.coverage?.inferred_shot_ratio
        ?? (allShots.length ? inferred / allShots.length : 0),
      coveredRatio: unitCount ? (unitCount - unmapped.length) / unitCount : 0,
      unmapped,
    },
  }
}

export const pct = (v: number) => `${Math.round(v * 100)}%`
