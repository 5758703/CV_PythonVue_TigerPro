<template>
  <div class="wb-grid">
    <section class="wb-controls" aria-label="图像修复输入与参数">
      <div class="wb-control-group">
        <h3>待修复图像</h3>
        <label class="wb-dropzone" :class="{ 'is-dragging': draggingFile, 'is-disabled': busy }" @dragenter.prevent="onFileDragEnter" @dragover.prevent @dragleave.prevent="onFileDragLeave" @drop.prevent="onFileDrop">
          <input type="file" accept="image/*" :disabled="busy" @change="onFileChange">
          <strong>{{ file ? file.name : '拖入原图或选择文件' }}</strong>
          <span>{{ inputHint }}</span>
        </label>
        <button v-if="file" class="wb-text-button" type="button" :disabled="busy" @click="clearFile">清除原图</button>
      </div>

      <div class="wb-control-group">
        <h3>遮罩图像</h3>
        <label class="wb-dropzone" :class="{ 'is-dragging': draggingMask, 'is-disabled': busy }" @dragenter.prevent="onMaskDragEnter" @dragover.prevent @dragleave.prevent="onMaskDragLeave" @drop.prevent="onMaskDrop">
          <input type="file" accept="image/*" :disabled="busy" @change="onMaskChange">
          <strong>{{ mask ? mask.name : '拖入遮罩或选择文件' }}</strong>
          <span>白色区域为修复目标</span>
        </label>
        <button v-if="mask" class="wb-text-button" type="button" :disabled="busy" @click="clearMask">清除遮罩</button>
      </div>

      <div class="wb-control-group">
        <div class="wb-control-heading"><h3>修复参数</h3><button class="wb-text-button" type="button" :disabled="busy" @click="resetParameters">恢复默认</button></div>
        <label class="wb-field">
          <span>遮罩膨胀 <output>{{ dilatePx }}</output> px</span>
          <input v-model.number="dilatePx" type="range" min="0" max="64" step="1" :disabled="busy">
        </label>
      </div>

      <aside class="wb-capability-note">
        <strong>生成式补全</strong>
        <p>修复结果是模型生成内容，不能作为原始证据；生产脱敏须保留原图与审计记录。</p>
      </aside>

      <div v-if="validationMessage" class="wb-form-error" role="alert">{{ validationMessage }}</div>
      <button class="scenario-button wb-run" type="button" :disabled="!canRun" @click="runInference">
        {{ busy ? '正在修复…' : '运行真实修复' }}
      </button>
    </section>

    <section class="wb-canvas" aria-label="图像修复预览">
      <header class="wb-canvas__header">
        <div><strong>修复预览</strong><span>原图 / 遮罩 / 结果</span></div>
        <span v-if="normalizedResult.width">{{ normalizedResult.width }} × {{ normalizedResult.height }}</span>
      </header>
      <div v-if="resultImageUrl || previewUrl" class="wb-canvas-stage">
        <img :src="resultImageUrl || previewUrl" :alt="resultImageUrl ? '修复结果图' : '待修复原图'">
      </div>
      <div v-else class="wb-canvas-empty">
        <span aria-hidden="true">▦</span>
        <strong>等待原图与遮罩</strong>
        <p>上传原图和白色遮罩后运行修复，结果图将显示在此。</p>
      </div>
      <div v-if="maskPreviewUrl" class="wb-crop-strip" aria-label="遮罩预览">
        <button type="button" class="is-active">
          <img :src="maskPreviewUrl" alt="遮罩预览">
          <span>遮罩</span>
        </button>
      </div>
    </section>

    <ResultPanel
      title="图像修复输出"
      :result="runOutput"
      :busy="busy"
      :error="error"
      :elapsed-ms="elapsedMs"
      :image-url="resultImageUrl"
      :filename="`${scenario.modelKey}-inpaint`"
    >
      <div v-if="resultImageUrl" class="wb-result-content">
        <div class="wb-metrics">
          <div><span>尺寸</span><strong>{{ sizeLabel }}</strong></div>
          <div><span>遮罩像素</span><strong>{{ maskPixelsLabel }}</strong></div>
          <div><span>膨胀</span><strong>{{ dilateLabel }}</strong></div>
        </div>
        <div v-if="maskPreviewUrl" class="wb-canvas-stage">
          <img :src="maskPreviewUrl" alt="后端遮罩预览">
        </div>
        <p class="wb-result-note">修复图仅供脱敏或素材清理；证据留存请使用修复前原图。</p>
      </div>
      <div v-else class="wb-normal-empty">
        <strong>尚未生成修复结果</strong>
        <p>请确认原图与遮罩已上传，并检查白色区域是否覆盖目标。</p>
      </div>
    </ResultPanel>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, ref } from 'vue'

import { scenarioApi } from '../../../../api/modelScenarios'
import ResultPanel from '../components/ResultPanel.vue'
import {
  createAsyncRequestGuard,
  isAcceptedImageCandidate,
  normalizeWorkbenchResult,
  serializeScenarioForm,
  validateWorkbenchState,
} from '../scenarioState'

const props = defineProps({ scenario: { type: Object, required: true } })
const emit = defineEmits(['completed'])
const requestGuard = createAsyncRequestGuard()

const file = ref(null)
const mask = ref(null)
const previewUrl = ref('')
const maskLocalUrl = ref('')
const draggingFile = ref(false)
const draggingMask = ref(false)
const dilatePx = ref(Number(props.scenario.defaults?.dilatePx ?? 0))
const busy = ref(false)
const error = ref('')
const runOutput = ref(null)
const normalizedResult = ref({})
const elapsedMs = ref(null)

const inputHint = computed(() => `${props.scenario.input?.formats?.join(', ') || '图片'} · 最大 ${props.scenario.input?.maxSizeMb || '配置'} MB`)
const validationErrors = computed(() => validateWorkbenchState('image_inpainting', {
  file: file.value,
  mask: mask.value,
  dilatePx: dilatePx.value,
}, props.scenario.input))
const validationMessage = computed(() => (file.value || mask.value) ? validationErrors.value[0] || '' : '')
const canRun = computed(() => (props.scenario.apiReady ?? props.scenario.ready) && !busy.value && validationErrors.value.length === 0)
const resultImageUrl = computed(() => normalizedResult.value.imageBase64 ? `data:image/jpeg;base64,${normalizedResult.value.imageBase64}` : '')
const maskPreviewUrl = computed(() => {
  if (normalizedResult.value.maskPreviewBase64) {
    return `data:image/png;base64,${normalizedResult.value.maskPreviewBase64}`
  }
  return maskLocalUrl.value
})
const sizeLabel = computed(() => {
  const width = normalizedResult.value.width
  const height = normalizedResult.value.height
  if (!(width && height)) return '—'
  return `${width} × ${height}`
})
const maskPixelsLabel = computed(() => (
  Number.isFinite(normalizedResult.value.maskPixels) ? String(normalizedResult.value.maskPixels) : '—'
))
const dilateLabel = computed(() => (
  Number.isFinite(normalizedResult.value.dilatePx) ? `${normalizedResult.value.dilatePx} px` : `${dilatePx.value} px`
))

function acceptImage(nextFile) {
  if (!isAcceptedImageCandidate(nextFile, props.scenario.input?.formats)) {
    error.value = '请选择浏览器可预览的图片文件。'
    return false
  }
  return true
}

function setFile(nextFile) {
  if (busy.value || !nextFile || !acceptImage(nextFile)) return
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  file.value = nextFile
  previewUrl.value = URL.createObjectURL(nextFile)
  error.value = ''
  resetResult()
}

function setMask(nextFile) {
  if (busy.value || !nextFile || !acceptImage(nextFile)) return
  if (maskLocalUrl.value) URL.revokeObjectURL(maskLocalUrl.value)
  mask.value = nextFile
  maskLocalUrl.value = URL.createObjectURL(nextFile)
  error.value = ''
  resetResult()
}

function onFileChange(event) {
  if (busy.value) return
  setFile(event.target.files?.[0])
  event.target.value = ''
}

function onMaskChange(event) {
  if (busy.value) return
  setMask(event.target.files?.[0])
  event.target.value = ''
}

function onFileDrop(event) {
  if (busy.value) return
  draggingFile.value = false
  setFile(event.dataTransfer?.files?.[0])
}

function onMaskDrop(event) {
  if (busy.value) return
  draggingMask.value = false
  setMask(event.dataTransfer?.files?.[0])
}

function clearFile() {
  if (busy.value) return
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  file.value = null
  previewUrl.value = ''
  resetResult()
}

function clearMask() {
  if (busy.value) return
  if (maskLocalUrl.value) URL.revokeObjectURL(maskLocalUrl.value)
  mask.value = null
  maskLocalUrl.value = ''
  resetResult()
}

function onFileDragEnter() {
  if (!busy.value) draggingFile.value = true
}

function onFileDragLeave() {
  if (!busy.value) draggingFile.value = false
}

function onMaskDragEnter() {
  if (!busy.value) draggingMask.value = true
}

function onMaskDragLeave() {
  if (!busy.value) draggingMask.value = false
}

function resetResult() {
  runOutput.value = null
  normalizedResult.value = {}
  elapsedMs.value = null
}

function resetParameters() {
  if (busy.value) return
  dilatePx.value = Number(props.scenario.defaults?.dilatePx ?? 0)
}

async function runInference() {
  if (!canRun.value) return
  const requestToken = requestGuard.begin()
  busy.value = true
  error.value = ''
  resetResult()
  try {
    const form = serializeScenarioForm('image_inpainting', {
      file: file.value,
      mask: mask.value,
      dilatePx: dilatePx.value,
    })
    const response = await scenarioApi.infer(props.scenario.modelKey, form)
    if (!requestGuard.isCurrent(requestToken)) return
    runOutput.value = response.data
    elapsedMs.value = Number.isFinite(response.data?.elapsedMs) ? response.data.elapsedMs : null
    normalizedResult.value = normalizeWorkbenchResult('image_inpainting', response.data?.result)
    emit('completed', response.data)
  } catch (requestError) {
    if (requestGuard.isCurrent(requestToken)) {
      error.value = requestError?.response?.data?.message || requestError?.message || '图像修复失败，请检查输入与运行环境。'
    }
  } finally {
    if (requestGuard.isCurrent(requestToken)) busy.value = false
  }
}

onBeforeUnmount(() => {
  requestGuard.dispose()
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  if (maskLocalUrl.value) URL.revokeObjectURL(maskLocalUrl.value)
})
</script>
