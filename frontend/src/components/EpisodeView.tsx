import { useState } from 'react'
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
              background: `hsl(${h} 62% 52% / ${
                seg.intensity === 'high' ? 0.85 : seg.intensity === 'mid' ? 0.55 : 0.3})`,
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
        <span className="ep__caret">{open ? '▾' : '▸'}</span>
        <span className="ep__id">{episode.id}</span>
        <h3 className="ep__title">{episode.title ?? '（无标题）'}</h3>
        <span className="ep__count">{episode.shots.length} 镜</span>
        {episode.music?.mood && (
          <span
            className="tag"
            style={{ borderColor: `hsl(${hue(episode.music.mood)} 60% 55%)` }}
          >
            🎵 {label(MOOD, episode.music.mood)}
          </span>
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
