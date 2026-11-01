import { cn } from '@/lib/utils'
import type { AspectRatio, NovelParams } from '../../types'

const RATIOS: AspectRatio[] = ['9:16', '16:9', '1:1', '4:3']
const MAX = 28

const box = (r: AspectRatio) => {
  const [w, h] = r.split(':').map(Number)
  const k = MAX / Math.max(w, h)
  return { width: Math.round(w * k), height: Math.round(h * k) }
}

interface Props { value: NovelParams; onChange: (next: NovelParams) => void }

export function RatioPicker({ value, onChange }: Props) {
  return (
    <div className="flex gap-2">
      {RATIOS.map((r) => {
        const on = value.aspect_ratio === r
        return (
          <button key={r} type="button" data-ratio={r} aria-pressed={on}
                  onClick={() => onChange({ ...value, aspect_ratio: r })}
                  className={cn(
                    'flex w-16 flex-col items-center gap-1.5 rounded-lg border-2 px-2 py-2 text-xs outline-none transition-colors hover:border-ring focus-visible:ring-2 focus-visible:ring-ring/50',
                    on ? 'border-primary text-foreground' : 'border-transparent text-muted-foreground')}>
            <span className="flex h-7 items-center">
              <span className={cn('block rounded-[3px] border-2', on ? 'border-primary' : 'border-current')} style={box(r)} />
            </span>
            {r}
          </button>
        )
      })}
    </div>
  )
}
