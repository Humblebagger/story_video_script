/** 交互流程回归：在真实 DOM（happy-dom）里驱动 App，用桩后端替代真实转换。
 *
 *  重点守的是「放到后台还能不能回来」——这条路径一旦断掉，
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
                 'localStorage', 'sessionStorage']) {
  Object.defineProperty(g, k, {
    value: (win as unknown as Record<string, unknown>)[k],
    writable: true, configurable: true,
  })
}
g.IS_REACT_ACT_ENVIRONMENT = true

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
g.confirm = () => true

// localStorage：happy-dom 提供，但要确保 App 启动时是干净的未登录态
win.localStorage.clear()

/* ---------- 桩后端：一个可手动结束的转换任务 ---------- */

interface StubJob {
  id: string; status: string; log: string[]; result: unknown
  quality_report: string | null; error: string | null
  created_at: string; work_title: string; chapter: string; chars: number
  user_id: string
}

const jobs = new Map<string, StubJob>()
const histories = new Map<string, Record<string, unknown>[]>()
const hist = (u: string) => {
  if (!histories.has(u)) histories.set(u, [])
  return histories.get(u)!
}
const users = new Map<string, string>()
const libs = new Map<string, Map<string, Record<string, { id: string }[]>>>()

const user = (name: string) => ({ id: name, username: name, created_at: '' })
const auth = (init?: { headers?: Record<string, string> }) => {
  const h = (init?.headers ?? {}).Authorization ?? ''
  return h.startsWith('Bearer tok-') && users.has(h.slice(11)) ? h.slice(11) : null
}
const lib = (u: string, work: string) => {
  const m = libs.get(u) ?? new Map()
  libs.set(u, m)
  if (!m.has(work)) m.set(work, {})
  return m.get(work)!
}
const counts = (w: Record<string, { id: string }[]>) => Object.fromEntries(
  ['characters', 'locations', 'props', 'creatures'].map((k) => [k, (w[k] ?? []).length]))
const libWorks = (u: string) => [...(libs.get(u) ?? new Map()).entries()]
  .map(([t, w]) => ({ work_title: t, updated_at: '', counts: counts(w) }))
/** 前端 PUT 回来的编辑结果，用于校验编辑没有破坏跨引用 */
const saved: Record<string, never>[] = []
let seq = 0

const DOC = {
  meta: { schema_version: '0.4', title: '药', fidelity_mode: 'faithful',
          style: { style_prefix: '写实' }, video: { aspect_ratio: '9:16' },
          narration: { mode: 'selective' } },
  source: { work_title: '药', chapter: '第一章',
            units: [{ id: 'u0001', text: '他推门。', kind: 'action' }] },
  assets: {
    characters: [{ id: 'C01', name: '华老栓', aliases: ['老栓'],
                   appearance: { age: '五十余岁', face: '瘦削' },
                   outfits: [{ id: 'default', name: '旧棉袄', visual_prompt: '灰布' }],
                   visual_prompt: '驼背老者' }],
    locations: [{ id: 'S01', name: '茶馆', interior_exterior: 'interior' }],
    props: [{ id: 'P01', name: '灯笼',
              states: [{ id: 'lit', name: '点亮' }, { id: 'dark', name: '熄灭' }] }],
  },
  episodes: [{ id: 'E01', title: '开端', shots: [{
    id: 'E01-SH001', duration_sec: 5, shot_size: 'wide', action: '推门',
    location_ref: 'S01',
    characters: [{ ref: 'C01', outfit: 'default', expression: '疲惫' }],
    prop_refs: [{ ref: 'P01', state: 'lit' }],
    source: { unit_refs: ['u0001'], derivation: 'explicit' } }] }],
}

function finishJob(id: string, status = 'succeeded') {
  const j = jobs.get(id)!
  j.status = status
  j.log.push('批 1 校验通过（第 1 次生成）')
  if (status === 'succeeded') {
    j.result = DOC
    hist(j.user_id).unshift({ id, created_at: j.created_at, edited_at: null, status,
                              work_title: j.work_title, chapter: j.chapter,
                              units: 1, episodes: 1, shots: 1, has_quality_report: false })
  } else {
    j.error = '批 1 重试 2 次后仍未通过校验\nFAIL: 引用了不存在的资产 C09'
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
  const err = (status: number, detail: string) => ({
    ok: false, status, text: async () => JSON.stringify({ detail }),
    json: async () => ({ detail }) })

  if (path === '/healthz') return json({ status: 'ok', model: 'stub',
                                         api_key_configured: true, users: users.size })

  // 认证：注册/登录发 token，其余接口一律要带 token
  if (path === '/auth/register' && method === 'POST') {
    const b = JSON.parse(init!.body!)
    if (users.has(b.username)) return err(400, '用户名已被占用')
    if ((b.password ?? '').length < 6) return err(400, '密码至少 6 位')
    users.set(b.username, b.password)
    return json({ token: `tok-${b.username}`, user: user(b.username) })
  }
  if (path === '/auth/login' && method === 'POST') {
    const b = JSON.parse(init!.body!)
    if (users.get(b.username) !== b.password) return err(401, '用户名或密码不正确')
    return json({ token: `tok-${b.username}`, user: user(b.username) })
  }
  const who = auth(init)
  if (!who) return { ok: false, status: 401, text: async () => '{"detail":"未登录"}',
                     json: async () => ({ detail: '未登录' }) }
  if (path === '/auth/me') return json(user(who))

  if (path === '/library') return json({ works: libWorks(who) })
  if (path.startsWith('/library/')) {
    const seg = path.slice('/library/'.length).split('/').map(decodeURIComponent)
    const work = seg[0]
    if (method === 'PUT' && seg.length === 3) {
      const card = JSON.parse(init!.body!)
      const w = lib(who, work)
      const lst = (w[seg[1]] ??= [])
      const i = lst.findIndex((c: { id: string }) => c.id === card.id)
      if (i >= 0) lst[i] = card; else lst.push(card)
      return json(card)
    }
    if (method === 'DELETE' && seg.length === 3) {
      const w = lib(who, work)
      w[seg[1]] = (w[seg[1]] ?? []).filter((c: { id: string }) => c.id !== seg[2])
      return json({ deleted: seg[2] })
    }
    if (method === 'POST' && seg.length === 1) {
      if (libs.get(who)?.has(work)) return err(409, '已在资产库中')
      lib(who, work)
      return json({ work_title: work, created: true })
    }
    if (method === 'DELETE') { libs.get(who)?.delete(work); return json({ deleted: work }) }
    if (!libs.get(who)?.has(work)) return err(404, '资产库里没有这部作品')
    return json({ work_title: work, updated_at: '', counts: counts(lib(who, work)),
                  assets: lib(who, work) })
  }
  if (path === '/history') return json({ runs: hist(who) })
  if (path.startsWith('/history/') && method === 'PUT') {
    saved.push(JSON.parse(init!.body!))
    return json({ id: path.slice('/history/'.length), edited_at: '2026-08-03T15:00:00+00:00' })
  }
  if (path.startsWith('/history/')) {
    const id = path.slice('/history/'.length)
    return json({ id, created_at: '', edited_at: null, status: 'succeeded',
                  params: {}, quality_report: null, result: DOC })
  }
  if (path === '/jobs') return json({ jobs: [...jobs.values()].filter((j) => j.user_id === who).map((j) => ({
    id: j.id, status: j.status, created_at: j.created_at, work_title: j.work_title,
    chapter: j.chapter, chars: j.chars, log_lines: j.log.length,
    last_log: j.log[j.log.length - 1] ?? null })) })
  if (path.startsWith('/jobs/')) {
    const j = jobs.get(path.slice('/jobs/'.length))
    return j && j.user_id === who ? json(j) : err(404, 'job 不存在')
  }
  if (path === '/convert' && method === 'POST') {
    const body = JSON.parse(init!.body!)
    const id = `job${++seq}`
    jobs.set(id, { id, status: 'running', log: ['批 1/1（8 字符）：调用 LLM…'],
                   result: null, quality_report: null, error: null,
                   created_at: new Date(0).toISOString(), work_title: body.work_title,
                   chapter: body.chapter, chars: body.text.length, user_id: who })
    return json({ job_id: id, status_url: `/jobs/${id}` })
  }
  throw new Error(`桩后端未实现的路径: ${method} ${path}`)
}

/* ---------- 驱动 ---------- */

const { act } = await import('react')
const { createRoot } = await import('react-dom/client')
const { default: App } = await import('../src/App')

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

await act(async () => { root.render(<App />) })
await settle()

// 0. 未登录：只能看到登录页，看不到任何业务界面
must(has('登录') && !has('小说原文'), '未登录时不应显示转换界面')
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
must(has('小说原文'), '注册后应进入转换界面')
must(has('alice'), '顶栏应显示当前用户')
console.log('0. 未登录挡在门外 / 密码二次确认 → 注册后进入 ✓')

// 1-2. 填原文与作品名并提交
const ta = container.querySelector('textarea') as unknown as HTMLTextAreaElement
await type(ta, '他推门。走进屋里。')
const titleInput = findByText('label', '作品名')
  .querySelector('input') as unknown as HTMLElement
await type(titleInput, '药', false)
await click(findByText('button', '开始转换'))
must(has('放到后台，去开新转换'), '提交后应显示任务面板')
must(jobs.size === 1, '桩后端应收到一个转换任务')
console.log('2. 提交 → 任务面板（转换中）✓')

// 3. 放到后台：必须回到表单，且任务仍留在侧栏里可见
await click(findByText('button', '放到后台，去开新转换'))
must(has('小说原文'), '放到后台后应回到表单')
must(!has('放到后台，去开新转换'), '放到后台后不应还停在任务面板')
must(has('批 1/1（8 字符）：调用 LLM…'), '侧栏必须留着在跑的任务及其最新日志')
console.log('3. 放到后台 → 回到表单，任务留在侧栏 ✓')

// 4. 点侧栏的在跑任务：必须能回到任务面板（用户报的就是这一步回不去）
await click(findByText('li', '批 1/1（8 字符）：调用 LLM…'))
must(has('放到后台，去开新转换'), '点侧栏在跑任务应能回到任务面板')
console.log('4. 点侧栏 → 回到任务面板 ✓')

// 5. 再放后台，让它在「没人看着」的情况下跑完：应弹通知并进历史
await click(findByText('button', '放到后台，去开新转换'))
finishJob('job1')
await settle(3600)          // 等一次巡检（在跑时 3s 一轮）
must(notifications.some((n) => n.title === '转换完成'), '后台跑完必须弹桌面通知')
must(!has('批 1/1（8 字符）：调用 LLM…'), '跑完后不应还挂在「在跑」列表里')
console.log('5. 后台跑完 → 桌面通知 ✓（共', notifications.length, '条）')

// 6. 从历史点开产物
await click(findByText('li', '药'))
must(has('E01-SH001') && has('推门'), '应能从历史打开分镜产物')
must(has('编辑分镜') && has('下载 JSON'), '产物应带编辑与下载入口')
// 角色名只在资产卡页签出现（镜头层只写引用），顺带验一下页签切换
await click(findByText('button', '资产卡'))
must(has('华老栓') && has('C01'), '资产卡页签应展示角色卡')
console.log('6. 历史 → 打开产物 + 页签切换 ✓')

// 7. 失败任务：原因要摊在面板上
await click(findByText('button', '＋ 新转换'))
await type(container.querySelector('textarea') as unknown as HTMLTextAreaElement, '另一段原文。')
await click(findByText('button', '开始转换'))
finishJob('job2', 'failed')
await settle(1800)          // 附着轮询 1.5s 一轮
must(has('转换失败，未通过的原因如下'), '失败应高亮原因区块')
must(has('不存在的资产 C09'), '失败的具体原因必须显示给用户')
console.log('7. 失败 → 原因摊开显示 ✓')

// 8. 资产卡编辑：改得动内容，但跨引用的 ID 一个都不能变
await click(findByText('button', '＋ 新转换'))
await click(findByText('li', '药'))
await click(findByText('button', '编辑分镜'))
await click(findByText('button', '资产卡'))

must(has('🔒'), '编辑态下应标出锁死的 ID')
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

// 9. 保存并核对：内容改了，ID 与镜头引用逐字未变
await click(findByText('button', '保存修改'))
must(saved.length === 1, '编辑后应 PUT 回后端')
const out = saved[0] as unknown as typeof DOC
const c0 = out.assets.characters[0]
must(c0.name === '华老栓（改）', '角色名应已更新')
must(c0.appearance!['age'] === '六十岁上下', '外貌字段应已更新')
must(c0.id === 'C01', '资产 ID 必须保持 C01')
must(c0.outfits![0].id === 'default', '服装 ID 必须保持 default')
must(out.assets.props[0].states.map((s) => s.id).join() === 'lit,dark', '状态 ID 必须原样')
const sh = out.episodes[0].shots[0]
must(sh.location_ref === 'S01' && sh.characters[0].ref === 'C01'
     && sh.characters[0].outfit === 'default' && sh.prop_refs[0].ref === 'P01'
     && sh.prop_refs[0].state === 'lit', '镜头层的跨引用必须逐字未变')
must(JSON.stringify(out.source.units) === JSON.stringify(DOC.source.units), '原文 units 不得变动')
console.log('9. 保存 → 内容已改 / ID 与跨引用逐字未变 ✓')

// 10. 资产库管理页：新建 / 编辑 / 删除（聚合视图做不到的三件事）
lib('alice', '药').characters = [{ id: 'C01', name: '华老栓' }]
await click(findByText('button', '资产库'))
await settle(120)
must(has('华老栓') && has('C01'), '资产库应列出已有卡片')

const addName = container.querySelector('.lib__add input') as unknown as HTMLElement
await type(addName, '康大叔', false)
await click(findByText('button', '＋ 新建'))
must(lib('alice', '药').characters.some((c) => c.id === 'C02'), '新建卡应写回后端并自动续号')
must(has('康大叔'), '新建的卡应出现在页面上')
console.log('10. 资产库 → 新建卡片（ID 自动续号 C02）✓')

// 编辑已有卡并保存
const nameInputs = [...container.querySelectorAll('.acard header input')] as unknown as HTMLElement[]
await type(nameInputs[0], '华老栓（库中改名）', false)
await click(findByText('button', '保存修改'))
must(lib('alice', '药').characters[0].name === '华老栓（库中改名）', '编辑应 PUT 回后端')
console.log('11. 资产库 → 编辑并保存 ✓')

// 12. 换个账号：看不到 alice 的任何东西
await click(findByText('button', '退出'))
// 注意：登录页文案里本就含「资产库」三字，故以业务界面元素判断是否已登出
must(has('login__tab') && !has('小说原文') && !has('新卡名称'), '退出后应回到登录页')
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
await settle(120)
must(has('bob') && !has('alice'), '顶栏应换成新用户')
must(!has('药') && !has('华老栓'), 'bob 不该看到 alice 的历史记录')
await click(findByText('button', '资产库'))
await settle(120)
must(!has('华老栓') && !has('康大叔'), 'bob 不该看到 alice 的资产库')
must(has('资产库还是空的'), 'bob 的资产库应为空')
console.log('12. 换账号 → 历史与资产库完全隔离 ✓')


// 13. 空库也要能从零建作品——「先设定人物场景再去转换」是常见用法
await click(findByText('button', '资产库'))
await settle(120)
must(has('资产库还是空的'), 'bob 的资产库应为空')
const workInput = container.querySelector('.lib__newwork input') as unknown as HTMLElement
must(!!workInput, '资产库为空时也必须有新建作品的入口')
await type(workInput, '鲍勃的新书', false)
await click(findByText('button', '＋ 建作品'))
await settle(120)
must(libs.get('bob')?.has('鲍勃的新书') === true, '新建作品应写回后端')
must(has('新卡名称'), '建完作品应能直接新建卡片')

const cardInput = container.querySelector('.lib__add input') as unknown as HTMLElement
for (const n of ['赵老三', '钱掌柜']) {
  await type(cardInput, n, false)
  await click(findByText('button', '＋ 新建'))
  await settle(60)
}
must(lib('bob', '鲍勃的新书').characters.length === 2, '应建出两张角色卡')
console.log('13. 空库 → 从零建作品 + 建卡片 ✓')

// 14. 资产库搜索：按名称过滤，跨类别
const search = container.querySelector('.lib__search') as unknown as HTMLElement
await type(search, '赵老三', false)
must(has('匹配') && has('赵老三') && !has('钱掌柜'), '搜索应只留下命中的卡')
await type(search, '不存在的名字', false)
must(has('换个关键词试试'), '无命中时应给出提示')
await type(search, '', false)
must(has('赵老三') && has('钱掌柜'), '清空搜索应恢复全部')
console.log('14. 资产库搜索 → 按名称跨类别过滤 ✓')

root.unmount()
console.log('\nALL PASS')
