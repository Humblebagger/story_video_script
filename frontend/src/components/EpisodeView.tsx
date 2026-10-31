import { useState } from 'react'
import { ChevronRight } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { INTENSITY, label, MOOD, MOOD_HUE } from '../labels'
import type { Index } from '../resolve'
import type { Episode, Mood, Shot } from '../types'
import { ShotCard } from './ShotCard'

interface Props {
  episode: Episode
  idx: Index
  editing: boolean
  onPickUnit: (unitId: string) => void
  onShotChange: (shotId: string, patch: Partial<Shot>) => void
}

const hue = (m?: Mood) => (m ? MOOD_HUE[m] ?? 210 : 210)

/** 情绪色与卡片底调和：浅色主题下是浅底、深色主题下是深底，文字一律用正文色 */
const moodFill = (h: number, pct: number) => `color-mix(in oklab, hsl(${h} 62% 52%) ${pct}%, var(--card))`

/** BGM 情绪曲线：按镜头序号铺成一条带子，段宽 = 覆盖镜头数占比 */
function MusicCurve({ episode }: { episode: Episode }) {
  const curve = episode.music?.curve ?? []
  const order = new Map(episode.shots.map((s, i) => [s.id, i]))
  const total = episode.shots.length || 1
  if (!curve.length) return null

  return (
    <div className="curve">
      {curve.map((seg, i) => {
        const from = order.get(seg.from_shot ?? '') ?? 0
        const to = order.get(seg.to_shot ?? '') ?? from
        const width = ((to - from + 1) / total) * 100
        const h = hue(seg.mood)
        return (
          <div
            className="curve__seg"
            key={i}
            style={{
              width: `${width}%`,
              background: moodFill(h,
                seg.intensity === 'high' ? 55 : seg.intensity === 'mid' ? 36 : 20),
            }}
            title={`${seg.from_shot} → ${seg.to_shot}\n${label(MOOD, seg.mood)} · 强度${
              label(INTENSITY, seg.intensity)}\n${seg.note ?? ''}`}
          >
            <span>{label(MOOD, seg.mood)}</span>
          </div>
        )
      })}
    </div>
  )
}

export function EpisodeView({ episode, idx, editing, onPickUnit, onShotChange }: Props) {
  const [open, setOpen] = useState(true)

  return (
    <section className="ep">
      <header className="ep__head" onClick={() => setOpen((v) => !v)}>
        <ChevronRight size={16} aria-hidden className={`ep__caret${open ? ' is-open' : ''}`} />
        <span className="ep__id">{episode.id}</span>
        <h3 className="ep__title">{episode.title ?? '（无标题）'}</h3>
        <Badge variant="secondary" className="ep__count font-normal">{episode.shots.length} 镜</Badge>
        {episode.music?.mood && (
          <Badge variant="outline" className="ep__mood font-normal text-muted-foreground" title="本集 BGM 情绪">
            <i style={{ background: `hsl(${hue(episode.music.mood)} 60% 55%)` }} />
            {label(MOOD, episode.music.mood)}
          </Badge>
        )}
      </header>

      {open && (
        <>
          {episode.summary && <p className="ep__summary">{episode.summary}</p>}
          <MusicCurve episode={episode} />
          {episode.music?.style_hint && (
            <p className="ep__music">配器：{episode.music.style_hint}</p>
          )}
          <div className="ep__shots">
            {episode.shots.map((s) => (
              <ShotCard
                key={s.id}
                shot={s}
                idx={idx}
                editing={editing}
                onPickUnit={onPickUnit}
                onChange={(patch) => onShotChange(s.id, patch)}
              />
            ))}
          </div>
          {episode.tail_frame_description && (
            <p className="ep__tail">尾帧：{episode.tail_frame_description}</p>
          )}
        </>
      )}
    </section>
  )
}
