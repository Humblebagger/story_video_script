/** 拉片表的界面回归：每镜一行、按集分组；各列文字；视频提示词按片段合并单元格；
 *  无关键帧与无出片规划的占位；提示词展开 / 收起；点行跳转；中英文。
 *  分组与合并的纯计算由 shot-sheet.test.ts 覆盖。跑法：npm test
 */
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

import type { FilmClip, FilmSession, Shot, Storyboard } from '../src/types'

/* ---------- 夹具：两集六镜，E01 的前三镜有出片规划 ---------- */
const shot = (id: string, over: Partial<Shot> = {}): Shot => ({
  id, duration_sec: 3, shot_size: 'medium', action: `${id} 的画面`,
  source: { unit_refs: [], derivation: 'explicit' }, ...over,
})
const doc = {
  meta: { schema_version: '0.5', title: '药', fidelity_mode: 'faithful', style: { style_prefix: '' },
          video: { aspect_ratio: '16:9' }, narration: { mode: 'narrated' } },
  source: { work_title: '药', units: [] },
  assets: { characters: [{ id: 'C01', name: '老栓' }, { id: 'C02', name: '华大妈' }] },
  episodes: [
    { id: 'E01', title: '黎明', shots: [
      shot('E01-SH001', { duration_sec: 5, shot_size: 'extreme_wide', camera: { movement: 'static', angle: 'high' },
                          action: '乌蓝的天色下，丁字街空无一人', atmosphere: '万籁俱寂',
                          narration: { text: '秋天的后半夜，月亮下去了' } }),
      shot('E01-SH002', { duration_sec: 3.5, shot_size: 'close_up', camera: { movement: 'push_in', angle: 'low' },
                          action: '老栓接过洋钱',
                          dialogue: [{ type: 'dialogue', text: '小栓的爹，你就去么？', character_ref: 'C02' },
                                     { type: 'inner_monologue', text: '这给谁治病的呀', character_ref: 'C01' }] }),
      shot('E01-SH003', { duration_sec: 4, action: '老栓走上大街' }),
      shot('E01-SH004', { duration_sec: 2, shot_size: 'wide', camera: { movement: 'pan' }, action: '街上黑沉沉的' }),
    ] },
    { id: 'E02', shots: [
      shot('E02-SH001', { duration_sec: 6, shot_size: 'full', camera: { movement: 'track', angle: 'eye_level' } }),
      shot('E02-SH002', { shot_size: 'insert', camera: { movement: 'static' } }),
    ] },
  ],
} as unknown as Storyboard

const LONG = '大远景，俯拍，固定机位。乌蓝的天色下，丁字街空无一人，屋脊只剩剪影；'
  + '随后切到特写，仰拍，缓慢推近：老栓接过洋钱，抖抖地装进衣袋，又在外面按了两下。'
const clip = (id: string, shots: string[], over: Partial<FilmClip> = {}): FilmClip => ({
  id, episode: 'E01', shots, duration: 8, truncated: false, prompt: 'p', refs: [], dropped_refs: [],
  missing_refs: [], first_frame: null, frame_mode: null, fingerprint: 'fp', estimate_cny: 8,
  attempts: [], chosen: null, mute_native: false, uncertain: false, error: null, state: 'planned', ...over,
})
const film = {
  provider: 'fake', model: 'fake-1', resolution: '720p', audio_mode: 'tts_all', budget_cny: 200,
  confirm_over_cny: 20, spent_cny: 0, orphaned: [], counts: {}, reserved_cny: 0, uncertain_count: 0, remaining_cny: 0,
  clips: [
    clip('E01-C01', ['E01-SH001', 'E01-SH002'], { duration: 8.5, prompt: LONG }),
    clip('E01-C02', ['E01-SH003'], { duration: 4, prompt: '中景，老栓走上大街' }),
  ],
  options: { providers: ['fake'], models: { 'fake-1': { label: '假厂商' } }, resolutions: ['720p'], cny_per_sec: {},
             max_clip_sec: 10, max_refs: 3, audio_modes: ['tts_all'], rate_note: '假厂商：不联网、不花钱' },
} as unknown as FilmSession

/* ---------- 桩后端：只有 E01-SH001 有关键帧 ---------- */
const K = '/novels/n1/chapters/c1/versions/v1/keyframes'
g.fetch = async (url: string) => {
  const path = String(url).replace(/^\/api/, '')
  if (path === K) return { ok: true, status: 200, json: async () => ({ shots: ['E01-SH001'] }) }
  if (path === `${K}/E01-SH001`) {
    return { ok: true, status: 200, blob: async () => new Blob(['x'], { type: 'image/png' }) }
  }
  throw new Error(`桩后端未实现的路径: ${path}`)
}
const version = { nid: 'n1', cid: 'c1', vid: 'v1' }

const { act } = await import('react')
const { createRoot } = await import('react-dom/client')
const { I18nProvider } = await import('../src/i18n')
const { setCurrentLocale } = await import('../src/i18n/core')
const { buildIndex } = await import('../src/resolve')
const { ShotSheet } = await import('../src/components/ShotSheet')

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }
const container = win.document.createElement('div')
win.document.body.appendChild(container)
const root = createRoot(container as unknown as HTMLElement)
const settle = async (ms = 50) => {
  await act(async () => { await new Promise((r) => setTimeout(r, ms)) })
}
const click = async (el: Element) => {
  await act(async () => {
    el.dispatchEvent(new win.MouseEvent('click', { bubbles: true }) as unknown as Event)
  })
  await settle()
}
const qa = (sel: string) => [...container.querySelectorAll(sel)] as unknown as HTMLElement[]
const row = (id: string) => {
  const el = container.querySelector(`tr[data-shot="${id}"]`)
  if (!el) throw new Error(`✗ 拉片表里找不到 ${id}`)
  return el as unknown as HTMLElement
}
/** 这一行第 i 个单元格的文字（0 镜号、1 关键帧、2 景别、3 运镜、4 画面、5 台词、6 提示词） */
const cell = (id: string, i: number) => row(id).querySelectorAll('td')[i]?.textContent ?? ''
const promptCell = (id: string) => row(id).querySelector('td.sheet__promptcell') as unknown as HTMLElement | null

const idx = buildIndex(doc)
const jumps: string[] = []
const sheet = (f: FilmSession | null, v: typeof version | null = version) =>
  <ShotSheet doc={doc} idx={idx} film={f} version={v} imagesKey={0} onJump={(id) => jumps.push(id)} />

// 1. 行数与分组：每镜一行，每集一个标题行（集号、标题、镜头数）
await act(async () => { root.render(sheet(film)) })
await settle()
must(qa('tr[data-shot]').length === 6, `每镜一行：${qa('tr[data-shot]').length}`)
must(qa('tr[data-shot]').map((r) => r.getAttribute('data-shot')).join() ===
     'E01-SH001,E01-SH002,E01-SH003,E01-SH004,E02-SH001,E02-SH002', '行按分镜顺序')
const eps = qa('tr.sheet__ep').map((r) => r.textContent ?? '')
must(eps.length === 2 && eps[0].includes('E01') && eps[0].includes('黎明') && eps[0].includes('4 镜')
     && eps[1].includes('E02') && eps[1].includes('2 镜'), `集标题行：${eps.join(' | ')}`)
must(qa('tbody').length === 2 && qa('tbody')[0].querySelectorAll('tr[data-shot]').length === 4, '每集一个 tbody')
must(qa('thead th').map((x) => x.textContent).join('|') === '镜号|关键帧|景别|运镜 / 角度|画面|台词 / 旁白|视频提示词', '七列表头')
must(container.querySelector('.sheet__wrap')?.getAttribute('aria-label') === '拉片表', '滚动容器有名字')
console.log('1. 行数与分组 ✓')

// 2. 各列文字
must(cell('E01-SH001', 0).includes('E01-SH001') && cell('E01-SH001', 0).includes('5s'), '镜号与时长')
must(cell('E01-SH002', 0).includes('3.5s'), '时长保留一位小数')
must(cell('E01-SH001', 2) === '大远景' && cell('E01-SH001', 3) === '固定 / 俯拍', '景别与运镜 / 角度')
must(cell('E01-SH002', 2) === '特写' && cell('E01-SH002', 3) === '推 / 仰拍', '推 / 仰拍')
must(cell('E01-SH003', 3) === '—' && cell('E01-SH004', 3) === '摇', '没有运镜显示 —，只有运镜只写运镜')
must(cell('E01-SH001', 4).includes('乌蓝的天色下，丁字街空无一人') && cell('E01-SH001', 4).includes('万籁俱寂'), '画面与氛围')
must(!row('E01-SH003').querySelector('.sheet__atmo'), '没有氛围不显示小字')
must(cell('E01-SH001', 5).includes('旁白') && cell('E01-SH001', 5).includes('秋天的后半夜，月亮下去了'), '旁白')
must(cell('E01-SH002', 5).includes('华大妈') && cell('E01-SH002', 5).includes('小栓的爹，你就去么？')
     && cell('E01-SH002', 5).includes('老栓') && cell('E01-SH002', 5).includes('内心独白'), '台词带说话人与类型')
must(row('E01-SH002').querySelectorAll('.chip').length === 1, '普通台词不带类型标签')
must(cell('E01-SH003', 5) === '—', '没有台词与旁白显示 —')
console.log('2. 各列文字 ✓')

// 3. 视频提示词：同段相邻的镜头合并；未规划占位；不出现模型与厂商名
must(promptCell('E01-SH001')?.getAttribute('rowspan') === '2', '同段两镜合并成一格')
must(promptCell('E01-SH002') === null, '被合并的行没有提示词格')
must((promptCell('E01-SH001')?.textContent ?? '').includes('E01-C01 · 8.5s')
     && (promptCell('E01-SH001')?.textContent ?? '').includes(LONG), '提示词格有片段号、时长与提示词')
must(promptCell('E01-SH003')?.getAttribute('rowspan') === '1'
     && (promptCell('E01-SH003')?.textContent ?? '').includes('中景，老栓走上大街'), '单镜的段')
must(promptCell('E01-SH004')?.textContent === '未规划', '不在任何段里的镜头显示未规划')
must(promptCell('E02-SH001')?.getAttribute('rowspan') === '2' && promptCell('E02-SH001')?.textContent === '未规划'
     && promptCell('E02-SH002') === null, '整集未规划合并成一格')
must(qa('td.sheet__promptcell').length === 4, '共四个提示词格')
const text = container.textContent ?? ''
must(!text.includes('fake') && !text.includes('假厂商'), '界面不出现模型或厂商名')
console.log('3. 视频提示词合并与未规划 ✓')

// 4. 关键帧：有图的显示图，其余占位
must(!!row('E01-SH001').querySelector('img.sheet__thumb'), '有关键帧的显示缩略图')
must(qa('.sheet__thumb--empty').length === 5 && qa('.sheet__thumb--empty').every((x) => x.textContent === '无图'),
     '没有关键帧的显示「无图」')
console.log('4. 关键帧缩略图与占位 ✓')

// 5. 展开 / 收起：长提示词才有按钮；点它不跳转
must(!promptCell('E01-SH003')?.querySelector('.sheet__more'), '短提示词没有展开按钮')
const more = () => promptCell('E01-SH001')!.querySelector('.sheet__more') as unknown as HTMLButtonElement
must(more().textContent === '展开' && more().getAttribute('aria-expanded') === 'false', '长提示词有展开按钮')
await click(more())
must(promptCell('E01-SH001')!.querySelector('.sheet__prompt')!.classList.contains('is-open')
     && more().textContent === '收起' && more().getAttribute('aria-expanded') === 'true', '点开显示全文')
await click(more())
must(!promptCell('E01-SH001')!.querySelector('.sheet__prompt')!.classList.contains('is-open'), '再点收起')
await click(promptCell('E01-SH001')!)
must(jumps.length === 0, '点提示词格与展开按钮都不跳转')
console.log('5. 展开与收起 ✓')

// 6. 点行跳转：点单元格、点镜号按钮都只报一次这一镜
await click(row('E01-SH003').querySelectorAll('td')[4])
must(jumps.join() === 'E01-SH003', `点行跳到这一镜：${jumps.join()}`)
await click(row('E01-SH002').querySelector('button.sheet__id')!)
must(jumps.join() === 'E01-SH003,E01-SH002', `点镜号按钮只报一次：${jumps.join()}`)
console.log('6. 点行跳转 ✓')

// 7. 没有出片会话、没有版本：每集一格未规划，全部无图
await act(async () => { root.render(sheet(null, null)) })
await settle()
must(qa('td.sheet__promptcell').length === 2 && qa('td.sheet__promptcell').every((x) => x.textContent === '未规划'),
     '没有会话时每集一格未规划')
must(promptCell('E01-SH001')?.getAttribute('rowspan') === '4', '整集合并')
must(qa('img.sheet__thumb').length === 0 && qa('.sheet__thumb--empty').length === 6, '没有版本时全部无图')
console.log('7. 没有会话与版本 ✓')

// 8. 英文：表头、枚举、占位都是英文；镜头正文原样
await act(async () => { root.render(<I18nProvider initial="en">{sheet(film, null)}</I18nProvider>) })
await settle()
must(qa('thead th').map((x) => x.textContent).join('|')
     === 'Shot|Keyframe|Size|Movement / Angle|Action|Lines / Narration|Video prompt', '英文表头')
must(cell('E01-SH001', 2) === 'Extreme wide' && cell('E01-SH001', 3) === 'Static / High angle', '英文景别与运镜')
must(promptCell('E01-SH004')?.textContent === 'Not planned', '英文未规划')
must(qa('.sheet__thumb--empty')[0].textContent === 'No image', '英文无图')
must(more().textContent === 'Show more', '英文展开')
must(cell('E01-SH001', 5).includes('Narration') && cell('E01-SH002', 5).includes('Inner monologue'), '英文旁白与台词类型')
must((qa('tr.sheet__ep')[0].textContent ?? '').includes('Shots: 4'), '英文镜头数')
must(!/[一-鿿]/.test(container.querySelector('thead')?.textContent ?? ''), '表头无中文')
must(cell('E01-SH001', 4).includes('乌蓝的天色下'), '镜头正文原样')
await act(async () => { root.render(sheet(film, null)) })
setCurrentLocale('zh')
console.log('8. 英文 ✓')

await act(async () => { root.unmount() })
console.log('\nALL PASS')
