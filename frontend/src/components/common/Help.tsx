/** 「?」：鼠标移上或键盘聚焦时显示一句解释（概念不用内部术语） */
import { CircleHelp } from 'lucide-react'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useI18n } from '@/i18n/core'

export function Help({ text }: { text: string }) {
  const { t } = useI18n()
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button type="button" aria-label={t('common.help')} data-help={text}
                className="inline-flex size-4 items-center justify-center rounded-full text-muted-foreground hover:text-foreground focus-visible:outline-2">
          <CircleHelp className="size-3.5" />
        </button>
      </TooltipTrigger>
      <TooltipContent className="max-w-64">{text}</TooltipContent>
    </Tooltip>
  )
}
