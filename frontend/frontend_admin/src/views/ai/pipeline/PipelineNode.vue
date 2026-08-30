<script setup>
import { computed } from 'vue'
import { Handle, useNodeId, useVueFlow } from '@vue-flow/core'
import {
  VideoCamera,
  Aim,
  Connection,
  Bell,
  View,
  Link,
  ChatDotRound,
  Coin,
  Monitor,
  Cpu,
} from '@element-plus/icons-vue'
import {
  defaultHandlesForMeta,
  handleToFlow,
  normalizeHandle,
  snapGuideStyle,
} from './handleGeometry'

const props = defineProps({
  id: String,
  data: { type: Object, default: () => ({}) },
  selected: Boolean,
})

const nodeId = useNodeId()
const { getEdges } = useVueFlow({ id: 'eva-pipeline' })

const iconMap = {
  'source.rtsp': VideoCamera,
  'detect.yolo': Aim,
  'track.bytetrack': Connection,
  'logic.alert': Bell,
  'logic.vlm_gate': ChatDotRound,
  'composite.mtmc': Cpu,
  'sink.overlay': Monitor,
  'sink.db': Coin,
  'sink.webhook': Link,
  'sink.mqtt': View,
}

const icon = computed(() => iconMap[props.data?.nodeType] || Aim)
const color = computed(() => props.data?.color || '#409eff')
const label = computed(() => props.data?.label || props.data?.nodeType || '节点')
const cat = computed(() => {
  const t = props.data?.nodeType || ''
  if (t.startsWith('source.')) return '输入处理'
  if (t.startsWith('detect.') || t.startsWith('track.')) return '模型推理'
  if (t.startsWith('logic.') || t.startsWith('composite.')) return '规则判断'
  if (t.startsWith('sink.')) return '告警输出'
  return ''
})

const handles = computed(() => {
  const defaults = defaultHandlesForMeta({
    portsIn: props.data?.portsIn,
    portsOut: props.data?.portsOut,
  })
  const saved = props.data?.handles || {}
  const out = {}
  if (defaults.target) {
    out.target = normalizeHandle(saved.target || defaults.target, defaults.target)
  }
  if (defaults.source) {
    out.source = normalizeHandle(saved.source || defaults.source, defaults.source)
  }
  return out
})

const targetFlow = computed(() => (handles.value.target ? handleToFlow(handles.value.target) : null))
const sourceFlow = computed(() => (handles.value.source ? handleToFlow(handles.value.source) : null))

const hasConnectedEdges = computed(() => {
  const id = nodeId?.value || props.id
  if (!id) return false
  return getEdges.value.some((e) => e.source === id || e.target === id)
})

const snapSides = ['top', 'right', 'bottom', 'left']
</script>

<template>
  <div
    class="eva-node"
    :class="{ selected, connected: hasConnectedEdges }"
    :style="{ '--node-accent': color }"
  >
    <template v-if="selected">
      <span
        v-for="side in snapSides"
        :key="side"
        class="eva-snap-guide"
        :style="snapGuideStyle(side)"
      />
    </template>

    <Handle
      v-if="targetFlow"
      id="target"
      type="target"
      :position="targetFlow.position"
      :style="targetFlow.style"
      class="eva-handle eva-handle-ghost"
    />

    <div class="eva-node-cat" v-if="cat">{{ cat }}</div>
    <div class="eva-node-body">
      <div class="eva-node-icon">
        <el-icon :size="22"><component :is="icon" /></el-icon>
      </div>
      <div class="eva-node-text">
        <div class="eva-node-title">{{ label }}</div>
        <div class="eva-node-type">{{ data.nodeType }}</div>
      </div>
    </div>

    <Handle
      v-if="sourceFlow"
      id="source"
      type="source"
      :position="sourceFlow.position"
      :style="sourceFlow.style"
      class="eva-handle eva-handle-ghost"
    />

    <div v-if="selected" class="eva-handle-hint">选中后可拖动节点 · 端点可沿边框自由移动 · 对角连线单拐点</div>
  </div>
</template>

<style scoped>
.eva-node {
  position: relative;
  min-width: 148px;
  max-width: 180px;
  background: #fff;
  border: 2px solid var(--node-accent, #409eff);
  border-radius: 12px;
  box-shadow: 0 4px 14px rgba(64, 158, 255, 0.12);
  padding: 10px 12px 12px;
  font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
  cursor: default;
  box-sizing: border-box;
}
.eva-node.selected {
  cursor: move;
  background: color-mix(in srgb, var(--node-accent, #409eff) 16%, #fff);
  border-color: var(--node-accent, #409eff);
  box-shadow: 0 0 0 3px rgba(64, 158, 255, 0.28), 0 8px 20px rgba(64, 158, 255, 0.18);
  border-width: 2px;
}
.eva-node.selected .eva-node-icon {
  background: color-mix(in srgb, var(--node-accent) 28%, #fff);
}
.eva-node.selected,
.eva-node.selected * {
  cursor: move;
}
.eva-node.selected .eva-handle-ghost {
  cursor: crosshair !important;
}
.eva-node-cat {
  font-size: 10px;
  letter-spacing: 0.04em;
  color: var(--node-accent);
  margin-bottom: 6px;
  font-weight: 600;
}
.eva-node-body {
  display: flex;
  align-items: center;
  gap: 10px;
}
.eva-node-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: color-mix(in srgb, var(--node-accent) 14%, #fff);
  color: var(--node-accent);
  flex-shrink: 0;
}
.eva-node-title {
  font-size: 13px;
  font-weight: 650;
  color: #303133;
  line-height: 1.25;
}
.eva-node-type {
  margin-top: 2px;
  font-size: 10px;
  color: #909399;
  font-family: ui-monospace, Consolas, monospace;
}
/* 连接点视觉与连线端点合一，保留透明热区用于新建连线 */
.eva-handle-ghost {
  width: 14px !important;
  height: 14px !important;
  opacity: 0 !important;
  background: transparent !important;
  border: none !important;
  z-index: 4;
}
.eva-snap-guide {
  position: absolute;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: color-mix(in srgb, var(--node-accent) 25%, #fff);
  border: 1px solid color-mix(in srgb, var(--node-accent) 55%, #fff);
  pointer-events: none;
  z-index: 1;
  opacity: 0.65;
}
.eva-handle-hint {
  position: absolute;
  left: 50%;
  bottom: -22px;
  transform: translateX(-50%);
  white-space: nowrap;
  font-size: 10px;
  color: #909399;
  pointer-events: none;
}
</style>
