<template>
  <div>
    <el-card shadow="never" class="cfg-card">
      <el-form :inline="true">
        <el-form-item label="模型分类">
          <el-select v-model="category" placeholder="全部分类" clearable style="width: 150px" @change="onCategoryChange">
            <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="OCR 模型">
          <el-select v-model="modelId" placeholder="选择 OCR 模型" style="width: 220px">
            <el-option v-for="m in filteredModels" :key="m.id"
                       :label="`${m.modelName}（${m.category || '未分类'}）`" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="格式化输出">
          <el-switch v-model="formatted" />
        </el-form-item>
        <el-form-item>
          <el-upload :show-file-list="false" :auto-upload="false" :on-change="onPick" accept="image/*">
            <el-button :icon="UploadFilled">选择图片</el-button>
          </el-upload>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :icon="Document" :loading="running" :disabled="!modelId || !file" @click="run">开始识别</el-button>
          <el-button :icon="Refresh" @click="clearAll">清空</el-button>
        </el-form-item>
      </el-form>
      <el-alert v-if="!modelOptions.length" type="warning" :closable="false"
                title="暂无可用模型：文字识别需 task=ocr 的模型（如 GOT-OCR2），请到「模型管理」新增并拉取权重。" />
    </el-card>

    <el-card shadow="never">
      <div v-if="running" class="progress-box">
        <div class="progress-title">识别中…（CPU 推理较慢，请稍候）</div>
      </div>

      <el-empty v-else-if="!previewSrc" description="选择模型与图片后开始识别" />

      <div v-else class="grid">
        <div class="col">
          <div class="col-title">原图</div>
          <div class="img-box">
            <el-image v-if="previewSrc" :src="previewSrc" :preview-src-list="[previewSrc]" fit="contain" />
          </div>
        </div>
        <div class="col">
          <div class="col-title">
            识别结果（{{ chars }} 字）
            <span>
              <el-button v-if="text" link type="primary" :icon="CopyDocument" @click="copyText">复制</el-button>
              <el-button v-if="text" link type="primary" :icon="Download" @click="downloadTxt">下载 .txt</el-button>
            </span>
          </div>
          <el-alert v-if="done && !text" type="info" :closable="false" title="未识别到文字" style="margin-bottom: 8px" />
          <el-input v-model="text" type="textarea" :rows="16" readonly placeholder="识别文本将显示在此" />
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { UploadFilled, Document, Refresh, Download, CopyDocument } from '@element-plus/icons-vue'
import { modelApi } from '../../../api/ai'

const modelOptions = ref([])
const modelId = ref(null)
const category = ref('')
const formatted = ref(false)
const file = ref(null)
const previewSrc = ref('')
const running = ref(false)
const done = ref(false)
const text = ref('')
const chars = ref(0)

const categories = computed(() => [...new Set(modelOptions.value.map((m) => m.category).filter(Boolean))])
const filteredModels = computed(() =>
  category.value ? modelOptions.value.filter((m) => m.category === category.value) : modelOptions.value)
const onCategoryChange = () => { modelId.value = filteredModels.value[0]?.id || null }

const loadModels = async () => {
  try {
    const res = await modelApi.list({ pageNum: 1, pageSize: 100 })
    modelOptions.value = (res.data.rows || []).filter(
      (m) => m.library === 'transformers' && m.task === 'ocr' && m.filePath && m.status === '0')
    if (modelOptions.value.length && !modelId.value) modelId.value = modelOptions.value[0].id
  } catch (e) {
    ElMessage.error('加载模型列表失败')
  }
}

const onPick = (uploadFile) => {
  const raw = uploadFile.raw
  if (!raw || !raw.type.startsWith('image/')) { ElMessage.error('请选择图片文件'); return }
  file.value = raw
  if (previewSrc.value) URL.revokeObjectURL(previewSrc.value)
  previewSrc.value = URL.createObjectURL(raw)
  text.value = ''
  chars.value = 0
  done.value = false
}

const run = async () => {
  running.value = true
  done.value = false
  text.value = ''
  try {
    const fd = new FormData()
    fd.append('file', file.value)
    fd.append('formatted', formatted.value ? '1' : '0')
    const res = await modelApi.ocr(modelId.value, fd)
    text.value = res.data.text || ''
    chars.value = res.data.chars || 0
    done.value = true
  } catch (e) {
    ElMessage.error('文字识别失败')
  } finally {
    running.value = false
  }
}

const copyText = async () => {
  try {
    await navigator.clipboard.writeText(text.value)
    ElMessage.success('已复制')
  } catch (e) {
    ElMessage.error('复制失败')
  }
}

const downloadTxt = () => {
  const blob = new Blob([text.value], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `ocr_${Date.now()}.txt`
  a.click()
  URL.revokeObjectURL(url)
}

const clearAll = () => {
  if (previewSrc.value) URL.revokeObjectURL(previewSrc.value)
  file.value = null
  previewSrc.value = ''
  text.value = ''
  chars.value = 0
  done.value = false
}

onMounted(loadModels)
onBeforeUnmount(() => { if (previewSrc.value) URL.revokeObjectURL(previewSrc.value) })
</script>

<style scoped>
.cfg-card { margin-bottom: 12px; }
.progress-box { padding: 28px 8px; }
.progress-title { font-weight: 600; color: #3a4a63; }
.grid { display: flex; gap: 16px; }
.col { flex: 1 1 50%; min-width: 0; }
.col-title { display: flex; align-items: center; justify-content: space-between; font-weight: 600; color: #3a4a63; margin-bottom: 8px; }
.img-box { background: #f6f8fc; border: 1px solid #e4e7ed; border-radius: 8px; height: 420px; display: flex; align-items: center; justify-content: center; overflow: hidden; }
.img-box :deep(.el-image) { max-width: 100%; max-height: 100%; }
</style>
