import { useEffect, useRef } from 'react'
import type { CardOption } from '../resolve'

const KIND_TAG: Record<CardOption['kind'], string> = {
  characters: '角色', locations: '场景', props: '道具', creatures: '生物',
}

/** 按 ID / 名称 / 别名 命中。别名很关键：原文里「老栓」「华老栓」是同一个人，
 *  打 @ 时按哪个叫法都得能选到 */
export function matchCards(options: CardOption[], query: string): CardOption[] {
  const q = query.trim().toLowerCase()
  if (!q) return options
  return options.filter((c) =>
    c.id.toLowerCase().includes(q) ||
    c.name.toLowerCase().includes(q) ||
    c.aliases.some((a) => a.toLowerCase().includes(q)))
}

interface Props {
  options: CardOption[]
  /** 高亮项下标：@ 模式下由 textarea 的方向键驱动，所以受控 */
  active: number
  onActive: (i: number) => void
  onPick: (card: CardOption) => void
  onClose: () => void
  /** 已挂在本镜头上的卡：标出来，避免重复挂 */
  isAttached?: (card: CardOption) => boolean
  hint?: string
}

export function CardPicker({
  options, active, onActive, onPick, onClose, isAttached, hint,
}: Props) {
  const box = useRef<HTMLDivElement | null>(null)

  // 点外面就收起来；捕获阶段监听，免得被卡片自身的点击先吃掉
  useEffect(() => {
    const away = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) onClose()
    }
    document.addEventListener('mousedown', away, true)
    return () => document.removeEventListener('mousedown', away, true)
  }, [onClose])

  return (
    <div className="cpick" ref={box}>
      {hint && <p className="cpick__hint">{hint}</p>}
      {!options.length && <p className="cpick__empty">没有匹配的资产卡</p>}
      <ul className="cpick__list">
        {options.map((c, i) => (
          <li key={c.id}>
            <button
              type="button"
              className={`cpick__item${i === active ? ' is-on' : ''}`}
              // 用 mousedown：textarea 的 blur 会先于 click 触发，浮层会被提前收掉
              onMouseDown={(e) => { e.preventDefault(); onPick(c) }}
              onMouseEnter={() => onActive(i)}
            >
              <span className={`cpick__kind cpick__kind--${c.kind}`}>{KIND_TAG[c.kind]}</span>
              <b className="cpick__id">{c.id}</b>
              <span className="cpick__name">{c.name}</span>
              {!!c.variants.length && (
                <em className="cpick__var">{c.variants.length} 个变体</em>
              )}
              {isAttached?.(c) && <span className="cpick__on">已挂</span>}
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
