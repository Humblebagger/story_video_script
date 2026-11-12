/** 提交转换 + 轮询任务。
 *
 *  转换是分钟级任务且在后台线程池里跑：**关掉页面转换照常继续**。
 *  所以这里除了 start 还提供 attach——回到页面时重新接上仍在跑的任务，
 *  完成时通过 onDone 回调触发桌面通知。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { getJob, TERMINAL } from './api'
import type { Job } from './types'

const POLL_MS = 1500

export function useJob(onDone?: (job: Job) => void) {
  const [job, setJob] = useState<Job | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const timer = useRef<number | null>(null)
  /** 轮询代：reset / 重新 attach / 重新 start 都会换代，旧代的迟到响应一律丢弃 */
  const gen = useRef(0)
  const doneRef = useRef(onDone)
  doneRef.current = onDone

  const stop = useCallback(() => {
    if (timer.current !== null) {
      clearInterval(timer.current)
      timer.current = null
    }
  }, [])

  useEffect(() => stop, [stop])

  const poll = useCallback((jobId: string) => {
    stop()
    const mine = ++gen.current
    const tick = async () => {
      try {
        const next = await getJob(jobId)
        if (gen.current !== mine) return
        setJob(next)
        if (TERMINAL.includes(next.status)) {
          stop()
          doneRef.current?.(next)
        }
      } catch (e) {
        if (gen.current !== mine) return
        setError(e instanceof Error ? e.message : String(e))
        stop()
      }
    }
    timer.current = window.setInterval(tick, POLL_MS)
    void tick()
  }, [stop])

  /** submit 发起一次转换（如 convertChapter），返回任务 id；meta 用于任务面板的标题 */
  const start = useCallback(async (submit: () => Promise<{ job_id: string }>,
                                   meta: { work_title: string; chapter: string }) => {
    setError(null)
    setSubmitting(true)
    const before = gen.current
    try {
      const { job_id } = await submit()
      // 提交途中被 reset / 换章了：任务照常在后台跑（侧栏巡检会发现），但不再接到当前页面
      if (gen.current !== before) return
      setJob({ id: job_id, status: 'queued', log: [], result: null,
               quality_report: null, error: null, ...meta })
      poll(job_id)
    } catch (e) {
      if (gen.current === before) setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSubmitting(false)
    }
  }, [poll])

  /** 接上一个已存在的任务（页面重开、或从侧栏点进在跑的任务） */
  const attach = useCallback((jobId: string) => {
    setError(null)
    poll(jobId)
  }, [poll])

  const reset = useCallback(() => {
    gen.current += 1
    stop()
    setJob(null)
    setError(null)
  }, [stop])

  return { job, error, submitting, start, attach, reset }
}
