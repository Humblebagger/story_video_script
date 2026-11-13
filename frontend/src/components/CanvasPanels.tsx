/** 画布侧栏里的「剧情」「任务」两页：把小说页、章节页上的操作搬进画布，不必退出去再进来。
 *
 *  剧情页直接复用小说页的主线剧情与创作限制（同一套接口与说明），
 *  任务页是章节页的生成 + 版本条：重新生成时画布不关，跑完自动换成新版本。
 */
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { useConfirm } from '@/components/common/ConfirmDialog'
import { useI18n } from '@/i18n/core'
import { errValue, formatMsg } from '@/i18n/serverMsg'
import type { MsgLike } from '@/i18n/serverMsg'
import { cn } from '@/lib/utils'
import { JOB_STATUS, NARRATION_MODE, label } from '../labels'
import type { Chapter, Job, NarrationMode, Novel } from '../types'
import { JobProgress } from './JobProgress'
import { ConstraintsTab, PlotTab } from './NovelPage'

/** 画布所在的章节会话：有它画布才出现「剧情」「任务」两页（本地 JSON、分批预览没有） */
export interface Workbench {
  novel: Novel
  chapter: Chapter
  /** 画布上正看着的版本 */
  versionId: string | null
  /** 正附着的转换任务（可能是别的章节的） */
  job: Job | null
  /** 本章有转换在跑 */
  converting: boolean
  disabled: boolean
  onConvert: (opts: { narration_mode?: NarrationMode; strict: boolean }) => void
  onOpenVersion: (vid: string) => void
  onAdopt: (vid: string) => void
  onDeleteVersion: (vid: string) => void
  /** 改了长期记忆：让上层重新取小说 */
  onNovelChanged: () => void
  /** 上层的提示（采用结果、转换 / 删除失败等）：画布盖住了页面，要在画布里也看得到 */
  notice?: string | null
}

const ADOPTABLE = ['succeeded', 'completed_with_warnings']

export function NovelPanel({ bench }: { bench: Workbench }) {
  const { t, locale } = useI18n()
  const [part, setPart] = useState<'plot' | 'constraints'>('plot')
  const [busy, setBusy] = useState(false)
  const [alert, setAlert] = useState<{ what: string; err: MsgLike } | null>(null)
  const run = async (what: string, _done: string, fn: () => Promise<unknown>) => {
    setBusy(true)
    setAlert(null)
    try {
      await fn()
      bench.onNovelChanged()
    } catch (e) {
      setAlert({ what, err: errValue(e) })
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="tlc__novel">
      <div className="tlc__seg2 inline-flex self-start rounded-lg bg-muted p-1" role="group" aria-label={t('canvas.panel.segAria')}>
        {([['plot', t('canvas.panel.plot')], ['constraints', t('canvas.panel.constraints')]] as const).map(([id, name]) => (
          <button key={id} type="button" aria-pressed={part === id}
                  className={cn(
                    'rounded-md border-0 px-3 py-1 text-sm text-muted-foreground',
                    'transition-[color,background-color,box-shadow] duration-150 ease-out hover:text-foreground',
                    part === id && 'is-on bg-background font-medium text-foreground shadow-sm dark:bg-foreground/10',
                  )}
                  onClick={() => setPart(id)}>{name}</button>
        ))}
      </div>
      {alert && <p className="tlc__kferr">{t('canvas.panel.failedWith', { what: alert.what, error: formatMsg(alert.err, locale) })}</p>}
      {part === 'plot'
        ? <PlotTab novel={bench.novel} busy={busy} run={run} />
        : <ConstraintsTab novel={bench.novel} busy={busy} run={run} />}
      <p className="tlc__kfnote">{t('canvas.panel.note')}</p>
    </div>
  )
}

export function TaskPanel({ bench, dirty }: { bench: Workbench; dirty: boolean }) {
  const { novel, chapter, versionId, job, converting } = bench
  const { t } = useI18n()
  const [ask, confirmUi] = useConfirm()
  const [mode, setMode] = useState<NarrationMode | ''>('')
  const [strict, setStrict] = useState(false)
  // 版本按时间正序编号 v1 v2 …（接口按时间倒序给）
  const versions = [...chapter.versions].reverse()
  const current = versions.find((v) => v.id === versionId)
  const live = job && (job.status === 'queued' || job.status === 'running') ? job : null

  return (
    <div className="tlc__tasks">
      {confirmUi}
      {bench.notice && <p className="tlc__notice">{bench.notice}</p>}
      <section>
        <h4>{t('canvas.panel.generate')}</h4>
        {live ? (
          <div className="tlc__job">
            <b>{label(JOB_STATUS, live.status)}</b>
            {live.progress && <JobProgress progress={live.progress} />}
            {!!live.log.length && <code className="tlc__jobline">{live.log[live.log.length - 1]}</code>}
            <p className="tlc__kfnote">{t('canvas.panel.liveNote')}</p>
          </div>
        ) : converting ? (
          <p className="tlc__kfnote">{t('canvas.panel.bgNote')}</p>
        ) : (
          <>
            <label className="field">
              <span>{t('flow.chapter.narration')}</span>
              <select value={mode} onChange={(e) => setMode(e.target.value as NarrationMode | '')}>
                <option value="">{t('flow.chapter.narrationInherit', {
                  mode: label(NARRATION_MODE, novel.params.narration_mode ?? 'selective') })}</option>
                {Object.entries(NARRATION_MODE).map(([v, n]) => <option key={v} value={v}>{n}</option>)}
              </select>
            </label>
            <label className="check" title={t('flow.chapter.strictHint')}>
              <input type="checkbox" checked={strict} onChange={(e) => setStrict(e.target.checked)} />
              {t('flow.chapter.strict')}
            </label>
            <Button size="sm" className="self-start" disabled={bench.disabled || !chapter.text.trim()}
                    onClick={async () => {
                      if (dirty && !(await ask({ title: t('confirm.regen.title'), body: t('confirm.regen.body'),
                        action: t('confirm.regen.action') }))) return
                      bench.onConvert({ ...(mode ? { narration_mode: mode } : {}), strict })
                    }}>
              {t('canvas.panel.regen')}
            </Button>
            <p className="tlc__kfnote">{t('canvas.panel.regenNote')}</p>
          </>
        )}
      </section>

      <section>
        <h4>{t('flow.chapter.versions')}</h4>
        <div className="tlc__vers">
          {versions.map((v, i) => (
            <button key={v.id}
                    className={`vchip${v.id === versionId ? ' is-on' : ''}${
                      v.id === chapter.adopted_version ? ' is-adopted' : ''}`}
                    title={`${label(JOB_STATUS, v.status)} · ${t('flow.chapter.shots', { n: v.shots })}`}
                    disabled={v.id === versionId}
                    onClick={() => bench.onOpenVersion(v.id)}>
              v{i + 1}{v.id === chapter.adopted_version && ' ★'}
              {!ADOPTABLE.includes(v.status) && <em>{label(JOB_STATUS, v.status)}</em>}
            </button>
          ))}
        </div>
        {current && current.id !== chapter.adopted_version && (
          <div className="tlc__kfacts">
            <Button size="sm" disabled={!ADOPTABLE.includes(current.status) || dirty}
                    title={dirty ? t('canvas.panel.saveFirst')
                      : ADOPTABLE.includes(current.status) ? t('flow.chapter.adoptHint')
                        : t('canvas.panel.adoptBlocked')}
                    onClick={() => bench.onAdopt(current.id)}>
              {t('flow.chapter.adopt')}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => bench.onDeleteVersion(current.id)}>
              {t('flow.chapter.removeVersion')}
            </Button>
          </div>
        )}
        {current && current.id === chapter.adopted_version && (
          <p className="tlc__kfnote">{t('canvas.panel.adoptedNote')}</p>
        )}
        {chapter.digest?.status === 'running' && <p className="tlc__kfnote">{t('canvas.panel.digesting')}</p>}
      </section>
    </div>
  )
}
