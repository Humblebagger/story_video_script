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
must(assetThumb({ id: 'L01', name: '街', angles: [{ uri: 'https://x/s.png' }] } as never) === 'https://x/s.png', '场景图取自 angles')
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
  must(q('[role="option"] .focus__item-summary')?.textContent === 'SH001 的画面', '列表项显示画面摘要')
  must(q('[role="option"]')?.getAttribute('title') === 'SH001 的画面', '悬停可看完整画面描述')
  must(opts()[1].getAttribute('data-issue') === 'hard' && opts()[2].getAttribute('data-issue') === 'soft', '红黄点')
  must(!opts()[0].hasAttribute('data-issue'), '无问题不标')

  must(q('[role="listbox"]')!.getAttribute('aria-activedescendant') === 'focus-opt-SH001', 'activedescendant 指向选中项')
  must(qa('[role="listbox"] > [role="group"]').length === 2, '集是 group')
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
  await view({ dirty: true, canSave: false, saving: true })
  must(!prim().disabled && prim().textContent === '在画布中查看', '非保存态不禁用')
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

  // 在章节页里：本步主按钮由通栏按钮接管（每屏一个主按钮）
  const { StepPrimaryContext } = await import('../src/components/workflow/chapterHead')
  const claims: boolean[] = []
  let ran = 0
  let fixed = 0
  const step = (primary: unknown) => ({
    primary, busy: false, run: () => { ran += 1 }, fix: () => { fixed += 1 },
    claim: (on: boolean) => { claims.push(on) },
  })
  const inStep = async (primary: unknown, o: Record<string, unknown> = {}) => {
    await act(async () => {
      root.render(h(I18nProvider, { initial: 'zh' }, h(TooltipProvider, null,
        h(StepPrimaryContext.Provider, { value: step(primary) as never },
          h(ShotFocusView, { ...base, ...o } as never)))) as never)
    })
    await settle()
  }
  await inStep({ action: 'openFilm', label: 'flow.primary.tryOne', cny: 1.5 })
  must(claims[claims.length - 1] === true, '挂上时接管主按钮')
  must(prim().textContent === '先试一段（约 ¥1.50）', `通栏按钮换成本步主按钮：${prim().textContent}`)
  await click(prim())
  must(ran === 1 && canvas === 1, '点了走本步动作而不是看画布')
  await inStep({ action: 'goto', goto: 'render', label: 'flow.primary.next',
                 blocked: { reason: 'flow.block.converting', fix: { step: 'review' } } })
  must(prim().disabled && !!q('[data-testid="focus-reason"]'), '被拦时禁用并写原因')
  await click(q('.focus__fix'))
  must(fixed === 1, '去修复')
  await inStep({ action: 'openFilm', label: 'flow.primary.viewFilm' }, { dirty: true, canSave: true })
  must(prim().textContent === '保存修改', '有未保存修改时仍是保存')
  await inStep({ action: 'none', label: 'flow.primary.next' })
  must(prim().textContent === '在画布中查看', '本步没有主按钮时回到看画布')
  await act(async () => { root.render(null as never) })
  must(claims[claims.length - 1] === false, '卸下时交还主按钮')
}

// ---------- 3. 分镜视图的页签 ----------
{
  const { act, createElement: h } = await import('react')
  const { createRoot } = await import('react-dom/client')
  const { I18nProvider } = await import('../src/i18n')
  const { TooltipProvider } = await import('../src/components/ui/tooltip')
  const { StoryboardView } = await import('../src/components/StoryboardView')
  const d = win.document
  const container = d.createElement('div')
  d.body.appendChild(container)
  const root = createRoot(container as unknown as HTMLElement)
  const settle = async (ms = 30) => { await act(async () => { await new Promise((r) => setTimeout(r, ms)) }) }
  const qa = (sel: string) => [...container.querySelectorAll(sel)] as unknown as HTMLElement[]
  const doc3 = { ...doc, meta: { video: { aspect_ratio: '16:9' } }, source: { work_title: 'x', units: [] } } as unknown as Storyboard
  const mount = async (extra: Record<string, unknown> = {}) => {
    await act(async () => {
      root.render(h(I18nProvider, { initial: 'zh' }, h(TooltipProvider, null,
        h(StoryboardView, { doc: doc3, canSave: false, dirty: false, saving: false,
          onChange: () => {}, onSave: () => {}, ...extra } as never))) as never)
    })
    await settle()
  }
  await mount()
  must(qa('.tabs__btn').map((b) => b.textContent).join(' ') === '镜头 卡片 拉片表 资产 原文 渲染 JSON', '七个页签')
  must(qa('.focus').length > 0, '默认是镜头视图')
  must(qa('.shot').length === 1, '镜头视图里只有中栏一张卡')
  await act(async () => { qa('.tabs__btn')[1].dispatchEvent(new win.MouseEvent('click', { bubbles: true }) as unknown as Event) })
  await settle()
  must(qa('.shot').length === 3, '卡片页签有 3 张')
  await act(async () => { root.unmount() })
  const root2 = createRoot(container as unknown as HTMLElement)
  await act(async () => {
    root2.render(h(I18nProvider, { initial: 'zh' }, h(TooltipProvider, null,
      h(StoryboardView, { doc: doc3, canSave: false, dirty: false, saving: false, defaultTab: 'cards',
        onChange: () => {}, onSave: () => {} } as never))) as never)
  })
  await settle()
  must(qa('.shot').length === 3 && qa('.focus').length === 0, 'defaultTab=cards 一开始就是卡片')
  await act(async () => { root2.unmount() })
}

// 4. 章节头部
{
  const { ChapterHeader } = await import('../src/components/workflow/ChapterHeader')
  const { ChapterHeadContext } = await import('../src/components/workflow/chapterHead')
  const { act, createElement: h, useContext } = await import('react')
  const { createRoot } = await import('react-dom/client')
  const { I18nProvider } = await import('../src/i18n')
  const box = win.document.createElement('div')
  win.document.body.appendChild(box)
  const r = createRoot(box as unknown as HTMLElement)
  const show = async (node: unknown) => {
    await act(async () => { r.render(h(I18nProvider, { initial: 'zh' }, node as never) as never) })
  }
  const base = { num: 3, title: '第三章', shots: 45, seconds: 285, step: 'review' as const, live: false }
  await show(h(ChapterHeader, { ...base, film: null }))
  const txt = () => box.textContent ?? ''
  must(txt().includes('EP·03') && txt().includes('第三章'), '编号与标题')
  must(txt().includes('45 镜') && txt().includes('4:45') && txt().includes('检查修改'), '状态行')
  const tiles = () => Array.from(box.querySelectorAll('[data-testid="cost-tile"]'))
  must(tiles().length === 3 && tiles().every((x) => x.textContent?.includes('—')), '没有出片会话：三格都是破折号')
  must(tiles().every((tile) => !tile.hasAttribute('data-cost-kind')), '无费用数据时保持中性底色')
  must(txt().includes('出片时才会花钱'), '说明出片时才花钱')
  const film = { budget_cny: 20, spent_cny: 3.66, clips: [{ estimate_cny: 2.5 }, { estimate_cny: 2.94 }] } as unknown as FilmSession
  await show(h(ChapterHeader, { ...base, film }))
  must(tiles().map((x) => x.querySelector('.chead__value')?.textContent).join() === '¥5.44,¥3.66,¥20.00', '三格金额')
  must(tiles().map((tile) => tile.getAttribute('data-cost-kind')).join() === 'estimate,spent,cap', '费用类别拥有稳定的语义色标记')
  must(!txt().includes('出片时才会花钱'), '有会话时不再说明')
  await show(h(ChapterHeader, { ...base, film, compact: true }))
  const c = box.querySelector('[data-testid="chapter-head-compact"]')
  must(!!c && c.textContent === 'EP·03第三章¥3.66 / ¥20.00', '精简头部一行')
  await show(h(ChapterHeader, { ...base, film: null, compact: true }))
  must(box.querySelector('[data-testid="chapter-head-compact"]')?.textContent === 'EP·03第三章', '精简头部无会话省略金额')
  const Probe = () => h('div', null, useContext(ChapterHeadContext))
  await show(h(ChapterHeadContext.Provider, { value: h('span', { id: 'x' }) }, h(Probe)))
  must(!!box.querySelector('#x'), 'Context 读得到')
  await act(async () => { r.unmount() })
}

// 5. 资产分区缩略图网格
{
  const { NovelAssets } = await import('../src/components/NovelAssets')
  const { act, createElement: h } = await import('react')
  const { createRoot } = await import('react-dom/client')
  const { I18nProvider } = await import('../src/i18n')
  const puts: string[] = []
  g.fetch = async (url: string, init?: { method?: string }) => {
    puts.push(`${init?.method ?? 'GET'} ${String(url)}`)
    return { ok: true, status: 200, json: async () => ({}), text: async () => '{}' }
  }
  const box = win.document.createElement('div')
  win.document.body.appendChild(box)
  const r = createRoot(box as unknown as HTMLElement)
  const assets = { characters: [
    { id: 'C01', name: '华老栓', aliases: ['老栓'], reference_images: [{ uri: 'https://x/a.png' }] },
    { id: 'C02', name: '康大叔', outfits: [{ id: 'o1', description: 'x' }] },
    { id: 'C03', name: '夏瑜' },
  ] }
  const show = async (kind?: string) => {
    await act(async () => {
      r.render(h(I18nProvider, { initial: 'zh' }, h(NovelAssets, { nid: 'n1', assets, onSaved: () => {}, kind } as never)) as never)
    })
  }
  const settle5 = async (ms = 30) => { await act(async () => { await new Promise((x) => setTimeout(x, ms)) }) }
  const q5 = (sel: string) => box.querySelector(sel) as unknown as HTMLElement | null
  const qa5 = (sel: string) => [...box.querySelectorAll(sel)] as unknown as HTMLElement[]
  const click5 = async (el: HTMLElement | null) => {
    must(!!el, '要点的元素不存在')
    await act(async () => { el!.dispatchEvent(new win.MouseEvent('click', { bubbles: true }) as unknown as Event) })
    await settle5()
  }
  const type5 = async (el: HTMLElement | null, v: string) => {
    must(!!el, '要输入的元素不存在')
    await act(async () => {
      Object.getOwnPropertyDescriptor(win.HTMLInputElement.prototype, 'value')!.set!.call(el, v)
      el!.dispatchEvent(new win.Event('input', { bubbles: true }) as unknown as Event)
    })
    await settle5()
  }

  await show('characters')
  must(qa5('[data-testid="asset-grid"] [data-testid="asset-tile"]').length === 3, '网格里 3 张卡')
  const tiles = () => qa5('[data-testid="asset-tile"]')
  must(tiles()[0].querySelector('img') !== null && tiles()[1].querySelector('img') === null && tiles()[2].querySelector('img') === null, '只有有图的那张有 img')
  must(tiles()[1].textContent!.includes('康') && tiles()[1].textContent!.includes('C02'), '无图显示首字与编号')
  must(tiles()[0].textContent!.includes('1 个别名') && tiles()[1].textContent!.includes('1 套服装'), '别名与服装数')
  must(tiles()[1].getAttribute('aria-label') === '康大叔', 'aria-label 是名字')

  await type5(q5('.lib__search'), '康大叔')
  must(tiles().length === 1, '搜索后只剩 1 张')
  await type5(q5('.lib__search'), '')

  await click5(tiles()[0])
  must(!q5('[data-testid="asset-grid"]'), '点开后网格消失')
  must(box.textContent!.includes('C01') && qa5('.acard').length === 1, '单卡编辑只渲染这一张')
  const back = qa5('button').find((b) => b.textContent === '← 全部角色')
  must(!!back, '有返回按钮')
  await click5(back!)
  must(qa5('[data-testid="asset-tile"]').length === 3, '返回后网格回来')

  await type5(q5('.lib__add input'), '赵四')
  await click5(qa5('button').find((b) => b.textContent!.includes('新建'))!)
  must(!q5('[data-testid="asset-grid"]') && box.textContent!.includes('C04') && qa5('.acard').length === 1, '新建后直接进入新卡编辑')
  must(puts.some((x) => x.startsWith('PUT') && x.includes('/C04')), '新卡已写回')

  await show()
  must(!q5('[data-testid="asset-grid"]'), '不传 kind 没有网格')
  await act(async () => { r.unmount() })
}

// 6. 风格参考图：设置页上传框与概览缩略图
{
  const { StyleImageField } = await import('../src/components/params/StyleImageField')
  const { NovelOverview } = await import('../src/components/NovelOverview')
  const { notice } = await import('../src/lib/notice')
  const { act, createElement: h } = await import('react')
  const { createRoot } = await import('react-dom/client')
  const { I18nProvider } = await import('../src/i18n')
  const calls: string[] = []
  const bodies: unknown[] = []
  const metaOut = { hash: 'h1', mime: 'image/png', bytes: 3, updated_at: 't' }
  g.fetch = async (url: string, init?: { method?: string; body?: unknown }) => {
    calls.push(`${init?.method ?? 'GET'} ${String(url).replace(/^.*\/novels/, '/novels')}`)
    bodies.push(init?.body)
    return { ok: true, status: 200, json: async () => metaOut, text: async () => JSON.stringify(metaOut),
             blob: async () => new Blob(['x']) }
  }
  const box = win.document.createElement('div')
  win.document.body.appendChild(box)
  const r = createRoot(box as unknown as HTMLElement)
  const q6 = (sel: string) => box.querySelector(sel) as unknown as HTMLElement | null
  const qa6 = (sel: string) => [...box.querySelectorAll(sel)] as unknown as HTMLElement[]
  const settle6 = async (ms = 30) => { await act(async () => { await new Promise((x) => setTimeout(x, ms)) }) }
  const click6 = async (el: HTMLElement) => { await act(async () => { el.dispatchEvent(new win.MouseEvent('click', { bubbles: true }) as unknown as Event) }) }
  const show6 = async (el: unknown) => { await act(async () => { r.render(h(I18nProvider, { initial: 'zh' }, el as never) as never) }) }
  const changed: unknown[] = []
  const field = (meta: unknown, url: string | null) => h(StyleImageField, {
    nid: 'n1', meta, url, onChanged: (m: unknown) => changed.push(m) } as never)
  const choose = async (file: File) => {
    const inp = q6('input[type="file"]') as unknown as HTMLInputElement
    Object.defineProperty(inp, 'files', { value: [file], configurable: true })
    await act(async () => { inp.dispatchEvent(new win.Event('change', { bubbles: true }) as unknown as Event) })
    await settle6()
  }

  await show6(field(null, null))
  must(!!q6('[data-testid="style-drop"]') && q6('[data-testid="style-drop"]')!.textContent!.includes('拖入或选择一张图'), '空态有虚线框与文字')
  must(qa6('img').length === 0, '空态没有图')

  await choose(new File(['abc'], 'a.png', { type: 'image/png' }))
  must(calls.join() === 'PUT /novels/n1/style-image', '选择文件发 PUT：' + calls.join())
  must((bodies[0] as File).name === 'a.png', '请求体就是这个文件')
  must(changed.length === 1 && (changed[0] as typeof metaOut).hash === 'h1', 'onChanged(meta)')

  calls.length = 0
  await choose(new File(['abc'], 'a.gif', { type: 'image/gif' }))
  must(calls.length === 0, 'gif 不发请求')
  must(notice.log.at(-1)!.kind === 'err' && notice.log.at(-1)!.msg === '只收 PNG / JPEG / WebP', 'gif 提示：' + notice.log.at(-1)!.msg)
  const big = new File(['x'], 'b.png', { type: 'image/png' })
  Object.defineProperty(big, 'size', { value: 8 * 1024 * 1024 + 1 })
  await choose(big)
  must(calls.length === 0 && notice.log.at(-1)!.kind === 'err' && notice.log.at(-1)!.msg.includes('8MB'), '超过 8MB 不发请求并提示')

  changed.length = 0
  await show6(field(metaOut, 'blob:x'))
  must(qa6('img').length === 1 && q6('img')!.getAttribute('src') === 'blob:x', '有图显示 img')
  const btns = qa6('button').map((b) => b.textContent)
  must(btns.includes('替换') && btns.includes('删除'), '替换与删除两个按钮')
  await click6(qa6('button').find((b) => b.textContent === '删除')!)
  must(calls.length === 0 && !!win.document.querySelector('[data-testid="confirm-dialog"]'), '删除先弹确认')
  await click6(win.document.querySelector('[data-testid="confirm-dialog"] button:last-child') as unknown as HTMLElement)
  await settle6(60)
  must(calls.join() === 'DELETE /novels/n1/style-image', '确认后发 DELETE：' + calls.join())
  must(changed.length === 1 && changed[0] === null, 'onChanged(null)')
  await show6(null)

  // 概览页缩略图
  const secs: string[] = []
  const novel = (si: unknown) => ({
    id: 'n1', title: '药', created_at: '', updated_at: '', params: {}, style_image: si,
    memory: { assets: { characters: [], locations: [], props: [], creatures: [] },
              numbering: { next_unit: 1, next_para: 1, next_episode: 1 }, lifecycle: [],
              plot: { outline: '', chapters: [] }, constraints: [] },
    chapters: [] })
  const ovw = (si: unknown) => h(NovelOverview, { novel: novel(si), summary: null, lastChapterId: null,
    onOpenChapter: () => {}, onSection: (s: string) => secs.push(s), onDeleted: () => {} } as never)
  const { TooltipProvider } = await import('../src/components/ui/tooltip')
  await show6(h(TooltipProvider, null, ovw(metaOut) as never))
  await settle6()
  const th = q6('[data-testid="ovw-outline"] [data-testid="ovw-style"]')
  must(!!th && th.tagName === 'BUTTON' && th.getAttribute('aria-label') === '风格参考图', '概览有风格图缩略图按钮')
  await click6(th!)
  must(secs.join() === 'settings', '点了进设置页')
  await show6(h(TooltipProvider, null, ovw(null) as never))
  must(!q6('[data-testid="ovw-style"]'), '没有风格图不显示')
  await act(async () => { r.unmount() })
}

win.happyDOM.abort?.()
console.log('chapter: ALL PASS')
