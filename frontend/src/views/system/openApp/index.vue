<template>
  <div>
    <el-card shadow="never" class="search-card">
      <el-form :inline="true" :model="query">
        <el-form-item label="应用名">
          <el-input v-model="query.name" clearable placeholder="名称" @keyup.enter="load" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :icon="Search" @click="load">搜索</el-button>
          <el-button :icon="Refresh" @click="reset">重置</el-button>
        </el-form-item>
      </el-form>
      <div v-if="catalogStats" class="stats-line">
        全量目录：{{ catalogStats.endpointCount }} 接口 ·
        可桥接 {{ catalogStats.bridgeableCount }} ·
        {{ catalogStats.domainCount }} 个业务域 ·
        对外路径前缀 <code>/openapi/v1/x/…</code>
      </div>
    </el-card>

    <el-card shadow="never">
      <div class="toolbar">
        <el-button v-permission="'system:openapp:add'" type="primary" :icon="Plus" @click="openAdd">新建应用</el-button>
        <el-button @click="showCatalog = true">API 分域目录</el-button>
        <el-link type="primary" href="/openapi/v1/docs" target="_blank" style="margin-left: 12px">OpenAPI 文档</el-link>
      </div>

      <el-table :data="rows" v-loading="loading" border stripe>
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="appId" label="App ID" min-width="140" />
        <el-table-column prop="name" label="名称" min-width="120" />
        <el-table-column label="Scopes" min-width="220">
          <template #default="{ row }">
            <el-tag v-for="s in (row.scopes || []).slice(0, 4)" :key="s" size="small" class="tag">{{ s }}</el-tag>
            <span v-if="(row.scopes || []).length > 4">+{{ row.scopes.length - 4 }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="qpsLimit" label="QPS" width="70" />
        <el-table-column prop="keyCount" label="Keys" width="70" />
        <el-table-column label="Webhook" width="90">
          <template #default="{ row }">
            <el-tag :type="row.webhookUrl ? 'success' : 'info'" size="small">{{ row.webhookUrl ? '已配' : '未配' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="row.status === '0' ? 'success' : 'info'">{{ row.status === '0' ? '启用' : '停用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="280" fixed="right">
          <template #default="{ row }">
            <el-button v-permission="'system:openapp:query'" link type="primary" @click="openDetail(row)">详情/用量</el-button>
            <el-button v-permission="'system:openapp:edit'" link type="primary" :icon="Edit" @click="openEdit(row)">编辑</el-button>
            <el-button v-permission="'system:openapp:remove'" link type="danger" :icon="Delete" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        class="pager"
        layout="total, prev, pager, next, sizes"
        :total="total"
        v-model:current-page="query.pageNum"
        v-model:page-size="query.pageSize"
        :page-sizes="[10, 20, 50]"
        @current-change="load"
        @size-change="load"
      />
    </el-card>

    <!-- 新建 / 编辑 -->
    <el-dialog v-model="dialog" :title="form.id ? '编辑开放应用' : '新建开放应用'" width="820px" @closed="resetForm">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="110px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item v-if="!form.id" label="App ID">
          <el-input v-model="form.appId" placeholder="可空，自动生成" />
        </el-form-item>

        <el-form-item label="能力授权">
          <div class="scope-toolbar">
            <el-button size="small" @click="selectAllDomains">全选域</el-button>
            <el-button size="small" @click="clearScopes">清空</el-button>
            <el-button size="small" type="danger" plain @click="grantSuper">授权 *:*:*</el-button>
            <span class="hint">已选 {{ form.scopes.length }} 项 · 勾选「域」即开放该域全部可桥接接口</span>
          </div>
          <el-collapse v-model="activeDomains" class="domain-collapse">
            <el-collapse-item v-for="d in domains" :key="d.id" :name="d.id">
              <template #title>
                <div class="domain-title" @click.stop>
                  <el-checkbox
                    :model-value="form.scopes.includes(d.domainScope)"
                    :disabled="d.id === 'open_app'"
                    @change="(v) => toggleDomain(d, v)"
                  >
                    {{ d.label }}
                  </el-checkbox>
                  <el-tag size="small" :type="riskType(d.risk)" class="ml">{{ d.risk }}</el-tag>
                  <span class="meta">可桥接 {{ d.bridgeableCount }}/{{ d.endpointCount }} · {{ d.domainScope }}</span>
                </div>
              </template>
              <el-checkbox-group v-model="form.scopes" class="scope-group">
                <el-checkbox
                  v-for="s in fineScopes(d)"
                  :key="s"
                  :label="s"
                  :disabled="d.id === 'open_app'"
                >{{ s }}</el-checkbox>
              </el-checkbox-group>
              <el-table :data="(d.endpoints || []).filter(e => e.bridgeable)" size="small" max-height="220" border>
                <el-table-column prop="method" label="方法" width="70" />
                <el-table-column prop="path" label="控制台路径" min-width="180" />
                <el-table-column prop="openPath" label="Open 路径" min-width="200" />
                <el-table-column prop="scope" label="Scope" width="140" />
                <el-table-column prop="summary" label="说明" min-width="100" />
              </el-table>
            </el-collapse-item>
          </el-collapse>
        </el-form-item>

        <el-form-item label="QPS 限额">
          <el-input-number v-model="form.qpsLimit" :min="0" />
        </el-form-item>
        <el-form-item label="日调用上限">
          <el-input-number v-model="form.dailyLimit" :min="0" :step="1000" />
        </el-form-item>
        <el-form-item label="Webhook URL">
          <el-input v-model="form.webhookUrl" placeholder="https://..." />
        </el-form-item>
        <el-form-item label="Webhook Secret">
          <el-input v-model="form.webhookSecret" placeholder="留空则不改；空串清除" show-password />
        </el-form-item>
        <el-form-item label="Webhook 事件">
          <el-select v-model="form.webhookEvents" multiple style="width: 100%">
            <el-option v-for="e in webhookEvents" :key="e" :label="e" :value="e" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-switch v-model="form.status" active-value="0" inactive-value="1" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">确定</el-button>
      </template>
    </el-dialog>

    <!-- 全量目录浏览 -->
    <el-drawer v-model="showCatalog" size="70%" title="开放 API 分域目录" destroy-on-close>
      <el-input v-model="catalogFilter" clearable placeholder="过滤 path / scope / 说明" class="mb" />
      <el-collapse>
        <el-collapse-item v-for="d in filteredDomains" :key="d.id" :title="`${d.label}（${d.bridgeableCount} 可桥接）`">
          <el-table :data="filterEps(d)" size="small" border>
            <el-table-column prop="method" label="方法" width="70" />
            <el-table-column prop="path" label="控制台" min-width="180" />
            <el-table-column prop="openPath" label="Open" min-width="200" />
            <el-table-column prop="scope" label="Scope" width="140" />
            <el-table-column label="桥接" width="70">
              <template #default="{ row }">
                <el-tag :type="row.bridgeable ? 'success' : 'info'" size="small">{{ row.bridgeable ? '是' : '否' }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="summary" label="说明" min-width="120" />
          </el-table>
        </el-collapse-item>
      </el-collapse>
    </el-drawer>

    <!-- 详情：密钥 / 用量 / 日志 -->
    <el-drawer v-model="drawer" size="56%" :title="detail ? `应用 ${detail.name}` : '详情'" destroy-on-close>
      <template v-if="detail">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="App ID">{{ detail.appId }}</el-descriptions-item>
          <el-descriptions-item label="Keys">{{ (detail.keys || []).length }}</el-descriptions-item>
          <el-descriptions-item label="Webhook">{{ detail.webhookUrl || '—' }}</el-descriptions-item>
          <el-descriptions-item label="文档">
            <el-link type="primary" href="/openapi/v1/docs" target="_blank">/openapi/v1/docs</el-link>
          </el-descriptions-item>
          <el-descriptions-item label="桥接示例" :span="2">
            <code>POST /openapi/v1/x/ai/face/recognize</code>
          </el-descriptions-item>
        </el-descriptions>

        <div class="section-head">
          <h4>API Keys</h4>
          <el-button v-permission="'system:openapp:add'" size="small" type="primary" @click="issueKey">签发密钥</el-button>
          <el-button v-permission="'system:openapp:edit'" size="small" @click="pingWebhook" :disabled="!detail.webhookUrl">测试 Webhook</el-button>
        </div>
        <el-alert v-if="newKeyPlain" type="warning" show-icon :closable="false" class="mb"
          :title="`请立即保存明文 Key：${newKeyPlain}`" />
        <el-table :data="detail.keys || []" size="small" border>
          <el-table-column prop="id" label="ID" width="60" />
          <el-table-column prop="name" label="名称" />
          <el-table-column prop="keyPrefix" label="前缀" />
          <el-table-column label="状态" width="80">
            <template #default="{ row }">
              <el-tag :type="row.status === '0' ? 'success' : 'info'" size="small">{{ row.status === '0' ? '启用' : '停用' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="lastUsedAt" label="最近使用" min-width="140" />
          <el-table-column label="操作" width="140">
            <template #default="{ row }">
              <el-button link type="primary" @click="toggleKey(row)">{{ row.status === '0' ? '停用' : '启用' }}</el-button>
              <el-button link type="danger" @click="dropKey(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>

        <div class="section-head"><h4>近 {{ usageDays }} 日用量</h4></div>
        <el-row :gutter="12" class="mb">
          <el-col :span="8"><el-statistic title="总调用" :value="usage.total || 0" /></el-col>
          <el-col :span="8"><el-statistic title="业务错误" :value="usage.errorCount || 0" /></el-col>
          <el-col :span="8"><el-statistic title="能力种类" :value="(usage.byCapability || []).length" /></el-col>
        </el-row>
        <el-row :gutter="12">
          <el-col :span="14"><div ref="dailyRef" class="chart" /></el-col>
          <el-col :span="10"><div ref="capRef" class="chart" /></el-col>
        </el-row>

        <div class="section-head"><h4>最近调用</h4></div>
        <el-table :data="logs" size="small" border max-height="280">
          <el-table-column prop="createTime" label="时间" width="160" />
          <el-table-column prop="capability" label="能力" width="120" />
          <el-table-column prop="path" label="路径" min-width="160" />
          <el-table-column prop="bizCode" label="code" width="70" />
          <el-table-column prop="latencyMs" label="ms" width="70" />
        </el-table>
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, nextTick, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Refresh, Plus, Edit, Delete } from '@element-plus/icons-vue'
import * as echarts from 'echarts'
import { openAppApi } from '../../../api/system'

const loading = ref(false)
const saving = ref(false)
const rows = ref([])
const total = ref(0)
const query = reactive({ pageNum: 1, pageSize: 10, name: '' })
const domains = ref([])
const catalogStats = ref(null)
const webhookEvents = ref(['job.succeeded', 'job.failed', 'api.call', '*'])
const activeDomains = ref([])
const showCatalog = ref(false)
const catalogFilter = ref('')

const dialog = ref(false)
const formRef = ref()
const emptyForm = () => ({
  id: null, name: '', appId: '', scopes: [], qpsLimit: 10, dailyLimit: 10000,
  webhookUrl: '', webhookSecret: '', webhookEvents: ['job.succeeded', 'job.failed'],
  status: '0', remark: ''
})
const form = reactive(emptyForm())
const rules = { name: [{ required: true, message: '请输入名称', trigger: 'blur' }] }

const drawer = ref(false)
const detail = ref(null)
const newKeyPlain = ref('')
const logs = ref([])
const usage = reactive({ total: 0, errorCount: 0, daily: [], byCapability: [] })
const usageDays = 7
const dailyRef = ref()
const capRef = ref()
let dailyChart
let capChart

const filteredDomains = computed(() => domains.value)

const riskType = (r) => ({ low: 'success', medium: 'warning', high: 'danger', critical: 'danger' }[r] || 'info')

const fineScopes = (d) => {
  // 域内细粒度，排除 domain:xxx 本身（已在标题勾选）
  return (d.scopes || []).filter((s) => s !== d.domainScope)
}

const filterEps = (d) => {
  const q = (catalogFilter.value || '').trim().toLowerCase()
  let list = d.endpoints || []
  if (!q) return list
  return list.filter((e) =>
    [e.path, e.openPath, e.scope, e.summary, e.method].join(' ').toLowerCase().includes(q)
  )
}

const load = async () => {
  loading.value = true
  try {
    const res = await openAppApi.list(query)
    rows.value = res.data.rows
    total.value = res.data.total
  } finally {
    loading.value = false
  }
}

const reset = () => {
  query.name = ''
  query.pageNum = 1
  load()
}

const loadMeta = async () => {
  const res = await openAppApi.scopes()
  domains.value = res.data.domains || []
  catalogStats.value = res.data.stats || null
  if (res.data.webhookEvents?.length) webhookEvents.value = res.data.webhookEvents
  activeDomains.value = domains.value.slice(0, 3).map((d) => d.id)
}

const resetForm = () => Object.assign(form, emptyForm())

const openAdd = () => {
  resetForm()
  // 默认勾选常用 AI 域
  form.scopes = domains.value
    .filter((d) => ['face', 'ai_model', 'water', 'vehicle', 'table', 'health', 'auth'].includes(d.id))
    .map((d) => d.domainScope)
  dialog.value = true
}

const openEdit = async (row) => {
  resetForm()
  const res = await openAppApi.get(row.id)
  const d = res.data
  Object.assign(form, {
    id: d.id,
    name: d.name,
    scopes: [...(d.scopes || [])],
    qpsLimit: d.qpsLimit,
    dailyLimit: d.dailyLimit,
    webhookUrl: d.webhookUrl || '',
    webhookSecret: '',
    webhookEvents: d.webhookEvents || [],
    status: d.status,
    remark: d.remark || ''
  })
  dialog.value = true
}

const toggleDomain = (d, checked) => {
  const set = new Set(form.scopes)
  if (checked) set.add(d.domainScope)
  else set.delete(d.domainScope)
  form.scopes = [...set]
}

const selectAllDomains = () => {
  const set = new Set(form.scopes)
  domains.value.forEach((d) => {
    if (d.id !== 'open_app') set.add(d.domainScope)
  })
  form.scopes = [...set]
}

const clearScopes = () => { form.scopes = [] }
const grantSuper = () => {
  form.scopes = ['*:*:*']
}

const submit = async () => {
  await formRef.value.validate()
  saving.value = true
  try {
    const payload = { ...form }
    if (!payload.webhookSecret) delete payload.webhookSecret
    if (form.id) {
      await openAppApi.update(payload)
      ElMessage.success('已更新')
    } else {
      const res = await openAppApi.add(payload)
      if (res.data?.apiKey) {
        ElMessage.success(`创建成功，请保存 Key：${res.data.apiKey}`)
      } else {
        ElMessage.success('创建成功')
      }
    }
    dialog.value = false
    load()
  } finally {
    saving.value = false
  }
}

const remove = async (row) => {
  await ElMessageBox.confirm(`确定删除应用「${row.name}」？`, '提示', { type: 'warning' })
  await openAppApi.remove(row.id)
  ElMessage.success('已删除')
  load()
}

const renderCharts = () => {
  if (!dailyRef.value || !capRef.value) return
  if (!dailyChart) dailyChart = echarts.init(dailyRef.value)
  if (!capChart) capChart = echarts.init(capRef.value)
  dailyChart.setOption({
    title: { text: '每日调用量', left: 0, textStyle: { fontSize: 13 } },
    tooltip: { trigger: 'axis' },
    grid: { left: 40, right: 16, top: 40, bottom: 28 },
    xAxis: { type: 'category', data: (usage.daily || []).map((d) => d.day) },
    yAxis: { type: 'value', minInterval: 1 },
    series: [{ type: 'bar', data: (usage.daily || []).map((d) => d.count), itemStyle: { color: '#409eff' } }]
  })
  capChart.setOption({
    title: { text: '按能力', left: 0, textStyle: { fontSize: 13 } },
    tooltip: { trigger: 'item' },
    series: [{
      type: 'pie',
      radius: ['35%', '65%'],
      data: (usage.byCapability || []).map((c) => ({ name: c.capability, value: c.count }))
    }]
  })
}

const openDetail = async (row) => {
  newKeyPlain.value = ''
  const [d, u, l] = await Promise.all([
    openAppApi.get(row.id),
    openAppApi.usage(row.id, { days: usageDays }),
    openAppApi.logs(row.id, { pageNum: 1, pageSize: 30 })
  ])
  detail.value = d.data
  Object.assign(usage, u.data)
  logs.value = l.data.rows || []
  drawer.value = true
  await nextTick()
  renderCharts()
}

watch(drawer, (v) => {
  if (!v) {
    dailyChart?.dispose()
    capChart?.dispose()
    dailyChart = null
    capChart = null
  }
})

const issueKey = async () => {
  const res = await openAppApi.createKey(detail.value.id, { name: 'key-' + Date.now() })
  newKeyPlain.value = res.data.apiKey
  const d = await openAppApi.get(detail.value.id)
  detail.value = d.data
  ElMessage.success('已签发，请保存明文')
}

const toggleKey = async (row) => {
  await openAppApi.updateKey(detail.value.id, row.id, { status: row.status === '0' ? '1' : '0' })
  const d = await openAppApi.get(detail.value.id)
  detail.value = d.data
}

const dropKey = async (row) => {
  await ElMessageBox.confirm('删除后不可恢复', '提示', { type: 'warning' })
  await openAppApi.removeKey(detail.value.id, row.id)
  const d = await openAppApi.get(detail.value.id)
  detail.value = d.data
}

const pingWebhook = async () => {
  const res = await openAppApi.testWebhook(detail.value.id)
  if (res.code === 0) ElMessage.success(res.message || '已投递')
  else ElMessage.error(res.message || '投递失败')
}

onMounted(() => {
  load()
  loadMeta()
})
</script>

<style scoped>
.search-card { margin-bottom: 12px; }
.stats-line { margin-top: 8px; color: #606266; font-size: 13px; }
.stats-line code { background: #f5f7fa; padding: 1px 6px; border-radius: 3px; }
.toolbar { margin-bottom: 12px; display: flex; align-items: center; }
.pager { margin-top: 14px; justify-content: flex-end; }
.tag { margin-right: 4px; margin-bottom: 2px; }
.section-head { display: flex; align-items: center; gap: 8px; margin: 18px 0 10px; }
.section-head h4 { margin: 0; flex: 1; }
.chart { height: 260px; width: 100%; }
.mb { margin-bottom: 12px; }
.ml { margin-left: 8px; }
.scope-toolbar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 8px; width: 100%; }
.scope-toolbar .hint { color: #909399; font-size: 12px; }
.domain-collapse { width: 100%; max-height: 420px; overflow: auto; border: 1px solid #ebeef5; border-radius: 4px; padding: 0 8px; }
.domain-title { display: flex; align-items: center; gap: 4px; width: 100%; }
.domain-title .meta { margin-left: 8px; color: #909399; font-size: 12px; }
.scope-group { display: flex; flex-wrap: wrap; gap: 4px 12px; margin-bottom: 8px; }
</style>
