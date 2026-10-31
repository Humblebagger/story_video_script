/** 「出片」页签下半部分：配音（各说话人的音色）、BGM 与选曲参考、合成整章（草稿合成、金额确认）、
 *  成片（状态、播放下载、合成报告）。
 *
 *  配音花钱：金额写在按钮上，大于 0 时先弹确认（useCompose 决定发不发请求）。
 *  不能合成时按钮禁用，原因逐条写出（composeBlockers）。 */
import { useEffect, useState } from 'react'
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

export function ComposePanel({ film, dirty }: { film: Film; dirty: boolean }) {
  const c = useCompose(film)
  const s = film.session!
  const p = c.preview
  if (!p) {
    return (
      <section className="compose">
        <h4>配音与合成</h4>
        {c.error ? <p className="tlc__kferr">{c.error}</p> : <p className="tlc__kfnote">读取合成预览…</p>}
      </section>
    )
  }
  const blockers = composeBlockers(p, s, c.voices, { dirty, gate: film.gate, draft: c.draft })
  return (
    <section className="compose">
      <div className="compose__head">
        <h4>配音与合成</h4>
        <button className="tlc__linkbtn" onClick={() => void c.load()}>刷新合成</button>
      </div>
      {c.error && <p className="tlc__kferr">{c.error}</p>}
      <Voices c={c} />
      <Music c={c} />
      {c.confirm && <ComposeConfirm s={s} c={c} blocked={blockers.length > 0} />}
      <div className="compose__run">
        <p>
          配音 {p.lines} 条{p.lines ? ` · 未缓存 ${p.tts_chars} 字 · 约 ${yuan(p.tts_cny)}` : ''}
          {p.no_video.length ? ` · ${p.no_video.length} 段还没出片` : ''}
        </p>
        <label className="check">
          <input type="checkbox" checked={c.draft} disabled={c.busy} onChange={(e) => c.setDraft(e.target.checked)} />
          草稿合成（没出的段用关键帧定格补位，没有关键帧用黑场）
        </label>
        {blockers.map((b) => <p key={b} className="tlc__notice">{b}</p>)}
        <button className="btn btn--sm" disabled={!!blockers.length || c.busy} onClick={c.start}>
          {composeLabel(p)}
        </button>
      </div>
      {p.final && <Final c={c} />}
    </section>
  )
}

/** 各说话人的音色：缺音色的展开并标红；选「按提示默认」恢复默认 */
function Voices({ c }: { c: Compose }) {
  const v = c.voices
  if (!c.preview!.lines) return <p className="tlc__kfnote">这个声音模式下没有要配音的语音条。</p>
  if (!v) return <p className="tlc__kfnote">读取音色表…</p>
  const name = (id: string | null) => v.voices.find((x) => x.id === id)?.name ?? id ?? ''
  return (
    <details className="compose__box" open={v.missing.length > 0}>
      <summary>音色 · {v.provider}{v.missing.length ? ` · 缺 ${v.missing.length} 个` : ''}</summary>
      <table className="compose__table">
        <tbody>
          {v.speakers.map((sp) => (
            <tr key={sp.key} className={sp.voice ? '' : 'is-missing'}>
              <td>{sp.name}{sp.hint && <span className="film__dim">（{sp.hint}）</span>}</td>
              <td>
                <select aria-label={`${sp.name} 的音色`} value={sp.chosen ?? ''} disabled={c.busy}
                        onChange={(e) => void c.setVoice(sp.key, e.target.value)}>
                  <option value="">
                    {sp.chosen ? '按提示默认' : sp.voice ? `默认：${name(sp.voice)}` : '请选择音色'}
                  </option>
                  {v.voices.map((x) => (
                    <option key={x.id} value={x.id}>{x.name}（{x.gender === 'male' ? '男' : '女'}）</option>
                  ))}
                </select>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="tlc__kfnote">音色只存在这次出片里，不改分镜。费率依据：{v.rate_note || '厂商未注明'}。</p>
    </details>
  )
}

/** 每集 BGM：上传 / 换一段 / 删除；分镜的选曲参考 */
function Music({ c }: { c: Compose }) {
  const p = c.preview!
  const eps = Object.entries(p.music)
  return (
    <details className="compose__box">
      <summary>BGM · 已上传 {p.bgm.length} / {eps.length} 集</summary>
      {eps.map(([ep, m]) => {
        const has = p.bgm.includes(ep)
        return (
          <div key={ep} className="compose__ep">
            <div className="compose__eprow">
              <b>{ep}</b>
              {has ? <span>已上传</span> : <span className="film__dim">没有 BGM</span>}
              <label className="tlc__linkbtn">
                {has ? '换一段' : '上传'}
                <input type="file" hidden accept={BGM_ACCEPT} aria-label={`${ep} 的 BGM`} disabled={c.busy}
                       onChange={(e) => {
                         const f = e.target.files?.[0]
                         e.target.value = ''
                         if (f) void c.uploadBgm(ep, f)
                       }} />
              </label>
              {has && (
                <button className="tlc__linkbtn" disabled={c.busy} onClick={() => void c.removeBgm(ep)}>删除</button>
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
      <p className="tlc__kfnote">每集一段（mp3 / wav / m4a / aac，≤ 30MB），合成时循环铺满，有人声时自动压低；选曲参考来自分镜。</p>
    </details>
  )
}

/** 成片：状态、失败时的 ffmpeg 输出、各集播放与下载、合成报告 */
function Final({ c }: { c: Compose }) {
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
          <summary>ffmpeg 输出</summary>
          <pre className="film__prompt">{f.detail}</pre>
        </details>
      )}
      {!!eps.length && f.state !== 'done' && (
        <p className="film__dim">下面是上一次合成的成片{f.stale ? '（已过期）' : ''}。</p>
      )}
      {!!eps.length && (
        <table className="compose__table">
          <tbody>
            {eps.map((e) => {
              const rep = r?.episodes.find((x) => x.episode === e.episode)
              return (
                <tr key={e.episode}>
                  <td><b>{e.episode}</b></td>
                  <td>{rep ? `${rep.seconds.toFixed(1)} 秒` : ''}</td>
                  <td><button className="tlc__linkbtn" onClick={() => setOpen(e.episode)}>播放 / 下载</button></td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
      {sel && <EpisodeFiles c={c} e={sel} />}
      {r && (
        <details className="compose__box">
          <summary>合成报告</summary>
          <p>{r.size} · {label(AUDIO_MODE, r.audio_mode)}{r.draft ? ' · 草稿合成' : ''}</p>
          {r.warning && <p className="tlc__notice">{r.warning}</p>}
          <p className="film__dim">{r.alignment}</p>
          {r.episodes.map((x) => (
            <div key={x.episode} className="compose__ep">
              <b>{x.episode}</b>
              {!!x.placeholders.length && <p>补位（关键帧或黑场）：{x.placeholders.join('、')}</p>}
              {!!x.stale.length && <p>用的是过期的段：{x.stale.join('、')}</p>}
              {x.notes.map((n, i) => <p key={i}>{noteText(n)}</p>)}
              {!x.placeholders.length && !x.stale.length && !x.notes.length && (
                <p className="film__dim">声画都对得上，没有调整。</p>
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
  const video = c.url(e.video)
  const srt = c.url(e.srt)
  return (
    <div className="compose__play">
      {e.video && (video
        ? <video className="film__video" src={video} controls />
        : <p className="tlc__kfnote">读取成片…</p>)}
      <div className="tlc__kfacts">
        {video && <a className="btn btn--sm" href={video} download={`${e.episode}.mp4`}>下载 {e.episode}.mp4</a>}
        {srt && <a className="btn btn--sm btn--ghost" href={srt} download={`${e.episode}.srt`}>下载字幕</a>}
      </div>
    </div>
  )
}

/** 配音花钱前的确认：配音金额、已花、执行后累计与上限、费率依据 */
function ComposeConfirm({ s, c, blocked }: { s: FilmSession; c: Compose; blocked: boolean }) {
  const cf = c.confirm!
  const after = Math.round((s.spent_cny + cf.cny) * 100) / 100
  const over = after > s.budget_cny + 1e-9
  return (
    <section className="film__confirm" role="dialog" aria-label="确认配音金额">
      <h4>合成整章</h4>
      {cf.changed && <p className="tlc__kferr">配音金额已变为 {yuan(cf.cny)}，请重新确认。</p>}
      <p>
        配音 <b>{yuan(cf.cny)}</b>（未缓存的 {c.preview!.tts_chars} 字）· 已花 {yuan(s.spent_cny)}
        {' '}· 执行后累计 {yuan(after)} / 上限 {yuan(s.budget_cny)}
      </p>
      {over && <p className="tlc__kferr">会超过上限，服务端会拒绝：先在设置里调高上限。</p>}
      <p className="tlc__kfnote">
        费率依据：{c.voices?.rate_note || '厂商未注明'}。合成本身不花钱；实际以厂商控制台账单为准。
      </p>
      <div className="tlc__kfacts">
        <button className="btn btn--sm" disabled={c.busy || over || blocked} onClick={() => void c.confirmNow()}>
          确认合成（{yuan(cf.cny)}）
        </button>
        <button className="btn btn--sm btn--ghost" onClick={c.cancelConfirm}>取消</button>
      </div>
    </section>
  )
}
