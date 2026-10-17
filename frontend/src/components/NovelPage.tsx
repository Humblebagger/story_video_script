import { useEffect, useState } from 'react'
import {
  addConstraint, addLifecycle, deleteConstraint, deleteLifecycle, deleteNovel, setOutline,
  setSynopsis, updateConstraint, updateLifecycle, updateNovel,
} from '../api'
import { LIFECYCLE_STATUS, LIFECYCLE_TYPE, label } from '../labels'
import type { LifecycleType, Novel, NovelParams } from '../types'
import { NovelAssets } from './NovelAssets'
import { DEFAULT_PARAMS, Field, ParamsForm } from './ParamsForm'

type Tab = 'params' | 'plot' | 'constraints' | 'assets' | 'lifecycle'

interface Props {
  novel: Novel
  /** 改完之后让上层重新取小说（侧栏、章节列表都跟着变） */
  onChanged: () => void
  onDeleted: () => void
  onOpenChapter: (cid: string) => void
}

const err = (e: unknown) => (e instanceof Error ? e.message : String(e))

/** 小说页 = 总会话：制作参数默认值 + 长期记忆（主线剧情、创作限制、资产库、人物生命周期） */
export function NovelPage({ novel, onChanged, onDeleted, onOpenChapter }: Props) {
  const pending = novel.memory.lifecycle.filter((e) => e.status === 'proposed').length
  const [tab, setTab] = useState<Tab>(pending ? 'lifecycle' : 'params')
  const [alert, setAlert] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const run = async (what: string, fn: () => Promise<unknown>) => {
    setBusy(true)
    setAlert(null)
    try {
      await fn()
      onChanged()
    } catch (e) {
      setAlert(`${what}失败：${err(e)}`)
    } finally {
      setBusy(false)
    }
  }

  const remove = () => {
    if (!confirm(`删除《${novel.title}》？全部章节、版本与长期记忆都会删掉，不可撤销。`)) return
    void deleteNovel(novel.id).then(onDeleted).catch((e) => setAlert(`删除失败：${err(e)}`))
  }

  const tabs: [Tab, string][] = [
    ['params', '制作参数'], ['plot', '主线剧情'], ['constraints', '创作限制'],
    ['assets', '资产库'], ['lifecycle', pending ? `人物生命周期（${pending} 待确认）` : '人物生命周期'],
  ]

  return (
    <section className="novel">
      <header className="novel__head">
        <h2>《{novel.title}》</h2>
        <span className="novel__meta">
          {novel.chapters.length} 章 · 已采用 {novel.chapters.filter((c) => c.adopted_version).length} 章
          · 下一章从 u{String(novel.memory.numbering.next_unit).padStart(4, '0')} /
          E{String(novel.memory.numbering.next_episode).padStart(2, '0')} 起编
        </span>
        <button className="btn btn--sm btn--ghost" onClick={remove}>删除小说</button>
      </header>
      <nav className="tabs">
        {tabs.map(([id, name]) => (
          <button key={id} className={`tabs__btn${tab === id ? ' is-on' : ''}`}
                  onClick={() => setTab(id)}>
            {name}
          </button>
        ))}
      </nav>
      {alert && <p className="alert">{alert}</p>}
      <div className="novel__body">
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

interface TabProps {
  novel: Novel
  busy: boolean
  run: (what: string, fn: () => Promise<unknown>) => Promise<void>
}

function ParamsTab({ novel, busy, run }: TabProps) {
  const [title, setTitle] = useState(novel.title)
  const [params, setParams] = useState<NovelParams>({ ...DEFAULT_PARAMS, ...novel.params })
  useEffect(() => {
    setTitle(novel.title)
    setParams({ ...DEFAULT_PARAMS, ...novel.params })
  }, [novel.id, novel.title, novel.params])
  return (
    <div className="form">
      <p className="lib__hint">本书每一章转换时都用这套参数（转换时可单独覆写旁白模式，只记在那个版本里）。</p>
      <div className="form__grid">
        <Field label="小说标题" wide>
          <input value={title} onChange={(e) => setTitle(e.target.value)} />
        </Field>
      </div>
      <ParamsForm value={params} onChange={setParams} />
      <div className="form__foot">
        <span />
        <button className="btn" disabled={busy || !title.trim()}
                onClick={() => void run('保存参数', () => updateNovel(novel.id, {
                  ...(title.trim() !== novel.title ? { title: title.trim() } : {}), params }))}>
          保存参数
        </button>
      </div>
    </div>
  )
}

function PlotTab({ novel, busy, run }: TabProps) {
  const [outline, setOutlineText] = useState(novel.memory.plot.outline)
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  useEffect(() => { setOutlineText(novel.memory.plot.outline) }, [novel.memory.plot.outline])
  const synopsis = Object.fromEntries(novel.memory.plot.chapters.map((s) => [s.chapter_id, s]))
  return (
    <div className="plot">
      <p className="lib__hint">
        主线剧情只用于让模型理解人物关系、称谓与来龙去脉；每个镜头仍必须依据本章原文，
        主线里有、本章原文里没有的情节不会被画进镜头。注入总长上限 2000 字。
      </p>
      <label className="field field--wide">
        <span>全书梗概（可空；写了模型从第一章起就知道人物最终走向）</span>
        <textarea className="ed ed--area" rows={4} value={outline}
                  onChange={(e) => setOutlineText(e.target.value)} />
      </label>
      <button className="btn btn--sm" disabled={busy || outline === novel.memory.plot.outline}
              onClick={() => void run('保存梗概', () => setOutline(novel.id, outline))}>
        保存梗概
      </button>
      <h3 className="plot__h">逐章摘要（采用版本后自动生成，可改；改过的不再被自动覆盖）</h3>
      {!novel.chapters.length && <p className="empty">还没有章节。</p>}
      <ol className="plot__list">
        {novel.chapters.map((c) => {
          const s = synopsis[c.id]
          const value = drafts[c.id] ?? s?.synopsis ?? ''
          return (
            <li key={c.id} className="plot__item">
              <div className="plot__title">
                <b>{c.title}</b>
                {s && <span className="tag">{s.origin === 'user' ? '人工' : '自动'}</span>}
                {!s && !c.adopted_version && <span className="tag tag--ghost">未采用</span>}
              </div>
              <textarea className="ed ed--area" rows={2} maxLength={200} value={value}
                        placeholder="本章剧情摘要（≤200 字）"
                        onChange={(e) => setDrafts((d) => ({ ...d, [c.id]: e.target.value }))} />
              {drafts[c.id] !== undefined && drafts[c.id] !== (s?.synopsis ?? '') && (
                <button className="btn btn--sm" disabled={busy}
                        onClick={() => void run('保存摘要', async () => {
                          await setSynopsis(novel.id, c.id, drafts[c.id])
                          setDrafts(({ [c.id]: _, ...rest }) => rest)
                        })}>
                  保存摘要
                </button>
              )}
            </li>
          )
        })}
      </ol>
    </div>
  )
}

function ConstraintsTab({ novel, busy, run }: TabProps) {
  const [text, setText] = useState('')
  const [neg, setNeg] = useState('')
  const [keywords, setKeywords] = useState('')
  const list = novel.memory.constraints
  const add = () => run('新增限制', async () => {
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
      <p className="lib__hint">
        限制约束的是画面怎么呈现，不能让原文句子消失：原文写到的仍要由镜头或旁白承载，
        只是改用侧面、遮挡、空镜或交给旁白。负面提示词由程序直接并进产物；
        关键词只扫画面描述（台词、旁白是原文，不扫），命中只提示、不打回。
      </p>
      <ul className="cons__list">
        {list.map((c) => (
          <li key={c.id} className={`cons__item${c.enabled ? '' : ' is-off'}`}>
            <label className="check">
              <input type="checkbox" checked={c.enabled} disabled={busy}
                     onChange={(e) => void run('切换限制', () =>
                       updateConstraint(novel.id, c.id, { enabled: e.target.checked }))} />
              <b>{c.text}</b>
            </label>
            {c.negative_prompt && <span className="cons__neg">负面提示词：{c.negative_prompt}</span>}
            {!!c.keywords.length && <span className="cons__kw">扫描关键词：{c.keywords.join('、')}</span>}
            <button className="hrun__del" title="删除这条限制"
                    onClick={() => confirm('删除这条限制？')
                      && void run('删除限制', () => deleteConstraint(novel.id, c.id))}>
              ×
            </button>
          </li>
        ))}
      </ul>
      {!list.length && <p className="empty">还没有创作限制。</p>}
      <div className="form cons__new">
        <Field label="规则（给模型看）" wide>
          <input value={text} placeholder="如：不出现血腥画面，暴力用侧面、遮挡或旁白交代"
                 onChange={(e) => setText(e.target.value)} />
        </Field>
        <div className="form__grid">
          <Field label="负面提示词（可空，逗号分隔）">
            <input value={neg} placeholder="血迹，伤口特写" onChange={(e) => setNeg(e.target.value)} />
          </Field>
          <Field label="扫描关键词（可空，逗号分隔）">
            <input value={keywords} placeholder="血，伤口" onChange={(e) => setKeywords(e.target.value)} />
          </Field>
        </div>
        <div className="form__foot">
          <span />
          <button className="btn btn--sm" disabled={busy || !text.trim()} onClick={() => void add()}>
            ＋ 新增限制
          </button>
        </div>
      </div>
    </div>
  )
}

function LifecycleTab({ novel, busy, run, onOpenChapter }: TabProps & {
  onOpenChapter: (cid: string) => void
}) {
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
      <p className="lib__hint">
        主线人物不可逆的状态变化（死亡、永久伤病/残疾、永久下线）。采用一章后由模型提议，
        每条都附原文逐字证据，程序核过才列出来；<b>确认后</b>才会注入后续章节的转换，
        并在已故/已下线角色出场（且没写明是回忆）时提示审阅。
      </p>
      <ul className="life__list">
        {list.map((e) => (
          <li key={e.id} className={`life__item life__item--${e.status}`}>
            <div className="life__top">
              <b>{e.character_id} {names[e.character_id] ?? ''}</b>
              <span className="tag">{label(LIFECYCLE_TYPE, e.type)}</span>
              <span className={`tag${e.status === 'proposed' ? ' tag--warn' : ''}`}>
                {label(LIFECYCLE_STATUS, e.status)}
              </span>
              <span className="tag tag--ghost">{e.origin === 'model' ? '模型提议' : '人工添加'}</span>
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
                <button className="btn btn--sm" disabled={busy}
                        onClick={() => void run('确认', () =>
                          updateLifecycle(novel.id, e.id, { status: 'confirmed' }))}>
                  确认
                </button>
              )}
              {e.status !== 'rejected' && (
                <button className="btn btn--sm btn--ghost" disabled={busy}
                        onClick={() => void run('驳回', () =>
                          updateLifecycle(novel.id, e.id, { status: 'rejected' }))}>
                  驳回
                </button>
              )}
              <button className="btn btn--sm btn--ghost" disabled={busy}
                      onClick={() => confirm('删除这条记录？')
                        && void run('删除', () => deleteLifecycle(novel.id, e.id))}>
                删除
              </button>
            </div>
          </li>
        ))}
      </ul>
      {!list.length && <p className="empty">还没有记录。采用一章后会自动提议，也可以在下面手动添加。</p>}
      <div className="form life__new">
        <div className="form__grid">
          <Field label="角色">
            <select value={who} onChange={(e) => setWho(e.target.value)}>
              <option value="">选择角色…</option>
              {chars.map((c) => <option key={c.id} value={c.id}>{c.id} {c.name}</option>)}
            </select>
          </Field>
          <Field label="类型">
            <select value={type} onChange={(e) => setType(e.target.value as LifecycleType)}>
              {Object.entries(LIFECYCLE_TYPE).map(([v, n]) => <option key={v} value={v}>{n}</option>)}
            </select>
          </Field>
          <Field label="自哪一章起">
            <select value={since} onChange={(e) => setSince(e.target.value)}>
              <option value="">（全书适用）</option>
              {novel.chapters.map((c) => <option key={c.id} value={c.id}>{c.title}</option>)}
            </select>
          </Field>
          <Field label="具体情况" wide>
            <input value={detail} placeholder="如：左腿残疾，此后拄拐"
                   onChange={(e) => setDetail(e.target.value)} />
          </Field>
        </div>
        <div className="form__foot">
          <span>{!chars.length && '资产库里还没有角色卡'}</span>
          <button className="btn btn--sm" disabled={busy || !who}
                  onClick={() => void run('添加', async () => {
                    await addLifecycle(novel.id, { character_id: who, type, detail,
                                                   chapter_id: since || null })
                    setDetail('')
                  })}>
            ＋ 手动添加（直接视为已确认）
          </button>
        </div>
      </div>
    </div>
  )
}
