<template>
  <div class="wb-grid">
    <section class="wb-controls" aria-label="OBB 检测输入与参数">
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
        <strong>四点几何</strong>
        <p>优先显示后端返回角度；缺失时从 quad 第一条边推导。没有 quad 时不会用水平框补造旋转结果。</p>
      </aside>
      <div v-if="validationMessage" class="wb-form-error" role="alert">{{ validationMessage }}</div>
      <button class="scenario-button wb-run" type="button" :disabled="!canRun" @click="runInference">
        {{ busy ? '正在检测…' : '运行真实 OBB 检测' }}
      </button>
    </section>

    <section class="wb-canvas" aria-label="OBB 检测画布">
      <header class="wb-canvas__header">
        <div><strong>旋转框画布</strong><span>四点多边形叠加</span></div>
        <span v-if="drawableShapes.length">{{ drawableShapes.length }} 个对象</span>
      </header>
      <div v-if="previewUrl" class="wb-canvas-stage">
        <img ref="imageElement" :src="previewUrl" alt="待检测旋转目标图片" @load="onImageLoad">
        <canvas ref="overlayCanvas" aria-hidden="true"></canvas>
      </div>
      <div v-else class="wb-canvas-empty">
        <span aria-hidden="true">◇</span>
        <strong>等待 OBB 图像</strong>
        <p>返回四点坐标后才绘制旋转多边形。</p>
      </div>
      <div v-if="selectedPreview" class="wb-selected-preview">
        <div><strong>对象 #{{ selectedIndex + 1 }} {{ previewKind }}</strong><span>{{ previewDescription }}</span></div>
        <img :src="selectedPreview" :alt="'对象 ' + (selectedIndex + 1) + ' 裁剪预览'">
      </div>
    </section>

    <ResultPanel
      title="OBB 结构化输出"
      :result="runOutput"
      :busy="busy"
      :error="error"
      :elapsed-ms="elapsedMs"
      :image-url="resultImageUrl"
      :filename="scenario.modelKey + '-obb'"
    >
      <div v-if="normalizedResult.detections.length" class="wb-result-content">
        <div class="wb-metrics">
          <div><span>对象</span><strong>{{ normalizedResult.detections.length }}</strong></div>
          <div><span>四点框</span><strong>{{ drawableQuadCount }}</strong></div>
          <div><span>选中角度</span><strong>{{ selectedAngle }}</strong></div>
        </div>
        <div class="wb-table-wrap">
          <table class="wb-table">
            <thead><tr><th>#</th><th>类别</th><th>置信度</th><th>角度</th><th>四点坐标</th></tr></thead>
            <tbody>
              <tr v-for="(item, index) in normalizedResult.detections" :key="index" :class="{ 'is-selected': selectedIndex === index }" tabindex="0" @click="selectDetection(index)" @keydown.enter="selectDetection(index)" @keydown.space.prevent="selectDetection(index)">
                <td>{{ index + 1 }}</td>
                <td>{{ item.className || (item.classId ?? '—') }}</td>
                <td>{{ typeof item.confidence === 'number' ? item.confidence.toFixed(4) : '—' }}</td>
                <td>{{ shapeAt(index)?.angle === undefined ? '未返回 quad' : shapeAt(index).angle.toFixed(1) + '°' }}</td>
                <td>{{ item.quad ? item.quad.map((point) => '[' + point.join(', ') + ']').join(' ') : '未返回' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
      <div v-else class="wb-normal-empty">
        <strong>没有检测到旋转目标</strong>
        <p>这是正常空结果。可降低置信度、提高推理尺寸或检查模型类别范围。</p>
      </div>
    </ResultPanel>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'
import { scenarioApi } from '../../../../api/modelScenarios'
import ResultPanel from '../components/ResultPanel.vue'
import { isAcceptedImageCandidate, normalizeWorkbenchResult, scaleDetectionGeometry, serializeScenarioForm, validateWorkbenchState } from '../scenarioState'

const props = defineProps({ scenario: { type: Object, required: true } })
const emit = defineEmits(['completed'])
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
const selectedIndex = ref(0)
const selectedCrop = ref('')

const inputHint = computed(() => `${props.scenario.input?.formats?.join(', ') || '图片'} · 最大 ${props.scenario.input?.maxSizeMb || '配置'} MB`)
const validationErrors = computed(() => validateWorkbenchState('obb_detection', { file: file.value, conf: conf.value, imgsz: imgsz.value }, props.scenario.input))
const validationMessage = computed(() => file.value ? validationErrors.value[0] || '' : '')
const canRun = computed(() => props.scenario.ready && !busy.value && validationErrors.value.length === 0)
const resultImageUrl = computed(() => normalizedResult.value.imageBase64 ? 'data:image/jpeg;base64,' + normalizedResult.value.imageBase64 : '')
const drawableShapes = computed(() => scaleDetectionGeometry(normalizedResult.value, Number(normalizedResult.value.width), Number(normalizedResult.value.height)))
const drawableQuadCount = computed(() => drawableShapes.value.filter((item) => item.quad).length)
const selectedAngle = computed(() => {
  const angle = shapeAt(selectedIndex.value)?.angle
  return angle === undefined ? '未返回' : angle.toFixed(1) + '°'
})
const backendPreview = computed(() => {
  const item = normalizedResult.value.detections[selectedIndex.value] || {}
  const value = item.perspectiveBase64 || item.rectifiedBase64 || item.cropBase64
  if (typeof value !== 'string' || !value) return ''
  return value.startsWith('data:') ? value : 'data:image/jpeg;base64,' + value
})
const selectedPreview = computed(() => backendPreview.value || selectedCrop.value)
const previewKind = computed(() => backendPreview.value ? '后端预览' : '裁剪')
const previewDescription = computed(() => backendPreview.value
  ? '直接显示后端返回的裁剪或透视结果。'
  : '按 quad 外接矩形从原图生成，非透视矫正。')

function shapeAt(index) {
  return drawableShapes.value.find((shape) => shape.index === index)
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
  selectedCrop.value = ''
  drawOverlay()
}
function onImageLoad() {
  drawOverlay()
  createSelectedCrop()
}
function drawOverlay() {
  const image = imageElement.value
  const canvas = overlayCanvas.value
  if (!image || !canvas) return
  canvas.width = image.naturalWidth
  canvas.height = image.naturalHeight
  const context = canvas.getContext('2d')
  context.clearRect(0, 0, canvas.width, canvas.height)
  scaleDetectionGeometry(normalizedResult.value, canvas.width, canvas.height).forEach((shape) => {
    if (!shape.quad) return
    context.beginPath()
    shape.quad.forEach(([x, y], pointIndex) => pointIndex ? context.lineTo(x, y) : context.moveTo(x, y))
    context.closePath()
    context.strokeStyle = shape.index === selectedIndex.value ? '#f3a634' : '#5d9cff'
    context.fillStyle = shape.index === selectedIndex.value ? 'rgba(243, 166, 52, .14)' : 'rgba(93, 156, 255, .1)'
    context.lineWidth = Math.max(2, canvas.width / 450)
    context.fill()
    context.stroke()
    shape.quad.forEach(([x, y]) => {
      context.beginPath()
      context.arc(x, y, Math.max(3, canvas.width / 220), 0, Math.PI * 2)
      context.fillStyle = context.strokeStyle
      context.fill()
    })
  })
}
function createSelectedCrop() {
  const image = imageElement.value
  const quad = normalizedResult.value.detections[selectedIndex.value]?.quad
  if (!image?.naturalWidth || !quad) {
    selectedCrop.value = ''
    return
  }
  const xs = quad.map((point) => point[0])
  const ys = quad.map((point) => point[1])
  const x1 = Math.max(0, Math.min(image.naturalWidth, ...xs))
  const y1 = Math.max(0, Math.min(image.naturalHeight, ...ys))
  const x2 = Math.max(0, Math.min(image.naturalWidth, Math.max(...xs)))
  const y2 = Math.max(0, Math.min(image.naturalHeight, Math.max(...ys)))
  if (x2 <= x1 || y2 <= y1) {
    selectedCrop.value = ''
    return
  }
  const canvas = document.createElement('canvas')
  canvas.width = Math.max(1, Math.round(x2 - x1))
  canvas.height = Math.max(1, Math.round(y2 - y1))
  canvas.getContext('2d').drawImage(image, x1, y1, x2 - x1, y2 - y1, 0, 0, canvas.width, canvas.height)
  selectedCrop.value = canvas.toDataURL('image/jpeg')
}
function selectDetection(index) {
  if (busy.value) return
  selectedIndex.value = index
  drawOverlay()
  createSelectedCrop()
}

function resetParameters() {
  if (busy.value) return
  conf.value = Number(props.scenario.defaults?.conf ?? 0.5)
  imgsz.value = Number(props.scenario.defaults?.imgsz ?? 640)
}
async function runInference() {
  if (!canRun.value) return
  busy.value = true
  error.value = ''
  resetResult()
  try {
    const form = serializeScenarioForm('obb_detection', { file: file.value, conf: conf.value, imgsz: imgsz.value })
    const response = await scenarioApi.infer(props.scenario.modelKey, form)
    runOutput.value = response.data
    elapsedMs.value = Number.isFinite(response.data?.elapsedMs) ? response.data.elapsedMs : null
    normalizedResult.value = normalizeWorkbenchResult('obb_detection', response.data?.result)
    await nextTick()
    drawOverlay()
    createSelectedCrop()
    emit('completed', response.data)
  } catch (requestError) {
    error.value = requestError?.response?.data?.message || requestError?.message || 'OBB 检测失败，请检查输入与运行环境。'
  } finally {
    busy.value = false
  }
}
onBeforeUnmount(() => {
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
})
</script>
