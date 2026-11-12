/** 应用根：接收 router 实例（浏览器用 createBrowserRouter，测试用 createMemoryRouter 并持有它来 navigate、读 state） */
import type { createBrowserRouter } from 'react-router'
import { RouterProvider } from 'react-router/dom'

export type AppRouter = ReturnType<typeof createBrowserRouter>

export function AppRoot({ router }: { router: AppRouter }) {
  return <RouterProvider router={router} />
}
