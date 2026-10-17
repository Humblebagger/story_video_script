/** 画布侧栏里的「剧情」「任务」两页：把小说页、章节页上的操作搬进画布，不必退出去再进来。
 *
 *  剧情页直接复用小说页的主线剧情与创作限制（同一套接口与说明），
 *  任务页是章节页的转换 + 版本条：重新转换时画布不关，跑完自动换成新版本。
 */
import { useState } from 'react'
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
const err = (e: unknown) => (e instanceof Error ? e.message : String(e))

export function NovelPanel({ bench }: { bench: Workbench }) {
  const [part, setPart] = useState<'plot' | 'constraints'>('plot')
  const [busy, setBusy] = useState(false)
  const [alert, setAlert] = useState<string | null>(null)
  const run = async (what: string, fn: () => Promise<unknown>) => {
    setBusy(true)
    setAlert(null)
    try {
      await fn()
      bench.onNovelChanged()
    } catch (e) {
      setAlert(`${what}失败：${err(e)}`)
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="tlc__novel">
      <div className="tlc__seg2">
        <button className={part === 'plot' ? 'is-on' : ''} onClick={() => setPart('plot')}>主线剧情</button>
        <button className={part === 'constraints' ? 'is-on' : ''}
                onClick={() => setPart('constraints')}>创作限制</button>
      </div>
      {alert && <p className="tlc__kferr">{alert}</p>}
      {part === 'plot'
        ? <PlotTab novel={bench.novel} busy={busy} run={run} />
        : <ConstraintsTab novel={bench.novel} busy={busy} run={run} />}
      <p className="tlc__kfnote">改的是整本小说的长期记忆，从下一次转换起生效；本版分镜不会自动变，要用新设定就去「任务」重新转换。</p>
    </div>
  )
}

export function TaskPanel({ bench, dirty }: { bench: Workbench; dirty: boolean }) {
  const { novel, chapter, versionId, job, converting } = bench
  const [mode, setMode] = useState<NarrationMode | ''>('')
  const [strict, setStrict] = useState(false)
  // 版本按时间正序编号 v1 v2 …（接口按时间倒序给）
  const versions = [...chapter.versions].reverse()
  const current = versions.find((v) => v.id === versionId)
  const live = job && (job.status === 'queued' || job.status === 'running') ? job : null

  return (
    <div className="tlc__tasks">
      {bench.notice && <p className="tlc__notice">{bench.notice}</p>}
      <section>
        <h4>转换</h4>
        {live ? (
          <div className="tlc__job">
            <b>{label(JOB_STATUS, live.status)}</b>
            {live.progress && <JobProgress progress={live.progress} />}
            {!!live.log.length && <code className="tlc__jobline">{live.log[live.log.length - 1]}</code>}
            <p className="tlc__kfnote">画布不用关，跑完自动换成新版本；也可以关掉画布去做别的，侧栏能点回来。</p>
          </div>
        ) : converting ? (
          <p className="tlc__kfnote">本章有转换在后台跑，跑完会出现在下面的版本里。</p>
        ) : (
          <>
            <label className="field">
              <span>旁白模式（本次）</span>
              <select value={mode} onChange={(e) => setMode(e.target.value as NarrationMode | '')}>
                <option value="">沿用小说设置（{label(NARRATION_MODE,
                  novel.params.narration_mode ?? 'selective')}）</option>
                {Object.entries(NARRATION_MODE).map(([v, n]) => <option key={v} value={v}>{n}</option>)}
              </select>
            </label>
            <label className="check" title="软质量门（旁白密度/评审分）重试耗尽时直接失败，而非择优降级交付">
              <input type="checkbox" checked={strict} onChange={(e) => setStrict(e.target.checked)} />
              严格模式
            </label>
            <button className="btn btn--sm" disabled={bench.disabled || !chapter.text.trim()}
                    onClick={() => {
                      if (dirty && !confirm('本版有未保存的修改，转换完成后画布会换成新版本。先不保存直接转换？')) return
                      bench.onConvert({ ...(mode ? { narration_mode: mode } : {}), strict })
                    }}>
              重新转换（新版本）
            </button>
            <p className="tlc__kfnote">按本章原文 + 小说当前的长期记忆（剧情、限制、资产库）重跑一遍，结果存成新版本，旧版本不动。</p>
          </>
        )}
      </section>

      <section>
        <h4>版本</h4>
        <div className="tlc__vers">
          {versions.map((v, i) => (
            <button key={v.id}
                    className={`vchip${v.id === versionId ? ' is-on' : ''}${
                      v.id === chapter.adopted_version ? ' is-adopted' : ''}`}
                    title={`${label(JOB_STATUS, v.status)} · ${v.shots} 镜`}
                    disabled={v.id === versionId}
                    onClick={() => bench.onOpenVersion(v.id)}>
              v{i + 1}{v.id === chapter.adopted_version && ' ★'}
              {!ADOPTABLE.includes(v.status) && <em>{label(JOB_STATUS, v.status)}</em>}
            </button>
          ))}
        </div>
        {current && current.id !== chapter.adopted_version && (
          <div className="tlc__kfacts">
            <button className="btn btn--sm" disabled={!ADOPTABLE.includes(current.status) || dirty}
                    title={dirty ? '先保存修改再采用'
                      : ADOPTABLE.includes(current.status) ? '把这一版写入小说的长期记忆'
                        : '只有转换成功、且编辑后仍通过复验的版本可以采用'}
                    onClick={() => bench.onAdopt(current.id)}>
              采用此版
            </button>
            <button className="btn btn--sm btn--ghost" onClick={() => bench.onDeleteVersion(current.id)}>
              删除此版
            </button>
          </div>
        )}
        {current && current.id === chapter.adopted_version && (
          <p className="tlc__kfnote">★ 采用版：资产卡、编号接续、人物状态与剧情摘要都以它为准。</p>
        )}
        {chapter.digest?.status === 'running' && <p className="tlc__kfnote">章后整理进行中（人物状态提议与本章摘要）…</p>}
      </section>
    </div>
  )
}
