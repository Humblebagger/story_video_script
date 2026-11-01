/** 危险操作的确认（删除、覆盖、停用…）：全站统一。用法：
 *    const [ask, confirmUi] = useConfirm()
 *    if (!(await ask({ title, body, action, danger: true }))) return
 *    …  并在 JSX 里渲染 {confirmUi}
 *  不需要全局 Provider：单测直接渲染组件也能用。花钱的确认用 MoneyConfirm，不用它。 */
import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { buttonVariants } from '@/components/ui/button'
import { useI18n } from '@/i18n/core'

export interface ConfirmOpts {
  title: string
  body?: ReactNode
  /** 确认按钮文字，默认「确定」 */
  action?: string
  /** 红色确认按钮（删除、停用） */
  danger?: boolean
}

export function useConfirm(): [(o: ConfirmOpts) => Promise<boolean>, ReactNode] {
  const { t } = useI18n()
  const [opts, setOpts] = useState<ConfirmOpts | null>(null)
  const [open, setOpen] = useState(false)
  const resolver = useRef<((v: boolean) => void) | null>(null)
  // 还没回答组件就卸载了（比如关掉了画布）：当取消，等着的调用方别永远挂着
  useEffect(() => () => { resolver.current?.(false); resolver.current = null }, [])
  const settle = (v: boolean) => {
    resolver.current?.(v)
    resolver.current = null
    setOpen(false) // opts 留着，关闭动画期间内容不消失
  }
  const ask = useCallback((o: ConfirmOpts) => new Promise<boolean>((res) => {
    resolver.current?.(false) // 上一个还没答就来新的：旧的当取消
    resolver.current = res
    setOpts(o)
    setOpen(true)
  }), [])
  const ui = opts && (
    <AlertDialog open={open} onOpenChange={(o) => { if (!o) settle(false) }}>
      <AlertDialogContent data-testid="confirm-dialog">
        <AlertDialogHeader>
          <AlertDialogTitle>{opts.title}</AlertDialogTitle>
          {opts.body && <AlertDialogDescription className="whitespace-pre-line">{opts.body}</AlertDialogDescription>}
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel data-testid="confirm-cancel" onClick={() => settle(false)}>{t('common.cancel')}</AlertDialogCancel>
          <AlertDialogAction data-testid="confirm-ok"
                             className={opts.danger ? buttonVariants({ variant: 'destructive' }) : undefined}
                             onClick={() => settle(true)}>
            {opts.action ?? t('confirm.ok')}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
  return [ask, ui]
}
