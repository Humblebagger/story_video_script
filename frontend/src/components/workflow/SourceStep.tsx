/** ① 导入原文：章节标题、删除章节、原文框（字数与预计批数、读取 .txt、采用后锁定）。
 *  编辑状态在 ChapterWorkflow 里（主按钮「保存原文」要知道有没有改动），这里只显示与上报。 */
import { useRef } from 'react'
import { useI18n } from '@/i18n/core'
import { Button } from '@/components/ui/button'

export function SourceStep({ title, text, locked, onTitle, onText, onDelete }: {
  title: string
  text: string
  locked: boolean
  onTitle: (v: string) => void
  onText: (v: string) => void
  onDelete: () => void
}) {
  const { t } = useI18n()
  const fileRef = useRef<HTMLInputElement>(null)
  const chars = text.trim().length
  const batches = Math.max(1, Math.ceil(chars / 2500))
  return (
    <div className="chap__text flex flex-col gap-3">
      <header className="chap__head">
        <input className="chap__title" value={title} onChange={(e) => onTitle(e.target.value)} />
        <Button size="sm" variant="ghost" onClick={onDelete}>{t('flow.chapter.remove')}</Button>
      </header>
      <p className="text-[13px] text-muted-foreground">
        {t('flow.chapter.source')}{locked && ` · ${t('flow.chapter.locked')}`}
      </p>
      <div className="form">
        <div className="form__textbar">
          <span className="form__count">{chars ? t('flow.chapter.count', { n: chars, b: batches }) : t('flow.chapter.empty')}</span>
          {!locked && (
            <>
              <Button type="button" size="sm" variant="outline"
                      onClick={() => fileRef.current?.click()}>{t('flow.chapter.readTxt')}</Button>
              <input ref={fileRef} type="file" accept=".txt,text/plain" hidden
                     onChange={(e) => {
                       const f = e.target.files?.[0]
                       if (f) void f.text().then(onText)
                       e.target.value = ''
                     }} />
            </>
          )}
        </div>
        <textarea id="chapter-source" value={text} readOnly={locked} spellCheck={false}
                  placeholder={t('flow.chapter.placeholder')}
                  onChange={(e) => onText(e.target.value)} />
      </div>
    </div>
  )
}
