<template>
  <div>
    <el-alert
      type="info"
      :closable="false"
      show-icon
      class="notice"
      title="合规提示：人脸生物特征属敏感个人信息。请仅在取得授权的场景使用，控制留存期限；InsightFace 模型许可请自行评估商业用途。"
    />

    <el-tabs v-model="tab" class="tabs">
      <el-tab-pane label="实时识别" name="live" />
      <el-tab-pane label="人脸底库" name="gallery" />
    </el-tabs>

    <!-- 实时识别 -->
    <template v-if="tab === 'live'">
      <el-card shadow="never" class="cfg-card">
        <el-form :inline="true">
          <el-form-item label="识别模型">
            <el-select v-model="modelId" placeholder="选择模型" style="width: 240px" :disabled="running">
              <el-option
                v-for="m in modelOptions"
                :key="m.id"
                :label="`${m.modelName}（${m.version || m.modelKey}）`"
                :value="m.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="摄像头">
            <el-select v-model="deviceId" placeholder="默认摄像头" style="width: 200px" :disabled="running">
              <el-option
                v-for="d in devices"
                :key="d.deviceId"
                :label="d.label || `摄像头 ${d.idx}`"
                :value="d.deviceId"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="相似度阈值">
            <el-slider v-model="threshold" :min="0.2" :max="0.8" :step="0.05" style="width: 140px" />
          </el-form-item>
          <el-form-item label="隔帧">
            <el-input-number v-model="skipFrames" :min="0" :max="5" :disabled="running" />
            <span class="hint">CPU 建议 2～3</span>
          </el-form-item>
          <el-form-item>
            <el-button v-if="!running" type="primary" :icon="VideoCamera" :disabled="!modelId" @click="start">
              开始识别
            </el-button>
            <el-button v-else type="danger" :icon="SwitchButton" @click="stop">停止</el-button>
          </el-form-item>
        </el-form>
        <el-alert
          v-if="!modelOptions.length"
          type="warning"
          :closable="false"
          title="暂无可用人脸模型：请到「模型管理」拉取 InsightFace Buffalo-S/L 权重。"
        />
      </el-card>

      <el-card shadow="never">
        <div class="live-grid">
          <div class="stage">
            <video ref="videoEl" class="cam-video" autoplay playsinline muted></video>
            <canvas ref="overlayEl" class="overlay"></canvas>
            <div v-if="!running" class="stage-hint">
              <el-icon :size="40"><VideoCamera /></el-icon>
              <span>点击「开始识别」启用摄像头</span>
            </div>
            <div v-if="running" class="hud">
              <el-tag type="success" effect="dark">{{ fps }} FPS</el-tag>
              <el-tag type="warning" effect="dark">人脸 {{ dets.length }}</el-tag>
              <el-tag v-if="matchedCount" type="primary" effect="dark">已识别 {{ matchedCount }}</el-tag>
            </div>
          </div>
          <div class="side">
            <div class="side-title">识别结果</div>
            <el-empty v-if="!dets.length" :image-size="60" description="无人脸" />
            <el-table v-else :data="dets" size="small" border max-height="460">
              <el-table-column type="index" label="#" width="48" />
              <el-table-column prop="name" label="姓名" />
              <el-table-column label="相似度" width="90">
                <template #default="{ row }">{{ (row.score * 100).toFixed(0) }}%</template>
              </el-table-column>
              <el-table-column label="状态" width="80">
                <template #default="{ row }">
                  <el-tag :type="row.matched ? 'success' : 'info'" size="small">
                    {{ row.matched ? '匹配' : '未知' }}
                  </el-tag>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </div>
      </el-card>
    </template>

    <!-- 底库管理 -->
    <template v-else>
      <el-card shadow="never" class="cfg-card">
        <el-form :inline="true">
          <el-form-item label="姓名">
            <el-input v-model="galleryQuery" clearable placeholder="搜索" @keyup.enter="loadPersons" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="loadPersons">查询</el-button>
            <el-button type="success" v-permission="'ai:face:add'" @click="openCreate">新增人员</el-button>
          </el-form-item>
        </el-form>
      </el-card>
      <el-card shadow="never">
        <el-table :data="persons" border stripe v-loading="galleryLoading">
          <el-table-column prop="id" label="ID" width="70" />
          <el-table-column prop="name" label="姓名" />
          <el-table-column prop="employeeNo" label="工号" width="120" />
          <el-table-column prop="embeddingCount" label="特征数" width="90" />
          <el-table-column prop="remark" label="备注" show-overflow-tooltip />
          <el-table-column label="状态" width="80">
            <template #default="{ row }">
              <el-tag :type="row.status === '0' ? 'success' : 'info'" size="small">
                {{ row.status === '0' ? '启用' : '停用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="260" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" v-permission="'ai:face:add'" @click="openEnroll(row)">登记人脸</el-button>
              <el-button link type="primary" v-permission="'ai:face:edit'" @click="openEdit(row)">编辑</el-button>
              <el-button link type="danger" v-permission="'ai:face:remove'" @click="onRemove(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-card>
    </template>

    <el-dialog v-model="personDlg" :title="personForm.id ? '编辑人员' : '新增人员'" width="420px">
      <el-form label-width="80px">
        <el-form-item label="姓名" required>
          <el-input v-model="personForm.name" />
        </el-form-item>
        <el-form-item label="工号">
          <el-input v-model="personForm.employeeNo" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="personForm.remark" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item v-if="personForm.id" label="状态">
          <el-radio-group v-model="personForm.status">
            <el-radio value="0">启用</el-radio>
            <el-radio value="1">停用</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="personDlg = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="savePerson">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="enrollDlg" title="登记人脸" width="480px">
      <p class="enroll-tip">选择识别模型并上传 1～5 张清晰正脸照（同人多图将平均特征）。换模型需重新登记。</p>
      <el-form label-width="90px">
        <el-form-item label="人员">{{ enrollPerson?.name }}</el-form-item>
        <el-form-item label="识别模型" required>
          <el-select v-model="enrollModelId" style="width: 100%">
            <el-option
              v-for="m in modelOptions"
              :key="m.id"
              :label="`${m.modelName}（${m.version || m.modelKey}）`"
              :value="m.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="人脸照片" required>
          <el-upload
            ref="uploadRef"
            :auto-upload="false"
            :limit="5"
            accept="image/*"
            list-type="picture-card"
            v-model:file-list="enrollFiles"
          >
            <el-icon><Plus /></el-icon>
          </el-upload>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="enrollDlg = false">取消</el-button>
        <el-button type="primary" :loading="enrolling" @click="doEnroll">提交登记</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { VideoCamera, SwitchButton, Plus } from '@element-plus/icons-vue'

import { modelApi, faceApi } from '../../../api/ai'

const tab = ref('live')
const modelOptions = ref([])
const modelId = ref(null)
const threshold = ref(0.4)
const skipFrames = ref(2)
const devices = ref([])
const deviceId = ref('')

const videoEl = ref(null)
const overlayEl = ref(null)
const running = ref(false)
const dets = ref([])
const fps = ref(0)
const matchedCount = computed(() => dets.value.filter((d) => d.matched).length)

let stream = null
let capCanvas = null
let busy = false
let frameCount = 0
let fpsTimer = null
let skipCounter = 0
let lastDets = []

const COLORS = ['#67c23a', '#409eff', '#e6a23c', '#f56c6c', '#9254de', '#13c2c2']

const galleryQuery = ref('')
const persons = ref([])
const galleryLoading = ref(false)
const personDlg = ref(false)
const saving = ref(false)
const personForm = ref({ id: null, name: '', employeeNo: '', remark: '', status: '0' })

const enrollDlg = ref(false)
const enrollPerson = ref(null)
const enrollModelId = ref(null)
const enrollFiles = ref([])
const enrolling = ref(false)

const loadModels = async () => {
  const res = await modelApi.list({ pageNum: 1, pageSize: 100 })
  modelOptions.value = (res.data.rows || []).filter(
    (m) => m.task === 'face-recognition' && m.library === 'insightface' && m.filePath && m.status === '0'
  )
  if (modelOptions.value.length && !modelId.value) modelId.value = modelOptions.value[0].id
  if (modelOptions.value.length && !enrollModelId.value) enrollModelId.value = modelOptions.value[0].id
}

const enumCams = async () => {
  try {
    const list = await navigator.mediaDevices.enumerateDevices()
    devices.value = list
      .filter((d) => d.kind === 'videoinput')
      .map((d, i) => ({ deviceId: d.deviceId, label: d.label, idx: i + 1 }))
  } catch (_) {
    /* ignore */
  }
}

const iou = (a, b) => {
  const [ax1, ay1, ax2, ay2] = a
  const [bx1, by1, bx2, by2] = b
  const ix1 = Math.max(ax1, bx1)
  const iy1 = Math.max(ay1, by1)
  const ix2 = Math.min(ax2, bx2)
  const iy2 = Math.min(ay2, by2)
  const iw = Math.max(0, ix2 - ix1)
  const ih = Math.max(0, iy2 - iy1)
  const inter = iw * ih
  const ua = Math.max(0, ax2 - ax1) * Math.max(0, ay2 - ay1) + Math.max(0, bx2 - bx1) * Math.max(0, by2 - by1) - inter
  return ua > 0 ? inter / ua : 0
}

const start = async () => {
  try {
    const constraints = {
      video: deviceId.value ? { deviceId: { exact: deviceId.value } } : true,
      audio: false,
    }
    stream = await navigator.mediaDevices.getUserMedia(constraints)
  } catch (_) {
    ElMessage.error('无法访问摄像头，请检查设备与浏览器权限')
    return
  }
  videoEl.value.srcObject = stream
  await videoEl.value.play()
  await enumCams()

  const vw = videoEl.value.videoWidth
  const vh = videoEl.value.videoHeight
  const capW = Math.min(vw, 640)
  const capH = Math.round((vh * capW) / vw)
  capCanvas = document.createElement('canvas')
  capCanvas.width = capW
  capCanvas.height = capH
  overlayEl.value.width = capW
  overlayEl.value.height = capH

  running.value = true
  frameCount = 0
  fps.value = 0
  skipCounter = 0
  lastDets = []
  fpsTimer = setInterval(() => {
    fps.value = frameCount
    frameCount = 0
  }, 1000)
  loop()
}

const loop = () => {
  if (!running.value) return
  if (busy) {
    requestAnimationFrame(loop)
    return
  }
  busy = true

  const ctx = capCanvas.getContext('2d')
  ctx.drawImage(videoEl.value, 0, 0, capCanvas.width, capCanvas.height)

  // 隔帧：复用上一帧识别结果画框，降低 CPU 压力
  if (skipCounter < skipFrames.value && lastDets.length) {
    drawBoxes(lastDets)
    dets.value = lastDets
    frameCount++
    skipCounter++
    busy = false
    if (running.value) requestAnimationFrame(loop)
    return
  }
  skipCounter = 0

  capCanvas.toBlob(async (blob) => {
    if (!running.value || !blob) {
      busy = false
      return
    }
    try {
      const fd = new FormData()
      fd.append('file', blob, 'frame.jpg')
      fd.append('modelId', modelId.value)
      fd.append('threshold', threshold.value)
      fd.append('draw', '0')
      const res = await faceApi.recognize(fd)
      const list = res.data.detections || []
      // 简单 IoU 跟踪：跨帧保留姓名标签更稳
      const tracked = list.map((d) => {
        const prev = lastDets.find((p) => iou(p.bbox, d.bbox) > 0.3)
        if (prev && !d.matched && prev.matched) {
          return { ...d, name: prev.name, matched: prev.matched, score: prev.score, personId: prev.personId }
        }
        return d
      })
      lastDets = tracked
      dets.value = tracked
      drawBoxes(tracked)
      frameCount++
    } catch (_) {
      /* 单帧失败忽略 */
    } finally {
      busy = false
      if (running.value) requestAnimationFrame(loop)
    }
  }, 'image/jpeg', 0.6)
}

const drawBoxes = (list) => {
  const cv = overlayEl.value
  if (!cv) return
  const ctx = cv.getContext('2d')
  ctx.clearRect(0, 0, cv.width, cv.height)
  ctx.lineWidth = 2
  ctx.font = '14px sans-serif'
  ctx.textBaseline = 'top'
  list.forEach((d, i) => {
    const [x1, y1, x2, y2] = d.bbox
    const color = d.matched ? COLORS[0] : COLORS[3]
    ctx.strokeStyle = color
    ctx.strokeRect(x1, y1, x2 - x1, y2 - y1)
    const label = `${d.name} ${(d.score * 100).toFixed(0)}%`
    const tw = ctx.measureText(label).width + 8
    ctx.fillStyle = color
    ctx.fillRect(x1, Math.max(0, y1 - 18), tw, 18)
    ctx.fillStyle = '#fff'
    ctx.fillText(label, x1 + 4, Math.max(0, y1 - 17))
  })
}

const stop = () => {
  running.value = false
  if (fpsTimer) {
    clearInterval(fpsTimer)
    fpsTimer = null
  }
  if (stream) {
    stream.getTracks().forEach((t) => t.stop())
    stream = null
  }
  if (videoEl.value) videoEl.value.srcObject = null
  if (overlayEl.value) {
    const ctx = overlayEl.value.getContext('2d')
    ctx.clearRect(0, 0, overlayEl.value.width, overlayEl.value.height)
  }
  dets.value = []
  lastDets = []
  fps.value = 0
}

const loadPersons = async () => {
  galleryLoading.value = true
  try {
    const res = await faceApi.listPersons({ name: galleryQuery.value || undefined })
    persons.value = res.data.rows || []
  } finally {
    galleryLoading.value = false
  }
}

const openCreate = () => {
  personForm.value = { id: null, name: '', employeeNo: '', remark: '', status: '0' }
  personDlg.value = true
}

const openEdit = (row) => {
  personForm.value = {
    id: row.id,
    name: row.name,
    employeeNo: row.employeeNo || '',
    remark: row.remark || '',
    status: row.status || '0',
  }
  personDlg.value = true
}

const savePerson = async () => {
  if (!personForm.value.name?.trim()) {
    ElMessage.warning('请填写姓名')
    return
  }
  saving.value = true
  try {
    if (personForm.value.id) {
      await faceApi.updatePerson(personForm.value.id, personForm.value)
    } else {
      await faceApi.addPerson(personForm.value)
    }
    ElMessage.success('已保存')
    personDlg.value = false
    await loadPersons()
  } finally {
    saving.value = false
  }
}

const onRemove = async (row) => {
  await ElMessageBox.confirm(`确认删除「${row.name}」及其全部人脸特征？`, '提示', { type: 'warning' })
  await faceApi.removePerson(row.id)
  ElMessage.success('已删除')
  await loadPersons()
}

const openEnroll = (row) => {
  enrollPerson.value = row
  enrollFiles.value = []
  if (!enrollModelId.value && modelOptions.value.length) enrollModelId.value = modelOptions.value[0].id
  enrollDlg.value = true
}

const doEnroll = async () => {
  if (!enrollModelId.value) {
    ElMessage.warning('请选择识别模型')
    return
  }
  const rawFiles = enrollFiles.value.map((f) => f.raw).filter(Boolean)
  if (!rawFiles.length) {
    ElMessage.warning('请上传人脸照片')
    return
  }
  const fd = new FormData()
  fd.append('modelId', enrollModelId.value)
  rawFiles.forEach((f) => fd.append('files', f))
  enrolling.value = true
  try {
    await faceApi.enroll(enrollPerson.value.id, fd)
    ElMessage.success('登记成功')
    enrollDlg.value = false
    await loadPersons()
  } finally {
    enrolling.value = false
  }
}

watch(tab, (v) => {
  if (v === 'gallery') loadPersons()
  if (v !== 'live') stop()
})

onMounted(async () => {
  await loadModels()
  await enumCams()
})
onBeforeUnmount(stop)
</script>

<style scoped>
.notice {
  margin-bottom: 12px;
}
.tabs {
  margin-bottom: 4px;
}
.cfg-card {
  margin-bottom: 12px;
}
.hint {
  margin-left: 8px;
  color: #909399;
  font-size: 12px;
}
.live-grid {
  display: flex;
  gap: 16px;
}
.stage {
  position: relative;
  flex: 1 1 70%;
  min-width: 0;
  background: #0c1733;
  border-radius: 8px;
  aspect-ratio: 16 / 9;
  overflow: hidden;
}
.cam-video,
.overlay {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: contain;
}
.overlay {
  pointer-events: none;
}
.stage-hint {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: #8aa0c8;
}
.hud {
  position: absolute;
  top: 10px;
  left: 10px;
  display: flex;
  gap: 8px;
}
.side {
  flex: 1 1 30%;
  min-width: 0;
}
.side-title {
  font-weight: 600;
  color: #3a4a63;
  margin-bottom: 10px;
}
.enroll-tip {
  color: #606266;
  font-size: 13px;
  margin: 0 0 12px;
  line-height: 1.5;
}
</style>
