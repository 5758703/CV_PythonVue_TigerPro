<template>
  <div>
    <el-card shadow="never" class="cfg-card panel">
      <div class="panel-title"><span class="pt-bar"></span>检测配置</div>
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

    <el-card shadow="never" class="panel">
      <div class="panel-title"><span class="pt-bar"></span>检测结果</div>
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
        <div class="report-actions">
          <el-button type="primary" :loading="reporting" @click="genReport">
            生成AI检测报告
          </el-button>
        </div>
      </div>

        <div v-if="report" class="report-stage">
          <div class="report-bar">
            <span class="rb-label">A4 正式报告</span>
            <el-button type="primary" :icon="Download" @click="exportPdf">下载 PDF</el-button>
          </div>

          <article ref="reportEl" class="a4-sheet">
            <div class="sheet-watermark">智能检测报告</div>

            <header class="doc-head">
              <div class="doc-org">TIGERPRO · 计算机视觉智能检测平台</div>
              <h1 class="doc-title">智能检测分析报告</h1>
              <div class="doc-subtitle">Intelligent Detection Analysis Report</div>
              <div class="doc-no">报告编号　{{ reportNo }}</div>
            </header>

            <table class="doc-info">
              <tbody>
                <tr>
                  <th>检测模型</th>
                  <td>{{ report.meta.modelName }}</td>
                  <th>模型分类</th>
                  <td>{{ report.meta.category || '未分类' }}</td>
                </tr>
                <tr>
                  <th>检测图片</th>
                  <td>{{ report.meta.imageName }}</td>
                  <th>置信度阈值</th>
                  <td class="mono">{{ report.meta.conf }}</td>
                </tr>
                <tr>
                  <th>生成时间</th>
                  <td class="mono">{{ report.meta.generatedAt }}</td>
                  <th>分析引擎</th>
                  <td>
                    <span :class="['engine-dot', report.meta.aiAvailable ? 'on' : 'off']"></span>
                    {{ report.meta.aiAvailable ? 'DeepSeek AI' : '案例库（降级）' }}
                  </td>
                </tr>
              </tbody>
            </table>

            <div v-if="!report.meta.aiAvailable" class="doc-warn">{{ report.warning }}</div>

            <figure class="doc-figs">
              <div class="fig">
                <img v-if="previewSrc" :src="previewSrc" />
                <figcaption>图 1　原始图像</figcaption>
              </div>
              <div class="fig">
                <img v-if="resultSrc" :src="resultSrc" />
                <figcaption>图 2　检测标注结果</figcaption>
              </div>
            </figure>

            <section class="doc-sec">
              <div class="sec-h"><span class="sec-no">01</span><h2>检测概述</h2></div>
              <p>{{ report.summary }}</p>
              <div class="chips">
                <span v-for="(b, i) in report.stats.byClass" :key="i" class="chip">
                  {{ b.className }}<b>×{{ b.count }}</b><i class="mono">{{ (b.avgConf * 100).toFixed(0) }}%</i>
                </span>
              </div>
            </section>

            <section class="doc-sec">
              <div class="sec-h"><span class="sec-no">02</span><h2>风险评估</h2></div>
              <div class="risk-row">
                <span class="risk-stamp" :class="riskClass(report.risk.level)">
                  <em>风险等级</em><strong>{{ report.risk.level }}</strong>
                </span>
                <p>{{ report.risk.desc }}</p>
              </div>
            </section>

            <section class="doc-sec" v-if="report.findings.length">
              <div class="sec-h"><span class="sec-no">03</span><h2>逐项发现</h2></div>
              <ul class="findings">
                <li v-for="(f, i) in report.findings" :key="i"><b>{{ f.className }}</b>{{ f.note }}</li>
              </ul>
            </section>

            <section class="doc-sec">
              <div class="sec-h"><span class="sec-no">04</span><h2>AI 智能建议</h2></div>
              <ol class="suggestions">
                <li v-for="(s, i) in report.suggestions" :key="i">
                  <h3>{{ s.title }}</h3>
                  <p>{{ s.detail }}</p>
                </li>
              </ol>
            </section>

            <section class="doc-sec" v-if="report.matchedCases.length">
              <div class="sec-h"><span class="sec-no">05</span><h2>匹配案例与关键词</h2></div>
              <div class="cases">
                <div v-for="c in report.matchedCases" :key="c.id" class="case" :class="riskClass(c.risk_level)">
                  <span class="case-dot"></span>
                  <span class="case-title">{{ c.title }}</span>
                  <span class="case-meta">{{ c.category }} · {{ c.risk_level }}</span>
                </div>
              </div>
              <div class="kw-row">
                <span class="kw-label">关键词</span>
                <span v-for="(k, i) in report.keywords" :key="i" class="kw">{{ k }}</span>
              </div>
            </section>

            <section class="doc-sec">
              <div class="sec-h"><span class="sec-no">06</span><h2>结论</h2></div>
              <p class="conclusion">{{ report.conclusion }}</p>
            </section>

            <footer class="doc-foot">
              <span>本报告由 TigerPro 智能检测平台自动生成{{ report.meta.aiAvailable ? '，AI 分析由 DeepSeek 提供' : '（AI 不可用，已采用案例库兜底）' }}。</span>
              <span class="mono">{{ reportNo }}</span>
            </footer>
          </article>
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
import jsPDF from 'jspdf'
import html2canvas from 'html2canvas'

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
const report = ref(null)
const reporting = ref(false)
const reportEl = ref(null)

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
  report.value = null
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
    report.value = null
    activeIndex.value = -1
    await nextTick()
    syncCanvas()
  } finally {
    if (progTimer) { clearInterval(progTimer); progTimer = null }
    detecting.value = false
  }
}

const genReport = async () => {
  if (!result.value) return
  reporting.value = true
  try {
    const payload = {
      detections: result.value.detections,
      width: result.value.width,
      height: result.value.height,
      count: result.value.count,
      imageName: file.value?.name || '未命名图片',
      conf: conf.value
    }
    const res = await modelApi.analyzeReport(modelId.value, payload)
    report.value = res.data
    if (report.value?.warning) ElMessage.warning(report.value.warning)
  } catch (e) {
    ElMessage.error('报告生成失败')
  } finally {
    reporting.value = false
  }
}

const riskClass = (level) => ({ 高: 'is-high', 中: 'is-mid', 低: 'is-low' }[level] || 'is-low')

// 报告编号：由生成时间数字串派生，形如 AIDR-202606241200
const reportNo = computed(() => {
  const digits = (report.value?.meta?.generatedAt || '').replace(/\D/g, '').slice(0, 12)
  return `AIDR-${digits || '------------'}`
})

const exportPdf = async () => {
  if (!reportEl.value) return
  try {
    const canvas = await html2canvas(reportEl.value, { scale: 2, useCORS: true, backgroundColor: '#ffffff' })
    const img = canvas.toDataURL('image/jpeg', 0.92)
    const pdf = new jsPDF('p', 'mm', 'a4')
    const pw = pdf.internal.pageSize.getWidth()
    const ph = pdf.internal.pageSize.getHeight()
    const imgH = (canvas.height * pw) / canvas.width // 等比缩放后总高(mm)
    let left = imgH
    let pos = 0
    pdf.addImage(img, 'JPEG', 0, pos, pw, imgH)
    left -= ph
    while (left > 0) {
      pos -= ph
      pdf.addPage()
      pdf.addImage(img, 'JPEG', 0, pos, pw, imgH)
      left -= ph
    }
    const name = (report.value?.meta?.imageName || 'detection').replace(/\.[^.]+$/, '')
    pdf.save(`${name}_AI检测报告.pdf`)
  } catch (e) {
    ElMessage.error('PDF 导出失败')
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
  report.value = null
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
/* ===== 设计令牌（深蓝公文 + 纸张）===== */
.panel {
  --ink: #1a2433;
  --navy: #1f3a5f;
  --navy-soft: #2f547f;
  --rule: #c8d0db;
  --rule-soft: #e6eaf1;
  --muted: #6b7787;
  --paper: #ffffff;
  --desk: #eef1f6;
  --seal: #b23b3b;
  --mono: 'JetBrains Mono', 'Cascadia Code', Consolas, 'Courier New', monospace;
  --serif: 'Source Han Serif SC', 'Noto Serif SC', 'Songti SC', SimSun, serif;
}

/* ===== 卡片面板标题 ===== */
.panel { border: 1px solid var(--rule-soft); border-radius: 10px; }
.cfg-card { margin-bottom: 14px; }
.panel-title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 15px;
  font-weight: 700;
  letter-spacing: 1px;
  color: var(--ink);
  margin-bottom: 16px;
}
.pt-bar {
  width: 4px;
  height: 16px;
  border-radius: 2px;
  background: linear-gradient(var(--navy), var(--navy-soft));
}

.picked {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
  font-size: 13px;
  color: var(--muted);
}
.pk-name { font-weight: 600; color: var(--ink); }

.progress-box { padding: 28px 8px; }
.progress-title { font-weight: 600; color: var(--ink); margin-bottom: 12px; }
.progress-hint { margin-top: 10px; font-size: 12px; color: var(--muted); }

/* ===== 检测结果双栏 ===== */
.grid { display: flex; gap: 16px; }
.col { flex: 1 1 50%; min-width: 0; }
.col-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 600;
  color: var(--ink);
  margin-bottom: 8px;
}
.img-box {
  background: #f6f8fc;
  border: 1px solid var(--rule-soft);
  border-radius: 8px;
  height: 380px;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}
.img-box :deep(.el-image) { max-width: 100%; max-height: 100%; }
.stage { position: relative; }
.stage-img { max-width: 100%; max-height: 100%; object-fit: contain; display: block; }
.stage-canvas { position: absolute; cursor: pointer; }
.result-meta { margin-top: 16px; }
.det-table { margin-top: 12px; }
.det-table :deep(.el-table__row) { cursor: pointer; }
.det-table :deep(.active-row > td.el-table__cell) { background: #fff3e0 !important; }
.cls-dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  margin-right: 6px;
  vertical-align: middle;
}
.report-actions { margin-top: 16px; }

/* ===== A4 报告：桌面与工具条 ===== */
.report-stage {
  margin-top: 20px;
  padding: 24px;
  background:
    radial-gradient(120% 120% at 50% 0%, #f3f5f9 0%, var(--desk) 70%);
  border-radius: 10px;
  border: 1px solid var(--rule-soft);
}
.report-bar {
  max-width: 794px;
  margin: 0 auto 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.rb-label {
  font-size: 12px;
  letter-spacing: 2px;
  color: var(--muted);
  text-transform: uppercase;
}

/* ===== A4 纸张 ===== */
.a4-sheet {
  position: relative;
  width: 794px;
  max-width: 100%;
  margin: 0 auto;
  box-sizing: border-box;
  padding: 56px 60px 40px;
  background: var(--paper);
  color: var(--ink);
  box-shadow: 0 1px 2px rgba(26, 36, 51, 0.06), 0 18px 50px rgba(26, 36, 51, 0.14);
  border: 1px solid #dfe4ec;
  overflow: hidden;
  font-size: 14px;
  line-height: 1.5;
}
.a4-sheet > *:not(.sheet-watermark) { position: relative; z-index: 1; }
.sheet-watermark {
  position: absolute;
  top: 46%;
  left: 50%;
  transform: translate(-50%, -50%) rotate(-22deg);
  font-family: var(--serif);
  font-size: 88px;
  font-weight: 700;
  letter-spacing: 12px;
  color: rgba(31, 58, 95, 0.045);
  white-space: nowrap;
  pointer-events: none;
  user-select: none;
  z-index: 0;
}

/* ===== 报告抬头 ===== */
.doc-head { text-align: center; padding-bottom: 18px; }
.doc-org {
  font-size: 12px;
  letter-spacing: 3px;
  color: var(--navy);
  font-weight: 600;
}
.doc-title {
  font-family: var(--serif);
  font-size: 30px;
  font-weight: 700;
  letter-spacing: 4px;
  color: var(--ink);
  margin: 10px 0 4px;
}
.doc-subtitle {
  font-size: 11px;
  letter-spacing: 2px;
  color: var(--muted);
  text-transform: uppercase;
}
.doc-no {
  margin-top: 12px;
  font-family: var(--mono);
  font-size: 12px;
  color: var(--navy);
}
.doc-head {
  border-bottom: 3px double var(--navy);
}

/* ===== 信息网格 ===== */
.doc-info {
  width: 100%;
  border-collapse: collapse;
  margin: 18px 0 4px;
  font-size: 13px;
}
.doc-info th,
.doc-info td {
  border: 1px solid var(--rule);
  padding: 9px 12px;
  text-align: left;
  vertical-align: middle;
}
.doc-info th {
  width: 92px;
  background: #f4f7fb;
  color: var(--navy);
  font-weight: 600;
  white-space: nowrap;
}
.doc-info td { color: var(--ink); word-break: break-all; }
.mono { font-family: var(--mono); }
.engine-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 6px;
  vertical-align: middle;
}
.engine-dot.on { background: #2f9e44; box-shadow: 0 0 0 3px rgba(47, 158, 68, 0.16); }
.engine-dot.off { background: #d98a00; box-shadow: 0 0 0 3px rgba(217, 138, 0, 0.16); }

.doc-warn {
  margin-top: 14px;
  padding: 10px 14px;
  border-left: 3px solid #d98a00;
  background: #fff8ec;
  color: #8a5d00;
  font-size: 13px;
}

/* ===== 图像 ===== */
.doc-figs {
  display: flex;
  gap: 18px;
  margin: 22px 0 6px;
}
.fig { flex: 1; min-width: 0; }
.fig img {
  width: 100%;
  display: block;
  border: 1px solid var(--rule);
  background: #f6f8fc;
}
.fig figcaption {
  margin-top: 6px;
  text-align: center;
  font-size: 12px;
  color: var(--muted);
}

/* ===== 章节 ===== */
.doc-sec { margin-top: 26px; }
.sec-h {
  display: flex;
  align-items: baseline;
  gap: 12px;
  padding-bottom: 8px;
  margin-bottom: 12px;
  border-bottom: 1px solid var(--rule);
}
.sec-no {
  font-family: var(--mono);
  font-size: 18px;
  font-weight: 700;
  color: var(--navy);
}
.sec-h h2 {
  font-family: var(--serif);
  font-size: 17px;
  font-weight: 700;
  letter-spacing: 2px;
  color: var(--ink);
  margin: 0;
}
.doc-sec p {
  margin: 0 0 8px;
  line-height: 1.85;
  color: #34404f;
  text-align: justify;
}

/* 概述统计 chips */
.chips { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 6px; }
.chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  border: 1px solid var(--rule);
  border-radius: 4px;
  background: #f8fafc;
  font-size: 12px;
  color: var(--ink);
}
.chip b { color: var(--navy); }
.chip i { font-style: normal; color: var(--muted); }

/* 风险印章 */
.risk-row { display: flex; align-items: flex-start; gap: 18px; }
.risk-row p { flex: 1; margin: 0; }
.risk-stamp {
  flex: 0 0 auto;
  display: inline-flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  width: 92px;
  height: 92px;
  border: 2.5px solid var(--seal);
  border-radius: 8px;
  color: var(--seal);
  transform: rotate(-5deg);
  box-shadow: inset 0 0 0 2px rgba(178, 59, 59, 0.18);
}
.risk-stamp em {
  font-style: normal;
  font-size: 11px;
  letter-spacing: 2px;
}
.risk-stamp strong {
  font-family: var(--serif);
  font-size: 30px;
  line-height: 1;
  margin-top: 4px;
}
.risk-stamp.is-mid { border-color: #d98a00; color: #d98a00; box-shadow: inset 0 0 0 2px rgba(217, 138, 0, 0.18); }
.risk-stamp.is-low { border-color: #2f9e44; color: #2f9e44; box-shadow: inset 0 0 0 2px rgba(47, 158, 68, 0.18); }

/* 逐项发现 */
.findings { margin: 0; padding-left: 0; list-style: none; }
.findings li {
  padding: 8px 0 8px 16px;
  border-bottom: 1px dashed var(--rule-soft);
  line-height: 1.7;
  color: #34404f;
  position: relative;
}
.findings li::before {
  content: '';
  position: absolute;
  left: 0;
  top: 16px;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--navy);
}
.findings li b { color: var(--ink); margin-right: 8px; }

/* AI 建议 */
.suggestions { margin: 0; padding-left: 0; list-style: none; counter-reset: sug; }
.suggestions li {
  counter-increment: sug;
  position: relative;
  padding: 6px 0 14px 40px;
}
.suggestions li::before {
  content: counter(sug, decimal-leading-zero);
  position: absolute;
  left: 0;
  top: 4px;
  font-family: var(--mono);
  font-size: 13px;
  font-weight: 700;
  color: #fff;
  background: var(--navy);
  width: 26px;
  height: 26px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.suggestions h3 {
  margin: 0 0 4px;
  font-size: 14px;
  font-weight: 700;
  color: var(--ink);
}
.suggestions p { margin: 0; }

/* 匹配案例 */
.cases { display: flex; flex-direction: column; gap: 8px; margin-bottom: 12px; }
.case {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border: 1px solid var(--rule);
  border-left-width: 3px;
  border-radius: 4px;
  background: #fbfcfe;
  font-size: 13px;
}
.case.is-high { border-left-color: var(--seal); }
.case.is-mid { border-left-color: #d98a00; }
.case.is-low { border-left-color: #2f9e44; }
.case-dot { width: 8px; height: 8px; border-radius: 50%; background: currentColor; opacity: 0.7; }
.case.is-high .case-dot { background: var(--seal); }
.case.is-mid .case-dot { background: #d98a00; }
.case.is-low .case-dot { background: #2f9e44; }
.case-title { font-weight: 600; color: var(--ink); }
.case-meta { margin-left: auto; color: var(--muted); font-size: 12px; }

.kw-row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.kw-label { font-size: 12px; color: var(--muted); letter-spacing: 1px; }
.kw {
  font-family: var(--mono);
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 3px;
  background: #eef2f8;
  color: var(--navy);
}

.conclusion {
  padding: 14px 16px;
  background: #f4f7fb;
  border-left: 3px solid var(--navy);
  font-weight: 500;
}

/* 页脚 */
.doc-foot {
  margin-top: 32px;
  padding-top: 12px;
  border-top: 1px solid var(--rule);
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  font-size: 11px;
  color: var(--muted);
}

@media (max-width: 860px) {
  .a4-sheet { padding: 32px 24px 28px; }
  .doc-figs { flex-direction: column; }
  .report-stage { padding: 14px; }
}
</style>
