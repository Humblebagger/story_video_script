/** 章节页的只读出片状态：出片会话（404 = 还没有）与成片是否过期（有成片时才读合成预览）。
 *  只发 GET、不花钱；读取失败当「没有」，不弹错（出片面板里有完整的错误处理）。
 *  版本变了、调用 reload() 时重读；换版本时之前的响应丢弃。 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { getCompose, getFilm } from './api'
import type { ComposePreview, FilmSession, VersionRef } from './types'

export function useChapterFlow(version: VersionRef | null) {
  const { nid, cid, vid } = version ?? {}
  const [film, setFilm] = useState<FilmSession | null>(null)
  const [compose, setCompose] = useState<ComposePreview | null>(null)
  const gen = useRef(0)

  const reload = useCallback(async () => {
    const mine = ++gen.current
    if (!nid || !cid || !vid) { setFilm(null); setCompose(null); return }
    let s: FilmSession | null = null
    try { s = await getFilm(nid, cid, vid) } catch { s = null }
    if (gen.current !== mine) return
    setFilm(s)
    let p: ComposePreview | null = null
    if (s) {
      try { p = await getCompose(nid, cid, vid, s.final?.draft ?? true) } catch { p = null }
    }
    if (gen.current === mine) setCompose(p)
  }, [nid, cid, vid])

  useEffect(() => { void reload() }, [reload])

  return { film, compose, finalStale: !!compose?.final?.stale, reload }
}
