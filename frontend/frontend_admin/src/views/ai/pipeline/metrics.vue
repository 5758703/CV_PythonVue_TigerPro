<template>
  <div class="metrics-page">
    <div class="metrics-hd">
      <div>
        <h2 class="metrics-title">正在运行的场景任务 <span class="count">{{ summary.running }} 个任务</span></h2>
        <p class="metrics-desc">EVA 流水线实时指标 · FPS / 断流 / 告警 / MQTT / VLM / MTMC</p>
      </div>
      <div class="metrics-acts">
        <el-button size="small" @click="load">刷新</el-button>
        <el-button size="small" type="primary" @click="$router.push('/ai/pipeline')">全部任务 →</el-button>
      </div>
    </div>

    <el-row :gutter="12" class="mb">
      <el-col :span="6" v-for="c in cards" :key="c.label">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-label">{{ c.label }}</div>
          <div class="stat-value" :style="{ color: c.color }">{{ c.value }}</div>
        </el-card>
      </el-col>
    </el-row>

    <div class="task-grid mb" v-if="live.length">
      <div v-for="row in live" :key="row.runKey" class="task-card">
        <div class="task-hd">
          <strong>{{ row.displayTitle || taskTitle(row) }}</strong>
          <span class="running"><i class="dot" />运行中</span>
        </div>
        <el-tag size="small" type="primary" effect="plain" class="cv-tag">CV</el-tag>
        <div class="task-metrics">
          <div>
            <div class="m-label">今日告警</div>
            <div class="m-alert">{{ row.stats?.alerts ?? 0 }}</div>
          </div>
          <div>
            <div class="m-label">运行路数</div>
            <div class="m-val">{{ row.cameraId ? 1 : 0 }}路</div>
          </div>
          <div>
            <div class="m-label">FPS</div>
            <div class="m-val">{{ row.stats?.lastFps ?? '-' }}</div>
          </div>
        </div>
        <ul class="task-desc">
          <li>相机 #{{ row.cameraId }} · {{ row.runKey }}</li>
          <li v-if="row.stats?.sourceStalled">源断流重连中（reconnects {{ row.stats?.reconnects || 0 }}）</li>
          <li v-else>MQTT {{ row.stats?.mqttOk ?? 0 }}/{{ row.stats?.mqttFail ?? 0 }} · VLM ✓{{ row.stats?.vlmConfirm ?? 0 }}</li>
        </ul>
        <div class="task-acts">
          <el-button type="primary" size="small" @click="$router.push('/ai/pipeline')">查看运行</el-button>
          <el-button size="small" @click="stopOne(row)">停止</el-button>
        </div>
      </div>
    </div>
    <el-empty v-else class="mb" description="暂无运行中的流水线" :image-size="64" />

    <el-card shadow="never">
      <template #header><span>近期运行历史</span></template>
      <el-table :data="history" size="small" border stripe max-height="360">
        <el-table-column prop="runKey" label="runKey" min-width="130" show-overflow-tooltip />
        <el-table-column label="任务" min-width="120" show-overflow-tooltip>
          <template #default="{ row }">{{ row.displayTitle || row.pipelineName || row.pipelineId }}</template>
        </el-table-column>
        <el-table-column prop="pipelineId" label="ID" width="60" />
        <el-table-column prop="cameraId" label="相机" width="70" />
        <el-table-column prop="state" label="状态" width="90" />
        <el-table-column label="FPS" width="70">
          <template #default="{ row }">{{ row.metrics?.lastFps ?? '-' }}</template>
        </el-table-column>
        <el-table-column label="告警" width="70">
          <template #default="{ row }">{{ row.metrics?.alerts ?? '-' }}</template>
        </el-table-column>
        <el-table-column label="模式" width="80">
          <template #default="{ row }">{{ row.metrics?.mode || '-' }}</template>
        </el-table-column>
        <el-table-column prop="startedAt" label="开始" min-width="150" show-overflow-tooltip />
        <el-table-column prop="errorMessage" label="错误" min-width="120" show-overflow-tooltip />
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { pipelineApi } from '../../../api/pipeline'

const live = ref([])
const history = ref([])
const summary = ref({ running: 0, stalled: 0, liveAlerts: 0, historyCount: 0 })
let timer = null

const cards = computed(() => [
  { label: '运行中', value: summary.value.running, color: '#409eff' },
  { label: '断流中', value: summary.value.stalled, color: '#f56c6c' },
  { label: '实时告警累计', value: summary.value.liveAlerts, color: '#e6a23c' },
  { label: '历史条数', value: summary.value.historyCount, color: '#67c23a' },
])

function taskTitle(row) {
  const name = row.pipelineName || (row.mode === 'mtmc' ? 'MTMC复合' : '流水线')
  const n = row.taskIndex || row.pipelineId || 1
  return `${name}#${n}`
}

async function load() {
  try {
    const res = await pipelineApi.metrics()
    live.value = res.data.live || []
    history.value = res.data.history || []
    summary.value = res.data.summary || summary.value
  } catch (_) { /* ignore */ }
}

async function stopOne(row) {
  try {
    await pipelineApi.stopRun(row.runKey)
    ElMessage.success('已停止')
    await load()
  } catch (e) {
    ElMessage.error(e?.response?.data?.message || '停止失败')
  }
}

onMounted(() => {
  load()
  timer = setInterval(load, 2000)
})
onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})
</script>

<style scoped>
.metrics-page {
  padding: 4px 4px 16px;
  font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
}
.metrics-hd {
  display: flex; justify-content: space-between; align-items: flex-start;
  gap: 12px; margin-bottom: 14px; flex-wrap: wrap;
}
.metrics-title {
  margin: 0; font-size: 20px; font-weight: 750; color: #303133;
}
.metrics-title .count { font-size: 14px; font-weight: 500; color: #909399; margin-left: 6px; }
.metrics-desc { margin: 4px 0 0; color: #909399; font-size: 13px; }
.metrics-acts { display: flex; gap: 8px; }
.mb { margin-bottom: 14px; }
.stat-card { text-align: center; }
.stat-label { color: #888; font-size: 13px; }
.stat-value { font-size: 28px; font-weight: 700; margin-top: 6px; }

.task-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}
.task-card {
  background: #fff;
  border: 1px solid #e4eaf3;
  border-radius: 14px;
  padding: 14px;
  box-shadow: 0 4px 14px rgba(48, 79, 140, 0.06);
}
.task-hd {
  display: flex; justify-content: space-between; align-items: center; gap: 8px;
  margin-bottom: 8px;
}
.running {
  display: inline-flex; align-items: center; gap: 6px;
  color: #67c23a; font-size: 12px; font-weight: 600;
}
.running .dot {
  width: 8px; height: 8px; border-radius: 50%; background: #67c23a;
  box-shadow: 0 0 0 3px rgba(103, 194, 58, 0.2);
}
.cv-tag { margin-bottom: 10px; }
.task-metrics {
  display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px;
  margin-bottom: 10px;
}
.m-label { font-size: 12px; color: #909399; }
.m-alert { font-size: 22px; font-weight: 750; color: #f56c6c; }
.m-val { font-size: 18px; font-weight: 700; color: #303133; }
.task-desc {
  margin: 0 0 12px; padding-left: 16px; color: #606266; font-size: 12px; line-height: 1.6;
}
.task-acts { display: flex; gap: 8px; }

@media (max-width: 1200px) {
  .task-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 640px) {
  .task-grid { grid-template-columns: 1fr; }
}
</style>
