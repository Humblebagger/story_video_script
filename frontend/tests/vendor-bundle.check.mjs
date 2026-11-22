/** 构建产物检查：首屏下发的文件（入口及其静态依赖、样式）里没有厂商或模型名；按需加载的块（运营后台）里有。
 *  依赖关系取自 vite 的构建清单（dist/.vite/manifest.json）：入口的静态 imports 与 css 一路跟到底，动态 imports 单独归为按需。
 *  dist/assets 下每个文件都必须能归入「首屏」或「按需」，归不进去就失败（不默认当按需）。词表与后端共用。
 *  跑法（在 frontend/ 下，先 npm run build）：node tests/vendor-bundle.check.mjs。不进 npm test（它依赖 dist）。 */
import { readdirSync, readFileSync } from 'node:fs'
import { join, posix } from 'node:path'

const dist = new URL('../dist/', import.meta.url).pathname
const read = (rel) => readFileSync(join(dist, rel), 'utf8')
const must = (cond, msg) => { if (!cond) { console.error('✗ ' + msg); process.exit(1) } }
const words = JSON.parse(readFileSync(new URL('../../backend/server/vendor_words.json', import.meta.url), 'utf8'))
const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
const RE = new RegExp(
  [...words.substr.map(esc), ...words.cjk.map(esc), ...words.word.map((w) => `(?<![a-z0-9])${esc(w)}(?![a-z0-9])`)]
    .sort((a, b) => b.length - a.length).join('|'), 'gi')

// 清单分类：入口的静态 imports / css / assets 一路跟到底为首屏；动态 imports 用队列展开成闭包（二级、三级动态块及各块的静态依赖、
// css、资源都算），再减去首屏集合为按需。清单里缺键直接抛错（无法分类的依赖）。
const classify = (manifest) => {
  const entries = Object.entries(manifest).filter(([, v]) => v.isEntry).map(([k]) => k)
  const walk = (roots) => {
    const files = new Set()
    const dynamic = new Set()
    const seen = new Set()
    const stack = [...roots]
    while (stack.length) {
      const key = stack.pop()
      if (seen.has(key)) continue
      seen.add(key)
      const chunk = manifest[key]
      if (!chunk) throw new Error(`构建清单里找不到 ${key}（无法分类的依赖）`)
      files.add(chunk.file)
      for (const f of [...(chunk.css ?? []), ...(chunk.assets ?? [])]) files.add(f)
      for (const k of chunk.imports ?? []) stack.push(k)
      for (const k of chunk.dynamicImports ?? []) dynamic.add(k)
    }
    return { files, dynamic }
  }
  const first = walk(entries)
  const lazyFiles = new Set()
  const doneDyn = new Set()
  let pending = [...first.dynamic]
  while (pending.length) {
    const batch = pending.filter((k) => !doneDyn.has(k))
    pending = []
    for (const k of batch) doneDyn.add(k)
    if (!batch.length) break
    const r = walk(batch)
    for (const f of r.files) lazyFiles.add(f)
    pending = [...r.dynamic]
  }
  return { entries, eager: first.files, lazy: new Set([...lazyFiles].filter((f) => !first.files.has(f))) }
}

// 分类函数自检：二级动态导入（入口 → 动态块 B → 动态块 C，C 静态依赖 D，各带 css）要全部归为按需
{
  const m = {
    'index.html': { file: 'assets/i.js', isEntry: true, imports: ['a'], dynamicImports: ['b'], css: ['assets/i.css'] },
    a: { file: 'assets/a.js' },
    b: { file: 'assets/b.js', dynamicImports: ['c'], css: ['assets/b.css'] },
    c: { file: 'assets/c.js', imports: ['d'], css: ['assets/c.css'], assets: ['assets/c.png'] },
    d: { file: 'assets/d.js', dynamicImports: ['e'] },
    e: { file: 'assets/e.js' },
  }
  const r = classify(m)
  must([...r.eager].sort().join() === 'assets/a.js,assets/i.css,assets/i.js', `自检：首屏集合 ${[...r.eager]}`)
  must([...r.lazy].sort().join() === 'assets/b.css,assets/b.js,assets/c.css,assets/c.js,assets/c.png,assets/d.js,assets/e.js',
    `自检：二级及更深的动态导入与它们的静态依赖都应归为按需：${[...r.lazy]}`)
  let threw = false
  try { classify({ 'index.html': { file: 'x.js', isEntry: true, imports: ['missing'] } }) } catch { threw = true }
  must(threw, '自检：清单里缺键要报错')
}

const manifest = JSON.parse(read('.vite/manifest.json'))
must(manifest['index.html'], `构建清单里应有入口 index.html，实为 ${Object.keys(manifest)}`)
let cls
try { cls = classify(manifest) } catch (e) { must(false, e.message) }
const { eager, lazy } = cls
// index.html 里的每个本地脚本、样式、预加载等引用（相对或绝对路径）：必须是 dist 里存在的文件；不在清单推出的首屏集合里的，
// 一律并入首屏扫描（它们照样在首屏被浏览器加载）；指向 dist 之外或不存在的本地引用直接失败
const html = read('index.html')
const norm = (ref) => {
  const clean = ref.split(/[?#]/)[0].replace(/^\.?\//, '')
  return clean
}
for (const m of html.matchAll(/<(?:script|link)\b[^>]*?\b(?:src|href)\s*=\s*["']([^"']+)["']/gi)) {
  const ref = m[1]
  if (/^(?:[a-z][a-z0-9+.-]*:|\/\/)/i.test(ref)) continue   // 外部地址或内联 data：浏览器去别处取，不在产物里
  const rel = norm(ref)
  must(rel && !rel.split('/').includes('..'), `index.html 的本地引用 ${ref} 无法归类`)
  try { read(rel) } catch { must(false, `index.html 引用的本地文件 ${ref} 在 dist 里不存在`) }
  eager.add(rel)
}
// 完整性：dist/assets 下每个文件都得归类
for (const f of readdirSync(join(dist, 'assets')).map((n) => `assets/${n}`)) {
  must(eager.has(f) || lazy.has(f), `无法分类的产物 ${f}：既不在首屏依赖里，也不在动态 imports 可达的块里`)
}
must([...eager].some((f) => f.endsWith('.js')), `应有首屏脚本，实为 ${[...eager]}`)

const hits = (text) => [...text.matchAll(RE)].map((m) => `${m[0]} @ …${text.slice(Math.max(0, m.index - 40), m.index + 40).replace(/\s+/g, ' ')}…`)
const TEXT = /\.(?:js|mjs|css|html|svg|json|txt|webmanifest)$/i
for (const file of ['index.html', ...eager].filter((f) => TEXT.test(f))) {
  const found = hits(read(file))
  must(found.length === 0, `首屏文件 ${file} 里有厂商或模型名（共 ${found.length} 处），前几处：\n  ` + found.slice(0, 8).join('\n  '))
}
// 首屏的 css 里再沿 @import 找本地依赖：能解析的并入扫描，解析不了的失败
for (const file of [...eager].filter((f) => f.endsWith('.css'))) {
  for (const m of read(file).matchAll(/@import\s*(?:url\()?["']?([^"')\s;]+)/g)) {
    must(/^(?:[a-z][a-z0-9+.-]*:|\/\/)/i.test(m[1]) || eager.has(posix.normalize(posix.join(posix.dirname(file), m[1].split(/[?#]/)[0]))), `首屏样式 ${file} @import 了不在首屏集合里的 ${m[1]}`)
  }
}

// 反向对照：按需加载的块（后台）里确实有，证明扫描有效
must(lazy.size > 0 && [...lazy].some((f) => hits(read(f)).length > 0), '反向对照失败：按需加载的后台块里应能扫到厂商词')

console.log(`首屏文件 ${eager.size + 1} 个，无厂商词；按需加载的块 ${lazy.size} 个`)
console.log('\nALL PASS')
