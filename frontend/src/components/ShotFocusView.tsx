/** 镜头三栏视图：左栏按集分组的镜头列表，中栏选中镜头的完整编辑，右栏关键帧 / 成片段与原文出处。 */
import { useContext, useEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties, KeyboardEvent } from 'react'
import { motion } from 'motion/react'
import { ChevronDown, Search } from 'lucide-react'
import { StepPrimaryContext } from '@/components/workflow/chapterHead'
import { useI18n } from '@/i18n/core'
import { primaryArgs } from '@/lib/fmt'
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
    const list = listRef.current
    const item = document.getElementById(optId(curId))
    if (!list || !item || !list.contains(item)) return
    const box = list.getBoundingClientRect()
    const row = item.getBoundingClientRect()
    if (row.top < box.top) list.scrollTop -= box.top - row.top
    else if (row.bottom > box.bottom) list.scrollTop += row.bottom - box.bottom
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
    shot.id.startsWith(`${cur.ep}-`) ? shot.id : `${cur.ep}-${shot.id}`,
    label(SHOT_SIZE, shot.shot_size),
    label(CAMERA_MOVEMENT, shot.camera?.movement),
    typeof shot.duration_sec === 'number' ? `${shot.duration_sec.toFixed(1)}s` : '',
  ].filter(Boolean).join(' · ')
  const ratio = (doc.meta?.video?.aspect_ratio ?? '16:9').replace(':', ' / ')
  const showSave = dirty && canSave
  // 在章节页里时，本步的主按钮（去出片、出剩余各段……）由这里的通栏按钮接管；画布入口在视图顶部
  const step = useContext(StepPrimaryContext)
  const claim = step?.claim
  useEffect(() => {
    if (!claim) return
    // 手机列表页把详情栏（连同里面的主按钮）藏起来了：
    // 这里不能再接管通栏按钮，否则整页会失去唯一的下一步入口。
    claim(!narrow)
    return () => claim(false)
  }, [claim, narrow])
  const stepAct = !showSave && step && step.primary.action !== 'none' && step.primary.action !== 'save'
    ? step : null

  return (
    <div className="focus">
      {showList && (
        <div className="focus__list">
          <label className="focus__searchbox">
            <Search size={14} aria-hidden />
            <input
              className="focus__search" type="search" value={query} placeholder={t('board.focus.search')}
              aria-label={t('board.focus.search')} onChange={(e) => setQuery(e.target.value)}
            />
          </label>
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
                    data-issue={issues.get(s.id)} className="focus__item" title={s.action} onClick={() => pick(s.id)}
                  >
                    {urls[s.id]
                      ? <img className="focus__thumb" src={urls[s.id]} alt="" />
                      : <span className="focus__thumb" style={{ background: hue(s) }} />}
                    <span className="focus__item-body">
                      <span className="focus__item-top">
                        <span className="focus__item-id">{s.id}</span>
                        <span className={`deriv deriv--${s.source?.derivation}`}>
                          {label(DERIVATION, s.source?.derivation)}
                        </span>
                        <span className="focus__item-dur">{playableSeconds(s).toFixed(1)}s</span>
                        {issues.has(s.id) && <span className="focus__dot" data-issue={issues.get(s.id)} />}
                      </span>
                      <span className="focus__item-summary">{s.action}</span>
                    </span>
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
              className="focus__frame" data-testid="focus-frame"
              style={{ aspectRatio: ratio, '--frame-hue': hue(shot) } as CSSProperties}
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
            {stepAct?.primary.blocked && (
              <div className="focus__reason" role="status" data-testid="focus-reason">
                <span>{t(stepAct.primary.blocked.reason)}</span>
                {(stepAct.primary.blocked.fix.step || stepAct.primary.blocked.fix.target || stepAct.primary.blocked.fix.openFilm) && (
                  <button type="button" className="focus__fix" onClick={() => stepAct.fix(stepAct.primary.blocked!.fix)}>
                    {t('flow.fix')}
                  </button>
                )}
              </div>
            )}
            {stepAct ? (
              <button
                type="button" className="focus__primary focus__primary--step" data-testid="focus-primary"
                disabled={!!stepAct.primary.blocked || stepAct.busy} onClick={stepAct.run}
              >
                {t(stepAct.primary.label, primaryArgs(stepAct.primary))}
              </button>
            ) : (
              <button
                type="button" className="focus__primary" data-testid="focus-primary" disabled={saving && showSave}
                onClick={showSave ? onSave : onOpenCanvas}
              >
                {t(showSave ? 'board.focus.saveEdits' : 'board.focus.openCanvas')}
              </button>
            )}
          </motion.aside>
        </>
      )}
    </div>
  )
}
