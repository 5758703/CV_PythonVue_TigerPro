<template>
  <main class="scenario-page scenario-overview" aria-labelledby="scenario-overview-title">
    <section class="scenario-hero">
      <div>
        <p class="scenario-kicker">MODEL APPLICATIONS · PHASE 01 — 10</p>
        <h1 id="scenario-overview-title">生产模型场景</h1>
        <p class="scenario-hero__copy">
          三十九个场景入口，覆盖九十个生产模型，涵盖视觉检测、姿态、分割、ReID、OCR、文本 NLP、语音与数字人等能力。
          就绪状态来自当前运行环境，未就绪场景仍可进入查看准备要求。
        </p>
      </div>
      <div class="scenario-progress" aria-label="全阶段建设进度 39 场景 / 90 模型">
        <div class="scenario-progress__value"><strong>{{ groupCount }}</strong><span>/ 39</span></div>
        <div class="scenario-progress__label">{{ groupCount }} 场景 · {{ modelCount }} 模型</div>
        <div class="scenario-progress__track" aria-hidden="true">
          <span :style="{ width: `${phaseProgress}%` }"></span>
        </div>
      </div>
    </section>

    <section class="scenario-catalog" aria-label="能力目录与筛选">
      <header class="scenario-catalog__header">
        <div>
          <p class="scenario-kicker">CAPABILITY MAP</p>
          <h2>能力目录</h2>
        </div>
        <p class="scenario-catalog__hint">点击能力可筛选下方场景列表</p>
      </header>

      <div class="scenario-distribution" role="list">
        <button
          v-for="item in abilityDistribution"
          :key="item.key"
          type="button"
          class="scenario-distribution__item"
          :class="{
            'is-active': abilityFilter === item.key,
            'is-empty': item.count === 0,
          }"
          role="listitem"
          :aria-pressed="abilityFilter === item.key"
          :aria-label="`${item.label}，${item.count} 个场景`"
          @click="toggleAbility(item.key)"
        >
          <span class="scenario-distribution__icon" aria-hidden="true">
            <el-icon :size="18"><component :is="item.icon" /></el-icon>
          </span>
          <span class="scenario-distribution__copy">
            <span class="scenario-distribution__label">{{ item.label }}</span>
            <small>{{ item.count }} 个场景</small>
          </span>
          <strong>{{ item.count }}</strong>
        </button>
      </div>

      <section class="scenario-toolbar" aria-label="场景筛选">
        <label class="scenario-field scenario-field--search">
          <span><el-icon :size="13"><Search /></el-icon> 搜索</span>
          <span class="scenario-field__control">
            <el-icon class="scenario-field__lead" :size="16"><Search /></el-icon>
            <input
              v-model.trim="search"
              type="search"
              placeholder="按序号、名称、项目、场景或模型 key"
              autocomplete="off"
            >
          </span>
        </label>
        <label class="scenario-field">
          <span><el-icon :size="13"><Grid /></el-icon> 能力</span>
          <span class="scenario-field__control">
            <el-icon class="scenario-field__lead" :size="16"><Grid /></el-icon>
            <select v-model="abilityFilter">
              <option value="all">全部能力</option>
              <option v-for="item in abilityDistribution" :key="item.key" :value="item.key">
                {{ item.label }}（{{ item.count }}）
              </option>
            </select>
          </span>
        </label>
        <label class="scenario-field">
          <span><el-icon :size="13"><CircleCheck /></el-icon> 就绪状态</span>
          <span class="scenario-field__control">
            <el-icon class="scenario-field__lead" :size="16"><CircleCheck /></el-icon>
            <select v-model="statusFilter">
              <option value="all">全部状态</option>
              <option value="ready">可运行</option>
              <option value="unready">待准备</option>
              <option value="unregistered">未登记模型</option>
              <option value="weights">缺少权重</option>
              <option value="runtime">缺少运行库</option>
            </select>
          </span>
        </label>
        <button class="scenario-button scenario-button--ghost" type="button" @click="resetFilters">
          <el-icon :size="15"><Refresh /></el-icon>
          重置筛选
        </button>
      </section>
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
          <h2>模型场景</h2>
        </div>
        <span>显示 {{ filteredScenarios.length }} / {{ scenarios.length }}</span>
      </div>

      <section v-if="filteredScenarios.length" class="scenario-grid" aria-label="场景列表">
        <article v-for="scenario in filteredScenarios" :key="scenario.groupKey" class="scenario-card">
          <div class="scenario-card__header">
            <span class="scenario-card__order">{{ String(scenario.order).padStart(2, '0') }}</span>
            <div class="scenario-card__badges">
              <span class="scenario-pill scenario-pill--phase">阶段 {{ scenario.phase || 1 }}</span>
              <span class="scenario-pill scenario-pill--models">{{ scenario.modelCount || scenario.models?.length || 0 }} 个模型</span>
              <span :class="['scenario-pill', scenarioApiReady(scenario) ? 'is-ready' : 'is-pending']">
                {{ scenarioApiReady(scenario) ? '可运行' : '待准备' }}
              </span>
            </div>
          </div>
          <p class="scenario-card__ability">{{ abilityLabel(scenario.workbenchType) }}</p>
          <h3>{{ scenario.name }}</h3>
          <p class="scenario-card__project">{{ scenario.project }}</p>
          <p class="scenario-card__description">{{ scenario.description }}</p>

          <dl class="scenario-card__facts">
            <div>
              <dt>场景 KEY</dt>
              <dd><code>{{ scenario.groupKey }}</code></dd>
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

          <RouterLink class="scenario-card__link" :to="scenarioRoute(scenario)">
            {{ scenarioApiReady(scenario) ? '进入工作台' : '查看准备步骤' }}
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
import {
  Aim,
  Avatar,
  ChatLineSquare,
  CircleCheck,
  CollectionTag,
  Crop,
  Document,
  FullScreen,
  Grid,
  Headset,
  MagicStick,
  Microphone,
  Pointer,
  Postcard,
  Refresh,
  Search,
  Tools,
  User,
  UserFilled,
  Van,
  VideoCamera,
  View,
} from '@element-plus/icons-vue'
import { computed, onMounted, ref } from 'vue'

import { scenarioApi } from '../../../api/modelScenarios'
import { SCENARIO_GROUP_ROUTE_KEYS, SCENARIO_MODEL_COUNT } from './scenarioState'
import './scenarios.css'

const ABILITIES = [
  { key: 'segmentation', label: '交互分割', icon: Crop },
  { key: 'vehicle_reid', label: '车辆 ReID', icon: Van },
  { key: 'person_reid', label: '行人 ReID', icon: User },
  { key: 'plate_detection', label: '车牌检测', icon: Postcard },
  { key: 'obb_detection', label: 'OBB 检测', icon: FullScreen },
  { key: 'plate_pose', label: '车牌四点', icon: Aim },
  { key: 'face_recognition', label: '人脸识别', icon: Avatar },
  { key: 'object_detection', label: '目标检测', icon: View },
  { key: 'instance_segmentation', label: '实例分割', icon: Grid },
  { key: 'document_ocr', label: '文档 OCR', icon: Document },
  { key: 'image_inpainting', label: '图像修复', icon: MagicStick },
  { key: 'image_classification', label: '图像分类', icon: CollectionTag },
  { key: 'multimodal_grounding', label: '多模态定位', icon: Aim },
  { key: 'industrial_diagnosis', label: '工业诊断', icon: Tools },
  { key: 'body_pose', label: '人体姿态', icon: UserFilled },
  { key: 'hand_pose', label: '手部姿态', icon: Pointer },
  { key: 'text_nlp', label: '文本 NLP', icon: ChatLineSquare },
  { key: 'speech_asr', label: '语音识别', icon: Microphone },
  { key: 'speech_tts', label: '语音合成', icon: Headset },
  { key: 'talking_head', label: '数字人', icon: VideoCamera },
]

const scenarios = ref([])
const loading = ref(true)
const loadError = ref('')
const search = ref('')
const abilityFilter = ref('all')
const statusFilter = ref('all')

const groupCount = SCENARIO_GROUP_ROUTE_KEYS.length
const modelCount = SCENARIO_MODEL_COUNT
const phaseProgress = Math.round((groupCount / 39) * 100)

const abilityDistribution = computed(() => ABILITIES.map((ability) => ({
  ...ability,
  count: scenarios.value.filter((scenario) => scenario.workbenchType === ability.key).length,
})))

const filteredScenarios = computed(() => {
  const keyword = search.value.toLocaleLowerCase('zh-CN')
  return scenarios.value.filter((scenario) => {
    const modelKeys = (scenario.models || []).map((item) => item.modelKey)
    const matchesSearch = !keyword || [
      scenario.order,
      scenario.name,
      scenario.project,
      scenario.groupKey,
      ...modelKeys,
    ].some((value) => String(value ?? '').toLocaleLowerCase('zh-CN').includes(keyword))
    const matchesAbility = abilityFilter.value === 'all' || scenario.workbenchType === abilityFilter.value
    const matchesStatus = statusFilter.value === 'all'
      || (statusFilter.value === 'ready' && scenarioApiReady(scenario))
      || (statusFilter.value === 'unready' && !scenarioApiReady(scenario))
      || (statusFilter.value === 'unregistered' && !scenario.configured)
      || (statusFilter.value === 'weights' && scenario.configured && !scenario.weightsPresent)
      || (statusFilter.value === 'runtime' && scenario.weightsPresent && !scenario.runtimeAvailable)
    return matchesSearch && matchesAbility && matchesStatus
  })
})

function abilityLabel(type) {
  return ABILITIES.find((item) => item.key === type)?.label || '未知能力'
}

function scenarioApiReady(scenario) {
  return Boolean(scenario?.anyReady ?? scenario?.apiReady ?? scenario?.ready)
}

function scenarioRoute(scenario) {
  return scenario.route || `/ai/scenarios/${scenario.groupKey}`
}

function readinessStages(scenario) {
  return [
    { key: 'registered', label: '模型登记', value: Boolean(scenario.configured) },
    { key: 'weights', label: '权重', value: Boolean(scenario.weightsPresent) },
    { key: 'runtime', label: '运行库', value: Boolean(scenario.runtimeAvailable) },
    { key: 'api', label: 'API', value: scenarioApiReady(scenario) },
  ]
}

function inputSummary(scenario) {
  const formats = scenario.input?.formats?.map((item) => item.replace('.', '').toUpperCase()).join(' / ')
    || scenario.models?.[0]?.input?.formats?.map((item) => item.replace('.', '').toUpperCase()).join(' / ')
  if (scenario.workbenchType === 'vehicle_reid' || scenario.workbenchType === 'person_reid') {
    return `查询图 + 候选图 · ${formats || '图片'}`
  }
  if (scenario.workbenchType === 'segmentation') return `图片 + 点/框提示 · ${formats || '图片'}`
  if (scenario.workbenchType === 'face_recognition') return `单张人脸图 · ${formats || 'JPG / PNG'}`
  if (scenario.workbenchType === 'image_inpainting') return `原图 + 遮罩 · ${formats || 'JPG / PNG'}`
  if (scenario.workbenchType === 'multimodal_grounding' || scenario.workbenchType === 'industrial_diagnosis') {
    return `图片 + 提示词 · ${formats || 'JPG / PNG'}`
  }
  if (scenario.workbenchType === 'text_nlp') return '文本输入'
  if (scenario.workbenchType === 'speech_asr') return `音频 · ${formats || 'WAV / MP3'}`
  if (scenario.workbenchType === 'speech_tts') return '文本 → 音频'
  if (scenario.workbenchType === 'talking_head') return '人物图 + 驱动音频'
  return `单张图片 · ${formats || 'JPG / PNG'}`
}

function toggleAbility(key) {
  abilityFilter.value = abilityFilter.value === key ? 'all' : key
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
    const response = await scenarioApi.list()
    const items = Array.isArray(response.data) ? response.data : []
    scenarios.value = items
      .filter((item) => SCENARIO_GROUP_ROUTE_KEYS.includes(item.groupKey))
      .sort((left, right) => left.order - right.order)
  } catch (error) {
    loadError.value = error?.response?.data?.message || error?.message || '请检查网络连接或访问权限。'
  } finally {
    loading.value = false
  }
}

onMounted(loadScenarios)
</script>
