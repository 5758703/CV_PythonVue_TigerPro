# CPU 语音识别部署说明

本次提供六类引擎、八个模型选项；Paraformer 沿用原有 FunASR 推理与既有模型绑定。模型选择、资源准备和真实推理分别验证，实际验证记录见文末。

## 模型选项

模型管理中的 `library` 是本项目的分派标识，不一定等同于 pip 包名。磁盘大小采用十进制 MB，除 Moonshine 外均为部署估算，不是内存占用。

| 模型键 | library | 页面语言选择 / 适用范围 | 本地文件估算 | 官方来源 |
| --- | --- | --- | ---: | --- |
| `paraformer-zh` | `funasr` | `auto`；普通话、中英混合 | 约 1,000 MB | [FunASR Paraformer](https://huggingface.co/funasr/paraformer-zh) |
| `streaming-zipformer-zh-int8` | `sherpa-onnx-asr` | `auto`；固定中文模型 | 约 180 MB | [官方 INT8 压缩包](https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30.tar.bz2) |
| `faster-whisper-small-int8` | `faster-whisper` | `auto/zh/en/ja/ko/de/fr/es`；多语种 | 约 510 MB | [Systran Small](https://huggingface.co/Systran/faster-whisper-small) |
| `parakeet-tdt-0p6b-v3-int8` | `sherpa-onnx-asr` | `auto`；英语及其他欧洲语言，不支持中文 | 约 700 MB | [官方 INT8 压缩包](https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8.tar.bz2) |
| `qwen3-asr-0p6b-int8` | `sherpa-onnx-asr` | `auto`；多语种及中文方言 | 约 1,050 MB | [官方 INT8 压缩包](https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-qwen3-asr-0.6B-int8-2026-03-25.tar.bz2) |
| `moonshine-tiny-streaming` | `moonshine-streaming` | `en`；英文 | 45,233,659 字节 | [Moonshine 官方项目](https://github.com/moonshine-ai/moonshine) |
| `moonshine-small-streaming` | `moonshine-streaming` | `en`；英文 | 142,300,974 字节 | [Moonshine 官方项目](https://github.com/moonshine-ai/moonshine) |
| `moonshine-medium-streaming` | `moonshine-streaming` | `en`；英文 | 269,141,623 字节 | [Moonshine 官方项目](https://github.com/moonshine-ai/moonshine) |

Qwen3 和 Parakeet 在当前固定的 sherpa-onnx API 中没有强制语言参数，因此仅提供自动识别。Zipformer 的 `auto` 表示使用中文模型，不代表能自动切换到其他语言。faster-whisper 的 INT8 指 CPU 计算方式，下载的是官方 Small 转换包。

## 安装、登记与检查

使用后端正在运行的 Python 环境，并先按现有部署方式配置基础依赖、数据库与模型存储目录。下列 PowerShell 命令从项目根目录执行；`--register`、`--model` 和 `--all` 需要能连接已初始化的数据库。

```powershell
Set-Location backend

# 安装新增 SDK 并检查全部条目；不下载模型权重
python -X utf8 scripts/prepare_cpu_asr.py --install-deps --check

# 幂等登记八个模型；保留用户停用状态、名称及自定义绑定
python -X utf8 scripts/prepare_cpu_asr.py --register

# 只检查本地文件与依赖
python -X utf8 scripts/prepare_cpu_asr.py --check

# 下载一个指定模型并登记本地目录
python -X utf8 scripts/prepare_cpu_asr.py --model streaming-zipformer-zh-int8

# --model 可重复；按需准备，避免一次下载所有模型
python -X utf8 scripts/prepare_cpu_asr.py --model moonshine-tiny-streaming --model faster-whisper-small-int8

# 下载全部八个模型选项
python -X utf8 scripts/prepare_cpu_asr.py --all
```

`--install-deps` 固定安装 sherpa-onnx 1.13.3、faster-whisper 1.2.1、moonshine-voice 0.1.5 及指定配套包，使用 `pip --no-deps --target` 写入 `backend/runtime/cpu-asr-python-<Python ABI>-<平台>`。服务只加载与当前 Python ABI 和平台匹配的项目本地目录，避免 Python 3.13 原生包影响项目推荐的 Python 3.12 环境；此步骤不会让 pip 自动升级全局 Torch、torchaudio 或 torchvision。基础环境仍需已有 Flask、NumPy、requests、Hugging Face Hub、imageio-ffmpeg 等依赖，Paraformer 继续使用已有 FunASR/Torch 环境。安装后重启后端。

权重默认写入 `backend/uploads/models/<模型键>`；自定义 `MODEL_FOLDER` 时须保持它对应 `UPLOAD_FOLDER/models`，与现有数据库相对路径约定一致。Hugging Face 文件按本次 API 返回的固定提交版本直接下载，只取必要文件，不依赖全局 Xet 缓存；LFS 文件核对 SHA256，普通文件核对 Git blob SHA1。网页模型管理的拉取入口也会调用同一套下载逻辑；显式重新拉取 Paraformer 或 faster-whisper 时也校验已有文件，损坏文件重新下载。

## 资源与完整性

八个条目的本地模型文件估算合计约 3.9 GB，还需为下载缓存、压缩包、解压临时目录与音频解码留空间。Zipformer、Parakeet、Qwen3 压缩包分别约 132.6、487.2、878.7 MB；下载器预检查“压缩包大小 + 本地文件估算 + 128 MiB”。Hugging Face 模型预检查“本地文件估算 + 128 MiB”，缓存可能增加实际占用。

Moonshine 固定使用 v0.1.5 对应的 `quantized_26_08_21` 英文资源。下载前按缺失文件的官方大小检查可用空间；已有文件也须通过大小与官方 CRC32C 校验才跳过。新文件写入 `.part`，校验通过后原子替换，失败清理临时文件。官方发布的是 CRC32C，而非 SHA256；来源见 [v0.1.5 文件清单](https://github.com/moonshine-ai/moonshine/blob/v0.1.5/core/moonshine-model-file-metadata.generated.cpp)。

页面预检查和 `--check` 不运行模型：Moonshine 检查准确字节大小，其他条目检查必需文件存在且非空，同时检查可选依赖能否被找到。`runtimeReady=false` 时按 `runtimeMessage` 补齐文件或依赖；`true` 只表示这些预检查通过，不保证动态库可加载、内存足够或识别质量达标。仍需用目标语言的真实音频做转写验收。

## 使用范围与限制

- 当前入口是上传音频或含音轨的视频。Zipformer 和 Moonshine 在服务端按约 0.2 秒音频块解码并刷新末尾结果；页面没有实时麦克风、WebSocket 或边识别边推送文字的功能。
- 新引擎单文件时长上限：Qwen3 60 秒、Parakeet 120 秒，其余新增引擎 600 秒。ffmpeg 最多解码到上限加 1 秒，再按实际 PCM 时长拒绝超长输入，不静默截断，也不先缓冲完整长录音。Paraformer 沿用原推理路径，本次不增加时长限制。
- 仅 Moonshine 的原生行时间与 faster-whisper 的原生片段时间用于字幕区间；仅在确实返回有效区间时设置 `timestampsAvailable=true`。Zipformer/Parakeet 可能返回 token 起点元数据，它不等于完整字幕时间区间；Qwen3 不提供可靠字幕时间戳，不用音频总时长补造区间。
- 新引擎在独立工作进程中运行，后端串行提交请求；相同模型复用进程，切换模型、模型目录或线程配置时先结束旧进程，再创建新进程，确保旧模型及其原生动态库卸载。Paraformer 继续沿用原有缓存机制。该限制约束新增引擎的常驻模型数量，不是整个后端的内存硬上限。
- `CPU_ASR_THREADS` 默认 4，用于 sherpa-onnx 和 faster-whisper。Moonshine 0.1.5 仅显式选择 CPU provider，没有可用的线程数控制参数，该配置不改变其线程数。
- `CPU_ASR_TIMEOUT_SECONDS` 默认 1800 秒。原生进程退出或超时会转为请求错误并保留诊断日志，后端保持运行，后续请求可重新创建进程；日志位于 `backend/runtime/cpu-asr-worker-logs`。
- 本机 Anaconda NumPy 的 MKL 与 CTranslate2 自带的 Intel OpenMP 动态库曾触发原生冲突。工作进程单独设置 `MKL_THREADING_LAYER=SEQUENTIAL`，避免 NumPy 加载另一套线程运行库；CTranslate2 仍使用显式 CPU 线程配置。父进程环境不变，不设置允许重复 OpenMP 运行库的危险选项。

## 已执行的验证

### 网页实际环境修复（2026-10-26）

此前权重验收使用 Anaconda 基础 Python 3.13，网页后端实际通过 `H:\DevelopmentEnv\anaconda3\envs\cv_python_tigerpro\python.exe`（Python 3.10.20）运行。因此此前的依赖检查不能代表网页环境；3.10 也不能加载 3.13 原生扩展。

- 已在实际后端解释器中执行 `scripts/prepare_cpu_asr.py --install-deps --check`，将配套 SDK 安装到 `backend/runtime/cpu-asr-python-cpython-310-win-amd64`，不改全局 Torch。
- 安装器现按 Python 版本选择 PyAV：3.10/3.11 使用 16.1.0，3.12 以上使用 19.0.2，修复旧固定版本在 3.10 下无法安装的问题。刷新模型状态也会重新发现启动后才创建的本地依赖目录。
- 在 Python 3.10 中完成真实转写：faster-whisper 中文、Parakeet 英文、Moonshine Tiny/Small/Medium 英文均返回非空文字。
- 用户确认 Parakeet 测试音频为中文或中英混合。该模型不支持中文；对中文可能输出空文字或错误英文，并不代表正常识别。不能通过参数把它变成中文模型，也不会自动换模型来冒充 Parakeet 结果。
- 空结果现返回 `recognitionStatus=empty` 和明确的录音/语言说明，页面显示提示；仅有文字而无字幕时间戳时显示全文并允许复制或导出 JSON。
- 本轮使用实际 Python 3.10 执行回归：131 项通过、1 项因 Windows 符号链接权限跳过；前端 8 项通过。

### 初次集成验收

- 八个选项已登记到当前数据库，管理端 options 返回全部八项（含缺少资源项）；浏览器挂载实际 Vue ASR 组件并逐项选中，选中标签与说明正常。验证入口使用真实数据库选项数据，不代表已重启线上后端。
- 本机八项权重均已准备并绑定到数据库；全新 Python 进程执行 `--check`，八项本地文件与依赖预检查均通过。权重与本地 SDK 位于忽略目录，源码提交不会携带这些大文件；其他机器仍需按上文安装和准备。
- 已在本机用真实权重成功转写 Paraformer、Zipformer、Qwen3 中文示例，以及 Parakeet、faster-whisper 和 Moonshine Tiny/Small/Medium 英文示例；这些是功能验收，不是同机隔离条件下的准确率排行榜。
- Qwen3 通过项目独立工作进程识别 Zipformer 官方压缩包中的 5.6115 秒中文样例，返回“对我做了介绍啊。那么我想说的是呢，大家如果对我的研究感兴趣呢。”；含进程启动与模型加载耗时约 13.6 秒。该单次冷启动结果不能当作纯推理速度或通用准确率。
- 已验证同一个父进程先运行 Parakeet，再切换到 faster-whisper；旧工作进程退出、新工作进程成功返回文字及其原生片段时间，父进程保持运行。测试也覆盖原生异常退出、超时、无效协议及后续请求恢复。
- Paraformer 的 FunASR 会探测裸命令 ffmpeg；接入会将 imageio-ffmpeg 已提供的可执行文件以标准名称准备到项目 runtime 并仅设置当前后端进程 PATH，避免依赖不可执行的系统命令。
- 自动回归：后端 123 项通过、1 项因 Windows 不具备符号链接权限跳过；前端 7 项通过；管理端生产构建成功，仍有既有的大分包提示。
