/** 转换服务客户端。开发期走 vite 代理的 /api，生产可用 VITE_API_BASE 直连。 */
import type {
  AssetWork, ConvertRequest, Health, HistoryRecord, HistorySummary, Job, JobSummary,
  Storyboard,
} from './types'

const BASE = import.meta.env.VITE_API_BASE ?? '/api'

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init)
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(`${res.status} ${res.statusText}${body ? ` — ${body.slice(0, 300)}` : ''}`)
  }
  return res.json() as Promise<T>
}

export function health(): Promise<Health> {
  return req<Health>('/healthz')
}

export function submitConvert(payload: ConvertRequest): Promise<{ job_id: string }> {
  return req<{ job_id: string }>('/convert', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function getJob(jobId: string): Promise<Job> {
  return req<Job>(`/jobs/${jobId}`)
}

/** 在跑/刚结束的任务：关掉页面后靠它重新接上 */
export function listJobs(): Promise<{ jobs: JobSummary[] }> {
  return req<{ jobs: JobSummary[] }>('/jobs')
}

export const TERMINAL = ['succeeded', 'completed_with_warnings', 'failed']

/* ---------- 历史记录 ---------- */

export function listHistory(): Promise<{ runs: HistorySummary[] }> {
  return req<{ runs: HistorySummary[] }>('/history')
}

export function getHistory(id: string): Promise<HistoryRecord> {
  return req<HistoryRecord>(`/history/${id}`)
}

/** 保存人工编辑后的分镜（覆盖 result，保留创建时间与制作参数） */
export function saveHistory(id: string, doc: Storyboard): Promise<{ edited_at: string }> {
  return req<{ edited_at: string }>(`/history/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(doc),
  })
}

export function deleteHistory(id: string): Promise<{ deleted: string }> {
  return req<{ deleted: string }>(`/history/${id}`, { method: 'DELETE' })
}

export function listAssets(): Promise<{ works: AssetWork[] }> {
  return req<{ works: AssetWork[] }>('/assets')
}
