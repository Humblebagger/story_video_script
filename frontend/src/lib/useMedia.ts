/** 订阅一条媒体查询；环境没有 matchMedia（如部分单测）时恒为 false。 */
import { useEffect, useState } from 'react'

export function useMedia(query: string): boolean {
  const mq = () => (typeof window !== 'undefined' && window.matchMedia ? window.matchMedia(query) : null)
  const [on, setOn] = useState(() => !!mq()?.matches)
  useEffect(() => {
    const m = mq()
    if (!m) return
    const fn = () => setOn(m.matches)
    fn()
    m.addEventListener?.('change', fn)
    return () => m.removeEventListener?.('change', fn)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query])
  return on
}
