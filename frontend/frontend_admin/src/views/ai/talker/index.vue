<template>
  <div>
    <el-card shadow="never" class="cfg-card">
      <el-form :inline="true">
        <el-form-item label="模型分类">
          <el-select v-model="category" placeholder="全部分类" clearable style="width: 150px" @change="onCategoryChange">
            <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="数字人模型">
          <el-select v-model="modelId" placeholder="选择模型" style="width: 240px">
            <el-option
              v-for="m in filteredModels"
              :key="m.id"
              :label="`${m.modelName}（${m.category || '未分类'}）`"
              :value="m.id"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <el-alert
        v-if="!modelOptions.length"
        type="warning"
        :closable="false"
        title="暂无可用数字人模型：请到「模型管理」新增 Linly-Talker 模型并拉取权重。"
      />
      <el-alert
        v-else
        type="info"
        :closable="false"
        show-icon
        title="数字人合成为 GPU 重型任务：需 CUDA 版 torch + SadTalker 运行环境。当前为脚手架，CPU 环境暂未启用生成。"
      />
    </el-card>

    <el-card shadow="never">
      <div class="grid">
        <div class="col">
          <div class="col-title">人像图片</div>
          <el-upload :show-file-list="false" :auto-upload="false" :on-change="onPickImage" accept="image/*">
            <div class="drop">
              <el-image v-if="imageSrc" :src="imageSrc" fit="contain" class="thumb" />
              <div v-else class="drop-tip"><el-icon><Picture /></el-icon><span>点击选择人像</span></div>
            </div>
          </el-upload>
        </div>
        <div class="col">
          <div class="col-title">驱动音频</div>
          <el-upload :show-file-list="false" :auto-upload="false" :on-change="onPickAudio" accept="audio/*">
            <el-button :icon="UploadFilled">选择音频</el-button>
          </el-upload>
          <audio v-if="audioSrc" :src="audioSrc" controls class="player" />
        </div>
      </div>

      <div class="bar">
        <el-button type="primary" :icon="VideoCamera" :loading="running" :disabled="!modelId || !imageFile || !audioFile" @click="run">开始合成</el-button>
        <el-button :icon="Refresh" @click="clearAll">清空</el-button>
      </div>

      <div v-if="running" class="progress-box">
        <div class="progress-title">合成中…{{ total ? ` ${processed}/${total} 帧` : '' }}</div>
        <el-progress :percentage="percent" :stroke-width="18" :text-inside="true" :status="percent >= 100 ? 'success' : ''" />
      </div>

      <el-alert v-if="errorMsg" type="error" :closable="false" :title="errorMsg" class="err" />

      <div v-if="resultUrl" class="out">
        <div class="col-title">合成结果</div>
        <video :src="resultUrl" controls class="result-video" />
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { Picture, UploadFilled, VideoCamera, Refresh } from '@element-plus/icons-vue'

import { modelApi } from '../../../api/ai'

const modelOptions = ref([])
const modelId = ref(null)
const category = ref('')
const imageFile = ref(null)
const audioFile = ref(null)
const imageSrc = ref('')
const audioSrc = ref('')

const running = ref(false)
const processed = ref(0)
const total = ref(0)
const errorMsg = ref('')
const resultUrl = ref('')
let timer = null

const percent = computed(() => (total.value ? Math.floor((processed.value / total.value) * 100) : (running.value ? 5 : 0)))

const categories = computed(() => [...new Set(modelOptions.value.map((m) => m.category).filter(Boolean))])
const filteredModels = computed(() =>
  category.value ? modelOptions.value.filter((m) => m.category === category.value) : modelOptions.value
)
const onCategoryChange = () => {
  modelId.value = filteredModels.value[0]?.id || null
}

const loadModels = async () => {
  const res = await modelApi.list({ pageNum: 1, pageSize: 100 })
  modelOptions.value = (res.data.rows || []).filter(
    (m) => m.library === 'linly' && m.task === 'talking-head' && m.filePath && m.status === '0'
  )
  if (modelOptions.value.length && !modelId.value) modelId.value = modelOptions.value[0].id
}

const onPickImage = (uploadFile) => {
  const raw = uploadFile.raw
  if (!raw || !raw.type.startsWith('image/')) { ElMessage.error('请选择图片'); return }
  imageFile.value = raw
  if (imageSrc.value) URL.revokeObjectURL(imageSrc.value)
  imageSrc.value = URL.createObjectURL(raw)
}
const onPickAudio = (uploadFile) => {
  const raw = uploadFile.raw
  if (!raw || !raw.type.startsWith('audio/')) { ElMessage.error('请选择音频'); return }
  audioFile.value = raw
  if (audioSrc.value) URL.revokeObjectURL(audioSrc.value)
  audioSrc.value = URL.createObjectURL(raw)
}

const stopPoll = () => { if (timer) { clearInterval(timer); timer = null } }

const run = async () => {
  errorMsg.value = ''
  if (resultUrl.value) { URL.revokeObjectURL(resultUrl.value); resultUrl.value = '' }
  running.value = true
  processed.value = 0
  total.value = 0
  try {
    const fd = new FormData()
    fd.append('image', imageFile.value)
    fd.append('audio', audioFile.value)
    const res = await modelApi.talkingHead(modelId.value, fd)
    const jobId = res.data.jobId
    timer = setInterval(() => poll(jobId), 1200)
  } catch (e) {
    running.value = false
    errorMsg.value = e?.response?.data?.message || '启动失败'
  }
}

const poll = async (jobId) => {
  try {
    const res = await modelApi.talkingProgress(modelId.value, jobId)
    const d = res.data
    processed.value = d.processed || 0
    total.value = d.total || 0
    if (d.status === 'done') {
      stopPoll()
      running.value = false
      const blob = await modelApi.outputVideo(d.output)
      resultUrl.value = URL.createObjectURL(blob.data)
    }
  } catch (e) {
    stopPoll()
    running.value = false
    errorMsg.value = e?.response?.data?.message || '合成失败'
  }
}

const clearAll = () => {
  stopPoll()
  running.value = false
  errorMsg.value = ''
  if (imageSrc.value) URL.revokeObjectURL(imageSrc.value)
  if (audioSrc.value) URL.revokeObjectURL(audioSrc.value)
  if (resultUrl.value) URL.revokeObjectURL(resultUrl.value)
  imageFile.value = null
  audioFile.value = null
  imageSrc.value = ''
  audioSrc.value = ''
  resultUrl.value = ''
}

onMounted(loadModels)
onBeforeUnmount(() => {
  stopPoll()
  if (imageSrc.value) URL.revokeObjectURL(imageSrc.value)
  if (audioSrc.value) URL.revokeObjectURL(audioSrc.value)
  if (resultUrl.value) URL.revokeObjectURL(resultUrl.value)
})
</script>

<style scoped>
.cfg-card {
  margin-bottom: 12px;
}
.grid {
  display: flex;
  gap: 24px;
}
.col {
  flex: 1 1 50%;
  min-width: 0;
}
.col-title {
  font-weight: 600;
  color: #3a4a63;
  margin-bottom: 8px;
}
.drop {
  width: 100%;
  height: 240px;
  border: 1px dashed #c0c4cc;
  border-radius: 8px;
  background: #f4f6fb;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}
.thumb {
  max-width: 100%;
  max-height: 100%;
}
.drop-tip {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  color: #909399;
  font-size: 14px;
}
.drop-tip .el-icon {
  font-size: 32px;
}
.player {
  display: block;
  height: 36px;
  margin-top: 12px;
}
.bar {
  margin: 16px 0;
  display: flex;
  gap: 12px;
}
.progress-box {
  margin: 12px 0;
}
.progress-title {
  font-weight: 600;
  color: #3a4a63;
  margin-bottom: 12px;
}
.err {
  margin-top: 12px;
}
.out {
  margin-top: 16px;
}
.result-video {
  width: 100%;
  max-height: 420px;
  border-radius: 8px;
  background: #000;
}
</style>
