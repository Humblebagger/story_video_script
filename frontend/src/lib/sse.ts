/** 解析 text/event-stream：把累积的缓冲切成完整事件，返回事件与剩下的半截。只认 event / data 两个字段。 */
import type { AssistantEvent } from '@/types'

export function parseSse(buffer: string): { events: AssistantEvent[]; rest: string } {
  const events: AssistantEvent[] = []
  const blocks = buffer.replace(/\r\n/g, '\n').split('\n\n')
  const rest = blocks.pop() ?? ''
  for (const block of blocks) {
    let event = 'message'
    const data: string[] = []
    for (const line of block.split('\n')) {
      if (line.startsWith('event:')) event = line.slice(6).trim()
      else if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''))
    }
    if (!data.length) continue
    try {
      events.push({ event, data: JSON.parse(data.join('\n')) } as AssistantEvent)
    } catch { /* 坏的一块跳过 */ }
  }
  return { events, rest }
}
