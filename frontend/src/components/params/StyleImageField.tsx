/** 设置页的「风格参考图」框：空着是虚线框（点选或拖入），有图显示缩略图与替换 / 删除。前端先按后端同样的规则校验。 */
import { useRef, useState } from 'react'
import { ImagePlus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useConfirm } from '@/components/common/ConfirmDialog'
import { useI18n } from '@/i18n/core'
import { notice } from '@/lib/notice'
import { cn } from '@/lib/utils'
import { deleteStyleImage, uploadStyleImage } from '../../api'
import type { StyleImageMeta } from '../../types'

const TYPES = ['image/png', 'image/jpeg', 'image/webp']
const MAX_BYTES = 8 * 1024 * 1024
const err = (e: unknown) => (e instanceof Error ? e.message : String(e))

interface Props {
  nid: string
  meta: StyleImageMeta | null | undefined
  /** 已取到的图片 blob URL */
  url: string | null
  onChanged: (meta: StyleImageMeta | null) => void
}

export function StyleImageField({ nid, meta, url, onChanged }: Props) {
  const { t } = useI18n()
  const [ask, confirmUi] = useConfirm()
  const [busy, setBusy] = useState(false)
  const [over, setOver] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const upload = async (file: File | undefined | null) => {
    if (!file) return
    if (!TYPES.includes(file.type)) { notice.err(t('style.ref.badType')); return }
    if (file.size > MAX_BYTES) { notice.err(t('style.ref.tooBig')); return }
    setBusy(true)
    try {
      const m = await uploadStyleImage(nid, file)
      notice.ok(t('style.ref.uploaded'))
      onChanged(m)
    } catch (e) {
      notice.err(t('style.ref.title'), err(e))
    } finally { setBusy(false) }
  }
  const remove = async () => {
    if (!(await ask({ title: t('style.ref.confirmTitle'), body: t('style.ref.confirmBody'),
                      action: t('style.ref.remove'), danger: true }))) return
    setBusy(true)
    try {
      await deleteStyleImage(nid)
      notice.ok(t('style.ref.removed'))
      onChanged(null)
    } catch (e) {
      notice.err(t('style.ref.title'), err(e))
    } finally { setBusy(false) }
  }
  const pick = () => fileRef.current?.click()
  const input = (
    <input ref={fileRef} type="file" accept={TYPES.join(',')} hidden data-testid="style-file"
           onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ''; void upload(f) }} />
  )

  if (!meta) {
    return (
      <div>
        <button type="button" data-testid="style-drop" disabled={busy} onClick={pick}
                aria-label={t('style.ref.aria')}
                onDragOver={(e) => { e.preventDefault(); setOver(true) }}
                onDragLeave={() => setOver(false)}
                onDrop={(e) => { e.preventDefault(); setOver(false); void upload(e.dataTransfer?.files?.[0]) }}
                className={cn('styleimg__drop', over && 'styleimg__drop--over')}>
          <ImagePlus className="size-5" aria-hidden />
          <span>{t('style.ref.drop')}</span>
        </button>
        {input}
        {confirmUi}
      </div>
    )
  }
  return (
    <div className="styleimg" data-testid="style-has">
      <div className="styleimg__row">
        {url && <img className="styleimg__thumb" src={url} alt={t('style.ref.title')} />}
        <div className="flex gap-2">
          <Button size="sm" variant="outline" disabled={busy} onClick={pick} data-testid="style-replace">
            {t('style.ref.replace')}
          </Button>
          <Button size="sm" variant="outline" disabled={busy} onClick={() => void remove()} data-testid="style-remove">
            {t('style.ref.remove')}
          </Button>
        </div>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">{t('style.ref.note')}</p>
      {input}
      {confirmUi}
    </div>
  )
}
