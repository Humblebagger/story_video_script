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
                 'localStorage', 'sessionStorage']) {
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

const { act } = await import('react')
const { createRoot } = await import('react-dom/client')
const { StoryboardView } = await import('../src/components/StoryboardView')
import type { Storyboard } from '../src/types'

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
const click = async (el: Element) => {
  await act(async () => {
    el.dispatchEvent(new win.MouseEvent('click', { bubbles: true }) as unknown as Event)
  })
  await settle()
}

await act(async () => {
  root.render(<StoryboardView doc={doc} canSave={false} dirty={false} saving={false}
                              onChange={() => {}} onSave={() => {}} />)
})

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

// 2. 播放：播放头推进，经过的镜头与角色节点点亮
const speed = container.querySelector('.tlc__bar select') as unknown as HTMLSelectElement
await act(async () => {
  Object.getOwnPropertyDescriptor(win.HTMLSelectElement.prototype, 'value')!.set!.call(speed, '2')
  speed.dispatchEvent(new win.Event('change', { bubbles: true }) as unknown as Event)
})
await click(button('▶ 播放'))
await settle(3000)
await click(button('❚❚ 暂停'))
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

// 3. 点镜头：关画布、回分镜页并定位到那一镜
const target = shots[5].id
await click(container.querySelectorAll('.tlc__shot')[5])
must(!container.querySelector('.tlc'), '点镜头应关闭画布')
must(!!win.document.getElementById(`shot-${target}`), '分镜页应有该镜头的锚点')
must(win.document.getElementById(`shot-${target}`)!.classList.contains('is-flash'), '定位的镜头要闪一下')
console.log(`3. 点镜头 → 回分镜页定位 ${target} ✓`)

// 4. 点浮层里的原文句：回原文溯源页
await click(button('时间轴画布'))
const unit = container.querySelector('.tlc__unit') as unknown as HTMLElement
must(!!unit, '浮层应列出本镜引用的原文句')
await click(unit)
must(!container.querySelector('.tlc') && !!container.querySelector('.src'), '点原文句应回到原文溯源页')
console.log('4. 点原文句 → 原文溯源页 ✓')

// 5. Esc 关闭
await click(button('时间轴画布'))
await act(async () => {
  win.dispatchEvent(new win.KeyboardEvent('keydown', { key: 'Escape' }) as unknown as Event)
})
await settle()
must(!container.querySelector('.tlc'), 'Esc 应关闭画布')
console.log('5. Esc 关闭 ✓')

await act(async () => { root.unmount() })
console.log('\nALL PASS')
