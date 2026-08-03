import { splitAliases } from '../edit'
import { APPEARANCE_FIELDS, VOICE_FIELDS } from '../labels'
import type { AssetKind } from '../edit'
import type {
  Assets, CharacterAsset, CreatureAsset, LocationAsset, LocationAngle, PropAsset,
} from '../types'

const KIND_TITLE: Record<AssetKind, string> = {
  characters: '角色 C', locations: '场景 S', props: '道具 P', creatures: '生物 A',
}

const KIND_HINT: Partial<Record<AssetKind, string>> = {
  characters: '外貌只存在于资产卡，镜头层只写引用——从根上防角色漂移',
}

const IE_LABEL: Record<string, string> = {
  interior: '内景', exterior: '外景', both: '内外兼有',
}

const ANGLE_LABEL: Record<LocationAngle, string> = {
  front: '正面', reverse: '反打', side: '侧面', overhead: '顶视', establishing: '定场',
}

interface Props {
  assets: Assets
  editing: boolean
  onChange: (kind: AssetKind, id: string, patch: Record<string, unknown>) => void
}

/* ---------- 小控件 ---------- */

function Text({ value, onChange, placeholder, area }: {
  value?: string
  onChange: (v: string | undefined) => void
  placeholder?: string
  area?: boolean
}) {
  const props = {
    className: `ed${area ? ' ed--area' : ''}`,
    value: value ?? '',
    placeholder,
    onChange: (e: { target: { value: string } }) => onChange(e.target.value || undefined),
  }
  return area ? <textarea rows={3} {...props} /> : <input {...props} />
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="arow">
      <span className="arow__k">{label}</span>
      <div className="arow__v">{children}</div>
    </div>
  )
}

/** 固定字段表（appearance / voice）。
 *
 *  这些对象在 schema 里是 additionalProperties: false 的白名单，
 *  所以只能按字段编辑，不能当自由键值表——多一个键就是 schema 校验失败。
 *  留空的字段写回时删掉，避免产出一堆空串。 */
function FixedMap({ map, fields, onChange }: {
  map: Record<string, string> | undefined
  fields: [string, string][]
  onChange: (next: Record<string, string> | undefined) => void
}) {
  const set = (k: string, v: string) => {
    const next = { ...(map ?? {}) }
    if (v) next[k] = v
    else delete next[k]
    onChange(Object.keys(next).length ? next : undefined)
  }
  return (
    <div className="amap">
      {fields.map(([key, label]) => (
        <div className="amap__row" key={key}>
          <span className="amap__k" title={key}>{label}</span>
          <input
            className="ed"
            value={map?.[key] ?? ''}
            placeholder="—"
            onChange={(e) => set(key, e.target.value)}
          />
        </div>
      ))}
    </div>
  )
}

/* ---------- 各类资产卡 ---------- */

function CharacterCard({ c, editing, patch }: {
  c: CharacterAsset; editing: boolean; patch: (p: Record<string, unknown>) => void
}) {
  if (!editing) {
    return (
      <>
        {APPEARANCE_FIELDS.filter(([k]) => c.appearance?.[k]).map(([k, label]) => (
          <p className="acard__row" key={k}><span>{label}</span>{c.appearance![k]}</p>
        ))}
        {!!c.outfits?.length && (
          <p className="acard__row"><span>服装</span>
            {c.outfits.map((o) => o.name ?? o.id).join('、')}</p>
        )}
        {VOICE_FIELDS.filter(([k]) => c.voice?.[k]).map(([k, label]) => (
          <p className="acard__row" key={k}><span>{label}</span>{c.voice![k]}</p>
        ))}
        {c.persona_notes && <p className="acard__row"><span>性格</span>{c.persona_notes}</p>}
      </>
    )
  }
  return (
    <>
      <Row label="别名">
        <Text value={(c.aliases ?? []).join('、')} placeholder="以顿号分隔"
              onChange={(v) => patch({ aliases: v ? splitAliases(v) : undefined })} />
      </Row>
      <Row label="外貌">
        <FixedMap map={c.appearance} fields={APPEARANCE_FIELDS}
                  onChange={(v) => patch({ appearance: v })} />
      </Row>
      {!!c.outfits?.length && (
        <Row label="服装">
          {c.outfits.map((o, i) => (
            <div className="asub" key={o.id}>
              <span className="asub__id" title="服装 ID 被镜头的 characters[].outfit 引用，不可改">
                🔒 {o.id}
              </span>
              <Text value={o.name} placeholder="名称"
                    onChange={(v) => patch({ outfits: c.outfits!.map(
                      (x, j) => (j === i ? { ...x, name: v } : x)) })} />
              <Text value={o.visual_prompt} placeholder="外观描述"
                    onChange={(v) => patch({ outfits: c.outfits!.map(
                      (x, j) => (j === i ? { ...x, visual_prompt: v } : x)) })} />
            </div>
          ))}
        </Row>
      )}
      <Row label="声音">
        <FixedMap map={c.voice} fields={VOICE_FIELDS}
                  onChange={(v) => patch({ voice: v })} />
      </Row>
      <Row label="性格">
        <Text value={c.persona_notes} area
              onChange={(v) => patch({ persona_notes: v })} />
      </Row>
    </>
  )
}

function LocationCard({ l, editing, patch }: {
  l: LocationAsset; editing: boolean; patch: (p: Record<string, unknown>) => void
}) {
  if (!editing) {
    return (
      <>
        {l.era && <p className="acard__row"><span>年代</span>{l.era}</p>}
        {l.interior_exterior && (
          <p className="acard__row"><span>内外景</span>{IE_LABEL[l.interior_exterior]}</p>
        )}
        {!!l.angles?.length && (
          <p className="acard__row"><span>机位</span>
            {l.angles.map((a) => (a.angle ? ANGLE_LABEL[a.angle] : '')).filter(Boolean).join('、')}</p>
        )}
        {l.lighting_defaults && (
          <p className="acard__row"><span>默认光</span>{l.lighting_defaults}</p>
        )}
      </>
    )
  }
  return (
    <>
      <Row label="年代"><Text value={l.era} onChange={(v) => patch({ era: v })} /></Row>
      <Row label="内外景">
        <select
          className="ed ed--sel"
          value={l.interior_exterior ?? ''}
          onChange={(e) => patch({ interior_exterior: e.target.value || undefined })}
        >
          <option value="">—</option>
          {Object.entries(IE_LABEL).map(([v, n]) => <option key={v} value={v}>{n}</option>)}
        </select>
      </Row>
      <Row label="默认光">
        <Text value={l.lighting_defaults} onChange={(v) => patch({ lighting_defaults: v })} />
      </Row>
      {!!l.angles?.length && (
        <Row label="机位">
          {l.angles.map((a, i) => (
            <div className="asub" key={i}>
              <select
                className="ed ed--sel"
                value={a.angle ?? ''}
                onChange={(e) => patch({ angles: l.angles!.map((x, j) =>
                  (j === i ? { ...x, angle: (e.target.value || undefined) as LocationAngle } : x)) })}
              >
                <option value="">—</option>
                {Object.entries(ANGLE_LABEL).map(([v, n]) => <option key={v} value={v}>{n}</option>)}
              </select>
              <Text value={a.visual_prompt} placeholder="该机位的画面描述"
                    onChange={(v) => patch({ angles: l.angles!.map(
                      (x, j) => (j === i ? { ...x, visual_prompt: v } : x)) })} />
            </div>
          ))}
        </Row>
      )}
    </>
  )
}

function PropCard({ p, editing, patch }: {
  p: PropAsset; editing: boolean; patch: (x: Record<string, unknown>) => void
}) {
  if (!editing) {
    return p.states?.length ? (
      <p className="acard__row"><span>状态机</span>
        {p.states.map((s) => s.name ?? s.id).join(' → ')}</p>
    ) : null
  }
  return p.states?.length ? (
    <Row label="状态机">
      {p.states.map((s, i) => (
        <div className="asub" key={s.id}>
          <span className="asub__id" title="状态 ID 被镜头的 prop_refs[].state 引用，不可改">
            🔒 {s.id}
          </span>
          <Text value={s.name} placeholder="名称"
                onChange={(v) => patch({ states: p.states!.map(
                  (x, j) => (j === i ? { ...x, name: v } : x)) })} />
          <Text value={s.visual_prompt} placeholder="该状态的外观"
                onChange={(v) => patch({ states: p.states!.map(
                  (x, j) => (j === i ? { ...x, visual_prompt: v } : x)) })} />
        </div>
      ))}
    </Row>
  ) : null
}

function CreatureCard({ c, editing, patch }: {
  c: CreatureAsset; editing: boolean; patch: (p: Record<string, unknown>) => void
}) {
  if (!editing) {
    return (
      <>
        {c.species && <p className="acard__row"><span>物种</span>{c.species}</p>}
        {c.notes && <p className="acard__row"><span>备注</span>{c.notes}</p>}
      </>
    )
  }
  return (
    <>
      <Row label="别名">
        <Text value={(c.aliases ?? []).join('、')} placeholder="以顿号分隔"
              onChange={(v) => patch({ aliases: v ? splitAliases(v) : undefined })} />
      </Row>
      <Row label="物种"><Text value={c.species} onChange={(v) => patch({ species: v })} /></Row>
      <Row label="备注"><Text value={c.notes} area onChange={(v) => patch({ notes: v })} /></Row>
    </>
  )
}

/* ---------- 主视图 ---------- */

export function AssetsView({ assets, editing, onChange }: Props) {
  const kinds = (['characters', 'locations', 'props', 'creatures'] as AssetKind[])
    .filter((k) => (assets[k] ?? []).length > 0)

  if (!kinds.length) return <p className="empty">此分镜没有资产卡。</p>

  return (
    <div className="assets">
      {editing && (
        <p className="assets__editnote">
          资产卡整个属于「呈现」侧，名称 / 别名 / 外貌 / 描述都可以改。
          只有 🔒 标出的 ID 锁死——它们被镜头层跨引用（场景、道具及其状态、角色及其服装），
          改了 lint 立刻报「引用不存在的资产」。
        </p>
      )}
      {kinds.map((kind) => (
        <section key={kind}>
          <h3 className="assets__title">
            {KIND_TITLE[kind]} <span className="assets__n">{(assets[kind] ?? []).length}</span>
          </h3>
          {KIND_HINT[kind] && <p className="assets__hint">{KIND_HINT[kind]}</p>}
          <div className="assets__grid">
            {(assets[kind] ?? []).map((card) => {
              const patch = (p: Record<string, unknown>) => onChange(kind, card.id, p)
              return (
                <article className={`acard${editing ? ' acard--ed' : ''}`} key={card.id}>
                  <header>
                    <span className="acard__id" title="资产 ID 被镜头层引用，不可改">
                      {editing && '🔒 '}{card.id}
                    </span>
                    {editing
                      ? <Text value={card.name} placeholder="名称"
                              onChange={(v) => patch({ name: v ?? '' })} />
                      : <b>{card.name}</b>}
                    {!editing && 'aliases' in card && !!card.aliases?.length && (
                      <span className="acard__alias">别称：{card.aliases.join('、')}</span>
                    )}
                  </header>

                  {kind === 'characters' && (
                    <CharacterCard c={card as CharacterAsset} editing={editing} patch={patch} />
                  )}
                  {kind === 'locations' && (
                    <LocationCard l={card as LocationAsset} editing={editing} patch={patch} />
                  )}
                  {kind === 'props' && (
                    <PropCard p={card as PropAsset} editing={editing} patch={patch} />
                  )}
                  {kind === 'creatures' && (
                    <CreatureCard c={card as CreatureAsset} editing={editing} patch={patch} />
                  )}

                  {editing ? (
                    <Row label="画面描述">
                      <Text value={card.visual_prompt} area
                            onChange={(v) => patch({ visual_prompt: v })} />
                    </Row>
                  ) : (
                    card.visual_prompt && <p className="acard__prompt">{card.visual_prompt}</p>
                  )}
                </article>
              )
            })}
          </div>
        </section>
      ))}
    </div>
  )
}
