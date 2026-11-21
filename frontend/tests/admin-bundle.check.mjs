/** 构建产物检查：运营后台的代码、文案、接口地址、样式不在首屏下发的文件里，只在按需加载的块里。
 *  跑法（在 frontend/ 下，先 npm run build）：node tests/admin-bundle.check.mjs
 *  不进 npm test（它依赖 dist）。 */
import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

const dist = new URL('../dist/', import.meta.url).pathname
const read = (rel) => readFileSync(join(dist, rel), 'utf8')
const must = (cond, msg) => { if (!cond) { console.error('✗ ' + msg); process.exit(1) } }

// 首屏下发的文件：index.html 引用的脚本、预加载与样式，再加上这些脚本静态 import 的块（一路跟到底）
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
must([...eager].some((f) => f.endsWith('.js')) && [...eager].some((f) => f.endsWith('.css')), `index.html 应引用入口脚本与样式，实为 ${[...eager]}`)

// 后台专属的标识：组件的类名与测试钩子、接口地址、中英文文案
const MARKS = ['adm-nav', 'admin-shell', 'adm__pagehead', '/admin/overview', '/admin/audit', '运营概览', '返回产品', 'Usage & cost']
for (const file of eager) {
  const text = read(file)
  for (const mark of MARKS) must(!text.includes(mark), `首屏文件 ${file} 里不应出现后台标识「${mark}」`)
}

// 这些标识确实存在于按需加载的块里（否则上面的检查是空转）
const lazy = readdirSync(join(dist, 'assets')).map((f) => `assets/${f}`).filter((f) => /\.(js|css)$/.test(f) && !eager.has(f))
must(lazy.length > 0, '应有按需加载的块')
const lazyText = lazy.map(read).join('\n')
for (const mark of MARKS) must(lazyText.includes(mark), `按需加载的块里应有后台标识「${mark}」`)

console.log(`首屏文件 ${eager.size} 个，都不含后台标识；按需加载的块 ${lazy.length} 个，含全部 ${MARKS.length} 个标识`)
console.log('\nALL PASS')
