<template>
  <div class="wb-grid">
    <section class="wb-controls" aria-label="车牌四点检测输入与参数">
      <div class="wb-control-group">
        <h3>待检测图像</h3>
        <label class="wb-dropzone" :class="{ 'is-dragging': dragging, 'is-disabled': busy }" @dragenter.prevent="onDragEnter" @dragover.prevent @dragleave.prevent="onDragLeave" @drop.prevent="onDrop">
          <input type="file" accept="image/*" :disabled="busy" @change="onFileChange">
          <strong>{{ file ? file.name : '拖入图片或选择文件' }}</strong>
          <span>{{ inputHint }}</span>
        </label>
        <button v-if="file" class="wb-text-button" type="button" :disabled="busy" @click="clearFile">清除图片</button>
      </div>

      <div class="wb-control-group">
        <div class="wb-control-heading"><h3>检测参数</h3><button class="wb-text-button" type="button" :disabled="busy" @click="resetParameters">恢复默认</button></div>
        <label class="wb-field">
          <span>置信度 <output>{{ Number(conf).toFixed(2) }}</output></span>
          <input v-model.number="conf" type="range" min="0" max="1" step="0.01" :disabled="busy">
        </label>
        <label class="wb-field">
          <span>推理尺寸</span>
          <input v-model.number="imgsz" type="number" min="32" max="4096" step="32" :disabled="busy">
        </label>
      </div>

      <aside class="wb-capability-note">
        <strong>Pose / 透视定位</strong>
        <p>优先使用四点坐标做透视矫正；本场景只定位车牌，不把检测框冒充 OCR 结果。</p>
        <RouterLink to="/ai/paddleocr">将矫正图送入 OCR <span aria-hidden="true">→</span></RouterLink>
      </aside>

      <div v-if="validationMessage" class="wb-form-error" role="alert">{{ validationMessage }}</div>
      <button class="scenario-button wb-run" type="button" :disabled="!canRun" @click="runInference">
        {{ busy ? '正在检测…' : '运行真实检测' }}
      </button>
    </section>

    <section class="wb-canvas" aria-label="车牌四点画布">
      <header class="wb-canvas__header">
        <div><strong>四点画布</strong><span>bbox / quad / keypoints</span></div>
        <span v-if="normalizedResult.detections.length">{{ normalizedResult.detections.length }} 个目标</span>
      </header>
      <div v-if="previewUrl" class="wb-canvas-stage">
        <img ref="imageElement" :src="previewUrl" alt="待检测车牌图片" @load="onImageLoad">
        <canvas ref="overlayCanvas" aria-hidden="true"></canvas>
      </div>
      <div v-else class="wb-canvas-empty">
        <span aria-hidden="true">◇</span>
        <strong>等待车牌图像</strong>
        <p>返回四点或关键点后叠加透视几何。</p>
      </div>
      <div v-if="crops.length" class="wb-crop-strip" aria-label="车牌裁剪预览">
        <button v-for="crop in crops" :key="crop.index" type="button" :class="{ 'is-active': selectedIndex === crop.index }" @click="selectDetection(crop.index)">
          <img :src="crop.url" :alt="`车牌裁剪 ${crop.index + 1}`">
          <span>#{{ crop.index + 1 }}</span>
        </button>
      </div>
    </section>

    <ResultPanel
      title="车牌四点输出"
      :result="runOutput"
      :busy="busy"
      :error="error"
      :elapsed-ms="elapsedMs"
      :image-url="resultImageUrl"
      :filename="`${scenario.modelKey}-plate-pose`"
    >
      <div v-if="normalizedResult.detections.length" class="wb-result-content">
        <div class="wb-metrics">
          <div><span>检测数</span><strong>{{ normalizedResult.detections.length }}</strong></div>
          <div><span>四点框</span><strong>{{ quadCount }}</strong></div>
          <div><span>关键点</span><strong>{{ keypointCount }}</strong></div>
        </div>
        <div class="wb-table-wrap">
          <table class="wb-table">
            <thead><tr><th>#</th><th>类别</th><th>置信度</th><th>坐标</th><th>四点</th></tr></thead>
            <tbody>
              <tr
                v-for="(item, index) in normalizedResult.detections"
                :key="index"
                :class="{ 'is-selected': selectedIndex === index }"
                tabindex="0"
                @click="selectDetection(index)"
                @keydown.enter="selectDetection(index)"
                @keydown.space.prevent="selectDetection(index)"
              >
                <td>{{ index + 1 }}</td>
                <td>{{ item.className || (item.classId ?? '—') }}</td>
                <td>{{ typeof item.confidence === 'number' ? item.confidence.toFixed(4) : '—' }}</td>
                <td>{{ item.bbox ? item.bbox.join(', ') : '未返回' }}</td>
                <td>{{ item.quad ? item.quad.map((point) => `[${point.join(', ')}]`).join(' ') : '未返回' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="wb-result-note">响应仅证明车牌几何已定位；透视矫正后的字符识别须走独立 OCR 流程。</p>
      </div>
      <div v-else class="wb-normal-empty">
        <strong>没有检测到车牌</strong>
        <p>这是正常空结果。可降低置信度、提高推理尺寸或更换清晰输入。</p>
      </div>
    </ResultPanel>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'

import { scenarioApi } from '../../../../api/modelScenarios'
import ResultPanel from '../components/ResultPanel.vue'
import {
  createAsyncRequestGuard,
  isAcceptedImageCandidate,
  normalizeWorkbenchResult,
  scaleDetectionGeometry,
  serializeScenarioForm,
  validateWorkbenchState,
} from '../scenarioState'

const props = defineProps({ scenario: { type: Object, required: true } })
const emit = defineEmits(['completed'])
const requestGuard = createAsyncRequestGuard()

const file = ref(null)
const previewUrl = ref('')
const dragging = ref(false)
const conf = ref(Number(props.scenario.defaults?.conf ?? 0.5))
const imgsz = ref(Number(props.scenario.defaults?.imgsz ?? 640))
const busy = ref(false)
const error = ref('')
const runOutput = ref(null)
const normalizedResult = ref({ detections: [] })
const elapsedMs = ref(null)
const imageElement = ref(null)
const overlayCanvas = ref(null)
const crops = ref([])
const selectedIndex = ref(0)

const inputHint = computed(() => `${props.scenario.input?.formats?.join(', ') || '图片'} · 最大 ${props.scenario.input?.maxSizeMb || '配置'} MB`)
const validationErrors = computed(() => validateWorkbenchState('plate_pose', {
  file: file.value,
  conf: conf.value,
  imgsz: imgsz.value,
}, props.scenario.input))
const validationMessage = computed(() => file.value ? validationErrors.value[0] || '' : '')
const canRun = computed(() => (props.scenario.apiReady ?? props.scenario.ready) && !busy.value && validationErrors.value.length === 0)
const resultImageUrl = computed(() => normalizedResult.value.imageBase64 ? `data:image/jpeg;base64,${normalizedResult.value.imageBase64}` : '')
const quadCount = computed(() => normalizedResult.value.detections.filter((item) => item.quad).length)
const keypointCount = computed(() => normalizedResult.value.detections.filter((item) => item.keypoints?.length).length)

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
  resetResult()
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
  resetResult()
}

function onDragEnter() {
  if (!busy.value) dragging.value = true
}

function onDragLeave() {
  if (!busy.value) dragging.value = false
}

function resetResult() {
  runOutput.value = null
  normalizedResult.value = { detections: [] }
  elapsedMs.value = null
  crops.value = []
  selectedIndex.value = 0
  drawOverlay()
}

function onImageLoad() {
  drawOverlay()
  createCrops()
}

function drawOverlay() {
  const image = imageElement.value
  const canvas = overlayCanvas.value
  if (!image || !canvas) return
  canvas.width = image.naturalWidth
  canvas.height = image.naturalHeight
  const context = canvas.getContext('2d')
  context.clearRect(0, 0, canvas.width, canvas.height)
  const shapes = scaleDetectionGeometry(normalizedResult.value, canvas.width, canvas.height)
  shapes.forEach((shape) => {
    const stroke = shape.index === selectedIndex.value ? '#f3a634' : '#5d9cff'
    context.strokeStyle = stroke
    context.lineWidth = Math.max(2, canvas.width / 450)
    if (shape.quad) {
      context.beginPath()
      shape.quad.forEach(([x, y], pointIndex) => (pointIndex ? context.lineTo(x, y) : context.moveTo(x, y)))
      context.closePath()
      context.fillStyle = shape.index === selectedIndex.value ? 'rgba(243, 166, 52, .14)' : 'rgba(93, 156, 255, .1)'
      context.fill()
      context.stroke()
    } else if (shape.bbox) {
      const [x1, y1, x2, y2] = shape.bbox
      context.strokeRect(x1, y1, x2 - x1, y2 - y1)
    }
    const points = shape.keypoints?.length ? shape.keypoints : shape.quad
    ;(points || []).forEach((point) => {
      if (point.length >= 3 && point[2] <= 0) return
      context.beginPath()
      context.arc(point[0], point[1], Math.max(3, canvas.width / 220), 0, Math.PI * 2)
      context.fillStyle = stroke
      context.fill()
    })
    const labelOrigin = shape.quad?.[0] || (shape.bbox ? [shape.bbox[0], shape.bbox[1]] : null)
    if (labelOrigin) {
      const [x, y] = labelOrigin
      context.fillStyle = stroke
      context.fillRect(x, Math.max(0, y - 22), 34, 22)
      context.fillStyle = '#fff'
      context.font = `${Math.max(12, canvas.width / 70)}px sans-serif`
      context.fillText(`#${shape.index + 1}`, x + 4, Math.max(15, y - 6))
    }
  })
}

function createCrops() {
  const image = imageElement.value
  if (!image?.naturalWidth) return
  crops.value = normalizedResult.value.detections.flatMap((item, index) => {
    let x1
    let y1
    let x2
    let y2
    if (item.quad) {
      const xs = item.quad.map((point) => point[0])
      const ys = item.quad.map((point) => point[1])
      x1 = Math.min(...xs)
      y1 = Math.min(...ys)
      x2 = Math.max(...xs)
      y2 = Math.max(...ys)
    } else if (item.bbox) {
      ;[x1, y1, x2, y2] = item.bbox
    } else {
      return []
    }
    x1 = Math.max(0, Math.min(image.naturalWidth, x1))
    y1 = Math.max(0, Math.min(image.naturalHeight, y1))
    x2 = Math.max(0, Math.min(image.naturalWidth, x2))
    y2 = Math.max(0, Math.min(image.naturalHeight, y2))
    if (x2 <= x1 || y2 <= y1) return []
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.round(x2 - x1))
    canvas.height = Math.max(1, Math.round(y2 - y1))
    canvas.getContext('2d').drawImage(image, x1, y1, x2 - x1, y2 - y1, 0, 0, canvas.width, canvas.height)
    return [{ index, url: canvas.toDataURL('image/jpeg') }]
  })
}

function selectDetection(index) {
  if (busy.value) return
  selectedIndex.value = index
  drawOverlay()
}

function resetParameters() {
  if (busy.value) return
  conf.value = Number(props.scenario.defaults?.conf ?? 0.5)
  imgsz.value = Number(props.scenario.defaults?.imgsz ?? 640)
}

async function runInference() {
  if (!canRun.value) return
  const requestToken = requestGuard.begin()
  busy.value = true
  error.value = ''
  resetResult()
  try {
    const form = serializeScenarioForm('plate_pose', { file: file.value, conf: conf.value, imgsz: imgsz.value })
    const response = await scenarioApi.infer(props.scenario.modelKey, form)
    if (!requestGuard.isCurrent(requestToken)) return
    runOutput.value = response.data
    elapsedMs.value = Number.isFinite(response.data?.elapsedMs) ? response.data.elapsedMs : null
    normalizedResult.value = normalizeWorkbenchResult('plate_pose', response.data?.result)
    await nextTick()
    if (!requestGuard.isCurrent(requestToken)) return
    drawOverlay()
    createCrops()
    emit('completed', response.data)
  } catch (requestError) {
    if (requestGuard.isCurrent(requestToken)) {
      error.value = requestError?.response?.data?.message || requestError?.message || '车牌四点检测失败，请检查输入与运行环境。'
    }
  } finally {
    if (requestGuard.isCurrent(requestToken)) busy.value = false
  }
}

onBeforeUnmount(() => {
  requestGuard.dispose()
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
})
</script>
