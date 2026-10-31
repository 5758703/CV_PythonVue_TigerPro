<template>
  <div>
    <el-card shadow="never" class="search-card">
      <el-form :inline="true" :model="query">
        <el-form-item label="用户名">
          <el-input v-model="query.username" placeholder="用户名" clearable @keyup.enter="load" />
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="query.status" placeholder="全部" clearable style="width: 120px">
            <el-option label="正常" value="0" />
            <el-option label="停用" value="1" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :icon="Search" @click="load">搜索</el-button>
          <el-button :icon="Refresh" @click="reset">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never">
      <div class="toolbar">
        <el-button v-if="store.isAdmin" v-permission="'system:user:add'" type="primary" :icon="Plus" @click="openAdd">新增用户</el-button>
        <span class="hint">行政与党组织共用一个账号；在「任职与授权」中分别配置身份和数据范围。</span>
      </div>

      <el-table :data="rows" v-loading="loading" border stripe>
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="username" label="用户名" />
        <el-table-column prop="nickname" label="昵称" />
        <el-table-column label="组织"><template #default="{ row }">{{ row.orgNames?.join('、') || row.deptName || '—' }}</template></el-table-column>
        <el-table-column prop="phone" label="手机号" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.status === '0' ? 'success' : 'info'">{{ row.status === '0' ? '正常' : '停用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="createTime" label="创建时间" width="180" />
        <el-table-column label="操作" :width="store.isAdmin ? 260 : 100" fixed="right">
          <template #default="{ row }">
            <el-button v-if="store.isAdmin || row.canEdit" v-permission="'system:user:edit'" link type="primary" :icon="Edit" @click="openEdit(row)">修改</el-button>
            <el-button v-if="store.isAdmin && !row.isPlatformAdmin" link type="primary" @click="openAccess(row)">任职与授权</el-button>
            <el-button v-if="store.isAdmin" v-permission="'system:user:remove'" link type="danger" :icon="Delete" @click="remove(row)">删除</el-button>
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

    <el-dialog v-model="dialog" :title="form.id ? '修改用户' : '新增用户'" width="600px" @closed="resetForm">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="用户名" prop="username">
              <el-input v-model="form.username" :disabled="!!form.id" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="昵称" prop="nickname">
              <el-input v-model="form.nickname" />
            </el-form-item>
          </el-col>
          <el-col v-if="!form.id" :span="12">
            <el-form-item label="密码" prop="password">
              <el-input v-model="form.password" type="password" show-password />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item v-if="store.isAdmin" label="主行政部门">
              <el-tree-select
                v-model="form.deptId"
                :data="deptTree"
                :props="{ label: 'deptName', children: 'children' }"
                node-key="id"
                check-strictly
                placeholder="选择部门"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="手机号">
              <el-input v-model="form.phone" :disabled="!store.isAdmin && !form.canEditSensitive" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="邮箱">
              <el-input v-model="form.email" :disabled="!store.isAdmin && !form.canEditSensitive" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item v-if="store.isAdmin" label="行政兼容角色">
              <el-select v-model="form.roleIds" multiple placeholder="选择角色" style="width: 100%">
                <el-option v-for="r in roles" :key="r.id" :label="r.roleName" :value="r.id" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item v-if="store.isAdmin" label="岗位">
              <el-select v-model="form.postIds" multiple placeholder="选择岗位" style="width: 100%">
                <el-option v-for="p in posts" :key="p.id" :label="p.postName" :value="p.id" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item v-if="store.isAdmin" label="状态">
              <el-switch v-model="form.status" active-value="0" inactive-value="1" />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">确定</el-button>
      </template>
    </el-dialog>
    <OrganizationAccess v-if="store.isAdmin" v-model="accessVisible" :user-id="accessUser?.id" :username="accessUser?.nickname || accessUser?.username" @changed="load" />
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Refresh, Plus, Edit, Delete } from '@element-plus/icons-vue'

import { userApi, roleApi, jobApi, deptApi } from '../../../api/system'
import { useUserStore } from '../../../store/user'
import OrganizationAccess from './OrganizationAccess.vue'

const store = useUserStore()
const accessVisible = ref(false), accessUser = ref(null)
const openAccess = row => { accessUser.value = row; accessVisible.value = true }

const loading = ref(false)
const saving = ref(false)
const rows = ref([])
const total = ref(0)
const roles = ref([])
const posts = ref([])
const deptTree = ref([])

const query = reactive({ pageNum: 1, pageSize: 10, username: '', status: '' })

const dialog = ref(false)
const formRef = ref()
const emptyForm = () => ({ id: null, username: '', nickname: '', password: '', deptId: null, phone: '', email: '', roleIds: [], postIds: [], status: '0', canEditSensitive: false })
const form = reactive(emptyForm())

const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }, { min: 6, message: '至少6位', trigger: 'blur' }]
}

const load = async () => {
  loading.value = true
  try {
    const res = await userApi.list(query)
    rows.value = res.data.rows
    total.value = res.data.total
  } finally {
    loading.value = false
  }
}

const reset = () => {
  query.username = ''
  query.status = ''
  query.pageNum = 1
  load()
}

const loadRefs = async () => {
  if (!store.isAdmin) return
  const [r, p, d] = await Promise.all([
    roleApi.list({ pageNum: 1, pageSize: 100 }),
    jobApi.list({ pageNum: 1, pageSize: 100 }),
    deptApi.tree({ orgType: 'ADMIN' })
  ])
  roles.value = r.data.rows
  posts.value = p.data.rows
  deptTree.value = d.data
}

const resetForm = () => Object.assign(form, emptyForm())

const openAdd = () => {
  resetForm()
  dialog.value = true
}

const openEdit = async (row) => {
  resetForm()
  const res = await userApi.get(row.id)
  Object.assign(form, {
    id: res.data.id,
    username: res.data.username,
    nickname: res.data.nickname,
    deptId: res.data.deptId,
    phone: res.data.phone,
    email: res.data.email,
    canEditSensitive: res.data.canEditSensitive || false,
    roleIds: res.data.roleIds || [],
    postIds: res.data.postIds || [],
    status: res.data.status
  })
  dialog.value = true
}

const submit = async () => {
  await formRef.value.validate()
  saving.value = true
  try {
    const safePayload = { id: form.id, nickname: form.nickname }
    if (form.canEditSensitive) Object.assign(safePayload, { phone: form.phone, email: form.email })
    if (form.id) await userApi.update(store.isAdmin ? form : safePayload)
    else await userApi.add(form)
    ElMessage.success('保存成功')
    dialog.value = false
    load()
  } finally {
    saving.value = false
  }
}

const remove = async (row) => {
  await ElMessageBox.confirm(`确定删除用户「${row.username}」？`, '提示', { type: 'warning' })
  await userApi.remove(row.id)
  ElMessage.success('删除成功')
  load()
}

onMounted(() => {
  load()
  loadRefs()
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
.hint { margin-left: 12px; color: #7a8495; font-size: 13px; }
</style>
