# VoxCPM2 模型集成 — 设计文档

**日期：** 2026-06-26
**作者：** Claude (brainstorming)
**状态：** 待评审

## 1. 背景与目标

将 [openbmb/VoxCPM2](https://huggingface.co/openbmb/VoxCPM2)（2.29B 参数 diffusion TTS，
apache-2.0，多语言）集成到项目，作为新的文本转语音引擎。暴露其三种能力：

- **纯 TTS**：文本 → 语音
- **零样本音色克隆**：参考音频(+其文本) → 用该音色读目标文本
- **音色设计（voice design）**：文本开头括号写自然语言描述，如 `(年轻女声，温柔)你好…`
  —— 无需特殊处理，括号描述即文本的一部分。

复用现有 TTS 引擎模式（已有 cosyvoice / vibevoice / sherpa-onnx / transformers 四引擎，按
`m.library` 分派）与前端 `tts/index.vue` 页面。

**模型变体**：本期主用 `openbmb/VoxCPM2`（用户指定）。集成不绑定特定权重——凡 `library=voxcpm`
的目录模型均可用，用户可在「模型管理」拉取 2.29B 或 0.5B 自选。

非目标（YAGNI）：不改现有四引擎；不做流式合成（`generate_streaming`）；不做独立页面；
不新增数据库字段。

## 2. 总体流程

```
模型管理新增 VoxCPM 模型（library=voxcpm, task=text-to-speech, sourceUrl=HF 链接）
  → 点「拉取」→ 现有 fetch 逻辑（is_dir_model=True）snapshot 整库到 uploads/models/<key>/
  → 文本转语音页选中该模型
  → 纯TTS：输入文本（可含括号音色描述）→ POST /tts
     克隆：开「启用音色克隆」→ 传参考音频+文本+目标文本 → POST /tts-clone
  → 后端按 library=voxcpm 分派 VoxCPM 推理 → 返回 wav(base64)+sampleRate
  → 前端播放 / 下载 WAV
```

拉取逻辑**无需改动**：`fetch_weight` 用 `is_dir_model = (library or "ultralytics") != "ultralytics"`，
`voxcpm` 自动按整目录 `snapshot_download`。

## 3. 后端设计

### 3.1 `inference.py` 新增（沿用 cosyvoice/vibevoice 写法）

**`_get_voxcpm(model_dir)`** — 加载/缓存：
- 模块级 `_voxcpm_cache = {}`（model_dir → VoxCPM 实例）。
- `from voxcpm import VoxCPM`；失败抛 `RuntimeError("VoxCPM 本地推理需安装 voxcpm 库：pip install voxcpm")`。
- `VoxCPM.from_pretrained(model_dir, load_denoiser=False)`（关降噪器，省依赖/提速）。

**`synthesize_speech_voxcpm(model_dir, text, cfg_value=2.0, inference_timesteps=10)`** — 纯 TTS + 音色设计：
- `model = _get_voxcpm(model_dir)`
- `wav = model.generate(text=text, cfg_value=cfg_value, inference_timesteps=inference_timesteps)`
- `sr = model.tts_model.sample_rate`（48000）
- `soundfile.write` 到内存 BytesIO（wav 格式）→ base64。
- 返回 `{"audio": <base64>, "sampleRate": sr, "speaker": None}`。

**`synthesize_speech_voxcpm_clone(model_dir, text, prompt_text, prompt_path)`** — 克隆：
- `wav = model.generate(text=text, prompt_wav_path=prompt_path, prompt_text=prompt_text,
  cfg_value=2.0, inference_timesteps=10)`
- 其余同上。返回 `{"audio", "sampleRate", "speaker": None}`。

复用现有 wav→base64 辅助（参照 cosyvoice/melotts 已有写法；若已有公共函数则复用，否则就地 `soundfile.write(BytesIO, wav, sr, format="WAV")`）。

### 3.2 `routes/ai_model.py` 改动

**`tts_route`**（约 461-494 行）新增分支：
```python
elif (m.library or "") == "voxcpm":
    from inference import synthesize_speech_voxcpm
    result = synthesize_speech_voxcpm(path, text)
```

**`tts_clone_route`**（约 497-535 行）改为按 library 分派：
```python
if (m.library or "") == "voxcpm":
    from inference import synthesize_speech_voxcpm_clone
    result = synthesize_speech_voxcpm_clone(path, text, prompt_text, prompt_path)
else:
    from inference import synthesize_speech_v2
    result = synthesize_speech_v2(path, text, prompt_text, prompt_path)
```

**`tts_speakers_route`**：voxcpm 无预置音色 → 落入现有默认 `return jsonify(code=0, data=[])`，无需改。

## 4. 前端设计

### 4.1 `model/index.vue`
- 推理库下拉（约 97-106 行）加：
  `<el-option label="voxcpm（语音合成/克隆/音色设计）" value="voxcpm" />`
- `LIB_TASK` 映射（约 269-271 行）加：`"voxcpm": "text-to-speech"`。

### 4.2 `tts/index.vue`
- `loadModels` 过滤（约 116-119 行）加 `m.library === 'voxcpm'`。
- 新增响应式 `useClone = ref(false)`（仅 voxcpm 用的克隆开关）。
- `isClone` 改为：
  `(currentModel.library === 'cosyvoice' && version === 'v2') || (currentModel.library === 'voxcpm' && useClone.value)`
- 仅当 `currentModel.library === 'voxcpm'` 时显示「启用音色克隆」开关（`el-switch`）。
- voxcpm 模型时文本框 `placeholder` 提示音色设计语法：
  `输入文本；可在开头用括号描述音色，如「(年轻女声，温柔)你好…」`
- 切换模型时重置 `useClone=false`。

## 5. 容错与降级

- 推理异常：`tts_route` / `tts_clone_route` 现有 `try/except` 统一捕获 → `code:500,
  message="合成失败：{e}"`。VoxCPM 分支沿用，无新增。
- 模型未拉取权重：现有 `_abs_model_path` 检查 → 400「请先拉取」。
- `voxcpm` 库未安装：`_get_voxcpm` 内 `try import` 抛带提示 `RuntimeError`，经 500 回传。
  voxcpm 未装时整站不受影响，仅该模型合成报错（与其他引擎隔离一致）。
- 克隆缺参考音频/文本：现有 `tts_clone_route` 校验 → 400。
- CPU 慢：复用 `useInferProgress` 进度条；TTS 接口已是长超时模式。

## 6. 依赖风险（重点）

`pip install voxcpm` 可能拉动 torch/torchaudio，与项目锁定的 `torch==2.11.0` +
funasr / transformers / sherpa-onnx 链冲突。

**全局约束**：安装 voxcpm 后**必须验证** `torch.__version__` 仍为 `2.11.0`，且现有
ASR/TTS 引擎仍可导入（`import app` 冒烟）。若 voxcpm 强制升级 torch，则记录冲突并回报，
**不擅自降级**其他依赖（交由人决定）。

## 7. 测试策略

大模型 + 权重依赖使纯逻辑单测意义有限。验证手段：
1. voxcpm 库 import 冒烟：`python -c "import voxcpm"`。
2. 后端 import 冒烟：`python -c "import app"`（确认新分支不破坏导入）。
3. torch 版本校验：`python -c "import torch; print(torch.__version__)"` == 2.11.0。
4. 真实拉取 VoxCPM2 后手动合成三条：纯 TTS / 音色设计（括号）/ 克隆。
5. 前端 `npm run build` 通过 + 页面手动验证（开关切换、占位提示、播放/下载）。

无新增 pytest 纯逻辑模块。

## 8. 验收标准

1. 「模型管理」可新增 library=voxcpm、task=text-to-speech 的模型并成功拉取 VoxCPM2 权重。
2. 文本转语音页可选中该模型，纯 TTS 合成出 48kHz 语音并播放/下载。
3. 文本开头括号音色描述生效（音色设计）。
4. 「启用音色克隆」开关开启后，上传参考音频+文本可克隆音色合成。
5. voxcpm 库未安装时合成报错信息明确，其余功能不受影响。
6. 安装 voxcpm 后 torch 仍为 2.11.0，现有 ASR/TTS 引擎不被破坏。
