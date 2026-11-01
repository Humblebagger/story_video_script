/** 章节页把精简头部通过 Context 交给画布（画布不认识章节，只管把它摆在左上角）。 */
import { createContext } from 'react'
import type { ReactNode } from 'react'

export const ChapterHeadContext = createContext<ReactNode | null>(null)
