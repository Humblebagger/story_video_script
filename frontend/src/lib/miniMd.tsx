/** 助手回答的极简渲染：段落、换行、**加粗**、无序（- / •）与有序（1.）列表。不解析 HTML，不加依赖。 */
import type { ReactNode } from 'react'

function inline(text: string, key: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*)/g).filter(Boolean).map((part, i) =>
    part.startsWith('**') && part.endsWith('**') && part.length > 4
      ? <strong key={`${key}-${i}`}>{part.slice(2, -2)}</strong>
      : <span key={`${key}-${i}`}>{part}</span>)
}

export function MiniMd({ text }: { text: string }) {
  const out: ReactNode[] = []
  let list: { ordered: boolean; items: string[] } | null = null
  const flush = () => {
    if (!list) return
    const items = list.items.map((it, i) => <li key={i}>{inline(it, `li${out.length}-${i}`)}</li>)
    out.push(list.ordered
      ? <ol key={`l${out.length}`} className="list-decimal pl-5">{items}</ol>
      : <ul key={`l${out.length}`} className="list-disc pl-5">{items}</ul>)
    list = null
  }
  for (const line of text.split('\n')) {
    const ul = /^\s*[-•*]\s+(.*)$/.exec(line)
    const ol = /^\s*\d+[.)]\s+(.*)$/.exec(line)
    if (ul || ol) {
      const ordered = !!ol
      if (list && list.ordered !== ordered) flush()
      list ??= { ordered, items: [] }
      list.items.push((ul ?? ol)![1])
      continue
    }
    flush()
    if (line.trim()) out.push(<p key={`p${out.length}`}>{inline(line, `p${out.length}`)}</p>)
  }
  flush()
  return <div className="assistant__md">{out}</div>
}
