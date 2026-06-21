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
          <el-select v-model="modelId" placeholder="选择模型" style="width: 220px" @change="clearResult">
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
          <el-upload
            :show-file-list="false"
            :auto-upload="false"
            :on-change="onPick"
            accept="image/*"
          >
            <el-button :icon="UploadFilled">选择图片</el-button>
          </el-upload>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :icon="VideoPlay" :loading="detecting" :disabled="!modelId || !file" @click="detect">开始检测</el-button>
          <el-button :icon="Refresh" @click="clearAll">清空</el-button>
        </el-form-item>
      </el-form>
      <div v-if="imageInfo" class="picked">
        <el-icon><Picture /></el-icon>
        <span class="pk-name">{{ file?.name }}</span>
        <el-tag size="small" type="info" effect="plain">{{ imageInfo.width }}×{{ imageInfo.height }}</el-tag>
        <el-tag size="small" type="info" effect="plain">{{ fmtSize(imageInfo.size) }}</el-tag>
      </div>
      <el-alert
        v-if="!modelOptions.length"
        type="warning"
        :closable="false"
        title="暂无可用模型：请先到「模型管理」上传或拉取权重，并保持启用状态。"
      />
    </el-card>

    <el-card shadow="never">
      <div v-if="detecting" class="progress-box">
        <div class="progress-title">检测中… 预计剩余 {{ etaText }}</div>
        <el-progress :percentage="percent" :stroke-width="18" :text-inside="true" :status="percent >= 100 ? 'success' : ''" />
        <div class="progress-hint">已用 {{ (elapsedMs / 1000).toFixed(1) }} 秒</div>
      </div>

      <el-empty v-else-if="!previewSrc && !result" description="选择模型与图片后开始检测" />

      <div v-else class="grid">
        <div class="col">
          <div class="col-title">原图</div>
          <div class="img-box">
            <el-image v-if="previewSrc" :src="previewSrc" :preview-src-list="[previewSrc]" fit="contain" />
          </div>
        </div>
        <div class="col">
          <div class="col-title">
            检测结果（点击目标高亮联动）
            <span>
              <el-button v-if="resultSrc" link type="primary" :icon="ZoomIn" @click="viewer = true">放大</el-button>
              <el-button v-if="resultSrc" link type="primary" :icon="Download" @click="downloadResult">下载结果图</el-button>
            </span>
          </div>
          <div class="img-box stage" ref="stageEl">
            <template v-if="result">
              <img ref="imgEl" :src="previewSrc" class="stage-img" @load="onImgLoad" />
              <canvas ref="overlayEl" class="stage-canvas" @click="onCanvasClick"></canvas>
            </template>
            <el-empty v-else :image-size="80" description="尚未检测" />
          </div>
        </div>
      </div>

      <div v-if="!detecting && result" class="result-meta">
        <el-alert :title="`检测到 ${result.count} 个目标（图像 ${result.width}×${result.height}）·点击表格行或图中框可联动高亮`" type="success" :closable="false" />
        <el-table
          ref="tableRef"
          :data="result.detections"
          size="small"
          border
          max-height="360"
          class="det-table"
          highlight-current-row
          :row-class-name="rowClass"
          @row-click="onRowClick"
        >
          <el-table-column type="index" label="#" width="56" />
          <el-table-column label="类别" min-width="140">
            <template #default="{ row, $index }">
              <span class="cls-dot" :style="{ background: boxColor($index) }"></span>
              {{ row.className }}
            </template>
          </el-table-column>
          <el-table-column label="置信度" width="120">
            <template #default="{ row }">
              <el-progress :percentage="+(row.confidence * 100).toFixed(1)" :stroke-width="12" />
            </template>
          </el-table-column>
          <el-table-column label="坐标 (x1, y1, x2, y2)" min-width="200">
            <template #default="{ row }">{{ row.bbox.join(', ') }}</template>
          </el-table-column>
        </el-table>
      </div>
    </el-card>

    <el-image-viewer v-if="viewer && resultSrc" :url-list="[resultSrc]" hide-on-click-modal @close="viewer = false" />
  </div>
</template>

<script setup>
import { ref, computed, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { UploadFilled, VideoPlay, Refresh, Download, ZoomIn, Picture } from '@element-plus/icons-vue'

import { modelApi } from '../../../api/ai'

const modelOptions = ref([])
const modelId = ref(null)
const category = ref('')
const conf = ref(0.25)
const file = ref(null)
const imageInfo = ref(null)

// 进度/预计剩余（单图无逐帧进度，按该模型上次耗时估算）
const elapsedMs = ref(0)
const estByModel = {}
let startTime = 0
let progTimer = null

const percent = computed(() => {
  const est = estByModel[modelId.value]
  const e = elapsedMs.value
  if (est) return Math.min(99, Math.floor((e / est) * 100))
  return Math.floor(90 * (1 - Math.exp(-e / 2500))) // 无历史估算：平滑爬升到~90%
})
const etaText = computed(() => {
  const est = estByModel[modelId.value]
  if (!est) return '首次检测加载模型，请稍候…'
  const remain = (est - elapsedMs.value) / 1000
  return remain > 0 ? fmtEta(remain) : '即将完成'
})
const fmtEta = (sec) => {
  if (!isFinite(sec) || sec < 0) return '--'
  const s = Math.round(sec)
  return s < 60 ? `${s} 秒` : `${Math.floor(s / 60)} 分 ${s % 60} 秒`
}
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
  clearResult()
}
const previewSrc = ref('')
const detecting = ref(false)
const result = ref(null)

const stageEl = ref(null)
const imgEl = ref(null)
const overlayEl = ref(null)
const tableRef = ref(null)
const activeIndex = ref(-1)
const viewer = ref(false)

const resultSrc = computed(() =>
  result.value?.imageBase64 ? `data:image/jpeg;base64,${result.value.imageBase64}` : ''
)

// 每个检测目标按序号取稳定颜色（与表格类别圆点一致）
const PALETTE = ['#67c23a', '#409eff', '#e6a23c', '#9254de', '#13c2c2', '#fa8c16', '#eb2f96', '#2f54eb']
const HIGHLIGHT = '#ff1744'
const boxColor = (i) => PALETTE[i % PALETTE.length]

const rowClass = ({ rowIndex }) => (rowIndex === activeIndex.value ? 'active-row' : '')

// 让 canvas 内部分辨率=原图像素，显示尺寸/位置对齐 contain 后的图片
const syncCanvas = () => {
  const img = imgEl.value
  const cv = overlayEl.value
  if (!img || !cv || !img.naturalWidth) return
  cv.width = img.naturalWidth
  cv.height = img.naturalHeight
  cv.style.left = `${img.offsetLeft}px`
  cv.style.top = `${img.offsetTop}px`
  cv.style.width = `${img.offsetWidth}px`
  cv.style.height = `${img.offsetHeight}px`
  drawBoxes()
}

const drawBoxes = () => {
  const cv = overlayEl.value
  if (!cv || !result.value) return
  const ctx = cv.getContext('2d')
  ctx.clearRect(0, 0, cv.width, cv.height)
  const lw = Math.max(2, cv.width / 400)
  const fs = Math.max(12, Math.round(cv.width / 55))
  ctx.font = `${fs}px sans-serif`
  ctx.textBaseline = 'top'
  result.value.detections.forEach((d, i) => {
    const [x1, y1, x2, y2] = d.bbox
    const active = i === activeIndex.value
    const color = active ? HIGHLIGHT : boxColor(i)
    ctx.lineWidth = active ? lw * 2 : lw
    ctx.strokeStyle = color
    if (active) {
      ctx.fillStyle = 'rgba(255,23,68,0.12)'
      ctx.fillRect(x1, y1, x2 - x1, y2 - y1)
    }
    ctx.strokeRect(x1, y1, x2 - x1, y2 - y1)
    const label = `${d.className} ${(d.confidence * 100).toFixed(0)}%`
    const tw = ctx.measureText(label).width + 8
    ctx.fillStyle = color
    ctx.fillRect(x1, Math.max(0, y1 - fs - 4), tw, fs + 4)
    ctx.fillStyle = '#fff'
    ctx.fillText(label, x1 + 4, Math.max(0, y1 - fs - 3))
  })
}

const setActive = (i) => {
  activeIndex.value = activeIndex.value === i ? -1 : i
  drawBoxes()
}

const onRowClick = (row) => {
  setActive(result.value.detections.indexOf(row))
}

const onCanvasClick = (e) => {
  const cv = overlayEl.value
  const scale = cv.width / cv.clientWidth
  const x = e.offsetX * scale
  const y = e.offsetY * scale
  // 命中最上层（面积最小）包含点击点的框
  let hit = -1
  let best = Infinity
  result.value.detections.forEach((d, i) => {
    const [x1, y1, x2, y2] = d.bbox
    if (x >= x1 && x <= x2 && y >= y1 && y <= y2) {
      const area = (x2 - x1) * (y2 - y1)
      if (area < best) { best = area; hit = i }
    }
  })
  activeIndex.value = hit
  drawBoxes()
  if (hit >= 0 && tableRef.value) {
    tableRef.value.setCurrentRow(result.value.detections[hit])
  }
}

const onImgLoad = () => syncCanvas()

const onResize = () => syncCanvas()

const loadModels = async () => {
  const res = await modelApi.list({ pageNum: 1, pageSize: 100 })
  // 仅保留 目标检测任务、已启用、有本地权重 的模型
  modelOptions.value = (res.data.rows || []).filter(
    (m) => m.task === 'object-detection' && m.filePath && m.status === '0'
  )
  if (modelOptions.value.length && !modelId.value) {
    modelId.value = modelOptions.value[0].id
  }
}

const clearResult = () => {
  result.value = null
  activeIndex.value = -1
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
  // 读取图片尺寸/大小
  imageInfo.value = { size: raw.size, width: 0, height: 0 }
  const im = new Image()
  im.onload = () => { imageInfo.value = { size: raw.size, width: im.naturalWidth, height: im.naturalHeight } }
  im.src = previewSrc.value
}

const detect = async () => {
  detecting.value = true
  startTime = Date.now()
  elapsedMs.value = 0
  progTimer = setInterval(() => { elapsedMs.value = Date.now() - startTime }, 100)
  try {
    const fd = new FormData()
    fd.append('file', file.value)
    fd.append('conf', conf.value)
    const res = await modelApi.detect(modelId.value, fd)
    estByModel[modelId.value] = Date.now() - startTime // 记录本次耗时供下次估算
    result.value = res.data
    activeIndex.value = -1
    await nextTick()
    syncCanvas()
  } finally {
    if (progTimer) { clearInterval(progTimer); progTimer = null }
    detecting.value = false
  }
}

const clearAll = () => {
  if (progTimer) { clearInterval(progTimer); progTimer = null }
  if (previewSrc.value) URL.revokeObjectURL(previewSrc.value)
  file.value = null
  previewSrc.value = ''
  result.value = null
  imageInfo.value = null
  activeIndex.value = -1
}

const downloadResult = () => {
  const a = document.createElement('a')
  a.href = resultSrc.value
  a.download = 'detection_result.jpg'
  a.click()
}

onMounted(() => {
  loadModels()
  window.addEventListener('resize', onResize)
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
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
.col {
  flex: 1 1 50%;
  min-width: 0;
}
.col-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 600;
  color: #3a4a63;
  margin-bottom: 8px;
}
.img-box {
  background: #f4f6fb;
  border-radius: 8px;
  height: 380px;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}
.img-box :deep(.el-image) {
  max-width: 100%;
  max-height: 100%;
}
.stage {
  position: relative;
}
.stage-img {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
  display: block;
}
.stage-canvas {
  position: absolute;
  cursor: pointer;
}
.result-meta {
  margin-top: 16px;
}
.det-table {
  margin-top: 12px;
}
.det-table :deep(.el-table__row) {
  cursor: pointer;
}
.det-table :deep(.active-row > td.el-table__cell) {
  background: #fff3e0 !important;
}
.cls-dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  margin-right: 6px;
  vertical-align: middle;
}
</style>
