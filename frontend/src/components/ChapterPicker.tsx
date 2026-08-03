import { useEffect, useMemo, useState } from 'react'
import { halfOf, joinParagraphs, paragraphs, parseChapters } from '../chapters'

type Mode = 'full' | 'chapters' | 'custom'
type Half = 'all' | 'first' | 'second'

interface Props {
  /** 上传/粘贴进来的整篇原文 */
  source: string
  /** 选出的待转换文本 */
  onChange: (text: string) => void
}

export function ChapterPicker({ source, onChange }: Props) {
  const chapters = useMemo(() => parseChapters(source), [source])
  const paras = useMemo(() => paragraphs(source), [source])

  const [mode, setMode] = useState<Mode>('full')
  const [picked, setPicked] = useState<number[]>([])
  const [half, setHalf] = useState<Half>('all')
  const [from, setFrom] = useState(1)
  const [to, setTo] = useState(paras.length)

  // 换了原文就回到全文，避免沿用上一篇的选择
  useEffect(() => {
    setMode('full')
    setPicked([])
    setHalf('all')
    setFrom(1)
    setTo(paragraphs(source).length)
  }, [source])

  // 选择状态一变就把选段回填给表单（不读 value，故不会与手工编辑互相打架）
  useEffect(() => {
    if (mode === 'full') return onChange(source)
    if (mode === 'custom') {
      const a = Math.max(1, Math.min(from, paras.length))
      const b = Math.max(a, Math.min(to, paras.length))
      return onChange(joinParagraphs(paras.slice(a - 1, b)))
    }
    const order = [...picked].sort((x, y) => x - y)
    if (!order.length) return onChange('')
    let text = order.map((i) => source.slice(chapters[i].start, chapters[i].end).trim())
                    .join('\n')
    if (order.length === 1 && half !== 'all') text = halfOf(text, half)
    onChange(text)
  }, [mode, picked, half, from, to, source, chapters, paras, onChange])

  const toggle = (i: number) =>
    setPicked((prev) => (prev.includes(i) ? prev.filter((x) => x !== i) : [...prev, i]))

  return (
    <div className="chp">
      <div className="chp__modes">
        <ModeBtn on={mode === 'full'} onClick={() => setMode('full')}>全文</ModeBtn>
        {chapters.length > 0 && (
          <ModeBtn on={mode === 'chapters'} onClick={() => setMode('chapters')}>
            按章节（识别到 {chapters.length} 章）
          </ModeBtn>
        )}
        <ModeBtn on={mode === 'custom'} onClick={() => setMode('custom')}>自定义分段</ModeBtn>
        {chapters.length === 0 && (
          <span className="chp__none">未识别到章节标记，可用自定义分段按段落切</span>
        )}
      </div>

      {mode === 'chapters' && (
        <>
          <div className="chp__list">
            {chapters.map((c, i) => (
              <button
                type="button"
                key={`${c.start}-${i}`}
                className={`chp__ch${picked.includes(i) ? ' is-on' : ''}`}
                onClick={() => toggle(i)}
              >
                <b>{c.title || `第 ${i + 1} 段`}</b>
                <em>{c.chars} 字</em>
              </button>
            ))}
          </div>
          {picked.length === 1 && (
            <div className="chp__half">
              <span>选段范围</span>
              {(['all', 'first', 'second'] as Half[]).map((h) => (
                <button
                  type="button"
                  key={h}
                  className={`chp__hb${half === h ? ' is-on' : ''}`}
                  onClick={() => setHalf(h)}
                >
                  {{ all: '整章', first: '前半章', second: '后半章' }[h]}
                </button>
              ))}
              <span className="chp__tip">半章在段落边界处切，不会从句子中间劈开</span>
            </div>
          )}
          {picked.length > 1 && (
            <p className="chp__tip">已选 {picked.length} 章，按原文顺序拼接转换</p>
          )}
          {!picked.length && <p className="chp__tip">点选要转换的章节（可多选）</p>}
        </>
      )}

      {mode === 'custom' && (
        <div className="chp__custom">
          <label>
            第
            <input type="number" min={1} max={paras.length} value={from}
                   onChange={(e) => setFrom(Number(e.target.value) || 1)} />
            段
          </label>
          <span>至</span>
          <label>
            第
            <input type="number" min={1} max={paras.length} value={to}
                   onChange={(e) => setTo(Number(e.target.value) || 1)} />
            段
          </label>
          <span className="chp__tip">全文共 {paras.length} 个自然段</span>
        </div>
      )}
    </div>
  )
}

function ModeBtn({ on, onClick, children }: {
  on: boolean; onClick: () => void; children: React.ReactNode
}) {
  return (
    <button type="button" className={`chp__mode${on ? ' is-on' : ''}`} onClick={onClick}>
      {children}
    </button>
  )
}
