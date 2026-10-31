import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { MOOD, MOOD_HUE, SHOT_SIZE, label } from '../labels'
import { stampVersion, updateAsset, updateShot } from '../edit'
import type { AssetKind } from '../edit'
import { buildIndex } from '../resolve'
import { chosenAttempt, clipOffset, clipSpans, laneKind, laneText, laneTitle, spanAt } from '../film'
import { useFilm } from '../useFilm'
import { FilmPanel } from './FilmPanel'
import { buildTimeline, fitText, fmtClock, previewFrom, shotSpan, speechAt, textPx, litFraction, shotIndexAt } from '../timeline'
import { applyOp } from '../timelineOps'
import type { TimelineOp } from '../timelineOps'
import { AssetsView } from './AssetsView'
import { NovelPanel, TaskPanel } from './CanvasPanels'
import type { Workbench } from './CanvasPanels'
import { ShotCard } from './ShotCard'
import { SourceView } from './SourceView'
import type { CharLane, Timeline } from '../timeline'
import type { Storyboard, VersionRef } from '../types'
import { promptSheet, useKeyframes } from '../useKeyframes'

interface Props {
  doc: Storyboard
  onClose: () => void
  /** 打开时停在哪个侧栏页 */
  initialPanel?: PanelTab
  /** 点镜头：回分镜页定位到这一镜 */
  onJumpShot: (shotId: string) => void
  /** 所在的章节会话：给了侧栏才有「剧情」「任务」两页 */
  bench?: Workbench | null
  /** 产物所属的版本：有它才能上传关键帧图（本地 JSON / 分批预览只有提示词） */
  version?: VersionRef | null
  /** 给了就能在画布上直接编辑（分批预览不给）；改动与分镜页是同一份产物 */
  onChange?: (doc: Storyboard) => void
  canSave?: boolean
  dirty?: boolean
  saving?: boolean
  onSave?: () => void
}

/** 连续打字时把一串改动并成一步撤销 */
const UNDO_MERGE_MS = 800

const GUTTER = 132         // 左侧泳道名一栏：角色两行（名字 / ID），不再挤成一行截断
const RULER = 30
const ROW = { episode: 24, scene: 26, shot: 38, clip: 34, frame: 72, char: 44, speech: 30, music: 26 }
const SPEEDS = [0.5, 1, 2]

export type PanelTab = 'shot' | 'source' | 'assets' | 'film' | 'novel' | 'tasks'

interface Row { key: string; label: string; sub?: string; y: number; h: number }

function layoutRows(tl: Timeline, withFrames: boolean, withClips: boolean): { rows: Row[]; height: number } {
  const rows: Row[] = []
  let y = RULER
  const push = (key: string, lbl: string, h: number, sub?: string) => {
    rows.push({ key, label: lbl, sub, y, h })
    y += h
  }
  push('episode', '集', ROW.episode)
  push('scene', '场景', ROW.scene)
  push('shot', '镜头', ROW.shot)
  // 有出片会话才出这条泳道：每段一条横条，横跨所含镜头
  if (withClips) push('clip', '成片', ROW.clip)
  // 有关键帧图才出这条泳道：图直接铺在画布上，不必盯着侧栏
  if (withFrames) push('frame', '画面', ROW.frame)
  for (const c of tl.characters) push(`c:${c.ref}`, c.name, ROW.char, c.ref)
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
 *  可就地编辑：拖右缘改时长、双击角色节点改动作（timelineOps.ts），右侧是本镜的编辑表单；自带撤销重做。 */
function downloadText(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/markdown;charset=utf-8' }))
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  URL.revokeObjectURL(url)
}

export function TimelineCanvas({
  doc, onClose, onJumpShot, bench = null, version = null,
  onChange, canSave = false, dirty = false, saving = false, onSave, initialPanel,
}: Props) {
  const kf = useKeyframes(doc, version)
  const idx = useMemo(() => buildIndex(doc), [doc])
  const editable = !!onChange
  const [editing, setEditing] = useState(false)
  /** 侧栏页签：外面能做的事在画布里都有一页，不必退出去 */
  const [panel, setPanel] = useState<PanelTab>(initialPanel ?? 'shot')
  const [focusUnit, setFocusUnit] = useState<string | null>(null)
  /** 实际显示的页签：没有可出片的版本时「出片」页签不存在，停在「本镜」而不是空白（与 film.enabled 同一判断） */
  const shown: PanelTab = panel === 'film' && !(version?.nid && version.cid && version.vid) ? 'shot' : panel
  /** 出片会话（只有存进后端的版本才有）；「出片」页签开着时轮询更勤 */
  const film = useFilm(version, { active: shown === 'film' })
  /** 「成片」泳道上选中的段 */
  const [clipSel, setClipSel] = useState<string | null>(null)
  /** 预览窗播已出的成片（采用的那一次）还是关键帧 */
  const [filmMode, setFilmMode] = useState(false)
  /** 「生成中 · 已等 m:ss」每秒走一次 */
  const [now, setNow] = useState(() => Date.now())
  const videoRef = useRef<HTMLVideoElement>(null)
  // 保存完（未保存 → 已保存）重读出片会话：分镜变了，段与金额要跟着服务端的最新值走
  const wasDirty = useRef(dirty)
  const reloadFilm = film.load
  useEffect(() => {
    if (wasDirty.current && !dirty) void reloadFilm()
    wasDirty.current = dirty
  }, [dirty, reloadFilm])
  const onJumpUnit = (unitId: string) => {
    setFocusUnit(unitId)
    setPanel('source')
  }

  /* ---- 编辑：每次改动都落成新文档交给上层（与分镜页同一份），画布自带撤销 / 重做 ---- */
  const docRef = useRef(doc)
  docRef.current = doc
  // 撤销栈放 ref 里（改动要同步生效），history 计数只用来触发按钮重渲染
  const past = useRef<Storyboard[]>([])
  const future = useRef<Storyboard[]>([])
  const [, setHistory] = useState(0)
  const lastRecord = useRef(0)
  const checkpoint = useCallback(() => {
    past.current = [...past.current.slice(-49), docRef.current]
    future.current = []
    setHistory((n) => n + 1)
  }, [])
  /** record=false：拖动途中的连续改动，撤销点在按下那一刻已经记过 */
  const commit = useCallback((next: Storyboard, record = true) => {
    if (!onChange || next === docRef.current) return
    const now = Date.now()
    if (record && now - lastRecord.current > UNDO_MERGE_MS) checkpoint()
    if (record) lastRecord.current = now
    docRef.current = next
    onChange(stampVersion(next))
  }, [onChange, checkpoint])
  const op = (o: TimelineOp, record = true) => commit(applyOp(docRef.current, o), record)
  const undo = useCallback(() => {
    const prev = past.current[past.current.length - 1]
    if (!prev || !onChange) return
    past.current = past.current.slice(0, -1)
    future.current = [docRef.current, ...future.current]
    lastRecord.current = 0
    docRef.current = prev
    onChange(prev)
    setHistory((n) => n + 1)
  }, [onChange])
  const redo = useCallback(() => {
    const next = future.current[0]
    if (!next || !onChange) return
    future.current = future.current.slice(1)
    past.current = [...past.current, docRef.current]
    lastRecord.current = 0
    docRef.current = next
    onChange(next)
    setHistory((n) => n + 1)
  }, [onChange])
  const [resizing, setResizing] = useState<{ shotId: string; sec: number } | null>(null)
  const [nodeEdit, setNodeEdit] = useState<{
    shotId: string; ref: string; value: string; left: number; top: number } | null>(null)
  const finishNodeEdit = (save: boolean) => {
    if (nodeEdit && save) op({ kind: 'setCharacterAction', shotId: nodeEdit.shotId,
                               ref: nodeEdit.ref, action: nodeEdit.value })
    setNodeEdit(null)
  }
  const [animatic, setAnimatic] = useState(true)
  const fileRef = useRef<HTMLInputElement>(null)
  const tl = useMemo(() => buildTimeline(doc), [doc])
  const withFrames = Object.keys(kf.urls).length > 0
  const spans = useMemo(() => (film.session ? clipSpans(tl, film.session) : []), [tl, film.session])
  const withClips = spans.length > 0
  const { rows, height } = useMemo(() => layoutRows(tl, withFrames, withClips), [tl, withFrames, withClips])
  const { ensure } = film
  // 成片泳道的缩略图：各段采用那次的尾帧
  useEffect(() => {
    for (const sp of spans) ensure(chosenAttempt(sp.clip)?.last_frame)
  }, [spans, ensure])
  useEffect(() => {
    if (!spans.some((sp) => laneKind(sp.clip) === 'busy')) return
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [spans])
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
  const drag = useRef<{ x: number; y: number; tx: number; ty: number; scrub: boolean
                        moved?: boolean; resize?: { shotId: string; start: number }
                        /** 在时间刻度上拖：圈出一段时间，空格预览这一段 */
                        select?: number } | null>(null)
  /** 选区（秒）：空格只播这一段；没有选区时空格播当前这一镜 */
  const [range, setRange] = useState<{ start: number; end: number } | null>(null)
  /** 本次播放播到哪儿停（null = 播到片尾） */
  const stopAt = useRef<number | null>(null)
  /** 拖动平移之后松手会补发一次 click，不能当成选中镜头 */
  const suppressClick = useRef(false)

  // 打开时让整章正好铺满一屏宽
  /** 用户自己缩放 / 平移过之后，画布区宽度变化就不再自动铺满，免得把人调好的视图冲掉 */
  const userView = useRef(false)
  const fit = useCallback(() => {
    userView.current = false
    const w = box.current?.clientWidth ?? 1200
    setWidth(w)
    if (tl.total > 0) setPps(Math.max(0.3, (w - GUTTER - 32) / tl.total))
    setTx(0)
    setTy(0)
  }, [tl.total])
  useEffect(() => { fit() }, [fit])
  // 进出编辑态时右侧栏变宽变窄：没手动调过视图就重新铺满
  useEffect(() => {
    if (!userView.current && tl.total > 0) setPps(Math.max(0.3, (width - GUTTER - 32) / tl.total))
  }, [width, tl.total])
  // 画布区宽度会随右侧栏变（编辑态更宽），只盯窗口 resize 不够
  useEffect(() => {
    const el = box.current
    const onResize = () => setWidth(el?.clientWidth ?? 1200)
    if (el && typeof ResizeObserver !== 'undefined') {
      const ro = new ResizeObserver(onResize)
      ro.observe(el)
      return () => ro.disconnect()
    }
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  // Esc 关闭；空格播放/暂停
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // 正在输入框里打字：空格、Esc、⌘Z 都归输入框自己
      const el = e.target as HTMLElement | null
      if (el && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)) return
      if (e.key === 'Escape') { if (rangeRef.current) setRange(null); else onClose() }
      if (e.key === ' ') { e.preventDefault(); previewRef.current() }
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'z') {
        e.preventDefault()
        if (e.shiftKey) redo(); else undo()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose, undo, redo])
  const rangeRef = useRef(range)
  rangeRef.current = range

  // 播放：按真实时间（×速度）推进播放头，到头停
  const tRef = useRef(0)
  tRef.current = t
  useEffect(() => {
    if (!playing) return
    let last = performance.now()
    let raf = 0
    const tick = (now: number) => {
      // 累计在 ref 里而不是读上一帧渲染出的 t：两帧之间不保证已经重新渲染过
      const end = Math.min(tl.total, stopAt.current ?? tl.total)
      // rAF 的时间戳是这一帧的起点，可能早于开播那一刻：不夹住的话首帧会倒退，从镜首开播会退回上一镜
      const next = Math.min(end, tRef.current + Math.max(0, now - last) / 1000 * speed)
      last = now
      tRef.current = next
      setT(next)
      if (next >= end) {
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
  const curPrompt = cur ? kf.promptOf(cur.id) : undefined
  /** 播成片：播放头所在段采用的视频（没有就退回关键帧，标「未出片」） */
  const curSpan = filmMode ? spanAt(spans, t) : undefined
  const curVideo = curSpan ? (chosenAttempt(curSpan.clip)?.file ?? undefined) : undefined
  useEffect(() => { ensure(curVideo) }, [curVideo, ensure])
  // 视频跟着播放头走：偏差超过 0.3 秒才拖，免得每帧都打断解码
  useEffect(() => {
    const v = videoRef.current
    if (!v || !curSpan) return
    const want = clipOffset(curSpan, t)
    if (Math.abs(v.currentTime - want) > 0.3) v.currentTime = want
    v.playbackRate = speed
    if (playing) {
      if (v.paused) void v.play()?.catch(() => {})
    } else if (!v.paused) {
      v.pause()
    }
  })

  /** 空格：播选区（没有选区就播当前这一镜），播到段尾停；正在播就暂停 */
  const preview = () => {
    if (playing) { setPlaying(false); return }
    const seg = range ?? (cur ? { start: cur.start, end: cur.end } : null)
    if (!seg) return
    const from = previewFrom(seg, tRef.current)
    // 停在段尾前一毫秒：停在正好段尾，播放头就算进了下一镜，再按空格会播成下一镜
    stopAt.current = seg.end - 0.001
    tRef.current = from
    setT(from)
    setPlaying(true)
  }
  const previewRef = useRef(preview)
  previewRef.current = preview
  /** 整章播放（播放按钮）：不设终点 */
  const playAll = () => {
    if (playing) { setPlaying(false); return }
    stopAt.current = null
    if (tRef.current >= tl.total) { tRef.current = 0; setT(0) }
    setPlaying(true)
  }

  const timeAt = (clientX: number) => {
    const left = box.current?.getBoundingClientRect().left ?? 0
    return Math.min(tl.total, Math.max(0, (clientX - left - GUTTER - tx) / pps))
  }

  const onWheel = (e: React.WheelEvent) => {
    userView.current = true
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
    suppressClick.current = false
    const top = box.current?.getBoundingClientRect().top ?? 0
    const onRuler = e.clientY - top < RULER
    const left = box.current?.getBoundingClientRect().left ?? 0
    // 刻度上按在播放头附近 = 拖播放头；别处按下拖动 = 圈选区，只点一下 = 跳过去
    const scrub = onRuler && Math.abs(e.clientX - left - playX) <= 8
    drag.current = { x: e.clientX, y: e.clientY, tx, ty, scrub,
                     ...(onRuler && !scrub ? { select: timeAt(e.clientX) } : {}) }
    if (onRuler) { setPlaying(false); seek(timeAt(e.clientX)) }
    ;(e.target as Element).setPointerCapture?.(e.pointerId)
  }
  const onPointerMove = (e: React.PointerEvent) => {
    const d = drag.current
    if (!d) return
    if (Math.abs(e.clientX - d.x) + Math.abs(e.clientY - d.y) > 4) d.moved = true
    if (d.resize) {
      // 拖镜头右缘改标称时长（取 0.5s、夹到 schema 范围由操作层负责）
      const sec = Math.max(0.5, Math.min(15, Math.round((timeAt(e.clientX) - d.resize.start) * 2) / 2))
      setResizing({ shotId: d.resize.shotId, sec })
      op({ kind: 'setDuration', shotId: d.resize.shotId, sec }, false)
      return
    }
    if (d.scrub) { seek(timeAt(e.clientX)); return }
    if (d.select !== undefined) {
      if (d.moved) {
        const now = timeAt(e.clientX)
        setRange({ start: Math.min(d.select, now), end: Math.max(d.select, now) })
        seek(Math.min(d.select, now))
      }
      return
    }
    userView.current = true
    setTx(d.tx + e.clientX - d.x)
    setTy(Math.min(0, d.ty + e.clientY - d.y))
  }
  const onPointerUp = () => {
    // 刻度上只点不拖：清掉选区
    if (drag.current?.select !== undefined && !drag.current.moved) setRange(null)
    // 只有平移才吞掉随后的 click；拖把手的 click 在把手上就拦住了
    if (drag.current?.moved && !drag.current.resize) suppressClick.current = true
    drag.current = null
    setResizing(null)
  }
  const startResize = (e: React.PointerEvent, shotId: string, start: number) => {
    e.stopPropagation()
    checkpoint()                      // 整次拖动算一步撤销
    drag.current = { x: e.clientX, y: e.clientY, tx, ty, scrub: false, resize: { shotId, start } }
    ;(e.target as Element).setPointerCapture?.(e.pointerId)
  }
  const seek = (sec: number) => {
    tRef.current = sec
    setT(sec)
  }
  /** 点镜头 / 角色节点：就地选中（播放头跳到这一镜），不离开画布。
   *  按住 Shift 点：从当前镜到这一镜圈成选区，空格预览这一段 */
  const selectShot = (shotId: string, extend = false) => {
    if (suppressClick.current) { suppressClick.current = false; return }
    const s = tl.shots.find((x) => x.id === shotId)
    if (!s) return
    setPlaying(false)
    if (extend && cur) {
      const span = shotSpan(tl, range ? (shotIndexAtStart(range.start) ?? cur.id) : cur.id, shotId)
      if (span) { setRange(span); seek(span.start) }
      return
    }
    setRange(null)
    seek(s.start)
    setPanel('shot')
  }
  const shotIndexAtStart = (sec: number) => tl.shots[shotIndexAt(tl, sec)]?.id
  /** 点成片横条：选中该段、播放头跳到段首、侧栏切到「出片」 */
  const selectClip = (clipId: string) => {
    if (suppressClick.current) { suppressClick.current = false; return }
    const sp = spans.find((x) => x.clip.id === clipId)
    setClipSel(clipId)
    setPanel('film')
    if (sp) {
      setPlaying(false)
      setRange(null)
      seek(sp.start)
    }
  }

  // 只画视野内的刻度
  const step = [1, 2, 5, 10, 15, 30, 60, 120, 300].find((s) => s * pps >= 70) ?? 600
  const firstTick = Math.max(0, Math.floor(-tx / pps / step) * step)
  const ticks: number[] = []
  for (let s = firstTick; s <= tl.total && x(s) < width + step * pps; s += step) ticks.push(s)

  const shotRow = rowOf.shot
  const mid = (i: number) => (tl.shots[i].start + tl.shots[i].end) / 2

  return (
    <div className="tlc">
      <div className="tlc__main" ref={box}>
      <div className="tlc__bar" onPointerDown={(e) => e.stopPropagation()}>
        {editable && (
          <span className="tlc__editbar">
            <button className={`btn btn--sm${editing ? '' : ' btn--ghost'}`} onClick={() => setEditing((v) => !v)}>
              {editing ? '完成编辑' : '编辑'}
            </button>
            {(editing || past.current.length > 0 || future.current.length > 0) && (
              <>
                <button className="btn btn--sm btn--ghost" disabled={!past.current.length} title="撤销（⌘Z）"
                        onClick={undo}>↶ 撤销</button>
                <button className="btn btn--sm btn--ghost" disabled={!future.current.length} title="重做（⌘⇧Z）"
                        onClick={redo}>↷ 重做</button>
              </>
            )}
            {canSave && onSave && (
              <button className="btn btn--sm" disabled={!dirty || saving} onClick={onSave}>
                {saving ? '保存中…' : dirty ? '保存修改' : '已保存'}
              </button>
            )}
          </span>
        )}
        <button className="btn btn--sm" title="从播放头播到片尾（空格只播选区或当前这一镜）"
                onClick={playAll}>{playing ? '❚❚ 暂停' : '▶ 播放'}</button>
        <button className="btn btn--sm btn--ghost" title="上一镜" disabled={current <= 0}
                onClick={() => seek(tl.shots[Math.max(0, current - 1)].start)}>⏮</button>
        <button className="btn btn--sm btn--ghost" title="下一镜" disabled={current >= tl.shots.length - 1}
                onClick={() => seek(tl.shots[Math.min(tl.shots.length - 1, current + 1)].start)}>⏭</button>
        <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
          {SPEEDS.map((s) => <option key={s} value={s}>{s}×</option>)}
        </select>
        <span className="tlc__clock">{fmtClock(t)} / {fmtClock(tl.total)}</span>
        <button className="btn btn--sm btn--ghost" title="整章铺满一屏" onClick={fit}>适应</button>
        <button className={`btn btn--sm${animatic ? '' : ' btn--ghost'}`}
                title="静帧预演：按播放头显示当前镜头的关键帧图" onClick={() => setAnimatic((v) => !v)}>
          预演
        </button>
        {animatic && spans.some((sp) => chosenAttempt(sp.clip)) && (
          <button className={`btn btn--sm${filmMode ? '' : ' btn--ghost'}`}
                  title="预览窗播已出的成片（采用的那一次）；未出片的段显示关键帧"
                  onClick={() => setFilmMode((v) => !v)}>
            {filmMode ? '播成片' : '播关键帧'}
          </button>
        )}
        <span className="tlc__kfcount" title="已上传关键帧图的镜头数">
          关键帧 {Object.keys(kf.urls).length}/{tl.shots.length}
        </span>
        {range && (
          <span className="tlc__range">
            选区 {fmtClock(range.start)}–{fmtClock(range.end)}（{(range.end - range.start).toFixed(1)}s）
            <button className="tlc__linkbtn" title="清除选区（Esc）" onClick={() => setRange(null)}>✕</button>
          </span>
        )}
        <span className="tlc__help" title={`空格 预览：播选区，没选区就播当前这一镜，播到段尾停 · ▶ 播放 从播放头播到片尾
在时间刻度上拖 = 圈选区 · 拖播放头 = 拖着看 · Shift+点镜头 = 从当前镜圈到这一镜
${editable ? '拖镜头右缘改时长（取 0.5s）· ⌘Z 撤销\n' : ''}⏮⏭ 逐镜 · 拖动平移 · 滚轮缩放 · Shift+滚轮上下 · Esc 清选区 / 关闭${
          editing ? '\n编辑：双击角色节点改动作 · 右侧改本镜全部呈现字段' : ''}`}>?</span>
        <button className="btn btn--sm btn--ghost tlc__close" title="关闭画布（Esc）" onClick={onClose}>✕</button>
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

          {range && (
            <rect className="tlc__rangeband" x={x(range.start)} y={RULER}
                  width={Math.max(1, (range.end - range.start) * pps)} height={height - RULER} />
          )}

          {/* 集 / 场景 */}
          {tl.episodes.map((e) => (
            <g key={e.key} className="tlc__seg tlc__seg--ep">
              <rect x={x(e.start)} y={rowOf.episode.y + 3} width={Math.max(1, (e.end - e.start) * pps - 2)}
                    height={ROW.episode - 6} rx={4} />
              <text x={x(e.start) + 6} y={rowOf.episode.y + 16}>{fitText(e.label, (e.end - e.start) * pps - 12, 11, 3)}</text>
            </g>
          ))}
          {tl.scenes.map((s, i) => (
            <g key={`${s.key}-${i}`} className="tlc__seg tlc__seg--scene">
              <rect x={x(s.start)} y={rowOf.scene.y + 3} width={Math.max(1, (s.end - s.start) * pps - 2)}
                    height={ROW.scene - 6} rx={4} />
              <text x={x(s.start) + 6} y={rowOf.scene.y + 17}>{fitText(s.label, (s.end - s.start) * pps - 12, 11, 4)}</text>
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
               onClick={(e) => selectShot(s.id, e.shiftKey)} onDoubleClick={() => onJumpShot(s.id)}>
              <rect x={x(s.start) + 1} y={shotRow.y + 6} width={Math.max(2, s.playable * pps - 2)}
                    height={ROW.shot - 12} rx={3} />
              {s.playable > s.nominal + 0.05 && (
                <rect className="tlc__over" x={x(s.start + s.nominal)} y={shotRow.y + ROW.shot - 9}
                      width={(s.playable - s.nominal) * pps} height={3} />
              )}
              {kf.urls[s.id] && (
                <circle className="tlc__kfdot" cx={x(s.start) + 6} cy={shotRow.y + 8} r={2.5} />
              )}
              <text x={x(s.start) + 5} y={shotRow.y + ROW.shot / 2 + 4}>
                {fitText(s.id.replace(/^E\d+-/, ''), s.playable * pps - 9, 10, Infinity)}
              </text>
              <title>{`${s.id} · ${label(SHOT_SIZE, s.shot.shot_size)} · ${s.playable.toFixed(1)}s${
                s.playable > s.nominal + 0.05 ? `（标称 ${s.nominal}s，念完旁白台词需更久）` : ''}\n${s.shot.action}`}</title>
              {editable && (
                <rect className="tlc__grip" data-shot={s.id} x={x(s.start + s.nominal) - 4} y={shotRow.y + 4}
                      width={8} height={ROW.shot - 8}
                      onPointerDown={(e) => startResize(e, s.id, s.start)}
                      onClick={(e) => e.stopPropagation()}>
                  <title>{`拖动改时长（标称 ${s.nominal}s）`}</title>
                </rect>
              )}
              {resizing?.shotId === s.id && (
                <text className="tlc__resizing" x={x(s.start + s.nominal) + 6} y={shotRow.y - 2}>
                  {resizing.sec}s
                </text>
              )}
            </g>
          ))}

          {/* 成片：每段一条横条，横跨所含镜头；点一下选中该段、切到「出片」页 */}
          {rowOf.clip && spans.map((sp) => {
            const c = sp.clip
            const kind = laneKind(c)
            const w = Math.max(2, (sp.end - sp.start) * pps - 2)
            const thumb = kind === 'done' || kind === 'stale'
              ? film.files[chosenAttempt(c)?.last_frame ?? ''] : undefined
            const marks = `${c.dropped_refs.length ? '⚠' : ''}${c.truncated ? '✂' : ''}`
            return (
              <g key={`clip-${c.id}`} data-clip={c.id}
                 className={`tlc__clip tlc__clip--${kind}${c.id === clipSel ? ' is-sel' : ''}`}
                 onClick={() => selectClip(c.id)}>
                <rect x={x(sp.start) + 1} y={rowOf.clip.y + 4} width={w} height={ROW.clip - 8} rx={3} />
                {thumb && (
                  <image href={thumb} x={x(sp.start) + 2} y={rowOf.clip.y + 5}
                         width={Math.max(1, Math.min(w - 2, 40))}
                         height={ROW.clip - 10} preserveAspectRatio="xMidYMid slice" />
                )}
                <text x={x(sp.start) + (thumb ? 46 : 6)} y={rowOf.clip.y + ROW.clip / 2 + 4}>
                  {fitText(`${marks}${laneText(c, now)}`, w - (thumb ? 50 : 10), 10, 3)}
                </text>
                {/* 横条窄到写不下字时，悬停照样看得到状态 */}
                <title>{`${laneText(c, now)}\n${laneTitle(c)}`}</title>
              </g>
            )
          })}

          {/* 画面：已上传的关键帧按镜头宽度整张放进去（不裁切），点一下选中该镜 */}
          {rowOf.frame && tl.shots.map((s, i) => kf.urls[s.id] && (
            <g key={`f-${s.id}`} className={`tlc__thumb${i === current ? ' is-cur' : ''}`}
               onClick={() => selectShot(s.id)} onDoubleClick={() => onJumpShot(s.id)}>
              <rect x={x(s.start) + 1} y={rowOf.frame.y + 4} width={Math.max(2, s.playable * pps - 2)}
                    height={ROW.frame - 8} rx={3} />
              <image href={kf.urls[s.id]} x={x(s.start) + 2} y={rowOf.frame.y + 5}
                     width={Math.max(1, s.playable * pps - 4)} height={ROW.frame - 10}
                     preserveAspectRatio="xMidYMid meet" />
              <title>{`${s.id} 关键帧`}</title>
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
                {(() => {
                  // 先算好每个节点的标签与位置：当前节点的标签可以放宽，与它相撞的邻居标签这一刻先不写
                  const labels = c.nodes.map((n, ni) => {
                    const on = n.shotId === cur?.id
                    // 标签居中在节点下方，最多占到左右相邻节点的中点，相邻标签就不会叠
                    const gap = Math.min(ni ? n.t - c.nodes[ni - 1].t : Infinity,
                                         ni < c.nodes.length - 1 ? c.nodes[ni + 1].t - n.t : Infinity) * pps
                    const tag = fitText(n.action, on ? Math.max(gap, 160) : Math.min(gap, 200) - 6, 11, 3)
                    // 居中放不下时往里挪：贴着泳道名一栏或画布右缘的标签不被挡住半截
                    const half = textPx(tag) / 2
                    const tx = Math.min(Math.max(x(n.t), GUTTER + 4 + half), Math.max(GUTTER + 4 + half, width - 4 - half))
                    return { on, tag, tx, half }
                  })
                  const hot = labels.find((l) => l.on && l.tag)
                  return labels.map((l) => (hot && !l.on && Math.abs(l.tx - hot.tx) < l.half + hot.half + 6
                    ? { ...l, tag: '' } : l))
                })().map(({ on, tag, tx }, ni) => {
                  const n = c.nodes[ni]
                  return (
                    <g key={n.shotId} className={`tlc__node${n.t <= t ? ' is-past' : ''}${on ? ' is-cur' : ''}`}
                       data-node={`${c.ref}@${n.shotId}`}
                       onClick={() => selectShot(n.shotId)}
                       onDoubleClick={() => {
                         if (!editing) return
                         setNodeEdit({ shotId: n.shotId, ref: c.ref,
                                       value: n.fromShotAction ? '' : n.action,
                                       left: x(n.t), top: cy + ty })
                       }}>
                      <circle cx={x(n.t)} cy={cy} r={on ? 6 : 4} />
                      {tag && <text x={tx} y={cy + 19} textAnchor="middle">{tag}</text>}
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
                <text x={x(m.start) + 8} y={rowOf.music.y + 17}>{fitText(label(MOOD, m.mood), (m.end - m.start) * pps - 14)}</text>
              )}
              <title>{`${m.mood ? label(MOOD, m.mood) : ''} ${m.intensity ?? ''}${m.label ? `\n${m.label}` : ''}`}</title>
            </g>
          ))}
        </g>

        {/* 时间刻度（不随上下平移） */}
        <g className="tlc__ruler">
          <rect x={0} y={0} width={width} height={RULER} />
          {range && (
            <rect className="tlc__rangeruler" x={x(range.start)} y={0}
                  width={Math.max(1, (range.end - range.start) * pps)} height={RULER} />
          )}
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
          <line className="tlc__gutterline" x1={GUTTER} x2={GUTTER} y1={RULER} y2={height} />
          {rows.map((r) => r.sub ? (
            <g key={r.key}>
              <text className="tlc__lname" x={12} y={r.y + 18}>{fitText(r.label, GUTTER - 20, 12)}</text>
              <text className="tlc__lsub" x={12} y={r.y + 32}>{r.sub}</text>
              <title>{`${r.sub} ${r.label}`}</title>
            </g>
          ) : (
            <text key={r.key} className="tlc__lfixed" x={12} y={r.y + r.h / 2 + 4}>{r.label}</text>
          ))}
        </g>

        {/* 播放头 */}
        <line className="tlc__head" x1={playX} x2={playX} y1={0} y2="100%" />
        <polygon className="tlc__head" points={`${playX - 6},0 ${playX + 6},0 ${playX},8`} />
      </svg>

      {/* 播放时的预览窗：当前镜的关键帧（没图给镜头描述占位）+ 此刻在念的旁白 / 台词字幕 */}
      {playing && animatic && cur && (
        <div className="tlc__pip" onPointerDown={(e) => e.stopPropagation()}>
          {curVideo && film.files[curVideo]
            ? <video ref={videoRef} src={film.files[curVideo]} muted={curSpan?.clip.mute_native} playsInline />
            : kf.urls[cur.id]
              ? <img src={kf.urls[cur.id]} alt={`${cur.id} 关键帧`} />
              : (
                <div className="tlc__pipph"><p>{cur.shot.action}</p></div>
              )}
          {filmMode && !curVideo && <span className="tlc__pipnote">未出片</span>}
          <div className="tlc__subs">
            {speechAt(tl, t).map((sp, i) => (
              <p key={i} className={`tlc__sub tlc__sub--${sp.kind}`}>
                {sp.kind === 'dialogue' && sp.who ? `${sp.who}：` : ''}{sp.text}
              </p>
            ))}
          </div>
          <span className="tlc__pipclock">{cur.id} · {label(SHOT_SIZE, cur.shot.shot_size)} · {fmtClock(t)}{stopAt.current !== null && ` / ${fmtClock(stopAt.current)}`}</span>
        </div>
      )}

      {nodeEdit && (
        <input className="tlc__nodeedit" autoFocus value={nodeEdit.value}
               placeholder="本镜动作（留空则用镜头描述）"
               style={{ left: nodeEdit.left, top: nodeEdit.top }}
               onPointerDown={(e) => e.stopPropagation()}
               onChange={(e) => setNodeEdit({ ...nodeEdit, value: e.target.value })}
               onKeyDown={(e) => {
                 if (e.key === 'Enter') finishNodeEdit(true)
                 if (e.key === 'Escape') finishNodeEdit(false)
               }}
               onBlur={() => finishNodeEdit(true)} />
      )}

      </div>

      <aside className={`tlc__panel${shown !== 'shot' ? ' tlc__panel--wide'
               : editing ? ' tlc__panel--edit' : ''}`}
             onPointerDown={(e) => e.stopPropagation()}>
        <nav className="tlc__tabs">
          {([['shot', '本镜'], ['source', '原文'], ['assets', '资产'],
             ...(film.enabled ? [['film', '出片']] : []),
             ...(bench ? [['novel', '剧情'], ['tasks', bench.converting ? '任务 ●' : '任务']] : [])] as [PanelTab, string][])
            .map(([id, name]) => (
              <button key={id} className={shown === id ? 'is-on' : ''} onClick={() => setPanel(id)}>{name}</button>
            ))}
        </nav>
        {shown === 'source' && (
          <SourceView doc={doc} idx={idx} focusUnit={focusUnit} onPickShot={selectShot} />
        )}
        {shown === 'assets' && (
          <AssetsView assets={doc.assets ?? {}} editing={editing}
                      onChange={(kind: AssetKind, id, patch) => commit(updateAsset(docRef.current, kind, id, patch))} />
        )}
        {shown === 'assets' && editable && !editing && (
          <p className="tlc__kfnote">点底部「编辑」后可直接改资产卡，和镜头改动共用撤销与保存。</p>
        )}
        {shown === 'novel' && bench && <NovelPanel bench={bench} />}
        {shown === 'film' && film.enabled && (
          <FilmPanel film={film} selected={clipSel} onPickShot={selectShot} dirty={dirty} />
        )}
        {shown === 'tasks' && bench && <TaskPanel bench={bench} dirty={dirty} />}
        {shown === 'shot' && cur && <>
          {animatic && (
            kf.urls[cur.id]
              ? (
                // 按图自己的比例整张显示：传上来的图未必是成片画幅，裁成 9:16 会只剩中间一条
                <figure className="tlc__frame">
                  <img src={kf.urls[cur.id]} alt={`${cur.id} 关键帧`} />
                  <figcaption>{cur.id} · {fmtClock(cur.start)}</figcaption>
                </figure>
              )
              // 没图只占一条：画面里不塞文字，提示词在下面关键帧一节里看和改
              : <div className="tlc__frame tlc__noframe">{cur.id} · 还没有关键帧图</div>
          )}
          {editing && (
            <ShotCard key={cur.id} shot={cur.shot} idx={idx} editing onPickUnit={onJumpUnit}
                      onChange={(patch) => commit(updateShot(docRef.current, cur.episodeId, cur.id, patch))} />
          )}
          {!editing && <>
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
              <button key={u} className="tlc__unit" onClick={() => onJumpUnit(u)} title="在侧栏「原文」页定位这一句">
                <code>{u}</code> {units[u] ?? ''}
              </button>
            ))}
          </div>
          </>}
          <section className="tlc__kf">
            <div className="tlc__kfhead">
              <b>关键帧</b>
              {kf.urls[cur.id] ? <span className="tag">已上传</span> : <span className="tag tag--ghost">未出图</span>}
            </div>
            <div className="tlc__kfacts">
              <button className="btn btn--sm btn--ghost" disabled={!curPrompt}
                      onClick={() => void navigator.clipboard?.writeText(curPrompt!.prompt)}>
                复制提示词
              </button>
              <button className="btn btn--sm btn--ghost" disabled={!Object.keys(kf.prompts).length}
                      title="全部镜头的关键帧出图提示词（含手改），拿去任意出图工具批量生成"
                      onClick={() => downloadText(`${doc.meta?.title ?? 'storyboard'}-关键帧提示词.md`,
                        promptSheet(doc.meta?.title ?? '', tl.shots.map((x) => kf.promptOf(x.id)!).filter(Boolean)))}>
                下载全章提示词
              </button>
              {kf.canUpload && (
                <>
                  <button className="btn btn--sm" disabled={kf.busy === cur.id}
                          onClick={() => fileRef.current?.click()}>
                    {kf.busy === cur.id ? '上传中…' : kf.urls[cur.id] ? '换图' : '上传图'}
                  </button>
                  {kf.urls[cur.id] && (
                    <button className="btn btn--sm btn--ghost" onClick={() => void kf.remove(cur.id)}>删除</button>
                  )}
                  <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp" hidden
                         onChange={(e) => {
                           const f = e.target.files?.[0]
                           if (f) void kf.upload(cur.id, f)
                           e.target.value = ''
                         }} />
                </>
              )}
            </div>
            {!kf.canUpload && <p className="tlc__kfnote">本地 JSON / 分批预览只有提示词；存进章节版本后才能上传关键帧图。</p>}
            {curPrompt && (
              <>
                <textarea className="tlc__prompt" value={curPrompt.prompt} rows={8}
                          aria-label="本镜关键帧出图提示词"
                          onChange={(e) => kf.editPrompt(cur.id, e.target.value)} />
                <div className="tlc__promptmeta">
                  {curPrompt.negative_prompt && <span>负面：{curPrompt.negative_prompt}</span>}
                  {!!curPrompt.reference_assets.length && <span>垫图：{curPrompt.reference_assets.join('、')}</span>}
                  {cur.id in kf.edited && (
                    <button className="tlc__linkbtn" onClick={() => kf.editPrompt(cur.id, null)}>恢复生成的提示词</button>
                  )}
                </div>
              </>
            )}
            {kf.error && <p className="tlc__kferr">{kf.error}</p>}
          </section>
          <button className="btn btn--sm btn--ghost" onClick={() => onJumpShot(cur.id)}>在分镜页打开这一镜</button>
        </>}
      </aside>
    </div>
  )
}
