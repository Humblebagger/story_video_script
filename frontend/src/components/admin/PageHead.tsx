import type { ReactNode } from 'react'
import { RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'

/** 后台每一页的标题行：左边页名（可带一行说明），右边操作。 */
export function PageHead({ title, hint, children }: { title: string; hint?: string; children?: ReactNode }) {
  return (
    <div className="adm__pagehead">
      <div className="min-w-0">
        <h2 className="text-lg font-semibold">{title}</h2>
        {hint && <p className="adm__note">{hint}</p>}
      </div>
      {children && <div className="adm__bar">{children}</div>}
    </div>
  )
}

export function RefreshButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <Button size="sm" variant="outline" type="button" onClick={onClick}>
      <RefreshCw aria-hidden />{label}
    </Button>
  )
}
