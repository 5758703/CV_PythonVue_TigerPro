<template>
  <section class="radar-report-panel" aria-label="辅助诊断报告">
    <div class="bar">
      <el-button
        type="primary"
        :loading="busy"
        :disabled="!canGenerate"
        @click="generate"
      >
        {{ busy ? '生成中…' : '生成辅助报告' }}
      </el-button>
      <span class="hint">基于 findings 阳性分数，调用 DeepSeek；不可用时案例库兜底</span>
    </div>
    <el-alert v-if="error" type="error" :closable="false" show-icon :title="error" class="mb" />

    <template v-if="report">
      <el-alert
        v-if="report.warning"
        type="warning"
        :closable="false"
        show-icon
        :title="report.warning"
        class="mb"
      />
      <el-descriptions :column="1" border size="small" class="mb">
        <el-descriptions-item label="摘要">{{ report.summary }}</el-descriptions-item>
        <el-descriptions-item label="风险">
          {{ report.risk?.level }} — {{ report.risk?.desc }}
        </el-descriptions-item>
        <el-descriptions-item label="结论">{{ report.conclusion }}</el-descriptions-item>
      </el-descriptions>

      <div class="report-block">
        <h4>Findings 解读</h4>
        <ul class="list">
          <li v-for="(item, i) in report.findings || []" :key="i">
            <strong>{{ item.className }}</strong>：{{ item.note }}
          </li>
        </ul>
      </div>

      <div class="report-block">
        <h4>建议</h4>
        <ul class="list">
          <li v-for="(item, i) in report.suggestions || []" :key="i">
            <strong>{{ item.title }}</strong> — {{ item.detail }}
          </li>
        </ul>
      </div>

      <p class="disclaimer">{{ report.disclaimer || '医学免责声明：AI 结果仅供辅助，需医生最终判读。' }}</p>
      <p class="meta">
        AI 可用：{{ report.meta?.aiAvailable ? '是' : '否' }}
        · {{ report.meta?.generatedAt }}
      </p>
    </template>
    <el-empty v-else description="先完成推理后再生成报告" :image-size="64" />
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { radarApi } from '../../../../api/radar'

const props = defineProps({
  findings: { type: Array, default: () => [] },
  threshold: { type: Number, default: 0.5 },
  imageName: { type: String, default: '' },
})

const busy = ref(false)
const error = ref('')
const report = ref(null)

const canGenerate = computed(() => !busy.value && Array.isArray(props.findings) && props.findings.length > 0)

watch(() => props.findings, () => {
  report.value = null
  error.value = ''
})

async function generate() {
  if (!canGenerate.value) return
  busy.value = true
  error.value = ''
  try {
    const res = await radarApi.report({
      findings: props.findings,
      threshold: props.threshold,
      imageName: props.imageName || undefined,
    })
    report.value = res.data || res
  } catch (e) {
    error.value = e?.response?.data?.message || e?.message || '报告生成失败'
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.radar-report-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
  color: var(--scenario-graphite, #18222d);
}

.bar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.hint {
  color: var(--scenario-muted, #647384);
  font-size: 12px;
  line-height: 1.5;
}

.mb { margin-bottom: 8px; }

.report-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 14px;
  border: 1px solid var(--scenario-line, #cdd8e1);
  border-radius: 2px;
  background: #fff;
}

h4 {
  margin: 0;
  font-size: 13px;
  font-weight: 800;
  color: var(--scenario-steel, #2166d1);
}

.list {
  margin: 0;
  padding-left: 18px;
  line-height: 1.7;
  color: var(--scenario-graphite, #18222d);
  font-size: 13px;
}

.list strong {
  color: var(--scenario-graphite, #18222d);
}

.disclaimer {
  margin: 0;
  padding: 10px 12px;
  color: #7a2430;
  background: #fff0f1;
  border-left: 3px solid var(--scenario-failure, #bf3038);
  font-size: 12px;
  line-height: 1.55;
}

.meta {
  margin: 0;
  color: var(--scenario-muted, #647384);
  font-size: 12px;
}

:deep(.el-descriptions) {
  --el-descriptions-item-bordered-label-background: #f3f6f9;
}

:deep(.el-empty__description p) {
  color: var(--scenario-muted, #647384);
}
</style>
