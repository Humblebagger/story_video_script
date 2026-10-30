import { useState } from 'react'
import type { User } from '../../auth'
import { AuditTab } from './AuditTab'
import { JobsTab } from './JobsTab'
import { Overview } from './Overview'
import { UsageTab } from './UsageTab'
import { Users } from './Users'

type Tab = 'overview' | 'users' | 'usage' | 'jobs' | 'audit'
const TABS: [Tab, string][] = [
  ['overview', '概览'], ['users', '用户'], ['usage', '用量'], ['jobs', '任务'], ['audit', '审计'],
]

/** 管理后台：只给管理员看（入口在右上角）；权限以后端为准。 */
export function AdminView({ me, onBack }: { me: User; onBack: () => void }) {
  const [tab, setTab] = useState<Tab>('overview')
  return (
    <div className="adm">
      <header className="adm__head">
        <h2>管理后台</h2>
        <button className="btn btn--sm btn--ghost" onClick={onBack}>返回</button>
      </header>
      <nav className="tabs">
        {TABS.map(([id, name]) => (
          <button key={id} className={`tabs__btn${tab === id ? ' is-on' : ''}`}
                  onClick={() => setTab(id)}>{name}</button>
        ))}
      </nav>
      {tab === 'overview' && <Overview />}
      {tab === 'users' && <Users me={me} />}
      {tab === 'usage' && <UsageTab />}
      {tab === 'jobs' && <JobsTab />}
      {tab === 'audit' && <AuditTab />}
    </div>
  )
}
