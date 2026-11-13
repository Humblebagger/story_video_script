import { useEffect, useRef } from 'react'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/i18n/core'
import { formatMsg } from '@/i18n/serverMsg'
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
  const { t, locale } = useI18n()
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
            <span className="job__hint">{t('job.hint')}</span>
            <Button variant="outline" size="sm" onClick={onBackground}>{t('job.background')}</Button>
          </>
        ) : (
          <Button variant="outline" size="sm" onClick={onReset}>{t('job.dismiss')}</Button>
        )}
      </header>

      {running && job.progress && <JobProgress progress={job.progress} />}

      {/* 长章节要跑好几分钟：已完成的批次先给人看。失败时同样给，已通过的批次不白跑 */}
      {!!job.partial_batches && (running || job.status === 'failed') && !previewing && onPreview && (
        <div className="job__partial">
          <span>
            {running
              ? t('job.partialRunning', { n: job.partial_batches })
              : t('job.partialFailed', { n: job.partial_batches })}
          </span>
          <Button size="sm" onClick={onPreview}>
            {running ? t('job.previewRunning', { n: job.partial_batches }) : t('job.previewFailed', { n: job.partial_batches })}
          </Button>
        </div>
      )}

      {job.status === 'failed' && job.error && (
        <div className="job__warn job__warn--err">
          <b>{t('job.failedTitle')}</b>
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
          <b>{t('job.qualityTitle')}</b>
          <pre>{job.quality_report}</pre>
        </div>
      )}

      {!!job.log.length && (
        <pre className="job__log" ref={logRef}>
          {job.log.map((line, i) => (
            <span key={i} className={i === job.log.length - 1 ? 'job__logline--last' : undefined}>
              {formatMsg(line, locale)}{i < job.log.length - 1 ? '\n' : ''}
            </span>
          ))}
        </pre>
      )}
    </section>
  )
}
