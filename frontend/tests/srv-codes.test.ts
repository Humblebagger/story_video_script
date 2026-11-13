/** 后端代码清单（backend/server/messages_codes.json）↔ 前端 srv 文案：键齐全、无多余、占位符都是登记过的参数、
 *  中文文案与后端兜底一字不差。跑法：npm test（在 frontend/ 下运行） */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { zh } from '../src/i18n/zh'
import { en } from '../src/i18n/en'

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }
type Codes = Record<string, { params: string[]; zh: string }>
const codes = JSON.parse(readFileSync(resolve(process.cwd(), '../backend/server/messages_codes.json'), 'utf-8')) as Codes

const leaves = (node: unknown, prefix = ''): Record<string, string> => {
  const out: Record<string, string> = {}
  for (const [k, v] of Object.entries(node as Record<string, unknown>)) {
    const p = prefix ? `${prefix}.${k}` : k
    if (typeof v === 'string') out[p] = v
    else Object.assign(out, leaves(v, p))
  }
  return out
}
const zhSrv = leaves((zh as unknown as { srv: unknown }).srv)
const enSrv = leaves((en as unknown as { srv: unknown }).srv)
const holes = (s: string) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1])

for (const [code, { params, zh: zhText }] of Object.entries(codes)) {
  must(code in zhSrv, `zh 缺 srv.${code}`)
  must(code in enSrv, `en 缺 srv.${code}`)
  must(zhSrv[code] === zhText, `zh srv.${code} 与后端兜底不一致：${zhSrv[code]} ≠ ${zhText}`)
  for (const h of holes(enSrv[code])) must(params.includes(h), `en srv.${code} 的 {${h}} 不是登记过的参数`)
  for (const p of params) must(holes(enSrv[code]).includes(p), `en srv.${code} 漏了参数 {${p}}`)
}
for (const k of Object.keys(zhSrv)) must(k in codes, `zh 多余的 srv.${k}（后端没登记）`)
console.log(`\n${Object.keys(codes).length} codes`)
console.log('\nALL PASS')
