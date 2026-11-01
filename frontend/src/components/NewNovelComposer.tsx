import { forwardRef, useImperativeHandle, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { motion } from 'motion/react'
import { ArrowRight, FileUp, Layers, Palette, Mic, RectangleVertical } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { useI18n } from '@/i18n/core'
import { useMotionPresets } from '@/motion'
import { parseChapters } from '../chapters'
import { ART_STYLES, TTS_VOICES } from '../presets'
import type { NovelParams } from '../types'
import { MoreParams } from './params/MoreParams'
import { NarrationPick } from './params/NarrationPick'
import { ParamChip } from './params/ParamChip'
import { RatioPicker } from './params/RatioPicker'
import { StylePicker } from './params/StylePicker'
import { VoicePicker } from './params/VoicePicker'
import { DEFAULT_PARAMS } from './ParamsForm'

export interface NewNovel {
  title: string
  params: NovelParams
  /** 导入整本时按章节标记拆出的各章；不导入就是空数组 */
  chapters: { title: string; text: string }[]
}

export interface ComposerHandle {
  /** 打开「更多」浮层并聚焦风格前缀输入框 */
  openMore: () => void
}

interface Props {
  disabled: boolean
  onSubmit: (n: NewNovel) => void
  /** 受控参数（不传则组件自管） */
  params?: NovelParams
  onParamsChange?: (next: NovelParams) => void
}

const COLLAPSE_AT = 4

/** 新建小说主卡片：无边框标题、旁白/剧情二选一、原文框（可拖入 .txt）、章节标签、底部参数胶囊与创建按钮 */
export const NewNovelComposer = forwardRef<ComposerHandle, Props>(function NewNovelComposer(
  { disabled, onSubmit, params: paramsProp, onParamsChange }, ref,
) {
  const { t } = useI18n()
  const m = useMotionPresets()
  const [title, setTitle] = useState('')
  const [own, setOwn] = useState<NovelParams>(DEFAULT_PARAMS)
  const params = paramsProp ?? own
  const setParams = (n: NovelParams) => { if (paramsProp === undefined) setOwn(n); onParamsChange?.(n) }
  const [source, setSource] = useState('')
  const [expanded, setExpanded] = useState(false)
  const [dropping, setDropping] = useState(false)
  const [moreOpen, setMoreOpen] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const areaRef = useRef<HTMLTextAreaElement>(null)
  const prefixRef = useRef<HTMLInputElement>(null)
  const dragDepth = useRef(0)

  useImperativeHandle(ref, () => ({
    openMore: () => {
      setMoreOpen(true)
      setTimeout(() => prefixRef.current?.focus(), 80)
    },
  }), [])

  const chapters = useMemo(() => {
    if (!source.trim()) return []
    const segs = parseChapters(source)
    // 识别不出章节标记：整篇作为第一章
    if (!segs.length) return [{ title: t('composer.firstChapter'), text: source.trim() }]
    return segs.map((s) => ({ title: s.title, text: source.slice(s.start, s.end).trim() }))
  }, [source, t])

  // 原文框随内容增高，最高 360px 之后滚动
  useLayoutEffect(() => {
    const el = areaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 360)}px`
  }, [source])

  const canSubmit = !disabled && !!title.trim()
  const submit = () => {
    if (canSubmit) onSubmit({ title: title.trim(), params, chapters })
  }

  const readFile = (f: File) => {
    void f.text().then(setSource)
    setTitle((cur) => cur.trim() ? cur : f.name.replace(/\.[^.]+$/, ''))
  }

  const hasFiles = (e: React.DragEvent) => !!e.dataTransfer && [...(e.dataTransfer.types ?? [])].includes('Files')
  const shown = expanded ? chapters : chapters.slice(0, COLLAPSE_AT)
  const hidden = chapters.length - COLLAPSE_AT
  const styleLabel = ART_STYLES.find((a) => a.value === params.art_style)?.label ?? params.art_style
  const voiceLabel = TTS_VOICES.find((v) => v.value === params.tts_voice)?.label ?? params.tts_voice

  return (
    <motion.section className="mx-auto w-full max-w-[760px]" {...m.enter}>
      <form className="composer relative rounded-2xl border bg-card shadow-sm" data-drop={dropping ? 'on' : undefined}
            onSubmit={(e) => { e.preventDefault(); submit() }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); submit() }
            }}
            onDragEnter={(e) => { if (hasFiles(e)) { e.preventDefault(); dragDepth.current++; setDropping(true) } }}
            onDragOver={(e) => { if (hasFiles(e)) e.preventDefault() }}
            onDragLeave={(e) => {
              if (!hasFiles(e)) return
              dragDepth.current = Math.max(0, dragDepth.current - 1)
              if (!dragDepth.current) setDropping(false)
            }}
            onDrop={(e) => {
              e.preventDefault()
              dragDepth.current = 0
              setDropping(false)
              const f = e.dataTransfer?.files?.[0]
              if (f) readFile(f)
            }}>
        {dropping && (
          <div className="composer__drop pointer-events-none absolute inset-0 z-10 flex items-center justify-center rounded-2xl text-sm font-semibold">
            {t('composer.dropHint')}
          </div>
        )}
        <div className="flex flex-col gap-3 p-4 pb-3">
          <input value={title} placeholder={t('composer.titlePh')} aria-label={t('composer.titleAria')}
                 onChange={(e) => setTitle(e.target.value)}
                 className="w-full border-0 bg-transparent text-[18px] font-semibold outline-none placeholder:text-muted-foreground/70" />
          <NarrationPick value={params} onChange={setParams} />
          <div className="form__text">
            <Textarea ref={areaRef} value={source} spellCheck={false} data-testid="composer-source"
                      aria-label={t('composer.sourceAria')}
                      placeholder={t('composer.sourcePh')}
                      onChange={(e) => setSource(e.target.value)}
                      className="min-h-40 resize-none border-0 bg-transparent px-0 shadow-none focus-visible:ring-0 dark:bg-transparent" />
          </div>
          {!!chapters.length && (
            <div className="flex flex-wrap items-center gap-1.5 text-xs" data-testid="chapter-list">
              <span className="text-muted-foreground">{t('composer.found', { n: chapters.length })}</span>
              {shown.map((c, i) => (
                <span key={i} data-testid="chapter-chip"
                      className="rounded-full bg-muted px-2.5 py-1 tabular-nums">
                  {t('composer.chip', { title: c.title, n: c.text.length.toLocaleString('en-US') })}
                </span>
              ))}
              {hidden > 0 && (
                <button type="button" data-testid="chapter-more" aria-expanded={expanded}
                        aria-label={expanded ? t('composer.lessAria') : t('composer.moreAria')}
                        onClick={() => setExpanded((v) => !v)}
                        className="rounded-full border px-2.5 py-1 tabular-nums outline-none hover:border-ring focus-visible:ring-2 focus-visible:ring-ring/50">
                  {expanded ? '−' : t('composer.more', { n: hidden })}
                </button>
              )}
            </div>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2 border-t px-4 py-3">
          <div className="flex flex-wrap items-center gap-2">
            <ParamChip testId="chip-ratio" icon={<RectangleVertical />} label={t('composer.chipRatio')} value={params.aspect_ratio}>
              <RatioPicker value={params} onChange={setParams} />
            </ParamChip>
            <ParamChip testId="chip-style" icon={<Palette />} label={t('composer.chipStyle')} value={styleLabel}>
              <StylePicker compact value={params} onChange={setParams}
                           onCustom={() => { setMoreOpen(true); setTimeout(() => prefixRef.current?.focus(), 80) }} />
            </ParamChip>
            <ParamChip testId="chip-voice" icon={<Mic />} label={t('composer.chipVoice')} value={voiceLabel}>
              <VoicePicker value={params} onChange={setParams} />
            </ParamChip>
            <ParamChip testId="chip-more" icon={<Layers />} label={t('composer.chipMore')} value=""
                       open={moreOpen} onOpenChange={setMoreOpen}>
              <MoreParams value={params} onChange={setParams} prefixRef={prefixRef} />
            </ParamChip>
          </div>
          <div className="ml-auto flex items-center gap-2">
            {!title.trim() && <span className="text-xs text-muted-foreground">{t('composer.needTitle')}</span>}
            <Button type="button" variant="ghost" size="sm" onClick={() => fileRef.current?.click()}>
              <FileUp />{t('composer.readTxt')}
            </Button>
            <input ref={fileRef} type="file" accept=".txt,text/plain" hidden
                   onChange={(e) => {
                     const f = e.target.files?.[0]
                     if (f) readFile(f)
                     e.target.value = ''
                   }} />
            <Button type="submit" data-testid="composer-submit" disabled={!canSubmit}>
              {chapters.length ? t('composer.submitN', { n: chapters.length }) : t('composer.submit')}
              <ArrowRight />
            </Button>
          </div>
        </div>
      </form>
    </motion.section>
  )
})
