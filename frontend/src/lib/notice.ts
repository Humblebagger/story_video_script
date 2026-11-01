/** 转瞬即逝的结果提示（右下角 toast）。log 只给测试读：单测没挂 <Toaster>。 */
import { toast } from 'sonner'

const log: { kind: 'ok' | 'err'; msg: string }[] = []
export const notice = {
  ok(msg: string, description?: string) { log.push({ kind: 'ok', msg }); toast.success(msg, { description }) },
  err(msg: string, description?: string) { log.push({ kind: 'err', msg }); toast.error(msg, { description }) },
  log,
}
