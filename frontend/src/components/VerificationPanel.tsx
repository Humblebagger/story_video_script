import { useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import type { Finding, Storyboard, VerificationReport } from '../types'
import { tr, useI18n } from '@/i18n/core'
import { findingText } from '@/i18n/serverMsg'
import type { MsgKey } from '@/i18n/core'

interface Props {
  report: VerificationReport
  doc?: Storyboard | null
  /** 报告从哪来的，用于文案：保存后的检查 or 渲染前拦截 */
  origin?: 'save' | 'render'
}

const HARD: Finding['severity'][] = ['critical', 'high']

const SEVERITIES = ['critical', 'high', 'medium', 'low']

/** JSON Pointer → 人话位置。
 *
 *  object_path 是给机器用的（修复 Agent 靠它打补丁），但人要拿它去屏幕上找那一镜，
 *  所以这里用当前文档把下标翻回集号镜号。翻不动就原样显示，不猜。 */
export function locate(path: string, doc?: Storyboard | null): string {
  const parts = path.split('/').filter(Boolean)
  if (parts[0] === 'source' && parts[1] === 'units' && parts[2] !== undefined) {
    const unit = doc?.source?.units?.[Number(parts[2])]
    return unit ? tr('verify.unitAt', { id: unit.id }) : tr('verify.unitNth', { n: Number(parts[2]) + 1 })
  }
  if (parts[0] !== 'episodes' || parts[1] === undefined) return path
  const ep = doc?.episodes?.[Number(parts[1])]
  const epLabel = ep?.id ?? tr('verify.epNth', { n: Number(parts[1]) + 1 })
  if (parts[2] !== 'shots' || parts[3] === undefined) return epLabel
  const shot = ep?.shots?.[Number(parts[3])]
  const shotLabel = shot?.id ?? tr('verify.shotNth', { n: Number(parts[3]) + 1 })
  const rest = parts.slice(4)
  return rest.length ? `${epLabel} / ${shotLabel} · ${rest.join('.')}`
    : `${epLabel} / ${shotLabel}`
}

function FindingRow({ f, doc }: { f: Finding; doc?: Storyboard | null }) {
  const { t, locale } = useI18n()
  return (
    <li className={`vf vf--${f.severity}`}>
      <div className="vf__head">
        <Badge variant={HARD.includes(f.severity) ? 'destructive' : 'secondary'}
               className={`vf__sev vf__sev--${f.severity}`}>
          {HARD.includes(f.severity) ? t('verify.hard') : t('verify.soft')} · {SEVERITIES.includes(f.severity) ? t(`verify.severity.${f.severity}` as MsgKey) : f.severity}
        </Badge>
        <span className="vf__rule">{f.rule_id}</span>
        <code className="vf__at">{locate(f.object_path, doc)}</code>
      </div>
      <p className="vf__msg">{findingText(f, locale)}</p>
      {f.evidence_quote && <p className="vf__quote">{t('verify.quote', { q: f.evidence_quote })}</p>}
      {(f.expected !== undefined || f.actual !== undefined) && (
        <p className="vf__diff">
          {t('verify.expected')}{' '}<code>{JSON.stringify(f.expected)}</code>
          {' → '}{t('verify.actual')}{' '}<code>{JSON.stringify(f.actual)}</code>
        </p>
      )}
      {!!f.unit_refs?.length && (
        <p className="vf__units">{t('verify.units', { list: f.unit_refs.join(t('common.listSep')) })}</p>
      )}
    </li>
  )
}

/** 完整性检查结果。
 *
 *  这份报告后端一直在算（每次保存、每次渲染前都整份检查），但界面上一直没透出来——
 *  用户改出一份不合法的 IR，屏幕照样显示保存成功，要到点渲染才被 422 打回。 */
export function VerificationPanel({ report, doc, origin = 'save' }: Props) {
  const { t } = useI18n()
  const [showSoft, setShowSoft] = useState(false)
  const hard = report.findings.filter((f) => HARD.includes(f.severity))
  const soft = report.findings.filter((f) => !HARD.includes(f.severity))
  const ok = report.status === 'verified'
  const cov = report.coverage

  if (ok && !soft.length) {
    return (
      <p className="vpanel vpanel--ok">
        <span className="vpanel__dot" aria-hidden />{t('verify.passed')}{cov?.selected?.length
          ? t('verify.allCovered', { n: cov.selected.length })
          : ''}
        {cov?.waived?.length ? t('verify.waived', { n: cov.waived.length }) : ''}
      </p>
    )
  }

  return (
    <section className={`vpanel ${ok ? 'vpanel--warn' : 'vpanel--bad'}`}>
      <h3 className="vpanel__title">
        {ok ? t('verify.titleWarn') : (origin === 'render'
          ? t('verify.titleRender')
          : t('verify.titleSave'))}
      </h3>
      {!ok && (
        <p className="vpanel__note">
          {t('verify.note', { n: hard.length })}
        </p>
      )}
      {cov && !!cov.failed?.length && (
        <p className="vpanel__note">
          {t('verify.failed', { n: cov.failed.length, list: cov.failed.slice(0, 12).join(t('common.listSep')) })}
          {cov.failed.length > 12 ? t('verify.more') : ''}
        </p>
      )}
      {!!hard.length && (
        <ul className="vf__list">
          {hard.map((f, i) => <FindingRow key={`${f.rule_id}-${i}`} f={f} doc={doc} />)}
        </ul>
      )}
      {!!soft.length && (
        <>
          <Button type="button" variant="ghost" size="sm"
            onClick={() => setShowSoft(!showSoft)}>
            {showSoft ? t('verify.hide') : t('verify.show', { n: soft.length })}
          </Button>
          {showSoft && (
            <ul className="vf__list">
              {soft.map((f, i) => <FindingRow key={`${f.rule_id}-${i}`} f={f} doc={doc} />)}
            </ul>
          )}
        </>
      )}
    </section>
  )
}
