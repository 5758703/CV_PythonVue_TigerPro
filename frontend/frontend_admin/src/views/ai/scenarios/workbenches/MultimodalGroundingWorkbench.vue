<template>
  <div class="wb-grid">
    <section class="wb-controls" aria-label="多模态定位输入与参数">
      <div class="wb-control-group">
        <h3>待定位图像</h3>
        <label class="wb-dropzone" :class="{ 'is-dragging': dragging, 'is-disabled': busy }" @dragenter.prevent="onDragEnter" @dragover.prevent @dragleave.prevent="onDragLeave" @drop.prevent="onDrop">
          <input type="file" accept="image/*" :disabled="busy" @change="onFileChange">
          <strong>{{ file ? file.name : '拖入图片或选择文件' }}</strong>
          <span>{{ inputHint }}</span>
        </label>
        <button v-if="file" class="wb-text-button" type="button" :disabled="busy" @click="clearFile">清除图片</button>
      </div>

      <div class="wb-control-group">
        <div class="wb-control-heading"><h3>定位参数</h3><button class="wb-text-button" type="button" :disabled="busy" @click="resetParameters">恢复默认</button></div>
        <label class="wb-field">
          <span>提示词</span>
          <textarea v-model="prompt" rows="3" maxlength="500" placeholder="例如 person, car 或自然语言描述" :disabled="busy"></textarea>
        </label>
        <label class="wb-field">
          <span>置信度 <output>{{ Number(conf).toFixed(2) }}</output></span>
          <input v-model.number="conf" type="range" min="0" max="1" step="0.01" :disabled="busy">
        </label>
      </div>

      <aside class="wb-capability-note">
        <strong>开放词汇定位</strong>
        <p>结果依赖提示质量；行业目标须专训或标定阈值后再接入告警链路。</p>
      </aside>

      <div v-if="validationMessage" class="wb-form-error" role="alert">{{ validationMessage }}</div>
      <button class="scenario-button wb-run" type="button" :disabled="!canRun" @click="runInference">
        {{ busy ? '正在定位…' : '运行真实定位' }}
      </button>
    </section>

    <section class="wb-canvas" aria-label="多模态定位画布">
      <header class="wb-canvas__header">
        <div><strong>定位画布</strong><span>后端坐标叠加</span></div>
        <span v-if="normalizedResult.detections.length">{{ normalizedResult.detections.length }} 个目标</span>
      </header>
      <div v-if="canvasUrl" class="wb-canvas-stage">
        <img ref="imageElement" :src="canvasUrl" alt="待定位图片" @load="onImageLoad">
        <canvas v-if="!resultImageUrl" ref="overlayCanvas" aria-hidden="true"></canvas>
      </div>
      <div v-else class="wb-canvas-empty">
        <span aria-hidden="true">▣</span>
        <strong>等待定位图像</strong>
        <p>填写提示词后运行，检测框将按后端坐标覆盖在图像上。</p>
      </div>
    </section>

    <ResultPanel
      title="多模态定位输出"
      :result="runOutput"
      :busy="busy"
      :error="error"
      :elapsed-ms="elapsedMs"
      :image-url="resultImageUrl"
      :filename="`${scenario.modelKey}-grounding`"
    >
      <div v-if="normalizedResult.detections.length" class="wb-result-content">
        <div class="wb-metrics">
          <div><span>检测数</span><strong>{{ normalizedResult.detections.length }}</strong></div>
          <div><span>提示词</span><strong>{{ promptLabel }}</strong></div>
          <div><span>最高置信度</span><strong>{{ topConfidence }}</strong></div>
        </div>
        <div class="wb-table-wrap">
          <table class="wb-table">
            <thead><tr><th>#</th><th>类别</th><th>置信度</th><th>坐标</th></tr></thead>
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
              </tr>
            </tbody>
          </table>
        </div>
        <p class="wb-result-note">开放词汇框仅作候选区域，生产告警前须用业务负样本校准提示与阈值。</p>
      </div>
      <div v-else class="wb-normal-empty">
        <strong>没有定位到目标</strong>
        <p>这是正常空结果。可调整提示词、降低置信度或更换更清晰输入。</p>
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
const prompt = ref(String(props.scenario.defaults?.prompt ?? props.scenario.defaults?.scenario ?? 'person'))
const conf = ref(Number(props.scenario.defaults?.conf ?? 0.25))
const busy = ref(false)
const error = ref('')
const runOutput = ref(null)
const normalizedResult = ref({ detections: [] })
const elapsedMs = ref(null)
const imageElement = ref(null)
const overlayCanvas = ref(null)
const selectedIndex = ref(0)

const inputHint = computed(() => `${props.scenario.input?.formats?.join(', ') || '图片'} · 最大 ${props.scenario.input?.maxSizeMb || '配置'} MB`)
const workbenchType = computed(() => (
  props.scenario.workbenchType === 'industrial_diagnosis' ? 'industrial_diagnosis' : 'multimodal_grounding'
))
const validationErrors = computed(() => validateWorkbenchState(workbenchType.value, {
  file: file.value,
  prompt: prompt.value,
  conf: conf.value,
}, props.scenario.input))
const validationMessage = computed(() => file.value ? validationErrors.value[0] || '' : '')
const canRun = computed(() => (props.scenario.apiReady ?? props.scenario.ready) && !busy.value && validationErrors.value.length === 0)
const resultImageUrl = computed(() => normalizedResult.value.imageBase64 ? `data:image/jpeg;base64,${normalizedResult.value.imageBase64}` : '')
const canvasUrl = computed(() => resultImageUrl.value || previewUrl.value)
const promptLabel = computed(() => normalizedResult.value.prompt || prompt.value || '—')
const topConfidence = computed(() => {
  const scores = normalizedResult.value.detections
    .map((item) => item.confidence)
    .filter((value) => typeof value === 'number')
  if (!scores.length) return '—'
  return Math.max(...scores).toFixed(4)
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
  if (resultImageUrl.value) return
  const image = imageElement.value
  const canvas = overlayCanvas.value
  if (!image || !canvas) return
  canvas.width = image.naturalWidth
  canvas.height = image.naturalHeight
  const context = canvas.getContext('2d')
  context.clearRect(0, 0, canvas.width, canvas.height)
  const shapes = scaleDetectionGeometry(normalizedResult.value, canvas.width, canvas.height)
  shapes.forEach((shape) => {
    if (!shape.bbox) return
    const [x1, y1, x2, y2] = shape.bbox
    context.strokeStyle = shape.index === selectedIndex.value ? '#f3a634' : '#5d9cff'
    context.lineWidth = Math.max(2, canvas.width / 450)
    context.strokeRect(x1, y1, x2 - x1, y2 - y1)
    context.fillStyle = context.strokeStyle
    context.fillRect(x1, Math.max(0, y1 - 22), 34, 22)
    context.fillStyle = '#fff'
    context.font = `${Math.max(12, canvas.width / 70)}px sans-serif`
    context.fillText(`#${shape.index + 1}`, x1 + 4, Math.max(15, y1 - 6))
  })
}

function selectDetection(index) {
  if (busy.value) return
  selectedIndex.value = index
  drawOverlay()
}

function resetParameters() {
  if (busy.value) return
  prompt.value = String(props.scenario.defaults?.prompt ?? props.scenario.defaults?.scenario ?? 'person')
  conf.value = Number(props.scenario.defaults?.conf ?? 0.25)
}

async function runInference() {
  if (!canRun.value) return
  const requestToken = requestGuard.begin()
  busy.value = true
  error.value = ''
  resetResult()
  try {
    const form = serializeScenarioForm(workbenchType.value, {
      file: file.value,
      prompt: prompt.value,
      conf: conf.value,
    })
    const response = await scenarioApi.infer(props.scenario.modelKey, form)
    if (!requestGuard.isCurrent(requestToken)) return
    runOutput.value = response.data
    elapsedMs.value = Number.isFinite(response.data?.elapsedMs) ? response.data.elapsedMs : null
    normalizedResult.value = normalizeWorkbenchResult(workbenchType.value, response.data?.result)
    await nextTick()
    if (!requestGuard.isCurrent(requestToken)) return
    drawOverlay()
    emit('completed', response.data)
  } catch (requestError) {
    if (requestGuard.isCurrent(requestToken)) {
      error.value = requestError?.response?.data?.message || requestError?.message || '多模态定位失败，请检查输入与运行环境。'
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
