/** 构建产物检查：首屏下发的文件（index.html 引用的脚本、样式及其静态依赖）里没有厂商或模型名；
 *  按需加载的块（运营后台）里有。词表与后端共用。
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

// 首屏文件：与 admin-bundle.check.mjs 同一算法
const html = read('index.html')
const eager = new Set([...html.matchAll(/(?:src|href)="\/?(assets\/[^"]+\.(?:js|css))"/g)].map((m) => m[1]))
const queue = [...eager].filter((f) => f.endsWith('.js'))
while (queue.length) {
  const src = read(queue.pop())
  for (const m of src.matchAll(/(?:from|import)\s*"\.\/([^"]+\.js)"/g)) {
    const file = `assets/${m[1]}`
    if (!eager.has(file)) { eager.add(file); queue.push(file) }
  }
}
must([...eager].some((f) => f.endsWith('.js')), `index.html 应引用入口脚本，实为 ${[...eager]}`)

const hits = (text) => [...text.matchAll(RE)].map((m) => `${m[0]} @ …${text.slice(Math.max(0, m.index - 40), m.index + 40).replace(/\s+/g, ' ')}…`)
for (const file of ['index.html', ...eager]) {
  const found = hits(read(file))
  must(found.length === 0, `首屏文件 ${file} 里有厂商或模型名（共 ${found.length} 处），前几处：\n  ` + found.slice(0, 8).join('\n  '))
}

// 反向对照：按需加载的块（后台）里确实有，证明扫描有效
const lazy = readdirSync(join(dist, 'assets')).map((f) => `assets/${f}`).filter((f) => f.endsWith('.js') && !eager.has(f))
must(lazy.length > 0 && lazy.some((f) => hits(read(f)).length > 0), '反向对照失败：按需加载的后台块里应能扫到厂商词')

console.log(`首屏文件 ${eager.size + 1} 个，无厂商词；按需加载的块 ${lazy.length} 个`)
console.log('\nALL PASS')
