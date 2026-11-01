/** 新手提示：按目标出现、一次一条、看过的存在本机。 */
export const TOUR = ['new-novel', 'import', 'steps', 'progress'] as const
export type TourId = (typeof TOUR)[number]
const KEY = 'inkreel.tour'

export function seen(): TourId[] {
  try { return JSON.parse(localStorage.getItem(KEY) ?? '[]') as TourId[] } catch { return [] }
}
export function markSeen(ids: readonly TourId[]) {
  try { localStorage.setItem(KEY, JSON.stringify([...new Set([...seen(), ...ids])])) } catch { /* 只在本页生效 */ }
}
/** 测试环境（happy-dom）不开，免得挡住现有用例 */
export const tourEnabled = () => typeof navigator === 'undefined' || !/HappyDOM/i.test(navigator.userAgent)
