import { Lock, MapPin, Package, PawPrint, User } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { SelectMenu } from '@/components/ui/select'
import { splitAliases } from '../edit'
import { appearanceFields, LOCATION_ANGLE, voiceFields } from '../labels'
import { tr, useI18n } from '@/i18n/core'
import type { MsgKey } from '@/i18n/core'
import type { AssetKind } from '../edit'
import type {
  AssetVariant, Assets, CharacterAsset, CreatureAsset, LocationAsset, LocationAngle,
  PropAsset, ReferenceImage,
} from '../types'

const ASSET_KINDS: AssetKind[] = ['characters', 'locations', 'props', 'creatures']

// oxlint-disable-next-line react/only-export-components -- 小说页资产库复用同一份分类名，不另抄一份
export const KIND_TITLE = Object.fromEntries(ASSET_KINDS.map((k) => [k, k])) as Record<AssetKind, string>
for (const k of ASSET_KINDS) {
  Object.defineProperty(KIND_TITLE, k, { enumerable: true, get: () => tr(`assetView.kindTitle.${k}` as MsgKey) })
}

const KIND_ICON = {
  characters: User, locations: MapPin, props: Package, creatures: PawPrint,
} as const

const IE_KEYS = ['interior', 'exterior', 'both']
const ieLabel = () => Object.fromEntries(IE_KEYS.map((k) => [k, tr(`assetView.ie.${k}` as MsgKey)])) as Record<string, string>
const ANGLE_LABEL = LOCATION_ANGLE

interface Props {
  assets: Assets
  editing: boolean
  onChange: (kind: AssetKind, id: string, patch: Record<string, unknown>) => void
  /** 资产库页才给：分镜里的资产卡不能删（删了镜头就引用不到了） */
  onDelete?: (kind: AssetKind, id: string) => void
  /** 资产库页自带说明，不必重复分镜页那段 */
  hideEditNote?: boolean
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

const VIEW_KEYS = ['front', 'side', 'back', 'three_quarter', 'close_up']
const viewLabel = () => Object.fromEntries(VIEW_KEYS.map((k) => [k, tr(`assetView.view.${k}` as MsgKey)])) as Record<string, string>

/** 设定图槽位。
 *
 *  这是「画师修正稿反过来约束后续每一帧」那条链的锚点：一张图必须说清画的是
 *  哪套变体，否则拿着另一套衣服的脸去垫图，等于白垫。所以归属下拉只列本卡真实
 *  存在的 outfit / state——lint 会逐条核对，界面提供不了非法选项才是对的。 */
function RefImages({ list, variants, tagKey, onChange }: {
  list: ReferenceImage[] | undefined
  variants: AssetVariant[]
  tagKey: 'outfit' | 'state'
  onChange: (next: ReferenceImage[] | undefined) => void
}) {
  const { t } = useI18n()
  const items = list ?? []
  const viewOptions = [
    { value: '', label: t('assetView.viewPh') },
    ...Object.entries(viewLabel()).map(([v, n]) => ({ value: v, label: n })),
  ]
  const variantOptions = variants.map((v) => ({ value: v.id, label: v.id }))
  const set = (i: number, patch: Partial<ReferenceImage>) =>
    onChange(items.map((x, j) => (j === i ? { ...x, ...patch } : x)))
  return (
    <div className="aimgs">
      {items.map((img, i) => (
        <div className="asub" key={i}>
          <SelectMenu
            value={img.view ?? ''}
            ariaLabel={t('assetView.viewPh')}
            options={viewOptions}
            onChange={(v) => set(i, { view: (v || undefined) as ReferenceImage['view'] })}
          />
          {!!variants.length && (
            <SelectMenu
              value={img[tagKey] ?? ''}
              title={tagKey === 'outfit' ? t('assetView.outfitTip') : t('assetView.stateTip')}
              ariaLabel={tagKey === 'outfit' ? t('assetView.outfitTip') : t('assetView.stateTip')}
              options={[{ value: '', label: t('assetView.baseLook') }, ...variantOptions]}
              onChange={(v) => set(i, { [tagKey]: v || undefined })}
            />
          )}
          <Text value={img.uri} placeholder={t('assetView.uriPh')}
                onChange={(v) => set(i, { uri: v })} />
          <button type="button" className="ed__x" title={t('assetView.delImg')}
                  onClick={() => onChange(items.filter((_, j) => j !== i).length
                    ? items.filter((_, j) => j !== i) : undefined)}>×</button>
        </div>
      ))}
      <Button type="button" size="sm" variant="outline"
              onClick={() => onChange([...items, {}])}>{t('assetView.addImg')}</Button>
    </div>
  )
}

/** 卡级负面约束：画这张卡时不要做什么 */
function Constraints({ list, onChange, hint }: {
  list: string[] | undefined
  onChange: (next: string[] | undefined) => void
  hint: string
}) {
  return (
    <Text value={(list ?? []).join(' / ')} placeholder={hint}
          onChange={(v) => {
            const clean = (v ?? '').split('/').map((x) => x.trim()).filter(Boolean)
            onChange(clean.length ? clean : undefined)
          }} />
  )
}

/* ---------- 各类资产卡 ---------- */

function CharacterCard({ c, editing, patch }: {
  c: CharacterAsset; editing: boolean; patch: (p: Record<string, unknown>) => void
}) {
  const { t } = useI18n()
  if (!editing) {
    const shownAppearance = appearanceFields().filter(([k]) => c.appearance?.[k])
    const shownVoice = voiceFields().filter(([k]) => c.voice?.[k])
    return (
      <>
        {!!shownAppearance.length && (
          <section className="acard__group">
            <h4 className="acard__ghead">{t('assetView.appearance')}</h4>
            {shownAppearance.map(([k, label]) => (
              <p className="acard__row" key={k}><span>{label}</span>{c.appearance![k]}</p>
            ))}
          </section>
        )}
        {!!c.outfits?.length && (
          <section className="acard__group">
            <h4 className="acard__ghead">{t('assetView.outfits')}</h4>
            <div className="chips">
              {c.outfits.map((o) => (
                <span className="chip chip--var" key={o.id}><b>{o.id}</b>{o.description}</span>
              ))}
            </div>
          </section>
        )}
        {!!shownVoice.length && (
          <section className="acard__group">
            <h4 className="acard__ghead">{t('assetView.voice')}</h4>
            {shownVoice.map(([k, label]) => (
              <p className="acard__row" key={k}><span>{label}</span>{c.voice![k]}</p>
            ))}
          </section>
        )}
        {c.persona_notes && (
          <section className="acard__group">
            <h4 className="acard__ghead">{t('assetView.persona')}</h4>
            <p className="acard__prose">{c.persona_notes}</p>
          </section>
        )}
      </>
    )
  }
  return (
    <>
      <Row label={t('assetView.alias')}>
        <Text value={(c.aliases ?? []).join(t('common.listSep'))} placeholder={t('assetView.aliasPh')}
              onChange={(v) => patch({ aliases: v ? splitAliases(v) : undefined })} />
      </Row>
      <Row label={t('assetView.appearance')}>
        <FixedMap map={c.appearance} fields={appearanceFields()}
                  onChange={(v) => patch({ appearance: v })} />
      </Row>
      {!!c.outfits?.length && (
        <Row label={t('assetView.outfits')}>
          {c.outfits.map((o, i) => (
            <div className="asub" key={o.id}>
              <span className="asub__id" title={t('assetView.outfitId')}>
                <Lock size={12} aria-hidden />{o.id}
              </span>
              <Text value={o.description} area
                    placeholder={t('assetView.outfitPh')}
                    onChange={(v) => patch({ outfits: c.outfits!.map(
                      (x, j) => (j === i ? { ...x, description: v } : x)) })} />
            </div>
          ))}
        </Row>
      )}
      <Row label={t('assetView.refImages')}>
        <RefImages list={c.reference_images} variants={c.outfits ?? []} tagKey="outfit"
                   onChange={(v) => patch({ reference_images: v })} />
      </Row>
      <Row label={t('assetView.cons')}>
        <Constraints list={c.constraints} onChange={(v) => patch({ constraints: v })}
                     hint={t('assetView.consCharHint')} />
      </Row>
      <Row label={t('assetView.voice')}>
        <FixedMap map={c.voice} fields={voiceFields()}
                  onChange={(v) => patch({ voice: v })} />
      </Row>
      <Row label={t('assetView.persona')}>
        <Text value={c.persona_notes} area
              onChange={(v) => patch({ persona_notes: v })} />
      </Row>
    </>
  )
}

function LocationCard({ l, editing, patch }: {
  l: LocationAsset; editing: boolean; patch: (p: Record<string, unknown>) => void
}) {
  const { t } = useI18n()
  const ieOptions = [
    { value: '', label: '—' },
    ...Object.entries(ieLabel()).map(([v, n]) => ({ value: v, label: n })),
  ]
  const angleOptions = [
    { value: '', label: '—' },
    ...Object.entries(ANGLE_LABEL).map(([v, n]) => ({ value: v, label: n })),
  ]
  if (!editing) {
    return (
      <section className="acard__group">
        <h4 className="acard__ghead">{t('assetView.groupScene')}</h4>
        {l.era && <p className="acard__row"><span>{t('assetView.era')}</span>{l.era}</p>}
        {l.interior_exterior && (
          <p className="acard__row"><span>{t('assetView.ieLabel')}</span>{ieLabel()[l.interior_exterior]}</p>
        )}
        {!!l.angles?.length && (
          <p className="acard__row"><span>{t('assetView.angles')}</span>
            {l.angles.map((a) => (a.angle ? ANGLE_LABEL[a.angle] : '')).filter(Boolean).join(t('common.listSep'))}</p>
        )}
        {l.lighting_defaults && (
          <p className="acard__row"><span>{t('assetView.defLight')}</span>{l.lighting_defaults}</p>
        )}
      </section>
    )
  }
  return (
    <>
      <Row label={t('assetView.era')}><Text value={l.era} onChange={(v) => patch({ era: v })} /></Row>
      <Row label={t('assetView.ieLabel')}>
        <SelectMenu
          value={l.interior_exterior ?? ''}
          ariaLabel={t('assetView.ieLabel')}
          options={ieOptions}
          onChange={(v) => patch({ interior_exterior: v || undefined })}
        />
      </Row>
      <Row label={t('assetView.defLight')}>
        <Text value={l.lighting_defaults} onChange={(v) => patch({ lighting_defaults: v })} />
      </Row>
      <Row label={t('assetView.cons')}>
        <Constraints list={l.constraints} onChange={(v) => patch({ constraints: v })}
                     hint={t('assetView.consHint')} />
      </Row>
      {!!l.angles?.length && (
        <Row label={t('assetView.angles')}>
          {l.angles.map((a, i) => (
            <div className="asub" key={i}>
              <SelectMenu
                value={a.angle ?? ''}
                ariaLabel={t('assetView.angles')}
                options={angleOptions}
                onChange={(v) => patch({ angles: l.angles!.map((x, j) =>
                  (j === i ? { ...x, angle: (v || undefined) as LocationAngle } : x)) })}
              />
              <Text value={a.uri} placeholder={t('assetView.angleUriPh')}
                    onChange={(v) => patch({ angles: l.angles!.map(
                      (x, j) => (j === i ? { ...x, uri: v } : x)) })} />
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
  const { t } = useI18n()
  if (!editing) {
    return p.states?.length ? (
      <section className="acard__group">
        <h4 className="acard__ghead">{t('assetView.states')}</h4>
        <div className="chips">
          {p.states.map((s) => (
            <span className="chip chip--var" key={s.id}><b>{s.id}</b>{s.description}</span>
          ))}
        </div>
      </section>
    ) : null
  }
  return (
    <>
      {!!p.states?.length && (
        <Row label={t('assetView.states')}>
          {p.states.map((s, i) => (
            <div className="asub" key={s.id}>
              <span className="asub__id" title={t('assetView.stateId')}>
                <Lock size={12} aria-hidden />{s.id}
              </span>
              <Text value={s.description} area
                    placeholder={t('assetView.statePh')}
                    onChange={(v) => patch({ states: p.states!.map(
                      (x, j) => (j === i ? { ...x, description: v } : x)) })} />
            </div>
          ))}
        </Row>
      )}
      <Row label={t('assetView.refImages')}>
        <RefImages list={p.reference_images} variants={p.states ?? []} tagKey="state"
                   onChange={(v) => patch({ reference_images: v })} />
      </Row>
      <Row label={t('assetView.cons')}>
        <Constraints list={p.constraints} onChange={(v) => patch({ constraints: v })}
                     hint={t('assetView.consHint')} />
      </Row>
    </>
  )
}

function CreatureCard({ c, editing, patch }: {
  c: CreatureAsset; editing: boolean; patch: (p: Record<string, unknown>) => void
}) {
  const { t } = useI18n()
  if (!editing) {
    return (
      <section className="acard__group">
        <h4 className="acard__ghead">{t('assetView.groupBasics')}</h4>
        {c.species && <p className="acard__row"><span>{t('assetView.species')}</span>{c.species}</p>}
        {c.notes && <p className="acard__row"><span>{t('assetView.notes')}</span>{c.notes}</p>}
      </section>
    )
  }
  return (
    <>
      <Row label={t('assetView.alias')}>
        <Text value={(c.aliases ?? []).join(t('common.listSep'))} placeholder={t('assetView.aliasPh')}
              onChange={(v) => patch({ aliases: v ? splitAliases(v) : undefined })} />
      </Row>
      <Row label={t('assetView.species')}><Text value={c.species} onChange={(v) => patch({ species: v })} /></Row>
      <Row label={t('assetView.refImages')}>
        {/* 生物卡没有变体集（lint 明令引用不得带 outfit），故不给归属下拉 */}
        <RefImages list={c.reference_images} variants={[]} tagKey="outfit"
                   onChange={(v) => patch({ reference_images: v })} />
      </Row>
      <Row label={t('assetView.cons')}>
        <Constraints list={c.constraints} onChange={(v) => patch({ constraints: v })}
                     hint={t('assetView.consHint')} />
      </Row>
      <Row label={t('assetView.notes')}><Text value={c.notes} area onChange={(v) => patch({ notes: v })} /></Row>
    </>
  )
}

/* ---------- 主视图 ---------- */

export function AssetsView({ assets, editing, onChange, onDelete, hideEditNote }: Props) {
  const { t } = useI18n()
  const kinds = ASSET_KINDS
    .filter((k) => (assets[k] ?? []).length > 0)

  if (!kinds.length) return <p className="empty">{t('assetView.emptyDoc')}</p>

  return (
    <div className="assets">
      {editing && !hideEditNote && (
        <p className="assets__editnote">
          {t('assetView.editNote')}
        </p>
      )}
      {kinds.map((kind) => (
        <section key={kind} data-kind={kind}>
          <h3 className="assets__title">
            {KIND_TITLE[kind]} <span className="assets__n">{(assets[kind] ?? []).length}</span>
          </h3>
          {kind === 'characters' && <p className="assets__hint">{t('assetView.charHint')}</p>}
          <div className="assets__grid">
            {(assets[kind] ?? []).map((card) => {
              const patch = (p: Record<string, unknown>) => onChange(kind, card.id, p)
              const Icon = KIND_ICON[kind]
              return (
                <article className={`acard${editing ? ' acard--ed' : ''}`} key={card.id} data-kind={kind}>
                  <header>
                    <Icon className="acard__icon" size={16} aria-hidden />
                    {editing
                      ? <Text value={card.name} placeholder={t('assetView.namePh')}
                              onChange={(v) => patch({ name: v ?? '' })} />
                      : <b className="acard__name">{card.name}</b>}
                    <span className="acard__id" title={t('assetView.idTip')}>
                      {editing && <Lock size={12} aria-hidden />}{card.id}
                    </span>
                    {!editing && 'aliases' in card && !!card.aliases?.length && (
                      <span className="acard__alias">{t('assetView.aliasShown', { v: card.aliases.join(t('common.listSep')) })}</span>
                    )}
                    {editing && onDelete && (
                      <button type="button" className="acard__del" title={t('assetView.delCard')}
                              onClick={() => onDelete(kind, card.id)}>×</button>
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
                    <Row label={t('assetView.visual')}>
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
