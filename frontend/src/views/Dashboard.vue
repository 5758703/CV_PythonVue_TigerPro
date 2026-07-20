<template>
  <div class="home">
    <!-- 平台介绍 -->
    <div class="hero">
      <a
        class="github-link"
        href="https://github.com/5758703/CV_PythonVue_TigerPro"
        target="_blank"
        rel="noopener noreferrer"
        title="在 GitHub 上查看本项目"
      >
        <svg class="github-icon" viewBox="0 0 16 16" aria-hidden="true">
          <path
            fill="currentColor"
            d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38
            0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52
            -.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2
            -3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82
            .64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12
            .51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93
            -.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z"
          />
        </svg>
        <span>GitHub</span>
      </a>
      <div class="hero-badge">CV</div>
      <div class="hero-body">
        <h1 class="hero-title">Tiger AI Platform</h1>
        <p class="hero-sub">多任务 / 多模态 AI 模型管理与测试学习平台 —— 视觉 · 文本 · 语音 · 多模态 全栈纳管</p>
        <p class="hero-desc">
          一站式管理与在线测试多种 AI 模型：从 <b>HuggingFace / ModelScope / Roboflow</b> 拉取权重、统一纳管、按任务即点即测。
          平台现支持 <b>14+ 类 AI 任务</b>，推理引擎涵盖 <b>YOLO · ByteTrack · transformers · funasr · RF-DETR</b> 等，纯 <b>CPU</b> 即可运行。
          视觉任务支持 <b>图片 / 视频 / 摄像头实时</b> 三种输入；图片检测可调 <b>DeepSeek AI</b> 生成正式分析报告。
        </p>
        <div class="hero-tags">
          <el-tag effect="dark" color="#409eff" class="htag">目标检测</el-tag>
          <el-tag effect="dark" color="#1a73e8" class="htag">模型训练闭环</el-tag>
          <el-tag effect="dark" color="#ff6b35" class="htag">视频抽帧 · 在线标注</el-tag>
          <el-tag effect="dark" color="#67c23a" class="htag">图像分类</el-tag>
          <el-tag effect="dark" color="#1f6feb" class="htag">目标追踪 · 越线计数</el-tag>
          <el-tag effect="dark" color="#00b894" class="htag">姿态估计</el-tag>
          <el-tag effect="dark" color="#d63384" class="htag">摄像头实时 · 录制</el-tag>
          <el-tag effect="dark" color="#b23b3b" class="htag">DeepSeek 分析报告</el-tag>
          <el-tag effect="dark" color="#e6a23c" class="htag">文本分类</el-tag>
          <el-tag effect="dark" color="#9254de" class="htag">实体识别 NER</el-tag>
          <el-tag effect="dark" color="#fa8c16" class="htag">智能问答 QA</el-tag>
          <el-tag effect="dark" color="#f5222d" class="htag">语音识别 ASR</el-tag>
          <el-tag effect="dark" color="#08979c" class="htag">语音合成 TTS</el-tag>
          <el-tag effect="dark" color="#722ed1" class="htag">模型全生命周期</el-tag>
          <el-tag effect="dark" color="#52c41a" class="htag">RBAC 权限</el-tag>
        </div>
      </div>
    </div>

    <!-- 训练闭环快捷入口 -->
    <el-card shadow="hover" class="loop-card">
      <template #header>
        <div class="loop-hd">
          <span class="loop-title">AI 训练闭环 · 从视频到可用模型</span>
          <router-link to="/ai/training">
            <el-button type="primary" size="small">进入模型训练</el-button>
          </router-link>
        </div>
      </template>
      <div class="loop-steps">
        <div v-for="(step, i) in trainSteps" :key="step.title" class="loop-step">
          <div class="step-idx">{{ i + 1 }}</div>
          <div class="step-body">
            <div class="step-title">{{ step.title }}</div>
            <div class="step-desc">{{ step.desc }}</div>
          </div>
          <el-icon v-if="i < trainSteps.length - 1" class="step-arrow"><ArrowRight /></el-icon>
        </div>
      </div>
    </el-card>

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
import { ArrowRight } from "@element-plus/icons-vue";

import { modelApi, trainingApi } from "../api/ai";

const TASK_LABELS = {
  "object-detection": "目标检测",
  "instance-segmentation": "实例分割",
  "interactive-segmentation": "交互分割",
  "pose-estimation": "姿态估计",
  "image-classification": "图像分类",
  "ocr": "OCR(端到端)",
  "text-detection": "文本检测",
  "text-recognition": "文本识别(行)",
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

const trainSteps = [
  { title: "新建数据集", desc: "yolo_flat 格式，配置检测类别" },
  { title: "视频抽帧", desc: "10s 视频可抽 200+ 张样本" },
  { title: "数据标注", desc: "Canvas 在线画框，YOLO 标签自动保存" },
  { title: "构建", desc: "自动划分 train/val，生成 data.yaml" },
  { title: "训练任务", desc: "YOLOv8 训练，曲线与 mAP 监控" },
  { title: "部署检测", desc: "注册到模型管理，即用于视频检测" },
];

const stats = reactive([
  { label: "模型总数", value: 0, icon: "Files", color: "#409eff" },
  { label: "已就绪（有权重）", value: 0, icon: "CircleCheck", color: "#67c23a" },
  { label: "训练数据集", value: 0, icon: "FolderOpened", color: "#1f6feb" },
  { label: "训练任务", value: 0, icon: "TrendCharts", color: "#ff6b35" },
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
  const taskCount = {};
  rows.forEach((m) => {
    const k = taskLabel(m.task);
    taskCount[k] = (taskCount[k] || 0) + 1;
  });
  const COLORS = ["#409eff", "#e6a23c", "#67c23a", "#9254de", "#13c2c2", "#f56c6c", "#2f54eb", "#fa8c16", "#52c41a", "#eb2f96", "#722ed1", "#08979c", "#fa541c", "#1890ff"];
  pieChart = echarts.init(pieRef.value);
  pieChart.setOption({
    tooltip: { trigger: "item", formatter: "{b}: {c} ({d}%)" },
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
        label: { show: false },
        labelLine: { show: false },
        emphasis: { label: { show: true, fontSize: 15, fontWeight: "bold", formatter: "{b}\n{c}" } },
        data: Object.entries(taskCount).map(([name, value]) => ({ name, value })),
      },
    ],
  });

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
  const [modelRes, dsRes, jobRes] = await Promise.allSettled([
    modelApi.list({ pageNum: 1, pageSize: 200 }),
    trainingApi.listDatasets({ pageNum: 1, pageSize: 100 }),
    trainingApi.listJobs({ pageNum: 1, pageSize: 100 }),
  ]);

  const rows = modelRes.status === "fulfilled" ? modelRes.value.data.rows || [] : [];
  stats[0].value = rows.length;
  stats[1].value = rows.filter((m) => m.filePath).length;
  stats[4].value = new Set(rows.map((m) => m.task).filter(Boolean)).size;
  stats[5].value = new Set(rows.map((m) => m.category).filter(Boolean)).size;

  if (dsRes.status === "fulfilled") {
    stats[2].value = dsRes.value.data.total ?? (dsRes.value.data.rows || []).length;
  }
  if (jobRes.status === "fulfilled") {
    stats[3].value = jobRes.value.data.total ?? (jobRes.value.data.rows || []).length;
  }

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
  position: relative;
  display: flex;
  gap: 20px;
  padding: 24px 28px;
  border-radius: 14px;
  margin-bottom: 16px;
  color: #eaf2ff;
  background: linear-gradient(120deg, #0c1733 0%, #16306b 60%, #1f6feb 100%);
  box-shadow: 0 8px 24px rgba(20, 48, 107, 0.25);
}
.github-link {
  position: absolute;
  top: 16px;
  right: 18px;
  z-index: 1;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 600;
  color: #eaf2ff;
  text-decoration: none;
  background: rgba(255, 255, 255, 0.12);
  border: 1px solid rgba(255, 255, 255, 0.22);
  transition: background 0.15s, border-color 0.15s, transform 0.15s;
}
.github-link:hover {
  background: rgba(255, 255, 255, 0.22);
  border-color: rgba(255, 255, 255, 0.4);
  transform: translateY(-1px);
}
.github-icon {
  width: 16px;
  height: 16px;
  flex: none;
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
  padding-right: 110px;
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
  margin: 0 0 10px;
  font-size: 13px;
  line-height: 1.7;
  color: #d6e3ff;
  max-width: 960px;
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
.loop-card {
  margin-bottom: 16px;
}
.loop-hd {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.loop-title {
  font-weight: 700;
  color: #1f2d3d;
}
.loop-steps {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 4px;
  align-items: flex-start;
}
.loop-step {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
  min-width: 140px;
  max-width: 200px;
}
.step-idx {
  flex: none;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: linear-gradient(135deg, #1f6feb, #409eff);
  color: #fff;
  font-size: 13px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
}
.step-body {
  flex: 1;
  min-width: 0;
}
.step-title {
  font-size: 13px;
  font-weight: 600;
  color: #1f2d3d;
}
.step-desc {
  font-size: 11px;
  color: #909399;
  line-height: 1.4;
  margin-top: 2px;
}
.step-arrow {
  color: #c0c4cc;
  font-size: 16px;
  flex: none;
}
.stat-row {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}
.stat-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.05);
  border-left: 4px solid var(--accent);
}
.stat-icon {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  color: #fff;
  background: var(--accent);
  flex: none;
}
.stat-value {
  font-size: 22px;
  font-weight: 700;
  color: #1f2d3d;
}
.stat-label {
  font-size: 12px;
  color: #909399;
  white-space: nowrap;
}
.chart {
  height: 320px;
}
@media (max-width: 1400px) {
  .stat-row {
    grid-template-columns: repeat(3, 1fr);
  }
}
@media (max-width: 768px) {
  .stat-row {
    grid-template-columns: repeat(2, 1fr);
  }
  .loop-step {
    max-width: 100%;
  }
}
</style>
