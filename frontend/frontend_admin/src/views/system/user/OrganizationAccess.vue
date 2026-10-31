<template>
  <el-drawer v-model="visible" :title="`${username} · 组织任职与授权`" size="min(1100px, 95vw)" @open="load">
    <el-alert title="同一账号可同时登记行政与党组织任职。组织关系本身不会自动授予角色；结束任职仅撤销该来源的权限。" type="info" :closable="false" />
    <el-tabs v-loading="loading" class="access-tabs">
      <el-tab-pane label="组织与任职">
        <el-table :data="overview.memberships" border>
          <el-table-column prop="orgName" label="组织" />
          <el-table-column label="类型" width="90"><template #default="{ row }">{{ typeText(row.orgType) }}</template></el-table-column>
          <el-table-column prop="memberKind" label="任职" />
          <el-table-column label="有效期" min-width="160"><template #default="{ row }">{{ period(row) }}</template></el-table-column>
          <el-table-column label="状态" width="90"><template #default="{ row }"><el-tag :type="row.effective ? 'success' : 'info'">{{ row.effective ? '生效' : '未生效' }}</el-tag></template></el-table-column>
          <el-table-column width="90"><template #default="{ row }"><el-button v-if="row.status === '0'" link type="danger" @click="endMembership(row)">结束任职</el-button></template></el-table-column>
        </el-table>
        <h3>登记新任职</h3>
        <el-form label-width="110px" :disabled="saving">
          <el-form-item label="组织类型"><el-radio-group v-model="member.orgType" @change="member.orgId = null"><el-radio-button value="ADMIN">行政组织</el-radio-button><el-radio-button value="PARTY">党组织</el-radio-button></el-radio-group></el-form-item>
          <el-form-item label="任职组织"><el-tree-select v-model="member.orgId" :data="memberTree" :props="orgProps" node-key="id" check-strictly filterable style="width: 100%" /></el-form-item>
          <el-form-item label="任职 / 成员身份"><el-input v-model="member.memberKind" placeholder="如：员工、党员、组织委员；不会按名称自动授权" maxlength="64" /></el-form-item>
          <el-form-item v-if="member.orgType === 'ADMIN'" label="主行政部门"><el-switch v-model="member.isPrimary" /><span class="hint">每人仅一个有效主行政任职</span></el-form-item>
          <el-form-item label="有效期（本地）"><el-date-picker v-model="member.validFrom" type="datetime" placeholder="开始：默认现在" /><span class="separator">至</span><el-date-picker v-model="member.validTo" type="datetime" placeholder="结束：可留空" /></el-form-item>
          <el-form-item><el-button type="primary" :loading="saving" @click="addMembership">登记任职</el-button></el-form-item>
        </el-form>
      </el-tab-pane>
      <el-tab-pane label="角色授权与解释">
        <el-alert title="查看、修改范围不同，请拆成两个角色分别授权。角色默认数据范围仅用于旧表单；以下每条授权的数据范围独立生效。" type="warning" :closable="false" />
        <el-table :data="overview.grants" border class="access-tabs">
          <el-table-column type="expand"><template #default="{ row }"><div class="grant-details"><p>{{ row.reason }}</p><p>权限点：{{ row.permissions.join('、') || '无' }}</p><p>实际组织 ID：{{ row.resolvedOrgIds.join('、') || '无' }}</p><p>来源：{{ row.sourceType }} / {{ row.sourceRef }}；批准依据：{{ row.approvalRef || '—' }}</p></div></template></el-table-column>
          <el-table-column prop="roleName" label="角色" />
          <el-table-column label="工作身份"><template #default="{ row }">{{ orgName(row.contextOrgId) }}</template></el-table-column>
          <el-table-column label="范围"><template #default="{ row }">{{ scopeLabel(row.scopeType) }}<div class="hint">{{ orgName(row.scopeAnchorOrgId) }}</div></template></el-table-column>
          <el-table-column label="有效期" min-width="140"><template #default="{ row }">{{ period(row) }}</template></el-table-column>
          <el-table-column label="状态" width="85"><template #default="{ row }"><el-tag :type="row.effective ? 'success' : 'info'">{{ row.effective ? '生效' : '未生效' }}</el-tag></template></el-table-column>
          <el-table-column width="65"><template #default="{ row }"><el-button v-if="row.status === '0'" link type="danger" @click="revokeGrant(row)">撤销</el-button></template></el-table-column>
        </el-table>
        <h3>为任职授予角色</h3>
        <el-form label-width="110px" :disabled="saving">
          <el-form-item label="有效任职"><el-select v-model="grant.membershipId" style="width: 100%" @change="changeMembership"><el-option v-for="m in activeMemberships" :key="m.id" :value="m.id" :label="`${typeText(m.orgType)} / ${m.orgName} / ${m.memberKind}`" /></el-select></el-form-item>
          <el-form-item label="业务角色"><el-select v-model="grant.roleId" filterable style="width: 100%"><el-option v-for="r in availableRoles" :key="r.id" :value="r.id" :label="`${r.roleName} (${r.businessDomain})`" /></el-select></el-form-item>
          <el-form-item label="数据范围"><el-select v-model="grant.scopeType" style="width: 100%"><el-option v-for="s in scopes" :key="s.value" v-bind="s" /></el-select></el-form-item>
          <el-form-item v-if="['SELF', 'ORG', 'ORG_SUBTREE'].includes(grant.scopeType)" label="范围锚点"><el-tree-select v-model="grant.scopeAnchorOrgId" :data="grantTree" :props="orgProps" node-key="id" check-strictly :disabled="grant.scopeType === 'SELF'" style="width: 100%" /></el-form-item>
          <el-form-item v-if="grant.scopeType === 'CUSTOM_ORG'" label="明确组织集合"><el-tree-select v-model="grant.scopeOrgIds" :data="grantTree" :props="orgProps" node-key="id" multiple show-checkbox check-strictly style="width: 100%" /></el-form-item>
          <el-form-item label="授权来源"><el-radio-group v-model="grant.sourceType"><el-radio value="MEMBERSHIP">任职授权</el-radio><el-radio value="MANUAL">人工批准</el-radio></el-radio-group></el-form-item>
          <el-form-item v-if="grant.sourceType === 'MANUAL'" label="批准依据"><el-input v-model="grant.approvalRef" maxlength="255" placeholder="填写审批单号或批准依据" /></el-form-item>
          <el-form-item label="有效期（本地）"><el-date-picker v-model="grant.validFrom" type="datetime" placeholder="开始：默认现在" /><span class="separator">至</span><el-date-picker v-model="grant.validTo" type="datetime" placeholder="不超过任职结束时间" /></el-form-item>
          <el-form-item><el-button type="primary" :loading="saving" @click="addGrant">确认授权</el-button></el-form-item>
        </el-form>
      </el-tab-pane>
      <el-tab-pane label="变更审计">
        <el-table :data="overview.audit" border><el-table-column prop="occurredAt" label="时间（UTC）" width="215" /><el-table-column prop="actorId" label="操作人 ID" width="100" /><el-table-column prop="eventType" label="事件" /><el-table-column type="expand"><template #default="{ row }"><pre class="audit-detail">{{ JSON.stringify(row.detail, null, 2) }}</pre></template></el-table-column></el-table>
      </el-tab-pane>
    </el-tabs>
  </el-drawer>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { organizationApi, deptApi, roleApi } from '../../../api/system'

const visible = defineModel({ type: Boolean, default: false })
const props = defineProps({ userId: Number, username: String })
const emit = defineEmits(['changed'])
const loading = ref(false), saving = ref(false)
const overview = reactive({ memberships: [], grants: [], audit: [] })
const orgTree = ref([]), roles = ref([])
const orgProps = { label: 'deptName', children: 'children', disabled: n => n.status !== '0' }
const scopes = [
  { value: 'SELF', label: '本人（当前组织）' }, { value: 'ORG', label: '指定组织' },
  { value: 'ORG_SUBTREE', label: '指定组织及下级' }, { value: 'CUSTOM_ORG', label: '明确组织集合（不含隐式下级）' },
  { value: 'DOMAIN_ALL', label: '当前组织类型全部（高权限）' }
]
const typeText = t => t === 'PARTY' ? '党组织' : '行政'
const scopeLabel = s => scopes.find(x => x.value === s)?.label || s
const localTime = s => s ? new Date(`${s}Z`).toLocaleString() : '长期'
const period = row => `${localTime(row.validFrom)} → ${localTime(row.validTo)}`
const flatOrgs = computed(() => {
  const result = []
  const walk = nodes => nodes.forEach(n => { result.push(n); walk(n.children || []) })
  walk(orgTree.value)
  return result
})
const orgName = id => id ? flatOrgs.value.find(o => o.id === id)?.deptName || String(id) : ''
const member = reactive({ orgType: 'ADMIN', orgId: null, memberKind: '', isPrimary: false, validFrom: null, validTo: null })
const grant = reactive({ membershipId: null, roleId: null, scopeType: 'ORG', scopeAnchorOrgId: null, scopeOrgIds: [], sourceType: 'MEMBERSHIP', approvalRef: '', validFrom: null, validTo: null })
const memberTree = computed(() => orgTree.value.filter(o => o.orgType === member.orgType))
const activeMemberships = computed(() => overview.memberships.filter(m => m.effective))
const selectedMember = computed(() => activeMemberships.value.find(m => m.id === grant.membershipId))
const grantTree = computed(() => orgTree.value.filter(o => o.orgType === selectedMember.value?.orgType))
const availableRoles = computed(() => roles.value.filter(r => r.roleKey !== 'admin' && r.status === '0' && ['SYSTEM', 'COMMON', selectedMember.value?.orgType].includes(r.businessDomain)))
const datePayload = form => ({ validFrom: form.validFrom?.toISOString() || null, validTo: form.validTo?.toISOString() || null })

const load = async () => {
  if (!props.userId) return
  loading.value = true
  try {
    const [o, d, r] = await Promise.all([organizationApi.overview(props.userId), deptApi.tree(), roleApi.list({ pageSize: 1000 })])
    Object.assign(overview, o.data)
    orgTree.value = d.data
    roles.value = r.data.rows
  } finally { loading.value = false }
}
const changeMembership = () => {
  grant.roleId = null
  grant.scopeAnchorOrgId = selectedMember.value?.orgId || null
  grant.scopeOrgIds = []
  grant.validFrom = null
  grant.validTo = null
}
watch(() => grant.scopeType, s => { if (s === 'SELF') grant.scopeAnchorOrgId = selectedMember.value?.orgId })
watch(() => props.userId, () => {
  Object.assign(member, { orgType: 'ADMIN', orgId: null, memberKind: '', isPrimary: false, validFrom: null, validTo: null })
  Object.assign(grant, { membershipId: null, roleId: null, scopeType: 'ORG', scopeAnchorOrgId: null, scopeOrgIds: [], sourceType: 'MEMBERSHIP', approvalRef: '', validFrom: null, validTo: null })
})
const mutate = async action => {
  saving.value = true
  try { await action(); await load(); emit('changed'); ElMessage.success('已保存，后续请求立即按新授权检查') }
  finally { saving.value = false }
}
const addMembership = async () => {
  if (!member.orgId || !member.memberKind.trim()) return ElMessage.warning('请选择组织并填写任职')
  await mutate(() => organizationApi.addMembership(props.userId, { ...member, isPrimary: member.orgType === 'ADMIN' && member.isPrimary, ...datePayload(member) }))
}
const addGrant = async () => {
  if (!grant.membershipId || !grant.roleId) return ElMessage.warning('请选择有效任职和角色')
  await mutate(() => organizationApi.addGrant(props.userId, {
    ...grant, scopeOrgIds: grant.scopeType === 'CUSTOM_ORG' ? grant.scopeOrgIds : [], ...datePayload(grant)
  }))
}
const endMembership = async row => {
  const affected = overview.grants.filter(g => g.membershipId === row.id && g.status === '0')
  await ElMessageBox.confirm(`结束「${row.orgName} / ${row.memberKind}」将撤销 ${affected.length} 条关联授权：${affected.map(g => g.roleName).join('、') || '无'}。其他组织任职及独立来源授权继续保留。`, '任职结束影响预览', { type: 'warning' })
  await mutate(() => organizationApi.endMembership(row.id))
}
const revokeGrant = async row => {
  await ElMessageBox.confirm(`撤销「${row.roleName}」的此条授权？其他有效来源仍可能提供同类权限。`, '撤销授权', { type: 'warning' })
  await mutate(() => organizationApi.revokeGrant(row.id))
}
</script>

<style scoped>
.access-tabs { margin-top: 16px; }
.hint { color: #737d8f; font-size: 12px; margin-left: 8px; }
.separator { margin: 0 12px; }
.grant-details { padding: 8px 24px; overflow-wrap: anywhere; }
.audit-detail { white-space: pre-wrap; padding: 16px; background: #f6f8fb; }
h3 { margin: 24px 0 16px; font-size: 16px; }
</style>
