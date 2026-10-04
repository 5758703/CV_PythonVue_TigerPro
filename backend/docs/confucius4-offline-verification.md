# Confucius4 本机 CPU 离线验收

验收日期：2026-10-04。机器：Windows x64，Intel Core i7-6700HQ（4 核 / 8 线程、AVX2），约 16 GB 内存。使用 llama.cpp b11146 官方 Windows CPU 构建；运行时及权重已下载到本项目并通过发布方 SHA-256 校验。

## 实际推理结果

| 模型 | 输入 | 实际输出 | 状态 |
| --- | --- | --- | --- |
| R2T2 Q4_K_M + Q8_0 音频编码器 | 官方示例音频前 6 秒 | 之前有顾客自己带酒水，也没加收钱或者不让喝。 | 通过，启动与推理合计 25.46 秒 |
| T3PO Q5_K_M，中译英 | 你好。 | Hello. | 通过，推理约 749.13 秒 |
| T3PO Q5_K_M，英译中 | Hello. | 你好。 | 通过，推理约 868.74 秒 |

结果来自真实 GGUF 推理，调用项目 `services.confucius` 适配器；没有使用模拟模型响应。原始报告和日志保存在 `backend/runtime/confucius-verification/`，其中 `passed=true` 才表示对应验收脚本全部成功。

两份最终报告 `r2t2-offline.json` / `t3po-offline.json` 均为 `passed=true`，且网络阻断自检通过。T3PO 启动、两次推理及清理合计 1854.46 秒（约 30 分 54 秒）；模型服务约 228 秒后就绪。两个模型按顺序测试，未测试同时常驻。临时服务已退出，没有占用日常服务端口。

## 离线与 CPU 约束

- 模型服务只监听回环地址，使用本地 GGUF；`--offline --device none --no-op-offload -ngl 0`，音频编码器额外使用 `--no-mmproj-offload`。
- 验证客户端拦截外部 DNS 和 socket 连接，并主动确认外网请求失败；本机 HTTP 请求禁用系统代理与重定向。
- 未禁用整台电脑网卡。验证约束为客户端外部网络被拦截，以及运行时显式离线、只读取本地资产；服务器日志记录 CPU 分配。
- 下载阶段联网；普通推理阶段无需 Hugging Face、ModelScope、云端推理服务或 GPU。

## 本机使用

`backend/.env` 已将两个模型后端设置为 `llama-cpu`，CPU 请求超时为 900 秒。重启项目后端使设置生效，在项目根目录按需运行：

```powershell
python backend/scripts/confucius_cpu_server.py r2t2
python backend/scripts/confucius_cpu_server.py t3po
```

每条命令启动一个服务；终端 Ctrl+C 停止。16 GB 机器建议先退出一个模型服务，再加载另一个。T3PO 权重约 10.51 GB，其他应用占用内存会导致换页；本次中译英仅短句也约需 12 分半，不保证实时性能或两个模型同时常驻。更长任务可调大 `CONFUCIUS_CPU_TIMEOUT_SECONDS`，内存充足后再测量速度。

重新验收：

```powershell
python backend/scripts/verify_confucius_cpu_offline.py r2t2
python backend/scripts/verify_confucius_cpu_offline.py t3po
```

CPU 适配最新回归：19 项通过；另有官方协议与场景相关回归 48 项通过。语法检查和改动空白检查通过。部署、权重来源和 API 使用见 [集成说明](confucius4-integration.md)。
