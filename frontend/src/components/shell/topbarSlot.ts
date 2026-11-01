/** 顶栏中间的插槽：AppShell 提供 #topbar-center 元素，章节工作流把步骤条 portal 进去；拿不到（null）时在原位渲染。 */
import { createContext, useContext } from 'react'

export const TopbarSlotContext = createContext<HTMLElement | null>(null)
export const useTopbarSlot = () => useContext(TopbarSlotContext)

/** 左栏是否收起：侧栏内容（项目导航）据此切换成只有图标的形态。 */
export const SidebarCollapsedContext = createContext(false)
export const useSidebarCollapsed = () => useContext(SidebarCollapsedContext)
