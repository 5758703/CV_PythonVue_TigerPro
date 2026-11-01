<template>
  <el-dialog v-model="visible" title="组织类型删除检查与处理指引" width="min(1050px, 96vw)" append-to-body @open="load">
    <div v-loading="loading" v-if="plan">
      <h3>{{ plan.type.name }}（{{ plan.type.code }}）</h3>
      <el-alert :title="plan.archived ? '已归档，历史定义只读保留' : plan.canDelete ? '当前引用已处理，可归档删除' : '请按以下顺序处理当前引用，再重新检查'" :type="plan.canDelete || plan.archived ? 'success' : 'warning'" :closable="false" />
      <p>{{ plan.preservation }}</p>
      <p>保留记录：组织 {{ plan.retained.organizations }} 个，角色 {{ plan.retained.roles }} 个，任职 {{ plan.retained.memberships }} 条，授权 {{ plan.retained.grants }} 条。</p>
      <el-collapse v-model="expanded">
        <el-collapse-item v-for="(group, index) in plan.blockers" :key="group.key" :name="group.key" :title="`${index + 1}. ${group.title}：${group.count} 项`">
          <p>{{ group.instruction }}</p>
          <el-button v-if="group.count" size="small" @click="navigate(group.route)">前往管理页面</el-button>
          <el-alert v-if="group.truncated" title="当前展示前 200 项。处理后重新检查可继续查看剩余项，总数包含全部引用。" type="info" :closable="false" />
          <el-table v-if="group.count" :data="group.items" border max-height="260" style="margin-top: 12px">
            <el-table-column prop="id" label="记录 ID" width="90" />
            <el-table-column prop="name" label="账号 / 组织 / 角色" />
            <el-table-column prop="reason" label="关联说明" />
            <el-table-column prop="userId" label="用户 ID" width="90" />
            <el-table-column v-if="['memberships', 'grants'].includes(group.key)" label="处理" width="115"><template #default="{ row }"><el-button link type="primary" @click="openAccess(row)">处理任职</el-button></template></el-table-column>
          </el-table>
        </el-collapse-item>
      </el-collapse>
    </div>
    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
      <el-button :loading="loading" @click="load">重新检查</el-button>
      <el-button type="danger" :disabled="!plan?.canDelete || loading" :loading="saving" @click="confirmDelete">归档删除并保留历史</el-button>
    </template>
    <OrganizationAccess v-model="accessVisible" :user-id="accessUser?.userId" :username="`用户 ID ${accessUser?.userId}`" @changed="load" />
  </el-dialog>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { orgTypeApi } from '../../../api/system'
import OrganizationAccess from '../user/OrganizationAccess.vue'
const visible = defineModel({ type: Boolean, default: false })
const props = defineProps({ code: String })
const emit = defineEmits(['changed', 'navigate'])
const router = useRouter()
const plan = ref(null), loading = ref(false), saving = ref(false)
const accessVisible = ref(false), accessUser = ref(null)
const expanded = ref(['accounts', 'memberships', 'grants', 'roles', 'organizations'])
const openAccess = row => { accessUser.value = row; accessVisible.value = true }
const load = async () => {
  if (!props.code) return
  loading.value = true
  plan.value = null
  try { plan.value = (await orgTypeApi.deletionPlan(props.code)).data }
  finally { loading.value = false }
}
const navigate = path => { visible.value = false; emit('navigate'); router.push(path) }
const confirmDelete = async () => {
  await ElMessageBox.confirm(`确认归档删除「${plan.value.type.name}」？历史记录保留，编码不可复用，也不能重新启用。`, '归档删除', { type: 'warning' })
  saving.value = true
  try {
    const result = await orgTypeApi.remove(props.code)
    ElMessage.success(result.message); await load(); emit('changed')
  } catch (error) {
    if (error.response?.data?.data?.blockers) plan.value = error.response.data.data
    else await load()
  } finally { saving.value = false }
}
</script>
