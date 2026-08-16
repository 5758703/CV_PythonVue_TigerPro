<template>
  <div class="annotate-root">
    <div class="annotate-toolbar">
      <el-select v-model="datasetId" placeholder="选择数据集" style="width: 240px" @change="onDatasetChange">
        <el-option
          v-for="d in datasetOptions"
          :key="d.id"
          :label="`${d.name}（${d.classNames?.join(', ') || '未设类别'}）`"
          :value="d.id"
        />
      </el-select>
      <el-tag v-if="stats.total" type="info">共 {{ stats.total }} 张</el-tag>
      <el-tag v-if="stats.annotated" type="success">已标 {{ stats.annotated }}</el-tag>
      <el-tag v-if="stats.unannotated" type="warning">未标 {{ stats.unannotated }}</el-tag>
      <el-select v-model="activeClassId" placeholder="当前类别" style="width: 180px">
        <el-option v-for="(c, i) in classNames" :key="c" :label="c" :value="i" />
      </el-select>
      <el-button :icon="ArrowLeft" :disabled="!canPrev" @click="prevSample">上一张</el-button>
      <el-button :icon="ArrowRight" :disabled="!canNext" @click="nextSample">下一张</el-button>
      <el-button type="primary" :loading="saving" @click="saveLabels">保存标注</el-button>
      <el-button type="danger" plain :disabled="!selectedIdx && selectedIdx !== 0" @click="deleteSelected">删除框</el-button>
      <el-button plain :disabled="!currentStem" @click="clearLabels">清空本图</el-button>
    </div>

    <el-empty v-if="!datasetId" description="请先选择数据集（建议格式 yolo_flat，并配置类别）" />
    <el-empty v-else-if="!samples.length" description="暂无图片，请先在「数据集管理」中视频抽帧或上传图片" />

    <div v-else class="annotate-main">
      <div class="sample-list">
        <div class="list-title">样本列表</div>
        <div
          v-for="(s, idx) in samples"
          :key="s.stem"
          class="sample-item"
          :class="{ active: idx === currentIdx, done: s.annotated }"
          @click="gotoSample(idx)"
        >
          <span class="si-name">{{ s.name }}</span>
          <el-tag size="small" :type="s.annotated ? 'success' : 'info'">{{ s.boxCount || 0 }}</el-tag>
        </div>
      </div>

      <div class="canvas-wrap" ref="wrapRef">
        <canvas
          ref="canvasRef"
          @mousedown="onMouseDown"
          @mousemove="onMouseMove"
          @mouseup="onMouseUp"
          @mouseleave="onMouseUp"
        />
        <div class="canvas-hint">拖拽绘制框 · 点击选中 · Del 删除 · ←/→ 切换 · Ctrl+S 保存</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { ArrowLeft, ArrowRight } from '@element-plus/icons-vue'
import { trainingApi } from '../../../api/ai'

const props = defineProps({
  initialDatasetId: { type: Number, default: null },
})

const CLASS_COLORS = ['#ff2d95', '#00e5ff', '#ffd400', '#7cff6b', '#ff8a00', '#b388ff']

const datasetOptions = ref([])
const datasetId = ref(props.initialDatasetId)
const classNames = ref([])
const samples = ref([])
const stats = ref({ total: 0, annotated: 0, unannotated: 0 })
const currentIdx = ref(0)
const activeClassId = ref(0)
const boxes = ref([])
const selectedIdx = ref(-1)
const saving = ref(false)

const canvasRef = ref(null)
const wrapRef = ref(null)
const img = ref(null)
const imgUrl = ref('')
const scale = ref(1)
const drawing = ref(false)
const dragStart = ref(null)
const draftBox = ref(null)

const currentSample = computed(() => samples.value[currentIdx.value] || null)
const currentStem = computed(() => currentSample.value?.stem || '')
const canPrev = computed(() => currentIdx.value > 0)
const canNext = computed(() => currentIdx.value < samples.value.length - 1)

async function loadDatasets() {
  const res = await trainingApi.listDatasets({ pageNum: 1, pageSize: 100 })
  datasetOptions.value = (res.data.rows || []).filter((d) => d.format !== 'import')
}

async function loadSamples() {
  if (!datasetId.value) return
  const res = await trainingApi.annotateSamples(datasetId.value)
  classNames.value = res.data.dataset?.classNames || []
  samples.value = res.data.samples || []
  stats.value = res.data.stats || { total: 0, annotated: 0, unannotated: 0 }
  if (!classNames.value.length) {
    ElMessage.warning('请先在数据集中配置类别名称（如 Rocket Body、Engine Flames）')
  }
  if (samples.value.length && currentIdx.value >= samples.value.length) {
    currentIdx.value = 0
  }
  if (samples.value.length) {
    await loadCurrentImage()
  }
}

function revokeImgUrl() {
  if (imgUrl.value) {
    URL.revokeObjectURL(imgUrl.value)
    imgUrl.value = ''
  }
}

async function loadCurrentImage() {
  if (!datasetId.value || !currentStem.value) return
  revokeImgUrl()
  boxes.value = []
  selectedIdx.value = -1
  draftBox.value = null
  const blob = await trainingApi.annotateImage(datasetId.value, currentStem.value)
  imgUrl.value = URL.createObjectURL(blob)
  const image = new Image()
  image.onload = async () => {
    img.value = image
    await nextTick()
    fitCanvas()
    await loadLabels()
    redraw()
  }
  image.src = imgUrl.value
}

async function loadLabels() {
  if (!datasetId.value || !currentStem.value) return
  try {
    const res = await trainingApi.annotateLabels(datasetId.value, currentStem.value)
    boxes.value = (res.data.boxes || []).map((b) => ({ ...b }))
  } catch {
    boxes.value = []
  }
}

function fitCanvas() {
  const canvas = canvasRef.value
  const wrap = wrapRef.value
  const image = img.value
  if (!canvas || !wrap || !image) return
  const maxW = wrap.clientWidth - 16
  const maxH = Math.max(360, window.innerHeight - 320)
  const s = Math.min(maxW / image.width, maxH / image.height, 1)
  scale.value = s
  canvas.width = Math.round(image.width * s)
  canvas.height = Math.round(image.height * s)
}

function normToPx(box) {
  const image = img.value
  const s = scale.value
  if (!image) return null
  const w = image.width * s
  const h = image.height * s
  const bw = box.w * w
  const bh = box.h * h
  const cx = box.cx * w
  const cy = box.cy * h
  return {
    x1: cx - bw / 2,
    y1: cy - bh / 2,
    x2: cx + bw / 2,
    y2: cy + bh / 2,
  }
}

function pxToNorm(x1, y1, x2, y2) {
  const image = img.value
  const s = scale.value
  const w = image.width * s
  const h = image.height * s
  const left = Math.min(x1, x2)
  const top = Math.min(y1, y2)
  const right = Math.max(x1, x2)
  const bottom = Math.max(y1, y2)
  const bw = right - left
  const bh = bottom - top
  return {
    cx: (left + bw / 2) / w,
    cy: (top + bh / 2) / h,
    w: bw / w,
    h: bh / h,
  }
}

function redraw() {
  const canvas = canvasRef.value
  const image = img.value
  if (!canvas || !image) return
  const ctx = canvas.getContext('2d')
  ctx.clearRect(0, 0, canvas.width, canvas.height)
  ctx.drawImage(image, 0, 0, canvas.width, canvas.height)

  boxes.value.forEach((box, i) => {
    const p = normToPx(box)
    if (!p) return
    const color = CLASS_COLORS[box.classId % CLASS_COLORS.length]
    ctx.strokeStyle = color
    ctx.lineWidth = i === selectedIdx.value ? 3 : 2
    ctx.strokeRect(p.x1, p.y1, p.x2 - p.x1, p.y2 - p.y1)
    const label = box.className || classNames.value[box.classId] || String(box.classId)
    ctx.font = '12px sans-serif'
    ctx.fillStyle = color
    ctx.fillRect(p.x1, Math.max(0, p.y1 - 18), ctx.measureText(label).width + 8, 18)
    ctx.fillStyle = '#fff'
    ctx.fillText(label, p.x1 + 4, Math.max(12, p.y1 - 5))
  })

  if (draftBox.value) {
    const p = draftBox.value
    ctx.strokeStyle = CLASS_COLORS[activeClassId.value % CLASS_COLORS.length]
    ctx.lineWidth = 2
    ctx.setLineDash([6, 4])
    ctx.strokeRect(p.x1, p.y1, p.x2 - p.x1, p.y2 - p.y1)
    ctx.setLineDash([])
  }
}

function canvasPos(evt) {
  const canvas = canvasRef.value
  const rect = canvas.getBoundingClientRect()
  return {
    x: evt.clientX - rect.left,
    y: evt.clientY - rect.top,
  }
}

function hitTest(x, y) {
  for (let i = boxes.value.length - 1; i >= 0; i--) {
    const p = normToPx(boxes.value[i])
    if (!p) continue
    if (x >= p.x1 && x <= p.x2 && y >= p.y1 && y <= p.y2) return i
  }
  return -1
}

function onMouseDown(evt) {
  const pos = canvasPos(evt)
  const hit = hitTest(pos.x, pos.y)
  if (hit >= 0) {
    selectedIdx.value = hit
    redraw()
    return
  }
  drawing.value = true
  dragStart.value = pos
  draftBox.value = { x1: pos.x, y1: pos.y, x2: pos.x, y2: pos.y }
  selectedIdx.value = -1
}

function onMouseMove(evt) {
  if (!drawing.value || !dragStart.value) return
  const pos = canvasPos(evt)
  draftBox.value = {
    x1: dragStart.value.x,
    y1: dragStart.value.y,
    x2: pos.x,
    y2: pos.y,
  }
  redraw()
}

function onMouseUp() {
  if (!drawing.value || !draftBox.value) return
  drawing.value = false
  const { x1, y1, x2, y2 } = draftBox.value
  draftBox.value = null
  if (Math.abs(x2 - x1) < 6 || Math.abs(y2 - y1) < 6) {
    redraw()
    return
  }
  const norm = pxToNorm(x1, y1, x2, y2)
  const clsId = activeClassId.value
  boxes.value.push({
    classId: clsId,
    className: classNames.value[clsId],
    ...norm,
  })
  selectedIdx.value = boxes.value.length - 1
  redraw()
}

function deleteSelected() {
  if (selectedIdx.value < 0) return
  boxes.value.splice(selectedIdx.value, 1)
  selectedIdx.value = -1
  redraw()
}

async function saveLabels() {
  if (!datasetId.value || !currentStem.value) return
  saving.value = true
  try {
    const res = await trainingApi.saveAnnotateLabels(datasetId.value, currentStem.value, { boxes: boxes.value })
    stats.value = res.data.stats || stats.value
    const s = samples.value[currentIdx.value]
    if (s) {
      s.annotated = res.data.boxCount > 0
      s.boxCount = res.data.boxCount
    }
    ElMessage.success(res.message || '保存成功')
  } finally {
    saving.value = false
  }
}

async function clearLabels() {
  if (!datasetId.value || !currentStem.value) return
  await trainingApi.clearAnnotateLabels(datasetId.value, currentStem.value)
  boxes.value = []
  selectedIdx.value = -1
  const s = samples.value[currentIdx.value]
  if (s) {
    s.annotated = false
    s.boxCount = 0
  }
  await loadSamples()
  redraw()
  ElMessage.success('已清空本图标注')
}

async function gotoSample(idx) {
  currentIdx.value = idx
  await loadCurrentImage()
}

async function prevSample() {
  if (!canPrev.value) return
  await gotoSample(currentIdx.value - 1)
}

async function nextSample() {
  if (!canNext.value) return
  await gotoSample(currentIdx.value + 1)
}

function onDatasetChange() {
  currentIdx.value = 0
  loadSamples()
}

function onKeydown(e) {
  if (!samples.value.length) return
  if (e.key === 'ArrowLeft') {
    e.preventDefault()
    prevSample()
  } else if (e.key === 'ArrowRight') {
    e.preventDefault()
    nextSample()
  } else if (e.key === 'Delete' || e.key === 'Backspace') {
    if (selectedIdx.value >= 0) {
      e.preventDefault()
      deleteSelected()
    }
  } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
    e.preventDefault()
    saveLabels()
  }
}

function onResize() {
  if (img.value) {
    fitCanvas()
    redraw()
  }
}

watch(() => props.initialDatasetId, (v) => {
  if (v) {
    datasetId.value = v
    loadSamples()
  }
})

onMounted(async () => {
  await loadDatasets()
  if (datasetId.value) await loadSamples()
  window.addEventListener('keydown', onKeydown)
  window.addEventListener('resize', onResize)
})

onBeforeUnmount(() => {
  revokeImgUrl()
  window.removeEventListener('keydown', onKeydown)
  window.removeEventListener('resize', onResize)
})

defineExpose({ reload: loadSamples, setDatasetId: (id) => { datasetId.value = id; loadSamples() } })
</script>

<style scoped>
.annotate-root {
  min-height: 520px;
}
.annotate-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}
.annotate-main {
  display: grid;
  grid-template-columns: 220px 1fr;
  gap: 12px;
  min-height: 480px;
}
.sample-list {
  border: 1px solid #e4e9f2;
  border-radius: 8px;
  overflow: auto;
  max-height: calc(100vh - 280px);
  background: #fafbfd;
}
.list-title {
  padding: 10px 12px;
  font-weight: 600;
  color: #3a4a63;
  border-bottom: 1px solid #e8edf5;
  position: sticky;
  top: 0;
  background: #f5f8fc;
}
.sample-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 12px;
  cursor: pointer;
  border-bottom: 1px solid #f0f3f8;
  font-size: 12px;
}
.sample-item:hover {
  background: #eef5ff;
}
.sample-item.active {
  background: #dbeafe;
}
.sample-item.done .si-name {
  color: #15803d;
}
.si-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}
.canvas-wrap {
  border: 1px solid #0c1733;
  border-radius: 8px;
  background: #0c1733;
  padding: 8px;
  display: flex;
  flex-direction: column;
  align-items: center;
}
canvas {
  cursor: crosshair;
  max-width: 100%;
}
.canvas-hint {
  margin-top: 8px;
  font-size: 12px;
  color: #9aa8c2;
}
</style>
