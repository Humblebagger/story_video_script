/** 小说汇总（花费与各章进度）：nid 或 refreshKey 变化时重新拉取；失败时 data 保持 null，不报错。 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { getNovelSummary } from './api'
import type { NovelSummaryData } from './types'

export function useNovelSummary(nid: string | undefined, refreshKey: unknown = 0) {
  // 记下数据属于哪部小说：切换小说后、新数据到之前不显示上一部的
  const [got, setGot] = useState<{ nid: string; data: NovelSummaryData } | null>(null)
  const seq = useRef(0)

  const reload = useCallback(async () => {
    const n = ++seq.current
    if (!nid) { setGot(null); return }
    try {
      const d = await getNovelSummary(nid)
      if (n === seq.current) setGot({ nid, data: d })
    } catch {
      if (n === seq.current) setGot(null)
    }
  }, [nid])

  useEffect(() => {
    void reload()
    const counter = seq
    return () => { counter.current++ }
  }, [reload, refreshKey])

  return { data: got && got.nid === nid ? got.data : null, reload }
}
