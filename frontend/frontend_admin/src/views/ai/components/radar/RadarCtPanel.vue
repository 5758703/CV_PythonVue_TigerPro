<template>
  <section class="radar-ct-panel" aria-label="腹部 CT 推理">
    <el-alert
      v-if="status"
      :type="status.engine === 'mock' ? 'warning' : 'success'"
      :closable="false"
      show-icon
      class="mb"
      :title="statusBanner"
    />

    <div class="controls">
      <el-upload
        drag
        :auto-upload="false"
        :show-file-list="false"
        accept=".nii,.nii.gz,.jpg,.jpeg,.png,.bmp,.webp,image/*,application/gzip"
        :disabled="busy"
        @change="onPick"
      >
        <div class="upload-inner">
          <strong>{{ file ? file.name : '拖入或选择 CT 影像（NIfTI / JPG / PNG）' }}</strong>
          <span>真推理需 .nii/.nii.gz + GPU 权重；JPG/PNG 仅演示引擎。未就绪时自动 mock</span>
        </div>
      </el-upload>
      <el-button v-if="file" link type="danger" :disabled="busy" @click="clearFile">清除文件</el-button>

      <div class="row">
        <span>阳性阈值</span>
        <el-slider v-model="threshold" :min="0.05" :max="0.95" :step="0.05" style="width: 180px" :disabled="busy" />
        <output>{{ Number(threshold).toFixed(2) }}</output>
      </div>

      <div class="actions">
        <el-button type="primary" :loading="busy" :disabled="!canRun" @click="runInfer">
          {{ busy ? '推理中…' : (file ? '运行推理' : '运行演示推理') }}
        </el-button>
        <el-tag v-if="result" size="small" :type="result.engine === 'mock' ? 'warning' : 'success'">
          engine: {{ result.engine }}
        </el-tag>
        <span v-if="elapsedMs != null" class="meta">{{ elapsedMs }} ms</span>
      </div>
      <el-alert v-if="error" type="error" :closable="false" show-icon :title="error" class="mb" />
    </div>

    <div v-if="result" class="findings">
      <div class="metrics">
        <div><span>Findings</span><strong>{{ result.findings?.length || 0 }}</strong></div>
        <div><span>阳性</span><strong>{{ result.positiveCount ?? 0 }}</strong></div>
        <div><span>阈值</span><strong>{{ Number(result.threshold).toFixed(2) }}</strong></div>
      </div>
      <el-table :data="result.findings || []" size="small" max-height="360" stripe>
        <el-table-column type="index" width="50" />
        <el-table-column prop="name" label="Finding" min-width="180" />
        <el-table-column prop="score" label="分数" width="100">
          <template #default="{ row }">{{ Number(row.score).toFixed(4) }}</template>
        </el-table-column>
        <el-table-column prop="positive" label="阳性" width="80">
          <template #default="{ row }">
            <el-tag :type="row.positive ? 'danger' : 'info'" size="small">
              {{ row.positive ? '是' : '否' }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
      <p class="note">{{ result.meta?.disclaimer || disclaimer }}</p>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { radarApi } from '../../../../api/radar'
import { scenarioApi } from '../../../../api/modelScenarios'

const props = defineProps({
  /** When set, call scenario infer instead of /api/ai/radar/infer */
  modelKey: { type: String, default: '' },
  initialThreshold: { type: Number, default: 0.5 },
})

const emit = defineEmits(['inferred', 'status'])

const status = ref(null)
const file = ref(null)
const threshold = ref(Number(props.initialThreshold) || 0.5)
const busy = ref(false)
const error = ref('')
const result = ref(null)
const elapsedMs = ref(null)

const disclaimer = 'AI 结果仅供辅助，需医生最终判读。'
const statusBanner = computed(() => {
  if (!status.value) return '正在读取引擎状态…'
  if (status.value.disclaimer) return status.value.disclaimer
  if (status.value.engine === 'real') {
    return `damo-radar 真推理已就绪（device: ${status.value.device || 'auto'}）。`
  }
  if (status.value.vendorReady && !status.value.weightsReady) {
    return '官方代码已就绪，权重未完整。请执行 backend/scripts/setup_radar.py --download-weights'
  }
  if (!status.value.vendorReady) {
    return '演示引擎：请执行 setup_radar.py 安装 damo-radar 代码与权重以启用真推理。'
  }
  return '当前为演示引擎（权重未就绪时按上传内容给出确定性分数）。'
})
const canRun = computed(() => !busy.value)

watch(() => props.initialThreshold, (v) => {
  if (typeof v === 'number' && !Number.isNaN(v)) threshold.value = v
})

async function loadStatus() {
  try {
    const res = await radarApi.status()
    status.value = res.data || res
    if (typeof status.value?.threshold === 'number') {
      threshold.value = status.value.threshold
    }
    emit('status', status.value)
  } catch (e) {
    status.value = { engine: 'mock', disclaimer: disclaimer + ' 状态接口暂不可用。' }
  }
}

const ALLOWED_EXT = ['.nii', '.nii.gz', '.jpg', '.jpeg', '.png', '.bmp', '.webp']

function isAllowedRadarFile(name) {
  const lower = String(name || '').toLowerCase()
  return ALLOWED_EXT.some((ext) => lower.endsWith(ext))
}

function onPick(uploadFile) {
  if (busy.value) return
  const raw = uploadFile?.raw
  if (!raw) return
  const name = (raw.name || '').toLowerCase()
  if (!isAllowedRadarFile(name)) {
    error.value = '仅支持 .nii / .nii.gz，或 .jpg / .jpeg / .png / .bmp / .webp'
    return
  }
  file.value = raw
  error.value = ''
  result.value = null
}

function clearFile() {
  if (busy.value) return
  file.value = null
  result.value = null
}

async function runInfer() {
  if (!canRun.value) return
  busy.value = true
  error.value = ''
  result.value = null
  const started = performance.now()
  try {
    const fd = new FormData()
    if (file.value) fd.append('file', file.value)
    fd.append('threshold', String(threshold.value))
    let res
    if (props.modelKey) {
      res = await scenarioApi.infer(props.modelKey, fd)
    } else {
      res = await radarApi.infer(fd)
    }
    const data = res.data || res
    // scenario wrapper: { modelKey, workbench, result }
    const payload = data?.result && data?.modelKey ? data.result : data
    result.value = payload
    elapsedMs.value = Math.round(performance.now() - started)
    emit('inferred', payload)
  } catch (e) {
    error.value = e?.response?.data?.message || e?.message || '推理失败'
  } finally {
    busy.value = false
  }
}

onMounted(loadStatus)

defineExpose({ result, status, runInfer, loadStatus })
</script>

<style scoped>
.radar-ct-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
  color: var(--scenario-graphite, #18222d);
}

.mb { margin-bottom: 8px; }

.controls { display: flex; flex-direction: column; gap: 10px; }

.upload-inner {
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  color: var(--scenario-muted, #647384);
}

.upload-inner strong {
  color: var(--scenario-graphite, #18222d);
}

.row {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--scenario-muted, #647384);
  font-size: 13px;
  font-weight: 600;
}

.row output {
  color: var(--scenario-steel, #2166d1);
  font: 700 12px/1 ui-monospace, SFMono-Regular, Consolas, monospace;
}

.actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.meta {
  color: var(--scenario-muted, #647384);
  font-size: 12px;
}

.findings {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px;
  border: 1px solid var(--scenario-line, #cdd8e1);
  border-radius: 2px;
  background: #fff;
}

.metrics {
  display: flex;
  gap: 20px;
  margin-bottom: 4px;
}

.metrics span {
  display: block;
  color: var(--scenario-muted, #647384);
  font-size: 12px;
  font-weight: 600;
}

.metrics strong {
  font-size: 20px;
  line-height: 1.2;
  color: var(--scenario-graphite, #18222d);
}

.note {
  margin: 0;
  color: var(--scenario-muted, #647384);
  font-size: 12px;
  line-height: 1.5;
}

:deep(.el-upload-dragger) {
  background: #edf2f6;
  border-color: #9cabb8;
}

:deep(.el-table) {
  --el-table-text-color: var(--scenario-graphite, #18222d);
  --el-table-header-text-color: var(--scenario-muted, #647384);
}
</style>
