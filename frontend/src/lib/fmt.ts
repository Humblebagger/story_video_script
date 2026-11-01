/** 金额与时长的统一格式：费用表、概览页、章节卡片共用。 */
import type { CostSum } from '../types'

export const cny = (n: number) => `¥${n.toFixed(2)}`
export const usd = (n: number) => `$${n.toFixed(2)}`

/** 「¥3.66 · $0.40」；没有汇总时给「—」 */
export function costText(cost: CostSum | null | undefined): string {
  if (!cost) return '—'
  return [cost.render_cny != null ? cny(cost.render_cny) : null, usd(cost.llm_usd)].filter(Boolean).join(' · ')
}

/** 秒数 → 分:秒（「1:05」）；没有或不为正时返回 null */
export function fmtDuration(s: number | null | undefined): string | null {
  if (s == null || !(s > 0)) return null
  const n = Math.round(s)
  return `${Math.floor(n / 60)}:${String(n % 60).padStart(2, '0')}`
}
