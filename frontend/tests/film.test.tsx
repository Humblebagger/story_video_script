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
                 'localStorage', 'sessionStorage', 'PointerEvent', 'MouseEvent', 'matchMedia', 'ResizeObserver', 'DOMRect',
                 'MutationObserver']) {
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
const GATE = '分镜没通过完整性检查，禁止进入付费渲染'
const IN_FLIGHT = ['queued', 'running', 'downloading']
let film: FilmSession | null = null
/** 每次出片请求记一行：`方法 子路径 请求体` */
const calls: string[] = []
/** 下一次花钱请求先回 409（模拟服务端重算的金额变了） */
let nextConflict: number | null = null
let gateFail = false
let gateObj = false
/** true 时验证门消息是已登记的代码 verify.gate.blocked；gateReadOk 时读取会话仍报通过（只让出片请求被拦） */
let gateCode = false
let gateReadOk = false
/** 出片被拦时返回的状态码（422 / 409） */
let gateHttp = 422
/** 下一次花钱请求回这个错（模拟带代码的 422 / 409） */
let nextFail: { status: number; detail: unknown } | null = null
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
    tier: 'demo', resolution: '720p', audio_mode: 'tts_all', budget_cny: 100000,
    confirm_over_cny: 20, spent_cny: 0, clips, orphaned: [], counts: {}, remaining_cny: 0,
    reserved_cny: 0, uncertain_count: 0,
    options: { tiers: [
                 { id: 'demo', label: { code: 'tier.demo', params: {} }, resolutions: ['480p', '720p'], default_resolution: '720p',
                   cny_per_sec: { '480p': 0.5, '720p': 1 }, audio_modes: ['tts_all', 'all_native', 'silent'] },
                 { id: 'a-fast', label: { code: 'tier.a_fast', params: {} }, resolutions: ['768P', '480P'], default_resolution: '768P',
                   cny_per_sec: { '768P': 0.4, '480P': 0.26 }, audio_modes: ['tts_all', 'silent'] },
               ], resolutions: ['480p', '720p'],
               cny_per_sec: { '480p': 0.5, '720p': 1 }, max_clip_sec: 10, max_refs: 3,
               audio_modes: ['tts_all', 'dialogue_native', 'all_native', 'silent'],
               rate_note: { code: 'rate.video', params: {} } },
  })
}

let lastSettings: Record<string, unknown> | undefined
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
  // 配音与合成由 compose.test.tsx 覆盖：这里回最小的合法预览与空音色表，也不记进 calls（免得打乱「最后一次调用」的断言）
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
    if (failNextGet) { failNextGet = false; throw new Error('网络断了') }
    return film ? ok({ ...film, gate: gateFail && !gateReadOk ? { ok: false, message: gateCode ? { code: 'verify.gate.blocked', params: {} } : gateObj ? { code: 'test.gate.unregistered', params: {}, message: GATE } : GATE } : { ok: true, message: null } })
      : fail(404, '还没有出片会话')
  }
  if (sub === '/session' && method === 'POST') {
    film = makeSession()
    return ok(film)
  }
  if (gateFail) return fail(gateHttp, gateCode ? { code: 'verify.gate.blocked', params: {}, message: GATE, verification: { ok: false } } : { message: GATE, verification: { ok: false } })
  const spend = (targets: FilmClip[], expected: number | undefined, batch: boolean) => {
    if (nextFail) {
      const f = nextFail
      nextFail = null
      return fail(f.status, f.detail)
    }
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
  if (sub === '/session' && method === 'PATCH') {
    lastSettings = body
    film = recount({ ...film!, ...(body.tier ? { tier: body.tier } : {}) })
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
// 花钱确认框是 Radix 对话框，挂在 document.body 下，所以文字与按钮都在整个 body 里找
const has = (s: string) => win.document.body.innerHTML.includes(s)
const button = (text: string) => {
  const b = [...win.document.body.querySelectorAll('button')].find((x) => (x.textContent ?? '').includes(text))
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
must(calls.includes(`POST /clips/${first}/run {"expected_cny":5}`), '试段不弹确认，但带着界面显示的金额')
must(bar(first).classList.contains('tlc__clip--busy') && (bar(first).textContent ?? '').includes('生成中'),
     '横条变生成中')
const queuedBtns = [...container.querySelectorAll('button')].map((b) => b.textContent ?? '')
must(!queuedBtns.some((t) => t.includes('先试这一段') || t.includes('出剩余')), '试段排队中不再提供第二次试段或批量')
must(has('试段生成中，出完再出剩余各段'), '排队中的提示')
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

const dlg = () => win.document.body.querySelector('[data-testid="money-confirm"]')
// 4. 批量：主按钮变「出剩余 N 段」；点了先弹确认（列各段、费率依据），不发请求
const n = film!.clips.length - 1
await click(button(`出剩余 ${n} 段`))
must(has('确认出片') && has('费率依据：按公开刊例价估算，未经账单核对'), '弹出确认框、写费率依据')
must(!!dlg() && dlg()!.querySelectorAll('.film__rows tr').length === n, '确认框列出各段')
must(!calls.some((c) => c.startsWith('POST /run')), '确认前不发批量请求')
console.log('4. 批量先确认 ✓')

// 5. 服务端重算金额变了（409）→ 确认框换成新金额并提示；再确认才排队
nextConflict = 123.45
await click(button('确认出片'))
must(has('金额已变为 ¥123.45'), '金额变了要重新确认')
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
must(has('请联系管理员核对'), '段详情提示联系管理员核对')
before = calls.length
await click(button('出这一段'))
must(dlg()!.textContent!.includes('结果不明'), '确认框里写明结果不明')
must(calls.length === before && !!win.document.body.querySelector('[data-testid="money-confirm"]'), '重做待核对的段先弹确认、不发请求')
// Esc 只关确认框，不连带关掉画布
await act(async () => {
  button('取消').dispatchEvent(new win.KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
})
await settle()
await act(async () => { await new Promise((r) => setTimeout(r, 400)) })
must(!dlg(), 'Esc 关掉确认框')
must(!!container.querySelector('.tlc'), 'Esc 关确认框时画布还在')
console.log('8. 待核对标记 ✓')

// 9. 未保存的改动：出片按钮禁用并提示先保存
await act(async () => { setDirty(true) })
await settle()
must(has('先保存再出片') && button('出这一段').disabled, '有未保存改动时不能出片')
await act(async () => { setDirty(false) })
await settle()
console.log('9. 未保存拦截 ✓')

// 10. 完整性检查：读取时报告没过 → 提示并禁用；修好后恢复
gateFail = true
await refresh()
must(has(GATE) && button('出这一段').disabled, '验证门没过时不能出片')
gateFail = false
await refresh()
must(!has(GATE) && !button('出这一段').disabled, '验证门通过后恢复')
gateFail = true; gateObj = true
await refresh()
must(has(GATE) && !has('[object') && button('出这一段').disabled, '验证门 message 是消息对象时也显示')
gateFail = false; gateObj = false
await refresh()
must(!has(GATE) && !button('出这一段').disabled, '消息对象的验证门通过后恢复')
console.log('10. 验证门拦截 ✓')

// 9b. 保存完（未保存 → 已保存）重读出片会话
{
  const gets = () => calls.filter((c) => c === 'GET /session').length
  const n0 = gets()
  await act(async () => { setDirty(true) })
  await settle()
  await act(async () => { setDirty(false) })
  await settle()
  must(gets() > n0, '保存后重读出片会话')
  console.log('9b. 保存后重读 ✓')
}

// 9c. 助手对这一版发起出片 / 合成：重读出片会话；别的版本不读
{
  const { notifyTask } = await import('../src/lib/assistantBridge')
  const gets = () => calls.filter((c) => c === 'GET /session').length
  const n0 = gets()
  await act(async () => { notifyTask({ kind: 'film', chapter_id: 'c1', version_id: 'v1' }) })
  await settle()
  must(gets() > n0, '助手对这一版出片后重读出片会话')
  const n1 = gets()
  await act(async () => { notifyTask({ kind: 'compose', chapter_id: 'c1', version_id: 'other' }) })
  await settle()
  must(gets() === n1, '别的版本不重读')
  console.log('9c. 助手发起后重读 ✓')
}

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

// 10d. 风格图：逐段说明、可重出提示与汇总计数；状态仍是完成
{
  const ids = film!.clips.map((c) => c.id)
  clipOf(ids[0]).style = 'used'
  clipOf(ids[0]).style_outdated = true
  clipOf(ids[1]).style = 'full'
  clipOf(ids[2]).style = 'first_frame'
  film!.style_outdated_count = 2
  await refresh()
  const styleText = async (id: string) => {
    await click(bar(id))
    return container.querySelector('[data-testid="clip-style"]')?.textContent ?? null
  }
  must((await styleText(ids[0])) === '风格图 ✓', 'used 写「风格图 ✓」')
  must((container.querySelector('[data-testid="clip-style-outdated"]')?.textContent ?? '').includes('风格图已换，可重出这一段'),
       '过期段有可重出提示')
  must(bar(ids[0]).classList.contains('tlc__clip--done'), '可重出的段状态仍是完成')
  must(has('2 段可按新风格图重出'), '汇总里有可重出计数')
  must((await styleText(ids[1])) === '未带上：参考位已满', 'full 的文字')
  must(!container.querySelector('[data-testid="clip-style-outdated"]'), '未过期的段没有可重出提示')
  must((await styleText(ids[2])) === '未带上：本段用首帧（关键帧或上一段尾帧）', 'first_frame 的文字')
  clipOf(ids[2]).style = null
  film!.style_outdated_count = 0
  await refresh()
  must((await styleText(ids[2])) === null, 'style 为 null 时没有这一行')
  must(!has('可按新风格图重出'), '计数为 0 时不显示')
  console.log('10d. 风格图说明与可重出 ✓')
}

// 10e. 画布关键帧区：给了 styleUrl 才有缩略图与下载链接
{
  const styled = (url: string | null) => (
    <StoryboardView doc={doc} canSave dirty={false} saving={false}
                    version={{ nid: 'n1', cid: 'c1', vid: 'v1' }}
                    styleUrl={url} styleMime="image/jpeg" onChange={() => {}} onSave={() => {}} />)
  await act(async () => { root.render(styled('blob:style-1')) })
  await click(button('时间轴画布'))
  const box = container.querySelector('[data-testid="kf-style"]')
  must(!!box && !!box.querySelector('img'), '有 styleUrl 时关键帧区有缩略图')
  const link = box!.querySelector('a')!
  must((link.textContent ?? '') === '下载风格图' && link.getAttribute('download') === 'style-reference.jpg',
       '下载链接文字与文件名')
  await act(async () => { root.render(styled(null)) })
  must(!container.querySelector('[data-testid="kf-style"]'), '不传 styleUrl 时没有这块')
  console.log('10e. 关键帧区下载风格图 ✓')
  await act(async () => { root.render(<Host key="v1" withVersion />) })
  await click(button('时间轴画布'))
  await click(tab('出片')!)
  await settle()
}

// 10f. 设置区只有一个档位下拉：选项是中性名字；没有「厂商」下拉；摘要一行带档位名
{
  const { zh } = await import('../src/i18n/zh')
  const setV = Object.getOwnPropertyDescriptor(win.HTMLSelectElement.prototype, 'value')!.set!
  const pick = async (el: HTMLSelectElement, v: string) => {
    await act(async () => { setV.call(el, v); el.dispatchEvent(new win.Event('change', { bubbles: true }) as unknown as Event) })
    await settle()
  }
  // 有段在跑时设置不能改：先把还在跑的段放回待出
  for (const c of film!.clips) if (['queued', 'running', 'downloading'].includes(c.state)) c.state = 'planned'
  film = recount(film!)
  await refresh()
  const sel = container.querySelector<HTMLSelectElement>('select[data-testid="film-tier"]')!
  must(!!sel && [...sel.options].map((o) => o.textContent).join('|') === `${zh.srv.tier.demo}|${zh.srv.tier.a_fast}`, '档位下拉的选项')
  must(container.querySelectorAll('.film__settings select').length === 3, '设置区只有档位、分辨率、声音三个下拉（没有厂商下拉）')
  must((container.querySelector('.film__settings summary')?.textContent ?? '').includes(zh.srv.tier.demo), '摘要带档位名')
  // 换到引擎 A · 快速：分辨率选项换成那一档的，当前 720p 不在其中 → 草稿取那一档的缺省 768P
  await pick(sel, 'a-fast')
  const res = container.querySelector<HTMLSelectElement>('select[data-testid="film-resolution"]')!
  must([...res.options].map((o) => o.value).join('|') === '768P|480P' && res.value === '768P', '换档带出分辨率')
  await click(button('应用设置'))
  const body = lastSettings as Record<string, unknown>
  must(body.tier === 'a-fast' && body.resolution === '768P' && !('provider' in body) && !('model' in body), '请求体用档位 id')
  // 10f-2. 原档位已不可用（tier 为 null）：下拉停在占位项，摘要写「原档位已不可用」
  film = { ...film!, tier: null }
  await refresh()
  must((container.querySelector('.film__settings summary')?.textContent ?? '').includes(zh.film.panel.tierGone), '摘要')
  must(container.querySelector<HTMLSelectElement>('select[data-testid="film-tier"]')!.value === '', '下拉占位')
  film = { ...film!, tier: 'demo' }
  await refresh()
  console.log('10f. 档位下拉 ✓')
}

// 10g. 后端错误按界面语言渲染：有 error_msg 按代码、没有就原样显示旧的 error；错误条存原始 detail，切语言跟着变
{
  const { I18nProvider } = await import('../src/i18n')
  const { useI18n } = await import('../src/i18n/core')
  const { en } = await import('../src/i18n/en')
  const { zh } = await import('../src/i18n/zh')
  const { conflictCny, ApiError } = await import('../src/api')
  let setLoc: (l: 'zh' | 'en') => void = () => {}
  function Cap() { setLoc = useI18n().setLocale; return null }
  const lang = async (l: 'zh' | 'en') => { await act(async () => { setLoc(l) }); await settle() }
  const [ca, cb] = [film!.clips[2].id, film!.clips[3].id]
  Object.assign(clipOf(ca), { state: 'failed', error: '这一段的画面描述或参考图没通过内容审核：…',
                              error_msg: { code: 'film.vendor.input_moderated', params: {} } })
  Object.assign(clipOf(cb), { state: 'failed', error: '旧中文原因', error_msg: null })
  film = recount({ ...film!, options: { ...film!.options, rate_note: { code: 'rate.video', params: {} } } })
  await act(async () => { root.render(<I18nProvider initial="zh"><Cap /><Host key="g1" withVersion /></I18nProvider>) })
  await click(button('时间轴画布'))
  await click(tab('出片')!)
  await settle()
  await click(bar(ca))
  must(has(zh.srv.film.vendor.input_moderated) && !has(en.srv.film.vendor.input_moderated), '中文界面：按代码渲染中文')
  await lang('en')
  must(has(en.srv.film.vendor.input_moderated) && !has(zh.srv.film.vendor.input_moderated), '切英文：按代码渲染英文')
  await click(bar(cb))
  must(has('旧中文原因'), '只有旧 error 时原样显示，切英文也不变')
  await lang('zh')
  must(has('旧中文原因'), '切回中文仍原样显示')
  // 确认框的费率依据随语言变
  await click(button('出剩余'))
  must(has(zh.srv.rate.video), '确认框费率依据（中文）')
  await lang('en')
  must(has(en.srv.rate.video) && !has(zh.srv.rate.video), '确认框费率依据（英文）')
  await lang('zh')
  await click(button('取消'))
  // 409 带代码仍取得到重算金额
  const conflict = new ApiError('x', 409, { code: 'film.run.changed', params: { amount: { t: 'money', cny: 6 } },
                                            message: '预估金额已变为 ¥6.00，请重新确认', expected_cny: 6 })
  must(conflictCny(conflict) === 6, '409 带代码：conflictCny 取到 6')
  // 出片失败的错误条：存原始 detail，切语言跟着变
  nextFail = { status: 422, detail: { code: 'film.run.nothing', params: {}, message: '没有要出的段' } }
  await click(button('出剩余'))
  await click(button('确认出片'))
  must(has(zh.srv.film.run.nothing), '错误条（中文）')
  await lang('en')
  must(has(en.srv.film.run.nothing) && !has(zh.srv.film.run.nothing), '切英文后已显示的错误条跟着变')
  console.log('10g. 后端错误按界面语言渲染 ✓')
  await act(async () => { root.render(<Host key="v1" withVersion />) })
  await click(button('时间轴画布'))
  await click(tab('出片')!)
  await settle()
}

// 10h. 验证门提示随语言变化（消息对象）
{
  const { I18nProvider } = await import('../src/i18n')
  const { useI18n } = await import('../src/i18n/core')
  const { en } = await import('../src/i18n/en')
  const { zh } = await import('../src/i18n/zh')
  let setLoc: (l: 'zh' | 'en') => void = () => {}
  function Cap() { setLoc = useI18n().setLocale; return null }
  const lang = async (l: 'zh' | 'en') => { await act(async () => { setLoc(l) }); await settle() }
  await act(async () => { root.render(<I18nProvider initial="zh"><Cap /><Host key="h1" withVersion /></I18nProvider>) })
  await click(button('时间轴画布'))
  await click(tab('出片')!)
  await settle()
  // 验证门消息是代码：读取会话的提示与出片被拦的提示都随语言变
  gateFail = true; gateCode = true
  await refresh()
  must(has(zh.srv.verify.gate.blocked), '读取会话的验证门提示（中文）')
  await lang('en')
  must(has(en.srv.verify.gate.blocked) && !has(zh.srv.verify.gate.blocked), '切英文后验证门提示变英文')
  gateFail = false
  await lang('zh')
  await refresh()
  must(!has(zh.srv.verify.gate.blocked), '验证门通过后提示消失')
  gateFail = true; gateReadOk = true
  await lang('zh')
  await refresh()
  await click(button('出剩余'))
  await click(button('确认出片'))
  must(has(zh.srv.verify.gate.blocked), '出片被拦（422 带 verification）提示中文')
  await lang('en')
  must(has(en.srv.verify.gate.blocked) && !has(zh.srv.verify.gate.blocked), '出片被拦的提示切英文跟着变')
  // 409 带 verification 与结构化门消息：同样随语言变
  gateFail = false; gateReadOk = false
  await lang('zh')
  await refresh()
  must(!has(zh.srv.verify.gate.blocked), '验证门通过后提示消失')
  gateFail = true; gateReadOk = true; gateHttp = 409
  await refresh()
  await click(button('出剩余'))
  await click(button('确认出片'))
  must(has(zh.srv.verify.gate.blocked), '409 出片被拦提示中文')
  await lang('en')
  must(has(en.srv.verify.gate.blocked) && !has(zh.srv.verify.gate.blocked), '409 出片被拦的提示切英文跟着变')
  gateFail = false; gateCode = false; gateReadOk = false; gateHttp = 422
  await lang('zh')
  await refresh()
  console.log('10h. 验证门提示随语言变化 ✓')
  await act(async () => { root.render(<Host key="v1" withVersion />) })
  await click(button('时间轴画布'))
  await click(tab('出片')!)
  await settle()
}

// 播放中视频的 blob 才落地时，act 会一直等 rAF 循环收不了场：播放期间的点击与等待不套 act（临时关掉 act 环境）
const actEnv = globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT?: boolean }
const rawWait = (ms: number) => new Promise((r) => setTimeout(r, ms))
const idle = async () => { await rawWait(60); actEnv.IS_REACT_ACT_ENVIRONMENT = true; await settle() }
const tap = async (el: Element, ms = 80) => {
  actEnv.IS_REACT_ACT_ENVIRONMENT = false
  el.dispatchEvent(new win.MouseEvent('click', { bubbles: true }) as unknown as Event)
  await rawWait(ms)
}
// 11. 有成片优先播成片：有已出的段时不点开关直接播放，预览窗就是采用那次的视频；切到「播关键帧」后是关键帧 / 脚本
await click(bar(first))
await tap(container.querySelector('.tlc__play')!)
await rawWait(300)
must(!!button('播成片'), '默认就是播成片（开关显示「播成片」）')
must(!!container.querySelector('.tlc__pip video'), '不点开关，预览窗里直接播视频')
must(calls.includes(`GET /files/clips/${first}.t1.mp4`), '取的是采用那次（第 1 次）的视频')
must(!container.querySelector('.tlc__pipnote'), '有视频的段不挂「未出片」')
// 播放中点开关切到「播关键帧」：预览窗换成关键帧 / 脚本
await tap(button('播成片'))
must(!!button('播关键帧'), '点开关切到播关键帧')
must(!container.querySelector('.tlc__pip video'), '切到播关键帧后预览窗没有视频')
must(!!container.querySelector('.tlc__pip img, .tlc__pip .tlc__pipph'), '切到播关键帧后预览窗是关键帧或脚本')
await tap(container.querySelector('.tlc__play')!)
await tap(button('播关键帧'))
await idle()
console.log('11. 有成片优先播成片 ✓')

// 11b. 没出片的段显示脚本：一段都没出片时没有「未出片」角标；有段已出片时播到未出片的段带角标
{
  const gone = film!.clips.find((c) => c.chosen !== null)!
  const savedChosen = gone.chosen
  const other = film!.clips.find((c) => c !== gone && c.chosen === null)!
  for (const c of film!.clips) c.chosen = null
  await refresh()
  await click(bar(other.id))
  await tap(container.querySelector('.tlc__play')!)
  await rawWait(150)
  must(!container.querySelector('.tlc__pip video'), '一段都没出片：预览窗没有视频')
  must(!!container.querySelector('.tlc__pip img, .tlc__pip .tlc__pipph'), '一段都没出片：预览窗显示关键帧或脚本')
  must(!container.querySelector('.tlc__pipnote'), '一段都没出片：没有「未出片」角标')
  await tap(container.querySelector('.tlc__play')!)
  await idle()
  gone.chosen = savedChosen
  await refresh()
  await click(bar(other.id))
  await tap(container.querySelector('.tlc__play')!)
  await rawWait(150)
  must(!container.querySelector('.tlc__pip video'), '有段已出片、播到未出片的段：显示脚本而不是视频')
  must(!!container.querySelector('.tlc__pipnote'), '有段已出片、播到未出片的段：带「未出片」角标')
  await tap(container.querySelector('.tlc__play')!)
  await idle()
  console.log('11b. 未出片的段显示脚本、角标只在部分出片时出现 ✓')
}

// 12. 卡片内确认（runClipNow）：409 带新金额时返回新金额，不弹确认框；成功返回 null
{
  const { useFilm } = await import('../src/useFilm')
  let hook: ReturnType<typeof useFilm> | null = null
  function Probe() { hook = useFilm({ nid: 'n1', cid: 'c1', vid: 'v1' }, { active: true }); return null }
  const probeRoot = createRoot(win.document.createElement('div') as unknown as HTMLElement)
  await act(async () => { probeRoot.render(<Probe />) })
  await settle()
  const id = film!.clips[0].id
  Object.assign(clipOf(id), { state: 'planned', error: null })
  film = recount(film!)
  nextConflict = 77.7
  let got: number | null = null
  await act(async () => { got = await hook!.runClipNow(id, 5) })
  must(got === 77.7, '409 带新金额：返回新金额')
  await act(async () => { got = await hook!.runClipNow(id, 77.7) })
  must(got === null && clipOf(id).state === 'queued', '成功返回 null、段已排队')
  await act(async () => { probeRoot.unmount() })
  console.log('12. 卡片内确认的金额回传 ✓')
}

await act(async () => { root.unmount() })
console.log('\nALL PASS')
