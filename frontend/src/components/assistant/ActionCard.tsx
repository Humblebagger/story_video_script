/** 助手对话里的操作卡：标题、金额与要点；待确认时给「确认」「取消」（请求回来之前禁用）；
 *  确认后或不需确认的操作下面挂任务卡；没做成的写原因。 */
import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { translate, useI18n } from '@/i18n/core'
import { formatMsg } from '@/i18n/serverMsg'
import type { MsgKey } from '@/i18n/core'
import type { AssistantCard, AssistantGoto } from '@/types'
import { TaskCard } from './TaskCard'

/** 后端写进 diff.target 的中文后缀（内部值），取自中文语言包 */
const ZH_SUFFIX = translate('zh', 'assistant.target.synopsis', { chapter: '' })
const EDITS = ['shots_edit', 'asset_edit', 'plot_edit']

export function ActionCard({ novelId, c, busy, onDecide, onUndo, onGoto }: {
  novelId: string
  c: AssistantCard
  /** 正在回答（或别的卡在发送）：按钮禁用 */
  busy: boolean
  onDecide: (decision: 'approve' | 'reject') => void
  onUndo: () => void
  onGoto: (g: AssistantGoto) => void
}) {
  const { t, locale } = useI18n()
  const info = c.card
  const edit = EDITS.includes(c.action)
  const title = t(`assistant.action.${c.action}` as MsgKey) + (info?.chapter ? ` · ${info.chapter}` : '')
  const cost = !info || info.currency === null ? null
    : info.amount === null ? t('assistant.card.modelCost') : t('assistant.card.cny', { n: info.amount.toFixed(2) })
  const d = info?.detail ?? {}
  const notes = [
    d.clips !== undefined ? t('assistant.card.clips', { n: d.clips }) : null,
    d.chars !== undefined ? t(c.action === 'compose' ? 'assistant.card.ttsChars' : 'assistant.card.chars', { n: d.chars }) : null,
    d.edits !== undefined ? t('assistant.card.edits', { n: d.edits }) : null,
    d.archived ? t('assistant.card.archived') : null,
    c.action === 'compose' && d.draft ? t('assistant.card.draft') : null,
  ].filter((x): x is string => !!x)
  const fieldName = (f: string) => {
    const key = `assistant.field.${f.replace(/\./g, '_')}` as MsgKey  // t() splits keys on '.'
    const s = t(key)
    return s === key ? f : s
  }
  /** diff 的 target 是内部值（恢复时比对，不能改）：plot_edit 的两类按字段翻译，其余是数据原样显示 */
  const targetOf = (r: { target: string; field: string }) =>
    c.action !== 'plot_edit' ? r.target
      : r.field === 'outline' ? t('assistant.target.outline')
      : r.field === 'synopsis' ? t('assistant.target.synopsis', { chapter: info?.chapter || (r.target.endsWith(ZH_SUFFIX) ? r.target.slice(0, -ZH_SUFFIX.length) : r.target) })
      : r.target
  const locked = busy || !!c.sending
  return (
    <div className="assistant__card" data-testid="assistant-card" data-outcome={c.outcome}>
      <p className="font-medium">{title}</p>
      {cost && <p data-testid="assistant-card-cost">{cost}</p>}
      {!!notes.length && <p className="text-xs text-muted-foreground">{notes.join(t('common.listSep'))}</p>}
      {!!info?.diff?.length && (
        <ul className="assistant__diff">
          {info.diff.map((r, i) => (
            <li key={i} data-testid="assistant-diff-row">
              <p className="text-xs text-muted-foreground">{targetOf(r)} · {fieldName(r.field)}</p>
              <p className="assistant__diff-before">{r.before}</p>
              <p className="assistant__diff-after">{r.after}</p>
            </li>
          ))}
        </ul>
      )}
      {!!info?.warnings?.length && (
        <div className="assistant__warn" data-testid="assistant-card-warnings">
          <p>{t('assistant.card.warnings')}</p>
          <ul className="list-disc pl-4">{info.warnings.map((w, i) => <li key={i}>{formatMsg(w, locale)}</li>)}</ul>
        </div>
      )}
      {c.outcome === 'pending' && (
        <div className="flex gap-2">
          <Button size="sm" disabled={locked} data-testid="assistant-card-approve" onClick={() => onDecide('approve')}>
            {c.sending && <Loader2 className="size-3 animate-spin" />}
            {t(edit ? 'assistant.card.apply' : 'assistant.card.confirm')}
          </Button>
          <Button size="sm" variant="outline" disabled={locked} data-testid="assistant-card-reject" onClick={() => onDecide('reject')}>
            {t(edit ? 'assistant.card.discard' : 'assistant.card.reject')}
          </Button>
        </div>
      )}
      {c.outcome === 'approved' && !edit && <p className="text-xs text-muted-foreground">{t('assistant.card.approved')}</p>}
      {c.outcome === 'approved' && edit && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span>{t('assistant.card.applied')}</span>
          <Button size="sm" variant="ghost" disabled={locked} data-testid="assistant-card-undo" onClick={onUndo}>
            {c.sending && <Loader2 className="size-3 animate-spin" />}
            {t('assistant.card.undo')}
          </Button>
        </div>
      )}
      {c.outcome === 'undone' && (
        <p className="text-xs text-muted-foreground" data-testid="assistant-card-undone">{t('assistant.card.undone')}</p>
      )}
      {c.outcome === 'rejected' && (
        <p className="text-xs text-muted-foreground" data-testid="assistant-card-rejected">{t('assistant.card.rejected')}</p>
      )}
      {c.outcome === 'failed' && (
        <p className="text-xs text-destructive" data-testid="assistant-card-failed">{t('assistant.card.failed', { msg: c.error_msg ? formatMsg(c.error_msg, locale) : (c.error ?? '') })}</p>
      )}
      {c.task && c.task.kind !== 'edit' && (c.outcome === 'approved' || c.outcome === 'done') && (
        <TaskCard novelId={novelId} task={c.task} chapter={info?.chapter ?? ''} onGoto={onGoto} />
      )}
    </div>
  )
}
