/** 时间轴画布的布局计算与编辑操作层单测（纯函数，不起 DOM）。
 *
 *  跑法：npm test
 */
import { execFileSync } from 'node:child_process'
import { existsSync, readFileSync } from 'node:fs'
import {
  buildTimeline, fitText, fmtClock, litFraction, playableSeconds, shotIndexAt,
} from '../src/timeline'
import { applyOp } from '../src/timelineOps'
import type { Storyboard } from '../src/types'

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }
const near = (a: number, b: number) => Math.abs(a - b) < 1e-6

const shot = (id: string, dur: number, extra: Record<string, unknown> = {}) => ({
  id, duration_sec: dur, shot_size: 'medium', action: `${id} 画面`,
  source: { unit_refs: ['u0001'], derivation: 'explicit' }, ...extra })

const DOC = {
  meta: {}, source: { units: [] },
  assets: {
    characters: [{ id: 'C01', name: '华老栓' }, { id: 'C02', name: '华大妈' }],
    creatures: [{ id: 'A01', name: '乌鸦' }],
    locations: [{ id: 'S01', name: '茶馆' }, { id: 'S02', name: '刑场' }],
  },
  episodes: [
    { id: 'E01', title: '开端', music: { curve: [
        { from_shot: 'E01-SH001', to_shot: 'E01-SH002', mood: 'tense', intensity: 'mid' },
        { from_shot: 'E01-SH003', mood: 'sorrow' }] },
      shots: [
        shot('E01-SH001', 4, { location_ref: 'S01',
             characters: [{ ref: 'C01', action: '推门', expression: '疲惫' }] }),
        // 旁白 18 字 → 4s 念完，比标称 2s 长：可播时长按 4s 算
        shot('E01-SH002', 2, { location_ref: 'S01',
             characters: [{ ref: 'C01' }, { ref: 'C02', action: '咳嗽' }],
             narration: { text: '一二三四五六七八九十一二三四五六七八', order: 'after_dialogue' },
             dialogue: [{ character_ref: 'C02', text: '小栓' }] }),
        shot('E01-SH003', 3, { location_ref: 'S02', characters: [{ ref: 'A01' }] }),
      ] },
    { id: 'E02', shots: [shot('E02-SH001', 5, { location_ref: 'S02',
                                                characters: [{ ref: 'C01', action: '坐下' }] })] },
  ],
} as unknown as Storyboard

const tl = buildTimeline(DOC)

// 1. 可播时长：max(标称, 念完旁白台词)，与后端 speech_seconds 同口径
must(near(playableSeconds(DOC.episodes[0].shots[1]), 20 / 4.5), '念不完时按念完所需算')
must(near(tl.total, 4 + 20 / 4.5 + 3 + 5), `总时长应按可播时长累计，实为 ${tl.total}`)
must(tl.shots.map((s) => s.index).join() === '0,1,2,3' && tl.shots[3].episodeId === 'E02',
     '镜头跨集连续编号')
must(near(tl.shots[2].start, tl.shots[1].end), '镜头首尾相接')
console.log('1. 可播时长 → max(标称, 念完所需) / 跨集连续 ✓')

// 2. 集、场景条：同一场景的连续镜头并成一段，跨集也并（画面上就是没换地方）
must(tl.episodes.map((e) => e.label).join() === 'E01 开端,E02', '集条')
must(tl.scenes.map((s) => s.label).join() === 'S01 茶馆,S02 刑场', `场景条应合并连续同场，实为 ${
  tl.scenes.map((s) => s.label)}`)
must(near(tl.scenes[1].end, tl.total), '刑场一段从 E01 末镜延续到 E02')
console.log('2. 集条 / 场景条（连续同场合并）✓')

// 3. 角色泳道：按首次出场排序；没写本镜动作就退回镜头画面描述；生物也有泳道
must(tl.characters.map((c) => c.name).join() === '华老栓,华大妈,乌鸦', '泳道按首次出场')
const c01 = tl.characters[0]
must(c01.nodes.length === 3 && c01.nodes[0].action === '推门' && c01.nodes[0].expression === '疲惫',
     '节点带动作与表情')
must(c01.nodes[1].fromShotAction && c01.nodes[1].action === 'E01-SH002 画面', '缺动作退回镜头描述')
must(near(c01.nodes[2].t, (tl.shots[3].start + tl.shots[3].end) / 2), '节点画在镜头中点')
console.log('3. 角色泳道 → 首次出场排序 / 动作退回镜头描述 / 生物入道 ✓')

// 4. 旁白台词段：按 narration.order 排先后，按字数分配，不越出镜头
const sp = tl.speech.filter((s) => s.shotId === 'E01-SH002')
must(sp.map((s) => s.kind).join() === 'dialogue,narration', 'after_dialogue：先台词后旁白')
must(sp[0].who === '华大妈' && near(sp[0].end - sp[0].start, 2 / 4.5), '台词带说话人、按字数计时')
must(sp[1].end <= tl.shots[1].end + 1e-9, '不越出镜头')
console.log('4. 旁白/台词段 → 顺序 / 说话人 / 按字数计时 ✓')

// 5. BGM 情绪段：from/to 映射到镜头时间，缺 to 取本集末镜
must(tl.music.length === 2 && tl.music[0].mood === 'tense' && near(tl.music[0].end, tl.shots[1].end),
     '情绪段覆盖 from..to')
must(near(tl.music[1].start, tl.shots[2].start) && near(tl.music[1].end, tl.shots[2].end),
     '缺 to_shot 取本集末镜，不跨到下一集')
console.log('5. BGM 情绪段 → 镜头区间映射 ✓')

// 6. 播放头：时刻 → 当前镜头；连线点亮比例
must(shotIndexAt(tl, 0) === 0 && shotIndexAt(tl, 4) === 1 && shotIndexAt(tl, 3.99) === 0, '边界归属')
must(shotIndexAt(tl, -5) === 0 && shotIndexAt(tl, 1e9) === 3, '超出两端夹到首末镜')
must(litFraction(2, 4, 1) === 0 && litFraction(2, 4, 3) === 0.5 && litFraction(2, 4, 9) === 1, '点亮比例')
must(fmtClock(75.9) === '1:15', '时钟格式')
console.log('6. 播放头 → 当前镜头 / 连线逐段点亮 ✓')

// 6b. 文字按像素宽度截断：SVG 不会自己裁切，放不下就截断或干脆不写，相邻标签才不会叠在一起
must(fitText('华家茶馆', 100) === '华家茶馆', '放得下原样返回')
must(fitText('S01 华家茶馆·店堂', 60) === 'S01 华家…', `截断后带省略号，实为 ${fitText('S01 华家茶馆·店堂', 60)}`)
must(fitText('华家茶馆·店堂', 20) === '', '剩不到两个字就不写（「华…」这种残片没有信息）')
must(fitText('S01 华家茶馆', 30, 11, 4) === '', '可以要求至少留几个字')
must(fitText('SH012', 20, 10, Infinity) === '' && fitText('SH012', 40, 10, Infinity) === 'SH012',
     '镜头号放不下就整个不写，不截成「SH…」')
console.log('6b. 标签按宽度截断 → 不溢出 / 不留残片 ✓')

// 7. 操作层：改时长（取 0.5s、夹 schema 范围）、改角色动作；锁死字段没有任何操作能碰
let d = applyOp(DOC, { kind: 'setDuration', shotId: 'E02-SH001', sec: 7.3 })
must(d.episodes[1].shots[0].duration_sec === 7.5, '时长按 0.5s 取整')
must(DOC.episodes[1].shots[0].duration_sec === 5, '不可变更新：原文档不动')
must(applyOp(DOC, { kind: 'setDuration', shotId: 'E02-SH001', sec: 99 })
  .episodes[1].shots[0].duration_sec === 15, '封顶 15s')
must(applyOp(DOC, { kind: 'setDuration', shotId: 'E02-SH001', sec: 0 })
  .episodes[1].shots[0].duration_sec === 0.5, '下限 0.5s')
must(applyOp(DOC, { kind: 'setDuration', shotId: 'nope', sec: 3 }) === DOC, '不存在的镜头原样返回')
d = applyOp(d, { kind: 'setCharacterAction', shotId: 'E01-SH002', ref: 'C01', action: ' 起身 ' })
const ch = d.episodes[0].shots[1].characters!
must(ch[0].action === '起身' && ch[1].action === '咳嗽', '只改指定角色')
d = applyOp(d, { kind: 'setCharacterAction', shotId: 'E01-SH002', ref: 'C01', action: '' })
must(!('action' in d.episodes[0].shots[1].characters![0]), '清空动作即去掉该字段（schema 不收空串）')
must(applyOp(DOC, { kind: 'setCharacterAction', shotId: 'E01-SH001', ref: 'C09', action: 'x' }) === DOC,
     '镜头里没有的角色不新增')
must(JSON.stringify(d.episodes.map((e) => e.shots.map((s) => [s.id, s.source, s.narration, s.dialogue])))
  === JSON.stringify(DOC.episodes.map((e) => e.shots.map((s) => [s.id, s.source, s.narration, s.dialogue]))),
     'ID、溯源、旁白与台词逐字未变')
console.log('7. 操作层 → 改时长（取整/夹范围）/ 改角色动作 / 锁死字段不受影响 ✓')

// 8. 真实产物：《药》全章，总时长与后端计价口径逐秒一致
const real: Storyboard = JSON.parse(
  readFileSync('../backend/tests/real_text_yao/output_merged.json', 'utf8'))
const rt = buildTimeline(real)
must(rt.shots.length === real.episodes.flatMap((e) => e.shots).length, '全部镜头上轴')
must(rt.characters.length > 5 && rt.scenes.length > 3, '泳道与场景条都铺开了')
const py = '../backend/.venv/bin/python'
if (existsSync(py)) {
  const out = execFileSync(py, ['-c', [
    'import json,sys; sys.path.insert(0, "../backend")',
    'from pipeline.quality import playable_seconds',
    'd = json.load(open("../backend/tests/real_text_yao/output_merged.json"))',
    'print(playable_seconds(d)[1])'].join('\n')], { encoding: 'utf8' })
  // 后端报表保留一位小数
  must(Math.abs(Number(out) - rt.total) < 0.05,
       `画布总时长 ${rt.total} 应与后端可播时长 ${out.trim()} 一致`)
  console.log(`8. 真实产物 → ${rt.shots.length} 镜 / ${rt.characters.length} 条角色泳道 / 总时长与后端计价一致（${fmtClock(rt.total)}）✓`)
} else {
  console.log('8. 真实产物 → 布局完整 ✓（未找到 ../backend/.venv，跳过与后端口径的比对）')
}

console.log('\nALL PASS')
