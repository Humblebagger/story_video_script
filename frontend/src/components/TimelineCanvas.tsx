import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { MOOD, MOOD_HUE, SHOT_SIZE, label } from '../labels'
import { buildTimeline, fmtClock, litFraction, shotIndexAt } from '../timeline'
import type { CharLane, Timeline } from '../timeline'
import type { Storyboard } from '../types'

interface Props {
  doc: Storyboard
  onClose: () => void
  /** 点镜头：回分镜页定位到这一镜 */
  onJumpShot: (shotId: string) => void
  /** 点原文句：回原文溯源页定位到这一句 */
  onJumpUnit: (unitId: string) => void
}

const GUTTER = 92          // 左侧泳道名一栏
const RULER = 30
const ROW = { episode: 24, scene: 26, shot: 38, char: 44, speech: 30, music: 26 }
const SPEEDS = [0.5, 1, 2]

interface Row { key: string; label: string; y: number; h: number }

function layoutRows(tl: Timeline): { rows: Row[]; height: number } {
  const rows: Row[] = []
  let y = RULER
  const push = (key: string, lbl: string, h: number) => { rows.push({ key, label: lbl, y, h }); y += h }
  push('episode', '集', ROW.episode)
  push('scene', '场景', ROW.scene)
  push('shot', '镜头', ROW.shot)
  for (const c of tl.characters) push(`c:${c.ref}`, `${c.ref} ${c.name}`, ROW.char)
  push('speech', '旁白/台词', ROW.speech)
  push('music', 'BGM', ROW.music)
  return { rows, height: y + 12 }
}

/** 角色泳道上的连线：已过的节点之间实线点亮，播放头所在的那一段按比例点亮 */
function litPath(lane: CharLane, t: number, x: (s: number) => number): string {
  const pts: string[] = []
  for (let i = 0; i < lane.nodes.length; i++) {
    const n = lane.nodes[i]
    if (n.t > t) {
      const prev = lane.nodes[i - 1]
      if (prev) {
        const f = litFraction(prev.t, n.t, t)
        pts.push(`${x(prev.t + (n.t - prev.t) * f)}`)
      }
      break
    }
    pts.push(`${x(n.t)}`)
  }
  return pts.length > 1 ? pts.map((p, i) => `${i ? 'L' : 'M'}${p},0`).join(' ') : ''
}

/** 时间轴画布：无边框、全屏，拖动平移、滚轮缩放；横轴是可播时长。
 *  只读的播放视图——编辑仍在分镜页，画布将来的编辑走 timelineOps.ts 的操作层。 */
export function TimelineCanvas({ doc, onClose, onJumpShot, onJumpUnit }: Props) {
  const tl = useMemo(() => buildTimeline(doc), [doc])
  const { rows, height } = useMemo(() => layoutRows(tl), [tl])
  const rowOf = Object.fromEntries(rows.map((r) => [r.key, r]))
  const units = useMemo(() => Object.fromEntries(
    (doc.source?.units ?? []).map((u) => [u.id, u.text])), [doc])

  const box = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(1200)
  const [pps, setPps] = useState(24)              // 每秒多少像素（缩放）
  const [tx, setTx] = useState(0)                 // 水平平移（像素）
  const [ty, setTy] = useState(0)                 // 垂直平移
  const [t, setT] = useState(0)                   // 播放头（秒）
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(1)
  const drag = useRef<{ x: number; y: number; tx: number; ty: number; scrub: boolean } | null>(null)

  // 打开时让整章正好铺满一屏宽
  const fit = useCallback(() => {
    const w = box.current?.clientWidth ?? 1200
    setWidth(w)
    if (tl.total > 0) setPps(Math.max(2, (w - GUTTER - 40) / tl.total))
    setTx(0)
    setTy(0)
  }, [tl.total])
  useEffect(() => { fit() }, [fit])
  useEffect(() => {
    const onResize = () => setWidth(box.current?.clientWidth ?? 1200)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  // Esc 关闭；空格播放/暂停
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
      if (e.key === ' ') { e.preventDefault(); setPlaying((p) => !p) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  // 播放：按真实时间（×速度）推进播放头，到头停
  const tRef = useRef(0)
  tRef.current = t
  useEffect(() => {
    if (!playing) return
    let last = performance.now()
    let raf = 0
    const tick = (now: number) => {
      // 累计在 ref 里而不是读上一帧渲染出的 t：两帧之间不保证已经重新渲染过
      const next = Math.min(tl.total, tRef.current + (now - last) / 1000 * speed)
      last = now
      tRef.current = next
      setT(next)
      if (next >= tl.total) {
        setPlaying(false)
        return
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [playing, speed, tl.total])

  const x = (sec: number) => GUTTER + tx + sec * pps
  const playX = x(t)
  // 播放时播放头跑出视野就把画面跟过去
  useEffect(() => {
    if (playing && (playX > width * 0.85 || playX < GUTTER)) setTx(-(t * pps) + width * 0.3)
  }, [playing, playX, width, t, pps])

  const current = shotIndexAt(tl, t)
  const cur = tl.shots[current]

  const timeAt = (clientX: number) => {
    const left = box.current?.getBoundingClientRect().left ?? 0
    return Math.min(tl.total, Math.max(0, (clientX - left - GUTTER - tx) / pps))
  }

  const onWheel = (e: React.WheelEvent) => {
    if (Math.abs(e.deltaX) > Math.abs(e.deltaY)) { setTx((v) => v - e.deltaX); return }
    if (e.shiftKey) { setTy((v) => Math.min(0, v - e.deltaY)); return }
    // 以光标处的时刻为锚点缩放：光标下的那一秒不动
    const anchor = timeAt(e.clientX)
    const left = box.current?.getBoundingClientRect().left ?? 0
    const next = Math.min(400, Math.max(1, pps * Math.exp(-e.deltaY * 0.0015)))
    setPps(next)
    setTx(e.clientX - left - GUTTER - anchor * next)
  }

  const onPointerDown = (e: React.PointerEvent) => {
    const top = box.current?.getBoundingClientRect().top ?? 0
    const scrub = e.clientY - top < RULER
    drag.current = { x: e.clientX, y: e.clientY, tx, ty, scrub }
    if (scrub) setT(timeAt(e.clientX))
    ;(e.target as Element).setPointerCapture?.(e.pointerId)
  }
  const onPointerMove = (e: React.PointerEvent) => {
    const d = drag.current
    if (!d) return
    if (d.scrub) { setT(timeAt(e.clientX)); return }
    setTx(d.tx + e.clientX - d.x)
    setTy(Math.min(0, d.ty + e.clientY - d.y))
  }
  const onPointerUp = () => { drag.current = null }

  // 只画视野内的刻度
  const step = [1, 2, 5, 10, 15, 30, 60, 120, 300].find((s) => s * pps >= 70) ?? 600
  const firstTick = Math.max(0, Math.floor(-tx / pps / step) * step)
  const ticks: number[] = []
  for (let s = firstTick; s <= tl.total && x(s) < width + step * pps; s += step) ticks.push(s)

  const shotRow = rowOf.shot
  const mid = (i: number) => (tl.shots[i].start + tl.shots[i].end) / 2

  return (
    <div className="tlc" ref={box}>
      <div className="tlc__bar" onPointerDown={(e) => e.stopPropagation()}>
        <button className="btn btn--sm" onClick={() => {
          if (t >= tl.total) setT(0)
          setPlaying((p) => !p)
        }}>{playing ? '❚❚ 暂停' : '▶ 播放'}</button>
        <button className="btn btn--sm btn--ghost" title="上一镜" disabled={current <= 0}
                onClick={() => setT(tl.shots[Math.max(0, current - 1)].start)}>⏮</button>
        <button className="btn btn--sm btn--ghost" title="下一镜" disabled={current >= tl.shots.length - 1}
                onClick={() => setT(tl.shots[Math.min(tl.shots.length - 1, current + 1)].start)}>⏭</button>
        <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
          {SPEEDS.map((s) => <option key={s} value={s}>{s}×</option>)}
        </select>
        <span className="tlc__clock">{fmtClock(t)} / {fmtClock(tl.total)}</span>
        <button className="btn btn--sm btn--ghost" onClick={() => setPps((v) => Math.min(400, v * 1.5))}>＋</button>
        <button className="btn btn--sm btn--ghost" onClick={() => setPps((v) => Math.max(1, v / 1.5))}>－</button>
        <button className="btn btn--sm btn--ghost" onClick={fit}>适应</button>
        <span className="tlc__hint">⏮⏭ 逐镜 · 拖动平移 · 滚轮缩放 · Shift+滚轮上下 · 点时间刻度跳转 · 空格播放 · Esc 关闭</span>
        <button className="btn btn--sm btn--ghost tlc__close" onClick={onClose}>✕ 关闭画布</button>
      </div>

      <svg className="tlc__svg" width={width} height="100%"
           onWheel={onWheel} onPointerDown={onPointerDown}
           onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerLeave={onPointerUp}>
        <g transform={`translate(0, ${ty})`}>
          {/* 泳道底纹 */}
          {rows.map((r, i) => (
            <rect key={r.key} x={0} y={r.y} width={width} height={r.h}
                  className={i % 2 ? 'tlc__lane tlc__lane--alt' : 'tlc__lane'} />
          ))}

          {/* 集 / 场景 */}
          {tl.episodes.map((e) => (
            <g key={e.key} className="tlc__seg tlc__seg--ep">
              <rect x={x(e.start)} y={rowOf.episode.y + 3} width={Math.max(1, (e.end - e.start) * pps - 2)}
                    height={ROW.episode - 6} rx={4} />
              <text x={x(e.start) + 6} y={rowOf.episode.y + 16}>{e.label}</text>
            </g>
          ))}
          {tl.scenes.map((s, i) => (
            <g key={`${s.key}-${i}`} className="tlc__seg tlc__seg--scene">
              <rect x={x(s.start)} y={rowOf.scene.y + 3} width={Math.max(1, (s.end - s.start) * pps - 2)}
                    height={ROW.scene - 6} rx={4} />
              {(s.end - s.start) * pps > 40 && <text x={x(s.start) + 6} y={rowOf.scene.y + 17}>{s.label}</text>}
            </g>
          ))}

          {/* 镜头：块 + 镜头顺序连线（随播放头点亮） */}
          <line className="tlc__link" x1={x(mid(0))} x2={x(mid(tl.shots.length - 1))}
                y1={shotRow.y + ROW.shot / 2} y2={shotRow.y + ROW.shot / 2} />
          {!!tl.shots.length && t > mid(0) && (
            <line className="tlc__link tlc__link--lit" x1={x(mid(0))}
                  x2={x(Math.min(t, mid(tl.shots.length - 1)))}
                  y1={shotRow.y + ROW.shot / 2} y2={shotRow.y + ROW.shot / 2} />
          )}
          {tl.shots.map((s, i) => (
            <g key={s.id} className={`tlc__shot tlc__shot--${s.shot.source?.derivation ?? 'explicit'}${
                 i === current ? ' is-cur' : ''}${s.end <= t ? ' is-past' : ''}`}
               onClick={() => onJumpShot(s.id)}>
              <rect x={x(s.start) + 1} y={shotRow.y + 6} width={Math.max(2, s.playable * pps - 2)}
                    height={ROW.shot - 12} rx={3} />
              {s.playable > s.nominal + 0.05 && (
                <rect className="tlc__over" x={x(s.start + s.nominal)} y={shotRow.y + ROW.shot - 9}
                      width={(s.playable - s.nominal) * pps} height={3} />
              )}
              {s.playable * pps > 46 && (
                <text x={x(s.start) + 5} y={shotRow.y + ROW.shot / 2 + 4}>{s.id.replace(/^E\d+-/, '')}</text>
              )}
              <title>{`${s.id} · ${label(SHOT_SIZE, s.shot.shot_size)} · ${s.playable.toFixed(1)}s${
                s.playable > s.nominal + 0.05 ? `（标称 ${s.nominal}s，念完旁白台词需更久）` : ''}\n${s.shot.action}`}</title>
            </g>
          ))}

          {/* 角色泳道：出场节点 + 动作顺序连线 */}
          {tl.characters.map((c) => {
            const r = rowOf[`c:${c.ref}`]
            const cy = r.y + 16
            const lit = litPath(c, t, x)
            return (
              <g key={c.ref} className="tlc__char">
                {c.nodes.length > 1 && (
                  <line className="tlc__link" x1={x(c.nodes[0].t)} x2={x(c.nodes[c.nodes.length - 1].t)}
                        y1={cy} y2={cy} />
                )}
                {lit && <path className="tlc__link tlc__link--lit" d={lit}
                              transform={`translate(0, ${cy})`} />}
                {c.nodes.map((n) => {
                  const on = n.shotId === cur?.id
                  return (
                    <g key={n.shotId} className={`tlc__node${n.t <= t ? ' is-past' : ''}${on ? ' is-cur' : ''}`}
                       onClick={() => onJumpShot(n.shotId)}>
                      <circle cx={x(n.t)} cy={cy} r={on ? 6 : 4} />
                      {(pps * (n.end - n.start) > 60 || on) && (
                        <text x={x(n.t)} y={cy + 17} textAnchor="middle">
                          {n.action.length > 10 ? `${n.action.slice(0, 10)}…` : n.action}
                        </text>
                      )}
                      <title>{`${c.name} · ${n.shotId}\n动作：${n.action}${n.fromShotAction ? '（镜头描述）' : ''}${
                        n.expression ? `\n表情：${n.expression}` : ''}${n.position ? `\n位置：${n.position}` : ''}${
                        n.outfit ? `\n服装：${n.outfit}` : ''}`}</title>
                    </g>
                  )
                })}
              </g>
            )
          })}

          {/* 旁白 / 台词段 */}
          {tl.speech.map((s, i) => (
            <rect key={i} className={`tlc__speech tlc__speech--${s.kind}${s.start <= t ? ' is-past' : ''}`}
                  x={x(s.start)} y={rowOf.speech.y + (s.kind === 'narration' ? 6 : 15)}
                  width={Math.max(1, (s.end - s.start) * pps - 1)} height={9} rx={2}>
              <title>{`${s.kind === 'narration' ? '旁白' : `台词 · ${s.who ?? ''}`}：${s.text}`}</title>
            </rect>
          ))}

          {/* BGM 情绪段 */}
          {tl.music.map((m) => (
            <g key={m.key} className="tlc__music">
              <rect x={x(m.start)} y={rowOf.music.y + 4} width={Math.max(1, (m.end - m.start) * pps - 2)}
                    height={ROW.music - 8} rx={8}
                    style={{ fill: m.mood ? `hsl(${MOOD_HUE[m.mood]} 55% 55% / ${
                      m.intensity === 'high' ? 0.75 : m.intensity === 'low' ? 0.3 : 0.5})` : undefined }} />
              {(m.end - m.start) * pps > 40 && m.mood && (
                <text x={x(m.start) + 8} y={rowOf.music.y + 17}>{label(MOOD, m.mood)}</text>
              )}
              <title>{`${m.mood ? label(MOOD, m.mood) : ''} ${m.intensity ?? ''}${m.label ? `\n${m.label}` : ''}`}</title>
            </g>
          ))}
        </g>

        {/* 时间刻度（不随上下平移） */}
        <g className="tlc__ruler">
          <rect x={0} y={0} width={width} height={RULER} />
          {ticks.map((s) => (
            <g key={s}>
              <line x1={x(s)} x2={x(s)} y1={RULER - 8} y2={RULER} />
              <text x={x(s) + 3} y={RULER - 11}>{fmtClock(s)}</text>
            </g>
          ))}
        </g>

        {/* 泳道名（不随左右平移） */}
        <g className="tlc__labels" transform={`translate(0, ${ty})`}>
          <rect x={0} y={RULER} width={GUTTER} height={height} />
          {rows.map((r) => (
            <text key={r.key} x={8} y={r.y + Math.min(r.h / 2 + 4, 20)}>
              {r.label.length > 9 ? `${r.label.slice(0, 9)}…` : r.label}
            </text>
          ))}
        </g>

        {/* 播放头 */}
        <line className="tlc__head" x1={playX} x2={playX} y1={0} y2="100%" />
        <polygon className="tlc__head" points={`${playX - 6},0 ${playX + 6},0 ${playX},8`} />
      </svg>

      {cur && (
        <aside className="tlc__panel" onPointerDown={(e) => e.stopPropagation()}>
          <header>
            <b>{cur.id}</b>
            <span>{label(SHOT_SIZE, cur.shot.shot_size)} · {fmtClock(cur.start)}–{fmtClock(cur.end)}
              {cur.playable > cur.nominal + 0.05 && `（标称 ${cur.nominal}s）`}</span>
          </header>
          <p className="tlc__action">{cur.shot.action}</p>
          {cur.shot.atmosphere && <p className="tlc__atmo">{cur.shot.atmosphere}</p>}
          {!!cur.shot.characters?.length && (
            <ul className="tlc__chars">
              {cur.shot.characters.map((c) => (
                <li key={c.ref}><b>{tl.characters.find((l) => l.ref === c.ref)?.name ?? c.ref}</b>
                  {c.action && ` ${c.action}`}{c.expression && `（${c.expression}）`}</li>
              ))}
            </ul>
          )}
          {cur.shot.dialogue?.map((d, i) => (
            <p key={i} className="tlc__line">
              「{d.text}」<em>{tl.characters.find((l) => l.ref === d.character_ref)?.name ?? d.character_ref}</em>
            </p>
          ))}
          {cur.shot.narration?.text && <p className="tlc__narr">旁白：{cur.shot.narration.text}</p>}
          <div className="tlc__units">
            {(cur.shot.source?.unit_refs ?? []).map((u) => (
              <button key={u} className="tlc__unit" onClick={() => onJumpUnit(u)} title="到原文溯源页定位这一句">
                <code>{u}</code> {units[u] ?? ''}
              </button>
            ))}
          </div>
          <button className="btn btn--sm btn--ghost" onClick={() => onJumpShot(cur.id)}>在分镜页打开这一镜</button>
        </aside>
      )}
    </div>
  )
}
