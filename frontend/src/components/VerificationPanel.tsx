import { useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import type { Finding, Storyboard, VerificationReport } from '../types'

interface Props {
  report: VerificationReport
  doc?: Storyboard | null
  /** 报告从哪来的，用于文案：保存后的检查 or 渲染前拦截 */
  origin?: 'save' | 'render'
}

const HARD: Finding['severity'][] = ['critical', 'high']

const SEVERITY_ZH: Record<string, string> = {
  critical: '致命', high: '严重', medium: '提醒', low: '提示',
}

/** JSON Pointer → 人话位置。
 *
 *  object_path 是给机器用的（修复 Agent 靠它打补丁），但人要拿它去屏幕上找那一镜，
 *  所以这里用当前文档把下标翻回集号镜号。翻不动就原样显示，不猜。 */
export function locate(path: string, doc?: Storyboard | null): string {
  const parts = path.split('/').filter(Boolean)
  if (parts[0] === 'source' && parts[1] === 'units' && parts[2] !== undefined) {
    const unit = doc?.source?.units?.[Number(parts[2])]
    return unit ? `原文 ${unit.id}` : `原文第 ${Number(parts[2]) + 1} 句`
  }
  if (parts[0] !== 'episodes' || parts[1] === undefined) return path
  const ep = doc?.episodes?.[Number(parts[1])]
  const epLabel = ep?.id ?? `第 ${Number(parts[1]) + 1} 集`
  if (parts[2] !== 'shots' || parts[3] === undefined) return epLabel
  const shot = ep?.shots?.[Number(parts[3])]
  const shotLabel = shot?.id ?? `第 ${Number(parts[3]) + 1} 镜`
  const rest = parts.slice(4)
  return rest.length ? `${epLabel} / ${shotLabel} · ${rest.join('.')}`
    : `${epLabel} / ${shotLabel}`
}

function FindingRow({ f, doc }: { f: Finding; doc?: Storyboard | null }) {
  return (
    <li className={`vf vf--${f.severity}`}>
      <div className="vf__head">
        <Badge variant={HARD.includes(f.severity) ? 'destructive' : 'secondary'}
               className={`vf__sev vf__sev--${f.severity}`}>
          {HARD.includes(f.severity) ? '硬性' : '提示'} · {SEVERITY_ZH[f.severity] ?? f.severity}
        </Badge>
        <span className="vf__rule">{f.rule_id}</span>
        <code className="vf__at">{locate(f.object_path, doc)}</code>
      </div>
      <p className="vf__msg">{f.message}</p>
      {f.evidence_quote && <p className="vf__quote">原文：{f.evidence_quote}</p>}
      {(f.expected !== undefined || f.actual !== undefined) && (
        <p className="vf__diff">
          应为 <code>{JSON.stringify(f.expected)}</code>
          {' → '}实为 <code>{JSON.stringify(f.actual)}</code>
        </p>
      )}
      {!!f.unit_refs?.length && (
        <p className="vf__units">涉及原文句：{f.unit_refs.join('、')}</p>
      )}
    </li>
  )
}

/** 完整性检查结果。
 *
 *  这份报告后端一直在算（每次保存、每次渲染前都整份检查），但界面上一直没透出来——
 *  用户改出一份不合法的 IR，屏幕照样显示保存成功，要到点渲染才被 422 打回。 */
export function VerificationPanel({ report, doc, origin = 'save' }: Props) {
  const [showSoft, setShowSoft] = useState(false)
  const hard = report.findings.filter((f) => HARD.includes(f.severity))
  const soft = report.findings.filter((f) => !HARD.includes(f.severity))
  const ok = report.status === 'verified'
  const cov = report.coverage

  if (ok && !soft.length) {
    return (
      <p className="vpanel vpanel--ok">
        <span className="vpanel__dot" aria-hidden />完整性检查通过{cov?.selected?.length
          ? `：${cov.selected.length} 句原文全部有着落`
          : ''}
        {cov?.waived?.length ? `（${cov.waived.length} 句已注明理由略过）` : ''}
      </p>
    )
  }

  return (
    <section className={`vpanel ${ok ? 'vpanel--warn' : 'vpanel--bad'}`}>
      <h3 className="vpanel__title">
        {ok ? '完整性检查通过，但有提示' : (origin === 'render'
          ? '完整性检查没通过，已拦在付费渲染之前'
          : '已保存，但没通过完整性检查')}
      </h3>
      {!ok && (
        <p className="vpanel__note">
          改动已经存下来了，不会丢。但在下面这
          {hard.length} 条修好之前，这份分镜不能进渲染。
        </p>
      )}
      {cov && !!cov.failed?.length && (
        <p className="vpanel__note">
          {cov.failed.length} 句原文没有任何镜头承载：{cov.failed.slice(0, 12).join('、')}
          {cov.failed.length > 12 ? ' …' : ''}
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
            {showSoft ? '收起' : `显示 ${soft.length} 条提示（不拦渲染）`}
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
