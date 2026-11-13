/** 配音与合成：纯计算（能不能合成及原因、状态文字、成片分组、对齐说明、选曲参考、BGM 类型、按钮文字、重读时机），
 *  以及「出片」页签里合成区的界面回归：缺音色拦截与选音色、没装 ffmpeg 的提示、配音金额先确认与 409 换新金额、
 *  合成中、完成后播放下载与报告、过期、失败、「先用图片代替」开关、BGM 上传删除、未保存拦截（保存后重读）、不配音的模式，
 *  以及操作报错不被重读清掉、确认框开着时锁住会改金额的操作、音色表读取失败不挡预览、预览读取失败可重试。
 *  桩后端在内存里模拟合成预览（后台合成的推进由测试直接改状态）。跑法：npm test
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

import {
  bgmType, composeBlockers, speakerName, composeKey, composeLabel, composing, curveText, finalEpisodes, finalText, noteText,
} from '../src/compose'
import type {
  ComposePreview, FilmClip, FilmSession, FinalState, MixReport, Storyboard, VoicesInfo,
} from '../src/types'

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }

/* ---------- 纯计算 ---------- */
{
  const P: ComposePreview = {
    lines: 3, tts_chars: 30, tts_cny: 0.01, missing_voices: ['C09'], voices: { narration: 'fake-male' },
    no_video: ['E01-C02'], fingerprint: 'fp', final: null, bgm: [], tools: true, music: {}, report: null,
  }
  const S = {
    audio_mode: 'tts_all', resolution: '720p', budget_cny: 200, spent_cny: 10, voices: {}, final: null,
    clips: [{ id: 'E01-C01', state: 'done', chosen: 0, mute_native: false },
            { id: 'E01-C02', state: 'planned', chosen: null, mute_native: false }],
  } as unknown as FilmSession
  const V: VoicesInfo = {
    provider: 'fake', rate_note: '假配音', voices: [{ id: 'fake-male', name: '假男声', gender: 'male' }],
    speakers: [{ key: 'C09', name: '路人', hint: null, voice: null, chosen: null }], missing: ['C09'],
  }
  const base = { dirty: false, gate: null, draft: true }

  must(composeBlockers(P, S, V, base).join('|') === '还有 1 个说话人没选音色：路人', '缺音色写说话人名字')
  const VM: VoicesInfo = { ...V, speakers: [
    { key: 'narration', name: { code: 'voice.narrator', params: {} }, hint: null, voice: null, chosen: null },
    { key: '', name: { code: 'voice.unlabeled', params: {} }, hint: null, voice: null, chosen: null }] }
  must(speakerName(VM, 'narration') === '旁白' && speakerName(VM, '') === '（未标说话人）', 'speakerName 渲染消息对象')
  must(speakerName(V, 'C09') === '路人' && speakerName(null, 'x') === 'x', 'speakerName 字符串原样')
  must(composeBlockers({ ...P, missing_voices: ['narration'] }, S, VM, base)[0].includes('旁白'), '拦截原因里写旁白')
  must(composeBlockers({ ...P, missing_voices: [] }, S, V, base).length === 0, '没出好的段先用图片代替时缺段不拦')
  must(composeBlockers({ ...P, missing_voices: [] }, S, V, { ...base, draft: false })[0]
    .startsWith('1 段还没有可用的视频'), '关掉「先用图片代替」时缺段要拦')
  const all = composeBlockers({ ...P, tools: false, tts_cny: 500, missing_voices: [] },
    { ...S, clips: [{ ...S.clips[0], state: 'running' }] } as FilmSession, V,
    { dirty: true, gate: '分镜没通过完整性检查', draft: true })
  must(all.length === 5 && all[0].includes('先保存再合成') && all[1].includes('分镜没通过完整性检查')
    && all[2].includes('ffmpeg') && !all[2].includes('brew') && all[3].includes('排队或生成中') && all[4].includes('超过上限'),
    `各种拦截按顺序列出：${all.join(' / ')}`)
  const busy: FinalState = { state: 'running', step: '混音 E01', files: [], report: null, error: null, detail: null }
  must(composing({ ...P, final: busy }) && !composing(P), '合成中')
  must(composeBlockers({ ...P, missing_voices: [], final: busy }, S, V, base)[0] === '正在合成，等它结束再合成',
    '合成中不能再合成')
  console.log('1. 能不能合成及原因 ✓')

  must(finalText(busy) === '合成中 · 混音 E01', '合成中写步骤')
  must(finalText({ ...busy, state: 'failed', error: '混音 E01 失败' }) === '合成失败：混音 E01 失败', '失败写原因')
  must(finalText({ ...busy, state: 'done', stale: false }) === '成片是最新的', '最新')
  must(finalText({ ...busy, state: 'done', stale: true }).startsWith('内容改过，需要重新合成'), '内容改过')
  const eps = finalEpisodes(['final/E01.mp4', 'final/E01.srt', 'final/E02.mp4', 'final/mix_report.json'])
  must(JSON.stringify(eps) === JSON.stringify([
    { episode: 'E01', video: 'final/E01.mp4', srt: 'final/E01.srt' }, { episode: 'E02', video: 'final/E02.mp4' }]),
    '成片按集分组')
  console.log('2. 成片状态与分组 ✓')

  must(noteText({ shot: 'S2', kind: 'speedup', speed: 1.1 }) === 'S2：语速提到 1.1×', '提速说明')
  must(noteText({ shot: 'S3', kind: 'freeze', speed: 1.15, extend: 0.61 })
    === 'S3：按 1.15× 念仍超出镜头，段尾定格延长 0.61 秒', '定格说明')
  must(curveText({ from_shot: 'E01-SH001', to_shot: 'E01-SH010', mood: 'calm', intensity: 'low', note: '秋夜' })
    === 'E01-SH001–E01-SH010 · 平静 · 弱 · 秋夜', '选曲参考')
  must(curveText({ mood: 'tense' }) === '紧张', '选曲参考缺项')
  console.log('3. 对齐说明与选曲参考 ✓')

  must(bgmType({ name: 'a.mp3', type: 'audio/mpeg' }) === 'audio/mpeg', '浏览器给的类型')
  must(bgmType({ name: 'b.M4A', type: '' }) === 'audio/mp4', '没有类型按扩展名')
  must(bgmType({ name: 'c.wav', type: 'audio/x-wav' }) === 'audio/x-wav', 'x-wav 也认')
  must(bgmType({ name: 'd.txt', type: 'text/plain' }) === null, '不是音频')
  must(composeLabel(P) === '合成整章（配音约 ¥0.01）' && composeLabel({ ...P, tts_cny: 0 }) === '合成整章（不花钱）',
    '按钮写金额')
  const k1 = composeKey(S)
  must(composeKey({ ...S, voices: { C09: 'fake-male' } } as FilmSession) !== k1
    && composeKey({ ...S, clips: [S.clips[0], { ...S.clips[1], state: 'done' }] } as FilmSession) !== k1
    && composeKey({ ...S, spent_cny: 99 } as FilmSession) === k1, '音色、段状态变了才重读；已花变了不重读')
  console.log('4. BGM 类型、按钮文字、重读时机 ✓')
}

/* ---------- 界面：桩后端 ---------- */
const doc: Storyboard = JSON.parse(
  readFileSync('../backend/tests/real_text_yao/output_merged.json', 'utf8'))
const R = '/novels/n1/chapters/c1/versions/v1/render'
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x))
/** 每次合成相关请求记一行：`方法 子路径 请求体`（BGM 记 Content-Type） */
const calls: string[] = []
let nextConflict: number | null = null
/** 下一次 POST /compose 直接按这个失败（测报错留在界面上） */
let nextPostFail: { status: number; detail: unknown } | null = null
/** 读预览 / 音色表失败 */
let composeDown: unknown = false
let voicesDown: unknown = false
let filesDown: unknown = false

/** 每集两镜一段；最后一段还没出片 */
function makeSession(): FilmSession {
  const clips: FilmClip[] = []
  for (const ep of doc.episodes) {
    for (let i = 0; i < ep.shots.length; i += 2) {
      const id = `${ep.id}-C${String(clips.length + 1).padStart(2, '0')}`
      clips.push({
        id, episode: ep.id, shots: ep.shots.slice(i, i + 2).map((s) => s.id), duration: 5, truncated: false,
        prompt: '提示词', refs: [], dropped_refs: [], missing_refs: [], first_frame: null, frame_mode: null,
        fingerprint: 'fp', estimate_cny: 5, chosen: 0, mute_native: false, uncertain: false, error: null,
        state: 'done',
        attempts: [{ task_id: 't1', state: 'succeeded', cost_cny: 5, file: `clips/${id}.t1.mp4`,
                     last_frame: null, error: null, at: '2026-10-31T03:00:00+00:00', fingerprint: 'fp',
                     first_frame_used: null }],
      })
    }
  }
  const last = clips[clips.length - 1]
  Object.assign(last, { state: 'planned', attempts: [], chosen: null })
  return {
    provider: 'fake', model: 'fake-1', resolution: '720p', audio_mode: 'tts_all', budget_cny: 200,
    confirm_over_cny: 20, spent_cny: 100, voices: {}, final: null, clips, orphaned: [],
    counts: { done: clips.length - 1, planned: 1 }, remaining_cny: 5, reserved_cny: 0, uncertain_count: 0,
    options: { providers: ['fake'], models: { 'fake-1': { label: '假厂商' } }, resolutions: ['720p'],
               cny_per_sec: { '720p': 1 }, max_clip_sec: 10, max_refs: 3,
               audio_modes: ['tts_all', 'dialogue_native', 'all_native', 'silent'], rate_note: '假厂商' },
  }
}
let film = makeSession()
const lastClip = film.clips[film.clips.length - 1].id

const voicesInfo: VoicesInfo = {
  provider: 'fake', rate_note: { code: 'rate.fake_tts', params: {} },
  voices: [{ id: 'fake-male', name: '假男声', gender: 'male' }, { id: 'fake-female', name: '假女声', gender: 'female' }],
  speakers: [
    { key: 'narration', name: { code: 'voice.narrator', params: {} }, hint: 'male_mature', voice: 'fake-male', chosen: null },
    { key: 'C01', name: '老栓', hint: 'male_elder', voice: 'fake-male', chosen: null },
    { key: 'C09', name: '路人', hint: null, voice: null, chosen: null },
  ],
  missing: ['C09'],
}
const preview: ComposePreview = {
  lines: 40, tts_chars: 600, tts_cny: 0.18, missing_voices: ['C09'],
  voices: { narration: 'fake-male', C01: 'fake-male' }, no_video: [lastClip], fingerprint: 'fp1', final: null,
  bgm: [], tools: true,
  music: Object.fromEntries(doc.episodes.map((ep) => [ep.id, ep.music ?? {}])), report: null,
}
const REPORT: MixReport = {
  audio_mode: 'tts_all', size: '720x1280', draft: true, alignment: '段内镜头切换时刻由视频模型决定，属近似对齐',
  episodes: [{ episode: 'E01', seconds: 61.5, placeholders: [], stale: [],
               notes: [{ shot: 'E01-SH002', kind: 'speedup', speed: 1.1 },
                       { shot: 'E01-SH003', kind: 'freeze', speed: 1.15, extend: 0.61 }] },
             { episode: 'E04', seconds: 40, placeholders: [lastClip], stale: [], notes: [] }],
}
const FILES = ['final/E01.mp4', 'final/E01.srt', 'final/E04.mp4', 'final/E04.srt']

const ok = (data: unknown) => ({ ok: true, status: 200, json: async () => clone(data) })
const fail = (status: number, detail: unknown) =>
  ({ ok: false, status, statusText: '', text: async () => JSON.stringify({ detail }) })

g.fetch = async (url: string, init?: { method?: string; body?: unknown; headers?: Record<string, string> }) => {
  const path = String(url).replace(/^\/api/, '')
  const method = init?.method ?? 'GET'
  if (path === '/render/keyframes') return ok({ keyframes: [] })
  if (path === '/novels/n1/chapters/c1/versions/v1/keyframes') return ok({ shots: [] })
  if (!path.startsWith(R)) throw new Error(`桩后端未实现的路径: ${method} ${path}`)
  const sub = path.slice(R.length)
  if (sub === '/session' && method === 'GET') {
    calls.push('GET /session')
    return ok({ ...film, gate: { ok: true, message: null } })
  }
  if (sub.startsWith('/files/')) {
    calls.push(`GET ${sub}`)
    if (filesDown) return fail(404, filesDown)
    return { ok: true, status: 200,
             blob: async () => new Blob(['x'], { type: sub.endsWith('.mp4') ? 'video/mp4' : 'text/plain' }) }
  }
  const m = sub.match(/^\/bgm\/([^/]+)$/)
  if (m) {
    const ep = decodeURIComponent(m[1])
    if (method === 'PUT') {
      calls.push(`PUT /bgm/${ep} ${init?.headers?.['Content-Type']}`)
      if (!preview.bgm.includes(ep)) preview.bgm.push(ep)
      return ok({ episode: ep, bytes: 3 })
    }
    calls.push(`DELETE /bgm/${ep}`)
    preview.bgm = preview.bgm.filter((x) => x !== ep)
    return ok({ deleted: ep })
  }
  const body = typeof init?.body === 'string' ? JSON.parse(init.body) : undefined
  calls.push(`${method} ${sub}${body === undefined ? '' : ` ${JSON.stringify(body)}`}`)
  if (sub.startsWith('/compose') && method === 'GET') {
    if (composeDown) return fail(500, composeDown)
    const draft = new URL(`http://x${sub}`).searchParams.get('draft') !== 'false'
    return ok({ ...preview, fingerprint: draft ? 'fp1' : 'fp1-nodraft' })
  }
  if (sub === '/voices' && method === 'GET') return voicesDown ? fail(500, voicesDown) : ok(voicesInfo)
  if (sub === '/voices' && method === 'PUT') {
    for (const [k, v] of Object.entries(body.voices as Record<string, string>)) {
      const sp = voicesInfo.speakers.find((x) => x.key === k)!
      sp.chosen = v || null
      sp.voice = v || (sp.hint ? 'fake-male' : null)
    }
    voicesInfo.missing = voicesInfo.speakers.filter((x) => !x.voice).map((x) => x.key)
    preview.missing_voices = [...voicesInfo.missing]
    film = { ...film, voices: Object.fromEntries(voicesInfo.speakers.filter((x) => x.chosen).map((x) => [x.key, x.chosen!])) }
    return ok(voicesInfo)
  }
  if (sub === '/compose' && method === 'POST') {
    if (nextPostFail) {
      const f = nextPostFail
      nextPostFail = null
      return fail(f.status, f.detail)
    }
    if (nextConflict !== null) {
      preview.tts_cny = nextConflict
      nextConflict = null
      return fail(409, { message: `本次配音约 ¥${preview.tts_cny.toFixed(2)}，请确认金额后再合成`,
                         expected_cny: preview.tts_cny })
    }
    if (body.expected_cny !== preview.tts_cny) {
      return fail(409, { message: '请确认金额后再合成', expected_cny: preview.tts_cny })
    }
    const f: FinalState = { state: 'running', step: '开始', files: [], report: null, error: null, detail: null,
                            draft: body.draft, started_at: '2026-10-31T04:00:00+00:00' }
    preview.final = { ...f, stale: false }
    film = { ...film, final: f }
    return ok(film)
  }
  throw new Error(`桩后端未实现的路径: ${method} ${path}`)
}

const { act, useState } = await import('react')
const { createRoot } = await import('react-dom/client')
const { StoryboardView } = await import('../src/components/StoryboardView')

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
const change = async (el: Element, set: () => void) => {
  await act(async () => {
    set()
    el.dispatchEvent(new win.Event('change', { bubbles: true }) as unknown as Event)
  })
  await settle()
}
const tab = (name: string) =>
  [...container.querySelectorAll('.tlc__tabs button')].find((b) => b.textContent === name)
const refresh = () => click(button('刷新合成'))
const composeBtn = () => button('合成整章')
const since = (n: number) => calls.slice(n)

let setDirty: (v: boolean) => void = () => {}
function Host() {
  const [dirty, set] = useState(false)
  setDirty = set
  return <StoryboardView doc={doc} canSave dirty={dirty} saving={false} version={{ nid: 'n1', cid: 'c1', vid: 'v1' }}
                         onChange={() => set(true)} onSave={() => set(false)} />
}

// 5. 打开「出片」页签：合成区读预览与音色表；缺音色时按钮禁用并写出说话人；选曲参考来自分镜
await act(async () => { root.render(<Host />) })
await click(button('时间轴画布'))
await click(tab('出片')!)
await settle()
must(calls.includes('GET /compose?draft=true') && calls.includes('GET /voices'), '读合成预览与音色表')
must(has('配音与合成') && has('配音 40 条 · 未缓存 600 字 · 约 ¥0.18') && has('1 段还没出片'), '预览数字')
must(has('还有 1 个说话人没选音色：路人') && composeBtn().disabled, '缺音色拦截')
must(has('秋夜死寂'), '选曲参考来自分镜 music.curve')
console.log('5. 合成区预览与缺音色拦截 ✓')

// 6. 给路人选音色 → PUT /voices → 重读后按钮可用、写配音金额
const sel = container.querySelector('select[aria-label="路人 的音色"]') as unknown as HTMLSelectElement
await change(sel, () => { sel.value = 'fake-female' })
must(calls.includes('PUT /voices {"voices":{"C09":"fake-female"}}'), '选音色写回')
must(!has('没选音色') && !composeBtn().disabled && (composeBtn().textContent ?? '').includes('配音约 ¥0.18'),
  '选完可以合成，按钮写金额')
console.log('6. 选音色 ✓')

// 7. 服务器没装 ffmpeg：提示面向用户（不写安装命令），按钮禁用
preview.tools = false
await refresh()
must(has('ffmpeg') && !has('brew') && !has('apt install') && composeBtn().disabled, '没装 ffmpeg 的提示')
preview.tools = true
await refresh()
must(!composeBtn().disabled, '装好后恢复')
console.log('7. 没装 ffmpeg 的提示 ✓')

// 8. 合成：先弹确认（配音金额、费率依据），不发请求；服务端金额变了（409）→ 换新金额再确认 → 带新金额发请求
let n0 = calls.length
await click(composeBtn())
must(has('确认合成（¥0.18）') && has('费率依据：假配音') && !since(n0).some((c) => c.startsWith('POST')),
  '确认前不发请求')
nextConflict = 0.21
n0 = calls.length
await click(button('确认合成'))
must(since(n0).includes('POST /compose {"expected_cny":0.18,"draft":true}'), '第一次带确认过的 ¥0.18')
must(has('金额已变为 ¥0.21'), '金额变了要重新确认')
n0 = calls.length
await click(button('确认合成（¥0.21）'))
must(since(n0).includes('POST /compose {"expected_cny":0.21,"draft":true}'), '带新金额与草稿设置')
must(!has('确认合成') && has('合成中 · 开始') && has('正在合成，等它结束再合成') && composeBtn().disabled,
  '合成中：写步骤、不能再合成')
console.log('8. 配音金额确认与 409 重新确认 ✓')

// 9. 后台合成完成 → 刷新：成片是最新的；出片会话跟着重读；播放 / 下载取 blob；报告写对齐调整
preview.final = { state: 'done', step: '完成', files: FILES, report: 'final/mix_report.json', error: null,
                  detail: null, draft: true, finished_at: '2026-10-31T04:05:00+00:00', stale: false }
preview.report = REPORT
film = { ...film, final: { ...preview.final, stale: undefined }, spent_cny: 100.21 }
n0 = calls.filter((c) => c === 'GET /session').length
await refresh()
await settle()
must(has('成片是最新的'), '完成')
must(calls.filter((c) => c === 'GET /session').length > n0, '合成跑完后出片会话重读（已花变了）')
await click(button('播放 / 下载'))
await settle()
must(calls.includes('GET /files/final/E01.mp4') && calls.includes('GET /files/final/E01.srt'), '取成片与字幕')
must(!!container.querySelector('.compose__play video'), '播放成片')
const links = [...container.querySelectorAll('.compose__play a')].map((a) => a.getAttribute('download'))
must(links.includes('E01.mp4') && links.includes('E01.srt'), '下载 mp4 与字幕')
must(has('61.5 秒') && has('E01-SH002：语速提到 1.1×') && has('段尾定格延长 0.61 秒')
  && has(`补位（关键帧或黑场）：${lastClip}`), '合成报告')
console.log('9. 完成后播放、下载与报告 ✓')

// 10. 过期与失败：失败时写原因、ffmpeg 输出，并说明下面是上一次的成片
preview.final = { ...preview.final, stale: true }
await refresh()
must(has('内容改过，需要重新合成'), '内容改过提示')
preview.final = { ...preview.final, state: 'failed', error: '混音 E01 失败（ffmpeg 退出码 1）',
                  detail: 'Invalid argument', stale: false }
await refresh()
must(has('合成失败：混音 E01 失败') && has('Invalid argument') && has('下面是上一次合成的成片'), '失败')
console.log('10. 过期与失败 ✓')

// 11. 「先用图片代替」开关：关掉后按 draft=false 重读，缺段拦截；再打开恢复
const draftBox = container.querySelector('.compose__run input[type=checkbox]') as unknown as HTMLInputElement
await act(async () => { draftBox.click() })
await settle()
must(calls.includes('GET /compose?draft=false'), '按关掉「先用图片代替」重读')
must(has('1 段还没有可用的视频') && composeBtn().disabled, '关掉「先用图片代替」时缺段拦截')
await act(async () => { draftBox.click() })
await settle()
must(!has('1 段还没有可用的视频') && !composeBtn().disabled, '打开后恢复')
console.log('11. 「先用图片代替」开关 ✓')

// 12. BGM：上传（按扩展名补类型）→ 已上传 → 删除；不是音频的不发请求
const pick = async (name: string, type: string) => {
  const input = container.querySelector('input[aria-label="E01 的 BGM"]') as unknown as HTMLInputElement
  const file = new win.File(['ID3'], name, { type }) as unknown as File
  await change(input, () => { Object.defineProperty(input, 'files', { value: [file], configurable: true }) })
}
await pick('theme.mp3', '')
must(calls.includes('PUT /bgm/E01 audio/mpeg') && has('已上传 1 /'), '上传 BGM')
n0 = calls.length
await pick('notes.txt', 'text/plain')
must(has('BGM 只支持 mp3、wav、m4a、aac') && !since(n0).some((c) => c.startsWith('PUT /bgm')), '不是音频不上传')
await click(button('删除'))
must(calls.includes('DELETE /bgm/E01') && has('已上传 0 /'), '删除 BGM')
console.log('12. BGM 上传与删除 ✓')

// 13. 有未保存的修改：不能合成
await act(async () => { setDirty(true) })
await settle()
must(has('先保存再合成') && composeBtn().disabled, '未保存拦截')
n0 = calls.length
await act(async () => { setDirty(false) })
await settle()
must(since(n0).includes('GET /compose?draft=true'), '保存后重读合成预览')
console.log('13. 未保存拦截、保存后重读 ✓')

// 14. 不配音的声音模式：不读音色表，按钮写「不花钱」
Object.assign(preview, { lines: 0, tts_chars: 0, tts_cny: 0, missing_voices: [], voices: {} })
n0 = calls.length
await refresh()
must(!since(n0).includes('GET /voices') && has('这个声音模式下没有要配音的语音条'), '不读音色表')
must((composeBtn().textContent ?? '').includes('不花钱'), '按钮写不花钱')
n0 = calls.length
await click(composeBtn())
must(since(n0).includes('POST /compose {"expected_cny":0,"draft":true}') && !has('确认合成'), '金额 0 不弹确认')
console.log('14. 不配音的模式 ✓')

// 15. 确认框开着：「先用图片代替」、音色、BGM 都锁住；重读出的金额变了就换新金额；409 不带金额 → 关掉确认框、原因留着
Object.assign(preview, { lines: 40, tts_chars: 600, tts_cny: 0.18, final: null, report: null })
await refresh()
await click(composeBtn())
must(has('确认合成（¥0.18）'), '弹确认')
const draftNow = container.querySelector('.compose__run input[type=checkbox]') as unknown as HTMLInputElement
const selects = [...container.querySelectorAll('.compose__table select')] as unknown as HTMLSelectElement[]
const bgmIn = container.querySelector('input[aria-label="E01 的 BGM"]') as unknown as HTMLInputElement
must(draftNow.disabled && selects.length === 3 && selects.every((x) => x.disabled) && bgmIn.disabled,
  '确认框开着时锁住会改金额的操作')
preview.tts_cny = 0.2
await refresh()
must(has('金额已变为 ¥0.20') && has('确认合成（¥0.20）'), '重读出的金额变了：换新金额再确认')
nextPostFail = { status: 409, detail: { message: '音色刚被改过，请重新确认金额', expected_cny: null } }
await click(button('确认合成'))
await settle()
must(has('音色刚被改过，请重新确认金额') && !has('确认合成'), '409 不带金额：原因留着、确认框关掉')
must(!draftNow.disabled, '确认框关掉后解锁')
console.log('15. 确认框开着时锁住、金额变了换新、409 原因不被重读清掉 ✓')

// 16. 422（比如音色刚被清掉）：原因留在界面上
nextPostFail = { status: 422, detail: '还有说话人没选音色：路人' }
await click(composeBtn())
await click(button('确认合成'))
await settle()
must(has('还有说话人没选音色：路人') && !has('确认合成'), '422 原因留着')
console.log('16. 422 原因留着 ✓')

// 17. 音色表读不出来：预览照常、按钮还在，音色那块写原因；恢复后音色表回来
voicesDown = '音色服务挂了'
await refresh()
must(has('配音 40 条') && !!composeBtn() && has('读取音色表失败：音色服务挂了'), '音色表出错不挡预览')
voicesDown = false
await refresh()
must(!has('读取音色表失败') && !!container.querySelector('select[aria-label="路人 的音色"]'), '音色表恢复')
console.log('17. 音色表出错不挡整块 ✓')

// 18. 预览读不出来：写原因并给「重试」；重试成功后显示预览
composeDown = '合成预览读不出来'
await click(tab('资产')!)
await click(tab('出片')!)
await settle()
must(has('合成预览读不出来') && !has('配音 40 条'), '预览读取失败')
composeDown = false
await click(button('重试'))
must(has('配音 40 条') && !has('合成预览读不出来'), '重试后显示预览')
console.log('18. 预览读取失败可重试 ✓')

// 19. 费率说明、旁白名、音色错误按界面语言渲染（对象不会直接放进 JSX），切语言后已显示的错误跟着变
{
  const { I18nProvider } = await import('../src/i18n')
  const { useI18n } = await import('../src/i18n/core')
  const { en } = await import('../src/i18n/en')
  const { zh } = await import('../src/i18n/zh')
  let setLoc: (l: 'zh' | 'en') => void = () => {}
  function Cap() { setLoc = useI18n().setLocale; return null }
  const lang = async (l: 'zh' | 'en') => { await act(async () => { setLoc(l) }); await settle() }
  await act(async () => { root.render(<I18nProvider initial="zh"><Cap /><Host key="i18n" /></I18nProvider>) })
  await click(button('时间轴画布'))
  await click(tab('出片')!)
  await settle()
  must(has(zh.srv.rate.fake_tts) && has(zh.srv.voice.narrator), '中文界面：费率说明与旁白名')
  await lang('en')
  must(has(en.srv.rate.fake_tts) && !has(zh.srv.rate.fake_tts), '英文界面：费率说明')
  must(has(en.srv.voice.narrator) && !!container.querySelector('select[aria-label="Voice for Narrator"]'),
    '英文界面：旁白名与音色选择框的无障碍名')
  must(has('假男声'), '音色名是专有名，不翻译')
  // 未标说话人（空 key）：英文界面显示 (no speaker)
  voicesInfo.speakers.push({ key: '', name: { code: 'voice.unlabeled', params: {} }, hint: null, voice: null, chosen: null })
  await click(button(en.compose.panel.refresh))
  must(has(en.srv.voice.unlabeled) && !has(zh.srv.voice.unlabeled), '英文界面：未标说话人')
  voicesInfo.speakers.pop()
  // 读取失败的几种错误（预览、音色表、成片文件）存原始对象，切语言跟着变
  const gone = { code: 'film.file.not_found', params: {}, message: zh.srv.film.file.not_found }
  voicesDown = gone
  await click(button(en.compose.panel.refresh))
  must(has(en.srv.film.file.not_found) && !has(zh.srv.film.file.not_found), '音色表错误（英文）')
  await lang('zh')
  must(has(zh.srv.film.file.not_found), '音色表错误切回中文跟着变')
  voicesDown = false
  await lang('zh')
  preview.final = { state: 'done', step: '完成', files: FILES, report: 'final/mix_report.json', error: null,
                    detail: null, draft: true, finished_at: '2026-10-31T04:06:00+00:00', stale: false }
  filesDown = gone
  await refresh()
  await click(button('播放 / 下载'))
  await settle()
  must(has('读取成片文件失败：' + zh.srv.film.file.not_found), '成片读取失败（中文）')
  await lang('en')
  must(has(en.compose.readFinalFailed.replace('{error}', en.srv.film.file.not_found)), '成片读取失败切英文跟着变')
  filesDown = false
  composeDown = gone
  await lang('zh')
  await click(tab('资产')!)
  await click(tab('出片')!)
  await settle()
  await lang('en')
  must(has(en.srv.film.file.not_found), '预览错误（英文）')
  await lang('zh')
  must(has(zh.srv.film.file.not_found) && !has(en.srv.film.file.not_found), '预览错误切回中文跟着变')
  composeDown = false
  await click(button('重试'))
  await lang('zh')
  nextPostFail = { status: 422, detail: { code: 'tts.volc.no_key', params: {}, message: zh.srv.tts.volc.no_key } }
  await click(composeBtn())
  await click(button('确认合成'))
  must(has(zh.srv.tts.volc.no_key) && !has(en.srv.tts.volc.no_key), '操作报错（中文）')
  await lang('en')
  must(has(en.srv.tts.volc.no_key) && !has(zh.srv.tts.volc.no_key), '切英文：已显示的错误跟着变')
  console.log('19. 费率说明、旁白名、音色错误按界面语言渲染 ✓')

  // 20. 合成进度、失败原因、报告按界面语言渲染；旧数据（只有字符串）原样显示
  must(!zh.compose.ffmpegHint.includes('brew') && !en.compose.ffmpegHint.includes('brew'), 'ffmpeg 提示不写安装命令')
  await lang('zh')
  const base = { files: [], report: null, error: null, detail: null, draft: true, stale: false }
  // 运行中：有 step_msg 按语言，只有 step（旧数据）原样
  preview.final = { ...base, state: 'running', step: '混音 E01',
                    step_msg: { code: 'compose.step.mix', params: { id: 'E01' } } }
  await refresh()
  must(has('混音 E01'), '运行中（中文）')
  await lang('en')
  must(has(en.srv.compose.step.mix.replace('{id}', 'E01')) && !has('混音 E01'), '运行中切英文跟着变')
  preview.final = { ...base, state: 'running', step: '旧步骤原文' }
  await click(button(en.compose.panel.refresh))
  must(has('旧步骤原文'), '旧数据只有 step：原样显示')
  // 失败：error_msg 优先，旧数据显示 error
  preview.final = { ...base, state: 'failed', error: '混音 E01 失败（ffmpeg 退出码 1）', detail: null,
                    error_msg: { code: 'compose.crashed', params: {} } }
  await click(button(en.compose.panel.refresh))
  must(has(en.srv.compose.crashed) && !has('混音 E01 失败'), '失败原因（英文，error_msg 优先）')
  await lang('zh')
  must(has(zh.srv.compose.crashed), '失败原因切回中文')
  preview.final = { ...base, state: 'failed', error: '老会话的失败原因', detail: null }
  await refresh()
  must(has('老会话的失败原因'), '旧数据只有 error：原样显示')
  // 报告：alignment / warning 为对象时按语言，字符串（旧报告）原样
  preview.final = { ...base, state: 'done', files: FILES, report: 'final/mix_report.json',
                    finished_at: '2026-10-31T04:06:00+00:00' }
  preview.report = { ...REPORT, alignment: { code: 'compose.alignment', params: {} },
                     warning: { code: 'compose.warning_native', params: {} } }
  await refresh()
  await lang('en')
  must(has(en.srv.compose.alignment) && has(en.srv.compose.warning_native) && !has(zh.srv.compose.alignment),
    '报告（对象）英文渲染')
  preview.report = { ...REPORT, alignment: '旧报告的对齐说明', warning: '旧报告的提醒' }
  await click(button(en.compose.panel.refresh))
  must(has('旧报告的对齐说明') && has('旧报告的提醒'), '报告（字符串）原样')
  preview.report = REPORT
  console.log('20. 合成进度、失败原因、报告按界面语言渲染，旧数据原样 ✓')
}

await act(async () => { root.unmount() })
console.log('\nALL PASS')
