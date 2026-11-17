/** 拉片表：每镜一行、按集分组的只读总表（设计 docs/specs/2026-11-17-shot-breakdown-sheet-design.md §3）。
 *  列：镜号与时长、关键帧、景别、运镜 / 角度、画面、台词 / 旁白、视频提示词。
 *  视频提示词取出片会话里这一镜所在的段，同一集内相邻的同段镜头合并成一格；点行跳到镜头视图。
 *  分组与合并的计算在 shotSheet.ts；关键帧图与镜头视图共用 useShotImages（只读已上传的图）。 */
import { useMemo, useState } from 'react'
import { useI18n } from '@/i18n/core'
import { cn } from '@/lib/utils'
import { DIALOGUE_TYPE, label, SHOT_SIZE } from '../labels'
import type { Index } from '../resolve'
import { cameraText, needsFold, sheetGroups } from '../shotSheet'
import type { FilmSession, Storyboard, VersionRef } from '../types'
import { useShotImages } from '../useShotImages'

interface Props {
  doc: Storyboard
  idx: Index
  /** 出片会话：没有时提示词列显示「未规划」 */
  film?: FilmSession | null
  /** 产物所属的章节版本：取关键帧图用；没有就都显示「无图」 */
  version?: VersionRef | null
  /** 变了就重取关键帧图（画布关上时） */
  imagesKey?: unknown
  /** 点一行：跳到镜头视图并选中这一镜 */
  onJump: (shotId: string) => void
}

const COLS = ['shot', 'frame', 'size', 'camera', 'action', 'voice', 'prompt'] as const
const DASH = '—'
const sec = (n: unknown) => (typeof n === 'number' ? `${Number(n.toFixed(1))}s` : '')

export function ShotSheet({ doc, idx, film = null, version = null, imagesKey, onJump }: Props) {
  const { t } = useI18n()
  const groups = useMemo(() => sheetGroups(doc, film), [doc, film])
  const urls = useShotImages(version, imagesKey)
  /** 展开了提示词的段 */
  const [open, setOpen] = useState<Set<string>>(new Set())
  const toggle = (clipId: string) => setOpen((prev) => {
    const next = new Set(prev)
    if (next.has(clipId)) next.delete(clipId); else next.add(clipId)
    return next
  })
  const [w, h] = (doc.meta?.video?.aspect_ratio ?? '16:9').split(':').map(Number)
  const thumb = {
    className: cn('sheet__thumb', h > w && 'sheet__thumb--tall'),
    style: { aspectRatio: w > 0 && h > 0 ? `${w} / ${h}` : '16 / 9' },
  }

  return (
    <div className="sheet">
      <div className="sheet__wrap" role="region" aria-label={t('board.sheet.aria')} tabIndex={0}>
        <table className="sheet__table">
          <thead>
            <tr>
              {COLS.map((c) => (
                <th key={c} scope="col" className={`sheet__col-${c}`}>{t(`board.sheet.col.${c}`)}</th>
              ))}
            </tr>
          </thead>
          {groups.map(({ ep, rows }) => (
            <tbody key={ep.id}>
              <tr className="sheet__ep">
                <th colSpan={COLS.length} scope="rowgroup">
                  <span className="sheet__ep-id">{ep.id}</span>
                  {ep.title && <span className="sheet__ep-title">{ep.title}</span>}
                  <span className="sheet__ep-n">{t('board.ep.count', { n: rows.length })}</span>
                </th>
              </tr>
              {rows.map(({ shot: s, clip, span }) => {
                const voiced = !!s.dialogue?.length || !!s.narration?.text
                const opened = !!clip && open.has(clip.id)
                return (
                  <tr key={s.id} className="sheet__row" data-shot={s.id} onClick={() => onJump(s.id)}>
                    <td>
                      {/* 点击冒泡到行上；按钮只为了键盘能聚焦、回车能跳 */}
                      <button type="button" className="sheet__id" title={t('board.sheet.jump')}>{s.id}</button>
                      <span className="sheet__dur">{sec(s.duration_sec)}</span>
                    </td>
                    <td>
                      {urls[s.id]
                        ? <img {...thumb} src={urls[s.id]} alt="" />
                        : <span {...thumb} className={cn(thumb.className, 'sheet__thumb--empty')}>{t('board.sheet.noFrame')}</span>}
                    </td>
                    <td>{label(SHOT_SIZE, s.shot_size) || DASH}</td>
                    <td>{cameraText(s) || DASH}</td>
                    <td>
                      <p className="sheet__action">{s.action}</p>
                      {s.atmosphere && <p className="sheet__atmo">{s.atmosphere}</p>}
                    </td>
                    <td>
                      {(s.dialogue ?? []).map((d, i) => (
                        <p key={i} className="sheet__line">
                          {d.character_ref && <b>{idx.assetName(d.character_ref)}</b>}
                          {d.type && d.type !== 'dialogue' && <span className="chip">{label(DIALOGUE_TYPE, d.type)}</span>}
                          <span>{d.text}</span>
                        </p>
                      ))}
                      {s.narration?.text && (
                        <p className="sheet__line sheet__line--nar">
                          <b>{t('shot.narrator')}</b>
                          <span>{s.narration.text}</span>
                        </p>
                      )}
                      {!voiced && DASH}
                    </td>
                    {span > 0 && (
                      // 提示词格可能跨几镜，点它跳哪一镜有歧义：不参与跳转
                      <td className="sheet__promptcell" rowSpan={span} onClick={(e) => e.stopPropagation()}>
                        {clip ? (
                          <>
                            <p className="sheet__clip">{clip.id} · {sec(clip.duration)}</p>
                            <p className={cn('sheet__prompt', opened && 'is-open')}>{clip.prompt}</p>
                            {needsFold(clip.prompt) && (
                              <button type="button" className="sheet__more" aria-expanded={opened}
                                      onClick={() => toggle(clip.id)}>
                                {t(opened ? 'board.sheet.less' : 'board.sheet.more')}
                              </button>
                            )}
                          </>
                        ) : <span className="sheet__none">{t('board.sheet.unplanned')}</span>}
                      </td>
                    )}
                  </tr>
                )
              })}
            </tbody>
          ))}
        </table>
      </div>
    </div>
  )
}
