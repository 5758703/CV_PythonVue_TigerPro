<template>
  <div class="bdm-root">
    <el-tabs v-model="activeTab" type="border-card" class="bdm-tabs">
      <!-- ── 分析功能 ── -->
      <el-tab-pane label="分析功能" name="analyze">
        <el-card shadow="never" class="cfg-card">
          <el-form :inline="true" class="cfg-form">
            <el-form-item label="姿态模型">
              <el-select v-model="poseId" placeholder="YOLO Pose" style="width:200px">
                <el-option v-for="m in poseModels" :key="m.id" :label="m.modelName" :value="m.id" />
              </el-select>
            </el-form-item>
            <el-form-item label="羽毛球模型">
              <el-select v-model="ballId" placeholder="可选 YOLO 检测" clearable style="width:200px">
                <el-option v-for="m in ballModels" :key="m.id" :label="m.modelName" :value="m.id" />
              </el-select>
            </el-form-item>
            <el-form-item label="置信度">
              <el-slider v-model="conf" :min="0.1" :max="0.9" :step="0.05" style="width:120px" />
            </el-form-item>
            <el-form-item>
              <el-upload :show-file-list="false" :auto-upload="false" :on-change="onPickVideo" accept="video/*">
                <el-button :icon="UploadFilled">选择比赛视频</el-button>
              </el-upload>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :icon="VideoPlay" :loading="running"
                :disabled="!poseId || !file || courtPoints.length < 4" @click="runAnalyze">
                开始分析
              </el-button>
              <el-button :icon="Refresh" @click="resetAll">清空</el-button>
            </el-form-item>
          </el-form>

          <div class="vis-row">
            <el-checkbox v-model="opts.showSkeleton">骨架</el-checkbox>
            <el-checkbox v-model="opts.showTrajectories">球员轨迹</el-checkbox>
            <el-checkbox v-model="opts.showShuttle">羽毛球轨迹</el-checkbox>
            <el-checkbox v-model="opts.showStats">统计叠加</el-checkbox>
            <el-checkbox v-model="opts.showCourt">球场边框</el-checkbox>
            <el-radio-group v-model="opts.language" size="small" class="lang-radio">
              <el-radio-button value="zh">中文</el-radio-button>
              <el-radio-button value="en">EN</el-radio-button>
            </el-radio-group>
          </div>

          <el-alert v-if="!poseModels.length" type="warning" :closable="false" class="tip-alert"
            title="暂无姿态模型：请到「模型管理」拉取 YOLO Pose 权重（如 YOLO11n 姿态估计）。" />
        </el-card>

        <el-empty v-if="!file && !running && !resultVideoUrl" description="选择姿态模型与比赛视频，标注球场四角后开始分析"
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
                    <el-icon><Aim /></el-icon> 球场四角标注
                  </span>
                  <span class="hint">{{ courtHint }}</span>
                  <el-button v-if="courtPoints.length" link type="warning" size="small" @click="clearCourt">重标</el-button>
                </div>
                <div class="media-body dark">
                  <div v-if="!frameSrc" class="media-placeholder">加载首帧中…</div>
                  <div v-else class="frame-box">
                    <canvas ref="courtCanvas" class="court-canvas" @click="onCourtClick" />
                  </div>
                </div>
                <div class="court-tip">请依次点击：左上 → 右上 → 右下 → 左下</div>
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

      <!-- ── 分析结果（统计 / 图表 / 说明 同页） ── -->
      <el-tab-pane label="分析结果" name="results">
        <div class="results-page">
          <!-- 统计摘要 -->
          <section class="result-section">
            <div class="section-head">
              <h3>统计摘要</h3>
              <el-tag v-if="stats" type="success" size="small">分析完成</el-tag>
              <el-tag v-else type="info" size="small">暂无数据</el-tag>
            </div>
            <div v-if="stats" class="stat-grid">
              <div class="stat-card">
                <div class="stat-val">{{ stats.frames }}</div>
                <div class="stat-label">总帧数</div>
              </div>
              <div class="stat-card accent-blue">
                <div class="stat-val">{{ stats.rallyCount }}</div>
                <div class="stat-label">回合数</div>
              </div>
              <div class="stat-card accent-green">
                <div class="stat-val">{{ stats.totalPersons }}</div>
                <div class="stat-label">人体检测累计</div>
              </div>
              <div class="stat-card accent-orange">
                <div class="stat-val">{{ stats.shuttleDetections }}</div>
                <div class="stat-label">羽毛球检出帧</div>
              </div>
            </div>
            <el-empty v-else description="完成分析后将在此展示统计数据" :image-size="72" />

            <div v-if="distRows.length" class="player-table-wrap">
              <div class="sub-title">球员移动统计</div>
              <el-table :data="distRows" size="small" border stripe class="player-table">
                <el-table-column prop="label" label="球员" width="100" />
                <el-table-column label="移动距离 (m)">
                  <template #default="{ row }">{{ row.dist }}</template>
                </el-table-column>
                <el-table-column label="峰值速度 (m/s)">
                  <template #default="{ row }">{{ row.speed }}</template>
                </el-table-column>
              </el-table>
            </div>
          </section>

          <!-- 热力图 + 散点图 -->
          <el-row :gutter="16" class="chart-row">
            <el-col :xs="24" :md="12">
              <section class="result-section chart-section">
                <div class="section-head">
                  <h3>位置热力图</h3>
                </div>
                <div v-if="heatmapUrl" class="chart-frame">
                  <img :src="heatmapUrl" class="chart-img" alt="heatmap" />
                </div>
                <el-empty v-else description="暂无热力图" :image-size="64" />
              </section>
            </el-col>
            <el-col :xs="24" :md="12">
              <section class="result-section chart-section">
                <div class="section-head">
                  <h3>位置散点图</h3>
                </div>
                <div v-if="scatterUrl" class="chart-frame">
                  <img :src="scatterUrl" class="chart-img" alt="scatter" />
                </div>
                <el-empty v-else description="暂无散点图" :image-size="64" />
              </section>
            </el-col>
          </el-row>

          <!-- 功能说明 -->
          <section class="result-section guide-section">
            <div class="section-head">
              <h3>功能说明</h3>
            </div>
            <el-row :gutter="16" class="guide-grid">
              <el-col :xs="24" :sm="12" :lg="6" v-for="item in guideItems" :key="item.title">
                <div class="guide-card">
                  <div class="guide-icon" :class="item.color">{{ item.icon }}</div>
                  <div class="guide-title">{{ item.title }}</div>
                  <div class="guide-desc">{{ item.desc }}</div>
                </div>
              </el-col>
            </el-row>
            <el-alert type="info" :closable="false" show-icon class="guide-alert"
              title="参考 Good-Badminton：需标注球场四角（左上→右上→右下→左下），可选羽毛球 YOLO 权重（如 yolo11s-ball.pt）。" />
          </section>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { UploadFilled, VideoPlay, Refresh, Download, VideoCamera, Aim, Film } from '@element-plus/icons-vue'
import { modelApi, badmintonApi } from '../../../api/ai'

const COURT_LABELS = ['左上', '右上', '右下', '左下']

const guideItems = [
  { icon: '🏸', title: '球员姿态', desc: 'YOLO Pose 骨架检测，结合球场区域过滤场外干扰', color: 'c-blue' },
  { icon: '⚡', title: '羽毛球追踪', desc: '可选专用 YOLO 权重，追踪球路与落点', color: 'c-green' },
  { icon: '📐', title: '球场映射', desc: '四角单应性变换，映射至标准场地坐标系', color: 'c-orange' },
  { icon: '📊', title: '分析输出', desc: '标注视频、detections.jsonl、热力图与散点图', color: 'c-purple' },
]

const activeTab = ref('analyze')
const allModels = ref([])
const poseId = ref(null)
const ballId = ref(null)
const conf = ref(0.25)
const file = ref(null)
const fileName = ref('')
const originalVideoUrl = ref('')
const frameSrc = ref('')
const frameW = ref(0)
const frameH = ref(0)
const courtPoints = ref([])
const courtCanvas = ref(null)

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
    m.library === 'ultralytics' && m.task === 'pose-estimation' && m.filePath && m.status === '0')
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
  if (courtPoints.value.length >= 4) return '四角已标注完成'
  return `请依次点击：${COURT_LABELS[courtPoints.value.length] || '完成'}`
})
const distRows = computed(() => {
  if (!stats.value?.playerDistances) return []
  const speeds = stats.value.playerMaxSpeed || {}
  return Object.entries(stats.value.playerDistances).map(([id, dist]) => ({
    id,
    label: `球员 P${id}`,
    dist,
    speed: speeds[id] ?? '-',
  }))
})

async function loadModels() {
  const res = await modelApi.list({ pageNum: 1, pageSize: 200 })
  allModels.value = res.data?.rows || []
  if (!poseId.value && poseModels.value.length) {
    const pref = poseModels.value.find(m =>
      m.modelKey === 'yolo11s-pose' || m.modelName === 'yolo11s-pose')
    poseId.value = pref?.id || poseModels.value[0].id
  }
  if (!ballId.value && ballModels.value.length) {
    const pref = ballModels.value.find(m =>
      m.modelKey === 'tennis-ball' || m.modelName === 'tennis-ball')
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
  stats.value = null
  revokeUrls()
  revokeOriginalUrl()
  originalVideoUrl.value = URL.createObjectURL(uploadFile.raw)
  loadFirstFrame(uploadFile.raw)
}

async function loadFirstFrame(raw) {
  const fd = new FormData()
  fd.append('video', raw)
  try {
    const res = await badmintonApi.extractFrame(fd)
    frameSrc.value = 'data:image/jpeg;base64,' + res.data.imageBase64
    frameW.value = res.data.width
    frameH.value = res.data.height
    await nextTick()
    drawCourtCanvas()
  } catch (e) {
    ElMessage.error(e.message || '提取首帧失败')
  }
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
    cv.width = dw
    cv.height = dh
    const ctx = cv.getContext('2d')
    ctx.drawImage(img, 0, 0, dw, dh)
    if (courtPoints.value.length) {
      const pts = courtPoints.value.map(p => [p[0] * dw, p[1] * dh])
      ctx.strokeStyle = '#00dc00'
      ctx.lineWidth = 2
      ctx.beginPath()
      pts.forEach((p, i) => (i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1])))
      if (pts.length === 4) ctx.closePath()
      ctx.stroke()
      pts.forEach((p, i) => {
        ctx.fillStyle = '#ff3300'
        ctx.beginPath()
        ctx.arc(p[0], p[1], 5, 0, Math.PI * 2)
        ctx.fill()
        ctx.fillStyle = '#fff'
        ctx.font = '12px sans-serif'
        ctx.fillText(COURT_LABELS[i], p[0] + 8, p[1] - 4)
      })
    }
  }
  img.src = frameSrc.value
}

function onCourtClick(e) {
  if (!frameSrc.value || courtPoints.value.length >= 4) return
  const cv = courtCanvas.value
  const rect = cv.getBoundingClientRect()
  const x = (e.clientX - rect.left) / cv.width
  const y = (e.clientY - rect.top) / cv.height
  courtPoints.value.push([+x.toFixed(4), +y.toFixed(4)])
  drawCourtCanvas()
}

function clearCourt() {
  courtPoints.value = []
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
  if (!file.value || !poseId.value || courtPoints.value.length < 4) return
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
  fd.append('conf', conf.value)
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
  running.value = false
  stats.value = null
  jobId.value = ''
  activeTab.value = 'analyze'
  revokeUrls()
  revokeOriginalUrl()
}

watch(courtPoints, () => nextTick(drawCourtCanvas), { deep: true })

onMounted(loadModels)
onBeforeUnmount(() => { stopPoll(); revokeUrls(); revokeOriginalUrl() })
</script>

<style scoped>
.bdm-root { padding: 0; }
.bdm-tabs :deep(.el-tabs__content) { padding: 16px; }

.cfg-card { margin-bottom: 16px; border: none; }
.cfg-form { flex-wrap: wrap; }
.vis-row {
  display: flex; flex-wrap: wrap; align-items: center; gap: 12px 18px;
  padding: 10px 0 4px; border-top: 1px solid #ebeef5; margin-top: 4px;
}
.lang-radio { margin-left: 4px; }
.tip-alert { margin-top: 10px; }

.work-row { margin-bottom: 16px; }
.media-panel {
  background: #fff; border: 1px solid #e4e7ed; border-radius: 10px;
  overflow: hidden; height: 100%; display: flex; flex-direction: column;
}
.panel-hd {
  display: flex; align-items: center; gap: 10px;
  padding: 12px 16px; background: linear-gradient(180deg, #f8fafc 0%, #f2f6fc 100%);
  border-bottom: 1px solid #ebeef5;
}
.panel-title { font-weight: 600; color: #303133; display: inline-flex; align-items: center; gap: 6px; }
.panel-actions { margin-left: auto; display: flex; gap: 4px; }
.file-tag {
  margin-left: auto; font-size: 12px; color: #606266; max-width: 180px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.hint { font-size: 12px; color: #909399; flex: 1; }
.media-body {
  flex: 1; min-height: 260px; display: flex; align-items: center; justify-content: center;
  background: #0f0f14; padding: 10px;
}
.media-body.dark { background: #1a1a2e; }
.media-placeholder { color: #909399; font-size: 14px; }
.player { width: 100%; max-height: 420px; border-radius: 6px; background: #000; }
.frame-box { width: 100%; text-align: center; }
.court-canvas { max-width: 100%; cursor: crosshair; border-radius: 4px; }
.court-tip { padding: 8px 16px 12px; font-size: 12px; color: #909399; background: #fafafa; }

.progress-panel {
  margin-bottom: 16px; padding: 16px 18px;
  background: linear-gradient(135deg, #f0f7ff 0%, #f5f0ff 100%);
  border: 1px solid #d9ecff; border-radius: 10px;
}
.progress-head { display: flex; justify-content: space-between; margin-bottom: 10px; font-weight: 600; color: #303133; }
.progress-num { font-size: 13px; color: #606266; font-weight: 500; }
.result-panel { margin-bottom: 8px; }

/* ── 分析结果页 ── */
.results-page { display: flex; flex-direction: column; gap: 16px; }
.result-section {
  background: #fff; border: 1px solid #e4e7ed; border-radius: 10px; padding: 18px 20px;
}
.section-head {
  display: flex; align-items: center; gap: 10px; margin-bottom: 16px;
}
.section-head h3 { margin: 0; font-size: 16px; font-weight: 600; color: #303133; }

.stat-grid {
  display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px;
}
@media (max-width: 992px) { .stat-grid { grid-template-columns: repeat(2, 1fr); } }
.stat-card {
  text-align: center; padding: 18px 12px; border-radius: 10px;
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
  background: #fafafa; border-radius: 8px; padding: 10px;
  border: 1px dashed #dcdfe6; text-align: center;
}
.chart-img { width: 100%; max-height: 360px; object-fit: contain; border-radius: 6px; }

.guide-grid { margin-bottom: 14px; }
.guide-card {
  padding: 16px; border-radius: 10px; background: #f8fafc;
  border: 1px solid #ebeef5; height: 100%; transition: box-shadow .2s;
}
.guide-card:hover { box-shadow: 0 4px 12px rgba(0,0,0,.06); }
.guide-icon {
  width: 40px; height: 40px; border-radius: 10px; display: flex;
  align-items: center; justify-content: center; font-size: 20px; margin-bottom: 10px;
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
