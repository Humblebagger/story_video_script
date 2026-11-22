/** 管理员提示：产品界面里在中性名字后面给管理员看的厂商字样。
 *  数据只来自 /admin/service（角色确认为管理员后由 App 请求一次），只放在内存里，退出登录即清空。
 *  这个文件、以及所有用它的组件里都不写任何厂商名：显示的文字是接口给的原样字符串。
 *  没有数据（普通用户、请求失败、旧后端）时两个钩子都给 null，界面与普通用户完全一样。 */
import { createContext, useContext } from 'react'
import { useI18n } from '@/i18n/core'
import type { AdminService } from './types'

export type AdminHints = NonNullable<AdminService['film']> | null

const Ctx = createContext<AdminHints>(null)
export const AdminHintsProvider = Ctx.Provider

/** (档位 id) → 厂商自己的档位名；不是管理员、档位不在表里时为 null */
export function useTierHint(): (tier: string | null | undefined) => string | null {
  const h = useContext(Ctx)
  return (tier) => (tier ? h?.tiers.find((r) => r.id === tier)?.vendor_label ?? null : null)
}

/** 配音厂商名；不是管理员时为 null */
export function useTtsHint(): string | null {
  return useContext(Ctx)?.tts.provider ?? null
}

/** 失败原因该不该带提示、带哪一种：生成服务侧的（film.vendor.*）用档位的，配音服务侧的（tts.vendor.*）用配音的 */
export function hintFor(code: string | undefined, tierHint: string | null, ttsHint: string | null): string | null {
  if (!code) return null
  if (code.startsWith('film.vendor.')) return tierHint
  if (code.startsWith('tts.vendor.')) return ttsHint
  return null
}

/** (原文, 提示) → 有提示就在后面加括号；括号的写法走语言包 common.paren */
export function useWithHint(): (text: string, hint: string | null) => string {
  const { t } = useI18n()
  return (text, hint) => (hint ? text + t('common.paren', { text: hint }) : text)
}
