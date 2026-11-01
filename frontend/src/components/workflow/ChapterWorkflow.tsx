/** 章节页 = 六步工作流：标题、步骤条、版本条，按正在看的步骤摆工作区（①原文 ②生成 ③④⑤分镜视图 ⑥下载），右下角一个主按钮。
 *  进章节、换版本（读到这一版的出片状态后）停在「该做的那一步」；之后只有该做的那一步往后走、且越过正在看的步骤时才跟着跳
 *  （用户手点的步骤保持；未保存的修改不算进跟步，保存或撤销不会让视图跳走），并对刚完成的步骤弹一句结果。
 *  原文与分镜的未保存修改共用底部的未保存提示条（保存 / 撤销两样都管）。 */
import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { motion } from 'motion/react'
import { Clapperboard, Film } from 'lucide-react'
import { toast } from 'sonner'
import { EmptyState } from '@/components/common/EmptyState'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/i18n/core'
import { flashTarget } from '@/lib/flash'
import { useMedia } from '@/lib/useMedia'
import { useMotionPresets } from '@/motion'
import { playableSeconds } from '@/timeline'
import { useTopbarSlot } from '@/components/shell/topbarSlot'
import type { Chapter, JobSummary, NarrationMode, Novel, Storyboard } from '@/types'
import type { useChapterFlow } from '@/useChapterFlow'
import { currentStep, primaryFor, stepDone, stepStates, STEPS } from '@/workflow'
import type { Fix, FlowInput, StepId } from '@/workflow'
import { ChapterHeader } from './ChapterHeader'
import { ChapterHeadContext } from './chapterHead'
import { DownloadStep } from './DownloadStep'
import { GenerateStep } from './GenerateStep'
import { PrimaryBar } from './PrimaryBar'
import { SourceStep } from './SourceStep'
import { Stepper } from './Stepper'
import { UnsavedBar } from './UnsavedBar'
import { VersionBar } from './VersionBar'

interface Props {
  novel: Novel
  chapter: Chapter
  /** 主区分镜属于哪个版本（正在看的版本）；没打开版本为 null */
  docVid: string | null
  doc: Storyboard | null
  /** 分镜有未保存的修改 / 正在保存 */
  dirty: boolean
  saving: boolean
  /** 保存后服务端复验没通过 */
  verificationFailed: boolean
  /** 本章有生成在跑（不论是否正看着它的任务面板） */
  converting: boolean
  disabled: boolean
  /** 在跑的任务（找本章的那个给「查看进度」） */
  running: JobSummary[]
  /** 正附着着的在跑任务（任务面板里那个）；没有为 null */
  liveJobId: string | null
  onOpenJob: (j: JobSummary) => void
  onConvert: (opts: { narration_mode?: NarrationMode; strict: boolean }) => void
  onOpenVersion: (vid: string) => void
  onAdopt: (vid: string) => void
  onDeleteVersion: (vid: string) => void
  onSaveText: (patch: { title?: string; text?: string }) => Promise<void>
  onSave: () => void
  /** 分镜回到上次保存的样子 */
  onUndo: () => void
  /** 原文框有没有没保存的改动（App 用来做离开提醒） */
  onTextDirty: (dirty: boolean) => void
  onDelete: () => void
  onRerunDigest: () => void
  /** ③④⑤ 的工作区：复验报告 + 分镜视图（App 组好传进来） */
  storyboard: ReactNode
  /** 打开画布并切到「出片」页 */
  openFilm: () => void
  flow: ReturnType<typeof useChapterFlow>
}

const BOARD: StepId[] = ['review', 'render', 'compose']
/** 这三步是居中卡片版式，主按钮放在卡片右下角 */
const CARD: StepId[] = ['import', 'storyboard', 'download']
const LIVE = ['queued', 'running']
const idx = (id: StepId) => STEPS.indexOf(id)
const nextFrame = (fn: () => void) =>
  typeof requestAnimationFrame === 'function' ? requestAnimationFrame(() => fn()) : setTimeout(fn, 0)

interface Seen {
  cur: StepId
  /** 上次比对时已读到出片状态的版本；没读到时是 undefined，这时不给④⑤的完成提示 */
  vid: string | null | undefined
  render: boolean
  compose: boolean
  /** 看到过本章在生成，等它出结果 */
  awaitingGen: boolean
  /** 等的是哪个任务（版本号 = 任务号）；只对它产出的版本提示「分镜已生成」 */
  genJob: string | undefined
}

export function ChapterWorkflow({
  novel, chapter, docVid, doc, dirty, saving, verificationFailed, converting, disabled, running, liveJobId, onOpenJob,
  onConvert, onOpenVersion, onAdopt, onDeleteVersion, onSaveText, onSave, onUndo, onTextDirty, onDelete, onRerunDigest,
  storyboard, openFilm, flow,
}: Props) {
  const { t } = useI18n()
  const m = useMotionPresets()
  const slot = useTopbarSlot()
  const narrowBar = useMedia('(max-width: 899px)')
  const [title, setTitle] = useState(chapter.title)
  const [text, setText] = useState(chapter.text)
  const [mode, setMode] = useState<NarrationMode | ''>('')
  const [strict, setStrict] = useState(false)
  const [savingText, setSavingText] = useState(false)
  useEffect(() => {
    setTitle(chapter.title)
    setText(chapter.text)
  }, [chapter.id, chapter.title, chapter.text])

  const locked = !!chapter.adopted_version
  const textDirty = title.trim() !== chapter.title || (!locked && text !== chapter.text)
  useEffect(() => { onTextDirty(textDirty) }, [textDirty, onTextDirty])
  // 离开本章（卸载）时撤掉离开提醒
  useEffect(() => () => onTextDirty(false), [onTextDirty])
  const version = chapter.versions.find((v) => v.id === docVid) ?? null
  // 出片状态没读到之前按「还没有」算：不让上一版的会话串过来，也不因为读到一半就跳步
  const ready = flow.loaded
  const input: FlowInput = {
    hasText: chapter.text.trim().length > 0, textDirty, converting, version, dirty, verificationFailed,
    film: version && ready ? flow.film : null,
    finalStale: ready && flow.finalStale,
    compose: ready ? flow.compose : null,
  }
  const cur = currentStep(input)
  // 跟步只看「做完了什么」：未保存的修改不算（否则保存或撤销会被当成往后走）
  const followCur = currentStep({ ...input, dirty: false, textDirty: false })
  const [view, setView] = useState<StepId>(cur)

  // 跟步与完成提示：只在「该做的那一步」往后走时跟；进章节的第一次计算、换版本后的首次读取都不提示
  const seen = useRef<Seen | null>(null)
  const vid = version?.id ?? null
  const live = !!version && LIVE.includes(version.status)
  const shots = version?.shots ?? 0
  const genDone = stepDone('storyboard', input)
  const renderDone = stepDone('render', input)
  const composeDone = stepDone('compose', input)
  const liveJob = running.find((j) => j.chapter_id === chapter.id)
  const genJobNow = liveJob?.id ?? liveJobId ?? undefined
  // 出片状态有读取在路上时值可能是旧的：跟步与提示等它落地
  const settled = ready && !flow.pending
  useEffect(() => {
    const now = { render: renderDone, compose: composeDone }
    const before = seen.current
    if (!before) {
      seen.current = { cur: followCur, vid: settled ? vid : undefined, ...now, awaitingGen: converting,
                       genJob: converting ? genJobNow : undefined }
      return
    }
    let awaitingGen = before.awaitingGen || converting
    let genJob = awaitingGen ? genJobNow ?? before.genJob : undefined
    // 生成结束：版本不再是「在跑」时出结果（只对这次生成产出的版本提示；失败或没打开它就不再等）
    if (awaitingGen && !converting && !live) {
      if (vid && vid === genJob && genDone) toast.success(t('flow.done.storyboard', { shots }))
      awaitingGen = false
      genJob = undefined
    }
    if (!settled) { seen.current = { ...before, awaitingGen, genJob }; return }
    if (vid && before.vid !== vid) {
      // 换了版本（含进章节后第一次打开版本、生成完摆出新版本）：等同重新进章节，停到这一版该做的那一步
      setView(followCur)
    } else if (idx(followCur) > idx(before.cur) && idx(followCur) > idx(view)) {
      // 只往前跟，且不把视图往回拉
      setView(followCur)
    }
    if (before.vid === vid) {
      if (!before.render && now.render) toast.success(t('flow.done.render'))
      if (!before.compose && now.compose) toast.success(t('flow.done.compose'))
    }
    seen.current = { cur: followCur, vid, ...now, awaitingGen, genJob }
  }, [followCur, view, vid, settled, converting, live, shots, genDone, renderDone, composeDone, genJobNow, t])

  const saveText = async () => {
    setSavingText(true)
    try {
      await onSaveText({
        ...(title.trim() !== chapter.title ? { title: title.trim() } : {}),
        ...(!locked && text !== chapter.text ? { text } : {}),
      })
    } finally {
      setSavingText(false)
    }
  }

  const primary = primaryFor(view, input)
  const run = () => {
    switch (primary.action) {
      case 'saveText': void saveText(); break
      case 'goto': if (primary.goto) setView(primary.goto); break
      case 'generate': onConvert({ ...(mode ? { narration_mode: mode } : {}), strict }); break
      case 'save': onSave(); break
      case 'openFilm': openFilm(); break
      case 'none': break
    }
  }
  /** 底部提示条：原文与分镜的未保存修改一起保存 / 一起撤销 */
  const boardDirty = dirty && docVid !== null
  const saveAll = async () => {
    if (textDirty) await saveText()
    if (boardDirty) onSave()
  }
  const undoAll = () => {
    if (textDirty) { setTitle(chapter.title); setText(chapter.text) }
    if (boardDirty) onUndo()
  }
  const busy = primary.action === 'generate' ? disabled
    : primary.action === 'save' ? saving
    : primary.action === 'saveText' ? savingText : false
  const fix = (f: Fix) => {
    if (f.step) setView(f.step)
    const target = f.target
    if (target) nextFrame(() => flashTarget(target))
    if (f.openFilm) openFilm()
  }
  /** ⑥「回到画布重新合成」：先回到 ⑤ 把分镜视图挂上，下一帧再打开画布（同一帧里加的计数会被新挂载的视图当成旧的） */
  const recompose = () => {
    setView('compose')
    nextFrame(openFilm)
  }

  const inlineBar = CARD.includes(view)
  const bar = <PrimaryBar primary={primary} busy={busy} inline={inlineBar} onRun={run} onFix={fix} />
  const finalFiles = input.film?.final?.files ?? []
  const workspace = (() => {
    switch (view) {
      case 'import':
        return (
          <div className="chap-card">
            <section className="chap">
              <SourceStep title={title} text={text} locked={locked} onTitle={setTitle} onText={setText} onDelete={onDelete} />
            </section>
            {bar}
          </div>
        )
      case 'storyboard':
        return (
          <>
            <div className="chap-card">
              <section className="chap">
                <GenerateStep novel={novel} chars={chapter.text.trim().length} mode={mode} strict={strict}
                              converting={converting} onMode={setMode} onStrict={setStrict}
                              onEditSource={() => setView('import')}
                              onOpenJob={liveJob ? () => onOpenJob(liveJob) : undefined} />
              </section>
              {bar}
            </div>
            {/* 打开的是没有产物的版本（失败等）时，它的复验报告仍在这里看得到 */}
            {!doc && storyboard}
          </>
        )
      case 'download':
        return docVid && input.film && finalFiles.length ? (
          <div className="chap-card">
            <section className="chap">
              <DownloadStep version={{ nid: novel.id, cid: chapter.id, vid: docVid }} film={input.film}
                            compose={input.compose} onOpenFilm={recompose} />
            </section>
            {bar}
          </div>
        ) : (
          <EmptyState icon={<Film className="size-6" />} title={t('flow.empty.film')} hint={t('flow.empty.filmHint')}
                      action={<Button variant="outline" onClick={() => setView('compose')}>{t('flow.goNeeded', { n: 5 })}</Button>} />
        )
      default:
        return (
          <>
            {!doc && (
              <EmptyState icon={<Clapperboard className="size-6" />} title={t('flow.empty.board')} hint={t('flow.empty.boardHint')}
                          action={<Button variant="outline" onClick={() => setView('storyboard')}>{t('flow.goNeeded', { n: 2 })}</Button>} />
            )}
            {storyboard}
          </>
        )
    }
  })()

  // 步骤条在顶栏中间的插槽里；拿不到插槽（单测等）时留在章节页原位
  const stepper = <Stepper states={stepStates(input)} view={view} onView={setView} compact={!!slot && narrowBar} />
  const headShots = doc ? doc.episodes.reduce((n, e) => n + e.shots.length, 0) : version?.shots ?? null
  const headSeconds = doc ? doc.episodes.reduce((n, e) => n + e.shots.reduce((a, sh) => a + playableSeconds(sh), 0), 0) : null
  const headProps = {
    num: Math.max(1, novel.chapters.findIndex((c) => c.id === chapter.id) + 1), title: chapter.title,
    shots: headShots, seconds: headSeconds, step: cur, live: converting, film: ready ? flow.film : null,
  }
  return (
    <ChapterHeadContext.Provider value={<ChapterHeader compact {...headProps} />}>
    <div className="flex flex-col gap-4 pb-28">
      {slot && createPortal(stepper, slot)}
      <ChapterHeader {...headProps} />
      {(!slot || view !== 'import') && (
        <section className="chap">
          {!slot && stepper}
          {view !== 'import' && (
            <VersionBar chapter={chapter} versionId={docVid} onOpenVersion={onOpenVersion} onAdopt={onAdopt}
                        onDeleteVersion={onDeleteVersion} onRerunDigest={onRerunDigest} />
          )}
        </section>
      )}
      {/* ③④⑤ 共用同一个 key：在这三步之间切换不重新挂载分镜视图（编辑态、页签、画布都保留） */}
      <motion.div key={BOARD.includes(view) ? 'board' : view} {...m.enter} className="flex flex-col gap-4">
        {workspace}
      </motion.div>
      {!inlineBar && bar}
      <UnsavedBar show={boardDirty || textDirty} saving={saving || savingText}
                  onSave={() => void saveAll()} onUndo={undoAll} />
    </div>
    </ChapterHeadContext.Provider>
  )
}
