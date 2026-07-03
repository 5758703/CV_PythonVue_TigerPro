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
      <!-- 左：图像 -->
      <el-col :span="14">
        <el-card shadow="never" class="img-card">
          <template #header>
            <div class="card-hd">
              <span>水位尺图像</span>
              <span class="hint" v-if="previewSrc && !result">
                可拖动红色虚线手动设置水面位置，再点「重新检测」
              </span>
              <span class="hint ok" v-if="result">
                水面置信度 {{ (result.surfaceConfidence * 100).toFixed(0) }}%
              </span>
            </div>
          </template>

          <div class="stage-wrap">
            <div v-if="running" class="loading-box">
              <el-icon class="rotating" :size="40"><Loading /></el-icon>
              <p>OCR 识别中，请稍候…</p>
            </div>

            <template v-else-if="previewSrc && !result">
              <div class="canvas-host"
                @mousedown="startDrag" @mousemove="onDrag" @mouseup="endDrag" @mouseleave="endDrag"
                @touchstart.prevent="startDragT" @touchmove.prevent="onDragT" @touchend="endDrag">
                <img ref="imgEl" :src="previewSrc" class="preview-img" @load="initCanvas" />
                <canvas ref="cv" class="overlay-canvas" />
              </div>
            </template>

            <template v-else-if="result">
              <img :src="'data:image/jpeg;base64,' + result.imageBase64" class="result-img" />
            </template>
          </div>
        </el-card>
      </el-col>

      <!-- 右：结果 -->
      <el-col :span="10">
        <el-card shadow="never" class="result-card">
          <template #header><span>检测结果</span></template>

          <div v-if="running" class="r-loading">
            <el-icon class="rotating" :size="28"><Loading /></el-icon>
          </div>

          <div v-else-if="result" class="result-body">
            <!-- 大号读数 -->
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
                <span v-if="result.ocrRawCount != null" style="margin-left:8px;color:#909399;font-size:12px">
                  （OCR 共检测到 {{ result.ocrRawCount }} 行文字）
                </span>
              </el-descriptions-item>
              <el-descriptions-item label="水面线 y">
                {{ result.waterY }} px（{{ (result.waterYRatio * 100).toFixed(1) }}%）
              </el-descriptions-item>
              <el-descriptions-item label="水面置信度">
                <el-progress
                  :percentage="+(result.surfaceConfidence * 100).toFixed(0)"
                  :status="result.surfaceConfidence > 0.5 ? 'success' : 'warning'"
                  :stroke-width="8" style="width:140px" />
              </el-descriptions-item>
              <el-descriptions-item label="图像尺寸">
                {{ result.width }} × {{ result.height }} px
              </el-descriptions-item>
            </el-descriptions>

            <div class="marks-section" v-if="result.marks.length">
              <div class="marks-title">已识别刻度</div>
              <div class="marks-list">
                <el-tag v-for="m in result.marks" :key="m.value" size="small" class="mark-tag"
                  :type="isNearWater(m) ? 'danger' : 'info'">
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

        <!-- 说明 -->
        <el-card shadow="never" class="tips-card">
          <div class="tips-title">使用说明</div>
          <ol class="tips-list">
            <li>到「模型管理」拉取 RapidOCR <b>检测</b>和<b>识别</b>模型（library=rapidocr）</li>
            <li>上传水位尺照片，点击<b>开始检测</b></li>
            <li>系统自动定位水面线，读取刻度数字并线性插值</li>
            <li>水面置信度低时可拖动预览图中红线手动校正，再重新检测</li>
            <li>理论精度 <b>0.01 m</b>（取决于图像分辨率与刻度间距）</li>
          </ol>
        </el-card>
      </el-col>
    </el-row>

    <el-empty v-if="!previewSrc && !running" description="请选择图片" :image-size="120"
      style="margin-top:80px" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { UploadFilled, Aim, Refresh, Download, Loading } from '@element-plus/icons-vue'
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
const manualWaterY = ref(null)  // 归一化 0-1，null = 自动检测

const detModels = computed(() => allModels.value.filter(m => m.task === 'text-detection'))
const recModels = computed(() => allModels.value.filter(m => m.task === 'text-recognition'))

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

function isNearWater(mark) {
  if (!result.value) return false
  return Math.abs(mark.y - result.value.waterY) < result.value.height * 0.08
}

async function loadModels() {
  try {
    const res = await modelApi.list({ pageNum: 1, pageSize: 200 })
    allModels.value = res.data?.rows || []
  } catch {}
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

// ── Canvas 水面线拖拽 ──
let canvasH = 0, canvasW = 0, dragging = false

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
  ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(canvasW, y); ctx.stroke()
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
    if (res.code !== 0) { ElMessage.error(res.message || '检测失败'); return }
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
  a.href = 'data:image/jpeg;base64,' + result.value.imageBase64
  a.download = `water_level_${result.value.level?.toFixed(2) ?? 'NA'}m.jpg`
  a.click()
}

onMounted(loadModels)
</script>

<style scoped>
.water-root { padding: 0; }
.cfg-card { margin-bottom: 14px; }
.main-row { margin-top: 0; }

.card-hd { display: flex; align-items: center; gap: 10px; }
.hint { font-size: 12px; color: #909399; }
.hint.ok { color: #67c23a; }

.stage-wrap {
  min-height: 320px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.loading-box {
  display: flex; flex-direction: column;
  align-items: center; gap: 12px;
  color: #909399; padding: 40px 0;
}
.rotating { animation: spin 1.2s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.canvas-host {
  position: relative;
  display: inline-block;
  cursor: ns-resize;
  user-select: none;
  max-width: 100%;
}
.preview-img {
  display: block;
  max-width: 100%;
  max-height: 540px;
  object-fit: contain;
}
.overlay-canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
}
.result-img {
  display: block;
  max-width: 100%;
  max-height: 560px;
  object-fit: contain;
  margin: 0 auto;
}

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

.marks-title { font-size: 13px; color: #606266; margin-bottom: 6px; }
.marks-list { display: flex; flex-wrap: wrap; gap: 6px; }
.mark-tag { font-family: monospace; }

.actions { display: flex; gap: 8px; padding-top: 4px; }

.tips-title { font-weight: 600; margin-bottom: 8px; color: #303133; }
.tips-list { margin: 0; padding-left: 18px; color: #606266; font-size: 13px; line-height: 2.1; }
</style>
