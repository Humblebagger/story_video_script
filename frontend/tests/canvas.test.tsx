/** 时间轴画布的界面回归：拿《药》的完整产物进画布——全部镜头上轴、角色泳道、播放头推进、
 *  点镜头回分镜页定位、点原文句回溯源页、Esc 关闭。布局计算本身由 timeline.test.ts 覆盖。
 *
 *  跑法：npm test
 */
import { readFileSync } from 'node:fs'
import { Window } from 'happy-dom'

const win = new Window({ url: 'http://localhost:5173' })
const g = globalThis as Record<string, unknown>
for (const k of ['window', 'document', 'navigator', 'location', 'HTMLElement',
                 'Element', 'Node', 'Event', 'CustomEvent', 'KeyboardEvent', 'getComputedStyle',
                 'localStorage', 'sessionStorage', 'PointerEvent', 'MouseEvent', 'matchMedia', 'ResizeObserver',
                 'DOMRect', 'MutationObserver']) {
  Object.defineProperty(g, k, {
    value: (win as unknown as Record<string, unknown>)[k],
    writable: true, configurable: true,
  })
}
g.IS_REACT_ACT_ENVIRONMENT = true
// 播放靠 requestAnimationFrame 推进；测试里用 16ms 定时器代替，时间戳取真实时钟
g.requestAnimationFrame = (cb: (t: number) => void) =>
  setTimeout(() => cb(performance.now()), 16) as unknown as number
g.cancelAnimationFrame = (id: number) => clearTimeout(id)

/* 桩后端：关键帧提示词 + 关键帧图（一开始只有首镜有图） */
const kfImages = new Map<string, string>([['E01-SH001', 'image/png']])
const puts: { shot: string; type: string }[] = []
const outlines: string[] = []
g.fetch = async (url: string, init?: { method?: string; body?: unknown; headers?: Record<string, string> }) => {
  const path = String(url).replace(/^\/api/, '')
  const method = init?.method ?? 'GET'
  const json = (data: unknown) => ({ ok: true, status: 200, json: async () => data })
  if (path === '/render/keyframes') {
    const d = JSON.parse(String(init!.body)).result as Storyboard
    return json({ keyframes: d.episodes.flatMap((e) => e.shots).map((s) => ({
      shot_id: s.id, prompt: `写实，电影静帧\n画面：${s.action}\n场景：某处`, negative_prompt: '血腥',
      reference_assets: (s.characters ?? []).map((c) => c.ref), aspect_ratio: '9:16' })) })
  }
  if (path === '/novels/n1/memory/plot' && method === 'PUT') {
    outlines.push(JSON.parse(String(init!.body)).outline)
    return json({ outline: outlines[outlines.length - 1] })
  }
  // 出片会话：这个版本还没建（画布出片的交互在 film.test.tsx）
  if (path === '/novels/n1/chapters/c1/versions/v1/render/session') {
    return { ok: false, status: 404, statusText: 'Not Found', text: async () => '{"detail":"还没有出片会话"}' }
  }
  const m = path.match(/^\/novels\/n1\/chapters\/c1\/versions\/v1\/keyframes(?:\/(.+))?$/)
  if (!m) throw new Error(`桩后端未实现的路径: ${method} ${path}`)
  if (!m[1]) return json({ shots: [...kfImages.keys()] })
  const shot = decodeURIComponent(m[1])
  if (method === 'PUT') {
    puts.push({ shot, type: init!.headers!['Content-Type'] })
    kfImages.set(shot, init!.headers!['Content-Type'])
    return json({ shot_id: shot, bytes: 4 })
  }
  if (method === 'DELETE') { kfImages.delete(shot); return json({ deleted: shot }) }
  return { ok: true, status: 200, blob: async () => new Blob(['img'], { type: kfImages.get(shot) }) }
}

const { act } = await import('react')
const { createRoot } = await import('react-dom/client')
const { useState } = await import('react')
const { StoryboardView } = await import('../src/components/StoryboardView')
const { buildTimeline, fmtClock } = await import('../src/timeline')
import type { Chapter, Novel, Storyboard } from '../src/types'
import type { Workbench } from '../src/components/CanvasPanels'

const doc: Storyboard = JSON.parse(
  readFileSync('../backend/tests/real_text_yao/output_merged.json', 'utf8'))
const shots = doc.episodes.flatMap((e) => e.shots)

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }
const container = win.document.createElement('div')
win.document.body.appendChild(container)
const root = createRoot(container as unknown as HTMLElement)
const settle = async (ms = 50) => {
  await act(async () => { await new Promise((r) => setTimeout(r, ms)) })
}
const has = (s: string) => container.innerHTML.includes(s)
const button = (text: string) => {
  const b = [...container.querySelectorAll('button')].find((x) => (x.textContent ?? '').includes(text))
  if (!b) throw new Error(`✗ 找不到按钮「${text}」`)
  return b as unknown as HTMLElement
}
/** 播放 / 暂停按钮（图标 + 文字，文字随状态变） */
const play = () => container.querySelector('.tlc__play') as unknown as HTMLElement
const playing = () => play()?.textContent === '暂停'
const paused = () => play()?.textContent === '播放'
const click = async (el: Element) => {
  await act(async () => {
    el.dispatchEvent(new win.MouseEvent('click', { bubbles: true }) as unknown as Event)
  })
  await settle()
}

/** 有状态的宿主：画布里的改动经 onChange 回到这里，和 App 里一样 */
let latest = doc
let saves = 0
/** 章节会话桩：画布「剧情」「任务」两页的上层动作只记下来 */
const calls: string[] = []
const novel = {
  id: 'n1', title: '药', params: {}, created_at: '', updated_at: '',
  chapters: [{ id: 'c1', title: '第一章', adopted_version: 'v0' }],
  memory: { plot: { outline: '', chapters: [] }, constraints: [], lifecycle: [], assets: {},
            numbering: { next_unit: 1, next_episode: 1 } },
} as unknown as Novel
const chapter = {
  id: 'c1', title: '第一章', order: 1, text: '原文', adopted_version: 'v0',
  versions: [{ id: 'v1', status: 'succeeded', shots: 133, created_at: '' },
             { id: 'v0', status: 'succeeded', shots: 120, created_at: '' }],
} as unknown as Chapter
const bench: Workbench = {
  novel, chapter, versionId: 'v1', job: null, converting: false, disabled: false,
  onConvert: (o) => calls.push(`convert:${JSON.stringify(o)}`),
  onOpenVersion: (v) => calls.push(`open:${v}`),
  onAdopt: (v) => calls.push(`adopt:${v}`),
  onDeleteVersion: (v) => calls.push(`delete:${v}`),
  onNovelChanged: () => calls.push('novel'),
  notice: '已采用：资产库新增 3 张',
}
function Host() {
  const [d, setD] = useState(doc)
  const [dirty, setDirty] = useState(false)
  latest = d
  return <StoryboardView doc={d} canSave dirty={dirty} saving={false}
                         version={{ nid: 'n1', cid: 'c1', vid: 'v1' }} bench={bench}
                         onChange={(n) => { setD(n); setDirty(true) }}
                         onSave={() => { saves++; setDirty(false) }} />
}
await act(async () => { root.render(<Host />) })

// 1. 打开画布：全屏、全部镜头上轴、每个角色一条泳道
await click(button('时间轴画布'))
must(!!container.querySelector('.tlc'), '应打开全屏画布')
must(container.querySelectorAll('.tlc__shot').length === shots.length,
     `${shots.length} 个镜头都应上轴`)
const lanes = [...container.querySelectorAll('.tlc__labels text')].map((t) => t.textContent)
must(lanes.includes('集') && lanes.includes('镜头') && lanes.includes('BGM'), '固定泳道齐全')
must(lanes.some((l) => (l ?? '').includes('华老栓')), '每个角色一条泳道')
must(container.querySelectorAll('.tlc__music').length > 0, 'BGM 情绪段铺开')
must(has('0:00 / 12:42'), '时钟按可播时长给总长')
must(has('E01-SH001') && !!container.querySelector('.tlc__shot.is-cur'), '播放头在首镜，浮层展开首镜详情')
console.log(`1. 打开画布 → ${shots.length} 镜上轴 / ${lanes.length} 条泳道 / BGM 情绪段 ✓`)

// 1b. 泳道比一屏高（happy-dom 里画布区高 0）：出竖滚动条，上下滚有底，最后一条停在底部工具条上方
const tyOf = () => Number(/translate\(0, (-?[\d.]+)\)/.exec(
  container.querySelector('.tlc__labels')!.getAttribute('transform') ?? '')?.[1])
must(!!container.querySelector('.tlc__vscroll .tlc__vthumb'), '泳道放不下时应出竖滚动条')
const shiftWheel = (dy: number) => act(async () => {
  const ev = new win.WheelEvent('wheel', { deltaY: dy, bubbles: true })
  Object.defineProperty(ev, 'shiftKey', { value: true }) // happy-dom 的 WheelEvent 不带修饰键
  container.querySelector('.tlc__svg')!.dispatchEvent(ev as unknown as Event)
})
await shiftWheel(100000)
const bottomTy = tyOf()
must(Number.isFinite(bottomTy) && bottomTy < 0, `往下滚应有位移，实为 ${bottomTy}`)
await shiftWheel(100000)
must(tyOf() === bottomTy, '滚到底再滚不再动（不会把泳道滚没）')
await shiftWheel(-100000)
must(tyOf() === 0, '往上滚回到顶')
console.log('1b. 竖滚动条、上下滚到底停住、能回到顶 ✓')

// 2. 播放：播放头推进，经过的镜头与角色节点点亮
const speed = [...container.querySelectorAll('.tlc__speed button')].find((b) => b.textContent === '2×')
must(!!speed, '倍速分段控件里有 2×')
await click(speed!)
await click(play())
await settle(3000)
await click(play())
const clock = container.querySelector('.tlc__clock')!.textContent ?? ''
must(/^0:0[5-7] /.test(clock), `2× 播放约 3 秒，播放头应走到 0:05 左右，实为 ${clock}`)
must(container.querySelectorAll('.tlc__link--lit').length > 0, '经过的连线应点亮')
// 逐镜前进：走到第 4 镜，华老栓已经出场两次，他的动作连线应点亮、节点变实心
for (let i = 0; i < 3; i++) await click(container.querySelector('button[title="下一镜"]')!)
must(container.querySelector('.tlc__shot.is-cur title')?.textContent?.startsWith(shots[3].id) === true,
     '逐镜前进应停在第 4 镜')
must(container.querySelectorAll('.tlc__node.is-past').length >= 2, '经过的角色节点应点亮')
must(container.querySelectorAll('.tlc__char .tlc__link--lit').length >= 1, '角色动作连线应点亮')
must(has(shots[3].id) && has(shots[3].action.slice(0, 8)), '浮层应换成当前镜的详情')
console.log(`2. 播放 / 暂停 → 播放头推进（${clock.split(' ')[0]}）/ 逐镜前进 / 镜头与角色连线逐段点亮 ✓`)

// 3. 点镜头：就地选中（不离开画布）；要去分镜页走浮层里的按钮
const target = shots[5].id
await click(container.querySelectorAll('.tlc__shot')[5])
must(!!container.querySelector('.tlc'), '点镜头不应离开画布')
must(container.querySelector('.tlc__panel header b')?.textContent === target, '点镜头应选中它，浮层换成这一镜')
await click(button('在分镜页打开这一镜'))
must(!container.querySelector('.tlc'), '「在分镜页打开」应关闭画布')
must(!!win.document.getElementById(`shot-${target}`), '分镜页应有该镜头的锚点')
must(win.document.getElementById(`shot-${target}`)!.classList.contains('is-flash'), '定位的镜头要闪一下')
console.log(`3. 点镜头 → 就地选中 / 按钮回分镜页定位 ${target} ✓`)

// 4. 点浮层里的原文句：在侧栏「原文」页定位，不离开画布；点句子下的镜头号回到那一镜
await click(button('时间轴画布'))
const unit = container.querySelector('.tlc__unit') as unknown as HTMLElement
must(!!unit, '浮层应列出本镜引用的原文句')
const unitId = unit.querySelector('code')!.textContent
await click(unit)
must(!!container.querySelector('.tlc') && !!container.querySelector('.tlc__panel .src'),
     '点原文句在侧栏「原文」页打开，不离开画布')
must(container.querySelector('.tlc__panel .unit--focus .unit__id')?.textContent === unitId, '定位到点的那一句')
const uref = container.querySelector('.tlc__panel .unit--focus button.uref') as unknown as HTMLElement
must(!!uref, '句子下的镜头号在画布里可点')
const back = uref.textContent
await click(uref)
must(container.querySelector('.tlc__panel > header b')?.textContent === back, '点镜头号回到「本镜」并选中那一镜')
await act(async () => {
  win.dispatchEvent(new win.KeyboardEvent('keydown', { key: 'Escape' }) as unknown as Event)
})
await settle()
console.log('4. 点原文句 → 画布侧栏「原文」页定位 / 点镜头号回本镜 ✓')

// 5. 静帧预演：已上传的关键帧按播放头显示；没图的镜头给提示词占位；上传 / 删除；导出提示词
await click(button('时间轴画布'))
await settle(120)
must(has('关键帧 1/133'), '应读出已上传的关键帧数')
must(!!container.querySelector('.tlc__frame img'), '首镜有图：预演画面显示关键帧图')
must(container.querySelectorAll('.tlc__kfdot').length === 1, '有图的镜头在轴上打点')
must(container.querySelectorAll('.tlc__thumb image').length === 1 && has('画面'),
     '画布上有「画面」泳道，已上传的关键帧直接铺在对应镜头下')
await click(container.querySelector('button[title="下一镜"]')!)
must(has('还没有关键帧图') && !container.querySelector('.tlc__frame p'), '没图的镜头只给一条占位，画面框里不塞提示词')
const pa = () => container.querySelector('textarea.tlc__prompt') as unknown as HTMLTextAreaElement
must(!!pa() && pa().value.length > 0 && has('负面：血腥'), '提示词放在关键帧一节里，直接可见')
must(!has('恢复生成的提示词'), '没改过不出现恢复按钮')
await act(async () => {
  Object.getOwnPropertyDescriptor(win.HTMLTextAreaElement.prototype, 'value')!.set!.call(pa(), '手改的出图提示词')
  pa().dispatchEvent(new win.Event('input', { bubbles: true }) as unknown as Event)
})
await settle()
must(pa().value === '手改的出图提示词' && has('恢复生成的提示词'), '提示词可以就地改')
await click(button('恢复生成的提示词'))
must(pa().value !== '手改的出图提示词' && !has('恢复生成的提示词'), '可以恢复成生成的原文')
const file = new File([new Uint8Array([1, 2, 3, 4])], 'kf.webp', { type: 'image/webp' })
const input = container.querySelector('.tlc__kf input[type="file"]') as unknown as HTMLInputElement
must(!!input, '存进版本的产物可以上传关键帧')
await act(async () => {
  Object.defineProperty(input, 'files', { value: [file], configurable: true })
  input.dispatchEvent(new win.Event('change', { bubbles: true }) as unknown as Event)
})
await settle(80)
must(puts.length === 1 && puts[0].shot === shots[1].id && puts[0].type === 'image/webp',
     '上传应按镜头 PUT 原始图片，带上图片类型')
must(has('关键帧 2/133') && !!container.querySelector('.tlc__frame img'), '上传后预演立刻换成这张图')
must(container.querySelectorAll('.tlc__thumb image').length === 2, '上传后画面泳道立刻多一张')
await click(button('删除'))
must(has('关键帧 1/133') && has('还没有关键帧图'), '删除后回到占位')
must(!(button('下载全章提示词') as HTMLButtonElement).disabled, '提示词清单可导出')
await click(button('预演'))
must(!container.querySelector('.tlc__frame'), '预演画面可以收起')
console.log('5. 静帧预演 → 显示已上传关键帧 / 无图只占一条 / 提示词就地改与恢复 / 上传 / 删除 / 导出 ✓')

// 6. 画布上就地编辑：拖右缘改时长、双击角色节点改动作、右侧改本镜呈现字段；撤销重做；保存
const ptr = (type: string, clientX: number) =>
  new win.PointerEvent(type, { bubbles: true, clientX, clientY: 100, pointerId: 1 }) as unknown as Event
// 分镜页顶栏也有「编辑分镜」，按钮要在画布的编辑条里找
const editBtn = () => container.querySelector('.tlc__editbar button') as unknown as HTMLElement
must(editBtn().textContent === '编辑' && !!container.querySelector('.tlc__grip'), '不进编辑态也能拖右缘改时长')
must(![...container.querySelectorAll('button')].some((b) => b.textContent?.includes('撤销')), '没改过不出现撤销')
const s2 = shots[1]
const start = buildTimeline(doc).shots[1].start
const grip = container.querySelector(`.tlc__grip[data-shot="${s2.id}"]`)!
// 画布宽度在 happy-dom 里是 0，适应时取下限每秒 0.3px、无平移：横坐标 = 泳道名栏 132 + 秒 × 0.3
await act(async () => { grip.dispatchEvent(ptr('pointerdown', 132 + (start + s2.duration_sec) * 0.3)) })
await act(async () => { grip.dispatchEvent(ptr('pointermove', 132 + (start + 6.2) * 0.3)) })
await act(async () => { grip.dispatchEvent(ptr('pointerup', 132 + (start + 6.2) * 0.3)) })
await settle()
const dur = () => latest.episodes[0].shots[1].duration_sec
must(dur() === 6, `拖右缘应把时长改成 6s（取 0.5s），实为 ${dur()}`)
must(has('保存修改'), '画布上的改动要让保存按钮亮起')
await click(button('撤销'))
must(dur() === s2.duration_sec, '撤销应恢复原时长')
await click(button('重做'))
must(dur() === 6, '重做应回到 6s')
await act(async () => {
  win.dispatchEvent(new win.KeyboardEvent('keydown', { key: 'z', metaKey: true }) as unknown as Event)
})
await settle()
must(dur() === s2.duration_sec, '⌘Z 撤销')
await click(editBtn())
must(editBtn().textContent === '完成编辑', '进入编辑态（改角色动作、右侧表单）')

const node = container.querySelector(`[data-node="C01@${s2.id}"]`)!
await act(async () => { node.dispatchEvent(new win.MouseEvent('dblclick', { bubbles: true }) as unknown as Event) })
await settle()
const ne = container.querySelector('.tlc__nodeedit') as unknown as HTMLInputElement
must(!!ne, '双击角色节点应出现就地输入框')
await act(async () => {
  Object.getOwnPropertyDescriptor(win.HTMLInputElement.prototype, 'value')!.set!.call(ne, '惊坐而起')
  ne.dispatchEvent(new win.Event('input', { bubbles: true }) as unknown as Event)
})
await act(async () => {
  ne.dispatchEvent(new win.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }) as unknown as Event)
})
await settle()
must(latest.episodes[0].shots[1].characters!.find((c) => c.ref === 'C01')!.action === '惊坐而起',
     '回车应写回该角色本镜的动作')
must(!container.querySelector('.tlc__nodeedit'), '写回后收起输入框')

await click(container.querySelectorAll('.tlc__shot')[0])
const area = container.querySelector('.tlc__panel .ed__at textarea') as unknown as HTMLTextAreaElement
must(!!area, '编辑态下右侧是本镜的编辑表单（与分镜页同一套，锁死规则沿用）')
must(!!container.querySelector('.tlc__panel .lock'), '锁死字段照样标出（锁形图标）')
await act(async () => {
  Object.getOwnPropertyDescriptor(win.HTMLTextAreaElement.prototype, 'value')!.set!.call(area, '画布上改的画面')
  area.dispatchEvent(new win.Event('input', { bubbles: true }) as unknown as Event)
})
await act(async () => {
  area.dispatchEvent(new win.KeyboardEvent('keydown', { key: ' ', bubbles: true }) as unknown as Event)
})
await settle()
must(latest.episodes[0].shots[0].action === '画布上改的画面', '右侧表单的改动应写回产物')
must(paused(), '在输入框里敲空格不能触发播放')
must(JSON.stringify(latest.episodes[0].shots[0].source) === JSON.stringify(shots[0].source),
     '溯源锚点不受画布编辑影响')
await click(button('保存修改'))
must(saves === 1 && has('已保存'), '画布里直接保存，不必退回分镜页')
await click(editBtn())
must(!container.querySelector('.tlc__panel .ed__at textarea'), '完成编辑后右侧回到只读详情')
console.log('6. 画布上就地编辑 → 拖右缘改时长 / 双击节点改动作 / 右侧改本镜 / 撤销重做（含 ⌘Z）/ 直接保存 ✓')

// 6b. 侧栏其余页签：资产卡（编辑态可改，进同一套撤销）/ 剧情（小说长期记忆）/ 任务（重新生成、版本）
const tab = (name: string) => [...container.querySelectorAll('.tlc__tabs button')]
  .find((b) => b.textContent === name) as unknown as HTMLElement
must(!!tab('资产') && !!tab('剧情') && !!tab('任务'), '有章节会话时侧栏有 资产 / 剧情 / 任务 页')
await click(editBtn())
await click(tab('资产'))
const aliasInput = container.querySelector('.tlc__panel .assets input[placeholder="以顿号分隔"]') as unknown as HTMLInputElement
must(!!aliasInput, '编辑态下资产卡可以直接改')
await act(async () => {
  Object.getOwnPropertyDescriptor(win.HTMLInputElement.prototype, 'value')!.set!.call(aliasInput, '画布别名')
  aliasInput.dispatchEvent(new win.Event('input', { bubbles: true }) as unknown as Event)
})
await settle()
const firstChar = () => Object.values(latest.assets?.characters ?? {})[0] as { aliases?: string[] } | undefined
must(JSON.stringify(firstChar()?.aliases) === '["画布别名"]', `资产卡改动写回产物，实为 ${JSON.stringify(firstChar()?.aliases)}`)
await click(button('撤销'))
must(JSON.stringify(firstChar()?.aliases) !== '["画布别名"]', '资产卡改动和镜头改动共用撤销')
await click(editBtn())

await click(tab('剧情'))
must(has('全书梗概') && !!container.querySelector('.tlc__panel .plot'), '剧情页复用小说页的主线剧情')
const outline = container.querySelector('.tlc__panel .plot textarea') as unknown as HTMLTextAreaElement
await act(async () => {
  Object.getOwnPropertyDescriptor(win.HTMLTextAreaElement.prototype, 'value')!.set!.call(outline, '华家父子的结局')
  outline.dispatchEvent(new win.Event('input', { bubbles: true }) as unknown as Event)
})
await click(button('保存梗概'))
must(outlines[0] === '华家父子的结局' && calls.includes('novel'), '在画布里改梗概直接存进小说长期记忆')
await click(button('创作限制'))
must(!!container.querySelector('.tlc__panel .cons'), '剧情页可切到创作限制')

await click(tab('任务'))
must(has('已采用：资产库新增 3 张'), '上层的提示在画布里也看得到')
// 撤销过的资产改动让本版仍算「未保存」：转换前要确认（会被新版本换掉）
const confirmDialog = () => win.document.body.querySelector('[data-testid="confirm-dialog"]')
async function answer(ok: boolean) {
  const btn = win.document.body.querySelector<HTMLElement>(`[data-testid="${ok ? 'confirm-ok' : 'confirm-cancel'}"]`)
  must(!!btn, '应弹出确认框')
  await click(btn!)
}
await click(button('重新生成（新版本）'))
must((confirmDialog()?.textContent ?? '').includes('先不保存直接生成'), '有未保存修改时先确认')
must(!calls.some((c) => c.startsWith('convert:')), '确认前不发起重新生成')
await answer(true)
must(calls.some((c) => c.startsWith('convert:')), '确认后在画布里发起重新生成')
const chips = [...container.querySelectorAll('.tlc__vers .vchip')] as unknown as HTMLButtonElement[]
must(chips.length === 2 && chips[1].disabled && chips[0].textContent!.includes('★'), '版本条：v1 采用版、v2 正在看')
await click(chips[0])
must(calls.includes('open:v0'), '在画布里切版本')
must((button('采用此版') as HTMLButtonElement).disabled, '有未保存修改时不能采用（采用的是存下来的那份）')
await click(button('保存修改'))
await click(button('采用此版'))
must(calls.includes('adopt:v1'), '保存后在画布里采用正在看的版本')
await click(container.querySelectorAll('.tlc__shot')[2])
must(!!container.querySelector('.tlc__panel > header'), '在别的页签时点镜头回到「本镜」')
console.log('6b. 侧栏页签 → 资产卡就地改（共用撤销）/ 剧情与限制 / 重新生成、切版本、采用 ✓')

// 6c. 选区与空格预览：Shift+点镜头圈选区，Esc 先清选区；空格只播当前这一镜，播到镜尾停，再按从镜首重播
const tlNow = () => buildTimeline(latest)
const shotEls = () => container.querySelectorAll('.tlc__shot')
await click(shotEls()[1])
await act(async () => {
  shotEls()[3].dispatchEvent(new win.MouseEvent('click', { bubbles: true, shiftKey: true }) as unknown as Event)
})
await settle()
const span = { start: tlNow().shots[1].start, end: tlNow().shots[3].end }
must(!!container.querySelector('.tlc__rangeband') && has(`选区 ${fmtClock(span.start)}–${fmtClock(span.end)}`),
     'Shift+点镜头：从当前镜圈到那一镜')
const esc = async () => {
  await act(async () => { win.dispatchEvent(new win.KeyboardEvent('keydown', { key: 'Escape' }) as unknown as Event) })
  await settle()
}
await esc()
must(!container.querySelector('.tlc__rangeband') && !!container.querySelector('.tlc'), 'Esc 先清选区，不关画布')
// 在时间刻度上拖：圈出一段
const svg = container.querySelector('.tlc__svg')!
const rptr = (type: string, sec: number) =>
  new win.PointerEvent(type, { bubbles: true, clientX: 132 + sec * 0.3, clientY: 10, pointerId: 1 }) as unknown as Event
await act(async () => { svg.dispatchEvent(rptr('pointerdown', 300)) })
await act(async () => { svg.dispatchEvent(rptr('pointermove', 400)) })
await act(async () => { svg.dispatchEvent(rptr('pointerup', 400)) })
await settle()
must(!!container.querySelector('.tlc__rangeband') && /^5:0\d /.test(container.querySelector('.tlc__clock')!.textContent ?? ''),
     '在刻度上拖出选区，播放头跳到选区起点')
await act(async () => { svg.dispatchEvent(rptr('pointerdown', 500)) })
await act(async () => { svg.dispatchEvent(rptr('pointerup', 500)) })
await settle()
must(!container.querySelector('.tlc__rangeband'), '刻度上只点一下：清选区并跳过去')
// 挑一个短镜头，空格预览它
const shortest = tlNow().shots.reduce((a, b) => (b.playable < a.playable ? b : a))
await click(shotEls()[shortest.index])
await click(button('预演'))          // 第 5 步收起了预演；预览窗跟着「预演」开关
const space = async () => {
  await act(async () => { win.dispatchEvent(new win.KeyboardEvent('keydown', { key: ' ' }) as unknown as Event) })
}
await space()
await settle(60)
must(playing() && !!container.querySelector('.tlc__pip'), '空格开始预览，出现预览窗')
await settle(shortest.playable * 1000 + 400)   // 画布重开过，速度回到 1×
must(paused() && !container.querySelector('.tlc__pip'), `只播这一镜（${shortest.playable.toFixed(1)}s），播到镜尾自己停`)
must(container.querySelector('.tlc__panel > header b')?.textContent === shortest.id, '停下后仍停在这一镜，不跳到下一镜')
await space()
await settle(60)
const clk = container.querySelector('.tlc__clock')!.textContent ?? ''
must(clk.startsWith(fmtClock(shortest.start)), `再按空格从镜首重播，实为 ${clk}`)
await space()
console.log('6c. 选区（Shift+点 / 刻度上拖 / Esc 清）/ 空格只播当前镜、镜尾自停、再按重播 / 预览窗 ✓')

// 7. Esc 关闭
await act(async () => {
  win.dispatchEvent(new win.KeyboardEvent('keydown', { key: 'Escape' }) as unknown as Event)
})
await settle()
must(!container.querySelector('.tlc'), 'Esc 应关闭画布')
console.log('7. Esc 关闭 ✓')

await act(async () => { root.unmount() })
console.log('\nALL PASS')
