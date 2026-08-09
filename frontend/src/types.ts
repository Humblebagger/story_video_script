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

export interface ConvertRequest {
  text: string
  work_title: string
  chapter: string
  style_prefix: string
  art_style: string
  color_tone: string
  aspect_ratio: AspectRatio
  target_platform: string
  narration_mode: NarrationMode
  tts_voice: string
  strict: boolean
  /** 自动沿用本人该作品的资产库（模型须复用其中的 ID 与描述，防跨章角色漂移） */
  use_library?: boolean
  /** 显式指定一份资产库，优先于 use_library */
  seed_assets?: Assets | null
  /** 转换成功后把产物里的资产卡并回库 */
  import_assets?: boolean
}

export interface Job {
  id: string
  status: JobStatus
  log: string[]
  result: Storyboard | null
  quality_report: string | null
  error: string | null
  created_at?: string
  work_title?: string
  chapter?: string
  chars?: number
}

/** 任务摘要：用于关掉页面后重新接上仍在后台跑的转换 */
export interface JobSummary {
  id: string
  status: JobStatus
  created_at: string | null
  work_title: string | null
  chapter: string | null
  chars: number | null
  log_lines: number
  last_log: string | null
}

export interface Health {
  status: string
  model: string
  api_key_configured: boolean
  users?: number
}

/* ---------- 历史记录（后端 runs/ 落盘） ---------- */

export interface HistorySummary {
  id: string
  created_at: string
  edited_at: string | null
  status: JobStatus
  work_title: string | null
  chapter: string | null
  units: number
  episodes: number
  shots: number
  has_quality_report: boolean
}

export interface HistoryRecord {
  id: string
  created_at: string
  edited_at: string | null
  status: JobStatus
  params: Record<string, string>
  quality_report: string | null
  result: Storyboard
}

/* ---------- 资产库（独立于任何一次转换的一等实体） ---------- */


export interface LibraryWork {
  work_title: string
  updated_at: string
  counts: Record<string, number>
  /** 列表接口只返回统计，取单部作品时才带上卡片 */
  assets?: Assets
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
}
