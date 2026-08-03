/** 上传文本的章节解析与分段选取。
 *
 *  中文小说的分章标记形态很杂：《药》用光秃秃的「一二三四」独占一行，
 *  网文多是「第十二章 标题」，译作常见「Chapter 3」。这里按优先级试多套模式，
 *  取命中数 ≥2 且优先级最高的那套——宁可识别不出（回退全文/自定义），
 *  也不要把正文里的句子误判成章节标题。
 */

export interface Segment {
  /** 在原文中的字符区间 [start, end) */
  start: number
  end: number
  title: string
  chars: number
}

interface Pattern {
  name: string
  priority: number
  re: RegExp
}

const PATTERNS: Pattern[] = [
  { name: '第N章', priority: 4,
    re: /^[ \t　]*第\s*[0-9０-９一二三四五六七八九十百千零〇两]{1,12}\s*[章回节卷篇折]([ \t　].*)?$/ },
  { name: 'Chapter N', priority: 4,
    re: /^[ \t　]*chapter\s+[0-9ivxlcIVXLC]+\b.*$/i },
  { name: '数字序号', priority: 3,
    re: /^[ \t　]*[0-9]{1,3}\s*[、.．]\s*\S.*$/ },
  { name: '汉字序号', priority: 2,
    re: /^[ \t　]*[一二三四五六七八九十百]{1,4}\s*[、．.]?[ \t　]*$/ },
]

/** 解析章节；识别不出返回空数组 */
export function parseChapters(text: string): Segment[] {
  const lines: { text: string; start: number; end: number }[] = []
  let pos = 0
  for (const line of text.split('\n')) {
    lines.push({ text: line, start: pos, end: pos + line.length })
    pos += line.length + 1
  }

  let best: { pattern: Pattern; hits: number[] } | null = null
  for (const pattern of PATTERNS) {
    const hits = lines
      .map((l, i) => (pattern.re.test(l.text) ? i : -1))
      .filter((i) => i >= 0)
    if (hits.length < 2) continue
    if (!best || pattern.priority > best.pattern.priority) {
      best = { pattern, hits }
    }
  }
  if (!best) return []

  const segments: Segment[] = []
  // 首个标记之前的内容（前言/楔子）也算一段，否则选章节会悄悄丢掉它
  const first = lines[best.hits[0]].start
  if (text.slice(0, first).trim().length > 0) {
    segments.push(mk(text, 0, first, '（开头）'))
  }
  best.hits.forEach((lineIdx, n) => {
    const start = lines[lineIdx].start
    const end = n + 1 < best!.hits.length
      ? lines[best!.hits[n + 1]].start
      : text.length
    segments.push(mk(text, start, end, lines[lineIdx].text.trim()))
  })
  return segments.filter((s) => s.chars > 0)
}

function mk(text: string, start: number, end: number, title: string): Segment {
  return { start, end, title, chars: text.slice(start, end).trim().length }
}

/** 在中点附近的段落边界处对半切——不从句子中间劈开 */
export function halfOf(text: string, which: 'first' | 'second'): string {
  const mid = Math.floor(text.length / 2)
  const after = text.indexOf('\n', mid)
  const before = text.lastIndexOf('\n', mid)
  const cut = after < 0 ? (before < 0 ? mid : before)
    : before < 0 ? after
    : (after - mid <= mid - before ? after : before)
  return (which === 'first' ? text.slice(0, cut) : text.slice(cut)).trim()
}

/** 非空段落（自定义分段以此为单位，比字符偏移好用得多） */
export function paragraphs(text: string): string[] {
  return text.split(/\n+/).map((p) => p.trim()).filter(Boolean)
}

export function joinParagraphs(list: string[]): string {
  return list.join('\n')
}
