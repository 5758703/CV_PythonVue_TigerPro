<template>
  <div class="wb-grid wb-grid--reid">
    <section class="wb-controls" aria-label="车辆 ReID 输入与参数">
      <div class="wb-control-group">
        <h3>查询车辆</h3>
        <label class="wb-dropzone" :class="{ 'is-disabled': busy }" @dragover.prevent @drop.prevent="dropQuery">
          <input type="file" accept="image/*" :disabled="busy" @change="pickQuery">
          <img v-if="queryPreview" :src="queryPreview" alt="查询车辆缩略图">
          <strong>{{ queryFile ? queryFile.name : '拖入或选择查询图' }}</strong>
          <span>单张查询图 · {{ inputHint }}</span>
        </label>
        <button v-if="queryFile" class="wb-text-button" type="button" :disabled="busy" @click="clearQuery">清除查询图</button>
      </div>

      <div class="wb-control-group">
        <h3>候选图库</h3>
        <label class="wb-dropzone" :class="{ 'is-disabled': busy }" @dragover.prevent @drop.prevent="dropGallery">
          <input type="file" accept="image/*" multiple :disabled="busy" @change="pickGallery">
          <strong>添加一张或多张候选图</strong>
          <span>重复 gallery 字段 · {{ inputHint }}</span>
        </label>
        <div v-if="galleryItems.length" class="wb-thumbnails" aria-label="候选图列表">
          <figure v-for="(item, index) in galleryItems" :key="item.id">
            <img :src="item.url" :alt="`候选车辆 ${item.file.name}`">
            <figcaption :title="item.file.name">{{ item.file.name }}</figcaption>
            <button type="button" :disabled="busy" :aria-label="`移除 ${item.file.name}`" @click="removeGallery(index)">×</button>
          </figure>
        </div>
      </div>

      <div class="wb-control-group">
        <div class="wb-control-heading"><h3>业务参数</h3><button class="wb-text-button" type="button" :disabled="busy" @click="resetParameters">恢复默认</button></div>
        <label class="wb-field">
          <span>匹配阈值 <output>{{ Number(threshold).toFixed(2) }}</output></span>
          <input v-model.number="threshold" type="range" min="0" max="1" step="0.01" :disabled="busy">
        </label>
        <p>后端按该阈值返回匹配或拒识结论；页面不重写判定。</p>
      </div>

      <div v-if="validationMessage" class="wb-form-error" role="alert">{{ validationMessage }}</div>
      <button class="scenario-button wb-run" type="button" :disabled="!canRun" @click="runInference">
        {{ busy ? '正在比对…' : '运行真实 ReID' }}
      </button>
      <RouterLink class="wb-flow-link" to="/ai/mtmc">进入完整视频 MTMC 流程 <span aria-hidden="true">→</span></RouterLink>
    </section>

    <section class="wb-canvas wb-reid-stage" aria-label="车辆候选排序画布">
      <header class="wb-canvas__header">
        <div><strong>候选排序</strong><span>查询特征 → 多候选真实相似度</span></div>
        <span>{{ galleryItems.length }} 个候选</span>
      </header>
      <div v-if="queryPreview" class="wb-reid-query">
        <span>QUERY</span>
        <img :src="queryPreview" alt="查询车辆大图预览">
      </div>
      <div v-else class="wb-canvas-empty">
        <span aria-hidden="true">⇄</span>
        <strong>等待查询车辆</strong>
        <p>上传查询图与候选图库后执行外观特征比对。</p>
      </div>
      <ol v-if="rankedMatches.length" class="wb-rank-list">
        <li v-for="(match, index) in rankedMatches" :key="match.galleryIndex">
          <span class="wb-rank-list__rank">{{ String(index + 1).padStart(2, '0') }}</span>
          <img v-if="galleryPreview(match.galleryIndex)" :src="galleryPreview(match.galleryIndex)" :alt="match.filename">
          <div>
            <strong>{{ match.filename || `候选 ${index + 1}` }}</strong>
            <span v-if="typeof match.similarity === 'number'">相似度 {{ (match.similarity * 100).toFixed(2) }}%</span>
            <span v-else>后端未返回相似度</span>
          </div>
          <b :class="match.matched === true ? 'is-match' : match.matched === false ? 'is-reject' : ''">
            {{ match.matched === true ? '匹配' : match.matched === false ? '拒识' : '未判定' }}
          </b>
        </li>
      </ol>
    </section>

    <ResultPanel
      title="ReID 结构化输出"
      :result="runOutput"
      :busy="busy"
      :error="error"
      :elapsed-ms="elapsedMs"
      :filename="`${scenario.modelKey}-reid`"
      empty-text="完成查询图与候选图库配置后运行比对。"
    >
      <div v-if="rankedMatches.length" class="wb-result-content">
        <div class="wb-metrics">
          <div><span>候选</span><strong>{{ rankedMatches.length }}</strong></div>
          <div><span>匹配</span><strong>{{ matchedCount }}</strong></div>
          <div><span>拒识</span><strong>{{ rejectedCount }}</strong></div>
          <div><span>TOP-1</span><strong>{{ topScore }}</strong></div>
        </div>
        <dl class="wb-result-facts">
          <div><dt>查询文件</dt><dd>{{ normalizedResult.query || '未返回' }}</dd></div>
          <div><dt>运行后端</dt><dd>{{ normalizedResult.backend?.backend || '未返回' }}</dd></div>
          <div><dt>特征维度</dt><dd>{{ normalizedResult.backend?.dim ?? '未返回' }}</dd></div>
          <div><dt>输入尺寸</dt><dd>{{ normalizedResult.backend?.inputSize || '未返回' }}</dd></div>
        </dl>
        <p class="wb-result-note">当前响应可作为 MTMC 候选关联输入；global_id 与时间线须在完整 MTMC 流程中生成。</p>
      </div>
      <div v-else class="wb-normal-empty">
        <strong>没有候选匹配结果</strong>
        <p>这是正常空结果。检查候选图片质量或降低阈值后重试。</p>
      </div>
    </ResultPanel>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, ref } from 'vue'

import { scenarioApi } from '../../../../api/modelScenarios'
import ResultPanel from '../components/ResultPanel.vue'
import { isAcceptedImageCandidate, normalizeWorkbenchResult, serializeScenarioForm, validateWorkbenchState } from '../scenarioState'

const props = defineProps({ scenario: { type: Object, required: true } })
const emit = defineEmits(['completed'])

const queryFile = ref(null)
const queryPreview = ref('')
const galleryItems = ref([])
const threshold = ref(Number(props.scenario.defaults?.threshold ?? 0.7))
const busy = ref(false)
const error = ref('')
const runOutput = ref(null)
const normalizedResult = ref({ matches: [] })
const elapsedMs = ref(null)
let gallerySequence = 0

const rankedMatches = computed(() => normalizedResult.value.matches || [])
const inputHint = computed(() => `${props.scenario.input?.formats?.join(', ') || '图片'} · 单张最大 ${props.scenario.input?.maxSizeMb || '配置'} MB`)
const validationErrors = computed(() => validateWorkbenchState('vehicle_reid', {
  query: queryFile.value,
  gallery: galleryItems.value.map((item) => item.file),
  threshold: threshold.value,
}, props.scenario.input))
const validationMessage = computed(() => queryFile.value || galleryItems.value.length ? validationErrors.value[0] || '' : '')
const canRun = computed(() => props.scenario.ready && !busy.value && validationErrors.value.length === 0)
const matchedCount = computed(() => rankedMatches.value.filter((item) => item.matched === true).length)
const rejectedCount = computed(() => rankedMatches.value.filter((item) => item.matched === false).length)
const topScore = computed(() => typeof rankedMatches.value[0]?.similarity === 'number'
  ? `${(rankedMatches.value[0].similarity * 100).toFixed(2)}%` : '未返回')

function acceptImage(nextFile) {
  if (busy.value) return false
  if (!isAcceptedImageCandidate(nextFile, props.scenario.input?.formats)) {
    error.value = '请选择浏览器可预览的图片文件。'
    return false
  }
  error.value = ''
  runOutput.value = null
  normalizedResult.value = { matches: [] }
  elapsedMs.value = null
  return true
}

function setQuery(nextFile) {
  if (busy.value) return
  if (!acceptImage(nextFile)) return
  if (queryPreview.value) URL.revokeObjectURL(queryPreview.value)
  queryFile.value = nextFile
  queryPreview.value = URL.createObjectURL(nextFile)
}

function clearQuery() {
  if (busy.value) return
  if (queryPreview.value) URL.revokeObjectURL(queryPreview.value)
  queryFile.value = null
  queryPreview.value = ''
  runOutput.value = null
  normalizedResult.value = { matches: [] }
  elapsedMs.value = null
}

function addGallery(files) {
  if (busy.value) return
  for (const nextFile of files || []) {
    if (!acceptImage(nextFile)) continue
    galleryItems.value.push({ id: ++gallerySequence, file: nextFile, url: URL.createObjectURL(nextFile) })
  }
}

function pickQuery(event) {
  if (busy.value) return
  setQuery(event.target.files?.[0])
  event.target.value = ''
}

function dropQuery(event) {
  if (busy.value) return
  setQuery(event.dataTransfer?.files?.[0])
}

function pickGallery(event) {
  if (busy.value) return
  addGallery(event.target.files)
  event.target.value = ''
}

function dropGallery(event) {
  if (busy.value) return
  addGallery(event.dataTransfer?.files)
}

function removeGallery(index) {
  if (busy.value) return
  URL.revokeObjectURL(galleryItems.value[index].url)
  galleryItems.value.splice(index, 1)
  runOutput.value = null
  normalizedResult.value = { matches: [] }
  elapsedMs.value = null
}

function galleryPreview(galleryIndex) {
  return galleryItems.value[galleryIndex]?.url || ''
}

function resetParameters() {
  if (busy.value) return
  threshold.value = Number(props.scenario.defaults?.threshold ?? 0.7)
}

async function runInference() {
  if (!canRun.value) return
  busy.value = true
  error.value = ''
  runOutput.value = null
  normalizedResult.value = { matches: [] }
  elapsedMs.value = null
  try {
    const form = serializeScenarioForm('vehicle_reid', {
      query: queryFile.value,
      gallery: galleryItems.value.map((item) => item.file),
      threshold: threshold.value,
    })
    const response = await scenarioApi.infer(props.scenario.modelKey, form)
    runOutput.value = response.data
    elapsedMs.value = Number.isFinite(response.data?.elapsedMs) ? response.data.elapsedMs : null
    normalizedResult.value = normalizeWorkbenchResult('vehicle_reid', response.data?.result)
    emit('completed', response.data)
  } catch (requestError) {
    error.value = requestError?.response?.data?.message || requestError?.message || '车辆 ReID 推理失败，请检查输入与运行环境。'
  } finally {
    busy.value = false
  }
}

onBeforeUnmount(() => {
  if (queryPreview.value) URL.revokeObjectURL(queryPreview.value)
  galleryItems.value.forEach((item) => URL.revokeObjectURL(item.url))
})
</script>
