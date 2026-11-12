/** 路由纯函数：地址 ↔ 位置、非法值规范化（设计 docs/specs/2026-11-12-frontend-routing-design.md §3）。 */
import { chapterPath, novelPath, parseLocation, passState } from '../src/paths'

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }
const eq = (a: unknown, b: unknown, msg: string) =>
  must(JSON.stringify(a) === JSON.stringify(b), `${msg}\n  得到 ${JSON.stringify(a)}\n  期望 ${JSON.stringify(b)}`)

// 1. 顶层
eq(parseLocation('/'), { loc: { kind: 'home' }, fix: null }, '/ 是首页')
eq(parseLocation('/admin'), { loc: { kind: 'admin' }, fix: null }, '/admin 是后台')
eq(parseLocation('/nope').loc, { kind: 'notFound' }, '未知顶层路径是 404')
eq(parseLocation('/admin/x').loc, { kind: 'notFound' }, '/admin 下没有子路径')
console.log('1. 顶层 ✓')

// 2. 小说
eq(parseLocation('/novels/n1'), { loc: { kind: 'novel', nid: 'n1', section: null }, fix: null }, '无分区：section 为 null，等加载完再 replace')
eq(parseLocation('/novels/n1/memory'), { loc: { kind: 'novel', nid: 'n1', section: 'memory' }, fix: null }, '分区')
eq(parseLocation('/novels/n1/chapters'), { loc: { kind: 'novel', nid: 'n1', section: 'chapters' }, fix: null }, '章节分区不是某一章')
eq(parseLocation('/novels/n1/bogus'), { loc: { kind: 'novel', nid: 'n1', section: null }, fix: '/novels/n1' }, '非法分区规范化到上级')
console.log('2. 小说分区 ✓')

// 3. 章节
const ch = (p: string, s = '') => parseLocation(p, s)
eq(ch('/novels/n1/chapters/c1').loc,
   { kind: 'chapter', nid: 'n1', cid: 'c1', step: null, tab: 'focus', canvas: false, view: 'timeline' }, '无步骤段')
eq(ch('/novels/n1/chapters/c1/review', '?tab=cards'),
   { loc: { kind: 'chapter', nid: 'n1', cid: 'c1', step: 'review', tab: 'cards', canvas: false, view: 'timeline' }, fix: null }, '步骤加页签')
eq(ch('/novels/n1/chapters/c1/render/canvas', '?view=graph'),
   { loc: { kind: 'chapter', nid: 'n1', cid: 'c1', step: 'render', tab: 'focus', canvas: true, view: 'graph' }, fix: null }, '画布加节点图')
eq(ch('/novels/n1/chapters/c1/zzz').fix, '/novels/n1/chapters/c1', '非法步骤规范化到章节')
eq(ch('/novels/n1/chapters/c1/import/canvas').fix, '/novels/n1/chapters/c1', '画布只挂在 review/render/compose')
eq(ch('/novels/n1/chapters/c1/import', '?tab=cards').fix, '/novels/n1/chapters/c1/import', '页签只在 review/render/compose 有意义')
eq(ch('/novels/n1/chapters/c1/review', '?tab=zzz').fix, '/novels/n1/chapters/c1/review', '非法页签去掉')
eq(ch('/novels/n1/chapters/c1/review', '?tab=focus').fix, '/novels/n1/chapters/c1/review', 'focus 是缺省值不写进地址')
eq(ch('/novels/n1/chapters/c1/review', '?view=graph').fix, '/novels/n1/chapters/c1/review', '不在画布时 view 去掉')
eq(ch('/novels/n1/chapters/c1/review/canvas', '?view=timeline').fix, '/novels/n1/chapters/c1/review/canvas', 'timeline 是缺省值')
eq(ch('/novels/n1/chapters/c1/review/canvas', '?view=zzz').fix, '/novels/n1/chapters/c1/review/canvas', '非法 view 去掉')
eq(ch('/novels/n1/chapters/c1/review/other').loc, { kind: 'notFound' }, '画布位置只能是 canvas')
eq(ch('/novels/n1/chapters/c1/review/canvas/x').loc, { kind: 'notFound' }, '画布下没有子路径')
console.log('3. 章节、步骤、页签、画布 ✓')

// 4. 拼地址
eq(novelPath('n1'), '/novels/n1', '小说地址')
eq(novelPath('n1', 'props'), '/novels/n1/props', '分区地址')
eq(chapterPath('n1', 'c1'), '/novels/n1/chapters/c1', '章节地址')
eq(chapterPath('n1', 'c1', { step: 'compose', tab: 'assets', canvas: true, view: 'graph' }),
   '/novels/n1/chapters/c1/compose/canvas?tab=assets&view=graph', '完整画布地址')
eq(chapterPath('n1', 'c1', { step: 'download', tab: 'assets', canvas: true, view: 'graph' }),
   '/novels/n1/chapters/c1/download', '非画布步骤丢掉页签、画布与视图')
eq(chapterPath('a b', 'c/1'), '/novels/a%20b/chapters/c%2F1', 'id 要编码')
eq(parseLocation('/novels/a%20b/chapters/c%2F1').loc,
   { kind: 'chapter', nid: 'a b', cid: 'c/1', step: null, tab: 'focus', canvas: false, view: 'timeline' }, 'id 要解码')
console.log('4. 拼地址 ✓')

// 5. state 透传：replace 时去掉一次性的键
eq(passState({ fromChapter: true, panel: 'film', vid: 'v1', jobId: 'j1', force: true }), { fromChapter: true, panel: 'film' },
   '透传保留 fromChapter / panel，去掉 vid / jobId / force')
eq(passState(null), {}, '没有 state 时是空对象')
console.log('5. state 透传 ✓')

console.log('\nALL PASS')
