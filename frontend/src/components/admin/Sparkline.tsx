/** 迷你折线：没有坐标轴，下方同色淡填充；只有一个点时画水平线。 */
export function Sparkline({ values }: { values: number[] }) {
  const W = 100
  const H = 32
  const pad = 2
  if (!values.length) return null
  const max = Math.max(...values)
  const min = Math.min(...values)
  const span = max - min || 1
  const x = (i: number) => (values.length === 1 ? 0 : (i * W) / (values.length - 1))
  // 全相同（含只有一个点）时画在中线
  const y = (v: number) => (max === min ? H / 2 : pad + (1 - (v - min) / span) * (H - 2 * pad))
  const pts = values.length === 1 ? [0, W].map((px) => [px, y(values[0])]) : values.map((v, i) => [x(i), y(v)])
  const line = pts.map(([px, py], i) => `${i ? 'L' : 'M'}${px.toFixed(1)} ${py.toFixed(1)}`).join('')
  const area = `${line}L${W} ${H}L0 ${H}Z`
  return (
    <svg data-testid="sparkline" aria-hidden="true" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none"
         width="100%" height={H} className="block">
      <path d={area} style={{ fill: 'var(--primary)', fillOpacity: 0.12, stroke: 'none' }} />
      <path d={line} fill="none" vectorEffect="non-scaling-stroke"
            style={{ stroke: 'var(--primary)', strokeWidth: 1.5 }} />
    </svg>
  )
}
