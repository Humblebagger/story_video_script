/** 新手提示：每 800ms 找第一条没看过、目标可见的提示，浮在目标旁；一次一条，Esc 等于「知道了」 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { motion } from 'motion/react'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/i18n/core'
import { useMotionPresets } from '@/motion'
import { TOUR, markSeen, seen, tourEnabled } from '@/tour'
import type { TourId } from '@/tour'

const GAP = 8
const MARGIN = 16

const targetOf = (id: TourId) => document.querySelector<HTMLElement>(`[data-tour="${id}"]`)
const visible = (el: HTMLElement | null) => {
  if (!el) return false
  const r = el.getBoundingClientRect()
  return r.width > 0 && r.height > 0
}

export function Tour({ force }: { force?: boolean }) {
  const { t } = useI18n()
  const m = useMotionPresets()
  const [cur, setCur] = useState<TourId | null>(null)
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null)
  const card = useRef<HTMLDivElement>(null)
  const on = !!force || tourEnabled()

  const find = useCallback(() => {
    const done = seen()
    const next = TOUR.find((id) => !done.includes(id) && visible(targetOf(id))) ?? null
    setCur((c) => (c && !done.includes(c) && visible(targetOf(c)) ? c : next))
  }, [])

  useEffect(() => {
    if (!on) return
    find()
    const timer = setInterval(find, 800)
    window.addEventListener('resize', find)
    return () => { clearInterval(timer); window.removeEventListener('resize', find) }
  }, [on, find])

  // 高亮目标；换条或关掉时摘掉
  useEffect(() => {
    const el = cur ? targetOf(cur) : null
    el?.setAttribute('data-tour-on', '')
    return () => el?.removeAttribute('data-tour-on')
  }, [cur])

  // 定位：目标下方 8px，放不下放上方，水平夹在视口内
  useEffect(() => {
    const el = cur ? targetOf(cur) : null
    const c = card.current
    if (!el || !c) { setPos(null); return }
    const place = () => {
      const r = el.getBoundingClientRect()
      const w = c.offsetWidth, h = c.offsetHeight
      const below = r.bottom + GAP
      const top = below + h + MARGIN > window.innerHeight && r.top - GAP - h >= MARGIN ? r.top - GAP - h : below
      const left = Math.max(MARGIN, Math.min(r.left, window.innerWidth - w - MARGIN))
      setPos({ left, top })
    }
    place()
    window.addEventListener('resize', place)
    window.addEventListener('scroll', place, true)
    return () => { window.removeEventListener('resize', place); window.removeEventListener('scroll', place, true) }
  }, [cur])

  const ok = useCallback(() => {
    if (!cur) return
    markSeen([cur])
    setCur(null)
    setPos(null)
  }, [cur])
  const skip = () => { markSeen(TOUR); setCur(null); setPos(null) }

  useEffect(() => {
    if (!cur) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') ok() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [cur, ok])

  if (!on || !cur) return null
  return createPortal(
    <motion.div ref={card} data-testid="tour-tip" role="dialog" aria-live="polite"
                aria-label={t(`tour.${cur}.title`)}
                initial={{ opacity: 0, scale: m.pop.initial.scale }} animate={{ opacity: 1, scale: 1 }}
                transition={m.pop.transition}
                style={{ position: 'fixed', zIndex: 60, left: pos?.left ?? MARGIN, top: pos?.top ?? MARGIN,
                         visibility: pos ? 'visible' : 'hidden' }}
                className="w-72 rounded-xl border bg-popover p-4 text-popover-foreground shadow-lg">
      <span className="absolute right-4 top-4 text-xs text-muted-foreground">
        {t('tour.count', { n: TOUR.indexOf(cur) + 1, total: TOUR.length })}
      </span>
      <p className="pr-12 text-sm font-medium">{t(`tour.${cur}.title`)}</p>
      <p className="mt-1 text-sm text-muted-foreground">{t(`tour.${cur}.body`)}</p>
      <div className="mt-4 flex items-center justify-between">
        <Button variant="ghost" size="sm" onClick={skip}>{t('tour.skip')}</Button>
        <Button size="sm" onClick={ok}>{t('tour.ok')}</Button>
      </div>
    </motion.div>,
    document.body,
  )
}
