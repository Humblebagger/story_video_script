import type { ReactNode } from 'react'
import { ArrowRight } from 'lucide-react'
import { Card } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import { AdminLink } from './AdminLink'

/** 数字卡片：标签、大数字、副标题（拿不到就不传）、行动链接。 */
export function StatCard({ id, label, value, sub, bad, to, action, children }: {
  id: string; label: string; value: string; sub?: string | null; bad?: boolean
  to?: string; action?: string; children?: ReactNode
}) {
  return (
    <Card className="adm__card gap-1 px-4 py-3" data-testid={`stat-${id}`}>
      <span className="text-xs text-muted-foreground">{label}</span>
      <b className={cn('font-mono text-2xl font-semibold tabular-nums', bad && 'text-destructive')}>{value}</b>
      {sub && <span className="adm__sub">{sub}</span>}
      {children}
      {to && action && (
        <AdminLink to={to} className="adm__go">{action}<ArrowRight size={12} aria-hidden /></AdminLink>
      )}
    </Card>
  )
}

export interface DistRow { label: string; value: string; share: number }

/** 分布小卡片：每行一个标签、一个数和一条占比条（share 取 0 到 1）。 */
export function DistCard({ id, title, rows, empty, note, to, action }: {
  id: string; title: string; rows: DistRow[]; empty: string; note?: string | null; to?: string; action?: string
}) {
  return (
    <Card className="adm__card gap-2 px-4 py-3" data-testid={`dist-${id}`}>
      <h3 className="text-sm font-semibold">{title}</h3>
      {rows.length === 0 && <p className="adm__note">{empty}</p>}
      {rows.map((r) => (
        <div key={r.label} className="adm__dist">
          <span className="min-w-0 truncate" title={r.label}>{r.label}</span>
          <span className="font-mono tabular-nums">{r.value}</span>
          <span className="adm__dist-track" aria-hidden>
            <span className="adm__dist-fill" style={{ width: `${Math.round(Math.min(Math.max(r.share, 0), 1) * 100)}%` }} />
          </span>
        </div>
      ))}
      {note && <p className="adm__note">{note}</p>}
      {to && action && (
        <AdminLink to={to} className="adm__go">{action}<ArrowRight size={12} aria-hidden /></AdminLink>
      )}
    </Card>
  )
}
