import type { LibraryWork } from '../types'

interface Props {
  works: LibraryWork[]
  /** 当前填写的作品名——资产库按作品名匹配 */
  workTitle: string
  useLibrary: boolean
  onToggle: (v: boolean) => void
  onPickWork: (title: string) => void
}

const total = (w: LibraryWork) =>
  Object.values(w.counts ?? {}).reduce((a, b) => a + b, 0)

/** 转换前明示：这次会不会沿用资产库、沿用哪一部。
 *
 *  沿用即把已有 C/S/P/A 卡作为【已有资产库】发给模型，模型须复用其 ID 与描述——
 *  续写同一部作品的下一章时角色不会换脸、场景不会改建。 */
export function AssetLibraryPicker({
  works, workTitle, useLibrary, onToggle, onPickWork,
}: Props) {
  const matched = works.find((w) => w.work_title === workTitle) ?? null
  const others = works.filter((w) => w.work_title !== workTitle)

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
