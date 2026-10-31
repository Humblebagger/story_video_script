/** 章节页的只读出片状态：出片会话（404 = 还没有）与成片是否过期（有成片时才读合成预览）。
 *  只发 GET、不花钱；404 当「没有」，其他读取失败保留上一次的值，不弹错（出片面板里有完整的错误处理）。
 *  版本变了先清空再重读（不让上一版的状态串过来）；reload() 重读但不清空；换版本时之前的响应丢弃。
 *  loaded：这个版本的第一次读取是否已落地（会话与合成预览一起落地，不会只来一半）。 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, getCompose, getFilm } from './api'
import type { ComposePreview, FilmSession, VersionRef } from './types'

const KEEP = Symbol('keep')
const is404 = (e: unknown) => e instanceof ApiError && e.status === 404

export function useChapterFlow(version: VersionRef | null) {
  const { nid, cid, vid } = version ?? {}
  const [film, setFilm] = useState<FilmSession | null>(null)
  const [compose, setCompose] = useState<ComposePreview | null>(null)
  /** 第一次读取已落地的版本 */
  const [loadedFor, setLoadedFor] = useState<string | null>(null)
  const gen = useRef(0)
  const filmRef = useRef(film)
  filmRef.current = film

  const reload = useCallback(async () => {
    const mine = ++gen.current
    if (!nid || !cid || !vid) { setFilm(null); setCompose(null); setLoadedFor(null); return }
    let s: FilmSession | null | typeof KEEP
    try { s = await getFilm(nid, cid, vid) } catch (e) { s = is404(e) ? null : KEEP }
    if (gen.current !== mine) return
    const session = s === KEEP ? filmRef.current : s
    let p: ComposePreview | null | typeof KEEP = null
    if (session) {
      try { p = await getCompose(nid, cid, vid, session.final?.draft ?? true) } catch (e) { p = is404(e) ? null : KEEP }
    }
    if (gen.current !== mine) return
    if (s !== KEEP) setFilm(s)
    if (p !== KEEP) setCompose(p)
    setLoadedFor(vid)
  }, [nid, cid, vid])

  // 换版本：先清掉上一版的状态（手动 reload 不清）
  useEffect(() => {
    setFilm(null)
    setCompose(null)
    setLoadedFor(null)
  }, [nid, cid, vid])

  useEffect(() => { void reload() }, [reload])

  return {
    film, compose, finalStale: !!compose?.final?.stale, reload,
    /** 当前版本的第一次读取已落地；没有版本时恒为 true */
    loaded: !vid || loadedFor === vid,
  }
}
