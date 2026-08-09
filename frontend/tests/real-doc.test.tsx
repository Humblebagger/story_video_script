/** 真实产物的渲染回归：拿《药》的完整产物（133 个镜头、26 张卡）进编辑态跑一遍。
 *
 *  小夹具测得了逻辑，测不出真数据的形状问题——比如某个镜头引用了一张卡里没有的
 *  变体、或引用了压根不存在的 ID。这类脏数据在真实产物里是会出现的（模型生成的），
 *  界面不能因此白屏。
 *
 *  跑法：npm test
 */
import { readFileSync } from 'node:fs'
import { Window } from 'happy-dom'

const win = new Window({ url: 'http://localhost:5173' })
const g = globalThis as Record<string, unknown>
for (const k of ['window', 'document', 'navigator', 'location', 'HTMLElement',
                 'Element', 'Node', 'Event', 'CustomEvent', 'getComputedStyle',
                 'localStorage', 'sessionStorage']) {
  Object.defineProperty(g, k, {
    value: (win as unknown as Record<string, unknown>)[k],
    writable: true, configurable: true,
  })
}
g.IS_REACT_ACT_ENVIRONMENT = true

const { act } = await import('react')
const { createRoot } = await import('react-dom/client')
const { StoryboardView } = await import('../src/components/StoryboardView')
const { buildIndex } = await import('../src/resolve')
const { attachCard } = await import('../src/edit')
import type { Storyboard } from '../src/types'

const doc: Storyboard = JSON.parse(
  readFileSync('../backend/tests/real_text_yao/output_merged.json', 'utf8'))

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }

const container = win.document.createElement('div')
win.document.body.appendChild(container)
const root = createRoot(container as unknown as HTMLElement)

let current = doc
await act(async () => {
  root.render(
    <StoryboardView doc={current} canSave={false} dirty={false} saving={false}
                    onChange={(d) => { current = d }} onSave={() => {}} />)
})

const shots = doc.episodes.flatMap((e) => e.shots)
must(container.querySelectorAll('.shot').length === shots.length,
     `应渲染全部 ${shots.length} 个镜头`)
console.log(`只读态 ok：${doc.episodes.length} 集 / ${shots.length} 镜渲染完整`)

// 进编辑态
const editBtn = [...container.querySelectorAll('button')]
  .find((b) => (b.textContent ?? '').includes('编辑分镜'))
must(!!editBtn, '应有「编辑分镜」入口')
await act(async () => { (editBtn as unknown as HTMLElement).click() })

must(container.querySelectorAll('.ed__at textarea').length === shots.length,
     '编辑态下每个镜头的画面描述都应挂着 @ 选卡容器')
must(container.querySelectorAll('.ed__attach').length === shots.length,
     '每个镜头都应有「＋ 挂卡 / 垫图」入口')

/** 变体下拉只该出现在「卡上确有变体集」的引用旁——多一个少一个都会诱人填出非法值 */
const idx = buildIndex(doc)
const expectVariants = shots.reduce((n, s) => n
  + (s.characters ?? []).filter((c) => (idx.card(c.ref)?.variants.length ?? 0) > 0).length
  + (s.prop_refs ?? []).filter((p) => (idx.card(p.ref)?.variants.length ?? 0) > 0).length, 0)
must(container.querySelectorAll('.ed--var').length === expectVariants,
     `变体下拉应恰好 ${expectVariants} 个，实为 ${container.querySelectorAll('.ed--var').length}`)
console.log(`编辑态 ok：${shots.length} 个镜头均有挂卡入口，变体下拉 ${expectVariants} 个`)

// 脏数据不该白屏：造一个引用了不存在资产的镜头
const dirtyDoc: Storyboard = JSON.parse(JSON.stringify(doc))
dirtyDoc.episodes[0].shots[0].characters = [{ ref: 'C99' }]
dirtyDoc.episodes[0].shots[0].prop_refs = [{ ref: 'P99', state: '不存在' }]
await act(async () => {
  root.render(
    <StoryboardView doc={dirtyDoc} canSave={false} dirty={false} saving={false}
                    onChange={() => {}} onSave={() => {}} />)
})
must(container.querySelectorAll('.shot').length === shots.length,
     '引用了不存在的资产时仍应完整渲染，不能白屏')
console.log('脏引用 ok：引用不存在的资产不至于白屏')

// 挂卡返回的 patch 用在真实镜头上，逐个核对与 lint 规则一致
let bad = 0
for (const s of shots.slice(0, 40)) {
  for (const card of idx.cardOptions) {
    const patch = attachCard(s, card)
    const ch = patch.characters?.find((c) => c.ref === card.id)
    const pr = patch.prop_refs?.find((p) => p.ref === card.id)
    if (card.kind === 'creatures' && ch && 'outfit' in ch) bad++
    if (card.kind === 'characters' && ch && card.variants.length && !ch.outfit) bad++
    if (card.kind === 'props' && pr && card.variants.length && !pr.state) bad++
    if (card.kind === 'props' && pr && !card.variants.length && 'state' in pr) bad++
  }
}
must(bad === 0, `挂卡产出的引用有 ${bad} 处不合 lint 规则`)
console.log(`挂卡规则 ok：40 个镜头 × ${idx.cardOptions.length} 张卡的组合全部合规`)

root.unmount()
console.log('\nALL PASS')
