/** 后端消息对象的渲染：字符串原样、代码按语言、带类型参数、嵌套原因、缺译回落。跑法：npm test */
import { formatMsg, itemError, errValue } from '../src/i18n/serverMsg'
import { ApiError } from '../src/api'

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
must(typeof errValue(api) === 'object', 'ApiError 保留 detail 对象')
must(errValue(new Error('plain')) === 'plain', '普通错误取 message')

console.log('\nALL PASS')
