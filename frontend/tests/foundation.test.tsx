/** 改版底座：语言包键一致与插值、主题偏好与 dark class、外壳（语言切换后文字变英文、收起侧边栏、管理入口与退出回调）、
 *  花钱确认（合计、累计、超上限禁用、金额变了提示）、动效预设在减少动态效果时不位移。跑法：npm test */
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
console.log('1. 语言包 ✓')

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
await act(async () => { setLoc('en') })
await settle()
must(body().includes('Inkreel') && body().includes('Sign out') && body().includes('API key not set'),
  '切到英文后外壳文字变英文')
console.log('4. 应用外壳 ✓')

// 5. 花钱确认：合计、执行后累计、超上限时确认禁用、金额变了提示
let confirmed = 0
function Money({ cny, changed }: { cny: number; changed?: boolean }) {
  return (
    <I18nProvider initial="zh">
      <MoneyConfirm open title="出剩余 3 段" cny={cny} spent={10} reserved={5} budget={100} changed={changed}
                    rateNote="假厂商" action="确认出片" onConfirm={() => { confirmed += 1 }} onCancel={() => {}} />
    </I18nProvider>
  )
}
await act(async () => { root.render(<Money cny={20} />) })
await settle()
must(body().includes('¥20.00') && body().includes('执行后累计 ¥35.00') && body().includes('费率依据：假厂商'),
  '合计与累计')
await click(button('确认出片（¥20.00）'))
must(confirmed === 1, '确认回调')
await act(async () => { root.render(<Money cny={90} changed />) })
await settle()
must(body().includes('金额已变为 ¥90.00') && body().includes('会超过上限') && button('确认出片（¥90.00）').disabled,
  '超上限禁用、金额变了提示')
console.log('5. 花钱确认 ✓')

await act(async () => { root.unmount() })
console.log('\nALL PASS')
