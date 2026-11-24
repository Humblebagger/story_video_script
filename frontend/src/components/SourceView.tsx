import { TriangleAlert } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Checkbox } from '@/components/ui/checkbox'
import { label, UNIT_KIND } from '../labels'
import type { Index } from '../resolve'
import { pct } from '../resolve'
import type { Storyboard } from '../types'
import { useI18n } from '@/i18n/core'

interface Props {
  doc: Storyboard
  idx: Index
  /** 从分镜卡点过来的溯源目标，滚动定位并高亮 */
  focusUnit: string | null
  /** 画布里用：点句子下的镜头号就在画布上选中那一镜 */
  onPickShot?: (shotId: string) => void
}

/** 命中的关键词高亮，方便在长文里一眼定位 */
function highlight(text: string, q: string) {
  if (!q) return text
  const i = text.toLowerCase().indexOf(q)
  if (i < 0) return text
  return (
    <>
      {text.slice(0, i)}
      <mark className="hl">{text.slice(i, i + q.length)}</mark>
      {text.slice(i + q.length)}
    </>
  )
}

export function SourceView({ doc, idx, focusUnit, onPickShot }: Props) {
  const { t } = useI18n()
  const [onlyGaps, setOnlyGaps] = useState(false)
  const [query, setQuery] = useState('')
  const rowRef = useRef<HTMLLIElement | null>(null)

  useEffect(() => {
    if (focusUnit && rowRef.current) {
      rowRef.current.scrollIntoView({ block: 'center', behavior: 'smooth' })
    }
  }, [focusUnit])

  const units = doc.source?.units ?? []
  const unmapped = new Set(idx.stats.unmapped)
  const q = query.trim().toLowerCase()
  const shown = units.filter((u) =>
    (!onlyGaps || unmapped.has(u.id)) &&
    (!q || u.text.toLowerCase().includes(q) || u.id.includes(q)))
  const groups: { key: string; para?: number; units: typeof shown }[] = []
  for (const u of shown) {
    const key = u.para === undefined ? 'raw' : `p:${u.para}`
    const last = groups[groups.length - 1]
    if (last?.key === key) last.units.push(u)
    else groups.push({ key, para: u.para, units: [u] })
  }

  return (
    <div className="src">
      <div className="src__bar">
        <span>
          {t('source.sumA', { n: units.length })}{' '}
          <b>{pct(idx.stats.coveredRatio)}</b> {t('source.sumB')}{' '}
          <b>{pct(idx.stats.narratedRatio)}</b>
        </span>
        <input
          className="src__search"
          value={query}
          placeholder={t('source.searchPh')}
          onChange={(e) => setQuery(e.target.value)}
        />
        <label className="src__toggle">
          <Checkbox
            checked={onlyGaps}
            onChange={(e) => setOnlyGaps(e.target.checked)}
          />
          {t('source.onlyGaps', { n: unmapped.size })}
        </label>
      </div>

      <div className="src__groups">
        {groups.map((g) => {
          const mapped = g.units.filter((u) => (idx.shotsByUnit.get(u.id)?.length ?? 0) > 0).length
          const ratio = g.units.length ? mapped / g.units.length : 0
          return (
            <section className="src__group" key={g.key}>
              <header className="src__ghead">
                <span className="src__gid">{g.para === undefined ? t('source.groupRaw') : t('source.group', { n: g.para })}</span>
                <span className="src__gstat">{t('source.groupStat', { a: mapped, b: g.units.length })}</span>
                <span className="src__gbar" aria-hidden><span style={{ width: `${Math.round(ratio * 100)}%` }} /></span>
              </header>
              <ol className="src__list">
                {g.units.map((u) => {
                  const refs = idx.shotsByUnit.get(u.id) ?? []
                  const isFocus = u.id === focusUnit
                  return (
                    <li
                      key={u.id}
                      ref={isFocus ? rowRef : null}
                      className={[
                        'unit',
                        isFocus ? 'unit--focus' : '',
                        unmapped.has(u.id) ? 'unit--gap' : refs.length ? 'unit--ref' : '',
                      ].filter(Boolean).join(' ')}
                    >
                      <div className="unit__meta">
                        <span className="unit__id">{u.id}</span>
                        {u.kind && <span className="chip">{label(UNIT_KIND, u.kind)}</span>}
                        {u.para !== undefined && <span className="unit__para">§{u.para}</span>}
                        {idx.narratedUnits.has(u.id) && <span className="chip chip--nar">{t('source.narration')}</span>}
                      </div>
                      <p className="unit__text">{highlight(u.text, q)}</p>
                      <div className="unit__refs">
                        {refs.length === 0
                          ? <span className="unit__gap"><TriangleAlert size={12} aria-hidden />{t('source.noRef')}</span>
                          : refs.map((r) => onPickShot
                            ? (
                              <button className="uref" key={r.shot.id} title={t('source.pickShot')}
                                      onClick={() => onPickShot(r.shot.id)}>{r.shot.id}</button>
                            )
                            : <span className="uref uref--static" key={r.shot.id}>{r.shot.id}</span>)}
                      </div>
                    </li>
                  )
                })}
              </ol>
            </section>
          )
        })}
      </div>
      {!shown.length && <p className="empty">{t('source.empty')}</p>}
    </div>
  )
}
