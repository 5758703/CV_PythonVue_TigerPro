<template>
  <div>
    <el-alert
      type="info"
      :closable="false"
      show-icon
      class="notice"
      title="行人重识别（Youtu ReID）：独立权限与底库。远距/背影/脸不清用外观；开启混合后近距正脸仍用人脸。登记请用全身或半身图。"
    />

    <el-tabs v-model="tab" class="tabs">
      <el-tab-pane label="实时识别" name="live" />
      <el-tab-pane label="图库/录像检索" name="search" />
      <el-tab-pane label="行人底库" name="gallery" />
    </el-tabs>

    <!-- 实时识别：框旁显示 像谁 / 未知 -->
    <template v-if="tab === 'live'">
      <el-card shadow="never" class="cfg-card">
        <el-form :inline="true">
          <el-form-item label="ReID 模型">
            <el-select v-model="reidModelId" placeholder="Youtu ReID" style="width: 260px" :disabled="running">
              <el-option
                v-for="m in reidModels"
                :key="m.id"
                :label="`${m.modelName}（${m.library}）`"
                :value="m.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="行人检测">
            <el-select v-model="detModelId" placeholder="默认 yolo26n" clearable style="width: 200px" :disabled="running">
              <el-option
                v-for="m in detModels"
                :key="m.id"
                :label="detModelLabel(m)"
                :value="m.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="视频源">
            <el-select v-model="videoSource" style="width: 140px" :disabled="running" @change="onSourceChange">
              <el-option label="本地摄像头" value="local" />
              <el-option label="本地视频" value="file" />
              <el-option label="上传图片" value="image" />
            </el-select>
          </el-form-item>
          <el-form-item v-if="videoSource === 'file'" label="视频">
            <el-upload :show-file-list="false" accept="video/*" :auto-upload="false" :on-change="onPickVideo">
              <el-button>{{ videoName || '选择视频' }}</el-button>
            </el-upload>
          </el-form-item>
          <el-form-item label="阈值">
            <el-slider v-model="threshold" :min="0.2" :max="0.8" :step="0.05" style="width: 120px" />
            <span class="n">{{ threshold }}</span>
          </el-form-item>
          <el-form-item label="混合人脸">
            <el-switch v-model="hybrid" :disabled="running" />
          </el-form-item>
          <el-form-item v-if="hybrid" label="人脸模型">
            <el-select v-model="faceModelId" placeholder="人脸模型" style="width: 220px" :disabled="running">
              <el-option
                v-for="m in faceModels"
                :key="m.id"
                :label="`${m.modelName}（${m.library}）`"
                :value="m.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item>
            <template v-if="videoSource === 'image'">
              <el-upload :show-file-list="false" accept="image/*" :auto-upload="false" :on-change="onPickImage">
                <el-button type="primary" :loading="busy" :disabled="!reidModelId || !selectedReidReady">识别图片</el-button>
              </el-upload>
            </template>
            <template v-else>
              <el-button type="primary" :disabled="!canStart" :loading="busy" @click="startLive">开始识别</el-button>
              <el-button :disabled="!running" @click="stopLive">停止</el-button>
            </template>
          </el-form-item>
        </el-form>
        <el-alert
          v-if="reidModelId && !selectedReidReady"
          type="warning"
          :closable="false"
          class="tip"
          title="当前 ReID 模型尚未拉取权重：请到「模型管理」对 OpenCV Youtu Person ReID 点击拉取。"
        />
      </el-card>

      <el-card shadow="never">
        <div class="stage-wrap">
          <div class="stage">
            <video
              v-show="(videoSource === 'local' || videoSource === 'file') && !imageMode"
              ref="videoEl"
              class="cam"
              autoplay
              playsinline
              muted
              loop
            />
            <img v-show="imageMode && previewUrl" :src="previewUrl" class="cam" alt="preview" />
            <canvas ref="overlayEl" class="overlay" />
          </div>
          <div class="side">
            <div class="stat">检出 {{ dets.length }} · 命中 {{ matchedCount }}</div>
            <el-table :data="dets" size="small" max-height="360" empty-text="暂无结果">
              <el-table-column prop="name" label="身份" min-width="90" />
              <el-table-column label="来源" width="72">
                <template #default="{ row }">
                  <el-tag size="small" :type="row.modality === 'face' ? 'success' : row.matched ? 'warning' : 'info'">
                    {{ row.modality === 'face' ? '人脸' : row.matched ? '外观' : '未知' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="分" width="64">
                <template #default="{ row }">{{ ((row.score || 0) * 100).toFixed(0) }}%</template>
              </el-table-column>
            </el-table>
          </div>
        </div>
      </el-card>
    </template>

    <!-- 底库 / 录像检索 -->
    <template v-else-if="tab === 'search'">
      <el-card shadow="never" class="cfg-card">
        <el-form :inline="true">
          <el-form-item label="ReID 模型">
            <el-select v-model="reidModelId" style="width: 260px">
              <el-option v-for="m in reidModels" :key="m.id" :label="m.modelName" :value="m.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="行人检测">
            <el-select v-model="detModelId" clearable placeholder="默认 yolo26n" style="width: 200px">
              <el-option
                v-for="m in detModels"
                :key="m.id"
                :label="detModelLabel(m)"
                :value="m.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="模式">
            <el-radio-group v-model="searchMode">
              <el-radio-button value="gallery">底库检索</el-radio-button>
              <el-radio-button value="video">录像检索</el-radio-button>
            </el-radio-group>
          </el-form-item>
        </el-form>
        <div class="search-row">
          <div>
            <div class="lbl">查询行人图</div>
            <el-upload drag :show-file-list="false" accept="image/*" :auto-upload="false" :on-change="onPickQuery">
              <div v-if="queryUrl" class="q-prev"><img :src="queryUrl" alt="query" /></div>
              <div v-else class="q-tip">拖拽或点击上传全身/半身图</div>
            </el-upload>
          </div>
          <div v-if="searchMode === 'video'">
            <div class="lbl">录像片段</div>
            <el-upload drag :show-file-list="false" accept="video/*" :auto-upload="false" :on-change="onPickSearchVideo">
              <div class="q-tip">{{ searchVideoName || '上传 mp4 / avi 等' }}</div>
            </el-upload>
          </div>
          <div class="actions">
            <el-button type="primary" :loading="searching" :disabled="!canSearch" @click="runSearch">
              {{ searchMode === 'gallery' ? '在底库检索' : '在录像中检索' }}
            </el-button>
          </div>
        </div>
      </el-card>
      <el-card shadow="never">
        <template v-if="searchMode === 'gallery'">
          <el-table :data="galleryHits" empty-text="上传查询图后检索">
            <el-table-column type="index" width="50" />
            <el-table-column prop="name" label="姓名" />
            <el-table-column prop="personId" label="底库ID" width="90" />
            <el-table-column label="相似度" width="100">
              <template #default="{ row }">{{ ((row.score || 0) * 100).toFixed(1) }}%</template>
            </el-table-column>
          </el-table>
        </template>
        <template v-else>
          <el-table :data="videoHits" empty-text="上传查询图与录像后检索">
            <el-table-column label="时间(s)" width="90">
              <template #default="{ row }">{{ row.timeSec }}</template>
            </el-table-column>
            <el-table-column prop="name" label="身份" />
            <el-table-column label="相似度" width="100">
              <template #default="{ row }">{{ ((row.score || 0) * 100).toFixed(1) }}%</template>
            </el-table-column>
            <el-table-column label="bbox" min-width="160">
              <template #default="{ row }">{{ (row.bbox || []).join(', ') }}</template>
            </el-table-column>
          </el-table>
        </template>
      </el-card>
    </template>

    <!-- 底库 -->
    <template v-else>
      <el-card shadow="never">
        <div class="gal-bar">
          <el-input v-model="galleryQuery" placeholder="按姓名搜索" clearable style="width: 200px" @keyup.enter="loadPersons" />
          <el-button @click="loadPersons">查询</el-button>
          <el-button type="primary" @click="openPersonDlg()">新增人员</el-button>
        </div>
        <el-table :data="persons" v-loading="galleryLoading">
          <el-table-column prop="id" label="ID" width="70" />
          <el-table-column prop="name" label="姓名" />
          <el-table-column prop="employeeNo" label="编号" width="120" />
          <el-table-column prop="embeddingCount" label="特征数" width="90" />
          <el-table-column label="关联人脸" min-width="140">
            <template #default="{ row }">
              <span v-if="row.facePersonId">
                {{ facePersonLabel(row.facePersonId) }}
              </span>
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="220" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="openEnroll(row)">登记外观</el-button>
              <el-button link @click="openPersonDlg(row)">编辑</el-button>
              <el-button link type="danger" @click="removePerson(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-card>
    </template>

    <el-dialog v-model="personDlg" :title="personForm.id ? '编辑人员' : '新增人员'" width="520px" @open="onPersonDlgOpen">
      <el-form label-width="110px">
        <el-form-item label="姓名" required>
          <el-input v-model="personForm.name" />
        </el-form-item>
        <el-form-item label="编号">
          <el-input v-model="personForm.employeeNo" />
        </el-form-item>
        <el-form-item label="关联人脸">
          <div class="face-link">
            <el-radio-group v-model="faceLinkMode" size="small" @change="onFaceLinkModeChange">
              <el-radio-button value="select">从人脸底库选择</el-radio-button>
              <el-radio-button value="input">直接输入 ID</el-radio-button>
            </el-radio-group>
            <el-select
              v-if="faceLinkMode === 'select'"
              v-model="personForm.facePersonId"
              filterable
              clearable
              placeholder="搜索姓名 / 编号 / ID"
              style="width: 100%; margin-top: 8px"
              :loading="facePersonsLoading"
              :filter-method="filterFacePersons"
              @visible-change="(v) => v && loadFacePersons()"
              @change="onFacePersonSelect"
            >
              <el-option
                v-for="p in facePersonOptions"
                :key="p.id"
                :label="formatFaceOption(p)"
                :value="p.id"
              />
            </el-select>
            <el-input
              v-else
              v-model="facePersonIdInput"
              clearable
              placeholder="输入人脸底库人员数字 ID"
              style="margin-top: 8px"
              @input="onFaceIdInput"
            />
            <div v-if="linkedFaceHint" class="face-hint">{{ linkedFaceHint }}</div>
          </div>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="personForm.remark" type="textarea" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="personDlg = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="savePerson">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="enrollDlg" title="登记外观特征" width="480px" @closed="enrollFiles = []">
      <p class="hint">请上传 1～若干张全身/半身图（背影亦可）。将按当前 ReID 模型写入独立 embedding 表。</p>
      <el-form label-width="100px">
        <el-form-item label="ReID 模型">
          <el-select v-model="enrollModelId" style="width: 100%">
            <el-option v-for="m in reidModels" :key="m.id" :label="m.modelName" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="照片">
          <el-upload
            :auto-upload="false"
            accept="image/*"
            multiple
            :file-list="enrollFiles"
            :on-change="onEnrollFiles"
            :on-remove="onEnrollRemove"
          >
            <el-button>选择图片</el-button>
          </el-upload>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="enrollDlg = false">取消</el-button>
        <el-button type="primary" :loading="enrolling" @click="doEnroll">登记</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { modelApi, reidApi, faceApi } from '../../../api/ai'

const tab = ref('live')
const reidModels = ref([])
const detModels = ref([])
const faceModels = ref([])
const reidModelId = ref(null)
const detModelId = ref(null)
const faceModelId = ref(null)
const threshold = ref(0.45)
const hybrid = ref(false)
const videoSource = ref('local')
const videoEl = ref(null)
const overlayEl = ref(null)
const running = ref(false)
const busy = ref(false)
const dets = ref([])
const imageMode = ref(false)
const previewUrl = ref('')
const videoUrl = ref('')
const videoName = ref('')

const matchedCount = computed(() => dets.value.filter((d) => d.matched).length)
const selectedReid = computed(() => reidModels.value.find((m) => m.id === reidModelId.value))
const selectedReidReady = computed(() => !!(selectedReid.value && selectedReid.value.filePath))
const canStart = computed(() => {
  if (!reidModelId.value || !selectedReidReady.value) return false
  if (hybrid.value && !faceModelId.value) return false
  if (videoSource.value === 'file' && !videoUrl.value) return false
  return true
})

let stream = null
let capCanvas = null
let loopTimer = null
let inferSeq = 0

const LM_FACE = '#67c23a'
const LM_REID = '#e6a23c'
const LM_UNK = '#909399'

const DET_LABEL_TAG = {
  yolo26n: '默认',
  'winedarksea-yolo26n_person': '推荐2',
  'simoswish-persondetector_yolo26_prw': '推荐3',
}
const detModelLabel = (m) => {
  const key = String(m.modelKey || '').toLowerCase()
  const tag = DET_LABEL_TAG[key]
  return tag ? `${m.modelName}（${tag}）` : m.modelName
}

const loadModels = async () => {
  const [r1, r2, r3] = await Promise.all([
    modelApi.list({ pageNum: 1, pageSize: 200, task: 'person-reid' }),
    modelApi.list({ pageNum: 1, pageSize: 200, task: 'object-detection' }),
    modelApi.list({ pageNum: 1, pageSize: 200, task: 'face-recognition' }),
  ])
  reidModels.value = (r1.data.rows || []).filter(
    (m) => /opencv-reid|youtu/i.test(m.library || '') && m.status === '0',
  )
  if (!reidModels.value.length) {
    reidModels.value = (r1.data.rows || []).filter((m) => m.status === '0')
  }
  detModels.value = (r2.data.rows || []).filter(
    (m) => (m.library || '').toLowerCase() === 'ultralytics' && m.filePath && m.status === '0',
  )
  // 下拉优先级：yolo26n > winedarksea-yolo26n_person > simoswish-PersonDetector_YOLO26_PRW
  const DET_PREF = [
    'yolo26n',
    'winedarksea-yolo26n_person',
    'simoswish-persondetector_yolo26_prw',
  ]
  const detRank = (m) => {
    const key = String(m.modelKey || '').toLowerCase()
    const i = DET_PREF.indexOf(key)
    return i >= 0 ? i : 100
  }
  detModels.value.sort((a, b) => detRank(a) - detRank(b) || (a.id || 0) - (b.id || 0))
  faceModels.value = (r3.data.rows || []).filter((m) => m.filePath && m.status === '0')
  if (!reidModelId.value && reidModels.value.length) reidModelId.value = reidModels.value[0].id
  if (!detModelId.value && detModels.value.length) {
    const pref = DET_PREF.map((k) =>
      detModels.value.find((m) => String(m.modelKey || '').toLowerCase() === k),
    ).find(Boolean)
    detModelId.value = pref?.id || detModels.value[0].id
  }
  if (!faceModelId.value && faceModels.value.length) {
    const ov = faceModels.value.find((m) => /opencv|yunet/i.test(m.library || ''))
    faceModelId.value = ov?.id || faceModels.value[0].id
  }
}

const onSourceChange = () => {
  stopLive()
  imageMode.value = false
  previewUrl.value = ''
}

const onPickVideo = (f) => {
  const raw = f.raw || f
  if (videoUrl.value) URL.revokeObjectURL(videoUrl.value)
  videoUrl.value = URL.createObjectURL(raw)
  videoName.value = raw.name || 'video'
}

const canvasToBlob = (cv, type = 'image/jpeg', q = 0.7) =>
  new Promise((resolve) => cv.toBlob((b) => resolve(b), type, q))

const drawBoxes = (list) => {
  const cv = overlayEl.value
  if (!cv) return
  const ctx = cv.getContext('2d')
  ctx.clearRect(0, 0, cv.width, cv.height)
  ctx.lineWidth = 2
  ctx.font = '13px sans-serif'
  list.forEach((d) => {
    const [x1, y1, x2, y2] = d.bbox || [0, 0, 0, 0]
    const color = d.matched ? (d.modality === 'face' ? LM_FACE : LM_REID) : LM_UNK
    ctx.strokeStyle = color
    ctx.strokeRect(x1, y1, x2 - x1, y2 - y1)
    const tag = d.modality === 'face' && d.matched ? '脸' : d.matched ? '外观' : '未知'
    const label = `[${tag}] ${d.name || '未知'} ${((d.score || 0) * 100).toFixed(0)}%`
    const tw = ctx.measureText(label).width + 8
    ctx.fillStyle = color
    ctx.fillRect(x1, Math.max(0, y1 - 18), tw, 18)
    ctx.fillStyle = '#fff'
    ctx.fillText(label, x1 + 4, Math.max(2, y1 - 16))
  })
}

const buildForm = (blob) => {
  const fd = new FormData()
  fd.append('file', blob, 'frame.jpg')
  fd.append('modelId', reidModelId.value)
  if (detModelId.value) fd.append('detectorModelId', detModelId.value)
  fd.append('threshold', threshold.value)
  fd.append('draw', '0')
  fd.append('hybrid', hybrid.value ? '1' : '0')
  if (hybrid.value && faceModelId.value) fd.append('faceModelId', faceModelId.value)
  return fd
}

const recognizeBlob = async (blob) => {
  const res = await reidApi.recognize(buildForm(blob))
  const list = res.data.detections || []
  dets.value = list
  drawBoxes(list)
  return list
}

const onPickImage = async (f) => {
  const raw = f.raw || f
  stopLive()
  imageMode.value = true
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = URL.createObjectURL(raw)
  busy.value = true
  try {
    await nextTick()
    const img = new Image()
    img.src = previewUrl.value
    await new Promise((r, j) => {
      img.onload = r
      img.onerror = j
    })
    const maxW = 640
    const scale = Math.min(1, maxW / img.width)
    const w = Math.round(img.width * scale)
    const h = Math.round(img.height * scale)
    capCanvas = document.createElement('canvas')
    capCanvas.width = w
    capCanvas.height = h
    capCanvas.getContext('2d').drawImage(img, 0, 0, w, h)
    if (overlayEl.value) {
      overlayEl.value.width = w
      overlayEl.value.height = h
    }
    const blob = await canvasToBlob(capCanvas)
    await recognizeBlob(blob)
  } catch (e) {
    ElMessage.error(e?.message || '识别失败')
  } finally {
    busy.value = false
  }
}

const waitVideo = (video, ms = 8000) =>
  new Promise((resolve, reject) => {
    if (video.videoWidth > 0) return resolve()
    const t = setTimeout(() => reject(new Error('视频未就绪')), ms)
    video.onloadeddata = () => {
      clearTimeout(t)
      resolve()
    }
  })

const startLive = async () => {
  if (!canStart.value) return
  stopLive()
  imageMode.value = false
  await nextTick()
  const video = videoEl.value
  if (!video) return
  try {
    if (videoSource.value === 'file') {
      video.srcObject = null
      video.src = videoUrl.value
      video.loop = true
      await video.play().catch(() => {})
      await waitVideo(video)
    } else {
      video.removeAttribute('src')
      stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false })
      video.srcObject = stream
      await video.play().catch(() => {})
      await waitVideo(video)
    }
  } catch (_) {
    ElMessage.error('无法打开视频源')
    return
  }
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
  scheduleLoop()
}

const scheduleLoop = () => {
  if (loopTimer) clearTimeout(loopTimer)
  loopTimer = setTimeout(liveLoop, 0)
}

const liveLoop = async () => {
  if (!running.value) return
  const video = videoEl.value
  if (!video || !capCanvas) {
    scheduleLoop()
    return
  }
  const ctx = capCanvas.getContext('2d')
  ctx.drawImage(video, 0, 0, capCanvas.width, capCanvas.height)
  const my = ++inferSeq
  busy.value = true
  try {
    const blob = await canvasToBlob(capCanvas, 'image/jpeg', 0.55)
    if (!running.value || my !== inferSeq) return
    await recognizeBlob(blob)
  } catch (_) {
    /* 单帧失败忽略 */
  } finally {
    busy.value = false
    if (running.value) {
      loopTimer = setTimeout(liveLoop, 200)
    }
  }
}

const stopLive = () => {
  running.value = false
  if (loopTimer) clearTimeout(loopTimer)
  loopTimer = null
  if (stream) {
    stream.getTracks().forEach((t) => t.stop())
    stream = null
  }
  if (videoEl.value) {
    videoEl.value.pause?.()
    videoEl.value.srcObject = null
  }
}

/* ---- search ---- */
const searchMode = ref('gallery')
const queryFile = ref(null)
const queryUrl = ref('')
const searchVideoFile = ref(null)
const searchVideoName = ref('')
const searching = ref(false)
const galleryHits = ref([])
const videoHits = ref([])
const canSearch = computed(() => {
  if (!reidModelId.value || !selectedReidReady.value || !queryFile.value) return false
  if (searchMode.value === 'video' && !searchVideoFile.value) return false
  return true
})

const onPickQuery = (f) => {
  const raw = f.raw || f
  queryFile.value = raw
  if (queryUrl.value) URL.revokeObjectURL(queryUrl.value)
  queryUrl.value = URL.createObjectURL(raw)
}
const onPickSearchVideo = (f) => {
  const raw = f.raw || f
  searchVideoFile.value = raw
  searchVideoName.value = raw.name || 'video'
}

const runSearch = async () => {
  if (!canSearch.value) return
  searching.value = true
  try {
    const fd = new FormData()
    fd.append('file', queryFile.value)
    fd.append('modelId', reidModelId.value)
    if (detModelId.value) fd.append('detectorModelId', detModelId.value)
    if (searchMode.value === 'gallery') {
      fd.append('topk', 10)
      const res = await reidApi.search(fd)
      galleryHits.value = res.data.matches || []
      ElMessage.success(`命中 ${galleryHits.value.length} 条`)
    } else {
      fd.append('query', queryFile.value)
      fd.append('video', searchVideoFile.value)
      fd.append('threshold', threshold.value)
      const res = await reidApi.searchVideo(fd)
      videoHits.value = res.data.hits || []
      ElMessage.success(`命中 ${videoHits.value.length} 处`)
    }
  } catch (e) {
    ElMessage.error(e?.response?.data?.message || e?.message || '检索失败')
  } finally {
    searching.value = false
  }
}

/* ---- gallery ---- */
const persons = ref([])
const galleryLoading = ref(false)
const galleryQuery = ref('')
const personDlg = ref(false)
const saving = ref(false)
const personForm = ref({ id: null, name: '', employeeNo: '', remark: '', facePersonId: null })
const faceLinkMode = ref('select') // select | input
const facePersonIdInput = ref('')
const facePersons = ref([])
const facePersonOptions = ref([])
const facePersonsLoading = ref(false)
const facePersonMap = computed(() => {
  const m = new Map()
  facePersons.value.forEach((p) => m.set(p.id, p))
  return m
})

const formatFaceOption = (p) => {
  const no = p.employeeNo ? ` · ${p.employeeNo}` : ''
  return `${p.name}（ID ${p.id}${no}）`
}

const facePersonLabel = (id) => {
  if (id == null || id === '') return '—'
  const p = facePersonMap.value.get(Number(id))
  if (p) return `${p.name}（#${p.id}）`
  return `#${id}`
}

const linkedFaceHint = computed(() => {
  const id = personForm.value.facePersonId
  if (id == null || id === '') return ''
  const p = facePersonMap.value.get(Number(id))
  if (p) {
    const no = p.employeeNo ? `，编号 ${p.employeeNo}` : ''
    return `已关联：${p.name}（人脸底库 ID ${p.id}${no}）`
  }
  if (faceLinkMode.value === 'input') {
    return `将关联人脸底库 ID ${id}（未在当前列表中找到，请确认 ID 正确）`
  }
  return ''
})

const loadFacePersons = async (name, { warn = false } = {}) => {
  facePersonsLoading.value = true
  try {
    const res = await faceApi.listPersons({ name: name || undefined })
    facePersons.value = res.data?.rows || []
    facePersonOptions.value = facePersons.value
  } catch (_) {
    if (warn) {
      ElMessage.warning('无法加载人脸底库，请改用「直接输入 ID」或确认已有 ai:face:list 权限')
    }
  } finally {
    facePersonsLoading.value = false
  }
}

const filterFacePersons = (query) => {
  const q = String(query || '').trim().toLowerCase()
  if (!q) {
    facePersonOptions.value = facePersons.value
    return
  }
  facePersonOptions.value = facePersons.value.filter((p) => {
    const hay = `${p.id} ${p.name || ''} ${p.employeeNo || ''}`.toLowerCase()
    return hay.includes(q)
  })
}

const syncFaceLinkModeFromValue = () => {
  const id = personForm.value.facePersonId
  if (id == null || id === '') {
    faceLinkMode.value = 'select'
    facePersonIdInput.value = ''
    return
  }
  const known = facePersonMap.value.has(Number(id))
  faceLinkMode.value = known ? 'select' : 'input'
  facePersonIdInput.value = String(id)
}

const onPersonDlgOpen = async () => {
  await loadFacePersons(undefined, { warn: true })
  syncFaceLinkModeFromValue()
}

const onFaceLinkModeChange = () => {
  if (faceLinkMode.value === 'input') {
    facePersonIdInput.value =
      personForm.value.facePersonId != null && personForm.value.facePersonId !== ''
        ? String(personForm.value.facePersonId)
        : ''
  } else {
    // 切回下拉：若当前 ID 不在列表中则清空，避免 el-select 显示异常
    const id = personForm.value.facePersonId
    if (id != null && id !== '' && !facePersonMap.value.has(Number(id))) {
      personForm.value.facePersonId = null
    }
  }
}

const onFacePersonSelect = (id) => {
  personForm.value.facePersonId = id == null || id === '' ? null : Number(id)
  const p = facePersonMap.value.get(Number(id))
  if (p) {
    if (!personForm.value.name?.trim()) personForm.value.name = p.name || ''
    if (!personForm.value.employeeNo?.trim() && p.employeeNo) {
      personForm.value.employeeNo = p.employeeNo
    }
  }
}

const onFaceIdInput = (val) => {
  const s = String(val || '').trim()
  if (!s) {
    personForm.value.facePersonId = null
    return
  }
  if (!/^\d+$/.test(s)) {
    return
  }
  personForm.value.facePersonId = Number(s)
}

const enrollDlg = ref(false)
const enrollPerson = ref(null)
const enrollModelId = ref(null)
const enrollFiles = ref([])
const enrolling = ref(false)

const loadPersons = async () => {
  galleryLoading.value = true
  try {
    const res = await reidApi.listPersons({ name: galleryQuery.value || undefined })
    persons.value = res.data.rows || []
  } finally {
    galleryLoading.value = false
  }
}

const openPersonDlg = async (row) => {
  if (row) {
    personForm.value = {
      id: row.id,
      name: row.name,
      employeeNo: row.employeeNo || '',
      remark: row.remark || '',
      facePersonId: row.facePersonId != null ? Number(row.facePersonId) : null,
    }
  } else {
    personForm.value = { id: null, name: '', employeeNo: '', remark: '', facePersonId: null }
  }
  facePersonIdInput.value =
    personForm.value.facePersonId != null ? String(personForm.value.facePersonId) : ''
  personDlg.value = true
}

const savePerson = async () => {
  if (!personForm.value.name?.trim()) {
    ElMessage.warning('请填写姓名')
    return
  }
  if (faceLinkMode.value === 'input') {
    const s = String(facePersonIdInput.value || '').trim()
    if (s && !/^\d+$/.test(s)) {
      ElMessage.warning('人脸 ID 须为数字')
      return
    }
    personForm.value.facePersonId = s ? Number(s) : null
  }
  const faceId = personForm.value.facePersonId
  if (faceId != null && faceId !== '' && !facePersonMap.value.has(Number(faceId))) {
    try {
      const res = await faceApi.getPerson(Number(faceId))
      if (!res?.data?.id) {
        await ElMessageBox.confirm(
          `人脸底库中未找到 ID=${faceId}，是否仍保存该关联？`,
          '提示',
          { type: 'warning' },
        )
      }
    } catch (e) {
      if (e === 'cancel' || e === 'close') return
      try {
        await ElMessageBox.confirm(
          `无法校验人脸 ID=${faceId}（可能无权限或不存在），是否仍保存？`,
          '提示',
          { type: 'warning' },
        )
      } catch (e2) {
        if (e2 === 'cancel' || e2 === 'close') return
        throw e2
      }
    }
  }
  saving.value = true
  try {
    const payload = {
      name: personForm.value.name,
      employeeNo: personForm.value.employeeNo,
      remark: personForm.value.remark,
      facePersonId: personForm.value.facePersonId || null,
    }
    if (personForm.value.id) await reidApi.updatePerson(personForm.value.id, payload)
    else await reidApi.addPerson(payload)
    ElMessage.success('已保存')
    personDlg.value = false
    await loadPersons()
  } finally {
    saving.value = false
  }
}

const removePerson = async (row) => {
  await ElMessageBox.confirm(`删除「${row.name}」及其外观特征？`, '确认', { type: 'warning' })
  await reidApi.removePerson(row.id)
  await loadPersons()
}

const openEnroll = (row) => {
  enrollPerson.value = row
  enrollModelId.value = reidModelId.value
  enrollFiles.value = []
  enrollDlg.value = true
}
const onEnrollFiles = (_f, list) => {
  enrollFiles.value = list
}
const onEnrollRemove = (_f, list) => {
  enrollFiles.value = list
}

const doEnroll = async () => {
  if (!enrollPerson.value || !enrollModelId.value) return
  if (!enrollFiles.value.length) {
    ElMessage.warning('请选择图片')
    return
  }
  enrolling.value = true
  try {
    const fd = new FormData()
    fd.append('modelId', enrollModelId.value)
    if (detModelId.value) fd.append('detectorModelId', detModelId.value)
    enrollFiles.value.forEach((f) => fd.append('files', f.raw || f))
    await reidApi.enroll(enrollPerson.value.id, fd)
    ElMessage.success('登记成功')
    enrollDlg.value = false
    await loadPersons()
  } catch (e) {
    ElMessage.error(e?.response?.data?.message || e?.message || '登记失败')
  } finally {
    enrolling.value = false
  }
}

onMounted(async () => {
  await Promise.all([loadModels(), loadPersons(), loadFacePersons()])
})

onBeforeUnmount(() => {
  stopLive()
  if (videoUrl.value) URL.revokeObjectURL(videoUrl.value)
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  if (queryUrl.value) URL.revokeObjectURL(queryUrl.value)
})
</script>

<style scoped>
.notice { margin-bottom: 12px; }
.tabs { margin-bottom: 8px; }
.cfg-card { margin-bottom: 12px; }
.tip { margin-top: 8px; }
.n { margin-left: 6px; color: #666; font-size: 12px; }
.stage-wrap { display: flex; gap: 16px; flex-wrap: wrap; }
.stage { position: relative; flex: 1; min-width: 320px; min-height: 360px; background: #111; border-radius: 6px; overflow: hidden; }
.cam,
.overlay {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: contain;
}
.overlay { pointer-events: none; }
.side { width: 280px; }
.stat { margin-bottom: 8px; font-weight: 600; }
.search-row { display: flex; gap: 16px; flex-wrap: wrap; align-items: flex-start; }
.lbl { margin-bottom: 6px; font-size: 13px; color: #666; }
.q-prev img { max-width: 220px; max-height: 160px; object-fit: contain; }
.q-tip { padding: 24px; color: #999; }
.actions { display: flex; align-items: flex-end; padding-top: 28px; }
.gal-bar { display: flex; gap: 8px; margin-bottom: 12px; }
.hint { font-size: 13px; color: #666; margin: 0 0 12px; }
.muted { color: #bbb; }
.face-link { width: 100%; }
.face-hint { margin-top: 6px; font-size: 12px; color: #67c23a; line-height: 1.4; }
</style>
