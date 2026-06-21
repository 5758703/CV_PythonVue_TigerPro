<template>
  <div>
    <el-card shadow="never" class="cfg-card">
      <el-form :inline="true">
        <el-form-item label="模型分类">
          <el-select v-model="category" placeholder="全部分类" clearable style="width: 150px" @change="onCategoryChange">
            <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="分类模型">
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
          <el-upload :show-file-list="false" :auto-upload="false" :on-change="onPick" accept="image/*">
            <el-button :icon="UploadFilled">选择图片</el-button>
          </el-upload>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :icon="MagicStick" :loading="analyzing" :disabled="!modelId || !file" @click="analyze">开始分类</el-button>
          <el-button :icon="Refresh" @click="clearAll">清空</el-button>
        </el-form-item>
      </el-form>
      <div v-if="imageInfo" class="picked">
        <span class="pk-name">{{ file?.name }}</span>
        <el-tag size="small" type="info" effect="plain">{{ imageInfo.width }}×{{ imageInfo.height }}</el-tag>
        <el-tag size="small" type="info" effect="plain">{{ fmtSize(imageInfo.size) }}</el-tag>
      </div>
      <el-alert
        v-if="!modelOptions.length"
        type="warning"
        :closable="false"
        title="暂无可用分类模型：请到「模型管理」新增 transformers 图像分类模型（如 ViT）并拉取权重。"
      />
    </el-card>

    <el-card shadow="never">
      <div v-if="analyzing" class="progress-box">
        <div class="progress-title">分类中… 预计剩余 {{ etaText }}</div>
        <el-progress :percentage="percent" :stroke-width="18" :text-inside="true" :status="percent >= 100 ? 'success' : ''" />
        <div class="progress-hint">已用 {{ elapsedText }}</div>
      </div>
      <el-empty v-else-if="!previewSrc && !result" description="选择模型与图片后开始分类" />
      <div v-else class="grid">
        <div class="col-img">
          <div class="img-box">
            <el-image v-if="previewSrc" :src="previewSrc" :preview-src-list="[previewSrc]" fit="contain" />
          </div>
        </div>
        <div class="col-res">
          <template v-if="result">
            <el-alert :title="`Top-1：${result.top.label}（${(result.top.score * 100).toFixed(1)}%）`" type="success" :closable="false" />
            <div class="scores">
              <div v-for="r in result.results" :key="r.label" class="score-row">
                <span class="score-label" :title="r.label">{{ r.label }}</span>
                <el-progress :percentage="+(r.score * 100).toFixed(1)" :stroke-width="14" class="score-bar" />
              </div>
            </div>
          </template>
          <el-empty v-else :image-size="70" description="尚未分类" />
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { UploadFilled, MagicStick, Refresh } from '@element-plus/icons-vue'

import { modelApi } from '../../../api/ai'
import { useInferProgress } from '../../../composables/useInferProgress'

const modelOptions = ref([])
const modelId = ref(null)
const category = ref('')
const file = ref(null)
const previewSrc = ref('')
const result = ref(null)
const imageInfo = ref(null)

const { running: analyzing, percent, etaText, elapsedText, start, finish } = useInferProgress(modelId)

const fmtSize = (bytes) => {
  if (!bytes) return '0 B'
  const u = ['B', 'KB', 'MB', 'GB']
  let i = 0
  let n = bytes
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++ }
  return `${n.toFixed(i ? 1 : 0)} ${u[i]}`
}

const categories = computed(() => [...new Set(modelOptions.value.map((m) => m.category).filter(Boolean))])
const filteredModels = computed(() =>
  category.value ? modelOptions.value.filter((m) => m.category === category.value) : modelOptions.value
)
const onCategoryChange = () => {
  modelId.value = filteredModels.value[0]?.id || null
  result.value = null
}

const loadModels = async () => {
  const res = await modelApi.list({ pageNum: 1, pageSize: 100 })
  modelOptions.value = (res.data.rows || []).filter(
    (m) => m.library === 'transformers' && m.task === 'image-classification' && m.filePath && m.status === '0'
  )
  if (modelOptions.value.length && !modelId.value) modelId.value = modelOptions.value[0].id
}

const onPick = (uploadFile) => {
  const raw = uploadFile.raw
  if (!raw || !raw.type.startsWith('image/')) {
    ElMessage.error('请选择图片文件')
    return
  }
  file.value = raw
  if (previewSrc.value) URL.revokeObjectURL(previewSrc.value)
  previewSrc.value = URL.createObjectURL(raw)
  result.value = null
  imageInfo.value = { size: raw.size, width: 0, height: 0 }
  const im = new Image()
  im.onload = () => { imageInfo.value = { size: raw.size, width: im.naturalWidth, height: im.naturalHeight } }
  im.src = previewSrc.value
}

const analyze = async () => {
  start()
  try {
    const fd = new FormData()
    fd.append('file', file.value)
    fd.append('topK', 5)
    const res = await modelApi.classifyImage(modelId.value, fd)
    result.value = res.data
  } finally {
    finish()
  }
}

const clearAll = () => {
  if (previewSrc.value) URL.revokeObjectURL(previewSrc.value)
  file.value = null
  previewSrc.value = ''
  result.value = null
  imageInfo.value = null
}

onMounted(loadModels)
onBeforeUnmount(() => {
  if (previewSrc.value) URL.revokeObjectURL(previewSrc.value)
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
.grid {
  display: flex;
  gap: 16px;
}
.col-img {
  flex: 1 1 50%;
  min-width: 0;
}
.col-res {
  flex: 1 1 50%;
  min-width: 0;
}
.img-box {
  background: #f4f6fb;
  border-radius: 8px;
  height: 360px;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}
.img-box :deep(.el-image) {
  max-width: 100%;
  max-height: 100%;
}
.scores {
  margin-top: 16px;
}
.score-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}
.score-label {
  width: 160px;
  text-align: right;
  color: #3a4a63;
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.score-bar {
  flex: 1;
}
</style>
