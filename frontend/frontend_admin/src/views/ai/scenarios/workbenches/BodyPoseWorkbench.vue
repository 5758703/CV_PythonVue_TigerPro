<template>
  <div class="wb-grid">
    <section class="wb-controls" aria-label="人体姿态估计输入与参数">
      <div class="wb-control-group">
        <h3>待估计图像</h3>
        <label class="wb-dropzone" :class="{ 'is-dragging': dragging, 'is-disabled': busy }" @dragenter.prevent="onDragEnter" @dragover.prevent @dragleave.prevent="onDragLeave" @drop.prevent="onDrop">
          <input type="file" accept="image/*" :disabled="busy" @change="onFileChange">
          <strong>{{ file ? file.name : '拖入图片或选择文件' }}</strong>
          <span>{{ inputHint }}</span>
        </label>
        <button v-if="file" class="wb-text-button" type="button" :disabled="busy" @click="clearFile">清除图片</button>
      </div>

      <div class="wb-control-group">
        <div class="wb-control-heading"><h3>姿态参数</h3><button class="wb-text-button" type="button" :disabled="busy" @click="resetParameters">恢复默认</button></div>
        <label class="wb-field">
          <span>置信度 <output>{{ Number(conf).toFixed(2) }}</output></span>
          <input v-model.number="conf" type="range" min="0" max="1" step="0.01" :disabled="busy">
        </label>
      </div>

      <aside class="wb-capability-note">
        <strong>骨架关键点</strong>
        <p>关键点模型不直接理解业务动作；生产分析须叠加时序规则或分类层。</p>
      </aside>

      <div v-if="validationMessage" class="wb-form-error" role="alert">{{ validationMessage }}</div>
      <button class="scenario-button wb-run" type="button" :disabled="!canRun" @click="runInference">
        {{ busy ? '正在估计…' : '运行真实姿态估计' }}
      </button>
    </section>

    <section class="wb-canvas" aria-label="人体姿态画布">
      <header class="wb-canvas__header">
        <div><strong>骨架预览</strong><span>优先后端叠加图</span></div>
        <span v-if="personCount">{{ personCount }} 人</span>
      </header>
      <div v-if="displayUrl" class="wb-canvas-stage">
        <img :src="displayUrl" :alt="resultImageUrl ? '姿态骨架叠加图' : '待估计姿态图片'">
      </div>
      <div v-else class="wb-canvas-empty">
        <span aria-hidden="true">◇</span>
        <strong>等待姿态图像</strong>
        <p>运行后优先展示后端返回的骨架叠加图。</p>
      </div>
    </section>

    <ResultPanel
      title="人体姿态输出"
      :result="runOutput"
      :busy="busy"
      :error="error"
      :elapsed-ms="elapsedMs"
      :image-url="resultImageUrl"
      :filename="`${scenario.modelKey}-pose`"
    >
      <div v-if="personCount" class="wb-result-content">
        <div class="wb-metrics">
          <div><span>人数</span><strong>{{ personCount }}</strong></div>
          <div><span>关键点数</span><strong>{{ keypointCountLabel }}</strong></div>
          <div><span>姿态类型</span><strong>{{ poseTypeLabel }}</strong></div>
        </div>
        <div class="wb-table-wrap">
          <table class="wb-table">
            <thead><tr><th>#</th><th>分数</th><th>关键点</th><th>坐标</th></tr></thead>
            <tbody>
              <tr v-for="(item, index) in normalizedResult.persons" :key="index">
                <td>{{ index + 1 }}</td>
                <td>{{ displayScore(item) }}</td>
                <td>{{ item.keypoints?.length || '—' }}</td>
                <td>{{ item.bbox ? item.bbox.join(', ') : '未返回' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="wb-result-note">骨架仅描述几何姿态；挥拍阶段、动作类别等业务语义须另行建模。</p>
      </div>
      <div v-else class="wb-normal-empty">
        <strong>没有检测到人体</strong>
        <p>这是正常空结果。可降低置信度或更换更清晰的全身图像。</p>
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
const conf = ref(Number(props.scenario.defaults?.conf ?? 0.25))
const busy = ref(false)
const error = ref('')
const runOutput = ref(null)
const normalizedResult = ref({ persons: [], count: 0 })
const elapsedMs = ref(null)

const inputHint = computed(() => `${props.scenario.input?.formats?.join(', ') || '图片'} · 最大 ${props.scenario.input?.maxSizeMb || '配置'} MB`)
const workbenchType = computed(() => (
  props.scenario.workbenchType === 'hand_pose' ? 'hand_pose' : 'body_pose'
))
const validationErrors = computed(() => validateWorkbenchState(workbenchType.value, {
  file: file.value,
  conf: conf.value,
}, props.scenario.input))
const validationMessage = computed(() => file.value ? validationErrors.value[0] || '' : '')
const canRun = computed(() => (props.scenario.apiReady ?? props.scenario.ready) && !busy.value && validationErrors.value.length === 0)
const resultImageUrl = computed(() => normalizedResult.value.imageBase64 ? `data:image/jpeg;base64,${normalizedResult.value.imageBase64}` : '')
const displayUrl = computed(() => resultImageUrl.value || previewUrl.value)
const personCount = computed(() => {
  if (Number.isInteger(normalizedResult.value.count)) return normalizedResult.value.count
  return Array.isArray(normalizedResult.value.persons) ? normalizedResult.value.persons.length : 0
})
const keypointCountLabel = computed(() => (
  Number.isFinite(normalizedResult.value.keypointCount) ? String(normalizedResult.value.keypointCount) : '—'
))
const poseTypeLabel = computed(() => normalizedResult.value.poseType || '—')

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
  normalizedResult.value = { persons: [], count: 0 }
  elapsedMs.value = null
}

function resetParameters() {
  if (busy.value) return
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
      conf: conf.value,
    })
    const response = await scenarioApi.infer(props.scenario.modelKey, form)
    if (!requestGuard.isCurrent(requestToken)) return
    runOutput.value = response.data
    elapsedMs.value = Number.isFinite(response.data?.elapsedMs) ? response.data.elapsedMs : null
    normalizedResult.value = normalizeWorkbenchResult(workbenchType.value, response.data?.result)
    emit('completed', response.data)
  } catch (requestError) {
    if (requestGuard.isCurrent(requestToken)) {
      error.value = requestError?.response?.data?.message || requestError?.message || '人体姿态估计失败，请检查输入与运行环境。'
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
