/** 首页（没登录时）：顶栏（滚动后磨砂）、非对称首屏（大标题、按钮、画布示意图）、功能索引、流程 4 步、
 *  常见问题、结尾号召、页脚。右上角与按钮打开登录 / 注册对话框（由 App 管）。文字全部走语言包。 */
import { useEffect, useState } from 'react'
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
  const { t, locale } = useI18n()
  const [scrolled, setScrolled] = useState(false)
  useEffect(() => {
    const on = () => setScrolled(window.scrollY > 8)
    window.addEventListener('scroll', on, { passive: true })
    return () => window.removeEventListener('scroll', on)
  }, [])
  const go = (id: string) => document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' })
  const k = (s: string) => s as MsgKey

  return (
    <div className="landing-page min-h-screen" data-testid="landing" data-locale={locale}>
      <header className={cn('fixed inset-x-0 top-0 z-40 transition-colors duration-200',
                            scrolled ? 'border-b bg-background/70 backdrop-blur-xl' : 'bg-transparent')}>
        <div className="mx-auto flex h-16 max-w-[1240px] items-center gap-6 px-6">
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
            <Button variant="ghost" size="sm" className="hidden sm:inline-flex" onClick={onSignIn} data-testid="landing-login">{t('landing.signIn')}</Button>
            <Button size="sm" onClick={onSignUp} data-testid="landing-register">{t('landing.signUp')}</Button>
          </div>
        </div>
      </header>

      <section className="landing-hero relative overflow-hidden">
        <div aria-hidden className="landing-hero__wash" />
        <div className="landing-hero__grid relative mx-auto max-w-[1240px] px-6">
          <div className="landing-hero__copy">
            <Reveal>
              <p className="landing-kicker">
                <span className="landing-kicker__dot" />
                {t('landing.eyebrow')}
              </p>
            </Reveal>
            <Reveal delay={0.05}>
              <h1 className="landing-title">{t('landing.title')}</h1>
            </Reveal>
            <Reveal delay={0.1}>
              <p className="landing-subtitle">{t('landing.subtitle')}</p>
            </Reveal>
            <Reveal delay={0.15} className="landing-hero__actions">
              <Button size="lg" onClick={onSignUp} className="gap-2">{t('landing.start')}<ArrowRight className="size-4" /></Button>
              <Button size="lg" variant="outline" onClick={() => go('workflow')}>{t('landing.seeFlow')}</Button>
            </Reveal>
            <Reveal delay={0.2} className="landing-hero__meta">
              {[t('landing.mock.shots'), t('landing.mock.speech'), t('landing.mock.film')].map((label, i) => (
                <span key={label} className="landing-hero__meta-item">
                  <span className="landing-hero__meta-no">0{i + 1}</span>{label}
                </span>
              ))}
            </Reveal>
          </div>
          <Reveal delay={0.18} className="landing-hero__visual">
            <div className="landing-hero__visual-caption">
              <span>STORYBOARD / 01</span>
              <span className="landing-hero__visual-rule" />
            </div>
            <CanvasMock />
            <p className="landing-hero__visual-note">
              <Film className="size-3.5" />{t('landing.eyebrow')}
            </p>
          </Reveal>
        </div>
      </section>

      <section id="features" className="mx-auto max-w-[1240px] scroll-mt-24 px-6 py-24 lg:py-32">
        <Reveal className="landing-section__head">
          <p className="landing-kicker"><span className="landing-kicker__no">01</span>{t('landing.nav.features')}</p>
          <h2 className="landing-display">{t('landing.featuresTitle')}</h2>
          <p className="landing-section__sub">{t('landing.featuresSub')}</p>
        </Reveal>
        <div className="landing-index">
          {FEATURES.map(({ id, icon: Icon }, i) => (
            <Reveal key={id} delay={i * 0.04} className="landing-index__item">
              <span className="landing-index__no">{String(i + 1).padStart(2, '0')}</span>
              <span className="landing-index__icon"><Icon className="size-5" /></span>
              <div className="landing-index__body">
                <h3>{t(k(`landing.features.${id}.title`))}</h3>
                <p>{t(k(`landing.features.${id}.desc`))}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </section>

      <section id="workflow" className="landing-flow scroll-mt-24 border-y py-24 lg:py-32">
        <div className="mx-auto max-w-[1240px] px-6">
          <Reveal className="landing-section__head landing-section__head--row">
            <div>
              <p className="landing-kicker"><span className="landing-kicker__no">02</span>{t('landing.nav.workflow')}</p>
              <h2 className="landing-display">{t('landing.workflowTitle')}</h2>
            </div>
          </Reveal>
            <ol className="landing-steps">
            {STEPS.map((id, i) => (
              <Reveal key={id} as="li" delay={i * 0.08} className="landing-step">
                <span className="landing-step__no">{String(i + 1).padStart(2, '0')}</span>
                <h3>{t(k(`landing.steps.${id}.title`))}</h3>
                <p>{t(k(`landing.steps.${id}.desc`))}</p>
              </Reveal>
            ))}
            </ol>
        </div>
      </section>

      <section id="faq" className="landing-faq mx-auto max-w-[1240px] scroll-mt-24 px-6 py-24 lg:py-32">
        <div className="landing-faq__grid">
          <Reveal className="landing-faq__head">
            <p className="landing-kicker"><span className="landing-kicker__no">03</span>{t('landing.nav.faq')}</p>
            <h2 className="landing-display">{t('landing.faqTitle')}</h2>
          </Reveal>
          <Reveal>
            <Accordion type="single" collapsible className="w-full">
              {FAQ.map((id) => (
                <AccordionItem key={id} value={id}>
                  <AccordionTrigger className="text-left">{t(k(`landing.faq.${id}.q`))}</AccordionTrigger>
                  <AccordionContent className="text-muted-foreground">{t(k(`landing.faq.${id}.a`))}</AccordionContent>
                </AccordionItem>
              ))}
            </Accordion>
          </Reveal>
        </div>
      </section>

      <section className="landing-cta-band">
        <Reveal className="landing-cta mx-auto max-w-[1240px] px-6 py-24 lg:py-32">
          <p className="landing-kicker landing-kicker--inverse"><span className="landing-kicker__dot" />INKREEL</p>
          <h2 className="landing-cta__title">{t('landing.ctaTitle')}</h2>
          <p className="landing-cta__sub">{t('landing.ctaSub')}</p>
          <Button size="lg" className="landing-cta__button gap-2" onClick={onSignUp}>
            {t('landing.signUp')}<ArrowRight className="size-4" />
          </Button>
        </Reveal>
      </section>

      <footer className="landing-footer border-t">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-6 py-8 text-sm text-muted-foreground">
          <Logo />
          <span>{t('landing.footer')}</span>
          <LangToggle />
        </div>
      </footer>
    </div>
  )
}
