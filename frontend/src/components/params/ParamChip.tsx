/** 胶囊按钮 + 浮层外壳：图标、小字标签、粗体当前值；点开是 children */
import type { ComponentProps, ReactNode } from 'react'
import { cn } from '@/lib/utils'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'

interface Props {
  icon: ReactNode
  label: string
  value: string
  children: ReactNode
  testId?: string
  /** 受控打开（父组件要从外面打开浮层时用）；不传则自管 */
  open?: boolean
  onOpenChange?: (open: boolean) => void
  /** 透传给浮层内容（如 onCloseAutoFocus） */
  contentProps?: Omit<ComponentProps<typeof PopoverContent>, 'children'>
}

export function ParamChip({ icon, label, value, children, testId, open, onOpenChange, contentProps }: Props) {
  return (
    <Popover open={open} onOpenChange={onOpenChange}>
      <PopoverTrigger asChild>
        <button type="button" data-testid={testId}
                className="inline-flex h-8 items-center gap-1.5 rounded-full border bg-background/60 px-3 text-sm outline-none transition-colors hover:border-ring focus-visible:ring-2 focus-visible:ring-ring/50 data-[state=open]:border-ring">
          <span className="text-muted-foreground [&_svg]:size-3.5" aria-hidden>{icon}</span>
          <span className="text-xs text-muted-foreground">{label}</span>
          <span className="font-semibold">{value}</span>
        </button>
      </PopoverTrigger>
      <PopoverContent {...contentProps} className={cn('w-auto min-w-72', contentProps?.className)}>{children}</PopoverContent>
    </Popover>
  )
}
