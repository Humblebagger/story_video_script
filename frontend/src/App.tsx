import { useCallback, useEffect, useRef, useState } from 'react'
import {
  deleteHistory, getHistory, getJobPartial, health, listHistory, listJobs, listLibrary, me,
  saveHistory,
} from './api'
import { clearSession, getCachedUser, getToken, onUnauthorized } from './auth'
import type { User } from './auth'
import { ConvertForm } from './components/ConvertForm'
import { HistoryPanel } from './components/HistoryPanel'
import { JobPanel } from './components/JobPanel'
import { LibraryView } from './components/LibraryView'
import { LoginView } from './components/LoginView'
import { StoryboardView } from './components/StoryboardView'
import { VerificationPanel } from './components/VerificationPanel'
import { notify, primeNotifications } from './notify'
import type {
  ConvertRequest, Health, HistorySummary, Job, JobSummary, LibraryWork, Storyboard, VerificationReport,
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
  /** 服务端对当前产物的复验结果。保存一次刷新一次，不通过时它就是拦人的那块牌子 */
  const [verification, setVerification] = useState<VerificationReport | null>(null)
  /** 正在看的是整章跑完之前的部分产物（只读）。null = 看的是正式产物或什么都没开 */
  const [preview, setPreview] = useState<{ done: number; total: number } | null>(null)
  /** 预览请求在路上时任务可能已经跑完：只有仍想看这个任务的预览时才落地 */
  const previewFor = useRef<string | null>(null)
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
    if (done.status === 'failed') return      // 失败时已打开的预览保留：已通过的批次照样能看
    previewFor.current = null
    setPreview(null)
    setDoc(done.result)
    setDocId(done.id)
    setDirty(false)
  }, [refresh, announce])

  const { job, error, submitting, start, attach, reset } = useJob(onJobDone)

  /** 打开/刷新整章跑完之前的预览：已完成批次的合并结果，只读 */
  const loadPreview = useCallback(async (jobId: string) => {
    previewFor.current = jobId
    try {
      const p = await getJobPartial(jobId)
      if (previewFor.current !== jobId) return
      setDoc(p.doc)
      setDocId(null)
      setDirty(false)
      setPreview({ done: p.batches_done, total: p.batches })
    } catch (e) {
      if (previewFor.current === jobId) {
        setAlert(`预览加载失败：${e instanceof Error ? e.message : String(e)}`)
      }
    }
  }, [])

  // 预览开着时又跑完了一批：自动换成更新的预览
  useEffect(() => {
    if (preview && job && previewFor.current === job.id
        && (job.partial_batches ?? 0) > preview.done) {
      void loadPreview(job.id)
    }
  }, [preview, job, loadPreview])

  const closePreview = () => {
    previewFor.current = null
    setPreview(null)
  }

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
    setVerification(null)
    try {
      const record = await getHistory(id)
      reset()
      closePreview()
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
    closePreview()
    setDoc(null)
    setDocId(null)
    setDirty(false)
    setAlert(null)
    setVerification(null)
    void watchJobs()
  }

  const openJob = (id: string) => {
    if (job?.id === id) return
    reset()
    closePreview()
    setDoc(null)
    setDocId(null)
    setAlert(null)
    setVerification(null)
    attach(id)
  }

  const save = async () => {
    if (!docId || !doc) return
    setSaving(true)
    setAlert(null)
    setVerification(null)
    try {
      const res = await saveHistory(docId, doc)
      // 后端整份复验过了才返回。不看 status 就等于假装保存成功——
      // 用户会一路改到点渲染时才被 422 挡住，那时早忘了改过什么。
      setVerification(res.verification)
      if (res.status === 'draft_invalid') {
        setAlert('已保存，但这份分镜没通过服务端复验，暂时不能进渲染（详见下方报告）')
      }
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
    setVerification(null)
    try {
      const parsed = JSON.parse(await f.text())
      if (!parsed?.meta || !parsed?.episodes) throw new Error('不是分镜 IR：缺少 meta / episodes')
      reset()
      closePreview()
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
            <JobPanel
              job={job}
              onReset={newConversion}
              onBackground={newConversion}
              previewing={preview !== null}
              onPreview={() => void loadPreview(job.id)}
            />
          )}
          {verification && <VerificationPanel report={verification} doc={doc} />}
          {doc && (
            <StoryboardView
              doc={doc}
              canSave={docId !== null}
              preview={preview}
              runId={docId}
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
