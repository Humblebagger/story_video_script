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
/** 测试用：让章节与版本的读取慢下来（lag 毫秒），或卡在 gate 上直到放行 */
let lag = 0
let gate: Promise<void> | null = null
g.fetch = async (url: string, init?: { method?: string; body?: string; headers?: Record<string, string> }) => {
  const path = String(url).replace(/^\/api/, '').split('?')[0]
  const method = init?.method ?? 'GET'
  const json = (data: unknown) => ({ ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(data)) })
  const err = (status: number, detail: unknown) => ({ ok: false, status, statusText: '',
    text: async () => JSON.stringify({ detail }), json: async () => ({ detail }) })
  if (path === '/healthz') return json({ status: 'ok', model: 'stub', api_key_configured: true, users: 2 })
  if (path === '/auth/login' && method === 'POST') {
    const b = JSON.parse(init!.body!)
    return users[b.username] ? json({ token: `tok-${b.username}`, user: userOf(b.username) }) : err(401, '用户名或密码不正确')
  }
  const h = init?.headers?.Authorization ?? ''
  const who = h.startsWith('Bearer tok-') ? h.slice(11) : null
  if (!who || !users[who]) return { ok: false, status: 401, text: async () => '{"detail":"未登录"}', json: async () => ({ detail: '未登录' }) }
  if (path === '/auth/me') return json(userOf(who))
  if (path === '/jobs') return json({ jobs: [] })
  if (path === '/novels' && method === 'GET') return json({ novels: [{ id: novel.id, title: novel.title, updated_at: '', chapters: novel.chapters.length, asset_counts: counts(novel.memory.assets) }] })
  const m = path.match(/^\/novels\/([^/]+)(?:\/chapters\/([^/]+)(?:\/versions\/([^/]+)(\/.*)?)?)?(\/summary)?$/)
  if (m && method === 'GET') {
    const [, nid, cid, vid, rest, summary] = m
    if (nid !== novel.id) return err(404, '小说不存在')
    if (summary) return err(404, 'stub')                                  // 费用表拿不到就不显示
    if (!cid) return json(novelView(novel))
    if (lag) await new Promise((r) => setTimeout(r, lag))
    if (vid && gate) await gate
    const c = novel.chapters.find((x) => x.id === cid)
    if (!c) return err(404, '章节不存在')
    if (!vid) return json(chapterView(c))
    const v = c.versions.find((x) => x.id === vid)
    if (!v) return err(404, '版本不存在')
    if (!rest) return json({ ...v, novel_id: nid, chapter_id: cid, params: {}, quality_report: null })
    if (rest === '/keyframes') return json({ shots: [] })
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
const { setSession, clearSession } = await import('../src/auth')
type Router = ReturnType<typeof createMemoryRouter>

const doc = win.document as unknown as Document
const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }
const settle = async (ms = 80) => { await act(async () => { await new Promise((r) => setTimeout(r, ms)) }) }

/** 从某个地址起一个全新的应用；who 为空 = 未登录 */
async function boot(path: string, who?: string) {
  resetData()
  win.localStorage.clear()
  clearSession()
  if (who) setSession(`tok-${who}`, userOf(who))
  const container = doc.createElement('div')
  doc.body.appendChild(container)
  const root = createRoot(container)
  const router: Router = createMemoryRouter(routes, { initialEntries: [path] })
  await act(async () => { root.render(<AppRoot router={router} />) })
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
  must(a.here() === '/' && !a.has('管理后台'), `普通用户不能停在后台，实际 ${a.here()}`)
  await a.done()
  const b = await boot('/admin', 'root')
  must(b.here() === '/admin' && b.has('管理后台'), '管理员可以直接打开后台')
  await b.done()
}
console.log('6. 非管理员 /admin → 回首页 ✓')

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

if (unhandled.size) console.log('（桩后端未处理：' + [...unhandled].join('，') + '）')
console.log('\nALL PASS')
process.exit(0)
