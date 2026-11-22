/** 后台「内容拦截」页：列表、按状态筛选、按编号查找、放行（二次确认、模型拒答不可放行）、错误页按编号查不到时转查拦截记录。
 *  用桩后端代替 /admin 接口。跑法：npm test */
import { Window } from 'happy-dom'

const win = new Window({ url: 'http://localhost:5173' })
const g = globalThis as Record<string, unknown>
for (const k of ['window', 'document', 'navigator', 'location', 'HTMLElement',
                 'Element', 'Node', 'Event', 'CustomEvent', 'KeyboardEvent', 'getComputedStyle',
                 'localStorage', 'sessionStorage', 'PointerEvent', 'MouseEvent', 'matchMedia', 'ResizeObserver',
                 'DOMRect', 'MutationObserver']) {
  Object.defineProperty(g, k, {
    value: (win as unknown as Record<string, unknown>)[k], writable: true, configurable: true,
  })
}
g.IS_REACT_ACT_ENVIRONMENT = true
g.requestAnimationFrame = (cb: (t: number) => void) => setTimeout(() => cb(performance.now()), 16) as unknown as number
g.cancelAnimationFrame = (id: number) => clearTimeout(id)

const at = new Date().toISOString()
const block = (id: string, extra: Record<string, unknown>) => ({
  id, at, last_at: at, hits: 1, user_id: 'u-bob', username: 'bob', novel_id: 'n1', novel_title: '药',
  chapter_id: 'c1', chapter_title: '第一章', version_id: 'v1', clip_id: null, stage: 'convert', category: 'sexual',
  reason: '露骨描写', reason_code: null, excerpt: '摘录甲', status: 'blocked', released_by: null, released_at: null,
  releasable: true, ...extra })
let blocks = [
  block('BLOCK001', {}),
  block('BLOCK002', { stage: 'video', clip_id: 'E01-C02', category: 'drugs', reason: '', reason_code: 'safety.reason.blocklist',
                      excerpt: '摘录乙', hits: 3 }),
  block('BLOCK003', { category: 'unspecified', reason: '', reason_code: 'safety.reason.model_refused', excerpt: '摘录丙',
                      releasable: false }),
]
const calls: string[] = []
g.fetch = async (url: string, init?: { method?: string }) => {
  const path = String(url).replace(/^\/api/, '')
  const method = init?.method ?? 'GET'
  calls.push(`${method} ${path}`)
  const json = (data: unknown) => ({ ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(data)),
                                     text: async () => JSON.stringify(data) })
  const err = (status: number, detail: unknown) => ({
    ok: false, status, text: async () => JSON.stringify({ detail }), json: async () => ({ detail }) })
  if (path.startsWith('/admin/safety/blocks') && method === 'GET') {
    const q = new URL('http://x' + path).searchParams
    return json({ blocks: blocks.filter((b) => (!q.get('status') || b.status === q.get('status'))
      && (!q.get('ref') || b.id === q.get('ref')!.toUpperCase())) })
  }
  const rel = /^\/admin\/safety\/blocks\/(\w+)\/release$/.exec(path)
  if (rel && method === 'POST') {
    blocks = blocks.map((b) => (b.id === rel[1] ? { ...b, status: 'released', released_by: 'root', released_at: at } : b))
    return json(blocks.find((b) => b.id === rel[1]))
  }
  if (path === '/admin/errors') return json({ errors: [] })
  if (path.startsWith('/admin/errors/')) {
    return err(404, { code: 'admin.error_ref.not_found', params: { ref: path.split('/').pop() }, message: '没有这个参考编号' })
  }
  throw new Error(`桩后端未实现的路径: ${method} ${path}`)
}

await import('../src/components/admin/i18n')
const { act } = await import('react')
const { createRoot } = await import('react-dom/client')
import type { ReactNode } from 'react'

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }
const container = win.document.createElement('div')
win.document.body.appendChild(container)
let root = createRoot(container as unknown as HTMLElement)
const settle = async (ms = 30) => { await act(async () => { await new Promise((r) => setTimeout(r, ms)) }) }
const text = () => container.textContent ?? ''
const byId = (id: string) => container.querySelector(`[data-testid="${id}"]`)
const click = async (el: unknown) => {
  await act(async () => {
    (el as EventTarget).dispatchEvent(new win.MouseEvent('click', { bubbles: true, cancelable: true }) as unknown as Event)
  })
  await settle()
}
const type = async (el: unknown, value: string) => {
  await act(async () => {
    const input = el as HTMLInputElement
    Object.getOwnPropertyDescriptor(win.HTMLInputElement.prototype, 'value')!.set!.call(input, value)
    input.dispatchEvent(new win.Event('input', { bubbles: true }) as unknown as Event)
  })
}
const submit = async (form: unknown) => {
  await act(async () => {
    (form as EventTarget).dispatchEvent(new win.Event('submit', { bubbles: true, cancelable: true }) as unknown as Event)
  })
  await settle()
}
const remount = async (node: ReactNode) => {
  await act(async () => { root.unmount() })
  root = createRoot(container as unknown as HTMLElement)
  await act(async () => { root.render(node) })
  await settle()
}

const { AdminNavContext } = await import('../src/components/admin/navContext')
const { SafetyTab } = await import('../src/components/admin/SafetyTab')
const nav: string[] = []
const wrap = (node: ReactNode) => (
  <AdminNavContext.Provider value={(to) => { nav.push(to) }}>{node}</AdminNavContext.Provider>)

// 1. 列表：缺省只看未放行；类别、理由、阶段、位置、次数、摘录都按文案显示
{
  await remount(wrap(<SafetyTab />))
  must(container.querySelector('h2')!.textContent === '内容拦截', '页名')
  must(calls.includes('GET /admin/safety/blocks?status=blocked'), `缺省筛未放行，实为 ${calls}`)
  const r1 = byId('safety-row-BLOCK001')!.textContent!
  must(['bob', '药', '第一章', '转换', '色情', '露骨描写', '摘录甲', 'BLOCK001'].every((s) => r1.includes(s)), `第一行，实为 ${r1}`)
  const r2 = byId('safety-row-BLOCK002')!.textContent!
  must(['出片', 'E01-C02', '毒品', '命中词表', '3'].every((s) => r2.includes(s)), `第二行，实为 ${r2}`)
  const r3 = byId('safety-row-BLOCK003')!
  must(r3.textContent!.includes('模型服务拒绝，放行无效') && !r3.querySelector('button'), '模型拒答：没有放行按钮，写明原因')
  must(text().includes('放行后需用户重新发起转换或出片'), '放行说明')
  console.log('1. 列表 ✓')
}

// 2. 放行要二次确认：第一次点只出现确认与取消；取消不发请求；确认后发请求并刷新
{
  const row = () => byId('safety-row-BLOCK001')!
  const btn = (label: string) => [...row().querySelectorAll('button')].find((b) => b.textContent!.trim() === label)
  await click(btn('放行'))
  must(!!btn('确认放行') && !!btn('取消') && !calls.some((c) => c.startsWith('POST')), '第一次点不发请求')
  await click(btn('取消'))
  must(!!btn('放行') && !calls.some((c) => c.startsWith('POST')), '取消回到原状')
  await click(btn('放行'))
  await click(btn('确认放行'))
  must(calls.includes('POST /admin/safety/blocks/BLOCK001/release'), '确认后发放行请求')
  must(!byId('safety-row-BLOCK001'), '放行后不再出现在未放行列表里')
  console.log('2. 放行 ✓')
}

// 3. 筛选：切到「已放行」「全部」；按编号查找
{
  const select = byId('safety-status') as unknown as HTMLSelectElement
  await act(async () => {
    select.value = 'released'
    select.dispatchEvent(new win.Event('change', { bubbles: true }) as unknown as Event)
  })
  await settle()
  must(calls.includes('GET /admin/safety/blocks?status=released') && !!byId('safety-row-BLOCK001')
       && byId('safety-row-BLOCK001')!.textContent!.includes('已放行'), '已放行列表')
  await type(container.querySelector('input')!, 'block002')
  await submit(container.querySelector('form')!)
  must(calls.includes('GET /admin/safety/blocks?ref=block002') && !!byId('safety-row-BLOCK002')
       && !byId('safety-row-BLOCK001'), `按编号查找，实为 ${calls.slice(-2)}`)
  console.log('3. 筛选与查找 ✓')
}

// 4. 错误页：编号在错误记录里查不到时转查拦截记录，找到就给出去内容拦截页的链接
{
  const { ErrorsTab } = await import('../src/components/admin/ErrorsTab')
  await remount(wrap(<ErrorsTab />))
  await type(container.querySelector('input')!, 'BLOCK002')
  await submit(container.querySelector('form')!)
  must(calls.includes('GET /admin/errors/BLOCK002') && calls.includes('GET /admin/safety/blocks?ref=BLOCK002'), '先查错误再查拦截')
  const hit = byId('errors-safety-hit')!
  must(hit.textContent!.includes('这是内容拦截记录') && hit.querySelector('a')!.getAttribute('href') === '/admin/safety',
    `命中提示，实为 ${hit.textContent}`)
  await type(container.querySelector('input')!, 'NOPE0000')
  await submit(container.querySelector('form')!)
  must(!byId('errors-safety-hit') && !!container.querySelector('[role="alert"]'), '两边都没有：照旧报找不到')
  console.log('4. 错误页转查 ✓')
}

await act(async () => { root.unmount() })
console.log('\nALL PASS')
