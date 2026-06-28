<template>
  <div>
    <el-card shadow="never" class="cfg-card">
      <el-form :inline="true">
        <el-form-item label="检测模型">
          <el-select v-model="detId" placeholder="选择检测模型" style="width: 200px">
            <el-option v-for="m in detModels" :key="m.id" :label="`${m.modelName}`" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="识别模型">
          <el-select v-model="recId" placeholder="选择识别模型" style="width: 200px">
            <el-option v-for="m in recModels" :key="m.id" :label="`${m.modelName}`" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-upload :show-file-list="false" :auto-upload="false" :on-change="onPick" accept="image/*">
            <el-button :icon="UploadFilled">选择图片</el-button>
          </el-upload>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :icon="Document" :loading="running" :disabled="!detId || !recId || !file" @click="run">开始识别</el-button>
          <el-button :icon="Refresh" @click="clearAll">清空</el-button>
        </el-form-item>
      </el-form>
      <el-alert v-if="!detModels.length || !recModels.length" type="warning" :closable="false"
                title="需各一个 RapidOCR 检测(text-detection) 与 识别(text-recognition) 模型；请到「模型管理」设库=rapidocr 并拉取。" />
    </el-card>

    <el-card shadow="never">
      <div v-if="running" class="progress-box">
        <div class="progress-title">识别中…（CPU 推理，请稍候）</div>
      </div>
      <el-empty v-else-if="!previewSrc" description="选择模型与图片后开始识别" />
      <div v-else class="grid">
        <div class="col">
          <div class="col-title">检测框</div>
          <div class="img-box stage">
            <img ref="imgEl" :src="previewSrc" class="stage-img" @load="draw" />
            <canvas ref="cv" class="stage-canvas"></canvas>
          </div>
        </div>
        <div class="col">
          <div class="col-title">
            识别结果（{{ count }} 行）
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
import { ref, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { UploadFilled, Document, Refresh, Download, CopyDocument } from '@element-plus/icons-vue'
import { modelApi } from '../../../api/ai'

const allModels = ref([])
const detId = ref(null)
const recId = ref(null)
const file = ref(null)
const previewSrc = ref('')
const running = ref(false)
const done = ref(false)
const text = ref('')
const count = ref(0)
const lines = ref([])
const imgEl = ref(null)
const cv = ref(null)

const detModels = computed(() => allModels.value.filter((m) => m.task === 'text-detection'))
const recModels = computed(() => allModels.value.filter((m) => m.task === 'text-recognition'))

const loadModels = async () => {
  try {
    const res = await modelApi.list({ pageNum: 1, pageSize: 100 })
    allModels.value = (res.data.rows || []).filter(
      (m) => m.library === 'rapidocr' && m.filePath && m.status === '0')
    if (detModels.value.length && !detId.value) detId.value = detModels.value[0].id
    if (recModels.value.length && !recId.value) recId.value = recModels.value[0].id
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
  text.value = ''; count.value = 0; lines.value = []; done.value = false
}

const run = async () => {
  running.value = true; done.value = false; text.value = ''; lines.value = []
  try {
    const fd = new FormData()
    fd.append('file', file.value)
    const res = await modelApi.paddleOcr(detId.value, recId.value, fd)
    text.value = res.data.text || ''
    count.value = res.data.count || 0
    lines.value = res.data.lines || []
    done.value = true
    await nextTick(); draw()
  } catch (e) {
    ElMessage.error('PaddleOCR 识别失败')
  } finally {
    running.value = false
  }
}

const draw = () => {
  const img = imgEl.value, canvas = cv.value
  if (!img || !canvas || !img.naturalWidth) return
  canvas.width = img.naturalWidth
  canvas.height = img.naturalHeight
  canvas.style.left = `${img.offsetLeft}px`
  canvas.style.top = `${img.offsetTop}px`
  canvas.style.width = `${img.offsetWidth}px`
  canvas.style.height = `${img.offsetHeight}px`
  const ctx = canvas.getContext('2d')
  ctx.clearRect(0, 0, canvas.width, canvas.height)
  ctx.strokeStyle = '#67c23a'
  ctx.lineWidth = Math.max(2, canvas.width / 500)
  for (const ln of lines.value) {
    const b = ln.box
    if (!b || b.length < 4) continue
    ctx.beginPath()
    ctx.moveTo(b[0][0], b[0][1])
    for (let i = 1; i < b.length; i++) ctx.lineTo(b[i][0], b[i][1])
    ctx.closePath()
    ctx.stroke()
  }
}

const copyText = async () => {
  try { await navigator.clipboard.writeText(text.value); ElMessage.success('已复制') }
  catch (e) { ElMessage.error('复制失败') }
}

const downloadTxt = () => {
  const blob = new Blob([text.value], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = `paddleocr_${Date.now()}.txt`; a.click()
  URL.revokeObjectURL(url)
}

const clearAll = () => {
  if (previewSrc.value) URL.revokeObjectURL(previewSrc.value)
  file.value = null; previewSrc.value = ''; text.value = ''; count.value = 0; lines.value = []; done.value = false
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
.stage { position: relative; }
.stage-img { max-width: 100%; max-height: 100%; object-fit: contain; display: block; }
.stage-canvas { position: absolute; pointer-events: none; }
</style>
