<template>
  <div>
    <el-card shadow="never" class="cfg-card">
      <el-form :inline="true">
        <el-form-item label="模式">
          <el-radio-group v-model="mode" @change="clearAll">
            <el-radio-button value="image">图片</el-radio-button>
            <el-radio-button value="camera">摄像头</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="姿态模型">
          <el-select v-model="modelId" placeholder="选择 pose 模型" style="width: 260px">
            <el-option v-for="m in modelOptions" :key="m.id" :label="modelLabel(m)" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="置信度">
          <el-slider v-model="conf" :min="0.05" :max="0.95" :step="0.05" style="width: 130px" />
        </el-form-item>
        <el-form-item label="记录事件">
          <el-switch v-model="persist" />
        </el-form-item>
        <el-form-item v-if="mode === 'image'">
          <el-upload :show-file-list="false" :auto-upload="false" :on-change="onPick" accept="image/*">
            <el-button :icon="UploadFilled">选择图片</el-button>
          </el-upload>
        </el-form-item>
        <el-form-item v-if="mode === 'image'">
          <el-button type="primary" :icon="VideoPlay" :loading="running" :disabled="!modelId || !file" @click="runImage">开始检测</el-button>
          <el-button :icon="Refresh" @click="clearAll">清空</el-button>
        </el-form-item>
        <el-form-item v-if="mode === 'camera'" label="摄像头">
          <el-select v-model="deviceId" placeholder="默认摄像头" style="width: 170px" :disabled="camRunning">
            <el-option v-for="d in devices" :key="d.deviceId" :label="d.label || `摄像头 ${d.idx}`" :value="d.deviceId" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="mode === 'camera'">
          <el-button v-if="!camRunning" type="primary" :icon="VideoPlay" :disabled="!modelId" @click="camStart">开始</el-button>
          <el-button v-else type="danger" :icon="Refresh" @click="camStop">停止</el-button>
        </el-form-item>
      </el-form>
      <el-alert v-if="!modelOptions.length" type="warning" :closable="false"
                title="暂无可用模型：请到「模型管理」拉取 YOLO-pose / RTMO / RTMPose 权重并启用。" />
      <el-alert type="info" :closable="false" class="tip-alert"
                title="四个阈值在「检测告警」页的「跌倒检测告警」规则中配置；该规则需先启用，本页才会判定与记事件。" />
    </el-card>

    <el-row :gutter="12">
      <el-col :span="16">
        <el-card shadow="never">
          <div v-if="mode === 'camera'" class="cam-wrap">
            <div class="cam-stage">
              <video ref="camVideo" class="cam-video" autoplay playsinline muted></video>
              <canvas ref="camCanvas" class="cam-canvas"></canvas>
              <div v-if="!camRunning" class="cam-hint">点「开始」启用摄像头，实时检测跌倒</div>
              <div v-if="camRunning" class="cam-hud">
                <el-tag type="success" effect="dark">{{ camFps }} FPS</el-tag>
                <el-tag type="warning" effect="dark">人数 {{ personCount }}</el-tag>
                <el-tag v-if="fallCount" type="danger" effect="dark">跌倒 {{ fallCount }}</el-tag>
              </div>
            </div>
          </div>
          <div v-else-if="resultImg">
            <div class="res-title">检测结果（{{ personCount }} 人，疑似跌倒 {{ fallCount }}）</div>
            <div class="cam-stage">
              <img ref="stillImg" :src="resultImg" class="cam-video" @load="drawStill" />
              <canvas ref="camCanvas" class="cam-canvas"></canvas>
            </div>
          </div>
          <el-empty v-else description="选择模型与图片后开始检测" />
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="never">
          <div class="res-title">触发记录</div>
          <el-empty v-if="!events.length" description="暂无触发" :image-size="60" />
          <el-timeline v-else>
            <el-timeline-item v-for="(e, i) in events" :key="i" :timestamp="e.time" type="danger">
              <div class="ev-title">{{ e.title }}</div>
              <div class="ev-msg">{{ e.message }}</div>
            </el-timeline-item>
          </el-timeline>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { UploadFilled, VideoPlay, Refresh } from '@element-plus/icons-vue'
import { modelApi, fallApi } from '../../../api/ai'

const POSE_TASKS = ['pose-estimation', 'wholebody-pose-estimation']
// COCO-17 骨架连接表（与姿态估计页一致）
const SKELETON = [
  [5, 7], [7, 9], [6, 8], [8, 10], [5, 6], [5, 11], [6, 12], [11, 12],
  [11, 13], [13, 15], [12, 14], [14, 16], [0, 1], [0, 2], [1, 3], [2, 4],
]
const KP_CONF = 0.3
// 摄像头模式与图片模式各用独立的 sourceKey：两者共享同一个 key 会导致
// assign_track_ids 把互不相干的人用 IoU 匹配成同一 trackId、站立基线用
// 上一张图的像素尺度当这张图的基线、质心速度用两次点击的墙钟间隔当 dt——
// 该间隔与真实运动完全无关，速度指标数值毫无意义（M-3）。
const SOURCE_KEY_CAMERA = 'fall-live'
const SOURCE_KEY_IMAGE = 'fall-image'

const mode = ref('image')
const modelOptions = ref([])
const modelId = ref(null)
const conf = ref(0.25)
const persist = ref(true)
const file = ref(null)
const running = ref(false)
const resultImg = ref('')
const personCount = ref(0)
const fallCount = ref(0)
const events = ref([])
const lastData = ref(null)

const devices = ref([])
const deviceId = ref('')
const camVideo = ref(null)
const camCanvas = ref(null)
const stillImg = ref(null)
const camRunning = ref(false)
const camFps = ref(0)
let camStream = null, capCanvas = null, camBusy = false
let frameCount = 0, fpsTimer = null

const modelLabel = (m) => `${m.modelName}（${m.library === 'rtmlib' ? 'rtmlib' : 'YOLO'}）`

const loadModels = async () => {
  try {
    const res = await modelApi.list({ pageNum: 1, pageSize: 100 })
    modelOptions.value = (res.data.rows || []).filter((m) => {
      if (m.status !== '0' || !POSE_TASKS.includes(m.task)) return false
      if (m.library === 'ultralytics') return !!m.filePath
      if (m.library === 'rtmlib') return m.filePath || /^(rtmo|rtmpose|dwpose)-/.test(m.modelKey || '')
      return false
    })
    if (modelOptions.value.length && !modelId.value) modelId.value = modelOptions.value[0].id
  } catch (e) {
    ElMessage.error('加载模型列表失败')
  }
}

const onPick = (uploadFile) => {
  file.value = uploadFile.raw
  if (resultImg.value) URL.revokeObjectURL(resultImg.value)
  resultImg.value = URL.createObjectURL(uploadFile.raw)
}

const applyData = (d) => {
  lastData.value = d
  personCount.value = d.count || 0
  fallCount.value = (d.detections || []).filter((x) => x.className === 'fall').length
  for (const t of d.triggered || []) {
    events.value.unshift({ time: new Date().toLocaleTimeString(), title: t.title, message: t.message })
  }
  if (events.value.length > 50) events.value.length = 50
}

const buildForm = (blob, name) => {
  const fd = new FormData()
  fd.append('file', blob, name)
  fd.append('modelId', modelId.value)
  fd.append('conf', conf.value)
  fd.append('sourceKey', mode.value === 'camera' ? SOURCE_KEY_CAMERA : SOURCE_KEY_IMAGE)
  fd.append('sourceType', mode.value === 'camera' ? 'camera' : 'image')
  fd.append('persist', persist.value ? '1' : '0')
  fd.append('draw', '0')
  return fd
}

const runImage = async () => {
  running.value = true
  try {
    // 图片模式每次检测前先重置该 sourceKey 的连续帧/冷却/跟踪状态：图片模式面向
    // 互不相干的独立照片，不应共享跨帧 trackId、站立基线与质心速度状态（M-3）。
    // 副作用：每次检测都是「无上一帧」的冷启动，质心速度指标恒不可用。
    await fallApi.resetRuntime({ sourceKey: SOURCE_KEY_IMAGE })
    const res = await fallApi.detect(buildForm(file.value, file.value.name))
    applyData(res.data)
    drawStill()
  } catch (e) {
    ElMessage.error(e.response?.data?.message || '跌倒检测失败')
  } finally {
    running.value = false
  }
}

const drawOverlay = (ctx, w, h) => {
  const d = lastData.value
  if (!d) return
  ctx.lineWidth = 2
  ctx.strokeStyle = '#00e5ff'
  for (const p of d.persons || []) {
    const kp = p.keypoints || []
    for (const [a, b] of SKELETON) {
      const pa = kp[a], pb = kp[b]
      if (!pa || !pb || pa[2] < KP_CONF || pb[2] < KP_CONF) continue
      ctx.beginPath(); ctx.moveTo(pa[0], pa[1]); ctx.lineTo(pb[0], pb[1]); ctx.stroke()
    }
  }
  for (const box of d.detections || []) {
    if (box.className !== 'fall') continue
    const [x1, y1, x2, y2] = box.bbox
    ctx.strokeStyle = '#ff2d2d'
    ctx.lineWidth = 3
    ctx.strokeRect(x1, y1, x2 - x1, y2 - y1)
    const ind = box.indicators || {}
    const lines = [
      `跌倒 ${(box.confidence * 100).toFixed(0)}%`,
      `角${ind.trunk ?? '-'} 速${ind.speed ?? '-'}`,
      `高${ind.height ?? '-'} 头${ind.head ?? '-'}`,
    ]
    ctx.font = '13px sans-serif'
    ctx.fillStyle = 'rgba(207,19,34,0.8)'
    ctx.fillRect(x1, Math.max(0, y1 - 52), 150, 50)
    ctx.fillStyle = '#fff'
    lines.forEach((ln, i) => ctx.fillText(ln, x1 + 5, Math.max(12, y1 - 38 + i * 16)))
  }
  if (d.overlay) {
    ctx.fillStyle = 'rgba(207,19,34,0.35)'
    ctx.fillRect(w * 0.14, h * 0.32, w * 0.72, h * 0.36)
    ctx.fillStyle = '#fff'
    ctx.font = `bold ${Math.round(w * 0.05)}px sans-serif`
    ctx.textAlign = 'center'
    ctx.fillText((d.overlay.titleLines || ['ALERT'])[0], w / 2, h * 0.5)
    ctx.textAlign = 'left'
  }
}

const drawStill = () => {
  const cv = camCanvas.value
  if (!cv || !lastData.value) return
  cv.width = lastData.value.width
  cv.height = lastData.value.height
  const ctx = cv.getContext('2d')
  ctx.clearRect(0, 0, cv.width, cv.height)
  drawOverlay(ctx, cv.width, cv.height)
}

const enumCams = async () => {
  try {
    const list = await navigator.mediaDevices.enumerateDevices()
    devices.value = list.filter((d) => d.kind === 'videoinput')
      .map((d, i) => ({ deviceId: d.deviceId, label: d.label, idx: i + 1 }))
  } catch (e) { /* 授权前 label 空 */ }
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
  camRunning.value = true; frameCount = 0; camFps.value = 0
  fpsTimer = setInterval(() => { camFps.value = frameCount; frameCount = 0 }, 1000)
  camLoop()
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
      const res = await fallApi.detect(buildForm(blob, 'frame.jpg'))
      applyData(res.data)
      const cv = camCanvas.value, c2 = cv.getContext('2d')
      c2.clearRect(0, 0, cv.width, cv.height)
      drawOverlay(c2, cv.width, cv.height)
      frameCount++
    } catch (e) { /* 单帧失败忽略 */ } finally {
      camBusy = false
      if (camRunning.value) requestAnimationFrame(camLoop)
    }
  }, 'image/jpeg', 0.6)
}

const camStop = async () => {
  camRunning.value = false
  if (fpsTimer) { clearInterval(fpsTimer); fpsTimer = null }
  if (camStream) { camStream.getTracks().forEach((t) => t.stop()); camStream = null }
  try { await fallApi.resetRuntime({ sourceKey: SOURCE_KEY_CAMERA }) } catch (e) { /* 忽略 */ }
}

const clearAll = () => {
  camStop()
  file.value = null
  if (resultImg.value) URL.revokeObjectURL(resultImg.value)
  resultImg.value = ''
  personCount.value = 0
  fallCount.value = 0
  lastData.value = null
  events.value = []
}

onMounted(() => {
  loadModels()
  enumCams()
})
onBeforeUnmount(() => { camStop() })
</script>

<style scoped>
.cfg-card { margin-bottom: 12px; }
.tip-alert { margin-top: 8px; }
.cam-wrap { display: flex; justify-content: center; }
.cam-stage { position: relative; display: inline-block; }
.cam-video { display: block; max-width: 100%; max-height: 480px; }
.cam-canvas { position: absolute; left: 0; top: 0; width: 100%; height: 100%; }
.cam-hint { position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%); color: #909399; }
.cam-hud { position: absolute; left: 8px; top: 8px; display: flex; gap: 6px; }
.res-title { font-weight: 600; margin-bottom: 8px; }
.ev-title { font-weight: 600; color: #cf1322; }
.ev-msg { font-size: 12px; color: #606266; }
</style>
