import { useMemo, useState } from 'react'
import { stampVersion, updateAsset, updateShot } from '../edit'
import type { AssetKind } from '../edit'
import { FIDELITY_MODE, label, NARRATION_MODE } from '../labels'
import { buildIndex, pct } from '../resolve'
import type { Shot, Storyboard } from '../types'
import { AssetsView } from './AssetsView'
import { EpisodeView } from './EpisodeView'
import { RenderView } from './RenderView'
import { SourceView } from './SourceView'

type Tab = 'shots' | 'assets' | 'source' | 'render' | 'json'

const TABS: [Tab, string][] = [
  ['shots', '分镜'], ['assets', '资产卡'], ['source', '原文溯源'],
  ['render', '渲染'], ['json', 'JSON'],
]

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
  /** 有 id 才能存回后端；本地打开的 JSON 只能下载 */
  canSave: boolean
  /** 历史记录 id，随任务清单一起带出去，便于把渲染产物挂回这次转换 */
  runId?: string | null
  dirty: boolean
  saving: boolean
  onChange: (doc: Storyboard) => void
  onSave: () => void
}

export function StoryboardView({
  doc, canSave, runId = null, dirty, saving, onChange, onSave,
}: Props) {
  const [tab, setTab] = useState<Tab>('shots')
  const [focusUnit, setFocusUnit] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const idx = useMemo(() => buildIndex(doc), [doc])
  const { meta, source } = doc

  const pickUnit = (unitId: string) => {
    setFocusUnit(unitId)
    setTab('source')
  }

  // stampVersion：一旦用上 beats/constraints，产物就不该再自称 0.4
  const changeShot = (episodeId: string, shotId: string, patch: Partial<Shot>) =>
    onChange(stampVersion(updateShot(doc, episodeId, shotId, patch)))

  const changeAsset = (kind: AssetKind, id: string, patch: Record<string, unknown>) =>
    onChange(updateAsset(doc, kind, id, patch))

  return (
    <div className="sb">
      <header className="sb__head">
        <div className="sb__title">
          <h2>{meta?.title ?? '未命名'}</h2>
          {source?.chapter && <span className="sb__chapter">{source.chapter}</span>}
          <span className="tag tag--ver">schema {meta?.schema_version}</span>
          <span className="tag">{label(FIDELITY_MODE, meta?.fidelity_mode)}</span>
          <span className="tag">{label(NARRATION_MODE, meta?.narration?.mode)}</span>
          <span className="tag">{meta?.video?.aspect_ratio}</span>

          <div className="sb__acts">
            <button
              className={`btn btn--sm${editing ? '' : ' btn--ghost'}`}
              onClick={() => setEditing((v) => !v)}
            >
              {editing ? '完成编辑' : '编辑分镜'}
            </button>
            {canSave && (
              <button
                className="btn btn--sm"
                disabled={!dirty || saving}
                onClick={onSave}
              >
                {saving ? '保存中…' : dirty ? '保存修改' : '已保存'}
              </button>
            )}
            <button className="btn btn--sm btn--ghost" onClick={() => download(doc)}>
              下载 JSON
            </button>
          </div>
        </div>

        {editing && (
          <p className="sb__editnote">
            编辑权只开在「呈现」一侧：分镜可改景别 / 运镜 / 时长 / 画面描述 / 氛围 / 音效 / 转场 / 角色表演，
            <b>资产卡</b>可改名称 / 别名 / 外貌 / 服装 / 状态 / 描述。
            🔒 锁死的是原文句子、溯源引用、推导标记、台词与旁白文本，以及被跨引用的各级 ID——
            改了就通不过后端的 lint 与保真校验。
            {!canSave && '　本地打开的 JSON 不入库，改完请下载。'}
          </p>
        )}

        <div className="stats">
          <Stat n={idx.stats.units} k="原文句" />
          <Stat n={idx.stats.episodes} k="集" />
          <Stat n={idx.stats.shots} k="镜头" />
          <Stat n={pct(idx.stats.coveredRatio)} k="覆盖率"
                warn={idx.stats.coveredRatio < 1} />
          <Stat n={pct(idx.stats.narratedRatio)} k="旁白占比" />
          <Stat n={pct(idx.stats.inferredRatio)} k="系统补充镜" />
        </div>

        {meta?.style?.style_prefix && (
          <p className="sb__style">🎨 {meta.style.style_prefix}</p>
        )}
      </header>

      <nav className="tabs">
        {TABS.map(([id, name]) => (
          <button
            key={id}
            className={`tabs__btn${tab === id ? ' is-on' : ''}`}
            onClick={() => setTab(id)}
          >
            {name}
          </button>
        ))}
      </nav>

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
      {tab === 'render' && <RenderView doc={doc} runId={runId} />}
      {tab === 'json' && <pre className="json">{JSON.stringify(doc, null, 2)}</pre>}
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
