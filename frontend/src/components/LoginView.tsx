import { useState } from 'react'
import { login, register } from '../api'
import { setSession } from '../auth'
import type { User } from '../auth'

/** 登录/注册。每个人的历史记录与资产库互相隔离，所以进门先表明身份。 */
export function LoginView({ onDone, firstRun }: {
  onDone: (user: User) => void
  /** 服务端还没有任何用户——首个注册者会接管单用户时代留下的历史记录 */
  firstRun: boolean
}) {
  const [mode, setMode] = useState<'login' | 'register'>(firstRun ? 'register' : 'login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const registering = mode === 'register'
  // 密码打错一个字符，注册完就再也登不进去——所以注册必须二次确认
  const mismatch = registering && confirm.length > 0 && confirm !== password
  const ready = username.trim() && password && (!registering || confirm === password)

  const switchMode = (m: 'login' | 'register') => {
    setMode(m)
    setConfirm('')
    setError(null)
  }

  const submit = async (e: { preventDefault: () => void }) => {
    e.preventDefault()
    if (!ready) return
    setBusy(true)
    setError(null)
    try {
      const fn = mode === 'login' ? login : register
      const { token, user } = await fn(username.trim(), password)
      setSession(token, user)
      onDone(user)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login">
      <form className="login__box" onSubmit={submit}>
        <h1>小说 → 分镜 IR</h1>
        <p className="login__sub">忠实转换：剧情属于小说，呈现属于系统</p>

        <div className="login__tabs">
          {(['login', 'register'] as const).map((m) => (
            <button
              type="button"
              key={m}
              className={`login__tab${mode === m ? ' is-on' : ''}`}
              onClick={() => switchMode(m)}
            >
              {m === 'login' ? '登录' : '注册'}
            </button>
          ))}
        </div>

        {firstRun && registering && (
          <p className="login__note">
            服务端还没有任何账号。第一个注册的账号会接管此前单用户时代的历史记录。
          </p>
        )}

        <label className="login__field">
          <span>用户名</span>
          <input
            value={username}
            autoFocus
            autoComplete="username"
            placeholder="2–32 位，中英文、数字、下划线"
            onChange={(e) => setUsername(e.target.value)}
          />
        </label>
        <label className="login__field">
          <span>密码</span>
          <input
            type="password"
            value={password}
            autoComplete={registering ? 'new-password' : 'current-password'}
            placeholder={registering ? '至少 6 位' : ''}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>

        {registering && (
          <label className="login__field">
            <span>确认密码</span>
            <input
              type="password"
              value={confirm}
              autoComplete="new-password"
              placeholder="再输入一次"
              onChange={(e) => setConfirm(e.target.value)}
            />
            {mismatch && <em className="login__mismatch">两次输入的密码不一致</em>}
          </label>
        )}

        {error && <p className="login__err">{error}</p>}

        <button className="btn" type="submit" disabled={busy || !ready}>
          {busy ? '请稍候…' : registering ? '注册并进入' : '登录'}
        </button>

        <p className="login__tip">
          每个账号的转换历史与资产库互相隔离。密码以 PBKDF2 哈希存储，不保存明文。
        </p>
      </form>
    </div>
  )
}
