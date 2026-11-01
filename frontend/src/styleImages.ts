/** 风格卡片的用户替换图：只存本机 localStorage，只作卡片显示，不上传、不进参数。 */
import { useSyncExternalStore } from 'react'
import { tr } from './i18n/core'
import { notice } from './lib/notice'

const KEY = 'inkreel.styleImages'
const MAX_SIDE = 320
const MAX_RAW = 1.5 * 1024 * 1024

type ImageMap = Record<string, string>

const read = (): ImageMap => {
  try {
    const raw = localStorage.getItem(KEY)
    const v = raw ? JSON.parse(raw) : {}
    return v && typeof v === 'object' ? v as ImageMap : {}
  } catch { return {} }
}

let snapshot: ImageMap = read()
const listeners = new Set<() => void>()
const publish = (next: ImageMap) => { snapshot = next; listeners.forEach((l) => l()) }

export const getStyleImage = (id: string): string | undefined => snapshot[id]

/** 订阅图片变化：卡片组件用它在换图 / 恢复默认后重绘 */
export function useStyleImages(): ImageMap {
  return useSyncExternalStore(
    (cb) => { listeners.add(cb); return () => { listeners.delete(cb) } },
    () => snapshot,
    () => snapshot,
  )
}

const readDataUrl = (blob: Blob) => new Promise<string>((resolve, reject) => {
  const fr = new FileReader()
  fr.onload = () => resolve(String(fr.result))
  fr.onerror = () => reject(fr.error)
  fr.readAsDataURL(blob)
})

/** 缩成最长边 320px 的 JPEG；没有 canvas / createImageBitmap（测试环境）时退化成直接读文件 */
async function raw(file: Blob): Promise<string> {
  if (file.size > MAX_RAW) throw new Error('too large')
  return await readDataUrl(file)
}

async function shrink(file: Blob): Promise<string> {
  try {
    if (typeof createImageBitmap !== 'function') return await raw(file)
    const bmp = await createImageBitmap(file)
    const k = Math.min(1, MAX_SIDE / Math.max(bmp.width, bmp.height))
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.round(bmp.width * k))
    canvas.height = Math.max(1, Math.round(bmp.height * k))
    const ctx = canvas.getContext('2d')
    if (!ctx) return await raw(file)
    ctx.drawImage(bmp, 0, 0, canvas.width, canvas.height)
    const blob = await new Promise<Blob | null>((r) => canvas.toBlob(r, 'image/jpeg', 0.85))
    return await (blob ? readDataUrl(blob) : raw(file))
  } catch {
    return await raw(file)
  }
}

/** 存成功返回 true；读图或写存储失败时 notice.err 并保持原样 */
export async function setStyleImage(id: string, file: Blob): Promise<boolean> {
  try {
    const url = await shrink(file)
    const next = { ...snapshot, [id]: url }
    localStorage.setItem(KEY, JSON.stringify(next))
    publish(next)
    return true
  } catch (e) {
    notice.err(tr(e instanceof Error && e.message === 'too large' ? 'params.styleImageTooBig' : 'params.styleImageFail'))
    return false
  }
}

export function clearStyleImage(id: string): void {
  const next = { ...snapshot }
  delete next[id]
  try { localStorage.setItem(KEY, JSON.stringify(next)) } catch { /* 存不下也先在内存里恢复 */ }
  publish(next)
}
