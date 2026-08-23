<template>
  <div class="segment-root">
    <el-tabs v-model="engine" @tab-change="onEngineChange">
      <el-tab-pane label="RF-DETR 实例分割" name="rfdetr" />
      <el-tab-pane label="YOLOE 开放词汇分割" name="ultralytics" />
      <el-tab-pane label="YOLO-Master 实例分割" name="yolo-master" />
      <el-tab-pane label="MobileSAM 交互分割" name="mobilesam" />
      <el-tab-pane label="EfficientSAM（OpenCV）" name="efficientsam" />
    </el-tabs>

    <el-card shadow="never" class="cfg-card">
      <el-form :inline="true">
        <el-form-item v-if="engine === 'rfdetr' || engine === 'ultralytics' || engine === 'yolo-master'" label="模式">
          <el-radio-group v-model="mode" @change="clearAll">
            <el-radio-button value="image">图片</el-radio-button>
            <el-radio-button value="video">视频</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="模型">
          <el-select v-model="modelId" placeholder="选择分割模型" style="width: 320px" @change="onModelChange">
            <el-option v-for="m in filteredModels" :key="m.id"
                       :label="`${m.modelName}（${m.library || m.modelKey || '未分类'}）`" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="置信度">
          <el-slider v-model="conf" :min="0.05" :max="0.95" :step="0.05" style="width: 140px" />
        </el-form-item>
        <el-form-item v-if="engine === 'ultralytics'" label="提示类别">
          <el-input
            v-model="promptClasses"
            clearable
            placeholder="留空=COCO常用类；如 person,car,dog"
            style="width: 280px"
          />
        </el-form-item>
        <el-form-item v-if="engine === 'mobilesam'" label="SAM 模式">
          <el-radio-group v-model="samMode">
            <el-radio-button value="prompt">点击分割</el-radio-button>
            <el-radio-button value="auto">全自动</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="engine === 'efficientsam'" label="精度">
          <el-radio-group v-model="esamPrecision">
            <el-radio-button value="fp32">FP32</el-radio-button>
            <el-radio-button value="int8">INT8</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="engine === 'rfdetr' || engine === 'ultralytics' || engine === 'yolo-master' || (engine === 'mobilesam' && samMode === 'auto')">
          <el-upload :show-file-list="false" :auto-upload="false" :on-change="onPick"
                     :accept="isVideoMode ? 'video/*' : 'image/*'">
            <el-button :icon="UploadFilled">{{ pickLabel }}</el-button>
          </el-upload>
        </el-form-item>
        <el-form-item v-if="isSamPrompt">
          <el-upload :show-file-list="false" :auto-upload="false" :on-change="onPickSam" accept="image/*">
            <el-button :icon="UploadFilled">选择图片</el-button>
          </el-upload>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :icon="VideoPlay" :loading="running" :disabled="!canRun" @click="run">
            开始分割
          </el-button>
          <el-button :icon="Refresh" @click="clearAll">清空</el-button>
          <el-button v-if="isSamPrompt && (points.length || promptBox)" link type="warning"
                     @click="clearPoints">清除标注</el-button>
        </el-form-item>
      </el-form>
      <el-alert v-if="emptyModelTitle" type="warning" :closable="false" :title="emptyModelTitle" />
      <p v-if="engine === 'ultralytics'" class="hint">
        YOLOE 支持文本提示类别（英文逗号分隔）。留空时使用 COCO 常用 80 类；自定义如 <code>person,hardhat,fire</code>。
      </p>
      <p v-if="engine === 'mobilesam' && samMode === 'prompt'" class="hint">
        左键 = 前景点，Shift+点击 = 背景点；按住拖拽可框选。然后点「开始分割」。
      </p>
      <p v-if="engine === 'efficientsam'" class="hint">
        OpenCV EfficientSAM-Ti：左键前景 / Shift+点击背景 / 拖拽框选。最多 6 个 prompt 点（框占 2 个槽位）。无全自动模式。
      </p>
    </el-card>

    <!-- 进度 -->
    <el-card v-if="running" shadow="never" class="cfg-card progress-box">
      <div class="progress-title">{{ progressTitle }}</div>
      <el-progress
        v-if="showProgressBar"
        :percentage="progressPercent"
        :stroke-width="18"
        :text-inside="true"
        :status="progressPercent >= 100 ? 'success' : ''"
        :striped="isSamRunning"
        :striped-flow="isSamRunning"
      />
      <div v-if="isSamRunning" class="progress-hint">已用 {{ samElapsedText }} · CPU/GPU 推理中，首次加载模型较慢</div>
    </el-card>

    <!-- 图片：原图 + 结果并排 -->
    <template v-if="isImageMode && (originImgUrl || running)">
      <el-row :gutter="16" class="media-row">
        <el-col :span="resultImg ? 12 : 24">
          <div class="media-panel">
            <div class="panel-hd">
              <span class="panel-title">原图</span>
              <span v-if="isSamPrompt && !resultImg" class="panel-hint">点击标注前景/背景</span>
              <div v-if="originImgUrl && !running" class="zoom-toolbar">
                <el-button-group size="small">
                  <el-button :icon="ZoomOut" @click="origZoom.zoomOut()" />
                  <el-button class="zoom-pct" @click="origZoom.zoomFit()">{{ origZoom.pctText }}</el-button>
                  <el-button :icon="ZoomIn" @click="origZoom.zoomIn()" />
                </el-button-group>
                <el-button size="small" link type="primary" @click="origViewer = true">全屏</el-button>
              </div>
            </div>
            <div v-if="running && !resultImg" class="panel-loading">
              <el-icon class="rotating" :size="32"><Loading /></el-icon>
              <span>{{ isSamRunning ? `${samEngineLabel} 分割中… ${samElapsedText}` : '分割中…' }}</span>
            </div>
            <div v-else-if="originImgUrl" ref="origViewport" class="zoom-viewport" @wheel.prevent="origZoom.onWheel">
              <div class="zoom-spacer" :style="origZoom.spacerStyle">
                <div class="zoom-inner" :style="origZoom.innerStyle">
                  <div class="canvas-host">
                    <img ref="imgEl" :src="originImgUrl" class="panel-img" draggable="false"
                         @load="onOrigLoad" />
                    <canvas v-if="isSamPrompt && !resultImg" ref="overlayEl" class="overlay-canvas"
                            @click="onCanvasClick"
                            @mousedown="onCanvasMouseDown"
                            @mousemove="onCanvasMouseMove"
                            @mouseup="onCanvasMouseUp"
                            @mouseleave="onCanvasMouseUp" />
                  </div>
                </div>
              </div>
            </div>
          </div>
        </el-col>

        <el-col v-if="resultImg" :span="12">
          <div class="media-panel">
            <div class="panel-hd">
              <span class="panel-title">分割结果</span>
              <span class="panel-hint ok">{{ segCount }} 个区域</span>
              <div class="zoom-toolbar">
                <el-button-group size="small">
                  <el-button :icon="ZoomOut" @click="resultZoom.zoomOut()" />
                  <el-button class="zoom-pct" @click="resultZoom.zoomFit()">{{ resultZoom.pctText }}</el-button>
                  <el-button :icon="ZoomIn" @click="resultZoom.zoomIn()" />
                </el-button-group>
                <el-button size="small" link type="primary" @click="resultViewer = true">全屏</el-button>
                <el-button size="small" link type="primary" :icon="Download" @click="downloadImg">下载</el-button>
              </div>
            </div>
            <div ref="resultViewport" class="zoom-viewport" @wheel.prevent="resultZoom.onWheel">
              <div class="zoom-spacer" :style="resultZoom.spacerStyle">
                <div class="zoom-inner" :style="resultZoom.innerStyle">
                  <img ref="resultImgEl" :src="resultImg" class="panel-img" draggable="false"
                       @load="onResultLoad" />
                </div>
              </div>
            </div>
          </div>
        </el-col>
      </el-row>

      <el-card v-if="detections.length && resultImg" shadow="never" class="cfg-card">
        <el-table :data="detections" size="small" stripe>
          <el-table-column prop="className" label="类别/区域" width="140" />
          <el-table-column prop="confidence" label="置信度" width="100" />
          <el-table-column label="框 (x1,y1,x2,y2)">
            <template #default="{ row }">{{ row.bbox?.join(', ') }}</template>
          </el-table-column>
        </el-table>
      </el-card>
    </template>

    <!-- 视频：原视频 + 结果并排 -->
    <template v-if="isVideoMode && (previewUrl || resultUrl || running)">
      <el-row :gutter="16" class="media-row">
        <el-col :span="resultUrl ? 12 : 24">
          <div class="media-panel video-panel">
            <div class="panel-hd">
              <span class="panel-title">原视频</span>
              <div v-if="previewUrl" class="zoom-toolbar">
                <el-button size="small" link type="primary" @click="enterVideoFs('orig')">全屏播放</el-button>
              </div>
            </div>
            <div class="video-wrap" ref="origVideoWrap">
              <video v-if="previewUrl" ref="origVideoEl" :src="previewUrl" controls class="video-el" />
              <div v-else class="panel-loading"><span>请先选择视频</span></div>
            </div>
          </div>
        </el-col>

        <el-col v-if="resultUrl || (running && previewUrl)" :span="12">
          <div class="media-panel video-panel">
            <div class="panel-hd">
              <span class="panel-title">分割结果</span>
              <div v-if="resultUrl" class="zoom-toolbar">
                <el-button size="small" link type="primary" @click="enterVideoFs('result')">全屏播放</el-button>
                <el-button size="small" link type="primary" :icon="Download" @click="downloadVideo">下载</el-button>
              </div>
            </div>
            <div v-if="running && !resultUrl" class="panel-loading">
              <el-icon class="rotating" :size="32"><Loading /></el-icon>
              <span>处理中 {{ processed }}/{{ total || '?' }} 帧</span>
            </div>
            <div v-else-if="resultUrl" class="video-wrap" ref="resultVideoWrap">
              <video ref="resultVideoEl" :src="resultUrl" controls class="video-el" />
            </div>
            <div v-if="resultUrl && stats.frames" class="stats">
              <el-tag type="success" effect="dark">帧数：{{ stats.frames }}</el-tag>
              <el-tag type="warning" effect="dark">检出：{{ stats.totalDetections }}</el-tag>
            </div>
          </div>
        </el-col>
      </el-row>
    </template>

    <el-empty v-if="!hasContent && !running" description="选择模型与文件后开始分割" :image-size="100" />

    <el-image-viewer v-if="origViewer && originImgUrl" :url-list="[originImgUrl]"
                     hide-on-click-modal @close="origViewer = false" />
    <el-image-viewer v-if="resultViewer && resultImg" :url-list="[resultImg]"
                     hide-on-click-modal @close="resultViewer = false" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import {
  UploadFilled, VideoPlay, Refresh, Download, ZoomIn, ZoomOut, Loading
} from '@element-plus/icons-vue'
import { modelApi } from '../../../api/ai'
import { useInferProgress } from '../../../composables/useInferProgress'
import {
  filterSegModelsByEngine,
  loadSegmentationModels,
  pickPreferredSegModel,
  resolveSegEngine,
} from '../../../utils/segModels'

const engine = ref('rfdetr')
const mode = ref('image')
const samMode = ref('prompt')
const esamPrecision = ref('fp32')
const modelOptions = ref([])
const modelId = ref(null)
const conf = ref(0.25)
const promptClasses = ref('')
const file = ref(null)
const samFile = ref(null)

const originImgUrl = ref('')
const previewUrl = ref('')
const running = ref(false)
const processed = ref(0)
const total = ref(0)
const resultImg = ref('')
const segCount = ref(0)
const detections = ref([])
const resultUrl = ref('')
const stats = ref({})

const origViewer = ref(false)
const resultViewer = ref(false)
const origViewport = ref(null)
const resultViewport = ref(null)
const imgEl = ref(null)
const resultImgEl = ref(null)
const overlayEl = ref(null)
const origVideoEl = ref(null)
const resultVideoEl = ref(null)

const points = ref([])
const pointLabels = ref([])
const promptBox = ref(null)
let boxDragging = false
let boxStart = null
let suppressClick = false

let originBlobUrl = null
let resultBlobUrl = null
let pollTimer = null

const isVideoMode = computed(() => (engine.value === 'rfdetr' || engine.value === 'ultralytics' || engine.value === 'yolo-master') && mode.value === 'video')
const isImageMode = computed(() => !isVideoMode.value)
const isInteractiveEngine = computed(() => engine.value === 'mobilesam' || engine.value === 'efficientsam')
const isSamPrompt = computed(() =>
  engine.value === 'efficientsam' || (engine.value === 'mobilesam' && samMode.value === 'prompt'))
const hasContent = computed(() => !!(originImgUrl.value || previewUrl.value || resultImg.value || resultUrl.value))
const samEngineLabel = computed(() => (engine.value === 'efficientsam' ? 'EfficientSAM' : 'MobileSAM'))
const maxPromptPoints = computed(() => {
  if (engine.value !== 'efficientsam') return Infinity
  return promptBox.value ? 4 : 6
})

/**
 * 下拉始终展示全部可用分割模型（含 EfficientSAM），避免只停在 RF-DETR Tab 时找不到。
 * 选中模型会通过 onModelChange 自动切换对应引擎 Tab。
 */
const filteredModels = computed(() => filterSegModelsByEngine(modelOptions.value, null))

const emptyModelTitle = computed(() => {
  if (!modelOptions.value.length) {
    return '暂无可用分割模型：请到「模型管理」拉取 RF-DETR / YOLOE / MobileSAM / efficient-sam（opencv-sam）。'
  }
  if (engine.value === 'efficientsam' && !filterSegModelsByEngine(modelOptions.value, 'efficientsam').length) {
    return '暂无 EfficientSAM 模型：请到「模型管理」拉取 efficient-sam（library=opencv-sam）。若已拉取请硬刷新页面。'
  }
  return ''
})

const pickLabel = computed(() => {
  if (isInteractiveEngine.value) return '选择图片'
  return mode.value === 'image' ? '选择图片' : '选择视频'
})

const canRun = computed(() => {
  if (!modelId.value) return false
  if (engine.value === 'mobilesam') {
    if (samMode.value === 'auto') return !!file.value
    return !!samFile.value && (points.value.length > 0 || !!promptBox.value)
  }
  if (engine.value === 'efficientsam') {
    return !!samFile.value && (points.value.length > 0 || !!promptBox.value)
  }
  return !!file.value
})

const samInfer = useInferProgress(modelId)

const isSamRunning = computed(() => running.value && isInteractiveEngine.value)
const showProgressBar = computed(() => isVideoMode.value || isSamRunning.value)
const videoPercent = computed(() => (total.value ? Math.min(100, Math.floor((processed.value / total.value) * 100)) : 0))
const progressPercent = computed(() => (isVideoMode.value ? videoPercent.value : samInfer.percent.value))
const samElapsedText = computed(() => samInfer.elapsedText.value)
const progressTitle = computed(() => {
  if (isVideoMode.value) return `视频分割中… ${processed.value}/${total.value || '?'} 帧`
  if (isSamRunning.value) {
    const modeLabel = engine.value === 'mobilesam' && samMode.value === 'auto' ? '全自动' : '交互'
    return `${samEngineLabel.value} ${modeLabel}分割中… 预计剩余 ${samInfer.etaText.value}`
  }
  return '分割中…'
})

function useImageZoom(viewportRef, imgRef) {
  const zoom = ref(1)
  const fitZoom = ref(1)
  const naturalW = ref(0)
  const naturalH = ref(0)
  const pctText = computed(() => `${Math.round(zoom.value * 100)}%`)
  const spacerStyle = computed(() => ({
    width: `${Math.max(1, naturalW.value * zoom.value)}px`,
    height: `${Math.max(1, naturalH.value * zoom.value)}px`
  }))
  const innerStyle = computed(() => ({
    transform: `scale(${zoom.value})`,
    transformOrigin: '0 0',
    width: naturalW.value ? `${naturalW.value}px` : 'auto'
  }))

  function onImageLoad() {
    const img = imgRef.value
    if (!img) return
    naturalW.value = img.naturalWidth || img.width
    naturalH.value = img.naturalHeight || img.height
    calcFit()
  }

  function calcFit() {
    nextTick(() => {
      const vp = viewportRef.value
      if (!vp || !naturalW.value) return
      const pad = 16
      fitZoom.value = Math.min((vp.clientWidth - pad) / naturalW.value,
        (vp.clientHeight - pad) / naturalH.value, 1)
      zoom.value = fitZoom.value
    })
  }

  function zoomIn() { zoom.value = Math.min(4, +(zoom.value + 0.15).toFixed(2)) }
  function zoomOut() { zoom.value = Math.max(0.15, +(zoom.value - 0.15).toFixed(2)) }
  function zoomFit() { zoom.value = fitZoom.value }
  function onWheel(e) {
    const delta = e.deltaY > 0 ? -0.1 : 0.1
    zoom.value = Math.max(0.15, Math.min(4, +(zoom.value + delta).toFixed(2)))
  }

  return { pctText, spacerStyle, innerStyle, onImageLoad, calcFit, zoomIn, zoomOut, zoomFit, onWheel }
}

const origZoom = useImageZoom(origViewport, imgEl)
const resultZoom = useImageZoom(resultViewport, resultImgEl)

function setOriginImgUrl(raw) {
  revokeOriginImg()
  if (raw) {
    originBlobUrl = URL.createObjectURL(raw)
    originImgUrl.value = originBlobUrl
  }
}

function revokeOriginImg() {
  if (originBlobUrl) {
    URL.revokeObjectURL(originBlobUrl)
    originBlobUrl = null
  }
  originImgUrl.value = ''
}

const onOrigLoad = () => {
  origZoom.onImageLoad()
  syncCanvas()
}

const onResultLoad = () => {
  resultZoom.onImageLoad()
}

const syncCanvas = () => {
  const img = imgEl.value
  const cv = overlayEl.value
  if (!img || !cv) return
  cv.width = img.naturalWidth
  cv.height = img.naturalHeight
  drawPoints()
}

const drawPoints = () => {
  const cv = overlayEl.value
  if (!cv) return
  const ctx = cv.getContext('2d')
  ctx.clearRect(0, 0, cv.width, cv.height)
  if (promptBox.value) {
    const [x1, y1, x2, y2] = promptBox.value
    ctx.strokeStyle = '#409eff'
    ctx.lineWidth = 2
    ctx.strokeRect(x1, y1, x2 - x1, y2 - y1)
  }
  points.value.forEach((p, i) => {
    const lbl = pointLabels.value[i]
    ctx.beginPath()
    ctx.arc(p[0], p[1], 8, 0, Math.PI * 2)
    ctx.fillStyle = lbl === 1 ? '#67c23a' : '#f56c6c'
    ctx.fill()
    ctx.strokeStyle = '#fff'
    ctx.lineWidth = 2
    ctx.stroke()
  })
}

const canvasToImageXY = (e) => {
  const cv = overlayEl.value
  const scale = cv.width / cv.clientWidth
  return [Math.round(e.offsetX * scale), Math.round(e.offsetY * scale)]
}

const onCanvasMouseDown = (e) => {
  if (!isSamPrompt.value || resultImg.value || e.shiftKey) return
  boxDragging = true
  boxStart = canvasToImageXY(e)
  suppressClick = false
}

const onCanvasMouseMove = (e) => {
  if (!boxDragging || !boxStart) return
  const [x2, y2] = canvasToImageXY(e)
  const [x1, y1] = boxStart
  if (Math.abs(x2 - x1) + Math.abs(y2 - y1) > 6) suppressClick = true
  promptBox.value = [
    Math.min(x1, x2), Math.min(y1, y2),
    Math.max(x1, x2), Math.max(y1, y2),
  ]
  drawPoints()
}

const onCanvasMouseUp = () => {
  if (!boxDragging) return
  boxDragging = false
  boxStart = null
  if (promptBox.value) {
    const [x1, y1, x2, y2] = promptBox.value
    if (Math.abs(x2 - x1) < 4 || Math.abs(y2 - y1) < 4) promptBox.value = null
  }
  drawPoints()
}

const onCanvasClick = (e) => {
  if (!isSamPrompt.value || resultImg.value) return
  if (suppressClick) {
    suppressClick = false
    return
  }
  if (points.value.length >= maxPromptPoints.value) {
    ElMessage.warning(engine.value === 'efficientsam'
      ? `EfficientSAM 最多 ${maxPromptPoints.value} 个点（含框时更少）`
      : '标注点已达上限')
    return
  }
  const xy = canvasToImageXY(e)
  points.value.push(xy)
  pointLabels.value.push(e.shiftKey ? 0 : 1)
  drawPoints()
}

const clearPoints = () => {
  points.value = []
  pointLabels.value = []
  promptBox.value = null
  boxDragging = false
  boxStart = null
  drawPoints()
}

const enterVideoFs = (which) => {
  const el = which === 'orig' ? origVideoEl.value : resultVideoEl.value
  if (!el) return
  const req = el.requestFullscreen || el.webkitRequestFullscreen
  if (req) req.call(el)
  else ElMessage.info('当前浏览器不支持全屏')
}

const loadModels = async () => {
  try {
    modelOptions.value = await loadSegmentationModels(modelApi)
    modelId.value = pickPreferredSegModel(modelOptions.value, engine.value, modelId.value)
  } catch {
    ElMessage.error('加载模型列表失败')
  }
}

const onEngineChange = () => {
  clearAll()
  modelId.value = pickPreferredSegModel(modelOptions.value, engine.value, null)
}

const onModelChange = (id) => {
  const m = modelOptions.value.find((x) => x.id === id)
  const next = resolveSegEngine(m)
  if (next && next !== engine.value) {
    engine.value = next
    clearAll()
    modelId.value = id
  }
}

const onPick = (uploadFile) => {
  const raw = uploadFile.raw
  const isVideo = isVideoMode.value
  if (!raw || (isVideo ? !raw.type.startsWith('video/') : !raw.type.startsWith('image/'))) {
    ElMessage.error(isVideo ? '请选择视频' : '请选择图片')
    return
  }
  file.value = raw
  resultImg.value = ''
  detections.value = []
  clearVideoOut()
  if (isVideo) {
    revokeOriginImg()
    if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
    previewUrl.value = URL.createObjectURL(raw)
  } else {
    setOriginImgUrl(raw)
    if (previewUrl.value) { URL.revokeObjectURL(previewUrl.value); previewUrl.value = '' }
  }
}

const onPickSam = (uploadFile) => {
  const raw = uploadFile.raw
  if (!raw?.type.startsWith('image/')) {
    ElMessage.error('请选择图片')
    return
  }
  samFile.value = raw
  file.value = raw
  resultImg.value = ''
  points.value = []
  pointLabels.value = []
  promptBox.value = null
  setOriginImgUrl(raw)
}

const run = async () => {
  if (isVideoMode.value) return runVideo()
  return runImage()
}

const runImage = async () => {
  const isSam = isInteractiveEngine.value
  running.value = true
  resultImg.value = ''
  detections.value = []
  if (isSam) samInfer.start()
  try {
    const fd = new FormData()
    const src = isSamPrompt.value ? samFile.value : file.value
    fd.append('file', src)
    fd.append('conf', conf.value)
    if (engine.value === 'ultralytics' && promptClasses.value.trim()) {
      fd.append('classes', promptClasses.value.trim())
    }
    if (engine.value === 'mobilesam') {
      fd.append('mode', samMode.value)
      if (samMode.value === 'prompt') {
        fd.append('points', JSON.stringify(points.value))
        fd.append('pointLabels', JSON.stringify(pointLabels.value))
        if (promptBox.value) fd.append('box', JSON.stringify(promptBox.value))
      }
    }
    if (engine.value === 'efficientsam') {
      fd.append('points', JSON.stringify(points.value))
      fd.append('pointLabels', JSON.stringify(pointLabels.value))
      if (promptBox.value) fd.append('box', JSON.stringify(promptBox.value))
      fd.append('precision', esamPrecision.value)
    }
    const res = await modelApi.segment(modelId.value, fd)
    const d = res.data
    segCount.value = d.count
    detections.value = d.detections || []
    resultImg.value = d.imageBase64 ? `data:image/jpeg;base64,${d.imageBase64}` : ''
    nextTick(() => resultZoom.calcFit())
  } catch (e) {
    ElMessage.error(e?.response?.data?.message || '分割失败')
  } finally {
    if (isSam) samInfer.finish()
    running.value = false
  }
}

const runVideo = async () => {
  running.value = true
  processed.value = 0
  total.value = 0
  clearVideoOut()
  try {
    const fd = new FormData()
    fd.append('file', file.value)
    fd.append('conf', conf.value)
    if (engine.value === 'ultralytics' && promptClasses.value.trim()) {
      fd.append('classes', promptClasses.value.trim())
    }
    const res = await modelApi.segmentVideo(modelId.value, fd)
    const jobId = res.data.jobId
    pollTimer = setInterval(async () => {
      try {
        const pr = await modelApi.videoProgress(modelId.value, jobId)
        const d = pr.data
        processed.value = d.processed || 0
        total.value = d.total || 0
        if (d.status === 'done') {
          clearInterval(pollTimer)
          pollTimer = null
          stats.value = d.stats || {}
          const blob = await modelApi.outputVideo(d.stats.output)
          resultBlobUrl = URL.createObjectURL(blob)
          resultUrl.value = resultBlobUrl
          running.value = false
        } else if (d.status === 'error') {
          clearInterval(pollTimer)
          pollTimer = null
          ElMessage.error(d.error || '视频分割失败')
          running.value = false
        }
      } catch {
        clearInterval(pollTimer)
        pollTimer = null
        running.value = false
      }
    }, 1500)
  } catch {
    ElMessage.error('启动视频分割失败')
    running.value = false
  }
}

const clearVideoOut = () => {
  if (resultBlobUrl) { URL.revokeObjectURL(resultBlobUrl); resultBlobUrl = null }
  resultUrl.value = ''
  stats.value = {}
}

const clearAll = () => {
  file.value = null
  samFile.value = null
  resultImg.value = ''
  detections.value = []
  segCount.value = 0
  points.value = []
  pointLabels.value = []
  promptBox.value = null
  boxDragging = false
  boxStart = null
  clearVideoOut()
  revokeOriginImg()
  if (previewUrl.value) { URL.revokeObjectURL(previewUrl.value); previewUrl.value = '' }
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
  samInfer.stop()
  running.value = false
  origViewer.value = false
  resultViewer.value = false
}

const downloadImg = () => {
  const a = document.createElement('a')
  a.href = resultImg.value
  a.download = 'segment_result.jpg'
  a.click()
}

const downloadVideo = () => {
  const a = document.createElement('a')
  a.href = resultUrl.value
  a.download = 'segment_result.mp4'
  a.click()
}

onMounted(loadModels)
onBeforeUnmount(clearAll)
</script>

<style scoped>
.segment-root { padding-bottom: 16px; }
.cfg-card { margin-bottom: 12px; }
.hint { margin: 8px 0 0; font-size: 13px; color: #909399; }
.media-row { margin-bottom: 12px; }

.media-panel {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  overflow: hidden;
  background: #fff;
  min-height: 420px;
}
.video-panel { min-height: auto; }

.panel-hd {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  background: #f8fafc;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.panel-title { font-weight: 600; font-size: 14px; color: #303133; }
.panel-hint { font-size: 12px; color: #909399; flex: 1; min-width: 80px; }
.panel-hint.ok { color: #67c23a; }

.zoom-toolbar {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-left: auto;
}
.zoom-pct { min-width: 58px; font-variant-numeric: tabular-nums; font-size: 12px; }

.zoom-viewport {
  flex: 1;
  min-height: 360px;
  max-height: 560px;
  overflow: auto;
  background: repeating-conic-gradient(#e8eaed 0% 25%, #f4f5f7 0% 50%) 50% / 16px 16px;
  padding: 8px;
}
.zoom-spacer { position: relative; min-width: 1px; min-height: 1px; }
.zoom-inner { position: absolute; top: 0; left: 0; line-height: 0; }

.canvas-host { position: relative; display: inline-block; }
.panel-img { display: block; width: auto; height: auto; max-width: none; }
.overlay-canvas {
  position: absolute; inset: 0; width: 100%; height: 100%;
  cursor: crosshair;
}

.panel-loading {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: #909399;
  min-height: 360px;
}
.rotating { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.video-wrap {
  padding: 12px;
  background: #0f0f0f;
  display: flex;
  justify-content: center;
}
.video-el {
  width: 100%;
  max-height: 480px;
  background: #000;
}
.stats { padding: 10px 14px; display: flex; gap: 8px; flex-wrap: wrap; }

.progress-box { padding: 4px 2px; }
.progress-title { margin-bottom: 10px; font-weight: 600; color: #3a4a63; }
.progress-hint { margin-top: 8px; font-size: 12px; color: #909399; }
</style>
