/** 出片的纯计算：段在时间轴上的位置、横条文字与样式、主按钮、确认清单、轮询间隔、前置检查。
 *  画布交互由 film.test.tsx 覆盖。跑法：npm test */
import { readFileSync } from 'node:fs'
import { buildTimeline } from '../src/timeline'
import {
  anyInFlight, batchSummary, cancelKind, chosenAttempt, clipOffset, clipSpans, copyIndex, firstFrameText, fmtWait,
  laneKind, laneText, laneTitle, mainAction, needsConfirm, playableAttempt, pollDelay, POLL_FAST_MS, POLL_SLOW_MS,
  precheck, slotsNeeded, spanAt, tailSources, waitedSec, waitLine, clockOffset,
} from '../src/film'
import { setCurrentLocale } from '../src/i18n/core'
import { en } from '../src/i18n/en'
import { zh } from '../src/i18n/zh'
import type { FilmAttempt, FilmClip, FilmFreeNode, FilmSession, Storyboard } from '../src/types'

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }
const doc: Storyboard = JSON.parse(
  readFileSync('../backend/tests/real_text_yao/output_merged.json', 'utf8'))
const tl = buildTimeline(doc)
const [a, b, c3] = tl.shots

const clip = (id: string, shots: string[], over: Partial<FilmClip> = {}): FilmClip => ({
  id, episode: 'E01', shots, duration: 8, truncated: false, prompt: 'p', refs: [], dropped_refs: [],
  missing_refs: [], first_frame: null, frame_mode: null, fingerprint: 'fp', estimate_cny: 8,
  attempts: [], chosen: null, mute_native: false, uncertain: false, error: null, state: 'planned', ...over,
})
const ok: FilmAttempt = {
  task_id: 't1', state: 'succeeded', cost_cny: 7.5, file: 'clips/x.t1.mp4', last_frame: 'clips/x.t1.last.jpg',
  error: null, at: '2026-10-31T03:00:00+00:00', fingerprint: 'fp', first_frame_used: null,
}
const session = (clips: FilmClip[], over: Partial<FilmSession> = {}): FilmSession => ({
  tier: 'demo', resolution: '720p', audio_mode: 'tts_all', budget_cny: 200,
  confirm_over_cny: 20, spent_cny: 0, clips, orphaned: [], counts: {}, reserved_cny: 0, uncertain_count: 0,
  remaining_cny: clips.filter((x) => (x.state === 'planned' || x.state === 'failed') && !x.uncertain)
    .reduce((n, x) => n + x.estimate_cny, 0),
  options: { tiers: [], resolutions: ['720p'], cny_per_sec: {}, max_clip_sec: 10,
             max_refs: 3, audio_modes: ['tts_all'], rate_note: '' },
  ...over,
})

// 1. 位置：段横跨所含镜头；镜头不在分镜里的段不画；按开始时间排序
{
  const s = session([clip('E01-C02', [c3.id]), clip('E01-C01', [a.id, b.id]), clip('E09-C01', ['NOPE'])])
  const spans = clipSpans(tl, s)
  must(spans.length === 2, '找不到镜头的段不画')
  must(spans[0].clip.id === 'E01-C01' && spans[0].start === a.start && spans[0].end === b.end, '第一段横跨前两镜')
  must(spans[1].start === c3.start && spans[1].end === c3.end, '第二段就是第三镜')
  must(spanAt(spans, (a.start + b.end) / 2)?.clip.id === 'E01-C01', '播放头在段内')
  must(spanAt(spans, tl.total + 1) === undefined, '片尾之后没有段')
  must(clipOffset(spans[1], c3.start + 1.5) === 1.5 && clipOffset(spans[1], 0) === 0, '段内偏移')
  console.log('1. 段的位置 ✓')
}

// 2. 横条：五种样式与文字；悬停说明；只有成功的那次算采用
{
  const now = Date.parse('2026-10-31T03:01:05+00:00')
  must(laneKind(clip('x', [])) === 'planned' && laneText(clip('E01-C01', []), now) === 'C01 · 8s · 约 ¥8.00', '未出片')
  const busy = clip('x', [], { state: 'running', queued_at: '2026-10-31T03:00:00+00:00' })
  must(laneKind(busy) === 'busy' && laneText(busy, now) === '生成中 · 已等 1:05', '生成中显示已等时间')
  must(laneKind(clip('x', [], { state: 'downloading' })) === 'busy', '下载中也算生成中')
  const done = clip('E01-C03', [], { state: 'done', attempts: [{ ...ok, state: 'failed', file: null }, ok], chosen: 1 })
  must(laneKind(done) === 'done' && laneText(done, now) === 'C03 · 第 2 次 · ¥7.50', '已完成写第几次与费用')
  must(laneText(clip('x', [], { state: 'failed', error: '内容审核未通过' }), now) === '内容审核未通过', '失败写原因')
  must(laneText(clip('x', [], { state: 'stale', attempts: [ok], chosen: 0 }), now) === '内容改过 · 仍可播放旧版', '内容改过')
  const t = laneTitle(clip('E01-C04', ['S1'], { dropped_refs: ['P01'], truncated: true }))
  must(t.includes('⚠') && t.includes('P01') && t.includes('✂'), '悬停列出被裁参考图与截断')
  must(chosenAttempt(done) === ok, '采用的那次')
  must(chosenAttempt(clip('x', [], { attempts: [{ ...ok, state: 'failed' }], chosen: 0 })) === null, '失败的那次不算采用')
  console.log('2. 横条样式与文字 ✓')
}

// 3. 主按钮：先试一段 → 出剩余；待核对的段不在批量里
{
  const fresh = session([clip('C1', []), clip('C2', []), clip('C3', [])])
  const m1 = mainAction(fresh, null)
  must(m1.kind === 'try' && m1.clip.id === 'C1', '一段都没出过：先试第一段')
  const m2 = mainAction(fresh, 'C2')
  must(m2.kind === 'try' && m2.clip.id === 'C2', '选中的段能出就试它')
  const tried = session([clip('C1', [], { state: 'done', attempts: [ok], chosen: 0 }), clip('C2', []),
                         clip('C3', [], { state: 'failed', uncertain: true })])
  const m3 = mainAction(tried, null)
  must(m3.kind === 'rest' && m3.count === 1 && m3.cny === 8, '出过之后：出剩余各段，跳过待核对')
  must(mainAction(session([clip('C1', [], { state: 'done', attempts: [ok], chosen: 0 })]), null).kind === 'none',
       '没有要出的段')
  const queued = session([clip('C1', [], { state: 'queued' }), clip('C2', [])])
  must(mainAction(queued, null).kind === 'none', '试段已排队、还没有尝试：不再提供第二次试段')
  const failedOnly = session([clip('C1', [], { state: 'failed', attempts: [{ ...ok, state: 'failed', file: null }] }),
                              clip('C2', [])])
  must(mainAction(failedOnly, null).kind === 'try', '试段只失败过：仍是先试一段')
  console.log('3. 主按钮 ✓')
}

// 4. 确认：批量清单与上限；单段超过确认线
{
  const s = session([clip('C1', [], { estimate_cny: 30 }), clip('C2', [], { estimate_cny: 25 })],
                    { spent_cny: 150, budget_cny: 200 })
  const sum = batchSummary(s)
  must(sum.rows.length === 2 && sum.total === 55 && sum.after === 205 && sum.over, '批量清单、累计与超限')
  must(needsConfirm(s.clips[0], s) && !needsConfirm(clip('C3', [], { estimate_cny: 20 }), s), '超过确认线才确认')
  console.log('4. 确认清单 ✓')
}

// 5. 轮询、前置检查、首帧说明
{
  const busy = session([clip('C1', [], { state: 'queued' })])
  must(pollDelay(busy, true) === POLL_FAST_MS && pollDelay(busy, false) === POLL_SLOW_MS, '页签开着且在跑才快轮询')
  must(pollDelay(session([clip('C1', [])]), true) === POLL_SLOW_MS && pollDelay(null, true) === POLL_SLOW_MS,
       '没在跑就慢轮询')
  const p = precheck(session([clip('C1', [], { missing_refs: ['S02', 'C01'] }),
                              clip('C2', [], { missing_refs: ['C01'], dropped_refs: ['P1'], truncated: true })]))
  must(p.missing.join() === 'C01,S02' && p.trimmed.join() === 'C2' && p.truncated.join() === 'C2', '前置检查去重')
  must(firstFrameText(clip('x', [], { first_frame: 'keyframe:E01-SH002', frame_mode: 'ref' }))
       === '关键帧 E01-SH002（占第一个参考位）', '关键帧首帧')
  must(firstFrameText(clip('x', [], { first_frame: 'relay:E01-C01', frame_mode: 'frame' }))
       === '接力上一段（E01-C01）的尾帧', '尾帧接力')
  must(firstFrameText(clip('x', [])) === '不带首帧', '无首帧')
  console.log('5. 轮询、前置检查、首帧 ✓')
}

// 6. 自由节点：在跑也快轮询；复制件不算「试段已出」；尾帧来源；参考位；首帧说明；复制件下标
{
  const n = (over: Partial<FilmFreeNode> = {}): FilmFreeNode => ({
    id: 'F01', target: null, target_shots: null, target_lost: false, prompt: 'p', refs: [], first_frame: null,
    duration: 5, estimate_cny: 5, state: 'planned', error: null, uncertain: false, attempts: [], chosen: null,
    created_at: '', over_refs: false, ...over,
  })
  const s = session([clip('C1', [])], { free: [n({ state: 'running' })] })
  must(anyInFlight(s) && pollDelay(s, true) === POLL_FAST_MS, '自由节点在跑也快轮询')
  must(!anyInFlight(session([clip('C1', [])], { free: [n()] })), '没在跑')
  const copied = session([clip('C1', [], { attempts: [{ ...ok, free_id: 'F01', cost_cny: 0 }] }), clip('C2', [])])
  must(mainAction(copied, null).kind === 'try', '复制件不算试段已出')
  const src = session([clip('C1', [], { attempts: [ok], chosen: 0, state: 'done' }), clip('C2', [])],
                      { free: [n({ id: 'F02', attempts: [ok], chosen: 0, state: 'done' }), n({ id: 'F03' })] })
  must(tailSources(src).join() === 'C1,F02', '有尾帧的才能作首帧来源')
  must(slotsNeeded(['a', 'b'], 'keyframe:x', src) === 3 && slotsNeeded([], 'keyframe:x', src) === 0
       && slotsNeeded(['a'], null, src) === 1, '首帧与参考图不能同用时首帧占一位')
  must(slotsNeeded(['a'], 'k', session([], { options: { ...src.options, frame_with_refs: true } })) === 1,
       '能同用时首帧不占位')
  must(firstFrameText({ first_frame: 'tail:F02', frame_mode: null }) === 'F02 的尾帧', '尾帧首帧说明')
  must(chosenAttempt(n({ attempts: [ok], chosen: 0 }))?.task_id === 't1', '自由节点也能取采用的那次')
  const att = session([clip('C1', [], { attempts: [ok, { ...ok, task_id: 't9', free_id: 'F01' }] })])
  must(copyIndex(att, n({ target: 'C1' }), { ...ok, task_id: 't9' }) === 1, '找到复制进段里的那次')
  must(copyIndex(att, n({ target: 'C1' }), ok) === -1 && copyIndex(att, n(), ok) === -1, '找不到为 -1')
  console.log('6. 自由节点 ✓')
}

// 7. 等待与取消：已等时长、通常区间（分钟：下限向下、上限向上取整）、超过上限换说法；能不能取消；播哪一次
{
  must(fmtWait(245.9) === '4 分 05 秒' && fmtWait(0) === '0 分 00 秒' && fmtWait(-3) === '0 分 00 秒', '已等时长')
  must(waitLine(245, [180, 420]) === '已等 4 分 05 秒 · 通常 3–7 分钟', `等待一行：${waitLine(245, [180, 420])}`)
  must(waitLine(30, [100, 130]) === '已等 0 分 30 秒 · 通常 1–3 分钟', '下限向下、上限向上取整到分钟')
  must(waitLine(421, [180, 420]) === '已等 7 分 01 秒 · 比通常久，仍在处理', '超过上限换说法')
  must(waitLine(10, null) === '已等 0 分 10 秒' && waitLine(10) === '已等 0 分 10 秒', '没有通常区间只说已等')
  must(waitedSec({ queued_at: new Date(1000).toISOString() }, 6000) === 5 && waitedSec({}, 6000) === null, '从排队那一刻算；缺字段为 null')
  setCurrentLocale('en')
  must(waitLine(245, [180, 420]) === 'Waited 4m 05s · usually 3–7 min', `英文等待一行：${waitLine(245, [180, 420])}`)
  must(waitLine(421, [180, 420]) === 'Waited 7m 01s · longer than usual, still working', '英文超过上限')
  setCurrentLocale('zh')

  const sub = { ...ok, state: 'submitting' as const, task_id: null, file: null }
  const run = { ...ok, state: 'running' as const, file: null }
  // 非法时间与区间：只显示安全降级文案，不出现 NaN / Infinity
  const nanLines = [waitLine(waitedSec({ queued_at: 'not-a-date' }, 6000), [180, 420]), waitLine(waitedSec({}, 6000), [180, 420]),
               waitLine(NaN, [180, 420]), waitLine(10, [NaN, 420]), waitLine(10, [180, Infinity]),
               waitLine(10, [180] as unknown as number[]), waitLine(10, ['a', 'b'] as unknown as number[]),
               waitLine(10, [420, 180]), fmtWait(NaN), fmtWait(Infinity)]
  must(nanLines.every((x) => !/NaN|Infinity|undefined/.test(x)), `不显示 NaN：${nanLines.join(' | ')}`)
  must(waitedSec({ queued_at: 'not-a-date' }, 6000) === null && waitedSec({ queued_at: new Date(1000).toISOString() }, NaN) === null,
       '非法时间得 null')
  must(waitLine(10, [NaN, 420]) === '已等 0 分 10 秒' && waitLine(null, [180, 420]) === '生成中', `降级：${waitLine(10, [NaN, 420])}`)
  // 时钟偏差：偏差 = 服务端时间 − 本地时间；本地时间加偏差再减排队时刻
  const q = Date.parse('2026-11-21T10:00:00Z')
  const srvNow = '2026-11-21T10:01:05Z'
  for (const skew of [10 * 60000, -10 * 60000]) {
    const local = Date.parse(srvNow) + skew
    must(waitedSec({ queued_at: '2026-11-21T10:00:00Z' }, local + clockOffset(srvNow, local)) === 65, `客户端偏 ${skew}ms 仍得 65 秒`)
  }
  must(clockOffset(undefined, 5) === 0 && clockOffset('坏', 5) === 0 && q > 0, '没有或非法的服务端时间：不校准')
  must(cancelKind(clip('C1', [], { state: 'queued' })) === 'free', '还没提交：取消不花钱')
  must(cancelKind(clip('C1', [], { state: 'queued', attempts: [sub] })) === null, '正在提交：先不给取消')
  must(cancelKind(clip('C1', [], { state: 'running', attempts: [run] })) === 'paid', '已提交：可能仍扣费')
  must(cancelKind(clip('C1', [], { state: 'downloading', attempts: [run] })) === null
       && cancelKind(clip('C1', [], { state: 'done', attempts: [ok], chosen: 0 })) === null
       && cancelKind(clip('C1', [])) === null, '在取回、已结束、没出过：不能取消')

  const late = { ...ok, task_id: 't2', file: 'clips/x.t2.mp4', late: true }
  const bad = { ...ok, task_id: 't3', state: 'failed' as const, file: null }
  must(playableAttempt(clip('C1', [], { attempts: [ok, late], chosen: 0 }))?.index === 0, '默认播采用的那次')
  must(playableAttempt(clip('C1', [], { attempts: [ok, late], chosen: 0 }), 1)?.index === 1, '点名播哪次就播哪次')
  must(playableAttempt(clip('C1', [], { attempts: [bad, late], chosen: null }))?.index === 1, '没有采用：播最近成功的一次')
  must(playableAttempt(clip('C1', [], { attempts: [bad] })) === null
       && playableAttempt(clip('C1', [], { attempts: [ok], chosen: 0 }), 5) === null, '没有可播的')

  // 等待、取消、播放、任务列表、通知的文案：两种语言都不出现厂商或模型的名字
  const vendor = /minimax|seedance|hailuo|ark\b|方舟|海螺|豆包|火山/i
  const flat = (node: unknown): string[] =>
    (typeof node === 'string' ? [node] : Object.values(node as Record<string, unknown>).flatMap(flat))
  for (const pack of [zh, en]) {
    const texts = [pack.film.wait, pack.film.waitOver, pack.film.waitOnly, pack.film.waitMin, pack.film.lateTag,
                   pack.film.lateHint,
                   ...flat(pack.film.cancel), ...flat(pack.film.play), ...flat(pack.activity), ...flat(pack.app.notify),
                   ...flat(pack.enums.attemptState)]
    must(texts.length > 30 && texts.every((x) => !vendor.test(x)), `文案里不出现厂商名：${texts.find((x) => vendor.test(x))}`)
  }
  console.log('7. 等待、取消与播放 ✓')
}

console.log('\nALL PASS')
