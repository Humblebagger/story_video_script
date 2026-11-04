/** 助手：SSE 解析、极简渲染、位置与跳转存储；面板交互（Task 6 追加）。跑法：npm test */
import { parseSse } from '../src/lib/sse'
import { cancelStep, getWhere, notifyTask, onStepRequest, onTask, requestStep, setWhere, takeStep } from '../src/lib/assistantBridge'
import { composeView, filmView, jobView } from '../src/lib/assistantTask'
import type { AssistantTask, FilmSession, Job } from '../src/types'

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }

// ---------- SSE ----------
{
  const a = parseSse('event: token\ndata: {"text":"你"}\n\nevent: tok')
  must(a.events.length === 1 && a.events[0].event === 'token', '一条完整事件')
  must(a.rest === 'event: tok', '半截留到下次')
  const b = parseSse(a.rest + 'en\ndata: {"text":"好"}\n\nevent: done\ndata: {}\n\n')
  must(b.events.map((e) => e.event).join() === 'token,done' && b.rest === '', '拼上后两条')
  must(parseSse('event: x\ndata: {坏\n\n').events.length === 0, '坏 JSON 跳过')
  must(parseSse('event: token\r\ndata: {"text":"a"}\r\n\r\n').events.length === 1, 'CRLF')
  console.log('✓ SSE 解析')
}

// ---------- 位置与跳转 ----------
{
  setWhere({ chapter_id: 'c1', step: 'review' })
  must(getWhere().chapter_id === 'c1' && getWhere().step === 'review', '位置')
  let hits = 0
  const off = onStepRequest(() => { hits++ })
  requestStep('c2', 'render')
  must(hits === 1, '通知订阅者')
  must(takeStep('c1') === null, '别的章取不到')
  must(takeStep('c2') === 'render' && takeStep('c2') === null, '只取一次')
  requestStep('c3', 'compose')
  cancelStep('c2')
  must(takeStep('c3') === 'compose', '撤别的章不影响')
  requestStep('c3', 'compose')
  cancelStep('c3')
  must(takeStep('c3') === null, '打开没成功：请求撤掉')
  off()
  console.log('✓ 位置与跳转')
}

// ---------- 任务通知 ----------
{
  const got: AssistantTask[] = []
  const off = onTask((t) => got.push(t))
  notifyTask({ kind: 'film', chapter_id: 'c1', version_id: 'v1' })
  off()
  notifyTask({ kind: 'job', chapter_id: 'c1', version_id: 'j1', job_id: 'j1' })
  must(got.length === 1 && got[0].kind === 'film', '订阅者收到、退订后不再收到')
  console.log('✓ 任务通知')
}

// ---------- 任务进度 ----------
{
  const job = (o: Partial<Job>) => ({ id: 'j1', status: 'running', log: [], result: null, quality_report: null, error: null, ...o }) as Job
  const prog = { batches: 2, batch: 1, total_chars: 200, done_chars: 50, attempt: 1, max_attempts: 3, phase: 'generating' as const }
  must(jobView(job({ progress: prog })).state === 'running' && jobView(job({ progress: prog })).pct === 25, '生成中百分比')
  must(jobView(job({ status: 'queued' })).pct === null, '还没进度')
  must(jobView(job({ status: 'succeeded' })).state === 'ok', '完成')
  must(jobView(job({ status: 'completed_with_warnings' })).state === 'ok', '带警告也算完成')
  const f = jobView(job({ status: 'failed', error: '模型超时\n详细' }))
  must(f.state === 'failed' && f.error === '模型超时', '失败取第一行')

  const clip = (state: string) => ({ id: state, state }) as unknown as FilmSession['clips'][number]
  const film = (states: string[], final: FilmSession['final'] = null) => ({ clips: states.map(clip), final }) as FilmSession
  const r = filmView(film(['done', 'running', 'queued', 'planned']))
  must(r.state === 'running' && r.done === 1 && r.total === 4 && r.flying === 2, '出片在跑')
  must(filmView(film(['done', 'done'])).state === 'ok', '出完')
  const ff = filmView(film(['done', 'failed']))
  must(ff.state === 'failed' && ff.failed === 1, '有失败的段')
  const fin = (state: 'queued' | 'running' | 'done' | 'failed', o = {}) =>
    ({ state, files: [], report: null, error: null, detail: null, ...o })
  must(composeView(film([], fin('running', { step: '配音 3 条' }))).state === 'running', '合成中')
  must(composeView(film([], fin('running', { step: '配音 3 条' }))).step === '配音 3 条', '合成步骤')
  must(composeView(film([], fin('done'))).state === 'ok', '合成完')
  must(composeView(film([], fin('failed', { error: 'ffmpeg 出错' }))).error === 'ffmpeg 出错', '合成失败原因')
  must(composeView(film([])).state === 'gone', '没有合成记录')
  console.log('✓ 任务进度')
}

// ---------- 极简渲染 ----------
const { Window } = await import('happy-dom')
const win = new Window({ url: 'http://localhost:5173' })
const g = globalThis as Record<string, unknown>
for (const k of ['window', 'document', 'navigator', 'location', 'HTMLElement', 'Element', 'Node', 'Event',
                 'CustomEvent', 'KeyboardEvent', 'MouseEvent', 'PointerEvent', 'getComputedStyle',
                 'localStorage', 'sessionStorage', 'matchMedia', 'ResizeObserver', 'DOMRect', 'MutationObserver', 'NodeFilter']) {
  Object.defineProperty(g, k, { value: (win as unknown as Record<string, unknown>)[k], writable: true, configurable: true })
}
g.IS_REACT_ACT_ENVIRONMENT = true
g.requestAnimationFrame ??= (cb: (t: number) => void) => setTimeout(() => cb(Date.now()), 16)
g.cancelAnimationFrame ??= (id: number) => clearTimeout(id)
const { act, createElement: h } = await import('react')
const { createRoot } = await import('react-dom/client')
const { MiniMd } = await import('../src/lib/miniMd')
const doc = win.document
const box = doc.createElement('div')
doc.body.appendChild(box)
{
  const root = createRoot(box as unknown as HTMLElement)
  await act(async () => { root.render(h(MiniMd, { text: '结论：**两段**没出\n- SH004\n- SH007\n1. 先出片\n2. 再合成\n<b>x</b>' })) })
  must(box.querySelector('strong')?.textContent === '两段', '加粗')
  must(box.querySelectorAll('ul li').length === 2 && box.querySelectorAll('ol li').length === 2, '两种列表')
  must(!box.querySelector('b') && (box.textContent ?? '').includes('<b>x</b>'), '不解析 HTML')
  await act(async () => { root.unmount() })
  console.log('✓ 极简渲染')
}

// ---------- 面板 ----------
const { I18nProvider } = await import('../src/i18n')
const { TooltipProvider } = await import('../src/components/ui/tooltip')
const { AssistantPanel } = await import('../src/components/assistant/AssistantPanel')
const { setWhere: setW } = await import('../src/lib/assistantBridge')
type Ev = { event: string; data: unknown }

const realFetch = globalThis.fetch
let history: unknown[] = []
let script: Ev[] = []
let hold: Promise<void> | null = null        // 设了就等它 resolve 再推 done（测「回答中」）
let after: Ev[] = []                          // hold 放行之后、done 之前再推的事件
const signals: AbortSignal[] = []
let status = 200
const calls: { method: string; url: string; body?: string }[] = []
globalThis.fetch = (async (url: string, init?: RequestInit) => {
  const method = init?.method ?? 'GET'
  calls.push({ method, url: String(url), body: init?.body as string | undefined })
  if (method === 'GET') return new Response(JSON.stringify({ messages: history }), { status: 200 })
  if (method === 'DELETE') return new Response(JSON.stringify({ ok: true }), { status: 200 })
  if (status !== 200) return new Response(JSON.stringify({ detail: 'x' }), { status })
  const enc = new TextEncoder()
  const signal = init?.signal
  if (signal) signals.push(signal)
  const stream = new ReadableStream({
    async start(ctl) {
      for (const e of script) ctl.enqueue(enc.encode(`event: ${e.event}\ndata: ${JSON.stringify(e.data)}\n\n`))
      if (hold) {
        await new Promise<void>((res, rej) => { hold!.then(res); signal?.addEventListener('abort', () => rej(new DOMException('aborted', 'AbortError'))) })
          .catch((err) => { ctl.error(err) })
        try { for (const e of after) ctl.enqueue(enc.encode(`event: ${e.event}\ndata: ${JSON.stringify(e.data)}\n\n`)) } catch { /* 已出错 */ }
      }
      try { ctl.enqueue(enc.encode('event: done\ndata: {}\n\n')); ctl.close() } catch { /* 已出错 */ }
    },
  })
  return new Response(stream, { status: 200, headers: { 'content-type': 'text/event-stream' } })
}) as typeof fetch

const flush = async () => { for (let i = 0; i < 5; i++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) }) }
const panelBox = doc.createElement('div')
doc.body.appendChild(panelBox)
const gotos: unknown[] = []
const mount = async (novelId = 'n1') => {
  const root = createRoot(panelBox as unknown as HTMLElement)
  await act(async () => {
    root.render(h(I18nProvider, null, h(TooltipProvider, null,
      h(AssistantPanel, { novelId, chapters: [{ id: 'c1', title: '第一章' }], onGoto: (g: unknown) => gotos.push(g) }))))
  })
  await flush()
  return root
}
const $ = (id: string) => panelBox.querySelector(`[data-testid="${id}"]`) as HTMLElement | null
const $$ = (id: string) => [...panelBox.querySelectorAll(`[data-testid="${id}"]`)] as HTMLElement[]
const type = async (v: string) => {
  const ta = $('assistant-input') as HTMLTextAreaElement
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(ta), 'value')!.set!
    setter.call(ta, v)
    ta.dispatchEvent(new win.Event('input', { bubbles: true }) as unknown as Event)
  })
}
const enter = async (composing = false, keyCode = 13) => {
  await act(async () => {
    $('assistant-input')!.dispatchEvent(new win.KeyboardEvent('keydown', { key: 'Enter', bubbles: true, isComposing: composing, keyCode }) as unknown as Event)
  })
  await flush()
}

{
  // 空对话：示例问题与当前位置
  setW({ chapter_id: 'c1', step: 'review' })
  let root = await mount()
  must($$('assistant-example').length === 3, '三个示例问题')
  must(($('assistant-where')?.textContent ?? '').includes('第一章'), '当前位置显示章节')

  // 发送：工具行三种状态、逐字文字、跳转按钮
  script = [
    { event: 'tool_start', data: { id: 't1', name: 'film_status', args: {} } },
    { event: 'tool_end', data: { id: 't1', ok: true, summary: '{}' } },
    { event: 'tool_start', data: { id: 't2', name: 'shots_get', args: { chapter: '九' } } },
    { event: 'tool_end', data: { id: 't2', ok: false, summary: '没有第九章' } },
    { event: 'goto', data: { chapter_id: 'c1', step: 'render' } },
    { event: 'token', data: { text: '还有' } },
    { event: 'token', data: { text: ' **两段**' } },
  ]
  await type('还有哪些没出片？')
  await enter(true)
  await enter(false, 229)
  must(!calls.some((c) => c.method === 'POST'), '输入法组字中 Enter 不发送')
  await enter()
  const post = calls.find((c) => c.method === 'POST')!
  const body = JSON.parse(post.body!)
  must(body.text === '还有哪些没出片？' && body.where.chapter_id === 'c1' && body.where.step === 'review', '带上位置')
  must($$('assistant-tool').map((x) => x.dataset.state).join() === 'ok,err', '工具行状态')
  must($('assistant-bot')?.querySelector('strong')?.textContent === '两段', '逐字拼接并渲染')
  await act(async () => { $('assistant-goto')!.click() })
  must(JSON.stringify(gotos[0]) === JSON.stringify({ chapter_id: 'c1', step: 'render' }), '跳转')
  await act(async () => { $$('assistant-tool')[1].querySelector('button')!.click() })
  must(($$('assistant-tool')[1].textContent ?? '').includes('没有第九章'), '工具行展开')

  // 停止：标「已中断」
  let release!: () => void
  hold = new Promise<void>((r) => { release = r })
  script = [{ event: 'token', data: { text: '正在' } }]
  await type('慢问题')
  await enter()
  must(!!$('assistant-stop'), '回答中显示停止')
  await act(async () => { $('assistant-stop')!.click() })
  await flush()
  must(!!$('assistant-interrupted'), '已中断')
  release(); hold = null

  // 清空：要确认
  await act(async () => { $('assistant-clear')!.click() })
  await flush()
  const confirmBtn = ([...doc.querySelectorAll('[data-testid="confirm-ok"]')] as HTMLElement[])[0]
  must(!!confirmBtn, '清空前弹确认')
  await act(async () => { confirmBtn!.click() })
  await flush()
  must(calls.some((c) => c.method === 'DELETE') && !$('assistant-bot'), '清空后没有消息')
  await act(async () => { root.unmount() })

  // 历史回放 + 429
  history = [{ role: 'user', text: '旧问题' }, { role: 'assistant', text: '旧回答', tools: [], goto: [] }]
  root = await mount()
  must($$('assistant-user')[0]?.textContent === '旧问题', '读历史')
  status = 429
  await type('再问')
  await enter()
  must(!!$('assistant-limit') && ($('assistant-input') as HTMLTextAreaElement).disabled, '429 禁用输入')
  must($$('assistant-user').length === 1, '429 时不留下这条问题')
  await act(async () => { root.unmount() })
  status = 200; history = []
  console.log('✓ 对话面板')

  // 回答中卸载面板（关面板、切到动态）：不中断；重新挂上时接着显示后来流进来的文字
  let go!: () => void
  hold = new Promise<void>((r) => { go = r })
  script = [{ event: 'token', data: { text: '前半' } }]
  after = [{ event: 'token', data: { text: '后半' } }]
  root = await mount('n2')
  await type('长问题')
  await enter()
  must(($('assistant-bot')?.textContent ?? '').includes('前半') && !!$('assistant-stop'), '回答中')
  const sig = signals[signals.length - 1]
  await act(async () => { root.unmount() })
  go(); await flush()
  must(!sig.aborted, '卸载面板不中断请求')
  root = await mount('n2')
  must(($('assistant-bot')?.textContent ?? '') === '前半后半', '重新挂上：接着流进来的文字都在')
  must(!$('assistant-interrupted') && !$('assistant-stop') && !!$('assistant-send'), '回答已正常结束')
  must(calls.filter((c) => c.method === 'GET' && c.url.includes('n2')).length === 1, '重新挂上不重读历史（不覆盖本地对话）')
  await act(async () => { root.unmount() })
  hold = null; after = []

  // 换到别的小说：正在跑的回答中断并丢掉
  const { keepOnlyAssistant, getSession } = await import('../src/lib/assistantSession')
  hold = new Promise<void>(() => {})
  script = [{ event: 'token', data: { text: '慢' } }]
  root = await mount('n3')
  await type('问')
  await enter()
  const sig3 = signals[signals.length - 1]
  await act(async () => { keepOnlyAssistant('n1') })
  await flush()
  must(sig3.aborted && !getSession('n3').msgs.length && !getSession('n2').msgs.length, '换小说中断并丢掉别的会话')
  await act(async () => { root.unmount() })
  hold = null

  // 恢复被限流（429）：卡片退出「发送中」，仍待确认，今日用完
  {
    const { sendAssistant, decideAssistant } = await import('../src/lib/assistantSession')
    const o = { lang: 'zh', where: {}, busyText: 'busy', cutOffText: 'cut' }
    const cardInfo = { id: 'i1', tool_call_id: 'tc1', action: 'compose', chapter_id: 'c1', chapter: 'c', version_id: 'v1',
                       amount: 1, currency: 'cny', detail: {} }
    script = [{ event: 'confirm', data: cardInfo }, { event: 'done', data: {} }]
    await sendAssistant('n9', 'go', o)
    must(getSession('n9').msgs[1].cards?.[0].outcome === 'pending', '种下待确认的卡')
    status = 429
    await decideAssistant('n9', 'tc1', 'approve', o)
    status = 200
    const c9 = getSession('n9').msgs[1].cards![0]
    must(!c9.sending && c9.outcome === 'pending' && getSession('n9').limited && !getSession('n9').busy, '恢复 429 后卡片不再发送中')
  }
  console.log('✓ 面板卸载不中断回答')
}
globalThis.fetch = realFetch

// ---------- 页签与入口 ----------
{
  const { ActivityPanel } = await import('../src/components/shell/ActivityPanel')
  const { AppShell } = await import('../src/components/shell/AppShell')
  const tbox = doc.createElement('div')
  doc.body.appendChild(tbox)
  const q = (sel: string) => tbox.querySelector(sel) as HTMLElement | null
  const tabs: string[] = []
  const panel = (p: Record<string, unknown>) => h(I18nProvider, null, h(TooltipProvider, null,
    h(ActivityPanel, { running: [], done: [], onOpen: () => {}, onClose: () => {}, ...p })))
  const root = createRoot(tbox as unknown as HTMLElement)

  await act(async () => { root.render(panel({ assistant: h('div', { 'data-testid': 'ast' }, '助手内容'), tab: 'activity', onTab: (x: string) => tabs.push(x) })) })
  must(tbox.querySelectorAll('[role="tab"]').length === 2, '传了 assistant 有两个页签')
  must(!q('.activity--wide') && !q('[data-testid="ast"]'), '动态页签不加宽、不渲染助手')
  await act(async () => { q('[data-testid="activity-tab-assistant"]')!.click() })
  must(tabs.join() === 'assistant', '点助手调 onTab')

  // 带一个在跑的任务：动态页签里看得到它，助手页签里不该出现
  const job = { id: 'j1', status: 'running', created_at: null, work_title: '药', chapter: '第一章', chars: 1,
                log_lines: 0, last_log: null, progress: null } as unknown as import('../src/types').JobSummary
  await act(async () => { root.render(panel({ running: [job], assistant: h('div', { 'data-testid': 'ast' }, '助手内容'), tab: 'activity' })) })
  must(!!q('[data-testid="activity-running"]'), '动态页签列出在跑的任务')
  await act(async () => { root.render(panel({ running: [job], assistant: h('div', { 'data-testid': 'ast' }, '助手内容'), tab: 'assistant' })) })
  must(!!q('aside.activity--wide'), '助手页签加宽')
  must(!!q('[data-testid="ast"]') && !q('[data-testid="activity-running"]') && !q('[data-testid="empty-state"]')
       && !tbox.querySelector('.activity__title'), '助手页签只渲染助手内容')
  must(q('[data-testid="activity-tab-assistant"]')!.getAttribute('aria-selected') === 'true', '助手页签选中')

  await act(async () => { root.render(panel({ tab: 'assistant' })) })
  must(tbox.querySelectorAll('[role="tab"]').length === 1 && !q('.activity--wide'), '不传 assistant 只有动态页签')

  let opened = 0
  const shell = (on: boolean) => h(I18nProvider, null, h(AppShell, {
    username: 'amy', isAdmin: false, adminOpen: false, onToggleAdmin: () => {}, onLogout: () => {}, onNewNovel: () => {},
    onOpenLocal: () => {}, service: { down: false }, sidebar: null, viewKey: 'a',
    onOpenAssistant: on ? () => { opened++ } : undefined,
  }, null))
  await act(async () => { root.render(shell(true)) })
  must(!!q('[data-testid="assistant-open"]'), '有入口按钮')
  await act(async () => { q('[data-testid="assistant-open"]')!.click() })
  must(opened === 1, '点入口')
  await act(async () => { root.render(shell(false)) })
  must(!q('[data-testid="assistant-open"]'), '不传没有入口按钮')
  await act(async () => { root.unmount() })
  console.log('✓ 页签与入口')
}

console.log('assistant: ALL PASS')
