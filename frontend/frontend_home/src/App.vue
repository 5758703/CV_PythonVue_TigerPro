<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import {
  Activity, ArrowRight, Boxes, BrainCircuit, CheckCircle2, ChevronRight, CircleDot,
  Database, ExternalLink, FolderKanban, GitBranch, Hand, BookOpen, Mic, Play, ScanFace,
  ScanLine, ShieldCheck, Sparkles, Target, TrendingUp, Users, Workflow,
} from 'lucide-vue-next'

import { fetchHealth, fetchOpenApiHealth, fetchPortalSummary } from './api/portal'
import {
  GITHUB_URL,
  getAdminUrl,
  consoleEntryHref,
  goConsole,
  openApiDocsHref,
  scrollToId,
  isConsoleLoggedIn,
} from './config'

const scrolled = ref(false)
const SCROLL_THRESHOLD = 360
const backendOnline = ref(false)
const summaryLoaded = ref(false)
const jobsRunning = ref(0)
const openApiMeta = ref(null)
const consoleLoggedIn = ref(false)

function refreshAuth() {
  consoleLoggedIn.value = isConsoleLoggedIn()
}

const adminHostLabel = computed(() => getAdminUrl().replace(/^https?:\/\//, ''))

const links = computed(() => ({
  github: GITHUB_URL,
  console: consoleEntryHref('/index'),
  test: consoleEntryHref('/ai/image'),
  training: consoleEntryHref('/ai/training'),
  models: consoleEntryHref('/ai/model'),
  openapi: openApiDocsHref(),
  scenariosAll: consoleEntryHref('/index'),
}))

function onConsoleNav(event, path = '/index', query = {}) {
  event.preventDefault()
  refreshAuth()
  goConsole(path, query)
}

function scenarioHref(item) {
  return consoleEntryHref(item.path, item.query || {})
}

function onScenarioNav(event, item) {
  event.preventDefault()
  refreshAuth()
  goConsole(item.path, item.query || {})
}

const FALLBACK_STATS = {
  modelTotal: 107,
  readyCount: 106,
  datasetTotal: 6,
  jobTotal: 5,
  jobsRunning: 0,
  taskKinds: 14,
  categoryKinds: 30,
}

const summary = ref({ ...FALLBACK_STATS })

const FALLBACK_DISTRIBUTION = [
  { name: '目标检测', value: 43, color: '#2f7df6' },
  { name: '图像分类', value: 18, color: '#20b8a8' },
  { name: '文本与语音', value: 16, color: '#f59e42' },
  { name: '跟踪识别', value: 12, color: '#8b5cf6' },
  { name: '其他任务', value: 11, color: '#9aa8bd' },
]

const FALLBACK_ACTIVITY = [
  { name: '目标检测', value: 34, color: '#2f7df6' },
  { name: '图像分类', value: 18, color: '#20b8a8' },
  { name: '姿态估计', value: 15, color: '#f59e42' },
  { name: '人脸识别', value: 13, color: '#8b5cf6' },
  { name: '目标追踪', value: 11, color: '#e62138' },
  { name: '文本分类', value: 9, color: '#09aebe' },
]

const CHART_COLORS = ['#2f7df6', '#20b8a8', '#f59e42', '#8b5cf6', '#e62138', '#09aebe', '#9aa8bd', '#1677e8']

const distribution = ref([...FALLBACK_DISTRIBUTION])
const activity = ref([...FALLBACK_ACTIVITY])

const donutStyle = computed(() => {
  const items = distribution.value
  const total = items.reduce((s, i) => s + i.value, 0) || 1
  let acc = 0
  const parts = items.map((item) => {
    const start = (acc / total) * 100
    acc += item.value
    const end = (acc / total) * 100
    return `${item.color} ${start}% ${end}%`
  })
  return { background: `conic-gradient(${parts.join(',')})` }
})

const activityMax = computed(() => Math.max(...activity.value.map((i) => i.value), 1))

const stats = computed(() => {
  const s = summary.value
  return [
    { label: '模型总数', value: String(s.modelTotal), detail: `覆盖 ${s.taskKinds}+ 任务类型`, icon: Boxes, tone: 'blue' },
    { label: '已就绪', value: String(s.readyCount), detail: '可直接在线测试', icon: CheckCircle2, tone: 'green' },
    { label: '训练数据集', value: String(s.datasetTotal), detail: '训练闭环可用', icon: Database, tone: 'teal' },
    {
      label: '训练任务',
      value: String(s.jobTotal),
      detail: s.jobsRunning > 0 ? `${s.jobsRunning} 个正在运行` : '暂无运行中任务',
      icon: TrendingUp,
      tone: 'orange',
    },
    { label: '任务种类', value: String(s.taskKinds), detail: '视觉、文本与语音', icon: BrainCircuit, tone: 'blue' },
    { label: '模型分类', value: String(s.categoryKinds), detail: '结构清晰可检索', icon: FolderKanban, tone: 'teal' },
  ]
})

const steps = [
  ['新建数据集', '配置检测类别'],
  ['视频抽帧', '提取高质量样本'],
  ['数据标注', '在线框选与保存'],
  ['构建数据', '自动划分训练集'],
  ['训练任务', '监控曲线与 mAP'],
  ['部署检测', '注册并在线测试'],
]

const scenarios = [
  { title: '开放词汇检测', description: 'OmDet-Turbo：输入类别列表做零样本检测，与固定类 YOLO 并存。', tag: '开放词汇', tagTone: 'blue', icon: Sparkles, path: '/ai/image' },
  { title: '多模态定位', description: 'VLM-FO1：自然语言 / REC 细粒度定位，YOLO 候选 + FO1 筛选。', tag: '多模态', tagTone: 'pink', icon: BrainCircuit, path: '/ai/image' },
  { title: '语音转写 ASR', description: 'MOSS 多人说话人转写与时间戳，支持音视频与字幕导出。', tag: '语音识别', tagTone: 'red', icon: Mic, path: '/ai/asr' },
  { title: '跨镜重识别', description: '三档门控 + 证据落库 + 候选晋升，多路全局 ID 与监控墙叠加。', tag: '跨镜追踪', tagTone: 'blue', icon: Workflow, path: '/ai/mtmc' },
  { title: '跌倒检测', description: '姿态四指标判定，支持图片、视频与实时摄像头。', tag: '安全监测', tagTone: 'red', icon: ShieldCheck, path: '/ai/fall' },
  { title: '手势识别', description: '数字手势与中国手语识别，支持多视角输入。', tag: '姿态识别', tagTone: 'pink', icon: Hand, path: '/ai/handpose' },
  { title: '人员离岗检测', description: '多工位在岗判定，支持移动镜头运动补偿。', tag: '行为分析', tagTone: 'orange', icon: Users, path: '/ai/track', query: { scenario: 'absence' } },
  { title: '车辆追踪', description: '车牌 OCR、测速抓拍、运动轨迹与过车记录。', tag: '智慧交通', tagTone: 'blue', icon: ScanLine, path: '/ai/track', query: { scenario: 'vehicle' } },
  { title: '通用目标追踪', description: 'ByteTrack 多目标追踪与区域越线进出统计。', tag: '视觉追踪', tagTone: 'green', icon: Target, path: '/ai/track', query: { scenario: 'general' } },
  { title: '人脸识别', description: 'InsightFace / YuNet+SFace 底库与 1:N 实时识别。', tag: '身份识别', tagTone: 'cyan', icon: ScanFace, path: '/ai/face' },
]

const heroTags = [
  ['开放词汇', 'blue'],
  ['多模态定位', 'pink'],
  ['语音 ASR', 'red'],
  ['跨镜 MTMC', 'blue'],
]

const runItems = computed(() => {
  const running = jobsRunning.value
  return [
    { name: '平台后端服务', state: backendOnline.value ? '运行中' : '离线', progress: backendOnline.value ? '100%' : '0%' },
    { name: '模型资产库', state: summaryLoaded.value ? '已同步' : '演示数据', progress: summaryLoaded.value ? '100%' : '70%' },
    {
      name: '训练任务队列',
      state: running > 0 ? `${running} 个运行中` : '空闲',
      progress: running > 0 ? `${Math.min(100, 40 + running * 20)}%` : '100%',
    },
  ]
})

function updateStickyBar() {
  scrolled.value = window.scrollY > SCROLL_THRESHOLD
}

function applySummary(data) {
  summary.value = {
    modelTotal: data.modelTotal ?? FALLBACK_STATS.modelTotal,
    readyCount: data.readyCount ?? FALLBACK_STATS.readyCount,
    datasetTotal: data.datasetTotal ?? FALLBACK_STATS.datasetTotal,
    jobTotal: data.jobTotal ?? FALLBACK_STATS.jobTotal,
    jobsRunning: data.jobsRunning ?? 0,
    taskKinds: data.taskKinds ?? FALLBACK_STATS.taskKinds,
    categoryKinds: data.categoryKinds ?? FALLBACK_STATS.categoryKinds,
  }
  jobsRunning.value = data.jobsRunning ?? 0

  const dist = data.taskDistribution || []
  if (dist.length) {
    const total = dist.reduce((s, i) => s + i.value, 0) || 1
    distribution.value = dist.map((item, i) => ({
      name: item.name,
      value: Math.max(1, Math.round((item.value / total) * 100)),
      color: CHART_COLORS[i % CHART_COLORS.length],
      raw: item.value,
    }))
  }

  const rank = data.categoryRanking || []
  if (rank.length) {
    activity.value = rank.slice(0, 6).map((item, i) => ({
      name: item.name,
      value: item.value,
      color: CHART_COLORS[i % CHART_COLORS.length],
    }))
  }
}

async function loadPortalData() {
  try {
    backendOnline.value = await fetchHealth()
  } catch {
    backendOnline.value = false
  }

  try {
    const open = await fetchOpenApiHealth()
    openApiMeta.value = open
  } catch {
    openApiMeta.value = null
  }

  try {
    const data = await fetchPortalSummary()
    applySummary(data)
    summaryLoaded.value = true
  } catch {
    summaryLoaded.value = false
  }
}

let healthTimer

onMounted(() => {
  refreshAuth()
  updateStickyBar()
  window.addEventListener('scroll', updateStickyBar, { passive: true })
  window.addEventListener('focus', refreshAuth)
  document.addEventListener('visibilitychange', refreshAuth)
  loadPortalData()
  healthTimer = window.setInterval(() => {
    fetchHealth().then((ok) => { backendOnline.value = ok }).catch(() => { backendOnline.value = false })
  }, 30000)
})

onUnmounted(() => {
  window.removeEventListener('scroll', updateStickyBar)
  window.removeEventListener('focus', refreshAuth)
  document.removeEventListener('visibilitychange', refreshAuth)
  if (healthTimer) window.clearInterval(healthTimer)
})
</script>

<template>
  <main>
    <header class="sticky-bar" :class="{ visible: scrolled }" :aria-hidden="!scrolled">
      <div class="container sticky-inner">
        <div class="sticky-top">
          <div class="brand sticky-brand">
            <div class="cv-mark sticky-cv">CV</div>
            <div>
              <p class="sticky-title">Tiger AI 平台</p>
              <small>MODEL LAB</small>
            </div>
          </div>
          <p class="sticky-headline">让每一个 AI 模型，都能更快走向可用</p>
          <div class="sticky-actions">
            <a :href="links.console" class="button light sticky-cta" @click="onConsoleNav($event, '/index')">进入控制台</a>
            <a :href="links.github" target="_blank" rel="noopener noreferrer" class="github sticky-github">
              <GitBranch :size="17" /> GitHub
            </a>
          </div>
        </div>
        <div class="sticky-bottom">
          <div class="eyebrow sticky-eyebrow"><Sparkles :size="15" /> 一站式 AI 模型测试与学习工作台</div>
          <div class="tag-row sticky-tags">
            <span v-for="([tag, tone]) in heroTags" :key="`sticky-${tag}`" class="tag" :class="`tag-${tone}`">{{ tag }}</span>
            <span class="task-count">{{ summary.taskKinds }}+ 任务类型</span>
          </div>
        </div>
      </div>
    </header>

    <section class="hero">
      <div class="container hero-container">
        <header class="topbar">
          <div class="brand">
            <div class="cv-mark">CV</div>
            <div>
              <p>Tiger AI</p>
              <small>MODEL LAB</small>
            </div>
          </div>
          <nav class="top-nav" aria-label="门户导航">
            <a href="#scenarios">场景</a>
            <a href="#training" @click.prevent="scrollToId('training')">训练</a>
            <a :href="links.openapi" target="_blank" rel="noopener noreferrer">OpenAPI</a>
            <a :href="links.console" class="nav-console" @click="onConsoleNav($event, '/index')">
              {{ consoleLoggedIn ? '进入控制台' : '登录控制台' }}
              <ExternalLink :size="13" />
            </a>
            <a :href="links.github" target="_blank" rel="noopener noreferrer" class="github">
              <GitBranch :size="14" /> GitHub
            </a>
          </nav>
        </header>
        <div class="hero-grid">
          <div class="hero-copy">
            <div class="eyebrow"><Sparkles :size="13" /> 一站式 AI 模型测试与学习工作台</div>
            <div>
              <h1>让每一个 AI 模型，都能更快走向可用</h1>
              <p class="hero-description">
                统一管理视觉、文本与语音模型。从数据构建、训练评估到在线测试，在一个清晰的工作流中完成。
                近期已接入 OmDet 开放词汇检测、VLM-FO1 自然语言定位、MOSS 多人 ASR，以及跨镜 MTMC 证据落库与候选人工核对。
              </p>
            </div>
            <div class="actions">
              <a :href="links.test" class="button light" @click="onConsoleNav($event, '/ai/image')">
                <Play :size="13" fill="currentColor" />开始模型测试
              </a>
              <a href="#training" class="button ghost" @click.prevent="scrollToId('training')">
                <Workflow :size="13" />查看训练流程
              </a>
            </div>
            <div class="tag-row">
              <span v-for="([tag, tone]) in heroTags" :key="tag" class="tag" :class="`tag-${tone}`">{{ tag }}</span>
              <span class="task-count">{{ summary.taskKinds }}+ 任务类型</span>
            </div>
          </div>
          <div class="run-center">
            <div class="run-head">
              <div>
                <p>模型运行中心</p>
                <small>实时服务状态</small>
              </div>
              <span class="status" :class="{ offline: !backendOnline }">
                <i />{{ backendOnline ? '系统正常' : '后端离线' }}
              </span>
            </div>
            <div class="run-list">
              <div v-for="item in runItems" :key="item.name" class="run-item">
                <div>
                  <b>{{ item.name }}</b>
                  <span>{{ item.state }}</span>
                </div>
                <div class="progress"><i :style="{ width: item.progress }" /></div>
              </div>
            </div>
            <div class="run-footer">
              <span><Activity :size="13" />控制台 {{ adminHostLabel }}</span>
              <span>{{ consoleLoggedIn ? '已登录' : (summaryLoaded ? '数据已同步' : '演示数据') }}</span>
            </div>
          </div>
        </div>
      </div>
    </section>

    <div class="container content">
      <section class="stats" aria-label="平台资产概览">
        <article v-for="stat in stats" :key="stat.label" class="stat-card">
          <div class="stat-icon" :class="stat.tone">
            <component :is="stat.icon" :size="20" />
          </div>
          <div>
            <div class="stat-title">
              <strong>{{ stat.value }}</strong>
              <span>{{ stat.label }}</span>
            </div>
            <p>{{ stat.detail }}</p>
          </div>
        </article>
      </section>

      <section id="training" class="card training">
        <div class="card-head">
          <div>
            <h2>AI 训练闭环</h2>
            <p>从原始视频到可部署模型，六步完成训练</p>
          </div>
          <a :href="links.training" class="button primary" @click="onConsoleNav($event, '/ai/training')">
            进入模型训练 <ArrowRight :size="16" />
          </a>
        </div>
        <ol>
          <li v-for="([title, detail], index) in steps" :key="title">
            <div class="step-number">{{ index + 1 }}</div>
            <div class="step-line" v-if="index < steps.length - 1" />
            <div>
              <h3>{{ title }}</h3>
              <p>{{ detail }}</p>
            </div>
          </li>
        </ol>
      </section>

      <section id="scenarios" class="scenarios">
        <div class="section-head">
          <div>
            <b>开箱即用</b>
            <h2>热门应用场景</h2>
            <p>选择场景，跳转控制台开始模型验证与业务测试。</p>
          </div>
          <a :href="links.scenariosAll" @click="onConsoleNav($event, '/index')">查看全部场景 <ChevronRight :size="16" /></a>
        </div>
        <div class="scenario-grid">
          <a
            v-for="item in scenarios"
            :key="item.title"
            :href="scenarioHref(item)"
            class="scenario-card"
            @click="onScenarioNav($event, item)"
          >
            <div class="scenario-top">
              <div class="scenario-icon">
                <component :is="item.icon" :size="20" />
              </div>
              <ArrowRight :size="17" />
            </div>
            <div class="scenario-body">
              <span class="tag" :class="`tag-${item.tagTone}`">{{ item.tag }}</span>
              <h3>{{ item.title }}</h3>
              <p>{{ item.description }}</p>
            </div>
          </a>
        </div>
      </section>

      <section class="insights">
        <div>
          <b>数据洞察</b>
          <h2>模型资产一目了然</h2>
          <p class="insights-note">
            {{ summaryLoaded ? '以下数据来自后端公开接口 /api/portal/summary' : '后端未连通时展示演示数据；启动后端后自动刷新' }}
          </p>
        </div>
        <div class="chart-grid">
          <article class="card chart-card">
            <div class="chart-head">
              <h3>模型任务分布</h3>
              <p>按任务类型统计当前启用模型</p>
            </div>
            <div class="distribution">
              <div class="donut" :style="donutStyle">
                <div>
                  <strong>{{ summary.modelTotal }}</strong>
                  <span>模型总数</span>
                </div>
              </div>
              <div class="legend">
                <div v-for="item in distribution" :key="item.name">
                  <span><i :style="{ backgroundColor: item.color }" />{{ item.name }}</span>
                  <b>{{ item.raw != null ? item.raw : `${item.value}%` }}</b>
                </div>
              </div>
            </div>
          </article>
          <article class="card chart-card">
            <div class="chart-head">
              <h3>热门模型分类</h3>
              <p>按可用模型数量排序，快速识别资产覆盖情况</p>
            </div>
            <div class="bar-chart">
              <div v-for="item in activity" :key="item.name" class="bar-row">
                <span>{{ item.name }}</span>
                <div>
                  <i :style="{ width: `${(item.value / activityMax) * 100}%`, backgroundColor: item.color }" />
                </div>
                <b>{{ item.value }}</b>
              </div>
            </div>
          </article>
        </div>
      </section>

      <section class="portal-cta card">
        <div>
          <h2>准备好进入工作台了吗？</h2>
          <p>登录控制台即可管理模型、发起训练与在线推理；开放平台文档可直接查阅。</p>
        </div>
        <div class="portal-cta-actions">
          <a :href="links.console" class="button primary" @click="onConsoleNav($event, '/index')">进入控制台</a>
          <a :href="links.models" class="button ghost dark" @click="onConsoleNav($event, '/ai/model')">模型管理</a>
          <a :href="links.openapi" target="_blank" rel="noopener noreferrer" class="button ghost dark">
            <BookOpen :size="15" /> API 文档
          </a>
        </div>
      </section>

      <footer>
        <p>Tiger AI Platform · 多任务 AI 模型管理与测试平台</p>
        <p>
          <CircleDot :size="14" fill="currentColor" :class="{ offline: !backendOnline }" />
          {{ backendOnline ? '所有服务运行正常' : '后端暂不可用（可先浏览门户）' }}
          <template v-if="openApiMeta?.uptimeSec != null">
            · OpenAPI uptime {{ Math.round(openApiMeta.uptimeSec) }}s
          </template>
        </p>
      </footer>
    </div>
  </main>
</template>
