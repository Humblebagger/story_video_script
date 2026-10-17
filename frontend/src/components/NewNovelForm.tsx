import { useMemo, useRef, useState } from 'react'
import { parseChapters } from '../chapters'
import type { NovelParams } from '../types'
import { DEFAULT_PARAMS, Field, ParamsForm } from './ParamsForm'

export interface NewNovel {
  title: string
  params: NovelParams
  /** 导入整本时按章节标记拆出的各章；不导入就是空数组 */
  chapters: { title: string; text: string }[]
}

interface Props {
  disabled: boolean
  onSubmit: (n: NewNovel) => void
}

/** 新建小说（总会话）：标题 + 默认制作参数；可选导入整本 .txt，按章节标记自动拆成多章 */
export function NewNovelForm({ disabled, onSubmit }: Props) {
  const [title, setTitle] = useState('')
  const [params, setParams] = useState<NovelParams>(DEFAULT_PARAMS)
  const [source, setSource] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  const chapters = useMemo(() => {
    if (!source.trim()) return []
    const segs = parseChapters(source)
    // 识别不出章节标记：整篇作为第一章
    if (!segs.length) return [{ title: '第一章', text: source.trim() }]
    return segs.map((s) => ({ title: s.title, text: source.slice(s.start, s.end).trim() }))
  }, [source])

  return (
    <form className="form" onSubmit={(e) => {
      e.preventDefault()
      if (title.trim()) onSubmit({ title: title.trim(), params, chapters })
    }}>
      <h2 className="form__h">新建小说</h2>
      <p className="lib__hint">
        一部小说是一个总会话：资产库、人物生命周期、主线剧情、创作限制与编号接续都记在这里，
        转换任何一章都会带上；每一章是其中的二级会话，每次转换是一个版本。
      </p>
      <div className="form__grid">
        <Field label="小说标题" wide>
          <input value={title} placeholder="如：呐喊" onChange={(e) => setTitle(e.target.value)} />
        </Field>
      </div>
      <ParamsForm value={params} onChange={setParams} />

      <div className="form__text">
        <div className="form__textbar">
          <label>导入原文（可选）</label>
          <span className="form__count">
            {chapters.length ? `识别出 ${chapters.length} 章` : '不导入则先建空小说，之后逐章添加'}
          </span>
          <button type="button" className="btn btn--sm btn--ghost"
                  onClick={() => fileRef.current?.click()}>读取 .txt</button>
          <input ref={fileRef} type="file" accept=".txt,text/plain" hidden
                 onChange={(e) => {
                   const f = e.target.files?.[0]
                   if (f) {
                     void f.text().then(setSource)
                     if (!title.trim()) setTitle(f.name.replace(/\.[^.]+$/, ''))
                   }
                   e.target.value = ''
                 }} />
        </div>
        <textarea value={source} spellCheck={false}
                  placeholder="粘贴整本或若干章原文，按「第N章」「一 二 三」等章节标记自动拆成多章"
                  onChange={(e) => setSource(e.target.value)} />
        {!!chapters.length && (
          <ol className="form__chapters">
            {chapters.map((c, i) => <li key={i}>{c.title} · {c.text.length} 字</li>)}
          </ol>
        )}
      </div>

      <div className="form__foot">
        <span />
        <button className="btn" type="submit" disabled={disabled || !title.trim()}>
          {chapters.length ? `建小说并导入 ${chapters.length} 章` : '建小说'}
        </button>
      </div>
    </form>
  )
}
