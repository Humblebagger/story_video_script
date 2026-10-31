/** 章节工作流组件：步骤条（打勾、灰步说明与直达）、主按钮（动作金额、原因与去修复）、未保存提示条、定位高亮。跑法：npm test */
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
g.IntersectionObserver ??= class { observe() {} unobserve() {} disconnect() {} takeRecords() { return [] } }
g.requestAnimationFrame ??= (cb: (t: number) => void) => setTimeout(() => cb(Date.now()), 16)
g.cancelAnimationFrame ??= (id: number) => clearTimeout(id)

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }
const { act } = await import('react')
const { createRoot } = await import('react-dom/client')
const { I18nProvider } = await import('../src/i18n')
const { Stepper } = await import('../src/components/workflow/Stepper')
const { PrimaryBar } = await import('../src/components/workflow/PrimaryBar')
const { UnsavedBar } = await import('../src/components/workflow/UnsavedBar')
const { flashTarget } = await import('../src/lib/flash')
const { primaryFor, stepStates } = await import('../src/workflow')
import type { FlowInput, StepId, Fix } from '../src/workflow'
import type { FilmClip, FilmSession, VersionSummary } from '../src/types'

const container = win.document.createElement('div')
win.document.body.appendChild(container)
const root = createRoot(container as unknown as HTMLElement)
const settle = async (ms = 40) => { await act(async () => { await new Promise((r) => setTimeout(r, ms)) }) }
const click = async (el: Element | null | undefined) => {
  if (!el) throw new Error('✗ 元素不存在')
  await act(async () => { el.dispatchEvent(new win.MouseEvent('click', { bubbles: true }) as unknown as Event) })
  await settle()
}
const q = (s: string) => win.document.querySelector(s)
const qa = (s: string) => [...win.document.querySelectorAll(s)]
const text = () => win.document.body.textContent ?? ''
const render = async (node: React.ReactNode) => {
  await act(async () => { root.render(<I18nProvider initial="zh">{node}</I18nProvider>) })
  await settle()
}

const ver = { id: 'v1', created_at: null, edited_at: null, status: 'succeeded', units: 10, episodes: 1, shots: 12,
  has_quality_report: false } as VersionSummary
const clip = (id: string) => ({ id, state: 'planned', shots: [id], duration: 5, estimate_cny: 2.5, attempts: [],
  chosen: null, missing_refs: [], dropped_refs: [], truncated: false, uncertain: false }) as unknown as FilmClip
const film = { clips: [clip('c1'), clip('c2')], remaining_cny: 5, final: null } as unknown as FilmSession
const base: FlowInput = {
  hasText: true, textDirty: false, converting: false, version: ver, dirty: false,
  verificationFailed: false, film: null, finalStale: false, compose: null,
}

// 1. 步骤条
const viewed: StepId[] = []
await render(<Stepper states={stepStates(base)} view="render" onView={(id) => viewed.push(id)} />)
const items = qa('[data-step]')
must(items.length === 6, '六个步骤')
for (const b of items.slice(0, 3)) must(!!b.querySelector('svg') && !/\d/.test(b.textContent ?? ''), '前三步打勾、不显示数字')
await click(q('[data-step="compose"]'))
must(viewed.length === 0, '点灰步不切换')
must((q('[data-testid="step-hint"]')?.textContent ?? '').includes('需要先完成第 4 步'), '说明要先完成第 4 步')
await click(qa('[data-testid="step-hint"] button')[0])
must(viewed.join() === 'render', '点「去第 4 步」切到出片')
await click(q('[data-step="review"]'))
must(viewed.join() === 'render,review', '点已完成的步骤可回看')
console.log('1. Stepper ✓')

// 2. 主按钮
let ran = 0
const fixed: Fix[] = []
await render(<PrimaryBar primary={primaryFor('render', { ...base, film })} onRun={() => { ran++ }} onFix={(f) => fixed.push(f)} />)
const act1 = q('[data-testid="primary-action"]') as HTMLButtonElement
must((act1.textContent ?? '').includes('先试一段（约 ¥2.50）') && !act1.disabled, '先试一段、可点')
await click(act1)
must(ran === 1, '点击调 onRun')
await render(<PrimaryBar primary={primaryFor('review', { ...base, verificationFailed: true })} onRun={() => { ran++ }}
                         onFix={(f) => fixed.push(f)} />)
must((q('[data-testid="primary-reason"]')?.textContent ?? '').includes('完整性检查没通过'), '显示原因')
must((q('[data-testid="primary-action"]') as HTMLButtonElement).disabled, '主按钮禁用')
await click(q('[data-testid="primary-fix"]'))
must(fixed.length === 1 && fixed[0].step === 'review' && fixed[0].target === 'verification', '去修复带目标')
await render(<PrimaryBar primary={primaryFor('download', base)} onRun={() => {}} onFix={() => {}} />)
must(!q('[data-testid="primary-action"]'), '⑥ 不渲染')
console.log('2. PrimaryBar ✓')

// 3. 未保存提示条
let saved = 0, undone = 0
await render(<UnsavedBar show saving={false} onSave={() => { saved++ }} onUndo={() => { undone++ }} />)
must(text().includes('有未保存的修改'), '显示提示')
const btns = qa('[data-testid="unsaved-bar"] button')
await click(btns.find((b) => b.textContent === '保存'))
await click(btns.find((b) => b.textContent === '撤销'))
must(saved === 1 && undone === 1, '保存、撤销各一次')
await render(<UnsavedBar show={false} saving={false} onSave={() => {}} onUndo={() => {}} />)
await settle(300)
must(!q('[data-testid="unsaved-bar"]'), 'show 为假时消失')
console.log('3. UnsavedBar ✓')

// 4. 定位高亮
const target = win.document.createElement('div')
target.id = 'x'
win.document.body.appendChild(target)
flashTarget('x')
must(target.classList.contains('fix-flash'), '加上高亮')
await new Promise((r) => setTimeout(r, 1600))
must(!target.classList.contains('fix-flash'), '1.5 秒后去掉')
console.log('4. flashTarget ✓')

console.log('\nALL PASS')
process.exit(0)
