/** 助手对话里的操作卡：标题、金额与要点；待确认时给「确认」「取消」（请求回来之前禁用）；
 *  确认后或不需确认的操作下面挂任务卡；没做成的写原因。 */
import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/i18n/core'
import type { MsgKey } from '@/i18n/core'
import type { AssistantCard, AssistantGoto } from '@/types'
import { TaskCard } from './TaskCard'

export function ActionCard({ novelId, c, busy, onDecide, onGoto }: {
  novelId: string
  c: AssistantCard
  /** 正在回答（或别的卡在发送）：按钮禁用 */
  busy: boolean
  onDecide: (decision: 'approve' | 'reject') => void
  onGoto: (g: AssistantGoto) => void
}) {
  const { t } = useI18n()
  const info = c.card
  const title = t(`assistant.action.${c.action}` as MsgKey) + (info?.chapter ? ` · ${info.chapter}` : '')
  const cost = !info || info.currency === null ? null
    : info.amount === null ? t('assistant.card.modelCost') : t('assistant.card.cny', { n: info.amount.toFixed(2) })
  const d = info?.detail ?? {}
  const notes = [
    d.clips !== undefined ? t('assistant.card.clips', { n: d.clips }) : null,
    d.chars !== undefined ? t(c.action === 'compose' ? 'assistant.card.ttsChars' : 'assistant.card.chars', { n: d.chars }) : null,
    d.archived ? t('assistant.card.archived') : null,
    c.action === 'compose' && d.draft ? t('assistant.card.draft') : null,
  ].filter((x): x is string => !!x)
  const locked = busy || !!c.sending
  return (
    <div className="assistant__card" data-testid="assistant-card" data-outcome={c.outcome}>
      <p className="font-medium">{title}</p>
      {cost && <p data-testid="assistant-card-cost">{cost}</p>}
      {!!notes.length && <p className="text-xs text-muted-foreground">{notes.join(t('common.listSep'))}</p>}
      {c.outcome === 'pending' && (
        <div className="flex gap-2">
          <Button size="sm" disabled={locked} data-testid="assistant-card-approve" onClick={() => onDecide('approve')}>
            {c.sending && <Loader2 className="size-3 animate-spin" />}
            {t('assistant.card.confirm')}
          </Button>
          <Button size="sm" variant="outline" disabled={locked} data-testid="assistant-card-reject" onClick={() => onDecide('reject')}>
            {t('assistant.card.reject')}
          </Button>
        </div>
      )}
      {c.outcome === 'approved' && <p className="text-xs text-muted-foreground">{t('assistant.card.approved')}</p>}
      {c.outcome === 'rejected' && (
        <p className="text-xs text-muted-foreground" data-testid="assistant-card-rejected">{t('assistant.card.rejected')}</p>
      )}
      {c.outcome === 'failed' && (
        <p className="text-xs text-destructive" data-testid="assistant-card-failed">{t('assistant.card.failed', { msg: c.error ?? '' })}</p>
      )}
      {c.task && (c.outcome === 'approved' || c.outcome === 'done') && (
        <TaskCard novelId={novelId} task={c.task} chapter={info?.chapter ?? ''} onGoto={onGoto} />
      )}
    </div>
  )
}
