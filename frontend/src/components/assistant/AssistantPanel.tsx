/** 助手对话（右侧面板的「助手」页签）：历史、流式回答、工具调用折叠行、跳转按钮、停止、清空、示例问题。
 *  对话状态与正在跑的流在 assistantSession（模块级），面板只是视图：卸载（关面板、切页签）不中断回答。
 *  当前位置读 assistantBridge；跳转交给 onGoto（App 打开章节并切步骤）。 */
import { useEffect, useRef, useState } from 'react'
import { Check, ChevronRight, Loader2, Send, Square, X } from 'lucide-react'
import { toast } from 'sonner'
import { useConfirm } from '@/components/common/ConfirmDialog'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { useI18n } from '@/i18n/core'
import type { MsgKey } from '@/i18n/core'
import { useWhere } from '@/lib/assistantBridge'
import {
  ASSISTANT_MAX as MAX, clearAssistantSession, loadAssistant, retryAssistant, sendAssistant, setDraft, stopAssistant,
  useAssistantSession,
} from '@/lib/assistantSession'
import type { SendOpts } from '@/lib/assistantSession'
import { MiniMd } from '@/lib/miniMd'
import type { AssistantGoto, AssistantTool } from '@/types'

export function AssistantPanel({ novelId, chapters, onGoto }: {
  novelId: string
  chapters: { id: string; title: string }[]
  onGoto: (g: AssistantGoto) => void
}) {
  const { t, locale } = useI18n()
  const where = useWhere()
  const [ask, confirmUi] = useConfirm()
  const { msgs, busy, limited, draft: text } = useAssistantSession(novelId)
  const [open, setOpen] = useState<Record<string, boolean>>({})
  const listRef = useRef<HTMLDivElement>(null)

  useEffect(() => { loadAssistant(novelId) }, [novelId])
  useEffect(() => { listRef.current?.scrollTo({ top: listRef.current.scrollHeight }) }, [msgs])

  const title = (cid?: string) => chapters.find((c) => c.id === cid)?.title ?? ''
  const whereLabel = where.chapter_id
    ? [title(where.chapter_id), where.step ? t(`flow.steps.${where.step}` as MsgKey) : ''].filter(Boolean).join(' · ')
    : t('assistant.whereOverview')

  const opts = (): SendOpts => ({ lang: locale, where, busyText: t('assistant.busy'), cutOffText: t('assistant.cutOff') })
  const setText = (v: string) => setDraft(novelId, v)
  const sendText = (raw: string) => { void sendAssistant(novelId, raw, opts()) }
  const retry = () => retryAssistant(novelId, opts())

  const clear = async () => {
    if (!(await ask({ title: t('assistant.clearTitle'), body: t('assistant.clearBody'), action: t('assistant.clear'), danger: true }))) return
    try {
      await clearAssistantSession(novelId)
    } catch (e) {
      toast.error(t('assistant.clearFailed', { msg: e instanceof Error ? e.message : String(e) }))
    }
  }

  const toolLabel = (x: AssistantTool) => {
    const key = `assistant.tool.${x.name}` as MsgKey
    const s = t(key)
    return s === key ? t('assistant.toolUnknown', { name: x.name }) : s
  }

  return (
    <div className="assistant" data-testid="assistant-panel">
      <div className="flex items-center justify-between">
        <p className="assistant__where" data-testid="assistant-where">{t('assistant.where', { where: whereLabel })}</p>
        {!!msgs.length && (
          <Button variant="ghost" size="sm" disabled={busy} onClick={() => void clear()} data-testid="assistant-clear">
            {t('assistant.clear')}
          </Button>
        )}
      </div>
      <div className="assistant__list" ref={listRef}>
        {!msgs.length && (
          <div className="space-y-2" data-testid="assistant-empty">
            <p className="text-sm text-muted-foreground">{t('assistant.empty')}</p>
            {[t('assistant.example1'), t('assistant.example2'), t('assistant.example3')].map((q) => (
              <Button key={q} variant="outline" size="sm" className="h-auto whitespace-normal text-left"
                      data-testid="assistant-example" onClick={() => sendText(q)}>{q}</Button>
            ))}
          </div>
        )}
        {msgs.map((m, i) => m.role === 'user' ? (
          <div key={i} className="assistant__user" data-testid="assistant-user">{m.text}</div>
        ) : (
          <div key={i} className="assistant__bot" data-testid="assistant-bot">
            {(m.tools ?? []).map((x) => (
              <div key={x.id} className="assistant__tool" data-testid="assistant-tool" data-state={x.ok === null ? 'run' : x.ok ? 'ok' : 'err'}>
                <button type="button" className="inline-flex items-center gap-1" aria-expanded={!!open[x.id]}
                        onClick={() => setOpen((o) => ({ ...o, [x.id]: !o[x.id] }))}>
                  <ChevronRight className={`size-3 transition-transform ${open[x.id] ? 'rotate-90' : ''}`} />
                  {toolLabel(x)}
                  {x.ok === null ? <Loader2 className="size-3 animate-spin" /> : x.ok ? <Check className="size-3" /> : <X className="size-3" />}
                </button>
                {open[x.id] && <pre>{JSON.stringify(x.args)}{x.summary ? `\n${x.summary}` : ''}</pre>}
              </div>
            ))}
            {!!m.text && <MiniMd text={m.text} />}
            {(m.goto ?? []).map((g, j) => (
              <Button key={j} variant="outline" size="sm" className="self-start" data-testid="assistant-goto" onClick={() => onGoto(g)}>
                {t('assistant.goto', { chapter: title(g.chapter_id), step: t(`flow.steps.${g.step}` as MsgKey) })}
              </Button>
            ))}
            {m.interrupted && <p className="text-xs text-muted-foreground" data-testid="assistant-interrupted">{t('assistant.interrupted')}</p>}
            {m.error && (
              <div className="flex items-center gap-2 text-xs text-destructive" data-testid="assistant-error">
                <span>{m.error}</span>
                {i === msgs.length - 1 && !busy && <Button variant="ghost" size="sm" onClick={retry}>{t('assistant.retry')}</Button>}
              </div>
            )}
          </div>
        ))}
        {limited && <p className="text-xs text-muted-foreground" data-testid="assistant-limit">{t('assistant.limit')}</p>}
      </div>
      <form className="assistant__input" onSubmit={(e) => { e.preventDefault(); sendText(text) }}>
        <Textarea value={text} disabled={limited} placeholder={t('assistant.placeholder')} maxLength={MAX}
                  data-testid="assistant-input" aria-label={t('assistant.placeholder')}
                  onChange={(e) => setText(e.target.value)}
                  onKeyDown={(e) => {
                    // Safari 确认输入法候选的回车 isComposing 已是 false，只能靠 keyCode 229 认出来
                    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing && e.keyCode !== 229) { e.preventDefault(); sendText(text) }
                  }} />
        {busy ? (
          <Button type="button" size="icon" variant="outline" aria-label={t('assistant.stop')} data-testid="assistant-stop"
                  onClick={() => stopAssistant(novelId)}>
            <Square className="size-4" />
          </Button>
        ) : (
          <Button type="submit" size="icon" aria-label={t('assistant.send')} data-testid="assistant-send"
                  disabled={!text.trim() || limited}>
            <Send className="size-4" />
          </Button>
        )}
      </form>
      {confirmUi}
    </div>
  )
}
