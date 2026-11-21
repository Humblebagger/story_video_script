import { createContext } from 'react'

/** 后台内部跳转：to 是 adminPath() 拼出的地址；replace 为 true 时不留历史（改筛选用） */
export type AdminNavFn = (to: string, replace?: boolean) => void

/** AdminView 提供；没有提供者时（单独渲染某一页）AdminLink 就是普通链接 */
export const AdminNavContext = createContext<AdminNavFn | null>(null)
