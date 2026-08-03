/** NovelStoryboard v0.4 分镜 IR 的 TypeScript 镜像（对齐 backend/schema/storyboard.schema.json）。
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

export interface CharacterAsset {
  id: string
  name: string
  aliases?: string[]
  appearance?: Record<string, string>
  outfits?: { id: string; name?: string; visual_prompt?: string }[]
  visual_prompt?: string
  reference_images?: { view?: string; prompt?: string }[]
  voice?: Record<string, string>
  persona_notes?: string
}

export interface LocationAsset {
  id: string
  name: string
  era?: string
  interior_exterior?: 'interior' | 'exterior' | 'both'
  visual_prompt?: string
  angles?: { angle?: LocationAngle; visual_prompt?: string }[]
  lighting_defaults?: string
}

export interface PropAsset {
  id: string
  name: string
  visual_prompt?: string
  reference_images?: { view?: string; prompt?: string }[]
  states?: { id: string; name?: string; visual_prompt?: string }[]
}

export interface CreatureAsset {
  id: string
  name: string
  aliases?: string[]
  species?: string
  visual_prompt?: string
  reference_images?: { view?: string; prompt?: string }[]
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
  creature_refs?: { ref: string }[]
  prop_refs?: ShotPropRef[]
  action: string
  atmosphere?: string
  dialogue?: DialogueLine[]
  narration?: ShotNarration
  sfx?: string[]
  transition_out?: Transition
  source: { unit_refs: string[]; derivation: Derivation; note?: string }
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
  /** 沿用历史资产库：模型须复用其中的 ID 与描述，防跨章角色漂移 */
  seed_assets?: Assets | null
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
  runs_dir?: string
  history_count?: number
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

/** 按作品聚合的历史资产库 */
export interface AssetWork {
  work_title: string
  updated_at: string
  runs: number
  counts: Record<string, number>
  assets: Assets
}
