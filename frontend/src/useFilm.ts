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
  | { kind: 'clip'; clipId: string; cny: number; changed: boolean; uncertain?: boolean }
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
  /** 每次读取结束加一：让轮询定时器在成功或失败后都重新排上 */
  const [tick, setTick] = useState(0)
  const [confirm, setConfirm] = useState<FilmConfirm | null>(null)
  /** 会话目录下的相对路径 → blob URL */
  const [files, setFiles] = useState<Record<string, string>>({})
  const live = useRef<Record<string, string>>({})
  const asking = useRef(new Set<string>())

  /** 换版本 / 卸载时加一：之前没取回来的文件取回后直接回收 */
  const gen = useRef(0)

  /** 读取会话带 gate；写操作的响应不带：通过了门的操作（建、改设置、出片）清掉旧提示，采用 / 静音保持原样 */
  const accept = useCallback((s: FilmSession, passedGate = false) => {
    setSession(s)
    setStatus('ready')
    if (s.gate) setGate(s.gate.ok ? null : (s.gate.message ?? '分镜未通过独立验证'))
    else if (passedGate) setGate(null)
  }, [])

  /** 验证门拦截记到 gate（按钮据此禁用），其余显示原因 */
  const fail = useCallback((e: unknown) => {
    if (e instanceof ApiError && e.verification) setGate(e.message)
    else setError(msg(e))
  }, [])

  const load = useCallback(async () => {
    if (!nid || !cid || !vid) return
    const mine = gen.current
    try {
      const got = await getFilm(nid, cid, vid)
      if (gen.current !== mine) return
      accept(got)
      setError(null)
    } catch (e) {
      if (gen.current !== mine) return
      if (e instanceof ApiError && e.status === 404) {
        setSession(null)
        setStatus('none')
      } else {
        fail(e)
        setStatus((st) => (st === 'loading' ? 'none' : st))
      }
    } finally {
      if (gen.current === mine) setTick((n) => n + 1)
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
  }, [status, session, opts.active, load, tick])

  /** 不花钱的操作：忙标记、清错误、成功后收下新会话 */
  const apply = useCallback(async (fn: () => Promise<FilmSession>, passedGate = false) => {
    const mine = gen.current
    setBusy(true)
    setError(null)
    try {
      const got = await fn()
      if (gen.current !== mine) return
      accept(got, passedGate)
    } catch (e) {
      if (gen.current !== mine) return
      fail(e)
    } finally {
      if (gen.current === mine) setBusy(false)
    }
  }, [accept, fail])

  /** 花钱的操作：409 带了重算金额就放回确认框，等用户再确认 */
  const spend = async (fn: () => Promise<FilmSession>, again: (cny: number) => FilmConfirm) => {
    const mine = gen.current
    setBusy(true)
    setError(null)
    try {
      const got = await fn()
      if (gen.current !== mine) return
      accept(got, true)
      setConfirm(null)
    } catch (e) {
      if (gen.current !== mine) return
      const fresh = conflictCny(e)
      if (fresh !== null) {
        setConfirm(again(fresh))
        void load()
      } else {
        setConfirm(null)
        fail(e)
      }
    } finally {
      if (gen.current === mine) setBusy(false)
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
    /** 版本 id（没有版本时都为 undefined）：配音与合成用同一会话 */
    ids: { nid, cid, vid },
    create: () => apply(() => createFilm(nid!, cid!, vid!), true),
    saveSettings: (patch: FilmSettings) => apply(() => patchFilm(nid!, cid!, vid!, patch), true),
    /** 出这一段：超过确认线先弹确认，确认后才发请求 */
    runClip: (c: FilmClip) => {
      // 待核对的段重做一律先确认（可能已扣费）；其余超过确认线才确认
      if (c.uncertain || (session && needsConfirm(c, session))) {
        setConfirm({ kind: 'clip', clipId: c.id, cny: c.estimate_cny, changed: false, uncertain: c.uncertain })
        return Promise.resolve()
      }
      // 带上界面显示的金额：保存后服务端重算对不上就 409 重新确认
      return sendClip(c.id, c.estimate_cny)
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
