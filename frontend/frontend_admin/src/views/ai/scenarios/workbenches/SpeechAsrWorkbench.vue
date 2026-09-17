<template>
  <div class="wb-grid">
    <section class="wb-controls" aria-label="语音识别输入与参数">
      <div class="wb-control-group">
        <h3>待识别音频</h3>
        <label class="wb-dropzone" :class="{ 'is-disabled': busy }" @dragover.prevent @drop.prevent="onDrop">
          <input type="file" accept="audio/*,.wav,.mp3,.flac,.m4a,.ogg" :disabled="busy" @change="onFileChange">
          <strong>{{ file ? file.name : '拖入或选择音频文件' }}</strong>
          <span>{{ inputHint }}</span>
        </label>
        <button v-if="file" class="wb-text-button" type="button" :disabled="busy" @click="clearFile">清除音频</button>
      </div>

      <div class="wb-control-group">
        <div class="wb-control-heading"><h3>识别参数</h3><button class="wb-text-button" type="button" :disabled="busy" @click="resetParameters">恢复默认</button></div>
        <label class="wb-field">
          <span>语言（可选）</span>
          <input v-model="language" type="text" placeholder="例如 zh / en，留空由模型决定" :disabled="busy">
        </label>
      </div>

      <aside class="wb-capability-note">
        <strong>语音转写</strong>
        <p>依赖本地 ASR 权重与运行库；嘈杂场景建议先降噪或切段再送入。</p>
      </aside>

      <div v-if="validationMessage" class="wb-form-error" role="alert">{{ validationMessage }}</div>
      <button class="scenario-button wb-run" type="button" :disabled="!canRun" @click="runInference">
        {{ busy ? '正在识别…' : '运行真实语音识别' }}
      </button>
    </section>

    <section class="wb-canvas" aria-label="音频预览">
      <header class="wb-canvas__header">
        <div><strong>音频预览</strong><span>ASR</span></div>
      </header>
      <div v-if="previewUrl" class="wb-canvas-stage">
        <audio :src="previewUrl" controls></audio>
      </div>
      <div v-else class="wb-canvas-empty">
        <span aria-hidden="true">♪</span>
        <strong>等待音频</strong>
        <p>上传音频后运行，转写文本显示在结果面板。</p>
      </div>
    </section>

    <ResultPanel
      title="语音识别输出"
      :result="runOutput"
      :busy="busy"
      :error="error"
      :elapsed-ms="elapsedMs"
      :filename="`${scenario.modelKey}-asr`"
    >
      <div v-if="transcript" class="wb-result-content">
        <div class="wb-metrics">
          <div><span>转写</span><strong>{{ transcript.slice(0, 24) }}{{ transcript.length > 24 ? '…' : '' }}</strong></div>
        </div>
        <p class="wb-result-note">{{ transcript }}</p>
      </div>
      <div v-else class="wb-normal-empty">
        <strong>没有转写结果</strong>
        <p>这是正常空结果。可更换更清晰音频或检查模型就绪状态。</p>
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
  normalizeWorkbenchResult,
  serializeScenarioForm,
  validateWorkbenchState,
} from '../scenarioState'

const props = defineProps({ scenario: { type: Object, required: true } })
const emit = defineEmits(['completed'])
const requestGuard = createAsyncRequestGuard()

const file = ref(null)
const previewUrl = ref('')
const language = ref(String(props.scenario.defaults?.language ?? ''))
const busy = ref(false)
const error = ref('')
const runOutput = ref(null)
const normalizedResult = ref({})
const elapsedMs = ref(null)

const inputHint = computed(() => `${props.scenario.input?.formats?.join(', ') || '音频'} · 最大 ${props.scenario.input?.maxSizeMb || '配置'} MB`)
const validationErrors = computed(() => validateWorkbenchState('speech_asr', {
  file: file.value,
  language: language.value,
}))
const validationMessage = computed(() => (file.value ? validationErrors.value[0] || '' : ''))
const canRun = computed(() => (props.scenario.apiReady ?? props.scenario.ready) && !busy.value && validationErrors.value.length === 0)
const transcript = computed(() => {
  const result = normalizedResult.value
  return String(result.text || result.transcript || result.result || '')
})

function setFile(nextFile) {
  if (busy.value || !nextFile) return
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  file.value = nextFile
  previewUrl.value = URL.createObjectURL(nextFile)
  error.value = ''
  runOutput.value = null
  normalizedResult.value = {}
  elapsedMs.value = null
}

function onFileChange(event) {
  if (busy.value) return
  setFile(event.target.files?.[0])
  event.target.value = ''
}

function onDrop(event) {
  if (busy.value) return
  setFile(event.dataTransfer?.files?.[0])
}

function clearFile() {
  if (busy.value) return
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  file.value = null
  previewUrl.value = ''
  runOutput.value = null
  normalizedResult.value = {}
  elapsedMs.value = null
}

function resetParameters() {
  if (busy.value) return
  language.value = String(props.scenario.defaults?.language ?? '')
}

async function runInference() {
  if (!canRun.value) return
  const requestToken = requestGuard.begin()
  busy.value = true
  error.value = ''
  runOutput.value = null
  normalizedResult.value = {}
  elapsedMs.value = null
  try {
    const form = serializeScenarioForm('speech_asr', {
      file: file.value,
      language: language.value,
    })
    const response = await scenarioApi.infer(props.scenario.modelKey, form)
    if (!requestGuard.isCurrent(requestToken)) return
    runOutput.value = response.data
    elapsedMs.value = Number.isFinite(response.data?.elapsedMs) ? response.data.elapsedMs : null
    normalizedResult.value = normalizeWorkbenchResult('speech_asr', response.data?.result)
    emit('completed', response.data)
  } catch (requestError) {
    if (requestGuard.isCurrent(requestToken)) {
      error.value = requestError?.response?.data?.message || requestError?.message || '语音识别失败，请检查输入与运行环境。'
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
