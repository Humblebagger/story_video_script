/** 助手：SSE 解析、极简渲染、位置与跳转存储；面板交互（Task 6 追加）。跑法：npm test */
import { parseSse } from '../src/lib/sse'
import { getWhere, onStepRequest, requestStep, setWhere, takeStep } from '../src/lib/assistantBridge'

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }

// ---------- SSE ----------
{
  const a = parseSse('event: token\ndata: {"text":"你"}\n\nevent: tok')
  must(a.events.length === 1 && a.events[0].event === 'token', '一条完整事件')
  must(a.rest === 'event: tok', '半截留到下次')
  const b = parseSse(a.rest + 'en\ndata: {"text":"好"}\n\nevent: done\ndata: {}\n\n')
  must(b.events.map((e) => e.event).join() === 'token,done' && b.rest === '', '拼上后两条')
  must(parseSse('event: x\ndata: {坏\n\n').events.length === 0, '坏 JSON 跳过')
  must(parseSse('event: token\r\ndata: {"text":"a"}\r\n\r\n').events.length === 1, 'CRLF')
  console.log('✓ SSE 解析')
}

// ---------- 位置与跳转 ----------
{
  setWhere({ chapter_id: 'c1', step: 'review' })
  must(getWhere().chapter_id === 'c1' && getWhere().step === 'review', '位置')
  let hits = 0
  const off = onStepRequest(() => { hits++ })
  requestStep('c2', 'render')
  must(hits === 1, '通知订阅者')
  must(takeStep('c1') === null, '别的章取不到')
  must(takeStep('c2') === 'render' && takeStep('c2') === null, '只取一次')
  off()
  console.log('✓ 位置与跳转')
}

// ---------- 极简渲染 ----------
const { Window } = await import('happy-dom')
const win = new Window({ url: 'http://localhost:5173' })
const g = globalThis as Record<string, unknown>
for (const k of ['window', 'document', 'navigator', 'location', 'HTMLElement', 'Element', 'Node', 'Event',
                 'CustomEvent', 'KeyboardEvent', 'MouseEvent', 'PointerEvent', 'getComputedStyle',
                 'localStorage', 'sessionStorage', 'matchMedia', 'ResizeObserver', 'DOMRect', 'MutationObserver', 'NodeFilter']) {
  Object.defineProperty(g, k, { value: (win as unknown as Record<string, unknown>)[k], writable: true, configurable: true })
}
g.IS_REACT_ACT_ENVIRONMENT = true
g.requestAnimationFrame ??= (cb: (t: number) => void) => setTimeout(() => cb(Date.now()), 16)
g.cancelAnimationFrame ??= (id: number) => clearTimeout(id)
const { act, createElement: h } = await import('react')
const { createRoot } = await import('react-dom/client')
const { MiniMd } = await import('../src/lib/miniMd')
const doc = win.document
const box = doc.createElement('div')
doc.body.appendChild(box)
{
  const root = createRoot(box as unknown as HTMLElement)
  await act(async () => { root.render(h(MiniMd, { text: '结论：**两段**没出\n- SH004\n- SH007\n1. 先出片\n2. 再合成\n<b>x</b>' })) })
  must(box.querySelector('strong')?.textContent === '两段', '加粗')
  must(box.querySelectorAll('ul li').length === 2 && box.querySelectorAll('ol li').length === 2, '两种列表')
  must(!box.querySelector('b') && (box.textContent ?? '').includes('<b>x</b>'), '不解析 HTML')
  await act(async () => { root.unmount() })
  console.log('✓ 极简渲染')
}

console.log('assistant: ALL PASS')
