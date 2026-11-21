/** 路由集成：桩后端加内存路由，从任意深链接起步（设计 §12.3）。跑法：npm test */
import { Window } from 'happy-dom'

const win = new Window({ url: 'http://localhost:5173' })
const g = globalThis as Record<string, unknown>
for (const k of ['window', 'document', 'navigator', 'location', 'HTMLElement',
                 'Element', 'Node', 'Event', 'CustomEvent', 'getComputedStyle',
                 'localStorage', 'sessionStorage', 'KeyboardEvent', 'MouseEvent', 'matchMedia',
                 'ResizeObserver', 'MutationObserver']) {
  Object.defineProperty(g, k, { value: (win as unknown as Record<string, unknown>)[k], writable: true, configurable: true })
}
g.IS_REACT_ACT_ENVIRONMENT = true
g.IntersectionObserver ??= class { observe() {} unobserve() {} disconnect() {} takeRecords() { return [] } }
g.requestAnimationFrame ??= (cb: (t: number) => void) => setTimeout(() => cb(Date.now()), 16)
g.cancelAnimationFrame ??= (id: number) => clearTimeout(id)
g.Notification = class { static permission = 'denied'; static requestPermission = async () => 'denied' }

/* ---------- 桩后端：一个用户的一本小说、一章、一版 ---------- */
interface StubVersion {
  id: string; created_at: string; edited_at: string | null; status: string
  result: unknown; verification: unknown; error: string | null
}
interface StubChapter {
  id: string; title: string; order: number; text: string
  adopted_version: string | null; versions: StubVersion[]; digest: unknown
}
type Card = { id: string; name?: string }
interface StubNovel {
  id: string; title: string; params: Record<string, unknown>; updated_at: string
  chapters: StubChapter[]
  memory: {
    assets: Record<string, Card[]>
    numbering: { next_unit: number; next_para: number; next_episode: number }
    lifecycle: Record<string, unknown>[]
    plot: { outline: string; chapters: { chapter_id: string; synopsis: string; origin: string }[] }
    constraints: Record<string, unknown>[]
  }
}

const KINDS = ['characters', 'locations', 'props', 'creatures']
const counts = (a: Record<string, Card[]>) =>
  Object.fromEntries(KINDS.map((k) => [k, (a[k] ?? []).length]))
const vsum = (v: StubVersion) => ({
  id: v.id, created_at: v.created_at, edited_at: v.edited_at, status: v.status,
  units: 1, episodes: 1, shots: 1, has_quality_report: false,
  verification_status: (v.verification as { status?: string } | null)?.status ?? null })
const chapterView = (c: StubChapter) => ({
  ...c, versions: [...c.versions].reverse().map(vsum) })
const chapterSummary = (c: StubChapter) => ({
  id: c.id, title: c.title, order: c.order, adopted_version: c.adopted_version,
  legacy_numbering: false, chars: c.text.length,
  versions: [...c.versions].reverse().map(vsum),
  latest_status: c.versions.length ? c.versions[c.versions.length - 1].status : null,
  digest: c.digest })
const novelView = (n: StubNovel) => ({ ...n, chapters: n.chapters.map(chapterSummary) })

const VERIFIED = { status: 'verified', findings: [], coverage: { selected: ['u0001'], covered: ['u0001'], waived: [], failed: [] } }

const DOC = {
  meta: { schema_version: '0.4', title: '药', fidelity_mode: 'faithful',
          style: { style_prefix: '写实' }, video: { aspect_ratio: '9:16' },
          narration: { mode: 'selective' } },
  source: { work_title: '药', chapter: '第一章',
            units: [{ id: 'u0001', text: '他推门。', kind: 'action' }] },
  assets: {
    characters: [{ id: 'C01', name: '华老栓', aliases: ['老栓'],
                   appearance: { age: '五十余岁', face: '瘦削' },
                   outfits: [{ id: 'default', description: '灰布旧棉袄，黑布鞋' }],
                   visual_prompt: '驼背老者' },
                 // 有两套服装：挂卡时必须自动选中其一，否则 lint 报错
                 { id: 'C02', name: '康大叔', aliases: ['刽子手'],
                   // schema：outfits 只有 {id, description}，且拒绝未知字段
                   outfits: [{ id: 'default', description: '青布短打，腰束皮带' },
                             { id: 'loose_black', description: '玄色宽大外褂，散腰' }] }],
    locations: [{ id: 'S01', name: '茶馆', interior_exterior: 'interior' }],
    props: [{ id: 'P01', name: '灯笼',
              states: [{ id: 'lit', description: '烛火点亮，纸面透暖黄' },
                       { id: 'dark', description: '熄灭，纸面发灰' }] },
            // 无状态集：挂上去不许带 state
            { id: 'P02', name: '一包洋钱' }],
    // 生物卡挂进 characters[]，但不得带 outfit
    creatures: [{ id: 'A01', name: '乌鸦', aliases: ['老鸦'] }],
  },
  episodes: [{ id: 'E01', title: '开端', shots: [{
    id: 'E01-SH001', duration_sec: 5, shot_size: 'wide', action: '推门',
    location_ref: 'S01',
    characters: [{ ref: 'C01', outfit: 'default', expression: '疲惫' }],
    prop_refs: [{ ref: 'P01', state: 'lit' }],
    source: { unit_refs: ['u0001'], derivation: 'explicit' } }] }],
}

const users: Record<string, { role?: 'admin' }> = { alice: {}, root: { role: 'admin' } }
const userOf = (name: string) => ({ id: name, username: name, created_at: '', ...users[name] })
let novel: StubNovel
function resetData() {
  novel = {
    id: 'n1', title: '药', params: { aspect_ratio: '9:16', art_style: 'realistic' }, updated_at: '',
    chapters: [{ id: 'c1', title: '第一章', order: 1, text: '他推门。', adopted_version: 'v1', digest: null,
                 versions: [{ id: 'v1', created_at: '', edited_at: null, status: 'succeeded',
                              result: JSON.parse(JSON.stringify(DOC)), verification: VERIFIED, error: null }] }],
    memory: { assets: {}, numbering: { next_unit: 2, next_para: 2, next_episode: 2 }, lifecycle: [],
              plot: { outline: '', chapters: [] }, constraints: [] },
  }
}
const unhandled = new Set<string>()
/** 测试用：章节读取失败，detail 为消息对象（格式同后端 to_detail） */
let submitFail = false
let chapterFail: { status: number; detail: unknown } | null = null
/** 测试用：让章节与版本的读取慢下来（lag 毫秒），或卡在 gate 上直到放行 */
let lag = 0
let gate: Promise<void> | null = null
/** 按版本号卡住读版本；me 与任务轮询也可卡住 */
const vgate: Record<string, Promise<void>> = {}
let meGate: Promise<void> | null = null
let jobGate: Promise<void> | null = null
let adminSvcCalls = 0
/** 非空时 /admin/service 卡在它上面（模拟慢响应） */
let svcGate: Promise<void> | null = null
/** 放行后 /admin/service 回 401（旧会话迟到的失效响应） */
let svcUnauth = false
const jobsById: Record<string, unknown> = {}
let jobsList: unknown[] = []
/** 本人的出片任务（GET /render/tasks 原样返回） */
let filmTasks: unknown[] = []
/** 队列里每项是一个 promise：对应的 /render/tasks 请求等它完成才返回（空项即刻返回） */
const tasksHold: (Promise<void> | undefined)[] = []
/** 收到的取消请求（路径） */
const cancelCalls: string[] = []
/** 取消请求体（expect）；服务端此刻认为这条是什么种类（与 expect 不符回 409 film.cancel.kind_changed；null = 不校验） */
const cancelBodies: unknown[] = []
let serverCancelKind: 'free' | 'paid' | null = null
/** 巡检接口的人为延迟（毫秒）与同时在途的请求数 */
let tasksDelay = 0
let jobsDelay = 0
const flight = { tasks: 0, tasksMax: 0, jobs: 0, jobsMax: 0, tasksCalls: 0, jobsCalls: 0, rawTasks: 0 }
/** 出片会话桩：给了就返回（画布出片页能显示合成区）；读取次数用来断言画布被通知刷新 */
let filmSession: unknown = null
let sessionGets = 0
g.fetch = async (url: string, init?: { method?: string; body?: string; headers?: Record<string, string> }) => {
  const path = String(url).replace(/^\/api/, '').split('?')[0]
  const method = init?.method ?? 'GET'
  const json = (data: unknown) => ({ ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(data)) })
  const err = (status: number, detail: unknown) => ({ ok: false, status, statusText: '',
    text: async () => JSON.stringify({ detail }), json: async () => ({ detail }) })
  if (path === '/healthz') return json({ status: 'ok', first_run: false })
  if (path === '/admin/service' && method === 'GET') {
    adminSvcCalls += 1
    const unauth = svcUnauth; svcUnauth = false   // 只有第一个（旧会话的）请求回 401
    if (svcGate) await svcGate
    if (unauth) return { ok: false, status: 401, text: async () => '{"detail":"未登录"}', json: async () => ({ detail: '未登录' }) }
    if (!/tok-root/.test(init?.headers?.Authorization ?? '')) return err(403, '需要管理员')
    return json({ model: 'stub-model', review_model: null, api_key_configured: false })
  }
  if (path === '/auth/login' && method === 'POST') {
    const b = JSON.parse(init!.body!)
    return users[b.username] ? json({ token: `tok-${b.username}`, user: userOf(b.username) }) : err(401, '用户名或密码不正确')
  }
  if (path === '/render/tasks') flight.rawTasks += 1     // 含未登录被拒的请求
  const h = init?.headers?.Authorization ?? ''
  const who = h.startsWith('Bearer tok-') ? h.slice(11) : null
  if (!who || !users[who]) return { ok: false, status: 401, text: async () => '{"detail":"未登录"}', json: async () => ({ detail: '未登录' }) }
  if (path === '/auth/me') { if (meGate) await meGate; return json(userOf(who)) }
  if (path === '/jobs') {
    const snap = jobsList
    flight.jobsCalls += 1; flight.jobs += 1; flight.jobsMax = Math.max(flight.jobsMax, flight.jobs)
    try { if (jobsDelay) await new Promise((r) => setTimeout(r, jobsDelay)) } finally { flight.jobs -= 1 }
    return json({ jobs: snap })
  }
  if (path === '/render/tasks') {
    const snap = filmTasks      // 请求发出时的快照；可控完成顺序的测试靠 tasksHold 让它晚点返回
    flight.tasksCalls += 1; flight.tasks += 1; flight.tasksMax = Math.max(flight.tasksMax, flight.tasks)
    try {
      const hold = tasksHold.shift()
      if (hold) await hold
      if (tasksDelay) await new Promise((r) => setTimeout(r, tasksDelay))
    } finally { flight.tasks -= 1 }
    return json({ tasks: snap })
  }
  if (method === 'POST' && /\/render\/(clips|free)\/[^/]+\/cancel$/.test(path)) {
    cancelCalls.push(path)
    const body = init?.body ? JSON.parse(init.body) : null
    cancelBodies.push(body)
    if (serverCancelKind && body?.expect !== serverCancelKind) return err(409, { code: 'film.cancel.kind_changed', params: {} })
    return json({ cancel_outcome: 'abandoned', clips: [], free: [] })
  }
  const jm = path.match(/^\/jobs\/([^/]+)$/)
  if (jm && method === 'GET') {
    if (jobGate) await jobGate
    return jobsById[jm[1]] ? json(jobsById[jm[1]]) : err(404, 'stub')
  }
  if (path === '/render/keyframes' && method === 'POST') return json({ keyframes: [] })
  if (path === '/admin/overview' && method === 'GET') {
    return json({ users: 2, active_7d: 1, tokens_30d: 0, cost_30d: 0, running: 0, failed_7d: 0, daily: [], unpriced_models: [] })
  }
  if (path === '/admin/users' && method === 'GET') return json({ users: [] })
  if (path === '/admin/jobs' && method === 'GET') return json({ running: [], failed: [] })
  if (path === '/admin/usage' && method === 'GET') {
    return json({ group: 'user', days: 30, rows: [], per_k_chars: { n: 0, mean: null, p90: null }, unpriced_models: [] })
  }
  if (path === '/admin/errors' && method === 'GET') return json({ errors: [] })
  if (path === '/admin/audit' && method === 'GET') return json({ audit: [] })
  if (path === '/admin/pricing' && method === 'GET') return json({ currency: 'USD', updated_at: null, models: {} })
  if (path === '/novels' && method === 'GET') return json({ novels: [{ id: novel.id, title: novel.title, updated_at: '', chapters: novel.chapters.length, asset_counts: counts(novel.memory.assets) }] })
  if (submitFail && method === 'POST' && path === '/novels/n1/chapters/c1/versions') {
    return err(422, { code: 'chapter.no_text', params: {}, message: '本章还没有原文' })
  }
  const m = path.match(/^\/novels\/([^/]+)(?:\/chapters\/([^/]+)(?:\/versions\/([^/]+)(\/.*)?)?)?(\/summary)?$/)
  if (m && method === 'GET') {
    const [, nid, cid, vid, rest, summary] = m
    if (nid !== novel.id) return err(404, '小说不存在')
    if (summary) return err(404, 'stub')                                  // 费用表拿不到就不显示
    if (!cid) return json(novelView(novel))
    if (lag) await new Promise((r) => setTimeout(r, lag))
    if (vid && gate) await gate
    if (vid && vgate[vid]) await vgate[vid]
    const c = novel.chapters.find((x) => x.id === cid)
    if (!c) return err(404, '章节不存在')
    if (chapterFail && !vid) return err(chapterFail.status, chapterFail.detail)
    if (!vid) return json(chapterView(c))
    const v = c.versions.find((x) => x.id === vid)
    if (!v) return err(404, '版本不存在')
    if (!rest) return json({ ...v, novel_id: nid, chapter_id: cid, params: {}, quality_report: null })
    if (rest === '/keyframes') return json({ shots: [] })
    if (rest === '/render/session' && filmSession) { sessionGets += 1; return json(filmSession) }
    return err(404, 'stub')                                              // 出片会话等：还没建
  }
  unhandled.add(`${method} ${path}`)
  return err(404, 'stub')
}

/* ---------- 驱动 ---------- */
const { act } = await import('react')
const { createRoot } = await import('react-dom/client')
const { createMemoryRouter } = await import('react-router')
const { routes } = await import('../src/routes')
const { AppRoot } = await import('../src/AppRoot')
const { I18nProvider } = await import('../src/i18n')
const { useI18n, setCurrentLocale } = await import('../src/i18n/core')
let setLoc: (l: 'zh' | 'en') => void = () => {}
function Grab() { setLoc = useI18n().setLocale; return null }
const { setSession, clearSession } = await import('../src/auth')
type Router = ReturnType<typeof createMemoryRouter>

const doc = win.document as unknown as Document
const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }
const settle = async (ms = 80) => { await act(async () => { await new Promise((r) => setTimeout(r, ms)) }) }

/** 从某个地址起一个全新的应用；who 为空 = 未登录 */
async function boot(path: string, who?: string, cached?: Record<string, unknown>) {
  resetData()
  win.localStorage.clear()
  clearSession()
  jobsList = []
  filmTasks = []
  filmSession = null; serverCancelKind = null; tasksDelay = 0; jobsDelay = 0
  for (const k of Object.keys(jobsById)) delete jobsById[k]
  if (who) setSession(`tok-${who}`, (cached ?? userOf(who)) as ReturnType<typeof userOf>)
  const container = doc.createElement('div')
  doc.body.appendChild(container)
  const root = createRoot(container)
  const router: Router = createMemoryRouter(routes, { initialEntries: [path] })
  await act(async () => { root.render(<I18nProvider initial="zh"><Grab /><AppRoot router={router} /></I18nProvider>) })
  await settle(150)
  const here = () => router.state.location.pathname + router.state.location.search
  const has = (s: string) => container.innerHTML.includes(s)
  const q = (sel: string) => container.querySelector(sel) as unknown as HTMLElement | null
  const done = async () => { await act(async () => { root.unmount() }); container.remove() }
  return { router, container, here, has, q, done }
}
const click = async (el: HTMLElement) => { await act(async () => { el.click() }); await settle() }
const button = (box: HTMLElement, text: string) =>
  [...box.querySelectorAll('button')].find((b) => (b.textContent ?? '').trim() === text) as unknown as HTMLElement | undefined
const inputSetter = Object.getOwnPropertyDescriptor(win.HTMLInputElement.prototype, 'value')!.set!
const typeIn = async (el: HTMLElement, text: string) => {
  await act(async () => {
    inputSetter.call(el, text)
    el.dispatchEvent(new win.Event('input', { bubbles: true }) as unknown as Event)
  })
  await settle()
}
/** 在已弹出的登录框里登录（桩后端对任意密码放行） */
async function loginAs(name: string, pw: string) {
  const [u, p] = [...doc.body.querySelectorAll('.login__field input')] as unknown as HTMLElement[]
  await typeIn(u, name)
  await typeIn(p, pw)
  await click(doc.body.querySelector('button[type="submit"]') as unknown as HTMLElement)
}

// ===== 用例（各 Task 往下追加，编号与设计 §12.3 对应）=====

// §12.3-2 /novels/n1：加载完 replace 到默认分区
{
  const a = await boot('/novels/n1', 'alice')
  must(a.here() === '/novels/n1/overview', `无分区应落到概览，实际 ${a.here()}`)
  must(a.router.state.historyAction === 'REPLACE', '默认分区是 replace')
  await a.done()
}
// 有待确认的人物状态提议时到「剧情与记忆」
{
  const a = await boot('/novels/n1', 'alice')
  novel.memory.lifecycle.push({ id: 'l1', character_id: 'C01', type: 'deceased', detail: '病死',
    since: { chapter_id: 'c1', unit_ref: 'u0001' }, evidence_quote: '他推门。', origin: 'model',
    status: 'proposed', written_by: { chapter_id: 'c1', version_id: 'v1' } })
  await act(async () => { await a.router.navigate('/') })
  await settle()
  await act(async () => { await a.router.navigate('/novels/n1') })
  await settle(150)
  must(a.here() === '/novels/n1/memory', `有提议时应落到剧情与记忆，实际 ${a.here()}`)
  await a.done()
}
console.log('2. 小说无分区 → replace 到默认分区 ✓')

// §12.3-4（小说部分）不存在的小说：回首页
{
  const a = await boot('/novels/nope/overview', 'alice')
  must(a.here() === '/', `不存在的小说应回首页，实际 ${a.here()}`)
  must(a.router.state.historyAction === 'REPLACE', '失败回退是 replace')
  await a.done()
}
console.log('4a. 不存在的小说 → 回首页 ✓')

// 404 页
{
  const a = await boot('/what/ever', 'alice')
  must(!!a.q('[data-testid="not-found"]'), '未知地址显示 404 页')
  await click(button(a.container, '回到书架')!)
  must(a.here() === '/', '404 页「回到书架」回首页')
  await a.done()
}
console.log('404 页 ✓')

// §12.3-5 未登录打开深链接：着陆页加登录框；登录后停在原地址；关掉登录框后不再自动弹出
{
  const a = await boot('/novels/n1/props')
  must(a.here() === '/novels/n1/props', '未登录不改地址')
  must(!!doc.body.querySelector('[role="dialog"]'), '未登录深链接自动打开登录框')
  const close = [...doc.body.querySelectorAll('[role="dialog"] button')]
    .find((b) => b.getAttribute('aria-label') === '关闭') as unknown as HTMLElement | undefined
  must(!!close, '登录框应有关闭按钮')
  await click(close!)
  await settle(300)
  must(!doc.body.querySelector('[role="dialog"]'), '关闭按钮应关掉登录框')
  await act(async () => { await a.router.navigate('/novels/n1/props', { replace: true }) })
  await settle()
  must(!doc.body.querySelector('[role="dialog"]'), '关掉后同一地址不再自动弹出')
  await a.done()
}
{
  const a = await boot('/novels/n1/props')
  await loginAs('alice', 'pw')
  await settle(600)                                                     // 首页淡出 ≤400ms
  must(a.here() === '/novels/n1/props' && a.has('道具'), `登录后应停在原深链接，实际 ${a.here()}`)
  await a.done()
}
console.log('5. 未登录深链接 → 登录后回到原地址，关掉后不重复弹 ✓')

// §12.3-6 非管理员访问 /admin：回首页
{
  const a = await boot('/admin', 'alice')
  must(a.here() === '/' && !a.has('运营后台'), `普通用户不能停在后台，实际 ${a.here()}`)
  await a.done()
  const b = await boot('/admin', 'root')
  must(b.here() === '/admin' && b.has('运营后台'), '管理员可以直接打开后台')
  await b.done()
}
console.log('6. 非管理员 /admin → 回首页 ✓')

// 后台每页有独立地址：深链接（等于刷新）、导航、后退、筛选、不规范地址、返回产品
{
  const h2 = (x: { q: (sel: string) => HTMLElement | null }) => x.q('.adm__pagehead h2')?.textContent
  const a = await boot('/admin/jobs?state=failed', 'root')
  must(a.here() === '/admin/jobs?state=failed' && h2(a) === '任务', `深链接到带筛选的任务页，实际 ${a.here()} / ${h2(a)}`)
  must(button(a.container, '失败')?.getAttribute('aria-pressed') === 'true', '筛选取自地址')
  must(doc.title === '任务 · 运营后台 — Inkreel', `后台页的标题，实际 ${doc.title}`)
  must(!a.q('[data-testid="app-shell"]') && !!a.q('[data-testid="admin-shell"]'), '后台是独立的一屏，不套产品外壳')
  await click(a.q('[data-testid="admin-nav-users"]')!)
  must(a.here() === '/admin/users' && a.router.state.historyAction === 'PUSH' && h2(a) === '用户', `点导航换页是 push，实际 ${a.here()}`)
  await act(async () => { await a.router.navigate(-1) })
  await settle()
  must(a.here() === '/admin/jobs?state=failed' && h2(a) === '任务', `后退回到上一页并带着筛选，实际 ${a.here()}`)
  await click(button(a.container, '全部')!)
  must(a.here() === '/admin/jobs' && a.router.state.historyAction === 'REPLACE', `改筛选是 replace，实际 ${a.here()}`)
  await a.done()
  const b = await boot('/admin/overview', 'root')
  must(b.here() === '/admin' && h2(b) === '运营概览', `/admin/overview 规范化到 /admin，实际 ${b.here()}`)
  await b.done()
  const c = await boot('/admin/usage?days=7&group=model&x=1', 'root')
  must(c.here() === '/admin/usage?group=model&days=7' && h2(c) === '用量与花费', `乱序与多余参数规范化，实际 ${c.here()}`)
  await c.done()
  const d = await boot('/admin/nope', 'root')
  must(!!d.q('[data-testid="not-found"]'), '后台下面不存在的页是 404')
  await d.done()
  const e = await boot('/admin/users', 'alice')
  must(e.here() === '/' && !e.has('运营后台'), `普通用户打不开后台子页，实际 ${e.here()}`)
  await e.done()
  // 返回产品：回到进后台之前在产品里的那一页（后台里翻过页也一样）
  const f = await boot('/novels/n1/props', 'root')
  await act(async () => { await f.router.navigate('/admin') })
  await settle(150)
  await click(f.q('[data-testid="admin-nav-audit"]')!)
  must(f.here() === '/admin/audit', `先在后台里换一页，实际 ${f.here()}`)
  await click(f.q('[data-testid="admin-back"]')!)
  await settle(150)
  must(f.here() === '/novels/n1/props' && !!f.q('[data-testid="app-shell"]'), `返回产品回到进后台之前的页，实际 ${f.here()}`)
  await f.done()
  const k = await boot('/admin/errors', 'root')
  await click(k.q('[data-testid="admin-back"]')!)
  await settle(150)
  must(k.here() === '/', `直接打开后台时返回产品回首页，实际 ${k.here()}`)
  await k.done()
}
console.log('后台各页独立地址 / 后退 / 筛选 / 规范化 / 返回产品 ✓')

// 后台不向非管理员透出：未登录、普通用户、角色未确认时都没有后台的界面与标题，后台代码也不加载
{
  const adminDom = (x: { q: (sel: string) => HTMLElement | null }) =>
    x.q('[data-testid="admin-shell"]') ?? x.q('.adm') ?? x.q('.adm-side') ?? x.q('.adm-top')
  const clean = (x: { q: (sel: string) => HTMLElement | null; has: (s: string) => boolean }) =>
    !adminDom(x) && !x.has('运营后台') && !x.has('运营概览') && !doc.title.includes('后台') && !doc.title.includes('任务 ·')
  for (const url of ['/admin', '/admin/jobs?state=failed']) {
    // 未登录：停在着陆页（弹登录框），没有后台
    const a = await boot(url)
    must(a.here() === url && clean(a) && !a.q('[data-testid="admin-loading"]'), `未登录打开 ${url}：没有后台界面，标题不含后台，实际标题 ${doc.title}`)
    await a.done()
    // 普通用户：me() 回来之前只有一块不带字的骨架；回来之后 replace 回首页，没有提示条泄露后台的存在
    let release!: () => void
    meGate = new Promise<void>((r) => { release = r })
    const b = await boot(url, 'alice')
    must(b.here() === url && clean(b) && !!b.q('[data-testid="admin-loading"]') && !b.q('[data-testid="app-shell"]'),
         `普通用户打开 ${url}、角色未确认：只有骨架，实际标题 ${doc.title}`)
    release(); meGate = null
    await settle(300)
    must(b.here() === '/' && b.router.state.historyAction === 'REPLACE' && clean(b) && !!b.q('[data-testid="app-shell"]'),
         `普通用户打开 ${url}：replace 回首页且没有后台界面，实际 ${b.here()}`)
    must(!doc.body.textContent!.includes('管理员'), '回首页时不提示「需要管理员权限」')
    await b.done()
  }
  // 管理员：角色确认之前同样只有骨架、不设后台标题；确认后才出现后台
  let release!: () => void
  meGate = new Promise<void>((r) => { release = r })
  const c = await boot('/admin/jobs?state=failed', 'root')
  must(clean(c) && !!c.q('[data-testid="admin-loading"]'), `管理员角色未确认：只有骨架，实际标题 ${doc.title}`)
  release(); meGate = null
  await settle(300)
  must(!!c.q('[data-testid="admin-shell"]') && !c.q('[data-testid="admin-loading"]') && doc.title === '任务 · 运营后台 — Inkreel',
       `管理员确认后出现后台，实际标题 ${doc.title}`)
  // 离开后台后标题跟着换回产品的
  await click(c.q('[data-testid="admin-back"]')!)
  await settle(150)
  must(c.here() === '/' && !doc.title.includes('后台'), `返回产品后标题不再是后台的，实际 ${doc.title}`)
  await c.done()
  // 入口只给管理员：侧边栏的「管理」按钮与账号菜单里的「管理」项
  const menuHas = async (x: Awaited<ReturnType<typeof boot>>) => {
    await act(async () => {
      x.q('[data-testid="account-menu"]')!.dispatchEvent(
        new win.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }) as unknown as Event)
    })
    await settle()
    return [...doc.body.querySelectorAll('[role="menuitem"]')].some((el) => (el.textContent ?? '').trim() === '管理')
  }
  const d = await boot('/', 'alice')
  must(!button(d.container, '管理') && !d.q('[aria-label="管理"]'), '普通用户的侧边栏没有「管理」入口')
  must(!(await menuHas(d)), '普通用户的账号菜单没有「管理」项')
  await d.done()
  const e = await boot('/', 'root')
  must(!!button(e.container, '管理'), '管理员的侧边栏有「管理」入口')
  must(await menuHas(e), '管理员的账号菜单有「管理」项')
  await e.done()
}
console.log('后台不向非管理员透出：未登录 / 普通用户 / 角色未确认 / 入口可见性 ✓')

// 入口与模型信息只认已确认的角色：缓存里写着 admin 也不算数（设计 §9.1、§9.4）
{
  const menuHas2 = async (x: Awaited<ReturnType<typeof boot>>) => {
    await act(async () => {
      x.q('[data-testid="account-menu"]')!.dispatchEvent(
        new win.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }) as unknown as Event)
    })
    await settle()
    const has = [...doc.body.querySelectorAll('[role="menuitem"]')].some((el) => (el.textContent ?? '').trim() === '管理')
    await act(async () => { doc.body.dispatchEvent(new win.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }) as unknown as Event) })
    await settle()
    return has
  }
  const sideHas = (x: Awaited<ReturnType<typeof boot>>) => !!button(x.container, '管理') || !!x.q('[aria-label="管理"]')
  // 缓存说是管理员、me() 还没回来：没有入口、没有请求 /admin/service
  adminSvcCalls = 0
  let release!: () => void
  meGate = new Promise<void>((r) => { release = r })
  const a = await boot('/', 'root', { id: 'root', username: 'root', created_at: '', role: 'admin' })
  must(!sideHas(a), '角色未确认：侧边栏没有「管理」入口')
  must(!(await menuHas2(a)), '角色未确认：账号菜单没有「管理」项')
  must(adminSvcCalls === 0, `角色未确认：不请求 /admin/service，实为 ${adminSvcCalls} 次`)
  release(); meGate = null
  await settle(300)
  must(sideHas(a) && (await menuHas2(a)), 'me() 确认是管理员后入口出现')
  must(adminSvcCalls === 1, `确认后请求一次 /admin/service，实为 ${adminSvcCalls} 次`)
  await a.done()
  // 缓存说是管理员，me() 确认是普通用户：入口始终没有，也不请求
  adminSvcCalls = 0
  meGate = new Promise<void>((r) => { release = r })
  const b = await boot('/', 'alice', { id: 'alice', username: 'alice', created_at: '', role: 'admin' })
  must(!sideHas(b) && !(await menuHas2(b)) && adminSvcCalls === 0, '缓存为管理员、角色未确认：没有入口与请求')
  release(); meGate = null
  await settle(300)
  must(!sideHas(b) && !(await menuHas2(b)), '确认为普通用户后始终没有入口')
  must(adminSvcCalls === 0, `确认为普通用户后不请求 /admin/service，实为 ${adminSvcCalls} 次`)
  await b.done()
}
console.log('入口与模型信息只认已确认的角色 ✓')

// §12.3-1（章节部分）深链接到章节的某一步
{
  const a = await boot('/novels/n1/chapters/c1/review', 'alice')
  must(a.here() === '/novels/n1/chapters/c1/review', `应停在原地址，实际 ${a.here()}`)
  must(!!a.q('[data-step="review"][aria-current="step"]'), '直接显示 ③')
  await a.done()
}
console.log('1a. 章节步骤深链接 ✓')

// §12.3-4（章节部分）不存在的章节：回这本小说的章节列表
{
  const a = await boot('/novels/n1/chapters/nope', 'alice')
  must(a.here() === '/novels/n1/chapters', `不存在的章节应回章节列表，实际 ${a.here()}`)
  await a.done()
}
console.log('4b. 不存在的章节 → 回章节列表 ✓')

// state.vid 是一次性参数：消费后 replace 清掉（§5.4）
{
  const a = await boot('/novels/n1/overview', 'alice')
  await act(async () => { await a.router.navigate('/novels/n1/chapters/c1', { state: { vid: 'v1' } }) })
  await settle(200)
  const st = a.router.state.location.state as { vid?: string } | null
  must(!st?.vid && a.router.state.historyAction === 'REPLACE', 'vid 消费后应被 replace 清掉')
  await a.done()
}
console.log('state 一次性参数消费 ✓')

// 点步骤条：push /:step；后退回到无步骤段
{
  const a = await boot('/novels/n1/chapters/c1', 'alice')
  await click(a.q('[data-step="review"]')!)
  must(a.here() === '/novels/n1/chapters/c1/review' && a.router.state.historyAction === 'PUSH', '步骤条是 push')
  await act(async () => { await a.router.navigate(-1) })
  await settle()
  must(a.here() === '/novels/n1/chapters/c1', '后退回到章节地址')
  await a.done()
}
console.log('步骤条 push / 后退 ✓')

// 切章时不渲染上一章的分镜（§5.2）：换到另一章的第一帧起就只有骨架
{
  const a = await boot('/novels/n1/chapters/c1/review', 'alice')
  novel.chapters.push({ id: 'c2', title: '第二章', order: 2, text: '他出门。', adopted_version: null, digest: null, versions: [] })
  must(a.has('E01-SH001'), '前提：c1 的分镜已摆出')
  let stale = false
  const obs = new win.MutationObserver(() => {
    if (a.here().includes('/chapters/c2') && a.has('E01-SH001')) stale = true
  })
  obs.observe(a.container as unknown as Node, { childList: true, subtree: true, characterData: true })
  await act(async () => { await a.router.navigate('/novels/n1/chapters/c2') })
  await settle(200)
  obs.disconnect()
  must(!stale, '切章途中不应渲染上一章的分镜')
  must(a.here() === '/novels/n1/chapters/c2' && !a.has('E01-SH001'), '到了 c2 不应残留 c1 的分镜')
  await a.done()
}
console.log('切章不闪上一章内容 ✓')

// §12.3-1 深链接到渲染步骤上的画布，节点图视图
{
  const a = await boot('/novels/n1/chapters/c1/render/canvas?view=graph', 'alice')
  must(a.here() === '/novels/n1/chapters/c1/render/canvas?view=graph', `应停在原地址，实际 ${a.here()}`)
  must(!!a.q('.tlc'), '画布打开')
  must(!!a.q('[data-testid="node-graph"]'), '节点图视图')
  await a.done()
}
console.log('1b. 画布加节点图深链接 ✓')

// §12.3-8 画布内切节点图：replace，fromChapter 仍在
{
  const a = await boot('/novels/n1/chapters/c1/review', 'alice')
  const open = button(a.container, '时间轴画布') ?? a.q('[title*="画布"]')
  await click(open!)
  must(a.here() === '/novels/n1/chapters/c1/review/canvas' && a.router.state.historyAction === 'PUSH', '打开画布是 push')
  const graphBtn = [...a.container.querySelectorAll('.tlc__bar button')].find((b) => b.textContent === '节点图') as unknown as HTMLElement
  await click(graphBtn)
  must(a.here() === '/novels/n1/chapters/c1/review/canvas?view=graph', `切到节点图，实际 ${a.here()}`)
  must(a.router.state.historyAction === 'REPLACE', '切视图是 replace')
  must((a.router.state.location.state as { fromChapter?: boolean } | null)?.fromChapter === true, 'fromChapter 透传')
  // §12.3-9 关闭画布：回到原步骤
  await click(a.q('.tlc__close')!)
  await settle(200)
  must(a.here() === '/novels/n1/chapters/c1/review', `关闭画布回原步骤，实际 ${a.here()}`)
  await a.done()
}
console.log('8/9a. 画布视图 replace、关闭回原步骤 ✓')

// §12.3-9 jumpShot：一次 replace 到 /:step（页签 focus）
{
  const a = await boot('/novels/n1/chapters/c1/render/canvas?tab=cards', 'alice')
  const shot = a.q('.tlc__shot')!
  await act(async () => { shot.dispatchEvent(new win.MouseEvent('dblclick', { bubbles: true }) as unknown as Event) })
  await settle(200)
  must(a.here() === '/novels/n1/chapters/c1/render', `双击镜头跳回聚焦页签，实际 ${a.here()}`)
  must(a.router.state.historyAction === 'REPLACE', 'jumpShot 是一次 replace')
  await a.done()
}
console.log('9b. jumpShot ✓')

// §12.3-3 不能开画布时规范化：章节没有版本
{
  const a = await boot('/novels/n1/overview', 'alice')
  novel.chapters[0].versions = []; novel.chapters[0].adopted_version = null
  await act(async () => { await a.router.navigate('/novels/n1/chapters/c1/review/canvas') })
  await settle(200)
  must(a.here() === '/novels/n1/chapters/c1', `没有版本时画布地址应规范化，实际 ${a.here()}`)
  await a.done()
}
console.log('3. 不能开画布 → 规范化 ✓')

// 深链接首帧：章节与版本都慢到（异步），画布地址不能被规范化掉
{
  lag = 60
  const a = await boot('/novels/n1/chapters/c1/render/canvas?view=graph', 'alice')
  await settle(400)
  lag = 0
  must(a.here() === '/novels/n1/chapters/c1/render/canvas?view=graph', `慢加载期间画布地址不应被改，实际 ${a.here()}`)
  must(!!a.q('.tlc'), '加载完画布打开')
  await a.done()
}
console.log('1c. 深链接首帧不误规范化 ✓')

// 受控 recompose 在 workflow-ui.test 里覆盖；这里覆盖 openFilm 一次 push 到画布地址
{
  const a = await boot('/novels/n1/chapters/c1/compose', 'alice')
  const before = a.router.state.historyAction
  void before
  const open = button(a.container, '时间轴画布') ?? a.q('[title*="画布"]')
  await click(open!)
  must(a.here() === '/novels/n1/chapters/c1/compose/canvas' && a.router.state.historyAction === 'PUSH', '⑤ 上开画布是一次 push')
  await act(async () => { await a.router.navigate(-1) })
  await settle()
  must(a.here() === '/novels/n1/chapters/c1/compose', `后退一步直接回 ⑤，没有中间项，实际 ${a.here()}`)
  await a.done()
}
console.log('开画布一次 push、后退一步 ✓')

// 换章时旧章的读版本还没回来；新章没有版本：深链接的画布地址仍要规范化
{
  const a = await boot('/novels/n1/overview', 'alice')
  novel.chapters.push({ id: 'c2', title: '第二章', order: 2, text: '他出门。', adopted_version: null, digest: null, versions: [] })
  let release!: () => void
  gate = new Promise<void>((r) => { release = r })
  await act(async () => { await a.router.navigate('/novels/n1/chapters/c1/review') })
  await settle(150)
  await act(async () => { await a.router.navigate('/novels/n1/chapters/c2/review/canvas') })
  await settle(200)
  release(); gate = null
  await settle(300)
  must(a.here() === '/novels/n1/chapters/c2', `旧章读版本迟到后，新章画布地址仍应规范化，实际 ${a.here()}`)
  await a.done()
}
console.log('换章时迟到的读版本不卡住规范化 ✓')

// §12.3-7 有未保存修改时离开当前章节：确认；取消留在原地，确认后离开；force 的退出不确认
{
  const a = await boot('/novels/n1/overview', 'alice')
  novel.chapters.push({ id: 'c2', title: '第二章', order: 2, text: '他出门。', adopted_version: null, digest: null, versions: [] })
  await act(async () => { await a.router.navigate('/novels/n1/chapters/c2/import') })
  await settle(200)
  const ta = a.q('textarea')!
  const set = Object.getOwnPropertyDescriptor(win.HTMLTextAreaElement.prototype, 'value')!.set!
  await act(async () => { set.call(ta, '他推门。改'); ta.dispatchEvent(new win.Event('input', { bubbles: true }) as unknown as Event) })
  await settle()
  await act(async () => { void a.router.navigate('/novels/n1/overview') })
  await settle()
  const dlg = () => doc.body.querySelector('[data-testid="confirm-dialog"]')
  must((dlg()?.textContent ?? '').includes('有未保存的修改'), '离开前应确认')
  await click(doc.body.querySelector<HTMLElement>('[data-testid="confirm-cancel"]')!); await settle(300)
  must(a.here() === '/novels/n1/chapters/c2/import', '取消后地址不变')
  await act(async () => { void a.router.navigate('/novels/n1/overview') }); await settle()
  await click(doc.body.querySelector<HTMLElement>('[data-testid="confirm-ok"]')!); await settle(300)
  must(a.here() === '/novels/n1/overview', '确认后离开')
  await a.done()
}
{
  const a = await boot('/novels/n1/overview', 'alice')
  novel.chapters.push({ id: 'c2', title: '第二章', order: 2, text: '他出门。', adopted_version: null, digest: null, versions: [] })
  await act(async () => { await a.router.navigate('/novels/n1/chapters/c2/import') })
  await settle(200)
  const ta = a.q('textarea')!
  const set = Object.getOwnPropertyDescriptor(win.HTMLTextAreaElement.prototype, 'value')!.set!
  await act(async () => { set.call(ta, '又改'); ta.dispatchEvent(new win.Event('input', { bubbles: true }) as unknown as Event) })
  await settle()
  // 同一章内换步骤不拦（§7）
  await act(async () => { void a.router.navigate('/novels/n1/chapters/c2/review') }); await settle()
  must(a.here() === '/novels/n1/chapters/c2/review' && !doc.body.querySelector('[data-testid="confirm-dialog"]'), '同章换步骤不拦')
  // 带 force 的程序性跳转放行
  await act(async () => { void a.router.navigate('/', { state: { force: true } }) }); await settle()
  must(a.here() === '/', 'force 放行')
  await a.done()
}
console.log('7. 离开拦截 ✓')

// §12.3-11 页面标题随位置变化
{
  const a = await boot('/novels/n1/props', 'alice')
  must(doc.title === '道具 · 药 — Inkreel', `分区标题，实际 ${doc.title}`)
  await act(async () => { void a.router.navigate('/novels/n1/chapters/c1/review/canvas') }); await settle(200)
  must(doc.title === '出片画布 · 第一章 — Inkreel', `画布标题，实际 ${doc.title}`)
  await act(async () => { void a.router.navigate('/nope') }); await settle()
  must(doc.title === '页面不存在 — Inkreel', `404 标题，实际 ${doc.title}`)
  await a.done()
}
console.log('11. 页面标题 ✓')

// ===== 终审修复回归 =====

// C1：同一章里快速换版本，慢的那次迟到回来不能覆盖新的
{
  const a = await boot('/novels/n1/chapters/c1/review', 'alice')
  const mk = (id: string, action: string) => {
    const d = JSON.parse(JSON.stringify(DOC)); d.episodes[0].shots[0].action = action
    return { id, created_at: '', edited_at: null, status: 'succeeded', result: d, verification: VERIFIED, error: null }
  }
  novel.chapters[0].versions.push(mk('v2', '动作甲'), mk('v3', '动作乙'))
  await act(async () => { await a.router.navigate('/novels/n1/chapters/c1/render'); await a.router.navigate('/novels/n1/chapters/c1/review') })
  await settle(200)
  // 重新取一遍章节，让版本条出现 v2 v3
  await click(a.q('[data-testid="chapter-card"]') ?? a.q('[data-step="review"]')!)
  await settle(200)
  let release!: () => void
  vgate.v2 = new Promise<void>((r) => { release = r })
  const chip = (t: string) => [...a.container.querySelectorAll('.vchip')].find((b) => (b.textContent ?? '').startsWith(t)) as unknown as HTMLElement | undefined
  must(!!chip('v2') && !!chip('v3'), '前提：版本条有 v2 v3')
  await click(chip('v2')!)
  await click(chip('v3')!)
  await settle(100)
  must(a.has('动作乙'), '前提：v3 已摆出')
  release(); delete vgate.v2
  await settle(200)
  must(a.has('动作乙') && !a.has('动作甲'), 'v2 迟到的响应不能覆盖 v3')
  await a.done()
}
console.log('C1. 快速换版本，迟到响应被丢弃 ✓')

// C2：附着着任务时换章，旧任务迟到的轮询结果不写进新章
{
  const a = await boot('/novels/n1/overview', 'alice')
  novel.chapters.push({ id: 'c2', title: '第二章', order: 2, text: '他出门。', adopted_version: null, digest: null, versions: [] })
  jobsList = [{ id: 'j1', status: 'running', novel_id: 'n1', chapter_id: 'c1', work_title: '药', chapter: '第一章' }]
  let release!: () => void
  jobGate = new Promise<void>((r) => { release = r })
  jobsById.j1 = { id: 'j1', status: 'succeeded', log: [], result: JSON.parse(JSON.stringify(DOC)),
                  quality_report: null, error: null, work_title: '药', chapter: '第一章' }
  await act(async () => { await a.router.navigate('/novels/n1/chapters/c1', { state: { jobId: 'j1' } }) })
  await settle(250)
  must(!a.has('1 镜约'), '前提：任务还没回来，c1 没有产物')
  await act(async () => { await a.router.navigate('/novels/n1/chapters/c2') })
  await settle(250)
  release(); jobGate = null
  await settle(300)
  must(a.here() === '/novels/n1/chapters/c2', '前提：停在 c2')
  must(!a.has('关闭任务面板') && !a.has('1 镜约'), '旧任务迟到的结果不能写进 c2（任务面板与产物都不该出现）')
  await a.done()
}
console.log('C2. 换章后旧任务迟到的轮询被丢弃 ✓')

// I2：缓存的用户没有角色字段：me() 确认之前不能被赶出 /admin
{
  let release!: () => void
  meGate = new Promise<void>((r) => { release = r })
  const a = await boot('/admin', 'root', { id: 'root', username: 'root', created_at: '' })
  must(a.here() === '/admin', `me() 回来前不应离开 /admin，实际 ${a.here()}`)
  release(); meGate = null
  await settle(300)
  must(a.here() === '/admin' && a.has('运营后台'), 'me() 确认是管理员后留在后台')
  await a.done()
}
console.log('I2. /admin 等角色确认 ✓')

// I3：force 只管那一次跳转；后退回到带 force 的旧条目，有未保存修改仍要拦
{
  const a = await boot('/novels/n1/overview', 'alice')
  novel.chapters.push({ id: 'c2', title: '第二章', order: 2, text: '他出门。', adopted_version: null, digest: null, versions: [] })
  await act(async () => { await a.router.navigate('/novels/n1/props', { state: { force: true } }) })
  await settle()
  await act(async () => { await a.router.navigate('/novels/n1/chapters/c2/import') })
  await settle(200)
  const ta = a.q('textarea')!
  const set = Object.getOwnPropertyDescriptor(win.HTMLTextAreaElement.prototype, 'value')!.set!
  await act(async () => { set.call(ta, '后退测试'); ta.dispatchEvent(new win.Event('input', { bubbles: true }) as unknown as Event) })
  await settle()
  await act(async () => { void a.router.navigate(-1) })
  await settle(200)
  must(!!doc.body.querySelector('[data-testid="confirm-dialog"]'), '后退进带 force 的旧条目仍应确认')
  must(a.here() === '/novels/n1/chapters/c2/import', `确认前留在原地，实际 ${a.here()}`)
  await click(doc.body.querySelector<HTMLElement>('[data-testid="confirm-cancel"]')!); await settle(300)
  await a.done()
}
console.log('I3. force 不污染历史条目 ✓')

const openLogin = async (box: HTMLElement) => {
  const b = [...box.querySelectorAll('button')].find((x) => (x.textContent ?? '').trim() === '登录') as unknown as HTMLElement | undefined
  if (b) await click(b)
}
// I2 补：退出再以同一账号登录，旧会话的角色确认不带过来；/admin 等新的 me() 回来再判定
{
  const a = await boot('/novels/n1/overview', 'alice')
  await click(a.container.querySelector('[aria-label="退出"]') as unknown as HTMLElement)
  await settle(200)
  let release!: () => void
  meGate = new Promise<void>((r) => { release = r })
  await act(async () => { await a.router.navigate('/') }); await settle()
  await openLogin(a.container)
  await loginAs('alice', 'pw')
  await settle(600)
  await act(async () => { await a.router.navigate('/admin') }); await settle(100)
  must(a.here() === '/admin', `新会话 me() 回来前不应重定向，实际 ${a.here()}`)
  release(); meGate = null
  await settle(300)
  must(a.here() === '/', `确认非管理员后才离开，实际 ${a.here()}`)
  await a.done()
}
console.log('I2b. 重登后角色确认重新等待 ✓')

// I4 补：加载章节途中退出再以同一账号登录，旧会话的响应不写进新会话
{
  lag = 300
  const a = await boot('/novels/n1/chapters/c1', 'alice')
  await click(a.container.querySelector('[aria-label="退出"]') as unknown as HTMLElement)
  await settle(100)
  await openLogin(a.container)
  await loginAs('alice', 'pw')
  await settle(900)
  lag = 0
  must(a.here() === '/' && !a.has('生成分镜'), `旧会话的章节不应出现在新会话，实际 ${a.here()}`)
  await a.done()
}
console.log('I4b. 重登后旧会话的加载响应被丢弃 ✓')

if (unhandled.size) console.log('（桩后端未处理：' + [...unhandled].join('，') + '）')
// §12.3-3 非法 section / step / tab / view：规范化到上级（replace）
for (const [from, to] of [
  ['/novels/n1/bogus', '/novels/n1/overview'],
  ['/novels/n1/chapters/c1/zzz', '/novels/n1/chapters/c1'],
  ['/novels/n1/chapters/c1/review?tab=zzz', '/novels/n1/chapters/c1/review'],
  ['/novels/n1/chapters/c1/review/canvas?view=zzz', '/novels/n1/chapters/c1/review/canvas'],
] as const) {
  const a = await boot(from, 'alice')
  must(a.here() === to, `${from} 应规范化到 ${to}，实际 ${a.here()}`)
  must(a.router.state.historyAction === 'REPLACE', `${from} 规范化是 replace`)
  await a.done()
}
console.log('3b. 非法值规范化 ✓')

// §12.3-10 同址再打开：在章节里点左栏同一章，不 push 新地址、仍在这一章
// （重置后工作流按章节进度重新跟步，这一步是 replace，所以步骤段可以变，历史条数不增）
{
  const a = await boot('/novels/n1/chapters/c1/review', 'alice')
  await click(a.q('[data-testid="chapter-card"]')!)
  must(a.router.state.historyAction !== 'PUSH', `同址再打开不 push，实际 ${a.router.state.historyAction}`)
  must(a.here().startsWith('/novels/n1/chapters/c1'), `同址再打开仍在这一章，实际 ${a.here()}`)
  await a.done()
}
console.log('10. 同址再打开不导航 ✓')

// 页面提示条存「文案键 + 错误值」：切换语言后整句（含前缀）跟着变；结构化 detail 不显示成 [object Object]
{
  chapterFail = { status: 500, detail: { code: 'chapter.not_found', params: {}, message: '章节不存在' } }
  const a = await boot('/novels/n1/chapters/c1', 'alice')
  const alertText = () => a.q('p.alert')?.textContent ?? ''
  must(alertText() === '打开章节失败：章节不存在', `中文提示条：${alertText()}`)
  await act(async () => { setLoc('en') })
  await settle()
  must(alertText() === 'Could not open the chapter: Chapter not found', `切英文后整句跟着变：${alertText()}`)
  must(!a.has('[object Object]'), '结构化 detail 不能显示成 [object Object]')
  await act(async () => { setLoc('zh') })
  chapterFail = null
  await a.done()
  setCurrentLocale('zh')
}
console.log('I5. 章节读取失败的提示条按语言渲染并随切换更新 ✓')
// 已在章节里再次点开它、读取返回结构化 404：走 openChapter 的错误提示条（深链接首次加载的 404 是另一条「章节已不存在」跳转分支）
{
  const a = await boot('/novels/n1/chapters/c1', 'alice')
  must(!a.q('p.alert'), '先正常打开章节')
  chapterFail = { status: 404, detail: { code: 'chapter.not_found', params: {}, message: '章节不存在' } }
  await click(a.q('[data-testid="chapter-card"]')!)
  await settle(200)
  const alertText = () => a.q('p.alert')?.textContent ?? ''
  must(alertText() === '打开章节失败：章节不存在', `中文提示条：${alertText()}`)
  await act(async () => { setLoc('en') })
  await settle()
  must(alertText() === 'Could not open the chapter: Chapter not found', `切英文后整句跟着变：${alertText()}`)
  must(!a.has('[object Object]'), '结构化 detail 不能显示成 [object Object]')
  await act(async () => { setLoc('zh') })
  chapterFail = null
  await a.done()
  setCurrentLocale('zh')
}
console.log('I5b. 已打开章节再读取返回结构化 404 → 提示条按语言渲染 ✓')

// 提交转换失败：app.err.submit 整句随语言变
{
  submitFail = true
  const a = await boot('/novels/n1/chapters/c1', 'alice')
  await click(a.q('[data-step="storyboard"]')!)
  await click(a.q('[data-testid="primary-action"]')!)
  await settle(200)
  const alertText = () => a.q('p.alert')?.textContent ?? ''
  must(alertText() === '提交失败：本章还没有原文', `中文提交错误：${alertText()}`)
  await act(async () => { setLoc('en') })
  await settle()
  must(alertText() === 'Submit failed: This chapter has no source text yet', `切英文后提交错误跟着变：${alertText()}`)
  must(!a.has('[object Object]'), '结构化 detail 不能显示成 [object Object]')
  await act(async () => { setLoc('zh') })
  submitFail = false
  await a.done()
  setCurrentLocale('zh')
}
console.log('I6. 提交转换失败的提示按语言渲染并随切换更新 ✓')

// 账号菜单的模型信息只给管理员（数据来自 /admin/service）；普通用户没有这一行、也不请求
{
  const openMenu = async (a: Awaited<ReturnType<typeof boot>>) => {
    await act(async () => {
      a.q('[data-testid="account-menu"]')!.dispatchEvent(
        new win.PointerEvent('pointerdown', { bubbles: true, button: 0, ctrlKey: false }) as unknown as Event)
    })
    await settle()
  }
  adminSvcCalls = 0
  const u = await boot('/', 'alice')
  await openMenu(u)
  must(!doc.body.textContent!.includes('当前模型') && !doc.body.textContent!.includes('stub-model'), '普通用户的账号菜单没有模型')
  must(adminSvcCalls === 0, '普通用户不请求 /admin/service')
  await u.done()
  const ad = await boot('/', 'root', { id: 'root', username: 'root', created_at: '', role: 'admin' })
  await settle(150)
  await openMenu(ad)
  must(doc.body.textContent!.includes('stub-model') && doc.body.textContent!.includes('未配置密钥'), '管理员能看到模型与未配置密钥')
  await act(async () => { setLoc('en') })
  await settle()
  must(doc.body.textContent!.includes('stub-model') && doc.body.textContent!.includes('API key not set'), '切英文后仍是管理员视图且文字变英文')
  await act(async () => { setLoc('zh') })
  await ad.done()
  setCurrentLocale('zh')
}
// 同一个应用实例换账号：旧管理员会话迟到的 /admin/service 响应不能落到新的普通用户身上
{
  let release!: () => void
  svcGate = new Promise<void>((r) => { release = r })
  const a = await boot('/', 'root', { id: 'root', username: 'root', created_at: '', role: 'admin' })
  await click(a.container.querySelector('[aria-label="退出"]') as unknown as HTMLElement)
  await settle(200)
  await openLogin(a.container)
  await loginAs('alice', 'pw')
  await settle(400)
  release(); svcGate = null
  await settle(300)
  await act(async () => {
    a.q('[data-testid="account-menu"]')!.dispatchEvent(
      new win.PointerEvent('pointerdown', { bubbles: true, button: 0, ctrlKey: false }) as unknown as Event)
  })
  await settle()
  must(doc.body.textContent!.includes('正常') && !doc.body.textContent!.includes('当前模型') && !doc.body.textContent!.includes('stub-model'),
       '旧管理员会话迟到的服务信息不显示在新的普通用户菜单里')
  await a.done()
}
console.log('T9b. 换账号后旧响应被丢弃 ✓')

// 旧会话迟到的 401 只拒绝，不能清掉新会话（退出再登录、会话过期再登录；新账号是普通用户 / 同一管理员 / 另一管理员）
{
  const { getToken, notifyUnauthorized } = await import('../src/auth')
  users.root2 = { role: 'admin' }
  const cases: { how: 'logout' | 'expire'; next: string }[] = [
    { how: 'logout', next: 'alice' }, { how: 'logout', next: 'root' }, { how: 'logout', next: 'root2' },
    { how: 'expire', next: 'alice' }, { how: 'expire', next: 'root' }, { how: 'expire', next: 'root2' },
  ]
  for (const c of cases) {
    let release!: () => void
    svcGate = new Promise<void>((r) => { release = r })
    svcUnauth = true
    const a = await boot('/', 'root', { id: 'root', username: 'root', created_at: '', role: 'admin' })
    if (c.how === 'logout') await click(a.container.querySelector('[aria-label="退出"]') as unknown as HTMLElement)
    else await act(async () => { notifyUnauthorized() })
    await settle(200)
    await openLogin(a.container)
    await loginAs(c.next, 'pw')
    await settle(400)
    release(); svcGate = null
    await settle(300)
    const tag = `${c.how} → ${c.next}`
    must(getToken() === `tok-${c.next}`, `${tag}：旧会话迟到的 401 不能清掉新令牌`)
    must(!!a.q('[data-testid="account-menu"]') && !doc.body.querySelector('.login__field input'), `${tag}：新会话仍在应用里，没被踢回登录页`)
    await a.done()
  }
  delete users.root2
}
console.log('T9d. 旧会话迟到的 401 不影响新会话 ✓')

// 当前会话（没换过账号）的 401 经请求层（api.ts send）：清令牌、回登录页并提示登录已过期
{
  const { getToken } = await import('../src/auth')
  svcUnauth = true
  const a = await boot('/', 'root', { id: 'root', username: 'root', created_at: '', role: 'admin' })
  await settle(400)
  must(getToken() === null, '当前会话的 401 经请求层应清掉令牌')
  must(!a.q('[data-testid="account-menu"]'), '当前会话的 401 后不再显示账号菜单')
  must(doc.body.textContent!.includes('登录已过期'), '当前会话的 401 后登录框带过期提示')
  await a.done()
}
console.log('T9e. 当前会话的 401 经请求层清令牌并提示过期 ✓')

// 出片任务：在跑的计入铃铛并列在动态面板；点「查看」到那一版的画布（节点图）并带上要选中的片段；
// 结束时发一条能点的桌面通知，点它带着「播放」回到那一段
{
  const { pokeFilmTasks } = await import('../src/filmTasks')
  const made: { title: string; body: string; tag: string; onclick: (() => void) | null }[] = []
  class Granted {
    static permission = 'granted'
    static requestPermission = async () => 'granted'
    onclick: (() => void) | null = null
    title: string
    body: string
    tag: string
    constructor(title: string, o: { body: string; tag: string }) {
      this.title = title; this.body = o.body; this.tag = o.tag
      made.push(this)
    }
    close() {}
  }
  const wn = win as unknown as Record<string, unknown>
  const before = [g.Notification, wn.Notification, wn.focus]
  g.Notification = Granted; wn.Notification = Granted; wn.focus = () => {}
  const task = (over: Record<string, unknown> = {}) => ({
    id: 'v1:E01-C01', item_id: 'E01-C01', kind: 'clip', novel_id: 'n1', chapter_id: 'c1', version_id: 'v1',
    work_title: '药', chapter: '第一章', state: 'running', elapsed_sec: 245, typical_sec: [180, 420],
    ended_at: null, cost_cny: null, ...over })
  const poke = async () => { await act(async () => { pokeFilmTasks() }); await settle(150) }
  const focusOf = (r: Router) => (r.state.location.state as { focus?: unknown; panel?: string } | null)

  const a = await boot('/novels/n1/overview', 'alice')
  must(!a.q('[data-testid="activity-count"]'), '没有任务：铃铛上没有数字')
  filmTasks = [task({ cancel: 'paid', shot_ids: ['E01-SH001', 'E01-SH002'] })]
  await poke()
  must(a.q('[data-testid="activity-count"]')?.textContent === '1', '在跑的出片任务计入铃铛')
  await click(a.q('[data-testid="activity-bell"]')!)
  const row = doc.body.querySelector('[data-testid="activity-film-running"]') as unknown as HTMLElement | null
  must(!!row && (row.textContent ?? '').includes('药 › 第一章 › E01-C01 · SH001–SH002') && /已等 4 分 \d\d 秒 · 通常 3–7 分钟/.test(row.textContent ?? ''),
       `任务面板里有这条，定位到小说、章节、片段与镜号：${row?.textContent}`)
  must(made.length === 0, '在跑的不发通知')
  // 面板里直接取消：先过确认框（写明可能仍扣费），确认才发请求，然后按结局提示
  const confirmBtn = (ok: boolean) => doc.body.querySelector(`[data-testid="${ok ? 'confirm-ok' : 'confirm-cancel'}"]`) as unknown as HTMLElement
  await click(row!.querySelector('[data-testid="activity-film-cancel"]') as unknown as HTMLElement)
  must((doc.body.querySelector('[data-testid="confirm-dialog"]')?.textContent ?? '').includes('服务商可能仍会生成并扣费')
       && cancelCalls.length === 0, '面板里取消：先确认')
  await click(confirmBtn(false))
  must(cancelCalls.length === 0, '确认框里点取消：不发请求')
  await click(row!.querySelector('[data-testid="activity-film-cancel"]') as unknown as HTMLElement)
  await click(confirmBtn(true))
  must(cancelCalls.join() === '/novels/n1/chapters/c1/versions/v1/render/clips/E01-C01/cancel', `确认后发取消请求：${cancelCalls}`)
  await click(button(row!, '查看')!)
  await settle(300)
  must(a.here() === '/novels/n1/chapters/c1/render/canvas?view=graph', `点查看到画布的节点图，实际 ${a.here()}`)
  must(JSON.stringify(focusOf(a.router)?.focus) === JSON.stringify({ vid: 'v1', id: 'E01-C01', play: false })
       && focusOf(a.router)?.panel === 'film', `带上要选中的片段：${JSON.stringify(a.router.state.location.state)}`)

  filmTasks = [task({ state: 'done', ended_at: '2026-11-21T03:00:00+00:00', elapsed_sec: 280 })]
  await poke()
  must(!a.q('[data-testid="activity-count"]'), '结束后铃铛数字消失')
  must(made.length === 1 && made[0].title === '片段已生成' && made[0].body.includes('药 · 第一章 · E01-C01')
       && made[0].tag === 'film-v1:E01-C01', `结束发一条通知：${JSON.stringify(made)}`)
  must(!/minimax|seedance|fake/i.test(made[0].title + made[0].body), '通知里不出现厂商名')
  await poke()
  must(made.length === 1, '同一条不重复通知')
  await act(async () => { made[0].onclick!() })
  await settle(300)
  must(a.here() === '/novels/n1/chapters/c1/render/canvas?view=graph', '点通知：还在这一章的画布')
  must(JSON.stringify(focusOf(a.router)?.focus) === JSON.stringify({ vid: 'v1', id: 'E01-C01', play: true }),
       `点通知带着播放：${JSON.stringify(a.router.state.location.state)}`)
  await a.done()

  // 登录后第一轮看到的已结束任务不播报（刷新页面不重弹）；取消后才出结果的要播报，带任务号
  filmTasks = []
  const b = await boot('/novels/n1/overview', 'alice')
  must(made.length === 1, '第一轮不播报')
  filmTasks = [task({ id: 'v1:E01-C02:t9', item_id: 'E01-C02', state: 'late', elapsed_sec: null,
                      ended_at: '2026-11-21T03:09:00+00:00', cost_cny: 7.5 })]
  await poke()
  must(made.length === 2 && made[1].title === '已取消的片段仍生成完成' && made[1].body.includes('¥7.50'),
       `取消后才出结果：${JSON.stringify(made[1])}`)
  await act(async () => { made[1].onclick!() })
  await settle(300)
  must(JSON.stringify(focusOf(b.router)?.focus) === JSON.stringify({ vid: 'v1', id: 'E01-C02', play: true, taskId: 't9' }),
       `点通知带着任务号：${JSON.stringify(b.router.state.location.state)}`)
  // 巡检响应乱序：先发的 A（仍在跑）后返回，后发的 B（已取消）先返回——铃铛与列表不回退
  {
    let release!: () => void
    tasksHold.push(new Promise<void>((r) => { release = r }))
    const running = task({ id: 'v1:E01-C09', item_id: 'E01-C09', cancel: 'paid' })
    filmTasks = [running]
    await poke()                      // A：快照是在跑，卡住
    filmTasks = [{ ...running, state: 'cancelled', ended_at: '2026-11-21T03:10:00+00:00', cancel: null }]
    flight.tasksMax = 0
    await poke()                      // B：已取消；A 还在途，B 只记待补刷、不同时发出
    must(flight.tasksMax <= 1 && !b.q('[data-testid="activity-count"]'), `A 在途时 B 不叠发：${flight.tasksMax}`)
    await act(async () => { release() })
    await settle(150)
    must(!b.q('[data-testid="activity-count"]'), '过期的 A 后返回：铃铛不回退')
    if (!doc.body.querySelector('[data-testid="activity-panel"]')) await click(b.q('[data-testid="activity-bell"]')!)
    must(!doc.body.querySelector('[data-testid="activity-film-running"]'), '过期的 A 后返回：列表里不再有在跑的')
    await click(b.q('[data-testid="activity-bell"]')!)      // 收起
  }
  // 成片合成也播报；点开到这一章的画布（出片页），不带要选中的片段
  filmTasks = [task({ id: 'v1:compose', item_id: 'compose', kind: 'compose', state: 'done', typical_sec: null,
                      elapsed_sec: 40, ended_at: '2026-11-21T03:12:00+00:00' })]
  await poke()
  must(made.length === 3 && made[2].title === '成片已合成' && made[2].body.includes('药 · 第一章 · 成片合成'),
       `合成完成的通知：${JSON.stringify(made[2])}`)
  await act(async () => { made[2].onclick!() })
  await settle(300)
  must(b.here() === '/novels/n1/chapters/c1/render/canvas' && !focusOf(b.router)?.focus && focusOf(b.router)?.panel === 'film',
       `点合成的通知：到画布的出片页，实际 ${b.here()} ${JSON.stringify(b.router.state.location.state)}`)
  await b.done()
  ;[g.Notification, wn.Notification, wn.focus] = before
}
console.log('出片任务：铃铛、面板、跳转与通知 ✓')

{
  const { pokeFilmTasks } = await import('../src/filmTasks')
  // 巡检在慢网络下仍有进展：每次响应都比轮询间隔慢，同一路也只有一个请求在途（间隔缩小 20 倍跑）
  const wsi = win as unknown as { setInterval: (fn: () => void, ms?: number, ...r: unknown[]) => number }
  const origSI = wsi.setInterval.bind(win)
  wsi.setInterval = (fn, ms, ...r) => origSI(fn, Math.max(20, (ms ?? 0) / 20), ...r)
  const task = (over: Record<string, unknown> = {}) => ({
    id: 'v1:E01-C01', item_id: 'E01-C01', kind: 'clip', novel_id: 'n1', chapter_id: 'c1', version_id: 'v1',
    work_title: '药', chapter: '第一章', state: 'running', elapsed_sec: 245, typical_sec: [180, 420],
    ended_at: null, cost_cny: null, ...over })
  const countOf = (r: { q: (s: string) => Element | null }) => r.q('[data-testid="activity-count"]')?.textContent ?? null
  {
    const c = await boot('/novels/n1/overview', 'alice')
    tasksDelay = 700; flight.tasksMax = 0
    filmTasks = [task()]
    await settle(2600)
    must(countOf(c) === '1', `出片巡检：响应比间隔慢也要更新（在跑 1），实际 ${countOf(c)}`)
    filmTasks = [task({ state: 'cancelled', ended_at: '2026-11-21T03:10:00+00:00' })]
    await settle(2600)
    must(countOf(c) === null, `出片巡检：慢响应下结束的任务也会显示，实际 ${countOf(c)}`)
    must(flight.tasksMax === 1, `出片巡检：同一时刻最多一个请求在途，实际 ${flight.tasksMax}`)
    // 操作触发（poke）连发：只合并成一次补刷，仍然最多一个在途，状态最终更新
    tasksDelay = 400; flight.tasksMax = 0; flight.tasksCalls = 0
    filmTasks = [task({ id: 'v1:E01-C05', item_id: 'E01-C05' })]
    for (let i = 0; i < 8; i++) { await act(async () => { pokeFilmTasks() }); await settle(40) }
    await settle(1800)
    must(countOf(c) === '1' && flight.tasksMax === 1, `连发触发：最终更新且不叠发，${countOf(c)} ${flight.tasksMax}`)
    tasksDelay = 0
    await c.done()
  }
  {
    const c = await boot('/novels/n1/overview', 'alice')
    jobsDelay = 700; flight.jobsMax = 0
    jobsList = [{ id: 'j9', status: 'running', novel_id: 'n1', chapter_id: 'c1', work_title: '药', chapter: '第一章' }]
    await settle(2600)
    must(countOf(c) === '1', `转换巡检：响应比间隔慢也要更新（在跑 1），实际 ${countOf(c)}`)
    jobsList = []
    await settle(2600)
    must(countOf(c) === null, `转换巡检：慢响应下结束也会更新，实际 ${countOf(c)}`)
    must(flight.jobsMax === 1, `转换巡检：同一时刻最多一个请求在途，实际 ${flight.jobsMax}`)
    jobsDelay = 0
    await c.done()
  }
  wsi.setInterval = origSI
}

{
  const { pokeFilmTasks } = await import('../src/filmTasks')
  // 合成任务点开：画布已打开、侧栏停在别的页签、路由 state 已是 panel:'film' 时，再点一次仍切到「出片」并显示合成区
  const session = { provider: 'fake', model: 'fake-1', resolution: '720p', audio_mode: 'tts_all', budget_cny: 100000,
    confirm_over_cny: 20, spent_cny: 0, clips: [], free: [], free_seq: 0, orphaned: [], counts: {}, remaining_cny: 0,
    reserved_cny: 0, uncertain_count: 0,
    options: { providers: ['fake'], models: { 'fake-1': { label: '假厂商' } }, resolutions: ['480p', '720p'],
               cny_per_sec: { '480p': 0.5, '720p': 1 }, max_clip_sec: 10, max_refs: 3, first_frame: true,
               frame_with_refs: false, audio_modes: ['tts_all', 'silent'], rate_note: '假厂商', typical_sec: [180, 420] } }
  const d = await boot('/novels/n1/overview', 'alice')
  filmSession = session
  await act(async () => { await d.router.navigate('/novels/n1/chapters/c1/render/canvas') })
  await settle(400)
  const tab = (name: string) => [...doc.body.querySelectorAll('.tlc__tabs button')]
    .find((x) => (x.textContent ?? '').trim() === name) as unknown as HTMLElement | undefined
  must(!!tab('出片') && tab('出片')!.getAttribute('aria-pressed') === 'false', '画布打开，侧栏不在出片页')
  filmTasks = [{ id: 'v1:compose', item_id: 'compose', kind: 'compose', novel_id: 'n1', chapter_id: 'c1', version_id: 'v1',
                 work_title: '药', chapter: '第一章', state: 'running', elapsed_sec: 10, typical_sec: null,
                 ended_at: null, cost_cny: null, cancel: null }]
  await act(async () => { pokeFilmTasks() }); await settle(200)
  const openCompose = async () => {
    if (!doc.body.querySelector('[data-testid="activity-panel"]')) await click(d.q('[data-testid="activity-bell"]')!)
    const row = doc.body.querySelector('[data-testid="activity-film-running"]') as unknown as HTMLElement
    await click(button(row, '查看')!)
    await settle(300)
  }
  await openCompose()
  must(tab('出片')!.getAttribute('aria-pressed') === 'true' && !!doc.body.querySelector('.compose'),
       `点合成任务：画布已开也切到出片页并显示合成区 ${tab('出片')?.getAttribute('aria-pressed')} ${!!doc.body.querySelector('.compose')} ${doc.body.querySelector('.tlc__panel')?.textContent?.slice(0, 200)} ${d.here()}`)
  await click(tab('本镜')!)
  must(tab('出片')!.getAttribute('aria-pressed') === 'false' && !doc.body.querySelector('.compose'), '手动切走')
  must((d.router.state.location.state as { panel?: string } | null)?.panel === 'film', '地址 state 里仍留着 panel:film')
  await openCompose()
  must(tab('出片')!.getAttribute('aria-pressed') === 'true' && !!doc.body.querySelector('.compose'),
       '切走后再点合成任务：再次切到出片页并显示合成区')
  await d.done()
}

{
  const { pokeFilmTasks } = await import('../src/filmTasks')
  // 面板取消：带用户确认的种类；服务端已转成扣费种类回 409 → 重读后重新确认，确认前不发第二次
  const e = await boot('/novels/n1/overview', 'alice')
  filmSession = { provider: 'fake', model: 'fake-1', resolution: '720p', audio_mode: 'silent', budget_cny: 100000,
    confirm_over_cny: 20, spent_cny: 0, clips: [], free: [], free_seq: 0, orphaned: [], counts: {}, remaining_cny: 0,
    reserved_cny: 0, uncertain_count: 0,
    options: { providers: ['fake'], models: { 'fake-1': { label: '假厂商' } }, resolutions: ['720p'],
               cny_per_sec: { '720p': 1 }, max_clip_sec: 10, max_refs: 3, first_frame: true,
               frame_with_refs: false, audio_modes: ['silent'], rate_note: '假厂商', typical_sec: [180, 420] } }
  await act(async () => { await e.router.navigate('/novels/n1/chapters/c1/render/canvas') })
  await settle(400)
  const mk = (cancel: 'free' | 'paid') => [{ id: 'v1:E01-C01', item_id: 'E01-C01', kind: 'clip', novel_id: 'n1', chapter_id: 'c1',
    version_id: 'v1', work_title: '药', chapter: '第一章', state: 'running', elapsed_sec: 5, typical_sec: [180, 420],
    ended_at: null, cost_cny: null, cancel, shot_ids: ['E01-SH001'] }]
  const confirmBtn = (ok: boolean) => doc.body.querySelector(`[data-testid="${ok ? 'confirm-ok' : 'confirm-cancel'}"]`) as unknown as HTMLElement
  const dlg = () => doc.body.querySelector('[data-testid="confirm-dialog"]')?.textContent ?? ''
  const startCancel = async () => {
    if (!doc.body.querySelector('[data-testid="activity-panel"]')) await click(e.q('[data-testid="activity-bell"]')!)
    await click(doc.body.querySelector('[data-testid="activity-film-cancel"]') as unknown as HTMLElement)
  }
  filmTasks = mk('free'); serverCancelKind = 'paid'
  await act(async () => { pokeFilmTasks() }); await settle(200)
  cancelCalls.length = 0; cancelBodies.length = 0
  await startCancel()
  must(!dlg().includes('服务商可能仍会生成并扣费') && cancelCalls.length === 0, '首次确认的是免费种类，还没发请求')
  filmTasks = mk('paid')           // 确认框开着时，服务端已转成扣费种类
  await click(confirmBtn(true))
  must(cancelCalls.length === 1 && JSON.stringify(cancelBodies[0]) === '{"expect":"free"}', `首次带 expect:free：${JSON.stringify(cancelBodies)}`)
  must(dlg().includes('服务商可能仍会生成并扣费'), '重读后弹出扣费风险确认')
  must(cancelCalls.length === 1, '重新确认之前不发第二次')
  await click(confirmBtn(false))
  must(cancelCalls.length === 1, '拒绝重新确认：不再发请求')
  // 再来一遍，这次确认：带 expect:paid，成功后任务列表与画布都重读
  filmTasks = mk('free')
  await act(async () => { pokeFilmTasks() }); await settle(200)
  await startCancel()
  filmTasks = mk('paid')
  await click(confirmBtn(true))
  must(dlg().includes('服务商可能仍会生成并扣费') && cancelCalls.length === 2, `又一次重新确认前只发了首次：${cancelCalls.length}`)
  const before = { tasks: flight.tasksCalls, session: sessionGets }
  serverCancelKind = null
  await click(confirmBtn(true))
  await settle(300)
  must(cancelCalls.length === 3 && JSON.stringify(cancelBodies[2]) === '{"expect":"paid"}', `确认后带 expect:paid：${JSON.stringify(cancelBodies)}`)
  must(flight.tasksCalls > before.tasks, '成功后任务列表重读')
  must(sessionGets > before.session, '成功后已打开的画布重读出片会话')
  await e.done()
}


{
  const { pokeFilmTasks } = await import('../src/filmTasks')
  // 已打开画布且会话已加载时点片段任务：state 同时带 focus 与 panelReq，两个一次性请求都要清掉（不互相写回）
  const session = { provider: 'fake', model: 'fake-1', resolution: '720p', audio_mode: 'tts_all', budget_cny: 100000,
    confirm_over_cny: 20, spent_cny: 0, clips: [], free: [], free_seq: 0, orphaned: [], counts: {}, remaining_cny: 0,
    reserved_cny: 0, uncertain_count: 0,
    options: { providers: ['fake'], models: { 'fake-1': { label: '假厂商' } }, resolutions: ['480p', '720p'],
               cny_per_sec: { '480p': 0.5, '720p': 1 }, max_clip_sec: 10, max_refs: 3, first_frame: true,
               frame_with_refs: false, audio_modes: ['tts_all', 'silent'], rate_note: '假厂商', typical_sec: [180, 420] } }
  const d = await boot('/novels/n1/overview', 'alice')
  filmSession = session
  await act(async () => { await d.router.navigate('/novels/n1/chapters/c1/render/canvas') })
  await settle(400)
  filmTasks = [{ id: 'v1:E01-C01', item_id: 'E01-C01', kind: 'clip', novel_id: 'n1', chapter_id: 'c1', version_id: 'v1',
                 work_title: '药', chapter: '第一章', state: 'running', elapsed_sec: 5, typical_sec: [180, 420],
                 ended_at: null, cost_cny: null, cancel: 'free', shot_ids: ['E01-SH001'] }]
  await act(async () => { pokeFilmTasks() }); await settle(200)
  await click(d.q('[data-testid="activity-bell"]')!)
  const row = doc.body.querySelector('[data-testid="activity-film-running"]') as unknown as HTMLElement
  await click(button(row, '查看')!)
  await settle(400)
  const st = d.router.state.location.state as { focus?: unknown; panelReq?: unknown } | null
  must(!st?.focus && !st?.panelReq, `点片段任务后两个一次性请求都已清掉：${JSON.stringify(st)}`)
  // 离开再返回（等同刷新/历史返回重新挂载）：不再带着请求
  await act(async () => { await d.router.navigate('/novels/n1/overview') }); await settle(200)
  await act(async () => { await d.router.navigate(-1) }); await settle(400)
  const st2 = d.router.state.location.state as { focus?: unknown; panelReq?: unknown } | null
  must(!st2?.focus && !st2?.panelReq, `返回后仍无残留请求：${JSON.stringify(st2)}`)
  await d.done()
}

{
  const { pokeFilmTasks } = await import('../src/filmTasks')
  // 请求在途且有待补刷时退出登录：旧响应返回后不再发新请求
  const f = await boot('/novels/n1/overview', 'alice')
  tasksDelay = 600
  await act(async () => { pokeFilmTasks() }); await settle(100)
  await act(async () => { pokeFilmTasks() }); await settle(50)
  await click(f.container.querySelector('[aria-label="退出"]') as unknown as HTMLElement)
  await settle(50)
  const calls = flight.rawTasks
  await settle(1200)
  must(flight.rawTasks === calls, `退出后旧响应返回不应再补刷：${calls} -> ${flight.rawTasks}`)
  tasksDelay = 0
  await f.done()
}


console.log('\nALL PASS')
process.exit(0)
