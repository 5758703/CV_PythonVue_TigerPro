<template>
  <div class="tools-root">
    <div class="toolbar">
      <el-select v-model="datasetId" placeholder="选择数据集" style="width: 260px" @change="onDatasetChange">
        <el-option
          v-for="d in datasetOptions"
          :key="d.id"
          :label="`${d.name}（${d.classNames?.join(', ') || '未设类别'}）`"
          :value="d.id"
        />
      </el-select>
      <el-button :icon="Refresh" :disabled="!datasetId" :loading="loading" @click="reload">刷新状态</el-button>
    </div>

    <el-empty v-if="!datasetId" description="请选择数据集后使用四套独立标注工具" />

    <template v-else>
      <el-alert
        type="info"
        :closable="false"
        show-icon
        class="hint"
        title="四套工具独立运行：Web 写 raw/labels；X-AnyLabeling / CVAT / Roboflow 各有 tools/<名>/labels 工作区。训练前请将外接工具结果「回灌」到 raw/labels。"
      />

      <el-radio-group v-model="activeTool" class="tool-switch" @change="onToolChange">
        <el-radio-button value="web">内置 Web 画框</el-radio-button>
        <el-radio-button value="xanylabeling">X-AnyLabeling</el-radio-button>
        <el-radio-button value="cvat">CVAT</el-radio-button>
        <el-radio-button value="roboflow">Roboflow</el-radio-button>
      </el-radio-group>

      <!-- Web：嵌入原有画框，与其它工具隔离（直接写 raw） -->
      <div v-show="activeTool === 'web'" class="panel">
        <el-alert
          v-if="toolMap.web"
          :title="`工作区：raw/labels · 已标 ${toolMap.web.stats?.annotated || 0}/${toolMap.web.stats?.total || 0}`"
          type="success"
          :closable="false"
          class="panel-tip"
        />
        <AnnotatePanel ref="webRef" :initial-dataset-id="datasetId" />
      </div>

      <!-- X-AnyLabeling -->
      <div v-show="activeTool === 'xanylabeling'" class="panel">
        <el-card shadow="never">
          <template #header>
            <div class="card-head">
              <span>X-AnyLabeling（桌面独立工作区）</span>
              <el-tag size="small" :type="toolMap.xanylabeling?.config?.ready ? 'success' : 'info'">
                {{ toolMap.xanylabeling?.config?.message || '—' }}
              </el-tag>
            </div>
          </template>
          <p class="desc">导出图片包 → 本机 X-AnyLabeling 标注 → 导入 YOLO 标签到本工具区 → 可选回灌训练。</p>
          <div class="stats-row" v-if="toolMap.xanylabeling">
            <el-tag>图片 {{ toolMap.xanylabeling.stats?.total || 0 }}</el-tag>
            <el-tag type="success">工作区已标 {{ toolMap.xanylabeling.stats?.annotated || 0 }}</el-tag>
            <el-tag type="warning">框数 {{ toolMap.xanylabeling.stats?.totalBoxes || 0 }}</el-tag>
            <el-tag type="info">状态 {{ toolMap.xanylabeling.session?.state || 'idle' }}</el-tag>
          </div>
          <div class="actions">
            <el-button type="primary" :loading="busy" @click="exportXany">导出标注包</el-button>
            <el-upload :show-file-list="false" :auto-upload="false" accept=".zip,.txt" :on-change="(f) => importLabels('xanylabeling', f)">
              <el-button :loading="busy">导入 YOLO 标签</el-button>
            </el-upload>
            <el-button type="success" plain :loading="busy" @click="applyLabels('xanylabeling', 'merge')">回灌 raw（合并）</el-button>
            <el-button type="danger" plain :loading="busy" @click="applyLabels('xanylabeling', 'replace')">回灌 raw（覆盖）</el-button>
          </div>
          <el-link type="primary" href="https://github.com/CVHub520/X-AnyLabeling" target="_blank">X-AnyLabeling 项目</el-link>
        </el-card>
      </div>

      <!-- CVAT -->
      <div v-show="activeTool === 'cvat'" class="panel">
        <el-card shadow="never">
          <template #header>
            <div class="card-head">
              <span>CVAT（API 独立工作区）</span>
              <el-tag size="small" :type="toolMap.cvat?.config?.ready ? 'success' : 'warning'">
                {{ toolMap.cvat?.config?.ready ? '已配置' : (toolMap.cvat?.config?.message || '未配置') }}
              </el-tag>
            </div>
          </template>
          <p class="desc">推送图片到自托管 CVAT 标注 → 拉取 YOLO 到 tools/cvat/labels → 回灌训练。</p>
          <div class="stats-row" v-if="toolMap.cvat">
            <el-tag>图片 {{ toolMap.cvat.stats?.total || 0 }}</el-tag>
            <el-tag type="success">工作区已标 {{ toolMap.cvat.stats?.annotated || 0 }}</el-tag>
            <el-tag type="info">状态 {{ toolMap.cvat.session?.state || 'idle' }}</el-tag>
            <el-link v-if="toolMap.cvat.session?.taskUrl" type="primary" :href="toolMap.cvat.session.taskUrl" target="_blank">
              打开 CVAT 任务
            </el-link>
          </div>
          <div class="actions">
            <el-button type="primary" :loading="busy" :disabled="!toolMap.cvat?.config?.ready" @click="cvatPush">推送到 CVAT</el-button>
            <el-button :loading="busy" :disabled="!toolMap.cvat?.config?.ready" @click="cvatPull">拉取标注</el-button>
            <el-button type="success" plain :loading="busy" @click="applyLabels('cvat', 'merge')">回灌 raw（合并）</el-button>
            <el-button type="danger" plain :loading="busy" @click="applyLabels('cvat', 'replace')">回灌 raw（覆盖）</el-button>
            <el-upload :show-file-list="false" :auto-upload="false" accept=".zip,.txt" :on-change="(f) => importLabels('cvat', f)">
              <el-button :loading="busy">手动导入 YOLO</el-button>
            </el-upload>
          </div>
          <p class="cfg-hint">.env：CVAT_URL、CVAT_TOKEN（或 CVAT_USERNAME / CVAT_PASSWORD）</p>
        </el-card>
      </div>

      <!-- Roboflow -->
      <div v-show="activeTool === 'roboflow'" class="panel">
        <el-card shadow="never">
          <template #header>
            <div class="card-head">
              <span>Roboflow Annotate（API 独立工作区）</span>
              <el-tag size="small" :type="toolMap.roboflow?.config?.ready ? 'success' : 'warning'">
                {{ toolMap.roboflow?.config?.ready ? '已配置' : (toolMap.roboflow?.config?.message || '未配置') }}
              </el-tag>
            </div>
          </template>
          <p class="desc">上传到 Roboflow 云端标注 → 生成版本后下载 YOLO → tools/roboflow/labels → 回灌训练。</p>
          <div class="stats-row" v-if="toolMap.roboflow">
            <el-tag>图片 {{ toolMap.roboflow.stats?.total || 0 }}</el-tag>
            <el-tag type="success">工作区已标 {{ toolMap.roboflow.stats?.annotated || 0 }}</el-tag>
            <el-tag type="info">状态 {{ toolMap.roboflow.session?.state || 'idle' }}</el-tag>
            <el-link v-if="toolMap.roboflow.session?.annotateUrl" type="primary" :href="toolMap.roboflow.session.annotateUrl" target="_blank">
              打开 Roboflow 标注
            </el-link>
          </div>
          <div class="actions">
            <el-button type="primary" :loading="busy" :disabled="!toolMap.roboflow?.config?.ready" @click="rfPush">推送到 Roboflow</el-button>
            <el-input-number v-model="rfVersion" :min="1" :step="1" controls-position="right" style="width: 120px" />
            <el-button :loading="busy" :disabled="!toolMap.roboflow?.config?.ready" @click="rfPull">拉取版本</el-button>
            <el-button type="success" plain :loading="busy" @click="applyLabels('roboflow', 'merge')">回灌 raw（合并）</el-button>
            <el-button type="danger" plain :loading="busy" @click="applyLabels('roboflow', 'replace')">回灌 raw（覆盖）</el-button>
            <el-upload :show-file-list="false" :auto-upload="false" accept=".zip,.txt" :on-change="(f) => importLabels('roboflow', f)">
              <el-button :loading="busy">手动导入 YOLO</el-button>
            </el-upload>
          </div>
          <p class="cfg-hint">.env：ROBOFLOW_API_KEY、可选 ROBOFLOW_WORKSPACE</p>
        </el-card>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { trainingApi } from '../../../api/ai'
import AnnotatePanel from './annotate.vue'

const props = defineProps({
  initialDatasetId: { type: Number, default: null },
})

const datasetOptions = ref([])
const datasetId = ref(props.initialDatasetId)
const tools = ref([])
const activeTool = ref('web')
const loading = ref(false)
const busy = ref(false)
const webRef = ref(null)
const rfVersion = ref(1)

const toolMap = computed(() => {
  const m = {}
  for (const t of tools.value) m[t.id] = t
  return m
})

async function loadDatasets() {
  const res = await trainingApi.listDatasets({ pageNum: 1, pageSize: 100 })
  datasetOptions.value = (res.data.rows || []).filter((d) => d.format !== 'import')
}

async function reload() {
  if (!datasetId.value) return
  loading.value = true
  try {
    const res = await trainingApi.annotateTools(datasetId.value)
    tools.value = res.data.tools || []
  } catch (e) {
    ElMessage.error(e?.response?.data?.message || e.message || '加载工具状态失败')
  } finally {
    loading.value = false
  }
}

function onDatasetChange() {
  webRef.value?.setDatasetId?.(datasetId.value)
  reload()
}

function onToolChange() {
  if (activeTool.value === 'web') {
    webRef.value?.setDatasetId?.(datasetId.value)
  }
}

function setDatasetId(id) {
  datasetId.value = id
  webRef.value?.setDatasetId?.(id)
  reload()
}

async function exportXany() {
  if (!datasetId.value) return
  busy.value = true
  try {
    const blob = await trainingApi.annotateToolExport(datasetId.value, 'xanylabeling')
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `xany_dataset_${datasetId.value}.zip`
    a.click()
    URL.revokeObjectURL(url)
    ElMessage.success('已导出 X-AnyLabeling 标注包')
    await reload()
  } catch (e) {
    ElMessage.error(e?.response?.data?.message || e.message || '导出失败')
  } finally {
    busy.value = false
  }
}

async function importLabels(tool, uploadFile) {
  const raw = uploadFile.raw
  if (!raw) return
  busy.value = true
  try {
    const fd = new FormData()
    fd.append('file', raw)
    const res = await trainingApi.annotateToolImport(datasetId.value, tool, fd)
    ElMessage.success(res.message || `已导入 ${res.data?.imported || 0} 个标签`)
    await reload()
  } catch (e) {
    ElMessage.error(e?.response?.data?.message || e.message || '导入失败')
  } finally {
    busy.value = false
  }
}

async function applyLabels(tool, mode) {
  try {
    await ElMessageBox.confirm(
      mode === 'replace'
        ? '将用该工具工作区标签覆盖 raw/labels，是否继续？'
        : '将合并写入 raw/labels（同名文件覆盖），是否继续？',
      '回灌确认',
      { type: 'warning' },
    )
  } catch (_) {
    return
  }
  busy.value = true
  try {
    const res = await trainingApi.annotateToolApply(datasetId.value, tool, { mode })
    ElMessage.success(res.message || `已回灌 ${res.data?.applied || 0} 个文件`)
    await reload()
  } catch (e) {
    ElMessage.error(e?.response?.data?.message || e.message || '回灌失败')
  } finally {
    busy.value = false
  }
}

async function cvatPush() {
  busy.value = true
  try {
    const res = await trainingApi.annotateCvatPush(datasetId.value)
    ElMessage.success(res.message || '已推送')
    await reload()
  } catch (e) {
    ElMessage.error(e?.response?.data?.message || e.message || 'CVAT 推送失败')
  } finally {
    busy.value = false
  }
}

async function cvatPull() {
  busy.value = true
  try {
    const res = await trainingApi.annotateCvatPull(datasetId.value)
    ElMessage.success(res.message || '已拉取')
    await reload()
  } catch (e) {
    ElMessage.error(e?.response?.data?.message || e.message || 'CVAT 拉取失败')
  } finally {
    busy.value = false
  }
}

async function rfPush() {
  busy.value = true
  try {
    const res = await trainingApi.annotateRoboflowPush(datasetId.value)
    ElMessage.success(res.message || '已推送')
    await reload()
  } catch (e) {
    ElMessage.error(e?.response?.data?.message || e.message || 'Roboflow 推送失败')
  } finally {
    busy.value = false
  }
}

async function rfPull() {
  busy.value = true
  try {
    const res = await trainingApi.annotateRoboflowPull(datasetId.value, { version: rfVersion.value })
    ElMessage.success(res.message || '已拉取')
    await reload()
  } catch (e) {
    ElMessage.error(e?.response?.data?.message || e.message || 'Roboflow 拉取失败')
  } finally {
    busy.value = false
  }
}

watch(
  () => props.initialDatasetId,
  (id) => {
    if (id) setDatasetId(id)
  },
)

onMounted(async () => {
  await loadDatasets()
  if (datasetId.value) {
    webRef.value?.setDatasetId?.(datasetId.value)
    await reload()
  }
})

defineExpose({ setDatasetId })
</script>

<style scoped>
.tools-root { min-height: 420px; }
.toolbar { display: flex; gap: 10px; margin-bottom: 12px; align-items: center; }
.hint { margin-bottom: 12px; }
.tool-switch { margin-bottom: 14px; }
.panel { margin-top: 4px; }
.panel-tip { margin-bottom: 10px; }
.card-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.desc { color: #5a6b87; font-size: 13px; margin: 0 0 10px; }
.stats-row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 12px; }
.actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 10px; }
.cfg-hint { font-size: 12px; color: #909399; margin: 0; }
</style>
