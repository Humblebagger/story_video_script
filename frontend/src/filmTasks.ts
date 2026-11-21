/** 出片任务列表（GET /render/tasks）：哪些在跑、哪些要播报、显示用的名字与等待文字（都是纯计算），
 *  外加一个「催一下」的小信号（画布 → 应用）。App 轮询、动态面板只吃这里的结果；单测见 tests/film-tasks.test.tsx。 */
import type { DoneJob } from './components/shell/ActivityPanel'
import { waitLine } from './film'
import { tr } from './i18n/core'
import { shortShotId } from './shotSheet'
import type { FilmTask, JobSummary } from './types'

const LIVE: FilmTask['state'][] = ['queued', 'running', 'downloading']

export const isLiveTask = (t: FilmTask) => LIVE.includes(t.state)

/** 「药 · 第一章 · E01-C01」：小说、章节、片段；标题缺失的略过 */
export const taskName = (t: FilmTask) =>
  [t.work_title, t.chapter, t.kind === 'compose' ? tr('activity.kind.compose') : t.item_id].filter(Boolean).join(' · ')

/** 「SH001–SH003」：一段所含镜头的短镜号范围；只有一个镜头不写范围，没有镜头为空 */
export const shotRange = (ids: string[]) =>
  (ids.length === 0 ? '' : ids.length === 1 ? shortShotId(ids[0])
    : `${shortShotId(ids[0])}–${shortShotId(ids[ids.length - 1])}`)

/** 任务队列里的定位行：小说 › 章节 › 片段 · 镜号范围（合成到章为止）。名字是服务端给的现在的名字，读不到写「已删除」 */
export function taskWhere(t: FilmTask): string {
  const last = t.kind === 'compose' ? tr('activity.kind.compose')
    : [t.item_id, shotRange(t.shot_ids ?? [])].filter(Boolean).join(' · ')
  return [t.work_title ?? tr('activity.deleted'), t.chapter ?? tr('activity.deleted'), last].join(' › ')
}

/** 转换任务的定位行：小说 › 章节；所属的小说或章节已删除时留名并标出 */
export function jobWhere(j: { work_title: string | null; chapter: string | null; deleted?: boolean }): string {
  const text = [j.work_title || tr('shell.shelf.converting'), j.chapter].filter(Boolean).join(' › ')
  return j.deleted ? text + tr('activity.deletedTag') : text
}

/** 结束时间：当天只写时分，隔天带月日（本地时间）；没有或解析不了为空 */
export function clockText(iso: string | null | undefined, now: Date = new Date()): string {
  const d = iso ? new Date(iso) : null
  if (!d || Number.isNaN(d.getTime())) return ''
  const p = (n: number) => String(n).padStart(2, '0')
  const hm = `${p(d.getHours())}:${p(d.getMinutes())}`
  return d.toDateString() === now.toDateString() ? hm : `${p(d.getMonth() + 1)}-${p(d.getDate())} ${hm}`
}

/** 任务面板「已结束」最多显示多少条 */
export const ENDED_MAX = 20
const RUNNING_JOB = ['queued', 'running']
const endTime = (iso: string | null | undefined) => {
  const v = iso ? Date.parse(iso) : NaN
  return Number.isNaN(v) ? Infinity : v      // 没有时间的是应用刚记下的：排最前
}
/** 按结束时间倒序（稳定：时间相同或都没有时保持原来的先后） */
function newestFirst<T>(list: T[], at: (x: T) => number): T[] {
  return list.map((x, i) => ({ x, i, at: at(x) }))
    .sort((a, b) => (a.at === b.at ? a.i - b.i : b.at - a.at)).map((e) => e.x)
}

/** 已结束的转换任务：应用记下的（prev）与 /jobs 里已结束、带结束时间的合在一起——刷新页面后列表还在。
 *  prev 里的条目用 /jobs 的最新信息补全（结束时间、失败原因、现在的名字、是否已删除） */
export function mergeDoneJobs(prev: DoneJob[], jobs: JobSummary[]): DoneJob[] {
  const ended = jobs.filter((j) => !RUNNING_JOB.includes(j.status))
  const fresh = (j: JobSummary): DoneJob => ({
    id: j.id, status: j.status, work_title: j.work_title, chapter: j.chapter, novel_id: j.novel_id, chapter_id: j.chapter_id,
    finished_at: j.finished_at ?? null, error_msg: j.error_msg ?? null, deleted: !!j.deleted,
  })
  const byId = new Map(ended.map((j) => [j.id, j]))
  const kept = prev.map((d) => {
    const j = byId.get(d.id)
    return j ? { ...d, ...fresh(j), finished_at: j.finished_at ?? d.finished_at ?? null } : d
  })
  const have = new Set(prev.map((d) => d.id))
  const added = ended.filter((j) => !have.has(j.id) && !!j.finished_at).map(fresh)
  return newestFirst([...kept, ...added], (d) => endTime(d.finished_at)).slice(0, ENDED_MAX)
}

export type EndedItem = { job: DoneJob; task?: undefined } | { task: FilmTask; job?: undefined }

/** 任务面板的「已结束」：转换任务与出片、合成任务合在一起，按结束时间倒序，最多 ENDED_MAX 条 */
export function endedItems(done: DoneJob[], tasks: FilmTask[]): EndedItem[] {
  const all: EndedItem[] = [...done.map((job) => ({ job })), ...tasks.map((task) => ({ task }))]
  return newestFirst(all, (it) => endTime(it.job ? it.job.finished_at : it.task.ended_at)).slice(0, ENDED_MAX)
}

/** 在跑的一条的等待文字：服务端算的已等秒数，加上取回（fetchedAt）之后过去的时间；now、fetchedAt 为毫秒时间戳 */
export const taskWait = (t: FilmTask, fetchedAt: number, now: number) =>
  waitLine((t.elapsed_sec ?? 0) + Math.max(0, (now - fetchedAt) / 1000), t.typical_sec)

/** 取消后才出结果的那条（state 为 late）对应的任务号：id 是 <版本>:<段>:<任务号>。其它状态没有 */
export const lateTaskId = (t: FilmTask) =>
  (t.state === 'late' ? t.id.slice(`${t.version_id}:${t.item_id}:`.length) || undefined : undefined)

const pokeSubs = new Set<() => void>()

/** 画布上刚发起或取消了出片：让应用马上重取任务列表，不必等下一轮巡检 */
export function pokeFilmTasks(): void {
  pokeSubs.forEach((f) => f())
}

export function onFilmPoke(cb: () => void): () => void {
  pokeSubs.add(cb)
  return () => { pokeSubs.delete(cb) }
}

/** 把一轮取回的任务分成在跑的、已结束的，并挑出要播报的。
 *  seen 记见过的结束（id + 结束时间）：每条只播一次；同一段再出一次、再结束，结束时间不同，照常播。
 *  first（登录后的第一轮）只记账不播报：刷新页面不该把十分钟内的结果再弹一遍。自己取消的不播。 */
export function diffFilmTasks(tasks: FilmTask[], seen: Set<string>, first: boolean) {
  const live = tasks.filter(isLiveTask)
  const ended = tasks.filter((t) => !isLiveTask(t))
  const announce: FilmTask[] = []
  for (const t of ended) {
    const key = `${t.id}@${t.ended_at ?? ''}`
    if (seen.has(key)) continue
    seen.add(key)
    if (!first && t.state !== 'cancelled') announce.push(t)
  }
  return { live, ended, announce }
}
