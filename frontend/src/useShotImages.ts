/** 三栏视图用的关键帧图：只读已上传的图，每镜一张 blob URL。
 *
 *  与 useKeyframes 的区别：这里不请求出图提示词（renderKeyframes），只列出、取图；
 *  上传、删除、改提示词都不在这里。读失败静默，出图的报错归画布管。
 *
 *  每镜单独取：一镜失败只跳过这一镜；取到一张就显示一张。reloadKey 变化时旧图留着，
 *  新图到了再换（不闪空白）；换版本或卸载才清空并回收。
 */
import { useEffect, useRef, useState } from 'react'
import { keyframeUrl, listKeyframes } from './api'
import type { VersionRef } from './types'

export function useShotImages(version: VersionRef | null | undefined, reloadKey: unknown): Record<string, string> {
  const [urls, setUrls] = useState<Record<string, string>>({})
  const { nid, cid, vid } = version ?? {}
  const cur = useRef<Record<string, string>>({})   // 当前显示着的 URL（归本 hook 回收）

  // 换版本或卸载：清空并回收
  useEffect(() => () => {
    for (const u of Object.values(cur.current)) URL.revokeObjectURL(u)
    cur.current = {}
    setUrls({})
  }, [nid, cid, vid])

  // 刷新：逐镜取，到一张换一张；旧 URL 在被替换时回收
  useEffect(() => {
    if (!nid || !cid || !vid) return
    let gone = false
    void (async () => {
      let shots: string[] = []
      try { shots = (await listKeyframes(nid, cid, vid)).shots ?? [] } catch { return }
      const queue = [...shots]
      const worker = async () => {
        for (let s = queue.shift(); s !== undefined; s = queue.shift()) {
          let url: string
          try { url = await keyframeUrl(nid, cid, vid, s) } catch { continue }
          if (gone) { URL.revokeObjectURL(url); continue }
          const old = cur.current[s]
          cur.current = { ...cur.current, [s]: url }
          setUrls(cur.current)
          if (old) URL.revokeObjectURL(old)
        }
      }
      await Promise.all(Array.from({ length: Math.min(4, queue.length) }, worker))
      if (gone) return
      // 已不存在的镜头：撤掉旧图
      const keep = new Set(shots)
      const stale = Object.keys(cur.current).filter((k) => !keep.has(k))
      if (stale.length) {
        const next = { ...cur.current }
        for (const k of stale) { URL.revokeObjectURL(next[k]); delete next[k] }
        cur.current = next
        setUrls(next)
      }
    })()
    return () => { gone = true }
  }, [nid, cid, vid, reloadKey])

  return urls
}
