import { useContext } from 'react'
import type { ComponentProps, MouseEvent } from 'react'
import { AdminNavContext } from './navContext'

/** 后台内部链接：真链接（可在新标签页打开），普通左键点击走前端路由。 */
export function AdminLink({ to, onClick, ...rest }: { to: string } & Omit<ComponentProps<'a'>, 'href'>) {
  const nav = useContext(AdminNavContext)
  const click = (e: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(e)
    if (!nav || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return
    e.preventDefault()
    nav(to)
  }
  return <a href={to} onClick={click} {...rest} />
}
