import { useEffect, useRef } from 'react'
import { Check } from 'lucide-react'
import { useI18n } from '@/i18n/core'
import type { CardOption } from '../resolve'

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
  const { t } = useI18n()
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
      {!options.length && <p className="cpick__empty">{t('cpick.empty')}</p>}
      <ul className="cpick__list">
        {options.map((c, i) => (
          <li key={c.id}>
            <button
              type="button"
              className={`cpick__item${i === active ? ' is-on' : ''}${isAttached?.(c) ? ' is-attached' : ''}`}
              // 用 mousedown：textarea 的 blur 会先于 click 触发，浮层会被提前收掉
              onMouseDown={(e) => { e.preventDefault(); onPick(c) }}
              onMouseEnter={() => onActive(i)}
            >
              <span className={`cpick__kind cpick__kind--${c.kind}`}>{t(`cpick.kind.${c.kind}`)}</span>
              <b className="cpick__id">{c.id}</b>
              <span className="cpick__name">{c.name}</span>
              {!!c.variants.length && (
                <em className="cpick__var">{t('cpick.variants', { n: c.variants.length })}</em>
              )}
              {isAttached?.(c) && (
                <span className="cpick__on"><Check size={12} aria-hidden />{t('cpick.attached')}</span>
              )}
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
