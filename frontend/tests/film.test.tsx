/** 画布出片的界面回归：没有版本不出现出片；建会话（不花钱）后出现「成片」泳道；先试一段；
 *  批量先确认、服务端金额变了再确认；单段超过确认线先确认；采用与原声静音；待核对标记；
 *  未保存与验证门拦截；播成片。桩后端在内存里模拟出片会话（出片线程的推进由测试直接改状态）。
 *  纯计算由 film-lane.test.ts 覆盖。跑法：npm test
 */
import { readFileSync } from 'node:fs'
import { Window } from 'happy-dom'

const win = new Window({ url: 'http://localhost:5173' })
const g = globalThis as Record<string, unknown>
for (const k of ['window', 'document', 'navigator', 'location', 'HTMLElement',
                 'Element', 'Node', 'Event', 'CustomEvent', 'KeyboardEvent', 'getComputedStyle',
                 'localStorage', 'sessionStorage']) {
  Object.defineProperty(g, k, {
    value: (win as unknown as Record<string, unknown>)[k],
    writable: true, configurable: true,
  })
}
g.IS_REACT_ACT_ENVIRONMENT = true
g.requestAnimationFrame = (cb: (t: number) => void) =>
  setTimeout(() => cb(performance.now()), 16) as unknown as number
g.cancelAnimationFrame = (id: number) => clearTimeout(id)

import type { FilmAttempt, FilmClip, FilmSession, Storyboard } from '../src/types'

const doc: Storyboard = JSON.parse(
  readFileSync('../backend/tests/real_text_yao/output_merged.json', 'utf8'))

/* ---------- 桩后端：内存里的出片会话 ---------- */
const R = '/novels/n1/chapters/c1/versions/v1/render'
const GATE = '分镜未通过独立验证，禁止进入付费渲染'
const IN_FLIGHT = ['queued', 'running', 'downloading']
let film: FilmSession | null = null
/** 每次出片请求记一行：`方法 子路径 请求体` */
const calls: string[] = []
/** 下一次花钱请求先回 409（模拟服务端重算的金额变了） */
let nextConflict: number | null = null
let gateFail = false
/** 下一次读取会话抛网络错误（只一次） */
let failNextGet = false
/** 记下长间隔（轮询）定时器，看出错后有没有重新排上 */
const pollTimers: number[] = []
const realSetTimeout = globalThis.setTimeout
g.setTimeout = ((fn: () => void, ms?: number, ...a: unknown[]) => {
  if ((ms ?? 0) >= 5000) pollTimers.push(ms!)
  return (realSetTimeout as (...x: unknown[]) => unknown)(fn, ms, ...a)
}) as unknown
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x))

function recount(s: FilmSession): FilmSession {
  const counts: Record<string, number> = {}
  for (const c of s.clips) counts[c.state] = (counts[c.state] ?? 0) + 1
  const sum = (cs: FilmClip[]) => Math.round(cs.reduce((n, c) => n + c.estimate_cny, 0) * 100) / 100
  return {
    ...s, counts,
    remaining_cny: sum(s.clips.filter((c) => (c.state === 'planned' || c.state === 'failed') && !c.uncertain)),
    reserved_cny: sum(s.clips.filter((c) => IN_FLIGHT.includes(c.state))),
    uncertain_count: s.clips.filter((c) => c.uncertain).length,
  }
}

/** 每集两镜一段，每段 ¥5 */
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
    provider: 'fake', model: 'fake-1', resolution: '720p', audio_mode: 'tts_all', budget_cny: 100000,
    confirm_over_cny: 20, spent_cny: 0, clips, orphaned: [], counts: {}, remaining_cny: 0,
    reserved_cny: 0, uncertain_count: 0,
    options: { providers: ['fake'], models: { 'fake-1': { label: '假厂商' } }, resolutions: ['480p', '720p'],
               cny_per_sec: { '480p': 0.5, '720p': 1 }, max_clip_sec: 10, max_refs: 3,
               audio_modes: ['tts_all', 'dialogue_native', 'all_native', 'silent'],
               rate_note: '假厂商：不联网、不花钱' },
  })
}

const clipOf = (id: string) => film!.clips.find((c) => c.id === id)!

/** 模拟出片线程跑完一次：追加一次成功的尝试并采用它 */
function finish(id: string) {
  const c = clipOf(id)
  const n = c.attempts.length + 1
  const a: FilmAttempt = {
    task_id: `t${n}`, state: 'succeeded', cost_cny: c.estimate_cny, file: `clips/${id}.t${n}.mp4`,
    last_frame: `clips/${id}.t${n}.last.jpg`, error: null, at: '2026-10-31T03:00:00+00:00',
    fingerprint: 'fp', first_frame_used: null,
  }
  c.attempts.push(a)
  c.chosen = c.attempts.length - 1
  c.state = 'done'
  film = recount({ ...film!, spent_cny: film!.spent_cny + c.estimate_cny })
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
  calls.push(`${method} ${sub}${body === undefined ? '' : ` ${JSON.stringify(body)}`}`)
  if (sub.startsWith('/files/')) {
    return { ok: true, status: 200,
             blob: async () => new Blob(['x'], { type: sub.endsWith('.mp4') ? 'video/mp4' : 'image/jpeg' }) }
  }
  if (sub === '/session' && method === 'GET') {
    if (failNextGet) { failNextGet = false; throw new Error('网络断了') }
    return film ? ok({ ...film, gate: gateFail ? { ok: false, message: GATE } : { ok: true, message: null } })
      : fail(404, '还没有出片会话')
  }
  if (sub === '/session' && method === 'POST') {
    film = makeSession()
    return ok(film)
  }
  if (gateFail) return fail(422, { message: GATE, verification: { ok: false } })
  const spend = (targets: FilmClip[], expected: number | undefined, batch: boolean) => {
    const total = Math.round(targets.reduce((n, c) => n + c.estimate_cny, 0) * 100) / 100
    if (nextConflict !== null) {
      const fresh = nextConflict
      nextConflict = null
      return fail(409, { message: `预估金额已变为 ¥${fresh.toFixed(2)}，请重新确认`, expected_cny: fresh })
    }
    if ((batch || total > film!.confirm_over_cny) && expected === undefined) {
      return fail(409, { message: `本次约 ¥${total.toFixed(2)}，请确认金额后再出片`, expected_cny: total })
    }
    for (const c of targets) {
      Object.assign(c, { state: 'queued', queued_at: new Date().toISOString(), uncertain: false, error: null })
    }
    film = recount(film!)
    return ok(film)
  }
  let m = sub.match(/^\/clips\/([^/]+)\/run$/)
  if (m && method === 'POST') return spend([clipOf(decodeURIComponent(m[1]))], body?.expected_cny, false)
  if (sub === '/run' && method === 'POST') {
    return spend(film!.clips.filter((c) => (c.state === 'planned' || c.state === 'failed') && !c.uncertain),
                 body?.expected_cny, true)
  }
  m = sub.match(/^\/clips\/([^/]+)\/chosen$/)
  if (m && method === 'PUT') {
    clipOf(decodeURIComponent(m[1])).chosen = body.attempt
    film = recount(film!)
    return ok(film)
  }
  m = sub.match(/^\/clips\/([^/]+)$/)
  if (m && method === 'PATCH') {
    clipOf(decodeURIComponent(m[1])).mute_native = body.mute_native
    film = recount(film!)
    return ok(film)
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
const has = (s: string) => container.innerHTML.includes(s)
const button = (text: string) => {
  const b = [...container.querySelectorAll('button')].find((x) => (x.textContent ?? '').includes(text))
  if (!b) throw new Error(`✗ 找不到按钮「${text}」`)
  return b as unknown as HTMLButtonElement
}
const click = async (el: Element) => {
  await act(async () => {
    el.dispatchEvent(new win.MouseEvent('click', { bubbles: true }) as unknown as Event)
  })
  await settle()
}
const tab = (name: string) =>
  [...container.querySelectorAll('.tlc__tabs button')].find((b) => b.textContent === name)
const lanes = () => [...container.querySelectorAll('.tlc__labels text')].map((t) => t.textContent)
const bar = (id: string) => {
  const el = container.querySelector(`[data-clip="${id}"]`)
  if (!el) throw new Error(`✗ 成片泳道上找不到段 ${id}`)
  return el
}
const refresh = () => click(button('刷新'))

let setDirty: (v: boolean) => void = () => {}
function Host({ withVersion }: { withVersion: boolean }) {
  const [dirty, set] = useState(false)
  setDirty = set
  return <StoryboardView doc={doc} canSave dirty={dirty} saving={false}
                         version={withVersion ? { nid: 'n1', cid: 'c1', vid: 'v1' } : null}
                         onChange={() => set(true)} onSave={() => set(false)} />
}

// 0. 没有版本（本地 JSON / 分批预览）：画布里没有出片页签，也不请求出片接口
await act(async () => { root.render(<Host withVersion={false} />) })
await click(button('时间轴画布'))
must(!!container.querySelector('.tlc') && !tab('出片'), '没有版本时不出现「出片」页签')
must(calls.length === 0 && !lanes().includes('成片'), '没有版本时不请求出片接口、没有成片泳道')
console.log('0. 没有版本不出片 ✓')

// 1. 有版本、还没会话：没有成片泳道；「出片」页签里建会话（不花钱）→ 泳道出现，每段一条
await act(async () => { root.render(<Host key="v1" withVersion />) })
await click(button('时间轴画布'))
must(calls.includes('GET /session') && !lanes().includes('成片'), '读取会话 404 → 没有成片泳道')
await click(tab('出片')!)
await click(button('建立出片会话'))
must(calls.includes('POST /session {}'), '建会话发 POST')
must(lanes().includes('成片'), '有会话后出现「成片」泳道')
must(container.querySelectorAll('.tlc__clip').length === film!.clips.length, '每段一条横条')
const first = film!.clips[0].id
must(bar(first).classList.contains('tlc__clip--planned') && (bar(first).textContent ?? '').includes('约 ¥5.00'),
     '未出片：虚线框、写预估')
console.log(`1. 建会话 → 成片泳道 ${film!.clips.length} 段 ✓`)

// 2. 先试一段（¥5，不超过确认线）：不弹确认直接排队，横条变「生成中」
await click(button('先试这一段'))
must(calls.includes(`POST /clips/${first}/run {}`), '试段直接发请求、不带金额')
must(bar(first).classList.contains('tlc__clip--busy') && (bar(first).textContent ?? '').includes('生成中'),
     '横条变生成中')
console.log('2. 先试一段 ✓')

// 3. 出片线程跑完 → 刷新：横条填色、第 1 次，缩略图取了尾帧
finish(first)
await refresh()
await settle()
must(bar(first).classList.contains('tlc__clip--done') && (bar(first).textContent ?? '').includes('第 1 次'),
     '已完成：第 1 次')
must(calls.includes(`GET /files/clips/${first}.t1.last.jpg`) && !!bar(first).querySelector('image'),
     '缩略图用采用那次的尾帧')
console.log('3. 出完 → 填色与缩略图 ✓')

// 4. 批量：主按钮变「出剩余 N 段」；点了先弹确认（列各段、费率依据），不发请求
const n = film!.clips.length - 1
await click(button(`出剩余 ${n} 段`))
must(has('确认出片') && has('费率依据：假厂商'), '弹出确认框、写费率依据')
must(container.querySelectorAll('.film__rows tr').length === n, '确认框列出各段')
must(!calls.some((c) => c.startsWith('POST /run')), '确认前不发批量请求')
console.log('4. 批量先确认 ✓')

// 5. 服务端重算金额变了（409）→ 确认框换成新金额并提示；再确认才排队
nextConflict = 123.45
await click(button('确认出片'))
must(has('预估金额已变为 ¥123.45'), '金额变了要重新确认')
await click(button('确认出片（¥123.45）'))
must(calls[calls.length - 1] === 'POST /run {"expected_cny":123.45}', '再确认时带新金额')
must(!has('确认出片') && film!.clips.filter((c) => c.state === 'queued').length === n, '剩余各段都排上队')
console.log('5. 金额变动重新确认 ✓')

// 6. 单段超过确认线：失败的一段改成 ¥25，选中它 →「出这一段（约 ¥25.00）」先弹确认，确认才带金额发请求
const second = film!.clips[1].id
Object.assign(clipOf(second), { state: 'failed', error: '厂商返回失败：内容审核未通过', estimate_cny: 25 })
film = recount(film!)
await refresh()
await click(bar(second))
must(has('厂商返回失败：内容审核未通过'), '段详情写失败原因')
let before = calls.length
await click(button('出这一段（约 ¥25.00）'))
must(!calls.slice(before).some((c) => c.includes('/run')) && has('确认出片（¥25.00）'), '超过确认线先确认')
await click(button('确认出片（¥25.00）'))
must(calls.slice(before).includes(`POST /clips/${second}/run {"expected_cny":25}`), '确认后带金额')
console.log('6. 单段超线先确认 ✓')

// 7. 采用与静音：出过两次的段可以改用第 1 次；原声静音写回
finish(first)
await refresh()
await click(bar(first))
must(has('第 2 次'), '第二次成功后采用第 2 次')
await click(button('☆ 采用'))
must(calls[calls.length - 1] === `PUT /clips/${first}/chosen {"attempt":0}`, '改用第 1 次')
before = calls.length
const mute = container.querySelector('.film__clip input[type=checkbox]') as unknown as HTMLInputElement
await act(async () => { mute.click() })
await settle()
must(calls.slice(before).includes(`PATCH /clips/${first} {"mute_native":true}`), '原声静音写回')
console.log('7. 采用与原声静音 ✓')

// 8. 待核对：总览与段详情都提示到控制台核对
const third = film!.clips[2].id
Object.assign(clipOf(third), { state: 'failed', uncertain: true, error: '提交时连接中断，不确定厂商是否已受理' })
film = recount(film!)
await refresh()
must(has('1 段结果不明'), '总览提示待核对的段数')
await click(bar(third))
must(has('请到厂商控制台核对'), '段详情提示到控制台核对')
console.log('8. 待核对标记 ✓')

// 9. 未保存的改动：出片按钮禁用并提示先保存
await act(async () => { setDirty(true) })
await settle()
must(has('先保存再出片') && button('出这一段').disabled, '有未保存改动时不能出片')
await act(async () => { setDirty(false) })
await settle()
console.log('9. 未保存拦截 ✓')

// 10. 验证门：读取时报告没过 → 提示并禁用；修好后恢复
gateFail = true
await refresh()
must(has(GATE) && button('出这一段').disabled, '验证门没过时不能出片')
gateFail = false
await refresh()
must(!has(GATE) && !button('出这一段').disabled, '验证门通过后恢复')
console.log('10. 验证门拦截 ✓')

// 10b. 确认框开着时：未保存 / 验证门没过都要禁用确认；总览主按钮在未保存时也禁用
Object.assign(clipOf(second), { state: 'failed', error: null, uncertain: false, estimate_cny: 25 })
film = recount(film!)
await refresh()
await click(bar(second))
await click(button('出这一段（约 ¥25.00）'))
must(has('确认出片（¥25.00）') && !button('确认出片').disabled, '确认框开着、可确认')
await act(async () => { setDirty(true) })
await settle()
must(button('确认出片').disabled, '未保存时确认按钮禁用')
must(button('出剩余').disabled || button('先试这一段').disabled, '未保存时总览主按钮禁用')
await act(async () => { setDirty(false) })
await settle()
gateFail = true
await refresh()
must(button('确认出片').disabled, '验证门没过时确认按钮禁用')
gateFail = false
await refresh()
must(!button('确认出片').disabled, '恢复后确认按钮可用')
await click(button('取消'))
must(!has('确认出片'), '取消关掉确认框')
console.log('10b. 确认框随未保存 / 验证门禁用 ✓')

// 10c. 读取出错后轮询重新排上
failNextGet = true
const armed = pollTimers.length
await refresh()
must(has('网络断了'), '读取出错显示原因')
must(pollTimers.length > armed, '出错后轮询定时器重新排上')
await refresh()
console.log('10c. 出错后轮询不断 ✓')

// 11. 播成片：有已出的段才有开关；切到「播成片」后播放，预览窗里是采用那次的视频
await click(button('播关键帧'))
must(!!button('播成片'), '切到播成片')
await click(bar(first))
await click(button('▶ 播放'))
await settle(150)
must(!!container.querySelector('.tlc__pip video'), '预览窗里播视频')
must(calls.includes(`GET /files/clips/${first}.t1.mp4`), '取的是采用那次（第 1 次）的视频')
await click(button('❚❚ 暂停'))
console.log('11. 播成片 ✓')

await act(async () => { root.unmount() })
console.log('\nALL PASS')
