<template>
  <div class="wb-grid">
    <section class="wb-controls" aria-label="分割输入与参数">
      <div class="wb-control-group">
        <h3>输入图像</h3>
        <label
          class="wb-dropzone"
          :class="{ 'is-dragging': dragging, 'is-disabled': busy }"
          @dragenter.prevent="onDragEnter"
          @dragover.prevent
          @dragleave.prevent="onDragLeave"
          @drop.prevent="onDrop"
        >
          <input type="file" accept="image/*" :disabled="busy" @change="onFileChange">
          <strong>{{ file ? file.name : '拖入图片或选择文件' }}</strong>
          <span>{{ inputHint }}</span>
        </label>
        <button v-if="file" class="wb-text-button" type="button" :disabled="busy" @click="clearFile">清除图片</button>
      </div>

      <div v-if="isMobileSam" class="wb-control-group">
        <div class="wb-control-heading"><h3>分割模式</h3><button class="wb-text-button" type="button" :disabled="busy" @click="resetParameters">恢复默认</button></div>
        <div class="wb-segmented" role="group" aria-label="分割模式">
          <button type="button" :disabled="busy" :class="{ 'is-active': mode === 'prompt' }" @click="setPromptMode">交互提示</button>
          <button type="button" :disabled="busy" :class="{ 'is-active': mode === 'auto' }" @click="setAutoMode">全自动</button>
        </div>
        <p>MobileSAM 支持交互提示与全自动模式。</p>
      </div>

      <div v-else class="wb-control-group">
        <div class="wb-control-heading"><h3>运行参数</h3><button class="wb-text-button" type="button" :disabled="busy" @click="resetParameters">恢复默认</button></div>
        <label class="wb-field">
          <span>ONNX 精度</span>
          <select v-model="precision" :disabled="busy">
            <option value="fp32">FP32 · 高精度</option>
            <option value="int8">INT8 · 低延迟</option>
          </select>
        </label>
        <p>EfficientSAM 使用固定模型权重，仅切换运行精度。</p>
      </div>

      <div v-if="mode === 'prompt'" class="wb-control-group">
        <h3>提示工具</h3>
        <div class="wb-tool-grid" role="group" aria-label="提示工具">
          <button type="button" :disabled="busy" :class="{ 'is-active': tool === 'positive' }" @click="setTool('positive')">＋ 正点</button>
          <button type="button" :disabled="busy" :class="{ 'is-active': tool === 'negative' }" @click="setTool('negative')">－ 负点</button>
          <button type="button" :disabled="busy" :class="{ 'is-active': tool === 'box' }" @click="setTool('box')">▱ 框选</button>
        </div>
        <div class="wb-inline-actions">
          <button class="wb-text-button" type="button" :disabled="!history.length || busy" @click="undoPrompt">撤销</button>
          <button class="wb-text-button" type="button" :disabled="!interactionCount || busy" @click="clearPrompts">清空提示</button>
        </div>
        <p>{{ interactionCount }} 次交互 · {{ points.length }} 点{{ box ? ' · 1 个框' : '' }}</p>
      </div>

      <div v-if="validationMessage" class="wb-form-error" role="alert">{{ validationMessage }}</div>
      <button class="scenario-button wb-run" type="button" :disabled="!canRun" @click="runInference">
        {{ busy ? '正在分割…' : '运行真实分割' }}
      </button>
    </section>

    <section class="wb-canvas" aria-label="交互分割画布">
      <header class="wb-canvas__header">
        <div><strong>提示画布</strong><span>{{ canvasStatus }}</span></div>
        <span v-if="file">{{ imageSize || '读取图像尺寸…' }}</span>
      </header>
      <div v-if="previewUrl" class="wb-canvas-stage" :class="{ 'is-disabled': mode === 'auto' || busy }">
        <img ref="imageElement" :src="previewUrl" alt="待分割图片预览" @load="onImageLoad">
        <canvas
          ref="overlayCanvas"
          tabindex="0"
          aria-label="在图片上添加正点、负点或框选提示"
          @pointerdown="onPointerDown"
          @pointermove="onPointerMove"
          @pointerup="onPointerUp"
          @pointercancel="cancelBox"
          @keydown.delete.prevent="undoPrompt"
          @keydown.backspace.prevent="undoPrompt"
        ></canvas>
      </div>
      <div v-else class="wb-canvas-empty">
        <span aria-hidden="true">⌖</span>
        <strong>画布等待图像</strong>
        <p>上传后将按原始像素坐标采集提示点和框。</p>
      </div>
    </section>

    <ResultPanel
      title="分割输出"
      :result="runOutput"
      :busy="busy"
      :error="error"
      :elapsed-ms="elapsedMs"
      :image-url="resultImageUrl"
      :filename="`${scenario.modelKey}-segmentation`"
    >
      <div v-if="normalizedResult.detections.length" class="wb-result-content">
        <img v-if="resultImageUrl" class="wb-result-image" :src="resultImageUrl" alt="后端返回的分割叠加图">
        <div class="wb-metrics">
          <div><span>MASK</span><strong>{{ normalizedResult.detections.length }}</strong></div>
          <div><span>交互</span><strong>{{ completedInteractions ?? '—' }}</strong></div>
          <div><span>面积</span><strong>{{ maskMetrics ? `${maskMetrics.area} px` : '未返回' }}</strong></div>
          <div><span>占比</span><strong>{{ maskMetrics ? `${(maskMetrics.ratio * 100).toFixed(2)}%` : '未返回' }}</strong></div>
        </div>
        <label v-if="maskOptions.length > 1" class="wb-field">
          <span>查看 mask</span>
          <select v-model.number="selectedMaskIndex" @change="measureSelectedMask">
            <option v-for="item in maskOptions" :key="item.index" :value="item.index">#{{ item.index + 1 }} {{ item.name }}</option>
          </select>
        </label>
        <img v-if="maskImageUrl" class="wb-mask-preview" :src="maskImageUrl" alt="后端返回的像素级 mask">
      </div>
      <div v-else class="wb-normal-empty">
        <strong>分割结果为空</strong>
        <p>后端未返回 mask；可调整提示位置或输入质量后重试。</p>
      </div>
    </ResultPanel>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'

import { scenarioApi } from '../../../../api/modelScenarios'
import ResultPanel from '../components/ResultPanel.vue'
import {
  clampImagePoint,
  deriveMaskMetrics,
  isAcceptedImageCandidate,
  isCurrentPreviewRequest,
  normalizeWorkbenchResult,
  serializeScenarioForm,
  undoSegmentationPrompt,
  validateWorkbenchState,
} from '../scenarioState'

const props = defineProps({ scenario: { type: Object, required: true } })
const emit = defineEmits(['completed'])

const file = ref(null)
const previewUrl = ref('')
const dragging = ref(false)
const busy = ref(false)
const error = ref('')
const runOutput = ref(null)
const normalizedResult = ref({ detections: [] })
const elapsedMs = ref(null)
const points = ref([])
const pointLabels = ref([])
const box = ref(null)
const history = ref([])
const tool = ref('positive')
const mode = ref('prompt')
const precision = ref('fp32')
const imageElement = ref(null)
const overlayCanvas = ref(null)
const imageSize = ref('')
const selectedMaskIndex = ref(0)
const maskMetrics = ref(null)
const completedInteractions = ref(null)
let boxStart = null
let activeBox = null
let maskRequestGeneration = 0

const isMobileSam = computed(() => props.scenario.modelKey === 'mobile-sam')
const inputHint = computed(() => {
  const formats = props.scenario.input?.formats?.join(', ') || '常见图片格式'
  return `${formats} · 最大 ${props.scenario.input?.maxSizeMb || '配置'} MB`
})
const interactionCount = computed(() => points.value.length + (box.value ? 1 : 0))
const validationErrors = computed(() => validateWorkbenchState('segmentation', {
  file: file.value,
  mode: mode.value,
  points: points.value,
  pointLabels: pointLabels.value,
  box: box.value,
}, props.scenario.input))
const validationMessage = computed(() => file.value ? validationErrors.value[0] || '' : '')
const canRun = computed(() => props.scenario.ready && !busy.value && validationErrors.value.length === 0)
const canvasStatus = computed(() => {
  if (mode.value === 'auto') return '全自动模式无需提示'
  if (tool.value === 'box') return '拖动绘制提示框'
  return tool.value === 'positive' ? '点击添加正点' : '点击添加负点'
})
const resultImageUrl = computed(() => normalizedResult.value.imageBase64
  ? `data:image/jpeg;base64,${normalizedResult.value.imageBase64}` : '')
const maskOptions = computed(() => normalizedResult.value.detections
  .map((item, index) => ({ index, name: item.className || 'segment', available: Boolean(item.maskBase64) }))
  .filter((item) => item.available))
const maskImageUrl = computed(() => {
  const base64 = normalizedResult.value.detections[selectedMaskIndex.value]?.maskBase64
  return base64 ? `data:image/png;base64,${base64}` : ''
})

function setFile(nextFile) {
  if (busy.value) return
  if (!isAcceptedImageCandidate(nextFile, props.scenario.input?.formats)) {
    error.value = '请选择浏览器可预览的图片文件。'
    return
  }
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  file.value = nextFile
  previewUrl.value = URL.createObjectURL(nextFile)
  error.value = ''
  runOutput.value = null
  normalizedResult.value = { detections: [] }
  elapsedMs.value = null
  maskMetrics.value = null
  maskRequestGeneration += 1
  clearPrompts()
}

function onFileChange(event) {
  if (busy.value) return
  setFile(event.target.files?.[0])
  event.target.value = ''
}

function onDrop(event) {
  if (busy.value) return
  dragging.value = false
  setFile(event.dataTransfer?.files?.[0])
}

function clearFile() {
  if (busy.value) return
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  file.value = null
  previewUrl.value = ''
  imageSize.value = ''
  runOutput.value = null
  normalizedResult.value = { detections: [] }
  elapsedMs.value = null
  maskMetrics.value = null
  maskRequestGeneration += 1
  clearPrompts()
}

function onDragEnter() {
  if (!busy.value) dragging.value = true
}

function onDragLeave() {
  if (!busy.value) dragging.value = false
}

function onImageLoad() {
  const image = imageElement.value
  const canvas = overlayCanvas.value
  if (!image || !canvas) return
  canvas.width = image.naturalWidth
  canvas.height = image.naturalHeight
  imageSize.value = `${image.naturalWidth} × ${image.naturalHeight}`
  drawPrompts()
}

function pointerCoordinates(event) {
  const canvas = overlayCanvas.value
  const bounds = canvas.getBoundingClientRect()
  return clampImagePoint([
    Math.round((event.clientX - bounds.left) * canvas.width / bounds.width),
    Math.round((event.clientY - bounds.top) * canvas.height / bounds.height),
  ], canvas.width, canvas.height)
}

function promptSnapshot() {
  return {
    points: points.value.map((point) => [...point]),
    pointLabels: [...pointLabels.value],
    box: box.value ? [...box.value] : null,
  }
}

function onPointerDown(event) {
  if (mode.value === 'auto' || busy.value || !overlayCanvas.value) return
  overlayCanvas.value.setPointerCapture?.(event.pointerId)
  const point = pointerCoordinates(event)
  if (tool.value === 'box') {
    boxStart = point
    activeBox = [point[0], point[1], point[0], point[1]]
    return
  }
  history.value.push(promptSnapshot())
  points.value.push(point)
  pointLabels.value.push(tool.value === 'positive' ? 1 : 0)
  drawPrompts()
}

function onPointerMove(event) {
  if (busy.value || !boxStart || tool.value !== 'box') return
  const [x, y] = pointerCoordinates(event)
  activeBox = [Math.min(boxStart[0], x), Math.min(boxStart[1], y), Math.max(boxStart[0], x), Math.max(boxStart[1], y)]
  drawPrompts()
}

function onPointerUp(event) {
  if (busy.value || !boxStart || tool.value !== 'box') return
  const [x, y] = pointerCoordinates(event)
  const nextBox = [Math.min(boxStart[0], x), Math.min(boxStart[1], y), Math.max(boxStart[0], x), Math.max(boxStart[1], y)]
  boxStart = null
  activeBox = null
  if (nextBox[2] - nextBox[0] >= 3 && nextBox[3] - nextBox[1] >= 3) {
    history.value.push(promptSnapshot())
    box.value = nextBox
  }
  drawPrompts()
}

function cancelBox() {
  boxStart = null
  activeBox = null
  drawPrompts()
}

function drawPrompts() {
  const canvas = overlayCanvas.value
  if (!canvas) return
  const context = canvas.getContext('2d')
  context.clearRect(0, 0, canvas.width, canvas.height)
  const promptBox = activeBox || box.value
  if (promptBox) {
    context.strokeStyle = '#5d9cff'
    context.lineWidth = Math.max(2, canvas.width / 500)
    context.setLineDash([10, 6])
    context.strokeRect(promptBox[0], promptBox[1], promptBox[2] - promptBox[0], promptBox[3] - promptBox[1])
    context.setLineDash([])
  }
  points.value.forEach(([x, y], index) => {
    context.beginPath()
    context.arc(x, y, Math.max(6, canvas.width / 130), 0, Math.PI * 2)
    context.fillStyle = pointLabels.value[index] === 1 ? '#42c8a0' : '#e24f59'
    context.fill()
    context.strokeStyle = '#ffffff'
    context.lineWidth = Math.max(2, canvas.width / 500)
    context.stroke()
  })
}

function undoPrompt() {
  if (busy.value) return
  const snapshot = history.value.pop()
  if (!snapshot) return
  const next = undoSegmentationPrompt({ points: points.value, pointLabels: pointLabels.value, box: box.value }, snapshot)
  points.value = next.points
  pointLabels.value = next.pointLabels
  box.value = next.box
  drawPrompts()
}

function clearPrompts() {
  if (busy.value) return
  points.value = []
  pointLabels.value = []
  box.value = null
  history.value = []
  cancelBox()
}

function setAutoMode() {
  if (busy.value) return
  mode.value = 'auto'
  clearPrompts()
}

function resetParameters() {
  if (busy.value) return
  mode.value = 'prompt'
  precision.value = 'fp32'
}

function setPromptMode() {
  if (!busy.value) mode.value = 'prompt'
}

function setTool(nextTool) {
  if (!busy.value) tool.value = nextTool
}

async function measureSelectedMask() {
  const generation = ++maskRequestGeneration
  const requestedUrl = maskImageUrl.value
  maskMetrics.value = null
  if (!requestedUrl) return
  const image = new Image()
  image.onload = () => {
    if (!isCurrentPreviewRequest(generation, maskRequestGeneration, requestedUrl, maskImageUrl.value)) return
    const canvas = document.createElement('canvas')
    canvas.width = image.naturalWidth
    canvas.height = image.naturalHeight
    const context = canvas.getContext('2d', { willReadFrequently: true })
    context.drawImage(image, 0, 0)
    const metrics = deriveMaskMetrics(
      context.getImageData(0, 0, canvas.width, canvas.height).data,
      canvas.width,
      canvas.height,
    )
    if (isCurrentPreviewRequest(generation, maskRequestGeneration, requestedUrl, maskImageUrl.value)) {
      maskMetrics.value = metrics
    }
  }
  image.src = requestedUrl
}

async function runInference() {
  if (!canRun.value) return
  busy.value = true
  error.value = ''
  runOutput.value = null
  normalizedResult.value = { detections: [] }
  elapsedMs.value = null
  maskMetrics.value = null
  maskRequestGeneration += 1
  completedInteractions.value = interactionCount.value
  try {
    const form = serializeScenarioForm('segmentation', {
      file: file.value,
      points: points.value,
      pointLabels: pointLabels.value,
      box: box.value,
      mode: isMobileSam.value ? mode.value : undefined,
      precision: isMobileSam.value ? undefined : precision.value,
    })
    const response = await scenarioApi.infer(props.scenario.modelKey, form)
    runOutput.value = response.data
    elapsedMs.value = Number.isFinite(response.data?.elapsedMs) ? response.data.elapsedMs : null
    normalizedResult.value = normalizeWorkbenchResult('segmentation', response.data?.result)
    selectedMaskIndex.value = maskOptions.value[0]?.index ?? 0
    await nextTick()
    measureSelectedMask()
    emit('completed', response.data)
  } catch (requestError) {
    error.value = requestError?.response?.data?.message || requestError?.message || '分割推理失败，请检查输入与运行环境。'
  } finally {
    busy.value = false
  }
}

onBeforeUnmount(() => {
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
})
</script>
