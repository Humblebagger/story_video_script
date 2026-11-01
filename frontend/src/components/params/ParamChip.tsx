/** 胶囊按钮 + 浮层外壳：图标、小字标签、粗体当前值；点开是 children */
import type { ReactNode } from 'react'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'

interface Props {
  icon: ReactNode
  label: string
  value: string
  children: ReactNode
  testId?: string
}

export function ParamChip({ icon, label, value, children, testId }: Props) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button type="button" data-testid={testId}
                className="inline-flex h-8 items-center gap-1.5 rounded-full border bg-background/60 px-3 text-sm outline-none transition-colors hover:border-ring focus-visible:ring-2 focus-visible:ring-ring/50 data-[state=open]:border-ring">
          <span className="text-muted-foreground [&_svg]:size-3.5" aria-hidden>{icon}</span>
          <span className="text-xs text-muted-foreground">{label}</span>
          <span className="font-semibold">{value}</span>
        </button>
      </PopoverTrigger>
      <PopoverContent>{children}</PopoverContent>
    </Popover>
  )
}
