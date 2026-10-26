# MOSS-Music GGUF 的 CPU 分析、项目接入与 CPU ASR 选型

调研日期：2026-10-26。本报告区分上游事实、公开基准、工程估算、本机验证；没有将其他硬件成绩当成本机成绩。

## 结论

MOSS-Music 适合歌曲歌词、音乐描述、乐器/风格分析，普通人声转写应优先使用专用 ASR。它能走 CPU，但 8B 自回归语言模型、额外音频编码器与较长音频上下文，使它不适合作为本项目 CPU 默认 ASR。

本次已接入专用 HOT-Step `ace-caption` CPU 调用链、模型登记、模型管理与语音/音乐下拉、三种输出模式和资源缺失提示。未下载时也能选择并看到说明；资源不全时不允许开始推理。模型生成的纯文本不会被包装成虚假的字幕时间戳。

本机探测：Intel i7-6700HQ，4 核 8 线程，物理内存约 15.82 GiB；探测时可用约 2.04 GiB，F 盘可用约 4.77 GiB。当前磁盘放不下必要权重，内存也不足以容纳其完整工作集。**没有完成本机真实模型的端到端推理、速度或准确率测试。** 测试中的子进程替身只验证接口、参数和失败处理，不代表模型运行成功。

## 模型与兼容性

官方模型由音频编码器、适配器和 Qwen3-8B 语言模型组成，总规模约 9.1B；音频表示约 12.5 token/s，模型通过多层音频特征注入来理解音乐。它输出文字，不是音乐生成模型。歌声识别与日常讲话识别也属于不同分布。[官方项目](https://github.com/OpenMOSS/MOSS-Music)

指定 GGUF 是 HOT-Step 的配套转换。转换作者明确说明：普通 llama.cpp 不能独立完成其音频推理，需要音频塔与 DeepStack 连接。本接入因此直接调用上游专用 `ace-caption`，不把它交给 Transformers ASR 或普通 GGUF 文本加载器。[转换说明](https://huggingface.co/scragnog/MOSS-Music-8B-Instruct-GGUF)

## 文件、磁盘与内存

| 组件 | 仓库标示大小，十进制 GB | 本项目默认下载 |
|---|---:|---|
| moss-lm-q8_0.gguf | 8.71 | 是 |
| moss-aud-f16.gguf | 1.72 | 是 |
| moss-lm-f16.gguf | 16.4 | 否 |
| Q8 组合合计 | 10.43，约 9.71 GiB | 语言模型与音频塔必须同时具备 |
| FP16 组合合计 | 18.12，约 16.88 GiB | 可手动使用，但不适合本机 |

文件大小来自[仓库文件列表](https://huggingface.co/scragnog/MOSS-Music-8B-Instruct-GGUF/tree/main)。不能把下载体积当成峰值内存。还要考虑加载缓冲、计算图、激活、音频投影、KV cache、操作系统、Flask 与项目中其他模型。32 GiB 内存是本报告的部署建议，不是上游测得的最低配置；16 GiB 只能在释放大量内存、短音频、低并发时评估，当前可用 2 GiB 无法支持。

下载器只取必要两文件，避免把约 26.8 GB 的整个仓库全部下载。下载前检查剩余容量；空目录首次下载需约 11 GB 以上可用空间。若要迁移权重位置，可通过 `MODEL_FOLDER` 的部署配置或模型管理中的受管理目录路径绑定，不能只改一个任意外部路径字符串。

## CPU 效率怎样判断

一次请求的墙钟耗时可以拆成：加载权重 + 解码/重采样 + 音频编码 + LLM 输入预处理 + 自回归输出 + 文件处理。本接入每次新建 CLI 进程，因此每次均承担模型加载；操作系统文件缓存可能加快第二次读取，但这不是常驻模型热推理。

1. **音频长度**：30 秒约 375 个音频 token，60 秒约 750，5 分钟约 3750；还会有时间标记、提示和输出 token。这些是按 12.5 Hz 计算的近似值。长音频既增加编码成本，也增加 LLM 的输入与 KV 成本。
2. **输出长度**：语言模型逐 token 生成。短音乐描述通常比完整长歌词更容易控制延迟。输出 256 token 时，假设实测速度分别为 1、2、4 token/s，仅生成部分就需 256、128、64 秒；这些是假设情景，绝不是本机测速结果。
3. **内存带宽与计算**：粗略的带宽上界可写为 `有效带宽 / 每步读取的权重字节数`。若假设每步读取约 8.71 GB，10/20/40 GB/s 的有效带宽分别给出约 1.15/2.30/4.59 token/s 的理想上界。它忽略算术、反量化、缓存和调度等开销，不能当成实际吞吐，也不能推断本机实际内存带宽。
4. **CPU 指令集与量化**：i7-6700HQ 属于较老的 AVX2 平台。Q8 减少文件和权重搬运，仍不代表总延迟固定减半。音频塔保持 FP16，旧 CPU 对半精度存储和计算的处理方式会影响其速度；不能直接套用现代 GPU 或新 CPU 数据。
5. **线程和并发**：先比较 2、4、8 线程；超线程不保证更快。默认 4 线程，环境强制 `GGML_BACKEND=CPU`。同一后端进程只允许运行一个任务，忙时明确返回提示；多 WSGI 进程仍需在部署侧限制总并发，避免每个进程各加载一套约 10 GB 权重。

按[官方配置](https://huggingface.co/OpenMOSS-Team/MOSS-Music-8B-Instruct/blob/main/config.json)，语言模型为 36 层、8 个 KV 头、head_dim 128。仅作为内存核算例子：若 KV 使用 FP16，则每 token 约 `2 × 36 × 8 × 128 × 2 = 144 KiB`；FP32 则翻倍。实际总内存必须测量，不能只加这一项。

本次未找到这套指定 GGUF 在 i7-6700HQ 上可复现的公开端到端 CPU 速度。转换作者的 FP32 CPU 对齐检查属于数值一致性证据，不能证明 CPU 实时速度，也不能证明所有音乐任务准确率。精确 BPM/调性应使用专门 MIR 方法复核。

## 接入方式与使用

模型 key：`moss-music-8b-instruct-gguf`；推理库：`moss-music-gguf`；任务：`audio-text-to-text`。它出现在模型管理和 `/ai/asr` 的语音/音乐模型下拉中。任务分类保留为“音乐理解”，没有冒充普通 ASR。

从项目根目录运行：

```powershell
# 检查缺少哪些文件，不下载、不推理
python backend/scripts/prepare_moss_music.py --check

# 仅登记模型；正常后端启动也会自动幂等登记
python backend/scripts/prepare_moss_music.py --register

# 准备 Windows x64 CPU 运行时，固定 HOT-Step v1.4.2，验证发布包 SHA256
python backend/scripts/prepare_moss_music.py --runtime-only

# 磁盘准备好之后，下载必要权重
python backend/scripts/prepare_moss_music.py --weights-only
```

默认运行时：`backend/runtime/hot-step/ace-caption.exe`。
默认权重：`backend/uploads/models/moss-music-8b-instruct-gguf/`。
运行时安装来源和校验值写入其目录下的 `release.json`，未将第三方引擎源码混入项目源码。

环境项见 `backend/.env.example`：`MOSS_MUSIC_EXECUTABLE`、`MOSS_MUSIC_THREADS`、`MOSS_MUSIC_MAX_SECONDS`、`MOSS_MUSIC_MAX_TOKENS`、`MOSS_MUSIC_TIMEOUT_SECONDS`。默认 60 秒、512 输出 token、30 分钟超时；长于上限的输入会明确拒绝，不会静默截断。普通音视频通过 ffmpeg 转换为 16 kHz 单声道音频；上游引擎保留 400 mel 帧编码窗口。

选中模型后可选 `lyrics`（歌词）、`prose`（音乐描述）、`mm3`（结构化音乐描述）。默认歌词。结果可复制或导出 JSON；本接入未验证可靠的词句级时间戳与说话人分离，因此不开放其 SRT/ASS 导出。

## CPU 语音转文字候选

下面是按本项目用途筛选的候选，不是跨数据集混排的准确率排行榜。先按中文、英语、多语种、流式需求选择，再在同一批录音上比较 CER/WER 与延迟。

| 候选 | CPU 建议路径 | 精度/语言特点 | 速度证据与适用性 | 本项目现状 |
|---|---|---|---|---|
| SenseVoice Small INT8 | funasr-onnx 或 sherpa-onnx | 普通话、粤语、英、日、韩；兼有情绪/事件标签 | 非自回归，优先评估中文 CPU 文件转写 | 已有 `sensevoice-small-onnx` |
| Paraformer-zh | FunASR，生产部署可评估 ONNX INT8 | 普通话和中英混合，可配 VAD/标点/热词 | 非自回归，并行输出；不能把上游 GPU 倍速算成 CPU 数据 | 已有 `paraformer-zh`，当前路径为 FunASR |
| 中文 Streaming Zipformer INT8 | sherpa-onnx 在线 Transducer | 按中文 checkpoint 评估，适合边说边出字 | 原生流式，比离线模型套 VAD 更适合低首字延迟 | 待单独接入在线识别链路 |
| Whisper small INT8 | faster-whisper / CTranslate2 | 多语言，跨语种场景成熟；长静音需 VAD | 有明确 CPU 公开基准，下文列出 | 现有 Whisper 用 Transformers，尚未切到 faster-whisper |
| Whisper base/tiny 量化 | whisper.cpp 或 faster-whisper | 较低资源，中文精度通常须更严格验收 | 适合更低配设备，须评估速度换精度的代价 | 可作为后续低资源档位 |
| Parakeet TDT 0.6B v3 | sherpa-onnx / ONNX，或其配套原生 CPU 实现 | 英语及 25 种欧洲语言；不覆盖中文 | TDT 是高吞吐候选；不能套用其 GPU benchmark 作为 CPU 速度 | 未接入 |
| Moonshine 流式系列 | 官方原生/ONNX CPU runtime | 面向低延迟语音交互；语言随 checkpoint 而定 | 短命令和语音助手值得比较；区分端点等待与计算时间 | 现有 `moonshine-tiny` 是 Transformers 路径，不等于最新流式 runtime |
| Qwen3-ASR 0.6B | 优先核验成熟的原生/ONNX CPU 移植 | 30 种语言、22 种中文方言；复杂口音候选 | 自回归，不能仅因 0.6B 就宣称比 NAR 模型快；官方 GPU 优化成绩不能直接用于 CPU | 未接入 |

依据：[SenseVoice 官方](https://github.com/QwenAudio/SenseVoice)、[SenseVoice ONNX 支持](https://k2-fsa.github.io/sherpa/onnx/sense-voice/index.html)、[Paraformer 官方](https://huggingface.co/funasr/paraformer-zh)、[流式 Zipformer 模型](https://k2-fsa.github.io/sherpa/onnx/pretrained_models/online-transducer/index.html)、[faster-whisper](https://github.com/SYSTRAN/faster-whisper)、[Parakeet 官方](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3)、[Moonshine 官方](https://github.com/moonshine-ai/moonshine)、[Qwen3-ASR 官方](https://huggingface.co/Qwen/Qwen3-ASR-0.6B)。

### 可核验的 CPU 数据

**SenseVoice INT8**：sherpa-onnx 官方 RK3588 CPU 表中，Cortex-A76 的 1/2/3/4 线程 RTF 为 0.099/0.065/0.049/0.049；A55 为 0.436/0.260/0.208/0.175。RTF 越小越快，0.049 约为 20.4 倍实时。这是特定 ARM 平台的上游测试，不能直接推算本机 i7，也不代表完整 VAD/解码/网络链路。[基准表](https://k2-fsa.github.io/sherpa/onnx/sense-voice/pretrained.html#speed-test-on-rk3588-cpu)

**Whisper small**：faster-whisper 官方对 13 分钟音频、i7-12700K、8 线程、beam=5 的旧版对比中，INT8 非批处理为 102 秒、1477 MB，RTF 约 0.131；batch_size=8 为 51 秒、3608 MB，RTF 约 0.065。批处理提高吞吐，同时增加内存，并不等于流式交互延迟减半。该现代桌面 CPU 远强于本机旧移动 CPU，不能承诺同速。[基准与版本条件](https://github.com/SYSTRAN/faster-whisper#small-model-on-cpu)

不能把“70ms / 10s 音频”等未核对硬件、线程和计时边界的宣传语作为本机 CPU 测试；也不能拿 AISHELL 的中文 CER 与另一模型 LibriSpeech 的英文 WER 直接排名。Parakeet 对中文不适用，MOSS-Music 歌词成绩也不能替代普通语音识别评测。

### 本项目建议

1. 中文离线默认优先验收已有 SenseVoice ONNX INT8；Paraformer 做中英混合、热词等任务的对照。
2. 需要真正边说边出字，优先另接中文 Streaming Zipformer；VAD 包住离线模型只属于分段识别。
3. 多语种长录音优先试 faster-whisper small INT8；英语/欧洲语言可加 Parakeet；短命令评估 Moonshine。
4. 方言/口音是主要难点时，把 Qwen3-ASR 0.6B 加入同机精度和速度对照，先核验所选 CPU runtime 的格式、许可和输出一致性。
5. MOSS-Music 保留给音乐/歌声理解，不设为 CPU 通用 ASR 默认模型。

## 如何补齐本机证据

腾出权重磁盘和足够内存后，先用 10–30 秒音频、128 输出 token、4 线程运行：

```powershell
python backend/scripts/benchmark_moss_music_cpu.py --audio sample.wav --runs 3 --threads 4 --max-tokens 128 --output moss_cpu_result.json
```

脚本记录每次调用的总墙钟耗时、音频长度、RTF、文本与参数，不伪造 token/s。然后比较 2/4/8 线程与 10/30/60 秒输入，监测峰值 RSS、可用内存与页面换入；歌词和描述模式分别评测。由于 CLI 每次重新加载，必须如实记录“每次加载”的计时边界。

ASR 验收建议使用同一批 20–50 条真实业务录音，覆盖安静/噪声/远场/快语速/中英混合；中文算 CER，英语算 WER，并固定大小写、标点和数字归一化规则。分别记录冷启动、模型热运行、总 RTF 和 p50/p95；流式还需首字延迟与句尾确认延迟。高精度且快的结论应建立在这套同机数据上。

## 本次验证记录

- 10 项新增后端用例通过，另 9 项原有 ASR/TTS 回归用例通过；新增路由用例也已单独运行通过。
- 4 项前端选择/时间戳逻辑测试通过，管理前端生产构建通过，git diff --check 通过。
- 当前数据库已登记模型（本机记录 ID 171），不需要通过伪造 filePath 来使下拉显示。
- 已安装并启动检查 HOT-Step v1.4.2 CPU CLI，发布包 SHA256 为 660f1a139718f790d8453ac2272720a12811a9d1565e38a73fde89c8a2ff00f1；CLI 支持本接入使用的模式和 encoder-window 参数。
- 浏览器通过临时验证入口挂载实际 Vue ASR 组件，使用当前数据库序列化模型记录，确认完整下拉名称、选中状态、缺失权重提示和三种模式；这验证界面，不是实际模型推理。
- prepare_moss_music.py --check 当前只报告缺少 moss-lm-q8_0.gguf 与 moss-aud-f16.gguf。
- 未验证完整权重推理、实际歌词准确率、实际 CPU RTF/token/s。
