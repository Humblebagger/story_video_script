/** 章节头部：编号、标题、镜头数与时长、当前步骤；右侧预估 / 已花 / 上限三格。compact 是画布里的一行版。 */
import { StatusPill } from '@/components/common/StatusPill'
import { useI18n } from '@/i18n/core'
import { cny, fmtDuration } from '@/lib/fmt'
import type { FilmSession } from '@/types'
import type { StepId } from '@/workflow'

interface Props {
  /** 1 起 */
  num: number
  title: string
  shots: number | null
  /** 可播总时长（秒） */
  seconds: number | null
  step: StepId
  /** 生成中 */
  live: boolean
  film: FilmSession | null
  compact?: boolean
}

const epNo = (n: number) => `EP·${String(n).padStart(2, '0')}`

export function ChapterHeader({ num, title, shots, seconds, step, live, film, compact }: Props) {
  const { t } = useI18n()
  if (compact) {
    return (
      <div className="chead chead--compact" data-testid="chapter-head-compact">
        <span className="chead__num">{epNo(num)}</span>
        <span className="chead__title">{title}</span>
        {film && (
          <span className="chead__money">{cny(film.spent_cny)} / {cny(film.budget_cny)}</span>
        )}
      </div>
    )
  }
  const dur = fmtDuration(seconds)
  const cells: [string, string][] = [
    [t('flow.head.estimate'), film ? cny(film.clips.reduce((a, c) => a + c.estimate_cny, 0)) : '—'],
    [t('flow.head.spent'), film ? cny(film.spent_cny) : '—'],
    [t('flow.head.cap'), film ? cny(film.budget_cny) : '—'],
  ]
  return (
    <section className="chead" data-testid="chapter-head">
      <div className="chead__main">
        <span className="chead__num">{epNo(num)}</span>
        <div className="chead__text">
          <h2 className="chead__title">{title}</h2>
          <div className="chead__meta">
            {shots != null && <span className="chead__mono">{t('flow.head.shots', { n: shots })}</span>}
            {dur && <span className="chead__mono">{t('flow.head.about', { d: dur })}</span>}
            <StatusPill tone={live ? 'live' : 'idle'}>{t(`flow.steps.${step}`)}</StatusPill>
          </div>
        </div>
      </div>
      <div className="chead__cost">
        <div className="chead__cells">
          {cells.map(([label, value]) => (
            <div key={label} className="chead__cell" data-testid="cost-tile">
              <span className="chead__label">{label}</span>
              <span className="chead__value">{value}</span>
            </div>
          ))}
        </div>
        {!film && <span className="chead__label">{t('flow.head.noFilm')}</span>}
      </div>
    </section>
  )
}
