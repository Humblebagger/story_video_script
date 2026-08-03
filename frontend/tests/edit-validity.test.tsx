/** 编辑不变量：界面上的编辑改完，产物仍是合法、可溯源、机器可校验的 IR。
 *
 *  JS 侧断言 ID/跨引用/原文逐字未变；若能找到后端 venv，再交给**真实的** Python
 *  校验器复核一遍——「改了不会破坏校验」这种话，只有真跑校验器才算数。
 *
 *  跑法：npm test
 */
import { execFileSync } from 'node:child_process'
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { updateAsset, updateShot } from '../src/edit'
import type { Storyboard } from '../src/types'

const YAO = '../backend/tests/real_text_yao'
const before: Storyboard = JSON.parse(readFileSync(`${YAO}/output_merged.json`, 'utf8'))
let doc = before

// 模拟用户在界面上的一通编辑：资产卡 + 分镜呈现层
doc = updateAsset(doc, 'characters', 'C01', {
  name: '华老栓（人工改名）',
  aliases: ['老栓', '华大爷'],
  appearance: { ...(before.assets!.characters![0].appearance ?? {}),
                age: '六十岁上下', hair: '花白' },
  visual_prompt: '驼背老者，人工重写的画面描述',
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
must(JSON.stringify(doc.source.units) === JSON.stringify(before.source.units),
     '原文 units 必须逐字未变')
console.log('不变量 ok：内容已改 / ID·跨引用·台词旁白·原文 逐字未变')

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
