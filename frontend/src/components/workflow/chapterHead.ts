/** 章节页交给分镜视图里各处的两样东西（分镜视图由 App 组好，但渲染在章节页里面，所以能读到这里的 Context）：
 *  - 精简头部：画布不认识章节，只管把它摆在左下角；
 *  - 本步主按钮：镜头三栏视图挂着时由它的通栏按钮接管，章节页就不再摆右下角那个（每屏一个主按钮）。 */
import { createContext } from 'react'
import type { ReactNode } from 'react'
import type { Fix, Primary } from '@/workflow'

export const ChapterHeadContext = createContext<ReactNode | null>(null)

export interface StepPrimary {
  primary: Primary
  busy: boolean
  run: () => void
  fix: (f: Fix) => void
  /** 挂上时 claim(true)、卸下时 claim(false)：接管期间章节页不摆固定主按钮 */
  claim: (on: boolean) => void
}

export const StepPrimaryContext = createContext<StepPrimary | null>(null)
