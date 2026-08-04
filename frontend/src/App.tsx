import { useCallback, useEffect, useRef, useState } from 'react'
import {
  deleteHistory, getHistory, health, listHistory, listJobs, listLibrary, me, saveHistory,
} from './api'
import { clearSession, getCachedUser, getToken, onUnauthorized } from './auth'
import type { User } from './auth'
import { ConvertForm } from './components/ConvertForm'
import { HistoryPanel } from './components/HistoryPanel'
import { JobPanel } from './components/JobPanel'
import { LibraryView } from './components/LibraryView'
import { LoginView } from './components/LoginView'
import { StoryboardView } from './components/StoryboardView'
import { notify, primeNotifications } from './notify'
import type {
  ConvertRequest, Health, HistorySummary, Job, JobSummary, LibraryWork, Storyboard,
} from './types'
import { useJob } from './useJob'

const RUNNING = ['queued', 'running']

export default function App() {
  const [user, setUser] = useState<User | null>(() => (getToken() ? getCachedUser() : null))
  const [page, setPage] = useState<'convert' | 'library'>('convert')
  const [svc, setSvc] = useState<Health | null>(null)
  const [svcDown, setSvcDown] = useState(false)

  const [runs, setRuns] = useState<HistorySummary[]>([])
  const [running, setRunning] = useState<JobSummary[]>([])
  const [runsLoading, setRunsLoading] = useState(true)
  const [works, setWorks] = useState<LibraryWork[]>([])

  const [doc, setDoc] = useState<Storyboard | null>(null)
  const [docId, setDocId] = useState<string | null>(null)
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [alert, setAlert] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const refresh = useCallback(async () => {
    try {
      const [h, a] = await Promise.all([listHistory(), listLibrary()])
      setRuns(h.runs)
      setWorks(a.works)
    } catch {
      /* 服务未连通时由 svcDown 统一提示，这里不再重复报错 */
    } finally {
      setRunsLoading(false)
    }
  }, [])

  /** 完成播报去重：附着轮询与后台巡检可能同时发现同一个任务结束 */
  const announced = useRef<Set<string>>(new Set())
  const announce = useCallback((j: { id: string; status: string;
                                     work_title?: string | null;
                                     chapter?: string | null }) => {
    if (announced.current.has(j.id)) return
    announced.current.add(j.id)
    const who = `${j.work_title ?? '分镜'} ${j.chapter ?? ''}`.trim()
    if (j.status === 'failed') notify('转换失败', `${who}——失败原因见日志`)
    else notify(j.status === 'completed_with_warnings' ? '转换完成（质量告警）' : '转换完成',
                `${who} 已生成，点开即可审阅`)
  }, [])

  // 任务跑完且用户正看着它：直接把产物摆出来
  const onJobDone = useCallback((done: Job) => {
    void refresh()
    announce(done)
    if (done.status === 'failed') return
    setDoc(done.result)
    setDocId(done.id)
    setDirty(false)
  }, [refresh, announce])

  const { job, error, submitting, start, attach, reset } = useJob(onJobDone)

  /** 任务列表巡检：独立于「是否正在看某个任务」。
   *  放到后台的任务靠它留在侧栏里可点回去，跑完也靠它播报——
   *  否则一旦松开附着，任务就既看不见也回不去了。 */
  const prevRunning = useRef<Set<string>>(new Set())
  const watchJobs = useCallback(async () => {
    try {
      const { jobs } = await listJobs()
      const live = jobs.filter((x) => RUNNING.includes(x.status))
      setRunning(live)
      const liveIds = new Set(live.map((x) => x.id))
      // 上一轮还在跑、这一轮不在了 → 刚刚结束
      let finished = false
      for (const id of prevRunning.current) {
        if (liveIds.has(id)) continue
        const done = jobs.find((x) => x.id === id)
        if (done) { announce(done); finished = true }
      }
      prevRunning.current = liveIds
      if (finished) void refresh()
    } catch {
      /* 巡检失败静默重试，不打扰用户 */
    }
  }, [announce, refresh])

  // 登录态失效（token 过期或被撤销）→ 退回登录页
  useEffect(() => onUnauthorized(() => setUser(null)), [])

  // 随登录态重取：否则注册后再退出，登录页仍显示「服务端还没有任何账号」
  useEffect(() => {
    health().then((h) => { setSvc(h); setSvcDown(false) }).catch(() => setSvcDown(true))
  }, [user?.id])

  useEffect(() => {
    if (!user) return
    // 缓存的用户信息可能已过期，向服务端确认一次
    me().then(setUser).catch(() => { /* 401 已由 onUnauthorized 处理 */ })
    void refresh()
    void watchJobs()
  }, [user?.id, refresh, watchJobs])

  // 常驻巡检：有任务在跑时勤一点，闲时慢一点
  useEffect(() => {
    if (!user) return
    const t = window.setInterval(() => void watchJobs(), running.length ? 3000 : 10000)
    return () => clearInterval(t)
  }, [user, running.length, watchJobs])

  // 只在首次进入页面时自动接上后台任务；之后由用户点选，
  // 否则「放到后台」会被立刻重新附着，等于按钮失灵
  const bootstrapped = useRef(false)
  useEffect(() => {
    if (bootstrapped.current || !running.length) return
    bootstrapped.current = true
    if (!job && !doc) attach(running[0].id)
  }, [running, job, doc, attach])

  const logout = () => {
    clearSession()
    reset()
    setUser(null)
    setDoc(null)
    setDocId(null)
    setRuns([])
    setWorks([])
    setRunning([])
    setPage('convert')
  }

  const submit = (payload: ConvertRequest) => {
    primeNotifications()
    bootstrapped.current = true      // 自己提交的任务无需再自动附着
    void start(payload)
    void watchJobs()                 // 立刻让它出现在侧栏，随时可以放后台再点回来
  }

  const openRun = async (id: string) => {
    if (dirty && !confirm('当前修改尚未保存，确定切换？')) return
    setAlert(null)
    try {
      const record = await getHistory(id)
      reset()
      setDoc(record.result)
      setDocId(record.id)
      setDirty(false)
    } catch (e) {
      setAlert(`打开记录失败：${e instanceof Error ? e.message : String(e)}`)
    }
  }

  const removeRun = async (id: string) => {
    if (!confirm('删除这条历史记录？该操作不可撤销。')) return
    try {
      await deleteHistory(id)
      if (docId === id) newConversion()
      await refresh()
    } catch (e) {
      setAlert(`删除失败：${e instanceof Error ? e.message : String(e)}`)
    }
  }

  /** 回到表单：在跑的任务不受影响，仍在后台继续，并留在侧栏可随时点回来 */
  const newConversion = () => {
    reset()
    setDoc(null)
    setDocId(null)
    setDirty(false)
    setAlert(null)
    void watchJobs()
  }

  const openJob = (id: string) => {
    if (job?.id === id) return
    reset()
    setDoc(null)
    setDocId(null)
    setAlert(null)
    attach(id)
  }

  const save = async () => {
    if (!docId || !doc) return
    setSaving(true)
    setAlert(null)
    try {
      await saveHistory(docId, doc)
      setDirty(false)
      await refresh()
    } catch (e) {
      setAlert(`保存失败：${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setSaving(false)
    }
  }

  const openLocal = async (f: File) => {
    setAlert(null)
    try {
      const parsed = JSON.parse(await f.text())
      if (!parsed?.meta || !parsed?.episodes) throw new Error('不是分镜 IR：缺少 meta / episodes')
      reset()
      setDoc(parsed as Storyboard)
      setDocId(null)          // 本地文件不入库，只能下载
      setDirty(false)
    } catch (e) {
      setAlert(`读取失败：${e instanceof Error ? e.message : String(e)}`)
    }
  }

  if (!user) {
    return <LoginView firstRun={(svc?.users ?? 0) === 0} onDone={setUser} />
  }

  return (
    <div className="app">
      <header className="top">
        <div className="top__brand">
          <h1>小说 → 分镜 IR</h1>
          <nav className="top__nav">
            {([['convert', '转换'], ['library', '资产库']] as const).map(([p, name]) => (
              <button
                key={p}
                className={`top__navbtn${page === p ? ' is-on' : ''}`}
                onClick={() => setPage(p)}
              >
                {name}
              </button>
            ))}
          </nav>
        </div>
        <div className="top__right">
          <button className="btn btn--sm btn--ghost" onClick={() => fileRef.current?.click()}>
            打开本地 JSON
          </button>
          <input
            ref={fileRef}
            type="file"
            accept=".json,application/json"
            hidden
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) void openLocal(f)
              e.target.value = ''
            }}
          />
          {svcDown
            ? <span className="svc svc--down">服务未连通</span>
            : svc && (
                <span className="svc">
                  {svc.model}
                  {!svc.api_key_configured && <em> · 未配置密钥</em>}
                </span>
              )}
          <span className="who" title={`已登录：${user.username}`}>
            {user.username}
            <button className="who__out" onClick={logout}>退出</button>
          </span>
        </div>
      </header>

      {page === 'library' ? (
        <main className="main main--wide"><LibraryView /></main>
      ) : (
      <div className="shell">
        <HistoryPanel
          runs={runs}
          running={running}
          activeId={job?.id ?? docId}
          loading={runsLoading}
          onOpen={openRun}
          onOpenJob={openJob}
          onDelete={removeRun}
          onNew={newConversion}
        />

        <main className="main">
          {!job && !doc && (
            <ConvertForm disabled={submitting || svcDown} works={works} onSubmit={submit} />
          )}
          {error && <p className="alert">提交失败：{error}</p>}
          {alert && <p className="alert">{alert}</p>}
          {job && (
            <JobPanel job={job} onReset={newConversion} onBackground={newConversion} />
          )}
          {doc && (
            <StoryboardView
              doc={doc}
              canSave={docId !== null}
              dirty={dirty}
              saving={saving}
              onChange={(next) => { setDoc(next); setDirty(true) }}
              onSave={save}
            />
          )}
        </main>
      </div>
      )}
    </div>
  )
}
