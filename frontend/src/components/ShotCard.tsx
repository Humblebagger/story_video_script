import { useEffect, useRef, useState } from 'react'
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

interface Props {
  shot: Shot
  idx: Index
  editing: boolean
  onPickUnit: (unitId: string) => void
  onChange: (patch: Partial<Shot>) => void
}

/** 枚举下拉：值域来自 schema，标签取中文表 */
function EnumSelect<T extends string>({ value, map, onChange, allowEmpty }: {
  value: T | undefined
  map: Record<T, string>
  onChange: (v: T | undefined) => void
  allowEmpty?: boolean
}) {
  return (
    <select
      className="ed ed--sel"
      value={value ?? ''}
      onChange={(e) => onChange((e.target.value || undefined) as T | undefined)}
    >
      {(allowEmpty || value === undefined) && <option value="">—</option>}
      {(Object.entries(map) as [T, string][]).map(([v, n]) => (
        <option key={v} value={v}>{n}</option>
      ))}
    </select>
  )
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
  if (!card?.variants.length) return null
  return (
    <select
      className="ed ed--sel ed--var"
      value={value ?? ''}
      title={card.kind === 'props' ? '本镜头的形态' : '本镜头的服装'}
      onChange={(e) => onChange(setVariant(shot, card, e.target.value))}
    >
      {card.variants.map((v) => (
        <option key={v.id} value={v.id}>
          {v.name && v.name !== v.id
            ? `${v.id} · ${v.name.length > 14 ? v.name.slice(0, 14) + '…' : v.name}`
            : v.id}
        </option>
      ))}
    </select>
  )
}

function DetachButton({ card, shot, onChange }: {
  card: CardOption | undefined
  shot: Shot
  onChange: (patch: Partial<Shot>) => void
}) {
  if (!card) return null
  return (
    <button type="button" className="ed__x" title={`把 ${card.name} 从本镜头摘掉`}
            onClick={() => onChange(detachCard(shot, card))}>×</button>
  )
}

/** 光标前的 @ 片段。遇到空白即失效——「@」后跟一段连续文字才算在选卡 */
const AT_MAX = 24
function atToken(text: string, caret: number): { from: number; query: string } | null {
  const head = text.slice(0, caret)
  const at = Math.max(head.lastIndexOf('@'), head.lastIndexOf('＠'))  // 中文输入法给的是全角
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
  const camText = [
    cam?.movement && label(CAMERA_MOVEMENT, cam.movement),
    cam?.angle && label(CAMERA_ANGLE, cam.angle),
  ].filter(Boolean).join(' · ')

  const place = shot.location_ref
    ? idx.assetName(shot.location_ref) +
      (shot.location_angle ? `（${label(LOCATION_ANGLE, shot.location_angle)}）` : '')
    : ''

  const setCam = (k: 'movement' | 'angle', v: string | undefined) =>
    onChange({ camera: { ...shot.camera, [k]: v } })

  return (
    <article className={`shot shot--${shot.source?.derivation ?? 'explicit'}${
      editing ? ' shot--editing' : ''}`}>
      <header className="shot__head">
        <span className="shot__id">{shot.id}</span>
        {editing ? (
          <>
            <input
              className="ed ed--num"
              type="number"
              min={1}
              value={shot.duration_sec}
              onChange={(e) => onChange({ duration_sec: Number(e.target.value) || 1 })}
            />
            <span className="ed__unit">秒</span>
            <EnumSelect<ShotSize>
              value={shot.shot_size} map={SHOT_SIZE}
              onChange={(v) => v && onChange({ shot_size: v })} />
            <EnumSelect<CameraMovement>
              value={cam?.movement} map={CAMERA_MOVEMENT} allowEmpty
              onChange={(v) => setCam('movement', v)} />
            <EnumSelect<CameraAngle>
              value={cam?.angle} map={CAMERA_ANGLE} allowEmpty
              onChange={(v) => setCam('angle', v)} />
            <EnumSelect<Transition>
              value={shot.transition_out} map={TRANSITION} allowEmpty
              onChange={(v) => onChange({ transition_out: v })} />
          </>
        ) : (
          <>
            <span className="shot__dur">{shot.duration_sec}s</span>
            <span className="tag tag--size">{label(SHOT_SIZE, shot.shot_size)}</span>
            {camText && <span className="tag">{camText}</span>}
            {shot.transition_out && (
              <span className="tag tag--ghost">→ {label(TRANSITION, shot.transition_out)}</span>
            )}
          </>
        )}
      </header>

      {editing ? (
        <div className="shot__place shot__place--ed">
          <select
            className="ed ed--sel"
            value={shot.location_ref ?? ''}
            onChange={(e) => onChange({ location_ref: e.target.value || undefined })}
          >
            <option value="">— 无场景 —</option>
            {idx.locationOptions.map((l) => (
              <option key={l.id} value={l.id}>{l.id} {l.name}</option>
            ))}
          </select>
          <EnumSelect<LocationAngle>
            value={shot.location_angle} map={LOCATION_ANGLE} allowEmpty
            onChange={(v) => onChange({ location_angle: v })} />
          <EnumSelect<TimeOfDay>
            value={shot.time_of_day} map={TIME_OF_DAY} allowEmpty
            onChange={(v) => onChange({ time_of_day: v })} />
          <input
            className="ed"
            placeholder="天气"
            value={shot.weather ?? ''}
            onChange={(e) => onChange({ weather: e.target.value || undefined })}
          />
        </div>
      ) : (
        (place || shot.time_of_day || shot.weather) && (
          <div className="shot__place">
            {place && <span>📍 {place}</span>}
            {shot.time_of_day && <span>🕰 {label(TIME_OF_DAY, shot.time_of_day)}</span>}
            {shot.weather && <span>☁ {shot.weather}</span>}
          </div>
        )
      )}

      {editing ? (
        <>
          <div className="ed__at">
            <textarea
              ref={areaRef}
              className="ed ed--area"
              value={shot.action}
              rows={3}
              placeholder="画面内容（打 @ 可挂资产卡）"
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
                hint="选中即挂上引用：角色锁形象、道具锁形态、场景锁机位"
              />
            )}
          </div>
          <input
            className="ed"
            placeholder="氛围"
            value={shot.atmosphere ?? ''}
            onChange={(e) => onChange({ atmosphere: e.target.value || undefined })}
          />
        </>
      ) : (
        <>
          <p className="shot__action">{shot.action}</p>
          {shot.atmosphere && <p className="shot__atmo">{shot.atmosphere}</p>}
        </>
      )}

      {!!shot.characters?.length && (
        <div className={editing ? 'ed__rows' : 'chips'}>
          {shot.characters.map((c, i) => (editing ? (
            <div className="ed__row" key={`${c.ref}-${i}`}>
              <b className="ed__label">{idx.assetName(c.ref)}</b>
              <VariantSelect card={idx.card(c.ref)} value={c.outfit} shot={shot}
                             onChange={onChange} />
              {(['expression', 'action', 'position'] as const).map((k) => (
                <input
                  key={k}
                  className="ed"
                  placeholder={{ expression: '表情', action: '动作', position: '位置' }[k]}
                  value={c[k] ?? ''}
                  onChange={(e) => onChange({
                    characters: shot.characters!.map((x, j) =>
                      j === i ? { ...x, [k]: e.target.value || undefined } : x),
                  })}
                />
              ))}
              <DetachButton card={idx.card(c.ref)} shot={shot} onChange={onChange} />
            </div>
          ) : (
            <span className="chip chip--char" key={`${c.ref}-${i}`}>
              <b>{idx.assetName(c.ref)}</b>
              {c.outfit && c.outfit !== 'default' && <em>{c.outfit}</em>}
              {c.expression && <em>{c.expression}</em>}
              {c.action && <span className="chip__note">{c.action}</span>}
            </span>
          )))}
        </div>
      )}

      {editing && !!shot.prop_refs?.length && (
        <div className="ed__rows">
          {shot.prop_refs.map((p, i) => (
            <div className="ed__row" key={`${p.ref}-${i}`}>
              <b className="ed__label">{idx.assetName(p.ref)}</b>
              <VariantSelect card={idx.card(p.ref)} value={p.state} shot={shot}
                             onChange={onChange} />
              <DetachButton card={idx.card(p.ref)} shot={shot} onChange={onChange} />
            </div>
          ))}
        </div>
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
                {b.expression && <em>表演：{b.expression}</em>}
                {b.lighting && <em>光：{b.lighting}</em>}
                {b.camera_note && <em>机位：{b.camera_note}</em>}
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
              <input
                className="ed ed--num" type="number" step="0.5" min="0.5"
                title="本拍时长（镜头总时长自动跟着各拍之和走）"
                value={b.duration_sec}
                onChange={(e) => onChange(updateBeat(shot, i,
                  { duration_sec: Number(e.target.value) || 0 }))}
              />
              <span className="ed__unit">秒</span>
              <input
                className="ed" placeholder="本拍画面" value={b.action}
                onChange={(e) => onChange(updateBeat(shot, i, { action: e.target.value }))}
              />
              <input
                className="ed" placeholder="表演" value={b.expression ?? ''}
                onChange={(e) => onChange(updateBeat(shot, i,
                  { expression: e.target.value || undefined }))}
              />
              <input
                className="ed" placeholder="光：正面柔光 / 右侧光 / 背光轮廓"
                value={b.lighting ?? ''}
                onChange={(e) => onChange(updateBeat(shot, i,
                  { lighting: e.target.value || undefined }))}
              />
              <input
                className="ed" placeholder="机位补充" value={b.camera_note ?? ''}
                onChange={(e) => onChange(updateBeat(shot, i,
                  { camera_note: e.target.value || undefined }))}
              />
              <button type="button" className="ed__x" title="删掉这一拍"
                      onClick={() => onChange(removeBeat(shot, i))}>×</button>
            </li>
          ))}
        </ol>
      )}

      {!editing && !!shot.constraints?.length && (
        <p className="cons">
          <span className="cons__tag">不要</span>
          {shot.constraints.join(' · ')}
        </p>
      )}

      {editing && (
        <div className="ed__attach">
          <span className="ed__attachbox">
            <button type="button" className="btn btn--sm btn--ghost"
                    onClick={() => setPick(pick?.mode === 'attach' ? null : { mode: 'attach' })}>
              ＋ 挂卡
            </button>
            {pick?.mode === 'attach' && (
              <span className="cpick__wrap">
                <input
                  className="ed ed--slim" autoFocus
                  placeholder="搜卡片：ID / 名称 / 别名"
                  value={attachQuery}
                  onChange={(e) => { setAttachQuery(e.target.value); setActive(0) }}
                  onKeyDown={pickKeys}
                />
                <CardPicker
                  options={options} active={active} onActive={setActive}
                  onPick={pickCard} onClose={closePick} isAttached={attached}
                  hint="角色/生物挂进出场主体，道具进道具引用，场景落到本镜头的场景卡"
                />
              </span>
            )}
          </span>

          <button type="button" className="btn btn--sm btn--ghost"
                  title="把这个镜头拆成几拍：同一个不切的长镜头里，情绪与灯光逐级推进"
                  onClick={() => onChange(addBeat(shot))}>
            {shot.beats?.length ? '＋ 加一拍' : '拆成分镜内阶段'}
          </button>

          <span className="ed__attachbox">
            <button type="button" className="btn btn--sm btn--ghost"
                    title="出图时拿哪几张卡垫图——直接决定形象锁不锁得住"
                    onClick={() => setPick(pick?.mode === 'refs' ? null : { mode: 'refs' })}>
              垫图 {shot.prompts?.reference_assets?.length || 0}
            </button>
            {pick?.mode === 'refs' && (
              <CardPicker
                options={options} active={active} onActive={setActive}
                onPick={pickCard} onClose={closePick}
                isAttached={(c) => !!shot.prompts?.reference_assets?.includes(c.id)}
                hint="从本镜头已挂的卡里勾选；摘掉卡时会自动从这里移除"
              />
            )}
          </span>

          <span className="ed__cons">
            <span className="ed__conslabel" title="出图质量的一半毁在没有负面约束上">不要</span>
            <input
              className="ed"
              placeholder="负面约束，用 / 分隔：画面内不出现灯具 / 无镜头光晕 / 全程不切镜"
              value={(shot.constraints ?? []).join(' / ')}
              onChange={(e) => onChange(setConstraints(splitList(e.target.value)))}
            />
          </span>

          {!!shot.prompts?.reference_assets?.length && (
            <span className="chips chips--refs">
              {shot.prompts.reference_assets.map((id) => (
                <span className="chip chip--ref" key={id}>
                  {id} {idx.assetName(id)}
                  <button type="button" className="chip__x" title="不再垫这张"
                          onClick={() => onChange(setReferenceAssets(shot,
                            shot.prompts!.reference_assets!.filter((r) => r !== id)))}>×</button>
                </span>
              ))}
            </span>
          )}
        </div>
      )}

      {!!shot.dialogue?.length && (
        <div className="lines">
          {shot.dialogue.map((d, i) => (
            <p className="line line--dia" key={i}>
              <span className="line__who">
                {d.character_ref ? idx.assetName(d.character_ref) : label(DIALOGUE_TYPE, d.type)}
              </span>
              <span className="line__text">{d.text}</span>
              {editing ? (
                <input
                  className="ed ed--slim"
                  placeholder="情绪/语气"
                  value={d.emotion ?? ''}
                  onChange={(e) => onChange({
                    dialogue: shot.dialogue!.map((x, j) =>
                      j === i ? { ...x, emotion: e.target.value || undefined } : x),
                  })}
                />
              ) : (
                d.emotion && <span className="line__emo">{d.emotion}</span>
              )}
              {d.verbatim === false && <span className="tag tag--warn">非原文</span>}
            </p>
          ))}
        </div>
      )}

      {shot.narration?.text && (
        <div className="lines">
          <p className="line line--nar">
            <span className="line__who">旁白</span>
            <span className="line__text">{shot.narration.text}</span>
            {editing && <span className="lock" title="旁白取自原文，改动会破坏保真校验">🔒</span>}
          </p>
        </div>
      )}

      {editing ? (
        <input
          className="ed"
          placeholder="音效（多条用 / 分隔）"
          value={(shot.sfx ?? []).join(' / ')}
          onChange={(e) => {
            const list = splitList(e.target.value)
            onChange({ sfx: list.length ? list : undefined })
          }}
        />
      ) : (
        !!shot.sfx?.length && <p className="shot__sfx">🔊 {shot.sfx.join(' / ')}</p>
      )}

      <footer className="shot__foot">
        <span className={`deriv deriv--${shot.source?.derivation ?? 'explicit'}`}>
          {label(DERIVATION, shot.source?.derivation)}
        </span>
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
        {editing && <span className="lock" title="溯源引用与推导标记锁死，保证产物仍可通过校验">🔒 溯源锁定</span>}
        {shot.source?.note && <span className="shot__note">{shot.source.note}</span>}
      </footer>
    </article>
  )
}
