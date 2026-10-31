/** 出片的纯计算：段在时间轴上的位置、横条文字与样式、主按钮、确认清单、轮询间隔、前置检查。
 *  画布交互由 film.test.tsx 覆盖。跑法：npm test */
import { readFileSync } from 'node:fs'
import { buildTimeline } from '../src/timeline'
import {
  batchSummary, chosenAttempt, clipOffset, clipSpans, firstFrameText, laneKind, laneText, laneTitle,
  mainAction, needsConfirm, pollDelay, POLL_FAST_MS, POLL_SLOW_MS, precheck, spanAt,
} from '../src/film'
import type { FilmAttempt, FilmClip, FilmSession, Storyboard } from '../src/types'

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
  provider: 'fake', model: 'fake-1', resolution: '720p', audio_mode: 'tts_all', budget_cny: 200,
  confirm_over_cny: 20, spent_cny: 0, clips, orphaned: [], counts: {}, reserved_cny: 0, uncertain_count: 0,
  remaining_cny: clips.filter((x) => (x.state === 'planned' || x.state === 'failed') && !x.uncertain)
    .reduce((n, x) => n + x.estimate_cny, 0),
  options: { providers: ['fake'], models: {}, resolutions: ['720p'], cny_per_sec: {}, max_clip_sec: 10,
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
  must(laneText(clip('x', [], { state: 'stale', attempts: [ok], chosen: 0 }), now) === '已过期 · 仍可播放旧版', '过期')
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

console.log('\nALL PASS')
