/** 编辑不变量：界面上的编辑改完，产物仍是合法、可溯源、机器可校验的 IR。
 *
 *  JS 侧断言 ID/跨引用/原文逐字未变；若能找到后端 venv，再交给**真实的** Python
 *  校验器复核一遍——「改了不会破坏校验」这种话，只有真跑校验器才算数。
 *
 *  跑法：npm test
 */
import { execFileSync } from 'node:child_process'
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import {
  addBeat, attachCard, detachCard, removeBeat, setConstraints, setReferenceAssets,
  setVariant, stampVersion, updateAsset, updateBeat, updateShot,
} from '../src/edit'
import { buildIndex } from '../src/resolve'
import type { Storyboard } from '../src/types'

const YAO = '../backend/tests/real_text_yao'
const before: Storyboard = JSON.parse(readFileSync(`${YAO}/output_merged.json`, 'utf8'))
let doc: Storyboard = before

// 模拟用户在界面上的一通编辑：资产卡 + 分镜呈现层
doc = updateAsset(doc, 'characters', 'C01', {
  name: '华老栓（人工改名）',
  aliases: ['老栓', '华大爷'],
  appearance: { ...(before.assets!.characters![0].appearance ?? {}),
                age: '六十岁上下', hair: '花白' },
  visual_prompt: '驼背老者，人工重写的画面描述',
})
// 改服装描述：schema 里 outfits 只有 {id, description} 且拒绝未知字段，
// 界面若把描述写进 name/visual_prompt，整份产物当场校验失败（曾经就是如此）
doc = updateAsset(doc, 'characters', 'C04', {
  outfits: before.assets!.characters!.find((c) => c.id === 'C04')!.outfits!.map((o) =>
    (o.id === 'loose_black' ? { ...o, description: o.description + '（人工补记：袖口磨损）' } : o)),
})
doc = updateAsset(doc, 'props', 'P01', {
  states: before.assets!.props!.find((p) => p.id === 'P01')!.states!.map((st) =>
    (st.id === 'charred' ? { ...st, description: st.description + '（人工补记：边缘发脆）' } : st)),
})
// 设定图必须说清画的是哪套变体：标错就是拿另一套衣服的脸去垫图，lint 会逐条核对
doc = updateAsset(doc, 'characters', 'C04', {
  reference_images: [
    { view: 'front', uri: 'assets/C04_lb_front.png', outfit: 'loose_black' },
    { view: 'three_quarter', uri: 'assets/C04_lb_tq.png', outfit: 'loose_black' },
    { view: 'close_up', uri: 'assets/C04_lb_face.png', outfit: 'loose_black' },
  ],
  constraints: ['不要平滑笔触', '不要加照片级细节', '不要改画风'],
})
doc = updateAsset(doc, 'props', 'P01', {
  reference_images: [{ view: 'close_up', uri: 'assets/P01_charred.png', state: 'charred' }],
})
doc = updateAsset(doc, 'locations', 'S02', { name: '里屋（改）', lighting_defaults: '油灯昏黄' })
doc = updateAsset(doc, 'props', 'P03', { name: '灯笼（改）' })
const ep = before.episodes[0]
doc = updateShot(doc, ep.id, ep.shots[0].id, {
  action: '人工重写的画面描述', duration_sec: 8, shot_size: 'close_up',
})

/** 所有被跨引用的标识符——这些一个字都不能变 */
const refs = (d: Storyboard) => JSON.stringify([
  (d.assets!.characters ?? []).map((c) => [c.id, (c.outfits ?? []).map((o) => o.id)]),
  (d.assets!.locations ?? []).map((c) => c.id),
  (d.assets!.props ?? []).map((c) => [c.id, (c.states ?? []).map((s) => s.id)]),
  (d.assets!.creatures ?? []).map((c) => c.id),
  d.episodes.flatMap((e) => e.shots.map((s) => [
    s.id, s.location_ref, s.source.unit_refs, s.source.derivation,
    (s.characters ?? []).map((c) => [c.ref, c.outfit]),
    (s.prop_refs ?? []).map((p) => [p.ref, p.state]),
    (s.dialogue ?? []).map((x) => [x.character_ref, x.text]),
    s.narration?.text ?? null])),
])

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }

must(doc !== before, '编辑应产生新对象（不可变更新）')
must(doc.assets!.characters![0].name === '华老栓（人工改名）', '资产内容应已更新')
must(before.assets!.characters![0].name === '华老栓', '原文档不得被就地修改')
must(refs(doc) === refs(before), 'ID / 跨引用 / 台词旁白文本必须逐字未变')
const of4 = doc.assets!.characters!.find((c) => c.id === 'C04')!.outfits!
  .find((o) => o.id === 'loose_black')!
must(of4.description.includes('袖口磨损'), '服装描述应已更新')
must(Object.keys(of4).join() === 'id,description',
     `服装条目只能有 id 与 description 两个字段，实为 ${Object.keys(of4).join()}`)
const st1 = doc.assets!.props!.find((p) => p.id === 'P01')!.states!
  .find((x) => x.id === 'charred')!
must(Object.keys(st1).join() === 'id,description',
     `道具形态条目只能有 id 与 description，实为 ${Object.keys(st1).join()}`)
const sheet = doc.assets!.characters!.find((c) => c.id === 'C04')!.reference_images!
must(sheet.length === 3 && sheet.every((x) => x.outfit === 'loose_black'),
     '三视图设定图应全部标注到同一套服装')
must(sheet.some((x) => x.view === 'close_up'), 'close_up 是本轮新加的视图，应能用')
const outfitIds = new Set(doc.assets!.characters!.find((c) => c.id === 'C04')!
  .outfits!.map((o) => o.id))
must(sheet.every((x) => !x.outfit || outfitIds.has(x.outfit)),
     '设定图标注的 outfit 必须真实存在，否则垫图垫错衣服')
must(JSON.stringify(doc.source.units) === JSON.stringify(before.source.units),
     '原文 units 必须逐字未变')
console.log('不变量 ok：内容已改 / ID·跨引用·台词旁白·原文 逐字未变')

/* ---------- 挂卡：@ 上去的引用必须是合法引用 ----------
 *
 *  这一段是整个特性的成败所在。lint 对引用有一串硬规矩（角色有 outfits 必须选中其一、
 *  生物不得带 outfit、道具有 states 必须填且只能填集合内的、没有 states 则不许填），
 *  界面若把这些规矩记漏一条，人工挂出来的镜头当场就是废品。所以这里逐条挂给它看，
 *  最后仍交给真实的 Python 校验器判。 */
const idx = buildIndex(doc)
const card = (id: string) => {
  const c = idx.card(id)
  if (!c) throw new Error(`✗ 索引里找不到资产卡 ${id}`)
  return c
}
const ep2 = doc.episodes[0]
const target = ep2.shots[1]        // 只挂了 C01 的一个镜头
const shotOf = (d: Storyboard) =>
  d.episodes[0].shots.find((s) => s.id === target.id)!
const apply = (patch: Partial<typeof target>) => {
  doc = updateShot(doc, ep2.id, target.id, patch)
}

apply(attachCard(shotOf(doc), card('C04')))          // 有 2 套服装的角色
apply(attachCard(shotOf(doc), card('A01')))          // 生物：不得带 outfit
apply(attachCard(shotOf(doc), card('P01')))          // 有 5 种状态的道具
apply(attachCard(shotOf(doc), card('P02')))          // 无状态道具：不许填 state
apply(attachCard(shotOf(doc), card('S04')))          // 场景是单选

const after = shotOf(doc)
const ch = (id: string) => after.characters!.find((c) => c.ref === id)!
const pr = (id: string) => after.prop_refs!.find((p) => p.ref === id)!

must(ch('C04').outfit === 'default', '角色卡有 outfits，挂上时必须自动选中其一')
must(!('outfit' in ch('A01')), '生物引用不得带 outfit（lint 会直接报错）')
must(pr('P01').state === 'fresh_bleeding', '道具卡有 states，挂上时必须自动填 state')
must(!('state' in pr('P02')), '无 states 的道具不许填 state')
must(after.location_ref === 'S04', '挂场景应落到 location_ref')
must(ch('C01') !== undefined, '挂新卡不得挤掉原有的引用')

// 幂等：同一张卡挂两次不该挂出两条
const dup = attachCard(after, card('C04'))
must(Object.keys(dup).length === 0, '已挂过的卡再挂应是空 patch')

// 换服装 / 换形态
apply(setVariant(shotOf(doc), card('C04'), 'loose_black'))
apply(setVariant(shotOf(doc), card('P01'), 'paper_wrapped'))
must(shotOf(doc).characters!.find((c) => c.ref === 'C04')!.outfit === 'loose_black',
     '换服装应落到 outfit')
must(shotOf(doc).prop_refs!.find((p) => p.ref === 'P01')!.state === 'paper_wrapped',
     '换形态应落到 state')

// 垫图列表，以及摘卡时的连带清理
apply(setReferenceAssets(shotOf(doc), ['C04', 'P01', 'S04']))
must(shotOf(doc).prompts!.reference_assets!.length === 3, '垫图列表应写进 prompts')
apply(detachCard(shotOf(doc), card('P01')))
must(!shotOf(doc).prop_refs!.some((p) => p.ref === 'P01'), '摘卡应移除引用')
must(!shotOf(doc).prompts!.reference_assets!.includes('P01'),
     '摘掉的卡必须同时从垫图列表里清掉，否则会垫一张画面里没有的卡')

// 垫图清空要连 prompts 空壳一起去掉——schema 允许空对象，但留着是噪声
const cleared = updateShot(doc, ep2.id, target.id, setReferenceAssets(shotOf(doc), []))
must(shotOf(cleared).prompts === undefined, '垫图清空后不应留下空的 prompts')

must(JSON.stringify(doc.source.units) === JSON.stringify(before.source.units),
     '挂卡不得触碰原文')
must(JSON.stringify(shotOf(doc).source) === JSON.stringify(target.source),
     '挂卡不得触碰溯源锚点')
must(JSON.stringify(shotOf(doc).narration) === JSON.stringify(target.narration),
     '挂卡不得触碰旁白')
console.log('挂卡 ok：服装/形态自动合规 · 生物不带 outfit · 无状态道具不填 state · 摘卡连带清垫图')

/* ---------- v0.5：镜头内阶段与负面约束 ----------
 *
 *  镜头有 duration_sec，各拍也有，两者必须自洽——lint 会逐个对账。所以界面每次
 *  改拍都得把镜头时长同步过去，不能指望用户自己算。 */
const beatShot = ep2.shots[2]
const beatOf = (d: Storyboard) =>
  d.episodes[0].shots.find((s) => s.id === beatShot.id)!
const applyBeat = (patch: Partial<typeof beatShot>) => {
  doc = updateShot(doc, ep2.id, beatShot.id, patch)
}

applyBeat(addBeat(beatOf(doc)))
must(beatOf(doc).beats!.length === 2, '首次拆拍应直接给出两拍——一拍等于没分，schema 也不收')
must(beatOf(doc).beats![0].action === beatShot.action,
     '拆出的第一拍应带上整镜原有的画面描述，别让人重打一遍')
must(beatOf(doc).duration_sec === beatShot.duration_sec,
     '拆拍不该改变镜头总时长')

applyBeat(addBeat(beatOf(doc)))
applyBeat(updateBeat(beatOf(doc), 1, { action: '猛地抬头，眨眼把泪逼回去', lighting: '右侧光，左半张脸沉入阴影' }))
applyBeat(updateBeat(beatOf(doc), 2, { action: '一声无声的笑', duration_sec: 3.5, lighting: '背光只剩轮廓' }))
const sum = beatOf(doc).beats!.reduce((a, b) => a + b.duration_sec, 0)
must(Math.abs(beatOf(doc).duration_sec - sum) < 0.001,
     `镜头时长必须等于各拍之和，实为 ${beatOf(doc).duration_sec} vs ${sum}`)

applyBeat(setConstraints(['画面内不出现任何灯具', '无镜头光晕', '全程不切镜', '  ']))
must(beatOf(doc).constraints!.length === 3, '空白约束应被丢掉——lint 会判空约束为错')

doc = stampVersion(doc)
must(doc.meta.schema_version === '0.5', '用了 v0.5 的字段就该把版本号顶上去')

// 删到只剩一拍时应整个撤掉分拍
const undone = updateShot(doc, ep2.id, beatShot.id, removeBeat(beatOf(doc), 0))
const undone2 = updateShot(undone, ep2.id, beatShot.id, removeBeat(beatOf(undone), 0))
must(beatOf(undone2).beats === undefined, '删到只剩一拍应整个撤掉分拍')
console.log('镜头内阶段 ok：拆拍带入原内容 · 时长自动自洽 · 空约束剔除 · 版本号自动顶到 0.5')

// 交给真实校验器复核
const out = '/tmp/edited_yao.json'
writeFileSync(out, JSON.stringify(doc, null, 2))
const py = '../backend/.venv/bin/python'
if (!existsSync(py)) {
  console.log('跳过真实校验器复核（未找到 ../backend/.venv，先建后端 venv）')
} else {
  for (const [name, args] of [
    ['lint', ['../backend/tools/lint_storyboard.py', out]],
    ['保真', ['../backend/tools/check_fidelity.py', out, `${YAO}/input_full.txt`]],
  ] as [string, string[]][]) {
    const r = execFileSync(py, args, { encoding: 'utf8' })
    must(r.includes('PASS'), `编辑后的产物未通过真实 ${name} 校验：\n${r}`)
    console.log(`真实 ${name} 校验 ok：${r.trim().split('\n').pop()}`)
  }
}
console.log('\nALL PASS')
