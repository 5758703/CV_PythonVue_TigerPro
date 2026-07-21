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
        <el-form-item label="视频源">
          <el-select
            v-model="videoSource"
            placeholder="选择视频源"
            style="width: 160px"
            :disabled="running"
            @change="onVideoSourceChange"
          >
            <el-option label="本地摄像头" value="local" />
            <el-option label="网络摄像头" value="network" />
          </el-select>
        </el-form-item>
        <el-form-item label="摄像头">
          <el-select
            v-if="videoSource === 'local'"
            v-model="deviceId"
            placeholder="默认本地摄像头"
            style="width: 220px"
            :disabled="running"
          >
            <el-option label="默认本地摄像头" value="" />
            <el-option
              v-for="d in devices"
              :key="d.deviceId"
              :label="d.label ? `${d.label}（本地）` : `本地摄像头 ${d.idx}`"
              :value="d.deviceId"
            />
          </el-select>
          <template v-else>
            <el-select
              v-model="cameraId"
              placeholder="选择网络摄像头"
              filterable
              clearable
              style="width: 240px"
              :disabled="running"
              :loading="camerasLoading"
            >
              <el-option
                v-for="c in managedCameras"
                :key="c.id"
                :label="cameraLabel(c)"
                :value="c.id"
              />
            </el-select>
            <el-button
              link
              type="primary"
              :disabled="running"
              style="margin-left: 4px"
              @click="loadManagedCameras"
            >
              刷新
            </el-button>
          </template>
        </el-form-item>
        <el-form-item label="置信度">
          <el-slider v-model="conf" :min="0.05" :max="0.95" :step="0.05" style="width: 140px" />
        </el-form-item>
        <el-form-item class="alert-action-item">
          <div class="alert-action-row">
            <el-button
              v-if="!running"
              type="primary"
              :icon="VideoCamera"
              :disabled="!modelId || (videoSource === 'network' && !cameraId)"
              @click="start"
            >
              开始检测
            </el-button>
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
      <el-alert
        v-else-if="videoSource === 'network' && !camerasLoading && !managedCameras.length"
        type="warning"
        :closable="false"
        class="net-cam-tip"
        title="暂无可用网络摄像头：请先到「摄像头管理」添加并启用（支持 RTSP / 文件 / 设备）。"
      />
    </el-card>

    <el-card shadow="never">
      <div class="live-grid">
        <div class="stage">
          <video
            v-show="localPreview && videoSource === 'local'"
            ref="videoEl"
            class="cam-video"
            autoplay
            playsinline
            muted
          ></video>
          <img
            v-show="running && videoSource === 'network'"
            ref="streamEl"
            class="cam-video"
            alt="网络摄像头"
            @error="onStreamError"
          />
          <canvas ref="overlayEl" class="overlay"></canvas>
          <div v-if="!running && !localPreview" class="stage-hint">
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
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { ElMessage, ElNotification } from 'element-plus'
import { VideoCamera, SwitchButton } from '@element-plus/icons-vue'
import { modelApi, alertApi } from '../../../api/ai'
import { cameraApi } from '../../../api/camera'
import {
  filterWorkbenchModels,
  ensureModelInList,
  categoriesFromModels,
} from '../../../utils/alertModels'

const ALERT_SOURCE_KEY = 'camera-live'
const SOURCE_TYPE_LABEL = { rtsp: 'RTSP', file: '文件', device: '设备' }

const allModels = ref([])
const modelId = ref(null)
const category = ref('')
const conf = ref(0.25)
const devices = ref([])
const deviceId = ref('')
const videoSource = ref('local') // local | network
const localPreview = ref(false)
const managedCameras = ref([])
const cameraId = ref(null)
const camerasLoading = ref(false)
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

const videoEl = ref(null)
const streamEl = ref(null)
const overlayEl = ref(null)

const running = ref(false)
const dets = ref([])
const fps = ref(0)

let stream = null
let capCanvas = null
let busy = false
let frameCount = 0
let fpsTimer = null
let loopTimer = null
let streamReady = false
let streamErrorCooldown = 0
const COLORS = ['#67c23a', '#409eff', '#e6a23c', '#f56c6c', '#9254de', '#13c2c2']

const cameraLabel = (c) => {
  const tag = SOURCE_TYPE_LABEL[c.sourceType] || c.sourceType || ''
  const kind = tag ? `网络·${tag}` : '网络'
  return `${c.name}（${kind}）`
}

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
    devices.value = list
      .filter((d) => d.kind === 'videoinput')
      .map((d, i) => ({ deviceId: d.deviceId, label: d.label, idx: i + 1 }))
  } catch (_) {
    /* 权限授予前 label 可能为空 */
  }
}

const loadManagedCameras = async () => {
  camerasLoading.value = true
  try {
    const res = await cameraApi.list({ pageNum: 1, pageSize: 100, status: '0' })
    managedCameras.value = res.data?.rows || []
    if (cameraId.value && !managedCameras.value.some((c) => c.id === cameraId.value)) {
      cameraId.value = null
    }
    if (!cameraId.value && managedCameras.value.length) {
      cameraId.value = managedCameras.value[0].id
    }
  } catch (_) {
    managedCameras.value = []
    /* 无 camera:list 权限时软失败，不阻断本地摄像头 */
  } finally {
    camerasLoading.value = false
  }
}

const onVideoSourceChange = async () => {
  if (running.value) stop()
  localPreview.value = false
  if (videoSource.value === 'network') await loadManagedCameras()
  else await enumCams()
}

const waitForVideoReady = (video, timeoutMs = 8000) =>
  new Promise((resolve, reject) => {
    if (video.videoWidth > 0 && video.readyState >= 2) {
      resolve()
      return
    }
    const started = Date.now()
    let settled = false
    const finish = (ok, err) => {
      if (settled) return
      settled = true
      clearInterval(poll)
      clearTimeout(timer)
      video.removeEventListener('loadedmetadata', onReady)
      video.removeEventListener('loadeddata', onReady)
      video.removeEventListener('playing', onReady)
      if (ok) resolve()
      else reject(err || new Error('timeout'))
    }
    const onReady = () => {
      if (video.videoWidth > 0) finish(true)
    }
    const poll = setInterval(() => {
      if (video.videoWidth > 0 && video.readyState >= 2) finish(true)
      else if (Date.now() - started > timeoutMs) finish(false, new Error('timeout'))
    }, 100)
    const timer = setTimeout(() => finish(false, new Error('timeout')), timeoutMs)
    video.addEventListener('loadedmetadata', onReady)
    video.addEventListener('loadeddata', onReady)
    video.addEventListener('playing', onReady)
  })

const waitForImgReady = (img, timeoutMs = 15000) =>
  new Promise((resolve, reject) => {
    if (img.complete && img.naturalWidth > 0) {
      resolve()
      return
    }
    const started = Date.now()
    let settled = false
    const finish = (ok, err) => {
      if (settled) return
      settled = true
      clearInterval(poll)
      clearTimeout(timer)
      img.removeEventListener('load', onLoad)
      img.removeEventListener('error', onError)
      if (ok) resolve()
      else reject(err || new Error('timeout'))
    }
    const onLoad = () => {
      if (img.naturalWidth > 0) finish(true)
    }
    const onError = () => finish(false, new Error('load'))
    const poll = setInterval(() => {
      if (img.naturalWidth > 0) finish(true)
      else if (Date.now() - started > timeoutMs) finish(false, new Error('timeout'))
    }, 200)
    const timer = setTimeout(() => finish(false, new Error('timeout')), timeoutMs)
    img.addEventListener('load', onLoad)
    img.addEventListener('error', onError)
  })

const onStreamError = () => {
  if (!running.value || videoSource.value !== 'network') return
  if (!streamReady) return
  const now = Date.now()
  if (now - streamErrorCooldown < 3000) return
  streamErrorCooldown = now
  const img = streamEl.value
  if (img && cameraId.value) {
    img.removeAttribute('crossorigin')
    img.src = cameraApi.streamUrl(cameraId.value, String(Date.now()), false, true)
  }
}

const getFrameSourceSize = () => {
  if (videoSource.value === 'network') {
    const img = streamEl.value
    return { w: img?.naturalWidth || 0, h: img?.naturalHeight || 0, el: img }
  }
  const video = videoEl.value
  return { w: video?.videoWidth || 0, h: video?.videoHeight || 0, el: video }
}

const scheduleLoop = (delayMs = 0) => {
  if (!running.value) return
  if (loopTimer) clearTimeout(loopTimer)
  loopTimer = setTimeout(() => {
    loopTimer = null
    loop()
  }, delayMs)
}

const start = async () => {
  if (!modelId.value) {
    ElMessage.warning('请选择检测模型')
    return
  }

  if (videoSource.value === 'network') {
    if (!cameraId.value) {
      ElMessage.warning('请选择网络摄像头')
      return
    }
    localPreview.value = false
    if (stream) {
      stream.getTracks().forEach((t) => t.stop())
      stream = null
    }
    if (videoEl.value) videoEl.value.srcObject = null

    running.value = true
    streamReady = false
    await nextTick()
    const img = streamEl.value
    if (!img) {
      ElMessage.error('预览组件未就绪')
      running.value = false
      return
    }
    // 检测抓帧必须走同源 /api，避免 dev 下跨域导致 canvas 污染
    img.removeAttribute('crossorigin')
    img.src = cameraApi.streamUrl(cameraId.value, String(Date.now()), false, true)
    try {
      await waitForImgReady(img)
      streamReady = true
    } catch (_) {
      ElMessage.error('无法连接网络摄像头，请检查摄像头管理中的源地址与状态')
      img.removeAttribute('src')
      running.value = false
      streamReady = false
      return
    }
  } else {
    if (streamEl.value) streamEl.value.removeAttribute('src')
    localPreview.value = true
    await nextTick()
    try {
      const constraints = {
        video: deviceId.value
          ? { deviceId: { exact: deviceId.value }, width: { ideal: 640 }, height: { ideal: 480 } }
          : { width: { ideal: 640 }, height: { ideal: 480 } },
        audio: false,
      }
      stream = await navigator.mediaDevices.getUserMedia(constraints)
    } catch (_) {
      localPreview.value = false
      ElMessage.error('无法访问摄像头，请检查设备与浏览器权限')
      return
    }
    const video = videoEl.value
    if (!video) {
      localPreview.value = false
      ElMessage.error('预览组件未就绪')
      return
    }
    video.srcObject = stream
    try {
      await video.play()
    } catch (_) {
      /* autoplay 策略偶发拒绝 */
    }
    try {
      await waitForVideoReady(video)
    } catch (_) {
      ElMessage.error('本地摄像头尚未就绪，请重试')
      stop()
      return
    }
    enumCams()
  }

  const { w: vw, h: vh } = getFrameSourceSize()
  if (!vw || !vh) {
    ElMessage.error('无法获取画面尺寸')
    stop()
    return
  }
  const capW = Math.min(vw, 640)
  const capH = Math.round((vh * capW) / vw)
  capCanvas = document.createElement('canvas')
  capCanvas.width = capW
  capCanvas.height = capH
  if (overlayEl.value) {
    overlayEl.value.width = capW
    overlayEl.value.height = capH
  }

  running.value = true
  frameCount = 0
  fps.value = 0
  lastAlertTitle.value = ''
  liveOverlay.value = null
  busy = false
  if (fpsTimer) clearInterval(fpsTimer)
  fpsTimer = setInterval(() => {
    fps.value = frameCount
    frameCount = 0
  }, 1000)

  scheduleLoop(0)
}

const loop = () => {
  if (!running.value) return
  if (busy) {
    scheduleLoop(40)
    return
  }
  busy = true

  const { el, w, h } = getFrameSourceSize()
  if (!el || !capCanvas || !w || !h) {
    busy = false
    scheduleLoop(50)
    return
  }
  const capW = Math.min(w, 640)
  const capH = Math.round((h * capW) / w)
  if (capCanvas.width !== capW || capCanvas.height !== capH) {
    capCanvas.width = capW
    capCanvas.height = capH
    if (overlayEl.value) {
      overlayEl.value.width = capW
      overlayEl.value.height = capH
    }
  }
  const ctx = capCanvas.getContext('2d')
  try {
    ctx.drawImage(el, 0, 0, capCanvas.width, capCanvas.height)
  } catch (_) {
    busy = false
    scheduleLoop(50)
    return
  }

  capCanvas.toBlob(async (blob) => {
    if (!running.value || !blob) {
      busy = false
      if (running.value) scheduleLoop(videoSource.value === 'network' ? 80 : 0)
      return
    }
    try {
      const fd = new FormData()
      fd.append('file', blob, 'frame.jpg')
      fd.append('conf', conf.value)
      fd.append('draw', '0')
      const res = await modelApi.detect(modelId.value, fd)
      if (!running.value) return
      dets.value = res.data.detections
      await evaluateAlerts(res.data.detections)
      drawBoxes(res.data.detections, liveOverlay.value)
      frameCount++
    } catch (_) {
      /* 单帧失败忽略，继续下一帧 */
    } finally {
      busy = false
      if (running.value) scheduleLoop(videoSource.value === 'network' ? 80 : 0)
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
  streamReady = false
  localPreview.value = false
  busy = false
  if (loopTimer) {
    clearTimeout(loopTimer)
    loopTimer = null
  }
  if (fpsTimer) {
    clearInterval(fpsTimer)
    fpsTimer = null
  }
  if (stream) {
    stream.getTracks().forEach((t) => t.stop())
    stream = null
  }
  if (videoEl.value) videoEl.value.srcObject = null
  if (streamEl.value) {
    streamEl.value.removeAttribute('src')
    streamEl.value.removeAttribute('srcset')
  }
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
  await Promise.all([loadModels(), enumCams(), loadManagedCameras()])
})
onBeforeUnmount(stop)
</script>

<style scoped>
.cfg-card {
  margin-bottom: 12px;
}
.net-cam-tip {
  margin-top: 8px;
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
