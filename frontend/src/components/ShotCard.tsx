import { splitList } from '../edit'
import {
  CAMERA_ANGLE, CAMERA_MOVEMENT, DERIVATION, DIALOGUE_TYPE, label,
  LOCATION_ANGLE, SHOT_SIZE, TIME_OF_DAY, TRANSITION,
} from '../labels'
import type { Index } from '../resolve'
import type {
  CameraAngle, CameraMovement, LocationAngle, Shot, ShotSize, TimeOfDay, Transition,
} from '../types'

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

export function ShotCard({ shot, idx, editing, onPickUnit, onChange }: Props) {
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
          <textarea
            className="ed ed--area"
            value={shot.action}
            rows={3}
            onChange={(e) => onChange({ action: e.target.value })}
          />
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
            </div>
          ) : (
            <span className="chip chip--char" key={`${c.ref}-${i}`}>
              <b>{idx.assetName(c.ref)}</b>
              {c.expression && <em>{c.expression}</em>}
              {c.action && <span className="chip__note">{c.action}</span>}
            </span>
          )))}
        </div>
      )}

      {!editing && (!!shot.prop_refs?.length || !!shot.creature_refs?.length) && (
        <div className="chips">
          {shot.prop_refs?.map((p, i) => (
            <span className="chip chip--prop" key={`${p.ref}-${i}`}>
              {idx.assetName(p.ref)}
              {p.state && <em>{p.state}</em>}
            </span>
          ))}
          {shot.creature_refs?.map((c, i) => (
            <span className="chip chip--prop" key={`${c.ref}-${i}`}>{idx.assetName(c.ref)}</span>
          ))}
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
