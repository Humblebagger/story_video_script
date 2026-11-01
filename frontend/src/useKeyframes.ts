/** 静帧预演的数据：每镜的关键帧出图提示词 + 已上传的关键帧图（blob URL）。
 *
 *  出图模型暂不接：提示词拿去任意工具出图，再把图传回来挂到镜头上。
 *  图挂在版本上（不进 IR），所以只有存进后端的版本能上传；本地打开的 JSON / 分批预览只有提示词。
 *  提示词可以手改（改的是拿去出图的那段文字，不动 IR），改动按版本记在本机浏览器里，复制 / 下载都用改后的。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { tr } from './i18n/core'
import { deleteKeyframe, keyframeUrl, listKeyframes, renderKeyframes, uploadKeyframe } from './api'
import type { KeyframePrompt, Storyboard, VersionRef } from './types'

export function useKeyframes(doc: Storyboard, version: VersionRef | null | undefined) {
  const [prompts, setPrompts] = useState<Record<string, KeyframePrompt>>({})
  const [urls, setUrls] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const live = useRef<Record<string, string>>({})
  const { nid, cid, vid } = version ?? {}
  const editKey = nid && cid && vid ? `kf-prompt-edits:${nid}/${cid}/${vid}` : null
  const [edits, setEdits] = useState<Record<string, string>>({})

  useEffect(() => {
    let saved: Record<string, string> = {}
    try { if (editKey) saved = JSON.parse(localStorage.getItem(editKey) ?? '{}') } catch { /* 读不到就当没改过 */ }
    setEdits(saved)
  }, [editKey])

  /** 改某镜的提示词；传 null 恢复成生成的原文 */
  const editPrompt = useCallback((shotId: string, text: string | null) => {
    setEdits((old) => {
      const next = { ...old }
      if (text === null) delete next[shotId]
      else next[shotId] = text
      try { if (editKey) localStorage.setItem(editKey, JSON.stringify(next)) } catch { /* 存不下只影响下次打开 */ }
      return next
    })
  }, [editKey])

  /** 生效的提示词：手改过的优先 */
  const promptOf = useCallback((shotId: string): KeyframePrompt | undefined => {
    const k = prompts[shotId]
    return k && shotId in edits ? { ...k, prompt: edits[shotId] } : k
  }, [prompts, edits])

  useEffect(() => {
    let gone = false
    renderKeyframes(doc)
      .then((r) => { if (!gone) setPrompts(Object.fromEntries(r.keyframes.map((k) => [k.shot_id, k]))) })
      .catch((e) => { if (!gone) setError(tr('keyframes.promptFailed', { error: e instanceof Error ? e.message : String(e) })) })
    return () => { gone = true }
  }, [doc])

  const put = useCallback((shotId: string, url: string | null) => {
    const old = live.current[shotId]
    if (old) URL.revokeObjectURL(old)
    if (url) live.current[shotId] = url
    else delete live.current[shotId]
    setUrls({ ...live.current })
  }, [])

  useEffect(() => {
    if (!nid || !cid || !vid) return
    let gone = false
    void (async () => {
      try {
        const { shots } = await listKeyframes(nid, cid, vid)
        for (const s of shots) {
          const url = await keyframeUrl(nid, cid, vid, s)
          if (gone) { URL.revokeObjectURL(url); return }
          put(s, url)
        }
      } catch (e) {
        if (!gone) setError(tr('keyframes.readFailed', { error: e instanceof Error ? e.message : String(e) }))
      }
    })()
    return () => {
      gone = true
      for (const u of Object.values(live.current)) URL.revokeObjectURL(u)
      live.current = {}
      setUrls({})
    }
  }, [nid, cid, vid, put])

  const upload = useCallback(async (shotId: string, file: File) => {
    if (!nid || !cid || !vid) return
    setBusy(shotId)
    setError(null)
    try {
      await uploadKeyframe(nid, cid, vid, shotId, file)
      put(shotId, URL.createObjectURL(file))
    } catch (e) {
      setError(tr('keyframes.uploadFailed', { error: e instanceof Error ? e.message : String(e) }))
    } finally {
      setBusy(null)
    }
  }, [nid, cid, vid, put])

  const remove = useCallback(async (shotId: string) => {
    if (!nid || !cid || !vid) return
    try {
      await deleteKeyframe(nid, cid, vid, shotId)
      put(shotId, null)
    } catch (e) {
      setError(tr('keyframes.deleteFailed', { error: e instanceof Error ? e.message : String(e) }))
    }
  }, [nid, cid, vid, put])

  return { prompts, urls, error, busy, canUpload: !!(nid && cid && vid), upload, remove,
           edited: edits, editPrompt, promptOf }
}

/** 全部关键帧提示词导出成一份文本，方便整批拿去出图工具 */
export function promptSheet(title: string, list: KeyframePrompt[]): string {
  return [tr('keyframes.sheetTitle', { title, n: list.length }), '', ...list.flatMap((k) => [
    `## ${k.shot_id}（${k.aspect_ratio}）`, k.prompt,
    ...(k.negative_prompt ? [tr('keyframes.negative', { text: k.negative_prompt })] : []),
    ...(k.reference_assets.length ? [tr('keyframes.refs', { list: k.reference_assets.join(tr('common.listSep')) })] : []), ''])].join('\n')
}
