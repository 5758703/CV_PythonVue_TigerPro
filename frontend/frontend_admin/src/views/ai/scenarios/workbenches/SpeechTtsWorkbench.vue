<template>
  <div class="wb-grid">
    <section class="wb-controls" aria-label="语音合成输入与参数">
      <div class="wb-control-group">
        <div class="wb-control-heading"><h3>待合成文本</h3><button class="wb-text-button" type="button" :disabled="busy" @click="resetParameters">恢复默认</button></div>
        <label class="wb-field">
          <span>文本</span>
          <textarea v-model="text" rows="8" maxlength="5000" placeholder="输入要合成的文本" :disabled="busy"></textarea>
        </label>
        <label class="wb-field">
          <span>说话人（可选）</span>
          <input v-model="speaker" type="text" :placeholder="String(scenario.defaults?.speaker || '模型默认')" :disabled="busy">
        </label>
      </div>

      <aside class="wb-capability-note">
        <strong>文本转语音</strong>
        <p>不同后端说话人字段含义不同；未配置权重时保持待准备，不自动下载。</p>
      </aside>

      <div v-if="validationMessage" class="wb-form-error" role="alert">{{ validationMessage }}</div>
      <button class="scenario-button wb-run" type="button" :disabled="!canRun" @click="runInference">
        {{ busy ? '正在合成…' : '运行真实语音合成' }}
      </button>
    </section>

    <section class="wb-canvas" aria-label="合成预览">
      <header class="wb-canvas__header">
        <div><strong>音频预览</strong><span>TTS</span></div>
      </header>
      <div v-if="audioUrl" class="wb-canvas-stage">
        <audio :src="audioUrl" controls></audio>
      </div>
      <div v-else class="wb-canvas-empty">
        <span aria-hidden="true">♫</span>
        <strong>等待合成</strong>
        <p>填写文本后运行，返回音频可在此试听。</p>
      </div>
    </section>

    <ResultPanel
      title="语音合成输出"
      :result="runOutput"
      :busy="busy"
      :error="error"
      :elapsed-ms="elapsedMs"
      :filename="`${scenario.modelKey}-tts`"
    >
      <div v-if="audioUrl" class="wb-result-content">
        <div class="wb-metrics">
          <div><span>格式</span><strong>{{ audioFormat }}</strong></div>
        </div>
        <p class="wb-result-note">音频以 Base64 返回；页面仅做试听，不改写合成参数。</p>
      </div>
      <div v-else class="wb-normal-empty">
        <strong>没有音频结果</strong>
        <p>检查模型就绪状态或缩短输入文本后重试。</p>
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

const text = ref('')
const speaker = ref(String(props.scenario.defaults?.speaker ?? ''))
const busy = ref(false)
const error = ref('')
const runOutput = ref(null)
const normalizedResult = ref({})
const elapsedMs = ref(null)
const audioUrl = ref('')

const validationErrors = computed(() => validateWorkbenchState('speech_tts', {
  text: text.value,
  speaker: speaker.value,
}))
const validationMessage = computed(() => (text.value ? validationErrors.value[0] || '' : ''))
const canRun = computed(() => (props.scenario.apiReady ?? props.scenario.ready) && !busy.value && validationErrors.value.length === 0)
const audioFormat = computed(() => String(normalizedResult.value.format || 'wav'))

function revokeAudio() {
  if (audioUrl.value) {
    URL.revokeObjectURL(audioUrl.value)
    audioUrl.value = ''
  }
}

function resetParameters() {
  if (busy.value) return
  speaker.value = String(props.scenario.defaults?.speaker ?? '')
}

function setAudioFromResult(result) {
  revokeAudio()
  const b64 = result?.audioBase64 || result?.audio
  if (!b64 || typeof b64 !== 'string') return
  const mime = audioFormat.value === 'mp3' ? 'audio/mpeg' : 'audio/wav'
  const binary = atob(b64)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i)
  audioUrl.value = URL.createObjectURL(new Blob([bytes], { type: mime }))
}

async function runInference() {
  if (!canRun.value) return
  const requestToken = requestGuard.begin()
  busy.value = true
  error.value = ''
  runOutput.value = null
  normalizedResult.value = {}
  elapsedMs.value = null
  revokeAudio()
  try {
    const form = serializeScenarioForm('speech_tts', {
      text: text.value,
      speaker: speaker.value,
    })
    const response = await scenarioApi.infer(props.scenario.modelKey, form)
    if (!requestGuard.isCurrent(requestToken)) return
    runOutput.value = response.data
    elapsedMs.value = Number.isFinite(response.data?.elapsedMs) ? response.data.elapsedMs : null
    normalizedResult.value = normalizeWorkbenchResult('speech_tts', response.data?.result)
    setAudioFromResult(normalizedResult.value)
    emit('completed', response.data)
  } catch (requestError) {
    if (requestGuard.isCurrent(requestToken)) {
      error.value = requestError?.response?.data?.message || requestError?.message || '语音合成失败，请检查输入与运行环境。'
    }
  } finally {
    if (requestGuard.isCurrent(requestToken)) busy.value = false
  }
}

onBeforeUnmount(() => {
  requestGuard.dispose()
  revokeAudio()
})
</script>
