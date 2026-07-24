<template>
  <div>
    <el-card shadow="never" class="search-card">
      <div v-if="catalogStats" class="stats-line">
        全量目录：{{ catalogStats.endpointCount }} 接口 ·
        可桥接 {{ catalogStats.bridgeableCount }} ·
        {{ catalogStats.domainCount }} 个 Blueprint 域 ·
        对外 <code>/openapi/v1/x/…</code>
      </div>
    </el-card>

    <el-card shadow="never">
      <el-tabs v-model="activeTab">
        <!-- Tab1: 按域新建 -->
        <el-tab-pane name="domains" label="按 Blueprint 域分类新建">
          <div class="toolbar">
            <span class="section-label">覆盖该域全部接口</span>
            <el-button v-permission="'system:openapp:add'" type="warning" plain @click="ensureAll">
              一键对齐全部域应用
            </el-button>
            <el-button @click="showCatalog = true">查看全量接口目录</el-button>
            <el-link type="primary" href="/openapi/v1/docs" target="_blank">OpenAPI 文档</el-link>
          </div>
          <div v-for="g in groups" :key="g.id" class="group-block">
            <div class="group-head">
              <b>{{ g.label }}</b>
              <span class="meta">{{ g.bridgeableCount }} 可桥接 / {{ g.endpointCount }} 接口 · {{ g.domains.length }} 个域</span>
            </div>
            <el-row :gutter="12">
              <el-col v-for="d in g.domains" :key="d.id" :xs="24" :sm="12" :md="8" :lg="6">
                <div class="domain-card">
                  <div class="dc-title">
                    {{ d.label }}
                    <el-tag size="small" :type="riskType(d.risk)">{{ d.risk }}</el-tag>
                  </div>
                  <div class="dc-meta">
                    Blueprint: <code>{{ d.blueprint || '—' }}</code><br />
                    接口 {{ d.endpointCount }} · 可桥接 {{ d.bridgeableCount }}
                  </div>
                  <el-button
                    v-permission="'system:openapp:add'"
                    type="primary"
                    size="small"
                    class="dc-btn"
                    :loading="creatingDomain === d.id"
                    @click="createDomainApp(d)"
                  >新建/刷新本域应用</el-button>
                </div>
              </el-col>
            </el-row>
          </div>
        </el-tab-pane>

        <!-- Tab2: 开放平台应用管理 -->
        <el-tab-pane name="apps" label="开放平台">
          <el-form :inline="true" :model="query" class="mb">
            <el-form-item label="分类">
              <el-select v-model="query.category" clearable placeholder="全部分组" style="width: 140px" @change="load">
                <el-option v-for="g in groups" :key="g.id" :label="g.label" :value="g.id" />
              </el-select>
            </el-form-item>
            <el-form-item label="业务域">
              <el-select v-model="query.domainId" clearable filterable placeholder="全部域" style="width: 180px" @change="load">
                <el-option v-for="d in domains" :key="d.id" :label="d.label" :value="d.id" />
              </el-select>
            </el-form-item>
            <el-form-item label="应用名">
              <el-input v-model="query.name" clearable placeholder="名称" @keyup.enter="load" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :icon="Search" @click="load">搜索</el-button>
              <el-button :icon="Refresh" @click="reset">重置</el-button>
            </el-form-item>
          </el-form>

          <div class="toolbar">
            <span class="section-label">已创建开放应用</span>
            <el-button v-permission="'system:openapp:add'" type="primary" :icon="Plus" @click="openAddCustom">自定义新建</el-button>
          </div>
          <el-table :data="rows" v-loading="loading" border stripe>
            <el-table-column prop="category" label="分组" width="100" />
            <el-table-column prop="domainId" label="域" width="110" />
            <el-table-column prop="appId" label="App ID" min-width="140" />
            <el-table-column prop="name" label="名称" min-width="140" />
            <el-table-column label="Scopes" min-width="200">
              <template #default="{ row }">
                <el-tag v-for="s in (row.scopes || []).slice(0, 3)" :key="s" size="small" class="tag">{{ s }}</el-tag>
                <span v-if="(row.scopes || []).length > 3">+{{ row.scopes.length - 3 }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="keyCount" label="Keys" width="70" />
            <el-table-column label="状态" width="80">
              <template #default="{ row }">
                <el-tag :type="row.status === '0' ? 'success' : 'info'">{{ row.status === '0' ? '启用' : '停用' }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="260" fixed="right">
              <template #default="{ row }">
                <el-button v-permission="'system:openapp:query'" link type="primary" @click="openDetail(row)">详情</el-button>
                <el-button v-permission="'system:openapp:edit'" link type="primary" @click="openEdit(row)">编辑</el-button>
                <el-button v-permission="'system:openapp:remove'" link type="danger" @click="remove(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-pagination
            class="pager"
            layout="total, prev, pager, next, sizes"
            :total="total"
            v-model:current-page="query.pageNum"
            v-model:page-size="query.pageSize"
            :page-sizes="[20, 50, 100]"
            @current-change="load"
            @size-change="load"
          />
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <!-- 自定义新建 / 编辑 -->
    <el-dialog v-model="dialog" :title="form.id ? '编辑开放应用' : '自定义新建应用'" width="720px" @closed="resetForm">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="100px">
        <el-form-item label="名称" prop="name"><el-input v-model="form.name" /></el-form-item>
        <el-form-item v-if="!form.id" label="App ID"><el-input v-model="form.appId" placeholder="可空" /></el-form-item>
        <el-form-item label="归属域">
          <el-select v-model="form.domainId" filterable clearable style="width: 100%" @change="onDomainPick">
            <el-option v-for="d in domains" :key="d.id" :label="`${d.groupLabel} / ${d.label}`" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="能力 Scope">
          <el-select v-model="form.scopes" multiple filterable allow-create style="width: 100%">
            <el-option v-for="s in scopeOptions" :key="s" :label="s" :value="s" />
          </el-select>
        </el-form-item>
        <el-form-item label="QPS"><el-input-number v-model="form.qpsLimit" :min="0" /></el-form-item>
        <el-form-item label="日限额"><el-input-number v-model="form.dailyLimit" :min="0" :step="1000" /></el-form-item>
        <el-form-item label="Webhook"><el-input v-model="form.webhookUrl" /></el-form-item>
        <el-form-item label="状态"><el-switch v-model="form.status" active-value="0" inactive-value="1" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="form.remark" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">确定</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="showCatalog" size="72%" title="全量 API 分域目录（全部 Blueprint）">
      <el-input v-model="catalogFilter" clearable placeholder="过滤 path / scope" class="mb" />
      <el-collapse>
        <el-collapse-item v-for="d in domains" :key="d.id" :title="`${d.groupLabel} · ${d.label}（${d.endpointCount}）`">
          <el-table :data="filterEps(d)" size="small" border max-height="320">
            <el-table-column prop="method" label="方法" width="70" />
            <el-table-column prop="path" label="控制台路径" min-width="180" />
            <el-table-column prop="openPath" label="Open 路径" min-width="200" />
            <el-table-column prop="scope" label="Scope" width="140" />
            <el-table-column label="桥接" width="70">
              <template #default="{ row }">
                <el-tag :type="row.bridgeable ? 'success' : 'info'" size="small">{{ row.bridgeable ? '是' : '否' }}</el-tag>
              </template>
            </el-table-column>
          </el-table>
        </el-collapse-item>
      </el-collapse>
    </el-drawer>

    <el-drawer v-model="drawer" size="56%" :title="detail ? detail.name : '详情'" destroy-on-close>
      <template v-if="detail">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="App ID">{{ detail.appId }}</el-descriptions-item>
          <el-descriptions-item label="域">{{ detail.domainId || '—' }} / {{ detail.category || '—' }}</el-descriptions-item>
          <el-descriptions-item label="桥接示例" :span="2">
            <code>POST /openapi/v1/x/…</code>
          </el-descriptions-item>
        </el-descriptions>
        <div class="section-head">
          <h4>API Keys</h4>
          <el-button size="small" type="primary" @click="issueKey">签发密钥</el-button>
        </div>
        <el-alert v-if="newKeyPlain" type="warning" :closable="false" class="mb" :title="`请保存明文 Key：${newKeyPlain}`" />
        <el-table :data="detail.keys || []" size="small" border>
          <el-table-column prop="name" label="名称" />
          <el-table-column prop="keyPrefix" label="前缀" />
          <el-table-column prop="status" label="状态" width="80" />
          <el-table-column label="操作" width="140">
            <template #default="{ row }">
              <el-button link type="primary" @click="toggleKey(row)">启停</el-button>
              <el-button link type="danger" @click="dropKey(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <div class="section-head"><h4>用量</h4></div>
        <el-row :gutter="12" class="mb">
          <el-col :span="8"><el-statistic title="总调用" :value="usage.total || 0" /></el-col>
          <el-col :span="8"><el-statistic title="错误" :value="usage.errorCount || 0" /></el-col>
          <el-col :span="8"><el-statistic title="能力数" :value="(usage.byCapability || []).length" /></el-col>
        </el-row>
        <el-row :gutter="12">
          <el-col :span="14"><div ref="dailyRef" class="chart" /></el-col>
          <el-col :span="10"><div ref="capRef" class="chart" /></el-col>
        </el-row>
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, nextTick, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Refresh, Plus } from '@element-plus/icons-vue'
import * as echarts from 'echarts'
import { openAppApi } from '../../../api/system'

const activeTab = ref('domains')
const loading = ref(false)
const saving = ref(false)
const creatingDomain = ref('')
const rows = ref([])
const total = ref(0)
const query = reactive({ pageNum: 1, pageSize: 50, name: '', domainId: '', category: '' })
const domains = ref([])
const groups = ref([])
const catalogStats = ref(null)
const scopeOptions = ref([])
const showCatalog = ref(false)
const catalogFilter = ref('')

const dialog = ref(false)
const formRef = ref()
const emptyForm = () => ({
  id: null, name: '', appId: '', domainId: '', category: '', scopes: [],
  qpsLimit: 20, dailyLimit: 10000, webhookUrl: '', status: '0', remark: ''
})
const form = reactive(emptyForm())
const rules = { name: [{ required: true, message: '请输入名称', trigger: 'blur' }] }

const drawer = ref(false)
const detail = ref(null)
const newKeyPlain = ref('')
const usage = reactive({ total: 0, errorCount: 0, daily: [], byCapability: [] })
const dailyRef = ref()
const capRef = ref()
let dailyChart
let capChart

const riskType = (r) => ({ low: 'success', medium: 'warning', high: 'danger', critical: 'danger' }[r] || 'info')

const filterEps = (d) => {
  const q = (catalogFilter.value || '').trim().toLowerCase()
  const list = d.endpoints || []
  if (!q) return list
  return list.filter((e) => [e.path, e.openPath, e.scope, e.method].join(' ').toLowerCase().includes(q))
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
  query.domainId = ''
  query.category = ''
  query.pageNum = 1
  load()
}

const loadMeta = async () => {
  const res = await openAppApi.scopes()
  domains.value = res.data.domains || []
  groups.value = res.data.groups || []
  catalogStats.value = res.data.stats || null
  scopeOptions.value = res.data.scopes || []
}

const createDomainApp = async (d) => {
  creatingDomain.value = d.id
  try {
    const res = await openAppApi.createFromDomain({ domainId: d.id })
    if (res.data?.apiKey) {
      ElMessage.success(`已创建 ${d.label}，请保存 Key：${res.data.apiKey}`)
    } else {
      ElMessage.success(res.message || `${d.label} 应用已就绪（全量 Scope）`)
    }
    await load()
    activeTab.value = 'apps'
  } finally {
    creatingDomain.value = ''
  }
}

const ensureAll = async () => {
  await ElMessageBox.confirm(
    '将为每个 Blueprint 域创建/刷新一个开放应用，Scope 覆盖该域全部接口，并额外创建全量应用。是否继续？',
    '一键对齐',
    { type: 'warning' }
  )
  const res = await openAppApi.ensureDomains()
  ElMessage.success(`完成：新建 ${(res.data.created || []).length}，刷新 ${(res.data.updated || []).length}`)
  await load()
  activeTab.value = 'apps'
}

const resetForm = () => Object.assign(form, emptyForm())

const openAddCustom = () => {
  resetForm()
  dialog.value = true
}

const onDomainPick = (id) => {
  const d = domains.value.find((x) => x.id === id)
  if (!d) return
  form.category = d.group
  form.scopes = [...(d.fullScopes || [d.domainScope])]
  if (!form.name) form.name = d.suggestedName
  if (!form.appId) form.appId = d.suggestedAppId
}

const openEdit = async (row) => {
  resetForm()
  const res = await openAppApi.get(row.id)
  const d = res.data
  Object.assign(form, {
    id: d.id,
    name: d.name,
    domainId: d.domainId || '',
    category: d.category || '',
    scopes: [...(d.scopes || [])],
    qpsLimit: d.qpsLimit,
    dailyLimit: d.dailyLimit,
    webhookUrl: d.webhookUrl || '',
    status: d.status,
    remark: d.remark || ''
  })
  dialog.value = true
}

const submit = async () => {
  await formRef.value.validate()
  saving.value = true
  try {
    if (form.id) {
      await openAppApi.update(form)
      ElMessage.success('已更新')
    } else {
      const res = await openAppApi.add(form)
      if (res.data?.apiKey) ElMessage.success(`创建成功，Key：${res.data.apiKey}`)
      else ElMessage.success('创建成功')
    }
    dialog.value = false
    load()
  } finally {
    saving.value = false
  }
}

const remove = async (row) => {
  await ElMessageBox.confirm(`删除应用「${row.name}」？`, '提示', { type: 'warning' })
  await openAppApi.remove(row.id)
  ElMessage.success('已删除')
  load()
}

const renderCharts = () => {
  if (!dailyRef.value || !capRef.value) return
  if (!dailyChart) dailyChart = echarts.init(dailyRef.value)
  if (!capChart) capChart = echarts.init(capRef.value)
  dailyChart.setOption({
    title: { text: '每日调用', textStyle: { fontSize: 13 } },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: (usage.daily || []).map((d) => d.day) },
    yAxis: { type: 'value', minInterval: 1 },
    series: [{ type: 'bar', data: (usage.daily || []).map((d) => d.count) }]
  })
  capChart.setOption({
    title: { text: '按能力', textStyle: { fontSize: 13 } },
    tooltip: { trigger: 'item' },
    series: [{
      type: 'pie', radius: ['35%', '65%'],
      data: (usage.byCapability || []).map((c) => ({ name: c.capability, value: c.count }))
    }]
  })
}

const openDetail = async (row) => {
  newKeyPlain.value = ''
  const [d, u] = await Promise.all([
    openAppApi.get(row.id),
    openAppApi.usage(row.id, { days: 7 })
  ])
  detail.value = d.data
  Object.assign(usage, u.data)
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
  detail.value = (await openAppApi.get(detail.value.id)).data
}

const toggleKey = async (row) => {
  await openAppApi.updateKey(detail.value.id, row.id, { status: row.status === '0' ? '1' : '0' })
  detail.value = (await openAppApi.get(detail.value.id)).data
}

const dropKey = async (row) => {
  await ElMessageBox.confirm('删除密钥？', '提示', { type: 'warning' })
  await openAppApi.removeKey(detail.value.id, row.id)
  detail.value = (await openAppApi.get(detail.value.id)).data
}

onMounted(async () => {
  await loadMeta()
  await load()
})
</script>

<style scoped>
.search-card { margin-bottom: 12px; }
.stats-line { color: #606266; font-size: 13px; }
.stats-line code, .dc-meta code { background: #f5f7fa; padding: 1px 6px; border-radius: 3px; }
.mb { margin-bottom: 12px; }
.toolbar { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-bottom: 12px; }
.section-label { font-weight: 600; margin-right: 8px; }
.group-block { margin-bottom: 18px; }
.group-head { display: flex; align-items: baseline; gap: 10px; margin: 8px 0 10px; }
.group-head .meta { color: #909399; font-size: 12px; }
.domain-card {
  border: 1px solid #ebeef5; border-radius: 6px; padding: 12px; margin-bottom: 12px;
  background: #fff; min-height: 132px; display: flex; flex-direction: column;
}
.dc-title { display: flex; justify-content: space-between; align-items: center; font-weight: 600; margin-bottom: 6px; }
.dc-meta { color: #909399; font-size: 12px; line-height: 1.6; flex: 1; }
.dc-btn { margin-top: 8px; width: 100%; }
.tag { margin-right: 4px; }
.pager { margin-top: 14px; justify-content: flex-end; }
.section-head { display: flex; align-items: center; gap: 8px; margin: 16px 0 10px; }
.section-head h4 { margin: 0; flex: 1; }
.chart { height: 240px; width: 100%; }
</style>
