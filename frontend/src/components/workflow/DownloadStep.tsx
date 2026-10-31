/** ⑥ 下载成片：每集一张卡（成片 mp4、字幕 srt），再加合成报告；旁边「回到画布重新合成」。
 *  下载走带登录态的请求拿 blob，再用临时 <a download> 存盘。失败时在对应卡片下方说原因。 */
import { useState } from 'react'
import { Download, FileText, Film, RotateCcw } from 'lucide-react'
import { filmFileUrl } from '@/api'
import { Button } from '@/components/ui/button'
import { finalEpisodes } from '@/compose'
import { useI18n } from '@/i18n/core'
import type { MsgKey } from '@/i18n/core'
import type { ComposePreview, FilmSession, VersionRef } from '@/types'

const msg = (e: unknown) => (e instanceof Error ? e.message : String(e))

export function DownloadStep({ version, film, onOpenFilm }: {
  version: VersionRef
  film: FilmSession
  /** 合成预览（暂未使用：以后在这里显示合成报告摘要） */
  compose: ComposePreview | null
  onOpenFilm: () => void
}) {
  const { t } = useI18n()
  /** 卡片键（集号或 report）→ 失败原因 */
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState<string | null>(null)
  const episodes = finalEpisodes(film.final?.files ?? [])
  const report = film.final?.report ?? null

  const save = async (key: string, path: string) => {
    setBusy(path)
    setErrors((x) => { const next = { ...x }; delete next[key]; return next })
    try {
      const url = await filmFileUrl(version.nid, version.cid, version.vid, path)
      const a = document.createElement('a')
      a.href = url
      a.download = path.split('/').pop() ?? path
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } catch (e) {
      setErrors((x) => ({ ...x, [key]: msg(e) }))
    } finally {
      setBusy(null)
    }
  }

  const fileBtn = (key: string, path: string | undefined, text: MsgKey, Icon: typeof Download) => path && (
    <Button size="sm" variant="outline" className="gap-1.5" disabled={busy === path}
            onClick={() => void save(key, path)}>
      <Icon className="size-3.5" />{t(text)}
    </Button>
  )
  const failed = (key: string) => errors[key] && (
    <p role="alert" className="text-sm text-destructive">{t('flow.download.failed', { reason: errors[key] })}</p>
  )

  return (
    <div className="flex flex-col gap-4" data-testid="download-step">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-base font-semibold">{t('flow.download.title')}</h3>
        <Button size="sm" variant="ghost" className="gap-1.5" onClick={onOpenFilm}>
          <RotateCcw className="size-3.5" />{t('flow.download.recompose')}
        </Button>
      </div>
      <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {episodes.map((e) => (
          <li key={e.episode} className="flex flex-col gap-3 rounded-xl border bg-card p-4">
            <div className="flex items-center gap-2 font-mono text-sm font-semibold">
              <Film className="size-4 text-muted-foreground" aria-hidden />{e.episode}
            </div>
            <div className="flex flex-wrap gap-2">
              {fileBtn(e.episode, e.video, 'flow.download.mp4', Download)}
              {fileBtn(e.episode, e.srt, 'flow.download.srt', FileText)}
            </div>
            {failed(e.episode)}
          </li>
        ))}
      </ul>
      {report && (
        <div className="flex flex-col gap-2">
          <div>{fileBtn('report', report, 'flow.download.report', FileText)}</div>
          {failed('report')}
        </div>
      )}
    </div>
  )
}
