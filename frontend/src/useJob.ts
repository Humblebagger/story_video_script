/** 提交转换 + 轮询任务。
 *
 *  转换是分钟级任务且在后台线程池里跑：**关掉页面转换照常继续**。
 *  所以这里除了 start 还提供 attach——回到页面时重新接上仍在跑的任务，
 *  完成时通过 onDone 回调触发桌面通知。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { getJob, submitConvert, TERMINAL } from './api'
import type { ConvertRequest, Job } from './types'

const POLL_MS = 1500

export function useJob(onDone?: (job: Job) => void) {
  const [job, setJob] = useState<Job | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const timer = useRef<number | null>(null)
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
    const tick = async () => {
      try {
        const next = await getJob(jobId)
        setJob(next)
        if (TERMINAL.includes(next.status)) {
          stop()
          doneRef.current?.(next)
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
        stop()
      }
    }
    timer.current = window.setInterval(tick, POLL_MS)
    void tick()
  }, [stop])

  const start = useCallback(async (payload: ConvertRequest) => {
    setError(null)
    setSubmitting(true)
    try {
      const { job_id } = await submitConvert(payload)
      setJob({ id: job_id, status: 'queued', log: [], result: null,
               quality_report: null, error: null,
               work_title: payload.work_title, chapter: payload.chapter })
      poll(job_id)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
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
    stop()
    setJob(null)
    setError(null)
  }, [stop])

  return { job, error, submitting, start, attach, reset }
}
