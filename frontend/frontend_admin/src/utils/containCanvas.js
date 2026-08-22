/** object-fit: contain 下，计算 img 元素内实际显示的内容区域（相对 img 左上角）。 */
export function getContainLayout(img) {
  const nw = img?.naturalWidth || 0
  const nh = img?.naturalHeight || 0
  if (!nw || !nh) return null
  const cw = img.clientWidth
  const ch = img.clientHeight
  if (!cw || !ch) return null
  const scale = Math.min(cw / nw, ch / nh)
  const displayW = nw * scale
  const displayH = nh * scale
  const offsetX = (cw - displayW) / 2
  const offsetY = (ch - displayH) / 2
  return { nw, nh, scale, displayW, displayH, offsetX, offsetY }
}

/** 将 canvas 内部分辨率设为原图像素，CSS 尺寸/位置对齐 contain 后的可见区域。 */
export function syncContainCanvas(img, canvas) {
  const layout = getContainLayout(img)
  if (!layout) return null
  const { nw, nh, displayW, displayH, offsetX, offsetY } = layout
  canvas.width = nw
  canvas.height = nh
  canvas.style.left = `${img.offsetLeft + offsetX}px`
  canvas.style.top = `${img.offsetTop + offsetY}px`
  canvas.style.width = `${displayW}px`
  canvas.style.height = `${displayH}px`
  return layout
}

/** canvas 内 click offset → 原图像素坐标 */
export function canvasOffsetToImageXY(canvas, offsetX, offsetY) {
  const scale = canvas.width / canvas.clientWidth
  return [offsetX * scale, offsetY * scale]
}
