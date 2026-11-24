import { useEffect, useRef, useState } from 'react'
import {
  ArrowRight, Ban, Clock, Cloud, Images, Lock, MapPin, Mic, Package, Plus,
  Scissors, Sparkles, Users, Volume2, X,
} from 'lucide-react'
import { SelectMenu } from '@/components/ui/select'
import { NumberField } from '@/components/ui/number-field'
import {
  addBeat, attachCard, detachCard, isAttached, removeBeat, setConstraints,
  setReferenceAssets, setVariant, splitList, updateBeat,
} from '../edit'
import {
  CAMERA_ANGLE, CAMERA_MOVEMENT, DERIVATION, DIALOGUE_TYPE, label,
  LOCATION_ANGLE, SHOT_SIZE, TIME_OF_DAY, TRANSITION,
} from '../labels'
import type { CardOption, Index } from '../resolve'
import type {
  CameraAngle, CameraMovement, LocationAngle, Shot, ShotSize, TimeOfDay, Transition,
} from '../types'
import { CardPicker, matchCards } from './CardPicker'
import { useI18n } from '@/i18n/core'

interface Props {
  shot: Shot
  idx: Index
  editing: boolean
  onPickUnit: (unitId: string) => void
  onChange: (patch: Partial<Shot>) => void
}

/** 枚举下拉：值域来自 schema，标签取中文表 */
function EnumSelect<T extends string>({ value, map, onChange, allowEmpty, label }: {
  value: T | undefined
  map: Record<T, string>
  onChange: (v: T | undefined) => void
  allowEmpty?: boolean
  label?: string
}) {
  const options: { value: string; label: string }[] =
    (Object.entries(map) as [T, string][]).map(([v, n]) => ({ value: v, label: n }))
  if (allowEmpty || value === undefined) options.unshift({ value: '', label: '—' })
  return (
    <SelectMenu
      value={value}
      options={options}
      ariaLabel={label ?? ''}
      onChange={(v) => onChange((v || undefined) as T | undefined)}
    />
  )
}

/** 变体描述常是一整段服装或形态说明，控件里只留一个能读的短标签；
 *  完整描述放进选项副行和悬停提示，避免把 447px 宽的镜头卡撑坏。 */
function compactVariant(name: string): string {
  const text = name.trim()
  if (text.length <= 12) return text
  const head = text.match(/^([^\uFF08(]{1,18})[\uFF08(]([^\uFF0C,\uFF1B;\uFF09)]{1,16})/)
  if (head) {
    const label = `${head[1]}\uFF08${head[2]}\uFF09`
    return label.length <= 26 ? label : `${label.slice(0, 25)}…`
  }
  const clause = text.split(/[\uFF0C,\uFF1B;\u3002]/)[0].trim()
  if (clause && clause.length <= 18) return `${clause}…`
  return `${text.slice(0, 17).replace(/[\uFF0C,\uFF1B;\u3001\s]+$/, '')}…`
}

function variantDescription(name: string, label: string): string | undefined {
  if (name === label) return undefined
  if (label.endsWith('…')) {
    const prefix = label.slice(0, -1)
    if (name.startsWith(prefix)) {
      const rest = name.slice(prefix.length).replace(/^[\uFF0C,\uFF1B;\u3002\s]+/, '')
      if (rest) return rest
    }
  }
  return name
}

/** 变体下拉：角色的服装 / 道具的形态。
 *  卡上没有变体集就不渲染——lint 明令「无 states 的道具不许填 state」，
 *  给个空下拉只会诱人填出非法值。 */
function VariantSelect({ card, value, shot, onChange }: {
  card: CardOption | undefined
  value: string | undefined
  shot: Shot
  onChange: (patch: Partial<Shot>) => void
}) {
  const { t } = useI18n()
  if (!card?.variants.length) return null
  const fallback = card.kind === 'props' ? t('shot.defaultForm') : t('shot.defaultOutfit')
  const options = card.variants.map((v) => {
    const name = v.name && v.name !== v.id ? v.name : v.id === 'default' ? fallback : v.id
    const label = compactVariant(name)
    return { value: v.id, label, description: variantDescription(name, label) }
  })
  return (
    <SelectMenu
      className="ed--var"
      menuMinWidth={260}
      value={value ?? ''}
      ariaLabel={card.kind === 'props' ? t('shot.propState') : t('shot.outfit')}
      options={options}
      onChange={(v) => onChange(setVariant(shot, card, v))}
    />
  )
}

function DetachButton({ card, shot, onChange }: {
  card: CardOption | undefined
  shot: Shot
  onChange: (patch: Partial<Shot>) => void
}) {
  const { t } = useI18n()
  if (!card) return null
  return (
    <button type="button" className="cast__remove" title={t('shot.detach', { name: card.name })}
            aria-label={t('shot.detach', { name: card.name })}
            onClick={() => onChange(detachCard(shot, card))}>
      <X size={13} aria-hidden />
      <span>{t('shot.remove')}</span>
    </button>
  )
}

/** 光标前的 @ 片段。遇到空白即失效——「@」后跟一段连续文字才算在选卡 */
const AT_MAX = 24
function atToken(text: string, caret: number): { from: number; query: string } | null {
  const head = text.slice(0, caret)
  const at = Math.max(head.lastIndexOf('@'), head.lastIndexOf('\uff20'))  // 全角 @：中文输入法给的是全角
  if (at < 0) return null
  const query = head.slice(at + 1)
  if (query.length > AT_MAX || /\s/.test(query)) return null
  return { from: at, query }
}

/** 选卡浮层的两种来源：点「＋挂卡」，或在画面描述里打 @ */
type PickState =
  | { mode: 'attach' }
  | { mode: 'refs' }
  | { mode: 'at'; from: number; caret: number; query: string }

export function ShotCard({ shot, idx, editing, onPickUnit, onChange }: Props) {
  const { t } = useI18n()
  const [pick, setPick] = useState<PickState | null>(null)
  const [active, setActive] = useState(0)
  const [attachQuery, setAttachQuery] = useState('')
  const areaRef = useRef<HTMLTextAreaElement | null>(null)
  const caretRef = useRef<number | null>(null)

  // @ 选完卡后把光标放回插入点之后，不然会被打回文末，接着打字就串行了
  useEffect(() => {
    if (caretRef.current !== null && areaRef.current) {
      areaRef.current.setSelectionRange(caretRef.current, caretRef.current)
      caretRef.current = null
    }
  })

  const closePick = () => { setPick(null); setActive(0); setAttachQuery('') }

  const attached = (c: CardOption) => isAttached(shot, c)
  const options = !pick ? []
    : pick.mode === 'refs'
      // 垫图只在「本镜头已挂的卡」里选：垫一张画面里根本没有的卡毫无意义
      ? idx.cardOptions.filter(attached)
      : matchCards(idx.cardOptions, pick.mode === 'at' ? pick.query : attachQuery)

  const pickCard = (card: CardOption) => {
    if (!pick) return
    if (pick.mode === 'refs') {
      const refs = shot.prompts?.reference_assets ?? []
      onChange(setReferenceAssets(shot, refs.includes(card.id)
        ? refs.filter((r) => r !== card.id) : [...refs, card.id]))
      return   // 垫图可以连着勾多张，不收浮层
    }
    if (pick.mode === 'at') {
      // 正文里落的是卡名（读起来仍是自然语句），形象绑定落在结构化引用上
      const text = shot.action.slice(0, pick.from) + card.name + shot.action.slice(pick.caret)
      caretRef.current = pick.from + card.name.length
      onChange({ action: text, ...attachCard(shot, card) })
    } else {
      onChange(attachCard(shot, card))
    }
    closePick()
  }

  /** 浮层开着时，方向键/回车归浮层，不该落进 textarea */
  const pickKeys = (e: React.KeyboardEvent) => {
    if (!pick || !options.length) return false
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive((i) => (i + 1) % options.length); return true }
    if (e.key === 'ArrowUp') { e.preventDefault(); setActive((i) => (i - 1 + options.length) % options.length); return true }
    if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); pickCard(options[active]); return true }
    if (e.key === 'Escape') { e.preventDefault(); closePick(); return true }
    return false
  }

  const cam = shot.camera

  const place = shot.location_ref
    ? idx.assetName(shot.location_ref) +
      (shot.location_angle ? t('shot.angled', { name: '', angle: label(LOCATION_ANGLE, shot.location_angle) }) : '')
    : ''

  const setCam = (k: 'movement' | 'angle', v: string | undefined) =>
    onChange({ camera: { ...shot.camera, [k]: v } })

  return (
    <article id={`shot-${shot.id}`} className={`shot shot--${shot.source?.derivation ?? 'explicit'}${
      editing ? ' shot--editing' : ''}`}>
      <header className="shot__head">
        <span className="shot__id">{shot.id}</span>
        {editing ? (
          <>
            <div className="shot__params">
              <label className="ed__field ed__field--num">
                <span className="ed__fieldlabel">{t('shot.duration')}</span>
                <span className="ed__numwrap">
                  <NumberField
                    className="ed ed--num"
                    min={1}
                    aria-label={t('shot.duration')}
                    value={shot.duration_sec}
                    onChange={(e) => onChange({ duration_sec: Number(e.target.value) || 1 })}
                  />
                  <span className="ed__unit">{t('shot.sec')}</span>
                </span>
              </label>
              <div className="ed__field">
                <span className="ed__fieldlabel">{t('shot.size')}</span>
                <EnumSelect<ShotSize>
                  value={shot.shot_size} map={SHOT_SIZE}
                  label={t('shot.size')}
                  onChange={(v) => v && onChange({ shot_size: v })} />
              </div>
              <div className="ed__field">
                <span className="ed__fieldlabel">{t('shot.movement')}</span>
                <EnumSelect<CameraMovement>
                  value={cam?.movement} map={CAMERA_MOVEMENT} allowEmpty
                  label={t('shot.movement')}
                  onChange={(v) => setCam('movement', v)} />
              </div>
              <div className="ed__field">
                <span className="ed__fieldlabel">{t('shot.angle')}</span>
                <EnumSelect<CameraAngle>
                  value={cam?.angle} map={CAMERA_ANGLE} allowEmpty
                  label={t('shot.angle')}
                  onChange={(v) => setCam('angle', v)} />
              </div>
              <div className="ed__field">
                <span className="ed__fieldlabel">{t('shot.transitionLabel')}</span>
                <EnumSelect<Transition>
                  value={shot.transition_out} map={TRANSITION} allowEmpty
                  label={t('shot.transitionLabel')}
                  onChange={(v) => onChange({ transition_out: v })} />
              </div>
            </div>
          </>
        ) : (
          <>
            <span className="chip">{label(SHOT_SIZE, shot.shot_size)}</span>
            {cam?.movement && <span className="chip">{label(CAMERA_MOVEMENT, cam.movement)}</span>}
            {cam?.angle && <span className="chip">{label(CAMERA_ANGLE, cam.angle)}</span>}
            <span className="chip chip--mono shot__dur">{shot.duration_sec}s</span>
          </>
        )}
        <span className={`deriv deriv--${shot.source?.derivation ?? 'explicit'}`}>
          {label(DERIVATION, shot.source?.derivation)}
        </span>
      </header>

      {editing ? (
        <div className="shot__place shot__place--ed">
          <div className="ed__field ed__field--wide">
            <span className="ed__fieldlabel">{t('shot.scene')}</span>
            <SelectMenu
              value={shot.location_ref ?? ''}
              ariaLabel={t('shot.scene')}
              options={[
                { value: '', label: t('shot.noPlace') },
                ...idx.locationOptions.map((l) => ({ value: l.id, label: `${l.id} ${l.name}` })),
              ]}
              onChange={(v) => onChange({ location_ref: v || undefined })}
            />
          </div>
          <div className="ed__field">
            <span className="ed__fieldlabel">{t('shot.locationAngle')}</span>
            <EnumSelect<LocationAngle>
              value={shot.location_angle} map={LOCATION_ANGLE} allowEmpty
              label={t('shot.locationAngle')}
              onChange={(v) => onChange({ location_angle: v })} />
          </div>
          <div className="ed__field">
            <span className="ed__fieldlabel">{t('shot.time')}</span>
            <EnumSelect<TimeOfDay>
              value={shot.time_of_day} map={TIME_OF_DAY} allowEmpty
              label={t('shot.time')}
              onChange={(v) => onChange({ time_of_day: v })} />
          </div>
          <label className="ed__field">
            <span className="ed__fieldlabel">{t('shot.weather')}</span>
            <input
              className="ed"
              placeholder={t('shot.weather')}
              aria-label={t('shot.weather')}
              value={shot.weather ?? ''}
              onChange={(e) => onChange({ weather: e.target.value || undefined })}
            />
          </label>
        </div>
      ) : (
        (place || shot.time_of_day || shot.weather) && (
          <div className="shot__place">
            {place && <span><MapPin size={12} aria-hidden />{place}</span>}
            {shot.time_of_day && <span><Clock size={12} aria-hidden />{label(TIME_OF_DAY, shot.time_of_day)}</span>}
            {shot.weather && <span><Cloud size={12} aria-hidden />{shot.weather}</span>}
          </div>
        )
      )}

      {editing ? (
        <>
          <div className="ed__field ed__field--stack">
            <span className="ed__fieldlabel">{t('shot.actionLabel')}</span>
            <div className="ed__at">
              <textarea
                ref={areaRef}
                className="ed ed--area"
                value={shot.action}
                rows={3}
                placeholder={t('shot.actionPh')}
                aria-label={t('shot.actionLabel')}
                onKeyDown={(e) => { if (pick?.mode === 'at') pickKeys(e) }}
                onChange={(e) => {
                  const caret = e.target.selectionStart ?? e.target.value.length
                  const tok = atToken(e.target.value, caret)
                  setPick(tok ? { mode: 'at', ...tok, caret } : null)
                  setActive(0)
                  onChange({ action: e.target.value })
                }}
                onBlur={() => { if (pick?.mode === 'at') closePick() }}
              />
              {pick?.mode === 'at' && (
                <CardPicker
                  options={options} active={active} onActive={setActive}
                  onPick={pickCard} onClose={closePick} isAttached={attached}
                  hint={t('shot.atHint')}
                />
              )}
            </div>
          </div>
          <label className="ed__field ed__field--stack">
            <span className="ed__fieldlabel">{t('shot.atmosphere')}</span>
            <input
              className="ed"
              placeholder={t('shot.atmospherePh')}
              aria-label={t('shot.atmosphere')}
              value={shot.atmosphere ?? ''}
              onChange={(e) => onChange({ atmosphere: e.target.value || undefined })}
            />
          </label>
        </>
      ) : (
        <>
          <p className="shot__action">{shot.action}</p>
          {(shot.atmosphere || !!shot.sfx?.length || shot.transition_out) && (
            <div className="shot__aux">
              {shot.atmosphere && (
                <p className="shot__atmo"><Sparkles size={12} aria-hidden />{shot.atmosphere}</p>
              )}
              {!!shot.sfx?.length && (
                <p className="shot__sfx"><Volume2 size={12} aria-hidden />{shot.sfx.join(' / ')}</p>
              )}
              {shot.transition_out && (
                <p className="shot__trans">
                  <ArrowRight size={12} aria-hidden />{t('shot.transition', { v: label(TRANSITION, shot.transition_out) })}
                </p>
              )}
            </div>
          )}
        </>
      )}

      {!!shot.characters?.length && (
        <div className={editing ? 'casting' : 'chips'}>
          {editing ? (
            <section className="casting__group">
              <header className="casting__head">
                <span className="casting__icon" aria-hidden><Users size={13} /></span>
                <div className="casting__heading">
                  <div className="casting__titleline">
                    <h4 className="casting__title">{t('shot.castHeading')}</h4>
                    <span className="casting__count">{shot.characters.length}</span>
                  </div>
                  <p className="casting__hint">{t('shot.castHint')}</p>
                </div>
              </header>
              <div className="casting__list">
                {shot.characters.map((c, i) => {
                  const card = idx.card(c.ref)
                  return (
                    <div className="cast" key={`${c.ref}-${i}`}>
                      <div className="cast__head">
                        <span className="cast__avatar" aria-hidden>
                          {idx.assetName(c.ref).slice(0, 1)}
                        </span>
                        <span className="cast__name">{idx.assetName(c.ref)}</span>
                        <span className="cast__ref">{c.ref}</span>
                        <DetachButton card={card} shot={shot} onChange={onChange} />
                      </div>
                      <div className="cast__fields">
                        <label className="ed__field cast__field cast__field--action">
                          <span className="ed__fieldlabel">{t('shot.action')}</span>
                          <input
                            className="ed"
                            placeholder={t('shot.castActionPh')}
                            aria-label={t('shot.action')}
                            value={c.action ?? ''}
                            onChange={(e) => onChange({
                              characters: shot.characters!.map((x, j) =>
                                j === i ? { ...x, action: e.target.value || undefined } : x),
                            })}
                          />
                        </label>
                        {!!card?.variants.length && (
                          <div className="ed__field cast__field cast__field--variant">
                            <span className="ed__fieldlabel">{t('shot.outfitShort')}</span>
                            <VariantSelect card={card} value={c.outfit} shot={shot}
                                           onChange={onChange} />
                          </div>
                        )}
                        <label className="ed__field cast__field">
                          <span className="ed__fieldlabel">{t('shot.expression')}</span>
                          <input
                            className="ed"
                            placeholder={t('shot.expressionPh')}
                            aria-label={t('shot.expression')}
                            value={c.expression ?? ''}
                            onChange={(e) => onChange({
                              characters: shot.characters!.map((x, j) =>
                                j === i ? { ...x, expression: e.target.value || undefined } : x),
                            })}
                          />
                        </label>
                        <label className="ed__field cast__field">
                          <span className="ed__fieldlabel">{t('shot.position')}</span>
                          <input
                            className="ed"
                            placeholder={t('shot.positionPh')}
                            aria-label={t('shot.position')}
                            value={c.position ?? ''}
                            onChange={(e) => onChange({
                              characters: shot.characters!.map((x, j) =>
                                j === i ? { ...x, position: e.target.value || undefined } : x),
                            })}
                          />
                        </label>
                      </div>
                    </div>
                  )
                })}
              </div>
            </section>
          ) : (
            shot.characters.map((c, i) => (
              <span className="chip chip--char" key={`${c.ref}-${i}`}>
                <b>{idx.assetName(c.ref)}</b>
                {c.outfit && c.outfit !== 'default' && <em>{c.outfit}</em>}
                {c.expression && <em>{c.expression}</em>}
                {c.action && <span className="chip__note">{c.action}</span>}
              </span>
            ))
          )}
        </div>
      )}

      {editing && !!shot.prop_refs?.length && (
        <section className="casting__group casting__group--props">
          <header className="casting__head">
            <span className="casting__icon" aria-hidden><Package size={13} /></span>
            <div className="casting__heading">
              <div className="casting__titleline">
                <h4 className="casting__title">{t('shot.propHeading')}</h4>
                <span className="casting__count">{shot.prop_refs.length}</span>
              </div>
              <p className="casting__hint">{t('shot.propHint')}</p>
            </div>
          </header>
          <div className="casting__list">
            {shot.prop_refs.map((p, i) => {
              const card = idx.card(p.ref)
              return (
                <div className="proprow" key={`${p.ref}-${i}`}>
                  <div className="proprow__identity">
                    <span className="proprow__icon" aria-hidden><Package size={12} /></span>
                    <span className="proprow__name">{idx.assetName(p.ref)}</span>
                    <span className="proprow__ref">{p.ref}</span>
                  </div>
                  {card?.variants.length ? (
                    <div className="proprow__field">
                      <span className="proprow__label">{t('shot.propStateShort')}</span>
                      <VariantSelect card={card} value={p.state} shot={shot} onChange={onChange} />
                    </div>
                  ) : (
                    <span className="proprow__static">{t('shot.fixedForm')}</span>
                  )}
                  <DetachButton card={card} shot={shot} onChange={onChange} />
                </div>
              )
            })}
          </div>
        </section>
      )}

      {!editing && !!shot.prop_refs?.length && (
        <div className="chips">
          {shot.prop_refs.map((p, i) => (
            <span className="chip chip--prop" key={`${p.ref}-${i}`}>
              {idx.assetName(p.ref)}
              {p.state && <em>{p.state}</em>}
            </span>
          ))}
        </div>
      )}

      {/* 镜头内阶段：一个不切的长镜头里，情绪与灯光逐级推进 */}
      {!editing && !!shot.beats?.length && (
        <ol className="beats">
          {shot.beats.map((b, i) => (
            <li className="beat" key={i}>
              <span className="beat__n">{i + 1}</span>
              <span className="beat__sec">{b.duration_sec}s</span>
              <span className="beat__body">
                <b>{b.action}</b>
                {b.expression && <em>{t('shot.beatExpr', { v: b.expression })}</em>}
                {b.lighting && <em>{t('shot.beatLight', { v: b.lighting })}</em>}
                {b.camera_note && <em>{t('shot.beatCam', { v: b.camera_note })}</em>}
              </span>
            </li>
          ))}
        </ol>
      )}

      {editing && !!shot.beats?.length && (
        <ol className="beats beats--ed">
          {shot.beats.map((b, i) => (
            <li className="beat beat--ed" key={i}>
              <span className="beat__n">{i + 1}</span>
              <NumberField
                className="ed ed--num" step="0.5" min="0.5"
                title={t('shot.beatSecTip')}
                value={b.duration_sec}
                onChange={(e) => onChange(updateBeat(shot, i,
                  { duration_sec: Number(e.target.value) || 0 }))}
              />
              <span className="ed__unit">{t('shot.sec')}</span>
              <input
                className="ed" placeholder={t('shot.beatAction')} aria-label={t('shot.beatAction')} value={b.action}
                onChange={(e) => onChange(updateBeat(shot, i, { action: e.target.value }))}
              />
              <input
                className="ed" placeholder={t('shot.beatExprPh')} value={b.expression ?? ''}
                aria-label={t('shot.beatExprPh')}
                onChange={(e) => onChange(updateBeat(shot, i,
                  { expression: e.target.value || undefined }))}
              />
              <input
                className="ed" placeholder={t('shot.beatLightPh')}
                aria-label={t('shot.beatLightPh')}
                value={b.lighting ?? ''}
                onChange={(e) => onChange(updateBeat(shot, i,
                  { lighting: e.target.value || undefined }))}
              />
              <input
                className="ed" placeholder={t('shot.beatCamPh')} value={b.camera_note ?? ''}
                aria-label={t('shot.beatCamPh')}
                onChange={(e) => onChange(updateBeat(shot, i,
                  { camera_note: e.target.value || undefined }))}
              />
              <button type="button" className="ed__x" title={t('shot.beatDel')}
                      aria-label={t('shot.beatDel')}
                      onClick={() => onChange(removeBeat(shot, i))}>×</button>
            </li>
          ))}
        </ol>
      )}

      {!editing && !!shot.constraints?.length && (
        <p className="cons">
          <span className="cons__tag">{t('shot.consTag')}</span>
          {shot.constraints.join(' · ')}
        </p>
      )}

      {editing && (
        <div className="ed__attach">
          <span className="ed__attachbox">
            <button type="button" className="edtool edtool--attach"
                    onClick={() => setPick(pick?.mode === 'attach' ? null : { mode: 'attach' })}>
              <Plus size={14} aria-hidden />
              {t('shot.attach')}
            </button>
            {pick?.mode === 'attach' && (
              <span className="cpick__wrap">
                <input
                  className="ed ed--slim" autoFocus
                  placeholder={t('shot.attachPh')}
                  value={attachQuery}
                  onChange={(e) => { setAttachQuery(e.target.value); setActive(0) }}
                  onKeyDown={pickKeys}
                />
                <CardPicker
                  options={options} active={active} onActive={setActive}
                  onPick={pickCard} onClose={closePick} isAttached={attached}
                  hint={t('shot.attachHint')}
                />
              </span>
            )}
          </span>

          <button type="button" className="edtool edtool--split"
                  title={t('shot.splitTip')}
                  onClick={() => onChange(addBeat(shot))}>
            <Scissors size={13} aria-hidden />
            {shot.beats?.length ? t('shot.addBeat') : t('shot.splitBeats')}
          </button>

          <span className="ed__attachbox">
            <button type="button" className="edtool edtool--refs"
                    title={t('shot.refsTip')}
                    onClick={() => setPick(pick?.mode === 'refs' ? null : { mode: 'refs' })}>
              <Images size={14} aria-hidden />
              {t('shot.refs', { n: shot.prompts?.reference_assets?.length || 0 })}
            </button>
            {pick?.mode === 'refs' && (
              <CardPicker
                options={options} active={active} onActive={setActive}
                onPick={pickCard} onClose={closePick}
                isAttached={(c) => !!shot.prompts?.reference_assets?.includes(c.id)}
                hint={t('shot.refsHint')}
              />
            )}
          </span>

          <span className="ed__cons">
            <span className="ed__conslabel" title={t('shot.consLabelTip')}>
              <Ban size={12} aria-hidden />
              {t('shot.consLabel')}
            </span>
            <input
              className="ed"
              placeholder={t('shot.consPh')}
              aria-label={t('shot.consLabel')}
              value={(shot.constraints ?? []).join(' / ')}
              onChange={(e) => onChange(setConstraints(splitList(e.target.value)))}
            />
          </span>

          {!!shot.prompts?.reference_assets?.length && (
            <span className="chips chips--refs">
              {shot.prompts.reference_assets.map((id) => (
                <span className="chip chip--ref" key={id}>
                  {id} {idx.assetName(id)}
                  <button type="button" className="chip__x" title={t('shot.unref')}
                          onClick={() => onChange(setReferenceAssets(shot,
                            shot.prompts!.reference_assets!.filter((r) => r !== id)))}>×</button>
                </span>
              ))}
            </span>
          )}
        </div>
      )}

      {editing && (
        <label className="ed__field ed__field--stack">
          <span className="ed__fieldlabel">{t('shot.sfxLabel')}</span>
          <input
            className="ed"
            placeholder={t('shot.sfxPh')}
            aria-label={t('shot.sfxLabel')}
            value={(shot.sfx ?? []).join(' / ')}
            onChange={(e) => {
              const list = splitList(e.target.value)
              onChange({ sfx: list.length ? list : undefined })
            }}
          />
        </label>
      )}

      {(!!shot.dialogue?.length || !!shot.narration?.text) && (
        <div className="shot__voice">
          {!!shot.dialogue?.length && (
            <div className="lines">
              {shot.dialogue.map((d, i) => (
                <p className="line line--dia" key={i}>
                  {d.character_ref && <span className="line__who">{idx.assetName(d.character_ref)}</span>}
                  {d.type && <span className="chip">{label(DIALOGUE_TYPE, d.type)}</span>}
                  <span className="line__text">{d.text}</span>
                  {editing ? (
                    <input
                      className="ed ed--slim"
                      placeholder={t('shot.emotionPh')}
                      value={d.emotion ?? ''}
                      onChange={(e) => onChange({
                        dialogue: shot.dialogue!.map((x, j) =>
                          j === i ? { ...x, emotion: e.target.value || undefined } : x),
                      })}
                    />
                  ) : (
                    d.emotion && <span className="line__emo">{d.emotion}</span>
                  )}
                  {d.verbatim === false && <span className="chip chip--warn">{t('shot.notVerbatim')}</span>}
                </p>
              ))}
            </div>
          )}

          {shot.narration?.text && (
            <div className="lines">
              <p className="line line--nar">
                <span className="line__who"><Mic size={12} aria-hidden />{t('shot.narrator')}</span>
                <span className="line__text">{shot.narration.text}</span>
                {editing && (
                  <span className="lock" title={t('shot.narLock')}>
                    <Lock size={12} aria-label={t('shot.lock')} />
                  </span>
                )}
              </p>
            </div>
          )}
        </div>
      )}

      <footer className="shot__foot">
        {shot.source?.unit_refs?.map((u) => (
          <button
            className="uref"
            key={u}
            type="button"
            title={idx.unitText(u)}
            onClick={() => onPickUnit(u)}
          >
            {u}
          </button>
        ))}
        {editing && (
          <span className="lock" title={t('shot.srcLockTip')}>
            <Lock size={12} aria-hidden />{t('shot.srcLock')}
          </span>
        )}
        {shot.source?.note && <span className="shot__note">{shot.source.note}</span>}
      </footer>
    </article>
  )
}
