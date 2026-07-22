<template>
  <div>
    <el-card shadow="never" class="cfg-card">
      <el-form :inline="true">
        <el-form-item label="表格检测">
          <el-select v-model="detectId" placeholder="YOLO 表格检测" style="width: 220px" filterable>
            <el-option
              v-for="m in detectModels"
              :key="m.id"
              :label="`${m.modelName}`"
              :value="m.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="OCR 检测">
          <el-select v-model="detId" placeholder="RapidOCR 检测" style="width: 200px">
            <el-option v-for="m in detModels" :key="m.id" :label="m.modelName" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="OCR 识别">
          <el-select v-model="recId" placeholder="RapidOCR 识别" style="width: 200px">
            <el-option v-for="m in recModels" :key="m.id" :label="m.modelName" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="结构模型">
          <el-select v-model="tableId" placeholder="SLANet_plus" style="width: 220px">
            <el-option v-for="m in tableModels" :key="m.id" :label="m.modelName" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="置信度">
          <el-slider v-model="conf" :min="0.05" :max="0.95" :step="0.05" style="width: 120px" />
        </el-form-item>
        <el-form-item>
          <el-upload :show-file-list="false" :auto-upload="false" :on-change="onPick" accept="image/*">
            <el-button :icon="UploadFilled">选择图片</el-button>
          </el-upload>
        </el-form-item>
        <el-form-item>
          <el-button
            type="primary"
            :icon="Grid"
            :loading="running"
            :disabled="!canRun"
            @click="run"
          >
            开始识别
          </el-button>
          <el-button :icon="Refresh" @click="clearAll">清空</el-button>
        </el-form-item>
      </el-form>
      <el-alert
        v-if="!detectModels.length || !detModels.length || !recModels.length || !tableModels.length"
        type="warning"
        :closable="false"
        title="请先到「模型管理」拉取：文档表格检测(YOLO)、RapidOCR 检测/识别、SLANet_plus 结构模型。"
      />
      <el-alert
        v-else
        type="info"
        :closable="false"
        class="flow-tip"
        title="流水线：YOLO 检表 → RapidOCR 单元格文字 → SLANet_plus 结构拼 HTML/CSV。未检出表格时自动按整图识别。"
      />
    </el-card>

    <el-card shadow="never">
      <div v-if="running" class="progress-box">
        <div class="progress-title">识别中…（CPU 推理，请稍候）</div>
      </div>
      <el-empty v-else-if="!previewSrc" description="选择模型与表格图片后开始识别" />
      <div v-else class="grid">
        <div class="col">
          <div class="col-title">
            预览
            <el-tag v-if="result" size="small" type="success">表格 {{ result.tableCount || 0 }}</el-tag>
          </div>
          <div class="img-box">
            <img :src="resultSrc || previewSrc" class="stage-img" alt="表格预览" />
          </div>
          <el-alert
            v-if="result?.fallbackFullImage"
            type="info"
            :closable="false"
            class="fallback-tip"
            title="未检测到独立表格区域，已按整图进行结构识别。"
          />
        </div>
        <div class="col">
          <div class="col-title">
            识别结果
            <span v-if="tables.length">
              <el-button link type="primary" :icon="CopyDocument" @click="copyActive">复制 CSV</el-button>
              <el-button link type="primary" :icon="Download" @click="downloadCsv">下载 CSV</el-button>
              <el-button link type="primary" :icon="Download" @click="downloadHtml">下载 HTML</el-button>
            </span>
          </div>
          <el-tabs v-if="tables.length" v-model="activeTab" type="card">
            <el-tab-pane
              v-for="(t, i) in tables"
              :key="i"
              :label="`表 ${i + 1}`"
              :name="String(i)"
            >
              <div class="meta">
                <el-tag size="small">{{ t.className }}</el-tag>
                <el-tag size="small" type="info">OCR {{ t.ocrCount || 0 }} 行</el-tag>
                <el-tag v-if="t.elapse" size="small" type="warning">结构 {{ t.elapse }}s</el-tag>
                <el-tag v-if="t.error" size="small" type="danger">失败</el-tag>
              </div>
              <el-alert v-if="t.error" type="error" :closable="false" :title="t.error" class="err-tip" />
              <el-table
                v-if="t.rows?.length"
                :data="tableRows(t)"
                size="small"
                border
                max-height="280"
                class="sheet"
              >
                <el-table-column
                  v-for="(h, ci) in columnHeaders(t)"
                  :key="ci"
                  :prop="`c${ci}`"
                  :label="h"
                  min-width="90"
                  show-overflow-tooltip
                />
              </el-table>
              <el-input
                v-model="t.csv"
                type="textarea"
                :rows="8"
                readonly
                class="csv-box"
                placeholder="CSV 文本"
              />
              <details class="html-details">
                <summary>查看 HTML</summary>
                <el-input :model-value="t.html" type="textarea" :rows="6" readonly />
              </details>
            </el-tab-pane>
          </el-tabs>
          <el-empty v-else-if="done" :image-size="60" description="未识别到表格内容" />
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { UploadFilled, Grid, Refresh, Download, CopyDocument } from '@element-plus/icons-vue'
import { modelApi, tableApi } from '../../../api/ai'

const allModels = ref([])
const detectId = ref(null)
const detId = ref(null)
const recId = ref(null)
const tableId = ref(null)
const conf = ref(0.25)
const file = ref(null)
const previewSrc = ref('')
const resultSrc = ref('')
const running = ref(false)
const done = ref(false)
const result = ref(null)
const activeTab = ref('0')

const detectModels = computed(() => {
  const yolo = allModels.value.filter(
    (m) =>
      m.library === 'ultralytics' &&
      m.task === 'object-detection' &&
      m.filePath &&
      m.status === '0',
  )
  const preferred = yolo.filter(
    (m) =>
      String(m.modelKey || '').includes('table') ||
      String(m.category || '').includes('文档') ||
      String(m.modelName || '').includes('表格'),
  )
  return preferred.length ? preferred : yolo
})
const detModels = computed(() =>
  allModels.value.filter((m) => m.library === 'rapidocr' && m.task === 'text-detection' && m.filePath && m.status === '0'),
)
const recModels = computed(() =>
  allModels.value.filter((m) => m.library === 'rapidocr' && m.task === 'text-recognition' && m.filePath && m.status === '0'),
)
const tableModels = computed(() =>
  allModels.value.filter(
    (m) => m.library === 'rapidtable' && m.task === 'table-structure' && m.filePath && m.status === '0',
  ),
)
const tables = computed(() => result.value?.tables || [])
const canRun = computed(
  () => detectId.value && detId.value && recId.value && tableId.value && file.value && !running.value,
)

const loadModels = async () => {
  try {
    const res = await modelApi.list({ pageNum: 1, pageSize: 200 })
    allModels.value = res.data.rows || []
    if (detectModels.value.length && !detectId.value) detectId.value = detectModels.value[0].id
    if (detModels.value.length && !detId.value) detId.value = detModels.value[0].id
    if (recModels.value.length && !recId.value) recId.value = recModels.value[0].id
    if (tableModels.value.length && !tableId.value) tableId.value = tableModels.value[0].id
  } catch (_) {
    ElMessage.error('加载模型列表失败')
  }
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
  resultSrc.value = ''
  result.value = null
  done.value = false
  activeTab.value = '0'
}

const run = async () => {
  if (!canRun.value) return
  running.value = true
  done.value = false
  result.value = null
  resultSrc.value = ''
  try {
    const fd = new FormData()
    fd.append('file', file.value)
    fd.append('detectId', detectId.value)
    fd.append('detId', detId.value)
    fd.append('recId', recId.value)
    fd.append('tableId', tableId.value)
    fd.append('conf', conf.value)
    const res = await tableApi.recognize(fd)
    result.value = res.data || {}
    if (result.value.imageBase64) {
      resultSrc.value = `data:image/jpeg;base64,${result.value.imageBase64}`
    }
    activeTab.value = '0'
    done.value = true
    const n = result.value.tableCount || 0
    if (!n) ElMessage.info('未识别到表格')
    else ElMessage.success(`识别完成，共 ${n} 张表`)
  } catch (e) {
    ElMessage.error(e?.message || '表格识别失败')
  } finally {
    running.value = false
  }
}

const activeTable = computed(() => {
  const i = Number(activeTab.value) || 0
  return tables.value[i] || null
})

const columnHeaders = (t) => {
  const rows = t?.rows || []
  if (!rows.length) return []
  const cols = Math.max(...rows.map((r) => r.length))
  return Array.from({ length: cols }, (_, i) => `列${i + 1}`)
}

const tableRows = (t) => {
  const headers = columnHeaders(t)
  return (t?.rows || []).map((row) => {
    const obj = {}
    headers.forEach((_, i) => {
      obj[`c${i}`] = row[i] ?? ''
    })
    return obj
  })
}

const copyActive = async () => {
  const csv = activeTable.value?.csv || ''
  if (!csv) {
    ElMessage.warning('无 CSV 内容')
    return
  }
  try {
    await navigator.clipboard.writeText(csv)
    ElMessage.success('已复制 CSV')
  } catch (_) {
    ElMessage.error('复制失败')
  }
}

const downloadBlob = (text, filename, mime) => {
  const blob = new Blob([text], { type: `${mime};charset=utf-8` })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

const downloadCsv = () => {
  const csv = activeTable.value?.csv || ''
  if (!csv) {
    ElMessage.warning('无 CSV 内容')
    return
  }
  downloadBlob(csv, `table_${Date.now()}.csv`, 'text/csv')
}

const downloadHtml = () => {
  const html = activeTable.value?.html || ''
  if (!html) {
    ElMessage.warning('无 HTML 内容')
    return
  }
  downloadBlob(html, `table_${Date.now()}.html`, 'text/html')
}

const clearAll = () => {
  if (previewSrc.value) URL.revokeObjectURL(previewSrc.value)
  file.value = null
  previewSrc.value = ''
  resultSrc.value = ''
  result.value = null
  done.value = false
  activeTab.value = '0'
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
.flow-tip,
.fallback-tip,
.err-tip {
  margin-top: 8px;
}
.progress-box {
  padding: 28px 8px;
}
.progress-title {
  font-weight: 600;
  color: #3a4a63;
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
  gap: 8px;
}
.img-box {
  background: #f6f8fc;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  height: 420px;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}
.stage-img {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
  display: block;
}
.meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}
.sheet {
  margin-bottom: 8px;
}
.csv-box {
  margin-top: 4px;
}
.html-details {
  margin-top: 8px;
  color: #606266;
  font-size: 13px;
}
.html-details summary {
  cursor: pointer;
  margin-bottom: 6px;
}
</style>
