/** 小说汇总（花费与各章进度）：nid 或 refreshKey 变化时重新拉取；失败时 data 保持 null，不报错。 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { getNovelSummary } from './api'
import type { NovelSummaryData } from './types'

export function useNovelSummary(nid: string | undefined, refreshKey: unknown = 0) {
  const [data, setData] = useState<NovelSummaryData | null>(null)
  const seq = useRef(0)

  const reload = useCallback(async () => {
    const n = ++seq.current
    if (!nid) { setData(null); return }
    try {
      const d = await getNovelSummary(nid)
      if (n === seq.current) setData(d)
    } catch {
      if (n === seq.current) setData(null)
    }
  }, [nid])

  useEffect(() => {
    void reload()
    const counter = seq
    return () => { counter.current++ }
  }, [reload, refreshKey])

  return { data, reload }
}
