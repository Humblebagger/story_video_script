/** 章节工作台第一批纯逻辑：镜头拍平、检查结果归镜头、找所在出片段、过滤与上下切换、资产缩略图。跑法：npm test */
import { assetThumb } from '../src/lib/assetThumb'
import { clipForShot, filterShots, flatShots, shotIssues, stepShot } from '../src/shotFocus'
import type { FilmSession, Shot, Storyboard, VerificationReport } from '../src/types'

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }

const shot = (id: string, o: Partial<Shot> = {}) =>
  ({ id, duration_sec: 3, shot_size: 'medium', action: `${id} 的画面`, source: { unit_refs: [], derivation: 'explicit' }, ...o }) as Shot
const doc = {
  episodes: [
    { id: 'E01', shots: [shot('SH001'), shot('SH002', { narration: { text: '康大叔推门' } as Shot['narration'] })] },
    { id: 'E02', shots: [shot('SH003')] },
  ],
} as unknown as Storyboard

const rows = flatShots(doc)
must(rows.map((r) => r.shot.id).join() === 'SH001,SH002,SH003', '按集顺序拍平')
must(rows[2].ep === 'E02', '记下所在集')

const report = { status: 'failed', findings: [
  { rule_id: 'a', severity: 'high', object_path: '/episodes/0/shots/1/action', message: '' },
  { rule_id: 'b', severity: 'low', object_path: '/episodes/0/shots/1', message: '' },
  { rule_id: 'c', severity: 'medium', object_path: '/episodes/1/shots/0/dialogue/0', message: '' },
  { rule_id: 'd', severity: 'critical', object_path: '/source/units/3', message: '' },
] } as VerificationReport
const issues = shotIssues(report, doc)
must(issues.get('SH002') === 'hard', '同镜有硬有软按硬')
must(issues.get('SH003') === 'soft', '中低级是软问题')
must(!issues.has('SH001') && issues.size === 2, '指不到镜头的不标')
must(shotIssues(null, doc).size === 0, '没报告时为空')

const film = { clips: [
  { id: 'K1', shots: ['SH001', 'SH002'], chosen: 0, attempts: [{ file: 'clips/K1-0.mp4' }] },
  { id: 'K2', shots: ['SH003'], chosen: null, attempts: [] },
] } as unknown as FilmSession
must(clipForShot(film, 'SH002')?.file === 'clips/K1-0.mp4', '找到片段与采用的文件')
must(clipForShot(film, 'SH003')?.file === null, '没采用时文件为 null')
must(clipForShot(film, 'SH999') === null && clipForShot(null, 'SH001') === null, '找不到为 null')

must(stepShot(rows, 'SH001', 1) === 'SH002' && stepShot(rows, 'SH003', 1) === 'SH003', '下一镜到底不动')
must(stepShot(rows, 'SH001', -1) === 'SH001', '上一镜到顶不动')
must(stepShot(rows, 'SH002', 'end') === 'SH003' && stepShot(rows, 'SH002', 'home') === 'SH001', 'Home / End')
must(stepShot(rows, 'SH003', -1, new Set(['E01'])) === 'SH003', '跳过折叠的集')

must(filterShots(rows, 'sh003').length === 1, '按 ID 不分大小写')
must(filterShots(rows, '推门').map((r) => r.shot.id).join() === 'SH002', '按旁白文字')
must(filterShots(rows, '  ').length === 3, '空查询不过滤')

must(assetThumb({ id: 'C01', name: '华', reference_images: [{ uri: 'refs/a.png' }, { uri: 'https://x/a.png' }] } as never) === 'https://x/a.png', '取第一个可直接显示的')
must(assetThumb({ id: 'C01', name: '华' } as never) === null, '没有图为 null')
console.log('chapter: ALL PASS')
