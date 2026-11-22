/** 后端消息对象的渲染：字符串原样、代码按语言、带类型参数、嵌套原因、缺译回落。跑法：npm test */
import { formatMsg, itemError, errValue, failHead, findingText } from '../src/i18n/serverMsg'
import { ApiError, conflictCny } from '../src/api'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
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

// 7. 真实代码：中英模板不同；金额、嵌套 cause
const confirm = { code: 'film.run.confirm', params: { amount: { t: 'money', cny: 6 } }, message: '本次约 ¥6.00，请确认金额后再出片' }
must(formatMsg(confirm, 'zh') === '本次约 ¥6.00，请确认金额后再出片', '真实代码中文')
must(formatMsg(confirm, 'en') === en.srv.film.run.confirm.replace('{amount}', '¥6.00'), '真实代码英文')
must(formatMsg(confirm, 'zh') !== formatMsg(confirm, 'en'), '中英模板不同')
const cause = { code: 'film.run.nothing', params: {} }
const amb = { code: 'film.submit.ambiguous', params: { cause } }
must(formatMsg(amb, 'zh').includes('请联系管理员核对') && formatMsg(amb, 'zh').includes('没有要出的段'), '嵌套 cause（中文）')
must(formatMsg(amb, 'en').includes(en.srv.film.run.nothing) && !formatMsg(amb, 'en').includes('{'),
  '嵌套 cause（英文）')

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

// 10. 旧会话里存的消息带已被拿掉的参数：按新模板渲染，不报错、不留占位符
{
  const old = { code: 'film.vendor.connect_failed', params: { kind: 'ConnectError' } }
  const enText = formatMsg(old, 'en')
  must(enText === en.srv.film.vendor.connect_failed && !enText.includes('{kind}') && !enText.includes('ConnectError'),
    '旧会话多余参数（en）渲染为新模板')
  const zhText = formatMsg(old, 'zh')
  must(zhText === zh.srv.film.vendor.connect_failed && !zhText.includes('{kind}') && !zhText.includes('ConnectError'),
    '旧会话多余参数（zh）渲染为新模板')
  const unk = formatMsg({ code: 'film.settings.no_model', params: { model: 'doubao-x' } }, 'en')
  must(unk === en.srv.film.settings.no_model && !unk.includes('doubao-x'), '旧会话 unknown_model 多余参数')
}

// 8. 参考编号：顶层 ref 附在渲染结果后；兜底 message 已带编号时不重复；嵌套原因不附
{
  const internal = { code: 'common.internal', params: {}, message: '服务器出了点问题，请稍后重试；仍失败请联系管理员（参考编号 K7Q2M9XD）', ref: 'K7Q2M9XD' }
  must(formatMsg(internal, 'zh') === '服务器出了点问题，请稍后重试；仍失败请联系管理员（参考编号 K7Q2M9XD）', '中文附编号')
  must(formatMsg(internal, 'en').endsWith(' (reference K7Q2M9XD)'), '英文附编号')
  const unreg = { code: 'x.not.registered', message: '兜底（参考编号 AB12CD34）', ref: 'AB12CD34' }
  must(formatMsg(unreg, 'en') === '兜底（参考编号 AB12CD34）', '缺译回落的 message 已带编号，不重复')
  must(itemError({ error: 'x', error_msg: { code: 'common.internal', params: {}, ref: 'K7Q2M9XD' } }, 'en').includes('K7Q2M9XD'), '持久化的 error_msg 也附编号')
  must(errValue(new ApiError('m', 500, internal)) === internal, 'errValue 保留带编号的 detail')
}

// 9. 转换失败带报告：整段渲染原因 + 换行 + 报告原文；一行显示只取原因
{
  const failed = { code: 'job.failed_report', params: {
    reason: { code: 'job.batch_failed', params: { batch: 2, retries: 3 } },
    report: { t: 'vendor', text: 'FAIL: E01 缺资产 C09' } } }
  must(formatMsg(failHead(failed), 'zh') === formatMsg({ code: 'job.batch_failed', params: { batch: 2, retries: 3 } }, 'zh'), '一行只取原因')
  must(failHead('第一行\n第二行') === '第一行', '旧数据取第一行')
  must(formatMsg(failHead({ code: 'llm.busy', params: {} }), 'en') === formatMsg({ code: 'llm.busy', params: {} }, 'en'), '没有报告的原样返回')
}

// 10. 转换失败带报告的具体文字（代码已登记，可以断言具体文字）
{
  const failed = { code: 'job.failed_report', params: {
    reason: { code: 'job.batch_failed', params: { batch: 2, retries: 3 } },
    report: { t: 'vendor', text: 'FAIL: E01 缺资产 C09' } } }
  must(formatMsg(failed, 'zh') === '批 2 重试 3 次后仍未通过校验\nFAIL: E01 缺资产 C09', '中文整段')
  must(formatMsg(failed, 'en').endsWith('\nFAIL: E01 缺资产 C09') && !formatMsg(failed, 'en').startsWith('批'), '英文原因 + 报告原文')
  must(formatMsg(failHead(failed), 'zh') === '批 2 重试 3 次后仍未通过校验', '一行只取原因')
}
// 子计划 5：报告参数的 lines 类型（逐项渲染、换行连接）；验证报告一条的说明（spec 子计划 5 C）
{
  const wrapL = (items: unknown) => ({ code: 'common.unknown', params: { message: { t: 'lines', items } } })
  must(formatMsg(wrapL([{ code: 'common.unknown', params: { message: 'a' } }, { t: 'vendor', text: 'b' }, 'c']) as never, 'en') === 'a\nb\nc',
    'lines 逐项渲染、换行连接')
  must(formatMsg(wrapL([]) as never, 'zh') === '', '空 lines 为空串')
  must(formatMsg(wrapL('x') as never, 'zh') === '', 'items 不是数组时为空串')
  must(formatMsg({ code: 'common.unknown', params: { message: { t: 'future', x: 1 } } } as never, 'en') === '', '不认识的 t 为空串（不崩）')
  const reason = { code: 'job.batch_failed', params: { batch: 2, retries: 3 } }
  const failed = { code: 'job.failed_report', params: { reason, report: { t: 'lines', items: [
    { code: 'common.unknown', params: { message: 'L1' } }, { code: 'common.unknown', params: { message: 'L2' } }] } } }
  must(formatMsg(failed, 'en') === en.srv.job.failed_report.replace('{reason}', formatMsg(reason, 'en')).replace('{report}', 'L1\nL2'),
    'failed_report 里的 lines（英文）')
  must(formatMsg(failed, 'zh') === `${zh.srv.job.batch_failed.replace('{batch}', '2').replace('{retries}', '3')}\nL1\nL2`, 'failed_report 里的 lines（中文）')
  must(formatMsg(failHead(failed), 'zh') === formatMsg(reason, 'zh'), '一行显示仍只取原因')
  must(findingText({ message: 'old' }) === 'old', '旧 finding（没有 msg）显示 message')
  must(findingText({ message: 'old', msg: { code: 'x.not.registered', params: {} } }, 'en') === 'old', '缺译回落到 message，不显示代码名')
  must(findingText({ message: 'old', msg: { code: 'common.unknown', params: { message: 'new' } } }, 'en') === 'new', '有 msg 按代码渲染')
  console.log('子计划 5：lines / findingText ✓')
}

// 子计划 5b：分镜检查（lint）逐条按规则渲染，英文里没有中文；中文与后端代码表的中文模板代入同一组参数后逐字相同；旧报告的原文照旧
{
  const CJK = /[\u4e00-\u9fff]/
  const codes = JSON.parse(readFileSync(resolve(process.cwd(), '../backend/server/messages_codes.json'), 'utf-8')) as Record<string, { zh: string }>
  const zhVal = (v: unknown): string => Array.isArray(v) ? v.map(zhVal).join('、') : typeof v === 'object' && v !== null ? String((v as { text?: unknown }).text ?? '') : String(v)
  const lintRules = Object.keys(en.srv.verify.lint) as (keyof typeof en.srv.verify.lint)[]
  must(lintRules.length === 23 && lintRules.every((k) => k in zh.srv.verify.lint), 'verify.lint 中英各 23 条')
  for (const rule of lintRules) {
    const holes = [...zh.srv.verify.lint[rule].matchAll(/\{(\w+)\}/g)].map((m) => m[1])
    const params: Record<string, unknown> = {}
    for (const k of holes) params[k] = k === 'options' ? ['default', 'summer'] : k === 'detail' ? { t: 'vendor', text: "'huge' is not valid" } : k === 'n' || k === 'beat' ? 2 : `X-${k}`
    const line = { code: 'verify.report.tool_error', params: { text: { code: `verify.lint.${rule}`, params } } }
    const e = formatMsg(line, 'en'), z = formatMsg(line, 'zh')
    must(!CJK.test(e) && !e.includes('{') && e.startsWith('  '), `${rule} 英文不混中文、占位符都填上：${e}`)
    const want = '  ' + codes[`verify.lint.${rule}`].zh.replace(/\{(\w+)\}/g, (_all, k: string) => zhVal(params[k]))
    must(z === want, `${rule} 中文与后端模板代入同一组参数后逐字相同：${z} ≠ ${want}`)
    must(CJK.test(z) && !e.includes(z.trim()), `${rule} 中文是中文、且与英文不同：${z}`)
  }
  const none = { code: 'verify.lint.ref_image_outfit', params: { card: 'C06', outfit: 'summer', options: { t: 'ref', code: 'verify.report.lint_none' } } }
  must(formatMsg(none, 'en') === '[C06] A reference image is tagged with outfit “summer”, which doesn’t exist (options: none)', formatMsg(none, 'en'))
  must(formatMsg(none, 'zh') === '[C06] 参考图标注的 outfit「summer」不存在（可选：无）', formatMsg(none, 'zh'))
  const opts = { code: 'verify.lint.outfit_unknown', params: { shot: 'E01-SH001', character: 'C01', outfit: 'summer', options: ['default', 'night'] } }
  must(formatMsg(opts, 'en').endsWith('(options: default, night)') && formatMsg(opts, 'zh').endsWith('（可选：default、night）'), '可选项按语言的列表分隔')
  const report = { t: 'lines', items: [{ code: 'verify.report.lint', params: {} },
    { code: 'verify.report.tool_error', params: { text: { code: 'verify.lint.location_ref', params: { shot: 'E01-SH001', location: 'S99' } } } },
    { code: 'verify.report.tool_error', params: { text: { t: 'vendor', text: '[E01] 认不出的一条' } } }] }
  const failedLint = { code: 'job.failed_report', params: { reason: { code: 'job.batch_failed', params: { batch: 1, retries: 2 } }, report } }
  must(formatMsg(failedLint, 'en').endsWith(`${en.srv.verify.report.lint}\n  [E01-SH001] location_ref refers to a location that doesn’t exist: S99\n  [E01] 认不出的一条`),
    '失败报告里的 lint 逐条（英文），认不出的一条原文显示：' + formatMsg(failedLint, 'en'))
  must(formatMsg(failedLint, 'zh').endsWith('分镜检查发现的错误：\n  [E01-SH001] location_ref 引用了不存在的场景：S99\n  [E01] 认不出的一条'), formatMsg(failedLint, 'zh'))
  const old = { code: 'verify.report.tool_error', params: { text: { t: 'vendor', text: '[E01-SH001] location_ref 引用不存在的场景: L09' } } }
  must(formatMsg(old, 'en') === '  [E01-SH001] location_ref 引用不存在的场景: L09', '旧报告（子计划 5 的 tool_error 原文）照旧原样显示')
  console.log('子计划 5b：lint 逐条中英渲染、旧报告兼容 ✓')
}

console.log('\nALL PASS')
