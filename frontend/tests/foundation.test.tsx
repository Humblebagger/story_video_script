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

// 1b. 新旧设计变量不重名：app.css 与 index.css 在 :root / .dark 里定义的自定义属性不能有交集（否则互相覆盖）
const cssVars = (file: string) => {
  const css = readFileSync(new URL(file, import.meta.url), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '')
  const names = new Set<string>()
  for (const b of css.matchAll(/(?:^|\n)\s*(?::root(?:\.dark)?|\.dark)\s*\{([^}]*)\}/g))
    for (const d of b[1].matchAll(/(--[\w-]+)\s*:/g)) names.add(d[1])
  return names
}
const uiVars = cssVars('../src/styles/app.css')
const legacyVars = cssVars('../src/index.css')
must(uiVars.size > 20 && legacyVars.size > 10, `读到两边的变量（${uiVars.size} / ${legacyVars.size}）`)
const clash = [...uiVars].filter((n) => legacyVars.has(n))
must(clash.length === 0, `新旧设计变量重名：${clash.join(', ')}`)
console.log('1b. 设计变量不重名 ✓')

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
must(body().includes('未配置密钥') && body().includes('书架内容') && body().includes('内容区'), '服务状态与插槽')
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

// 静态检查：名单里的源文件除注释外不许有中文（Task 8 改成全量）
const fs = await import('node:fs')
const path = await import('node:path')
const SRC = path.resolve(import.meta.dirname ?? '.', '../src')
const I18N_FILES = [
  'labels.ts', 'presets.ts', 'compose.ts', 'film.ts', 'api.ts', 'chapters.ts', 'useKeyframes.ts',
  'useFilm.ts', 'useCompose.ts', 'edit.ts', 'resolve.ts', 'types.ts', 'theme.ts', 'auth.ts', 'notify.ts', 'main.tsx',
]
// 必须保持中文的数据字面量（正确性所需），按文件、按行形态放行：
//  presets.ts：P('中文取值', 'presets.…') 的取值会写进分镜、发给模型，不能译；显示名走语言包
//  chapters.ts：解析「第X章」之类中文章节标题的正则，换成别的字就认不出中文章节了
const ALLOW: Record<string, RegExp> = {
  'presets.ts': /^\s*P\('[^']*', 'presets\./,
  'chapters.ts': /^\s*re: \/\^/,
}
const stripComments = (s: string) => s
  .replace(/\{\/\*[\s\S]*?\*\/\}/g, '').replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|\s)\/\/.*$/gm, '$1')
for (const f of I18N_FILES) {
  const hits = stripComments(fs.readFileSync(path.join(SRC, f), 'utf8')).split('\n')
    .map((l, i) => [i + 1, l] as const).filter(([, l]) => cjk.test(l) && !ALLOW[f]?.test(l))
  must(!hits.length, `${f} 还有硬编码中文：第 ${hits.slice(0, 3).map(([n]) => n).join('、')} 行`)
}

await act(async () => { root.unmount() })
console.log('\nALL PASS')
