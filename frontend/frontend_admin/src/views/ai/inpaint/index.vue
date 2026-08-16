<template>
  <div class="inpaint-root">
    <el-card shadow="never" class="cfg-card">
      <el-form :inline="true">
        <el-form-item label="修复模型">
          <el-select v-model="modelId" placeholder="选择 LaMa 模型" style="width: 300px">
            <el-option
              v-for="m in modelOptions"
              :key="m.id"
              :label="`${m.modelName}（${m.library || m.modelKey}）`"
              :value="m.id"
            />
          </el-select>
          <el-button link type="primary" style="margin-left: 6px" @click="loadModels">刷新</el-button>
        </el-form-item>
        <el-form-item label="笔刷">
          <el-slider v-model="brushSize" :min="4" :max="80" :step="2" style="width: 140px" />
          <span class="brush-n">{{ brushSize }}px</span>
        </el-form-item>
        <el-form-item label="遮罩外扩">
          <el-checkbox v-model="expandMask">启用</el-checkbox>
          <el-input-number
            v-model="dilatePx"
            :min="1"
            :max="64"
            :step="1"
            :disabled="!expandMask"
            controls-position="right"
            style="width: 110px; margin-left: 8px"
          />
          <span class="brush-n">px</span>
        </el-form-item>
        <el-form-item>
          <el-upload :show-file-list="false" :auto-upload="false" :on-change="onPick" accept="image/*">
            <el-button :icon="UploadFilled">选择图片</el-button>
          </el-upload>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :icon="MagicStick" :loading="running" :disabled="!canRun" @click="run">
            开始修复
          </el-button>
          <el-button :disabled="!hasMask" @click="clearMask">清除遮罩</el-button>
          <el-button :icon="Refresh" @click="clearAll">清空</el-button>
        </el-form-item>
      </el-form>
      <el-alert
        v-if="!modelOptions.length"
        type="warning"
        :closable="false"
        title="暂无 LaMa 模型：请到「模型管理」拉取 inpainting-lama（library=opencv-lama）。"
      />
      <p class="hint">
        OpenCV Zoo LaMa：涂抹待修复区域（红笔仅预览）。建议勾选「遮罩外扩」，涂主体时自动扩边，减轻毛发/软边残留。外扩越大越干净，过大可能误修背景。
      </p>
    </el-card>

    <el-card v-if="running" shadow="never" class="cfg-card">
      <div class="progress-title">修复中… CPU 首次加载约数十秒</div>
      <el-progress :percentage="percent" :stroke-width="16" :text-inside="true" striped striped-flow />
      <div class="progress-hint">已用 {{ elapsedText }}</div>
    </el-card>

    <el-row v-if="originUrl || resultUrl" :gutter="16" class="media-row">
      <el-col :span="resultUrl ? 12 : 24">
        <div class="media-panel">
          <div class="panel-hd">
            <span class="panel-title">原图 · 涂抹遮罩</span>
            <span v-if="originUrl && !resultUrl" class="panel-hint">按住左键涂抹</span>
          </div>
          <div class="canvas-wrap">
            <img v-if="originUrl" ref="imgEl" :src="originUrl" class="base-img" draggable="false" @load="onImgLoad" />
            <canvas
              v-if="originUrl"
              ref="maskEl"
              class="mask-canvas"
              @mousedown="onDown"
              @mousemove="onMove"
              @mouseup="onUp"
              @mouseleave="onUp"
              @touchstart.prevent="onTouchStart"
              @touchmove.prevent="onTouchMove"
              @touchend="onUp"
            />
          </div>
        </div>
      </el-col>
      <el-col v-if="resultUrl" :span="12">
        <div class="media-panel">
          <div class="panel-hd">
            <span class="panel-title">修复结果</span>
            <div>
              <el-tag v-if="meta.latencyMs != null" size="small" effect="plain">{{ meta.latencyMs }} ms</el-tag>
              <el-tag v-if="meta.backend" size="small" effect="plain" style="margin-left: 6px">{{ meta.backend }}</el-tag>
              <el-tag v-if="meta.dilatePx" size="small" effect="plain" style="margin-left: 6px">外扩 {{ meta.dilatePx }}px</el-tag>
              <el-button size="small" link type="primary" :icon="Download" @click="downloadResult">下载</el-button>
            </div>
          </div>
          <el-image :src="resultUrl" fit="contain" class="result-img" :preview-src-list="[resultUrl]" />
        </div>
      </el-col>
    </el-row>

    <el-empty v-if="!originUrl && !running" description="选择图片后涂抹待修复区域" :image-size="100" />
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Download, MagicStick, Refresh, UploadFilled } from '@element-plus/icons-vue'
import { modelApi } from '../../../api/ai'
import { useInferProgress } from '../../../composables/useInferProgress'

const modelOptions = ref([])
const modelId = ref(null)
const file = ref(null)
const originUrl = ref('')
const resultUrl = ref('')
const brushSize = ref(24)
const expandMask = ref(true)
const dilatePx = ref(12)
const running = ref(false)
const hasMask = ref(false)
const meta = ref({})

const imgEl = ref(null)
const maskEl = ref(null)
let drawing = false
let naturalW = 0
let naturalH = 0
let originBlob = null

const canRun = computed(() => !!modelId.value && !!file.value && hasMask.value)
const infer = useInferProgress(modelId)
const percent = computed(() => infer.percent.value)
const elapsedText = computed(() => infer.elapsedText.value)

const loadModels = async () => {
  try {
    const byId = new Map()
    const ingest = (rows) => {
      for (const m of rows || []) {
        if (m?.id != null) byId.set(m.id, m)
      }
    }
    const res = await modelApi.list({ pageNum: 1, pageSize: 100, task: 'image-inpainting' })
    ingest(res.data?.rows)
    if (![...byId.values()].some((m) => /lama|inpaint/i.test(`${m.library || ''}${m.modelKey || ''}`))) {
      const r2 = await modelApi.list({ pageNum: 1, pageSize: 50, modelName: 'LaMa' })
      ingest(r2.data?.rows)
    }
    const list = [...byId.values()].filter((m) => {
      if (!m.filePath || String(m.status) !== '0') return false
      const lib = String(m.library || '').toLowerCase()
      return ['opencv-lama', 'lama', 'inpainting', 'opencv-inpaint'].includes(lib)
        || String(m.modelKey || '').toLowerCase() === 'inpainting-lama'
    })
    modelOptions.value = list
    if (!list.find((m) => m.id === modelId.value)) modelId.value = list[0]?.id || null
  } catch {
    ElMessage.error('加载模型列表失败')
  }
}

const revokeOrigin = () => {
  if (originBlob) {
    URL.revokeObjectURL(originBlob)
    originBlob = null
  }
}

const onPick = (uploadFile) => {
  const raw = uploadFile.raw
  if (!raw?.type?.startsWith('image/')) {
    ElMessage.error('请选择图片')
    return
  }
  file.value = raw
  resultUrl.value = ''
  meta.value = {}
  hasMask.value = false
  revokeOrigin()
  originBlob = URL.createObjectURL(raw)
  originUrl.value = originBlob
}

const syncCanvasSize = () => {
  const img = imgEl.value
  const canvas = maskEl.value
  if (!img || !canvas) return
  naturalW = img.naturalWidth || 0
  naturalH = img.naturalHeight || 0
  const w = img.clientWidth || naturalW
  const h = img.clientHeight || naturalH
  canvas.width = naturalW
  canvas.height = naturalH
  canvas.style.width = `${w}px`
  canvas.style.height = `${h}px`
  const ctx = canvas.getContext('2d')
  ctx.clearRect(0, 0, naturalW, naturalH)
  hasMask.value = false
}

const onImgLoad = () => nextTick(syncCanvasSize)

const canvasPos = (e) => {
  const canvas = maskEl.value
  const rect = canvas.getBoundingClientRect()
  const x = ((e.clientX - rect.left) / rect.width) * canvas.width
  const y = ((e.clientY - rect.top) / rect.height) * canvas.height
  return { x, y }
}

const paintAt = (x, y) => {
  const canvas = maskEl.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  const scale = canvas.width / (canvas.getBoundingClientRect().width || canvas.width)
  const r = Math.max(2, (brushSize.value * scale) / 2)
  ctx.fillStyle = 'rgba(255, 60, 60, 0.55)'
  ctx.beginPath()
  ctx.arc(x, y, r, 0, Math.PI * 2)
  ctx.fill()
  hasMask.value = true
}

const onDown = (e) => {
  drawing = true
  const { x, y } = canvasPos(e)
  paintAt(x, y)
}
const onMove = (e) => {
  if (!drawing) return
  const { x, y } = canvasPos(e)
  paintAt(x, y)
}
const onUp = () => { drawing = false }
const onTouchStart = (e) => {
  const t = e.touches[0]
  if (!t) return
  drawing = true
  const { x, y } = canvasPos({ clientX: t.clientX, clientY: t.clientY })
  paintAt(x, y)
}
const onTouchMove = (e) => {
  if (!drawing) return
  const t = e.touches[0]
  if (!t) return
  const { x, y } = canvasPos({ clientX: t.clientX, clientY: t.clientY })
  paintAt(x, y)
}

const clearMask = () => {
  const canvas = maskEl.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  ctx.clearRect(0, 0, canvas.width, canvas.height)
  hasMask.value = false
}

const exportMaskBlob = () => new Promise((resolve) => {
  const canvas = maskEl.value
  // 导出单通道灰度 PNG（白=待修，黑=保留），避免 RGBA alpha 全 255 被后端误判为整图遮罩
  const out = document.createElement('canvas')
  out.width = canvas.width
  out.height = canvas.height
  const ctx = out.getContext('2d', { willReadFrequently: true })
  const src = canvas.getContext('2d', { willReadFrequently: true })
  const imgData = src.getImageData(0, 0, canvas.width, canvas.height)
  const d = imgData.data
  const gray = ctx.createImageData(out.width, out.height)
  const g = gray.data
  for (let i = 0; i < d.length; i += 4) {
    const painted = d[i + 3] > 20 || d[i] > 40 || d[i + 1] > 40 || d[i + 2] > 40
    const v = painted ? 255 : 0
    g[i] = v
    g[i + 1] = v
    g[i + 2] = v
    g[i + 3] = 255
  }
  ctx.putImageData(gray, 0, 0)
  out.toBlob((b) => resolve(b), 'image/png')
})

const run = async () => {
  if (!canRun.value) return
  running.value = true
  resultUrl.value = ''
  infer.start()
  try {
    const maskBlob = await exportMaskBlob()
    if (!maskBlob) throw new Error('遮罩导出失败')
    const fd = new FormData()
    fd.append('file', file.value)
    fd.append('mask', maskBlob, 'mask.png')
    if (expandMask.value) {
      fd.append('expandMask', '1')
      fd.append('dilatePx', String(Math.max(1, Number(dilatePx.value) || 12)))
    } else {
      fd.append('expandMask', '0')
      fd.append('dilatePx', '0')
    }
    const res = await modelApi.inpaint(modelId.value, fd)
    const d = res.data || {}
    meta.value = {
      latencyMs: d.latencyMs,
      backend: d.backend,
      onnx: d.onnx,
      maskPixels: d.maskPixels,
      dilatePx: d.dilatePx,
    }
    resultUrl.value = d.imageBase64 ? `data:image/jpeg;base64,${d.imageBase64}` : ''
    if (!resultUrl.value) ElMessage.warning('未返回修复图')
  } catch (e) {
    ElMessage.error(e?.response?.data?.message || e?.message || '修复失败')
  } finally {
    infer.finish()
    running.value = false
  }
}

const downloadResult = () => {
  if (!resultUrl.value) return
  const a = document.createElement('a')
  a.href = resultUrl.value
  a.download = `inpaint-${Date.now()}.jpg`
  a.click()
}

const clearAll = () => {
  file.value = null
  resultUrl.value = ''
  meta.value = {}
  hasMask.value = false
  revokeOrigin()
  originUrl.value = ''
}

const onResize = () => {
  if (originUrl.value) nextTick(syncCanvasSize)
}

onMounted(() => {
  loadModels()
  window.addEventListener('resize', onResize)
})
onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  revokeOrigin()
})
</script>

<style scoped>
.inpaint-root { padding-bottom: 24px; }
.cfg-card { margin-bottom: 12px; }
.hint { margin: 4px 0 0; color: var(--el-text-color-secondary); font-size: 13px; line-height: 1.5; }
.brush-n { margin-left: 8px; color: var(--el-text-color-secondary); font-size: 13px; }
.progress-title { margin-bottom: 8px; font-weight: 600; }
.progress-hint { margin-top: 6px; font-size: 12px; color: var(--el-text-color-secondary); }
.media-row { margin-top: 4px; }
.media-panel {
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 10px 12px 14px;
  min-height: 280px;
}
.panel-hd {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.panel-title { font-weight: 600; }
.panel-hint { font-size: 12px; color: var(--el-color-primary); }
.canvas-wrap {
  position: relative;
  display: inline-block;
  max-width: 100%;
  line-height: 0;
}
.base-img {
  max-width: 100%;
  max-height: 62vh;
  display: block;
  user-select: none;
}
.mask-canvas {
  position: absolute;
  left: 0;
  top: 0;
  cursor: crosshair;
  touch-action: none;
}
.result-img {
  width: 100%;
  max-height: 62vh;
  display: block;
}
</style>
