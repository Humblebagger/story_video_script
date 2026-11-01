/** 章节工作台 ↔ 助手：当前位置（工作台发布、助手读）与跳转请求（助手发出、工作台接）。模块级小存储，不需要 Provider。 */
import { useSyncExternalStore } from 'react'
import type { AssistantStep, AssistantWhere } from '@/types'

let where: AssistantWhere = {}
const whereSubs = new Set<() => void>()

export function setWhere(w: AssistantWhere): void {
  if (w.chapter_id === where.chapter_id && w.version_id === where.version_id && w.step === where.step) return
  where = w
  whereSubs.forEach((f) => f())
}

export function getWhere(): AssistantWhere { return where }

export function useWhere(): AssistantWhere {
  return useSyncExternalStore((cb) => { whereSubs.add(cb); return () => { whereSubs.delete(cb) } }, getWhere, getWhere)
}

type Want = { chapter_id: string; step: AssistantStep }
let wanted: Want | null = null
const wantSubs = new Set<() => void>()

/** 请求跳到某章某步：章节已打开就立即生效；还没打开，等它的工作台挂载后用 takeStep 取走 */
export function requestStep(chapter_id: string, step: AssistantStep): void {
  wanted = { chapter_id, step }
  wantSubs.forEach((f) => f())
}

/** 取走发给这一章的跳转请求（只取一次） */
export function takeStep(chapter_id: string): AssistantStep | null {
  if (!wanted || wanted.chapter_id !== chapter_id) return null
  const s = wanted.step
  wanted = null
  return s
}

/** 撤掉发给这一章、还没被取走的跳转请求（打开章节没成功时） */
export function cancelStep(chapter_id: string): void {
  if (wanted?.chapter_id === chapter_id) wanted = null
}

export function onStepRequest(cb: () => void): () => void {
  wantSubs.add(cb)
  return () => { wantSubs.delete(cb) }
}
