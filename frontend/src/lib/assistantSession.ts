/** 助手对话的会话存储（模块级，按小说分开）：消息、回答中、今日已用完、输入草稿，以及正在跑的那条流。
 *  面板只是它的视图：关面板、切页签、Esc、点铃铛都不会中断回答；只有显式停止、换到别的小说、退出登录才中断。 */
import { useSyncExternalStore } from 'react'
import { ApiError, clearAssistant, getAssistant, streamAssistant } from '@/api'
import type { AssistantMsg, AssistantWhere } from '@/types'

export const ASSISTANT_MAX = 2000

export interface AssistantSession {
  msgs: AssistantMsg[]
  busy: boolean
  limited: boolean
  draft: string
}

/** 发送时由界面给出的文字与位置（存储里不碰 i18n） */
export interface SendOpts {
  lang: string
  where: AssistantWhere
  busyText: string
  cutOffText: string
}

const EMPTY: AssistantSession = { msgs: [], busy: false, limited: false, draft: '' }
const sessions = new Map<string, AssistantSession>()
const ctls = new Map<string, AbortController>()
const subs = new Set<() => void>()

const emit = () => subs.forEach((f) => f())
const subscribe = (cb: () => void) => { subs.add(cb); return () => { subs.delete(cb) } }
export const getSession = (nid: string): AssistantSession => sessions.get(nid) ?? EMPTY
const put = (nid: string, fn: (s: AssistantSession) => AssistantSession) => { sessions.set(nid, fn(getSession(nid))); emit() }

export function useAssistantSession(nid: string): AssistantSession {
  return useSyncExternalStore(subscribe, () => getSession(nid), () => getSession(nid))
}

/** 读历史：本地已有消息或正在回答就不读（读回来时本地已经开聊也不覆盖） */
export function loadAssistant(nid: string): void {
  const s = getSession(nid)
  if (s.busy || s.msgs.length) return
  getAssistant(nid).then((r) => {
    const cur = getSession(nid)
    if (!cur.busy && !cur.msgs.length) put(nid, (x) => ({ ...x, msgs: r.messages }))
  }).catch(() => {})
}

export function setDraft(nid: string, draft: string): void {
  put(nid, (s) => ({ ...s, draft }))
}

/** 被停掉时还没有结果的工具调用：标成失败，不再转圈 */
const settleTools = (m: AssistantMsg): AssistantMsg =>
  ({ ...m, tools: (m.tools ?? []).map((x) => (x.ok === null ? { ...x, ok: false } : x)) })

export async function sendAssistant(nid: string, raw: string, o: SendOpts): Promise<void> {
  const q = raw.trim()
  const s0 = getSession(nid)
  if (!q || s0.busy || s0.limited || q.length > ASSISTANT_MAX) return
  const ctl = new AbortController()
  ctls.set(nid, ctl)
  // 换小说、退出登录会把这条流从表里撤掉：之后的事件一律丢弃
  const alive = () => ctls.get(nid) === ctl
  const patchLast = (fn: (m: AssistantMsg) => AssistantMsg) => {
    if (alive()) put(nid, (s) => ({ ...s, msgs: s.msgs.map((m, i) => (i === s.msgs.length - 1 ? fn(m) : m)) }))
  }
  put(nid, (s) => ({ ...s, draft: '', busy: true,
                     msgs: [...s.msgs, { role: 'user', text: q }, { role: 'assistant', text: '', tools: [], goto: [] }] }))
  let ended = false
  let gap = false        // 工具调用之后的下一段文字另起一段
  try {
    await streamAssistant(nid, { text: q, lang: o.lang, where: o.where }, (e) => {
      if (e.event === 'token') {
        const sep = gap
        gap = false
        patchLast((m) => ({ ...m, text: m.text + (sep && m.text ? '\n\n' : '') + e.data.text }))
      } else if (e.event === 'tool_start') {
        gap = true
        patchLast((m) => ({ ...m, tools: [...(m.tools ?? []), { ...e.data, ok: null, summary: '' }] }))
      } else if (e.event === 'tool_end') {
        patchLast((m) => ({ ...m, tools: (m.tools ?? []).map((x) => (x.id === e.data.id ? { ...x, ok: e.data.ok, summary: e.data.summary } : x)) }))
      } else if (e.event === 'goto') patchLast((m) => ({ ...m, goto: [...(m.goto ?? []), e.data] }))
      else if (e.event === 'error') { ended = true; patchLast((m) => ({ ...m, error: e.data.message })) }
      else if (e.event === 'done') ended = true
    }, ctl.signal)
    // 流断了却既没有 done 也没有 error（代理掐断、服务重启）：给报错与重试，不留空泡泡
    if (!ended) patchLast((m) => settleTools({ ...m, error: o.cutOffText }))
  } catch (err) {
    if (ctl.signal.aborted) patchLast((m) => settleTools({ ...m, interrupted: true }))
    else if (err instanceof ApiError && err.status === 429) {
      if (alive()) put(nid, (s) => ({ ...s, limited: true, msgs: s.msgs.slice(0, -2), draft: q }))
    } else if (err instanceof ApiError && err.status === 409) patchLast((m) => ({ ...m, error: o.busyText }))
    else patchLast((m) => settleTools({ ...m, error: err instanceof Error ? err.message : String(err) }))
  } finally {
    if (alive()) {
      ctls.delete(nid)
      put(nid, (s) => ({ ...s, busy: false }))
    }
  }
}

export function retryAssistant(nid: string, o: SendOpts): void {
  const s = getSession(nid)
  const lastUser = [...s.msgs].reverse().find((m) => m.role === 'user')
  if (!lastUser || s.busy) return
  put(nid, (x) => ({ ...x, msgs: x.msgs.slice(0, -2) }))
  void sendAssistant(nid, lastUser.text, o)
}

/** 显式停止 */
export function stopAssistant(nid: string): void {
  ctls.get(nid)?.abort()
}

/** 清空（服务端删存档）；失败时抛出，由界面提示 */
export async function clearAssistantSession(nid: string): Promise<void> {
  await clearAssistant(nid)
  put(nid, (s) => ({ ...s, msgs: [] }))
}

/** 只留这一部小说的会话：别的小说正在跑的回答中断并丢掉（回来时重读历史）。传 null 即全部丢掉（退出登录） */
export function keepOnlyAssistant(nid: string | null): void {
  let changed = false
  for (const [k, ctl] of [...ctls]) {
    if (k !== nid) { ctls.delete(k); ctl.abort() }
  }
  for (const k of [...sessions.keys()]) {
    if (k !== nid) { sessions.delete(k); changed = true }
  }
  if (changed) emit()
}
