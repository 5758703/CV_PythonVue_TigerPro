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
        <el-form-item label="姿态模型">
          <el-select v-model="modelId" placeholder="选择 pose 模型" style="width: 260px">
            <el-option v-for="m in modelOptions" :key="m.id" :label="modelLabel(m)" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="置信度">
          <el-slider v-model="conf" :min="0.05" :max="0.95" :step="0.05" style="width: 130px" />
        </el-form-item>
        <el-form-item label="记录事件">
          <el-switch v-model="persist" />
        </el-form-item>
        <el-form-item v-if="mode === 'video' || mode === 'camera'" label="告警声音">
          <el-switch v-model="soundOn" />
        </el-form-item>
        <el-form-item v-if="mode === 'image'">
          <el-upload :show-file-list="false" :auto-upload="false" :on-change="onPick" accept="image/*">
            <el-button :icon="UploadFilled">选择图片</el-button>
          </el-upload>
        </el-form-item>
        <el-form-item v-if="mode === 'image'">
          <el-button type="primary" :icon="VideoPlay" :loading="running" :disabled="!modelId || !file" @click="runImage">开始检测</el-button>
          <el-button :icon="Refresh" @click="clearAll">清空</el-button>
        </el-form-item>
        <el-form-item v-if="mode === 'video'">
          <el-upload :show-file-list="false" :auto-upload="false" :on-change="onPickVideo" accept="video/*">
            <el-button :icon="UploadFilled">选择视频</el-button>
          </el-upload>
        </el-form-item>
        <el-form-item v-if="mode === 'video'">
          <el-button type="primary" :icon="VideoPlay" :loading="videoRunning" :disabled="!modelId || !videoFile" @click="runVideo">开始检测</el-button>
          <el-button :icon="Refresh" @click="clearAll">清空</el-button>
        </el-form-item>
        <el-form-item v-if="mode === 'camera'" label="摄像头">
          <el-select v-model="deviceId" placeholder="默认摄像头" style="width: 170px" :disabled="camRunning">
            <el-option v-for="d in devices" :key="d.deviceId" :label="d.label || `摄像头 ${d.idx}`" :value="d.deviceId" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="mode === 'camera'">
          <el-button v-if="!camRunning" type="primary" :icon="VideoPlay" :disabled="!modelId" @click="camStart">开始</el-button>
          <el-button v-else type="danger" :icon="Refresh" @click="camStop">停止</el-button>
        </el-form-item>
      </el-form>
      <el-alert v-if="!modelOptions.length" type="warning" :closable="false"
                title="暂无可用模型：请到「模型管理」拉取 YOLO-pose / RTMO / RTMPose 权重并启用。" />
      <el-alert type="info" :closable="false" class="tip-alert"
                title="四个阈值在「检测告警」页的「跌倒检测告警」规则中配置；该规则需先启用，本页才会判定与记事件。" />
      <el-alert v-if="mode === 'video'" type="warning" :closable="false" class="tip-alert"
                title="红框每帧画、事件列表稀疏：合成视频里每一帧只要判定为跌倒都会画红框（计入 fallFrames），但右侧「触发记录」受规则的连续帧确认与冷却时间（默认 60 秒）约束，只在满足条件时记一条，数量远少于红框帧数，并非漏检。开启「告警声音」后，播放结果视频并到达触发时刻时会播警告音。" />
    </el-card>

    <el-row :gutter="12">
      <el-col :span="16">
        <el-card shadow="never">
          <div v-if="mode === 'camera'" class="cam-wrap">
            <div class="cam-stage">
              <video ref="camVideo" class="cam-video" autoplay playsinline muted></video>
              <canvas ref="camCanvas" class="cam-canvas"></canvas>
              <div v-if="!camRunning" class="cam-hint">点「开始」启用摄像头，实时检测跌倒</div>
              <div v-if="camRunning" class="cam-hud">
                <el-tag type="success" effect="dark">{{ camFps }} FPS</el-tag>
                <el-tag type="warning" effect="dark">人数 {{ personCount }}</el-tag>
                <el-tag v-if="fallCount" type="danger" effect="dark">跌倒 {{ fallCount }}</el-tag>
              </div>
            </div>
          </div>

          <div v-else-if="mode === 'video'" class="pair-wrap">
            <div class="media-pair">
              <div class="media-pane">
                <div class="pane-label">原视频</div>
                <div v-if="sourceVideoUrl" class="cam-stage pane-stage">
                  <video :src="sourceVideoUrl" controls class="cam-video"></video>
                </div>
                <el-empty v-else description="选择本地视频" :image-size="56" />
              </div>
              <div class="media-pane">
                <div class="pane-label">
                  检测结果
                  <el-button v-if="videoResultUrl && !videoRunning" link type="primary" :icon="Download" @click="downloadVideoResult">下载</el-button>
                </div>
                <div v-if="videoRunning" class="progress-box">
                  <div class="progress-title">处理中… {{ processed }}/{{ total || '?' }} 帧</div>
                  <el-progress :percentage="percent" :stroke-width="18" :text-inside="true" :status="percent >= 100 ? 'success' : ''" />
                </div>
                <template v-else-if="videoResultUrl">
                  <div class="cam-stage pane-stage">
                    <video
                      ref="videoRef"
                      :src="videoResultUrl"
                      controls
                      class="cam-video"
                      @timeupdate="onResultVideoTime"
                      @seeked="onResultVideoTime"
                    ></video>
                  </div>
                  <div class="stats">
                    <el-tag type="info" effect="plain">总帧 {{ videoStats.totalFrames ?? videoStats.frames ?? '-' }}</el-tag>
                    <el-tag type="danger" effect="dark">红框帧 {{ videoStats.fallFrames ?? 0 }}</el-tag>
                    <el-tag type="warning" effect="dark">触发 {{ (videoStats.fallEvents || []).length }}</el-tag>
                  </div>
                </template>
                <el-empty v-else description="开始检测后显示标注视频" :image-size="56" />
              </div>
            </div>
          </div>

          <div v-else class="media-pair">
            <div class="media-pane">
              <div class="pane-label">原图</div>
              <div v-if="sourceImgUrl" class="cam-stage pane-stage">
                <img :src="sourceImgUrl" class="cam-video" alt="原图" />
              </div>
              <el-empty v-else description="选择图片" :image-size="56" />
            </div>
            <div class="media-pane">
              <div class="pane-label">
                检测结果
                <span v-if="lastData" class="pane-meta">{{ personCount }} 人 · 疑似跌倒 {{ fallCount }}</span>
              </div>
              <div v-if="resultReady" class="cam-stage pane-stage">
                <img ref="stillImg" :src="sourceImgUrl" class="cam-video" alt="检测结果" @load="drawStill" />
                <canvas ref="camCanvas" class="cam-canvas"></canvas>
              </div>
              <el-empty v-else description="开始检测后显示标注结果" :image-size="56" />
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="never">
          <div class="res-title">触发记录</div>
          <template v-if="mode === 'video'">
            <el-empty v-if="!(videoStats.fallEvents || []).length" description="暂无触发" :image-size="60" />
            <el-timeline v-else>
              <el-timeline-item v-for="(e, i) in videoStats.fallEvents" :key="i" :timestamp="`${e.sec.toFixed(1)} 秒`" type="danger">
                <div class="ev-title ev-clickable" @click="seekTo(e.sec)">{{ e.title }}</div>
                <div class="ev-msg">角{{ e.indicators?.trunk ?? '-' }} 速{{ e.indicators?.speed ?? '-' }} 高{{ e.indicators?.height ?? '-' }} 头{{ e.indicators?.head ?? '-' }}</div>
              </el-timeline-item>
            </el-timeline>
          </template>
          <template v-else>
            <el-empty v-if="!events.length" description="暂无触发" :image-size="60" />
            <el-timeline v-else>
              <el-timeline-item v-for="(e, i) in events" :key="i" :timestamp="e.time" type="danger">
                <div class="ev-title">{{ e.title }}</div>
                <div class="ev-msg">{{ e.message }}</div>
              </el-timeline-item>
            </el-timeline>
          </template>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { UploadFilled, VideoPlay, Refresh, Download } from '@element-plus/icons-vue'
import { modelApi, fallApi } from '../../../api/ai'

const POSE_TASKS = ['pose-estimation', 'wholebody-pose-estimation']
// COCO-17 骨架连接表（与姿态估计页一致）
const SKELETON = [
  [5, 7], [7, 9], [6, 8], [8, 10], [5, 6], [5, 11], [6, 12], [11, 12],
  [11, 13], [13, 15], [12, 14], [14, 16], [0, 1], [0, 2], [1, 3], [2, 4],
]
const KP_CONF = 0.3
// 摄像头模式与图片模式各用独立的 sourceKey：两者共享同一个 key 会导致
// assign_track_ids 把互不相干的人用 IoU 匹配成同一 trackId、站立基线用
// 上一张图的像素尺度当这张图的基线、质心速度用两次点击的墙钟间隔当 dt——
// 该间隔与真实运动完全无关，速度指标数值毫无意义（M-3）。
const SOURCE_KEY_CAMERA = 'fall-live'
const SOURCE_KEY_IMAGE = 'fall-image'

const mode = ref('image')
const modelOptions = ref([])
const modelId = ref(null)
const conf = ref(0.25)
const persist = ref(true)
/** 视频/摄像头触发跌倒事件时播放告警音（图片模式不播） */
const soundOn = ref(true)
const file = ref(null)
const running = ref(false)
const sourceImgUrl = ref('')
const resultReady = ref(false)
const personCount = ref(0)
const fallCount = ref(0)
const events = ref([])
const lastData = ref(null)

// 视频模式状态
const videoFile = ref(null)
const sourceVideoUrl = ref('')
const videoRunning = ref(false)
const processed = ref(0)
const total = ref(0)
const videoResultUrl = ref('')
const videoStats = ref({})
const videoRef = ref(null)
let videoBlobUrl = null
let sourceVideoBlobUrl = null
let pollTimer = null
const percent = computed(() => (total.value ? Math.min(100, Math.floor((processed.value / total.value) * 100)) : 0))

const devices = ref([])
const deviceId = ref('')
const camVideo = ref(null)
const camCanvas = ref(null)
const stillImg = ref(null)
const camRunning = ref(false)
const camFps = ref(0)
let camStream = null, capCanvas = null, camBusy = false
let frameCount = 0, fpsTimer = null

const modelLabel = (m) => `${m.modelName}（${m.library === 'rtmlib' ? 'rtmlib' : 'YOLO'}）`

const loadModels = async () => {
  try {
    const res = await modelApi.list({ pageNum: 1, pageSize: 100 })
    modelOptions.value = (res.data.rows || []).filter((m) => {
      if (m.status !== '0' || !POSE_TASKS.includes(m.task)) return false
      if (m.library === 'ultralytics') return !!m.filePath
      if (m.library === 'rtmlib') return m.filePath || /^(rtmo|rtmpose|dwpose)-/.test(m.modelKey || '')
      return false
    })
    if (modelOptions.value.length && !modelId.value) modelId.value = modelOptions.value[0].id
  } catch (e) {
    ElMessage.error('加载模型列表失败')
  }
}

const onPick = (uploadFile) => {
  file.value = uploadFile.raw
  resultReady.value = false
  lastData.value = null
  personCount.value = 0
  fallCount.value = 0
  if (sourceImgUrl.value) URL.revokeObjectURL(sourceImgUrl.value)
  sourceImgUrl.value = URL.createObjectURL(uploadFile.raw)
}

let fallAudioCtx = null
let alarmBusyUntil = 0
/** 结果视频播放过程中已播过告警的跌倒事件下标（回退进度后可再次触发） */
const soundedFallIdx = new Set()
let lastPlaySec = 0

/** 跌倒告警音：短促三连蜂鸣 + 语音提示「疑似跌倒」 */
const playFallAlarm = (title, { force = false } = {}) => {
  if (!soundOn.value) return
  const nowMs = Date.now()
  // 摄像头模式冷却内不重复播；视频按事件下标去重时可用 force
  if (!force && nowMs < alarmBusyUntil) return
  alarmBusyUntil = nowMs + 2500
  try {
    const AC = window.AudioContext || window.webkitAudioContext
    if (!AC) throw new Error('no AudioContext')
    if (!fallAudioCtx) fallAudioCtx = new AC()
    if (fallAudioCtx.state === 'suspended') fallAudioCtx.resume()
    const t0 = fallAudioCtx.currentTime
    for (let i = 0; i < 3; i++) {
      const osc = fallAudioCtx.createOscillator()
      const gain = fallAudioCtx.createGain()
      osc.type = 'square'
      osc.frequency.value = i % 2 === 0 ? 920 : 620
      const start = t0 + i * 0.32
      gain.gain.setValueAtTime(0.0001, start)
      gain.gain.exponentialRampToValueAtTime(0.22, start + 0.02)
      gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.2)
      osc.connect(gain)
      gain.connect(fallAudioCtx.destination)
      osc.start(start)
      osc.stop(start + 0.22)
    }
  } catch (_) { /* 自动播放策略等失败时静默 */ }
  try {
    if (window.speechSynthesis) {
      window.speechSynthesis.cancel()
      const u = new SpeechSynthesisUtterance(title || '疑似跌倒，请立即查看')
      u.lang = 'zh-CN'
      u.rate = 1.05
      window.speechSynthesis.speak(u)
    }
  } catch (_) { /* 忽略 */ }
}

/** 播放结果视频时：到达跌倒触发时刻（frame/sec）开始告警 */
const onResultVideoTime = () => {
  const v = videoRef.value
  if (!v || mode.value !== 'video') return
  const t = Number(v.currentTime) || 0
  const evs = videoStats.value.fallEvents || []
  if (!evs.length) {
    lastPlaySec = t
    return
  }
  // 进度回退：清除该时刻之后事件的“已播”标记，便于重播时再次告警
  if (t + 0.08 < lastPlaySec) {
    for (let i = 0; i < evs.length; i++) {
      if (Number(evs[i].sec) > t + 0.05) soundedFallIdx.delete(i)
    }
  }
  const prev = lastPlaySec
  lastPlaySec = t
  for (let i = 0; i < evs.length; i++) {
    if (soundedFallIdx.has(i)) continue
    const sec = Number(evs[i].sec)
    if (!Number.isFinite(sec)) continue
    // 正向越过跌倒触发时刻才告警（时间线点击会先把 lastPlaySec 调到略早于目标点）
    if (!(prev < sec && t >= sec)) continue
    // 大跨度快进越过时只记已过、不连响
    if (t - sec > 1.2) {
      soundedFallIdx.add(i)
      continue
    }
    soundedFallIdx.add(i)
    const frameHint = evs[i].frame != null ? `第 ${evs[i].frame} 帧` : `${sec.toFixed(1)} 秒`
    playFallAlarm(evs[i].title || `疑似跌倒，${frameHint}`, { force: true })
  }
}

const resetVideoAlarmCues = () => {
  soundedFallIdx.clear()
  lastPlaySec = 0
}

const applyData = (d) => {
  lastData.value = d
  personCount.value = d.count || 0
  fallCount.value = (d.detections || []).filter((x) => x.className === 'fall').length
  const triggered = d.triggered || []
  for (const t of triggered) {
    events.value.unshift({ time: new Date().toLocaleTimeString(), title: t.title, message: t.message })
  }
  if (events.value.length > 50) events.value.length = 50
  // 仅摄像头实时触发播报；图片模式不播声音
  if (mode.value === 'camera' && triggered.length) {
    playFallAlarm(triggered[0].title || triggered[0].message)
  }
}

const buildForm = (blob, name) => {
  const fd = new FormData()
  fd.append('file', blob, name)
  fd.append('modelId', modelId.value)
  fd.append('conf', conf.value)
  fd.append('sourceKey', mode.value === 'camera' ? SOURCE_KEY_CAMERA : SOURCE_KEY_IMAGE)
  fd.append('sourceType', mode.value === 'camera' ? 'camera' : 'image')
  fd.append('persist', persist.value ? '1' : '0')
  fd.append('draw', '0')
  return fd
}

const runImage = async () => {
  running.value = true
  resultReady.value = false
  try {
    // 图片模式每次检测前先重置该 sourceKey 的连续帧/冷却/跟踪状态：图片模式面向
    // 互不相干的独立照片，不应共享跨帧 trackId、站立基线与质心速度状态（M-3）。
    // 副作用：每次检测都是「无上一帧」的冷启动，质心速度指标恒不可用。
    await fallApi.resetRuntime({ sourceKey: SOURCE_KEY_IMAGE })
    const res = await fallApi.detect(buildForm(file.value, file.value.name))
    applyData(res.data)
    resultReady.value = true
    // nextTick 后 canvas 才挂载；@load 也会触发，这里再补一次
    requestAnimationFrame(() => drawStill())
  } catch (e) {
    ElMessage.error(e.response?.data?.message || '跌倒检测失败')
  } finally {
    running.value = false
  }
}

const clearSourceVideo = () => {
  if (sourceVideoBlobUrl) {
    URL.revokeObjectURL(sourceVideoBlobUrl)
    sourceVideoBlobUrl = null
  }
  sourceVideoUrl.value = ''
}

const onPickVideo = (uploadFile) => {
  videoFile.value = uploadFile.raw
  clearVideoResult()
  videoStats.value = {}
  clearSourceVideo()
  sourceVideoBlobUrl = URL.createObjectURL(uploadFile.raw)
  sourceVideoUrl.value = sourceVideoBlobUrl
}

const clearVideoResult = () => {
  if (videoBlobUrl) { URL.revokeObjectURL(videoBlobUrl); videoBlobUrl = null }
  videoResultUrl.value = ''
  resetVideoAlarmCues()
}

const runVideo = async () => {
  videoRunning.value = true
  processed.value = 0
  total.value = 0
  clearVideoResult()
  videoStats.value = {}
  try {
    const fd = new FormData()
    fd.append('file', videoFile.value)
    fd.append('modelId', modelId.value)
    fd.append('conf', conf.value)
    const res = await fallApi.detectVideo(fd)
    await pollVideo(res.data.jobId)
  } catch (e) {
    ElMessage.error(e.response?.data?.message || '跌倒视频检测失败')
    videoRunning.value = false
  }
}

// 轮询统一 HTTP 200：业务失败靠 status === 'error' 判断，不走 catch 分支
const pollVideo = (jobId) => new Promise((resolve) => {
  pollTimer = setInterval(async () => {
    try {
      const res = await fallApi.videoProgress(jobId)
      const d = res.data
      processed.value = d.processed
      total.value = d.total
      if (d.status === 'error') {
        clearInterval(pollTimer); pollTimer = null
        ElMessage.error(d.error || '跌倒视频检测失败')
        videoRunning.value = false
        resolve()
        return
      }
      if (d.status === 'done') {
        clearInterval(pollTimer); pollTimer = null
        videoStats.value = d.stats || {}
        resetVideoAlarmCues()
        const blob = await fallApi.outputVideo(d.stats.output)
        videoBlobUrl = URL.createObjectURL(blob)
        videoResultUrl.value = videoBlobUrl
        videoRunning.value = false
        resolve()
      }
    } catch (e) {
      clearInterval(pollTimer); pollTimer = null
      ElMessage.error(e?.message || '跌倒视频检测失败')
      videoRunning.value = false
      resolve()
    }
  }, 1000)
})

const downloadVideoResult = () => {
  const a = document.createElement('a')
  a.href = videoResultUrl.value
  a.download = videoStats.value.output || `fall_${Date.now()}.mp4`
  a.click()
}

const seekTo = (sec) => {
  const v = videoRef.value
  if (!v) return
  // 允许再次触发该时刻告警：清除该点及之后的已播标记
  const t = Number(sec) || 0
  const evs = videoStats.value.fallEvents || []
  for (let i = 0; i < evs.length; i++) {
    if (Number(evs[i].sec) >= t - 0.05) soundedFallIdx.delete(i)
  }
  lastPlaySec = Math.max(0, t - 0.05)
  v.currentTime = t
  v.play?.().catch(() => {})
}

const drawOverlay = (ctx, w, h) => {
  const d = lastData.value
  if (!d) return
  ctx.lineWidth = 2
  ctx.strokeStyle = '#00e5ff'
  for (const p of d.persons || []) {
    const kp = p.keypoints || []
    for (const [a, b] of SKELETON) {
      const pa = kp[a], pb = kp[b]
      if (!pa || !pb || pa[2] < KP_CONF || pb[2] < KP_CONF) continue
      ctx.beginPath(); ctx.moveTo(pa[0], pa[1]); ctx.lineTo(pb[0], pb[1]); ctx.stroke()
    }
  }
  for (const box of d.detections || []) {
    if (box.className !== 'fall') continue
    const [x1, y1, x2, y2] = box.bbox
    ctx.strokeStyle = '#ff2d2d'
    ctx.lineWidth = 3
    ctx.strokeRect(x1, y1, x2 - x1, y2 - y1)
    const ind = box.indicators || {}
    const lines = [
      `跌倒 ${(box.confidence * 100).toFixed(0)}%`,
      `角${ind.trunk ?? '-'} 速${ind.speed ?? '-'}`,
      `高${ind.height ?? '-'} 头${ind.head ?? '-'}`,
    ]
    ctx.font = '13px sans-serif'
    ctx.fillStyle = 'rgba(207,19,34,0.8)'
    ctx.fillRect(x1, Math.max(0, y1 - 52), 150, 50)
    ctx.fillStyle = '#fff'
    lines.forEach((ln, i) => ctx.fillText(ln, x1 + 5, Math.max(12, y1 - 38 + i * 16)))
  }
  if (d.overlay) {
    ctx.fillStyle = 'rgba(207,19,34,0.35)'
    ctx.fillRect(w * 0.14, h * 0.32, w * 0.72, h * 0.36)
    ctx.fillStyle = '#fff'
    ctx.font = `bold ${Math.round(w * 0.05)}px sans-serif`
    ctx.textAlign = 'center'
    ctx.fillText((d.overlay.titleLines || ['ALERT'])[0], w / 2, h * 0.5)
    ctx.textAlign = 'left'
  }
}

const drawStill = () => {
  const cv = camCanvas.value
  if (!cv || !lastData.value) return
  cv.width = lastData.value.width
  cv.height = lastData.value.height
  const ctx = cv.getContext('2d')
  ctx.clearRect(0, 0, cv.width, cv.height)
  drawOverlay(ctx, cv.width, cv.height)
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
  fpsTimer = setInterval(() => { camFps.value = frameCount; frameCount = 0 }, 1000)
  camLoop()
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
      const res = await fallApi.detect(buildForm(blob, 'frame.jpg'))
      applyData(res.data)
      const cv = camCanvas.value, c2 = cv.getContext('2d')
      c2.clearRect(0, 0, cv.width, cv.height)
      drawOverlay(c2, cv.width, cv.height)
      frameCount++
    } catch (e) { /* 单帧失败忽略 */ } finally {
      camBusy = false
      if (camRunning.value) requestAnimationFrame(camLoop)
    }
  }, 'image/jpeg', 0.6)
}

const camStop = async () => {
  camRunning.value = false
  if (fpsTimer) { clearInterval(fpsTimer); fpsTimer = null }
  if (camStream) { camStream.getTracks().forEach((t) => t.stop()); camStream = null }
  try { await fallApi.resetRuntime({ sourceKey: SOURCE_KEY_CAMERA }) } catch (e) { /* 忽略 */ }
}

const clearAll = () => {
  camStop()
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
  file.value = null
  if (sourceImgUrl.value) URL.revokeObjectURL(sourceImgUrl.value)
  sourceImgUrl.value = ''
  resultReady.value = false
  personCount.value = 0
  fallCount.value = 0
  lastData.value = null
  events.value = []
  videoFile.value = null
  videoRunning.value = false
  processed.value = 0
  total.value = 0
  videoStats.value = {}
  clearSourceVideo()
  clearVideoResult()
}

onMounted(() => {
  loadModels()
  enumCams()
})
onBeforeUnmount(() => {
  camStop()
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
  clearSourceVideo()
  clearVideoResult()
  if (sourceImgUrl.value) URL.revokeObjectURL(sourceImgUrl.value)
  try { window.speechSynthesis?.cancel() } catch (_) { /* 忽略 */ }
  if (fallAudioCtx) {
    try { fallAudioCtx.close() } catch (_) { /* 忽略 */ }
    fallAudioCtx = null
  }
})
</script>

<style scoped>
.cfg-card { margin-bottom: 12px; }
.tip-alert { margin-top: 8px; }
.cam-wrap { display: flex; justify-content: center; }
.cam-stage { position: relative; display: inline-block; max-width: 100%; }
.cam-video { display: block; max-width: 100%; max-height: 420px; }
.cam-canvas { position: absolute; left: 0; top: 0; width: 100%; height: 100%; }
.cam-hint { position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%); color: #909399; }
.cam-hud { position: absolute; left: 8px; top: 8px; display: flex; gap: 6px; }
.res-title { font-weight: 600; margin-bottom: 8px; display: flex; align-items: center; gap: 10px; }
.ev-title { font-weight: 600; color: #cf1322; }
.ev-clickable { cursor: pointer; text-decoration: underline dotted; }
.ev-msg { font-size: 12px; color: #606266; }
.progress-box { padding: 22px 4px; }
.progress-title { font-weight: 600; color: #3a4a63; margin-bottom: 12px; }
.stats { display: flex; gap: 8px; margin-top: 10px; flex-wrap: wrap; }
.pair-wrap { width: 100%; }
.media-pair {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  width: 100%;
}
.media-pane {
  min-width: 0;
  background: #fafbfc;
  border: 1px solid #eef0f4;
  border-radius: 8px;
  padding: 10px;
}
.pane-label {
  font-weight: 600;
  color: #3a4a63;
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 24px;
}
.pane-meta { font-weight: 400; font-size: 12px; color: #909399; }
.pane-stage { width: 100%; display: flex; justify-content: center; }
@media (max-width: 900px) {
  .media-pair { grid-template-columns: 1fr; }
}
</style>
