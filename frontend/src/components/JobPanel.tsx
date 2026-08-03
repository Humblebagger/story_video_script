import { useEffect, useRef } from 'react'
import { JOB_STATUS, label } from '../labels'
import type { Job } from '../types'

interface Props {
  job: Job
  onReset: () => void
  /** 转换在后台线程池里跑，离开本页不会中断 */
  onBackground: () => void
}

export function JobPanel({ job, onReset, onBackground }: Props) {
  const logRef = useRef<HTMLPreElement>(null)
  const running = job.status === 'queued' || job.status === 'running'

  useEffect(() => {
    const el = logRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [job.log.length])

  return (
    <section className={`job job--${job.status}`}>
      <header className="job__head">
        <span className={`dot${running ? ' dot--live' : ''}`} />
        <b>{label(JOB_STATUS, job.status)}</b>
        <code className="job__id">{job.id}</code>
        {running ? (
          <>
            <span className="job__hint">
              分钟级任务，可以离开本页——转换在后台继续，完成后桌面通知你
            </span>
            <button className="btn btn--sm btn--ghost" onClick={onBackground}>
              放到后台，去开新转换
            </button>
          </>
        ) : (
          <button className="btn btn--sm btn--ghost" onClick={onReset}>新建转换</button>
        )}
      </header>

      {job.status === 'failed' && job.error && (
        <div className="job__warn job__warn--err">
          <b>✕ 转换失败，未通过的原因如下</b>
          <pre className="job__err">{job.error}</pre>
        </div>
      )}

      {job.quality_report && (
        <div className="job__warn">
          <b>⚠ 质量告警（已择优降级交付）</b>
          <pre>{job.quality_report}</pre>
        </div>
      )}

      {!!job.log.length && (
        <pre className="job__log" ref={logRef}>
          {job.log.join('\n')}
        </pre>
      )}
    </section>
  )
}
