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
        <el-form-item class="alert-action-item">
          <div class="alert-action-row">
            <el-button v-if="!running" type="primary" :icon="VideoCamera" :disabled="!modelId" @click="start">开始检测</el-button>
            <el-button v-else type="danger" :icon="SwitchButton" @click="stop">停止</el-button>
            <el-checkbox v-model="alertEnabled" :disabled="running" style="margin-left: 12px">启用告警</el-checkbox>
            <el-alert
              v-if="alertEnabled && allModels.length && filteredModels.length"
              type="info"
              :closable="false"
              show-icon
              class="alert-tip-inline"
              title="总开关已开：仅「检测告警」页中已启用的规则会生效。单项开关请到检测告警页配置。"
            />
          </div>
        </el-form-item>
      </el-form>
      <el-alert
        v-if="!allModels.length"
        type="warning"
        :closable="false"
        title="暂无可用模型：请先到「模型管理」上传或拉取权重，并保持启用状态。"
      />
      <el-alert
        v-else-if="alertEnabled && !filteredModels.length"
        type="warning"
        :closable="false"
        title="启用告警后无可用模型：请选用 YOLO / RF-DETR / transformers 目标检测权重（如烟火、PPE、YOLO26）。"
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
            <el-tag v-if="alertEnabled && lastAlertTitle" type="danger" effect="dark">{{ lastAlertTitle }}</el-tag>
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
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage, ElNotification } from 'element-plus'
import { VideoCamera, SwitchButton } from '@element-plus/icons-vue'
import { modelApi, alertApi } from '../../../api/ai'
import {
  filterWorkbenchModels,
  ensureModelInList,
  categoriesFromModels,
} from '../../../utils/alertModels'

const ALERT_SOURCE_KEY = 'camera-live'

const allModels = ref([])
const modelId = ref(null)
const category = ref('')
const conf = ref(0.25)
const devices = ref([])
const alertEnabled = ref(false)
const lastAlertTitle = ref('')
const liveOverlay = ref(null)

const categories = computed(() => categoriesFromModels(
  filterWorkbenchModels(allModels.value, { alertEnabled: alertEnabled.value }),
))
const filteredModels = computed(() =>
  filterWorkbenchModels(allModels.value, {
    alertEnabled: alertEnabled.value,
    category: category.value,
  }),
)
const syncModelSelection = () => {
  modelId.value = ensureModelInList(modelId.value, filteredModels.value)
}
const onCategoryChange = () => {
  syncModelSelection()
}

watch(alertEnabled, () => {
  if (category.value && !categories.value.includes(category.value)) category.value = ''
  syncModelSelection()
})
watch(filteredModels, () => { syncModelSelection() }, { immediate: true })
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

const notifyAlert = (item) => {
  const type = item.severity === 'high' ? 'error' : item.severity === 'medium' ? 'warning' : 'info'
  ElNotification({
    title: item.title || item.ruleName || '检测告警',
    message: item.message || '请现场核实',
    type,
    duration: item.severity === 'high' ? 0 : 8000,
    position: 'top-right',
  })
  lastAlertTitle.value = item.title || item.ruleName || '告警'
}

const evaluateAlerts = async (detections) => {
  if (!alertEnabled.value) {
    liveOverlay.value = null
    return
  }
  if (!detections?.length) {
    liveOverlay.value = null
    return
  }
  try {
    const res = await alertApi.evaluate({
      detections,
      sourceKey: ALERT_SOURCE_KEY,
      sourceType: 'camera',
      modelId: modelId.value,
      persist: true,
    })
    const list = res.data?.triggered || []
    list.filter((t) => t.notify).forEach(notifyAlert)
    liveOverlay.value = res.data?.overlay || null
  } catch (_) {
    /* 告警失败不阻断检测 */
  }
}

const loadModels = async () => {
  const res = await modelApi.list({ pageNum: 1, pageSize: 100 })
  allModels.value = (res.data.rows || []).filter(
    (m) => m.task === 'object-detection' && m.filePath && m.status === '0'
  )
  syncModelSelection()
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
      await evaluateAlerts(res.data.detections)
      drawBoxes(res.data.detections, liveOverlay.value)
      frameCount++
    } catch (e) {
      /* 单帧失败忽略，继续下一帧 */
    } finally {
      busy = false
      if (running.value) requestAnimationFrame(loop)
    }
  }, 'image/jpeg', 0.6)
}

const drawAlertOverlay = (ctx, cv, style) => {
  if (!style || style.enabled === false) return
  const w = cv.width
  const h = cv.height
  const wr = Math.min(0.95, Math.max(0.3, Number(style.panelWidthRatio) || 0.72))
  const hr = Math.min(0.8, Math.max(0.18, Number(style.panelHeightRatio) || 0.36))
  const opacity = Math.min(0.85, Math.max(0.15, Number(style.opacity) || 0.45))
  const pw = Math.round(w * wr)
  const ph = Math.round(h * hr)
  const x = Math.round((w - pw) / 2)
  const y = Math.round((h - ph) / 2)
  const cx = Math.round(w / 2)

  ctx.save()
  ctx.globalAlpha = opacity
  ctx.fillStyle = style.fillColor || '#FFD400'
  ctx.fillRect(x, y, pw, ph)
  ctx.globalAlpha = 1
  ctx.strokeStyle = style.borderColor || style.fillColor || '#E6B800'
  ctx.lineWidth = 3
  ctx.strokeRect(x, y, pw, ph)

  if (style.showTriangle !== false) {
    const triR = Math.max(22, Math.min(pw, ph) * 0.12)
    const icy = y + Math.round(ph * 0.28)
    ctx.beginPath()
    ctx.moveTo(cx, icy - triR)
    ctx.lineTo(cx - triR * 0.95, icy + triR * 0.78)
    ctx.lineTo(cx + triR * 0.95, icy + triR * 0.78)
    ctx.closePath()
    ctx.fillStyle = style.triangleFill || '#1A1A1A'
    ctx.fill()
    ctx.strokeStyle = '#fff'
    ctx.lineWidth = 2
    ctx.stroke()
    ctx.strokeStyle = style.triangleMark || '#fff'
    ctx.lineWidth = Math.max(3, triR / 7)
    ctx.beginPath()
    ctx.moveTo(cx, icy - triR * 0.38)
    ctx.lineTo(cx, icy + triR * 0.08)
    ctx.stroke()
    ctx.beginPath()
    ctx.arc(cx, icy + triR * 0.4, Math.max(3, triR / 10), 0, Math.PI * 2)
    ctx.fillStyle = style.triangleMark || '#fff'
    ctx.fill()
  }

  const titles = style.titleLines || []
  const subs = style.subtitleLines || []
  const lines = [...titles, ...subs]
  ctx.fillStyle = style.textColor || '#1A1A1A'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'top'
  let ty = y + Math.round(ph * 0.52)
  lines.forEach((ln, i) => {
    const isTitle = i < titles.length
    ctx.font = `${isTitle ? 'bold ' : ''}${isTitle ? 20 : 16}px "Microsoft YaHei", "PingFang SC", sans-serif`
    ctx.fillText(ln, cx, ty)
    ty += isTitle ? 26 : 22
  })
  ctx.restore()
}

const drawBoxes = (list, overlayStyle = null) => {
  const cv = overlayEl.value
  if (!cv) return
  const ctx = cv.getContext('2d')
  ctx.clearRect(0, 0, cv.width, cv.height)
  ctx.lineWidth = 2
  ctx.font = '14px sans-serif'
  ctx.textBaseline = 'top'
  ctx.textAlign = 'left'
  ;(list || []).forEach((d, i) => {
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
  if (alertEnabled.value && overlayStyle) {
    drawAlertOverlay(ctx, cv, overlayStyle)
  }
}

const stop = async () => {
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
  lastAlertTitle.value = ''
  liveOverlay.value = null
  try {
    await alertApi.resetRuntime({ sourceKey: ALERT_SOURCE_KEY })
  } catch (_) { /* ignore */ }
}

onMounted(async () => {
  await Promise.all([loadModels(), enumCams()])
})
onBeforeUnmount(stop)
</script>

<style scoped>
.cfg-card {
  margin-bottom: 12px;
}
.alert-action-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px 0;
}
.alert-tip-inline {
  flex: 1 1 320px;
  width: auto;
  margin: 0 0 0 12px;
  padding: 5px 12px;
}
.alert-tip-inline :deep(.el-alert__content) {
  padding: 0;
}
.alert-tip-inline :deep(.el-alert__title) {
  font-size: 13px;
  line-height: 1.4;
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
