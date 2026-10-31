/** 标志：一枚带品牌渐变的胶片格（墨滴变胶片），加名字。size 控制图形边长。 */
import { useI18n } from '@/i18n/core'
import { cn } from '@/lib/utils'

export function LogoMark({ size = 24, className }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden className={className}>
      <defs>
        <linearGradient id="inkreel-g" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="var(--brand-from)" />
          <stop offset="1" stopColor="var(--brand-to)" />
        </linearGradient>
      </defs>
      <rect x="3" y="3" width="26" height="26" rx="8" fill="url(#inkreel-g)" />
      <path d="M16 8c3.5 4.2 5.5 7.3 5.5 10a5.5 5.5 0 0 1-11 0c0-2.7 2-5.8 5.5-10Z" fill="white" fillOpacity=".92" />
      <rect x="7" y="7" width="2" height="3" rx=".6" fill="white" fillOpacity=".55" />
      <rect x="7" y="22" width="2" height="3" rx=".6" fill="white" fillOpacity=".55" />
      <rect x="23" y="7" width="2" height="3" rx=".6" fill="white" fillOpacity=".55" />
      <rect x="23" y="22" width="2" height="3" rx=".6" fill="white" fillOpacity=".55" />
    </svg>
  )
}

export function Logo({ className, compact }: { className?: string; compact?: boolean }) {
  const { t } = useI18n()
  return (
    <span className={cn('inline-flex items-center gap-2 font-semibold tracking-tight', className)} title={t('brand.name')}>
      <LogoMark />
      {!compact && <span>{t('brand.name')}</span>}
    </span>
  )
}
