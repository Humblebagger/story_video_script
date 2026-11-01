/** 三栏视图用的关键帧图：只读已上传的图，每镜一张 blob URL。
 *
 *  与 useKeyframes 的区别：这里不请求出图提示词（renderKeyframes），只列出、取图；
 *  上传、删除、改提示词都不在这里。读失败静默给空表，出图的报错归画布管。
 */
import { useEffect, useState } from 'react'
import { keyframeUrl, listKeyframes } from './api'
import type { VersionRef } from './types'

export function useShotImages(version: VersionRef | null | undefined, reloadKey: unknown): Record<string, string> {
  const [urls, setUrls] = useState<Record<string, string>>({})
  const { nid, cid, vid } = version ?? {}

  useEffect(() => {
    if (!nid || !cid || !vid) return
    let gone = false
    const live: Record<string, string> = {}
    void (async () => {
      try {
        const { shots } = await listKeyframes(nid, cid, vid)
        for (const s of shots) {
          const url = await keyframeUrl(nid, cid, vid, s)
          if (gone) { URL.revokeObjectURL(url); return }
          live[s] = url
        }
        if (!gone) setUrls({ ...live })
      } catch { /* 读不到就当没有图 */ }
    })()
    return () => {
      gone = true
      for (const u of Object.values(live)) URL.revokeObjectURL(u)
      setUrls({})
    }
  }, [nid, cid, vid, reloadKey])

  return urls
}
