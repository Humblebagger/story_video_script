/** 画布侧栏「出片」页：设置、前置检查、总览与主按钮、选中段详情、花钱前的确认框，最后是配音与合成（ComposePanel）。
 *
 *  花钱的按钮上都写着金额；批量和超过确认线的单段先弹确认（useFilm 决定发不发请求）。
 *  有未保存的改动或验证门没过时，所有出片按钮禁用并写明原因。 */
import { useEffect, useState } from 'react'
import { ATTEMPT_STATE, AUDIO_MODE, FILM_STATE, label } from '../labels'
import { batchSummary, firstFrameText, inFlight, mainAction, precheck } from '../film'
import type { Film } from '../useFilm'
import { ComposePanel } from './ComposePanel'
import type { AudioMode, FilmClip, FilmSession, FilmSettings } from '../types'

const yuan = (n: number) => `¥${n.toFixed(2)}`
const p2 = (n: number) => String(n).padStart(2, '0')
/** 尝试时间按本地时区显示到分钟 */
const when = (iso: string) => {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso
    : `${p2(d.getMonth() + 1)}-${p2(d.getDate())} ${p2(d.getHours())}:${p2(d.getMinutes())}`
}

interface Props {
  film: Film
  /** 「成片」泳道上选中的段 */
  selected: string | null
  /** 点段里的镜头：画布选中那一镜 */
  onPickShot: (shotId: string) => void
  /** 有未保存的改动：出片只认已保存的版本 */
  dirty: boolean
}

export function FilmPanel({ film, selected, onPickShot, dirty }: Props) {
  const s = film.session
  if (film.status === 'loading') return <p className="tlc__kfnote">读取出片会话…</p>
  const blocked = dirty ? '有未保存的修改：先保存再出片（出片只用已保存的版本）'
    : film.gate ? `${film.gate}：先在分镜页修好再出片` : null
  const clip = s?.clips.find((c) => c.id === selected)
  return (
    <div className="film">
      {film.error && <p className="tlc__kferr">{film.error}</p>}
      {blocked && <p className="tlc__notice">{blocked}</p>}
      {film.confirm && s && <ConfirmBox s={s} film={film} blocked={blocked} />}
      {!s ? (
        <section>
          <p className="tlc__kfnote">按厂商能力把镜头切成段、组装提示词（不花钱）；先试一段，满意后再出剩余各段。</p>
          <button className="btn btn--sm" disabled={!!blocked || film.busy} onClick={() => void film.create()}>
            建立出片会话（不花钱）
          </button>
        </section>
      ) : (
        <>
          <Settings key={[s.provider, s.model, s.resolution, s.audio_mode, s.budget_cny, s.confirm_over_cny].join('|')}
                    s={s} film={film} />
          <Precheck s={s} gateOk={!film.gate} />
          <Overview s={s} film={film} selected={selected} blocked={blocked} />
          {clip
            ? <ClipDetail key={clip.id} c={clip} film={film} blocked={blocked} onPickShot={onPickShot} />
            : <p className="tlc__kfnote">点「成片」泳道上的一段看详情、重做或换用别的一次。</p>}
          <ComposePanel film={film} dirty={dirty} />
        </>
      )}
    </div>
  )
}

/** 设置：首次展开，出过片后折叠。改了才能「应用设置」；有段在跑时不能改 */
function Settings({ s, film }: { s: FilmSession; film: Film }) {
  const [draft, setDraft] = useState<FilmSettings>({})
  const val = <K extends keyof FilmSettings>(k: K) => draft[k] ?? s[k]
  const flying = s.clips.some(inFlight)
  const tried = s.clips.some((c) => c.attempts.some((a) => a.state === 'succeeded'))
  const otherProvider = !!draft.provider && draft.provider !== s.provider
  return (
    <details className="film__settings" open={!tried}>
      <summary>
        设置 · {s.options.models[s.model]?.label ?? s.model} · {s.resolution} · {label(AUDIO_MODE, s.audio_mode)}
        {' '}· 上限 {yuan(s.budget_cny)}
      </summary>
      <label className="field">
        <span>厂商</span>
        <select value={val('provider')}
                onChange={(e) => setDraft({ ...draft, provider: e.target.value, model: undefined, resolution: undefined })}>
          {[...new Set([s.provider, ...s.options.providers])].map((p) => <option key={p} value={p}>{p}</option>)}
        </select>
      </label>
      {otherProvider ? (
        <p className="tlc__kfnote">换厂商后档位与分辨率先用它的默认值，应用后再细调。</p>
      ) : (
        <>
          <label className="field">
            <span>档位</span>
            <select value={val('model')}
                    onChange={(e) => setDraft({ ...draft, model: e.target.value, resolution: undefined })}>
              {Object.entries(s.options.models).map(([id, m]) => <option key={id} value={id}>{m.label}</option>)}
            </select>
          </label>
          <label className="field">
            <span>分辨率</span>
            <select value={val('resolution')} onChange={(e) => setDraft({ ...draft, resolution: e.target.value })}>
              {s.options.resolutions.map((r) => {
                const price = s.options.cny_per_sec[r]
                return <option key={r} value={r}>{`${r}${price !== undefined ? `（约 ¥${price}/秒）` : ''}`}</option>
              })}
            </select>
          </label>
        </>
      )}
      <label className="field">
        <span>声音</span>
        <select value={val('audio_mode')}
                onChange={(e) => setDraft({ ...draft, audio_mode: e.target.value as AudioMode })}>
          {s.options.audio_modes.map((m) => <option key={m} value={m}>{label(AUDIO_MODE, m)}</option>)}
        </select>
      </label>
      <label className="field">
        <span>上限（元，按版本计）</span>
        <input type="number" min={1} step={10} value={val('budget_cny')}
               onChange={(e) => setDraft({ ...draft, budget_cny: Number(e.target.value) })} />
      </label>
      <label className="field">
        <span>单段超过多少元先确认</span>
        <input type="number" min={0} step={5} value={val('confirm_over_cny')}
               onChange={(e) => setDraft({ ...draft, confirm_over_cny: Number(e.target.value) })} />
      </label>
      <p className="tlc__kfnote">
        音色分配在配音与合成那一步做。改设置会按新设置重新切段（不花钱），已出的段标「过期」，旧视频仍可播。
      </p>
      <button className="btn btn--sm" disabled={!Object.keys(draft).length || flying || film.busy}
              onClick={() => void film.saveSettings(draft)}>
        应用设置
      </button>
      {flying && <p className="tlc__kfnote">有段在排队或生成中，等它们结束再改设置。</p>}
    </details>
  )
}

/** 前置检查：待核对的段、缺参考图的资产、被裁 / 截断的段 */
function Precheck({ s, gateOk }: { s: FilmSession; gateOk: boolean }) {
  const p = precheck(s)
  const passed = gateOk ? <p className="tlc__kfnote">验证门：已通过</p> : null
  if (!s.uncertain_count && !p.missing.length && !p.trimmed.length && !p.truncated.length) return passed
  return (
    <section className="film__check">
      {passed}
      {!!s.uncertain_count && (
        <p className="tlc__kferr">
          {s.uncertain_count} 段结果不明：厂商那边可能还有任务在跑或已扣费，请到厂商控制台核对；
          批量出片会跳过它们，确认没有生成再单独重做。
        </p>
      )}
      {!!p.missing.length && <p>缺参考图的资产（只写文字描述）：{p.missing.join('、')}</p>}
      {!!p.trimmed.length && <p>⚠ 参考图超出名额被裁的段：{p.trimmed.join('、')}</p>}
      {!!p.truncated.length && <p>✂ 超出单段上限被截断的段：{p.truncated.join('、')}</p>}
    </section>
  )
}

/** 总览：各状态计数、钱（已花 / 在跑预留 / 剩余预估 / 上限）、主按钮 */
function Overview({ s, film, selected, blocked }: {
  s: FilmSession; film: Film; selected: string | null; blocked: string | null
}) {
  const next = mainAction(s, selected)
  const used = Math.min(100, ((s.spent_cny + s.reserved_cny) / s.budget_cny) * 100)
  return (
    <section className="film__overview">
      <div className="film__counts">
        <b>{s.clips.length} 段</b>
        {Object.entries(s.counts).map(([k, n]) => (
          <span key={k} className={`film__count film__count--${k}`}>{label(FILM_STATE, k)} {n}</span>
        ))}
        <button className="tlc__linkbtn" onClick={() => void film.load()}>刷新</button>
      </div>
      <div className="film__money">
        <span>已花 {yuan(s.spent_cny)}</span>
        {s.reserved_cny > 0 && <span>在跑预留 {yuan(s.reserved_cny)}</span>}
        <span>剩余预估 {yuan(s.remaining_cny)}</span>
        <span>上限 {yuan(s.budget_cny)}</span>
      </div>
      <div className="film__bar" title="已花 + 在跑预留 占上限"><i style={{ width: `${used}%` }} /></div>
      {next.kind === 'try' && (
        <button className="btn btn--sm" disabled={!!blocked || film.busy} onClick={() => void film.runClip(next.clip)}>
          先试这一段（{next.clip.id}，约 {yuan(next.clip.estimate_cny)}）
        </button>
      )}
      {next.kind === 'rest' && (
        <button className="btn btn--sm" disabled={!!blocked || film.busy} onClick={film.runRest}>
          出剩余 {next.count} 段（约 {yuan(next.cny)}）
        </button>
      )}
      {next.kind === 'none' && (
        <p className="tlc__kfnote">
          {!s.clips.some((c) => c.attempts.some((a) => a.state === 'succeeded')) && s.clips.some(inFlight)
            ? '试段生成中，出完再出剩余各段'
            : s.clips.some(inFlight) ? '各段在生成中，出完会自动刷新。' : '各段都出完了：在下面「配音与合成」合成整章。'}
        </p>
      )}
    </section>
  )
}

/** 选中段详情：所含镜头、提示词（只读）、参考图、首帧来源、尝试记录（播放、★ 采用）、重做、原声静音 */
function ClipDetail({ c, film, blocked, onPickShot }: {
  c: FilmClip; film: Film; blocked: string | null; onPickShot: (shotId: string) => void
}) {
  const [watch, setWatch] = useState<number | null>(null)
  const file = watch === null ? null : (c.attempts[watch]?.file ?? null)
  const { ensure } = film
  useEffect(() => { ensure(file) }, [file, ensure])
  const flying = inFlight(c)
  const redo = c.attempts.some((a) => a.state === 'succeeded')
  return (
    <section className="film__clip">
      <header>
        <b>{c.id}</b>
        <span>{label(FILM_STATE, c.state)} · {c.duration}s · 约 {yuan(c.estimate_cny)}{c.truncated ? ' · ✂ 尾部截断' : ''}</span>
      </header>
      <div className="film__shots">
        {c.shots.map((id) => (
          <button key={id} className="tlc__unit" title="在画布上选中这一镜" onClick={() => onPickShot(id)}>
            <code>{id}</code>
          </button>
        ))}
      </div>
      {c.uncertain && (
        <p className="tlc__kferr">这一段结果不明：厂商那边可能还有任务在跑或已扣费，请到厂商控制台核对，确认没有生成再重做。</p>
      )}
      {c.error && <p className="tlc__kferr">{c.error}</p>}
      <details>
        <summary>提示词（只读，要改就改镜头）</summary>
        <pre className="film__prompt">{c.prompt}</pre>
      </details>
      <p className="film__line">
        参考图：{c.refs.length ? c.refs.join('、') : '无'}
        {!!c.dropped_refs.length && <span className="film__dim">（超出名额被裁：{c.dropped_refs.join('、')}）</span>}
        {!!c.missing_refs.length && <span className="film__dim">（没有图、只写文字描述：{c.missing_refs.join('、')}）</span>}
      </p>
      <p className="film__line">首帧：{firstFrameText(c)}</p>
      {!!c.attempts.length && (
        <table className="film__attempts">
          <tbody>
            {c.attempts.map((a, i) => (
              <tr key={i} className={i === c.chosen ? 'is-chosen' : ''}>
                <td>第 {i + 1} 次</td>
                <td>{when(a.at)}</td>
                <td>{label(ATTEMPT_STATE, a.state)}</td>
                <td>{yuan(a.cost_cny)}</td>
                <td>
                  {a.state === 'succeeded' && a.file && (
                    <button className="tlc__linkbtn" onClick={() => setWatch(i)}>播放</button>
                  )}
                </td>
                <td>
                  {i === c.chosen ? <span title="采用的这一次">★</span> : a.state === 'succeeded' && (
                    <button className="tlc__linkbtn" disabled={flying || film.busy} title="改用这一次"
                            onClick={() => void film.choose(c.id, i)}>☆ 采用</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {file && (film.files[file]
        ? <video className="film__video" src={film.files[file]} controls autoPlay muted={c.mute_native} />
        : <p className="tlc__kfnote">读取视频…</p>)}
      <div className="tlc__kfacts">
        <button className="btn btn--sm" disabled={!!blocked || flying || film.busy} onClick={() => void film.runClip(c)}>
          {flying ? label(FILM_STATE, c.state) : `${redo ? '重做这一段' : '出这一段'}（约 ${yuan(c.estimate_cny)}）`}
        </button>
        <label className="check" title="合成整章时这一段的视频原声静音">
          <input type="checkbox" checked={c.mute_native} disabled={film.busy}
                 onChange={(e) => void film.mute(c.id, e.target.checked)} />
          原声静音
        </label>
      </div>
    </section>
  )
}

/** 花钱前的确认：批量列出各段；合计、已花、在跑预留、执行后累计与上限；费率依据如实照抄 */
function ConfirmBox({ s, film, blocked }: { s: FilmSession; film: Film; blocked: string | null }) {
  const cf = film.confirm!
  const rows = cf.kind === 'rest' ? batchSummary(s).rows : []
  const after = Math.round((s.spent_cny + s.reserved_cny + cf.cny) * 100) / 100
  const over = after > s.budget_cny + 1e-9
  return (
    <section className="film__confirm" role="dialog" aria-label="确认出片金额">
      <h4>{cf.kind === 'rest' ? `出剩余 ${rows.length} 段` : `出 ${cf.clipId}`}</h4>
      {cf.kind === 'clip' && cf.uncertain && (
        <p className="tlc__kferr">这一段结果不明：厂商那边可能还有任务在跑或已扣费，请到厂商控制台核对，确认没有生成再重做。</p>
      )}
      {cf.changed && <p className="tlc__kferr">预估金额已变为 {yuan(cf.cny)}，请重新确认。</p>}
      {!!rows.length && (
        <table className="film__rows">
          <tbody>
            {rows.map((r) => <tr key={r.id}><td>{r.id}</td><td>{r.duration}s</td><td>{yuan(r.cny)}</td></tr>)}
          </tbody>
        </table>
      )}
      <p>
        合计 <b>{yuan(cf.cny)}</b> · 已花 {yuan(s.spent_cny)}
        {s.reserved_cny > 0 ? ` · 在跑预留 ${yuan(s.reserved_cny)}` : ''} · 执行后累计 {yuan(after)} / 上限 {yuan(s.budget_cny)}
      </p>
      {over && <p className="tlc__kferr">会超过上限，服务端会拒绝：先在设置里调高上限。</p>}
      <p className="tlc__kfnote">费率依据：{s.options.rate_note || '厂商未注明'}。实际以厂商控制台账单为准。</p>
      <div className="tlc__kfacts">
        <button className="btn btn--sm" disabled={film.busy || over || !!blocked} onClick={() => void film.confirmNow()}>
          确认出片（{yuan(cf.cny)}）
        </button>
        <button className="btn btn--sm btn--ghost" onClick={film.cancelConfirm}>取消</button>
      </div>
    </section>
  )
}
