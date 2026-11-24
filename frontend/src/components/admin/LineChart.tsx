import { useId } from 'react'
import { tr } from '@/i18n/core'
import { usd } from './format'

interface Props {
  points: { label: string; value: number }[]
  height?: number
  label?: string
}

/** 手写 SVG 折线图：纵轴 0 到最大值，只标首尾日期与最大值。 */
export function LineChart({ points, height = 140, label = tr('admin.chart.label') }: Props) {
  const gradient = `adm-chart-${useId().replace(/:/g, '')}`
  if (!points.length) return <p className="adm__empty">{tr('admin.chart.empty')}</p>
  const W = 640
  const P = { l: 52, r: 12, t: 12, b: 24 }
  const max = Math.max(...points.map((p) => p.value), 0) || 1
  const x = (i: number) =>
    P.l + (points.length === 1 ? 0 : (i * (W - P.l - P.r)) / (points.length - 1))
  const y = (v: number) => P.t + (1 - v / max) * (height - P.t - P.b)
  const d = points.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(p.value).toFixed(1)}`).join('')
  const area = `${d} L${x(points.length - 1).toFixed(1)} ${height - P.b} L${x(0).toFixed(1)} ${height - P.b} Z`
  return (
    <svg className="adm__chart" viewBox={`0 0 ${W} ${height}`} role="img" aria-label={label}>
      <defs>
        <linearGradient id={gradient} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--content-blue)" stopOpacity=".28" />
          <stop offset="100%" stopColor="var(--content-blue)" stopOpacity=".015" />
        </linearGradient>
      </defs>
      {[0.33, 0.66].map((k) => (
        <line key={k} className="adm__grid" x1={P.l} x2={W - P.r}
              y1={P.t + (height - P.t - P.b) * k} y2={P.t + (height - P.t - P.b) * k} />
      ))}
      <line className="adm__axis" x1={P.l} x2={W - P.r} y1={height - P.b} y2={height - P.b} />
      <text className="adm__tick" x={P.l - 6} y={P.t + 4} textAnchor="end">{usd(max)}</text>
      <text className="adm__tick" x={P.l - 6} y={height - P.b} textAnchor="end">$0</text>
      <path className="adm__area" d={area} fill={`url(#${gradient})`} />
      <path className="adm__line" d={d} fill="none" />
      {points.map((p, i) => (
        <circle key={p.label} className="adm__dot" cx={x(i)} cy={y(p.value)} r={2.5}>
          <title>{`${p.label} ${usd(p.value)}`}</title>
        </circle>
      ))}
      <text className="adm__tick" x={P.l} y={height - 6}>{points[0].label}</text>
      <text className="adm__tick" x={W - P.r} y={height - 6} textAnchor="end">
        {points[points.length - 1].label}
      </text>
    </svg>
  )
}
