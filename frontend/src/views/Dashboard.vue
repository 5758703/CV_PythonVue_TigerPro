<template>
  <div class="home">
    <!-- 平台介绍 -->
    <div class="hero">
      <div class="hero-badge">CV</div>
      <div class="hero-body">
        <h1 class="hero-title">Tiger AI Platform</h1>
        <p class="hero-sub">多任务 / 多模态 AI 模型管理与测试学习平台 —— 视觉 · 文本 · 语音 · 多模态 全栈纳管</p>
        <p class="hero-desc">一站式管理与在线测试多种 AI 模型：从 <b>HuggingFace / ModelScope（模搭社区）双下载源</b>拉取权重、统一纳管、按任务在对应页面即点即测。 平台现支持 <b>14 类 AI 任务</b>，跨 <b>视觉 / 文本 / 语音 / 多模态</b> 四大方向， 推理引擎涵盖 <b>YOLO · ByteTrack · transformers · funasr · onnx 量化 · CosyVoice · VibeVoice · VoxCPM</b>，纯 <b>CPU</b> 即可运行 —— 覆盖目标检测、图像分类、目标追踪、姿态估计、文本分类、零样本分类、完形填空、翻译 / 摘要 / 生成、实体识别、智能问答、语音识别、语音合成、数字人合成。 视觉任务支持<b>图片 / 视频 / 摄像头实时</b>三种输入，追踪与姿态可<b>摄像头实时处理、越线计数并录制下载</b>；图片检测可调 <b>DeepSeek AI</b> 生成正式检测报告。</p>
        <div class="hero-tags">
          <el-tag effect="dark" color="#409eff" class="htag">目标检测</el-tag>
          <el-tag effect="dark" color="#67c23a" class="htag">图像分类</el-tag>
          <el-tag effect="dark" color="#1f6feb" class="htag">目标追踪 · 越线计数</el-tag>
          <el-tag effect="dark" color="#00b894" class="htag">姿态估计</el-tag>
          <el-tag effect="dark" color="#d63384" class="htag">摄像头实时 · 录制</el-tag>
          <el-tag effect="dark" color="#b23b3b" class="htag">DeepSeek 检测报告</el-tag>
          <el-tag effect="dark" color="#e6a23c" class="htag">文本分类</el-tag>
          <el-tag effect="dark" color="#2f54eb" class="htag">零样本分类</el-tag>
          <el-tag effect="dark" color="#13c2c2" class="htag">完形填空</el-tag>
          <el-tag effect="dark" color="#eb2f96" class="htag">翻译 / 摘要 / 生成</el-tag>
          <el-tag effect="dark" color="#9254de" class="htag">实体识别 NER</el-tag>
          <el-tag effect="dark" color="#fa8c16" class="htag">智能问答 QA</el-tag>
          <el-tag effect="dark" color="#f5222d" class="htag">语音识别 ASR</el-tag>
          <el-tag effect="dark" color="#08979c" class="htag">语音合成 TTS</el-tag>
          <el-tag effect="dark" color="#c41d7f" class="htag">数字人合成</el-tag>
          <el-tag effect="dark" color="#722ed1" class="htag">模型全生命周期管理</el-tag>
          <el-tag effect="dark" color="#52c41a" class="htag">RBAC 权限</el-tag>
        </div>
      </div>
    </div>

    <!-- 统计卡片 -->
    <div class="stat-row">
      <div v-for="s in stats" :key="s.label" class="stat-card" :style="{ '--accent': s.color }">
        <div class="stat-icon">
          <el-icon><component :is="s.icon" /></el-icon>
        </div>
        <div class="stat-meta">
          <div class="stat-value">{{ s.value }}</div>
          <div class="stat-label">{{ s.label }}</div>
        </div>
      </div>
    </div>

    <!-- 图表 -->
    <el-row :gutter="16" class="chart-row">
      <el-col :span="10">
        <el-card shadow="hover">
          <template #header>模型任务类型分布</template>
          <div ref="pieRef" class="chart"></div>
        </el-card>
      </el-col>
      <el-col :span="14">
        <el-card shadow="hover">
          <template #header>模型分类统计</template>
          <div ref="barRef" class="chart"></div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, onBeforeUnmount, nextTick } from "vue";
import * as echarts from "echarts";

import { modelApi } from "../api/ai";

const TASK_LABELS = {
  "object-detection": "目标检测",
  "pose-estimation": "姿态估计",
  "image-classification": "图像分类",
  "ocr": "文字识别",
  "text-classification": "文本分类",
  "zero-shot-classification": "零样本分类",
  "fill-mask": "完形填空",
  translation: "翻译",
  summarization: "摘要",
  "text-generation": "文本生成",
  "token-classification": "实体识别",
  "question-answering": "问答",
  "automatic-speech-recognition": "语音识别",
  "text-to-speech": "语音合成",
  "talking-head": "数字人",
};
const taskLabel = (t) => TASK_LABELS[t] || t || "其他";

const stats = reactive([
  { label: "模型总数", value: 0, icon: "Files", color: "#409eff" },
  { label: "已就绪（有权重）", value: 0, icon: "CircleCheck", color: "#67c23a" },
  { label: "任务种类", value: 0, icon: "Cpu", color: "#e6a23c" },
  { label: "模型分类数", value: 0, icon: "Collection", color: "#9254de" },
]);

const pieRef = ref();
const barRef = ref();
let pieChart = null;
let barChart = null;

const resize = () => {
  pieChart && pieChart.resize();
  barChart && barChart.resize();
};

const renderCharts = (rows) => {
  // 任务分布
  const taskCount = {};
  rows.forEach((m) => {
    const k = taskLabel(m.task);
    taskCount[k] = (taskCount[k] || 0) + 1;
  });
  // 13+ 类任务，配足够区分的色板
  const COLORS = ["#409eff", "#e6a23c", "#67c23a", "#9254de", "#13c2c2", "#f56c6c", "#2f54eb", "#fa8c16", "#52c41a", "#eb2f96", "#722ed1", "#08979c", "#fa541c", "#1890ff"];
  pieChart = echarts.init(pieRef.value);
  pieChart.setOption({
    tooltip: { trigger: "item", formatter: "{b}: {c} ({d}%)" },
    // 图例移到右侧纵向滚动，避免底部堆叠遮挡
    legend: {
      type: "scroll",
      orient: "vertical",
      right: 8,
      top: 16,
      bottom: 16,
      itemWidth: 12,
      itemHeight: 12,
      textStyle: { fontSize: 12, color: "#5a6b87" },
    },
    color: COLORS,
    series: [
      {
        type: "pie",
        radius: ["45%", "72%"],
        center: ["34%", "52%"],
        avoidLabelOverlap: true,
        itemStyle: { borderColor: "#fff", borderWidth: 2, borderRadius: 4 },
        label: { show: false }, // 不在扇区上堆字，hover 显示
        labelLine: { show: false },
        emphasis: { label: { show: true, fontSize: 15, fontWeight: "bold", formatter: "{b}\n{c}" } },
        data: Object.entries(taskCount).map(([name, value]) => ({ name, value })),
      },
    ],
  });

  // 分类统计
  const catCount = {};
  rows.forEach((m) => {
    const k = m.category || "未分类";
    catCount[k] = (catCount[k] || 0) + 1;
  });
  const cats = Object.keys(catCount);
  const grad = (c1, c2) =>
    new echarts.graphic.LinearGradient(0, 0, 0, 1, [
      { offset: 0, color: c1 },
      { offset: 1, color: c2 },
    ]);
  // 每个分类一种竖向渐变（上浅下深），循环取色
  const BAR_GRADS = [
    ["#7ab8ff", "#2f7bff"], ["#7ee0a6", "#34c759"], ["#ffd27a", "#f5a623"],
    ["#b794f6", "#805ad5"], ["#5ce0e0", "#13c2c2"], ["#ff9aa0", "#f5515f"],
    ["#8fb0ff", "#2f54eb"], ["#ffb37a", "#fa8c16"], ["#9be36b", "#52c41a"],
    ["#ff9ed6", "#eb2f96"], ["#c4a0ff", "#722ed1"], ["#6fe0d6", "#08979c"],
  ];
  barChart = echarts.init(barRef.value);
  barChart.setOption({
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    grid: { left: 36, right: 16, top: 30, bottom: cats.length > 6 ? 78 : 50, containLabel: true },
    xAxis: {
      type: "category",
      data: cats,
      axisTick: { alignWithLabel: true },
      axisLine: { lineStyle: { color: "#dcdfe6" } },
      axisLabel: { interval: 0, rotate: cats.length > 6 ? 35 : 0, fontSize: 12, color: "#5a6b87" },
    },
    yAxis: {
      type: "value",
      minInterval: 1,
      axisLabel: { color: "#909399" },
      splitLine: { lineStyle: { type: "dashed", color: "#eef1f6" } },
    },
    series: [
      {
        type: "bar",
        barMaxWidth: 38,
        data: cats.map((c, i) => {
          const [c1, c2] = BAR_GRADS[i % BAR_GRADS.length];
          return { value: catCount[c], itemStyle: { borderRadius: [6, 6, 0, 0], color: grad(c1, c2) } };
        }),
        label: { show: true, position: "top", color: "#5a6b87", fontWeight: 600, fontSize: 12 },
        emphasis: { itemStyle: { shadowBlur: 10, shadowColor: "rgba(0,0,0,0.2)" } },
      },
    ],
  });
};

onMounted(async () => {
  const res = await modelApi.list({ pageNum: 1, pageSize: 200 });
  const rows = res.data.rows || [];
  stats[0].value = rows.length;
  stats[1].value = rows.filter((m) => m.filePath).length;
  stats[2].value = new Set(rows.map((m) => m.task).filter(Boolean)).size;
  stats[3].value = new Set(rows.map((m) => m.category).filter(Boolean)).size;

  await nextTick();
  renderCharts(rows);
  window.addEventListener("resize", resize);
});

onBeforeUnmount(() => {
  window.removeEventListener("resize", resize);
  pieChart && pieChart.dispose();
  barChart && barChart.dispose();
});
</script>

<style scoped>
.hero {
  display: flex;
  gap: 20px;
  padding: 24px 28px;
  border-radius: 14px;
  margin-bottom: 16px;
  color: #eaf2ff;
  background: linear-gradient(120deg, #0c1733 0%, #16306b 60%, #1f6feb 100%);
  box-shadow: 0 8px 24px rgba(20, 48, 107, 0.25);
}
.hero-badge {
  flex: none;
  width: 64px;
  height: 64px;
  border-radius: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 26px;
  font-weight: 800;
  color: #fff;
  background: linear-gradient(135deg, #409eff, #6a5acd);
}
.hero-title {
  margin: 0;
  font-size: 26px;
  font-weight: 800;
  letter-spacing: 0.5px;
}
.hero-sub {
  margin: 6px 0 8px;
  font-size: 14px;
  color: #bcd0f5;
}
.hero-desc {
  margin: 0 0 12px;
  font-size: 13px;
  line-height: 1.7;
  color: #d6e3ff;
  max-width: 880px;
}
.hero-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.htag {
  border: none;
  color: #fff;
}
.stat-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 16px;
}
.stat-card {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 20px;
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.05);
  border-left: 4px solid var(--accent);
}
.stat-icon {
  width: 52px;
  height: 52px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 26px;
  color: #fff;
  background: var(--accent);
}
.stat-value {
  font-size: 26px;
  font-weight: 700;
  color: #1f2d3d;
}
.stat-label {
  font-size: 13px;
  color: #909399;
}
.chart {
  height: 320px;
}
</style>
