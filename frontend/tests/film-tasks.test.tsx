/** 出片任务列表：纯计算（哪些在跑、哪些要播报、名字、等待文字）、可点击的桌面通知、动态面板里的出片任务。
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

import type { FilmTask } from '../src/types'

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }
const task = (over: Partial<FilmTask> = {}): FilmTask => ({
  id: 'v1:E01-C01', item_id: 'E01-C01', kind: 'clip', novel_id: 'n1', chapter_id: 'c1', version_id: 'v1',
  work_title: '药', chapter: '第一章', state: 'running', elapsed_sec: 245, typical_sec: [180, 420],
  ended_at: null, cost_cny: null, ...over,
})

const { diffFilmTasks, isLiveTask, lateTaskId, onFilmPoke, pokeFilmTasks, taskName, taskWait } = await import('../src/filmTasks')

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

// 4. 动态面板：在跑的出片任务（章节、片段、状态、已等与通常时长）、最近结束的；点击带着是否播放回调
{
  const { act } = await import('react')
  const { createRoot } = await import('react-dom/client')
  const { ActivityPanel } = await import('../src/components/shell/ActivityPanel')
  const { I18nProvider } = await import('../src/i18n')
  const container = win.document.createElement('div')
  win.document.body.appendChild(container)
  const root = createRoot(container as unknown as HTMLElement)
  const opened: [string, boolean][] = []
  const live = [task(), task({ id: 'v1:F01', item_id: 'F01', kind: 'free', state: 'queued', elapsed_sec: 5 })]
  const ended = [
    task({ id: 'v1:E01-C02', item_id: 'E01-C02', state: 'done', ended_at: '2026-11-21T03:00:00+00:00' }),
    task({ id: 'v1:E01-C03', item_id: 'E01-C03', state: 'failed', ended_at: '2026-11-21T02:59:00+00:00' }),
    task({ id: 'v1:E01-C04:t9', item_id: 'E01-C04', state: 'late', ended_at: '2026-11-21T02:58:00+00:00', cost_cny: 7.5 }),
    task({ id: 'v1:E01-C05', item_id: 'E01-C05', state: 'cancelled', ended_at: '2026-11-21T02:57:00+00:00' }),
  ]
  const panel = (film?: { live: FilmTask[]; ended: FilmTask[]; at: number }) => (
    <I18nProvider initial="zh">
      <ActivityPanel running={[]} done={[]} onOpen={() => {}} onClose={() => {}} film={film}
                     onOpenFilm={(tk, play) => opened.push([tk.id, play])} />
    </I18nProvider>
  )
  await act(async () => { root.render(panel()) })
  must((container.textContent ?? '').includes('没有在跑的任务'), '没有任何任务时是空状态')
  await act(async () => { root.render(panel({ live, ended, at: Date.now() })) })
  const text = container.textContent ?? ''
  must(!text.includes('没有在跑的任务'), '有出片任务就不是空状态')
  const running = [...container.querySelectorAll('[data-testid="activity-film-running"]')]
  must(running.length === 2, `在跑两条：${running.length}`)
  must((running[0].textContent ?? '').includes('药 · 第一章 · E01-C01') && (running[0].textContent ?? '').includes('生成中')
       && /已等 4 分 0\d 秒 · 通常 3–7 分钟/.test(running[0].textContent ?? ''), `在跑的一条：${running[0].textContent}`)
  must((running[1].textContent ?? '').includes('排队中'), '排队中的一条')
  must(!/minimax|seedance|fake|假厂商/i.test(text), '面板里不出现厂商名')
  const done = [...container.querySelectorAll('[data-testid="activity-film-done"]')]
  must(done.length === 4, `最近结束四条：${done.length}`)
  must((done[0].textContent ?? '').includes('已生成') && (done[1].textContent ?? '').includes('生成失败')
       && (done[2].textContent ?? '').includes('取消后仍生成完成') && (done[2].textContent ?? '').includes('¥7.50')
       && (done[3].textContent ?? '').includes('已取消'), '各种结局的标签')
  const press = async (el: Element) => {
    await act(async () => { el.dispatchEvent(new win.MouseEvent('click', { bubbles: true }) as unknown as Event) })
  }
  await press(running[0].querySelector('button')!)
  for (const li of done) await press(li.querySelector('button')!)
  must(JSON.stringify(opened) === JSON.stringify([
    ['v1:E01-C01', false], ['v1:E01-C02', true], ['v1:E01-C03', false], ['v1:E01-C04:t9', true], ['v1:E01-C05', false],
  ]), `点击回调：${JSON.stringify(opened)}`)
  await act(async () => { root.unmount() })
  console.log('4. 动态面板里的出片任务 ✓')
}

console.log('\nALL PASS')
