<template>
  <div class="absence-page">
    <!-- ======== 检测配置（与结果分离） ======== -->
    <el-card shadow="never" class="cfg-card">
      <template #header>
        <div class="card-head">
          <div class="card-head-left">
            <span class="card-title">检测配置</span>
            <el-tooltip placement="bottom-start">
              <template #content>
                <div class="help-pop">
                  <p>{{ alertTitle }}</p>
                  <p>推荐：YOLO26s 通用检测 + InsightFace Buffalo-L。人脸模型须与「人脸识别」页登记时一致，否则无法判定在岗（S/L 特征空间不通用）。</p>
                </div>
              </template>
              <el-icon class="card-help"><QuestionFilled /></el-icon>
            </el-tooltip>
            <el-tag v-if="camRunning" type="success" size="small" effect="plain">检测中</el-tag>
            <el-tag v-else-if="previewOpen && mode !== 'file'" type="info" size="small" effect="plain">预览中</el-tag>
          </div>
          <div class="card-head-actions">
            <template v-if="mode === 'file'">
              <el-button type="primary" :loading="running" :disabled="!canStartFile" @click="runVideo">开始检测</el-button>
            </template>
            <template v-else>
              <el-button v-if="!camRunning" type="primary" :disabled="!canStartLive" @click="camStart">开始检测</el-button>
              <el-button v-else type="danger" @click="camStopDetect">停止检测</el-button>
            </template>
          </div>
        </div>
      </template>

      <el-form label-position="top" class="cfg-form" @submit.prevent>
        <div class="cfg-section">
          <div class="cfg-section-title">输入源</div>
          <el-row :gutter="16">
            <el-col :xs="24" :sm="8" :md="5">
              <el-form-item label="来源">
                <el-select v-model="mode" :disabled="busy" @change="onModeChange">
                  <el-option label="视频文件" value="file" />
                  <el-option label="本地摄像头" value="local" />
                  <el-option label="网络摄像头" value="network" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col v-if="mode === 'file'" :xs="24" :sm="16" :md="10">
              <el-form-item label="视频文件">
                <div class="src-pick">
                  <el-upload :show-file-list="false" :auto-upload="false" accept="video/*" :on-change="onPick">
                    <el-button :icon="UploadFilled" :disabled="busy">选择视频</el-button>
                  </el-upload>
                  <span class="file-name" :title="file?.name">{{ file?.name || '未选择' }}</span>
                </div>
              </el-form-item>
            </el-col>
            <el-col v-if="mode === 'local'" :xs="24" :sm="16" :md="10">
              <el-form-item label="本地摄像头">
                <div class="src-pick">
                  <el-select
                    v-model="deviceId"
                    placeholder="选择本地摄像头"
                    :disabled="camRunning"
                    :loading="devicesLoading"
                    @change="onLocalDeviceChange"
                  >
                    <el-option v-for="d in devices" :key="d.deviceId" :label="d.label" :value="d.deviceId" />
                  </el-select>
                  <el-button link type="primary" :disabled="camRunning" @click="refreshLocalDevices">刷新</el-button>
                </div>
              </el-form-item>
            </el-col>
            <el-col v-if="mode === 'network'" :xs="24" :sm="16" :md="10">
              <el-form-item label="网络摄像头">
                <div class="src-pick">
                  <el-select v-model="cameraId" filterable clearable :disabled="camRunning" :loading="camerasLoading" @change="onNetworkCameraChange">
                    <el-option v-for="c in managedCameras" :key="c.id" :label="cameraLabel(c)" :value="c.id" />
                  </el-select>
                  <el-button link type="primary" @click="loadCameras">刷新</el-button>
                </div>
              </el-form-item>
            </el-col>
          </el-row>
        </div>

        <div class="cfg-section">
          <div class="cfg-section-title">模型</div>
          <el-row :gutter="16">
            <el-col :xs="24" :sm="12" :md="7">
              <el-form-item label="人员检测">
                <el-select v-model="detectId" placeholder="YOLO 检测" filterable :disabled="busy">
                  <el-option v-for="m in detectModels" :key="m.id" :label="detectOptionLabel(m)" :value="m.id" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12" :md="7">
              <el-form-item label="人脸模型">
                <el-select v-model="faceModelId" placeholder="InsightFace" filterable :disabled="busy" @change="onFaceModelChange">
                  <el-option v-for="m in faceModels" :key="m.id" :label="faceOptionLabel(m)" :value="m.id" />
                </el-select>
              </el-form-item>
            </el-col>
          </el-row>
        </div>

        <div class="cfg-section">
          <div class="cfg-section-title">在岗判定</div>
          <el-row :gutter="16">
            <el-col :xs="24" :sm="12" :md="8">
              <el-form-item label="在岗名单">
                <div class="src-pick">
                  <el-select
                    v-model="staffIds"
                    multiple
                    filterable
                    collapse-tags
                    collapse-tags-tooltip
                    placeholder="勾选已登记员工"
                    :disabled="busy"
                    :loading="staffLoading"
                  >
                    <el-option v-for="p in staffOptions" :key="p.id" :label="staffLabel(p)" :value="p.id" />
                  </el-select>
                  <el-button link type="primary" :disabled="busy" @click="loadStaff">刷新</el-button>
                </div>
              </el-form-item>
            </el-col>
            <el-col :xs="12" :sm="6" :md="5">
              <el-form-item label="工位模式">
                <el-select v-model="zoneMode" :disabled="busy" @change="onZoneModeChange">
                  <el-option label="整帧" value="none" />
                  <el-option label="单工位" value="single" />
                  <el-option label="多工位" value="multi" />
                </el-select>
                <div class="field-hint">{{ zoneModeHint }}</div>
              </el-form-item>
            </el-col>
            <el-col :xs="12" :sm="6" :md="5">
              <el-form-item label="离岗阈值（秒）">
                <el-input-number v-model="absenceThresholdSec" :min="3" :max="3600" :step="5" :disabled="busy" style="width: 100%" />
              </el-form-item>
            </el-col>
          </el-row>
        </div>

        <el-collapse class="adv-collapse">
          <el-collapse-item name="adv">
            <template #title>
              <span class="adv-title">高级参数</span>
              <span class="adv-sub">人脸阈值 {{ faceThreshold.toFixed(2) }} · 置信度 {{ conf.toFixed(2) }}</span>
            </template>
            <el-row :gutter="24">
              <el-col :xs="24" :sm="12" :md="6">
                <el-form-item label="人脸阈值">
                  <el-slider v-model="faceThreshold" :min="0.2" :max="0.8" :step="0.05" :disabled="busy" />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12" :md="6">
                <el-form-item label="检测置信度">
                  <el-slider v-model="conf" :min="0.05" :max="0.95" :step="0.05" :disabled="busy" />
                </el-form-item>
              </el-col>
              <template v-if="zoneMode === 'single'">
                <el-col :xs="8" :sm="4" :md="3">
                  <el-form-item label="区域线色">
                    <el-color-picker v-model="zoneBorderColor" :disabled="busy" />
                  </el-form-item>
                </el-col>
                <el-col :xs="8" :sm="4" :md="3">
                  <el-form-item label="区域填充">
                    <el-color-picker v-model="zoneFillColor" show-alpha :disabled="busy" />
                  </el-form-item>
                </el-col>
              </template>
              <el-col v-if="zoneMode !== 'none'" :xs="8" :sm="6" :md="4">
                <el-form-item label="区域线宽">
                  <el-input-number v-model="zoneBorderWidth" :min="1" :max="16" :step="1" :disabled="busy" controls-position="right" style="width: 100%" />
                </el-form-item>
              </el-col>
            </el-row>
          </el-collapse-item>
        </el-collapse>
      </el-form>

      <!-- 摄像头模式的工位列表（文件模式的列表在「工位绘制」卡内） -->
      <div v-if="zoneMode === 'multi' && mode !== 'file'" class="zone-list">
        <div class="zone-list-title">工位列表（{{ dutyZones.length }}）</div>
        <div v-if="!dutyZones.length" class="hint-inline">在实时画面上点 ≥3 点后「闭合并添加工位」</div>
        <div v-for="(z, i) in dutyZones" :key="z.id" class="zone-row">
          <span class="zone-swatch" :style="{ background: z.borderColor }" />
          <el-input v-model="z.name" size="small" style="width: 110px" :disabled="busy" />
          <el-select
            v-model="z.staffIds"
            multiple
            filterable
            collapse-tags
            collapse-tags-tooltip
            placeholder="本工位人员"
            size="small"
            style="width: 220px"
            :disabled="busy"
          >
            <el-option v-for="p in staffOptions" :key="p.id" :label="staffLabel(p)" :value="p.id" />
          </el-select>
          <el-color-picker v-model="z.borderColor" size="small" :disabled="busy" @change="(c) => onZoneColorChange(z, c)" />
          <el-button link type="danger" :disabled="busy" @click="removeDutyZone(i)">删除</el-button>
        </div>
      </div>
    </el-card>

    <!-- ======== 工位绘制（属于配置，独立成卡） ======== -->
    <el-card v-if="mode === 'file' && previewUrl" shadow="never" class="draw-card">
      <template #header>
        <div class="card-head">
          <div class="card-head-left">
            <span class="card-title">{{ zoneMode === 'none' ? '视频预览' : '工位绘制' }}</span>
            <template v-if="zoneMode !== 'none'">
              <el-tag v-if="motionLoading" size="small" type="info">镜头运动分析中…</el-tag>
              <el-tag v-else-if="motionProfile" size="small" type="success" effect="plain">已启用镜头运动补偿</el-tag>
            </template>
          </div>
        </div>
      </template>
      <el-row :gutter="16">
        <!-- 左侧：仅预览/定位，绝不画工位、绝不在 seek 时改右侧 -->
        <el-col :xs="24" :lg="zoneMode === 'none' ? 24 : 10">
          <div class="sub-title">视频预览（拖动只换画面，蓝框为已添加工位）</div>
          <div class="preview-stage">
            <video
              ref="previewVideo"
              :src="previewUrl"
              class="player"
              preload="auto"
              playsinline
              @loadedmetadata="onPreviewMeta"
              @seeked="onPreviewSeeked"
              @timeupdate="onPreviewTimeUpdate"
            />
            <canvas ref="previewOverlay" class="preview-zone-overlay" />
          </div>
          <div v-if="zoneMode !== 'none'" class="seek-bar">
            <el-button size="small" @click="togglePreviewPlay">{{ previewPlaying ? '暂停' : '播放' }}</el-button>
            <span class="seek-label">定位</span>
            <el-slider
              v-model="seekSec"
              :min="0"
              :max="Math.max(durationSec, 0.1)"
              :step="0.05"
              :format-tooltip="formatSeekTip"
              style="flex: 1; margin: 0 12px"
              @change="seekPreviewTo"
            />
            <span class="seek-time">{{ formatClock(seekSec) }} / {{ formatClock(durationSec) }}</span>
          </div>
          <div v-if="zoneMode !== 'none'" class="capture-row">
            <el-button type="primary" size="small" :disabled="!canCaptureFrame" @click="captureDrawFrame(true)">
              用当前帧作底图
            </el-button>
            <span class="hint-inline">只有点此按钮才会更新右侧画布；拖定位条不会改右侧。</span>
          </div>
        </el-col>
        <!-- 右侧：完全独立的冻结 ImageData 画布 -->
        <el-col v-if="zoneMode !== 'none'" :xs="24" :lg="14">
          <div class="sub-title">
            工位画布（冻结底图）
            <el-tag v-if="frozenAtSec != null" size="small" type="warning" class="frozen-tag">
              底图冻结于 {{ formatClock(frozenAtSec) }}
            </el-tag>
            <el-tag v-else size="small" type="info" class="frozen-tag">尚未抓取底图</el-tag>
          </div>
          <div class="field-hint zone-fixed-tip">
            在下方画布画工位（可连续画多个）。工位钉在画面内容上：镜头移动或拖动定位时，左侧叠加框自动跟随所标注的真实位置。
          </div>
          <div v-if="zoneMode === 'single'" class="line-tip">
            在画布上点 ≥3 点后闭合。
            <el-button link type="success" :disabled="regionPts.length < 3" @click="finishRegion">闭合区域</el-button>
            <el-button link type="primary" @click="clearRegion">清除</el-button>
          </div>
          <div v-else class="line-tip">
            多工位：画布加点 → 闭合并添加 → 再画下一个。
            <el-button link type="success" :disabled="draftPts.length < 3" @click="finishDraftZone">闭合并添加工位</el-button>
            <el-button link type="warning" :disabled="!draftPts.length" @click="undoDraftPoint">撤销点</el-button>
            <el-button link type="primary" :disabled="!draftPts.length" @click="clearDraft">清除草稿</el-button>
          </div>
          <canvas ref="drawCanvas" class="frame-canvas" @click="onDrawCanvasClick" />
        </el-col>
      </el-row>
      <!-- 文件模式的多工位列表：紧邻绘制画布，边画边配名单 -->
      <div v-if="zoneMode === 'multi'" class="zone-list">
        <div class="zone-list-title">工位列表（{{ dutyZones.length }}）</div>
        <div v-if="!dutyZones.length" class="hint-inline">在右侧画布点 ≥3 点后「闭合并添加工位」</div>
        <div v-for="(z, i) in dutyZones" :key="z.id" class="zone-row">
          <span class="zone-swatch" :style="{ background: z.borderColor }" />
          <el-input v-model="z.name" size="small" style="width: 110px" :disabled="busy" />
          <el-select
            v-model="z.staffIds"
            multiple
            filterable
            collapse-tags
            collapse-tags-tooltip
            placeholder="本工位人员"
            size="small"
            style="width: 220px"
            :disabled="busy"
          >
            <el-option v-for="p in staffOptions" :key="p.id" :label="staffLabel(p)" :value="p.id" />
          </el-select>
          <el-color-picker v-model="z.borderColor" size="small" :disabled="busy" @change="(c) => onZoneColorChange(z, c)" />
          <el-button link type="danger" :disabled="busy" @click="removeDutyZone(i)">删除</el-button>
        </div>
      </div>
    </el-card>

    <!-- ======== 检测结果 ======== -->
    <el-card v-if="mode === 'file'" shadow="never" class="res-card">
      <template #header>
        <div class="card-head">
          <div class="card-head-left">
            <span class="card-title">检测结果</span>
            <el-tag v-if="running" size="small" type="warning" effect="plain">处理中</el-tag>
          </div>
          <div class="card-head-actions">
            <el-button v-if="resultUrl" link type="primary" @click="downloadResult">下载结果视频</el-button>
          </div>
        </div>
      </template>
      <div v-if="running" class="progress-box">
        <div>处理中 {{ processed }}/{{ total || '?' }}</div>
        <el-progress :percentage="percent" :stroke-width="16" />
      </div>
      <el-empty v-else-if="!resultUrl" description="完成配置并点击「开始检测」后，结果将显示在此处" />
      <div v-else>
        <video :src="resultUrl" controls class="player" />
        <div class="stats">
          <el-tag :type="dutyTagType(stats.dutyStatus)" effect="dark">状态 {{ dutyStatusZh(stats.dutyStatus) }}</el-tag>
          <el-tag type="warning">{{ awayTimeLabel(stats.dutyStatus, stats.awaySeconds) }}</el-tag>
          <el-tag>事件 {{ stats.eventCount || 0 }}</el-tag>
          <el-tag
            v-for="z in (stats.zones || [])"
            :key="z.zoneId || z.zoneName"
            :type="dutyTagType(z.dutyStatus)"
            size="small"
          >
            {{ z.zoneName || z.zoneId }} {{ dutyStatusZh(z.dutyStatus) }}
          </el-tag>
        </div>
        <el-table :data="stats.events || []" size="small" border class="evt-table">
          <el-table-column prop="time" label="时间" width="160" />
          <el-table-column label="工位" width="100">
            <template #default="{ row }">{{ row.zoneName || '-' }}</template>
          </el-table-column>
          <el-table-column label="事件" width="100">
            <template #default="{ row }">{{ dutyEventZh(row.event) }}</template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">{{ dutyStatusZh(row.dutyStatus) }}</template>
          </el-table-column>
          <el-table-column label="离岗时长" width="100">
            <template #default="{ row }">{{ formatAwaySec(row.awaySeconds) }}</template>
          </el-table-column>
          <el-table-column prop="staffName" label="人员" />
          <el-table-column prop="detail" label="说明" />
        </el-table>
      </div>
    </el-card>

    <el-card v-if="mode !== 'file'" shadow="never" class="res-card">
      <template #header>
        <div class="card-head">
          <div class="card-head-left">
            <span class="card-title">实时画面与结果</span>
            <span v-if="zoneMode !== 'none'" class="hint-inline">在画面上点击可绘制工位区</span>
          </div>
          <div class="card-head-actions">
            <template v-if="zoneMode === 'single'">
              <el-button v-if="camRegionPts.length >= 3 && !camRegion" link type="success" @click="finishCamRegion">闭合区域</el-button>
              <el-button v-if="camRegion" link type="primary" @click="clearCamRegion">清除区域</el-button>
            </template>
            <template v-if="zoneMode === 'multi'">
              <el-button link type="success" :disabled="draftPts.length < 3" @click="finishDraftZone">闭合并添加工位</el-button>
              <el-button link type="warning" :disabled="!draftPts.length" @click="undoDraftPoint">撤销点</el-button>
              <el-button link type="primary" :disabled="!draftPts.length" @click="clearDraft">清除草稿</el-button>
            </template>
            <el-button v-if="previewOpen && !camRunning" link type="danger" @click="closePreview">关闭预览</el-button>
            <el-button link type="primary" :disabled="!sessionId" @click="exportCsv">导出事件</el-button>
          </div>
        </div>
      </template>
      <div class="cam-stage">
        <video v-show="mode === 'local'" ref="camVideo" class="cam-media" muted playsinline autoplay />
        <img
          v-show="mode === 'network'"
          ref="streamImg"
          class="cam-media"
          alt="stream"
          @load="onStreamLoad"
          @error="onStreamError"
        />
        <canvas ref="camCanvas" class="cam-overlay" @click="onCamClick" />
        <div v-if="!previewOpen && !camRunning" class="preview-placeholder">
          <template v-if="mode === 'local'">选择「本地摄像头」后将自动申请权限并预览画面；若浏览器弹出权限提示请允许</template>
          <template v-else>请选择网络摄像头；选择后自动预览画面，再点「开始检测」</template>
        </div>
        <div class="hud">
          <el-tag v-if="previewOpen && !camRunning" type="success" effect="plain">预览中</el-tag>
          <el-tag :type="dutyTagType(dutyStatus)" effect="dark">{{ liveStatusLabel }}</el-tag>
          <el-tag type="info">{{ awayTimeLabel(dutyStatus, awaySeconds) }}</el-tag>
          <el-tag v-if="streamStatus === 'reconnect'" type="warning">重连中…</el-tag>
          <el-tag v-if="matchedLabel" type="success">{{ matchedLabel }}</el-tag>
          <el-tag
            v-for="z in liveZones"
            :key="z.zoneId || z.zoneName"
            :type="dutyTagType(z.dutyStatus)"
            size="small"
            effect="plain"
          >
            {{ z.zoneName || z.zoneId }} {{ dutyStatusZh(z.dutyStatus) }}
            <template v-if="z.alertActive"> ·告警</template>
          </el-tag>
          <span class="fps">{{ camFps.toFixed(1) }} FPS</span>
        </div>
      </div>
      <el-table :data="liveEvents" size="small" border class="evt-table">
        <el-table-column prop="time" label="时间" width="160" />
        <el-table-column label="工位" width="100">
          <template #default="{ row }">{{ row.zoneName || '-' }}</template>
        </el-table-column>
        <el-table-column label="事件" width="100">
          <template #default="{ row }">{{ dutyEventZh(row.event) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">{{ dutyStatusZh(row.dutyStatus) }}</template>
        </el-table-column>
        <el-table-column label="离岗时长" width="100">
          <template #default="{ row }">{{ formatAwaySec(row.awaySeconds) }}</template>
        </el-table-column>
        <el-table-column prop="staffName" label="人员" />
        <el-table-column prop="detail" label="说明" />
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { UploadFilled, QuestionFilled } from '@element-plus/icons-vue'
import { modelApi, absenceApi } from '../../../../api/ai'
import { cameraApi } from '../../../../api/camera'
import { recommendedModelId } from '../../../../utils/trackModelRecommendation'

const mode = ref('file')
const detectModels = ref([])
const faceModels = ref([])
const detectId = ref(null)
const faceModelId = ref(null)
const staffOptions = ref([])
const staffIds = ref([])
const staffLoading = ref(false)
const absenceThresholdSec = ref(30)
const faceThreshold = ref(0.4)
const conf = ref(0.25)
/** none=整帧 | single=单多边形 | multi=多工位各自名单 */
const zoneMode = ref('single')
const ZONE_PALETTE = ['#1E88E5', '#43A047', '#FB8C00', '#8E24AA', '#E53935', '#00897B']
/** 多工位闭合多边形（归一化坐标） */
const dutyZones = ref([])
/** 多工位草稿点（像素：文件画布或摄像头画布） */
const draftPts = ref([])
/** 文件模式单工位草稿点（像素，画布坐标） */
const regionPts = ref([])
/** 工位区域：蓝系粗线；人员框用荧光绿/品红，与区域色明显区分 */
const zoneBorderColor = ref('#1E88E5')
const zoneFillColor = ref('rgba(30, 136, 229, 0.20)')
const zoneBorderWidth = ref(4)
const BOX_MATCHED = '#00E676'
const BOX_UNMATCHED = '#FF00E5'

const file = ref(null)
const previewUrl = ref('')
const previewVideo = ref(null)
const previewOverlay = ref(null)
const drawCanvas = ref(null)
const seekSec = ref(0)
const durationSec = ref(0)
const previewPlaying = ref(false)
const videoReady = ref(false)
/** 右侧底图冻结的时间点（秒）；null=尚未抓取 */
const frozenAtSec = ref(null)
const running = ref(false)
const processed = ref(0)
const total = ref(0)
const resultUrl = ref('')
const stats = ref({})
let pollTimer = null
let blobUrl = ''
let overlayRaf = null
/** 冻结底图像素，只能被 captureDrawFrame 显式改写 */
let frameBaseImage = null
let initialCaptureTimer = null

const region = ref(null)
/** 单工位 region 的绘制参考时间（秒） */
const regionRefSec = ref(0)

/** ---- 镜头运动补偿：归一化空间累计仿射（行 [a,b,tx,c,d,ty]），来自 /motion-profile ---- */
const motionProfile = ref(null)
const motionLoading = ref(false)
const MAT_I = [1, 0, 0, 0, 1, 0]

const matAt = (sec) => {
  const p = motionProfile.value
  if (!p?.frames?.length) return MAT_I
  const fps = Number(p.fps) || 25
  const idx = Math.min(p.frames.length - 1, Math.max(0, Math.round((Number(sec) || 0) * fps)))
  return p.frames[idx] || MAT_I
}

const matInv = (m) => {
  const [a, b, tx, c, d, ty] = m
  const det = a * d - b * c
  if (!Number.isFinite(det) || Math.abs(det) < 1e-9) return MAT_I
  const ia = d / det
  const ib = -b / det
  const ic = -c / det
  const idd = a / det
  return [ia, ib, -(ia * tx + ib * ty), ic, idd, -(ic * tx + idd * ty)]
}

const matMul = (m, n) => [
  m[0] * n[0] + m[1] * n[3],
  m[0] * n[1] + m[1] * n[4],
  m[0] * n[2] + m[1] * n[5] + m[2],
  m[3] * n[0] + m[4] * n[3],
  m[3] * n[1] + m[4] * n[4],
  m[3] * n[2] + m[4] * n[5] + m[5],
]

/** 把参考帧 refSec 上标注的归一化多边形，映射到 curSec 帧的坐标（工位钉在画面内容上） */
const warpRegionNorm = (regionNorm, refSec, curSec) => {
  if (!regionNorm?.length || !motionProfile.value) return regionNorm
  if (Math.abs((Number(refSec) || 0) - (Number(curSec) || 0)) < 1e-3) return regionNorm
  const m = matMul(matAt(curSec), matInv(matAt(refSec)))
  return regionNorm.map((p) => [
    m[0] * p[0] + m[1] * p[1] + m[2],
    m[3] * p[0] + m[4] * p[1] + m[5],
  ])
}

const loadMotionProfile = async (f) => {
  motionProfile.value = null
  if (!f) return
  motionLoading.value = true
  try {
    const fd = new FormData()
    fd.append('file', f)
    const res = await absenceApi.motionProfile(fd)
    // 期间换了视频则丢弃过期结果
    if (file.value === f) motionProfile.value = res.data || null
  } catch {
    motionProfile.value = null
  } finally {
    motionLoading.value = false
    if (mode.value === 'file') redrawDrawCanvas()
  }
}

const clamp01 = (v) => Math.min(1, Math.max(0, Number(v) || 0))
const canCaptureFrame = computed(() => videoReady.value)

const formatClock = (sec) => {
  const s = Math.max(0, Number(sec) || 0)
  const m = Math.floor(s / 60)
  const r = Math.floor(s % 60)
  const ms = Math.floor((s % 1) * 10)
  return `${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}.${ms}`
}
const formatSeekTip = (v) => formatClock(v)

const devices = ref([])
const deviceId = ref('')
const devicesLoading = ref(false)
const cameraId = ref(null)
const managedCameras = ref([])
const camerasLoading = ref(false)
const camVideo = ref(null)
const streamImg = ref(null)
const camCanvas = ref(null)
const camRunning = ref(false)
const previewOpen = ref(false)
const camFps = ref(0)
const camRegionPts = ref([])
const camRegion = ref(null)
const dutyStatus = ref('')
const awaySeconds = ref(0)
const matchedLabel = ref('')
const liveEvents = ref([])
const liveZones = ref([])
const sessionId = ref('')
const streamStatus = ref('idle')
const streamOk = ref(true)

let camStream = null
let capCanvas = null
let camBusy = false
let camFirst = true
let frameCount = 0
let fpsTimer = null
let loopTimer = null
let reconnectTimer = null
let previewRaf = null
let streamRetries = 0
const MAX_BACKOFF_MS = 30000
/** 检测叠加：短时保持 + 平滑，避免框随推理延迟闪烁 */
const DET_HOLD_MS = 500
const DET_SMOOTH = 0.55
let heldDetections = []
let heldDetsAt = 0
let detectPaintOn = false

/** 把色值规范成 canvas 可用的 CSS 色；填充可附带透明度 */
const toCssColor = (raw, alpha) => {
  const s = String(raw || '').trim()
  if (!s) return alpha != null ? `rgba(30, 136, 229, ${alpha})` : '#1E88E5'
  if (s.startsWith('rgba(') || s.startsWith('rgb(')) return s
  let h = s.startsWith('#') ? s.slice(1) : s
  if (h.length === 3) h = h.split('').map((c) => c + c).join('')
  if (h.length === 8) {
    const a = parseInt(h.slice(6, 8), 16) / 255
    h = h.slice(0, 6)
    const r = parseInt(h.slice(0, 2), 16)
    const g = parseInt(h.slice(2, 4), 16)
    const b = parseInt(h.slice(4, 6), 16)
    return `rgba(${r}, ${g}, ${b}, ${Number.isFinite(a) ? a : (alpha ?? 1)})`
  }
  if (h.length !== 6 || alpha == null) return s.startsWith('#') ? s : `#${h}`
  const r = parseInt(h.slice(0, 2), 16)
  const g = parseInt(h.slice(2, 4), 16)
  const b = parseInt(h.slice(4, 6), 16)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

const zoneStylePayload = () => ({
  borderColor: zoneBorderColor.value,
  fillColor: zoneFillColor.value,
  borderWidth: Number(zoneBorderWidth.value) || 4,
})

const applyZoneStroke = (ctx, borderColor, fillColor) => {
  const border = borderColor || zoneBorderColor.value
  const fill = fillColor || zoneFillColor.value || toCssColor(border, 0.2)
  ctx.strokeStyle = toCssColor(border)
  ctx.fillStyle = fill
  ctx.lineWidth = Math.max(1, Number(zoneBorderWidth.value) || 4)
  ctx.lineJoin = 'round'
  ctx.lineCap = 'round'
}

const zoneModeHint = computed(() => ({
  none: '整帧判定在岗',
  single: '仅单区域内计在岗',
  multi: '每人一个工位、各自离岗告警',
}[zoneMode.value] || ''))

const alertTitle = computed(() => {
  if (zoneMode.value === 'multi') {
    return '规则：每人一个工位、各自离岗告警；工位内匹配到名单人员=在岗，连续非在岗达到阈值才告警。'
  }
  return '规则：至少一名「在岗名单」内已登记人员在画面/工位区 = 在岗；仅有陌生人或无人 ≠ 在岗。连续非在岗达到阈值才告警。'
})

const nextZoneName = () => {
  const names = new Set(dutyZones.value.map((z) => z.name))
  let n = dutyZones.value.length + 1
  while (names.has(`工位${n}`)) n += 1
  return `工位${n}`
}

const nextZoneColor = () => ZONE_PALETTE[dutyZones.value.length % ZONE_PALETTE.length]

const onZoneColorChange = (z, color) => {
  if (!z) return
  z.borderColor = color || z.borderColor
  z.fillColor = toCssColor(z.borderColor, 0.2)
  if (mode.value === 'file') redrawDrawCanvas()
}

const removeDutyZone = (i) => {
  dutyZones.value.splice(i, 1)
  if (mode.value === 'file') redrawDrawCanvas()
}

const clearDraft = () => {
  draftPts.value = []
  if (mode.value === 'file') redrawDrawCanvas()
}

const undoDraftPoint = () => {
  if (!draftPts.value.length) return
  draftPts.value.pop()
  if (mode.value === 'file') redrawDrawCanvas()
}

const finishDraftZone = () => {
  if (draftPts.value.length < 3) return
  let regionNorm = null
  if (mode.value === 'file') {
    const canvas = drawCanvas.value
    if (!canvas?.width || !canvas?.height) return
    regionNorm = draftPts.value.map((p) => [
      clamp01(p.x / canvas.width),
      clamp01(p.y / canvas.height),
    ])
  } else {
    const canvas = camCanvas.value
    if (!canvas?.width || !canvas?.height) return
    regionNorm = draftPts.value.map((p) => [
      clamp01(p.x / canvas.width),
      clamp01(p.y / canvas.height),
    ])
  }
  const border = nextZoneColor()
  dutyZones.value.push({
    id: `z${Date.now().toString(36)}${dutyZones.value.length}`,
    name: nextZoneName(),
    region: regionNorm,
    // 绘制参考帧时间：文件模式=冻结底图时刻；摄像头=0（实时无补偿）
    refSec: mode.value === 'file' ? (Number(frozenAtSec.value) || 0) : 0,
    staffIds: [...(staffIds.value || [])],
    absenceThresholdSec: Number(absenceThresholdSec.value) || 30,
    borderColor: border,
    fillColor: toCssColor(border, 0.2),
  })
  draftPts.value = []
  if (mode.value === 'file') redrawDrawCanvas()
}

const drawNormPolygon = (ctx, region, w, h, borderColor, fillColor) => {
  if (!region || region.length < 3) return
  applyZoneStroke(ctx, borderColor, fillColor)
  ctx.beginPath()
  region.forEach((p, i) => {
    const x = p[0] * w
    const y = p[1] * h
    i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)
  })
  ctx.closePath()
  ctx.fill()
  ctx.stroke()
}

const drawPixelDraft = (ctx, pts, borderColor) => {
  if (!pts?.length) return
  applyZoneStroke(ctx, borderColor)
  ctx.beginPath()
  pts.forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)))
  ctx.stroke()
  const r = Math.max(4, zoneBorderWidth.value)
  pts.forEach((p) => {
    ctx.fillStyle = toCssColor(borderColor || zoneBorderColor.value)
    ctx.beginPath()
    ctx.arc(p.x, p.y, r, 0, Math.PI * 2)
    ctx.fill()
  })
}

/**
 * 画全部工位。curSec 非空时按镜头运动把工位从各自 refSec 参考帧映射到 curSec 帧，
 * 保证工位始终标在视频内容（真实桌位）上；curSec 为空（摄像头模式）不补偿。
 */
const paintAllDutyZones = (ctx, w, h, curSec = null) => {
  dutyZones.value.forEach((z) => {
    const reg = curSec == null ? z.region : warpRegionNorm(z.region, z.refSec || 0, curSec)
    drawNormPolygon(ctx, reg, w, h, z.borderColor, z.fillColor)
    // 工位名标注
    if (reg?.length >= 1) {
      const cx = reg.reduce((s, p) => s + p[0], 0) / reg.length * w
      const cy = reg.reduce((s, p) => s + p[1], 0) / reg.length * h
      ctx.font = 'bold 13px sans-serif'
      ctx.fillStyle = toCssColor(z.borderColor)
      ctx.fillText(z.name || '', cx - 18, cy)
    }
  })
}

const buildZonesPayload = () => {
  if (zoneMode.value === 'multi' && dutyZones.value.length) {
    return dutyZones.value.map((z) => ({
      id: z.id,
      name: z.name,
      region: z.region,
      refSec: Number(z.refSec) || 0,
      staffIds: [...(z.staffIds || [])],
      absenceThresholdSec: Number(z.absenceThresholdSec) || Number(absenceThresholdSec.value) || 30,
      borderColor: z.borderColor,
      fillColor: z.fillColor,
    }))
  }
  if (zoneMode.value === 'single') {
    const reg = mode.value === 'file' ? region.value : camRegion.value
    if (reg?.length >= 3) {
      return [{
        id: 'z1',
        name: '工位1',
        region: reg,
        refSec: mode.value === 'file' ? (Number(regionRefSec.value) || 0) : 0,
        staffIds: [...(staffIds.value || [])],
        absenceThresholdSec: Number(absenceThresholdSec.value) || 30,
        borderColor: zoneBorderColor.value,
        fillColor: zoneFillColor.value,
      }]
    }
  }
  return []
}

const onZoneModeChange = async () => {
  draftPts.value = []
  regionPts.value = []
  if (zoneMode.value === 'none') {
    region.value = null
    camRegion.value = null
    camRegionPts.value = []
  }
  if (mode.value === 'file' && previewUrl.value && zoneMode.value !== 'none') {
    await nextTick()
    if (!frameBaseImage) {
      // 不 seek，直接抓当前帧；避免 seeked 回调误改底图
      await captureDrawFrame(false)
    } else {
      redrawDrawCanvas()
    }
  } else {
    paintPreviewOverlay()
  }
}

const busy = computed(() => running.value || camRunning.value)
const percent = computed(() => {
  if (!total.value) return 0
  return Math.min(100, Math.round((processed.value / total.value) * 100))
})
const canStartFile = computed(() => detectId.value && faceModelId.value && file.value && !running.value)
const canStartLive = computed(() => {
  if (!detectId.value || !faceModelId.value) return false
  if (mode.value === 'local') return !!deviceId.value
  if (mode.value === 'network') return !!cameraId.value
  return false
})

const staffLabel = (p) => `${p.name}${p.employeeNo ? ` (${p.employeeNo})` : ''}`
const cameraLabel = (c) => c.name || c.cameraName || `摄像头#${c.id}`
const dutyTagType = (s) => ({ on_duty: 'success', away: 'warning', absent: 'danger', stream_down: 'info' }[s] || 'info')

const DUTY_STATUS_ZH = {
  on_duty: '在岗',
  away: '暂离',
  absent: '离岗',
  stream_down: '信号中断',
}
const DUTY_EVENT_ZH = {
  absent: '离岗告警',
  return: '回岗',
}

const dutyStatusZh = (s) => DUTY_STATUS_ZH[s] || (s || '-')
const dutyEventZh = (e) => DUTY_EVENT_ZH[e] || (e || '-')
const formatAwaySec = (sec) => {
  const n = Number(sec)
  if (!Number.isFinite(n)) return '-'
  return `${n.toFixed(n % 1 === 0 ? 0 : 1)} 秒`
}
/** 离岗计时展示：在岗显示 0；暂离/离岗显示已累计时长 */
const awayTimeLabel = (status, sec) => {
  const n = Number(sec)
  const t = Number.isFinite(n) ? n : 0
  if (status === 'on_duty') return '离岗计时 0 秒'
  if (status === 'stream_down') return `计时暂停 ${formatAwaySec(t)}`
  if (status === 'absent') return `已离岗 ${formatAwaySec(t)}`
  if (status === 'away') return `已离岗 ${formatAwaySec(t)}`
  return `离岗计时 ${formatAwaySec(t)}`
}
const liveStatusLabel = computed(() => {
  if (dutyStatus.value) return dutyStatusZh(dutyStatus.value)
  if (camRunning.value) return '检测中'
  if (previewOpen.value) return '空闲'
  return '空闲'
})

/** 离岗场景优先：通用 COCO 检人；避开车牌/PPE/姿态等专用权重 */
const DETECT_EXCLUDE_RE = /plate|ppe|ball|tumor|pose|obb|seg|license|helmet|fire|smoke|crack|brain/i
const DETECT_PREF_KEYS = [
  'yolo26s', 'yolo26n', 'yolo11s', 'yolo11n', 'yolov8s', 'yolov8n', 'yolo26m', 'yolo11m',
]

const isBuffaloL = (m) => {
  const key = String(m.modelKey || '').toLowerCase()
  const ver = String(m.version || '').toLowerCase()
  return key.includes('buffalo-l') || key.includes('buffalo_l') || ver === 'buffalo_l'
}

const isBuffaloS = (m) => {
  const key = String(m.modelKey || '').toLowerCase()
  const ver = String(m.version || '').toLowerCase()
  return key.includes('buffalo-s') || key.includes('buffalo_s') || ver === 'buffalo_s'
}

const detectOptionLabel = (m) => {
  if (m.id === recommendedModelId(detectModels.value, 'person')) return `${m.modelName}（推荐）`
  return m.modelName
}

const faceOptionLabel = (m) => (
  m.id === recommendedModelId(faceModels.value, 'face') ? `${m.modelName}（推荐）` : m.modelName
)

const pickDefaultDetectId = (models) => {
  const general = models.filter((m) => {
    const key = String(m.modelKey || '')
    const name = String(m.modelName || '')
    return !DETECT_EXCLUDE_RE.test(key) && !DETECT_EXCLUDE_RE.test(name)
  })
  const pool = general.length ? general : models
  const recommended = recommendedModelId(pool, 'person')
  if (recommended != null) return recommended
  for (const pref of DETECT_PREF_KEYS) {
    const hit = pool.find((m) => String(m.modelKey || '').toLowerCase() === pref)
    if (hit?.filePath) return hit.id
  }
  const named = pool.find((m) => String(m.modelName || '').includes('通用检测') && m.filePath)
  if (named) return named.id
  const withWeight = pool.find((m) => m.filePath)
  return (withWeight || pool[0])?.id ?? null
}

const pickDefaultFaceId = (models) => {
  const recommended = recommendedModelId(models, 'face')
  if (recommended != null) return recommended
  const l = models.find((m) => isBuffaloL(m))
  if (l) return l.id
  const s = models.find((m) => isBuffaloS(m))
  if (s) return s.id
  return models[0]?.id ?? null
}

const loadModels = async () => {
  const res = await modelApi.list({ pageNum: 1, pageSize: 200 })
  const rows = res.data?.rows || res.data || []
  const detects = rows.filter((m) => m.library === 'ultralytics' && m.task === 'object-detection' && m.filePath && m.status === '0')
  // 推荐项靠前：通用 YOLO26s/n → 其他通用 → 其余
  detects.sort((a, b) => {
    const rank = (m) => {
      const key = String(m.modelKey || '').toLowerCase()
      const i = DETECT_PREF_KEYS.indexOf(key)
      if (i >= 0) return i
      if (DETECT_EXCLUDE_RE.test(key) || DETECT_EXCLUDE_RE.test(String(m.modelName || ''))) return 900
      if (String(m.modelName || '').includes('通用检测')) return 100
      return 500
    }
    return rank(a) - rank(b)
  })
  detectModels.value = detects

  const faces = rows.filter((m) => m.library === 'insightface' && m.status === '0')
  faces.sort((a, b) => Number(isBuffaloL(b)) - Number(isBuffaloL(a)))
  faceModels.value = faces

  if (!detectId.value && detectModels.value.length) {
    detectId.value = pickDefaultDetectId(detectModels.value)
  }
  if (!faceModelId.value && faceModels.value.length) {
    faceModelId.value = pickDefaultFaceId(faceModels.value)
  }
}

const loadStaff = async () => {
  staffLoading.value = true
  try {
    const face = faceModels.value.find((m) => m.id === faceModelId.value)
    const res = await absenceApi.staffOptions(face?.modelKey ? { modelKey: face.modelKey } : {})
    staffOptions.value = res.data?.rows || []
    // 切换人脸模型后，剔除当前模型下无底库的勾选
    const ok = new Set(staffOptions.value.map((p) => p.id))
    staffIds.value = (staffIds.value || []).filter((id) => ok.has(id))
    dutyZones.value.forEach((z) => {
      z.staffIds = (z.staffIds || []).filter((id) => ok.has(id))
    })
  } catch {
    staffOptions.value = []
  } finally {
    staffLoading.value = false
  }
}

const onFaceModelChange = async () => {
  await loadStaff()
  const face = faceModels.value.find((m) => m.id === faceModelId.value)
  if (!staffOptions.value.length) {
    ElMessage.warning(
      `「${face?.modelName || '当前人脸模型'}」下暂无已登记人员。请到「人脸识别」页用同一模型重新录入，或改选登记时使用的模型（特征空间不通用）。`,
    )
  }
}

const loadCameras = async () => {
  camerasLoading.value = true
  try {
    const res = await cameraApi.list({ pageNum: 1, pageSize: 100 })
    managedCameras.value = res.data?.rows || res.data || []
  } finally {
    camerasLoading.value = false
  }
}

const listDevices = async ({ requestPerm = false } = {}) => {
  devicesLoading.value = true
  try {
    if (!navigator.mediaDevices?.enumerateDevices) {
      devices.value = []
      return
    }
    // 未授权时 label 为空，会显示成「摄像头 1/2」；先申请权限再枚举以拿到真实名称
    if (requestPerm) {
      try {
        const tmp = await navigator.mediaDevices.getUserMedia({ video: true, audio: false })
        tmp.getTracks().forEach((t) => t.stop())
      } catch {
        /* 用户拒绝时仍可枚举，仅无不到友好名称 */
      }
    }
    const list = await navigator.mediaDevices.enumerateDevices()
    devices.value = list
      .filter((d) => d.kind === 'videoinput')
      .map((d, i) => ({
        deviceId: d.deviceId,
        label: d.label ? `${d.label}（本地）` : `本地摄像头 ${i + 1}`,
        idx: i + 1,
      }))
    if (!deviceId.value && devices.value.length) {
      deviceId.value = devices.value[0].deviceId
    } else if (deviceId.value && !devices.value.some((d) => d.deviceId === deviceId.value)) {
      deviceId.value = devices.value[0]?.deviceId || ''
    }
  } catch {
    devices.value = []
  } finally {
    devicesLoading.value = false
  }
}

const refreshLocalDevices = async () => {
  await listDevices({ requestPerm: true })
  if (mode.value === 'local' && !camRunning.value) {
    await openLocalPreview()
  }
}

const stopMediaTracks = () => {
  if (camStream) {
    camStream.getTracks().forEach((t) => t.stop())
    camStream = null
  }
  if (camVideo.value) camVideo.value.srcObject = null
}

const openLocalPreview = async () => {
  if (mode.value !== 'local') return
  await nextTick()
  const video = camVideo.value
  if (!video) return
  stopPreviewPaint()
  stopMediaTracks()
  previewOpen.value = false
  try {
    const constraints = {
      video: deviceId.value
        ? { deviceId: { exact: deviceId.value }, width: { ideal: 1280 }, height: { ideal: 720 } }
        : { width: { ideal: 1280 }, height: { ideal: 720 } },
      audio: false,
    }
    camStream = await navigator.mediaDevices.getUserMedia(constraints)
    // 切换模式后丢弃过期打开结果
    if (mode.value !== 'local') {
      camStream.getTracks().forEach((t) => t.stop())
      camStream = null
      return
    }
    video.srcObject = camStream
    await video.play()
    await waitVideo(video)
    if (mode.value !== 'local') {
      stopMediaTracks()
      return
    }
    previewOpen.value = true
    streamStatus.value = 'live'
    resizeCanvas()
    startPreviewPaint()
    // 拿到权限后再刷一次设备名（避免「摄像头 1/2」占位）
    await listDevices({ requestPerm: false })
  } catch (e) {
    previewOpen.value = false
    stopPreviewPaint()
    ElMessage.error(e?.name === 'NotAllowedError' || /permission/i.test(e?.message || '')
      ? '无法访问本地摄像头，请允许浏览器摄像头权限后重试'
      : (e.message || '无法打开本地摄像头'))
  }
}

const drawRegionGuide = (ctx, w, h) => {
  if (zoneMode.value === 'multi') {
    paintAllDutyZones(ctx, w, h)
    drawPixelDraft(ctx, draftPts.value, nextZoneColor())
    return
  }
  if (zoneMode.value !== 'single') return
  if (camRegion.value?.length >= 3) {
    drawNormPolygon(ctx, camRegion.value, w, h, zoneBorderColor.value, zoneFillColor.value)
  } else if (camRegionPts.value.length) {
    drawPixelDraft(ctx, camRegionPts.value, zoneBorderColor.value)
  }
}

const drawPreviewFrame = () => {
  const canvas = camCanvas.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  if (mode.value === 'local') {
    const video = camVideo.value
    if (!video || !video.videoWidth) return
    if (canvas.width !== video.videoWidth || canvas.height !== video.videoHeight) {
      canvas.width = video.videoWidth
      canvas.height = video.videoHeight
    }
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height)
  } else {
    const img = streamImg.value
    if (!img?.naturalWidth) return
    if (canvas.width !== img.naturalWidth || canvas.height !== img.naturalHeight) {
      canvas.width = img.naturalWidth
      canvas.height = img.naturalHeight
    }
    ctx.drawImage(img, 0, 0)
  }
  drawRegionGuide(ctx, canvas.width, canvas.height)
}

const stopPreviewPaint = () => {
  if (previewRaf) {
    cancelAnimationFrame(previewRaf)
    previewRaf = null
  }
  detectPaintOn = false
}

const startPreviewPaint = () => {
  stopPreviewPaint()
  const tick = () => {
    if (!previewOpen.value || camRunning.value) {
      previewRaf = null
      return
    }
    drawPreviewFrame()
    previewRaf = requestAnimationFrame(tick)
  }
  previewRaf = requestAnimationFrame(tick)
}

/** 检测中：透明 canvas 只画区域/检测框，底层 video/img 持续出画，避免每帧清空闪烁 */
const startDetectPaint = () => {
  stopPreviewPaint()
  detectPaintOn = true
  const tick = () => {
    if (!camRunning.value || !detectPaintOn) {
      previewRaf = null
      return
    }
    paintLiveOverlay()
    previewRaf = requestAnimationFrame(tick)
  }
  previewRaf = requestAnimationFrame(tick)
}

const clearHeldDetections = () => {
  heldDetections = []
  heldDetsAt = 0
}

/** 后端 bbox 基于 capCanvas 送检尺寸；叠加层为摄像头全分辨率，需比例映射 */
const scaleDetectionsToCanvas = (list) => {
  const canvas = camCanvas.value
  if (!canvas?.width || !capCanvas?.width || !Array.isArray(list)) return list || []
  const sx = canvas.width / capCanvas.width
  const sy = canvas.height / capCanvas.height
  if (Math.abs(sx - 1) < 1e-3 && Math.abs(sy - 1) < 1e-3) return list
  return list.map((d) => {
    const box = d.bbox
    if (!box || box.length < 4) return d
    return {
      ...d,
      bbox: [box[0] * sx, box[1] * sy, box[2] * sx, box[3] * sy],
    }
  })
}

const mergeDetections = (incoming) => {
  const now = Date.now()
  const list = scaleDetectionsToCanvas(Array.isArray(incoming) ? incoming : [])
  const smoothed = list.map((d) => {
    const tid = d.trackId
    const prev = tid != null ? heldDetections.find((p) => p.trackId === tid) : null
    if (!prev?.bbox || !d.bbox || d.bbox.length < 4 || prev.bbox.length < 4) {
      return { ...d, _at: now }
    }
    const bbox = d.bbox.map((v, i) => prev.bbox[i] * (1 - DET_SMOOTH) + Number(v) * DET_SMOOTH)
    return { ...d, bbox, _at: now }
  })
  const seen = new Set(smoothed.map((d) => d.trackId).filter((t) => t != null))
  for (const prev of heldDetections) {
    if (prev.trackId == null || seen.has(prev.trackId)) continue
    if (now - (prev._at || heldDetsAt) < DET_HOLD_MS) {
      smoothed.push({ ...prev, _held: true })
    }
  }
  heldDetections = smoothed
  heldDetsAt = now
  return heldDetections
}

const paintLiveOverlay = () => {
  const canvas = camCanvas.value
  if (!canvas || !canvas.width) return
  const ctx = canvas.getContext('2d')
  const w = canvas.width
  const h = canvas.height
  ctx.clearRect(0, 0, w, h)

  // 网络流：img 可能与 canvas 叠放，仍补一帧底图以免透明空隙；本地靠底层 <video>
  if (mode.value === 'network') {
    const img = streamImg.value
    if (img?.naturalWidth) {
      try { ctx.drawImage(img, 0, 0, w, h) } catch { /* */ }
    }
  }

  if (zoneMode.value === 'multi') {
    paintAllDutyZones(ctx, w, h)
    drawPixelDraft(ctx, draftPts.value, nextZoneColor())
  } else if (zoneMode.value === 'single') {
    if (camRegion.value?.length >= 3) {
      drawNormPolygon(ctx, camRegion.value, w, h, zoneBorderColor.value, zoneFillColor.value)
    } else if (camRegionPts.value.length) {
      drawPixelDraft(ctx, camRegionPts.value, zoneBorderColor.value)
    }
  }

  const now = Date.now()
  const dets = heldDetections.filter((d) => now - (d._at || heldDetsAt) < DET_HOLD_MS + 80)
  dets.forEach((d) => {
    const [x1, y1, x2, y2] = d.bbox || []
    if (x2 == null) return
    const stroke = d.faceMatched ? BOX_MATCHED : BOX_UNMATCHED
    ctx.strokeStyle = stroke
    ctx.lineWidth = 3
    ctx.lineJoin = 'round'
    ctx.globalAlpha = d._held ? 0.75 : 1
    ctx.strokeRect(x1, y1, x2 - x1, y2 - y1)
    const cls = d.className === 'person' ? '人员' : d.className
    const label = [d.trackId != null ? `ID${d.trackId}` : '', d.personName || cls || '人员'].filter(Boolean).join(' ')
    if (label) {
      ctx.font = 'bold 13px sans-serif'
      const tw = ctx.measureText(label).width + 10
      ctx.fillStyle = stroke
      ctx.fillRect(x1, Math.max(0, y1 - 20), tw, 20)
      ctx.fillStyle = '#fff'
      ctx.fillText(label, x1 + 5, Math.max(14, y1 - 5))
    }
    ctx.globalAlpha = 1
  })
}

const closePreview = () => {
  if (camRunning.value) return
  stopDetectLoopOnly()
  stopPreviewPaint()
  stopMediaTracks()
  if (streamImg.value) streamImg.value.removeAttribute('src')
  previewOpen.value = false
  streamStatus.value = 'idle'
  const canvas = camCanvas.value
  if (canvas) {
    const ctx = canvas.getContext('2d')
    ctx.clearRect(0, 0, canvas.width, canvas.height)
  }
}

const onLocalDeviceChange = async () => {
  if (camRunning.value) return
  await openLocalPreview()
}

const onNetworkCameraChange = async () => {
  if (camRunning.value) return
  if (!cameraId.value) {
    closePreview()
    return
  }
  await openNetworkPreview()
}

const openNetworkPreview = async () => {
  if (mode.value !== 'network' || !cameraId.value) return
  await nextTick()
  stopMediaTracks()
  setStreamSrc(true)
  try {
    await waitImg(streamImg.value)
    previewOpen.value = true
    streamOk.value = true
    streamStatus.value = 'live'
    resizeCanvas()
    startPreviewPaint()
  } catch {
    previewOpen.value = false
    streamOk.value = false
    stopPreviewPaint()
    ElMessage.warning('网络摄像头预览失败，请检查摄像头管理中的源')
  }
}

const onModeChange = async () => {
  await camStop(true)
  clearAllResult()
  draftPts.value = []
  liveZones.value = []
  if (mode.value === 'local') {
    await listDevices({ requestPerm: true })
    await openLocalPreview()
  } else if (mode.value === 'network') {
    await loadCameras()
    if (cameraId.value) await openNetworkPreview()
  }
}

const appendCommon = (fd) => {
  fd.append('detectId', String(detectId.value))
  fd.append('faceModelId', String(faceModelId.value))
  fd.append('staffIds', JSON.stringify(staffIds.value || []))
  fd.append('absenceThresholdSec', String(absenceThresholdSec.value))
  fd.append('faceThreshold', String(faceThreshold.value))
  fd.append('conf', String(conf.value))
  fd.append('imgsz', '640')
  const zones = buildZonesPayload()
  if (zones.length) {
    fd.append('zones', JSON.stringify(zones))
    fd.append('region', JSON.stringify(zones[0].region))
    fd.append('zoneStyle', JSON.stringify(zoneStylePayload()))
  } else {
    const reg = mode.value === 'file' ? region.value : camRegion.value
    if (zoneMode.value === 'single' && reg) {
      fd.append('region', JSON.stringify(reg))
      fd.append('zoneStyle', JSON.stringify(zoneStylePayload()))
    }
  }
}

const onPick = async (uploadFile) => {
  file.value = uploadFile.raw
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = URL.createObjectURL(file.value)
  region.value = null
  regionRefSec.value = 0
  regionPts.value = []
  draftPts.value = []
  seekSec.value = 0
  durationSec.value = 0
  previewPlaying.value = false
  videoReady.value = false
  frozenAtSec.value = null
  frameBaseImage = null
  if (initialCaptureTimer) {
    clearTimeout(initialCaptureTimer)
    initialCaptureTimer = null
  }
  // 后台估计整段镜头运动，用于把工位钉在画面内容上（预览与检测共用同一模型）
  loadMotionProfile(file.value)
  await nextTick()
}

const onPreviewMeta = async () => {
  const v = previewVideo.value
  if (!v) return
  durationSec.value = Number.isFinite(v.duration) ? v.duration : 0
  videoReady.value = !!v.videoWidth
  if (zoneMode.value === 'none') return
  await nextTick()
  // 首次：seek 到清晰帧后延迟抓一次底图。之后任何 seek 都不再自动抓。
  const t = durationSec.value > 0.3 ? 0.2 : 0
  seekSec.value = t
  try {
    v.pause()
    previewPlaying.value = false
    v.currentTime = t
  } catch { /* */ }
  if (initialCaptureTimer) clearTimeout(initialCaptureTimer)
  initialCaptureTimer = setTimeout(async () => {
    initialCaptureTimer = null
    // 仅当还没有冻结底图时自动抓一次，避免覆盖用户已画内容时的底图时间点以外的重复抓取
    if (!frameBaseImage) await captureDrawFrame(false)
  }, 400)
  paintPreviewOverlay()
}

const seekPreviewTo = (t) => {
  const v = previewVideo.value
  if (!v) return
  const sec = Math.min(Math.max(0, Number(t) || 0), durationSec.value || 0)
  seekSec.value = sec
  try {
    v.pause()
    previewPlaying.value = false
  } catch { /* */ }
  // 只改左侧视频时间；禁止在此处或 seeked 里调用 captureDrawFrame
  v.currentTime = sec
}

const togglePreviewPlay = async () => {
  const v = previewVideo.value
  if (!v) return
  try {
    if (v.paused) {
      await v.play()
      previewPlaying.value = true
    } else {
      v.pause()
      previewPlaying.value = false
    }
  } catch {
    previewPlaying.value = !v.paused
  }
}

/** seeked：只同步时间显示与左侧叠加层，绝不抓帧/重绘右侧底图 */
const onPreviewSeeked = () => {
  const v = previewVideo.value
  if (v) seekSec.value = v.currentTime || 0
  paintPreviewOverlay()
}

const onPreviewTimeUpdate = () => {
  const v = previewVideo.value
  if (!v) return
  if (!v.paused) seekSec.value = v.currentTime || 0
  paintPreviewOverlay()
}

/**
 * 显式冻结左侧当前帧到右侧画布。
 * @param {boolean} fromUser 用户点击按钮时为 true（提示成功）
 */
const captureDrawFrame = async (fromUser = false) => {
  if (zoneMode.value === 'none') return
  const v = previewVideo.value
  await nextTick()
  const canvas = drawCanvas.value
  if (!v || !canvas || !v.videoWidth) {
    if (fromUser) ElMessage.warning('视频尚未就绪，请稍候再抓取底图')
    return
  }
  // 与车辆追踪一致：画布最大宽 640，坐标按画布归一化
  const dispW = Math.min(640, v.videoWidth)
  const scale = dispW / v.videoWidth
  canvas.width = dispW
  canvas.height = Math.round(v.videoHeight * scale)
  const ctx = canvas.getContext('2d')
  try {
    ctx.drawImage(v, 0, 0, canvas.width, canvas.height)
  } catch (e) {
    if (fromUser) ElMessage.error('抓取底图失败，请暂停后重试')
    return
  }
  // 深拷贝像素，后续左侧 seek 无法影响这份数据
  frameBaseImage = ctx.getImageData(0, 0, canvas.width, canvas.height)
  frozenAtSec.value = Number(v.currentTime) || 0
  redrawDrawCanvas()
  if (fromUser) {
    ElMessage.success(`已冻结底图（${formatClock(frozenAtSec.value)}），拖定位条不会再改右侧`)
  }
}

/**
 * 左侧预览叠加层：把已闭合的工位（归一化坐标）实时画在视频上方。
 * 工位固定于画面坐标，拖动定位/播放时叠加框不动，用户可直观校验。
 */
const paintPreviewOverlay = () => {
  const c = previewOverlay.value
  if (!c) return
  const v = previewVideo.value
  const elW = v?.clientWidth || 0
  const elH = v?.clientHeight || 0
  const ctx = c.getContext('2d')
  if (!v?.videoWidth || !elW || !elH || zoneMode.value === 'none') {
    c.width = Math.max(1, elW)
    c.height = Math.max(1, elH)
    ctx.clearRect(0, 0, c.width, c.height)
    return
  }
  if (c.width !== elW || c.height !== elH) {
    c.width = elW
    c.height = elH
  }
  ctx.clearRect(0, 0, elW, elH)
  // video 默认 object-fit: contain，内容区可能有黑边，需按内容区映射
  const scale = Math.min(elW / v.videoWidth, elH / v.videoHeight)
  const cw = v.videoWidth * scale
  const ch = v.videoHeight * scale
  ctx.save()
  ctx.translate((elW - cw) / 2, (elH - ch) / 2)
  // 只在视频内容区内绘制，出画幅的工位部分不画到黑边上
  ctx.beginPath()
  ctx.rect(0, 0, cw, ch)
  ctx.clip()
  const curSec = Number(v.currentTime) || 0
  if (zoneMode.value === 'multi') {
    paintAllDutyZones(ctx, cw, ch, curSec)
  } else if (region.value?.length >= 3) {
    const reg = warpRegionNorm(region.value, regionRefSec.value, curSec)
    drawNormPolygon(ctx, reg, cw, ch, zoneBorderColor.value, zoneFillColor.value)
  }
  ctx.restore()
}

const redrawDrawCanvas = () => {
  const canvas = drawCanvas.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  if (frameBaseImage) {
    // 尺寸被改过时重新铺底
    if (frameBaseImage.width !== canvas.width || frameBaseImage.height !== canvas.height) {
      canvas.width = frameBaseImage.width
      canvas.height = frameBaseImage.height
    }
    ctx.putImageData(frameBaseImage, 0, 0)
  } else {
    ctx.clearRect(0, 0, canvas.width, canvas.height)
  }
  const w = canvas.width
  const h = canvas.height
  // 右侧底图冻结于 frozenAtSec：工位按该时刻做镜头运动补偿，与底图内容对齐
  const baseSec = frozenAtSec.value != null ? Number(frozenAtSec.value) : null
  if (zoneMode.value === 'multi') {
    paintAllDutyZones(ctx, w, h, baseSec)
    drawPixelDraft(ctx, draftPts.value, nextZoneColor())
  } else if (zoneMode.value === 'single') {
    if (region.value?.length >= 3) {
      const reg = baseSec == null
        ? region.value
        : warpRegionNorm(region.value, regionRefSec.value, baseSec)
      drawNormPolygon(ctx, reg, w, h, zoneBorderColor.value, zoneFillColor.value)
    } else if (regionPts.value.length) {
      drawPixelDraft(ctx, regionPts.value, zoneBorderColor.value)
    }
  }
  paintPreviewOverlay()
}

const onDrawCanvasClick = async (e) => {
  if (zoneMode.value === 'none') return
  let canvas = drawCanvas.value
  if (!canvas?.width || !frameBaseImage) {
    // 底图缺失时自动抓当前帧兜底，避免「点了没反应」
    await captureDrawFrame(false)
    canvas = drawCanvas.value
    if (!canvas?.width || !frameBaseImage) {
      ElMessage.warning('视频尚未就绪，请点击左侧「用当前帧作底图」后再画工位')
      return
    }
  }
  const rect = canvas.getBoundingClientRect()
  if (!rect.width || !rect.height) return
  const x = ((e.clientX - rect.left) / rect.width) * canvas.width
  const y = ((e.clientY - rect.top) / rect.height) * canvas.height
  if (zoneMode.value === 'multi') {
    draftPts.value.push({ x, y })
    redrawDrawCanvas()
    return
  }
  regionPts.value.push({ x, y })
  region.value = null
  redrawDrawCanvas()
}

const finishRegion = () => {
  const canvas = drawCanvas.value
  if (regionPts.value.length < 3 || !canvas?.width) return
  region.value = regionPts.value.map((p) => [
    clamp01(p.x / canvas.width),
    clamp01(p.y / canvas.height),
  ])
  regionRefSec.value = Number(frozenAtSec.value) || 0
  regionPts.value = []
  redrawDrawCanvas()
}
const clearRegion = () => {
  regionPts.value = []
  region.value = null
  redrawDrawCanvas()
}

const clearAllResult = () => {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = null
  if (blobUrl) URL.revokeObjectURL(blobUrl)
  blobUrl = ''
  resultUrl.value = ''
  stats.value = {}
  processed.value = 0
  total.value = 0
}

const validateZonesBeforeStart = () => {
  if (zoneMode.value === 'single' && !region.value && mode.value === 'file') {
    ElMessage.warning('请先闭合工位区域，或将工位模式改为「整帧」')
    return false
  }
  if (zoneMode.value === 'multi') {
    if (!dutyZones.value.length) {
      ElMessage.warning('多工位模式请至少闭合添加工位 1 个')
      return false
    }
    const ok = dutyZones.value.some((z) => (z.staffIds || []).length > 0)
    if (!ok) {
      ElMessage.warning('请为至少一个工位选择在岗人员')
      return false
    }
  }
  return true
}

const runVideo = async () => {
  if (!validateZonesBeforeStart()) return
  clearAllResult()
  running.value = true
  try {
    const fd = new FormData()
    fd.append('file', file.value)
    appendCommon(fd)
    const res = await absenceApi.trackVideo(fd)
    const jobId = res.data?.jobId
    if (!jobId) throw new Error('无 jobId')
    pollTimer = setInterval(async () => {
      try {
        const p = await absenceApi.videoProgress(jobId)
        const d = p.data || {}
        processed.value = d.processed || 0
        total.value = d.total || 0
        if (d.status === 'done') {
          clearInterval(pollTimer)
          pollTimer = null
          running.value = false
          stats.value = d.stats || {}
          const name = d.stats?.output
          if (name) {
            const blob = await absenceApi.outputVideo(name)
            blobUrl = URL.createObjectURL(blob)
            resultUrl.value = blobUrl
          }
        } else if (d.status === 'error') {
          clearInterval(pollTimer)
          pollTimer = null
          running.value = false
          ElMessage.error(d.error || '任务失败')
        }
      } catch (err) {
        clearInterval(pollTimer)
        pollTimer = null
        running.value = false
        ElMessage.error(err.message || '进度查询失败')
      }
    }, 800)
  } catch (e) {
    running.value = false
    ElMessage.error(e.message || '启动失败')
  }
}

const downloadResult = () => {
  if (!resultUrl.value) return
  const a = document.createElement('a')
  a.href = resultUrl.value
  a.download = 'absence_result.mp4'
  a.click()
}

const newSessionId = () => {
  sessionId.value = (crypto.randomUUID && crypto.randomUUID()) || `${Date.now()}-${Math.random()}`
}

const camStart = async () => {
  if (!detectId.value || !faceModelId.value) {
    ElMessage.warning('请选择人员检测模型与人脸模型')
    return
  }
  if (mode.value === 'local' && !previewOpen.value) {
    await openLocalPreview()
    if (!previewOpen.value) return
  }
  if (mode.value === 'network') {
    if (!cameraId.value) {
      ElMessage.warning('请选择网络摄像头')
      return
    }
    if (!previewOpen.value) {
      await openNetworkPreview()
      if (!previewOpen.value) return
    }
  }
  if (zoneMode.value === 'multi') {
    if (!dutyZones.value.length) {
      ElMessage.warning('多工位模式请至少闭合添加工位 1 个')
      return
    }
    if (!dutyZones.value.some((z) => (z.staffIds || []).length > 0)) {
      ElMessage.warning('请为至少一个工位选择在岗人员')
      return
    }
  } else if (zoneMode.value === 'single' && !camRegion.value) {
    ElMessage.info('可在预览画面点 ≥3 点后「闭合区域」，或将工位模式改为「整帧」')
  }
  newSessionId()
  stopPreviewPaint()
  clearHeldDetections()
  camRunning.value = true
  camFirst = true
  camBusy = false
  streamOk.value = true
  streamRetries = 0
  liveEvents.value = []
  liveZones.value = []
  dutyStatus.value = ''
  awaySeconds.value = 0
  matchedLabel.value = ''
  await nextTick()
  resizeCanvas()
  startDetectPaint()
  scheduleLoop(mode.value === 'network' ? 80 : 33)
  if (fpsTimer) clearInterval(fpsTimer)
  frameCount = 0
  fpsTimer = setInterval(() => {
    camFps.value = frameCount
    frameCount = 0
  }, 1000)
}

const stopDetectLoopOnly = () => {
  camRunning.value = false
  if (loopTimer) clearTimeout(loopTimer)
  loopTimer = null
  if (fpsTimer) clearInterval(fpsTimer)
  fpsTimer = null
  if (reconnectTimer) clearTimeout(reconnectTimer)
  reconnectTimer = null
}

const camStopDetect = async () => {
  stopDetectLoopOnly()
  detectPaintOn = false
  stopPreviewPaint()
  clearHeldDetections()
  if (sessionId.value) {
    try { await absenceApi.resetSession(sessionId.value) } catch { /* */ }
  }
  dutyStatus.value = ''
  liveZones.value = []
  // 停止检测后保留实时预览
  if (previewOpen.value) startPreviewPaint()
}

const camStop = async (full = true) => {
  stopDetectLoopOnly()
  detectPaintOn = false
  clearHeldDetections()
  if (full) {
    stopPreviewPaint()
    stopMediaTracks()
    if (streamImg.value) streamImg.value.removeAttribute('src')
    previewOpen.value = false
    streamStatus.value = 'idle'
  }
  if (sessionId.value) {
    try { await absenceApi.resetSession(sessionId.value) } catch { /* */ }
  }
}

const waitVideo = (v) => new Promise((resolve, reject) => {
  const t = setTimeout(() => reject(new Error('视频超时')), 8000)
  const check = () => {
    if (v.videoWidth > 0) {
      clearTimeout(t)
      resolve()
    } else requestAnimationFrame(check)
  }
  check()
})

const waitImg = (img) => new Promise((resolve, reject) => {
  const t = setTimeout(() => reject(new Error('拉流超时')), 12000)
  const tick = () => {
    if (img.naturalWidth > 0) {
      clearTimeout(t)
      resolve()
    } else setTimeout(tick, 50)
  }
  tick()
})

const setStreamSrc = (force = false) => {
  if (!cameraId.value || !streamImg.value) return
  const bust = force || streamRetries > 0 ? String(Date.now()) : ''
  streamImg.value.src = cameraApi.streamUrl(cameraId.value, bust, false, true)
  streamStatus.value = streamRetries > 0 ? 'reconnect' : 'live'
}

const scheduleReconnect = () => {
  if (!camRunning.value || mode.value !== 'network') return
  if (reconnectTimer) clearTimeout(reconnectTimer)
  const delay = Math.min(1000 * (2 ** Math.min(streamRetries, 4)), MAX_BACKOFF_MS)
  streamStatus.value = 'reconnect'
  reconnectTimer = setTimeout(() => {
    if (!camRunning.value) return
    streamRetries += 1
    setStreamSrc(true)
  }, delay)
}

const onStreamLoad = () => {
  streamStatus.value = 'live'
  streamRetries = 0
  streamOk.value = true
  if (reconnectTimer) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
}

const onStreamError = () => {
  streamOk.value = false
  streamStatus.value = 'error'
  if (camRunning.value) scheduleReconnect()
}

const resizeCanvas = () => {
  const canvas = camCanvas.value
  const src = mode.value === 'local' ? camVideo.value : streamImg.value
  if (!canvas || !src) return
  const w = mode.value === 'local' ? src.videoWidth : src.naturalWidth
  const h = mode.value === 'local' ? src.videoHeight : src.naturalHeight
  if (!w || !h) return
  // 仅尺寸变化时赋值，否则会清空 canvas 导致检测框闪烁
  if (canvas.width !== w || canvas.height !== h) {
    canvas.width = w
    canvas.height = h
  }
  if (!capCanvas) capCanvas = document.createElement('canvas')
  const maxW = 640
  const scale = Math.min(1, maxW / w)
  const cw = Math.round(w * scale)
  const ch = Math.round(h * scale)
  if (capCanvas.width !== cw || capCanvas.height !== ch) {
    capCanvas.width = cw
    capCanvas.height = ch
  }
}

const scheduleLoop = (delay) => {
  if (loopTimer) clearTimeout(loopTimer)
  loopTimer = setTimeout(loopOnce, delay)
}

const loopOnce = async () => {
  if (!camRunning.value) return
  if (camBusy) {
    scheduleLoop(mode.value === 'network' ? 80 : 33)
    return
  }
  const src = mode.value === 'local' ? camVideo.value : streamImg.value
  const canvas = camCanvas.value
  if (!src || !canvas || !capCanvas) {
    scheduleLoop(80)
    return
  }
  if (mode.value === 'network' && (!streamImg.value.naturalWidth || !streamOk.value)) {
    // 断流：仍上报 streamOk=0 推进状态机暂停
    if (!streamOk.value) {
      try {
        camBusy = true
        const blank = document.createElement('canvas')
        blank.width = 16
        blank.height = 16
        const blob = await new Promise((r) => blank.toBlob(r, 'image/jpeg', 0.5))
        if (blob) await postFrame(blob, true)
      } catch { /* ignore */ }
      finally { camBusy = false }
    }
    scheduleLoop(200)
    return
  }
  resizeCanvas()
  const ctx = capCanvas.getContext('2d')
  ctx.drawImage(src, 0, 0, capCanvas.width, capCanvas.height)
  camBusy = true
  try {
    const blob = await new Promise((r) => capCanvas.toBlob(r, 'image/jpeg', 0.6))
    if (blob) await postFrame(blob, false)
    frameCount += 1
  } catch { /* ignore single frame */ }
  finally { camBusy = false }
  scheduleLoop(mode.value === 'network' ? 80 : 33)
}

const postFrame = async (blob, isStreamDown) => {
  const fd = new FormData()
  fd.append('file', blob, 'frame.jpg')
  appendCommon(fd)
  fd.append('sessionId', sessionId.value)
  fd.append('reset', camFirst ? '1' : '0')
  fd.append('streamOk', isStreamDown || !streamOk.value ? '0' : '1')
  camFirst = false
  const res = await absenceApi.trackFrame(fd)
  if (!camRunning.value) return
  const data = res.data || {}
  dutyStatus.value = data.dutyStatus || ''
  awaySeconds.value = data.awaySeconds || 0
  matchedLabel.value = (data.matchedStaff || []).map((s) => s.name).join(', ')
  liveEvents.value = data.events || []
  liveZones.value = data.zones || []
  mergeDetections(data.detections || [])
  // 由 rAF 持续绘制；此处立即补一帧，降低首包延迟
  if (!detectPaintOn) startDetectPaint()
  else paintLiveOverlay()
}

const onCamClick = (e) => {
  // 预览或检测中均可绘制工位区
  if (zoneMode.value === 'none' || (!previewOpen.value && !camRunning.value)) return
  const canvas = camCanvas.value
  if (!canvas) return
  const rect = canvas.getBoundingClientRect()
  const x = ((e.clientX - rect.left) / rect.width) * canvas.width
  const y = ((e.clientY - rect.top) / rect.height) * canvas.height
  if (zoneMode.value === 'multi') {
    draftPts.value.push({ x, y })
    return
  }
  if (camRegion.value) return
  camRegionPts.value.push({ x, y })
}

const finishCamRegion = () => {
  const canvas = camCanvas.value
  if (!canvas || camRegionPts.value.length < 3) return
  camRegion.value = camRegionPts.value.map((p) => [p.x / canvas.width, p.y / canvas.height])
}
const clearCamRegion = () => {
  camRegionPts.value = []
  camRegion.value = null
}

const exportCsv = async () => {
  if (!sessionId.value) return
  try {
    const res = await absenceApi.exportEvents(sessionId.value)
    const csv = res.data?.csv || ''
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = 'absence_events.csv'
    a.click()
  } catch (e) {
    ElMessage.error(e.message || '导出失败')
  }
}

onMounted(async () => {
  await loadModels()
  await loadStaff()
  await loadCameras()
  if (mode.value === 'local') {
    await listDevices({ requestPerm: true })
    if (deviceId.value) await openLocalPreview()
  } else {
    await listDevices()
  }
})

watch([zoneBorderColor, zoneFillColor, zoneBorderWidth], () => {
  if (mode.value === 'file' && zoneMode.value !== 'none') redrawDrawCanvas()
})

watch(
  () => dutyZones.value.map((z) => `${z.id}|${z.name}|${z.borderColor}|${z.fillColor}`).join(';'),
  () => {
    if (mode.value === 'file' && zoneMode.value === 'multi') redrawDrawCanvas()
  },
)

onBeforeUnmount(() => {
  if (overlayRaf) cancelAnimationFrame(overlayRaf)
  overlayRaf = null
  if (initialCaptureTimer) clearTimeout(initialCaptureTimer)
  initialCaptureTimer = null
  frameBaseImage = null
  stopPreviewPaint()
  camStop(true)
  clearAllResult()
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
})
</script>

<style scoped>
.absence-page { display: flex; flex-direction: column; gap: 12px; }
.cfg-card, .draw-card, .res-card { border-radius: 8px; }

/* 卡片头：标题 + 状态 + 主操作 */
.card-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.card-head-left { display: flex; align-items: center; gap: 8px; min-width: 0; }
.card-head-actions { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; }
.card-title { font-size: 15px; font-weight: 650; color: #2c3e57; }
.card-help { color: #a0aec0; cursor: help; font-size: 16px; }
.card-help:hover { color: #409eff; }
.help-pop { max-width: 340px; line-height: 1.6; }
.help-pop p { margin: 0 0 6px; }
.help-pop p:last-child { margin-bottom: 0; }

/* 配置表单：分组 + 顶部标签 */
.cfg-form :deep(.el-form-item) { margin-bottom: 10px; }
.cfg-form :deep(.el-form-item__label) { padding-bottom: 4px; font-size: 12px; color: #7a8aa5; line-height: 1.4; }
.cfg-form :deep(.el-select), .cfg-form :deep(.el-input) { width: 100%; }
.cfg-section { margin-bottom: 6px; }
.cfg-section-title {
  font-size: 12px; font-weight: 600; color: #a5b1c5; letter-spacing: 2px;
  margin-bottom: 6px; padding-left: 8px; border-left: 3px solid #409eff; line-height: 1.2;
}
.src-pick { display: flex; align-items: center; gap: 8px; width: 100%; }
.src-pick .el-select { flex: 1; }
.file-name {
  flex: 1; min-width: 0; font-size: 13px; color: #606266;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.field-hint { font-size: 12px; color: #a5b1c5; line-height: 1.4; margin-top: 2px; }

/* 高级参数折叠 */
.adv-collapse { border: none; margin-top: 2px; }
.adv-collapse :deep(.el-collapse-item__header) {
  border: none; height: 36px; font-size: 13px; color: #606266; background: transparent;
}
.adv-collapse :deep(.el-collapse-item__wrap) { border: none; background: transparent; }
.adv-collapse :deep(.el-collapse-item__content) { padding: 8px 0 0; }
.adv-title { font-weight: 600; }
.adv-sub { margin-left: 10px; font-size: 12px; color: #a5b1c5; }

.hint-inline { margin-left: 8px; font-size: 12px; color: #909399; }
.zone-list { margin: 8px 0 12px; padding: 8px 10px; background: #fafafa; border-radius: 6px; }
.zone-list-title { font-size: 13px; font-weight: 600; margin-bottom: 8px; color: #303133; }
.zone-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 8px; }
.zone-swatch { width: 14px; height: 14px; border-radius: 3px; flex-shrink: 0; border: 1px solid rgba(0,0,0,.12); }
.seek-bar {
  display: flex; align-items: center; gap: 4px; margin: 10px 0 8px; flex-wrap: wrap;
  padding: 8px 10px; background: #f5f7fa; border-radius: 6px;
}
.seek-label { font-size: 13px; color: #606266; white-space: nowrap; }
.seek-time { font-size: 12px; color: #909399; white-space: nowrap; min-width: 110px; text-align: right; }
.capture-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin: 0 0 8px; }
.frozen-tag { margin-left: 8px; vertical-align: middle; }
.zone-fixed-tip { margin-bottom: 8px; }
.sub-title { font-weight: 600; margin-bottom: 8px; font-size: 13px; color: #303133; }
.player { width: 100%; max-height: 420px; background: #111; }
.preview-stage { position: relative; display: inline-block; width: 100%; }
.preview-stage .player { display: block; }
.preview-zone-overlay {
  position: absolute; inset: 0; width: 100%; height: 100%;
  pointer-events: none; z-index: 1;
}
.frame-canvas {
  max-width: 100%;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  cursor: crosshair;
  display: block;
  background: #111;
}
.line-tip { margin: 8px 0; font-size: 13px; color: #606266; }
.progress-box { padding: 12px 0; }
.stats { display: flex; gap: 8px; flex-wrap: wrap; margin: 10px 0; }
.evt-table { margin-top: 12px; }
.cam-stage {
  position: relative; background: #0b1220; border-radius: 8px; overflow: hidden;
  min-height: 420px; display: flex; align-items: center; justify-content: center;
}
.cam-media { width: 100%; max-height: 70vh; display: block; object-fit: contain; background: #000; }
.cam-overlay {
  position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%);
  max-width: 100%; max-height: 70vh; width: auto; height: auto;
  cursor: crosshair; z-index: 1;
  /* 透明底：检测时只画框，底层 video 连续播放，避免整帧重绘闪烁 */
  background: transparent;
}
.preview-placeholder {
  position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
  color: #94a3b8; font-size: 14px; padding: 24px; text-align: center; pointer-events: none;
}
.hud { position: absolute; left: 10px; top: 10px; display: flex; gap: 6px; align-items: center; flex-wrap: wrap; z-index: 2; }
.fps { color: #fff; font-size: 12px; margin-left: 6px; }
</style>
