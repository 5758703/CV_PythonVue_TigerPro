<template>
  <div>
    <el-card shadow="never" class="cfg-card">
      <el-form :inline="true" class="cfg-form general-config-form">
        <el-form-item label="模式">
          <el-select v-model="mode" style="width: 140px" :disabled="camRunning" @change="onModeChange">
            <el-option label="视频文件" value="file" />
            <el-option label="本地摄像头" value="local" />
            <el-option label="网络摄像头" value="network" />
          </el-select>
        </el-form-item>
        <el-form-item label="模型分类">
          <el-select v-model="category" placeholder="全部分类" clearable style="width: 150px" @change="onCategoryChange">
            <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="检测模型">
          <el-select v-model="modelId" placeholder="自动选择推荐模型" style="width: 240px" filterable>
            <el-option v-for="m in filteredModels" :key="m.id"
                       :label="modelOptionLabel(m)" :value="m.id" />
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
        <el-form-item label="统计类别">
          <el-select v-model="classPreset" style="width: 140px" :disabled="camRunning || running">
            <el-option label="全部" value="all" />
            <el-option label="仅人" value="person" />
            <el-option label="仅车" value="vehicle" />
            <el-option label="人+车" value="person_vehicle" />
          </el-select>
        </el-form-item>
        <el-form-item label="计数方式">
          <el-select v-model="countMode" style="width: 140px" :disabled="camRunning || running" @change="onCountModeChange">
            <el-option label="多边形区域" value="zone" />
            <el-option label="计数线" value="line" />
            <el-option label="不计数" value="none" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="countMode==='zone'" label="边框色">
          <el-color-picker v-model="zoneBorderColor" :disabled="running" />
        </el-form-item>
        <el-form-item v-if="countMode==='zone'" label="填充色">
          <el-color-picker v-model="zoneFillColor" show-alpha :disabled="running" />
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
        <el-form-item v-if="mode==='local'" label="摄像头">
          <el-select v-model="deviceId" placeholder="默认摄像头" style="width: 180px" :disabled="camRunning">
            <el-option v-for="d in devices" :key="d.deviceId" :label="d.label || `摄像头 ${d.idx}`" :value="d.deviceId" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="mode==='network'" label="网络摄像头">
          <el-select
            v-model="cameraId"
            placeholder="选择网络摄像头"
            filterable
            clearable
            style="width: 220px"
            :disabled="camRunning"
            :loading="camerasLoading"
          >
            <el-option v-for="c in managedCameras" :key="c.id" :label="cameraLabel(c)" :value="c.id" />
          </el-select>
          <el-button link type="primary" :disabled="camRunning" @click="loadManagedCameras">刷新</el-button>
        </el-form-item>
        <el-form-item v-if="mode!=='file'" class="alert-action-item">
          <div class="alert-action-row">
            <el-button
              v-if="!camRunning"
              type="primary"
              :icon="VideoCamera"
              :disabled="!modelId || (mode==='network' && !cameraId)"
              @click="camStart"
            >开始</el-button>
            <el-button v-else type="danger" :icon="SwitchButton" @click="camStop">停止</el-button>
            <el-checkbox v-model="alertEnabled" :disabled="camRunning" style="margin-left: 12px">启用告警</el-checkbox>
            <el-alert
              v-if="alertEnabled && allModels.length && filteredModels.length"
              type="info"
              :closable="false"
              show-icon
              class="alert-tip-inline"
              title="总开关已开：仅「检测告警」页中已启用的规则会生效；画警戒线/多边形后可触发越线或区域越界。单项开关请到检测告警页配置。"
            />
            <el-button v-if="camLine" link type="primary" @click="clearCamLine">清除线</el-button>
            <el-button v-if="camRegion" link type="primary" @click="clearCamRegion">清除区域</el-button>
            <el-button v-if="countMode==='zone' && camRegionPts.length >= 3 && !camRegion" link type="success" @click="finishCamRegion">闭合区域</el-button>
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
        <template v-if="countMode==='zone'">TrackZone 区域：点 ≥3 点绘制多边形并闭合；仅框面积 ≥30% 进入区域才计进出。可自定义边框色/填充色。</template>
        <template v-else-if="countMode==='line'">越线计数：在下方首帧点两点画线。</template>
        <template v-else">仅追踪目标，不做进出统计。</template>
      </div>
    </el-card>

    <el-card v-if="mode==='file' && previewUrl" shadow="never" class="cfg-card">
      <div class="preview-title">原视频预览</div>
      <video :src="previewUrl" controls class="player" />
    </el-card>

    <el-card v-if="mode==='file' && file && countMode!=='none'" shadow="never" class="cfg-card">
      <div class="line-tip">
        <template v-if="countMode==='zone'">
          绘制多边形：依次点击添加顶点（≥3），完成后点「闭合区域」。
          <el-button link type="success" :disabled="regionPts.length < 3" @click="finishRegion">闭合区域</el-button>
          <el-button link type="primary" @click="clearRegion">清除区域</el-button>
          <span v-if="region" class="meta">已设置监控区域（{{ region.length }} 点）</span>
          <span v-else-if="regionPts.length" class="meta">已点 {{ regionPts.length }} 个顶点</span>
        </template>
        <template v-else>
          首帧画线：点第一点 → 点第二点。
          <el-button link type="primary" @click="clearLine">清除线</el-button>
          <span v-if="line" class="meta">已设置计数线</span>
        </template>
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
            {{ stats.regionEnabled ? '区域' : '越线' }}
            进:{{ stats.crossing.in }} 出:{{ stats.crossing.out }}
            净:{{ stats.crossing.net != null ? stats.crossing.net : (stats.crossing.in - stats.crossing.out) }}
          </el-tag>
          <el-tag v-if="stats.crossing?.person" type="success" effect="plain">
            人 进{{ stats.crossing.person.in }} 出{{ stats.crossing.person.out }}
          </el-tag>
          <el-tag v-if="stats.crossing?.vehicle" type="primary" effect="plain">
            车 进{{ stats.crossing.vehicle.in }} 出{{ stats.crossing.vehicle.out }}
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

    <div v-if="mode!=='file'" class="cam-wrap">
      <div class="cam-stage">
        <video v-show="mode==='local'" ref="camVideo" class="cam-video" autoplay playsinline muted></video>
        <img v-show="mode==='network'" ref="streamImg" class="cam-video" alt="网络摄像头画面" />
        <canvas ref="camCanvas" class="cam-canvas" @click="onCamClick"></canvas>
        <div v-if="!camRunning" class="cam-hint">
          <template v-if="countMode==='zone'">
            {{ mode === 'network' ? '选择网络摄像头后点「开始」；画面点 ≥3 点后点「闭合区域」' : '点「开始」后在画面点 ≥3 点绘制监控区域，再点「闭合区域」' }}
          </template>
          <template v-else-if="countMode==='line'">
            {{ mode === 'network' ? '选择网络摄像头后点「开始」；可在画面点两点画计数线' : '点「开始」启用本地摄像头；可在画面点两点画计数线' }}
          </template>
          <template v-else>
            {{ mode === 'network' ? '选择网络摄像头后点「开始」' : '点「开始」启用本地摄像头' }}
          </template>
        </div>
        <div v-if="camRunning" class="cam-hud">
          <el-tag type="success" effect="dark">{{ camFps }} FPS</el-tag>
          <el-tag type="warning" effect="dark">目标 {{ camDets.length }}</el-tag>
          <el-tag v-if="camLine || camRegion" type="danger" effect="dark">进{{ cross.in }} 出{{ cross.out }}</el-tag>
          <el-tag v-if="cross.person" type="success" effect="plain">人 {{ cross.person.in }}/{{ cross.person.out }}</el-tag>
          <el-tag v-if="cross.vehicle" type="primary" effect="plain">车 {{ cross.vehicle.in }}/{{ cross.vehicle.out }}</el-tag>
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
import { modelApi, alertApi } from '../../../../api/ai'
import { cameraApi } from '../../../../api/camera'
import {
  filterWorkbenchModels,
  ensureModelInList,
  categoriesFromModels,
} from '../../../../utils/alertModels'
import { recommendedModelId } from '../../../../utils/trackModelRecommendation'

const ALERT_SOURCE_KEY = 'track-camera'

const allModels = ref([])
const modelId = ref(null)
const category = ref('')
const imgsz = ref(640)
const conf = ref(0.25)
const classPreset = ref('person_vehicle')
const countMode = ref('zone')  // zone | line | none
const zoneBorderColor = ref('#2196f3')
const zoneFillColor = ref('rgba(33, 150, 243, 0.12)')
const alertEnabled = ref(false)
const file = ref(null)
const previewUrl = ref('')   // 选中视频的原视频回放 URL
const lastAlertTitle = ref('')
const liveOverlay = ref(null)

const frameCanvas = ref(null)
const linePts = ref([])      // 像素点 [{x,y}...]（canvas 坐标）
const line = ref(null)       // 归一化 [x1,y1,x2,y2]
const regionPts = ref([])    // 多边形顶点（canvas 坐标）
const region = ref(null)     // 归一化 [[x,y],...]
let frameBaseImage = null    // ImageData 用于重绘
let frameW = 0
let frameH = 0

const running = ref(false)
const processed = ref(0)
const total = ref(0)
const resultUrl = ref('')
const stats = ref({})
let pollTimer = null
let blobUrl = ''

// 模式与摄像头状态（file / local / network）
const mode = ref('file')
const devices = ref([])
const deviceId = ref('')
const cameraId = ref(null)
const managedCameras = ref([])
const camerasLoading = ref(false)
const camVideo = ref(null)
const streamImg = ref(null)
const camCanvas = ref(null)
const camRunning = ref(false)
const camDets = ref([])
const camFps = ref(0)
const camLine = ref(null)          // 归一化 [x1,y1,x2,y2]
const camRegionPts = ref([])       // 绘制中的多边形顶点（canvas）
const camRegion = ref(null)        // 归一化多边形
const zoneOcc = ref({ person: 0, vehicle: 0 })  // 框内累计：人/车
const cross = ref({ in: 0, out: 0, person: { in: 0, out: 0 }, vehicle: { in: 0, out: 0 } })
const recBlobUrl = ref('')
let camStream = null, capCanvas = null, camBusy = false, camFirst = true
let frameCount = 0, fpsTimer = null, recorder = null, recChunks = []
let recUrl = null
let streamReady = false
let loopTimer = null
const lastCentroid = {}
const lastInside = {}
const counted = new Set()
const CAM_COLORS = ['#67c23a', '#409eff', '#e6a23c', '#f56c6c', '#9254de', '#13c2c2']
const PERSON_NAMES = new Set(['person', 'people', 'human', 'pedestrian', '人', '行人'])
const VEHICLE_NAMES = new Set(['bicycle', 'car', 'motorcycle', 'bus', 'truck', '自行车', '汽车', '摩托车', '公交车', '卡车', '车辆'])

const emptyCross = () => ({ in: 0, out: 0, person: { in: 0, out: 0 }, vehicle: { in: 0, out: 0 } })
const classGroupOf = (name) => {
  const n = String(name || '').toLowerCase()
  if (PERSON_NAMES.has(n)) return 'person'
  if (VEHICLE_NAMES.has(n)) return 'vehicle'
  return 'other'
}

/** 将 #RGB/#RRGGBB/#RRGGBBAA / rgb/rgba 转为 canvas 可用色 */
const toCssColor = (raw, fallback = '#2196f3') => {
  if (!raw) return fallback
  return String(raw)
}
const withAlpha = (raw, alpha = 0.12) => {
  const s = String(raw || '').trim()
  if (!s) return `rgba(33, 150, 243, ${alpha})`
  if (s.startsWith('rgba(') || s.startsWith('rgb(')) return s
  let h = s.startsWith('#') ? s.slice(1) : s
  if (h.length === 3) h = h.split('').map((c) => c + c).join('')
  if (h.length === 8) {
    const a = parseInt(h.slice(6, 8), 16) / 255
    h = h.slice(0, 6)
    const r = parseInt(h.slice(0, 2), 16)
    const g = parseInt(h.slice(2, 4), 16)
    const b = parseInt(h.slice(4, 6), 16)
    return `rgba(${r}, ${g}, ${b}, ${Number.isFinite(a) ? a : alpha})`
  }
  if (h.length !== 6) return s
  const r = parseInt(h.slice(0, 2), 16)
  const g = parseInt(h.slice(2, 4), 16)
  const b = parseInt(h.slice(4, 6), 16)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}
const zoneStylePayload = () => ({
  borderColor: zoneBorderColor.value,
  fillColor: zoneFillColor.value,
})

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
  const currentValid = modelId.value != null && filteredModels.value.some((m) => m.id === modelId.value)
  modelId.value = currentValid
    ? modelId.value
    : (recommendedModelId(filteredModels.value, 'general') ?? ensureModelInList(null, filteredModels.value))
}
const modelOptionLabel = (m) => {
  const recommended = m.id === recommendedModelId(filteredModels.value, 'general') ? ' · 推荐' : ''
  return `${m.modelName}${recommended}（${m.category || '未分类'}）`
}
const onCategoryChange = () => { syncModelSelection() }

watch(alertEnabled, () => {
  if (category.value && !categories.value.includes(category.value)) category.value = ''
  syncModelSelection()
})
watch(filteredModels, () => { syncModelSelection() }, { immediate: true })
watch([zoneBorderColor, zoneFillColor], () => {
  if (countMode.value === 'zone') redraw()
})

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
  clearRegion()
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
    const dispW = Math.min(640, frameW)
    const scale = dispW / frameW
    cv.width = dispW
    cv.height = Math.round(frameH * scale)
    const ctx = cv.getContext('2d')
    ctx.drawImage(v, 0, 0, cv.width, cv.height)
    frameBaseImage = ctx.getImageData(0, 0, cv.width, cv.height)
    URL.revokeObjectURL(url)
    redraw()
  })
}

const redraw = () => {
  const cv = frameCanvas.value
  if (!cv) return
  const ctx = cv.getContext('2d')
  if (frameBaseImage) ctx.putImageData(frameBaseImage, 0, 0)

  if (countMode.value === 'line' && linePts.value.length) {
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

  const pts = region.value
    ? region.value.map((p) => ({ x: p[0] * cv.width, y: p[1] * cv.height }))
    : regionPts.value
  if (countMode.value === 'zone' && pts.length) {
    const border = toCssColor(zoneBorderColor.value)
    const fill = withAlpha(zoneFillColor.value)
    ctx.fillStyle = border
    pts.forEach((p) => { ctx.beginPath(); ctx.arc(p.x, p.y, 4, 0, Math.PI * 2); ctx.fill() })
    ctx.strokeStyle = border
    ctx.lineWidth = 2
    ctx.beginPath()
    ctx.moveTo(pts[0].x, pts[0].y)
    for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i].x, pts[i].y)
    if (region.value) ctx.closePath()
    ctx.stroke()
    if (region.value) {
      ctx.fillStyle = fill
      ctx.fill()
    }
  }
}

const canvasPoint = (e, cv) => {
  const rect = cv.getBoundingClientRect()
  return {
    x: (e.clientX - rect.left) * (cv.width / rect.width),
    y: (e.clientY - rect.top) * (cv.height / rect.height),
  }
}

const onCanvasClick = (e) => {
  const cv = frameCanvas.value
  if (!cv) return
  const { x, y } = canvasPoint(e, cv)
  if (countMode.value === 'line') {
    if (linePts.value.length >= 2) return
    linePts.value.push({ x, y })
    redraw()
    if (linePts.value.length === 2) {
      line.value = [
        linePts.value[0].x / cv.width, linePts.value[0].y / cv.height,
        linePts.value[1].x / cv.width, linePts.value[1].y / cv.height,
      ]
    }
    return
  }
  if (countMode.value === 'zone') {
    if (region.value) return
    regionPts.value.push({ x, y })
    redraw()
  }
}

const clearLine = () => {
  linePts.value = []
  line.value = null
  redraw()
  if (!frameBaseImage && file.value) drawFirstFrame(file.value)
}

const clearRegion = () => {
  regionPts.value = []
  region.value = null
  redraw()
  if (!frameBaseImage && file.value) drawFirstFrame(file.value)
}

const finishRegion = () => {
  const cv = frameCanvas.value
  if (!cv || regionPts.value.length < 3) {
    ElMessage.warning('请至少点击 3 个点')
    return
  }
  region.value = regionPts.value.map((p) => [
    p.x / cv.width, p.y / cv.height,
  ])
  regionPts.value = []
  redraw()
  ElMessage.success('监控区域已设置')
}

const onCountModeChange = () => {
  clearLine()
  clearRegion()
  clearCamLine()
  clearCamRegion()
  if (file.value && countMode.value !== 'none') drawFirstFrame(file.value)
}

const run = async () => {
  if (countMode.value === 'zone' && !region.value) {
    ElMessage.warning('请先绘制并闭合多边形监控区域')
    return
  }
  running.value = true
  processed.value = 0
  total.value = 0
  clearOutput()
  try {
    const fd = new FormData()
    fd.append('file', file.value)
    fd.append('conf', conf.value)
    fd.append('imgsz', imgsz.value)
    fd.append('classPreset', classPreset.value)
    if (countMode.value === 'line' && line.value) fd.append('line', JSON.stringify(line.value))
    if (countMode.value === 'zone' && region.value) {
      fd.append('region', JSON.stringify(region.value))
      fd.append('zoneStyle', JSON.stringify(zoneStylePayload()))
    }
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
  clearRegion()
  frameBaseImage = null
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
    if (camRegion.value) payload.region = camRegion.value
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

const cameraLabel = (c) => `${c.name || `摄像头#${c.id}`}${c.status === '0' ? '' : '（停用）'}`

const loadManagedCameras = async () => {
  camerasLoading.value = true
  try {
    const res = await cameraApi.list({ pageNum: 1, pageSize: 200, status: '0' })
    managedCameras.value = res.data.rows || []
  } catch (_) {
    ElMessage.error('加载网络摄像头失败')
  } finally {
    camerasLoading.value = false
  }
}

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

const pointInPoly = (pt, poly) => {
  // ray casting
  let inside = false
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const xi = poly[i][0], yi = poly[i][1]
    const xj = poly[j][0], yj = poly[j][1]
    const intersect = ((yi > pt[1]) !== (yj > pt[1]))
      && (pt[0] < (xj - xi) * (pt[1] - yi) / ((yj - yi) || 1e-9) + xi)
    if (intersect) inside = !inside
  }
  return inside
}

/** 检测框与多边形重叠面积比（采样近似），≥0.3 才算有效进入 */
const AREA_RATIO = 0.3
const bboxZoneOverlapRatio = (bbox, poly, samples = 8) => {
  const [x1, y1, x2, y2] = bbox
  const w = x2 - x1, h = y2 - y1
  if (w <= 0 || h <= 0) return 0
  let hit = 0, total = 0
  for (let i = 0; i < samples; i++) {
    for (let j = 0; j < samples; j++) {
      const px = x1 + ((i + 0.5) / samples) * w
      const py = y1 + ((j + 0.5) / samples) * h
      total++
      if (pointInPoly([px, py], poly)) hit++
    }
  }
  return hit / total
}
const isEffectivelyInside = (bbox, poly) => bboxZoneOverlapRatio(bbox, poly) >= AREA_RATIO

const resetCrossState = () => {
  cross.value = emptyCross()
  zoneOcc.value = { person: 0, vehicle: 0 }
  for (const k of Object.keys(lastCentroid)) delete lastCentroid[k]
  for (const k of Object.keys(lastInside)) delete lastInside[k]
  counted.clear()
}

const onCamClick = (e) => {
  if (!camRunning.value || countMode.value === 'none') return
  const cv = camCanvas.value
  const { x, y } = canvasPoint(e, cv)

  if (countMode.value === 'line') {
    if (!cv._p0) {
      cv._p0 = [x, y]
      camLine.value = null
    } else {
      camLine.value = [cv._p0[0] / cv.width, cv._p0[1] / cv.height, x / cv.width, y / cv.height]
      cv._p0 = null
      resetCrossState()
    }
    return
  }

  if (countMode.value === 'zone') {
    if (camRegion.value) return
    camRegionPts.value.push({ x, y })
  }
}

const clearCamLine = () => {
  camLine.value = null
  if (camCanvas.value) camCanvas.value._p0 = null
}

const clearCamRegion = () => {
  camRegion.value = null
  camRegionPts.value = []
  resetCrossState()
}

const finishCamRegion = () => {
  const cv = camCanvas.value
  if (!cv || camRegionPts.value.length < 3) {
    ElMessage.warning('请至少点击 3 个点')
    return
  }
  camRegion.value = camRegionPts.value.map((p) => [p.x / cv.width, p.y / cv.height])
  camRegionPts.value = []
  resetCrossState()
  ElMessage.success('监控区域已设置')
}

const waitForImgReady = (img, timeoutMs = 12000) => new Promise((resolve, reject) => {
  if (!img) {
    reject(new Error('no img'))
    return
  }
  if (img.naturalWidth > 0) {
    resolve(true)
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
    if (ok) resolve(true)
    else reject(err || new Error('ready'))
  }
  const onLoad = () => finish(true)
  const onError = () => finish(false, new Error('load'))
  const poll = setInterval(() => {
    if (img.naturalWidth > 0) finish(true)
    else if (Date.now() - started > timeoutMs) finish(false, new Error('timeout'))
  }, 200)
  const timer = setTimeout(() => finish(false, new Error('timeout')), timeoutMs)
  img.addEventListener('load', onLoad)
  img.addEventListener('error', onError)
})

const getFrameSource = () => {
  if (mode.value === 'network') {
    const img = streamImg.value
    return { el: img, w: img?.naturalWidth || 0, h: img?.naturalHeight || 0 }
  }
  const video = camVideo.value
  return { el: video, w: video?.videoWidth || 0, h: video?.videoHeight || 0 }
}

const setupCapCanvas = (vw, vh) => {
  const capW = Math.min(vw || 640, 640)
  const capH = Math.round(((vh || 480) * capW) / (vw || 640))
  capCanvas = document.createElement('canvas')
  capCanvas.width = capW
  capCanvas.height = capH
  camCanvas.value.width = capW
  camCanvas.value.height = capH
}

const scheduleLoop = (delayMs = 0) => {
  if (!camRunning.value) return
  if (loopTimer) clearTimeout(loopTimer)
  loopTimer = setTimeout(() => {
    loopTimer = null
    camLoop()
  }, delayMs)
}

const camStart = async () => {
  camFirst = true
  resetCrossState()
  if (recBlobUrl.value) { URL.revokeObjectURL(recUrl); recBlobUrl.value = '' }

  if (mode.value === 'network') {
    if (!cameraId.value) {
      ElMessage.warning('请选择网络摄像头')
      return
    }
    camRunning.value = true
    streamReady = false
    await nextTick()
    const img = streamImg.value
    if (!img) {
      camRunning.value = false
      return
    }
    img.removeAttribute('crossorigin')
    img.src = cameraApi.streamUrl(cameraId.value, String(Date.now()), false, true)
    try {
      await waitForImgReady(img)
      streamReady = true
    } catch (_) {
      ElMessage.error('无法连接网络摄像头')
      img.removeAttribute('src')
      camRunning.value = false
      return
    }
    setupCapCanvas(img.naturalWidth, img.naturalHeight)
    frameCount = 0
    camFps.value = 0
    fpsTimer = setInterval(() => { camFps.value = frameCount; frameCount = 0 }, 1000)
    startRecording()
    scheduleLoop(80)
    return
  }

  try {
    const constraints = { video: deviceId.value ? { deviceId: { exact: deviceId.value } } : true, audio: false }
    camStream = await navigator.mediaDevices.getUserMedia(constraints)
  } catch (e) { ElMessage.error('无法访问摄像头，请检查设备与浏览器权限'); return }
  camVideo.value.srcObject = camStream
  await camVideo.value.play()
  await enumCams()
  setupCapCanvas(camVideo.value.videoWidth, camVideo.value.videoHeight)
  camRunning.value = true
  frameCount = 0
  camFps.value = 0
  fpsTimer = setInterval(() => { camFps.value = frameCount; frameCount = 0 }, 1000)
  startRecording()
  scheduleLoop(0)
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
  if (camBusy) {
    scheduleLoop(mode.value === 'network' ? 80 : 0)
    return
  }
  const { el, w, h } = getFrameSource()
  if (!el || !w || !h || !capCanvas) {
    scheduleLoop(mode.value === 'network' ? 80 : 16)
    return
  }
  if (mode.value === 'network' && !streamReady) {
    scheduleLoop(80)
    return
  }
  camBusy = true
  const ctx = capCanvas.getContext('2d')
  ctx.drawImage(el, 0, 0, capCanvas.width, capCanvas.height)
  capCanvas.toBlob(async (blob) => {
    if (!camRunning.value || !blob) { camBusy = false; scheduleLoop(mode.value === 'network' ? 80 : 0); return }
    try {
      const fd = new FormData()
      fd.append('file', blob, 'frame.jpg')
      fd.append('conf', conf.value)
      fd.append('imgsz', imgsz.value)
      fd.append('classPreset', classPreset.value)
      fd.append('reset', camFirst ? '1' : '0')
      if (countMode.value === 'zone' && camRegion.value) {
        fd.append('region', JSON.stringify(camRegion.value))
      }
      camFirst = false
      const res = await modelApi.trackFrame(modelId.value, fd)
      camDets.value = res.data.detections
      if (res.data.zoneCrossing) {
        const z = res.data.zoneCrossing
        cross.value = {
          in: z.in || 0,
          out: z.out || 0,
          person: z.person || { in: 0, out: 0 },
          vehicle: z.vehicle || { in: 0, out: 0 },
        }
        zoneOcc.value = {
          person: z.person?.in || 0,
          vehicle: z.vehicle?.in || 0,
        }
      } else if (res.data.zoneOccupancy) {
        zoneOcc.value = {
          person: res.data.zoneOccupancy.person || 0,
          vehicle: res.data.zoneOccupancy.vehicle || 0,
        }
        updateCrossing(res.data.detections)
      } else {
        updateCrossing(res.data.detections)
      }
      await evaluateAlerts(res.data.detections, res.data.width || capCanvas.width, res.data.height || capCanvas.height)
      camDraw(res.data.detections, liveOverlay.value)
      frameCount++
    } catch (e) { /* 单帧失败忽略 */ } finally {
      camBusy = false
      if (camRunning.value) scheduleLoop(mode.value === 'network' ? 80 : 0)
    }
  }, 'image/jpeg', 0.6)
}

const updateCrossing = (list) => {
  const cv = camCanvas.value
  if (!cv) return

  // 计数线模式（前端几何）
  if (countMode.value === 'line' && camLine.value) {
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
          const g = classGroupOf(d.className)
          if (dir > 0) {
            cross.value.in++
            if (cross.value[g]) cross.value[g].in++
          } else {
            cross.value.out++
            if (cross.value[g]) cross.value[g].out++
          }
        }
      }
      lastCentroid[d.trackId] = [cx, cy]
    }
    return
  }

  // 区域模式兜底（后端已统计时不会走到这里）
  if (countMode.value === 'zone' && camRegion.value) {
    const poly = camRegion.value.map((p) => [p[0] * cv.width, p[1] * cv.height])
    for (const d of list) {
      if (d.trackId == null) continue
      const inside = isEffectivelyInside(d.bbox, poly)
      const prevIn = lastInside[d.trackId]
      lastInside[d.trackId] = inside
      if (prevIn == null) continue
      let dir = 0
      if (!prevIn && inside) dir = 1
      else if (prevIn && !inside) dir = -1
      const key = `${d.trackId}:${dir}`
      if (dir !== 0 && !counted.has(key)) {
        counted.add(key)
        const g = classGroupOf(d.className)
        if (dir > 0) {
          cross.value.in++
          if (cross.value[g]) cross.value[g].in++
        } else {
          cross.value.out++
          if (cross.value[g]) cross.value[g].out++
        }
      }
    }
    zoneOcc.value = {
      person: cross.value.person?.in || 0,
      vehicle: cross.value.vehicle?.in || 0,
    }
  }
}

const camDraw = (list, overlayStyle = null) => {
  const cv = camCanvas.value, ctx = cv.getContext('2d')
  const { el } = getFrameSource()
  ctx.clearRect(0, 0, cv.width, cv.height)
  if (el) ctx.drawImage(el, 0, 0, cv.width, cv.height)
  ctx.lineWidth = 2; ctx.font = '14px sans-serif'; ctx.textBaseline = 'top'
  list.forEach((d, i) => {
    const [x1, y1, x2, y2] = d.bbox
    const alarm = d.alarm
    const color = alarm ? '#ff1744' : CAM_COLORS[(d.trackId ?? i) % CAM_COLORS.length]
    ctx.strokeStyle = color
    ctx.lineWidth = alarm ? 3 : 2
    ctx.strokeRect(x1, y1, x2 - x1, y2 - y1)
    const label = `${d.trackId != null ? 'ID' + d.trackId + ' ' : ''}${d.className}${alarm ? ' ' + alarm : ''}`
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
  const zonePts = camRegion.value
    ? camRegion.value.map((p) => ({ x: p[0] * cv.width, y: p[1] * cv.height }))
    : camRegionPts.value
  if (zonePts.length) {
    const border = toCssColor(zoneBorderColor.value)
    const fill = withAlpha(zoneFillColor.value)
    ctx.strokeStyle = border
    ctx.lineWidth = 2
    ctx.beginPath()
    ctx.moveTo(zonePts[0].x, zonePts[0].y)
    for (let i = 1; i < zonePts.length; i++) ctx.lineTo(zonePts[i].x, zonePts[i].y)
    if (camRegion.value) ctx.closePath()
    ctx.stroke()
    zonePts.forEach((p) => {
      ctx.fillStyle = border
      ctx.beginPath(); ctx.arc(p.x, p.y, 4, 0, Math.PI * 2); ctx.fill()
    })
    if (camRegion.value) {
      ctx.fillStyle = fill
      ctx.fill()
      // 多边形中心：人/车累计（为 0 不显示）；加粗并放大 5 倍，透明背景
      const labels = []
      if (zoneOcc.value.vehicle > 0) labels.push(`车：${zoneOcc.value.vehicle}`)
      if (zoneOcc.value.person > 0) labels.push(`人：${zoneOcc.value.person}`)
      if (labels.length) {
        const cx = zonePts.reduce((s, p) => s + p.x, 0) / zonePts.length
        const cy = zonePts.reduce((s, p) => s + p.y, 0) / zonePts.length
        let polyArea = 0
        for (let i = 0; i < zonePts.length; i++) {
          const a = zonePts[i], b = zonePts[(i + 1) % zonePts.length]
          polyArea += a.x * b.y - b.x * a.y
        }
        polyArea = Math.abs(polyArea) / 2
        const targetArea = Math.max(polyArea * 0.06, 1)
        const xs = zonePts.map((p) => p.x), ys = zonePts.map((p) => p.y)
        const bw = Math.max(...xs) - Math.min(...xs)
        const bh = Math.max(...ys) - Math.min(...ys)
        const fontFamily = '"Microsoft YaHei", "PingFang SC", sans-serif'
        const measure = (size) => {
          ctx.font = `bold ${size}px ${fontFamily}`
          const widths = labels.map((t) => ctx.measureText(t).width)
          const lineH = size * 1.15
          const gap = Math.max(4, size / 8)
          const tw = Math.max(...widths)
          const th = labels.length * lineH + gap * Math.max(0, labels.length - 1)
          return { tw, th, lineH, gap, widths }
        }
        let lo = 14, hi = Math.max(18, Math.floor(Math.min(bw, bh) * 0.22)), best = 14
        while (lo <= hi) {
          const mid = (lo + hi) >> 1
          const { tw, th } = measure(mid)
          if (tw * th <= targetArea) { best = mid; lo = mid + 1 }
          else hi = mid - 1
        }
        best = Math.min(Math.round(best * 2.5), Math.max(18, Math.floor(Math.min(bw, bh) * 0.95)))
        const { lineH, gap } = measure(best)
        const totalH = labels.length * lineH + gap * Math.max(0, labels.length - 1)
        ctx.textAlign = 'center'
        ctx.textBaseline = 'middle'
        const outline = Math.max(2, Math.floor(best / 18))
        labels.forEach((t, i) => {
          const ty = cy - totalH / 2 + i * (lineH + gap) + lineH / 2
          ctx.lineWidth = outline * 2
          ctx.strokeStyle = 'rgba(0,0,0,0.85)'
          ctx.strokeText(t, cx, ty)
          ctx.fillStyle = '#fff'
          ctx.fillText(t, cx, ty)
        })
        ctx.textAlign = 'left'
        ctx.textBaseline = 'top'
        ctx.font = '14px sans-serif'
      }
    }
  }
  if (alertEnabled.value && overlayStyle) {
    drawAlertOverlay(ctx, cv, overlayStyle)
  }
}

const camStop = async () => {
  camRunning.value = false
  streamReady = false
  if (loopTimer) { clearTimeout(loopTimer); loopTimer = null }
  if (fpsTimer) { clearInterval(fpsTimer); fpsTimer = null }
  if (recorder && recorder.state !== 'inactive') recorder.stop()
  recorder = null
  if (camStream) { camStream.getTracks().forEach((t) => t.stop()); camStream = null }
  if (camVideo.value) camVideo.value.srcObject = null
  if (streamImg.value) {
    streamImg.value.removeAttribute('src')
  }
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
  await loadManagedCameras()
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
