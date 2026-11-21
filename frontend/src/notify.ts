/** 桌面通知：转换要跑好几分钟，用户不该守着页面等。 */

/** 在提交那一刻申请权限——必须由用户手势触发，浏览器才不会直接拒 */
export function primeNotifications(): void {
  if (!('Notification' in window)) return
  if (Notification.permission === 'default') void Notification.requestPermission()
}

/** tag 相同的通知互相顶替（出片按片段给，各段的通知不互相盖掉）；给了 onClick，点通知先把窗口拉到前面再执行 */
export function notify(title: string, body: string, opts: { tag?: string; onClick?: () => void } = {}): void {
  if (!('Notification' in window) || Notification.permission !== 'granted') return
  try {
    const n = new Notification(title, { body, tag: opts.tag ?? 'storyboard-job' })
    const { onClick } = opts
    if (onClick) n.onclick = () => { window.focus(); n.close(); onClick() }
  } catch {
    /* 部分浏览器在非安全上下文下会抛异常，通知失败不该影响主流程 */
  }
}
