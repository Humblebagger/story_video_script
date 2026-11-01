import { useRef } from 'react'
import { motion } from 'motion/react'
import { Check, ImagePlus, Pencil, Undo2 } from 'lucide-react'
import { useI18n } from '@/i18n/core'
import { cn } from '@/lib/utils'
import { useMotionPresets } from '@/motion'
import { ART_STYLES } from '../../presets'
import { clearStyleImage, setStyleImage, useStyleImages } from '../../styleImages'
import { lookOf, prefixTouched } from '../../styleLook'
import type { NovelParams } from '../../types'

interface Props {
  value: NovelParams
  onChange: (next: NovelParams) => void
  /** 点「自定义」：由父组件打开「更多」并聚焦风格前缀 */
  onCustom?: () => void
  /** 放在胶囊浮层里：小卡片，不显示换图按钮 */
  compact?: boolean
}

export function StylePicker({ value, onChange, onCustom, compact }: Props) {
  const { t } = useI18n()
  const m = useMotionPresets()
  const images = useStyleImages()
  const fileRef = useRef<HTMLInputElement>(null)
  const target = useRef<string>('')

  const pick = (id: string) => {
    const look = lookOf(id)
    const touched = prefixTouched(value.style_prefix)
    onChange({
      ...value, art_style: id,
      ...(look && !touched ? { style_prefix: look.prefix.value } : {}),
    })
  }
  const w = compact ? 'w-[84px]' : 'w-28'
  const hh = compact ? 'h-11' : 'h-16'
  const custom = !ART_STYLES.some((a) => a.value === value.art_style)

  return (
    <div className={cn('flex flex-wrap gap-2', compact && 'w-[276px]')} data-style-picker>
      {ART_STYLES.map((a, i) => {
        const look = lookOf(a.value)
        const on = value.art_style === a.value
        const img = images[a.value]
        return (
          <motion.div key={a.value} {...m.item(i)} className={cn('group relative', w)}>
            <button type="button" data-style={a.value} aria-pressed={on} onClick={() => pick(a.value)}
                    className={cn('block w-full rounded-lg p-0.5 text-left text-xs outline-none ring-offset-2 ring-offset-background transition-shadow focus-visible:ring-2 focus-visible:ring-ring/50',
                                  on ? 'ring-2 ring-primary' : 'hover:ring-1 hover:ring-border')}>
              {img
                ? <img src={img} alt="" className={cn('w-full rounded-md object-cover', hh)} />
                : <span className={cn('block w-full rounded-md', hh)} style={{ background: look?.swatch }} />}
              <span className="mt-1 block truncate px-0.5">{a.label}</span>
              {on && (
                <span className="absolute right-1.5 top-1.5 grid size-4 place-items-center rounded-full bg-primary text-primary-foreground">
                  <Check className="size-3" />
                </span>
              )}
            </button>
            {!compact && (
              <span className="absolute bottom-6 right-1.5 flex gap-1 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100 pointer-coarse:opacity-100">
                {img && (
                  <button type="button" data-style-reset={a.value} title={t('params.styleImageReset')}
                          aria-label={t('params.styleImageResetOf', { name: a.label })} onClick={() => clearStyleImage(a.value)}
                          className="grid size-5 place-items-center rounded bg-background/80 text-foreground shadow-sm hover:bg-background">
                    <Undo2 className="size-3" />
                  </button>
                )}
                <button type="button" data-style-upload={a.value} title={t('params.styleImageChange')}
                        aria-label={t('params.styleImageChangeOf', { name: a.label })}
                        onClick={() => { target.current = a.value; fileRef.current?.click() }}
                        className="grid size-5 place-items-center rounded bg-background/80 text-foreground shadow-sm hover:bg-background">
                  <ImagePlus className="size-3" />
                </button>
              </span>
            )}
          </motion.div>
        )
      })}
      <motion.div {...m.item(ART_STYLES.length)} className={w}>
        <button type="button" data-style-custom aria-pressed={custom} onClick={() => onCustom?.()}
                className={cn('block w-full rounded-lg p-0.5 text-left text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring/50',
                              custom ? 'ring-2 ring-primary' : 'hover:ring-1 hover:ring-border')}>
          <span className={cn('grid w-full place-items-center rounded-md border border-dashed text-muted-foreground', hh)}>
            <Pencil className="size-4" />
          </span>
          <span className="mt-1 block truncate px-0.5">{t('params.styleCustom')}</span>
        </button>
      </motion.div>
      {!compact && (
        <input ref={fileRef} type="file" accept="image/*" hidden data-style-file
               onChange={(e) => {
                 const f = e.target.files?.[0]
                 e.target.value = ''
                 if (f && target.current) void setStyleImage(target.current, f)
               }} />
      )}
    </div>
  )
}
