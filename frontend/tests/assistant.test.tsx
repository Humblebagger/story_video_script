/** 助手：SSE 解析、极简渲染、位置与跳转存储；面板交互（Task 6 追加）。跑法：npm test */
import { parseSse } from '../src/lib/sse'
import { cancelStep, getWhere, notifyTask, onStepRequest, onTask, requestStep, setWhere, takeStep } from '../src/lib/assistantBridge'
import { composeView, filmView, jobView } from '../src/lib/assistantTask'
import { formatMsg } from '../src/i18n/serverMsg'
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
  const reason = { code: 'job.batch_failed', params: { batch: 2, retries: 3 } }
  const failed = { code: 'job.failed_report', params: { reason, report: { t: 'vendor', text: 'FAIL: E01 缺资产 C09' } } }
  const fm = jobView(job({ status: 'failed', error: '旧\n详细', error_msg: failed }))
  must(JSON.stringify(fm.error) === JSON.stringify(reason) && formatMsg(fm.error, 'zh') === '批 2 重试 3 次后仍未通过校验',
       '失败取原因消息对象 ' + JSON.stringify(fm.error))

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
  const stepMsg = { code: 'compose.step.voice', params: { n: 3 } }
  const errMsg = { code: 'compose.crashed', params: {} }
  must(JSON.stringify(composeView(film([], fin('running', { step: '配音 3 条', step_msg: stepMsg }))).step) === JSON.stringify(stepMsg), '合成步骤取消息对象')
  must(JSON.stringify(composeView(film([], fin('failed', { error: 'x', error_msg: errMsg }))).error) === JSON.stringify(errMsg), '合成失败取消息对象')
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
let undoReply: { status: number; body: unknown } = { status: 200, body: { ok: true, message: 'ok', task: { kind: 'edit', chapter_id: 'c1', version_id: 'v1' } } }
let filmState: unknown = { clips: [{ id: 'C1', state: 'running' }, { id: 'C2', state: 'done' }], final: null }
let jobState: unknown = null
let script: Ev[] = []
let hold: Promise<void> | null = null        // 设了就等它 resolve 再推 done（测「回答中」）
let after: Ev[] = []                          // hold 放行之后、done 之前再推的事件
const signals: AbortSignal[] = []
let status = 200
let statusDetail: unknown = 'x'                // 非 200 时 POST 流接口的 detail
let clearReply: { status: number; body: unknown } = { status: 200, body: { ok: true } }
let exportReply: { status: number; body: unknown } | null = null
const calls: { method: string; url: string; body?: string }[] = []
globalThis.fetch = (async (url: string, init?: RequestInit) => {
  const method = init?.method ?? 'GET'
  calls.push({ method, url: String(url), body: init?.body as string | undefined })
  if (method === 'GET') {
    const u = String(url)
    if (u.includes('/render/session')) return new Response(JSON.stringify(filmState), { status: 200 })
    if (u.includes('/jobs/')) return new Response(JSON.stringify(jobState), { status: jobState ? 200 : 404 })
    if (u.includes('/export.zip') && exportReply) return new Response(JSON.stringify(exportReply.body), { status: exportReply.status })
    if (u.includes('/export.zip')) return new Response('zip', { status: 200, headers: { 'content-disposition': 'attachment; filename="p.zip"' } })
    return new Response(JSON.stringify({ messages: history }), { status: 200 })
  }
  if (method === 'DELETE') return new Response(JSON.stringify(clearReply.body), { status: clearReply.status })
  if (method === 'POST' && String(url).endsWith('/assistant/undo')) {
    return new Response(JSON.stringify(undoReply.body), { status: undoReply.status })
  }
  if (status !== 200) return new Response(JSON.stringify({ detail: statusDetail }), { status })
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

{
  // 确认卡：出卡 → 待确认（金额与要点）→ 点确认发 resume、按钮禁用 → action 结果 → 任务卡与通知
  const tasks: unknown[] = []
  const offTask = onTask((t) => tasks.push(t))
  const card = { id: 'i1', tool_call_id: 'f1', action: 'film_run', chapter_id: 'c1', chapter: '第一章',
                 version_id: 'v1', amount: 1.5, currency: 'cny', detail: { clips: 2 } }
  history = []
  let root = await mount('n-card')
  script = [{ event: 'confirm', data: card }]
  await type('第一章出片')
  await enter()
  const box = () => $$('assistant-card').at(-1)!
  must(box().getAttribute('data-outcome') === 'pending', '待确认的卡')
  must((box().textContent ?? '').includes('1.50') && (box().textContent ?? '').includes('2'), '金额与段数')
  must(!!$('assistant-card-approve') && !($('assistant-card-approve') as HTMLButtonElement).disabled, '可以确认')
  must(!$$('assistant-tool').length, '操作工具不出折叠的工具行')

  let release!: () => void
  hold = new Promise<void>((r) => { release = r })
  script = [{ event: 'action', data: { tool_call_id: 'f1', action: 'film_run', outcome: 'approved', card,
                                       task: { kind: 'film', chapter_id: 'c1', version_id: 'v1' } } }]
  after = [{ event: 'token', data: { text: '开始了' } }]
  await act(async () => { $('assistant-card-approve')!.click() })
  await flush()
  const last = calls.filter((c) => c.method === 'POST').at(-1)!
  must(last.url.endsWith('/assistant/resume') && JSON.parse(last.body!).id === 'i1' && JSON.parse(last.body!).decision === 'approve',
       '点确认发 resume，带中断编号')
  must(box().getAttribute('data-outcome') === 'approved', 'action 到了就是已确认')
  release()
  await flush()
  hold = null
  after = []
  must(tasks.length === 1 && (tasks[0] as { kind: string }).kind === 'film', '通知工作台')
  must(!!$('assistant-task') && ($('assistant-task')!.textContent ?? '').includes('1'), '任务卡显示进度')
  must(($$('assistant-bot').at(-1)!.textContent ?? '').includes('开始了'), '恢复后的文字接在同一条回答')
  await act(async () => { root.unmount() })

  // 发送中禁用：再出一张卡，点取消，流还没回来时按钮都禁用
  history = []
  root = await mount('n-card2')
  script = [{ event: 'confirm', data: { ...card, id: 'i2', tool_call_id: 'f2' } }]
  await type('出片')
  await enter()
  hold = new Promise<void>((r) => { release = r })
  script = []
  after = [{ event: 'action', data: { tool_call_id: 'f2', action: 'film_run', outcome: 'rejected', card } }]
  await act(async () => { $('assistant-card-reject')!.click() })
  await flush()
  must(($('assistant-card-approve') as HTMLButtonElement).disabled && ($('assistant-card-reject') as HTMLButtonElement).disabled,
       '请求回来之前两个按钮都禁用')
  release()
  await flush()
  hold = null
  after = []
  must(box().getAttribute('data-outcome') === 'rejected' && !!$('assistant-card-rejected'), '取消后显示已取消')
  await act(async () => { root.unmount() })

  // 有待确认的卡时发新消息：卡本地标成已取消
  history = []
  root = await mount('n-card3')
  script = [{ event: 'confirm', data: { ...card, id: 'i3', tool_call_id: 'f3' } }]
  await type('出片')
  await enter()
  script = [{ event: 'token', data: { text: '好的' } }]
  await type('算了')
  await enter()
  must($$('assistant-card')[0].getAttribute('data-outcome') === 'rejected', '发新消息后待确认的卡变已取消')
  await act(async () => { root.unmount() })

  // 历史里待确认的卡能直接点；没做成的卡显示原因；导出给下载按钮；生成分镜写按用量计费
  history = [
    { role: 'user', text: '做几件事' },
    { role: 'assistant', text: '', error: 'x', tools: [], goto: [], cards: [
      { tool_call_id: 'x1', action: 'compose', outcome: 'failed', error: '还有说话人没选音色' },
      { tool_call_id: 'x2', action: 'export_fcpxml', outcome: 'done',
        card: { ...card, tool_call_id: 'x2', action: 'export_fcpxml', amount: null, currency: null, detail: {} },
        task: { kind: 'export', chapter_id: 'c1', version_id: 'v1' } },
      { tool_call_id: 'x3', action: 'generate_storyboard', outcome: 'approved',
        card: { ...card, tool_call_id: 'x3', action: 'generate_storyboard', amount: null, currency: 'usd', detail: { chars: 300, archived: true } },
        task: { kind: 'job', chapter_id: 'c1', version_id: 'j1', job_id: 'j1' } },
      { tool_call_id: 'x4', action: 'film_run', outcome: 'pending',
        card: { ...card, id: 'i4', tool_call_id: 'x4', amount: 2 } },
    ] },
  ]
  jobState = { id: 'j1', status: 'running', log: [], result: null, quality_report: null, error: null,
               progress: { batches: 2, batch: 1, total_chars: 100, done_chars: 40, attempt: 1, max_attempts: 3, phase: 'generating' } }
  root = await mount('n-card4')
  const cards = $$('assistant-card')
  must(cards.length === 4, '四张卡')
  must(!!$('assistant-card-failed') && ($('assistant-card-failed')!.textContent ?? '').includes('音色'), '没做成的原因')
  must(!!$('assistant-download'), '导出给下载按钮')
  must(cards[2].textContent!.includes('40'), '生成分镜的进度百分比')
  must(!($('assistant-card-approve') as HTMLButtonElement).disabled, '历史里待确认的卡能点')
  must($$('assistant-error').length === 1, '这条回答带报错，报错行要显示')
  must(!$('assistant-error')!.querySelector('button'), '有待确认的卡时不给重试')
  jobState = null
  await act(async () => { root.unmount() })
  offTask()
  console.log('✓ 确认卡与任务卡')
}

{
  // 对比卡：原 → 新、复验警告、应用 / 放弃；应用后撤销；撤销失败给提示；撤销成功通知工作台
  const tasks: unknown[] = []
  const offTask = onTask((t) => tasks.push(t))
  const diffCard = { id: 'i9', tool_call_id: 'e1', action: 'shots_edit', chapter_id: 'c1', chapter: '第一章', version_id: 'v1',
                     amount: null, currency: null, detail: { edits: 2 },
                     diff: [{ target: 'E01-SH001', field: 'action', before: '旧画面', after: '新画面' },
                            { target: 'E01-SH001', field: 'camera.movement', before: 'static', after: 'push_in' }],
                     warnings: [{ code: 'verify.finding', params: { path: 'episodes[0]', detail: { t: 'vendor', text: '时长对不上' } },
                                 message: 'episodes[0]：时长对不上' }, '旧字符串警告'] }
  history = []
  let root = await mount('n-edit')
  script = [{ event: 'confirm', data: diffCard }]
  await type('改第一个镜头')
  await enter()
  const box = () => $$('assistant-card').at(-1)!
  const rows = $$('assistant-diff-row')
  must(rows.length === 2 && rows[0].textContent!.includes('旧画面') && rows[0].textContent!.includes('新画面'), '原 → 新')
  // 嵌套字段（camera.movement）也要显示译名：t() 按点号分层，键里的点换成下划线
  must(rows[1].textContent!.includes('Camera movement') && !rows[1].textContent!.includes('camera.movement'),
       '运镜字段名 ' + rows[1].textContent)
  must(!!$('assistant-card-warnings') && $('assistant-card-warnings')!.textContent!.includes('时长'), '复验警告')
  must($('assistant-card-warnings')!.textContent!.includes('旧字符串警告') && !$('assistant-card-warnings')!.textContent!.includes('[object'), '复验警告：对象与旧字符串都显示')
  must(!$('assistant-card-cost'), '改内容没有金额行')
  must(($('assistant-card-approve')!.textContent ?? '').length > 0 && !$('assistant-card-undo'), '待确认时没有撤销')
  script = [{ event: 'action', data: { tool_call_id: 'e1', action: 'shots_edit', outcome: 'approved', card: diffCard,
                                       task: { kind: 'edit', chapter_id: 'c1', version_id: 'v1' } } }]
  await act(async () => { $('assistant-card-approve')!.click() })
  await flush()
  must(box().getAttribute('data-outcome') === 'approved' && !!$('assistant-card-undo'), '应用后有撤销')
  must(!$('assistant-task'), '改内容不挂任务卡')
  must(tasks.length === 1 && (tasks[0] as { kind: string }).kind === 'edit', '应用后通知工作台')

  undoReply = { status: 409, body: { detail: '镜头 E01-SH001 在这之后又被改过，不能撤销' } }
  await act(async () => { $('assistant-card-undo')!.click() })
  await flush()
  must(box().getAttribute('data-outcome') === 'approved' && !($('assistant-card-undo') as HTMLButtonElement).disabled,
       '撤销失败：卡不变，还能再点')
  must(calls.at(-1)!.url.endsWith('/assistant/undo') && JSON.parse(calls.at(-1)!.body!).tool_call_id === 'e1', '撤销请求带工具调用编号')
  undoReply = { status: 200, body: { ok: true, message: 'ok', task: { kind: 'edit', chapter_id: 'c1', version_id: 'v1' } } }
  await act(async () => { $('assistant-card-undo')!.click() })
  await flush()
  must(box().getAttribute('data-outcome') === 'undone' && !!$('assistant-card-undone') && !$('assistant-card-undo'), '撤销后变已撤销')
  must(tasks.length === 2, '撤销后通知工作台')
  await act(async () => { root.unmount() })

  // 历史里撤销过的卡；放弃的卡
  history = [
    { role: 'user', text: '改' },
    { role: 'assistant', text: '', tools: [], goto: [], cards: [
      { tool_call_id: 'e2', action: 'plot_edit', outcome: 'undone',
        card: { ...diffCard, tool_call_id: 'e2', action: 'plot_edit', warnings: [],
                diff: [{ target: 'all', field: 'outline', before: 'a', after: 'b' }] } },
      { tool_call_id: 'e3', action: 'asset_edit', outcome: 'rejected', card: { ...diffCard, tool_call_id: 'e3', action: 'asset_edit', warnings: [] } },
    ] },
  ]
  root = await mount('n-edit2')
  must($$('assistant-card').map((x) => x.getAttribute('data-outcome')).join() === 'undone,rejected', '历史卡片状态')
  must(!$('assistant-card-undo'), '撤销过、放弃的都没有撤销按钮')
  await act(async () => { root.unmount() })
  offTask()
  console.log('✓ 对比卡与撤销')
}

// ---------- 按代码渲染：随界面语言切换 ----------
{
  const { useI18n, setCurrentLocale } = await import('../src/i18n/core')
  const { Toaster } = await import('../src/components/ui/sonner')
  const { getSession } = await import('../src/lib/assistantSession')
  let setLoc: (l: 'zh' | 'en') => void = () => {}
  const Grab = () => { setLoc = useI18n().setLocale; return null }
  const mountL = async (novelId: string) => {
    const root = createRoot(panelBox as unknown as HTMLElement)
    await act(async () => {
      root.render(h(I18nProvider, { initial: 'zh' }, h(TooltipProvider, null, h(Grab), h(Toaster),
        h(AssistantPanel, { novelId, chapters: [{ id: 'c1', title: '第一章' }], onGoto: () => {} }))))
    })
    await flush()
    return root
  }
  const toEn = async () => { await act(async () => { setLoc('en') }); await flush() }
  const txt = (id: string) => $(id)?.textContent ?? ''
  const hasZh = (s: string) => /[一-鿿]/.test(s)

  // 会话事件：notice 不拼进正文；error 带代码与编号
  history = []
  let root = await mountL('n-i18n')
  script = [
    { event: 'token', data: { text: '好的' } },
    { event: 'tool_start', data: { id: 'a1', name: 'shots_get', args: {} } },
    { event: 'tool_end', data: { id: 'a1', ok: false, summary: '（还没有章节）原文', msg: { code: 'assistant.tool.no_chapters', params: {} } } },
    { event: 'tool_start', data: { id: 'a2', name: 'shots_get', args: {} } },
    { event: 'tool_end', data: { id: 'a2', ok: false, summary: '旧摘要' } },
    { event: 'notice', data: { code: 'assistant.too_many_steps', params: {} } },
    { event: 'error', data: { code: 'assistant.crashed', params: {}, message: '助手出错了，请重试；仍失败请联系管理员', ref: 'K7Q2M9XD' } },
  ]
  await type('问')
  await enter()
  const m0 = getSession('n-i18n').msgs[1]
  must(m0.text === '好的' && m0.notices?.length === 1 && m0.notices[0].code === 'assistant.too_many_steps', 'notice 进 notices，不进正文')
  must(typeof m0.error === 'object' && (m0.error as { ref?: string }).ref === 'K7Q2M9XD', 'error 事件存为对象')
  must(txt('assistant-notice').includes('步骤太多'), '中文提示')
  must(txt('assistant-error').includes('助手出错了') && txt('assistant-error').includes('K7Q2M9XD'), '中文报错带编号 ' + txt('assistant-error'))
  await act(async () => { $$('assistant-tool')[0].querySelector('button')!.click(); $$('assistant-tool')[1].querySelector('button')!.click() })
  must(($$('assistant-tool')[0].textContent ?? '').includes('（还没有章节）') && !($$('assistant-tool')[0].textContent ?? '').includes('原文'), '工具失败按 msg 渲染')
  must(($$('assistant-tool')[1].textContent ?? '').includes('旧摘要'), '没有 msg 显示 summary')
  await toEn()
  must(!hasZh(txt('assistant-error')) && txt('assistant-error').includes('K7Q2M9XD'), '英文报错带编号 ' + txt('assistant-error'))
  must(!hasZh(txt('assistant-notice')) && txt('assistant-notice').length > 5, '英文提示 ' + txt('assistant-notice'))
  must(($$('assistant-tool')[0].textContent ?? '').includes('(no chapters yet)'), '工具失败切英文')
  await act(async () => { root.unmount() })
  setCurrentLocale('zh')

  // 旧后端：error 只有 message
  history = []
  root = await mountL('n-i18n2')
  script = [{ event: 'error', data: { message: '旧文字' } }]
  await type('问')
  await enter()
  must(txt('assistant-error').includes('旧文字'), '旧后端报错显示原文')
  await toEn()
  must(txt('assistant-error').includes('旧文字'), '旧后端报错英文界面仍原文')
  await act(async () => { root.unmount() })
  setCurrentLocale('zh')
  script = []

  // 操作卡：失败原因、复验警告、diff 目标
  const base = { id: 'i1', tool_call_id: 'k', action: 'plot_edit', chapter_id: 'c1', chapter: '第一章', version_id: 'v1',
                 amount: null, currency: null, detail: { edits: 2 } }
  history = [
    { role: 'user', text: '做' },
    { role: 'assistant', text: '', tools: [], goto: [], cards: [
      { tool_call_id: 'f1', action: 'compose', outcome: 'failed', error: '小说不存在', error_msg: { code: 'novel.not_found', params: {} } },
      { tool_call_id: 'f2', action: 'compose', outcome: 'failed', error: '旧存档原文' },
      { tool_call_id: 'p1', action: 'plot_edit', outcome: 'pending',
        card: { ...base, tool_call_id: 'p1',
                warnings: [{ code: 'assistant.edit.nothing', params: {}, message: '没有要改的地方' }],
                diff: [{ target: '全书梗概', field: 'outline', before: 'a', after: 'b' },
                       { target: '第一章 梗概', field: 'synopsis', before: 'c', after: 'd' }] } },
      { tool_call_id: 's1', action: 'shots_edit', outcome: 'pending',
        card: { ...base, tool_call_id: 's1', action: 'shots_edit', warnings: [],
                diff: [{ target: 'E01-SH003', field: 'action', before: 'e', after: 'f' }] } },
    ] },
  ]
  root = await mountL('n-i18n3')
  const fails = $$('assistant-card-failed')
  must(fails[0].textContent!.includes('小说不存在') && fails[1].textContent!.includes('旧存档原文'), '失败卡中文')
  const rowsT = () => $$('assistant-diff-row').map((r) => r.querySelector('p')!.textContent ?? '')
  must(rowsT()[0].startsWith('全书梗概') && rowsT()[1].startsWith('第一章 梗概') && rowsT()[2].startsWith('E01-SH003'), 'diff 目标中文 ' + rowsT().join('|'))
  must(txt('assistant-card-warnings').includes('没有要改的地方'), '警告中文')
  await toEn()
  const fe = $$('assistant-card-failed')
  must(!hasZh(fe[0].textContent ?? '') && fe[0].textContent!.length > 10, '失败卡切英文 ' + fe[0].textContent)
  must(fe[1].textContent!.includes('旧存档原文'), '没有 error_msg 显示原文')
  must(rowsT()[0].startsWith('Book synopsis'), '全书梗概英文 ' + rowsT()[0])
  must(rowsT()[1].startsWith('第一章 synopsis'), '章梗概英文 ' + rowsT()[1])
  must(rowsT()[2].startsWith('E01-SH003'), '镜头目标原样 ' + rowsT()[2])
  must(!txt('assistant-card-warnings').includes('没有要改的地方'), '警告切英文 ' + txt('assistant-card-warnings'))
  await act(async () => { root.unmount() })
  setCurrentLocale('zh')

  // 撤销失败的 toast 按当前语言
  history = [
    { role: 'user', text: '改' },
    { role: 'assistant', text: '', tools: [], goto: [], cards: [
      { tool_call_id: 'u1', action: 'shots_edit', outcome: 'approved',
        card: { ...base, tool_call_id: 'u1', action: 'shots_edit', warnings: [], diff: [] } },
    ] },
  ]
  undoReply = { status: 409, body: { detail: { code: 'assistant.undo.already', params: {}, message: '这次修改已经撤销过了' } } }
  root = await mountL('n-i18n4')
  await toEn()
  await act(async () => { $('assistant-card-undo')!.click() })
  await flush()
  await act(async () => { await new Promise((r) => setTimeout(r, 100)) })
  const body = doc.body.textContent ?? ''
  must(body.includes('This change has already been undone') && !body.includes('撤销过了'), '撤销失败 toast 英文')
  await act(async () => { root.unmount() })
  setCurrentLocale('zh')

  // 清空失败的 toast：英文界面、消息对象 detail，对话不清
  history = [{ role: 'user', text: '旧问题' }, { role: 'assistant', text: '旧回答', tools: [], goto: [] }]
  clearReply = { status: 409, body: { detail: { code: 'assistant.busy_clear', params: {}, message: '助手正在回答，等它说完再清空' } } }
  root = await mountL('n-i18n5')
  await toEn()
  await act(async () => { $('assistant-clear')!.click() })
  await flush()
  await act(async () => { ([...doc.querySelectorAll('[data-testid="confirm-ok"]')] as HTMLElement[])[0].click() })
  await flush()
  await act(async () => { await new Promise((r) => setTimeout(r, 100)) })
  const body2 = doc.body.textContent ?? ''
  must(body2.includes('Could not clear: ') && !body2.includes('等它说完再清空'), '清空失败 toast 英文 ' + body2.slice(-200))
  must($$('assistant-user').length === 1, '清空失败时对话还在')
  clearReply = { status: 200, body: { ok: true } }
  await act(async () => { root.unmount() })
  setCurrentLocale('zh')

  // 发送、恢复的接口失败：会话保留消息对象与编号，按当前语言渲染
  {
    const { sendAssistant, decideAssistant } = await import('../src/lib/assistantSession')
    const o = { lang: 'zh', where: {}, busyText: 'busy', cutOffText: 'cut' }
    const coded = { code: 'assistant.crashed', params: {}, message: '助手出错了，请重试；仍失败请联系管理员', ref: 'R7K2M9XD' }
    history = []
    root = await mountL('n-i18n6')
    status = 500; statusDetail = coded
    script = []
    await type('问')
    await enter()
    const e1 = getSession('n-i18n6').msgs[1].error as { ref?: string; code?: string }
    must(typeof e1 === 'object' && e1.code === 'assistant.crashed' && e1.ref === 'R7K2M9XD', '发送失败保留消息对象与编号')
    must(txt('assistant-error').includes('助手出错了') && txt('assistant-error').includes('R7K2M9XD'), '发送失败中文 ' + txt('assistant-error'))
    await toEn()
    must(!hasZh(txt('assistant-error')) && txt('assistant-error').includes('R7K2M9XD'), '发送失败切英文 ' + txt('assistant-error'))
    await act(async () => { root.unmount() })
    setCurrentLocale('zh')
    status = 200; statusDetail = 'x'

    const cardInfo = { id: 'ri1', tool_call_id: 'rc1', action: 'compose', chapter_id: 'c1', chapter: 'c', version_id: 'v1',
                       amount: 1, currency: 'cny', detail: {} }
    script = [{ event: 'confirm', data: cardInfo }, { event: 'done', data: {} }]
    await sendAssistant('n-i18n7', 'go', o)
    status = 409; statusDetail = { ...coded, ref: 'R9K2M9XD' }
    await decideAssistant('n-i18n7', 'rc1', 'approve', o)
    status = 200; statusDetail = 'x'
    const e2 = getSession('n-i18n7').msgs[1].error as { ref?: string; code?: string }
    must(typeof e2 === 'object' && e2.code === 'assistant.crashed' && e2.ref === 'R9K2M9XD', '恢复 409 保留消息对象与编号')
    root = await mountL('n-i18n7')
    must(txt('assistant-error').includes('助手出错了') && txt('assistant-error').includes('R9K2M9XD'), '恢复失败中文 ' + txt('assistant-error'))
    await toEn()
    must(!hasZh(txt('assistant-error')) && txt('assistant-error').includes('R9K2M9XD'), '恢复失败切英文 ' + txt('assistant-error'))
    await act(async () => { root.unmount() })
    setCurrentLocale('zh')
    script = []
  }

  // 任务卡：失败原因与合成步骤按代码渲染，切语言后重画
  {
    const taskCard = (id: string, action: string, task: unknown) => ({ tool_call_id: id, action, outcome: 'approved',
      card: { ...base, tool_call_id: id, action, detail: {} }, task })
    history = [{ role: 'user', text: '做' }, { role: 'assistant', text: '', tools: [], goto: [], cards: [
      taskCard('t1', 'generate_storyboard', { kind: 'job', chapter_id: 'c1', version_id: 'j1', job_id: 'j1' }),
    ] }]
    jobState = { id: 'j1', status: 'failed', log: [], result: null, quality_report: null, error: '旧\n详细',
                 error_msg: { code: 'job.failed_report', params: { reason: { code: 'job.batch_failed', params: { batch: 2, retries: 3 } },
                                                                   report: { t: 'vendor', text: 'FAIL: E01' } } } }
    root = await mountL('n-i18n8')
    must(txt('assistant-task').includes('批 2 重试 3 次后仍未通过校验') && !txt('assistant-task').includes('FAIL'), '任务卡失败原因中文 ' + txt('assistant-task'))
    await toEn()
    must(!hasZh(txt('assistant-task').replace(/第一章/g, '')) && txt('assistant-task').includes('2') && !txt('assistant-task').includes('FAIL'), '任务卡失败原因英文 ' + txt('assistant-task'))
    await act(async () => { root.unmount() })
    setCurrentLocale('zh')
    jobState = null

    const fin = (o: object) => ({ state: 'running', files: [], report: null, error: null, detail: null, ...o })
    history = [{ role: 'user', text: '做' }, { role: 'assistant', text: '', tools: [], goto: [], cards: [
      taskCard('t2', 'compose', { kind: 'compose', chapter_id: 'c1', version_id: 'v1' }),
    ] }]
    filmState = { clips: [], final: fin({ step: '配音 3 条', step_msg: { code: 'compose.step.voice', params: { n: 3 } } }) }
    root = await mountL('n-i18n9')
    must(txt('assistant-task').includes('配音 3 条'), '合成步骤中文 ' + txt('assistant-task'))
    await toEn()
    must(!hasZh(txt('assistant-task').replace(/第一章/g, '')) && txt('assistant-task').includes('3'), '合成步骤英文 ' + txt('assistant-task'))
    await act(async () => { root.unmount() })
    setCurrentLocale('zh')

    filmState = { clips: [], final: fin({ state: 'failed', error: 'x', error_msg: { code: 'compose.crashed', params: {} } }) }
    root = await mountL('n-i18n10')
    must(txt('assistant-task').includes('合成时出现意外错误'), '合成失败中文 ' + txt('assistant-task'))
    await toEn()
    must(!hasZh(txt('assistant-task').replace(/第一章/g, '')) && txt('assistant-task').includes('Mix failed'), '合成失败英文 ' + txt('assistant-task'))
    await act(async () => { root.unmount() })
    setCurrentLocale('zh')
    filmState = { clips: [{ id: 'C1', state: 'running' }, { id: 'C2', state: 'done' }], final: null }

    // 下载失败 toast
    history = [{ role: 'user', text: '做' }, { role: 'assistant', text: '', tools: [], goto: [], cards: [
      taskCard('t3', 'export_fcpxml', { kind: 'export', chapter_id: 'c1', version_id: 'v1' }),
    ] }]
    exportReply = { status: 404, body: { detail: { code: 'novel.not_found', params: {}, message: '小说不存在' } } }
    root = await mountL('n-i18n11')
    await toEn()
    await act(async () => { $('assistant-download')!.click() })
    await flush()
    await act(async () => { await new Promise((r) => setTimeout(r, 100)) })
    const body3 = doc.body.textContent ?? ''
    must(body3.includes('Download failed: ') && !body3.includes('小说不存在'), '下载失败 toast 英文 ' + body3.slice(-200))
    exportReply = null
    await act(async () => { root.unmount() })
    setCurrentLocale('zh')
  }
  console.log('✓ 助手按代码渲染')
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
