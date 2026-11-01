/** 书架与新建：底层零件（风格色块与前缀、状态标签）。跑法：npm test */
import { Window } from 'happy-dom'

const win = new Window({ url: 'http://localhost:5173' })
const g = globalThis as Record<string, unknown>
for (const k of ['window', 'document', 'navigator', 'location', 'HTMLElement', 'Element', 'Node', 'Event',
                 'CustomEvent', 'KeyboardEvent', 'MouseEvent', 'PointerEvent', 'getComputedStyle',
                 'localStorage', 'sessionStorage', 'matchMedia', 'ResizeObserver', 'DOMRect', 'MutationObserver', 'FileReader', 'NodeFilter']) {
  Object.defineProperty(g, k, {
    value: (win as unknown as Record<string, unknown>)[k], writable: true, configurable: true,
  })
}
g.IS_REACT_ACT_ENVIRONMENT = true

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }
const { act, createElement: h } = await import('react')
const { createRoot } = await import('react-dom/client')
const { ART_STYLES, COLOR_TONES, STYLE_PREFIXES } = await import('../src/presets')
const { STYLE_LOOKS, lookOf, prefixTouched, swatchFor } = await import('../src/styleLook')
const { DEFAULT_PARAMS } = await import('../src/components/ParamsForm')
const { RatioPicker } = await import('../src/components/params/RatioPicker')
const { StylePicker } = await import('../src/components/params/StylePicker')
const { VoicePicker } = await import('../src/components/params/VoicePicker')
const { NarrationPick } = await import('../src/components/params/NarrationPick')
const { MoreParams } = await import('../src/components/params/MoreParams')
const { getStyleImage, setStyleImage, clearStyleImage } = await import('../src/styleImages')
const { notice } = await import('../src/lib/notice')
const { ParamChip } = await import('../src/components/params/ParamChip')
const { NewNovelComposer } = await import('../src/components/NewNovelComposer')
const { StatusPill } = await import('../src/components/common/StatusPill')

const container = win.document.createElement('div')
win.document.body.appendChild(container)
const root = createRoot(container as unknown as HTMLElement)

must(ART_STYLES.every((a) => STYLE_LOOKS.some((s) => s.id === a.value)), 'STYLE_LOOKS 没覆盖全部画风')
must(lookOf('realistic')?.prefix.value === DEFAULT_PARAMS.style_prefix, '写实的前缀应等于默认风格前缀')
must(prefixTouched(DEFAULT_PARAMS.style_prefix) === false, '默认前缀不算手改')
must(prefixTouched('自己写的') === true, '自写前缀算手改')
must(swatchFor('n1') === swatchFor('n1'), '色块要稳定')

await act(async () => { root.render(h(StatusPill, { tone: 'live' }, '生成中')) })
const pill = win.document.querySelector('[data-tone="live"]')
must(!!pill && pill.textContent === '生成中', '状态标签应渲染出文字')

// ---------- 参数组件 ----------
type P = typeof DEFAULT_PARAMS
const doc = win.document
const q = (sel: string) => doc.querySelector(sel) as unknown as HTMLElement | null
const qa = (sel: string) => [...doc.querySelectorAll(sel)] as unknown as HTMLElement[]
const click = async (el: HTMLElement | null) => {
  must(!!el, '要点的元素不存在')
  await act(async () => { el!.dispatchEvent(new win.MouseEvent('click', { bubbles: true }) as unknown as Event) })
}
const mount = async (C: unknown, value: P, extra: Record<string, unknown> = {}) => {
  const got: P[] = []
  await act(async () => { root.render(h(C as never, { value, onChange: (n: P) => got.push(n), ...extra })) })
  return got
}
const setInput = async (el: HTMLElement, v: string) => {
  await act(async () => {
    const proto = Object.getPrototypeOf(el)
    Object.getOwnPropertyDescriptor(proto, 'value')!.set!.call(el, v)
    el.dispatchEvent(new win.Event('input', { bubbles: true }) as unknown as Event)
  })
}

{ // RatioPicker
  const got = await mount(RatioPicker, DEFAULT_PARAMS)
  must(qa('[data-ratio]').length === 4, '应有 4 个比例按钮')
  must(q('[data-ratio="9:16"]')!.getAttribute('aria-pressed') === 'true', '当前比例应选中')
  await click(q('[data-ratio="16:9"]'))
  must(got[0].aspect_ratio === '16:9' && got[0].tts_voice === DEFAULT_PARAMS.tts_voice, '点 16:9 只改画幅')
}

{ // StylePicker
  let got = await mount(StylePicker, DEFAULT_PARAMS)
  must(qa('[data-style]').length === 9 && qa('[data-style-custom]').length === 1, '应有 9 张风格卡 + 1 张自定义')
  await click(q('[data-style="anime"]'))
  must(got[0].art_style === 'anime' && got[0].style_prefix === lookOf('anime')!.prefix.value, '默认前缀时带出动漫前缀')
  got = await mount(StylePicker, { ...DEFAULT_PARAMS, style_prefix: '自己写的' })
  await click(q('[data-style="ink_wash"]'))
  must(got[0].art_style === 'ink_wash' && got[0].style_prefix === '自己写的', '手改过的前缀不覆盖')
  let customed = 0
  await act(async () => { root.render(h(StylePicker as never, { value: DEFAULT_PARAMS, onChange: () => {}, onCustom: () => { customed++ } })) })
  await click(q('[data-style-custom]'))
  must(customed === 1, '点自定义应调用 onCustom')
  await mount(StylePicker, DEFAULT_PARAMS, { compact: true })
  must(qa('[data-style-upload]').length === 0, 'compact 不显示换图按钮')
}

{ // 风格卡换图
  await mount(StylePicker, DEFAULT_PARAMS)
  must(!q('[data-style="anime"] img'), '默认应是色块')
  const file = new win.File(['x'], 'a.png', { type: 'image/png' })
  await act(async () => { await setStyleImage('anime', file as unknown as Blob) })
  must((getStyleImage('anime') ?? '').startsWith('data:image/'), '换图后应存成 data URL')
  must(!!q('[data-style="anime"] img'), '换图后动漫卡片应显示 img')
  must(!!q('[data-style-reset="anime"]'), '有图时应有恢复默认按钮')
  await act(async () => { clearStyleImage('anime') })
  must(getStyleImage('anime') === undefined && !q('[data-style="anime"] img'), '恢复默认后回到色块')
  const realLS = g.localStorage
  const before = notice.log.length
  g.localStorage = { getItem: () => null, setItem: () => { throw new Error('quota') } }
  let ok = true
  await act(async () => { ok = await setStyleImage('anime', file as unknown as Blob) })
  g.localStorage = realLS
  must(ok === false && getStyleImage('anime') === undefined, '存不下时保持色块')
  must(notice.log.length === before + 1 && notice.log[notice.log.length - 1].kind === 'err', '存不下应记一条 notice.err')
}

{ // NarrationPick
  let got = await mount(NarrationPick, DEFAULT_PARAMS)
  await click(q('[data-narration="acted"]'))
  must(got[0].narration_mode === 'none', '剧情演绎写入 none')
  got = await mount(NarrationPick, { ...DEFAULT_PARAMS, narration_mode: 'none' })
  await click(q('[data-narration="narrated"]'))
  must(got[0].narration_mode === 'selective', '旁白解说写入 selective')
  await mount(NarrationPick, { ...DEFAULT_PARAMS, narration_mode: 'condensed' })
  must(q('[data-narration="narrated"]')!.getAttribute('aria-checked') === 'true', 'condensed 时旁白解说选中')
  must(q('[data-narration-sub]')?.textContent === '压缩概述', '应显示压缩概述角标')
}

{ // VoicePicker
  const got = await mount(VoicePicker, DEFAULT_PARAMS)
  const items = qa('[data-voice]')
  must(items.length === 5, '应有 5 个音色')
  must((items[2].textContent ?? '').includes('女声 · 沉稳'), '音色应带描述')
  await click(items[2])
  must(got[0].tts_voice === 'female_mature', '第 3 项写入 female_mature')
}

{ // MoreParams
  const got = await mount(MoreParams, DEFAULT_PARAMS)
  const selects = qa('select')
  const sel0 = selects[0] as unknown as HTMLSelectElement
  await act(async () => {
    sel0.value = COLOR_TONES[2].value
    sel0.dispatchEvent(new win.Event('change', { bubbles: true }) as unknown as Event)
  })
  must(got.at(-1)!.color_tone === COLOR_TONES[2].value, '色调写回 color_tone')
  const sel1 = selects[1] as unknown as HTMLSelectElement
  await act(async () => {
    sel1.value = '快手'
    sel1.dispatchEvent(new win.Event('change', { bubbles: true }) as unknown as Event)
  })
  must(got.at(-1)!.target_platform === '快手', '平台写回 target_platform')
  await setInput(q('[data-more="prefix"]')!, '新前缀')
  must(got.at(-1)!.style_prefix === '新前缀', '风格前缀输入写回')
  await click(qa('[data-prefix-tag]')[1])
  must(got.at(-1)!.style_prefix === STYLE_PREFIXES[1].value, '点小标签填入前缀')
  must(qa('[data-narr-mode]').length === 4, '旁白细项应有 4 种')
  await click(q('[data-narr-mode="original_text"]'))
  must(got.at(-1)!.narration_mode === 'original_text', '旁白细项可选原文照念')
}

{ // ParamChip
  await act(async () => { root.render(h(ParamChip as never, { icon: null, label: '画幅', value: '9:16', testId: 'chip-ratio' }, h('i', { id: 'chip-body' }))) })
  const chip = q('[data-testid="chip-ratio"]')
  must(!!chip && (chip.textContent ?? '').includes('画幅') && (chip.textContent ?? '').includes('9:16'), '胶囊显示标签与当前值')
  must(!q('#chip-body'), '未点开时不渲染浮层内容')
}
{ // NewNovelComposer
  const calls: { title: string; params: P; chapters: { title: string; text: string }[] }[] = []
  await act(async () => { root.render(h(NewNovelComposer as never, { disabled: false, onSubmit: (n: never) => calls.push(n) })) })
  const submitBtn = () => q('[data-testid="composer-submit"]') as unknown as HTMLButtonElement
  must(submitBtn().disabled, '标题为空时主按钮禁用')
  must((doc.body.textContent ?? '').includes('先给小说起个名字'), '应提示先起名')
  const area = q('[data-testid="composer-source"]')!
  must(area.closest('.form__text') !== null, '原文框外层保留 form__text')
  await setInput(area, '第一章 甲\n正文一\n第二章 乙\n正文二')
  must(qa('[data-testid="chapter-chip"]').length === 2, '粘贴两章后应有 2 个章节标签')
  must((submitBtn().textContent ?? '').includes('创建并导入 2 章'), '主按钮应写创建并导入 2 章')
  await setInput(q('input[aria-label="小说标题"]')!, '药')
  must(!submitBtn().disabled, '填了标题后主按钮可点')
  await click(q('[data-narration="acted"]'))
  await click(q('[data-testid="chip-ratio"]'))
  await click(q('[data-ratio="16:9"]'))
  await click(submitBtn())
  must(calls.length === 1, '点主按钮应提交一次')
  must(JSON.stringify(calls[0].params) === JSON.stringify({ ...DEFAULT_PARAMS, aspect_ratio: '16:9', narration_mode: 'none' }), '提交的参数应带上画幅与剧情演绎')
  must(calls[0].chapters.length === 2 && calls[0].chapters[0].title === '第一章 甲' && calls[0].chapters[1].title === '第二章 乙', '应按章拆成两章')

  // ⌘Enter 提交
  await act(async () => {
    q('input[aria-label="小说标题"]')!.dispatchEvent(new win.KeyboardEvent('keydown', { key: 'Enter', metaKey: true, bubbles: true }) as unknown as Event)
  })
  must(calls.length === 2, '⌘Enter 应提交')

}
{ // 拖放与折叠
  await act(async () => { root.render(h(NewNovelComposer as never, { key: 'fresh', disabled: false, onSubmit: () => {} })) })
  const card = q('.composer')!
  const fire = (type: string, dt: unknown) => act(async () => {
    const ev = new win.Event(type, { bubbles: true, cancelable: true })
    Object.defineProperty(ev, 'dataTransfer', { value: dt })
    card.dispatchEvent(ev as unknown as Event)
  })
  await fire('dragenter', { files: [], types: ['Files'] })
  must(card.getAttribute('data-drop') === 'on', '拖入时卡片带 data-drop=on')
  const file = new win.File(['第一章\n内容'], '我的小说.txt')
  await fire('drop', { files: [file], types: ['Files'] })
  await act(async () => { await new Promise((r) => setTimeout(r, 30)) })
  must(card.getAttribute('data-drop') !== 'on', '松手后取消高亮')
  must((q('input[aria-label="小说标题"]') as unknown as HTMLInputElement).value === '我的小说', '标题自动取文件名')
  must(((q('[data-testid="composer-source"]') as unknown as HTMLTextAreaElement).value).includes('内容'), '原文框应有内容')

  // 超过 4 章：4 个标签加 +N
  const six = Array.from({ length: 6 }, (_, i) => `第${i + 1}章 题\n正文${i}`).join('\n')
  await setInput(q('[data-testid="composer-source"]')!, six)
  must(qa('[data-testid="chapter-chip"]').length === 4, '超过 4 章只显示 4 个标签')
  must((q('[data-testid="chapter-more"]')?.textContent ?? '') === '+2', '应有 +2 折叠标签')
  await click(q('[data-testid="chapter-more"]'))
  must(qa('[data-testid="chapter-chip"]').length === 6, '点开显示全部')
}

await act(async () => { root.unmount() })
console.log('\nALL PASS')
