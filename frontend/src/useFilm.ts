/** 画布上的出片会话：读取、建立、改设置、出片（含确认金额）、采用、静音、轮询，以及片段文件的 blob URL。
 *
 *  只有存进后端的版本才有出片（version 为空 = 本地 JSON / 分批预览，什么都不做、不发请求）。
 *  花钱的两步（单段超过确认线、批量出剩余各段）先进 confirm，用户点确认才发请求；
 *  服务端重算的金额对不上（409）就把新金额放回 confirm 让用户再确认。 */
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  ApiError, cancelFilmItem, chooseFilmAttempt, chooseFreeAttempt, conflictCny, createFilm, createFreeNode,
  deleteFreeNode, filmFileUrl, getFilm, muteFilmClip, patchFilm, patchFreeNode, runFilmClip, runFilmRest, runFreeNode,
} from './api'
import { pokeFilmTasks } from './filmTasks'
import { primeNotifications } from './notify'
import { tr } from './i18n/core'
import { errValue, formatMsg } from './i18n/serverMsg'
import type { MsgLike } from './i18n/serverMsg'
import { clockOffset, needsConfirm, pollDelay } from './film'
import type { CancelOutcome, FilmClip, FilmSession, FilmSettings, FreePatch, VersionRef } from './types'

export type FilmConfirm =
  | { kind: 'clip'; clipId: string; cny: number; changed: boolean; uncertain?: boolean }
  | { kind: 'rest'; cny: number; changed: boolean }

export function useFilm(version: VersionRef | null | undefined, opts: { active: boolean }) {
  const { nid, cid, vid } = version ?? {}
  const enabled = !!(nid && cid && vid)
  const [session, setSession] = useState<FilmSession | null>(null)
  /** off：没有版本（不出片）；none：还没建会话 */
  const [status, setStatus] = useState<'off' | 'loading' | 'none' | 'ready'>(enabled ? 'loading' : 'off')
  /** 读取失败（轮询、取文件）：下一次读取成功就清掉 */
  const [readError, setReadError] = useState<MsgLike>(null)
  /** 操作失败（出片、取消等）：读取成功不清它，直到用户关掉提示或再次操作 */
  const [opError, setOpError] = useState<MsgLike>(null)
  const error = opError ?? readError
  /** 服务端时钟减本地时钟（毫秒），每次收到响应时重算：等待时长用（本地 now + 偏差）减排队时刻 */
  const [skew, setSkew] = useState(0)
  /** 验证门没过的原因（读取时报告的，或出片被 422 拦下的） */
  const [gate, setGate] = useState<MsgLike>(null)
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
    if (s.server_now) setSkew(clockOffset(s.server_now, Date.now()))
    setStatus('ready')
    if (s.gate) setGate(s.gate.ok ? null : (s.gate.message ?? tr('film.gateFailed')))
    else if (passedGate) setGate(null)
  }, [])

  /** 验证门拦截记到 gate（按钮据此禁用），其余显示原因 */
  const fail = useCallback((e: unknown, read = false) => {
    if (e instanceof ApiError && e.verification) setGate(errValue(e))
    else (read ? setReadError : setOpError)(errValue(e))
  }, [])

  /** 读取会话；成功返回读到的会话（取消的重新确认要拿最新的），失败 / 过期 / 没有为 null */
  const load = useCallback(async (): Promise<FilmSession | null> => {
    if (!nid || !cid || !vid) return null
    const mine = gen.current
    try {
      const got = await getFilm(nid, cid, vid)
      if (gen.current !== mine) return null
      accept(got)
      setReadError(null)
      return got
    } catch (e) {
      if (gen.current !== mine) return null
      if (e instanceof ApiError && e.status === 404) {
        setSession(null)
        setStatus('none')
      } else {
        fail(e, true)
        setStatus((st) => (st === 'loading' ? 'none' : st))
      }
      return null
    } finally {
      if (gen.current === mine) setTick((n) => n + 1)
    }
  }, [nid, cid, vid, accept, fail])

  useEffect(() => {
    setSession(null)
    setReadError(null)
    setOpError(null)
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
    setOpError(null)
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

  /** 花钱请求的唯一执行体：返回结局，由两个薄封装各自处理确认框 / 卡片。
   *  stale 为请求期间会话已换（切版本等），结果作废；revised 为服务端重算的金额对不上（409 带新金额） */
  const runPaid = useCallback(async (fn: () => Promise<FilmSession>):
      Promise<{ kind: 'ok' | 'stale' | 'failed' } | { kind: 'revised'; cny: number }> => {
    const mine = gen.current
    primeNotifications()     // 出片要等几分钟：趁这次点击申请通知权限，出完好提醒
    setBusy(true)
    setOpError(null)
    try {
      const got = await fn()
      if (gen.current !== mine) return { kind: 'stale' }
      accept(got, true)
      pokeFilmTasks()
      return { kind: 'ok' }
    } catch (e) {
      if (gen.current !== mine) return { kind: 'stale' }
      const fresh = conflictCny(e)
      if (fresh !== null) {
        void load()
        return { kind: 'revised', cny: fresh }
      }
      fail(e)
      return { kind: 'failed' }
    } finally {
      if (gen.current === mine) setBusy(false)
    }
  }, [accept, fail, load])

  /** 取消排队或生成中的一段 / 一个自由节点：expect 是用户确认时的种类（free 不花钱 / paid 不等了）。
   *  成功返回结局：先用响应里的会话（去掉 cancel_outcome）更新界面，再重新读取刷新（失败只显示读取错误）；
   *  服务端发现种类已变（409 kind_changed）返回 'changed'，调用方重新读取后以新种类重新确认；
   *  其他被拒记到操作错误（刷新成功也不清）并重读会话 */
  const cancelItem = useCallback(async (itemId: string, free: boolean, expect?: 'free' | 'paid'):
      Promise<CancelOutcome | 'changed' | null> => {
    const mine = gen.current
    setBusy(true)
    setOpError(null)
    try {
      const got = await cancelFilmItem(nid!, cid!, vid!, itemId, free, expect)
      if (gen.current !== mine) return null
      // 先用响应里的会话立即更新（服务商不可用时是降级视图，结构完整，只是少了闸门信息）；
      // 再重读刷新，重读失败只显示读取错误，不退回取消前的状态
      const { cancel_outcome: outcome, ...next } = got
      accept(next)
      pokeFilmTasks()
      await load()
      return outcome ?? null
    } catch (e) {
      if (gen.current !== mine) return null
      if (e instanceof ApiError && e.status === 409 && (e.detail as { code?: unknown } | null)?.code === 'film.cancel.kind_changed') {
        return 'changed'
      }
      fail(e)
      void load()
      return null
    } finally {
      if (gen.current === mine) setBusy(false)
    }
  }, [nid, cid, vid, accept, fail, load])

  /** 花钱的操作（确认框）：409 带了重算金额就放回确认框，等用户再确认 */
  const spend = async (fn: () => Promise<FilmSession>, again: (cny: number) => FilmConfirm) => {
    const r = await runPaid(fn)
    if (r.kind === 'ok' || r.kind === 'failed') setConfirm(null)
    else if (r.kind === 'revised') setConfirm(again(r.cny))
  }
  const sendClip = (clipId: string, cny?: number) =>
    spend(() => runFilmClip(nid!, cid!, vid!, clipId, cny),
          (fresh) => ({ kind: 'clip', clipId, cny: fresh, changed: cny !== undefined }))
  const sendRest = (cny: number) =>
    spend(() => runFilmRest(nid!, cid!, vid!, cny), (fresh) => ({ kind: 'rest', cny: fresh, changed: true }))

  /** 卡片内确认的花钱操作（节点图）：成功返回 null；服务端重算的金额对不上返回新金额，由卡片再问一次 */
  const spendInline = async (fn: () => Promise<FilmSession>): Promise<number | null> => {
    const r = await runPaid(fn)
    return r.kind === 'revised' ? r.cny : null
  }
  /** 改自由节点（卡片上的防抖保存要用稳定的引用） */
  const patchFree = useCallback((fid: string, patch: FreePatch) =>
    apply(() => patchFreeNode(nid!, cid!, vid!, fid, patch)), [apply, nid, cid, vid])

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
      .catch((e) => { if (gen.current === mine) setReadError(tr('film.readClipFailed', { error: formatMsg(errValue(e)) })) })
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
    enabled, session, status, error, gate, clockOffset: skew,
    /** 关掉操作与读取的错误提示 */
    dismissError: () => { setOpError(null); setReadError(null) },
    busy, confirm, files, load, ensure,
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
    cancelItem,
    /** 节点图卡片：确认过金额后直接出这一段 */
    runClipNow: (clipId: string, cny: number) => spendInline(() => runFilmClip(nid!, cid!, vid!, clipId, cny)),
    createFree: (fromClip?: string) => apply(() => createFreeNode(nid!, cid!, vid!, fromClip)),
    patchFree,
    deleteFree: (fid: string) => apply(() => deleteFreeNode(nid!, cid!, vid!, fid)),
    runFree: (fid: string, cny: number) => spendInline(() => runFreeNode(nid!, cid!, vid!, fid, cny)),
    chooseFree: (fid: string, attempt: number) => apply(() => chooseFreeAttempt(nid!, cid!, vid!, fid, attempt)),
  }
}

export type Film = ReturnType<typeof useFilm>
