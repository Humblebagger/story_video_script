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

/** 叶子：路径 → 文案；路径本身（键名）也要查 */
const leaves = (node: unknown, prefix = ''): [string, string][] =>
  Object.entries(node as Record<string, unknown>).flatMap(([k, v]) => {
    const p = prefix ? `${prefix}.${k}` : k
    return typeof v === 'string' ? [[p, v] as [string, string]] : leaves(v, p)
  })

for (const [name, pack] of [['zh', zh], ['en', en]] as const) {
  const bad = leaves(pack).filter(([path, text]) => `${path}\n${text}`.match(VENDOR_RE))
  must(bad.length === 0, `${name} 语言包里有厂商或模型名：\n` + bad.slice(0, 20).map(([p, t]) => `  ${p}: ${t}`).join('\n'))
  console.log(`${name}: ${leaves(pack).length} 条，无厂商词 ✓`)
}

// 反向对照：后台的源码里确实有这些词（读源文件，不 import，免得把后台代码拉进这个测试的构建）
const admin = ['messages.zh.ts', 'messages.en.ts', 'pricing.ts']
  .map((f) => readFileSync(resolve(process.cwd(), 'src/components/admin', f), 'utf-8')).join('\n')
must(!!admin.match(VENDOR_RE), '反向对照失败：后台源码里应能扫到厂商词（扫描失效？）')
// 词表自检：短词只在独立成词时命中
must(!'dark park spark'.match(VENDOR_RE) && !!'film.ark.x'.match(VENDOR_RE) && !!'MiniMax'.match(VENDOR_RE), '词表规则')
console.log('\nALL PASS')
