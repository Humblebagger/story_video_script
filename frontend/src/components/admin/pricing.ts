/** 价格表的纯计算：厂商推断、编辑草稿与校验、保存体。 */
import type { PricingTable } from '../../types'

export const PRICE_KEYS = ['input', 'output', 'cache_read', 'cache_write'] as const
export type PriceKey = (typeof PRICE_KEYS)[number]

/** 按模型名前缀推断厂商；认不出返回 null。 */
export function inferVendor(model: string): string | null {
  const m = model.trim().toLowerCase()
  const rules: [RegExp, string][] = [
    [/^claude/, 'Anthropic'], [/^deepseek/, 'DeepSeek'], [/^minimax/, 'MiniMax'],
    [/^(doubao|seedance|ark)/, 'ByteDance'], [/^(gpt|o1|o3|o4)/, 'OpenAI'],
    [/^gemini/, 'Google'], [/^qwen/, 'Alibaba'],
  ]
  for (const [re, v] of rules) if (re.test(m)) return v
  return null
}

/** 编辑中的一行：价格先当文本存着，保存时才转数字。 */
export interface DraftRow {
  id: number
  name: string
  vendor: string
  input: string
  output: string
  cache_read: string
  cache_write: string
}

export type RowErrors = Partial<Record<'name' | PriceKey, 'empty' | 'dup' | 'price'>>

export function toDrafts(models: PricingTable['models']): DraftRow[] {
  return Object.entries(models).map(([name, p], i) => ({
    id: i, name, vendor: p.vendor ?? '',
    input: String(p.input), output: String(p.output),
    cache_read: String(p.cache_read), cache_write: String(p.cache_write),
  }))
}

export function parsePrice(s: string): number | null {
  if (s.trim() === '') return null
  const n = Number(s)
  return Number.isFinite(n) && n >= 0 ? n : null
}

/** 逐行校验：名称非空且不重复，四个价都是有限非负数。返回 行 id → 错误；空对象表示通过。 */
export function validateDrafts(rows: DraftRow[]): Record<number, RowErrors> {
  const out: Record<number, RowErrors> = {}
  const seen = new Map<string, number>()
  for (const r of rows) {
    const e: RowErrors = {}
    const name = r.name.trim()
    if (!name) e.name = 'empty'
    else if (seen.has(name)) e.name = 'dup'
    else seen.set(name, r.id)
    for (const k of PRICE_KEYS) if (parsePrice(r[k]) === null) e[k] = 'price'
    if (Object.keys(e).length) out[r.id] = e
  }
  return out
}

/** PUT 体：只含 models；每行四价，厂商填了才带。 */
export function buildPayload(rows: DraftRow[]) {
  const models: Record<string, Record<string, number | string>> = {}
  for (const r of rows) {
    const row: Record<string, number | string> = {}
    for (const k of PRICE_KEYS) row[k] = parsePrice(r[k]) as number
    if (r.vendor.trim()) row.vendor = r.vendor.trim()
    models[r.name.trim()] = row
  }
  return { models }
}
