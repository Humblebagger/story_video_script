import { useEffect, useState } from 'react'
import { useConfirm } from '@/components/common/ConfirmDialog'
import { useI18n } from '@/i18n/core'
import { deleteMemoryCard, upsertMemoryCard } from '../api'
import type { AssetKind } from '../edit'
import type { Assets } from '../types'
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

interface Props {
  nid: string
  assets: Assets
  /** 写回后端之后通知上层刷新小说（侧栏卡数等） */
  onSaved: () => void
}

/** 小说长期记忆里的资产库：各章采用版写入，也可手工新建、改、删。
 *  转换本书任何一章时都整份注入为【已有资产库】——角色不换脸、场景不改建。 */
export function NovelAssets({ nid, assets: initial, onSaved }: Props) {
  const { t } = useI18n()
  const [ask, confirmUi] = useConfirm()
  const [assets, setAssets] = useState<Assets>(initial)
  const [dirty, setDirty] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)
  const [alert, setAlert] = useState<string | null>(null)
  const [newKind, setNewKind] = useState<AssetKind>('characters')
  const [newName, setNewName] = useState('')
  const [query, setQuery] = useState('')

  // 换了小说（或上层重新取了长期记忆）且本地没有未保存的修改：跟上
  useEffect(() => {
    if (!dirty.size) setAssets(initial)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initial])

  const patchCard = (kind: AssetKind, id: string, patch: Record<string, unknown>) => {
    setAssets((prev) => ({
      ...prev,
      [kind]: (prev[kind] ?? []).map((c) => (c.id === id ? { ...c, ...patch } : c)),
    }))
    setDirty((prev) => new Set(prev).add(`${kind}:${id}`))
  }

  const run = async (what: string, fn: () => Promise<void>) => {
    setBusy(true)
    setAlert(null)
    try {
      await fn()
    } catch (e) {
      setAlert(`${what}失败：${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setBusy(false)
    }
  }

  const save = () => run('保存', async () => {
    for (const key of dirty) {
      const [kind, id] = key.split(':') as [AssetKind, string]
      const card = (assets[kind] ?? []).find((c) => c.id === id)
      if (card) await upsertMemoryCard(nid, kind, card)
    }
    setDirty(new Set())
    onSaved()
  })

  const addCard = () => run('新建', async () => {
    const name = newName.trim()
    if (!name) return
    const card = { id: nextId(assets, newKind), name }
    await upsertMemoryCard(nid, newKind, card)
    setAssets((prev) => ({ ...prev, [newKind]: [...(prev[newKind] ?? []), card]
      .sort((a, b) => a.id.localeCompare(b.id)) }))
    setNewName('')
    onSaved()
  })

  const removeCard = async (kind: AssetKind, id: string) => {
    if (!(await ask({ title: t('confirm.asset.title', { id }), body: t('confirm.asset.body'),
      action: t('confirm.delete'), danger: true }))) return
    void run('删除', async () => {
      await deleteMemoryCard(nid, kind, id)
      setAssets((prev) => ({ ...prev, [kind]: (prev[kind] ?? []).filter((c) => c.id !== id) }))
      setDirty((prev) => {
        const next = new Set(prev)
        next.delete(`${kind}:${id}`)
        return next
      })
      onSaved()
    })
  }

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
      {confirmUi}
      <p className="lib__hint">
        各章采用版的资产卡自动并进这里；转换本书任何一章都整份注入为【已有资产库】，
        模型须沿用其 ID 与描述。也可以先把人物场景设定好再去转换。
      </p>
      {alert && <p className="alert">{alert}</p>}
      <div className="lib__bar">
        <div className="lib__add">
          <select value={newKind} onChange={(e) => setNewKind(e.target.value as AssetKind)}>
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
          <button className="btn btn--sm" disabled={!dirty.size || busy} onClick={() => void save()}>
            {busy ? '保存中…' : dirty.size ? `保存修改（${dirty.size}）` : '已保存'}
          </button>
        </div>
      </div>
      {!allCount && <p className="empty">资产库还是空的：转换并采用一章后自动填入，或在上面手工新建。</p>}
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
    </div>
  )
}
