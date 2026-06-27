<template>
  <div>
    <el-card shadow="never" class="cfg-card">
      <el-form :inline="true">
        <el-form-item label="模型分类">
          <el-select v-model="category" placeholder="全部分类" clearable style="width: 150px" @change="onCategoryChange">
            <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="检测模型">
          <el-select v-model="modelId" placeholder="选择 YOLO 模型" style="width: 220px">
            <el-option v-for="m in filteredModels" :key="m.id"
                       :label="`${m.modelName}（${m.category || '未分类'}）`" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="分辨率">
          <el-select v-model="imgsz" style="width: 110px">
            <el-option :value="640" label="640" />
            <el-option :value="480" label="480" />
            <el-option :value="320" label="320（最快）" />
          </el-select>
        </el-form-item>
        <el-form-item label="置信度">
          <el-slider v-model="conf" :min="0.05" :max="0.95" :step="0.05" style="width: 150px" />
        </el-form-item>
        <el-form-item>
          <el-upload :show-file-list="false" :auto-upload="false" :on-change="onPick" accept="video/*">
            <el-button :icon="UploadFilled">选择视频</el-button>
          </el-upload>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :icon="VideoPlay" :loading="running" :disabled="!modelId || !file" @click="run">开始追踪</el-button>
          <el-button :icon="Refresh" @click="clearAll">清空</el-button>
        </el-form-item>
      </el-form>
      <el-alert v-if="!modelOptions.length" type="warning" :closable="false"
                title="暂无可用模型：目标追踪需 ultralytics（YOLO）目标检测模型，请到「模型管理」上传/拉取并启用。" />
      <div v-else class="hint">越线计数（可选）：在下方首帧上点两点画一条计数线；不画则不统计越线。</div>
    </el-card>

    <el-card v-if="file" shadow="never" class="cfg-card">
      <div class="line-tip">
        首帧画线：点第一点 → 点第二点。
        <el-button link type="primary" @click="clearLine">清除线</el-button>
        <span v-if="line" class="meta">已设置计数线</span>
      </div>
      <div class="frame-box">
        <canvas ref="frameCanvas" class="frame-canvas" @click="onCanvasClick"></canvas>
      </div>
    </el-card>

    <el-card shadow="never">
      <div v-if="running" class="progress-box">
        <div class="progress-title">追踪中… {{ processed }}/{{ total || '?' }} 帧</div>
        <el-progress :percentage="percent" :stroke-width="18" :text-inside="true" :status="percent >= 100 ? 'success' : ''" />
      </div>

      <el-empty v-else-if="!resultUrl" description="选择模型与视频后开始追踪" />

      <div v-else>
        <div class="res-title">
          追踪结果
          <el-button link type="primary" :icon="Download" @click="download">下载视频</el-button>
        </div>
        <video :src="resultUrl" controls class="player" />
        <div class="stats">
          <el-tag type="success" effect="dark">唯一目标数：{{ stats.uniqueObjects }}</el-tag>
          <el-tag v-if="stats.crossing" type="warning" effect="dark">
            越线 进:{{ stats.crossing.in }} 出:{{ stats.crossing.out }} 净:{{ stats.crossing.in - stats.crossing.out }}
          </el-tag>
        </div>
        <el-table :data="classRows" size="small" border class="cls-table">
          <el-table-column prop="name" label="类别" />
          <el-table-column prop="count" label="唯一数量" width="120" />
        </el-table>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { UploadFilled, VideoPlay, Refresh, Download } from '@element-plus/icons-vue'
import { modelApi } from '../../../api/ai'

const modelOptions = ref([])
const modelId = ref(null)
const category = ref('')
const imgsz = ref(640)
const conf = ref(0.25)
const file = ref(null)

const frameCanvas = ref(null)
const linePts = ref([])      // 像素点 [{x,y}...]（canvas 坐标）
const line = ref(null)       // 归一化 [x1,y1,x2,y2]
let frameW = 0
let frameH = 0

const running = ref(false)
const processed = ref(0)
const total = ref(0)
const resultUrl = ref('')
const stats = ref({})
let pollTimer = null
let blobUrl = ''

const categories = computed(() => [...new Set(modelOptions.value.map((m) => m.category).filter(Boolean))])
const filteredModels = computed(() =>
  category.value ? modelOptions.value.filter((m) => m.category === category.value) : modelOptions.value)
const percent = computed(() => (total.value ? Math.min(100, Math.floor((processed.value / total.value) * 100)) : 0))
const classRows = computed(() =>
  Object.entries(stats.value.classCounts || {}).map(([name, count]) => ({ name, count })))

const onCategoryChange = () => { modelId.value = filteredModels.value[0]?.id || null }

const loadModels = async () => {
  const res = await modelApi.list({ pageNum: 1, pageSize: 100 })
  modelOptions.value = (res.data.rows || []).filter(
    (m) => m.library === 'ultralytics' && m.task === 'object-detection' && m.filePath && m.status === '0')
  if (modelOptions.value.length && !modelId.value) modelId.value = modelOptions.value[0].id
}

const onPick = (uploadFile) => {
  const raw = uploadFile.raw
  if (!raw || !raw.type.startsWith('video/')) { ElMessage.error('请选择视频文件'); return }
  file.value = raw
  clearLine()
  clearOutput()
  drawFirstFrame(raw)
}

const clearOutput = () => {
  if (blobUrl) { URL.revokeObjectURL(blobUrl); blobUrl = '' }
  resultUrl.value = ''
  stats.value = {}
}

const drawFirstFrame = (raw) => {
  const url = URL.createObjectURL(raw)
  const v = document.createElement('video')
  v.preload = 'auto'
  v.muted = true
  v.src = url
  v.addEventListener('loadeddata', () => {
    v.currentTime = 0
  })
  v.addEventListener('seeked', async () => {
    frameW = v.videoWidth
    frameH = v.videoHeight
    await nextTick()
    const cv = frameCanvas.value
    if (!cv) return
    // 显示宽度上限 640，等比
    const dispW = Math.min(640, frameW)
    const scale = dispW / frameW
    cv.width = dispW
    cv.height = Math.round(frameH * scale)
    const ctx = cv.getContext('2d')
    ctx.drawImage(v, 0, 0, cv.width, cv.height)
    URL.revokeObjectURL(url)
  })
}

const redraw = () => {
  const cv = frameCanvas.value
  if (!cv) return
  const ctx = cv.getContext('2d')
  // 重画底图需重新抽帧太重，这里只在已绘制基础上叠加点/线
  if (linePts.value.length) {
    ctx.fillStyle = '#ff1744'
    linePts.value.forEach((p) => { ctx.beginPath(); ctx.arc(p.x, p.y, 4, 0, Math.PI * 2); ctx.fill() })
    if (linePts.value.length === 2) {
      ctx.strokeStyle = '#ff1744'
      ctx.lineWidth = 2
      ctx.beginPath()
      ctx.moveTo(linePts.value[0].x, linePts.value[0].y)
      ctx.lineTo(linePts.value[1].x, linePts.value[1].y)
      ctx.stroke()
    }
  }
}

const onCanvasClick = (e) => {
  if (linePts.value.length >= 2) return
  const cv = frameCanvas.value
  const rect = cv.getBoundingClientRect()
  const x = (e.clientX - rect.left) * (cv.width / rect.width)
  const y = (e.clientY - rect.top) * (cv.height / rect.height)
  linePts.value.push({ x, y })
  redraw()
  if (linePts.value.length === 2) {
    line.value = [
      linePts.value[0].x / cv.width, linePts.value[0].y / cv.height,
      linePts.value[1].x / cv.width, linePts.value[1].y / cv.height,
    ]
  }
}

const clearLine = () => {
  linePts.value = []
  line.value = null
  if (file.value) drawFirstFrame(file.value)  // 重抽首帧清掉线
}

const run = async () => {
  running.value = true
  processed.value = 0
  total.value = 0
  clearOutput()
  try {
    const fd = new FormData()
    fd.append('file', file.value)
    fd.append('conf', conf.value)
    fd.append('imgsz', imgsz.value)
    if (line.value) fd.append('line', JSON.stringify(line.value))
    const res = await modelApi.trackVideo(modelId.value, fd)
    const jobId = res.data.jobId
    await poll(jobId)
  } catch (e) {
    ElMessage.error('追踪启动失败')
    running.value = false
  }
}

const poll = (jobId) => new Promise((resolve) => {
  pollTimer = setInterval(async () => {
    try {
      const res = await modelApi.videoProgress(modelId.value, jobId)
      const d = res.data
      processed.value = d.processed
      total.value = d.total
      if (d.status === 'done') {
        clearInterval(pollTimer); pollTimer = null
        stats.value = d.stats
        // outputVideo 返回 Blob，用 createObjectURL 得到可播放 URL（与视频检测页一致）
        const blob = await modelApi.outputVideo(d.stats.output)
        blobUrl = URL.createObjectURL(blob)
        resultUrl.value = blobUrl
        running.value = false
        resolve()
      }
    } catch (e) {
      clearInterval(pollTimer); pollTimer = null
      ElMessage.error('追踪失败')
      running.value = false
      resolve()
    }
  }, 1000)
})

const download = () => {
  const a = document.createElement('a')
  a.href = resultUrl.value
  a.download = stats.value.output || 'track.mp4'
  a.click()
}

const clearAll = () => {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
  clearOutput()
  file.value = null
  clearLine()
  processed.value = 0
  total.value = 0
  running.value = false
}

onMounted(loadModels)
onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer)
  if (blobUrl) URL.revokeObjectURL(blobUrl)
})
</script>

<style scoped>
.cfg-card { margin-bottom: 12px; }
.hint, .line-tip { font-size: 13px; color: #5a6b87; margin-top: 8px; }
.meta { margin-left: 10px; color: #67c23a; }
.frame-box { margin-top: 10px; }
.frame-canvas { max-width: 100%; border: 1px solid #e4e7ed; border-radius: 6px; cursor: crosshair; }
.progress-box { padding: 22px 4px; }
.progress-title { font-weight: 600; color: #3a4a63; margin-bottom: 12px; }
.res-title { display: flex; align-items: center; gap: 12px; font-weight: 600; color: #3a4a63; margin-bottom: 12px; }
.player { width: 100%; max-height: 480px; background: #000; border-radius: 6px; }
.stats { display: flex; gap: 10px; margin: 12px 0; }
.cls-table { margin-top: 8px; max-width: 400px; }
</style>
