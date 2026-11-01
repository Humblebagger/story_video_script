/** 结果提示（右下角 toast）。失败的停留更久并带关闭按钮（保存失败这类要让人看到）。log 只给测试读：单测没挂 <Toaster>。 */
import { toast } from 'sonner'

const log: { kind: 'ok' | 'err'; msg: string }[] = []
const push = (kind: 'ok' | 'err', msg: string) => { log.push({ kind, msg }); if (log.length > 50) log.splice(0, log.length - 50) }
export const notice = {
  ok(msg: string, description?: string) { push('ok', msg); toast.success(msg, { description }) },
  err(msg: string, description?: string) { push('err', msg); toast.error(msg, { description, duration: 12000, closeButton: true }) },
  log,
}
