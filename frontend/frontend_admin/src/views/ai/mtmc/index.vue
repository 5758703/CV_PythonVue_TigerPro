<template>
  <div class="mtmc-page">
    <header class="page-hero">
      <div>
        <div class="hero-title">跨镜重识别</div>
        <div class="hero-subtitle">多路检测、Tracklet 关联、全局身份与证据复核的一体化工作台</div>
      </div>
      <div class="hero-flow" aria-label="处理流程">
        <span>检测</span><i>→</i><span>跟踪</span><i>→</i><span>跨镜关联</span><i>→</i><span>证据复核</span>
      </div>
      <div :class="['hero-status', session?.running ? 'running' : 'idle']">
        <span class="status-dot"></span>{{ session?.running ? '跨镜会话运行中' : '当前无跨镜会话' }}
      </div>
    </header>

    <el-tabs v-model="tab" type="border-card" class="mtmc-tabs">
      <el-tab-pane label="实时检测测试" name="detect">
        <div class="tab-intro">
          <div><strong>单路检测验证</strong><span>先确认视频源和人车模型可用，再启动跨镜会话。</span></div>
          <el-tag type="success" effect="plain">不产生全局 ID</el-tag>
        </div>
        <el-alert
          type="success"
          :closable="false"
          show-icon
          class="mb"
          title="单路实时检测：仅 YOLO 人/车画框叠加，不做 Tracklet / ReID / 跨镜关联；与「会话控制」互不影响。"
        />
        <el-form :inline="true" label-width="100px" class="cfg config-panel">
          <div class="config-title"><span>① 视频源</span><small>选择一种输入方式并填写来源</small></div>
          <el-form-item label="视频源">
            <el-radio-group v-model="detectForm.sourceMode">
              <el-radio value="upload">本地视频</el-radio>
              <el-radio value="image">图片</el-radio>
              <el-radio value="stream">网络流 RTSP</el-radio>
              <el-radio value="device">本机摄像头</el-radio>
            </el-radio-group>
          </el-form-item>
          <template v-if="detectForm.sourceMode === 'upload'">
            <el-form-item label="载入方式">
              <el-radio-group v-model="uploadMode">
                <el-radio value="path">服务器路径</el-radio>
                <el-radio value="file">本地上传</el-radio>
              </el-radio-group>
            </el-form-item>
            <div v-if="uploadMode === 'path'" class="upload-slots">
              <div class="upload-slot">
                <el-input v-model="pathSlots[0].name" placeholder="名称" style="width: 140px" />
                <el-input
                  v-model="pathSlots[0].path"
                  placeholder="相对 docs/test_data，如 video/行人和车辆视频.mp4"
                  style="width: 420px"
                  clearable
                />
              </div>
              <p class="hint upload-hint">单路测试。路径相对 docs/test_data 或 uploads</p>
            </div>
            <div v-else class="upload-slots">
              <div class="upload-slot">
                <el-input v-model="uploadSlots[0].name" placeholder="名称" style="width: 140px" />
                <el-upload
                  :auto-upload="false"
                  :limit="1"
                  accept="video/*,.mp4,.avi,.mov,.mkv,.webm"
                  :on-change="(f) => onVideoPick(0, f)"
                  :on-remove="() => onVideoRemove(0)"
                  :file-list="uploadSlots[0].fileList"
                >
                  <el-button type="primary" plain>选择视频</el-button>
                </el-upload>
              </div>
            </div>
          </template>
          <template v-if="detectForm.sourceMode === 'image'">
            <div class="upload-slots">
              <div class="upload-slot">
                <el-input v-model="imageSlots[0].name" placeholder="名称" style="width: 140px" />
                <el-input v-model="imageSlots[0].path" placeholder="服务器图片路径（可选）" style="width: 280px" clearable />
                <el-upload
                  :auto-upload="false"
                  :limit="1"
                  accept="image/*,.jpg,.jpeg,.png,.bmp,.webp"
                  :on-change="(f) => onImagePick(0, f)"
                  :on-remove="() => onImageRemove(0)"
                  :file-list="imageSlots[0].fileList"
                >
                  <el-button type="primary" plain>选择图片</el-button>
                </el-upload>
              </div>
            </div>
          </template>
          <template v-if="detectForm.sourceMode === 'stream'">
            <div class="upload-slots">
              <div class="upload-slot">
                <el-input v-model="streamSlots[0].name" placeholder="名称" style="width: 140px" />
                <el-input v-model="streamSlots[0].url" placeholder="rtsp://..." style="width: 420px" clearable />
              </div>
            </div>
          </template>
          <template v-if="detectForm.sourceMode === 'device'">
            <div class="upload-slots">
              <div class="upload-slot">
                <el-input v-model="deviceSlots[0].name" placeholder="名称" style="width: 140px" />
                <el-select v-model="deviceSlots[0].device" filterable allow-create placeholder="本机采集设备" style="width: 360px">
                  <el-option v-for="d in devices" :key="d" :label="d" :value="d" />
                </el-select>
              </div>
            </div>
          </template>
          <div class="config-title"><span>② 检测目标</span><small>设置识别类型与处理频率</small></div>
          <el-form-item label="人员">
            <el-switch v-model="detectForm.enablePerson" />
          </el-form-item>
          <el-form-item label="车辆">
            <el-switch v-model="detectForm.enableVehicle" />
          </el-form-item>
          <el-form-item label="采样 FPS">
            <el-input-number v-model="detectForm.sampleFps" :min="0.5" :max="15" :step="0.5" />
            <span class="form-hint">仅控制检测频率；播放跟原视频帧率，处理落后时会丢帧保流畅</span>
          </el-form-item>
          <el-form-item class="action-bar">
            <el-button type="primary" :loading="detectBusy" v-permission="'ai:mtmc:edit'" @click="onDetectStart">启动检测</el-button>
            <el-button type="danger" :disabled="!detectSessionId" v-permission="'ai:mtmc:edit'" @click="onDetectStop">停止</el-button>
            <el-button @click="refreshSession">刷新状态</el-button>
          </el-form-item>
        </el-form>

        <el-descriptions v-if="detectSession" :column="4" border size="small" class="mb status-panel">
          <el-descriptions-item label="检测会话">{{ detectSession.sessionId }}</el-descriptions-item>
          <el-descriptions-item label="运行">{{ detectSession.running ? '是' : '否' }}</el-descriptions-item>
          <el-descriptions-item label="源">{{ sourceModeLabel(detectSession.sourceMode) }}</el-descriptions-item>
          <el-descriptions-item label="策略">纯检测（无 Tracklet）</el-descriptions-item>
          <el-descriptions-item label="帧数">{{ detectSession.stats?.frames }}</el-descriptions-item>
          <el-descriptions-item label="人员命中">{{ detectSession.stats?.persons }}</el-descriptions-item>
          <el-descriptions-item label="车辆命中">{{ detectSession.stats?.vehicles }}</el-descriptions-item>
          <el-descriptions-item label="当前检出">{{ detectCamId ? camDetCount(detectCamId, detectSession) : 0 }}</el-descriptions-item>
        </el-descriptions>

        <div v-if="detectSession?.running && detectCamId" class="detect-views">
          <div class="cell">
            <div class="cell-h">
              <span>原视频</span>
              <span class="cell-h-meta">
                <span class="fps-chip">FPS {{ formatFps(camMeta(detectCamId, detectSession).streamFps) }}</span>
              </span>
            </div>
            <img :src="detectRawSrc" class="cell-v" @error="bustDetectStream" />
          </div>
          <div class="cell">
            <div class="cell-h">
              <span>结果视频（AI 叠加）</span>
              <span class="cell-h-meta">
                <span class="fps-chip detect">检测 {{ formatFps(camMeta(detectCamId, detectSession).detectFps) }}</span>
                <span class="fps-chip">推流 {{ formatFps(camMeta(detectCamId, detectSession).streamFps) }}</span>
                · 检出 {{ camDetCount(detectCamId, detectSession) }}
                <template v-if="camMeta(detectCamId, detectSession).lastError"> · {{ camMeta(detectCamId, detectSession).lastError }}</template>
              </span>
            </div>
            <img :src="detectOverlaySrc" class="cell-v" @error="bustDetectStream" />
          </div>
        </div>
        <el-table
          v-if="detectSession?.running && detectCamId"
          :data="camDetections(detectCamId, detectSession)"
          size="small"
          border
          stripe
          class="mb"
          max-height="220"
          empty-text="本帧暂无检出"
        >
          <el-table-column label="类型" width="70">
            <template #default="{ row }">
              <el-tag size="small" :type="row.objectType === 'vehicle' ? 'warning' : 'success'" effect="plain">
                {{ row.objectType === 'vehicle' ? '车' : '人' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="label" label="标签" min-width="140" show-overflow-tooltip />
          <el-table-column label="分" width="70">
            <template #default="{ row }">{{ formatScore(row.score) }}</template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="会话控制" name="session">
        <div class="tab-intro">
          <div><strong>跨镜会话控制台</strong><span>选择摄像头、设置关联策略，并实时观察各镜头与全局身份。</span></div>
          <el-tag :type="session?.running ? 'success' : 'info'" effect="plain">{{ session?.running ? '运行中' : '未启动' }}</el-tag>
        </div>
        <el-form :inline="true" label-width="100px" class="cfg config-panel">
          <div class="config-title"><span>① 基础配置</span><small>选择至少两路摄像头并设置检测目标</small></div>
          <el-form-item label="跨镜源">
            <el-radio-group v-model="form.sourceMode">
              <el-radio value="camera">摄像头（仅跨镜）</el-radio>
            </el-radio-group>
          </el-form-item>
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
          <el-collapse v-model="advancedPanels" class="advanced-controls">
            <el-collapse-item name="association">
              <template #title>
                <div class="advanced-title">
                  <span>② 高级关联策略</span>
                  <small>模型默认由后端按推荐顺序选择；仅在误合并或漏匹配时调整</small>
                </div>
              </template>
              <div class="advanced-grid">
                <el-form-item label="确认阈值">
                  <el-input-number v-model="form.confirmThresh" :min="0" :max="0.95" :step="0.01" />
                </el-form-item>
                <el-form-item label="外观阈值">
                  <el-input-number v-model="form.appearThresh" :min="0.2" :max="0.9" :step="0.01" />
                </el-form-item>
                <el-form-item label="候选阈值">
                  <el-input-number v-model="form.candidateThresh" :min="0" :max="0.9" :step="0.01" />
                </el-form-item>
                <el-form-item label="FAISS Gallery">
                  <el-switch v-model="form.useFaissGallery" />
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
                <el-form-item label="证据落库">
                  <el-switch v-model="form.persistEvents" />
                </el-form-item>
              </div>
            </el-collapse-item>
          </el-collapse>
          <el-form-item class="action-bar">
            <el-button :disabled="session?.running" @click="resetSessionDefaults">恢复推荐配置</el-button>
            <el-button type="primary" :loading="busy" v-permission="'ai:mtmc:edit'" @click="onStart">启动跨镜</el-button>
            <el-button type="danger" :disabled="!sessionId" v-permission="'ai:mtmc:edit'" @click="onStop">停止</el-button>
            <el-button @click="refreshSession">刷新状态</el-button>
            <el-button type="success" :disabled="!sessionId" @click="goWall">打开监控墙</el-button>
          </el-form-item>
        </el-form>
        <p class="hint mb">
          本页仅用于跨镜关联；本地视频/图片/RTSP/本机摄像头请在「实时检测测试」页使用。
          开启「证据落库」后 Tracklet、候选关联、证据边会写入数据库，便于停会话后审计与候选晋升/驳回落库；略增 DB 写入。
        </p>

        <el-descriptions v-if="session && !isDetectKind(session)" :column="3" border size="small" class="mb status-panel">
          <el-descriptions-item label="会话">{{ session.sessionId }}</el-descriptions-item>
          <el-descriptions-item label="运行">{{ session.running ? '是' : '否' }}</el-descriptions-item>
          <el-descriptions-item label="模式">{{ sourceModeLabel(session.sourceMode) }}</el-descriptions-item>
          <el-descriptions-item label="视频源">
            <template v-if="session.sourceMode === 'upload' || session.sourceMode === 'image'">
              {{ (session.videoSources || []).map((v) => v.name).join(' · ') || '—' }}
            </template>
            <template v-else>{{ (session.cameraIds || []).join(', ') }}</template>
          </el-descriptions-item>
          <el-descriptions-item label="帧数">{{ session.stats?.frames }}</el-descriptions-item>
          <el-descriptions-item label="人员命中">{{ session.stats?.persons }}</el-descriptions-item>
          <el-descriptions-item label="车辆命中">{{ session.stats?.vehicles }}</el-descriptions-item>
          <el-descriptions-item label="局部跟踪">{{ session.localTrackBackend || '-' }}</el-descriptions-item>
          <el-descriptions-item label="CMC">{{ session.enableCmc ? '开' : '关' }}</el-descriptions-item>
          <el-descriptions-item label="证据落库">{{ session.persistEvents ? '开' : '关' }}</el-descriptions-item>
          <el-descriptions-item label="跨镜策略">{{ session.mcbyteDecouple === false ? '标准' : '增强' }}</el-descriptions-item>
        </el-descriptions>

        <section v-if="session && !isDetectKind(session)" class="runtime-flight mb" aria-label="MTMC 运行时真值">
          <header class="runtime-flight__head">
            <div>
              <strong>运行飞行记录器</strong>
              <span>展示实际启用模型与有效策略，不以配置意图代替运行结果</span>
            </div>
            <el-tag :type="runtimeOverallTone" effect="dark">{{ runtimeOverallLabel }}</el-tag>
          </header>
          <el-alert
            v-if="runtimeRiskText"
            :title="runtimeRiskText"
            type="error"
            :closable="false"
            show-icon
            class="runtime-risk"
          />
          <div class="runtime-models">
            <article v-for="model in runtimeModels" :key="model.role" :class="['runtime-model', `is-${model.tone}`]">
              <div class="runtime-model__role">
                <span>{{ model.roleLabel }}</span>
                <el-tag size="small" :type="model.tone" effect="plain">{{ model.statusLabel }}</el-tag>
              </div>
              <strong>{{ model.selectedModelKey }}</strong>
              <div class="runtime-model__meta">
                <span>版本 {{ model.modelVersion }}</span>
                <span>后端 {{ model.provider }}</span>
                <span>输入 {{ model.inputSize }}</span>
                <span>维度 {{ model.embeddingDim ?? '—' }}</span>
              </div>
              <p v-if="model.degradedReason">{{ model.degradedReason }}</p>
            </article>
          </div>
          <div class="runtime-policy">
            <div>
              <span class="runtime-policy__label">预算队列</span>
              <span v-for="budget in runtimeBudgets" :key="budget.role">
                {{ budget.label }} {{ budget.consumed }}/{{ budget.queued }}，跳过 {{ budget.skipped }}（每帧 {{ budget.limitPerFrame }}）
              </span>
            </div>
            <div>
              <span class="runtime-policy__label">有效阈值</span>
              <span>{{ effectiveThresholdText }}</span>
            </div>
            <div>
              <span class="runtime-policy__label">拓扑</span>
              <span>{{ effectiveTopologyText }}</span>
            </div>
          </div>
        </section>

        <div class="grid-preview" v-if="session?.running && !isDetectKind(session)">
          <div v-for="cid in (session?.cameraIds || [])" :key="cid" class="cell">
            <div class="cell-h">
              <span>{{ cameraTitle(cid) }}</span>
              <span class="cell-h-meta">
                <span class="playback-time">播放 {{ formatPlaybackTime(camMeta(cid).playbackSeconds) }}</span>
                · 当前 {{ camCurrentDetCount(cid) }} · 会话 {{ camDetCount(cid) }}
                <template v-if="camMeta(cid).frameSeq"> · 帧 #{{ camMeta(cid).frameSeq }}</template>
                <template v-if="camCongestionLabel(cid)"> · {{ camCongestionLabel(cid) }}</template>
                <template v-if="camMeta(cid).lastError"> · {{ camMeta(cid).lastError }}</template>
              </span>
            </div>
            <img :src="overlaySrc(cid)" class="cell-v" @error="bustOverlay(cid)" />
            <div class="cell-dets">
              <div class="result-summary">
                <span>会话实时结果</span>
                <span class="summary-chip person">人 {{ camTypeCount(cid, 'person') }}</span>
                <span class="summary-chip vehicle">车 {{ camTypeCount(cid, 'vehicle') }}</span>
                <span class="summary-total">共 {{ camDetCount(cid) }} 个</span>
              </div>
              <div v-if="camDetections(cid).length" class="result-list">
                <div v-for="row in camDetections(cid)" :key="`${row.objectType}-${row.localTrackId}`" class="result-item">
                  <span :class="['result-type', row.objectType]">{{ row.objectType === 'vehicle' ? '车' : '人' }}</span>
                  <div class="result-main">
                    <div class="result-primary">
                      <span class="result-identity">{{ detectionIdentity(row) }}</span>
                      <span v-if="row.label" class="result-label">{{ row.label }}</span>
                    </div>
                    <div class="result-secondary">
                      <span>Local L{{ row.localTrackId }}</span>
                      <button v-if="row.globalId" class="global-link" @click="showTraj(row.globalId)">
                        Global {{ compactGlobalId(row.globalId) }}
                      </button>
                      <span v-else class="muted">Global 待关联</span>
                    </div>
                  </div>
                  <div class="result-status">
                    <span class="result-score">{{ formatScore(row.fuseScore ?? row.score) }}</span>
                    <span :class="['mode-pill', assocModeClass(row.assocMode)]">{{ assocModeLabel(row.assocMode) }}</span>
                  </div>
                </div>
              </div>
              <div v-else class="result-empty">本会话尚未识别到人员或车辆</div>
            </div>
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
        <div class="tab-intro">
          <div><strong>识别事件与过车记录</strong><span>按 Global ID、目标类型或车牌快速定位历史命中。</span></div>
        </div>
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
        <h4 class="section-title"><span>识别事件</span><small>人员和车辆的逐次命中记录</small></h4>
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
        <h4 class="section-title"><span>过车记录</span><small>车辆身份、融合分数与通行状态</small></h4>
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

      <el-tab-pane label="Tracklet / 证据" name="evidence">
        <div class="tab-intro">
          <div><strong>关联证据复核</strong><span>检查候选关系、局部轨迹与打分依据，完成晋升或驳回。</span></div>
          <el-tag type="warning" effect="plain">候选 {{ candidateRows.length }}</el-tag>
        </div>
        <div class="tab-toolbar">
          <el-input v-model="evidenceQ.globalId" clearable placeholder="globalId" style="width: 160px" />
          <el-select v-model="evidenceQ.objectType" clearable placeholder="类型" style="width: 110px">
            <el-option label="人员" value="person" />
            <el-option label="车辆" value="vehicle" />
          </el-select>
          <el-button @click="loadEvidence">刷新</el-button>
        </div>
        <h4 class="section-title"><span>候选关联</span><small>三档策略的中间态，可人工晋升或驳回</small></h4>
        <el-table :data="candidateRows" size="small" border stripe class="mb" max-height="220">
          <el-table-column prop="globalId" label="新建 Global" min-width="130" />
          <el-table-column prop="candidateGlobalId" label="候选 Global" min-width="130" />
          <el-table-column prop="status" label="状态" width="90" />
          <el-table-column prop="finalScore" label="综合分" width="80" />
          <el-table-column prop="reidScore" label="ReID" width="70" />
          <el-table-column label="操作" width="140">
            <template #default="{ row }">
              <el-button
                v-if="row.status === 'pending' || !row.status"
                link
                type="success"
                v-permission="'ai:mtmc:edit'"
                @click="onPromote(row)"
              >晋升</el-button>
              <el-button
                v-if="row.status === 'pending' || !row.status"
                link
                type="warning"
                v-permission="'ai:mtmc:edit'"
                @click="onReject(row)"
              >驳回</el-button>
            </template>
          </el-table-column>
        </el-table>
        <h4 class="section-title"><span>Tracklet 片段</span><small>每个镜头中的局部连续轨迹</small></h4>
        <el-table :data="tracklets" size="small" border stripe class="mb" max-height="260">
          <el-table-column prop="trackletId" label="Tracklet" min-width="120" show-overflow-tooltip />
          <el-table-column prop="globalId" label="Global ID" min-width="120" />
          <el-table-column prop="objectType" label="类型" width="70" />
          <el-table-column prop="cameraId" label="相机" width="70" />
          <el-table-column prop="localTrackId" label="Local" width="70" />
          <el-table-column prop="observationCount" label="观测" width="70" />
          <el-table-column prop="qualityScore" label="质量" width="70" />
          <el-table-column prop="startTs" label="开始" width="170" />
          <el-table-column prop="endTs" label="结束" width="170" />
        </el-table>
        <h4 class="section-title"><span>关联证据边</span><small>查看最终决策及 ReID、拓扑等分数组成</small></h4>
        <el-table :data="associations" size="small" border stripe max-height="260">
          <el-table-column prop="decision" label="决策" width="90" />
          <el-table-column prop="targetGlobalId" label="目标 Global" min-width="120" />
          <el-table-column prop="sourceGlobalId" label="来源 Global" min-width="120" />
          <el-table-column prop="candidateGlobalId" label="候选 Global" min-width="120" />
          <el-table-column prop="trackletId" label="Tracklet" min-width="110" show-overflow-tooltip />
          <el-table-column prop="policyVersion" label="策略" width="90" />
          <el-table-column label="外观" width="74"><template #default="{ row }">{{ formatScore(associationScoreParts(row).appearance) }}</template></el-table-column>
          <el-table-column label="拓扑" width="74"><template #default="{ row }">{{ formatScore(associationScoreParts(row).topology) }}</template></el-table-column>
          <el-table-column label="时间" width="74"><template #default="{ row }">{{ formatScore(associationScoreParts(row).time) }}</template></el-table-column>
          <el-table-column label="边际" width="74"><template #default="{ row }">{{ formatScore(associationScoreParts(row).margin) }}</template></el-table-column>
          <el-table-column label="最终" width="74"><template #default="{ row }">{{ formatScore(associationScoreParts(row).final) }}</template></el-table-column>
          <el-table-column prop="createdAt" label="时间" width="170" />
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="跨镜事件 / 检索" name="p2">
        <div class="tab-intro">
          <div><strong>跨镜事件与轨迹检索</strong><span>查看镜头间通行事件，并按身份或查询图发起异步检索。</span></div>
        </div>
        <div class="tab-toolbar">
          <el-input v-model="crossQ.globalId" clearable placeholder="globalId" style="width: 160px" />
          <el-button @click="loadCrossEvents">刷新跨镜事件</el-button>
        </div>
        <h4 class="section-title"><span>跨镜通行事件</span><small>Global ID 从一个镜头转移到另一个镜头的记录</small></h4>
        <el-table :data="crossEvents" size="small" border stripe class="mb" max-height="240">
          <el-table-column prop="eventTime" label="时间" width="170" />
          <el-table-column prop="globalId" label="Global ID" min-width="120" />
          <el-table-column prop="fromCameraId" label="From" width="70" />
          <el-table-column prop="toCameraId" label="To" width="70" />
          <el-table-column prop="transitSec" label="间隔(s)" width="80" />
          <el-table-column prop="displayName" label="人员" width="90" />
          <el-table-column prop="plate" label="车牌" width="100" />
          <el-table-column prop="decision" label="决策" width="90" />
        </el-table>

        <h4 class="section-title"><span>全局轨迹检索</span><small>按 Global ID 汇总跨镜轨迹</small></h4>
        <el-form :inline="true" class="mb">
          <el-form-item label="Global ID">
            <el-input v-model="searchForm.globalId" clearable style="width: 160px" />
          </el-form-item>
          <el-button type="primary" :disabled="!searchForm.globalId" v-permission="'ai:mtmc:edit'" @click="submitGlobalTrace">
            提交轨迹检索
          </el-button>
        </el-form>

        <h4 class="section-title"><span>多视频 ReID 检索</span><small>上传查询图，在本地视频源中查找相似目标</small></h4>
        <el-form :inline="true" class="mb">
          <el-form-item label="摄像头">
            <el-select v-model="searchForm.cameraIds" multiple collapse-tags style="width: 280px" placeholder="本地视频源">
              <el-option
                v-for="c in fileCameras"
                :key="c.id"
                :label="`${c.name} (#${c.id})`"
                :value="c.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="查询图">
            <input type="file" accept="image/*" @change="onQueryFile" />
          </el-form-item>
          <el-button
            type="primary"
            :disabled="!searchForm.cameraIds.length || !searchForm.queryFile"
            v-permission="'ai:mtmc:edit'"
            @click="submitMultiVideoSearch"
          >
            提交多视频检索
          </el-button>
          <el-button @click="loadSearchJobs">刷新任务</el-button>
        </el-form>
        <el-table :data="searchJobs" size="small" border stripe max-height="260">
          <el-table-column prop="jobId" label="任务 ID" min-width="120" />
          <el-table-column prop="jobType" label="类型" width="120" />
          <el-table-column prop="status" label="状态" width="90" />
          <el-table-column prop="progress" label="进度" width="70">
            <template #default="{ row }">{{ Math.round((row.progress || 0) * 100) }}%</template>
          </el-table-column>
          <el-table-column prop="message" label="说明" min-width="120" />
          <el-table-column label="结果" width="90">
            <template #default="{ row }">
              <el-button link type="primary" @click="showSearchResult(row)">查看</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="相机拓扑" name="topo">
        <div class="tab-intro">
          <div><strong>相机通行拓扑</strong><span>配置镜头间合理通行时间，排除不可能的跨镜匹配。</span></div>
          <el-tag effect="plain">拓扑边 {{ topology.length }}</el-tag>
        </div>
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
        <h4 class="section-title"><span>已配置拓扑</span><small>有向边需要按两个方向分别配置</small></h4>
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
        <div class="tab-intro guide-intro">
          <div><strong>快速上手与排障指南</strong><span>按推荐流程完成配置；遇到问题时从本页末尾的排障顺序开始检查。</span></div>
        </div>
        <div class="guide-wrap">
          <el-alert
            type="info"
            :closable="false"
            show-icon
            title="跨镜 MTMC 用于多路摄像头下给人员/车辆分配稳定全局 ID，并可与监控墙 AI 叠加联动。建议首次使用先通读本页，再按步骤操作。"
            class="mb"
          />

          <h3 class="guide-h3">一、推荐使用流程</h3>
          <el-steps :active="8" align-center finish-status="success" class="guide-steps mb">
            <el-step title="准备摄像头" description="摄像头管理录入 RTSP，流可预览" />
            <el-step title="准备权重" description="检测 + ReID / 车牌模型已拉取" />
            <el-step title="配置拓扑" description="相机拓扑 Tab 添加通行边" />
            <el-step title="启动会话" description="会话控制 Tab 选路并启动" />
            <el-step title="查看实时检出" description="每路预览下方列表 + 全局身份表" />
            <el-step title="Tracklet / 证据" description="核对关联决策与落库片段" />
            <el-step title="跨镜事件 / 检索" description="通行事件与多视频检索队列（P2）" />
            <el-step title="监控墙叠加" description="可选：大屏 AI 叠加" />
          </el-steps>

          <h3 class="guide-h3">二、链路概览（P0 + P1 + P2）</h3>
          <p class="guide-p">
            当前 MTMC 采用 <b>Tracklet 优先</b> 的跨镜关联链路（策略版本 <code>mtmc_v2</code>）：
          </p>
          <ol class="guide-ol mb">
            <li><b>共享拉流</b> → YOLO 检测 → ByteTrack / BoT-SORT 局部跟踪（车辆漏跟大目标时自动补 orphan 检测框）</li>
            <li><b>Tracklet 累积</b>：按 local_track_id 聚合多帧观测，关键帧质量筛选 + Top-K 加权 embedding 聚合</li>
            <li><b>关联决策</b>：短时粘性续 Global；仅新生轨迹才开放长时外观匹配；跨镜优先用对侧相机原型（FAISS Gallery）</li>
            <li><b>三档门控（P1）</b>：ReID 分 ≥ 确认阈值 → 自动合并；介于候选～确认 → 新建 Global 并标记候选；低于候选 → 新建</li>
            <li><b>落库</b>：全局身份、Tracklet 片段、关联证据边、轨迹事件一并持久化</li>
            <li><b>跨镜事件（P2）</b>：同一 Global 切换相机时写入轻量通行事件，可审计通行链</li>
            <li><b>候选晋升（P2）</b>：三档 candidate 可人工晋升合并或驳回，并更新 Tracklet 绑定</li>
            <li><b>检索队列（P2）</b>：全局轨迹检索、多路本地视频 ReID 异步任务</li>
          </ol>
          <el-descriptions :column="1" border size="small" class="mb">
            <el-descriptions-item label="画面标签">未分配 Global 时显示 <code>L{localId}</code>；分配后显示 <code>GlobalId|姓名/车牌</code></el-descriptions-item>
            <el-descriptions-item label="实时检出列表">每路预览下方展示该镜头的会话实时结果（类型、Local、Global、身份、分数、关联决策）；标题同时区分当前帧数量与会话累计数量，约 1.5s 刷新</el-descriptions-item>
            <el-descriptions-item label="决策类型">sticky / long_term / candidate / new / promoted（人工晋升）</el-descriptions-item>
            <el-descriptions-item label="硬冲突">车辆：仅「可靠车牌」不一致，或 truck/bus ↔ car 类别互斥时拒绝合并；OCR 噪声短牌（如 UNEC）不参与硬冲突</el-descriptions-item>
            <el-descriptions-item label="行人软线索">跨视角外观偏弱时，用 HSV 颜色签名抬分（红帽/浅色上衣/白盔等）；行人检测阈值略低于车辆</el-descriptions-item>
            <el-descriptions-item label="近分 tie-break">分数接近时优先「已在对侧相机出现过」的 Global，减少多辆相似白车/深色车抢占</el-descriptions-item>
            <el-descriptions-item label="FAISS Gallery">在线 Active Gallery 按 (Global, 相机) 存原型；跨镜用对侧原型余弦，避免本侧 centroid 污染</el-descriptions-item>
            <el-descriptions-item label="跨镜事件表">mtmc_cross_camera_event：From→To 相机、通行间隔、关联决策（P2）</el-descriptions-item>
          </el-descriptions>

          <h3 class="guide-h3">三、会话控制 · 参数说明</h3>
          <el-table :data="paramGuide" size="small" border stripe class="mb">
            <el-table-column prop="name" label="参数" width="120" />
            <el-table-column prop="desc" label="说明" min-width="280" />
            <el-table-column prop="suggest" label="建议值" width="160" />
          </el-table>

          <h3 class="guide-h3">四、Tracklet / 证据 Tab（P0 + P1）</h3>
          <p class="guide-p">
            用于审计跨镜关联是否「有据可依」，建议在联调阶段与「事件 / 过车」Tab 配合使用。
          </p>
          <el-table :data="evidenceGuide" size="small" border stripe class="mb">
            <el-table-column prop="name" label="区块" width="140" />
            <el-table-column prop="desc" label="说明" min-width="320" />
          </el-table>
          <p class="guide-p">
            <b>关联证据边</b> 字段含义：<code>decision</code> 为决策路径；
            <code>targetGlobalId</code> 为本次写入的 Global；
            <code>candidateGlobalId</code> 为三档中间态时「疑似同一目标」的候选 Global；
            <code>policyVersion</code> 为 <code>mtmc_v2</code> 时含三档门控；
            分数列 <code>r=</code> 为 ReID 分，<code>f=</code> 为综合分（含拓扑权重）。
          </p>

          <h3 class="guide-h3">五、跨镜事件 / 检索 Tab（P2）</h3>
          <ul class="guide-ol mb">
            <li><b>跨镜通行事件</b>：会话运行中，同一 Global 从相机 A 切换到 B 时自动记录（含通行间隔秒数）。可用于园区通行链审计，无需单独告警规则。</li>
            <li><b>候选晋升 / 驳回</b>：在「Tracklet / 证据」Tab 对 pending 候选点击晋升，将把「新建 Global」合并进「候选 Global」；驳回则保持分离。</li>
            <li><b>全局轨迹检索</b>：输入 Global ID 提交异步任务，汇总事件、Tracklet、跨镜事件。</li>
            <li><b>多视频检索队列</b>：上传查询行人图 + 多选<b>本地视频</b>摄像头（sourceType=file），后台按路排队执行录像 ReID，适合离线复盘。</li>
          </ul>

          <h3 class="guide-h3">六、相机拓扑（必配，直接影响能否合并）</h3>
          <p class="guide-p">
            在「相机拓扑」Tab 为相邻摄像头添加有向边 <code>From → To</code>，并设置最短/最长通行秒数。
            跨镜关联时，若候选轨迹不在该时间窗内会被<strong>整条拒绝</strong>（拓扑硬门控）。
          </p>
          <el-descriptions :column="1" border size="small" class="mb">
            <el-descriptions-item label="重叠视野（同街对向/同向机位）">
              <b>最短通行秒数请设为 0</b>。两路几乎同时看到同一目标时，若最短秒 &gt; 0（例如 0.5），会出现「两侧都新建 Global、永不合并」。最长秒建议 20～60。
            </el-descriptions-item>
            <el-descriptions-item label="非重叠（门口→走廊）">
              按实际步行/车行时间：门口 → 走廊（5～30s）、走廊 → 出口（10～60s）。
            </el-descriptions-item>
            <el-descriptions-item label="默认值">
              本页表单默认最短 0、最长 120；请按现场改，改完无需重启会话即可对新关联生效（已绑定 sticky 的轨迹不受影响）。
            </el-descriptions-item>
          </el-descriptions>

          <h3 class="guide-h3">七、监控墙 AI 叠加</h3>
          <ol class="guide-ol mb">
            <li>在本页「会话控制」启动跨镜并选中摄像头。</li>
            <li>点击「打开监控墙叠加」，或手动进入 <b>视频监控 → 监控墙</b>。</li>
            <li>开启「AI 叠加」，填写会话 ID（本页启动后会写入本地缓存）。</li>
            <li>各画面切换为带框与 Global ID 的 MJPEG 流；若叠加失败会自动回退普通监控流。</li>
          </ol>

          <h3 class="guide-h3">八、模型与权重依赖</h3>
          <el-descriptions :column="1" border size="small" class="mb">
            <el-descriptions-item label="人员检测">YOLO 行人检测（如 yolo26n），模型管理启用</el-descriptions-item>
            <el-descriptions-item label="人员强 ReID">osnet-x1-0 / clip-reid-person ONNX（与 Youtu 可加权融合）</el-descriptions-item>
            <el-descriptions-item label="人员底库（P1）">按 model_key 多路检索（OSNet/CLIP + Youtu）；行人重识别页登记后命中显示姓名；可选 FAISS 加速</el-descriptions-item>
            <el-descriptions-item label="车辆检测">YOLO 车辆检测 + 车牌检测/OCR</el-descriptions-item>
            <el-descriptions-item label="车辆视觉 ReID">transreid-vehicle / clip-reid-vehicle（无牌时兜底）</el-descriptions-item>
            <el-descriptions-item label="全局身份落库（P0）">会话运行中持续写入 MtmcGlobalPerson / MtmcGlobalVehicle</el-descriptions-item>
          </el-descriptions>

          <h3 class="guide-h3">九、注意事项（必读）</h3>
          <div class="guide-alerts">
            <el-alert type="warning" :closable="false" show-icon title="后端重启后会话失效" description="跨镜会话保存在后端内存中。重启 Flask 后旧 sessionId 无效，监控墙叠加会 404；请重新启动会话，或关闭 AI 叠加。已落库的 Tracklet / 证据边 / 全局身份仍可在数据库中查询。代码/关联策略更新后也必须重启 backend 才会生效。" />
            <el-alert type="error" :closable="false" show-icon title="多路必须时间对齐" description="两路（或多路）应同时运行、交错采样。本地录像联调时请同步播放（或评估脚本 --interleaved），不要先跑完一路再跑另一路——否则对侧 Gallery 为空，无法跨镜合并。" />
            <el-alert type="warning" :closable="false" show-icon title="重叠视野拓扑最短秒=0" description="同街两侧摄像头几乎同时看到同一人/车时，拓扑最短通行秒必须为 0。设成 0.5 以上会导致两侧各自新建 Global，表现为「明明是同一辆白 SUV / 同一骑行人却 ID 不同」。" />
            <el-alert type="warning" :closable="false" show-icon title="CPU 与路数" description="建议 2～4 路摄像头、采样 FPS ≤ 2、检测分辨率约 640。路数或 FPS 过高会导致延迟堆积、全局 ID 抖动。" />
            <el-alert type="warning" :closable="false" show-icon title="局部跟踪与 CMC" description="默认 ByteTrack + McByte++ 解耦（粘性续 Global、仅新生才长时 ReID）。货车等大目标若 ByteTrack 漏跟，引擎会按 truck/bus 补 orphan 检测框。镜头抖动明显可试 BoT-SORT 并开启 CMC；静止机位不必开 CMC。" />
            <el-alert type="info" :closable="false" show-icon title="三档决策调参（P1）" description="确认阈值默认等于外观阈值；候选阈值默认为外观阈值的约 82%。设为 0 表示使用后端默认。行人跨镜在默认配置下会略放宽确认分（弱外观+颜色签名）；显式抬高确认阈值时仍走三档 candidate。候选态 precision-first：不自动合并，可在「Tracklet / 证据」Tab 人工核对。" />
            <el-alert type="info" :closable="false" show-icon title="车辆车牌与类别" description="仅长度≥6 且分数足够的车牌参与硬冲突；OCR 噪声短串不会阻断视觉合并。truck/bus 与轿车互斥；YOLO 把大车误标摩托时会按框面积纠正，不与 car 硬冲突。" />
            <el-alert type="info" :closable="false" show-icon title="Tracklet 与 tentative 关联（P0）" description="局部轨迹积累足够高质量观测后 tentatively 关联；轨迹结束（local 消失）时 finalize 并落库 Tracklet。画面可能短暂显示 L{localId}，finalize 后稳定为 Global ID。" />
            <el-alert type="info" :closable="false" show-icon title="候选晋升（P2）" description="晋升/驳回需会话仍在运行（内存 Associator 合并）。会话已停止时仅更新数据库候选状态，不会 retroactive 合并在线 Global。" />
            <el-alert type="error" :closable="false" show-icon title="合规与隐私" description="人脸、行人外观、车牌属于敏感信息。请确保采集与展示已获授权，生产环境应限制访问权限并遵守当地法规。" />
            <el-alert type="info" :closable="false" show-icon title="排障顺序" description="权重是否就绪 → 摄像头流可预览 → 会话 running → 拓扑最短秒是否适合视野 → 两路是否同步播放 → sessionAlive 通过 → Tracklet / 证据看 decision 与 crossProto → FAISS 未安装时自动回退矩阵检索。" />
          </div>

          <h3 class="guide-h3">十、常见问题</h3>
          <el-collapse class="mb">
            <el-collapse-item title="监控墙开了 AI 叠加但没有框？" name="q1">
              <p>先确认跨镜会话仍在运行（本页状态为「是」）；后端重启后需重新启动。监控墙会先调 alive 接口，失败则回退普通流。</p>
            </el-collapse-item>
            <el-collapse-item title="同一辆白 SUV / 同一骑行人两镜 Global 不同？" name="q2b">
              <p>
                按顺序排查：① 拓扑最短秒是否为 0（重叠视野）；② 两路是否同步交错播放，而非串行跑完一路；③ 代码更新后是否已重启 backend；
                ④ 「Tracklet / 证据」里 decision 是否全是 <code>new</code>（若是，多半是拓扑拒掉了跨镜）；
                ⑤ 车辆是否被标成 truck 与 car 互斥（货车与轿车本就不该合并）。多辆相似白色车辆时，系统会优先续接「已在对侧出现」的 Global。
              </p>
            </el-collapse-item>
            <el-collapse-item title="全局 ID 频繁切换？" name="q2">
              <p>适当降低采样 FPS、检查检测是否稳定；调高外观阈值或缩短时间窗；确认拓扑边的时间范围符合实际通行时间；强 ReID 权重未就绪时会更多依赖 Youtu/直方图，跨镜稳定性会下降。</p>
            </el-collapse-item>
            <el-collapse-item title="车辆有牌仍串车？ / OCR 乱码阻断合并？" name="q3">
              <p>
                检查车牌 OCR 置信度与检测框质量；夜间/污损车牌会退回视觉键。
                仅「可靠车牌」（通常长度≥6 且分数达标）不一致才硬冲突；短噪声串（如 UNEC、LMM）不会阻断高相似视觉合并。
                可在事件/过车 Tab 查看 identityKey 与 fuseScore。
              </p>
            </el-collapse-item>
            <el-collapse-item title="行人/骑行人跨镜不稳定？" name="q3b">
              <p>
                跨视角（背影↔正脸）外观余弦往往只有 0.3～0.5。系统会结合颜色签名与略低的行人检测阈值提升召回。
                请保证拓扑最短秒=0、两路同步，并确认人员开关已开启、强 ReID / Youtu 权重可用。
              </p>
            </el-collapse-item>
            <el-collapse-item title="无 edit 权限无法启动？" name="q4">
              <p>启动/停止跨镜、维护拓扑需要 <code>ai:mtmc:edit</code>。只读角色可查看会话与事件。</p>
            </el-collapse-item>
            <el-collapse-item title="画面一直显示 L{数字} 没有 Global ID？" name="q5">
              <p>属 P0 Tracklet 流程正常现象：局部轨迹尚在累积观测，或尚未达到 tentative / finalize 条件。待轨迹结束或关键帧质量足够后会分配 Global ID。可在「Tracklet / 证据」Tab 查看对应 tracklet 的观测数与质量分。</p>
            </el-collapse-item>
            <el-collapse-item title="出现 candidate 决策是什么意思？" name="q6">
              <p>P1 三档中间态：ReID 分介于候选阈值与确认阈值之间，系统新建了 Global ID 但记录了疑似同一目标的候选 Global（precision-first，不自动合并）。请在「Tracklet / 证据」Tab 的「候选关联」表核对，必要时结合事件轨迹人工确认。</p>
            </el-collapse-item>
            <el-collapse-item title="关联证据里 decision 有哪些？" name="q7">
              <p><code>sticky</code> 短时粘性续接；<code>long_term</code> 长时确认合并；<code>candidate</code> 候选态新建；<code>new</code> 无匹配新建。策略版本 <code>mtmc_v2</code> 表示已启用三档门控与证据落库。跨镜成功合并时通常可见 <code>long_term</code>，证据中可能含 <code>crossProto</code>（对侧原型相似度）。</p>
            </el-collapse-item>
            <el-collapse-item title="多视频检索没有可选摄像头？" name="q9">
              <p>仅 <code>sourceType=file</code> 的本地视频摄像头会出现在多视频检索下拉框。RTSP 实时流请使用在线 MTMC 会话，离线录像需先在摄像头管理配置为本地文件源。</p>
            </el-collapse-item>
            <el-collapse-item title="FAISS Gallery 关或 faiss-cpu 未安装？" name="q8">
              <p>关闭「FAISS Gallery」或环境未装 faiss-cpu 时，在线 Global 候选与行人底库匹配会自动回退全量矩阵检索，功能可用但 CPU 占用略高。安装：<code>pip install faiss-cpu</code>。</p>
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
import { ref, reactive, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { cameraApi } from '../../../api/camera'
import { mtmcApi } from '../../../api/mtmc'
import {
  associationScoreParts,
  runtimeModelRows,
  runtimeRiskSummary,
  topologyPolicyText,
} from '../../../utils/mtmcRuntimeStatus'

const router = useRouter()
const tab = ref('detect')
const busy = ref(false)
const detectBusy = ref(false)
const cameras = ref([])
const sessionId = ref('')
const session = ref(null)
const advancedPanels = ref([])
const detectSessionId = ref('')
const detectSession = ref(null)
const topology = ref([])
const events = ref([])
const passes = ref([])
const tracklets = ref([])
const associations = ref([])
const candidates = ref([])
const candidateDb = ref([])
const crossEvents = ref([])
const searchJobs = ref([])
const overlayBust = reactive({})
let pollTimer = null

const runtimeModels = computed(() => runtimeModelRows(session.value?.runtime || {}))
const runtimeRiskText = computed(() => runtimeRiskSummary(session.value?.runtime || {}))
const runtimeOverallTone = computed(() => {
  const gallery = session.value?.runtime?.gallery || {}
  if (gallery.degraded === true || gallery.ready === false) return 'danger'
  if (runtimeModels.value.some((row) => row.tone === 'danger')) return 'danger'
  if (runtimeModels.value.length && runtimeModels.value.every((row) => row.tone === 'success')) return 'success'
  return 'info'
})
const runtimeOverallLabel = computed(() => ({
  danger: '存在降级',
  success: '运行就绪',
  info: '等待运行探测',
})[runtimeOverallTone.value])
const runtimeBudgets = computed(() => {
  const labels = { personReid: '人员 ReID', vehicleReid: '车辆 ReID', plateOcr: '车牌 OCR' }
  return Object.entries(session.value?.runtime?.budgets || {}).map(([role, value]) => ({
    role,
    label: labels[role] || role,
    limitPerFrame: value.limitPerFrame ?? 0,
    queued: value.queued ?? 0,
    consumed: value.consumed ?? 0,
    skipped: value.skipped ?? 0,
  }))
})
const effectiveThresholdText = computed(() => {
  const value = session.value?.runtime?.effectiveThresholds
  if (!value) return '等待会话快照'
  return [
    `外观 ${formatScore(value.appearance)}`,
    `车辆 ${formatScore(value.vehicleAppearance)}`,
    `确认 ${formatScore(value.confirm)}`,
    `候选 ${formatScore(value.candidate)}`,
    `边际 ${formatScore(value.minMatchMargin)}`,
  ].join(' · ')
})
const effectiveTopologyText = computed(() => topologyPolicyText(
  session.value?.runtime?.topologyPolicy || {},
))

const form = reactive({
  sourceMode: 'camera',
  cameraIds: [],
  enablePerson: true,
  enableVehicle: true,
  sampleFps: 4,
  appearThresh: 0.48,
  confirmThresh: 0,
  candidateThresh: 0,
  useFaissGallery: true,
  timeWindowSec: 90,
  localTrackBackend: 'bytetrack',
  enableCmc: false,
  persistEvents: false,
  mcbyteDecouple: true,
})

const detectForm = reactive({
  sourceMode: 'upload',
  enablePerson: true,
  enableVehicle: true,
  sampleFps: 4,
})

const resetSessionDefaults = () => {
  Object.assign(form, {
    enablePerson: true,
    enableVehicle: true,
    sampleFps: 4,
    appearThresh: 0.48,
    confirmThresh: 0,
    candidateThresh: 0,
    useFaissGallery: true,
    timeWindowSec: 90,
    localTrackBackend: 'bytetrack',
    enableCmc: false,
    persistEvents: false,
    mcbyteDecouple: true,
  })
}

const uploadMode = ref('path')

const uploadSlots = reactive([
  { name: '镜头A', file: null, fileList: [] },
])

const pathSlots = reactive([
  {
    name: '镜头A',
    path: 'video/行人和车辆视频.mp4',
  },
])

const imageSlots = reactive([{ name: '图片A', path: '', file: null, fileList: [] }])
const streamSlots = reactive([{ name: 'RTSP-A', url: '' }])
const deviceSlots = reactive([{ name: '本机摄像头', device: '' }])
const devices = ref([])

const sessionPayload = () => ({
  enablePerson: form.enablePerson,
  enableVehicle: form.enableVehicle,
  sampleFps: form.sampleFps,
  appearThresh: form.appearThresh,
  confirmThresh: form.confirmThresh,
  candidateThresh: form.candidateThresh,
  useFaissGallery: form.useFaissGallery,
  timeWindowSec: form.timeWindowSec,
  localTrackBackend: form.localTrackBackend,
  enableCmc: form.enableCmc,
  mcbyteDecouple: form.mcbyteDecouple,
  persistEvents: form.persistEvents,
  detectOnly: false,
})

const detectPayload = () => ({
  enablePerson: detectForm.enablePerson,
  enableVehicle: detectForm.enableVehicle,
  sampleFps: detectForm.sampleFps,
  persistEvents: false,
  detectOnly: true,
  localTrackBackend: 'iou',
  reidBudget: 0,
  plateBudget: 0,
})

const onVideoPick = (idx, file) => {
  const slot = uploadSlots[idx]
  if (!slot || !file?.raw) return
  slot.file = file.raw
  slot.fileList = [file]
}
const onVideoRemove = (idx) => {
  const slot = uploadSlots[idx]
  if (!slot) return
  slot.file = null
  slot.fileList = []
}
const addUploadSlot = () => {
  if (uploadSlots.length >= 4) return
  uploadSlots.push({ name: `镜头${String.fromCharCode(65 + uploadSlots.length)}`, file: null, fileList: [] })
}
const removeUploadSlot = (idx) => {
  if (uploadSlots.length <= 1) return
  uploadSlots.splice(idx, 1)
}
const addPathSlot = () => {
  if (pathSlots.length >= 4) return
  pathSlots.push({ name: `镜头${String.fromCharCode(65 + pathSlots.length)}`, path: '' })
}
const removePathSlot = (idx) => {
  if (pathSlots.length <= 1) return
  pathSlots.splice(idx, 1)
}
const onImagePick = (idx, file) => {
  const slot = imageSlots[idx]
  if (!slot || !file?.raw) return
  slot.file = file.raw
  slot.fileList = [file]
}
const onImageRemove = (idx) => {
  const slot = imageSlots[idx]
  if (!slot) return
  slot.file = null
  slot.fileList = []
}
const addImageSlot = () => {
  if (imageSlots.length >= 4) return
  imageSlots.push({ name: `图片${String.fromCharCode(65 + imageSlots.length)}`, path: '', file: null, fileList: [] })
}
const removeImageSlot = (idx) => {
  if (imageSlots.length <= 1) return
  imageSlots.splice(idx, 1)
}
const addStreamSlot = () => {
  if (streamSlots.length >= 4) return
  streamSlots.push({ name: `RTSP-${streamSlots.length + 1}`, url: '' })
}
const removeStreamSlot = (idx) => {
  if (streamSlots.length <= 1) return
  streamSlots.splice(idx, 1)
}
const addDeviceSlot = () => {
  if (deviceSlots.length >= 4) return
  deviceSlots.push({ name: `设备${deviceSlots.length + 1}`, device: '' })
}
const removeDeviceSlot = (idx) => {
  if (deviceSlots.length <= 1) return
  deviceSlots.splice(idx, 1)
}

const topoForm = reactive({
  fromCameraId: null,
  toCameraId: null,
  minTransitSec: 0,
  maxTransitSec: 120,
})

const eventQ = reactive({ globalId: '', objectType: '' })
const passQ = reactive({ plate: '' })
const evidenceQ = reactive({ globalId: '', objectType: '' })
const crossQ = reactive({ globalId: '' })
const searchForm = reactive({
  globalId: '',
  cameraIds: [],
  queryFile: null,
})

const trajOpen = ref(false)
const trajEvents = ref([])

/** 操作说明 Tab：参数对照表 */
const paramGuide = [
  { name: '摄像头', desc: '参与跨镜的多路视频源，须已在「摄像头管理」配置且可预览；多路须同时运行', suggest: '先 2 路联调' },
  { name: '本地视频', desc: '直接上传 2 路及以上 MP4 等视频，无需预建摄像头；自动全互通拓扑（minTransitSec=0）', suggest: '演示/离线联调' },
  { name: '人员 / 车辆', desc: '是否启用人员 MTMC、车辆 MTMC（含车牌融合与视觉 ReID）', suggest: '按场景开关' },
  { name: '采样 FPS', desc: '每路每秒处理帧数，越高越耗 CPU', suggest: '2～4' },
  { name: '外观阈值', desc: '长时外观匹配的 ReID 下限；确认阈值默认值。行人跨镜后端会略放宽', suggest: '0.45～0.55' },
  { name: '确认阈值', desc: 'P1 三档：ReID 分 ≥ 此值自动合并到候选 Global（long_term）', suggest: '0 或同外观阈值' },
  { name: '候选阈值', desc: 'P1 三档：ReID 分介于候选～确认时新建并标记 candidate', suggest: '0 或约外观×0.82' },
  { name: 'FAISS Gallery', desc: '按 (Global,相机) 存原型；跨镜用对侧原型。关则回退矩阵检索', suggest: '开' },
  { name: '时间窗(s)', desc: '全局身份在线缓存秒数，影响跨镜关联范围', suggest: '60～120' },
  { name: '局部跟踪', desc: 'ByteTrack 推荐；大目标漏跟时车辆侧会补 orphan 框', suggest: 'bytetrack' },
  { name: 'CMC', desc: '镜头运动补偿，移动/云台摄像头可开', suggest: '静止机关' },
  { name: '证据落库', desc: 'Tracklet 片段、候选关联、关联证据边写入数据库；人工核对候选时建议开启', suggest: '核对时开' },
  { name: '拓扑最短秒', desc: '重叠视野必须为 0；非重叠按通行时间', suggest: '重叠=0' },
]

/** Tracklet / 证据 Tab 说明 */
const evidenceGuide = [
  { name: '候选关联', desc: 'P1 三档中间态：新建 Global 与疑似候选 Global 的配对，含 ReID / 综合分，供人工核对' },
  { name: 'Tracklet 片段', desc: 'P0 局部轨迹落库：每段 local track 的观测数、质量分、起止时间与绑定 Global ID' },
  { name: '关联证据边', desc: 'P0 每次 associate 的决策与分数（reid / topology / final），policyVersion=mtmc_v2' },
]

const fileCameras = computed(() => cameras.value.filter((c) => c.sourceType === 'file'))

const candidateRows = computed(() => {
  const db = candidateDb.value || []
  if (db.length) return db
  return (candidates.value || []).map((r) => ({ ...r, status: 'pending' }))
})

const overlaySrc = (cid) => {
  if (!sessionId.value || !session.value?.running) return ''
  return mtmcApi.overlayUrl(sessionId.value, cid, overlayBust[cid] || '')
}
const bustOverlay = (cid) => {
  if (!session.value?.running) return
  overlayBust[cid] = String(Date.now())
}

const isDetectKind = (row) => row && (row.kind === 'detect' || row.detectOnly === true)

const camMeta = (cid, sess = session.value) => sess?.cams?.[String(cid)] || {}
const camDetections = (cid, sess = session.value) => camMeta(cid, sess).detections || []
const camDetCount = (cid, sess = session.value) => {
  const m = camMeta(cid, sess)
  if (typeof m.detCount === 'number') return m.detCount
  return (m.detections || []).length
}
const camCurrentDetCount = (cid, sess = session.value) => {
  const m = camMeta(cid, sess)
  if (typeof m.currentDetCount === 'number') return m.currentDetCount
  return (m.detections || []).length
}
const camTypeCount = (cid, type) => camDetections(cid).filter((row) => row.objectType === type).length
const formatPlaybackTime = (value) => {
  const total = Math.max(0, Math.floor(Number(value) || 0))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const seconds = total % 60
  return [hours, minutes, seconds].map((part) => String(part).padStart(2, '0')).join(':')
}
const detectionIdentity = (row) => {
  if (row.objectType === 'vehicle') return row.plate || '未识别车牌'
  return row.displayName || '匿名人员'
}
const compactGlobalId = (value) => {
  const text = String(value || '')
  if (text.length <= 15) return text
  return `${text.slice(0, 8)}…${text.slice(-5)}`
}
const camCongestionLabel = (cid) => {
  const c = camMeta(cid).congestion
  if (!c) return ''
  return c.label || c.level || ''
}
const cameraTitle = (cid) => {
  const vs = (session.value?.videoSources || []).find((v) => Number(v.id) === Number(cid))
  if (vs?.name) return `${vs.name} (#${cid})`
  const row = cameras.value.find((c) => Number(c.id) === Number(cid))
  const name = row?.name || ''
  return name ? `${name} (#${cid})` : `Cam #${cid}`
}
const detectCamId = computed(() => {
  const ids = detectSession.value?.cameraIds || []
  return ids.length ? ids[0] : null
})
const detectBust = ref('')
const detectOverlaySrc = computed(() => {
  if (!detectSessionId.value || !detectSession.value?.running || !detectCamId.value) return ''
  return mtmcApi.overlayUrl(detectSessionId.value, detectCamId.value, detectBust.value)
})
const detectRawSrc = computed(() => {
  if (!detectSessionId.value || !detectSession.value?.running || !detectCamId.value) return ''
  return mtmcApi.rawUrl(detectSessionId.value, detectCamId.value, detectBust.value)
})
const bustDetectStream = () => {
  if (!detectSession.value?.running) return
  detectBust.value = String(Date.now())
}
const formatScore = (v) => {
  if (v == null || v === '') return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return n.toFixed(2)
}
const formatFps = (v) => {
  const n = Number(v)
  if (!Number.isFinite(n) || n <= 0) return '—'
  return n >= 10 ? n.toFixed(0) : n.toFixed(1)
}
const sourceModeLabel = (mode) => {
  const map = {
    camera: '摄像头',
    upload: '本地视频',
    image: '图片',
    stream: 'RTSP 流',
    device: '本机摄像头',
  }
  return map[mode] || mode || '—'
}

const assocModeClass = (mode) => {
  if (!mode) return 'muted'
  if (mode === 'long_term' || mode === 'promoted') return 'mode-ok'
  if (mode === 'sticky') return 'mode-sticky'
  if (mode === 'candidate') return 'mode-cand'
  return 'muted'
}
const assocModeLabel = (mode) => {
  const map = {
    long_term: '长期库',
    promoted: '已确认',
    sticky: '持续跟踪',
    candidate: '候选',
    new: '新目标',
  }
  return map[mode] || mode || '待关联'
}

const clearSavedSession = () => {
  sessionId.value = ''
  session.value = null
  localStorage.removeItem('mtmc-session-id')
}

const clearDetectSession = () => {
  detectSessionId.value = ''
  detectSession.value = null
  detectBust.value = ''
  localStorage.removeItem('mtmc-detect-session-id')
}

const applyLiveRow = (row) => {
  if (!row) return
  if (isDetectKind(row)) {
    detectSessionId.value = row.sessionId
    detectSession.value = row
    localStorage.setItem('mtmc-detect-session-id', detectSessionId.value)
  } else {
    sessionId.value = row.sessionId
    session.value = row
    localStorage.setItem('mtmc-session-id', sessionId.value)
  }
}

const pingSaved = async (id, kind) => {
  if (!id) return false
  try {
    const alive = await mtmcApi.sessionAlive(id)
    if (!alive.data?.active) return false
    const res = await mtmcApi.getSession(id)
    const data = res.data
    if (kind === 'detect' && !isDetectKind(data)) return false
    if (kind === 'mtmc' && isDetectKind(data)) return false
    applyLiveRow(data)
    return true
  } catch (_) {
    return false
  }
}

const loadCameras = async () => {
  const res = await cameraApi.list({ pageNum: 1, pageSize: 100, status: '0' })
  cameras.value = res.data.rows || []
}

const loadDevices = async () => {
  try {
    const res = await cameraApi.devices()
    devices.value = res.data?.rows || res.data || []
  } catch (_) {
    devices.value = []
  }
}

const loadTopo = async () => {
  const res = await mtmcApi.listTopology()
  topology.value = res.data.rows || []
}

const refreshSession = async () => {
  let sawDetect = false
  let sawMtmc = false
  try {
    const list = await mtmcApi.listSessions()
    const rows = list.data.rows || []
    const liveDetect = rows.find((r) => r.running && isDetectKind(r))
    const liveMtmc = rows.find((r) => r.running && !isDetectKind(r))
    if (liveDetect) {
      applyLiveRow(liveDetect)
      sawDetect = true
    }
    if (liveMtmc) {
      applyLiveRow(liveMtmc)
      sawMtmc = true
    }
  } catch (_) {
    /* 列表失败时不打断页面 */
  }
  if (!sawDetect) {
    const saved = detectSessionId.value || localStorage.getItem('mtmc-detect-session-id')
    sawDetect = await pingSaved(saved, 'detect')
    if (!sawDetect) clearDetectSession()
  }
  if (!sawMtmc) {
    const saved = sessionId.value || localStorage.getItem('mtmc-session-id')
    sawMtmc = await pingSaved(saved, 'mtmc')
    if (!sawMtmc) clearSavedSession()
  }
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
    const res = await mtmcApi.startSession({ ...form, ...sessionPayload(), sourceMode: 'camera' })
    sessionId.value = res.data.sessionId
    session.value = res.data
    localStorage.setItem('mtmc-session-id', sessionId.value)
    ElMessage.success('跨镜会话已启动')
    const ids = res.data.cameraIds || []
    const t = String(Date.now())
    ids.forEach((cid) => { overlayBust[cid] = t })
    setTimeout(() => {
      if (!session.value?.running) return
      const t2 = String(Date.now())
      ;(session.value.cameraIds || []).forEach((cid) => { overlayBust[cid] = t2 })
    }, 800)
  } finally {
    busy.value = false
  }
}

const onDetectStart = async () => {
  const mode = detectForm.sourceMode
  if (mode === 'upload') {
    if (uploadMode.value === 'path') {
      if (!(pathSlots[0]?.path || '').trim()) {
        ElMessage.warning('请填写服务器视频路径')
        return
      }
    } else if (!uploadSlots[0]?.file) {
      ElMessage.warning('请选择一个视频')
      return
    }
  }
  if (mode === 'image') {
    if (!(imageSlots[0]?.path || '').trim() && !imageSlots[0]?.file) {
      ElMessage.warning('请上传图片或填写服务器图片路径')
      return
    }
  }
  if (mode === 'stream' && !(streamSlots[0]?.url || '').trim().startsWith('rtsp://')) {
    ElMessage.warning('请填写有效的 RTSP 地址')
    return
  }
  if (mode === 'device' && !(deviceSlots[0]?.device || '').trim()) {
    ElMessage.warning('请选择本机摄像头设备')
    return
  }
  detectBusy.value = true
  try {
    if (detectSessionId.value) {
      try { await mtmcApi.stopSession(detectSessionId.value) } catch (_) { /* ignore */ }
    }
    let res
    const payload = detectPayload()
    if (mode === 'upload') {
      if (uploadMode.value === 'path') {
        res = await mtmcApi.startSessionVideoPaths({
          ...payload,
          videoPaths: [pathSlots[0].path.trim()],
          videoNames: [pathSlots[0].name || '检测源'],
        })
      } else {
        const fd = new FormData()
        fd.append('videos', uploadSlots[0].file)
        fd.append('videoNames', JSON.stringify([uploadSlots[0].name || '检测源']))
        Object.entries(payload).forEach(([k, v]) => fd.append(k, String(v)))
        res = await mtmcApi.startSessionVideos(fd)
      }
    } else if (mode === 'image') {
      if (imageSlots[0].file) {
        const fd = new FormData()
        fd.append('videos', imageSlots[0].file)
        fd.append('videoNames', JSON.stringify([imageSlots[0].name || '图片']))
        Object.entries(payload).forEach(([k, v]) => fd.append(k, String(v)))
        res = await mtmcApi.startSessionVideos(fd)
      } else {
        res = await mtmcApi.startSessionVideoPaths({
          ...payload,
          videoPaths: [imageSlots[0].path.trim()],
          videoNames: [imageSlots[0].name || '图片'],
        })
      }
    } else if (mode === 'stream') {
      res = await mtmcApi.startSessionSources({
        ...payload,
        sources: [{ type: 'rtsp', name: streamSlots[0].name || 'RTSP', url: streamSlots[0].url.trim() }],
      })
    } else {
      res = await mtmcApi.startSessionSources({
        ...payload,
        sources: [{ type: 'device', name: deviceSlots[0].name || '本机摄像头', device: deviceSlots[0].device.trim() }],
      })
    }
    detectSessionId.value = res.data.sessionId
    detectSession.value = res.data
    detectBust.value = String(Date.now())
    localStorage.setItem('mtmc-detect-session-id', detectSessionId.value)
    ElMessage.success('实时检测已启动')
    // 稍后再刷新一次流地址，等待 worker 产出首帧
    setTimeout(() => {
      if (detectSession.value?.running) detectBust.value = String(Date.now())
    }, 800)
  } finally {
    detectBusy.value = false
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
  ElMessage.success('已停止跨镜会话')
}

const onDetectStop = async () => {
  if (!detectSessionId.value) return
  try {
    await mtmcApi.stopSession(detectSessionId.value)
  } catch (_) {
    /* ignore */
  }
  clearDetectSession()
  ElMessage.success('已停止实时检测')
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

const loadEvidence = async () => {
  const sid = sessionId.value || undefined
  const [tRes, aRes] = await Promise.all([
    mtmcApi.listTracklets({
      sessionId: sid,
      globalId: evidenceQ.globalId || undefined,
      objectType: evidenceQ.objectType || undefined,
      pageNum: 1,
      pageSize: 80,
    }),
    mtmcApi.listAssociations({
      sessionId: sid,
      globalId: evidenceQ.globalId || undefined,
      pageNum: 1,
      pageSize: 80,
    }),
  ])
  tracklets.value = tRes.data.rows || []
  associations.value = aRes.data.rows || []
  if (sessionId.value) {
    try {
      const cRes = await mtmcApi.listCandidates(sessionId.value, { status: 'pending' })
      candidates.value = cRes.data.live || []
      candidateDb.value = cRes.data.rows || []
    } catch (_) {
      candidates.value = session.value?.candidates || []
      candidateDb.value = []
    }
  } else {
    candidates.value = []
    candidateDb.value = []
  }
}

const onPromote = async (row) => {
  if (!sessionId.value) {
    ElMessage.warning('请先启动会话')
    return
  }
  await mtmcApi.promoteCandidate({
    sessionId: sessionId.value,
    globalId: row.globalId,
    candidateGlobalId: row.candidateGlobalId,
  })
  ElMessage.success('已晋升合并')
  await loadEvidence()
  await refreshSession()
}

const onReject = async (row) => {
  if (!sessionId.value) return
  await mtmcApi.rejectCandidate({
    sessionId: sessionId.value,
    globalId: row.globalId,
    candidateGlobalId: row.candidateGlobalId,
  })
  ElMessage.success('已驳回')
  await loadEvidence()
}

const loadCrossEvents = async () => {
  const res = await mtmcApi.listCrossEvents({
    sessionId: sessionId.value || undefined,
    globalId: crossQ.globalId || undefined,
    pageNum: 1,
    pageSize: 80,
  })
  const db = res.data.rows || []
  const live = (res.data.live || []).map((e) => ({
    ...e,
    eventTime: e.eventTime || e.ts,
  }))
  crossEvents.value = [...live, ...db]
}

const loadSearchJobs = async () => {
  const res = await mtmcApi.listSearchJobs({ limit: 30 })
  searchJobs.value = res.data.rows || []
}

const submitGlobalTrace = async () => {
  await mtmcApi.submitSearchJob({
    jobType: 'global_trace',
    globalId: searchForm.globalId,
    sessionId: sessionId.value || undefined,
  })
  ElMessage.success('轨迹检索任务已提交')
  await loadSearchJobs()
}

const onQueryFile = (ev) => {
  searchForm.queryFile = ev.target.files?.[0] || null
}

const submitMultiVideoSearch = async () => {
  const fd = new FormData()
  fd.append('jobType', 'multi_video_reid')
  fd.append('cameraIds', searchForm.cameraIds.join(','))
  fd.append('query', searchForm.queryFile)
  fd.append('threshold', '0.45')
  await mtmcApi.submitSearchJob(fd)
  ElMessage.success('多视频检索任务已提交')
  await loadSearchJobs()
}

const showSearchResult = async (row) => {
  const res = await mtmcApi.getSearchJob(row.jobId)
  const result = res.data.result
  if (!result) {
    ElMessage.info(res.data.message || '尚无结果')
    return
  }
  ElMessage.info(`匹配 ${result.matchCount ?? result.eventCount ?? '-'} 条，详见控制台`)
  console.log('MTMC search result', res.data)
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
  await loadDevices()
  await loadTopo()
  form.cameraIds = []
  await refreshSession()
  // Faster while running so per-camera live detections stay fresh
  pollTimer = setInterval(refreshSession, 1500)
})

onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<style scoped>
.mtmc-page { padding: 4px; color: #24344d; }
.page-hero {
  display: grid;
  grid-template-columns: minmax(260px, 1fr) auto auto;
  align-items: center;
  gap: 24px;
  padding: 18px 22px;
  margin-bottom: 14px;
  border: 1px solid #dce7f6;
  border-radius: 12px;
  background: linear-gradient(120deg, #f7faff 0%, #eef5ff 58%, #f7fbff 100%);
}
.hero-title { color: #172a46; font-size: 21px; font-weight: 750; letter-spacing: .5px; }
.hero-subtitle { margin-top: 5px; color: #6f819a; font-size: 13px; }
.hero-flow { display: flex; align-items: center; gap: 8px; color: #416a9f; font-size: 12px; white-space: nowrap; }
.hero-flow span { padding: 5px 9px; border: 1px solid #d5e3f6; border-radius: 12px; background: rgba(255,255,255,.8); }
.hero-flow i { color: #9aacc3; font-style: normal; }
.hero-status { display: flex; align-items: center; gap: 7px; padding: 7px 11px; border-radius: 15px; font-size: 12px; white-space: nowrap; }
.hero-status.idle { color: #68788e; background: #e9eef5; }
.hero-status.running { color: #147550; background: #dff5ea; }
.status-dot { width: 7px; height: 7px; border-radius: 50%; background: currentColor; box-shadow: 0 0 0 3px rgba(80,120,160,.1); }
.mtmc-tabs { border-radius: 10px; overflow: hidden; box-shadow: 0 5px 18px rgba(33, 58, 92, .07); }
.mtmc-tabs :deep(.el-tabs__header) { position: sticky; top: 0; z-index: 20; background: #f7f9fc; }
.mtmc-tabs :deep(.el-tabs__item) { height: 44px; padding: 0 20px; color: #60718a; font-weight: 500; }
.mtmc-tabs :deep(.el-tabs__item.is-active) { color: #2670d9; background: #fff; font-weight: 650; }
.mtmc-tabs :deep(.el-tabs__content) { padding: 16px; background: #fff; }
.tab-intro {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 11px 14px;
  margin-bottom: 14px;
  border-left: 3px solid #409eff;
  border-radius: 4px 8px 8px 4px;
  background: #f4f8fe;
}
.tab-intro > div { display: flex; align-items: baseline; gap: 12px; min-width: 0; }
.tab-intro strong { color: #253a57; font-size: 14px; white-space: nowrap; }
.tab-intro span { color: #72839a; font-size: 12px; }
.mb { margin-bottom: 12px; }
.cfg { margin-bottom: 8px; }
.config-panel {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: 0 8px;
  padding: 14px 16px 6px;
  margin-bottom: 12px;
  border: 1px solid #e1e8f2;
  border-radius: 10px;
  background: #fbfcfe;
}
.config-title { flex: 0 0 100%; display: flex; align-items: baseline; gap: 10px; margin: 0 0 12px; padding-bottom: 8px; border-bottom: 1px solid #e9eef5; }
.config-title.advanced { margin-top: 3px; }
.config-title span { color: #304866; font-size: 13px; font-weight: 700; }
.config-title small { color: #91a0b3; font-size: 11px; }
.advanced-controls { flex: 0 0 100%; margin: 2px 0 12px; border-top: 1px solid #e5ebf3; border-bottom: 1px solid #e5ebf3; }
.advanced-controls :deep(.el-collapse-item__header) { min-height: 46px; height: auto; background: transparent; }
.advanced-controls :deep(.el-collapse-item__wrap) { background: transparent; }
.advanced-title { display: flex; align-items: baseline; gap: 10px; }
.advanced-title span { color: #304866; font-size: 13px; font-weight: 700; }
.advanced-title small { color: #91a0b3; font-size: 11px; font-weight: 400; }
.advanced-grid { display: flex; flex-wrap: wrap; gap: 0 8px; padding-top: 10px; }
.config-panel :deep(.el-form-item) { margin-right: 12px; margin-bottom: 12px; }
.config-panel :deep(.el-form-item__label) { color: #61748d; font-size: 12px; }
.action-bar { flex: 0 0 100%; display: flex; justify-content: flex-end; margin: 2px 0 0 !important; padding: 11px 0 5px; border-top: 1px solid #e6ecf4; }
.action-bar :deep(.el-form-item__content) { width: 100%; justify-content: flex-end; }
.status-panel { overflow: hidden; border-radius: 9px; }
.status-panel :deep(.el-descriptions__label) { color: #718198; background: #f5f8fc !important; }
.status-panel :deep(.el-descriptions__content) { color: #263a56; font-weight: 500; }
.runtime-flight { overflow: hidden; border: 1px solid #cedaea; border-radius: 10px; background: #f7faff; }
.runtime-flight__head { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 12px 14px; color: #eaf3ff; background: #18304f; }
.runtime-flight__head > div { display: flex; align-items: baseline; gap: 12px; min-width: 0; }
.runtime-flight__head strong { font-size: 14px; letter-spacing: .3px; }
.runtime-flight__head span { color: #9fb5d1; font-size: 11px; }
.runtime-risk { border-radius: 0; }
.runtime-models { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px; padding: 12px 14px; }
.runtime-model { min-width: 0; padding: 10px 11px; border: 1px solid #dfe7f2; border-left: 3px solid #8a9aaf; border-radius: 7px; background: #fff; }
.runtime-model.is-success { border-left-color: #3aaa78; }
.runtime-model.is-danger { border-left-color: #e05252; background: #fffafa; }
.runtime-model__role { display: flex; align-items: center; justify-content: space-between; gap: 8px; color: #60748f; font-size: 11px; }
.runtime-model > strong { display: block; margin: 7px 0 6px; overflow: hidden; color: #263b58; font: 650 13px/1.3 ui-monospace, SFMono-Regular, Consolas, monospace; text-overflow: ellipsis; white-space: nowrap; }
.runtime-model__meta { display: flex; flex-wrap: wrap; gap: 4px 10px; color: #7a8ca4; font-size: 10px; }
.runtime-model p { margin: 7px 0 0; color: #b84444; font-size: 10px; line-height: 1.45; }
.runtime-policy { display: grid; gap: 7px; padding: 10px 14px 12px; border-top: 1px solid #dfe7f2; color: #60748f; font-size: 11px; }
.runtime-policy > div { display: flex; flex-wrap: wrap; gap: 6px 14px; }
.runtime-policy__label { min-width: 64px; color: #2d496c; font-weight: 700; }
.tab-toolbar { display: flex; gap: 8px; align-items: center; margin-bottom: 16px; padding: 11px 12px; flex-wrap: wrap; border: 1px solid #e2e9f2; border-radius: 9px; background: #f8fafc; }
.section-title { display: flex; align-items: baseline; gap: 10px; margin: 17px 0 9px; color: #2b405d; }
.section-title span { font-size: 14px; font-weight: 700; }
.section-title small { color: #8a99ac; font-size: 11px; font-weight: 400; }
.mtmc-tabs :deep(.el-table) { overflow: hidden; border-radius: 8px; --el-table-header-bg-color: #f4f7fb; --el-table-header-text-color: #526780; }
.mtmc-tabs :deep(.el-table th.el-table__cell) { font-weight: 650; }
.grid-preview {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(420px, 1fr));
  gap: 12px;
  margin: 12px 0;
}
.detect-views {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin: 12px 0;
}
@media (max-width: 1100px) {
  .page-hero { grid-template-columns: 1fr auto; }
  .hero-flow { display: none; }
  .detect-views { grid-template-columns: 1fr; }
}
.cell {
  background: #fff;
  border-radius: 10px;
  overflow: hidden;
  border: 1px solid #dfe7f3;
  box-shadow: 0 4px 16px rgba(30, 55, 90, 0.08);
  display: flex;
  flex-direction: column;
}
.cell-h {
  color: #cfe0ff;
  font-size: 12px;
  padding: 6px 8px;
  background: #152238;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}
.cell-h-meta { color: #8aa0c2; font-size: 11px; white-space: nowrap; }
.playback-time { color: #d7e7ff; font-variant-numeric: tabular-nums; }
.fps-chip {
  display: inline-block;
  margin-right: 6px;
  padding: 1px 8px;
  border-radius: 999px;
  background: rgba(64, 158, 255, 0.18);
  color: #9fd0ff;
  font-variant-numeric: tabular-nums;
  font-weight: 600;
}
.fps-chip.detect {
  background: rgba(103, 194, 58, 0.2);
  color: #b7eb8f;
}
.cell-v { width: 100%; display: block; min-height: 160px; object-fit: contain; background: #060c18; }
.form-hint { margin-left: 10px; color: #8aa0c2; font-size: 12px; }
.cell-dets {
  background: #f7f9fc;
  padding: 10px;
  border-top: 1px solid #e4eaf3;
}
.result-summary { display: flex; align-items: center; gap: 7px; color: #263750; font-size: 12px; font-weight: 600; margin-bottom: 8px; }
.summary-chip { padding: 2px 7px; border-radius: 10px; font-weight: 500; }
.summary-chip.person { color: #18875d; background: #e7f7f0; }
.summary-chip.vehicle { color: #b76a0b; background: #fff3df; }
.summary-total { margin-left: auto; color: #8492a6; font-weight: 400; }
.result-list { display: flex; flex-direction: column; gap: 6px; max-height: 190px; overflow: auto; padding-right: 2px; }
.result-item { min-width: 0; display: flex; align-items: center; gap: 9px; padding: 8px 9px; background: #fff; border: 1px solid #e7ecf4; border-radius: 7px; }
.result-type { flex: 0 0 26px; height: 26px; display: grid; place-items: center; border-radius: 7px; font-size: 12px; font-weight: 700; }
.result-type.person { color: #16835b; background: #e5f7ef; }
.result-type.vehicle { color: #bd6d08; background: #fff0d8; }
.result-main { flex: 1; min-width: 0; }
.result-primary, .result-secondary { display: flex; align-items: center; gap: 7px; min-width: 0; }
.result-primary { margin-bottom: 3px; }
.result-identity { color: #263750; font-size: 13px; font-weight: 600; white-space: nowrap; }
.result-label { color: #8492a6; font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.result-secondary { color: #8a97aa; font-size: 11px; }
.global-link { max-width: 180px; padding: 0; border: 0; background: transparent; color: #3578e5; font: inherit; cursor: pointer; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.global-link:hover { color: #1d5fc8; text-decoration: underline; }
.result-status { flex: 0 0 auto; display: flex; flex-direction: column; align-items: flex-end; gap: 4px; }
.result-score { color: #52647c; font-size: 11px; font-variant-numeric: tabular-nums; }
.mode-pill { padding: 2px 6px; border-radius: 9px; background: #edf1f7; font-size: 10px; white-space: nowrap; }
.result-empty { padding: 18px 8px; color: #98a4b5; font-size: 12px; text-align: center; background: #fff; border: 1px dashed #dce3ed; border-radius: 7px; }
@media (max-width: 720px) {
  .grid-preview { grid-template-columns: 1fr; }
  .result-label { display: none; }
}
.muted { color: #7a8ba8; }
.mode-ok { color: #67c23a; }
.mode-sticky { color: #79bbff; }
.mode-cand { color: #e6a23c; }
.upload-slots {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin: 0 0 12px 100px;
  max-width: 720px;
}
.upload-slot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}
.upload-hint { margin: -4px 0 12px 100px; }
.hint { color: #8899aa; font-size: 12px; }
.guide-wrap { padding: 4px 6px 16px; max-width: 1280px; margin: 0 auto; }
.guide-h3 { margin: 24px 0 11px; padding-left: 10px; border-left: 3px solid #76a9ee; font-size: 15px; font-weight: 700; color: #1f2d3d; }
.guide-h3:first-of-type { margin-top: 4px; }
.guide-p, .guide-ol { font-size: 13px; line-height: 1.7; color: #5a6b87; margin: 0 0 12px; }
.guide-ol { padding-left: 20px; }
.guide-ol li { margin-bottom: 6px; }
.guide-steps { margin: 16px 0 24px; padding: 18px 8px 10px; border: 1px solid #e5ebf3; border-radius: 10px; background: #fbfcfe; }
.guide-alerts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin-bottom: 16px; }
.guide-alerts :deep(.el-alert) { align-items: flex-start; min-height: 82px; }
.guide-wrap :deep(.el-descriptions) { overflow: hidden; border-radius: 9px; }
.guide-foot { font-size: 12px; color: #8a9bb5; margin-top: 8px; }
.guide-wrap code { font-size: 12px; background: #f0f4f8; padding: 1px 5px; border-radius: 4px; }
@media (max-width: 760px) {
  .mtmc-page { padding: 0; }
  .page-hero { grid-template-columns: 1fr; gap: 10px; padding: 14px; }
  .hero-status { width: fit-content; }
  .mtmc-tabs :deep(.el-tabs__item) { padding: 0 12px; font-size: 12px; }
  .mtmc-tabs :deep(.el-tabs__content) { padding: 11px; }
  .tab-intro { align-items: flex-start; }
  .tab-intro > div { display: block; }
  .tab-intro span { display: block; margin-top: 4px; line-height: 1.5; }
  .config-panel { padding: 12px 10px 4px; }
  .config-title { display: block; }
  .config-title small { display: block; margin-top: 3px; line-height: 1.5; }
  .advanced-title { display: block; padding: 8px 0; }
  .advanced-title small { display: block; margin-top: 3px; line-height: 1.4; }
  .config-panel :deep(.el-form-item) { width: 100%; margin-right: 0; }
  .config-panel :deep(.el-form-item__content) { flex-wrap: wrap; }
  .action-bar :deep(.el-form-item__content) { justify-content: flex-start; gap: 6px; }
  .cell-h { align-items: flex-start; flex-direction: column; }
  .cell-h-meta { white-space: normal; line-height: 1.5; }
  .runtime-flight__head { align-items: flex-start; }
  .runtime-flight__head > div { display: block; }
  .runtime-flight__head span { display: block; margin-top: 3px; line-height: 1.4; }
  .guide-alerts { grid-template-columns: 1fr; }
}
</style>
