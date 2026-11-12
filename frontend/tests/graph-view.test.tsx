/** 节点图视图的界面回归（组件：NodeGraph）。目前覆盖 Esc：没选中时放行给画布关闭，选中后第一下只取消选中。
 *  跑法：npm test */
import { Window } from 'happy-dom'

const win = new Window({ url: 'http://localhost:5173' })
const g = globalThis as Record<string, unknown>
for (const k of ['window', 'document', 'navigator', 'location', 'HTMLElement', 'Element', 'Node', 'Event',
                 'CustomEvent', 'KeyboardEvent', 'getComputedStyle', 'localStorage', 'sessionStorage',
                 'PointerEvent', 'MouseEvent', 'matchMedia', 'ResizeObserver', 'DOMRect', 'MutationObserver']) {
  Object.defineProperty(g, k, { value: (win as unknown as Record<string, unknown>)[k], writable: true, configurable: true })
}
g.IS_REACT_ACT_ENVIRONMENT = true

const { act } = await import('react')
const { createRoot } = await import('react-dom/client')
const { NodeGraph } = await import('../src/components/NodeGraph')
import type { Film } from '../src/useFilm'
import type { FilmSession, Storyboard } from '../src/types'

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }

const session = {
  provider: 'fake', model: 'fake-1', resolution: '720p', audio_mode: 'tts_all', budget_cny: 200,
  confirm_over_cny: 20, spent_cny: 0, free: [], orphaned: [], counts: {}, reserved_cny: 0, uncertain_count: 0,
  remaining_cny: 0,
  clips: [{
    id: 'E01-C1', episode: 'E01', shots: ['s1'], duration: 5, truncated: false, prompt: 'p', refs: [],
    dropped_refs: [], missing_refs: [], first_frame: null, frame_mode: null, fingerprint: 'fp', estimate_cny: 5,
    attempts: [], chosen: null, mute_native: false, uncertain: false, error: null, state: 'planned',
  }],
  options: { providers: ['fake'], models: {}, resolutions: ['720p'], cny_per_sec: {}, max_clip_sec: 10,
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

console.log('graph-view: ALL PASS')
