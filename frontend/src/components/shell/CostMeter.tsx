/** 顶栏的费用表：「¥3.66 · $0.40」，点开浮层看三行明细（大模型、出片与配音、上限）。
 *  传了 chapterId 且该章有费用时显示该章的；汇总没读到时显示「—」。 */
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { useI18n } from '@/i18n/core'
import type { CostSum, NovelSummaryData } from '@/types'

const cny = (n: number) => `¥${n.toFixed(2)}`
const usd = (n: number) => `$${n.toFixed(2)}`

export function CostMeter({ data, chapterId }: { data: NovelSummaryData | null; chapterId?: string | null }) {
  const { t } = useI18n()
  const cost: CostSum | null = data
    ? (chapterId ? data.chapters.find((c) => c.id === chapterId)?.cost : null) ?? data.cost
    : null
  const text = cost
    ? [cost.render_cny != null ? cny(cost.render_cny) : null, usd(cost.llm_usd)].filter(Boolean).join(' · ')
    : '—'
  const dash = '—'
  const rows: [string, string][] = cost ? [
    [t('shell.cost.llm'), usd(cost.llm_usd)],
    [t('shell.cost.render'), cost.render_cny != null ? cny(cost.render_cny) : dash],
    [t('shell.cost.budget'), cost.budget_cny != null ? cny(cost.budget_cny) : t('shell.cost.unset')],
  ] : []
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="sm" className="font-mono text-xs tabular-nums" aria-label={t('shell.cost.label')}
                data-testid="cost-meter">
          {text}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-64">
        <p className="mb-2 text-xs font-medium text-muted-foreground">{t('shell.cost.label')}</p>
        {rows.length === 0 && <p className="text-sm text-muted-foreground">{dash}</p>}
        {rows.map(([k, v]) => (
          <div key={k} data-testid="cost-row" className="flex items-center justify-between gap-3 py-1 text-sm">
            <span className="text-muted-foreground">{k}</span>
            <span className="font-mono tabular-nums">{v}</span>
          </div>
        ))}
      </PopoverContent>
    </Popover>
  )
}
