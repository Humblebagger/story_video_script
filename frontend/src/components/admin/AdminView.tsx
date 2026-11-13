import { useState } from 'react'
import { ArrowLeft } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/i18n/core'
import { cn } from '@/lib/utils'
import type { User } from '../../auth'
import { AuditTab } from './AuditTab'
import { ErrorsTab } from './ErrorsTab'
import { JobsTab } from './JobsTab'
import { Overview } from './Overview'
import { UsageTab } from './UsageTab'
import { Users } from './Users'

type Tab = 'overview' | 'users' | 'usage' | 'jobs' | 'audit' | 'errors'
const TABS: Tab[] = ['overview', 'users', 'usage', 'jobs', 'audit', 'errors']

/** 管理后台：只给管理员看（入口在右上角）；权限以后端为准。 */
export function AdminView({ me, onBack }: { me: User; onBack: () => void }) {
  const [tab, setTab] = useState<Tab>('overview')
  const { t } = useI18n()
  return (
    <div className="adm">
      <header className="adm__head">
        <h2 className="text-base font-semibold">{t('admin.title')}</h2>
        <Button size="sm" variant="ghost" onClick={onBack}><ArrowLeft aria-hidden />{t('admin.back')}</Button>
      </header>
      <nav className="inline-flex rounded-lg bg-muted p-1" aria-label={t('admin.tabsLabel')}>
        {TABS.map((id) => (
          <button
            key={id}
            type="button"
            aria-pressed={tab === id}
            className={cn(
              'tabs__btn rounded-md border-0 px-3 py-1.5 text-sm text-muted-foreground',
              'transition-[color,background-color,box-shadow] duration-150 ease-out hover:text-foreground',
              tab === id && 'is-on bg-background font-medium text-foreground shadow-sm dark:bg-foreground/10',
            )}
            onClick={() => setTab(id)}
          >
            {t(`admin.tabs.${id}`)}
          </button>
        ))}
      </nav>
      {tab === 'overview' && <Overview />}
      {tab === 'users' && <Users me={me} />}
      {tab === 'usage' && <UsageTab />}
      {tab === 'jobs' && <JobsTab />}
      {tab === 'audit' && <AuditTab />}
      {tab === 'errors' && <ErrorsTab />}
    </div>
  )
}
