/** 助手任务卡的进度：生成分镜查 /jobs，出片与合成查出片会话；状态判断是纯函数（可单测），钩子只管轮询。
 *  只在卡片挂载（面板显示）时查，卸载即停；网络抖动不改显示，下次再查。 */
import { useEffect, useState } from 'react'
import { ApiError, getFilm, getJob, TERMINAL } from '@/api'
import { IN_FLIGHT } from '@/film'
import type { AssistantTask, FilmSession, Job } from '@/types'

export interface TaskView {
  state: 'loading' | 'running' | 'ok' | 'failed' | 'gone'
  /** 生成分镜的百分比；还没进度为 null */
  pct?: number | null
  /** 出片：已出、共、在跑、失败的段数 */
  done?: number
  total?: number
  flying?: number
  failed?: number
  /** 合成进行到哪一步（服务端给的文字） */
  step?: string | null
  error?: string | null
}

export const TASK_POLL_MS: Record<AssistantTask['kind'], number> = { job: 1500, film: 5000, compose: 3000, export: 0 }

export function jobView(j: Job): TaskView {
  if (!TERMINAL.includes(j.status)) {
    const p = j.progress
    return { state: 'running', pct: p && p.total_chars ? Math.round((100 * p.done_chars) / p.total_chars) : null }
  }
  return j.status === 'failed' ? { state: 'failed', error: (j.error ?? '').split('\n')[0] || null } : { state: 'ok' }
}

export function filmView(s: FilmSession): TaskView {
  const count = (pred: (st: string) => boolean) => s.clips.filter((c) => pred(c.state)).length
  const v = { done: count((st) => st === 'done'), total: s.clips.length,
              flying: count((st) => (IN_FLIGHT as string[]).includes(st)), failed: count((st) => st === 'failed') }
  if (v.flying) return { state: 'running', ...v }
  return { state: v.failed ? 'failed' : 'ok', ...v }
}

export function composeView(s: FilmSession): TaskView {
  const f = s.final
  if (!f) return { state: 'gone' }
  if (f.state === 'queued' || f.state === 'running') return { state: 'running', step: f.step ?? null }
  return f.state === 'failed' ? { state: 'failed', error: f.error } : { state: 'ok' }
}

export function useTaskView(nid: string, task: AssistantTask): TaskView {
  const { kind, chapter_id: cid, version_id: vid, job_id: jobId } = task
  const [view, setView] = useState<TaskView>({ state: kind === 'export' ? 'ok' : 'loading' })
  useEffect(() => {
    if (kind === 'export') return
    let gone = false
    let timer: number | undefined
    const tick = async () => {
      let next: TaskView | null = null
      try {
        if (kind === 'job') next = jobView(await getJob(jobId ?? ''))
        else {
          const s = await getFilm(nid, cid, vid ?? '')
          next = kind === 'film' ? filmView(s) : composeView(s)
        }
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) next = { state: 'gone' }
      }
      if (gone) return
      if (next) setView(next)
      if (!next || next.state === 'running') timer = window.setTimeout(() => void tick(), TASK_POLL_MS[kind])
    }
    void tick()
    return () => { gone = true; window.clearTimeout(timer) }
  }, [nid, kind, cid, vid, jobId])
  return view
}
