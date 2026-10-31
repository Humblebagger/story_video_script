/** 章节工作流的纯计算：六步的完成判断、「该做的那一步」、各步状态、各步主按钮（动作、金额、拦截原因与修复目标）。
 *  界面只吃这里的结果；单测见 tests/workflow.test.ts。原因与按钮文字是语言包的键，界面再翻译。 */
import type { MsgKey } from './i18n/core'
import type { ComposePreview, FilmSession, VersionSummary } from './types'

export const STEPS = ['import', 'storyboard', 'review', 'render', 'compose', 'download'] as const
export type StepId = (typeof STEPS)[number]

const OK = ['succeeded', 'completed_with_warnings']

export interface FlowInput {
  /** 本章原文非空（按已保存的算） */
  hasText: boolean
  /** 原文框里有没保存的改动 */
  textDirty: boolean
  /** 本章有生成在跑 */
  converting: boolean
  /** 正在看的版本摘要；还没有版本为 null */
  version: VersionSummary | null
  /** 分镜有未保存的修改 */
  dirty: boolean
  /** 保存后复验没通过 */
  verificationFailed: boolean
  /** 出片会话：null = 还没有（或还没读到） */
  film: FilmSession | null
  /** 成片已过期（合成预览给的） */
  finalStale: boolean
  /** 合成预览（只用来显示配音金额）；没读到为 null */
  compose: ComposePreview | null
}

export function stepDone(id: StepId, f: FlowInput): boolean {
  switch (id) {
    case 'import': return f.hasText
    case 'storyboard': return !!f.version && OK.includes(f.version.status) && !f.converting
    case 'review': return stepDone('storyboard', f) && !f.dirty && !f.verificationFailed
      && f.version?.verification_status !== 'failed'
    case 'render': return !!f.film && f.film.clips.length > 0 && f.film.clips.every((c) => c.state === 'done')
    case 'compose': return f.film?.final?.state === 'done' && !f.finalStale
    case 'download': return false
  }
}

/** 按顺序取第一个没完成的步骤；前五步都完成就是 ⑥ */
export function currentStep(f: FlowInput): StepId {
  return STEPS.find((id) => !stepDone(id, f)) ?? 'download'
}

export interface StepState {
  id: StepId
  state: 'done' | 'current' | 'locked'
  /** 灰掉时：要先完成第几步（1 起） */
  needs?: number
}

export function stepStates(f: FlowInput): StepState[] {
  const cur = STEPS.indexOf(currentStep(f))
  return STEPS.map((id, i) => i < cur ? { id, state: 'done' }
    : i === cur ? { id, state: 'current' } : { id, state: 'locked', needs: cur + 1 })
}

export interface Fix {
  /** 切到哪一步 */
  step?: StepId
  /** 再滚到并高亮哪个元素（id） */
  target?: string
}

export interface Primary {
  action: 'saveText' | 'goto' | 'generate' | 'save' | 'openFilm' | 'none'
  label: MsgKey
  goto?: StepId
  cny?: number
  count?: number
  blocked?: { reason: MsgKey; fix: Fix }
}

const block = (p: Omit<Primary, 'blocked'>, reason: MsgKey, fix: Fix): Primary => ({ ...p, blocked: { reason, fix } })

/** 第 id 步右下角的主按钮 */
export function primaryFor(id: StepId, f: FlowInput): Primary {
  switch (id) {
    case 'import': {
      if (f.textDirty) return { action: 'saveText', label: 'flow.primary.saveText' }
      const p: Primary = { action: 'goto', goto: 'storyboard', label: 'flow.primary.next' }
      return f.hasText ? p : block(p, 'flow.block.noText', { step: 'import', target: 'chapter-source' })
    }
    case 'storyboard': {
      const p: Primary = { action: 'generate', label: f.version ? 'flow.primary.regenerate' : 'flow.primary.generate' }
      if (f.converting) return block({ ...p, label: 'flow.primary.generating' }, 'flow.block.converting', {})
      if (!f.hasText) return block(p, 'flow.block.noText', { step: 'import', target: 'chapter-source' })
      if (f.textDirty) return block(p, 'flow.block.textDirty', { step: 'import', target: 'chapter-source' })
      return p
    }
    case 'review': {
      if (f.dirty) return { action: 'save', label: 'flow.primary.save' }
      const p: Primary = { action: 'goto', goto: 'render', label: 'flow.primary.next' }
      if (!stepDone('storyboard', f)) return block(p, 'flow.block.noVersion', { step: 'storyboard' })
      if (f.verificationFailed || f.version?.verification_status === 'failed') {
        return block(p, 'flow.block.verify', { step: 'review', target: 'verification' })
      }
      return p
    }
    case 'render': {
      const s = f.film
      const rest = s ? s.clips.filter((c) => (c.state === 'planned' || c.state === 'failed') && !c.uncertain) : []
      const tried = !!s?.clips.some((c) => c.state === 'done')
      const p: Primary = !s ? { action: 'openFilm', label: 'flow.primary.startFilm' }
        : !rest.length ? { action: 'openFilm', label: 'flow.primary.viewFilm' }
        : tried ? { action: 'openFilm', label: 'flow.primary.renderRest', count: rest.length, cny: s.remaining_cny }
        : { action: 'openFilm', label: 'flow.primary.tryOne', cny: rest[0].estimate_cny }
      if (!stepDone('storyboard', f)) return block(p, 'flow.block.noVersion', { step: 'storyboard' })
      if (f.dirty) return block(p, 'flow.block.dirty', { step: 'review', target: 'storyboard-save' })
      if (f.verificationFailed || f.version?.verification_status === 'failed') {
        return block(p, 'flow.block.verify', { step: 'review', target: 'verification' })
      }
      return p
    }
    case 'compose': {
      const p: Primary = { action: 'openFilm', label: 'flow.primary.compose', cny: f.compose?.tts_cny }
      if (f.dirty) return block(p, 'flow.block.dirty', { step: 'review', target: 'storyboard-save' })
      if (!f.film) return block(p, 'flow.block.noFilm', { step: 'render' })
      return p
    }
    case 'download':
      return { action: 'none', label: 'flow.primary.next' }
  }
}
