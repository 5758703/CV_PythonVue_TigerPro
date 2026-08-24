<template>
  <div class="defect-page">
    <el-card shadow="never" class="cfg-card">
      <el-form :inline="true">
        <el-form-item label="检测模型">
          <el-select v-model="detModelId" placeholder="YOLO 快筛" filterable style="width: 260px">
            <el-option
              v-for="m in detModels"
              :key="m.id"
              :label="modelLabel(m)"
              :value="m.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="分割模型">
          <el-select v-model="segModelId" clearable placeholder="可选·框引导掩码" filterable style="width: 240px">
            <el-option
              v-for="m in segModels"
              :key="m.id"
              :label="modelLabel(m)"
              :value="m.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="场景">
          <el-select v-model="scenario" style="width: 120px">
            <el-option label="通用" value="general" />
            <el-option label="PCB" value="pcb" />
            <el-option label="注塑" value="injection" />
          </el-select>
        </el-form-item>
        <el-form-item label="检测置信度">
          <el-slider v-model="conf" :min="0.05" :max="0.95" :step="0.05" style="width: 120px" />
        </el-form-item>
        <el-form-item label="诊断门控">
          <el-slider v-model="suspiciousConf" :min="0.1" :max="0.95" :step="0.05" style="width: 120px" />
        </el-form-item>
        <el-form-item>
          <el-upload :show-file-list="false" :auto-upload="false" :on-change="onPick" accept="image/*">
            <el-button :icon="UploadFilled">选择图片</el-button>
          </el-upload>
        </el-form-item>
        <el-form-item>
          <el-button
            type="primary"
            :icon="VideoPlay"
            :loading="running"
            :disabled="!detModelId || !file"
            @click="runDiagnose"
          >开始诊断</el-button>
          <el-button :icon="Refresh" @click="clearAll">清空</el-button>
        </el-form-item>
      </el-form>

      <el-alert
        :type="status?.qwenVlConfigured ? 'success' : 'warning'"
        :closable="false"
        show-icon
        class="mb"
        :title="statusTitle"
      />
      <el-alert
        type="info"
        :closable="false"
        show-icon
        class="mb"
        title="双引擎：YOLO 实时快筛可疑框 → MobileSAM/EfficientSAM 框引导像素掩码 → 云端 Qwen-VL 输出「是什么/为什么/怎么办」结构化报告。未配置 QWEN_VL_API_KEY 时自动规则降级。"
      />
    </el-card>

    <el-row :gutter="12">
      <el-col :span="14">
        <el-card shadow="never">
          <div class="media-pair">
            <div class="media-pane">
              <div class="pane-label">原图</div>
              <div v-if="sourceUrl" class="stage">
                <img :src="sourceUrl" class="media" alt="source" />
              </div>
              <el-empty v-else description="选择工业质检图片" :image-size="56" />
            </div>
            <div class="media-pane">
              <div class="pane-label">
                诊断叠加
                <span v-if="result" class="pane-meta">
                  检出 {{ result.detCount }} · 可疑 {{ result.suspiciousCount }}
                </span>
              </div>
              <div v-if="resultUrl" class="stage">
                <img :src="resultUrl" class="media" alt="result" />
              </div>
              <el-empty v-else description="开始诊断后显示框与掩码" :image-size="56" />
            </div>
          </div>
          <div v-if="result?.engines" class="engine-tags">
            <el-tag size="small" effect="plain">检测 {{ result.engines.detector }}</el-tag>
            <el-tag size="small" effect="plain">分割 {{ result.engines.segmentation }}</el-tag>
            <el-tag
              size="small"
              :type="result.engines.diagnosis === 'qwen_vl' ? 'success' : 'warning'"
              effect="dark"
            >诊断 {{ result.engines.diagnosis }}</el-tag>
            <el-tag v-if="result.engines.qwenVlModel" size="small" type="info">{{ result.engines.qwenVlModel }}</el-tag>
          </div>
        </el-card>
      </el-col>
      <el-col :span="10">
        <el-card shadow="never">
          <div class="res-title">结构化诊断报告</div>
          <el-empty v-if="!(diagnoses || []).length" description="暂无可疑 ROI 诊断" :image-size="60" />
          <div v-for="(d, i) in diagnoses" :key="i" class="diag-card">
            <div class="diag-h">
              <el-tag :type="severityType(d.severity)" effect="dark" size="small">{{ d.severity || 'medium' }}</el-tag>
              <span class="diag-type">{{ d.defectType }}</span>
              <el-tag size="small" :type="d.engine === 'qwen_vl' ? 'success' : 'info'" effect="plain">{{ d.engine }}</el-tag>
            </div>
            <div class="diag-row"><b>位置</b>{{ d.locationDesc }}</div>
            <div class="diag-row"><b>成因</b>{{ d.rootCause }}</div>
            <div class="diag-row"><b>置信</b>{{ formatScore(d.confidence) }} · 检测类 {{ d.className || '-' }}</div>
            <div class="diag-advice">
              <div class="adv-title">工艺建议</div>
              <ul>
                <li v-for="(a, j) in (d.processAdvice || [])" :key="j">{{ a }}</li>
              </ul>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, UploadFilled, VideoPlay } from '@element-plus/icons-vue'
import { defectApi, modelApi } from '../../../api/ai'

const detModels = ref([])
const segModels = ref([])
const detModelId = ref(null)
const segModelId = ref(null)
const scenario = ref('general')
const conf = ref(0.25)
const suspiciousConf = ref(0.45)
const file = ref(null)
const sourceUrl = ref('')
const resultUrl = ref('')
const result = ref(null)
const running = ref(false)
const status = ref(null)

const diagnoses = computed(() => result.value?.diagnoses || [])

const statusTitle = computed(() => {
  const s = status.value
  if (!s) return '正在读取引擎状态…'
  if (s.qwenVlConfigured) {
    return `云端诊断已就绪：${s.qwenVlModel}（${s.qwenVlBaseUrl}）`
  }
  return '未配置 QWEN_VL_API_KEY / DASHSCOPE_API_KEY：将使用规则降级报告（检测与分割仍可用）'
})

const modelLabel = (m) => `${m.modelName || m.model_key}（${m.category || m.library || '-'}）`

const formatScore = (v) => {
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return n.toFixed(2)
}

const severityType = (s) => {
  const k = String(s || '').toLowerCase()
  if (k === 'critical' || k === 'high') return 'danger'
  if (k === 'medium') return 'warning'
  return 'info'
}

const loadModels = async () => {
  const [det, segA, segB] = await Promise.all([
    modelApi.options({ task: 'object-detection' }),
    modelApi.options({ task: 'interactive-segmentation' }),
    modelApi.options({ task: 'instance-segmentation' }),
  ])
  const asList = (res) => {
    const d = res?.data
    if (Array.isArray(d)) return d
    if (Array.isArray(d?.rows)) return d.rows
    return []
  }
  detModels.value = asList(det)
  const seen = new Set()
  segModels.value = [...asList(segA), ...asList(segB)].filter((m) => {
    if (seen.has(m.id)) return false
    seen.add(m.id)
    return true
  })
  if (!detModelId.value && detModels.value.length) {
    detModelId.value = detModels.value[0].id
  }
}

const loadStatus = async () => {
  try {
    const res = await defectApi.status()
    status.value = res.data || null
    if (status.value?.suspiciousConfDefault != null) {
      suspiciousConf.value = Number(status.value.suspiciousConfDefault) || 0.45
    }
  } catch {
    status.value = { qwenVlConfigured: false }
  }
}

const onPick = (uploadFile) => {
  file.value = uploadFile.raw
  if (sourceUrl.value) URL.revokeObjectURL(sourceUrl.value)
  sourceUrl.value = URL.createObjectURL(uploadFile.raw)
  result.value = null
  resultUrl.value = ''
}

const clearAll = () => {
  file.value = null
  if (sourceUrl.value) URL.revokeObjectURL(sourceUrl.value)
  sourceUrl.value = ''
  resultUrl.value = ''
  result.value = null
}

const runDiagnose = async () => {
  if (!file.value || !detModelId.value) return
  running.value = true
  try {
    const fd = new FormData()
    fd.append('file', file.value)
    fd.append('modelId', String(detModelId.value))
    if (segModelId.value) fd.append('segModelId', String(segModelId.value))
    fd.append('conf', String(conf.value))
    fd.append('suspiciousConf', String(suspiciousConf.value))
    fd.append('scenario', scenario.value)
    fd.append('draw', '1')
    const res = await defectApi.diagnose(fd)
    result.value = res.data
    if (res.data?.imageBase64) {
      resultUrl.value = `data:image/jpeg;base64,${res.data.imageBase64}`
    } else {
      resultUrl.value = ''
    }
    const n = res.data?.suspiciousCount ?? 0
    ElMessage.success(n ? `诊断完成：${n} 个可疑区域` : '检测完成：无达到门控的可疑区域')
  } catch (e) {
    ElMessage.error(e?.response?.data?.message || e?.message || '诊断失败')
  } finally {
    running.value = false
  }
}

onMounted(async () => {
  await Promise.all([loadModels(), loadStatus()])
})
</script>

<style scoped>
.defect-page { padding: 4px; }
.cfg-card { margin-bottom: 12px; }
.mb { margin-bottom: 8px; }
.media-pair {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
.media-pane { min-width: 0; }
.pane-label {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 6px;
  display: flex;
  justify-content: space-between;
  gap: 8px;
}
.pane-meta { font-weight: 400; color: #909399; font-size: 12px; }
.stage {
  background: #0b1220;
  border-radius: 6px;
  border: 1px solid #1e2a44;
  min-height: 220px;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}
.media { max-width: 100%; max-height: 420px; display: block; object-fit: contain; }
.engine-tags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.res-title { font-weight: 700; margin-bottom: 10px; }
.diag-card {
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 10px;
  background: #fafbfd;
}
.diag-h {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.diag-type { font-weight: 700; flex: 1; min-width: 0; }
.diag-row {
  font-size: 13px;
  line-height: 1.55;
  color: #606266;
  margin-bottom: 4px;
}
.diag-row b {
  color: #303133;
  margin-right: 6px;
}
.diag-advice { margin-top: 6px; }
.adv-title { font-size: 12px; color: #909399; margin-bottom: 2px; }
.diag-advice ul {
  margin: 0;
  padding-left: 18px;
  font-size: 13px;
  color: #606266;
}
@media (max-width: 960px) {
  .media-pair { grid-template-columns: 1fr; }
}
</style>
