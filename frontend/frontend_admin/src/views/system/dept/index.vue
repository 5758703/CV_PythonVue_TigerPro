<template>
  <div>
    <el-card shadow="never">
      <div class="toolbar">
        <el-select v-model="orgType" placeholder="请选择组织类型" style="width: 220px" @change="load"><el-option v-for="t in types" :key="t.code" :value="t.code" :label="t.name + (t.status === '1' ? '（停用）' : '')" /></el-select>
        <el-button v-if="store.isAdmin" @click="typeDialog = true">组织类型管理</el-button>
        <el-button v-permission="'system:dept:add'" type="primary" :icon="Plus"  :disabled="!types.some(t => t.code === orgType && t.status === '0')" @click="openAdd()">新增组织</el-button>
        <el-button :icon="Refresh" @click="load">刷新</el-button>
      </div>

      <el-table
        :data="deptTree"
        v-loading="loading"
        row-key="id"
        :tree-props="{ children: 'children' }"
        default-expand-all
        border
      >
        <el-table-column prop="deptName" label="组织名称" />
        <el-table-column prop="leader" label="负责人" />
        <el-table-column prop="phone" label="联系电话" />
        <el-table-column prop="orderNum" label="排序" width="80" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.status === '0' ? 'success' : 'info'">{{ row.status === '0' ? '正常' : '停用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <el-button v-permission="'system:dept:add'" link type="primary" :icon="Plus" @click="openAdd(row)">新增</el-button>
            <el-button v-permission="'system:dept:edit'" link type="primary" :icon="Edit" @click="openEdit(row)">修改</el-button>
            <el-button v-if="store.isAdmin" v-permission="'system:dept:remove'" link type="danger" :icon="Delete" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <OrganizationTypes v-model="typeDialog" @changed="typesChanged" />
    <el-dialog v-model="dialog" :title="form.id ? '修改组织' : '新增组织'" width="520px" @closed="resetForm">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
        <el-form-item label="上级组织">
          <el-tree-select
            v-model="form.parentId"
            :data="parentOptions"
            :props="{ label: 'deptName', children: 'children' }"
            node-key="id"
            check-strictly
            :disabled="!!form.id && !store.isAdmin"
            placeholder="选择上级组织"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="组织名称" prop="deptName">
          <el-input v-model="form.deptName" />
        </el-form-item>
        <el-form-item label="负责人">
          <el-input v-model="form.leader" />
        </el-form-item>
        <el-form-item label="联系电话">
          <el-input v-model="form.phone" />
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="form.orderNum" :min="0" />
        </el-form-item>
        <el-form-item label="状态">
          <el-switch v-model="form.status" active-value="0" inactive-value="1" :disabled="!store.isAdmin" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Edit, Delete, Refresh } from '@element-plus/icons-vue'

import OrganizationTypes from './OrganizationTypes.vue'
import { deptApi, orgTypeApi } from '../../../api/system'
import { useUserStore } from '../../../store/user'
const store = useUserStore()
const orgType = ref(store.contexts.find(c => c.orgId === store.contextOrgId)?.orgType || null)

const types = ref([]), typeDialog = ref(false)
const loadTypes = async () => {
  types.value = (await orgTypeApi.list()).data
  if (!types.value.some(t => t.code === orgType.value)) orgType.value = types.value.find(t => t.status === '0')?.code || types.value[0]?.code || null
}
const typesChanged = async () => { await loadTypes(); await store.loadInfo(); await load() }
const loading = ref(false)
const saving = ref(false)
const deptTree = ref([])

const dialog = ref(false)
const formRef = ref()
const emptyForm = () => ({ id: null, parentId: 0, orgType: orgType.value, deptName: '', leader: '', phone: '', orderNum: 0, status: '0' })
const form = reactive(emptyForm())

const rules = {
  deptName: [{ required: true, message: '请输入组织名称', trigger: 'blur' }]
}

// 上级选项：顶级 + 现有树
const parentOptions = computed(() => [{ id: 0, deptName: '顶级', children: deptTree.value }])

const load = async () => {
  loading.value = true
  try {
    if (!orgType.value) { deptTree.value = []; return }
    const res = await deptApi.tree({ orgType: orgType.value })
    deptTree.value = res.data
  } finally {
    loading.value = false
  }
}

const resetForm = () => Object.assign(form, emptyForm())

const openAdd = (row) => {
  resetForm()
  form.parentId = row ? row.id : 0
  dialog.value = true
}

const openEdit = (row) => {
  resetForm()
  Object.assign(form, {
    id: row.id,
    parentId: row.parentId,
    deptName: row.deptName,
    leader: row.leader,
    phone: row.phone,
    orderNum: row.orderNum,
    status: row.status
  })
  dialog.value = true
}

const submit = async () => {
  await formRef.value.validate()
  saving.value = true
  try {
    if (form.id) await deptApi.update(form)
    else await deptApi.add(form)
    ElMessage.success('保存成功')
    dialog.value = false
    load()
  } finally {
    saving.value = false
  }
}

const remove = async (row) => {
  await ElMessageBox.confirm(`确定删除组织「${row.deptName}」？`, '提示', { type: 'warning' })
  await deptApi.remove(row.id)
  ElMessage.success('删除成功')
  load()
}

onMounted(async () => { await loadTypes(); await load() })
</script>

<style scoped>
.toolbar {
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 12px;
}
</style>
