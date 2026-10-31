/** 应用外壳：左侧可收起的侧边栏（标志、新建小说、小说列表插槽、管理入口、账号与退出）+ 顶栏（面包屑、服务状态、
 *  打开本地 JSON、语言与主题）+ 内容区（切换时淡入上移）。文字全部走语言包。
 *  测试依赖的按钮文字：「管理」「返回书架」「退出」「新建小说」，以及用户名可见（展开时）；收起时只剩图标，aria-label 与提示同文字。
 *  窄屏（< 768px）默认收起。 */
import { useState } from 'react'
import type { ReactNode } from 'react'
import { motion } from 'motion/react'
import { FileJson, LogOut, PanelLeftClose, PanelLeftOpen, Plus, Shield } from 'lucide-react'
import { Logo } from '@/components/brand/Logo'
import { LangToggle } from '@/components/common/LangToggle'
import { ThemeToggle } from '@/components/common/ThemeToggle'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { useI18n } from '@/i18n/core'
import { cn } from '@/lib/utils'
import { useMotionPresets } from '@/motion'

export interface AppShellProps {
  username: string
  isAdmin: boolean
  adminOpen: boolean
  onToggleAdmin: () => void
  onLogout: () => void
  onNewNovel: () => void
  onOpenLocal: () => void
  /** 面包屑（小说名 / 章节 / 版本），空则只显示产品名 */
  crumbs: string[]
  /** 服务状态：down 为连不上；model 为当前模型；noKey 为没配密钥 */
  service: { down: boolean; model?: string; noKey?: boolean }
  /** 侧边栏中部（小说列表） */
  sidebar: ReactNode
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
                    aria-label={collapsed ? t('shell.newNovel') : undefined} onClick={p.onNewNovel}>
              <Plus className="size-4" />{!collapsed && t('shell.newNovel')}
            </Button>
          </Tip>
        </div>
        <div className={cn('min-h-0 flex-1 overflow-y-auto px-2', collapsed && 'invisible')}>{p.sidebar}</div>
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
        <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b bg-background/80 px-5 backdrop-blur supports-[backdrop-filter]:bg-background/60">
          <nav className="min-w-0 flex-1 truncate text-sm text-muted-foreground" aria-label={t('shell.breadcrumb')}>
            {p.crumbs.length
              ? p.crumbs.map((c, i) => (
                <span key={i}>
                  {i > 0 && <span className="mx-2 opacity-50">/</span>}
                  {i === p.crumbs.length - 1
                    ? <span className="text-foreground" aria-current="page">{c}</span>
                    : <span>{c}</span>}
                </span>
              ))
              : <span className="text-foreground">{t('brand.name')}</span>}
          </nav>
          {p.service.down
            ? <Badge variant="destructive">{t('shell.serviceDown')}</Badge>
            : p.service.model && (
              <Badge variant="outline" className="font-mono text-xs font-normal">
                {p.service.model}{p.service.noKey && <span className="ml-1 text-destructive">· {t('shell.noKey')}</span>}
              </Badge>
            )}
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
        </header>
        <motion.main key={p.viewKey} {...m.enter} className="min-w-0 flex-1 px-6 py-6">
          {p.children}
        </motion.main>
      </div>
    </div>
    </TooltipProvider>
  )
}
