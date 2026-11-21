/** 出片任务列表（GET /render/tasks）：哪些在跑、哪些要播报、显示用的名字与等待文字（都是纯计算），
 *  外加一个「催一下」的小信号（画布 → 应用）。App 轮询、动态面板只吃这里的结果；单测见 tests/film-tasks.test.tsx。 */
import { waitLine } from './film'
import type { FilmTask } from './types'

const LIVE: FilmTask['state'][] = ['queued', 'running', 'downloading']

export const isLiveTask = (t: FilmTask) => LIVE.includes(t.state)

/** 「药 · 第一章 · E01-C01」：小说、章节、片段；标题缺失的略过 */
export const taskName = (t: FilmTask) => [t.work_title, t.chapter, t.item_id].filter(Boolean).join(' · ')

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
