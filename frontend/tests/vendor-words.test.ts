/** 普通用户的语言包里不得出现厂商或模型名（文案与键名都查）。词表与后端共用：backend/server/vendor_words.json。
 *  反向对照：后台的语言包与价格表工具里有这些词（证明扫描有效；后台允许）。跑法：npm test（在 frontend/ 下） */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { zh } from '../src/i18n/zh'
import { en } from '../src/i18n/en'

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }
const words = JSON.parse(readFileSync(resolve(process.cwd(), '../backend/server/vendor_words.json'), 'utf-8')) as
  { substr: string[]; word: string[]; cjk: string[] }
const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
export const VENDOR_RE = new RegExp(
  [...words.substr.map(esc), ...words.cjk.map(esc), ...words.word.map((w) => `(?<![a-z0-9])${esc(w)}(?![a-z0-9])`)]
    .sort((a, b) => b.length - a.length).join('|'), 'gi')

/** 遍历语言包：每个属性一出现就扫键名（空对象下的键名也不漏），字符串叶子扫文案；
 *  不认识的节点类型（数字、布尔、数组、函数等）直接报错，免得新类型悄悄绕过扫描。返回 [路径, 文案] 与命中。 */
const scan = (node: unknown, prefix = ''): { leaves: [string, string][]; bad: [string, string][] } => {
  const leaves: [string, string][] = []
  const bad: [string, string][] = []
  for (const [k, v] of Object.entries(node as Record<string, unknown>)) {
    const p = prefix ? `${prefix}.${k}` : k
    if (k.match(VENDOR_RE)) bad.push([p, '（键名）'])
    if (typeof v === 'string') {
      leaves.push([p, v])
      if (v.match(VENDOR_RE)) bad.push([p, v])
    } else if (v !== null && typeof v === 'object' && !Array.isArray(v)) {
      const sub = scan(v, p)
      leaves.push(...sub.leaves)
      bad.push(...sub.bad)
    } else {
      throw new Error(`✗ 语言包里有不支持的节点类型 ${p}: ${Array.isArray(v) ? 'array' : typeof v}（扫描只认字符串与对象）`)
    }
  }
  return { leaves, bad }
}

for (const [name, pack] of [['zh', zh], ['en', en]] as const) {
  const { leaves, bad } = scan(pack)
  must(bad.length === 0, `${name} 语言包里有厂商或模型名：\n` + bad.slice(0, 20).map(([p, t]) => `  ${p}: ${t}`).join('\n'))
  console.log(`${name}: ${leaves.length} 条，无厂商词 ✓`)
}
// 自检：空对象下的厂商键名、数字叶子都要被抓到
must(scan({ a: { minimax: {} } }).bad.length === 1, '键名扫描：空对象下的厂商键名要报出')
let threw = false
try { scan({ a: 1 }) } catch { threw = true }
must(threw, '不支持的节点类型要报错')

// 反向对照：后台的源码里确实有这些词（读源文件，不 import，免得把后台代码拉进这个测试的构建）
const admin = ['messages.zh.ts', 'messages.en.ts', 'pricing.ts']
  .map((f) => readFileSync(resolve(process.cwd(), 'src/components/admin', f), 'utf-8')).join('\n')
must(!!admin.match(VENDOR_RE), '反向对照失败：后台源码里应能扫到厂商词（扫描失效？）')
// 词表自检：短词只在独立成词时命中
must(!'dark park spark'.match(VENDOR_RE) && !!'film.ark.x'.match(VENDOR_RE) && !!'MiniMax'.match(VENDOR_RE), '词表规则')
console.log('\nALL PASS')
