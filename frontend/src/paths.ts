/** 前端路由的纯函数：地址 ↔ 位置（设计 docs/specs/2026-11-12-frontend-routing-design.md §3）。
 *  不依赖 React；单测见 tests/paths.test.ts。 */
import { SECTIONS } from './section'
import type { Section } from './section'
import { STEPS } from './workflow'
import type { StepId } from './workflow'
import type { Tab } from './components/StoryboardView'

export const TABS = ['focus', 'cards', 'sheet', 'assets', 'source', 'render', 'json'] as const satisfies readonly Tab[]
/** 画布只挂在这三步（StoryboardView 只在这三步挂载） */
export const CANVAS_STEPS = ['review', 'render', 'compose'] as const satisfies readonly StepId[]
export type CanvasView = 'timeline' | 'graph'

export type Loc =
  | { kind: 'home' }
  | { kind: 'admin' }
  /** section 为 null：地址里没有分区段，小说加载完再 replace 到默认分区 */
  | { kind: 'novel'; nid: string; section: Section | null }
  /** step 为 null：步骤是章节工作流的组件内状态（§4.2） */
  | { kind: 'chapter'; nid: string; cid: string; step: StepId | null; tab: Tab; canvas: boolean; view: CanvasView }
  | { kind: 'notFound' }

/** 路由 state：push 时按需构造；replace 时用 passState 透传 */
export interface NavState {
  /** 程序性跳转：离开拦截放行（§7） */
  force?: boolean
  /** 跨地址打开章节时的一次性参数：打开这一版 / 接上这个任务（§5.4） */
  vid?: string
  jobId?: string
  /** 画布是从章节页里打开的：关闭时可以后退（§8） */
  fromChapter?: boolean
  /** 打开画布时停在哪个侧栏页（只有「出片」） */
  panel?: 'film'
}

const enc = encodeURIComponent
const isIn = <T extends string>(list: readonly T[], v: string | null | undefined): v is T =>
  v != null && (list as readonly string[]).includes(v)

export const isCanvasStep = (s: StepId | null | undefined): s is (typeof CANVAS_STEPS)[number] =>
  isIn(CANVAS_STEPS, s ?? null)

export function novelPath(nid: string, section?: Section | null): string {
  return `/novels/${enc(nid)}${section ? `/${section}` : ''}`
}

export function chapterPath(nid: string, cid: string, o: {
  step?: StepId | null; tab?: Tab | null; canvas?: boolean; view?: CanvasView | null
} = {}): string {
  const board = isCanvasStep(o.step)
  let p = `/novels/${enc(nid)}/chapters/${enc(cid)}`
  if (o.step) p += `/${o.step}`
  const canvas = board && !!o.canvas
  if (canvas) p += '/canvas'
  const q = new URLSearchParams()
  if (board && o.tab && o.tab !== 'focus') q.set('tab', o.tab)
  if (canvas && o.view === 'graph') q.set('view', 'graph')
  const s = q.toString()
  return s ? `${p}?${s}` : p
}

/** replace 时透传的 state：去掉一次性的 vid / jobId / force */
export function passState(s: NavState | null | undefined): NavState {
  const rest: NavState = { ...(s ?? {}) }
  delete rest.vid
  delete rest.jobId
  delete rest.force
  return rest
}

const decode = (s: string) => { try { return decodeURIComponent(s) } catch { return s } }

/** 解析地址。fix 非空 = 地址不规范（非法值、缺省值写进了地址），应 replace 到 fix（§3） */
export function parseLocation(pathname: string, search = ''): { loc: Loc; fix: string | null } {
  const parts = pathname.split('/').filter(Boolean).map(decode)
  const notFound = { loc: { kind: 'notFound' } as Loc, fix: null }
  if (parts.length === 0) return { loc: { kind: 'home' }, fix: null }
  if (parts[0] === 'admin') return parts.length === 1 ? { loc: { kind: 'admin' }, fix: null } : notFound
  if (parts[0] !== 'novels' || parts.length < 2) return notFound
  const nid = parts[1]
  if (parts.length === 2) return { loc: { kind: 'novel', nid, section: null }, fix: null }
  if (parts.length === 3) {
    return isIn(SECTIONS, parts[2])
      ? { loc: { kind: 'novel', nid, section: parts[2] }, fix: null }
      : { loc: { kind: 'novel', nid, section: null }, fix: novelPath(nid) }
  }
  if (parts[2] !== 'chapters' || parts.length > 6) return notFound
  const cid = parts[3]
  const rawStep = parts[4] ?? null
  if (parts.length === 6 && parts[5] !== 'canvas') return notFound
  const mk = (step: StepId | null, tab: Tab = 'focus', canvas = false, view: CanvasView = 'timeline'): Loc =>
    ({ kind: 'chapter', nid, cid, step, tab, canvas, view })
  if (rawStep === null) {
    const loc = mk(null)
    const canon = chapterPath(nid, cid)
    return { loc, fix: search && search !== '?' ? canon : null }
  }
  if (!isIn(STEPS, rawStep)) return { loc: mk(null), fix: chapterPath(nid, cid) }
  const wantsCanvas = parts.length === 6
  if (wantsCanvas && !isCanvasStep(rawStep)) return { loc: mk(null), fix: chapterPath(nid, cid) }
  const q = new URLSearchParams(search)
  const tab: Tab = isCanvasStep(rawStep) && isIn(TABS, q.get('tab')) ? (q.get('tab') as Tab) : 'focus'
  const view: CanvasView = wantsCanvas && q.get('view') === 'graph' ? 'graph' : 'timeline'
  const loc = mk(rawStep, tab, wantsCanvas, view)
  const canon = chapterPath(nid, cid, { step: rawStep, tab, canvas: wantsCanvas, view })
  const here = pathname + (search && search !== '?' ? search : '')
  return { loc, fix: canon === here ? null : canon }
}
