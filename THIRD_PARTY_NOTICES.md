# 第三方声明（THIRD_PARTY_NOTICES）

本项目（Apache-2.0）集成了多种开源库、模型权重与数据集来源。  
**使用、分发模型权重时，除遵守本仓库 Apache-2.0 外，还必须遵守各上游许可证与使用条款。**  
权重通常通过「模型管理 → 拉取」下载到本地 `uploads/` / `models/`，**默认不随 Git 分发**。

本文为尽职调查清单，可能未穷尽；发现遗漏请提 PR 补全。最后核对：2026-07-25。

---

## 1. 主要 Python / 前端依赖（摘要）

详细版本以 `backend/requirements.txt`、`frontend/package.json` 为准。安装依赖即接受其各自许可证。

| 组件 | 典型用途 | 许可证（常见声明） | 备注 |
|------|----------|-------------------|------|
| Flask 生态 | Web API | BSD-3-Clause | Flask / Flask-Cors 等 |
| SQLAlchemy / PyMySQL | ORM / MySQL | MIT / MIT | |
| PyJWT / Flask-JWT-Extended | 认证 | MIT | |
| Ultralytics | YOLO 训练与推理 | **AGPL-3.0** | **商用请阅读 [Ultralytics License](https://www.ultralytics.com/license)** |
| OpenVINO | YOLO CPU 加速 | Apache-2.0 | Intel OpenVINO |
| PyTorch / torchvision / torchaudio | 深度学习运行时 | BSD-style | |
| transformers / huggingface_hub | HF 模型 | Apache-2.0 | |
| onnxruntime | ORT 推理 | MIT | |
| opencv-python | 图像/视频 | Apache-2.0 | |
| insightface | 人脸检测识别 | MIT（**代码**） | **模型权重条款更严，见 §2.1** |
| rtmlib | RTMO/RTMPose | Apache-2.0 | |
| funasr / modelscope | 语音识别 | Apache-2.0 等 | 以包与模型页为准 |
| rapidocr_onnxruntime / RapidOCR | OCR | Apache-2.0 | |
| rfdetr | RF-DETR | Apache-2.0 | |
| MobileSAM | 交互分割 | Apache-2.0 | git 依赖 |
| Vue 3 / Vite / Element Plus / Pinia / Axios / ECharts | 前端 | MIT 等 | 见 package.json |

> **重要：** Ultralytics（YOLO）默认为 **AGPL-3.0**。若你将本项目用于闭源商业分发，请自行评估 AGPL 义务或购买 Ultralytics 企业许可，并与法务确认。

---

## 2. 模型 / 权重 / 数据集来源（种子与常用）

### 2.1 已人工核对的常用模型（精确许可证链接）

下列条目已对照 `backend/seed.py` 的 `source_url`，并打开上游页面核对（核对日：**2026-07-25**）。

| model_key / 名称 | 来源 | 任务 | 许可证（上游声明） | 许可证 / 模型卡链接 | 许可证注意 |
|-----------|---------------------------|------|--------------------|------------------------|------------|
| `yolo26n` / `yolo26s` | [Ultralytics/YOLO26](https://huggingface.co/Ultralytics/YOLO26)（`#yolo26n.pt` / `#yolo26s.pt`） | 目标检测 | **AGPL-3.0** | [HF 模型卡 `license: agpl-3.0`](https://huggingface.co/Ultralytics/YOLO26) · [AGPL-3.0 全文](https://www.gnu.org/licenses/agpl-3.0.html) · [Ultralytics 许可说明/企业选项](https://www.ultralytics.com/license) · [GitHub LICENSE](https://github.com/ultralytics/ultralytics/blob/main/LICENSE) | **注意：AGPL。** 官方 YOLO26 权重与 Ultralytics 栈常按 AGPL 约束；闭源商用需评估开源义务或企业许可。 |
| `rf-detr-medium` | [Roboflow/rf-detr-medium](https://huggingface.co/Roboflow/rf-detr-medium) | 目标检测 | Apache-2.0 | [HF 模型卡 `license: apache-2.0`](https://huggingface.co/Roboflow/rf-detr-medium) · [Apache-2.0 全文](https://www.apache.org/licenses/LICENSE-2.0) | Roboflow RF-DETR Medium（COCO）；模型卡声明 Apache-2.0，商用相对友好，仍须保留版权与 NOTICE。 |
| `mobile-sam` | [ChaoningZhang/MobileSAM](https://github.com/ChaoningZhang/MobileSAM) | 交互分割 | Apache-2.0 | [GitHub LICENSE（Apache-2.0）](https://github.com/ChaoningZhang/MobileSAM/blob/master/LICENSE) · [仓库页](https://github.com/ChaoningZhang/MobileSAM) | MobileSAM 代码与仓库许可证为 Apache-2.0；分发时保留许可证与归属声明。 |
| `detr-resnet-50` | [facebook/detr-resnet-50](https://huggingface.co/facebook/detr-resnet-50) | 目标检测 | Apache-2.0 | [HF 模型卡 `license: apache-2.0`](https://huggingface.co/facebook/detr-resnet-50) · [Apache-2.0 全文](https://www.apache.org/licenses/LICENSE-2.0) | Facebook DETR + ResNet-50（COCO）；模型卡声明 Apache-2.0。 |
| `vit-base` | [google/vit-base-patch16-224](https://huggingface.co/google/vit-base-patch16-224) | 图像分类 | Apache-2.0 | [HF 模型卡 `license: apache-2.0`](https://huggingface.co/google/vit-base-patch16-224) · [Apache-2.0 全文](https://www.apache.org/licenses/LICENSE-2.0) | Google ViT base（ImageNet）；模型卡声明 Apache-2.0。 |
| `insightface-buffalo-s` / `insightface-buffalo-l` | [buffalo_s.zip](https://github.com/deepinsight/insightface/releases/download/) / [buffalo_l.zip](https://github.com/deepinsight/insightface/releases/download/) | 人脸识别 | **代码 MIT；权重默认非商用研究** | [InsightFace License 说明](https://github.com/deepinsight/insightface#license) · 商用识别包联系 [recognition-oss-pack@insightface.ai](mailto:recognition-oss-pack@insightface.ai) | **注意：特殊条款。** 代码 MIT 可商用；**含标注数据训练的模型（含 buffalo 等）默认仅非商用研究**；商用须另洽官方。另须遵守人脸数据隐私合规。 |

### 2.2 其余常用模型（许可证待继续补链）

下列 `model_key` 来自 `backend/seed.py` 及业务绑定，许可证以**上游页面当前声明**为准，拉取前请复核。

| model_key / 名称 | 来源 | 任务 | 许可证注意 |
|------------------|------|------|------------|
| yolo26n-plate | https://huggingface.co/CodexParas/car-plate-detection-yolov26 | 车牌 bbox | 见 HF 模型卡；YOLO/Ultralytics 衍生权重还需关注 AGPL 传导风险 |
| yolo26s-plate-pose | https://raw.githubusercontent.com/we0091234/yolo26-plate/main/weights/yolo26s-plate-detect.pt | 车牌四点 | 见 [we0091234/yolo26-plate](https://github.com/we0091234/yolo26-plate) 仓库许可 |
| yolo26n-pose / yolo26n-obb | openvision（HF） | 姿态 / OBB | 见模型卡 |
| yolo26n-p2-plate | https://docs.ultralytics.com/models/yolo26/ | 自训入口 | 无官方预训练；自训权重许可取决于你的训练数据与基座 |
| yolov11-license-plate-* | morsetechlab（HF） | 车牌 | 见模型卡 |
| yolov8-license-plate | Koushim（HF） | 车牌 | 见模型卡 |
| keremberke yolov5* plate / table | HF keremberke/* | 车牌/表格 | 见模型卡 |
| PP-OCRv* / RapidOCR / RapidTable | RapidAI / ModelScope | OCR/表格 | Apache-2.0 常见；以模型页为准 |
| SenseVoice / Paraformer / Fun-ASR | ModelScope / FunASR | ASR | 见模型页 |
| moonshine-tiny | UsefulSensors（HF） | ASR | 见模型卡 |
| rtmo-* / rtmpose-* | OpenMMLab 生态 ONNX | 姿态 | 见 rtmlib / 上游 |
| yolo11s-ball | Good-Badminton 相关权重 | 羽毛球 | 见绑定说明与上游 |
| rf-detr-seg-medium | https://huggingface.co/Roboflow/rf-detr-seg-medium | 实例分割 | 与 rf-detr-medium 同系，请打开模型卡确认（常见 Apache-2.0） |
| finbert | https://huggingface.co/ProsusAI/finbert | 文本分类 | **HF 模型卡目前未声明 `license` 字段**；使用/分发前请自行与上游确认，勿默认等同 Apache-2.0 |
| Roboflow 宇宙模型（如 rocket-detect） | Roboflow Universe | 检测 | 遵守 Roboflow / 数据集条款 |
| 训练集（用户自备） | 用户提供 | 训练 | **贡献者不得上传含隐私的未授权数据** |

人脸底库图片与 embedding 属于**用户数据**，不在开源分发范围内；部署方需自行满足隐私与合规要求。

---

## 3. 文档与代码中的第三方引用

- 羽毛球分析思路参考社区项目 Good-Badminton 等（见代码注释），实现为本仓库自有代码时仍须尊重其许可与致谢习惯。
- README / 文档中的截图与演示视频若含第三方素材，仅用于说明，不授予额外商标权。

---

## 4. 商标

「YOLO」「Ultralytics」「InsightFace」「OpenVINO」「Roboflow」等为各自权利人商标。本项目名称 TigerPro / Tiger AI Platform 与上述商标无隶属关系。

---

## 5. 如何更新本文

新增依赖、模型种子或数据集绑定时，请在同一 PR 中更新本文件对应表格，并在 Issue/PR 中注明上游许可证链接。
