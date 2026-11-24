import type { ReactNode } from 'react'
import {
  ArrowLeft, ChartColumn, LayoutDashboard, ListChecks, PanelLeftClose, PanelLeftOpen, ScrollText, ShieldAlert, TriangleAlert, Users,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { SelectMenu } from '@/components/ui/select'
import { useI18n } from '@/i18n/core'
import { cn } from '@/lib/utils'
import { adminPath } from '../../paths'
import type { AdminPage } from '../../paths'
import { AdminLink } from './AdminLink'
import { badgeText, NAV_GROUPS } from './derive'

const ICONS: Record<AdminPage, LucideIcon> = {
  overview: LayoutDashboard, users: Users, usage: ChartColumn, jobs: ListChecks, errors: TriangleAlert, safety: ShieldAlert, audit: ScrollText,
}

export interface AdminNavProps {
  page: AdminPage
  /** 导航项旁的计数；没有这一项就不显示 */
  counts: Partial<Record<AdminPage, number>>
  onBack: () => void
  /** 语言、主题切换与当前账号 */
  tools: ReactNode
}

/** 计数的说明文字（徽标的 title，也给读屏用） */
function useCountLabel() {
  const { t } = useI18n()
  return (page: AdminPage, n: number) =>
    (page === 'jobs' || page === 'errors' || page === 'usage' || page === 'safety' ? t(`admin.nav.counts.${page}`, { n }) : String(n))
}

/** 宽屏：左侧分组导航，可收起成只有图标的窄条。 */
export function AdminSidebar({ page, counts, onBack, tools, collapsed, onToggle }: AdminNavProps & {
  collapsed: boolean; onToggle: () => void
}) {
  const { t } = useI18n()
  const countLabel = useCountLabel()
  const toggleLabel = collapsed ? t('admin.nav.expand') : t('admin.nav.collapse')
  return (
    <aside className="adm-side" data-testid="admin-sidebar">
      <div className="adm-side__head">
        {!collapsed && <h1 className="truncate text-sm font-semibold">{t('admin.title')}</h1>}
        <Button variant="ghost" size="icon" aria-label={toggleLabel} title={toggleLabel} aria-expanded={!collapsed}
                data-testid="admin-nav-toggle" onClick={onToggle}>
          {collapsed ? <PanelLeftOpen className="size-4" /> : <PanelLeftClose className="size-4" />}
        </Button>
      </div>
      <Button variant="ghost" size={collapsed ? 'icon' : 'sm'} className={collapsed ? '' : 'justify-start gap-2'}
              aria-label={collapsed ? t('admin.back') : undefined} title={collapsed ? t('admin.back') : undefined}
              data-testid="admin-back" onClick={onBack}>
        <ArrowLeft aria-hidden className="size-4" />{!collapsed && t('admin.back')}
      </Button>
      <nav className="adm-nav" aria-label={t('admin.nav.label')}>
        {NAV_GROUPS.map((g) => (
          <div key={g.id} className="adm-nav__group">
            {!collapsed && <p className="adm-nav__title">{t(`admin.nav.groups.${g.id}`)}</p>}
            {g.pages.map((id) => {
              const Icon = ICONS[id]
              const name = t(`admin.nav.pages.${id}`)
              const n = counts[id]
              return (
                <AdminLink key={id} to={adminPath(id)} data-testid={`admin-nav-${id}`}
                           className={cn('adm-nav__item', page === id && 'is-on')}
                           aria-current={page === id ? 'page' : undefined}
                           aria-label={collapsed ? name : undefined} title={collapsed ? name : undefined}>
                  <Icon aria-hidden className="size-4 shrink-0" />
                  {!collapsed && <span className="min-w-0 flex-1 truncate">{name}</span>}
                  {n !== undefined && (
                    <span className={cn('adm-nav__badge', id === 'usage' && 'is-warn')} data-testid={`admin-count-${id}`}
                          title={countLabel(id, n)} aria-label={countLabel(id, n)}>
                      {badgeText(n)}
                    </span>
                  )}
                </AdminLink>
              )
            })}
          </div>
        ))}
      </nav>
      <div className="adm-side__foot">{tools}</div>
    </aside>
  )
}

/** 窄屏：顶部一条，导航变成下拉框（计数写在选项文字里）。 */
export function AdminTopNav({ page, counts, onBack, tools, onPage }: AdminNavProps & { onPage: (page: AdminPage) => void }) {
  const { t } = useI18n()
  return (
    <header className="adm-top" data-testid="admin-topnav">
      <Button variant="ghost" size="icon" aria-label={t('admin.back')} title={t('admin.back')}
              data-testid="admin-back" onClick={onBack}>
        <ArrowLeft aria-hidden className="size-4" />
      </Button>
      <h1 className="adm-top__title text-sm font-semibold">{t('admin.title')}</h1>
      <SelectMenu
        className="ui-select adm-top__select"
        testId="admin-nav-select"
        ariaLabel={t('admin.nav.label')}
        value={page}
        onChange={(v) => onPage(v as AdminPage)}
        options={NAV_GROUPS.flatMap((g) => g.pages.map((id) => ({
          value: id,
          group: t(`admin.nav.groups.${g.id}`),
          label: `${t(`admin.nav.pages.${id}`)}${counts[id] !== undefined
            ? t('common.paren', { text: badgeText(counts[id]) })
            : ''}`,
        })))}
      />
      <div className="flex shrink-0 items-center">{tools}</div>
    </header>
  )
}
