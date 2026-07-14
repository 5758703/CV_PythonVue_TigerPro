<template>
  <div>
    <el-card shadow="never" class="cfg-card">
      <el-form :inline="true">
        <el-form-item label="模型分类">
          <el-select v-model="category" placeholder="全部分类" clearable style="width: 160px" @change="onCategoryChange">
            <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="检测模型">
          <el-select v-model="modelId" placeholder="选择模型" style="width: 220px">
            <el-option
              v-for="m in filteredModels"
              :key="m.id"
              :label="`${m.modelName}（${m.category || '未分类'}）`"
              :value="m.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="置信度">
          <el-slider v-model="conf" :min="0.05" :max="0.95" :step="0.05" style="width: 160px" />
        </el-form-item>
        <el-form-item>
          <el-upload :show-file-list="false" :auto-upload="false" :on-change="onPick" accept="video/*">
            <el-button :icon="UploadFilled">选择视频</el-button>
          </el-upload>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :icon="VideoPlay" :loading="detecting" :disabled="!modelId || !file" @click="detect">开始检测</el-button>
          <el-button :icon="Refresh" @click="clearAll">清空</el-button>
        </el-form-item>
      </el-form>

      <div v-if="fileName" class="picked">
        <el-icon><VideoCamera /></el-icon>
        <span class="pk-name">{{ fileName }}</span>
        <template v-if="videoInfo">
          <el-tag size="small" type="info" effect="plain">时长 {{ fmtDuration(videoInfo.duration) }}</el-tag>
          <el-tag size="small" type="info" effect="plain">{{ videoInfo.width }}×{{ videoInfo.height }}</el-tag>
          <el-tag size="small" type="info" effect="plain">{{ fmtSize(videoInfo.size) }}</el-tag>
        </template>
      </div>
      <el-alert
        v-if="!modelOptions.length"
        type="warning"
        :closable="false"
        title="暂无可用模型：请先到「模型管理」上传或拉取权重，并保持启用状态。"
      />
    </el-card>

    <el-card v-if="previewUrl" shadow="never" class="cfg-card">
      <div class="preview-header">
        <div class="preview-title">原视频预览</div>
        <div class="video-rotate-bar">
          <span class="rotate-label">旋转</span>
          <el-button-group size="small">
            <el-button :icon="RefreshLeft" @click="rotatePreview(-90)">左转 90°</el-button>
            <el-button :icon="RefreshRight" @click="rotatePreview(90)">右转 90°</el-button>
            <el-button :disabled="!previewRotation" @click="previewRotation = 0">重置</el-button>
          </el-button-group>
          <el-tag v-if="previewRotation" size="small" type="info" effect="plain">{{ previewRotation }}°</el-tag>
        </div>
      </div>
      <div class="video-wrap">
        <video :src="previewUrl" controls class="result-video" :style="videoRotateStyle(previewRotation)" />
      </div>
    </el-card>

    <el-card shadow="never">
      <div v-if="detecting" class="progress-box">
        <div class="progress-title">逐帧检测中… {{ processed }} / {{ total || '?' }} 帧 · 预计剩余 {{ etaText }}</div>
        <el-progress :percentage="percent" :stroke-width="20" :text-inside="true" :status="percent >= 100 ? 'success' : ''" />
        <div class="progress-hint">输出为 H.264 编码，完成后可在线播放；处理期间请勿离开页面。</div>
      </div>

      <el-empty v-else-if="!result" description="选择模型与视频后开始检测" />

      <div v-else>
        <div class="preview-header">
          <div class="preview-title">检测结果视频</div>
          <div class="video-rotate-bar">
            <span class="rotate-label">旋转</span>
            <el-button-group size="small">
              <el-button :icon="RefreshLeft" @click="rotateOutput(-90)">左转 90°</el-button>
              <el-button :icon="RefreshRight" @click="rotateOutput(90)">右转 90°</el-button>
              <el-button :disabled="!outputRotation" @click="outputRotation = 0">重置</el-button>
            </el-button-group>
            <el-tag v-if="outputRotation" size="small" type="info" effect="plain">{{ outputRotation }}°</el-tag>
          </div>
        </div>
        <div class="video-wrap">
          <video v-if="outputUrl" :src="outputUrl" controls class="result-video" :style="videoRotateStyle(outputRotation)" />
        </div>

        <div class="stat-row">
          <el-statistic title="总帧数" :value="result.frames" />
          <el-statistic title="检出目标总数" :value="result.totalDetections" />
          <el-statistic title="帧率(FPS)" :value="result.fps" />
          <el-statistic title="分辨率" :value="`${result.width}×${result.height}`" />
          <el-statistic
            v-if="result.rocketTelemetry"
            title="平均下降速度"
            :value="result.rocketTelemetry.avgDescentSpeed"
            suffix="米/秒"
          />
          <el-statistic
            v-if="result.rocketTelemetry"
            title="最大下降速度"
            :value="result.rocketTelemetry.maxDescentSpeed"
            suffix="米/秒"
          />
          <el-button type="primary" :icon="Download" @click="downloadResult">下载结果视频</el-button>
        </div>

        <el-table :data="classRows" size="small" border class="cls-table">
          <el-table-column type="index" label="#" width="56" />
          <el-table-column prop="name" label="目标类别" min-width="160" />
          <el-table-column prop="count" label="累计检出（帧次）" min-width="160" />
        </el-table>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { UploadFilled, VideoPlay, VideoCamera, Refresh, Download, RefreshLeft, RefreshRight } from '@element-plus/icons-vue'

import { modelApi } from '../../../api/ai'

const normalizeRotation = (deg) => ((deg % 360) + 360) % 360
const isPortraitRotation = (deg) => deg === 90 || deg === 270
const videoRotateStyle = (deg) => ({
  transform: deg ? `rotate(${deg}deg)` : undefined,
  transformOrigin: 'center center',
  transition: 'transform 0.25s ease',
  maxWidth: isPortraitRotation(deg) ? '520px' : '100%',
  maxHeight: isPortraitRotation(deg) ? '80vh' : '520px',
})

const modelOptions = ref([])
const modelId = ref(null)
const category = ref('')
const conf = ref(0.25)
const file = ref(null)
const fileName = ref('')
const videoInfo = ref(null)
const previewUrl = ref('')   // 选中视频的原视频回放 URL
const previewRotation = ref(0)
const outputRotation = ref(0)

const rotatePreview = (delta) => { previewRotation.value = normalizeRotation(previewRotation.value + delta) }
const rotateOutput = (delta) => { outputRotation.value = normalizeRotation(outputRotation.value + delta) }

const detecting = ref(false)
const result = ref(null)
const outputUrl = ref('')
const processed = ref(0)
const total = ref(0)

let pollTimer = null
let startTime = 0

const percent = computed(() => {
  if (total.value > 0) return Math.min(99, Math.floor((processed.value / total.value) * 100))
  return processed.value > 0 ? 50 : 0
})

const etaText = computed(() => {
  // 依赖 processed（每次轮询变化）触发重算
  if (!detecting.value || processed.value <= 0 || total.value <= 0) return '计算中…'
  const elapsed = (Date.now() - startTime) / 1000
  const remain = (elapsed / processed.value) * (total.value - processed.value)
  return fmtEta(remain)
})

const fmtEta = (sec) => {
  if (!isFinite(sec) || sec < 0) return '--'
  const s = Math.round(sec)
  if (s < 60) return `${s} 秒`
  const m = Math.floor(s / 60)
  return `${m} 分 ${s % 60} 秒`
}

const categories = computed(() => [...new Set(modelOptions.value.map((m) => m.category).filter(Boolean))])
const filteredModels = computed(() =>
  category.value ? modelOptions.value.filter((m) => m.category === category.value) : modelOptions.value
)
const onCategoryChange = () => {
  modelId.value = filteredModels.value[0]?.id || null
}

const classRows = computed(() =>
  result.value
    ? Object.entries(result.value.classCounts || {})
        .map(([name, count]) => ({ name, count }))
        .sort((a, b) => b.count - a.count)
    : []
)

const fmtDuration = (sec) => {
  if (!sec || !isFinite(sec)) return '--'
  const s = Math.round(sec)
  const m = Math.floor(s / 60)
  const r = s % 60
  return m > 0 ? `${m}分${r}秒` : `${r}秒`
}
const fmtSize = (bytes) => {
  if (!bytes) return '0 B'
  const u = ['B', 'KB', 'MB', 'GB']
  let i = 0
  let n = bytes
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++ }
  return `${n.toFixed(i ? 1 : 0)} ${u[i]}`
}

const loadModels = async () => {
  const res = await modelApi.list({ pageNum: 1, pageSize: 100 })
  modelOptions.value = (res.data.rows || []).filter(
    (m) => m.task === 'object-detection' && m.filePath && m.status === '0'
  )
  if (modelOptions.value.length && !modelId.value) modelId.value = modelOptions.value[0].id
}

const onPick = (uploadFile) => {
  const raw = uploadFile.raw
  if (!raw || !raw.type.startsWith('video/')) {
    ElMessage.error('请选择视频文件')
    return
  }
  file.value = raw
  fileName.value = raw.name
  videoInfo.value = null
  clearOutput()
  result.value = null
  previewRotation.value = 0
  outputRotation.value = 0
  // 原视频回放 + 浏览器端读取视频元信息（时长/分辨率），复用同一 objectURL
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = URL.createObjectURL(raw)
  const v = document.createElement('video')
  v.preload = 'metadata'
  v.onloadedmetadata = () => {
    videoInfo.value = { duration: v.duration, width: v.videoWidth, height: v.videoHeight, size: raw.size }
  }
  v.src = previewUrl.value
}

const clearOutput = () => {
  if (outputUrl.value) URL.revokeObjectURL(outputUrl.value)
  outputUrl.value = ''
}

const stopPoll = () => {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

const detect = async () => {
  detecting.value = true
  clearOutput()
  result.value = null
  outputRotation.value = 0
  processed.value = 0
  total.value = 0
  startTime = Date.now()
  try {
    const fd = new FormData()
    fd.append('file', file.value)
    fd.append('conf', conf.value)
    const res = await modelApi.detectVideo(modelId.value, fd)
    poll(res.data.jobId)
  } catch (e) {
    detecting.value = false
  }
}

const poll = (jobId) => {
  stopPoll()
  pollTimer = setInterval(async () => {
    try {
      const res = await modelApi.videoProgress(modelId.value, jobId)
      const d = res.data
      processed.value = d.processed || 0
      total.value = d.total || 0
      if (d.status === 'done') {
        stopPoll()
        result.value = d.stats
        const blob = await modelApi.outputVideo(d.stats.output)
        outputUrl.value = URL.createObjectURL(blob)
        detecting.value = false
      }
    } catch (e) {
      // 进度接口返回错误（如检测失败）→ 拦截器已提示
      stopPoll()
      detecting.value = false
    }
  }, 700)
}

const clearAll = () => {
  stopPoll()
  clearOutput()
  if (previewUrl.value) { URL.revokeObjectURL(previewUrl.value); previewUrl.value = '' }
  file.value = null
  fileName.value = ''
  videoInfo.value = null
  previewRotation.value = 0
  outputRotation.value = 0
  result.value = null
  detecting.value = false
}

const downloadResult = () => {
  if (!outputUrl.value) return
  const a = document.createElement('a')
  a.href = outputUrl.value
  a.download = result.value.output || 'detection_result.mp4'
  a.click()
}

onMounted(loadModels)
onBeforeUnmount(() => {
  stopPoll()
  clearOutput()
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
})
</script>

<style scoped>
.cfg-card {
  margin-bottom: 12px;
}
.picked {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 4px 0 10px;
  font-size: 13px;
  color: #5a6b87;
}
.pk-name {
  font-weight: 600;
  color: #3a4a63;
}
.preview-title {
  font-weight: 600;
  color: #3a4a63;
}
.preview-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.video-rotate-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.rotate-label {
  font-size: 13px;
  color: #909399;
}
.progress-box {
  padding: 28px 8px;
}
.progress-title {
  font-weight: 600;
  color: #3a4a63;
  margin-bottom: 12px;
}
.progress-hint {
  margin-top: 10px;
  font-size: 12px;
  color: #909399;
}
.video-wrap {
  display: flex;
  justify-content: center;
  background: #0c1733;
  border-radius: 8px;
  padding: 8px;
}
.result-video {
  max-width: 100%;
  max-height: 520px;
  border-radius: 6px;
  object-fit: contain;
}
.stat-row {
  display: flex;
  align-items: center;
  gap: 32px;
  margin: 18px 0 6px;
  flex-wrap: wrap;
}
.cls-table {
  margin-top: 12px;
}
</style>
