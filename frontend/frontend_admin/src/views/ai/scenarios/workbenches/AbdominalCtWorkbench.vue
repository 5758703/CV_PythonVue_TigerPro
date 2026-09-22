<template>
  <div class="radar-wb" aria-label="腹部 CT 诊断工作台">
    <section class="radar-wb__panel radar-wb__panel--infer">
      <header class="radar-wb__header">
        <strong>推理与 Findings</strong>
        <span>NIfTI / JPG / PNG · 阳性分数</span>
      </header>
      <RadarCtPanel
        :model-key="scenario.modelKey"
        :initial-threshold="Number(scenario.defaults?.threshold ?? 0.5)"
        @inferred="onInferred"
      />
    </section>
    <section class="radar-wb__panel radar-wb__panel--report">
      <header class="radar-wb__header">
        <strong>辅助报告</strong>
        <span>DeepSeek / 案例兜底</span>
      </header>
      <RadarReportPanel
        :findings="findings"
        :threshold="threshold"
        :image-name="imageName"
      />
    </section>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import RadarCtPanel from '../../components/radar/RadarCtPanel.vue'
import RadarReportPanel from '../../components/radar/RadarReportPanel.vue'

defineProps({ scenario: { type: Object, required: true } })
defineEmits(['completed'])

const findings = ref([])
const threshold = ref(0.5)
const imageName = ref('')

function onInferred(payload) {
  findings.value = payload?.findings || []
  threshold.value = Number(payload?.threshold ?? 0.5)
  imageName.value = payload?.meta?.filename || ''
}
</script>

<style scoped>
.radar-wb {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(0, 1fr);
  min-height: 550px;
  overflow: hidden;
  background: #101b25;
  border: 1px solid #101b25;
}

.radar-wb__panel {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 0 0 20px;
  color: var(--scenario-graphite, #18222d);
  background: #f8fafc;
}

.radar-wb__panel--infer {
  border-right: 1px solid #aebbc6;
}

.radar-wb__header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 20px;
  border-bottom: 1px solid #d8e0e7;
  background: #fff;
}

.radar-wb__header strong {
  font-size: 13px;
  color: var(--scenario-graphite, #18222d);
}

.radar-wb__header span {
  color: #8fa1b1;
  font: 10px/1.4 ui-monospace, SFMono-Regular, Consolas, monospace;
}

.radar-wb__panel :deep(.radar-ct-panel),
.radar-wb__panel :deep(.radar-report-panel) {
  padding: 0 20px;
}

@media (max-width: 1100px) {
  .radar-wb {
    grid-template-columns: 1fr;
  }

  .radar-wb__panel--infer {
    border-right: 0;
    border-bottom: 1px solid #aebbc6;
  }
}
</style>
