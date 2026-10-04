# Confucius4-R2T2 / T3PO 集成

复用现有模型管理、语音识别、文本生成和模型场景 API。可独立选择官方服务或本地 `llama-cpu` 服务。Flask 后端只运行客户端；CPU 模型在 llama-server 中加载，无需安装 vLLM。

## 官方来源（2026-10-04 核查）

| 模型 | 功能 | 官方代码 | 权重 |
| --- | --- | --- | --- |
| Confucius4-R2T2 | 稳定增量流式语音识别 | https://github.com/netease-youdao/Confucius4-R2T2 | https://huggingface.co/netease-youdao/Confucius4-R2T2 |
| Confucius4-T3PO | 14B 中英双向流式文本翻译 | https://github.com/netease-youdao/Confucius4-T3PO | https://huggingface.co/netease-youdao/Confucius4-T3PO |

ModelScope 同名仓库：`netease-youdao/Confucius4-R2T2`、`netease-youdao/Confucius4-T3PO`。官方 GGUF 可通过以下 CPU 适配接入。

## 本地 CPU 部署（Windows / Linux）

使用较新的 [llama.cpp](https://github.com/ggml-org/llama.cpp/releases) CPU 构建，必须支持 Qwen3-ASR 音频输入、`--mmproj` 与 `/v1/chat/completions`。官方 R2T2 原生扩展的 Linux/CUDA 二进制不适用于 Windows；本项目使用其文档中的 llama-server HTTP 路径，避免安装该扩展。旧版 llama.cpp 即使能加载解码器也可能不支持音频编码器。

默认下载官方文件：

| 模型 | 文件 | 磁盘大小 |
| --- | --- | --- |
| R2T2 | Confucius4-R2T2-Q4_K_M.gguf | 1.11 GB |
| R2T2 音频编码器 | mmproj-Confucius4-R2T2-Q8_0.gguf | 348 MB |
| T3PO | Confucius4-T3PO-Q5_K_M.gguf | 10.5 GB |

下载来源：[R2T2 官方 GGUF](https://huggingface.co/netease-youdao/Confucius4-R2T2-GGUF/tree/main)、[T3PO 官方 GGUF](https://huggingface.co/netease-youdao/Confucius4-T3PO-GGUF/tree/main)。实际内存还包含 KV 缓存、音频缓冲区和运行时开销，文件大小不代表内存需求。CPU 速度与量化质量需要在目标机器上测量。

联网准备阶段，在项目根目录执行（下面的下载器仅使用项目现有 `requests`，支持断点下载，并与官方仓库记录的 SHA-256 核对）：

```powershell
python backend/scripts/prepare_confucius_cpu_weights.py r2t2
python backend/scripts/prepare_confucius_cpu_weights.py t3po
```

离线运行阶段，只使用本地文件。当前 Windows 工作区已准备 `backend/runtime/llama-cpu/llama-server.exe`，启动脚本会自动发现它。分别启动所需服务：

```powershell
python backend/scripts/confucius_cpu_server.py r2t2
python backend/scripts/confucius_cpu_server.py t3po
```

启动脚本固定 `--offline --device none --no-op-offload -ngl 0`；R2T2 额外固定 `--no-mmproj-offload`，将解码器和音频编码器都放在 CPU。服务只监听 `127.0.0.1`，默认端口分别为 8273 / 8010，模型别名为 `Confucius4-R2T2` / `Confucius4-T3PO`。默认 4 个 CPU 线程、4096 上下文、256 batch、128 micro-batch，并禁用启动预热。本机 R2T2 实测采用这组参数；初次使用默认预热的启动尝试超时，现已改用验证通过的参数。终端 Ctrl+C 停止服务。

可设置 `--threads 8`、`--context 8192`、`--port` 或 `--weights-dir`，更大的上下文和 batch 会增加内存开销。若可执行文件在其他目录，传入 `--server "C:\llama.cpp\llama-server.exe"`。`--check` 只检查文件与参数，不实际加载权重。无需 `--download` 即可离线启动；模型、音频编码器和分词信息均在本地 GGUF 文件中。

Linux 使用同一脚本，`--server /path/to/llama-server`。权重放在 `backend/weights/confucius/r2t2` 和 `backend/weights/confucius/t3po`。也可直接使用 llama-server 加载其他官方量化版本，再配置相同地址和模型别名。

在 `backend/.env` 启用 CPU 适配，并重启项目后端：

```dotenv
CONFUCIUS_R2T2_BACKEND=llama-cpu
CONFUCIUS_T3PO_BACKEND=llama-cpu
CONFUCIUS_R2T2_CPU_URL=http://127.0.0.1:8273
CONFUCIUS_T3PO_CPU_URL=http://127.0.0.1:8010
CONFUCIUS_CPU_TIMEOUT_SECONDS=900
CONFUCIUS_R2T2_CPU_MAX_TOKENS=4096
CONFUCIUS_T3PO_CPU_MAX_TOKENS=4096
```

CPU_URL 接受本机回环地址的服务根地址或 `/v1` 地址，拒绝外部主机；客户端禁用系统 HTTP 代理，禁止 HTTP 重定向。若自己部署的 llama-server 启用了认证，配置对应 `CONFUCIUS_R2T2_CPU_API_KEY` / `CONFUCIUS_T3PO_CPU_API_KEY`。CPU 适配不使用官方 WebSocket 密钥或官方 T3PO FastAPI URL；可以分别选择不同后端。将 `BACKEND` 改回 `official` 即可切回已有官方服务。

运行时同时设置 `HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1`、`HF_HUB_DISABLE_TELEMETRY=1`。联网下载只发生在明确调用准备命令时，普通 CPU 推理不下载文件、不调用云端推理接口。

可重复执行真实离线验证（会临时启动模型服务并在测试后退出，默认使用已准备的本地音频）：

```powershell
python backend/scripts/verify_confucius_cpu_offline.py r2t2
python backend/scripts/verify_confucius_cpu_offline.py t3po
```

该验证程序阻断客户端外部 DNS 和连接，先确认外网访问失败，再通过本机服务做真实推理。服务使用 `--offline`。报告与服务器日志写入 `backend/runtime/confucius-verification/`；准备文件的版本与校验值写入各模型目录的 `verified-assets.json`。运行时发布版本与校验值见 `backend/runtime/llama-cpu/verified-runtime.json`。权重和运行时已加入 Git 忽略规则，避免提交大文件。

验证工具默认等待启动 600 秒，单次推理等待 900 秒，可用 `--startup-timeout` / `--timeout` 调整。项目 CPU 请求使用独立的 `CONFUCIUS_CPU_TIMEOUT_SECONDS`，默认 900 秒。T3PO 的 Q5_K_M 权重约 10.51 GB；在本机 16 GB 内存且其他应用运行时，换页会显著拖慢启动和逐 token 生成。建议按需依次启动两个服务，完成一种任务后退出对应服务再加载另一个模型；本机配置不保证实时翻译或两模型同时常驻的性能。

服务加载完成后检查 `http://127.0.0.1:8273/health` 和 `http://127.0.0.1:8010/health`，应返回 HTTP 200。管理页面和场景页面继续选择原来的两个模型，管理列表会显示「CPU 服务」。无需在模型管理中上传 GGUF，权重由专用服务持有。

CPU 模式行为：

- R2T2：上传音频/视频，经 ffmpeg 转为 16 kHz 单声道 PCM16 WAV，通过 `input_audio` 提交。使用 Qwen3-ASR 音频模板，中文/英文可约束语言，auto 为自动检测。返回整段转写和一个 `reset=true` 最终事件，不模拟流式增量。
- T3PO：中英双向整段翻译，保留 `<STREAMING_HISTORY>` / `<CURRENT_INPUT>` 格式，并添加完整输入指令。这是针对文件/整段文本入口的提示适配，未声称与官方流式策略质量一致。仅支持 `latencyMode=native`；`low/high` 在 CPU 模式明确拒绝，界面隐藏这两个选项。
- 输出含 `backend=llama-cpu`。服务超时、空结果、WAIT、无效协议或输出达到 token 上限均报错，避免把未完成结果当成成功。较长输入可提高上下文/输出上限，或拆分后提交。
- 场景 ready 只检查客户端依赖与配置，仍不联网检查健康；`weightsPresent=false` / `localWeightsRequired=false` 表示 Flask 不直接持有模型权重。

协议依据：[R2T2 llama-server 客户端](https://github.com/netease-youdao/Confucius4-R2T2/blob/master/r2t2_llama/llama_native_backend.py)、[llama.cpp 多模态支持](https://github.com/ggml-org/llama.cpp/blob/master/docs/multimodal.md)、[T3PO 提示接口](https://github.com/netease-youdao/Confucius4-T3PO/blob/main/inference/prompts.py)。

R2T2 代码为 Apache-2.0，权重适用网易模型使用许可（官方 `MODEL_LICENSE`）；T3PO 权重页标注 Apache-2.0。按实际下载版本的许可使用。

## Linux / CUDA 模型服务器部署

两个项目分别使用独立 Python 环境，CUDA / PyTorch 组合遵循官方说明。以下命令在模型服务器执行。

R2T2：克隆官方仓库，按 README 安装依赖，下载 R2T2 权重及启动脚本需要的 FireRedVAD 资产，配置并执行 `run_start_server.sh`。模型路径、VAD 路径与监听端口必须匹配部署目录。官方 `ws_client.py` 使用端口 8272，T3PO 示例使用 8093，以实际监听端口为准。

T3PO：

```bash
git clone https://github.com/netease-youdao/Confucius4-T3PO.git
cd Confucius4-T3PO
python -m venv .venv
source .venv/bin/activate
pip install -e '.[models]'
hf download netease-youdao/Confucius4-T3PO --local-dir ./Confucius4-T3PO
vllm serve ./Confucius4-T3PO --served-model-name Confucius4-T3PO --dtype auto --port 8010
```

另一终端启动同一仓库的官方应用：

```bash
source .venv/bin/activate
export VLLM_BASE_URL=http://127.0.0.1:8010/v1
export VLLM_MODEL=Confucius4-T3PO
bash scripts/start.sh
```

本项目连接官方 FastAPI 应用（默认 8000），**不直接连接 vLLM 的 8010 `/v1`**。检查：`GET /api/v1/health`。

R2T2 当前官方代码开发密钥为 `test0102`，生产部署应替换官方服务中的密钥校验。本项目要求显式配置密钥。T3PO 官方演示 HTTP 接口没有认证；可在反向代理配置 Bearer 校验，客户端支持 `CONFUCIUS_T3PO_API_KEY`。

## 项目配置

在 `backend/.env` 设置实际地址，重启后端：

```dotenv
CONFUCIUS_R2T2_WS_URL=ws://MODEL_HOST:8272/asr_stream_api_v1
CONFUCIUS_R2T2_SECRET_KEY=YOUR_R2T2_SECRET
CONFUCIUS_T3PO_URL=http://MODEL_HOST:8000
CONFUCIUS_T3PO_API_KEY=
CONFUCIUS_TIMEOUT_SECONDS=120
```

客户端依赖：`pip install 'websockets>=12,<17'`；音频转换复用 `imageio-ffmpeg`。后端启动时幂等注册 `confucius4-r2t2` 和 `confucius4-t3po`，无需在管理端拉取权重。

场景 ready 表示登记、启用、客户端依赖及地址配置有效；检查不会联网或加载模型，不保证远端服务健康。`weightsPresent=false` 正常，`localWeightsRequired=false` 表示权重由模型服务管理。

## 使用与接口

- 「语音识别」选择 R2T2，上传音频或视频，返回转写与 `increments`。音频转换为 16 kHz 单声道 PCM16LE，客户端并发发送和接收，发送官方 EOS 后等待正常关闭。
- 「文本生成」或「机器翻译」场景选择 T3PO，可选 `zh2en` / `en2zh` 及 `low` / `native` / `high`。每次请求建立独立上游会话，以 `end=true` 刷新尾部，返回 `text` 和 `events`。
- 管理接口沿用 JWT / RBAC：`POST /api/ai/model/{id}/transcribe`（multipart 的 `file`、可选 `language`）；`POST /api/ai/model/{id}/generate-text`（JSON）。
- 开放接口沿用 AppKey / HMAC 签名鉴权，需要 `model-scenario:infer` scope 和时间戳、nonce、签名请求头：`POST /openapi/v1/model-scenarios/confucius4-r2t2/infer`、`POST /openapi/v1/model-scenarios/confucius4-t3po/infer`。签名规则复用项目现有开放 API 文档。

T3PO 示例：

```json
{"text":"大家好。","direction":"zh2en","latencyMode":"native"}
```

开放场景接口使用 multipart 提交同名参数。R2T2 `language` 支持 `auto` / `zh` / `en` / `Chinese` / `English` / `zhen`，`auto` 映射为中英混合 `zhen`。

当前项目页面采用文件上传 / 一次请求返回汇总结果。模型服务内部使用流式协议，没有新增麦克风实时同传界面。可将 R2T2 返回的 `text` 提交给 T3PO 翻译。官方 T3PO 自带实时同传演示，配置它的 `ASR_WS_URL`、`ASR_SECRET_KEY` 即可串联，协议见官方 README。

## 验证范围

自动化回归覆盖官方服务协议、CPU 请求格式、音频转换、语言参数、错误响应、截断检测、CPU 启动参数、外部 URL/代理拦截、场景就绪状态和 API。真实离线验证另外执行，结果以 `backend/runtime/confucius-verification/*-offline.json` 为准；协议测试本身不能替代实际模型推理。

本机真实验收已完成：R2T2 返回完整中文转写；T3PO 中译英返回 `Hello.`，英译中返回 `你好。`，两份报告均通过。实际配置、耗时与限制见 [CPU 离线验收记录](confucius4-offline-verification.md)。
