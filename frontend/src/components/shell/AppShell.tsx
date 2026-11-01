/** 应用外壳：左侧可收起的侧边栏（标志、新建小说、小说列表插槽、管理入口、账号与退出）+ 三段式顶栏（左：项目切换器与章节；
 *  中：#topbar-center 步骤条插槽；右：费用表、服务未连通、铃铛、打开本地 JSON、语言、主题、账号菜单）+ 内容区（切换时淡入上移）。
 *  文字全部走语言包。
 *  测试依赖的按钮文字：「管理」「返回书架」「退出」「新建小说」，以及用户名可见（展开时）；收起时只剩图标，aria-label 与提示同文字。
 *  窄屏（< 768px）默认收起。 */
import { useState } from 'react'
import type { ReactNode } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { Bell, FileJson, LogOut, PanelLeftClose, PanelLeftOpen, Plus, Shield, Sparkles } from 'lucide-react'
import { Logo } from '@/components/brand/Logo'
import { LangToggle } from '@/components/common/LangToggle'
import { ThemeToggle } from '@/components/common/ThemeToggle'
import { StatusPill } from '@/components/common/StatusPill'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { useI18n } from '@/i18n/core'
import { cn } from '@/lib/utils'
import { useMotionPresets } from '@/motion'
import { SidebarCollapsedContext, TopbarSlotContext } from './topbarSlot'

export interface AppShellProps {
  username: string
  isAdmin: boolean
  adminOpen: boolean
  onToggleAdmin: () => void
  onLogout: () => void
  onNewNovel: () => void
  onOpenLocal: () => void
  /** 面包屑（没传 projectSwitcher 时用；空则只显示产品名） */
  crumbs?: string[]
  /** 顶栏左侧：项目切换器（没打开小说时不传，显示产品名）与章节切换 */
  projectSwitcher?: ReactNode
  chapterCrumb?: ReactNode
  /** 顶栏右侧：费用表 */
  costMeter?: ReactNode
  /** 任务铃铛：在跑任务数（0 不显示徽标）与点击回调 */
  runningCount?: number
  onToggleActivity?: () => void
  /** 助手入口（进了小说才传）；不传则不显示按钮 */
  onOpenAssistant?: () => void
  /** 铃铛上的「有新完成」小圆点 */
  activityDot?: boolean
  /** 右侧动态面板（ActivityPanel）；null 为收起 */
  activity?: ReactNode
  /** 服务状态：down 为连不上；model 为当前模型；noKey 为没配密钥 */
  service: { down: boolean; model?: string; noKey?: boolean }
  /** 侧边栏中部（小说列表或项目导航） */
  sidebar: ReactNode
  /** 侧边栏内容自己处理收起形态（读 useSidebarCollapsed）：为 true 时收起也不隐藏内容 */
  sidebarHandlesCollapse?: boolean
  /** 内容区的切换键：变了就播一次进场动画 */
  viewKey: string
  children: ReactNode
}

/** 窄屏（< 768px）默认收起 */
const narrow = () => typeof window !== 'undefined' && !!window.matchMedia?.('(max-width: 767px)').matches

/** 收起时图标按钮没有文字：套一层提示，显示与 aria-label 相同的文字；展开时原样渲染 */
function Tip({ on, label, children }: { on: boolean; label: string; children: ReactNode }) {
  if (!on) return <>{children}</>
  return (
    <Tooltip>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent side="right">{label}</TooltipContent>
    </Tooltip>
  )
}

export function AppShell(p: AppShellProps) {
  const { t } = useI18n()
  const m = useMotionPresets()
  const [collapsed, setCollapsed] = useState(narrow)
  const [slot, setSlot] = useState<HTMLElement | null>(null)
  const toggleLabel = collapsed ? t('shell.expand') : t('shell.collapse')
  const adminLabel = p.adminOpen ? t('shell.backToShelf') : t('shell.admin')
  return (
    <TooltipProvider delayDuration={200}>
    <div className="flex min-h-screen bg-background text-foreground" data-testid="app-shell">
      <aside className={cn('sticky top-0 flex h-screen shrink-0 flex-col overflow-hidden border-r border-sidebar-border bg-sidebar text-sidebar-foreground transition-[width] duration-200 ease-out',
                           collapsed ? 'w-16' : 'w-72')}>
        <div className={cn('flex px-3', collapsed ? 'flex-col items-center gap-2 py-3' : 'h-14 items-center justify-between')}>
          <Logo compact={collapsed} />
          <Tip on={collapsed} label={toggleLabel}>
            <Button variant="ghost" size="icon" aria-label={toggleLabel} aria-expanded={!collapsed}
                    onClick={() => setCollapsed((v) => !v)}>
              {collapsed ? <PanelLeftOpen className="size-4" /> : <PanelLeftClose className="size-4" />}
            </Button>
          </Tip>
        </div>
        <div className={cn('pb-2', collapsed ? 'flex justify-center px-0' : 'px-3')}>
          <Tip on={collapsed} label={t('shell.newNovel')}>
            <Button className={collapsed ? '' : 'w-full justify-start gap-2'} size={collapsed ? 'icon' : 'default'}
                    data-tour="new-novel" aria-label={collapsed ? t('shell.newNovel') : undefined} onClick={p.onNewNovel}>
              <Plus className="size-4" />{!collapsed && t('shell.newNovel')}
            </Button>
          </Tip>
        </div>
        <div className={cn('min-h-0 flex-1 overflow-y-auto px-2', collapsed && !p.sidebarHandlesCollapse && 'invisible')}>
          <SidebarCollapsedContext.Provider value={collapsed}>{p.sidebar}</SidebarCollapsedContext.Provider>
        </div>
        <div className={cn('space-y-1 border-t border-sidebar-border', collapsed ? 'flex flex-col items-center py-3' : 'p-3')}>
          {p.isAdmin && (
            <Tip on={collapsed} label={adminLabel}>
              <Button variant="ghost" size={collapsed ? 'icon' : 'default'} className={collapsed ? '' : 'w-full justify-start gap-2'}
                      aria-label={adminLabel} onClick={p.onToggleAdmin}>
                <Shield className="size-4" />{!collapsed && adminLabel}
              </Button>
            </Tip>
          )}
          {collapsed ? (
            <>
              <span className="flex size-7 items-center justify-center rounded-full bg-brand text-xs font-semibold text-white"
                    title={t('shell.signedInAs', { name: p.username })}>
                {p.username.slice(0, 1).toUpperCase()}
              </span>
              <Tip on label={t('shell.logout')}>
                <Button variant="ghost" size="icon" className="text-muted-foreground" aria-label={t('shell.logout')} onClick={p.onLogout}>
                  <LogOut className="size-3.5" />
                </Button>
              </Tip>
            </>
          ) : (
            <div className="flex items-center gap-2 rounded-lg px-2 py-1.5" title={t('shell.signedInAs', { name: p.username })}>
              <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-brand text-xs font-semibold text-white">
                {p.username.slice(0, 1).toUpperCase()}
              </span>
              <span className="min-w-0 flex-1 truncate text-sm">{p.username}</span>
              <Button variant="ghost" size="sm" className="gap-1.5 text-muted-foreground" aria-label={t('shell.logout')} onClick={p.onLogout}>
                <LogOut className="size-3.5" />{t('shell.logout')}
              </Button>
            </div>
          )}
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 grid h-14 grid-cols-[minmax(0,1fr)_auto_minmax(max-content,1fr)] items-center gap-3 border-b bg-background/80 px-5 backdrop-blur supports-[backdrop-filter]:bg-background/60"
                data-testid="topbar">
          <div className="flex min-w-0 items-center gap-1 overflow-hidden">
            {p.projectSwitcher ? (
              <>{p.projectSwitcher}{p.chapterCrumb}</>
            ) : (
              <nav className="min-w-0 truncate text-sm text-muted-foreground" aria-label={t('shell.breadcrumb')}>
                {p.crumbs?.length
                  ? p.crumbs.map((c, i) => (
                    <span key={i}>
                      {i > 0 && <span className="mx-2 opacity-50">/</span>}
                      {i === p.crumbs!.length - 1
                        ? <span className="text-foreground" aria-current="page">{c}</span>
                        : <span>{c}</span>}
                    </span>
                  ))
                  : <span className="text-foreground">{t('brand.name')}</span>}
              </nav>
            )}
          </div>
          <div id="topbar-center" ref={setSlot} className="flex min-w-0 justify-center" />
          <div className="flex items-center justify-end gap-1">
            {p.costMeter}
            {p.service.down && <StatusPill tone="err">{t('shell.serviceDown')}</StatusPill>}
            {p.onOpenAssistant && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button variant="ghost" size="icon" aria-label={t('assistant.open')}
                          data-testid="assistant-open" onClick={p.onOpenAssistant}>
                    <Sparkles className="size-4" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>{t('assistant.open')}</TooltipContent>
              </Tooltip>
            )}
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="ghost" size="icon" className="relative" aria-label={t('shell.activity')}
                        data-testid="activity-bell" onClick={p.onToggleActivity}>
                  <Bell className="size-4" />
                  {!!p.runningCount && (
                    <span data-testid="activity-count"
                          className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 font-mono text-[10px] text-primary-foreground">
                      {p.runningCount}
                    </span>
                  )}
                  {!!p.activityDot && (
                    <span data-testid="activity-dot" aria-label={t('shell.activityNew')}
                          className="absolute right-0.5 top-0.5 size-2 rounded-full bg-destructive" />
                  )}
                </Button>
              </TooltipTrigger>
              <TooltipContent>{t('shell.activity')}</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="ghost" size="icon" aria-label={t('shell.openLocal')} onClick={p.onOpenLocal}>
                  <FileJson className="size-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>{t('shell.openLocal')}</TooltipContent>
            </Tooltip>
            <LangToggle />
            <ThemeToggle />
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon" aria-label={t('shell.account')} data-testid="account-menu">
                  <span className="flex size-7 items-center justify-center rounded-full bg-brand text-xs font-semibold text-white">
                    {p.username.slice(0, 1).toUpperCase()}
                  </span>
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-64">
                <DropdownMenuLabel>{t('shell.signedInAs', { name: p.username })}</DropdownMenuLabel>
                <div className="flex items-center justify-between gap-3 px-2 py-1.5 text-sm">
                  <span className="text-muted-foreground">{t('shell.model')}</span>
                  <span className="min-w-0 truncate font-mono text-xs">
                    {p.service.model ?? '—'}{p.service.noKey && <span className="ml-1 text-destructive">· {t('shell.noKey')}</span>}
                  </span>
                </div>
                <div className="flex items-center justify-between gap-3 px-2 py-1.5 text-sm">
                  <span className="text-muted-foreground">{t('shell.service')}</span>
                  <StatusPill tone={p.service.down ? 'err' : 'ok'}>
                    {p.service.down ? t('shell.serviceDown') : t('shell.serviceOk')}
                  </StatusPill>
                </div>
                <DropdownMenuSeparator />
                {p.isAdmin && (
                  <DropdownMenuItem onSelect={p.onToggleAdmin}><Shield className="size-4" />{adminLabel}</DropdownMenuItem>
                )}
                <DropdownMenuItem onSelect={p.onLogout}><LogOut className="size-4" />{t('shell.logout')}</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </header>
        <div className="flex min-h-0 min-w-0 flex-1">
          <TopbarSlotContext.Provider value={slot}>
            <motion.main key={p.viewKey} {...m.enter} className="min-w-0 flex-1 px-6 py-6">
              {p.children}
            </motion.main>
          </TopbarSlotContext.Provider>
          <AnimatePresence>{p.activity}</AnimatePresence>
        </div>
      </div>
    </div>
    </TooltipProvider>
  )
}
