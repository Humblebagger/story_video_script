import { useEffect, useMemo, useRef, useState } from 'react'
import { Check, Clapperboard, Download, Lock, Palette, PencilLine } from 'lucide-react'
import { stampVersion, updateAsset, updateShot } from '../edit'
import type { AssetKind } from '../edit'
import { FIDELITY_MODE, label, NARRATION_MODE } from '../labels'
import { buildIndex, pct } from '../resolve'
import type { Shot, Storyboard, VersionRef } from '../types'
import { AssetsView } from './AssetsView'
import { EpisodeView } from './EpisodeView'
import { RenderView } from './RenderView'
import { SourceView } from './SourceView'
import type { Workbench } from './CanvasPanels'
import { TimelineCanvas } from './TimelineCanvas'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { useI18n } from '@/i18n/core'

type Tab = 'shots' | 'assets' | 'source' | 'render' | 'json'

const TABS: Tab[] = ['shots', 'assets', 'source', 'render', 'json']

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
}

export function StoryboardView({
  doc, canSave, runId = null, dirty, saving, onChange, onSave, preview = null, version = null,
  bench = null, openFilm, onCanvasClose,
}: Props) {
  const { t } = useI18n()
  const [tab, setTab] = useState<Tab>('shots')
  const [focusUnit, setFocusUnit] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [canvas, setCanvas] = useState(false)
  const [canvasPanel, setCanvasPanel] = useState<'film' | undefined>(undefined)
  // 只认挂载之后的新信号：计数在挂载前就大于 0（比如换步骤后重新挂载）不能自己打开画布
  const seenOpenFilm = useRef(openFilm)
  useEffect(() => {
    if (!openFilm || openFilm === seenOpenFilm.current) return
    seenOpenFilm.current = openFilm
    setCanvasPanel('film')
    setCanvas(true)
  }, [openFilm])
  const closeCanvas = () => { setCanvas(false); setCanvasPanel(undefined); onCanvasClose?.() }
  /** 从画布跳回来要定位的镜头 */
  const [focusShot, setFocusShot] = useState<string | null>(null)
  const idx = useMemo(() => buildIndex(doc), [doc])
  const { meta, source } = doc

  const pickUnit = (unitId: string) => {
    setFocusUnit(unitId)
    setTab('source')
  }

  const jumpShot = (shotId: string) => {
    closeCanvas()
    setTab('shots')
    setFocusShot(shotId)
  }

  useEffect(() => {
    if (!focusShot || tab !== 'shots') return
    const el = document.getElementById(`shot-${focusShot}`)
    el?.scrollIntoView?.({ block: 'center', behavior: 'smooth' })
    el?.classList.add('is-flash')
    const t = window.setTimeout(() => el?.classList.remove('is-flash'), 1600)
    setFocusShot(null)
    return () => clearTimeout(t)
  }, [focusShot, tab])

  // stampVersion：一旦用上 beats/constraints，产物就不该再自称 0.4
  const changeShot = (episodeId: string, shotId: string, patch: Partial<Shot>) =>
    onChange(stampVersion(updateShot(doc, episodeId, shotId, patch)))

  const changeAsset = (kind: AssetKind, id: string, patch: Record<string, unknown>) =>
    onChange(updateAsset(doc, kind, id, patch))

  return (
    <div className="sb">
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
                disabled={!dirty || saving}
                onClick={onSave}
              >
                {saving ? t('board.saving') : dirty ? t('board.save') : t('board.saved')}
              </Button>
            )}
            <Button size="sm" variant="ghost" onClick={() => setCanvas(true)}
                    title={t('board.canvasTip')}>
              <Clapperboard />
              {t('board.canvas')}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => download(doc)}>
              <Download />
              {t('board.download')}
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

        <div className="stats grid grid-cols-3 gap-2 md:grid-cols-6">
          <Stat n={idx.stats.units} k={t('board.statUnits')} />
          <Stat n={idx.stats.episodes} k={t('board.statEpisodes')} />
          <Stat n={idx.stats.shots} k={t('board.statShots')} />
          <Stat n={pct(idx.stats.coveredRatio)} k={t('board.statCoverage')}
                warn={idx.stats.coveredRatio < 1} />
          <Stat n={pct(idx.stats.narratedRatio)} k={t('board.statNarrated')} />
          <Stat n={pct(idx.stats.inferredRatio)} k={t('board.statInferred')} />
        </div>

        {meta?.style?.style_prefix && (
          <p className="sb__style"><Palette size={14} aria-hidden />{meta.style.style_prefix}</p>
        )}
      </header>

      <div className="sb__bar">
        <nav className="inline-flex shrink-0 rounded-lg bg-muted p-1" aria-label={t('board.viewsAria')}>
          {TABS.filter((id) => !preview || id !== 'render').map((id) => (
            <button
              key={id}
              type="button"
              aria-pressed={tab === id}
              className={cn(
                'tabs__btn rounded-md border-0 px-3 py-1.5 text-sm text-muted-foreground',
                'transition-[color,background-color,box-shadow] duration-150 ease-out hover:text-foreground',
                tab === id && 'is-on bg-background font-medium text-foreground shadow-sm dark:bg-foreground/10',
              )}
              onClick={() => setTab(id)}
            >
              {t(`board.tabs.${id}`)}
            </button>
          ))}
        </nav>
      </div>

      {tab === 'shots' && (
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
                        onClose={closeCanvas} onJumpShot={jumpShot} initialPanel={canvasPanel} />
      )}
    </div>
  )
}

function Stat({ n, k, warn }: { n: number | string; k: string; warn?: boolean }) {
  return (
    <div className={`stat${warn ? ' stat--warn' : ''}`}>
      <b>{n}</b>
      <span>{k}</span>
    </div>
  )
}
