<template>
  <div class="convert-root">
    <el-card shadow="never" class="intro-card">
      <div class="intro-hd">
        <span class="intro-title">格式转换</span>
        <el-tooltip content="在数据集 raw 目录与 export 目录间进行格式互转" placement="top">
          <el-icon class="hint-icon"><QuestionFilled /></el-icon>
        </el-tooltip>
      </div>
      <div class="intro-desc">支持 LabelMe / Pascal VOC / YOLO / COCO 常见格式互转，转换结果写入当前数据集目录。</div>
    </el-card>

    <div class="type-grid">
      <div
        v-for="t in convertTypes"
        :key="t.value"
        class="type-card"
        :class="{ active: convertType === t.value }"
        @click="selectType(t.value)"
      >
        <div class="type-title">{{ t.label }}</div>
        <div class="type-summary">{{ t.summary }}</div>
      </div>
    </div>

    <el-card shadow="never" class="form-card">
      <el-form label-width="110px" label-position="left">
        <el-form-item label="数据集">
          <el-select v-model="datasetId" placeholder="选择数据集" style="width:320px">
            <el-option
              v-for="d in datasetOptions"
              :key="d.id"
              :label="`${d.name}（${d.format}）`"
              :value="d.id"
            />
          </el-select>
        </el-form-item>

        <el-form-item v-if="needsTarget" label="输出目录">
          <el-input v-model="targetSubdir" placeholder="留空写入 raw/；如 converted" style="width:320px" />
          <span class="field-hint">相对 datasets/&lt;id&gt;/ 的子目录</span>
        </el-form-item>

        <el-form-item v-if="convertType === 'yolo_to_voc' || convertType === 'yolo_to_coco'" label="导出路径">
          <el-input
            v-model="exportSubdir"
            :placeholder="exportPlaceholder"
            style="width:320px"
          />
        </el-form-item>

        <el-form-item v-if="needsClassMap" label="类别映射">
          <div class="map-list">
            <div v-for="(m, i) in classMap" :key="i" class="map-row">
              <el-input v-model="m.name" placeholder="类别名称" style="width:160px" />
              <span class="map-arrow">→ ID</span>
              <el-input-number v-model="m.id" :min="0" :max="999" controls-position="right" />
              <el-button type="danger" link :icon="Delete" @click="classMap.splice(i, 1)" />
            </div>
            <el-button size="small" :icon="Plus" @click="classMap.push({ name: '', id: 0 })">添加</el-button>
          </div>
          <div class="field-hint">将旧类别名称映射到新的 class_id（需与数据集 classNames 对应）</div>
        </el-form-item>

        <el-form-item v-if="selectedDataset?.classNames?.length" label="当前类别">
          <el-tag v-for="(c, i) in selectedDataset.classNames" :key="c" size="small" style="margin:2px">
            {{ i }}: {{ c }}
          </el-tag>
        </el-form-item>

        <el-form-item>
          <el-button
            type="primary"
            :icon="RefreshRight"
            :loading="converting"
            :disabled="!datasetId || !convertType"
            @click="runConvert"
          >
            开始转换
          </el-button>
        </el-form-item>
      </el-form>

      <el-alert v-if="lastResult" type="success" :closable="false" class="result-alert">
        <template #title>转换完成</template>
        <pre class="result-json">{{ JSON.stringify(lastResult, null, 2) }}</pre>
      </el-alert>
    </el-card>

    <el-card shadow="never" class="backend-card">
      <div class="backend-hd">
        <el-tag type="success" effect="dark" size="small">已连接</el-tag>
        <span>Flask 后端分析引擎</span>
      </div>
      <div class="backend-desc">
        质量分析与格式转换依赖本地 Python 后端（与训练服务共用），请确保 backend 已启动。
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { QuestionFilled, RefreshRight, Plus, Delete } from '@element-plus/icons-vue'
import { trainingApi } from '../../../api/ai'

const props = defineProps({
  initialDatasetId: { type: Number, default: null },
})

const datasetOptions = ref([])
const convertTypes = ref([])
const datasetId = ref(props.initialDatasetId)
const convertType = ref('labelme_to_yolo')
const targetSubdir = ref('')
const exportSubdir = ref('')
const classMap = ref([{ name: '', id: 0 }])
const converting = ref(false)
const lastResult = ref(null)

const selectedDataset = computed(() => datasetOptions.value.find((d) => d.id === datasetId.value) || null)
const currentTypeSpec = computed(() => convertTypes.value.find((t) => t.value === convertType.value) || {})
const needsTarget = computed(() => ['labelme_to_yolo', 'voc_to_yolo'].includes(convertType.value))
const needsClassMap = computed(() => convertType.value === 'yolo_remap')
const exportPlaceholder = computed(() =>
  convertType.value === 'yolo_to_coco' ? 'export/instances.json' : 'export/voc'
)

function selectType(v) {
  convertType.value = v
  lastResult.value = null
  if (v === 'yolo_to_coco') exportSubdir.value = 'export/instances.json'
  else if (v === 'yolo_to_voc') exportSubdir.value = 'export/voc'
}

async function loadMeta() {
  const [dsRes, typesRes] = await Promise.all([
    trainingApi.listDatasets({ pageNum: 1, pageSize: 100 }),
    trainingApi.convertTypes(),
  ])
  datasetOptions.value = resRows(dsRes)
  convertTypes.value = typesRes.data || []
  if (props.initialDatasetId && !datasetId.value) {
    datasetId.value = props.initialDatasetId
  }
}

function resRows(res) {
  return (res.data.rows || []).filter((d) => d.format !== 'import' || d.sourcePath)
}

async function runConvert() {
  if (!datasetId.value || !convertType.value) return
  const spec = currentTypeSpec.value
  if (spec.needsClassNames && !selectedDataset.value?.classNames?.length && convertType.value !== 'labelme_to_yolo') {
    ElMessage.warning('请先在数据集中配置类别名称')
    return
  }
  converting.value = true
  lastResult.value = null
  try {
    const payload = {
      type: convertType.value,
      targetSubdir: targetSubdir.value.trim() || undefined,
      exportSubdir: exportSubdir.value.trim() || undefined,
    }
    if (needsClassMap.value) {
      payload.classMap = classMap.value.filter((m) => m.name?.trim())
    }
    const res = await trainingApi.convertDataset(datasetId.value, payload)
    lastResult.value = res.data.result
    ElMessage.success(res.message || '转换完成')
  } catch {
    /* 拦截器已提示 */
  } finally {
    converting.value = false
  }
}

onMounted(loadMeta)

defineExpose({ setDatasetId: (id) => { datasetId.value = id } })
</script>

<style scoped>
.convert-root { min-height: 400px; }
.intro-card { margin-bottom: 12px; }
.intro-hd { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.intro-title { font-size: 16px; font-weight: 600; color: #3a4a63; }
.intro-desc { font-size: 13px; color: #909399; line-height: 1.6; }
.hint-icon { color: #909399; cursor: help; }
.type-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
  margin-bottom: 12px;
}
.type-card {
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  padding: 14px 16px;
  cursor: pointer;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.type-card:hover { border-color: #c6e2ff; box-shadow: 0 2px 8px rgba(64, 158, 255, 0.08); }
.type-card.active {
  border-color: #409eff;
  background: #ecf5ff;
  box-shadow: 0 0 0 1px #409eff inset;
}
.type-title { font-weight: 600; color: #303133; font-size: 14px; margin-bottom: 6px; }
.type-card.active .type-title { color: #409eff; }
.type-summary { font-size: 12px; color: #909399; line-height: 1.5; }
.form-card { margin-bottom: 12px; }
.field-hint { display: block; font-size: 12px; color: #909399; margin-left: 8px; margin-top: 4px; }
.map-list { display: flex; flex-direction: column; gap: 8px; width: 100%; }
.map-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.map-arrow { font-size: 13px; color: #909399; }
.result-alert { margin-top: 12px; }
.result-json {
  margin: 8px 0 0;
  font-size: 12px;
  font-family: Consolas, monospace;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 200px;
  overflow: auto;
}
.backend-card { background: #fafafa; }
.backend-hd { display: flex; align-items: center; gap: 8px; font-weight: 500; color: #303133; margin-bottom: 6px; }
.backend-desc { font-size: 12px; color: #909399; line-height: 1.6; }
</style>
