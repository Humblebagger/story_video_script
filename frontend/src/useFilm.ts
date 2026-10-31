/** 画布上的出片会话：读取、建立、改设置、出片（含确认金额）、采用、静音、轮询，以及片段文件的 blob URL。
 *
 *  只有存进后端的版本才有出片（version 为空 = 本地 JSON / 分批预览，什么都不做、不发请求）。
 *  花钱的两步（单段超过确认线、批量出剩余各段）先进 confirm，用户点确认才发请求；
 *  服务端重算的金额对不上（409）就把新金额放回 confirm 让用户再确认。 */
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  ApiError, chooseFilmAttempt, conflictCny, createFilm, filmFileUrl, getFilm, muteFilmClip, patchFilm,
  runFilmClip, runFilmRest,
} from './api'
import { needsConfirm, pollDelay } from './film'
import type { FilmClip, FilmSession, FilmSettings, VersionRef } from './types'

export type FilmConfirm =
  | { kind: 'clip'; clipId: string; cny: number; changed: boolean }
  | { kind: 'rest'; cny: number; changed: boolean }

const msg = (e: unknown) => (e instanceof Error ? e.message : String(e))

export function useFilm(version: VersionRef | null | undefined, opts: { active: boolean }) {
  const { nid, cid, vid } = version ?? {}
  const enabled = !!(nid && cid && vid)
  const [session, setSession] = useState<FilmSession | null>(null)
  /** off：没有版本（不出片）；none：还没建会话 */
  const [status, setStatus] = useState<'off' | 'loading' | 'none' | 'ready'>(enabled ? 'loading' : 'off')
  const [error, setError] = useState<string | null>(null)
  /** 验证门没过的原因（读取时报告的，或出片被 422 拦下的） */
  const [gate, setGate] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [confirm, setConfirm] = useState<FilmConfirm | null>(null)
  /** 会话目录下的相对路径 → blob URL */
  const [files, setFiles] = useState<Record<string, string>>({})
  const live = useRef<Record<string, string>>({})
  const asking = useRef(new Set<string>())
  /** 换版本 / 卸载时加一：之前没取回来的文件取回后直接回收 */
  const gen = useRef(0)

  const accept = useCallback((s: FilmSession) => {
    setSession(s)
    setStatus('ready')
    setGate(s.gate && !s.gate.ok ? (s.gate.message ?? '分镜未通过独立验证') : null)
  }, [])

  /** 验证门拦截记到 gate（按钮据此禁用），其余显示原因 */
  const fail = useCallback((e: unknown) => {
    if (e instanceof ApiError && e.verification) setGate(e.message)
    else setError(msg(e))
  }, [])

  const load = useCallback(async () => {
    if (!nid || !cid || !vid) return
    try {
      accept(await getFilm(nid, cid, vid))
      setError(null)
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        setSession(null)
        setStatus('none')
      } else {
        fail(e)
        setStatus((st) => (st === 'loading' ? 'none' : st))
      }
    }
  }, [nid, cid, vid, accept, fail])

  useEffect(() => {
    setSession(null)
    setError(null)
    setGate(null)
    setConfirm(null)
    setStatus(enabled ? 'loading' : 'off')
    if (enabled) void load()
  }, [enabled, load])

  // 轮询：页签开着且有段在跑 5 秒，否则 30 秒
  useEffect(() => {
    if (status !== 'ready') return
    const id = setTimeout(() => void load(), pollDelay(session, opts.active))
    return () => clearTimeout(id)
  }, [status, session, opts.active, load])

  /** 不花钱的操作：忙标记、清错误、成功后收下新会话 */
  const apply = useCallback(async (fn: () => Promise<FilmSession>) => {
    setBusy(true)
    setError(null)
    try {
      accept(await fn())
    } catch (e) {
      fail(e)
    } finally {
      setBusy(false)
    }
  }, [accept, fail])

  /** 花钱的操作：409 带了重算金额就放回确认框，等用户再确认 */
  const spend = async (fn: () => Promise<FilmSession>, again: (cny: number) => FilmConfirm) => {
    setBusy(true)
    setError(null)
    try {
      accept(await fn())
      setConfirm(null)
    } catch (e) {
      const fresh = conflictCny(e)
      if (fresh !== null) {
        setConfirm(again(fresh))
      } else {
        setConfirm(null)
        fail(e)
      }
    } finally {
      setBusy(false)
    }
  }
  const sendClip = (clipId: string, cny?: number) =>
    spend(() => runFilmClip(nid!, cid!, vid!, clipId, cny),
          (fresh) => ({ kind: 'clip', clipId, cny: fresh, changed: cny !== undefined }))
  const sendRest = (cny: number) =>
    spend(() => runFilmRest(nid!, cid!, vid!, cny), (fresh) => ({ kind: 'rest', cny: fresh, changed: true }))

  /** 取一个片段文件（视频、尾帧）的 blob URL：每个只取一次 */
  const ensure = useCallback((path: string | null | undefined) => {
    if (!path || !nid || !cid || !vid || live.current[path] || asking.current.has(path)) return
    const mine = gen.current
    asking.current.add(path)
    filmFileUrl(nid, cid, vid, path)
      .then((url) => {
        if (gen.current !== mine) { URL.revokeObjectURL(url); return }
        live.current[path] = url
        setFiles({ ...live.current })
      })
      .catch((e) => { if (gen.current === mine) setError(`读取片段文件失败：${msg(e)}`) })
      .finally(() => asking.current.delete(path))
  }, [nid, cid, vid])
  useEffect(() => () => {
    gen.current += 1
    for (const u of Object.values(live.current)) URL.revokeObjectURL(u)
    live.current = {}
    asking.current.clear()
    setFiles({})
  }, [nid, cid, vid])

  return {
    enabled, session, status, error, gate, busy, confirm, files, load, ensure,
    create: () => apply(() => createFilm(nid!, cid!, vid!)),
    saveSettings: (patch: FilmSettings) => apply(() => patchFilm(nid!, cid!, vid!, patch)),
    /** 出这一段：超过确认线先弹确认，确认后才发请求 */
    runClip: (c: FilmClip) => {
      if (session && needsConfirm(c, session)) {
        setConfirm({ kind: 'clip', clipId: c.id, cny: c.estimate_cny, changed: false })
        return Promise.resolve()
      }
      return sendClip(c.id)
    },
    /** 批量出剩余各段：一律先弹确认 */
    runRest: () => {
      if (session) setConfirm({ kind: 'rest', cny: session.remaining_cny, changed: false })
    },
    confirmNow: () => (!confirm ? Promise.resolve()
      : confirm.kind === 'clip' ? sendClip(confirm.clipId, confirm.cny) : sendRest(confirm.cny)),
    cancelConfirm: () => setConfirm(null),
    choose: (clipId: string, attempt: number) =>
      apply(() => chooseFilmAttempt(nid!, cid!, vid!, clipId, attempt)),
    mute: (clipId: string, mute: boolean) => apply(() => muteFilmClip(nid!, cid!, vid!, clipId, mute)),
  }
}

export type Film = ReturnType<typeof useFilm>
