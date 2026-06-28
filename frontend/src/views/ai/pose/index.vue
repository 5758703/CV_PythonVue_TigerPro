<template>
  <div>
    <el-card shadow="never" class="cfg-card">
      <el-form :inline="true">
        <el-form-item label="模式">
          <el-radio-group v-model="mode" @change="clearAll">
            <el-radio-button value="image">图片</el-radio-button>
            <el-radio-button value="video">视频</el-radio-button>
            <el-radio-button value="camera">摄像头</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="模型分类">
          <el-select v-model="category" placeholder="全部分类" clearable style="width: 150px" @change="onCategoryChange">
            <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="姿态模型">
          <el-select v-model="modelId" placeholder="选择 pose 模型" style="width: 220px">
            <el-option v-for="m in filteredModels" :key="m.id"
                       :label="`${m.modelName}（${m.category || '未分类'}）`" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="置信度">
          <el-slider v-model="conf" :min="0.05" :max="0.95" :step="0.05" style="width: 150px" />
        </el-form-item>
        <el-form-item v-if="mode !== 'camera'">
          <el-upload :show-file-list="false" :auto-upload="false" :on-change="onPick" :accept="mode === 'image' ? 'image/*' : 'video/*'">
            <el-button :icon="UploadFilled">{{ mode === 'image' ? '选择图片' : '选择视频' }}</el-button>
          </el-upload>
        </el-form-item>
        <el-form-item v-if="mode !== 'camera'">
          <el-button type="primary" :icon="VideoPlay" :loading="running" :disabled="!modelId || !file" @click="run">开始估计</el-button>
          <el-button :icon="Refresh" @click="clearAll">清空</el-button>
        </el-form-item>
        <el-form-item v-if="mode === 'camera'" label="摄像头">
          <el-select v-model="deviceId" placeholder="默认摄像头" style="width: 180px" :disabled="camRunning">
            <el-option v-for="d in devices" :key="d.deviceId" :label="d.label || `摄像头 ${d.idx}`" :value="d.deviceId" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="mode === 'camera'">
          <el-button v-if="!camRunning" type="primary" :icon="VideoPlay" :disabled="!modelId" @click="camStart">开始</el-button>
          <el-button v-else type="danger" :icon="Refresh" @click="camStop">停止</el-button>
          <el-button v-if="recBlobUrl" link type="primary" :icon="Download" @click="downloadRec">下载录制</el-button>
        </el-form-item>
      </el-form>
      <el-alert v-if="!modelOptions.length" type="warning" :closable="false"
                title="暂无可用模型：姿态估计需 task=pose-estimation 的 YOLO 模型，请到「模型管理」上传/拉取并启用。" />
    </el-card>

    <el-card v-if="mode === 'video' && previewUrl" shadow="never" class="cfg-card">
      <div class="preview-title">原视频预览</div>
      <video :src="previewUrl" controls class="player" />
    </el-card>

    <el-card shadow="never">
      <div v-if="running" class="progress-box">
        <div class="progress-title">
          {{ mode === 'video' ? `处理中… ${processed}/${total || '?'} 帧` : '估计中…' }}
        </div>
        <el-progress v-if="mode === 'video'" :percentage="percent" :stroke-width="18" :text-inside="true" :status="percent >= 100 ? 'success' : ''" />
      </div>

      <!-- 摄像头舞台（独立 v-if，置于 image/video v-else-if 链之外） -->
      <div v-if="mode === 'camera'" class="cam-wrap">
        <div class="cam-stage">
          <video ref="camVideo" class="cam-video" autoplay playsinline muted></video>
          <canvas ref="camCanvas" class="cam-canvas"></canvas>
          <div v-if="!camRunning" class="cam-hint">点「开始」启用摄像头，实时显示骨架</div>
          <div v-if="camRunning" class="cam-hud">
            <el-tag type="success" effect="dark">{{ camFps }} FPS</el-tag>
            <el-tag type="warning" effect="dark">人数 {{ camCount }}</el-tag>
          </div>
        </div>
      </div>

      <el-empty v-else-if="!resultImg && !resultUrl" description="选择模型与文件后开始估计" />

      <!-- 图片结果 -->
      <div v-else-if="mode === 'image' && resultImg">
        <div class="res-title">
          姿态结果（检测到 {{ poseCount }} 个人体姿态）
          <el-button link type="primary" :icon="Download" @click="downloadImg">下载结果图</el-button>
        </div>
        <el-alert v-if="poseCount === 0" type="info" :closable="false"
                  title="未检测到人体姿态（请确认所选为 pose 模型）" style="margin-bottom: 10px" />
        <el-image :src="resultImg" :preview-src-list="[resultImg]" fit="contain" class="result-img" />
      </div>

      <!-- 视频结果 -->
      <div v-else-if="mode === 'video' && resultUrl">
        <div class="res-title">
          姿态视频结果
          <el-button link type="primary" :icon="Download" @click="downloadVideo">下载视频</el-button>
        </div>
        <video :src="resultUrl" controls class="player" />
        <div class="stats">
          <el-tag type="success" effect="dark">帧数：{{ stats.frames }}</el-tag>
          <el-tag type="warning" effect="dark">累计人体数：{{ stats.totalPersons }}</el-tag>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { UploadFilled, VideoPlay, Refresh, Download } from '@element-plus/icons-vue'
import { modelApi } from '../../../api/ai'

const mode = ref('image')
const modelOptions = ref([])
const modelId = ref(null)
const category = ref('')
const conf = ref(0.25)
const file = ref(null)
const previewUrl = ref('')   // 视频模式：选中视频的原视频回放 URL

const running = ref(false)
const processed = ref(0)
const total = ref(0)
const resultImg = ref('')      // 图片模式：data:image/jpeg;base64
const poseCount = ref(0)
const resultUrl = ref('')      // 视频模式：blob url
const stats = ref({})
let blobUrl = null
let pollTimer = null

// 摄像头模式状态
const devices = ref([])
const deviceId = ref('')
const camVideo = ref(null)
const camCanvas = ref(null)
const camRunning = ref(false)
const camCount = ref(0)
const camFps = ref(0)
const recBlobUrl = ref('')
let camStream = null, capCanvas = null, camBusy = false
let frameCount = 0, fpsTimer = null, recorder = null, recChunks = []
let recUrl = null
// COCO-17 骨架连接表（ultralytics 关键点顺序）
const SKELETON = [
  [5,7],[7,9],[6,8],[8,10],[5,6],[5,11],[6,12],[11,12],
  [11,13],[13,15],[12,14],[14,16],[0,1],[0,2],[1,3],[2,4],[3,5],[4,6],
]
const KP_CONF = 0.3

const categories = computed(() => [...new Set(modelOptions.value.map((m) => m.category).filter(Boolean))])
const filteredModels = computed(() =>
  category.value ? modelOptions.value.filter((m) => m.category === category.value) : modelOptions.value)
const percent = computed(() => (total.value ? Math.min(100, Math.floor((processed.value / total.value) * 100)) : 0))

const onCategoryChange = () => { modelId.value = filteredModels.value[0]?.id || null }

const loadModels = async () => {
  try {
    const res = await modelApi.list({ pageNum: 1, pageSize: 100 })
    modelOptions.value = (res.data.rows || []).filter(
      (m) => m.library === 'ultralytics' && m.task === 'pose-estimation' && m.filePath && m.status === '0')
    if (modelOptions.value.length && !modelId.value) modelId.value = modelOptions.value[0].id
  } catch (e) {
    ElMessage.error('加载模型列表失败')
  }
}

const onPick = (uploadFile) => {
  const raw = uploadFile.raw
  const wantImage = mode.value === 'image'
  if (!raw || (wantImage ? !raw.type.startsWith('image/') : !raw.type.startsWith('video/'))) {
    ElMessage.error(wantImage ? '请选择图片文件' : '请选择视频文件')
    return
  }
  file.value = raw
  resultImg.value = ''
  clearVideoOut()
  if (previewUrl.value) { URL.revokeObjectURL(previewUrl.value); previewUrl.value = '' }
  if (!wantImage) previewUrl.value = URL.createObjectURL(raw)
}

const run = async () => {
  if (mode.value === 'image') return runImage()
  return runVideo()
}

const runImage = async () => {
  running.value = true
  resultImg.value = ''
  try {
    const fd = new FormData()
    fd.append('file', file.value)
    fd.append('conf', conf.value)
    const res = await modelApi.pose(modelId.value, fd)
    const d = res.data
    poseCount.value = d.count
    resultImg.value = d.imageBase64 ? `data:image/jpeg;base64,${d.imageBase64}` : ''
  } catch (e) {
    ElMessage.error('姿态估计失败')
  } finally {
    running.value = false
  }
}

const runVideo = async () => {
  running.value = true
  processed.value = 0
  total.value = 0
  clearVideoOut()
  try {
    const fd = new FormData()
    fd.append('file', file.value)
    fd.append('conf', conf.value)
    const res = await modelApi.poseVideo(modelId.value, fd)
    await poll(res.data.jobId)
  } catch (e) {
    ElMessage.error('姿态估计启动失败')
    running.value = false
  }
}

const poll = (jobId) => new Promise((resolve) => {
  pollTimer = setInterval(async () => {
    try {
      const res = await modelApi.videoProgress(modelId.value, jobId)
      const d = res.data
      processed.value = d.processed
      total.value = d.total
      if (d.status === 'done') {
        clearInterval(pollTimer); pollTimer = null
        stats.value = d.stats
        const blob = await modelApi.outputVideo(d.stats.output)
        blobUrl = URL.createObjectURL(blob)
        resultUrl.value = blobUrl
        running.value = false
        resolve()
      }
    } catch (e) {
      clearInterval(pollTimer); pollTimer = null
      ElMessage.error('姿态视频处理失败')
      running.value = false
      resolve()
    }
  }, 1000)
})

const downloadImg = () => {
  const a = document.createElement('a')
  a.href = resultImg.value
  a.download = `pose_${Date.now()}.jpg`
  a.click()
}

const downloadVideo = () => {
  const a = document.createElement('a')
  a.href = resultUrl.value
  a.download = stats.value.output || 'pose.mp4'
  a.click()
}

const clearVideoOut = () => {
  if (blobUrl) { URL.revokeObjectURL(blobUrl); blobUrl = null }
  resultUrl.value = ''
}

const clearAll = () => {
  if (camRunning.value) camStop()
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
  if (previewUrl.value) { URL.revokeObjectURL(previewUrl.value); previewUrl.value = '' }
  file.value = null
  resultImg.value = ''
  poseCount.value = 0
  clearVideoOut()
  stats.value = {}
  processed.value = 0
  total.value = 0
  running.value = false
}

const enumCams = async () => {
  try {
    const list = await navigator.mediaDevices.enumerateDevices()
    devices.value = list.filter((d) => d.kind === 'videoinput')
      .map((d, i) => ({ deviceId: d.deviceId, label: d.label, idx: i + 1 }))
  } catch (e) { /* 授权前 label 空 */ }
}

const camStart = async () => {
  try {
    const constraints = { video: deviceId.value ? { deviceId: { exact: deviceId.value } } : true, audio: false }
    camStream = await navigator.mediaDevices.getUserMedia(constraints)
  } catch (e) { ElMessage.error('无法访问摄像头，请检查设备与浏览器权限'); return }
  camVideo.value.srcObject = camStream
  await camVideo.value.play()
  await enumCams()
  const vw = camVideo.value.videoWidth, vh = camVideo.value.videoHeight
  const capW = Math.min(vw, 640), capH = Math.round((vh * capW) / vw)
  capCanvas = document.createElement('canvas'); capCanvas.width = capW; capCanvas.height = capH
  camCanvas.value.width = capW; camCanvas.value.height = capH
  camRunning.value = true; frameCount = 0; camFps.value = 0
  if (recBlobUrl.value) { URL.revokeObjectURL(recUrl); recBlobUrl.value = '' }
  fpsTimer = setInterval(() => { camFps.value = frameCount; frameCount = 0 }, 1000)
  startRecording()
  camLoop()
}

const startRecording = () => {
  try {
    const mime = ['video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm']
      .find((t) => window.MediaRecorder && MediaRecorder.isTypeSupported(t))
    if (!mime) { ElMessage.warning('浏览器不支持录制，仅实时预览'); return }
    recChunks = []
    const stream = camCanvas.value.captureStream(15)
    recorder = new MediaRecorder(stream, { mimeType: mime })
    recorder.ondataavailable = (ev) => { if (ev.data && ev.data.size) recChunks.push(ev.data) }
    recorder.onstop = () => {
      if (!recChunks.length) return
      const blob = new Blob(recChunks, { type: 'video/webm' })
      if (recUrl) URL.revokeObjectURL(recUrl)
      recUrl = URL.createObjectURL(blob); recBlobUrl.value = recUrl
    }
    recorder.start()
  } catch (e) { ElMessage.warning('录制启动失败，仅实时预览') }
}

const camLoop = () => {
  if (!camRunning.value) return
  if (camBusy) { requestAnimationFrame(camLoop); return }
  camBusy = true
  const ctx = capCanvas.getContext('2d')
  ctx.drawImage(camVideo.value, 0, 0, capCanvas.width, capCanvas.height)
  capCanvas.toBlob(async (blob) => {
    if (!camRunning.value || !blob) { camBusy = false; return }
    try {
      const fd = new FormData()
      fd.append('file', blob, 'frame.jpg')
      fd.append('conf', conf.value)
      fd.append('draw', '0')
      const res = await modelApi.pose(modelId.value, fd)
      camCount.value = res.data.count
      camDraw(res.data.persons || [])
      frameCount++
    } catch (e) { /* 单帧失败忽略 */ } finally {
      camBusy = false
      if (camRunning.value) requestAnimationFrame(camLoop)
    }
  }, 'image/jpeg', 0.6)
}

const camDraw = (persons) => {
  const cv = camCanvas.value, ctx = cv.getContext('2d')
  ctx.clearRect(0, 0, cv.width, cv.height)
  ctx.drawImage(camVideo.value, 0, 0, cv.width, cv.height)  // 合成底图，供录制
  for (const p of persons) {
    const kp = p.keypoints
    ctx.strokeStyle = '#00e5ff'; ctx.lineWidth = 2
    for (const [a, b] of SKELETON) {
      if (kp[a] && kp[b] && kp[a][2] > KP_CONF && kp[b][2] > KP_CONF) {
        ctx.beginPath(); ctx.moveTo(kp[a][0], kp[a][1]); ctx.lineTo(kp[b][0], kp[b][1]); ctx.stroke()
      }
    }
    ctx.fillStyle = '#ff1744'
    for (const pt of kp) {
      if (pt[2] > KP_CONF) { ctx.beginPath(); ctx.arc(pt[0], pt[1], 3, 0, Math.PI * 2); ctx.fill() }
    }
  }
}

const camStop = () => {
  camRunning.value = false
  if (fpsTimer) { clearInterval(fpsTimer); fpsTimer = null }
  if (recorder && recorder.state !== 'inactive') recorder.stop()
  recorder = null
  if (camStream) { camStream.getTracks().forEach((t) => t.stop()); camStream = null }
  if (camVideo.value) camVideo.value.srcObject = null
  if (camCanvas.value) {
    const ctx = camCanvas.value.getContext('2d')
    ctx.clearRect(0, 0, camCanvas.value.width, camCanvas.value.height)
  }
  camCount.value = 0; camFps.value = 0
}

const downloadRec = () => {
  const a = document.createElement('a')
  a.href = recBlobUrl.value; a.download = `pose_cam_${Date.now()}.webm`; a.click()
}

onMounted(() => {
  loadModels()
  enumCams()
})
onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer)
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  clearVideoOut()
  camStop()
  if (recUrl) URL.revokeObjectURL(recUrl)
})
</script>

<style scoped>
.cfg-card { margin-bottom: 12px; }
.progress-box { padding: 22px 4px; }
.progress-title { font-weight: 600; color: #3a4a63; margin-bottom: 12px; }
.res-title { display: flex; align-items: center; gap: 12px; font-weight: 600; color: #3a4a63; margin-bottom: 12px; }
.preview-title { font-weight: 600; color: #3a4a63; margin-bottom: 10px; }
.result-img { max-width: 100%; max-height: 560px; border: 1px solid #ebeef5; border-radius: 6px; }
.player { width: 100%; max-height: 480px; background: #000; border-radius: 6px; }
.stats { display: flex; gap: 10px; margin-top: 12px; }
.cam-wrap { margin-top: 8px; }
.cam-stage { position: relative; background: #0c1733; border-radius: 8px; aspect-ratio: 16/9; overflow: hidden; }
.cam-video { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; }
.cam-canvas { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; }
.cam-hint { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; color: #8aa0c8; }
.cam-hud { position: absolute; top: 10px; left: 10px; display: flex; gap: 8px; }
</style>
