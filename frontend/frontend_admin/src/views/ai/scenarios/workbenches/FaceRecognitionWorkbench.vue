<template>
  <div class="wb-grid">
    <section class="wb-controls" aria-label="人脸识别输入与参数">
      <div class="wb-control-group">
        <h3>待识别图像</h3>
        <label class="wb-dropzone" :class="{ 'is-dragging': dragging, 'is-disabled': busy }" @dragenter.prevent="onDragEnter" @dragover.prevent @dragleave.prevent="onDragLeave" @drop.prevent="onDrop">
          <input type="file" accept="image/*" :disabled="busy" @change="onFileChange">
          <strong>{{ file ? file.name : '拖入图片或选择文件' }}</strong>
          <span>{{ inputHint }}</span>
        </label>
        <button v-if="file" class="wb-text-button" type="button" :disabled="busy" @click="clearFile">清除图片</button>
      </div>

      <div class="wb-control-group">
        <div class="wb-control-heading"><h3>识别参数</h3><button class="wb-text-button" type="button" :disabled="busy" @click="resetParameters">恢复默认</button></div>
        <label class="wb-field">
          <span>匹配阈值 <output>{{ Number(threshold).toFixed(2) }}</output></span>
          <input v-model.number="threshold" type="range" min="0" max="1" step="0.01" :disabled="busy">
        </label>
        <label class="wb-field">
          <span>检测阈值 <output>{{ Number(detThresh).toFixed(2) }}</output></span>
          <input v-model.number="detThresh" type="range" min="0" max="1" step="0.01" :disabled="busy">
        </label>
        <p>后端按匹配阈值返回身份或拒识；页面不重写判定。</p>
      </div>

      <aside class="wb-capability-note">
        <strong>1:N 底库比对</strong>
        <p>需先在人脸管理中登记授权人员；未登记时只能得到检测框与未知身份。</p>
        <RouterLink to="/ai/face">前往人脸登记 <span aria-hidden="true">→</span></RouterLink>
      </aside>

      <div v-if="validationMessage" class="wb-form-error" role="alert">{{ validationMessage }}</div>
      <button class="scenario-button wb-run" type="button" :disabled="!canRun" @click="runInference">
        {{ busy ? '正在识别…' : '运行真实识别' }}
      </button>
    </section>

    <section class="wb-canvas" aria-label="人脸识别画布">
      <header class="wb-canvas__header">
        <div><strong>识别画布</strong><span>检测框与身份叠加</span></div>
        <span v-if="normalizedResult.detections.length">{{ normalizedResult.detections.length }} 张人脸</span>
      </header>
      <div v-if="previewUrl" class="wb-canvas-stage">
        <img ref="imageElement" :src="previewUrl" alt="待识别人脸图片" @load="onImageLoad">
        <canvas ref="overlayCanvas" aria-hidden="true"></canvas>
      </div>
      <div v-else class="wb-canvas-empty">
        <span aria-hidden="true">◉</span>
        <strong>等待人脸图像</strong>
        <p>检测框与匹配标签将按后端坐标覆盖在图像上。</p>
      </div>
    </section>

    <ResultPanel
      title="人脸识别输出"
      :result="runOutput"
      :busy="busy"
      :error="error"
      :elapsed-ms="elapsedMs"
      :image-url="resultImageUrl"
      :filename="`${scenario.modelKey}-faces`"
    >
      <div v-if="normalizedResult.detections.length" class="wb-result-content">
        <div class="wb-metrics">
          <div><span>检测数</span><strong>{{ normalizedResult.detections.length }}</strong></div>
          <div><span>匹配</span><strong>{{ matchedCount }}</strong></div>
          <div><span>拒识</span><strong>{{ rejectedCount }}</strong></div>
        </div>
        <div class="wb-table-wrap">
          <table class="wb-table">
            <thead><tr><th>#</th><th>姓名</th><th>分数</th><th>匹配</th><th>坐标</th></tr></thead>
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
                <td>{{ displayName(item) }}</td>
                <td>{{ displayScore(item) }}</td>
                <td>{{ item.matched === true ? '匹配' : item.matched === false ? '拒识' : '未判定' }}</td>
                <td>{{ item.bbox ? item.bbox.join(', ') : '未返回' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="wb-result-note">无活体证明时不可单独用于高安全门禁；不同特征空间底库不可互通。</p>
      </div>
      <div v-else class="wb-normal-empty">
        <strong>没有检测到人脸</strong>
        <p>这是正常空结果。可降低检测阈值、更换更清晰的正脸图像，或先完成底库登记。</p>
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
const threshold = ref(Number(props.scenario.defaults?.threshold ?? 0.4))
const detThresh = ref(Number(props.scenario.defaults?.detThresh ?? 0.5))
const busy = ref(false)
const error = ref('')
const runOutput = ref(null)
const normalizedResult = ref({ detections: [] })
const elapsedMs = ref(null)
const imageElement = ref(null)
const overlayCanvas = ref(null)
const selectedIndex = ref(0)

const inputHint = computed(() => `${props.scenario.input?.formats?.join(', ') || '图片'} · 最大 ${props.scenario.input?.maxSizeMb || '配置'} MB`)
const validationErrors = computed(() => validateWorkbenchState('face_recognition', {
  file: file.value,
  threshold: threshold.value,
  detThresh: detThresh.value,
}, props.scenario.input))
const validationMessage = computed(() => file.value ? validationErrors.value[0] || '' : '')
const canRun = computed(() => (props.scenario.apiReady ?? props.scenario.ready) && !busy.value && validationErrors.value.length === 0)
const resultImageUrl = computed(() => normalizedResult.value.imageBase64 ? `data:image/jpeg;base64,${normalizedResult.value.imageBase64}` : '')
const matchedCount = computed(() => normalizedResult.value.detections.filter((item) => item.matched === true).length)
const rejectedCount = computed(() => normalizedResult.value.detections.filter((item) => item.matched === false).length)

function displayName(item) {
  return item?.name || item?.className || '未知'
}

function displayScore(item) {
  const score = typeof item?.score === 'number' ? item.score : item?.confidence
  return typeof score === 'number' ? score.toFixed(4) : '—'
}

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
  selectedIndex.value = 0
  drawOverlay()
}

function onImageLoad() {
  drawOverlay()
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
  const detections = normalizedResult.value.detections
  shapes.forEach((shape) => {
    const item = detections[shape.index] || {}
    const stroke = shape.index === selectedIndex.value
      ? '#f3a634'
      : item.matched === true
        ? '#2f9d62'
        : '#5d9cff'
    if (shape.bbox) {
      const [x1, y1, x2, y2] = shape.bbox
      context.strokeStyle = stroke
      context.lineWidth = Math.max(2, canvas.width / 450)
      context.strokeRect(x1, y1, x2 - x1, y2 - y1)
      const label = `${displayName(item)} ${displayScore(item)}`
      context.font = `${Math.max(12, canvas.width / 70)}px sans-serif`
      const textWidth = context.measureText(label).width + 8
      context.fillStyle = stroke
      context.fillRect(x1, Math.max(0, y1 - 22), textWidth, 22)
      context.fillStyle = '#fff'
      context.fillText(label, x1 + 4, Math.max(15, y1 - 6))
    }
    const landmarkColors = ['#0080ff', '#ff4040', '#20c050', '#d040d0', '#e0b000']
    ;(shape.landmarks || []).forEach(([x, y], landmarkIndex) => {
      context.beginPath()
      context.arc(x, y, Math.max(3, canvas.width / 220), 0, Math.PI * 2)
      context.fillStyle = landmarkColors[landmarkIndex % landmarkColors.length]
      context.fill()
    })
  })
}

function selectDetection(index) {
  if (busy.value) return
  selectedIndex.value = index
  drawOverlay()
}

function resetParameters() {
  if (busy.value) return
  threshold.value = Number(props.scenario.defaults?.threshold ?? 0.4)
  detThresh.value = Number(props.scenario.defaults?.detThresh ?? 0.5)
}

async function runInference() {
  if (!canRun.value) return
  const requestToken = requestGuard.begin()
  busy.value = true
  error.value = ''
  resetResult()
  try {
    const form = serializeScenarioForm('face_recognition', {
      file: file.value,
      threshold: threshold.value,
      detThresh: detThresh.value,
    })
    const response = await scenarioApi.infer(props.scenario.modelKey, form)
    if (!requestGuard.isCurrent(requestToken)) return
    runOutput.value = response.data
    elapsedMs.value = Number.isFinite(response.data?.elapsedMs) ? response.data.elapsedMs : null
    normalizedResult.value = normalizeWorkbenchResult('face_recognition', response.data?.result)
    await nextTick()
    if (!requestGuard.isCurrent(requestToken)) return
    drawOverlay()
    emit('completed', response.data)
  } catch (requestError) {
    if (requestGuard.isCurrent(requestToken)) {
      error.value = requestError?.response?.data?.message || requestError?.message || '人脸识别失败，请检查输入与运行环境。'
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
