<template>
  <main class="scenario-page scenario-detail" aria-labelledby="scenario-title">
    <RouterLink class="scenario-back" to="/ai/scenarios"><span aria-hidden="true">←</span> 返回场景总览</RouterLink>

    <section v-if="loading" class="scenario-state" aria-live="polite">
      <span class="scenario-loader" aria-hidden="true"></span>
      <h1 id="scenario-title">正在装载场景</h1>
      <p>读取场景分组与当前模型就绪状态。</p>
    </section>

    <section v-else-if="notFound" class="scenario-state scenario-state--error" role="alert">
      <span class="scenario-state__code">SCENARIO 404</span>
      <h1 id="scenario-title">场景不存在</h1>
      <p>该固定路由没有对应的场景分组登记。</p>
      <RouterLink class="scenario-button" to="/ai/scenarios">返回场景总览</RouterLink>
    </section>

    <section v-else-if="loadError" class="scenario-state scenario-state--error" role="alert">
      <span class="scenario-state__code">LOAD FAILED</span>
      <h1 id="scenario-title">场景加载失败</h1>
      <p>{{ loadError }}</p>
      <button class="scenario-button" type="button" @click="loadScenario">重新加载</button>
    </section>

    <template v-else-if="scenario">
      <header class="scenario-detail__header">
        <div>
          <p class="scenario-kicker">SCENARIO {{ String(scenario.order).padStart(2, '0') }} · {{ abilityLabel }}</p>
          <h1 id="scenario-title">{{ groupName }}</h1>
          <p>{{ scenario.description }}</p>
          <code>{{ selectedModelKey }}</code>
          <label v-if="modelOptions.length > 1" class="scenario-field scenario-model-select">
            <span>模型</span>
            <select :value="selectedModelKey" @change="onModelChange">
              <option
                v-for="model in modelOptions"
                :key="model.modelKey"
                :value="model.modelKey"
              >
                {{ model.name }} · {{ modelReady(model) ? '可运行' : '待准备' }}
              </option>
            </select>
          </label>
        </div>
        <div :class="['scenario-health', apiReady ? 'is-ready' : 'is-pending']">
          <span aria-hidden="true"></span>
          <div>
            <strong>{{ apiReady ? '生产可运行' : '等待环境准备' }}</strong>
            <small>{{ apiReady ? '模型、权重、运行库与 API 均已就绪' : readinessReason }}</small>
          </div>
        </div>
      </header>

      <ol class="scenario-status-strip" aria-label="四级就绪状态">
        <li v-for="(stage, index) in readinessStages" :key="stage.key" :class="{ 'is-complete': stage.value }">
          <span class="scenario-status-strip__index">{{ index + 1 }}</span>
          <span><strong>{{ stage.label }}</strong><small>{{ stage.detail }}</small></span>
        </li>
      </ol>

      <aside v-if="!apiReady" class="scenario-readiness-note" aria-labelledby="preparation-title">
        <div>
          <p class="scenario-kicker">PREPARATION REQUIRED</p>
          <h2 id="preparation-title">该模型尚未就绪</h2>
          <p>{{ readinessReason }}。你仍可查看工作流程、验收指标与 API 契约。</p>
        </div>
        <ol>
          <li v-for="step in preparationSteps" :key="step">{{ step }}</li>
        </ol>
      </aside>

      <section class="scenario-project" aria-labelledby="project-title">
        <div>
          <p class="scenario-kicker">PRODUCTION PROJECT</p>
          <h2 id="project-title">{{ scenario.project }}</h2>
          <p>{{ scenario.description }}</p>
        </div>
        <dl>
          <div><dt>能力类别</dt><dd>{{ abilityLabel }}</dd></div>
          <div><dt>输入限制</dt><dd>{{ inputLimit }}</dd></div>
          <div><dt>核心产出</dt><dd>{{ scenario.outputs }}</dd></div>
        </dl>
      </section>

      <section class="scenario-workbench" aria-labelledby="workbench-title">
        <div class="scenario-section-heading">
          <div>
            <p class="scenario-kicker">WORKBENCH</p>
            <h2 id="workbench-title">{{ abilityLabel }}工作台</h2>
          </div>
          <span class="scenario-workbench__mode">当前模型 · {{ selectedModelKey }}</span>
        </div>
        <component
          :is="workbenchComponent"
          v-if="workbenchComponent"
          :key="selectedModelKey"
          :scenario="scenario"
          @completed="onWorkbenchCompleted"
        />
        <div v-else class="scenario-workbench__fallback">
            <div class="scenario-canvas-placeholder" aria-hidden="true">
              <span></span><span></span><span></span>
              <b>VISION CANVAS</b>
            </div>
            <div>
              <span class="scenario-state__code">{{ workbench ? workbench.toUpperCase() : 'UNSUPPORTED' }}</span>
              <h3>{{ workbench ? '专用工作台正在接入' : '暂不支持该工作台类型' }}</h3>
              <p>场景外壳已锁定分组身份；工作台插槽可安全接入输入、运行与结构化结果区域。</p>
              <button class="scenario-button" type="button" disabled>运行推理</button>
            </div>
        </div>
        <p v-if="lastCompletedKey" class="scenario-sr-status" aria-live="polite">
          {{ lastCompletedKey }} 推理已完成。
        </p>
      </section>

      <section class="scenario-operations" aria-label="生产说明">
        <article>
          <span class="scenario-panel-number">01</span>
          <p class="scenario-kicker">WORKFLOW</p>
          <h2>生产流程</h2>
          <p>{{ scenario.workflow }}</p>
        </article>
        <article>
          <span class="scenario-panel-number">02</span>
          <p class="scenario-kicker">ACCEPTANCE</p>
          <h2>验收指标</h2>
          <p>{{ scenario.metrics }}</p>
        </article>
        <article class="scenario-operations__risk">
          <span class="scenario-panel-number">03</span>
          <p class="scenario-kicker">RISK BOUNDARY</p>
          <h2>风险边界</h2>
          <p>{{ scenario.risks }}</p>
        </article>
      </section>

      <section
        class="scenario-api"
        :class="{ 'is-collapsed': !apiPanelOpen }"
        aria-labelledby="api-title"
      >
        <div class="scenario-section-heading scenario-api__heading">
          <button
            class="scenario-api__toggle"
            type="button"
            :aria-expanded="apiPanelOpen"
            aria-controls="scenario-api-panel"
            @click="apiPanelOpen = !apiPanelOpen"
          >
            <div>
              <p class="scenario-kicker">OPEN API CONTRACT</p>
              <h2 id="api-title">API 调用</h2>
            </div>
            <span class="scenario-api__chevron" aria-hidden="true"></span>
            <span class="scenario-api__toggle-label">{{ apiPanelOpen ? '收起' : '展开' }}</span>
          </button>
          <button
            v-show="apiPanelOpen"
            class="scenario-button scenario-button--ghost"
            type="button"
            @click="copyCurl"
          >
            {{ copied ? '已复制' : '复制 curl' }}
          </button>
        </div>
        <div
          v-show="apiPanelOpen"
          id="scenario-api-panel"
          class="scenario-api__body"
        >
          <pre class="scenario-code" tabindex="0"><code>{{ curlExample }}</code></pre>
          <div class="scenario-api__grid">
            <div>
              <h3>请求字段</h3>
              <dl class="scenario-api__fields">
                <div v-for="field in apiFields" :key="field.name">
                  <dt><code>{{ field.name }}</code><span>{{ field.required ? '必填' : '可选' }}</span></dt>
                  <dd>{{ field.description }}</dd>
                </div>
              </dl>
            </div>
            <div>
              <h3>响应示例</h3>
              <pre class="scenario-code" tabindex="0"><code>{{ responseExample }}</code></pre>
            </div>
          </div>
        </div>
      </section>
    </template>
  </main>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { scenarioApi } from '../../../api/modelScenarios'
import BodyPoseWorkbench from './workbenches/BodyPoseWorkbench.vue'
import ClassificationWorkbench from './workbenches/ClassificationWorkbench.vue'
import FaceRecognitionWorkbench from './workbenches/FaceRecognitionWorkbench.vue'
import InpaintingWorkbench from './workbenches/InpaintingWorkbench.vue'
import MultimodalGroundingWorkbench from './workbenches/MultimodalGroundingWorkbench.vue'
import ObbDetectionWorkbench from './workbenches/ObbDetectionWorkbench.vue'
import ObjectDetectionWorkbench from './workbenches/ObjectDetectionWorkbench.vue'
import PlateDetectionWorkbench from './workbenches/PlateDetectionWorkbench.vue'
import PlatePoseWorkbench from './workbenches/PlatePoseWorkbench.vue'
import SegmentationWorkbench from './workbenches/SegmentationWorkbench.vue'
import SpeechAsrWorkbench from './workbenches/SpeechAsrWorkbench.vue'
import SpeechTtsWorkbench from './workbenches/SpeechTtsWorkbench.vue'
import SquatCountingWorkbench from './workbenches/SquatCountingWorkbench.vue'
import TalkingHeadWorkbench from './workbenches/TalkingHeadWorkbench.vue'
import TextNlpWorkbench from './workbenches/TextNlpWorkbench.vue'
import VehicleReidWorkbench from './workbenches/VehicleReidWorkbench.vue'
import {
  buildScenarioApiDocumentation,
  isLatestScenarioRequest,
  mergeSelectedScenario,
  pickScenarioModel,
  resolveFixedGroupKey,
  resolveQueryModelKey,
  resolveWorkbench,
} from './scenarioState'
import './scenarios.css'

const props = defineProps({
  groupKey: {
    type: String,
    default: '',
  },
})

const route = useRoute()
const router = useRouter()
const loading = ref(true)
const group = ref(null)
const selectedModelKey = ref('')
const loadError = ref('')
const notFound = ref(false)
const copied = ref(false)
const apiPanelOpen = ref(false)
const lastCompletedKey = ref('')
let requestSequence = 0
let syncingQuery = false

const fixedGroupKey = computed(() => resolveFixedGroupKey(route) || props.groupKey || null)
const queryModelKey = computed(() => resolveQueryModelKey(route))
const modelOptions = computed(() => (Array.isArray(group.value?.models) ? group.value.models : []))
const groupName = computed(() => group.value?.name || '')
const scenario = computed(() => mergeSelectedScenario(group.value, selectedModelKey.value))
const workbench = computed(() => resolveWorkbench(scenario.value?.workbenchType))
const workbenchComponent = computed(() => ({
  segmentation: SegmentationWorkbench,
  vehicle_reid: VehicleReidWorkbench,
  person_reid: VehicleReidWorkbench,
  plate_detection: PlateDetectionWorkbench,
  obb_detection: ObbDetectionWorkbench,
  plate_pose: PlatePoseWorkbench,
  face_recognition: FaceRecognitionWorkbench,
  object_detection: ObjectDetectionWorkbench,
  instance_segmentation: ObjectDetectionWorkbench,
  document_ocr: ObjectDetectionWorkbench,
  image_inpainting: InpaintingWorkbench,
  image_classification: ClassificationWorkbench,
  multimodal_grounding: MultimodalGroundingWorkbench,
  industrial_diagnosis: MultimodalGroundingWorkbench,
  body_pose: BodyPoseWorkbench,
  squat_counting: SquatCountingWorkbench,
  hand_pose: BodyPoseWorkbench,
  text_nlp: TextNlpWorkbench,
  speech_asr: SpeechAsrWorkbench,
  speech_tts: SpeechTtsWorkbench,
  talking_head: TalkingHeadWorkbench,
})[workbench.value] || null)

const ABILITY_LABELS = {
  segmentation: '交互分割',
  vehicle_reid: '车辆 ReID',
  person_reid: '行人 ReID',
  plate_detection: '车牌检测',
  obb_detection: 'OBB 检测',
  plate_pose: '车牌四点',
  face_recognition: '人脸识别',
  object_detection: '目标检测',
  instance_segmentation: '实例分割',
  document_ocr: '文档 OCR',
  image_inpainting: '图像修复',
  image_classification: '图像分类',
  multimodal_grounding: '多模态定位',
  industrial_diagnosis: '工业诊断',
  body_pose: '人体姿态',
  squat_counting: '健身蹲起计数',
  hand_pose: '手部姿态',
  text_nlp: '文本 NLP',
  speech_asr: '语音识别',
  speech_tts: '语音合成',
  talking_head: '数字人',
}

const abilityLabel = computed(() => ABILITY_LABELS[workbench.value] || '未知能力')
const apiReady = computed(() => Boolean(scenario.value?.apiReady ?? scenario.value?.ready))

const readinessStages = computed(() => [
  { key: 'registered', label: '模型登记', detail: scenario.value?.configured ? '登记完成' : '尚未登记', value: Boolean(scenario.value?.configured) },
  { key: 'weights', label: '权重资产', detail: scenario.value?.weightsPresent ? '文件可用' : '等待准备', value: Boolean(scenario.value?.weightsPresent) },
  { key: 'runtime', label: '运行环境', detail: scenario.value?.runtimeAvailable ? '依赖可用' : '依赖缺失', value: Boolean(scenario.value?.runtimeAvailable) },
  { key: 'api', label: '推理 API', detail: apiReady.value ? '允许执行' : '暂不可执行', value: apiReady.value },
])

const readinessReason = computed(() => {
  if (scenario.value?.reason) return scenario.value.reason
  if (!scenario.value?.configured) return '模型尚未在系统中登记'
  if (!scenario.value?.enabled) return '模型已停用'
  if (!scenario.value?.weightsPresent) return '模型权重尚未准备'
  if (!scenario.value?.runtimeAvailable) return '模型运行库尚不可用'
  return '推理 API 尚未开放'
})

const preparationSteps = computed(() => {
  const steps = []
  if (!scenario.value?.configured) steps.push('在模型管理中登记与当前所选模型一致的模型 key。')
  if (scenario.value?.configured && !scenario.value?.enabled) steps.push('在模型管理中启用该模型。')
  if (!scenario.value?.weightsPresent) steps.push('由管理员配置已验证的本地权重资产；页面不会自动下载。')
  if (!scenario.value?.runtimeAvailable) steps.push('安装并验证该模型适配器所需的运行库。')
  steps.push('重新进入页面核对四级状态，全部通过后再运行推理。')
  return steps
})

const inputLimit = computed(() => {
  const formats = scenario.value?.input?.formats?.map((item) => item.replace('.', '').toUpperCase()).join(' / ') || '图片'
  const size = scenario.value?.input?.maxSizeMb
  const pixels = scenario.value?.input?.maxPixels
  const prompts = scenario.value?.input?.maxPrompts
  const gallery = scenario.value?.input?.maxGalleryImages
  return `${formats}${size ? ` · 单图不超过 ${size} MB` : ''}`
    + `${pixels ? ` · 最多 ${pixels.toLocaleString()} 像素` : ''}`
    + `${prompts ? ` · 最多 ${prompts} 个提示` : ''}`
    + `${gallery ? ` · gallery 最多 ${gallery} 张` : ''}`
})

const apiDocumentation = computed(() => scenario.value
  ? buildScenarioApiDocumentation(scenario.value, {
    origin: typeof window === 'undefined' ? '' : window.location.origin,
  })
  : { curl: '', fields: [], response: {} })
const apiFields = computed(() => apiDocumentation.value.fields)
const curlExample = computed(() => apiDocumentation.value.curl)
const responseExample = computed(() => JSON.stringify(apiDocumentation.value.response, null, 2))

function modelReady(model) {
  return Boolean(model?.apiReady ?? model?.ready)
}

async function copyCurl() {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(curlExample.value)
    } else {
      const textarea = document.createElement('textarea')
      textarea.value = curlExample.value
      textarea.setAttribute('readonly', '')
      textarea.style.position = 'fixed'
      textarea.style.opacity = '0'
      document.body.appendChild(textarea)
      textarea.select()
      document.execCommand('copy')
      textarea.remove()
    }
    copied.value = true
    window.setTimeout(() => { copied.value = false }, 1600)
  } catch {
    copied.value = false
  }
}

function onWorkbenchCompleted(result) {
  lastCompletedKey.value = result?.modelKey || selectedModelKey.value || ''
}

function applySelectedModel(modelKey, { syncQuery = true } = {}) {
  const picked = pickScenarioModel(group.value, modelKey)
  const nextKey = picked?.modelKey || ''
  selectedModelKey.value = nextKey
  if (!syncQuery || !nextKey || !fixedGroupKey.value) return
  const currentQuery = resolveQueryModelKey(route)
  if (currentQuery === nextKey) return
  syncingQuery = true
  router.replace({
    path: route.path,
    query: { ...route.query, model: nextKey },
  }).finally(() => {
    syncingQuery = false
  })
}

function onModelChange(event) {
  const nextKey = event?.target?.value
  if (!nextKey || nextKey === selectedModelKey.value) return
  lastCompletedKey.value = ''
  apiPanelOpen.value = false
  applySelectedModel(nextKey)
}

async function loadScenario() {
  const requestedKey = fixedGroupKey.value
  const sequence = ++requestSequence
  const isCurrent = () => isLatestScenarioRequest(
    sequence,
    requestSequence,
    requestedKey,
    fixedGroupKey.value,
  )
  loading.value = true
  lastCompletedKey.value = ''
  apiPanelOpen.value = false
  loadError.value = ''
  notFound.value = false
  group.value = null
  selectedModelKey.value = ''
  if (!requestedKey) {
    notFound.value = true
    loading.value = false
    return
  }
  try {
    const params = {}
    if (queryModelKey.value) params.model = queryModelKey.value
    const response = await scenarioApi.get(requestedKey, params)
    if (!isCurrent()) return
    group.value = response.data
    applySelectedModel(
      queryModelKey.value || response.data?.selectedModelKey || response.data?.defaultModelKey,
      { syncQuery: true },
    )
  } catch (error) {
    if (!isCurrent()) return
    if (error?.response?.status === 404) notFound.value = true
    else loadError.value = error?.response?.data?.message || error?.message || '请检查网络连接或访问权限。'
  } finally {
    if (isCurrent()) loading.value = false
  }
}

watch(fixedGroupKey, loadScenario, { immediate: true })

watch(queryModelKey, (nextKey) => {
  if (syncingQuery || loading.value || !group.value || !nextKey) return
  if (nextKey === selectedModelKey.value) return
  if (!pickScenarioModel(group.value, nextKey)) return
  lastCompletedKey.value = ''
  apiPanelOpen.value = false
  applySelectedModel(nextKey, { syncQuery: false })
})
</script>
