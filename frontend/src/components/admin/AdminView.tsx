// 文案与样式跟着这一块代码一起加载；挂文案必须排在最前面（下面的模块有的在加载时就读文案）
import './i18n'
import './admin.css'
import { useEffect, useState } from 'react'
import { LangToggle } from '@/components/common/LangToggle'
import { ThemeToggle } from '@/components/common/ThemeToggle'
import { useI18n } from '@/i18n/core'
import { cn } from '@/lib/utils'
import { BRAND } from '../../brand'
import { adminErrors, adminOverview, adminSafetyCount } from './api'
import type { User } from '../../auth'
import { adminPath } from '../../paths'
import type { AdminPage, JobState, UsageDays, UsageGroup } from '../../paths'
import { AdminSidebar, AdminTopNav } from './AdminNav'
import { AuditTab } from './AuditTab'
import { navCounts } from './derive'
import { ErrorsTab } from './ErrorsTab'
import { JobsTab } from './JobsTab'
import { AdminNavContext } from './navContext'
import type { AdminNavFn } from './navContext'
import { Overview } from './Overview'
import { SafetyTab } from './SafetyTab'
import { UsageTab } from './UsageTab'
import { useLoad } from './useLoad'
import { Users } from './Users'

export interface AdminViewProps {
  me: User
  /** 当前页与筛选都来自地址（paths.ts 的 parseLocation） */
  page: AdminPage
  jobState: JobState | null
  usageGroup: UsageGroup
  usageDays: UsageDays
  /** 后台内部跳转（上层改地址） */
  onNav: AdminNavFn
  /** 返回产品 */
  onBack: () => void
}

const NARROW = '(max-width: 767px)'
const COLLAPSE_KEY = 'inkreel.admin.navCollapsed'

/** 窄屏（< 768px）：导航改成顶部下拉；跟着窗口宽度变 */
function useNarrow() {
  const [narrow, setNarrow] = useState(() => typeof window !== 'undefined' && !!window.matchMedia?.(NARROW).matches)
  useEffect(() => {
    const mq = window.matchMedia?.(NARROW)
    if (!mq?.addEventListener) return
    const sync = () => setNarrow(mq.matches)
    mq.addEventListener('change', sync)
    return () => mq.removeEventListener('change', sync)
  }, [])
  return narrow
}

const readCollapsed = () => {
  try { return localStorage.getItem(COLLAPSE_KEY) === '1' } catch { return false }
}

/** 运营后台的外框：左侧分组导航（窄屏为顶部下拉）+ 右侧内容。只给管理员看；权限以后端为准。 */
export function AdminView(p: AdminViewProps) {
  const { t } = useI18n()
  // 浏览器标题由后台自己设：只有后台真的渲染出来（确认是管理员）才会出现后台的名字
  useEffect(() => {
    document.title = `${t(`admin.nav.pages.${p.page}`)} · ${t('admin.title')} — ${BRAND.id}`
  }, [p.page, t])
  // 概览数据放在外框：导航计数与概览页共用一份，每 30 秒刷新
  const overview = useLoad(adminOverview, [], 30000)
  const errors = useLoad(adminErrors, [], 60000)
  const blocked = useLoad(adminSafetyCount, [], 60000)
  const counts = navCounts(overview.data, errors.data, Date.now(), blocked.data)
  const narrow = useNarrow()
  const [collapsed, setCollapsed] = useState(readCollapsed)
  const toggle = () => setCollapsed((v) => {
    try { localStorage.setItem(COLLAPSE_KEY, v ? '0' : '1') } catch { /* 存不了就只在本次有效 */ }
    return !v
  })
  const tools = (
    <>
      <LangToggle /><ThemeToggle />
      <span className="adm-side__user min-w-0 truncate text-xs text-muted-foreground">{p.me.username}</span>
    </>
  )
  return (
    <AdminNavContext.Provider value={p.onNav}>
      <div className={cn('adm-shell', narrow && 'is-narrow', !narrow && collapsed && 'is-collapsed')} data-testid="admin-shell">
        {narrow
          ? <AdminTopNav page={p.page} counts={counts} onBack={p.onBack} tools={tools}
                         onPage={(id) => p.onNav(adminPath(id))} />
          : <AdminSidebar page={p.page} counts={counts} onBack={p.onBack} tools={tools}
                          collapsed={collapsed} onToggle={toggle} />}
        <main className="adm">
          {p.page === 'overview' && <Overview shared={overview} />}
          {p.page === 'users' && <Users me={p.me} />}
          {p.page === 'usage' && (
            <UsageTab group={p.usageGroup} days={p.usageDays}
                      onQuery={(group, days) => p.onNav(adminPath('usage', { group, days }), true)} />
          )}
          {p.page === 'jobs' && (
            <JobsTab state={p.jobState} onState={(state) => p.onNav(adminPath('jobs', { state }), true)} />
          )}
          {p.page === 'errors' && <ErrorsTab />}
          {p.page === 'safety' && <SafetyTab />}
          {p.page === 'audit' && <AuditTab />}
        </main>
      </div>
    </AdminNavContext.Provider>
  )
}
