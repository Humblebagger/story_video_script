/** 花钱前的确认（全站统一）：标题、可选的明细行、合计加粗、已花 / 在跑预留 / 执行后累计 / 上限、
 *  金额变了的提示、超上限的拦截、费率依据。确认按钮上写金额。出片与合成在子计划 4 换成它。 */
import type { ReactNode } from 'react'
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { useI18n } from '@/i18n/core'

const yuan = (n: number) => `¥${n.toFixed(2)}`

export interface MoneyConfirmProps {
  open: boolean
  title: string
  /** 合计（本次要花的） */
  cny: number
  spent: number
  reserved?: number
  budget: number
  /** 服务端重算后金额变了 */
  changed?: boolean
  rateNote?: string
  /** 确认按钮的动作词，如「确认出片」 */
  action: string
  /** 额外拦截（未保存、验证门没过）：为 true 时确认按钮禁用 */
  blocked?: boolean
  busy?: boolean
  /** 明细（如批量出片的各段）、警告 */
  children?: ReactNode
  onConfirm: () => void
  onCancel: () => void
}

export function MoneyConfirm(p: MoneyConfirmProps) {
  const { t } = useI18n()
  const after = Math.round((p.spent + (p.reserved ?? 0) + p.cny) * 100) / 100
  const over = after > p.budget + 1e-9
  return (
    <AlertDialog open={p.open} onOpenChange={(o) => { if (!o) p.onCancel() }}>
      <AlertDialogContent data-testid="money-confirm">
        <AlertDialogHeader>
          <AlertDialogTitle>{p.title}</AlertDialogTitle>
          <AlertDialogDescription asChild>
            <div className="space-y-3 text-sm">
              {p.changed && <p className="text-destructive">{t('money.changed', { amount: yuan(p.cny) })}</p>}
              {p.children}
              <div className="rounded-lg border bg-muted/40 p-3">
                <div className="flex items-baseline justify-between">
                  <span>{t('money.total')}</span>
                  <b className="text-2xl font-semibold tabular-nums text-foreground">{yuan(p.cny)}</b>
                </div>
                <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-muted-foreground tabular-nums">
                  <span>{t('money.spent')} {yuan(p.spent)}</span>
                  {!!p.reserved && <span>{t('money.reserved')} {yuan(p.reserved)}</span>}
                  <span>{t('money.after')} {yuan(after)}</span>
                  <span>{t('money.budget')} {yuan(p.budget)}</span>
                </div>
              </div>
              {over && <p className="text-destructive">{t('money.over')}</p>}
              <p className="text-xs text-muted-foreground">
                {t('money.rateNote', { note: p.rateNote || t('money.rateUnknown') })}
              </p>
            </div>
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
          <AlertDialogAction disabled={p.busy || over || p.blocked}
                             onClick={(e) => { e.preventDefault(); p.onConfirm() }}>
            {t('money.confirm', { action: p.action, amount: yuan(p.cny) })}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
