import { tr } from '@/i18n/core'

/** 相对时间：刚刚 / N 分钟 / N 小时 / N 天；超过 30 天或无法解析时给日期 */
export function ago(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return ''
  const ts = Date.parse(iso)
  if (Number.isNaN(ts)) return ''
  const min = Math.floor((now - ts) / 60000)
  if (min < 1) return tr('shelf.ago.now')
  if (min < 60) return tr('shelf.ago.min', { n: min })
  if (min < 1440) return tr('shelf.ago.hour', { n: Math.floor(min / 60) })
  if (min < 43200) return tr('shelf.ago.day', { n: Math.floor(min / 1440) })
  return new Date(ts).toLocaleDateString()
}
