import { useMemo, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { useI18n } from '@/i18n/core'
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
  const { t } = useI18n()
  const [title, setTitle] = useState('')
  const [params, setParams] = useState<NovelParams>(DEFAULT_PARAMS)
  const [source, setSource] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  const chapters = useMemo(() => {
    if (!source.trim()) return []
    const segs = parseChapters(source)
    // 识别不出章节标记：整篇作为第一章
    if (!segs.length) return [{ title: t('newNovel.firstChapter'), text: source.trim() }]
    return segs.map((s) => ({ title: s.title, text: source.slice(s.start, s.end).trim() }))
  }, [source, t])

  return (
    <form className="form" onSubmit={(e) => {
      e.preventDefault()
      if (title.trim()) onSubmit({ title: title.trim(), params, chapters })
    }}>
      <h2 className="form__h">{t('newNovel.heading')}</h2>
      <p className="lib__hint">{t('newNovel.hint')}</p>
      <div className="form__grid">
        <Field label={t('novel.titleLabel')} wide>
          <Input value={title} placeholder={t('newNovel.titlePh')} onChange={(e) => setTitle(e.target.value)} />
        </Field>
      </div>
      <ParamsForm value={params} onChange={setParams} />

      <div className="form__text">
        <div className="form__textbar">
          <Label>{t('newNovel.import')}</Label>
          <span className="form__count">
            {chapters.length ? t('newNovel.found', { n: chapters.length }) : t('newNovel.none')}
          </span>
          <Button type="button" variant="outline" size="sm"
                  onClick={() => fileRef.current?.click()}>{t('newNovel.readTxt')}</Button>
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
        <Textarea value={source} spellCheck={false}
                  placeholder={t('newNovel.sourcePh')}
                  onChange={(e) => setSource(e.target.value)} />
        {!!chapters.length && (
          <ol className="form__chapters">
            {chapters.map((c, i) => <li key={i}>{t('newNovel.itemChars', { title: c.title, n: c.text.length })}</li>)}
          </ol>
        )}
      </div>

      <div className="form__foot">
        <span />
        <Button type="submit" disabled={disabled || !title.trim()}>
          {chapters.length ? t('newNovel.submitN', { n: chapters.length }) : t('newNovel.submit')}
        </Button>
      </div>
    </form>
  )
}
