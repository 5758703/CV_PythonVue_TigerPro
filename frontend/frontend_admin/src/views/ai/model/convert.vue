<template>
  <div class="convert-page">
    <el-card shadow="never" class="intro-card">
      <div class="intro-hd">
        <span class="intro-title">模型格式转换</span>
        <el-tag size="small" type="info" effect="plain">YOLO / Ultralytics</el-tag>
      </div>
      <div class="intro-desc">
        选择或上传权重文件，指定输出格式与保存位置后一键转换。
        支持 <b>pt → onnx / TorchScript / OpenVINO / NCNN / TensorRT</b>，以及 <b>onnx → OpenVINO</b>。
        部署格式无法还原为可训练的 .pt。
      </div>
    </el-card>

    <el-row :gutter="16">
      <el-col :xs="24" :lg="14">
        <el-card shadow="never" class="form-card">
          <el-form label-width="110px" :disabled="running" @submit.prevent>
            <el-form-item label="输入来源">
              <el-radio-group v-model="sourceMode" @change="onSourceModeChange">
                <el-radio-button value="model">已纳管模型</el-radio-button>
                <el-radio-button value="upload">上传文件</el-radio-button>
                <el-radio-button value="path">服务器路径</el-radio-button>
              </el-radio-group>
            </el-form-item>

            <el-form-item v-if="sourceMode === 'model'" label="选择模型">
              <el-select
                v-model="modelId"
                filterable
                clearable
                placeholder="选择带本地权重的模型"
                style="width: 100%"
                @change="onModelChange"
              >
                <el-option
                  v-for="m in modelOptions"
                  :key="m.id"
                  :label="`${m.modelName}（${m.modelKey}）`"
                  :value="m.id"
                />
              </el-select>
              <div v-if="weightHint" class="field-hint">{{ weightHint }}</div>
            </el-form-item>

            <el-form-item v-else-if="sourceMode === 'upload'" label="权重文件">
              <el-upload
                drag
                :auto-upload="false"
                :limit="1"
                accept=".pt,.pth,.onnx"
                :on-change="onFileChange"
                :on-remove="onFileRemove"
                :file-list="fileList"
              >
                <div class="upload-inner">
                  <el-icon :size="28"><UploadFilled /></el-icon>
                  <div>拖拽或点击上传 .pt / .pth / .onnx</div>
                </div>
              </el-upload>
            </el-form-item>

            <el-form-item v-else label="服务器路径">
              <el-input
                v-model="serverPath"
                placeholder="相对 uploads/，如 models/xxx/best.pt"
                clearable
                @change="refreshFormats"
              />
              <div class="field-hint">须位于后端 uploads 目录内</div>
            </el-form-item>

            <el-form-item label="输出格式">
              <el-select v-model="target" placeholder="选择目标格式" style="width: 100%">
                <el-option
                  v-for="f in formats"
                  :key="f.value"
                  :label="f.label + (f.recommended ? '（推荐）' : '')"
                  :value="f.value"
                >
                  <div class="fmt-opt">
                    <span>{{ f.label }}</span>
                    <el-tag v-if="f.recommended" size="small" type="success" effect="plain">推荐</el-tag>
                    <el-tag v-if="f.requiresGpu" size="small" type="warning" effect="plain">需 GPU</el-tag>
                  </div>
                </el-option>
              </el-select>
              <div v-if="selectedFormat" class="field-hint">{{ selectedFormat.note }}</div>
            </el-form-item>

            <el-form-item label="输出位置">
              <el-radio-group v-model="outMode">
                <el-radio value="sibling">与源文件同目录</el-radio>
                <el-radio value="converted">统一目录 models/_converted/</el-radio>
                <el-radio value="custom">自定义子目录</el-radio>
              </el-radio-group>
              <div v-if="sourceMode === 'upload'" class="field-hint">
                上传文件默认写入 models/_converted/（同目录模式会自动切换）
              </div>
            </el-form-item>

            <el-form-item v-if="outMode === 'custom'" label="子目录">
              <el-input
                v-model="customSubdir"
                placeholder="相对 models/，如 my-exports/yolo11"
                clearable
              />
            </el-form-item>

            <el-divider content-position="left">导出参数</el-divider>

            <el-form-item label="输入尺寸">
              <el-input-number v-model="opts.imgsz" :min="320" :max="1280" :step="32" />
              <span class="field-hint inline">imgsz</span>
            </el-form-item>
            <el-form-item label="动态输入">
              <el-switch v-model="opts.dynamic" />
              <span class="field-hint inline">ONNX 任意分辨率（与 half 互斥）</span>
            </el-form-item>
            <el-form-item label="半精度">
              <el-switch v-model="opts.half" :disabled="opts.dynamic" />
              <span class="field-hint inline">FP16 缩小体积</span>
            </el-form-item>
            <el-form-item v-if="target === 'onnx'" label="ONNX opset">
              <el-input-number v-model="opts.opset" :min="11" :max="17" />
            </el-form-item>

            <el-form-item>
              <el-button type="primary" :icon="Switch" :loading="running" :disabled="!canStart" @click="startConvert">
                {{ running ? '转换中…' : '开始转换' }}
              </el-button>
              <el-button :disabled="running" @click="resetForm">重置</el-button>
            </el-form-item>
          </el-form>

          <div v-if="running" class="progress-box">
            <el-progress :percentage="100" :indeterminate="true" :duration="2.5" :show-text="false" />
            <div class="field-hint">正在转换（{{ elapsed }}s）… 大模型可能需要数分钟</div>
          </div>
          <el-alert v-if="error" type="error" :closable="false" show-icon class="result-alert" :title="error" />
          <el-alert
            v-if="done"
            type="success"
            :closable="false"
            show-icon
            class="result-alert"
            :title="`已生成 ${outputName}${outputSize ? `（${fmtSize(outputSize)}）` : ''}`"
          >
            <template v-if="outputPath" #default>
              <div class="out-path">{{ outputPath }}</div>
            </template>
          </el-alert>
        </el-card>
      </el-col>

      <el-col :xs="24" :lg="10">
        <el-card shadow="never" class="help-card">
          <template #header>支持的转换路径</template>
          <el-table :data="allFormats" size="small" stripe border>
            <el-table-column prop="label" label="目标" width="120" />
            <el-table-column label="源格式" min-width="100">
              <template #default="{ row }">{{ (row.sources || []).join(' / ') }}</template>
            </el-table-column>
            <el-table-column prop="note" label="说明" min-width="160" show-overflow-tooltip />
          </el-table>
          <el-alert
            class="help-alert"
            type="info"
            :closable="false"
            show-icon
            title="TensorRT(.engine) 需本机 CUDA + TensorRT；无 GPU 时请选 ONNX 或 OpenVINO。"
          />
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import { Switch, UploadFilled } from "@element-plus/icons-vue";
import { modelApi } from "../../../api/ai";

const sourceMode = ref("model");
const modelId = ref(null);
const modelOptions = ref([]);
const serverPath = ref("");
const uploadFile = ref(null);
const fileList = ref([]);
const formats = ref([]);
const allFormats = ref([]);
const target = ref("onnx");
const outMode = ref("sibling");
const customSubdir = ref("");
const opts = reactive({ imgsz: 640, dynamic: false, half: false, opset: 12 });
const weightHint = ref("");

const running = ref(false);
const error = ref("");
const done = ref(false);
const elapsed = ref(0);
const outputName = ref("");
const outputPath = ref("");
const outputSize = ref(0);
let timer = null;

const selectedFormat = computed(() => formats.value.find((f) => f.value === target.value));
const canStart = computed(() => {
  if (!target.value) return false;
  if (sourceMode.value === "model") return !!modelId.value;
  if (sourceMode.value === "upload") return !!uploadFile.value;
  return !!(serverPath.value || "").trim();
});

const fmtSize = (n) => {
  if (n == null || n < 0) return "-";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
};

const stopTimer = () => {
  if (timer) clearInterval(timer);
  timer = null;
};

const loadModels = async () => {
  const res = await modelApi.options();
  modelOptions.value = res.data || [];
};

const loadAllFormats = async () => {
  const res = await modelApi.convertFormats();
  allFormats.value = res.data || [];
  if (!formats.value.length) formats.value = allFormats.value;
};

const refreshFormats = async (sourceExt) => {
  let src = sourceExt || "";
  if (!src && sourceMode.value === "path" && serverPath.value) {
    const m = serverPath.value.match(/(\.[a-z0-9]+)$/i);
    src = m ? m[1] : "";
  }
  if (!src && sourceMode.value === "upload" && uploadFile.value?.name) {
    const m = uploadFile.value.name.match(/(\.[a-z0-9]+)$/i);
    src = m ? m[1] : "";
  }
  const res = await modelApi.convertFormats(src ? { source: src } : undefined);
  formats.value = res.data || [];
  if (formats.value.length && !formats.value.some((f) => f.value === target.value)) {
    target.value = formats.value.find((f) => f.recommended)?.value || formats.value[0].value;
  }
};

const onSourceModeChange = () => {
  error.value = "";
  done.value = false;
  weightHint.value = "";
  if (sourceMode.value === "upload") {
    outMode.value = "converted";
    refreshFormats(uploadFile.value?.name?.match(/(\.[a-z0-9]+)$/i)?.[1]);
  } else if (sourceMode.value === "model" && modelId.value) {
    onModelChange(modelId.value);
  } else {
    refreshFormats();
  }
};

const onModelChange = async (id) => {
  weightHint.value = "";
  if (!id) {
    refreshFormats();
    return;
  }
  const res = await modelApi.weightInfo(id);
  const d = res.data || {};
  const parts = [];
  if (d.pt) parts.push(`pt ${fmtSize(d.pt.size)}`);
  if (d.onnx) parts.push(`onnx ${fmtSize(d.onnx.size)}`);
  if (d.torchscript) parts.push(`torchscript ${fmtSize(d.torchscript.size)}`);
  if (d.openvino) parts.push(`openvino ${fmtSize(d.openvino.size)}`);
  weightHint.value = parts.length ? `本地权重：${parts.join(" · ")}` : "未检测到可用权重";
  formats.value = d.formats || [];
  if (!formats.value.length) await refreshFormats(d.pt ? ".pt" : d.onnx ? ".onnx" : "");
  if (formats.value.length && !formats.value.some((f) => f.value === target.value)) {
    target.value = formats.value.find((f) => f.recommended)?.value || formats.value[0].value;
  }
};

const onFileChange = (file) => {
  uploadFile.value = file.raw || file;
  fileList.value = [file];
  const m = (file.name || "").match(/(\.[a-z0-9]+)$/i);
  refreshFormats(m ? m[1] : "");
};

const onFileRemove = () => {
  uploadFile.value = null;
  fileList.value = [];
  refreshFormats();
};

const resetForm = () => {
  stopTimer();
  running.value = false;
  error.value = "";
  done.value = false;
  elapsed.value = 0;
  outputName.value = "";
  outputPath.value = "";
  outputSize.value = 0;
  modelId.value = null;
  serverPath.value = "";
  uploadFile.value = null;
  fileList.value = [];
  weightHint.value = "";
  target.value = "onnx";
  outMode.value = sourceMode.value === "upload" ? "converted" : "sibling";
  customSubdir.value = "";
  opts.imgsz = 640;
  opts.dynamic = false;
  opts.half = false;
  opts.opset = 12;
  refreshFormats();
};

const pollProgress = (jobId) => {
  timer = setInterval(async () => {
    try {
      const p = await modelApi.convertStandaloneProgress(jobId);
      const d = p.data || {};
      elapsed.value += 2;
      if (d.status === "done") {
        stopTimer();
        running.value = false;
        done.value = true;
        outputName.value = d.output || "";
        outputPath.value = d.outputPath || "";
        outputSize.value = d.outputSize || 0;
        elapsed.value = d.elapsed || elapsed.value;
        ElMessage.success("转换完成");
        if (sourceMode.value === "model" && modelId.value) onModelChange(modelId.value);
      } else if (d.status === "error") {
        stopTimer();
        running.value = false;
        error.value = d.error || "转换失败";
      }
    } catch (e) {
      stopTimer();
      running.value = false;
      error.value = e.message || "进度查询失败";
    }
  }, 2000);
};

const startConvert = async () => {
  error.value = "";
  done.value = false;
  running.value = true;
  elapsed.value = 0;
  outputName.value = "";
  outputPath.value = "";
  outputSize.value = 0;

  try {
    let res;
    const payloadBase = {
      target: target.value,
      outMode: sourceMode.value === "upload" && outMode.value === "sibling" ? "converted" : outMode.value,
      customSubdir: customSubdir.value,
      imgsz: opts.imgsz,
      dynamic: opts.dynamic,
      half: opts.half,
      opset: opts.opset,
    };

    if (sourceMode.value === "upload") {
      const fd = new FormData();
      fd.append("file", uploadFile.value);
      Object.entries(payloadBase).forEach(([k, v]) => fd.append(k, v == null ? "" : String(v)));
      res = await modelApi.convertStandalone(fd);
    } else if (sourceMode.value === "model") {
      res = await modelApi.convertStandalone({ ...payloadBase, modelId: modelId.value });
    } else {
      res = await modelApi.convertStandalone({ ...payloadBase, serverPath: serverPath.value.trim() });
    }

    const jobId = res.data?.jobId;
    if (!jobId) throw new Error("无 jobId");
    pollProgress(jobId);
  } catch (e) {
    running.value = false;
    error.value = e.message || "启动失败";
  }
};

onMounted(async () => {
  await Promise.all([loadModels(), loadAllFormats()]);
  await refreshFormats();
});

onBeforeUnmount(() => stopTimer());
</script>

<style scoped>
.convert-page { display: flex; flex-direction: column; gap: 12px; }
.intro-card { margin-bottom: 0; }
.intro-hd { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }
.intro-title { font-size: 16px; font-weight: 600; color: #303133; }
.intro-desc { font-size: 13px; color: #606266; line-height: 1.6; }
.form-card, .help-card { margin-bottom: 12px; }
.field-hint { margin-top: 4px; font-size: 12px; color: #909399; line-height: 1.5; }
.field-hint.inline { margin-left: 10px; margin-top: 0; }
.upload-inner { padding: 12px 0; color: #909399; text-align: center; }
.fmt-opt { display: flex; align-items: center; gap: 8px; }
.progress-box { margin-top: 8px; }
.result-alert { margin-top: 12px; }
.out-path { margin-top: 6px; font-size: 12px; color: #606266; word-break: break-all; }
.help-alert { margin-top: 12px; }
</style>
