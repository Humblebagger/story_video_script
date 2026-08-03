/** 桌面通知：转换要跑好几分钟，用户不该守着页面等。 */

/** 在提交那一刻申请权限——必须由用户手势触发，浏览器才不会直接拒 */
export function primeNotifications(): void {
  if (!('Notification' in window)) return
  if (Notification.permission === 'default') void Notification.requestPermission()
}

export function notify(title: string, body: string): void {
  if (!('Notification' in window) || Notification.permission !== 'granted') return
  try {
    new Notification(title, { body, tag: 'storyboard-job' })
  } catch {
    /* 部分浏览器在非安全上下文下会抛异常，通知失败不该影响主流程 */
  }
}
