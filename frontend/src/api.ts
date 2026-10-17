/** 转换服务客户端。开发期走 vite 代理的 /api，生产可用 VITE_API_BASE 直连。
 *
 *  除注册/登录外的所有接口都要带 token；后端按 token 判定身份，
 *  各人只看得到自己的小说。会话结构：小说（长期记忆）→ 章节 → 版本（每次转换）。
 */
import { getToken, notifyUnauthorized } from './auth'
import type { User } from './auth'
import type {
  Chapter, Constraint, Health, Job, JobPartial, JobStatus, JobSummary, LifecycleEntry,
  KeyframePrompt, LifecycleType, Novel, NovelMemory, NovelParams, NovelSummary, RenderPack, Storyboard,
  VerificationReport, VersionRecord,
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

/** 带 token 发请求，统一处理 401 与错误 detail；成功时返回原始 Response */
async function send(path: string, init?: RequestInit): Promise<Response> {
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
  return res
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  return (await send(path, init)).json() as Promise<T>
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

export function health(): Promise<Health> {
  return req<Health>('/healthz')
}

export function getJob(jobId: string): Promise<Job> {
  return req<Job>(`/jobs/${jobId}`)
}

/** 已完成批次的合并结果（只读预览）。整章成功后不再提供 */
export function getJobPartial(jobId: string): Promise<JobPartial> {
  return req<JobPartial>(`/jobs/${jobId}/partial`)
}

/** 在跑/刚结束的任务：关掉页面后靠它重新接上 */
export function listJobs(): Promise<{ jobs: JobSummary[] }> {
  return req<{ jobs: JobSummary[] }>('/jobs')
}

export const TERMINAL = ['succeeded', 'completed_with_warnings', 'failed']

/* ---------- 小说 / 章节 / 版本 ---------- */

const enc = encodeURIComponent
const jsonBody = (method: string, body: unknown): RequestInit => ({
  method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
})
const novelPath = (nid: string) => `/novels/${enc(nid)}`
const chapterPath = (nid: string, cid: string) => `${novelPath(nid)}/chapters/${enc(cid)}`
const versionPath = (nid: string, cid: string, vid: string) =>
  `${chapterPath(nid, cid)}/versions/${enc(vid)}`

export function listNovels(): Promise<{ novels: NovelSummary[] }> {
  return req('/novels')
}

export function createNovel(title: string, params: Partial<NovelParams> = {}): Promise<Novel> {
  return req('/novels', jsonPost({ title, params }))
}

export function getNovel(nid: string): Promise<Novel> {
  return req(novelPath(nid))
}

export function updateNovel(nid: string,
                            patch: { title?: string; params?: Partial<NovelParams> }) {
  return req<Novel>(novelPath(nid), jsonBody('PATCH', patch))
}

export function deleteNovel(nid: string) {
  return req<{ deleted: string }>(novelPath(nid), { method: 'DELETE' })
}

export function createChapter(nid: string, title: string, text = ''): Promise<Chapter> {
  return req(`${novelPath(nid)}/chapters`, jsonPost({ title, text }))
}

export function getChapter(nid: string, cid: string): Promise<Chapter> {
  return req(chapterPath(nid, cid))
}

export function updateChapter(nid: string, cid: string,
                              patch: { title?: string; text?: string; order?: number }) {
  return req<Chapter>(chapterPath(nid, cid), jsonBody('PATCH', patch))
}

export function deleteChapter(nid: string, cid: string) {
  return req<{ deleted: string }>(chapterPath(nid, cid), { method: 'DELETE' })
}

/** 转换本章 → 新版本。job_id 即版本 id，进度照旧走 /jobs */
export function convertChapter(nid: string, cid: string,
                               opts: { overrides?: Partial<NovelParams>; strict?: boolean } = {}) {
  return req<{ job_id: string; version_id: string }>(
    `${chapterPath(nid, cid)}/versions`,
    jsonPost({ overrides: opts.overrides ?? {}, strict: opts.strict ?? false }))
}

export function getVersion(nid: string, cid: string, vid: string): Promise<VersionRecord> {
  return req(versionPath(nid, cid, vid))
}

export interface SaveResult {
  id: string
  edited_at: string
  /** 复验不通过时是 draft_invalid：版本已存下，但不许采用、不许进渲染 */
  status: JobStatus
  verification: VerificationReport
}

/** 保存人工编辑后的分镜（覆盖该版本的 result）。
 *  服务端会整份复验，结果一并返回——调用方必须看 status，不能只当保存成功。 */
export function saveVersion(nid: string, cid: string, vid: string,
                            doc: Storyboard): Promise<SaveResult> {
  return req(versionPath(nid, cid, vid), jsonBody('PUT', doc))
}

export function deleteVersion(nid: string, cid: string, vid: string) {
  return req<{ deleted: string }>(versionPath(nid, cid, vid), { method: 'DELETE' })
}

export function adoptVersion(nid: string, cid: string, vid: string) {
  return req<{ adopted_version: string; added: number; merged: number; retracted: number;
               changed: boolean; digest?: string }>(
    `${versionPath(nid, cid, vid)}/adopt`, { method: 'POST' })
}

export function rerunDigest(nid: string, cid: string) {
  return req<{ digest: string }>(`${chapterPath(nid, cid)}/digest`, { method: 'POST' })
}

/* ---------- 长期记忆 ---------- */

export function getMemory(nid: string): Promise<NovelMemory> {
  return req(`${novelPath(nid)}/memory`)
}

export function upsertMemoryCard(nid: string, kind: string, card: { id: string }) {
  return req<Record<string, unknown>>(
    `${novelPath(nid)}/memory/assets/${kind}/${enc(card.id)}`, jsonBody('PUT', card))
}

export function deleteMemoryCard(nid: string, kind: string, cardId: string) {
  return req<{ deleted: string }>(
    `${novelPath(nid)}/memory/assets/${kind}/${enc(cardId)}`, { method: 'DELETE' })
}

export function addLifecycle(nid: string, entry: {
  character_id: string; type: LifecycleType; detail?: string; chapter_id?: string | null
}): Promise<LifecycleEntry> {
  return req(`${novelPath(nid)}/memory/lifecycle`, jsonPost(entry))
}

/** 确认 / 驳回 / 修改一条生命周期记录 */
export function updateLifecycle(nid: string, lid: string, patch: {
  status?: LifecycleEntry['status']; type?: LifecycleType; detail?: string
}): Promise<LifecycleEntry> {
  return req(`${novelPath(nid)}/memory/lifecycle/${enc(lid)}`, jsonPost(patch))
}

export function deleteLifecycle(nid: string, lid: string) {
  return req<{ deleted: string }>(`${novelPath(nid)}/memory/lifecycle/${enc(lid)}`,
                                  { method: 'DELETE' })
}

export function setOutline(nid: string, outline: string) {
  return req<{ outline: string }>(`${novelPath(nid)}/memory/plot`,
                                  jsonBody('PUT', { outline }))
}

export function setSynopsis(nid: string, cid: string, synopsis: string) {
  return req<{ synopsis: string }>(`${novelPath(nid)}/memory/plot/chapters/${enc(cid)}`,
                                   jsonBody('PUT', { synopsis }))
}

export function addConstraint(nid: string,
                              c: Partial<Omit<Constraint, 'id'>>): Promise<Constraint> {
  return req(`${novelPath(nid)}/memory/constraints`, jsonPost(c))
}

export function updateConstraint(nid: string, kid: string,
                                 patch: Partial<Omit<Constraint, 'id'>>): Promise<Constraint> {
  return req(`${novelPath(nid)}/memory/constraints/${enc(kid)}`, jsonBody('PATCH', patch))
}

export function deleteConstraint(nid: string, kid: string) {
  return req<{ deleted: string }>(`${novelPath(nid)}/memory/constraints/${enc(kid)}`,
                                  { method: 'DELETE' })
}

/* ---------- 渲染任务包 ---------- */

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

/* ---------- 静帧预演：关键帧 ---------- */

/** 每镜一条关键帧出图提示词（传屏幕上的产物，可能还没保存） */
export function renderKeyframes(doc: Storyboard): Promise<{ keyframes: KeyframePrompt[] }> {
  return req('/render/keyframes', jsonPost({ result: doc }))
}

const keyframePath = (nid: string, cid: string, vid: string) =>
  `${versionPath(nid, cid, vid)}/keyframes`

/** 这个版本里已经上传了关键帧图的镜头 */
export function listKeyframes(nid: string, cid: string, vid: string): Promise<{ shots: string[] }> {
  return req(keyframePath(nid, cid, vid))
}

/** 取一张关键帧图。<img src> 带不了 token，所以带 token 取回来转成 blob URL（用完要 revoke） */
export async function keyframeUrl(nid: string, cid: string, vid: string, shotId: string) {
  const res = await send(`${keyframePath(nid, cid, vid)}/${enc(shotId)}`)
  return URL.createObjectURL(await res.blob())
}

/** 上传（或替换）一镜的关键帧图：PNG / JPEG / WebP，≤ 8MB */
export function uploadKeyframe(nid: string, cid: string, vid: string, shotId: string, file: Blob) {
  return req<{ shot_id: string; bytes: number }>(`${keyframePath(nid, cid, vid)}/${enc(shotId)}`, {
    method: 'PUT', headers: { 'Content-Type': file.type }, body: file })
}

export function deleteKeyframe(nid: string, cid: string, vid: string, shotId: string) {
  return req<{ deleted: string }>(`${keyframePath(nid, cid, vid)}/${enc(shotId)}`,
                                  { method: 'DELETE' })
}
