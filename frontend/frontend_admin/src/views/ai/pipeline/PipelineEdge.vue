<script setup>
import { computed, inject, ref } from 'vue'
import { BaseEdge, useVueFlow } from '@vue-flow/core'
import {
  buildElbowPath,
  clientToSvgPoint,
  findPathSegmentHit,
  perimeterFromClient,
} from './handleGeometry'

const props = defineProps({
  id: { type: String, required: true },
  source: { type: String, required: true },
  target: { type: String, required: true },
  sourceX: { type: Number, required: true },
  sourceY: { type: Number, required: true },
  targetX: { type: Number, required: true },
  targetY: { type: Number, required: true },
  sourcePosition: { type: String, required: true },
  targetPosition: { type: String, required: true },
  sourceHandleId: { type: String, default: 'source' },
  targetHandleId: { type: String, default: 'target' },
  selected: { type: Boolean, default: false },
  animated: { type: Boolean, default: true },
  markerEnd: { type: String, default: undefined },
  style: { type: Object, default: () => ({}) },
  data: { type: Object, default: () => ({}) },
  interactionWidth: { type: Number, default: 24 },
})

const { screenToFlowCoordinate } = useVueFlow({ id: 'eva-pipeline' })
const patchNodeHandle = inject('patchNodeHandle', null)
const patchEdgeBend = inject('patchEdgeBend', null)

const dragMode = ref('')

const bend = computed(() => props.data?.bend || {})

const path = computed(() =>
  buildElbowPath({
    sourceX: props.sourceX,
    sourceY: props.sourceY,
    sourcePosition: props.sourcePosition,
    targetX: props.targetX,
    targetY: props.targetY,
    targetPosition: props.targetPosition,
    bend: bend.value,
  }),
)

const edgeStyle = computed(() => ({
  ...props.style,
  strokeDasharray: props.animated === false ? undefined : '8 6',
}))

const corner = computed(() => {
  // 取路径第一个拐点（L 形只有一个；Z 形取第一折）
  const d = String(path.value[0] || '')
  const parts = d.match(/[ML]\s*(-?\d+(?:\.\d+)?)\s*,?\s*(-?\d+(?:\.\d+)?)/gi)
  if (!parts || parts.length < 2) return null
  const parse = (seg) => {
    const m = seg.match(/(-?\d+(?:\.\d+)?)\s*,?\s*(-?\d+(?:\.\d+)?)/)
    return m ? { x: Number(m[1]), y: Number(m[2]) } : null
  }
  const p0 = parse(parts[0])
  const p1 = parse(parts[1])
  if (!p0 || !p1) return null
  // 若第二段与第三段存在，优先中间控制点（Z 的竖/横中段中点）
  if (parts.length >= 3) {
    const p2 = parse(parts[2])
    if (p2 && (Math.abs(p1.x - p2.x) < 0.5 || Math.abs(p1.y - p2.y) < 0.5)) {
      return { x: (p1.x + p2.x) / 2, y: (p1.y + p2.y) / 2 }
    }
  }
  return p1
})

function nodeEl(nodeId) {
  return document.querySelector(`.vue-flow__node[data-id="${nodeId}"]`)
}

function applyFreeHandle(nodeId, role, clientX, clientY) {
  const el = nodeEl(nodeId)
  if (!el || typeof patchNodeHandle !== 'function') return
  const next = perimeterFromClient(el, clientX, clientY)
  patchNodeHandle(nodeId, role, next)
}

function applyBendFree(clientX, clientY, axisHint) {
  if (typeof patchEdgeBend !== 'function') return
  const flow = screenToFlowCoordinate({ x: clientX, y: clientY })
  if (axisHint === 'horizontal') {
    patchEdgeBend(props.id, { centerX: flow.x, centerY: undefined })
  } else if (axisHint === 'vertical') {
    patchEdgeBend(props.id, { centerX: undefined, centerY: flow.y })
  } else {
    patchEdgeBend(props.id, { centerX: flow.x, centerY: flow.y })
  }
}

function startDrag(event, mode) {
  event.stopPropagation()
  event.preventDefault()
  dragMode.value = mode

  const onMove = (ev) => {
    ev.preventDefault()
    ev.stopPropagation()
    if (mode === 'source') {
      applyFreeHandle(props.source, props.sourceHandleId || 'source', ev.clientX, ev.clientY)
      return
    }
    if (mode === 'target') {
      applyFreeHandle(props.target, props.targetHandleId || 'target', ev.clientX, ev.clientY)
      return
    }
    if (mode === 'middle-h') {
      applyBendFree(ev.clientX, ev.clientY, 'horizontal')
      return
    }
    if (mode === 'middle-v') {
      applyBendFree(ev.clientX, ev.clientY, 'vertical')
      return
    }
    applyBendFree(ev.clientX, ev.clientY, null)
  }

  const onUp = () => {
    dragMode.value = ''
    window.removeEventListener('pointermove', onMove)
    window.removeEventListener('pointerup', onUp)
    window.removeEventListener('pointercancel', onUp)
    document.body.classList.remove('eva-edge-dragging')
  }

  document.body.classList.add('eva-edge-dragging')
  window.addEventListener('pointermove', onMove, { passive: false })
  window.addEventListener('pointerup', onUp)
  window.addEventListener('pointercancel', onUp)
}

function onPathDown(event) {
  const pt = clientToSvgPoint(event)
  const hit = findPathSegmentHit(
    path.value[0],
    pt.x,
    pt.y,
    props.sourceX,
    props.sourceY,
    props.targetX,
    props.targetY,
  )
  if (hit.isSource) {
    startDrag(event, 'source')
    return
  }
  if (hit.isTarget) {
    startDrag(event, 'target')
    return
  }
  startDrag(event, hit.horizontal ? 'middle-h' : 'middle-v')
}

function onJointDown(event, end) {
  startDrag(event, end)
}

function onCornerDown(event) {
  startDrag(event, 'middle')
}
</script>

<template>
  <g class="eva-edge-root nopan nodrag" :class="{ dragging: !!dragMode, selected, animated }">
    <BaseEdge
      :id="id"
      :path="path[0]"
      :marker-end="markerEnd"
      :style="edgeStyle"
      :interaction-width="interactionWidth"
      class="eva-edge-path"
    />
    <path
      :d="path[0]"
      class="eva-edge-hit"
      fill="none"
      :stroke-width="interactionWidth"
      @pointerdown="onPathDown"
    />
    <circle
      v-if="corner"
      class="eva-edge-corner nopan nodrag"
      :class="{ active: !!dragMode && dragMode.startsWith('middle') }"
      :cx="corner.x"
      :cy="corner.y"
      r="4"
      @pointerdown="onCornerDown"
    />
    <circle
      class="eva-edge-joint-hit nopan nodrag"
      :cx="sourceX"
      :cy="sourceY"
      r="12"
      @pointerdown="onJointDown($event, 'source')"
    />
    <circle
      class="eva-edge-joint nopan nodrag"
      :class="{ active: selected || dragMode === 'source' }"
      :cx="sourceX"
      :cy="sourceY"
      r="4"
      @pointerdown="onJointDown($event, 'source')"
    />
    <circle
      class="eva-edge-joint-hit nopan nodrag"
      :cx="targetX"
      :cy="targetY"
      r="12"
      @pointerdown="onJointDown($event, 'target')"
    />
    <circle
      class="eva-edge-joint nopan nodrag"
      :class="{ active: selected || dragMode === 'target' }"
      :cx="targetX"
      :cy="targetY"
      r="4"
      @pointerdown="onJointDown($event, 'target')"
    />
  </g>
</template>

<style scoped>
.eva-edge-root {
  pointer-events: all;
  touch-action: none;
}
.eva-edge-path :deep(.vue-flow__edge-path) {
  stroke-linecap: round;
  stroke-linejoin: miter;
}
.eva-edge-root.animated :deep(.vue-flow__edge-path) {
  animation: eva-edge-flow 0.55s linear infinite;
}
.eva-edge-root.dragging :deep(.vue-flow__edge-path) {
  stroke: #2f6fed;
}
.eva-edge-hit {
  stroke: rgba(64, 158, 255, 0.01);
  pointer-events: stroke;
  cursor: move;
}
.eva-edge-joint-hit {
  fill: transparent;
  stroke: none;
  cursor: move;
  pointer-events: all;
}
.eva-edge-joint,
.eva-edge-corner {
  fill: #409eff;
  stroke: #fff;
  stroke-width: 2px;
  cursor: move;
  pointer-events: all;
}
.eva-edge-corner {
  fill: #66b1ff;
  opacity: 0.85;
}
.eva-edge-joint:hover,
.eva-edge-joint.active,
.eva-edge-corner.active,
.eva-edge-root.selected .eva-edge-joint {
  fill: #2f6fed;
}
@keyframes eva-edge-flow {
  to {
    stroke-dashoffset: -14;
  }
}
</style>

<style>
body.eva-edge-dragging {
  cursor: move !important;
}
body.eva-edge-dragging .eva-edge-hit,
body.eva-edge-dragging .eva-edge-joint,
body.eva-edge-dragging .eva-edge-joint-hit,
body.eva-edge-dragging .eva-edge-corner {
  cursor: move !important;
}
</style>
