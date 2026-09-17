<template>
  <div class="squat-workbench">
    <section class="squat-controls">
      <div class="squat-tabs" role="tablist" aria-label="视频来源">
        <button v-for="item in sources" :key="item.key" type="button" :class="{ active: source === item.key }" :disabled="busy" @click="switchSource(item.key)">{{ item.label }}</button>
      </div>

      <label v-if="source === 'video'" class="wb-dropzone">
        <input type="file" accept="video/*" :disabled="busy" @change="pickVideo">
        <strong>{{ videoFile?.name || '选择训练视频' }}</strong>
        <span>完成后生成带骨架和计数的标注视频</span>
      </label>

      <div v-else-if="source === 'local'" class="squat-source-card">
        <strong>本地摄像头</strong>
        <p>{{ mediaReady ? '摄像头已授权，可开始实时计数。' : '视频仅用于实时分析，不保存录像。' }}</p>
        <button class="scenario-button scenario-button--ghost" type="button" :disabled="busy || mediaReady" @click="prepareLocalCamera">授权摄像头</button>
      </div>

      <div v-else class="squat-source-card">
        <label class="wb-field"><span>已登记网络摄像头</span>
          <select v-model="cameraId" :disabled="busy || camerasLoading">
            <option :value="null">请选择</option>
            <option v-for="camera in cameras" :key="camera.id" :value="camera.id">{{ camera.name }} · {{ camera.sourceType }}</option>
          </select>
        </label>
        <small v-if="!camerasLoading && !cameras.length">没有可用的已登记摄像头。</small>
      </div>

      <div class="wb-control-group">
        <h3>检测参数</h3>
        <label class="wb-field"><span>姿态置信度 <output>{{ conf.toFixed(2) }}</output></span><input v-model.number="conf" type="range" min="0.05" max="0.95" step="0.05" :disabled="busy"></label>
        <details>
          <summary>高级动作阈值</summary>
          <label class="wb-field"><span>站立角度</span><input v-model.number="standingAngle" type="number" min="1" max="180" :disabled="busy"></label>
          <label class="wb-field"><span>下蹲角度</span><input v-model.number="bottomAngle" type="number" min="1" max="179" :disabled="busy"></label>
          <label class="wb-field"><span>连续确认帧数</span><input v-model.number="confirmFrames" type="number" min="1" max="30" :disabled="busy"></label>
        </details>
      </div>

      <p v-if="validationMessage" class="wb-form-error" role="alert">{{ validationMessage }}</p>
      <p v-if="error" class="wb-form-error" role="alert">{{ error }}</p>
      <button v-if="!busy" class="scenario-button wb-run" type="button" :disabled="!canStart" @click="start">开始检测计数</button>
      <button v-else class="scenario-button wb-run" type="button" @click="stop">停止并保留摘要</button>
    </section>

    <section class="squat-stage" aria-label="蹲起检测画面">
      <header><strong>动作画面</strong><span>{{ sourceLabel }}</span></header>
      <video v-show="source === 'local' && mediaReady && !annotatedImage" ref="localVideo" autoplay muted playsinline></video>
      <img v-if="annotatedImage" :src="annotatedImage" alt="实时蹲起标注画面">
      <img v-else-if="networkStreamUrl" :src="networkStreamUrl" alt="网络摄像头蹲起标注流">
      <video v-else-if="outputUrl" :src="outputUrl" controls playsinline></video>
      <div v-else class="wb-canvas-empty"><strong>等待视频输入</strong><p>请在左侧选择来源并开始检测。</p></div>
      <canvas ref="captureCanvas" hidden></canvas>
    </section>

    <aside class="squat-dashboard" aria-live="polite">
      <div class="squat-count"><span>已完成</span><strong>{{ metrics.count }}</strong><small>次蹲起</small></div>
      <dl>
        <div><dt>阶段</dt><dd>{{ stageLabel }}</dd></div>
        <div><dt>膝角</dt><dd>{{ angleLabel }}</dd></div>
        <div><dt>跟踪</dt><dd>{{ trackingLabel }}</dd></div>
        <div><dt>有效时长</dt><dd>{{ Number(metrics.activeSeconds || 0).toFixed(1) }} s</dd></div>
        <div><dt>处理进度</dt><dd>{{ progressLabel }}</dd></div>
      </dl>
      <a v-if="outputUrl" class="scenario-button" :href="outputUrl" download>下载标注视频</a>
    </aside>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

import { cameraApi } from '../../../../api/camera'
import { squatApi } from '../../../../api/squat'
import { validateSquatParameters, validateSquatSourceState } from '../scenarioState'

const props = defineProps({ scenario: { type: Object, required: true } })
const emit = defineEmits(['completed'])

const sources = [
  { key: 'video', label: '上传视频' },
  { key: 'local', label: '本地摄像头' },
  { key: 'network', label: '网络摄像头' },
]
const source = ref('video')
const videoFile = ref(null)
const cameraId = ref(null)
const cameras = ref([])
const camerasLoading = ref(false)
const conf = ref(Number(props.scenario.defaults?.conf ?? 0.25))
const standingAngle = ref(Number(props.scenario.defaults?.standingAngle ?? 160))
const bottomAngle = ref(Number(props.scenario.defaults?.bottomAngle ?? 100))
const confirmFrames = ref(Number(props.scenario.defaults?.confirmFrames ?? 3))
const busy = ref(false)
const mediaReady = ref(false)
const error = ref('')
const localVideo = ref(null)
const captureCanvas = ref(null)
const annotatedImage = ref('')
const networkStreamUrl = ref('')
const outputUrl = ref('')
const sessionId = ref('')
const progress = ref({ processed: 0, total: 0 })
const metrics = ref({ count: 0, stage: 'waiting_stand', trackingStatus: 'no_person', activeSeconds: 0 })
let mediaStream = null
let pollTimer = null
let frameTimer = null
let requestGeneration = 0
let frameSequence = 0

const modelId = computed(() => props.scenario.model?.id)
const sourceLabel = computed(() => sources.find((item) => item.key === source.value)?.label || '')
const validationMessage = computed(() => [
  ...validateSquatParameters({ standingAngle: standingAngle.value, bottomAngle: bottomAngle.value, confirmFrames: confirmFrames.value }),
  ...validateSquatSourceState(source.value, { file: videoFile.value, mediaReady: mediaReady.value, cameraId: cameraId.value }),
][0] || '')
const canStart = computed(() => Boolean(modelId.value) && Boolean(props.scenario.apiReady ?? props.scenario.ready) && !validationMessage.value)
const stageLabel = computed(() => ({ waiting_stand: '等待站立', standing: '站立', descending: '下蹲中', bottom: '已到底', ascending: '起身中' })[metrics.value.stage] || metrics.value.stage || '等待')
const trackingLabel = computed(() => ({ tracking: '已锁定', no_person: '未检测到人体', temporarily_lost: '目标短暂丢失', insufficient_keypoints: '腿部关键点不足' })[metrics.value.trackingStatus] || metrics.value.trackingStatus || '等待')
const angleLabel = computed(() => Number.isFinite(metrics.value.kneeAngle) ? `${metrics.value.kneeAngle.toFixed(1)}°` : '--')
const progressLabel = computed(() => progress.value.total ? `${Math.round(progress.value.processed / progress.value.total * 100)}%` : (busy.value ? '实时' : '--'))

function parameters() {
  return { modelId: modelId.value, conf: conf.value, standingAngle: standingAngle.value, bottomAngle: bottomAngle.value, confirmFrames: confirmFrames.value }
}

function pickVideo(event) {
  videoFile.value = event.target.files?.[0] || null
  outputUrl.value = ''
  event.target.value = ''
}

async function loadCameras() {
  camerasLoading.value = true
  try {
    const response = await cameraApi.list({ pageNum: 1, pageSize: 100, status: '0' })
    cameras.value = response.data?.rows || []
  } catch {
    cameras.value = []
  } finally {
    camerasLoading.value = false
  }
}

async function prepareLocalCamera() {
  error.value = ''
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 960 }, height: { ideal: 540 } }, audio: false })
    mediaReady.value = true
    await nextTick()
    localVideo.value.srcObject = mediaStream
    await localVideo.value.play()
  } catch (reason) {
    error.value = reason?.message || '无法访问本地摄像头'
    mediaReady.value = false
  }
}

function applyState(state) {
  if (!state) return
  metrics.value = { ...metrics.value, ...state }
}

async function startVideoJob(generation) {
  const form = new FormData()
  form.append('file', videoFile.value)
  Object.entries(parameters()).forEach(([key, value]) => form.append(key, String(value)))
  const response = await squatApi.startVideo(form)
  const jobId = response.data.jobId
  const poll = async () => {
    if (generation !== requestGeneration) return
    const current = await squatApi.videoProgress(jobId)
    if (generation !== requestGeneration) return
    progress.value = { processed: current.data.processed || 0, total: current.data.total || 0 }
    if (current.data.status === 'done') {
      applyState(current.data.stats)
      outputUrl.value = squatApi.outputUrl(current.data.stats.output)
      busy.value = false
      emit('completed', { modelKey: props.scenario.modelKey, ...current.data.stats })
    } else if (current.data.status === 'error') {
      throw new Error(current.data.error || '视频分析失败')
    } else {
      pollTimer = window.setTimeout(poll, 800)
    }
  }
  await poll()
}

async function createLiveSession(generation) {
  const response = await squatApi.createSession({
    ...parameters(), sourceType: source.value, ...(source.value === 'network' ? { cameraId: cameraId.value } : {}),
  })
  if (generation !== requestGeneration) return
  sessionId.value = response.data.sessionId
  applyState(response.data)
  if (source.value === 'network') {
    networkStreamUrl.value = squatApi.streamUrl(sessionId.value)
    pollSession(generation)
  } else {
    sendLocalFrame(generation)
  }
}

async function pollSession(generation) {
  if (generation !== requestGeneration || !sessionId.value) return
  try {
    const response = await squatApi.session(sessionId.value)
    if (generation !== requestGeneration) return
    applyState(response.data)
    if (response.data.status === 'running') pollTimer = window.setTimeout(() => pollSession(generation), 700)
    else busy.value = false
  } catch (reason) {
    if (generation === requestGeneration) { error.value = reason?.message || '会话状态读取失败'; busy.value = false }
  }
}

async function sendLocalFrame(generation) {
  if (generation !== requestGeneration || !busy.value || !sessionId.value || !localVideo.value?.videoWidth) return
  const canvas = captureCanvas.value
  const width = Math.min(960, localVideo.value.videoWidth)
  const height = Math.round(width * localVideo.value.videoHeight / localVideo.value.videoWidth)
  canvas.width = width
  canvas.height = height
  canvas.getContext('2d').drawImage(localVideo.value, 0, 0, width, height)
  const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.78))
  if (!blob || generation !== requestGeneration) return
  const form = new FormData()
  form.append('file', blob, 'frame.jpg')
  form.append('sequence', String(++frameSequence))
  form.append('capturedAt', String(performance.now() / 1000))
  try {
    const response = await squatApi.submitFrame(sessionId.value, form)
    if (generation !== requestGeneration) return
    applyState(response.data.state)
    annotatedImage.value = `data:image/jpeg;base64,${response.data.annotatedImageBase64}`
  } catch (reason) {
    if (generation === requestGeneration) error.value = reason?.message || '实时帧分析失败'
  }
  if (generation === requestGeneration && busy.value) frameTimer = window.setTimeout(() => sendLocalFrame(generation), 250)
}

async function start() {
  if (!canStart.value) return
  error.value = ''
  busy.value = true
  const generation = ++requestGeneration
  try {
    if (source.value === 'video') await startVideoJob(generation)
    else await createLiveSession(generation)
  } catch (reason) {
    if (generation === requestGeneration) { error.value = reason?.message || '蹲起检测启动失败'; busy.value = false }
  }
}

async function stop() {
  ++requestGeneration
  window.clearTimeout(pollTimer)
  window.clearTimeout(frameTimer)
  if (sessionId.value) {
    try {
      const response = await squatApi.stopSession(sessionId.value)
      applyState(response.data)
      emit('completed', { modelKey: props.scenario.modelKey, ...response.data })
    } catch { /* session may already have expired */ }
  }
  sessionId.value = ''
  networkStreamUrl.value = ''
  busy.value = false
}

async function switchSource(next) {
  if (next === source.value) return
  await stop()
  annotatedImage.value = ''
  outputUrl.value = ''
  source.value = next
  if (next === 'network' && !cameras.value.length) loadCameras()
}

function releaseMedia() {
  mediaStream?.getTracks().forEach((track) => track.stop())
  mediaStream = null
  mediaReady.value = false
}

watch(() => props.scenario.modelKey, async () => { await stop() })
onBeforeUnmount(() => { stop(); releaseMedia() })
</script>

<style scoped>
.squat-workbench { display: grid; grid-template-columns: minmax(250px, .8fr) minmax(360px, 1.6fr) minmax(220px, .7fr); gap: 18px; }
.squat-controls, .squat-stage, .squat-dashboard { border: 1px solid var(--scenario-line, #d8e0e8); border-radius: 14px; padding: 18px; background: var(--scenario-panel, #fff); }
.squat-tabs { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; margin-bottom: 18px; }
.squat-tabs button { border: 1px solid #ccd7df; border-radius: 8px; padding: 9px 5px; background: transparent; cursor: pointer; }
.squat-tabs button.active { color: #fff; border-color: #1677ff; background: #1677ff; }
.squat-source-card { padding: 16px; margin-bottom: 16px; border-radius: 10px; background: #f4f7fa; }
.squat-stage { min-height: 420px; display: flex; flex-direction: column; }
.squat-stage header { display: flex; justify-content: space-between; margin-bottom: 12px; }
.squat-stage img, .squat-stage video { width: 100%; min-height: 320px; max-height: 560px; object-fit: contain; background: #081018; border-radius: 10px; }
.squat-stage .wb-canvas-empty { flex: 1; }
.squat-count { display: grid; text-align: center; padding: 22px 8px; border-radius: 12px; color: #fff; background: linear-gradient(145deg, #075985, #0f766e); }
.squat-count strong { font-size: 64px; line-height: 1; margin: 8px 0; }
.squat-dashboard dl div { display: flex; justify-content: space-between; gap: 16px; padding: 12px 0; border-bottom: 1px solid #e5eaf0; }
.squat-dashboard dd { margin: 0; font-weight: 700; text-align: right; }
@media (max-width: 1100px) { .squat-workbench { grid-template-columns: 1fr 1.5fr; } .squat-dashboard { grid-column: 1 / -1; } }
@media (max-width: 760px) { .squat-workbench { grid-template-columns: 1fr; } .squat-dashboard { grid-column: auto; } }
</style>
