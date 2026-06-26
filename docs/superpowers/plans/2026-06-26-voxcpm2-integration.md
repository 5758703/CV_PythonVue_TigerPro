# VoxCPM2 集成 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 集成 openbmb/VoxCPM2 作为新的 TTS 引擎，支持纯 TTS、零样本音色克隆、音色设计，复用现有 `library` 分派与 `tts/index.vue` 页面。

**Architecture:** 后端按 `m.library` 分派，新增 `voxcpm` 分支（`inference.py` 加三个函数、`ai_model.py` 路由加分派）。模型作为 HF 目录模型经现有 fetch 逻辑自动 snapshot 下载，拉取逻辑不改。前端 `model/index.vue` 加库选项、`tts/index.vue` 加可选克隆开关。

**Tech Stack:** 后端 Flask + voxcpm 库（PyTorch，48kHz 输出）+ soundfile。前端 Vue3 + Element Plus。

## Global Constraints

- VoxCPM 推理 API：`from voxcpm import VoxCPM`；`VoxCPM.from_pretrained(model_dir, load_denoiser=False)`；`model.generate(text=..., cfg_value=2.0, inference_timesteps=10[, prompt_wav_path=..., prompt_text=...])` 返回 numpy；采样率 `model.tts_model.sample_rate`（48000）。
- 合成返回结构统一 `{"audio": <base64 wav>, "sampleRate": int, "speaker": None}`（与现有引擎一致）。
- 库分派值：`voxcpm`；任务 `text-to-speech`。
- **现有四引擎（cosyvoice / vibevoice / sherpa-onnx / transformers）及其函数不得改动**，只新增分支。
- 拉取逻辑不改（`fetch_weight` 的 `is_dir_model = library != "ultralytics"` 已覆盖 voxcpm）。
- **依赖约束**：安装 voxcpm 后必须验证 `torch.__version__ == "2.11.0"` 且 `import app` 仍正常；若 voxcpm 强升 torch，STOP 并回报，不擅自降级其他依赖。
- 后端命令在 `backend/` 目录运行。本特性无纯逻辑单测（推理依赖大模型+权重），用 import 冒烟 + 构建 + 手动验证。
- 编辑按代码内容定位锚点，不依赖绝对行号（行号仅作提示）。

---

### Task 1: 后端 VoxCPM 推理函数

**Files:**
- Modify: `backend/inference.py`（文件末尾追加 VoxCPM 段，约第 776 行后）
- Modify: `backend/requirements.txt`（末尾追加 voxcpm）

**Interfaces:**
- Consumes: 模块级 `_lock`（已存在，用于缓存加锁）。
- Produces:
  - `synthesize_speech_voxcpm(model_dir: str, text: str, cfg_value: float = 2.0, inference_timesteps: int = 10) -> dict`
  - `synthesize_speech_voxcpm_clone(model_dir: str, text: str, prompt_text: str, prompt_path: str, cfg_value: float = 2.0, inference_timesteps: int = 10) -> dict`
  - 两者均返回 `{"audio": <base64 wav>, "sampleRate": 48000, "speaker": None}`。

- [ ] **Step 1: 追加依赖**

在 `backend/requirements.txt` 末尾追加：

```
# VoxCPM2 文本转语音 / 音色克隆 / 音色设计（openbmb/VoxCPM2，HF voxcpm 库，48kHz 输出）
voxcpm
```

- [ ] **Step 2: 追加 VoxCPM 推理段**

在 `backend/inference.py` 末尾（`synthesize_speech_melotts` 函数之后）追加：

```python


# ------------------------------------------------------------ VoxCPM2 文本转语音 / 克隆 / 音色设计
_voxcpm_cache = {}  # model_dir -> VoxCPM 实例


def _get_voxcpm(model_dir):
    """加载/缓存 VoxCPM 模型（openbmb/VoxCPM2 等，HF voxcpm 库，CPU/GPU 自适应）。"""
    with _lock:
        if model_dir in _voxcpm_cache:
            return _voxcpm_cache[model_dir]
        try:
            from voxcpm import VoxCPM
        except ImportError as e:
            raise RuntimeError(
                "VoxCPM 本地推理需安装 voxcpm 库：pip install voxcpm") from e
        # load_denoiser=False：关闭可选降噪器，省额外依赖并加速
        model = VoxCPM.from_pretrained(model_dir, load_denoiser=False)
        _voxcpm_cache[model_dir] = model
        return model


def _voxcpm_to_result(model, wav):
    """VoxCPM generate 输出(numpy) -> {audio(base64 wav), sampleRate, speaker}。"""
    import io
    import base64 as _b64
    import numpy as np
    import soundfile as _sf

    arr = np.asarray(wav, dtype=np.float32).squeeze()
    if arr.size == 0:
        raise ValueError("合成结果为空")
    sr = int(model.tts_model.sample_rate)
    buf = io.BytesIO()
    _sf.write(buf, arr, sr, format="WAV")
    return {"audio": _b64.b64encode(buf.getvalue()).decode(), "sampleRate": sr, "speaker": None}


def synthesize_speech_voxcpm(model_dir, text, cfg_value=2.0, inference_timesteps=10):
    """VoxCPM 纯文本转语音（含音色设计：文本开头括号描述即可，无需特殊处理）。"""
    model = _get_voxcpm(model_dir)
    wav = model.generate(text=text, cfg_value=cfg_value,
                         inference_timesteps=inference_timesteps)
    return _voxcpm_to_result(model, wav)


def synthesize_speech_voxcpm_clone(model_dir, text, prompt_text, prompt_path,
                                   cfg_value=2.0, inference_timesteps=10):
    """VoxCPM 零样本音色克隆：参考音频(+其文本) → 用该音色读目标文本。"""
    model = _get_voxcpm(model_dir)
    wav = model.generate(text=text, prompt_wav_path=prompt_path, prompt_text=prompt_text,
                         cfg_value=cfg_value, inference_timesteps=inference_timesteps)
    return _voxcpm_to_result(model, wav)
```

- [ ] **Step 3: import 冒烟（不需安装 voxcpm）**

voxcpm 为函数内惰性导入，`import inference` 不应要求 voxcpm 已安装。

Run（在 `backend/`）: `python -c "import inference; print('ok')"`
Expected: 打印 `ok`，无 ImportError。

- [ ] **Step 4: 后端整体 import 冒烟**

Run（在 `backend/`）: `python -c "import app; print('ok')"`
Expected: 打印 `ok`，无错误。

- [ ] **Step 5: Commit**

```bash
git add backend/inference.py backend/requirements.txt
git commit -m "feat: VoxCPM 推理函数（纯TTS/克隆/音色设计）+ voxcpm 依赖"
```

---

### Task 2: 后端路由分派

**Files:**
- Modify: `backend/routes/ai_model.py`（`tts_route` 与 `tts_clone_route` 两处，按内容定位）

**Interfaces:**
- Consumes: Task 1 的 `synthesize_speech_voxcpm` / `synthesize_speech_voxcpm_clone`；现有 `synthesize_speech_v2`。
- Produces: `POST /<mid>/tts` 与 `POST /<mid>/tts-clone` 支持 `library == "voxcpm"`。

- [ ] **Step 1: tts_route 增 voxcpm 分支**

在 `backend/routes/ai_model.py` 的 `tts_route` 函数内，找到 sherpa-onnx 分支：

```python
        elif (m.library or "") == "sherpa-onnx":
            from inference import synthesize_speech_melotts
            result = synthesize_speech_melotts(path, text)
```

在它之后、`else:`（transformers 默认）之前插入：

```python
        elif (m.library or "") == "voxcpm":
            from inference import synthesize_speech_voxcpm
            result = synthesize_speech_voxcpm(path, text)
```

- [ ] **Step 2: tts_clone_route 改按 library 分派**

在 `tts_clone_route` 函数内，找到现有调用：

```python
    try:
        from inference import synthesize_speech_v2
        result = synthesize_speech_v2(path, text, prompt_text, prompt_path)
```

替换 `try` 块内这两行为按库分派：

```python
    try:
        if (m.library or "") == "voxcpm":
            from inference import synthesize_speech_voxcpm_clone
            result = synthesize_speech_voxcpm_clone(path, text, prompt_text, prompt_path)
        else:
            from inference import synthesize_speech_v2
            result = synthesize_speech_v2(path, text, prompt_text, prompt_path)
```

（保留其后的 `except` / `finally` 不变。）

- [ ] **Step 3: import 冒烟**

Run（在 `backend/`）: `python -c "import app; print('ok')"`
Expected: 打印 `ok`，无错误。

- [ ] **Step 4: Commit**

```bash
git add backend/routes/ai_model.py
git commit -m "feat: tts/tts-clone 路由支持 voxcpm 分派"
```

---

### Task 3: 前端集成（库选项 + TTS 页克隆开关）

**Files:**
- Modify: `frontend/src/views/ai/model/index.vue`（库下拉选项 + LIB_TASK 映射）
- Modify: `frontend/src/views/ai/tts/index.vue`（模型过滤 + 克隆开关 + 占位提示）

**Interfaces:**
- Consumes: 后端 voxcpm 路由（Task 2）。
- Produces: UI 可选 voxcpm 库、TTS 页可对 voxcpm 模型纯合成或开启克隆。

- [ ] **Step 1: model/index.vue 加库选项**

在 `frontend/src/views/ai/model/index.vue` 的推理库 `el-select` 内，找到：

```html
            <el-option label="vibevoice（实时语音合成）" value="vibevoice" />
```

在其后插入：

```html
            <el-option label="voxcpm（语音合成/克隆/音色设计）" value="voxcpm" />
```

- [ ] **Step 2: model/index.vue 加 LIB_TASK 映射**

找到库→任务映射对象中的：

```javascript
  "vibevoice": "text-to-speech",
```

在其后插入：

```javascript
  "voxcpm": "text-to-speech",
```

- [ ] **Step 3: tts/index.vue 模型过滤纳入 voxcpm**

在 `frontend/src/views/ai/tts/index.vue` 的 `loadModels` 内，找到过滤条件：

```javascript
    (m) => (m.library === 'cosyvoice' || m.library === 'transformers' || m.library === 'vibevoice' || m.library === 'sherpa-onnx') &&
      m.task === 'text-to-speech' && m.filePath && m.status === '0'
```

替换为（加入 voxcpm）：

```javascript
    (m) => (m.library === 'cosyvoice' || m.library === 'transformers' || m.library === 'vibevoice' || m.library === 'sherpa-onnx' || m.library === 'voxcpm') &&
      m.task === 'text-to-speech' && m.filePath && m.status === '0'
```

- [ ] **Step 4: tts/index.vue 加克隆开关状态与计算属性**

找到：

```javascript
const promptText = ref('')
```

在其后追加：

```javascript
const useClone = ref(false)  // 仅 voxcpm：是否启用音色克隆
const isVoxcpm = computed(() => currentModel.value?.library === 'voxcpm')
```

找到现有 `isClone` 定义：

```javascript
const isClone = computed(() => currentModel.value?.library === 'cosyvoice' && currentModel.value?.version === 'v2')
```

替换为：

```javascript
const isClone = computed(() =>
  (currentModel.value?.library === 'cosyvoice' && currentModel.value?.version === 'v2') ||
  (isVoxcpm.value && useClone.value)
)
```

- [ ] **Step 5: tts/index.vue 切换模型时重置克隆开关**

找到 `loadSpeakers` 函数定义的起始行：

```javascript
const loadSpeakers = async () => {
  if (!modelId.value) return
```

在 `if (!modelId.value) return` 之后插入一行重置（始终先关克隆开关，避免跨模型残留）：

```javascript
  useClone.value = false
```

- [ ] **Step 6: tts/index.vue 加克隆开关 UI 与音色设计占位提示**

在配置卡 `el-form` 内，找到音色选择项：

```html
        <el-form-item v-if="!isClone && speakers.length" label="音色">
```

在该 `el-form-item` 之前插入克隆开关（仅 voxcpm 显示）：

```html
        <el-form-item v-if="isVoxcpm" label="音色克隆">
          <el-switch v-model="useClone" />
        </el-form-item>
```

然后找到合成文本输入框：

```html
      <el-input v-model="text" type="textarea" :rows="5" maxlength="500" show-word-limit placeholder="输入要合成的文本…" />
```

替换其 `placeholder` 为动态提示（voxcpm 时提示音色设计语法）：

```html
      <el-input v-model="text" type="textarea" :rows="5" maxlength="500" show-word-limit :placeholder="isVoxcpm ? '输入文本；可在开头用括号描述音色，如「(年轻女声，温柔)你好…」' : '输入要合成的文本…'" />
```

- [ ] **Step 7: 构建验证**

Run（在 `frontend/`）: `npx vite build`
Expected: `✓ built`，无编译错误。

- [ ] **Step 8: Commit**

```bash
git add frontend/src/views/ai/model/index.vue frontend/src/views/ai/tts/index.vue
git commit -m "feat: 前端集成 voxcpm 引擎（库选项 + TTS 页可选克隆 + 音色设计提示）"
```

---

### Task 4: 安装 voxcpm 依赖并验证环境

**Files:**
- 无源码改动（环境与验证任务）。

**Interfaces:**
- Consumes: Task 1 的 `requirements.txt` voxcpm 行。
- Produces: 可运行的 voxcpm 库 + 确认未破坏 torch 栈。

- [ ] **Step 1: 记录当前 torch 版本**

Run（在 `backend/`）: `python -c "import torch; print(torch.__version__)"`
Expected: `2.11.0`（作为安装后比对基线）。

- [ ] **Step 2: 安装 voxcpm**

Run（在 `backend/`）: `pip install voxcpm`
Expected: 安装成功。留意输出是否提示卸载/升级 `torch` / `torchaudio` / `torchvision`。

- [ ] **Step 3: 验证 torch 未被改动**

Run（在 `backend/`）: `python -c "import torch; print(torch.__version__)"`
Expected: 仍为 `2.11.0`。

**若不是 2.11.0**：STOP。记录 voxcpm 实际要求的 torch 版本与冲突详情，回报状态 BLOCKED，**不要**降级/改动其他依赖——交由控制者/人决定（升级整套 torch 栈或换 voxcpm 版本）。

- [ ] **Step 4: 验证 voxcpm 与后端可导入**

Run（在 `backend/`）: `python -c "import voxcpm; import app; print('ok')"`
Expected: 打印 `ok`，无错误。

- [ ] **Step 5: 无源码改动则跳过提交**

本任务通常无源码改动（依赖以 requirements.txt 声明、实际安装在环境中）。若 Step 2 产生了需要锁定的版本信息且决定写入 requirements.txt，再单独提交；否则无需提交。

---

## 手动验证（全部任务完成后）

1. 启动后端 + 前端，登录。
2. 「模型管理」新增模型：library=voxcpm，task=text-to-speech，来源 `https://huggingface.co/openbmb/VoxCPM2`，保存后点「拉取」（耗时较长，约数 GB）。
3. 「文本转语音」页选中该模型：
   - 纯 TTS：输入中文/英文文本 → 合成 → 播放 48000 Hz 音频、可下载。
   - 音色设计：文本开头加 `(年轻女声，温柔)` → 合成音色随描述变化。
   - 克隆：打开「音色克隆」开关 → 上传 3~10s 参考音频 + 填其文本 → 合成出该音色。
4. 不破坏其他引擎：随便选一个 cosyvoice / melotts 模型仍能正常合成。

---

## Self-Review

**1. Spec coverage：**
- spec §3.1 inference 三函数 → Task 1 ✓（`_get_voxcpm` + `synthesize_speech_voxcpm` + `_voxcpm_clone`）
- spec §3.2 路由 tts_route + tts_clone_route 分派 → Task 2 ✓；tts_speakers voxcpm 返回 []（落入现有默认分支，无需改，spec 已说明）✓
- spec §3.3 requirements voxcpm → Task 1 Step 1 ✓
- spec §4.1 model/index.vue 库选项 + LIB_TASK → Task 3 Step 1-2 ✓
- spec §4.2 tts/index.vue 过滤 + useClone + isClone + 占位 + 重置 → Task 3 Step 3-6 ✓
- spec §5 容错（沿用现有 try/except；voxcpm 未装 RuntimeError）→ Task 1 `_get_voxcpm` ImportError→RuntimeError ✓；路由层无需改 ✓
- spec §6 依赖风险（torch 校验、不擅自降级）→ Task 4 Step 1-3 ✓
- spec §7 测试策略（import 冒烟 / build / 手动）→ 各任务验证步 + 手动验证段 ✓
- spec §8 验收 1-6 → 手动验证段覆盖 ✓

**2. Placeholder scan：** 无 TBD/TODO；所有代码步含完整代码；命令含预期输出。Task 4 Step 5 “可能不提交”是依赖安装任务的真实情况，非占位。

**3. Type consistency：**
- `synthesize_speech_voxcpm(model_dir, text, cfg_value, inference_timesteps)` Task1 定义、Task2 调用（仅传 path, text）一致（其余用默认值）✓
- `synthesize_speech_voxcpm_clone(model_dir, text, prompt_text, prompt_path, ...)` Task1 定义、Task2 调用 `(path, text, prompt_text, prompt_path)` 实参顺序一致 ✓
- 返回结构 `{audio, sampleRate, speaker}` 与前端 `run()` 解析（`d.audio`/`d.sampleRate`/`d.speaker`）一致 ✓
- `useClone` / `isVoxcpm` / `isClone` 前端命名 Task3 各步一致 ✓
