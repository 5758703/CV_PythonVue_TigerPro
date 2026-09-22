<template>
  <div class="radar-page">
    <el-card shadow="never" class="mb">
      <template #header>
        <div class="hdr">
          <strong>腹部 CT 诊断（RADAR）</strong>
          <el-tag size="small" type="info">alibaba-damo-academy/damo-radar</el-tag>
        </div>
      </template>
      <p class="intro">
        上传腹部增强 CT 的 NIfTI（.nii / .nii.gz）可走 damo-radar 真推理；JPG/PNG 切片可用于演示引擎。
        执行 <code>python scripts/setup_radar.py --download-weights</code> 并配置
        <code>RADAR_ENGINE=auto</code>（默认）后，权重就绪即自动切换真推理（需 GPU）。
      </p>
    </el-card>

    <el-row :gutter="16">
      <el-col :xs="24" :md="14">
        <el-card shadow="never">
          <RadarCtPanel @inferred="onInferred" />
        </el-card>
      </el-col>
      <el-col :xs="24" :md="10">
        <el-card shadow="never">
          <RadarReportPanel
            :findings="findings"
            :threshold="threshold"
            :image-name="imageName"
          />
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import RadarCtPanel from '../components/radar/RadarCtPanel.vue'
import RadarReportPanel from '../components/radar/RadarReportPanel.vue'

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
.radar-page { padding: 0 0 24px; }
.mb { margin-bottom: 12px; }
.hdr { display: flex; align-items: center; gap: 10px; }
.intro { margin: 0; color: #606266; line-height: 1.6; }
</style>
