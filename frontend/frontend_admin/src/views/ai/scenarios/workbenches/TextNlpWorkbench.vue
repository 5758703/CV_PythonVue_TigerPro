<template>
  <div class="wb-grid">
    <section class="wb-controls" aria-label="文本 NLP 输入与参数">
      <div class="wb-control-group">
        <div class="wb-control-heading"><h3>{{ abilityTitle }}</h3><button class="wb-text-button" type="button" :disabled="busy" @click="resetParameters">恢复默认</button></div>
        <template v-if="isQa">
          <label class="wb-field">
            <span>问题</span>
            <textarea v-model="question" rows="2" maxlength="2000" placeholder="输入问题" :disabled="busy"></textarea>
          </label>
          <label class="wb-field">
            <span>上下文</span>
            <textarea v-model="context" rows="8" maxlength="20000" placeholder="输入上下文段落" :disabled="busy"></textarea>
          </label>
        </template>
        <template v-else>
          <label class="wb-field">
            <span>文本</span>
            <textarea v-model="text" rows="8" maxlength="20000" :placeholder="textPlaceholder" :disabled="busy"></textarea>
          </label>
          <label v-if="isZeroShot" class="wb-field">
            <span>候选标签（逗号分隔）</span>
            <input v-model="labels" type="text" placeholder="positive,negative,neutral" :disabled="busy">
          </label>
          <label v-if="isFillMask" class="wb-field">
            <span>Top-K <output>{{ topK }}</output></span>
            <input v-model.number="topK" type="range" min="1" max="20" step="1" :disabled="busy">
          </label>
        </template>
      </div>

      <aside class="wb-capability-note">
        <strong>文本推理</strong>
        <p>结果依赖权重与分词器本地可用性；生产接入前请用业务语料标定阈值。</p>
      </aside>

      <div v-if="validationMessage" class="wb-form-error" role="alert">{{ validationMessage }}</div>
      <button class="scenario-button wb-run" type="button" :disabled="!canRun" @click="runInference">
        {{ busy ? '正在推理…' : '运行真实文本推理' }}
      </button>
    </section>

    <section class="wb-canvas" aria-label="文本预览">
      <header class="wb-canvas__header">
        <div><strong>输入预览</strong><span>{{ ability }}</span></div>
      </header>
      <div class="wb-canvas-empty">
        <span aria-hidden="true">¶</span>
        <strong>{{ abilityTitle }}</strong>
        <p>{{ previewSnippet || '填写输入后运行，结构化结果在右侧面板展示。' }}</p>
      </div>
    </section>

    <ResultPanel
      title="文本 NLP 输出"
      :result="runOutput"
      :busy="busy"
      :error="error"
      :elapsed-ms="elapsedMs"
      :filename="`${scenario.modelKey}-text`"
    >
      <div v-if="runOutput" class="wb-result-content">
        <p class="wb-result-note">完整字段见下方 JSON；页面不做二次业务判定。</p>
      </div>
      <div v-else class="wb-normal-empty">
        <strong>等待文本结果</strong>
        <p>提交后返回实体、标签、摘要或答案等结构化字段。</p>
      </div>
    </ResultPanel>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'

import { scenarioApi } from '../../../../api/modelScenarios'
import ResultPanel from '../components/ResultPanel.vue'
import {
  createAsyncRequestGuard,
  normalizeWorkbenchResult,
  serializeScenarioForm,
  validateWorkbenchState,
} from '../scenarioState'

const props = defineProps({ scenario: { type: Object, required: true } })
const emit = defineEmits(['completed'])
const requestGuard = createAsyncRequestGuard()

const ability = computed(() => String(props.scenario.ability || ''))
const isQa = computed(() => ability.value === 'question-answering')
const isZeroShot = computed(() => ability.value === 'zero-shot-classification')
const isFillMask = computed(() => ability.value === 'fill-mask')

const ABILITY_TITLES = {
  'token-classification': '命名实体识别',
  'text-classification': '文本分类',
  'zero-shot-classification': '零样本文本分类',
  'fill-mask': '完形填空',
  summarization: '文本摘要',
  translation: '机器翻译',
  'question-answering': '抽取式问答',
}

const abilityTitle = computed(() => ABILITY_TITLES[ability.value] || '文本 NLP')
const textPlaceholder = computed(() => (
  isFillMask.value ? '请输入含 [MASK] 的句子' : '请输入待处理文本'
))

const text = ref('')
const labels = ref(String(props.scenario.defaults?.labels ?? 'positive,negative'))
const question = ref('')
const context = ref('')
const topK = ref(Number(props.scenario.defaults?.topK ?? 5))
const busy = ref(false)
const error = ref('')
const runOutput = ref(null)
const elapsedMs = ref(null)

const formState = computed(() => ({
  ability: ability.value,
  text: text.value,
  labels: labels.value,
  question: question.value,
  context: context.value,
  topK: topK.value,
}))
const validationErrors = computed(() => validateWorkbenchState('text_nlp', formState.value))
const validationMessage = computed(() => {
  const touched = isQa.value
    ? Boolean(question.value || context.value)
    : Boolean(text.value || (isZeroShot.value && labels.value))
  return touched ? (validationErrors.value[0] || '') : ''
})
const canRun = computed(() => (props.scenario.apiReady ?? props.scenario.ready) && !busy.value && validationErrors.value.length === 0)
const previewSnippet = computed(() => {
  if (isQa.value) return question.value || context.value
  return text.value
})

function resetParameters() {
  if (busy.value) return
  labels.value = String(props.scenario.defaults?.labels ?? 'positive,negative')
  topK.value = Number(props.scenario.defaults?.topK ?? 5)
}

async function runInference() {
  if (!canRun.value) return
  const requestToken = requestGuard.begin()
  busy.value = true
  error.value = ''
  runOutput.value = null
  elapsedMs.value = null
  try {
    const form = serializeScenarioForm('text_nlp', formState.value)
    const response = await scenarioApi.infer(props.scenario.modelKey, form)
    if (!requestGuard.isCurrent(requestToken)) return
    runOutput.value = {
      ...response.data,
      result: normalizeWorkbenchResult('text_nlp', response.data?.result),
    }
    elapsedMs.value = Number.isFinite(response.data?.elapsedMs) ? response.data.elapsedMs : null
    emit('completed', response.data)
  } catch (requestError) {
    if (requestGuard.isCurrent(requestToken)) {
      error.value = requestError?.response?.data?.message || requestError?.message || '文本推理失败，请检查输入与运行环境。'
    }
  } finally {
    if (requestGuard.isCurrent(requestToken)) busy.value = false
  }
}
</script>
