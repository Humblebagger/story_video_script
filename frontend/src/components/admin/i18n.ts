/** 把运营后台的文案挂进语言包。这个文件只有副作用：后台外框（AdminView）第一行就引入它，
 *  所以文案跟着后台那一块代码一起加载，主包里没有。单独渲染后台某一页的测试要自己先引入它。 */
import { registerAdminMessages } from '@/i18n/core'
import { enAdmin } from './messages.en'
import { zhAdmin } from './messages.zh'

registerAdminMessages(zhAdmin, enAdmin)
