/** 全站统一的状态标签：圆点 + 文字，底色是语义色 12% 透明度；进行中的圆点缓慢脉动 */
import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

export type Tone = 'ok' | 'live' | 'warn' | 'err' | 'idle'
const TONE: Record<Tone, string> = {
  ok: 'var(--success)', live: 'var(--primary)', warn: 'var(--warning)',
  err: 'var(--destructive)', idle: 'var(--ui-muted-foreground)',
}

export function StatusPill({ tone, children, className }: { tone: Tone; children: ReactNode; className?: string }) {
  return (
    <span data-slot="status-pill" data-tone={tone}
          className={cn('status-pill inline-flex h-5 items-center gap-1.5 rounded-full px-2 text-xs font-medium', className)}
          style={{ ['--pill' as string]: TONE[tone] }}>
      <span className="status-pill__dot size-1.5 rounded-full" aria-hidden />
      {children}
    </span>
  )
}
