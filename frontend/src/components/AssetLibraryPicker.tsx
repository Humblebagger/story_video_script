import { useEffect, useState } from 'react'
import { getLibraryWork } from '../api'
import type { AssetKind } from '../edit'
import type { Assets, LibraryWork } from '../types'

interface Props {
  works: LibraryWork[]
  /** 当前填写的作品名——资产库按作品名匹配 */
  workTitle: string
  useLibrary: boolean
  onToggle: (v: boolean) => void
  onPickWork: (title: string) => void
  /** 只钉一部分卡时给出这份显式资产库；整部沿用则回 null */
  onPin: (assets: Assets | null) => void
}

const KIND_LABEL: Record<AssetKind, string> = {
  characters: '角色', locations: '场景', props: '道具', creatures: '生物',
}
const KINDS = Object.keys(KIND_LABEL) as AssetKind[]

const total = (w: LibraryWork) =>
  Object.values(w.counts ?? {}).reduce((a, b) => a + b, 0)

/** 转换前明示：这次会不会沿用资产库、沿用哪一部、以及具体钉哪几张卡。
 *
 *  沿用即把已有 C/S/P/A 卡作为【已有资产库】发给模型，模型须复用其 ID 与描述——
 *  续写同一部作品的下一章时角色不会换脸、场景不会改建。 */
export function AssetLibraryPicker({
  works, workTitle, useLibrary, onToggle, onPickWork, onPin,
}: Props) {
  const matched = works.find((w) => w.work_title === workTitle) ?? null
  const others = works.filter((w) => w.work_title !== workTitle)

  const [assets, setAssets] = useState<Assets>({})
  const [open, setOpen] = useState(false)
  // null = 整部沿用（默认）；一旦动过勾选就变成显式白名单
  const [picked, setPicked] = useState<Set<string> | null>(null)

  // 换作品或关掉沿用，之前钉的卡就作废了，别把上一部的选择带过去
  useEffect(() => {
    setPicked(null)
    setOpen(false)
    setAssets({})
    onPin(null)
    if (!matched || !useLibrary) return
    let alive = true
    void getLibraryWork(matched.work_title)
      .then((w) => { if (alive) setAssets(w.assets ?? {}) })
      .catch(() => { if (alive) setAssets({}) })
    return () => { alive = false }
    // onPin 由父组件每次渲染新建，进依赖会打成死循环
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [matched?.work_title, useLibrary])

  const allIds = KINDS.flatMap((k) => (assets[k] ?? []).map((c) => c.id))

  /** 把勾选集变成一份可直接当【已有资产库】发出去的 assets */
  const emit = (next: Set<string> | null) => {
    setPicked(next)
    if (!next) return onPin(null)
    const out: Assets = {}
    for (const k of KINDS) {
      const list = (assets[k] ?? []).filter((c) => next.has(c.id))
      if (list.length) (out[k] as unknown[]) = list
    }
    onPin(out)
  }

  const toggle = (id: string) => {
    const next = new Set(picked ?? allIds)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    // 又勾回全部，就回到「整部沿用」，避免钉出一份和全量一样的白名单
    emit(next.size === allIds.length ? null : next)
  }

  const on = (id: string) => (picked ?? new Set(allIds)).has(id)
  const pinnedCount = picked ? picked.size : allIds.length

  if (!works.length) {
    return (
      <section className="alib">
        <b>资产库</b>
        <span className="alib__hint">
          还是空的。这次转换产出的角色/场景卡会自动入库，续写下一章时即可沿用。
        </span>
      </section>
    )
  }

  return (
    <section className="alib">
      <header className="alib__head">
        <div>
          <b>资产库</b>
          <span className="alib__hint">
            {matched
              ? `将沿用《${matched.work_title}》已有的 ${total(matched)} 张卡，模型须复用其 ID 与描述——续写下一章时角色不会换脸`
              : `《${workTitle || '（未填作品名）'}》在库中还没有资产卡；本次产出会自动入库`}
          </span>
        </div>
        {matched && (
          <label className="check">
            <input type="checkbox" checked={useLibrary}
                   onChange={(e) => onToggle(e.target.checked)} />
            沿用
          </label>
        )}
      </header>

      {matched && useLibrary && !!allIds.length && (
        <div className="alib__pin">
          <button type="button" className="btn btn--sm btn--ghost"
                  onClick={() => setOpen((v) => !v)}>
            {open ? '收起' : '指定钉哪几张卡'}
            <em className="alib__pinn">
              {picked ? `已钉 ${pinnedCount}/${allIds.length}` : `全部 ${allIds.length} 张`}
            </em>
          </button>

          {open && (
            <div className="alib__cards">
              <p className="alib__warn">
                取消勾选只是不发给模型。模型没见过的角色会被当成新人物重新起卡，
                ID 可能与你排除掉的那张撞号——除非确有必要，建议整部沿用。
              </p>
              {KINDS.map((k) => !!(assets[k] ?? []).length && (
                <div className="alib__kind" key={k}>
                  <span className="alib__kindname">{KIND_LABEL[k]}</span>
                  {(assets[k] ?? []).map((c) => (
                    <label className={`alib__card${on(c.id) ? ' is-on' : ''}`} key={c.id}>
                      <input type="checkbox" checked={on(c.id)}
                             onChange={() => toggle(c.id)} />
                      <b>{c.id}</b> {c.name}
                    </label>
                  ))}
                </div>
              ))}
              {picked && (
                <button type="button" className="btn btn--sm btn--ghost"
                        onClick={() => emit(null)}>恢复整部沿用</button>
              )}
            </div>
          )}
        </div>
      )}

      {!!others.length && (
        <div className="alib__works">
          <span className="alib__pick">库中已有：</span>
          {others.map((w) => (
            <button type="button" key={w.work_title} className="wchip"
                    title="点击把作品名改成它，即可沿用这部作品的资产库"
                    onClick={() => onPickWork(w.work_title)}>
              {w.work_title}
              <em>{total(w)} 张卡</em>
            </button>
          ))}
        </div>
      )}
    </section>
  )
}
