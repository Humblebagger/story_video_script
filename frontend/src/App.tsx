import { motion } from 'motion/react'
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  adoptVersion, convertChapter, createChapter, createNovel, deleteChapter, deleteVersion,
  getChapter, getJobPartial, getNovel, getVersion, health, listJobs, listNovels, me,
  rerunDigest, saveVersion, updateChapter,
} from './api'
import { clearSession, getCachedUser, getToken, onUnauthorized } from './auth'
import type { User } from './auth'
import { AppShell } from './components/shell/AppShell'
import { CostMeter } from './components/shell/CostMeter'
import { ChapterCrumb, ProjectSwitcher } from './components/shell/ProjectSwitcher'
import { AdminView } from './components/admin/AdminView'
import { ChapterWorkflow } from './components/workflow/ChapterWorkflow'
import type { StepId } from './workflow'
import { JobPanel } from './components/JobPanel'
import { AuthDialog } from './components/auth/AuthDialog'
import type { AuthMode } from './components/auth/AuthDialog'
import { Landing } from './components/landing/Landing'
import { useI18n } from './i18n/core'
import { errText, errValue, formatMsg } from './i18n/serverMsg'
import type { MsgLike } from './i18n/serverMsg'
import type { MsgKey } from './i18n/core'
import { BRAND } from './brand'
import { Tour } from './components/common/Tour'
import { useConfirm } from './components/common/ConfirmDialog'
import type { NewNovel } from './components/NewNovelComposer'
import { ShelfHome } from './components/ShelfHome'
import { NovelPage } from './components/NovelPage'
import { NovelSidebar } from './components/NovelSidebar'
import { ActivityPanel } from './components/shell/ActivityPanel'
import { AssistantPanel } from './components/assistant/AssistantPanel'
import { onTask } from './lib/assistantBridge'
import { keepOnlyAssistant } from './lib/assistantSession'
import type { DoneJob } from './components/shell/ActivityPanel'
import { ProjectNav } from './components/shell/ProjectNav'
import { readLastChapter, writeLastChapter } from './lastChapter'
import type { Section } from './section'
import { useStyleImage } from './useStyleImage'
import { StoryboardView } from './components/StoryboardView'
import type { Tab } from './components/StoryboardView'
import { VerificationPanel } from './components/VerificationPanel'
import { toast } from 'sonner'
import { useBlocker, useLocation, useNavigate } from 'react-router'
import { ApiError } from './api'
import { NotFound } from './components/NotFound'
import { Skeleton } from './components/ui/skeleton'
import { chapterPath, isCanvasStep, novelPath, parseLocation, passState } from './paths'
import type { NavState } from './paths'
import { notice } from './lib/notice'
import { UnsavedBar } from './components/workflow/UnsavedBar'
import { notify, primeNotifications } from './notify'
import type {
  Chapter, Health, Job, JobSummary, NarrationMode, Novel, NovelSummary, Storyboard,
  VerificationReport,
} from './types'
import { useChapterFlow } from './useChapterFlow'
import { useNovelSummary } from './useNovelSummary'
import { ART_STYLES } from './presets'
import { useJob } from './useJob'
import { DUR, EASE_OUT } from './motion'

const RUNNING = ['queued', 'running']
const msg = (e: unknown) => errText(e)

type AlertKey = 'app.err.preview' | 'app.err.version' | 'app.err.chapter' | 'app.err.createNovel' | 'app.err.novel' | 'app.versionFailed' | 'app.versionEmpty' | 'app.savedInvalid'
type AlertState = { key?: AlertKey; err?: MsgLike }

export default function App() {
  const { t, locale } = useI18n()
  const [ask, confirmUi] = useConfirm()
  const location = useLocation()
  const navigate = useNavigate()
  const { loc, fix } = parseLocation(location.pathname, location.search)
  const navState = (location.state ?? null) as NavState | null
  /** 最新地址与 state：异步回调里读，不进依赖 */
  const hereRef = useRef('')
  hereRef.current = location.pathname + location.search
  const navStateRef = useRef<NavState | null>(null)
  navStateRef.current = navState
  /** 导航统一走这里（§5.4、§8）：
   *  - 目标等于当前地址时不导航，返回 false，调用方自己执行同址动作；
   *  - replace 透传当前 state（去掉一次性的键）；
   *  - force = 程序性跳转，离开拦截放行。 */
  const go = useCallback((to: string, o: { replace?: boolean; state?: NavState; force?: boolean } = {}) => {
    if (to === hereRef.current) return false
    const base = o.replace ? passState(navStateRef.current) : {}
    navigate(to, { replace: !!o.replace, state: { ...base, ...o.state, ...(o.force ? { force: true } : {}) } })
    return true
  }, [navigate])
  /** 当前地址指向的小说（URL 是唯一真相） */
  const nid = loc.kind === 'novel' || loc.kind === 'chapter' ? loc.nid : null
  const cid = loc.kind === 'chapter' ? loc.cid : null
  const adminOpen = loc.kind === 'admin'
  const section: Section = loc.kind === 'novel' && loc.section ? loc.section : 'overview'
  const [user, setUser] = useState<User | null>(() => (getToken() ? getCachedUser() : null))
  /** 登录成功后、首页淡出期间暂存的用户；淡出完才真正进应用 */
  const [entering, setEntering] = useState<User | null>(null)
  /** 没登录时的登录注册对话框；expired 为登录失效后自动打开时的提示 */
  const [auth, setAuth] = useState<{ open: boolean; mode: AuthMode; expired: boolean }>(
    { open: false, mode: 'login', expired: false })
  const [svc, setSvc] = useState<Health | null>(null)
  const [svcDown, setSvcDown] = useState(false)

  const [novels, setNovels] = useState<NovelSummary[]>([])
  const [novelsLoading, setNovelsLoading] = useState(true)
  const [running, setRunning] = useState<JobSummary[]>([])
  /** 打开的小说（总会话）与章节（二级会话）；都为空时主区是新建小说 */
  const [novel, setNovel] = useState<Novel | null>(null)
  const [chapter, setChapter] = useState<Chapter | null>(null)
  const [busy, setBusy] = useState(false)
  const [importing, setImporting] = useState(false)
  /** 右侧动态面板开关；recentDone 为最近完成的任务（只在内存，最多 20 条）；activityDot 为面板关着时的新完成提示 */
  const [activityOpen, setActivityOpen] = useState(false)
  const [recentDone, setRecentDone] = useState<DoneJob[]>([])
  const [activityDot, setActivityDot] = useState(false)
  const [activityTab, setActivityTab] = useState<'activity' | 'assistant'>('activity')
  const activityOpenRef = useRef(false)
  activityOpenRef.current = activityOpen

  const [doc, setDoc] = useState<Storyboard | null>(null)
  /** doc 属于哪个版本；本地打开的 JSON 与分批预览都没有 */
  const [docVid, setDocVid] = useState<string | null>(null)
  const [dirty, setDirty] = useState(false)
  /** 撤销的基准：上一次从服务端拿到（或存下）的那份 doc；编辑不改它 */
  const savedDoc = useRef<Storyboard | null>(null)
  const [saving, setSaving] = useState(false)
  /** 页面提示条：存文案键与错误值，渲染时按当前语言拼（切换语言后跟着变） */
  const [alert, setAlert] = useState<AlertState | null>(null)
  const alertText = (a: AlertState) => (a.key ? t(a.key, { msg: formatMsg(a.err, locale) }) : formatMsg(a.err, locale))
  /** 服务端对当前产物的复验结果。保存一次刷新一次，不通过时它就是拦人的那块牌子 */
  const [verification, setVerification] = useState<VerificationReport | null>(null)
  /** 正在看的是整章跑完之前的部分产物（只读）。null = 看的是正式产物或什么都没开 */
  const [preview, setPreview] = useState<{ done: number; total: number } | null>(null)
  /** 预览请求在路上时任务可能已经跑完：只有仍想看这个任务的预览时才落地 */
  const previewFor = useRef<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  /** 异步回来时用户可能已经切走：只认仍然打开着的那一章 */
  const openChapterId = useRef<string | null>(null)
  openChapterId.current = cid
  /** 异步回来时 URL 可能已经换了小说：只认地址里的那一本（§5.3） */
  const openNovelId = useRef<string | null>(null)
  openNovelId.current = nid
  /** 会话代：退出、登录失效、换账号时加一；旧账号迟到的响应一律丢弃 */
  const epoch = useRef(0)
  const epochUid = useRef(user?.id)
  if (epochUid.current !== user?.id) { epochUid.current = user?.id; epoch.current += 1 }
  /** 工作代：(账号, 小说, 章节) 任何一个变了就加一；所有异步写回都核对它 */
  const workGen = useRef(0)
  const workKey = useRef('')
  const wk = `${user?.id ?? ''}|${nid ?? ''}|${cid ?? ''}`
  if (workKey.current !== wk) { workKey.current = wk; workGen.current += 1 }
  /** 打开本地 JSON：先回到 /，到了再摆出来（§5.5） */
  const pendingLocal = useRef<Storyboard | null>(null)
  const chapterRef = useRef<Chapter | null>(null)
  chapterRef.current = chapter
  /** 章节级只读出片状态（步骤条与主按钮用）；画布关闭、保存后重读 */
  const flow = useChapterFlow(novel && chapter && docVid ? { nid: novel.id, cid: chapter.id, vid: docVid } : null)
  /** 费用表与左栏汇总的刷新键：任务结束、出片或合成刷新、采用、删版本时加一 */
  const [summaryKey, setSummaryKey] = useState(0)
  const bumpSummary = useCallback(() => setSummaryKey((k) => k + 1), [])
  const summary = useNovelSummary(novel?.id, summaryKey)
  const styleUrl = useStyleImage(novel?.id ?? '', novel?.style_image?.hash)
  const flowReload = flow.reload
  const reloadFlow = useCallback(async () => { await flowReload(); bumpSummary() }, [flowReload, bumpSummary])
  /** 章节原文框里有没保存的改动（由章节工作流报上来）；和分镜的 dirty 一起管离开提醒 */
  const [textDirty, setTextDirty] = useState(false)
  /** 正附着着的任务（announce 用来判断「用户正看着它跑完」） */
  const attachedJob = useRef<string | null>(null)
  const jobWork = useRef(-1)
  const attachedFor = useRef<string | null>(null)

  const refreshNovels = useCallback(async () => {
    const ep = epoch.current
    try {
      const r = await listNovels()
      if (epoch.current === ep) setNovels(r.novels)
    } catch {
      /* 服务未连通时由 svcDown 统一提示，这里不再重复报错 */
    } finally {
      if (epoch.current === ep) setNovelsLoading(false)
    }
  }, [])

  /** 重新取打开着的小说与章节（转换完成、采用、改记忆之后） */
  const reloadOpen = useCallback(async (nid?: string, cid?: string | null) => {
    const ep = epoch.current
    const here = () => epoch.current === ep && openNovelId.current === nid
    try {
      if (nid) { const n = await getNovel(nid); if (here()) setNovel(n) }
      if (nid && cid) {
        const c = await getChapter(nid, cid)
        if (here() && openChapterId.current === cid) setChapter(c)
      }
    } catch (e) {
      if (here() && (!cid || openChapterId.current === cid)) setAlert({ err: errValue(e) })
    }
  }, [])

  /** 完成播报去重：附着轮询与后台巡检可能同时发现同一个任务结束 */
  const announced = useRef<Set<string>>(new Set())
  /** 提示里「查看」要打开那一章；用 ref 拿最新的打开函数，announce 的依赖就不用跟着变 */
  const openFromToast = useRef<(j: { id: string; status: string; novel_id?: string | null;
                                       chapter_id?: string | null }) => void>(() => {})
  const announce = useCallback((j: { id: string; status: string;
                                     work_title?: string | null;
                                     chapter?: string | null;
                                     novel_id?: string | null;
                                     chapter_id?: string | null }) => {
    if (announced.current.has(j.id)) return
    announced.current.add(j.id)
    const who = `${j.work_title ?? t('flow.toast.fallbackWho')} ${j.chapter ?? ''}`.trim()
    const view = { label: t('flow.view'), onClick: () => openFromToast.current(j) }
    if (j.status === 'failed') {
      notify(t('app.notify.failed'), t('app.notify.failedBody', { who }))
      toast.error(t('flow.toast.failed'), { description: who, action: view })
    } else {
      const title = t(j.status === 'completed_with_warnings' ? 'app.notify.doneWarn' : 'app.notify.done')
      notify(title, t('app.notify.doneBody', { who }))
      // 用户正在本章看着它跑完：产物会直接摆出来，章节工作流另有「分镜已生成」，这里不再弹一条
      const watching = !!j.chapter_id && j.chapter_id === openChapterId.current && attachedJob.current === j.id
      if (!watching) {
        toast.success(t(j.status === 'completed_with_warnings' ? 'flow.toast.doneWarn' : 'flow.toast.done'),
                      { description: who, action: view })
      }
    }
  }, [t])

  const novelRef = useRef<Novel | null>(null)
  novelRef.current = novel

  // 任务跑完且用户正看着它：直接把产物摆出来
  const onJobDone = useCallback((done: Job) => {
    // 这个任务是在哪个工作代附着的：地址已经换了就只做全局收尾，不把产物写进现在的章节
    const mine = jobWork.current === workGen.current && attachedFor.current === done.id
    void refreshNovels()
    bumpSummary()
    announce(done)
    // 巡检要过几秒才发现它结束了；在那之前章节页不能还显示「转换中」
    setRunning((list) => list.filter((j) => j.id !== done.id))
    const nid = novelRef.current?.id
    if (nid) void reloadOpen(nid, openChapterId.current)
    if (!mine) return
    if (done.status === 'failed') return      // 失败时已打开的预览保留：已通过的批次照样能看
    previewFor.current = null
    setPreview(null)
    setDoc(done.result)
    savedDoc.current = done.result
    setDocVid(done.id)
    setDirty(false)
  }, [refreshNovels, reloadOpen, announce, bumpSummary])

  const { job, error, submitting, start, attach: attachRaw, reset } = useJob(onJobDone)
  attachedJob.current = job?.id ?? null
  /** 附着任务时记下当时的工作代与任务号（onJobDone 回头核对） */
  const attach = useCallback((jobId: string) => {
    jobWork.current = workGen.current; attachedFor.current = jobId
    attachRaw(jobId)
  }, [attachRaw])

  /** 打开/刷新整章跑完之前的预览：已完成批次的合并结果，只读 */
  const loadPreview = useCallback(async (jobId: string) => {
    previewFor.current = jobId
    try {
      const p = await getJobPartial(jobId)
      if (previewFor.current !== jobId) return
      setDoc(p.doc)
      savedDoc.current = p.doc
      setDocVid(null)
      setDirty(false)
      setPreview({ done: p.batches_done, total: p.batches })
    } catch (e) {
      if (previewFor.current === jobId) setAlert({ key: 'app.err.preview', err: errValue(e) })
    }
  }, [])

  // 预览开着时又跑完了一批：自动换成更新的预览
  useEffect(() => {
    if (preview && job && previewFor.current === job.id
        && (job.partial_batches ?? 0) > preview.done) {
      void loadPreview(job.id)
    }
  }, [preview, job, loadPreview])

  /** 清掉主区的产物与任务面板（不影响后台在跑的转换） */
  const clearWork = useCallback(() => {
    reset()
    previewFor.current = null
    setPreview(null)
    setDoc(null)
    savedDoc.current = null
    setDocVid(null)
    setDirty(false)
    setAlert(null)
    setVerification(null)
  }, [reset])

  /** 任务列表巡检：独立于「是否正在看某个任务」。
   *  放到后台的任务靠它留在侧栏里可点回去，跑完也靠它播报——
   *  否则一旦松开附着，任务就既看不见也回不去了。 */
  const prevRunning = useRef<Set<string>>(new Set())
  const watchJobs = useCallback(async () => {
    const ep = epoch.current
    try {
      const { jobs } = await listJobs()
      if (epoch.current !== ep) return
      const live = jobs.filter((x) => RUNNING.includes(x.status))
      setRunning(live)
      const liveIds = new Set(live.map((x) => x.id))
      // 上一轮还在跑、这一轮不在了 → 刚刚结束
      let finished = false
      for (const id of prevRunning.current) {
        if (liveIds.has(id)) continue
        const done = jobs.find((x) => x.id === id)
        if (done) {
          announce(done); finished = true
          const { id: did, status, work_title, chapter: chapterName, novel_id, chapter_id } = done
          setRecentDone((r) => [{ id: did, status, work_title, chapter: chapterName, novel_id, chapter_id },
            ...r.filter((x) => x.id !== did)].slice(0, 20))
          if (!activityOpenRef.current) setActivityDot(true)
        }
      }
      prevRunning.current = liveIds
      if (finished) {
        void refreshNovels()
        bumpSummary()
        const nid = novelRef.current?.id
        if (nid) void reloadOpen(nid, openChapterId.current)
      }
    } catch {
      /* 巡检失败静默重试，不打扰用户 */
    }
  }, [announce, refreshNovels, reloadOpen, bumpSummary])

  // 登录态失效（token 过期或被撤销）→ 回首页并打开登录框
  // 监听只订阅一次，所以通过 ref 拿到最新的重置函数；和退出共用，保证换账号不残留上一个人的小说与产物
  const resetRef = useRef<() => void>(() => {})
  useEffect(() => onUnauthorized(() => {
    resetRef.current()
    setEntering(null)
    setAuth({ open: true, mode: 'login', expired: true })
  }), [])

  // 全新部署（服务端还没有任何账号）：首页直接打开注册
  const firstRun = !!svc && (svc.first_run ?? (svc.users ?? 0) === 0)
  useEffect(() => {
    if (!user && firstRun) setAuth((a) => (a.open ? a : { open: true, mode: 'register', expired: false }))
  }, [user, firstRun])

  // 非法值、缺省值写进了地址：规范化（§3），带 force 不被离开拦截挡住
  useEffect(() => {
    if (fix) navigate(fix, { replace: true, state: { ...passState(navStateRef.current), force: true } })
  }, [fix, navigate])

  /** 加载 effect 里要用的最新函数：放进 ref，effect 只按 (user, nid, cid) 重跑 */
  // t 也从这里取：语言切换会换 t 的引用，不能让加载 effect 因此重跑（重跑会清空主区）
  const fns = useRef({ clearWork: () => {}, t,
                       attach: (id: string) => { void id },
                       openVersion: async (n: string, c: string, v: string) => { void n; void c; void v } })
  fns.current.t = t
  fns.current.clearWork = clearWork
  const userId = user?.id
  /** 已由 me() 确认过角色的用户 id；缓存的角色可能过期，/admin 的守卫要等它 */
  const [roleOf, setRoleOf] = useState<string | null>(null)
  const runningRef = useRef<JobSummary[]>([])
  runningRef.current = running
  // 按地址加载小说与章节（§5.1）：(nid, cid) 变了先清掉主区产物，迟到的响应一律丢弃（§5.3）
  useEffect(() => {
    if (!userId) return
    const f = fns.current
    f.clearWork()
    if (!nid) {
      setNovel(null); setChapter(null)
      const local = pendingLocal.current
      if (local) { pendingLocal.current = null; setDoc(local); savedDoc.current = local }
      return
    }
    if (novelRef.current?.id !== nid) setNovel(null)
    setChapter(null)
    let live = true
    const ep = epoch.current
    const st = navStateRef.current
    void (async () => {
      const [nr, cr] = await Promise.allSettled([getNovel(nid), cid ? getChapter(nid, cid) : Promise.resolve(null)])
      if (!live || epoch.current !== ep) return
      const gone = (e: unknown) => e instanceof ApiError && (e.status === 404 || e.status === 403)
      if (nr.status === 'rejected') {
        if (gone(nr.reason)) { toast.error(f.t('route.err.novelGone')); navigate('/', { replace: true, state: { force: true } }) }
        else setAlert({ key: 'app.err.novel', err: errValue(nr.reason) })
        return
      }
      setNovel(nr.value)
      if (!cid) return
      if (cr.status === 'rejected') {
        if (gone(cr.reason)) {
          toast.error(f.t('route.err.chapterGone'))
          navigate(novelPath(nid, 'chapters'), { replace: true, state: { force: true } })
        } else setAlert({ key: 'app.err.chapter', err: errValue(cr.reason) })
        return
      }
      const c = cr.value!
      writeLastChapter(nid, c.id)
      setChapter(c)
      const liveJob = st?.vid ? undefined : st?.jobId ?? runningRef.current.find((j) => j.chapter_id === c.id)?.id
      if (liveJob) f.attach(liveJob)
      else {
        const target = st?.vid ?? c.adopted_version ?? c.versions[0]?.id
        if (target) void f.openVersion(nid, c.id, target)
      }
      // 一次性参数用完就清掉：刷新、后退时不会再接一次已结束的任务或打开已删的版本（§5.4）
      if (st?.vid || st?.jobId) navigate(hereRef.current, { replace: true, state: passState(st) })
    })()
    return () => { live = false }
  }, [userId, nid, cid, navigate])

  // /novels/:nid 没有分区：小说加载完 replace 到默认分区（§3）
  const locNid = loc.kind === 'novel' ? loc.nid : null
  const locSection = loc.kind === 'novel' ? loc.section : null
  useEffect(() => {
    if (!locNid || locSection || novel?.id !== locNid) return
    const sec: Section = novel.memory.lifecycle.some((e) => e.status === 'proposed') ? 'memory' : 'overview'
    navigate(novelPath(locNid, sec), { replace: true, state: passState(navStateRef.current) })
  }, [locNid, locSection, novel, navigate])

  // /admin 只给管理员（§6）；缓存用户的角色以 me() 回来的为准，所以依赖 role
  const isAdminUser = user?.role === 'admin'
  const roleConfirmed = !!user && roleOf === user.id
  useEffect(() => {
    if (!user || !roleConfirmed || loc.kind !== 'admin' || isAdminUser) return
    toast.error(fns.current.t('route.err.adminOnly'))
    navigate('/', { replace: true, state: { force: true } })
  }, [user, roleConfirmed, loc.kind, isAdminUser, navigate])

  // 未登录打开非首页的地址：自动弹一次登录框（每个地址只弹一次，用户关掉后不再弹）（§6）
  const prompted = useRef(new Set<string>())
  useEffect(() => {
    if (user || entering || loc.kind === 'home' || prompted.current.has(location.pathname)) return
    prompted.current.add(location.pathname)
    setAuth((a) => (a.open ? a : { open: true, mode: firstRun ? 'register' : 'login', expired: false }))
  }, [user, entering, loc.kind, location.pathname, firstRun])

  // 随登录态重取：否则注册后再退出，登录页仍显示「服务端还没有任何账号」
  useEffect(() => {
    health().then((h) => { setSvc(h); setSvcDown(false) }).catch(() => setSvcDown(true))
  }, [user?.id])

  // 助手：换到别的小说（或回书架）时中断并丢掉上一部的对话；同一部小说里关面板、切页签都不中断
  useEffect(() => { keepOnlyAssistant(novel?.id ?? null) }, [novel?.id])

  useEffect(() => {
    if (!user) return
    // 缓存的用户信息可能已过期，向服务端确认一次
    const ep = epoch.current
    me().then((u) => {
      if (epoch.current !== ep) return
      setUser(u); setRoleOf(u.id)
    }).catch(() => { /* 401 已由 onUnauthorized 处理 */ })
    void refreshNovels()
    void watchJobs()
  }, [user?.id, refreshNovels, watchJobs])

  // 常驻巡检：有任务在跑时勤一点，闲时慢一点
  useEffect(() => {
    if (!user) return
    const t = window.setInterval(() => void watchJobs(), running.length ? 3000 : 10000)
    return () => clearInterval(t)
  }, [user, running.length, watchJobs])

  // 章后整理在后台跑（一次小调用）：跑着时盯一下，完了刷新小说页的待确认提议
  useEffect(() => {
    if (!novel || !chapter || chapter.digest?.status !== 'running') return
    const t = window.setTimeout(() => void reloadOpen(novel.id, chapter.id), 2000)
    return () => clearTimeout(t)
  }, [novel, chapter, reloadOpen])

  const confirmLeave = async () => !(dirty || textDirty) || ask({
    title: t('confirm.leave.title'), body: t('confirm.leave.body'), action: t('confirm.leave.action'), danger: true })

  /** 正在读某一版（画布地址要等它读完才能判断挂不挂得上） */
  const [versionLoading, setVersionLoading] = useState(false)
  /** 只有最近一次读版本的请求拥有 versionLoading；换章时一并清掉（新章可能根本没有版本要读） */
  const versionSeq = useRef(0)
  useEffect(() => { versionSeq.current += 1; setVersionLoading(false) }, [userId, nid, cid])
  const openVersion = useCallback(async (nid: string, cid: string, vid: string) => {
    const seq = ++versionSeq.current
    const ep = epoch.current
    /** 这次请求是否仍是最近一次、且地址还指着它要的那一章 */
    const current = () => versionSeq.current === seq && epoch.current === ep
      && openNovelId.current === nid && openChapterId.current === cid
    setVersionLoading(true)
    reset()
    previewFor.current = null
    setPreview(null)
    setAlert(null)
    setVerification(null)
    try {
      const v = await getVersion(nid, cid, vid)
      if (!current()) return
      setDoc(v.result)
      savedDoc.current = v.result
      setDocVid(v.result ? v.id : null)
      setDirty(false)
      // 这一版的复验没过（改坏的草稿）：把检查结果摆出来，「去修复」才有地方可去
      if (v.result && (v.status === 'draft_invalid' || v.verification?.status === 'failed')) {
        setVerification(v.verification ?? null)
      }
      if (!v.result) {
        setVerification(v.verification ?? null)
        setAlert(v.status === 'failed'
          ? { key: 'app.versionFailed', err: v.error_msg ?? (v.error ?? '').split('\n')[0] }
          : { key: 'app.versionEmpty' })
      }
    } catch (e) {
      if (current()) setAlert({ key: 'app.err.version', err: errValue(e) })
    } finally {
      if (versionSeq.current === seq) setVersionLoading(false)
    }
  }, [reset])
  fns.current.attach = attach
  fns.current.openVersion = openVersion

  // 助手发起了操作或改了内容：转换让任务巡检立刻刷新；改内容重读小说，正在看的这一版没有未保存修改就重读
  // （有就只提示，免得冲掉用户的修改）；各种操作都让小说概览重算
  useEffect(() => onTask((task) => {
    if (task.kind === 'job') void watchJobs()
    if (task.kind === 'edit' && novel) {
      void reloadOpen(novel.id, chapter?.id ?? null)
      if (task.chapter_id && task.version_id && chapter?.id === task.chapter_id && docVid === task.version_id) {
        if (dirty) notice.err(t('assistant.editedDirty'))
        else void openVersion(novel.id, task.chapter_id, task.version_id)
      }
    }
    bumpSummary()
  }), [watchJobs, bumpSummary, novel, chapter?.id, docVid, dirty, reloadOpen, openVersion, t])

  /** 打开章节（§5.4）：跨地址就导航，vid / jobId 作一次性 state；目标就是地址里这一章时不导航，直接执行动作 */
  const openChapter = async (cidT: string, nidT = nid ?? undefined, jobId?: string, vid?: string,
                             o: { force?: boolean } = {}): Promise<boolean> => {
    if (!nidT) return false
    if (nidT === nid && cidT === cid) {
      // 同址再打开：换版本、接任务都会丢掉未保存的修改，所以照样确认（§7 保留项）
      if (vid) {
        if (!(await confirmLeave())) return false
        void openVersion(nidT, cidT, vid)
        return true
      }
      const live = jobId ?? running.find((j) => j.chapter_id === cidT)?.id
      if (live) {
        // 已经挂着这个任务就保持任务面板
        if (job?.id !== live) {
          if (!(await confirmLeave())) return false
          clearWork(); attach(live)
        }
        return true
      }
      // 没有要接的任务：重置，重新摆出采用版（没有就最新一版），和进章节时一样
      if (!(await confirmLeave())) return false
      clearWork()
      const ep = epoch.current
      try {
        const c = await getChapter(nidT, cidT)
        if (openChapterId.current !== cidT || openNovelId.current !== nidT || epoch.current !== ep) return false
        setChapter(c)
        const target = c.adopted_version ?? c.versions[0]?.id
        if (target) void openVersion(nidT, cidT, target)
      } catch (e) {
        setAlert({ key: 'app.err.chapter', err: errValue(e) })
        return false
      }
      return true
    }
    go(chapterPath(nidT, cidT), { state: { ...(jobId ? { jobId } : {}), ...(vid ? { vid } : {}) }, force: o.force })
    return true
  }

  /** ChapterWorkflow 报上来的实际步骤（拼页签、画布地址用） */
  const viewRef = useRef<StepId | null>(null)
  const onViewChange = useCallback((v: StepId) => { viewRef.current = v }, [])
  const urlTab = loc.kind === 'chapter' ? loc.tab : null
  const stepNav = useCallback((s: StepId, how: 'push' | 'replace') => {
    if (!nid || !cid) return
    // 在 ③④⑤ 之间切换时页签保留（分镜视图不重新挂载）；其它步骤不带页签
    go(chapterPath(nid, cid, { step: s, tab: urlTab }), { replace: how === 'replace' })
  }, [nid, cid, go, urlTab])

  /** 画布挂在哪一步：地址步骤是 ③④⑤ 就用它；否则用工作流实际步骤；都不是就 ⑤（§4.2 openFilm） */
  const boardStep = (): StepId => {
    if (loc.kind === 'chapter' && isCanvasStep(loc.step)) return loc.step
    return isCanvasStep(viewRef.current) ? viewRef.current : 'compose'
  }
  const openCanvas = (step: StepId = boardStep(), panel?: 'film') => {
    if (!nid || !cid) return
    go(chapterPath(nid, cid, { step, tab: urlTab, canvas: true }), { state: { fromChapter: true, ...(panel ? { panel } : {}) } })
  }
  const closeCanvas = () => {
    if (!nid || !cid || loc.kind !== 'chapter') return
    // 从章节里打开的：后退一步，视图和页签的 replace 不会把它弄丢；否则 replace 回原步骤与页签（§8）
    if (navState?.fromChapter && location.key !== 'default') navigate(-1)
    else go(chapterPath(nid, cid, { step: loc.step, tab: loc.tab }), { replace: true })
  }
  // 画布地址但画布挂不上（没有版本、分镜为空、在看分批预览）：等加载落定后规范化回章节地址（§3）
  const canvasStranded = loc.kind === 'chapter' && loc.canvas && chapter?.id === cid
    && !versionLoading && !job && (!doc || !docVid || !!preview)
  useEffect(() => {
    if (canvasStranded && nid && cid) navigate(chapterPath(nid, cid), { replace: true, state: { force: true } })
  }, [canvasStranded, nid, cid, navigate])

  const openNovel = async (target: string) => {
    // 同一本：地址相同时不导航，默认分区 effect 也不会动，所以直接回到它的默认分区
    if (!go(novelPath(target)) && novel) {
      go(novelPath(target, novel.memory.lifecycle.some((e) => e.status === 'proposed') ? 'memory' : 'overview'))
    }
  }

  const openJob = (j: JobSummary) => {
    if (job?.id === j.id) return
    if (j.novel_id && j.chapter_id) void openChapter(j.chapter_id, j.novel_id, j.id)
    else { clearWork(); attach(j.id) }
  }

  // 成功的：直接打开它产出的那一版（版本号 = 任务号），不留一个跑完的任务面板；失败的接上任务面板看原因
  openFromToast.current = (j) => {
    const { novel_id: n, chapter_id: c } = j
    if (n && c) void openChapter(c, n, j.status === 'failed' ? j.id : undefined, j.status === 'failed' ? undefined : j.id)
    else openJob(j as unknown as JobSummary)
  }

  /** 左栏点分区：在章节里就先离开章节（未保存走 confirmLeave），回到小说层的那个分区 */
  const gotoSection = async (sec: Section) => {
    if (!nid) return
    go(novelPath(nid, sec))
  }

  const undo = () => {
    if (savedDoc.current) { setDoc(savedDoc.current); setDirty(false) }
  }

  // 有未保存的修改（分镜或原文）时，关页面前让浏览器提醒一下
  const anyDirty = dirty || textDirty
  useEffect(() => {
    if (!anyDirty) return
    const h = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = '' }
    window.addEventListener('beforeunload', h)
    return () => window.removeEventListener('beforeunload', h)
  }, [anyDirty])

  // 有未保存修改时离开当前章节：统一在这里确认（§7）。判定读 ref，不读闭包；带 force 的程序性跳转放行
  const dirtyRef = useRef(false)
  dirtyRef.current = anyDirty
  const chapterKey = (pathname: string) => {
    const l = parseLocation(pathname).loc
    return l.kind === 'chapter' ? `${l.nid}/${l.cid}` : null
  }
  const blocker = useBlocker(({ currentLocation, nextLocation, historyAction }) => {
    // force 只对这一次程序性跳转有效；后退/前进（POP）回到带 force 的旧条目仍要拦
    if (!dirtyRef.current || (historyAction !== 'POP' && (nextLocation.state as NavState | null)?.force)) return false
    const a = chapterKey(currentLocation.pathname)
    return !(a !== null && a === chapterKey(nextLocation.pathname))
  })
  useEffect(() => {
    if (blocker.state !== 'blocked') return
    void ask({ title: t('confirm.leave.title'), body: t('confirm.leave.body'), action: t('confirm.leave.action'), danger: true })
      .then((ok) => { if (ok) { clearWork(); blocker.proceed?.() } else blocker.reset?.() })
  }, [blocker, ask, t, clearWork])

  // 页面标题跟着位置走（§10）；加载中不显示上一本小说的名字
  const sectionKey = loc.kind === 'novel' ? loc.section : null
  const canvasKey = loc.kind === 'chapter' && loc.canvas
  useEffect(() => {
    const brand = BRAND.id
    const novelName = novel && novel.id === nid ? novel.title : null
    const chapterName = chapter && chapter.id === cid ? chapter.title : null
    const join = (head: string, tail: string | null) => (tail ? `${head} · ${tail} — ${brand}` : `${head} — ${brand}`)
    let title = BRAND.title
    if (loc.kind === 'admin') title = `${t('route.title.admin')} — ${brand}`
    else if (loc.kind === 'notFound') title = `${t('route.title.notFound')} — ${brand}`
    else if (loc.kind === 'novel') title = join(t(`nav.${sectionKey ?? 'overview'}` as MsgKey), novelName)
    else if (loc.kind === 'chapter') {
      title = canvasKey ? join(t('route.title.canvas'), chapterName)
        : chapterName ? join(chapterName, novelName) : brand
    }
    document.title = title
  }, [loc.kind, nid, cid, sectionKey, canvasKey, novel, chapter, t])

  const newNovel = async () => {
    setActivityTab('activity')
    // 已经在 / 上（本地 JSON、无章节的任务面板）：同址不导航，直接清掉；不改地址就没有 blocker，自己确认
    if (!go('/')) { if (!(await confirmLeave())) return; clearWork(); setNovel(null); setChapter(null) }
  }

  const enterAdmin = () => {
    go('/admin')
  }
  const leaveAdmin = () => {
    if (location.key !== 'default') navigate(-1)
    else navigate('/', { replace: true })
  }

  const submitNovel = async (n: NewNovel) => {
    setBusy(true)
    setAlert(null)
    try {
      const created = await createNovel(n.title, n.params)
      const chapters = await createChapters(created.id, n.chapters)
      await refreshNovels()
      if (chapters.length) await openChapter(chapters[0].id, created.id)
      else go(novelPath(created.id, 'overview'))
    } catch (e) {
      setAlert({ key: 'app.err.createNovel', err: errValue(e) })
    } finally {
      setBusy(false)
    }
  }

  /** 逐章新建（顺序创建，章节编号按先后） */
  const createChapters = async (nid: string, list: { title: string; text: string }[]) => {
    const made = []
    for (const c of list) made.push(await createChapter(nid, c.title, c.text))
    return made
  }

  /** 导入整本：在当前小说里按已拆好的章节逐章新建，停留在「原文与章节」页 */
  const importChapters = async (list: { title: string; text: string }[]) => {
    if (!novel || !list.length) return
    if (importing) return
    const nid = novel.id
    const ep = epoch.current
    let made = 0
    setImporting(true)
    try {
      for (const c of list) { await createChapter(nid, c.title, c.text); made++ }
      notice.ok(t('app.imported', { n: made }))
    } catch (e) {
      const m = msg(e)
      notice.err(made
        ? t('app.importPartial', { n: made, total: list.length, msg: m })
        : t('app.err.createChapter', { msg: m }))
    } finally {
      // 已建出的章节无论成败都要显示出来，否则重试会重复建
      if (made) {
        try { void refreshNovels(); const n = await getNovel(nid); if (openNovelId.current === nid && epoch.current === ep) setNovel(n); bumpSummary() } catch { /* 刷新失败不覆盖上面的提示 */ }
      }
      setImporting(false)
    }
  }

  const newChapter = async () => {
    if (!novel || !(await confirmLeave())) return
    try {
      const c = await createChapter(novel.id, t('app.chapterDefault', { n: novel.chapters.length + 1 }))
      await refreshNovels()
      await openChapter(c.id, novel.id, undefined, undefined, { force: true })
      bumpSummary()
    } catch (e) {
      notice.err(t('app.err.createChapter', { msg: msg(e) }))
    }
  }

  /** keepDoc：从画布发起时画布不关，旧版本留在画布上，跑完由 onJobDone 换成新版本 */
  const convert = (opts: { narration_mode?: NarrationMode; strict: boolean }, keepDoc = false) => {
    if (!novel || !chapter) return
    primeNotifications()
    if (keepDoc) { reset(); setAlert(null); setVerification(null) } else clearWork()
    const { strict, ...overrides } = opts
    const [nid, cid] = [novel.id, chapter.id]
    const gen = workGen.current
    void start(() => convertChapter(nid, cid, { overrides, strict }).then((r) => {
      jobWork.current = gen; attachedFor.current = r.job_id
      return r
    }),
               { work_title: novel.title, chapter: chapter.title })
      .then(() => reloadOpen(nid, cid))
    void watchJobs()                 // 立刻让它出现在侧栏，随时可以放后台再点回来
  }

  /** 放到后台：任务面板收起，回到本章；转换在后台继续，侧栏可随时点回来 */
  const background = () => {
    clearWork()
    void watchJobs()
  }

  const adopt = async (vid: string) => {
    if (!novel || !chapter) return
    try {
      const r = await adoptVersion(novel.id, chapter.id, vid)
      notice.ok(t('app.adopted', { added: r.added, merged: r.merged })
        + (r.retracted ? t('app.adoptedRetracted', { n: r.retracted }) : '')
        + (r.digest === 'running' ? t('app.adoptedDigest') : ''))
      await reloadOpen(novel.id, chapter.id)
      void refreshNovels()
      bumpSummary()
    } catch (e) {
      notice.err(t('app.err.adopt', { msg: msg(e) }))
    }
  }

  const removeVersion = async (vid: string) => {
    if (!novel || !chapter) return
    if (!(await ask({ title: t('confirm.version.title'), body: t('confirm.version.body'),
      action: t('confirm.delete'), danger: true }))) return
    try {
      await deleteVersion(novel.id, chapter.id, vid)
      bumpSummary()
      await reloadOpen(novel.id, chapter.id)
      if (docVid === vid) {
        // 删的正是在看的这版：换到采用版（没有就最新一版），画布不必跟着关掉
        const c = await getChapter(novel.id, chapter.id)
        const next = c.adopted_version ?? c.versions[0]?.id
        if (next) await openVersion(novel.id, chapter.id, next)
        else { setDoc(null); setDocVid(null); setDirty(false) }
      }
    } catch (e) {
      notice.err(t('app.err.remove', { msg: msg(e) }))
    }
  }

  const removeChapter = async () => {
    if (!novel || !chapter) return
    if (!(await ask({ title: t('confirm.chapter.title', { title: chapter.title }), body: t('confirm.chapter.body'),
      action: t('confirm.delete'), danger: true }))) return
    try {
      await deleteChapter(novel.id, chapter.id)
      bumpSummary()
      navigate(novelPath(novel.id, 'chapters'), { replace: true, state: { force: true } })
      void refreshNovels()
    } catch (e) {
      notice.err(t('app.err.remove', { msg: msg(e) }))
    }
  }

  const saveText = async (patch: { title?: string; text?: string }) => {
    if (!novel || !chapter) return
    try {
      await updateChapter(novel.id, chapter.id, patch)
      await reloadOpen(novel.id, chapter.id)
    } catch (e) {
      notice.err(t('app.err.saveText', { msg: msg(e) }))
    }
  }

  const save = async () => {
    if (!novel || !chapter || !docVid || !doc) return
    setSaving(true)
    setAlert(null)
    setVerification(null)
    try {
      const res = await saveVersion(novel.id, chapter.id, docVid, doc)
      // 后端整份复验过了才返回。不看 status 就等于假装保存成功——
      // 用户会一路改到点渲染时才被 422 挡住，那时早忘了改过什么。
      setVerification(res.verification)
      if (res.status === 'draft_invalid') {
        setAlert({ key: 'app.savedInvalid' })
      }
      savedDoc.current = doc
      setDirty(false)
      // 和 setDirty 同一拍开始重读出片状态：不让保存后的那一拍拿旧的出片状态去跟步
      void reloadFlow()
      await reloadOpen(novel.id, chapter.id)
    } catch (e) {
      notice.err(t('app.err.save', { msg: msg(e) }))
    } finally {
      setSaving(false)
    }
  }

  const openLocal = async (f: File) => {
    setAlert(null)
    setVerification(null)
    try {
      const parsed = JSON.parse(await f.text())
      if (!parsed?.meta || !parsed?.episodes) throw new Error(t('app.err.notStoryboard'))
      const local = parsed as Storyboard      // 本地文件不入库，只能下载；只能在 / 上看
      if (go('/', { force: true })) pendingLocal.current = local
      else { clearWork(); setChapter(null); setNovel(null); setDoc(local); savedDoc.current = local }
    } catch (e) {
      notice.err(t('app.err.read', { msg: msg(e) }))
    }
  }

  const resetSignedOut = () => {
    epoch.current += 1
    setRoleOf(null)           // 旧会话的角色确认不带到下一次登录
    keepOnlyAssistant(null)   // 退出登录：中断助手回答，丢掉所有对话
    clearWork()
    setUser(null)
    setNovel(null)
    setChapter(null)
    setNovels([])
    setRunning([])
    setRecentDone([]); setActivityDot(false); setActivityOpen(false); setActivityTab('activity')
    prevRunning.current = new Set()
  }
  resetRef.current = resetSignedOut

  const logout = () => {
    // 主动退出不算「未登录打开深链接」：导航落地前的那一帧还在旧地址上，别弹登录框
    prompted.current.add(location.pathname)
    clearSession()
    resetSignedOut()
    setAuth({ open: false, mode: 'login', expired: false })
    navigate('/', { replace: true, state: { force: true } })
  }

  // 登录成功后首页淡出（≤400ms），完成后进应用；动画回调之外再留一个定时兜底，进应用不只靠动画事件
  const fadeMs = Math.round(DUR.base * 1000)
  useEffect(() => {
    if (!entering) return
    const id = window.setTimeout(() => { setUser(entering); setEntering(null) }, fadeMs + 60)
    return () => window.clearTimeout(id)
  }, [entering, fadeMs])

  if (!user) {
    return (
      <motion.div animate={{ opacity: entering ? 0 : 1 }} transition={{ duration: fadeMs / 1000, ease: EASE_OUT }}
                  onAnimationComplete={() => { if (entering) { setUser(entering); setEntering(null) } }}>
        <Landing onSignIn={() => setAuth({ open: true, mode: 'login', expired: false })}
                 onSignUp={() => setAuth({ open: true, mode: 'register', expired: false })} />
        <AuthDialog open={auth.open} mode={auth.mode} firstRun={firstRun}
                    notice={auth.expired ? t('auth.expired') : null}
                    onMode={(mode) => setAuth((a) => ({ ...a, mode }))}
                    onClose={() => setAuth((a) => ({ ...a, open: false }))}
                    onDone={(u) => { setAuth({ open: false, mode: 'login', expired: false }); setEntering(u) }} />
      </motion.div>
    )
  }

  /** 加载途中不显示旧小说（§5.2） */
  const shown = novel && novel.id === nid ? novel : null
  const converting = !!chapter && (running.some((j) => j.chapter_id === chapter.id)
    || (!!job && RUNNING.includes(job.status)))
  /** 章节打开时复验报告与分镜视图进工作流的 ③④⑤；本地 JSON 与分批预览（属于 ② 的进度）留在原位 */
  const inWorkflow = !!(shown && chapter && chapter.id === cid && !preview)
  const board = (
    <>
      {verification && <div id="verification"><VerificationPanel report={verification} doc={doc} /></div>}
      {doc && (
        <StoryboardView
          doc={doc}
          canSave={docVid !== null}
          report={verification}
          film={flow.film}
          styleUrl={styleUrl}
          styleMime={novel?.style_image?.mime}
          preview={preview}
          runId={docVid}
          version={novel && chapter && docVid
            ? { nid: novel.id, cid: chapter.id, vid: docVid } : null}
          dirty={dirty}
          saving={saving}
          onChange={(next) => { setDoc(next); setDirty(true) }}
          onSave={save}
          onCanvasClose={() => void reloadFlow()}
          {...(inWorkflow && loc.kind === 'chapter' && nid && cid ? {
            tab: loc.tab,
            onTab: (tb: Tab) => go(chapterPath(nid, cid, { step: boardStep(), tab: tb, canvas: loc.canvas, view: loc.view }),
                                   { replace: true }),
            canvasOpen: loc.canvas,
            onCanvas: (open: boolean) => { if (open) openCanvas(); else closeCanvas() },
            canvasPanel: navState?.panel,
            canvasView: loc.view,
            onCanvasView: (v: 'timeline' | 'graph') =>
              go(chapterPath(nid, cid, { step: boardStep(), tab: loc.tab, canvas: true, view: v }), { replace: true }),
            onJumpShot: () => go(chapterPath(nid, cid, { step: boardStep() }), { replace: true }),
          } : {})}
          bench={novel && chapter ? {
            novel, chapter, versionId: docVid, job, converting,
            disabled: submitting || svcDown,
            onConvert: (opts) => convert(opts, true),
            onOpenVersion: (vid) => { void confirmLeave().then((ok) => { if (ok) void openVersion(novel.id, chapter.id, vid) }) },
            onAdopt: (vid) => void adopt(vid),
            onDeleteVersion: (vid) => void removeVersion(vid),
            onNovelChanged: () => { void reloadOpen(novel.id, chapter.id); void refreshNovels() },
            notice: error ? t('app.err.submit', { msg: formatMsg(error, locale) }) : alert && alertText(alert),
          } : null}
        />
      )}
    </>
  )

  return (
    <>
      {confirmUi}
      <Tour />
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
      <AppShell
        username={user.username}
        isAdmin={user.role === 'admin'}
        adminOpen={adminOpen && user.role === 'admin'}
        onToggleAdmin={() => { if (adminOpen) leaveAdmin(); else void enterAdmin() }}
        onLogout={logout}
        onNewNovel={() => void newNovel()}
        onOpenLocal={() => fileRef.current?.click()}
        crumbs={[]}
        projectSwitcher={shown && !(adminOpen && user.role === 'admin') ? (
          <ProjectSwitcher novels={novels} currentId={shown.id}
                           meta={[shown.params.aspect_ratio, ART_STYLES.find((a) => a.value === shown.params.art_style)?.label]
                             .filter(Boolean).join(' · ')}
                           onOpen={(nid) => void openNovel(nid)} onNew={() => void newNovel()}
                           onAll={() => void newNovel()} />
        ) : null}
        chapterCrumb={shown && chapter && !(adminOpen && user.role === 'admin') ? (
          <ChapterCrumb chapters={[...shown.chapters].sort((a, b) => a.order - b.order)} currentId={chapter.id}
                        onOpen={(cid) => void openChapter(cid)} />
        ) : null}
        costMeter={shown && !(adminOpen && user.role === 'admin')
          ? <CostMeter data={summary.data} chapterId={chapter?.id ?? null} /> : null}
        runningCount={running.length}
        onOpenAssistant={shown && !(adminOpen && user.role === 'admin')
          ? () => { setActivityTab('assistant'); setActivityOpen(true) } : undefined}
        onToggleActivity={() => {
          setActivityDot(false)
          if (!activityOpen) { setActivityTab('activity'); setActivityOpen(true) }
          else if (activityTab === 'activity') setActivityOpen(false)
          else setActivityTab('activity')
        }}
        activityDot={activityDot && !activityOpen}
        activity={activityOpen ? (
          <ActivityPanel running={running} done={recentDone} onOpen={openJob}
                         tab={activityTab} onTab={setActivityTab}
                         assistant={shown ? (
                           <AssistantPanel novelId={shown.id}
                                           chapters={shown.chapters.map((c) => ({ id: c.id, title: c.title }))}
                                           onGoto={(g) => {
                                             if (!nid) return
                                             if (g.chapter_id === cid) { go(chapterPath(nid, cid, { step: g.step }), { replace: true }); return }
                                             go(chapterPath(nid, g.chapter_id, { step: g.step }))
                                           }} />
                         ) : undefined}
                         onOpenDone={(d) => openFromToast.current(d)}
                         onClose={() => {
                           setActivityOpen(false)
                           document.querySelector<HTMLElement>('[data-testid="activity-bell"]')?.focus()
                         }} />
        ) : null}
        service={{ down: svcDown, model: svc?.model, noKey: !!svc && !svc.api_key_configured }}
        viewKey={adminOpen ? 'admin' : `${novel?.id ?? ''}/${chapter?.id ?? ''}`}
        sidebarHandlesCollapse={!!shown}
        sidebar={adminOpen && user.role === 'admin' ? null : shown ? (
          <ProjectNav
            novel={shown}
            section={chapter ? null : section}
            chapterId={chapter?.id ?? null}
            summary={summary.data}
            running={running}
            onSection={(sec) => void gotoSection(sec)}
            onOpenChapter={(cid) => void openChapter(cid)}
            onNewChapter={() => void newChapter()}
          />
        ) : (
          <NovelSidebar
            novels={novels}
            novel={shown}
            chapterId={chapter?.id ?? null}
            running={running}
            activeJobId={job?.id ?? null}
            loading={novelsLoading}
            onOpenNovel={(nid) => void openNovel(nid)}
            onOpenChapter={(cid) => void openChapter(cid)}
            onOpenJob={openJob}
            onNewChapter={() => void newChapter()}
            onNewNovel={() => void newNovel()}
          />
        )}
      >
        {adminOpen && user.role === 'admin' ? (
          <AdminView me={user} onBack={leaveAdmin} />
        ) : (
          <div className="main">
            {loc.kind === 'notFound' && <NotFound onHome={() => go('/')} />}
            {((nid && novel?.id !== nid) || (cid && chapter?.id !== cid)) && (
              <div className="flex flex-col gap-3" data-testid="route-loading" aria-label={t('route.loading')}>
                <Skeleton className="h-8 w-1/3" /><Skeleton className="h-40 w-full" />
              </div>
            )}
            {loc.kind === 'home' && !doc && !job && (
              <ShelfHome novels={novels} running={running} disabled={busy || svcDown}
                         onSubmit={(n) => void submitNovel(n)} onOpenNovel={(nid) => void openNovel(nid)} />
            )}
            {novel && novel.id === nid && loc.kind === 'novel' && (
              <NovelPage
                key={novel.id}
                novel={novel}
                onChanged={() => { void reloadOpen(novel.id); void refreshNovels() }}
                onDeleted={() => { navigate('/', { replace: true, state: { force: true } }); void refreshNovels() }}
                onOpenChapter={(cid) => void openChapter(cid)}
                section={section}
                onNewChapter={() => void newChapter()}
                summary={summary.data}
                lastChapterId={readLastChapter(novel.id)}
                onSection={(sec) => void gotoSection(sec)}
                onImportChapters={(list) => void importChapters(list)} importing={importing}
              />
            )}
            {novel && novel.id === nid && chapter && chapter.id === cid && (
              <ChapterWorkflow
                key={chapter.id}
                novel={novel}
                chapter={chapter}
                docVid={docVid}
                doc={doc}
                dirty={dirty}
                saving={saving}
                verificationFailed={verification?.status === 'failed'}
                converting={converting}
                disabled={submitting || svcDown}
                running={running}
                liveJobId={job && RUNNING.includes(job.status) ? job.id : null}
                onOpenJob={openJob}
                onConvert={convert}
                onOpenVersion={(vid) => {
                  void confirmLeave().then((ok) => { if (ok) void openVersion(novel.id, chapter.id, vid) })
                }}
                onAdopt={(vid) => void adopt(vid)}
                onDeleteVersion={(vid) => void removeVersion(vid)}
                onSaveText={saveText}
                onSave={() => void save()}
                onUndo={undo}
                onTextDirty={setTextDirty}
                onDelete={() => void removeChapter()}
                onRerunDigest={() => void rerunDigest(novel.id, chapter.id)
                  .then(() => reloadOpen(novel.id, chapter.id))
                  .catch((e) => setAlert({ err: errValue(e) }))}
                storyboard={inWorkflow ? board : null}
                step={loc.kind === 'chapter' ? loc.step : null}
                onStep={stepNav}
                onViewChange={onViewChange}
                openFilm={(s) => openCanvas(isCanvasStep(s) ? s : boardStep(), 'film')}
                flow={flow}
              />
            )}
            {error && <p className="alert">{t('app.err.submit', { msg: formatMsg(error, locale) })}</p>}
            {alert && <p className="alert">{alertText(alert)}</p>}
            {job && (
              <JobPanel
                job={job}
                onReset={reset}
                onBackground={background}
                previewing={preview !== null}
                onPreview={() => void loadPreview(job.id)}
              />
            )}
            {!inWorkflow && (!cid || chapter?.id === cid) && board}
            {/* 章节打开时提示条由章节工作流摆（原文与分镜一起管） */}
            {!(novel && chapter) && (
              <UnsavedBar show={dirty && docVid !== null} saving={saving}
                          onSave={() => void save()} onUndo={undo} />
            )}
          </div>
        )}
      </AppShell>
    </>
  )
}
