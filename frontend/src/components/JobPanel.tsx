import { useEffect, useRef } from 'react'
import { JOB_STATUS, label } from '../labels'
import type { Job } from '../types'
import { JobProgress } from './JobProgress'
import { VerificationPanel } from './VerificationPanel'

interface Props {
  job: Job
  onReset: () => void
  /** 转换在后台线程池里跑，离开本页不会中断 */
  onBackground: () => void
  /** 已完成批次的预览是否已经打开 */
  previewing?: boolean
  onPreview?: () => void
}

export function JobPanel({ job, onReset, onBackground, previewing, onPreview }: Props) {
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
              放到后台
            </button>
          </>
        ) : (
          <button className="btn btn--sm btn--ghost" onClick={onReset}>关闭任务面板</button>
        )}
      </header>

      {running && job.progress && <JobProgress progress={job.progress} />}

      {/* 长章节要跑好几分钟：已完成的批次先给人看。失败时同样给，已通过的批次不白跑 */}
      {!!job.partial_batches && (running || job.status === 'failed') && !previewing && onPreview && (
        <div className="job__partial">
          <span>
            {running
              ? `已完成 ${job.partial_batches} 批，可以先审阅，整章跑完后自动换成完整产物`
              : `转换失败，但前 ${job.partial_batches} 批已通过校验`}
          </span>
          <button className="btn btn--sm" onClick={onPreview}>
            {running ? `先审阅已完成的 ${job.partial_batches} 批` : `查看已通过的 ${job.partial_batches} 批`}
          </button>
        </div>
      )}

      {job.status === 'failed' && job.error && (
        <div className="job__warn job__warn--err">
          <b>✕ 转换失败，未通过的原因如下</b>
          <pre className="job__err">{job.error}</pre>
        </div>
      )}

      {/* 转换本身也过验证链路。跑通了要说一声（证明这条链真跑了），
          没跑通要给逐条原因，而不是只丢一段报错文本 */}
      {!running && job.verification && (
        <VerificationPanel report={job.verification} doc={job.result} />
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
