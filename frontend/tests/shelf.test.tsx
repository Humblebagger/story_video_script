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
g.requestAnimationFrame = (f: () => void) => setTimeout(f, 0)
g.cancelAnimationFrame = (n: number) => clearTimeout(n)
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
const { ago } = await import('../src/lib/ago')
const { ShelfHome } = await import('../src/components/ShelfHome')
const { TooltipProvider } = await import('../src/components/ui/tooltip')

const container = win.document.createElement('div')
win.document.body.appendChild(container)
const root = createRoot(container as unknown as HTMLElement)

must(ART_STYLES.every((a) => STYLE_LOOKS.some((s) => s.id === a.value)), 'STYLE_LOOKS 没覆盖全部画风')
must(lookOf('realistic')?.prefix.value === DEFAULT_PARAMS.style_prefix, '写实的前缀应等于默认风格前缀')
must(prefixTouched(DEFAULT_PARAMS.style_prefix) === false, '默认前缀不算手改')
must(prefixTouched('自己写的') === true, '自写前缀算手改')
must(swatchFor('n1') === swatchFor('n1'), '色块要稳定')
must(new Set(Array.from({ length: 20 }, (_, i) => swatchFor(`n${i}`))).size > 1, '不同 id 应分到不止一种色块')
must(prefixTouched('') === false && prefixTouched('  ') === false, '空白前缀不算手改')

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
const pickSelect = async (el: HTMLElement, value: string) => {
  await click(el)
  await act(async () => { await new Promise((r) => setTimeout(r, 80)) })
  const item = [...doc.querySelectorAll<HTMLElement>('.sel__content[data-state="open"] .sel__item')]
    .find((x) => x.getAttribute('data-value') === value || (x.textContent ?? '').includes(value))
  must(!!item, `下拉里找不到 ${value}`)
  await click(item!)
  await act(async () => { await new Promise((r) => setTimeout(r, 180)) })
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
  await pickSelect(q('button[aria-label="色调"]')!, COLOR_TONES[2].value)
  must(got.at(-1)!.color_tone === COLOR_TONES[2].value, '色调写回 color_tone')
  await pickSelect(q('button[aria-label="目标平台"]')!, '快手')
  must(got.at(-1)!.target_platform === '快手', '平台写回 target_platform')
  await setInput(q('[data-more="prefix"]')!, '新前缀')
  must(got.at(-1)!.style_prefix === '新前缀', '风格前缀输入写回')
  const got2 = await mount(MoreParams, { ...DEFAULT_PARAMS, tts_voice: 'my_voice', art_style: 'ukiyo_e' }, { key: 'custom-more' })
  await setInput(qa('input').find((i) => i.getAttribute('placeholder') === '音色标识')!, 'my_voice2')
  must(got2.at(-1)!.tts_voice === 'my_voice2', '音色可自定义输入')
  await setInput(qa('input').find((i) => i.getAttribute('placeholder') === '风格分类标识，如 ukiyo_e')!, 'noir')
  must(got2.at(-1)!.art_style === 'noir', '风格类别可自定义输入')
  const got3 = await mount(MoreParams, DEFAULT_PARAMS, { key: 'plain-more' })
  await click(qa('[data-prefix-tag]')[1])
  must(got3.at(-1)!.style_prefix === STYLE_PREFIXES[1].value, '点小标签填入前缀')
  must(qa('[data-narr-mode]').length === 4, '旁白细项应有 4 种')
  await click(q('[data-narr-mode="original_text"]'))
  must(got3.at(-1)!.narration_mode === 'original_text', '旁白细项可选原文照念')
  const got4 = await mount(MoreParams, DEFAULT_PARAMS, { key: 'custom-pick' })
  await pickSelect(q('button[aria-label="色调"]')!, '__custom__')
  const customInput = q('input[placeholder="描述整体色彩倾向"]')
  must(!!customInput && doc.activeElement === (customInput as unknown), '选自定后出现输入框并聚焦')
  await setInput(customInput!, '冷调')
  must(got4.at(-1)!.color_tone === '冷调', '自定义色调写回')
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

  // 非 .txt 被拒
  const nBefore = notice.log.length
  const png = new win.File(['x'], 'a.png', { type: 'image/png' })
  await fire('drop', { files: [png], types: ['Files'] })
  await act(async () => { await new Promise((r) => setTimeout(r, 30)) })
  must((q('input[aria-label="小说标题"]') as unknown as HTMLInputElement).value === '我的小说', '拒绝图片后标题不变')
  must(notice.log.length === nBefore + 1 && notice.log.at(-1)!.msg.includes('.txt'), '拒绝非 txt 应有 notice.err')

  // 超过 4 章：4 个标签加 +N
  const six = Array.from({ length: 6 }, (_, i) => `第${i + 1}章 题\n正文${i}`).join('\n')
  await setInput(q('[data-testid="composer-source"]')!, six)
  must(qa('[data-testid="chapter-chip"]').length === 4, '超过 4 章只显示 4 个标签')
  must((q('[data-testid="chapter-more"]')?.textContent ?? '') === '+2', '应有 +2 折叠标签')
  await click(q('[data-testid="chapter-more"]'))
  must(qa('[data-testid="chapter-chip"]').length === 6, '点开显示全部')
}

{ // 受控 + openMore
  const seen: P[] = []
  const ref = { current: null as null | { openMore: () => void } }
  await act(async () => {
    root.render(h(NewNovelComposer as never, { key: 'ctl', ref, disabled: false, onSubmit: () => {}, params: DEFAULT_PARAMS, onParamsChange: (n: P) => seen.push(n) }))
  })
  await click(q('[data-testid="chip-ratio"]'))
  await click(q('[data-ratio="1:1"]'))
  must(seen.at(-1)?.aspect_ratio === '1:1', '受控模式点比例应回调 onParamsChange')
  await act(async () => { ref.current!.openMore() })
  await act(async () => { await new Promise((r) => setTimeout(r, 80)) })
  must(!!q('[data-more="prefix"]') && doc.activeElement === (q('[data-more="prefix"]') as unknown), 'openMore 应打开更多并聚焦风格前缀')
}

{ // 风格浮层里点自定义：交棒给「更多」，不能一闪即关
  await act(async () => { root.render(h(NewNovelComposer as never, { key: 'handoff', disabled: false, onSubmit: () => {} })) })
  await click(q('[data-testid="chip-style"]'))
  await click(q('[data-style-custom]'))
  await act(async () => { await new Promise((r) => setTimeout(r, 400)) })
  const px = q('[data-more="prefix"]')
  must(!!px, '点自定义后「更多」应保持打开')
  must(doc.activeElement === (px as unknown), '点自定义后焦点应在风格前缀输入框')
  must(!q('[data-style-custom]'), '风格浮层应已关闭')
}

{ // ago
  const now = Date.parse('2026-11-01T12:00:00Z')
  const at = (min: number) => new Date(now - min * 60000).toISOString()
  must(ago(null, now) === '' && ago('bad', now) === '', '缺失或无法解析应为空串')
  must(ago(at(0), now) === '刚刚', '刚刚')
  must(ago(at(59), now) === '59 分钟前', '59 分钟')
  must(ago(at(60), now) === '1 小时前', '60 分钟应为 1 小时')
  must(ago(at(23 * 60), now) === '23 小时前', '23 小时')
  must(ago(at(24 * 60), now) === '1 天前', '24 小时应为 1 天')
  must(ago(at(31 * 1440), now) === new Date(now - 31 * 86400000).toLocaleDateString('zh-CN'), '超过 30 天给日期')
}

{ // 书架首页
  const nv = (id: string, title: string) => ({ id, title, updated_at: new Date(Date.now() - 2 * 3600e3).toISOString(), chapters: 6, adopted: 2, asset_counts: {} })
  const opened: string[] = []
  const props = { disabled: false, onSubmit: () => {}, onOpenNovel: (id: string) => { opened.push(id) } }
  await act(async () => {
    root.render(h(TooltipProvider, null, h(ShelfHome as never, { key: 'home', ...props, novels: [nv('a', '药'), nv('b', '洪水'), nv('c', '雪')], running: [{ id: 'j1', novel_id: 'b' }] })))
  })
  must((q('h1')?.textContent ?? '') === '新的故事，从哪一章开始？', '应有首屏大标题')
  must(!!q('button[data-help]'), '标题旁应有帮助按钮')
  must(qa('[data-style-picker] [data-style], [data-style-picker] [data-style-custom]').length === 10, '风格区应有 10 张卡片')
  await click(q('[data-style-picker] [data-style="watercolor"]'))
  must((q('[data-testid="chip-style"]')?.textContent ?? '').includes('水彩'), '点水彩后风格胶囊变成水彩')
  must(qa('[data-testid="shelf-card"]').length === 3 && !!q('[data-testid="shelf-new"]'), '应有 3 张小说卡和新建入口')
  must(!q('.shelf-home__projects [data-testid="shelf-new"]'), '新建入口应在分区标题旁，不占作品网格')
  must(q('[data-style-picker]')!.getAttribute('aria-label') === '画面风格', '风格区应有可访问名称')
  must(qa('[data-testid="shelf-card"]')[1].querySelector('[data-tone="live"]') !== null, '生成中的卡片有 live 标签')
  const firstCard = qa('[data-testid="shelf-card"]')[0]
  const firstTone = firstCard.querySelector('[data-cover-tone]')?.getAttribute('data-cover-tone')
  must(new Set(qa('[data-cover-tone]').map((cover) => cover.getAttribute('data-cover-tone'))).size === 3, '不同作品使用辅助色封面')
  must(firstCard.textContent!.includes('6 章 · 2 已采用') && firstCard.textContent!.includes('2 小时前'), '卡片应保留章数、采用数和相对时间')
  must(firstCard.querySelector('[title="药"]') !== null, '小说标题应保留完整文本提示')
  await click(qa('[data-testid="shelf-card"]')[2])
  must(opened.at(-1) === 'c', '点卡片应打开该小说')
  await click(q('[data-testid="shelf-new"]'))
  must(doc.activeElement === (q('input[aria-label="小说标题"]') as unknown), '点新建卡应聚焦标题输入')
  await act(async () => {
    root.render(h(TooltipProvider, null, h(ShelfHome as never, { key: 'home', ...props, novels: [nv('c', '雪'), nv('a', '药'), nv('b', '洪水')], running: [] })))
  })
  must(qa('[data-testid="shelf-card"]')[1].querySelector('[data-cover-tone]')?.getAttribute('data-cover-tone') === firstTone, '作品排序变化不改变封面色')
  await act(async () => {
    root.render(h(TooltipProvider, null, h(ShelfHome as never, { key: 'empty', ...props, novels: [], running: [] })))
  })
  must(!q('[data-testid="shelf-recent"]'), '没有小说时不显示最近的小说区')
}
{ // 小说设置页
  const { NovelPage } = await import('../src/components/NovelPage')
  const patches: Array<Record<string, unknown>> = []
  g.fetch = async (_u: unknown, init?: { method?: string; body?: string }) => {
    if (init?.method === 'PATCH') patches.push(JSON.parse(init.body ?? '{}'))
    return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } })
  }
  const novel = {
    id: 'n1', title: '药', created_at: '', updated_at: '', params: {}, chapters: [],
    memory: { assets: { characters: [], scenes: [], props: [] }, numbering: { next_unit: 1, next_para: 1, next_episode: 1 },
              lifecycle: [], plot: { outline: '', chapters: [] }, constraints: [] },
  }
  await act(async () => {
    root.render(h(TooltipProvider, null, h(NovelPage as never, {
      key: 'setpage', novel, section: 'settings', onChanged: () => {}, onDeleted: () => {}, onOpenChapter: () => {}, onNewChapter: () => {},
    })))
  })
  const heads = qa('[data-testid^="set-"] h3').map((e) => e.textContent)
  for (const w of ['画幅', '画面风格', '旁白', '音色', '更多']) must(heads.includes(w), `设置页应有「${w}」分区`)
  must((q('[data-testid="set-save"]') as unknown as HTMLButtonElement).disabled, '没改动时保存不可点')
  await click(q('[data-ratio="1:1"]'))
  must(!(q('[data-testid="set-save"]') as unknown as HTMLButtonElement).disabled, '改了之后保存可点')
  await click(q('[data-testid="set-save"]'))
  await act(async () => { await new Promise((r) => setTimeout(r, 50)) })
  must(patches.length === 1 && !('title' in patches[0]), '只应发出一次不带标题的 PATCH')
  must(JSON.stringify(patches[0].params) === JSON.stringify({ ...DEFAULT_PARAMS, aspect_ratio: '1:1' }),
       'params 应只有画幅变了')
}
{ // 设置页：自定义风格、重置策略
  const { NovelPage } = await import('../src/components/NovelPage')
  const patches: Array<Record<string, unknown>> = []
  g.fetch = async (_u: unknown, init?: { method?: string; body?: string }) => {
    if (init?.method === 'PATCH') patches.push(JSON.parse(init.body ?? '{}'))
    return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } })
  }
  const mk = (id: string, title: string) => ({
    id, title, created_at: '', updated_at: '', params: {}, chapters: [],
    memory: { assets: { characters: [], scenes: [], props: [] }, numbering: { next_unit: 1, next_para: 1, next_episode: 1 },
              lifecycle: [], plot: { outline: '', chapters: [] }, constraints: [] },
  })
  const page = async (novel: ReturnType<typeof mk>, key: string) => {
    await act(async () => {
      root.render(h(TooltipProvider, null, h(NovelPage as never, {
        key, novel, section: 'settings', onChanged: () => {}, onDeleted: () => {}, onOpenChapter: () => {}, onNewChapter: () => {},
      })))
    })
  }
  const toParams = async () => {}     // 设置分区由 section 直接给出，不再有页签
  const titleBox = () => q('input[aria-label="小说标题"]') as unknown as HTMLInputElement
  const save = () => q('[data-testid="set-save"]') as unknown as HTMLButtonElement

  await page(mk('c1', '药'), 'cust')
  await toParams()
  await click(q('[data-style-custom]'))
  must(doc.activeElement === (q('[data-more="prefix"]') as unknown), '设置页点自定义应聚焦风格前缀')
  must(qa('section[data-testid^="set-"]').every((e) => e.getAttribute('role') === 'group' && !!e.getAttribute('aria-labelledby')), '设置分区应是带标题的 group')

  await setInput(titleBox(), '药 ')
  must(save().disabled, '仅多了空白的标题不算改动')
  await setInput(titleBox(), '  新名  ')
  must(!save().disabled, '改标题后可保存')
  patches.length = 0
  await click(save())
  await act(async () => { await new Promise((r) => setTimeout(r, 50)) })
  must(patches.length === 1 && patches[0].title === '新名', '标题 PATCH 应带去空白后的新标题')

  // 同一小说的无关刷新（新对象、同内容）不冲掉未保存的编辑
  await setInput(titleBox(), '草稿')
  await page(mk('c1', '药'), 'cust')
  must(titleBox().value === '草稿', '同一小说刷新不应冲掉未保存的标题')
  // 换了小说则重置
  await page(mk('c2', '雪'), 'cust')
  must(titleBox().value === '雪', '换小说应重置表单')
}
await act(async () => { root.unmount() })
console.log('\nALL PASS')
