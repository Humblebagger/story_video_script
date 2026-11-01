import { motion } from 'motion/react'
import { useEffect, useState } from 'react'
import { BookOpen, MoreHorizontal, Trash2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Progress } from '@/components/ui/progress'
import { EmptyState } from '@/components/common/EmptyState'
import { useConfirm } from '@/components/common/ConfirmDialog'
import { useI18n } from '@/i18n/core'
import { notice } from '@/lib/notice'
import { cn } from '@/lib/utils'
import { useMotionPresets } from '@/motion'
import {
  addConstraint, addLifecycle, deleteConstraint, deleteLifecycle, deleteNovel, setOutline,
  setSynopsis, updateConstraint, updateLifecycle, updateNovel,
} from '../api'
import { LIFECYCLE_STATUS, LIFECYCLE_TYPE, label } from '../labels'
import type { ChapterSummary, JobSummary, LifecycleType, Novel, NovelParams } from '../types'
import { NovelAssets } from './NovelAssets'
import { DEFAULT_PARAMS, Field, ParamsForm } from './ParamsForm'

type Tab = 'chapters' | 'params' | 'plot' | 'constraints' | 'assets' | 'lifecycle'

interface Props {
  novel: Novel
  /** 改完之后让上层重新取小说（侧栏、章节列表都跟着变） */
  onChanged: () => void
  onDeleted: () => void
  onOpenChapter: (cid: string) => void
  /** 后台在跑的转换：章节卡片据此显示「生成中」与进度 */
  running: JobSummary[]
  onNewChapter: () => void
}

const err = (e: unknown) => (e instanceof Error ? e.message : String(e))

/** 小说页 = 总会话：制作参数默认值 + 长期记忆（主线剧情、创作限制、资产库、人物生命周期） */
export function NovelPage({ novel, onChanged, onDeleted, onOpenChapter, running, onNewChapter }: Props) {
  const { t } = useI18n()
  const [ask, confirmUi] = useConfirm()
  const pending = novel.memory.lifecycle.filter((e) => e.status === 'proposed').length
  const [tab, setTab] = useState<Tab>(pending ? 'lifecycle' : 'chapters')
  const [busy, setBusy] = useState(false)

  const run = async (what: string, done: string, fn: () => Promise<unknown>) => {
    setBusy(true)
    try {
      await fn()
      onChanged()
      notice.ok(done)
    } catch (e) {
      notice.err(t('novel.failed', { what }), err(e))
    } finally {
      setBusy(false)
    }
  }

  const remove = async () => {
    if (!(await ask({ title: t('confirm.novel.title', { title: novel.title }), body: t('confirm.novel.body'),
      action: t('confirm.delete'), danger: true }))) return
    void deleteNovel(novel.id).then(onDeleted)
      .catch((e) => notice.err(t('novel.failed', { what: t('novel.deleteNovel') }), err(e)))
  }

  const tabs: [Tab, string][] = [
    ['chapters', t('novel.chapters')], ['params', t('novel.tabs.params')], ['plot', t('novel.tabs.plot')],
    ['constraints', t('novel.tabs.constraints')], ['assets', t('novel.tabs.assets')],
    ['lifecycle', pending ? t('novel.tabs.lifecyclePending', { n: pending }) : t('novel.tabs.lifecycle')],
  ]

  return (
    <section className="novel">
      {confirmUi}
      <header className="novel__head">
        <h2>《{novel.title}》</h2>
        <span className="novel__meta">
          {t('novel.meta', {
            n: novel.chapters.length, a: novel.chapters.filter((c) => c.adopted_version).length,
            u: String(novel.memory.numbering.next_unit).padStart(4, '0'),
            e: String(novel.memory.numbering.next_episode).padStart(2, '0'),
          })}
        </span>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" aria-label={t('novel.more')}>
              <MoreHorizontal aria-hidden />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem variant="destructive" onSelect={() => void remove()}>
              <Trash2 aria-hidden />{t('novel.deleteNovel')}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </header>
      <div className="novel__tabs">
        <nav className="inline-flex rounded-lg bg-muted p-1" aria-label={t('novel.tabsLabel')}>
          {tabs.map(([id, name]) => (
            <button
              key={id}
              type="button"
              aria-pressed={tab === id}
              className={cn(
                'tabs__btn whitespace-nowrap rounded-md border-0 px-3 py-1.5 text-sm text-muted-foreground',
                'transition-[color,background-color,box-shadow] duration-150 ease-out hover:text-foreground',
                tab === id && 'is-on bg-background font-medium text-foreground shadow-sm dark:bg-foreground/10',
              )}
              onClick={() => setTab(id)}
            >
              {name}
            </button>
          ))}
        </nav>
      </div>
      <div className="novel__body">
        {tab === 'chapters' && (
          <ChaptersTab novel={novel} running={running}
                       onOpenChapter={onOpenChapter} onNewChapter={onNewChapter} />
        )}
        {tab === 'params' && <ParamsTab novel={novel} busy={busy} run={run} />}
        {tab === 'plot' && <PlotTab novel={novel} busy={busy} run={run} />}
        {tab === 'constraints' && <ConstraintsTab novel={novel} busy={busy} run={run} />}
        {tab === 'assets' && (
          <NovelAssets nid={novel.id} assets={novel.memory.assets} onSaved={onChanged} />
        )}
        {tab === 'lifecycle' && (
          <LifecycleTab novel={novel} busy={busy} run={run} onOpenChapter={onOpenChapter} />
        )}
      </div>
    </section>
  )
}

/** 章节卡片网格：状态一眼可见，整卡可点进入该章 */
function ChaptersTab({ novel, running, onOpenChapter, onNewChapter }: {
  novel: Novel
  running: JobSummary[]
  onOpenChapter: (cid: string) => void
  onNewChapter: () => void
}) {
  const { t } = useI18n()
  const m = useMotionPresets()
  if (!novel.chapters.length) {
    return (
      <EmptyState icon={<BookOpen className="size-5" />} title={t('novel.empty')}
                  action={<Button onClick={onNewChapter}>{t('novel.newChapter')}</Button>} />
    )
  }
  const badge = (c: ChapterSummary, live: JobSummary | undefined) => {
    if (live) {
      return (
        <Badge variant="secondary">
          <span className="size-1.5 animate-pulse motion-reduce:animate-none rounded-full bg-primary" aria-hidden />
          {t('novel.status.running')}
        </Badge>
      )
    }
    if (c.adopted_version) return <Badge>{t('novel.status.adopted')}</Badge>
    if (c.latest_status === 'failed') return <Badge variant="destructive">{t('novel.status.failed')}</Badge>
    if (c.versions.length) return <Badge variant="outline">{t('novel.status.generated')}</Badge>
    return <Badge variant="outline" className="text-muted-foreground">{t('novel.status.none')}</Badge>
  }
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {novel.chapters.map((c, i) => {
        const live = running.find((j) => j.chapter_id === c.id)
        const p = live?.progress
        return (
          <motion.div key={c.id} {...m.item(i)}>
            <Card role="button" tabIndex={0} data-testid="chapter-card"
                  className="h-full cursor-pointer gap-3 p-4 transition-[border-color,box-shadow] duration-150 hover:border-foreground/20 hover:shadow-sm"
                  onClick={() => onOpenChapter(c.id)}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onOpenChapter(c.id) } }}>
              <div className="flex items-start justify-between gap-2">
                <b className="text-base">{c.title}</b>
                {badge(c, live)}
              </div>
              <p className="text-sm text-muted-foreground">
                {t('novel.chars', { n: c.chars })} · {t('novel.versions', { n: c.versions.length })}
              </p>
              {p && p.total_chars > 0 && <Progress value={(p.done_chars / p.total_chars) * 100} />}
            </Card>
          </motion.div>
        )
      })}
      <motion.div {...m.item(novel.chapters.length)}>
        <Card role="button" tabIndex={0} onClick={onNewChapter}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onNewChapter() } }}
              className="h-full min-h-24 cursor-pointer items-center justify-center border-dashed p-4 text-sm text-muted-foreground hover:bg-accent">
          {t('novel.newChapter')}
        </Card>
      </motion.div>
    </div>
  )
}

export interface TabProps {
  novel: Novel
  busy: boolean
  run: (what: string, done: string, fn: () => Promise<unknown>) => Promise<void>
}

function ParamsTab({ novel, busy, run }: TabProps) {
  const { t } = useI18n()
  const [title, setTitle] = useState(novel.title)
  const [params, setParams] = useState<NovelParams>({ ...DEFAULT_PARAMS, ...novel.params })
  useEffect(() => {
    setTitle(novel.title)
    setParams({ ...DEFAULT_PARAMS, ...novel.params })
  }, [novel.id, novel.title, novel.params])
  return (
    <Card className="novel__sec gap-4 p-4">
      <div className="form">
        <p className="lib__hint">{t('novel.params.hint')}</p>
        <div className="form__grid">
          <Field label={t('novel.titleLabel')} wide>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} />
          </Field>
        </div>
        <ParamsForm value={params} onChange={setParams} />
        <div className="form__foot">
          <span />
          <Button disabled={busy || !title.trim()}
                  onClick={() => void run(t('novel.params.save'), t('novel.ok.saved'), () => updateNovel(novel.id, {
                    ...(title.trim() !== novel.title ? { title: title.trim() } : {}), params }))}>
            {t('novel.params.save')}
          </Button>
        </div>
      </div>
    </Card>
  )
}

export function PlotTab({ novel, busy, run }: TabProps) {
  const { t } = useI18n()
  const [outline, setOutlineText] = useState(novel.memory.plot.outline)
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  useEffect(() => { setOutlineText(novel.memory.plot.outline) }, [novel.memory.plot.outline])
  const synopsis = Object.fromEntries(novel.memory.plot.chapters.map((s) => [s.chapter_id, s]))
  return (
    <div className="plot">
      <p className="lib__hint">{t('novel.plot.hint')}</p>
      <Card className="novel__sec gap-3 p-4">
        <Label className="field field--wide flex-col items-stretch gap-1.5 font-normal">
          <span>{t('novel.plot.outline')}</span>
          <Textarea rows={4} value={outline} onChange={(e) => setOutlineText(e.target.value)} />
        </Label>
        <div>
          <Button size="sm" disabled={busy || outline === novel.memory.plot.outline}
                  onClick={() => void run(t('novel.plot.saveOutline'), t('novel.ok.saved'), () => setOutline(novel.id, outline))}>
            {t('novel.plot.saveOutline')}
          </Button>
        </div>
      </Card>
      <Card className="novel__sec gap-3 p-4">
        <h3 className="plot__h mt-0">{t('novel.plot.perChapter')}</h3>
        {!novel.chapters.length && <p className="empty">{t('novel.plot.noChapters')}</p>}
        <ol className="plot__list">
          {novel.chapters.map((c) => {
            const s = synopsis[c.id]
            const value = drafts[c.id] ?? s?.synopsis ?? ''
            return (
              <li key={c.id} className="plot__item">
                <div className="plot__title">
                  <b>{c.title}</b>
                  {s && <Badge variant="secondary">{s.origin === 'user' ? t('novel.plot.byUser') : t('novel.plot.byAuto')}</Badge>}
                  {!s && !c.adopted_version && <Badge variant="outline">{t('novel.plot.notAdopted')}</Badge>}
                </div>
                <Textarea rows={2} maxLength={200} value={value}
                          placeholder={t('novel.plot.synopsisPh')}
                          onChange={(e) => setDrafts((d) => ({ ...d, [c.id]: e.target.value }))} />
                {drafts[c.id] !== undefined && drafts[c.id] !== (s?.synopsis ?? '') && (
                  <Button size="sm" disabled={busy}
                          onClick={() => void run(t('novel.plot.saveSynopsis'), t('novel.ok.saved'), async () => {
                            await setSynopsis(novel.id, c.id, drafts[c.id])
                            setDrafts(({ [c.id]: _, ...rest }) => rest)
                          })}>
                    {t('novel.plot.saveSynopsis')}
                  </Button>
                )}
              </li>
            )
          })}
        </ol>
      </Card>
    </div>
  )
}

export function ConstraintsTab({ novel, busy, run }: TabProps) {
  const { t } = useI18n()
  const [ask, confirmUi] = useConfirm()
  const [text, setText] = useState('')
  const [neg, setNeg] = useState('')
  const [keywords, setKeywords] = useState('')
  const list = novel.memory.constraints
  const add = () => run(t('novel.cons.whatAdd'), t('novel.ok.consAdded'), async () => {
    await addConstraint(novel.id, {
      text: text.trim(), negative_prompt: neg.trim(),
      keywords: keywords.split(/[,，、\s]+/).filter(Boolean),
    })
    setText('')
    setNeg('')
    setKeywords('')
  })
  return (
    <div className="cons">
      {confirmUi}
      <p className="lib__hint">{t('novel.cons.hint')}</p>
      <ul className="cons__list">
        {list.map((c) => (
          <li key={c.id} className={`cons__item${c.enabled ? '' : ' is-off'}`}>
            <label className="check">
              <input type="checkbox" checked={c.enabled} disabled={busy}
                     onChange={(e) => void run(t('novel.cons.whatToggle'), t('novel.ok.updated'), () =>
                       updateConstraint(novel.id, c.id, { enabled: e.target.checked }))} />
              <b>{c.text}</b>
            </label>
            {c.negative_prompt && <span className="cons__neg">{t('novel.cons.neg', { v: c.negative_prompt })}</span>}
            {!!c.keywords.length && <span className="cons__kw">{t('novel.cons.kw', { v: c.keywords.join(t('common.listSep')) })}</span>}
            <Button variant="ghost" size="icon-xs" className="hrun__del text-muted-foreground hover:text-destructive"
                    title={t('novel.cons.delTip')} aria-label={t('novel.cons.delTip')}
                    onClick={async () => {
                      if (await ask({ title: t('confirm.constraint.title'), action: t('confirm.delete'), danger: true })) {
                        void run(t('novel.cons.whatDelete'), t('novel.ok.deleted'), () => deleteConstraint(novel.id, c.id))
                      }
                    }}>
              <Trash2 aria-hidden />
            </Button>
          </li>
        ))}
      </ul>
      {!list.length && <p className="empty">{t('novel.cons.empty')}</p>}
      <Card className="novel__sec gap-3 p-4">
        <div className="form cons__new">
          <Field label={t('novel.cons.rule')} wide>
            <Input value={text} placeholder={t('novel.cons.rulePh')}
                   onChange={(e) => setText(e.target.value)} />
          </Field>
          <div className="form__grid">
            <Field label={t('novel.cons.negField')}>
              <Input value={neg} placeholder={t('novel.cons.negPh')} onChange={(e) => setNeg(e.target.value)} />
            </Field>
            <Field label={t('novel.cons.kwField')}>
              <Input value={keywords} placeholder={t('novel.cons.kwPh')} onChange={(e) => setKeywords(e.target.value)} />
            </Field>
          </div>
          <div className="form__foot">
            <span />
            <Button size="sm" disabled={busy || !text.trim()} onClick={() => void add()}>
              {t('novel.cons.add')}
            </Button>
          </div>
        </div>
      </Card>
    </div>
  )
}

function LifecycleTab({ novel, busy, run, onOpenChapter }: TabProps & {
  onOpenChapter: (cid: string) => void
}) {
  const { t } = useI18n()
  const [ask, confirmUi] = useConfirm()
  const chars = novel.memory.assets.characters ?? []
  const names = Object.fromEntries(chars.map((c) => [c.id, c.name]))
  const titles = Object.fromEntries(novel.chapters.map((c) => [c.id, c.title]))
  const [who, setWho] = useState('')
  const [type, setType] = useState<LifecycleType>('deceased')
  const [detail, setDetail] = useState('')
  const [since, setSince] = useState('')
  const order = { proposed: 0, confirmed: 1, rejected: 2 }
  const list = [...novel.memory.lifecycle].sort((a, b) => order[a.status] - order[b.status])

  return (
    <div className="life">
      {confirmUi}
      <p className="lib__hint">
        {t('novel.life.hintA')}<b>{t('novel.life.hintB')}</b>{t('novel.life.hintC')}
      </p>
      <ul className="life__list">
        {list.map((e) => (
          <li key={e.id} className={`life__item life__item--${e.status}`}>
            <div className="life__top">
              <b>{e.character_id} {names[e.character_id] ?? ''}</b>
              <Badge variant="secondary">{label(LIFECYCLE_TYPE, e.type)}</Badge>
              <Badge variant={e.status === 'proposed' ? 'destructive' : 'outline'}>
                {label(LIFECYCLE_STATUS, e.status)}
              </Badge>
              <Badge variant="outline" className="border-dashed">
                {e.origin === 'model' ? t('novel.life.byModel') : t('novel.life.byUser')}
              </Badge>
              {e.since.chapter_id && (
                <button className="linkbtn" onClick={() => onOpenChapter(e.since.chapter_id!)}>
                  {titles[e.since.chapter_id] ?? e.since.chapter_id}
                  {e.since.unit_ref ? ` · ${e.since.unit_ref}` : ''}
                </button>
              )}
            </div>
            {e.detail && <p className="life__detail">{e.detail}</p>}
            {e.evidence_quote && <blockquote className="life__quote">「{e.evidence_quote}」</blockquote>}
            <div className="life__acts">
              {e.status !== 'confirmed' && (
                <Button size="sm" disabled={busy}
                        onClick={() => void run(t('novel.life.confirm'), t('novel.ok.confirmed'), () =>
                          updateLifecycle(novel.id, e.id, { status: 'confirmed' }))}>
                  {t('novel.life.confirm')}
                </Button>
              )}
              {e.status !== 'rejected' && (
                <Button size="sm" variant="outline" disabled={busy}
                        onClick={() => void run(t('novel.life.reject'), t('novel.ok.rejected'), () =>
                          updateLifecycle(novel.id, e.id, { status: 'rejected' }))}>
                  {t('novel.life.reject')}
                </Button>
              )}
              <Button variant="ghost" size="icon-xs" disabled={busy}
                      className="ml-auto text-muted-foreground hover:text-destructive"
                      aria-label={t('novel.life.delete')} title={t('novel.life.delete')}
                      onClick={async () => {
                        if (await ask({ title: t('confirm.record.title'), action: t('confirm.delete'), danger: true })) {
                          void run(t('novel.life.delete'), t('novel.ok.deleted'), () => deleteLifecycle(novel.id, e.id))
                        }
                      }}>
                <Trash2 aria-hidden />
              </Button>
            </div>
          </li>
        ))}
      </ul>
      {!list.length && <p className="empty">{t('novel.life.empty')}</p>}
      <Card className="novel__sec gap-3 p-4">
        <div className="form life__new">
          <div className="form__grid">
            <Field label={t('novel.life.character')}>
              <select value={who} onChange={(e) => setWho(e.target.value)}>
                <option value="">{t('novel.life.pickCharacter')}</option>
                {chars.map((c) => <option key={c.id} value={c.id}>{c.id} {c.name}</option>)}
              </select>
            </Field>
            <Field label={t('novel.life.type')}>
              <select value={type} onChange={(e) => setType(e.target.value as LifecycleType)}>
                {Object.entries(LIFECYCLE_TYPE).map(([v, n]) => <option key={v} value={v}>{n}</option>)}
              </select>
            </Field>
            <Field label={t('novel.life.since')}>
              <select value={since} onChange={(e) => setSince(e.target.value)}>
                <option value="">{t('novel.life.wholeBook')}</option>
                {novel.chapters.map((c) => <option key={c.id} value={c.id}>{c.title}</option>)}
              </select>
            </Field>
            <Field label={t('novel.life.detail')} wide>
              <Input value={detail} placeholder={t('novel.life.detailPh')}
                     onChange={(e) => setDetail(e.target.value)} />
            </Field>
          </div>
          <div className="form__foot">
            <span>{!chars.length && t('novel.life.noChars')}</span>
            <Button size="sm" disabled={busy || !who}
                    onClick={() => void run(t('novel.life.whatAdd'), t('novel.ok.recordAdded'), async () => {
                      await addLifecycle(novel.id, { character_id: who, type, detail,
                                                     chapter_id: since || null })
                      setDetail('')
                    })}>
              {t('novel.life.addManual')}
            </Button>
          </div>
        </div>
      </Card>
    </div>
  )
}
