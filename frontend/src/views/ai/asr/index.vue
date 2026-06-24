<template>
  <div>
    <el-card shadow="never" class="cfg-card">
      <el-form :inline="true">
        <el-form-item label="模型分类">
          <el-select v-model="category" placeholder="全部分类" clearable style="width: 150px" @change="onCategoryChange">
            <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="语音模型">
          <el-select v-model="modelId" placeholder="选择模型" style="width: 240px">
            <el-option
              v-for="m in filteredModels"
              :key="m.id"
              :label="`${m.modelName}（${m.category || '未分类'}）`"
              :value="m.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-upload :show-file-list="false" :auto-upload="false" :on-change="onPick" accept="audio/*">
            <el-button :icon="UploadFilled">选择音频</el-button>
          </el-upload>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :icon="MagicStick" :loading="running" :disabled="!modelId || !file" @click="run">开始识别</el-button>
          <el-button :icon="Refresh" @click="clearAll">清空</el-button>
        </el-form-item>
      </el-form>
      <div v-if="audioInfo" class="picked">
        <span class="pk-name">{{ file?.name }}</span>
        <el-tag size="small" type="info" effect="plain">{{ fmtSize(audioInfo.size) }}</el-tag>
        <el-tag v-if="audioInfo.duration" size="small" type="info" effect="plain">{{ fmtDuration(audioInfo.duration) }}</el-tag>
        <audio v-if="audioSrc" :src="audioSrc" controls class="player" />
      </div>
      <el-alert
        v-if="!modelOptions.length"
        type="warning"
        :closable="false"
        title="暂无可用语音模型：请到「模型管理」新增 funasr 语音识别模型（如 SenseVoiceSmall）并拉取权重。"
      />
    </el-card>

    <el-card shadow="never">
      <div v-if="running" class="progress-box">
        <div class="progress-title">识别中… 预计剩余 {{ etaText }}</div>
        <el-progress :percentage="percent" :stroke-width="18" :text-inside="true" :status="percent >= 100 ? 'success' : ''" />
        <div class="progress-hint">已用 {{ elapsedText }}</div>
      </div>
      <el-empty v-else-if="!result" description="选择模型与音频后开始识别" />
      <div v-else class="result">
        <div class="tags">
          <el-tag v-if="result.language" type="primary" effect="plain">语言：{{ result.language }}</el-tag>
          <el-tag v-if="result.emotion" type="success" effect="plain">情感：{{ result.emotion }}</el-tag>
          <el-tag v-for="(ev, i) in result.events" :key="i" type="warning" effect="plain">事件：{{ ev }}</el-tag>
        </div>
        <div class="trans-title">
          转写文本
          <el-button v-if="result.text" link type="primary" :icon="CopyDocument" @click="copy">复制</el-button>
        </div>
        <div class="trans-box">{{ result.text || '（未识别到语音内容）' }}</div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { UploadFilled, MagicStick, Refresh, CopyDocument } from '@element-plus/icons-vue'

import { modelApi } from '../../../api/ai'
import { useInferProgress } from '../../../composables/useInferProgress'

const modelOptions = ref([])
const modelId = ref(null)
const category = ref('')
const file = ref(null)
const audioSrc = ref('')
const audioInfo = ref(null)
const result = ref(null)

const { running, percent, etaText, elapsedText, start, finish } = useInferProgress(modelId)

const fmtSize = (bytes) => {
  if (!bytes) return '0 B'
  const u = ['B', 'KB', 'MB', 'GB']
  let i = 0
  let n = bytes
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++ }
  return `${n.toFixed(i ? 1 : 0)} ${u[i]}`
}
const fmtDuration = (s) => {
  if (!s || !isFinite(s)) return ''
  const m = Math.floor(s / 60)
  const sec = Math.floor(s % 60)
  return `${m}:${String(sec).padStart(2, '0')}`
}

const categories = computed(() => [...new Set(modelOptions.value.map((m) => m.category).filter(Boolean))])
const filteredModels = computed(() =>
  category.value ? modelOptions.value.filter((m) => m.category === category.value) : modelOptions.value
)
const onCategoryChange = () => {
  modelId.value = filteredModels.value[0]?.id || null
  result.value = null
}

// 首选语音识别模型：Paraformer 中英（默认置顶并默认选中）
const PREFERRED_ASR_KEY = 'paraformer-zh'

const loadModels = async () => {
  const res = await modelApi.list({ pageNum: 1, pageSize: 100 })
  const rows = (res.data.rows || []).filter(
    (m) => (m.library === 'funasr' || m.library === 'funasr-onnx' || m.library === 'transformers') &&
      m.task === 'automatic-speech-recognition' && m.filePath && m.status === '0'
  )
  rows.sort((a, b) => (b.modelKey === PREFERRED_ASR_KEY) - (a.modelKey === PREFERRED_ASR_KEY))
  modelOptions.value = rows
  if (modelOptions.value.length && !modelId.value) modelId.value = modelOptions.value[0].id
}

const onPick = (uploadFile) => {
  const raw = uploadFile.raw
  if (!raw || !raw.type.startsWith('audio/')) {
    ElMessage.error('请选择音频文件')
    return
  }
  file.value = raw
  if (audioSrc.value) URL.revokeObjectURL(audioSrc.value)
  audioSrc.value = URL.createObjectURL(raw)
  result.value = null
  audioInfo.value = { size: raw.size, duration: 0 }
  const a = new Audio()
  a.onloadedmetadata = () => { audioInfo.value = { size: raw.size, duration: a.duration } }
  a.src = audioSrc.value
}

const run = async () => {
  start()
  try {
    const fd = new FormData()
    fd.append('file', file.value)
    const res = await modelApi.transcribe(modelId.value, fd)
    result.value = res.data
  } finally {
    finish()
  }
}

const copy = async () => {
  await navigator.clipboard.writeText(result.value.text)
  ElMessage.success('已复制')
}

const clearAll = () => {
  if (audioSrc.value) URL.revokeObjectURL(audioSrc.value)
  file.value = null
  audioSrc.value = ''
  audioInfo.value = null
  result.value = null
}

onMounted(loadModels)
onBeforeUnmount(() => {
  if (audioSrc.value) URL.revokeObjectURL(audioSrc.value)
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
  margin-top: 8px;
  font-size: 13px;
  color: #5a6b87;
}
.pk-name {
  font-weight: 600;
  color: #3a4a63;
}
.player {
  height: 32px;
  margin-left: 8px;
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
.result {
  padding: 4px;
}
.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 14px;
}
.trans-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 600;
  color: #3a4a63;
  margin-bottom: 8px;
}
.trans-box {
  padding: 14px 16px;
  border-radius: 8px;
  background: #f4f6fb;
  line-height: 1.9;
  font-size: 15px;
  color: #1f2d3d;
  min-height: 80px;
  white-space: pre-wrap;
}
</style>
