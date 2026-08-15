<template>
  <div class="handpose-page">
    <!-- 配置 -->
    <el-card shadow="never" class="cfg-card">
      <template #header>
        <div class="card-head">
          <div class="card-head-left">
            <span class="card-title">手势识别</span>
            <el-tooltip placement="bottom-start">
              <template #content>
                <div class="help-pop">
                  <p><b>数字手势（MediaPipe）</b>：21 关键点 → 0–9（含中式 6–9）；双手「右 左」组合。</p>
                  <p><b>中国手语（YOLO11s）</b>：先定位手部再识别 30 类字母/声母（A–Z、CH、NG、SH、ZH）。请将手靠近镜头、背景简洁。</p>
                  <p>识别稳定约 1 秒自动记入序列，可勾选语音播报。</p>
                </div>
              </template>
              <el-icon class="card-help"><QuestionFilled /></el-icon>
            </el-tooltip>
            <el-tag v-if="running" type="success" size="small" effect="plain">识别中</el-tag>
          </div>
          <div class="card-head-actions">
            <template v-if="mode === 'camera'">
              <el-button v-if="!running" type="primary" :disabled="!deviceId" @click="start">开始识别</el-button>
              <el-button v-else type="danger" @click="stop">停止</el-button>
            </template>
          </div>
        </div>
      </template>
      <el-form label-position="top" class="cfg-form" @submit.prevent>
        <el-row :gutter="16">
          <el-col :xs="24" :sm="12" :md="8">
            <el-form-item label="识别模型">
              <el-select v-model="recognizer" :disabled="running" @change="onRecognizerChange">
                <el-option
                  v-for="r in recognizers"
                  :key="r.id"
                  :label="r.name"
                  :value="r.id"
                />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :xs="12" :sm="6" :md="4">
            <el-form-item label="来源">
              <el-select v-model="mode" :disabled="running" @change="onModeChange">
                <el-option label="本地摄像头" value="camera" />
                <el-option label="图片" value="image" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col v-if="mode === 'camera'" :xs="24" :sm="10" :md="8">
            <el-form-item label="摄像头">
              <div class="src-pick">
                <el-select v-model="deviceId" placeholder="选择摄像头" :disabled="running" :loading="devicesLoading">
                  <el-option v-for="d in devices" :key="d.deviceId" :label="d.label || d.deviceId" :value="d.deviceId" />
                </el-select>
                <el-button link type="primary" :disabled="running" @click="listDevices(true)">刷新</el-button>
              </div>
            </el-form-item>
          </el-col>
          <el-col v-if="mode === 'image'" :xs="24" :sm="10" :md="8">
            <el-form-item label="图片">
              <div class="src-pick">
                <el-upload :show-file-list="false" :auto-upload="false" accept="image/*" :on-change="onPickImage">
                  <el-button :icon="UploadFilled" :loading="imgLoading">选择图片并识别</el-button>
                </el-upload>
              </div>
            </el-form-item>
          </el-col>
          <el-col v-if="isMediapipe" :xs="12" :sm="4" :md="3">
            <el-form-item label="最大手数">
              <el-input-number v-model="maxHands" :min="1" :max="4" style="width: 100%" :disabled="running" />
            </el-form-item>
          </el-col>
          <el-col v-if="isMediapipe" :xs="12" :sm="6" :md="4">
            <el-form-item label="关键点置信度">
              <el-slider v-model="handConf" :min="0.5" :max="0.95" :step="0.05" :disabled="running" />
            </el-form-item>
          </el-col>
          <el-col v-if="isCsl" :xs="12" :sm="6" :md="4">
            <el-form-item label="检测置信度">
              <el-slider v-model="detConf" :min="0.25" :max="0.9" :step="0.05" :disabled="running" />
            </el-form-item>
          </el-col>
          <el-col :xs="12" :sm="6" :md="4">
            <el-form-item label="语音播报">
              <el-switch v-model="speakOn" />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
    </el-card>

    <el-row :gutter="12">
      <!-- 画面 -->
      <el-col :xs="24" :md="15">
        <el-card shadow="never" class="stage-card">
          <template #header>
            <div class="card-head"><span class="card-title">{{ mode === 'camera' ? '实时画面' : '识别结果图' }}</span>
              <span v-if="fps" class="hint-inline">{{ fps }} FPS</span>
            </div>
          </template>
          <div v-if="mode === 'camera'" class="cam-stage">
            <video ref="videoEl" class="cam-media" autoplay muted playsinline />
            <canvas ref="overlayEl" class="cam-overlay" />
            <div v-if="!previewOpen" class="stage-placeholder">选择摄像头后点击「开始识别」</div>
          </div>
          <div v-else class="img-stage">
            <img v-if="imgResult" :src="'data:image/jpeg;base64,' + imgResult" class="result-img" />
            <el-empty v-else description="选择包含手部的图片" />
          </div>
        </el-card>
      </el-col>
      <!-- 结果 -->
      <el-col :xs="24" :md="9">
        <el-card shadow="never" class="res-card">
          <template #header>
            <div class="card-head"><span class="card-title">当前识别结果</span></div>
          </template>
          <div class="digit-big" :class="{ 'digit-none': !displayText, 'digit-dual': isDualDisplay, 'digit-csl': isCsl }">
            {{ displayText || '—' }}
          </div>
          <div class="digit-sub">{{ displaySubText }}</div>
          <!-- MediaPipe 手列表 -->
          <div v-if="isMediapipe" class="hand-chips">
            <div v-for="(h, i) in handsNow" :key="i" class="hand-chip">
              <el-tag size="small" :type="h.handedness === 'Right' ? 'success' : 'warning'" effect="dark">
                {{ h.handedness === 'Right' ? '右手' : '左手' }} · {{ h.digit ?? h.count }}
              </el-tag>
              <span class="gesture-zh">{{ h.gestureZh || '' }}</span>
              <span class="finger-dots">
                <span v-for="f in FINGER_ORDER" :key="f" class="finger-dot" :class="{ on: h.fingers[f] }" :title="f" />
              </span>
              <span class="hint-inline">{{ (h.confidence * 100).toFixed(0) }}%</span>
            </div>
          </div>
          <!-- 手语检测列表 -->
          <div v-else class="hand-chips">
            <div v-for="(det, i) in detectionsNow" :key="i" class="hand-chip">
              <el-tag size="small" type="primary" effect="dark">{{ det.className }}</el-tag>
              <span class="gesture-zh">{{ det.labelZh || '' }}</span>
              <span class="hint-inline">{{ (det.confidence * 100).toFixed(0) }}%</span>
            </div>
            <div v-if="!detectionsNow.length" class="hint-inline">未检测到手语手势</div>
          </div>

          <el-divider content-position="left">{{ isCsl ? '动态手语序列' : '动态数字序列' }}</el-divider>
          <div class="seq-box">
            <span v-if="!digitSeq.length" class="hint-inline">{{ isCsl ? '比出手语并保持约 1 秒，自动记录到这里' : '比出数字并保持约 1 秒，自动记录到这里' }}</span>
            <span v-for="(d, i) in digitSeq" :key="i" class="seq-digit">{{ d }}</span>
          </div>
          <div class="seq-actions">
            <el-button size="small" :disabled="!digitSeq.length" @click="digitSeq = []">清空序列</el-button>
            <el-button size="small" link type="primary" :disabled="!digitSeq.length" @click="copySeq">复制</el-button>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, computed, onBeforeUnmount } from "vue";
import { ElMessage } from "element-plus";
import { QuestionFilled, UploadFilled } from "@element-plus/icons-vue";
import { handposeApi } from "../../../api/ai";

const FINGER_ORDER = ["thumb", "index", "middle", "ring", "pinky"];
// 逐指配色与后端 draw 一致（拇指紫/食指黄/中指绿/无名指蓝/小指橙）
const FINGER_COLORS = { thumb: "#c800c8", index: "#ffc800", middle: "#00c800", ring: "#0078ff", pinky: "#ff7800" };
const CONNECTIONS = [
  [0, 1], [1, 2], [2, 3], [3, 4],
  [0, 5], [5, 6], [6, 7], [7, 8],
  [5, 9], [9, 10], [10, 11], [11, 12],
  [9, 13], [13, 14], [14, 15], [15, 16],
  [13, 17], [17, 18], [18, 19], [19, 20],
  [0, 17],
];
const CONN_FINGER = ["thumb", "thumb", "thumb", "thumb", "index", "index", "index", "index",
  "middle", "middle", "middle", "middle", "ring", "ring", "ring", "ring",
  "pinky", "pinky", "pinky", "pinky", "pinky"];

const mode = ref("camera");
const recognizer = ref("mediapipe");
const recognizers = ref([
  { id: "mediapipe", name: "数字手势（MediaPipe 0–9）" },
  { id: "csl-yolo11s", name: "中国手语（YOLO11s）" },
]);
const devices = ref([]);
const deviceId = ref("");
const devicesLoading = ref(false);
const running = ref(false);
const previewOpen = ref(false);
const maxHands = ref(2);
const handConf = ref(0.8);
const detConf = ref(0.5);
const speakOn = ref(false);
const fps = ref(0);

const isMediapipe = computed(() => recognizer.value === "mediapipe");
const isCsl = computed(() => recognizer.value === "csl-yolo11s");

const videoEl = ref(null);
const overlayEl = ref(null);
const handsNow = ref([]);
const detectionsNow = ref([]);
const displayText = ref("");
const labelZh = ref("");
const leftDigit = ref(null);
const rightDigit = ref(null);
const digitSeq = ref([]);

const isDualDisplay = computed(() => isMediapipe.value && leftDigit.value != null && rightDigit.value != null);

const displaySubText = computed(() => {
  if (isCsl.value) {
    if (!detectionsNow.value.length) return "未检测到手语手势";
    return labelZh.value || `检测到 ${detectionsNow.value.length} 个手势`;
  }
  if (!handsNow.value.length) return "未检测到手";
  if (leftDigit.value != null && rightDigit.value != null) {
    return `左手 ${leftDigit.value} · 右手 ${rightDigit.value}`;
  }
  if (leftDigit.value != null) return `左手 ${leftDigit.value}`;
  if (rightDigit.value != null) return `右手 ${rightDigit.value}`;
  return `检测到 ${handsNow.value.length} 只手`;
});

const resetResult = () => {
  handsNow.value = [];
  detectionsNow.value = [];
  displayText.value = "";
  labelZh.value = "";
  leftDigit.value = null;
  rightDigit.value = null;
};

const applyDisplayFromResponse = (d) => {
  if (d.recognizer === "csl-yolo11s" || isCsl.value) {
    detectionsNow.value = d.detections || [];
    handsNow.value = [];
    leftDigit.value = null;
    rightDigit.value = null;
    displayText.value = d.displayText != null && d.displayText !== "" ? String(d.displayText) : "";
    labelZh.value = d.labelZh || "";
    return;
  }

  detectionsNow.value = [];
  handsNow.value = d.hands || [];
  leftDigit.value = d.leftDigit ?? null;
  rightDigit.value = d.rightDigit ?? null;
  labelZh.value = "";
  let text = d.displayText != null && d.displayText !== "" ? String(d.displayText) : "";

  const hands = handsNow.value;
  const looksDual = /^\d+\s+\d+$/.test(text.trim());
  if (hands.length >= 2 && !looksDual) {
    const top2 = [...hands]
      .sort((a, b) => (b.confidence || 0) - (a.confidence || 0))
      .slice(0, 2)
      .sort((a, b) => {
        const cx = (h) => (h.bbox ? (h.bbox[0] + h.bbox[2]) / 2 : (h.landmarks?.[0]?.[0] || 0));
        return cx(a) - cx(b);
      });
    const leftD = top2[1]?.digit ?? top2[1]?.count;
    const rightD = top2[0]?.digit ?? top2[0]?.count;
    if (leftD != null && rightD != null) {
      text = `${rightD} ${leftD}`;
      leftDigit.value = leftD;
      rightDigit.value = rightD;
    }
  }

  if (text) {
    displayText.value = text;
  } else if (hands.length) {
    displayText.value = d.primaryDigit != null ? String(d.primaryDigit) : String(d.totalCount ?? "");
  } else {
    displayText.value = "";
  }
};

const appendFormParams = (fd) => {
  fd.append("recognizer", recognizer.value);
  if (isMediapipe.value) {
    fd.append("maxHands", String(maxHands.value));
    fd.append("handConf", String(handConf.value));
  } else {
    fd.append("conf", String(detConf.value));
  }
};

const loadRecognizers = async () => {
  try {
    const res = await handposeApi.models();
    const list = res.data?.recognizers;
    if (Array.isArray(list) && list.length) recognizers.value = list;
  } catch { /* 使用默认列表 */ }
};

const onRecognizerChange = () => {
  stop();
  resetResult();
  digitSeq.value = [];
  stableDigit = null;
  stableCnt = 0;
  lastCommitted = null;
  imgResult.value = "";
};

const imgLoading = ref(false);
const imgResult = ref("");

let stream = null;
let loopTimer = null;
let busy = false;
let frameCount = 0;
let fpsTimer = null;
// 动态数字：连续稳定 STABLE_N 次（≈1s）且与上次入队值不同才记录
const STABLE_N = 5;
let stableDigit = null;
let stableCnt = 0;
let lastCommitted = null;

const listDevices = async (requestPerm = false) => {
  devicesLoading.value = true;
  try {
    if (requestPerm) {
      const s = await navigator.mediaDevices.getUserMedia({ video: true });
      s.getTracks().forEach((t) => t.stop());
    }
    const all = await navigator.mediaDevices.enumerateDevices();
    devices.value = all.filter((d) => d.kind === "videoinput");
    if (!deviceId.value && devices.value.length) deviceId.value = devices.value[0].deviceId;
  } catch (e) {
    ElMessage.warning(e.message || "无法枚举摄像头");
  } finally {
    devicesLoading.value = false;
  }
};

const onModeChange = () => {
  stop();
  imgResult.value = "";
  resetResult();
};

const start = async () => {
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: { deviceId: deviceId.value ? { exact: deviceId.value } : undefined, width: 960, height: 540 },
    });
  } catch (e) {
    ElMessage.error(e.message || "摄像头打开失败");
    return;
  }
  videoEl.value.srcObject = stream;
  previewOpen.value = true;
  running.value = true;
  frameCount = 0;
  if (fpsTimer) clearInterval(fpsTimer);
  fpsTimer = setInterval(() => { fps.value = frameCount; frameCount = 0; }, 1000);
  loopOnce();
};

const stop = () => {
  running.value = false;
  if (loopTimer) clearTimeout(loopTimer);
  loopTimer = null;
  if (fpsTimer) clearInterval(fpsTimer);
  fpsTimer = null;
  fps.value = 0;
  if (stream) {
    stream.getTracks().forEach((t) => t.stop());
    stream = null;
  }
  previewOpen.value = false;
  resetResult();
  const ov = overlayEl.value;
  if (ov?.width) ov.getContext("2d").clearRect(0, 0, ov.width, ov.height);
};

const SEND_W_DIGIT = 480;
const SEND_W_CSL = 640;
const capCanvas = document.createElement("canvas");

const loopOnce = async () => {
  if (!running.value) return;
  const v = videoEl.value;
  if (!v || !v.videoWidth || busy) {
    loopTimer = setTimeout(loopOnce, 80);
    return;
  }
  busy = true;
  try {
    const sendW = isCsl.value ? SEND_W_CSL : SEND_W_DIGIT;
    const scale = sendW / v.videoWidth;
    capCanvas.width = sendW;
    capCanvas.height = Math.round(v.videoHeight * scale);
    capCanvas.getContext("2d").drawImage(v, 0, 0, capCanvas.width, capCanvas.height);
    const blob = await new Promise((r) => capCanvas.toBlob(r, "image/jpeg", 0.7));
    if (blob && running.value) {
      const fd = new FormData();
      fd.append("file", blob, "frame.jpg");
      appendFormParams(fd);
      const res = await handposeApi.estimate(fd);
      if (running.value) {
        const d = res.data || {};
        applyDisplayFromResponse(d);
        drawOverlay(d);
        trackDigit(d);
        frameCount += 1;
      }
    }
  } catch { /* 单帧失败忽略 */ }
  finally { busy = false; }
  loopTimer = setTimeout(loopOnce, 60);
};

const drawOverlay = (d) => {
  const ov = overlayEl.value;
  if (!ov) return;
  if (ov.width !== d.width || ov.height !== d.height) {
    ov.width = d.width;
    ov.height = d.height;
  }
  const ctx = ov.getContext("2d");
  ctx.clearRect(0, 0, ov.width, ov.height);

  if (d.recognizer === "csl-yolo11s" || isCsl.value) {
    for (const det of d.detections || []) {
      const [x1, y1, x2, y2] = det.bbox;
      ctx.strokeStyle = "#00ff88";
      ctx.lineWidth = 2;
      ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
      ctx.font = "bold 18px sans-serif";
      ctx.fillStyle = "#00ff88";
      ctx.fillText(`${det.className}`, x1, Math.max(20, y1 - 6));
    }
    return;
  }

  for (const h of d.hands || []) {
    const pts = h.landmarks;
    ctx.lineWidth = 2;
    CONNECTIONS.forEach(([a, b], i) => {
      ctx.strokeStyle = FINGER_COLORS[CONN_FINGER[i]];
      ctx.beginPath();
      ctx.moveTo(pts[a][0], pts[a][1]);
      ctx.lineTo(pts[b][0], pts[b][1]);
      ctx.stroke();
    });
    ctx.fillStyle = "#ff2d2d";
    for (const p of pts) {
      ctx.beginPath();
      ctx.arc(p[0], p[1], 3.5, 0, Math.PI * 2);
      ctx.fill();
    }
    const dig = h.digit != null ? h.digit : h.count;
    ctx.font = "bold 20px sans-serif";
    ctx.fillStyle = "#ffee00";
    ctx.fillText(`${h.handedness === "Right" ? "右" : "左"} ${dig}`, h.bbox[0], Math.max(20, h.bbox[1] - 6));
  }
};

const trackDigit = (d) => {
  let token = null;
  if (d.recognizer === "csl-yolo11s" || isCsl.value) {
    token = (d.detections || []).length && d.displayText ? String(d.displayText) : null;
  } else {
    token = (d.hands || []).length && d.displayText != null && d.displayText !== ""
      ? String(d.displayText) : null;
  }
  if (token === stableDigit) {
    stableCnt += 1;
  } else {
    stableDigit = token;
    stableCnt = 1;
  }
  if (stableDigit == null) {
    if (stableCnt >= STABLE_N) lastCommitted = null;
    return;
  }
  if (stableCnt === STABLE_N && stableDigit !== lastCommitted) {
    lastCommitted = stableDigit;
    digitSeq.value.push(stableDigit);
    if (speakOn.value && window.speechSynthesis) {
      const u = new SpeechSynthesisUtterance(isCsl.value ? (d.labelZh || stableDigit) : stableDigit);
      u.lang = "zh-CN";
      window.speechSynthesis.speak(u);
    }
  }
};

const onPickImage = async (uploadFile) => {
  imgLoading.value = true;
  try {
    const fd = new FormData();
    fd.append("file", uploadFile.raw);
    appendFormParams(fd);
    fd.append("draw", "1");
    const res = await handposeApi.estimate(fd);
    const d = res.data || {};
    imgResult.value = d.imageBase64 || "";
    applyDisplayFromResponse(d);
    if (isCsl.value) {
      if (!(d.detections || []).length) ElMessage.info("未检测到手语手势");
    } else if (!(d.hands || []).length) {
      ElMessage.info("未检测到手部");
    }
  } catch (e) {
    ElMessage.error(e.message || "识别失败");
  } finally {
    imgLoading.value = false;
  }
};

const copySeq = async () => {
  try {
    await navigator.clipboard.writeText(digitSeq.value.join(" "));
    ElMessage.success("已复制");
  } catch {
    ElMessage.warning("复制失败");
  }
};

listDevices();
loadRecognizers();

onBeforeUnmount(() => {
  stop();
});
</script>

<style scoped>
.handpose-page { display: flex; flex-direction: column; gap: 12px; }
.card-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.card-head-left { display: flex; align-items: center; gap: 8px; }
.card-title { font-size: 15px; font-weight: 650; color: #2c3e57; }
.card-help { color: #a0aec0; cursor: help; font-size: 16px; }
.card-help:hover { color: #409eff; }
.help-pop { max-width: 320px; line-height: 1.6; }
.help-pop p { margin: 0 0 6px; }
.cfg-form :deep(.el-form-item) { margin-bottom: 8px; }
.cfg-form :deep(.el-form-item__label) { padding-bottom: 4px; font-size: 12px; color: #7a8aa5; }
.cfg-form :deep(.el-select) { width: 100%; }
.src-pick { display: flex; align-items: center; gap: 8px; width: 100%; }
.src-pick .el-select { flex: 1; }
.hint-inline { font-size: 12px; color: #909399; }

.cam-stage {
  position: relative; background: #0b1220; border-radius: 8px; overflow: hidden;
  min-height: 360px; display: flex; align-items: center; justify-content: center;
}
.cam-media { width: 100%; max-height: 62vh; display: block; object-fit: contain; background: #000; }
.cam-overlay {
  position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%);
  max-width: 100%; max-height: 62vh; width: auto; height: auto; pointer-events: none;
}
.stage-placeholder {
  position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
  color: #94a3b8; font-size: 14px; pointer-events: none;
}
.img-stage { min-height: 360px; display: flex; align-items: center; justify-content: center; }
.result-img { max-width: 100%; max-height: 62vh; border-radius: 8px; }

.digit-big {
  font-size: 96px; font-weight: 800; line-height: 1.1; text-align: center;
  color: #1f6feb; font-variant-numeric: tabular-nums;
}
.digit-big.digit-dual { font-size: 84px; letter-spacing: 0.02em; }
.digit-big.digit-csl { font-size: 72px; letter-spacing: 0.04em; }
.digit-big.digit-none { color: #c0c4cc; }
.digit-sub { text-align: center; color: #7a8aa5; font-size: 13px; margin-bottom: 10px; }
.hand-chips { display: flex; flex-direction: column; gap: 8px; }
.hand-chip { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.gesture-zh { font-size: 12px; color: #606266; min-width: 72px; }
.finger-dots { display: inline-flex; gap: 4px; }
.finger-dot {
  width: 12px; height: 12px; border-radius: 50%; background: #e4e7ed; display: inline-block;
}
.finger-dot.on { background: #409eff; }
.seq-box {
  min-height: 48px; padding: 8px 10px; background: #f5f7fa; border-radius: 6px;
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
}
.seq-digit {
  min-width: 34px; height: 34px; border-radius: 6px; background: #1f6feb; color: #fff;
  font-size: 18px; font-weight: 700; display: inline-flex; align-items: center; justify-content: center;
  padding: 0 8px;
}
.seq-actions { margin-top: 8px; display: flex; gap: 8px; }
</style>
