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

      <el-tab-pane label="操作说明" name="guide">
        <div class="guide-wrap">
          <el-alert
            type="info"
            :closable="false"
            show-icon
            title="跨镜 MTMC 用于多路摄像头下给人员/车辆分配稳定全局 ID，并可与监控墙 AI 叠加联动。建议首次使用先通读本页，再按步骤操作。"
            class="mb"
          />

          <h3 class="guide-h3">一、推荐使用流程</h3>
          <el-steps :active="6" align-center finish-status="success" class="guide-steps mb">
            <el-step title="准备摄像头" description="摄像头管理录入 RTSP，流可预览" />
            <el-step title="准备权重" description="检测 + ReID / 车牌模型已拉取" />
            <el-step title="配置拓扑" description="相机拓扑 Tab 添加通行边" />
            <el-step title="启动会话" description="会话控制 Tab 选路并启动" />
            <el-step title="查看全局 ID" description="预览与全局身份表" />
            <el-step title="监控墙叠加" description="可选：大屏 AI 叠加" />
          </el-steps>

          <h3 class="guide-h3">二、会话控制 · 参数说明</h3>
          <el-table :data="paramGuide" size="small" border stripe class="mb">
            <el-table-column prop="name" label="参数" width="120" />
            <el-table-column prop="desc" label="说明" min-width="280" />
            <el-table-column prop="suggest" label="建议值" width="160" />
          </el-table>

          <h3 class="guide-h3">三、相机拓扑</h3>
          <p class="guide-p">
            在「相机拓扑」Tab 为相邻摄像头添加有向边 <code>From → To</code>，并设置最短/最长通行秒数。
            跨镜关联时，若候选轨迹不在该时间窗内会被拒绝，避免「瞬移」误合并。
            园区典型配置：门口 → 走廊（5～30s）、走廊 → 出口（10～60s）。
          </p>

          <h3 class="guide-h3">四、监控墙 AI 叠加</h3>
          <ol class="guide-ol mb">
            <li>在本页「会话控制」启动跨镜并选中摄像头。</li>
            <li>点击「打开监控墙叠加」，或手动进入 <b>视频监控 → 监控墙</b>。</li>
            <li>开启「AI 叠加」，填写会话 ID（本页启动后会写入本地缓存）。</li>
            <li>各画面切换为带框与 Global ID 的 MJPEG 流；若叠加失败会自动回退普通监控流。</li>
          </ol>

          <h3 class="guide-h3">五、模型与权重依赖</h3>
          <el-descriptions :column="1" border size="small" class="mb">
            <el-descriptions-item label="人员检测">YOLO 行人检测（如 yolo26n），模型管理启用</el-descriptions-item>
            <el-descriptions-item label="人员强 ReID">osnet-x1-0 / clip-reid-person ONNX（可选，无则回退 Youtu）</el-descriptions-item>
            <el-descriptions-item label="人员底库">行人重识别页登记后，命中可显示姓名</el-descriptions-item>
            <el-descriptions-item label="车辆检测">YOLO 车辆检测 + 车牌检测/OCR</el-descriptions-item>
            <el-descriptions-item label="车辆视觉 ReID">transreid-vehicle / clip-reid-vehicle（可选，无牌时兜底）</el-descriptions-item>
          </el-descriptions>

          <h3 class="guide-h3">六、注意事项（必读）</h3>
          <div class="guide-alerts">
            <el-alert type="warning" :closable="false" show-icon title="后端重启后会话失效" description="跨镜会话保存在后端内存中。重启 Flask 后旧 sessionId 无效，监控墙叠加会 404；请重新启动会话，或关闭 AI 叠加。" />
            <el-alert type="warning" :closable="false" show-icon title="CPU 与路数" description="建议 2～4 路摄像头、采样 FPS ≤ 2、检测分辨率约 640。路数或 FPS 过高会导致延迟堆积、全局 ID 抖动。" />
            <el-alert type="warning" :closable="false" show-icon title="局部跟踪与 CMC" description="默认 ByteTrack + McByte++ 解耦（粘性续 Global、仅新生才长时 ReID）。镜头抖动明显可试 BoT-SORT 并开启 CMC；静止机位不必开 CMC。" />
            <el-alert type="error" :closable="false" show-icon title="合规与隐私" description="人脸、行人外观、车牌属于敏感信息。请确保采集与展示已获授权，生产环境应限制访问权限并遵守当地法规。" />
            <el-alert type="info" :closable="false" show-icon title="排障顺序" description="权重是否就绪 → 摄像头流是否可预览 → 会话是否 running → sessionAlive 是否通过 → 拓扑时间窗是否合理 → 外观阈值是否过严/过松。" />
          </div>

          <h3 class="guide-h3">七、常见问题</h3>
          <el-collapse class="mb">
            <el-collapse-item title="监控墙开了 AI 叠加但没有框？" name="q1">
              <p>先确认跨镜会话仍在运行（本页状态为「是」）；后端重启后需重新启动。监控墙会先调 alive 接口，失败则回退普通流。</p>
            </el-collapse-item>
            <el-collapse-item title="全局 ID 频繁切换？" name="q2">
              <p>适当降低采样 FPS、检查检测是否稳定；调高外观阈值或缩短时间窗；确认拓扑边的时间范围符合实际通行时间；强 ReID 权重未就绪时会更多依赖 Youtu/直方图，跨镜稳定性会下降。</p>
            </el-collapse-item>
            <el-collapse-item title="车辆有牌仍串车？" name="q3">
              <p>检查车牌 OCR 置信度与检测框质量；夜间/污损车牌会退回视觉键。可在事件/过车 Tab 查看 identityKey 与 fuseScore。</p>
            </el-collapse-item>
            <el-collapse-item title="无 edit 权限无法启动？" name="q4">
              <p>启动/停止跨镜、维护拓扑需要 <code>ai:mtmc:edit</code>。只读角色可查看会话与事件。</p>
            </el-collapse-item>
          </el-collapse>

          <p class="guide-foot">
            更完整的技术说明见项目文档 <code>docs/mtmc-cross-camera-reid.md</code>。
          </p>
        </div>
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

/** 操作说明 Tab：参数对照表 */
const paramGuide = [
  { name: '摄像头', desc: '参与跨镜的多路视频源，须已在「摄像头管理」配置且可预览', suggest: '先 2 路联调' },
  { name: '人员 / 车辆', desc: '是否启用人员 MTMC、车辆 MTMC（含车牌融合）', suggest: '按场景开关' },
  { name: '采样 FPS', desc: '每路每秒处理帧数，越高越耗 CPU', suggest: '1～2' },
  { name: '外观阈值', desc: '跨镜外观匹配置信下限，过高易断联，过低易串 ID', suggest: '0.45～0.55' },
  { name: '时间窗(s)', desc: '全局身份在线缓存秒数，影响跨镜关联范围', suggest: '60～120' },
  { name: '局部跟踪', desc: 'ByteTrack 推荐；BoT-SORT 可配合 CMC 抗抖动', suggest: 'bytetrack' },
  { name: 'CMC', desc: '镜头运动补偿，移动/云台摄像头可开', suggest: '静止机关' },
]

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
.guide-wrap { padding: 4px 8px 16px; max-width: 960px; }
.guide-h3 { margin: 18px 0 10px; font-size: 15px; font-weight: 700; color: #1f2d3d; }
.guide-h3:first-of-type { margin-top: 4px; }
.guide-p, .guide-ol { font-size: 13px; line-height: 1.7; color: #5a6b87; margin: 0 0 12px; }
.guide-ol { padding-left: 20px; }
.guide-ol li { margin-bottom: 6px; }
.guide-steps { margin: 12px 0 20px; }
.guide-alerts { display: flex; flex-direction: column; gap: 10px; margin-bottom: 16px; }
.guide-foot { font-size: 12px; color: #8a9bb5; margin-top: 8px; }
.guide-wrap code { font-size: 12px; background: #f0f4f8; padding: 1px 5px; border-radius: 4px; }
</style>
