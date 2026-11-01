/** 「出片」页签下半部分：配音（各说话人的音色）、BGM 与选曲参考、合成整章（没出好的段先用图片代替、金额确认）、
 *  成片（状态、播放下载、合成报告）。
 *
 *  配音花钱：金额写在按钮上，大于 0 时先弹确认（useCompose 决定发不发请求）。
 *  不能合成时按钮禁用，原因逐条写出（composeBlockers）。确认框开着时，会改金额的操作（没出好的段先用图片代替、音色、BGM）
 *  一律锁住，免得确认的金额与实际不符。 */
import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { MoneyConfirm } from '@/components/common/MoneyConfirm'
import { useI18n } from '@/i18n/core'
import { AUDIO_MODE, MOOD, label } from '../labels'
import {
  BGM_ACCEPT, composeBlockers, composeLabel, curveText, finalEpisodes, finalText, noteText,
} from '../compose'
import type { FinalEpisode } from '../compose'
import { useCompose } from '../useCompose'
import type { Compose } from '../useCompose'
import type { Film } from '../useFilm'
import type { FilmSession } from '../types'

const yuan = (n: number) => `¥${n.toFixed(2)}`
/** 忙着，或确认框开着（改了会让确认的金额对不上） */
const locked = (c: Compose) => c.busy || !!c.confirm

export function ComposePanel({ film, dirty }: { film: Film; dirty: boolean }) {
  const { t } = useI18n()
  const c = useCompose(film, dirty)
  const s = film.session!
  const p = c.preview
  if (!p) {
    return (
      <section className="compose">
        <h4>{t('compose.panel.title')}</h4>
        {c.error
          ? (
            <>
              <p className="tlc__kferr">{c.error}</p>
              <Button size="sm" variant="outline" className="self-start" onClick={() => void c.load()}>{t('common.retry')}</Button>
            </>
          )
          : <p className="tlc__kfnote">{t('compose.panel.loading')}</p>}
      </section>
    )
  }
  const blockers = composeBlockers(p, s, c.voices, { dirty, gate: film.gate, draft: c.draft })
  return (
    <section className="compose">
      <div className="compose__head">
        <h4>{t('compose.panel.title')}</h4>
        <button className="tlc__linkbtn" onClick={() => void c.load()}>{t('compose.panel.refresh')}</button>
      </div>
      {c.error && <p className="tlc__kferr">{c.error}</p>}
      <Voices c={c} />
      <Music c={c} />
      <ComposeConfirm s={s} c={c} blockers={blockers} />
      <div className="compose__run">
        <p>
          {t('compose.panel.lines', { n: p.lines })}
          {p.lines ? t('compose.panel.uncached', { chars: p.tts_chars, cost: yuan(p.tts_cny) }) : ''}
          {p.no_video.length ? t('compose.panel.noVideo', { n: p.no_video.length }) : ''}
        </p>
        <label className="check">
          <input type="checkbox" checked={c.draft} disabled={locked(c)} onChange={(e) => c.setDraft(e.target.checked)} />
          {t('compose.panel.draft')}
        </label>
        {blockers.map((b) => <p key={b} className="tlc__notice">{b}</p>)}
        <Button size="sm" className="self-start" disabled={!!blockers.length || c.busy} onClick={c.start}>
          {composeLabel(p)}
        </Button>
      </div>
      {p.final && <Final c={c} />}
    </section>
  )
}

/** 各说话人的音色：缺音色的展开并标红；选「按提示默认」恢复默认 */
function Voices({ c }: { c: Compose }) {
  const { t } = useI18n()
  const v = c.voices
  if (!c.preview!.lines) return <p className="tlc__kfnote">{t('compose.panel.noLines')}</p>
  if (!v) {
    return c.voicesError
      ? <p className="tlc__kferr">{t('compose.panel.voicesFailed', { error: c.voicesError ?? '' })}</p>
      : <p className="tlc__kfnote">{t('compose.panel.voicesLoading')}</p>
  }
  const name = (id: string | null) => v.voices.find((x) => x.id === id)?.name ?? id ?? ''
  return (
    <details className="compose__box" open={v.missing.length > 0}>
      <summary>{t('compose.panel.voicesSum', { provider: v.provider ?? '' })}{v.missing.length ? t('compose.panel.voicesMissing', { n: v.missing.length }) : ''}</summary>
      <table className="compose__table">
        <tbody>
          {v.speakers.map((sp) => (
            <tr key={sp.key} className={sp.voice ? '' : 'is-missing'}>
              <td>{sp.name}{sp.hint && <span className="film__dim">{t('common.paren', { text: sp.hint })}</span>}</td>
              <td>
                <select aria-label={t('compose.panel.voiceAria', { name: sp.name })} value={sp.chosen ?? ''} disabled={locked(c)}
                        onChange={(e) => void c.setVoice(sp.key, e.target.value)}>
                  <option value="">
                    {sp.chosen ? t('compose.panel.hintDefault')
                      : sp.voice ? t('compose.panel.defaultVoice', { name: name(sp.voice) }) : t('compose.panel.pickVoice')}
                  </option>
                  {v.voices.map((x) => (
                    <option key={x.id} value={x.id}>{t('compose.panel.voiceOpt', { name: x.name, gender: t(x.gender === 'male' ? 'compose.panel.male' : 'compose.panel.female') })}</option>
                  ))}
                </select>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="tlc__kfnote">{t('compose.panel.voicesNote', { note: v.rate_note || t('money.rateUnknown') })}</p>
    </details>
  )
}

/** 每集 BGM：上传 / 换一段 / 删除；分镜的选曲参考 */
function Music({ c }: { c: Compose }) {
  const { t } = useI18n()
  const p = c.preview!
  const eps = Object.entries(p.music)
  return (
    <details className="compose__box">
      <summary>{t('compose.panel.bgmSum', { n: p.bgm.length, total: eps.length })}</summary>
      {eps.map(([ep, m]) => {
        const has = p.bgm.includes(ep)
        return (
          <div key={ep} className="compose__ep">
            <div className="compose__eprow">
              <b>{ep}</b>
              {has ? <span>{t('compose.panel.uploaded')}</span> : <span className="film__dim">{t('compose.panel.noBgm')}</span>}
              <label className="compose__upload">
                {has ? t('compose.panel.replace') : t('compose.panel.upload')}
                <input type="file" hidden accept={BGM_ACCEPT} aria-label={t('compose.panel.bgmAria', { ep })} disabled={locked(c)}
                       onChange={(e) => {
                         const f = e.target.files?.[0]
                         e.target.value = ''
                         if (f) void c.uploadBgm(ep, f)
                       }} />
              </label>
              {has && (
                <button className="tlc__linkbtn" disabled={locked(c)} onClick={() => void c.removeBgm(ep)}>{t('compose.panel.remove')}</button>
              )}
            </div>
            {(m.mood || m.style_hint) && (
              <p className="film__dim">{[label(MOOD, m.mood), m.style_hint ?? ''].filter(Boolean).join(' · ')}</p>
            )}
            {!!m.curve?.length && (
              <ul className="compose__curve">{m.curve.map((seg, i) => <li key={i}>{curveText(seg)}</li>)}</ul>
            )}
          </div>
        )
      })}
      <p className="tlc__kfnote">{t('compose.panel.bgmNote')}</p>
    </details>
  )
}

/** 成片：状态、失败时的 ffmpeg 输出、各集播放与下载、合成报告 */
function Final({ c }: { c: Compose }) {
  const { t } = useI18n()
  const sep = t('common.listSep')
  const f = c.preview!.final!
  const r = c.preview!.report
  const eps = finalEpisodes(f.files)
  const [open, setOpen] = useState<string | null>(null)
  const sel = eps.find((e) => e.episode === open)
  const { ensure } = c
  useEffect(() => {
    ensure(sel?.video)
    ensure(sel?.srt)
  }, [sel?.video, sel?.srt, ensure])
  const tone = f.state === 'failed' ? 'tlc__kferr' : f.stale ? 'tlc__notice' : 'tlc__kfnote'
  return (
    <section className="compose__final">
      <p className={tone}>{finalText(f)}</p>
      {f.state === 'failed' && f.detail && (
        <details>
          <summary>{t('compose.panel.ffmpegOut')}</summary>
          <pre className="film__prompt">{f.detail}</pre>
        </details>
      )}
      {!!eps.length && f.state !== 'done' && (
        <p className="film__dim">{t('compose.panel.lastCut', { stale: f.stale ? t('compose.panel.edited') : '' })}</p>
      )}
      {!!eps.length && (
        <table className="compose__table">
          <tbody>
            {eps.map((e) => {
              const rep = r?.episodes.find((x) => x.episode === e.episode)
              return (
                <tr key={e.episode}>
                  <td><b>{e.episode}</b></td>
                  <td>{rep ? t('compose.panel.seconds', { v: rep.seconds.toFixed(1) }) : ''}</td>
                  <td><button className="tlc__linkbtn" onClick={() => setOpen(e.episode)}>{t('compose.panel.playDl')}</button></td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
      {sel && <EpisodeFiles c={c} e={sel} />}
      {r && (
        <details className="compose__box">
          <summary>{t('compose.panel.report')}</summary>
          <p>{r.size} · {label(AUDIO_MODE, r.audio_mode)}{r.draft ? t('compose.panel.draftUsed') : ''}</p>
          {r.warning && <p className="tlc__notice">{r.warning}</p>}
          <p className="film__dim">{r.alignment}</p>
          {r.episodes.map((x) => (
            <div key={x.episode} className="compose__ep">
              <b>{x.episode}</b>
              {!!x.placeholders.length && <p>{t('compose.panel.placeholders', { list: x.placeholders.join(sep) })}</p>}
              {!!x.stale.length && <p>{t('compose.panel.staleSegs', { list: x.stale.join(sep) })}</p>}
              {x.notes.map((n, i) => <p key={i}>{noteText(n)}</p>)}
              {!x.placeholders.length && !x.stale.length && !x.notes.length && (
                <p className="film__dim">{t('compose.panel.aligned')}</p>
              )}
            </div>
          ))}
        </details>
      )}
    </section>
  )
}

/** 一集的成片播放与下载（文件取回成 blob 后才有链接） */
function EpisodeFiles({ c, e }: { c: Compose; e: FinalEpisode }) {
  const { t } = useI18n()
  const video = c.url(e.video)
  const srt = c.url(e.srt)
  return (
    <div className="compose__play">
      {e.video && (video
        ? <video className="film__video" src={video} controls />
        : <p className="tlc__kfnote">{t('compose.panel.readingFinal')}</p>)}
      <div className="tlc__kfacts">
        {video && <a className="compose__dl" href={video} download={`${e.episode}.mp4`}>{t('compose.panel.dlMp4', { ep: e.episode })}</a>}
        {srt && <a className="compose__dl compose__dl--ghost" href={srt} download={`${e.episode}.srt`}>{t('compose.panel.dlSrt')}</a>}
      </div>
    </div>
  )
}

/** 配音花钱前的确认（全站统一的 MoneyConfirm）；一直挂着、靠 open 开合，关闭时才有退出动画 */
function ComposeConfirm({ s, c, blockers }: { s: FilmSession; c: Compose; blockers: string[] }) {
  const { t } = useI18n()
  // 关闭动画期间沿用最后一次的内容，免得标题、金额跳成占位值
  const last = useRef(c.confirm)
  if (c.confirm) last.current = c.confirm
  const cf = c.confirm ?? last.current
  return (
    <MoneyConfirm
      open={!!c.confirm} title={t('compose.panel.confirmTitle')} cny={cf?.cny ?? 0} spent={s.spent_cny} budget={s.budget_cny}
      changed={cf?.changed} rateNote={c.voices?.rate_note} action={t('compose.panel.action')}
      blocked={blockers.length > 0} busy={c.busy} onConfirm={() => void c.confirmNow()} onCancel={c.cancelConfirm}>
      {blockers.map((b) => <p key={b} className="text-destructive">{b}</p>)}
      <p>{t('compose.panel.ttsNote', { n: c.preview?.tts_chars ?? 0 })}</p>
    </MoneyConfirm>
  )
}
