<template>
  <div class="quality-root">
    <el-row :gutter="16">
      <!-- 左侧：配置 -->
      <el-col :xs="24" :lg="7">
        <el-card shadow="never" class="side-card">
          <template #header>
            <div class="card-hd">
              <span>质量检测</span>
              <el-tooltip content="分析图片-标签配对、类别分布与标注框统计" placement="top">
                <el-icon class="hint-icon"><QuestionFilled /></el-icon>
              </el-tooltip>
            </div>
          </template>

          <div class="field-block">
            <div class="field-label">加载方式</div>
            <el-radio-group v-model="mode" size="small">
              <el-radio-button value="raw">数据集 raw</el-radio-button>
              <el-radio-button value="yaml">YAML 配置</el-radio-button>
            </el-radio-group>
            <div class="field-hint">
              {{ mode === 'yaml' ? '分析已构建的 yolo/data.yaml 目录' : '分析 raw/images + raw/labels' }}
            </div>
          </div>

          <div class="field-block">
            <div class="field-label">数据集</div>
            <el-select v-model="datasetId" placeholder="选择数据集" style="width:100%" @change="onDatasetChange">
              <el-option
                v-for="d in datasetOptions"
                :key="d.id"
                :label="`${d.name}（${formatLabel(d.format)}）`"
                :value="d.id"
              />
            </el-select>
          </div>

          <div v-if="selectedDataset" class="path-box">
            <div class="path-label">数据路径</div>
            <div class="path-value">{{ dataPathHint }}</div>
            <el-tag v-if="selectedDataset.classNames?.length" size="small" type="info" class="path-tag">
              {{ selectedDataset.classNames.length }} 个类别
            </el-tag>
          </div>

          <el-button
            type="primary"
            :icon="DataAnalysis"
            :loading="analyzing"
            :disabled="!datasetId"
            class="run-btn"
            @click="runAnalyze"
          >
            开始分析
          </el-button>

          <div v-if="lastRun" class="status-box">
            <el-tag size="small" :type="mode === 'yaml' ? 'warning' : 'primary'" effect="plain">
              {{ mode === 'yaml' ? 'YAML 配置' : '数据集 raw' }}
            </el-tag>
            <el-tag size="small" type="success" effect="plain">已生成结果 · {{ lastRun }}</el-tag>
          </div>

          <div class="history-block">
            <div class="field-label">历史记录</div>
            <el-empty v-if="!history.length" description="暂无记录" :image-size="48" />
            <div v-else class="history-list">
              <div v-for="(h, i) in history" :key="i" class="history-item" @click="loadHistory(h)">
                <div class="hi-name">{{ h.datasetName }}</div>
                <div class="hi-meta">{{ h.time }} · {{ h.imageCount }} 张</div>
              </div>
            </div>
          </div>
        </el-card>
      </el-col>

      <!-- 右侧：结果 -->
      <el-col :xs="24" :lg="17">
        <el-empty v-if="!report" description="选择数据集后点击「开始分析」" />

        <template v-else>
          <el-card shadow="never" class="result-card">
            <template #header>
              <div class="card-hd">
                <span>分析概览</span>
                <el-button size="small" :icon="Download" @click="exportReport">导出报告</el-button>
              </div>
            </template>

            <el-alert
              v-for="(issue, i) in report.issues"
              :key="i"
              :type="issue.level === 'error' ? 'error' : issue.level === 'warning' ? 'warning' : issue.level === 'success' ? 'success' : 'info'"
              :title="issue.text"
              :closable="false"
              class="issue-alert"
            />

            <div class="metric-grid">
              <div v-for="m in overviewMetrics" :key="m.key" class="metric-item" :class="m.cls">
                <div class="metric-val">{{ m.value }}</div>
                <div class="metric-lbl">{{ m.label }}</div>
              </div>
            </div>
          </el-card>

          <el-row :gutter="16" class="detail-row">
            <el-col :span="24">
              <el-card shadow="never" class="result-card">
                <template #header><span>类别分布</span></template>
                <el-empty v-if="!report.classDistribution?.length" description="无标注框" :image-size="48" />
                <div v-else class="class-dist">
                  <div v-for="c in report.classDistribution" :key="c.classId" class="dist-row">
                    <span class="dist-name">{{ c.classId }} {{ c.name }}</span>
                    <div class="dist-bar-wrap">
                      <div class="dist-bar" :style="{ width: c.barPercent + '%', background: classColor(c.classId) }" />
                    </div>
                    <span class="dist-count">{{ c.count }} ({{ c.percent }}%)</span>
                  </div>
                </div>
              </el-card>
            </el-col>

            <el-col :xs="24" :md="12">
              <el-card shadow="never" class="result-card">
                <template #header><span>图片尺寸</span></template>
                <el-descriptions :column="1" border size="small">
                  <el-descriptions-item label="平均宽度">{{ report.imageSize.avgWidth }} px</el-descriptions-item>
                  <el-descriptions-item label="平均高度">{{ report.imageSize.avgHeight }} px</el-descriptions-item>
                  <el-descriptions-item label="宽度范围">
                    {{ report.imageSize.widthRange.min }} ~ {{ report.imageSize.widthRange.max }} px
                  </el-descriptions-item>
                  <el-descriptions-item label="高度范围">
                    {{ report.imageSize.heightRange.min }} ~ {{ report.imageSize.heightRange.max }} px
                  </el-descriptions-item>
                </el-descriptions>
              </el-card>
            </el-col>

            <el-col :xs="24" :md="12">
              <el-card shadow="never" class="result-card">
                <template #header><span>标注框统计</span></template>
                <el-descriptions :column="1" border size="small">
                  <el-descriptions-item label="平均面积占比">{{ report.boxStats.avgAreaRatio }}%</el-descriptions-item>
                  <el-descriptions-item label="平均宽高比">{{ report.boxStats.avgAspectRatio }}</el-descriptions-item>
                  <el-descriptions-item label="小目标 (&lt;{{ report.boxStats.smallThresholdPercent }}%)">
                    {{ report.boxStats.smallObjects }}
                  </el-descriptions-item>
                  <el-descriptions-item label="大目标 (&gt;{{ report.boxStats.largeThresholdPercent }}%)">
                    {{ report.boxStats.largeObjects }}
                  </el-descriptions-item>
                </el-descriptions>
              </el-card>
            </el-col>
          </el-row>
        </template>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { DataAnalysis, Download, QuestionFilled } from '@element-plus/icons-vue'
import { trainingApi } from '../../../api/ai'

const props = defineProps({
  initialDatasetId: { type: Number, default: null },
})

const HISTORY_KEY = 'training_quality_history'

const datasetOptions = ref([])
const datasetId = ref(props.initialDatasetId)
const mode = ref('raw')
const analyzing = ref(false)
const report = ref(null)
const lastRun = ref(null)
const history = ref([])

const CLASS_COLORS = ['#409eff', '#9b59b6', '#e91e8c', '#f56c6c', '#67c23a', '#e6a23c']

const selectedDataset = computed(() => datasetOptions.value.find((d) => d.id === datasetId.value) || null)

const formatLabel = (fmt) => {
  const map = { yolo_flat: 'YOLO扁平', yolo: 'YOLO', voc: 'VOC', labelme: 'LabelMe', auto: '自动', import: '导入' }
  return map[fmt] || fmt
}

const dataPathHint = computed(() => {
  if (!selectedDataset.value) return '—'
  if (mode.value === 'yaml') {
    return selectedDataset.value.yamlPath || '（需先构建数据集）'
  }
  if (selectedDataset.value.format === 'import') {
    return selectedDataset.value.sourcePath || '—'
  }
  return `uploads/datasets/${selectedDataset.value.id}/raw`
})

const overviewMetrics = computed(() => {
  const o = report.value?.overview
  if (!o) return []
  return [
    { key: 'img', label: '图片总数', value: o.totalImages, cls: '' },
    { key: 'lbl', label: '标签总数', value: o.totalLabels, cls: '' },
    { key: 'box', label: '标注框', value: o.totalBoxes, cls: '' },
    { key: 'cls', label: '类别数', value: o.classCount, cls: '' },
    { key: 'ok', label: '配对成功', value: o.matchedPairs, cls: 'ok' },
    { key: 'oi', label: '孤立图片', value: o.orphanImages, cls: o.orphanImages ? 'warn' : '' },
    { key: 'ol', label: '孤立标签', value: o.orphanLabels, cls: o.orphanLabels ? 'warn' : '' },
    { key: 'empty', label: '空标签', value: o.emptyLabels, cls: o.emptyLabels ? 'warn' : '' },
  ]
})

const classColor = (id) => CLASS_COLORS[id % CLASS_COLORS.length]

function loadHistoryFromStorage() {
  try {
    history.value = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]').slice(0, 8)
  } catch {
    history.value = []
  }
}

function saveHistory(entry) {
  history.value = [entry, ...history.value.filter((h) => h.datasetId !== entry.datasetId)].slice(0, 8)
  localStorage.setItem(HISTORY_KEY, JSON.stringify(history.value))
}

function loadHistory(h) {
  datasetId.value = h.datasetId
  report.value = h.report
  lastRun.value = h.time
  mode.value = h.mode || 'raw'
}

async function loadDatasets() {
  const res = await trainingApi.listDatasets({ pageNum: 1, pageSize: 100 })
  datasetOptions.value = (res.data.rows || []).filter((d) => d.format !== 'import' || d.sourcePath)
  if (props.initialDatasetId && !datasetId.value) {
    datasetId.value = props.initialDatasetId
  }
}

function onDatasetChange() {
  report.value = null
  lastRun.value = null
}

async function runAnalyze() {
  if (!datasetId.value) return
  if (mode.value === 'yaml' && !selectedDataset.value?.yamlPath) {
    ElMessage.warning('请先在「数据集管理」中构建数据集，再使用 YAML 模式')
    return
  }
  analyzing.value = true
  try {
    const res = await trainingApi.analyzeQuality(datasetId.value, { mode: mode.value })
    report.value = res.data.report
    lastRun.value = res.data.analyzedAt
    saveHistory({
      datasetId: datasetId.value,
      datasetName: selectedDataset.value?.name,
      time: res.data.analyzedAt,
      mode: mode.value,
      imageCount: res.data.report?.overview?.totalImages || 0,
      report: res.data.report,
    })
    ElMessage.success('分析完成')
  } catch {
    /* 拦截器已提示 */
  } finally {
    analyzing.value = false
  }
}

function exportReport() {
  if (!report.value) return
  const blob = new Blob([JSON.stringify(report.value, null, 2)], { type: 'application/json' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `quality_report_${datasetId.value}_${Date.now()}.json`
  a.click()
  URL.revokeObjectURL(a.href)
}

onMounted(() => {
  loadDatasets()
  loadHistoryFromStorage()
})

defineExpose({ setDatasetId: (id) => { datasetId.value = id } })
</script>

<style scoped>
.quality-root { min-height: 400px; }
.side-card, .result-card { margin-bottom: 12px; }
.card-hd {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 600;
  color: #3a4a63;
}
.hint-icon { color: #909399; cursor: help; }
.field-block { margin-bottom: 16px; }
.field-label { font-size: 13px; color: #606266; margin-bottom: 8px; font-weight: 500; }
.field-hint { font-size: 12px; color: #909399; margin-top: 6px; line-height: 1.5; }
.path-box {
  background: #f5f7fa;
  border-radius: 6px;
  padding: 10px 12px;
  margin-bottom: 16px;
  font-size: 12px;
}
.path-label { color: #909399; margin-bottom: 4px; }
.path-value { color: #303133; word-break: break-all; font-family: Consolas, monospace; }
.path-tag { margin-top: 6px; }
.run-btn { width: 100%; margin-bottom: 12px; }
.status-box { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 16px; }
.history-block { border-top: 1px solid #ebeef5; padding-top: 12px; }
.history-list { max-height: 200px; overflow-y: auto; }
.history-item {
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
  margin-bottom: 4px;
  border: 1px solid transparent;
}
.history-item:hover { background: #f5f7fa; border-color: #e4e7ed; }
.hi-name { font-size: 13px; font-weight: 500; color: #303133; }
.hi-meta { font-size: 12px; color: #909399; margin-top: 2px; }
.issue-alert { margin-bottom: 8px; }
.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}
@media (max-width: 768px) {
  .metric-grid { grid-template-columns: repeat(2, 1fr); }
}
.metric-item {
  background: #f5f7fa;
  border-radius: 8px;
  padding: 14px 12px;
  text-align: center;
}
.metric-item.ok .metric-val { color: #67c23a; }
.metric-item.warn .metric-val { color: #e6a23c; }
.metric-val { font-size: 22px; font-weight: 700; color: #303133; line-height: 1.2; }
.metric-lbl { font-size: 12px; color: #909399; margin-top: 4px; }
.detail-row { margin-top: 0; }
.class-dist { display: flex; flex-direction: column; gap: 10px; }
.dist-row { display: flex; align-items: center; gap: 10px; font-size: 13px; }
.dist-name { width: 120px; flex-shrink: 0; color: #606266; }
.dist-bar-wrap {
  flex: 1;
  height: 10px;
  background: #ebeef5;
  border-radius: 5px;
  overflow: hidden;
}
.dist-bar { height: 100%; border-radius: 5px; min-width: 2px; transition: width 0.3s; }
.dist-count { width: 100px; text-align: right; color: #909399; font-size: 12px; flex-shrink: 0; }
</style>
