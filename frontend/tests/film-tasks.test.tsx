/** 个人任务队列：纯计算（哪些在跑、哪些要播报、名字与定位、等待文字、已结束的合并与排序）、可点击的桌面通知、
 *  任务面板里的进行中与已结束（转换、出片片段、成片合成）。
 *  应用里的轮询、铃铛计数与跳转由 routing.test.tsx 覆盖。跑法：npm test */
import { Window } from 'happy-dom'

const win = new Window({ url: 'http://localhost:5173' })
const g = globalThis as Record<string, unknown>
for (const k of ['window', 'document', 'navigator', 'location', 'HTMLElement',
                 'Element', 'Node', 'Event', 'CustomEvent', 'KeyboardEvent', 'getComputedStyle',
                 'localStorage', 'sessionStorage', 'MouseEvent', 'matchMedia', 'ResizeObserver', 'DOMRect',
                 'MutationObserver', 'NodeFilter']) {
  Object.defineProperty(g, k, {
    value: (win as unknown as Record<string, unknown>)[k],
    writable: true, configurable: true,
  })
}
g.IS_REACT_ACT_ENVIRONMENT = true
g.requestAnimationFrame = (cb: (t: number) => void) =>
  setTimeout(() => cb(performance.now()), 16) as unknown as number
g.cancelAnimationFrame = (id: number) => clearTimeout(id)

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import type { FilmTask } from '../src/types'

// 共用词表（backend/server/vendor_words.json）；不 import vendor-words.test.ts：它一导入就会执行
const vw = JSON.parse(readFileSync(resolve(process.cwd(), '../backend/server/vendor_words.json'), 'utf-8')) as
  { substr: string[]; word: string[]; cjk: string[] }
const vwEsc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
const VENDOR_RE = new RegExp([...vw.substr.map(vwEsc), ...vw.cjk.map(vwEsc),
  ...vw.word.map((w) => `(?<![a-z0-9])${vwEsc(w)}(?![a-z0-9])`)].sort((a, b) => b.length - a.length).join('|'), 'i')

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }
const task = (over: Partial<FilmTask> = {}): FilmTask => ({
  id: 'v1:E01-C01', item_id: 'E01-C01', kind: 'clip', novel_id: 'n1', chapter_id: 'c1', version_id: 'v1',
  work_title: '药', chapter: '第一章', state: 'running', elapsed_sec: 245, typical_sec: [180, 420],
  ended_at: null, cost_cny: null, cancel: null, error: null, step: null,
  shot_ids: ['E01-SH001', 'E01-SH002', 'E01-SH003'], ...over,
})

const {
  clockText, diffFilmTasks, endedItems, isLiveTask, jobWhere, lateTaskId, mergeDoneJobs, onFilmPoke, pokeFilmTasks,
  shotRange, taskName, taskWait, taskWhere,
} = await import('../src/filmTasks')

// 1. 名字与等待文字：服务端给的已等秒数加上取回之后过去的时间
{
  must(taskName(task()) === '药 · 第一章 · E01-C01', `名字：${taskName(task())}`)
  must(taskName(task({ work_title: null, chapter: null })) === 'E01-C01', '标题缺失时只写片段')
  must(taskWait(task(), 1000, 1000) === '已等 4 分 05 秒 · 通常 3–7 分钟', `等待：${taskWait(task(), 1000, 1000)}`)
  must(taskWait(task(), 1000, 6000) === '已等 4 分 10 秒 · 通常 3–7 分钟', '取回之后接着走')
  must(taskWait(task({ elapsed_sec: null }), 1000, 3000) === '已等 0 分 02 秒 · 通常 3–7 分钟', '没有已等秒数从 0 算')
  must(isLiveTask(task({ state: 'queued' })) && isLiveTask(task({ state: 'downloading' }))
       && !isLiveTask(task({ state: 'done' })) && !isLiveTask(task({ state: 'late' })), '在跑的三种状态')
  must(lateTaskId(task({ id: 'v1:E01-C01:t9', state: 'late' })) === 't9' && lateTaskId(task()) === undefined,
       '取消后才出结果的那条带着厂商任务号，其它没有')
  let poked = 0
  const off = onFilmPoke(() => { poked += 1 })
  pokeFilmTasks()
  off()
  pokeFilmTasks()
  must(poked === 1, '出片操作之后催一次任务列表；退订后不再收到')
  console.log('1. 名字与等待文字 ✓')
}

// 1b. 定位：小说 › 章节 › 片段 · 镜号范围；名字读不到写「已删除」；合成与转换到章为止
{
  must(taskWhere(task()) === '药 › 第一章 › E01-C01 · SH001–SH003', `片段：${taskWhere(task())}`)
  must(shotRange(['E01-SH004']) === 'SH004' && shotRange([]) === '', '一个镜头不写范围，没有镜头不写')
  must(taskWhere(task({ item_id: 'F01', kind: 'free', shot_ids: [] })) === '药 › 第一章 › F01', '没有镜头的只写编号')
  must(taskWhere(task({ work_title: null, chapter: null })) === '已删除 › 已删除 › E01-C01 · SH001–SH003', '名字读不到：占位')
  const compose = task({ id: 'v1:compose', item_id: 'compose', kind: 'compose', shot_ids: [], typical_sec: null })
  must(taskWhere(compose) === '药 › 第一章 › 成片合成' && taskName(compose) === '药 · 第一章 · 成片合成', '合成到章为止')
  must(taskWait({ ...compose, elapsed_sec: 65 }, 0, 0) === '已等 1 分 05 秒', '合成没有通常时长')
  must(jobWhere({ work_title: '药', chapter: '第一章' }) === '药 › 第一章', '转换到章为止')
  must(jobWhere({ work_title: '药', chapter: '第一章', deleted: true }) === '药 › 第一章（已删除）', '已删除的转换任务留名并标出')
  must(jobWhere({ work_title: null, chapter: null }) === '转换中', '旧任务没有名字')
  console.log('1b. 定位 ✓')
}

// 1c. 已结束的：转换与出片合在一起按结束时间倒序；没有时间的（刚结束、应用自己记下的）排最前；最多 20 条
{
  const dj = (id: string, finished_at?: string) => ({ id, status: 'succeeded' as const, work_title: '药', chapter: id, finished_at })
  const tk = (id: string, ended_at: string) => task({ id, state: 'done', ended_at })
  const got = endedItems([dj('a', '2026-11-21T03:00:00+00:00'), dj('b'), dj('c', '2026-11-21T01:00:00+00:00')],
                         [tk('x', '2026-11-21T04:00:00+00:00'), tk('y', '2026-11-21T02:00:00+00:00')])
  must(got.map((it) => it.job?.id ?? it.task?.id).join() === 'b,x,a,y,c', `顺序：${got.map((it) => it.job?.id ?? it.task?.id)}`)
  const many = Array.from({ length: 30 }, (_, i) => tk(`t${i}`, `2026-11-21T03:${String(i).padStart(2, '0')}:00+00:00`))
  must(endedItems([], many).length === 20 && endedItems([], many)[0].task?.id === 't29', '最多 20 条，留最新的')

  // 转换任务：/jobs 里已结束、带结束时间的并进来（刷新页面后还在）；应用记下的那条补上结束时间与失败原因；在跑的不算
  const sj = (id: string, status: string, o: object = {}) => ({ id, status, created_at: null, work_title: '药', chapter: id,
    chars: 1, log_lines: 0, last_log: null, ...o }) as unknown as import('../src/types').JobSummary
  const merged = mergeDoneJobs([dj('a')], [
    sj('a', 'failed', { finished_at: '2026-11-21T03:00:00+00:00', error_msg: { code: 'x', message: '原因' }, deleted: true }),
    sj('b', 'succeeded', { finished_at: '2026-11-21T05:00:00+00:00' }), sj('c', 'running'), sj('d', 'succeeded')])
  must(merged.map((d) => d.id).join() === 'b,a', `合并：${merged.map((d) => d.id)}`)
  must(merged[1].status === 'failed' && merged[1].finished_at === '2026-11-21T03:00:00+00:00' && merged[1].deleted === true
       && (merged[1].error_msg as { message: string }).message === '原因', '应用记下的那条补全')
  const noon = new Date(2026, 10, 21, 12, 0)
  must(clockText(new Date(2026, 10, 21, 9, 5).toISOString(), noon) === '09:05'
       && clockText(new Date(2026, 10, 20, 23, 40).toISOString(), noon) === '11-20 23:40'
       && clockText(null) === '' && clockText('乱写') === '', '结束时间：当天只写时分，隔天带日期')
  console.log('1c. 已结束的合并与排序 ✓')
}

// 2. 播报：登录后的第一轮只记账；之后新结束的各播一次；取消的不播；同一段再出一次、再结束照常播
{
  const seen = new Set<string>()
  const done = task({ state: 'done', ended_at: '2026-11-21T03:00:00+00:00', elapsed_sec: 280 })
  const first = diffFilmTasks([task({ id: 'v1:E01-C02', item_id: 'E01-C02' }), done], seen, true)
  must(first.live.length === 1 && first.ended.length === 1 && first.announce.length === 0, '第一轮不播报')
  must(diffFilmTasks([done], seen, false).announce.length === 0, '第一轮见过的之后也不播')
  const next = task({ id: 'v1:E01-C02', item_id: 'E01-C02', state: 'failed', ended_at: '2026-11-21T03:05:00+00:00' })
  const second = diffFilmTasks([done, next], seen, false)
  must(second.announce.length === 1 && second.announce[0].id === 'v1:E01-C02', '新结束的播一次')
  must(diffFilmTasks([done, next], seen, false).announce.length === 0, '不重复播')
  const cancelled = task({ id: 'v1:E01-C03', state: 'cancelled', ended_at: '2026-11-21T03:06:00+00:00' })
  must(diffFilmTasks([cancelled], seen, false).announce.length === 0, '自己取消的不播')
  const late = task({ id: 'v1:E01-C03:t9', state: 'late', ended_at: '2026-11-21T03:09:00+00:00', cost_cny: 7.5 })
  must(diffFilmTasks([cancelled, late], seen, false).announce[0]?.state === 'late', '取消后才出结果的要播')
  const again = { ...done, ended_at: '2026-11-21T03:20:00+00:00' }
  must(diffFilmTasks([again], seen, false).announce.length === 1, '同一段再出一次、再结束：照常播')
  console.log('2. 播报 ✓')
}

// 3. 桌面通知：带标签；给了点击回调时，点通知先把窗口拉到前面再执行
{
  const made: { title: string; opts: { body: string; tag: string }; onclick: (() => void) | null; closed: boolean }[] = []
  class FakeNotification {
    static permission = 'granted'
    static requestPermission = async () => 'granted'
    onclick: (() => void) | null = null
    closed = false
    title: string
    opts: { body: string; tag: string }
    constructor(title: string, opts: { body: string; tag: string }) {
      this.title = title
      this.opts = opts
      made.push(this)
    }
    close() { this.closed = true }
  }
  g.Notification = FakeNotification
  ;(win as unknown as Record<string, unknown>).Notification = FakeNotification
  let focused = 0
  ;(win as unknown as { focus: () => void }).focus = () => { focused += 1 }
  const { notify } = await import('../src/notify')
  notify('转换完成', '药 第一章')
  must(made[0].opts.tag === 'storyboard-job' && made[0].onclick === null, '不给回调：老样子')
  let clicked = 0
  notify('片段已生成', '药 · 第一章 · E01-C01', { tag: 'film-v1:E01-C01', onClick: () => { clicked += 1 } })
  must(made[1].opts.tag === 'film-v1:E01-C01' && made[1].opts.body === '药 · 第一章 · E01-C01', '标签与正文')
  made[1].onclick!()
  must(clicked === 1 && focused === 1 && made[1].closed, '点通知：拉到前面、关掉通知、执行回调')
  console.log('3. 可点击的通知 ✓')
}

// 4. 任务面板：进行中（转换、出片、合成）与已结束两区；定位行悬停有全称；可取消的有取消入口；失败带原因；点击带着是否播放回调
{
  const { act } = await import('react')
  const { createRoot } = await import('react-dom/client')
  const { ActivityPanel } = await import('../src/components/shell/ActivityPanel')
  const { I18nProvider } = await import('../src/i18n')
  const container = win.document.createElement('div')
  win.document.body.appendChild(container)
  const root = createRoot(container as unknown as HTMLElement)
  const opened: [string, boolean][] = []
  const cancelled: string[] = []
  const live = [
    task({ cancel: 'paid' }),
    task({ id: 'v1:F01', item_id: 'F01', kind: 'free', state: 'queued', elapsed_sec: 5, cancel: 'free', shot_ids: [] }),
    task({ id: 'v1:compose', item_id: 'compose', kind: 'compose', elapsed_sec: 65, typical_sec: null, shot_ids: [],
           step: { code: 'compose.step.start', params: {}, message: '准备合成' } }),
  ]
  const ended = [
    task({ id: 'v1:E01-C02', item_id: 'E01-C02', state: 'done', ended_at: '2026-11-21T03:00:00+00:00' }),
    task({ id: 'v1:E01-C03', item_id: 'E01-C03', state: 'failed', ended_at: '2026-11-21T02:59:00+00:00',
           error: { message: '下载的文件不能播放' } }),
    task({ id: 'v1:E01-C04:t9', item_id: 'E01-C04', state: 'late', ended_at: '2026-11-21T02:58:00+00:00', cost_cny: 7.5 }),
    task({ id: 'v1:E01-C05', item_id: 'E01-C05', state: 'cancelled', ended_at: '2026-11-21T02:57:00+00:00' }),
    task({ id: 'v1:E01-C06', item_id: 'E01-C06', state: 'failed', ended_at: '2026-11-21T02:56:00+00:00' }),
    task({ id: 'v2:compose', item_id: 'compose', kind: 'compose', state: 'done', typical_sec: null, shot_ids: [],
           ended_at: '2026-11-21T02:55:00+00:00' }),
  ]
  const job = { id: 'j1', status: 'running', created_at: null, work_title: '雾港', chapter: '第二章', chars: 100, log_lines: 1,
    last_log: null, novel_id: 'n2', chapter_id: 'c2',
    progress: { batches: 4, batch: 2, total_chars: 100, done_chars: 40, attempt: 1, max_attempts: 3, phase: 'checking',
                elapsed_sec: 30, eta_sec: 150 } } as unknown as import('../src/types').JobSummary
  const doneJob = { id: 'j0', status: 'failed' as const, work_title: '雾港', chapter: '第一章', deleted: true,
    finished_at: '2026-11-21T02:58:30+00:00', error_msg: { message: '本章还没有原文' } }
  const panel = (film?: { live: FilmTask[]; ended: FilmTask[]; at: number }, withJobs = false) => (
    <I18nProvider initial="zh">
      <ActivityPanel running={withJobs ? [job] : []} done={withJobs ? [doneJob] : []} onOpen={() => {}} onClose={() => {}} film={film}
                     onOpenFilm={(tk, play) => opened.push([tk.id, play])} onCancelFilm={(tk) => cancelled.push(tk.id)} />
    </I18nProvider>
  )
  await act(async () => { root.render(panel()) })
  must((container.textContent ?? '').includes('没有在跑的任务'), '没有任何任务时是空状态')
  await act(async () => { root.render(panel({ live, ended, at: Date.now() }, true)) })
  const text = container.textContent ?? ''
  must(!text.includes('没有在跑的任务'), '有任务就不是空状态')
  const zone = (id: string) => container.querySelector(`[data-testid="${id}"]`)!
  must((zone('queue-running').querySelector('h3 > span')?.textContent ?? '') === '进行中'
       && (zone('queue-ended').querySelector('h3 > span')?.textContent ?? '') === '已结束', '两个区')
  must(zone('queue-running').querySelectorAll('li').length === 4 && zone('queue-ended').querySelectorAll('li').length === 7,
       '进行中 4 条（1 转换 + 3 出片与合成），已结束 7 条（1 转换 + 6 出片与合成）')
  must(container.querySelectorAll('h3').length === 2 && zone('queue-running').contains(container.querySelector('[data-testid="activity-film-running"]')!)
       && zone('queue-ended').contains(container.querySelector('[data-testid="activity-film-done"]')!), '每区一个标题，条目在标题所在的区下')
  must(!!zone('queue-running').querySelector('[data-testid="activity-running"] [role="progressbar"]'), '转换任务带进度条')
  const running = [...container.querySelectorAll('[data-testid="activity-film-running"]')]
  const whereOf = (el: Element) => el.querySelector('[data-testid="activity-where"]')!
  must(whereOf(running[0]).textContent === '药 › 第一章 › E01-C01 · SH001–SH003'
       && whereOf(running[0]).getAttribute('title') === '药 › 第一章 › E01-C01 · SH001–SH003'
       && (whereOf(running[0]).getAttribute('class') ?? '').includes('truncate'), `定位行：可截断，悬停有全称：${whereOf(running[0]).textContent}`)
  must((running[0].textContent ?? '').includes('生成中')
       && /已等 4 分 0\d 秒 · 通常 3–7 分钟/.test(running[0].textContent ?? ''), `在跑的一条：${running[0].textContent}`)
  must((running[1].textContent ?? '').includes('排队中') && whereOf(running[1]).textContent === '药 › 第一章 › F01', '排队中的自由节点')
  must(whereOf(running[2]).textContent === '药 › 第一章 › 成片合成' && (running[2].textContent ?? '').includes('合成中')
       && /已等 1 分 0\d 秒/.test(running[2].textContent ?? '') && !(running[2].textContent ?? '').includes('通常'),
       `合成：步骤与已等，没有通常时长：${running[2].textContent}`)
  const cancelBtns = running.map((li) => li.querySelector('[data-testid="activity-film-cancel"]'))
  must(cancelBtns[0]?.textContent === '不等了' && cancelBtns[1]?.textContent === '取消' && !cancelBtns[2], '可取消的才有取消入口；合成没有')
  must(!VENDOR_RE.test(text) && !/假厂商/.test(text), '面板里不出现厂商名')
  const endedLis = [...zone('queue-ended').querySelectorAll('li')]
  must(endedLis.map((li) => li.getAttribute('data-testid') === 'activity-done' ? 'job' : 'task').join()
       === 'task,task,job,task,task,task,task', '转换与出片按结束时间混排')
  const done = [...container.querySelectorAll('[data-testid="activity-film-done"]')]
  must((done[0].textContent ?? '').includes('已生成') && (done[1].textContent ?? '').includes('生成失败')
       && (done[2].textContent ?? '').includes('取消后仍生成完成') && (done[2].textContent ?? '').includes('¥7.50')
       && (done[3].textContent ?? '').includes('已取消') && (done[5].textContent ?? '').includes('已合成'), '各种结局的标签')
  must(/\d\d:\d\d/.test(done[0].textContent ?? ''), '已结束的带结束时间')
  must(done[1].querySelector('[data-testid="activity-reason"]')?.textContent === '下载的文件不能播放'
       && done[4].querySelector('[data-testid="activity-reason"]')?.textContent === '点开查看原因'
       && !done[0].querySelector('[data-testid="activity-reason"]'), '失败的带原因；原因不能给的写「点开查看原因」')
  const jobLi = container.querySelector('[data-testid="activity-done"]')!
  must(whereOf(jobLi).textContent === '雾港 › 第一章（已删除）'
       && jobLi.querySelector('[data-testid="activity-reason"]')?.textContent === '本章还没有原文', `已结束的转换任务：${jobLi.textContent}`)
  const press = async (el: Element) => {
    await act(async () => { el.dispatchEvent(new win.MouseEvent('click', { bubbles: true }) as unknown as Event) })
  }
  await press(cancelBtns[0]!)
  await press(cancelBtns[1]!)
  must(cancelled.join() === 'v1:E01-C01,v1:F01' && opened.length === 0, '点取消：交给上层，不触发查看')
  await press([...running[0].querySelectorAll('button')].find((b) => b.textContent === '查看')!)
  for (const li of done) await press(li.querySelector('button')!)
  must(JSON.stringify(opened) === JSON.stringify([
    ['v1:E01-C01', false], ['v1:E01-C02', true], ['v1:E01-C03', false], ['v1:E01-C04:t9', true], ['v1:E01-C05', false],
    ['v1:E01-C06', false], ['v2:compose', false],
  ]), `点击回调：${JSON.stringify(opened)}`)
  // 4b. 管理员提示（H5、H7）：生成服务侧的失败带档位的厂商字样，配音服务侧的带配音厂商；没有数据或档位不在表里不带
  {
    const { AdminHintsProvider } = await import('../src/adminHints')
    const { zh } = await import('../src/i18n/zh')
    const HINTS = {
      default_provider: 'minimax', fell_back: false,
      tiers: [{ id: 'demo', provider: 'fake', model: 'fake-1', vendor_label: 'ZZ-Vendor Demo', key_configured: true }],
      tts: { provider: 'zz-tts', key_configured: true },
    }
    const bal = { code: 'film.vendor.balance', params: {}, message: 'x' }
    const failedTasks = [
      task({ id: 'v1:A', item_id: 'A', state: 'failed', ended_at: '2026-11-21T03:00:00+00:00', tier: 'demo', error: bal }),
      task({ id: 'v1:B', item_id: 'B', state: 'failed', ended_at: '2026-11-21T02:59:00+00:00', tier: null, error: bal }),
      task({ id: 'v1:compose', item_id: 'compose', kind: 'compose', state: 'failed', typical_sec: null, shot_ids: [], tier: 'demo',
             ended_at: '2026-11-21T02:58:00+00:00', error: { code: 'tts.vendor.unavailable', params: { status: 503 }, message: 'x' } }),
      task({ id: 'v1:N1', item_id: 'N1', kind: 'compose', state: 'failed', typical_sec: null, shot_ids: [], tier: 'demo',
             ended_at: '2026-11-21T02:56:00+00:00', error: { code: 'compose.lines_failed', params: { items: [
        { code: 'compose.line_failed', params: { id: 'L01', cause: { code: 'tts.vendor.unavailable', params: { status: 503 } } } },
        { code: 'compose.line_failed', params: { id: 'L02', cause: { code: 'tts.vendor.unavailable', params: { status: 503 } } } }] } } }),
      task({ id: 'v1:N2', item_id: 'N2', kind: 'compose', state: 'failed', typical_sec: null, shot_ids: [], tier: 'demo',
             ended_at: '2026-11-21T02:55:00+00:00', error: { code: 'compose.lines_failed', params: { items: [
        { code: 'compose.line_failed', params: { id: 'L01', cause: { code: 'tts.unknown_voice', params: { voice: 'v' } } } }] } } }),
      task({ id: 'v1:D', item_id: 'D', state: 'failed', ended_at: '2026-11-21T02:57:00+00:00', tier: 'demo',
             error: { code: 'film.submit.stale', params: {}, message: 'x' } }),
    ]
    const view = (hints: typeof HINTS | null) => (
      <I18nProvider initial="zh">
        <AdminHintsProvider value={hints}>
          <ActivityPanel running={[]} done={[]} onOpen={() => {}} onClose={() => {}}
                         film={{ live: [], ended: failedTasks, at: Date.now() }} />
        </AdminHintsProvider>
      </I18nProvider>)
    const reasons = () => [...container.querySelectorAll('[data-testid="activity-reason"]')].map((e) => e.textContent)
    await act(async () => { root.render(view(null)) })
    const plain = reasons()
    must(plain.length === 6 && !plain.join('').includes('ZZ-Vendor') && !plain.join('').includes('zz-tts'), '没有提示数据：不带')
    await act(async () => { root.render(view(HINTS)) })
    const adm = reasons()
    must(adm[0] === `${zh.srv.film.vendor.balance}（ZZ-Vendor Demo）`, 'H5 生成服务侧的失败带提示')
    must(adm[1] === zh.srv.film.vendor.balance, '档位为 null 不带')
    must(adm[2] === `${zh.srv.tts.vendor.unavailable.replace('{status}', '503')}（zz-tts）`, 'H7 配音服务侧的失败带配音厂商')
    must(adm[3] === zh.srv.film.submit.stale, '别的失败不带')
    must(adm[4] === plain[4] + '（zz-tts）', `嵌套的配音服务失败带配音厂商：${adm[4]}`)
    must(adm[5] === plain[5], '嵌套的非配音服务原因不带')
  }
  await act(async () => { root.unmount() })
  console.log('4. 任务面板 ✓')
}

console.log('\nALL PASS')
