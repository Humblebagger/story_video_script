/** 章节页的只读出片状态：出片会话（404 = 还没有）与合成预览（有会话时就读：配音金额、成片是否过期）。
 *  只发 GET、不花钱；404 当「没有」，其他读取失败保留上一次的值，不弹错（出片面板里有完整的错误处理）。
 *  版本变了先清空再重读（不让上一版的状态串过来）；reload() 重读但不清空；换版本时之前的响应丢弃。
 *  loaded：这个版本的第一次读取是否已落地（会话与合成预览一起落地，不会只来一半）。
 *  pending：有一次读取在路上（重读开始时同步置上），这期间的值可能是旧的，跟步与完成提示要等它落地。 */
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
  const [pending, setPending] = useState(false)
  const gen = useRef(0)
  const filmRef = useRef(film)
  filmRef.current = film
  const loadedForRef = useRef(loadedFor)
  loadedForRef.current = loadedFor

  const reload = useCallback(async () => {
    const mine = ++gen.current
    if (!nid || !cid || !vid) { setFilm(null); setCompose(null); setLoadedFor(null); setPending(false); return }
    setPending(true)
    let s: FilmSession | null | typeof KEEP
    try { s = await getFilm(nid, cid, vid) } catch (e) { s = is404(e) ? null : KEEP }
    if (gen.current !== mine) return
    // 读失败时保留上一次的会话——但只限同一个版本；新版本的第一次读取失败就当还没有，不拿上一版的成片去查合成
    const session = s === KEEP ? (loadedForRef.current === vid ? filmRef.current : null) : s
    let p: ComposePreview | null | typeof KEEP = null
    if (session) {
      try { p = await getCompose(nid, cid, vid, session.final?.draft ?? true) } catch (e) { p = is404(e) ? null : KEEP }
    }
    if (gen.current !== mine) return
    if (s !== KEEP) setFilm(s)
    if (p !== KEEP) setCompose(p)
    setLoadedFor(vid)
    setPending(false)
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
    /** 有一次读取在路上（值可能是旧的） */
    pending,
  }
}
