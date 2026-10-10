/** 转换服务客户端。开发期走 vite 代理的 /api，生产可用 VITE_API_BASE 直连。
 *
 *  除注册/登录外的所有接口都要带 token；后端按 token 判定身份，
 *  各人只看得到自己的历史记录与资产库。
 */
import { getToken, notifyUnauthorized } from './auth'
import type { User } from './auth'
import type {
  RenderPack,
  ConvertRequest, Health, HistoryRecord, HistorySummary, Job, JobStatus, JobSummary,
  LibraryWork, Storyboard, VerificationReport,
} from './types'

/** 带结构化 detail 的接口错误。
 *
 *  服务端拒绝付费渲染时返回的是 {message, verification} 对象而不是字符串，
 *  以前一律 String() 之后用户只看得到 "[object Object]"。 */
export class ApiError extends Error {
  readonly status: number
  readonly detail: unknown
  constructor(message: string, status: number, detail: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }

  /** 服务端在 detail 里附的验证报告（渲染门拦截时有） */
  get verification(): VerificationReport | null {
    const d = this.detail
    if (d && typeof d === 'object' && 'verification' in d) {
      return (d as { verification: VerificationReport }).verification
    }
    return null
  }
}

const BASE = import.meta.env.VITE_API_BASE ?? '/api'

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken()
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      ...(init?.headers ?? {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  })
  if (res.status === 401) {
    notifyUnauthorized()          // 广播出去，让 App 退回登录页
    throw new Error('未登录或登录已过期')
  }
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    const fallback = body.slice(0, 300)
    let detail: unknown = fallback
    try { detail = JSON.parse(body).detail ?? fallback } catch { /* 非 JSON 就原样显示 */ }
    const message = typeof detail === 'string' ? detail
      : (detail && typeof detail === 'object' && typeof (detail as { message?: unknown }).message === 'string'
        ? (detail as { message: string }).message
        : fallback)
    throw new ApiError(message || `${res.status} ${res.statusText}`, res.status, detail)
  }
  return res.json() as Promise<T>
}

const jsonPost = (body: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

/* ---------- 认证 ---------- */

export function register(username: string, password: string) {
  return req<{ token: string; user: User }>('/auth/register',
    jsonPost({ username, password }))
}

export function login(username: string, password: string) {
  return req<{ token: string; user: User }>('/auth/login',
    jsonPost({ username, password }))
}

export function me() {
  return req<User>('/auth/me')
}

/* ---------- 资产库 ---------- */

export function listLibrary(): Promise<{ works: LibraryWork[] }> {
  return req<{ works: LibraryWork[] }>('/library')
}

export function createLibraryWork(work: string) {
  return req<{ work_title: string }>(`/library/${encodeURIComponent(work)}`,
    { method: 'POST' })
}

export function getLibraryWork(work: string): Promise<LibraryWork> {
  return req<LibraryWork>(`/library/${encodeURIComponent(work)}`)
}

export function upsertCard(work: string, kind: string, card: { id: string }) {
  return req<Record<string, unknown>>(
    `/library/${encodeURIComponent(work)}/${kind}/${encodeURIComponent(card.id)}`,
    { method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(card) })
}

export function deleteCard(work: string, kind: string, cardId: string) {
  return req<{ deleted: string }>(
    `/library/${encodeURIComponent(work)}/${kind}/${encodeURIComponent(cardId)}`,
    { method: 'DELETE' })
}

export function deleteLibraryWork(work: string) {
  return req<{ deleted: string }>(`/library/${encodeURIComponent(work)}`,
    { method: 'DELETE' })
}

/** 从本人历史记录补齐资产库（同 ID 追加式合并，重复调用安全） */
export function backfillLibrary() {
  return req<{ works: { work_title: string; added: number; merged: number }[] }>(
    '/library/backfill', { method: 'POST' })
}

export function importAssets(work: string, assets: unknown) {
  return req<{ added: number; merged: number }>(
    `/library/${encodeURIComponent(work)}/import`, jsonPost(assets))
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

export interface SaveResult {
  id: string
  edited_at: string
  /** 复验不通过时是 draft_invalid：记录已存下，但不许进渲染 */
  status: JobStatus
  verification: VerificationReport
}

/** 保存人工编辑后的分镜（覆盖 result，保留创建时间与制作参数）。
 *  服务端会整份复验，结果一并返回——调用方必须看 status，不能只当保存成功。 */
export function saveHistory(id: string, doc: Storyboard): Promise<SaveResult> {
  return req<SaveResult>(`/history/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(doc),
  })
}

export function deleteHistory(id: string): Promise<{ deleted: string }> {
  return req<{ deleted: string }>(`/history/${id}`, { method: 'DELETE' })
}


/** 分镜 IR → 渲染任务清单 + 人读版生产包 + 费用估算。
 *  传当前屏幕上的产物（可能还没保存），所以人工改完能立刻看到提示词与费用变化。 */
export function renderPlan(
  doc: Storyboard, opts: {
    maxClipSeconds?: number; runId?: string | null
    model?: string; cnyPerSecond?: number | null
  } = {},
): Promise<RenderPack> {
  return req<RenderPack>('/render/plan', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      result: doc,
      max_clip_seconds: opts.maxClipSeconds ?? 15,
      run_id: opts.runId ?? null,
      ...(opts.model ? { model: opts.model } : {}),
      ...(opts.cnyPerSecond ? { cny_per_second: opts.cnyPerSecond } : {}),
    }),
  })
}
