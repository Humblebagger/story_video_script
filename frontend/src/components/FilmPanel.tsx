/** 画布侧栏「出片」页：设置、前置检查、总览与主按钮、选中段详情、花钱前的确认框，最后是配音与合成（ComposePanel）。
 *
 *  花钱的按钮上都写着金额；批量和超过确认线的单段先弹确认（useFilm 决定发不发请求）。
 *  有未保存的改动或完整性检查没过时，所有出片按钮禁用并写明原因。 */
import { useEffect, useRef, useState } from 'react'
import { Play } from 'lucide-react'
import { ATTEMPT_STATE, AUDIO_MODE, FILM_STATE, label } from '../labels'
import { Button } from '@/components/ui/button'
import { StatusPill } from '@/components/common/StatusPill'
import { MoneyConfirm } from '@/components/common/MoneyConfirm'
import { useI18n } from '@/i18n/core'
import { formatMsg, itemError } from '@/i18n/serverMsg'
import { anyInFlight, batchSummary, firstFrameText, inFlight, mainAction, playableAttempt, precheck } from '../film'
import type { Film } from '../useFilm'
import { ComposePanel } from './ComposePanel'
import { rememberOpener } from '../playerFocus'
import { WaitRow } from './NodeCards'
import type { AudioMode, FilmClip, FilmFreeNode, FilmSession, FilmSettings } from '../types'

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
  /** 点「播放」（画布弹播放窗口）；点取消（画布弹确认框） */
  onPlay?: (id: string) => void
  onCancel?: (id: string) => void
}

export function FilmPanel({ film, selected, onPickShot, dirty, onPlay, onCancel }: Props) {
  const { t, locale } = useI18n()
  const s = film.session
  if (film.status === 'loading') return <p className="tlc__kfnote">{t('film.panel.loading')}</p>
  const blocked = dirty ? t('film.panel.blockedDirty')
    : film.gate ? t('film.panel.blockedGate', { gate: formatMsg(film.gate, locale) }) : null
  const clip = s?.clips.find((c) => c.id === selected)
  const freeSel = s?.free?.find((n) => n.id === selected)
  return (
    <div className="film">
      {film.error && (
        <p className="tlc__kferr">
          {formatMsg(film.error, locale)}
          <button type="button" className="tlc__linkbtn" data-testid="film-error-dismiss" onClick={film.dismissError}>{t('common.close')}</button>
        </p>
      )}
      {blocked && <p className="tlc__notice">{blocked}</p>}
      {s && <FilmConfirm s={s} film={film} blocked={blocked} />}
      {!s ? (
        <section className="film__card">
          <p className="tlc__kfnote">{t('film.panel.intro')}</p>
          <Button size="sm" className="self-start" disabled={!!blocked || film.busy} onClick={() => void film.create()}>
            {t('film.panel.create')}
          </Button>
        </section>
      ) : (
        <>
          <Settings key={[s.tier, s.resolution, s.audio_mode, s.budget_cny, s.confirm_over_cny].join('|')}
                    s={s} film={film} />
          <Precheck s={s} gateOk={!film.gate} />
          <Overview s={s} film={film} selected={selected} blocked={blocked} />
          {clip
            ? <ClipDetail key={clip.id} c={clip} s={s} film={film} blocked={blocked} onPickShot={onPickShot}
                          onPlay={onPlay} onCancel={onCancel} />
            : freeSel ? <FreeDetail key={freeSel.id} n={freeSel} film={film} />
            : <p className="tlc__kfnote">{t('film.panel.pickClip')}</p>}
          <ComposePanel film={film} dirty={dirty} />
        </>
      )}
    </div>
  )
}

/** 设置：首次展开，出过片后折叠。改了才能「应用设置」；有段在跑时不能改 */
function Settings({ s, film }: { s: FilmSession; film: Film }) {
  const { t, locale } = useI18n()
  const [draft, setDraft] = useState<FilmSettings>({})
  const val = <K extends 'resolution' | 'audio_mode' | 'budget_cny' | 'confirm_over_cny'>(k: K) => draft[k] ?? s[k]
  const flying = anyInFlight(s)
  const tried = s.clips.some((c) => c.attempts.some((a) => a.state === 'succeeded'))
  const tiers = s.options.tiers
  const tierId = draft.tier ?? s.tier ?? ''
  const tierName = (id: string | null) => {
    const x = tiers.find((o) => o.id === id)
    return x ? formatMsg(x.label, locale) : t('film.panel.tierGone')
  }
  // 草稿换了档位：分辨率、价格、声音模式的可选项取那一档的；没换就用会话当前的
  const picked = draft.tier && draft.tier !== s.tier ? tiers.find((o) => o.id === draft.tier) : undefined
  const resolutions = picked ? picked.resolutions : s.options.resolutions
  const prices = picked ? picked.cny_per_sec : s.options.cny_per_sec
  const audioModes = picked ? picked.audio_modes : s.options.audio_modes
  const pickTier = (id: string) => {
    const nt = tiers.find((o) => o.id === id)
    if (!nt) return
    setDraft({
      ...draft, tier: id,
      resolution: nt.resolutions.includes(val('resolution')) ? draft.resolution : nt.default_resolution,
      audio_mode: nt.audio_modes.includes(val('audio_mode')) ? draft.audio_mode : 'tts_all',
    })
  }
  return (
    <details className="film__settings film__card" open={!tried}>
      <summary>
        {t('film.panel.settingsSum', { tier: tierName(s.tier), res: s.resolution,
          audio: label(AUDIO_MODE, s.audio_mode), cap: yuan(s.budget_cny) })}
      </summary>
      <label className="field">
        <span>{t('film.panel.tier')}</span>
        <select data-testid="film-tier" value={tierId} onChange={(e) => pickTier(e.target.value)}>
          {s.tier === null && !draft.tier ? <option value="" disabled>{t('film.panel.tierGone')}</option> : null}
          {tiers.map((o) => <option key={o.id} value={o.id}>{formatMsg(o.label, locale)}</option>)}
        </select>
      </label>
      <label className="field">
        <span>{t('film.panel.resolution')}</span>
        <select data-testid="film-resolution" value={val('resolution')} onChange={(e) => setDraft({ ...draft, resolution: e.target.value })}>
          {resolutions.map((r) => {
            const price = prices[r]
            return <option key={r} value={r}>{`${r}${price !== undefined ? t('film.panel.resPrice', { price }) : ''}`}</option>
          })}
        </select>
      </label>
      <label className="field">
        <span>{t('film.panel.sound')}</span>
        <select value={val('audio_mode')}
                onChange={(e) => setDraft({ ...draft, audio_mode: e.target.value as AudioMode })}>
          {audioModes.map((m) => <option key={m} value={m}>{label(AUDIO_MODE, m)}</option>)}
        </select>
      </label>
      <label className="field">
        <span>{t('film.panel.budget')}</span>
        <input type="number" min={1} step={10} value={val('budget_cny')}
               onChange={(e) => setDraft({ ...draft, budget_cny: Number(e.target.value) })} />
      </label>
      <label className="field">
        <span>{t('film.panel.confirmOver')}</span>
        <input type="number" min={0} step={5} value={val('confirm_over_cny')}
               onChange={(e) => setDraft({ ...draft, confirm_over_cny: Number(e.target.value) })} />
      </label>
      <p className="tlc__kfnote">{t('film.panel.settingsNote')}</p>
      <Button size="sm" variant="outline" className="self-start"
              disabled={!Object.keys(draft).length || flying || film.busy}
              onClick={() => void film.saveSettings(draft)}>
        {t('film.panel.apply')}
      </Button>
      {flying && <p className="tlc__kfnote">{t('film.panel.flying')}</p>}
    </details>
  )
}

/** 前置检查：待核对的段、缺参考图的资产、被裁 / 截断的段 */
function Precheck({ s, gateOk }: { s: FilmSession; gateOk: boolean }) {
  const { t } = useI18n()
  const sep = t('common.listSep')
  const p = precheck(s)
  const passed = gateOk ? <p className="tlc__kfnote">{t('film.panel.gateOk')}</p> : null
  if (!s.uncertain_count && !p.missing.length && !p.trimmed.length && !p.truncated.length) return passed
  return (
    <section className="film__check film__card">
      {passed}
      {!!s.uncertain_count && (
        <p className="tlc__kferr">
          {t('film.panel.uncertain', { n: s.uncertain_count })}
        </p>
      )}
      {!!p.missing.length && <p>{t('film.panel.missingRefs', { list: p.missing.join(sep) })}</p>}
      {!!p.trimmed.length && <p>{t('film.panel.trimmedClips', { list: p.trimmed.join(sep) })}</p>}
      {!!p.truncated.length && <p>{t('film.panel.truncatedClips', { list: p.truncated.join(sep) })}</p>}
    </section>
  )
}

/** 总览：各状态计数、钱（已花 / 在跑预留 / 剩余预估 / 上限）、主按钮 */
function Overview({ s, film, selected, blocked }: {
  s: FilmSession; film: Film; selected: string | null; blocked: string | null
}) {
  const { t } = useI18n()
  const next = mainAction(s, selected)
  const used = Math.min(100, ((s.spent_cny + s.reserved_cny) / s.budget_cny) * 100)
  return (
    <section className="film__overview film__card">
      <div className="film__counts">
        <b>{t('film.panel.clips', { n: s.clips.length })}</b>
        {Object.entries(s.counts).map(([k, n]) => (
          <span key={k} className={`film__count film__count--${k}`}>{label(FILM_STATE, k)} {n}</span>
        ))}
        <button className="tlc__linkbtn" onClick={() => void film.load()}>{t('film.panel.refresh')}</button>
      </div>
      {!!s.style_outdated_count && (
        <p data-testid="style-outdated-count">
          <StatusPill tone="warn">{t('film.style.outdatedCount', { n: s.style_outdated_count })}</StatusPill>
        </p>
      )}
      <div className="film__money">
        <span>{t('film.panel.spent', { v: yuan(s.spent_cny) })}</span>
        {s.reserved_cny > 0 && <span>{t('film.panel.reserved', { v: yuan(s.reserved_cny) })}</span>}
        <span>{t('film.panel.remaining', { v: yuan(s.remaining_cny) })}</span>
        <span>{t('film.panel.cap', { v: yuan(s.budget_cny) })}</span>
      </div>
      <div className="film__bar" title={t('film.panel.barTip')}><i style={{ width: `${used}%` }} /></div>
      {next.kind === 'try' && (
        <Button size="sm" disabled={!!blocked || film.busy} onClick={() => void film.runClip(next.clip)}>
          {t('film.panel.tryOne', { id: next.clip.id, cost: yuan(next.clip.estimate_cny) })}
        </Button>
      )}
      {next.kind === 'rest' && (
        <Button size="sm" disabled={!!blocked || film.busy} onClick={film.runRest}>
          {t('film.panel.rest', { n: next.count, cost: yuan(next.cny) })}
        </Button>
      )}
      {next.kind === 'none' && (
        <p className="tlc__kfnote">
          {!s.clips.some((c) => c.attempts.some((a) => a.state === 'succeeded')) && s.clips.some(inFlight)
            ? t('film.panel.trying')
            : s.clips.some(inFlight) ? t('film.panel.inflight') : t('film.panel.allDone')}
        </p>
      )}
    </section>
  )
}

/** 选中段详情：所含镜头、提示词（只读）、参考图、首帧来源、尝试记录（播放、★ 采用）、重做、原声静音 */
function ClipDetail({ c, s, film, blocked, onPickShot, onPlay, onCancel }: {
  c: FilmClip; s: FilmSession; film: Film; blocked: string | null; onPickShot: (shotId: string) => void
  onPlay?: (id: string) => void
  onCancel?: (id: string) => void
}) {
  const { t, locale } = useI18n()
  const sep = t('common.listSep')
  const [watch, setWatch] = useState<number | null>(null)
  const file = watch === null ? null : (c.attempts[watch]?.file ?? null)
  const { ensure } = film
  useEffect(() => { ensure(file) }, [file, ensure])
  const flying = inFlight(c)
  const redo = c.attempts.some((a) => a.state === 'succeeded')
  return (
    <section className="film__clip film__card">
      <header>
        <b><i className={`film__dot film__dot--${c.state}`} aria-hidden="true" />{c.id}</b>
        <span>{t('film.panel.clipMeta', { state: label(FILM_STATE, c.state), dur: c.duration, cost: yuan(c.estimate_cny) })}{c.truncated ? t('film.panel.clipCut') : ''}</span>
      </header>
      {flying && (
        <WaitRow item={c} typical={s.options.typical_sec} disabled={film.busy} offset={film.clockOffset}
                 onCancel={onCancel && (() => onCancel(c.id))} />
      )}
      {onPlay && playableAttempt(c) && (
        <Button size="sm" variant="secondary" className="film__play" data-testid="clip-play"
                onClick={(e) => { rememberOpener(e.currentTarget); onPlay(c.id) }}>
          <Play aria-hidden />{t('film.play.open')}
        </Button>
      )}
      <div className="film__shots">
        {c.shots.map((id) => (
          <button key={id} className="tlc__unit" title={t('film.panel.pickShot')} onClick={() => onPickShot(id)}>
            <code>{id}</code>
          </button>
        ))}
      </div>
      {c.uncertain && (
        <p className="tlc__kferr">{t('film.panel.clipUncertain')}</p>
      )}
      {itemError(c, locale) && <p className="tlc__kferr">{itemError(c, locale)}</p>}
      <details>
        <summary>{t('film.panel.promptSum')}</summary>
        <pre className="film__prompt">{c.prompt}</pre>
      </details>
      <p className="film__line">
        {t('film.panel.refs', { list: c.refs.length ? c.refs.join(sep) : t('film.panel.none') })}
        {!!c.dropped_refs.length && <span className="film__dim">{t('film.panel.droppedList', { list: c.dropped_refs.join(sep) })}</span>}
        {!!c.missing_refs.length && <span className="film__dim">{t('film.panel.missingList', { list: c.missing_refs.join(sep) })}</span>}
      </p>
      {c.style && (
        <p className="film__line" data-testid="clip-style">
          {t(c.style === 'used' ? 'film.style.used' : c.style === 'full' ? 'film.style.full' : 'film.style.firstFrame')}
        </p>
      )}
      {c.style_outdated && (
        <p className="film__line" data-testid="clip-style-outdated">
          <StatusPill tone="warn">{t('film.style.outdated')}</StatusPill>
        </p>
      )}
      <p className="film__line">{t('film.panel.firstFrame', { v: firstFrameText(c) })}</p>
      {!!c.attempts.length && (
        <table className="film__attempts">
          <tbody>
            {c.attempts.map((a, i) => (
              <tr key={i} className={i === c.chosen ? 'is-chosen' : ''}>
                <td>{t('film.panel.attemptN', { n: i + 1 })}</td>
                <td>{when(a.at)}</td>
                <td>{label(ATTEMPT_STATE, a.state)}{a.late ? ` · ${t('film.lateTag')}` : ''}</td>
                <td>{yuan(a.cost_cny)}</td>
                <td>
                  {a.state === 'succeeded' && a.file && (
                    <button className="tlc__linkbtn" onClick={() => setWatch(i)}>{t('film.panel.play')}</button>
                  )}
                </td>
                <td>
                  {i === c.chosen ? <span title={t('film.panel.chosenTip')}>★</span> : a.state === 'succeeded' && (
                    <button className="tlc__linkbtn" disabled={flying || film.busy} title={t('film.panel.chooseTip')}
                            onClick={() => void film.choose(c.id, i)}>{t('film.panel.choose')}</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {file && (film.files[file]
        ? <video className="film__video" src={film.files[file]} controls autoPlay muted={c.mute_native} />
        : <p className="tlc__kfnote">{t('film.panel.readingVideo')}</p>)}
      <div className="tlc__kfacts">
        <Button size="sm" disabled={!!blocked || flying || film.busy} onClick={() => void film.runClip(c)}>
          {flying ? label(FILM_STATE, c.state)
            : t('film.panel.runBtn', { what: t(redo ? 'film.panel.redo' : 'film.panel.make'), cost: yuan(c.estimate_cny) })}
        </Button>
        <label className="check" title={t('film.panel.muteTip')}>
          <input type="checkbox" checked={c.mute_native} disabled={film.busy}
                 onChange={(e) => void film.mute(c.id, e.target.checked)} />
          {t('film.panel.mute')}
        </label>
      </div>
    </section>
  )
}

/** 选中的自由节点：完整正文、参考、首帧、全部尝试（可播放）、失败原因；编辑与生成在节点图的卡片上 */
function FreeDetail({ n, film }: { n: FilmFreeNode; film: Film }) {
  const { t, locale } = useI18n()
  const sep = t('common.listSep')
  const [watch, setWatch] = useState<number | null>(null)
  const file = watch === null ? null : (n.attempts[watch]?.file ?? null)
  const { ensure } = film
  useEffect(() => { ensure(file) }, [file, ensure])
  return (
    <section className="film__clip film__card" data-testid="free-detail">
      <header>
        <b><i className={`film__dot film__dot--${n.state}`} aria-hidden="true" />{t('graph.free.detail', { id: n.id })}</b>
        <span>{label(FILM_STATE, n.state)} · {n.duration}s · {yuan(n.estimate_cny)}</span>
      </header>
      {itemError(n, locale) && <p className="tlc__kferr">{itemError(n, locale)}</p>}
      <pre className="film__prompt">{n.prompt || t('film.panel.none')}</pre>
      <p className="film__line">{t('film.panel.refs', { list: n.refs.length ? n.refs.join(sep) : t('film.panel.none') })}</p>
      <p className="film__line">{t('film.panel.firstFrame', { v: firstFrameText({ first_frame: n.first_frame, frame_mode: null }) })}</p>
      {!!n.attempts.length && (
        <table className="film__attempts">
          <tbody>
            {n.attempts.map((a, i) => (
              <tr key={i} className={i === n.chosen ? 'is-chosen' : ''}>
                <td>{t('film.panel.attemptN', { n: i + 1 })}</td>
                <td>{when(a.at)}</td>
                <td>{label(ATTEMPT_STATE, a.state)}</td>
                <td>{yuan(a.cost_cny)}</td>
                <td>
                  {a.state === 'succeeded' && a.file && (
                    <button className="tlc__linkbtn" onClick={() => setWatch(i)}>{t('film.panel.play')}</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {file && (film.files[file]
        ? <video className="film__video" src={film.files[file]} controls autoPlay muted />
        : <p className="tlc__kfnote">{t('film.panel.readingVideo')}</p>)}
    </section>
  )
}

/** 花钱前的确认（全站统一的 MoneyConfirm）：批量列出各段；金额变了、结果不明的提示放在明细里。
 *  一直挂着、靠 open 开合，关闭时才有退出动画；没有确认时用占位值。 */
function FilmConfirm({ s, film, blocked }: { s: FilmSession; film: Film; blocked: string | null }) {
  const { t } = useI18n()
  // 关闭动画期间沿用最后一次的内容，免得标题、金额跳成占位值
  const last = useRef(film.confirm)
  if (film.confirm) last.current = film.confirm
  const cf = film.confirm ?? last.current
  const rows = cf?.kind === 'rest' ? batchSummary(s).rows : []
  return (
    <MoneyConfirm
      open={!!film.confirm}
      title={cf?.kind === 'rest' ? t('film.panel.restTitle', { n: rows.length })
        : cf ? t('film.panel.clipTitle', { id: cf.clipId }) : ''}
      cny={cf?.cny ?? 0} spent={s.spent_cny} reserved={s.reserved_cny} budget={s.budget_cny}
      changed={cf?.changed} rateNote={s.options.rate_note} action={t('film.panel.action')}
      blocked={!!blocked} busy={film.busy}
      onConfirm={() => void film.confirmNow()} onCancel={film.cancelConfirm}>
      {blocked && <p className="text-destructive">{blocked}</p>}
      {cf?.kind === 'clip' && cf.uncertain && (
        <p className="text-destructive">{t('film.panel.clipUncertain')}</p>
      )}
      {!!rows.length && (
        <table className="film__rows w-full text-xs tabular-nums">
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}><td className="font-mono">{r.id}</td><td>{r.duration}s</td><td className="text-right">{yuan(r.cny)}</td></tr>
            ))}
          </tbody>
        </table>
      )}
    </MoneyConfirm>
  )
}
