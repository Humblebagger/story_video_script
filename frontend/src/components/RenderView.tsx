import { ChevronRight } from 'lucide-react'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { ApiError, renderPlan } from '../api'
import type { RenderPack, Storyboard, VerificationReport } from '../types'
import { VerificationPanel } from './VerificationPanel'
import { tr, useI18n } from '@/i18n/core'
import { errValue, formatMsg } from '@/i18n/serverMsg'
import type { MsgLike } from '@/i18n/serverMsg'

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
 *  这一页刻意把「费用」放在最前面。按公开资费，《药》这样一章 11 分钟的片子
 *  一次过就是三位数，抽卡到能用是四位数——在花钱之前先把提示词逐条看一遍，
 *  是这个界面存在的唯一理由。
 *
 *  出图排在出视频之前：资产图没出，就只能纯文生视频，每个镜头换一张脸，
 *  整套资产引用制的防漂移能力等于白做。 */
export function RenderView({ doc, runId }: Props) {
  const { t, locale } = useI18n()
  const [pack, setPack] = useState<RenderPack | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<MsgLike>(null)
  /** 被完整性检查拦下时服务端附的报告——光说「422」用户没法据此修改 */
  const [blocked, setBlocked] = useState<VerificationReport | null>(null)
  const [maxClip, setMaxClip] = useState(15)
  const [model, setModel] = useState('standard')
  /** 拿真实账单标定过就填这里；空表示用推算值 */
  const [rate, setRate] = useState('')
  const [open, setOpen] = useState<string | null>(null)
  /** 「费用怎么算」折叠 */
  const [basisOpen, setBasisOpen] = useState(false)
  /** 只渲染选中的 clip。这是唯一真能把钱包住的手段——不动 IR，先渲一集看效果 */
  const [picked, setPicked] = useState<Set<string> | null>(null)

  const build = async (over: {
    maxClipSeconds?: number; model?: string; cnyPerSecond?: number | null
  } = {}) => {
    setBusy(true)
    setErr(null)
    setBlocked(null)
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
      setErr(errValue(e))
      if (e instanceof ApiError) setBlocked(e.verification)
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
  const stem = `${plan?.work_title || tr('renderPack.fileStem')}_${plan?.chapter || ''}`.replace(/[/\\:*?"<>|]/g, '_')

  return (
    <div className="rend">
      <header className="rend__head">
        <div>
          <h3>{t('renderPack.title')}</h3>
          <p className="rend__hint">
            {t('renderPack.hint')}
          </p>
        </div>
        <div className="rend__acts">
          <label className="rend__len">
            {t('renderPack.maxClip')}
            <select value={maxClip} disabled={busy}
                    onChange={(e) => {
                      const v = Number(e.target.value)
                      setMaxClip(v)
                      void build({ maxClipSeconds: v })
                    }}>
              {CLIP_LENGTHS.map((s) => <option key={s} value={s}>{t('renderPack.secs', { s })}</option>)}
            </select>
          </label>
          <label className="rend__len">
            {t('renderPack.tier')}
            <select value={model} disabled={busy}
                    onChange={(e) => { setModel(e.target.value); void build({ model: e.target.value }) }}>
              {(plan?.tiers ?? [{ id: 'standard', label: t('renderPack.tierDefault') }])
                .map((tier) => <option key={tier.id} value={tier.id}>{tier.label}</option>)}
            </select>
          </label>
          <label className="rend__len" title={t('renderPack.rateTip')}>
            {t('renderPack.rate')}
            <input className="rend__rate" value={rate} placeholder={t('renderPack.ratePh')}
                   inputMode="decimal" disabled={busy}
                   onChange={(e) => setRate(e.target.value)}
                   onBlur={() => plan && void build()} />
          </label>
          <Button size="sm" disabled={busy} onClick={() => void build()}>
            {busy ? t('renderPack.building') : plan ? t('renderPack.rebuild') : t('renderPack.build')}
          </Button>
        </div>
      </header>

      {err && <p className="alert">{formatMsg(err, locale)}</p>}
      {blocked && <VerificationPanel report={blocked} doc={doc} origin="render" />}

      {!plan && !busy && !err && (
        <p className="empty">{t('renderPack.empty')}</p>
      )}

      {plan && (
        <>
          <div className="rend__cost">
            <div className="rend__num">
              <b>{plan.estimate.clips}</b><span>{t('renderPack.clips')}</span>
            </div>
            <div className="rend__num">
              <b>{Math.round(plan.estimate.playable_seconds)}</b>
              <span>
                {t('renderPack.playable')}
                {plan.estimate.speech_overflow_sec > 0 &&
                  t('renderPack.overflow', {
                    nominal: Math.round(plan.estimate.seconds),
                    extra: Math.round(plan.estimate.speech_overflow_sec),
                  })}
              </span>
            </div>
            <div className="rend__num rend__num--warn">
              <b>{plan.estimate.asset_images_missing}</b>
              <span>{t('renderPack.imgsMissing', { total: plan.estimate.asset_images_total })}</span>
            </div>
            <div className="rend__num rend__num--cost">
              <b>¥{partial ? chosenCny : plan.estimate.cny_once}–{
                partial ? Math.round(chosenCny * plan.estimate.retry_factor * 10) / 10
                        : plan.estimate.cny_with_retries}</b>
              <span>
                {plan.estimate.calibrated ? t('renderPack.cost') : t('renderPack.costEst')}
                {t('renderPack.retries', { n: plan.estimate.retry_factor })}
                {partial && t('renderPack.onlyChosen', { n: chosen.length, total: plan.clips.length })}
              </span>
            </div>
          </div>
          <div className="rend__basis">
            <button type="button" className="rend__basis-head" aria-expanded={basisOpen}
                    onClick={() => setBasisOpen(!basisOpen)}>
              <ChevronRight size={14} aria-hidden />
              <b>{t('renderPack.basis')}</b>
              <span>
                {plan.estimate.calibrated
                  ? t('renderPack.basisCal', { rate: plan.estimate.cny_per_second })
                  : t('renderPack.basisEst', { model: plan.estimate.model_label, rate: plan.estimate.cny_per_second })}
                {t('renderPack.basisTail')}
              </span>
            </button>
            <div className="rend__basis-body" hidden={!basisOpen}>
              <p className="rend__note">{plan.estimate.note}</p>
              <ul className="rend__caveats">
                {plan.estimate.caveats.map((c) => <li key={c}>{c}</li>)}
              </ul>
              <p className="rend__note">
                {t('renderPack.resNote', {
                  res: plan.estimate.resolutions,
                  price: plan.estimate.rate.cny_per_million_tokens,
                  tps: plan.estimate.rate.tokens_per_second,
                })}
              </p>
            </div>
          </div>

          {plan.estimate.asset_images_missing > 0 && (
            <p className="rend__warn">
              {t('renderPack.warnA')}<b>{plan.estimate.asset_images_missing}</b>{t('renderPack.warnB')}
            </p>
          )}

          <div className="rend__dl">
            <Button size="sm" variant="outline" onClick={() => saveFile(
              `${stem}_${t('renderPack.fileList')}${partial ? t('renderPack.fileSel', { n: chosen.length }) : ''}.json`,
              JSON.stringify(partial ? { ...plan, clips: chosen } : plan, null, 2),
              'application/json;charset=utf-8')}>
              {t('renderPack.dlList')}
            </Button>
            {pack!.packs.map((p) => (
              <Button size="sm" variant="ghost" key={p.episode}
                      onClick={() => saveFile(`${stem}_${p.episode}_${t('renderPack.filePack')}.md`, p.markdown)}>
                {t('renderPack.dlPack', { ep: p.episode })}
              </Button>
            ))}
          </div>

          <h4 className="rend__sub">{t('renderPack.assetList', { n: plan.assets.length })}</h4>
          <ul className="rend__assets">
            {plan.assets.map((a) => (
              <li className="rasset" key={a.id}>
                <div className="rasset__top">
                  <span className="rasset__id">{a.id}</span>
                  <b>{a.name}</b>
                  <span className="chip">{a.kind_zh}</span>
                  <span className={`rasset__imgs${
                    a.have_images >= a.need_images ? ' is-ok' : ''}`}>
                    {t('renderPack.imgCount', { have: a.have_images, need: a.need_images })}
                  </span>
                </div>
                <p className="rasset__prompt">{a.image_prompt}</p>
                {a.variants.map((v) => (
                  <p className="rasset__var" key={v.id}>
                    <span>{v.id}</span>{v.description}
                  </p>
                ))}
                {!!a.constraints.length && (
                  <p className="rasset__cons">{t('renderPack.avoid', { list: a.constraints.join(t('renderPack.avoidSep')) })}</p>
                )}
              </li>
            ))}
          </ul>

          <div className="rend__pick">
            <h4 className="rend__sub">
              {t('renderPack.clipTitle', {
                count: partial ? t('renderPack.clipCountSel', { n: chosen.length, total: plan.clips.length })
                  : plan.clips.length,
                sec: chosenSec, cny: chosenCny,
              })}
            </h4>
            <span className="rend__eps">
              {t('renderPack.onlyRender')}
              {[...new Set(plan.clips.map((c) => c.episode))].map((ep) => (
                <Button size="xs" variant="outline" key={ep}
                        onClick={() => onlyEpisode(ep)}>{ep}</Button>
              ))}
              <Button size="xs" variant="ghost"
                      onClick={() => setPicked(null)}>{t('renderPack.all')}</Button>
            </span>
          </div>
          <ul className="rend__clips">
            {plan.clips.map((c) => (
              <li className={`rclip${picked && !picked.has(c.id) ? ' is-off' : ''}`} key={c.id}>
                <span className="rclip__pick">
                  <input type="checkbox" checked={!picked || picked.has(c.id)}
                         title={t('renderPack.pickTip')}
                         onChange={() => toggle(c.id)} />
                </span>
                <button className="rclip__head" onClick={() =>
                  setOpen(open === c.id ? null : c.id)}>
                  <span className="rclip__id">{c.id}</span>
                  <span className="rclip__dur" title={c.speech_overflow > 0
                    ? t('renderPack.overTip', { nominal: c.duration_sec, play: c.playable_sec }) : ''}>
                    {c.playable_sec}s
                    {c.speech_overflow > 0 && <em className="rclip__over">+{c.speech_overflow}</em>}
                  </span>
                  <span className="rclip__shots">{c.shots.join(' + ')}</span>
                  <span className="rclip__refs">{t('renderPack.refsOf', { list: c.reference_assets.join(t('common.listSep')) || t('renderPack.none') })}</span>
                  <span className="rclip__caret">{open === c.id ? t('renderPack.collapse') : t('renderPack.showPrompt')}</span>
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
