import { useState } from 'react'
import { renderPlan } from '../api'
import type { RenderPack, Storyboard } from '../types'

interface Props {
  doc: Storyboard
  runId: string | null
}

const CLIP_LENGTHS = [5, 10, 15]

function saveFile(name: string, text: string, mime = 'text/plain;charset=utf-8') {
  const url = URL.createObjectURL(new Blob([text], { type: mime }))
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  URL.revokeObjectURL(url)
}

/** 渲染任务包：把分镜 IR 变成能喂给视频模型的东西。
 *
 *  这一页刻意把「费用」放在最前面。按方舟公开资费，《药》这样一章 11 分钟的片子
 *  一次过就是三位数，抽卡到能用是四位数——在花钱之前先把提示词逐条看一遍，
 *  是这个界面存在的唯一理由。
 *
 *  出图排在出视频之前：资产图没出，就只能纯文生视频，每个镜头换一张脸，
 *  整套资产引用制的防漂移能力等于白做。 */
export function RenderView({ doc, runId }: Props) {
  const [pack, setPack] = useState<RenderPack | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [maxClip, setMaxClip] = useState(15)
  const [model, setModel] = useState('seedance-2.0')
  /** 拿真实账单标定过就填这里；空表示用推算值 */
  const [rate, setRate] = useState('')
  const [open, setOpen] = useState<string | null>(null)
  /** 只渲染选中的 clip。这是唯一真能把钱包住的手段——不动 IR，先渲一集看效果 */
  const [picked, setPicked] = useState<Set<string> | null>(null)

  const build = async (over: {
    maxClipSeconds?: number; model?: string; cnyPerSecond?: number | null
  } = {}) => {
    setBusy(true)
    setErr(null)
    try {
      setPicked(null)
      setPack(await renderPlan(doc, {
        maxClipSeconds: over.maxClipSeconds ?? maxClip,
        model: over.model ?? model,
        cnyPerSecond: over.cnyPerSecond !== undefined
          ? over.cnyPerSecond : (Number(rate) || null),
        runId,
      }))
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const plan = pack?.plan
  const chosen = plan
    ? plan.clips.filter((c) => !picked || picked.has(c.id))
    : []
  const chosenSec = Math.round(chosen.reduce((a, c) => a + c.playable_sec, 0) * 10) / 10
  const chosenCny = plan ? Math.round(chosenSec * plan.estimate.cny_per_second * 10) / 10 : 0
  const partial = !!picked && !!plan && chosen.length !== plan.clips.length
  const toggle = (id: string) => {
    const next = new Set(picked ?? plan!.clips.map((c) => c.id))
    if (next.has(id)) next.delete(id); else next.add(id)
    setPicked(next.size === plan!.clips.length ? null : next)
  }
  const onlyEpisode = (ep: string) => {
    setPicked(new Set(plan!.clips.filter((c) => c.episode === ep).map((c) => c.id)))
  }
  const stem = `${plan?.work_title || '分镜'}_${plan?.chapter || ''}`.replace(/[/\\:*?"<>|]/g, '_')

  return (
    <div className="rend">
      <header className="rend__head">
        <div>
          <h3>渲染任务包</h3>
          <p className="rend__hint">
            把分镜拆成视频模型能直接吃的 clip，附出图清单与费用估算。
            提示词与「生产包」Markdown 里那一段逐字相同——在这里核对过，发出去的就是它。
          </p>
        </div>
        <div className="rend__acts">
          <label className="rend__len">
            单 clip 上限
            <select value={maxClip} disabled={busy}
                    onChange={(e) => {
                      const v = Number(e.target.value)
                      setMaxClip(v)
                      void build({ maxClipSeconds: v })
                    }}>
              {CLIP_LENGTHS.map((s) => <option key={s} value={s}>{s} 秒</option>)}
            </select>
          </label>
          <label className="rend__len">
            费率档位
            <select value={model} disabled={busy}
                    onChange={(e) => { setModel(e.target.value); void build({ model: e.target.value }) }}>
              {(plan?.tiers ?? [{ id: 'seedance-2.0', label: 'Seedance 2.0（标准）' }])
                .map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
            </select>
          </label>
          <label className="rend__len" title="拿一次真实调用的账单标定后填这里，estimate 就不再是推算值">
            实测元/秒
            <input className="rend__rate" value={rate} placeholder="留空=推算"
                   inputMode="decimal" disabled={busy}
                   onChange={(e) => setRate(e.target.value)}
                   onBlur={() => plan && void build()} />
          </label>
          <button className="btn" disabled={busy} onClick={() => void build()}>
            {busy ? '组装中…' : plan ? '重新组装' : '生成任务包'}
          </button>
        </div>
      </header>

      {err && <p className="alert">{err}</p>}

      {!plan && !busy && !err && (
        <p className="empty">还没组装。点「生成任务包」看这一章要切成几个 clip、缺几张图、大概多少钱。</p>
      )}

      {plan && (
        <>
          <div className="rend__cost">
            <div className="rend__num">
              <b>{plan.estimate.clips}</b><span>个 clip</span>
            </div>
            <div className="rend__num">
              <b>{Math.round(plan.estimate.playable_seconds)}</b>
              <span>
                秒成片
                {plan.estimate.speech_overflow_sec > 0 &&
                  `（标称 ${Math.round(plan.estimate.seconds)}s，
                    含念完旁白必须补的 ${Math.round(plan.estimate.speech_overflow_sec)}s）`}
              </span>
            </div>
            <div className="rend__num rend__num--warn">
              <b>{plan.estimate.asset_images_missing}</b>
              <span>张资产图待出（共 {plan.estimate.asset_images_total}）</span>
            </div>
            <div className="rend__num rend__num--cost">
              <b>¥{partial ? chosenCny : plan.estimate.cny_once}–{
                partial ? Math.round(chosenCny * plan.estimate.retry_factor * 10) / 10
                        : plan.estimate.cny_with_retries}</b>
              <span>
                {plan.estimate.calibrated ? '费用' : '费用估算'}
                （一次过 → 抽 {plan.estimate.retry_factor} 次）
                {partial && ` · 仅选中的 ${chosen.length}/${plan.clips.length} 条`}
              </span>
            </div>
          </div>
          <details className="rend__basis">
            <summary>
              {plan.estimate.calibrated
                ? `按你指定的 ${plan.estimate.cny_per_second} 元/秒 计算`
                : `按 ${plan.estimate.model_label} 推算 ${plan.estimate.cny_per_second} 元/秒`}
              —— 这是估算，点开看依据与不确定性
            </summary>
            <p className="rend__note">{plan.estimate.note}</p>
            <ul className="rend__caveats">
              {plan.estimate.caveats.map((c) => <li key={c}>{c}</li>)}
            </ul>
            <p className="rend__note">
              档位适用分辨率：{plan.estimate.resolutions}；
              费率 {plan.estimate.rate.cny_per_million_tokens} 元/百万 token ×
              {plan.estimate.rate.tokens_per_second} token/秒。
            </p>
          </details>

          {plan.estimate.asset_images_missing > 0 && (
            <p className="rend__warn">
              还有 <b>{plan.estimate.asset_images_missing}</b> 张资产图没出。
              直接文生视频的话，同一个角色在不同 clip 里会换脸——
              资产引用制防的就是这个。建议先按下面的出图清单把图出好，
              填回资产卡的「设定图」，再来生成视频。
            </p>
          )}

          <div className="rend__dl">
            <button className="btn btn--sm" onClick={() => saveFile(
              `${stem}_渲染任务清单${partial ? `_选中${chosen.length}条` : ''}.json`,
              JSON.stringify(partial ? { ...plan, clips: chosen } : plan, null, 2),
              'application/json;charset=utf-8')}>
              下载任务清单 JSON
            </button>
            {pack!.packs.map((p) => (
              <button className="btn btn--sm btn--ghost" key={p.episode}
                      onClick={() => saveFile(`${stem}_${p.episode}_生产包.md`, p.markdown)}>
                下载 {p.episode} 生产包
              </button>
            ))}
          </div>

          <h4 className="rend__sub">出图清单（{plan.assets.length} 张卡）</h4>
          <ul className="rend__assets">
            {plan.assets.map((a) => (
              <li className="rasset" key={a.id}>
                <div className="rasset__top">
                  <span className="rasset__id">{a.id}</span>
                  <b>{a.name}</b>
                  <span className="tag">{a.kind_zh}</span>
                  <span className={`rasset__imgs${
                    a.have_images >= a.need_images ? ' is-ok' : ''}`}>
                    {a.have_images}/{a.need_images} 张图
                  </span>
                </div>
                <p className="rasset__prompt">{a.image_prompt}</p>
                {a.variants.map((v) => (
                  <p className="rasset__var" key={v.id}>
                    <span>{v.id}</span>{v.description}
                  </p>
                ))}
                {!!a.constraints.length && (
                  <p className="rasset__cons">不要：{a.constraints.join('；')}</p>
                )}
              </li>
            ))}
          </ul>

          <div className="rend__pick">
            <h4 className="rend__sub">
              分镜 clip（{partial ? `选中 ${chosen.length}/${plan.clips.length}`
                                 : plan.clips.length} 条 · {chosenSec}s · ¥{chosenCny}）
            </h4>
            <span className="rend__eps">
              只渲染：
              {[...new Set(plan.clips.map((c) => c.episode))].map((ep) => (
                <button className="btn btn--sm btn--ghost" key={ep}
                        onClick={() => onlyEpisode(ep)}>{ep}</button>
              ))}
              <button className="btn btn--sm btn--ghost"
                      onClick={() => setPicked(null)}>全选</button>
            </span>
          </div>
          <ul className="rend__clips">
            {plan.clips.map((c) => (
              <li className={`rclip${picked && !picked.has(c.id) ? ' is-off' : ''}`} key={c.id}>
                <span className="rclip__pick">
                  <input type="checkbox" checked={!picked || picked.has(c.id)}
                         title="不勾就不渲染这一条"
                         onChange={() => toggle(c.id)} />
                </span>
                <button className="rclip__head" onClick={() =>
                  setOpen(open === c.id ? null : c.id)}>
                  <span className="rclip__id">{c.id}</span>
                  <span className="rclip__dur" title={c.speech_overflow > 0
                    ? `标称 ${c.duration_sec}s，念完旁白需 ${c.playable_sec}s` : ''}>
                    {c.playable_sec}s
                    {c.speech_overflow > 0 && <em className="rclip__over">+{c.speech_overflow}</em>}
                  </span>
                  <span className="rclip__shots">{c.shots.join(' + ')}</span>
                  <span className="rclip__refs">垫图 {c.reference_assets.join('、') || '无'}</span>
                  <span className="rclip__caret">{open === c.id ? '收起' : '看提示词'}</span>
                </button>
                {open === c.id && <pre className="rclip__prompt">{c.prompt}</pre>}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}
