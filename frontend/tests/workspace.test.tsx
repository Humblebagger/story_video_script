/** 工作台骨架：章节所在步骤的纯函数 chapterStage、顶栏（项目切换器、费用表、外壳插槽）。跑法：npm test */
import { chapterStage } from '../src/workflow'
import type { ChapterSum, ChapterSummary, VersionSummary } from '../src/types'

import { Window } from 'happy-dom'

const win = new Window({ url: 'http://localhost:5173' })
const g = globalThis as Record<string, unknown>
for (const k of ['window', 'document', 'navigator', 'location', 'HTMLElement', 'Element', 'Node', 'Event',
                 'CustomEvent', 'KeyboardEvent', 'MouseEvent', 'PointerEvent', 'getComputedStyle',
                 'localStorage', 'sessionStorage', 'matchMedia', 'ResizeObserver', 'DOMRect', 'MutationObserver', 'NodeFilter']) {
  Object.defineProperty(g, k, {
    value: (win as unknown as Record<string, unknown>)[k], writable: true, configurable: true,
  })
}
g.IS_REACT_ACT_ENVIRONMENT = true
g.requestAnimationFrame ??= (cb: (t: number) => void) => setTimeout(() => cb(Date.now()), 16)
g.cancelAnimationFrame ??= (id: number) => clearTimeout(id)

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }

const ch = (o: Partial<ChapterSummary> = {}): ChapterSummary => ({
  id: 'c1', title: '第一章', order: 1, adopted_version: null, legacy_numbering: false,
  chars: 100, versions: [], latest_status: null, digest: null, ...o })
const ok = { id: 'v1', status: 'succeeded', created_at: null, edited_at: null, units: 1, episodes: 1, shots: 3,
  has_quality_report: false } as VersionSummary
const sum = (o: Partial<ChapterSum> = {}): ChapterSum => ({
  id: 'c1', version: 'v1', shots: 3, duration_s: 30,
  film: { done: 3, total: 3, failed: 0, running: 0 }, final: 'fresh', cost: null, ...o })

must(chapterStage(ch({ chars: 0 }), undefined, false) === 'import', '没原文')
must(chapterStage(ch(), undefined, false) === 'storyboard', '没版本')
must(chapterStage(ch({ versions: [ok] }), sum(), true) === 'storyboard', '生成中')
must(chapterStage(ch({ versions: [{ ...ok, status: 'draft_invalid' }] }), sum(), false) === 'review', '检查没过')
must(chapterStage(ch({ versions: [ok] }), sum({ film: null }), false) === 'render', '没出片会话')
must(chapterStage(ch({ versions: [ok] }), sum({ film: { done: 1, total: 3, failed: 0, running: 0 } }), false) === 'render', '还有段')
must(chapterStage(ch({ versions: [ok] }), sum({ final: 'stale' }), false) === 'compose', '成片过期')
must(chapterStage(ch({ versions: [ok] }), sum({ final: 'none' }), false) === 'compose', '还没成片')
must(chapterStage(ch({ versions: [ok] }), sum(), false) === 'download', '都完成')
must(chapterStage(ch({ chars: 0, versions: [ok] }), sum(), true) === 'import', '没原文优先于生成中')
must(chapterStage(ch({ adopted_version: 'v1', versions: [{ ...ok, id: 'v2' }, ok] }), sum(), false) === 'download', '采用版')


// ---------- 顶栏：项目切换器、费用表、外壳插槽 ----------
const { act } = await import('react')
const { createPortal } = await import('react-dom')
const { createRoot } = await import('react-dom/client')
const { I18nProvider } = await import('../src/i18n')
const { ProjectSwitcher } = await import('../src/components/shell/ProjectSwitcher')
const { CostMeter } = await import('../src/components/shell/CostMeter')
const { AppShell } = await import('../src/components/shell/AppShell')
const { useTopbarSlot } = await import('../src/components/shell/topbarSlot')
const { TooltipProvider } = await import('../src/components/ui/tooltip')
const { Stepper } = await import('../src/components/workflow/Stepper')
const { stepStates } = await import('../src/workflow')
const { createElement: h } = await import('react')
type NS = import('../src/types').NovelSummary

const doc = win.document
const container = doc.createElement('div')
doc.body.appendChild(container)
const root = createRoot(container as unknown as HTMLElement)
const settle = async (ms = 30) => { await act(async () => { await new Promise((r) => setTimeout(r, ms)) }) }
const render = async (node: unknown) => { await act(async () => { root.render(node as never) }); await settle() }
const q = (sel: string) => doc.querySelector(sel) as unknown as HTMLElement | null
const qa = (sel: string) => [...doc.querySelectorAll(sel)] as unknown as HTMLElement[]
const click = async (el: HTMLElement | null) => {
  must(!!el, '要点的元素不存在')
  await act(async () => { el!.dispatchEvent(new win.MouseEvent('click', { bubbles: true }) as unknown as Event) })
  await settle()
}
/** Radix 的触发器在 pointerdown 时打开 */
const open = async (el: HTMLElement | null) => {
  must(!!el, '要打开的触发器不存在')
  await act(async () => {
    el!.dispatchEvent(new win.PointerEvent('pointerdown', { bubbles: true, button: 0, ctrlKey: false }) as unknown as Event)
  })
  await settle()
}
const wrap = (node: unknown) => h(I18nProvider, { initial: 'zh' }, h(TooltipProvider, null, node as never))

const novels: NS[] = [
  { id: 'n1', title: '药', updated_at: '2026-10-01', chapters: 3, adopted: 1, asset_counts: {} },
  { id: 'n2', title: '洪荒', updated_at: '2026-10-02', chapters: 1, adopted: 0, asset_counts: {} },
  { id: 'n3', title: '春', updated_at: '2026-10-03', chapters: 2, adopted: 2, asset_counts: {} },
]

// 1. ProjectSwitcher
{
  const calls: string[] = []
  await render(wrap(h(ProjectSwitcher, {
    novels, currentId: 'n1', meta: '9:16 · 写实',
    onOpen: (id: string) => calls.push('open:' + id), onNew: () => calls.push('new'), onAll: () => calls.push('all') })))
  const trig = q('[data-testid="project-switcher"]')!
  must((trig.textContent ?? '').includes('药') && (trig.textContent ?? '').includes('9:16 · 写实'), '触发按钮显示当前小说与小字')
  await open(trig)
  must(qa('[data-testid="switch-item"]').length === 3, '3 个小说项')
  must(!!q('input[aria-label="搜索小说"]'), '有搜索框')
  must(qa('[role="menuitem"]').some((x) => (x.textContent ?? '').includes('＋ 新建小说')), '有「＋ 新建小说」')
  const input = q('input[aria-label="搜索小说"]') as unknown as HTMLInputElement
  await act(async () => {
    const set = Object.getOwnPropertyDescriptor(win.HTMLInputElement.prototype, 'value')!.set!
    set.call(input, '洪')
    input.dispatchEvent(new win.Event('input', { bubbles: true }) as unknown as Event)
  })
  await settle()
  must(qa('[data-testid="switch-item"]').length === 1, '搜索「洪」只剩 1 项')
  await click(qa('[data-testid="switch-item"]')[0])
  must(calls.join() === 'open:n2', '点小说项调 onOpen')
  await open(q('[data-testid="project-switcher"]'))
  await click(qa('[role="menuitem"]').find((x) => (x.textContent ?? '').includes('新建小说')) ?? null)
  must(calls.join() === 'open:n2,new', '点「＋ 新建小说」调 onNew')
  await open(q('[data-testid="project-switcher"]'))
  await click(qa('[role="menuitem"]').find((x) => (x.textContent ?? '').includes('全部小说')) ?? null)
  must(calls.join() === 'open:n2,new,all', '点「全部小说」只调 onAll，不调 onNew')
  await render(wrap(h(ProjectSwitcher, { novels, currentId: 'n1', onOpen: () => {}, onNew: () => {} })))
  await open(q('[data-testid="project-switcher"]'))
  must(!qa('[role="menuitem"]').some((x) => (x.textContent ?? '').includes('全部小说')), '没传 onAll 就不显示「全部小说」')
  await render(null)
  console.log('1. ProjectSwitcher ✓')
}

// 2. CostMeter
{
  const data = { cost: { llm_usd: 0.4, render_cny: 3.66, budget_cny: 40 }, unpriced: [], chapters: [] }
  await render(wrap(h(CostMeter, { data })))
  must(q('[data-testid="cost-meter"]')!.textContent === '¥3.66 · $0.40', '费用文字格式')
  await click(q('[data-testid="cost-meter"]'))
  must(qa('[data-testid="cost-row"]').length === 3, '浮层三行明细')
  must((q('[data-testid="cost-row"]')!.textContent ?? '').includes('$0.40'), '第一行是大模型花费')
  await render(wrap(h(CostMeter, { data: null })))
  must(q('[data-testid="cost-meter"]')!.textContent === '—', '没数据显示「—」')
  await render(wrap(h(CostMeter, { data: { ...data, cost: { llm_usd: 0.4, render_cny: null, budget_cny: null } } })))
  must(q('[data-testid="cost-meter"]')!.textContent === '$0.40', '没有出片费用时只显示美元')
  await render(null)
  console.log('2. CostMeter ✓')
}

// 3. AppShell：#topbar-center 与 portal、铃铛计数、账号菜单
{
  const calls: string[] = []
  function Consumer() {
    const slot = useTopbarSlot()
    return slot ? createPortal(h('span', { 'data-testid': 'in-topbar' }, '步骤条'), slot) : null
  }
  const shell = (n: number) => wrap(h(AppShell, {
    username: 'amy', isAdmin: true, adminOpen: false, onToggleAdmin: () => calls.push('admin'),
    onLogout: () => calls.push('logout'), onNewNovel: () => {}, onOpenLocal: () => {},
    service: { down: true, model: 'claude-x' }, sidebar: null, viewKey: 'a',
    runningCount: n, onToggleActivity: () => calls.push('bell'),
  }, h(Consumer)))
  await render(shell(0))
  const center = q('#topbar-center')
  must(!!center, '顶栏中间有 #topbar-center')
  must(!!center!.querySelector('[data-testid="in-topbar"]'), 'portal 的内容出现在顶栏中间')
  must(q('[data-testid="topbar"]')!.className.includes('grid-cols-[1fr_auto_1fr]'), '三段式')
  must(!q('[data-testid="activity-count"]'), '0 个任务不显示徽标')
  must((q('[data-testid="topbar"]')!.textContent ?? '').includes('服务未连通'), '连不上时显示红色状态')
  await render(shell(3))
  must(q('[data-testid="activity-count"]')?.textContent === '3', '铃铛徽标显示在跑任务数')
  await click(q('[data-testid="activity-bell"]'))
  must(calls.join() === 'bell', '点铃铛')
  await open(q('[data-testid="account-menu"]'))
  const items = qa('[role="menuitem"]').map((x) => x.textContent ?? '')
  must(items.some((x) => x.includes('管理')) && items.some((x) => x.includes('退出')), '账号菜单有管理与退出')
  must((doc.body.textContent ?? '').includes('claude-x'), '账号菜单里有当前模型')
  await click(qa('[role="menuitem"]').find((x) => (x.textContent ?? '').includes('退出')) ?? null)
  must(calls.join() === 'bell,logout', '菜单里的退出')
  await render(null)
  console.log('3. AppShell 顶栏 ✓')
}

// 4. Stepper 紧凑形态
{
  const viewed: string[] = []
  const states = stepStates({ hasText: true, textDirty: false, converting: false, version: null, dirty: false,
    verificationFailed: false, film: null, finalStale: false, compose: null })
  await render(wrap(h(Stepper, { states, view: 'storyboard', onView: (id: string) => viewed.push(id), compact: true })))
  const trig = q('[data-testid="stepper-compact"]')!
  must((trig.textContent ?? '').includes('2') && (trig.textContent ?? '').includes('生成'), '紧凑形态只显示当前步')
  must(qa('[data-step]').length === 0, '没打开时不列出全部步骤')
  await open(trig)
  must(qa('[data-step]').length === 6, '下拉里列出全部步骤')
  await click(q('[data-step="import"]'))
  must(viewed.join() === 'import', '下拉里选步骤')
  await render(null)
  console.log('4. Stepper 紧凑形态 ✓')
}

// 5. ProjectNav：九个导航项、数量、待确认提示点、章节卡片、搜索、收起态
{
  const { ProjectNav } = await import('../src/components/shell/ProjectNav')
  const { SidebarCollapsedContext } = await import('../src/components/shell/topbarSlot')
  type N = import('../src/types').Novel
  const mkNovel = (nch: number, pending = 0): N => ({
    id: 'n1', title: '药', created_at: '', updated_at: '', params: {},
    memory: {
      assets: { characters: [{ id: 'C01', name: '甲' }, { id: 'C02', name: '乙' }, { id: 'C03', name: '丙' }],
                locations: [{ id: 'S01', name: '屋' }], props: [], creatures: [] },
      numbering: { next_unit: 1, next_para: 1, next_episode: 1 },
      lifecycle: Array.from({ length: pending }, (_, i) => ({ id: 'L' + i, status: 'proposed' })) as never,
      plot: { outline: '', chapters: [] }, constraints: [],
    },
    chapters: Array.from({ length: nch }, (_, i) => ch({
      id: 'c' + (i + 1), title: i === 0 ? '第一章' : `章${i + 1}`, order: i + 1,
      versions: [ok], adopted_version: 'v1' })),
  }) as unknown as N
  const sums = {
    cost: { llm_usd: 0, render_cny: null, budget_cny: null }, unpriced: [],
    chapters: [
      sum({ id: 'c1' }),                                                              // download 6/6
      sum({ id: 'c2', duration_s: 65, film: { done: 0, total: 3, failed: 0, running: 0 } }), // render 3/6
    ],
  }
  const calls: string[] = []
  const nav = (novel: N, o: Record<string, unknown> = {}, collapsed = false) => wrap(h(SidebarCollapsedContext.Provider,
    { value: collapsed }, h(ProjectNav, {
      novel, section: 'overview', chapterId: 'c2', summary: sums, running: [],
      onSection: (s: string) => calls.push('sec:' + s), onOpenChapter: (id: string) => calls.push('open:' + id),
      onNewChapter: () => calls.push('new'), ...o })))

  await render(nav(mkNovel(2, 2)))
  const items = qa('[data-testid="nav-item"]')
  must(items.length === 9, '9 个导航项')
  const sec = (k: string) => q(`[data-section="${k}"]`)!
  must(sec('characters').textContent!.includes('3') && sec('locations').textContent!.includes('1'), '资产数量取自各类长度')
  must(sec('props').hasAttribute('data-empty') && sec('creatures').hasAttribute('data-empty'), '0 个的项带 data-empty')
  must(!sec('characters').hasAttribute('data-empty'), '有数量的不带 data-empty')
  must(qa('[data-testid="nav-badge"]').length === 1 && !!sec('memory').querySelector('[data-testid="nav-badge"]'),
       '待确认的人物状态：剧情与记忆上有提示点')
  must(sec('overview').getAttribute('aria-current') === 'page' && !sec('chapters').hasAttribute('aria-current'), '当前项 aria-current')
  await click(sec('props'))
  must(calls.join() === 'sec:props', '空项也能点')

  const cards = qa('[data-testid="chapter-card"]')
  must(cards.length === 2, '每章一张卡片')
  must((cards[0].textContent ?? '').includes('01') && (cards[0].textContent ?? '').includes('第一章')
       && (cards[0].textContent ?? '').includes('下载成片'), '卡片：编号、标题、步骤名')
  must((cards[1].textContent ?? '').includes('出片') && (cards[1].textContent ?? '').includes('1:05'), '卡片：步骤名与时长')
  const w = (c: HTMLElement) => (c.querySelector('[data-testid="chapter-progress"]') as unknown as HTMLElement).style.width
  must(w(cards[0]) === '100%', 'download 是 6/6：' + w(cards[0]))
  must(w(cards[1]) === '50%', 'render 是 3/6：' + w(cards[1]))
  must(cards[1].getAttribute('aria-current') === 'true' && !cards[0].hasAttribute('aria-current'), '当前章节 aria-current')
  must(!q('[data-testid="chapter-card"] [data-tone="live"]'), '没在生成就没有 live')
  await click(cards[0])
  must(calls.join() === 'sec:props,open:c1', '点卡片调 onOpenChapter')
  await click(q('[data-testid="nav-new-chapter"]'))
  must(calls[calls.length - 1] === 'new', '＋ 调 onNewChapter')
  must(!q('[data-testid="nav-search"]'), '章节不多于 8 个没有搜索框')

  await render(nav(mkNovel(2), { section: null, running: [{ id: 'j', chapter_id: 'c1' }] }))
  must(!!qa('[data-testid="chapter-card"]')[0].querySelector('[data-tone="live"]'), '生成中的章节有 live')
  must(qa('[data-testid="nav-item"]').every((x) => !x.hasAttribute('aria-current')), '章节里没有高亮的导航项')
  must(!q('[data-testid="nav-badge"]'), '没有待确认就没有提示点')

  await render(nav(mkNovel(9)))
  const inp = q('[data-testid="nav-search"]') as unknown as HTMLInputElement
  must(!!inp, '超过 8 章出现搜索框')
  await act(async () => {
    Object.getOwnPropertyDescriptor(win.HTMLInputElement.prototype, 'value')!.set!.call(inp, '章9')
    inp.dispatchEvent(new win.Event('input', { bubbles: true }) as unknown as Event)
  })
  await settle()
  must(qa('[data-testid="chapter-card"]').length === 1, '搜索过滤章节')

  await render(null)                                  // 卸载，清掉上面搜索框里的输入
  await render(nav(mkNovel(2, 1), {}, true))
  must(qa('[data-testid="nav-item"]').length === 9 && !sec('characters').textContent!.includes('角色'), '收起只剩图标')
  must(sec('characters').getAttribute('aria-label') === '角色', '收起时名字放进 aria-label 与提示')
  must(!!q('[data-testid="chapter-card"]') && !(q('[data-testid="chapter-card"]')!.textContent ?? '').includes('第一章')
       && (q('[data-testid="chapter-card"]')!.textContent ?? '').includes('01'), '收起时章节只剩编号方块')
  await render(null)
  console.log('5. ProjectNav ✓')
}

win.happyDOM.abort?.()
console.log('workspace: ALL PASS')
