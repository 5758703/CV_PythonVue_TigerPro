<template>
  <div>
    <el-card shadow="never" class="cfg-card">
      <el-form :inline="true">
        <el-form-item label="模式">
          <el-radio-group v-model="mode" @change="clearAll">
            <el-radio-button value="image">图片</el-radio-button>
            <el-radio-button value="video">视频</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="模型分类">
          <el-select v-model="category" placeholder="全部分类" clearable style="width: 150px" @change="onCategoryChange">
            <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="姿态模型">
          <el-select v-model="modelId" placeholder="选择 pose 模型" style="width: 220px">
            <el-option v-for="m in filteredModels" :key="m.id"
                       :label="`${m.modelName}（${m.category || '未分类'}）`" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="置信度">
          <el-slider v-model="conf" :min="0.05" :max="0.95" :step="0.05" style="width: 150px" />
        </el-form-item>
        <el-form-item>
          <el-upload :show-file-list="false" :auto-upload="false" :on-change="onPick" :accept="mode === 'image' ? 'image/*' : 'video/*'">
            <el-button :icon="UploadFilled">{{ mode === 'image' ? '选择图片' : '选择视频' }}</el-button>
          </el-upload>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :icon="VideoPlay" :loading="running" :disabled="!modelId || !file" @click="run">开始估计</el-button>
          <el-button :icon="Refresh" @click="clearAll">清空</el-button>
        </el-form-item>
      </el-form>
      <el-alert v-if="!modelOptions.length" type="warning" :closable="false"
                title="暂无可用模型：姿态估计需 task=pose-estimation 的 YOLO 模型，请到「模型管理」上传/拉取并启用。" />
    </el-card>

    <el-card shadow="never">
      <div v-if="running" class="progress-box">
        <div class="progress-title">
          {{ mode === 'video' ? `处理中… ${processed}/${total || '?'} 帧` : '估计中…' }}
        </div>
        <el-progress v-if="mode === 'video'" :percentage="percent" :stroke-width="18" :text-inside="true" :status="percent >= 100 ? 'success' : ''" />
      </div>

      <el-empty v-else-if="!resultImg && !resultUrl" description="选择模型与文件后开始估计" />

      <!-- 图片结果 -->
      <div v-else-if="mode === 'image' && resultImg">
        <div class="res-title">
          姿态结果（检测到 {{ poseCount }} 个人体姿态）
          <el-button link type="primary" :icon="Download" @click="downloadImg">下载结果图</el-button>
        </div>
        <el-alert v-if="poseCount === 0" type="info" :closable="false"
                  title="未检测到人体姿态（请确认所选为 pose 模型）" style="margin-bottom: 10px" />
        <el-image :src="resultImg" :preview-src-list="[resultImg]" fit="contain" class="result-img" />
      </div>

      <!-- 视频结果 -->
      <div v-else-if="mode === 'video' && resultUrl">
        <div class="res-title">
          姿态视频结果
          <el-button link type="primary" :icon="Download" @click="downloadVideo">下载视频</el-button>
        </div>
        <video :src="resultUrl" controls class="player" />
        <div class="stats">
          <el-tag type="success" effect="dark">帧数：{{ stats.frames }}</el-tag>
          <el-tag type="warning" effect="dark">累计人体数：{{ stats.totalPersons }}</el-tag>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { UploadFilled, VideoPlay, Refresh, Download } from '@element-plus/icons-vue'
import { modelApi } from '../../../api/ai'

const mode = ref('image')
const modelOptions = ref([])
const modelId = ref(null)
const category = ref('')
const conf = ref(0.25)
const file = ref(null)

const running = ref(false)
const processed = ref(0)
const total = ref(0)
const resultImg = ref('')      // 图片模式：data:image/jpeg;base64
const poseCount = ref(0)
const resultUrl = ref('')      // 视频模式：blob url
const stats = ref({})
let blobUrl = null
let pollTimer = null

const categories = computed(() => [...new Set(modelOptions.value.map((m) => m.category).filter(Boolean))])
const filteredModels = computed(() =>
  category.value ? modelOptions.value.filter((m) => m.category === category.value) : modelOptions.value)
const percent = computed(() => (total.value ? Math.min(100, Math.floor((processed.value / total.value) * 100)) : 0))

const onCategoryChange = () => { modelId.value = filteredModels.value[0]?.id || null }

const loadModels = async () => {
  try {
    const res = await modelApi.list({ pageNum: 1, pageSize: 100 })
    modelOptions.value = (res.data.rows || []).filter(
      (m) => m.library === 'ultralytics' && m.task === 'pose-estimation' && m.filePath && m.status === '0')
    if (modelOptions.value.length && !modelId.value) modelId.value = modelOptions.value[0].id
  } catch (e) {
    ElMessage.error('加载模型列表失败')
  }
}

const onPick = (uploadFile) => {
  const raw = uploadFile.raw
  const wantImage = mode.value === 'image'
  if (!raw || (wantImage ? !raw.type.startsWith('image/') : !raw.type.startsWith('video/'))) {
    ElMessage.error(wantImage ? '请选择图片文件' : '请选择视频文件')
    return
  }
  file.value = raw
  resultImg.value = ''
  clearVideoOut()
}

const run = async () => {
  if (mode.value === 'image') return runImage()
  return runVideo()
}

const runImage = async () => {
  running.value = true
  resultImg.value = ''
  try {
    const fd = new FormData()
    fd.append('file', file.value)
    fd.append('conf', conf.value)
    const res = await modelApi.pose(modelId.value, fd)
    const d = res.data
    poseCount.value = d.count
    resultImg.value = d.imageBase64 ? `data:image/jpeg;base64,${d.imageBase64}` : ''
  } catch (e) {
    ElMessage.error('姿态估计失败')
  } finally {
    running.value = false
  }
}

const runVideo = async () => {
  running.value = true
  processed.value = 0
  total.value = 0
  clearVideoOut()
  try {
    const fd = new FormData()
    fd.append('file', file.value)
    fd.append('conf', conf.value)
    const res = await modelApi.poseVideo(modelId.value, fd)
    await poll(res.data.jobId)
  } catch (e) {
    ElMessage.error('姿态估计启动失败')
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
        const blob = await modelApi.outputVideo(d.stats.output)
        blobUrl = URL.createObjectURL(blob)
        resultUrl.value = blobUrl
        running.value = false
        resolve()
      }
    } catch (e) {
      clearInterval(pollTimer); pollTimer = null
      ElMessage.error('姿态视频处理失败')
      running.value = false
      resolve()
    }
  }, 1000)
})

const downloadImg = () => {
  const a = document.createElement('a')
  a.href = resultImg.value
  a.download = `pose_${Date.now()}.jpg`
  a.click()
}

const downloadVideo = () => {
  const a = document.createElement('a')
  a.href = resultUrl.value
  a.download = stats.value.output || 'pose.mp4'
  a.click()
}

const clearVideoOut = () => {
  if (blobUrl) { URL.revokeObjectURL(blobUrl); blobUrl = null }
  resultUrl.value = ''
}

const clearAll = () => {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
  file.value = null
  resultImg.value = ''
  poseCount.value = 0
  clearVideoOut()
  stats.value = {}
  processed.value = 0
  total.value = 0
  running.value = false
}

onMounted(loadModels)
onBeforeUnmount(() => { if (pollTimer) clearInterval(pollTimer); clearVideoOut() })
</script>

<style scoped>
.cfg-card { margin-bottom: 12px; }
.progress-box { padding: 22px 4px; }
.progress-title { font-weight: 600; color: #3a4a63; margin-bottom: 12px; }
.res-title { display: flex; align-items: center; gap: 12px; font-weight: 600; color: #3a4a63; margin-bottom: 12px; }
.result-img { max-width: 100%; max-height: 560px; border: 1px solid #ebeef5; border-radius: 6px; }
.player { width: 100%; max-height: 480px; background: #000; border-radius: 6px; }
.stats { display: flex; gap: 10px; margin-top: 12px; }
</style>
