/** 书架与新建：底层零件（风格色块与前缀、状态标签）。跑法：npm test */
import { Window } from 'happy-dom'

const win = new Window({ url: 'http://localhost:5173' })
const g = globalThis as Record<string, unknown>
for (const k of ['window', 'document', 'navigator', 'location', 'HTMLElement', 'Element', 'Node', 'Event',
                 'CustomEvent', 'KeyboardEvent', 'MouseEvent', 'PointerEvent', 'getComputedStyle',
                 'localStorage', 'sessionStorage', 'matchMedia', 'ResizeObserver', 'DOMRect', 'MutationObserver']) {
  Object.defineProperty(g, k, {
    value: (win as unknown as Record<string, unknown>)[k], writable: true, configurable: true,
  })
}
g.IS_REACT_ACT_ENVIRONMENT = true

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }
const { act, createElement: h } = await import('react')
const { createRoot } = await import('react-dom/client')
const { ART_STYLES } = await import('../src/presets')
const { STYLE_LOOKS, lookOf, prefixTouched, swatchFor } = await import('../src/styleLook')
const { DEFAULT_PARAMS } = await import('../src/components/ParamsForm')
const { StatusPill } = await import('../src/components/common/StatusPill')

const container = win.document.createElement('div')
win.document.body.appendChild(container)
const root = createRoot(container as unknown as HTMLElement)

must(ART_STYLES.every((a) => STYLE_LOOKS.some((s) => s.id === a.value)), 'STYLE_LOOKS 没覆盖全部画风')
must(lookOf('realistic')?.prefix.value === DEFAULT_PARAMS.style_prefix, '写实的前缀应等于默认风格前缀')
must(prefixTouched(DEFAULT_PARAMS.style_prefix) === false, '默认前缀不算手改')
must(prefixTouched('自己写的') === true, '自写前缀算手改')
must(swatchFor('n1') === swatchFor('n1'), '色块要稳定')

await act(async () => { root.render(h(StatusPill, { tone: 'live' }, '生成中')) })
const pill = win.document.querySelector('[data-tone="live"]')
must(!!pill && pill.textContent === '生成中', '状态标签应渲染出文字')

await act(async () => { root.unmount() })
console.log('\nALL PASS')
