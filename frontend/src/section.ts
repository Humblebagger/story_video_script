/** 小说层的九个分区：左栏项目导航切换，主区按它渲染。 */
export const SECTIONS = [
  'overview', 'chapters', 'characters', 'locations', 'props', 'creatures', 'memory', 'constraints', 'settings',
] as const
export type Section = (typeof SECTIONS)[number]
