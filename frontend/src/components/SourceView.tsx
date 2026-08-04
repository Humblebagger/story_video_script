import { useEffect, useRef, useState } from 'react'
import { label, UNIT_KIND } from '../labels'
import type { Index } from '../resolve'
import { pct } from '../resolve'
import type { Storyboard } from '../types'

interface Props {
  doc: Storyboard
  idx: Index
  /** 从分镜卡点过来的溯源目标，滚动定位并高亮 */
  focusUnit: string | null
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

export function SourceView({ doc, idx, focusUnit }: Props) {
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

  return (
    <div className="src">
      <div className="src__bar">
        <span>
          原文 {units.length} 句 · 已被镜头覆盖{' '}
          <b>{pct(idx.stats.coveredRatio)}</b> · 念作旁白{' '}
          <b>{pct(idx.stats.narratedRatio)}</b>
        </span>
        <input
          className="src__search"
          value={query}
          placeholder="搜索原文 / 句子编号"
          onChange={(e) => setQuery(e.target.value)}
        />
        <label className="src__toggle">
          <input
            type="checkbox"
            checked={onlyGaps}
            onChange={(e) => setOnlyGaps(e.target.checked)}
          />
          只看未覆盖（{unmapped.size}）
        </label>
      </div>

      <ol className="src__list">
        {shown.map((u) => {
          const refs = idx.shotsByUnit.get(u.id) ?? []
          const isFocus = u.id === focusUnit
          return (
            <li
              key={u.id}
              ref={isFocus ? rowRef : null}
              className={[
                'unit',
                isFocus ? 'unit--focus' : '',
                unmapped.has(u.id) ? 'unit--gap' : '',
              ].filter(Boolean).join(' ')}
            >
              <div className="unit__meta">
                <span className="unit__id">{u.id}</span>
                {u.kind && <span className="tag tag--kind">{label(UNIT_KIND, u.kind)}</span>}
                {u.para !== undefined && <span className="unit__para">§{u.para}</span>}
                {idx.narratedUnits.has(u.id) && <span className="tag tag--nar">旁白</span>}
              </div>
              <p className="unit__text">{highlight(u.text, q)}</p>
              <div className="unit__refs">
                {refs.length === 0
                  ? <span className="unit__gap">⚠ 无镜头引用</span>
                  : refs.map((r) => (
                      <span className="uref uref--static" key={r.shot.id}>{r.shot.id}</span>
                    ))}
              </div>
            </li>
          )
        })}
      </ol>
      {!shown.length && <p className="empty">没有符合条件的句子。</p>}
    </div>
  )
}
