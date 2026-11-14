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
  must(q('[data-testid="topbar"]')!.className.includes('grid-cols-[minmax(0,1fr)_auto_minmax(max-content,1fr)]'), '三段式')
  must(q('[data-testid="topbar"] > div')!.className.includes('overflow-hidden'), '左栏放不下时截断，不压到中间的步骤条')
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
  // 普通用户：service 里没有 model，账号菜单不出现「当前模型」那一行
  await render(wrap(h(AppShell, {
    username: 'bob', isAdmin: false, adminOpen: false, onToggleAdmin: () => {},
    onLogout: () => {}, onNewNovel: () => {}, onOpenLocal: () => {},
    service: { down: false }, sidebar: null, viewKey: 'a',
    runningCount: 0, onToggleActivity: () => {},
  }, h(Consumer))))
  await open(q('[data-testid="account-menu"]'))
  must(!(doc.body.textContent ?? '').includes('当前模型') && (doc.body.textContent ?? '').includes('正常'), '普通用户的账号菜单没有当前模型一行')
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

// 6. 概览页与原文与章节页
{
  const { NovelOverview } = await import('../src/components/NovelOverview')
  const { mainCharacters } = await import('../src/mainCharacters')
  const { ChaptersPage } = await import('../src/components/ChaptersPage')
  type N = import('../src/types').Novel
  const chs = Array.from({ length: 6 }, (_, i) => ch({
    id: 'c' + (i + 1), title: ['第一章', '第二章', '第三章', '第四章', '第五章', '第六章'][i], order: i + 1,
    versions: [ok], adopted_version: i < 4 ? 'v1' : null }))
  const mk = (o: Partial<N['memory']['plot']> = {}, life: unknown[] = [], chars?: unknown[]): N => ({
    id: 'n1', title: '药', created_at: '', updated_at: '',
    params: { aspect_ratio: '9:16', art_style: 'realistic', narration_mode: 'selective', tts_voice: 'male_mature' },
    memory: {
      assets: { characters: chars ?? ['甲', '乙', '丙', '丁', '戊', '己', '庚'].map((n, i) => ({ id: 'C0' + (i + 1), name: n })),
                locations: [{ id: 'S01', name: '屋' }], props: [{ id: 'P01', name: '药' }], creatures: [] },
      numbering: { next_unit: 1, next_para: 1, next_episode: 1 },
      lifecycle: life as never, plot: { outline: '', chapters: [], ...o }, constraints: [],
    },
    chapters: chs,
  }) as unknown as N
  const full = (stages: Record<string, Partial<ChapterSum>> = {}) => ({
    cost: { llm_usd: 0.4, render_cny: 3.66, budget_cny: null }, unpriced: [],
    chapters: chs.map((c) => sum({ id: c.id, shots: 10, ...(stages[c.id] ?? {}) })),
  })
  // c1,c2 下载；c3 版本检查没过（review）；c4..c6 还在出片
  const mid = full({
    c1: { final: 'fresh' }, c2: { final: 'fresh' }, c3: { final: 'none' },
    c4: { film: { done: 0, total: 3, failed: 0, running: 0 }, final: 'none' },
    c5: { film: { done: 0, total: 3, failed: 0, running: 0 }, final: 'none' },
    c6: { film: { done: 0, total: 3, failed: 0, running: 0 }, final: 'none' },
  })
  const novelMid = mk()
  novelMid.chapters = chs.map((c, i) => i === 2 ? { ...c, versions: [{ ...ok, status: 'draft_invalid' }] } as never : c)
  const calls: string[] = []
  const ovw = (novel: N, summary: unknown, o: Record<string, unknown> = {}) => wrap(h(NovelOverview, {
    novel, summary, lastChapterId: null, onOpenChapter: (id: string) => calls.push('open:' + id),
    onSection: (x: string) => calls.push('sec:' + x), onDeleted: () => calls.push('deleted'), ...o }))

  await render(ovw(novelMid, mid))
  must(q('[data-testid="ovw-title"]')!.textContent === '药', '标题')
  must(q('[data-testid="ovw-meta"]')!.textContent === '9:16 · 写实 · 择要旁白 · 男声·沉稳', '参数小字：' + q('[data-testid="ovw-meta"]')!.textContent)
  const stat = qa('[data-testid="stat"]').map((x) => x.textContent ?? '')
  must(stat.length === 6, '6 张数字卡')
  must(stat[0].includes('6') && stat[1].includes('4') && stat[2].includes('60') && stat[3].includes('9')
       && stat[4].includes('2/6') && stat[5].includes('¥3.66 · $0.40'), '数字卡：' + stat.join('|'))
  const cont = q('[data-testid="ovw-continue"]') as unknown as HTMLButtonElement
  must(cont.textContent === '继续：第三章 · 检查修改', '继续：' + cont.textContent)
  await click(cont)
  must(calls.join() === 'open:c3', '点继续')
  await render(ovw(novelMid, mid, { lastChapterId: 'c5' }))
  must(q('[data-testid="ovw-continue"]')!.textContent === '继续：第五章 · 出片', '优先最近打开的章节')

  await render(ovw(novelMid, null))
  must(qa('[data-testid="stat"]')[5].textContent!.includes('—'), '没有汇总时花费显示「—」')

  const allMid = full()
  await render(ovw(mk(), allMid))
  const done = q('[data-testid="ovw-continue"]') as unknown as HTMLButtonElement
  must(done.textContent === '全部完成' && done.disabled, '全部完成且不能点')

  must(!!q('[data-testid="ovw-outline"]')!.textContent!.includes('还没有主线剧情'), '无梗概')
  calls.length = 0
  await click(qa('[data-testid="ovw-outline"] button')[0])
  must(calls.join() === 'sec:memory', '去填写')
  await render(ovw(mk({ outline: '一\n\n二\n三\n四\n五' }), mid))
  must(qa('[data-testid="outline-line"]').map((x) => x.textContent).join('') === '一二三四', '梗概只取前 4 行')

  const syn = ['丙遇见丁', '丙', '乙', '丙'].map((x, i) => ({ chapter_id: 'c' + (i + 1), synopsis: x, origin: 'user' as const }))
  const mains = mainCharacters(mk({ chapters: syn }))
  must(mains.length === 5 && mains.map((c) => c.name).join('') === '丙乙丁甲戊', '主要人物按出场章数：' + mains.map((c) => c.name).join(''))
  must(mainCharacters(mk()).map((c) => c.name).join('') === '甲乙丙丁戊', '没有摘要时按资产卡顺序')
  await render(ovw(mk({ chapters: syn }), mid))
  must(qa('[data-testid="main-char"]').length === 5 && qa('[data-testid="avatar"]')[0].textContent === '丙', '人物与首字头像')

  await render(ovw(novelMid, mid))
  const rows = qa('[data-testid="progress-row"]')
  must(rows.length === 6, '每章一行')
  const cells = (r: HTMLElement) => [...r.querySelectorAll('[data-testid="cell"]')].map((c) => c.getAttribute('data-state')).join()
  must(cells(rows[0]) === 'done,done,done,done,done,done', '下载：全部完成')
  must(cells(rows[2]) === 'done,done,current,todo,todo,todo', 'review：前两格完成、第三格当前')
  must((rows[2].textContent ?? '').includes('检查修改') && (rows[0].textContent ?? '').includes('0:30'), '步骤名与时长')
  calls.length = 0
  await click(rows[1])
  must(calls.join() === 'open:c2', '点一行')

  must(!q('[data-testid="ovw-pending"]'), '没有待处理时不显示')
  const withLife = mk({}, [{ id: 'l1', status: 'proposed' }, { id: 'l2', status: 'proposed' }, { id: 'l3', status: 'confirmed' }])
  await render(ovw(withLife, full({ c1: { final: 'stale' } })))
  const pend = q('[data-testid="ovw-pending"]')!.textContent ?? ''
  must(pend.includes('2 条人物状态待确认') && pend.includes('去确认'), '待确认人物状态')
  must(pend.includes('第一章的成片内容改过，需要重新合成') && pend.includes('去处理'), '成片过期')
  calls.length = 0
  await click(qa('[data-testid="ovw-pending"] button')[0])
  await click(qa('[data-testid="ovw-pending"] button')[1])
  must(calls.join() === 'sec:memory,open:c1', '待处理的去处理按钮：' + calls.join())

  await open(q('button[aria-label="更多操作"]'))
  must(qa('[role="menuitem"]').some((x) => (x.textContent ?? '').includes('删除小说')), '更多菜单里有「删除小说」')
  await render(null)

  // 原文与章节页
  const cc: string[] = []
  const imported: unknown[] = []
  await render(wrap(h(ChaptersPage, {
    novel: novelMid, summary: mid, onOpenChapter: (id: string) => cc.push('open:' + id), onNewChapter: () => cc.push('new'),
    onImport: (l: unknown) => imported.push(l) })))
  const trs = qa('[data-testid="chapter-row"]')
  must(trs.length === 6, '章节表格 6 行')
  must((trs[2].textContent ?? '').includes('第三章') && (trs[2].textContent ?? '').includes('100') && (trs[2].textContent ?? '').includes('检查修改'),
       '行内含标题、字数、步骤')
  await click(q('[data-testid="new-chapter"]'))
  must(cc.join() === 'new', '点＋新章节')
  must(q('[data-testid="import-txt"]')!.getAttribute('data-tour') === 'import', '导入按钮带 data-tour="import"')
  await click(trs[1])
  must(cc.join() === 'new,open:c2', '点行打开章节')
  await render(null)
  console.log('6. 概览页与原文与章节页 ✓')
}

// ---------- 右侧动态面板 ----------
{
  const { ActivityPanel } = await import('../src/components/shell/ActivityPanel')
  const rj = (id: string, o: object = {}) => ({ id, status: 'running', created_at: null, work_title: '雾港', chapter: '第' + id + '章',
    chars: 100, log_lines: 3, last_log: '第 2 批校验中', novel_id: 'n1', chapter_id: 'c' + id,
    progress: { batches: 4, batch: 2, total_chars: 100, done_chars: 40, attempt: 1, max_attempts: 3, phase: 'checking',
                elapsed_sec: 30, eta_sec: 150 }, ...o })
  const opened: string[] = []
  let closed = 0
  const dn = (id: string, status: string) => ({ id, status, work_title: '雾港', chapter: '第' + id + '章' })
  const panel = (r: unknown[], d: unknown[]) => wrap(h(ActivityPanel, {
    running: r, done: d, onOpen: (j: { id: string }) => opened.push(j.id), onClose: () => { closed += 1 } }))
  await render(panel([rj('1'), rj('2', { progress: null })], [dn('3', 'succeeded'), dn('4', 'completed_with_warnings'), dn('5', 'failed')]))
  const runs = qa('[data-testid="activity-running"]')
  must(runs.length === 2, '在跑 2 项')
  const r0 = runs[0].textContent ?? ''
  must(r0.includes('雾港 · 第1章') && r0.includes('第 2 批校验中') && r0.includes('3 分'), '在跑项内容：' + r0)
  must(!!runs[0].querySelector('[role="progressbar"]'), '进度条')
  await click(runs[1].querySelector('button'))
  must(opened.join() === '2', '查看')
  const dones = qa('[data-testid="activity-done"]')
  must(dones.length === 3, '完成 3 项')
  must(dones.map((x) => x.querySelector('[data-slot="status-pill"]')!.getAttribute('data-tone')).join() === 'ok,warn,err', '状态语义色')
  must(qa('[role="tab"]').length === 1, '只有一个页签')
  await click(q('button[aria-label="关闭"]'))
  must(closed === 1, '关闭按钮')
  await act(async () => { q('[data-testid="activity-panel"]')!.dispatchEvent(new win.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }) as unknown as Event) })
  must(closed === 2, 'Esc 关闭')
  await render(panel([], []))
  must((q('[data-testid="empty-state"]')?.textContent ?? '').includes('没有在跑的任务'), '空状态')
  // 最近一行：事件对象显示 message（代码未登记时回落），旧字符串原样
  await render(panel([rj('1', { last_log: { code: 'job.event.split', params: { chars: 4, batches: 1 }, message: '输入 4 字符 → 1 批', at: 't' } }),
                      rj('2', { last_log: '旧的一行' })], []))
  const lg = qa('[data-testid="activity-running"]').map((x) => x.textContent ?? '')
  must(lg[0].includes('输入 4 字符 → 1 批') && !lg[0].includes('[object'), '最近一行是事件对象：' + lg[0])
  must(lg[1].includes('旧的一行'), '最近一行是字符串')
  // 转换面板：进度、失败区、质量报告按代码渲染，切语言跟着变；旧数据原样显示
  const { JobPanel } = await import('../src/components/JobPanel')
  const { useI18n } = await import('../src/i18n/core')
  const { zh } = await import('../src/i18n/zh')
  const { en } = await import('../src/i18n/en')
  let setLoc: (l: 'zh' | 'en') => void = () => {}
  const Grab = () => { setLoc = useI18n().setLocale; return null }
  const jwrap = (node: unknown) => h(I18nProvider, { initial: 'zh' }, h(Grab), node as never)
  const lang = async (l: 'zh' | 'en') => { await act(async () => { setLoc(l) }); await settle() }
  const base = { id: 'j1', status: 'running', result: null, quality_report: null, error: null }
  const jobOf = (log: unknown[], o: object = {}) => ({ ...base, log, ...o }) as never
  const ev = { code: 'job.event.split', params: { chars: 4, batches: 1 }, message: '输入 4 字符 → 1 批', at: 't' }
  const props = { onReset: () => {}, onBackground: () => {} }
  await render(jwrap(h(JobPanel, { job: jobOf([ev]), ...props })))
  must((q('.job__log')?.textContent ?? '').includes('输入 4 字符 → 1 批'), '进度行是事件对象')
  await render(jwrap(h(JobPanel, { job: jobOf(['旧行']), ...props })))
  must((doc.body.textContent ?? '').includes('旧行'), '进度行是字符串')
  const failed = { code: 'job.failed_report', params: {
    reason: { code: 'job.batch_failed', params: { batch: 2, retries: 3 } },
    report: { t: 'vendor', text: 'FAIL: E01 缺资产 C09' } } }
  const fj = jobOf([ev], { status: 'failed', error: '旧中文', error_msg: failed, quality_msg: null })
  await render(jwrap(h(JobPanel, { job: fj, ...props })))
  must((q('.job__log')?.textContent ?? '') === '输入 4 字符 → 1 批', '中文进度行')
  must(q('.job__err')?.textContent === '批 2 重试 3 次后仍未通过校验\nFAIL: E01 缺资产 C09', '失败区是整段：' + q('.job__err')?.textContent)
  await lang('en')
  must(q('.job__log')?.textContent === en.srv.job.event.split.replace('{chars}', '4').replace('{batches}', '1'), '切英文：进度行变英文')
  must(!(q('.job__err')?.textContent ?? '').includes('批 2') && (q('.job__err')?.textContent ?? '').endsWith('\nFAIL: E01 缺资产 C09'), '切英文：失败区变英文、报告原文保留')
  await lang('zh')
  await render(jwrap(h(JobPanel, { job: jobOf([], { status: 'failed', error: '只有旧的报错', error_msg: null }), ...props })))
  must(q('.job__err')?.textContent === '只有旧的报错', '没有 error_msg 时显示旧 error')
  // 质量报告：quality_msg 有值按代码渲染，没有显示 quality_report
  const qm = [{ code: 'job.batch_failed', params: { batch: 1, retries: 2 } }, { code: 'llm.busy', params: {} }]
  await render(jwrap(h(JobPanel, { job: jobOf([], { status: 'succeeded', quality_report: '旧质量报告', quality_msg: qm }), ...props })))
  const qtxt = () => [...doc.querySelectorAll('.job__warn pre')].map((x) => x.textContent ?? '').join('|')
  must(qtxt() === '批 1 重试 2 次后仍未通过校验\n\n' + zh.srv.llm.busy, '质量报告按代码渲染：' + qtxt())
  await lang('en')
  must(qtxt().includes(en.srv.llm.busy) && !qtxt().includes('旧质量报告') && !qtxt().includes('批 1'), '切英文：质量报告变英文')
  await lang('zh')
  await render(jwrap(h(JobPanel, { job: jobOf([], { status: 'succeeded', quality_report: '旧质量报告', quality_msg: null }), ...props })))
  must(qtxt() === '旧质量报告', '没有 quality_msg 时显示 quality_report')
  // 子计划 5：失败区与质量报告的逐条（lines）、任务验证面板的每条说明，按代码渲染并随语言变化；旧 finding 显示 message
  const line = { code: 'verify.report.finding', params: { severity: { t: 'ref', code: 'verify.severity.high' }, rule: 'REF-UNIT-001',
    path: '/episodes/0/shots/0/source/unit_refs', detail: { code: 'verify.rule.REF-UNIT-001', params: { unit: 'u0099' } } } }
  const failedL = { code: 'job.failed_report', params: { reason: { code: 'job.batch_failed', params: { batch: 2, retries: 3 } },
    report: { t: 'lines', items: [{ code: 'verify.report.fail', params: { n: 1 } }, line] } } }
  await render(jwrap(h(JobPanel, { job: jobOf([], { status: 'failed', error: '旧中文', error_msg: failedL }), ...props })))
  must(q('.job__err')?.textContent === '批 2 重试 3 次后仍未通过校验\n未通过（1 条硬性问题）\n严重 [REF-UNIT-001] '
    + '/episodes/0/shots/0/source/unit_refs：镜头引用了不存在的原文句子 u0099', '失败区逐条（中文）：' + q('.job__err')?.textContent)
  await lang('en')
  const enLine = en.srv.verify.report.finding.replace('{severity}', en.srv.verify.severity.high).replace('{rule}', 'REF-UNIT-001')
    .replace('{path}', '/episodes/0/shots/0/source/unit_refs')
    .replace('{detail}', en.srv.verify.rule['REF-UNIT-001'].replace('{unit}', 'u0099'))
  must((q('.job__err')?.textContent ?? '').includes(enLine) && !(q('.job__err')?.textContent ?? '').includes('严重'),
    '失败区逐条切英文：' + q('.job__err')?.textContent)
  await lang('zh')
  const deg = { code: 'job.quality.degraded', params: { batch: 1, retries: 2, attempt: 2, candidates: 2,
    report: { t: 'lines', items: [{ code: 'verify.quality.density', params: { ratio: '80%', max: '60%' } }] } } }
  await render(jwrap(h(JobPanel, { job: jobOf([], { status: 'completed_with_warnings', quality_report: '旧', quality_msg: [deg] }), ...props })))
  must(qtxt().includes(zh.srv.verify.quality.density.replace('{ratio}', '80%').replace('{max}', '60%')), '质量报告逐条（中文）：' + qtxt())
  await lang('en')
  must(qtxt().includes(en.srv.verify.quality.density.replace('{ratio}', '80%').replace('{max}', '60%')) && !qtxt().includes('旁白占比'),
    '质量报告逐条切英文：' + qtxt())
  await lang('zh')
  const ver = { status: 'failed', coverage: {}, findings: [
    { rule_id: 'REF-UNIT-001', severity: 'high', object_path: '/episodes/0/shots/0/source/unit_refs',
      message: 'shot references unknown source unit u0099', unit_refs: ['u0099'],
      msg: { code: 'verify.rule.REF-UNIT-001', params: { unit: 'u0099' } } },
    { rule_id: 'ID-SHOT-001', severity: 'high', object_path: '/episodes', message: 'duplicate shot id E01-SH001' }] }
  await render(jwrap(h(JobPanel, { job: jobOf([], { status: 'failed', error: 'x', verification: ver }), ...props })))
  const vmsg = () => [...doc.querySelectorAll('.vf__msg')].map((x) => x.textContent ?? '')
  must(vmsg()[0] === '镜头引用了不存在的原文句子 u0099' && vmsg()[1] === 'duplicate shot id E01-SH001',
    '验证面板：有 msg 按代码，旧 finding 显示 message：' + vmsg().join('|'))
  await lang('en')
  must(vmsg()[0] === en.srv.verify.rule['REF-UNIT-001'].replace('{unit}', 'u0099') && vmsg()[1] === 'duplicate shot id E01-SH001',
    '验证面板切英文：' + vmsg().join('|'))
  await lang('zh')
  await render(null)
  console.log('7. 动态面板 ✓')
}

win.happyDOM.abort?.()
console.log('workspace: ALL PASS')
