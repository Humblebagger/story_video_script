/** 交互流程回归：在真实 DOM（happy-dom）里驱动 App，用桩后端替代真实转换。
 *
 *  会话结构是 小说 → 章节 → 版本。重点守的是「放到后台还能不能回来」——这条路径一旦断掉，
 *  分钟级的任务就既看不见也点不回去，用户只能干等。类型检查与构建都拦不住这种 bug。
 *
 *  跑法：npm test
 */
import { Window } from 'happy-dom'

/* ---------- DOM / 通知 / fetch 三件套要在 React 之前装好 ---------- */

const win = new Window({ url: 'http://localhost:5173' })
const g = globalThis as Record<string, unknown>
// navigator 等在 Node 里是只读访问器，直接赋值会抛，统一用 defineProperty 覆盖
for (const k of ['window', 'document', 'navigator', 'location', 'HTMLElement',
                 'Element', 'Node', 'Event', 'CustomEvent', 'getComputedStyle',
                 'localStorage', 'sessionStorage', 'KeyboardEvent', 'MouseEvent', 'matchMedia',
                 'ResizeObserver', 'MutationObserver']) {
  Object.defineProperty(g, k, {
    value: (win as unknown as Record<string, unknown>)[k],
    writable: true, configurable: true,
  })
}
g.IS_REACT_ACT_ENVIRONMENT = true
// 首页的进场动效（motion whileInView）要用这两个浏览器接口，happy-dom 没有全局版本：补最小桩
g.IntersectionObserver ??= class { observe() {} unobserve() {} disconnect() {} takeRecords() { return [] } }
g.requestAnimationFrame ??= (cb: (t: number) => void) => setTimeout(() => cb(Date.now()), 16)
g.cancelAnimationFrame ??= (id: number) => clearTimeout(id)

const notifications: { title: string; body: string }[] = []
class FakeNotification {
  static permission = 'granted'
  static requestPermission = async () => 'granted'
  constructor(title: string, opts?: { body?: string }) {
    notifications.push({ title, body: opts?.body ?? '' })
  }
}
;(win as unknown as Record<string, unknown>).Notification = FakeNotification
g.Notification = FakeNotification

// localStorage：happy-dom 提供，但要确保 App 启动时是干净的未登录态
win.localStorage.clear()

/* ---------- 桩后端：小说 → 章节 → 版本 + 可手动结束的转换任务 ---------- */

interface StubJob {
  id: string; status: string; log: string[]; result: unknown
  quality_report: string | null; error: string | null; verification?: unknown
  created_at: string; work_title: string; chapter: string; chars: number
  user_id: string; progress?: unknown; partial_batches?: number
  novel_id: string; chapter_id: string
}
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

const jobs = new Map<string, StubJob>()
const users = new Map<string, string>()
const novelsOf = new Map<string, StubNovel[]>()
const shelf = (u: string) => {
  if (!novelsOf.has(u)) novelsOf.set(u, [])
  return novelsOf.get(u)!
}
const user = (name: string) => ({ id: name, username: name, created_at: '',
                                  ...(name === 'boss' ? { role: 'admin' } : {}) })
const auth = (init?: { headers?: Record<string, string> }) => {
  const h = (init?.headers ?? {}).Authorization ?? ''
  return h.startsWith('Bearer tok-') && users.has(h.slice(11)) ? h.slice(11) : null
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
/** 前端 PUT 回来的编辑结果，用于校验编辑没有破坏跨引用 */
const saved: Record<string, never>[] = []
const renderCalls: { seconds: number; shots: number; model: string }[] = []
let seq = 0
let ids = 0

const VERIFIED = { status: 'verified', findings: [], coverage: { selected: ['u0001'], covered: ['u0001'], waived: [], failed: [] } }
const INVALID = {
  status: 'failed',
  findings: [{
    rule_id: 'SOURCE-FROZEN-002', severity: 'critical',
    object_path: '/episodes/0/shots/0/dialogue/0/text',
    message: '台词不是所引原文句的逐字摘录',
    unit_refs: ['u0001'], evidence_quote: '小栓——你坐着，不要到这儿来。',
    expected: '小栓', actual: '小栓（改写）',
  }],
  coverage: { selected: ['u0001', 'u0002'], covered: ['u0001'], waived: [], failed: ['u0002'] },
}
/** 下一次 PUT /history 的复验判定；置一次用一次 */
let nextSaveVerdict: { status: string; verification: unknown } | null = null
/** 置位后下一次 /render/plan 返回 422 验证拦截 */
let blockNextRender = false

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


/** 采用：资产卡并进长期记忆，章后整理给出一条待确认的人物状态提议和本章摘要 */
function adopt(n: StubNovel, c: StubChapter, v: StubVersion) {
  c.adopted_version = v.id
  const assets = (v.result as typeof DOC).assets as unknown as Record<string, Card[]>
  for (const k of KINDS) {
    const lst = (n.memory.assets[k] ??= [])
    for (const card of assets[k] ?? []) {
      if (!lst.some((x) => x.id === card.id)) lst.push(JSON.parse(JSON.stringify(card)))
    }
  }
  n.memory.lifecycle = n.memory.lifecycle.filter((e) =>
    (e.since as { chapter_id: string }).chapter_id !== c.id || e.status === 'confirmed')
  n.memory.lifecycle.push({
    id: `l${++ids}`, character_id: 'C01', type: 'deceased', detail: '病死',
    since: { chapter_id: c.id, unit_ref: 'u0001' }, evidence_quote: '他推门。',
    origin: 'model', status: 'proposed', written_by: { chapter_id: c.id, version_id: v.id } })
  n.memory.plot.chapters = n.memory.plot.chapters.filter((s) => s.chapter_id !== c.id)
  n.memory.plot.chapters.push({ chapter_id: c.id, synopsis: '老栓推门进屋。', origin: 'model' })
  c.digest = { status: 'done', at: '', version_id: v.id, proposed: 1, dropped: [] }
}

function finishJob(id: string, status = 'succeeded') {
  const j = jobs.get(id)!
  j.status = status
  j.log.push('批 1 校验通过（第 1 次生成）')
  const n = shelf(j.user_id).find((x) => x.id === j.novel_id)!
  const c = n.chapters.find((x) => x.id === j.chapter_id)!
  const v = c.versions.find((x) => x.id === id)!
  v.status = status
  if (status === 'succeeded') {
    j.result = v.result = JSON.parse(JSON.stringify(DOC))
    j.verification = v.verification = VERIFIED
    if (!c.adopted_version) adopt(n, c, v)
  } else {
    j.error = v.error = '批 1 重试 2 次后仍未通过校验\nFAIL: 引用了不存在的资产 C09'
    j.verification = v.verification = INVALID
  }
}

g.fetch = async (url: string, init?: { method?: string; body?: string }) => {
  const path = String(url).replace(/^\/api/, '')
  const method = init?.method ?? 'GET'
  // 必须深拷贝：真 HTTP 会过一遍 JSON 序列化，桩若直接把自己持有的数组交出去，
  // 前端 state 与「后端」就共用同一个可变对象——后续写入会凭空污染 state，
  // 测出的现象既不真也不假，纯属噪声（曾据此误判过一次资产卡重复）。
  const json = (data: unknown) =>
    ({ ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(data)) })
  // detail 可以是字符串，也可以是结构化对象（渲染门返回 {message, verification}）
  const err = (status: number, detail: unknown) => ({
    ok: false, status, text: async () => JSON.stringify({ detail }),
    json: async () => ({ detail }) })
  const body = () => JSON.parse(init!.body!)

  if (path === '/healthz') return json({ status: 'ok', model: 'stub',
                                         api_key_configured: true, users: users.size })

  // 认证：注册/登录发 token，其余接口一律要带 token
  if (path === '/auth/register' && method === 'POST') {
    const b = body()
    if (users.has(b.username)) return err(400, '用户名已被占用')
    if ((b.password ?? '').length < 6) return err(400, '密码至少 6 位')
    users.set(b.username, b.password)
    return json({ token: `tok-${b.username}`, user: user(b.username) })
  }
  if (path === '/auth/login' && method === 'POST') {
    const b = body()
    if (users.get(b.username) !== b.password) return err(401, '用户名或密码不正确')
    return json({ token: `tok-${b.username}`, user: user(b.username) })
  }
  const who = auth(init)
  if (!who) return { ok: false, status: 401, text: async () => '{"detail":"未登录"}',
                     json: async () => ({ detail: '未登录' }) }
  if (path === '/auth/me') return json(user(who))
  if (path === '/render/plan' && method === 'POST') {
    const b = JSON.parse(init!.body!)
    if (blockNextRender) {
      blockNextRender = false
      // 服务端拒绝付费渲染时 detail 是对象而不是字符串
      return err(422, { message: '分镜未通过独立验证，禁止进入付费渲染',
                        verification: INVALID })
    }
    const shots = b.result.episodes.flatMap((e: { shots: unknown[] }) => e.shots)
    const seconds = shots.reduce((a: number, s: { duration_sec: number }) =>
      a + s.duration_sec, 0)
    renderCalls.push({ seconds: b.max_clip_seconds, shots: shots.length,
                       model: b.model ?? 'seedance-2.0' })
    return json({
      plan: {
        plan_version: '1', run_id: b.run_id, work_title: '药', chapter: '第一章',
        schema_version: '0.4', style_prefix: '写实', video: { aspect_ratio: '9:16' },
        max_clip_seconds: b.max_clip_seconds,
        assets: [{ id: 'C01', kind: 'characters', kind_zh: '角色', name: '华老栓',
                   image_prompt: '驼背老者', variants: [], constraints: [],
                   images: [{ view: 'front', uri: null, variant: null }],
                   have_images: 0, need_images: 1 }],
        clips: [{ id: 'E01-C01', episode: 'E01', shots: shots.map(
                    (s: { id: string }) => s.id),
                  start_sec: 0, duration_sec: seconds, playable_sec: seconds + 3,
                  speech_overflow: 3,
                  prompt: '写实，5秒，9:16竖屏\n\n0.0-5.0秒：远景，推门。',
                  reference_assets: ['C01', 'S01'], narration: [] },
                { id: 'E02-C01', episode: 'E02', shots: ['E02-SH001'],
                  start_sec: seconds, duration_sec: 10, playable_sec: 10,
                  speech_overflow: 0, prompt: '写实，10秒，9:16竖屏',
                  reference_assets: [], narration: [] }],
        estimate: { clips: 1, seconds, asset_images_total: 1, asset_images_missing: 1,
                    model: b.model ?? 'seedance-2.0',
                    model_label: b.model === 'seedance-2.0-mini'
                      ? 'Seedance 2.0 mini' : 'Seedance 2.0（标准）',
                    resolutions: '1080p 及以上',
                    cny_per_second: b.cny_per_second ?? (b.model === 'seedance-2.0-mini' ? 0.47 : 0.95),
                    playable_seconds: seconds + 13, speech_overflow_sec: 3, speech_cps: 4.5,
                    cny_once: b.model === 'seedance-2.0-mini' ? 2.4 : 4.7,
                    cny_with_retries: b.model === 'seedance-2.0-mini' ? 7.1 : 14.2,
                    retry_factor: 3, calibrated: b.cny_per_second != null,
                    rate: { tokens_per_second: 20600, cny_per_million_tokens: 46,
                            source: '2026-03 公开报道的方舟资费，非官方定价页' },
                    caveats: ['分辨率未建模：token 消耗与分辨率强相关。'],
                    note: '实际以控制台账单为准' },
        tiers: [{ id: 'seedance-2.0', label: 'Seedance 2.0（标准）',
                  resolutions: '1080p 及以上', cny_per_second: 0.95 },
                { id: 'seedance-2.0-mini', label: 'Seedance 2.0 mini',
                  resolutions: '480P / 720P', cny_per_second: 0.47 }],
      },
      packs: [{ episode: 'E01', title: '开端', markdown: '# 药 · E01 —— Seedance 2.0 生产包' }],
    })
  }

  if (path === '/jobs') return json({ jobs: [...jobs.values()].filter((j) => j.user_id === who).map((j) => ({
    id: j.id, status: j.status, created_at: j.created_at, work_title: j.work_title,
    chapter: j.chapter, chars: j.chars, log_lines: j.log.length,
    last_log: j.log[j.log.length - 1] ?? null, progress: j.progress ?? null,
    novel_id: j.novel_id, chapter_id: j.chapter_id })) })
  if (path.startsWith('/jobs/') && path.endsWith('/partial')) {
    const j = jobs.get(path.slice('/jobs/'.length, -'/partial'.length))
    if (!j || j.user_id !== who) return err(404, 'job 不存在')
    return j.partial_batches
      ? json({ doc: DOC, batches_done: j.partial_batches, batches: 3 })
      : err(404, '暂无已完成的批次可预览')
  }
  if (path.startsWith('/jobs/')) {
    const j = jobs.get(path.slice('/jobs/'.length))
    return j && j.user_id === who ? json(j) : err(404, 'job 不存在')
  }

  // ---------- 小说 → 章节 → 版本 ----------
  const seg = path.split('/').filter(Boolean).map(decodeURIComponent)
  if (seg[0] !== 'novels') throw new Error(`桩后端未实现的路径: ${method} ${path}`)
  const mine = shelf(who)
  if (seg.length === 1 && method === 'GET') return json({ novels: mine.map((n) => ({
    id: n.id, title: n.title, updated_at: n.updated_at, chapters: n.chapters.length,
    adopted: n.chapters.filter((c) => c.adopted_version).length,
    asset_counts: counts(n.memory.assets) })) })
  if (seg.length === 1 && method === 'POST') {
    const b = body()
    if (mine.some((n) => n.title === b.title)) return err(422, `《${b.title}》已存在`)
    const n: StubNovel = { id: `n${++ids}`, title: b.title, params: b.params ?? {},
      updated_at: '', chapters: [], memory: {
        assets: Object.fromEntries(KINDS.map((k) => [k, []])),
        numbering: { next_unit: 1, next_para: 1, next_episode: 1 },
        lifecycle: [], plot: { outline: '', chapters: [] }, constraints: [] } }
    mine.unshift(n)
    return json(novelView(n))
  }
  const n = mine.find((x) => x.id === seg[1])
  if (!n) return err(404, '小说不存在')
  if (seg.length === 2) {
    if (method === 'DELETE') { mine.splice(mine.indexOf(n), 1); return json({ deleted: n.id }) }
    if (method === 'PATCH') Object.assign(n, body())
    return json(novelView(n))
  }
  if (seg[2] === 'memory') {
    const m = n.memory
    if (seg.length === 3) return json(m)
    if (seg[3] === 'assets') {
      const lst = (m.assets[seg[4]] ??= [])
      if (method === 'DELETE') { m.assets[seg[4]] = lst.filter((c) => c.id !== seg[5]); return json({ deleted: seg[5] }) }
      const card = body()
      const i = lst.findIndex((c) => c.id === card.id)
      if (i >= 0) lst[i] = card; else lst.push(card)
      return json(card)
    }
    if (seg[3] === 'lifecycle') {
      if (seg.length === 4) {
        const e = { id: `l${++ids}`, ...body(), origin: 'user', status: 'confirmed',
                    since: { chapter_id: null, unit_ref: null }, evidence_quote: '', written_by: null }
        m.lifecycle.push(e)
        return json(e)
      }
      const e = m.lifecycle.find((x) => x.id === seg[4])
      if (!e) return err(404, '生命周期记录不存在')
      if (method === 'DELETE') { m.lifecycle.splice(m.lifecycle.indexOf(e), 1); return json({ deleted: seg[4] }) }
      const b = body()
      for (const k of Object.keys(b)) if (b[k] != null) e[k] = b[k]
      return json(e)
    }
    if (seg[3] === 'plot') {
      if (seg.length === 4) { m.plot.outline = body().outline; return json(m.plot) }
      m.plot.chapters = m.plot.chapters.filter((s) => s.chapter_id !== seg[5])
      m.plot.chapters.push({ chapter_id: seg[5], synopsis: body().synopsis, origin: 'user' })
      return json(m.plot.chapters[m.plot.chapters.length - 1])
    }
    if (seg[3] === 'constraints') {
      if (seg.length === 4) {
        const k = { id: `k${++ids}`, negative_prompt: '', keywords: [], enabled: true, ...body() }
        m.constraints.push(k)
        return json(k)
      }
      const k = m.constraints.find((x) => x.id === seg[4])!
      if (method === 'DELETE') { m.constraints.splice(m.constraints.indexOf(k), 1); return json({ deleted: seg[4] }) }
      Object.assign(k, body())
      return json(k)
    }
  }
  if (seg[2] === 'chapters' && seg.length === 3 && method === 'POST') {
    const b = body()
    const c: StubChapter = { id: `c${++ids}`, title: b.title, text: b.text ?? '',
      order: n.chapters.length + 1, adopted_version: null, versions: [], digest: null }
    n.chapters.push(c)
    return json(chapterView(c))
  }
  const c = n.chapters.find((x) => x.id === seg[3])
  if (!c) return err(404, '章节不存在')
  if (seg.length === 4) {
    if (method === 'DELETE') { n.chapters.splice(n.chapters.indexOf(c), 1); return json({ deleted: c.id }) }
    if (method === 'PATCH') Object.assign(c, body())
    return json(chapterView(c))
  }
  if (seg[4] === 'digest') return json({ digest: 'running' })
  if (seg[4] === 'versions' && seg.length === 5 && method === 'POST') {
    const id = `job${++seq}`
    c.versions.push({ id, created_at: new Date(seq * 1000).toISOString(), edited_at: null,
                      status: 'running', result: null, verification: null, error: null })
    jobs.set(id, { id, status: 'running', log: ['批 1/1（8 字符）：调用 LLM…'],
                   result: null, quality_report: null, error: null,
                   created_at: new Date(0).toISOString(), work_title: n.title,
                   chapter: c.title, chars: c.text.length, user_id: who,
                   novel_id: n.id, chapter_id: c.id })
    return json({ job_id: id, version_id: id, status_url: `/jobs/${id}` })
  }
  // 出片会话与合成（…/versions/{vid}/render/…）：本测试不出片，章节级只读查询一律得到「还没有出片会话」
  if (seg[4] === 'versions' && seg[6] === 'render') return err(404, '还没有出片会话')
  const v = c.versions.find((x) => x.id === seg[5])
  if (!v) return err(404, '版本不存在')
  if (seg[6] === 'adopt') {
    if (!['succeeded', 'completed_with_warnings'].includes(v.status)) return err(422, '这个版本不能采用')
    const changed = c.adopted_version !== v.id
    if (changed) adopt(n, c, v)
    return json({ chapter_id: c.id, adopted_version: v.id, added: 0, merged: 6,
                  retracted: 0, changed, digest: changed ? 'running' : undefined })
  }
  if (method === 'PUT') {
    const doc = body()
    saved.push(doc)
    // 服务端每次保存都整份复验并把结果带回来；nextSaveVerdict 用来演一次不通过
    const verdict = nextSaveVerdict ?? { status: 'succeeded', verification: VERIFIED }
    nextSaveVerdict = null
    Object.assign(v, { result: doc, status: verdict.status, verification: verdict.verification,
                       edited_at: '2026-08-03T15:00:00+00:00' })
    return json({ id: v.id, edited_at: v.edited_at, ...verdict })
  }
  if (method === 'DELETE') { c.versions.splice(c.versions.indexOf(v), 1); return json({ deleted: v.id }) }
  return json({ ...v, novel_id: n.id, chapter_id: c.id, params: {}, quality_report: null })
}

/* ---------- 驱动 ---------- */

const { act } = await import('react')
const { createRoot } = await import('react-dom/client')
const { default: App } = await import('../src/App')
const { notifyUnauthorized } = await import('../src/auth')
const { NovelPage } = await import('../src/components/NovelPage')
const { I18nProvider } = await import('../src/i18n')
const { setCurrentLocale } = await import('../src/i18n/core')

const doc = win.document as unknown as Document
const container = doc.createElement('div')
doc.body.appendChild(container)
const root = createRoot(container)

const settle = async (ms = 60) => {
  await act(async () => { await new Promise((r) => setTimeout(r, ms)) })
}
const html = () => container.innerHTML
const has = (s: string) => html().includes(s)
const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }

function findByText(tag: string, text: string): HTMLElement {
  const hit = [...container.querySelectorAll(tag)]
    .find((e) => (e.textContent ?? '').includes(text))
  if (!hit) throw new Error(`✗ 找不到含「${text}」的 <${tag}>`)
  return hit as unknown as HTMLElement
}

const click = async (el: HTMLElement) => {
  await act(async () => { el.click() })
  await settle()
}
const confirmDialog = () => win.document.body.querySelector('[data-testid="confirm-dialog"]')
async function answer(ok: boolean) {
  const b = win.document.body.querySelector<HTMLElement>(`[data-testid="${ok ? 'confirm-ok' : 'confirm-cancel'}"]`)
  must(!!b, '应弹出确认框')
  await click(b!)
  await settle(300)          // 确认框有退场动画
}
/** 章节工作流：点步骤条上的某一步；右下角的主按钮 */
const goStep = (id: string) => click(container.querySelector(`[data-step="${id}"]`) as unknown as HTMLElement)
const primary = () => container.querySelector('[data-testid="primary-action"]') as unknown as HTMLButtonElement
const onStep = (id: string) => !!container.querySelector(`[data-step="${id}"][aria-current="step"]`)

/** 退出后回到首页：先点右上角「登录」打开对话框 */
const openLogin = async () => {
  await click(container.querySelector('[data-testid="landing-login"]') as unknown as HTMLElement)
}

/** 选卡浮层用的是 mousedown（click 之前 textarea 已 blur，浮层会先被收掉），
 *  所以测试也必须发 mousedown，发 click 是测不到的 */
const mouseDown = async (el: HTMLElement) => {
  await act(async () => {
    el.dispatchEvent(new win.MouseEvent('mousedown', { bubbles: true }) as unknown as Event)
  })
  await settle()
}

await act(async () => { root.render(<App />) })
await settle()

// 0. 未登录：只能看到登录页，看不到任何业务界面
must(has('登录') && !has('新建小说'), '未登录时不应显示业务界面')
must(has('第一个注册的账号'), '服务端无账号时应引导注册')

const setter = Object.getOwnPropertyDescriptor(
  win.HTMLTextAreaElement.prototype, 'value')!.set!
const inputSetter = Object.getOwnPropertyDescriptor(
  win.HTMLInputElement.prototype, 'value')!.set!

const type = async (el: HTMLElement, text: string, isArea = true) => {
  await act(async () => {
    (isArea ? setter : inputSetter).call(el, text)
    el.dispatchEvent(new win.Event('input', { bubbles: true }) as unknown as Event)
  })
  await settle()
}

// 注册：密码需二次确认，不一致时不许提交
const fields = () =>
  [...container.querySelectorAll('.login__field input')] as unknown as HTMLElement[]
const [uIn, pIn, cIn] = fields()
must(!!cIn, '注册表单应有确认密码输入框')
await type(uIn, 'alice', false)
await type(pIn, 'pw123456', false)
await type(cIn, 'pw12345X', false)
must(has('两次输入的密码不一致'), '密码不一致应当场提示')
must((findByText('button', '注册并进入') as HTMLButtonElement).disabled,
     '密码不一致时提交按钮必须禁用')
await type(cIn, 'pw123456', false)
must(!has('两次输入的密码不一致'), '改对后提示应消失')
await click(findByText('button', '注册并进入'))
await settle(400)
must(has('新建小说'), '注册后应进入新建小说')
must(has('alice'), '顶栏应显示当前用户')
must(![...container.querySelectorAll('button')].some((b) => b.textContent === '管理'),
     '普通用户不应看到「管理」入口')
console.log('0. 未登录挡在门外 / 密码二次确认 → 注册后进入 ✓')

// 1. 新建小说：导入原文按章节标记自动拆章
const field = (name: string) => findByText('label', name).querySelector('input') as unknown as HTMLElement
await type(field('小说标题'), '药', false)
await type(container.querySelector('.form__text textarea') as unknown as HTMLElement,
           '一\n他推门。\n二\n走进屋里。\n')
must(has('识别出 2 章'), '应按「一 二」识别出两章')
await click(findByText('button', '建小说并导入 2 章'))
await settle(150)
must(shelf('alice')[0]?.chapters.length === 2, '应建出小说与两个章节')
must(has('本章原文') && (primary()?.textContent ?? '').includes('生成分镜'), '建完应直接打开第一章')
must(onStep('storyboard'), '新章节有原文、还没有版本：应停在 ② 生成分镜')
must(!!container.querySelector('.hnovel.is-open') && has('未转换'), '侧栏应展开小说并列出章节')
console.log('1. 新建小说 → 导入原文自动拆章 / 打开第一章 ✓')

// 2. 转换本章 → 任务面板
await click(primary())
must(has('放到后台'), '提交后应显示任务面板')
must(jobs.size === 1 && jobs.get('job1')!.chapter_id === shelf('alice')[0].chapters[0].id,
     '桩后端应收到本章的转换任务')
console.log('2. 转换本章 → 任务面板（转换中）✓')

// 3. 放到后台：回到章节页，任务仍留在侧栏里可见
await click(findByText('button', '放到后台'))
must(!has('放到后台'), '放到后台后不应还停在任务面板')
must(has('本章原文'), '放到后台后应回到章节页')
must(has('批 1/1（8 字符）：调用 LLM…'), '侧栏必须留着在跑的任务及其最新日志')
must(has('生成中…'), '章节上要标出正在转换')
must(primary().disabled && (primary().textContent ?? '').includes('生成中…'), '生成中主按钮显示「生成中…」且不能再点')
console.log('3. 放到后台 → 回到章节页，任务留在侧栏 ✓')

// 4. 点侧栏的在跑任务：必须能回到任务面板
await click(findByText('li', '批 1/1（8 字符）：调用 LLM…'))
must(has('放到后台'), '点侧栏在跑任务应能回到任务面板')
console.log('4. 点侧栏 → 回到任务面板 ✓')

// 4b. 进度可见：任务面板给出批次/尝试/阶段与剩余时间，侧栏给单行摘要
jobs.get('job1')!.progress = {
  batches: 3, batch: 2, batch_chars: 2000, total_chars: 4500, done_chars: 1300,
  attempt: 2, max_attempts: 3, phase: 'repairing', elapsed_sec: 125, eta_sec: 130,
}
await settle(3600)          // 任务面板 1.5s 一轮、侧栏 3s 一轮，都等到
must(has('受限修复'), '任务面板应显示当前阶段')
must(has('批 2/3 · 第 2 次尝试（最多 3）'), '任务面板应显示批次与尝试次数')
must(has('已用 2 分 05 秒'), '应显示已用时间')
must(has('预计还需约 2 分钟'), '应显示预计剩余时间（分钟粒度）')
must(!!container.querySelector('[role="progressbar"]'), '应有进度条')
must(has('批 2/3 · 受限修复 · 还需约 2 分钟'), '侧栏应显示单行进度摘要')
jobs.get('job1')!.progress = { ...jobs.get('job1')!.progress as object,
                               done_chars: 0, eta_sec: null, batch: 1 }
await settle(1600)
must(has('第一批完成后估算剩余时间'), '第一批完成前不给剩余时间，要说明原因')
console.log('4b. 进度可见 → 批次/尝试/阶段 + 已用/剩余时间，侧栏单行摘要 ✓')

// 4c. 分批先看：已完成的批次先给人审阅，只读；又跑完一批时预览自动刷新
must(!has('先审阅已完成的'), '还没有完成的批次时不该出现预览入口')
jobs.get('job1')!.partial_batches = 1
await settle(1600)
await click(findByText('button', '先审阅已完成的 1 批'))
must(has('预览：只含已完成的前 1/3 批'), '预览要标明只含前几批、只读')
must(!has('编辑分镜') && !has('保存修改'), '预览不能编辑、不能保存')
must(![...container.querySelectorAll('.tabs__btn')].some((b) => b.textContent === '渲染'),
     '部分产物不能进渲染')
must(has('放到后台'), '预览时任务面板仍在，转换照常继续')
jobs.get('job1')!.partial_batches = 2
await settle(1600)
must(has('预览：只含已完成的前 2/3 批'), '又跑完一批时预览应自动刷新')
console.log('4c. 分批先看 → 只读预览（不可编辑/保存/渲染），新批次完成自动刷新 ✓')

// 5. 再放后台，让它在「没人看着」的情况下跑完：应弹通知，首个成功版本自动采用
await click(findByText('button', '放到后台'))
finishJob('job1')
await settle(3600)          // 等一次巡检（在跑时 3s 一轮）
must(notifications.some((n) => n.title === '转换完成'), '后台跑完必须弹桌面通知')
must(!has('批 1/1（8 字符）：调用 LLM…'), '跑完后不应还挂在「在跑」列表里')
must(has('✓ 采用 v1'), '首个成功版本应自动采用，侧栏标出采用版')
console.log('5. 后台跑完 → 桌面通知 / 自动采用 ✓（共', notifications.length, '条）')

// 6. 打开章节：摆出采用版
const chapterItem = (i: number) =>
  container.querySelectorAll('.hchap__item')[i] as unknown as HTMLElement
await click(chapterItem(0))
must(has('E01-SH001') && has('推门'), '打开章节应摆出采用版的分镜')
must(onStep('render'), '有采用版、还没有出片会话：进章节应停在 ④ 出片')
must(has('编辑分镜') && has('下载 JSON'), '产物应带编辑与下载入口')
must(has('v1 ★') && has('采用版：资产卡'), '版本条要标出采用版')
must(has('1 条人物状态待确认'), '章后整理的结果要在章节页说出来')
await click(findByText('button', '资产卡'))
must(has('华老栓') && has('C01'), '资产卡页签应展示角色卡')
console.log('6. 章节 → 采用版产物 + 页签切换 ✓')

// 7. 重转出一个失败版本：原因要摊在面板上
await goStep('storyboard')
must((primary().textContent ?? '').includes('重新生成（新版本）'), '已有版本时主按钮是「重新生成（新版本）」')
await click(primary())
finishJob('job2', 'failed')
await settle(1800)          // 附着轮询 1.5s 一轮
must(has('转换失败，未通过的原因如下'), '失败应高亮原因区块')
must(has('不存在的资产 C09'), '失败的具体原因必须显示给用户')
// 报错文本之外还得给结构化发现——用户要据此改，不是据此叹气
must(has('SOURCE-FROZEN-002') && has('台词不是所引原文句的逐字摘录'),
     '失败任务应摊开逐条验证发现')
await click(findByText('button', 'v2'))
must(has('这一版转换失败'), '点开失败版本要说明它没有产物')
must(!has('采用此版') || (findByText('button', '采用此版') as HTMLButtonElement).disabled,
     '失败版本不能采用')
console.log('7. 失败 → 原因摊开显示（含结构化验证发现）/ 失败版本不可采用 ✓')

// 8. 资产卡编辑：改得动内容，但跨引用的 ID 一个都不能变
await click(findByText('button', 'v1'))
await click(findByText('button', '编辑分镜'))
await click(findByText('button', '资产卡'))

must(!!container.querySelector('.acard .acard__id svg'), '编辑态下应标出锁死的 ID')
const idCell = findByText('span', 'C01')
must(idCell.querySelector('input') === null, '资产 ID 不可编辑')
must(findByText('div', 'default').querySelector('input') === null
     || findByText('span', 'default').tagName === 'SPAN', '服装 ID 不可编辑')

// 改角色名与外貌
const nameInput = [...container.querySelectorAll('.acard header input')][0] as HTMLElement
await type(nameInput, '华老栓（改）', false)
const ageInput = [...container.querySelectorAll('.amap__row input')]
  .find((e) => (e as HTMLInputElement).value === '五十余岁') as unknown as HTMLElement
must(!!ageInput, '外貌字段应可编辑')
await type(ageInput, '六十岁上下', false)
console.log('8. 资产卡 → 名称/外貌可编辑，ID 锁死 ✓')

// 8b. 未保存提示条：撤销回到上次保存的样子；再改一次后用提示条保存
const bar = () => container.querySelector('[data-testid="unsaved-bar"]') as HTMLElement | null
const barBtn = (label: string) =>
  [...bar()!.querySelectorAll('button')].find((b) => b.textContent === label) as HTMLElement
must(has('有未保存的修改') && !!bar(), '编辑后应出现未保存提示条')
await click(barBtn('撤销'))
await settle(500)          // 提示条有退场动画
must(!bar(), '撤销后提示条应消失')
must(![...container.querySelectorAll('.acard header input')]
  .some((e) => (e as HTMLInputElement).value === '华老栓（改）'), '撤销后内容应回到上次保存的样子')
await click(findByText('button', '资产卡'))
await type([...container.querySelectorAll('.acard header input')][0] as HTMLElement, '华老栓（改）', false)
await type([...container.querySelectorAll('.amap__row input')]
  .find((e) => (e as HTMLInputElement).value === '五十余岁') as unknown as HTMLElement, '六十岁上下', false)
// 有未保存的修改时离开：先弹确认；取消就留在原处，修改还在
await click(findByText('button', '新建小说'))
must((confirmDialog()?.textContent ?? '').includes('有未保存的修改'), '离开未保存的画布前应确认')
await answer(false)
must(!confirmDialog(), '确认框应关闭'); must(!!bar(), '取消离开：留在原处，未保存提示条还在')
console.log('8b. 未保存提示条 → 撤销回到原样 / 再改 / 取消离开 ✓')

// 9. 保存并核对：内容改了，ID 与镜头引用逐字未变（用提示条里的「保存」）
//    先回看 ③：保存后「该做的那一步」从 ③ 回到 ④，不算往后走，视图不能被拉走
await goStep('review')
must(onStep('review') && !!bar(), '回看 ③，提示条仍在')
await click(barBtn('保存'))
must(saved.length === 1, '编辑后应 PUT 回后端')
await settle(500)
must(!bar(), '保存成功后提示条应消失')
must(onStep('review'), '保存后视图应停在用户正看的 ③，不能跳步')
const out = saved[0] as unknown as typeof DOC
const c0 = out.assets.characters[0]
must(c0.name === '华老栓（改）', '角色名应已更新')
must(c0.appearance!['age'] === '六十岁上下', '外貌字段应已更新')
must(c0.id === 'C01', '资产 ID 必须保持 C01')
must(c0.outfits![0].id === 'default', '服装 ID 必须保持 default')
must(out.assets.props[0].states.map((s) => s.id).join() === 'lit,dark', '状态 ID 必须原样')
must(Object.keys(c0.outfits![0]).join() === 'id,description',
     '服装条目不得多出 schema 不认的字段')
const sh = out.episodes[0].shots[0]
must(sh.location_ref === 'S01' && sh.characters[0].ref === 'C01'
     && sh.characters[0].outfit === 'default' && sh.prop_refs[0].ref === 'P01'
     && sh.prop_refs[0].state === 'lit', '镜头层的跨引用必须逐字未变')
must(JSON.stringify(out.source.units) === JSON.stringify(DOC.source.units), '原文 units 不得变动')
console.log('9. 保存 → 内容已改 / ID 与跨引用逐字未变 ✓')

// 9b. 再转一版并改采用它
await goStep('storyboard')
must((primary().textContent ?? '').includes('重新生成（新版本）'), '主按钮应是「重新生成（新版本）」')
await click(primary())
finishJob('job3')
await settle(1800)
must(has('E01-SH001') && has('采用此版'), '新版本跑完应摆出来，可以改采用')
must(onStep('render'), '生成完成后应自动跟到 ④ 出片（新版本没有出片会话）')
await click(findByText('button', '采用此版'))
await settle(120)
must(shelf('alice')[0].chapters[0].adopted_version === 'job3', '采用应写回后端')
must(has('v3 ★') && has('已采用'), '版本条应改标 v3 为采用版')
console.log('9b. 新版本 → 改采用 ✓')

// 10. 小说页：章后整理的人物状态提议高亮待确认，确认后才进后续章节的转换
await click(container.querySelector('.hnovel .hrun') as unknown as HTMLElement)
must(has('《药》') && has('人物生命周期（1 待确认）'), '小说页要突出待确认的提议')
must(has('他推门。') && has('模型提议'), '提议要附原文证据')
// 页签文案里也有「待确认」，按钮要按全文匹配
await click([...container.querySelectorAll('.life__acts button')]
  .find((b) => b.textContent === '确认') as unknown as HTMLElement)
must(shelf('alice')[0].memory.lifecycle[0].status === 'confirmed', '确认应写回后端')
must(!has('1 待确认'), '确认后不再提示待确认')
console.log('10. 小说页 → 人物生命周期提议附证据 / 确认 ✓')

// 11. 资产库并入小说页：新建 / 编辑
await click(findByText('button', '资产库'))
must(has('华老栓') && has('C01'), '资产库应列出采用版写入的卡片')
const addName = container.querySelector('.lib__add input') as unknown as HTMLElement
await type(addName, '赵四', false)
await click(findByText('button', '＋ 新建'))
must(shelf('alice')[0].memory.assets.characters.some((c) => c.id === 'C03' && c.name === '赵四'),
     '新建卡应写回长期记忆并自动续号（C01、C02 已占用）')
const nameInputs = [...container.querySelectorAll('.acard header input')] as unknown as HTMLElement[]
await type(nameInputs[0], '华老栓（库中改名）', false)
await click(findByText('button', '保存修改'))
must(shelf('alice')[0].memory.assets.characters[0].name === '华老栓（库中改名）', '编辑应 PUT 回后端')
console.log('11. 小说页资产库 → 新建（自动续号）/ 编辑并保存 ✓')

// 11b. 创作限制与主线剧情
await click(findByText('button', '创作限制'))
await type(field('规则（给模型看）'), '不出现血腥画面', false)
await type(field('负面提示词（可空，逗号分隔）'), '血迹，伤口特写', false)
await type(field('扫描关键词（可空，逗号分隔）'), '血，伤口', false)
await click(findByText('button', '＋ 新增限制'))
const k = shelf('alice')[0].memory.constraints[0]
must(k?.text === '不出现血腥画面' && JSON.stringify(k.keywords) === '["血","伤口"]',
     '限制应连同负面提示词与关键词写回')
must(has('负面提示词：血迹，伤口特写'), '限制应列在页面上')
await click(container.querySelector('.cons__item input[type="checkbox"]') as unknown as HTMLElement)
must(shelf('alice')[0].memory.constraints[0].enabled === false, '可以停用一条限制')
// 删除一条限制：取消不删，确认才删
await type(field('规则（给模型看）'), '临时规则', false)
await click(findByText('button', '＋ 新增限制'))
must(shelf('alice')[0].memory.constraints.length === 2, '新增了第二条限制')
const delBtn = () => [...container.querySelectorAll('.hrun__del')].pop() as unknown as HTMLElement
await click(delBtn())
must((confirmDialog()?.textContent ?? '').includes('删除这条限制'), '删除限制前应确认')
await answer(false)
must(shelf('alice')[0].memory.constraints.length === 2, '取消后不删除')
await click(delBtn())
await answer(true)
must(shelf('alice')[0].memory.constraints.length === 1, '确认后才删除')
await click(findByText('button', '主线剧情'))
must(has('老栓推门进屋。') && has('自动'), '逐章摘要应列出（采用后自动生成）')
await type(container.querySelector('.plot textarea') as unknown as HTMLElement, '华老栓买药救子。')
await click(findByText('button', '保存梗概'))
must(shelf('alice')[0].memory.plot.outline === '华老栓买药救子。', '全书梗概应写回')
console.log('11b. 创作限制（负面提示词/关键词/停用）/ 主线剧情（梗概 + 逐章摘要）✓')

// 11c. 小说页默认是「章节」卡片：含章节标题与「已采用」，点卡片进入章节
await click(container.querySelector('.hchap__item') as unknown as HTMLElement)     // 先进章节，再回小说页以重新挂载
await click(container.querySelector('.hnovel .hrun') as unknown as HTMLElement)
const tabOn = container.querySelector('.tabs__btn.is-on')
must((tabOn?.textContent ?? '') === '章节', '小说页无待确认提议时默认停在「章节」页签')
const cards = [...container.querySelectorAll('[data-testid="chapter-card"]')]
must(cards.length === 2 && (cards[0].textContent ?? '').includes('一')
     && (cards[0].textContent ?? '').includes('已采用')
     && (cards[1].textContent ?? '').includes('未生成'), '章节卡片应含标题、「已采用」与「未生成」')
must(has('＋ 新章节'), '应有「＋ 新章节」卡')
await click(cards[0] as unknown as HTMLElement)
must(!!container.querySelector('[data-step]'), '点卡片应进入章节工作流')
console.log('11c. 小说页章节卡片 → 默认页签 / 状态徽章 / 点卡片进章节 ✓')

// 11d. 英文：同一本小说单独渲染一次（App 之外包英文 Provider），页签与「新章节」按钮是英文，随后切回中文
{
  const enBox = doc.createElement('div')
  doc.body.appendChild(enBox)
  const enRoot = createRoot(enBox)
  const enNovel = JSON.parse(JSON.stringify(shelf('alice')[0]))
  await act(async () => {
    enRoot.render(
      <I18nProvider initial="en">
        <NovelPage novel={enNovel} running={[]} onChanged={() => {}} onDeleted={() => {}}
                   onOpenChapter={() => {}} onNewChapter={() => {}} />
      </I18nProvider>)
  })
  await settle()
  const enTabs = [...enBox.querySelectorAll('.tabs__btn')].map((b) => b.textContent ?? '')
  must(enTabs.includes('Chapters') && enTabs.includes('Plot') && enTabs.includes('Constraints'), '英文页签：' + enTabs.join('|'))
  must((enBox.textContent ?? '').includes('+ New chapter') && !(enBox.textContent ?? '').includes('新章节'), '「新章节」按钮应是英文')
  must(!!enBox.querySelector('button[aria-label="More actions"]'), '标题右侧应有「更多操作」菜单')
  await act(async () => { enRoot.unmount() })
  enBox.remove()
  setCurrentLocale('zh')
}
console.log('11d. 小说页英文 → 页签 / 新章节按钮 / 更多菜单 ✓')

// 12. 换个账号：看不到 alice 的任何东西
await click(findByText('button', '退出'))
await settle(100)
must(!container.querySelector('[data-testid="auth-dialog"]'), '已有账号时退出后不该自动弹出注册')
await openLogin()
must(has('login__tab') && !has('新建小说'), '退出后应回到登录页')
must(!has('第一个注册的账号'), '已有账号时不该再显示首次注册引导')
must(fields().length === 2, '登录模式下不该出现确认密码框')
// 已有账号时默认停在「登录」页签，先切到注册
const regTab = [...container.querySelectorAll('.login__tab')]
  .find((b) => (b.textContent ?? '').trim() === '注册') as unknown as HTMLElement
await click(regTab)
const [u2, p2, c2] = fields()
await type(u2, 'bob', false)
await type(p2, 'pw654321', false)
await type(c2, 'pw654321', false)
await click(findByText('button', '注册并进入'))
await settle(400)
must(has('bob') && !has('alice'), '顶栏应换成新用户')
must(!has('药') && !has('华老栓'), 'bob 不该看到 alice 的小说')
must(has('还没有小说'), 'bob 的书架应为空')
console.log('12. 换账号 → 小说与长期记忆完全隔离 ✓')

// 12b. 管理入口：管理员能进能出；401 / 退出后换成普通用户，不能落进后台
users.set('boss', 'pw000000')
const loginAs = async (name: string, pw: string) => {
  const [uu, pp] = fields()
  await type(uu, name, false)
  await type(pp, pw, false)
  await click(container.querySelector('button[type="submit"]') as unknown as HTMLElement)
  await settle(400)
}
const btn = (t: string) =>
  [...container.querySelectorAll('button')].find((b) => b.textContent === t) as unknown as HTMLElement | undefined
await click(findByText('button', '退出'))
await openLogin()
await loginAs('boss', 'pw000000')
must(!!btn('管理'), '管理员应看到「管理」入口')
await click(btn('管理')!)
must(has('管理后台') && !!btn('返回书架'), '点「管理」应进入后台')
await click(btn('返回书架')!)
must(!has('管理后台') && !!btn('管理'), '「返回书架」应回到书架')
await click(btn('管理')!)
must(has('管理后台'), '再次进入后台')
await act(async () => { notifyUnauthorized() })     // 后台开着时登录失效
await settle(50)
must(has('login__tab') && !has('管理后台'), '401 后应回到登录页')
must(has('登录已过期'), '401 后登录框应带过期提示')
await loginAs('bob', 'pw654321')
must(has('bob') && !has('管理后台') && !btn('管理') && !btn('返回书架'),
     '401 后换普通用户登录，不能落进后台，也不该有「管理」入口')
console.log('12b. 管理入口 → 管理员进出后台 / 401 后换普通用户不落进后台 ✓')

// 13. 从零建小说再设定人物——「先设定人物场景再去转换」是常见用法
await type(field('小说标题'), '鲍勃的新书', false)
await click(btn('建小说')!)       // 精确匹配：外壳里还有一个「新建小说」按钮
await settle(150)
must(shelf('bob').length === 1 && has('《鲍勃的新书》'), '不导入原文也能建小说，建完打开小说页')
await click(findByText('button', '资产库'))
const cardInput = container.querySelector('.lib__add input') as unknown as HTMLElement
for (const name of ['赵老三', '钱掌柜']) {
  await type(cardInput, name, false)
  await click(findByText('button', '＋ 新建'))
  await settle(60)
}
must(shelf('bob')[0].memory.assets.characters.length === 2, '应建出两张角色卡')
console.log('13. 空小说 → 先建角色卡 ✓')

// 14. 资产库搜索：按名称过滤，跨类别
const search = container.querySelector('.lib__search') as unknown as HTMLElement
await type(search, '赵老三', false)
must(has('匹配') && has('赵老三') && !has('钱掌柜'), '搜索应只留下命中的卡')
await type(search, '不存在的名字', false)
must(has('换个关键词试试'), '无命中时应给出提示')
await type(search, '', false)
must(has('赵老三') && has('钱掌柜'), '清空搜索应恢复全部')
console.log('14. 资产库搜索 → 按名称跨类别过滤 ✓')

// 15. 分镜里 @ 挂卡：形象锁定落到结构化引用，正文只留自然语句
await click(findByText('button', '退出'))
await openLogin()
const loginTab = [...container.querySelectorAll('.login__tab')]
  .find((b) => (b.textContent ?? '').trim() === '登录') as unknown as HTMLElement
await click(loginTab)
const [u3, p3] = fields()
must(!has('登录已过期'), '手动退出后的登录框不该带过期提示')
await type(u3, 'alice', false)
// 打错密码：显示服务端的原因，而不是当成登录过期
await type(p3, 'wrong-password', false)
await click(container.querySelector('button[type="submit"]') as unknown as HTMLElement)
must(has('用户名或密码不正确') && !has('登录已过期'), '密码错应显示服务端原因，不该当成登录过期')
await type(p3, 'pw123456', false)
// 页签和提交按钮文案都是「登录」，必须按 type=submit 取，否则点回的是页签
await click(container.querySelector('button[type="submit"]') as unknown as HTMLElement)
await settle(400)
must(has('药'), 'alice 应已重新登录并看到自己的小说')
await click(container.querySelector('.hnovel .hrun') as unknown as HTMLElement)
await click(chapterItem(0))
await click(findByText('button', '编辑分镜'))

const area = container.querySelector('.ed__at textarea') as unknown as HTMLTextAreaElement
must(!!area, '编辑态的画面描述应带 @ 挂卡的浮层容器')
/** 打字要连光标一起模拟：@ 片段是按光标位置往前找的 */
const typeAt = async (el: HTMLTextAreaElement, text: string) => {
  await act(async () => {
    setter.call(el, text)
    el.selectionStart = el.selectionEnd = text.length
    el.dispatchEvent(new win.Event('input', { bubbles: true }) as unknown as Event)
  })
  await settle()
}

await typeAt(area, '推门，@康')
must(!!container.querySelector('.cpick'), '打 @ 应唤出选卡浮层')
must(has('康大叔') && !has('乌鸦'), '浮层应按 @ 后的关键词过滤')
await typeAt(area, '推门，@刽子')
must(has('康大叔'), '按别名也要能搜到——原文里同一个人有多种叫法')

await mouseDown(findByText('button', '康大叔'))
const areaNow = container.querySelector('.ed__at textarea') as unknown as HTMLTextAreaElement
must(areaNow.value === '推门，康大叔', `正文里应落卡名而非 @token，实为「${areaNow.value}」`)
must(!container.querySelector('.cpick'), '选完应收起浮层')
must(has('玄色外褂') || has('青布短打'), '有多套服装的角色挂上后应出现服装下拉')

// ＋挂卡：生物与无状态道具
await click(findByText('button', '＋ 挂卡'))
const attachInput = container.querySelector('.cpick__wrap input') as unknown as HTMLElement
await type(attachInput, '乌鸦', false)
await mouseDown(findByText('button', '乌鸦'))
await click(findByText('button', '＋ 挂卡'))
await type(container.querySelector('.cpick__wrap input') as unknown as HTMLElement, '洋钱', false)
await mouseDown(findByText('button', '一包洋钱'))

// 垫图列表
await click(findByText('button', '垫图'))
await mouseDown(findByText('button', '康大叔'))
must(has('已挂'), '垫图浮层应标出已勾选的卡')
// 分镜视图自己的「保存修改」按钮（#storyboard-save，主按钮的「去修复」也定位到它）
const sbSave = container.querySelector('#storyboard-save') as unknown as HTMLButtonElement
must(!!sbSave && (sbSave.textContent ?? '').includes('保存修改') && !sbSave.disabled, '分镜视图里应有可点的「保存修改」')
const savedBefore15 = saved.length
await click(sbSave)
must(saved.length === savedBefore15 + 1, '点 #storyboard-save 应 PUT 回后端')

const out2 = saved[saved.length - 1] as unknown as typeof DOC
const shot2 = out2.episodes[0].shots[0]
const cref = (id: string) => shot2.characters.find((c) => c.ref === id)
must(shot2.action === '推门，康大叔', '正文应保存为自然语句')
must(cref('C02')?.outfit === 'default', '有服装集的角色必须带上合法 outfit')
must(cref('A01') !== undefined && !('outfit' in cref('A01')!),
     '生物引用不得带 outfit——lint 会直接判错')
must(shot2.prop_refs.some((p) => p.ref === 'P02' && !('state' in p)),
     '无状态集的道具不许填 state')
must(shot2.prompts.reference_assets.includes('C02'), '垫图列表应写进 prompts')
must(cref('C01') !== undefined && shot2.location_ref === 'S01',
     '挂新卡不得动原有引用')
must(JSON.stringify(shot2.source) === JSON.stringify(DOC.episodes[0].shots[0].source),
     '挂卡不得触碰溯源锚点')
console.log('15. 分镜 @ 挂卡 → 引用合规（服装自动选中 / 生物不带 outfit / 无状态道具不填 state）✓')

// 16. 渲染任务包：花钱之前先看清楚提示词、缺几张图、多少钱
await click(findByText('button', '渲染'))
must(has('还没组装'), '未生成时应给出引导而不是空白')
await click(findByText('button', '生成任务包'))
await settle(150)
must(renderCalls.length === 1 && renderCalls[0].seconds === 15,
     '应按默认 15 秒上限请求任务包')
must(has('个 clip') && has('秒成片'), '应摊开 clip 数与成片时长')
must(has('¥4.7–14.2'), '费用必须给区间（一次过 → 抽卡），不能只给最乐观的数')
must(has('张资产图待出'), '缺图数量要显式提示')
must(has('会换脸'), '缺图时必须警告角色一致性会崩——这正是资产引用制要防的')
must(!has('0.0-5.0秒'), '提示词默认收起，先看总账')
await click(findByText('button', '看提示词'))
must(has('0.0-5.0秒：远景，推门。'), '展开后应能逐条核对提示词')

// 改 clip 上限要重新组装（切法变了，费用与 clip 数都会变）
const lenSel = container.querySelector('.rend__len select') as unknown as HTMLSelectElement
await act(async () => {
  const setV = Object.getOwnPropertyDescriptor(
    win.HTMLSelectElement.prototype, 'value')!.set!
  setV.call(lenSel, '5')
  lenSel.dispatchEvent(new win.Event('change', { bubbles: true }) as unknown as Event)
})
await settle(150)
must(renderCalls.length === 2 && renderCalls[1].seconds === 5,
     '改单 clip 上限应重新组装任务包')
// 费用是估算，依据与保留意见必须能摊开——四位数的数字配一行小字不够
must(has('这是估算，点开看依据与不确定性'), '必须明示费用是估算')
must(has('分辨率未建模'), '不确定性要如实列出，不能只给一个数')

const tierSel = [...container.querySelectorAll('.rend__len select')][1] as unknown as HTMLSelectElement
await act(async () => {
  const setV = Object.getOwnPropertyDescriptor(
    win.HTMLSelectElement.prototype, 'value')!.set!
  setV.call(tierSel, 'seedance-2.0-mini')
  tierSel.dispatchEvent(new win.Event('change', { bubbles: true }) as unknown as Event)
})
await settle(150)
must(renderCalls[renderCalls.length - 1].model === 'seedance-2.0-mini',
     '切换费率档位应重新估算')
must(has('¥2.4–7.1'), 'mini 档的费用应随之减半')
// 账必须按「能念完旁白」的实际时长算，否则预算是纸面数字
must(has('含念完旁白必须补的'), '标称时长与可播时长不一致时必须点明')

// 只渲染选中的：唯一真能把钱包住的手段
const boxes = [...container.querySelectorAll('.rclip__pick input')] as unknown as HTMLElement[]
must(boxes.length === 2, '每条 clip 都应可勾选')
await act(async () => boxes[1].click())
await settle(60)
must(has('选中 1/2'), '取消勾选后应显示选中子集')
must(container.querySelectorAll('.rclip.is-off').length === 1, '未选中的 clip 应弱化')
must(has('仅选中的 1/2 条'), '费用应只算选中的部分')
await click(findByText('button', '全选'))
must(!has('选中 1/2'), '全选应恢复')
console.log('16. 渲染任务包 → 按可播时长计价 / 可选范围渲染 / 费用可切档 ✓')

// 17. 服务端验证结果必须在界面上看得见
//     后端每次保存、每次渲染前都整份复验，但界面一直没透出来——用户改出一份
//     不合法的 IR，屏幕照样显示保存成功，要到点渲染才被 422 打回。
// 步骤条上「生成分镜」也含「分镜」二字：按分镜视图的页签精确取
await click([...container.querySelectorAll('.tabs__btn')]
  .find((b) => b.textContent === '分镜') as unknown as HTMLElement)
const area17 = container.querySelector('.ed__at textarea') as unknown as HTMLTextAreaElement
must(!!area17, '切回分镜页应仍在编辑态')
await typeAt(area17, '推门，康大叔（再改）')
nextSaveVerdict = { status: 'draft_invalid', verification: INVALID }
await click(findByText('button', '保存修改'))
await settle(60)
must(has('没通过完整性检查'), '完整性检查不通过必须当场说，不能显示保存成功')
must(has('改动已经存下来了'), '要讲清楚编辑没丢——否则用户不敢改')
must(has('SOURCE-FROZEN-002'), '规则号要露出，便于定位与追问')
must(has('E01 / E01-SH001 · dialogue.0.text'),
     'JSON Pointer 要翻成集号镜号，否则用户找不到是哪一镜')
must(has('1 句原文没有任何镜头承载'), '覆盖率缺口要直说')
must(has('草稿未过验证'), '历史列表也要标出来，否则换个页面回来就看不见了')

blockNextRender = true
await click(findByText('button', '渲染'))
await click(findByText('button', '生成任务包'))
await settle(150)
must(has('已拦在付费渲染之前'), '渲染门拦截要有明确说法')
must(!has('[object Object]'), '结构化 detail 不能退化成 [object Object]')
must(has('台词不是所引原文句的逐字摘录'), '拦截原因要逐条列出')
console.log('17. 验证结果透出 → 保存复验不通过当场可见 / 渲染门给出可执行原因 ✓')

// 17b. 工作流的主按钮也拦在完整性检查：说原因，「去修复」回到 ③ 并定位到检查结果
await goStep('render')
const reason = container.querySelector('[data-testid="primary-reason"]')
must((reason?.textContent ?? '').includes('完整性检查没通过'), '完整性检查不通过时 ④ 的主按钮要说明被完整性检查拦住')
must(primary().disabled, '被拦住时主按钮不能点')
await click(container.querySelector('[data-testid="primary-fix"]') as unknown as HTMLElement)
must(onStep('review'), '「去修复」应回到 ③ 检查修改')
must(!!doc.getElementById('verification'), '③ 里要看得到检查结果（修复定位的目标）')
console.log('17b. 主按钮被完整性检查拦住 → 说明原因 / 去修复回到 ③ ✓')

// 18. 分批先看的两个收尾：预览开着时整章跑完 → 自动换成完整产物（不能被
//     晚到的预览盖回去）；转换失败 → 已通过的批次照样能看
await goStep('storyboard')
await click(primary())
jobs.get('job4')!.partial_batches = 1
await settle(1600)
await click(findByText('button', '先审阅已完成的 1 批'))
must(has('预览：只含已完成的前 1/3 批'), '应打开预览')
finishJob('job4')
await settle(1800)
must(!has('预览：只含'), '整章跑完后预览标记应消失')
must(has('编辑分镜'), '完整产物可以编辑')

await goStep('storyboard')
await click(primary())
jobs.get('job5')!.partial_batches = 2
finishJob('job5', 'failed')
await settle(1800)
must(has('转换失败，但前 2 批已通过校验'), '失败时要告诉用户已通过的批次还在')
await click(findByText('button', '查看已通过的 2 批'))
must(has('预览：只含已完成的前 2/3 批'), '失败后仍能打开已通过批次的预览')
must(has('转换失败，未通过的原因如下'), '失败原因仍要摆在面板上')
console.log('18. 分批先看 → 跑完自动换完整产物 / 失败后已通过批次照样能看 ✓')

// 收尾前等在路上的请求落地，再在 act 里卸载，免得卸载后还有状态更新
await settle(300)
await act(async () => { root.unmount() })
console.log('\nALL PASS')
