/** 转换服务客户端。开发期走 vite 代理的 /api，生产可用 VITE_API_BASE 直连。
 *
 *  除注册/登录外的所有接口都要带 token；后端按 token 判定身份，
 *  各人只看得到自己的小说。会话结构：小说（长期记忆）→ 章节 → 版本（每次转换）。
 */
import { tr } from './i18n/core'
import { getToken, notifyUnauthorized } from './auth'
import { parseSse } from './lib/sse'
import type { User } from './auth'
import type {
  Chapter, Constraint, NovelSummaryData, Health, Job, JobPartial, JobStatus, JobSummary, LifecycleEntry,
  KeyframePrompt, LifecycleType, Novel, NovelMemory, NovelParams, NovelSummary, RenderPack, Storyboard,
  FilmSession, FilmSettings, StyleImageMeta, ComposePreview, VoicesInfo,
  VerificationReport, VersionRecord,
  AdminJobs, AdminOverview, AdminUserDetail, AdminUserRow, AuditEntry, PricingTable, UsageReport,
  AssistantEvent, AssistantMsg, AssistantWhere,
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
  if (res.status === 401 && token) {   // 没带 token 的 401（登录 / 注册失败）交给下面带服务端 detail 的错误
    notifyUnauthorized()          // 广播出去，让 App 退回登录页
    throw new Error(tr('api.unauthenticated'))
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

export function getNovelSummary(nid: string): Promise<NovelSummaryData> {
  return req(`${novelPath(nid)}/summary`)
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

/* ---------- 风格参考图（每部小说一张） ---------- */

/** 带 token 取风格参考图，转成 blob URL（用完要 revoke）；没有图是 404 */
export async function styleImageUrl(nid: string, hash: string) {
  // ?v=hash：换图后换地址，浏览器 HTTP 缓存不会把旧图当新图
  const res = await send(`/novels/${enc(nid)}/style-image?v=${enc(hash)}`, { cache: 'no-store' })
  return URL.createObjectURL(await res.blob())
}

/** 上传（或替换）风格参考图：PNG / JPEG / WebP，≤ 8MB */
export function uploadStyleImage(nid: string, file: Blob) {
  return req<StyleImageMeta>(`/novels/${enc(nid)}/style-image`, {
    method: 'PUT', headers: { 'Content-Type': file.type }, body: file })
}

export function deleteStyleImage(nid: string) {
  return req<unknown>(`/novels/${enc(nid)}/style-image`, { method: 'DELETE' })
}

/* ---------- 出片（视频生成会话） ---------- */

const filmPath = (nid: string, cid: string, vid: string) => `${versionPath(nid, cid, vid)}/render`

/** 读取出片会话（附验证门结果）；还没建过是 404 */
export function getFilm(nid: string, cid: string, vid: string): Promise<FilmSession> {
  return req(`${filmPath(nid, cid, vid)}/session`)
}

/** 建立（或按当前设置重建）出片会话：过验证门、切段，不花钱 */
export function createFilm(nid: string, cid: string, vid: string,
                           settings: FilmSettings = {}): Promise<FilmSession> {
  return req(`${filmPath(nid, cid, vid)}/session`, jsonPost(settings))
}

/** 改设置：按新设置重新切段（不花钱）；有段在跑时 409 */
export function patchFilm(nid: string, cid: string, vid: string,
                          settings: FilmSettings): Promise<FilmSession> {
  return req(`${filmPath(nid, cid, vid)}/session`, jsonBody('PATCH', settings))
}

/** 出这一段（试段 / 重做）。超过确认线时要带用户确认过的金额 */
export function runFilmClip(nid: string, cid: string, vid: string, clipId: string,
                            expectedCny?: number): Promise<FilmSession> {
  return req(`${filmPath(nid, cid, vid)}/clips/${enc(clipId)}/run`,
             jsonPost(expectedCny === undefined ? {} : { expected_cny: expectedCny }))
}

/** 批量出剩余各段：必须带确认金额，服务端重算不一致 409 */
export function runFilmRest(nid: string, cid: string, vid: string,
                            expectedCny: number): Promise<FilmSession> {
  return req(`${filmPath(nid, cid, vid)}/run`, jsonPost({ expected_cny: expectedCny }))
}

/** 采用这一段的第几次 */
export function chooseFilmAttempt(nid: string, cid: string, vid: string, clipId: string,
                                  attempt: number): Promise<FilmSession> {
  return req(`${filmPath(nid, cid, vid)}/clips/${enc(clipId)}/chosen`, jsonBody('PUT', { attempt }))
}

/** 合成时这一段的视频原声静音 */
export function muteFilmClip(nid: string, cid: string, vid: string, clipId: string,
                             mute: boolean): Promise<FilmSession> {
  return req(`${filmPath(nid, cid, vid)}/clips/${enc(clipId)}`, jsonBody('PATCH', { mute_native: mute }))
}

/** 取会话目录下的文件（片段视频、尾帧）。<video>/<image> 带不了 token，转成 blob URL（用完要 revoke） */
export async function filmFileUrl(nid: string, cid: string, vid: string, path: string): Promise<string> {
  const res = await send(`${filmPath(nid, cid, vid)}/files/${path.split('/').map(enc).join('/')}`)
  return URL.createObjectURL(await res.blob())
}

/** 从 Content-Disposition 取文件名：优先 filename*（RFC 5987，utf-8 编码），没有再取 filename="…"；都取不到返回 null */
export function dispositionName(cd: string): string | null {
  const star = /filename\*\s*=\s*utf-8''([^;]+)/i.exec(cd)
  if (star) {
    try {
      const v = decodeURIComponent(star[1].trim())
      if (v) return v
    } catch { /* 解码失败退回 filename= */ }
  }
  const plain = /filename\s*=\s*"([^"]+)"/i.exec(cd)
  return plain ? plain[1] : null
}

/** 把 blob 地址存成文件：临时 <a download> 点一下，1 秒后回收（立刻回收会让 Firefox / Safari 中断下载） */
export function downloadUrl(url: string, name: string): void {
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** 导出剪辑工程（FCPXML 工程包 zip）：带登录态取回后存盘；失败抛带服务端 detail 的错误 */
export async function exportFcpxml(nid: string, cid: string, vid: string): Promise<void> {
  const res = await send(`${filmPath(nid, cid, vid)}/export.zip`)
  const name = dispositionName(res.headers.get('content-disposition') ?? '') ?? 'project.zip'
  downloadUrl(URL.createObjectURL(await res.blob()), name)
}

/** 出片 409 里服务端重算的金额（确认金额对不上、或单段需要确认时附带）；不是这种错误返回 null */
export function conflictCny(e: unknown): number | null {
  if (!(e instanceof ApiError) || e.status !== 409) return null
  const d = e.detail as { expected_cny?: unknown } | null
  return d && typeof d === 'object' && typeof d.expected_cny === 'number' ? d.expected_cny : null
}

/* ---------- 配音与合成 ---------- */

/** 音色表与各说话人现在用的音色；这个声音模式不配音时为空表 */
export function getVoices(nid: string, cid: string, vid: string): Promise<VoicesInfo> {
  return req(`${filmPath(nid, cid, vid)}/voices`)
}

/** 选音色：说话人 → 音色 id，空串为恢复按提示默认 */
export function putVoices(nid: string, cid: string, vid: string,
                          voices: Record<string, string>): Promise<VoicesInfo> {
  return req(`${filmPath(nid, cid, vid)}/voices`, jsonBody('PUT', { voices }))
}

/** 合成预览（不花钱）：配音条数与金额、缺音色、缺视频的段、BGM、选曲参考、成片状态与报告 */
export function getCompose(nid: string, cid: string, vid: string, draft: boolean): Promise<ComposePreview> {
  return req(`${filmPath(nid, cid, vid)}/compose?draft=${draft}`)
}

/** 合成整章（后台）：带用户确认过的配音金额，服务端重算不一致 409 */
export function startCompose(nid: string, cid: string, vid: string, draft: boolean,
                             expectedCny: number): Promise<FilmSession> {
  return req(`${filmPath(nid, cid, vid)}/compose`, jsonPost({ expected_cny: expectedCny, draft }))
}

/** 上传一集的 BGM（原样作为请求体） */
export function putBgm(nid: string, cid: string, vid: string, episode: string, file: Blob,
                       type: string): Promise<{ episode: string; bytes: number }> {
  return req(`${filmPath(nid, cid, vid)}/bgm/${enc(episode)}`,
             { method: 'PUT', headers: { 'Content-Type': type }, body: file })
}

export function deleteBgm(nid: string, cid: string, vid: string, episode: string): Promise<{ deleted: string }> {
  return req(`${filmPath(nid, cid, vid)}/bgm/${enc(episode)}`, { method: 'DELETE' })
}

/* ---------- 管理后台 ---------- */

export function adminOverview() {
  return req<AdminOverview>('/admin/overview')
}

export async function adminUsers(): Promise<AdminUserRow[]> {
  return (await req<{ users: AdminUserRow[] }>('/admin/users')).users
}

export function adminUser(id: string) {
  return req<AdminUserDetail>(`/admin/users/${encodeURIComponent(id)}`)
}

export function adminPatchUser(id: string,
  patch: { disabled: boolean } | { role: 'admin' | 'user' } | { monthly_cap_usd: number | null }) {
  return req<AdminUserRow>(`/admin/users/${encodeURIComponent(id)}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(patch),
  })
}

export function adminResetPassword(id: string, password: string) {
  return req<{ ok: boolean }>(`/admin/users/${encodeURIComponent(id)}/password`,
    jsonPost({ password }))
}

export function adminUsage(group: 'user' | 'day' | 'model', days: number) {
  return req<UsageReport>(`/admin/usage?group=${group}&days=${days}`)
}

export async function adminUsageCsv(days: number): Promise<string> {
  return (await send(`/admin/usage.csv?days=${days}`)).text()
}

export function adminJobs() {
  return req<AdminJobs>('/admin/jobs')
}

export async function adminAudit(): Promise<AuditEntry[]> {
  return (await req<{ audit: AuditEntry[] }>('/admin/audit')).audit
}

export function adminPricing() {
  return req<PricingTable>('/admin/pricing')
}

export function adminSavePricing(table: unknown) {
  return req<PricingTable>('/admin/pricing', {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(table),
  })
}

// ---------- 助手 ----------

export const getAssistant = (nid: string) =>
  req<{ messages: AssistantMsg[] }>(`/novels/${encodeURIComponent(nid)}/assistant`)

export const clearAssistant = (nid: string) =>
  req<{ ok: true }>(`/novels/${encodeURIComponent(nid)}/assistant`, { method: 'DELETE' })

/** POST 一个 JSON，逐个回调返回的 SSE 事件；signal 中止即停止。429 / 409 / 422 等在开始流之前以 ApiError 抛出。 */
async function streamSse(path: string, body: unknown, onEvent: (e: AssistantEvent) => void,
                         signal?: AbortSignal): Promise<void> {
  const res = await send(path, { ...jsonPost(body), signal })
  const reader = res.body?.getReader()
  if (!reader) return
  const dec = new TextDecoder()
  let buf = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buf += dec.decode(value, { stream: true })
    const { events, rest } = parseSse(buf)
    buf = rest
    events.forEach(onEvent)
  }
  const { events } = parseSse(buf + '\n\n')
  events.forEach(onEvent)
}

/** 发一条消息并逐个回调事件；signal 中止即停止（服务端跑完当前这一步就停）。 */
export const streamAssistant = (
  nid: string, body: { text: string; lang: string; where: AssistantWhere },
  onEvent: (e: AssistantEvent) => void, signal?: AbortSignal,
) => streamSse(`/novels/${encodeURIComponent(nid)}/assistant/messages`, body, onEvent, signal)

/** 确认卡上点了确认或取消：接着跑被中断的那一轮，同样流式返回 */
export const resumeAssistant = (
  nid: string, body: { id: string; decision: 'approve' | 'reject'; lang: string; where: AssistantWhere },
  onEvent: (e: AssistantEvent) => void, signal?: AbortSignal,
) => streamSse(`/novels/${encodeURIComponent(nid)}/assistant/resume`, body, onEvent, signal)
