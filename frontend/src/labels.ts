/** 枚举值 → 界面标签。IR 里存英文枚举（机器消费），界面按当前语言显示（中英文表在 i18n/zh.ts、en.ts 的 enums 下）。 */
import type {
  AudioMode, CameraAngle, CameraMovement, Derivation, DialogueType, FidelityMode, FilmAttempt, FilmClipState,
  JobStatus, LifecycleEntry, LifecycleType, LocationAngle, Mood, NarrationMode, ShotSize, TimeOfDay,
  Transition, UnitKind,
} from './types'
import { localized, tr } from './i18n/core'
import type { MsgKey } from './i18n/core'
import { en } from './i18n/en'
import { zh } from './i18n/zh'

export const SHOT_SIZE: Record<ShotSize, string> = localized<ShotSize>(zh.enums.shotSize as Record<ShotSize, string>, en.enums.shotSize as Record<ShotSize, string>)

export const CAMERA_MOVEMENT: Record<CameraMovement, string> = localized<CameraMovement>(zh.enums.cameraMovement as Record<CameraMovement, string>, en.enums.cameraMovement as Record<CameraMovement, string>)

export const CAMERA_ANGLE: Record<CameraAngle, string> = localized<CameraAngle>(zh.enums.cameraAngle as Record<CameraAngle, string>, en.enums.cameraAngle as Record<CameraAngle, string>)

export const LOCATION_ANGLE: Record<LocationAngle, string> = localized<LocationAngle>(zh.enums.locationAngle as Record<LocationAngle, string>, en.enums.locationAngle as Record<LocationAngle, string>)

export const TIME_OF_DAY: Record<TimeOfDay, string> = localized<TimeOfDay>(zh.enums.timeOfDay as Record<TimeOfDay, string>, en.enums.timeOfDay as Record<TimeOfDay, string>)

export const DIALOGUE_TYPE: Record<DialogueType, string> = localized<DialogueType>(zh.enums.dialogueType as Record<DialogueType, string>, en.enums.dialogueType as Record<DialogueType, string>)

export const TRANSITION: Record<Transition, string> = localized<Transition>(zh.enums.transition as Record<Transition, string>, en.enums.transition as Record<Transition, string>)

export const DERIVATION: Record<Derivation, string> = localized<Derivation>(zh.enums.derivation as Record<Derivation, string>, en.enums.derivation as Record<Derivation, string>)

export const UNIT_KIND: Record<UnitKind, string> = localized<UnitKind>(zh.enums.unitKind as Record<UnitKind, string>, en.enums.unitKind as Record<UnitKind, string>)

export const MOOD: Record<Mood, string> = localized<Mood>(zh.enums.mood as Record<Mood, string>, en.enums.mood as Record<Mood, string>)

/** 情绪 → 色相，用于 BGM 曲线条与情绪标签的着色 */
export const MOOD_HUE: Record<Mood, number> = {
  calm: 200, warm: 32, playful: 48, tense: 8, ominous: 280,
  eerie: 160, sorrow: 220, melancholy: 250, triumph: 42, epic: 12,
}

export const FIDELITY_MODE: Record<FidelityMode, string> = localized<FidelityMode>(zh.enums.fidelityMode as Record<FidelityMode, string>, en.enums.fidelityMode as Record<FidelityMode, string>)

export const NARRATION_MODE: Record<NarrationMode, string> = localized<NarrationMode>(zh.enums.narrationMode as Record<NarrationMode, string>, en.enums.narrationMode as Record<NarrationMode, string>)

export const JOB_STATUS: Record<JobStatus, string> = localized<JobStatus>(zh.enums.jobStatus as Record<JobStatus, string>, en.enums.jobStatus as Record<JobStatus, string>)

export const PHASE: Record<string, string> = localized(zh.enums.phase, en.enums.phase)

/** 秒数 → 「3 分 05 秒」/「42 秒」 */
export function fmtDuration(sec: number): string {
  const s = Math.max(0, Math.round(sec))
  const m = Math.floor(s / 60)
  return m ? tr('time.minSec', { m, s: String(s % 60).padStart(2, '0') }) : tr('time.sec', { s })
}

/** 剩余时间只给到分钟粒度：按字数线性外推本就粗，精确到秒是假精确 */
export function fmtEta(sec: number): string {
  if (sec < 60) return tr('time.lessThanMin')
  return tr('time.aboutMin', { m: Math.round(sec / 60) })
}

export const INTENSITY: Record<string, string> = localized(zh.enums.intensity, en.enums.intensity)

/** 角色外貌与声音的键是 schema 写死的（additionalProperties: false），
 *  不能当自由键值表编辑——多一个键就是 schema 校验失败。顺序即界面展示顺序。 */
export const appearanceFields = (): [string, string][] => [
  'age', 'gender', 'body', 'face', 'hair', 'eyes', 'distinguishing_marks',
].map((k) => [k, tr(`labels.appearance.${k}` as MsgKey)])

export const voiceFields = (): [string, string][] => [
  'tts_voice', 'tone',
].map((k) => [k, tr(`labels.voice.${k}` as MsgKey)])

/** 找不到映射时原样回显英文，避免界面出现空白 */
export function label<K extends string>(map: Record<K, string>, key?: string): string {
  if (!key) return ''
  return (map as Record<string, string>)[key] ?? key
}

export const LIFECYCLE_TYPE: Record<LifecycleType, string> = localized<LifecycleType>(zh.enums.lifecycleType as Record<LifecycleType, string>, en.enums.lifecycleType as Record<LifecycleType, string>)

export const LIFECYCLE_STATUS: Record<LifecycleEntry['status'], string> = localized<LifecycleEntry['status']>(zh.enums.lifecycleStatus as Record<LifecycleEntry['status'], string>, en.enums.lifecycleStatus as Record<LifecycleEntry['status'], string>)

/** 出片的声音模式（设计文档 1.3 / 3.4） */
export const AUDIO_MODE: Record<AudioMode, string> = localized<AudioMode>(zh.enums.audioMode as Record<AudioMode, string>, en.enums.audioMode as Record<AudioMode, string>)

export const FILM_STATE: Record<FilmClipState, string> = localized<FilmClipState>(zh.enums.filmState as Record<FilmClipState, string>, en.enums.filmState as Record<FilmClipState, string>)

export const ATTEMPT_STATE: Record<FilmAttempt['state'], string> = localized<FilmAttempt['state']>(zh.enums.attemptState as Record<FilmAttempt['state'], string>, en.enums.attemptState as Record<FilmAttempt['state'], string>)
