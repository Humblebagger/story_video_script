/** 出片画布的「节点图」视图：资产、剧本段、自由节点三列，连线显示谁参考了谁（设计文档 2026-11-11 §5）。
 *  布局由 nodeGraph.ts 的纯函数算好，这里只管平移缩放、高亮和把卡片摆上去。
 *  盖在时间轴上面（时间轴不卸载），指针与滚轮事件在这一层处理、不往下传；Esc 先取消选中，再交给画布关闭。 */
import { useEffect, useMemo, useRef, useState } from 'react'
import type { PointerEvent as RPointerEvent, WheelEvent as RWheelEvent } from 'react'
import { Maximize2, Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/i18n/core'
import { formatMsg } from '@/i18n/serverMsg'
import { cn } from '@/lib/utils'
import { chosenAttempt, freeNodes } from '../film'
import { edgePath, fitView, layoutGraph, related } from '../nodeGraph'
import { clipShotTags, shotsById } from '../shotSheet'
import type { Film } from '../useFilm'
import type { Storyboard } from '../types'
import { AssetCard, ClipCard, FreeCard } from './NodeCards'

const ZOOM = { min: 0.3, max: 1.5 }

export function NodeGraph({ film, doc, styleUrl, kfUrls, selected, blocked, onSelect, onOpenAssets, onOpenFilm, onPlay, onCancel }: {
  film: Film
  doc: Storyboard
  styleUrl: string | null
  /** 镜头 id → 关键帧图 */
  kfUrls: Record<string, string>
  /** 选中的段或自由节点（与侧栏「出片」页同一个） */
  selected: string | null
  /** 有未保存的改动或没过验证门：花钱的按钮禁用 */
  blocked: string | null
  onSelect: (id: string) => void
  onOpenAssets: () => void
  onOpenFilm: () => void
  /** 播放某一段 / 自由节点采用的那次；取消它的生成（画布弹播放窗口与确认框） */
  onPlay?: (id: string) => void
  onCancel?: (id: string) => void
}) {
  const { t, locale } = useI18n()
  const s = film.session
  const assets = doc.assets
  const graph = useMemo(() => (s ? layoutGraph({ session: s, assets: assets ?? {}, hasStyle: !!styleUrl, styleUrl }) : null),
                        [s, assets, styleUrl])
  /** 镜头 id → 镜头：片段卡上的镜头小标签用 */
  const shots = useMemo(() => shotsById(doc), [doc])
  const [view, setView] = useState({ scale: 1, x: 24, y: 24 })
  const [focus, setFocus] = useState<string | null>(selected)
  const [hover, setHover] = useState<string | null>(null)
  useEffect(() => { setFocus(selected) }, [selected])
  const box = useRef<HTMLDivElement>(null)
  const drag = useRef<{ x: number; y: number; vx: number; vy: number } | null>(null)
  // Esc 先取消选中（只有选中时才拦，仅悬停放行给画布关闭）：捕获阶段抢在画布的「Esc 关闭」前面，preventDefault 后画布就不处理了
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || !focus) return
      e.preventDefault()
      setFocus(null)
      setHover(null)
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [focus, hover])
  const key = hover ?? focus
  const lit = useMemo(() => (graph ? related(graph, key) : new Set<string>()), [graph, key])

  const stop = (e: { stopPropagation: () => void }) => e.stopPropagation()
  if (!s || !graph) {
    return (
      <div className="ngv" role="region" aria-label={t('graph.viewAria')} data-testid="node-graph" onPointerDown={stop} onWheel={stop}>
        <div className="ngv__empty">
          <p>{t('graph.noSession')}</p>
          <Button size="sm" onClick={onOpenFilm}>{t('graph.openFilm')}</Button>
        </div>
      </div>
    )
  }

  const down = (e: RPointerEvent<HTMLDivElement>) => {
    e.stopPropagation()
    if ((e.target as HTMLElement).closest('.ngv__node, .ngv__tools')) return
    drag.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y }
  }
  const move = (e: RPointerEvent<HTMLDivElement>) => {
    const d = drag.current
    if (d) setView((v) => ({ ...v, x: d.vx + e.clientX - d.x, y: d.vy + e.clientY - d.y }))
  }
  const up = () => { drag.current = null }
  const wheel = (e: RWheelEvent<HTMLDivElement>) => {
    e.stopPropagation()
    const rect = box.current?.getBoundingClientRect()
    const px = e.clientX - (rect?.left ?? 0)
    const py = e.clientY - (rect?.top ?? 0)
    setView((v) => {
      const scale = Math.min(ZOOM.max, Math.max(ZOOM.min, v.scale * Math.exp(-e.deltaY * 0.001)))
      const k = scale / v.scale
      return { scale, x: px - (px - v.x) * k, y: py - (py - v.y) * k }
    })
  }
  const fit = () => { if (box.current) setView(fitView(graph, box.current.clientWidth, box.current.clientHeight)) }

  /** 首帧来源图：关键帧，或那一段 / 那个节点采用的那次的尾帧（由它自己的卡片取回） */
  const frameOf = (ff: string | null): string | null => {
    if (!ff) return null
    if (ff.startsWith('keyframe:')) return kfUrls[ff.slice('keyframe:'.length)] ?? null
    const src = ff.replace(/^(relay|tail):/, '')
    const it = [...s.clips, ...freeNodes(s)].find((x) => x.id === src)
    const lf = it ? chosenAttempt(it)?.last_frame : null
    return lf ? film.files[lf] ?? null : null
  }
  const kfShots = Object.keys(kfUrls)
  const assetOptions = graph.nodes.flatMap((n) => (n.kind === 'asset' && n.image
    ? [{ id: n.assetId, name: n.role === 'style' ? t('graph.style') : n.name }] : []))
  const byId = new Map(graph.nodes.map((n) => [n.id, n]))
  const dimmed = lit.size > 0

  return (
    <div className="ngv" ref={box} role="region" aria-label={t('graph.viewAria')} data-testid="node-graph" onPointerDown={down} onPointerMove={move}
         onPointerUp={up} onPointerLeave={up} onWheel={wheel}
         onClick={(e) => { if (!(e.target as HTMLElement).closest('.ngv__node, .ngv__tools')) setFocus(null) }}>
      <div className="ngv__tools">
        <Button size="sm" variant="ghost" onClick={fit}><Maximize2 aria-hidden />{t('graph.fit')}</Button>
        <Button size="sm" variant="ghost" disabled={film.busy} onClick={() => void film.createFree()}>
          <Plus aria-hidden />{t('graph.newFree')}
        </Button>
        {film.error && <span className="ngv__err">{formatMsg(film.error, locale)}</span>}
        {blocked && <span className="ngv__err">{blocked}</span>}
      </div>
      <div className="ngv__world"
           style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})`, width: graph.width, height: graph.height }}>
        <svg className="ngv__edges" width={graph.width + 80} height={graph.height} aria-hidden="true">
          {graph.edges.map((e) => {
            const on = key !== null && (e.from === key || e.to === key)
            return (
              <path key={e.id} data-edge={e.id} d={edgePath(byId.get(e.from)!, byId.get(e.to)!)}
                    className={cn('ngv__edge', `ngv__edge--${e.kind}`, dimmed && (on ? 'is-lit' : 'is-dim'))} />
            )
          })}
        </svg>
        {graph.nodes.map((n) => {
          const style = { left: n.x, top: n.y, width: n.w, height: n.h }
          const cls = cn('ngv__node', `ngv__node--${n.kind}`, n.id === focus && 'is-on',
                         dimmed && (lit.has(n.id) ? 'is-lit' : 'is-dim'))
          if (n.kind === 'episode') return <div key={n.id} className={cls} style={style}>{n.episode}</div>
          const pick = () => {
            setFocus(n.id)
            if (n.kind === 'clip' || n.kind === 'free') onSelect(n.id)
          }
          const hot = hover === n.id || focus === n.id
          return (
            <div key={n.id} className={cls} style={style} data-node={n.id} tabIndex={0}
                 onClick={pick} onKeyDown={(e) => { if (e.key === 'Enter' && e.target === e.currentTarget) pick() }}
                 onMouseEnter={() => setHover(n.id)} onMouseLeave={() => setHover(null)}>
              {n.kind === 'asset' && (
                <AssetCard role={n.role} name={n.name} image={n.image} usedBy={n.usedBy} onOpen={onOpenAssets} />
              )}
              {n.kind === 'clip' && (
                <ClipCard clip={n.clip} s={s} film={film} blocked={blocked} hot={hot}
                          tags={clipShotTags(n.clip.shots, shots)}
                          fallback={frameOf(n.clip.first_frame)} onDerive={() => void film.createFree(n.clip.id)}
                          onPlay={onPlay && (() => onPlay(n.id))} onCancel={onCancel && (() => onCancel(n.id))} />
              )}
              {n.kind === 'free' && (
                <FreeCard node={n.node} s={s} film={film} blocked={blocked} hot={hot}
                          fallback={frameOf(n.node.first_frame)} kfShots={kfShots} assetOptions={assetOptions}
                          onPlay={onPlay && (() => onPlay(n.id))} onCancel={onCancel && (() => onCancel(n.id))} />
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
