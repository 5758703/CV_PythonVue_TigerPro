<template>
  <div ref="wallRef" class="wall">
    <div class="bar">
      <div class="bar-title">
        <span class="title">监控墙</span>
        <el-tag size="small" type="success" effect="dark">RTSP 7×24</el-tag>
        <el-tag v-if="aiOverlay && aiMode === 'mtmc'" size="small" type="warning" effect="dark">MTMC AI</el-tag>
        <el-tag v-else-if="aiOverlay && aiMode === 'pipeline'" size="small" type="danger" effect="dark">流水线 AI</el-tag>
        <span class="sub">多路共享拉流 · 断线自动重连{{ aiOverlayHint }}</span>
      </div>
      <el-radio-group v-model="layout" size="small" @change="onLayoutChange">
        <el-radio-button :value="1">1 屏</el-radio-button>
        <el-radio-button :value="4">4 屏</el-radio-button>
        <el-radio-button :value="6">6 屏</el-radio-button>
        <el-radio-button :value="9">9 屏</el-radio-button>
        <el-radio-button :value="16">16 屏</el-radio-button>
      </el-radio-group>
      <div class="bar-right">
        <el-switch v-model="aiOverlay" active-text="AI 叠加" @change="onAiToggle" />
        <el-select
          v-if="aiOverlay"
          v-model="aiMode"
          size="small"
          style="width: 120px"
          @change="onAiModeChange"
        >
          <el-option label="MTMC" value="mtmc" />
          <el-option label="流水线" value="pipeline" />
        </el-select>
        <el-input
          v-if="aiOverlay && aiMode === 'mtmc'"
          v-model="mtmcSessionId"
          size="small"
          placeholder="MTMC 会话 ID"
          style="width: 160px"
          @change="reloadAll"
        />
        <el-input
          v-if="aiOverlay && aiMode === 'pipeline'"
          v-model="pipelineRunKey"
          size="small"
          placeholder="可选 runKey（空则按摄像头）"
          style="width: 180px"
          @change="reloadAll"
        />
        <el-switch v-model="autoReconnect" active-text="自动重连" inactive-text="" />
        <el-button size="small" :icon="Refresh" @click="reloadAll">刷新列表</el-button>
        <el-button size="small" type="primary" :icon="FullScreen" @click="toggleFull">
          {{ isFull ? '退出全屏' : '全屏大屏' }}
        </el-button>
      </div>
    </div>

    <div v-if="singleIdx !== null" class="single">
      <div class="cell-head">
        <span class="cam-name">{{ cameraName(cells[singleIdx].cameraId) }}</span>
        <el-tag size="small" :type="statusType(cells[singleIdx])">{{ statusLabel(cells[singleIdx]) }}</el-tag>
        <el-button size="small" link type="primary" @click="singleIdx = null">返回分屏</el-button>
      </div>
      <div class="cell-body">
        <img
          v-if="cells[singleIdx].src"
          :src="cells[singleIdx].src"
          class="cell-video"
          @load="onLoad(singleIdx)"
          @error="onError(singleIdx)"
        />
        <div v-if="cells[singleIdx].status === 'error'" class="cell-err">流不可用，正在重连…</div>
      </div>
    </div>

    <div v-else class="grid" :style="gridStyle">
      <div v-for="i in layout" :key="i - 1" class="cell" @dblclick="toggleSingle(i - 1)">
        <div class="cell-head">
          <el-select
            v-model="cells[i - 1].cameraId"
            size="small"
            placeholder="选择摄像头"
            clearable
            filterable
            style="width: 100%"
            @change="onBind(i - 1)"
          >
            <el-option
              v-for="c in cameras"
              :key="c.id"
              :label="`${c.name}${c.sourceType === 'rtsp' ? ' [RTSP]' : ''}`"
              :value="c.id"
            />
          </el-select>
          <el-tag size="small" :type="statusType(cells[i - 1])" class="st">{{ statusLabel(cells[i - 1]) }}</el-tag>
        </div>
        <div class="cell-body">
          <img
            v-if="cells[i - 1].src"
            :src="cells[i - 1].src"
            class="cell-video"
            @load="onLoad(i - 1)"
            @error="onError(i - 1)"
          />
          <div v-else class="cell-empty">
            <el-icon :size="28"><VideoCamera /></el-icon>
            <span>未绑定（双击放大）</span>
          </div>
          <div v-if="cells[i - 1].status === 'error'" class="cell-err">流不可用</div>
          <div v-else-if="cells[i - 1].status === 'reconnect'" class="cell-warn">重连中…</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount } from 'vue'
import { onBeforeRouteLeave, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Refresh, FullScreen, VideoCamera } from '@element-plus/icons-vue'

import { cameraApi } from '../../../api/camera'
import { mtmcApi } from '../../../api/mtmc'
import { pipelineApi } from '../../../api/pipeline'

const MAX = 16
const COLS = { 1: 1, 4: 2, 6: 3, 9: 3, 16: 4 }
const LS_KEY = 'camera-wall'
const MAX_BACKOFF_MS = 30000

const route = useRoute()
const wallRef = ref(null)
const layout = ref(4)
const isFull = ref(false)
const singleIdx = ref(null)
const autoReconnect = ref(true)
const aiOverlay = ref(false)
const aiMode = ref('mtmc') // mtmc | pipeline
const mtmcSessionId = ref('')
const pipelineRunKey = ref('')
/** null=未校验, true/false=会话是否可用 */
const overlaySessionActive = ref(null)
let overlayFallbackOnce = false
const pageAlive = ref(true)
const cameras = ref([])
const cells = reactive(Array.from({ length: MAX }, () => ({
  cameraId: null,
  src: '',
  status: 'idle',
  retries: 0,
  timer: null,
})))

const gridStyle = computed(() => ({ gridTemplateColumns: `repeat(${COLS[layout.value]}, 1fr)` }))
const aiOverlayHint = computed(() => {
  if (!aiOverlay.value) return ''
  return aiMode.value === 'pipeline' ? ' · 视频分析流水线叠加' : ' · 跨镜重识别叠加'
})

const cameraName = (id) => cameras.value.find((c) => c.id === id)?.name || '未绑定'
const statusLabel = (cell) => ({
  idle: '未绑定',
  live: '直播中',
  reconnect: '重连中',
  error: '异常',
}[cell.status] || '')
const statusType = (cell) => ({
  idle: 'info',
  live: 'success',
  reconnect: 'warning',
  error: 'danger',
}[cell.status] || 'info')

const clearTimer = (i) => {
  if (cells[i].timer) {
    clearTimeout(cells[i].timer)
    cells[i].timer = null
  }
}

const useOverlayStream = () => (
  aiOverlay.value && overlaySessionActive.value === true && (
    (aiMode.value === 'mtmc' && !!mtmcSessionId.value)
    || aiMode.value === 'pipeline'
  )
)

const refreshOverlaySession = async () => {
  if (aiMode.value === 'pipeline') {
    // 按摄像头探测：只要有任一 cell 绑定摄像头即可；真正是否有流在 setSrc 时按 cam 取
    overlaySessionActive.value = true
    return true
  }
  if (!mtmcSessionId.value) {
    overlaySessionActive.value = false
    return false
  }
  try {
    const res = await mtmcApi.sessionAlive(mtmcSessionId.value)
    overlaySessionActive.value = !!res.data?.active
  } catch (_) {
    overlaySessionActive.value = false
  }
  return overlaySessionActive.value
}

const onAiModeChange = async () => {
  overlayFallbackOnce = false
  await refreshOverlaySession()
  reloadAll()
  persist()
}

const disableOverlayFallback = (msg) => {
  if (overlayFallbackOnce || !aiOverlay.value) return
  overlayFallbackOnce = true
  aiOverlay.value = false
  overlaySessionActive.value = false
  ElMessage.warning(msg)
  persist()
  for (let i = 0; i < layout.value; i++) {
    if (!cells[i].cameraId) continue
    clearTimer(i)
    cells[i].retries = 0
    setSrc(i, { force: true })
  }
}

const setSrc = (i, { force = false } = {}) => {
  if (!pageAlive.value) return
  const cell = cells[i]
  clearTimer(i)
  if (!cell.cameraId) {
    cell.src = ''
    cell.status = 'idle'
    cell.retries = 0
    return
  }
  const bust = force || cell.retries > 0 ? String(Date.now()) : ''
  if (useOverlayStream()) {
    if (aiMode.value === 'pipeline') {
      if (pipelineRunKey.value) {
        cell.src = pipelineApi.overlayUrl(pipelineRunKey.value, bust)
      } else {
        cell.src = pipelineApi.overlayByCameraUrl(cell.cameraId, bust)
      }
    } else {
      cell.src = mtmcApi.overlayUrl(mtmcSessionId.value, cell.cameraId, bust)
    }
  } else {
    cell.src = cameraApi.streamUrl(cell.cameraId, bust)
  }
  cell.status = cell.retries > 0 ? 'reconnect' : 'live'
}

const scheduleReconnect = (i) => {
  if (!pageAlive.value || !autoReconnect.value || !cells[i].cameraId) return
  clearTimer(i)
  const delay = Math.min(1000 * (2 ** Math.min(cells[i].retries, 4)), MAX_BACKOFF_MS)
  cells[i].status = 'reconnect'
  cells[i].timer = setTimeout(() => {
    if (!pageAlive.value) return
    cells[i].retries += 1
    setSrc(i, { force: true })
  }, delay)
}

const onLoad = (i) => {
  if (!pageAlive.value) return
  cells[i].status = 'live'
  cells[i].retries = 0
  clearTimer(i)
}

const onError = async (i) => {
  if (!pageAlive.value) return
  if (aiOverlay.value && mtmcSessionId.value) {
    await refreshOverlaySession()
    if (!overlaySessionActive.value) {
      disableOverlayFallback('跨镜会话未运行（可能后端已重启），已切换为普通监控流')
      return
    }
  }
  cells[i].status = 'error'
  if (autoReconnect.value) scheduleReconnect(i)
}

const onBind = (i) => {
  cells[i].retries = 0
  setSrc(i, { force: true })
  persist()
}

const onAiToggle = async () => {
  if (aiOverlay.value) {
    overlayFallbackOnce = false
    if (aiMode.value === 'pipeline') {
      if (!pipelineRunKey.value) {
        pipelineRunKey.value = localStorage.getItem('pipeline-run-key') || ''
      }
      await refreshOverlaySession()
      // 按摄像头叠加：允许无 runKey
    } else {
      if (!mtmcSessionId.value) {
        mtmcSessionId.value = localStorage.getItem('mtmc-session-id') || ''
      }
      if (!mtmcSessionId.value) {
        ElMessage.warning('请先在「跨镜重识别」页启动会话，或填写会话 ID')
        aiOverlay.value = false
        persist()
        return
      }
      await refreshOverlaySession()
      if (!overlaySessionActive.value) {
        ElMessage.warning('跨镜会话未运行，请先在「跨镜重识别」页启动会话')
        aiOverlay.value = false
        persist()
        return
      }
    }
  } else {
    overlaySessionActive.value = null
  }
  for (let i = 0; i < layout.value; i++) {
    if (cells[i].cameraId) setSrc(i, { force: true })
  }
  persist()
}

const onLayoutChange = () => {
  for (let i = layout.value; i < MAX; i++) {
    clearTimer(i)
    cells[i].src = ''
    if (!cells[i].cameraId) cells[i].status = 'idle'
  }
  for (let i = 0; i < layout.value; i++) {
    if (cells[i].cameraId && !cells[i].src) setSrc(i, { force: true })
  }
  persist()
}

const toggleSingle = (i) => {
  if (!cells[i].cameraId) {
    ElMessage.info('请先为该格选择摄像头')
    return
  }
  singleIdx.value = singleIdx.value === i ? null : i
}

const toggleFull = async () => {
  try {
    if (!isFull.value) await wallRef.value.requestFullscreen()
    else await document.exitFullscreen()
  } catch (_) {
    ElMessage.warning('浏览器不支持全屏或被拒绝')
  }
}
const onFsChange = () => { isFull.value = !!document.fullscreenElement }

const persist = () => {
  localStorage.setItem(LS_KEY, JSON.stringify({
    layout: layout.value,
    binds: cells.map((c) => c.cameraId),
    autoReconnect: autoReconnect.value,
    aiOverlay: aiOverlay.value,
    aiMode: aiMode.value,
    mtmcSessionId: mtmcSessionId.value,
    pipelineRunKey: pipelineRunKey.value,
  }))
}
const restore = () => {
  try {
    const data = JSON.parse(localStorage.getItem(LS_KEY) || '{}')
    if (data.layout && COLS[data.layout]) layout.value = data.layout
    if (typeof data.autoReconnect === 'boolean') autoReconnect.value = data.autoReconnect
    if (typeof data.aiOverlay === 'boolean') aiOverlay.value = data.aiOverlay
    if (data.aiMode === 'pipeline' || data.aiMode === 'mtmc') aiMode.value = data.aiMode
    if (data.mtmcSessionId) mtmcSessionId.value = data.mtmcSessionId
    if (data.pipelineRunKey) pipelineRunKey.value = data.pipelineRunKey
    if (Array.isArray(data.binds)) {
      data.binds.forEach((id, i) => { if (i < MAX) cells[i].cameraId = id || null })
    }
  } catch (_) { /* ignore */ }
}

const loadCameras = async () => {
  const res = await cameraApi.list({ pageNum: 1, pageSize: 100, status: '0' })
  cameras.value = res.data.rows || []
}

const reloadAll = async () => {
  await loadCameras()
  if (aiOverlay.value) {
    overlayFallbackOnce = false
    await refreshOverlaySession()
    if (aiMode.value === 'mtmc' && !overlaySessionActive.value) {
      disableOverlayFallback('跨镜会话未运行，已切换为普通监控流')
      return
    }
  }
  for (let i = 0; i < layout.value; i++) {
    if (cells[i].cameraId) setSrc(i, { force: true })
  }
  ElMessage.success('已刷新')
}

const stopAll = () => {
  pageAlive.value = false
  for (let i = 0; i < MAX; i++) {
    clearTimer(i)
    cells[i].src = ''
    cells[i].retries = 0
    cells[i].status = 'idle'
  }
}

onMounted(async () => {
  pageAlive.value = true
  overlayFallbackOnce = false
  restore()
  if (route.query.ai === 'pipeline') {
    aiMode.value = 'pipeline'
    aiOverlay.value = true
    if (route.query.runKey) pipelineRunKey.value = String(route.query.runKey)
    else if (!pipelineRunKey.value) pipelineRunKey.value = localStorage.getItem('pipeline-run-key') || ''
    if (route.query.cameraId && !cells[0].cameraId) {
      cells[0].cameraId = Number(route.query.cameraId) || null
    }
  } else if (route.query.mtmc) {
    mtmcSessionId.value = String(route.query.mtmc)
    aiMode.value = 'mtmc'
    aiOverlay.value = true
  } else if (route.query.ai === '1') {
    aiOverlay.value = true
    if (!mtmcSessionId.value) mtmcSessionId.value = localStorage.getItem('mtmc-session-id') || ''
  }
  if (aiOverlay.value) {
    await refreshOverlaySession()
    if (aiMode.value === 'mtmc' && !overlaySessionActive.value) {
      disableOverlayFallback('跨镜会话未运行（可能后端已重启），已切换为普通监控流')
    }
  }
  await loadCameras()
  for (let i = 0; i < layout.value; i++) {
    if (cells[i].cameraId) setSrc(i, { force: true })
  }
  document.addEventListener('fullscreenchange', onFsChange)
})
onBeforeRouteLeave(() => {
  stopAll()
  persist()
})
onBeforeUnmount(() => {
  stopAll()
  document.removeEventListener('fullscreenchange', onFsChange)
  persist()
})
</script>

<style scoped>
.wall {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 120px);
  background: #0a1020;
  border-radius: 8px;
  padding: 10px;
}
.wall:fullscreen { height: 100vh; border-radius: 0; }
.bar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 4px 8px 10px;
  color: #eaf2ff;
  flex-wrap: wrap;
}
.bar-title { display: flex; align-items: center; gap: 8px; }
.title { font-weight: 700; font-size: 16px; letter-spacing: 1px; }
.sub { font-size: 12px; color: #8aa0c8; }
.bar-right { margin-left: auto; display: flex; align-items: center; gap: 10px; }
.grid { flex: 1; display: grid; gap: 8px; min-height: 0; }
.single { flex: 1; display: flex; flex-direction: column; min-height: 0; }
.cell, .single {
  background: #111c34;
  border: 1px solid rgba(120, 170, 255, 0.15);
  border-radius: 6px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.cell { min-height: 0; }
.cell-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 8px;
  background: rgba(20, 40, 80, 0.5);
}
.cam-name { color: #cfe0ff; font-size: 13px; font-weight: 600; }
.st { flex-shrink: 0; }
.cell-body {
  position: relative;
  flex: 1;
  min-height: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #060c18;
}
.cell-video { max-width: 100%; max-height: 100%; object-fit: contain; }
.cell-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  color: #5a6f9c;
  font-size: 12px;
}
.cell-err, .cell-warn {
  position: absolute;
  bottom: 6px;
  left: 6px;
  font-size: 12px;
  background: rgba(0, 0, 0, 0.55);
  padding: 2px 6px;
  border-radius: 4px;
}
.cell-err { color: #f56c6c; }
.cell-warn { color: #e6a23c; }
</style>
