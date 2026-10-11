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
  const total = p.total_chars || 1
  const done = Math.min(1, p.done_chars / total)
  const current = p.phase === 'done' || p.phase === 'merging'
    ? 0 : Math.min(1 - done, (p.batch_chars ?? 0) / total)
  const phase = label(PHASE, p.phase)
  const where = p.batch
    ? `批 ${p.batch}/${p.batches}` + (p.attempt
      ? ` · 第 ${p.attempt} 次尝试（最多 ${p.max_attempts}）` : '')
    : `共 ${p.batches} 批`
  const time = [
    p.elapsed_sec != null ? `已用 ${fmtDuration(p.elapsed_sec)}` : null,
    p.eta_sec != null ? `预计还需${fmtEta(p.eta_sec)}`
      : p.phase !== 'done' && p.phase !== 'merging' && !p.done_chars
        ? '第一批完成后估算剩余时间' : null,
  ].filter(Boolean).join(' · ')

  if (compact) {
    // 侧栏窄，只留批次、阶段与剩余时间；尝试次数在任务面板里看
    const batch = p.batch ? `批 ${p.batch}/${p.batches}` : `共 ${p.batches} 批`
    return (
      <p className="jprog__compact">
        {batch} · {phase}{p.eta_sec != null ? ` · 还需${fmtEta(p.eta_sec)}` : ''}
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
