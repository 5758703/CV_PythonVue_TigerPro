# 跨镜车辆外观 C++ 版本：接入、精度与效率验证

更新日期：2026-10-14。保留原有 Python 车辆推理，新增车辆专用 C++ 运行时。本文记录实际代码和真实权重/标注裁剪测量；特征检索结果不等于完整视频的 MTMC 身份准确率。

## 1. 使用入口与实现

「跨镜重识别 → 跨镜会话控制台 → 高级关联策略」新增独立的 **车辆外观推理**、**车辆外观模型**、**车辆外观阈值**、**跨镜匹配分差**。行人选项仍只控制 Strong/Youtu；车辆选项控制车辆 ONNX。运行中的会话禁止修改新增项，重新进入页面会恢复当前会话选择。

| 参数 | 默认 | 作用 |
|---|---|---|
| `vehicleReidRuntime` | `python` | `python` 原有路径；`cpp` 严格原生；`auto` 原生失败后显式回退 |
| `vehicleReidModelKey` | 空，原有自动选择 | 可明确选择 `transreid-vehicle`、`clip-reid-vehicle`、`vehicle-vit-reid`，不以其它模型替代显式 key |
| `vehicleReidModelId` | 无 | 保留已有 API；同时指定 key 时必须与该 key 对应，否则 400 |
| `vehicleAppearThresh` | 0 | 0 继承通用外观阈值；正值作为车辆外观阈值，继续执行已有拓扑/车型/车牌规则 |
| `minMatchMargin` | 0 | 最佳和次佳候选需要拉开分差；这是已有共享关联参数，同时影响行人和车辆 |

JSON/multipart 的各会话启动接口及流水线 `composite.mtmc` 共用解析与校验。显式模型须在模型管理中拉取并启用。严格 C++ 缺车辆权重时启动前返回错误；执行失败时实际运行面板标记 `failed/unavailable`，不伪装成 Python 推理成功。多视频行人检索仍由行人选项控制。

执行链路：

```mermaid
flowchart LR
  D[车辆检测 / 局部跟踪] --> Q[原有质量采样 / 车辆预算 / 同帧调度]
  Q --> C[OpenCV resize / contiguous BGR]
  C --> N[C++ RGB归一化 / NCHW / 持久ORT CPU会话]
  N --> V[有限非零向量校验 / L2 / SHA256版本空间]
  V --> A[Tracklet聚合 / 车牌投票 / 车型拓扑 / 候选分差]
  A --> G[全局车辆身份 / 证据 / 运行时状态]
```

同帧调度先按原有轨迹优先级、采样资格和预算预留样本，统一提取，然后按原顺序处理车牌、聚合和关联；没有跨摄像头排队等待。预算仍按车辆样本计数，失败记录已消费预算。未进入采样的车辆继续复用已有轨迹证据。

## 2. 模型契约与识别质量保护

C ABI 2 增加 `reid_create_vehicle`，原行人入口保持单输入约束。车辆支持首输入 float32 NCHW、三通道，固定或动态 batch；动态空间尺寸按原路径默认 256×256；首输出 `[1,D]` 或 `[D]`，静态 D。float32/int32/int64/bool/double 辅助输入沿用原 Python 的零 camera/view feed，动态辅助维度按 1；有辅助输入或扁平输出时强制逐图 Run，避免猜测辅助标签的 batch 语义。辅助 rank≤8、元素数≤1048576、数量≤16；未知类型明确报错。

预处理保持 OpenCV INTER_LINEAR、BGR→RGB、`x/255` 和 ImageNet mean/std。原生输出检查形状与有限值，车辆禁止零向量；业务层继续 L2。关联空间仍是 **`vehicle-onnx + 实际维度 + 权重 SHA256`**，Python/C++ 可比较同模型特征，不把不同权重或直方图拼入同一空间。

`auto` 的两个退化层次不同：原生失败但 Python 同权重成功，保留同空间特征并报告降级原因；Python 也失败而得到颜色直方图时，标记 `associationUsable=false`，在进入 Tracklet 身份原型之前清除该外观证据。车牌和局部跟踪继续运行。原有 `python` 模式保留历史直方图行为，便于回滚比较。该保护减少“同色即同车”的弱特征误合并机会，不等于已经测出了生产误合并率改善。

实际语义 `backend=vehicle-onnx`，执行标识 `runtimeBackend=vehicle-cpp-ort`、`provider=onnxruntime-cpp-cpu`。面板显示真实 provider、哈希版本和降级原因；`auto` 是错误回退策略，不会自动比较哪种运行时最快。

## 3. 构建与部署

与行人核心共用 C++17、ORT API 20 和构建脚本。新产物为 `backend/runtime/reid_cpp/reid_runtime_v2.dll`，Linux/macOS 对应 `libreid_runtime_v2.so/.dylib`；旧库并存。新桥优先 v2，仍可用 v1 做原行人推理，车辆须 ABI 2。Windows v2 已在当前工作区实际编译/运行；其它系统尚未执行验证。

```powershell
# 使用已有 SDK / 编译器；CMake 方式见 REID_CPP_RUNTIME.md
python backend/scripts/build_reid_cpp.py --compiler F:/tools/zig/zig.exe --include-dir F:/sdk/onnxruntime/include
# 或下载固定版本的官方便携工具和头文件
python backend/scripts/build_reid_cpp.py --fetch-tools
```

```dotenv
REID_RUNTIME=python
VEHICLE_REID_RUNTIME=python
REID_CPP_THREADS=2
VEHICLE_REID_CPP_THREADS=4
VEHICLE_REID_CPP_BATCH_SIZE=1
# 若配置过旧库绝对路径，更新为 v2，或者删除此覆盖以使用默认发现：
# REID_CPP_LIBRARY=F:/deployment/reid_runtime_v2.dll
# REID_CPP_ORT_LIBRARY=F:/sdk/onnxruntime/lib/onnxruntime.dll
```

车辆线程默认为 `min(4,逻辑CPU数)`，独立于行人线程；车辆模型 batch 上限默认 **1**，可在 1–64 内配置。同帧调度仍减少重复会话查找、模型哈希/元数据准备；只有动态模型且 batch 上限>1 才采用模型级多图 Run。默认 1 来自下方 CPU 实测中大 batch 的负收益。修改核心库/线程配置后重启后端，并重启跨镜会话；回滚在工作台选择 `python`，无需迁移底库。

模型缓存有界、按资产修订/线程/库/人或车辆 profile 区分；同模型会话可并发，输入、辅助 tensor、输出均为调用级缓冲，ctypes 释放 GIL。热测量需要常驻复用，避免每帧创建模型。

## 4. 六对真实标注车辆的精度对照

输入为 `docs/test_data/images/跨镜车辆重识别-两个镜头同一辆车画面01..06.png` 中的 12 个人工标注车体裁剪。沿用已有 `benchmark_vehicle_reid.py` 的 6 对标注和 bbox；标注只用于评估，不注入模型或关联器。检索在两个镜头的 6×6 余弦矩阵上计算，接受条件为互为最佳、达到阈值且拉开分差。

| 现有权重 | 维度/输入 | 左→右 Rank-1 | 右→左 Rank-1 | 阈值0.48/分差0.04的接受正确/错误对 |
|---|---|---:|---:|---:|
| TransReID | 512 / 128×256 | 2/6 | 1/6 | 0 / 0 |
| CLIP 车辆 | 512 / 256×256 | 6/6 | 6/6 | 4 / 0 |
| ViT 车辆 | 512 / 256×256 | 6/6 | 6/6 | 4 / 0 |

三个运行时（旧 Python ORT、同线程 Python ORT、C++ ORT）的排序完全一致。归一化向量对旧版最大绝对差≤`6e-8`，对同线程 Python ORT 为 0；allclose 均通过。本地 CLIP 与 ViT 文件 SHA256 完全相同，属于同一组权重，不能当作两个独立模型的融合收益。

**模型选择带来的差异比语言迁移更大。** 当前 6 对样本更适合 CLIP 权重，但该模型更重。0.48 下 CLIP 的 30 个异车有向组合全部超过阈值，说明只看“超过0.48”不够。以本组样本的 CLIP 为起点，可尝试 **车辆阈值0.80、匹配分差0.04**：接受4个正确、0个错误，另2对保留为模糊/候选，不强行合并。更大的现场同车/异车集应重新校准；不把这6对结果外推为生产 Rank-1、mAP 或 IDF1。

```json
{"cameraIds":[1,2],"enablePerson":false,"enableVehicle":true,
 "vehicleReidRuntime":"cpp","vehicleReidModelKey":"clip-reid-vehicle",
 "vehicleAppearThresh":0.80,"minMatchMargin":0.04}
```

完整 MTMC 继续按现有拓扑、车牌、多观测、同镜互斥与候选策略判定，因此上述检索接受数不是完整视频的全局身份正确数。没有放松关联阈值来制造更高“命中率”。

## 5. 真实特征级性能与配置选择

环境同本项目概述：Windows 11、Intel Family 6 Model 94、8逻辑CPU、Python3.13.5、ORT1.27.0、OpenCV5.0.0。计时包含裁剪 resize/归一化/forward/L2；不含检测、解码、数据库、OCR或整个MTMC。旧 ORT 使用原自动线程配置；对照 ORT/C++ 使用相同线程数、关闭 spinning。每次模式顺序执行，测量时没有并行本任务测试/前端构建；主机负载、冷加载和内存影响仍造成波动。

默认车辆4线程、每次1图，20次/预热3次单并发与32次/预热3次4并发：

| 模型 / 并发 | 模式 | 热p50 ms | 热p95 ms | crops/s |
|---|---|---:|---:|---:|
| Trans / 1 | 原Python | 43.11 | 49.75 | 23.57 |
| Trans / 1 | 同线程Python ORT | 45.77 | 53.90 | 22.65 |
| Trans / 1 | C++ | 41.65 | 47.66 | 24.13 |
| Trans / 4 | 原Python | 100.03 | 113.23 | 38.65 |
| Trans / 4 | 同线程Python ORT | 107.79 | 129.98 | 35.40 |
| Trans / 4 | C++ | 113.01 | 145.60 | 33.31 |
| CLIP / 1 | 原Python | 379.22 | 411.53 | 2.62 |
| CLIP / 1 | 同线程Python ORT | 360.09 | 399.97 | 2.74 |
| CLIP / 1 | C++ | 386.84 | 437.39 | 2.56 |
| CLIP / 4 | 原Python | 1095.35 | 1458.76 | 3.45 |
| CLIP / 4 | 同线程Python ORT | 1126.52 | 1272.82 | 3.51 |
| CLIP / 4 | C++ | 1129.74 | 1692.70 | 3.22 |

2线程对照中，4并发 Trans 的 C++ 为28.19、原版22.95 crops/s；单并发又明显较慢，不能截取一个更快场景声称普遍加速。CLIP 的4图动态 batch（4线程、1并发）为 C++2.31、原逐图2.59 crops/s，反而更慢，故生产默认模型 batch=1。相同文件内容的 CLIP/ViT 在不同测量时段也有速度差异，进一步说明单次数字不能作为保证。

这里已经完成线程预算、同帧调度、有界会话复用和模型批大小控制，但**没有证明车辆 C++ 在所有负载下更快**。若当前现场 Python ORT 更快，应使用原版本；吞吐要求高、识别难度低可测轻模型，准确度要求高可测CLIP并降低重复ReID采样频率。减少重复采样需要保留首次/更好视角/失活前样本，现有采样器和预算继续负责这些门控。

原始结果：[2线程单并发](benchmarks/vehicle-b1-w1.json)、[2线程4并发](benchmarks/vehicle-b1-w4.json)、[4线程单并发](benchmarks/vehicle-t4-w1.json)、[4线程4并发](benchmarks/vehicle-t4-w4.json)、[4图动态batch](benchmarks/vehicle-b4-t4-w1.json)。每份包含模型SHA、标注图片SHA、环境、完整相似度矩阵和数值一致性。

真实 CLIP 裁剪另做生产批接口对照：模型 batch 上限1、2、4提取这12张车体的归一化向量均与逐图结果最大绝对差为0，排序一致；0.80/0.04校准下均接受4个正确、0个错误。[批量一致性记录](benchmarks/vehicle-batch-parity.json)

## 6. 复验与当前验证范围

```powershell
python -m pytest backend/unittests/test_vehicle_cpp_runtime.py backend/unittests/test_vehicle_reid_contract.py backend/unittests/test_reid_cpp_runtime.py -q -p no:cacheprovider
python backend/scripts/benchmark_vehicle_cpp.py --models backend/uploads/models/base/clip-reid-vehicle/clip_vehicle_reid.onnx --threads 4 --workers 1 --iterations 20 --output backend/runtime/reid_cpp/vehicle-verify.json
# 原有车辆离线检测/完整视频评估工具也可选择 C++：
python backend/scripts/benchmark_vehicle_reid.py --reid backend/uploads/models/base/clip-reid-vehicle/clip_vehicle_reid.onnx --vehicle-runtime cpp --stage all --output backend/runtime/reid_cpp/vehicle-video-eval
```

最终相关回归 **337 passed、1 skipped、1 deselected**，管理端 Vite 构建通过。覆盖原生辅助输入5种dtype/标量、并发、flat输出、跨镜绑定、同帧预算、批限制、零向量、哈希空间、严格失败、自动退化、流水线模型校验、ID/key冲突与API400映射、旧人车/场景/OpenVINO回归。跳过为可选真实FAISS未安装；单独排除的是上一轮已确认的既有OCR fixture路径基线失败，未计为通过。

本次没有重跑完整两视频的身份标签评估，没有报告端到端FPS、IDF1或生产误合并率。完整视频工具的 C++ 参数已接通，可在更大标注集上复验。启动后观察实际 `vehicleReid` provider、degradedReason、分段耗时、候选及人工核对结果，再选定现场配置。

源码定位：`native/reid/src/reid_runtime.cpp`、`services/reid_cpp.py`、`services/vehicle_reid_feat.py`、`services/mtmc_engine.py`、`routes/mtmc.py`、前端 `views/ai/mtmc/index.vue`；基准脚本 `scripts/benchmark_vehicle_cpp.py`。
