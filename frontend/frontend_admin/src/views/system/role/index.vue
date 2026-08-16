<template>
  <div>
    <el-card shadow="never" class="search-card">
      <el-form :inline="true" :model="query">
        <el-form-item label="角色名">
          <el-input v-model="query.roleName" placeholder="角色名" clearable @keyup.enter="load" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :icon="Search" @click="load">搜索</el-button>
          <el-button :icon="Refresh" @click="reset">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never">
      <div class="toolbar">
        <el-button v-permission="'system:role:add'" type="primary" :icon="Plus" @click="openAdd">新增角色</el-button>
      </div>

      <el-table :data="rows" v-loading="loading" border stripe>
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="roleName" label="角色名称" />
        <el-table-column prop="roleKey" label="权限字符" />
        <el-table-column label="数据范围">
          <template #default="{ row }">
            <el-tag effect="plain">{{ scopeText(row.dataScope) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.status === '0' ? 'success' : 'info'">{{ row.status === '0' ? '正常' : '停用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="remark" label="备注" />
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button v-permission="'system:role:edit'" link type="primary" :icon="Edit" @click="openEdit(row)">修改</el-button>
            <el-button v-permission="'system:role:remove'" link type="danger" :icon="Delete" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        class="pager"
        layout="total, prev, pager, next"
        :total="total"
        v-model:current-page="query.pageNum"
        v-model:page-size="query.pageSize"
        @current-change="load"
      />
    </el-card>

    <el-dialog v-model="dialog" :title="form.id ? '修改角色' : '新增角色'" width="560px" @closed="resetForm">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
        <el-form-item label="角色名称" prop="roleName">
          <el-input v-model="form.roleName" />
        </el-form-item>
        <el-form-item label="权限字符" prop="roleKey">
          <el-input v-model="form.roleKey" :disabled="!!form.id" placeholder="如 manager" />
        </el-form-item>
        <el-form-item label="角色顺序">
          <el-input-number v-model="form.roleSort" :min="0" />
        </el-form-item>
        <el-form-item label="数据范围">
          <el-select v-model="form.dataScope" style="width: 100%">
            <el-option v-for="s in scopes" :key="s.value" :label="s.label" :value="s.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="菜单权限">
          <el-tree
            ref="treeRef"
            :data="menuTree"
            show-checkbox
            node-key="id"
            :props="{ label: 'menuName', children: 'children' }"
            class="perm-tree"
          />
        </el-form-item>
        <el-form-item label="状态">
          <el-switch v-model="form.status" active-value="0" inactive-value="1" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" type="textarea" />
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
import { ref, reactive, onMounted, nextTick } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Refresh, Plus, Edit, Delete } from '@element-plus/icons-vue'

import { roleApi, menuApi } from '../../../api/system'

const scopes = [
  { value: 1, label: '仅本人' },
  { value: 2, label: '本部门' },
  { value: 3, label: '本部门及以下' },
  { value: 4, label: '全部数据' }
]
const scopeText = (v) => (scopes.find((s) => s.value === v) || {}).label || '-'

const loading = ref(false)
const saving = ref(false)
const rows = ref([])
const total = ref(0)
const menuTree = ref([])
const query = reactive({ pageNum: 1, pageSize: 10, roleName: '' })

const dialog = ref(false)
const formRef = ref()
const treeRef = ref()
const emptyForm = () => ({ id: null, roleName: '', roleKey: '', roleSort: 0, dataScope: 1, status: '0', remark: '' })
const form = reactive(emptyForm())

const rules = {
  roleName: [{ required: true, message: '请输入角色名称', trigger: 'blur' }],
  roleKey: [{ required: true, message: '请输入权限字符', trigger: 'blur' }]
}

const load = async () => {
  loading.value = true
  try {
    const res = await roleApi.list(query)
    rows.value = res.data.rows
    total.value = res.data.total
  } finally {
    loading.value = false
  }
}

const reset = () => {
  query.roleName = ''
  query.pageNum = 1
  load()
}

const resetForm = () => {
  Object.assign(form, emptyForm())
  treeRef.value && treeRef.value.setCheckedKeys([])
}

const openAdd = () => {
  resetForm()
  dialog.value = true
  nextTick(() => treeRef.value.setCheckedKeys([]))
}

const openEdit = async (row) => {
  resetForm()
  const res = await roleApi.get(row.id)
  Object.assign(form, {
    id: res.data.id,
    roleName: res.data.roleName,
    roleKey: res.data.roleKey,
    roleSort: res.data.roleSort,
    dataScope: res.data.dataScope,
    status: res.data.status,
    remark: res.data.remark
  })
  dialog.value = true
  nextTick(() => treeRef.value.setCheckedKeys(res.data.menuIds || []))
}

const submit = async () => {
  await formRef.value.validate()
  const menuIds = [...treeRef.value.getCheckedKeys(), ...treeRef.value.getHalfCheckedKeys()]
  saving.value = true
  try {
    const payload = { ...form, menuIds }
    if (form.id) await roleApi.update(payload)
    else await roleApi.add(payload)
    ElMessage.success('保存成功')
    dialog.value = false
    load()
  } finally {
    saving.value = false
  }
}

const remove = async (row) => {
  await ElMessageBox.confirm(`确定删除角色「${row.roleName}」？`, '提示', { type: 'warning' })
  await roleApi.remove(row.id)
  ElMessage.success('删除成功')
  load()
}

onMounted(async () => {
  load()
  const m = await menuApi.tree()
  menuTree.value = m.data
})
</script>

<style scoped>
.search-card {
  margin-bottom: 12px;
}
.toolbar {
  margin-bottom: 12px;
}
.pager {
  margin-top: 14px;
  justify-content: flex-end;
}
.perm-tree {
  width: 100%;
  max-height: 260px;
  overflow: auto;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 6px;
}
</style>
