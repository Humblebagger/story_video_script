import { useCallback, useEffect, useState } from 'react'
import {
  backfillLibrary, createLibraryWork, deleteCard, deleteLibraryWork, getLibraryWork,
  listLibrary, upsertCard,
} from '../api'
import type { AssetKind } from '../edit'
import type { Assets, LibraryWork } from '../types'
import { AssetsView } from './AssetsView'

const KIND_LABEL: Record<AssetKind, string> = {
  characters: '角色 C', locations: '场景 S', props: '道具 P', creatures: '生物 A',
}
/** 各类资产的惯用 ID 前缀，新建时按现有卡数自动续号 */
const KIND_PREFIX: Record<AssetKind, string> = {
  characters: 'C', locations: 'S', props: 'P', creatures: 'A',
}

function nextId(assets: Assets, kind: AssetKind): string {
  const prefix = KIND_PREFIX[kind]
  const used = new Set((assets[kind] ?? []).map((c) => c.id))
  for (let n = 1; n < 1000; n++) {
    const id = `${prefix}${String(n).padStart(2, '0')}`
    if (!used.has(id)) return id
  }
  return `${prefix}${Date.now()}`
}

export function LibraryView() {
  const [works, setWorks] = useState<LibraryWork[]>([])
  const [title, setTitle] = useState<string | null>(null)
  const [assets, setAssets] = useState<Assets>({})
  const [dirty, setDirty] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)
  const [alert, setAlert] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  // 新建卡片表单
  const [newKind, setNewKind] = useState<AssetKind>('characters')
  const [newName, setNewName] = useState('')
  const [newWork, setNewWork] = useState('')
  const [query, setQuery] = useState('')

  const refreshWorks = useCallback(async () => {
    setLoading(true)
    try {
      const { works: list } = await listLibrary()
      setWorks(list)
      return list
    } catch (e) {
      setAlert(e instanceof Error ? e.message : String(e))
      return []
    } finally {
      setLoading(false)
    }
  }, [])

  const openWork = useCallback(async (t: string) => {
    if (dirty.size && !confirm('有未保存的修改，确定切换作品？')) return
    setAlert(null)
    try {
      const w = await getLibraryWork(t)
      setTitle(t)
      setAssets(w.assets ?? {})
      setDirty(new Set())
    } catch (e) {
      setAlert(e instanceof Error ? e.message : String(e))
    }
  }, [dirty.size])

  useEffect(() => {
    void refreshWorks().then((list) => {
      if (list.length) void openWork(list[0].work_title)
    })
    // 首次进入自动打开最近更新的作品；后续切换由用户点选
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshWorks])

  const patchCard = (kind: AssetKind, id: string, patch: Record<string, unknown>) => {
    setAssets((prev) => ({
      ...prev,
      [kind]: (prev[kind] ?? []).map((c) => (c.id === id ? { ...c, ...patch } : c)),
    }))
    setDirty((prev) => new Set(prev).add(`${kind}:${id}`))
  }

  const save = async () => {
    if (!title || !dirty.size) return
    setBusy(true)
    setAlert(null)
    try {
      for (const key of dirty) {
        const [kind, id] = key.split(':') as [AssetKind, string]
        const card = (assets[kind] ?? []).find((c) => c.id === id)
        if (card) await upsertCard(title, kind, card)
      }
      setDirty(new Set())
      await refreshWorks()
    } catch (e) {
      setAlert(`保存失败：${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setBusy(false)
    }
  }

  const addCard = async () => {
    const name = newName.trim()
    if (!title || !name) return
    const card = { id: nextId(assets, newKind), name }
    setBusy(true)
    setAlert(null)
    try {
      await upsertCard(title, newKind, card)
      setAssets((prev) => ({ ...prev, [newKind]: [...(prev[newKind] ?? []), card]
        .sort((a, b) => a.id.localeCompare(b.id)) }))
      setNewName('')
      await refreshWorks()
    } catch (e) {
      setAlert(`新建失败：${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setBusy(false)
    }
  }

  const removeCard = async (kind: AssetKind, id: string) => {
    if (!title) return
    if (!confirm(`删除资产卡 ${id}？\n\n注意：已有分镜若引用了它，那份产物再校验会报「引用不存在的资产」。`)) return
    try {
      await deleteCard(title, kind, id)
      setAssets((prev) => ({ ...prev, [kind]: (prev[kind] ?? []).filter((c) => c.id !== id) }))
      setDirty((prev) => {
        const next = new Set(prev)
        next.delete(`${kind}:${id}`)
        return next
      })
      await refreshWorks()
    } catch (e) {
      setAlert(`删除失败：${e instanceof Error ? e.message : String(e)}`)
    }
  }

  const addWork = async () => {
    const t = newWork.trim()
    if (!t) return
    setBusy(true)
    setAlert(null)
    try {
      await createLibraryWork(t)
      setNewWork('')
      await refreshWorks()
      await openWork(t)
    } catch (e) {
      setAlert(`新建作品失败：${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setBusy(false)
    }
  }

  /** 早于「自动入库」的转换、以及关掉入库的转换，资产都不在库里——一键补齐 */
  const backfill = async () => {
    setBusy(true)
    setAlert(null)
    try {
      const { works: filled } = await backfillLibrary()
      const list = await refreshWorks()
      if (!filled.length) {
        setAlert('历史记录里没有可补齐的资产卡（可能还没跑过成功的转换）。')
      } else {
        const n = filled.reduce((a, w) => a + w.added, 0)
        setAlert(`已从历史记录补齐：${filled.map((w) => `《${w.work_title}》新增 ${w.added} 张`)
          .join('，')}${n ? '' : '（都已在库中）'}`)
        if (!title && list.length) void openWork(list[0].work_title)
      }
    } catch (e) {
      setAlert(`补齐失败：${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setBusy(false)
    }
  }

  const removeWork = async () => {
    if (!title) return
    if (!confirm(`删除《${title}》的整个资产库？该操作不可撤销。`)) return
    try {
      await deleteLibraryWork(title)
      setTitle(null)
      setAssets({})
      setDirty(new Set())
      const list = await refreshWorks()
      if (list.length) void openWork(list[0].work_title)
    } catch (e) {
      setAlert(`删除失败：${e instanceof Error ? e.message : String(e)}`)
    }
  }

  const total = (w: LibraryWork) =>
    Object.values(w.counts ?? {}).reduce((a, b) => a + b, 0)

  /** 搜索按 ID / 名称 / 别名 / 各类描述匹配——卡多了光靠肉眼翻很痛苦 */
  const q = query.trim().toLowerCase()
  const hit = (c: Record<string, unknown>) => {
    if (!q) return true
    const bag = [c.id, c.name, c.visual_prompt, c.persona_notes, c.notes,
                 c.species, c.era, c.lighting_defaults,
                 ...((c.aliases as string[]) ?? []),
                 ...Object.values((c.appearance as Record<string, string>) ?? {}),
                 ...(((c.outfits ?? c.states) as { name?: string }[]) ?? [])
                   .map((x) => x?.name)]
    return bag.some((v) => typeof v === 'string' && v.toLowerCase().includes(q))
  }
  const shown: Assets = q
    ? Object.fromEntries((Object.entries(assets) as [AssetKind, Record<string, unknown>[]][])
        .map(([k, list]) => [k, (list ?? []).filter(hit)])
        .filter(([, list]) => (list as unknown[]).length)) as Assets
    : assets
  const shownCount = Object.values(shown).reduce((a, l) => a + (l?.length ?? 0), 0)
  const allCount = Object.values(assets).reduce((a, l) => a + (l?.length ?? 0), 0)

  return (
    <div className="lib">
      <header className="lib__head">
        <div>
          <h2>资产库</h2>
          <p className="lib__hint">
            资产卡在这里是一等实体，独立于任何一次转换：可新建、可改、可删。
            转换时按作品名自动注入为【已有资产库】，转换完成后新卡自动入库——
            同一部作品无论转多少章，角色不会换脸、场景不会改建。
          </p>
        </div>
      </header>

      {alert && <p className="alert">{alert}</p>}
      {loading && <p className="empty">读取中…</p>}
      {!loading && !works.length && (
        <div className="empty">
          <p>资产库还是空的。</p>
          <p className="lib__emptytip">
            新转换会自动入库；早于该功能的转换可一键补齐；也可以先手工建一部作品，
            把人物场景设定好再去转换。
          </p>
          <div className="lib__emptyacts">
            <button className="btn" disabled={busy} onClick={() => void backfill()}>
              从历史记录补齐
            </button>
          </div>
        </div>
      )}

      {!loading && (
        <div className="lib__works">
          {works.map((w) => (
            <button
              key={w.work_title}
              className={`wchip${w.work_title === title ? ' is-on' : ''}`}
              onClick={() => void openWork(w.work_title)}
            >
              {w.work_title}
              <em>{total(w)} 张卡</em>
            </button>
          ))}
          <span className="lib__newwork">
            <input
              value={newWork}
              placeholder="新建作品名"
              onChange={(e) => setNewWork(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); void addWork() } }}
            />
            <button className="btn btn--sm" disabled={busy || !newWork.trim()}
                    onClick={() => void addWork()}>＋ 建作品</button>
          </span>
        </div>
      )}

      {/* 新建卡片、搜索、编辑都挂在「当前打开的作品」上——没选中时说清楚，别让人对着空白页猜 */}
      {!loading && !!works.length && !title && (
        <p className="empty">点上面的作品名打开，才能新建 / 搜索 / 编辑它的资产卡。</p>
      )}

      {title && (
        <>
          <div className="lib__bar">
            <div className="lib__add">
              <select value={newKind}
                      onChange={(e) => setNewKind(e.target.value as AssetKind)}>
                {(Object.keys(KIND_LABEL) as AssetKind[]).map((k) => (
                  <option key={k} value={k}>{KIND_LABEL[k]}</option>
                ))}
              </select>
              <input
                value={newName}
                placeholder="新卡名称"
                onChange={(e) => setNewName(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); void addCard() } }}
              />
              <button className="btn btn--sm" disabled={busy || !newName.trim()}
                      onClick={() => void addCard()}>
                ＋ 新建（ID 自动续号 {nextId(assets, newKind)}）
              </button>
            </div>
            <input
              className="lib__search"
              value={query}
              placeholder="搜索卡片：ID / 名称 / 别名 / 描述"
              onChange={(e) => setQuery(e.target.value)}
            />
            <div className="lib__acts">
              <button className="btn btn--sm btn--ghost" disabled={busy}
                      title="扫本人历史记录，把其中的资产卡补进库（同 ID 合并，不覆盖人工编辑）"
                      onClick={() => void backfill()}>
                从历史补齐
              </button>
              <button className="btn btn--sm" disabled={!dirty.size || busy}
                      onClick={() => void save()}>
                {busy ? '保存中…' : dirty.size ? `保存修改（${dirty.size}）` : '已保存'}
              </button>
              <button className="btn btn--sm btn--ghost" onClick={() => void removeWork()}>
                删除整部作品
              </button>
            </div>
          </div>

          {q && (
            <p className="lib__found">
              匹配 <b>{shownCount}</b> / {allCount} 张卡
              {shownCount === 0 && ' —— 换个关键词试试'}
            </p>
          )}
          <AssetsView
            assets={shown}
            editing
            hideEditNote
            onChange={patchCard}
            onDelete={(kind, id) => void removeCard(kind, id)}
          />
        </>
      )}
    </div>
  )
}
