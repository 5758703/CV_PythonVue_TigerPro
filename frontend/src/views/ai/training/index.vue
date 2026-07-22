<template>
  <div class="training-root">
    <el-tabs v-model="activeTab" type="border-card">
      <!-- ── 数据集管理 ── -->
      <el-tab-pane label="数据集管理" name="dataset">
        <el-alert class="workflow-alert" type="success" :closable="false"
          title="平台闭环：Roboflow YOLO zip / 自有抽帧标注 → 构建 → YOLO11n/s 训练 → 部署到模型管理 → 羽毛球分析选用" />
        <div class="toolbar">
          <el-input v-model="dsQuery.name" placeholder="数据集名称" clearable style="width:200px" @keyup.enter="loadDatasets" />
          <el-button type="primary" :icon="Plus" @click="openDsDialog()">新建数据集</el-button>
          <el-button type="warning" plain @click="applyBadmintonPreset">羽毛球自训预设</el-button>
          <el-button :icon="Refresh" @click="loadDatasets">刷新</el-button>
        </div>
        <el-table :data="datasets" v-loading="dsLoading" border stripe>
          <el-table-column prop="name" label="名称" min-width="140" />
          <el-table-column label="格式" width="110">
            <template #default="{ row }">
              <el-tag size="small" type="info">{{ formatLabel(row.format) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="类别" min-width="160">
            <template #default="{ row }">
              <el-tag v-for="c in row.classNames" :key="c" size="small" style="margin:2px">{{ c }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="样本" width="120">
            <template #default="{ row }">{{ row.trainCount }} / {{ row.valCount }}</template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="dsStatusType(row.status)" size="small">{{ dsStatusText(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="createTime" label="创建时间" width="170" />
          <el-table-column label="操作" width="460" fixed="right" class-name="col-actions">
            <template #default="{ row }">
              <div class="row-actions">
                <el-upload v-if="row.format !== 'import'" :show-file-list="false" :auto-upload="false" multiple
                  :accept="uploadAccept(row.format)"
                  :on-change="(f) => onDsUpload(row, f)">
                  <el-button size="small" :icon="Upload">上传</el-button>
                </el-upload>
                <el-button v-if="row.format !== 'import'" size="small" :icon="VideoCamera" @click="openExtractDialog(row)">抽帧</el-button>
                <el-button v-if="row.format !== 'import'" size="small" type="warning" @click="openAnnotate(row)">标注</el-button>
                <el-button size="small" @click="previewDs(row)">预览</el-button>
                <el-button size="small" type="success" :loading="row._building" @click="buildDs(row)">构建</el-button>
                <el-button size="small" :icon="Edit" @click="openDsDialog(row)">编辑</el-button>
                <el-button size="small" type="danger" :icon="Delete" @click="removeDs(row)">删除</el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>
        <el-pagination class="pager" v-model:current-page="dsPage" v-model:page-size="dsSize"
          :total="dsTotal" layout="total, prev, pager, next" @current-change="loadDatasets" />
      </el-tab-pane>

      <!-- ── 数据标注 ── -->
      <el-tab-pane label="数据标注" name="annotate">
        <el-tabs v-model="annotateSubTab" type="card" class="annotate-sub-tabs">
          <el-tab-pane label="标注工具" name="canvas">
            <AnnotateToolsPanel ref="annotateRef" :initial-dataset-id="annotateDatasetId" />
          </el-tab-pane>
          <el-tab-pane label="质量检测" name="quality">
            <QualityPanel ref="qualityRef" :initial-dataset-id="annotateDatasetId" />
          </el-tab-pane>
          <el-tab-pane label="格式转换" name="convert">
            <ConvertPanel ref="convertRef" :initial-dataset-id="annotateDatasetId" />
          </el-tab-pane>
        </el-tabs>
      </el-tab-pane>

      <!-- ── 训练任务 ── -->
      <el-tab-pane label="训练任务" name="job">
        <div class="toolbar">
          <el-select v-model="jobQuery.status" placeholder="状态" clearable style="width:130px" @change="loadJobs">
            <el-option label="待训练" value="pending" />
            <el-option label="训练中" value="running" />
            <el-option label="取消中" value="cancelling" />
            <el-option label="已完成" value="done" />
            <el-option label="失败" value="failed" />
            <el-option label="已取消" value="cancelled" />
          </el-select>
          <el-button type="primary" :icon="Plus" @click="openJobDialog()">新建任务</el-button>
          <el-button :icon="Refresh" @click="loadJobs">刷新</el-button>
        </div>
        <el-table :data="jobs" v-loading="jobLoading" border stripe>
          <el-table-column prop="jobName" label="任务名称" min-width="140" />
          <el-table-column prop="datasetName" label="数据集" min-width="120" />
          <el-table-column prop="baseModel" label="基座模型" width="120" />
          <el-table-column label="进度" min-width="180">
            <template #default="{ row }">
              <el-progress :percentage="row.progress || 0" :status="jobProgressStatus(row)" />
              <span class="epoch-hint" v-if="row.status === 'running'">
                {{ row.currentEpoch }} / {{ row.totalEpochs }} epoch
              </span>
            </template>
          </el-table-column>
          <el-table-column label="mAP50" width="90">
            <template #default="{ row }">
              {{ fmtMetric(row.latestMetrics, 'metrics/mAP50(B)') }}
            </template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="jobStatusType(row.status)" size="small">{{ jobStatusText(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="300" fixed="right">
            <template #default="{ row }">
              <el-button size="small" type="primary" v-if="row.status === 'pending' || row.status === 'failed'"
                @click="startJob(row)">启动</el-button>
              <el-button
                size="small"
                type="warning"
                v-if="row.status === 'running' || row.status === 'cancelling'"
                :loading="cancellingId === row.id"
                @click="cancelJob(row)"
              >{{ row.status === 'cancelling' ? '取消中' : '取消' }}</el-button>
              <el-button size="small" @click="openJobDetail(row)">监控</el-button>
              <el-button size="small" type="danger" :icon="Delete" @click="removeJob(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-pagination class="pager" v-model:current-page="jobPage" v-model:page-size="jobSize"
          :total="jobTotal" layout="total, prev, pager, next" @current-change="loadJobs" />
      </el-tab-pane>

      <!-- ── 格式说明 ── -->
      <el-tab-pane label="格式说明" name="formats">
        <div class="format-list" v-loading="formatsLoading">
          <el-card v-for="f in formatOptions" :key="f.value" shadow="never" class="format-card">
            <template #header>
              <div class="format-card-hd">
                <el-tag type="primary" size="small">{{ f.value }}</el-tag>
                <span class="format-card-title">{{ f.label }}</span>
              </div>
            </template>
            <p class="guide-summary">{{ f.summary }}</p>
            <div class="guide-section">
              <div class="guide-label">目录结构</div>
              <pre class="guide-tree">{{ f.directoryTree }}</pre>
            </div>
            <el-descriptions :column="1" border size="small" class="guide-desc">
              <el-descriptions-item label="必需文件">{{ f.requiredFiles }}</el-descriptions-item>
              <el-descriptions-item label="类别填写">{{ f.classNames }}</el-descriptions-item>
              <el-descriptions-item label="训练比例">{{ f.splitRatio }}</el-descriptions-item>
              <el-descriptions-item label="上传类型">{{ f.uploadTypes }}</el-descriptions-item>
              <el-descriptions-item label="示例">{{ f.example }}</el-descriptions-item>
            </el-descriptions>
            <ul v-if="f.notes?.length" class="guide-notes">
              <li v-for="(n, i) in f.notes" :key="i">{{ n }}</li>
            </ul>
          </el-card>
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- 数据集对话框 -->
    <el-dialog v-model="dsDialog" :title="dsForm.id ? '编辑数据集' : '新建数据集'" width="600px" @closed="resetDsForm">
      <el-form :model="dsForm" label-width="110px">
        <el-form-item label="名称" required>
          <el-input v-model="dsForm.name" placeholder="如：水位尺数据集" />
        </el-form-item>
        <el-form-item label="数据格式" required>
          <el-select v-model="dsForm.format" style="width:100%" @change="onFormatChange">
            <el-option v-for="f in formatOptions" :key="f.value" :label="f.label" :value="f.value" />
          </el-select>
        </el-form-item>
        <!-- 格式详细说明 -->
        <el-collapse v-if="selectedFormatSpec" class="format-guide">
          <el-collapse-item title="格式详细说明（目录结构 / 要求 / 示例）" name="guide">
            <div class="guide-block">
              <p class="guide-summary">{{ selectedFormatSpec.summary }}</p>
              <div class="guide-section">
                <div class="guide-label">目录结构</div>
                <pre class="guide-tree">{{ selectedFormatSpec.directoryTree }}</pre>
              </div>
              <el-descriptions :column="1" border size="small" class="guide-desc">
                <el-descriptions-item label="必需文件">{{ selectedFormatSpec.requiredFiles }}</el-descriptions-item>
                <el-descriptions-item label="类别填写">{{ selectedFormatSpec.classNames }}</el-descriptions-item>
                <el-descriptions-item label="训练比例">{{ selectedFormatSpec.splitRatio }}</el-descriptions-item>
                <el-descriptions-item label="上传类型">{{ selectedFormatSpec.uploadTypes }}</el-descriptions-item>
                <el-descriptions-item label="示例">{{ selectedFormatSpec.example }}</el-descriptions-item>
              </el-descriptions>
              <ul v-if="selectedFormatSpec.notes?.length" class="guide-notes">
                <li v-for="(n, i) in selectedFormatSpec.notes" :key="i">{{ n }}</li>
              </ul>
            </div>
          </el-collapse-item>
        </el-collapse>
        <el-form-item v-if="dsForm.format === 'import'" label="本地路径" required>
          <el-input v-model="dsForm.sourcePath"
            placeholder="如 F:/python_project/.../backend/yolo_dataset" />
          <div class="field-hint">仅允许项目目录内的已有 YOLO/VOC 数据集路径</div>
        </el-form-item>
        <el-form-item label="类别" :required="needClassNames">
          <el-select v-model="dsForm.classNames" multiple filterable allow-create default-first-option
            :placeholder="classNamesPlaceholder" style="width:100%" />
        </el-form-item>
        <el-form-item v-if="showSplitRatio" label="训练比例">
          <el-slider v-model="dsForm.splitRatio" :min="0.5" :max="0.95" :step="0.05" show-input />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="dsForm.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-alert v-if="selectedFormatSpec?.summary" type="info" :closable="false"
          :title="selectedFormatSpec.summary" />
      </el-form>
      <template #footer>
        <el-button @click="dsDialog = false">取消</el-button>
        <el-button type="primary" :loading="dsSaving" @click="saveDs">保存</el-button>
      </template>
    </el-dialog>

    <!-- 视频抽帧 -->
    <el-dialog v-model="extractDialog" title="视频抽帧" width="520px" @closed="resetExtractForm">
      <el-form :model="extractForm" label-width="110px">
        <el-form-item label="数据集">
          <el-input :model-value="extractForm.datasetName" disabled />
        </el-form-item>
        <el-form-item label="选择视频" required>
          <el-upload :show-file-list="true" :auto-upload="false" :limit="1" accept="video/*"
            :on-change="onExtractVideoPick" :on-remove="() => { extractForm.file = null }">
            <el-button :icon="VideoCamera">选择视频</el-button>
          </el-upload>
        </el-form-item>
        <el-form-item label="抽帧间隔">
          <el-input-number v-model="extractForm.frameInterval" :min="1" :max="30" />
          <span class="field-hint-inline">每 N 帧保存 1 张（10s@30fps 间隔1≈300张）</span>
        </el-form-item>
        <el-form-item label="最大帧数">
          <el-input-number v-model="extractForm.maxFrames" :min="10" :max="2000" :step="10" />
        </el-form-item>
        <el-form-item label="起始秒">
          <el-input-number v-model="extractForm.startSec" :min="0" :max="600" :step="0.5" />
        </el-form-item>
        <el-form-item label="结束秒">
          <el-input-number v-model="extractForm.endSec" :min="0" :max="600" :step="0.5" />
          <span class="field-hint-inline">0 表示到视频末尾</span>
        </el-form-item>
        <el-alert type="info" :closable="false"
          title="抽帧图片保存到 raw/images/，完成后请到「数据标注」页画框，再点击「构建」生成训练集。" />
      </el-form>
      <template #footer>
        <el-button @click="extractDialog = false">取消</el-button>
        <el-button type="primary" :loading="extracting" @click="submitExtract">开始抽帧</el-button>
      </template>
    </el-dialog>

    <!-- 新建训练任务 -->
    <el-dialog v-model="jobDialog" title="新建训练任务" width="560px" @closed="resetJobForm">
      <el-form :model="jobForm" label-width="100px">
        <el-form-item label="任务名称" required>
          <el-input v-model="jobForm.jobName" placeholder="如：水位尺-v1" />
        </el-form-item>
        <el-form-item label="数据集" required>
          <el-select v-model="jobForm.datasetId" placeholder="选择已构建的数据集" style="width:100%">
            <el-option v-for="d in readyDatasets" :key="d.id" :label="`${d.name} (${d.trainCount}/${d.valCount})`" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="基座模型">
          <el-select v-model="jobForm.baseModel" style="width:100%" filterable>
            <el-option-group v-for="g in baseModelGroups" :key="g.label" :label="g.label">
              <el-option v-for="o in g.options" :key="o.value" :label="o.label" :value="o.value">
                <span>{{ o.label }}</span>
                <span v-if="o.hint" class="opt-hint">{{ o.hint }}</span>
              </el-option>
            </el-option-group>
          </el-select>
        </el-form-item>
        <el-form-item label="训练轮数">
          <el-input-number v-model="jobForm.epochs" :min="1" :max="500" />
        </el-form-item>
        <el-form-item label="Batch">
          <el-input-number v-model="jobForm.batch" :min="1" :max="64" />
        </el-form-item>
        <el-form-item label="图像尺寸">
          <el-input-number v-model="jobForm.imgsz" :min="320" :max="1280" :step="32" />
        </el-form-item>
        <el-form-item label="设备">
          <el-radio-group v-model="jobForm.device">
            <el-radio value="cpu">CPU</el-radio>
            <el-radio value="0">GPU (cuda:0)</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="jobDialog = false">取消</el-button>
        <el-button type="primary" :loading="jobSaving" @click="saveJob">创建</el-button>
      </template>
    </el-dialog>

    <!-- 训练监控抽屉 -->
    <el-drawer
      v-model="detailOpen"
      :title="`训练监控 — ${detailJob?.jobName || ''}`"
      size="78%"
      destroy-on-close
      class="monitor-drawer"
    >
      <div v-if="detailJob" class="monitor-shell">
        <!-- 概览头部 -->
        <section class="monitor-hero">
          <div class="hero-top">
            <div class="hero-info">
              <h3 class="hero-title">{{ detailJob.jobName }}</h3>
              <div class="hero-meta">
                <span><b>数据集</b> {{ detailJob.datasetName || '—' }}</span>
                <span class="meta-dot">·</span>
                <span><b>基座</b> {{ detailJob.baseModel || '—' }}</span>
                <span class="meta-dot">·</span>
                <span><b>设备</b> {{ detailJob.device === '0' ? 'GPU' : 'CPU' }}</span>
              </div>
            </div>
            <el-tag :type="jobStatusType(detailJob.status)" effect="dark" size="large" round>
              {{ jobStatusText(detailJob.status) }}
            </el-tag>
          </div>

          <div class="stat-grid">
            <div class="stat-card stat-primary">
              <div class="stat-label">训练进度</div>
              <div class="stat-value">{{ detailJob.progress || 0 }}<span class="stat-unit">%</span></div>
            </div>
            <div class="stat-card">
              <div class="stat-label">Epoch</div>
              <div class="stat-value">{{ detailJob.currentEpoch || 0 }}<span class="stat-unit"> / {{ detailJob.totalEpochs || 0 }}</span></div>
            </div>
            <div class="stat-card">
              <div class="stat-label">mAP50</div>
              <div class="stat-value stat-accent">{{ detailMap50 }}</div>
            </div>
            <div class="stat-card">
              <div class="stat-label">mAP50-95</div>
              <div class="stat-value">{{ detailMap5095 }}</div>
            </div>
          </div>

          <div class="progress-block">
            <el-progress
              :percentage="detailJob.progress || 0"
              :stroke-width="14"
              :status="detailJob.status === 'done' ? 'success' : detailJob.status === 'failed' ? 'exception' : ''"
            />
          </div>
          <el-alert v-if="detailJob.errorMessage" type="error" :closable="false" :title="detailJob.errorMessage" show-icon class="hero-alert" />
        </section>

        <!-- 分区内容 -->
        <el-tabs v-model="monitorTab" class="monitor-tabs">
          <el-tab-pane label="训练曲线" name="charts">
            <div v-if="chartUrls.length" class="chart-grid">
              <div v-for="c in chartUrls" :key="c.name" class="chart-item">
                <div class="chart-title">{{ c.label }}</div>
                <img :src="c.url" class="chart-img" :alt="c.label" />
              </div>
            </div>
            <el-empty v-else description="训练进行中或完成后将显示 loss / mAP 曲线图" />
          </el-tab-pane>

          <el-tab-pane label="实时日志" name="logs">
            <div class="log-panels">
              <div class="log-panel">
                <div class="panel-hd">
                  <span class="panel-title">训练日志</span>
                  <el-tag size="small" type="info">stdout</el-tag>
                </div>
                <el-scrollbar height="360px" class="log-box">
                  <pre class="log-pre">{{ trainLogText || '（等待训练输出…）' }}</pre>
                </el-scrollbar>
              </div>
              <div class="log-panel">
                <div class="panel-hd">
                  <span class="panel-title">验证日志</span>
                  <el-tag size="small" type="warning">val</el-tag>
                </div>
                <el-scrollbar height="360px" class="log-box">
                  <pre class="log-pre">{{ valLogText || '（暂无验证日志）' }}</pre>
                </el-scrollbar>
              </div>
            </div>
          </el-tab-pane>

          <el-tab-pane label="指标历史" name="metrics">
            <el-table :data="metricsRows" size="small" border stripe max-height="420" empty-text="暂无指标数据">
              <el-table-column prop="epoch" label="Epoch" width="80" align="center" fixed />
              <el-table-column label="box_loss" min-width="100" align="center">
                <template #default="{ row }">{{ fmtNum(row['train/box_loss']) }}</template>
              </el-table-column>
              <el-table-column label="cls_loss" min-width="100" align="center">
                <template #default="{ row }">{{ fmtNum(row['train/cls_loss']) }}</template>
              </el-table-column>
              <el-table-column label="mAP50" min-width="100" align="center">
                <template #default="{ row }">{{ fmtNum(row['metrics/mAP50(B)'] ?? row.mAP50) }}</template>
              </el-table-column>
              <el-table-column label="mAP50-95" min-width="110" align="center">
                <template #default="{ row }">{{ fmtNum(row['metrics/mAP50-95(B)'] ?? row['mAP50-95']) }}</template>
              </el-table-column>
            </el-table>
          </el-tab-pane>

          <el-tab-pane label="模型应用" name="workflow">
            <div class="workflow-grid">
              <!-- 验证 -->
              <div class="workflow-card">
                <div class="wf-hd">
                  <span class="wf-step">01</span>
                  <div>
                    <div class="wf-title">模型验证</div>
                    <div class="wf-desc">在验证集上评估精度指标</div>
                  </div>
                </div>
                <div class="wf-body">
                  <el-button type="primary" :loading="validating" :disabled="detailJob.status !== 'done'" @click="runValidate">
                    开始验证
                  </el-button>
                  <el-progress
                    v-if="valProgress.status && valProgress.status !== 'idle'"
                    :percentage="valProgress.progress || 0"
                    class="wf-progress"
                  />
                  <el-descriptions v-if="valResult" :column="1" border size="small" class="wf-result">
                    <el-descriptions-item v-for="(v, k) in valResult" :key="k" :label="k">{{ v }}</el-descriptions-item>
                  </el-descriptions>
                </div>
              </div>

              <!-- 测试 -->
              <div class="workflow-card">
                <div class="wf-hd">
                  <span class="wf-step">02</span>
                  <div>
                    <div class="wf-title">推理测试</div>
                    <div class="wf-desc">上传单张图片查看检测效果</div>
                  </div>
                </div>
                <div class="wf-body">
                  <div class="wf-actions">
                    <el-upload :show-file-list="false" :auto-upload="false" accept="image/*" :on-change="onTestPick">
                      <el-button :icon="Upload" :disabled="detailJob.status !== 'done'">选择图片</el-button>
                    </el-upload>
                    <el-button type="primary" :loading="testing" :disabled="!testFile || detailJob.status !== 'done'" @click="runTest">
                      运行推理
                    </el-button>
                  </div>
                  <div v-if="testResult?.imageBase64" class="test-preview">
                    <img :src="'data:image/jpeg;base64,' + testResult.imageBase64" alt="检测结果" />
                    <p>检出 <b>{{ testResult.count }}</b> 个目标</p>
                  </div>
                  <div v-else class="wf-placeholder">训练完成后可上传测试图</div>
                </div>
              </div>

              <!-- 导出 -->
              <div class="workflow-card">
                <div class="wf-hd">
                  <span class="wf-step">03</span>
                  <div>
                    <div class="wf-title">模型导出</div>
                    <div class="wf-desc">导出为 ONNX 或 TorchScript</div>
                  </div>
                </div>
                <div class="wf-body">
                  <div class="wf-actions">
                    <el-radio-group v-model="exportFmt" size="small">
                      <el-radio-button value="onnx">ONNX</el-radio-button>
                      <el-radio-button value="torchscript">TorchScript</el-radio-button>
                    </el-radio-group>
                    <el-button type="success" :loading="exporting" :disabled="detailJob.status !== 'done'" @click="runExport">
                      导出
                    </el-button>
                  </div>
                  <div v-if="exportInfo" class="export-info">
                    <el-icon><Document /></el-icon>
                    <span>{{ exportInfo.fileName }} ({{ fmtSize(exportInfo.size) }})</span>
                    <el-button link type="primary" @click="downloadExport">下载</el-button>
                  </div>
                </div>
              </div>

              <!-- 部署 -->
              <div class="workflow-card wf-span">
                <div class="wf-hd">
                  <span class="wf-step">04</span>
                  <div>
                    <div class="wf-title">部署到模型管理</div>
                    <div class="wf-desc">注册后可在羽毛球分析等页面选用（library=ultralytics）</div>
                  </div>
                </div>
                <div class="wf-body wf-deploy">
                  <el-form :model="deployForm" label-width="88px" size="default" class="deploy-form">
                    <el-row :gutter="16">
                      <el-col :span="8">
                        <el-form-item label="模型名称">
                          <el-input v-model="deployForm.modelName" placeholder="显示名称" />
                        </el-form-item>
                      </el-col>
                      <el-col :span="8">
                        <el-form-item label="模型标识">
                          <el-input v-model="deployForm.modelKey" placeholder="唯一 key" />
                        </el-form-item>
                      </el-col>
                      <el-col :span="8">
                        <el-form-item label="分类">
                          <el-input v-model="deployForm.category" />
                        </el-form-item>
                      </el-col>
                    </el-row>
                    <el-checkbox v-model="deployForm.forBadminton">部署为羽毛球检测模型（目标检测 / 分析页优先选用）</el-checkbox>
                  </el-form>
                  <div class="wf-actions">
                    <el-button @click="fillBadmintonDeploy" :disabled="detailJob.status !== 'done'">填入羽毛球预设</el-button>
                    <el-button type="primary" :loading="deploying" :disabled="detailJob.status !== 'done'" @click="runDeploy">
                      注册到模型管理
                    </el-button>
                    <el-tag v-if="detailJob.outputModelId" type="success" effect="plain">
                      已部署 #{{ detailJob.outputModelId }}
                    </el-tag>
                  </div>
                </div>
              </div>
            </div>
          </el-tab-pane>
        </el-tabs>
      </div>
    </el-drawer>

    <!-- 数据集预览 -->
    <el-dialog v-model="previewOpen" :title="`数据集预览 — ${previewData?.dataset?.name || ''}`" width="640px">
      <div v-if="previewData">
        <el-descriptions :column="2" border size="small" class="preview-desc">
          <el-descriptions-item label="格式">{{ formatLabel(previewData.dataset?.format) }}</el-descriptions-item>
          <el-descriptions-item label="检测格式">
            {{ previewData.formatLabel || previewData.detectedFormat || '未检测' }}
          </el-descriptions-item>
          <el-descriptions-item label="data.yaml">{{ previewData.hasDataYaml ? '有' : '无' }}</el-descriptions-item>
          <el-descriptions-item label="COCO JSON">{{ previewData.cocoJsonCount ?? 0 }} 个</el-descriptions-item>
          <el-descriptions-item label="LabelMe 配对">{{ previewData.labelmePairs ?? 0 }} 组</el-descriptions-item>
          <el-descriptions-item label="文件数">{{ previewData.fileCount ?? 0 }}</el-descriptions-item>
          <el-descriptions-item v-if="previewData.annotation" label="标注进度">
            已标 {{ previewData.annotation.annotated }} / 共 {{ previewData.annotation.total }}
            （{{ previewData.annotation.totalBoxes }} 框）
          </el-descriptions-item>
          <el-descriptions-item v-if="previewData.yamlNames?.length" label="YAML 类别" :span="2">
            <el-tag v-for="n in previewData.yamlNames" :key="n" size="small" style="margin:2px">{{ n }}</el-tag>
          </el-descriptions-item>
        </el-descriptions>
        <el-table :data="previewData.files || []" size="small" border max-height="320" class="mt12">
          <el-table-column prop="name" label="文件" min-width="280" show-overflow-tooltip />
          <el-table-column label="大小" width="100">
            <template #default="{ row }">{{ fmtSize(row.size) }}</template>
          </el-table-column>
        </el-table>
      </div>
    </el-dialog>

    <div class="doc-links">
      <el-link :href="ANNOTATION_DOC_URL" target="_blank" type="primary" :underline="false">
        <el-icon class="doc-link-icon"><Document /></el-icon>
        数据标注功能说明
      </el-link>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh, Edit, Delete, Upload, Document, VideoCamera } from '@element-plus/icons-vue'
import { trainingApi } from '../../../api/ai'
import AnnotateToolsPanel from './annotateTools.vue'
import QualityPanel from './quality.vue'
import ConvertPanel from './convert.vue'

const route = useRoute()
const router = useRouter()

const ANNOTATION_DOC_URL = 'https://github.com/5758703/CV_PythonVue_TigerPro/blob/main/docs/数据标注功能说明.md'

const activeTab = ref('dataset')
const annotateSubTab = ref('canvas')
const annotateRef = ref(null)
const qualityRef = ref(null)
const convertRef = ref(null)
const annotateDatasetId = ref(null)

const formatsLoading = ref(false)
const dsLoading = ref(false)
const datasets = ref([])
const dsPage = ref(1)
const dsSize = ref(10)
const dsTotal = ref(0)
const dsQuery = reactive({ name: '' })
const dsDialog = ref(false)
const dsSaving = ref(false)
const formatOptions = ref([])
const dsForm = reactive({
  id: null, name: '', format: 'auto', classNames: [], splitRatio: 0.8,
  description: '', sourcePath: ''
})
const previewOpen = ref(false)
const previewData = ref(null)

const extractDialog = ref(false)
const extracting = ref(false)
const extractForm = reactive({
  datasetId: null,
  datasetName: '',
  file: null,
  frameInterval: 1,
  maxFrames: 250,
  startSec: 0,
  endSec: 0,
})

const needClassNames = computed(() => !['yolo', 'auto', 'coco', 'labelme', 'import'].includes(dsForm.format))
const showSplitRatio = computed(() => !['yolo', 'import'].includes(dsForm.format))
const selectedFormatSpec = computed(() =>
  formatOptions.value.find(f => f.value === dsForm.format) || null
)
const classNamesPlaceholder = computed(() => {
  if (['yolo', 'auto'].includes(dsForm.format)) return '可选；YOLO 可从 data.yaml 自动读取'
  if (dsForm.format === 'coco') return '可选；不填则使用 COCO JSON categories 全部类别'
  if (dsForm.format === 'labelme') return '可选；不填则汇总所有 shapes[].label'
  if (dsForm.format === 'import') return '可选；导入时可从标注文件推断'
  return '输入类别名后回车，如 WaterGuage'
})

function formatLabel(fmt) {
  const f = formatOptions.value.find(x => x.value === fmt)
  if (f) return f.label.split('（')[0]
  const map = {
    auto: '自动检测', voc: 'VOC', voc_standard: 'VOC标准', yolo: 'YOLO',
    yolo_flat: 'YOLO扁平', coco: 'COCO', labelme: 'LabelMe', import: '本地导入'
  }
  return map[fmt] || fmt || '-'
}

function uploadAccept(fmt) {
  if (fmt === 'yolo' || fmt === 'yolo_flat') {
    return '.jpg,.jpeg,.png,.bmp,.txt,.yaml,.yml,.zip'
  }
  if (fmt === 'voc_standard') {
    return '.jpg,.jpeg,.png,.bmp,.xml,.zip'
  }
  if (fmt === 'coco' || fmt === 'labelme') {
    return '.jpg,.jpeg,.png,.bmp,.json,.zip'
  }
  return '.jpg,.jpeg,.png,.bmp,.xml,.txt,.json,.zip'
}

function onFormatChange() {
  if (dsForm.format === 'import') {
    dsForm.sourcePath = dsForm.sourcePath || 'F:/python_project/CV_PyhonVue_Tigerpro/backend/yolo_dataset'
  }
}

async function loadFormats() {
  formatsLoading.value = true
  try {
    const res = await trainingApi.datasetFormats()
    formatOptions.value = res.data || []
  } catch {
    formatOptions.value = [
      { value: 'auto', label: '自动检测' },
      { value: 'voc', label: 'Pascal VOC' },
      { value: 'yolo', label: 'YOLO 原生' },
      { value: 'import', label: '本地导入' },
    ]
  } finally { formatsLoading.value = false }
}

const readyDatasets = computed(() => datasets.value.filter(d => d.status === 'ready'))

function dsStatusType(s) {
  return { draft: 'info', ready: 'success', error: 'danger' }[s] || 'info'
}
function dsStatusText(s) {
  return { draft: '草稿', ready: '就绪', error: '错误' }[s] || s
}

async function loadDatasets() {
  dsLoading.value = true
  try {
    const res = await trainingApi.listDatasets({ pageNum: dsPage.value, pageSize: dsSize.value, name: dsQuery.name })
    datasets.value = res.data.rows
    dsTotal.value = res.data.total
  } finally { dsLoading.value = false }
}

function openDsDialog(row) {
  if (row) {
    Object.assign(dsForm, {
      id: row.id, name: row.name, format: row.format || 'auto',
      classNames: [...row.classNames], splitRatio: row.splitRatio,
      description: row.description || '', sourcePath: row.sourcePath || ''
    })
  } else {
    resetDsForm()
  }
  dsDialog.value = true
}

function resetDsForm() {
  Object.assign(dsForm, {
    id: null, name: '', format: 'auto', classNames: [], splitRatio: 0.8,
    description: '', sourcePath: ''
  })
}

async function saveDs() {
  if (!dsForm.name) {
    ElMessage.warning('请填写名称')
    return
  }
  if (needClassNames.value && !dsForm.classNames.length) {
    ElMessage.warning('请填写类别')
    return
  }
  if (dsForm.format === 'import' && !dsForm.sourcePath.trim()) {
    ElMessage.warning('请填写本地数据集路径')
    return
  }
  dsSaving.value = true
  try {
    const payload = {
      name: dsForm.name, format: dsForm.format, classNames: dsForm.classNames,
      splitRatio: dsForm.splitRatio, description: dsForm.description,
      sourcePath: dsForm.sourcePath || undefined
    }
    if (dsForm.id) {
      await trainingApi.updateDataset(dsForm.id, payload)
      ElMessage.success('更新成功')
    } else {
      await trainingApi.addDataset(payload)
      ElMessage.success('创建成功，请上传数据或构建')
    }
    dsDialog.value = false
    loadDatasets()
  } finally { dsSaving.value = false }
}

async function onDsUpload(row, uploadFile) {
  const fd = new FormData()
  fd.append('files', uploadFile.raw)
  try {
    const res = await trainingApi.uploadDatasetFiles(row.id, fd)
    ElMessage.success(res.message || '上传成功')
  } catch (e) {
    ElMessage.error(e.message || '上传失败')
  }
}

async function buildDs(row) {
  row._building = true
  try {
    const res = await trainingApi.buildDataset(row.id)
    ElMessage.success(res.message)
    loadDatasets()
  } catch (e) {
    ElMessage.error(e.message || '构建失败')
  } finally { row._building = false }
}

async function previewDs(row) {
  try {
    const res = await trainingApi.datasetSamples(row.id)
    previewData.value = res.data
    previewOpen.value = true
  } catch (e) {
    ElMessage.error(e.message || '预览失败')
  }
}

function openExtractDialog(row) {
  extractForm.datasetId = row.id
  extractForm.datasetName = row.name
  extractForm.file = null
  extractForm.frameInterval = 1
  extractForm.maxFrames = 250
  extractForm.startSec = 0
  extractForm.endSec = 0
  extractDialog.value = true
}

function resetExtractForm() {
  extractForm.datasetId = null
  extractForm.datasetName = ''
  extractForm.file = null
}

function onExtractVideoPick(uploadFile) {
  extractForm.file = uploadFile.raw
}

async function submitExtract() {
  if (!extractForm.datasetId || !extractForm.file) {
    ElMessage.warning('请选择视频文件')
    return
  }
  extracting.value = true
  try {
    const fd = new FormData()
    fd.append('file', extractForm.file)
    fd.append('frameInterval', extractForm.frameInterval)
    fd.append('maxFrames', extractForm.maxFrames)
    fd.append('startSec', extractForm.startSec)
    if (extractForm.endSec > 0) fd.append('endSec', extractForm.endSec)
    const res = await trainingApi.extractFrames(extractForm.datasetId, fd)
    ElMessage.success(res.message || '抽帧完成')
    extractDialog.value = false
    loadDatasets()
    annotateDatasetId.value = extractForm.datasetId
    activeTab.value = 'annotate'
    annotateSubTab.value = 'canvas'
    annotateRef.value?.setDatasetId?.(extractForm.datasetId)
    qualityRef.value?.setDatasetId?.(extractForm.datasetId)
    convertRef.value?.setDatasetId?.(extractForm.datasetId)
  } catch (e) {
    ElMessage.error(e.message || '抽帧失败')
  } finally {
    extracting.value = false
  }
}

function openAnnotate(row) {
  if (!row.classNames?.length) {
    ElMessage.warning('请先编辑数据集并配置类别名称')
    return
  }
  annotateDatasetId.value = row.id
  activeTab.value = 'annotate'
  annotateSubTab.value = 'canvas'
  annotateRef.value?.setDatasetId?.(row.id)
  qualityRef.value?.setDatasetId?.(row.id)
  convertRef.value?.setDatasetId?.(row.id)
}

async function removeDs(row) {
  await ElMessageBox.confirm(`确定删除数据集「${row.name}」？`, '提示', { type: 'warning' })
  await trainingApi.removeDataset(row.id)
  ElMessage.success('已删除')
  loadDatasets()
}

// ── 训练任务 ──
const jobLoading = ref(false)
const jobs = ref([])
const jobPage = ref(1)
const jobSize = ref(10)
const jobTotal = ref(0)
const jobQuery = reactive({ status: '' })
const jobDialog = ref(false)
const jobSaving = ref(false)
const jobForm = reactive({
  jobName: '', datasetId: null, baseModel: 'yolo11n.pt',
  epochs: 100, batch: 8, imgsz: 640, device: 'cpu'
})
const baseModelOptions = ref([])
const baseModelGroups = computed(() => {
  const groups = [
    { key: 'yolo11', label: 'YOLO11（推荐羽毛球）', options: [] },
    { key: 'finetune', label: '本地微调起点', options: [] },
    { key: 'yolov8', label: 'YOLOv8', options: [] },
  ]
  const map = Object.fromEntries(groups.map(g => [g.key, g]))
  for (const o of baseModelOptions.value) {
    const g = map[o.group] || map.yolov8
    g.options.push(o)
  }
  return groups.filter(g => g.options.length)
})

async function loadBaseModels() {
  try {
    const res = await trainingApi.baseModels()
    baseModelOptions.value = res.data || []
  } catch {
    baseModelOptions.value = [
      { value: 'yolo11n.pt', label: 'YOLO11n', group: 'yolo11' },
      { value: 'yolo11s.pt', label: 'YOLO11s', group: 'yolo11' },
      { value: 'yolov8n.pt', label: 'YOLOv8n', group: 'yolov8' },
    ]
  }
}

async function applyBadmintonPreset() {
  try {
    const res = await trainingApi.badmintonPreset()
    const p = res.data || {}
    const ds = p.dataset || {}
    Object.assign(dsForm, {
      id: null,
      name: ds.name || '羽毛球检测-Roboflow',
      format: ds.format || 'auto',
      classNames: [...(ds.classNames || ['badminton'])],
      splitRatio: ds.splitRatio ?? 0.8,
      description: ds.hint || '',
      sourcePath: '',
    })
    const jb = p.job || {}
    Object.assign(jobForm, {
      jobName: jb.jobName || '羽毛球YOLO11n自训',
      datasetId: null,
      baseModel: jb.baseModel || 'yolo11n.pt',
      epochs: jb.epochs ?? 80,
      batch: jb.batch ?? 8,
      imgsz: jb.imgsz ?? 960,
      device: jb.device || 'cpu',
    })
    activeTab.value = 'dataset'
    dsDialog.value = true
    ElMessage.success('已套用羽毛球自训预设：上传 Roboflow YOLO zip 后构建，再新建训练任务')
    const steps = (p.workflow || []).map((s, i) => `${i + 1}. ${s}`).join('\n')
    if (steps) {
      ElMessageBox.alert(steps, '羽毛球自训流程', { confirmButtonText: '知道了' })
    }
  } catch (e) {
    ElMessage.error(e?.message || '加载预设失败')
  }
}

function jobStatusType(s) {
  return {
    pending: 'info', running: 'warning', cancelling: 'warning',
    done: 'success', failed: 'danger', cancelled: 'info',
  }[s] || 'info'
}
function jobStatusText(s) {
  return {
    pending: '待训练', running: '训练中', cancelling: '取消中',
    done: '已完成', failed: '失败', cancelled: '已取消',
  }[s] || s
}
function jobProgressStatus(row) {
  if (row.status === 'done') return 'success'
  if (row.status === 'failed') return 'exception'
  return ''
}
function fmtMetric(m, key) {
  if (!m || m[key] == null) return '-'
  return Number(m[key]).toFixed(4)
}
function fmtNum(v) {
  if (v == null || v === '') return '-'
  return Number(v).toFixed(4)
}
function fmtSize(n) {
  if (!n) return '0 B'
  if (n < 1024) return n + ' B'
  if (n < 1048576) return (n / 1024).toFixed(1) + ' KB'
  return (n / 1048576).toFixed(1) + ' MB'
}

async function loadJobs() {
  jobLoading.value = true
  try {
    const res = await trainingApi.listJobs({ pageNum: jobPage.value, pageSize: jobSize.value, status: jobQuery.status })
    jobs.value = res.data.rows
    jobTotal.value = res.data.total
  } finally { jobLoading.value = false }
}

function resetJobForm() {
  Object.assign(jobForm, {
    jobName: '', datasetId: null, baseModel: 'yolo11n.pt',
    epochs: 100, batch: 8, imgsz: 640, device: 'cpu'
  })
}

function openJobDialog() {
  resetJobForm()
  if (route.query.preset === 'badminton') {
    jobForm.imgsz = 960
    jobForm.epochs = 80
    jobForm.jobName = '羽毛球YOLO11n自训'
    jobForm.baseModel = 'yolo11n.pt'
  }
  jobDialog.value = true
  loadDatasets()
  loadBaseModels()
}

async function saveJob() {
  if (!jobForm.jobName || !jobForm.datasetId) {
    ElMessage.warning('请填写任务名称并选择数据集')
    return
  }
  jobSaving.value = true
  try {
    await trainingApi.addJob({ ...jobForm })
    ElMessage.success('任务已创建，点击「启动」开始训练')
    jobDialog.value = false
    loadJobs()
  } finally { jobSaving.value = false }
}

async function startJob(row) {
  await trainingApi.startJob(row.id)
  ElMessage.success('训练已启动')
  loadJobs()
  openJobDetail(row)
}

const cancellingId = ref(null)

async function cancelJob(row) {
  if (cancellingId.value === row.id) return
  try {
    await ElMessageBox.confirm(
      row.status === 'cancelling'
        ? '仍在等待训练线程响应，是否再次发送取消请求？'
        : '确定取消该训练任务？将在当前 batch 结束后停止（首轮可能需等待片刻）。',
      '取消训练',
      { type: 'warning', confirmButtonText: '确定取消', cancelButtonText: '返回' },
    )
  } catch {
    return
  }
  cancellingId.value = row.id
  try {
    const res = await trainingApi.cancelJob(row.id)
    ElMessage.success(res.message || '已请求取消')
    row.status = res.data?.status || 'cancelling'
    // 轮询直到真正 cancelled；超时则强制标记（应对后端重启后线程已死）
    let done = false
    for (let i = 0; i < 45; i++) {
      await loadJobs()
      const cur = jobs.value.find(j => j.id === row.id)
      if (!cur || ['cancelled', 'failed', 'done'].includes(cur.status)) {
        if (cur?.status === 'cancelled') ElMessage.success('训练已取消')
        done = true
        break
      }
      await new Promise(r => setTimeout(r, 2000))
    }
    if (!done) {
      try {
        await ElMessageBox.confirm(
          '训练线程长时间未响应（可能后端已重启）。是否强制标记为「已取消」？',
          '强制取消',
          { type: 'warning', confirmButtonText: '强制取消', cancelButtonText: '继续等待' },
        )
        const fr = await trainingApi.cancelJob(row.id, { force: true })
        ElMessage.success(fr.message || '已强制取消')
      } catch { /* 用户选择继续等待 */ }
    }
  } catch (e) {
    ElMessage.error(e?.response?.data?.message || e.message || '取消失败')
  } finally {
    cancellingId.value = null
    loadJobs()
  }
}

async function removeJob(row) {
  await ElMessageBox.confirm(`确定删除任务「${row.jobName}」？`, '提示', { type: 'warning' })
  await trainingApi.removeJob(row.id)
  ElMessage.success('已删除')
  loadJobs()
}

// ── 训练监控 ──
const detailOpen = ref(false)
const detailJob = ref(null)
const monitorTab = ref('charts')
const chartUrls = ref([])
const metricsRows = ref([])
let pollTimer = null
const chartBlobUrls = []
const trainLogText = ref('')
const valLogText = ref('')
let trainLogOffset = 0
let valLogOffset = 0
const valProgress = ref({ status: 'idle', progress: 0 })

const CHART_LABELS = {
  'results.png': '训练曲线',
  'confusion_matrix.png': '混淆矩阵',
  'F1_curve.png': 'F1 曲线',
  'PR_curve.png': 'PR 曲线'
}

const detailMap50 = computed(() =>
  fmtMetric(detailJob.value?.latestMetrics, 'metrics/mAP50(B)')
)
const detailMap5095 = computed(() =>
  fmtMetric(detailJob.value?.latestMetrics, 'metrics/mAP50-95(B)')
)

async function refreshDetail() {
  if (!detailJob.value) return
  const res = await trainingApi.jobProgress(detailJob.value.id)
  detailJob.value = res.data
  chartBlobUrls.forEach(u => URL.revokeObjectURL(u))
  chartBlobUrls.length = 0
  const charts = []
  for (const [name, _path] of Object.entries(res.data.charts || {})) {
    try {
      const blob = await trainingApi.getArtifact(detailJob.value.id, name)
      const url = URL.createObjectURL(blob)
      chartBlobUrls.push(url)
      charts.push({ name, label: CHART_LABELS[name] || name, url })
    } catch { /* 图表尚未生成 */ }
  }
  chartUrls.value = charts
  metricsRows.value = (res.data.metricsHistory || []).map((r, i) => ({
    epoch: r.epoch ?? i + 1, ...r
  }))
}

async function refreshLogs() {
  if (!detailJob.value) return
  try {
    const r1 = await trainingApi.jobLogs(detailJob.value.id, { type: 'train', offset: trainLogOffset, limit: 8000 })
    if (r1.data?.text) {
      trainLogText.value += r1.data.text
      trainLogOffset = r1.data.nextOffset ?? trainLogOffset
    }
  } catch {}
  try {
    const r2 = await trainingApi.jobLogs(detailJob.value.id, { type: 'val', offset: valLogOffset, limit: 8000 })
    if (r2.data?.text) {
      valLogText.value += r2.data.text
      valLogOffset = r2.data.nextOffset ?? valLogOffset
    }
  } catch {}
}

async function openJobDetail(row) {
  detailJob.value = { ...row }
  detailOpen.value = true
  monitorTab.value = row.status === 'done' ? 'workflow' : 'charts'
  valResult.value = null
  testResult.value = null
  exportInfo.value = null
  trainLogText.value = ''
  valLogText.value = ''
  trainLogOffset = 0
  valLogOffset = 0
  valProgress.value = { status: 'idle', progress: 0 }
  await refreshDetail()
  await refreshLogs()
  startPoll()
}

function startPoll() {
  stopPoll()
  if (!detailJob.value || !['running', 'pending'].includes(detailJob.value.status)) return
  pollTimer = setInterval(async () => {
    await refreshDetail()
    await refreshLogs()
    loadJobs()
    if (detailJob.value && !['running', 'pending'].includes(detailJob.value.status)) {
      stopPoll()
      loadJobs()
    }
  }, 3000)
}

function stopPoll() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

watch(detailOpen, (v) => {
  if (!v) {
    stopPoll()
    chartBlobUrls.forEach(u => URL.revokeObjectURL(u))
    chartBlobUrls.length = 0
    trainLogText.value = ''
    valLogText.value = ''
    trainLogOffset = 0
    valLogOffset = 0
  }
})
onBeforeUnmount(() => {
  stopPoll()
  chartBlobUrls.forEach(u => URL.revokeObjectURL(u))
})

// 验证 / 测试 / 导出 / 部署
const validating = ref(false)
const valResult = ref(null)
const testing = ref(false)
const testFile = ref(null)
const testResult = ref(null)
const exporting = ref(false)
const exportFmt = ref('onnx')
const exportInfo = ref(null)
const deploying = ref(false)
const deployForm = reactive({
  modelName: '', modelKey: '', category: '目标检测', forBadminton: false, description: '',
})

async function fillBadmintonDeploy() {
  if (!detailJob.value) return
  try {
    const res = await trainingApi.badmintonPreset()
    const d = { ...(res.data?.deploy || {}) }
    // 用当前 job id 生成唯一 key
    const jid = detailJob.value.id
    deployForm.modelName = d.modelName || `自训羽毛球 YOLO11n`
    deployForm.modelKey = (d.modelKey || `badminton-yolo11n-${jid}`).replace(/-0$/, `-${jid}`)
    if (!deployForm.modelKey.includes(String(jid))) {
      deployForm.modelKey = `badminton-yolo11n-${jid}`
    }
    deployForm.category = d.category || '目标检测'
    deployForm.description = d.description || ''
    deployForm.forBadminton = true
    ElMessage.success('已填入羽毛球部署字段')
  } catch {
    deployForm.modelName = `自训羽毛球检测`
    deployForm.modelKey = `badminton-yolo11n-${detailJob.value.id}`
    deployForm.category = '目标检测'
    deployForm.forBadminton = true
  }
}

async function runValidate() {
  validating.value = true
  try {
    await trainingApi.validateJob(detailJob.value.id)
    ElMessage.success('验证已启动')
    const jid = detailJob.value.id
    for (let i = 0; i < 200; i++) {
      await refreshLogs()
      const p = await trainingApi.validateProgress(jid)
      valProgress.value = p.data
      if (p.data.status === 'done') {
        valResult.value = p.data.result
        ElMessage.success('验证完成')
        break
      }
      if (p.data.status === 'error') {
        ElMessage.error(p.data.error || '验证失败')
        break
      }
      await new Promise(r => setTimeout(r, 1500))
    }
  } finally { validating.value = false }
}

function onTestPick(f) { testFile.value = f.raw }

async function runTest() {
  if (!testFile.value) return
  testing.value = true
  try {
    const fd = new FormData()
    fd.append('image', testFile.value)
    const res = await trainingApi.testJob(detailJob.value.id, fd)
    testResult.value = res.data
  } finally { testing.value = false }
}

async function runExport() {
  exporting.value = true
  try {
    const res = await trainingApi.exportJob(detailJob.value.id, { format: exportFmt.value })
    exportInfo.value = res.data
    ElMessage.success('导出成功')
  } finally { exporting.value = false }
}

async function downloadExport() {
  if (!exportInfo.value?.fileName) return
  const blob = await trainingApi.downloadExportFile(detailJob.value.id, exportInfo.value.fileName)
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = exportInfo.value.fileName
  a.click()
  URL.revokeObjectURL(url)
}

async function runDeploy() {
  if (!deployForm.modelName || !deployForm.modelKey) {
    ElMessage.warning('请填写模型名称和标识')
    return
  }
  deploying.value = true
  try {
    const payload = {
      modelName: deployForm.modelName,
      modelKey: deployForm.modelKey,
      category: deployForm.category,
      description: deployForm.description,
      forBadminton: !!deployForm.forBadminton,
    }
    const res = await trainingApi.deployJob(detailJob.value.id, payload)
    ElMessage.success(
      deployForm.forBadminton
        ? `${res.message}，可到「羽毛球分析」选用`
        : res.message,
    )
    detailJob.value.outputModelId = res.data.modelId
    loadJobs()
  } finally { deploying.value = false }
}

watch(detailOpen, (v) => {
  if (v && detailJob.value) {
    const name = detailJob.value.jobName || ''
    const isBdm = /羽毛球|badminton|shuttle/i.test(name) || route.query.preset === 'badminton'
    deployForm.forBadminton = isBdm
    if (isBdm) {
      fillBadmintonDeploy()
    } else {
      deployForm.modelName = name
      deployForm.modelKey = `custom-${detailJob.value.id}`
      deployForm.category = '目标检测'
      deployForm.description = ''
    }
  }
})

onMounted(async () => {
  loadFormats()
  loadBaseModels()
  loadDatasets()
  loadJobs()
  if (route.query.preset === 'badminton') {
    await applyBadmintonPreset()
    // 清理 query，避免重复弹窗
    router.replace({ path: route.path, query: { ...route.query, preset: undefined } })
  }
})
</script>

<style scoped>
.training-root { padding: 0; }
.toolbar { display: flex; gap: 10px; margin-bottom: 14px; flex-wrap: wrap; align-items: center; }
.opt-hint { float: right; color: #909399; font-size: 12px; margin-left: 12px; }
.pager { margin-top: 14px; justify-content: flex-end; }
.epoch-hint { font-size: 12px; color: #909399; margin-left: 8px; }
.mt16 { margin-top: 16px; }
.ml8 { margin-left: 8px; }

/* ── 训练监控抽屉 ── */
.monitor-shell {
  padding: 0 4px 24px;
  background: linear-gradient(180deg, #f5f8fc 0%, #f0f2f5 120px, #f0f2f5 100%);
  min-height: 100%;
}
.monitor-hero {
  background: #fff;
  border-radius: 12px;
  padding: 20px 22px;
  margin-bottom: 16px;
  box-shadow: 0 1px 4px rgba(15, 23, 42, 0.06);
  border: 1px solid #e8edf3;
}
.hero-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 18px;
}
.hero-title {
  margin: 0 0 8px;
  font-size: 20px;
  font-weight: 600;
  color: #1d2b3a;
  letter-spacing: 0.02em;
}
.hero-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #64748b;
}
.hero-meta b { color: #475569; font-weight: 600; }
.meta-dot { color: #cbd5e1; }
.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}
.stat-card {
  background: #f8fafc;
  border: 1px solid #e8edf3;
  border-radius: 10px;
  padding: 14px 16px;
  transition: box-shadow 0.2s;
}
.stat-card:hover { box-shadow: 0 2px 8px rgba(15, 23, 42, 0.05); }
.stat-primary {
  background: linear-gradient(135deg, #ecf5ff 0%, #f0f7ff 100%);
  border-color: #c6e2ff;
}
.stat-label {
  font-size: 12px;
  color: #909399;
  margin-bottom: 6px;
}
.stat-value {
  font-size: 22px;
  font-weight: 700;
  color: #303133;
  line-height: 1.2;
}
.stat-accent { color: #409eff; }
.stat-unit {
  font-size: 14px;
  font-weight: 500;
  color: #909399;
}
.progress-block { margin-top: 4px; }
.hero-alert { margin-top: 14px; }

.monitor-tabs {
  background: #fff;
  border-radius: 12px;
  padding: 4px 16px 16px;
  box-shadow: 0 1px 4px rgba(15, 23, 42, 0.06);
  border: 1px solid #e8edf3;
}
.monitor-tabs :deep(.el-tabs__header) {
  margin-bottom: 16px;
}
.monitor-tabs :deep(.el-tabs__item) {
  font-size: 14px;
  font-weight: 500;
  padding: 0 20px;
  height: 44px;
}

.chart-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 14px;
}
.chart-item {
  border: 1px solid #ebeef5;
  border-radius: 10px;
  padding: 12px;
  background: #fafbfc;
  transition: border-color 0.2s;
}
.chart-item:hover { border-color: #c6e2ff; }
.chart-title {
  font-size: 13px;
  font-weight: 600;
  color: #606266;
  margin-bottom: 8px;
}
.chart-img {
  width: 100%;
  border-radius: 6px;
  display: block;
}

.log-panels {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}
.log-panel {
  border: 1px solid #e8edf3;
  border-radius: 10px;
  overflow: hidden;
  background: #fff;
}
.panel-hd {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  background: #f8fafc;
  border-bottom: 1px solid #e8edf3;
}
.panel-title {
  font-size: 13px;
  font-weight: 600;
  color: #475569;
}
.log-box {
  border: none;
  border-radius: 0;
  padding: 10px 12px;
  background: #0f172a;
}
.log-pre {
  margin: 0;
  color: #cbd5e1;
  font-size: 12px;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: Consolas, 'Courier New', monospace;
}

.workflow-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 14px;
}
.workflow-card {
  border: 1px solid #e8edf3;
  border-radius: 12px;
  background: #fafbfc;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.workflow-card.wf-span {
  grid-column: 1 / -1;
}
.wf-hd {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 14px 16px;
  background: #fff;
  border-bottom: 1px solid #eef2f6;
}
.wf-step {
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: linear-gradient(135deg, #409eff, #337ecc);
  color: #fff;
  font-size: 13px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
}
.wf-title {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 2px;
}
.wf-desc {
  font-size: 12px;
  color: #909399;
}
.wf-body {
  padding: 14px 16px 16px;
  flex: 1;
}
.wf-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}
.wf-progress { margin-top: 12px; }
.wf-result { margin-top: 12px; }
.wf-placeholder {
  margin-top: 12px;
  padding: 24px;
  text-align: center;
  font-size: 13px;
  color: #c0c4cc;
  border: 1px dashed #dcdfe6;
  border-radius: 8px;
  background: #fff;
}
.wf-deploy .deploy-form { margin-bottom: 4px; }
.test-preview {
  margin-top: 12px;
  padding: 10px;
  background: #fff;
  border-radius: 8px;
  border: 1px solid #ebeef5;
}
.test-preview img {
  width: 100%;
  max-height: 220px;
  object-fit: contain;
  border-radius: 6px;
  background: #f5f7fa;
}
.test-preview p {
  font-size: 13px;
  color: #606266;
  margin: 8px 0 0;
  text-align: center;
}
.export-info {
  margin-top: 12px;
  padding: 10px 12px;
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 8px;
  background: #f0f9eb;
  border: 1px solid #e1f3d8;
  border-radius: 8px;
  color: #529b2e;
}

@media (max-width: 1200px) {
  .stat-grid { grid-template-columns: repeat(2, 1fr); }
  .log-panels { grid-template-columns: 1fr; }
  .workflow-grid { grid-template-columns: 1fr; }
  .chart-grid { grid-template-columns: 1fr; }
}

:deep(.monitor-drawer .el-drawer__body) {
  padding: 12px 20px 20px;
  background: #f0f2f5;
}
:deep(.monitor-drawer .el-drawer__header) {
  margin-bottom: 0;
  padding-bottom: 12px;
  border-bottom: 1px solid #e8edf3;
}

.mt12 { margin-top: 12px; }
.doc-links { margin-top: 16px; font-size: 13px; text-align: center; }
.doc-link-icon { vertical-align: -2px; margin-right: 4px; }
.annotate-sub-tabs :deep(.el-tabs__header) { margin-bottom: 12px; }
.workflow-alert { margin-bottom: 12px; }
.field-hint-inline { font-size: 12px; color: #909399; margin-left: 8px; }
.preview-desc { margin-bottom: 8px; }
.format-guide { margin-bottom: 12px; }
.guide-block { font-size: 13px; color: #606266; }
.guide-summary { margin: 0 0 10px; line-height: 1.6; }
.guide-section { margin-bottom: 10px; }
.guide-label { font-weight: 600; color: #303133; margin-bottom: 4px; }
.guide-tree {
  margin: 0; padding: 10px 12px; background: #f5f7fa; border-radius: 6px;
  font-size: 12px; line-height: 1.5; white-space: pre-wrap; font-family: Consolas, monospace;
}
.guide-desc { margin: 10px 0; }
.guide-notes { margin: 8px 0 0; padding-left: 18px; line-height: 1.8; color: #606266; }
.format-list { display: flex; flex-direction: column; gap: 14px; }
.format-card { margin-bottom: 0; }
.format-card-hd { display: flex; align-items: center; gap: 10px; }
.format-card-title { font-weight: 600; font-size: 15px; }
.row-actions {
  display: flex;
  flex-wrap: nowrap;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}
.row-actions :deep(.el-upload) {
  display: inline-flex;
  flex-shrink: 0;
}
.row-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}
:deep(.col-actions .cell) {
  white-space: nowrap;
}
</style>
