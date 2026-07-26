# 第三方声明（THIRD_PARTY_NOTICES）

本项目（Apache-2.0）集成了多种开源库、模型权重与数据集来源。  
**使用、分发模型权重时，除遵守本仓库 Apache-2.0 外，还必须遵守各上游许可证与使用条款。**  
权重通常通过「模型管理 → 拉取」下载到本地 `uploads/` / `models/`，**默认不随 Git 分发**。

本文为尽职调查清单，可能未穷尽；发现遗漏请提 PR 补全。最后核对：2026-07-26。

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
| funasr / modelscope | 语音识别 | Apache-2.0 等 | 以包与模型页为准；部分权重为 FunASR Model License |
| rapidocr_onnxruntime / RapidOCR | OCR | Apache-2.0 | |
| rfdetr | RF-DETR | Apache-2.0 | Nano–Large 常见 Apache-2.0；XL/2XL 另见 Roboflow PML |
| MobileSAM | 交互分割 | Apache-2.0 | git 依赖 |
| Vue 3 / Vite / Element Plus / Pinia / Axios / ECharts | 前端 | MIT 等 | 见 package.json |

> **重要：** Ultralytics（YOLO）默认为 **AGPL-3.0**。若你将本项目用于闭源商业分发，请自行评估 AGPL 义务或购买 Ultralytics 企业许可，并与法务确认。

---

## 2. 模型 / 权重 / 数据集来源（种子与常用）

下列条目对照 `backend/seed.py` 的 `model_key` / `source_url`，并打开上游页面或 HF/GitHub API 核对（核对日：**2026-07-25**）。

### 2.1 核心视觉基座（已人工核对）

| model_key / 名称 | 来源 | 任务 | 许可证（上游声明） | 许可证 / 模型卡链接 | 许可证注意 |
|-----------|---------------------------|------|--------------------|------------------------|------------|
| `yolo26n` / `yolo26s` | [Ultralytics/YOLO26](https://huggingface.co/Ultralytics/YOLO26)（`#yolo26n.pt` / `#yolo26s.pt`） | 目标检测 | **AGPL-3.0** | [HF `license: agpl-3.0`](https://huggingface.co/Ultralytics/YOLO26) · [AGPL-3.0 全文](https://www.gnu.org/licenses/agpl-3.0.html) · [Ultralytics 企业选项](https://www.ultralytics.com/license) · [GitHub LICENSE](https://github.com/ultralytics/ultralytics/blob/main/LICENSE) | **注意：AGPL。** 闭源商用需评估开源义务或企业许可。 |
| `rf-detr-medium` | [Roboflow/rf-detr-medium](https://huggingface.co/Roboflow/rf-detr-medium) | 目标检测 | Apache-2.0 | [HF `license: apache-2.0`](https://huggingface.co/Roboflow/rf-detr-medium) · [Apache-2.0 全文](https://www.apache.org/licenses/LICENSE-2.0) | COCO；保留版权与 NOTICE。 |
| `rf-detr-seg-medium` | [Roboflow/rf-detr-seg-medium](https://huggingface.co/Roboflow/rf-detr-seg-medium) | 实例分割 | Apache-2.0 | [HF `license: apache-2.0`](https://huggingface.co/Roboflow/rf-detr-seg-medium) · [Seg 许可说明（N–L Apache；XL/2XL 为 PML）](https://playground.roboflow.com/models/roboflow/rf-detr-segmentation) | Medium 为 Apache-2.0。 |
| `mobile-sam` | [ChaoningZhang/MobileSAM](https://github.com/ChaoningZhang/MobileSAM) | 交互分割 | Apache-2.0 | [GitHub LICENSE](https://github.com/ChaoningZhang/MobileSAM/blob/master/LICENSE) | 分发时保留许可证与归属。 |
| `detr-resnet-50` | [facebook/detr-resnet-50](https://huggingface.co/facebook/detr-resnet-50) | 目标检测 | Apache-2.0 | [HF `license: apache-2.0`](https://huggingface.co/facebook/detr-resnet-50) | COCO。 |
| `vit-base` | [google/vit-base-patch16-224](https://huggingface.co/google/vit-base-patch16-224) | 图像分类 | Apache-2.0 | [HF `license: apache-2.0`](https://huggingface.co/google/vit-base-patch16-224) | ImageNet。 |
| `insightface-buffalo-s` / `insightface-buffalo-l` | [buffalo_s.zip](https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_s.zip) / [buffalo_l.zip](https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip) | 人脸识别 | **代码 MIT；权重默认非商用研究** | [InsightFace License](https://github.com/deepinsight/insightface#license) · 商用联系 [recognition-oss-pack@insightface.ai](mailto:recognition-oss-pack@insightface.ai) | **特殊条款。** 含标注数据训练的模型默认仅研究；商用须另洽。人脸数据须隐私合规。 |
| `yoloe-26s-seg` | [ultralytics assets yoloe-26s-seg.pt](https://github.com/ultralytics/assets/releases/download/v8.4.0/yoloe-26s-seg.pt) | 开放词汇分割 | **AGPL-3.0**（Ultralytics 栈） | [Ultralytics LICENSE](https://github.com/ultralytics/ultralytics/blob/main/LICENSE) · [企业选项](https://www.ultralytics.com/license) | 官方权重/栈按 AGPL。 |

### 2.2 检测 / 车牌 / 文档 OCR·表格（已补链）

| model_key / 名称 | 来源 | 任务 | 许可证（上游声明） | 许可证 / 模型卡链接 | 许可证注意 |
|------------------|------|------|--------------------|------------------------|------------|
| `yolo26n-plate` | [CodexParas/car-plate-detection-yolov26](https://huggingface.co/CodexParas/car-plate-detection-yolov26)（`#best.pt`） | 车牌 bbox | **Apache-2.0** | [HF `license: apache-2.0`](https://huggingface.co/CodexParas/car-plate-detection-yolov26) | YOLO26 微调；**另关注 Ultralytics AGPL 传导**。 |
| `yolo26s-plate-pose` | [we0091234/yolo26-plate](https://github.com/we0091234/yolo26-plate) 权重 | 车牌四点 pose | **AGPL-3.0** | [GitHub 仓 license: AGPL-3.0](https://github.com/we0091234/yolo26-plate) · [AGPL-3.0 全文](https://www.gnu.org/licenses/agpl-3.0.html) | **注意：AGPL。** |
| `yolo26n-pose` | [openvision/yolo26-n-pose](https://huggingface.co/openvision/yolo26-n-pose) | 姿态 | **AGPL-3.0** | [HF `license: agpl-3.0`](https://huggingface.co/openvision/yolo26-n-pose) | **注意：AGPL。** |
| `yolo26n-obb` | [openvision/yolo26-n-obb](https://huggingface.co/openvision/yolo26-n-obb) | OBB | **AGPL-3.0** | [HF `license: agpl-3.0`](https://huggingface.co/openvision/yolo26-n-obb) | **注意：AGPL。** |
| `yolo26n-p2-plate` | [YOLO26 文档](https://docs.ultralytics.com/models/yolo26/) | 自训脚手架 | 无官方预训练 | 同上文档 · [Ultralytics License](https://www.ultralytics.com/license) | 自训权重许可（ AGPL 栈）。 |
| `yolov11-license-plate-n` / `-s` | [morsetechlab/yolov11-license-plate-detection](https://huggingface.co/morsetechlab/yolov11-license-plate-detection) | 车牌 | **AGPL-3.0** | [HF `license: agpl-3.0`](https://huggingface.co/morsetechlab/yolov11-license-plate-detection) | **注意：AGPL。** |
| `yolov8-license-plate` | [Koushim/yolov8-license-plate-detection](https://huggingface.co/Koushim/yolov8-license-plate-detection) | 车牌 | **MIT** | [HF `license: mit`](https://huggingface.co/Koushim/yolov8-license-plate-detection) · [MIT 全文](https://opensource.org/licenses/MIT) | 卡页 MIT；**Ultralytics 推理栈仍可能 AGPL 传导**。 |
| `keremberke-yolov5n-license-plate` / `…-yolov5m-…` | [keremberke/yolov5n-license-plate](https://huggingface.co/keremberke/yolov5n-license-plate) / [yolov5m](https://huggingface.co/keremberke/yolov5m-license-plate) | 车牌 | **HF 卡页未声明 `license`**；YOLOv5 基座 **AGPL-3.0** | 模型卡页 · [ultralytics/yolov5 LICENSE=AGPL-3.0](https://github.com/ultralytics/yolov5) | **勿默认等同 Apache/MIT**；按 AGPL 基座评估。 |
| `yolov8m-table-extraction` | [keremberke/yolov8m-table-extraction](https://huggingface.co/keremberke/yolov8m-table-extraction) | 表格检测 | **AGPL-3.0** | [HF `license: agpl-3.0`](https://huggingface.co/keremberke/yolov8m-table-extraction) | **注意：AGPL。** |
| `PP-OCRv6_small_det_onnx` / `PP-OCRv6_small_rec_onnx` | [RapidAI/RapidOCR](https://www.modelscope.cn/models/RapidAI/RapidOCR) | OCR det/rec | **Apache-2.0** | [RapidOCR GitHub Apache-2.0](https://github.com/RapidAI/RapidOCR) · [PaddleOCR Apache-2.0](https://github.com/PaddlePaddle/PaddleOCR/blob/main/LICENSE) | 以 ModelScope/仓库当前声明为准。 |
| `rapidtable-slanet-plus` | [RapidAI/RapidTable slanet-plus.onnx](https://www.modelscope.cn/models/RapidAI/RapidTable/resolve/v2.0.0/slanet-plus.onnx) | 表格结构 | **Apache-2.0** | [RapidTable LICENSE](https://github.com/RapidAI/RapidTable/blob/main/LICENSE) | 保留 NOTICE。 |
| `fire-smoke-detection` | [SalahALHaismawi/yolov26-fire-detection](https://huggingface.co/SalahALHaismawi/yolov26-fire-detection) | 烟火检测 | 卡页 **MIT** | [HF `license: mit`](https://huggingface.co/SalahALHaismawi/yolov26-fire-detection) | YOLO26 微调；**关注 AGPL 传导**。 |
| `ppe-detection` | [Hexmon/vyra-yolo-ppe-detection](https://huggingface.co/Hexmon/vyra-yolo-ppe-detection) | PPE | **CC-BY-4.0** | [HF `license: cc-by-4.0`](https://huggingface.co/Hexmon/vyra-yolo-ppe-detection) · [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | 需署名。 |
| `brain-tumor-yolo-opennoor` | [OpenNoorIlm/…Brain-Tumor-Yolo…](https://huggingface.co/OpenNoorIlm/Noor-Ul-Ilm-Brain-Tumor-Yolo-1.0-24-06-2026) | 医学影像 | **MIT**（`base_model: Ultralytics/YOLO26`） | [HF `license: mit`](https://huggingface.co/OpenNoorIlm/Noor-Ul-Ilm-Brain-Tumor-Yolo-1.0-24-06-2026) | 医学场景另遵数据与临床合规；**AGPL 基座传导风险**。 |
| `rocket-detect-nasaspaceflight` | [Roboflow Universe rocket-detect](https://universe.roboflow.com/nasaspaceflight/rocket-detect/model/2) | 火箭检测 | **CC-BY-4.0** | [HF `license: cc-by-4.0`](https://huggingface.co/Hexmon/vyra-yolo-ppe-detection) · [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)·项目页 · [Roboflow 条款](https://roboflow.com/terms) | 遵守 Universe 与数据集许可，勿默认 Apache-2.0。 |

### 2.3 语音识别 / 语音合成（已补链）

| model_key / 名称 | 来源 | 任务 | 许可证（上游声明） | 许可证 / 模型卡链接 | 许可证注意 |
|------------------|------|------|--------------------|------------------------|------------|
| `sensevoice-small` | [iic/SenseVoiceSmall](https://modelscope.cn/models/iic/SenseVoiceSmall)（HF 镜像 [FunAudioLLM/SenseVoiceSmall](https://huggingface.co/FunAudioLLM/SenseVoiceSmall)） | ASR+情感 | **Apache-2.0** | [HF 卡 · license_link](https://huggingface.co/FunAudioLLM/SenseVoiceSmall) · [MODEL_LICENSE 全文](https://github.com/modelscope/FunASR/blob/main/MODEL_LICENSE) | **非标准 OSI 许可证。** 可使用/修改/分享，须保留出处与模型名；以协议原文为准。 |
| `sensevoice-small-onnx` | [iic/SenseVoiceSmall-onnx](https://modelscope.cn/models/iic/SenseVoiceSmall-onnx) | ASR onnx | **Apache-2.0** | ModelScope 模型页 · 建议仍对照 [MODEL_LICENSE](https://github.com/modelscope/FunASR/blob/main/MODEL_LICENSE) | **以你实际下载工件的模型页为准**；官方 Small 卡为 FunASR Model License。 |
| `paraformer-zh` | [funasr/paraformer-zh](https://huggingface.co/funasr/paraformer-zh) | ASR | **Apache-2.0** | [HF `license: apache-2.0`](https://huggingface.co/funasr/paraformer-zh) | 友好；保留 NOTICE。 |
| `fun-asr-nano` | [FunAudioLLM/Fun-ASR-Nano-2512](https://modelscope.cn/models/FunAudioLLM/Fun-ASR-Nano-2512)（[HF同名](https://huggingface.co/FunAudioLLM/Fun-ASR-Nano-2512)） | ASR | **HF 元数据 `apache-2.0`**；**ModelScope  页未声明 License** | [HF README frontmatter `license:<br/>  apache-2.0`](https://huggingface.co/FunAudioLLM/Fun-ASR-Nano-2512/blob/main/README.md) · [Fun-ASR 代码仓  Apache-2.0](https://github.com/FunAudioLLM/Fun-ASR) | HF API/`README.md`  YAML 声明 `license: apache-2.0`，官方代码仓为 Apache-2.0；**模型仓内无独立 LICENSE 文件**。商用前建议再打开 HF/MS  页复核。 |
| `moonshine-tiny` | [UsefulSensors/moonshine-tiny](https://huggingface.co/UsefulSensors/moonshine-tiny) | ASR（英） | **MIT** | [HF `license: mit`](https://huggingface.co/UsefulSensors/moonshine-tiny) | 英文边缘 ASR。 |
| `mms-tts-eng` | [facebook/mms-tts-eng](https://huggingface.co/facebook/mms-tts-eng) | TTS | **CC-BY-NC-4.0** | [HF `license: cc-by-nc-4.0`](https://huggingface.co/facebook/mms-tts-eng) · [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) | **注意：非商用。** 商用需另获授权。 |
| `melotts-zh-en` | [wolfofbackstreet/melotts_chinese_mix_english_onnx](https://huggingface.co/wolfofbackstreet/melotts_chinese_mix_english_onnx) | TTS onnx | **MIT** | [HF `license: mit`](https://huggingface.co/wolfofbackstreet/melotts_chinese_mix_english_onnx) | 基座 MeloTTS；以卡页为准。 |
| `vibevoice-realtime` | [microsoft/VibeVoice-Realtime-0.5B](https://modelscope.cn/models/microsoft/VibeVoice-Realtime-0.5B) | TTS | 代码仓常见 **MIT**；权重以模型页为**MIT** | [microsoft/VibeVoice](https://github.com/microsoft/VibeVoice) · ModelScope 模型页 | 拉取前复核 ModelScope/HF 卡页 license。 |
| `linly-talker` | [Kedreamix/Linly-Talker](https://huggingface.co/Kedreamix/Linly-Talker)（[GitHub](https://github.co<br/>  m/Kedreamix/Linly-Talker)） | 数字人 | **项目代码 MIT**；**HF 卡页无 `license` 字段**；捆绑权重各依上游 | [GitHub  LICENSE=MIT](https://github.com/Kedreamix/Linly-Talker/blob/main/LICENSE) · [HF  模型仓](https://huggingface.co/Kedreamix/Linly-Talker) · [SadTalker  Apache-2.0](https://github.com/OpenTalker/SadTalker/blob/main/LICENSE) | seed 为脚手架（需 GPU + SadTalker  等运行环境）。**Linly-Talker 本体 MIT**；HF 仓为多模型合集（SadTalker / Wav2Lip / GFPGAN / Qwen  等），**各组件许可证不同**，商用前须逐项打开上游许可，勿将整包默认等同 MIT。 |

### 2.4 文本 / NLP（已补链）

| model_key / 名称 | 来源 | 任务 | 许可证（上游声明） | 许可证 / 模型卡链接 | 许可证注意 |
|------------------|------|------|--------------------|------------------------|------------|
| `finbert` | [ProsusAI/finbert](https://huggingface.co/ProsusAI/finbert) | 金融情感 | **HF 卡页无 `license` 字段**；代码仓 **Apache-2.0** | [HF 模型卡（无 license 元数据）](https://huggingface.co/ProsusAI/finbert) · [ProsusAI/finBERT Apache-2.0](https://github.com/ProsusAI/finBERT) · [LICENSE 文件](https://github.com/ProsusAI/finBERT/blob/master/LICENSE) | **勿默认 Apache。** 权重分发建议对照代码仓 Apache-2.0 并保留 NOTICE；有疑义询上游。 |
| `bert-emotion` | [bhadresh-savani/bert-base-uncased-emotion](https://huggingface.co/bhadresh-savani/bert-base-uncased-emotion) | 情绪分类 | Apache-2.0 | [HF `license: apache-2.0`](https://huggingface.co/bhadresh-savani/bert-base-uncased-emotion) | 基于 BERT 微调；Apache-2.0，分发时保留版权与 NOTICE。 |
| `bart-mnli` | [facebook/bart-large-mnli](https://huggingface.co/facebook/bart-large-mnli) | 零样本分类 | **MIT** | [HF `license: mit`](https://huggingface.co/facebook/bart-large-mnli) | Meta BART 零样本 NLI；MIT，保留版权声明即可。 |
| `bert-fill-mask` | [bert-base-uncased](https://huggingface.co/bert-base-uncased)（google-bert） | 完形填空 | Apache-2.0 | [HF `license: apache-2.0`](https://huggingface.co/google-bert/bert-base-uncased) | Google BERT 基座；Apache-2.0，保留 NOTICE。 |
| `distilbart-cnn` | [sshleifer/distilbart-cnn-12-6](https://huggingface.co/sshleifer/distilbart-cnn-12-6) | 摘要 | Apache-2.0 | [HF `license: apache-2.0`](https://huggingface.co/sshleifer/distilbart-cnn-12-6) | BART  蒸馏摘要模型；Apache-2.0，保留 NOTICE。 |
| `opus-mt-en-zh` | [Helsinki-NLP/opus-mt-en-zh](https://huggingface.co/Helsinki-NLP/opus-mt-en-zh) | 翻译 | Apache-2.0 | [HF `license: apache-2.0`](https://huggingface.co/Helsinki-NLP/opus-mt-en-zh) | Helsinki-NLP  OPUS-MT；Apache-2.0，保留 NOTICE。 |
| `bert-ner` | [dslim/bert-base-NER](https://huggingface.co/dslim/bert-base-NER) | NER | **MIT** | [HF `license: mit`](https://huggingface.co/dslim/bert-base-NER) | 基于 BERT 的 NER；MIT，保留版权声明即可。 |
| `distilbert-squad` | [distilbert-base-cased-distilled-squad](https://huggingface.co/distilbert-base-cased-distilled-squad) | 问答 | Apache-2.0 | [HF `license: apache-2.0`](https://huggingface.co/distilbert/distilbert-base-cased-distilled-squad) | istilBERT +  SQuAD；Apache-2.0，保留 NOTICE。 |

### 2.5 姿态估计 / 羽毛球（已补链）

| model_key / 名称 | 来源 | 任务 | 许可证（上游声明） | 许可证 / 模型卡链接 | 许可证注意 |
|------------------|------|------|--------------------|------------------------|------------|
| `yolo11n-pose` | [Ultralytics/YOLO11](https://huggingface.co/Ultralytics/YOLO11)（`#yolo11n-pose.pt`） | 姿态 | **AGPL-3.0** | [HF `license: agpl-3.0`](https://huggingface.co/Ultralytics/YOLO11) · [企业选项](https://www.ultralytics.com/license) | **注意：AGPL。** |
| `yolo11s-ball` | [Good-Badminton yolo11s-ball.pt](https://github.com/yo-WASSUP/Good-Badminton/releases/download/v0.1.0/yolo11s-ball.pt) | 羽毛球检测 | **Apache-2.0**（项目声明） | [Good-Badminton 许可说明](https://github.com/yo-WASSUP/Good-Badminton) | 项目声明代码与该权重 Apache-2.0；**若用 Ultralytics 推理仍评估 AGPL 栈**。 |
| `rtmo-s` | [RTMO-S ONNX zip](https://download.openmmlab.com/mmpose/v1/projects/rtmo/onnx_sdk/rtmo-s_8xb32-600e_body7<br/>  -640x640-dac2bf74_20231211.zip)（OpenMMLab） | 姿态 | **Apache-2.0** | [mmpose  LICENSE](https://github.com/open-mmlab/mmpose/blob/main/LICENSE) · [rtmlib  LICENSE](https://github.com/Tau-J/rtmlib/blob/main/LICENSE) · [RTMO  权重目录](https://download.openmmlab.com/mmpose/v1/projects/rtmo/) · [RTMO  论文页/项目](https://github.com/open-mmlab/mmpose/tree/main/projects/rtmo) | eed 权重为 OpenMMLab 官方 ONNX  SDK；推理库 rtmlib 与 mmpose 均为 Apache-2.0。 |
| `rtmo-m` | [RTMO-M ONNX zip](https://download.openmmlab.com/mmpose/v1/projects/rtmo/onnx_sdk/rtmo-m_16xb16-600e_body<br/>  7-640x640-39e78cc4_20231211.zip)（OpenMMLab） | 姿态 | **Apache-2.0** | [mmpose  LICENSE](https://github.com/open-mmlab/mmpose/blob/main/LICENSE) · [rtmlib  LICENSE](https://github.com/Tau-J/rtmlib/blob/main/LICENSE) · [RTMO  权重目录](https://download.openmmlab.com/mmpose/v1/projects/rtmo/) | 同上 |
| `rtmpose-m` | [RTMPose-M body7 ONNX zip](https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/onnx_sdk/rtmpos<br/>  e-m_simcc-body7_pt-body7_420e-256x192-e48f03d0_20230504.zip)（OpenMMLab） | 姿态 | **Apache-2.0** | [mmpose  LICENSE](https://github.com/open-mmlab/mmpose/blob/main/LICENSE) · [rtmlib  LICENSE](https://github.com/Tau-J/rtmlib/blob/main/LICENSE) · [RTMPose  权重目录](https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/) · [RTMPose  项目](https://github.com/open-mmlab/mmpose/tree/main/projects/rtmpose) | body7 姿态；Apache-2.0，保留 NOTICE。 |
| `dwpose-m` | [RTMPose-M DW-UCOCO ONNX zip](https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/onnx_sdk/rtmp<br/>  ose-m_simcc-ucoco_dw-ucoco_270e-256x192-c8b76419_20230728.zip)（OpenMMLab；DWPose 全身） | 全身姿态 | **Apache-2.0** | [mmpose LICENSE](https://github.com/open-mmlab/mmpose/blob/main/LICENSE) · [DWPose  LICENSE](https://github.com/IDEA-Research/DWPose/blob/main/LICENSE) · [rtmlib  LICENSE](https://github.com/Tau-J/rtmlib/blob/main/LICENSE) · [权重目录](https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/) | seed 实为 **DWPose/UCOCO 训练的 RTMPose-M  wholebody ONNX**；mmpose / DWPose / rtmlib 均为 Apache-2.0。133 关键点全身。 |

### 2.6 用户数据与训练集

| 类型 | 说明 |
|------|------|
| 训练集（用户自备） | **贡献者不得上传含隐私的未授权数据**；自训权重许可取决于数据授权 + 基座模型许可。 |
| 人脸底库图片与 embedding | **用户数据**，不在开源分发范围内；部署方需满足隐私与合规。 |
| Roboflow Universe 等第三方数据集/托管模型 | 除模型卡外，遵守平台与数据集条款。 |

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
