/** 镜头三栏视图：左栏按集分组的镜头列表，中栏选中镜头的完整编辑，右栏关键帧 / 成片段与原文出处。 */
import { useEffect, useMemo, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { motion } from 'motion/react'
import { ChevronDown } from 'lucide-react'
import { useI18n } from '@/i18n/core'
import { useMedia } from '@/lib/useMedia'
import { useMotionPresets } from '@/motion'
import { filmFileUrl } from '../api'
import { CAMERA_MOVEMENT, DERIVATION, label, SHOT_SIZE } from '../labels'
import type { Index } from '../resolve'
import { clipForShot, filterShots, flatShots, shotIssues, SIZE_HUE, stepShot } from '../shotFocus'
import type { FilmSession, Shot, Storyboard, VerificationReport, VersionRef } from '../types'
import { playableSeconds } from '../timeline'
import { useShotImages } from '../useShotImages'
import { ShotCard } from './ShotCard'

interface Props {
  doc: Storyboard
  idx: Index
  report?: VerificationReport | null
  film?: FilmSession | null
  version?: VersionRef | null
  imagesKey?: unknown
  readOnly: boolean
  dirty: boolean
  saving: boolean
  canSave: boolean
  /** 外部要求选中的镜头（画布跳回）；n 每变一次就重新选中，同一镜可反复定位 */
  focusShot?: { id: string; n: number } | null
  onShotChange: (episodeId: string, shotId: string, patch: Partial<Shot>) => void
  onPickUnit: (unitId: string) => void
  onSave: () => void
  onOpenCanvas: () => void
}

const optId = (id: string) => `focus-opt-${id}`
const epId = (ep: string) => `focus-ep-${ep}`
const hue = (shot: Shot) => `hsl(${SIZE_HUE[shot.shot_size] ?? 200} 55% 50% / .35)`

export function ShotFocusView({
  doc, idx, report, film, version, imagesKey, readOnly, dirty, saving, canSave,
  focusShot, onShotChange, onPickUnit, onSave, onOpenCanvas,
}: Props) {
  const { t } = useI18n()
  const m = useMotionPresets()
  const narrow = useMedia('(max-width: 759px)')
  const rows = useMemo(() => flatShots(doc), [doc])
  const issues = useMemo(() => shotIssues(report, doc), [report, doc])
  const urls = useShotImages(version, imagesKey)

  const [sel, setSel] = useState<string>(rows[0]?.shot.id ?? '')
  const [query, setQuery] = useState('')
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const [editingNarrow, setEditingNarrow] = useState(false)
  const [view, setView] = useState<{ id: string; mode: 'frame' | 'clip' }>({ id: '', mode: 'frame' })
  const listRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!focusShot) return
    // n 是触发器：同一镜头也能反复定位
    setSel(focusShot.id)
    setEditingNarrow(true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusShot?.n])

  const showList = !narrow || !editingNarrow
  const showEdit = !narrow || editingNarrow
  const cur = rows.find((r) => r.shot.id === sel) ?? rows[0]
  const curId = cur?.shot.id

  useEffect(() => {
    if (!curId) return
    document.getElementById(optId(curId))?.scrollIntoView?.({ block: 'nearest' })
  }, [curId, showList])

  const shown = useMemo(() => filterShots(rows, query), [rows, query])
  const groups = useMemo(() => {
    const g: { ep: string; rows: typeof rows }[] = []
    for (const r of shown) {
      const last = g[g.length - 1]
      if (last && last.ep === r.ep) last.rows.push(r)
      else g.push({ ep: r.ep, rows: [r] })
    }
    return g
  }, [shown])

  const clip = cur ? clipForShot(film, cur.shot.id) : null
  const file = clip?.file ?? null
  const mode = file && view.id === curId ? view.mode : 'frame'
  const [clipUrl, setClipUrl] = useState<string | null>(null)
  const { nid, cid, vid } = version ?? {}
  useEffect(() => {
    if (mode !== 'clip' || !file || !nid || !cid || !vid) { setClipUrl(null); return }
    let gone = false
    let made: string | null = null
    void filmFileUrl(nid, cid, vid, file).then((u) => {
      if (gone) URL.revokeObjectURL(u)
      else { made = u; setClipUrl(u) }
    }).catch(() => { /* 取不到就留空 */ })
    return () => { gone = true; if (made) URL.revokeObjectURL(made); setClipUrl(null) }
  }, [mode, file, nid, cid, vid])

  const onKey = (e: KeyboardEvent) => {
    const tag = (e.target as HTMLElement).tagName
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
    const dir = e.key === 'ArrowDown' ? 1 : e.key === 'ArrowUp' ? -1
      : e.key === 'Home' ? 'home' : e.key === 'End' ? 'end' : null
    if (dir === null || !curId) return
    e.preventDefault()
    setSel(stepShot(shown, curId, dir, collapsed))
  }

  const toggle = (ep: string) => setCollapsed((s) => {
    const n = new Set(s)
    if (n.has(ep)) n.delete(ep); else n.add(ep)
    return n
  })

  const pick = (id: string) => { setSel(id); setEditingNarrow(true) }

  const shot = cur?.shot
  const title = shot && [
    `${cur.ep}-${shot.id}`,
    label(SHOT_SIZE, shot.shot_size),
    label(CAMERA_MOVEMENT, shot.camera?.movement),
    typeof shot.duration_sec === 'number' ? `${shot.duration_sec.toFixed(1)}s` : '',
  ].filter(Boolean).join(' · ')
  const ratio = (doc.meta?.video?.aspect_ratio ?? '16:9').replace(':', ' / ')
  const showSave = dirty && canSave

  return (
    <div className="focus">
      {showList && (
        <div className="focus__list">
          <input
            className="focus__search" type="search" value={query} placeholder={t('board.focus.search')}
            aria-label={t('board.focus.search')} onChange={(e) => setQuery(e.target.value)}
          />
          <div
            ref={listRef} className="focus__scroll" role="listbox" tabIndex={0}
            aria-label={t('board.focus.listAria')} onKeyDown={onKey}
            aria-activedescendant={curId && shown.some((r) => r.shot.id === curId) ? optId(curId) : undefined}
          >
            {groups.map((g) => {
              const closed = collapsed.has(g.ep)
              return (
                <div key={g.ep} role="group" aria-labelledby={epId(g.ep)}>
                <button
                  type="button" className="focus__ep" aria-expanded={!closed}
                  onClick={() => toggle(g.ep)}
                >
                  <ChevronDown size={14} className="focus__caret" aria-hidden />
                  <span id={epId(g.ep)} className="focus__ep-id">{g.ep}</span>
                  <span className="focus__ep-n">{t('board.focus.epCount', { n: g.rows.length })}</span>
                </button>
                {closed ? null : g.rows.map(({ shot: s }) => (
                  <div
                    key={s.id} id={optId(s.id)} role="option" tabIndex={-1} data-shot={s.id} aria-selected={s.id === curId}
                    data-issue={issues.get(s.id)} className="focus__item" onClick={() => pick(s.id)}
                  >
                    {urls[s.id]
                      ? <img className="focus__thumb" src={urls[s.id]} alt="" />
                      : <span className="focus__thumb" style={{ background: hue(s) }} />}
                    <span className="focus__item-id">{s.id}</span>
                    <span className={`deriv deriv--${s.source?.derivation}`}>
                      {label(DERIVATION, s.source?.derivation)}
                    </span>
                    <span className="focus__item-dur">{playableSeconds(s).toFixed(1)}s</span>
                    {issues.has(s.id) && <span className="focus__dot" data-issue={issues.get(s.id)} />}
                  </div>
                ))}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {showEdit && shot && cur && (
        <>
          <div className="focus__main">
            {narrow && (
              <button type="button" className="focus__back" onClick={() => setEditingNarrow(false)}>
                {'← ' + t('board.focus.backToList')}
              </button>
            )}
            <motion.div key={shot.id} {...m.enter} className="focus__pane">
              <h3 className="focus__title">{title}</h3>
              <ShotCard
                shot={shot} idx={idx} editing={!readOnly} onPickUnit={onPickUnit}
                onChange={(p) => onShotChange(cur.ep, shot.id, p)}
              />
            </motion.div>
          </div>

          <motion.aside key={shot.id} {...m.enter} className="focus__side">
            {file && (
              <div className="focus__seg" role="group" data-testid="focus-media">
                {(['frame', 'clip'] as const).map((k) => (
                  <button
                    key={k} type="button" aria-pressed={mode === k}
                    onClick={() => setView({ id: shot.id, mode: k })}
                  >
                    {t(k === 'frame' ? 'board.focus.frame' : 'board.focus.clip')}
                  </button>
                ))}
              </div>
            )}
            <div
              className="focus__frame" data-testid="focus-frame" style={{ aspectRatio: ratio, background: hue(shot) }}
            >
              {mode === 'clip' && clipUrl
                ? <video src={clipUrl} controls />
                : urls[shot.id]
                  ? <img src={urls[shot.id]} alt={shot.id} />
                  : <span className="focus__frame-id">{shot.id}</span>}
            </div>
            <div data-testid="focus-source">
              {shot.source?.unit_refs?.length ? (
                <ul className="focus__source">
                  {shot.source.unit_refs.map((u) => (
                    <li key={u}>
                      <button type="button" onClick={() => onPickUnit(u)}>
                        <span className="focus__source-id">{u}</span>
                        <span>{idx.unitText(u)}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              ) : <p className="focus__none">{t('board.focus.noSource')}</p>}
            </div>
            <button
              type="button" className="focus__primary" data-testid="focus-primary" disabled={saving && showSave}
              onClick={showSave ? onSave : onOpenCanvas}
            >
              {t(showSave ? 'board.focus.saveEdits' : 'board.focus.openCanvas')}
            </button>
          </motion.aside>
        </>
      )}
    </div>
  )
}
