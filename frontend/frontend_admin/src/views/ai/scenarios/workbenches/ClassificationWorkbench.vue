<template>
  <div class="wb-grid">
    <section class="wb-controls" aria-label="图像分类输入与参数">
      <div class="wb-control-group">
        <h3>待分类图像</h3>
        <label class="wb-dropzone" :class="{ 'is-dragging': dragging, 'is-disabled': busy }" @dragenter.prevent="onDragEnter" @dragover.prevent @dragleave.prevent="onDragLeave" @drop.prevent="onDrop">
          <input type="file" accept="image/*" :disabled="busy" @change="onFileChange">
          <strong>{{ file ? file.name : '拖入图片或选择文件' }}</strong>
          <span>{{ inputHint }}</span>
        </label>
        <button v-if="file" class="wb-text-button" type="button" :disabled="busy" @click="clearFile">清除图片</button>
      </div>

      <div class="wb-control-group">
        <div class="wb-control-heading"><h3>分类参数</h3><button class="wb-text-button" type="button" :disabled="busy" @click="resetParameters">恢复默认</button></div>
        <label class="wb-field">
          <span>Top-K <output>{{ topK }}</output></span>
          <input v-model.number="topK" type="range" min="1" max="20" step="1" :disabled="busy">
        </label>
        <label v-if="showPrecision" class="wb-field">
          <span>精度</span>
          <select v-model="precision" :disabled="busy">
            <option value="fp32">fp32</option>
            <option value="int8">int8</option>
          </select>
        </label>
        <label v-if="showConf" class="wb-field">
          <span>置信度 <output>{{ Number(conf).toFixed(2) }}</output></span>
          <input v-model.number="conf" type="range" min="0" max="1" step="0.01" :disabled="busy">
        </label>
      </div>

      <aside class="wb-capability-note">
        <strong>整图分类</strong>
        <p>ImageNet 通用类别用于素材路由与质检，不能替代检测或局部目标判定。</p>
      </aside>

      <div v-if="validationMessage" class="wb-form-error" role="alert">{{ validationMessage }}</div>
      <button class="scenario-button wb-run" type="button" :disabled="!canRun" @click="runInference">
        {{ busy ? '正在分类…' : '运行真实分类' }}
      </button>
    </section>

    <section class="wb-canvas" aria-label="图像分类预览">
      <header class="wb-canvas__header">
        <div><strong>输入预览</strong><span>整图分类</span></div>
        <span v-if="normalizedResult.results.length">Top-{{ normalizedResult.results.length }}</span>
      </header>
      <div v-if="previewUrl" class="wb-canvas-stage">
        <img :src="previewUrl" alt="待分类图片">
      </div>
      <div v-else class="wb-canvas-empty">
        <span aria-hidden="true">▤</span>
        <strong>等待分类图像</strong>
        <p>上传整图后运行，结果以 Top-K 标签表展示。</p>
      </div>
    </section>

    <ResultPanel
      title="图像分类输出"
      :result="runOutput"
      :busy="busy"
      :error="error"
      :elapsed-ms="elapsedMs"
      :filename="`${scenario.modelKey}-classify`"
    >
      <div v-if="normalizedResult.results.length" class="wb-result-content">
        <div class="wb-metrics">
          <div><span>Top-1</span><strong>{{ topLabel }}</strong></div>
          <div><span>分数</span><strong>{{ topScore }}</strong></div>
          <div><span>返回数</span><strong>{{ normalizedResult.results.length }}</strong></div>
        </div>
        <div class="wb-table-wrap">
          <table class="wb-table">
            <thead><tr><th>#</th><th>标签</th><th>分数</th></tr></thead>
            <tbody>
              <tr v-for="(item, index) in normalizedResult.results" :key="`${item.label}-${index}`">
                <td>{{ index + 1 }}</td>
                <td>{{ item.label }}</td>
                <td>{{ typeof item.score === 'number' ? item.score.toFixed(4) : '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="wb-result-note">低置信样本建议送人工标注或更专用模型，不宜直接驱动业务决策。</p>
      </div>
      <div v-else class="wb-normal-empty">
        <strong>没有分类结果</strong>
        <p>这是正常空结果。可提高 Top-K、调整精度或更换更清晰输入。</p>
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
const previewUrl = ref('')
const dragging = ref(false)
const topK = ref(Number(props.scenario.defaults?.topK ?? 5))
const precision = ref(String(props.scenario.defaults?.precision ?? 'fp32'))
const conf = ref(Number(props.scenario.defaults?.conf ?? 0.25))
const busy = ref(false)
const error = ref('')
const runOutput = ref(null)
const normalizedResult = ref({ results: [] })
const elapsedMs = ref(null)

const showPrecision = computed(() => props.scenario.modelKey === 'mobilenet-v2')
const showConf = computed(() => props.scenario.modelKey === 'yolo-master-cls-n')
const inputHint = computed(() => `${props.scenario.input?.formats?.join(', ') || '图片'} · 最大 ${props.scenario.input?.maxSizeMb || '配置'} MB`)
const formState = computed(() => {
  const state = {
    file: file.value,
    topK: topK.value,
  }
  if (showPrecision.value) state.precision = precision.value
  if (showConf.value) state.conf = conf.value
  return state
})
const validationErrors = computed(() => validateWorkbenchState('image_classification', formState.value, props.scenario.input))
const validationMessage = computed(() => file.value ? validationErrors.value[0] || '' : '')
const canRun = computed(() => (props.scenario.apiReady ?? props.scenario.ready) && !busy.value && validationErrors.value.length === 0)
const topLabel = computed(() => normalizedResult.value.results[0]?.label || normalizedResult.value.top?.label || '—')
const topScore = computed(() => {
  const score = normalizedResult.value.results[0]?.score ?? normalizedResult.value.top?.score
  return typeof score === 'number' ? score.toFixed(4) : '—'
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
  normalizedResult.value = { results: [] }
  elapsedMs.value = null
}

function resetParameters() {
  if (busy.value) return
  topK.value = Number(props.scenario.defaults?.topK ?? 5)
  precision.value = String(props.scenario.defaults?.precision ?? 'fp32')
  conf.value = Number(props.scenario.defaults?.conf ?? 0.25)
}

async function runInference() {
  if (!canRun.value) return
  const requestToken = requestGuard.begin()
  busy.value = true
  error.value = ''
  resetResult()
  try {
    const form = serializeScenarioForm('image_classification', formState.value)
    const response = await scenarioApi.infer(props.scenario.modelKey, form)
    if (!requestGuard.isCurrent(requestToken)) return
    runOutput.value = response.data
    elapsedMs.value = Number.isFinite(response.data?.elapsedMs) ? response.data.elapsedMs : null
    normalizedResult.value = normalizeWorkbenchResult('image_classification', response.data?.result)
    emit('completed', response.data)
  } catch (requestError) {
    if (requestGuard.isCurrent(requestToken)) {
      error.value = requestError?.response?.data?.message || requestError?.message || '图像分类失败，请检查输入与运行环境。'
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
