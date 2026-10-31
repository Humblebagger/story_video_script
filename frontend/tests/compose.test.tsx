/** 配音与合成的纯计算：能不能合成及原因、状态文字、成片按集分组、对齐说明、选曲参考、BGM 类型、按钮文字。
 *  界面回归在 Task 4 补上。跑法：npm test */
import {
  bgmType, composeBlockers, composeKey, composeLabel, composing, curveText, finalEpisodes, finalText, noteText,
} from '../src/compose'
import type { ComposePreview, FilmSession, FinalState, VoicesInfo } from '../src/types'

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }

const P: ComposePreview = {
  lines: 3, tts_chars: 30, tts_cny: 0.01, missing_voices: ['C09'], voices: { narration: 'fake-male' },
  no_video: ['E01-C02'], fingerprint: 'fp', final: null, bgm: [], tools: true, music: {}, report: null,
}
const S = {
  audio_mode: 'tts_all', resolution: '720p', budget_cny: 200, spent_cny: 10, voices: {}, final: null,
  clips: [{ id: 'E01-C01', state: 'done', chosen: 0, mute_native: false },
          { id: 'E01-C02', state: 'planned', chosen: null, mute_native: false }],
} as unknown as FilmSession
const V: VoicesInfo = {
  provider: 'fake', rate_note: '假配音', voices: [{ id: 'fake-male', name: '假男声', gender: 'male' }],
  speakers: [{ key: 'C09', name: '路人', hint: null, voice: null, chosen: null }], missing: ['C09'],
}
const base = { dirty: false, gate: null, draft: true }

must(composeBlockers(P, S, V, base).join('|') === '还有 1 个说话人没选音色：路人', '缺音色写说话人名字')
must(composeBlockers({ ...P, missing_voices: [] }, S, V, base).length === 0, '草稿合成时缺段不拦')
must(composeBlockers({ ...P, missing_voices: [] }, S, V, { ...base, draft: false })[0]
  .startsWith('1 段还没有可用的视频'), '关掉草稿合成时缺段要拦')
const all = composeBlockers({ ...P, tools: false, tts_cny: 500, missing_voices: [] },
  { ...S, clips: [{ ...S.clips[0], state: 'running' }] } as FilmSession, V,
  { dirty: true, gate: '分镜未通过独立验证', draft: true })
must(all.length === 5 && all[0].includes('先保存再合成') && all[1].includes('分镜未通过独立验证')
  && all[2].includes('apt install ffmpeg') && all[3].includes('排队或生成中') && all[4].includes('超过上限'),
  `各种拦截按顺序列出：${all.join(' / ')}`)
const busy: FinalState = { state: 'running', step: '混音 E01', files: [], report: null, error: null, detail: null }
must(composing({ ...P, final: busy }) && !composing(P), '合成中')
must(composeBlockers({ ...P, missing_voices: [], final: busy }, S, V, base)[0] === '正在合成，等它结束再合成',
  '合成中不能再合成')
console.log('1. 能不能合成及原因 ✓')

must(finalText(busy) === '合成中 · 混音 E01', '合成中写步骤')
must(finalText({ ...busy, state: 'failed', error: '混音 E01 失败' }) === '合成失败：混音 E01 失败', '失败写原因')
must(finalText({ ...busy, state: 'done', stale: false }) === '成片是最新的', '最新')
must(finalText({ ...busy, state: 'done', stale: true }).startsWith('成片已过期'), '过期')
const eps = finalEpisodes(['final/E01.mp4', 'final/E01.srt', 'final/E02.mp4', 'final/mix_report.json'])
must(JSON.stringify(eps) === JSON.stringify([
  { episode: 'E01', video: 'final/E01.mp4', srt: 'final/E01.srt' }, { episode: 'E02', video: 'final/E02.mp4' }]),
  '成片按集分组')
console.log('2. 成片状态与分组 ✓')

must(noteText({ shot: 'S2', kind: 'speedup', speed: 1.1 }) === 'S2：语速提到 1.1×', '提速说明')
must(noteText({ shot: 'S3', kind: 'freeze', speed: 1.15, extend: 0.61 })
  === 'S3：按 1.15× 念仍超出镜头，段尾定格延长 0.61 秒', '定格说明')
must(curveText({ from_shot: 'E01-SH001', to_shot: 'E01-SH010', mood: 'calm', intensity: 'low', note: '秋夜' })
  === 'E01-SH001–E01-SH010 · 平静 · 弱 · 秋夜', '选曲参考')
must(curveText({ mood: 'tense' }) === '紧张', '选曲参考缺项')
console.log('3. 对齐说明与选曲参考 ✓')

must(bgmType({ name: 'a.mp3', type: 'audio/mpeg' }) === 'audio/mpeg', '浏览器给的类型')
must(bgmType({ name: 'b.M4A', type: '' }) === 'audio/mp4', '没有类型按扩展名')
must(bgmType({ name: 'c.wav', type: 'audio/x-wav' }) === 'audio/x-wav', 'x-wav 也认')
must(bgmType({ name: 'd.txt', type: 'text/plain' }) === null, '不是音频')
must(composeLabel(P) === '合成整章（配音约 ¥0.01）' && composeLabel({ ...P, tts_cny: 0 }) === '合成整章（不花钱）',
  '按钮写金额')
const k1 = composeKey(S)
must(composeKey({ ...S, voices: { C09: 'fake-male' } } as FilmSession) !== k1
  && composeKey({ ...S, clips: [S.clips[0], { ...S.clips[1], state: 'done' }] } as FilmSession) !== k1
  && composeKey({ ...S, spent_cny: 99 } as FilmSession) === k1, '音色、段状态变了才重读；已花变了不重读')
console.log('4. BGM 类型、按钮文字、重读时机 ✓')

console.log('\nALL PASS')
