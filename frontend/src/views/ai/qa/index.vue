<template>
  <div>
    <el-card shadow="never" class="cfg-card">
      <el-form :inline="true">
        <el-form-item label="模型分类">
          <el-select v-model="category" placeholder="全部分类" clearable style="width: 150px" @change="onCategoryChange">
            <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="问答模型">
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
        title="暂无可用模型：请到「模型管理」新增 transformers 抽取式问答模型（如 distilbert-squad）并拉取权重。"
      />
    </el-card>

    <el-card shadow="never">
      <div class="field-label">上下文（Context）</div>
      <el-input v-model="context" type="textarea" :rows="6" maxlength="5000" show-word-limit placeholder="粘贴一段文字作为知识背景…" />
      <div class="field-label mt">问题（Question）</div>
      <el-input v-model="question" placeholder="基于上下文提出问题…" @keyup.enter="run" />
      <div class="bar">
        <el-button type="primary" :icon="MagicStick" :loading="running" :disabled="!modelId || !context.trim() || !question.trim()" @click="run">获取答案</el-button>
        <el-button :icon="Refresh" @click="clearAll">清空</el-button>
        <span class="meta">上下文 {{ context.length }} 字 · 问题 {{ question.length }} 字</span>
      </div>

      <div v-if="running" class="progress-box">
        <div class="progress-title">问答中… 预计剩余 {{ etaText }}</div>
        <el-progress :percentage="percent" :stroke-width="18" :text-inside="true" :status="percent >= 100 ? 'success' : ''" />
        <div class="progress-hint">已用 {{ elapsedText }}</div>
      </div>

      <div v-if="!running && result" class="answer-area">
        <el-alert :title="`答案：${result.answer}（置信度 ${(result.score * 100).toFixed(1)}%）`" type="success" :closable="false" />
        <div class="ctx-title">答案出处</div>
        <div class="ctx-box">
          <template v-for="(seg, i) in segments" :key="i">
            <span v-if="seg.hit" class="ans-hl">{{ seg.text }}</span>
            <span v-else>{{ seg.text }}</span>
          </template>
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
const context = ref('')
const question = ref('')
const result = ref(null)

const { running, percent, etaText, elapsedText, start, finish } = useInferProgress(modelId)

const categories = computed(() => [...new Set(modelOptions.value.map((m) => m.category).filter(Boolean))])
const filteredModels = computed(() =>
  category.value ? modelOptions.value.filter((m) => m.category === category.value) : modelOptions.value
)
const onCategoryChange = () => {
  modelId.value = filteredModels.value[0]?.id || null
  result.value = null
}

// 用 start/end 把上下文切成 普通段 / 答案段
const segments = computed(() => {
  if (!result.value) return []
  const src = context.value
  const { start, end } = result.value
  if (start == null || end == null || end <= start) return [{ text: src }]
  return [
    { text: src.slice(0, start) },
    { text: src.slice(start, end), hit: true },
    { text: src.slice(end) }
  ]
})

const loadModels = async () => {
  const res = await modelApi.list({ pageNum: 1, pageSize: 100 })
  modelOptions.value = (res.data.rows || []).filter(
    (m) => m.library === 'transformers' && m.task === 'question-answering' && m.filePath && m.status === '0'
  )
  if (modelOptions.value.length && !modelId.value) modelId.value = modelOptions.value[0].id
}

const run = async () => {
  start()
  try {
    const res = await modelApi.answerQuestion(modelId.value, question.value, context.value)
    result.value = res.data
  } finally {
    finish()
  }
}

const clearAll = () => {
  context.value = ''
  question.value = ''
  result.value = null
}

onMounted(loadModels)
</script>

<style scoped>
.cfg-card {
  margin-bottom: 12px;
}
.field-label {
  font-weight: 600;
  color: #3a4a63;
  margin-bottom: 8px;
}
.field-label.mt {
  margin-top: 14px;
}
.bar {
  margin: 14px 0;
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
.answer-area {
  margin-top: 8px;
}
.ctx-title {
  font-weight: 600;
  color: #3a4a63;
  margin: 14px 0 8px;
}
.ctx-box {
  padding: 14px 16px;
  border-radius: 8px;
  background: #f4f6fb;
  line-height: 2;
  color: #1f2d3d;
}
.ans-hl {
  background: #ffe08a;
  padding: 2px 4px;
  border-radius: 4px;
  font-weight: 600;
}
</style>
