<template>
  <div class="bdm-root">
    <el-tabs v-model="activeTab" type="border-card" class="bdm-tabs">
      <!-- ── 分析功能 ── -->
      <el-tab-pane label="分析功能" name="analyze">
        <el-card shadow="never" class="cfg-card">
          <el-form :inline="true" class="cfg-form">
            <el-form-item label="姿态模型">
              <el-select v-model="poseId" placeholder="YOLO / RTMO / RTMPose" style="width:220px">
                <el-option v-for="m in poseModels" :key="m.id"
                  :label="`${m.modelName}（${m.library}）`" :value="m.id" />
              </el-select>
            </el-form-item>
            <el-form-item label="羽毛球模型">
              <el-select v-model="ballId" placeholder="推荐自训 / YOLO11s-ball" clearable style="width:240px">
                <el-option v-for="m in ballModels" :key="m.id"
                  :label="ballModelLabel(m)" :value="m.id" />
              </el-select>
              <el-button link type="primary" class="train-link" @click="goTrainBallModel">自训提高精度</el-button>
            </el-form-item>
            <el-form-item label="置信度">
              <el-slider v-model="conf" :min="0.1" :max="0.9" :step="0.05" style="width:120px" />
            </el-form-item>
            <el-form-item label="球检测阈值">
              <el-slider v-model="ballConf" :min="0.08" :max="0.5" :step="0.02" style="width:120px" />
            </el-form-item>
            <el-form-item>
              <el-upload :show-file-list="false" :auto-upload="false" :on-change="onPickVideo" accept="video/*">
                <el-button :icon="UploadFilled">选择比赛视频</el-button>
              </el-upload>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :icon="VideoPlay" :loading="running"
                :disabled="!canAnalyze" @click="runAnalyze">
                开始分析
              </el-button>
              <el-button :icon="Refresh" @click="resetAll">清空</el-button>
            </el-form-item>
            <el-form-item label="叠加层" class="vis-item">
              <el-checkbox v-model="opts.showSkeleton">骨架</el-checkbox>
              <el-checkbox v-model="opts.showTrajectories">球员轨迹</el-checkbox>
              <el-checkbox v-model="opts.showShuttle">羽毛球轨迹</el-checkbox>
              <el-checkbox v-model="opts.showStats">统计叠加</el-checkbox>
              <el-checkbox v-model="opts.showCourt">球场边框</el-checkbox>
              <el-radio-group v-model="opts.language" size="small" class="lang-radio">
                <el-radio-button value="zh">中文</el-radio-button>
                <el-radio-button value="en">EN</el-radio-button>
              </el-radio-group>
            </el-form-item>
          </el-form>

          <el-alert v-if="!poseModels.length" type="warning" :closable="false" class="tip-alert"
            title="暂无姿态模型：请到「模型管理」拉取 YOLO Pose / RTMO / RTMPose（rtmlib）权重。" />
          <el-alert v-else-if="!ballModels.length" type="info" :closable="false" class="tip-alert"
            title="未检测到羽毛球模型：请拉取 yolo11s-ball，或点击「自训提高精度」用 Roboflow 数据集 + 自有比赛视频训练 YOLO11n/s 后部署。" />
        </el-card>

        <el-empty v-if="!file && !running && !resultVideoUrl" description="选择姿态模型与比赛视频，标注球场四角与网线后开始分析"
          :image-size="96" class="empty-main" />

        <template v-else>
          <el-row :gutter="16" class="work-row">
            <el-col :xs="24" :lg="12">
              <div class="media-panel">
                <div class="panel-hd">
                  <span class="panel-title">
                    <el-icon><VideoCamera /></el-icon> 原比赛视频
                  </span>
                  <span v-if="fileName" class="file-tag">{{ fileName }}</span>
                </div>
                <div class="media-body">
                  <video v-if="originalVideoUrl" :src="originalVideoUrl" controls class="player" />
                  <div v-else class="media-placeholder">请先选择视频文件</div>
                </div>
              </div>
            </el-col>

            <el-col :xs="24" :lg="12">
              <div class="media-panel">
                <div class="panel-hd">
                  <span class="panel-title">
                    <el-icon><Aim /></el-icon> 球场与网线标注
                  </span>
                  <span class="hint">{{ courtHint }}</span>
                </div>
                <div class="annot-toolbar">
                  <el-radio-group v-model="annotMode" size="small">
                    <el-radio-button value="corner">四角</el-radio-button>
                    <el-radio-button value="net" :disabled="courtPoints.length < 4">网线</el-radio-button>
                    <el-radio-button value="edit" :disabled="courtPoints.length < 4">拖拽修正</el-radio-button>
                  </el-radio-group>
                  <div class="annot-actions">
                    <el-button v-if="file" link type="primary" size="small" :loading="detectingCourt"
                      @click="runAutoDetect">自动检测</el-button>
                    <el-button v-if="courtPoints.length >= 4" link type="success" size="small"
                      @click="resetNetFromCorners">网线按四角重算</el-button>
                    <el-button v-if="courtPoints.length" link type="warning" size="small" @click="clearCourt">清空</el-button>
                  </div>
                </div>
                <div class="media-body dark">
                  <div v-if="!frameSrc" class="media-placeholder">加载首帧中…</div>
                  <div v-else class="frame-box">
                    <canvas
                      ref="courtCanvas"
                      class="court-canvas"
                      :class="{ dragging: !!dragTarget }"
                      @mousedown="onAnnotDown"
                      @mousemove="onAnnotMove"
                      @mouseup="onAnnotUp"
                      @mouseleave="onAnnotUp"
                      @click="onAnnotClick"
                    />
                  </div>
                </div>
                <div class="court-tip">
                  四角顺序：左上 → 右上 → 右下 → 左下；网线：左端 → 右端（可拖拽修正）。
                  四角完成后默认用左右边中点生成网线，也可切换「网线」模式手动画线。
                  <el-tag v-if="courtAutoDetected" type="success" size="small" effect="plain" class="court-tag">
                    自动检测 {{ courtConfidenceText }}
                  </el-tag>
                  <el-tag v-if="netManual" type="warning" size="small" effect="plain" class="court-tag">
                    网线已手改
                  </el-tag>
                </div>
              </div>
            </el-col>
          </el-row>

          <div v-if="running" class="progress-panel">
            <div class="progress-head">
              <span>分析进度</span>
              <span class="progress-num">{{ processed }} / {{ total || '?' }} 帧</span>
            </div>
            <el-progress :percentage="percent" :stroke-width="18" :text-inside="true" striped striped-flow />
          </div>

          <div v-if="resultVideoUrl" class="media-panel result-panel">
            <div class="panel-hd">
              <span class="panel-title">
                <el-icon><Film /></el-icon> 分析结果视频
              </span>
              <div class="panel-actions">
                <el-button link type="primary" @click="activeTab = 'results'">查看统计与图表</el-button>
                <el-button link type="primary" :icon="Download" @click="downloadVideo">下载</el-button>
              </div>
            </div>
            <div class="media-body">
              <video :src="resultVideoUrl" controls class="player" />
            </div>
          </div>
        </template>
      </el-tab-pane>

      <!-- ── 分析结果（球员对比 / 热区落点 / AI 洞察 / 训练建议） ── -->
      <el-tab-pane label="分析结果" name="results">
        <BadmintonMatchReport
          v-if="stats?.report"
          :report="stats.report"
          :summary="stats"
          :heatmap-url="heatmapUrl"
          :scatter-url="scatterUrl"
          :result-video-url="resultVideoUrl"
          @play-video="scrollToResultVideo"
        />
        <div v-else class="results-page">
          <el-empty description="完成分析后将展示技战术报告（球员对比、热区、落点、AI 洞察与训练建议）" :image-size="96" />
          <el-row v-if="heatmapUrl || scatterUrl" :gutter="16" class="chart-row">
            <el-col :xs="24" :md="12">
              <section class="result-section chart-section">
                <div class="section-head"><h3>位置热力图</h3></div>
                <div v-if="heatmapUrl" class="chart-frame">
                  <img :src="heatmapUrl" class="chart-img" alt="heatmap" />
                </div>
              </section>
            </el-col>
            <el-col :xs="24" :md="12">
              <section class="result-section chart-section">
                <div class="section-head"><h3>位置散点图</h3></div>
                <div v-if="scatterUrl" class="chart-frame">
                  <img :src="scatterUrl" class="chart-img" alt="scatter" />
                </div>
              </section>
            </el-col>
          </el-row>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { UploadFilled, VideoPlay, Refresh, Download, VideoCamera, Aim, Film } from '@element-plus/icons-vue'
import { modelApi, badmintonApi } from '../../../api/ai'
import BadmintonMatchReport from './BadmintonMatchReport.vue'

const router = useRouter()

const COURT_LABELS = ['左上', '右上', '右下', '左下']
const NET_LABELS = ['网左', '网右']
const HIT_RADIUS = 14

const activeTab = ref('analyze')
const allModels = ref([])
const poseId = ref(null)
const ballId = ref(null)
const conf = ref(0.25)
const ballConf = ref(0.15)
const file = ref(null)
const fileName = ref('')
const originalVideoUrl = ref('')
const frameSrc = ref('')
const frameW = ref(0)
const frameH = ref(0)
const courtPoints = ref([])
const netPoints = ref([])
const netManual = ref(false)
const annotMode = ref('corner')
const courtCanvas = ref(null)
const detectingCourt = ref(false)
const courtAutoDetected = ref(false)
const courtConfidence = ref(0)
const dragTarget = ref(null) // { kind: 'corner'|'net', index: number }
let suppressClick = false
let canvasScale = { dw: 1, dh: 1 }

const running = ref(false)
const jobId = ref('')
const processed = ref(0)
const total = ref(0)
const stats = ref(null)
const resultVideoUrl = ref('')
const heatmapUrl = ref('')
const scatterUrl = ref('')

const opts = reactive({
  showSkeleton: true,
  showTrajectories: true,
  showShuttle: true,
  showStats: true,
  showCourt: true,
  language: 'zh',
})

let pollTimer = null

const poseModels = computed(() =>
  allModels.value.filter(m =>
    (m.library === 'ultralytics' || m.library === 'rtmlib')
    && m.task === 'pose-estimation' && m.status === '0'
    && (m.library === 'rtmlib' || m.filePath))
)
const ballModels = computed(() =>
  allModels.value.filter(m =>
    m.library === 'ultralytics' && m.task === 'object-detection' && m.filePath && m.status === '0')
)
const percent = computed(() => {
  if (!total.value) return running.value ? 5 : 0
  return Math.min(100, Math.round((processed.value / total.value) * 100))
})
const courtHint = computed(() => {
  if (detectingCourt.value) return '正在自动检测球场线…'
  if (annotMode.value === 'edit') return '拖拽彩色角点或橙色网线端点修正'
  if (annotMode.value === 'net') {
    if (netPoints.value.length >= 2) return '网线已标注，可切换「拖拽修正」微调'
    return `请点击网线：${NET_LABELS[netPoints.value.length] || '完成'}`
  }
  if (courtPoints.value.length >= 4) {
    return courtAutoDetected.value
      ? '四角已自动检测，可拖拽修正或编辑网线'
      : '四角已完成，可拖拽修正或切换「网线」手动画线'
  }
  return `请依次点击：${COURT_LABELS[courtPoints.value.length] || '完成'}`
})
const courtConfidenceText = computed(() =>
  courtConfidence.value ? `${Math.round(courtConfidence.value * 100)}%` : '')
const canAnalyze = computed(() =>
  !!poseId.value && !!file.value && courtPoints.value.length >= 4 && netPoints.value.length >= 2)
function scrollToResultVideo() {
  activeTab.value = 'analyze'
  nextTick(() => {
    document.querySelector('.result-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  })
}

function isCustomBallModel(m) {
  const k = (m.modelKey || '').toLowerCase()
  const n = (m.modelName || '').toLowerCase()
  return k.startsWith('badminton-yolo')
    || (k.startsWith('custom-') && (n.includes('羽毛球') || n.includes('badminton') || n.includes('shuttle')))
    || (n.includes('自训') && (n.includes('羽毛') || n.includes('ball')))
}

function ballModelLabel(m) {
  if (isCustomBallModel(m)) return `${m.modelName}（自训）`
  if (m.modelKey === 'yolo11s-ball') return `${m.modelName}（预置）`
  return m.modelName
}

function pickPreferredBall(models) {
  const rank = (m) => {
    if (isCustomBallModel(m)) return 0
    if (m.modelKey === 'yolo11s-ball') return 1
    if ((m.modelName || '').includes('羽毛球') || (m.modelKey || '').includes('badminton')) return 2
    if (m.modelKey === 'tennis-ball') return 3
    return 9
  }
  return [...models].sort((a, b) => rank(a) - rank(b))[0]
}

function goTrainBallModel() {
  router.push({ name: 'aiTraining', query: { preset: 'badminton' } })
}

async function loadModels() {
  const res = await modelApi.list({ pageNum: 1, pageSize: 200 })
  allModels.value = res.data?.rows || []
  if (!poseId.value && poseModels.value.length) {
    const pref = poseModels.value.find(m =>
      m.modelKey === 'rtmo-s' || m.modelKey === 'rtmpose-m' || m.modelKey === 'yolo11s-pose' || m.modelName?.includes('RTMO'))
    poseId.value = pref?.id || poseModels.value[0].id
  }
  if (!ballId.value && ballModels.value.length) {
    const pref = pickPreferredBall(ballModels.value)
    if (pref) ballId.value = pref.id
  }
}

function revokeOriginalUrl() {
  if (originalVideoUrl.value?.startsWith('blob:')) URL.revokeObjectURL(originalVideoUrl.value)
  originalVideoUrl.value = ''
}

function onPickVideo(uploadFile) {
  file.value = uploadFile.raw
  fileName.value = uploadFile.name || '比赛视频'
  courtPoints.value = []
  netPoints.value = []
  netManual.value = false
  annotMode.value = 'corner'
  courtAutoDetected.value = false
  courtConfidence.value = 0
  stats.value = null
  revokeUrls()
  revokeOriginalUrl()
  originalVideoUrl.value = URL.createObjectURL(uploadFile.raw)
  runAutoDetect(uploadFile.raw)
}

function midNetFromCorners(corners) {
  if (!corners || corners.length < 4) return []
  const [tl, tr, br, bl] = corners
  return [
    [+((tl[0] + bl[0]) / 2).toFixed(4), +((tl[1] + bl[1]) / 2).toFixed(4)],
    [+((tr[0] + br[0]) / 2).toFixed(4), +((tr[1] + br[1]) / 2).toFixed(4)],
  ]
}

function syncNetFromCorners(force = false) {
  if (courtPoints.value.length < 4) {
    netPoints.value = []
    return
  }
  if (!force && netManual.value && netPoints.value.length === 2) return
  netPoints.value = midNetFromCorners(courtPoints.value)
  if (force) netManual.value = false
}

function resetNetFromCorners() {
  syncNetFromCorners(true)
  drawCourtCanvas()
  ElMessage.success('已按四角左右边中点重算网线')
}

async function runAutoDetect(raw) {
  const video = raw || file.value
  if (!video) return
  detectingCourt.value = true
  courtPoints.value = []
  netPoints.value = []
  netManual.value = false
  annotMode.value = 'corner'
  courtAutoDetected.value = false
  courtConfidence.value = 0
  const fd = new FormData()
  fd.append('video', video)
  try {
    const res = await badmintonApi.detectCourt(fd)
    const d = res.data
    frameSrc.value = 'data:image/jpeg;base64,' + d.imageBase64
    frameW.value = d.width
    frameH.value = d.height
    if (d.autoDetected && d.courtPoints?.length === 4) {
      courtPoints.value = d.courtPoints
      courtAutoDetected.value = true
      courtConfidence.value = d.confidence || 0
      syncNetFromCorners(true)
      annotMode.value = 'edit'
      ElMessage.success(`球场四角已自动检测（置信度 ${Math.round((d.confidence || 0) * 100)}%），可拖拽修正四角/网线`)
    } else {
      ElMessage.warning('未能自动识别球场，请手动标注四角')
    }
    await nextTick()
    drawCourtCanvas()
  } catch (e) {
    ElMessage.error(e?.response?.data?.message || e.message || '球场检测失败')
  } finally {
    detectingCourt.value = false
  }
}

function canvasNormFromEvent(e) {
  const cv = courtCanvas.value
  if (!cv) return null
  const rect = cv.getBoundingClientRect()
  const x = (e.clientX - rect.left) / cv.width
  const y = (e.clientY - rect.top) / cv.height
  return [
    +Math.min(1, Math.max(0, x)).toFixed(4),
    +Math.min(1, Math.max(0, y)).toFixed(4),
  ]
}

function hitTest(nx, ny) {
  const cv = courtCanvas.value
  if (!cv) return null
  const r = HIT_RADIUS / Math.max(cv.width, cv.height)
  const near = (pts, kind) => {
    for (let i = 0; i < pts.length; i++) {
      const dx = pts[i][0] - nx
      const dy = pts[i][1] - ny
      if (Math.hypot(dx, dy) <= r * 1.8) return { kind, index: i }
    }
    return null
  }
  return near(netPoints.value, 'net') || near(courtPoints.value, 'corner')
}

function drawCourtCanvas() {
  const cv = courtCanvas.value
  if (!cv || !frameSrc.value) return
  const img = new Image()
  img.onload = () => {
    const maxW = cv.parentElement?.clientWidth || 720
    const scale = Math.min(1, maxW / img.width)
    const dw = Math.round(img.width * scale)
    const dh = Math.round(img.height * scale)
    canvasScale = { dw, dh }
    cv.width = dw
    cv.height = dh
    const ctx = cv.getContext('2d')
    ctx.drawImage(img, 0, 0, dw, dh)

    ctx.fillStyle = 'rgba(0, 180, 255, 0.04)'
    const grid = 32
    for (let gx = 0; gx < dw; gx += grid) ctx.fillRect(gx, 0, 1, dh)
    for (let gy = 0; gy < dh; gy += grid) ctx.fillRect(0, gy, dw, 1)

    if (courtPoints.value.length) {
      const pts = courtPoints.value.map(p => [p[0] * dw, p[1] * dh])
      ctx.strokeStyle = 'rgba(0, 220, 255, 0.85)'
      ctx.lineWidth = 2
      ctx.shadowColor = 'rgba(0, 220, 255, 0.6)'
      ctx.shadowBlur = 8
      ctx.beginPath()
      pts.forEach((p, i) => (i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1])))
      if (pts.length === 4) ctx.closePath()
      ctx.stroke()
      ctx.shadowBlur = 0

      const colors = ['#00dcff', '#ff6bcb', '#ffd54f', '#7cffb2']
      pts.forEach((p, i) => {
        ctx.beginPath()
        ctx.arc(p[0], p[1], 7, 0, Math.PI * 2)
        ctx.fillStyle = colors[i]
        ctx.fill()
        ctx.strokeStyle = '#fff'
        ctx.lineWidth = 1.5
        ctx.stroke()
        ctx.fillStyle = 'rgba(8, 12, 20, 0.75)'
        ctx.font = '600 11px "Segoe UI", sans-serif'
        const tw = ctx.measureText(COURT_LABELS[i]).width
        ctx.fillRect(p[0] + 10, p[1] - 18, tw + 8, 16)
        ctx.fillStyle = '#e8f4ff'
        ctx.fillText(COURT_LABELS[i], p[0] + 14, p[1] - 6)
      })
    }

    if (netPoints.value.length) {
      const npts = netPoints.value.map(p => [p[0] * dw, p[1] * dh])
      ctx.strokeStyle = 'rgba(255, 170, 0, 0.95)'
      ctx.lineWidth = 2.5
      ctx.setLineDash([8, 5])
      ctx.beginPath()
      if (npts.length >= 2) {
        ctx.moveTo(npts[0][0], npts[0][1])
        ctx.lineTo(npts[1][0], npts[1][1])
      }
      ctx.stroke()
      ctx.setLineDash([])
      npts.forEach((p, i) => {
        ctx.beginPath()
        ctx.arc(p[0], p[1], 8, 0, Math.PI * 2)
        ctx.fillStyle = '#ffaa00'
        ctx.fill()
        ctx.strokeStyle = '#fff'
        ctx.lineWidth = 1.5
        ctx.stroke()
        ctx.fillStyle = 'rgba(8, 12, 20, 0.75)'
        ctx.font = '600 11px "Segoe UI", sans-serif'
        const label = NET_LABELS[i]
        const tw = ctx.measureText(label).width
        ctx.fillRect(p[0] + 10, p[1] + 6, tw + 8, 16)
        ctx.fillStyle = '#ffe8c2'
        ctx.fillText(label, p[0] + 14, p[1] + 18)
      })
    }
  }
  img.src = frameSrc.value
}

function onAnnotDown(e) {
  if (!frameSrc.value) return
  const norm = canvasNormFromEvent(e)
  if (!norm) return
  const hit = hitTest(norm[0], norm[1])
  if (hit) {
    dragTarget.value = hit
    suppressClick = true
    courtAutoDetected.value = false
    if (hit.kind === 'net') netManual.value = true
    e.preventDefault()
  }
}

function onAnnotMove(e) {
  if (!dragTarget.value) return
  const norm = canvasNormFromEvent(e)
  if (!norm) return
  const { kind, index } = dragTarget.value
  if (kind === 'corner' && courtPoints.value[index]) {
    courtPoints.value[index] = norm
    if (!netManual.value) syncNetFromCorners(false)
  } else if (kind === 'net' && netPoints.value[index]) {
    netPoints.value[index] = norm
    netManual.value = true
  }
  drawCourtCanvas()
  suppressClick = true
}

function onAnnotUp() {
  if (dragTarget.value) {
    dragTarget.value = null
    setTimeout(() => { suppressClick = false }, 0)
  }
}

function onAnnotClick(e) {
  if (suppressClick || dragTarget.value) return
  if (!frameSrc.value) return
  const norm = canvasNormFromEvent(e)
  if (!norm) return

  if (annotMode.value === 'edit') return

  if (annotMode.value === 'net') {
    if (courtPoints.value.length < 4) return
    courtAutoDetected.value = false
    if (netPoints.value.length >= 2) {
      const hit = hitTest(norm[0], norm[1])
      if (hit?.kind === 'net') {
        netPoints.value[hit.index] = norm
      } else {
        netPoints.value = [norm]
      }
      netManual.value = true
    } else {
      netPoints.value.push(norm)
      netManual.value = true
    }
    drawCourtCanvas()
    return
  }

  courtAutoDetected.value = false
  if (courtPoints.value.length >= 4) {
    const hit = hitTest(norm[0], norm[1])
    if (hit?.kind === 'corner') {
      courtPoints.value[hit.index] = norm
      if (!netManual.value) syncNetFromCorners(false)
    }
    drawCourtCanvas()
    return
  }
  courtPoints.value.push(norm)
  if (courtPoints.value.length === 4) {
    syncNetFromCorners(true)
    annotMode.value = 'edit'
    ElMessage.success('四角与默认网线已就绪，可拖拽修正或切换「网线」重画')
  }
  drawCourtCanvas()
}

function clearCourt() {
  courtPoints.value = []
  netPoints.value = []
  netManual.value = false
  annotMode.value = 'corner'
  courtAutoDetected.value = false
  courtConfidence.value = 0
  dragTarget.value = null
  drawCourtCanvas()
}

function revokeUrls() {
  ;[resultVideoUrl, heatmapUrl, scatterUrl].forEach(u => {
    if (u.value?.startsWith('blob:')) URL.revokeObjectURL(u.value)
  })
  resultVideoUrl.value = ''
  heatmapUrl.value = ''
  scatterUrl.value = ''
}

async function runAnalyze() {
  if (!canAnalyze.value) return
  running.value = true
  stats.value = null
  revokeUrls()
  processed.value = 0
  total.value = 0

  const fd = new FormData()
  fd.append('video', file.value)
  fd.append('poseId', poseId.value)
  if (ballId.value) fd.append('ballId', ballId.value)
  fd.append('courtPoints', JSON.stringify(courtPoints.value))
  fd.append('netPoints', JSON.stringify(netPoints.value))
  fd.append('conf', conf.value)
  fd.append('ballConf', ballConf.value)
  fd.append('showSkeleton', opts.showSkeleton ? '1' : '0')
  fd.append('showTrajectories', opts.showTrajectories ? '1' : '0')
  fd.append('showShuttle', opts.showShuttle ? '1' : '0')
  fd.append('showStats', opts.showStats ? '1' : '0')
  fd.append('showCourt', opts.showCourt ? '1' : '0')
  fd.append('language', opts.language)

  try {
    const res = await badmintonApi.analyze(fd)
    jobId.value = res.data.jobId
    startPoll()
  } catch (e) {
    running.value = false
    ElMessage.error(e.message || '启动失败')
  }
}

function startPoll() {
  stopPoll()
  pollTimer = setInterval(pollOnce, 2000)
  pollOnce()
}

async function pollOnce() {
  if (!jobId.value) return
  try {
    const res = await badmintonApi.progress(jobId.value)
    const d = res.data
    processed.value = d.processed || 0
    total.value = d.total || 0
    if (d.status === 'done') {
      running.value = false
      stopPoll()
      stats.value = d.stats
      await loadArtifacts(d.artifacts)
      activeTab.value = 'results'
      ElMessage.success('分析完成，已切换至分析结果')
    } else if (d.status === 'error') {
      running.value = false
      stopPoll()
      ElMessage.error(d.error || '分析失败')
    }
  } catch { /* ignore transient */ }
}

async function loadArtifacts(artifacts) {
  if (!artifacts) return
  const pick = (url) => {
    const m = url?.match(/\/artifact\/[^/]+\/(.+)$/)
    return m ? m[1] : null
  }
  if (artifacts.video) {
    const name = pick(artifacts.video)
    const blob = await badmintonApi.artifactBlob(jobId.value, name)
    resultVideoUrl.value = URL.createObjectURL(blob)
  }
  if (artifacts.heatmap) {
    const blob = await badmintonApi.artifactBlob(jobId.value, pick(artifacts.heatmap))
    heatmapUrl.value = URL.createObjectURL(blob)
  }
  if (artifacts.scatter) {
    const blob = await badmintonApi.artifactBlob(jobId.value, pick(artifacts.scatter))
    scatterUrl.value = URL.createObjectURL(blob)
  }
}

function stopPoll() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

function downloadVideo() {
  if (!resultVideoUrl.value) return
  const a = document.createElement('a')
  a.href = resultVideoUrl.value
  a.download = `badminton_${Date.now()}.mp4`
  a.click()
}

function resetAll() {
  stopPoll()
  file.value = null
  fileName.value = ''
  frameSrc.value = ''
  courtPoints.value = []
  netPoints.value = []
  netManual.value = false
  annotMode.value = 'corner'
  courtAutoDetected.value = false
  courtConfidence.value = 0
  dragTarget.value = null
  running.value = false
  stats.value = null
  jobId.value = ''
  activeTab.value = 'analyze'
  revokeUrls()
  revokeOriginalUrl()
}

watch([courtPoints, netPoints], () => nextTick(drawCourtCanvas), { deep: true })

onMounted(loadModels)
onBeforeUnmount(() => { stopPoll(); revokeUrls(); revokeOriginalUrl() })
</script>

<style scoped>
.bdm-root { padding: 0; }
.bdm-tabs :deep(.el-tabs__content) { padding: 16px; }

.cfg-card { margin-bottom: 16px; border: none; }
.cfg-form { flex-wrap: wrap; }
.train-link { margin-left: 6px; }
.vis-item :deep(.el-form-item__content) {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 14px;
}
.lang-radio { margin-left: 4px; }
.tip-alert { margin-top: 10px; }

.work-row { margin-bottom: 16px; }
.media-panel {
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 10px;
  overflow: hidden;
  height: 100%;
  display: flex;
  flex-direction: column;
}
.panel-hd {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  background: linear-gradient(180deg, #f8fafc 0%, #f2f6fc 100%);
  border-bottom: 1px solid #ebeef5;
}
.panel-title {
  font-weight: 600;
  color: #303133;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.panel-actions { margin-left: auto; display: flex; gap: 4px; }
.file-tag {
  margin-left: auto;
  font-size: 12px;
  color: #606266;
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.hint { font-size: 12px; color: #909399; flex: 1; }
.media-body {
  flex: 1;
  min-height: 260px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #0f0f14;
  padding: 10px;
}
.media-body.dark { background: #1a1a2e; }
.media-placeholder { color: #909399; font-size: 14px; }
.player { width: 100%; max-height: 420px; border-radius: 6px; background: #000; }
.frame-box { width: 100%; text-align: center; }
.annot-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 0 12px 8px;
}
.annot-actions { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }
.court-canvas { max-width: 100%; cursor: crosshair; border-radius: 4px; user-select: none; }
.court-canvas.dragging { cursor: grabbing; }
.court-tip {
  padding: 8px 16px 12px;
  font-size: 12px;
  color: #909399;
  background: #fafafa;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.court-tag { margin-left: 4px; }

.progress-panel {
  margin-bottom: 16px;
  padding: 16px 18px;
  background: linear-gradient(135deg, #f0f7ff 0%, #f5f0ff 100%);
  border: 1px solid #d9ecff;
  border-radius: 10px;
}
.progress-head {
  display: flex;
  justify-content: space-between;
  margin-bottom: 10px;
  font-weight: 600;
  color: #303133;
}
.progress-num { font-size: 13px; color: #606266; font-weight: 500; }
.result-panel { margin-bottom: 8px; }

.results-page { display: flex; flex-direction: column; gap: 16px; }
.result-section {
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 10px;
  padding: 18px 20px;
}
.section-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
}
.section-head h3 { margin: 0; font-size: 16px; font-weight: 600; color: #303133; }

.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
}
@media (max-width: 992px) { .stat-grid { grid-template-columns: repeat(2, 1fr); } }
.stat-card {
  text-align: center;
  padding: 18px 12px;
  border-radius: 10px;
  background: linear-gradient(145deg, #f5f7fa 0%, #eef2f7 100%);
  border: 1px solid #e4e7ed;
}
.stat-card.accent-blue { background: linear-gradient(145deg, #ecf5ff 0%, #d9ecff 100%); border-color: #b3d8ff; }
.stat-card.accent-green { background: linear-gradient(145deg, #f0f9eb 0%, #e1f3d8 100%); border-color: #b3e19d; }
.stat-card.accent-orange { background: linear-gradient(145deg, #fdf6ec 0%, #faecd8 100%); border-color: #f5dab1; }
.stat-val { font-size: 28px; font-weight: 700; color: #303133; line-height: 1.2; }
.stat-label { margin-top: 6px; font-size: 13px; color: #606266; }

.player-table-wrap { margin-top: 18px; }
.sub-title { font-size: 14px; font-weight: 600; color: #303133; margin-bottom: 10px; }
.player-table { max-width: 520px; }

.chart-row { margin: 0 !important; }
.chart-section { height: 100%; min-height: 320px; }
.chart-frame {
  background: #fafafa;
  border-radius: 8px;
  padding: 10px;
  border: 1px dashed #dcdfe6;
  text-align: center;
}
.chart-img { width: 100%; max-height: 360px; object-fit: contain; border-radius: 6px; }

.guide-grid { margin-bottom: 14px; }
.guide-card {
  padding: 16px;
  border-radius: 10px;
  background: #f8fafc;
  border: 1px solid #ebeef5;
  height: 100%;
  transition: box-shadow 0.2s;
}
.guide-card:hover { box-shadow: 0 4px 12px rgba(0, 0, 0, 0.06); }
.guide-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  margin-bottom: 10px;
}
.guide-icon.c-blue { background: #ecf5ff; }
.guide-icon.c-green { background: #f0f9eb; }
.guide-icon.c-orange { background: #fdf6ec; }
.guide-icon.c-purple { background: #f4ecff; }
.guide-title { font-weight: 600; color: #303133; margin-bottom: 6px; }
.guide-desc { font-size: 13px; color: #606266; line-height: 1.6; }
.guide-alert { margin-top: 4px; }

.empty-main { margin: 48px 0; }
</style>
