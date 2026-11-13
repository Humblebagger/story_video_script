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
const { ChapterWorkflow } = await import('../src/components/workflow/ChapterWorkflow')
const { primaryFor, stepStates } = await import('../src/workflow')
import type { FlowInput, StepId, Fix } from '../src/workflow'
import type { Chapter, FilmClip, FilmSession, Novel, VersionSummary } from '../src/types'

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
for (const b of items.slice(0, 3)) must(!!b.querySelector('svg') && !b.querySelector('[data-testid="step-num"]'), '前三步打勾、不显示数字')
must(!!items[3].querySelector('[data-testid="step-num"]'), '当前步显示步号')
await click(q('[data-step="compose"]'))
must(viewed.length === 0, '点灰步不切换')
must((q('[data-testid="step-hint"]')?.textContent ?? '').includes('需要先完成第 4 步'), '说明要先完成第 4 步')
const composeBtn = q('[data-step="compose"]')!
must(composeBtn.getAttribute('aria-expanded') === 'true'
     && composeBtn.getAttribute('aria-controls') === q('[data-testid="step-hint"]')?.id, '灰步按钮标出展开状态并指向说明')
must(q('[data-step="download"]')?.getAttribute('aria-expanded') === 'false', '别的灰步是收起状态')
await act(async () => { win.document.dispatchEvent(new win.KeyboardEvent('keydown', { key: 'Escape' }) as unknown as Event) })
await settle(300)
must(!q('[data-testid="step-hint"]'), 'Esc 收起说明')
await click(q('[data-step="compose"]'))
must(!!q('[data-testid="step-hint"]'), '再点灰步重新打开说明')
await click(qa('[data-testid="step-hint"] button')[0])
must(viewed.join() === 'render', '点「去第 4 步」切到出片')
await click(q('[data-step="review"]'))
must(viewed.join() === 'render,review', '点已完成的步骤可回看')
// 说明开着时那一步解锁了：说明随之收起
await click(q('[data-step="compose"]'))
must(!!q('[data-testid="step-hint"]'), '说明打开')
const doneFilm = { clips: [{ ...clip('c1'), state: 'done' }], remaining_cny: 0, final: null } as unknown as FilmSession
await render(<Stepper states={stepStates({ ...base, film: doneFilm })} view="render" onView={(id) => viewed.push(id)} />)
await settle(300)
must(!q('[data-testid="step-hint"]'), '那一步解锁后说明自动收起')
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
await render(<PrimaryBar primary={primaryFor('storyboard', { ...base, converting: true })} onRun={() => {}} onFix={() => {}} />)
must((q('[data-testid="primary-reason"]')?.textContent ?? '').includes('正在生成'), '生成中：说原因')
must(!q('[data-testid="primary-fix"]'), '没有可去修复的地方时不显示「去修复」')
await render(<PrimaryBar primary={primaryFor('render', { ...base, film: { ...film, clips: [] } as FilmSession })}
                         onRun={() => {}} onFix={(f) => fixed.push(f)} />)
must((q('[data-testid="primary-reason"]')?.textContent ?? '').includes('还没有可出的段'), '一段都没有：说原因')
await click(q('[data-testid="primary-fix"]'))
must(fixed.length === 2 && fixed[1].openFilm === true, '去修复 = 打开出片面板')
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
flashTarget('x')
await new Promise((r) => setTimeout(r, 1000))
flashTarget('x')
await new Promise((r) => setTimeout(r, 1000))
must(target.classList.contains('fix-flash'), '1.5 秒内再定位一次：重新计时，不被上一次的定时器提前收掉')
await new Promise((r) => setTimeout(r, 700))
must(!target.classList.contains('fix-flash'), '第二次定位的 1.5 秒后去掉')
console.log('4. flashTarget ✓')

// 5. 章节工作流的跟步：未保存修改的来回不拉视图；换版本重新停到该做的那一步；⑥「回到画布重新合成」
{
  const vs = (id: string) => ({ ...ver, id })
  const chapter = { id: 'c1', title: '一', order: 1, text: '他推门。', adopted_version: 'v1',
    versions: [vs('v2'), vs('v1')], digest: null } as Chapter
  const novel = { id: 'n1', title: '药', created_at: '', updated_at: '', params: {}, memory: {}, chapters: [] } as unknown as Novel
  const doneClip = { ...clip('c1'), state: 'done' } as unknown as FilmClip
  const full = { clips: [doneClip], remaining_cny: 0, spent_cny: 0, budget_cny: 20,
    final: { state: 'done', files: ['final/E01.mp4'], report: null, error: null, detail: null } } as unknown as FilmSession
  const flowOf = (f: FilmSession | null, loaded = true) =>
    ({ film: f, compose: null, finalStale: false, reload: async () => {}, loaded, pending: false })
  let films = 0
  const wf = (p: { docVid: string | null; dirty?: boolean; flow: ReturnType<typeof flowOf>; ctl?: object; films?: (s?: string) => void }) => (
    <ChapterWorkflow novel={novel} chapter={chapter} docVid={p.docVid} doc={null} dirty={!!p.dirty} saving={false}
                     verificationFailed={false} converting={false} disabled={false} running={[]} liveJobId={null}
                     onOpenJob={() => {}} onConvert={() => {}} onOpenVersion={() => {}} onAdopt={() => {}}
                     onDeleteVersion={() => {}} onSaveText={async () => {}} onSave={() => {}} onUndo={() => {}}
                     onTextDirty={() => {}} onDelete={() => {}} onRerunDigest={() => {}}
                     storyboard={<div data-testid="board" />} openFilm={(s) => { films++; p.films?.(s) }} flow={p.flow as never} {...p.ctl} />
  )
  const on = (id: string) => !!q(`[data-step="${id}"][aria-current="step"]`)
  await render(null)
  await render(wf({ docVid: 'v1', flow: flowOf(full) }))
  must(q('[data-testid="chapter-head"]')?.textContent?.includes('一') === true, '章节头部写着章节标题')
  must(on('download') && !!q('[data-testid="download-step"]'), '整条链都完成：进章节停在 ⑥')
  await click(qa('[data-testid="download-step"] button').find((b) => (b.textContent ?? '').includes('回到画布重新合成')))
  must(on('compose') && !!q('[data-testid="board"]'), '「回到画布重新合成」先回到 ⑤（分镜视图挂上）')
  must(films === 1, '再打开画布的出片页')
  await click(q('[data-step="review"]'))
  // 卡片版式：导入、生成、下载三步的主按钮在 .chap-card 里（不固定定位），其余步骤仍是固定版
  const fixedUp = (el: Element | null) => { for (let n = el; n; n = n.parentElement) if (n.classList.contains('fixed')) return true; return false }
  must(!q('.chap-card'), '检查修改：没有卡片')
  must(!q('.chap-card [data-testid="primary-action"]') && !!q('[data-testid="primary-action"]')
       && !!q('.fixed [data-testid="primary-action"]'), '检查修改：主按钮是固定版、不在卡片里')
  await click(q('[data-step="import"]'))
  must(!!q('.chap-card [data-testid="primary-action"]') && !fixedUp(q('[data-testid="primary-action"]')), '导入原文：主按钮在卡片里且不固定')
  must(qa('[data-testid="primary-action"]').length === 1, '导入原文：只有一个主按钮')
  await click(q('[data-step="storyboard"]'))
  must(!!q('.chap-card [data-testid="primary-action"]') && !fixedUp(q('[data-testid="primary-action"]')), '生成分镜：主按钮在卡片里且不固定')
  must(qa('[data-testid="primary-action"]').length === 1, '生成分镜：只有一个主按钮')
  must(!!q('[data-testid="board"]') && !q('.chap-card [data-testid="board"]'), '生成分镜：复验报告区不进卡片')
  await click(q('[data-step="download"]'))
  must(!!q('.chap-card [data-testid="download-step"]') && !q('[data-testid="primary-action"]'), '下载：内容在卡片里，没有固定主按钮')
  await click(q('[data-step="render"]'))
  must(!q('.chap-card') && !!q('.fixed [data-testid="primary-action"]'), '出片：回到固定主按钮')
  await click(q('[data-step="review"]'))
  await render(wf({ docVid: 'v1', dirty: true, flow: flowOf(full) }))
  must(on('review'), '改动中：视图不动')
  await render(wf({ docVid: 'v1', dirty: false, flow: flowOf(full) }))
  must(on('review'), '保存 / 撤销后：「该做的那一步」没往前走，视图不跳到 ⑥')
  await render(wf({ docVid: 'v2', flow: flowOf(null, false) }))
  must(on('review'), '新版本的出片状态没读到之前不动')
  await render(wf({ docVid: 'v2', flow: flowOf(null) }))
  must(on('render'), '换到没出过片的版本：重新停到 ④，不停在灰掉的 ⑥ 或用户之前看的步骤')
  await render(null)
  console.log('5. ChapterWorkflow 跟步 ✓')

  // 5a. 受控（给了 onStep）：回到画布重新合成 = 只调一次 openFilm('compose')，不先 onStep（否则成两次 push）
  {
    const steps: string[] = []; const opened: (string | undefined)[] = []
    await render(wf({ docVid: 'v1', flow: flowOf(full), films: (s) => opened.push(s),
      ctl: { step: 'download', onStep: (s: string, how: string) => steps.push(`${how}:${s}`) } }))
    await click(qa('[data-testid="download-step"] button').find((b) => (b.textContent ?? '').includes('回到画布重新合成')))
    await settle()
    must(opened.length === 1 && opened[0] === 'compose', `受控 recompose 应只 openFilm('compose')，实际 ${opened}`)
    must(!steps.some((x) => x.startsWith('push')), `受控 recompose 不应先 push 步骤：${steps}`)
    await render(null)
  }
  console.log('5a. 受控 recompose 单次导航 ✓')

  // 5b. 助手跳进还没打开的章：版本与出片状态后到，也停在请求的那一步，不被「该做的那一步」盖掉；之后照常跟步
  const { requestStep } = await import('../src/lib/assistantBridge')
  requestStep('c1', 'review')
  await render(wf({ docVid: null, flow: flowOf(null) }))           // 刚打开：版本还没摆出来
  must(on('review'), '挂载时取走跳转请求')
  await render(wf({ docVid: 'v1', flow: flowOf(null, false) }))    // 版本到了，出片状态在读
  must(on('review'), '出片状态没读到：停在请求的那一步')
  await render(wf({ docVid: 'v1', flow: flowOf(full) }))           // 落地：该做的是 ⑥
  must(on('review'), '落地后仍停在请求的那一步')
  await render(wf({ docVid: 'v2', flow: flowOf(null) }))
  must(on('render'), '请求用过即清：之后换版本照常停到该做的那一步')
  await render(null)
  console.log('5b. 助手跳转进未打开的章 ✓')
}

// 6. 下载页：导出剪辑工程按钮
{
  const { DownloadStep } = await import('../src/components/workflow/DownloadStep')
  const done = { clips: [], remaining_cny: 0, final: { state: 'done', files: ['final/E01.mp4'], report: null, error: null, detail: null } } as unknown as FilmSession
  const cp = (o: Record<string, unknown>) => ({ lines: 0, final: done.final, ...o }) as never
  const dl = (compose: never) => render(<DownloadStep version={{ nid: 'n1', cid: 'c1', vid: 'v1' }} film={done} compose={compose} onOpenFilm={() => {}} />)
  const btn = () => q('[data-testid="export-fcpxml"]') as unknown as HTMLButtonElement
  const realFetch = globalThis.fetch
  const urls: string[] = []
  let status = 200
  let failBody: unknown = { detail: '成片已过期' }
  let disposition = "attachment; filename=\"x.zip\"; filename*=utf-8''%E8%8D%AF.zip"
  globalThis.fetch = (async (u: string) => {
    urls.push(String(u))
    if (status !== 200) return new Response(JSON.stringify(failBody), { status })
    return new Response('zipdata', { status: 200, headers: { 'content-disposition': disposition } })
  }) as never
  const g2 = globalThis as unknown as { URL: { createObjectURL: (b: Blob) => string; revokeObjectURL: (u: string) => void } }
  const origCreate = g2.URL.createObjectURL, origRevoke = g2.URL.revokeObjectURL
  g2.URL.createObjectURL = () => 'blob:x'
  const revoked: string[] = []
  g2.URL.revokeObjectURL = (u) => { revoked.push(u) }
  const names: string[] = []
  const origCreateEl = win.document.createElement.bind(win.document)
  win.document.createElement = ((tag: string) => {
    const el = origCreateEl(tag)
    if (tag === 'a') (el as unknown as { click: () => void }).click = () => { names.push((el as unknown as HTMLAnchorElement).download) }
    return el
  }) as never

  await dl(cp({ exportable: true, export_reason: null }))
  must(!btn().disabled && btn().textContent === '导出剪辑工程（FCPXML）', '可导出：按钮可点、文字正确')
  must(text().includes('可导入 Final Cut Pro、DaVinci Resolve'), '可导出：旁边有说明')
  must(btn().className.includes('border'), '导出按钮是 outline 样式')
  await click(btn())
  await settle(60)
  must(urls.some((u) => u.endsWith('/render/export.zip?lang=zh')), '点了之后请求 export.zip，带当前界面语言 lang=zh')
  must(names[0] === '药.zip', '文件名取 filename*（小写 utf-8 也认）并解码')
  await settle(60)
  must(revoked.length === 0, '点击后不能立刻回收 blob 地址')
  await settle(1100)
  must(revoked.length === 1, '1 秒后回收 blob 地址')

  // 纯 ASCII 标题：服务端只带 filename="…"（也可能同时带 filename*），大小写不敏感
  disposition = 'attachment; FILENAME="My_Novel-Ch_1-ab12cd34.zip"'
  await click(btn())
  await settle(60)
  must(names[names.length - 1] === 'My_Novel-Ch_1-ab12cd34.zip', '只有 filename= 时取其值')
  await settle(1100)
  disposition = "attachment; filename=\"x.zip\"; filename*=utf-8''%E8%8D%AF.zip"

  status = 409
  await click(btn())
  await settle(60)
  must((q('[data-testid="export-error"]')?.textContent ?? '').includes('成片已过期'), '失败：就地显示后端 detail')
  must(!btn().disabled, '失败后按钮恢复')
  // 带代码的导出错误：按界面语言渲染，切语言跟着变
  const { en } = await import('../src/i18n/en')
  const { zh } = await import('../src/i18n/zh')
  const { useI18n } = await import('../src/i18n/core')
  let setLoc: (l: 'zh' | 'en') => void = () => {}
  function Cap() { setLoc = useI18n().setLocale; return null }
  const coded = { code: 'export.no_ffmpeg', params: {}, message: zh.srv.export.no_ffmpeg }
  failBody = { detail: coded }
  await act(async () => { root.render(<I18nProvider initial="en"><Cap />
    <DownloadStep version={{ nid: 'n1', cid: 'c1', vid: 'v1' }} film={done} compose={cp({ exportable: true, export_reason: null })} onOpenFilm={() => {}} />
    </I18nProvider>) })
  await act(async () => { setLoc('en') })
  await click(btn())
  await settle(60)
  must(text().includes(en.srv.export.no_ffmpeg) && !text().includes(zh.srv.export.no_ffmpeg), '导出错误（英文）')
  await act(async () => { setLoc('zh') })
  await settle()
  must(text().includes(zh.srv.export.no_ffmpeg) && !text().includes(en.srv.export.no_ffmpeg), '导出错误切中文跟着变')
  failBody = { detail: '成片已过期' }

  await dl(cp({ exportable: false, export_reason: 'no_timeline' }))
  must(btn().disabled && text().includes('重新合成一次即可导出（会复用已有的配音与规整结果，不花钱）'), 'no_timeline：禁用并说明')
  await dl(cp({ exportable: false, export_reason: 'stale' }))
  must(btn().disabled && text().includes('成片已过期，请先重新合成'), 'stale：禁用并说明')
  await dl(cp({ exportable: false, export_reason: 'busy' }))
  must(btn().disabled && text().includes('正在合成'), 'busy：禁用并说明')
  await dl(null as never)
  must(btn().disabled, '没有 compose 数据：禁用')

  globalThis.fetch = realFetch
  g2.URL.createObjectURL = origCreate; g2.URL.revokeObjectURL = origRevoke
  win.document.createElement = origCreateEl as never
  await render(null)
  console.log('6. 下载页导出按钮 ✓')
}

// 7. 章后整理失败：有 error_msg 直接接在标签后（不嵌套「失败（…）」）；旧数据照旧；关闭提示不含变量名
{
  const { VersionBar } = await import('../src/components/workflow/VersionBar')
  const { en } = await import('../src/i18n/en')
  const { zh } = await import('../src/i18n/zh')
  const { useI18n } = await import('../src/i18n/core')
  let setLoc: (l: 'zh' | 'en') => void = () => {}
  function Cap() { setLoc = useI18n().setLocale; return null }
  const bar = (digest: unknown) => (
    <I18nProvider initial="zh"><Cap />
      <VersionBar chapter={{ id: 'c1', title: '一', order: 1, text: '', adopted_version: null, versions: [], digest } as unknown as Chapter}
                  versionId={null} onOpenVersion={() => {}} onAdopt={() => {}} onDeleteVersion={() => {}} onRerunDigest={() => {}} />
    </I18nProvider>)
  const txt = () => q('.chap__digest')?.textContent ?? ''
  await act(async () => { root.render(bar({ status: 'failed', at: '', error: '旧中文',
    error_msg: { code: 'chapter.digest.failed', params: {}, ref: 'K7Q2M9XD' } })) })
  await act(async () => { setLoc('zh') })
  must(txt().includes('章后整理：没有完成，可以稍后重跑；仍失败请联系管理员（参考编号 K7Q2M9XD）') && !txt().includes('失败（'),
       '章后整理失败（中文）：按代码、带编号、不嵌套')
  await act(async () => { setLoc('en') })
  must(txt().includes(en.srv.chapter.digest.failed) && txt().includes('reference K7Q2M9XD') && !txt().includes('failed ('),
       '章后整理失败（英文）')
  await act(async () => { root.render(bar({ status: 'failed', at: '', error: '旧中文' })) })
  await act(async () => { setLoc('zh') })
  must(txt().includes('失败（旧中文）'), '只有 error：照旧显示')
  await act(async () => { root.render(bar({ status: 'off', at: '' })) })
  must(txt().includes('未开启，可在小说页手动补') && !txt().includes('STORYBOARD_CHAPTER_DIGEST'), 'off（中文）不含变量名')
  await act(async () => { setLoc('en') })
  must(txt().includes(en.flow.digest.off) && !txt().includes('STORYBOARD_CHAPTER_DIGEST'), 'off（英文）不含变量名')
  must(!zh.flow.digest.off.includes('STORYBOARD') && !en.flow.digest.off.includes('STORYBOARD'), '文案里没有变量名')
  await render(null)
  console.log('7. 章后整理失败按代码渲染 ✓')
}

// 收尾：卸载并关掉 happy-dom 的窗口（清掉它的定时器），进程自然退出
await act(async () => { root.unmount() })
await win.happyDOM.close()
console.log('\nALL PASS')
