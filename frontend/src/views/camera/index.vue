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
        <el-table-column prop="source" label="来源" min-width="180" show-overflow-tooltip />
        <el-table-column label="来源状态" width="96" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.sourceType === 'file'" size="small" :type="row.sourceReady ? 'success' : 'danger'">
              {{ row.sourceReady ? '文件就绪' : '文件缺失' }}
            </el-tag>
            <el-tag v-else-if="row.sourceType === 'device'" size="small" :type="row.sourceReady ? 'success' : 'info'">
              {{ row.sourceReady ? '已配置' : '未配置' }}
            </el-tag>
            <span v-else class="muted-text">推流时可用</span>
          </template>
        </el-table-column>
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

    <el-collapse v-model="guideOpen" class="rtsp-guide">
      <el-collapse-item name="source">
        <template #title>
          <span class="rtsp-guide-title">来源类型说明：本地视频 vs 网络 RTSP</span>
        </template>
        <div class="rtsp-guide-body">
          <el-table :data="sourceCompareRows" size="small" border class="compare-table">
            <el-table-column prop="item" label="对比项" width="120" />
            <el-table-column prop="file" label="本地视频（ffmpeg 模拟）" />
            <el-table-column prop="rtsp" label="网络摄像头（RTSP）" />
          </el-table>
        </div>
      </el-collapse-item>
      <el-collapse-item name="guide">
        <template #title>
          <span class="rtsp-guide-title">网络 RTSP 推流说明（MediaMTX + ffmpeg）</span>
        </template>
        <div class="rtsp-guide-body">
          <p class="rtsp-intro">
            来源类型选 <b>网络摄像头（RTSP）</b> 时，需先有 RTSP 服务。开发/测试可用
            <a href="https://github.com/bluenviron/mediamtx" target="_blank" rel="noopener">MediaMTX</a>
            接收推流，再用 ffmpeg 将本地 MP4 循环推送到该服务，最后在上方新增摄像头并填写对应 RTSP 地址。
          </p>

          <div class="rtsp-step">
            <div class="step-hd">步骤 1：启动 MediaMTX（独立二进制，PowerShell）</div>
            <p>下载 Windows 版后进入解压目录，执行（路径按本机安装位置修改）：</p>
            <pre class="cmd-block">cd E:\DevelopmentEnvironment\mediamtx_v1.19.2_windows_amd64
.\mediamtx.exe</pre>
            <p class="step-note">默认 RTSP 监听 <code>8554</code> 端口；保持此窗口运行，不要关闭。</p>
          </div>

          <div class="rtsp-step">
            <div class="step-hd">步骤 2：用 ffmpeg 将本地 MP4 循环推为 RTSP 流</div>
            <p>另开一个终端，在 MP4 所在目录执行（<code>footballtrack.mp4</code> 换成你的文件名）：</p>
            <pre class="cmd-block">ffmpeg -re -stream_loop -1 -i footballtrack.mp4 -c copy -f rtsp rtsp://localhost:8554/footballtrack</pre>
            <p class="step-note">
              路径 <code>/footballtrack</code> 为流名称，可自定义；推流成功后 MediaMTX 日志会出现 publisher 连接。
            </p>
          </div>

          <div class="rtsp-step">
            <div class="step-hd">步骤 3：在表格上方新增摄像头</div>
            <ul class="step-list">
              <li>来源类型：<b>网络摄像头（RTSP）</b></li>
              <li>RTSP 地址：<code>rtsp://localhost:8554/footballtrack</code>（与步骤 2 流名称一致）</li>
              <li>保存后点击 <b>预览</b>，或在「实时监控大屏」中选择该摄像头</li>
            </ul>
          </div>

          <el-alert type="info" :closable="false" show-icon class="rtsp-alert"
            title="提示：后端通过 ffmpeg 以 TCP 方式拉取 RTSP；请确保 MediaMTX 与后端在同一台机器，或 RTSP 地址对服务器可达。本机未安装 ffmpeg 时预览会失败。" />
        </div>
      </el-collapse-item>
    </el-collapse>

    <!-- 新增/编辑 -->
    <el-dialog v-model="dialog" :title="form.id ? '修改摄像头' : '新增摄像头'" width="580px" @closed="resetForm">
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

        <el-alert v-if="form.sourceType === 'file'" :closable="false" show-icon type="success" class="type-tip"
          title="本地视频：上传 MP4 到服务器，ffmpeg 按原帧率循环转 MJPEG，无需 MediaMTX，适合单机演示与测试。" />
        <el-alert v-else-if="form.sourceType === 'rtsp'" :closable="false" show-icon type="warning" class="type-tip"
          title="网络 RTSP：从 rtsp:// 地址拉流（如 MediaMTX+ffmpeg 推流、真实 IPC），需源端持续在线推流。" />
        <el-alert v-else :closable="false" show-icon type="info" class="type-tip"
          title="本机摄像头：读取服务器电脑的 USB 摄像头（DirectShow），仅本地部署有效。" />

        <el-form-item v-if="form.sourceType === 'file'" label="视频文件" prop="source">
          <el-upload :show-file-list="false" :before-upload="beforeUpload" :http-request="doUpload" accept="video/*">
            <el-button :icon="UploadFilled" :loading="uploading">上传视频到服务器</el-button>
          </el-upload>
          <div v-if="form.source" class="file-hint">
            已上传：{{ uploadedName || form.sourceFileName || form.source }}
          </div>
          <div class="file-hint muted">预览时将循环播放；建议 MP4(H.264)，分辨率宽与帧率可在下方调整</div>
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
          <el-input v-model="form.source" placeholder="rtsp://localhost:8554/footballtrack" />
          <div class="file-hint muted">开发测试可参考表格下方「网络 RTSP 推流说明」</div>
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
    <el-dialog v-model="previewDialog" :title="`预览 - ${previewName}`" width="800px" @closed="closePreview">
      <div class="preview-meta">
        <el-tag size="small" :type="srcTagType(previewRow?.sourceType || 'file')">
          {{ srcTagLabel(previewRow?.sourceType || 'file') }}
        </el-tag>
        <span v-if="previewRow?.source" class="preview-source">{{ previewRow.source }}</span>
      </div>
      <div class="preview-stage">
        <div v-if="previewLoading && !previewErr" class="preview-loading">
          <el-icon class="rotating" :size="28"><Loading /></el-icon>
          <span>正在连接视频流…</span>
        </div>
        <img v-show="previewSrc && !previewErr"
             :key="previewKey"
             :src="previewSrc"
             class="preview-video"
             @load="onPreviewLoad"
             @error="onPreviewError" />
        <div v-if="previewErr" class="preview-err-box">
          <p>{{ previewErrHint }}</p>
          <el-button type="primary" size="small" :icon="Refresh" @click="retryPreview">重新连接</el-button>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onBeforeUnmount } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Refresh, Plus, Edit, Delete, UploadFilled, VideoPlay, Loading } from '@element-plus/icons-vue'

import { cameraApi } from '../../api/camera'

const loading = ref(false)
const saving = ref(false)
const uploading = ref(false)
const guideOpen = ref([])
const sourceCompareRows = [
  { item: '视频来源', file: '上传 MP4 到服务器 uploads/cameras/', rtsp: '外部 rtsp:// 地址（IPC、NVR、MediaMTX 等）' },
  { item: '依赖服务', file: '仅需后端 ffmpeg，无需 RTSP 服务', rtsp: '需推流端持续在线（如 MediaMTX+ffmpeg）' },
  { item: '播放方式', file: 'ffmpeg 循环读取本地文件，按原帧率模拟直播', rtsp: 'ffmpeg 以 TCP 拉取网络 RTSP 流' },
  { item: '适用场景', file: '单机演示、离线测试、快速验证大屏', rtsp: '多路流、模拟真实监控、与第三方系统对接' },
  { item: '配置步骤', file: '上传视频 → 保存 → 预览', rtsp: '启动推流 → 填写 RTSP 地址 → 预览' },
]
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
const uploadedName = ref('')
const resetForm = () => { Object.assign(form, emptyForm()); uploadedName.value = '' }
const openAdd = () => { resetForm(); dialog.value = true }
const openEdit = (row) => {
  resetForm()
  Object.assign(form, { ...row })
  uploadedName.value = row.sourceFileName || ''
  dialog.value = true
}
const onTypeChange = () => { form.source = ''; uploadedName.value = '' }

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
    uploadedName.value = res.data.fileName || ''
    ElMessage.success('视频已上传到服务器，保存后即可预览循环播放')
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
const previewKey = ref(0)
const previewName = ref('')
const previewRow = ref(null)
const previewLoading = ref(false)
const previewErr = ref(false)
const previewErrDetail = ref('')
let previewLoadTimer = null

const clearPreviewTimer = () => {
  if (previewLoadTimer) {
    clearTimeout(previewLoadTimer)
    previewLoadTimer = null
  }
}

const armPreviewTimeout = () => {
  clearPreviewTimer()
  previewLoadTimer = setTimeout(() => {
    if (previewLoading.value) {
      previewLoading.value = false
      previewErr.value = true
      if (!previewErrDetail.value) {
        previewErrDetail.value = '视频流连接超时，请重试或降低分辨率/帧率'
      }
      previewSrc.value = ''
    }
  }, 18000)
}

/** 开流前轻量探测（仅本地视频需 ffmpeg 预检） */
async function probeStream(row) {
  const bust = Date.now()
  if (row.sourceType === 'file') {
    const checkUrl = cameraApi.streamUrl(row.id, bust, true)
    const ctrl = new AbortController()
    const timer = setTimeout(() => ctrl.abort(), 22000)
    try {
      const res = await fetch(checkUrl, { signal: ctrl.signal })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        throw new Error(data.message || `连接失败 (${res.status})`)
      }
    } catch (e) {
      if (e.name === 'AbortError') {
        throw new Error('连接超时，请确认视频可解码或降低分辨率/帧率')
      }
      throw e
    } finally {
      clearTimeout(timer)
    }
  }
  return cameraApi.streamUrl(row.id, bust)
}

const previewErrHint = computed(() => {
  if (previewErrDetail.value) return previewErrDetail.value
  const row = previewRow.value
  if (!row) return '无法读取视频源'
  if (row.sourceType === 'file') {
    return row.sourceReady === false
      ? '服务器上找不到该视频文件，请重新上传或检查 uploads/cameras/ 目录'
      : '本地视频转流失败，请确认文件为可解码的 MP4，或调低分辨率/帧率后重试'
  }
  if (row.sourceType === 'rtsp') {
    return '无法连接 RTSP 地址，请确认 MediaMTX/推流端已启动且地址正确'
  }
  return '无法打开本机摄像头，请确认设备名正确且服务器可访问该设备'
})

const startPreviewStream = async (row) => {
  previewErr.value = false
  previewErrDetail.value = ''
  previewLoading.value = true
  previewSrc.value = ''
  clearPreviewTimer()
  try {
    const url = await probeStream(row)
    previewKey.value += 1
    previewSrc.value = url
    armPreviewTimeout()
  } catch (e) {
    previewLoading.value = false
    previewErr.value = true
    previewErrDetail.value = e?.message || '无法连接视频流'
  }
}

const openPreview = async (row) => {
  if (row.status !== '0') { ElMessage.warning('摄像头已停用，无法预览'); return }
  if (row.sourceType === 'file' && row.sourceReady === false) {
    ElMessage.error('视频文件不存在，请先上传或修改来源')
    return
  }
  previewRow.value = row
  previewName.value = row.name
  previewDialog.value = true
  await startPreviewStream(row)
}
const onPreviewLoad = () => {
  clearPreviewTimer()
  previewLoading.value = false
  previewErr.value = false
}
const onPreviewError = () => {
  clearPreviewTimer()
  previewLoading.value = false
  previewErr.value = true
  if (!previewErrDetail.value) {
    previewErrDetail.value = '视频流中断或无法解码'
  }
}
const retryPreview = async () => {
  if (!previewRow.value) return
  await startPreviewStream(previewRow.value)
}
const closePreview = () => {
  clearPreviewTimer()
  previewSrc.value = ''
  previewErr.value = false
  previewErrDetail.value = ''
  previewLoading.value = false
  previewRow.value = null
}

onBeforeUnmount(() => { clearPreviewTimer(); previewSrc.value = '' })
load()
</script>

<style scoped>
.search-card { margin-bottom: 12px; }
.rtsp-guide { margin-top: 12px; margin-bottom: 0; border: 1px solid #ebeef5; border-radius: 4px; overflow: hidden; }
.rtsp-guide :deep(.el-collapse-item__header) { padding: 0 16px; font-weight: 600; color: #303133; background: #f8fafc; }
.rtsp-guide :deep(.el-collapse-item__wrap) { border-top: 1px solid #ebeef5; }
.rtsp-guide-title { font-size: 14px; }
.rtsp-guide-body { padding: 4px 16px 16px; font-size: 13px; color: #606266; line-height: 1.65; }
.rtsp-intro { margin: 0 0 14px; }
.rtsp-step { margin-bottom: 16px; }
.step-hd { font-weight: 600; color: #303133; margin-bottom: 6px; }
.step-note { margin: 6px 0 0; font-size: 12px; color: #909399; }
.step-list { margin: 6px 0 0; padding-left: 20px; }
.step-list li { margin-bottom: 4px; }
.cmd-block {
  margin: 8px 0 0;
  padding: 10px 12px;
  background: #1e1e1e;
  color: #d4d4d4;
  border-radius: 6px;
  font-family: ui-monospace, Consolas, monospace;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
  user-select: all;
}
.compare-table { margin-top: 4px; }
.muted-text { font-size: 12px; color: #909399; }
.type-tip { margin: 0 0 14px; }
.toolbar { margin-bottom: 12px; }
.pager { margin-top: 14px; justify-content: flex-end; }
.file-hint { margin-top: 6px; font-size: 12px; color: #67c23a; word-break: break-all; }
.file-hint.muted { color: #909399; }
.device-row { display: flex; gap: 8px; width: 100%; }
.preview-meta {
  display: flex; align-items: center; gap: 10px; margin-bottom: 10px;
  font-size: 12px; color: #606266;
}
.preview-source { word-break: break-all; flex: 1; }
.preview-stage {
  position: relative; background: #0c1733; border-radius: 8px; min-height: 360px;
  display: flex; align-items: center; justify-content: center;
}
.preview-loading {
  display: flex; flex-direction: column; align-items: center; gap: 10px;
  color: #8aa0c8; font-size: 14px;
}
.preview-video { max-width: 100%; max-height: 520px; border-radius: 6px; }
.preview-err-box { text-align: center; padding: 24px; color: #f56c6c; font-size: 14px; line-height: 1.6; }
.preview-err-box p { margin: 0 0 14px; max-width: 420px; }
.rotating { animation: spin 1s linear infinite; }
@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
</style>
