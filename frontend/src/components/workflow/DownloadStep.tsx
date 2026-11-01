/** ⑥ 下载成片：每集一张卡（成片 mp4、字幕 srt），再加合成报告；旁边「回到画布重新合成」。
 *  下载走带登录态的请求拿 blob，再用临时 <a download> 存盘。失败时在对应卡片下方说原因。 */
import { useState } from 'react'
import { Download, FileText, Film, Loader2, PackageOpen, RotateCcw } from 'lucide-react'
import { downloadUrl, exportFcpxml, filmFileUrl } from '@/api'
import { Button } from '@/components/ui/button'
import { finalEpisodes } from '@/compose'
import { useI18n } from '@/i18n/core'
import { notice } from '@/lib/notice'
import type { MsgKey } from '@/i18n/core'
import type { ComposePreview, FilmSession, VersionRef } from '@/types'

const msg = (e: unknown) => (e instanceof Error ? e.message : String(e))

export function DownloadStep({ version, film, compose, onOpenFilm }: {
  version: VersionRef
  film: FilmSession
  /** 合成预览：用它的 exportable / export_reason 决定导出按钮 */
  compose: ComposePreview | null
  onOpenFilm: () => void
}) {
  const { t } = useI18n()
  /** 卡片键（集号或 report）→ 失败原因 */
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState<string | null>(null)
  const [exporting, setExporting] = useState(false)
  const episodes = finalEpisodes(film.final?.files ?? [])
  const report = film.final?.report ?? null

  const save = async (key: string, path: string) => {
    setBusy(path)
    setErrors((x) => { const next = { ...x }; delete next[key]; return next })
    try {
      const url = await filmFileUrl(version.nid, version.cid, version.vid, path)
      downloadUrl(url, path.split('/').pop() ?? path)
    } catch (e) {
      setErrors((x) => ({ ...x, [key]: msg(e) }))
    } finally {
      setBusy(null)
    }
  }

  const exportable = compose?.exportable === true
  const reason = compose?.export_reason ?? (compose ? 'none' : null)
  const doExport = async () => {
    setExporting(true)
    try {
      await exportFcpxml(version.nid, version.cid, version.vid)
    } catch (e) {
      notice.err(t('flow.export.failed', { reason: msg(e) }))
    } finally {
      setExporting(false)
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
      <div className="flex flex-col gap-1.5">
        <div>
          <Button size="sm" variant="outline" className="gap-1.5" data-testid="export-fcpxml"
                  disabled={!exportable || exporting} onClick={() => void doExport()}>
            {exporting ? <Loader2 className="size-3.5 animate-spin" /> : <PackageOpen className="size-3.5" />}
            {exporting ? t('flow.export.busy') : t('flow.export.button')}
          </Button>
        </div>
        <p className="text-xs text-muted-foreground" data-testid="export-hint">
          {exportable || !reason ? t('flow.export.hint') : t(`flow.export.reason.${reason}` as MsgKey)}
        </p>
      </div>
      {report && (
        <div className="flex flex-col gap-2">
          <div>{fileBtn('report', report, 'flow.download.report', FileText)}</div>
          {failed('report')}
        </div>
      )}
    </div>
  )
}
