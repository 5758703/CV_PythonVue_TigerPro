import { Position } from '@vue-flow/core'

export const SNAP_OFFSET = 0.5
export const SNAP_THRESHOLD = 0.07

const SIDE_POSITION = {
  left: Position.Left,
  right: Position.Right,
  top: Position.Top,
  bottom: Position.Bottom,
}

export function defaultHandlesForMeta(meta = {}) {
  const hasIn = Array.isArray(meta.portsIn) ? meta.portsIn.length > 0 : true
  const hasOut = Array.isArray(meta.portsOut) ? meta.portsOut.length > 0 : true
  const handles = {}
  if (hasIn) handles.target = { side: 'left', offset: SNAP_OFFSET }
  if (hasOut) handles.source = { side: 'right', offset: SNAP_OFFSET }
  return handles
}

export function normalizeHandle(handle, fallback = { side: 'left', offset: SNAP_OFFSET }) {
  const side = ['left', 'right', 'top', 'bottom'].includes(handle?.side) ? handle.side : fallback.side
  const offset = clamp01(Number(handle?.offset ?? fallback.offset))
  return { side, offset: snapOffset(offset) }
}

export function snapOffset(offset) {
  const o = clamp01(offset)
  if (Math.abs(o - SNAP_OFFSET) <= SNAP_THRESHOLD) return SNAP_OFFSET
  return o
}

export function clamp01(v) {
  if (!Number.isFinite(v)) return SNAP_OFFSET
  return Math.min(1, Math.max(0, v))
}

export function handleToFlow(handle) {
  const { side, offset } = normalizeHandle(handle)
  const pct = `${Math.round(offset * 1000) / 10}%`
  const position = SIDE_POSITION[side]
  const style =
    side === 'left' || side === 'right'
      ? { top: pct, transform: 'translateY(-50%)' }
      : { left: pct, transform: 'translateX(-50%)' }
  return { position, style, side, offset }
}

export function projectPointToPerimeter(relX, relY) {
  const x = clamp01(relX)
  const y = clamp01(relY)
  const dTop = y
  const dBottom = 1 - y
  const dLeft = x
  const dRight = 1 - x
  const min = Math.min(dTop, dBottom, dLeft, dRight)

  if (min === dTop) return { side: 'top', offset: snapOffset(x) }
  if (min === dBottom) return { side: 'bottom', offset: snapOffset(x) }
  if (min === dLeft) return { side: 'left', offset: snapOffset(y) }
  return { side: 'right', offset: snapOffset(y) }
}

export function perimeterFromClient(nodeEl, clientX, clientY) {
  if (!nodeEl) return { side: 'left', offset: SNAP_OFFSET }
  const rect = nodeEl.getBoundingClientRect()
  if (rect.width <= 0 || rect.height <= 0) return { side: 'left', offset: SNAP_OFFSET }
  const relX = (clientX - rect.left) / rect.width
  const relY = (clientY - rect.top) / rect.height
  return projectPointToPerimeter(relX, relY)
}

export function snapGuideStyle(side) {
  if (side === 'top' || side === 'bottom') {
    return { left: '50%', top: side === 'top' ? '0' : '100%', transform: 'translate(-50%, -50%)' }
  }
  return { top: '50%', left: side === 'left' ? '0' : '100%', transform: 'translate(-50%, -50%)' }
}

/** 返回点击处在路径上的归一化位置 t∈[0,1]，0 靠近起点、1 靠近终点 */
export function pathHitParameter(pathD, x, y) {
  if (typeof document === 'undefined' || !pathD) return 0
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
  const path = document.createElementNS('http://www.w3.org/2000/svg', 'path')
  path.setAttribute('d', pathD)
  svg.appendChild(path)

  const total = path.getTotalLength()
  if (total <= 0) return 0

  let bestDist = Infinity
  let bestT = 0
  const steps = 96
  for (let i = 0; i <= steps; i += 1) {
    const t = i / steps
    const pt = path.getPointAtLength(t * total)
    const dist = Math.hypot(pt.x - x, pt.y - y)
    if (dist < bestDist) {
      bestDist = dist
      bestT = t
    }
  }
  return bestT
}

export function slideHandleOnAxis(currentHandle, nodeEl, clientX, clientY, axis) {
  if (!nodeEl) return normalizeHandle(currentHandle)
  const rect = nodeEl.getBoundingClientRect()
  if (rect.width <= 0 || rect.height <= 0) return normalizeHandle(currentHandle)
  const h = normalizeHandle(currentHandle)
  const relX = clamp01((clientX - rect.left) / rect.width)
  const relY = clamp01((clientY - rect.top) / rect.height)

  if (axis === 'horizontal') {
    if (h.side === 'top' || h.side === 'bottom') {
      return { side: h.side, offset: snapOffset(relX) }
    }
    return { side: h.side, offset: snapOffset(relY) }
  }
  if (h.side === 'left' || h.side === 'right') {
    return { side: h.side, offset: snapOffset(relY) }
  }
  return { side: h.side, offset: snapOffset(relX) }
}

function distPointToSegment(px, py, x1, y1, x2, y2) {
  const dx = x2 - x1
  const dy = y2 - y1
  const len2 = dx * dx + dy * dy
  if (len2 === 0) return Math.hypot(px - x1, py - y1)
  let t = ((px - x1) * dx + (py - y1) * dy) / len2
  t = Math.min(1, Math.max(0, t))
  const nx = x1 + t * dx
  const ny = y1 + t * dy
  return Math.hypot(px - nx, py - ny)
}

export function pathSegments(pathD) {
  if (typeof document === 'undefined' || !pathD) return []
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
  const path = document.createElementNS('http://www.w3.org/2000/svg', 'path')
  path.setAttribute('d', pathD)
  svg.appendChild(path)
  const total = path.getTotalLength()
  if (total <= 0) return []

  const samples = 48
  const pts = []
  for (let i = 0; i <= samples; i += 1) {
    pts.push(path.getPointAtLength((i / samples) * total))
  }

  const segments = []
  for (let i = 1; i < pts.length; i += 1) {
    const a = pts[i - 1]
    const b = pts[i]
    const dx = b.x - a.x
    const dy = b.y - a.y
    if (Math.hypot(dx, dy) < 0.5) continue
    segments.push({
      x1: a.x,
      y1: a.y,
      x2: b.x,
      y2: b.y,
      horizontal: Math.abs(dx) >= Math.abs(dy),
    })
  }
  return segments
}

export function findPathSegmentHit(pathD, x, y, sourceX = 0, sourceY = 0, targetX = 0, targetY = 0) {
  const segments = pathSegments(pathD)
  if (!segments.length) {
    return { index: 0, total: 0, horizontal: true, isSource: true, isTarget: false, isMiddle: false }
  }
  let bestIdx = 0
  let bestDist = Infinity
  segments.forEach((seg, i) => {
    const d = distPointToSegment(x, y, seg.x1, seg.y1, seg.x2, seg.y2)
    if (d < bestDist) {
      bestDist = d
      bestIdx = i
    }
  })
  const seg = segments[bestIdx]
  const midX = (seg.x1 + seg.x2) / 2
  const midY = (seg.y1 + seg.y2) / 2
  const distSource = Math.hypot(midX - sourceX, midY - sourceY)
  const distTarget = Math.hypot(midX - targetX, midY - targetY)
  const span = Math.hypot(targetX - sourceX, targetY - sourceY) || 1
  const zone = Math.max(56, span * 0.3)
  const isMiddle = distSource > zone && distTarget > zone
  const isSource = !isMiddle && distSource <= distTarget
  const isTarget = !isMiddle && !isSource
  return {
    index: bestIdx,
    total: segments.length,
    horizontal: seg.horizontal,
    isSource,
    isTarget,
    isMiddle,
    segment: seg,
  }
}

export function clientToSvgPoint(event) {
  const svg = event.currentTarget?.ownerSVGElement || event.target?.ownerSVGElement
  if (!svg) return { x: event.clientX, y: event.clientY }
  const pt = svg.createSVGPoint()
  pt.x = event.clientX
  pt.y = event.clientY
  const ctm = svg.getScreenCTM()
  if (!ctm) return { x: event.clientX, y: event.clientY }
  const local = pt.matrixTransform(ctm.inverse())
  return { x: local.x, y: local.y }
}

const EST_NODE_W = 164
const EST_NODE_H = 90

function nodeCenter(node) {
  const w = Number(node?.dimensions?.width) || EST_NODE_W
  const h = Number(node?.dimensions?.height) || EST_NODE_H
  return {
    x: (node?.position?.x || 0) + w / 2,
    y: (node?.position?.y || 0) + h / 2,
  }
}

/**
 * 按相对位置选择连接边，匹配阶梯布局红线示意：
 * - 目标在右下且偏竖：源下边 → 目标左边
 * - 目标在右下且偏横：源右边 → 目标上边
 */
export function routeHandlesForPair(sourceNode, targetNode) {
  const s = nodeCenter(sourceNode)
  const t = nodeCenter(targetNode)
  const dx = t.x - s.x
  const dy = t.y - s.y
  const ax = Math.abs(dx)
  const ay = Math.abs(dy)

  // 近似水平
  if (ay < 48) {
    return {
      source: { side: dx >= 0 ? 'right' : 'left', offset: SNAP_OFFSET },
      target: { side: dx >= 0 ? 'left' : 'right', offset: SNAP_OFFSET },
    }
  }
  // 近似竖直
  if (ax < 48) {
    return {
      source: { side: dy >= 0 ? 'bottom' : 'top', offset: SNAP_OFFSET },
      target: { side: dy >= 0 ? 'top' : 'bottom', offset: SNAP_OFFSET },
    }
  }

  // 右下（截图红线）
  if (dx > 0 && dy > 0) {
    if (ay >= ax) {
      return {
        source: { side: 'bottom', offset: SNAP_OFFSET },
        target: { side: 'left', offset: SNAP_OFFSET },
      }
    }
    return {
      source: { side: 'right', offset: SNAP_OFFSET },
      target: { side: 'top', offset: SNAP_OFFSET },
    }
  }
  // 左下
  if (dx < 0 && dy > 0) {
    if (ay >= ax) {
      return {
        source: { side: 'bottom', offset: SNAP_OFFSET },
        target: { side: 'right', offset: SNAP_OFFSET },
      }
    }
    return {
      source: { side: 'left', offset: SNAP_OFFSET },
      target: { side: 'top', offset: SNAP_OFFSET },
    }
  }
  // 右上
  if (dx > 0 && dy < 0) {
    if (ay >= ax) {
      return {
        source: { side: 'top', offset: SNAP_OFFSET },
        target: { side: 'left', offset: SNAP_OFFSET },
      }
    }
    return {
      source: { side: 'right', offset: SNAP_OFFSET },
      target: { side: 'bottom', offset: SNAP_OFFSET },
    }
  }
  // 左上
  if (ay >= ax) {
    return {
      source: { side: 'top', offset: SNAP_OFFSET },
      target: { side: 'right', offset: SNAP_OFFSET },
    }
  }
  return {
    source: { side: 'left', offset: SNAP_OFFSET },
    target: { side: 'bottom', offset: SNAP_OFFSET },
  }
}

export function applyAutoRouteHandles(nodeList, edgeList) {
  const byId = new Map((nodeList || []).map((n) => [n.id, n]))
  const outVotes = new Map()
  const inVotes = new Map()

  for (const e of edgeList || []) {
    const src = byId.get(e.source)
    const tgt = byId.get(e.target)
    if (!src || !tgt) continue
    const routed = routeHandlesForPair(src, tgt)
    if (!outVotes.has(e.source)) outVotes.set(e.source, {})
    if (!inVotes.has(e.target)) inVotes.set(e.target, {})
    outVotes.get(e.source)[routed.source.side] = (outVotes.get(e.source)[routed.source.side] || 0) + 1
    inVotes.get(e.target)[routed.target.side] = (inVotes.get(e.target)[routed.target.side] || 0) + 1
  }

  const pick = (votes) =>
    Object.entries(votes || {}).sort((a, b) => b[1] - a[1])[0]?.[0]

  return (nodeList || []).map((n) => {
    const outSide = pick(outVotes.get(n.id))
    const inSide = pick(inVotes.get(n.id))
    if (!outSide && !inSide) return n
    const handles = { ...(n.data?.handles || {}) }
    if (outSide && handles.source?.auto !== false) {
      handles.source = { side: outSide, offset: SNAP_OFFSET, auto: true }
    }
    if (inSide && handles.target?.auto !== false) {
      handles.target = { side: inSide, offset: SNAP_OFFSET, auto: true }
    }
    return { ...n, data: { ...n.data, handles } }
  })
}

function posKey(p) {
  const s = String(p || '').toLowerCase()
  if (s === 'left' || s === 'right' || s === 'top' || s === 'bottom') return s
  return 'right'
}

function isVerticalSide(side) {
  return side === 'top' || side === 'bottom'
}

/**
 * 正交折线：同轴直连；对角尽量单拐点 L；同向进出用双拐点 Z。
 * 返回 [pathD, labelX, labelY]
 */
export function buildElbowPath({
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  bend = {},
}) {
  const sp = posKey(sourcePosition)
  const tp = posKey(targetPosition)
  const dx = targetX - sourceX
  const dy = targetY - sourceY
  const srcV = isVerticalSide(sp)
  const tgtV = isVerticalSide(tp)

  // 近似共线 → 直连
  if (Math.abs(dy) < 1.5 && !srcV && !tgtV) {
    return [`M ${sourceX},${sourceY} L ${targetX},${targetY}`, (sourceX + targetX) / 2, sourceY]
  }
  if (Math.abs(dx) < 1.5 && srcV && tgtV) {
    return [`M ${sourceX},${sourceY} L ${targetX},${targetY}`, sourceX, (sourceY + targetY) / 2]
  }

  // 单拐点 L：垂出横入 / 横出垂入（两端均与边框垂直）
  if (srcV !== tgtV) {
    if (srcV) {
      // 先竖后横：拐点 (sourceX, targetY)
      let cx = sourceX
      let cy = targetY
      if (Number.isFinite(bend.centerY)) cy = bend.centerY
      if (Number.isFinite(bend.centerX) && !Number.isFinite(bend.centerY)) {
        // 用户水平拖中段 → 改为先横后竖
        cx = bend.centerX
        cy = sourceY
      }
      return [
        `M ${sourceX},${sourceY} L ${cx},${cy} L ${targetX},${targetY}`,
        (sourceX + targetX) / 2,
        (sourceY + targetY) / 2,
      ]
    }
    // 先横后竖：拐点 (targetX, sourceY)
    let cx = targetX
    let cy = sourceY
    if (Number.isFinite(bend.centerX)) cx = bend.centerX
    if (Number.isFinite(bend.centerY) && !Number.isFinite(bend.centerX)) {
      cx = sourceX
      cy = bend.centerY
    }
    return [
      `M ${sourceX},${sourceY} L ${cx},${cy} L ${targetX},${targetY}`,
      (sourceX + targetX) / 2,
      (sourceY + targetY) / 2,
    ]
  }

  // 左右同向：中间竖直折段（两拐点）
  if (!srcV && !tgtV) {
    if (Math.abs(dy) < 8) {
      return [`M ${sourceX},${sourceY} L ${targetX},${targetY}`, (sourceX + targetX) / 2, sourceY]
    }
    const midX = Number.isFinite(bend.centerX) ? bend.centerX : (sourceX + targetX) / 2
    return [
      `M ${sourceX},${sourceY} L ${midX},${sourceY} L ${midX},${targetY} L ${targetX},${targetY}`,
      midX,
      (sourceY + targetY) / 2,
    ]
  }

  // 上下同向
  if (Math.abs(dx) < 8) {
    return [`M ${sourceX},${sourceY} L ${targetX},${targetY}`, sourceX, (sourceY + targetY) / 2]
  }
  const midY = Number.isFinite(bend.centerY) ? bend.centerY : (sourceY + targetY) / 2
  return [
    `M ${sourceX},${sourceY} L ${sourceX},${midY} L ${targetX},${midY} L ${targetX},${targetY}`,
    (sourceX + targetX) / 2,
    midY,
  ]
}


