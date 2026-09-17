<template>
  <div class="wb-grid">
    <section class="wb-controls" aria-label="数字人输入与参数">
      <div class="wb-control-group">
        <h3>人物图片</h3>
        <label class="wb-dropzone" :class="{ 'is-disabled': busy }" @dragover.prevent @drop.prevent="dropImage">
          <input type="file" accept="image/*" :disabled="busy" @change="pickImage">
          <img v-if="imagePreview" :src="imagePreview" alt="人物缩略图">
          <strong>{{ imageFile ? imageFile.name : '拖入或选择人物图' }}</strong>
          <span>{{ inputHint }}</span>
        </label>
        <button v-if="imageFile" class="wb-text-button" type="button" :disabled="busy" @click="clearImage">清除图片</button>
      </div>

      <div class="wb-control-group">
        <h3>驱动音频</h3>
        <label class="wb-dropzone" :class="{ 'is-disabled': busy }" @dragover.prevent @drop.prevent="dropAudio">
          <input type="file" accept="audio/*,.wav,.mp3,.m4a" :disabled="busy" @change="pickAudio">
          <strong>{{ audioFile ? audioFile.name : '拖入或选择驱动音频' }}</strong>
          <span>驱动口型与表情</span>
        </label>
        <button v-if="audioFile" class="wb-text-button" type="button" :disabled="busy" @click="clearAudio">清除音频</button>
        <audio v-if="audioPreview" :src="audioPreview" controls style="width:100%;margin-top:8px"></audio>
      </div>

      <aside class="wb-capability-note">
        <strong>数字人合成</strong>
        <p>需要本地 talking-head 权重；合成较慢，适合单人正面清晰肖像。</p>
      </aside>

      <div v-if="validationMessage" class="wb-form-error" role="alert">{{ validationMessage }}</div>
      <button class="scenario-button wb-run" type="button" :disabled="!canRun" @click="runInference">
        {{ busy ? '正在合成…' : '运行真实数字人合成' }}
      </button>
    </section>

    <section class="wb-canvas" aria-label="数字人预览">
      <header class="wb-canvas__header">
        <div><strong>视频预览</strong><span>Talking Head</span></div>
      </header>
      <div v-if="videoUrl" class="wb-canvas-stage">
        <video :src="videoUrl" controls playsinline></video>
      </div>
      <div v-else-if="imagePreview" class="wb-canvas-stage">
        <img :src="imagePreview" alt="人物预览">
      </div>
      <div v-else class="wb-canvas-empty">
        <span aria-hidden="true">◎</span>
        <strong>等待输入</strong>
        <p>上传人物图与驱动音频后运行合成。</p>
      </div>
    </section>

    <ResultPanel
      title="数字人输出"
      :result="runOutput"
      :busy="busy"
      :error="error"
      :elapsed-ms="elapsedMs"
      :filename="`${scenario.modelKey}-talking-head`"
    >
      <div v-if="videoUrl" class="wb-result-content">
        <div class="wb-metrics">
          <div><span>格式</span><strong>{{ videoFormat }}</strong></div>
        </div>
        <p class="wb-result-note">视频以 Base64 返回；页面仅做预览，不二次剪辑。</p>
      </div>
      <div v-else class="wb-normal-empty">
        <strong>没有视频结果</strong>
        <p>确认权重与运行库就绪后重试。</p>
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

const imageFile = ref(null)
const imagePreview = ref('')
const audioFile = ref(null)
const audioPreview = ref('')
const busy = ref(false)
const error = ref('')
const runOutput = ref(null)
const normalizedResult = ref({})
const elapsedMs = ref(null)
const videoUrl = ref('')

const inputHint = computed(() => `${props.scenario.input?.formats?.join(', ') || '图片'} · 最大 ${props.scenario.input?.maxSizeMb || '配置'} MB`)
const validationErrors = computed(() => validateWorkbenchState('talking_head', {
  file: imageFile.value,
  audio: audioFile.value,
}))
const validationMessage = computed(() => (
  imageFile.value || audioFile.value ? validationErrors.value[0] || '' : ''
))
const canRun = computed(() => (props.scenario.apiReady ?? props.scenario.ready) && !busy.value && validationErrors.value.length === 0)
const videoFormat = computed(() => String(normalizedResult.value.format || 'mp4'))

function revokeVideo() {
  if (videoUrl.value) {
    URL.revokeObjectURL(videoUrl.value)
    videoUrl.value = ''
  }
}

function setImage(nextFile) {
  if (busy.value || !nextFile) return
  if (!isAcceptedImageCandidate(nextFile, props.scenario.input?.formats)) {
    error.value = '请选择浏览器可预览的图片文件。'
    return
  }
  if (imagePreview.value) URL.revokeObjectURL(imagePreview.value)
  imageFile.value = nextFile
  imagePreview.value = URL.createObjectURL(nextFile)
  error.value = ''
  runOutput.value = null
  normalizedResult.value = {}
  elapsedMs.value = null
  revokeVideo()
}

function setAudio(nextFile) {
  if (busy.value || !nextFile) return
  if (audioPreview.value) URL.revokeObjectURL(audioPreview.value)
  audioFile.value = nextFile
  audioPreview.value = URL.createObjectURL(nextFile)
  error.value = ''
  runOutput.value = null
  normalizedResult.value = {}
  elapsedMs.value = null
  revokeVideo()
}

function pickImage(event) {
  if (busy.value) return
  setImage(event.target.files?.[0])
  event.target.value = ''
}

function dropImage(event) {
  if (busy.value) return
  setImage(event.dataTransfer?.files?.[0])
}

function pickAudio(event) {
  if (busy.value) return
  setAudio(event.target.files?.[0])
  event.target.value = ''
}

function dropAudio(event) {
  if (busy.value) return
  setAudio(event.dataTransfer?.files?.[0])
}

function clearImage() {
  if (busy.value) return
  if (imagePreview.value) URL.revokeObjectURL(imagePreview.value)
  imageFile.value = null
  imagePreview.value = ''
  revokeVideo()
}

function clearAudio() {
  if (busy.value) return
  if (audioPreview.value) URL.revokeObjectURL(audioPreview.value)
  audioFile.value = null
  audioPreview.value = ''
  revokeVideo()
}

function setVideoFromResult(result) {
  revokeVideo()
  const b64 = result?.videoBase64 || result?.video
  if (!b64 || typeof b64 !== 'string') return
  const binary = atob(b64)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i)
  videoUrl.value = URL.createObjectURL(new Blob([bytes], { type: 'video/mp4' }))
}

async function runInference() {
  if (!canRun.value) return
  const requestToken = requestGuard.begin()
  busy.value = true
  error.value = ''
  runOutput.value = null
  normalizedResult.value = {}
  elapsedMs.value = null
  revokeVideo()
  try {
    const form = serializeScenarioForm('talking_head', {
      file: imageFile.value,
      audio: audioFile.value,
    })
    const response = await scenarioApi.infer(props.scenario.modelKey, form)
    if (!requestGuard.isCurrent(requestToken)) return
    runOutput.value = response.data
    elapsedMs.value = Number.isFinite(response.data?.elapsedMs) ? response.data.elapsedMs : null
    normalizedResult.value = normalizeWorkbenchResult('talking_head', response.data?.result)
    setVideoFromResult(normalizedResult.value)
    emit('completed', response.data)
  } catch (requestError) {
    if (requestGuard.isCurrent(requestToken)) {
      error.value = requestError?.response?.data?.message || requestError?.message || '数字人合成失败，请检查输入与运行环境。'
    }
  } finally {
    if (requestGuard.isCurrent(requestToken)) busy.value = false
  }
}

onBeforeUnmount(() => {
  requestGuard.dispose()
  if (imagePreview.value) URL.revokeObjectURL(imagePreview.value)
  if (audioPreview.value) URL.revokeObjectURL(audioPreview.value)
  revokeVideo()
})
</script>
