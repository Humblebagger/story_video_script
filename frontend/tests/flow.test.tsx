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
                 'Element', 'Node', 'Event', 'CustomEvent', 'getComputedStyle']) {
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

/* ---------- 桩后端：一个可手动结束的转换任务 ---------- */

interface StubJob {
  id: string; status: string; log: string[]; result: unknown
  quality_report: string | null; error: string | null
  created_at: string; work_title: string; chapter: string; chars: number
}

const jobs = new Map<string, StubJob>()
const history: Record<string, unknown>[] = []
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
    history.unshift({ id, created_at: j.created_at, edited_at: null, status,
                      work_title: j.work_title, chapter: j.chapter,
                      units: 1, episodes: 1, shots: 1, has_quality_report: false })
  } else {
    j.error = '批 1 重试 2 次后仍未通过校验\nFAIL: 引用了不存在的资产 C09'
  }
}

g.fetch = async (url: string, init?: { method?: string; body?: string }) => {
  const path = String(url).replace(/^\/api/, '')
  const method = init?.method ?? 'GET'
  const json = (data: unknown) => ({ ok: true, status: 200, json: async () => data })

  if (path === '/healthz') return json({ status: 'ok', model: 'stub', api_key_configured: true })
  if (path === '/assets') return json({ works: [] })
  if (path === '/history') return json({ runs: history })
  if (path.startsWith('/history/') && method === 'PUT') {
    saved.push(JSON.parse(init!.body!))
    return json({ id: path.slice('/history/'.length), edited_at: '2026-08-03T15:00:00+00:00' })
  }
  if (path.startsWith('/history/')) {
    const id = path.slice('/history/'.length)
    return json({ id, created_at: '', edited_at: null, status: 'succeeded',
                  params: {}, quality_report: null, result: DOC })
  }
  if (path === '/jobs') return json({ jobs: [...jobs.values()].map((j) => ({
    id: j.id, status: j.status, created_at: j.created_at, work_title: j.work_title,
    chapter: j.chapter, chars: j.chars, log_lines: j.log.length,
    last_log: j.log[j.log.length - 1] ?? null })) })
  if (path.startsWith('/jobs/')) return json(jobs.get(path.slice('/jobs/'.length)))
  if (path === '/convert' && method === 'POST') {
    const body = JSON.parse(init!.body!)
    const id = `job${++seq}`
    jobs.set(id, { id, status: 'running', log: ['批 1/1（8 字符）：调用 LLM…'],
                   result: null, quality_report: null, error: null,
                   created_at: new Date(0).toISOString(), work_title: body.work_title,
                   chapter: body.chapter, chars: body.text.length })
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

// 1. 空状态：显示转换表单
must(has('小说原文'), '初始应显示转换表单')
console.log('1. 空状态 → 转换表单 ✓')

// 2. 填原文与作品名并提交
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

root.unmount()
console.log('\nALL PASS')
