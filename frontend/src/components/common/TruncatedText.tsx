import { useEffect, useId, useRef, useState } from 'react'
import { useI18n } from '@/i18n/core'
import { cn } from '@/lib/utils'

/** 多行截断 + 「查看全文 / 收起」。只在内容真的溢出时出现按钮。 */
export function TruncatedText({ text, lines = 2, className, strong, testId }: {
  text: string
  lines?: number
  className?: string
  strong?: boolean
  testId?: string
}) {
  const { t } = useI18n()
  const ref = useRef<HTMLParagraphElement>(null)
  const id = useId()
  const [open, setOpen] = useState(false)
  const [overflow, setOverflow] = useState(false)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const measure = () => {
      if (open) return
      setOverflow(el.scrollHeight > el.clientHeight + 1)
    }
    measure()
    if (typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [text, open, lines])

  useEffect(() => { setOpen(false) }, [text])

  return (
    <div className={cn('truncate-text', className)}>
      <p ref={ref} id={id} data-testid={testId} title={open ? undefined : text}
         className={cn('truncate-text__body', strong && 'font-medium', open && 'is-open')}
         style={{ WebkitLineClamp: open ? undefined : lines }}>
        {text}
      </p>
      {overflow && (
        <button type="button" className="truncate-text__toggle" aria-expanded={open}
                aria-controls={id} onClick={() => setOpen((v) => !v)}>
          {t(open ? 'common.collapse' : 'common.viewFull')}
        </button>
      )}
    </div>
  )
}
