/** 工作台骨架：章节所在步骤的纯函数 chapterStage 等。跑法：npm test */
import { chapterStage } from '../src/workflow'
import type { ChapterSum, ChapterSummary, VersionSummary } from '../src/types'

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }

const ch = (o: Partial<ChapterSummary> = {}): ChapterSummary => ({
  id: 'c1', title: '第一章', order: 1, adopted_version: null, legacy_numbering: false,
  chars: 100, versions: [], latest_status: null, digest: null, ...o })
const ok = { id: 'v1', status: 'succeeded', created_at: null, edited_at: null, units: 1, episodes: 1, shots: 3,
  has_quality_report: false } as VersionSummary
const sum = (o: Partial<ChapterSum> = {}): ChapterSum => ({
  id: 'c1', version: 'v1', shots: 3, duration_s: 30,
  film: { done: 3, total: 3, failed: 0, running: 0 }, final: 'fresh', cost: null, ...o })

must(chapterStage(ch({ chars: 0 }), undefined, false) === 'import', '没原文')
must(chapterStage(ch(), undefined, false) === 'storyboard', '没版本')
must(chapterStage(ch({ versions: [ok] }), sum(), true) === 'storyboard', '生成中')
must(chapterStage(ch({ versions: [{ ...ok, status: 'draft_invalid' }] }), sum(), false) === 'review', '检查没过')
must(chapterStage(ch({ versions: [ok] }), sum({ film: null }), false) === 'render', '没出片会话')
must(chapterStage(ch({ versions: [ok] }), sum({ film: { done: 1, total: 3, failed: 0, running: 0 } }), false) === 'render', '还有段')
must(chapterStage(ch({ versions: [ok] }), sum({ final: 'stale' }), false) === 'compose', '成片过期')
must(chapterStage(ch({ versions: [ok] }), sum({ final: 'none' }), false) === 'compose', '还没成片')
must(chapterStage(ch({ versions: [ok] }), sum(), false) === 'download', '都完成')
must(chapterStage(ch({ chars: 0, versions: [ok] }), sum(), true) === 'import', '没原文优先于生成中')
must(chapterStage(ch({ adopted_version: 'v1', versions: [{ ...ok, id: 'v2' }, ok] }), sum(), false) === 'download', '采用版')

console.log('workspace: ALL PASS')
