<template>
  <div class="mtmc-page">
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="跨镜 MTMC（McByte++ 解耦）：检测看到目标 → Kalman/IoU/ByteTrack 短时跟踪 → 粘性续 Global；仅新生轨迹才用 OSNet/外观长时复活；CMC 可选；Mask 钩子默认关"
      class="mb"
    />

    <el-tabs v-model="tab" type="border-card">
      <el-tab-pane label="会话控制" name="session">
        <el-form :inline="true" label-width="100px" class="cfg">
          <el-form-item label="摄像头">
            <el-select v-model="form.cameraIds" multiple filterable collapse-tags style="width: 320px" placeholder="多选">
              <el-option v-for="c in cameras" :key="c.id" :label="`${c.name} (#${c.id})`" :value="c.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="人员">
            <el-switch v-model="form.enablePerson" />
          </el-form-item>
          <el-form-item label="车辆">
            <el-switch v-model="form.enableVehicle" />
          </el-form-item>
          <el-form-item label="采样 FPS">
            <el-input-number v-model="form.sampleFps" :min="0.5" :max="8" :step="0.5" />
          </el-form-item>
          <el-form-item label="外观阈值">
            <el-input-number v-model="form.appearThresh" :min="0.2" :max="0.9" :step="0.01" />
          </el-form-item>
          <el-form-item label="时间窗(s)">
            <el-input-number v-model="form.timeWindowSec" :min="10" :max="300" :step="5" />
          </el-form-item>
          <el-form-item label="局部跟踪">
            <el-select v-model="form.localTrackBackend" style="width: 180px">
              <el-option label="ByteTrack（推荐）" value="bytetrack" />
              <el-option label="BoT-SORT（可CMC）" value="botsort" />
              <el-option label="IoU（轻量）" value="iou" />
            </el-select>
          </el-form-item>
          <el-form-item label="CMC">
            <el-switch v-model="form.enableCmc" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="busy" v-permission="'ai:mtmc:edit'" @click="onStart">启动跨镜</el-button>
            <el-button type="danger" :disabled="!sessionId" v-permission="'ai:mtmc:edit'" @click="onStop">停止</el-button>
            <el-button @click="refreshSession">刷新状态</el-button>
            <el-button type="success" :disabled="!sessionId" @click="goWall">打开监控墙叠加</el-button>
          </el-form-item>
        </el-form>

        <el-descriptions v-if="session" :column="3" border size="small" class="mb">
          <el-descriptions-item label="会话">{{ session.sessionId }}</el-descriptions-item>
          <el-descriptions-item label="运行">{{ session.running ? '是' : '否' }}</el-descriptions-item>
          <el-descriptions-item label="摄像头">{{ (session.cameraIds || []).join(', ') }}</el-descriptions-item>
          <el-descriptions-item label="帧数">{{ session.stats?.frames }}</el-descriptions-item>
          <el-descriptions-item label="人员命中">{{ session.stats?.persons }}</el-descriptions-item>
          <el-descriptions-item label="车辆命中">{{ session.stats?.vehicles }}</el-descriptions-item>
          <el-descriptions-item label="局部跟踪">{{ session.localTrackBackend || '-' }}</el-descriptions-item>
          <el-descriptions-item label="CMC">{{ session.enableCmc ? '开' : '关' }}</el-descriptions-item>
          <el-descriptions-item label="McByte++解耦">{{ session.mcbyteDecouple === false ? '关' : '开' }}</el-descriptions-item>
        </el-descriptions>

        <div class="grid-preview" v-if="session?.running">
          <div v-for="cid in (session?.cameraIds || [])" :key="cid" class="cell">
            <div class="cell-h">Cam #{{ cid }}</div>
            <img :src="overlaySrc(cid)" class="cell-v" @error="bustOverlay(cid)" />
          </div>
        </div>

        <h4>全局身份（在线）</h4>
        <el-table :data="session?.globals || []" size="small" border stripe max-height="280">
          <el-table-column prop="globalId" label="Global ID" min-width="140" />
          <el-table-column prop="objectType" label="类型" width="80" />
          <el-table-column prop="cameraId" label="当前相机" width="90" />
          <el-table-column prop="displayName" label="人员" width="100" />
          <el-table-column prop="plate" label="车牌" width="110" />
          <el-table-column prop="identityKey" label="车辆身份键" min-width="160" show-overflow-tooltip />
          <el-table-column prop="hitCount" label="命中" width="70" />
          <el-table-column label="轨迹" width="80">
            <template #default="{ row }">
              <el-button link type="primary" @click="showTraj(row.globalId)">查看</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="事件 / 过车" name="events">
        <div class="tab-toolbar">
          <el-input v-model="eventQ.globalId" clearable placeholder="globalId" style="width: 160px" />
          <el-select v-model="eventQ.objectType" clearable placeholder="类型" style="width: 110px">
            <el-option label="人员" value="person" />
            <el-option label="车辆" value="vehicle" />
          </el-select>
          <el-button @click="loadEvents">刷新事件</el-button>
          <el-input v-model="passQ.plate" clearable placeholder="车牌" style="width: 140px; margin-left: 12px" />
          <el-button @click="loadPasses">刷新过车</el-button>
        </div>
        <el-table :data="events" size="small" border stripe class="mb" max-height="300">
          <el-table-column prop="eventTime" label="时间" width="170" />
          <el-table-column prop="cameraId" label="相机" width="70" />
          <el-table-column prop="objectType" label="类型" width="70" />
          <el-table-column prop="globalId" label="Global ID" min-width="120" />
          <el-table-column prop="displayName" label="人员" width="90" />
          <el-table-column prop="plate" label="车牌" width="100" />
          <el-table-column prop="speedKmh" label="速度" width="70" />
          <el-table-column prop="score" label="分" width="70" />
        </el-table>
        <el-table :data="passes" size="small" border stripe max-height="260">
          <el-table-column prop="passTime" label="过车时间" width="170" />
          <el-table-column prop="cameraId" label="相机" width="70" />
          <el-table-column prop="globalId" label="Global ID" min-width="120" />
          <el-table-column prop="plate" label="车牌" width="100" />
          <el-table-column prop="identityKey" label="身份键" min-width="160" show-overflow-tooltip />
          <el-table-column prop="fuseScore" label="融合分" width="80" />
          <el-table-column prop="speedKmh" label="速度" width="70" />
          <el-table-column prop="congestion" label="拥堵" width="90" />
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="相机拓扑" name="topo">
        <el-form :inline="true" class="mb">
          <el-form-item label="From">
            <el-select v-model="topoForm.fromCameraId" style="width: 180px">
              <el-option v-for="c in cameras" :key="c.id" :label="c.name" :value="c.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="To">
            <el-select v-model="topoForm.toCameraId" style="width: 180px">
              <el-option v-for="c in cameras" :key="'t'+c.id" :label="c.name" :value="c.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="最短(s)">
            <el-input-number v-model="topoForm.minTransitSec" :min="0" :max="600" />
          </el-form-item>
          <el-form-item label="最长(s)">
            <el-input-number v-model="topoForm.maxTransitSec" :min="1" :max="600" />
          </el-form-item>
          <el-button type="primary" v-permission="'ai:mtmc:edit'" @click="addTopo">添加边</el-button>
        </el-form>
        <el-table :data="topology" size="small" border stripe>
          <el-table-column prop="id" label="ID" width="60" />
          <el-table-column prop="fromCameraId" label="From" width="90" />
          <el-table-column prop="toCameraId" label="To" width="90" />
          <el-table-column prop="minTransitSec" label="最短秒" width="90" />
          <el-table-column prop="maxTransitSec" label="最长秒" width="90" />
          <el-table-column prop="remark" label="备注" />
          <el-table-column label="操作" width="90">
            <template #default="{ row }">
              <el-button link type="danger" v-permission="'ai:mtmc:edit'" @click="delTopo(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <el-drawer v-model="trajOpen" title="跨镜轨迹" size="40%">
      <el-timeline>
        <el-timeline-item
          v-for="(e, i) in trajEvents"
          :key="i"
          :timestamp="e.eventTime || e.ts"
        >
          Cam {{ e.cameraId }} · {{ e.objectType }} · {{ e.displayName || e.plate || e.globalId }}
          <div class="hint">score={{ e.score }} speed={{ e.speedKmh }}</div>
        </el-timeline-item>
      </el-timeline>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { cameraApi } from '../../../api/camera'
import { mtmcApi } from '../../../api/mtmc'

const router = useRouter()
const tab = ref('session')
const busy = ref(false)
const cameras = ref([])
const sessionId = ref('')
const session = ref(null)
const topology = ref([])
const events = ref([])
const passes = ref([])
const overlayBust = reactive({})
let pollTimer = null

const form = reactive({
  cameraIds: [],
  enablePerson: true,
  enableVehicle: true,
  sampleFps: 2,
  appearThresh: 0.48,
  timeWindowSec: 90,
  localTrackBackend: 'bytetrack',
  enableCmc: false,
  mcbyteDecouple: true,
})

const topoForm = reactive({
  fromCameraId: null,
  toCameraId: null,
  minTransitSec: 0,
  maxTransitSec: 120,
})

const eventQ = reactive({ globalId: '', objectType: '' })
const passQ = reactive({ plate: '' })

const trajOpen = ref(false)
const trajEvents = ref([])

const overlaySrc = (cid) => {
  if (!sessionId.value || !session.value?.running) return ''
  return mtmcApi.overlayUrl(sessionId.value, cid, overlayBust[cid] || '')
}
const bustOverlay = (cid) => {
  if (!session.value?.running) return
  overlayBust[cid] = String(Date.now())
}

const clearSavedSession = () => {
  sessionId.value = ''
  session.value = null
  localStorage.removeItem('mtmc-session-id')
}

const loadCameras = async () => {
  const res = await cameraApi.list({ pageNum: 1, pageSize: 100, status: '0' })
  cameras.value = res.data.rows || []
}

const loadTopo = async () => {
  const res = await mtmcApi.listTopology()
  topology.value = res.data.rows || []
}

const refreshSession = async () => {
  try {
    const list = await mtmcApi.listSessions()
    const rows = list.data.rows || []
    const live = rows.find((r) => r.running)
    if (live) {
      sessionId.value = live.sessionId
      session.value = live
      localStorage.setItem('mtmc-session-id', sessionId.value)
      return
    }
  } catch (_) {
    /* 列表失败时不打断页面 */
  }
  if (sessionId.value) {
    try {
      const alive = await mtmcApi.sessionAlive(sessionId.value)
      if (alive.data?.active) {
        const res = await mtmcApi.getSession(sessionId.value)
        session.value = res.data
        return
      }
    } catch (_) {
      /* ignore stale id */
    }
  }
  clearSavedSession()
}

const onStart = async () => {
  if (!form.cameraIds.length) {
    ElMessage.warning('请选择至少一路摄像头')
    return
  }
  busy.value = true
  try {
    if (sessionId.value) {
      try { await mtmcApi.stopSession(sessionId.value) } catch (_) { /* ignore */ }
    }
    const res = await mtmcApi.startSession({ ...form })
    sessionId.value = res.data.sessionId
    session.value = res.data
    localStorage.setItem('mtmc-session-id', sessionId.value)
    ElMessage.success('跨镜会话已启动')
  } finally {
    busy.value = false
  }
}

const onStop = async () => {
  if (!sessionId.value) return
  try {
    await mtmcApi.stopSession(sessionId.value)
  } catch (_) {
    /* 会话已失效也视为停止 */
  }
  clearSavedSession()
  ElMessage.success('已停止')
}

const goWall = () => {
  localStorage.setItem('mtmc-session-id', sessionId.value)
  router.push({ path: '/camera/wall', query: { mtmc: sessionId.value, ai: '1' } })
}

const addTopo = async () => {
  if (!topoForm.fromCameraId || !topoForm.toCameraId) return
  await mtmcApi.addTopology({ ...topoForm })
  ElMessage.success('已添加')
  await loadTopo()
}

const delTopo = async (row) => {
  await mtmcApi.removeTopology(row.id)
  await loadTopo()
}

const loadEvents = async () => {
  const res = await mtmcApi.listEvents({
    sessionId: sessionId.value || undefined,
    globalId: eventQ.globalId || undefined,
    objectType: eventQ.objectType || undefined,
    pageNum: 1,
    pageSize: 80,
  })
  events.value = res.data.rows || []
}

const loadPasses = async () => {
  const res = await mtmcApi.listPasses({
    sessionId: sessionId.value || undefined,
    plate: passQ.plate || undefined,
    pageNum: 1,
    pageSize: 80,
  })
  passes.value = res.data.rows || []
}

const showTraj = async (gid) => {
  const res = await mtmcApi.trajectory(gid)
  const db = res.data.dbEvents || []
  const live = res.data.liveEvents || []
  trajEvents.value = [...db, ...live]
  trajOpen.value = true
}

onMounted(async () => {
  await loadCameras()
  await loadTopo()
  form.cameraIds = []
  await refreshSession()
  pollTimer = setInterval(refreshSession, 3000)
})

onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<style scoped>
.mtmc-page { padding: 4px; }
.mb { margin-bottom: 12px; }
.cfg { margin-bottom: 8px; }
.tab-toolbar { display: flex; gap: 8px; align-items: center; margin-bottom: 10px; flex-wrap: wrap; }
.grid-preview {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 10px;
  margin: 12px 0;
}
.cell {
  background: #0b1220;
  border-radius: 6px;
  overflow: hidden;
  border: 1px solid #1e2a44;
}
.cell-h { color: #cfe0ff; font-size: 12px; padding: 4px 8px; background: #152238; }
.cell-v { width: 100%; display: block; min-height: 160px; object-fit: contain; background: #060c18; }
.hint { color: #8899aa; font-size: 12px; }
</style>
