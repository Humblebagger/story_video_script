/** 后台各页共用的加载骨架、错误条与空状态。 */
import { Inbox } from 'lucide-react'
import type { ReactNode } from 'react'
import { EmptyState } from '@/components/common/EmptyState'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useI18n } from '@/i18n/core'
import { formatMsg } from '@/i18n/serverMsg'
import type { MsgLike } from '@/i18n/serverMsg'
import { cn } from '@/lib/utils'

export function TableSkeleton() {
  return (
    <div className="adm-skel" aria-busy="true">
      {Array.from({ length: 5 }, (_, i) => (
        <div key={i} className="adm-skel__row">
          <Skeleton className="adm-skel__dot" />
          <div className="adm-skel__lines">
            <Skeleton className="adm-skel__bar" />
            <Skeleton className="adm-skel__bar is-short" />
          </div>
          <Skeleton className="adm-skel__value" />
          <Skeleton className="adm-skel__pill" />
        </div>
      ))}
    </div>
  )
}

export function ErrorBar({ error, onRetry }: { error: MsgLike; onRetry: () => void }) {
  const { t, locale } = useI18n()
  return (
    <div className="adm__errbar flex items-center gap-3 px-4 py-3 text-sm text-destructive">
      <span className="adm__err">{formatMsg(error, locale)}</span>
      <Button size="sm" variant="outline" onClick={onRetry}>{t('common.retry')}</Button>
    </div>
  )
}

export type EmptyTone = 'blue' | 'violet' | 'rose' | 'sand' | 'clay'

/** 空状态：各页统一用这一个（图标 + 一句话 + 可选的说明），带分色卡片底。 */
export function Empty({ title, hint, tone = 'blue', icon }: {
  title: string; hint?: string; tone?: EmptyTone; icon?: ReactNode
}) {
  return (
    <div className="adm__emptycard" data-tone={tone}>
      <EmptyState icon={icon ?? <Inbox aria-hidden />} title={title} hint={hint} compact />
    </div>
  )
}

/** 分段控件：和分镜视图的页签同一套写法（is-on 是测试钩子）。 */
export function Segmented<T extends string | number>({ items, value, onChange, label }: {
  items: [T, string][]; value: T; onChange: (v: T) => void; label?: string
}) {
  return (
    <div className="inline-flex shrink-0 rounded-lg bg-muted p-1" role="group" aria-label={label}>
      {items.map(([id, name]) => (
        <button
          key={id}
          type="button"
          aria-pressed={value === id}
          className={cn(
            'rounded-md border-0 px-3 py-1.5 text-sm text-muted-foreground',
            'transition-[color,background-color,box-shadow] duration-150 ease-out hover:text-foreground',
            value === id && 'is-on bg-background font-medium text-foreground shadow-sm dark:bg-foreground/10',
          )}
          onClick={() => onChange(id)}
        >
          {name}
        </button>
      ))}
    </div>
  )
}
