/** 片段播放窗口：带声音与控制条（节点图卡片、出片页的选中段、完成通知都从这里播）。
 *  文件走 useFilm 的同一套 blob 缓存（ensure / files），和卡片封面、侧栏里的小播放器取的是同一份。
 *  target 为 null 时关着；attempt 不给就播采用的那次，没有采用播最近成功的一次。 */
import { useEffect, useRef } from 'react'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useI18n } from '@/i18n/core'
import { freeNodes, playableAttempt } from '../film'
import { restoreFocus } from '../playerFocus'
import type { Film } from '../useFilm'

export interface PlayTarget { id: string; attempt?: number }

export function ClipPlayer({ film, target, onClose }: {
  film: Film; target: PlayTarget | null; onClose: () => void
}) {
  const { t } = useI18n()
  const s = film.session
  /** 关窗时 target 已是 null：记下最后一次的 id 给回退用 */
  const lastId = useRef<string | undefined>(undefined)
  if (target) lastId.current = target.id
  const item = target && s ? [...s.clips, ...freeNodes(s)].find((x) => x.id === target.id) : undefined
  const hit = item ? playableAttempt(item, target?.attempt) : null
  const file = hit?.attempt.file ?? null
  const { ensure } = film
  useEffect(() => { ensure(file) }, [file, ensure])
  // 关窗后把焦点还回去（Radix 的 onCloseAutoFocus 之外再兜一次：它的时机依赖卸载顺序，这里按 target 变空来触发）
  const open = !!target
  const wasOpen = useRef(false)
  useEffect(() => {
    if (wasOpen.current && !open) {
      const id = setTimeout(() => restoreFocus(lastId.current), 0)
      wasOpen.current = false
      return () => clearTimeout(id)
    }
    wasOpen.current = open
  }, [open])
  const url = file ? film.files[file] : undefined
  return (
    <Dialog open={!!target} onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent className="sm:max-w-3xl" data-testid="clip-player"
                     onCloseAutoFocus={(e) => { e.preventDefault(); restoreFocus(target?.id ?? lastId.current) }}>
        <DialogHeader>
          <DialogTitle>
            {target && hit ? t('film.play.title', { id: target.id, n: hit.index + 1 }) : target?.id ?? ''}
            {hit?.attempt.late && <span className="ml-2 text-xs font-normal text-muted-foreground">{t('film.lateTag')}</span>}
          </DialogTitle>
          <DialogDescription className="sr-only">{t('film.play.desc')}</DialogDescription>
        </DialogHeader>
        {url
          ? <video className="film__video film__video--big" src={url} controls autoPlay playsInline />
          : <p className="tlc__kfnote">{t(!s || !item || file ? 'film.play.loading' : 'film.play.none')}</p>}
      </DialogContent>
    </Dialog>
  )
}
