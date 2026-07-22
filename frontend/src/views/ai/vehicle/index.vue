<template>
  <div>
    <el-card shadow="never" class="cfg-card">
      <el-form :inline="true" class="cfg-form">
        <el-form-item label="模式">
          <el-select
            v-model="mode"
            placeholder="选择输入源"
            style="width: 160px"
            :disabled="busy"
            @change="onModeChange"
          >
            <el-option label="图片识别" value="image" />
            <el-option label="视频文件" value="file" />
            <el-option label="本地摄像头" value="local" />
            <el-option label="网络摄像头" value="network" />
          </el-select>
        </el-form-item>
        <el-form-item label="车辆检测">
          <el-select v-model="detectId" placeholder="YOLO 车辆检测" style="width: 220px" filterable :disabled="busy">
            <el-option
              v-for="m in detectModels"
              :key="m.id"
              :label="modelOptionLabel(m, 'detect')"
              :value="m.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="车牌检测">
          <el-select v-model="plateId" placeholder="可选（推荐 YOLOv11）" clearable style="width: 200px" filterable :disabled="busy">
            <el-option
              v-for="m in plateModels"
              :key="m.id"
              :label="modelOptionLabel(m, 'plate')"
              :value="m.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="OCR 检测">
          <el-select v-model="detId" placeholder="RapidOCR det" clearable style="width: 180px" filterable :disabled="busy">
            <el-option
              v-for="m in detModels"
              :key="m.id"
              :label="modelOptionLabel(m, 'ocrDet')"
              :value="m.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="OCR 识别">
          <el-select v-model="recId" placeholder="RapidOCR rec" clearable style="width: 180px" filterable :disabled="busy">
            <el-option
              v-for="m in recModels"
              :key="m.id"
              :label="modelOptionLabel(m, 'ocrRec')"
              :value="m.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="置信度">
          <el-slider v-model="conf" :min="0.05" :max="0.95" :step="0.05" style="width: 120px" :disabled="busy" />
        </el-form-item>
        <el-form-item label="分辨率">
          <el-select v-model="imgsz" style="width: 100px" :disabled="busy">
            <el-option :value="640" label="640" />
            <el-option :value="480" label="480" />
            <el-option :value="320" label="320" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="enableOcr" :disabled="busy">号牌 OCR</el-checkbox>
          <el-checkbox v-if="mode !== 'image'" v-model="enableSpeed" :disabled="busy" style="margin-left: 8px">测速</el-checkbox>
          <el-checkbox v-model="vehicleOnly" :disabled="busy" style="margin-left: 8px">仅车辆类</el-checkbox>
        </el-form-item>
        <el-form-item v-if="enableSpeed && mode !== 'image'" label="米/像素">
          <el-input-number v-model="metersPerPixel" :min="0" :step="0.001" :precision="4" style="width: 130px" :disabled="busy" />
        </el-form-item>
        <el-form-item v-if="mode === 'image'">
          <el-upload :show-file-list="false" :auto-upload="false" :on-change="onPickImage" accept="image/*">
            <el-button :icon="UploadFilled">选择图片</el-button>
          </el-upload>
        </el-form-item>
        <el-form-item v-if="mode === 'file'">
          <el-upload :show-file-list="false" :auto-upload="false" :on-change="onPick" accept="video/*">
            <el-button :icon="UploadFilled">选择视频</el-button>
          </el-upload>
        </el-form-item>
        <el-form-item v-if="mode === 'local'" label="摄像头">
          <el-select v-model="deviceId" placeholder="默认" style="width: 180px" :disabled="liveRunning">
            <el-option v-for="d in devices" :key="d.deviceId" :label="d.label || `摄像头 ${d.idx}`" :value="d.deviceId" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="mode === 'network'" label="网络摄像头">
          <el-select v-model="cameraId" placeholder="选择" filterable style="width: 200px" :disabled="liveRunning" :loading="camerasLoading">
            <el-option v-for="c in managedCameras" :key="c.id" :label="cameraLabel(c)" :value="c.id" />
          </el-select>
          <el-button link type="primary" :disabled="liveRunning" @click="loadManagedCameras">刷新</el-button>
        </el-form-item>
        <el-form-item v-if="mode === 'image'" class="alert-action-item">
          <div class="alert-action-row">
            <el-button type="primary" :icon="VideoPlay" :loading="imageRunning" :disabled="!canRunImage" @click="runImage">开始识别</el-button>
            <el-button :icon="Refresh" @click="clearImage" style="margin-left: 8px">清空</el-button>
          </div>
        </el-form-item>
        <el-form-item v-if="mode === 'file'" class="alert-action-item">
          <div class="alert-action-row">
            <el-button type="primary" :icon="VideoPlay" :loading="fileRunning" :disabled="!canRunFile" @click="runVideo">开始追踪</el-button>
            <el-checkbox v-model="alertEnabled" :disabled="fileRunning" style="margin-left: 12px">启用告警</el-checkbox>
            <el-button :icon="Refresh" @click="clearFile" style="margin-left: 8px">清空</el-button>
          </div>
        </el-form-item>
        <el-form-item v-if="mode === 'local' || mode === 'network'" class="alert-action-item">
          <div class="alert-action-row">
            <el-button v-if="!liveRunning" type="primary" :icon="VideoCamera" :disabled="!canStartLive" @click="liveStart">开始</el-button>
            <el-button v-else type="danger" :icon="SwitchButton" @click="liveStop">停止</el-button>
            <el-checkbox v-model="alertEnabled" :disabled="liveRunning" style="margin-left: 12px">启用告警</el-checkbox>
            <el-button v-if="liveLine" link type="primary" @click="clearLiveLine">清除线</el-button>
            <el-button v-if="recordCount" link type="primary" :icon="Download" @click="exportCsv">导出 CSV</el-button>
          </div>
        </el-form-item>
      </el-form>
      <el-alert
        v-if="!detectModels.length"
        type="warning"
        :closable="false"
        title="请先到「模型管理」拉取 YOLO 车辆检测模型（如 YOLO26）。"
      />
      <el-alert
        v-else-if="enableOcr && (!detModels.length || !recModels.length)"
        type="warning"
        :closable="false"
        title="号牌 OCR 需 RapidOCR 检测 + 识别模型；未配置时将跳过 OCR。"
      />
      <el-alert
        v-else
        type="info"
        :closable="false"
        class="flow-tip"
        title="车牌检测可选：YOLOv11n/s（推荐）、YOLOv8（Koushim）、YOLOv5n/m（keremberke 兼容）。OCR 推荐 PP-OCRv6 small det+rec。"
      />
    </el-card>

    <!-- 图片识别模式 -->
    <template v-if="mode === 'image'">
      <el-card v-if="imagePreviewUrl" shadow="never" class="cfg-card">
        <div class="section-title">原图预览</div>
        <img :src="imagePreviewUrl" class="preview-img" alt="车辆原图" />
      </el-card>
      <el-card shadow="never">
        <el-empty v-if="!imageRunning && !imageResultSrc" description="选择车辆图片后开始识别（车辆框 + 车牌 OCR）" />
        <div v-else-if="imageRunning" class="progress-box">
          <div class="progress-title">识别中…</div>
          <el-progress :percentage="100" :indeterminate="true" :stroke-width="18" />
        </div>
        <div v-else>
          <div class="section-title">
            识别结果
            <el-button link type="primary" :icon="Download" @click="downloadImageResult">下载标注图</el-button>
          </div>
          <img :src="imageResultSrc" class="preview-img result-img" alt="识别结果" />
          <div class="stats">
            <el-tag type="success" effect="dark">车辆 {{ imageDets.length }}</el-tag>
            <el-tag type="warning" effect="dark">号牌 {{ imagePlateCount }}</el-tag>
          </div>
          <el-table v-if="imageDets.length" :data="imageDets" size="small" border max-height="280" class="rec-table">
            <el-table-column prop="trackId" label="ID" width="70" />
            <el-table-column prop="className" label="车型" width="100" />
            <el-table-column prop="confidence" label="置信度" width="90">
              <template #default="{ row }">{{ Number(row.confidence || 0).toFixed(2) }}</template>
            </el-table-column>
            <el-table-column prop="plate" label="号牌" min-width="120" />
            <el-table-column prop="plateScore" label="OCR 分" width="90">
              <template #default="{ row }">{{ row.plateScore != null ? Number(row.plateScore).toFixed(2) : '—' }}</template>
            </el-table-column>
            <el-table-column prop="plateSource" label="车牌来源" width="100" />
          </el-table>
        </div>
      </el-card>
    </template>

    <!-- 视频文件模式 -->
    <template v-else-if="mode === 'file'">
      <el-card v-if="previewUrl" shadow="never" class="cfg-card">
        <div class="section-title">原视频预览</div>
        <video :src="previewUrl" controls class="player" />
      </el-card>
      <el-card v-if="file" shadow="never" class="cfg-card">
        <div class="line-tip">
          首帧画计数线（可选）：点两点。
          <el-button link type="primary" @click="clearFileLine">清除线</el-button>
        </div>
        <canvas ref="frameCanvas" class="frame-canvas" @click="onFileCanvasClick" />
      </el-card>
      <el-card shadow="never">
        <div v-if="fileRunning" class="progress-box">
          <div class="progress-title">追踪中… {{ processed }}/{{ total || '?' }} 帧</div>
          <el-progress :percentage="percent" :stroke-width="18" :text-inside="true" />
        </div>
        <el-empty v-else-if="!resultUrl" description="选择模型与视频后开始追踪" />
        <div v-else>
          <div class="section-title">
            追踪结果
            <el-button link type="primary" :icon="Download" @click="downloadVideo">下载视频</el-button>
            <el-button v-if="fileRecords.length" link type="primary" @click="downloadFileCsv">下载过车 CSV</el-button>
          </div>
          <video :src="resultUrl" controls class="player" />
          <div class="stats">
            <el-tag type="success" effect="dark">唯一车辆 {{ stats.uniqueObjects ?? '-' }}</el-tag>
            <el-tag v-if="stats.crossing" type="warning" effect="dark">
              越线 进{{ stats.crossing.in }} 出{{ stats.crossing.out }}
            </el-tag>
            <el-tag v-if="stats.recordCount" type="info" effect="dark">过车记录 {{ stats.recordCount }}</el-tag>
            <el-tag v-if="stats.congestionSummary" type="danger" effect="dark">
              拥堵帧占比 {{ Math.round((stats.congestionSummary.busyRatio || 0) * 100) }}%
            </el-tag>
          </div>
          <el-table v-if="fileRecords.length" :data="fileRecords" size="small" border max-height="240" class="rec-table">
            <el-table-column prop="trackId" label="ID" width="70" />
            <el-table-column prop="className" label="车型" width="90" />
            <el-table-column prop="plate" label="号牌" min-width="100" />
            <el-table-column prop="speedKmh" label="速度 km/h" width="100" />
            <el-table-column prop="plateScore" label="OCR 分" width="80" />
          </el-table>
        </div>
      </el-card>
    </template>

    <!-- 实时模式（本地 / 网络） -->
    <template v-else>
      <el-card shadow="never">
        <div class="cam-wrap">
          <div class="cam-stage">
            <video v-show="mode === 'local'" ref="camVideo" class="cam-video" autoplay playsinline muted />
            <img v-show="mode === 'network'" ref="streamImg" class="cam-video" alt="网络摄像头" />
            <canvas ref="camCanvas" class="cam-canvas" @click="onLiveClick" />
            <div v-if="!liveRunning" class="cam-hint">
              {{ mode === 'network' ? '选择网络摄像头后点「开始」' : '点「开始」启用摄像头；可在画面点两点画计数线' }}
            </div>
            <div v-if="liveRunning" class="cam-hud">
              <el-tag type="success" effect="dark">{{ camFps }} FPS</el-tag>
              <el-tag type="warning" effect="dark">车辆 {{ liveDets.length }}</el-tag>
              <el-tag :type="congestionTagType" effect="dark">{{ congestion.label || '—' }}</el-tag>
              <el-tag v-if="liveLine" type="danger" effect="dark">进{{ crossing.in }} 出{{ crossing.out }}</el-tag>
              <el-tag v-if="recordCount" type="info" effect="dark">记录 {{ recordCount }}</el-tag>
            </div>
          </div>
        </div>
        <el-table v-if="recentRecords.length" :data="recentRecords" size="small" border max-height="200" class="rec-table">
          <el-table-column prop="trackId" label="ID" width="70" />
          <el-table-column prop="className" label="车型" width="90" />
          <el-table-column prop="plate" label="号牌" min-width="100" />
          <el-table-column prop="speedKmh" label="速度" width="80" />
        </el-table>
      </el-card>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { ElMessage, ElNotification } from 'element-plus'
import {
  UploadFilled, VideoPlay, Refresh, Download, VideoCamera, SwitchButton,
} from '@element-plus/icons-vue'
import { modelApi, vehicleApi, alertApi } from '../../../api/ai'
import { cameraApi } from '../../../api/camera'

const ALERT_SOURCE_KEY = 'vehicle-camera'

const allModels = ref([])
const detectId = ref(null)
const plateId = ref(null)
const detId = ref(null)
const recId = ref(null)
const conf = ref(0.25)
const imgsz = ref(640)
const enableOcr = ref(true)
const enableSpeed = ref(true)
const vehicleOnly = ref(true)
const metersPerPixel = ref(0.05)
const alertEnabled = ref(false)

/** 推荐权重优先级（高精度 + CPU 友好，面向行驶车牌） */
const DETECT_PREF = [
  /yolo26s/i,
  /yolo26n/i,
  /yolo11s/i,
  /yolo11n/i,
  /yolov8s/i,
  /yolov8n/i,
]
const PLATE_PREF = [
  /yolov11-license-plate-n/i,
  /yolov11-license-plate-s/i,
  /yolov11-license-plate|license-plate-finetune-v1/i,
  /yolov8-license-plate|Koushim/i,
  /keremberke-yolov5m/i,
  /keremberke-yolov5n|yolov5n-license-plate/i,
  /license-plate-detection/i,
  /车牌检测/i,
]
const OCR_DET_PREF = [/pp-ocrv6.*det|v6.*small.*det|OCRv6_small_det/i, /pp-ocrv5.*det/i, /pp-ocrv4.*det|ch_PP-OCRv4.*det/i]
const OCR_REC_PREF = [/pp-ocrv6.*rec|v6.*small.*rec|OCRv6_small_rec/i, /pp-ocrv5.*rec/i, /pp-ocrv4.*rec|ch_PP-OCRv4.*rec/i]

const scoreByPref = (m, prefs) => {
  const text = `${m.modelKey || ''} ${m.modelName || ''} ${m.filePath || ''}`
  const idx = prefs.findIndex((re) => re.test(text))
  return idx === -1 ? 1000 : idx
}

const sortByPref = (list, prefs) =>
  [...list].sort((a, b) => scoreByPref(a, prefs) - scoreByPref(b, prefs) || String(a.modelName).localeCompare(String(b.modelName)))

const pickPreferred = (list, prefs) => {
  if (!list.length) return null
  return sortByPref(list, prefs)[0]
}

const modelOptionLabel = (m, kind) => {
  const text = `${m.modelKey || ''} ${m.modelName || ''}`
  let tag = ''
  if (kind === 'plate' && /yolov11-license-plate-s/i.test(text)) tag = ' · 推荐·精度'
  else if (kind === 'plate' && /yolov11-license-plate-n/i.test(text)) tag = ' · 推荐·CPU'
  else if (kind === 'plate' && /yolov8-license-plate|Koushim/i.test(text)) tag = ' · YOLOv8'
  else if (kind === 'plate' && /yolov5m-license-plate/i.test(text)) tag = ' · 兼容·YOLOv5m'
  else if (kind === 'plate' && /yolov5n-license-plate|keremberke-yolov5n/i.test(text)) tag = ' · 兼容·YOLOv5n'
  else if ((kind === 'ocrDet' || kind === 'ocrRec') && /pp-ocrv6|v6_small/i.test(text)) tag = ' · 推荐'
  return `${m.modelName}${tag}`
}

const detectModels = computed(() => {
  const yolo = allModels.value.filter(
    (m) =>
      m.library === 'ultralytics' &&
      m.task === 'object-detection' &&
      m.filePath &&
      m.status === '0' &&
      !/plate|license|车牌/i.test(`${m.modelKey} ${m.modelName}`),
  )
  const traffic = yolo.filter(
    (m) =>
      /车|交通|vehicle|traffic|yolo26|yolo11|yolov8/i.test(`${m.modelName} ${m.category} ${m.modelKey}`),
  )
  return sortByPref(traffic.length ? traffic : yolo, DETECT_PREF)
})
const plateModels = computed(() => {
  const list = allModels.value.filter(
    (m) =>
      m.library === 'ultralytics' &&
      m.task === 'object-detection' &&
      m.filePath &&
      m.status === '0' &&
      /车牌|plate|license/i.test(`${m.modelName} ${m.modelKey}`),
  )
  return sortByPref(list, PLATE_PREF)
})

const detModels = computed(() =>
  sortByPref(
    allModels.value.filter((m) => m.library === 'rapidocr' && m.task === 'text-detection' && m.filePath && m.status === '0'),
    OCR_DET_PREF,
  ),
)
const recModels = computed(() =>
  sortByPref(
    allModels.value.filter((m) => m.library === 'rapidocr' && m.task === 'text-recognition' && m.filePath && m.status === '0'),
    OCR_REC_PREF,
  ),
)

const mode = ref('image')
const file = ref(null)
const previewUrl = ref('')
const fileRunning = ref(false)
const processed = ref(0)
const total = ref(0)
const resultUrl = ref('')
const stats = ref({})
const fileRecords = ref([])
let pollTimer = null
let blobUrl = ''

const imageFile = ref(null)
const imagePreviewUrl = ref('')
const imageRunning = ref(false)
const imageResultSrc = ref('')
const imageDets = ref([])
const imagePlateCount = ref(0)

const frameCanvas = ref(null)
const fileLinePts = ref([])
const fileLine = ref(null)

const devices = ref([])
const deviceId = ref('')
const managedCameras = ref([])
const camerasLoading = ref(false)
const cameraId = ref(null)

const camVideo = ref(null)
const streamImg = ref(null)
const camCanvas = ref(null)
const liveRunning = ref(false)
const liveDets = ref([])
const camFps = ref(0)
const liveLine = ref(null)
const crossing = ref({ in: 0, out: 0 })
const congestion = ref({ label: '—', level: 'smooth' })
const recentRecords = ref([])
const recordCount = ref(0)
const sessionId = ref('')
let camStream = null
let capCanvas = null
let camBusy = false
let camFirst = true
let frameCount = 0
let fpsTimer = null
let loopTimer = null
let streamReady = false

const busy = computed(() => liveRunning.value || fileRunning.value || imageRunning.value)
const canRunFile = computed(() => detectId.value && file.value && !fileRunning.value)
const canRunImage = computed(() => detectId.value && imageFile.value && !imageRunning.value)
const canStartLive = computed(() => {
  if (!detectId.value) return false
  if (mode.value === 'network') return !!cameraId.value
  return true
})
const percent = computed(() => (total.value ? Math.min(100, Math.floor((processed.value / total.value) * 100)) : 0))
const congestionTagType = computed(() => {
  const lv = congestion.value.level
  if (lv === 'severe' || lv === 'busy') return 'danger'
  if (lv === 'moderate') return 'warning'
  return 'success'
})

const newSessionId = () => {
  sessionId.value = (globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`)
}

const appendCommonFields = (fd, { reset = false, line = null } = {}) => {
  fd.append('detectId', detectId.value)
  if (plateId.value) fd.append('plateId', plateId.value)
  if (detId.value && recId.value) {
    fd.append('detId', detId.value)
    fd.append('recId', recId.value)
  }
  fd.append('conf', conf.value)
  fd.append('imgsz', imgsz.value)
  fd.append('enableOcr', enableOcr.value ? '1' : '0')
  fd.append('enableSpeed', enableSpeed.value ? '1' : '0')
  fd.append('vehicleOnly', vehicleOnly.value ? '1' : '0')
  if (enableSpeed.value && metersPerPixel.value > 0) {
    fd.append('metersPerPixel', metersPerPixel.value)
  }
  if (line) fd.append('line', JSON.stringify(line))
  if (sessionId.value) fd.append('sessionId', sessionId.value)
  fd.append('reset', reset ? '1' : '0')
}

const loadModels = async () => {
  const res = await modelApi.list({ pageNum: 1, pageSize: 200 })
  allModels.value = res.data.rows || []
  if (detectModels.value.length) {
    const preferred = pickPreferred(detectModels.value, DETECT_PREF)
    const currentOk = detectId.value && detectModels.value.some((m) => m.id === detectId.value)
    if (!currentOk) detectId.value = preferred?.id || detectModels.value[0].id
  }
  if (plateModels.value.length) {
    const preferred = pickPreferred(plateModels.value, PLATE_PREF)
    const currentOk = plateId.value && plateModels.value.some((m) => m.id === plateId.value)
    if (!currentOk) plateId.value = preferred?.id || plateModels.value[0].id
  } else {
    plateId.value = null
  }
  if (detModels.value.length) {
    const preferred = pickPreferred(detModels.value, OCR_DET_PREF)
    const currentOk = detId.value && detModels.value.some((m) => m.id === detId.value)
    if (!currentOk) detId.value = preferred?.id || detModels.value[0].id
  }
  if (recModels.value.length) {
    const preferred = pickPreferred(recModels.value, OCR_REC_PREF)
    const currentOk = recId.value && recModels.value.some((m) => m.id === recId.value)
    if (!currentOk) recId.value = preferred?.id || recModels.value[0].id
  }
}

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
    devices.value = list.filter((d) => d.kind === 'videoinput').map((d, i) => ({
      deviceId: d.deviceId, label: d.label, idx: i + 1,
    }))
  } catch (_) { /* ignore */ }
}

const onModeChange = () => {
  if (liveRunning.value) liveStop()
}

const onPickImage = (uploadFile) => {
  const raw = uploadFile.raw
  if (!raw || !raw.type.startsWith('image/')) {
    ElMessage.error('请选择图片文件')
    return
  }
  imageFile.value = raw
  if (imagePreviewUrl.value) URL.revokeObjectURL(imagePreviewUrl.value)
  imagePreviewUrl.value = URL.createObjectURL(raw)
  imageResultSrc.value = ''
  imageDets.value = []
  imagePlateCount.value = 0
}

const clearImage = () => {
  imageRunning.value = false
  imageFile.value = null
  if (imagePreviewUrl.value) {
    URL.revokeObjectURL(imagePreviewUrl.value)
    imagePreviewUrl.value = ''
  }
  imageResultSrc.value = ''
  imageDets.value = []
  imagePlateCount.value = 0
}

const runImage = async () => {
  if (!canRunImage.value) return
  imageRunning.value = true
  imageResultSrc.value = ''
  imageDets.value = []
  imagePlateCount.value = 0
  try {
    const fd = new FormData()
    fd.append('file', imageFile.value)
    appendCommonFields(fd)
    const res = await vehicleApi.detectImage(fd)
    const data = res.data || {}
    imageDets.value = data.detections || []
    imagePlateCount.value = data.plateCount ?? imageDets.value.filter((d) => d.plate).length
    imageResultSrc.value = data.imageBase64 ? `data:image/jpeg;base64,${data.imageBase64}` : ''
    if (!imageDets.value.length) ElMessage.warning('未检测到车辆')
    else ElMessage.success(`识别完成：${imageDets.value.length} 辆，号牌 ${imagePlateCount.value}`)
  } catch (e) {
    ElMessage.error(e?.response?.data?.message || e?.message || '图片识别失败')
  } finally {
    imageRunning.value = false
  }
}

const downloadImageResult = () => {
  if (!imageResultSrc.value) return
  const a = document.createElement('a')
  a.href = imageResultSrc.value
  a.download = `vehicle_plate_${Date.now()}.jpg`
  a.click()
}

const onPick = (uploadFile) => {
  const raw = uploadFile.raw
  if (!raw || !raw.type.startsWith('video/')) {
    ElMessage.error('请选择视频文件')
    return
  }
  file.value = raw
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = URL.createObjectURL(raw)
  clearFileLine()
  clearFileOutput()
  drawFirstFrame(raw)
}

const clearFileOutput = () => {
  if (blobUrl) { URL.revokeObjectURL(blobUrl); blobUrl = '' }
  resultUrl.value = ''
  stats.value = {}
  fileRecords.value = []
}

const drawFirstFrame = (raw) => {
  const url = URL.createObjectURL(raw)
  const v = document.createElement('video')
  v.preload = 'auto'
  v.muted = true
  v.src = url
  v.addEventListener('loadeddata', () => { v.currentTime = 0 })
  v.addEventListener('seeked', async () => {
    await nextTick()
    const cv = frameCanvas.value
    if (!cv) return
    const dispW = Math.min(640, v.videoWidth)
    const scale = dispW / v.videoWidth
    cv.width = dispW
    cv.height = Math.round(v.videoHeight * scale)
    cv.getContext('2d').drawImage(v, 0, 0, cv.width, cv.height)
    URL.revokeObjectURL(url)
  })
}

const redrawFileLine = () => {
  const cv = frameCanvas.value
  if (!cv || !fileLinePts.value.length) return
  const ctx = cv.getContext('2d')
  ctx.fillStyle = '#ff1744'
  fileLinePts.value.forEach((p) => {
    ctx.beginPath()
    ctx.arc(p.x, p.y, 4, 0, Math.PI * 2)
    ctx.fill()
  })
  if (fileLinePts.value.length === 2) {
    ctx.strokeStyle = '#ff1744'
    ctx.lineWidth = 2
    ctx.beginPath()
    ctx.moveTo(fileLinePts.value[0].x, fileLinePts.value[0].y)
    ctx.lineTo(fileLinePts.value[1].x, fileLinePts.value[1].y)
    ctx.stroke()
  }
}

const onFileCanvasClick = (e) => {
  if (fileLinePts.value.length >= 2) return
  const cv = frameCanvas.value
  const rect = cv.getBoundingClientRect()
  const x = (e.clientX - rect.left) * (cv.width / rect.width)
  const y = (e.clientY - rect.top) * (cv.height / rect.height)
  fileLinePts.value.push({ x, y })
  redrawFileLine()
  if (fileLinePts.value.length === 2) {
    fileLine.value = [
      fileLinePts.value[0].x / cv.width, fileLinePts.value[0].y / cv.height,
      fileLinePts.value[1].x / cv.width, fileLinePts.value[1].y / cv.height,
    ]
  }
}

const clearFileLine = () => {
  fileLinePts.value = []
  fileLine.value = null
  if (file.value) drawFirstFrame(file.value)
}

const clearFile = () => {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
  clearFileOutput()
  if (previewUrl.value) { URL.revokeObjectURL(previewUrl.value); previewUrl.value = '' }
  file.value = null
  clearFileLine()
  processed.value = 0
  total.value = 0
  fileRunning.value = false
}

const runVideo = async () => {
  fileRunning.value = true
  processed.value = 0
  total.value = 0
  clearFileOutput()
  try {
    const fd = new FormData()
    fd.append('file', file.value)
    appendCommonFields(fd, { line: fileLine.value })
    fd.append('alertEnabled', alertEnabled.value ? '1' : '0')
    const res = await vehicleApi.trackVideo(fd)
    await pollVideo(res.data.jobId)
  } catch (_) {
    ElMessage.error('车辆追踪启动失败')
    fileRunning.value = false
  }
}

const pollVideo = (jobId) => new Promise((resolve) => {
  pollTimer = setInterval(async () => {
    try {
      const res = await vehicleApi.videoProgress(jobId)
      const d = res.data
      processed.value = d.processed
      total.value = d.total
      if (d.status === 'done') {
        clearInterval(pollTimer)
        pollTimer = null
        stats.value = d.stats || {}
        fileRecords.value = d.stats?.records || []
        const blob = await modelApi.outputVideo(d.stats.output)
        blobUrl = URL.createObjectURL(blob)
        resultUrl.value = blobUrl
        fileRunning.value = false
        ElMessage.success(`追踪完成，过车记录 ${fileRecords.value.length} 条`)
        resolve()
      } else if (d.status === 'error') {
        clearInterval(pollTimer)
        pollTimer = null
        ElMessage.error(d.error || '追踪失败')
        fileRunning.value = false
        resolve()
      }
    } catch (_) {
      clearInterval(pollTimer)
      pollTimer = null
      ElMessage.error('查询进度失败')
      fileRunning.value = false
      resolve()
    }
  }, 1000)
})

const downloadVideo = () => {
  const a = document.createElement('a')
  a.href = resultUrl.value
  a.download = stats.value.output || 'vehicle.mp4'
  a.click()
}

const downloadBlob = (text, filename) => {
  const blob = new Blob([text], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

const recordsToCsv = (rows) => {
  const header = ['time', 'trackId', 'className', 'plate', 'plateScore', 'speedKmh', 'confidence']
  const lines = [header.join(',')]
  for (const r of rows) {
    lines.push(header.map((k) => JSON.stringify(r[k] ?? '')).join(','))
  }
  return lines.join('\n')
}

const downloadFileCsv = () => {
  if (!fileRecords.value.length) return
  downloadBlob(recordsToCsv(fileRecords.value), `vehicle_records_${Date.now()}.csv`)
}

const exportCsv = async () => {
  if (!sessionId.value) return
  try {
    const res = await vehicleApi.exportRecords(sessionId.value)
    downloadBlob(res.data.csv, `vehicle_live_${Date.now()}.csv`)
    ElMessage.success(`已导出 ${res.data.count || 0} 条记录`)
  } catch (_) {
    ElMessage.error('导出失败')
  }
}

const waitForImgReady = (img, timeoutMs = 15000) =>
  new Promise((resolve, reject) => {
    if (img.naturalWidth > 0) { resolve(); return }
    const started = Date.now()
    const finish = (ok, err) => {
      clearInterval(poll)
      clearTimeout(timer)
      img.removeEventListener('load', onLoad)
      img.removeEventListener('error', onError)
      ok ? resolve() : reject(err)
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

const liveStart = async () => {
  newSessionId()
  crossing.value = { in: 0, out: 0 }
  recentRecords.value = []
  recordCount.value = 0
  congestion.value = { label: '—', level: 'smooth' }
  camFirst = true

  if (mode.value === 'network') {
    if (!cameraId.value) {
      ElMessage.warning('请选择网络摄像头')
      return
    }
    liveRunning.value = true
    streamReady = false
    await nextTick()
    const img = streamImg.value
    if (!img) {
      liveRunning.value = false
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
      liveRunning.value = false
      return
    }
    setupCapCanvas(img.naturalWidth, img.naturalHeight)
    fpsTimer = setInterval(() => { camFps.value = frameCount; frameCount = 0 }, 1000)
    scheduleLoop(80)
    return
  }

  try {
    const constraints = {
      video: deviceId.value ? { deviceId: { exact: deviceId.value } } : true,
      audio: false,
    }
    camStream = await navigator.mediaDevices.getUserMedia(constraints)
  } catch (_) {
    ElMessage.error('无法访问摄像头')
    return
  }
  camVideo.value.srcObject = camStream
  await camVideo.value.play()
  await enumCams()
  setupCapCanvas(camVideo.value.videoWidth, camVideo.value.videoHeight)
  liveRunning.value = true
  fpsTimer = setInterval(() => { camFps.value = frameCount; frameCount = 0 }, 1000)
  scheduleLoop(0)
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
  if (!liveRunning.value) return
  if (loopTimer) clearTimeout(loopTimer)
  loopTimer = setTimeout(() => {
    loopTimer = null
    liveLoop()
  }, delayMs)
}

const onLiveClick = (e) => {
  if (!liveRunning.value) return
  const cv = camCanvas.value
  const rect = cv.getBoundingClientRect()
  const x = (e.clientX - rect.left) * (cv.width / rect.width)
  const y = (e.clientY - rect.top) * (cv.height / rect.height)
  if (!cv._p0) {
    cv._p0 = [x, y]
    liveLine.value = null
  } else {
    liveLine.value = [cv._p0[0] / cv.width, cv._p0[1] / cv.height, x / cv.width, y / cv.height]
    cv._p0 = null
    crossing.value = { in: 0, out: 0 }
  }
}

const clearLiveLine = () => {
  liveLine.value = null
  if (camCanvas.value) camCanvas.value._p0 = null
}

const notifyAlert = (item) => {
  ElNotification({
    title: item.title || item.ruleName || '检测告警',
    message: item.message || '请现场核实',
    type: item.severity === 'high' ? 'error' : item.severity === 'medium' ? 'warning' : 'info',
    duration: item.severity === 'high' ? 0 : 8000,
    position: 'top-right',
  })
}

const evaluateAlerts = async (detections, frameW, frameH) => {
  if (!alertEnabled.value || !detections?.length) return null
  try {
    const payload = {
      detections,
      sourceKey: ALERT_SOURCE_KEY,
      sourceType: 'camera',
      modelId: detectId.value,
      persist: true,
      frameWidth: frameW,
      frameHeight: frameH,
    }
    if (liveLine.value) payload.line = liveLine.value
    const res = await alertApi.evaluate(payload)
    const list = res.data?.triggered || []
    list.filter((t) => t.notify).forEach(notifyAlert)
    return res.data?.overlay || null
  } catch (_) {
    return null
  }
}

const COLORS = ['#67c23a', '#409eff', '#e6a23c', '#f56c6c', '#9254de', '#13c2c2']

const camDraw = (data, overlayStyle = null) => {
  const cv = camCanvas.value
  const ctx = cv.getContext('2d')
  const src = getFrameSource().el
  ctx.clearRect(0, 0, cv.width, cv.height)
  if (src) ctx.drawImage(src, 0, 0, cv.width, cv.height)

  const list = data.detections || []
  ctx.lineWidth = 2
  ctx.font = '13px sans-serif'
  ctx.textBaseline = 'top'
  list.forEach((d, i) => {
    const [x1, y1, x2, y2] = d.bbox
    const color = COLORS[(d.trackId ?? i) % COLORS.length]
    ctx.strokeStyle = color
    ctx.strokeRect(x1, y1, x2 - x1, y2 - y1)
    const parts = []
    if (d.trackId != null) parts.push(`ID${d.trackId}`)
    parts.push(d.className || 'vehicle')
    if (d.plate) parts.push(d.plate)
    if (d.speedKmh) parts.push(`${d.speedKmh}km/h`)
    const label = parts.join(' ')
    const tw = ctx.measureText(label).width + 8
    ctx.fillStyle = color
    ctx.fillRect(x1, Math.max(0, y1 - 18), tw, 18)
    ctx.fillStyle = '#fff'
    ctx.fillText(label, x1 + 4, Math.max(0, y1 - 17))
    if (d.plateBbox?.length >= 4) {
      const [px1, py1, px2, py2] = d.plateBbox
      ctx.strokeStyle = '#ffd700'
      ctx.strokeRect(px1, py1, px2 - px1, py2 - py1)
    }
  })

  if (liveLine.value) {
    const ln = [
      liveLine.value[0] * cv.width, liveLine.value[1] * cv.height,
      liveLine.value[2] * cv.width, liveLine.value[3] * cv.height,
    ]
    ctx.strokeStyle = '#ff1744'
    ctx.lineWidth = 3
    ctx.beginPath()
    ctx.moveTo(ln[0], ln[1])
    ctx.lineTo(ln[2], ln[3])
    ctx.stroke()
  }

  const cong = data.congestion || {}
  ctx.fillStyle = 'rgba(0,0,0,0.55)'
  ctx.fillRect(8, cv.height - 36, 180, 28)
  ctx.fillStyle = '#fff'
  ctx.font = 'bold 14px sans-serif'
  ctx.fillText(`拥堵: ${cong.label || '—'} (${cong.vehicleCount ?? 0}辆)`, 14, cv.height - 30)

  if (alertEnabled.value && overlayStyle) {
    drawAlertOverlay(ctx, cv, overlayStyle)
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
  const titles = style.titleLines || []
  const subs = style.subtitleLines || []
  const lines = [...titles, ...subs]
  ctx.fillStyle = style.textColor || '#FFFFFF'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  const startY = y + Math.round(ph * 0.58)
  const step = Math.max(18, Math.round(ph * 0.14))
  lines.forEach((ln, i) => {
    ctx.font = `${i < titles.length ? 'bold ' : ''}${Math.max(14, Math.round(ph * 0.11))}px sans-serif`
    ctx.fillText(String(ln), cx, startY + i * step)
  })
  ctx.restore()
}

const liveLoop = () => {
  if (!liveRunning.value) return
  if (camBusy) { scheduleLoop(mode.value === 'network' ? 80 : 0); return }
  const src = getFrameSource()
  if (!src.el || !src.w || !src.h) { scheduleLoop(200); return }

  camBusy = true
  const ctx = capCanvas.getContext('2d')
  ctx.drawImage(src.el, 0, 0, capCanvas.width, capCanvas.height)
  capCanvas.toBlob(async (blob) => {
    if (!liveRunning.value || !blob) { camBusy = false; return }
    try {
      const fd = new FormData()
      fd.append('file', blob, 'frame.jpg')
      appendCommonFields(fd, { reset: camFirst, line: liveLine.value })
      camFirst = false
      const res = await vehicleApi.trackFrame(fd)
      const data = res.data || {}
      if (data.sessionId) sessionId.value = data.sessionId
      liveDets.value = data.detections || []
      crossing.value = data.crossing || crossing.value
      congestion.value = data.congestion || congestion.value
      recentRecords.value = data.recentRecords || []
      recordCount.value = data.recordCount || 0
      const overlay = await evaluateAlerts(data.detections, data.width || capCanvas.width, data.height || capCanvas.height)
      camDraw(data, overlay)
      frameCount++
    } catch (_) { /* 单帧失败忽略 */ } finally {
      camBusy = false
      if (liveRunning.value) scheduleLoop(mode.value === 'network' ? 80 : 0)
    }
  }, 'image/jpeg', 0.6)
}

const liveStop = async () => {
  liveRunning.value = false
  if (loopTimer) { clearTimeout(loopTimer); loopTimer = null }
  if (fpsTimer) { clearInterval(fpsTimer); fpsTimer = null }
  if (camStream) {
    camStream.getTracks().forEach((t) => t.stop())
    camStream = null
  }
  if (camVideo.value) camVideo.value.srcObject = null
  if (streamImg.value) streamImg.value.removeAttribute('src')
  streamReady = false
  if (camCanvas.value) {
    const ctx = camCanvas.value.getContext('2d')
    ctx.clearRect(0, 0, camCanvas.value.width, camCanvas.value.height)
  }
  liveDets.value = []
  camFps.value = 0
  try {
    await alertApi.resetRuntime({ sourceKey: ALERT_SOURCE_KEY })
  } catch (_) { /* ignore */ }
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
  if (imagePreviewUrl.value) URL.revokeObjectURL(imagePreviewUrl.value)
  liveStop()
})
</script>

<style scoped>
.cfg-card { margin-bottom: 12px; }
.cfg-form { row-gap: 4px; }
.flow-tip { margin-top: 8px; }
.alert-action-row { display: flex; align-items: center; flex-wrap: wrap; gap: 4px; }
.section-title { font-weight: 600; color: #3a4a63; margin-bottom: 10px; display: flex; align-items: center; gap: 12px; }
.line-tip { font-size: 13px; color: #5a6b87; margin-bottom: 8px; }
.frame-canvas { max-width: 100%; border: 1px solid #e4e7ed; border-radius: 6px; cursor: crosshair; }
.progress-box { padding: 22px 4px; }
.progress-title { font-weight: 600; margin-bottom: 12px; color: #3a4a63; }
.player { width: 100%; max-height: 480px; background: #000; border-radius: 6px; }
.preview-img { max-width: 100%; max-height: 480px; border-radius: 6px; display: block; background: #0c1733; }
.result-img { margin-top: 4px; }
.stats { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0; }
.rec-table { margin-top: 12px; }
.cam-wrap { margin-top: 4px; }
.cam-stage { position: relative; background: #0c1733; border-radius: 8px; aspect-ratio: 16/9; overflow: hidden; }
.cam-video { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; }
.cam-canvas { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; cursor: crosshair; }
.cam-hint { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; color: #8aa0c8; text-align: center; padding: 16px; }
.cam-hud { position: absolute; top: 10px; left: 10px; display: flex; flex-wrap: wrap; gap: 8px; max-width: calc(100% - 20px); }
</style>
