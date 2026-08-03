/** 枚举值 → 中文标签。IR 里存英文枚举（机器消费），界面上一律显示中文。 */
import type {
  CameraAngle, CameraMovement, Derivation, DialogueType, FidelityMode,
  JobStatus, LocationAngle, Mood, NarrationMode, ShotSize, TimeOfDay,
  Transition, UnitKind,
} from './types'

export const SHOT_SIZE: Record<ShotSize, string> = {
  extreme_wide: '大远景', wide: '远景', full: '全景', medium: '中景',
  medium_close: '中近景', close_up: '特写', extreme_close_up: '大特写', insert: '插入镜',
}

export const CAMERA_MOVEMENT: Record<CameraMovement, string> = {
  static: '固定', push_in: '推', pull_out: '拉', pan: '摇', tilt: '俯仰摇',
  track: '移', follow: '跟', orbit: '环绕', crane: '升降', handheld: '手持', zoom: '变焦',
}

export const CAMERA_ANGLE: Record<CameraAngle, string> = {
  eye_level: '平视', high: '俯拍', low: '仰拍', overhead: '顶拍',
  dutch: '斜角', pov: '主观视角', over_shoulder: '过肩',
}

export const LOCATION_ANGLE: Record<LocationAngle, string> = {
  front: '正面', reverse: '反打', side: '侧面', overhead: '顶视', establishing: '定场',
}

export const TIME_OF_DAY: Record<TimeOfDay, string> = {
  dawn: '黎明', day: '白天', dusk: '黄昏', night: '夜晚',
}

export const DIALOGUE_TYPE: Record<DialogueType, string> = {
  dialogue: '台词', inner_monologue: '内心独白', voiceover: '画外音',
}

export const TRANSITION: Record<Transition, string> = {
  cut: '硬切', dissolve: '叠化', fade_to_black: '淡出黑场',
  match_cut: '匹配剪辑', whip_pan: '甩镜',
}

export const DERIVATION: Record<Derivation, string> = {
  explicit: '原文明写', inferred: '系统补充', transition: '过渡镜',
}

export const UNIT_KIND: Record<UnitKind, string> = {
  action: '动作', dialogue: '对白', psychology: '心理',
  description: '描写', narration_meta: '叙述',
}

export const MOOD: Record<Mood, string> = {
  calm: '平静', warm: '温暖', playful: '轻快', tense: '紧张', ominous: '不祥',
  eerie: '诡异', sorrow: '悲恸', melancholy: '怅惘', triumph: '昂扬', epic: '史诗',
}

/** 情绪 → 色相，用于 BGM 曲线条与情绪标签的着色 */
export const MOOD_HUE: Record<Mood, number> = {
  calm: 200, warm: 32, playful: 48, tense: 8, ominous: 280,
  eerie: 160, sorrow: 220, melancholy: 250, triumph: 42, epic: 12,
}

export const FIDELITY_MODE: Record<FidelityMode, string> = {
  faithful: '忠实转换', pacing_optimized: '节奏优化', adapted: '改编',
}

export const NARRATION_MODE: Record<NarrationMode, string> = {
  original_text: '原文照念', selective: '择要旁白', condensed: '压缩概述', none: '无旁白',
}

export const JOB_STATUS: Record<JobStatus, string> = {
  queued: '排队中', running: '转换中', succeeded: '已完成',
  completed_with_warnings: '完成（质量告警）', failed: '失败',
}

export const INTENSITY: Record<string, string> = { low: '弱', mid: '中', high: '强' }

/** 角色外貌与声音的键是 schema 写死的（additionalProperties: false），
 *  不能当自由键值表编辑——多一个键就是 schema 校验失败。顺序即界面展示顺序。 */
export const APPEARANCE_FIELDS: [string, string][] = [
  ['age', '年龄'], ['gender', '性别'], ['body', '体型'], ['face', '面容'],
  ['hair', '发型'], ['eyes', '眼睛'], ['distinguishing_marks', '标志性特征'],
]

export const VOICE_FIELDS: [string, string][] = [
  ['tts_voice', '音色'], ['tone', '语气'],
]

/** 找不到映射时原样回显英文，避免界面出现空白 */
export function label<K extends string>(map: Record<K, string>, key?: string): string {
  if (!key) return ''
  return (map as Record<string, string>)[key] ?? key
}
