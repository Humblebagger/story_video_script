/** 首页（没登录时）：顶栏（滚动后磨砂）、首屏（标题、按钮、慢速光斑背景、画布示意图）、功能 6 卡、流程 4 步、
 *  常见问题、结尾号召、页脚。右上角与按钮打开登录 / 注册对话框（由 App 管）。文字全部走语言包。 */
import { useEffect, useState } from 'react'
import { motion, useReducedMotion } from 'motion/react'
import {
  ArrowRight, BookOpenText, Clapperboard, Film, Layers, Mic, ShieldCheck, Sparkles,
} from 'lucide-react'
import { Logo } from '@/components/brand/Logo'
import { LangToggle } from '@/components/common/LangToggle'
import { ThemeToggle } from '@/components/common/ThemeToggle'
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '@/components/ui/accordion'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/i18n/core'
import type { MsgKey } from '@/i18n/core'
import { cn } from '@/lib/utils'
import { CanvasMock } from './CanvasMock'
import { Reveal } from './Reveal'

const FEATURES = [
  { id: 'convert', icon: BookOpenText }, { id: 'check', icon: ShieldCheck }, { id: 'canvas', icon: Layers },
  { id: 'render', icon: Clapperboard }, { id: 'voice', icon: Mic }, { id: 'memory', icon: Sparkles },
] as const
const STEPS = ['import', 'storyboard', 'edit', 'film'] as const
const FAQ = ['cost', 'models', 'privacy', 'edit', 'export'] as const

export function Landing({ onSignIn, onSignUp }: { onSignIn: () => void; onSignUp: () => void }) {
  const { t } = useI18n()
  const reduced = !!useReducedMotion()
  const [scrolled, setScrolled] = useState(false)
  useEffect(() => {
    const on = () => setScrolled(window.scrollY > 8)
    window.addEventListener('scroll', on, { passive: true })
    return () => window.removeEventListener('scroll', on)
  }, [])
  const go = (id: string) => document.getElementById(id)?.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth' })
  const k = (s: string) => s as MsgKey

  return (
    <div className="min-h-screen bg-background text-foreground" data-testid="landing">
      <header className={cn('fixed inset-x-0 top-0 z-40 transition-colors duration-200',
                            scrolled ? 'border-b bg-background/70 backdrop-blur-xl' : 'bg-transparent')}>
        <div className="mx-auto flex h-16 max-w-6xl items-center gap-6 px-6">
          <Logo className="text-base" />
          <nav className="hidden flex-1 items-center justify-center gap-7 text-sm text-muted-foreground md:flex">
            {(['features', 'workflow', 'faq'] as const).map((id) => (
              <button key={id} type="button" onClick={() => go(id)} className="transition-colors hover:text-foreground">
                {t(k(`landing.nav.${id}`))}
              </button>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-1 md:ml-0">
            <LangToggle />
            <ThemeToggle />
            <Button variant="ghost" size="sm" onClick={onSignIn} data-testid="landing-login">{t('landing.signIn')}</Button>
            <Button size="sm" onClick={onSignUp} data-testid="landing-register">{t('landing.signUp')}</Button>
          </div>
        </div>
      </header>

      <section className="relative overflow-hidden pb-24 pt-36">
        <div aria-hidden className="pointer-events-none absolute inset-0 -z-0">
          <motion.div className="absolute -top-32 left-1/2 h-[520px] w-[820px] -translate-x-1/2 rounded-full bg-brand opacity-20 blur-3xl"
                      animate={reduced ? undefined : { x: ['-52%', '-48%', '-52%'], y: [0, 24, 0] }}
                      transition={{ duration: 18, repeat: Infinity, ease: 'easeInOut' }} />
          <div className="absolute inset-0 opacity-[0.035] [background-image:radial-gradient(currentColor_1px,transparent_1px)] [background-size:3px_3px]" />
        </div>
        <div className="relative mx-auto max-w-6xl px-6 text-center">
          <Reveal>
            <p className="mb-5 inline-flex items-center gap-2 rounded-full border bg-card/60 px-3 py-1 text-xs text-muted-foreground backdrop-blur">
              <Film className="size-3.5" />{t('landing.eyebrow')}
            </p>
          </Reveal>
          <Reveal delay={0.05}>
            <h1 className="mx-auto max-w-3xl text-5xl font-semibold tracking-tight md:text-7xl">
              <span className="text-brand">{t('landing.title')}</span>
            </h1>
          </Reveal>
          <Reveal delay={0.1}>
            <p className="mx-auto mt-6 max-w-2xl text-lg text-muted-foreground">{t('landing.subtitle')}</p>
          </Reveal>
          <Reveal delay={0.15} className="mt-9 flex flex-wrap items-center justify-center gap-3">
            <Button size="lg" onClick={onSignUp} className="gap-2">{t('landing.start')}<ArrowRight className="size-4" /></Button>
            <Button size="lg" variant="outline" onClick={() => go('workflow')}>{t('landing.seeFlow')}</Button>
          </Reveal>
          <Reveal delay={0.25} className="mt-16"><CanvasMock /></Reveal>
        </div>
      </section>

      <section id="features" className="mx-auto max-w-6xl scroll-mt-20 px-6 py-24">
        <Reveal className="mx-auto max-w-2xl text-center">
          <h2 className="text-3xl font-semibold tracking-tight md:text-4xl">{t('landing.featuresTitle')}</h2>
          <p className="mt-4 text-muted-foreground">{t('landing.featuresSub')}</p>
        </Reveal>
        <div className="mt-14 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map(({ id, icon: Icon }, i) => (
            <Reveal key={id} delay={i * 0.05}>
              <div className="group h-full rounded-2xl border bg-card p-6 transition-all duration-200 hover:-translate-y-0.5 hover:border-brand-to/40 hover:shadow-lg">
                <div className="mb-4 flex size-10 items-center justify-center rounded-xl bg-muted text-foreground transition-colors group-hover:bg-brand group-hover:text-white">
                  <Icon className="size-5" />
                </div>
                <h3 className="font-semibold">{t(k(`landing.features.${id}.title`))}</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{t(k(`landing.features.${id}.desc`))}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </section>

      <section id="workflow" className="scroll-mt-20 border-y bg-muted/30 py-24">
        <div className="mx-auto max-w-6xl px-6">
          <Reveal className="text-center">
            <h2 className="text-3xl font-semibold tracking-tight md:text-4xl">{t('landing.workflowTitle')}</h2>
          </Reveal>
          <ol className="relative mt-14 grid gap-8 md:grid-cols-4">
            <div aria-hidden className="absolute left-0 right-0 top-5 hidden h-px bg-border md:block">
              <motion.div className="h-full origin-left bg-brand"
                          initial={{ scaleX: reduced ? 1 : 0 }} whileInView={{ scaleX: 1 }}
                          viewport={{ once: true }} transition={{ duration: 1.2, ease: 'easeOut' }} />
            </div>
            {STEPS.map((id, i) => (
              <Reveal key={id} delay={i * 0.15}>
                <li className="relative list-none">
                  <span className="relative z-10 flex size-10 items-center justify-center rounded-full border bg-background font-mono text-sm font-semibold">
                    {i + 1}
                  </span>
                  <h3 className="mt-4 font-semibold">{t(k(`landing.steps.${id}.title`))}</h3>
                  <p className="mt-1.5 text-sm text-muted-foreground">{t(k(`landing.steps.${id}.desc`))}</p>
                </li>
              </Reveal>
            ))}
          </ol>
        </div>
      </section>

      <section id="faq" className="mx-auto max-w-3xl scroll-mt-20 px-6 py-24">
        <Reveal className="text-center">
          <h2 className="text-3xl font-semibold tracking-tight md:text-4xl">{t('landing.faqTitle')}</h2>
        </Reveal>
        <Reveal className="mt-10">
          <Accordion type="single" collapsible className="w-full">
            {FAQ.map((id) => (
              <AccordionItem key={id} value={id}>
                <AccordionTrigger className="text-left">{t(k(`landing.faq.${id}.q`))}</AccordionTrigger>
                <AccordionContent className="text-muted-foreground">{t(k(`landing.faq.${id}.a`))}</AccordionContent>
              </AccordionItem>
            ))}
          </Accordion>
        </Reveal>
      </section>

      <section className="px-6 pb-24">
        <Reveal className="relative mx-auto max-w-5xl overflow-hidden rounded-3xl border bg-card px-8 py-16 text-center">
          <div aria-hidden className="absolute inset-x-0 -top-24 mx-auto h-48 w-2/3 rounded-full bg-brand opacity-20 blur-3xl" />
          <h2 className="relative text-3xl font-semibold tracking-tight md:text-4xl">{t('landing.ctaTitle')}</h2>
          <p className="relative mt-4 text-muted-foreground">{t('landing.ctaSub')}</p>
          <Button size="lg" className="relative mt-8 gap-2" onClick={onSignUp}>
            {t('landing.signUp')}<ArrowRight className="size-4" />
          </Button>
        </Reveal>
      </section>

      <footer className="border-t">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-6 py-8 text-sm text-muted-foreground">
          <Logo />
          <span>{t('landing.footer')}</span>
          <LangToggle />
        </div>
      </footer>
    </div>
  )
}
