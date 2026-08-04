/** 登录态：token 存 localStorage，刷新页面不用重登。
 *
 *  这里只管 token 的存取与失效广播；登录/注册的网络请求在 api.ts，
 *  两边分开是为了避免 api ↔ auth 循环依赖。
 */
const KEY = 'storyboard.token'
const USER_KEY = 'storyboard.user'

/** localStorage 在隐私模式/禁用存储时不可用。此时退化为内存保存：
 *  刷新页面要重登，但至少登得进去——否则会「登录成功后立刻被弹回登录页」。 */
const mem: Record<string, string | null> = { [KEY]: null, [USER_KEY]: null }

function read(k: string): string | null {
  try {
    return localStorage.getItem(k) ?? mem[k]
  } catch {
    return mem[k]
  }
}

function write(k: string, v: string | null): void {
  mem[k] = v
  try {
    if (v === null) localStorage.removeItem(k)
    else localStorage.setItem(k, v)
  } catch { /* 存不下就只靠内存，本次会话内仍可用 */ }
}

export interface User {
  id: string
  username: string
  created_at: string
}

let listeners: (() => void)[] = []

export function getToken(): string | null {
  return read(KEY)
}

export function getCachedUser(): User | null {
  const raw = read(USER_KEY)
  try {
    return raw ? (JSON.parse(raw) as User) : null
  } catch {
    return null
  }
}

export function setSession(token: string, user: User): void {
  write(KEY, token)
  write(USER_KEY, JSON.stringify(user))
}

export function clearSession(): void {
  write(KEY, null)
  write(USER_KEY, null)
}

/** token 失效时（后端返回 401）广播出去，让 App 退回登录页 */
export function onUnauthorized(fn: () => void): () => void {
  listeners.push(fn)
  return () => { listeners = listeners.filter((f) => f !== fn) }
}

export function notifyUnauthorized(): void {
  clearSession()
  for (const fn of listeners) fn()
}
