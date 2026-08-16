<template>
  <div>
    <el-card shadow="never" class="search-card">
      <el-form :inline="true" :model="query">
        <el-form-item label="岗位名称">
          <el-input v-model="query.postName" placeholder="岗位名称" clearable @keyup.enter="load" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :icon="Search" @click="load">搜索</el-button>
          <el-button :icon="Refresh" @click="reset">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never">
      <div class="toolbar">
        <el-button v-permission="'system:job:add'" type="primary" :icon="Plus" @click="openAdd">新增岗位</el-button>
      </div>

      <el-table :data="rows" v-loading="loading" border stripe>
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="postCode" label="岗位编码" />
        <el-table-column prop="postName" label="岗位名称" />
        <el-table-column prop="postSort" label="排序" width="90" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.status === '0' ? 'success' : 'info'">{{ row.status === '0' ? '正常' : '停用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button v-permission="'system:job:edit'" link type="primary" :icon="Edit" @click="openEdit(row)">修改</el-button>
            <el-button v-permission="'system:job:remove'" link type="danger" :icon="Delete" @click="remove(row)">删除</el-button>
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

    <el-dialog v-model="dialog" :title="form.id ? '修改岗位' : '新增岗位'" width="460px" @closed="resetForm">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
        <el-form-item label="岗位编码" prop="postCode">
          <el-input v-model="form.postCode" />
        </el-form-item>
        <el-form-item label="岗位名称" prop="postName">
          <el-input v-model="form.postName" />
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="form.postSort" :min="0" />
        </el-form-item>
        <el-form-item label="状态">
          <el-switch v-model="form.status" active-value="0" inactive-value="1" />
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
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Refresh, Plus, Edit, Delete } from '@element-plus/icons-vue'

import { jobApi } from '../../../api/system'

const loading = ref(false)
const saving = ref(false)
const rows = ref([])
const total = ref(0)
const query = reactive({ pageNum: 1, pageSize: 10, postName: '' })

const dialog = ref(false)
const formRef = ref()
const emptyForm = () => ({ id: null, postCode: '', postName: '', postSort: 0, status: '0' })
const form = reactive(emptyForm())

const rules = {
  postCode: [{ required: true, message: '请输入岗位编码', trigger: 'blur' }],
  postName: [{ required: true, message: '请输入岗位名称', trigger: 'blur' }]
}

const load = async () => {
  loading.value = true
  try {
    const res = await jobApi.list(query)
    rows.value = res.data.rows
    total.value = res.data.total
  } finally {
    loading.value = false
  }
}

const reset = () => {
  query.postName = ''
  query.pageNum = 1
  load()
}

const resetForm = () => Object.assign(form, emptyForm())

const openAdd = () => {
  resetForm()
  dialog.value = true
}

const openEdit = (row) => {
  resetForm()
  Object.assign(form, { ...row })
  dialog.value = true
}

const submit = async () => {
  await formRef.value.validate()
  saving.value = true
  try {
    if (form.id) await jobApi.update(form)
    else await jobApi.add(form)
    ElMessage.success('保存成功')
    dialog.value = false
    load()
  } finally {
    saving.value = false
  }
}

const remove = async (row) => {
  await ElMessageBox.confirm(`确定删除岗位「${row.postName}」？`, '提示', { type: 'warning' })
  await jobApi.remove(row.id)
  ElMessage.success('删除成功')
  load()
}

onMounted(load)
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
</style>
