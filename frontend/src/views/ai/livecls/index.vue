<template>
  <div>
    <el-card shadow="never" class="cfg-card">
      <el-form :inline="true">
        <el-form-item label="分类模型">
          <el-select v-model="modelId" placeholder="选择模型" style="width: 320px" :disabled="running">
            <el-option
              v-for="m in modelOptions"
              :key="m.id"
              :label="`${m.modelName}（${m.library}${m.modelKey ? ' · ' + m.modelKey : ''}）`"
              :value="m.id"
            />
          </el-select>
          <el-button :disabled="running" style="margin-left: 8px" @click="loadModels">刷新</el-button>
        </el-form-item>
        <el-form-item label="精度">
          <el-radio-group v-model="precision" :disabled="running || !isDnn">
            <el-radio-button value="int8">INT8</el-radio-button>
            <el-radio-button value="fp32">FP32</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="摄像头">
          <el-select v-model="deviceId" placeholder="默认本地摄像头" style="width: 220px" :disabled="running">
            <el-option label="默认本地摄像头" value="" />
            <el-option
              v-for="d in devices"
              :key="d.deviceId"
              :label="d.label || `摄像头 ${d.idx}`"
              :value="d.deviceId"
            />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button
            v-if="!running"
            type="primary"
            :icon="VideoCamera"
            :disabled="!modelId"
            @click="start"
          >
            开始实时分类
          </el-button>
          <el-button v-else type="danger" :icon="SwitchButton" @click="stop">停止</el-button>
        </el-form-item>
      </el-form>
      <el-alert
        v-if="!modelOptions.length"
        type="warning"
        :closable="false"
        title="暂无可用分类模型：请到「模型管理」拉取 MobileNet V2（opencv-dnn）或 ViT，并保持启用。"
      />
      <el-alert
        v-else-if="isDnn"
        type="info"
        :closable="false"
        show-icon
        title="OpenCV DNN：INT8 适合实时预览；FP32 作精度对照。画面叠加 Top-3，底部显示置信度与推理耗时。"
      />
    </el-card>

    <el-card shadow="never">
      <div class="stage-wrap">
        <div class="stage">
          <video
            v-show="previewing"
            ref="videoEl"
            class="cam-video"
            autoplay
            playsinline
            muted
          ></video>
          <canvas ref="overlayEl" class="overlay"></canvas>
          <div v-if="!previewing" class="stage-hint">
            <el-icon :size="40"><VideoCamera /></el-icon>
            <span>点击「开始实时分类」启用摄像头</span>
          </div>
          <div v-if="running" class="hud">
            <el-tag type="success" effect="dark">{{ fps }} FPS</el-tag>
            <el-tag type="info" effect="dark">{{ (lastResult?.precision || precision).toUpperCase() }}</el-tag>
            <el-tag type="warning" effect="dark">{{ lastResult?.backend || '-' }}</el-tag>
          </div>
        </div>

        <div class="bottom-panel">
          <div class="panel-title">Top-3 分类 · 置信度 / 耗时</div>
          <div v-if="!lastResult?.results?.length" class="panel-empty">等待首帧推理…</div>
          <template v-else>
            <div v-for="(r, i) in lastResult.results" :key="(r.label || '') + i" class="score-row">
              <span class="rank">#{{ i + 1 }}</span>
              <span class="score-label" :title="r.labelEn || r.label">{{ r.label }}</span>
              <el-progress
                :percentage="+((r.score || 0) * 100).toFixed(1)"
                :stroke-width="14"
                class="score-bar"
              />
            </div>
            <div class="meta-row">
              <el-tag size="small" effect="plain">推理 {{ lastResult.latencyMs ?? '-' }} ms</el-tag>
              <el-tag size="small" effect="plain">精度 {{ (lastResult.precision || precision).toUpperCase() }}</el-tag>
              <el-tag size="small" effect="plain">后端 {{ lastResult.backend || '-' }}</el-tag>
              <el-tag v-if="lastResult.top" size="small" type="success" effect="plain">
                Top-1 {{ lastResult.top.label }}
              </el-tag>
            </div>
          </template>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { VideoCamera, SwitchButton } from '@element-plus/icons-vue'
import { modelApi } from '../../../api/ai'
import { loadImageClassificationModels, pickPreferredClsModel } from '../../../utils/clsModels'

const modelOptions = ref([])
const modelId = ref(null)
const precision = ref('int8')
const devices = ref([])
const deviceId = ref('')
const videoEl = ref(null)
const overlayEl = ref(null)
const previewing = ref(false)
const running = ref(false)
const fps = ref(0)
const lastResult = ref(null)

let stream = null
let capCanvas = null
let busy = false
let frameCount = 0
let fpsTimer = null
let loopTimer = null

const selectedModel = computed(() => modelOptions.value.find((m) => m.id === modelId.value))
const isDnn = computed(() => {
  const lib = (selectedModel.value?.library || '').toLowerCase()
  return lib === 'opencv-dnn' || lib === 'opencv_dnn' || lib === 'mobilenet' || /opencv|dnn|mobilenet/.test(lib)
})

const loadModels = async () => {
  try {
    modelOptions.value = await loadImageClassificationModels(modelApi)
    modelId.value = pickPreferredClsModel(modelOptions.value, modelId.value)
  } catch (_) {
    modelOptions.value = []
  }
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

const waitForVideoReady = (video, timeoutMs = 8000) =>
  new Promise((resolve, reject) => {
    if (video.videoWidth > 0 && video.readyState >= 2) {
      resolve()
      return
    }
    const t0 = Date.now()
    const timer = setInterval(() => {
      if (video.videoWidth > 0 && video.readyState >= 2) {
        clearInterval(timer)
        resolve()
      } else if (Date.now() - t0 > timeoutMs) {
        clearInterval(timer)
        reject(new Error('timeout'))
      }
    }, 100)
  })

const drawOverlay = (results) => {
  const canvas = overlayEl.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  ctx.clearRect(0, 0, canvas.width, canvas.height)
  if (!results?.length) return

  const pad = 10
  const lineH = 22
  const boxH = pad * 2 + results.length * lineH
  const boxW = Math.min(canvas.width - 16, 360)
  ctx.fillStyle = 'rgba(0, 0, 0, 0.55)'
  ctx.fillRect(8, 8, boxW, boxH)
  ctx.font = '14px sans-serif'
  results.forEach((r, i) => {
    const pct = ((r.score || 0) * 100).toFixed(1)
    const name = r.label || r.labelEn || ''
    const text = `#${i + 1} ${name}  ${pct}%`
    ctx.fillStyle = i === 0 ? '#67c23a' : '#ffffff'
    ctx.fillText(text, 8 + pad, 8 + pad + (i + 1) * lineH - 6)
  })
}

const scheduleLoop = (delayMs = 0) => {
  if (!running.value) return
  if (loopTimer) clearTimeout(loopTimer)
  loopTimer = setTimeout(() => {
    loopTimer = null
    loop()
  }, delayMs)
}

const start = async () => {
  if (!modelId.value) {
    ElMessage.warning('请选择分类模型')
    return
  }
  previewing.value = true
  await nextTick()
  try {
    const constraints = {
      video: deviceId.value
        ? { deviceId: { exact: deviceId.value }, width: { ideal: 640 }, height: { ideal: 480 } }
        : { width: { ideal: 640 }, height: { ideal: 480 } },
      audio: false,
    }
    stream = await navigator.mediaDevices.getUserMedia(constraints)
  } catch (_) {
    previewing.value = false
    ElMessage.error('无法访问摄像头，请检查设备与浏览器权限')
    return
  }
  const video = videoEl.value
  if (!video) {
    previewing.value = false
    ElMessage.error('预览组件未就绪')
    return
  }
  video.srcObject = stream
  try {
    await video.play()
  } catch (_) {
    /* autoplay */
  }
  try {
    await waitForVideoReady(video)
  } catch (_) {
    ElMessage.error('摄像头尚未就绪，请重试')
    stop()
    return
  }
  enumCams()

  const vw = video.videoWidth
  const vh = video.videoHeight
  const capW = Math.min(vw, 640)
  const capH = Math.round((vh * capW) / vw)
  capCanvas = document.createElement('canvas')
  capCanvas.width = capW
  capCanvas.height = capH
  if (overlayEl.value) {
    overlayEl.value.width = capW
    overlayEl.value.height = capH
  }

  running.value = true
  lastResult.value = null
  frameCount = 0
  fps.value = 0
  busy = false
  if (fpsTimer) clearInterval(fpsTimer)
  fpsTimer = setInterval(() => {
    fps.value = frameCount
    frameCount = 0
  }, 1000)
  scheduleLoop(0)
}

const loop = () => {
  if (!running.value) return
  if (busy) {
    scheduleLoop(60)
    return
  }
  busy = true
  const video = videoEl.value
  if (!video || !capCanvas || !video.videoWidth) {
    busy = false
    scheduleLoop(50)
    return
  }
  const capW = Math.min(video.videoWidth, 640)
  const capH = Math.round((video.videoHeight * capW) / video.videoWidth)
  if (capCanvas.width !== capW || capCanvas.height !== capH) {
    capCanvas.width = capW
    capCanvas.height = capH
    if (overlayEl.value) {
      overlayEl.value.width = capW
      overlayEl.value.height = capH
    }
  }
  const ctx = capCanvas.getContext('2d')
  try {
    ctx.drawImage(video, 0, 0, capCanvas.width, capCanvas.height)
  } catch (_) {
    busy = false
    scheduleLoop(50)
    return
  }

  capCanvas.toBlob(async (blob) => {
    if (!running.value || !blob) {
      busy = false
      if (running.value) scheduleLoop(0)
      return
    }
    try {
      const fd = new FormData()
      fd.append('file', blob, 'frame.jpg')
      fd.append('topK', 3)
      fd.append('precision', isDnn.value ? precision.value : 'fp32')
      fd.append('backend', 'auto')
      const res = await modelApi.classifyImage(modelId.value, fd)
      if (!running.value) return
      lastResult.value = res.data
      drawOverlay(res.data?.results || [])
      frameCount++
    } catch (_) {
      /* 单帧失败忽略 */
    } finally {
      busy = false
      // 略降采样，避免 HTTP 分类打满 CPU
      if (running.value) scheduleLoop(80)
    }
  }, 'image/jpeg', 0.7)
}

const stop = () => {
  running.value = false
  previewing.value = false
  if (loopTimer) {
    clearTimeout(loopTimer)
    loopTimer = null
  }
  if (fpsTimer) {
    clearInterval(fpsTimer)
    fpsTimer = null
  }
  if (stream) {
    stream.getTracks().forEach((t) => t.stop())
    stream = null
  }
  if (videoEl.value) videoEl.value.srcObject = null
  const canvas = overlayEl.value
  if (canvas) {
    const ctx = canvas.getContext('2d')
    ctx.clearRect(0, 0, canvas.width, canvas.height)
  }
  busy = false
  fps.value = 0
}

onMounted(() => {
  loadModels()
  enumCams()
})
onBeforeUnmount(stop)
</script>

<style scoped>
.cfg-card {
  margin-bottom: 12px;
}
.stage-wrap {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.stage {
  position: relative;
  width: 100%;
  max-width: 720px;
  margin: 0 auto;
  background: #1a1a1a;
  border-radius: 6px;
  overflow: hidden;
  min-height: 320px;
}
.cam-video,
.overlay {
  display: block;
  width: 100%;
  height: auto;
}
.overlay {
  position: absolute;
  left: 0;
  top: 0;
  width: 100%;
  height: 100%;
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
  color: #909399;
}
.hud {
  position: absolute;
  right: 10px;
  top: 10px;
  display: flex;
  gap: 6px;
}
.bottom-panel {
  max-width: 720px;
  margin: 0 auto;
  width: 100%;
  padding: 12px 14px;
  background: #f5f7fa;
  border-radius: 6px;
}
.panel-title {
  font-weight: 600;
  color: #3a4a63;
  margin-bottom: 10px;
}
.panel-empty {
  color: #909399;
  font-size: 13px;
}
.score-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.rank {
  width: 28px;
  color: #909399;
  font-size: 12px;
}
.score-label {
  width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  color: #3a4a63;
}
.score-bar {
  flex: 1;
}
.meta-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}
</style>
