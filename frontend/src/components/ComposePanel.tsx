/** 「出片」页签下半部分：配音（各说话人的音色）、BGM 与选曲参考、合成整章（没出好的段先用图片代替、金额确认）、
 *  成片（状态、播放下载、合成报告）。
 *
 *  配音花钱：金额写在按钮上，大于 0 时先弹确认（useCompose 决定发不发请求）。
 *  不能合成时按钮禁用，原因逐条写出（composeBlockers）。确认框开着时，会改金额的操作（没出好的段先用图片代替、音色、BGM）
 *  一律锁住，免得确认的金额与实际不符。 */
import { useEffect, useRef, useState } from 'react'
import type { RefObject } from 'react'
import { ArrowLeft, RefreshCw, Save } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { FieldHint, InlineAlert } from '@/components/ui/form-field'
import { SelectMenu } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { MoneyConfirm } from '@/components/common/MoneyConfirm'
import { useI18n } from '@/i18n/core'
import { formatMsg } from '@/i18n/serverMsg'
import { AUDIO_MODE, MOOD, label } from '../labels'
import {
  BGM_ACCEPT, composeBlockers, composeLabel, curveText, finalEpisodes, finalText, noteText,
} from '../compose'
import type { FinalEpisode } from '../compose'
import { useCompose } from '../useCompose'
import type { Compose } from '../useCompose'
import type { Film } from '../useFilm'
import type { FilmSession } from '../types'
import { hintForMsg, useTtsHint, useWithHint } from '../adminHints'

const yuan = (n: number) => `¥${n.toFixed(2)}`
/** 忙着，或确认框开着（改了会让确认的金额对不上） */
const locked = (c: Compose) => c.busy || !!c.confirm

export function ComposePanel({ film, dirty, onSave, onBackToBoard, onOpenSettings }: {
  film: Film; dirty: boolean; onSave?: () => void; onBackToBoard?: () => void; onOpenSettings?: () => void
}) {
  const { t, locale } = useI18n()
  const c = useCompose(film, dirty)
  const s = film.session!
  const p = c.preview
  const voicesRef = useRef<HTMLDetailsElement>(null)
  const openVoices = () => {
    const el = voicesRef.current
    if (!el) return
    el.open = true
    el.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }
  if (!p) {
    return (
      <section className="compose">
        <h4>{t('compose.panel.title')}</h4>
        {c.error
          ? (
            <InlineAlert tone="warning" title={t('compose.panel.loadTitle')}
                         action={<Button size="sm" variant="outline" onClick={() => void c.load()}><RefreshCw aria-hidden />{t('common.retry')}</Button>}>
              {formatMsg(c.error, locale)}
            </InlineAlert>
          )
          : (
            <div className="flex flex-col gap-2" aria-busy="true" aria-label={t('compose.panel.loading')}>
              <Skeleton className="h-4 w-28" />
              <Skeleton className="h-9 w-full" />
              <Skeleton className="h-9 w-4/5" />
            </div>
          )}
      </section>
    )
  }
  const blockers = composeBlockers(p, s, c.voices, { dirty, gate: film.gate, draft: c.draft })
  return (
    <section className="compose">
      <div className="compose__head">
        <div>
          <span className="film__eyebrow">{t('compose.panel.eyebrow')}</span>
          <h4>{t('compose.panel.title')}</h4>
        </div>
        <Button size="sm" variant="ghost" onClick={() => void c.load()}><RefreshCw aria-hidden />{t('compose.panel.refresh')}</Button>
      </div>
      {c.error && (
        <InlineAlert tone="warning" title={t('compose.panel.actionFailed')}
                     action={<Button size="sm" variant="ghost" onClick={() => void c.load()}>{t('common.retry')}</Button>}>
          {formatMsg(c.error, locale)}
        </InlineAlert>
      )}
      {c.finalError && (
        <InlineAlert tone="warning" title={t('compose.panel.finalReadFailed')}>
          {t('compose.readFinalFailed', { error: formatMsg(c.finalError, locale) })}
        </InlineAlert>
      )}
      <Voices c={c} panelRef={voicesRef} />
      <Music c={c} />
      <ComposeConfirm s={s} c={c} blockers={blockers} />
      <div className="compose__run">
        <p>
          {t('compose.panel.lines', { n: p.lines })}
          {p.lines ? t('compose.panel.uncached', { chars: p.tts_chars, cost: yuan(p.tts_cny) }) : ''}
          {p.no_video.length ? t('compose.panel.noVideo', { n: p.no_video.length }) : ''}
        </p>
        <label className="check">
          <Checkbox checked={c.draft} disabled={locked(c)} onChange={(e) => c.setDraft(e.target.checked)} />
          {t('compose.panel.draft')}
        </label>
        {!!blockers.length && (
          <InlineAlert tone="warning" title={t('compose.panel.blockersTitle', { n: blockers.length })}
                       testId="compose-blockers"
                       action={(
                         <span className="film__alertacts">
                           {dirty && onSave && <Button size="sm" variant="outline" onClick={onSave}><Save aria-hidden />{t('compose.panel.goSave')}</Button>}
                           {!dirty && film.gate && onBackToBoard && (
                             <Button size="sm" variant="outline" onClick={onBackToBoard}><ArrowLeft aria-hidden />{t('compose.panel.goStoryboard')}</Button>
                           )}
                           {!dirty && !film.gate && p.missing_voices.length > 0 && (
                             <Button size="sm" variant="outline" onClick={openVoices}>{t('compose.panel.goVoices')}</Button>
                           )}
                           {!dirty && !film.gate && !p.missing_voices.length && !c.draft && p.no_video.length > 0 && (
                             <Button size="sm" variant="outline" onClick={() => c.setDraft(true)}>{t('compose.panel.useDraft')}</Button>
                           )}
                           {!dirty && !film.gate && !p.missing_voices.length && c.draft && p.tts_cny + s.spent_cny > s.budget_cny && onOpenSettings && (
                             <Button size="sm" variant="outline" onClick={onOpenSettings}>{t('compose.panel.goSettings')}</Button>
                           )}
                           <Button size="sm" variant="ghost" onClick={() => void c.load()}><RefreshCw aria-hidden />{t('compose.panel.refresh')}</Button>
                         </span>
                       )}>
            <ul className="ui-alert__list">
              {blockers.map((b) => <li key={b}>{b}</li>)}
            </ul>
          </InlineAlert>
        )}
        <Button size="sm" className="self-start" disabled={!!blockers.length || c.busy} onClick={c.start}>
          {composeLabel(p)}
        </Button>
      </div>
      {p.final && <Final c={c} />}
    </section>
  )
}

/** 各说话人的音色：缺音色的展开并标红；选「按提示默认」恢复默认 */
function Voices({ c, panelRef }: { c: Compose; panelRef: RefObject<HTMLDetailsElement | null> }) {
  const { t, locale } = useI18n()
  const ttsHint = useTtsHint()
  const withHint = useWithHint()
  const v = c.voices
  if (!c.preview!.lines) return <p className="tlc__kfnote">{t('compose.panel.noLines')}</p>
  if (!v) {
    return c.voicesError
      ? (
        <InlineAlert tone="warning" title={t('compose.panel.voicesErrorTitle')}
                     action={<Button size="sm" variant="outline" onClick={() => void c.load()}><RefreshCw aria-hidden />{t('common.retry')}</Button>}>
          {t('compose.panel.voicesFailed', { error: formatMsg(c.voicesError, locale) })}
        </InlineAlert>
      )
      : <p className="tlc__kfnote">{t('compose.panel.voicesLoading')}</p>
  }
  const name = (id: string | null) => v.voices.find((x) => x.id === id)?.name ?? id ?? ''
  return (
    <details ref={panelRef} className="compose__box" open={v.missing.length > 0}>
      <summary>{withHint(t('compose.panel.voicesSum'), ttsHint)}{v.missing.length ? t('compose.panel.voicesMissing', { n: v.missing.length }) : ''}</summary>
      <table className="compose__table" aria-label={t('compose.panel.voicesSum')}>
        <tbody>
          {v.speakers.map((sp) => (
            <tr key={sp.key} className={sp.voice ? '' : 'is-missing'}>
              <td>{formatMsg(sp.name, locale)}{sp.hint && <span className="film__dim">{t('common.paren', { text: sp.hint })}</span>}</td>
              <td>
                <SelectMenu
                  className="ui-select"
                  ariaLabel={t('compose.panel.voiceAria', { name: formatMsg(sp.name, locale) })}
                  value={sp.chosen ?? ''}
                  disabled={locked(c)}
                  options={[
                    {
                      value: '',
                      label: sp.chosen ? t('compose.panel.hintDefault')
                        : sp.voice ? t('compose.panel.defaultVoice', { name: name(sp.voice) })
                          : t('compose.panel.pickVoice'),
                    },
                    ...v.voices.map((x) => ({
                      value: x.id,
                      label: t('compose.panel.voiceOpt', {
                        name: x.name,
                        gender: t(x.gender === 'male' ? 'compose.panel.male' : 'compose.panel.female'),
                      }),
                    })),
                  ]}
                  onChange={(v) => void c.setVoice(sp.key, v)}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <FieldHint>{t('compose.panel.voicesNote', { note: formatMsg(v.rate_note, locale) || t('money.rateUnknown') })}</FieldHint>
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
  const { t, locale } = useI18n()
  const ttsHint = useTtsHint()
  const withHint = useWithHint()
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
      <p className={tone}>{withHint(finalText(f), f.state === 'failed' ? hintForMsg(f.error_msg, null, ttsHint) : null)}</p>
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
          {!!r.warning && <p className="tlc__notice">{formatMsg(r.warning, locale)}</p>}
          <p className="film__dim">{formatMsg(r.alignment, locale)}</p>
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
