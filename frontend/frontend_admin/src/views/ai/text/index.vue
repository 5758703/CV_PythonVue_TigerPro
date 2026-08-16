<template>
  <div>
    <el-card shadow="never" class="cfg-card">
      <el-form :inline="true">
        <el-form-item label="模型分类">
          <el-select v-model="category" placeholder="全部分类" clearable style="width: 150px" @change="onCategoryChange">
            <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="文本模型">
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
        title="暂无可用文本模型：请到「模型管理」新增 transformers 文本分类模型（如 FinBERT）并拉取权重。"
      />
    </el-card>

    <el-card shadow="never">
      <el-input
        v-if="currentTask === 'zero-shot-classification'"
        v-model="labels"
        class="labels-input"
        placeholder="候选标签（逗号分隔），如：科技, 财经, 体育, 娱乐"
      />
      <el-input
        v-model="text"
        type="textarea"
        :rows="5"
        maxlength="2000"
        show-word-limit
        :placeholder="textPlaceholder"
      />
      <div class="bar">
        <el-button type="primary" :icon="MagicStick" :loading="analyzing" :disabled="!modelId || !text.trim()" @click="analyze">开始分析</el-button>
        <el-button :icon="Refresh" @click="clearAll">清空</el-button>
        <span class="meta">字符数：{{ text.length }}</span>
        <span class="samples">示例：
          <el-link type="primary" @click="useSample(0)">利好</el-link> /
          <el-link type="primary" @click="useSample(1)">利空</el-link> /
          <el-link type="primary" @click="useSample(2)">中性</el-link>
        </span>
      </div>

      <div v-if="analyzing" class="progress-box">
        <div class="progress-title">分析中… 预计剩余 {{ etaText }}</div>
        <el-progress :percentage="percent" :stroke-width="18" :text-inside="true" :status="percent >= 100 ? 'success' : ''" />
        <div class="progress-hint">已用 {{ elapsedText }}</div>
      </div>

      <div v-if="!analyzing && result" class="result">
        <el-alert
          :title="`判定：${labelText(result.top.label)}（${(result.top.score * 100).toFixed(1)}%）`"
          :type="alertType(result.top.label)"
          :closable="false"
        />
        <div class="scores">
          <div v-for="r in orderedResults" :key="r.label" class="score-row">
            <span class="score-label">{{ labelText(r.label) }}</span>
            <el-progress
              :percentage="+(r.score * 100).toFixed(1)"
              :color="labelColor(r.label)"
              :stroke-width="16"
              class="score-bar"
            />
          </div>
        </div>
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

const { running: analyzing, percent, etaText, elapsedText, start, finish } = useInferProgress(modelId)

const SAMPLES = [
  'The company reported record quarterly profits, beating analyst expectations.',
  'Shares plunged after the firm warned of mounting losses and possible bankruptcy.',
  'The central bank kept interest rates unchanged at its meeting today.'
]

const categories = computed(() => [...new Set(modelOptions.value.map((m) => m.category).filter(Boolean))])
const filteredModels = computed(() =>
  category.value ? modelOptions.value.filter((m) => m.category === category.value) : modelOptions.value
)
const onCategoryChange = () => {
  modelId.value = filteredModels.value[0]?.id || null
  result.value = null
}

const TEXT_TASKS = ['text-classification', 'zero-shot-classification', 'fill-mask']

const loadModels = async () => {
  const res = await modelApi.list({ pageNum: 1, pageSize: 100 })
  // 文本分类 / 零样本 / 完形填空（标签分数族），transformers、已启用、有权重
  modelOptions.value = (res.data.rows || []).filter(
    (m) => m.library === 'transformers' && TEXT_TASKS.includes(m.task) && m.filePath && m.status === '0'
  )
  if (modelOptions.value.length && !modelId.value) modelId.value = modelOptions.value[0].id
}

const currentTask = computed(() => modelOptions.value.find((m) => m.id === modelId.value)?.task || 'text-classification')
const textPlaceholder = computed(() => {
  if (currentTask.value === 'fill-mask') return '输入含 [MASK] 的句子，如：Paris is the [MASK] of France.'
  if (currentTask.value === 'zero-shot-classification') return '输入待分类文本…'
  return '输入待分析文本（如金融新闻、评论等）…'
})

// 固定显示顺序 + 中英双语标签
const LABEL_ORDER = ['positive', 'negative', 'neutral']
const LABEL_CN = {
  positive: '积极', negative: '消极', neutral: '中性',
  anger: '愤怒', joy: '喜悦', sadness: '悲伤', fear: '恐惧',
  surprise: '惊讶', love: '喜爱', disgust: '厌恶'
}
const labelText = (label) => {
  const l = String(label).toLowerCase()
  const en = label.charAt(0).toUpperCase() + label.slice(1).toLowerCase()
  return LABEL_CN[l] ? `${LABEL_CN[l]} ${en}` : label
}
const orderedResults = computed(() => {
  if (!result.value) return []
  const arr = [...result.value.results]
  // 情感模型(positive/negative/neutral)用固定顺序；其它(如 emotion 多类)按分数降序
  const isSentiment = arr.every((r) => LABEL_ORDER.includes(String(r.label).toLowerCase()))
  if (isSentiment) {
    return arr.sort((a, b) => LABEL_ORDER.indexOf(a.label.toLowerCase()) - LABEL_ORDER.indexOf(b.label.toLowerCase()))
  }
  return arr.sort((a, b) => b.score - a.score)
})

const labelColor = (label) => {
  const l = String(label).toLowerCase()
  if (l.includes('pos')) return '#67c23a'
  if (l.includes('neg')) return '#f56c6c'
  return '#909399'
}
const alertType = (label) => {
  const l = String(label).toLowerCase()
  if (l.includes('pos')) return 'success'
  if (l.includes('neg')) return 'error'
  return 'info'
}

const useSample = (i) => {
  text.value = SAMPLES[i]
}

const labels = ref('')  // 零样本候选标签（逗号分隔）

const analyze = async () => {
  start()
  try {
    let res
    if (currentTask.value === 'zero-shot-classification') {
      const arr = labels.value.split(/[,，]/).map((s) => s.trim()).filter(Boolean)
      res = await modelApi.zeroShot(modelId.value, text.value, arr)
    } else if (currentTask.value === 'fill-mask') {
      res = await modelApi.fillMask(modelId.value, text.value, 5)
    } else {
      res = await modelApi.analyzeText(modelId.value, text.value)
    }
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
.labels-input {
  margin-bottom: 10px;
}
.bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 12px 0;
}
.samples {
  font-size: 13px;
  color: #909399;
}
.meta {
  font-size: 13px;
  color: #5a6b87;
}
.progress-box {
  padding: 22px 4px;
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
.result {
  margin-top: 8px;
}
.scores {
  margin-top: 16px;
  max-width: 560px;
}
.score-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}
.score-label {
  width: 90px;
  text-align: right;
  color: #3a4a63;
  font-size: 13px;
}
.score-bar {
  flex: 1;
}
</style>
