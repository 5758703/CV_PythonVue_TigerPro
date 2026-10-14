# 行人重识别 / 跨镜重识别 C++ 核心版本

## 交付范围

保留原有 Flask API、权限、底库、YOLO 检测、局部跟踪和跨镜关联。新增的 C++17 共享库执行行人外观模型的 RGB/ImageNet 归一化/NCHW、ONNX Runtime CPU 推理及输出校验。图片解码与 resize 仍调用 OpenCV；底库匹配、Tracklet 聚合和身份关联仍由既有业务代码处理。此版本不要求部署独立推理服务，也不要求安装新的 Python 扩展包。

源代码在 `backend/native/reid`，Python 桥在 `services/reid_cpp.py`，策略层在 `services/reid_runtime.py`。ctypes 调用原生推理时释放 GIL；C++ 会话共享、输入输出缓冲按调用隔离，同模型可并发运行。模型缓存最多 8 个会话，以路径、纳秒修改时间、文件大小和线程配置区分，更新资产后重新加载。一个进程使用一个 ORT 动态库，修改 ORT 库配置后应重启服务。

## 构建

支持单输入 float32 NCHW、三通道、固定 H/W、固定 batch=1 或动态 batch，首个输出为 float32 embedding（固定特征维度）。固定 batch=1 在 C++ 内逐个 Run；只有动态 batch 模型才进行模型级批推理。一次 ABI 调用最多 64 张，Python 自动分块。INT8 的输入若仍为 float32 可尝试，但算子支持取决于 ORT；不自动量化模型。

需要 C++17 编译器及 ONNX Runtime SDK 头文件（辅助脚本固定 1.20.1，运行库要求兼容 API 20 或更新）。推荐沿用服务环境中已有的 `onnxruntime` 动态库，避免两个不同 ORT 版本混用。

已有 CMake + MSVC/GCC/Clang 时，在项目根目录：

```powershell
cmake -S backend/native/reid -B backend/runtime/reid_cpp/build -DONNXRUNTIME_INCLUDE_DIR=F:/sdk/onnxruntime/include
cmake --build backend/runtime/reid_cpp/build --config Release
cmake --install backend/runtime/reid_cpp/build --config Release --prefix backend/runtime/reid_cpp
```

或者已有 Zig/GCC/Clang 时：

```powershell
python backend/scripts/build_reid_cpp.py --compiler F:/tools/zig/zig.exe --include-dir F:/sdk/onnxruntime/include
```

Windows x64 缺少编译器时可显式下载便携 Zig 0.13.0 与固定版本 ORT 头文件（会访问官方站点，不修改系统 Python 或 PATH）：

```powershell
python backend/scripts/build_reid_cpp.py --fetch-tools
```

产物默认在 `backend/runtime/reid_cpp/reid_runtime.dll`；Linux 为 `libreid_runtime.so`，macOS 为 `libreid_runtime.dylib`。辅助脚本下载的工具、头文件、许可证、缓存和构建信息均留在被忽略的 runtime 目录。SDK 头文件和运行库按 ONNX Runtime 原始许可证使用。

## 启用与回退

前端「行人重识别」顶部选择外观推理版本，登记、识别、图库检索和录像检索均使用这一选项；「跨镜重识别 → 会话控制 → 高级关联策略」选择行人外观推理。车辆 ReID、检测器和关联策略不受此选项影响。

| 选项 | 行为 |
|---|---|
| `python` | 原有 OpenCV/ORT 路径，默认值 |
| `cpp` | 严格使用原生核心；独立 ReID 失败返回错误，MTMC 在运行时状态报告失败 |
| `auto` | 先试 C++；失败时回退原有路径，返回 `effectiveRuntime=python`、`degraded=true`、`fallbackReason` |

独立 ReID 的 multipart 接口均接受 `reidRuntime`：`POST /api/ai/reid/persons/<id>/enroll`、`/recognize`、`/search`、`/search-video`。跨镜会话启动及多视频 ReID 搜索任务的 JSON/multipart 支持同名字段，流水线 `composite.mtmc` 节点配置复用该参数。

```json
{"cameraIds": [1, 2], "enablePerson": true, "enableVehicle": false, "reidRuntime": "cpp"}
```

服务端环境配置：

```dotenv
REID_RUNTIME=python
REID_CPP_THREADS=2
# 默认产物路径以外才需指定：
# REID_CPP_LIBRARY=F:/deployment/reid_runtime.dll
# REID_CPP_ORT_LIBRARY=F:/sdk/onnxruntime/lib/onnxruntime.dll
```

优先级为请求/会话显式选项 > `REID_RUNTIME` > `python`。默认前端显式发送 `python`；要使用 C++，直接在工作台切换。库路径只能由服务端配置，不接受客户端指定任意动态库。未配置 ORT 路径时从当前 Python 环境的 `onnxruntime/capi` 查找；如果 wheel 未提供独立运行库，则设置 SDK 运行库绝对路径。

实际特征后端为 `reid-cpp-ort`，provider 为 `onnxruntime-cpp-cpu`。独立识别/检索返回 `runtime` 元数据；MTMC 复用现有运行时面板，显示实际 provider、特征空间及降级原因。强模型与 Youtu 的 modelKey、维度及 modelVersion 保持分离；C++ 返回原始向量，业务层照常 L2 归一化，既有底库可复用。沿用旧行人模型的文件名版本键，不解决同名文件被替换的历史版本问题，建议后续迁移为内容哈希版本键。

多图登记和录像检索汇总所有特征调用状态，混用后端时标记 `provider/effectiveRuntime=mixed`，保留任何一次回退原因；`callCount` 为被汇总的提取调用数，多人批提取计作一次。跨镜多视频结果弹窗按摄像头展示实际后端、回退原因或错误。

## 验证与性能基准

```powershell
python -m pytest backend/unittests/test_reid_cpp_runtime.py backend/unittests/test_mtmc_reid_runtime.py -q -p no:cacheprovider
python backend/scripts/benchmark_reid_cpp.py --model backend/uploads/models/opencv-person-reid-youtu --batch-size 1 --threads 2 --iterations 30 --output backend/runtime/reid_cpp/bench-b1.json
python backend/scripts/benchmark_reid_cpp.py --model backend/uploads/models/opencv-person-reid-youtu --batch-size 1 --workers 4 --threads 2 --iterations 40 --output backend/runtime/reid_cpp/bench-b1-w4.json
python backend/scripts/benchmark_reid_cpp.py --model backend/uploads/models/opencv-person-reid-youtu --batch-size 8 --workers 4 --threads 2 --iterations 30 --output backend/runtime/reid_cpp/bench-b8-w4.json
```

测试生成小型真实 ONNX 图，验证固定/动态 batch、非连续裁剪、数值一致性、并发、关闭生命周期和输入错误。未编译原生库时，原生集成测试会明确跳过；运行时选择与回退测试仍执行。构建后必须重新运行，不能把跳过当作原生验证通过。

基准同时比较旧路径、相同线程数的 Python ORT、C++ ORT，报告会话初始化、首次批次、热 p50/p95、每秒裁剪数、数值误差、模型 SHA256 和环境信息。旧路径为惰性加载，加载时间出现在首次批次；比较冷启动应相加 `sessionCreateMs + firstBatchMs`。默认输入为固定随机裁剪，只能验证效率和数值，不衡量识别准确率；用 `--images <crop1> <crop2>` 指定真实行人裁剪。

特征耗时不等于端到端 MTMC 耗时。上线选择需同时评估视频解码、检测、ReID、关联、落库、输出的分段耗时与 IDF1/误合并率。C++ 不保证超过已经使用原生算子的 Python ORT；线程和模型后端选择可能比语言迁移贡献更大。实测记录见 `PROJECT_INFERENCE_OVERVIEW.md`。

本机真实 Youtu 权重实测：4 并发下新 C++ 路径相对旧 OpenCV 吞吐约 1.80–1.95 倍；单并发单人约慢 26%，与同配置 Python ORT 基本相当。因此默认仍使用原有推理，按实际负载选择版本。Windows DLL 已在本工作区构建；其它系统请按上方命令构建并验证。

## 常见问题

- 缺少 `reid_runtime.dll`：先构建，或检查 `REID_CPP_LIBRARY` 的绝对路径。
- ORT 库未找到或 DLL 依赖缺失：确认架构匹配（64 位服务使用 64 位 DLL），指定与 SDK 头兼容的运行库；Windows SDK 运行库可能需要相应 VC Runtime。
- 图输入/输出不符合约定：使用单图像输入的 ReID ONNX 导出，检查 NCHW、空间维度及输出维度。不要将多输入 CLIP 文本图送入本核心。
- CPU 并发越高越慢：从 `REID_CPP_THREADS=1/2/4` 和并发 `1/2/4` 网格测量，限制同时运行的检测与 ReID 会话数量，避免线程过度争抢。
- 回滚：工作台选「原有推理」或请求 `reidRuntime=python`，重启跨镜会话，无需修改数据库或替换权重。
