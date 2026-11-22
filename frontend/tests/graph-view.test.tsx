/** 节点图的界面回归：切到节点图（没会话时的空状态与打开出片页签）；建会话后每段一张卡、缺图资产与连线；
 *  选中高亮、Esc 只取消选中；封面只取尾帧、选中才取视频；派生自由节点、正文防抖保存；超过确认线在卡片里确认；
 *  设为挂靠段的采用；删除前确认；切回时间轴。桩后端在内存里模拟出片会话。纯计算由 node-graph.test.ts 覆盖。
 *  跑法：npm test
 */
import { readFileSync } from 'node:fs'
import { Window } from 'happy-dom'

const win = new Window({ url: 'http://localhost:5173' })
const g = globalThis as Record<string, unknown>
for (const k of ['window', 'document', 'navigator', 'location', 'HTMLElement',
                 'Element', 'Node', 'Event', 'CustomEvent', 'KeyboardEvent', 'getComputedStyle',
                 'localStorage', 'sessionStorage', 'PointerEvent', 'MouseEvent', 'matchMedia', 'ResizeObserver', 'DOMRect',
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

import type { Film } from '../src/useFilm'
import type { FilmAttempt, FilmClip, FilmFocus, FilmFreeNode, FilmSession, Storyboard } from '../src/types'

const doc: Storyboard = JSON.parse(
  readFileSync('../backend/tests/real_text_yao/output_merged.json', 'utf8'))

/* ---------- 桩后端：内存里的出片会话（含自由节点） ---------- */
const R = '/novels/n1/chapters/c1/versions/v1/render'
const IN_FLIGHT = ['queued', 'running', 'downloading']
let film: FilmSession | null = null
let seq = 0
const calls: string[] = []
/** 模拟浏览器时钟与服务端的偏差（毫秒，本地 − 服务端）；强制取消失败；取消响应是不带选项的降级视图 */
let clockSkew = 0
let cancelRefused: unknown = null
let lenientCancel = false
/** 读取会话一律失败（模拟服务商不可用时普通 GET 也失败） */
let getFails = false
const serverNow = () => new Date(Date.now() - clockSkew).toISOString()
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x))

function recount(s: FilmSession): FilmSession {
  const counts: Record<string, number> = {}
  for (const c of s.clips) counts[c.state] = (counts[c.state] ?? 0) + 1
  const sum = (cs: { estimate_cny: number }[]) => Math.round(cs.reduce((n, c) => n + c.estimate_cny, 0) * 100) / 100
  return {
    ...s, counts,
    remaining_cny: sum(s.clips.filter((c) => (c.state === 'planned' || c.state === 'failed') && !c.uncertain)),
    reserved_cny: sum([...s.clips, ...(s.free ?? [])].filter((c) => IN_FLIGHT.includes(c.state))),
    uncertain_count: s.clips.filter((c) => c.uncertain).length,
  }
}

/** 每集两镜一段，每段 ¥5，都缺 C01 的图 */
function makeSession(): FilmSession {
  const clips: FilmClip[] = []
  for (const ep of doc.episodes) {
    for (let i = 0; i < ep.shots.length; i += 2) {
      clips.push({
        id: `${ep.id}-C${String(clips.length + 1).padStart(2, '0')}`, episode: ep.id,
        shots: ep.shots.slice(i, i + 2).map((s) => s.id), duration: 5, truncated: false,
        prompt: `${ep.id} 第 ${i / 2 + 1} 段的提示词`, refs: [], dropped_refs: [], missing_refs: ['C01'],
        first_frame: null, frame_mode: null, fingerprint: 'fp', estimate_cny: 5, attempts: [], chosen: null,
        mute_native: false, uncertain: false, error: null, state: 'planned',
      })
    }
  }
  return recount({
    tier: 'demo', resolution: '720p', audio_mode: 'tts_all', budget_cny: 100000,
    confirm_over_cny: 20, spent_cny: 0, clips, free: [], free_seq: 0, orphaned: [], counts: {}, remaining_cny: 0,
    reserved_cny: 0, uncertain_count: 0,
    options: { tiers: [{ id: 'demo', label: { code: 'tier.demo', params: {} }, resolutions: ['480p', '720p'], default_resolution: '720p',
                         cny_per_sec: { '480p': 0.5, '720p': 1 }, audio_modes: ['tts_all', 'dialogue_native', 'all_native', 'silent'] }],
               resolutions: ['480p', '720p'],
               cny_per_sec: { '480p': 0.5, '720p': 1 }, max_clip_sec: 10, max_refs: 3, first_frame: true,
               frame_with_refs: false, audio_modes: ['tts_all', 'dialogue_native', 'all_native', 'silent'],
               rate_note: '假厂商：不联网、不花钱', typical_sec: [180, 420] },
  })
}

const clipOf = (id: string) => film!.clips.find((c) => c.id === id)!
const freeOf = (id: string) => film!.free!.find((n) => n.id === id)!
const attempt = (id: string, n: number, cost: number): FilmAttempt => ({
  task_id: `${id}-t${n}`, state: 'succeeded', cost_cny: cost, file: `clips/${id}.t${n}.mp4`,
  last_frame: `clips/${id}.t${n}.last.jpg`, error: null, at: '2026-11-11T03:00:00+00:00', fingerprint: 'fp',
  first_frame_used: null,
})

/** 模拟出片线程跑完一段 */
function finish(id: string) {
  const c = clipOf(id)
  c.attempts.push(attempt(id, c.attempts.length + 1, c.estimate_cny))
  c.chosen = c.attempts.length - 1
  c.state = 'done'
  film = recount(film!)
}

/** 模拟出片线程跑完一个自由节点：挂靠的复制一份进目标段（花费 0、带来源） */
function finishFree(id: string) {
  const n = freeOf(id)
  const a = attempt(id, n.attempts.length + 1, n.estimate_cny)
  n.attempts.push(a)
  n.chosen = n.attempts.length - 1
  n.state = 'done'
  if (n.target) clipOf(n.target).attempts.push({ ...a, free_id: id, cost_cny: 0 })
  film = recount(film!)
}

const ok = (data: unknown) => ({ ok: true, status: 200, json: async () => clone(data) })
const fail = (status: number, detail: unknown) =>
  ({ ok: false, status, statusText: '', text: async () => JSON.stringify({ detail }) })

g.fetch = async (url: string, init?: { method?: string; body?: unknown }) => {
  const path = String(url).replace(/^\/api/, '')
  const method = init?.method ?? 'GET'
  const body = init?.body ? JSON.parse(String(init.body)) : undefined
  if (path === '/render/keyframes') return ok({ keyframes: [] })
  if (path === '/novels/n1/chapters/c1/versions/v1/keyframes') return ok({ shots: [] })
  if (!path.startsWith(R)) throw new Error(`桩后端未实现的路径: ${method} ${path}`)
  const sub = path.slice(R.length)
  if (sub.startsWith('/compose') && method === 'GET') {
    return ok({ lines: 0, tts_chars: 0, tts_cny: 0, missing_voices: [], voices: {}, no_video: [], fingerprint: 'fp',
                final: null, bgm: [], tools: true, music: {}, report: null })
  }
  if (sub === '/voices' && method === 'GET') {
    return ok({ rate_note: '', voices: [], speakers: [], missing: [] })
  }
  calls.push(`${method} ${sub}${body === undefined ? '' : ` ${JSON.stringify(body)}`}`)
  if (sub.startsWith('/files/')) {
    return { ok: true, status: 200,
             blob: async () => new Blob(['x'], { type: sub.endsWith('.mp4') ? 'video/mp4' : 'image/jpeg' }) }
  }
  if (sub === '/session' && method === 'GET') {
    if (getFails) return fail(500, '服务商暂不可用')
    return film ? ok({ ...film, gate: { ok: true, message: null }, server_now: serverNow() }) : fail(404, '还没有出片会话')
  }
  if (sub === '/session' && method === 'POST') {
    film = makeSession()
    return ok(film)
  }
  let m = sub.match(/^\/clips\/([^/]+)\/chosen$/)
  if (m && method === 'PUT') {
    clipOf(decodeURIComponent(m[1])).chosen = body.attempt
    film = recount(film!)
    return ok(film)
  }
  if (sub === '/free' && method === 'POST') {
    seq += 1
    const id = `F${String(seq).padStart(2, '0')}`
    const from = body?.from_clip ? clipOf(body.from_clip) : null
    const n: FilmFreeNode = {
      id, target: from?.id ?? null, target_shots: from?.shots ?? null, target_lost: false,
      prompt: from ? from.prompt : '', refs: from ? [...from.refs] : [], first_frame: null,
      duration: from?.duration ?? 5, estimate_cny: from ? from.estimate_cny : 25, state: 'planned', error: null,
      uncertain: false, attempts: [], chosen: null, created_at: '', over_refs: false,
    }
    film = recount({ ...film!, free: [...(film!.free ?? []), n], free_seq: seq })
    return ok(film)
  }
  m = sub.match(/^\/free\/([^/]+)$/)
  if (m && method === 'PATCH') {
    Object.assign(freeOf(m[1]), body)
    film = recount(film!)
    return ok(film)
  }
  if (m && method === 'DELETE') {
    const fid = m[1]
    film = recount({ ...film!, free: film!.free!.filter((n) => n.id !== fid) })
    return ok(film)
  }
  m = sub.match(/^\/free\/([^/]+)\/run$/)
  if (m && method === 'POST') {
    const n = freeOf(m[1])
    if (n.estimate_cny > film!.confirm_over_cny && body?.expected_cny === undefined) {
      return fail(409, { message: `本次约 ¥${n.estimate_cny.toFixed(2)}，请确认金额后再生成`, expected_cny: n.estimate_cny })
    }
    Object.assign(n, { state: 'queued', queued_at: new Date().toISOString() })
    film = recount(film!)
    return ok(film)
  }
  m = sub.match(/^\/(clips|free)\/([^/]+)\/cancel$/)
  if (m && method === 'POST') {
    const it = m[1] === 'free' ? freeOf(m[2]) : clipOf(decodeURIComponent(m[2]))
    if (cancelRefused) return fail(409, cancelRefused)
    const kind = it.state === 'queued' ? 'free' : 'paid'
    if (body?.expect && body.expect !== kind) return fail(409, { code: 'film.cancel.kind_changed', params: {} })
    const outcome = it.state === 'queued' ? 'dequeued' : 'abandoned'
    if (outcome === 'abandoned') it.attempts[it.attempts.length - 1].state = 'abandoned'
    it.state = it.chosen === null ? 'planned' : 'done'
    film = recount(film!)
    return ok(lenientCancel ? { ...film, options: { ...film!.options, tiers: [], resolutions: [] }, cancel_outcome: outcome }
                            : { ...film, cancel_outcome: outcome })
  }
  throw new Error(`桩后端未实现的路径: ${method} ${path}`)
}

const { act, useState } = await import('react')
const { createRoot } = await import('react-dom/client')
const { StoryboardView } = await import('../src/components/StoryboardView')

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }
const container = win.document.createElement('div')
win.document.body.appendChild(container)
const root = createRoot(container as unknown as HTMLElement)
const settle = async (ms = 50) => {
  await act(async () => { await new Promise((r) => setTimeout(r, ms)) })
}
const has = (s: string) => win.document.body.innerHTML.includes(s)
const button = (text: string) => {
  const b = [...win.document.body.querySelectorAll('button')].find((x) => (x.textContent ?? '').includes(text))
  if (!b) throw new Error(`✗ 找不到按钮「${text}」`)
  return b as unknown as HTMLButtonElement
}
const exact = (text: string) => {
  const b = [...container.querySelectorAll('button')].find((x) => x.textContent === text)
  if (!b) throw new Error(`✗ 找不到按钮「${text}」`)
  return b as unknown as HTMLButtonElement
}
const card = (id: string) => {
  const el = container.querySelector(`[data-node="${id}"]`)
  if (!el) throw new Error(`✗ 节点图上找不到 ${id}`)
  return el as unknown as HTMLElement
}
const inCard = (id: string, text: string) => {
  const b = [...card(id).querySelectorAll('button')].find((x) => (x.textContent ?? '').includes(text))
  if (!b) throw new Error(`✗ ${id} 卡片里找不到按钮「${text}」`)
  return b as unknown as HTMLButtonElement
}
const click = async (el: Element) => {
  await act(async () => {
    el.dispatchEvent(new win.MouseEvent('click', { bubbles: true }) as unknown as Event)
  })
  await settle()
}
const type = async (el: Element, value: string) => {
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(win.HTMLTextAreaElement.prototype, 'value')!.set!
    setter.call(el, value)
    el.dispatchEvent(new win.Event('input', { bubbles: true }) as unknown as Event)
  })
}
const tab = (name: string) =>
  [...container.querySelectorAll('.tlc__tabs button')].find((b) => b.textContent === name)
const refresh = () => click(button('刷新'))

/** 测试用：给画布一个聚焦请求（从任务列表、提示、通知点过来）；focusDone 记画布回报了几次「用完了」 */
let giveFocus: (f: FilmFocus | undefined) => void = () => {}
let focusDone = 0
function Host() {
  const [dirty, set] = useState(false)
  const [focus, setFocus] = useState<FilmFocus | undefined>(undefined)
  giveFocus = setFocus
  return <StoryboardView doc={doc} canSave dirty={dirty} saving={false}
                         version={{ nid: 'n1', cid: 'c1', vid: 'v1' }}
                         onChange={() => set(true)} onSave={() => set(false)}
                         canvasFocus={focus} onCanvasFocusDone={() => { focusDone += 1; setFocus(undefined) }} />
}

// 0. 切到节点图：没会话时空状态，按钮打开出片页签；建会话后每段一张卡、缺图资产与连线
await act(async () => { root.render(<Host />) })
await click(button('时间轴画布'))
await click(exact('节点图'))
must(!!container.querySelector('[data-testid="node-graph"]') && has('先在出片页签选好档位'), '没会话时的空状态')
await click(button('打开出片页签'))
must(tab('出片')?.getAttribute('aria-pressed') === 'true', '打开出片页签')
await click(button('建立出片会话'))
must(container.querySelectorAll('.ngv__node--clip').length === film!.clips.length, '每段一张卡')
must(!!card('asset:C01'), '缺图但被用到的资产也上图')
must(container.querySelectorAll('[data-edge^="missing:"]').length === film!.clips.length, '每段一条缺图连线')
console.log(`0. 节点图 ${film!.clips.length} 段 ✓`)

// 1. 选中高亮：选中段与相连的资产亮，其余变淡；侧栏显示这一段；Esc 只取消选中，不关画布
const first = film!.clips[0].id
const second = film!.clips[1].id
await click(card(first))
must(card(first).classList.contains('is-on') && card('asset:C01').classList.contains('is-lit')
     && card(second).classList.contains('is-dim'), '选中高亮相关节点')
must((container.querySelector('.film__clip')?.textContent ?? '').includes(first), '侧栏显示选中的段')
await act(async () => {
  win.document.body.dispatchEvent(new win.KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }) as unknown as Event)
})
await settle()
must(!!container.querySelector('.tlc') && !container.querySelector('.ngv__node.is-on'), 'Esc 先取消选中，不关画布')
console.log('1. 选中高亮与 Esc ✓')

// 2. 封面只取尾帧；没悬停或选中不取视频；选中才取
finish(first)
await refresh()
must(calls.some((c) => c.startsWith(`GET /files/clips/${first}.t1.last.jpg`)), '封面取尾帧')
must(!!card(first).querySelector('img.ngv__media'), '卡片自己显示封面')
must(!calls.some((c) => c.includes('.mp4')), '没悬停或选中不取视频')
await click(card(first))
must(calls.some((c) => c.startsWith(`GET /files/clips/${first}.t1.mp4`)), '选中才取视频')
console.log('2. 视频按需取 ✓')

// 3. 派生自由节点：挂靠这一段；正文停止输入后保存；点自由卡侧栏显示详情
await click(inCard(first, '派生自由节点'))
must(calls.includes(`POST /free {"from_clip":"${first}"}`) && (card('F01').textContent ?? '').includes(`顶替 ${first}`),
     '派生并挂靠这一段')
await type(card('F01').querySelector('textarea')!, '换个机位重拍')
await settle(900)
must(calls.includes('PATCH /free/F01 {"prompt":"换个机位重拍"}'), '停止输入后保存正文')
await click(card('F01'))
must(!!container.querySelector('[data-testid="free-detail"]'), '侧栏显示自由节点详情')
console.log('3. 派生与保存 ✓')

// 4. 新建独立素材：超过确认线时先在卡片里确认，确认后才发请求
await click(button('新建自由节点'))
await type(card('F02').querySelector('textarea')!, '空镜：河面')
await settle(900)
const n0 = calls.length
await click(inCard('F02', '生成 ¥25.00'))
must((card('F02').textContent ?? '').includes('约 ¥25.00，确认花这笔钱？')
     && !calls.slice(n0).some((c) => c.startsWith('POST /free/F02/run')), '超过确认线先在卡片里确认')
await click(inCard('F02', '确认'))
must(calls.includes('POST /free/F02/run {"expected_cny":25}') && freeOf('F02').state === 'queued', '确认后生成')
console.log('4. 卡片内确认 ✓')

// 5. 挂靠节点出完：设为这一段的采用（走现有采用接口，复制件在段里的下标）
finishFree('F01')
await refresh()
await click(inCard('F01', '设为这一段的采用'))
must(calls.includes(`PUT /clips/${first}/chosen {"attempt":1}`), '用现有采用接口设为采用')
console.log('5. 设为采用 ✓')

// 6. 删除：有结果时先确认
await click(inCard('F01', '删除'))
must((card('F01').textContent ?? '').includes('已下载的视频也会删掉，确定删除？') && !calls.includes('DELETE /free/F01'),
     '有结果时先确认')
await click(inCard('F01', '删除'))
must(calls.includes('DELETE /free/F01') && !container.querySelector('[data-node="F01"]'), '确认后删除')
console.log('6. 删除 ✓')

// 6b. 引用超限的自由节点：生成按钮禁用（正文非空，禁用只能来自 over_refs）
await click(button('新建自由节点'))
freeOf('F03').prompt = '空镜：山'
await refresh()
must(!inCard('F03', '生成').disabled, '正文非空且没超限时可生成')
freeOf('F03').over_refs = true
await refresh()
must(inCard('F03', '生成').disabled, 'over_refs 时生成按钮禁用')
console.log('6b. 引用超限禁生成 ✓')

// 6c. 采用位置不在成功的几次里：不显示 0/n，显示 –/n；采用其中一次后显示 n/total
const other = film!.clips[1].id
clipOf(other).attempts = [attempt(other, 1, 5), attempt(other, 2, 5)]
clipOf(other).chosen = null
await refresh()
const navText = () => card(other).querySelector('.ngv__nav')?.textContent ?? ''
must(navText().includes('–/2') && !navText().includes('0/2'), `没有采用时显示 –/2：${navText()}`)
clipOf(other).chosen = 1
await refresh()
must(navText().includes('2/2'), `采用第二次时显示 2/2：${navText()}`)
must(container.querySelector('[data-testid="node-graph"]')?.getAttribute('role') === 'region'
     && container.querySelector('[data-testid="node-graph"]')?.getAttribute('aria-label') === '画布视图',
     '节点图容器是带名字的 region')
console.log('6c. 采用位置与无障碍 ✓')

// 6d. 在跑的卡片：已等多久 · 通常多久，不带厂商名；还没提交的取消先确认、不花钱
{
  const third = film!.clips[2].id
  const waitText = () => card(third).querySelector('[data-testid="ngv-wait"]')?.textContent ?? ''
  const dialogText = () => win.document.body.querySelector('[data-testid="confirm-dialog"]')?.textContent ?? ''
  const answer = (ok: boolean) =>
    click(win.document.body.querySelector(`[data-testid="${ok ? 'confirm-ok' : 'confirm-cancel'}"]`)!)
  const cancelCalls = () => calls.filter((c) => c.startsWith(`POST /clips/${third}/cancel`)).length
  Object.assign(clipOf(third), { state: 'queued', queued_at: new Date(Date.now() - 65000).toISOString() })
  film = recount(film!)
  await refresh()
  must(/已等 1 分 0\d 秒 · 通常 3–7 分钟/.test(waitText()), `等待一行：${waitText()}`)
  must(!/minimax|seedance|fake|假厂商/i.test(card(third).textContent ?? ''), '卡片上不出现厂商名')
  await click(inCard(third, '取消'))
  must(dialogText().includes(`取消 ${third}？`) && dialogText().includes('现在取消不花钱') && cancelCalls() === 0,
       `还没提交：先确认，说明不花钱：${dialogText()}`)
  await answer(true)
  must(cancelCalls() === 1 && clipOf(third).state === 'planned', '确认后取消')
  must(!card(third).querySelector('[data-testid="ngv-wait"]'), '取消后不再显示等待')

  // 已提交、等得比通常久：换说法；「不等了」的确认框写明可能仍扣费；点「取消」不发请求，确认才发
  Object.assign(clipOf(third), { state: 'running', queued_at: new Date(Date.now() - 500000).toISOString(),
    attempts: [{ ...attempt(third, 1, 0), state: 'running', file: null, last_frame: null }] })
  film = recount(film!)
  await refresh()
  must(waitText().includes('比通常久，仍在处理'), `超过通常上限：${waitText()}`)
  await click(inCard(third, '不等了'))
  must(dialogText().includes('服务商可能仍会生成并扣费'), `已提交：确认框写明可能仍扣费：${dialogText()}`)
  await answer(false)
  must(cancelCalls() === 1 && clipOf(third).state === 'running', '确认框里点取消：不发请求')
  await click(inCard(third, '不等了'))
  await answer(true)
  must(cancelCalls() === 2 && clipOf(third).attempts[0].state === 'abandoned', '确认后不等了')
  const { notice } = await import('../src/lib/notice')
  must(notice.log.some((x) => x.msg.includes('已取消，没有花钱'))
       && notice.log.some((x) => x.msg.includes('已停止等待')), '两种结局各有提示')
  console.log('6d. 等待与取消 ✓')
}

// 6e. 出完的卡片有明显的播放按钮：点开是带控制条、不静音的播放窗口；侧栏选中段也能点开
{
  const player = () => win.document.body.querySelector('[data-testid="clip-player"]')
  const closePlayer = async () => {
    await click(win.document.body.querySelector('[data-testid="clip-player"] [data-slot="dialog-close"]')!)
    await settle(300)
  }
  const playBtn = card(first).querySelector('[data-testid="ngv-play"]')
  must(!!playBtn && (playBtn.textContent ?? '').includes('播放'), '出完的卡片有播放按钮')
  must(!card(film!.clips[2].id).querySelector('[data-testid="ngv-play"]'), '没有结果的卡片没有播放按钮')
  await click(playBtn!)
  const video = player()?.querySelector('video')
  must(!!video && video.hasAttribute('controls') && !video.hasAttribute('muted') && !video.hasAttribute('loop'),
       '播放窗口：有控制条、不静音、不循环')
  must((player()?.textContent ?? '').includes(`${first} · 第 ${clipOf(first).chosen! + 1} 次`), '标题写明哪一段第几次')
  await closePlayer()
  must(!player(), '关掉播放窗口')
  await click(card(first))
  const side = container.querySelector('[data-testid="clip-play"]')
  must(!!side, '侧栏选中段有播放按钮')
  await click(side!)
  must(!!player()?.querySelector('video[controls]'), '侧栏也能点开播放窗口')
  await closePlayer()
  console.log('6e. 播放 ✓')
}

// 6f. 取消种类竞态：确认框开着时状态从「排队」迁到「生成中」，确认带上 expect，服务端 409 后重新读取并以新种类重新确认
{
  const third = film!.clips[2].id
  const dialogText = () => win.document.body.querySelector('[data-testid="confirm-dialog"]')?.textContent ?? ''
  const answer = (ok: boolean) =>
    click(win.document.body.querySelector(`[data-testid="${ok ? 'confirm-ok' : 'confirm-cancel'}"]`)!)
  const sent = () => calls.filter((c) => c.startsWith(`POST /clips/${third}/cancel`))
  Object.assign(clipOf(third), { state: 'queued', queued_at: new Date().toISOString(), attempts: [] })
  film = recount(film!)
  await refresh()
  const n0 = sent().length
  await click(inCard(third, '取消'))
  must(dialogText().includes('现在取消不花钱'), '先是不花钱的确认')
  Object.assign(clipOf(third), { state: 'running',
    attempts: [{ ...attempt(third, 1, 0), state: 'running', file: null, last_frame: null }] })     // 确认框开着时已提交
  film = recount(film!)
  await answer(true)
  must(sent().length === n0 + 1 && sent()[n0].includes('"expect":"free"'), `确认时带上用户确认的种类：${sent()[n0]}`)
  must(clipOf(third).state === 'running' && clipOf(third).attempts[0].state === 'running', '服务端拒绝：什么都没动')
  must(dialogText().includes('服务商可能仍会生成并扣费'), `以新种类重新确认：${dialogText()}`)
  await answer(false)
  must(sent().length === n0 + 1 && clipOf(third).state === 'running', '重新确认里点取消：不再发请求')
  await click(inCard(third, '不等了'))
  await answer(true)
  must(sent()[n0 + 1].includes('"expect":"paid"') && clipOf(third).attempts[0].state === 'abandoned', '重新确认后按新种类执行')
  console.log('6f. 取消种类竞态 ✓')
}

// 6g. 浏览器时钟快或慢 10 分钟：等待时长按服务端时间算
{
  const third = film!.clips[2].id
  const waitText = () => card(third).querySelector('[data-testid="ngv-wait"]')?.textContent ?? ''
  for (const skew of [10 * 60000, -10 * 60000]) {
    clockSkew = skew
    Object.assign(clipOf(third), { state: 'queued', attempts: [], queued_at: new Date(Date.now() - skew - 65000).toISOString() })
    film = recount(film!)
    await refresh()
    must(/已等 1 分 0\d 秒 · 通常 3–7 分钟/.test(waitText()), `客户端偏 ${skew / 60000} 分钟：${waitText()}`)
  }
  clockSkew = 0
  console.log('6g. 时钟偏差 ✓')
}

// 6h. 取消后才出的结果（没有采用）：卡片仍有播放按钮，能打开播放器；封面不是它
{
  const id = film!.clips[3].id
  Object.assign(clipOf(id), { state: 'planned', chosen: null, attempts: [{ ...attempt(id, 1, 5), late: true }] })
  film = recount(film!)
  await refresh()
  const btn = card(id).querySelector('[data-testid="ngv-play"]')
  must(!!btn, '没有采用、只有迟到的成功结果：也有播放按钮')
  await click(btn!)
  const pl = win.document.body.querySelector('[data-testid="clip-player"]')
  must(!!pl?.querySelector('video[controls]') && (pl?.textContent ?? '').includes('取消后才出的结果'), '能打开播放器并标明是迟到结果')
  await click(win.document.body.querySelector('[data-testid="clip-player"] [data-slot="dialog-close"]')!)
  await settle(300)
  console.log('6h. 迟到结果可播 ✓')
}

// 6i. 选中节点时打开播放器：一次 Escape 就关；关闭后焦点回到播放按钮
{
  const id = film!.clips[3].id
  await click(card(id))
  must(card(id).classList.contains('is-on'), '节点已选中')
  const btn = card(id).querySelector('[data-testid="ngv-play"]') as unknown as HTMLElement
  await click(btn)
  const pl = () => win.document.body.querySelector('[data-testid="clip-player"]')
  must(!!pl(), '播放器开着')
  await act(async () => {
    pl()!.dispatchEvent(new win.KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }) as unknown as Event)
  })
  await settle(300)
  must(!pl(), '一次 Escape 关闭播放器')
  must(card(id).classList.contains('is-on'), '这一下没有同时取消节点选中')
  must(win.document.activeElement === (card(id).querySelector('[data-testid="ngv-play"]') as unknown), '关闭后焦点回到播放按钮')
  console.log('6i. 播放器键盘 ✓')
}

// 6j. 取消被拒（409）后刷新成功：错误提示仍在，直到用户关掉
{
  const third = film!.clips[2].id
  Object.assign(clipOf(third), { state: 'running', queued_at: new Date().toISOString(),
    attempts: [{ ...attempt(third, 1, 0), state: 'running', file: null, last_frame: null }] })
  film = recount(film!)
  await refresh()
  cancelRefused = { code: 'film.cancel.finished', params: {} }
  await click(inCard(third, '不等了'))
  await click(win.document.body.querySelector('[data-testid="confirm-ok"]')!)
  await settle(200)
  const err = () => container.querySelector('.ngv__err')?.textContent ?? ''
  must(err().includes('正在取回'), `取消被拒后提示在：${err()}`)
  await refresh()
  await settle(200)
  must(err().includes('正在取回'), '刷新成功后提示仍在')
  await click(container.querySelector('[data-testid="film-error-dismiss"]')!)
  must(err() === '', '用户关闭后消失')
  cancelRefused = null
  console.log('6j. 取消错误保留 ✓')
}

// 6k. 取消成功后不用响应覆盖会话（降级视图缺选项）：重新读取
{
  const third = film!.clips[2].id
  Object.assign(clipOf(third), { state: 'queued', attempts: [] })
  film = recount(film!)
  await refresh()
  lenientCancel = true
  const at = calls.length
  await click(inCard(third, '取消'))
  await click(win.document.body.querySelector('[data-testid="confirm-ok"]')!)
  await settle(200)
  const after = calls.slice(at)
  const i = after.findIndex((c) => c.startsWith(`POST /clips/${third}/cancel`))
  must(i >= 0 && after.slice(i + 1).includes('GET /session'), `取消后重新读取会话：${after.join(' | ')}`)
  // 取消响应是缺当前档位的降级视图；重读成功后必须换回正常视图：档位名、分辨率都在，没有占位
  const { zh } = await import('../src/i18n/zh')
  const sumText = () => container.querySelector('.film__settings summary')?.textContent ?? ''
  must(!!container.querySelector('[data-testid="node-graph"]') && sumText().includes(zh.srv.tier.demo) && sumText().includes('720p')
       && !has(zh.film.panel.tierGone), `重读成功后采用正常视图：${sumText()}`)
  lenientCancel = false
  console.log('6k. 取消后重读 ✓')
}

// 6l. 取消成功但随后读取也失败（服务商不可用）：先按响应里的会话更新界面，不停在取消前；读取错误照实显示
{
  const third = film!.clips[2].id
  for (const c of film!.clips) if (IN_FLIGHT.includes(c.state)) Object.assign(c, { state: 'planned', attempts: [] })
  for (const f of film!.free ?? []) if (IN_FLIGHT.includes(f.state)) Object.assign(f, { state: 'planned', attempts: [] })
  Object.assign(clipOf(third), { state: 'queued', queued_at: new Date().toISOString(), attempts: [] })
  film = recount(film!)
  await refresh()
  await click(tab('出片')!)
  must(!!inCard(third, '取消') && has('有段在排队或生成中'), '前提：在排队、取消入口在、设置因在跑被挡')
  lenientCancel = true
  getFails = true
  await click(inCard(third, '取消'))
  await click(win.document.body.querySelector('[data-testid="confirm-ok"]')!)
  await settle(300)
  getFails = false
  lenientCancel = false
  const el = card(third)
  must(![...el.querySelectorAll('button')].some((b) => b.textContent === '取消'), '取消入口消失')
  must(!has('有段在排队或生成中'), '设置不再因在跑被挡')
  must((container.querySelector('.ngv__err')?.textContent ?? '').includes('服务商暂不可用'), '显示读取错误')
  must((container.querySelector('.film__settings summary')?.textContent ?? '').includes('原档位已不可用'), '读取失败时保留取消响应里的降级视图')
  await settle(100)
  console.log('6l. 取消后读取失败不退回 ✓')
}

// 6f. 聚焦请求：只认本版本的；选中那一段、停在出片页，要播放就打开播放窗口；点名任务号就播那一次；每个请求只执行一次
{
  const player = () => win.document.body.querySelector('[data-testid="clip-player"]')
  const closePlayer = async () => {
    await click(win.document.body.querySelector('[data-testid="clip-player"] [data-slot="dialog-close"]')!)
    await settle(300)
  }
  const give = async (f: FilmFocus) => { await act(async () => { giveFocus(f) }); await settle() }
  const second = film!.clips[1].id
  await click(card(second))
  await give({ vid: 'other', id: first, play: true })
  must(!player() && focusDone === 0, '别的版本的请求：不动，留着等那一版')
  await act(async () => { giveFocus(undefined) })
  await give({ vid: 'v1', id: first, play: false })
  must(!player() && focusDone === 1, '不要播放：只选中')
  must(tab('出片')?.getAttribute('aria-pressed') === 'true'
       && !!container.querySelector('[data-testid="clip-play"]'), '停在出片页，选中的是有结果的那一段')
  const late = { ...attempt(first, 9, 7.5), task_id: 't-late', late: true }
  clipOf(first).attempts.push(late)
  film = recount(film!)
  await refresh()
  must(!!card(first).querySelector('[data-testid="ngv-late"]'), '卡片上提示有取消后才出的结果')
  await give({ vid: 'v1', id: first, play: true, taskId: 't-late' })
  must((player()?.textContent ?? '').includes(`${first} · 第 ${clipOf(first).attempts.length} 次`)
       && (player()?.textContent ?? '').includes('取消后才出的结果') && focusDone === 2,
       `点名任务号：播的是那一次：${player()?.textContent}`)
  await closePlayer()
  await give({ vid: 'v1', id: 'E99-C99', play: true })
  must(!player() && focusDone === 3, '找不到的片段：不打开播放窗口，请求照样用掉')
  clipOf(first).attempts.pop()
  film = recount(film!)
  await refresh()
  console.log('6f. 聚焦请求 ✓')
}

// 6m. 点名了任务号但画布的会话还没有那一次（任务列表先发现、画布自己的轮询还没到）：
//     先重读会话，找到后播那一次；重读后仍没有才降级为只选中，不播别的
{
  const player = () => win.document.body.querySelector('[data-testid="clip-player"]')
  const closePlayer = async () => {
    await click(win.document.body.querySelector('[data-testid="clip-player"] [data-slot="dialog-close"]')!)
    await settle(300)
  }
  const give = async (f: FilmFocus) => { await act(async () => { giveFocus(f) }); await settle(300) }
  await act(async () => { giveFocus(undefined) })
  const before = clipOf(first).attempts.length
  const done0 = focusDone
  clipOf(first).attempts.push({ ...attempt(first, 9, 7.5), task_id: 't-late2', late: true })
  film = recount(film!)      // 只改服务端；画布的会话仍是旧的，没点刷新
  await give({ vid: 'v1', id: first, play: true, taskId: 't-late2' })
  must(!!player() && (player()?.textContent ?? '').includes(`${first} · 第 ${before + 1} 次`)
       && (player()?.textContent ?? '').includes('取消后才出的结果') && focusDone === done0 + 1,
       `会话旧：先重读再播指定的那一次：${player()?.textContent}`)
  await closePlayer()
  await act(async () => { giveFocus(undefined) })
  await give({ vid: 'v1', id: first, play: true, taskId: 't-nope' })
  must(!player() && focusDone === done0 + 2, '重读后仍没有那一次：不播别的，请求用掉')
  clipOf(first).attempts.pop()
  film = recount(film!)
  await refresh()
  console.log('6m. 点名的尝试还没读到：先重读再播 ✓')
}

// 6n. 管理员提示（H4）：片段详情、自由节点详情、两类历史尝试行，分别定位；去掉提示后与普通用户一字不差
{
  const { AdminHintsProvider } = await import('../src/adminHints')
  const { zh } = await import('../src/i18n/zh')
  const HINTS = {
    default_provider: 'minimax', fell_back: false,
    tiers: [{ id: 'demo', provider: 'fake', model: 'fake-1', vendor_label: 'ZZ-Vendor Demo', key_configured: true }],
    tts: { provider: 'zz-tts', key_configured: true },
  }
  const bad = (code: string): FilmAttempt => ({ task_id: `x-${code}`, state: 'failed', cost_cny: 0, file: null, last_frame: null,
    error: '旧', error_msg: { code, params: {} } as FilmAttempt['error_msg'], at: '2026-11-11T03:00:00+00:00', fingerprint: 'fp',
    first_frame_used: null })
  // 当前已成功（采用在前面的成功尝试上）、历史曾失败：失败尝试追加在后面，不动采用下标
  clipOf(first).attempts.push(bad('film.vendor.balance'), bad('film.submit.stale'))
  Object.assign(clipOf(first), { state: 'failed', error: 'c', error_msg: { code: 'film.vendor.balance', params: {} } })
  const f9: FilmFreeNode = { id: 'F09', target: null, target_shots: null, target_lost: false, prompt: 'p', refs: [], first_frame: null,
    duration: 5, estimate_cny: 5, state: 'failed', error: 'f', error_msg: { code: 'film.vendor.balance', params: {} } as FilmFreeNode['error_msg'],
    uncertain: false, attempts: [bad('film.vendor.balance'), bad('film.submit.stale')], chosen: null, created_at: '', over_refs: false }
  film = recount({ ...film!, free: [...(film!.free ?? []), f9] })
  const grab = async (hints: typeof HINTS | null) => {
    await act(async () => { root.render(<AdminHintsProvider value={hints}><Host /></AdminHintsProvider>) })
    await click(button('时间轴画布'))
    await click(exact('节点图'))
    await click(tab('出片')!)
    await refresh()
    await click(card(first))
    const clipBox = container.querySelector('section.film__clip:not([data-testid])')!
    const clipTop = clipBox.querySelector('[data-testid="detail-error"]')?.textContent ?? null
    const clipRows = [...clipBox.querySelectorAll('[data-testid="attempt-error"]')].map((x) => x.textContent ?? '')
    await click(card('F09'))
    const freeBox = container.querySelector('[data-testid="free-detail"]')!
    return { clipText: clipBox.textContent ?? '', clipTop, clipRows, freeText: freeBox.textContent ?? '',
             freeTop: freeBox.querySelector('[data-testid="detail-error"]')?.textContent ?? null,
             freeRows: [...freeBox.querySelectorAll('[data-testid="attempt-error"]')].map((x) => x.textContent ?? '') }
  }
  const P = await grab(null)
  const bal = zh.srv.film.vendor.balance
  must(P.clipRows.filter(Boolean).join('|') === `${bal}|${zh.srv.film.submit.stale}` && P.freeRows.filter(Boolean).join('|') === `${bal}|${zh.srv.film.submit.stale}`,
       `普通用户：历史尝试行有中性原因 ${P.clipRows.join('|')}`)
  must(!P.clipText.includes('ZZ-Vendor') && !P.freeText.includes('ZZ-Vendor'), '普通用户无括号')
  const A = await grab(HINTS)
  const ZZ = '（ZZ-Vendor Demo）'
  must(P.clipTop === bal && P.freeTop === bal, `普通用户：当前错误段落存在且无括号：${P.clipTop}|${P.freeTop}`)
  must(A.clipTop === bal + ZZ, `H4 片段详情当前失败：${A.clipTop}`)
  must(A.freeTop === bal + ZZ, `H4 自由节点详情当前失败：${A.freeTop}`)
  must(A.clipRows.filter(Boolean).join('|') === `${bal}${ZZ}|${zh.srv.film.submit.stale}`, `H4 片段历史尝试行：${A.clipRows.join('|')}`)
  must(A.freeRows.filter(Boolean).join('|') === `${bal}${ZZ}|${zh.srv.film.submit.stale}`, `H4 自由节点历史尝试行：${A.freeRows.join('|')}`)
  must(A.clipText.replaceAll(ZZ, '') === P.clipText && A.freeText.replaceAll(ZZ, '') === P.freeText, '各区域去掉提示后与普通用户一致')
  // 历史失败后重试成功并采用、当前错误已清空（state: done）：历史行仍显示原因，当前错误段落不存在
  const ok: FilmAttempt = { ...bad('x'), task_id: 'x-ok', state: 'succeeded', cost_cny: 5, error: null, error_msg: null }
  Object.assign(clipOf(first), { state: 'done', error: null, error_msg: null })
  Object.assign(freeOf('F09'), { state: 'done', error: null, error_msg: null, attempts: [...freeOf('F09').attempts, ok], chosen: 2 })
  film = recount(film!)
  const P2 = await grab(null)
  const A2 = await grab(HINTS)
  must(P2.clipTop === null && P2.freeTop === null && A2.clipTop === null && A2.freeTop === null, `当前错误已清空：没有当前错误段落 ${P2.clipTop}|${P2.freeTop}|${A2.clipTop}|${A2.freeTop}`)
  must(P2.clipRows.filter(Boolean).join('|') === `${bal}|${zh.srv.film.submit.stale}` && P2.freeRows.filter(Boolean).join('|') === `${bal}|${zh.srv.film.submit.stale}`,
       `普通用户：已成功的节点历史行仍有中性原因 ${P2.clipRows.join('|')} / ${P2.freeRows.join('|')}`)
  must(A2.clipRows.filter(Boolean).join('|') === `${bal}${ZZ}|${zh.srv.film.submit.stale}` && A2.freeRows.filter(Boolean).join('|') === `${bal}${ZZ}|${zh.srv.film.submit.stale}`,
       `管理员：已成功的节点历史行带提示 ${A2.clipRows.join('|')} / ${A2.freeRows.join('|')}`)
  must(!P2.clipText.includes('ZZ-Vendor') && !P2.freeText.includes('ZZ-Vendor'), '普通用户无括号')
  must(A2.clipText.replaceAll(ZZ, '') === P2.clipText && A2.freeText.replaceAll(ZZ, '') === P2.freeText, '已成功：各区域去掉提示后与普通用户一致')
  console.log('6n. 管理员提示（详情与历史尝试） ✓')
}

// 7. 切回时间轴：节点图收起
await click(exact('时间轴'))
must(!container.querySelector('[data-testid="node-graph"]'), '切回时间轴')
console.log('7. 切回时间轴 ✓')

await act(async () => { root.unmount() })
console.log('graph-view integration: PASS')

// ---------- 片段卡的镜头小标签：镜号、景别、运镜；超过 3 个折叠成 +N（NodeGraph 单独渲染） ----------
{
const { NodeGraph } = await import('../src/components/NodeGraph')
const { I18nProvider } = await import('../src/i18n')
const { setCurrentLocale } = await import('../src/i18n/core')

const mk = (n: number, size: string, movement?: string) => ({
  id: `E01-SH00${n}`, duration_sec: 3, shot_size: size, camera: movement ? { movement } : undefined, action: 'a',
  source: { unit_refs: [], derivation: 'explicit' },
})
const tagDoc = { assets: {}, episodes: [{ id: 'E01', shots: [
  mk(1, 'wide', 'static'), mk(2, 'close_up', 'push_in'), mk(3, 'medium'), mk(4, 'full', 'pan'),
  mk(5, 'insert', 'track'), mk(6, 'extreme_close_up', 'follow'), mk(7, 'medium_close', 'handheld'),
] }] } as unknown as Storyboard
const mkClip = (id: string, shots: string[]) => ({
  id, episode: 'E01', shots, duration: 5, truncated: false, prompt: 'p', refs: [],
  dropped_refs: [], missing_refs: [], first_frame: null, frame_mode: null, fingerprint: 'fp', estimate_cny: 5,
  attempts: [], chosen: null, mute_native: false, uncertain: false, error: null, state: 'planned',
})
const session = {
  tier: 'demo', resolution: '720p', audio_mode: 'tts_all', budget_cny: 200,
  confirm_over_cny: 20, spent_cny: 0, free: [], orphaned: [], counts: {}, reserved_cny: 0, uncertain_count: 0,
  remaining_cny: 0,
  clips: [
    mkClip('E01-C1', ['E01-SH001', 'E01-SH002', 'E01-SH003']),
    mkClip('E01-C2', ['E01-SH004', 'E01-SH005', 'E01-SH006', 'E01-SH007', 'E01-SH099']),
    mkClip('E01-C3', []),
  ],
  options: { tiers: [], resolutions: ['720p'], cny_per_sec: {}, max_clip_sec: 10,
             max_refs: 3, audio_modes: ['tts_all'], rate_note: '' },
} as unknown as FilmSession
const film = { session, busy: false, error: null, files: {}, ensure: () => {}, createFree: async () => {} } as unknown as Film

const container = win.document.createElement('div')
win.document.body.appendChild(container)
const root = createRoot(container as unknown as HTMLElement)
const graph = <NodeGraph film={film} doc={tagDoc} styleUrl={null} kfUrls={{}}
                         selected={null} blocked={null} onSelect={() => {}} onOpenAssets={() => {}} onOpenFilm={() => {}} />
const tagsOf = (id: string) => container.querySelector(`[data-node="${id}"] [data-testid="clip-shots"]`)
const texts = (id: string) => [...(tagsOf(id)?.querySelectorAll('.ngv__shot') ?? [])].map((x) => x.textContent)

await act(async () => { root.render(graph) })
must(texts('E01-C1').join('|') === 'SH001 远景·固定|SH002 特写·推|SH003 中景', `逐镜标签：${texts('E01-C1').join('|')}`)
must(!tagsOf('E01-C1')?.querySelector('.ngv__shot--more'), '恰好 3 个不折叠')
must(texts('E01-C2').join('|') === 'SH004 全景·摇|SH005 插入镜·移|SH006 大特写·跟|+2', `超过 3 个折叠：${texts('E01-C2').join('|')}`)
must(tagsOf('E01-C2')?.getAttribute('title')
     === 'SH004 全景·摇\nSH005 插入镜·移\nSH006 大特写·跟\nSH007 中近景·手持\nSH099', '悬停提示列出全部，找不到的镜头只写短镜号')
must(!!container.querySelector('[data-node="E01-C3"]') && !tagsOf('E01-C3'), '没有镜头的段不显示标签行')
const rowsOf = (id: string) => [...(tagsOf(id)?.querySelectorAll('.ngv__shot-row') ?? [])]
must(rowsOf('E01-C1').length === 3 && rowsOf('E01-C1').every((r) => r.querySelectorAll('.ngv__shot').length === 1),
     '三个标签各占一行，一行一个')
{
  const rows = rowsOf('E01-C2')
  must(rows.length === 3, `折叠后最多 3 行：${rows.length}`)
  must(rows.slice(0, 2).every((r) => r.querySelectorAll('.ngv__shot').length === 1), '前两行只有一个标签')
  must(rows[2].querySelectorAll('.ngv__shot').length === 2 && rows[2].lastElementChild?.textContent === '+2'
       && rows[2].firstElementChild?.textContent === 'SH006 大特写·跟', '+N 与第 3 个标签同在第 3 行末尾')
}
{
  const errs: string[] = []
  const orig = console.error
  console.error = (...a: unknown[]) => { errs.push(a.map(String).join(' ')); }
  const dup = { ...session, clips: [mkClip('E01-C1', ['E01-SH001', 'E01-SH001'])] } as unknown as FilmSession
  const dupFilm = { ...film, session: dup } as unknown as Film
  await act(async () => { root.render(<NodeGraph film={dupFilm} doc={tagDoc} styleUrl={null} kfUrls={{}}
    selected={null} blocked={null} onSelect={() => {}} onOpenAssets={() => {}} onOpenFilm={() => {}} />) })
  console.error = orig
  must(texts('E01-C1').join('|') === 'SH001 远景·固定|SH001 远景·固定', `重复镜头渲染两个标签：${texts('E01-C1').join('|')}`)
  must(!errs.some((e) => /same key|unique "key"/i.test(e)), `不报重复 key：${errs.join(';')}`)
  await act(async () => { root.render(graph) })
}
console.log('片段卡镜头标签 ✓')

await act(async () => { root.render(<I18nProvider initial="en">{graph}</I18nProvider>) })
must(texts('E01-C1').join('|') === 'SH001 Wide·Static|SH002 Close-up·Push in|SH003 Medium', `英文标签：${texts('E01-C1').join('|')}`)
await act(async () => { root.render(graph) })
setCurrentLocale('zh')
console.log('片段卡镜头标签（英文） ✓')

// 管理员提示（H3）：片段卡与自由节点卡上，生成服务侧的失败原因后面带档位的厂商字样；没有提示数据时一字不差
{
  const { AdminHintsProvider } = await import('../src/adminHints')
  const { zh } = await import('../src/i18n/zh')
  const HINTS = {
    default_provider: 'minimax', fell_back: false,
    tiers: [{ id: 'demo', provider: 'fake', model: 'fake-1', vendor_label: 'ZZ-Vendor Demo', key_configured: true }],
    tts: { provider: 'zz-tts', key_configured: true },
  }
  const failed = { ...session,
    clips: [{ ...mkClip('E01-C1', ['E01-SH001']), state: 'failed', error: 'x', error_msg: { code: 'film.vendor.balance', params: {} } },
            { ...mkClip('E01-C2', ['E01-SH004']), state: 'failed', error: 'y', error_msg: { code: 'film.submit.stale', params: {} } }],
    free: [{ id: 'F01', prompt: 'p', refs: [], first_frame: null, target: null, duration: 5, estimate_cny: 5, attempts: [],
             chosen: null, state: 'failed', error: 'z', error_msg: { code: 'film.vendor.balance', params: {} } }],
  } as unknown as FilmSession
  const fFilm = { ...film, session: failed } as unknown as Film
  const view = (hints: typeof HINTS | null) => (
    <AdminHintsProvider value={hints}>
      <NodeGraph film={fFilm} doc={tagDoc} styleUrl={null} kfUrls={{}}
                 selected={null} blocked={null} onSelect={() => {}} onOpenAssets={() => {}} onOpenFilm={() => {}} />
    </AdminHintsProvider>)
  const errsOf = () => [...container.querySelectorAll('.ngv__err')].map((e) => e.textContent)
  await act(async () => { root.render(view(null)) })
  const plain = errsOf()
  must(plain.length === 3 && plain.every((x) => !x?.includes('ZZ-Vendor')), '没有提示数据：不带厂商字样')
  await act(async () => { root.render(view(HINTS)) })
  const adm = errsOf()
  must(adm[0] === `${zh.srv.film.vendor.balance}（ZZ-Vendor Demo）` && adm[2] === adm[0], 'H3 片段卡与自由节点卡带提示')
  must(adm[1] === zh.srv.film.submit.stale, '别的失败不带')
  must(adm.map((x) => x?.replaceAll('（ZZ-Vendor Demo）', '')).join('|') === plain.join('|'), '提示只是附加')
  console.log('管理员提示（节点卡） ✓')
  await act(async () => { root.render(graph) })
}
await act(async () => { root.unmount() })
}

// ---------- Esc：没选中时放行给画布关闭，选中后第一下只取消选中（NodeGraph 单独渲染） ----------
{
const { NodeGraph } = await import('../src/components/NodeGraph')

const session = {
  tier: 'demo', resolution: '720p', audio_mode: 'tts_all', budget_cny: 200,
  confirm_over_cny: 20, spent_cny: 0, free: [], orphaned: [], counts: {}, reserved_cny: 0, uncertain_count: 0,
  remaining_cny: 0,
  clips: [{
    id: 'E01-C1', episode: 'E01', shots: ['s1'], duration: 5, truncated: false, prompt: 'p', refs: [],
    dropped_refs: [], missing_refs: [], first_frame: null, frame_mode: null, fingerprint: 'fp', estimate_cny: 5,
    attempts: [], chosen: null, mute_native: false, uncertain: false, error: null, state: 'planned',
  }],
  options: { tiers: [], resolutions: ['720p'], cny_per_sec: {}, max_clip_sec: 10,
             max_refs: 3, audio_modes: ['tts_all'], rate_note: '' },
} as unknown as FilmSession
const film = { session, busy: false, error: null, files: {}, ensure: () => {}, createFree: async () => {} } as unknown as Film

const container = win.document.createElement('div')
win.document.body.appendChild(container)
const root = createRoot(container as unknown as HTMLElement)
await act(async () => {
  root.render(<NodeGraph film={film} doc={{ assets: {} } as unknown as Storyboard} styleUrl={null} kfUrls={{}}
                         selected={null} blocked={null} onSelect={() => {}} onOpenAssets={() => {}} onOpenFilm={() => {}} />)
})

const esc = () => {
  const ev = new win.KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
  win.document.body.dispatchEvent(ev)
  return ev.defaultPrevented
}
const card = container.querySelector('[data-node="E01-C1"]') as unknown as HTMLElement
must(!!card, '有剧本段卡片')

// 只是指针悬停在卡片上、没选中：Esc 要放行（画布才能关）
await act(async () => { card.dispatchEvent(new win.MouseEvent('mouseover', { bubbles: true })) })
await act(async () => { card.dispatchEvent(new win.MouseEvent('mouseenter')) })
must(!esc(), '仅悬停时 Esc 不被吃掉')
console.log('1. 仅悬停时 Esc 放行 ✓')

// 点选后：第一下 Esc 只取消选中并拦住画布
await act(async () => { card.click() })
must(card.className.includes('is-on'), '点选后卡片高亮')
let prevented = false
await act(async () => { prevented = esc() })
must(prevented, '选中时 Esc 被吃掉')
must(!card.className.includes('is-on'), 'Esc 后取消选中')
await act(async () => { card.dispatchEvent(new win.MouseEvent('mouseleave')) })
must(!esc(), '取消选中后再按 Esc 放行')
console.log('2. 选中后 Esc 先取消选中、再放行 ✓')

console.log('\nALL PASS')
}
