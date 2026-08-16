<template>
  <div class="dash">
    <!-- 报告头 -->
    <section class="hero">
      <div class="hero-left">
        <div class="hero-badge-wrap">
          <span class="hero-icon">🏆</span>
        </div>
        <div>
          <div class="hero-tags">
            <span class="tag-ok">AI 分析完成</span>
            <span class="tag-muted">单打 · 技战术报告</span>
          </div>
          <h1 class="hero-title">{{ report.title || '技战术分析报告' }}</h1>
          <p class="hero-sub">{{ report.subtitle }}</p>
        </div>
      </div>
      <div class="hero-right">
        <div>
          <p class="hr-label">综合表现评分</p>
          <p class="hr-score">{{ report.overallScore ?? '-' }}<span> / 100</span></p>
        </div>
        <div class="hr-div" />
        <div>
          <p class="hr-label">AI 判定优势方</p>
          <p class="hr-adv">{{ advText }}</p>
        </div>
        <el-button v-if="resultVideoUrl" type="primary" plain size="small" class="hero-btn" @click="$emit('play-video')">
          查看标注视频
        </el-button>
      </div>
    </section>

    <!-- 指标卡 -->
    <section class="metric-grid">
      <article v-for="m in report.metrics || []" :key="m.label" class="metric-card">
        <div class="metric-top">
          <span>{{ m.label }}</span>
        </div>
        <p class="metric-val">
          {{ m.value }} <span class="metric-unit">{{ m.unit }}</span>
        </p>
        <p class="metric-note">{{ m.note }}</p>
      </article>
    </section>

    <div class="row-2">
      <!-- 球员对比 -->
      <section class="panel grow">
        <header class="panel-hd">
          <h2>运动员表现对比</h2>
          <span class="pill">同场数据校准</span>
        </header>
        <div class="compare-body">
          <div class="player-cards">
            <div
              v-for="(p, idx) in report.players || []"
              :key="p.label"
              class="player-card"
              :class="idx === 0 ? 'p1' : 'p2'"
            >
              <div class="pc-top">
                <span class="pc-name">{{ p.label }}</span>
                <span v-if="p.advantage" class="pc-adv">优势</span>
              </div>
              <p class="pc-score">{{ p.score }}</p>
              <p class="pc-sub">综合评分</p>
              <div class="pc-rows">
                <span>移动距离 <b>{{ p.distance }} m</b></span>
                <span>峰值速度 <b>{{ p.maxSpeedKmh }} km/h</b></span>
                <span>平均速度 <b>{{ p.avgSpeed }} m/s</b></span>
              </div>
            </div>
          </div>
          <div class="dim-list">
            <div v-for="d in report.dimensions || []" :key="d.label" class="dim-row">
              <span class="dim-label">{{ d.label }}</span>
              <div class="dim-bar">
                <span class="bar-p1" :style="{ width: `${d.p1 / 2}%` }" />
                <span class="bar-p2" :style="{ width: `${d.p2 / 2}%` }" />
              </div>
              <span class="dim-num">{{ d.p1 }}/{{ d.p2 }}</span>
            </div>
            <div class="dim-legend">
              <span><i class="dot p1" />P1</span>
              <span><i class="dot p2" />P2</span>
            </div>
          </div>
        </div>
      </section>

      <!-- AI 洞察 -->
      <aside class="panel">
        <header class="panel-hd">
          <h2>AI 比赛洞察</h2>
          <span class="pill">{{ (report.insights || []).length }} 条关键发现</span>
        </header>
        <div class="insight-list">
          <div
            v-for="(ins, i) in report.insights || []"
            :key="i"
            class="insight"
            :class="ins.tone || 'primary'"
          >
            <p class="ins-title">{{ ins.title }}</p>
            <p class="ins-text">{{ ins.text }}</p>
          </div>
          <el-empty v-if="!(report.insights || []).length" description="暂无洞察" :image-size="48" />
        </div>
      </aside>
    </div>

    <div class="row-3">
      <!-- 热区 -->
      <section class="panel">
        <header class="panel-hd">
          <h2>场上移动热区</h2>
          <span class="pill">位置密度</span>
        </header>
        <div class="court-wrap">
          <div class="court">
            <div class="line net" />
            <div class="line mid-v" />
            <div class="line svc-t" />
            <div class="line svc-b" />
            <div class="line side-l" />
            <div class="line side-r" />
            <span
              v-for="(h, i) in report.heatDots || []"
              :key="i"
              class="heat-blob"
              :class="h.level"
              :style="{ left: h.left + '%', top: h.top + '%' }"
            />
          </div>
          <div v-if="heatmapUrl" class="heat-img-box">
            <img :src="heatmapUrl" alt="heatmap" />
            <span>密度图</span>
          </div>
        </div>
      </section>

      <!-- 落点 -->
      <section class="panel">
        <header class="panel-hd">
          <h2>球落点分布</h2>
          <span class="pill">{{ report.landingCount || 0 }} 次落地</span>
        </header>
        <div class="court-wrap">
          <div class="court">
            <div class="line net" />
            <div class="line mid-v" />
            <div class="line svc-t" />
            <div class="line svc-b" />
            <div class="line side-l" />
            <div class="line side-r" />
            <span
              v-for="(L, i) in visibleLandings"
              :key="i"
              class="land-dot"
              :class="L.player"
              :style="landingStyle(L)"
              :title="landingTitle(L)"
            />
          </div>
          <div class="land-meta">
            <span><i class="dot p1" />P1 / 上场侧落地</span>
            <span><i class="dot p2" />P2 / 下场侧落地</span>
            <p>边线附近落地 <b>{{ report.edgeUtilization ?? 0 }}%</b></p>
            <p class="land-note">仅统计死球落地（非每次过网）；原始球检 {{ report.shuttleDetectionCount ?? summary.shuttleDetections ?? 0 }} 次</p>
          </div>
        </div>
      </section>

      <!-- 技术分布 -->
      <section class="panel">
        <header class="panel-hd">
          <h2>技术使用分布</h2>
          <span class="pill">场地分区代理</span>
        </header>
        <div class="shot-list">
          <div v-for="s in report.shots || []" :key="s.label" class="shot-row">
            <div class="shot-top">
              <span>{{ s.label }}</span>
              <b>{{ s.value }}%</b>
            </div>
            <div class="shot-track">
              <div class="shot-fill" :style="{ width: Math.min(100, s.value * 1.2) + '%' }" />
            </div>
          </div>
          <div class="shot-note">
            主动进攻代理占比 <b>{{ report.attackShare ?? 0 }}%</b>
            （由前场/后场活动与峰值速度估算，非击球分类模型）
          </div>
        </div>
      </section>
    </div>

    <!-- 教练建议 -->
    <section class="panel">
      <header class="panel-hd">
        <h2>教练训练建议</h2>
        <span class="pill">优先级排序</span>
      </header>
      <div class="tips-grid">
        <div
          v-for="t in report.coachTips || []"
          :key="t.level"
          class="tip-card"
          :class="t.tone"
        >
          <span class="tip-level">{{ t.level }}</span>
          <h3>{{ t.title }}</h3>
          <p>{{ t.text }}</p>
        </div>
      </div>
    </section>

    <!-- 原始图表 + 摘要 -->
    <section class="panel">
      <header class="panel-hd">
        <h2>原始统计与图表</h2>
        <span class="pill">兼容导出</span>
      </header>
      <div class="raw-grid">
        <div class="raw-stats">
          <div class="raw-item"><b>{{ summary.frames ?? '-' }}</b><span>总帧数</span></div>
          <div class="raw-item"><b>{{ summary.rallyCount ?? '-' }}</b><span>回合数</span></div>
          <div class="raw-item"><b>{{ summary.totalPersons ?? '-' }}</b><span>人体累计</span></div>
          <div class="raw-item"><b>{{ summary.shuttleDetections ?? '-' }}</b><span>羽毛球检出</span></div>
        </div>
        <div class="raw-charts">
          <div v-if="heatmapUrl" class="raw-chart">
            <p>位置热力图</p>
            <img :src="heatmapUrl" alt="heatmap" />
          </div>
          <div v-if="scatterUrl" class="raw-chart">
            <p>位置散点图</p>
            <img :src="scatterUrl" alt="scatter" />
          </div>
        </div>
      </div>
      <p class="foot-note">
        分析引擎：YOLO Pose / RTMO / RTMPose · 报告指标由轨迹与检测数据推导，仅供训练辅助
      </p>
    </section>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const COURT_W = 5.18
const COURT_L = 13.4

const props = defineProps({
  report: { type: Object, default: () => ({}) },
  summary: { type: Object, default: () => ({}) },
  heatmapUrl: { type: String, default: '' },
  scatterUrl: { type: String, default: '' },
  resultVideoUrl: { type: String, default: '' },
})

defineEmits(['play-video'])

const advText = computed(() => {
  const a = props.report?.advantage
  if (!a?.label) return '—'
  return `${a.label} · ${a.style || ''}`
})

const visibleLandings = computed(() => {
  const list = props.report?.landings || []
  if (list.length <= 100) return list
  const step = Math.ceil(list.length / 100)
  return list.filter((_, i) => i % step === 0)
})

function landingStyle(L) {
  return {
    left: `${Math.min(96, Math.max(2, (Number(L.x) / COURT_W) * 100))}%`,
    top: `${Math.min(96, Math.max(2, (Number(L.y) / COURT_L) * 100))}%`,
  }
}

function landingTitle(L) {
  const side = L.player === 'p1' ? 'P1 上场' : 'P2 下场'
  const kind = ({ net_cross: '过网', flight_peak: '飞入', decel: '减速', player_proxy: '代理' })[L.kind] || L.kind || ''
  return `${side} · ${kind}${L.frame ? ` · f${L.frame}` : ''}`
}
</script>

<style scoped>
.dash {
  --bg: #f3f6f9;
  --fg: #172033;
  --card: #fff;
  --primary: #146c5c;
  --muted: #edf1f4;
  --muted-fg: #6b7789;
  --border: #dce3e9;
  --orange: #f29d49;
  --green: #52b788;
  --blue: #2f80ed;
  display: flex;
  flex-direction: column;
  gap: 14px;
  color: var(--fg);
}

.hero {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 20px;
  border-radius: 12px;
  background: #172033;
  color: #f7fafc;
}
.hero-left { display: flex; gap: 14px; align-items: center; }
.hero-badge-wrap {
  width: 56px; height: 56px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.15);
  font-size: 26px;
}
.hero-tags { display: flex; gap: 8px; margin-bottom: 6px; flex-wrap: wrap; }
.tag-ok {
  background: rgba(82,183,136,0.2); color: #7dcea0;
  font-size: 10px; font-weight: 700; padding: 2px 8px; border-radius: 4px;
}
.tag-muted { font-size: 12px; color: rgba(255,255,255,0.45); }
.hero-title { margin: 0; font-size: 20px; font-weight: 800; letter-spacing: -0.02em; }
.hero-sub { margin: 4px 0 0; font-size: 12px; color: rgba(255,255,255,0.5); }
.hero-right {
  display: flex; align-items: center; gap: 16px;
  background: rgba(255,255,255,0.06); border-radius: 10px; padding: 10px 14px;
}
.hr-label { margin: 0; font-size: 10px; color: rgba(255,255,255,0.45); }
.hr-score { margin: 2px 0 0; font-size: 26px; font-weight: 800; }
.hr-score span { font-size: 12px; color: rgba(255,255,255,0.45); font-weight: 500; }
.hr-div { width: 1px; height: 36px; background: rgba(255,255,255,0.15); }
.hr-adv { margin: 2px 0 0; font-size: 14px; font-weight: 700; color: #7dcea0; }
.hero-btn { margin-left: 4px; }

.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}
@media (max-width: 992px) { .metric-grid { grid-template-columns: repeat(2, 1fr); } }
.metric-card {
  background: var(--card); border: 1px solid var(--border);
  border-radius: 12px; padding: 14px 16px;
}
.metric-top { font-size: 12px; font-weight: 600; color: var(--muted-fg); }
.metric-val { margin: 10px 0 4px; font-size: 26px; font-weight: 800; }
.metric-unit { font-size: 12px; font-weight: 500; color: var(--muted-fg); }
.metric-note { margin: 0; font-size: 11px; color: var(--muted-fg); }

.panel {
  background: var(--card); border: 1px solid var(--border);
  border-radius: 12px; overflow: hidden;
}
.panel.grow { flex: 1.35; }
.panel-hd {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 18px; border-bottom: 1px solid var(--border);
}
.panel-hd h2 { margin: 0; font-size: 14px; font-weight: 700; }
.pill {
  font-size: 11px; font-weight: 600; color: var(--primary);
  background: rgba(20,108,92,0.08); padding: 3px 10px; border-radius: 999px;
}

.row-2 { display: grid; grid-template-columns: 1.35fr 0.65fr; gap: 14px; }
.row-3 { display: grid; grid-template-columns: 1fr 1fr 0.9fr; gap: 14px; }
@media (max-width: 1100px) {
  .row-2, .row-3 { grid-template-columns: 1fr; }
}

.compare-body {
  display: grid; grid-template-columns: 0.9fr 1.1fr; gap: 16px; padding: 16px 18px;
}
@media (max-width: 768px) { .compare-body { grid-template-columns: 1fr; } }
.player-cards { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.player-card { border-radius: 10px; padding: 14px; background: var(--muted); }
.player-card.p1 { background: rgba(20,108,92,0.07); }
.pc-top { display: flex; justify-content: space-between; align-items: center; }
.pc-name { font-size: 12px; font-weight: 700; color: var(--primary); }
.player-card.p2 .pc-name { color: var(--fg); }
.pc-adv {
  font-size: 10px; font-weight: 700; color: #fff;
  background: var(--primary); padding: 2px 8px; border-radius: 4px;
}
.pc-score { margin: 10px 0 0; font-size: 32px; font-weight: 800; }
.pc-sub { margin: 0; font-size: 10px; color: var(--muted-fg); }
.pc-rows {
  margin-top: 12px; display: flex; flex-direction: column; gap: 6px;
  font-size: 11px; color: var(--muted-fg);
}
.pc-rows b { float: right; color: var(--fg); }

.dim-list { display: flex; flex-direction: column; gap: 12px; }
.dim-row {
  display: grid; grid-template-columns: 72px 1fr 52px;
  align-items: center; gap: 8px;
}
.dim-label { font-size: 11px; color: var(--muted-fg); }
.dim-bar {
  display: flex; height: 8px; border-radius: 999px; overflow: hidden; background: var(--muted);
}
.bar-p1 { background: var(--primary); }
.bar-p2 { margin-left: auto; background: var(--orange); }
.dim-num { font-size: 10px; font-weight: 700; text-align: right; }
.dim-legend {
  display: flex; gap: 14px; font-size: 10px; color: var(--muted-fg); margin-top: 4px;
}
.dot {
  display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 4px;
}
.dot.p1 { background: var(--primary); }
.dot.p2 { background: var(--orange); }

.insight-list { display: flex; flex-direction: column; gap: 10px; padding: 14px; }
.insight {
  border-radius: 8px; padding: 12px; border-left: 4px solid var(--primary);
  background: rgba(20,108,92,0.05);
}
.insight.orange { border-left-color: var(--orange); background: rgba(242,157,73,0.08); }
.insight.green { border-left-color: var(--green); background: rgba(82,183,136,0.08); }
.ins-title { margin: 0; font-size: 12px; font-weight: 700; }
.ins-text { margin: 6px 0 0; font-size: 11px; line-height: 1.55; color: var(--muted-fg); }

.court-wrap {
  display: flex; align-items: center; justify-content: center;
  gap: 14px; padding: 14px; flex-wrap: wrap;
}
.court {
  position: relative; width: 130px; height: 260px;
  border: 2px solid rgba(20,108,92,0.28);
  background: rgba(20,108,92,0.04); overflow: hidden;
}
.line { position: absolute; background: rgba(20,108,92,0.22); }
.line.net { left: 0; right: 0; top: 50%; height: 2px; }
.line.mid-v { top: 0; bottom: 0; left: 50%; width: 1px; }
.line.svc-t { left: 0; right: 0; top: 24%; height: 1px; }
.line.svc-b { left: 0; right: 0; bottom: 24%; height: 1px; }
.line.side-l { top: 0; bottom: 0; left: 13%; width: 1px; }
.line.side-r { top: 0; bottom: 0; right: 13%; width: 1px; }
.heat-blob {
  position: absolute; width: 36px; height: 36px; border-radius: 50%;
  transform: translate(-50%, -50%); filter: blur(10px);
}
.heat-blob.high { background: rgba(242,157,73,0.75); width: 48px; height: 48px; }
.heat-blob.mid { background: rgba(20,108,92,0.55); }
.heat-blob.low { background: rgba(20,108,92,0.2); }
.land-dot {
  position: absolute; width: 9px; height: 9px; border-radius: 50%;
  border: 2px solid #fff; transform: translate(-50%, -50%);
}
/* 与图例 .dot.p1/.dot.p2、维度条 bar-p1/bar-p2 一致：P1=primary，P2=orange */
.land-dot.p1 { background: var(--primary); }
.land-dot.p2 { background: var(--orange); }
.heat-img-box, .land-meta {
  font-size: 10px; color: var(--muted-fg);
  display: flex; flex-direction: column; gap: 8px;
}
.heat-img-box img { max-height: 160px; border-radius: 6px; border: 1px solid var(--border); }
.land-meta b { color: var(--fg); }
.land-note { margin: 0; line-height: 1.45; opacity: 0.9; }

.shot-list { padding: 16px 18px; display: flex; flex-direction: column; gap: 12px; }
.shot-top { display: flex; justify-content: space-between; font-size: 11px; margin-bottom: 4px; }
.shot-track { height: 8px; border-radius: 999px; background: var(--muted); overflow: hidden; }
.shot-fill { height: 100%; border-radius: 999px; background: var(--primary); }
.shot-note {
  margin-top: 4px; padding: 10px 12px; border-radius: 8px;
  background: var(--muted); font-size: 11px; line-height: 1.5; color: var(--muted-fg);
}
.shot-note b { color: var(--fg); }

.tips-grid {
  display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; padding: 14px;
}
@media (max-width: 900px) { .tips-grid { grid-template-columns: 1fr; } }
.tip-card {
  border-radius: 10px; padding: 14px; border: 1px solid var(--border);
}
.tip-card.primary { border-color: rgba(20,108,92,0.25); background: rgba(20,108,92,0.05); }
.tip-level { font-size: 10px; font-weight: 800; color: var(--primary); }
.tip-card.orange .tip-level { color: var(--orange); }
.tip-card.green .tip-level { color: var(--green); }
.tip-card h3 { margin: 8px 0 6px; font-size: 13px; font-weight: 700; }
.tip-card p { margin: 0; font-size: 12px; line-height: 1.55; color: var(--muted-fg); }

.raw-grid { padding: 14px 18px; display: flex; flex-direction: column; gap: 14px; }
.raw-stats {
  display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px;
}
.raw-item {
  text-align: center; padding: 12px; border-radius: 8px; background: var(--muted);
}
.raw-item b { display: block; font-size: 22px; font-weight: 800; }
.raw-item span { font-size: 12px; color: var(--muted-fg); }
.raw-charts {
  display: grid; grid-template-columns: 1fr 1fr; gap: 12px;
}
.raw-chart {
  text-align: center; padding: 10px; border: 1px dashed var(--border); border-radius: 8px;
}
.raw-chart p { margin: 0 0 8px; font-size: 12px; font-weight: 600; }
.raw-chart img { max-width: 100%; max-height: 280px; object-fit: contain; }
.foot-note {
  margin: 0; padding: 0 18px 14px; font-size: 10px; color: var(--muted-fg);
}
</style>
