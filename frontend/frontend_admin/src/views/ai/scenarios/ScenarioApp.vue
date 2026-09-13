<template>
  <main class="scenario-page scenario-detail" aria-labelledby="scenario-title">
    <RouterLink class="scenario-back" to="/ai/scenarios"><span aria-hidden="true">←</span> 返回场景总览</RouterLink>

    <section v-if="loading" class="scenario-state" aria-live="polite">
      <span class="scenario-loader" aria-hidden="true"></span>
      <h1 id="scenario-title">正在装载场景</h1>
      <p>读取固定模型身份与当前运行就绪状态。</p>
    </section>

    <section v-else-if="notFound" class="scenario-state scenario-state--error" role="alert">
      <span class="scenario-state__code">SCENARIO 404</span>
      <h1 id="scenario-title">场景不存在</h1>
      <p>该固定路由没有对应的场景登记，模型 query 不会改变当前页面身份。</p>
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
          <h1 id="scenario-title">{{ scenario.name }}</h1>
          <p>{{ scenario.description }}</p>
          <code>{{ fixedModelKey }}</code>
        </div>
        <div :class="['scenario-health', scenario.ready ? 'is-ready' : 'is-pending']">
          <span aria-hidden="true"></span>
          <div>
            <strong>{{ scenario.ready ? '生产可运行' : '等待环境准备' }}</strong>
            <small>{{ scenario.ready ? '模型、权重、运行库与 API 均已就绪' : readinessReason }}</small>
          </div>
        </div>
      </header>

      <ol class="scenario-status-strip" aria-label="四级就绪状态">
        <li v-for="(stage, index) in readinessStages" :key="stage.key" :class="{ 'is-complete': stage.value }">
          <span class="scenario-status-strip__index">{{ index + 1 }}</span>
          <span><strong>{{ stage.label }}</strong><small>{{ stage.detail }}</small></span>
        </li>
      </ol>

      <aside v-if="!scenario.ready" class="scenario-readiness-note" aria-labelledby="preparation-title">
        <div>
          <p class="scenario-kicker">PREPARATION REQUIRED</p>
          <h2 id="preparation-title">该场景尚未就绪</h2>
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
          <span class="scenario-workbench__mode">固定模型 · {{ fixedModelKey }}</span>
        </div>
        <slot
          name="workbench"
          :scenario="scenario"
          :workbench="workbench"
          :ready="scenario.ready"
        >
          <div class="scenario-workbench__fallback">
            <div class="scenario-canvas-placeholder" aria-hidden="true">
              <span></span><span></span><span></span>
              <b>VISION CANVAS</b>
            </div>
            <div>
              <span class="scenario-state__code">{{ workbench ? workbench.toUpperCase() : 'UNSUPPORTED' }}</span>
              <h3>{{ workbench ? '专用工作台正在接入' : '暂不支持该工作台类型' }}</h3>
              <p>场景外壳已锁定模型身份；工作台插槽可安全接入输入、运行与结构化结果区域。</p>
              <button class="scenario-button" type="button" disabled>运行推理</button>
            </div>
          </div>
        </slot>
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

      <section class="scenario-api" aria-labelledby="api-title">
        <div class="scenario-section-heading">
          <div>
            <p class="scenario-kicker">OPEN API CONTRACT</p>
            <h2 id="api-title">API 调用</h2>
          </div>
          <button class="scenario-button scenario-button--ghost" type="button" @click="copyCurl">
            {{ copied ? '已复制' : '复制 curl' }}
          </button>
        </div>
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
      </section>
    </template>
  </main>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import { scenarioApi } from '../../../api/modelScenarios'
import {
  buildScenarioApiDocumentation,
  isLatestScenarioRequest,
  resolveFixedModelKey,
  resolveWorkbench,
} from './scenarioState'
import './scenarios.css'

const props = defineProps({
  modelKey: {
    type: String,
    default: '',
  },
})

const route = useRoute()
const loading = ref(true)
const scenario = ref(null)
const loadError = ref('')
const notFound = ref(false)
const copied = ref(false)
let requestSequence = 0

const fixedModelKey = computed(() => resolveFixedModelKey(route) || props.modelKey || null)
const workbench = computed(() => resolveWorkbench(scenario.value?.workbenchType))

const ABILITY_LABELS = {
  segmentation: '交互分割',
  vehicle_reid: '车辆 ReID',
  plate_detection: '车牌检测',
  obb_detection: 'OBB 检测',
}

const abilityLabel = computed(() => ABILITY_LABELS[workbench.value] || '未知能力')

const readinessStages = computed(() => [
  { key: 'registered', label: '模型登记', detail: scenario.value?.configured ? '登记完成' : '尚未登记', value: Boolean(scenario.value?.configured) },
  { key: 'weights', label: '权重资产', detail: scenario.value?.weightsPresent ? '文件可用' : '等待准备', value: Boolean(scenario.value?.weightsPresent) },
  { key: 'runtime', label: '运行环境', detail: scenario.value?.runtimeAvailable ? '依赖可用' : '依赖缺失', value: Boolean(scenario.value?.runtimeAvailable) },
  { key: 'api', label: '推理 API', detail: scenario.value?.ready ? '允许执行' : '暂不可执行', value: Boolean(scenario.value?.ready) },
])

const readinessReason = computed(() => {
  if (!scenario.value?.configured) return '模型尚未在系统中登记'
  if (!scenario.value?.enabled) return '模型已停用'
  if (!scenario.value?.weightsPresent) return '模型权重尚未准备'
  if (!scenario.value?.runtimeAvailable) return '模型运行库尚不可用'
  return scenario.value?.reason || '推理 API 尚未开放'
})

const preparationSteps = computed(() => {
  const steps = []
  if (!scenario.value?.configured) steps.push('在模型管理中登记与当前路由一致的模型 key。')
  if (scenario.value?.configured && !scenario.value?.enabled) steps.push('在模型管理中启用该模型。')
  if (!scenario.value?.weightsPresent) steps.push('由管理员配置已验证的本地权重资产；页面不会自动下载。')
  if (!scenario.value?.runtimeAvailable) steps.push('安装并验证该模型适配器所需的运行库。')
  steps.push('重新进入页面核对四级状态，全部通过后再运行推理。')
  return steps
})

const inputLimit = computed(() => {
  const formats = scenario.value?.input?.formats?.map((item) => item.replace('.', '').toUpperCase()).join(' / ') || '图片'
  const size = scenario.value?.input?.maxSizeMb
  return `${formats}${size ? ` · 单次不超过 ${size} MB` : ''}`
})

const apiDocumentation = computed(() => scenario.value
  ? buildScenarioApiDocumentation(scenario.value, {
    origin: typeof window === 'undefined' ? '' : window.location.origin,
  })
  : { curl: '', fields: [], response: {} })
const apiFields = computed(() => apiDocumentation.value.fields)
const curlExample = computed(() => apiDocumentation.value.curl)
const responseExample = computed(() => JSON.stringify(apiDocumentation.value.response, null, 2))

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

async function loadScenario() {
  const requestedKey = fixedModelKey.value
  const sequence = ++requestSequence
  const isCurrent = () => isLatestScenarioRequest(
    sequence,
    requestSequence,
    requestedKey,
    fixedModelKey.value,
  )
  loading.value = true
  loadError.value = ''
  notFound.value = false
  scenario.value = null
  if (!requestedKey) {
    notFound.value = true
    loading.value = false
    return
  }
  try {
    const response = await scenarioApi.get(requestedKey)
    if (!isCurrent()) return
    scenario.value = response.data
  } catch (error) {
    if (!isCurrent()) return
    if (error?.response?.status === 404) notFound.value = true
    else loadError.value = error?.response?.data?.message || error?.message || '请检查网络连接或访问权限。'
  } finally {
    if (isCurrent()) loading.value = false
  }
}

watch(fixedModelKey, loadScenario, { immediate: true })
</script>
