/** 助手对话（右侧面板的「助手」页签）：历史、流式回答、工具调用折叠行、跳转按钮、停止、清空、示例问题。
 *  当前位置读 assistantBridge；跳转交给 onGoto（App 打开章节并切步骤）。 */
import { useEffect, useRef, useState } from 'react'
import { Check, ChevronRight, Loader2, Send, Square, X } from 'lucide-react'
import { ApiError, clearAssistant, getAssistant, streamAssistant } from '@/api'
import { useConfirm } from '@/components/common/ConfirmDialog'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { useI18n } from '@/i18n/core'
import type { MsgKey } from '@/i18n/core'
import { useWhere } from '@/lib/assistantBridge'
import { MiniMd } from '@/lib/miniMd'
import type { AssistantGoto, AssistantMsg, AssistantTool } from '@/types'

const MAX = 2000

export function AssistantPanel({ novelId, chapters, onGoto }: {
  novelId: string
  chapters: { id: string; title: string }[]
  onGoto: (g: AssistantGoto) => void
}) {
  const { t, locale } = useI18n()
  const where = useWhere()
  const [ask, confirmUi] = useConfirm()
  const [msgs, setMsgs] = useState<AssistantMsg[]>([])
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [limited, setLimited] = useState(false)
  const [open, setOpen] = useState<Record<string, boolean>>({})
  const abort = useRef<AbortController | null>(null)
  const listRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let live = true
    setMsgs([])
    getAssistant(novelId).then((r) => { if (live) setMsgs(r.messages) }).catch(() => {})
    return () => { live = false; abort.current?.abort() }
  }, [novelId])
  useEffect(() => { listRef.current?.scrollTo({ top: listRef.current.scrollHeight }) }, [msgs])

  const title = (cid?: string) => chapters.find((c) => c.id === cid)?.title ?? ''
  const whereLabel = where.chapter_id
    ? [title(where.chapter_id), where.step ? t(`flow.steps.${where.step}` as MsgKey) : ''].filter(Boolean).join(' · ')
    : t('assistant.whereOverview')

  /** 改最后一条助手消息 */
  const patchLast = (fn: (m: AssistantMsg) => AssistantMsg) =>
    setMsgs((ms) => ms.map((m, i) => (i === ms.length - 1 ? fn(m) : m)))

  const sendText = async (raw: string) => {
    const q = raw.trim()
    if (!q || busy || limited || q.length > MAX) return
    setText('')
    setBusy(true)
    setMsgs((ms) => [...ms, { role: 'user', text: q }, { role: 'assistant', text: '', tools: [], goto: [] }])
    const ctl = new AbortController()
    abort.current = ctl
    try {
      await streamAssistant(novelId, { text: q, lang: locale, where }, (e) => {
        if (e.event === 'token') patchLast((m) => ({ ...m, text: m.text + e.data.text }))
        else if (e.event === 'tool_start') {
          const tool: AssistantTool = { ...e.data, ok: null, summary: '' }
          patchLast((m) => ({ ...m, tools: [...(m.tools ?? []), tool] }))
        } else if (e.event === 'tool_end') {
          patchLast((m) => ({ ...m, tools: (m.tools ?? []).map((x) => (x.id === e.data.id ? { ...x, ok: e.data.ok, summary: e.data.summary } : x)) }))
        } else if (e.event === 'goto') patchLast((m) => ({ ...m, goto: [...(m.goto ?? []), e.data] }))
        else if (e.event === 'error') patchLast((m) => ({ ...m, error: e.data.message }))
      }, ctl.signal)
    } catch (err) {
      if (ctl.signal.aborted) patchLast((m) => ({ ...m, interrupted: true }))
      else if (err instanceof ApiError && err.status === 429) {
        setLimited(true)
        setMsgs((ms) => ms.slice(0, -2))
        setText(q)
      } else if (err instanceof ApiError && err.status === 409) patchLast((m) => ({ ...m, error: t('assistant.busy') }))
      else patchLast((m) => ({ ...m, error: err instanceof Error ? err.message : String(err) }))
    } finally {
      setBusy(false)
      abort.current = null
    }
  }

  const retry = () => {
    const lastUser = [...msgs].reverse().find((m) => m.role === 'user')
    if (!lastUser) return
    setMsgs((ms) => ms.slice(0, -2))
    void sendText(lastUser.text)
  }

  const clear = async () => {
    if (!(await ask({ title: t('assistant.clearTitle'), body: t('assistant.clearBody'), action: t('assistant.clear'), danger: true }))) return
    await clearAssistant(novelId)
    setMsgs([])
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
                      data-testid="assistant-example" onClick={() => void sendText(q)}>{q}</Button>
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
      <form className="assistant__input" onSubmit={(e) => { e.preventDefault(); void sendText(text) }}>
        <Textarea value={text} disabled={limited} placeholder={t('assistant.placeholder')} maxLength={MAX}
                  data-testid="assistant-input" aria-label={t('assistant.placeholder')}
                  onChange={(e) => setText(e.target.value)}
                  onKeyDown={(e) => {
                    // Safari 确认输入法候选的回车 isComposing 已是 false，只能靠 keyCode 229 认出来
                    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing && e.keyCode !== 229) { e.preventDefault(); void sendText(text) }
                  }} />
        {busy ? (
          <Button type="button" size="icon" variant="outline" aria-label={t('assistant.stop')} data-testid="assistant-stop"
                  onClick={() => abort.current?.abort()}>
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
