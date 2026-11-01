/** 风格卡片的色块（代码画，不用图片）与选中时带出的默认风格前缀。
 *  前缀是中文、会发给模型，按预设惯例用 P() 写（取值不译，显示名走语言包）。 */
import type { Preset } from './presets'
import { tr } from './i18n/core'
import type { MsgKey } from './i18n/core'

const P = (value: string, key: MsgKey): Preset => ({ value, get label() { return tr(key) } })

export interface StyleLook { id: string; swatch: string; prefix: Preset }

export const STYLE_LOOKS: StyleLook[] = [
  { id: 'realistic', swatch: 'linear-gradient(135deg, oklch(0.62 0.03 60), oklch(0.38 0.03 50))',
    prefix: P('电影感写实风格，自然光影', 'presets.style.cinematic') },
  { id: 'cinematic', swatch: 'linear-gradient(135deg, oklch(0.55 0.1 220), oklch(0.7 0.14 60))',
    prefix: P('电影级调色，青橙对比，浅景深，宽银幕构图', 'presets.lookPrefix.cinematic') },
  { id: 'anime', swatch: 'linear-gradient(135deg, oklch(0.8 0.12 350), oklch(0.75 0.12 240))',
    prefix: P('日系动画风格，干净线条，通透高光，柔和配色', 'presets.lookPrefix.anime') },
  { id: 'ink_wash', swatch: 'radial-gradient(circle at 30% 30%, oklch(0.95 0.01 90), oklch(0.35 0 0))',
    prefix: P('中国水墨风格，留白，墨色浓淡渐变，宣纸质感', 'presets.lookPrefix.ink_wash') },
  { id: 'chinese_comic', swatch: 'linear-gradient(135deg, oklch(0.55 0.2 28), oklch(0.78 0.14 85))',
    prefix: P('国漫风格，厚涂上色，朱红与金色点缀，古风服饰细节', 'presets.lookPrefix.chinese_comic') },
  { id: 'oil_painting', swatch: 'linear-gradient(135deg, oklch(0.6 0.13 50), oklch(0.42 0.1 20))',
    prefix: P('古典油画风格，厚涂笔触，暖色光影', 'presets.lookPrefix.oil_painting') },
  { id: 'watercolor', swatch: 'linear-gradient(135deg, oklch(0.88 0.06 200), oklch(0.86 0.07 330))',
    prefix: P('水彩风格，淡彩晕染，纸张纹理，柔和边缘', 'presets.lookPrefix.watercolor') },
  { id: '3d_render', swatch: 'linear-gradient(135deg, oklch(0.75 0.12 280), oklch(0.6 0.15 200))',
    prefix: P('三维渲染风格，柔和全局光照，细腻材质', 'presets.lookPrefix.render3d') },
  { id: 'pixel_art', swatch: 'repeating-conic-gradient(oklch(0.7 0.15 150) 0 25%, oklch(0.55 0.15 260) 0 50%) 0 0 / 16px 16px',
    prefix: P('像素风格，低分辨率方块，复古游戏配色', 'presets.lookPrefix.pixel_art') },
]

export const lookOf = (artStyle: string) => STYLE_LOOKS.find((s) => s.id === artStyle)
/** 用户手改过前缀吗：空白不算；不是任何一种风格的默认前缀，就算手改过 */
export const prefixTouched = (prefix: string) => prefix.trim() !== '' && !STYLE_LOOKS.some((s) => s.prefix.value === prefix)
/** 按 id 稳定地挑一套色块（最近小说的封面用） */
export const swatchFor = (id: string) =>
  STYLE_LOOKS[[...id].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7) % STYLE_LOOKS.length].swatch
