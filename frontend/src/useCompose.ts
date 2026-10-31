/** 「出片」页签里的配音与合成：读预览与音色表、改音色、上传删除 BGM、合成（配音金额先确认）、合成中轮询、
 *  成片文件的 blob URL。
 *
 *  预览随出片会话里会影响合成的部分变化重读（composeKey），分镜保存后（dirty 由真变假）也重读；合成在跑时
 *  3 秒一读，跑完让出片会话也重读（配音费计入了已花）。配音金额大于 0 先进 confirm；服务端重算对不上
 *  （409 带金额）或重读出的金额变了，就换成新金额再确认。
 *
 *  报错分两份：读取的（loadError，只由 load 设和清）与操作的（actionError，下一次操作开始时才清），
 *  免得操作失败后紧跟的重读把原因清掉。 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { conflictCny, deleteBgm, filmFileUrl, getCompose, getVoices, putBgm, putVoices, startCompose } from './api'
import { COMPOSE_POLL_MS, bgmType, composeKey, composing } from './compose'
import type { ComposePreview, VoicesInfo } from './types'
import type { Film } from './useFilm'

const msg = (e: unknown) => (e instanceof Error ? e.message : String(e))

export function useCompose(film: Film, dirty: boolean) {
  const { nid, cid, vid } = film.ids
  const key = film.session ? composeKey(film.session) : ''
  const reloadFilm = film.load
  const [preview, setPreview] = useState<ComposePreview | null>(null)
  const [voices, setVoices] = useState<VoicesInfo | null>(null)
  const [draft, setDraft] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  /** 音色表读取失败：只挡音色那一块，预览照常显示 */
  const [voicesError, setVoicesError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  /** 每次读取结束加一：合成中的轮询定时器据此重排 */
  const [tick, setTick] = useState(0)
  const [confirm, setConfirm] = useState<{ cny: number; changed: boolean } | null>(null)
  /** `合成完成时间|相对路径` → blob URL */
  const [files, setFiles] = useState<Record<string, string>>({})
  const live = useRef<Record<string, string>>({})
  const asking = useRef(new Set<string>())
  /** 换版本 / 卸载时加一：之前的响应一律丢弃 */
  const gen = useRef(0)
  /** 每次读取加一：只有最后一次读取的响应算数 */
  const seq = useRef(0)

  const load = useCallback(async () => {
    if (!nid || !cid || !vid) return
    const mine = gen.current
    const n = ++seq.current
    const current = () => gen.current === mine && seq.current === n
    try {
      const p = await getCompose(nid, cid, vid, draft)
      if (!current()) return
      let v: VoicesInfo | null = null
      let ve: string | null = null
      if (p.lines) {
        try { v = await getVoices(nid, cid, vid) } catch (e) { ve = msg(e) }
        if (!current()) return
      }
      setPreview(p)
      setVoices(v)
      setVoicesError(ve)
      setLoadError(null)
      // 确认框开着时金额变了：换成新金额再确认
      setConfirm((c) => (c && c.cny !== p.tts_cny ? { cny: p.tts_cny, changed: true } : c))
    } catch (e) {
      if (current()) setLoadError(msg(e))
    } finally {
      if (current()) setTick((x) => x + 1)
    }
  }, [nid, cid, vid, draft])

  useEffect(() => { void load() }, [load, key])

  // 分镜刚保存（有未保存 → 没有）：合成预览跟着重读
  const wasDirty = useRef(dirty)
  useEffect(() => {
    if (wasDirty.current && !dirty) void load()
    wasDirty.current = dirty
  }, [dirty, load])

  const running = composing(preview)
  useEffect(() => {
    if (!running) return
    const id = setTimeout(() => void load(), COMPOSE_POLL_MS)
    return () => clearTimeout(id)
  }, [running, load, tick])

  // 合成跑完（在跑 → 不在跑）：出片会话也重读
  const was = useRef(false)
  useEffect(() => {
    if (was.current && !running) void reloadFilm()
    was.current = running
  }, [running, reloadFilm])

  /** 成片文件按合成完成时间区分：重新合成后同一路径取新的 */
  const stamp = preview?.final?.finished_at ?? ''
  const ensure = useCallback((path?: string | null) => {
    if (!path || !nid || !cid || !vid) return
    const k = `${stamp}|${path}`
    if (live.current[k] || asking.current.has(k)) return
    const mine = gen.current
    asking.current.add(k)
    filmFileUrl(nid, cid, vid, path)
      .then((url) => {
        if (gen.current !== mine) { URL.revokeObjectURL(url); return }
        live.current[k] = url
        setFiles({ ...live.current })
      })
      .catch((e) => { if (gen.current === mine) setActionError(`读取成片文件失败：${msg(e)}`) })
      .finally(() => asking.current.delete(k))
  }, [nid, cid, vid, stamp])
  const url = (path?: string | null) => (path ? files[`${stamp}|${path}`] : undefined)

  // 换了一次合成：上一次的 blob 回收
  useEffect(() => {
    for (const [k, u] of Object.entries(live.current)) {
      if (!k.startsWith(`${stamp}|`)) {
        URL.revokeObjectURL(u)
        delete live.current[k]
      }
    }
    setFiles({ ...live.current })
  }, [stamp])
  useEffect(() => () => {
    gen.current += 1
    for (const u of Object.values(live.current)) URL.revokeObjectURL(u)
    live.current = {}
    asking.current.clear()
  }, [nid, cid, vid])

  /** 不花钱的操作：忙标记、清上一次操作的错误、成功后重读预览 */
  const apply = useCallback(async (fn: () => Promise<unknown>) => {
    const mine = gen.current
    setBusy(true)
    setActionError(null)
    try {
      await fn()
      if (gen.current === mine) await load()
    } catch (e) {
      if (gen.current === mine) setActionError(msg(e))
    } finally {
      if (gen.current === mine) setBusy(false)
    }
  }, [load])

  /** 花钱的一步：带确认过的配音金额发请求；409 带金额就放回确认框，不带（音色刚改过、正在合成）就写原因 */
  const send = async (cny: number) => {
    const mine = gen.current
    setBusy(true)
    setActionError(null)
    try {
      await startCompose(nid!, cid!, vid!, draft, cny)
      if (gen.current !== mine) return
      setConfirm(null)
      await Promise.all([load(), reloadFilm()])
    } catch (e) {
      if (gen.current !== mine) return
      const fresh = conflictCny(e)
      if (fresh !== null) setConfirm({ cny: fresh, changed: true })
      else {
        setConfirm(null)
        setActionError(msg(e))
      }
      void load()
    } finally {
      if (gen.current === mine) setBusy(false)
    }
  }

  return {
    preview, voices, voicesError, draft, error: actionError ?? loadError, busy, confirm, load, ensure, url,
    setDraft,
    setVoice: (speaker: string, voice: string) => apply(() => putVoices(nid!, cid!, vid!, { [speaker]: voice })),
    uploadBgm: (episode: string, file: File) => {
      const type = bgmType(file)
      if (!type) {
        setActionError('BGM 只支持 mp3、wav、m4a、aac')
        return Promise.resolve()
      }
      return apply(() => putBgm(nid!, cid!, vid!, episode, file, type))
    },
    removeBgm: (episode: string) => apply(() => deleteBgm(nid!, cid!, vid!, episode)),
    /** 合成整章：配音金额大于 0 先弹确认 */
    start: () => {
      if (!preview) return
      if (preview.tts_cny > 0) setConfirm({ cny: preview.tts_cny, changed: false })
      else void send(0)
    },
    confirmNow: () => (confirm ? send(confirm.cny) : Promise.resolve()),
    cancelConfirm: () => setConfirm(null),
  }
}

export type Compose = ReturnType<typeof useCompose>
