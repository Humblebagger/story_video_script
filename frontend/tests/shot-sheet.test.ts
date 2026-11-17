/** 拉片表与片段卡镜头标签的纯计算：分组与提示词格合并、运镜文字、镜头小标签、折叠。
 *  界面由 sheet-view.test.tsx 与 graph-view.test.tsx 覆盖。跑法：npm test */
import { setCurrentLocale } from '../src/i18n/core'
import {
  cameraText, clipShotTags, foldTags, needsFold, sheetGroups, shortShotId, shotTag, shotsById,
} from '../src/shotSheet'
import type { FilmClip, FilmSession, Shot, Storyboard } from '../src/types'

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }
const eq = (a: unknown, b: unknown, msg: string) =>
  must(JSON.stringify(a) === JSON.stringify(b), `${msg}\n  得到 ${JSON.stringify(a)}\n  期望 ${JSON.stringify(b)}`)

const shot = (id: string, over: Partial<Shot> = {}): Shot => ({
  id, duration_sec: 3, shot_size: 'medium', action: `${id} 的画面`,
  source: { unit_refs: [], derivation: 'explicit' }, ...over,
})
const s1 = shot('E01-SH001', { shot_size: 'extreme_wide', camera: { movement: 'static', angle: 'high' } })
const s2 = shot('E01-SH002', { shot_size: 'close_up', camera: { movement: 'push_in', angle: 'low' } })
const s3 = shot('E01-SH003')
const s4 = shot('E01-SH004', { shot_size: 'wide', camera: { movement: 'pan' } })
const doc = {
  episodes: [
    { id: 'E01', title: '第一集', shots: [s1, s2, s3, s4] },
    { id: 'E02', shots: [shot('E02-SH001'), shot('E02-SH002')] },
  ],
} as unknown as Storyboard

const clip = (id: string, shots: string[], over: Partial<FilmClip> = {}): FilmClip => ({
  id, episode: 'E01', shots, duration: 8, truncated: false, prompt: `${id} 的提示词`, refs: [], dropped_refs: [],
  missing_refs: [], first_frame: null, frame_mode: null, fingerprint: 'fp', estimate_cny: 8,
  attempts: [], chosen: null, mute_native: false, uncertain: false, error: null, state: 'planned', ...over,
})
const session = (clips: FilmClip[]): FilmSession => ({
  provider: 'fake', model: 'fake-1', resolution: '720p', audio_mode: 'tts_all', budget_cny: 200,
  confirm_over_cny: 20, spent_cny: 0, clips, orphaned: [], counts: {}, reserved_cny: 0, uncertain_count: 0,
  remaining_cny: 0,
  options: { providers: ['fake'], models: {}, resolutions: ['720p'], cny_per_sec: {}, max_clip_sec: 10,
             max_refs: 3, audio_modes: ['tts_all'], rate_note: '' },
} as unknown as FilmSession)

const spans = (doc_: Storyboard, film: FilmSession | null) =>
  sheetGroups(doc_, film).map((g) => g.rows.map((r) => r.span))
const clips = (doc_: Storyboard, film: FilmSession | null) =>
  sheetGroups(doc_, film).map((g) => g.rows.map((r) => r.clip?.id ?? null))

// 1. 没有出片会话：每集一组、每镜一行，整集并成一格「未规划」
{
  const g = sheetGroups(doc, null)
  eq(g.map((x) => x.ep.id), ['E01', 'E02'], '每集一组')
  eq(g.map((x) => x.rows.map((r) => r.shot.id)),
     [['E01-SH001', 'E01-SH002', 'E01-SH003', 'E01-SH004'], ['E02-SH001', 'E02-SH002']], '每镜一行，顺序不变')
  eq(spans(doc, null), [[4, 0, 0, 0], [2, 0]], '没有会话时每集一格')
  eq(clips(doc, null), [[null, null, null, null], [null, null]], '没有会话时都没有段')
  eq(spans(doc, undefined as unknown as null), [[4, 0, 0, 0], [2, 0]], 'undefined 等同没有会话')
  console.log('1. 没有出片会话 ✓')
}

// 2. 有会话：同段相邻的镜头合并；未规划的相邻镜头也合并；合并不跨集
{
  const film = session([clip('E01-C01', ['E01-SH001', 'E01-SH002']), clip('E01-C02', ['E01-SH003'])])
  eq(spans(doc, film), [[2, 0, 1, 1], [2, 0]], '同段相邻合并')
  eq(clips(doc, film), [['E01-C01', 'E01-C01', 'E01-C02', null], [null, null]], '每镜所在的段')
  const tail = session([clip('E01-C01', ['E01-SH004', 'E02-SH001'])])
  eq(spans(doc, tail), [[3, 0, 0, 1], [1, 1]], '同一段跨集时两集各成一格')
  console.log('2. 合并提示词格 ✓')
}

// 3. 同一段的镜头不相邻：各自成格
{
  const film = session([clip('E01-C01', ['E01-SH001', 'E01-SH003']), clip('E01-C02', ['E01-SH002'])])
  eq(spans(doc, film), [[1, 1, 1, 1], [2, 0]], '不相邻不合并')
  eq(clips(doc, film)[0], ['E01-C01', 'E01-C02', 'E01-C01', null], '段照旧对上')
  console.log('3. 不相邻不合并 ✓')
}

// 4. 一镜出现在两段里取第一段；没有集的分镜是空表
{
  const film = session([clip('E01-C01', ['E01-SH001']), clip('E01-C02', ['E01-SH001', 'E01-SH002'])])
  eq(clips(doc, film)[0], ['E01-C01', 'E01-C02', null, null], '取第一段')
  eq(sheetGroups({} as unknown as Storyboard, film), [], '没有集')
  console.log('4. 重复与空 ✓')
}

// 5. 运镜文字与镜头小标签（中文）
{
  eq(shortShotId('E01-SH003'), 'SH003', '短镜号')
  eq(shortShotId('s1'), 's1', '没有 - 原样')
  eq(cameraText(s1), '固定 / 俯拍', '运镜 / 角度')
  eq(cameraText(s4), '摇', '只有运镜')
  eq(cameraText(shot('x', { camera: { angle: 'pov' } })), '主观视角', '只有角度')
  eq(cameraText(s3), '', '没有 camera 为空串')
  eq(shotTag(s2), 'SH002 特写·推', '景别·运镜')
  eq(shotTag(s3), 'SH003 中景', '没有运镜只写景别')
  eq(shotTag(shot('E01-SH009', { shot_size: 'weird' as never })), 'SH009 weird', '不认识的枚举原样显示')
  const byId = shotsById(doc)
  eq(byId.size, 6, '镜头索引')
  eq(shotsById({} as unknown as Storyboard).size, 0, '没有集时索引为空')
  eq(clipShotTags(['E01-SH001', 'E01-SH099', 'E01-SH004'], byId), ['SH001 大远景·固定', 'SH099', 'SH004 远景·摇'],
     '找不到的镜头只写短镜号')
  eq(clipShotTags([], byId), [], '空段')
  console.log('5. 运镜文字与小标签 ✓')
}

// 6. 折叠
{
  eq(foldTags(['a', 'b', 'c']), { shown: ['a', 'b', 'c'], more: 0 }, '恰好 3 个不折叠')
  eq(foldTags(['a', 'b', 'c', 'd', 'e']), { shown: ['a', 'b', 'c'], more: 2 }, '5 个折叠成 +2')
  eq(foldTags([]), { shown: [], more: 0 }, '空')
  must(!needsFold('字'.repeat(60)) && needsFold('字'.repeat(61)), '超过 60 字要展开按钮')
  must(!needsFold('a\nb\nc') && needsFold('a\nb\nc\nd'), '超过 3 行要展开按钮')
  console.log('6. 折叠 ✓')
}

// 7. 英文
{
  setCurrentLocale('en')
  eq(cameraText(s1), 'Static / High angle', '英文运镜 / 角度')
  eq(shotTag(s2), 'SH002 Close-up·Push in', '英文小标签')
  setCurrentLocale('zh')
  eq(shotTag(s2), 'SH002 特写·推', '切回中文')
  console.log('7. 英文 ✓')
}

console.log('\nALL PASS')
