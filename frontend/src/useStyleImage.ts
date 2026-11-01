/** 小说风格参考图的 blob URL：hash 为空返回 null；hash 变了重取；卸载或换图时 revoke；取失败返回 null、不报错。 */
import { useEffect, useState } from 'react'
import { styleImageUrl } from './api'

export function useStyleImage(nid: string, hash: string | null | undefined): string | null {
  const [state, setState] = useState<{ key: string; url: string } | null>(null)
  useEffect(() => {
    if (!hash) return
    const key = `${nid}:${hash}`
    let alive = true
    let made: string | null = null
    styleImageUrl(nid).then((u) => {
      if (!alive) { URL.revokeObjectURL(u); return }
      made = u
      setState({ key, url: u })
    }).catch(() => { if (alive) setState(null) })
    return () => { alive = false; if (made) URL.revokeObjectURL(made) }
  }, [nid, hash])
  return hash && state?.key === `${nid}:${hash}` ? state.url : null
}
