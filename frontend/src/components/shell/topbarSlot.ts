/** 顶栏中间的插槽：AppShell 提供 #topbar-center 元素，章节工作流把步骤条 portal 进去；拿不到（null）时在原位渲染。 */
import { createContext, useContext } from 'react'

export const TopbarSlotContext = createContext<HTMLElement | null>(null)
export const useTopbarSlot = () => useContext(TopbarSlotContext)
