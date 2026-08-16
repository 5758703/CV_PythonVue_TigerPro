<template>
  <div>
    <el-card shadow="never">
      <div class="toolbar">
        <el-button v-permission="'system:menu:add'" type="primary" :icon="Plus" @click="openAdd()">新增菜单</el-button>
        <el-button :icon="Refresh" @click="load">刷新</el-button>
      </div>

      <el-table
        :data="menuTree"
        v-loading="loading"
        row-key="id"
        :tree-props="{ children: 'children' }"
        default-expand-all
        border
      >
        <el-table-column prop="menuName" label="菜单名称" width="200" />
        <el-table-column label="类型" width="90">
          <template #default="{ row }">
            <el-tag :type="typeTag(row.menuType).color" effect="plain">{{ typeTag(row.menuType).text }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="icon" label="图标" width="90">
          <template #default="{ row }">
            <el-icon v-if="row.icon"><component :is="row.icon" /></el-icon>
          </template>
        </el-table-column>
        <el-table-column prop="perms" label="权限标识" />
        <el-table-column prop="path" label="路由路径" />
        <el-table-column prop="orderNum" label="排序" width="80" />
        <el-table-column label="操作" width="320" fixed="right">
          <template #default="{ row }">
            <div class="op-btns">
              <el-button v-permission="'system:menu:edit'" link type="primary" :icon="Top" :disabled="reordering" title="上移" @click="move(row, -1)">上移</el-button>
              <el-button v-permission="'system:menu:edit'" link type="primary" :icon="Bottom" :disabled="reordering" title="下移" @click="move(row, 1)">下移</el-button>
              <el-button v-permission="'system:menu:add'" link type="primary" :icon="Plus" @click="openAdd(row)">新增</el-button>
              <el-button v-permission="'system:menu:edit'" link type="primary" :icon="Edit" @click="openEdit(row)">修改</el-button>
              <el-button v-permission="'system:menu:remove'" link type="danger" :icon="Delete" @click="remove(row)">删除</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialog" :title="form.id ? '修改菜单' : '新增菜单'" width="560px" @closed="resetForm">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
        <el-form-item label="上级菜单">
          <el-tree-select
            v-model="form.parentId"
            :data="parentOptions"
            :props="{ label: 'menuName', children: 'children' }"
            node-key="id"
            check-strictly
            placeholder="选择上级菜单"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="菜单类型" prop="menuType">
          <el-radio-group v-model="form.menuType">
            <el-radio value="M">目录</el-radio>
            <el-radio value="C">菜单</el-radio>
            <el-radio value="F">按钮</el-radio>
            <el-radio value="A">接口</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="菜单名称" prop="menuName">
          <el-input v-model="form.menuName" />
        </el-form-item>
        <el-form-item v-if="['M', 'C'].includes(form.menuType)" label="图标">
          <el-input v-model="form.icon" placeholder="Element 图标名，如 User" />
        </el-form-item>
        <el-form-item v-if="['M', 'C'].includes(form.menuType)" label="路由路径">
          <el-input v-model="form.path" placeholder="如 /system 或 user" />
        </el-form-item>
        <el-form-item v-if="form.menuType === 'C'" label="组件路径">
          <el-input v-model="form.component" placeholder="如 system/user/index" />
        </el-form-item>
        <el-form-item v-if="['C', 'F', 'A'].includes(form.menuType)" label="权限标识">
          <el-input v-model="form.perms" placeholder="如 system:user:list" />
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="form.orderNum" :min="0" />
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
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Edit, Delete, Refresh, Top, Bottom } from '@element-plus/icons-vue'

import { menuApi } from '../../../api/system'

const TYPE_MAP = {
  M: { text: '目录', color: 'primary' },
  C: { text: '菜单', color: 'success' },
  F: { text: '按钮', color: 'warning' },
  A: { text: '接口', color: 'danger' }
}
const typeTag = (t) => TYPE_MAP[t] || { text: t, color: 'info' }

const loading = ref(false)
const saving = ref(false)
const reordering = ref(false)
const menuTree = ref([])

const dialog = ref(false)
const formRef = ref()
const emptyForm = () => ({ id: null, parentId: 0, menuType: 'C', menuName: '', icon: '', path: '', component: '', perms: '', orderNum: 0, status: '0' })
const form = reactive(emptyForm())

const rules = {
  menuName: [{ required: true, message: '请输入菜单名称', trigger: 'blur' }],
  menuType: [{ required: true, message: '请选择菜单类型', trigger: 'change' }]
}

const parentOptions = computed(() => [{ id: 0, menuName: '顶级', children: menuTree.value }])

const load = async () => {
  loading.value = true
  try {
    const res = await menuApi.tree()
    menuTree.value = res.data
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
    menuType: row.menuType,
    menuName: row.menuName,
    icon: row.icon,
    path: row.path,
    component: row.component,
    perms: row.perms,
    orderNum: row.orderNum,
    status: row.status
  })
  dialog.value = true
}

const submit = async () => {
  await formRef.value.validate()
  saving.value = true
  try {
    if (form.id) await menuApi.update(form)
    else await menuApi.add(form)
    ElMessage.success('保存成功')
    dialog.value = false
    load()
  } finally {
    saving.value = false
  }
}

const flatten = (nodes, out = []) => {
  nodes.forEach((n) => { out.push(n); if (n.children) flatten(n.children, out) })
  return out
}

// 同级菜单上移/下移：重排兄弟节点 orderNum（dir=-1 上移，1 下移）
const move = async (row, dir) => {
  if (reordering.value) return
  const sibs = flatten(menuTree.value)
    .filter((n) => n.parentId === row.parentId)
    .sort((a, b) => (a.orderNum - b.orderNum) || (a.id - b.id))
  const idx = sibs.findIndex((n) => n.id === row.id)
  const tgt = idx + dir
  if (tgt < 0 || tgt >= sibs.length) {
    ElMessage.info(dir < 0 ? '已在最前' : '已在最后')
    return
  }
  sibs.splice(tgt, 0, sibs.splice(idx, 1)[0])  // 交换位置
  reordering.value = true
  try {
    // 重排为连续序号，仅提交变化的
    const changed = []
    sibs.forEach((n, i) => {
      const no = i + 1
      if (n.orderNum !== no) { n.orderNum = no; changed.push(n) }
    })
    for (const n of changed) await menuApi.update(n)
    ElMessage.success('顺序已调整')
    await load()
  } finally {
    reordering.value = false
  }
}

const remove = async (row) => {
  await ElMessageBox.confirm(`确定删除菜单「${row.menuName}」？`, '提示', { type: 'warning' })
  await menuApi.remove(row.id)
  ElMessage.success('删除成功')
  load()
}

onMounted(load)
</script>

<style scoped>
.toolbar {
  margin-bottom: 12px;
}
.op-btns {
  display: flex;
  flex-wrap: nowrap;
  align-items: center;
  gap: 8px;
  white-space: nowrap;
}
</style>
