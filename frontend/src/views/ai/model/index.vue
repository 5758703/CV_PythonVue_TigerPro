<template>
  <div>
    <el-card shadow="never" class="search-card">
      <el-form :inline="true" :model="query">
        <el-form-item label="模型名称">
          <el-input v-model="query.modelName" placeholder="模型名称" clearable @keyup.enter="load" />
        </el-form-item>
        <el-form-item label="分类">
          <el-select v-model="query.category" placeholder="全部分类" clearable style="width: 160px;">
            <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="来源">
          <el-select v-model="query.source" placeholder="全部来源" clearable style="width: 150px;" @change="load">
            <el-option label="HuggingFace" value="huggingface" />
            <el-option label="ModelScope" value="modelscope" />
            <el-option label="其他" value="other" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :icon="Search" @click="load">搜索</el-button>
          <el-button :icon="Refresh" @click="reset">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never">
      <div class="toolbar">
        <el-button v-permission="'ai:model:add'" type="primary" :icon="Plus" @click="openAdd">新增模型</el-button>
        <el-button v-permission="'ai:model:remove'" type="danger" :icon="Delete" :disabled="!selectedIds.length" @click="batchRemove">批量删除{{ selectedIds.length ? `（${selectedIds.length}）` : "" }}</el-button>
      </div>

      <el-table :data="rows" v-loading="loading" border stripe @selection-change="onSelect">
        <el-table-column type="selection" width="48" />
        <el-table-column prop="id" label="ID" width="50" />
        <el-table-column prop="modelName" label="模型名称" min-width="130" show-overflow-tooltip />
        <el-table-column label="分类" width="120">
          <template #default="{ row }">
            <el-tag v-if="row.category" effect="dark" :color="categoryColor(row.category)" class="cat-tag">{{ row.category }}</el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column prop="modelKey" label="标识" min-width="150" show-overflow-tooltip />
        <el-table-column label="任务" width="120">
          <template #default="{ row }">
            <el-tag size="small" :type="taskTagType(row.task)">{{ taskLabel(row.task) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="version" label="版本" width="80" />
        <el-table-column label="权重文件" width="130">
          <template #default="{ row }">
            <el-tag v-if="row.filePath" type="success" effect="plain">{{ fmtSize(row.fileSize) }}</el-tag>
            <el-tag v-else type="info" effect="plain">未上传</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="来源" width="150">
          <template #default="{ row }">
            <el-link v-if="row.sourceUrl" :href="row.sourceUrl" target="_blank" :underline="false">
              <el-tag size="small" effect="dark" :color="hubMeta(row.hub).color">{{ hubMeta(row.hub).label }}</el-tag>
            </el-link>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.status === '0' ? 'success' : 'info'">{{ row.status === "0" ? "启用" : "停用" }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="320" fixed="right">
          <template #default="{ row }">
            <el-button v-permission="'ai:model:query'" link type="success" :icon="VideoPlay" :disabled="!row.filePath" @click="openTest(row)">测试</el-button>
            <el-button v-if="row.filePath" v-permission="'ai:model:download'" link type="primary" :icon="Download" @click="downloadWeight(row)">下载</el-button>
            <el-button v-else-if="row.sourceUrl" v-permission="'ai:model:add'" link type="warning" :icon="Download" :loading="fetchingId === row.id" @click="fetchWeight(row)">拉取权重</el-button>
            <el-button v-permission="'ai:model:edit'" link type="primary" :icon="Edit" @click="openEdit(row)">修改</el-button>
            <el-button v-permission="'ai:model:remove'" link type="danger" :icon="Delete" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination class="pager" layout="total, prev, pager, next" :total="total" v-model:current-page="query.pageNum" v-model:page-size="query.pageSize" @current-change="load" />
    </el-card>

    <el-dialog v-model="dialog" :title="form.id ? '修改模型' : '新增模型'" width="560px" @closed="resetForm">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
        <el-form-item label="模型名称" prop="modelName">
          <el-input v-model="form.modelName" placeholder="如：烟雾探测" />
        </el-form-item>
        <el-form-item label="分类" prop="category">
          <el-select v-model="form.category" placeholder="选择或输入分类" filterable allow-create default-first-option style="width: 100%;">
            <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="标识" prop="modelKey">
          <el-input v-model="form.modelKey" placeholder="唯一标识，如：fire-smoke-detection" />
        </el-form-item>
        <el-form-item label="推理库" prop="library">
          <el-select v-model="form.library" style="width: 100%" @change="onLibChange">
            <el-option label="ultralytics（YOLO 单文件权重）" value="ultralytics" />
            <el-option label="transformers（HF 模型目录）" value="transformers" />
            <el-option label="funasr（语音识别）" value="funasr" />
            <el-option label="funasr-onnx（语音识别 onnx）" value="funasr-onnx" />
            <el-option label="sherpa-onnx（语音合成 onnx）" value="sherpa-onnx" />
            <el-option label="cosyvoice（语音合成/克隆）" value="cosyvoice" />
            <el-option label="vibevoice（实时语音合成）" value="vibevoice" />
            <el-option label="voxcpm（语音合成/克隆/音色设计）" value="voxcpm" />
            <el-option label="linly（数字人）" value="linly" />
          </el-select>
        </el-form-item>
        <el-form-item label="任务类型" prop="task">
          <el-select v-model="form.task" style="width: 100%" filterable>
            <el-option label="目标检测 object-detection" value="object-detection" />
            <el-option label="姿态估计 pose-estimation" value="pose-estimation" />
            <el-option label="图像分类 image-classification" value="image-classification" />
            <el-option label="文本分类 text-classification" value="text-classification" />
            <el-option label="零样本分类 zero-shot-classification" value="zero-shot-classification" />
            <el-option label="完形填空 fill-mask" value="fill-mask" />
            <el-option label="翻译 translation" value="translation" />
            <el-option label="摘要 summarization" value="summarization" />
            <el-option label="文本生成 text-generation" value="text-generation" />
            <el-option label="命名实体识别 token-classification" value="token-classification" />
            <el-option label="问答 question-answering" value="question-answering" />
            <el-option label="语音识别 automatic-speech-recognition" value="automatic-speech-recognition" />
            <el-option label="语音合成 text-to-speech" value="text-to-speech" />
            <el-option label="数字人 talking-head" value="talking-head" />
          </el-select>
        </el-form-item>
        <el-form-item label="版本">
          <el-input v-model="form.version" placeholder="v1" />
        </el-form-item>
        <el-form-item label="来源地址">
          <el-input v-model="form.sourceUrl" placeholder="HuggingFace 等模型来源链接" />
        </el-form-item>
        <el-form-item label="权重文件">
          <el-upload :show-file-list="false" :before-upload="beforeUpload" :http-request="doUpload" accept=".pt,.pth,.onnx,.engine,.weights">
            <el-button :icon="UploadFilled" :loading="uploading">上传权重</el-button>
          </el-upload>
          <div v-if="form.filePath" class="file-hint">已上传：{{ form.filePath }}（{{ fmtSize(form.fileSize) }}）</div>
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="2" maxlength="500" show-word-limit />
        </el-form-item>
        <el-form-item label="状态">
          <el-switch v-model="form.status" active-value="0" inactive-value="1" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">确定</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="testDialog" :title="`在线测试 - ${testModel.modelName}`" width="860px" draggable @closed="resetTest">
      <div class="test-bar">
        <el-upload :show-file-list="false" :before-upload="beforeTestImg" :http-request="runDetect" accept="image/*">
          <el-button type="primary" :icon="UploadFilled" :loading="detecting">选择图片并检测</el-button>
        </el-upload>
        <span class="conf-label">置信度阈值</span>
        <el-slider v-model="testConf" :min="0.05" :max="0.95" :step="0.05" style="width: 180px;" />
      </div>

      <el-empty v-if="!testResult && !detecting" description="选择一张图片进行检测" />
      <div v-loading="detecting" class="test-body">
        <div v-if="testResult" class="result-grid">
          <div class="result-img stage" ref="tStageEl">
            <img ref="tImgEl" :src="testImgSrc" class="stage-img" @load="tSync" />
            <canvas ref="tOverlayEl" class="stage-canvas" @click="tCanvasClick"></canvas>
          </div>
          <div class="result-info">
            <div class="info-head">
              <el-alert :title="`检测到 ${testResult.count} 个目标（点击行/框联动高亮）`" type="success" :closable="false" />
              <el-button v-if="resultImgSrc" link type="primary" :icon="ZoomIn" @click="tViewer = true">放大</el-button>
            </div>
            <el-table
              ref="tTableRef"
              :data="testResult.detections"
              size="small"
              border
              max-height="320"
              class="det-table"
              highlight-current-row
              :row-class-name="tRowClass"
              @row-click="tRowClick"
            >
              <el-table-column type="index" label="#" width="48" />
              <el-table-column label="类别" min-width="120">
                <template #default="{ row, $index }">
                  <span class="cls-dot" :style="{ background: tBoxColor($index) }"></span>
                  {{ row.className }}
                </template>
              </el-table-column>
              <el-table-column label="置信度" width="100">
                <template #default="{ row }">{{ (row.confidence * 100).toFixed(1) }}%</template>
              </el-table-column>
              <el-table-column label="坐标(x1,y1,x2,y2)" min-width="170">
                <template #default="{ row }">{{ row.bbox.join(", ") }}</template>
              </el-table-column>
            </el-table>
          </div>
        </div>
      </div>
      <el-image-viewer v-if="tViewer && resultImgSrc" :url-list="[resultImgSrc]" hide-on-click-modal @close="tViewer = false" />
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, nextTick, onMounted, onBeforeUnmount } from "vue";
import { useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import { Search, Refresh, Plus, Edit, Delete, UploadFilled, Download, VideoPlay, ZoomIn } from "@element-plus/icons-vue";

import { modelApi } from "../../../api/ai";

const router = useRouter();

const loading = ref(false);
const saving = ref(false);
const uploading = ref(false);
const rows = ref([]);
const total = ref(0);
const categories = ref([]);
const query = reactive({ pageNum: 1, pageSize: 10, modelName: "", category: "", source: "" });

const HUB_META = {
  huggingface: { label: "HuggingFace", color: "#ff9d00" },
  modelscope: { label: "ModelScope", color: "#624aff" },
  other: { label: "其他", color: "#909399" }
};
const hubMeta = (h) => HUB_META[h] || HUB_META.other;

const dialog = ref(false);
const formRef = ref();
const emptyForm = () => ({
  id: null,
  modelName: "",
  category: "",
  modelKey: "",
  task: "object-detection",
  library: "ultralytics",
  version: "v1",
  sourceUrl: "",
  filePath: "",
  fileSize: 0,
  description: "",
  status: "0",
});

// 切库时给个合理的默认任务
const TASK_LABELS = {
  "object-detection": "目标检测",
  "image-classification": "图像分类",
  "text-classification": "文本分类",
  "zero-shot-classification": "零样本分类",
  "fill-mask": "完形填空",
  "translation": "翻译",
  "summarization": "摘要",
  "text-generation": "文本生成",
  "token-classification": "实体识别",
  "question-answering": "问答",
  "automatic-speech-recognition": "语音识别",
  "text-to-speech": "语音合成",
  "talking-head": "数字人",
};
const taskLabel = (t) => TASK_LABELS[t] || t || "目标检测";
const taskTagType = (t) => (t === "text-classification" ? "warning" : t === "image-classification" ? "success" : "");

const LIB_DEFAULT_TASK = {
  ultralytics: "object-detection",
  "funasr": "automatic-speech-recognition",
  "funasr-onnx": "automatic-speech-recognition",
  "sherpa-onnx": "text-to-speech",
  "cosyvoice": "text-to-speech",
  "vibevoice": "text-to-speech",
  "voxcpm": "text-to-speech",
  "linly": "talking-head",
};
const onLibChange = (lib) => {
  if (lib === "transformers" && form.task === "object-detection") form.task = "text-classification";
  else if (LIB_DEFAULT_TASK[lib]) form.task = LIB_DEFAULT_TASK[lib];
};
const form = reactive(emptyForm());

const rules = {
  modelName: [{ required: true, message: "请输入模型名称", trigger: "blur" }],
};

// 分类配色：场景语义优先（烟火=红等），未知分类按 hash 取色板，保证同名同色
const CAT_PALETTE = ["#2f54eb", "#13c2c2", "#722ed1", "#eb2f96", "#52c41a", "#1677ff", "#a0522d"];
const CAT_SEMANTIC = [
  { kw: ["烟", "火", "焰", "fire", "smoke", "火警"], color: "#f56c6c" }, // 红 - 火灾烟雾
  { kw: ["安全", "防护", "ppe", "穿戴", "帽"], color: "#409eff" }, // 蓝 - 安全防护
  { kw: ["电", "漏电", "触电", "electric"], color: "#fa8c16" }, // 橙 - 电气
  { kw: ["入侵", "闯入", "周界", "安防", "intrude"], color: "#9254de" }, // 紫 - 周界安防
  { kw: ["车", "交通", "车辆", "traffic", "vehicle"], color: "#13c2c2" }, // 青 - 交通车辆
];
const categoryColor = (cat) => {
  if (!cat) return "#909399";
  const low = String(cat).toLowerCase();
  for (const s of CAT_SEMANTIC) {
    if (s.kw.some((k) => low.includes(k))) return s.color;
  }
  let h = 0;
  for (let i = 0; i < cat.length; i++) h = (h * 31 + cat.charCodeAt(i)) >>> 0;
  return CAT_PALETTE[h % CAT_PALETTE.length];
};

const fmtSize = (bytes) => {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  let n = bytes;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i++;
  }
  return `${n.toFixed(i ? 1 : 0)} ${units[i]}`;
};

const loadCategories = async () => {
  const res = await modelApi.categories();
  categories.value = res.data || [];
};

const load = async () => {
  loading.value = true;
  try {
    const res = await modelApi.list(query);
    rows.value = res.data.rows;
    total.value = res.data.total;
  } finally {
    loading.value = false;
  }
};

const reset = () => {
  query.modelName = "";
  query.category = "";
  query.source = "";
  query.pageNum = 1;
  load();
};

const resetForm = () => Object.assign(form, emptyForm());

const openAdd = () => {
  resetForm();
  dialog.value = true;
};

const openEdit = (row) => {
  resetForm();
  Object.assign(form, { ...row });
  dialog.value = true;
};

const beforeUpload = (file) => {
  const max = 500 * 1024 * 1024;
  if (file.size > max) {
    ElMessage.error("文件超过 500MB 上限");
    return false;
  }
  return true;
};

const doUpload = async (opt) => {
  uploading.value = true;
  try {
    const fd = new FormData();
    fd.append("file", opt.file);
    fd.append("modelKey", form.modelKey || "");
    const res = await modelApi.upload(fd);
    form.filePath = res.data.filePath;
    form.fileSize = res.data.fileSize;
    ElMessage.success("权重上传成功");
  } finally {
    uploading.value = false;
  }
};

const submit = async () => {
  await formRef.value.validate();
  saving.value = true;
  try {
    if (form.id) await modelApi.update(form);
    else await modelApi.add(form);
    ElMessage.success("保存成功");
    dialog.value = false;
    load();
    loadCategories();
  } finally {
    saving.value = false;
  }
};

const remove = async (row) => {
  await ElMessageBox.confirm(`确定删除模型「${row.modelName}」？`, "提示", { type: "warning" });
  await modelApi.remove(row.id);
  ElMessage.success("删除成功");
  load();
};

const selectedIds = ref([]);
const onSelect = (rows) => {
  selectedIds.value = rows.map((r) => r.id);
};

const batchRemove = async () => {
  await ElMessageBox.confirm(`确定删除选中的 ${selectedIds.value.length} 个模型？`, "提示", { type: "warning" });
  await modelApi.batchRemove(selectedIds.value);
  ElMessage.success("批量删除成功");
  load();
  loadCategories();
};

// ---------------- 权重下载 / 拉取
const fetchingId = ref(null);

const downloadWeight = async (row) => {
  const blob = await modelApi.download(row.id);
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = (row.filePath || "weight").split("/").pop();
  a.click();
  URL.revokeObjectURL(url);
};

const fetchWeight = async (row) => {
  fetchingId.value = row.id;
  try {
    await modelApi.fetchWeight(row.id);
    ElMessage.success("权重拉取成功");
    load();
  } finally {
    fetchingId.value = null;
  }
};

// ---------------- 在线测试
const testDialog = ref(false);
const detecting = ref(false);
const testConf = ref(0.25);
const testModel = reactive({ id: null, modelName: "" });
const testResult = ref(null);
const testImgSrc = ref("");
const tStageEl = ref(null);
const tImgEl = ref(null);
const tOverlayEl = ref(null);
const tTableRef = ref(null);
const tActive = ref(-1);
const tViewer = ref(false);

const T_PALETTE = ["#67c23a", "#409eff", "#e6a23c", "#9254de", "#13c2c2", "#fa8c16", "#eb2f96", "#2f54eb"];
const T_HIGHLIGHT = "#ff1744";
const tBoxColor = (i) => T_PALETTE[i % T_PALETTE.length];
const tRowClass = ({ rowIndex }) => (rowIndex === tActive.value ? "active-row" : "");

const resultImgSrc = computed(() => (testResult.value?.imageBase64 ? `data:image/jpeg;base64,${testResult.value.imageBase64}` : ""));

const tSync = () => {
  const img = tImgEl.value;
  const cv = tOverlayEl.value;
  if (!img || !cv || !img.naturalWidth) return;
  cv.width = img.naturalWidth;
  cv.height = img.naturalHeight;
  cv.style.left = `${img.offsetLeft}px`;
  cv.style.top = `${img.offsetTop}px`;
  cv.style.width = `${img.offsetWidth}px`;
  cv.style.height = `${img.offsetHeight}px`;
  tDraw();
};

const tDraw = () => {
  const cv = tOverlayEl.value;
  if (!cv || !testResult.value) return;
  const ctx = cv.getContext("2d");
  ctx.clearRect(0, 0, cv.width, cv.height);
  const lw = Math.max(2, cv.width / 400);
  const fs = Math.max(12, Math.round(cv.width / 55));
  ctx.font = `${fs}px sans-serif`;
  ctx.textBaseline = "top";
  testResult.value.detections.forEach((d, i) => {
    const [x1, y1, x2, y2] = d.bbox;
    const active = i === tActive.value;
    const color = active ? T_HIGHLIGHT : tBoxColor(i);
    ctx.lineWidth = active ? lw * 2 : lw;
    ctx.strokeStyle = color;
    if (active) {
      ctx.fillStyle = "rgba(255,23,68,0.12)";
      ctx.fillRect(x1, y1, x2 - x1, y2 - y1);
    }
    ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
    const label = `${d.className} ${(d.confidence * 100).toFixed(0)}%`;
    const tw = ctx.measureText(label).width + 8;
    ctx.fillStyle = color;
    ctx.fillRect(x1, Math.max(0, y1 - fs - 4), tw, fs + 4);
    ctx.fillStyle = "#fff";
    ctx.fillText(label, x1 + 4, Math.max(0, y1 - fs - 3));
  });
};

const tSetActive = (i) => {
  tActive.value = tActive.value === i ? -1 : i;
  tDraw();
};
const tRowClick = (row) => tSetActive(testResult.value.detections.indexOf(row));
const tCanvasClick = (e) => {
  const cv = tOverlayEl.value;
  const scale = cv.width / cv.clientWidth;
  const x = e.offsetX * scale;
  const y = e.offsetY * scale;
  let hit = -1;
  let best = Infinity;
  testResult.value.detections.forEach((d, i) => {
    const [x1, y1, x2, y2] = d.bbox;
    if (x >= x1 && x <= x2 && y >= y1 && y <= y2) {
      const area = (x2 - x1) * (y2 - y1);
      if (area < best) { best = area; hit = i; }
    }
  });
  tActive.value = hit;
  tDraw();
  if (hit >= 0 && tTableRef.value) tTableRef.value.setCurrentRow(testResult.value.detections[hit]);
};

// 各任务对应的专属测试页（检测类除外，检测类用本页图像弹窗）
const TASK_PAGE = {
  "text-classification": { path: "/ai/text", label: "文本分析" },
  "zero-shot-classification": { path: "/ai/text", label: "文本分析" },
  "fill-mask": { path: "/ai/text", label: "文本分析" },
  "translation": { path: "/ai/generate", label: "文本生成" },
  "summarization": { path: "/ai/generate", label: "文本生成" },
  "text-generation": { path: "/ai/generate", label: "文本生成" },
  "token-classification": { path: "/ai/ner", label: "实体识别" },
  "question-answering": { path: "/ai/qa", label: "智能问答" },
  "image-classification": { path: "/ai/imgcls", label: "图像分类" },
  "automatic-speech-recognition": { path: "/ai/asr", label: "语音识别" },
  "text-to-speech": { path: "/ai/tts", label: "文本转语音" },
  "talking-head": { path: "/ai/talker", label: "数字人合成" }
};

const openTest = (row) => {
  // 非检测任务跳转到对应专属测试页；图像测试弹窗仅用于检测类
  if (row.task && row.task !== "object-detection") {
    const p = TASK_PAGE[row.task];
    if (p) {
      ElMessage.info(`该模型为${p.label}任务，正在前往「${p.label}」页测试`);
      router.push(p.path);
    } else {
      ElMessage.info("该模型任务暂不支持在线测试，请到对应任务页");
    }
    return;
  }
  testResult.value = null;
  tActive.value = -1;
  Object.assign(testModel, { id: row.id, modelName: row.modelName });
  testDialog.value = true;
};

const resetTest = () => {
  testResult.value = null;
  testModel.id = null;
  tActive.value = -1;
  if (testImgSrc.value) URL.revokeObjectURL(testImgSrc.value);
  testImgSrc.value = "";
};

const beforeTestImg = (file) => {
  if (!file.type.startsWith("image/")) {
    ElMessage.error("请选择图片文件");
    return false;
  }
  return true;
};

const runDetect = async (opt) => {
  detecting.value = true;
  try {
    const fd = new FormData();
    fd.append("file", opt.file);
    fd.append("conf", testConf.value);
    if (testImgSrc.value) URL.revokeObjectURL(testImgSrc.value);
    testImgSrc.value = URL.createObjectURL(opt.file);
    const res = await modelApi.detect(testModel.id, fd);
    testResult.value = res.data;
    tActive.value = -1;
    await nextTick();
    tSync();
  } finally {
    detecting.value = false;
  }
};

const onTResize = () => tSync();

onMounted(() => {
  load();
  loadCategories();
  window.addEventListener("resize", onTResize);
});
onBeforeUnmount(() => {
  window.removeEventListener("resize", onTResize);
  if (testImgSrc.value) URL.revokeObjectURL(testImgSrc.value);
});
</script>

<style scoped>
.search-card {
  margin-bottom: 12px;
}
.toolbar {
  margin-bottom: 12px;
}
.pager {
  margin-top: 14px;
  justify-content: flex-end;
}
.file-hint {
  margin-top: 6px;
  font-size: 12px;
  color: #67c23a;
}
.cat-tag {
  color: #fff;
  border: none;
}
.test-bar {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 14px;
}
.conf-label {
  font-size: 13px;
  color: #5a6b87;
}
.test-body {
  min-height: 120px;
}
.result-grid {
  display: flex;
  gap: 16px;
}
.result-img {
  flex: 1 1 55%;
  min-width: 0;
  background: #f4f6fb;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  max-height: 460px;
  overflow: hidden;
}
.result-info {
  flex: 1 1 45%;
  min-width: 0;
}
.result-img.stage {
  position: relative;
}
.stage-img {
  max-width: 100%;
  max-height: 460px;
  object-fit: contain;
  display: block;
}
.stage-canvas {
  position: absolute;
  cursor: pointer;
}
.info-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.info-head :deep(.el-alert) {
  flex: 1;
}
.det-table {
  margin-top: 12px;
}
.det-table :deep(.el-table__row) {
  cursor: pointer;
}
.det-table :deep(.active-row > td.el-table__cell) {
  background: #fff3e0 !important;
}
.cls-dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  margin-right: 6px;
  vertical-align: middle;
}
</style>
