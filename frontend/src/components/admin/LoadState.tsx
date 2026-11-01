/** 后台各页共用的加载骨架与错误条。 */
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useI18n } from '@/i18n/core'
import { cn } from '@/lib/utils'

export function TableSkeleton() {
  return (
    <div className="flex flex-col gap-2 py-4" aria-busy="true">
      {Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-9 w-full" />)}
    </div>
  )
}

export function ErrorBar({ error, onRetry }: { error: string; onRetry: () => void }) {
  const { t } = useI18n()
  return (
    <div className="flex items-center gap-3 py-3 text-sm text-destructive">
      <span className="adm__err">{error}</span>
      <Button size="sm" variant="outline" onClick={onRetry}>{t('common.retry')}</Button>
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
