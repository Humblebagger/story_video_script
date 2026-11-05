/** 助手任务卡：按任务种类显示进度，结束后给跳转；导出就是一个下载按钮。只在挂载（面板显示）时轮询。 */
import { useState } from 'react'
import { Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { exportFcpxml } from '@/api'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/i18n/core'
import type { MsgKey } from '@/i18n/core'
import { useTaskView } from '@/lib/assistantTask'
import type { TaskView } from '@/lib/assistantTask'
import type { AssistantGoto, AssistantStep, AssistantTask } from '@/types'

/** 结束后去哪一步：分镜生成完去检查，出片去出片，合成完去下载（失败回合成） */
const NEXT: Record<AssistantTask['kind'], AssistantStep> = { job: 'review', film: 'render', compose: 'download', export: 'download', edit: 'review' }

function taskText(t: (k: MsgKey, v?: Record<string, string | number>) => string, kind: AssistantTask['kind'], v: TaskView): string {
  if (v.state === 'loading') return t('assistant.task.loading')
  if (v.state === 'gone') return t('assistant.task.gone')
  const msg = v.error || t('assistant.task.unknownError')
  if (kind === 'job') {
    if (v.state === 'running') return v.pct == null ? t('assistant.task.jobStarting') : t('assistant.task.jobRunning', { pct: v.pct })
    return v.state === 'ok' ? t('assistant.task.jobOk') : t('assistant.task.jobFailed', { msg })
  }
  if (kind === 'film') {
    const n = { done: v.done ?? 0, total: v.total ?? 0, flying: v.flying ?? 0, failed: v.failed ?? 0 }
    return t(v.state === 'running' ? 'assistant.task.filmRunning' : v.state === 'ok' ? 'assistant.task.filmOk' : 'assistant.task.filmFailed', n)
  }
  if (v.state === 'running') return t('assistant.task.composeRunning', { step: v.step ? t('common.paren', { text: v.step }) : '' })
  return v.state === 'ok' ? t('assistant.task.composeOk') : t('assistant.task.composeFailed', { msg })
}

export function TaskCard({ novelId, task, chapter, onGoto }: {
  novelId: string
  task: AssistantTask
  chapter: string
  onGoto: (g: AssistantGoto) => void
}) {
  const { t } = useI18n()
  const v = useTaskView(novelId, task)
  const [saving, setSaving] = useState(false)

  if (task.kind === 'export') {
    const save = async () => {
      setSaving(true)
      try {
        await exportFcpxml(novelId, task.chapter_id, task.version_id ?? '')
      } catch (e) {
        toast.error(t('assistant.task.downloadFailed', { msg: e instanceof Error ? e.message : String(e) }))
      } finally {
        setSaving(false)
      }
    }
    return (
      <Button variant="outline" size="sm" className="self-start" disabled={saving} data-testid="assistant-download"
              onClick={() => void save()}>
        {saving && <Loader2 className="size-3 animate-spin" />}
        {t('assistant.task.download')}
      </Button>
    )
  }

  const running = v.state === 'loading' || v.state === 'running'
  const step: AssistantStep = task.kind === 'compose' && v.state === 'failed' ? 'compose' : NEXT[task.kind]
  return (
    <div className="assistant__task" data-testid="assistant-task" data-state={v.state}>
      <span className="inline-flex items-center gap-1">
        {running && <Loader2 className="size-3 animate-spin" />}
        {taskText(t, task.kind, v)}
      </span>
      {!running && (
        <Button variant="outline" size="sm" className="self-start" data-testid="assistant-task-goto"
                onClick={() => onGoto({ chapter_id: task.chapter_id, step })}>
          {t('assistant.goto', { chapter, step: t(`flow.steps.${step}` as MsgKey) })}
        </Button>
      )}
    </div>
  )
}
