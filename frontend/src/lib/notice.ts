/** 结果提示（右下角 toast）。失败的停留更久并带关闭按钮（保存失败这类要让人看到）。log 只给测试读：单测没挂 <Toaster>。 */
import { toast } from 'sonner'

const log: { kind: 'ok' | 'err'; msg: string }[] = []
export const notice = {
  ok(msg: string, description?: string) { log.push({ kind: 'ok', msg }); toast.success(msg, { description }) },
  err(msg: string, description?: string) { log.push({ kind: 'err', msg }); toast.error(msg, { description, duration: 12000, closeButton: true }) },
  log,
}
