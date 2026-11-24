import { useEffect, useId, useRef, useState } from 'react'
import { BookOpen, ShieldBan, Trash2, UserRoundCheck } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { SelectMenu } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { useConfirm } from '@/components/common/ConfirmDialog'
import { useI18n } from '@/i18n/core'
import { errText } from '@/i18n/serverMsg'
import type { MsgKey } from '@/i18n/core'
import { notice } from '@/lib/notice'
import {
  addConstraint, addLifecycle, deleteConstraint, deleteLifecycle, setOutline,
  setSynopsis, updateConstraint, updateLifecycle, updateNovel,
} from '../api'
import { LIFECYCLE_STATUS, LIFECYCLE_TYPE, NARRATION_MODE, label } from '../labels'
import { ART_STYLES, TTS_VOICES } from '../presets'
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
import { StyleImageField } from './params/StyleImageField'
import { useStyleImage } from '../useStyleImage'
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
  importing?: boolean
}

const ASSET_SECTIONS: Section[] = ['characters', 'locations', 'props', 'creatures']

const SECTION_EYEBROW: Record<Section, string> = {
  overview: 'OVERVIEW',
  chapters: 'CHAPTERS',
  characters: 'CHARACTERS',
  locations: 'LOCATIONS',
  props: 'PROPS',
  creatures: 'CREATURES',
  memory: 'MEMORY',
  constraints: 'RULES',
  settings: 'SETTINGS',
}

const noop = () => {}

const err = errText

/** 小说页 = 总会话：制作参数默认值 + 长期记忆（主线剧情、创作限制、资产库、人物生命周期） */
export function NovelPage({
  novel, onChanged, onDeleted, onOpenChapter, section, onNewChapter,
  summary, lastChapterId, onSection = noop, onImportChapters = noop, importing,
}: Props) {
  const { t } = useI18n()
  const [addCard, setAddCard] = useState(0)
  const [busy, setBusy] = useState(false)
  const sectionCount = section === 'chapters' ? novel.chapters.length
    : ASSET_SECTIONS.includes(section) ? (novel.memory.assets[section as AssetKind] ?? []).length
      : null

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
    <section className="novel" data-section={section}>
      <div className="novel__body" data-section={section}>
        {section !== 'overview' && <div className="sechead" data-section={section}>
          <div className="sechead__lead">
            <span className="sechead__eyebrow">{SECTION_EYEBROW[section]}</span>
            <div className="sechead__titlerow">
              <h3>{t(`nav.${section}` as MsgKey)}</h3>
              {sectionCount != null && (
                <span className="sechead__count">
                  <b>{sectionCount}</b>
                  {section === 'chapters' ? t('overview.stat.chapters') : t('overview.stat.assets')}
                </span>
              )}
            </div>
          </div>
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
                        onNewChapter={onNewChapter} onImport={onImportChapters} importing={importing} />
        )}
        {section === 'settings' && <ParamsTab novel={novel} busy={busy} run={run} onChanged={onChanged} />}
        {section === 'constraints' && <ConstraintsTab novel={novel} busy={busy} run={run} />}
        {ASSET_SECTIONS.includes(section) && (
          <NovelAssets key={section} nid={novel.id} assets={novel.memory.assets} onSaved={onChanged}
                       kind={section as AssetKind} focusAdd={addCard} />
        )}
        {section === 'memory' && (
          <div className="memory">
            <section className="memory__group" data-tone="blue" aria-label={t('nav.memoryPlot')}>
              <header className="memory__group-head">
                <span className="memory__group-icon" aria-hidden><BookOpen /></span>
                <div className="memory__group-text">
                  <span className="memory__group-index">01 / PLOT</span>
                  <h4>{t('nav.memoryPlot')}</h4>
                </div>
              </header>
              <PlotTab novel={novel} busy={busy} run={run} />
            </section>
            <section className="memory__group" data-tone="violet" aria-label={t('nav.memoryLife')}>
              <header className="memory__group-head">
                <span className="memory__group-icon" aria-hidden><UserRoundCheck /></span>
                <div className="memory__group-text">
                  <span className="memory__group-index">02 / STATE</span>
                  <h4>{t('nav.memoryLife')}</h4>
                </div>
              </header>
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
             className="setrow flex flex-col gap-3 border-b py-5 first:pt-0 last:border-b-0 sm:flex-row sm:gap-6">
      <div className="shrink-0 sm:w-60">
        <h3 id={id} className="text-sm font-medium">{label}</h3>
        {desc && <p className="mt-1 text-xs text-muted-foreground">{desc}</p>}
      </div>
      <div className="min-w-0 flex-1">{children}</div>
    </section>
  )
}

function ParamsTab({ novel, busy, run, onChanged }: TabProps & { onChanged: () => void }) {
  const { t } = useI18n()
  const styleUrl = useStyleImage(novel.id, novel.style_image?.hash)
  const [title, setTitle] = useState(novel.title)
  const [params, setParams] = useState<NovelParams>({ ...DEFAULT_PARAMS, ...novel.params })
  const prefixRef = useRef<HTMLInputElement>(null)
  const saved = { ...DEFAULT_PARAMS, ...novel.params }
  const styleLabel = ART_STYLES.find((a) => a.value === params.art_style)?.label ?? params.art_style
  const voiceLabel = TTS_VOICES.find((v) => v.value === params.tts_voice)?.label ?? params.tts_voice
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
    <Card className="novel__sec params__card max-w-[760px] gap-0 p-5 sm:p-6">
      <div className="params__summary">
        <span className="params__summary-eyebrow" aria-hidden>PROJECT / SETTINGS</span>
        <div className="params__chips">
          <span className="params__chip" data-tone="blue">
            <small>{t('novel.set.ratio')}</small><b>{params.aspect_ratio}</b>
          </span>
          <span className="params__chip" data-tone="clay">
            <small>{t('novel.set.style')}</small><b>{styleLabel}</b>
          </span>
          <span className="params__chip" data-tone="violet">
            <small>{t('novel.set.narration')}</small><b>{label(NARRATION_MODE, params.narration_mode)}</b>
          </span>
          <span className="params__chip" data-tone="sand">
            <small>{t('novel.set.voice')}</small><b>{voiceLabel}</b>
          </span>
        </div>
      </div>
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
      <SetRow testId="set-style-image" label={t('style.ref.title')}>
        <StyleImageField nid={novel.id} meta={novel.style_image} url={styleUrl} onChanged={() => onChanged()} />
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
  // Server value changed (e.g. the assistant edited it): follow it only when there is no unsaved typing,
  // i.e. the local text still equals the previous server value.
  const serverOutline = novel.memory.plot.outline
  const lastServerOutline = useRef(serverOutline)
  useEffect(() => {
    const prev = lastServerOutline.current
    lastServerOutline.current = serverOutline
    setOutlineText((cur) => (cur === prev ? serverOutline : cur))
  }, [serverOutline])
  const synopsis = Object.fromEntries(novel.memory.plot.chapters.map((s) => [s.chapter_id, s]))
  return (
    <div className="plot">
      <p className="lib__hint">{t('novel.plot.hint')}</p>
      <Card className="novel__sec plot__outline gap-3 p-4 sm:p-5">
        <span className="plot__eyebrow" aria-hidden>MAIN ARC</span>
        <Field label={t('novel.plot.outline')} wide>
          <Textarea rows={4} value={outline} onChange={(e) => setOutlineText(e.target.value)} />
        </Field>
        <div>
          <Button size="sm" disabled={busy || outline === novel.memory.plot.outline}
                  onClick={() => void run(t('novel.plot.saveOutline'), t('novel.ok.saved'), () => setOutline(novel.id, outline))}>
            {t('novel.plot.saveOutline')}
          </Button>
        </div>
      </Card>
      <Card className="novel__sec plot__chapters gap-3 p-4 sm:p-5">
        <div className="plot__chapter-head">
          <h3 className="plot__h mt-0">{t('novel.plot.perChapter')}</h3>
          <span className="plot__chapter-count">{novel.chapters.length}</span>
        </div>
        {!novel.chapters.length && <p className="empty">{t('novel.plot.noChapters')}</p>}
        <ol className="plot__list">
          {novel.chapters.map((c, i) => {
            const s = synopsis[c.id]
            const value = drafts[c.id] ?? s?.synopsis ?? ''
            return (
              <li key={c.id} className="plot__item" data-state={s ? 'ready' : 'todo'}>
                <div className="plot__title">
                  <span className="plot__num" aria-hidden>{String(i + 1).padStart(2, '0')}</span>
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
      <div className="cons__cols">
        <section className="cons__main">
          <div className="cons__main-head">
            <h3>{t('novel.cons.listTitle')}</h3>
            <span className="cons__count">{list.length}</span>
          </div>
          <ul className="cons__list">
            {list.map((c) => (
              <li key={c.id} className={`cons__item${c.enabled ? '' : ' is-off'}`}>
                <label className="check">
                  <Checkbox checked={c.enabled} disabled={busy}
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
          {!list.length && (
            <div className="cons__empty">
              <span className="cons__empty-halo" aria-hidden />
              <span className="cons__empty-icon" aria-hidden><ShieldBan /></span>
              <span className="cons__empty-tag" aria-hidden>RULEBOOK / 0</span>
              <p>{t('novel.cons.empty')}</p>
              <span className="cons__empty-hint">{t('novel.cons.emptyHint')}</span>
            </div>
          )}
        </section>
        <Card className="novel__sec cons__compose gap-4 p-4 sm:p-5">
          <div className="cons__compose-head">
            <span className="cons__compose-eyebrow" aria-hidden>NEW RULE</span>
            <h3>{t('novel.cons.compose')}</h3>
          </div>
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
      <section className="life__main">
        <div className="life__main-head">
          <h3>{t('novel.life.listTitle')}</h3>
          <span className="life__count">{list.length}</span>
        </div>
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
        {!list.length && (
          <div className="life__empty">
            <span className="life__empty-icon" aria-hidden><UserRoundCheck /></span>
            <p>{t('novel.life.empty')}</p>
          </div>
        )}
      </section>
      <Card className="novel__sec life__compose gap-4 p-4 sm:p-5">
        <div className="life__compose-head">
          <span className="life__compose-eyebrow" aria-hidden>NEW RECORD</span>
          <h3>{t('novel.life.compose')}</h3>
        </div>
        <div className="form life__new">
          <div className="form__grid">
            <Field label={t('novel.life.character')}>
              <SelectMenu
                className="ui-select"
                ariaLabel={t('novel.life.character')}
                value={who}
                options={[
                  { value: '', label: t('novel.life.pickCharacter') },
                  ...chars.map((c) => ({ value: c.id, label: `${c.id} ${c.name}` })),
                ]}
                onChange={setWho}
              />
            </Field>
            <Field label={t('novel.life.type')}>
              <SelectMenu
                className="ui-select"
                ariaLabel={t('novel.life.type')}
                value={type}
                options={(Object.entries(LIFECYCLE_TYPE) as [LifecycleType, string][])
                  .map(([v, n]) => ({ value: v, label: n }))}
                onChange={(v) => setType(v as LifecycleType)}
              />
            </Field>
            <Field label={t('novel.life.since')}>
              <SelectMenu
                className="ui-select"
                ariaLabel={t('novel.life.since')}
                value={since}
                options={[
                  { value: '', label: t('novel.life.wholeBook') },
                  ...novel.chapters.map((c) => ({ value: c.id, label: c.title })),
                ]}
                onChange={setSince}
              />
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
