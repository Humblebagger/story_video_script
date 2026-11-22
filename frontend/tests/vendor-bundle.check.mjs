/** 构建产物检查：首屏下发的文件（入口及其静态依赖、样式）里没有厂商或模型名；按需加载的块（运营后台）里有。
 *  依赖关系取自 vite 的构建清单（dist/.vite/manifest.json）：入口的静态 imports 与 css 一路跟到底，动态 imports 单独归为按需。
 *  dist/assets 下每个文件都必须能归入「首屏」或「按需」，归不进去就失败（不默认当按需）。词表与后端共用。
 *  跑法（在 frontend/ 下，先 npm run build）：node tests/vendor-bundle.check.mjs。不进 npm test（它依赖 dist）。 */
import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

const dist = new URL('../dist/', import.meta.url).pathname
const read = (rel) => readFileSync(join(dist, rel), 'utf8')
const must = (cond, msg) => { if (!cond) { console.error('✗ ' + msg); process.exit(1) } }
const words = JSON.parse(readFileSync(new URL('../../backend/server/vendor_words.json', import.meta.url), 'utf8'))
const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
const RE = new RegExp(
  [...words.substr.map(esc), ...words.cjk.map(esc), ...words.word.map((w) => `(?<![a-z0-9])${esc(w)}(?![a-z0-9])`)]
    .sort((a, b) => b.length - a.length).join('|'), 'gi')

const manifest = JSON.parse(read('.vite/manifest.json'))
const entries = Object.entries(manifest).filter(([, v]) => v.isEntry).map(([k]) => k)
must(entries.length > 0 && manifest['index.html'], `构建清单里应有入口 index.html，实为 ${Object.keys(manifest)}`)

// 从一组清单键出发，沿 imports（静态依赖）收集文件；每个块的 css 与 assets 一并带上。dynamicImports 只记下来，不算首屏。
const collect = (roots) => {
  const files = new Set()
  const dynamic = new Set()
  const seen = new Set()
  const stack = [...roots]
  while (stack.length) {
    const key = stack.pop()
    if (seen.has(key)) continue
    seen.add(key)
    const chunk = manifest[key]
    must(chunk, `构建清单里找不到 ${key}（无法分类的依赖）`)
    files.add(chunk.file)
    for (const f of [...(chunk.css ?? []), ...(chunk.assets ?? [])]) files.add(f)
    for (const k of chunk.imports ?? []) stack.push(k)
    for (const k of chunk.dynamicImports ?? []) dynamic.add(k)
  }
  return { files, dynamic }
}
const first = collect(entries)
const eager = first.files
// index.html 自己引用的文件也必须在首屏集合里（清单与页面不一致就失败）
const html = read('index.html')
for (const m of html.matchAll(/(?:src|href)="\/?(assets\/[^"]+\.(?:js|css))"/g)) {
  must(eager.has(m[1]), `index.html 引用的 ${m[1]} 不在清单推出的首屏集合里`)
}
// 按需：从动态 imports 出发（它们的静态依赖也算按需，除非已在首屏）
const lazyRoots = collect([...first.dynamic])
const lazy = new Set([...lazyRoots.files].filter((f) => !eager.has(f)))
// 完整性：dist/assets 下每个文件都得归类
for (const f of readdirSync(join(dist, 'assets')).map((n) => `assets/${n}`)) {
  must(eager.has(f) || lazy.has(f), `无法分类的产物 ${f}：既不在首屏依赖里，也不在动态 imports 可达的块里`)
}
must([...eager].some((f) => f.endsWith('.js')), `应有首屏脚本，实为 ${[...eager]}`)

const hits = (text) => [...text.matchAll(RE)].map((m) => `${m[0]} @ …${text.slice(Math.max(0, m.index - 40), m.index + 40).replace(/\s+/g, ' ')}…`)
for (const file of ['index.html', ...eager]) {
  const found = hits(read(file))
  must(found.length === 0, `首屏文件 ${file} 里有厂商或模型名（共 ${found.length} 处），前几处：\n  ` + found.slice(0, 8).join('\n  '))
}
// 首屏的 css 里再沿 @import 找本地依赖：能解析的并入扫描，解析不了的失败
for (const file of [...eager].filter((f) => f.endsWith('.css'))) {
  for (const m of read(file).matchAll(/@import\s*(?:url\()?["']?([^"')\s;]+)/g)) {
    must(/^(https?:)?\/\//.test(m[1]) || eager.has(`assets/${m[1].replace(/^\.\//, '')}`), `首屏样式 ${file} @import 了不在首屏集合里的 ${m[1]}`)
  }
}

// 反向对照：按需加载的块（后台）里确实有，证明扫描有效
must(lazy.size > 0 && [...lazy].some((f) => hits(read(f)).length > 0), '反向对照失败：按需加载的后台块里应能扫到厂商词')

console.log(`首屏文件 ${eager.size + 1} 个，无厂商词；按需加载的块 ${lazy.size} 个`)
console.log('\nALL PASS')
