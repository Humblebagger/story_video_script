/** 制作参数的预设选项。
 *
 *  这些字段在 schema 里是自由文本（不是枚举）——它们直接进 prompt 的【制作参数】，
 *  由 LLM 理解，不参与机器校验。所以预设只是省去手打，选择框一律允许「自定义」兜底，
 *  不能把用户锁死在列表里。
 */

import { tr } from './i18n/core'
import type { MsgKey } from './i18n/core'

export interface Preset {
  value: string
  /** 显示名：getter，按当前语言取值。value 是写进分镜、发给模型的内容，不翻译 */
  readonly label: string
}

const P = (value: string, key: MsgKey): Preset => ({ value, get label() { return tr(key) } })

/** 风格分类：与 style_prefix 配合，前者定画风门类，后者写具体画面调性 */
export const ART_STYLES: Preset[] = [
  P('realistic', 'presets.artStyle.realistic'),
  P('cinematic', 'presets.artStyle.cinematic'),
  P('anime', 'presets.artStyle.anime'),
  P('ink_wash', 'presets.artStyle.ink_wash'),
  P('chinese_comic', 'presets.artStyle.chinese_comic'),
  P('oil_painting', 'presets.artStyle.oil_painting'),
  P('watercolor', 'presets.artStyle.watercolor'),
  P('3d_render', 'presets.artStyle.render3d'),
  P('pixel_art', 'presets.artStyle.pixel_art'),
]

export const COLOR_TONES: Preset[] = [
  P('自然色调', 'presets.tone.natural'),
  P('青灰冷色调，晨昏低饱和', 'presets.tone.cool'),
  P('暖黄怀旧色调，颗粒感', 'presets.tone.warm'),
  P('高饱和明快色调', 'presets.tone.vivid'),
  P('低饱和灰调，阴郁压抑', 'presets.tone.gloomy'),
  P('冷蓝夜色调，霓虹点缀', 'presets.tone.nightBlue'),
  P('金红暖调，逆光通透', 'presets.tone.goldenBack'),
  P('黑白单色，高反差', 'presets.tone.mono'),
]

export const TARGET_PLATFORMS: Preset[] = [
  P('抖音', 'presets.platform.douyin'),
  P('快手', 'presets.platform.kuaishou'),
  P('视频号', 'presets.platform.wechat'),
  P('小红书', 'presets.platform.xiaohongshu'),
  P('B站', 'presets.platform.bilibili'),
  P('YouTube Shorts', 'presets.platform.shorts'),
  P('通用', 'presets.platform.general'),
]

export const TTS_VOICES: Preset[] = [
  P('male_mature', 'presets.voice.male_mature'),
  P('male_young', 'presets.voice.male_young'),
  P('female_mature', 'presets.voice.female_mature'),
  P('female_young', 'presets.voice.female_young'),
  P('neutral', 'presets.voice.neutral'),
]

/** 画面风格前缀的常用写法，点了填进输入框，仍可继续改 */
export const STYLE_PREFIXES: Preset[] = [
  P('电影感写实风格，自然光影', 'presets.style.cinematic'),
  P('民国江南小镇写实风格，电影感光影，青灰冷色调', 'presets.style.republic'),
  P('古装武侠写实风格，水墨意境，山野晨雾', 'presets.style.wuxia'),
  P('现代都市写实风格，浅景深，玻璃与霓虹反射', 'presets.style.urban'),
  P('东方玄幻风格，飞檐仙山，云海流光', 'presets.style.xuanhuan'),
  P('日系青春动画风格，通透高光，柔和暖色', 'presets.style.anime'),
]
