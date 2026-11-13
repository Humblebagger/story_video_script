/** 后端消息对象的渲染：字符串原样、代码按语言、带类型参数、嵌套原因、缺译回落。跑法：npm test */
import { formatMsg, itemError, errValue } from '../src/i18n/serverMsg'
import { ApiError, conflictCny } from '../src/api'
import { zh } from '../src/i18n/zh'
import { en } from '../src/i18n/en'

const must = (cond: boolean, msg: string) => { if (!cond) throw new Error('✗ ' + msg) }

// 1. 字符串 / 空值
must(formatMsg('原样') === '原样', '字符串原样')
must(formatMsg(null) === '' && formatMsg(undefined) === '', '空值为空串')

// 2. common.unknown 的模板是 {message}
const unk = { code: 'common.unknown', params: { message: 'raw' }, message: 'raw' }
must(formatMsg(unk, 'zh') === 'raw' && formatMsg(unk, 'en') === 'raw', 'common.unknown 原样')

// 3. 缺译：没有这个代码 → message → 代码名
must(formatMsg({ code: 'x.not.registered', message: '兜底' }, 'en') === '兜底', '缺译用 message')
must(formatMsg({ code: 'x.not.registered' }, 'en') === 'x.not.registered', '没有 message 用代码名')

// 4. 带类型参数与嵌套：用 common.unknown 的 {message} 占位验证
const wrap = (v: unknown) => ({ code: 'common.unknown', params: { message: v } })
must(formatMsg(wrap({ t: 'money', cny: 3 }) as never, 'en') === '¥3.00', '金额')
must(formatMsg(wrap({ t: 'vendor', text: 'HTTP 500' }) as never, 'en') === 'HTTP 500', '厂商原文')
must(formatMsg(wrap(['a', 'b']) as never, 'zh') === 'a、b', '列表中文用顿号')
must(formatMsg(wrap(['a', 'b']) as never, 'en') === 'a, b', '列表英文用逗号')
must(formatMsg(wrap({ code: 'common.unknown', params: { message: 'inner' } }) as never, 'en') === 'inner', '嵌套原因')

// 5. 旧数据：有 error_msg 按代码，没有就原样 error
must(itemError({ error: '旧中文', error_msg: null }) === '旧中文', '旧数据原样')
must(itemError({ error: '中文', error_msg: { code: 'common.unknown', params: { message: 'new' } } }, 'en') === 'new',
  '有 error_msg 按代码')

// 6. errValue：ApiError 取 detail（对象原样保留，渲染时再格式化），其它取 message
const api = new ApiError('m', 409, { code: 'common.unknown', params: { message: 'd' }, message: 'd' })
must(errValue(api) === api.detail, 'ApiError 的 detail 引用原样保留（渲染时再格式化）')
must(errValue(new Error('plain')) === 'plain', '普通错误取 message')

// 7. 真实代码：中英模板不同；金额、嵌套 cause、console 引用
const confirm = { code: 'film.run.confirm', params: { amount: { t: 'money', cny: 6 } }, message: '本次约 ¥6.00，请确认金额后再出片' }
must(formatMsg(confirm, 'zh') === '本次约 ¥6.00，请确认金额后再出片', '真实代码中文')
must(formatMsg(confirm, 'en') === en.srv.film.run.confirm.replace('{amount}', '¥6.00'), '真实代码英文')
must(formatMsg(confirm, 'zh') !== formatMsg(confirm, 'en'), '中英模板不同')
const cause = { code: 'film.run.nothing', params: {} }
const amb = { code: 'film.submit.ambiguous', params: { console: { t: 'ref', code: 'console.minimax' }, cause } }
must(formatMsg(amb, 'zh').includes('MiniMax 开放平台') && formatMsg(amb, 'zh').includes('没有要出的段'), 'console 引用与嵌套 cause（中文）')
must(formatMsg(amb, 'en').includes(en.srv.console.minimax) && formatMsg(amb, 'en').includes(en.srv.film.run.nothing),
  'console 引用与嵌套 cause（英文）')

// 8. 英文缺译回落到中文模板（临时删掉英文条目，再还原）
{
  const node = en.srv.film.run as Record<string, string>
  const saved = node.nothing
  delete node.nothing
  try {
    must(formatMsg({ code: 'film.run.nothing', params: {}, message: 'm' }, 'en') === zh.srv.film.run.nothing, '英文缺译 → 中文模板')
  } finally { node.nothing = saved }
}

// 9. 旧格式：字符串 detail、{message, expected_cny}
const oldObj = { message: '旧提示', expected_cny: 5 }
must(formatMsg(oldObj, 'en') === '旧提示', '旧对象取 message')
const apiOld = new ApiError('旧提示', 409, oldObj)
must(errValue(apiOld) === '旧提示' && conflictCny(apiOld) === 5, '旧 409：取 message、仍有重算金额')
const apiStr = new ApiError('串', 422, '串')
must(errValue(apiStr) === '串', '字符串 detail')
const apiCoded = new ApiError('m', 409, { ...confirm, expected_cny: 6 })
must(conflictCny(apiCoded) === 6, '带代码的 409 仍有重算金额')

console.log('\nALL PASS')
