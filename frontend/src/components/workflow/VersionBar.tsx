/** 版本条（每次生成一个版本，标出采用版；采用此版 / 删除此版）与章后整理的结果（含「重跑」）。②–⑥ 都显示。 */
import { useI18n } from '@/i18n/core'
import { JOB_STATUS, label } from '@/labels'
import type { Chapter, VersionSummary } from '@/types'

const ADOPTABLE = ['succeeded', 'completed_with_warnings']

function fmtTime(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return `${d.getMonth() + 1}/${d.getDate()} ${d.toLocaleTimeString('zh-CN', {
    hour: '2-digit', minute: '2-digit' })}`
}

export function VersionBar({ chapter, versionId, onOpenVersion, onAdopt, onDeleteVersion, onRerunDigest }: {
  chapter: Chapter
  /** 正在看的版本 */
  versionId: string | null
  onOpenVersion: (vid: string) => void
  onAdopt: (vid: string) => void
  onDeleteVersion: (vid: string) => void
  onRerunDigest: () => void
}) {
  const { t } = useI18n()
  // 版本按时间正序编号 v1 v2 …（接口按时间倒序给）
  const versions: VersionSummary[] = [...chapter.versions].reverse()
  const current = versions.find((v) => v.id === versionId)
  const digest = chapter.digest
  const digestText = (d: NonNullable<Chapter['digest']>) => ({
    running: t('flow.digest.running'),
    done: `${t('flow.digest.done')}${d.proposed ? t('flow.digest.proposed', { n: d.proposed }) : t('flow.digest.none')}${
      d.dropped?.length ? t('flow.digest.dropped', { n: d.dropped.length }) : ''}${
      d.synopsis_kept_user ? t('flow.digest.keptUser') : ''}`,
    failed: t('flow.digest.failed', { reason: d.error ?? t('flow.digest.unknown') }),
    off: t('flow.digest.off'),
  }[d.status])
  return (
    <>
      {!!versions.length && (
        <div className="vbar">
          <span className="vbar__label">{t('flow.chapter.versions')}</span>
          {versions.map((v, i) => (
            <button key={v.id}
                    className={`vchip${v.id === versionId ? ' is-on' : ''}${
                      v.id === chapter.adopted_version ? ' is-adopted' : ''}`}
                    title={`${fmtTime(v.created_at)} · ${label(JOB_STATUS, v.status)} · ${t('flow.chapter.shots', { n: v.shots })}`}
                    onClick={() => onOpenVersion(v.id)}>
              v{i + 1}{v.id === chapter.adopted_version && ' ★'}
              {!ADOPTABLE.includes(v.status) && <em>{label(JOB_STATUS, v.status)}</em>}
            </button>
          ))}
          {current && current.id !== chapter.adopted_version && (
            <>
              <button className="btn btn--sm" disabled={!ADOPTABLE.includes(current.status)}
                      title={ADOPTABLE.includes(current.status) ? t('flow.chapter.adoptHint')
                        : t('flow.chapter.adoptBlocked')}
                      onClick={() => onAdopt(current.id)}>
                {t('flow.chapter.adopt')}
              </button>
              <button className="btn btn--sm btn--ghost" onClick={() => onDeleteVersion(current.id)}>
                {t('flow.chapter.removeVersion')}
              </button>
            </>
          )}
          {current && current.id === chapter.adopted_version && (
            <span className="vbar__note">{t('flow.chapter.adoptedNote')}</span>
          )}
        </div>
      )}
      {digest && (
        <p className={`chap__digest chap__digest--${digest.status}`}>
          {t('flow.digest.label')}{digestText(digest)}
          {(digest.status === 'failed' || digest.status === 'done') && (
            <button className="linkbtn" onClick={onRerunDigest}>{t('flow.digest.rerun')}</button>
          )}
        </p>
      )}
    </>
  )
}
