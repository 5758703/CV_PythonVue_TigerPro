<template>
  <aside class="wb-results" aria-labelledby="workbench-result-title">
    <header class="wb-results__header">
      <div>
        <span class="wb-results__eyebrow">{{ eyebrow }}</span>
        <h3 id="workbench-result-title">{{ title }}</h3>
      </div>
      <span v-if="elapsedMs !== null" class="wb-results__latency">{{ elapsedMs }} ms</span>
    </header>

    <div v-if="busy" class="wb-result-state" aria-live="polite">
      <span class="scenario-loader" aria-hidden="true"></span>
      <strong>推理执行中</strong>
      <p>输入与参数已锁定，请等待真实推理响应。</p>
    </div>

    <div v-else-if="error" class="wb-result-state wb-result-state--error" role="alert">
      <span class="scenario-state__code">INFERENCE FAILED</span>
      <strong>本次推理未完成</strong>
      <p>{{ error }}</p>
      <small>输入与参数已保留，可直接重试。</small>
    </div>

    <div v-else-if="!result" class="wb-result-state">
      <span class="scenario-state__code">NO RESULT</span>
      <strong>{{ emptyTitle }}</strong>
      <p>{{ emptyText }}</p>
    </div>

    <template v-else>
      <slot :result="result"></slot>

      <div class="wb-results__actions">
        <button class="scenario-button scenario-button--ghost" type="button" @click="copyResult">
          {{ copied ? 'JSON 已复制' : '复制 JSON' }}
        </button>
        <button class="scenario-button scenario-button--ghost" type="button" @click="downloadResult">
          下载 JSON
        </button>
        <button
          v-if="imageUrl"
          class="scenario-button scenario-button--ghost"
          type="button"
          @click="downloadImage"
        >
          下载结果图
        </button>
      </div>

      <details class="wb-json">
        <summary>查看原始响应</summary>
        <pre tabindex="0"><code>{{ formattedResult }}</code></pre>
      </details>
    </template>
  </aside>
</template>

<script setup>
import { computed, ref } from 'vue'

import { downloadJson } from '../scenarioState'

const props = defineProps({
  title: { type: String, default: '结构化结果' },
  eyebrow: { type: String, default: 'REAL INFERENCE OUTPUT' },
  result: { type: Object, default: null },
  busy: { type: Boolean, default: false },
  error: { type: String, default: '' },
  elapsedMs: { type: Number, default: null },
  imageUrl: { type: String, default: '' },
  filename: { type: String, default: 'scenario-result' },
  emptyTitle: { type: String, default: '等待推理结果' },
  emptyText: { type: String, default: '完成输入并运行后，这里显示后端返回的真实结果。' },
})

const copied = ref(false)
const formattedResult = computed(() => JSON.stringify(props.result, null, 2))

async function copyResult() {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(formattedResult.value)
    } else {
      const textarea = document.createElement('textarea')
      textarea.value = formattedResult.value
      textarea.setAttribute('readonly', '')
      textarea.style.position = 'fixed'
      textarea.style.opacity = '0'
      document.body.appendChild(textarea)
      textarea.select()
      document.execCommand('copy')
      textarea.remove()
    }
    copied.value = true
    window.setTimeout(() => { copied.value = false }, 1600)
  } catch {
    copied.value = false
  }
}

function downloadResult() {
  downloadJson(props.filename, props.result)
}

function downloadImage() {
  const link = document.createElement('a')
  link.href = props.imageUrl
  link.download = `${props.filename}.jpg`
  link.click()
}
</script>
