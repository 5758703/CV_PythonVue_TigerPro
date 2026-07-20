<template>
  <div>
    <el-card shadow="never" class="cfg-card">
      <el-form :inline="true">
        <el-form-item label="模式">
          <el-radio-group v-model="mode" :disabled="camRunning" @change="onModeChange">
            <el-radio-button value="file">视频文件</el-radio-button>
            <el-radio-button value="camera">摄像头</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="模型分类">
          <el-select v-model="category" placeholder="全部分类" clearable style="width: 150px" @change="onCategoryChange">
            <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="检测模型">
          <el-select v-model="modelId" placeholder="选择 YOLO 模型" style="width: 220px">
            <el-option v-for="m in filteredModels" :key="m.id"
                       :label="`${m.modelName}（${m.category || '未分类'}）`" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="分辨率">
          <el-select v-model="imgsz" style="width: 110px">
            <el-option :value="640" label="640" />
            <el-option :value="480" label="480" />
            <el-option :value="320" label="320（最快）" />
          </el-select>
        </el-form-item>
        <el-form-item label="置信度">
          <el-slider v-model="conf" :min="0.05" :max="0.95" :step="0.05" style="width: 150px" />
        </el-form-item>
        <el-form-item v-if="mode==='file'">
          <el-upload :show-file-list="false" :auto-upload="false" :on-change="onPick" accept="video/*">
            <el-button :icon="UploadFilled">选择视频</el-button>
          </el-upload>
        </el-form-item>
        <el-form-item v-if="mode==='file'" class="alert-action-item">
          <div class="alert-action-row">
            <el-button type="primary" :icon="VideoPlay" :loading="running" :disabled="!modelId || !file" @click="run">开始追踪</el-button>
            <el-checkbox v-model="alertEnabled" :disabled="running" style="margin-left: 12px">启用告警</el-checkbox>
            <el-alert
              v-if="alertEnabled && allModels.length && filteredModels.length"
              type="info"
              :closable="false"
              show-icon
              class="alert-tip-inline"
              title="总开关已开：仅「检测告警」页已启用规则会烧录叠加；单项开关请到检测告警页配置。"
            />
            <el-button :icon="Refresh" @click="clearAll" style="margin-left: 8px">清空</el-button>
          </div>
        </el-form-item>
        <el-form-item v-if="mode==='camera'" label="摄像头">
          <el-select v-model="deviceId" placeholder="默认摄像头" style="width: 180px" :disabled="camRunning">
            <el-option v-for="d in devices" :key="d.deviceId" :label="d.label || `摄像头 ${d.idx}`" :value="d.deviceId" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="mode==='camera'" class="alert-action-item">
          <div class="alert-action-row">
            <el-button v-if="!camRunning" type="primary" :icon="VideoCamera" :disabled="!modelId" @click="camStart">开始</el-button>
            <el-button v-else type="danger" :icon="SwitchButton" @click="camStop">停止</el-button>
            <el-checkbox v-model="alertEnabled" :disabled="camRunning" style="margin-left: 12px">启用告警</el-checkbox>
            <el-alert
              v-if="alertEnabled && allModels.length && filteredModels.length"
              type="info"
              :closable="false"
              show-icon
              class="alert-tip-inline"
              title="总开关已开：仅「检测告警」页中已启用的规则会生效；画警戒线后越线规则可触发。单项开关请到检测告警页配置。"
            />
            <el-button v-if="camLine" link type="primary" @click="clearCamLine">清除线</el-button>
            <el-button v-if="recBlobUrl" link type="primary" :icon="Download" @click="downloadRec">下载录制</el-button>
          </div>
        </el-form-item>
      </el-form>
      <el-alert v-if="!allModels.length" type="warning" :closable="false"
                title="暂无可用模型：目标追踪需 ultralytics（YOLO）目标检测模型，请到「模型管理」上传/拉取并启用。" />
      <el-alert
        v-else-if="alertEnabled && !filteredModels.length"
        type="warning"
        :closable="false"
        title="启用告警后无可用模型：请拉取 YOLO 目标检测权重（如 YOLO26 / PPE / 烟火）。"
      />
      <div v-else-if="mode==='file'" class="hint">
        越线计数（可选）：在下方首帧点两点画线。
      </div>
    </el-card>

    <el-card v-if="mode==='file' && previewUrl" shadow="never" class="cfg-card">
      <div class="preview-title">原视频预览</div>
      <video :src="previewUrl" controls class="player" />
    </el-card>

    <el-card v-if="mode==='file' && file" shadow="never" class="cfg-card">
      <div class="line-tip">
        首帧画线：点第一点 → 点第二点。
        <el-button link type="primary" @click="clearLine">清除线</el-button>
        <span v-if="line" class="meta">已设置计数线</span>
      </div>
      <div class="frame-box">
        <canvas ref="frameCanvas" class="frame-canvas" @click="onCanvasClick"></canvas>
      </div>
    </el-card>

    <el-card v-if="mode==='file'" shadow="never">
      <div v-if="running" class="progress-box">
        <div class="progress-title">追踪中… {{ processed }}/{{ total || '?' }} 帧</div>
        <el-progress :percentage="percent" :stroke-width="18" :text-inside="true" :status="percent >= 100 ? 'success' : ''" />
      </div>

      <el-empty v-else-if="!resultUrl" description="选择模型与视频后开始追踪" />

      <div v-else>
        <div class="res-title">
          追踪结果
          <el-button link type="primary" :icon="Download" @click="download">下载视频</el-button>
        </div>
        <video :src="resultUrl" controls class="player" />
        <div class="stats">
          <el-tag type="success" effect="dark">唯一目标数：{{ stats.uniqueObjects }}</el-tag>
          <el-tag v-if="stats.crossing" type="warning" effect="dark">
            越线 进:{{ stats.crossing.in }} 出:{{ stats.crossing.out }} 净:{{ stats.crossing.in - stats.crossing.out }}
          </el-tag>
          <el-tag v-if="stats.alertOverlayFrames" type="danger" effect="dark">
            告警叠加 {{ stats.alertOverlayFrames }} 帧
          </el-tag>
          <el-tag v-if="stats.alertTriggered?.length" type="danger" effect="dark">
            触发 {{ stats.alertTriggered.length }} 次
          </el-tag>
        </div>
        <el-table :data="classRows" size="small" border class="cls-table">
          <el-table-column prop="name" label="类别" />
          <el-table-column prop="count" label="唯一数量" width="120" />
        </el-table>
      </div>
    </el-card>

    <div v-if="mode==='camera'" class="cam-wrap">
      <div class="cam-stage">
        <video ref="camVideo" class="cam-video" autoplay playsinline muted></video>
        <canvas ref="camCanvas" class="cam-canvas" @click="onCamClick"></canvas>
        <div v-if="!camRunning" class="cam-hint">点「开始」启用摄像头；可在画面点两点画计数线</div>
        <div v-if="camRunning" class="cam-hud">
          <el-tag type="success" effect="dark">{{ camFps }} FPS</el-tag>
          <el-tag type="warning" effect="dark">目标 {{ camDets.length }}</el-tag>
          <el-tag v-if="camLine" type="danger" effect="dark">进{{ cross.in }} 出{{ cross.out }}</el-tag>
          <el-tag v-if="alertEnabled && lastAlertTitle" type="danger" effect="dark">{{ lastAlertTitle }}</el-tag>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { ElMessage, ElNotification } from 'element-plus'
import { UploadFilled, VideoPlay, Refresh, Download, VideoCamera, SwitchButton } from '@element-plus/icons-vue'
import { modelApi, alertApi } from '../../../api/ai'
import {
  filterWorkbenchModels,
  ensureModelInList,
  categoriesFromModels,
} from '../../../utils/alertModels'

const ALERT_SOURCE_KEY = 'track-camera'

const allModels = ref([])
const modelId = ref(null)
const category = ref('')
const imgsz = ref(640)
const conf = ref(0.25)
const alertEnabled = ref(false)
const file = ref(null)
const previewUrl = ref('')   // 选中视频的原视频回放 URL
const lastAlertTitle = ref('')
const liveOverlay = ref(null)

const frameCanvas = ref(null)
const linePts = ref([])      // 像素点 [{x,y}...]（canvas 坐标）
const line = ref(null)       // 归一化 [x1,y1,x2,y2]
let frameW = 0
let frameH = 0

const running = ref(false)
const processed = ref(0)
const total = ref(0)
const resultUrl = ref('')
const stats = ref({})
let pollTimer = null
let blobUrl = ''

// 模式与摄像头状态
const mode = ref('file')
const devices = ref([])
const deviceId = ref('')
const camVideo = ref(null)
const camCanvas = ref(null)
const camRunning = ref(false)
const camDets = ref([])
const camFps = ref(0)
const camLine = ref(null)          // 归一化 [x1,y1,x2,y2]
const cross = ref({ in: 0, out: 0 })
const recBlobUrl = ref('')
let camStream = null, capCanvas = null, camBusy = false, camFirst = true
let frameCount = 0, fpsTimer = null, recorder = null, recChunks = []
let recUrl = null
const lastCentroid = {}
const counted = new Set()
const CAM_COLORS = ['#67c23a', '#409eff', '#e6a23c', '#f56c6c', '#9254de', '#13c2c2']

const categories = computed(() => categoriesFromModels(
  filterWorkbenchModels(allModels.value, { alertEnabled: alertEnabled.value, forTrack: true }),
))
const filteredModels = computed(() =>
  filterWorkbenchModels(allModels.value, {
    alertEnabled: alertEnabled.value,
    forTrack: true,
    category: category.value,
  }),
)

const syncModelSelection = () => {
  modelId.value = ensureModelInList(modelId.value, filteredModels.value)
}
const onCategoryChange = () => { syncModelSelection() }

watch(alertEnabled, () => {
  if (category.value && !categories.value.includes(category.value)) category.value = ''
  syncModelSelection()
})
watch(filteredModels, () => { syncModelSelection() }, { immediate: true })

const percent = computed(() => (total.value ? Math.min(100, Math.floor((processed.value / total.value) * 100)) : 0))
const classRows = computed(() =>
  Object.entries(stats.value.classCounts || {}).map(([name, count]) => ({ name, count })))

const loadModels = async () => {
  const res = await modelApi.list({ pageNum: 1, pageSize: 100 })
  allModels.value = (res.data.rows || []).filter(
    (m) => m.library === 'ultralytics' && m.task === 'object-detection' && m.filePath && m.status === '0')
  syncModelSelection()
}

const onPick = (uploadFile) => {
  const raw = uploadFile.raw
  if (!raw || !raw.type.startsWith('video/')) { ElMessage.error('请选择视频文件'); return }
  file.value = raw
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = URL.createObjectURL(raw)
  clearLine()
  clearOutput()
  drawFirstFrame(raw)
}

const clearOutput = () => {
  if (blobUrl) { URL.revokeObjectURL(blobUrl); blobUrl = '' }
  resultUrl.value = ''
  stats.value = {}
}

const drawFirstFrame = (raw) => {
  const url = URL.createObjectURL(raw)
  const v = document.createElement('video')
  v.preload = 'auto'
  v.muted = true
  v.src = url
  v.addEventListener('loadeddata', () => {
    v.currentTime = 0
  })
  v.addEventListener('seeked', async () => {
    frameW = v.videoWidth
    frameH = v.videoHeight
    await nextTick()
    const cv = frameCanvas.value
    if (!cv) return
    // 显示宽度上限 640，等比
    const dispW = Math.min(640, frameW)
    const scale = dispW / frameW
    cv.width = dispW
    cv.height = Math.round(frameH * scale)
    const ctx = cv.getContext('2d')
    ctx.drawImage(v, 0, 0, cv.width, cv.height)
    URL.revokeObjectURL(url)
  })
}

const redraw = () => {
  const cv = frameCanvas.value
  if (!cv) return
  const ctx = cv.getContext('2d')
  // 重画底图需重新抽帧太重，这里只在已绘制基础上叠加点/线
  if (linePts.value.length) {
    ctx.fillStyle = '#ff1744'
    linePts.value.forEach((p) => { ctx.beginPath(); ctx.arc(p.x, p.y, 4, 0, Math.PI * 2); ctx.fill() })
    if (linePts.value.length === 2) {
      ctx.strokeStyle = '#ff1744'
      ctx.lineWidth = 2
      ctx.beginPath()
      ctx.moveTo(linePts.value[0].x, linePts.value[0].y)
      ctx.lineTo(linePts.value[1].x, linePts.value[1].y)
      ctx.stroke()
    }
  }
}

const onCanvasClick = (e) => {
  if (linePts.value.length >= 2) return
  const cv = frameCanvas.value
  const rect = cv.getBoundingClientRect()
  const x = (e.clientX - rect.left) * (cv.width / rect.width)
  const y = (e.clientY - rect.top) * (cv.height / rect.height)
  linePts.value.push({ x, y })
  redraw()
  if (linePts.value.length === 2) {
    line.value = [
      linePts.value[0].x / cv.width, linePts.value[0].y / cv.height,
      linePts.value[1].x / cv.width, linePts.value[1].y / cv.height,
    ]
  }
}

const clearLine = () => {
  linePts.value = []
  line.value = null
  if (file.value) drawFirstFrame(file.value)  // 重抽首帧清掉线
}

const run = async () => {
  running.value = true
  processed.value = 0
  total.value = 0
  clearOutput()
  try {
    const fd = new FormData()
    fd.append('file', file.value)
    fd.append('conf', conf.value)
    fd.append('imgsz', imgsz.value)
    if (line.value) fd.append('line', JSON.stringify(line.value))
    fd.append('alertEnabled', alertEnabled.value ? '1' : '0')
    const res = await modelApi.trackVideo(modelId.value, fd)
    const jobId = res.data.jobId
    await poll(jobId)
  } catch (e) {
    ElMessage.error('追踪启动失败')
    running.value = false
  }
}

const poll = (jobId) => new Promise((resolve) => {
  pollTimer = setInterval(async () => {
    try {
      const res = await modelApi.videoProgress(modelId.value, jobId)
      const d = res.data
      processed.value = d.processed
      total.value = d.total
      if (d.status === 'done') {
        clearInterval(pollTimer); pollTimer = null
        stats.value = d.stats
        // outputVideo 返回 Blob，用 createObjectURL 得到可播放 URL（与视频检测页一致）
        const blob = await modelApi.outputVideo(d.stats.output)
        blobUrl = URL.createObjectURL(blob)
        resultUrl.value = blobUrl
        running.value = false
        resolve()
      }
    } catch (e) {
      clearInterval(pollTimer); pollTimer = null
      ElMessage.error('追踪失败')
      running.value = false
      resolve()
    }
  }, 1000)
})

const download = () => {
  const a = document.createElement('a')
  a.href = resultUrl.value
  a.download = stats.value.output || 'track.mp4'
  a.click()
}

const clearAll = () => {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
  clearOutput()
  if (previewUrl.value) { URL.revokeObjectURL(previewUrl.value); previewUrl.value = '' }
  file.value = null
  clearLine()
  processed.value = 0
  total.value = 0
  running.value = false
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

const evaluateAlerts = async (detections, frameW, frameH) => {
  if (!alertEnabled.value) {
    liveOverlay.value = null
    return
  }
  if (!detections?.length) {
    liveOverlay.value = null
    return
  }
  try {
    const payload = {
      detections,
      sourceKey: ALERT_SOURCE_KEY,
      sourceType: 'camera',
      modelId: modelId.value,
      persist: true,
      frameWidth: frameW,
      frameHeight: frameH,
    }
    if (camLine.value) payload.line = camLine.value
    const res = await alertApi.evaluate(payload)
    const list = res.data?.triggered || []
    list.filter((t) => t.notify).forEach(notifyAlert)
    liveOverlay.value = res.data?.overlay || null
  } catch (_) {
    /* 告警失败不阻断追踪 */
  }
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
  ctx.fillStyle = style.fillColor || '#9254DE'
  ctx.fillRect(x, y, pw, ph)
  ctx.globalAlpha = 1
  ctx.strokeStyle = style.borderColor || style.fillColor || '#722ED1'
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
    ctx.fillStyle = style.triangleFill || '#FFFFFF'
    ctx.fill()
    ctx.strokeStyle = '#fff'
    ctx.lineWidth = 2
    ctx.stroke()
  }

  const titles = style.titleLines || []
  const subs = style.subtitleLines || []
  const lines = [...titles, ...subs]
  ctx.fillStyle = style.textColor || '#FFFFFF'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  const startY = y + Math.round(ph * (style.showTriangle === false ? 0.35 : 0.58))
  const step = Math.max(18, Math.round(ph * 0.14))
  lines.forEach((ln, i) => {
    ctx.font = `${i < titles.length ? 'bold ' : ''}${Math.max(14, Math.round(ph * 0.11))}px sans-serif`
    ctx.fillText(String(ln), cx, startY + i * step)
  })
  ctx.restore()
}

// 摄像头模式方法
const onModeChange = () => { if (camRunning.value) camStop() }

const enumCams = async () => {
  try {
    const list = await navigator.mediaDevices.enumerateDevices()
    devices.value = list.filter((d) => d.kind === 'videoinput')
      .map((d, i) => ({ deviceId: d.deviceId, label: d.label, idx: i + 1 }))
  } catch (e) { /* 授权前 label 可能为空 */ }
}

// JS 端口：与后端 _crosses 方向一致（prev 负侧->正侧=进+1，反向=出-1）
const segCross = (prev, curr, line) => {
  const orient = (ax, ay, bx, by, cx, cy) => (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
  const [x1, y1, x2, y2] = line
  const d1 = orient(x1, y1, x2, y2, prev[0], prev[1])
  const d2 = orient(x1, y1, x2, y2, curr[0], curr[1])
  const d3 = orient(prev[0], prev[1], curr[0], curr[1], x1, y1)
  const d4 = orient(prev[0], prev[1], curr[0], curr[1], x2, y2)
  if ((d1 > 0) !== (d2 > 0) && (d3 > 0) !== (d4 > 0)) return d1 < 0 ? 1 : -1
  return 0
}

const onCamClick = (e) => {
  if (!camRunning.value) return
  const cv = camCanvas.value
  const rect = cv.getBoundingClientRect()
  const x = (e.clientX - rect.left) * (cv.width / rect.width)
  const y = (e.clientY - rect.top) * (cv.height / rect.height)
  if (!cv._p0) {
    cv._p0 = [x, y]        // 第一点
    camLine.value = null
  } else {
    camLine.value = [cv._p0[0] / cv.width, cv._p0[1] / cv.height, x / cv.width, y / cv.height]  // 第二点 -> 归一化线
    cv._p0 = null
    cross.value = { in: 0, out: 0 }
    for (const k of Object.keys(lastCentroid)) delete lastCentroid[k]
    counted.clear()
  }
}

const clearCamLine = () => {
  camLine.value = null
  if (camCanvas.value) camCanvas.value._p0 = null
}

const camStart = async () => {
  try {
    const constraints = { video: deviceId.value ? { deviceId: { exact: deviceId.value } } : true, audio: false }
    camStream = await navigator.mediaDevices.getUserMedia(constraints)
  } catch (e) { ElMessage.error('无法访问摄像头，请检查设备与浏览器权限'); return }
  camVideo.value.srcObject = camStream
  await camVideo.value.play()
  await enumCams()
  const vw = camVideo.value.videoWidth, vh = camVideo.value.videoHeight
  const capW = Math.min(vw, 640), capH = Math.round((vh * capW) / vw)
  capCanvas = document.createElement('canvas'); capCanvas.width = capW; capCanvas.height = capH
  camCanvas.value.width = capW; camCanvas.value.height = capH
  camRunning.value = true; camFirst = true; frameCount = 0; camFps.value = 0
  cross.value = { in: 0, out: 0 }; counted.clear()
  if (recBlobUrl.value) { URL.revokeObjectURL(recUrl); recBlobUrl.value = '' }
  fpsTimer = setInterval(() => { camFps.value = frameCount; frameCount = 0 }, 1000)
  startRecording()
  camLoop()
}

const startRecording = () => {
  try {
    const mime = ['video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm']
      .find((t) => window.MediaRecorder && MediaRecorder.isTypeSupported(t))
    if (!mime) { ElMessage.warning('浏览器不支持录制，仅实时预览'); return }
    recChunks = []
    const stream = camCanvas.value.captureStream(15)
    recorder = new MediaRecorder(stream, { mimeType: mime })
    recorder.ondataavailable = (ev) => { if (ev.data && ev.data.size) recChunks.push(ev.data) }
    recorder.onstop = () => {
      if (!recChunks.length) return
      const blob = new Blob(recChunks, { type: 'video/webm' })
      if (recUrl) URL.revokeObjectURL(recUrl)
      recUrl = URL.createObjectURL(blob); recBlobUrl.value = recUrl
    }
    recorder.start()
  } catch (e) { ElMessage.warning('录制启动失败，仅实时预览') }
}

const camLoop = () => {
  if (!camRunning.value) return
  if (camBusy) { requestAnimationFrame(camLoop); return }
  camBusy = true
  const ctx = capCanvas.getContext('2d')
  ctx.drawImage(camVideo.value, 0, 0, capCanvas.width, capCanvas.height)
  capCanvas.toBlob(async (blob) => {
    if (!camRunning.value || !blob) { camBusy = false; return }
    try {
      const fd = new FormData()
      fd.append('file', blob, 'frame.jpg')
      fd.append('conf', conf.value)
      fd.append('reset', camFirst ? '1' : '0')
      camFirst = false
      const res = await modelApi.trackFrame(modelId.value, fd)
      camDets.value = res.data.detections
      updateCrossing(res.data.detections)
      await evaluateAlerts(res.data.detections, res.data.width || capCanvas.width, res.data.height || capCanvas.height)
      camDraw(res.data.detections, liveOverlay.value)
      frameCount++
    } catch (e) { /* 单帧失败忽略 */ } finally {
      camBusy = false
      if (camRunning.value) requestAnimationFrame(camLoop)
    }
  }, 'image/jpeg', 0.6)
}

const updateCrossing = (list) => {
  if (!camLine.value) return
  const cv = camCanvas.value
  const ln = [camLine.value[0] * cv.width, camLine.value[1] * cv.height,
              camLine.value[2] * cv.width, camLine.value[3] * cv.height]
  for (const d of list) {
    if (d.trackId == null) continue
    const cx = (d.bbox[0] + d.bbox[2]) / 2, cy = (d.bbox[1] + d.bbox[3]) / 2
    const prev = lastCentroid[d.trackId]
    if (prev) {
      const dir = segCross(prev, [cx, cy], ln)
      const key = `${d.trackId}:${dir}`
      if (dir !== 0 && !counted.has(key)) {
        counted.add(key)
        if (dir > 0) cross.value.in++; else cross.value.out++
      }
    }
    lastCentroid[d.trackId] = [cx, cy]
  }
}

const camDraw = (list, overlayStyle = null) => {
  const cv = camCanvas.value, ctx = cv.getContext('2d')
  ctx.clearRect(0, 0, cv.width, cv.height)
  ctx.drawImage(camVideo.value, 0, 0, cv.width, cv.height)  // 合成：底图+标注，供录制
  ctx.lineWidth = 2; ctx.font = '14px sans-serif'; ctx.textBaseline = 'top'
  list.forEach((d, i) => {
    const [x1, y1, x2, y2] = d.bbox
    const color = CAM_COLORS[(d.trackId ?? i) % CAM_COLORS.length]
    ctx.strokeStyle = color
    ctx.strokeRect(x1, y1, x2 - x1, y2 - y1)
    const label = `${d.trackId != null ? 'ID' + d.trackId + ' ' : ''}${d.className}`
    const tw = ctx.measureText(label).width + 8
    ctx.fillStyle = color; ctx.fillRect(x1, Math.max(0, y1 - 18), tw, 18)
    ctx.fillStyle = '#fff'; ctx.fillText(label, x1 + 4, Math.max(0, y1 - 17))
  })
  if (camLine.value) {
    const ln = [camLine.value[0] * cv.width, camLine.value[1] * cv.height,
                camLine.value[2] * cv.width, camLine.value[3] * cv.height]
    ctx.strokeStyle = '#ff1744'; ctx.lineWidth = 3
    ctx.beginPath(); ctx.moveTo(ln[0], ln[1]); ctx.lineTo(ln[2], ln[3]); ctx.stroke()
  }
  if (alertEnabled.value && overlayStyle) {
    drawAlertOverlay(ctx, cv, overlayStyle)
  }
}

const camStop = async () => {
  camRunning.value = false
  if (fpsTimer) { clearInterval(fpsTimer); fpsTimer = null }
  if (recorder && recorder.state !== 'inactive') recorder.stop()
  recorder = null
  if (camStream) { camStream.getTracks().forEach((t) => t.stop()); camStream = null }
  if (camVideo.value) camVideo.value.srcObject = null
  if (camCanvas.value) {
    const ctx = camCanvas.value.getContext('2d')
    ctx.clearRect(0, 0, camCanvas.value.width, camCanvas.value.height)
  }
  camDets.value = []; camFps.value = 0
  lastAlertTitle.value = ''
  liveOverlay.value = null
  try {
    await alertApi.resetRuntime({ sourceKey: ALERT_SOURCE_KEY })
  } catch (_) { /* ignore */ }
}

const downloadRec = () => {
  const a = document.createElement('a')
  a.href = recBlobUrl.value; a.download = `track_cam_${Date.now()}.webm`; a.click()
}

onMounted(async () => {
  await loadModels()
  await enumCams()
})
onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer)
  if (blobUrl) URL.revokeObjectURL(blobUrl)
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  camStop()
  if (recUrl) URL.revokeObjectURL(recUrl)
})
</script>

<style scoped>
.cfg-card { margin-bottom: 12px; }
.hint, .line-tip { font-size: 13px; color: #5a6b87; margin-top: 8px; }
.alert-tip { margin-top: 8px; }
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
.preview-title { font-weight: 600; color: #3a4a63; margin-bottom: 10px; }
.meta { margin-left: 10px; color: #67c23a; }
.frame-box { margin-top: 10px; }
.frame-canvas { max-width: 100%; border: 1px solid #e4e7ed; border-radius: 6px; cursor: crosshair; }
.progress-box { padding: 22px 4px; }
.progress-title { font-weight: 600; color: #3a4a63; margin-bottom: 12px; }
.res-title { display: flex; align-items: center; gap: 12px; font-weight: 600; color: #3a4a63; margin-bottom: 12px; }
.player { width: 100%; max-height: 480px; background: #000; border-radius: 6px; }
.stats { display: flex; gap: 10px; margin: 12px 0; }
.cls-table { margin-top: 8px; max-width: 400px; }
.cam-wrap { margin-top: 8px; }
.cam-stage { position: relative; background: #0c1733; border-radius: 8px; aspect-ratio: 16/9; overflow: hidden; }
.cam-video { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; }
.cam-canvas { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; cursor: crosshair; }
.cam-hint { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; color: #8aa0c8; }
.cam-hud { position: absolute; top: 10px; left: 10px; display: flex; gap: 8px; }
</style>
