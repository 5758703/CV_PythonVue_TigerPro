<template>
  <div class="training-root">
    <el-tabs v-model="activeTab" type="border-card">
      <!-- ── 数据集管理 ── -->
      <el-tab-pane label="数据集管理" name="dataset">
        <div class="toolbar">
          <el-input v-model="dsQuery.name" placeholder="数据集名称" clearable style="width:200px" @keyup.enter="loadDatasets" />
          <el-button type="primary" :icon="Plus" @click="openDsDialog()">新建数据集</el-button>
          <el-button :icon="Refresh" @click="loadDatasets">刷新</el-button>
        </div>
        <el-table :data="datasets" v-loading="dsLoading" border stripe>
          <el-table-column prop="name" label="名称" min-width="140" />
          <el-table-column label="类别" min-width="160">
            <template #default="{ row }">
              <el-tag v-for="c in row.classNames" :key="c" size="small" style="margin:2px">{{ c }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="样本" width="120">
            <template #default="{ row }">{{ row.trainCount }} / {{ row.valCount }}</template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="dsStatusType(row.status)" size="small">{{ dsStatusText(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="createTime" label="创建时间" width="170" />
          <el-table-column label="操作" width="320" fixed="right">
            <template #default="{ row }">
              <el-upload :show-file-list="false" :auto-upload="false" multiple accept=".jpg,.jpeg,.png,.xml"
                :on-change="(f) => onDsUpload(row, f)" style="display:inline-block;margin-right:8px">
                <el-button size="small" :icon="Upload">上传</el-button>
              </el-upload>
              <el-button size="small" type="success" :loading="row._building" @click="buildDs(row)">构建</el-button>
              <el-button size="small" :icon="Edit" @click="openDsDialog(row)">编辑</el-button>
              <el-button size="small" type="danger" :icon="Delete" @click="removeDs(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-pagination class="pager" v-model:current-page="dsPage" v-model:page-size="dsSize"
          :total="dsTotal" layout="total, prev, pager, next" @current-change="loadDatasets" />
      </el-tab-pane>

      <!-- ── 训练任务 ── -->
      <el-tab-pane label="训练任务" name="job">
        <div class="toolbar">
          <el-select v-model="jobQuery.status" placeholder="状态" clearable style="width:130px" @change="loadJobs">
            <el-option label="待训练" value="pending" />
            <el-option label="训练中" value="running" />
            <el-option label="已完成" value="done" />
            <el-option label="失败" value="failed" />
            <el-option label="已取消" value="cancelled" />
          </el-select>
          <el-button type="primary" :icon="Plus" @click="openJobDialog()">新建任务</el-button>
          <el-button :icon="Refresh" @click="loadJobs">刷新</el-button>
        </div>
        <el-table :data="jobs" v-loading="jobLoading" border stripe>
          <el-table-column prop="jobName" label="任务名称" min-width="140" />
          <el-table-column prop="datasetName" label="数据集" min-width="120" />
          <el-table-column prop="baseModel" label="基座模型" width="120" />
          <el-table-column label="进度" min-width="180">
            <template #default="{ row }">
              <el-progress :percentage="row.progress || 0" :status="jobProgressStatus(row)" />
              <span class="epoch-hint" v-if="row.status === 'running'">
                {{ row.currentEpoch }} / {{ row.totalEpochs }} epoch
              </span>
            </template>
          </el-table-column>
          <el-table-column label="mAP50" width="90">
            <template #default="{ row }">
              {{ fmtMetric(row.latestMetrics, 'metrics/mAP50(B)') }}
            </template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="jobStatusType(row.status)" size="small">{{ jobStatusText(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="300" fixed="right">
            <template #default="{ row }">
              <el-button size="small" type="primary" v-if="row.status === 'pending' || row.status === 'failed'"
                @click="startJob(row)">启动</el-button>
              <el-button size="small" type="warning" v-if="row.status === 'running'" @click="cancelJob(row)">取消</el-button>
              <el-button size="small" @click="openJobDetail(row)">监控</el-button>
              <el-button size="small" type="danger" :icon="Delete" @click="removeJob(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-pagination class="pager" v-model:current-page="jobPage" v-model:page-size="jobSize"
          :total="jobTotal" layout="total, prev, pager, next" @current-change="loadJobs" />
      </el-tab-pane>
    </el-tabs>

    <!-- 数据集对话框 -->
    <el-dialog v-model="dsDialog" :title="dsForm.id ? '编辑数据集' : '新建数据集'" width="520px" @closed="resetDsForm">
      <el-form :model="dsForm" label-width="100px">
        <el-form-item label="名称" required>
          <el-input v-model="dsForm.name" placeholder="如：水位尺数据集" />
        </el-form-item>
        <el-form-item label="类别" required>
          <el-select v-model="dsForm.classNames" multiple filterable allow-create default-first-option
            placeholder="输入类别名后回车，如 WaterGuage" style="width:100%" />
        </el-form-item>
        <el-form-item label="训练比例">
          <el-slider v-model="dsForm.splitRatio" :min="0.5" :max="0.95" :step="0.05" show-input />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="dsForm.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-alert type="info" :closable="false" title="支持 Pascal VOC 格式：每张图片配合同名 .xml 标注文件。" />
      </el-form>
      <template #footer>
        <el-button @click="dsDialog = false">取消</el-button>
        <el-button type="primary" :loading="dsSaving" @click="saveDs">保存</el-button>
      </template>
    </el-dialog>

    <!-- 新建训练任务 -->
    <el-dialog v-model="jobDialog" title="新建训练任务" width="560px" @closed="resetJobForm">
      <el-form :model="jobForm" label-width="100px">
        <el-form-item label="任务名称" required>
          <el-input v-model="jobForm.jobName" placeholder="如：水位尺-v1" />
        </el-form-item>
        <el-form-item label="数据集" required>
          <el-select v-model="jobForm.datasetId" placeholder="选择已构建的数据集" style="width:100%">
            <el-option v-for="d in readyDatasets" :key="d.id" :label="`${d.name} (${d.trainCount}/${d.valCount})`" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="基座模型">
          <el-select v-model="jobForm.baseModel" style="width:100%">
            <el-option label="YOLOv8n（轻量）" value="yolov8n.pt" />
            <el-option label="YOLOv8s" value="yolov8s.pt" />
            <el-option label="YOLOv8m" value="yolov8m.pt" />
          </el-select>
        </el-form-item>
        <el-form-item label="训练轮数">
          <el-input-number v-model="jobForm.epochs" :min="1" :max="500" />
        </el-form-item>
        <el-form-item label="Batch">
          <el-input-number v-model="jobForm.batch" :min="1" :max="64" />
        </el-form-item>
        <el-form-item label="图像尺寸">
          <el-input-number v-model="jobForm.imgsz" :min="320" :max="1280" :step="32" />
        </el-form-item>
        <el-form-item label="设备">
          <el-radio-group v-model="jobForm.device">
            <el-radio value="cpu">CPU</el-radio>
            <el-radio value="0">GPU (cuda:0)</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="jobDialog = false">取消</el-button>
        <el-button type="primary" :loading="jobSaving" @click="saveJob">创建</el-button>
      </template>
    </el-dialog>

    <!-- 训练监控抽屉 -->
    <el-drawer v-model="detailOpen" :title="`训练监控 — ${detailJob?.jobName || ''}`" size="72%" destroy-on-close>
      <div v-if="detailJob" class="detail-wrap">
        <el-row :gutter="16">
          <el-col :span="14">
            <el-card shadow="never">
              <template #header>训练进度</template>
              <el-progress :percentage="detailJob.progress || 0" :stroke-width="18" :text-inside="true"
                :status="detailJob.status === 'done' ? 'success' : ''" />
              <div class="detail-meta">
                <span>Epoch: {{ detailJob.currentEpoch }} / {{ detailJob.totalEpochs }}</span>
                <el-tag :type="jobStatusType(detailJob.status)" size="small">{{ jobStatusText(detailJob.status) }}</el-tag>
              </div>
              <div v-if="detailJob.errorMessage" class="err-msg">{{ detailJob.errorMessage }}</div>

              <el-card shadow="never" class="mt16">
                <template #header>训练日志（实时）</template>
                <el-scrollbar height="220px" class="log-box">
                  <pre class="log-pre">{{ trainLogText || '（暂无日志）' }}</pre>
                </el-scrollbar>
              </el-card>

              <div class="chart-grid" v-if="chartUrls.length">
                <div v-for="c in chartUrls" :key="c.name" class="chart-item">
                  <div class="chart-title">{{ c.label }}</div>
                  <img :src="c.url" class="chart-img" />
                </div>
              </div>
              <el-empty v-else description="训练完成后可查看 loss/mAP 曲线图" />
            </el-card>

            <el-card shadow="never" class="mt16">
              <template #header>指标历史</template>
              <el-table :data="metricsRows" size="small" border max-height="280">
                <el-table-column prop="epoch" label="Epoch" width="70" />
                <el-table-column label="box_loss" width="90">
                  <template #default="{ row }">{{ row['train/box_loss'] ?? '-' }}</template>
                </el-table-column>
                <el-table-column label="cls_loss" width="90">
                  <template #default="{ row }">{{ row['train/cls_loss'] ?? '-' }}</template>
                </el-table-column>
                <el-table-column label="mAP50" width="90">
                  <template #default="{ row }">{{ row['metrics/mAP50(B)'] ?? row.mAP50 ?? '-' }}</template>
                </el-table-column>
                <el-table-column label="mAP50-95" width="100">
                  <template #default="{ row }">{{ row['metrics/mAP50-95(B)'] ?? row['mAP50-95'] ?? '-' }}</template>
                </el-table-column>
              </el-table>
            </el-card>
          </el-col>

          <el-col :span="10">
            <!-- 验证 -->
            <el-card shadow="never">
              <template #header>模型验证</template>
              <el-button type="primary" :loading="validating" :disabled="detailJob.status !== 'done'"
                @click="runValidate">在验证集上评估</el-button>
              <el-progress v-if="valProgress.status && valProgress.status !== 'idle'"
                :percentage="valProgress.progress || 0" class="mt12" />
              <el-scrollbar height="180px" class="log-box mt12">
                <pre class="log-pre">{{ valLogText || '（暂无验证日志）' }}</pre>
              </el-scrollbar>
              <el-descriptions v-if="valResult" :column="1" border size="small" class="mt12">
                <el-descriptions-item v-for="(v, k) in valResult" :key="k" :label="k">{{ v }}</el-descriptions-item>
              </el-descriptions>
            </el-card>

            <!-- 测试 -->
            <el-card shadow="never" class="mt16">
              <template #header>模型测试</template>
              <el-upload :show-file-list="false" :auto-upload="false" accept="image/*" :on-change="onTestPick">
                <el-button :icon="Upload" :disabled="detailJob.status !== 'done'">选择测试图</el-button>
              </el-upload>
              <el-button class="ml8" type="primary" :loading="testing" :disabled="!testFile || detailJob.status !== 'done'"
                @click="runTest">推理测试</el-button>
              <div v-if="testResult?.imageBase64" class="test-preview">
                <img :src="'data:image/jpeg;base64,' + testResult.imageBase64" />
                <p>检出 {{ testResult.count }} 个目标</p>
              </div>
            </el-card>

            <!-- 导出 -->
            <el-card shadow="never" class="mt16">
              <template #header>模型导出</template>
              <el-radio-group v-model="exportFmt">
                <el-radio value="onnx">ONNX</el-radio>
                <el-radio value="torchscript">TorchScript</el-radio>
              </el-radio-group>
              <el-button class="ml8" type="success" :loading="exporting" :disabled="detailJob.status !== 'done'"
                @click="runExport">导出</el-button>
              <div v-if="exportInfo" class="export-info">
                <span>{{ exportInfo.fileName }} ({{ fmtSize(exportInfo.size) }})</span>
                <el-button link type="primary" @click="downloadExport">下载</el-button>
              </div>
            </el-card>

            <!-- 部署 -->
            <el-card shadow="never" class="mt16">
              <template #header>部署到模型管理</template>
              <el-form :model="deployForm" label-width="80px" size="small">
                <el-form-item label="模型名称">
                  <el-input v-model="deployForm.modelName" />
                </el-form-item>
                <el-form-item label="模型标识">
                  <el-input v-model="deployForm.modelKey" placeholder="唯一 key，如 water-gauge-v1" />
                </el-form-item>
                <el-form-item label="分类">
                  <el-input v-model="deployForm.category" />
                </el-form-item>
              </el-form>
              <el-button type="primary" :loading="deploying" :disabled="detailJob.status !== 'done'"
                @click="runDeploy">注册到模型管理</el-button>
              <el-tag v-if="detailJob.outputModelId" type="success" class="ml8">已部署 #{{ detailJob.outputModelId }}</el-tag>
            </el-card>
          </el-col>
        </el-row>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh, Edit, Delete, Upload } from '@element-plus/icons-vue'
import { trainingApi } from '../../../api/ai'

const activeTab = ref('dataset')

// ── 数据集 ──
const dsLoading = ref(false)
const datasets = ref([])
const dsPage = ref(1)
const dsSize = ref(10)
const dsTotal = ref(0)
const dsQuery = reactive({ name: '' })
const dsDialog = ref(false)
const dsSaving = ref(false)
const dsForm = reactive({ id: null, name: '', classNames: [], splitRatio: 0.8, description: '' })

const readyDatasets = computed(() => datasets.value.filter(d => d.status === 'ready'))

function dsStatusType(s) {
  return { draft: 'info', ready: 'success', error: 'danger' }[s] || 'info'
}
function dsStatusText(s) {
  return { draft: '草稿', ready: '就绪', error: '错误' }[s] || s
}

async function loadDatasets() {
  dsLoading.value = true
  try {
    const res = await trainingApi.listDatasets({ pageNum: dsPage.value, pageSize: dsSize.value, name: dsQuery.name })
    datasets.value = res.data.rows
    dsTotal.value = res.data.total
  } finally { dsLoading.value = false }
}

function openDsDialog(row) {
  if (row) {
    Object.assign(dsForm, { id: row.id, name: row.name, classNames: [...row.classNames],
      splitRatio: row.splitRatio, description: row.description || '' })
  } else {
    resetDsForm()
  }
  dsDialog.value = true
}

function resetDsForm() {
  Object.assign(dsForm, { id: null, name: '', classNames: [], splitRatio: 0.8, description: '' })
}

async function saveDs() {
  if (!dsForm.name || !dsForm.classNames.length) {
    ElMessage.warning('请填写名称和类别')
    return
  }
  dsSaving.value = true
  try {
    const payload = { name: dsForm.name, classNames: dsForm.classNames,
      splitRatio: dsForm.splitRatio, description: dsForm.description }
    if (dsForm.id) {
      await trainingApi.updateDataset(dsForm.id, payload)
      ElMessage.success('更新成功')
    } else {
      await trainingApi.addDataset(payload)
      ElMessage.success('创建成功，请上传 VOC 标注并构建')
    }
    dsDialog.value = false
    loadDatasets()
  } finally { dsSaving.value = false }
}

async function onDsUpload(row, uploadFile) {
  const fd = new FormData()
  fd.append('files', uploadFile.raw)
  try {
    const res = await trainingApi.uploadDatasetFiles(row.id, fd)
    ElMessage.success(res.message || '上传成功')
  } catch (e) {
    ElMessage.error(e.message || '上传失败')
  }
}

async function buildDs(row) {
  row._building = true
  try {
    const res = await trainingApi.buildDataset(row.id)
    ElMessage.success(res.message)
    loadDatasets()
  } catch (e) {
    ElMessage.error(e.message || '构建失败')
  } finally { row._building = false }
}

async function removeDs(row) {
  await ElMessageBox.confirm(`确定删除数据集「${row.name}」？`, '提示', { type: 'warning' })
  await trainingApi.removeDataset(row.id)
  ElMessage.success('已删除')
  loadDatasets()
}

// ── 训练任务 ──
const jobLoading = ref(false)
const jobs = ref([])
const jobPage = ref(1)
const jobSize = ref(10)
const jobTotal = ref(0)
const jobQuery = reactive({ status: '' })
const jobDialog = ref(false)
const jobSaving = ref(false)
const jobForm = reactive({
  jobName: '', datasetId: null, baseModel: 'yolov8n.pt',
  epochs: 100, batch: 8, imgsz: 640, device: 'cpu'
})

function jobStatusType(s) {
  return { pending: 'info', running: 'warning', done: 'success', failed: 'danger', cancelled: '' }[s] || 'info'
}
function jobStatusText(s) {
  return { pending: '待训练', running: '训练中', done: '已完成', failed: '失败', cancelled: '已取消' }[s] || s
}
function jobProgressStatus(row) {
  if (row.status === 'done') return 'success'
  if (row.status === 'failed') return 'exception'
  return ''
}
function fmtMetric(m, key) {
  if (!m || m[key] == null) return '-'
  return Number(m[key]).toFixed(4)
}
function fmtSize(n) {
  if (!n) return '0 B'
  if (n < 1024) return n + ' B'
  if (n < 1048576) return (n / 1024).toFixed(1) + ' KB'
  return (n / 1048576).toFixed(1) + ' MB'
}

async function loadJobs() {
  jobLoading.value = true
  try {
    const res = await trainingApi.listJobs({ pageNum: jobPage.value, pageSize: jobSize.value, status: jobQuery.status })
    jobs.value = res.data.rows
    jobTotal.value = res.data.total
  } finally { jobLoading.value = false }
}

function openJobDialog() {
  resetJobForm()
  jobDialog.value = true
  loadDatasets()
}

function resetJobForm() {
  Object.assign(jobForm, {
    jobName: '', datasetId: null, baseModel: 'yolov8n.pt',
    epochs: 100, batch: 8, imgsz: 640, device: 'cpu'
  })
}

async function saveJob() {
  if (!jobForm.jobName || !jobForm.datasetId) {
    ElMessage.warning('请填写任务名称并选择数据集')
    return
  }
  jobSaving.value = true
  try {
    await trainingApi.addJob({ ...jobForm })
    ElMessage.success('任务已创建，点击「启动」开始训练')
    jobDialog.value = false
    loadJobs()
  } finally { jobSaving.value = false }
}

async function startJob(row) {
  await trainingApi.startJob(row.id)
  ElMessage.success('训练已启动')
  loadJobs()
  openJobDetail(row)
}

async function cancelJob(row) {
  await trainingApi.cancelJob(row.id)
  ElMessage.info('已发送取消请求')
  loadJobs()
}

async function removeJob(row) {
  await ElMessageBox.confirm(`确定删除任务「${row.jobName}」？`, '提示', { type: 'warning' })
  await trainingApi.removeJob(row.id)
  ElMessage.success('已删除')
  loadJobs()
}

// ── 训练监控 ──
const detailOpen = ref(false)
const detailJob = ref(null)
const chartUrls = ref([])
const metricsRows = ref([])
let pollTimer = null
const chartBlobUrls = []
const trainLogText = ref('')
const valLogText = ref('')
let trainLogOffset = 0
let valLogOffset = 0
const valProgress = ref({ status: 'idle', progress: 0 })

const CHART_LABELS = {
  'results.png': '训练曲线',
  'confusion_matrix.png': '混淆矩阵',
  'F1_curve.png': 'F1 曲线',
  'PR_curve.png': 'PR 曲线'
}

async function refreshDetail() {
  if (!detailJob.value) return
  const res = await trainingApi.jobProgress(detailJob.value.id)
  detailJob.value = res.data
  chartBlobUrls.forEach(u => URL.revokeObjectURL(u))
  chartBlobUrls.length = 0
  const charts = []
  for (const [name, _path] of Object.entries(res.data.charts || {})) {
    try {
      const blob = await trainingApi.getArtifact(detailJob.value.id, name)
      const url = URL.createObjectURL(blob)
      chartBlobUrls.push(url)
      charts.push({ name, label: CHART_LABELS[name] || name, url })
    } catch { /* 图表尚未生成 */ }
  }
  chartUrls.value = charts
  metricsRows.value = (res.data.metricsHistory || []).map((r, i) => ({
    epoch: r.epoch ?? i + 1, ...r
  }))
}

async function refreshLogs() {
  if (!detailJob.value) return
  try {
    const r1 = await trainingApi.jobLogs(detailJob.value.id, { type: 'train', offset: trainLogOffset, limit: 8000 })
    if (r1.data?.text) {
      trainLogText.value += r1.data.text
      trainLogOffset = r1.data.nextOffset ?? trainLogOffset
    }
  } catch {}
  try {
    const r2 = await trainingApi.jobLogs(detailJob.value.id, { type: 'val', offset: valLogOffset, limit: 8000 })
    if (r2.data?.text) {
      valLogText.value += r2.data.text
      valLogOffset = r2.data.nextOffset ?? valLogOffset
    }
  } catch {}
}

async function openJobDetail(row) {
  detailJob.value = { ...row }
  detailOpen.value = true
  valResult.value = null
  testResult.value = null
  exportInfo.value = null
  trainLogText.value = ''
  valLogText.value = ''
  trainLogOffset = 0
  valLogOffset = 0
  valProgress.value = { status: 'idle', progress: 0 }
  await refreshDetail()
  await refreshLogs()
  startPoll()
}

function startPoll() {
  stopPoll()
  if (!detailJob.value || !['running', 'pending'].includes(detailJob.value.status)) return
  pollTimer = setInterval(async () => {
    await refreshDetail()
    await refreshLogs()
    loadJobs()
    if (detailJob.value && !['running', 'pending'].includes(detailJob.value.status)) {
      stopPoll()
      loadJobs()
    }
  }, 3000)
}

function stopPoll() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

watch(detailOpen, (v) => {
  if (!v) {
    stopPoll()
    chartBlobUrls.forEach(u => URL.revokeObjectURL(u))
    chartBlobUrls.length = 0
    trainLogText.value = ''
    valLogText.value = ''
    trainLogOffset = 0
    valLogOffset = 0
  }
})
onBeforeUnmount(() => {
  stopPoll()
  chartBlobUrls.forEach(u => URL.revokeObjectURL(u))
})

// 验证 / 测试 / 导出 / 部署
const validating = ref(false)
const valResult = ref(null)
const testing = ref(false)
const testFile = ref(null)
const testResult = ref(null)
const exporting = ref(false)
const exportFmt = ref('onnx')
const exportInfo = ref(null)
const deploying = ref(false)
const deployForm = reactive({ modelName: '', modelKey: '', category: '自定义训练' })

async function runValidate() {
  validating.value = true
  try {
    await trainingApi.validateJob(detailJob.value.id)
    ElMessage.success('验证已启动')
    const jid = detailJob.value.id
    for (let i = 0; i < 200; i++) {
      await refreshLogs()
      const p = await trainingApi.validateProgress(jid)
      valProgress.value = p.data
      if (p.data.status === 'done') {
        valResult.value = p.data.result
        ElMessage.success('验证完成')
        break
      }
      if (p.data.status === 'error') {
        ElMessage.error(p.data.error || '验证失败')
        break
      }
      await new Promise(r => setTimeout(r, 1500))
    }
  } finally { validating.value = false }
}

function onTestPick(f) { testFile.value = f.raw }

async function runTest() {
  if (!testFile.value) return
  testing.value = true
  try {
    const fd = new FormData()
    fd.append('image', testFile.value)
    const res = await trainingApi.testJob(detailJob.value.id, fd)
    testResult.value = res.data
  } finally { testing.value = false }
}

async function runExport() {
  exporting.value = true
  try {
    const res = await trainingApi.exportJob(detailJob.value.id, { format: exportFmt.value })
    exportInfo.value = res.data
    ElMessage.success('导出成功')
  } finally { exporting.value = false }
}

async function downloadExport() {
  if (!exportInfo.value?.fileName) return
  const blob = await trainingApi.downloadExportFile(detailJob.value.id, exportInfo.value.fileName)
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = exportInfo.value.fileName
  a.click()
  URL.revokeObjectURL(url)
}

async function runDeploy() {
  if (!deployForm.modelName || !deployForm.modelKey) {
    ElMessage.warning('请填写模型名称和标识')
    return
  }
  deploying.value = true
  try {
    const res = await trainingApi.deployJob(detailJob.value.id, { ...deployForm })
    ElMessage.success(res.message)
    detailJob.value.outputModelId = res.data.modelId
    loadJobs()
  } finally { deploying.value = false }
}

watch(detailOpen, (v) => {
  if (v && detailJob.value) {
    deployForm.modelName = detailJob.value.jobName
    deployForm.modelKey = `custom-${detailJob.value.id}`
  }
})

onMounted(() => {
  loadDatasets()
  loadJobs()
})
</script>

<style scoped>
.training-root { padding: 0; }
.toolbar { display: flex; gap: 10px; margin-bottom: 14px; flex-wrap: wrap; align-items: center; }
.pager { margin-top: 14px; justify-content: flex-end; }
.epoch-hint { font-size: 12px; color: #909399; margin-left: 8px; }
.mt16 { margin-top: 16px; }
.ml8 { margin-left: 8px; }
.detail-wrap { padding: 0 4px; }
.detail-meta { display: flex; justify-content: space-between; align-items: center; margin-top: 12px; }
.err-msg { color: #f56c6c; font-size: 13px; margin-top: 8px; }
.chart-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 16px; }
.chart-item { border: 1px solid #ebeef5; border-radius: 6px; padding: 8px; }
.chart-title { font-size: 13px; color: #606266; margin-bottom: 6px; }
.chart-img { width: 100%; border-radius: 4px; }
.log-box { border: 1px solid #ebeef5; border-radius: 6px; padding: 6px 8px; background: #0b1020; }
.log-pre { margin: 0; color: #d4e2ff; font-size: 12px; line-height: 1.45; white-space: pre-wrap; word-break: break-word; }
.test-preview { margin-top: 12px; }
.test-preview img { max-width: 100%; border-radius: 6px; border: 1px solid #ebeef5; }
.test-preview p { font-size: 13px; color: #606266; margin-top: 6px; }
.export-info { margin-top: 10px; font-size: 13px; display: flex; align-items: center; gap: 8px; }
.mt12 { margin-top: 12px; }
</style>
