/** 节点图的纯计算：三列布局、资产分组与排序、集标题、挂靠节点对齐与下推、独立素材、连线种类、高亮、适应画面。
 *  组件交互由 graph-view.test.tsx 覆盖。跑法：npm test */
import {
  ASSET_H, CARD_H, CARD_W, COL_ASSET, COL_CLIP, COL_FREE, EP_H, FREE_H, GAP, assetImage, edgePath, fitView,
  layoutGraph, related,
} from '../src/nodeGraph'
import type { GNode, Graph } from '../src/nodeGraph'
import type { Assets, FilmClip, FilmFreeNode, FilmSession } from '../src/types'

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }

const clip = (id: string, episode: string, over: Partial<FilmClip> = {}): FilmClip => ({
  id, episode, shots: [`${id}-S`], duration: 5, truncated: false, prompt: 'p', refs: [], dropped_refs: [],
  missing_refs: [], first_frame: null, frame_mode: null, fingerprint: 'fp', estimate_cny: 5, attempts: [],
  chosen: null, mute_native: false, uncertain: false, error: null, state: 'planned', ...over,
})
const free = (id: string, over: Partial<FilmFreeNode> = {}): FilmFreeNode => ({
  id, target: null, target_shots: null, target_lost: false, prompt: 'p', refs: [], first_frame: null, duration: 5,
  estimate_cny: 5, state: 'planned', error: null, uncertain: false, attempts: [], chosen: null, created_at: '',
  over_refs: false, ...over,
})
const session = (clips: FilmClip[], frees: FilmFreeNode[] = []): FilmSession => ({
  provider: 'fake', model: 'fake-1', resolution: '720p', audio_mode: 'tts_all', budget_cny: 200,
  confirm_over_cny: 20, spent_cny: 0, clips, free: frees, orphaned: [], counts: {}, reserved_cny: 0,
  uncertain_count: 0, remaining_cny: 0,
  options: { providers: ['fake'], models: {}, resolutions: ['720p'], cny_per_sec: {}, max_clip_sec: 10,
             max_refs: 3, audio_modes: ['tts_all'], rate_note: '' },
})
const img = (id: string) => [{ view: 'front' as const, uri: `https://img/${id}.png` }]
const assets = {
  characters: [{ id: 'C01', name: '甲', reference_images: img('C01') }, { id: 'C02', name: '乙', reference_images: img('C02') },
               { id: 'C03', name: '丙' }],
  creatures: [{ id: 'A01', name: '狗' }],
  locations: [{ id: 'S01', name: '街', angles: [{ uri: 'local/x.png' }, { uri: 'https://img/S01.png' }] }],
  props: [{ id: 'P01', name: '灯', reference_images: [{ uri: 'local/p.png' }] }],
} as unknown as Assets
const node = (g: Graph, id: string) => {
  const n = g.nodes.find((x) => x.id === id)
  if (!n) throw new Error(`✗ 没有节点 ${id}`)
  return n
}
const ids = (g: Graph, kind: GNode['kind']) => g.nodes.filter((n) => n.kind === kind).map((n) => n.id)

// 1. 三列、资产分组与排序、集标题
{
  const s = session([
    clip('E01-C01', 'E01', { refs: ['C02', 'S01'], missing_refs: ['A01'] }),
    clip('E01-C02', 'E01', { refs: ['C02'], dropped_refs: ['C01'], first_frame: 'relay:E01-C01' }),
    clip('E02-C01', 'E02', { refs: ['C01', '__style__'] }),
  ])
  const g = layoutGraph({ session: s, assets, hasStyle: true, styleUrl: 'blob:style' })
  must(ids(g, 'asset').join() === 'asset:__style__,asset:C02,asset:C01,asset:A01,asset:S01',
       '风格在前；角色按被用段数降序；没图又没被用到的不列；缺图但被用到的要列')
  must(g.nodes.filter((n) => n.kind === 'asset').every((n) => n.x === COL_ASSET), '资产在左列')
  const style = node(g, 'asset:__style__')
  must(style.kind === 'asset' && style.role === 'style' && style.image === 'blob:style' && style.usedBy === 1, '风格图节点')
  const c02 = node(g, 'asset:C02')
  must(c02.kind === 'asset' && c02.usedBy === 2 && c02.image === 'https://img/C02.png' && c02.y === ASSET_H + GAP, '角色卡')
  const s01 = node(g, 'asset:S01')
  must(s01.kind === 'asset' && s01.image === 'https://img/S01.png', '场景取第一张可用的机位图')
  must(ids(g, 'episode').join() === 'ep:E01,ep:E02', '每集一个标题')
  must(ids(g, 'clip').join() === 'E01-C01,E01-C02,E02-C01' && g.nodes.filter((n) => n.kind === 'clip').every((n) => n.x === COL_CLIP),
       '剧本段按顺序在中列')
  const c1 = node(g, 'E01-C01'), c2 = node(g, 'E01-C02'), ep2 = node(g, 'ep:E02')
  must(node(g, 'ep:E01').y === 0 && c1.y === EP_H + GAP && c2.y === c1.y + CARD_H + GAP && ep2.y === c2.y + CARD_H + GAP,
       '集标题与段竖排')
  console.log('1. 三列与资产分组 ✓')
}

// 2. 自由节点：挂靠的从目标段那一行排起、后面的段下推；独立素材与挂靠段不存在的排在最下面
{
  const s = session([clip('E01-C01', 'E01'), clip('E01-C02', 'E01')],
    [free('F02', { target: 'E01-C01' }), free('F01', { target: 'E01-C01' }), free('F03'), free('F04', { target: 'E09-C09' })])
  const g = layoutGraph({ session: s, assets: {}, hasStyle: false })
  const f1 = node(g, 'F01'), f2 = node(g, 'F02'), c1 = node(g, 'E01-C01'), c2 = node(g, 'E01-C02')
  const f3 = node(g, 'F03'), f4 = node(g, 'F04')
  must(f1.x === COL_FREE && f1.y === c1.y && f2.y === f1.y + FREE_H + GAP && f1.h === FREE_H, '挂靠节点按 id 从目标段那一行排')
  must(c2.y === f2.y + FREE_H + GAP, '后面的段下推，不重叠')
  must(f3.y === c2.y + CARD_H + GAP && f4.y === f3.y + FREE_H + GAP, '独立素材在最下面')
  must(g.width === COL_FREE + CARD_W && g.height === f4.y + FREE_H, '画布大小')
  must(ids(g, 'asset').length === 0, '没有资产就没有左列')
  console.log('2. 自由节点位置 ✓')
}

// 3. 连线：参考 / 被裁 / 缺图 / 接力与尾帧首帧 / 挂靠；未知资产与关键帧不画；重复去重
const g3 = layoutGraph({
  session: session([
    clip('E01-C01', 'E01', { refs: ['C01', 'C01'], dropped_refs: ['C02'], missing_refs: ['A01'] }),
    clip('E01-C02', 'E01', { first_frame: 'relay:E01-C01', refs: ['ZZ'] }),
  ], [free('F01', { target: 'E01-C02', refs: ['C02'], first_frame: 'tail:E01-C01' }),
      free('F02', { first_frame: 'keyframe:E01-SH001' })]),
  assets, hasStyle: false,
})
{
  must(g3.edges.map((e) => e.id).sort().join('|') === [
    'dropped:asset:C02>E01-C01', 'frame:E01-C01>E01-C02', 'frame:E01-C01>F01', 'missing:asset:A01>E01-C01',
    'ref:asset:C01>E01-C01', 'ref:asset:C02>F01', 'target:F01>E01-C02',
  ].sort().join('|'), '连线种类与去重：' + g3.edges.map((e) => e.id).join(' '))
  console.log('3. 连线 ✓')
}

// 4. 高亮相关节点；连线路径；适应画面；资产取图
{
  const lit = related(g3, 'E01-C01')
  must(['E01-C01', 'asset:C01', 'asset:C02', 'asset:A01', 'E01-C02', 'F01'].every((id) => lit.has(id)) && !lit.has('F02'),
       '选中节点与直接相连的节点')
  must(related(g3, null).size === 0, '没选中什么都不亮')
  const a = node(g3, 'asset:C01'), c1 = node(g3, 'E01-C01'), c2 = node(g3, 'E01-C02'), f1 = node(g3, 'F01')
  must(edgePath(a, c1).startsWith(`M${a.x + a.w},${a.y + a.h / 2} C`), '左列到中列：从右边出')
  must(edgePath(f1, c2).startsWith(`M${f1.x},`) && edgePath(f1, c2).endsWith(`${c2.x + c2.w},${c2.y + c2.h / 2}`),
       '右列连回中列：从左边出、右边进')
  must(edgePath(c1, c2).includes(`${c1.x + c1.w + 60}`), '同一列：从右边绕出去')
  const v = fitView(g3, 800, 600)
  must(v.scale <= 1 && v.scale >= 0.3 && v.x === 24 && v.y === 24, '适应画面')
  must(fitView(g3, 0, 0).scale === 1, '量不到尺寸时不缩放')
  must(assetImage(assets, 'location', 'S01') === 'https://img/S01.png' && assetImage(assets, 'prop', 'P01') === null
       && assetImage(assets, 'character', 'C09') === null, '资产取第一张可用图')
  console.log('4. 高亮、路径、适应画面 ✓')
}

// 5. 空会话：没有段也没有自由节点
{
  const g = layoutGraph({ session: session([]), assets: {}, hasStyle: false })
  must(g.nodes.length === 0 && g.height === 0 && g.edges.length === 0, '空会话 0 节点、高度 0')
  console.log('5. 空会话 ✓')
}

console.log('\nALL PASS')
