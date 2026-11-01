import { useEffect, useId, useRef, useState } from 'react'
import { Trash2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { useConfirm } from '@/components/common/ConfirmDialog'
import { useI18n } from '@/i18n/core'
import type { MsgKey } from '@/i18n/core'
import { notice } from '@/lib/notice'
import {
  addConstraint, addLifecycle, deleteConstraint, deleteLifecycle, setOutline,
  setSynopsis, updateConstraint, updateLifecycle, updateNovel,
} from '../api'
import { LIFECYCLE_STATUS, LIFECYCLE_TYPE, label } from '../labels'
import type { LifecycleType, Novel, NovelParams, NovelSummaryData } from '../types'
import type { AssetKind } from '../edit'
import type { Section } from '../section'
import { ChaptersPage } from './ChaptersPage'
import { NovelAssets } from './NovelAssets'
import { NovelOverview } from './NovelOverview'
import { MoreParams } from './params/MoreParams'
import { NarrationPick } from './params/NarrationPick'
import { RatioPicker } from './params/RatioPicker'
import { StylePicker } from './params/StylePicker'
import { VoicePicker } from './params/VoicePicker'
import { DEFAULT_PARAMS, Field } from './ParamsForm'

interface Props {
  novel: Novel
  /** 改完之后让上层重新取小说（侧栏、章节列表都跟着变） */
  onChanged: () => void
  onDeleted: () => void
  onOpenChapter: (cid: string) => void
  /** 左栏项目导航选中的分区：主区按它渲染 */
  section: Section
  onNewChapter: () => void
  /** 以下四个由 App 传入；单独渲染（测试）时可省 */
  summary?: NovelSummaryData | null
  lastChapterId?: string | null
  onSection?: (s: Section) => void
  onImportChapters?: (chapters: { title: string; text: string }[]) => void
}

const ASSET_SECTIONS: Section[] = ['characters', 'locations', 'props', 'creatures']

const noop = () => {}

const err = (e: unknown) => (e instanceof Error ? e.message : String(e))

/** 小说页 = 总会话：制作参数默认值 + 长期记忆（主线剧情、创作限制、资产库、人物生命周期） */
export function NovelPage({
  novel, onChanged, onDeleted, onOpenChapter, section, onNewChapter,
  summary, lastChapterId, onSection = noop, onImportChapters = noop,
}: Props) {
  const { t } = useI18n()
  const [addCard, setAddCard] = useState(0)
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

  return (
    <section className="novel">
      <div className="novel__body" data-section={section}>
        {section !== 'overview' && <div className="sechead">
          <h3>{t(`nav.${section}` as MsgKey)}</h3>
          {ASSET_SECTIONS.includes(section) && (
            <Button size="sm" data-testid="new-card" onClick={() => setAddCard((n) => n + 1)}>{t('nav.newCard')}</Button>
          )}
        </div>}
        {section === 'overview' && (
          <NovelOverview novel={novel} summary={summary ?? null} lastChapterId={lastChapterId}
                         onOpenChapter={onOpenChapter} onSection={onSection} onDeleted={onDeleted} />
        )}
        {section === 'chapters' && (
          <ChaptersPage novel={novel} summary={summary ?? null} onOpenChapter={onOpenChapter}
                        onNewChapter={onNewChapter} onImport={onImportChapters} />
        )}
        {section === 'settings' && <ParamsTab novel={novel} busy={busy} run={run} />}
        {section === 'constraints' && <ConstraintsTab novel={novel} busy={busy} run={run} />}
        {ASSET_SECTIONS.includes(section) && (
          <NovelAssets nid={novel.id} assets={novel.memory.assets} onSaved={onChanged}
                       kind={section as AssetKind} focusAdd={addCard} />
        )}
        {section === 'memory' && (
          <div className="flex flex-col gap-8">
            <section aria-label={t('nav.memoryPlot')}>
              <h4 className="mb-3 text-sm font-medium">{t('nav.memoryPlot')}</h4>
              <PlotTab novel={novel} busy={busy} run={run} />
            </section>
            <section aria-label={t('nav.memoryLife')}>
              <h4 className="mb-3 text-sm font-medium">{t('nav.memoryLife')}</h4>
              <LifecycleTab novel={novel} busy={busy} run={run} onOpenChapter={onOpenChapter} />
            </section>
          </div>
        )}
      </div>
    </section>
  )
}

export interface TabProps {
  novel: Novel
  busy: boolean
  run: (what: string, done: string, fn: () => Promise<unknown>) => Promise<void>
}

function SetRow({ label, desc, children, testId }: {
  label: string; desc?: string; children: React.ReactNode; testId: string
}) {
  const id = useId()
  return (
    <section data-testid={testId} role="group" aria-labelledby={id}
             className="flex flex-col gap-3 border-b py-5 first:pt-0 last:border-b-0 sm:flex-row sm:gap-6">
      <div className="shrink-0 sm:w-60">
        <h3 id={id} className="text-sm font-medium">{label}</h3>
        {desc && <p className="mt-1 text-xs text-muted-foreground">{desc}</p>}
      </div>
      <div className="min-w-0 flex-1">{children}</div>
    </section>
  )
}

function ParamsTab({ novel, busy, run }: TabProps) {
  const { t } = useI18n()
  const [title, setTitle] = useState(novel.title)
  const [params, setParams] = useState<NovelParams>({ ...DEFAULT_PARAMS, ...novel.params })
  const prefixRef = useRef<HTMLInputElement>(null)
  const saved = { ...DEFAULT_PARAMS, ...novel.params }
  const dirty = title.trim() !== novel.title
    || (Object.keys(params) as (keyof NovelParams)[]).some((k) => params[k] !== saved[k])
  // 只在换了小说、或服务端内容真的变了且本地没有未保存改动时才重置表单
  const dirtyRef = useRef(dirty)
  useEffect(() => { dirtyRef.current = dirty })
  const lastId = useRef(novel.id)
  const paramsKey = JSON.stringify(novel.params)
  useEffect(() => {
    const switched = lastId.current !== novel.id
    lastId.current = novel.id
    if (!switched && dirtyRef.current) return
    setTitle(novel.title)
    setParams({ ...DEFAULT_PARAMS, ...JSON.parse(paramsKey) })
  }, [novel.id, novel.title, paramsKey])
  return (
    <Card className="novel__sec max-w-[720px] gap-0 p-5">
      <p className="lib__hint mb-4">{t('novel.params.hint')}</p>
      <SetRow testId="set-title" label={t('novel.titleLabel')} desc={t('novel.set.titleDesc')}>
        <Input aria-label={t('novel.titleLabel')} value={title} onChange={(e) => setTitle(e.target.value)} />
      </SetRow>
      <SetRow testId="set-ratio" label={t('novel.set.ratio')} desc={t('novel.set.ratioDesc')}>
        <RatioPicker aria-label={t('novel.set.ratio')} value={params} onChange={setParams} />
      </SetRow>
      <SetRow testId="set-style" label={t('novel.set.style')} desc={t('novel.set.styleDesc')}>
        <StylePicker aria-label={t('novel.set.style')} value={params} onChange={setParams}
                     onCustom={() => { prefixRef.current?.scrollIntoView?.({ block: 'center', behavior: 'smooth' }); prefixRef.current?.focus() }} />
      </SetRow>
      <SetRow testId="set-narration" label={t('novel.set.narration')} desc={t('novel.set.narrationDesc')}>
        <NarrationPick value={params} onChange={setParams} />
      </SetRow>
      <SetRow testId="set-voice" label={t('novel.set.voice')} desc={t('novel.set.voiceDesc')}>
        <VoicePicker value={params} onChange={setParams} />
      </SetRow>
      <SetRow testId="set-more" label={t('novel.set.more')} desc={t('novel.set.moreDesc')}>
        <MoreParams value={params} onChange={setParams} prefixRef={prefixRef} />
      </SetRow>
      <div className="flex justify-end pt-5">
        <Button disabled={busy || !title.trim() || !dirty} data-testid="set-save"
                onClick={() => void run(t('novel.params.save'), t('novel.ok.saved'), () => updateNovel(novel.id, {
                  ...(title.trim() !== novel.title ? { title: title.trim() } : {}), params }))}>
          {t('novel.params.save')}
        </Button>
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
      keywords: keywords.split(/[,\uff0c\u3001\s]+/).filter(Boolean),  // 半角逗号、全角逗号、顿号、空白
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
            {e.evidence_quote && <blockquote className="life__quote">{t('common.quote', { text: e.evidence_quote })}</blockquote>}
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
