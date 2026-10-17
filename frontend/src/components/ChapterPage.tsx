import { useEffect, useRef, useState } from 'react'
import { JOB_STATUS, NARRATION_MODE, label } from '../labels'
import type { Chapter, NarrationMode, Novel, VersionSummary } from '../types'

interface Props {
  novel: Novel
  chapter: Chapter
  /** 正在看的版本 */
  versionId: string | null
  /** 本章有转换在跑（不论是否正看着它的任务面板） */
  converting: boolean
  disabled: boolean
  onConvert: (opts: { narration_mode?: NarrationMode; strict: boolean }) => void
  onOpenVersion: (vid: string) => void
  onAdopt: (vid: string) => void
  onDeleteVersion: (vid: string) => void
  onSaveText: (patch: { title?: string; text?: string }) => Promise<void>
  onDelete: () => void
  onRerunDigest: () => void
}

const ADOPTABLE = ['succeeded', 'completed_with_warnings']

function fmtTime(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return `${d.getMonth() + 1}/${d.getDate()} ${d.toLocaleTimeString('zh-CN', {
    hour: '2-digit', minute: '2-digit' })}`
}

/** 章节页 = 二级会话：原文 + 「转换」+ 版本切换条（每次转换一个版本，标出采用版） */
export function ChapterPage({
  novel, chapter, versionId, converting, disabled, onConvert, onOpenVersion, onAdopt,
  onDeleteVersion, onSaveText, onDelete, onRerunDigest,
}: Props) {
  const [title, setTitle] = useState(chapter.title)
  const [text, setText] = useState(chapter.text)
  const [mode, setMode] = useState<NarrationMode | ''>('')
  const [strict, setStrict] = useState(false)
  const [saving, setSaving] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  useEffect(() => {
    setTitle(chapter.title)
    setText(chapter.text)
  }, [chapter.id, chapter.title, chapter.text])

  const locked = !!chapter.adopted_version
  const dirty = title.trim() !== chapter.title || (!locked && text !== chapter.text)
  // 版本按时间正序编号 v1 v2 …（接口按时间倒序给）
  const versions: VersionSummary[] = [...chapter.versions].reverse()
  const current = versions.find((v) => v.id === versionId)
  const chars = text.trim().length
  const batches = Math.max(1, Math.ceil(chars / 2500))
  const digest = chapter.digest

  const save = async () => {
    setSaving(true)
    try {
      await onSaveText({
        ...(title.trim() !== chapter.title ? { title: title.trim() } : {}),
        ...(!locked && text !== chapter.text ? { text } : {}),
      })
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="chap">
      <header className="chap__head">
        <span className="chap__novel">《{novel.title}》</span>
        <input className="chap__title" value={title} onChange={(e) => setTitle(e.target.value)} />
        <button className="btn btn--sm btn--ghost" onClick={onDelete}>删除章节</button>
      </header>

      <details className="chap__text" open={!versions.length}>
        <summary>
          本章原文 · {chars} 字{locked && ' · 已有采用版，原文已锁定'}
        </summary>
        <div className="form">
          <div className="form__textbar">
            <span className="form__count">{chars ? `${chars} 字 · 预计 ${batches} 批` : '尚未填写'}</span>
            {!locked && (
              <>
                <button type="button" className="btn btn--sm btn--ghost"
                        onClick={() => fileRef.current?.click()}>读取 .txt</button>
                <input ref={fileRef} type="file" accept=".txt,text/plain" hidden
                       onChange={(e) => {
                         const f = e.target.files?.[0]
                         if (f) void f.text().then(setText)
                         e.target.value = ''
                       }} />
              </>
            )}
          </div>
          <textarea value={text} readOnly={locked} spellCheck={false}
                    placeholder="粘贴本章原文……转换为忠实分镜 IR：每个镜头可溯源到原文句子。"
                    onChange={(e) => setText(e.target.value)} />
          {dirty && (
            <div className="form__foot">
              <span />
              <button className="btn btn--sm" disabled={saving} onClick={() => void save()}>
                {saving ? '保存中…' : '保存章节'}
              </button>
            </div>
          )}
        </div>
      </details>

      <div className="chap__convert">
        <label className="field">
          <span>旁白模式（本次）</span>
          <select value={mode} onChange={(e) => setMode(e.target.value as NarrationMode | '')}>
            <option value="">沿用小说设置（{label(NARRATION_MODE,
              novel.params.narration_mode ?? 'selective')}）</option>
            {Object.entries(NARRATION_MODE).map(([v, n]) => <option key={v} value={v}>{n}</option>)}
          </select>
        </label>
        <label className="check" title="软质量门（旁白密度/评审分）重试耗尽时直接失败，而非择优降级交付">
          <input type="checkbox" checked={strict} onChange={(e) => setStrict(e.target.checked)} />
          严格模式
        </label>
        <button className="btn" disabled={disabled || converting || !chars || dirty}
                title={dirty ? '先保存章节再转换' : undefined}
                onClick={() => onConvert({ ...(mode ? { narration_mode: mode } : {}), strict })}>
          {converting ? '转换中…' : versions.length ? '重新转换（新版本）' : '开始转换'}
        </button>
      </div>

      {!!versions.length && (
        <div className="vbar">
          <span className="vbar__label">版本</span>
          {versions.map((v, i) => (
            <button key={v.id}
                    className={`vchip${v.id === versionId ? ' is-on' : ''}${
                      v.id === chapter.adopted_version ? ' is-adopted' : ''}`}
                    title={`${fmtTime(v.created_at)} · ${label(JOB_STATUS, v.status)} · ${v.shots} 镜`}
                    onClick={() => onOpenVersion(v.id)}>
              v{i + 1}{v.id === chapter.adopted_version && ' ★'}
              {!ADOPTABLE.includes(v.status) && <em>{label(JOB_STATUS, v.status)}</em>}
            </button>
          ))}
          {current && current.id !== chapter.adopted_version && (
            <>
              <button className="btn btn--sm" disabled={!ADOPTABLE.includes(current.status)}
                      title={ADOPTABLE.includes(current.status) ? '把这一版写入小说的长期记忆'
                        : '只有转换成功、且编辑后仍通过复验的版本可以采用'}
                      onClick={() => onAdopt(current.id)}>
                采用此版
              </button>
              <button className="btn btn--sm btn--ghost" onClick={() => onDeleteVersion(current.id)}>
                删除此版
              </button>
            </>
          )}
          {current && current.id === chapter.adopted_version && (
            <span className="vbar__note">★ 采用版：资产卡、编号接续、人物状态与剧情摘要都以它为准</span>
          )}
        </div>
      )}

      {digest && (
        <p className={`chap__digest chap__digest--${digest.status}`}>
          章后整理：{{
            running: '进行中（提取人物生命周期提议与本章摘要）…',
            done: `完成${digest.proposed ? `，${digest.proposed} 条人物状态待确认（见小说页）` : '，本章没有不可逆的人物状态变化'}${
              digest.dropped?.length ? `；${digest.dropped.length} 条提议证据不符已丢弃` : ''}${
              digest.synopsis_kept_user ? '；保留了你手改的摘要' : ''}`,
            failed: `失败（${digest.error ?? '未知原因'}）`,
            off: '已关闭（STORYBOARD_CHAPTER_DIGEST=0），可在小说页手动补',
          }[digest.status]}
          {(digest.status === 'failed' || digest.status === 'done') && (
            <button className="linkbtn" onClick={onRerunDigest}>重跑</button>
          )}
        </p>
      )}
    </section>
  )
}
