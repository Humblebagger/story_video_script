/** 首屏的「时间轴画布」示意图：四条泳道（镜头 / 画面 / 语音 / 成片）+ 播放头，跟主题与语言走。
 *  鼠标在上面移动时整体轻微倾斜（视差）；减少动态效果时不动。纯装饰，对读屏隐藏。 */
import { motion, useMotionValue, useReducedMotion, useSpring, useTransform } from 'motion/react'
import { useI18n } from '@/i18n/core'

const SHOTS = [12, 18, 10, 22, 14, 16]

export function CanvasMock() {
  const { t } = useI18n()
  const reduced = !!useReducedMotion()
  const mx = useMotionValue(0)
  const my = useMotionValue(0)
  const rx = useSpring(useTransform(my, [-1, 1], [4, -4]), { stiffness: 120, damping: 18 })
  const ry = useSpring(useTransform(mx, [-1, 1], [-6, 6]), { stiffness: 120, damping: 18 })
  const total = SHOTS.reduce((a, b) => a + b, 0)
  return (
    <div aria-hidden className="mx-auto w-full max-w-4xl [perspective:1200px]"
         onMouseMove={(e) => {
           if (reduced) return
           const r = e.currentTarget.getBoundingClientRect()
           mx.set(((e.clientX - r.left) / r.width) * 2 - 1)
           my.set(((e.clientY - r.top) / r.height) * 2 - 1)
         }}
         onMouseLeave={() => { mx.set(0); my.set(0) }}>
      <motion.div style={reduced ? undefined : { rotateX: rx, rotateY: ry }}
                  className="relative overflow-hidden rounded-2xl border bg-card/80 p-4 shadow-2xl backdrop-blur">
        <div className="mb-3 flex items-center gap-1.5">
          <span className="size-2.5 rounded-full bg-destructive/70" />
          <span className="size-2.5 rounded-full bg-warning/70" />
          <span className="size-2.5 rounded-full bg-success/70" />
        </div>
        <div className="grid grid-cols-[88px_1fr] gap-x-3 gap-y-2 text-xs">
          <span className="self-center text-muted-foreground">{t('landing.mock.shots')}</span>
          <div className="flex gap-1">
            {SHOTS.map((w, i) => (
              <div key={i} style={{ flexGrow: w }}
                   className={`h-7 rounded-md border ${i === 2 ? 'border-transparent bg-brand text-white' : 'bg-secondary'} px-1.5 py-1 font-mono text-[10px]`}>
                SH{String(i + 1).padStart(3, '0')}
              </div>
            ))}
          </div>
          <span className="self-center text-muted-foreground">{t('landing.mock.frames')}</span>
          <div className="flex gap-1">
            {SHOTS.map((w, i) => (
              <div key={i} style={{ flexGrow: w, opacity: 0.55 + (i % 3) * 0.15 }}
                   className="h-12 rounded-md bg-gradient-to-br from-brand-from/40 to-brand-to/30" />
            ))}
          </div>
          <span className="self-center text-muted-foreground">{t('landing.mock.speech')}</span>
          <div className="flex gap-1">
            <div style={{ flexGrow: SHOTS[0] + SHOTS[1] }} className="truncate rounded-md bg-muted px-2 py-1 text-[11px]">{t('landing.mock.line1')}</div>
            <div style={{ flexGrow: total - SHOTS[0] - SHOTS[1] }} className="truncate rounded-md bg-muted px-2 py-1 text-[11px]">{t('landing.mock.line2')}</div>
          </div>
          <span className="self-center text-muted-foreground">{t('landing.mock.film')}</span>
          <div className="flex gap-1">
            <div style={{ flexGrow: SHOTS[0] + SHOTS[1] + SHOTS[2] }}
                 className="h-6 rounded-md bg-success/25 px-2 py-1 text-[10px] text-success">✓ {t('landing.mock.rendered')}</div>
            <div style={{ flexGrow: total - SHOTS[0] - SHOTS[1] - SHOTS[2] }}
                 className="h-6 rounded-md border border-dashed px-2 py-1 text-[10px] text-muted-foreground">{t('landing.mock.rendering')}…</div>
          </div>
        </div>
        <div className="pointer-events-none absolute bottom-3 top-12 w-px bg-brand-to" style={{ left: 'calc(88px + 2.75rem + 38%)' }} />
      </motion.div>
    </div>
  )
}
