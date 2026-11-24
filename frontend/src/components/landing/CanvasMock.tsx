/** 首屏的「时间轴画布」示意图：四条泳道（镜头 / 画面 / 语音 / 成片）+ 播放头，跟主题与语言走。
 *  鼠标在上面移动时整体轻微倾斜（视差）；减少动态效果时不动。纯装饰，对读屏隐藏。 */
import { motion, useMotionValue, useReducedMotion, useSpring, useTransform } from 'motion/react'
import { useI18n } from '@/i18n/core'

const SHOTS = [12, 18, 10, 22, 14, 16]
const FRAME_TONES = ['rose', 'blue', 'sand', 'violet'] as const

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
                  className="landing-mock-card relative overflow-hidden rounded-2xl border p-4 shadow-2xl backdrop-blur">
        <div className="mb-3 flex items-center gap-1.5">
          <span className="landing-mock__dot size-2.5 rounded-full" data-tone="rose" />
          <span className="landing-mock__dot size-2.5 rounded-full" data-tone="sand" />
          <span className="landing-mock__dot size-2.5 rounded-full" data-tone="blue" />
          <span className="landing-mock__mode">STORYBOARD</span>
        </div>
        <div className="landing-mock__preview">
          <span className="landing-mock__play" />
          <span className="landing-mock__preview-id">EP·01 / SH003</span>
          <span className="landing-mock__preview-time">4.2s</span>
        </div>
        <div className="landing-mock__grid relative">
          <span className="self-center text-muted-foreground">{t('landing.mock.shots')}</span>
          <div className="landing-mock__lane">
            {SHOTS.map((w, i) => (
              <div key={i} style={{ flexGrow: w }}
                   className="landing-mock__shot h-7 rounded-md border px-1.5 py-1 font-mono text-[10px]"
                   data-active={i === 2 || undefined}>
                SH{String(i + 1).padStart(3, '0')}
              </div>
            ))}
          </div>
          <span className="self-center text-muted-foreground">{t('landing.mock.frames')}</span>
          <div className="landing-mock__lane">
            {SHOTS.map((w, i) => (
              <div key={i} style={{ flexGrow: w }}
                   className="landing-mock__frame h-12 rounded-md"
                   data-tone={FRAME_TONES[i % FRAME_TONES.length]} />
            ))}
          </div>
          <span className="self-center text-muted-foreground">{t('landing.mock.speech')}</span>
          <div className="landing-mock__lane">
            <div style={{ flexGrow: SHOTS[0] + SHOTS[1] }} className="landing-mock__speech truncate rounded-md px-2 py-1 text-[11px]" data-tone="blue">{t('landing.mock.line1')}</div>
            <div style={{ flexGrow: total - SHOTS[0] - SHOTS[1] }} className="landing-mock__speech truncate rounded-md px-2 py-1 text-[11px]" data-tone="rose">{t('landing.mock.line2')}</div>
          </div>
          <span className="self-center text-muted-foreground">{t('landing.mock.film')}</span>
          <div className="landing-mock__lane">
            <div style={{ flexGrow: SHOTS[0] + SHOTS[1] + SHOTS[2] }}
                 className="landing-mock__film h-6 rounded-md px-2 py-1 text-[10px]" data-state="done">✓ {t('landing.mock.rendered')}</div>
            <div style={{ flexGrow: total - SHOTS[0] - SHOTS[1] - SHOTS[2] }}
                 className="landing-mock__film h-6 rounded-md border border-dashed px-2 py-1 text-[10px] text-muted-foreground" data-state="pending">{t('landing.mock.rendering')}…</div>
          </div>
          <div className="landing-mock__playhead pointer-events-none absolute -bottom-1 -top-1 w-px"
               style={{ left: 'calc(var(--lane-offset, 100px) + (100% - var(--lane-offset, 100px)) * 0.43)' }} />
        </div>
      </motion.div>
    </div>
  )
}
