/** 章节工作台第一批纯逻辑：镜头拍平、检查结果归镜头、找所在出片段、过滤与上下切换、资产缩略图。跑法：npm test */
import { assetThumb } from '../src/lib/assetThumb'
import { clipForShot, filterShots, flatShots, shotIssues, stepShot } from '../src/shotFocus'
import type { FilmSession, Shot, Storyboard, VerificationReport } from '../src/types'

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }

const shot = (id: string, o: Partial<Shot> = {}) =>
  ({ id, duration_sec: 3, shot_size: 'medium', action: `${id} 的画面`, source: { unit_refs: [], derivation: 'explicit' }, ...o }) as Shot
const doc = {
  episodes: [
    { id: 'E01', shots: [shot('SH001'), shot('SH002', { narration: { text: '康大叔推门' } as Shot['narration'] })] },
    { id: 'E02', shots: [shot('SH003')] },
  ],
} as unknown as Storyboard

const rows = flatShots(doc)
must(rows.map((r) => r.shot.id).join() === 'SH001,SH002,SH003', '按集顺序拍平')
must(rows[2].ep === 'E02', '记下所在集')

const report = { status: 'failed', findings: [
  { rule_id: 'a', severity: 'high', object_path: '/episodes/0/shots/1/action', message: '' },
  { rule_id: 'b', severity: 'low', object_path: '/episodes/0/shots/1', message: '' },
  { rule_id: 'c', severity: 'medium', object_path: '/episodes/1/shots/0/dialogue/0', message: '' },
  { rule_id: 'd', severity: 'critical', object_path: '/source/units/3', message: '' },
] } as VerificationReport
const issues = shotIssues(report, doc)
must(issues.get('SH002') === 'hard', '同镜有硬有软按硬')
must(issues.get('SH003') === 'soft', '中低级是软问题')
must(!issues.has('SH001') && issues.size === 2, '指不到镜头的不标')
must(shotIssues(null, doc).size === 0, '没报告时为空')

const film = { clips: [
  { id: 'K1', shots: ['SH001', 'SH002'], chosen: 0, attempts: [{ file: 'clips/K1-0.mp4' }] },
  { id: 'K2', shots: ['SH003'], chosen: null, attempts: [] },
] } as unknown as FilmSession
must(clipForShot(film, 'SH002')?.file === 'clips/K1-0.mp4', '找到片段与采用的文件')
must(clipForShot(film, 'SH003')?.file === null, '没采用时文件为 null')
must(clipForShot(film, 'SH999') === null && clipForShot(null, 'SH001') === null, '找不到为 null')

must(stepShot(rows, 'SH001', 1) === 'SH002' && stepShot(rows, 'SH003', 1) === 'SH003', '下一镜到底不动')
must(stepShot(rows, 'SH001', -1) === 'SH001', '上一镜到顶不动')
must(stepShot(rows, 'SH002', 'end') === 'SH003' && stepShot(rows, 'SH002', 'home') === 'SH001', 'Home / End')
must(stepShot(rows, 'SH003', -1, new Set(['E01'])) === 'SH003', '跳过折叠的集')

must(filterShots(rows, 'sh003').length === 1, '按 ID 不分大小写')
must(filterShots(rows, '推门').map((r) => r.shot.id).join() === 'SH002', '按旁白文字')
must(filterShots(rows, '  ').length === 3, '空查询不过滤')

must(assetThumb({ id: 'C01', name: '华', reference_images: [{ uri: 'refs/a.png' }, { uri: 'https://x/a.png' }] } as never) === 'https://x/a.png', '取第一个可直接显示的')
must(assetThumb({ id: 'C01', name: '华' } as never) === null, '没有图为 null')

// ---------- 2. 镜头三栏视图 ----------
import { Window } from 'happy-dom'

const win = new Window({ url: 'http://localhost:5173' })
const g = globalThis as Record<string, unknown>
for (const k of ['window', 'document', 'navigator', 'location', 'HTMLElement', 'Element', 'Node', 'Event',
                 'CustomEvent', 'KeyboardEvent', 'MouseEvent', 'PointerEvent', 'getComputedStyle',
                 'localStorage', 'sessionStorage', 'matchMedia', 'ResizeObserver', 'DOMRect', 'MutationObserver', 'NodeFilter',
                 'CSS']) {
  Object.defineProperty(g, k, {
    value: (win as unknown as Record<string, unknown>)[k], writable: true, configurable: true,
  })
}
g.IS_REACT_ACT_ENVIRONMENT = true
g.requestAnimationFrame ??= (cb: (t: number) => void) => setTimeout(() => cb(Date.now()), 16)
g.cancelAnimationFrame ??= (id: number) => clearTimeout(id)
const gCss = g.CSS as { escape?: (s: string) => string } | undefined
if (!gCss?.escape) g.CSS = { escape: (x: string) => x }

{
  const { act, createElement: h } = await import('react')
  const { createRoot } = await import('react-dom/client')
  const { I18nProvider } = await import('../src/i18n')
  const { TooltipProvider } = await import('../src/components/ui/tooltip')
  const { ShotFocusView } = await import('../src/components/ShotFocusView')
  const { buildIndex } = await import('../src/resolve')

  const d = win.document
  const container = d.createElement('div')
  d.body.appendChild(container)
  const root = createRoot(container as unknown as HTMLElement)
  const settle = async (ms = 30) => { await act(async () => { await new Promise((r) => setTimeout(r, ms)) }) }
  const q = (sel: string) => d.querySelector(sel) as unknown as HTMLElement | null
  const qa = (sel: string) => [...d.querySelectorAll(sel)] as unknown as HTMLElement[]
  const click = async (el: HTMLElement | null) => {
    must(!!el, '要点的元素不存在')
    await act(async () => { el!.dispatchEvent(new win.MouseEvent('click', { bubbles: true }) as unknown as Event) })
    await settle()
  }
  const key = async (el: HTMLElement | null, k: string) => {
    must(!!el, '要按键的元素不存在')
    await act(async () => { el!.dispatchEvent(new win.KeyboardEvent('keydown', { key: k, bubbles: true }) as unknown as Event) })
    await settle()
  }
  const type = async (el: HTMLElement | null, v: string) => {
    must(!!el, '要输入的元素不存在')
    await act(async () => {
      const proto = (el as unknown as { tagName: string }).tagName === 'TEXTAREA' ? win.HTMLTextAreaElement : win.HTMLInputElement
      Object.getOwnPropertyDescriptor(proto.prototype, 'value')!.set!.call(el, v)
      el!.dispatchEvent(new win.Event('input', { bubbles: true }) as unknown as Event)
    })
    await settle()
  }

  const doc2 = {
    ...doc,
    meta: { video: { aspect_ratio: '16:9' } },
    source: { work_title: 'x', units: [{ id: 'U1', text: '康大叔推开了门' }] },
    episodes: [
      { id: 'E01', shots: [shot('SH001'), shot('SH002', {
        narration: { text: '康大叔推门' } as Shot['narration'],
        source: { unit_refs: ['U1'], derivation: 'explicit' } })] },
      { id: 'E02', shots: [shot('SH003', { source: { unit_refs: [], derivation: 'inferred' } })] },
    ],
  } as unknown as Storyboard
  const idx = buildIndex(doc2)
  const changes: unknown[][] = []
  let saved = 0
  let canvas = 0
  const base = {
    doc: doc2, idx, readOnly: false, dirty: false, saving: false, canSave: false,
    onShotChange: (...a: unknown[]) => { changes.push(a) }, onPickUnit: () => {},
    onSave: () => { saved += 1 }, onOpenCanvas: () => { canvas += 1 },
  }
  const view = async (o: Record<string, unknown> = {}) => {
    await act(async () => {
      root.render(h(I18nProvider, { initial: 'zh' }, h(TooltipProvider, null,
        h(ShotFocusView, { ...base, ...o } as never))) as never)
    })
    await settle()
  }
  const opts = () => qa('[role="option"]')
  const selected = () => opts().filter((o) => o.getAttribute('aria-selected') === 'true').map((o) => o.getAttribute('data-shot')).join()

  await view({ report })
  must(opts().length === 3, '3 个镜头项')
  const heads = qa('.focus__ep')
  must(heads.length === 2 && heads[0].textContent!.includes('E01') && heads[1].textContent!.includes('E02'), '两个集标题')
  must(selected() === 'SH001', '默认选中第一镜')
  must(opts()[1].getAttribute('data-issue') === 'hard' && opts()[2].getAttribute('data-issue') === 'soft', '红黄点')
  must(!opts()[0].hasAttribute('data-issue'), '无问题不标')

  await click(opts()[1])
  must(qa('.shot').length === 1 && q('.shot')!.id === 'shot-SH002', '中栏只有选中镜头')
  const src = q('[data-testid="focus-source"]')!.textContent!
  must(src.includes('U1') && src.includes('康大叔推开了门'), '原文出处：' + src)
  must(q('[data-testid="focus-frame"]')!.textContent!.includes('SH002'), '景别色块写镜头 ID')

  const list = q('[role="listbox"]')
  await key(list, 'ArrowDown')
  must(selected() === 'SH003', 'ArrowDown')
  await key(list, 'Home')
  must(selected() === 'SH001', 'Home')
  await click(opts()[0]) // 回到 SH001 再去 SH003
  await key(list, 'End')
  must(selected() === 'SH003', 'End')
  await click(qa('.focus__ep')[0])
  must(opts().length === 1, '折叠后只剩 E02 的项')
  await key(list, 'ArrowUp')
  must(selected() === 'SH003', '折叠后上键停在原处')
  await click(qa('.focus__ep')[0])
  must(opts().length === 3, '展开')

  await type(q('.focus__search'), '推门')
  must(opts().length === 1, '搜索只剩 1 项')
  await type(q('.focus__search'), '')

  await view({ report })
  const prim = () => q('[data-testid="focus-primary"]') as unknown as HTMLButtonElement
  must(prim().textContent === '在画布中查看', '主按钮：看画布')
  await click(prim())
  must(canvas === 1, '打开画布')
  await view({ dirty: true, canSave: true })
  must(prim().textContent === '保存修改', '主按钮：保存')
  await click(prim())
  must(saved === 1, '保存')
  await view({ dirty: true, canSave: true, saving: true })
  must(prim().disabled, '保存中禁用')
  await view({})

  await click(opts()[1])
  const ta = qa('.shot textarea')[0]
  await type(ta, '新的画面')
  const last = changes[changes.length - 1]
  must(!!last && last[0] === 'E01' && last[1] === 'SH002' && (last[2] as { action?: string }).action === '新的画面', '编辑回传')

  must(!q('[data-testid="focus-media"]'), '没出片会话没有分段控件')
  await view({ film, version: { nid: 'n', cid: 'c', vid: 'v' } })
  await click(opts()[0])
  must(!!q('[data-testid="focus-media"]'), 'SH001 有成片段切换')
  await click(opts()[2])
  must(!q('[data-testid="focus-media"]'), 'SH003 没有')

  await view({ focusShot: { id: 'SH003', n: 1 } })
  must(selected() === 'SH003', '外部定位')
  await click(opts()[0])
  await view({ focusShot: { id: 'SH003', n: 2 } })
  must(selected() === 'SH003', '同一镜再次定位')

  await act(async () => { root.render(null as never) })
}

win.happyDOM.abort?.()
console.log('chapter: ALL PASS')
