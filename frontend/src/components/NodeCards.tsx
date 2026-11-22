/** 节点图上的卡片：资产、剧本段、自由节点（设计文档 2026-11-11 §5.4）。
 *  卡片上能直接出这一段 / 重出、换采用、派生、生成；花钱前在卡片里确认金额（不弹窗）。
 *  视频只在悬停或选中时才取（filmFileUrl 会把整个文件取成 blob），平时显示尾帧图。
 *  这个文件只导出组件（Fast Refresh 要求），共用的计算在 film.ts / nodeGraph.ts。 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Play } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { StatusPill } from '@/components/common/StatusPill'
import type { Tone } from '@/components/common/StatusPill'
import { useI18n } from '@/i18n/core'
import { itemError } from '@/i18n/serverMsg'
import { hintFor, useTierHint, useWithHint } from '../adminHints'
import type { MsgKey } from '@/i18n/core'
import { FILM_STATE, label } from '../labels'
import {
  cancelKind, chosenAttempt, copyIndex, inFlight, needsConfirm, playableAttempt, slotsNeeded, tailSources, waitedSec, waitLine,
} from '../film'
import { rememberOpener } from '../playerFocus'
import type { Film } from '../useFilm'
import type { AssetRole } from '../nodeGraph'
import { foldTags } from '../shotSheet'
import type { FilmAttempt, FilmClip, FilmClipState, FilmFreeNode, FilmSession } from '../types'

const yuan = (n: number) => `¥${n.toFixed(2)}`
const TONE: Record<FilmClipState, Tone> = {
  planned: 'idle', queued: 'live', running: 'live', downloading: 'live', done: 'ok', failed: 'err', stale: 'warn',
}

/** 结果区：悬停或选中时播采用的那次（静音循环），平时显示它的尾帧；没有结果时显示首帧来源图。
 *  有结果且给了 onPlay 时，封面正中是「播放」按钮：点开带声音与控制条的播放窗口 */
function Preview({ film, attempt, fallback, hot, id, onPlay, canPlay }: {
  film: Film; attempt: FilmAttempt | null; fallback: string | null; hot: boolean
  id: string; onPlay?: () => void
  /** 有能播的结果（采用的，或没采用时最近成功的一次）：播放入口依据它，封面仍只展示采用的那次 */
  canPlay: boolean
}) {
  const { t } = useI18n()
  const { ensure, files } = film
  const poster = attempt?.last_frame ?? null
  const file = attempt?.file ?? null
  useEffect(() => { ensure(poster) }, [poster, ensure])
  useEffect(() => { if (hot) ensure(file) }, [hot, file, ensure])
  const video = hot && file ? files[file] : undefined
  const still = (poster && files[poster]) || fallback
  const media = video ? <video className="ngv__media" src={video} autoPlay muted loop playsInline />
    : still ? <img className="ngv__media" src={still} alt="" />
    : <div className="ngv__media ngv__media--empty">{t('graph.noResult')}</div>
  if (!canPlay || !onPlay) return media
  return (
    <div className="ngv__stage">
      {media}
      <button type="button" className="ngv__play" data-testid="ngv-play" aria-label={t('film.play.aria', { id })}
              onClick={(e) => { e.stopPropagation(); rememberOpener(e.currentTarget); onPlay() }}>
        <Play aria-hidden />{t('film.play.open')}
      </button>
    </div>
  )
}

/** 在跑的那一行：已等多久 · 通常多久（每秒走一次），右边是取消入口（还没提交写「取消」，已提交写「不等了」）。
 *  只有时间，不带厂商或模型名。确认框由上层弹（onCancel） */
export function WaitRow({ item, typical, disabled, offset = 0, onCancel }: {
  item: { state: FilmClipState; attempts: FilmAttempt[]; queued_at?: string }
  typical?: number[] | null
  disabled: boolean
  /** 服务端时钟减本地时钟（毫秒）：已等时长按服务端时间算 */
  offset?: number
  onCancel?: () => void
}) {
  const { t } = useI18n()
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [])
  const kind = cancelKind(item)
  return (
    <p className="ngv__wait" data-testid="ngv-wait" onClick={(e) => e.stopPropagation()}>
      <span>{waitLine(waitedSec(item, now + offset), typical)}</span>
      {kind && onCancel && (
        <button type="button" className="tlc__linkbtn" disabled={disabled} onClick={onCancel}>
          {t(kind === 'free' ? 'film.cancel.free' : 'film.cancel.paid')}
        </button>
      )}
    </p>
  )
}

/** 花钱的按钮：不用确认就直接发；要确认（超过确认线、待核对）或服务端金额变了就在卡片里问一次 */
function SpendButton({ text, cny, must, disabled, onSpend }: {
  text: string; cny: number; must: boolean; disabled: boolean
  /** 发请求；服务端金额变了返回新金额 */
  onSpend: (cny: number) => Promise<number | null>
}) {
  const { t } = useI18n()
  const [asking, setAsking] = useState<number | null>(null)
  const go = async (amount: number) => setAsking(await onSpend(amount))
  if (asking !== null) {
    return (
      <span className="ngv__ask" data-testid="ngv-ask">
        <span>{t('graph.confirmCost', { cost: yuan(asking) })}</span>
        <Button size="sm" disabled={disabled} onClick={() => void go(asking)}>{t('graph.confirm')}</Button>
        <Button size="sm" variant="ghost" onClick={() => setAsking(null)}>{t('graph.cancel')}</Button>
      </span>
    )
  }
  return <Button size="sm" disabled={disabled} onClick={() => (must ? setAsking(cny) : void go(cny))}>{text}</Button>
}

/** 在成功的几次之间切换采用（at 为当前采用的那次在列表里的位置，没有为 -1，此时序号显示 –；没有可切换的成功尝试就不渲染） */
function AttemptNav({ at, total, disabled, onPick }: {
  at: number; total: number; disabled: boolean; onPick: (k: number) => void
}) {
  const { t } = useI18n()
  if (total <= 0) return null
  return (
    <span className="ngv__nav">
      <button type="button" className="tlc__linkbtn" disabled={disabled || at <= 0} aria-label={t('graph.prev')}
              onClick={() => onPick(at - 1)}>‹</button>
      <span>{t('graph.attemptOf', { n: at < 0 ? '–' : at + 1, total })}</span>
      <button type="button" className="tlc__linkbtn" disabled={disabled || at >= total - 1} aria-label={t('graph.next')}
              onClick={() => onPick(at + 1)}>›</button>
    </span>
  )
}

export function AssetCard({ role, name, image, usedBy, onOpen }: {
  role: AssetRole; name: string; image: string | null; usedBy: number; onOpen: () => void
}) {
  const { t } = useI18n()
  return (
    <>
      {image ? <img className="ngv__thumb" src={image} alt="" />
        : <div className="ngv__thumb ngv__thumb--empty">{t('graph.noImage')}</div>}
      <div className="ngv__meta">
        <b title={role === 'style' ? t('graph.style') : name}>{role === 'style' ? t('graph.style') : name}</b>
        <span className="ngv__dim" title={`${t(`graph.kind.${role}` as MsgKey)} · ${t('graph.usedBy', { n: usedBy })}`}>
          {t(`graph.kind.${role}` as MsgKey)} · {t('graph.usedBy', { n: usedBy })}
        </span>
        {role !== 'style' && (
          <button type="button" className="tlc__linkbtn ngv__open" onClick={(e) => { e.stopPropagation(); onOpen() }}>
            {t('graph.openAssets')}
          </button>
        )}
      </div>
    </>
  )
}

export function ClipCard({ clip: c, s, film, blocked, hot, fallback, tags, onDerive, onPlay, onCancel }: {
  clip: FilmClip; s: FilmSession; film: Film; blocked: string | null; hot: boolean
  /** 这一段每个镜头的小标签（「SH003 特写·推」），由 NodeGraph 按分镜算好 */
  tags: string[]
  /** 没有结果时显示的首帧来源图（关键帧或上一段尾帧） */
  fallback: string | null
  onDerive: () => void
  /** 点封面上的「播放」；点等待一行里的取消（都由画布接：播放窗口、确认框） */
  onPlay?: () => void
  onCancel?: () => void
}) {
  const { t, locale } = useI18n()
  const tierHint = useTierHint()
  const withHint = useWithHint()
  const err = withHint(itemError(c, locale), hintFor(c.error_msg?.code, tierHint(s.tier), null))
  const ok = c.attempts.map((a, i) => ({ a, i })).filter((x) => x.a.state === 'succeeded' && x.a.file)
  const at = ok.findIndex((x) => x.i === c.chosen)
  const lock = !!blocked || inFlight(c) || film.busy
  const spent = c.attempts.reduce((n, a) => n + (a.cost_cny ?? 0), 0)
  const chosen = chosenAttempt(c)
  const redo = c.attempts.some((a) => a.state === 'succeeded')
  const fold = foldTags(tags)
  return (
    <>
      <header className="ngv__head">
        <b>{c.id}</b><span className="ngv__dim">{c.duration}s</span>
        <StatusPill tone={TONE[c.state]}>{label(FILM_STATE, c.state)}</StatusPill>
        {c.uncertain && <StatusPill tone="warn">{t('graph.uncertainTag')}</StatusPill>}
      </header>
      {tags.length > 0 && (
        <div className="ngv__shots" data-testid="clip-shots" title={tags.join('\n')}>
          {fold.shown.map((x, i) => (
            <div key={i} className="ngv__shot-row">
              <span className="ngv__shot">{x}</span>
              {i === fold.shown.length - 1 && fold.more > 0 && <span className="ngv__shot ngv__shot--more">+{fold.more}</span>}
            </div>
          ))}
        </div>
      )}
      <Preview film={film} attempt={chosen} fallback={fallback} hot={hot} id={c.id} onPlay={onPlay} canPlay={!!playableAttempt(c)} />
      {inFlight(c) && (
        <WaitRow item={c} typical={s.options.typical_sec} disabled={film.busy} offset={film.clockOffset} onCancel={onCancel} />
      )}
      {chosen?.free_id && <p className="ngv__dim">{t('graph.fromFree', { id: chosen.free_id })}</p>}
      {c.attempts.some((a, i) => a.late && a.state === 'succeeded' && i !== c.chosen) && (
        <p className="ngv__dim" data-testid="ngv-late">{t('film.lateHint')}</p>
      )}
      <p className="ngv__prompt" title={c.prompt}>{c.prompt}</p>
      <p className="ngv__dim">
        {t('graph.spent', { spent: yuan(spent), est: yuan(c.estimate_cny) })} · {t('graph.attempts', { n: c.attempts.length })}
      </p>
      {itemError(c, locale) && <p className="ngv__err" title={err}>{err}</p>}
      <div className="ngv__acts" onClick={(e) => e.stopPropagation()}>
        <SpendButton text={t(redo ? 'graph.redo' : 'graph.run', { cost: yuan(c.estimate_cny) })} cny={c.estimate_cny}
                     must={c.uncertain || needsConfirm(c, s)} disabled={lock}
                     onSpend={(cny) => film.runClipNow(c.id, cny)} />
        {(ok.length > 1 || (ok.length === 1 && at < 0)) && (
          <AttemptNav at={at} total={ok.length} disabled={lock} onPick={(k) => void film.choose(c.id, ok[k].i)} />
        )}
        <Button size="sm" variant="ghost" disabled={film.busy || inFlight(c)} onClick={onDerive}>{t('graph.derive')}</Button>
      </div>
    </>
  )
}

export function FreeCard({ node: n, s, film, blocked, hot, fallback, kfShots, assetOptions, onPlay, onCancel }: {
  node: FilmFreeNode; s: FilmSession; film: Film; blocked: string | null; hot: boolean
  fallback: string | null
  onPlay?: () => void
  onCancel?: () => void
  /** 有关键帧的镜头 */
  kfShots: string[]
  /** 参考可选项：左列有图的资产与风格图 */
  assetOptions: { id: string; name: string }[]
}) {
  const { t, locale } = useI18n()
  const tierHint = useTierHint()
  const withHint = useWithHint()
  const err = withHint(itemError(n, locale), hintFor(n.error_msg?.code, tierHint(s.tier), null))
  const lock = !!blocked || inFlight(n) || film.busy
  const { patchFree } = film
  const [text, setText] = useState(n.prompt)
  const [saving, setSaving] = useState<'idle' | 'saving' | 'saved'>('idle')
  const [askDel, setAskDel] = useState(false)
  // 服务端的正文变了（派生、别处改的）且本地没有未保存的输入：跟着服务端
  const server = useRef(n.prompt)
  useEffect(() => {
    setText((cur) => (cur === server.current ? n.prompt : cur))
    server.current = n.prompt
  }, [n.prompt])
  const timer = useRef<number | undefined>(undefined)
  const flush = useCallback((value: string) => {
    window.clearTimeout(timer.current)
    setSaving('saving')
    void patchFree(n.id, { prompt: value }).then(() => setSaving('saved'))
  }, [patchFree, n.id])
  useEffect(() => () => window.clearTimeout(timer.current), [])
  const onType = (value: string) => {
    setText(value)
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => flush(value), 800)
  }

  const max = s.options.max_refs
  const used = slotsNeeded(n.refs, n.first_frame, s)
  const toggleRef = (id: string) =>
    void patchFree(n.id, { refs: n.refs.includes(id) ? n.refs.filter((x) => x !== id) : [...n.refs, id] })
  const tails = tailSources(s).filter((id) => id !== n.id)
  const ok = n.attempts.map((a, i) => ({ a, i })).filter((x) => x.a.state === 'succeeded' && x.a.file)
  const at = ok.findIndex((x) => x.i === n.chosen)
  const chosen = chosenAttempt(n)
  const target = n.target ? s.clips.find((c) => c.id === n.target) : undefined
  const copy = target && chosen ? copyIndex(s, n, chosen) : -1
  const url = chosen?.file ? film.files[chosen.file] : undefined
  return (
    <>
      <header className="ngv__head">
        <b>{n.id}</b>
        <StatusPill tone={TONE[n.state]}>{label(FILM_STATE, n.state)}</StatusPill>
        <span className="ngv__dim">{n.target ? t('graph.free.replaces', { id: n.target }) : t('graph.free.standalone')}</span>
      </header>
      {n.target_lost && !n.target && <p className="ngv__warn">{t('graph.free.lost')}</p>}
      {n.over_refs && <p className="ngv__warn">{t('graph.free.overRefs', { n: used, max })}</p>}
      <Preview film={film} attempt={chosen} fallback={fallback} hot={hot} id={n.id} onPlay={onPlay} canPlay={!!playableAttempt(n)} />
      {inFlight(n) && (
        <WaitRow item={n} typical={s.options.typical_sec} disabled={film.busy} offset={film.clockOffset} onCancel={onCancel} />
      )}
      <div className="ngv__form" onClick={(e) => e.stopPropagation()}>
        <textarea className="ngv__text" value={text} disabled={lock} placeholder={t('graph.free.promptPh')}
                  onChange={(e) => onType(e.target.value)}
                  onBlur={() => { if (text !== n.prompt && saving !== 'saving') flush(text) }} />
        {saving !== 'idle' && (
          <span className="ngv__dim">{saving === 'saving' ? t('graph.free.saving') : t('graph.free.saved')}</span>
        )}
        <label className="ngv__field">{t('graph.free.duration')}
          {n.target ? <span>{t('graph.free.sec', { n: n.duration })}</span> : (
            <input key={n.duration} type="number" min={1} max={s.options.max_clip_sec} step={0.5}
                   defaultValue={n.duration} disabled={lock}
                   onBlur={(e) => {
                     const v = Number(e.target.value)
                     if (v && v !== n.duration) void patchFree(n.id, { duration: v })
                   }} />
          )}
        </label>
        <label className="ngv__field">{t('graph.free.firstFrame')}
          <select value={n.first_frame ?? ''} disabled={lock}
                  onChange={(e) => void patchFree(n.id, { first_frame: e.target.value || null })}>
            <option value="">{t('graph.free.none')}</option>
            {kfShots.map((id) => <option key={id} value={`keyframe:${id}`}>{t('graph.free.keyframe', { id })}</option>)}
            {tails.map((id) => <option key={id} value={`tail:${id}`}>{t('graph.free.tail', { id })}</option>)}
          </select>
        </label>
        <details className="ngv__refs">
          <summary>{t('graph.free.refs', { n: used, max })}</summary>
          {assetOptions.map((o) => {
            const on = n.refs.includes(o.id)
            const full = !on && slotsNeeded([...n.refs, o.id], n.first_frame, s) > max
            return (
              <label key={o.id} className="check">
                <input type="checkbox" checked={on} disabled={lock || full} onChange={() => toggleRef(o.id)} />
                {o.name}
              </label>
            )
          })}
        </details>
        <label className="ngv__field">{t('graph.free.target')}
          <select value={n.target ?? ''} disabled={lock}
                  onChange={(e) => void patchFree(n.id, { target: e.target.value || null })}>
            <option value="">{t('graph.free.noTarget')}</option>
            {s.clips.map((c) => <option key={c.id} value={c.id}>{c.id}</option>)}
          </select>
        </label>
      </div>
      {itemError(n, locale) && <p className="ngv__err" title={err}>{err}</p>}
      <div className="ngv__acts" onClick={(e) => e.stopPropagation()}>
        <SpendButton text={t('graph.free.generate', { cost: yuan(n.estimate_cny) })} cny={n.estimate_cny}
                     must={n.uncertain || n.estimate_cny > s.confirm_over_cny}
                     disabled={lock || n.over_refs || !n.prompt.trim()}
                     onSpend={(cny) => film.runFree(n.id, cny)} />
        {(ok.length > 1 || (ok.length === 1 && at < 0)) && (
          <AttemptNav at={at} total={ok.length} disabled={lock} onPick={(k) => void film.chooseFree(n.id, ok[k].i)} />
        )}
        {target && copy >= 0 && target.chosen !== copy && (
          <Button size="sm" variant="secondary" disabled={lock || inFlight(target)}
                  onClick={() => void film.choose(target.id, copy)}>{t('graph.free.adopt')}</Button>
        )}
        {!n.target && chosen?.file && (url
          ? <a className="tlc__linkbtn" href={url} download={`${n.id}.mp4`}>{t('graph.free.download')}</a>
          : <button type="button" className="tlc__linkbtn" onClick={() => film.ensure(chosen.file)}>
              {t('graph.free.download')}
            </button>)}
        {askDel ? (
          <span className="ngv__ask">
            <span>{t('graph.free.deleteConfirm')}</span>
            <Button size="sm" variant="destructive" disabled={lock} onClick={() => void film.deleteFree(n.id)}>
              {t('graph.free.delete')}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setAskDel(false)}>{t('graph.cancel')}</Button>
          </span>
        ) : (
          <Button size="sm" variant="ghost" disabled={lock}
                  onClick={() => (n.attempts.some((a) => a.state === 'succeeded') ? setAskDel(true)
                    : void film.deleteFree(n.id))}>
            {t('graph.free.delete')}
          </Button>
        )}
      </div>
    </>
  )
}
