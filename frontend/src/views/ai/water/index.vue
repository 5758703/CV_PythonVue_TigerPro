<template>
  <div class="water-root">
    <!-- 配置卡 -->
    <el-card shadow="never" class="cfg-card">
      <el-form :inline="true" class="cfg-form">
        <el-form-item label="检测模型">
          <el-select v-model="detId" placeholder="RapidOCR 检测模型" style="width:210px">
            <el-option v-for="m in detModels" :key="m.id" :label="m.modelName" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="识别模型">
          <el-select v-model="recId" placeholder="RapidOCR 识别模型" style="width:210px">
            <el-option v-for="m in recModels" :key="m.id" :label="m.modelName" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-upload :show-file-list="false" :auto-upload="false" :on-change="onPick" accept="image/*">
            <el-button :icon="UploadFilled">选择图片</el-button>
          </el-upload>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :icon="Aim" :loading="running"
            :disabled="!detId || !recId || !file" @click="run">开始检测</el-button>
          <el-button :icon="Refresh" @click="reset">清空</el-button>
        </el-form-item>
      </el-form>
      <el-alert v-if="!detModels.length || !recModels.length" type="warning" :closable="false"
        title="需各一个 RapidOCR 检测(text-detection) 和 识别(text-recognition) 模型；请到「模型管理」设 library=rapidocr 后拉取。" />
    </el-card>

    <!-- 主体 -->
    <el-row :gutter="16" class="main-row" v-if="previewSrc || running">
      <!-- 左：图像预览 -->
      <el-col :span="15">
        <el-row :gutter="12" class="img-row">
          <!-- 原图 -->
          <el-col :span="result && !running ? 12 : 24">
            <div class="img-panel">
              <div class="panel-hd">
                <span class="panel-title">原图</span>
                <span v-if="!result && previewSrc && !running" class="panel-hint">
                  拖动红线可手动设置水面位置
                </span>
                <div v-if="previewSrc && !running" class="zoom-toolbar">
                  <el-button-group size="small">
                    <el-button :icon="ZoomOut" @click="origZoom.zoomOut()" />
                    <el-button class="zoom-pct" @click="origZoom.zoomFit()">{{ origZoom.pctText }}</el-button>
                    <el-button :icon="ZoomIn" @click="origZoom.zoomIn()" />
                  </el-button-group>
                  <el-button size="small" link type="primary" @click="origViewer = true">全屏</el-button>
                </div>
              </div>

              <div v-if="running" class="panel-loading">
                <el-icon class="rotating" :size="36"><Loading /></el-icon>
                <p>识别中…</p>
              </div>

              <div
                v-else-if="previewSrc"
                ref="origViewport"
                class="zoom-viewport"
                @wheel.prevent="origZoom.onWheel"
              >
                <div class="zoom-spacer" :style="origZoom.spacerStyle">
                  <div class="zoom-inner" :style="origZoom.innerStyle">
                  <div
                    class="canvas-host"
                    :class="{ interactive: !result }"
                    @mousedown="!result && startDrag($event)"
                    @mousemove="!result && onDrag($event)"
                    @mouseup="endDrag"
                    @mouseleave="endDrag"
                    @touchstart.prevent="!result && startDragT($event)"
                    @touchmove.prevent="!result && onDragT($event)"
                    @touchend="endDrag"
                  >
                    <img
                      ref="imgEl"
                      :src="previewSrc"
                      class="panel-img"
                      draggable="false"
                      @load="onOrigLoad"
                    />
                    <canvas v-if="!result" ref="cv" class="overlay-canvas" />
                  </div>
                  </div>
                </div>
              </div>
            </div>
          </el-col>

          <!-- 检测结果图 -->
          <el-col v-if="result && !running" :span="12">
            <div class="img-panel">
              <div class="panel-hd">
                <span class="panel-title">检测结果</span>
                <span class="panel-hint ok">
                  置信度 {{ (result.surfaceConfidence * 100).toFixed(0) }}%
                </span>
                <div class="zoom-toolbar">
                  <el-button-group size="small">
                    <el-button :icon="ZoomOut" @click="resultZoom.zoomOut()" />
                    <el-button class="zoom-pct" @click="resultZoom.zoomFit()">{{ resultZoom.pctText }}</el-button>
                    <el-button :icon="ZoomIn" @click="resultZoom.zoomIn()" />
                  </el-button-group>
                  <el-button size="small" link type="primary" @click="resultViewer = true">全屏</el-button>
                </div>
              </div>

              <div ref="resultViewport" class="zoom-viewport" @wheel.prevent="resultZoom.onWheel">
                <div class="zoom-spacer" :style="resultZoom.spacerStyle">
                  <div class="zoom-inner" :style="resultZoom.innerStyle">
                    <img
                      ref="resultImgEl"
                      :src="resultSrc"
                      class="panel-img"
                      draggable="false"
                      @load="onResultLoad"
                    />
                  </div>
                </div>
              </div>
            </div>
          </el-col>
        </el-row>
      </el-col>

      <!-- 右：结果数据 -->
      <el-col :span="9">
        <el-card shadow="never" class="result-card">
          <template #header><span>检测结果</span></template>

          <div v-if="running" class="r-loading">
            <el-icon class="rotating" :size="28"><Loading /></el-icon>
          </div>

          <div v-else-if="result" class="result-body">
            <div class="level-display" :class="levelClass">
              <div class="level-value">
                {{ result.level != null ? result.level.toFixed(2) : 'N/A' }}
              </div>
              <div class="level-unit">m</div>
            </div>

            <el-descriptions :column="1" border size="small" class="desc-table">
              <el-descriptions-item label="计算方法">
                <el-tag size="small" :type="methodType">{{ result.method }}</el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="说明">{{ result.note }}</el-descriptions-item>
              <el-descriptions-item label="水位尺定位">
                <el-tag size="small" :type="result.gaugeDetected ? 'success' : 'info'">
                  {{ result.gaugeDetected ? 'YOLOv8 已定位' : '未训练/未检测到' }}
                </el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="识别刻度数">
                {{ result.markCount }} 个
                <span v-if="result.ocrRawCount != null" class="sub-hint">
                  （OCR 共 {{ result.ocrRawCount }} 行）
                </span>
              </el-descriptions-item>
              <el-descriptions-item label="水面线 y">
                {{ result.waterY }} px（{{ (result.waterYRatio * 100).toFixed(1) }}%）
              </el-descriptions-item>
              <el-descriptions-item label="水面置信度">
                <el-progress
                  :percentage="+(result.surfaceConfidence * 100).toFixed(0)"
                  :status="result.surfaceConfidence > 0.5 ? 'success' : 'warning'"
                  :stroke-width="8"
                  style="width:140px"
                />
              </el-descriptions-item>
              <el-descriptions-item label="图像尺寸">
                {{ result.width }} × {{ result.height }} px
              </el-descriptions-item>
            </el-descriptions>

            <div class="marks-section" v-if="result.marks.length">
              <div class="marks-title">已识别刻度</div>
              <div class="marks-list">
                <el-tag
                  v-for="m in result.marks"
                  :key="m.value"
                  size="small"
                  class="mark-tag"
                  :type="isNearWater(m) ? 'danger' : 'info'"
                >
                  {{ m.value }} m
                </el-tag>
              </div>
            </div>

            <div class="actions">
              <el-button type="primary" :icon="Aim" size="small" @click="run">重新检测</el-button>
              <el-button size="small" :icon="Download" @click="downloadResult">下载结果图</el-button>
            </div>
          </div>

          <el-empty v-else description="上传图片并选择模型后开始检测" :image-size="80" />
        </el-card>

        <el-card shadow="never" class="tips-card">
          <div class="tips-title">使用说明</div>
          <ol class="tips-list">
            <li>到「模型管理」拉取 RapidOCR <b>检测</b>和<b>识别</b>模型（library=rapidocr）</li>
            <li>上传水位尺照片，点击<b>开始检测</b></li>
            <li>原图与结果图均支持<b>滚轮缩放</b>、工具栏放大/缩小/适应</li>
            <li>检测前可在原图上拖动红线手动校正水面位置</li>
            <li>理论精度 <b>0.01 m</b>（取决于图像分辨率与刻度间距）</li>
          </ol>
        </el-card>
      </el-col>
    </el-row>

    <el-empty v-if="!previewSrc && !running" description="请选择图片" :image-size="120" class="empty-pick" />

    <el-image-viewer
      v-if="origViewer && previewSrc"
      :url-list="[previewSrc]"
      hide-on-click-modal
      @close="origViewer = false"
    />
    <el-image-viewer
      v-if="resultViewer && resultSrc"
      :url-list="[resultSrc]"
      hide-on-click-modal
      @close="resultViewer = false"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  UploadFilled, Aim, Refresh, Download, Loading, ZoomIn, ZoomOut
} from '@element-plus/icons-vue'
import { modelApi } from '../../../api/ai'
import request from '../../../api/request'

const allModels = ref([])
const detId = ref(null)
const recId = ref(null)
const file = ref(null)
const previewSrc = ref('')
const running = ref(false)
const result = ref(null)

const imgEl = ref(null)
const cv = ref(null)
const origViewport = ref(null)
const resultImgEl = ref(null)
const resultViewport = ref(null)
const manualWaterY = ref(null)

const origViewer = ref(false)
const resultViewer = ref(false)

const detModels = computed(() => allModels.value.filter(m => m.task === 'text-detection'))
const recModels = computed(() => allModels.value.filter(m => m.task === 'text-recognition'))
const resultSrc = computed(() =>
  result.value?.imageBase64 ? `data:image/jpeg;base64,${result.value.imageBase64}` : ''
)

const levelClass = computed(() => {
  if (!result.value || result.value.level == null) return 'level-na'
  return result.value.method === '失败' ? 'level-warn' : 'level-ok'
})

const methodType = computed(() => {
  if (!result.value) return ''
  const m = result.value.method
  if (m === '插值') return 'success'
  if (m === '失败') return 'danger'
  return 'warning'
})

function useImageZoom(viewportRef, imgRef) {
  const zoom = ref(1)
  const fitZoom = ref(1)
  const naturalW = ref(0)
  const naturalH = ref(0)
  const pctText = computed(() => `${Math.round(zoom.value * 100)}%`)
  const spacerStyle = computed(() => ({
    width: `${Math.max(1, naturalW.value * zoom.value)}px`,
    height: `${Math.max(1, naturalH.value * zoom.value)}px`
  }))
  const innerStyle = computed(() => ({
    transform: `scale(${zoom.value})`,
    transformOrigin: '0 0',
    width: naturalW.value ? `${naturalW.value}px` : 'auto'
  }))

  function onImageLoad() {
    const img = imgRef.value
    if (!img) return
    naturalW.value = img.naturalWidth || img.width
    naturalH.value = img.naturalHeight || img.height
    calcFit()
  }

  function calcFit() {
    nextTick(() => {
      const vp = viewportRef.value
      if (!vp || !naturalW.value) return
      const pad = 16
      const vw = vp.clientWidth - pad
      const vh = vp.clientHeight - pad
      fitZoom.value = Math.min(vw / naturalW.value, vh / naturalH.value, 1)
      zoom.value = fitZoom.value
    })
  }

  function zoomIn() {
    zoom.value = Math.min(4, +(zoom.value + 0.15).toFixed(2))
  }
  function zoomOut() {
    zoom.value = Math.max(0.15, +(zoom.value - 0.15).toFixed(2))
  }
  function zoomFit() {
    zoom.value = fitZoom.value
  }
  function onWheel(e) {
    const delta = e.deltaY > 0 ? -0.1 : 0.1
    zoom.value = Math.max(0.15, Math.min(4, +(zoom.value + delta).toFixed(2)))
  }

  return { zoom, fitZoom, pctText, spacerStyle, innerStyle, onImageLoad, calcFit, zoomIn, zoomOut, zoomFit, onWheel }
}

const origZoom = useImageZoom(origViewport, imgEl)
const resultZoom = useImageZoom(resultViewport, resultImgEl)

function isNearWater(mark) {
  if (!result.value) return false
  return Math.abs(mark.y - result.value.waterY) < result.value.height * 0.08
}

async function loadModels() {
  try {
    const res = await modelApi.list({ pageNum: 1, pageSize: 200 })
    allModels.value = res.data?.rows || []
  } catch { /* ignore */ }
}

function onPick(uploadFile) {
  file.value = uploadFile.raw
  result.value = null
  manualWaterY.value = null
  const reader = new FileReader()
  reader.onload = e => { previewSrc.value = e.target.result }
  reader.readAsDataURL(uploadFile.raw)
}

function reset() {
  file.value = null
  previewSrc.value = ''
  result.value = null
  manualWaterY.value = null
}

function onOrigLoad() {
  origZoom.onImageLoad()
  initCanvas()
}

function onResultLoad() {
  resultZoom.onImageLoad()
}

watch([result, running], ([r, run]) => {
  if (r && !run) nextTick(() => resultZoom.onImageLoad())
})

// ── Canvas 水面线拖拽 ──
let canvasH = 0
let canvasW = 0
let dragging = false

function initCanvas() {
  nextTick(() => {
    if (!imgEl.value || !cv.value) return
    const rect = imgEl.value.getBoundingClientRect()
    canvasW = rect.width
    canvasH = rect.height
    cv.value.width = canvasW
    cv.value.height = canvasH
    drawLine()
  })
}

watch(() => origZoom.zoom.value, () => {
  if (!result.value) nextTick(initCanvas)
})

function drawLine() {
  if (!cv.value) return
  const ctx = cv.value.getContext('2d')
  ctx.clearRect(0, 0, canvasW, canvasH)
  if (manualWaterY.value == null) return
  const y = manualWaterY.value * canvasH
  ctx.save()
  ctx.strokeStyle = '#ff3300'
  ctx.lineWidth = 2
  ctx.setLineDash([8, 5])
  ctx.beginPath()
  ctx.moveTo(0, y)
  ctx.lineTo(canvasW, y)
  ctx.stroke()
  ctx.fillStyle = '#ff3300'
  ctx.font = '13px monospace'
  ctx.setLineDash([])
  ctx.fillText(`水面线 ${(manualWaterY.value * 100).toFixed(1)}%`, 8, Math.max(20, y - 6))
  ctx.restore()
}

function _ratio(clientY) {
  const rect = cv.value.getBoundingClientRect()
  return Math.max(0.01, Math.min(0.99, (clientY - rect.top) / rect.height))
}

function startDrag(e) { dragging = true; manualWaterY.value = _ratio(e.clientY); drawLine() }
function onDrag(e) { if (!dragging) return; manualWaterY.value = _ratio(e.clientY); drawLine() }
function endDrag() { dragging = false }
function startDragT(e) { dragging = true; manualWaterY.value = _ratio(e.touches[0].clientY); drawLine() }
function onDragT(e) { if (!dragging) return; manualWaterY.value = _ratio(e.touches[0].clientY); drawLine() }

// ── 检测 ──
async function run() {
  if (!detId.value || !recId.value || !file.value) {
    ElMessage.warning('请选择模型并上传图片')
    return
  }
  running.value = true
  result.value = null
  try {
    const fd = new FormData()
    fd.append('image', file.value)
    fd.append('detId', detId.value)
    fd.append('recId', recId.value)
    if (manualWaterY.value != null) {
      fd.append('waterYRatio', manualWaterY.value.toFixed(6))
    }
    const res = await request.post('/ai/water-level/detect', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 0
    })
    if (res.code !== 0) {
      ElMessage.error(res.message || '检测失败')
      return
    }
    result.value = res.data
    if (res.data.level == null) {
      ElMessage.warning(`检测完成，但未计算出水位：${res.data.note}`)
    } else {
      ElMessage.success(`水位 ${res.data.level.toFixed(2)} m（${res.data.method}）`)
    }
  } catch (e) {
    ElMessage.error(`请求失败：${e.message || e}`)
  } finally {
    running.value = false
  }
}

function downloadResult() {
  if (!result.value?.imageBase64) return
  const a = document.createElement('a')
  a.href = resultSrc.value
  a.download = `water_level_${result.value.level?.toFixed(2) ?? 'NA'}m.jpg`
  a.click()
}

onMounted(loadModels)
</script>

<style scoped>
.water-root { padding: 0; }
.cfg-card { margin-bottom: 14px; }
.main-row { margin-top: 0; }
.empty-pick { margin-top: 80px; }

.img-row { align-items: stretch; }

.img-panel {
  background: #fff;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 460px;
}

.panel-hd {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  padding: 10px 14px;
  background: #f8fafc;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.panel-title {
  font-weight: 600;
  font-size: 14px;
  color: #303133;
}
.panel-hint {
  font-size: 12px;
  color: #909399;
  flex: 1;
  min-width: 120px;
}
.panel-hint.ok { color: #67c23a; }
.zoom-toolbar {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-left: auto;
}
.zoom-pct {
  min-width: 58px;
  font-variant-numeric: tabular-nums;
  font-size: 12px;
}

.zoom-viewport {
  flex: 1;
  min-height: 400px;
  max-height: 520px;
  overflow: auto;
  background: repeating-conic-gradient(#e8eaed 0% 25%, #f4f5f7 0% 50%) 50% / 16px 16px;
  padding: 8px;
}
.zoom-spacer {
  position: relative;
  min-width: 1px;
  min-height: 1px;
}
.zoom-inner {
  position: absolute;
  top: 0;
  left: 0;
  line-height: 0;
}

.panel-loading {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: #909399;
  min-height: 400px;
}

.canvas-host {
  position: relative;
  display: inline-block;
  user-select: none;
}
.canvas-host.interactive {
  cursor: ns-resize;
}
.panel-img {
  display: block;
  width: auto;
  height: auto;
  max-width: none;
}
.overlay-canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
}

.rotating { animation: spin 1.2s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

/* 结果卡 */
.result-card { margin-bottom: 14px; }
.r-loading { display: flex; justify-content: center; padding: 40px 0; }
.result-body { display: flex; flex-direction: column; gap: 14px; }

.level-display {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding: 18px 0 14px;
  justify-content: center;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.level-value {
  font-size: 58px;
  font-weight: 700;
  line-height: 1;
  font-variant-numeric: tabular-nums;
  font-family: 'Courier New', monospace;
}
.level-unit { font-size: 22px; color: #606266; padding-bottom: 8px; }
.level-ok   .level-value { color: #409eff; }
.level-warn .level-value { color: #e6a23c; }
.level-na   .level-value { color: #909399; }

.desc-table { font-size: 13px; }
.sub-hint { margin-left: 6px; color: #909399; font-size: 12px; }

.marks-title { font-size: 13px; color: #606266; margin-bottom: 6px; }
.marks-list { display: flex; flex-wrap: wrap; gap: 6px; }
.mark-tag { font-family: monospace; }

.actions { display: flex; gap: 8px; padding-top: 4px; }

.tips-title { font-weight: 600; margin-bottom: 8px; color: #303133; }
.tips-list { margin: 0; padding-left: 18px; color: #606266; font-size: 13px; line-height: 2.1; }

@media (max-width: 1200px) {
  .img-row .el-col { max-width: 100%; flex: 0 0 100%; }
  .main-row .el-col { max-width: 100%; flex: 0 0 100%; }
}
</style>
