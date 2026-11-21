import type { StepId } from './workflow'
import type { MsgLike, ServerMsg } from './i18n/serverMsg'

/** NovelStoryboard v0.4 / v0.5 分镜 IR 的 TypeScript 镜像（对齐 backend/schema/storyboard.schema.json）。
 *  字段可选性以 schema 的 required 为准：非必填一律标 `?`，渲染层不得假设其存在。 */

export type FidelityMode = 'faithful' | 'pacing_optimized' | 'adapted'
export type AspectRatio = '9:16' | '16:9' | '1:1' | '4:3'
export type NarrationMode = 'original_text' | 'selective' | 'condensed' | 'none'
export type UnitKind = 'action' | 'dialogue' | 'psychology' | 'description' | 'narration_meta'
export type ShotSize =
  | 'extreme_wide' | 'wide' | 'full' | 'medium'
  | 'medium_close' | 'close_up' | 'extreme_close_up' | 'insert'
export type CameraMovement =
  | 'static' | 'push_in' | 'pull_out' | 'pan' | 'tilt' | 'track'
  | 'follow' | 'orbit' | 'crane' | 'handheld' | 'zoom'
export type CameraAngle =
  | 'eye_level' | 'high' | 'low' | 'overhead' | 'dutch' | 'pov' | 'over_shoulder'
export type LocationAngle = 'front' | 'reverse' | 'side' | 'overhead' | 'establishing'
export type TimeOfDay = 'dawn' | 'day' | 'dusk' | 'night'
export type DialogueType = 'dialogue' | 'inner_monologue' | 'voiceover'
export type Transition = 'cut' | 'dissolve' | 'fade_to_black' | 'match_cut' | 'whip_pan'
export type Derivation = 'explicit' | 'inferred' | 'transition'
export type Mood =
  | 'calm' | 'warm' | 'playful' | 'tense' | 'ominous'
  | 'eerie' | 'sorrow' | 'melancholy' | 'triumph' | 'epic'

export interface Meta {
  schema_version: string
  title: string
  fidelity_mode: FidelityMode
  style: {
    style_prefix: string
    art_style?: string
    color_tone?: string
    negative_prompt?: string
  }
  video: {
    aspect_ratio: AspectRatio
    resolution?: string
    target_platform?: string
  }
  narration: {
    mode: NarrationMode
    tts_voice?: string
  }
}

export interface SourceUnit {
  id: string
  text: string
  para?: number
  kind?: UnitKind
}

export interface Source {
  work_title: string
  chapter?: string
  units: SourceUnit[]
}

/** 设定图槽位。tag（角色的 outfit / 道具的 state）说明这张图画的是哪套变体——
 *  设定图是「画师修正稿反过来约束后续每一帧」这条链的锚点，垫错衣服等于白垫。 */
export interface ReferenceImage {
  view?: 'front' | 'side' | 'back' | 'three_quarter' | 'close_up'
  uri?: string
  outfit?: string
  state?: string
}

/** 角色的服装 / 道具的形态。id 被镜头层跨引用，description 是这套变体的完整外观描述 */
export interface AssetVariant {
  id: string
  description: string
}

export interface CharacterAsset {
  id: string
  name: string
  aliases?: string[]
  appearance?: Record<string, string>
  /** 服装状态集。schema：{id, description}，且 additionalProperties: false——
   *  多写一个字段整份产物就校验失败 */
  outfits?: AssetVariant[]
  visual_prompt?: string
  reference_images?: ReferenceImage[]
  /** 画这张卡时不要做什么：不要平滑笔触 / 不要加照片级细节 / 不要改画风 */
  constraints?: string[]
  voice?: Record<string, string>
  persona_notes?: string
}

export interface LocationAsset {
  id: string
  name: string
  era?: string
  interior_exterior?: 'interior' | 'exterior' | 'both'
  visual_prompt?: string
  /** 各机位的设定图槽位（schema：{angle, uri}） */
  angles?: { angle?: LocationAngle; uri?: string }[]
  constraints?: string[]
  lighting_defaults?: string
}

export interface PropAsset {
  id: string
  name: string
  visual_prompt?: string
  reference_images?: ReferenceImage[]
  constraints?: string[]
  /** 道具形态集，形状同 outfits */
  states?: AssetVariant[]
}

export interface CreatureAsset {
  id: string
  name: string
  aliases?: string[]
  species?: string
  visual_prompt?: string
  reference_images?: ReferenceImage[]
  constraints?: string[]
  notes?: string
}

export interface Assets {
  characters?: CharacterAsset[]
  locations?: LocationAsset[]
  props?: PropAsset[]
  creatures?: CreatureAsset[]
}

export interface ShotCharacter {
  ref: string
  outfit?: string
  expression?: string
  action?: string
  position?: string
}

export interface ShotPropRef {
  ref: string
  state?: string
}

export interface DialogueLine {
  type: DialogueType
  text: string
  character_ref?: string
  emotion?: string
  verbatim?: boolean
}

/** 镜头内的一拍。各拍时长之和必须等于镜头的 duration_sec，lint 会校验 */
export interface ShotBeat {
  duration_sec: number
  action: string
  expression?: string
  lighting?: string
  camera_note?: string
}

export interface ShotNarration {
  unit_refs?: string[]
  text?: string
  order?: 'before_dialogue' | 'after_dialogue'
}

export interface Shot {
  id: string
  duration_sec: number
  shot_size: ShotSize
  camera?: { movement?: CameraMovement; angle?: CameraAngle }
  location_ref?: string
  location_angle?: LocationAngle
  time_of_day?: TimeOfDay
  weather?: string
  characters?: ShotCharacter[]
  prop_refs?: ShotPropRef[]
  action: string
  atmosphere?: string
  /** v0.5：镜头内的阶段。一个不切的长镜头里情绪/灯光可以逐级推进 */
  beats?: ShotBeat[]
  /** v0.5：本镜头明确不要出现的东西 */
  constraints?: string[]
  dialogue?: DialogueLine[]
  narration?: ShotNarration
  sfx?: string[]
  transition_out?: Transition
  source: { unit_refs: string[]; derivation: Derivation; note?: string }
  prompts?: ShotPrompts
}

/** 组装后的提示词。reference_assets = 出图时拿哪几张卡垫图，直接决定形象锁不锁得住 */
export interface ShotPrompts {
  image_prompt?: string
  video_prompt?: string
  reference_assets?: string[]
}

export interface MusicSegment {
  from_shot?: string
  to_shot?: string
  mood?: Mood
  intensity?: 'low' | 'mid' | 'high'
  note?: string
  unit_refs?: string[]
}

export interface Episode {
  id: string
  title?: string
  source_range?: { from_unit?: string; to_unit?: string }
  summary?: string
  tail_frame_description?: string
  music?: { mood?: Mood; style_hint?: string; curve?: MusicSegment[] }
  shots: Shot[]
}

export interface Coverage {
  unmapped_units?: string[]
  inferred_shot_ratio?: number
}

export interface Storyboard {
  meta: Meta
  source: Source
  assets?: Assets
  episodes: Episode[]
  coverage?: Coverage
}

/* ---------- 后端 HTTP 契约（backend/server/app.py） ---------- */

export type JobStatus =
  | 'queued' | 'running' | 'succeeded' | 'completed_with_warnings' | 'failed'
  // 人工编辑后没通过服务端复验：记录仍保存（不丢人的工作），但禁止进入付费渲染
  | 'draft_invalid'

/* ---------- 服务端验证报告（backend/pipeline/verification.py） ---------- */

export type Severity = 'critical' | 'high' | 'medium' | 'low'

/** 一条结构化发现。object_path 是 JSON Pointer，可直接定位到出问题的镜头/字段。 */
export interface Finding {
  rule_id: string
  severity: Severity
  object_path: string
  message: string
  /** 说明的消息对象（verify.rule.<rule_id>），界面按语言渲染；message 是回喂模型的原文。旧报告没有 */
  msg?: ServerMsg
  unit_refs?: string[]
  evidence_quote?: string
  expected?: unknown
  actual?: unknown
}

export interface VerificationCoverage {
  selected?: string[]
  covered?: string[]
  waived?: string[]
  failed?: string[]
  inferred_shot_ratio?: number
}

export interface VerificationReport {
  status: 'verified' | 'failed'
  findings: Finding[]
  coverage?: VerificationCoverage
}

/** 制作参数（backend ConvertParams 去掉作品名/章节名）：小说级默认值，转换时可按章覆写 */
export interface NovelParams {
  style_prefix: string
  art_style: string
  color_tone: string
  aspect_ratio: AspectRatio
  target_platform: string
  narration_mode: NarrationMode
  tts_voice: string
}

/** 转换进度（服务端 _progress_view）。剩余时间在第一批跑完之前为 null——没有依据不瞎猜 */
export interface JobProgress {
  batches: number
  batch: number
  batch_chars?: number
  total_chars: number
  done_chars: number
  attempt: number
  max_attempts: number
  phase: 'starting' | 'generating' | 'regenerating' | 'checking' | 'repairing'
    | 'merging' | 'done'
  elapsed_sec: number | null
  eta_sec: number | null
}

export interface Job {
  id: string
  status: JobStatus
  /** 兼容：后端子计划 4 之前是字符串 */
  log: (JobEvent | string)[]
  result: Storyboard | null
  quality_report: string | null
  /** 质量报告的消息对象（逐条）；旧任务没有，退回 quality_report */
  quality_msg?: ServerMsg[] | null
  error: string | null
  error_msg?: ServerMsg | null
  /** 服务端对本次产物的验证报告（失败时带上不通过的逐条原因） */
  verification?: VerificationReport | null
  created_at?: string
  work_title?: string
  chapter?: string
  chars?: number
  progress?: JobProgress | null
  /** 已完成、可先预览的批数（部分产物本身走 /jobs/{id}/partial 单独取） */
  partial_batches?: number
}

/** 已完成批次的合并结果：整章跑完之前的只读预览 */
export interface JobPartial {
  doc: Storyboard
  batches_done: number
  batches: number
}

/** 转换进度事件（后端 job.log 的一条）：消息对象 + 时间；旧任务是字符串 */
export type JobEvent = ServerMsg & { at?: string }

/** 任务摘要：用于关掉页面后重新接上仍在后台跑的转换 */
export interface JobSummary {
  id: string
  status: JobStatus
  created_at: string | null
  work_title: string | null
  chapter: string | null
  chars: number | null
  log_lines: number
  /** 兼容：后端子计划 4 之前是字符串 */
  last_log: JobEvent | string | null
  progress?: JobProgress | null
  novel_id?: string | null
  chapter_id?: string | null
}

export interface Health {
  status: string
  /** 首次注册标记（免登录探针只给这一项） */
  first_run?: boolean
}

/** 管理员的服务信息（GET /admin/service）：普通用户不可见 */
export interface AdminService {
  model: string
  review_model: string | null
  api_key_configured: boolean
}

/* ---------- 小说级会话（backend/server/novels.py） ---------- */

export interface NovelSummary {
  id: string
  title: string
  updated_at: string | null
  chapters: number
  adopted: number
  asset_counts: Record<string, number>
}

/** 一次转换 = 一个版本（短期记忆）。列表里只带摘要 */
export interface VersionSummary {
  id: string
  created_at: string | null
  edited_at: string | null
  status: JobStatus
  units: number
  episodes: number
  shots: number
  has_quality_report: boolean
  verification_status?: 'verified' | 'failed' | null
}

export interface VersionRecord {
  id: string
  novel_id: string
  chapter_id: string
  created_at: string
  edited_at: string | null
  status: JobStatus
  params: Record<string, unknown>
  quality_report: string | null
  verification?: VerificationReport | null
  error?: string | null
  error_msg?: ServerMsg | null
  result: Storyboard | null
}

/** 采用版本后的「章后整理」：人物生命周期提议 + 本章摘要 */
export interface DigestState {
  status: 'running' | 'done' | 'failed' | 'off'
  at: string
  version_id?: string
  proposed?: number
  dropped?: string[]
  synopsis_kept_user?: boolean
  error?: string
  error_msg?: ServerMsg | null
}

export interface ChapterSummary {
  id: string
  title: string
  order: number
  adopted_version: string | null
  legacy_numbering: boolean
  chars: number
  versions: VersionSummary[]
  latest_status: JobStatus | null
  digest?: DigestState | null
}

export interface Chapter {
  id: string
  title: string
  order: number
  text: string
  adopted_version: string | null
  legacy_numbering?: boolean
  versions: VersionSummary[]
  digest?: DigestState | null
}

export type LifecycleType = 'deceased' | 'permanent_condition' | 'departed'

/** 主线人物不可逆的状态变化：死亡 / 永久伤病 / 永久下线 */
export interface LifecycleEntry {
  id: string
  character_id: string
  type: LifecycleType
  detail: string
  since: { chapter_id: string | null; unit_ref: string | null }
  evidence_quote: string
  origin: 'model' | 'user'
  status: 'proposed' | 'confirmed' | 'rejected'
  written_by: { chapter_id: string; version_id: string } | null
}

export interface ChapterSynopsis {
  chapter_id: string
  synopsis: string
  origin: 'model' | 'user'
}

export interface Constraint {
  id: string
  text: string
  negative_prompt: string
  keywords: string[]
  enabled: boolean
}

/** 长期记忆：只由各章的采用版写入 */
export interface NovelMemory {
  assets: Assets
  numbering: { next_unit: number; next_para: number; next_episode: number }
  lifecycle: LifecycleEntry[]
  plot: { outline: string; chapters: ChapterSynopsis[] }
  constraints: Constraint[]
}

export interface Novel {
  id: string
  title: string
  created_at: string
  updated_at: string
  params: Partial<NovelParams>
  memory: NovelMemory
  chapters: ChapterSummary[]
  /** 风格参考图的元数据；没传过图为 null */
  style_image?: StyleImageMeta | null
}

export interface StyleImageMeta { hash: string; mime: string; bytes: number; updated_at: string }

/* ---------- 静帧预演（backend/render/keyframes.py） ---------- */

/** 一镜的关键帧出图提示词：静态单帧，人物/场景/道具描述取自资产卡 */
export interface KeyframePrompt {
  shot_id: string
  prompt: string
  negative_prompt: string
  reference_assets: string[]
  aspect_ratio: string
}

/** 关键帧挂在哪个版本上（只有存进后端的版本才能上传图） */
export interface VersionRef {
  nid: string
  cid: string
  vid: string
}

/* ---------- 渲染任务包 ---------- */

/** 与 edit.ts 的 AssetKind 同值；types.ts 不反向依赖 edit.ts，故在此独立声明 */
export type AssetKindName = 'characters' | 'locations' | 'props' | 'creatures'

export interface RenderClip {
  id: string
  episode: string
  shots: string[]
  start_sec: number
  duration_sec: number
  /** 能念完旁白台词的实际时长；短于自身旁白的镜头成片时必须拉长，按这个计价 */
  playable_sec: number
  speech_overflow: number
  /** 发给视频模型的整段提示词，与人读版生产包里那一段逐字相同 */
  prompt: string
  reference_assets: string[]
  narration: { shot: string; text: string; order?: string }[]
}

export interface RenderAsset {
  id: string
  kind: AssetKindName
  kind_zh: string
  name: string
  image_prompt: string
  variants: AssetVariant[]
  constraints: string[]
  images: { view?: string; uri?: string; variant?: string }[]
  have_images: number
  /** 至少需要几张图：没声明槽位的卡也需要一张，否则没得垫 */
  need_images: number
  angles?: string[]
}

export interface RenderTier {
  id: string
  label: string
  resolutions: string
  cny_per_second: number
}

export interface RenderEstimate {
  clips: number
  seconds: number
  playable_seconds: number
  speech_overflow_sec: number
  speech_cps: number
  asset_images_total: number
  asset_images_missing: number
  model: string
  model_label: string
  resolutions: string
  cny_per_second: number
  cny_once: number
  cny_with_retries: number
  retry_factor: number
  /** true 表示用的是人工指定/标定过的费率，不是推算值 */
  calibrated: boolean
  rate: { tokens_per_second: number; cny_per_million_tokens: number; source: string }
  caveats: string[]
  note: string
}

export interface RenderPlan {
  plan_version: string
  run_id: string | null
  work_title: string
  chapter: string
  schema_version: string
  style_prefix: string
  video: { aspect_ratio?: string }
  max_clip_seconds: number
  assets: RenderAsset[]
  clips: RenderClip[]
  estimate: RenderEstimate
  tiers: RenderTier[]
}

export interface RenderPack {
  plan: RenderPlan
  packs: { episode: string; title: string; markdown: string }[]
  verification?: VerificationReport
}

/* ---------- 管理后台 ---------- */

export interface AdminUserRow {
  id: string
  username: string
  role: 'admin' | 'user'
  disabled: boolean
  created_at: string | null
  last_seen_at: string | null
  has_password: boolean
  monthly_cap_usd: number | null
  novels: number
  chapters: number
  versions: number
  month_cost_usd: number
}

export interface UsageEntry {
  at: string
  user_id: string
  novel_id: string | null
  chapter_id: string | null
  version_id: string | null
  purpose: string
  model: string
  ok: boolean
  calls: number
  input: number
  output: number
  cache_read: number
  cache_write: number
  chars: number
  mixed_models?: string[]
}

export interface DailyCost {
  day: string
  cost_usd: number
}

export interface AdminUserDetail {
  user: AdminUserRow
  recent: (UsageEntry & { novel_title: string | null; chapter_title: string | null;
                          cost_usd: number | null })[]
  daily: DailyCost[]
}

export interface AdminOverview {
  users: number
  active_7d: number
  tokens_30d: number
  cost_30d: number
  running: number
  failed_7d: number
  daily: DailyCost[]
  unpriced_models: string[]
}

export interface UsageGroupRow {
  key: string
  label: string
  calls: number
  input: number
  output: number
  cache_read: number
  cache_write: number
  chars: number
  cost_usd: number
  unpriced: number
  records: number
}

export interface UsageReport {
  group: 'user' | 'day' | 'model'
  days: number
  rows: UsageGroupRow[]
  per_k_chars: { n: number; mean: number | null; p90: number | null }
  unpriced_models: string[]
}

export interface AdminJobs {
  running: { id: string; user_id: string; username: string | null; status: string; work_title: string | null;
             chapter: string | null; chars: number | null; created_at: string | null;
             elapsed_sec: number | null }[]
  failed: { id: string; user_id: string; username: string | null; novel_title: string | null;
            chapter_title: string | null; created_at: string; chars: number;
            attempts: number; error: string; error_msg?: ServerMsg | null }[]
}

export interface ErrorRefRow {
  ref: string; at: string; user_id: string | null; username: string | null
  code: string; params: Record<string, unknown>; where: string
  /** 只有单条接口返回（查看会写审计） */
  detail?: string
}

export interface AuditEntry {
  at: string
  admin: string
  action: string
  target: string | null
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
}

export interface PricingTable {
  currency: string
  note?: string
  updated_at: string | null
  models: Record<string, { input: number; output: number; cache_read: number; cache_write: number; vendor?: string }>
}

/* ---------- 出片（视频生成会话，…/versions/{vid}/render/session） ---------- */

export type FilmClipState = 'planned' | 'queued' | 'running' | 'downloading' | 'done' | 'failed' | 'stale'
export type AudioMode = 'tts_all' | 'dialogue_native' | 'all_native' | 'silent'

/** 一段的一次出片尝试 */
export interface FilmAttempt {
  task_id: string | null
  /** cancelled：服务商确认已取消（不计费）；abandoned：用户不等了，服务商那边可能还在跑，后台盯到有结果 */
  state: 'submitting' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'abandoned'
  cost_cny: number
  /** 会话目录下的相对路径，用 filmFileUrl 取 */
  file: string | null
  last_frame: string | null
  error: string | null
  error_msg?: ServerMsg | null
  at: string
  /** 自由节点的尝试没有分镜指纹，存 null */
  fingerprint: string | null
  first_frame_used: string | null
  /** 这次实际带上的风格图哈希（没带为 null） */
  style_ref?: string | null
  /** 自由节点生成后复制进剧本段的那次：来自哪个节点（花费记在节点上，这里为 0） */
  free_id?: string
  /** 用户不等了之后才出结果的那次：已计费、可采用，不会自动采用 */
  late?: boolean
  cancelled_at?: string
}

export interface FilmClip {
  id: string
  episode: string
  shots: string[]
  duration: number
  /** 超出单段上限，尾部被截断 */
  truncated: boolean
  prompt: string
  /** 带图的参考资产；dropped 为超出名额被裁的；missing 为没有图、只写文字描述的 */
  refs: string[]
  dropped_refs: string[]
  missing_refs: string[]
  /** keyframe:<镜头 id> | relay:<上一段 id> | null */
  first_frame: string | null
  frame_mode: 'frame' | 'ref' | null
  fingerprint: string
  estimate_cny: number
  attempts: FilmAttempt[]
  /** 采用第几次（attempts 的下标） */
  chosen: number | null
  mute_native: boolean
  /** 厂商那边可能还有这一段的任务（提交结果不明、查询放弃）：请到控制台核对，批量出片跳过 */
  uncertain: boolean
  error: string | null
  error_msg?: ServerMsg | null
  state: FilmClipState
  queued_at?: string
  /** 最近一次结束的时间与结局（任务列表用） */
  ended_at?: string
  ended_as?: 'done' | 'failed' | 'cancelled'
  /** 风格图：used 已带上 / full 参考位已满 / first_frame 本段用首帧 / null 没有风格图 */
  style?: 'used' | 'full' | 'first_frame' | null
  style_hash?: string | null
  /** 用旧风格图出完的段，可按新图重出 */
  style_outdated?: boolean
}

/** 自由节点（剧本之外补拍或重做一段）：target 为空是独立素材，否则成功的每一次都复制进那一段的尝试 */
export interface FilmFreeNode {
  id: string
  target: string | null
  /** 挂靠时那一段的镜头：重新切段后同 id 换了内容就转为独立素材 */
  target_shots: string[] | null
  /** 挂靠的段已不存在或换了镜头（此时 target 已为 null） */
  target_lost: boolean
  /** 画面描述正文（参考行在生成时按 refs 顺序拼上） */
  prompt: string
  /** 资产 id，顺序即发给厂商的顺序；风格图为 __style__ */
  refs: string[]
  /** keyframe:<镜头 id> | tail:<段或自由节点 id> | null */
  first_frame: string | null
  duration: number
  estimate_cny: number
  state: FilmClipState
  error: string | null
  error_msg?: ServerMsg | null
  uncertain: boolean
  attempts: FilmAttempt[]
  chosen: number | null
  created_at: string
  queued_at?: string
  ended_at?: string
  ended_as?: 'done' | 'failed' | 'cancelled'
  /** 参考位超出当前厂商上限：删减之前不能生成 */
  over_refs: boolean
}

/** 改自由节点：传了哪些改哪些；null 为清掉 */
export interface FreePatch {
  prompt?: string
  refs?: string[]
  first_frame?: string | null
  duration?: number
  target?: string | null
}

/** 取消接口的结局：dequeued 还没提交 / cancelled 服务商确认取消 / abandoned 不等了（可能仍扣费） */
export type CancelOutcome = 'dequeued' | 'cancelled' | 'abandoned'

/** 本人的一条出片任务（GET /render/tasks）：在跑的，或最近结束的。不带厂商与档位 */
export interface FilmTask {
  /** <版本>:<段或节点 id>；late 的再加 :<任务 id> */
  id: string
  item_id: string
  kind: 'clip' | 'free'
  novel_id: string
  chapter_id: string
  version_id: string
  work_title: string | null
  chapter: string | null
  /** late：取消后服务商仍生成完成（已计费，可采用） */
  state: 'queued' | 'running' | 'downloading' | 'done' | 'failed' | 'cancelled' | 'late'
  /** 服务端算的已等秒数（结束的为总共等了多久）；late 没有 */
  elapsed_sec: number | null
  typical_sec: [number, number]
  /** 在跑的为 null */
  ended_at: string | null
  /** 只有 late 有 */
  cost_cny: number | null
}

export interface FilmSettings {
  provider?: string
  model?: string
  resolution?: string
  audio_mode?: AudioMode
  budget_cny?: number
  confirm_over_cny?: number
}

export interface FilmSession {
  provider: string
  model: string
  resolution: string
  audio_mode: AudioMode
  /** 上限按版本计 */
  budget_cny: number
  /** 单段预估超过它要先确认 */
  confirm_over_cny: number
  spent_cny: number
  /** 说话人 → 用户选的音色 id */
  voices?: Record<string, string>
  /** 合成状态与成片（没合成过为 null 或没有） */
  final?: FinalState | null
  clips: FilmClip[]
  /** 自由节点（旧会话没有） */
  free?: FilmFreeNode[]
  free_seq?: number
  orphaned: { id: string; shots: string[]; attempts: FilmAttempt[]; chosen: number | null }[]
  counts: Partial<Record<FilmClipState, number>>
  /** 批量「出剩余各段」的预估（不含待核对的段） */
  remaining_cny: number
  /** 在排队 / 生成中的段的预估 */
  reserved_cny: number
  uncertain_count: number
  /** 可按新风格图重出的段数 */
  style_outdated_count?: number
  /** 只有取消接口的响应带 */
  cancel_outcome?: CancelOutcome
  /** 验证门：只有读取时带；没有就当已通过（建会话、出片这几个接口本身过门） */
  /** 兼容：message 在后端子计划 4 之前是字符串 */
  gate?: { ok: boolean; message: MsgLike }
  options: {
    providers: string[]
    models: Record<string, { label: string }>
    resolutions: string[]
    cny_per_sec: Record<string, number>
    max_clip_sec: number
    max_refs: number
    /** 厂商能否指定首帧；首帧与参考图能否同用（不能时首帧占一个参考位） */
    first_frame?: boolean
    frame_with_refs?: boolean
    audio_modes: AudioMode[]
    /** 费率说明：消息对象（按界面语言渲染）；旧数据是字符串 */
    rate_note: MsgLike
    /** 一段通常要等多久（秒，[下限, 上限]）：只用于显示「通常 x–y 分钟」 */
    typical_sec?: [number, number]
    /** 缺省厂商回落到 Seedance 的原因代码（文案走 i18n）；没有回落为 null */
    default_note: 'minimax_key_missing' | null
  }
}

/* ---------- 配音与合成（…/render/voices、…/render/compose） ---------- */

export interface TtsVoice { id: string; name: string; gender: 'male' | 'female' }

export interface VoiceSpeaker {
  /** narration 为旁白，其余为角色 id */
  key: string
  name: MsgLike
  /** 分镜里的抽象音色提示（male_elder…） */
  hint: string | null
  /** 现在用的音色（选的或按提示默认）；null 为缺音色 */
  voice: string | null
  /** 用户选的；null 为按提示默认 */
  chosen: string | null
}

export interface VoicesInfo {
  /** 这个声音模式不配音时为 null（音色表为空） */
  provider: string | null
  rate_note: MsgLike
  voices: TtsVoice[]
  speakers: VoiceSpeaker[]
  missing: string[]
}

export interface FinalState {
  state: 'queued' | 'running' | 'done' | 'failed'
  step?: string
  /** 按代码渲染的步骤与失败原因；旧会话没有，退回 step / error */
  step_msg?: ServerMsg | null
  error_msg?: ServerMsg | null
  /** 现有成片（会话目录下的相对路径）；失败时仍是上一次的 */
  files: string[]
  report: string | null
  error: string | null
  /** ffmpeg 的错误输出 */
  detail: string | null
  draft?: boolean
  started_at?: string
  finished_at?: string
  /** 只在合成预览里有：现有成片是否已过期 */
  stale?: boolean
}

export interface MixNote { shot: string; kind: 'speedup' | 'freeze'; speed: number; extend?: number }

export interface MixReport {
  audio_mode: AudioMode
  size: string
  draft: boolean
  /** 对象（新报告）或字符串（旧报告，原样显示） */
  alignment: MsgLike
  warning?: MsgLike
  episodes: { episode: string; seconds: number; notes: MixNote[]; placeholders: string[]; stale: string[] }[]
}

export interface ComposePreview {
  /** 走 TTS 的语音条数 */
  lines: number
  /** 还没缓存的字数与配音费用（合成前要确认） */
  tts_chars: number
  tts_cny: number
  missing_voices: string[]
  voices: Record<string, string>
  /** 没有可用视频的段 */
  no_video: string[]
  fingerprint: string
  final: FinalState | null
  /** 已上传 BGM 的集号 */
  bgm: string[]
  /** 服务器装了 ffmpeg */
  tools: boolean
  /** 各集的选曲参考（分镜 music） */
  music: Record<string, { mood?: Mood; style_hint?: string; curve?: MusicSegment[] }>
  report: MixReport | null
  /** 可否导出剪辑工程（FCPXML）；旧服务端没有这两个字段 */
  exportable?: boolean
  export_reason?: 'none' | 'stale' | 'no_timeline' | 'busy' | null
}

/* ---------- 小说汇总（GET /novels/{nid}/summary，backend/server/summary.py） ---------- */

export interface CostSum {
  llm_usd: number
  render_cny: number | null
  budget_cny: number | null
}

export interface ChapterSum {
  id: string
  version: string | null
  shots: number | null
  duration_s: number | null
  film: { done: number; total: number; failed: number; running: number } | null
  /** 后端目前不会给 stale（它无法判断），类型里留着备用 */
  final: 'none' | 'busy' | 'fresh' | 'stale'
  cost: CostSum | null
}

export interface NovelSummaryData {
  cost: CostSum
  unpriced: boolean
  chapters: ChapterSum[]
}

// ---------- 助手 ----------
export type AssistantStep = StepId
export interface AssistantWhere { chapter_id?: string; version_id?: string; step?: AssistantStep }
export interface AssistantGoto { chapter_id: string; step: AssistantStep }
export interface AssistantTool {
  id: string
  name: string
  args: Record<string, unknown>
  /** null：进行中 */
  ok: boolean | null
  summary: string
  /** 带代码的失败原因（新后端）；有就按代码渲染，没有（旧存档）显示 summary */
  msg?: ServerMsg
}
export type AssistantAction = 'generate_storyboard' | 'film_run' | 'compose' | 'export_fcpxml'
  | 'shots_edit' | 'asset_edit' | 'plot_edit'
/** 操作开始后要跟进度的任务：job 跟 /jobs，film / compose 跟出片会话，export 只是一个下载按钮 */
export interface AssistantTask {
  kind: 'job' | 'film' | 'compose' | 'export' | 'edit'
  /** 改资产卡、改全书梗概时为 null（不属于某一章） */
  chapter_id: string | null
  version_id: string | null
  job_id?: string
}
/** 确认卡上的内容（服务端算好的预估）；待确认时带 id（中断编号，恢复时用） */
export interface AssistantCardInfo {
  id?: string
  tool_call_id: string
  action: AssistantAction
  chapter_id: string | null
  chapter: string
  version_id: string | null
  /** 生成分镜为 null（按模型用量计费，无法预估） */
  amount: number | null
  currency: 'cny' | 'usd' | null
  detail: { clips?: number; chars?: number; archived?: boolean; draft?: boolean; edits?: number }
  /** 改内容：逐条「原 → 新」（值都是显示用的文字） */
  diff?: { target: string; field: string; before: string; after: string }[]
  /** 改镜头：复验不过的原因（应用后版本会标草稿） */
  /** 兼容：后端子计划 4 之前是字符串 */
  warnings?: (string | ServerMsg)[]
}
export interface AssistantCard {
  tool_call_id: string
  action: AssistantAction
  outcome: 'pending' | 'approved' | 'rejected' | 'done' | 'failed' | 'undone'
  card?: AssistantCardInfo | null
  task?: AssistantTask | null
  error?: string
  error_msg?: ServerMsg
  /** 本地标记：点了按钮，恢复请求还没回来 */
  sending?: boolean
}
export interface AssistantMsg {
  role: 'user' | 'assistant'
  text: string
  tools?: AssistantTool[]
  goto?: AssistantGoto[]
  /** 本地标记：用户点了停止 */
  interrupted?: boolean
  /** 本地标记：这一轮出错（显示报错与重试） */
  error?: MsgLike
  /** 提示（如「步骤太多」）：不拼进回答正文 */
  notices?: ServerMsg[]
  cards?: AssistantCard[]
}
export type AssistantEvent =
  | { event: 'token'; data: { text: string } }
  | { event: 'tool_start'; data: { id: string; name: string; args: Record<string, unknown> } }
  | { event: 'tool_end'; data: { id: string; ok: boolean; summary: string; msg?: ServerMsg } }
  | { event: 'goto'; data: AssistantGoto }
  | { event: 'confirm'; data: AssistantCardInfo & { id: string } }
  | { event: 'action'; data: AssistantCard }
  | { event: 'done'; data: Record<string, never> }
  | { event: 'error'; data: ServerMsg | { message: string } }
  | { event: 'notice'; data: ServerMsg }
