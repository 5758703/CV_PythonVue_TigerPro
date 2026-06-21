<template>
  <div>
    <el-card shadow="never" class="cfg-card">
      <el-form :inline="true">
        <el-form-item label="模型分类">
          <el-select v-model="category" placeholder="全部分类" clearable style="width: 150px" :disabled="running" @change="onCategoryChange">
            <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="检测模型">
          <el-select v-model="modelId" placeholder="选择模型" style="width: 200px" :disabled="running">
            <el-option
              v-for="m in filteredModels"
              :key="m.id"
              :label="`${m.modelName}（${m.category || '未分类'}）`"
              :value="m.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="摄像头">
          <el-select v-model="deviceId" placeholder="默认摄像头" style="width: 200px" :disabled="running">
            <el-option v-for="d in devices" :key="d.deviceId" :label="d.label || `摄像头 ${d.idx}`" :value="d.deviceId" />
          </el-select>
        </el-form-item>
        <el-form-item label="置信度">
          <el-slider v-model="conf" :min="0.05" :max="0.95" :step="0.05" style="width: 140px" />
        </el-form-item>
        <el-form-item>
          <el-button v-if="!running" type="primary" :icon="VideoCamera" :disabled="!modelId" @click="start">开始检测</el-button>
          <el-button v-else type="danger" :icon="SwitchButton" @click="stop">停止</el-button>
        </el-form-item>
      </el-form>
      <el-alert
        v-if="!modelOptions.length"
        type="warning"
        :closable="false"
        title="暂无可用模型：请先到「模型管理」上传或拉取权重，并保持启用状态。"
      />
    </el-card>

    <el-card shadow="never">
      <div class="live-grid">
        <div class="stage">
          <video ref="videoEl" class="cam-video" autoplay playsinline muted></video>
          <canvas ref="overlayEl" class="overlay"></canvas>
          <div v-if="!running" class="stage-hint">
            <el-icon :size="40"><VideoCamera /></el-icon>
            <span>点击「开始检测」启用摄像头</span>
          </div>
          <div v-if="running" class="hud">
            <el-tag type="success" effect="dark">{{ fps }} FPS</el-tag>
            <el-tag type="warning" effect="dark">目标 {{ dets.length }}</el-tag>
          </div>
        </div>
        <div class="side">
          <div class="side-title">实时检测目标</div>
          <el-empty v-if="!dets.length" :image-size="60" description="无目标" />
          <el-table v-else :data="dets" size="small" border max-height="460">
            <el-table-column type="index" label="#" width="48" />
            <el-table-column prop="className" label="类别" />
            <el-table-column label="置信度" width="90">
              <template #default="{ row }">{{ (row.confidence * 100).toFixed(0) }}%</template>
            </el-table-column>
          </el-table>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { VideoCamera, SwitchButton } from '@element-plus/icons-vue'

import { modelApi } from '../../../api/ai'

const modelOptions = ref([])
const modelId = ref(null)
const category = ref('')
const conf = ref(0.25)
const devices = ref([])

const categories = computed(() => [...new Set(modelOptions.value.map((m) => m.category).filter(Boolean))])
const filteredModels = computed(() =>
  category.value ? modelOptions.value.filter((m) => m.category === category.value) : modelOptions.value
)
const onCategoryChange = () => {
  modelId.value = filteredModels.value[0]?.id || null
}
const deviceId = ref('')

const videoEl = ref(null)
const overlayEl = ref(null)

const running = ref(false)
const dets = ref([])
const fps = ref(0)

let stream = null
let capCanvas = null         // 离屏抓帧画布
let busy = false             // 串行：上一帧未返回不发下一帧
let frameCount = 0
let fpsTimer = null
const COLORS = ['#67c23a', '#409eff', '#e6a23c', '#f56c6c', '#9254de', '#13c2c2']

const loadModels = async () => {
  const res = await modelApi.list({ pageNum: 1, pageSize: 100 })
  modelOptions.value = (res.data.rows || []).filter(
    (m) => m.task === 'object-detection' && m.filePath && m.status === '0'
  )
  if (modelOptions.value.length && !modelId.value) modelId.value = modelOptions.value[0].id
}

const enumCams = async () => {
  try {
    const list = await navigator.mediaDevices.enumerateDevices()
    devices.value = list.filter((d) => d.kind === 'videoinput').map((d, i) => ({ deviceId: d.deviceId, label: d.label, idx: i + 1 }))
  } catch (e) {
    /* 权限授予前 label 可能为空 */
  }
}

const start = async () => {
  try {
    const constraints = { video: deviceId.value ? { deviceId: { exact: deviceId.value } } : true, audio: false }
    stream = await navigator.mediaDevices.getUserMedia(constraints)
  } catch (e) {
    ElMessage.error('无法访问摄像头，请检查设备与浏览器权限')
    return
  }
  videoEl.value.srcObject = stream
  await videoEl.value.play()
  await enumCams()  // 授权后可拿到 label

  // 抓帧分辨率（限宽 640 提速）
  const vw = videoEl.value.videoWidth
  const vh = videoEl.value.videoHeight
  const capW = Math.min(vw, 640)
  const capH = Math.round((vh * capW) / vw)
  capCanvas = document.createElement('canvas')
  capCanvas.width = capW
  capCanvas.height = capH
  overlayEl.value.width = capW
  overlayEl.value.height = capH

  running.value = true
  frameCount = 0
  fps.value = 0
  fpsTimer = setInterval(() => { fps.value = frameCount; frameCount = 0 }, 1000)
  loop()
}

const loop = () => {
  if (!running.value) return
  if (busy) { requestAnimationFrame(loop); return }
  busy = true

  const ctx = capCanvas.getContext('2d')
  ctx.drawImage(videoEl.value, 0, 0, capCanvas.width, capCanvas.height)
  capCanvas.toBlob(async (blob) => {
    if (!running.value || !blob) { busy = false; return }
    try {
      const fd = new FormData()
      fd.append('file', blob, 'frame.jpg')
      fd.append('conf', conf.value)
      fd.append('draw', '0')  // 仅取坐标，客户端画框
      const res = await modelApi.detect(modelId.value, fd)
      dets.value = res.data.detections
      drawBoxes(res.data.detections)
      frameCount++
    } catch (e) {
      /* 单帧失败忽略，继续下一帧 */
    } finally {
      busy = false
      if (running.value) requestAnimationFrame(loop)
    }
  }, 'image/jpeg', 0.6)
}

const drawBoxes = (list) => {
  const cv = overlayEl.value
  const ctx = cv.getContext('2d')
  ctx.clearRect(0, 0, cv.width, cv.height)
  ctx.lineWidth = 2
  ctx.font = '14px sans-serif'
  ctx.textBaseline = 'top'
  list.forEach((d, i) => {
    const [x1, y1, x2, y2] = d.bbox
    const color = COLORS[d.classId % COLORS.length] || COLORS[i % COLORS.length]
    ctx.strokeStyle = color
    ctx.strokeRect(x1, y1, x2 - x1, y2 - y1)
    const label = `${d.className} ${(d.confidence * 100).toFixed(0)}%`
    const tw = ctx.measureText(label).width + 8
    ctx.fillStyle = color
    ctx.fillRect(x1, Math.max(0, y1 - 18), tw, 18)
    ctx.fillStyle = '#fff'
    ctx.fillText(label, x1 + 4, Math.max(0, y1 - 17))
  })
}

const stop = () => {
  running.value = false
  if (fpsTimer) { clearInterval(fpsTimer); fpsTimer = null }
  if (stream) { stream.getTracks().forEach((t) => t.stop()); stream = null }
  if (videoEl.value) videoEl.value.srcObject = null
  if (overlayEl.value) {
    const ctx = overlayEl.value.getContext('2d')
    ctx.clearRect(0, 0, overlayEl.value.width, overlayEl.value.height)
  }
  dets.value = []
  fps.value = 0
}

onMounted(async () => {
  await loadModels()
  await enumCams()
})
onBeforeUnmount(stop)
</script>

<style scoped>
.cfg-card {
  margin-bottom: 12px;
}
.live-grid {
  display: flex;
  gap: 16px;
}
.stage {
  position: relative;
  flex: 1 1 70%;
  min-width: 0;
  background: #0c1733;
  border-radius: 8px;
  aspect-ratio: 16 / 9;
  overflow: hidden;
}
.cam-video,
.overlay {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: contain;
}
.overlay {
  pointer-events: none;
}
.stage-hint {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: #8aa0c8;
}
.hud {
  position: absolute;
  top: 10px;
  left: 10px;
  display: flex;
  gap: 8px;
}
.side {
  flex: 1 1 30%;
  min-width: 0;
}
.side-title {
  font-weight: 600;
  color: #3a4a63;
  margin-bottom: 10px;
}
</style>
