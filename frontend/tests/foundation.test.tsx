/** 改版底座：语言包键一致与插值、主题偏好与 dark class、外壳（语言切换后文字变英文、收起侧边栏、管理入口与退出回调）、
 *  花钱确认（合计、累计、超上限禁用、金额变了提示）、动效预设在减少动态效果时不位移。跑法：npm test */
import { readFileSync } from 'node:fs'
import { Window } from 'happy-dom'

const win = new Window({ url: 'http://localhost:5173' })
const g = globalThis as Record<string, unknown>
for (const k of ['window', 'document', 'navigator', 'location', 'HTMLElement', 'Element', 'Node', 'Event',
                 'CustomEvent', 'KeyboardEvent', 'MouseEvent', 'PointerEvent', 'getComputedStyle',
                 'localStorage', 'sessionStorage', 'matchMedia', 'ResizeObserver', 'DOMRect', 'MutationObserver']) {
  Object.defineProperty(g, k, {
    value: (win as unknown as Record<string, unknown>)[k], writable: true, configurable: true,
  })
}
g.IS_REACT_ACT_ENVIRONMENT = true

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }

const { zh } = await import('../src/i18n/zh')
const { en } = await import('../src/i18n/en')
const { translate, useI18n } = await import('../src/i18n/core')
const { presets } = await import('../src/motion')
const theme = await import('../src/theme')

// 1. 语言包：键一致（运行时再比一遍，防类型被 as 绕过）、插值、缺键回落为键名
const keys = (o: object, p = ''): string[] => Object.entries(o).flatMap(([k, v]) =>
  typeof v === 'string' ? [`${p}${k}`] : keys(v as object, `${p}${k}.`))
must(JSON.stringify(keys(zh).sort()) === JSON.stringify(keys(en).sort()), '中英文语言包的键必须一致')
must(translate('en', 'shell.signedInAs', { name: 'amy' }) === 'Signed in as amy', '英文插值')
must(translate('zh', 'shell.signedInAs', { name: 'amy' }) === '已登录：amy', '中文插值')
must(translate('zh', 'brand.name') === '墨卷' && translate('en', 'brand.name') === 'Inkreel', '品牌名')
must(translate('en', 'nope.missing' as never) === 'nope.missing', '缺键回落为键名')
must(translate('en', 'money.confirm', { action: 'Go', amount: '¥1.00' }) === 'Go (¥1.00)', '确认按钮文案（英文）')
console.log('1. 语言包 ✓')

// 1b. 旧样式表 index.css 已删除；styles/*.css 不许再引用旧变量
{
  const fs = await import('node:fs')
  const dir = new URL('../src/styles/', import.meta.url)
  must(!fs.existsSync(new URL('../src/index.css', import.meta.url)), '旧样式表 src/index.css 应已删除')
  const oldVar = /var\(--(bg|panel|panel-2|text|muted|faint|line|line-2|accent|accent-soft|explicit|inferred|transition|danger|warn-bg|radius|mono)\)/
  const styles = fs.readdirSync(dir).filter((f) => f.endsWith('.css'))
  must(styles.length >= 8, `读到 styles/*.css（${styles.length}）`)
  for (const f of styles) {
    const m = readFileSync(new URL(f, dir), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '').match(oldVar)
    must(!m, `styles/${f} 还在用旧变量 ${m?.[0]}`)
  }
}
console.log('1b. 旧样式表已删、无旧变量 ✓')

// 2. 主题：偏好存本机，实际深浅写到 <html class="dark">
theme.setPref('dark')
must(win.document.documentElement.classList.contains('dark') && theme.readPref() === 'dark', '深色')
theme.setPref('light')
must(!win.document.documentElement.classList.contains('dark') && theme.readPref() === 'light', '浅色')
theme.setPref('system')
must(theme.readPref() === 'system' && win.localStorage.getItem('inkreel.theme') === null, '跟随系统不存值')
console.log('2. 主题 ✓')

// 3. 动效：减少动态效果时不位移
must(presets(true).enter.initial.y === 0 && presets(false).enter.initial.y === 8, '进场位移')
must(presets(true).item(3).initial.y === 0 && presets(true).pop.initial.scale === 1, '列表与弹出')
console.log('3. 动效预设 ✓')

const { act } = await import('react')
const { createRoot } = await import('react-dom/client')
const { I18nProvider } = await import('../src/i18n')
const { AppShell } = await import('../src/components/shell/AppShell')
const { MoneyConfirm } = await import('../src/components/common/MoneyConfirm')
const { TooltipProvider } = await import('../src/components/ui/tooltip')

const container = win.document.createElement('div')
win.document.body.appendChild(container)
const root = createRoot(container as unknown as HTMLElement)
const settle = async (ms = 30) => { await act(async () => { await new Promise((r) => setTimeout(r, ms)) }) }
const body = () => win.document.body.innerHTML
const button = (text: string) => {
  const b = [...win.document.querySelectorAll('button')].find((x) => (x.textContent ?? '').includes(text))
  if (!b) throw new Error(`✗ 找不到按钮「${text}」`)
  return b as unknown as HTMLButtonElement
}
const click = async (el: Element) => {
  await act(async () => { el.dispatchEvent(new win.MouseEvent('click', { bubbles: true }) as unknown as Event) })
  await settle()
}

// 4. 外壳：中文文字、管理入口与退出回调、收起侧边栏；切到英文后文字跟着变
const log: string[] = []
let setLoc: (l: 'zh' | 'en') => void = () => {}
function Grab() { setLoc = useI18n().setLocale; return null }
function Host() {
  return (
    <I18nProvider initial="zh">
      <TooltipProvider>
        <Grab />
        <AppShell username="amy" isAdmin adminOpen={false} onToggleAdmin={() => log.push('admin')}
                  onLogout={() => log.push('logout')} onNewNovel={() => log.push('new')} onOpenLocal={() => {}}
                  crumbs={['药', '第一章']} service={{ down: false, model: 'claude-x', noKey: true }}
                  sidebar={<p>书架内容</p>} viewKey="a">
          <p>内容区</p>
        </AppShell>
      </TooltipProvider>
    </I18nProvider>
  )
}
await act(async () => { root.render(<Host />) })
await settle()
must(body().includes('墨卷') && body().includes('amy') && body().includes('药') && body().includes('第一章'),
  '外壳显示品牌、用户与面包屑')
must(body().includes('书架内容') && body().includes('内容区'), '插槽')
const openAccount = async () => {
  await act(async () => {
    win.document.querySelector('[data-testid="account-menu"]')!.dispatchEvent(
      new win.PointerEvent('pointerdown', { bubbles: true, button: 0, ctrlKey: false }) as unknown as Event)
  })
  await settle()
}
await openAccount()
must(body().includes('未配置密钥') && body().includes('claude-x'), '账号菜单里有当前模型与服务状态')
await act(async () => { win.document.dispatchEvent(new win.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }) as unknown as Event) })
await settle()
await click(button('管理'))
await click(button('新建小说'))
await click(button('退出'))
must(log.join(',') === 'admin,new,logout', `外壳按钮回调：${log}`)
await click(win.document.querySelector('button[aria-label="收起侧边栏"]')!)
must(!!win.document.querySelector('button[aria-label="展开侧边栏"]'), '收起侧边栏')
const aside = win.document.querySelector('[data-testid="app-shell"] aside')!
must(!(aside.textContent ?? '').includes('amy'), '收起后不显示用户名文字')
must(win.document.querySelector('button[aria-label="展开侧边栏"]')!.getAttribute('aria-expanded') === 'false', '收起按钮 aria-expanded')
await click(win.document.querySelector('button[aria-label="退出"]')!)
must(log.join(',') === 'admin,new,logout,logout', '收起后退出仍可用（按 aria-label 找到）')
must(win.document.documentElement.lang === 'zh-CN', 'html lang 为中文')
must(win.document.querySelector('nav[aria-label="位置"] [aria-current="page"]')?.textContent === '第一章', '面包屑最后一节 aria-current')
await act(async () => { setLoc('en') })
await settle()
await openAccount()
must(body().includes('Inkreel') && body().includes('Sign out') && body().includes('API key not set'),
  '切到英文后外壳文字变英文')
must(win.document.documentElement.lang === 'en', 'html lang 跟着切到英文')
console.log('4. 应用外壳 ✓')

// 5. 花钱确认：合计、执行后累计、超上限时确认禁用、金额变了提示
let confirmed = 0
let cancelled = 0
function Money({ cny, changed }: { cny: number; changed?: boolean }) {
  return (
    <I18nProvider initial="zh">
      <MoneyConfirm open title="出剩余 3 段" cny={cny} spent={10} reserved={5} budget={100} changed={changed}
                    rateNote="假厂商" action="确认出片" onConfirm={() => { confirmed += 1 }} onCancel={() => { cancelled += 1 }} />
    </I18nProvider>
  )
}
await act(async () => { root.render(<Money cny={20} />) })
await settle()
must(body().includes('¥20.00') && body().includes('执行后累计 ¥35.00') && body().includes('费率依据：假厂商'),
  '合计与累计')
await click(button('确认出片（¥20.00）'))
must(confirmed === 1, '确认回调')
await click(button('取消'))
must(cancelled === 1, '取消 → onCancel')
await act(async () => {
  win.document.activeElement?.dispatchEvent(new win.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }) as unknown as Event)
})
await settle()
must(cancelled === 2, `Esc → onCancel（${cancelled}）`)
await act(async () => { root.render(<Money cny={90} changed />) })
await settle()
must(body().includes('金额已变为 ¥90.00') && body().includes('会超过上限') && button('确认出片（¥90.00）').disabled,
  '超上限禁用、金额变了提示')
console.log('5. 花钱确认 ✓')

// 5b. 危险确认 useConfirm：取消得 false、确定得 true、连续两次 ask 时前一次得 false
const { useConfirm } = await import('../src/components/common/ConfirmDialog')
const answers: boolean[] = []
function Asker() {
  const [ask, ui] = useConfirm()
  return (
    <I18nProvider initial="zh">
      <button data-testid="ask1" onClick={() => void ask({ title: '删除这个？', body: '不可撤销', action: '删除', danger: true }).then((v) => answers.push(v))}>问一次</button>
      <button data-testid="ask2" onClick={() => {
        void ask({ title: '第一问' }).then((v) => answers.push(v))
        void ask({ title: '第二问' }).then((v) => answers.push(v))
      }}>连问</button>
      {ui}
    </I18nProvider>
  )
}
const byId = (id: string) => win.document.body.querySelector<HTMLElement>(`[data-testid="${id}"]`)
await act(async () => { root.render(<Asker />) })
await settle()
must(!byId('confirm-dialog'), '没问之前没有确认框')
await click(byId('ask1')!)
must(!!byId('confirm-dialog') && body().includes('删除这个？') && body().includes('不可撤销'), '问一次：确认框出现')
must(byId('confirm-ok')!.textContent === '删除', '确认按钮文字')
await click(byId('confirm-cancel')!)
must(answers.join() === 'false', '取消得 false')
await settle(300)
await click(byId('ask1')!)
await click(byId('confirm-ok')!)
must(answers.join() === 'false,true', '确定得 true')
await settle(300)
answers.length = 0
await click(byId('ask2')!)
must(answers.join() === 'false' && body().includes('第二问'), '连续两次：第一次得 false，弹的是第二问')
await click(byId('confirm-ok')!)
must(answers.join() === 'false,true', '第二问确定得 true')
console.log('5b. 危险确认 useConfirm ✓')

// 非组件文字：tr / localized 跟着当前语言走
const core = await import('../src/i18n/core')
const labels = await import('../src/labels')
core.setCurrentLocale('en')
must(labels.label(labels.SHOT_SIZE, 'wide') === 'Wide', '枚举标签（英文）')
must(core.tr('common.cancel') === 'Cancel', 'tr（英文）')
must(Object.keys(labels.SHOT_SIZE).includes('close_up'), 'localized 可枚举')
core.setCurrentLocale('zh')
must(labels.label(labels.SHOT_SIZE, 'wide') === '远景', '枚举标签（中文）')

// 英文语言包里不许有中文
const cjk = /[一-鿿]/
const leaves = (o: unknown, p = ''): [string, string][] => typeof o === 'string' ? [[p, o]]
  : Object.entries(o as Record<string, unknown>).flatMap(([k, v]) => leaves(v, p ? `${p}.${k}` : k))
const bad = leaves(en).filter(([, v]) => cjk.test(v))
must(!bad.length, `英文包含中文：${bad.slice(0, 5).map(([k]) => k).join(', ')}`)

// 6. 新手引导：目标在页面上才显示、一次一条、看过的记进本机、跳过全部
{
  const tour = await import('../src/tour')
  const { Tour } = await import('../src/components/common/Tour')
  win.localStorage.removeItem('inkreel.tour')
  const host = win.document.createElement('div')
  host.innerHTML = '<button data-tour="new-novel">新建</button>'
  win.document.body.appendChild(host)
  const rect = () => ({ width: 100, height: 30, top: 10, left: 10, right: 110, bottom: 40, x: 10, y: 10, toJSON() {} })
  const stub = (el: Element) => { (el as unknown as { getBoundingClientRect: () => unknown }).getBoundingClientRect = rect }
  stub(host.firstElementChild!)
  const tc = win.document.createElement('div')
  win.document.body.appendChild(tc)
  const troot = createRoot(tc as unknown as HTMLElement)
  const tip = () => win.document.body.querySelector('[data-testid="tour-tip"]')
  await act(async () => { troot.render(<I18nProvider><Tour force /></I18nProvider>) })
  await settle()
  must(!!tip(), '目标在页面上就显示提示')
  must(host.firstElementChild!.hasAttribute('data-tour-on'), '目标被高亮')
  await click(tip()!.querySelectorAll('button')[1])
  must(tour.seen().includes('new-novel'), '看过的记进本机')
  must(!tip(), '看过的不再显示')
  must(!host.firstElementChild!.hasAttribute('data-tour-on'), '高亮摘掉')
  const imp = win.document.createElement('button')
  imp.setAttribute('data-tour', 'import'); stub(imp); host.appendChild(imp)
  await act(async () => { await new Promise((r) => setTimeout(r, 900)) })
  must(!!tip(), '新目标出现后显示下一条')
  // Esc：关掉提示并 preventDefault；有画布层时不出提示
  win.localStorage.removeItem('inkreel.tour')
  await act(async () => { await new Promise((r) => setTimeout(r, 900)) })
  must(!!tip(), '清掉记录后又出现')
  const esc = new win.KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
  await act(async () => { win.document.body.dispatchEvent(esc as unknown as Event) })
  must(esc.defaultPrevented && !tip(), 'Esc 关提示并 preventDefault')
  const tlc = win.document.createElement('div'); tlc.className = 'tlc'; win.document.body.appendChild(tlc)
  await act(async () => { await new Promise((r) => setTimeout(r, 900)) })
  must(!tip(), '画布层打开时不出提示')
  tlc.remove()
  await act(async () => { await new Promise((r) => setTimeout(r, 900)) })
  await click(tip()!.querySelectorAll('button')[0])
  must(['new-novel', 'import', 'steps', 'progress'].every((id) => tour.seen().includes(id as never)), '跳过全部记满 4 条')
  must(!tour.tourEnabled(), '测试环境默认不开引导')
  await act(async () => { troot.unmount() })
  host.remove(); tc.remove()
}
console.log('6. 新手引导 ✓')

// 静态检查：src/ 下全部 .ts / .tsx（中文语言包 i18n/zh.ts 与后台的中文文案 components/admin/messages.zh.ts 除外）除注释外不许有中文与全角标点
const fs = await import('node:fs')
const path = await import('node:path')
const SRC = path.resolve(import.meta.dirname ?? '.', '../src')
const walk = (d: string): string[] => fs.readdirSync(path.join(SRC, d), { withFileTypes: true }).flatMap((e) => {
  const rel = d ? `${d}/${e.name}` : e.name
  return e.isDirectory() ? walk(rel) : /\.tsx?$/.test(e.name) ? [rel] : []
})
const ZH_PACKS = ['i18n/zh.ts', 'components/admin/messages.zh.ts']
const I18N_FILES = walk('').filter((f) => !ZH_PACKS.includes(f))
must(I18N_FILES.length > 60 && I18N_FILES.includes('components/ui/dialog.tsx'), `全量扫描源文件（${I18N_FILES.length}）`)
const cjkWide = /[\u3000-\u303f\u4e00-\u9fff\uff00-\uffef]/
// src/ 下不许再有含独立单词 btn 的 className（旧按钮类已换成 Button）
for (const f of I18N_FILES) {
  const hits = fs.readFileSync(path.join(SRC, f), 'utf8').split('\n')
    .map((l, i) => [i + 1, l] as const).filter(([, l]) => /className=(?:"[^"]*|\{[^}]*)(?<![\w-])btn(?![\w-])/.test(l))
  must(!hits.length, `${f} 还在用旧按钮类 btn：第 ${hits.map(([n]) => n).join('、')} 行`)
}
// 必须保持中文的数据字面量（正确性所需），按文件、按行形态放行：
//  presets.ts：P('中文取值', 'presets.…') 的取值会写进分镜、发给模型，不能译；显示名走语言包
//  chapters.ts：解析「第X章」之类中文章节标题的正则，换成别的字就认不出中文章节了
const ALLOW: Record<string, RegExp> = {
  'presets.ts': /^\s*P\('[^']*', 'presets\./,
  'styleLook.ts': /^\s*prefix: P\('[^']*', 'presets\./,
  'chapters.ts': /^\s*re: \/\^/,
  // 制作参数默认值：逐字对齐后端 ConvertParams，会写进分镜、发给模型，不能译
  'components/ParamsForm.tsx': /^\s*(style_prefix|color_tone|target_platform): '/,
}
// 语言菜单里「中文」两个字是有意保留的（不论界面是什么语言，都用本语言写自己的名字）
const PRESTRIP: Record<string, (s: string) => string> = { 'i18n/core.ts': (s) => s.replace(/'中文'/g, "''") }
const stripComments = (s: string) => s
  .replace(/\{\/\*[\s\S]*?\*\/\}/g, '').replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|\s)\/\/.*$/gm, '$1')
for (const f of I18N_FILES) {
  const raw = fs.readFileSync(path.join(SRC, f), 'utf8')
  const hits = stripComments(PRESTRIP[f]?.(raw) ?? raw).split('\n')
    .map((l, i) => [i + 1, l] as const).filter(([, l]) => cjkWide.test(l) && !ALLOW[f]?.test(l))
  must(!hits.length, `${f} 还有硬编码中文：第 ${hits.slice(0, 3).map(([n]) => n).join('、')} 行`)
}

// 样式表里每个 var(--x) 都要有定义（--x: 声明，含 @theme），TSX 内联设的变量放行
{
  const styleDir = path.join(SRC, 'styles')
  const css = fs.readdirSync(styleDir).filter((f) => f.endsWith('.css')).map((f) => fs.readFileSync(path.join(styleDir, f), 'utf8'))
  const defined = new Set(css.flatMap((s) => [...s.matchAll(/(--[\w-]+)\s*:/g)].map((m) => m[1])))
  const inline = new Set([
    '--mood', '--pill',
    // Radix 在浮层挂载时写到 style 上的可用高度与变换原点，不在样式表里声明。
    '--radix-popover-content-available-height',
    '--radix-popover-content-transform-origin',
  ])
  const used = new Set(css.flatMap((s) => [...s.matchAll(/var\((--[\w-]+)/g)].map((m) => m[1])))
  const bad = [...used].filter((v) => !defined.has(v) && !inline.has(v))
  must(!bad.length, `样式表用了未定义的变量：${bad.join('、')}`)
}

await act(async () => { root.unmount() })
console.log('\nALL PASS')
