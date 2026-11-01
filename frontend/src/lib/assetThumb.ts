/** 资产卡的缩略图：参考图里第一个浏览器能直接显示的地址（http(s)、data:、站内绝对路径）；没有为 null */
export function assetThumb(card: { reference_images?: { uri?: string }[] }): string | null {
  return card.reference_images?.find((r) => r.uri && /^(https?:|data:|\/)/.test(r.uri))?.uri ?? null
}
