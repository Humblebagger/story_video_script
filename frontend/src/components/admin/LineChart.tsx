import { usd } from './format'

interface Props {
  points: { label: string; value: number }[]
  height?: number
  label?: string
}

/** 手写 SVG 折线图：纵轴 0 到最大值，只标首尾日期与最大值。 */
export function LineChart({ points, height = 140, label = '每日金额' }: Props) {
  if (!points.length) return <p className="adm__empty">暂无数据</p>
  const W = 640
  const P = { l: 52, r: 12, t: 12, b: 24 }
  const max = Math.max(...points.map((p) => p.value), 0) || 1
  const x = (i: number) =>
    P.l + (points.length === 1 ? 0 : (i * (W - P.l - P.r)) / (points.length - 1))
  const y = (v: number) => P.t + (1 - v / max) * (height - P.t - P.b)
  const d = points.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(p.value).toFixed(1)}`).join('')
  return (
    <svg className="adm__chart" viewBox={`0 0 ${W} ${height}`} role="img" aria-label={label}>
      <line className="adm__axis" x1={P.l} x2={W - P.r} y1={height - P.b} y2={height - P.b} />
      <text className="adm__tick" x={P.l - 6} y={P.t + 4} textAnchor="end">{usd(max)}</text>
      <text className="adm__tick" x={P.l - 6} y={height - P.b} textAnchor="end">$0</text>
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
