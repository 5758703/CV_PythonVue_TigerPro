<script setup>
import { computed } from 'vue'
import { Handle, Position } from '@vue-flow/core'
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

const props = defineProps({
  id: String,
  data: { type: Object, default: () => ({}) },
  selected: Boolean,
})

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
</script>

<template>
  <div class="eva-node" :class="{ selected }" :style="{ '--node-accent': color }">
    <Handle type="target" :position="Position.Left" class="eva-handle" />
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
    <Handle type="source" :position="Position.Right" class="eva-handle" />
  </div>
</template>

<style scoped>
.eva-node {
  min-width: 148px;
  max-width: 180px;
  background: #fff;
  border: 2px solid var(--node-accent, #409eff);
  border-radius: 12px;
  box-shadow: 0 4px 14px rgba(64, 158, 255, 0.12);
  padding: 10px 12px 12px;
  font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
}
.eva-node.selected {
  box-shadow: 0 0 0 3px rgba(64, 158, 255, 0.28), 0 8px 20px rgba(64, 158, 255, 0.18);
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
.eva-handle {
  width: 10px !important;
  height: 10px !important;
  background: var(--node-accent) !important;
  border: 2px solid #fff !important;
}
</style>
