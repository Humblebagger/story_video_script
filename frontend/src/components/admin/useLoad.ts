import { useEffect, useState } from 'react'
import { errValue } from '@/i18n/serverMsg'
import type { MsgLike } from '@/i18n/serverMsg'

/** 拉一次数据；everyMs 给了就定时刷新；reload() 手动刷新。 */
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[], everyMs?: number) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<MsgLike>(null)
  const [tick, setTick] = useState(0)

  useEffect(() => {
    let alive = true
    fn().then((d) => { if (alive) { setData(d); setError(null) } })
      .catch((e: unknown) => { if (alive) setError(errValue(e)) })
    return () => { alive = false }
    // fn 每次渲染都是新闭包，依赖由调用方给出
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick])

  useEffect(() => {
    if (!everyMs) return
    const t = window.setInterval(() => setTick((x) => x + 1), everyMs)
    return () => clearInterval(t)
  }, [everyMs])

  return { data, error, reload: () => setTick((x) => x + 1) }
}
