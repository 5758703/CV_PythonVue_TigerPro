<template>
  <main class="scenario-page scenario-overview" aria-labelledby="scenario-overview-title">
    <section class="scenario-hero">
      <div>
        <p class="scenario-kicker">MODEL APPLICATIONS · PHASE 01</p>
        <h1 id="scenario-overview-title">生产模型场景</h1>
        <p class="scenario-hero__copy">
          九个独立应用入口，覆盖交互分割、车辆重识别、车牌检测与旋转框检测。
          就绪状态来自当前运行环境，未就绪场景仍可进入查看准备要求。
        </p>
      </div>
      <div class="scenario-progress" aria-label="第一阶段建设进度 9 / 90">
        <div class="scenario-progress__value"><strong>{{ phaseCount }}</strong><span>/ 90</span></div>
        <div class="scenario-progress__label">第一阶段建设进度</div>
        <div class="scenario-progress__track" aria-hidden="true">
          <span :style="{ width: `${phaseProgress}%` }"></span>
        </div>
      </div>
    </section>

    <section class="scenario-distribution" aria-label="能力分布">
      <article v-for="item in abilityDistribution" :key="item.key" class="scenario-distribution__item">
        <span>{{ item.label }}</span>
        <strong>{{ item.count }}</strong>
        <small>个场景</small>
      </article>
    </section>

    <section class="scenario-toolbar" aria-label="场景筛选">
      <label class="scenario-field scenario-field--search">
        <span>搜索</span>
        <input
          v-model.trim="search"
          type="search"
          placeholder="按序号、名称、项目或模型 key"
          autocomplete="off"
        >
      </label>
      <label class="scenario-field">
        <span>能力</span>
        <select v-model="abilityFilter">
          <option value="all">全部能力</option>
          <option v-for="item in abilityDistribution" :key="item.key" :value="item.key">
            {{ item.label }}（{{ item.count }}）
          </option>
        </select>
      </label>
      <label class="scenario-field">
        <span>就绪状态</span>
        <select v-model="statusFilter">
          <option value="all">全部状态</option>
          <option value="ready">可运行</option>
          <option value="unready">待准备</option>
          <option value="unregistered">未登记模型</option>
          <option value="weights">缺少权重</option>
          <option value="runtime">缺少运行库</option>
        </select>
      </label>
      <button class="scenario-button scenario-button--ghost" type="button" @click="resetFilters">
        重置筛选
      </button>
    </section>

    <section v-if="loading" class="scenario-state" aria-live="polite">
      <span class="scenario-loader" aria-hidden="true"></span>
      <h2>正在读取场景状态</h2>
      <p>正在核对模型登记、权重、运行库与 API 四级状态。</p>
    </section>

    <section v-else-if="loadError" class="scenario-state scenario-state--error" role="alert">
      <span class="scenario-state__code">CONNECTION FAILED</span>
      <h2>场景目录暂时无法读取</h2>
      <p>{{ loadError }}</p>
      <button class="scenario-button" type="button" @click="loadScenarios">重新加载</button>
    </section>

    <template v-else>
      <div class="scenario-list-heading">
        <div>
          <p class="scenario-kicker">APPLICATION ROUTES</p>
          <h2>第一阶段场景</h2>
        </div>
        <span>显示 {{ filteredScenarios.length }} / {{ scenarios.length }}</span>
      </div>

      <section v-if="filteredScenarios.length" class="scenario-grid" aria-label="场景列表">
        <article v-for="scenario in filteredScenarios" :key="scenario.modelKey" class="scenario-card">
          <div class="scenario-card__header">
            <span class="scenario-card__order">{{ String(scenario.order).padStart(2, '0') }}</span>
            <span :class="['scenario-pill', scenario.ready ? 'is-ready' : 'is-pending']">
              {{ scenario.ready ? '可运行' : '待准备' }}
            </span>
          </div>
          <p class="scenario-card__ability">{{ abilityLabel(scenario.workbenchType) }}</p>
          <h3>{{ scenario.name }}</h3>
          <p class="scenario-card__project">{{ scenario.project }}</p>
          <p class="scenario-card__description">{{ scenario.description }}</p>

          <dl class="scenario-card__facts">
            <div>
              <dt>模型 KEY</dt>
              <dd><code>{{ scenario.modelKey }}</code></dd>
            </div>
            <div>
              <dt>输入</dt>
              <dd>{{ inputSummary(scenario) }}</dd>
            </div>
            <div>
              <dt>核心产出</dt>
              <dd>{{ scenario.outputs }}</dd>
            </div>
          </dl>

          <ol class="scenario-readiness" aria-label="四级就绪状态">
            <li v-for="stage in readinessStages(scenario)" :key="stage.key" :class="{ 'is-complete': stage.value }">
              <span aria-hidden="true"></span>{{ stage.label }}
            </li>
          </ol>

          <RouterLink class="scenario-card__link" :to="scenario.route">
            {{ scenario.ready ? '进入工作台' : '查看准备步骤' }}
            <span aria-hidden="true">→</span>
          </RouterLink>
        </article>
      </section>

      <section v-else class="scenario-state">
        <span class="scenario-state__code">NO MATCH</span>
        <h2>没有符合条件的场景</h2>
        <p>尝试更换关键词或重置筛选条件。</p>
        <button class="scenario-button scenario-button--ghost" type="button" @click="resetFilters">清除筛选</button>
      </section>
    </template>
  </main>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'

import { scenarioApi } from '../../../api/modelScenarios'
import { PHASE_ONE_ROUTE_KEYS } from './scenarioState'
import './scenarios.css'

const ABILITIES = [
  { key: 'segmentation', label: '交互分割' },
  { key: 'vehicle_reid', label: '车辆 ReID' },
  { key: 'plate_detection', label: '车牌检测' },
  { key: 'obb_detection', label: 'OBB 检测' },
]

const scenarios = ref([])
const loading = ref(true)
const loadError = ref('')
const search = ref('')
const abilityFilter = ref('all')
const statusFilter = ref('all')

const phaseCount = PHASE_ONE_ROUTE_KEYS.length
const phaseProgress = Math.round((phaseCount / 90) * 100)

const abilityDistribution = computed(() => ABILITIES.map((ability) => ({
  ...ability,
  count: scenarios.value.filter((scenario) => scenario.workbenchType === ability.key).length,
})))

const filteredScenarios = computed(() => {
  const keyword = search.value.toLocaleLowerCase('zh-CN')
  return scenarios.value.filter((scenario) => {
    const matchesSearch = !keyword || [
      scenario.order,
      scenario.name,
      scenario.project,
      scenario.modelKey,
    ].some((value) => String(value ?? '').toLocaleLowerCase('zh-CN').includes(keyword))
    const matchesAbility = abilityFilter.value === 'all' || scenario.workbenchType === abilityFilter.value
    const matchesStatus = statusFilter.value === 'all'
      || (statusFilter.value === 'ready' && scenario.ready)
      || (statusFilter.value === 'unready' && !scenario.ready)
      || (statusFilter.value === 'unregistered' && !scenario.configured)
      || (statusFilter.value === 'weights' && scenario.configured && !scenario.weightsPresent)
      || (statusFilter.value === 'runtime' && scenario.weightsPresent && !scenario.runtimeAvailable)
    return matchesSearch && matchesAbility && matchesStatus
  })
})

function abilityLabel(type) {
  return ABILITIES.find((item) => item.key === type)?.label || '未知能力'
}

function readinessStages(scenario) {
  return [
    { key: 'registered', label: '模型登记', value: Boolean(scenario.configured) },
    { key: 'weights', label: '权重', value: Boolean(scenario.weightsPresent) },
    { key: 'runtime', label: '运行库', value: Boolean(scenario.runtimeAvailable) },
    { key: 'api', label: 'API', value: Boolean(scenario.ready) },
  ]
}

function inputSummary(scenario) {
  const formats = scenario.input?.formats?.map((item) => item.replace('.', '').toUpperCase()).join(' / ')
  if (scenario.workbenchType === 'vehicle_reid') return `查询图 + 候选图 · ${formats || '图片'}`
  if (scenario.workbenchType === 'segmentation') return `图片 + 点/框提示 · ${formats || '图片'}`
  return `单张图片 · ${formats || 'JPG / PNG'}`
}

function resetFilters() {
  search.value = ''
  abilityFilter.value = 'all'
  statusFilter.value = 'all'
}

async function loadScenarios() {
  loading.value = true
  loadError.value = ''
  try {
    const response = await scenarioApi.list({ phase: 1 })
    const items = Array.isArray(response.data) ? response.data : []
    scenarios.value = items
      .filter((item) => PHASE_ONE_ROUTE_KEYS.includes(item.modelKey))
      .sort((left, right) => left.order - right.order)
  } catch (error) {
    loadError.value = error?.response?.data?.message || error?.message || '请检查网络连接或访问权限。'
  } finally {
    loading.value = false
  }
}

onMounted(loadScenarios)
</script>
