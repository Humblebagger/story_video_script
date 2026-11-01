import type { CharacterAsset, Novel } from './types'

/** 主要人物：按出场章节数取前几个。出场数 = 章节摘要里提到其姓名或别名的章数；
 *  摘要里一个都没提到（或还没有摘要）时，全是 0，稳定排序下就是资产卡顺序。 */
export function mainCharacters(novel: Novel, limit = 5): CharacterAsset[] {
  const chars = novel.memory.assets.characters ?? []
  const syn = novel.memory.plot.chapters.map((c) => c.synopsis)
  const score = (c: CharacterAsset) => {
    const names = [c.name, ...(c.aliases ?? [])].filter(Boolean)
    return syn.filter((s) => names.some((n) => s.includes(n))).length
  }
  return chars.map((c, i) => ({ c, i, n: score(c) }))
    .sort((a, b) => b.n - a.n || a.i - b.i).slice(0, limit).map((x) => x.c)
}

