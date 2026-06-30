<template>
  <div>
    <el-card shadow="never" class="search-card">
      <el-form :inline="true" :model="query">
        <el-form-item label="名称">
          <el-input v-model="query.name" placeholder="摄像头名称" clearable @keyup.enter="load" />
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="query.status" placeholder="全部" clearable style="width: 120px" @change="load">
            <el-option label="启用" value="0" />
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
        <el-button v-permission="'camera:add'" type="primary" :icon="Plus" @click="openAdd">新增摄像头</el-button>
        <el-button v-permission="'camera:remove'" type="danger" :icon="Delete" :disabled="!selectedIds.length" @click="batchRemove">批量删除{{ selectedIds.length ? `（${selectedIds.length}）` : '' }}</el-button>
      </div>

      <el-table :data="rows" v-loading="loading" border stripe @selection-change="onSelect">
        <el-table-column type="selection" width="48" />
        <el-table-column prop="id" label="ID" width="64" />
        <el-table-column prop="name" label="名称" min-width="140" show-overflow-tooltip />
        <el-table-column label="来源类型" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="srcTagType(row.sourceType)">{{ srcTagLabel(row.sourceType) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="source" label="来源" min-width="200" show-overflow-tooltip />
        <el-table-column prop="location" label="位置" width="120" show-overflow-tooltip />
        <el-table-column prop="resolution" label="分辨率宽" width="90" />
        <el-table-column prop="fps" label="帧率" width="70" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.status === '0' ? 'success' : 'info'">{{ row.status === '0' ? '启用' : '停用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <el-button v-permission="'camera:query'" link type="success" :icon="VideoPlay" @click="openPreview(row)">预览</el-button>
            <el-button v-permission="'camera:edit'" link type="primary" :icon="Edit" @click="openEdit(row)">修改</el-button>
            <el-button v-permission="'camera:remove'" link type="danger" :icon="Delete" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination class="pager" layout="total, prev, pager, next" :total="total"
                     v-model:current-page="query.pageNum" v-model:page-size="query.pageSize" @current-change="load" />
    </el-card>

    <!-- 新增/编辑 -->
    <el-dialog v-model="dialog" :title="form.id ? '修改摄像头' : '新增摄像头'" width="520px" @closed="resetForm">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" placeholder="如：大门入口" />
        </el-form-item>
        <el-form-item label="来源类型" prop="sourceType">
          <el-select v-model="form.sourceType" style="width: 100%" @change="onTypeChange">
            <el-option label="本地视频（ffmpeg 模拟）" value="file" />
            <el-option label="网络摄像头（RTSP）" value="rtsp" />
            <el-option label="本机摄像头（DirectShow）" value="device" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="form.sourceType === 'file'" label="视频文件" prop="source">
          <el-upload :show-file-list="false" :before-upload="beforeUpload" :http-request="doUpload" accept="video/*">
            <el-button :icon="UploadFilled" :loading="uploading">上传视频</el-button>
          </el-upload>
          <div v-if="form.source" class="file-hint">已选：{{ form.source }}</div>
        </el-form-item>
        <el-form-item v-else-if="form.sourceType === 'device'" label="本机摄像头" prop="source">
          <div class="device-row">
            <el-select v-model="form.source" placeholder="点右侧获取本机摄像头" style="flex: 1" filterable>
              <el-option v-for="d in devices" :key="d" :label="d" :value="d" />
            </el-select>
            <el-button :icon="Refresh" :loading="loadingDevices" @click="fetchDevices">获取</el-button>
          </div>
          <div class="file-hint">仅当服务器与摄像头同机（本地部署）有效</div>
        </el-form-item>
        <el-form-item v-else label="RTSP 地址" prop="source">
          <el-input v-model="form.source" placeholder="rtsp://用户:密码@ip:554/stream" />
        </el-form-item>
        <el-form-item label="位置">
          <el-input v-model="form.location" placeholder="可选，安装位置/备注" />
        </el-form-item>
        <el-form-item label="分辨率宽">
          <el-input-number v-model="form.resolution" :min="160" :max="1920" :step="80" />
        </el-form-item>
        <el-form-item label="帧率">
          <el-input-number v-model="form.fps" :min="1" :max="30" />
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

    <!-- 预览 -->
    <el-dialog v-model="previewDialog" :title="`预览 - ${previewName}`" width="760px" @closed="closePreview">
      <div class="preview-stage">
        <img v-if="previewSrc" :src="previewSrc" class="preview-video" @error="onPreviewError" />
        <div v-if="previewErr" class="preview-err">无法读取视频源，请检查文件/RTSP 地址或状态</div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onBeforeUnmount } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Refresh, Plus, Edit, Delete, UploadFilled, VideoPlay } from '@element-plus/icons-vue'

import { cameraApi } from '../../api/camera'

const loading = ref(false)
const saving = ref(false)
const uploading = ref(false)
const rows = ref([])
const total = ref(0)
const query = reactive({ pageNum: 1, pageSize: 10, name: '', status: '' })

const load = async () => {
  loading.value = true
  try {
    const res = await cameraApi.list(query)
    rows.value = res.data.rows
    total.value = res.data.total
  } finally {
    loading.value = false
  }
}
const reset = () => { query.name = ''; query.status = ''; query.pageNum = 1; load() }

const selectedIds = ref([])
const onSelect = (sel) => { selectedIds.value = sel.map((r) => r.id) }

// 本机摄像头(DirectShow)设备枚举
const devices = ref([])
const loadingDevices = ref(false)
const fetchDevices = async () => {
  loadingDevices.value = true
  try {
    const res = await cameraApi.devices()
    devices.value = res.data || []
    if (!devices.value.length) ElMessage.warning('未发现本机摄像头设备')
  } catch (e) {
    ElMessage.error('获取本机摄像头失败')
  } finally {
    loadingDevices.value = false
  }
}

const SRC_META = {
  file: { label: '本地模拟', type: 'success' },
  rtsp: { label: '网络RTSP', type: 'warning' },
  device: { label: '本机摄像头', type: 'primary' },
}
const srcTagLabel = (t) => (SRC_META[t] || SRC_META.file).label
const srcTagType = (t) => (SRC_META[t] || SRC_META.file).type

const dialog = ref(false)
const formRef = ref()
const emptyForm = () => ({ id: null, name: '', sourceType: 'file', source: '', location: '', resolution: 640, fps: 15, status: '0' })
const form = reactive(emptyForm())
const rules = {
  name: [{ required: true, message: '请输入名称', trigger: 'blur' }],
  source: [{ required: true, message: '请提供来源（上传视频或填 RTSP 地址）', trigger: 'blur' }],
}
const resetForm = () => Object.assign(form, emptyForm())
const openAdd = () => { resetForm(); dialog.value = true }
const openEdit = (row) => { resetForm(); Object.assign(form, { ...row }); dialog.value = true }
const onTypeChange = () => { form.source = '' }

const beforeUpload = (file) => {
  if (file.size > 500 * 1024 * 1024) { ElMessage.error('文件超过 500MB 上限'); return false }
  return true
}
const doUpload = async (opt) => {
  uploading.value = true
  try {
    const fd = new FormData()
    fd.append('file', opt.file)
    const res = await cameraApi.upload(fd)
    form.source = res.data.filePath
    ElMessage.success('视频上传成功')
  } finally {
    uploading.value = false
  }
}

const submit = async () => {
  await formRef.value.validate()
  saving.value = true
  try {
    if (form.id) await cameraApi.update(form)
    else await cameraApi.add(form)
    ElMessage.success('保存成功')
    dialog.value = false
    load()
  } finally {
    saving.value = false
  }
}

const remove = async (row) => {
  await ElMessageBox.confirm(`确定删除摄像头「${row.name}」？`, '提示', { type: 'warning' })
  await cameraApi.remove(row.id)
  ElMessage.success('删除成功')
  load()
}
const batchRemove = async () => {
  await ElMessageBox.confirm(`确定删除选中的 ${selectedIds.value.length} 个摄像头？`, '提示', { type: 'warning' })
  await cameraApi.batchRemove(selectedIds.value)
  ElMessage.success('批量删除成功')
  load()
}

// 预览
const previewDialog = ref(false)
const previewSrc = ref('')
const previewName = ref('')
const previewErr = ref(false)
const openPreview = (row) => {
  if (row.status !== '0') { ElMessage.warning('摄像头已停用，无法预览'); return }
  previewErr.value = false
  previewName.value = row.name
  previewSrc.value = cameraApi.streamUrl(row.id)
  previewDialog.value = true
}
const onPreviewError = () => { previewErr.value = true }
const closePreview = () => { previewSrc.value = ''; previewErr.value = false }  // 断流 -> 后端 kill ffmpeg

onBeforeUnmount(() => { previewSrc.value = '' })
load()
</script>

<style scoped>
.search-card { margin-bottom: 12px; }
.toolbar { margin-bottom: 12px; }
.pager { margin-top: 14px; justify-content: flex-end; }
.file-hint { margin-top: 6px; font-size: 12px; color: #67c23a; word-break: break-all; }
.device-row { display: flex; gap: 8px; width: 100%; }
.preview-stage { position: relative; background: #0c1733; border-radius: 8px; min-height: 360px; display: flex; align-items: center; justify-content: center; }
.preview-video { max-width: 100%; max-height: 520px; border-radius: 6px; }
.preview-err { color: #f56c6c; font-size: 14px; }
</style>
