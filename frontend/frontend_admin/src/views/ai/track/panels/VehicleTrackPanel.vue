<template>
  <div class="vehicle-root">
    <el-tabs v-model="activeTab" type="border-card" class="vehicle-tabs">
      <!-- ── 任务配置 ── -->
      <el-tab-pane label="任务配置" name="config">
        <el-card shadow="never" class="cfg-card">
          <el-form :inline="true" class="cfg-form">
            <el-form-item label="模式">
              <el-select
                v-model="mode"
                placeholder="选择输入源"
                style="width: 160px"
                :disabled="busy"
                @change="onModeChange"
              >
                <el-option label="图片识别" value="image" />
                <el-option label="视频文件" value="file" />
                <el-option label="本地摄像头" value="local" />
                <el-option label="网络摄像头" value="network" />
              </el-select>
            </el-form-item>
            <el-form-item label="车辆检测">
              <el-select v-model="detectId" placeholder="YOLO 车辆检测" style="width: 220px" filterable :disabled="busy">
                <el-option
                  v-for="m in detectModels"
                  :key="m.id"
                  :label="modelOptionLabel(m, 'detect')"
                  :value="m.id"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="车牌检测">
              <el-select v-model="plateId" placeholder="可选（推荐 YOLO26 四点/bbox）" clearable style="width: 240px" filterable :disabled="busy">
                <el-option
                  v-for="m in plateModels"
                  :key="m.id"
                  :label="modelOptionLabel(m, 'plate')"
                  :value="m.id"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="OCR 检测">
              <el-select v-model="detId" placeholder="RapidOCR det" clearable style="width: 180px" filterable :disabled="busy">
                <el-option
                  v-for="m in detModels"
                  :key="m.id"
                  :label="modelOptionLabel(m, 'ocrDet')"
                  :value="m.id"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="OCR 识别">
              <el-select v-model="recId" placeholder="RapidOCR rec" clearable style="width: 180px" filterable :disabled="busy">
                <el-option
                  v-for="m in recModels"
                  :key="m.id"
                  :label="modelOptionLabel(m, 'ocrRec')"
                  :value="m.id"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="置信度">
              <el-slider v-model="conf" :min="0.05" :max="0.95" :step="0.05" style="width: 120px" :disabled="busy" />
            </el-form-item>
            <el-form-item label="分辨率">
              <el-select v-model="imgsz" style="width: 100px" :disabled="busy">
                <el-option :value="640" label="640" />
                <el-option :value="480" label="480" />
                <el-option :value="320" label="320" />
              </el-select>
            </el-form-item>
            <el-form-item v-if="mode !== 'image'" label="计数方式">
              <el-select v-model="countMode" style="width: 130px" :disabled="busy" @change="onCountModeChange">
                <el-option label="多边形区域" value="zone" />
                <el-option label="计数线" value="line" />
                <el-option label="不计数" value="none" />
              </el-select>
            </el-form-item>
            <el-form-item v-if="mode !== 'image'" label="统计类别">
              <el-select v-model="classPreset" style="width: 120px" :disabled="busy">
                <el-option label="仅车" value="vehicle" />
                <el-option label="人+车" value="person_vehicle" />
                <el-option label="仅人" value="person" />
                <el-option label="全部" value="all" />
              </el-select>
            </el-form-item>
            <el-form-item v-if="mode !== 'image' && countMode === 'zone'" label="边框色">
              <el-color-picker v-model="zoneBorderColor" :disabled="busy" />
            </el-form-item>
            <el-form-item v-if="mode !== 'image' && countMode === 'zone'" label="填充色">
              <el-color-picker v-model="zoneFillColor" show-alpha :disabled="busy" />
            </el-form-item>
            <el-form-item>
              <el-checkbox v-model="enableOcr" :disabled="busy">号牌 OCR</el-checkbox>
              <el-checkbox v-if="mode !== 'image'" v-model="enableSpeed" :disabled="busy" style="margin-left: 8px">测速</el-checkbox>
              <el-checkbox v-if="mode !== 'image'" v-model="enableTrail" :disabled="busy" style="margin-left: 8px">运动轨迹</el-checkbox>
              <el-checkbox v-if="mode === 'image'" v-model="vehicleOnly" :disabled="busy" style="margin-left: 8px">仅车辆类</el-checkbox>
            </el-form-item>
            <el-form-item v-if="enableSpeed && mode !== 'image'" label="测速设置" class="speed-setting-item">
              <div class="speed-settings">
                <el-radio-group v-model="speedMode" :disabled="busy" @change="onSpeedModeChange">
                  <el-radio-button label="double-line">双线标定（推荐）</el-radio-button>
                  <el-radio-button label="scale">局部米/像素</el-radio-button>
                </el-radio-group>
                <template v-if="speedMode === 'double-line'">
                  <div class="speed-field-row">
                    <span>两线实际距离</span>
                    <el-input-number v-model="speedDistanceM" :min="0.01" :step="1" :precision="2" style="width: 130px" :disabled="busy" />
                    <span>米</span>
                    <span>速度上限</span>
                    <el-input-number v-model="speedMaxKmh" :min="30" :max="400" :step="10" :precision="0" style="width: 120px" :disabled="busy" />
                    <span>km/h</span>
                  </div>
                  <div class="speed-field-row speed-draw-controls">
                    <el-button size="small" type="primary" plain :disabled="!canDrawSpeedLines" @click="setDrawTool('speedA')">绘制测速线 A</el-button>
                    <el-button size="small" type="warning" plain :disabled="!canDrawSpeedLines" @click="setDrawTool('speedB')">绘制测速线 B</el-button>
                    <el-button v-if="activeSpeedLineA || activeSpeedLineB" size="small" link type="primary" :disabled="busy" @click="clearActiveSpeedLines">清除测速线</el-button>
                    <el-tag size="small" :type="activeSpeedLineA ? 'success' : 'info'">A{{ activeSpeedLineA ? '已绘制' : '待绘制' }}</el-tag>
                    <el-tag size="small" :type="activeSpeedLineB ? 'success' : 'info'">B{{ activeSpeedLineB ? '已绘制' : '待绘制' }}</el-tag>
                  </div>
                  <div class="speed-help">在{{ mode === 'file' ? '视频首帧' : '实时画面' }}依次点击两点绘制 A、B 两条测速线。</div>
                </template>
                <template v-else>
                  <div class="speed-field-row">
                    <span>米/像素</span>
                    <el-input-number v-model="metersPerPixel" :min="0.0001" :step="0.001" :precision="4" placeholder="请标定" style="width: 130px" :disabled="busy" />
                    <span>速度上限</span>
                    <el-input-number v-model="speedMaxKmh" :min="30" :max="400" :step="10" :precision="0" style="width: 120px" :disabled="busy" />
                    <span>km/h</span>
                  </div>
                  <el-alert class="speed-scale-warning" type="warning" :closable="false" title="米/像素需按当前分辨率和道路区域标定，结果仅供估算参考。" />
                </template>
              </div>
            </el-form-item>
            <el-form-item v-if="mode === 'image'">
              <el-upload :show-file-list="false" :auto-upload="false" :on-change="onPickImage" accept="image/*">
                <el-button :icon="UploadFilled">选择图片</el-button>
              </el-upload>
            </el-form-item>
            <el-form-item v-if="mode === 'file'">
              <el-upload :show-file-list="false" :auto-upload="false" :on-change="onPick" accept="video/*">
                <el-button :icon="UploadFilled">选择视频</el-button>
              </el-upload>
            </el-form-item>
            <el-form-item v-if="mode === 'local'" label="摄像头">
              <el-select v-model="deviceId" placeholder="默认" style="width: 180px" :disabled="liveRunning" @change="onLiveSourceChange">
                <el-option v-for="d in devices" :key="d.deviceId" :label="d.label || `摄像头 ${d.idx}`" :value="d.deviceId" />
              </el-select>
            </el-form-item>
            <el-form-item v-if="mode === 'network'" label="网络摄像头">
              <el-select v-model="cameraId" placeholder="选择" filterable style="width: 200px" :disabled="liveRunning" :loading="camerasLoading" @change="onLiveSourceChange">
                <el-option v-for="c in managedCameras" :key="c.id" :label="cameraLabel(c)" :value="c.id" />
              </el-select>
              <el-button link type="primary" :disabled="liveRunning" @click="loadManagedCameras">刷新</el-button>
            </el-form-item>
            <el-form-item v-if="mode === 'image'" class="alert-action-item">
              <div class="alert-action-row">
                <el-button type="primary" :icon="VideoPlay" :loading="imageRunning" :disabled="!canRunImage" @click="runImage">开始识别</el-button>
                <el-button :icon="Refresh" style="margin-left: 8px" @click="clearImage">清空</el-button>
                <el-button v-if="hasResults" link type="primary" @click="activeTab = 'results'">查看结果</el-button>
              </div>
            </el-form-item>
            <el-form-item v-if="mode === 'file'" class="alert-action-item">
              <div class="alert-action-row">
                <el-button type="primary" :icon="VideoPlay" :loading="fileRunning" :disabled="!canRunFile" @click="runVideo">开始追踪</el-button>
                <el-checkbox v-model="alertEnabled" :disabled="fileRunning" style="margin-left: 12px">启用告警</el-checkbox>
                <el-button :icon="Refresh" style="margin-left: 8px" @click="clearFile">清空</el-button>
                <el-button v-if="hasResults" link type="primary" @click="activeTab = 'results'">查看结果</el-button>
              </div>
            </el-form-item>
            <el-form-item v-if="mode === 'local' || mode === 'network'" class="alert-action-item">
              <div class="alert-action-row">
                <el-button v-if="!livePreviewing" type="primary" :icon="VideoCamera" :loading="previewOpening" :disabled="!canOpenLivePreview || previewOpening" @click="openLivePreview">打开预览</el-button>
                <el-button v-else-if="!liveRunning" type="primary" :icon="VideoPlay" :disabled="!canStartLive" @click="liveStart">开始分析</el-button>
                <el-button v-else type="danger" :icon="SwitchButton" @click="liveStop">停止</el-button>
                <el-button v-if="livePreviewing && !liveRunning" :icon="SwitchButton" @click="liveStop">关闭预览</el-button>
                <el-checkbox v-model="alertEnabled" :disabled="liveRunning" style="margin-left: 12px">启用告警</el-checkbox>
                <el-button v-if="liveLine" link type="primary" @click="clearLiveLine">清除线</el-button>
                <el-button v-if="liveRegion" link type="primary" @click="clearLiveRegion">清除区域</el-button>
                <el-button v-if="countMode==='zone' && liveRegionPts.length >= 3 && !liveRegion" link type="success" @click="finishLiveRegion">闭合区域</el-button>
                <el-button v-if="recordCount" link type="primary" :icon="Download" @click="exportCsv">导出 CSV</el-button>
                <el-button link type="primary" @click="activeTab = 'results'">实时画面</el-button>
              </div>
            </el-form-item>
          </el-form>
          <el-alert
            v-if="!detectModels.length"
            type="warning"
            :closable="false"
            title="请先到「模型管理」拉取 YOLO 车辆检测模型（如 YOLO26）。"
          />
          <el-alert
            v-else-if="enableOcr && (!detModels.length || !recModels.length)"
            type="warning"
            :closable="false"
            title="号牌 OCR 需 RapidOCR 检测 + 识别模型；未配置时将跳过 OCR。"
          />
          <el-alert
            v-else
            type="info"
            :closable="false"
            class="flow-tip"
            title="支持多边形区域/计数线的人车进出统计；车牌推荐 YOLO26s 四点 pose → YOLO26n bbox；OCR 推荐 PP-OCRv6 small det+rec。"
          />
        </el-card>

        <!-- 配置页：输入源预览 / 画线 -->
        <template v-if="mode === 'image'">
          <el-card v-if="imagePreviewUrl" shadow="never" class="cfg-card">
            <div class="section-title">原图预览</div>
            <img :src="imagePreviewUrl" class="preview-img" alt="车辆原图" />
          </el-card>
          <el-empty v-else description="选择图片后可在此预览，识别结果在「追踪结果」页查看" :image-size="80" />
        </template>

        <template v-else-if="mode === 'file'">
          <el-row :gutter="16">
            <el-col v-if="previewUrl" :xs="24" :lg="12">
              <el-card shadow="never" class="cfg-card">
                <div class="section-title">原视频预览</div>
                <video :src="previewUrl" controls class="player" />
              </el-card>
            </el-col>
            <el-col v-if="file" :xs="24" :lg="previewUrl ? 12 : 24">
              <el-card shadow="never" class="cfg-card">
                <div class="line-tip">
                  <template v-if="speedMode === 'double-line' && enableSpeed && drawTool !== 'count'">
                    正在绘制测速线 {{ drawTool === 'speedA' ? 'A（青色）' : 'B（琥珀色）' }}：请点击第 {{ fileSpeedDrawPointCount + 1 }} 个点。
                  </template>
                  <template v-else-if="countMode === 'zone'">
                    绘制多边形：依次点击添加顶点（≥3），完成后点「闭合区域」。
                    <el-button link type="success" :disabled="fileRegionPts.length < 3" @click="finishFileRegion">闭合区域</el-button>
                    <el-button link type="primary" @click="clearFileRegion">清除区域</el-button>
                    <span v-if="fileRegion" class="meta">已设置监控区域（{{ fileRegion.length }} 点）</span>
                    <span v-else-if="fileRegionPts.length" class="meta">已点 {{ fileRegionPts.length }} 个顶点</span>
                  </template>
                  <template v-else-if="countMode === 'line'">
                    首帧画计数线（可选）：点两点。
                    <el-button link type="primary" @click="clearFileLine">清除线</el-button>
                  </template>
                  <template v-else>当前不计数，可直接开始追踪。</template>
                </div>
                <canvas ref="frameCanvas" class="frame-canvas" @click="onFileCanvasClick" />
              </el-card>
            </el-col>
          </el-row>
          <el-empty v-if="!file" description="选择视频后可预览并设置区域/越线，追踪结果在「追踪结果」页查看" :image-size="80" />
        </template>

        <template v-else>
          <el-alert
            type="info"
            :closable="false"
            show-icon
            title="实时模式：先打开摄像头预览并绘制计数/测速标定，再点「开始分析」；画面与过车记录在「追踪结果」页查看。"
          />
        </template>
      </el-tab-pane>

      <!-- ── 追踪结果 ── -->
      <el-tab-pane name="results">
        <template #label>
          <span class="tab-label">
            追踪结果
            <el-badge v-if="resultBadge" :value="resultBadge" :max="99" class="tab-badge" />
          </span>
        </template>

        <!-- 图片结果 -->
        <template v-if="mode === 'image'">
          <el-card shadow="never">
            <el-empty v-if="!imageRunning && !imageResultSrc" description="选择车辆图片并开始识别后，标注图与明细将显示在此" />
            <div v-else-if="imageRunning" class="progress-box">
              <div class="progress-title">识别中…</div>
              <el-progress :percentage="100" :indeterminate="true" :stroke-width="18" />
            </div>
            <div v-else>
              <div class="section-title">
                识别结果
                <el-button link type="primary" :icon="Download" @click="downloadImageResult">下载标注图</el-button>
                <el-button link type="primary" @click="activeTab = 'config'">返回配置</el-button>
              </div>
              <div class="image-compare">
                <figure>
                  <figcaption>原始图片</figcaption>
                  <img :src="imagePreviewUrl" class="preview-img" alt="原始车辆图片" />
                </figure>
                <figure>
                  <figcaption>识别结果</figcaption>
                  <img :src="imageResultSrc" class="preview-img result-img" alt="识别结果" />
                </figure>
              </div>
              <div class="stats">
                <el-tag type="success" effect="dark">车辆 {{ imageDets.length }}</el-tag>
                <el-tag type="warning" effect="dark">号牌 {{ imagePlateCount }}</el-tag>
              </div>
              <el-table v-if="imageDets.length" :data="imageDets" size="small" border max-height="280" class="rec-table">
                <el-table-column prop="trackId" label="ID" width="70" />
                <el-table-column prop="className" label="车型" width="100" />
                <el-table-column prop="confidence" label="置信度" width="90">
                  <template #default="{ row }">{{ Number(row.confidence || 0).toFixed(2) }}</template>
                </el-table-column>
                <el-table-column prop="plate" label="号牌" min-width="120" />
                <el-table-column prop="plateScore" label="OCR 分" width="90">
                  <template #default="{ row }">{{ row.plateScore != null ? Number(row.plateScore).toFixed(2) : '—' }}</template>
                </el-table-column>
                <el-table-column prop="plateSource" label="车牌来源" width="100" />
              </el-table>
            </div>
          </el-card>
        </template>

        <!-- 视频文件结果 -->
        <template v-else-if="mode === 'file'">
          <el-card shadow="never">
            <div v-if="fileRunning" class="progress-box">
              <div class="progress-title">追踪中… {{ processed }}/{{ total || '?' }} 帧</div>
              <el-progress :percentage="percent" :stroke-width="18" :text-inside="true" striped striped-flow />
            </div>
            <el-empty v-else-if="!resultUrl" description="在「任务配置」选择模型与视频并开始追踪后，结果视频将显示在此" />
            <div v-else>
              <div class="section-title">
                追踪结果
                <el-button link type="primary" :icon="Download" @click="downloadVideo">下载视频</el-button>
                <el-button v-if="fileRecords.length" link type="primary" @click="downloadFileCsv">下载过车 CSV</el-button>
                <el-button link type="primary" @click="activeTab = 'config'">返回配置</el-button>
              </div>
              <video :key="resultUrl" :src="resultUrl" controls preload="metadata" class="player" />
              <div class="stats">
                <el-tag type="success" effect="dark">唯一目标 {{ stats.uniqueObjects ?? '-' }}</el-tag>
                <el-tag v-if="stats.crossing" type="warning" effect="dark">
                  {{ stats.regionEnabled ? '区域' : '越线' }}
                  进{{ stats.crossing.in }} 出{{ stats.crossing.out }}
                  <template v-if="stats.crossing.net != null"> 净{{ stats.crossing.net }}</template>
                </el-tag>
                <el-tag v-if="stats.crossing?.person" type="success" effect="plain">
                  人 进{{ stats.crossing.person.in }} 出{{ stats.crossing.person.out }}
                </el-tag>
                <el-tag v-if="stats.crossing?.vehicle" type="primary" effect="plain">
                  车 进{{ stats.crossing.vehicle.in }} 出{{ stats.crossing.vehicle.out }}
                </el-tag>
                <el-tag v-if="stats.recordCount" type="info" effect="dark">过车记录 {{ stats.recordCount }}</el-tag>
                <el-tag v-if="stats.congestionSummary" type="danger" effect="dark">
                  拥堵帧占比 {{ Math.round((stats.congestionSummary.busyRatio || 0) * 100) }}%
                </el-tag>
              </div>
              <el-table v-if="fileRecords.length" :data="fileRecords" size="small" border max-height="240" class="rec-table">
                <el-table-column prop="trackId" label="ID" width="70" />
                <el-table-column prop="className" label="车型" width="90" />
                <el-table-column prop="plate" label="号牌" min-width="100" />
                <el-table-column label="速度" width="180">
                  <template #default="{ row }">
                    <span>{{ speedDisplay(row) }}</span>
                    <el-tag v-if="speedSourceLabel(row)" size="small" class="speed-source-tag">{{ speedSourceLabel(row) }}</el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="plateScore" label="OCR 分" width="80" />
              </el-table>
            </div>
          </el-card>
        </template>

        <!-- 实时画面 -->
        <template v-else>
          <el-card shadow="never">
            <div class="section-title">
              实时画面
              <el-button v-if="!livePreviewing" type="primary" size="small" :icon="VideoCamera" :loading="previewOpening" :disabled="!canOpenLivePreview || previewOpening" @click="openLivePreview">打开预览</el-button>
              <el-button v-else-if="!liveRunning" type="primary" size="small" :icon="VideoPlay" :disabled="!canStartLive" @click="liveStart">开始分析</el-button>
              <el-button v-else type="danger" size="small" :icon="SwitchButton" @click="liveStop">停止</el-button>
              <el-button v-if="livePreviewing && !liveRunning" size="small" :icon="SwitchButton" @click="liveStop">关闭预览</el-button>
              <el-button v-if="livePreviewing && !liveRunning && enableSpeed && speedMode === 'double-line'" size="small" type="primary" plain @click="setDrawTool('speedA')">绘制测速线 A</el-button>
              <el-button v-if="livePreviewing && !liveRunning && enableSpeed && speedMode === 'double-line'" size="small" type="warning" plain @click="setDrawTool('speedB')">绘制测速线 B</el-button>
              <el-button v-if="liveLine" link type="primary" @click="clearLiveLine">清除线</el-button>
              <el-button v-if="liveSpeedLineA || liveSpeedLineB" link type="primary" @click="clearLiveSpeedLines">清除测速线</el-button>
              <el-button v-if="liveRegion" link type="primary" @click="clearLiveRegion">清除区域</el-button>
              <el-button v-if="countMode==='zone' && liveRegionPts.length >= 3 && !liveRegion" link type="success" @click="finishLiveRegion">闭合区域</el-button>
              <el-button v-if="recordCount" link type="primary" :icon="Download" @click="exportCsv">导出 CSV</el-button>
              <el-button link type="primary" @click="activeTab = 'config'">返回配置</el-button>
            </div>
            <div class="cam-wrap">
              <div class="cam-stage">
                <video v-show="mode === 'local'" ref="camVideo" class="cam-video" autoplay playsinline muted />
                <img v-show="mode === 'network'" ref="streamImg" class="cam-video" alt="网络摄像头" />
                <canvas ref="camCanvas" class="cam-canvas" @click="onLiveClick" />
                <div v-if="!livePreviewing" class="cam-hint">
                  <template v-if="countMode === 'zone'">
                    {{ mode === 'network' ? '点「打开预览」后在画面点 ≥3 点并闭合区域' : '点「打开预览」后绘制多边形监控区域' }}
                  </template>
                  <template v-else-if="countMode === 'line'">
                    {{ mode === 'network' ? '点「打开预览」后可画计数线' : '点「打开预览」后可在画面点两点画计数线' }}
                  </template>
                  <template v-else>
                    {{ mode === 'network' ? '选择网络摄像头后点「打开预览」' : '点「打开预览」启用摄像头' }}
                  </template>
                </div>
                <div v-if="livePreviewing && !liveRunning && speedMode === 'double-line' && enableSpeed && drawTool !== 'count'" class="cam-draw-tip">
                  正在绘制测速线 {{ drawTool === 'speedA' ? 'A（青色）' : 'B（琥珀色）' }}：请点击第 {{ liveSpeedDrawPointCount + 1 }} 个点。
                </div>
                <div v-if="liveRunning" class="cam-hud">
                  <el-tag type="success" effect="dark">{{ camFps }} FPS</el-tag>
                  <el-tag type="warning" effect="dark">目标 {{ liveDets.length }}</el-tag>
                  <el-tag v-if="liveLine || liveRegion" type="danger" effect="dark">进{{ crossing.in }} 出{{ crossing.out }}</el-tag>
                  <el-tag v-if="crossing.person" type="success" effect="plain">人 {{ crossing.person.in }}/{{ crossing.person.out }}</el-tag>
                  <el-tag v-if="crossing.vehicle" type="primary" effect="plain">车 {{ crossing.vehicle.in }}/{{ crossing.vehicle.out }}</el-tag>
                  <el-tag :type="congestionTagType" effect="dark">{{ congestion.label || '—' }}</el-tag>
                  <el-tag v-if="recordCount" type="info" effect="dark">记录 {{ recordCount }}</el-tag>
                </div>
              </div>
            </div>
            <el-table v-if="recentRecords.length" :data="recentRecords" size="small" border max-height="200" class="rec-table">
              <el-table-column prop="trackId" label="ID" width="70" />
              <el-table-column prop="className" label="车型" width="90" />
              <el-table-column prop="plate" label="号牌" min-width="100" />
              <el-table-column label="速度" width="180">
                <template #default="{ row }">
                  <span>{{ speedDisplay(row) }}</span>
                  <el-tag v-if="speedSourceLabel(row)" size="small" class="speed-source-tag">{{ speedSourceLabel(row) }}</el-tag>
                </template>
              </el-table-column>
            </el-table>
          </el-card>
        </template>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { ElMessage, ElNotification } from 'element-plus'
import {
  UploadFilled, VideoPlay, Refresh, Download, VideoCamera, SwitchButton,
} from '@element-plus/icons-vue'
import { modelApi, vehicleApi, alertApi } from '../../../../api/ai'
import { cameraApi } from '../../../../api/camera'
import { pickRecommendedModel } from '../../../../utils/trackModelRecommendation'
import {
  createLivePreviewLifecycle,
  releaseOpenedStream,
  waitForImageReady,
} from '../../../../utils/livePreviewLifecycle'

const ALERT_SOURCE_KEY = 'vehicle-camera'

const activeTab = ref('config')
const allModels = ref([])
const detectId = ref(null)
const plateId = ref(null)
const detId = ref(null)
const recId = ref(null)
const conf = ref(0.25)
const imgsz = ref(640)
const enableOcr = ref(true)
const enableSpeed = ref(true)
const enableTrail = ref(true)
const vehicleOnly = ref(true)
const countMode = ref('zone')  // zone | line | none
const classPreset = ref('person_vehicle')
const zoneBorderColor = ref('#2196f3')
const zoneFillColor = ref('rgba(33, 150, 243, 0.12)')
const metersPerPixel = ref(null)
const speedMode = ref('double-line') // double-line | scale
const speedDistanceM = ref(10)
const speedMaxKmh = ref(240)
const drawTool = ref('count') // count | speedA | speedB
const alertEnabled = ref(false)

/** 推荐权重优先级（高精度 + CPU 友好，面向行驶车牌） */
const DETECT_PREF = [
  /yolo26s/i,
  /yolo26n/i,
  /yolo11s/i,
  /yolo11n/i,
  /yolov8s/i,
  /yolov8n/i,
]
const PLATE_PREF = [
  /yolo26s-plate-pose/i,
  /yolo26n-plate/i,
  /yolo26n-obb/i,
  /yolo26n-p2-plate/i,
  /yolov11-license-plate-n/i,
  /yolov11-license-plate-s/i,
  /yolov11-license-plate|license-plate-finetune-v1/i,
  /yolov8-license-plate|Koushim/i,
  /keremberke-yolov5m/i,
  /keremberke-yolov5n|yolov5n-license-plate/i,
  /license-plate-detection/i,
  /车牌检测/i,
]
const OCR_DET_PREF = [/pp-ocrv6.*det|v6.*small.*det|OCRv6_small_det/i, /pp-ocrv5.*det/i, /pp-ocrv4.*det|ch_PP-OCRv4.*det/i]
const OCR_REC_PREF = [/pp-ocrv6.*rec|v6.*small.*rec|OCRv6_small_rec/i, /pp-ocrv5.*rec/i, /pp-ocrv4.*rec|ch_PP-OCRv4.*rec/i]

const scoreByPref = (m, prefs) => {
  const text = `${m.modelKey || ''} ${m.modelName || ''} ${m.filePath || ''}`
  const idx = prefs.findIndex((re) => re.test(text))
  return idx === -1 ? 1000 : idx
}

const sortByPref = (list, prefs) =>
  [...list].sort((a, b) => scoreByPref(a, prefs) - scoreByPref(b, prefs) || String(a.modelName).localeCompare(String(b.modelName)))

const pickPreferred = (list, prefs) => {
  if (!list.length) return null
  return sortByPref(list, prefs)[0]
}

const modelOptionLabel = (m, kind) => {
  const text = `${m.modelKey || ''} ${m.modelName || ''}`
  let tag = ''
  if (kind === 'detect' && m.id === pickRecommendedModel(detectModels.value, 'vehicle')?.id) tag = ' · 推荐'
  if (kind === 'plate' && /yolo26s-plate-pose/i.test(text)) tag = ' · 推荐·透视四点'
  else if (kind === 'plate' && /yolo26n-plate/i.test(text)) tag = ' · 推荐·bbox'
  else if (kind === 'plate' && /yolo26n-obb/i.test(text)) tag = ' · OBB 旋转框'
  else if (kind === 'plate' && /yolo26n-p2-plate/i.test(text)) tag = ' · P2 自训脚手架'
  else if (kind === 'plate' && /yolov11-license-plate-s/i.test(text)) tag = ' · 兼容·精度'
  else if (kind === 'plate' && /yolov11-license-plate-n/i.test(text)) tag = ' · 兼容·CPU'
  else if (kind === 'plate' && /yolov8-license-plate|Koushim/i.test(text)) tag = ' · YOLOv8'
  else if (kind === 'plate' && /yolov5m-license-plate/i.test(text)) tag = ' · 兼容·YOLOv5m'
  else if (kind === 'plate' && /yolov5n-license-plate|keremberke-yolov5n/i.test(text)) tag = ' · 兼容·YOLOv5n'
  else if ((kind === 'ocrDet' || kind === 'ocrRec') && /pp-ocrv6|v6_small/i.test(text)) tag = ' · 推荐'
  return `${m.modelName}${tag}`
}

const detectModels = computed(() => {
  const yolo = allModels.value.filter(
    (m) =>
      m.library === 'ultralytics' &&
      m.task === 'object-detection' &&
      m.filePath &&
      m.status === '0' &&
      !/plate|license|车牌/i.test(`${m.modelKey} ${m.modelName}`),
  )
  const traffic = yolo.filter(
    (m) =>
      /车|交通|vehicle|traffic|yolo26|yolo11|yolov8/i.test(`${m.modelName} ${m.category} ${m.modelKey}`),
  )
  return sortByPref(traffic.length ? traffic : yolo, DETECT_PREF)
})
const plateModels = computed(() => {
  const list = allModels.value.filter(
    (m) =>
      m.library === 'ultralytics' &&
      ['object-detection', 'obb', 'pose-estimation'].includes(m.task) &&
      m.filePath &&
      m.status === '0' &&
      (/车牌|plate|license/i.test(`${m.modelName} ${m.modelKey}`) || /yolo26n-obb/i.test(`${m.modelKey}`)),
  )
  return sortByPref(list, PLATE_PREF)
})

const detModels = computed(() =>
  sortByPref(
    allModels.value.filter((m) => m.library === 'rapidocr' && m.task === 'text-detection' && m.filePath && m.status === '0'),
    OCR_DET_PREF,
  ),
)
const recModels = computed(() =>
  sortByPref(
    allModels.value.filter((m) => m.library === 'rapidocr' && m.task === 'text-recognition' && m.filePath && m.status === '0'),
    OCR_REC_PREF,
  ),
)

const mode = ref('image')
const file = ref(null)
const previewUrl = ref('')
const fileRunning = ref(false)
const processed = ref(0)
const total = ref(0)
const resultUrl = ref('')
const stats = ref({})
const fileRecords = ref([])
let pollTimer = null
let blobUrl = ''

const imageFile = ref(null)
const imagePreviewUrl = ref('')
const imageRunning = ref(false)
const imageResultSrc = ref('')
const imageDets = ref([])
const imagePlateCount = ref(0)

const frameCanvas = ref(null)
const fileLinePts = ref([])
const fileLine = ref(null)
const fileSpeedLineAPts = ref([])
const fileSpeedLineBPts = ref([])
const fileSpeedLineA = ref(null)
const fileSpeedLineB = ref(null)
const fileRegionPts = ref([])
const fileRegion = ref(null)
let frameBaseImage = null

const devices = ref([])
const deviceId = ref('')
const managedCameras = ref([])
const camerasLoading = ref(false)
const cameraId = ref(null)

const camVideo = ref(null)
const streamImg = ref(null)
const camCanvas = ref(null)
const livePreviewing = ref(false)
const previewOpening = ref(false)
const liveRunning = ref(false)
const liveDets = ref([])
const camFps = ref(0)
const liveLine = ref(null)
const liveSpeedLineAPts = ref([])
const liveSpeedLineBPts = ref([])
const liveSpeedLineA = ref(null)
const liveSpeedLineB = ref(null)
const liveRegionPts = ref([])
const liveRegion = ref(null)
const zoneOcc = ref({ person: 0, vehicle: 0 })
const crossing = ref({ in: 0, out: 0, person: { in: 0, out: 0 }, vehicle: { in: 0, out: 0 } })
const congestion = ref({ label: '—', level: 'smooth' })
const recentRecords = ref([])
const recordCount = ref(0)
const sessionId = ref('')
let camStream = null
let capCanvas = null
let camBusy = false
let camFirst = true
let frameCount = 0
let fpsTimer = null
let loopTimer = null
let streamReady = false
let imageReadyController = null
const previewLifecycle = createLivePreviewLifecycle({
  requestFrame: (callback) => requestAnimationFrame(callback),
  cancelFrame: (id) => cancelAnimationFrame(id),
})

const emptyCross = () => ({ in: 0, out: 0, person: { in: 0, out: 0 }, vehicle: { in: 0, out: 0 } })
const toCssColor = (raw, fallback = '#2196f3') => (raw ? String(raw) : fallback)
const withAlpha = (raw, alpha = 0.12) => {
  const s = String(raw || '').trim()
  if (!s) return `rgba(33, 150, 243, ${alpha})`
  if (s.startsWith('rgba(') || s.startsWith('rgb(')) return s
  let h = s.startsWith('#') ? s.slice(1) : s
  if (h.length === 3) h = h.split('').map((c) => c + c).join('')
  if (h.length === 8) {
    const a = parseInt(h.slice(6, 8), 16) / 255
    h = h.slice(0, 6)
    return `rgba(${parseInt(h.slice(0, 2), 16)}, ${parseInt(h.slice(2, 4), 16)}, ${parseInt(h.slice(4, 6), 16)}, ${Number.isFinite(a) ? a : alpha})`
  }
  if (h.length !== 6) return s
  return `rgba(${parseInt(h.slice(0, 2), 16)}, ${parseInt(h.slice(2, 4), 16)}, ${parseInt(h.slice(4, 6), 16)}, ${alpha})`
}
const zoneStylePayload = () => ({
  borderColor: zoneBorderColor.value,
  fillColor: zoneFillColor.value,
})

const isSpeedLine = (line) => Array.isArray(line) && line.length === 4 && line.every((v) => {
  const value = Number(v)
  return Number.isFinite(value) && value >= 0 && value <= 1
})
const isPositiveNumber = (value) => Number.isFinite(Number(value)) && Number(value) > 0
const isDoubleLineCalibrationReady = (lineA, lineB) => (
  isSpeedLine(lineA) && isSpeedLine(lineB) && isPositiveNumber(speedDistanceM.value)
)
const busy = computed(() => liveRunning.value || fileRunning.value || imageRunning.value)
const activeSpeedLineA = computed(() => (mode.value === 'file' ? fileSpeedLineA.value : liveSpeedLineA.value))
const activeSpeedLineB = computed(() => (mode.value === 'file' ? fileSpeedLineB.value : liveSpeedLineB.value))
const fileSpeedDrawPointCount = computed(() => (
  drawTool.value === 'speedA' ? fileSpeedLineAPts.value.length : drawTool.value === 'speedB' ? fileSpeedLineBPts.value.length : 0
))
const liveSpeedDrawPointCount = computed(() => (
  drawTool.value === 'speedA' ? liveSpeedLineAPts.value.length : drawTool.value === 'speedB' ? liveSpeedLineBPts.value.length : 0
))
const canDrawSpeedLines = computed(() => {
  if (fileRunning.value || imageRunning.value || liveRunning.value || speedMode.value !== 'double-line') return false
  if (mode.value === 'file') return !!(file.value && frameCanvas.value)
  return livePreviewing.value && !!camCanvas.value
})
const isSpeedCalibrationReady = (lineA, lineB) => (
  !enableSpeed.value
  || (speedMode.value === 'double-line'
    ? isDoubleLineCalibrationReady(lineA, lineB)
    : isPositiveNumber(metersPerPixel.value))
)
const fileSpeedCalibrationReady = computed(() => (
  isSpeedCalibrationReady(fileSpeedLineA.value, fileSpeedLineB.value)
))
const liveSpeedCalibrationReady = computed(() => (
  isSpeedCalibrationReady(liveSpeedLineA.value, liveSpeedLineB.value)
))
const hasResults = computed(() => {
  if (mode.value === 'image') return !!(imageResultSrc.value || imageRunning.value)
  if (mode.value === 'file') return !!(resultUrl.value || fileRunning.value)
  return !!(livePreviewing.value || liveRunning.value || recentRecords.value.length)
})
const resultBadge = computed(() => {
  if (mode.value === 'image') return imageDets.value.length || (imageRunning.value ? '…' : 0)
  if (mode.value === 'file') return fileRecords.value.length || (fileRunning.value ? '…' : 0)
  return recordCount.value || (liveRunning.value ? '…' : 0)
})
const canRunFile = computed(() => detectId.value && file.value && !fileRunning.value && fileSpeedCalibrationReady.value)
const canRunImage = computed(() => detectId.value && imageFile.value && !imageRunning.value)
const canOpenLivePreview = computed(() => {
  if (!detectId.value) return false
  if (mode.value === 'network') return !!cameraId.value
  return true
})
const canStartLive = computed(() => (
  canOpenLivePreview.value
  && livePreviewing.value
  && !liveRunning.value
  && liveSpeedCalibrationReady.value
))
const percent = computed(() => (total.value ? Math.min(100, Math.floor((processed.value / total.value) * 100)) : 0))
const congestionTagType = computed(() => {
  const lv = congestion.value.level
  if (lv === 'severe' || lv === 'busy') return 'danger'
  if (lv === 'moderate') return 'warning'
  return 'success'
})

const newSessionId = () => {
  sessionId.value = (globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`)
}

const appendCommonFields = (fd, {
  reset = false,
  line = null,
  region = null,
  speedLineA = null,
  speedLineB = null,
} = {}) => {
  fd.append('detectId', detectId.value)
  if (plateId.value) fd.append('plateId', plateId.value)
  if (detId.value && recId.value) {
    fd.append('detId', detId.value)
    fd.append('recId', recId.value)
  }
  fd.append('conf', conf.value)
  fd.append('imgsz', imgsz.value)
  fd.append('enableOcr', enableOcr.value ? '1' : '0')
  fd.append('enableSpeed', enableSpeed.value ? '1' : '0')
  fd.append('enableTrail', enableTrail.value ? '1' : '0')
  fd.append('classPreset', classPreset.value)
  // 图片模式仍可用 vehicleOnly；视频/实时以 classPreset 为准
  fd.append('vehicleOnly', (classPreset.value === 'vehicle' || vehicleOnly.value) ? '1' : '0')
  if (enableSpeed.value && mode.value !== 'image') {
    fd.append('speedMode', speedMode.value)
    fd.append('speedMaxKmh', String(speedMaxKmh.value))
    if (speedMode.value === 'double-line') {
      if (isSpeedLine(speedLineA)) fd.append('speedLineA', JSON.stringify(speedLineA))
      if (isSpeedLine(speedLineB)) fd.append('speedLineB', JSON.stringify(speedLineB))
      fd.append('speedDistanceM', String(speedDistanceM.value))
    } else if (metersPerPixel.value > 0) {
      fd.append('metersPerPixel', String(metersPerPixel.value))
    }
  }
  if (countMode.value === 'line' && line) fd.append('line', JSON.stringify(line))
  if (countMode.value === 'zone' && region) {
    fd.append('region', JSON.stringify(region))
    fd.append('zoneStyle', JSON.stringify(zoneStylePayload()))
  }
  if (sessionId.value) fd.append('sessionId', sessionId.value)
  fd.append('reset', reset ? '1' : '0')
}

const loadModels = async () => {
  const res = await modelApi.list({ pageNum: 1, pageSize: 200 })
  allModels.value = res.data.rows || []
  if (detectModels.value.length) {
    const preferred = pickRecommendedModel(detectModels.value, 'vehicle') || pickPreferred(detectModels.value, DETECT_PREF)
    const currentOk = detectId.value && detectModels.value.some((m) => m.id === detectId.value)
    if (!currentOk) detectId.value = preferred?.id || detectModels.value[0].id
  }
  if (plateModels.value.length) {
    const preferred = pickPreferred(plateModels.value, PLATE_PREF)
    const currentOk = plateId.value && plateModels.value.some((m) => m.id === plateId.value)
    if (!currentOk) plateId.value = preferred?.id || plateModels.value[0].id
  } else {
    plateId.value = null
  }
  if (detModels.value.length) {
    const preferred = pickPreferred(detModels.value, OCR_DET_PREF)
    const currentOk = detId.value && detModels.value.some((m) => m.id === detId.value)
    if (!currentOk) detId.value = preferred?.id || detModels.value[0].id
  }
  if (recModels.value.length) {
    const preferred = pickPreferred(recModels.value, OCR_REC_PREF)
    const currentOk = recId.value && recModels.value.some((m) => m.id === recId.value)
    if (!currentOk) recId.value = preferred?.id || recModels.value[0].id
  }
}

const cameraLabel = (c) => `${c.name || `摄像头#${c.id}`}${c.status === '0' ? '' : '（停用）'}`

const loadManagedCameras = async () => {
  camerasLoading.value = true
  try {
    const res = await cameraApi.list({ pageNum: 1, pageSize: 200, status: '0' })
    managedCameras.value = res.data.rows || []
  } catch (_) {
    ElMessage.error('加载网络摄像头失败')
  } finally {
    camerasLoading.value = false
  }
}

const enumCams = async ({ apply = true } = {}) => {
  try {
    const list = await navigator.mediaDevices.enumerateDevices()
    const nextDevices = list.filter((d) => d.kind === 'videoinput').map((d, i) => ({
      deviceId: d.deviceId, label: d.label, idx: i + 1,
    }))
    if (apply) devices.value = nextDevices
    return nextDevices
  } catch (_) {
    return []
  }
}

const onModeChange = async () => {
  await liveStop()
  clearFileSpeedLines()
  activeTab.value = 'config'
}

const onLiveSourceChange = async () => {
  await liveStop()
}

const onSpeedModeChange = () => {
  drawTool.value = 'count'
  if (mode.value === 'file') clearFileSpeedLines()
  else clearLiveSpeedLines()
}

const onPickImage = (uploadFile) => {
  const raw = uploadFile.raw
  if (!raw || !raw.type.startsWith('image/')) {
    ElMessage.error('请选择图片文件')
    return
  }
  imageFile.value = raw
  if (imagePreviewUrl.value) URL.revokeObjectURL(imagePreviewUrl.value)
  imagePreviewUrl.value = URL.createObjectURL(raw)
  imageResultSrc.value = ''
  imageDets.value = []
  imagePlateCount.value = 0
}

const clearImage = () => {
  imageRunning.value = false
  imageFile.value = null
  if (imagePreviewUrl.value) {
    URL.revokeObjectURL(imagePreviewUrl.value)
    imagePreviewUrl.value = ''
  }
  imageResultSrc.value = ''
  imageDets.value = []
  imagePlateCount.value = 0
}

const runImage = async () => {
  if (!canRunImage.value) return
  imageRunning.value = true
  activeTab.value = 'results'
  imageResultSrc.value = ''
  imageDets.value = []
  imagePlateCount.value = 0
  try {
    const fd = new FormData()
    fd.append('file', imageFile.value)
    appendCommonFields(fd)
    const res = await vehicleApi.detectImage(fd)
    const data = res.data || {}
    imageDets.value = data.detections || []
    imagePlateCount.value = data.plateCount ?? imageDets.value.filter((d) => d.plate).length
    imageResultSrc.value = data.imageBase64 ? `data:image/jpeg;base64,${data.imageBase64}` : ''
    if (!imageDets.value.length) ElMessage.warning('未检测到车辆')
    else ElMessage.success(`识别完成：${imageDets.value.length} 辆，号牌 ${imagePlateCount.value}`)
  } catch (e) {
    ElMessage.error(e?.response?.data?.message || e?.message || '图片识别失败')
  } finally {
    imageRunning.value = false
  }
}

const downloadImageResult = () => {
  if (!imageResultSrc.value) return
  const a = document.createElement('a')
  a.href = imageResultSrc.value
  a.download = `vehicle_plate_${Date.now()}.jpg`
  a.click()
}

const onPick = (uploadFile) => {
  const raw = uploadFile.raw
  if (!raw || !raw.type.startsWith('video/')) {
    ElMessage.error('请选择视频文件')
    return
  }
  file.value = raw
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = URL.createObjectURL(raw)
  clearFileLine()
  clearFileRegion()
  clearFileSpeedLines()
  frameBaseImage = null
  clearFileOutput()
  drawFirstFrame(raw)
}

const clearFileOutput = () => {
  if (blobUrl) { URL.revokeObjectURL(blobUrl); blobUrl = '' }
  resultUrl.value = ''
  stats.value = {}
  fileRecords.value = []
}

const drawFirstFrame = (raw) => {
  const url = URL.createObjectURL(raw)
  const v = document.createElement('video')
  v.preload = 'auto'
  v.muted = true
  v.src = url
  v.addEventListener('loadeddata', () => { v.currentTime = 0 })
  v.addEventListener('seeked', async () => {
    await nextTick()
    const cv = frameCanvas.value
    if (!cv) return
    const dispW = Math.min(640, v.videoWidth)
    const scale = dispW / v.videoWidth
    cv.width = dispW
    cv.height = Math.round(v.videoHeight * scale)
    const ctx = cv.getContext('2d')
    ctx.drawImage(v, 0, 0, cv.width, cv.height)
    frameBaseImage = ctx.getImageData(0, 0, cv.width, cv.height)
    URL.revokeObjectURL(url)
    redrawFileCanvas()
  })
}

const drawSpeedLine = (ctx, cv, line, pendingPoints, color, label) => {
  const points = isSpeedLine(line)
    ? [
      { x: Number(line[0]) * cv.width, y: Number(line[1]) * cv.height },
      { x: Number(line[2]) * cv.width, y: Number(line[3]) * cv.height },
    ]
    : pendingPoints
  if (!points.length) return
  ctx.save()
  ctx.strokeStyle = color
  ctx.fillStyle = color
  ctx.lineWidth = 3
  points.forEach((point) => {
    ctx.beginPath()
    ctx.arc(point.x, point.y, 4, 0, Math.PI * 2)
    ctx.fill()
  })
  if (points.length === 2) {
    ctx.beginPath()
    ctx.moveTo(points[0].x, points[0].y)
    ctx.lineTo(points[1].x, points[1].y)
    ctx.stroke()
    const x = (points[0].x + points[1].x) / 2
    const y = (points[0].y + points[1].y) / 2
    const text = `测速线 ${label}`
    ctx.font = 'bold 13px sans-serif'
    const width = ctx.measureText(text).width + 10
    ctx.fillStyle = 'rgba(0, 0, 0, 0.68)'
    ctx.fillRect(Math.max(0, x - width / 2), Math.max(0, y - 24), width, 18)
    ctx.fillStyle = color
    ctx.fillText(text, Math.max(5, x - width / 2 + 5), Math.max(1, y - 22))
  }
  ctx.restore()
}

const addSpeedLinePoint = (points, line, cv, x, y) => {
  if (line.value || points.value.length >= 2) {
    points.value = []
    line.value = null
  }
  points.value.push({ x, y })
  if (points.value.length === 2) {
    line.value = [
      points.value[0].x / cv.width, points.value[0].y / cv.height,
      points.value[1].x / cv.width, points.value[1].y / cv.height,
    ]
    points.value = []
    drawTool.value = 'count'
  }
}

const setDrawTool = (tool) => {
  if (!canDrawSpeedLines.value) return
  drawTool.value = tool
  if (mode.value === 'file') redrawFileCanvas()
  else redrawLiveCanvas()
}

const clearFileSpeedLines = () => {
  fileSpeedLineAPts.value = []
  fileSpeedLineBPts.value = []
  fileSpeedLineA.value = null
  fileSpeedLineB.value = null
  if (mode.value === 'file') drawTool.value = 'count'
  redrawFileCanvas()
}

const clearActiveSpeedLines = () => {
  if (mode.value === 'file') clearFileSpeedLines()
  else clearLiveSpeedLines()
}

const redrawFileCanvas = () => {
  const cv = frameCanvas.value
  if (!cv) return
  const ctx = cv.getContext('2d')
  if (frameBaseImage) ctx.putImageData(frameBaseImage, 0, 0)

  if (countMode.value === 'line' && fileLinePts.value.length) {
    ctx.fillStyle = '#ff1744'
    fileLinePts.value.forEach((p) => {
      ctx.beginPath(); ctx.arc(p.x, p.y, 4, 0, Math.PI * 2); ctx.fill()
    })
    if (fileLinePts.value.length === 2) {
      ctx.strokeStyle = '#ff1744'
      ctx.lineWidth = 2
      ctx.beginPath()
      ctx.moveTo(fileLinePts.value[0].x, fileLinePts.value[0].y)
      ctx.lineTo(fileLinePts.value[1].x, fileLinePts.value[1].y)
      ctx.stroke()
    }
  }

  const pts = fileRegion.value
    ? fileRegion.value.map((p) => ({ x: p[0] * cv.width, y: p[1] * cv.height }))
    : fileRegionPts.value
  if (countMode.value === 'zone' && pts.length) {
    const border = toCssColor(zoneBorderColor.value)
    const fill = withAlpha(zoneFillColor.value)
    ctx.fillStyle = border
    pts.forEach((p) => { ctx.beginPath(); ctx.arc(p.x, p.y, 4, 0, Math.PI * 2); ctx.fill() })
    ctx.strokeStyle = border
    ctx.lineWidth = 2
    ctx.beginPath()
    ctx.moveTo(pts[0].x, pts[0].y)
    for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i].x, pts[i].y)
    if (fileRegion.value) ctx.closePath()
    ctx.stroke()
    if (fileRegion.value) {
      ctx.fillStyle = fill
      ctx.fill()
    }
  }

  if (enableSpeed.value && speedMode.value === 'double-line') {
    drawSpeedLine(ctx, cv, fileSpeedLineA.value, fileSpeedLineAPts.value, '#00d9ff', 'A')
    drawSpeedLine(ctx, cv, fileSpeedLineB.value, fileSpeedLineBPts.value, '#ffb000', 'B')
  }
}

const onFileCanvasClick = (e) => {
  const cv = frameCanvas.value
  if (!cv) return
  const rect = cv.getBoundingClientRect()
  const x = (e.clientX - rect.left) * (cv.width / rect.width)
  const y = (e.clientY - rect.top) * (cv.height / rect.height)
  if (enableSpeed.value && speedMode.value === 'double-line' && drawTool.value !== 'count') {
    if (drawTool.value === 'speedA') addSpeedLinePoint(fileSpeedLineAPts, fileSpeedLineA, cv, x, y)
    else addSpeedLinePoint(fileSpeedLineBPts, fileSpeedLineB, cv, x, y)
    redrawFileCanvas()
    return
  }
  if (countMode.value === 'none') return
  if (countMode.value === 'line') {
    if (fileLinePts.value.length >= 2) return
    fileLinePts.value.push({ x, y })
    redrawFileCanvas()
    if (fileLinePts.value.length === 2) {
      fileLine.value = [
        fileLinePts.value[0].x / cv.width, fileLinePts.value[0].y / cv.height,
        fileLinePts.value[1].x / cv.width, fileLinePts.value[1].y / cv.height,
      ]
    }
    return
  }
  if (countMode.value === 'zone') {
    if (fileRegion.value) return
    fileRegionPts.value.push({ x, y })
    redrawFileCanvas()
  }
}

const clearFileLine = () => {
  fileLinePts.value = []
  fileLine.value = null
  redrawFileCanvas()
  if (!frameBaseImage && file.value) drawFirstFrame(file.value)
}

const clearFileRegion = () => {
  fileRegionPts.value = []
  fileRegion.value = null
  redrawFileCanvas()
  if (!frameBaseImage && file.value) drawFirstFrame(file.value)
}

const finishFileRegion = () => {
  const cv = frameCanvas.value
  if (!cv || fileRegionPts.value.length < 3) {
    ElMessage.warning('请至少点击 3 个点')
    return
  }
  fileRegion.value = fileRegionPts.value.map((p) => [p.x / cv.width, p.y / cv.height])
  fileRegionPts.value = []
  redrawFileCanvas()
  ElMessage.success('监控区域已设置')
}

const onCountModeChange = () => {
  clearFileLine()
  clearFileRegion()
  clearLiveLine()
  clearLiveRegion()
  if (file.value && countMode.value !== 'none') drawFirstFrame(file.value)
}

const clearFile = () => {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
  clearFileOutput()
  if (previewUrl.value) { URL.revokeObjectURL(previewUrl.value); previewUrl.value = '' }
  file.value = null
  clearFileLine()
  clearFileRegion()
  clearFileSpeedLines()
  frameBaseImage = null
  processed.value = 0
  total.value = 0
  fileRunning.value = false
}

const runVideo = async () => {
  if (!fileSpeedCalibrationReady.value) {
    ElMessage.warning(speedMode.value === 'double-line'
      ? '双线测速需绘制测速线 A、B 并填写大于 0 的实际距离'
      : '比例测速需先填写显式大于 0 的米/像素标定值')
    return
  }
  if (countMode.value === 'zone' && !fileRegion.value) {
    ElMessage.warning('请先绘制并闭合多边形监控区域')
    return
  }
  fileRunning.value = true
  activeTab.value = 'results'
  processed.value = 0
  total.value = 0
  clearFileOutput()
  try {
    const fd = new FormData()
    fd.append('file', file.value)
    appendCommonFields(fd, {
      line: fileLine.value,
      region: fileRegion.value,
      speedLineA: fileSpeedLineA.value,
      speedLineB: fileSpeedLineB.value,
    })
    fd.append('alertEnabled', alertEnabled.value ? '1' : '0')
    const res = await vehicleApi.trackVideo(fd)
    await pollVideo(res.data.jobId)
  } catch (_) {
    ElMessage.error('车辆追踪启动失败')
    fileRunning.value = false
  }
}

const pollVideo = (jobId) => new Promise((resolve) => {
  pollTimer = setInterval(async () => {
    try {
      const res = await vehicleApi.videoProgress(jobId)
      const d = res.data
      processed.value = d.processed
      total.value = d.total
      if (d.status === 'done') {
        clearInterval(pollTimer)
        pollTimer = null
        stats.value = d.stats || {}
        fileRecords.value = d.stats?.records || []
        const outName = d.stats?.output
        if (!outName) {
          ElMessage.warning('追踪完成，但未返回输出视频名')
          fileRunning.value = false
          resolve()
          return
        }
        const raw = await vehicleApi.outputVideo(outName)
        const blob = raw instanceof Blob ? raw : raw?.data
        if (!(blob instanceof Blob) || blob.size < 64) {
          throw new Error('输出视频为空或无效')
        }
        // 后端错误可能以 JSON blob 返回
        if ((blob.type || '').includes('json')) {
          const errText = await blob.text()
          let msg = '拉取输出视频失败'
          try { msg = JSON.parse(errText).message || msg } catch (_) { /* ignore */ }
          throw new Error(msg)
        }
        const playable = (blob.type || '').startsWith('video/')
          ? blob
          : new Blob([blob], { type: 'video/mp4' })
        if (blobUrl) URL.revokeObjectURL(blobUrl)
        blobUrl = URL.createObjectURL(playable)
        resultUrl.value = blobUrl
        fileRunning.value = false
        ElMessage.success(`追踪完成，过车记录 ${fileRecords.value.length} 条`)
        resolve()
      } else if (d.status === 'error') {
        clearInterval(pollTimer)
        pollTimer = null
        ElMessage.error(d.error || '追踪失败')
        fileRunning.value = false
        resolve()
      }
    } catch (_) {
      clearInterval(pollTimer)
      pollTimer = null
      ElMessage.error('查询进度失败')
      fileRunning.value = false
      resolve()
    }
  }, 1000)
})

const downloadVideo = () => {
  const a = document.createElement('a')
  a.href = resultUrl.value
  a.download = stats.value.output || 'vehicle.mp4'
  a.click()
}

const downloadBlob = (text, filename) => {
  const blob = new Blob([text], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

const recordsToCsv = (rows) => {
  const header = [
    'time', 'trackId', 'className', 'plate', 'plateScore',
    'speedKmh', 'speedSource', 'speedQuality', 'confidence',
  ]
  const lines = [header.join(',')]
  for (const r of rows) {
    lines.push(header.map((k) => JSON.stringify(r[k] ?? '')).join(','))
  }
  return lines.join('\n')
}

const downloadFileCsv = () => {
  if (!fileRecords.value.length) return
  downloadBlob(recordsToCsv(fileRecords.value), `vehicle_records_${Date.now()}.csv`)
}

const exportCsv = async () => {
  if (!sessionId.value) return
  try {
    const res = await vehicleApi.exportRecords(sessionId.value)
    downloadBlob(res.data.csv, `vehicle_live_${Date.now()}.csv`)
    ElMessage.success(`已导出 ${res.data.count || 0} 条记录`)
  } catch (_) {
    ElMessage.error('导出失败')
  }
}

const getFrameSource = () => {
  if (mode.value === 'network') {
    const img = streamImg.value
    return { el: img, w: img?.naturalWidth || 0, h: img?.naturalHeight || 0 }
  }
  const video = camVideo.value
  return { el: video, w: video?.videoWidth || 0, h: video?.videoHeight || 0 }
}

const openLivePreview = async () => {
  if (!canOpenLivePreview.value || livePreviewing.value || previewOpening.value) return
  const openToken = previewLifecycle.beginOpen()
  previewOpening.value = true
  activeTab.value = 'results'
  streamReady = false
  await nextTick()
  if (!previewLifecycle.isCurrent(openToken)) return

  if (mode.value === 'network') {
    const img = streamImg.value
    if (!img) {
      if (previewLifecycle.isCurrent(openToken)) previewOpening.value = false
      return
    }
    img.removeAttribute('crossorigin')
    img.src = cameraApi.streamUrl(cameraId.value, String(Date.now()), false, true)
    imageReadyController?.abort()
    const readyController = new AbortController()
    imageReadyController = readyController
    try {
      await waitForImageReady(img, { signal: readyController.signal })
      if (!previewLifecycle.isCurrent(openToken)) return
      streamReady = true
    } catch (_) {
      if (!previewLifecycle.isCurrent(openToken)) return
      ElMessage.error('无法连接网络摄像头')
      img.removeAttribute('src')
      return
    } finally {
      if (imageReadyController === readyController) imageReadyController = null
      if (previewLifecycle.isCurrent(openToken)) previewOpening.value = false
    }
    setupCapCanvas(img.naturalWidth, img.naturalHeight)
    livePreviewing.value = true
    previewLifecycle.startLoop(openToken, redrawLiveCanvas)
    return
  }

  let openedStream = null
  try {
    const constraints = {
      video: deviceId.value ? { deviceId: { exact: deviceId.value } } : true,
      audio: false,
    }
    openedStream = await navigator.mediaDevices.getUserMedia(constraints)
  } catch (_) {
    if (!previewLifecycle.isCurrent(openToken)) return
    ElMessage.error('无法访问摄像头')
    previewOpening.value = false
    return
  }
  if (!previewLifecycle.isCurrent(openToken)) {
    releaseOpenedStream(openedStream, camStream, camVideo.value)
    return
  }
  await nextTick()
  if (!previewLifecycle.isCurrent(openToken)) {
    releaseOpenedStream(openedStream, camStream, camVideo.value)
    return
  }
  if (!camVideo.value) {
    releaseOpenedStream(openedStream, camStream, null)
    ElMessage.error('实时画面未就绪，请重试')
    previewOpening.value = false
    return
  }
  camStream = openedStream
  camVideo.value.srcObject = camStream
  try {
    await camVideo.value.play()
  } catch (_) {
    if (previewLifecycle.isCurrent(openToken)) ElMessage.error('摄像头画面播放失败')
    camStream = releaseOpenedStream(openedStream, camStream, camVideo.value)
    if (previewLifecycle.isCurrent(openToken)) previewOpening.value = false
    return
  }
  if (!previewLifecycle.isCurrent(openToken)) {
    camStream = releaseOpenedStream(openedStream, camStream, camVideo.value)
    return
  }
  const nextDevices = await enumCams({ apply: false })
  if (!previewLifecycle.isCurrent(openToken)) {
    camStream = releaseOpenedStream(openedStream, camStream, camVideo.value)
    return
  }
  devices.value = nextDevices
  setupCapCanvas(camVideo.value.videoWidth, camVideo.value.videoHeight)
  livePreviewing.value = true
  previewOpening.value = false
  previewLifecycle.startLoop(openToken, redrawLiveCanvas)
}

const liveStart = () => {
  if (!livePreviewing.value) {
    ElMessage.warning('请先打开摄像头预览并完成标定')
    return
  }
  if (!liveSpeedCalibrationReady.value) {
    ElMessage.warning(speedMode.value === 'double-line'
      ? '双线测速需绘制测速线 A、B 并填写大于 0 的实际距离'
      : '比例测速需先填写显式大于 0 的米/像素标定值')
    return
  }

  newSessionId()
  crossing.value = emptyCross()
  zoneOcc.value = { person: 0, vehicle: 0 }
  recentRecords.value = []
  recordCount.value = 0
  congestion.value = { label: '—', level: 'smooth' }
  camFirst = true
  camBusy = false
  frameCount = 0
  previewLifecycle.stopLoop()
  liveRunning.value = true
  fpsTimer = setInterval(() => { camFps.value = frameCount; frameCount = 0 }, 1000)
  scheduleLoop(mode.value === 'network' ? 80 : 0)
}

const setupCapCanvas = (vw, vh) => {
  const capW = Math.min(vw || 640, 640)
  const capH = Math.round(((vh || 480) * capW) / (vw || 640))
  capCanvas = document.createElement('canvas')
  capCanvas.width = capW
  capCanvas.height = capH
  camCanvas.value.width = capW
  camCanvas.value.height = capH
}

const scheduleLoop = (delayMs = 0) => {
  if (!liveRunning.value) return
  if (loopTimer) clearTimeout(loopTimer)
  loopTimer = setTimeout(() => {
    loopTimer = null
    liveLoop()
  }, delayMs)
}

const getContainedContentBox = (boxWidth, boxHeight, contentWidth, contentHeight) => {
  if (![boxWidth, boxHeight, contentWidth, contentHeight].every((value) => Number.isFinite(value) && value > 0)) return null
  const scale = Math.min(boxWidth / contentWidth, boxHeight / contentHeight)
  const width = contentWidth * scale
  const height = contentHeight * scale
  return {
    left: (boxWidth - width) / 2,
    top: (boxHeight - height) / 2,
    width,
    height,
  }
}

const mapContainedCanvasPoint = (clientX, clientY, rect, canvasWidth, canvasHeight) => {
  const content = getContainedContentBox(rect.width, rect.height, canvasWidth, canvasHeight)
  if (!content) return null
  const x = clientX - rect.left
  const y = clientY - rect.top
  if (x < content.left || x > content.left + content.width || y < content.top || y > content.top + content.height) return null
  return {
    x: (x - content.left) * (canvasWidth / content.width),
    y: (y - content.top) * (canvasHeight / content.height),
  }
}

const onLiveClick = (e) => {
  if (!livePreviewing.value || liveRunning.value) return
  const cv = camCanvas.value
  if (!cv) return
  const rect = cv.getBoundingClientRect()
  const point = mapContainedCanvasPoint(e.clientX, e.clientY, rect, cv.width, cv.height)
  if (!point) return
  const { x, y } = point
  if (enableSpeed.value && speedMode.value === 'double-line' && drawTool.value !== 'count') {
    if (drawTool.value === 'speedA') addSpeedLinePoint(liveSpeedLineAPts, liveSpeedLineA, cv, x, y)
    else addSpeedLinePoint(liveSpeedLineBPts, liveSpeedLineB, cv, x, y)
    redrawLiveCanvas()
    return
  }
  if (countMode.value === 'none') return
  if (countMode.value === 'line') {
    if (!cv._p0) {
      cv._p0 = [x, y]
      liveLine.value = null
    } else {
      liveLine.value = [cv._p0[0] / cv.width, cv._p0[1] / cv.height, x / cv.width, y / cv.height]
      cv._p0 = null
      crossing.value = emptyCross()
    }
    return
  }
  if (countMode.value === 'zone') {
    if (liveRegion.value) return
    liveRegionPts.value.push({ x, y })
  }
}

const clearLiveLine = () => {
  liveLine.value = null
  if (camCanvas.value) camCanvas.value._p0 = null
}

const clearLiveSpeedLines = () => {
  liveSpeedLineAPts.value = []
  liveSpeedLineBPts.value = []
  liveSpeedLineA.value = null
  liveSpeedLineB.value = null
  if (mode.value !== 'file') drawTool.value = 'count'
  redrawLiveCanvas()
}

const clearLiveRegion = () => {
  liveRegion.value = null
  liveRegionPts.value = []
  zoneOcc.value = { person: 0, vehicle: 0 }
  crossing.value = emptyCross()
}

const finishLiveRegion = () => {
  const cv = camCanvas.value
  if (!cv || liveRegionPts.value.length < 3) {
    ElMessage.warning('请至少点击 3 个点')
    return
  }
  liveRegion.value = liveRegionPts.value.map((p) => [p.x / cv.width, p.y / cv.height])
  liveRegionPts.value = []
  crossing.value = emptyCross()
  ElMessage.success('监控区域已设置')
}

const notifyAlert = (item) => {
  ElNotification({
    title: item.title || item.ruleName || '检测告警',
    message: item.message || '请现场核实',
    type: item.severity === 'high' ? 'error' : item.severity === 'medium' ? 'warning' : 'info',
    duration: item.severity === 'high' ? 0 : 8000,
    position: 'top-right',
  })
}

const evaluateAlerts = async (detections, frameW, frameH) => {
  if (!alertEnabled.value || !detections?.length) return null
  try {
    const payload = {
      detections,
      sourceKey: ALERT_SOURCE_KEY,
      sourceType: 'camera',
      modelId: detectId.value,
      persist: true,
      frameWidth: frameW,
      frameHeight: frameH,
    }
    if (liveLine.value) payload.line = liveLine.value
    if (liveRegion.value) payload.region = liveRegion.value
    const res = await alertApi.evaluate(payload)
    const list = res.data?.triggered || []
    list.filter((t) => t.notify).forEach(notifyAlert)
    return res.data?.overlay || null
  } catch (_) {
    return null
  }
}

const COLORS = ['#67c23a', '#409eff', '#e6a23c', '#f56c6c', '#9254de', '#13c2c2']

const speedSourceLabel = (item) => {
  if (item?.speedSource === 'double-line') return '区间实测'
  if (item?.speedSource === 'scale') return '比例估算'
  return ''
}

const speedDisplay = (item) => {
  if (item?.speedQuality === 'warming-up') return '测速准备中'
  if (item?.speedQuality === 'invalid') return '测速无效'
  const speed = Number(item?.speedKmh)
  if (!item?.speedSource || item?.speedKmh == null || !Number.isFinite(speed)) return '—'
  return `${Math.round(speed * 10) / 10} km/h`
}

const redrawLiveCanvas = () => {
  if (!livePreviewing.value || !camCanvas.value) return
  camDraw({ detections: liveDets.value, congestion: congestion.value })
}

const camDraw = (data, overlayStyle = null) => {
  const cv = camCanvas.value
  const ctx = cv.getContext('2d')
  const src = getFrameSource().el
  ctx.clearRect(0, 0, cv.width, cv.height)
  if (src) ctx.drawImage(src, 0, 0, cv.width, cv.height)

  const list = data.detections || []
  // 先画轨迹（按 Track ID），再画检测框
  if (enableTrail.value) {
    list.forEach((d, i) => {
      const trail = d.trail || []
      if (trail.length < 2) return
      const color = COLORS[(d.trackId ?? i) % COLORS.length]
      ctx.strokeStyle = color
      ctx.lineWidth = 2
      ctx.lineJoin = 'round'
      ctx.lineCap = 'round'
      ctx.beginPath()
      ctx.moveTo(trail[0][0], trail[0][1])
      for (let k = 1; k < trail.length; k++) ctx.lineTo(trail[k][0], trail[k][1])
      ctx.stroke()
      const head = trail[trail.length - 1]
      ctx.fillStyle = color
      ctx.beginPath()
      ctx.arc(head[0], head[1], 3.5, 0, Math.PI * 2)
      ctx.fill()
    })
  }
  ctx.lineWidth = 2
  ctx.font = '13px sans-serif'
  ctx.textBaseline = 'top'
  list.forEach((d, i) => {
    const [x1, y1, x2, y2] = d.bbox
    const color = COLORS[(d.trackId ?? i) % COLORS.length]
    ctx.strokeStyle = color
    ctx.strokeRect(x1, y1, x2 - x1, y2 - y1)
    const parts = []
    if (d.trackId != null) parts.push(`ID${d.trackId}`)
    parts.push(d.className || 'vehicle')
    if (d.plate) parts.push(d.plate)
    const speed = speedDisplay(d)
    if (speed !== '—') parts.push(speed)
    const source = speedSourceLabel(d)
    if (source) parts.push(source)
    const label = parts.join(' ')
    const tw = ctx.measureText(label).width + 8
    ctx.fillStyle = color
    ctx.fillRect(x1, Math.max(0, y1 - 18), tw, 18)
    ctx.fillStyle = '#fff'
    ctx.fillText(label, x1 + 4, Math.max(0, y1 - 17))
    if (d.plateBbox?.length >= 4) {
      const [px1, py1, px2, py2] = d.plateBbox
      ctx.strokeStyle = '#ffd700'
      ctx.strokeRect(px1, py1, px2 - px1, py2 - py1)
    }
  })

  if (liveLine.value) {
    const ln = [
      liveLine.value[0] * cv.width, liveLine.value[1] * cv.height,
      liveLine.value[2] * cv.width, liveLine.value[3] * cv.height,
    ]
    ctx.strokeStyle = '#ff1744'
    ctx.lineWidth = 3
    ctx.beginPath()
    ctx.moveTo(ln[0], ln[1])
    ctx.lineTo(ln[2], ln[3])
    ctx.stroke()
  }

  if (enableSpeed.value && speedMode.value === 'double-line') {
    drawSpeedLine(ctx, cv, liveSpeedLineA.value, liveSpeedLineAPts.value, '#00d9ff', 'A')
    drawSpeedLine(ctx, cv, liveSpeedLineB.value, liveSpeedLineBPts.value, '#ffb000', 'B')
  }

  const zonePts = liveRegion.value
    ? liveRegion.value.map((p) => ({ x: p[0] * cv.width, y: p[1] * cv.height }))
    : liveRegionPts.value
  if (zonePts.length) {
    const border = toCssColor(zoneBorderColor.value)
    const fill = withAlpha(zoneFillColor.value)
    ctx.strokeStyle = border
    ctx.lineWidth = 2
    ctx.beginPath()
    ctx.moveTo(zonePts[0].x, zonePts[0].y)
    for (let i = 1; i < zonePts.length; i++) ctx.lineTo(zonePts[i].x, zonePts[i].y)
    if (liveRegion.value) ctx.closePath()
    ctx.stroke()
    zonePts.forEach((p) => {
      ctx.fillStyle = border
      ctx.beginPath(); ctx.arc(p.x, p.y, 4, 0, Math.PI * 2); ctx.fill()
    })
    if (liveRegion.value) {
      ctx.fillStyle = fill
      ctx.fill()
      const labels = []
      if (zoneOcc.value.vehicle > 0) labels.push(`车：${zoneOcc.value.vehicle}`)
      if (zoneOcc.value.person > 0) labels.push(`人：${zoneOcc.value.person}`)
      if (labels.length) {
        const cx = zonePts.reduce((s, p) => s + p.x, 0) / zonePts.length
        const cy = zonePts.reduce((s, p) => s + p.y, 0) / zonePts.length
        let polyArea = 0
        for (let i = 0; i < zonePts.length; i++) {
          const a = zonePts[i], b = zonePts[(i + 1) % zonePts.length]
          polyArea += a.x * b.y - b.x * a.y
        }
        polyArea = Math.abs(polyArea) / 2
        const targetArea = Math.max(polyArea * 0.06, 1)
        const xs = zonePts.map((p) => p.x), ys = zonePts.map((p) => p.y)
        const bw = Math.max(...xs) - Math.min(...xs)
        const bh = Math.max(...ys) - Math.min(...ys)
        const fontFamily = '"Microsoft YaHei", "PingFang SC", sans-serif'
        const measure = (size) => {
          ctx.font = `bold ${size}px ${fontFamily}`
          const widths = labels.map((t) => ctx.measureText(t).width)
          const lineH = size * 1.15
          const gap = Math.max(4, size / 8)
          const tw = Math.max(...widths)
          const th = labels.length * lineH + gap * Math.max(0, labels.length - 1)
          return { tw, th, lineH, gap }
        }
        let lo = 14, hi = Math.max(18, Math.floor(Math.min(bw, bh) * 0.22)), best = 14
        while (lo <= hi) {
          const mid = (lo + hi) >> 1
          const { tw, th } = measure(mid)
          if (tw * th <= targetArea) { best = mid; lo = mid + 1 }
          else hi = mid - 1
        }
        best = Math.min(Math.round(best * 2.5), Math.max(18, Math.floor(Math.min(bw, bh) * 0.95)))
        const { lineH, gap } = measure(best)
        const totalH = labels.length * lineH + gap * Math.max(0, labels.length - 1)
        ctx.textAlign = 'center'
        ctx.textBaseline = 'middle'
        const outline = Math.max(2, Math.floor(best / 18))
        labels.forEach((t, i) => {
          const ty = cy - totalH / 2 + i * (lineH + gap) + lineH / 2
          ctx.lineWidth = outline * 2
          ctx.strokeStyle = 'rgba(0,0,0,0.85)'
          ctx.strokeText(t, cx, ty)
          ctx.fillStyle = '#fff'
          ctx.fillText(t, cx, ty)
        })
        ctx.textAlign = 'left'
        ctx.textBaseline = 'top'
        ctx.font = '13px sans-serif'
      }
    }
  }

  const cong = data.congestion || {}
  ctx.fillStyle = 'rgba(0,0,0,0.55)'
  ctx.fillRect(8, cv.height - 36, 180, 28)
  ctx.fillStyle = '#fff'
  ctx.font = 'bold 14px sans-serif'
  ctx.fillText(`拥堵: ${cong.label || '—'} (${cong.vehicleCount ?? 0}辆)`, 14, cv.height - 30)

  if (alertEnabled.value && overlayStyle) {
    drawAlertOverlay(ctx, cv, overlayStyle)
  }
}

const drawAlertOverlay = (ctx, cv, style) => {
  if (!style || style.enabled === false) return
  const w = cv.width
  const h = cv.height
  const wr = Math.min(0.95, Math.max(0.3, Number(style.panelWidthRatio) || 0.72))
  const hr = Math.min(0.8, Math.max(0.18, Number(style.panelHeightRatio) || 0.36))
  const opacity = Math.min(0.85, Math.max(0.15, Number(style.opacity) || 0.45))
  const pw = Math.round(w * wr)
  const ph = Math.round(h * hr)
  const x = Math.round((w - pw) / 2)
  const y = Math.round((h - ph) / 2)
  const cx = Math.round(w / 2)
  ctx.save()
  ctx.globalAlpha = opacity
  ctx.fillStyle = style.fillColor || '#9254DE'
  ctx.fillRect(x, y, pw, ph)
  ctx.globalAlpha = 1
  ctx.strokeStyle = style.borderColor || style.fillColor || '#722ED1'
  ctx.lineWidth = 3
  ctx.strokeRect(x, y, pw, ph)
  const titles = style.titleLines || []
  const subs = style.subtitleLines || []
  const lines = [...titles, ...subs]
  ctx.fillStyle = style.textColor || '#FFFFFF'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  const startY = y + Math.round(ph * 0.58)
  const step = Math.max(18, Math.round(ph * 0.14))
  lines.forEach((ln, i) => {
    ctx.font = `${i < titles.length ? 'bold ' : ''}${Math.max(14, Math.round(ph * 0.11))}px sans-serif`
    ctx.fillText(String(ln), cx, startY + i * step)
  })
  ctx.restore()
}

const liveLoop = () => {
  if (!liveRunning.value) return
  if (camBusy) { scheduleLoop(mode.value === 'network' ? 80 : 0); return }
  const src = getFrameSource()
  if (!src.el || !src.w || !src.h) { scheduleLoop(200); return }

  camBusy = true
  const ctx = capCanvas.getContext('2d')
  ctx.drawImage(src.el, 0, 0, capCanvas.width, capCanvas.height)
  capCanvas.toBlob(async (blob) => {
    if (!liveRunning.value || !blob) { camBusy = false; return }
    try {
      const fd = new FormData()
      fd.append('file', blob, 'frame.jpg')
      appendCommonFields(fd, {
        reset: camFirst,
        line: liveLine.value,
        region: liveRegion.value,
        speedLineA: liveSpeedLineA.value,
        speedLineB: liveSpeedLineB.value,
      })
      camFirst = false
      const res = await vehicleApi.trackFrame(fd)
      const data = res.data || {}
      if (data.sessionId) sessionId.value = data.sessionId
      liveDets.value = data.detections || []
      if (data.crossing) {
        crossing.value = {
          in: data.crossing.in || 0,
          out: data.crossing.out || 0,
          person: data.crossing.person || { in: 0, out: 0 },
          vehicle: data.crossing.vehicle || { in: 0, out: 0 },
        }
      }
      if (data.zoneOccupancy) {
        zoneOcc.value = {
          person: data.zoneOccupancy.person || 0,
          vehicle: data.zoneOccupancy.vehicle || 0,
        }
      } else if (data.crossing?.person || data.crossing?.vehicle) {
        zoneOcc.value = {
          person: data.crossing?.person?.in || 0,
          vehicle: data.crossing?.vehicle?.in || 0,
        }
      }
      congestion.value = data.congestion || congestion.value
      recentRecords.value = data.recentRecords || []
      recordCount.value = data.recordCount || 0
      const overlay = await evaluateAlerts(data.detections, data.width || capCanvas.width, data.height || capCanvas.height)
      camDraw(data, overlay)
      frameCount++
    } catch (_) { /* 单帧失败忽略 */ } finally {
      camBusy = false
      if (liveRunning.value) scheduleLoop(mode.value === 'network' ? 80 : 0)
    }
  }, 'image/jpeg', 0.6)
}

const liveStop = async () => {
  previewLifecycle.invalidate()
  imageReadyController?.abort()
  imageReadyController = null
  previewOpening.value = false
  liveRunning.value = false
  livePreviewing.value = false
  if (loopTimer) { clearTimeout(loopTimer); loopTimer = null }
  if (fpsTimer) { clearInterval(fpsTimer); fpsTimer = null }
  if (camStream) {
    camStream.getTracks().forEach((t) => t.stop())
    camStream = null
  }
  if (camVideo.value) camVideo.value.srcObject = null
  if (streamImg.value) streamImg.value.removeAttribute('src')
  streamReady = false
  camBusy = false
  camFirst = true
  frameCount = 0
  capCanvas = null
  clearLiveSpeedLines()
  if (camCanvas.value) {
    camCanvas.value._p0 = null
    const ctx = camCanvas.value.getContext('2d')
    ctx.clearRect(0, 0, camCanvas.value.width, camCanvas.value.height)
  }
  liveDets.value = []
  camFps.value = 0
  try {
    await alertApi.resetRuntime({ sourceKey: ALERT_SOURCE_KEY })
  } catch (_) { /* ignore */ }
}

onMounted(async () => {
  await loadModels()
  await enumCams()
  await loadManagedCameras()
})
onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer)
  if (blobUrl) URL.revokeObjectURL(blobUrl)
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  if (imagePreviewUrl.value) URL.revokeObjectURL(imagePreviewUrl.value)
  liveStop()
})
</script>

<style scoped>
.vehicle-root { min-height: 360px; }
.vehicle-tabs :deep(.el-tabs__content) { padding: 16px; }
.tab-label { display: inline-flex; align-items: center; gap: 6px; }
.tab-badge { margin-left: 2px; }
.tab-badge :deep(.el-badge__content) { transform: translateY(-2px); }
.cfg-card { margin-bottom: 12px; }
.cfg-form { row-gap: 4px; }
.speed-setting-item :deep(.el-form-item__content) { min-width: 0; }
.speed-settings { display: grid; gap: 8px; min-width: 0; }
.speed-field-row { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; color: #52647c; font-size: 13px; }
.speed-draw-controls { gap: 8px; }
.speed-help { color: #7a889e; font-size: 12px; }
.speed-scale-warning { max-width: 540px; }
.speed-source-tag { margin-left: 6px; vertical-align: middle; }
.flow-tip { margin-top: 8px; }
.alert-action-row { display: flex; align-items: center; flex-wrap: wrap; gap: 4px; }
.section-title { font-weight: 600; color: #3a4a63; margin-bottom: 10px; display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.line-tip { font-size: 13px; color: #5a6b87; margin-bottom: 8px; }
.meta { margin-left: 10px; color: #67c23a; }
.frame-canvas { max-width: 100%; border: 1px solid #e4e7ed; border-radius: 6px; cursor: crosshair; }
.progress-box { padding: 22px 4px; }
.progress-title { font-weight: 600; margin-bottom: 12px; color: #3a4a63; }
.player { width: 100%; max-height: 480px; background: #000; border-radius: 6px; }
.preview-img { max-width: 100%; max-height: 480px; border-radius: 6px; display: block; background: #0c1733; }
.result-img { margin-top: 4px; }
.image-compare { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; align-items: start; }
.image-compare figure { min-width: 0; margin: 0; padding: 12px; border: 1px solid #e3eaf2; border-radius: 10px; background: #f8fafc; }
.image-compare figcaption { margin-bottom: 9px; color: #52647c; font-size: 13px; font-weight: 650; }
@media (max-width: 900px) { .image-compare { grid-template-columns: 1fr; } }
.stats { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0; }
.rec-table { margin-top: 12px; }
.cam-wrap { margin-top: 4px; }
.cam-stage { position: relative; background: #0c1733; border-radius: 8px; aspect-ratio: 16/9; overflow: hidden; }
.cam-video { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; }
.cam-canvas { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; cursor: crosshair; }
.cam-hint { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; color: #8aa0c8; text-align: center; padding: 16px; }
.cam-draw-tip { position: absolute; right: 10px; bottom: 10px; max-width: calc(100% - 20px); padding: 7px 10px; border-radius: 4px; background: rgba(0, 0, 0, 0.68); color: #fff; font-size: 13px; }
.cam-hud { position: absolute; top: 10px; left: 10px; display: flex; flex-wrap: wrap; gap: 8px; max-width: calc(100% - 20px); }
</style>
