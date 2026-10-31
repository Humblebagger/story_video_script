/** 章节工作流的纯计算：该做哪一步、各步状态、各步主按钮（动作、金额、拦截原因与修复目标）。跑法：npm test */
import { currentStep, primaryFor, stepStates, STEPS } from '../src/workflow'
import type { FlowInput } from '../src/workflow'
import type { ComposePreview, FilmClip, FilmSession, VersionSummary } from '../src/types'

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }

const ver = (status: VersionSummary['status'] = 'succeeded', extra: Partial<VersionSummary> = {}): VersionSummary => ({
  id: 'v1', created_at: null, edited_at: null, status, units: 10, episodes: 1, shots: 12,
  has_quality_report: false, ...extra,
})
const clip = (id: string, state: FilmClip['state'], extra: Partial<FilmClip> = {}) => ({
  id, state, shots: [`E01-${id}`], duration: 5, estimate_cny: 2.5, attempts: [], chosen: null,
  missing_refs: [], dropped_refs: [], truncated: false, uncertain: false, queued_at: null, error: null,
  first_frame: null, frame_mode: 'first', mute_native: false, ...extra,
}) as unknown as FilmClip
const film = (clips: FilmClip[], extra: Partial<FilmSession> = {}) => ({
  clips, budget_cny: 100, spent_cny: 0, reserved_cny: 0, remaining_cny: clips.length * 2.5, confirm_over_cny: 20,
  final: null, gate: { ok: true, message: null }, ...extra,
}) as unknown as FilmSession
const base: FlowInput = {
  hasText: true, textDirty: false, converting: false, version: ver(), dirty: false,
  verificationFailed: false, film: null, finalStale: false, compose: null,
}
const at = (p: Partial<FlowInput>) => currentStep({ ...base, ...p })

// 1. 按顺序取第一个没完成的步骤
must(STEPS.join() === 'import,storyboard,review,render,compose,download', '六步顺序')
must(at({ hasText: false, version: null }) === 'import', '没有原文 → ①')
must(at({ version: null }) === 'storyboard', '没有版本 → ②')
must(at({ version: ver('failed') }) === 'storyboard', '只有失败的版本 → ②')
must(at({ converting: true }) === 'storyboard', '生成中也停在 ②')
must(at({ dirty: true }) === 'review', '有未保存修改 → ③')
must(at({ verificationFailed: true }) === 'review', '完整性检查没过 → ③')
must(at({ version: ver('succeeded', { verification_status: 'failed' }) }) === 'review', '版本摘要里复验失败 → ③')
must(at({ film: null }) === 'render', '没有出片会话 → ④')
must(at({ film: film([clip('c1', 'done'), clip('c2', 'planned')]) }) === 'render', '还有段没出 → ④')
const done2 = film([clip('c1', 'done'), clip('c2', 'done')])
must(at({ film: done2 }) === 'compose', '都出好了、没有成片 → ⑤')
const finalDone = { state: 'done', files: ['final/E01.mp4'], report: null, error: null, detail: null }
must(at({ film: { ...done2, final: finalDone } as FilmSession, finalStale: true }) === 'compose', '成片过期 → ⑤')
must(at({ film: { ...done2, final: { ...finalDone, state: 'running' } } as FilmSession }) === 'compose', '合成中 → ⑤')
must(at({ film: { ...done2, final: finalDone } as FilmSession }) === 'download', '都完成 → ⑥')
console.log('1. currentStep ✓')

// 2. 各步状态：之前的打勾，当前高亮，之后的灰掉并说明先完成第几步
const st = stepStates({ ...base, film: null })
must(st.map((s) => s.state).join() === 'done,done,done,current,locked,locked', '状态序列')
must(st[5].needs === 4, '灰掉的步骤记着要先完成第几步（1 起）')
console.log('2. stepStates ✓')

// 3. 主按钮：动作、金额、拦截原因与修复目标
const p1 = primaryFor('import', { ...base, version: null, hasText: false })
must(p1.blocked?.reason === 'flow.block.noText' && p1.blocked.fix.target === 'chapter-source', '没原文：拦截并定位到原文框')
const p1b = primaryFor('import', { ...base, textDirty: true })
must(p1b.action === 'saveText' && !p1b.blocked, '原文改过：主按钮是保存原文')
must(primaryFor('import', base).action === 'goto' && primaryFor('import', base).goto === 'storyboard', '原文好了：去下一步')
const p2 = primaryFor('storyboard', { ...base, version: null, textDirty: true })
must(p2.blocked?.reason === 'flow.block.textDirty' && p2.blocked.fix.step === 'import', '原文没保存：拦截，修复去 ①')
must(primaryFor('storyboard', { ...base, version: null }).action === 'generate', '主按钮生成分镜')
must(primaryFor('storyboard', base).label === 'flow.primary.regenerate', '已有版本：重新生成')
must(primaryFor('storyboard', { ...base, converting: true }).blocked?.reason === 'flow.block.converting', '生成中不能再点')
must(primaryFor('review', { ...base, dirty: true }).action === 'save', '有修改：主按钮保存')
const p3 = primaryFor('review', { ...base, verificationFailed: true })
must(p3.blocked?.reason === 'flow.block.verify' && p3.blocked.fix.target === 'verification', '检查没过：定位到检查结果')
const p4 = primaryFor('render', { ...base, film: film([clip('c1', 'planned'), clip('c2', 'planned')]) })
must(p4.action === 'openFilm' && p4.label === 'flow.primary.tryOne' && p4.cny === 2.5, '没出过：先试一段（约 ¥2.50）')
const p4b = primaryFor('render', { ...base, film: film([clip('c1', 'done'), clip('c2', 'planned')], { remaining_cny: 2.5 }) })
must(p4b.label === 'flow.primary.renderRest' && p4b.count === 1 && p4b.cny === 2.5, '出过一段：出剩余 1 段')
must(primaryFor('render', base).label === 'flow.primary.startFilm', '没有会话：去出片（先切段，不花钱）')
const p4c = primaryFor('render', { ...base, dirty: true })
must(p4c.blocked?.reason === 'flow.block.dirty' && p4c.blocked.fix.target === 'storyboard-save', '没保存：定位到保存按钮')
const preview = { tts_cny: 0.18 } as ComposePreview
const p5 = primaryFor('compose', { ...base, film: done2, compose: preview })
must(p5.action === 'openFilm' && p5.label === 'flow.primary.compose' && p5.cny === 0.18, '去配音合成（约 ¥0.18）')
must(primaryFor('compose', { ...base, film: null }).blocked?.fix.step === 'render', '还没出片：修复去 ④')
must(primaryFor('download', base).action === 'none', '⑥没有主按钮动作（下载在工作区里）')
console.log('3. primaryFor ✓')

console.log('\nALL PASS')
