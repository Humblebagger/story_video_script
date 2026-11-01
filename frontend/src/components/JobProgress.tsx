import { useI18n } from '@/i18n/core'
import { fmtDuration, fmtEta, label, PHASE } from '../labels'
import type { JobProgress as Progress } from '../types'

interface Props {
  progress: Progress
  /** 侧栏用的单行精简版 */
  compact?: boolean
}

/** 转换进度：批次 / 尝试 / 阶段 + 已用与预计剩余时间。
 *
 *  进度条实心段是已完成的批次（按字数），浅色脉动段是正在跑的这一批——
 *  一批之内走到哪一步没法按比例算，就不画假的百分比。 */
export function JobProgress({ progress: p, compact }: Props) {
  const { t } = useI18n()
  const total = p.total_chars || 1
  const done = Math.min(1, p.done_chars / total)
  const current = p.phase === 'done' || p.phase === 'merging'
    ? 0 : Math.min(1 - done, (p.batch_chars ?? 0) / total)
  const phase = label(PHASE, p.phase)
  const where = p.batch
    ? t('job.batch', { b: p.batch, n: p.batches }) + (p.attempt
      ? t('job.attempt', { a: p.attempt, max: p.max_attempts }) : '')
    : t('job.batchTotal', { n: p.batches })
  const time = [
    p.elapsed_sec != null ? t('job.elapsed', { t: fmtDuration(p.elapsed_sec) }) : null,
    p.eta_sec != null ? t('job.eta', { t: fmtEta(p.eta_sec) })
      : p.phase !== 'done' && p.phase !== 'merging' && !p.done_chars
        ? t('job.etaWait') : null,
  ].filter(Boolean).join(' · ')

  if (compact) {
    // 侧栏窄，只留批次、阶段与剩余时间；尝试次数在任务面板里看
    const batch = p.batch ? t('job.batch', { b: p.batch, n: p.batches }) : t('job.batchTotal', { n: p.batches })
    return (
      <p className="jprog__compact">
        {batch} · {phase}{p.eta_sec != null ? ` · ${t('job.etaShort', { t: fmtEta(p.eta_sec) })}` : ''}
      </p>
    )
  }
  return (
    <div className="jprog">
      <div className="jprog__bar" role="progressbar"
           aria-valuemin={0} aria-valuemax={100}
           aria-valuenow={Math.round(done * 100)}>
        <span className="jprog__done" style={{ width: `${done * 100}%` }} />
        <span className="jprog__cur" style={{ width: `${current * 100}%` }} />
      </div>
      <div className="jprog__line">
        <b>{phase}</b>
        <span>{where}</span>
        {time && <span className="jprog__time">{time}</span>}
      </div>
    </div>
  )
}
