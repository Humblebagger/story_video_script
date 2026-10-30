import { adminOverview } from '../../api'
import { int, usd } from './format'
import { LineChart } from './LineChart'
import { useLoad } from './useLoad'

/** 概览：几张数字卡片 + 近 30 天每日金额；打开时每 30 秒刷新。 */
export function Overview() {
  const { data, error } = useLoad(adminOverview, [], 30000)
  if (error) return <p className="adm__err">{error}</p>
  if (!data) return <p className="adm__empty">加载中…</p>
  const cards: [string, string][] = [
    ['用户', int(data.users)], ['7 天活跃', int(data.active_7d)],
    ['30 天 token', int(data.tokens_30d)], ['30 天金额', usd(data.cost_30d)],
    ['运行中任务', int(data.running)], ['7 天失败', int(data.failed_7d)],
  ]
  return (
    <section className="adm__sec">
      <div className="adm__cards">
        {cards.map(([k, v]) => (
          <div key={k} className="adm__card"><b>{v}</b><span>{k}</span></div>
        ))}
      </div>
      {data.unpriced_models.length > 0 && (
        <p className="adm__warn">
          未定价模型：{data.unpriced_models.join('、')}（不计入金额，可在「用量」页编辑价格表）
        </p>
      )}
      <h3 className="adm__h">近 30 天每日金额</h3>
      <LineChart points={data.daily.map((d) => ({ label: d.day.slice(5), value: d.cost_usd }))} />
      <p className="adm__note">金额按当前价格表估算。</p>
    </section>
  )
}
