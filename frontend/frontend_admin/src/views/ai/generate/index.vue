<template>
  <div>
    <el-card shadow="never" class="cfg-card">
      <el-form :inline="true">
        <el-form-item label="模型分类">
          <el-select v-model="category" placeholder="全部分类" clearable style="width: 150px" @change="onCategoryChange">
            <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="生成模型">
          <el-select v-model="modelId" placeholder="选择模型" style="width: 260px">
            <el-option
              v-for="m in filteredModels"
              :key="m.id"
              :label="`${m.modelName} · ${taskLabel(m.task)}`"
              :value="m.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item v-if="currentTask === 'text-generation'" label="最大长度">
          <el-input-number v-model="maxNewTokens" :min="16" :max="512" :step="16" />
        </el-form-item>
      </el-form>
      <el-alert
        v-if="!modelOptions.length"
        type="warning"
        :closable="false"
        title="暂无可用模型：请到「模型管理」新增 transformers 翻译/摘要/文本生成模型并拉取权重。"
      />
    </el-card>

    <el-card shadow="never">
      <div class="grid">
        <div class="col">
          <div class="col-title">输入文本</div>
          <el-input v-model="text" type="textarea" :rows="10" maxlength="5000" show-word-limit placeholder="输入原文…" />
        </div>
        <div class="col">
          <div class="col-title">
            生成结果
            <el-button v-if="output" link type="primary" :icon="CopyDocument" @click="copy">复制</el-button>
          </div>
          <div class="out-box">{{ output || '——' }}</div>
        </div>
      </div>
      <div class="bar">
        <el-button type="primary" :icon="MagicStick" :loading="running" :disabled="!modelId || !text.trim()" @click="run">开始生成</el-button>
        <el-button :icon="Refresh" @click="clearAll">清空</el-button>
        <span class="meta">字符数：{{ text.length }}</span>
      </div>

      <div v-if="running" class="progress-box">
        <div class="progress-title">生成中… 预计剩余 {{ etaText }}</div>
        <el-progress :percentage="percent" :stroke-width="18" :text-inside="true" :status="percent >= 100 ? 'success' : ''" />
        <div class="progress-hint">已用 {{ elapsedText }}</div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { MagicStick, Refresh, CopyDocument } from '@element-plus/icons-vue'

import { modelApi } from '../../../api/ai'
import { useInferProgress } from '../../../composables/useInferProgress'

const GEN_TASKS = ['translation', 'summarization', 'text-generation']
const TASK_CN = { translation: '翻译', summarization: '摘要', 'text-generation': '文本生成' }
const taskLabel = (t) => TASK_CN[t] || t

const modelOptions = ref([])
const modelId = ref(null)
const category = ref('')
const text = ref('')
const output = ref('')
const maxNewTokens = ref(256)

const { running, percent, etaText, elapsedText, start, finish } = useInferProgress(modelId)

const categories = computed(() => [...new Set(modelOptions.value.map((m) => m.category).filter(Boolean))])
const filteredModels = computed(() =>
  category.value ? modelOptions.value.filter((m) => m.category === category.value) : modelOptions.value
)
const currentTask = computed(() => modelOptions.value.find((m) => m.id === modelId.value)?.task || '')
const onCategoryChange = () => {
  modelId.value = filteredModels.value[0]?.id || null
  output.value = ''
}

const loadModels = async () => {
  const res = await modelApi.list({ pageNum: 1, pageSize: 100 })
  modelOptions.value = (res.data.rows || []).filter(
    (m) => m.library === 'transformers' && GEN_TASKS.includes(m.task) && m.filePath && m.status === '0'
  )
  if (modelOptions.value.length && !modelId.value) modelId.value = modelOptions.value[0].id
}

const run = async () => {
  start()
  try {
    const res = await modelApi.generateText(modelId.value, text.value, maxNewTokens.value)
    output.value = res.data.text
  } finally {
    finish()
  }
}

const copy = async () => {
  await navigator.clipboard.writeText(output.value)
  ElMessage.success('已复制')
}

const clearAll = () => {
  text.value = ''
  output.value = ''
}

onMounted(loadModels)
</script>

<style scoped>
.cfg-card {
  margin-bottom: 12px;
}
.grid {
  display: flex;
  gap: 16px;
}
.col {
  flex: 1 1 50%;
  min-width: 0;
}
.col-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 600;
  color: #3a4a63;
  margin-bottom: 8px;
}
.out-box {
  min-height: 232px;
  padding: 12px 14px;
  border-radius: 6px;
  background: #f4f6fb;
  border: 1px solid #e4e7ed;
  white-space: pre-wrap;
  line-height: 1.7;
  color: #1f2d3d;
}
.bar {
  margin-top: 14px;
  display: flex;
  align-items: center;
  gap: 12px;
}
.meta {
  font-size: 13px;
  color: #5a6b87;
}
.progress-box {
  margin-top: 16px;
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
</style>
