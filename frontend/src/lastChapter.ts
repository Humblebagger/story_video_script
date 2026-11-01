/** 每部小说最近打开的章节：存在本机，概览页的「继续」按钮用。读写都包 try/catch，存不了就当没有。 */
const key = (nid: string) => `inkreel.lastChapter.${nid}`

export function readLastChapter(nid: string): string | null {
  try { return localStorage.getItem(key(nid)) } catch { return null }
}

export function writeLastChapter(nid: string, cid: string) {
  try { localStorage.setItem(key(nid), cid) } catch { /* 只在本页生效 */ }
}
