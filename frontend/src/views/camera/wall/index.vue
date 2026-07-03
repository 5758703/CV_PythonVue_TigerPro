<template>
  <div ref="wallRef" class="wall">
    <div class="bar">
      <span class="title">实时监控大屏</span>
      <el-radio-group v-model="layout" size="small" @change="onLayoutChange">
        <el-radio-button :value="1">1 屏</el-radio-button>
        <el-radio-button :value="4">4 屏</el-radio-button>
        <el-radio-button :value="6">6 屏</el-radio-button>
        <el-radio-button :value="9">9 屏</el-radio-button>
        <el-radio-button :value="16">16 屏</el-radio-button>
      </el-radio-group>
      <div class="bar-right">
        <el-button size="small" :icon="Refresh" @click="loadCameras">刷新列表</el-button>
        <el-button size="small" type="primary" :icon="FullScreen" @click="toggleFull">{{ isFull ? '退出全屏' : '全屏大屏' }}</el-button>
      </div>
    </div>

    <!-- 单屏放大 -->
    <div v-if="singleIdx !== null" class="single">
      <div class="cell-head">
        <span class="cam-name">{{ cameraName(cells[singleIdx].cameraId) }}</span>
        <el-button size="small" link type="primary" @click="singleIdx = null">返回分屏</el-button>
      </div>
      <div class="cell-body">
        <img v-if="cells[singleIdx].src" :src="cells[singleIdx].src" class="cell-video" @error="cells[singleIdx].err = true" />
        <div v-if="cells[singleIdx].err" class="cell-err">流不可用</div>
      </div>
    </div>

    <!-- 分屏网格 -->
    <div v-else class="grid" :style="gridStyle">
      <div v-for="i in layout" :key="i - 1" class="cell" @dblclick="toggleSingle(i - 1)">
        <div class="cell-head">
          <el-select v-model="cells[i - 1].cameraId" size="small" placeholder="选择摄像头" clearable filterable
                     style="width: 100%" @change="onBind(i - 1)">
            <el-option v-for="c in cameras" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </div>
        <div class="cell-body">
          <img v-if="cells[i - 1].src" :src="cells[i - 1].src" class="cell-video" @error="cells[i - 1].err = true" />
          <div v-else class="cell-empty">
            <el-icon :size="28"><VideoCamera /></el-icon><span>未绑定（双击放大）</span>
          </div>
          <div v-if="cells[i - 1].err" class="cell-err">流不可用</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, FullScreen, VideoCamera } from '@element-plus/icons-vue'

import { cameraApi } from '../../../api/camera'

const MAX = 16
const COLS = { 1: 1, 4: 2, 6: 3, 9: 3, 16: 4 }
const LS_KEY = 'camera-wall'

const wallRef = ref(null)
const layout = ref(4)
const isFull = ref(false)
const singleIdx = ref(null)
const cameras = ref([])
// 固定 16 格，按索引持久化绑定；src 为空表示不取流
const cells = reactive(Array.from({ length: MAX }, () => ({ cameraId: null, src: '', err: false })))

const gridStyle = computed(() => ({ gridTemplateColumns: `repeat(${COLS[layout.value]}, 1fr)` }))

const cameraName = (id) => cameras.value.find((c) => c.id === id)?.name || '未绑定'

const loadCameras = async () => {
  // 仅列启用摄像头（status=0）
  const res = await cameraApi.list({ pageNum: 1, pageSize: 100, status: '0' })
  cameras.value = res.data.rows || []
}

const setSrc = (i) => {
  const cell = cells[i]
  cell.err = false
  cell.src = cell.cameraId ? cameraApi.streamUrl(cell.cameraId) : ''
}

const onBind = (i) => { setSrc(i); persist() }

const onLayoutChange = () => {
  // 收缩布局时，断开超出范围格子的流（释放后端 ffmpeg）
  for (let i = layout.value; i < MAX; i++) cells[i].src = ''
  // 进入可见范围的已绑定格子恢复取流
  for (let i = 0; i < layout.value; i++) if (cells[i].cameraId && !cells[i].src) setSrc(i)
  persist()
}

const toggleSingle = (i) => {
  if (!cells[i].cameraId) { ElMessage.info('请先为该格选择摄像头'); return }
  singleIdx.value = singleIdx.value === i ? null : i
}

const toggleFull = async () => {
  try {
    if (!isFull.value) { await wallRef.value.requestFullscreen() }
    else { await document.exitFullscreen() }
  } catch (e) { ElMessage.warning('浏览器不支持全屏或被拒绝') }
}
const onFsChange = () => { isFull.value = !!document.fullscreenElement }

const persist = () => {
  const data = { layout: layout.value, binds: cells.map((c) => c.cameraId) }
  localStorage.setItem(LS_KEY, JSON.stringify(data))
}
const restore = () => {
  try {
    const data = JSON.parse(localStorage.getItem(LS_KEY) || '{}')
    if (data.layout && COLS[data.layout]) layout.value = data.layout
    if (Array.isArray(data.binds)) data.binds.forEach((id, i) => { if (i < MAX) cells[i].cameraId = id || null })
  } catch (e) { /* ignore */ }
}

const stopAll = () => { for (const c of cells) c.src = '' }

onMounted(async () => {
  restore()
  await loadCameras()
  for (let i = 0; i < layout.value; i++) if (cells[i].cameraId) setSrc(i)
  document.addEventListener('fullscreenchange', onFsChange)
})
onBeforeUnmount(() => {
  stopAll()
  document.removeEventListener('fullscreenchange', onFsChange)
})
</script>

<style scoped>
.wall { display: flex; flex-direction: column; height: calc(100vh - 120px); background: #0a1020; border-radius: 8px; padding: 10px; }
.wall:fullscreen { height: 100vh; border-radius: 0; }
.bar { display: flex; align-items: center; gap: 16px; padding: 4px 8px 10px; color: #eaf2ff; }
.title { font-weight: 700; font-size: 16px; letter-spacing: 1px; }
.bar-right { margin-left: auto; display: flex; gap: 8px; }
.grid { flex: 1; display: grid; gap: 8px; min-height: 0; }
.single { flex: 1; display: flex; flex-direction: column; min-height: 0; }
.cell, .single { background: #111c34; border: 1px solid rgba(120,170,255,0.15); border-radius: 6px; overflow: hidden; display: flex; flex-direction: column; }
.cell { min-height: 0; }
.cell-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 5px 8px; background: rgba(20,40,80,0.5); }
.cam-name { color: #cfe0ff; font-size: 13px; font-weight: 600; }
.cell-body { position: relative; flex: 1; min-height: 0; display: flex; align-items: center; justify-content: center; background: #060c18; }
.cell-video { max-width: 100%; max-height: 100%; object-fit: contain; }
.cell-empty { display: flex; flex-direction: column; align-items: center; gap: 6px; color: #5a6f9c; font-size: 12px; }
.cell-err { position: absolute; bottom: 6px; left: 6px; color: #f56c6c; font-size: 12px; background: rgba(0,0,0,0.5); padding: 2px 6px; border-radius: 4px; }
</style>
