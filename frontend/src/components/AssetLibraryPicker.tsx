import { useState } from 'react'
import type { AssetWork } from '../types'

const KIND_LABEL: Record<string, string> = {
  characters: '人物', locations: '场景', props: '道具', creatures: '生物',
}

interface Props {
  works: AssetWork[]
  selected: string | null
  onSelect: (workTitle: string | null) => void
}

/** 生产页的历史资料卡：勾选某部作品后，其 C/S/P/A 卡作为【已有资产库】注入本次转换，
 *  模型须沿用已有 ID 与描述——续写下一章时角色不会换脸、场景不会改建。 */
export function AssetLibraryPicker({ works, selected, onSelect }: Props) {
  const [open, setOpen] = useState(false)
  if (!works.length) return null

  const active = works.find((w) => w.work_title === selected) ?? null

  return (
    <section className="alib">
      <header className="alib__head">
        <div>
          <b>历史资料卡</b>
          <span className="alib__hint">
            续写同一部作品时沿用已有人物/场景卡，角色 ID 与外貌保持一致，防跨章漂移
          </span>
        </div>
        {active && (
          <button type="button" className="btn btn--sm btn--ghost"
                  onClick={() => setOpen((v) => !v)}>
            {open ? '收起卡片' : '查看卡片'}
          </button>
        )}
      </header>

      <div className="alib__works">
        <button
          type="button"
          className={`wchip${selected === null ? ' is-on' : ''}`}
          onClick={() => onSelect(null)}
        >
          不沿用
        </button>
        {works.map((w) => (
          <button
            type="button"
            key={w.work_title}
            className={`wchip${selected === w.work_title ? ' is-on' : ''}`}
            onClick={() => onSelect(w.work_title)}
          >
            {w.work_title}
            <em>
              {Object.entries(w.counts)
                .filter(([, n]) => n > 0)
                .map(([k, n]) => `${KIND_LABEL[k] ?? k}${n}`)
                .join(' · ')}
            </em>
          </button>
        ))}
      </div>

      {active && open && (
        <div className="alib__cards">
          {(['characters', 'locations', 'props', 'creatures'] as const).map((kind) => {
            const list = active.assets[kind] ?? []
            if (!list.length) return null
            return (
              <div className="alib__group" key={kind}>
                <h4>{KIND_LABEL[kind]}</h4>
                <div className="alib__grid">
                  {list.map((c) => (
                    <div className="lcard" key={c.id}>
                      <span className="lcard__id">{c.id}</span>
                      <b>{c.name}</b>
                      {'visual_prompt' in c && c.visual_prompt && (
                        <p>{c.visual_prompt}</p>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </section>
  )
}
