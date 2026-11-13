import { useEffect, useRef, useState } from 'react'
import { Boxes, Search } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { EmptyState } from '@/components/common/EmptyState'
import { useConfirm } from '@/components/common/ConfirmDialog'
import { useI18n } from '@/i18n/core'
import { errText } from '@/i18n/serverMsg'
import { assetThumb } from '@/lib/assetThumb'
import { notice } from '@/lib/notice'
import { deleteMemoryCard, upsertMemoryCard } from '../api'
import type { AssetKind } from '../edit'
import type { Assets } from '../types'
import { AssetsView, KIND_TITLE } from './AssetsView'

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

type AnyCard = { id: string; name: string; aliases?: string[]; outfits?: unknown[]; states?: unknown[]
  reference_images?: { uri?: string }[]; angles?: { uri?: string }[] }

function AssetTile({ kind, card, onOpen }: { kind: AssetKind; card: AnyCard; onOpen: () => void }) {
  const { t } = useI18n()
  const url = assetThumb(card)
  const meta = [
    card.aliases?.length ? t('assets.grid.aliases', { n: card.aliases.length }) : '',
    card.outfits?.length ? t('assets.grid.outfits', { n: card.outfits.length }) : '',
    card.states?.length ? t('assets.grid.states', { n: card.states.length }) : '',
  ].filter(Boolean).join(' · ')
  return (
    <button type="button" className="agrid__tile" data-testid="asset-tile" aria-label={card.name} onClick={onOpen}>
      <span className="agrid__thumb" data-kind={kind}>
        {url ? <img src={url} alt="" /> : <span aria-hidden>{(card.name || card.id).slice(0, 1)}</span>}
      </span>
      <span className="agrid__name" aria-hidden>{card.name}</span>
      <span className="agrid__id" aria-hidden>{card.id}</span>
      {meta && <span className="agrid__meta" aria-hidden>{meta}</span>}
    </button>
  )
}

interface Props {
  nid: string
  assets: Assets
  /** 写回后端之后通知上层刷新小说（侧栏卡数等） */
  onSaved: () => void
  /** 只显示并新建这一类（分区页用）；不传则显示全部类别并可选类别 */
  kind?: AssetKind
  /** 每递增一次就聚焦「新卡名称」输入框（分区标题行的「＋ 新卡片」用） */
  focusAdd?: number
}

/** 小说长期记忆里的资产库：各章采用版写入，也可手工新建、改、删。
 *  转换本书任何一章时都整份注入为【已有资产库】——角色不换脸、场景不改建。 */
export function NovelAssets({ nid, assets: initial, onSaved, kind, focusAdd }: Props) {
  const { t } = useI18n()
  const [ask, confirmUi] = useConfirm()
  const [assets, setAssets] = useState<Assets>(initial)
  const [dirty, setDirty] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)
  const [pickedKind, setNewKind] = useState<AssetKind>('characters')
  const newKind = kind ?? pickedKind
  const nameRef = useRef<HTMLInputElement>(null)
  const seenAdd = useRef(focusAdd)
  useEffect(() => {
    if (focusAdd && focusAdd !== seenAdd.current) nameRef.current?.focus()
    seenAdd.current = focusAdd
  }, [focusAdd])
  const [newName, setNewName] = useState('')
  const [query, setQuery] = useState('')
  /** 单卡编辑的卡 ID；null 时（且有 kind）显示缩略图网格 */
  const [open, setOpen] = useState<string | null>(null)

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

  const run = async (what: string, done: string, fn: () => Promise<void>) => {
    setBusy(true)
    try {
      await fn()
      notice.ok(done)
    } catch (e) {
      notice.err(t('novel.failed', { what }), errText(e))
    } finally {
      setBusy(false)
    }
  }

  const save = () => run(t('assets.whatSave'), t('novel.ok.saved'), async () => {
    for (const key of dirty) {
      const [kind, id] = key.split(':') as [AssetKind, string]
      const card = (assets[kind] ?? []).find((c) => c.id === id)
      if (card) await upsertMemoryCard(nid, kind, card)
    }
    setDirty(new Set())
    onSaved()
  })

  const addCard = () => !newName.trim() ? Promise.resolve() : run(t('assets.whatAdd'), t('assets.okAdded'), async () => {
    const name = newName.trim()
    if (!name) return
    const card = { id: nextId(assets, newKind), name }
    await upsertMemoryCard(nid, newKind, card)
    setAssets((prev) => ({ ...prev, [newKind]: [...(prev[newKind] ?? []), card]
      .sort((a, b) => a.id.localeCompare(b.id)) }))
    setNewName('')
    if (kind) setOpen(card.id)
    onSaved()
  })

  const removeCard = async (kind: AssetKind, id: string) => {
    if (!(await ask({ title: t('confirm.asset.title', { id }), body: t('confirm.asset.body'),
      action: t('confirm.delete'), danger: true }))) return
    void run(t('assets.whatDelete'), t('novel.ok.deleted'), async () => {
      await deleteMemoryCard(nid, kind, id)
      setAssets((prev) => ({ ...prev, [kind]: (prev[kind] ?? []).filter((c) => c.id !== id) }))
      setOpen((cur) => (cur === id ? null : cur))
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
  const scoped: Assets = kind ? ({ [kind]: assets[kind] ?? [] } as Assets) : assets
  const shown: Assets = q
    ? Object.fromEntries((Object.entries(scoped) as [AssetKind, Record<string, unknown>[]][])
        .map(([k, list]) => [k, (list ?? []).filter(hit)])
        .filter(([, list]) => (list as unknown[]).length)) as Assets
    : scoped
  const shownCount = Object.values(shown).reduce((a, l) => a + (l?.length ?? 0), 0)
  const allCount = Object.values(scoped).reduce((a, l) => a + (l?.length ?? 0), 0)

  const openCard = kind && open ? (assets[kind] ?? []).find((c) => c.id === open) ?? null : null

  return (
    <div className="lib">
      {confirmUi}
      <p className="lib__hint">{t('assets.hint')}</p>
      <div className="lib__bar">
        <div className="lib__add">
          {!kind && <select value={newKind} onChange={(e) => setNewKind(e.target.value as AssetKind)}>
            {(Object.keys(KIND_TITLE) as AssetKind[]).map((k) => (
              <option key={k} value={k}>{KIND_TITLE[k]}</option>
            ))}
          </select>}
          <Input
            ref={nameRef}
            value={newName}
            placeholder={t('assets.newName')}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); void addCard() } }}
          />
          <Button size="sm" disabled={busy || !newName.trim()} onClick={() => void addCard()}>
            {t('assets.add', { id: nextId(assets, newKind) })}
          </Button>
        </div>
        {!openCard && <div className="lib__searchbox">
          <Search size={14} aria-hidden />
          <Input
            className="lib__search"
            value={query}
            aria-label={t('assets.search')}
            placeholder={t('assets.searchPh')}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>}
        <div className="lib__acts">
          <Button size="sm" disabled={!dirty.size || busy} onClick={() => void save()}>
            {busy ? t('assets.saving') : dirty.size ? t('assets.save', { n: dirty.size }) : t('assets.saved')}
          </Button>
        </div>
      </div>
      {!allCount && (
        <EmptyState icon={<Boxes className="size-5" />} title={t('assets.emptyTitle')}
                    hint={t('assets.emptyHint')} />
      )}
      {q && !openCard && (
        <p className="lib__found">
          {t('assets.matchPre')} <b>{shownCount}</b> {t('assets.matchPost', { all: allCount })}
          {shownCount === 0 && ` ${t('assets.tryOther')}`}
        </p>
      )}
      {q && !openCard && shownCount === 0 && !!allCount && (
        <EmptyState title={t('assets.noMatch')}
                    action={<Button size="sm" variant="outline" onClick={() => setQuery('')}>{t('common.clearSearch')}</Button>} />
      )}
      {kind && !openCard && (
        <div className="agrid" data-testid="asset-grid"
             aria-label={t('assets.grid.aria', { kind: t(`assets.grid.kinds.${kind}`) })}>
          {(shown[kind] ?? []).map((c) => <AssetTile key={c.id} kind={kind} card={c} onOpen={() => setOpen(c.id)} />)}
        </div>
      )}
      {kind && openCard && (
        <>
          <Button size="sm" variant="ghost" className="agrid__back" onClick={() => setOpen(null)}>
            {t('assets.grid.back', { kind: t(`assets.grid.kinds.${kind}`) })}
          </Button>
          <AssetsView
            assets={{ [kind]: [openCard] } as Assets}
            editing
            hideEditNote
            onChange={patchCard}
            onDelete={(k, id) => void removeCard(k, id)}
          />
        </>
      )}
      {!kind && (
        <AssetsView
          assets={shown}
          editing
          hideEditNote
          onChange={patchCard}
          onDelete={(kind, id) => void removeCard(kind, id)}
        />
      )}
    </div>
  )
}
