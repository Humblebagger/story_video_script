/** 节点图的纯计算：资产、剧本段、自由节点三列自动布局与连线（设计文档 docs/specs/2026-11-11-film-node-graph-design.md §5.2）。
 *  不读 DOM，组件 NodeGraph 只按这里的坐标画；单测见 tests/node-graph.test.ts。 */
import { STYLE_REF, freeNodes } from './film'
import type { Assets, FilmClip, FilmFreeNode, FilmSession } from './types'

export const ASSET_W = 208
export const ASSET_H = 66
export const CARD_W = 260
/** 剧本段卡高（含最多两行镜头小标签）；自由节点卡带编辑项，更高 */
export const CARD_H = 276
export const FREE_H = 340
export const EP_H = 28
export const GAP = 24
export const COL_GAP = 160
export const COL_ASSET = 0
export const COL_CLIP = ASSET_W + COL_GAP
export const COL_FREE = COL_CLIP + CARD_W + COL_GAP
/** 同一列之间的连线（接力、自由节点互作首帧）从右边绕出去的距离 */
const BULGE = 60
const PAD = 24

export type AssetRole = 'style' | 'character' | 'creature' | 'location' | 'prop'
interface Box { id: string; x: number; y: number; w: number; h: number }
export type GNode =
  | (Box & { kind: 'asset'; assetId: string; role: AssetRole; name: string; image: string | null; usedBy: number })
  | (Box & { kind: 'episode'; episode: string })
  | (Box & { kind: 'clip'; clip: FilmClip })
  | (Box & { kind: 'free'; node: FilmFreeNode })
export type EdgeKind = 'ref' | 'dropped' | 'missing' | 'frame' | 'target'
export interface GEdge { id: string; from: string; to: string; kind: EdgeKind }
export interface Graph { nodes: GNode[]; edges: GEdge[]; width: number; height: number }

export const assetNodeId = (assetId: string) => `asset:${assetId}`

const usable = (uri?: string | null): uri is string => !!uri && /^(https?:|data:image\/)/.test(uri)

type ImageCard = { id: string; name?: string; reference_images?: { uri?: string }[] }

/** 资产卡的第一张可用图（与后端自由节点取图同一规则：不分着装 / 机位） */
export function assetImage(assets: Assets, role: AssetRole, id: string): string | null {
  if (role === 'location') {
    return assets.locations?.find((x) => x.id === id)?.angles?.find((a) => usable(a.uri))?.uri ?? null
  }
  const list = (role === 'character' ? assets.characters : role === 'creature' ? assets.creatures
    : role === 'prop' ? assets.props : undefined) as ImageCard[] | undefined
  return list?.find((x) => x.id === id)?.reference_images?.find((r) => usable(r.uri))?.uri ?? null
}

export interface GraphInput {
  session: FilmSession
  assets: Assets
  /** 本小说当前有风格图 */
  hasStyle: boolean
  styleUrl?: string | null
}

export function layoutGraph({ session, assets, hasStyle, styleUrl = null }: GraphInput): Graph {
  const clips = session.clips
  const frees = freeNodes(session)
  // 每个资产被几段剧本段用到（只数 refs）；出现在任何连线里的资产都要上图
  const usedBy = new Map<string, number>()
  const mentioned = new Set<string>()
  for (const c of clips) {
    // 同一段里重复引用（如同一场景两个机位）只算一段
    for (const id of new Set(c.refs)) usedBy.set(id, (usedBy.get(id) ?? 0) + 1)
    for (const id of [...c.refs, ...c.dropped_refs, ...c.missing_refs]) mentioned.add(id)
  }
  for (const n of frees) for (const id of n.refs) mentioned.add(id)

  const nodes: GNode[] = []
  let y = 0
  const pushAsset = (assetId: string, role: AssetRole, name: string, image: string | null) => {
    nodes.push({ kind: 'asset', id: assetNodeId(assetId), assetId, role, name, image, usedBy: usedBy.get(assetId) ?? 0,
                 x: COL_ASSET, y, w: ASSET_W, h: ASSET_H })
    y += ASSET_H + GAP
  }
  if (hasStyle || mentioned.has(STYLE_REF)) pushAsset(STYLE_REF, 'style', '', styleUrl)
  // 角色按被用段数降序（同数按资产卡顺序）；生物、场景、道具按资产 id 排
  const chars = (assets.characters ?? []).map((a, i) => ({ a, i }))
    .sort((p, q) => (usedBy.get(q.a.id) ?? 0) - (usedBy.get(p.a.id) ?? 0) || p.i - q.i).map((x) => x.a)
  const byId = <T extends { id: string }>(list?: T[]) => [...(list ?? [])].sort((p, q) => p.id.localeCompare(q.id))
  const groups: [AssetRole, { id: string; name?: string }[]][] = [
    ['character', chars], ['creature', byId(assets.creatures)], ['location', byId(assets.locations)],
    ['prop', byId(assets.props)],
  ]
  for (const [role, list] of groups) {
    for (const a of list) {
      const image = assetImage(assets, role, a.id)
      if (mentioned.has(a.id) || image) pushAsset(a.id, role, a.name ?? a.id, image)
    }
  }
  const assetBottom = y

  // 中列剧本段（每集前一行集标题）；右列挂靠的自由节点从目标段那一行排起，排不下就把后面的段下推
  y = 0
  const clipIds = new Set(clips.map((c) => c.id))
  const attached = new Map<string, FilmFreeNode[]>()
  const standalone: FilmFreeNode[] = []
  for (const n of [...frees].sort((p, q) => p.id.localeCompare(q.id))) {
    if (n.target && clipIds.has(n.target)) attached.set(n.target, [...(attached.get(n.target) ?? []), n])
    else standalone.push(n)
  }
  let ep: string | null = null
  for (const c of clips) {
    if (c.episode !== ep) {
      ep = c.episode
      nodes.push({ kind: 'episode', id: `ep:${ep}`, episode: ep, x: COL_CLIP, y, w: CARD_W, h: EP_H })
      y += EP_H + GAP
    }
    nodes.push({ kind: 'clip', id: c.id, clip: c, x: COL_CLIP, y, w: CARD_W, h: CARD_H })
    const mine = attached.get(c.id) ?? []
    mine.forEach((n, i) => nodes.push({ kind: 'free', id: n.id, node: n, x: COL_FREE, y: y + i * (FREE_H + GAP),
                                        w: CARD_W, h: FREE_H }))
    y += Math.max(CARD_H, mine.length * (FREE_H + GAP) - GAP) + GAP
  }
  for (const n of standalone) {
    nodes.push({ kind: 'free', id: n.id, node: n, x: COL_FREE, y, w: CARD_W, h: FREE_H })
    y += FREE_H + GAP
  }

  const has = new Set(nodes.map((n) => n.id))
  const edges: GEdge[] = []
  const seen = new Set<string>()
  const add = (from: string, to: string, kind: EdgeKind) => {
    const id = `${kind}:${from}>${to}`
    if (!has.has(from) || !has.has(to) || seen.has(id)) return
    seen.add(id)
    edges.push({ id, from, to, kind })
  }
  for (const c of clips) {
    for (const id of c.refs) add(assetNodeId(id), c.id, 'ref')
    for (const id of c.dropped_refs) add(assetNodeId(id), c.id, 'dropped')
    for (const id of c.missing_refs) add(assetNodeId(id), c.id, 'missing')
    if (c.first_frame?.startsWith('relay:')) add(c.first_frame.slice('relay:'.length), c.id, 'frame')
  }
  for (const n of frees) {
    for (const id of n.refs) add(assetNodeId(id), n.id, 'ref')
    if (n.first_frame?.startsWith('tail:')) add(n.first_frame.slice('tail:'.length), n.id, 'frame')
    if (n.target) add(n.id, n.target, 'target')
  }
  return { nodes, edges, width: COL_FREE + CARD_W, height: Math.max(0, Math.max(assetBottom, y) - GAP) }
}

/** 连线路径（三次贝塞尔）：从左往右的从源右边出、目标左边进；从右往左的反过来；
 *  同一列的从源右边出、绕回目标右边进，不穿过卡片 */
export function edgePath(a: Box, b: Box): string {
  const ay = a.y + a.h / 2
  const by = b.y + b.h / 2
  if (a.x === b.x) {
    const x = a.x + a.w
    return `M${x},${ay} C${x + BULGE},${ay} ${x + BULGE},${by} ${x},${by}`
  }
  const right = a.x < b.x
  const sx = right ? a.x + a.w : a.x
  const ex = right ? b.x : b.x + b.w
  const dx = Math.max(40, Math.abs(ex - sx) / 2) * (right ? 1 : -1)
  return `M${sx},${ay} C${sx + dx},${ay} ${ex - dx},${by} ${ex},${by}`
}

/** 与 id 直接相连的节点（含自己）；没选中返回空集 */
export function related(g: Graph, id: string | null): Set<string> {
  const out = new Set<string>()
  if (!id) return out
  out.add(id)
  for (const e of g.edges) {
    if (e.from === id) out.add(e.to)
    if (e.to === id) out.add(e.from)
  }
  return out
}

/** 适应画面：整张图放进 w × h（留边），不放大，最小 0.3；量不到尺寸时原样 */
export function fitView(g: Graph, w: number, h: number) {
  if (w <= 0 || h <= 0 || !g.width || !g.height) return { scale: 1, x: PAD, y: PAD }
  const scale = Math.min(1, Math.max(0.3, Math.min((w - 2 * PAD) / g.width, (h - 2 * PAD) / g.height)))
  return { scale, x: PAD, y: PAD }
}
