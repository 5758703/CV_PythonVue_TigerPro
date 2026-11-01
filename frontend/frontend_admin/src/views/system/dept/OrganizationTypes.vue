<template>
  <el-dialog v-model="visible" title="组织类型管理" width="min(900px, 95vw)" @open="load">
    <el-alert title="停用会使相关授权失效。删除前可检查引用并查看处理指引；处理完当前引用后归档删除，历史记录保留。" type="info" :closable="false" />
    <el-checkbox v-model="includeArchived" @change="load">显示已归档类型（只读）</el-checkbox>
    <el-table :data="types" v-loading="loading" border style="margin: 16px 0">
      <el-table-column prop="code" label="编码" width="120" />
      <el-table-column prop="name" label="名称" />
      <el-table-column prop="orderNum" label="排序" width="70" />
      <el-table-column label="主组织用途" width="110"><template #default="{ row }">{{ row.supportsPrimary ? '允许' : '不允许' }}</template></el-table-column>
      <el-table-column label="状态" width="80"><template #default="{ row }">{{ row.archived ? '已归档' : row.status === '0' ? '启用' : '停用' }}</template></el-table-column>
      <el-table-column label="操作" width="190"><template #default="{ row }"><el-button v-if="!row.archived" link type="primary" @click="edit(row)">修改</el-button><el-button link :type="row.archived ? 'info' : 'danger'" @click="remove(row)">{{ row.archived ? '查看保留记录' : '删除检查与指引' }}</el-button></template></el-table-column>
    </el-table>
    <el-button @click="reset">新增类型</el-button>
    <el-form :model="form" label-width="120px" style="margin-top: 16px" :disabled="saving">
      <el-form-item label="类型编码" required><el-input v-model="form.code" :disabled="editing" maxlength="16" placeholder="大写字母开头，如 UNION；创建后不可改" /></el-form-item>
      <el-form-item label="类型名称" required><el-input v-model="form.name" maxlength="64" placeholder="例如：工会组织、项目团队" /></el-form-item>
      <el-form-item label="排序"><el-input-number v-model="form.orderNum" :min="0" :max="99999" /></el-form-item>
      <el-form-item label="可作为主组织"><el-switch v-model="form.supportsPrimary" /><span class="hint">供用户主组织选择；类型被引用后不可更改此用途</span></el-form-item>
      <el-form-item label="状态"><el-switch v-model="form.status" active-value="0" inactive-value="1" /></el-form-item>
      <el-form-item><el-button type="primary" :loading="saving" @click="save">{{ editing ? '保存修改' : '新增类型' }}</el-button></el-form-item>
    </el-form>
    <OrganizationTypeDeletion v-model="deletionVisible" :code="deletionCode" @changed="deleted" @navigate="visible = false" />
  </el-dialog>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { orgTypeApi } from '../../../api/system'
import OrganizationTypeDeletion from './OrganizationTypeDeletion.vue'
const visible = defineModel({ type: Boolean, default: false })
const emit = defineEmits(['changed'])
const types = ref([]), loading = ref(false), saving = ref(false), editing = ref(false)
const includeArchived = ref(false), deletionVisible = ref(false), deletionCode = ref(null)
const blank = () => ({ code: '', name: '', orderNum: 0, status: '0', supportsPrimary: false })
const form = reactive(blank())
const reset = () => { editing.value = false; Object.assign(form, blank()) }
const edit = row => { editing.value = true; Object.assign(form, row) }
const load = async () => {
  loading.value = true
  try { types.value = (await orgTypeApi.list({ includeArchived: includeArchived.value })).data } finally { loading.value = false }
}
const save = async () => {
  if (!/^[A-Z][A-Z0-9_]{0,15}$/.test(form.code) || !form.name.trim()) return ElMessage.warning('请填写有效编码和名称')
  const old = types.value.find(t => t.code === form.code)
  if (old?.status === '0' && form.status === '1') await ElMessageBox.confirm('停用后，此类型下全部组织的任职与授权将失效，确认停用？', '停用组织类型', { type: 'warning' })
  saving.value = true
  try {
    if (editing.value) await orgTypeApi.update(form)
    else await orgTypeApi.add(form)
    await load(); reset(); emit('changed'); ElMessage.success('已保存')
  } finally { saving.value = false }
}
const remove = row => { deletionCode.value = row.code; deletionVisible.value = true }
const deleted = async () => { await load(); reset(); emit('changed') }
</script>

<style scoped>.hint { margin-left: 12px; color: #737d8f; font-size: 12px; }</style>
