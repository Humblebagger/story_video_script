import { useEffect, useMemo, useRef, useState } from 'react'
import {
  BookOpenText, Braces, Check, Clapperboard, Download, LayoutGrid, Lock, Palette,
  PencilLine, Play, Table2, UsersRound,
} from 'lucide-react'
import { stampVersion, updateAsset, updateShot } from '../edit'
import type { AssetKind } from '../edit'
import { FIDELITY_MODE, label, NARRATION_MODE } from '../labels'
import { buildIndex, pct } from '../resolve'
import type { FilmFocus, FilmSession, Shot, Storyboard, VerificationReport, VersionRef } from '../types'
import { AssetsView } from './AssetsView'
import { EpisodeView } from './EpisodeView'
import { ShotFocusView } from './ShotFocusView'
import { ShotSheet } from './ShotSheet'
import { RenderView } from './RenderView'
import { SourceView } from './SourceView'
import type { Workbench } from './CanvasPanels'
import { TimelineCanvas } from './TimelineCanvas'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { useI18n } from '@/i18n/core'

export type Tab = 'focus' | 'cards' | 'sheet' | 'assets' | 'source' | 'render' | 'json'

const TABS: Tab[] = ['focus', 'cards', 'sheet', 'assets', 'source', 'render', 'json']
const TAB_ICONS = {
  focus: Clapperboard,
  cards: LayoutGrid,
  sheet: Table2,
  assets: UsersRound,
  source: BookOpenText,
  render: Play,
  json: Braces,
} satisfies Record<Tab, typeof Clapperboard>

function download(doc: Storyboard) {
  const blob = new Blob([JSON.stringify(doc, null, 2)], {
    type: 'application/json;charset=utf-8',
  })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${doc.meta?.title || 'storyboard'}.json`
  a.click()
  URL.revokeObjectURL(url)
}

interface Props {
  doc: Storyboard
  /** 每加一就打开画布并停在「出片」页（章节工作流 ④⑤ 的主按钮） */
  openFilm?: number
  /** 画布关上时（出片、合成可能改了状态，让上层重读） */
  onCanvasClose?: () => void
  /** 有 id 才能存回后端；本地打开的 JSON 只能下载 */
  canSave: boolean
  /** 历史记录 id，随任务清单一起带出去，便于把渲染产物挂回这次转换 */
  runId?: string | null
  dirty: boolean
  saving: boolean
  onChange: (doc: Storyboard) => void
  onSave: () => void
  /** 整章跑完之前的部分产物：只读，不能编辑、保存或渲染 */
  preview?: { done: number; total: number } | null
  /** 产物所属的章节版本：画布上传关键帧图要用 */
  version?: VersionRef | null
  /** 所在的章节会话：画布里的「剧情」「任务」页要用 */
  bench?: Workbench | null
  /** 检查报告：三栏视图给镜头标红点 */
  report?: VerificationReport | null
  /** 出片会话：三栏视图右栏切成片段 */
  film?: FilmSession | null
  defaultTab?: Tab
  /** 页签（受控可选）：给了 onTab 就受控 */
  tab?: Tab
  onTab?: (t: Tab) => void
  /** 画布开关（受控可选）：给了 onCanvas 就受控；关闭时的重读、图片刷新照常 */
  canvasOpen?: boolean
  onCanvas?: (open: boolean) => void
  /** 画布打开时停在哪个侧栏页（受控时由上层给） */
  canvasPanel?: 'film'
  canvasView?: 'timeline' | 'graph'
  onCanvasView?: (v: 'timeline' | 'graph') => void
  /** 画布的聚焦请求与「用完了」的回报（原样交给画布） */
  canvasFocus?: FilmFocus
  onCanvasFocusDone?: () => void
  /** 侧栏页请求（可重复消费，见 NavState.panelReq）与「用完了」的回报 */
  canvasPanelReq?: { panel: 'film'; n: number }
  onCanvasPanelReqDone?: () => void
  /** 从画布跳回某个镜头（受控时由上层一次 replace 到 /:step，页签 focus）（§4.3） */
  onJumpShot?: () => void
  /** 小说风格参考图：画布关键帧区显示与下载 */
  styleUrl?: string | null
  styleMime?: string
}

export function StoryboardView({
  doc, canSave, runId = null, dirty, saving, onChange, onSave, preview = null, version = null,
  bench = null, openFilm, onCanvasClose, report = null, film = null, defaultTab, styleUrl = null, styleMime,
  tab: tabProp, onTab, canvasOpen, onCanvas, canvasPanel: canvasPanelProp, canvasView, onCanvasView, onJumpShot,
  canvasFocus, onCanvasFocusDone, canvasPanelReq, onCanvasPanelReqDone,
}: Props) {
  const { t } = useI18n()
  const [tabLocal, setTabLocal] = useState<Tab>(defaultTab ?? 'focus')
  const tab = onTab ? (tabProp ?? 'focus') : tabLocal
  const setTab = (next: Tab) => { if (onTab) onTab(next); else setTabLocal(next) }
  const [focusUnit, setFocusUnit] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [canvasLocal, setCanvasLocal] = useState(false)
  const canvas = onCanvas ? !!canvasOpen : canvasLocal
  const [panelLocal, setPanelLocal] = useState<'film' | undefined>(undefined)
  const canvasPanel = onCanvas ? canvasPanelProp : panelLocal
  // 只认挂载之后的新信号：计数在挂载前就大于 0（比如换步骤后重新挂载）不能自己打开画布；受控时上层直接给地址
  const seenOpenFilm = useRef(openFilm)
  useEffect(() => {
    if (!openFilm || openFilm === seenOpenFilm.current) return
    seenOpenFilm.current = openFilm
    setPanelLocal('film')
    setCanvasLocal(true)
  }, [openFilm])
  const [imagesKey, setImagesKey] = useState(0)
  // 画布从开到关（点关闭、浏览器后退都算）：刷新关键帧图，并让上层重读出片状态
  const closeRef = useRef(onCanvasClose)
  closeRef.current = onCanvasClose
  const wasOpen = useRef(canvas)
  useEffect(() => {
    if (wasOpen.current && !canvas) { setImagesKey((k) => k + 1); setPanelLocal(undefined); closeRef.current?.() }
    wasOpen.current = canvas
  }, [canvas])
  const openCanvas = () => { if (onCanvas) onCanvas(true); else setCanvasLocal(true) }
  const closeCanvas = () => { if (onCanvas) onCanvas(false); else setCanvasLocal(false) }
  /** 从画布跳回来要定位的镜头 */
  const [focusShot, setFocusShot] = useState<{ id: string; n: number } | null>(null)
  const idx = useMemo(() => buildIndex(doc), [doc])
  const { meta, source } = doc

  const pickUnit = (unitId: string) => {
    setFocusUnit(unitId)
    setTab('source')
  }

  const jumpShot = (shotId: string) => {
    setFocusShot((prev) => ({ id: shotId, n: (prev?.n ?? 0) + 1 }))
    if (onJumpShot) onJumpShot()        // 一次 replace：去掉 /canvas，页签回 focus
    else { closeCanvas(); setTab('focus') }
  }

  // stampVersion：一旦用上 beats/constraints，产物就不该再自称 0.4
  const changeShot = (episodeId: string, shotId: string, patch: Partial<Shot>) =>
    onChange(stampVersion(updateShot(doc, episodeId, shotId, patch)))

  const changeAsset = (kind: AssetKind, id: string, patch: Record<string, unknown>) =>
    onChange(updateAsset(doc, kind, id, patch))

  return (
    <div className={cn('sb', editing && 'sb--editing')}>
      <header className="sb__head">
        <div className="sb__title">
          <h2>{meta?.title ?? t('board.untitled')}</h2>
          {source?.chapter && <span className="sb__chapter">{source.chapter}</span>}
          <span className="sb__badges">
            <Badge variant="secondary" className="font-mono font-normal">schema {meta?.schema_version}</Badge>
            <Badge variant="secondary" className="font-normal">{label(FIDELITY_MODE, meta?.fidelity_mode)}</Badge>
            <Badge variant="secondary" className="font-normal">{label(NARRATION_MODE, meta?.narration?.mode)}</Badge>
            <Badge variant="secondary" className="font-normal tabular-nums">{meta?.video?.aspect_ratio}</Badge>
          </span>

          <div className="sb__acts">
            {!preview && (
              <Button size="sm" variant={editing ? 'default' : 'outline'}
                      onClick={() => setEditing((v) => !v)}>
                {editing ? <Check /> : <PencilLine />}
                {editing ? t('board.editDone') : t('board.edit')}
              </Button>
            )}
            {canSave && !preview && (
              <Button
                size="sm"
                id="storyboard-save"
                className={cn('sb__save', !dirty && !saving && 'is-saved')}
                disabled={!dirty || saving}
                title={!dirty && !saving ? t('board.saved') : undefined}
                onClick={onSave}
              >
                {saving ? t('board.saving') : dirty ? t('board.save') : (
                  <>
                    <Check aria-hidden />
                    <span className="max-sm:sr-only">{t('board.saved')}</span>
                  </>
                )}
              </Button>
            )}
            <Button size="sm" variant="ghost" className="sb__canvas" onClick={openCanvas}
                    title={t('board.canvasTip')} aria-label={t('board.canvas')}>
              <Clapperboard />
              <span className="max-sm:sr-only">{t('board.canvas')}</span>
            </Button>
            <Button size="sm" variant="ghost" className="sb__download" onClick={() => download(doc)}
                    aria-label={t('board.download')}>
              <Download />
              <span className="max-sm:sr-only">{t('board.download')}</span>
            </Button>
          </div>
        </div>

        {preview && (
          <p className="sb__preview">
            {t('board.preview', { done: preview.done, total: preview.total })}
          </p>
        )}

        {editing && !preview && (
          <p className="sb__editnote">
            {t('board.editNoteA')}
            <b>{t('board.editNoteAssets')}</b>{t('board.editNoteB')}
            <Lock size={12} aria-label={t('board.lock')} />{t('board.editNoteC')}
            {!canSave && t('board.localNote')}
          </p>
        )}

        <div className={cn(
          'stats grid grid-cols-3 gap-2 pb-1 md:grid-cols-6',
          editing && 'max-md:hidden',
        )}>
          <Stat n={idx.stats.units} k={t('board.statUnits')} tone="blue" />
          <Stat n={idx.stats.episodes} k={t('board.statEpisodes')} tone="violet" />
          <Stat n={idx.stats.shots} k={t('board.statShots')} tone="clay" />
          <Stat n={pct(idx.stats.coveredRatio)} k={t('board.statCoverage')}
                tone="sand" warn={idx.stats.coveredRatio < 1} />
          <Stat n={pct(idx.stats.narratedRatio)} k={t('board.statNarrated')} tone="rose" />
          <Stat n={pct(idx.stats.inferredRatio)} k={t('board.statInferred')} tone="slate" />
        </div>

        {meta?.style?.style_prefix && (
          <p className="sb__style"><Palette size={14} aria-hidden />{meta.style.style_prefix}</p>
        )}
      </header>

      <div className="sb__bar">
        <nav className="shrink-0 rounded-lg bg-muted p-1" aria-label={t('board.viewsAria')}>
          {TABS.filter((id) => !preview || id !== 'render').map((id) => {
            const Icon = TAB_ICONS[id]
            return (
              <button
                key={id}
                type="button"
                aria-pressed={tab === id}
                className={cn(
                  'tabs__btn rounded-md border-0',
                  'transition-[color,background-color,box-shadow] duration-150 ease-out',
                  tab === id && 'is-on font-medium',
                )}
                onClick={() => { setTab(id); setFocusShot(null) }}
              >
                <Icon size={14} aria-hidden />
                {t(`board.tabs.${id}`)}
              </button>
            )
          })}
        </nav>
      </div>

      {tab === 'focus' && (
        <ShotFocusView
          doc={doc} idx={idx} report={report} film={film} version={version}
          imagesKey={imagesKey} readOnly={!!preview} dirty={dirty} saving={saving}
          canSave={canSave && !preview} focusShot={focusShot}
          onShotChange={changeShot} onPickUnit={pickUnit} onSave={onSave}
          onOpenCanvas={openCanvas}
        />
      )}
      {tab === 'cards' && (
        <div className="eps">
          {doc.episodes?.map((ep) => (
            <EpisodeView
              key={ep.id}
              episode={ep}
              idx={idx}
              editing={editing}
              onPickUnit={pickUnit}
              onShotChange={(shotId, patch) => changeShot(ep.id, shotId, patch)}
            />
          ))}
        </div>
      )}
      {tab === 'sheet' && (
        <ShotSheet doc={doc} idx={idx} film={film} version={version} imagesKey={imagesKey} onJump={jumpShot} />
      )}
      {tab === 'assets' && (
        <AssetsView assets={doc.assets ?? {}} editing={editing} onChange={changeAsset} />
      )}
      {tab === 'source' && <SourceView doc={doc} idx={idx} focusUnit={focusUnit} />}
      {tab === 'render' && !preview && <RenderView doc={doc} runId={runId} />}
      {tab === 'json' && <pre className="json">{JSON.stringify(doc, null, 2)}</pre>}
      {canvas && (
        // 换版本（含画布里重新转换跑完）时撤销栈清零：上一版的改动不该能撤到新版上
        <TimelineCanvas key={version?.vid ?? 'local'} doc={doc} version={preview ? null : version}
                        bench={preview ? null : bench}
                        onChange={preview ? undefined : onChange}
                        canSave={canSave && !preview} dirty={dirty} saving={saving} onSave={onSave}
                        onClose={closeCanvas} onJumpShot={jumpShot} initialPanel={canvasPanel}
                        view={onCanvasView ? canvasView : undefined} onView={onCanvasView}
                        focus={canvasFocus} onFocusDone={onCanvasFocusDone}
                        panelReq={canvasPanelReq} onPanelReqDone={onCanvasPanelReqDone}
                        styleUrl={styleUrl} styleMime={styleMime} />
      )}
    </div>
  )
}

function Stat({ n, k, warn, tone }: {
  n: number | string; k: string; warn?: boolean; tone: 'blue' | 'violet' | 'clay' | 'sand' | 'rose' | 'slate'
}) {
  return (
    <div className={`stat${warn ? ' stat--warn' : ''}`} data-tone={tone}>
      <b>{n}</b>
      <span>{k}</span>
    </div>
  )
}
