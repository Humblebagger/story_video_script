/** 制作参数的预设选项。
 *
 *  这些字段在 schema 里是自由文本（不是枚举）——它们直接进 prompt 的【制作参数】，
 *  由 LLM 理解，不参与机器校验。所以预设只是省去手打，选择框一律允许「自定义」兜底，
 *  不能把用户锁死在列表里。
 */

export interface Preset {
  value: string
  label: string
}

/** 风格分类：与 style_prefix 配合，前者定画风门类，后者写具体画面调性 */
export const ART_STYLES: Preset[] = [
  { value: 'realistic', label: '写实 realistic' },
  { value: 'cinematic', label: '电影感 cinematic' },
  { value: 'anime', label: '日系动画 anime' },
  { value: 'ink_wash', label: '水墨 ink_wash' },
  { value: 'chinese_comic', label: '国漫 chinese_comic' },
  { value: 'oil_painting', label: '油画 oil_painting' },
  { value: 'watercolor', label: '水彩 watercolor' },
  { value: '3d_render', label: '三维渲染 3d_render' },
  { value: 'pixel_art', label: '像素 pixel_art' },
]

export const COLOR_TONES: Preset[] = [
  { value: '自然色调', label: '自然色调' },
  { value: '青灰冷色调，晨昏低饱和', label: '青灰冷调（民国/沉郁）' },
  { value: '暖黄怀旧色调，颗粒感', label: '暖黄怀旧' },
  { value: '高饱和明快色调', label: '高饱和明快' },
  { value: '低饱和灰调，阴郁压抑', label: '低饱和阴郁' },
  { value: '冷蓝夜色调，霓虹点缀', label: '冷蓝夜景' },
  { value: '金红暖调，逆光通透', label: '金红逆光' },
  { value: '黑白单色，高反差', label: '黑白高反差' },
]

export const TARGET_PLATFORMS: Preset[] = [
  { value: '抖音', label: '抖音' },
  { value: '快手', label: '快手' },
  { value: '视频号', label: '微信视频号' },
  { value: '小红书', label: '小红书' },
  { value: 'B站', label: 'B 站' },
  { value: 'YouTube Shorts', label: 'YouTube Shorts' },
  { value: '通用', label: '通用（不针对平台）' },
]

export const TTS_VOICES: Preset[] = [
  { value: 'male_mature', label: '男声·沉稳' },
  { value: 'male_young', label: '男声·青年' },
  { value: 'female_mature', label: '女声·沉稳' },
  { value: 'female_young', label: '女声·青年' },
  { value: 'neutral', label: '中性' },
]

/** 画面风格前缀的常用写法，点了填进输入框，仍可继续改 */
export const STYLE_PREFIXES: Preset[] = [
  { value: '电影感写实风格，自然光影', label: '电影感写实' },
  { value: '民国江南小镇写实风格，电影感光影，青灰冷色调', label: '民国江南' },
  { value: '古装武侠写实风格，水墨意境，山野晨雾', label: '古装武侠' },
  { value: '现代都市写实风格，浅景深，玻璃与霓虹反射', label: '现代都市' },
  { value: '东方玄幻风格，飞檐仙山，云海流光', label: '东方玄幻' },
  { value: '日系青春动画风格，通透高光，柔和暖色', label: '日系青春' },
]
