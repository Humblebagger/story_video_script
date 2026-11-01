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
import { AdminView } from './components/admin/AdminView'
import { ChapterWorkflow } from './components/workflow/ChapterWorkflow'
import { JobPanel } from './components/JobPanel'
import { AuthDialog } from './components/auth/AuthDialog'
import type { AuthMode } from './components/auth/AuthDialog'
import { Landing } from './components/landing/Landing'
import { useI18n } from './i18n/core'
import { Tour } from './components/common/Tour'
import { useConfirm } from './components/common/ConfirmDialog'
import type { NewNovel } from './components/NewNovelForm'
import { NewNovelForm } from './components/NewNovelForm'
import { NovelPage } from './components/NovelPage'
import { NovelSidebar } from './components/NovelSidebar'
import { StoryboardView } from './components/StoryboardView'
import { VerificationPanel } from './components/VerificationPanel'
import { toast } from 'sonner'
import { notice } from './lib/notice'
import { UnsavedBar } from './components/workflow/UnsavedBar'
import { notify, primeNotifications } from './notify'
import type {
  Chapter, Health, Job, JobSummary, NarrationMode, Novel, NovelSummary, Storyboard,
  VerificationReport,
} from './types'
import { useChapterFlow } from './useChapterFlow'
import { useJob } from './useJob'
import { DUR, EASE_OUT } from './motion'

const RUNNING = ['queued', 'running']
const msg = (e: unknown) => (e instanceof Error ? e.message : String(e))

export default function App() {
  const { t } = useI18n()
  const [ask, confirmUi] = useConfirm()
  const [user, setUser] = useState<User | null>(() => (getToken() ? getCachedUser() : null))
  const [adminOpen, setAdminOpen] = useState(false)
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

  const [doc, setDoc] = useState<Storyboard | null>(null)
  /** doc 属于哪个版本；本地打开的 JSON 与分批预览都没有 */
  const [docVid, setDocVid] = useState<string | null>(null)
  const [dirty, setDirty] = useState(false)
  /** 撤销的基准：上一次从服务端拿到（或存下）的那份 doc；编辑不改它 */
  const savedDoc = useRef<Storyboard | null>(null)
  const [saving, setSaving] = useState(false)
  const [alert, setAlert] = useState<string | null>(null)
  /** 服务端对当前产物的复验结果。保存一次刷新一次，不通过时它就是拦人的那块牌子 */
  const [verification, setVerification] = useState<VerificationReport | null>(null)
  /** 正在看的是整章跑完之前的部分产物（只读）。null = 看的是正式产物或什么都没开 */
  const [preview, setPreview] = useState<{ done: number; total: number } | null>(null)
  /** 预览请求在路上时任务可能已经跑完：只有仍想看这个任务的预览时才落地 */
  const previewFor = useRef<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  /** 异步回来时用户可能已经切走：只认仍然打开着的那一章 */
  const openChapterId = useRef<string | null>(null)
  openChapterId.current = chapter?.id ?? null
  /** 章节级只读出片状态（步骤条与主按钮用）；画布关闭、保存后重读 */
  const flow = useChapterFlow(novel && chapter && docVid ? { nid: novel.id, cid: chapter.id, vid: docVid } : null)
  const reloadFlow = flow.reload
  /** 递增一次 = 打开画布并切到「出片」页 */
  const [openFilmN, setOpenFilmN] = useState(0)
  /** 章节原文框里有没保存的改动（由章节工作流报上来）；和分镜的 dirty 一起管离开提醒 */
  const [textDirty, setTextDirty] = useState(false)
  /** 正附着着的任务（announce 用来判断「用户正看着它跑完」） */
  const attachedJob = useRef<string | null>(null)

  const refreshNovels = useCallback(async () => {
    try {
      setNovels((await listNovels()).novels)
    } catch {
      /* 服务未连通时由 svcDown 统一提示，这里不再重复报错 */
    } finally {
      setNovelsLoading(false)
    }
  }, [])

  /** 重新取打开着的小说与章节（转换完成、采用、改记忆之后） */
  const reloadOpen = useCallback(async (nid?: string, cid?: string | null) => {
    try {
      if (nid) setNovel(await getNovel(nid))
      if (nid && cid) {
        const c = await getChapter(nid, cid)
        if (openChapterId.current === cid) setChapter(c)
      }
    } catch (e) {
      setAlert(msg(e))
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
    void refreshNovels()
    announce(done)
    // 巡检要过几秒才发现它结束了；在那之前章节页不能还显示「转换中」
    setRunning((list) => list.filter((j) => j.id !== done.id))
    const nid = novelRef.current?.id
    if (nid) void reloadOpen(nid, openChapterId.current)
    if (done.status === 'failed') return      // 失败时已打开的预览保留：已通过的批次照样能看
    previewFor.current = null
    setPreview(null)
    setDoc(done.result)
    savedDoc.current = done.result
    setDocVid(done.id)
    setDirty(false)
  }, [refreshNovels, reloadOpen, announce])

  const { job, error, submitting, start, attach, reset } = useJob(onJobDone)
  attachedJob.current = job?.id ?? null

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
      if (previewFor.current === jobId) setAlert(t('app.err.preview', { msg: msg(e) }))
    }
  }, [t])

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
      if (finished) {
        void refreshNovels()
        const nid = novelRef.current?.id
        if (nid) void reloadOpen(nid, openChapterId.current)
      }
    } catch {
      /* 巡检失败静默重试，不打扰用户 */
    }
  }, [announce, refreshNovels, reloadOpen])

  // 登录态失效（token 过期或被撤销）→ 回首页并打开登录框
  // 监听只订阅一次，所以通过 ref 拿到最新的重置函数；和退出共用，保证换账号不残留上一个人的小说与产物
  const resetRef = useRef<() => void>(() => {})
  useEffect(() => onUnauthorized(() => {
    resetRef.current()
    setEntering(null)
    setAuth({ open: true, mode: 'login', expired: true })
  }), [])

  // 全新部署（服务端还没有任何账号）：首页直接打开注册
  const firstRun = !!svc && (svc.users ?? 0) === 0
  useEffect(() => {
    if (!user && firstRun) setAuth((a) => (a.open ? a : { open: true, mode: 'register', expired: false }))
  }, [user, firstRun])

  // 随登录态重取：否则注册后再退出，登录页仍显示「服务端还没有任何账号」
  useEffect(() => {
    health().then((h) => { setSvc(h); setSvcDown(false) }).catch(() => setSvcDown(true))
  }, [user?.id])

  useEffect(() => {
    if (!user) return
    // 缓存的用户信息可能已过期，向服务端确认一次
    me().then(setUser).catch(() => { /* 401 已由 onUnauthorized 处理 */ })
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

  const openVersion = useCallback(async (nid: string, cid: string, vid: string) => {
    reset()
    previewFor.current = null
    setPreview(null)
    setAlert(null)
    setVerification(null)
    try {
      const v = await getVersion(nid, cid, vid)
      if (openChapterId.current !== cid) return
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
          ? t('app.versionFailed', { msg: (v.error ?? '').split('\n')[0] })
          : t('app.versionEmpty'))
      }
    } catch (e) {
      setAlert(t('app.err.version', { msg: msg(e) }))
    }
  }, [reset, t])

  const openNovel = async (nid: string) => {
    if (!(await confirmLeave())) return
    clearWork()
    setChapter(null)
    try {
      setNovel(await getNovel(nid))
    } catch (e) {
      setAlert(t('app.err.novel', { msg: msg(e) }))
    }
  }

  /** 打开章节：给了 vid 就直接打开那一版；否则本章有转换在跑就接上任务面板，再否则摆出采用版（没有就最新一版） */
  const openChapter = async (cid: string, nid = novel?.id, jobId?: string, vid?: string) => {
    if (!nid || !(await confirmLeave())) return
    clearWork()
    try {
      const [n, c] = await Promise.all([
        novel?.id === nid ? Promise.resolve(novel) : getNovel(nid), getChapter(nid, cid)])
      setNovel(n)
      openChapterId.current = c.id
      setChapter(c)
      const live = vid ? undefined : jobId ?? running.find((j) => j.chapter_id === cid)?.id
      if (live) attach(live)
      else {
        const target = vid ?? c.adopted_version ?? c.versions[0]?.id
        if (target) void openVersion(nid, cid, target)
      }
    } catch (e) {
      setAlert(t('app.err.chapter', { msg: msg(e) }))
    }
  }

  const openJob = (j: JobSummary) => {
    if (job?.id === j.id) return
    if (j.novel_id && j.chapter_id) void openChapter(j.chapter_id, j.novel_id, j.id)
    else { clearWork(); attach(j.id) }
  }

  // 成功的：直接打开它产出的那一版（版本号 = 任务号），不留一个跑完的任务面板；失败的接上任务面板看原因
  openFromToast.current = (j) => {
    const { novel_id: nid, chapter_id: cid } = j
    if (nid && cid) {
      if (j.status === 'failed') void openChapter(cid, nid, j.id)
      // 已经在这一章：和点版本条一样只换版本；否则和侧栏打开别的章节一样
      else if (novel?.id === nid && chapter?.id === cid) { void confirmLeave().then((ok) => { if (ok) void openVersion(nid, cid, j.id) }) }
      else void openChapter(cid, nid, undefined, j.id)
    } else openJob(j as unknown as JobSummary)
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

  const newNovel = async () => {
    if (!(await confirmLeave())) return
    clearWork()
    setNovel(null)
    setChapter(null)
  }

  const submitNovel = async (n: NewNovel) => {
    setBusy(true)
    setAlert(null)
    try {
      const created = await createNovel(n.title, n.params)
      const chapters = []
      for (const c of n.chapters) chapters.push(await createChapter(created.id, c.title, c.text))
      await refreshNovels()
      setNovel(await getNovel(created.id))
      if (chapters.length) await openChapter(chapters[0].id, created.id)
    } catch (e) {
      setAlert(t('app.err.createNovel', { msg: msg(e) }))
    } finally {
      setBusy(false)
    }
  }

  const newChapter = async () => {
    if (!novel || !(await confirmLeave())) return
    try {
      const c = await createChapter(novel.id, t('app.chapterDefault', { n: novel.chapters.length + 1 }))
      await refreshNovels()
      await openChapter(c.id, novel.id)
      setNovel(await getNovel(novel.id))
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
    void start(() => convertChapter(nid, cid, { overrides, strict }),
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
      clearWork()
      setChapter(null)
      await reloadOpen(novel.id)
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
        setAlert(t('app.savedInvalid'))
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
      clearWork()
      setChapter(null)
      setNovel(null)
      setDoc(parsed as Storyboard)    // 本地文件不入库，只能下载
      savedDoc.current = parsed as Storyboard
    } catch (e) {
      notice.err(t('app.err.read', { msg: msg(e) }))
    }
  }

  const resetSignedOut = () => {
    clearWork()
    setAdminOpen(false)
    setUser(null)
    setNovel(null)
    setChapter(null)
    setNovels([])
    setRunning([])
  }
  resetRef.current = resetSignedOut

  const logout = () => {
    clearSession()
    resetSignedOut()
    setAuth({ open: false, mode: 'login', expired: false })
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

  const converting = !!chapter && (running.some((j) => j.chapter_id === chapter.id)
    || (!!job && RUNNING.includes(job.status)))
  /** 章节打开时复验报告与分镜视图进工作流的 ③④⑤；本地 JSON 与分批预览（属于 ② 的进度）留在原位 */
  const inWorkflow = !!(novel && chapter && !preview)
  const board = (
    <>
      {verification && <div id="verification"><VerificationPanel report={verification} doc={doc} /></div>}
      {doc && (
        <StoryboardView
          doc={doc}
          canSave={docVid !== null}
          preview={preview}
          runId={docVid}
          version={novel && chapter && docVid
            ? { nid: novel.id, cid: chapter.id, vid: docVid } : null}
          dirty={dirty}
          saving={saving}
          onChange={(next) => { setDoc(next); setDirty(true) }}
          onSave={save}
          openFilm={openFilmN}
          onCanvasClose={() => void reloadFlow()}
          bench={novel && chapter ? {
            novel, chapter, versionId: docVid, job, converting,
            disabled: submitting || svcDown,
            onConvert: (opts) => convert(opts, true),
            onOpenVersion: (vid) => { void confirmLeave().then((ok) => { if (ok) void openVersion(novel.id, chapter.id, vid) }) },
            onAdopt: (vid) => void adopt(vid),
            onDeleteVersion: (vid) => void removeVersion(vid),
            onNovelChanged: () => { void reloadOpen(novel.id, chapter.id); void refreshNovels() },
            notice: error ? t('app.err.submit', { msg: error }) : alert,
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
        onToggleAdmin={() => setAdminOpen((v) => !v)}
        onLogout={logout}
        onNewNovel={() => void newNovel()}
        onOpenLocal={() => fileRef.current?.click()}
        crumbs={adminOpen && user.role === 'admin' ? []
          : [novel?.title, chapter?.title, docVid ?? undefined].filter((x): x is string => !!x)}
        service={{ down: svcDown, model: svc?.model, noKey: !!svc && !svc.api_key_configured }}
        viewKey={adminOpen ? 'admin' : `${novel?.id ?? ''}/${chapter?.id ?? ''}`}
        sidebar={adminOpen && user.role === 'admin' ? null : (
          <NovelSidebar
            novels={novels}
            novel={novel}
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
          <AdminView me={user} onBack={() => setAdminOpen(false)} />
        ) : (
          <div className="main">
            {!novel && !doc && !job && (
              <NewNovelForm disabled={busy || svcDown} onSubmit={(n) => void submitNovel(n)} />
            )}
            {novel && !chapter && (
              <NovelPage
                key={novel.id}
                novel={novel}
                onChanged={() => { void reloadOpen(novel.id); void refreshNovels() }}
                onDeleted={() => { setNovel(null); void refreshNovels() }}
                onOpenChapter={(cid) => void openChapter(cid)}
                running={running}
                onNewChapter={() => void newChapter()}
              />
            )}
            {novel && chapter && (
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
                  .catch((e) => setAlert(msg(e)))}
                storyboard={inWorkflow ? board : null}
                openFilm={() => setOpenFilmN((n) => n + 1)}
                flow={flow}
              />
            )}
            {error && <p className="alert">{t('app.err.submit', { msg: error })}</p>}
            {alert && <p className="alert">{alert}</p>}
            {job && (
              <JobPanel
                job={job}
                onReset={reset}
                onBackground={background}
                previewing={preview !== null}
                onPreview={() => void loadPreview(job.id)}
              />
            )}
            {!inWorkflow && board}
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
