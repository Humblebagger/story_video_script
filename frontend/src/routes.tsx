/** 路由配置：只有一条通配路由，位置由 App 用 parseLocation 解析（设计 §2：不用 loader/action，加载仍在 App） */
import type { RouteObject } from 'react-router'
import App from './App'

export const routes: RouteObject[] = [{ path: '*', element: <App /> }]
