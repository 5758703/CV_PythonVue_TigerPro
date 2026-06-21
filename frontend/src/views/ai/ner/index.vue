<template>
  <div>
    <el-card shadow="never" class="cfg-card">
      <el-form :inline="true">
        <el-form-item label="模型分类">
          <el-select v-model="category" placeholder="全部分类" clearable style="width: 150px" @change="onCategoryChange">
            <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="NER 模型">
          <el-select v-model="modelId" placeholder="选择模型" style="width: 240px">
            <el-option
              v-for="m in filteredModels"
              :key="m.id"
              :label="`${m.modelName}（${m.category || '未分类'}）`"
              :value="m.id"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <el-alert
        v-if="!modelOptions.length"
        type="warning"
        :closable="false"
        title="暂无可用模型：请到「模型管理」新增 transformers 命名实体识别模型（如 bert-base-NER）并拉取权重。"
      />
    </el-card>

    <el-card shadow="never">
      <el-input v-model="text" type="textarea" :rows="4" maxlength="2000" show-word-limit placeholder="输入文本，如：Apple was founded by Steve Jobs in California." />
      <div class="bar">
        <el-button type="primary" :icon="MagicStick" :loading="running" :disabled="!modelId || !text.trim()" @click="run">开始识别</el-button>
        <el-button :icon="Refresh" @click="clearAll">清空</el-button>
        <span class="meta">字符数：{{ text.length }}</span>
      </div>

      <div v-if="running" class="progress-box">
        <div class="progress-title">识别中… 预计剩余 {{ etaText }}</div>
        <el-progress :percentage="percent" :stroke-width="18" :text-inside="true" :status="percent >= 100 ? 'success' : ''" />
        <div class="progress-hint">已用 {{ elapsedText }}</div>
      </div>

      <div v-if="!running && result">
        <div class="hl-title">标注结果</div>
        <div class="hl-box">
          <template v-for="(seg, i) in segments" :key="i">
            <span
              v-if="seg.group"
              class="ent"
              :style="{ background: groupColor(seg.group) }"
              :title="`${seg.group} ${(seg.score * 100).toFixed(0)}%`"
            >{{ seg.text }}<sub class="ent-tag">{{ seg.group }}</sub></span>
            <span v-else>{{ seg.text }}</span>
          </template>
        </div>

        <el-table :data="result.entities" size="small" border max-height="320" class="ent-table">
          <el-table-column type="index" label="#" width="48" />
          <el-table-column prop="word" label="实体" min-width="140" />
          <el-table-column label="类型" width="120">
            <template #default="{ row }">
              <el-tag size="small" :color="groupColor(row.entityGroup)" class="g-tag">{{ row.entityGroup }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="置信度" width="100">
            <template #default="{ row }">{{ (row.score * 100).toFixed(1) }}%</template>
          </el-table-column>
          <el-table-column label="位置" width="110">
            <template #default="{ row }">{{ row.start }} - {{ row.end }}</template>
          </el-table-column>
        </el-table>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { MagicStick, Refresh } from '@element-plus/icons-vue'

import { modelApi } from '../../../api/ai'
import { useInferProgress } from '../../../composables/useInferProgress'

const modelOptions = ref([])
const modelId = ref(null)
const category = ref('')
const text = ref('')
const result = ref(null)

const { running, percent, etaText, elapsedText, start, finish } = useInferProgress(modelId)

const PALETTE = ['#409eff', '#67c23a', '#e6a23c', '#9254de', '#13c2c2', '#f56c6c', '#eb2f96']
const groupColor = (g) => {
  let h = 0
  const s = String(g || '')
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0
  return PALETTE[h % PALETTE.length]
}

const categories = computed(() => [...new Set(modelOptions.value.map((m) => m.category).filter(Boolean))])
const filteredModels = computed(() =>
  category.value ? modelOptions.value.filter((m) => m.category === category.value) : modelOptions.value
)
const onCategoryChange = () => {
  modelId.value = filteredModels.value[0]?.id || null
  result.value = null
}

// 用实体 start/end 把原文切成「普通段 / 实体段」
const segments = computed(() => {
  if (!result.value) return []
  const src = result.value.text
  const ents = [...result.value.entities].sort((a, b) => a.start - b.start)
  const segs = []
  let cur = 0
  ents.forEach((e) => {
    if (e.start > cur) segs.push({ text: src.slice(cur, e.start) })
    segs.push({ text: src.slice(e.start, e.end), group: e.entityGroup, score: e.score })
    cur = e.end
  })
  if (cur < src.length) segs.push({ text: src.slice(cur) })
  return segs
})

const loadModels = async () => {
  const res = await modelApi.list({ pageNum: 1, pageSize: 100 })
  modelOptions.value = (res.data.rows || []).filter(
    (m) => m.library === 'transformers' && m.task === 'token-classification' && m.filePath && m.status === '0'
  )
  if (modelOptions.value.length && !modelId.value) modelId.value = modelOptions.value[0].id
}

const run = async () => {
  start()
  try {
    const res = await modelApi.extractEntities(modelId.value, text.value)
    result.value = res.data
  } finally {
    finish()
  }
}

const clearAll = () => {
  text.value = ''
  result.value = null
}

onMounted(loadModels)
</script>

<style scoped>
.cfg-card {
  margin-bottom: 12px;
}
.bar {
  margin: 12px 0;
  display: flex;
  align-items: center;
  gap: 12px;
}
.meta {
  font-size: 13px;
  color: #5a6b87;
}
.progress-box {
  margin: 12px 0;
}
.progress-title {
  font-weight: 600;
  color: #3a4a63;
  margin-bottom: 12px;
}
.progress-hint {
  margin-top: 10px;
  font-size: 12px;
  color: #909399;
}
.hl-title {
  font-weight: 600;
  color: #3a4a63;
  margin: 6px 0 8px;
}
.hl-box {
  padding: 14px 16px;
  border-radius: 8px;
  background: #f4f6fb;
  line-height: 2.2;
  font-size: 15px;
  color: #1f2d3d;
}
.ent {
  padding: 2px 4px;
  border-radius: 4px;
  color: #fff;
  margin: 0 1px;
}
.ent-tag {
  font-size: 10px;
  margin-left: 2px;
  vertical-align: sub;
  opacity: 0.9;
}
.ent-table {
  margin-top: 16px;
}
.g-tag {
  color: #fff;
  border: none;
}
</style>
