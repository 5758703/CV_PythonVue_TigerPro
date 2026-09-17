"""Side-effect-free contract checks shared by scenario readiness and inference."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
from pathlib import Path
import re
from typing import Callable


@dataclass(frozen=True)
class ScenarioContractResult:
    weights_present: bool
    runtime_available: bool
    api_ready: bool
    reason: str | None
    weight_path: Path | None = None
    supported_precisions: tuple[str, ...] = ()


_CONTRACTS = {
    "efficient-sam": {
        "task": "interactive-segmentation",
        "library": "opencv-sam",
        "adapter": "efficient_sam",
        "extensions": frozenset((".onnx",)),
        "runtime": ("cv2",),
    },
    "mobile-sam": {
        "task": "interactive-segmentation",
        "library": "mobilesam",
        "adapter": "mobile_sam",
        "extensions": frozenset((".pt", ".pth")),
        "runtime": ("mobile_sam",),
    },
    "clip-reid-vehicle": {
        "task": "vehicle-reid",
        "library": "clip-reid",
        "adapter": "vehicle_reid_onnx",
        "extensions": frozenset((".onnx",)),
        "runtime": ("onnxruntime",),
    },
    "keremberke-yolov5m-license-plate": {
        "task": "object-detection",
        "library": "ultralytics",
        "adapter": "ultralytics_detection",
        "extensions": frozenset((".pt", ".pth", ".onnx", ".engine")),
        "runtime": ("ultralytics",),
    },
    "keremberke-yolov5n-license-plate": {
        "task": "object-detection",
        "library": "ultralytics",
        "adapter": "ultralytics_detection",
        "extensions": frozenset((".pt", ".pth", ".onnx", ".engine")),
        "runtime": ("ultralytics",),
    },
    "transreid-vehicle": {
        "task": "vehicle-reid",
        "library": "transreid",
        "adapter": "vehicle_reid_onnx",
        "extensions": frozenset((".onnx",)),
        "runtime": ("onnxruntime",),
    },
    "vehicle-vit-reid": {
        "task": "vehicle-reid",
        "library": "vit-reid",
        "adapter": "vehicle_reid_onnx",
        "extensions": frozenset((".onnx",)),
        "runtime": ("onnxruntime",),
    },
    "yolo26n-obb": {
        "task": "obb",
        "library": "ultralytics",
        "adapter": "ultralytics_obb",
        "extensions": frozenset((".pt", ".pth", ".onnx", ".engine")),
        "runtime": ("ultralytics",),
    },
    "yolo26n-p2-plate": {
        "task": "object-detection",
        "library": "ultralytics",
        "adapter": "ultralytics_detection",
        "extensions": frozenset((".pt", ".pth", ".onnx", ".engine")),
        "runtime": ("ultralytics",),
    },
    "yolo26n-plate": {
        "task": "object-detection",
        "library": "ultralytics",
        "adapter": "ultralytics_detection",
        "extensions": frozenset((".pt", ".pth", ".onnx", ".engine")),
        "runtime": ("ultralytics",),
    },
    "yolo26s-plate-pose": {
        "task": "pose-estimation",
        "library": "ultralytics",
        "adapter": "ultralytics_pose",
        "extensions": frozenset((".pt", ".pth", ".onnx", ".engine")),
        "runtime": ("ultralytics",),
    },
    "yolov11-license-plate-n": {
        "task": "object-detection",
        "library": "ultralytics",
        "adapter": "ultralytics_detection",
        "extensions": frozenset((".pt", ".pth", ".onnx", ".engine")),
        "runtime": ("ultralytics",),
    },
    "yolov11-license-plate-s": {
        "task": "object-detection",
        "library": "ultralytics",
        "adapter": "ultralytics_detection",
        "extensions": frozenset((".pt", ".pth", ".onnx", ".engine")),
        "runtime": ("ultralytics",),
    },
    "yolov8-license-plate": {
        "task": "object-detection",
        "library": "ultralytics",
        "adapter": "ultralytics_detection",
        "extensions": frozenset((".pt", ".pth", ".onnx", ".engine")),
        "runtime": ("ultralytics",),
    },
    "insightface-buffalo-l": {
        "task": "face-recognition",
        "library": "insightface",
        "adapter": "face_recognition",
        "extensions": frozenset((".onnx",)),
        "runtime": ("insightface",),
        "pack": "buffalo_l",
    },
    "insightface-buffalo-s": {
        "task": "face-recognition",
        "library": "insightface",
        "adapter": "face_recognition",
        "extensions": frozenset((".onnx",)),
        "runtime": ("insightface",),
        "pack": "buffalo_s",
    },
    "opencv-yunet-sface": {
        "task": "face-recognition",
        "library": "opencv-face",
        "adapter": "face_recognition",
        "extensions": frozenset((".onnx",)),
        "runtime": ("cv2",),
    },
    "brain-tumor-yolo-opennoor": {
        "task": "object-detection",
        "library": "ultralytics",
        "adapter": "ultralytics_detection",
        "extensions": frozenset((".pt", ".pth", ".onnx", ".engine")),
        "runtime": ("ultralytics",),
    },
    "inpainting-lama": {
        "task": "image-inpainting",
        "library": "opencv-lama",
        "adapter": "opencv_lama",
        "extensions": frozenset((".onnx",)),
        "runtime": ("cv2",),
    },
    "mobilenet-v2": {
        "task": "image-classification",
        "library": "opencv-dnn",
        "adapter": "opencv_dnn_classify",
        "extensions": frozenset((".onnx",)),
        "runtime": ("cv2",),
    },
    "vit-base": {
        "task": "image-classification",
        "library": "transformers",
        "adapter": "transformers_classify",
        "extensions": frozenset((".safetensors", ".bin", ".msgpack", ".pt", ".pth")),
        "runtime": ("transformers",),
    },
    "yolo-master-cls-n": {
        "task": "image-classification",
        "library": "yolo-master",
        "adapter": "yolo_master_classify",
        "extensions": frozenset((".pt", ".pth", ".onnx", ".engine")),
        "runtime": ("ultralytics",),
    },
    "vlm-fo1-3b": {
        "task": "object-detection",
        "library": "vlm-fo1",
        "adapter": "vlm_fo1",
        "extensions": frozenset((".safetensors", ".bin", ".pt", ".pth", ".json")),
        "runtime": ("torch", "transformers"),
    },
    "dwpose-m": {
        "task": "wholebody-pose-estimation",
        "library": "rtmlib",
        "adapter": "rtmlib_pose",
        "extensions": frozenset((".onnx", ".zip")),
        "runtime": ("rtmlib",),
    },
    "rtmo-m": {
        "task": "pose-estimation",
        "library": "rtmlib",
        "adapter": "rtmlib_pose",
        "extensions": frozenset((".onnx", ".zip")),
        "runtime": ("rtmlib",),
    },
    "rtmo-s": {
        "task": "pose-estimation",
        "library": "rtmlib",
        "adapter": "rtmlib_pose",
        "extensions": frozenset((".onnx", ".zip")),
        "runtime": ("rtmlib",),
    },
    "rtmpose-m": {
        "task": "pose-estimation",
        "library": "rtmlib",
        "adapter": "rtmlib_pose",
        "extensions": frozenset((".onnx", ".zip")),
        "runtime": ("rtmlib",),
    },
    "yolo-master-pose-n": {
        "task": "pose-estimation",
        "library": "yolo-master",
        "adapter": "yolo_master_pose",
        "extensions": frozenset((".pt", ".pth", ".onnx", ".engine")),
        "runtime": ("ultralytics",),
    },
    "yolo11n-pose": {
        "task": "pose-estimation",
        "library": "ultralytics",
        "adapter": "ultralytics_pose",
        "extensions": frozenset((".pt", ".pth", ".onnx", ".engine")),
        "runtime": ("ultralytics",),
    },
    "yolo26n-pose": {
        "task": "pose-estimation",
        "library": "ultralytics",
        "adapter": "ultralytics_pose",
        "extensions": frozenset((".pt", ".pth", ".onnx", ".engine")),
        "runtime": ("ultralytics",),
    },
    "ppe-detection": {
        "task": "object-detection",
        "library": "ultralytics",
        "adapter": "ultralytics_detection",
        "extensions": frozenset((".pt", ".pth", ".onnx", ".engine")),
        "runtime": ("ultralytics",),
    },
    "damoyolo-cigarette": {
        "task": "object-detection",
        "library": "modelscope",
        "adapter": "modelscope_detection",
        "extensions": frozenset((".safetensors", ".bin", ".pt", ".pth", ".onnx", ".json", ".pkl", ".params", ".model", ".pb")),
        "runtime": ("modelscope",),
    },
    "sec-fall-coco-yolov12m": {
        "task": "object-detection",
        "library": "ultralytics",
        "adapter": "ultralytics_detection",
        "extensions": frozenset((".pt", ".pth", ".onnx", ".engine")),
        "runtime": ("ultralytics",),
    },
    "sec-fall-yolo11n": {
        "task": "object-detection",
        "library": "ultralytics",
        "adapter": "ultralytics_detection",
        "extensions": frozenset((".pt", ".pth", ".onnx", ".engine")),
        "runtime": ("ultralytics",),
    },
    "sec-fight-nano": {
        "task": "object-detection",
        "library": "ultralytics",
        "adapter": "ultralytics_detection",
        "extensions": frozenset((".pt", ".pth", ".onnx", ".engine")),
        "runtime": ("ultralytics",),
    },
    "sec-fight-small": {
        "task": "object-detection",
        "library": "ultralytics",
        "adapter": "ultralytics_detection",
        "extensions": frozenset((".pt", ".pth", ".onnx", ".engine")),
        "runtime": ("ultralytics",),
    },
    "sec-fire-collision-yolo11": {
        "task": "object-detection",
        "library": "ultralytics",
        "adapter": "ultralytics_detection",
        "extensions": frozenset((".pt", ".pth", ".onnx", ".engine")),
        "runtime": ("ultralytics",),
    },
    "sec-fire-forest-yolov8": {
        "task": "object-detection",
        "library": "ultralytics",
        "adapter": "ultralytics_detection",
        "extensions": frozenset((".pt", ".pth", ".onnx", ".engine")),
        "runtime": ("ultralytics",),
    },
    "sec-fire-yolov8n": {
        "task": "object-detection",
        "library": "ultralytics",
        "adapter": "ultralytics_detection",
        "extensions": frozenset((".pt", ".pth", ".onnx", ".engine")),
        "runtime": ("ultralytics",),
    },
    "sec-helmet-yolov8s": {
        "task": "object-detection",
        "library": "ultralytics",
        "adapter": "ultralytics_detection",
        "extensions": frozenset((".pt", ".pth", ".onnx", ".engine")),
        "runtime": ("ultralytics",),
    },
    "sec-plate-yolov8": {
        "task": "object-detection",
        "library": "ultralytics",
        "adapter": "ultralytics_detection",
        "extensions": frozenset((".pt", ".pth", ".onnx", ".engine")),
        "runtime": ("ultralytics",),
    },
    "sec-ppe-yolo": {
        "task": "object-detection",
        "library": "ultralytics",
        "adapter": "ultralytics_detection",
        "extensions": frozenset((".pt", ".pth", ".onnx", ".engine")),
        "runtime": ("ultralytics",),
    },
    "sec-weapon-yolov8": {
        "task": "object-detection",
        "library": "ultralytics",
        "adapter": "ultralytics_detection",
        "extensions": frozenset((".pt", ".pth", ".onnx", ".engine")),
        "runtime": ("ultralytics",),
    },
    "yolo26-smoking-detection": {
        "task": "object-detection",
        "library": "ultralytics",
        "adapter": "ultralytics_detection",
        "extensions": frozenset((".pt", ".pth", ".onnx", ".engine")),
        "runtime": ("ultralytics",),
    },
    "yolo8-smoking-behavior": {
        "task": "object-detection",
        "library": "ultralytics",
        "adapter": "ultralytics_detection",
        "extensions": frozenset((".pt", ".pth", ".onnx", ".engine")),
        "runtime": ("ultralytics",),
    },
    "yolov8n-mobile-phone": {
        "task": "object-detection",
        "library": "ultralytics",
        "adapter": "ultralytics_detection",
        "extensions": frozenset((".pt", ".pth", ".onnx", ".engine")),
        "runtime": ("ultralytics",),
    },
    "bert-ner": {
        "task": "token-classification",
        "library": "transformers",
        "adapter": "transformers_ner",
        "extensions": frozenset((".safetensors", ".bin", ".msgpack", ".pt", ".pth")),
        "runtime": ("transformers",),
    },
    "rf-detr-seg-medium": {
        "task": "instance-segmentation",
        "library": "rfdetr",
        "adapter": "rfdetr_seg",
        "extensions": frozenset((".pt",)),
        "runtime": ("rfdetr",),
    },
    "yolo-master-seg-n": {
        "task": "instance-segmentation",
        "library": "yolo-master",
        "adapter": "yolo_master_seg",
        "extensions": frozenset((".pt", ".pth", ".onnx", ".engine")),
        "runtime": ("ultralytics",),
    },
    "yoloe-26s-seg": {
        "task": "instance-segmentation",
        "library": "ultralytics",
        "adapter": "ultralytics_seg",
        "extensions": frozenset((".pt", ".pth", ".onnx", ".engine")),
        "runtime": ("ultralytics",),
    },
    "qwen3-vl-seg-cloud": {
        "task": "visual-diagnosis",
        "library": "qwen-vl-api",
        "adapter": "qwen_vl_api",
        "extensions": frozenset(),
        "runtime": (),
    },
    "omdet-turbo-swin-tiny": {
        "task": "object-detection",
        "library": "transformers",
        "adapter": "omdet_detection",
        "extensions": frozenset((".safetensors", ".bin", ".msgpack", ".pt", ".pth")),
        "runtime": ("transformers",),
    },
    "chinese-sign-language-tigerhhzz-yolo11s": {
        "task": "object-detection",
        "library": "ultralytics",
        "adapter": "ultralytics_detection",
        "extensions": frozenset((".pt", ".pth", ".onnx", ".engine")),
        "runtime": ("ultralytics",),
    },
    "opencv-handpose-mediapipe": {
        "task": "pose-estimation",
        "library": "opencv-dnn",
        "adapter": "opencv_handpose",
        "extensions": frozenset((".onnx",)),
        "runtime": ("cv2",),
    },
    "linly-talker": {
        "task": "talking-head",
        "library": "linly",
        "adapter": "linly_talker",
        "extensions": frozenset((".safetensors", ".bin", ".pt", ".pth", ".onnx", ".json", ".pkl", ".params", ".model", ".pb")),
        "runtime": ("torch",),
    },
    "bert-emotion": {
        "task": "text-classification",
        "library": "transformers",
        "adapter": "transformers_text_classify",
        "extensions": frozenset((".safetensors", ".bin", ".msgpack", ".pt", ".pth")),
        "runtime": ("transformers",),
    },
    "finbert": {
        "task": "text-classification",
        "library": "transformers",
        "adapter": "transformers_text_classify",
        "extensions": frozenset((".safetensors", ".bin", ".msgpack", ".pt", ".pth")),
        "runtime": ("transformers",),
    },
    "bart-mnli": {
        "task": "zero-shot-classification",
        "library": "transformers",
        "adapter": "transformers_zero_shot",
        "extensions": frozenset((".safetensors", ".bin", ".msgpack", ".pt", ".pth")),
        "runtime": ("transformers",),
    },
    "bert-fill-mask": {
        "task": "fill-mask",
        "library": "transformers",
        "adapter": "transformers_fill_mask",
        "extensions": frozenset((".safetensors", ".bin", ".msgpack", ".pt", ".pth")),
        "runtime": ("transformers",),
    },
    "distilbart-cnn": {
        "task": "summarization",
        "library": "transformers",
        "adapter": "transformers_summarize",
        "extensions": frozenset((".safetensors", ".bin", ".msgpack", ".pt", ".pth")),
        "runtime": ("transformers",),
    },
    "opus-mt-en-zh": {
        "task": "translation",
        "library": "transformers",
        "adapter": "transformers_translate",
        "extensions": frozenset((".safetensors", ".bin", ".msgpack", ".pt", ".pth")),
        "runtime": ("transformers",),
    },
    "PP-OCRv6_small_det_onnx": {
        "task": "text-detection",
        "library": "rapidocr",
        "adapter": "rapidocr_det",
        "extensions": frozenset((".onnx",)),
        "runtime": ("rapidocr_onnxruntime",),
    },
    "PP-OCRv6_small_rec_onnx": {
        "task": "text-recognition",
        "library": "rapidocr",
        "adapter": "rapidocr_rec",
        "extensions": frozenset((".onnx",)),
        "runtime": ("rapidocr_onnxruntime",),
    },
    "rapidtable-slanet-plus": {
        "task": "table-structure",
        "library": "rapidtable",
        "adapter": "rapidtable",
        "extensions": frozenset((".onnx",)),
        "runtime": ("rapid_table",),
    },
    "yolov8m-table-extraction": {
        "task": "object-detection",
        "library": "ultralytics",
        "adapter": "ultralytics_detection",
        "extensions": frozenset((".pt", ".pth", ".onnx", ".engine")),
        "runtime": ("ultralytics",),
    },
    "yolo-master-obb-n": {
        "task": "obb",
        "library": "yolo-master",
        "adapter": "yolo_master_obb",
        "extensions": frozenset((".pt", ".pth", ".onnx", ".engine")),
        "runtime": ("ultralytics",),
    },
    "distilbert-squad": {
        "task": "question-answering",
        "library": "transformers",
        "adapter": "transformers_qa",
        "extensions": frozenset((".safetensors", ".bin", ".msgpack", ".pt", ".pth")),
        "runtime": ("transformers",),
    },
    "yolo11-fish-detector-grayscale": {
        "task": "object-detection",
        "library": "ultralytics",
        "adapter": "ultralytics_detection",
        "extensions": frozenset((".pt", ".pth", ".onnx", ".engine")),
        "runtime": ("ultralytics",),
    },
    "fire-smoke-detection": {
        "task": "object-detection",
        "library": "ultralytics",
        "adapter": "ultralytics_detection",
        "extensions": frozenset((".pt", ".pth", ".onnx", ".engine")),
        "runtime": ("ultralytics",),
    },
    "yolo11s-ball": {
        "task": "object-detection",
        "library": "ultralytics",
        "adapter": "ultralytics_detection",
        "extensions": frozenset((".pt", ".pth", ".onnx", ".engine")),
        "runtime": ("ultralytics",),
    },
    "rocket-detect-nasaspaceflight": {
        "task": "object-detection",
        "library": "ultralytics",
        "adapter": "ultralytics_detection",
        "extensions": frozenset((".pt", ".pth", ".onnx", ".engine")),
        "runtime": ("ultralytics",),
    },
    "clip-reid-person": {
        "task": "person-reid",
        "library": "clip-reid",
        "adapter": "person_reid_onnx",
        "extensions": frozenset((".onnx",)),
        "runtime": ("onnxruntime",),
    },
    "opencv-person-reid-youtu": {
        "task": "person-reid",
        "library": "opencv-reid",
        "adapter": "person_reid_onnx",
        "extensions": frozenset((".onnx",)),
        "runtime": ("cv2",),
    },
    "osnet-x1-0": {
        "task": "person-reid",
        "library": "osnet",
        "adapter": "person_reid_onnx",
        "extensions": frozenset((".onnx",)),
        "runtime": ("onnxruntime",),
    },
    "melotts-zh-en": {
        "task": "text-to-speech",
        "library": "sherpa-onnx",
        "adapter": "sherpa_tts",
        "extensions": frozenset((".onnx",)),
        "runtime": ("sherpa_onnx",),
    },
    "mms-tts-eng": {
        "task": "text-to-speech",
        "library": "transformers",
        "adapter": "transformers_tts",
        "extensions": frozenset((".safetensors", ".bin", ".msgpack", ".pt", ".pth")),
        "runtime": ("transformers",),
    },
    "vibevoice-realtime": {
        "task": "text-to-speech",
        "library": "vibevoice",
        "adapter": "vibevoice_tts",
        "extensions": frozenset((".safetensors", ".bin", ".pt", ".pth", ".onnx", ".json", ".pkl", ".params", ".model", ".pb")),
        "runtime": ("torch",),
    },
    "fun-asr-nano": {
        "task": "automatic-speech-recognition",
        "library": "funasr-nano",
        "adapter": "funasr_nano",
        "extensions": frozenset((".safetensors", ".bin", ".pt", ".pth", ".onnx", ".json", ".pkl", ".params", ".model", ".pb")),
        "runtime": ("funasr",),
    },
    "moonshine-tiny": {
        "task": "automatic-speech-recognition",
        "library": "transformers",
        "adapter": "transformers_asr",
        "extensions": frozenset((".safetensors", ".bin", ".msgpack", ".pt", ".pth")),
        "runtime": ("transformers",),
    },
    "moss-transcribe-diarize-0p9b": {
        "task": "automatic-speech-recognition",
        "library": "transformers",
        "adapter": "transformers_asr",
        "extensions": frozenset((".safetensors", ".bin", ".msgpack", ".pt", ".pth")),
        "runtime": ("transformers",),
    },
    "paraformer-zh": {
        "task": "automatic-speech-recognition",
        "library": "funasr",
        "adapter": "funasr",
        "extensions": frozenset((".safetensors", ".bin", ".pt", ".pth", ".onnx", ".json", ".pkl", ".params", ".model", ".pb")),
        "runtime": ("funasr",),
    },
    "sensevoice-small": {
        "task": "automatic-speech-recognition",
        "library": "funasr",
        "adapter": "funasr",
        "extensions": frozenset((".safetensors", ".bin", ".pt", ".pth", ".onnx", ".json", ".pkl", ".params", ".model", ".pb")),
        "runtime": ("funasr",),
    },
    "sensevoice-small-onnx": {
        "task": "automatic-speech-recognition",
        "library": "funasr-onnx",
        "adapter": "funasr_onnx",
        "extensions": frozenset((".onnx",)),
        "runtime": ("funasr_onnx",),
    },
    "detr-resnet-50": {
        "task": "object-detection",
        "library": "transformers",
        "adapter": "transformers_detection",
        "extensions": frozenset((".safetensors", ".bin", ".msgpack", ".pt", ".pth")),
        "runtime": ("transformers",),
    },
    "rf-detr-medium": {
        "task": "object-detection",
        "library": "rfdetr",
        "adapter": "rfdetr_detection",
        "extensions": frozenset((".pt",)),
        "runtime": ("rfdetr",),
    },
    "yolo-master-esmoe-n": {
        "task": "object-detection",
        "library": "yolo-master",
        "adapter": "yolo_master_detect",
        "extensions": frozenset((".pt", ".pth", ".onnx", ".engine")),
        "runtime": ("ultralytics",),
    },
    "yolo-master-esmoe-s": {
        "task": "object-detection",
        "library": "yolo-master",
        "adapter": "yolo_master_detect",
        "extensions": frozenset((".pt", ".pth", ".onnx", ".engine")),
        "runtime": ("ultralytics",),
    },
    "yolo-master-v01-n": {
        "task": "object-detection",
        "library": "yolo-master",
        "adapter": "yolo_master_detect",
        "extensions": frozenset((".pt", ".pth", ".onnx", ".engine")),
        "runtime": ("ultralytics",),
    },
    "yolo26n": {
        "task": "object-detection",
        "library": "ultralytics",
        "adapter": "ultralytics_detection",
        "extensions": frozenset((".pt", ".pth", ".onnx", ".engine")),
        "runtime": ("ultralytics",),
    },
    "yolo26s": {
        "task": "object-detection",
        "library": "ultralytics",
        "adapter": "ultralytics_detection",
        "extensions": frozenset((".pt", ".pth", ".onnx", ".engine")),
        "runtime": ("ultralytics",),
    },
}

_MIN_DIRECTORY_ONNX_BYTES = 100_000
_EFFICIENT_SAM_ONNX_NAMES = frozenset((
    "image_segmentation_efficientsam_ti_2025april.onnx",
    "image_segmentation_efficientsam_ti_2025april_int8.onnx",
    "image_segmentation_efficientsam_ti_2024may.onnx",
))


def _model_value(model, name: str):
    if isinstance(model, dict):
        return model.get(name)
    return getattr(model, name, None)


def _files(path: Path) -> list[Path]:
    try:
        if path.is_file():
            return [path] if path.stat().st_size > 0 else []
        if path.is_dir():
            return sorted(
                candidate for candidate in path.rglob("*")
                if candidate.is_file() and candidate.stat().st_size > 0
            )
    except OSError:
        return []
    return []


def _compatible_weights(model_key: str, path: Path, extensions: frozenset[str]) -> list[Path]:
    if model_key in ("insightface-buffalo-l", "insightface-buffalo-s"):
        pack = (_CONTRACTS.get(model_key) or {}).get("pack")
        pack_dir = path / "models" / str(pack) if path is not None and pack else None
        if pack_dir is None:
            return []
        return [
            item for item in _files(pack_dir)
            if item.suffix.lower() in extensions
        ]
    search_root = path
    # RTMPose/DWPose often bind file_path to rtmlib_manifest.json; search the model folder.
    # If the configured path is already a usable weight file, keep it as the only candidate.
    if model_key in ("dwpose-m", "rtmo-m", "rtmo-s", "rtmpose-m") and path is not None:
        if path.is_file() and path.suffix.lower() in extensions:
            return [path]
        if path.is_file():
            search_root = path.parent
    candidates = [item for item in _files(search_root) if item.suffix.lower() in extensions]
    if model_key in (
        "efficient-sam", "clip-reid-vehicle", "transreid-vehicle", "vehicle-vit-reid",
        "opencv-yunet-sface", "inpainting-lama", "mobilenet-v2",
        "opencv-person-reid-youtu", "clip-reid-person", "osnet-x1-0",
    ):
        candidates = [
            item for item in candidates
            if item.suffix.lower() == ".onnx" and item.stat().st_size > _MIN_DIRECTORY_ONNX_BYTES
        ]
    if model_key == "efficient-sam":
        candidates = [
            item for item in candidates if item.name.lower() in _EFFICIENT_SAM_ONNX_NAMES
        ]
    if model_key in ("dwpose-m", "rtmo-m", "rtmo-s", "rtmpose-m"):
        onnx_candidates = [item for item in candidates if item.suffix.lower() == ".onnx"]
        if onnx_candidates:
            candidates = onnx_candidates
    contract_lib = (_CONTRACTS.get(model_key) or {}).get("library")
    if contract_lib == "transformers" and model_key != "vlm-fo1-3b":
        config = search_root / "config.json" if search_root.is_dir() else search_root.parent / "config.json"
        if not config.is_file():
            return []
    if model_key == "vlm-fo1-3b":
        # Directory models publish index/config JSON plus sharded weights.
        weight_like = [
            item for item in candidates
            if item.suffix.lower() in (".safetensors", ".bin", ".pt", ".pth")
            or item.name.lower().endswith(".safetensors.index.json")
        ]
        if not weight_like:
            return []
        candidates = weight_like
    return candidates


def _select_unique_weight(candidates: list[Path]) -> Path | None:
    """Prefer a single primary artifact when a directory contains multiple formats."""
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        return None
    for extension in (".pt", ".pth", ".onnx", ".engine"):
        matched = [item for item in candidates if item.suffix.lower() == extension]
        if len(matched) == 1:
            return matched[0]
    return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_manifest(directory: Path) -> dict | None:
    marker = directory / "production-manifest.json"
    try:
        if not marker.is_file() or marker.stat().st_size > 16_384:
            return None
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _artifact_binding(data: dict, weight_path: Path) -> bool:
    artifact_file = data.get("artifactFile")
    expected_hash = data.get("artifactSha256")
    if (
        not isinstance(artifact_file, str)
        or not artifact_file
        or Path(artifact_file).name != artifact_file
        or not isinstance(expected_hash, str)
        or not re.fullmatch(r"[0-9a-fA-F]{64}", expected_hash)
        or artifact_file != weight_path.name
    ):
        return False
    try:
        return hmac.compare_digest(_sha256(weight_path), expected_hash.lower())
    except OSError:
        return False


def _production_manifest_confirms(model_key: str, task: str, weight_path: Path) -> bool:
    data = _read_manifest(weight_path.parent)
    if data is None or data.get("modelKey") != model_key or data.get("task") != task:
        return False
    if model_key == "yolo26n-p2-plate":
        classes = data.get("classes")
        normalized_classes = {
            str(item).strip().lower().replace("-", "_") for item in classes
        } if isinstance(classes, list) else set()
        if data.get("trainingComplete") is not True or not normalized_classes.intersection(
            ("plate", "license_plate")
        ):
            return False
    return _artifact_binding(data, weight_path)


def _efficient_sam_artifacts(
    configured_path: Path, candidates: list[Path], task: str,
) -> dict[str, Path] | None:
    directory = configured_path if configured_path.is_dir() else configured_path.parent
    data = _read_manifest(directory)
    if data is None or data.get("modelKey") != "efficient-sam" or data.get("task") != task:
        return None
    raw_artifacts = data.get("artifacts")
    if raw_artifacts is None:
        raw_artifacts = {"fp32": data}
    if not isinstance(raw_artifacts, dict) or not raw_artifacts:
        return None
    by_name = {candidate.name: candidate for candidate in candidates}
    resolved = {}
    for precision in ("fp32", "int8"):
        binding = raw_artifacts.get(precision)
        if binding is None:
            continue
        if not isinstance(binding, dict):
            return None
        artifact_file = binding.get("artifactFile")
        candidate = by_name.get(artifact_file) if isinstance(artifact_file, str) else None
        if candidate is None or not _artifact_binding(binding, candidate):
            return None
        resolved[precision] = candidate
    if len(resolved) != len(raw_artifacts):
        return None
    return resolved or None


def evaluate_scenario_contract(
    scenario: dict,
    model,
    configured_path: Path | None,
    *,
    runtime_probe: Callable[[str], bool],
    requested_precision: str | None = None,
) -> ScenarioContractResult:
    """Evaluate publication, exact DB metadata, assets, adapter and runtime.

    The function performs no imports, model loading, downloads, or writes.
    """
    model_key = str(scenario.get("modelKey") or "")
    contract = _CONTRACTS.get(model_key)
    all_files = _files(configured_path) if configured_path is not None else []
    weights_present = bool(all_files)
    adapter_matches = contract is not None and scenario.get("adapter") == contract["adapter"]
    library_matches = bool(contract) and (
        str(_model_value(model, "library") or "").strip().lower() == contract["library"]
    )
    runtime_available = bool(
        adapter_matches
        and library_matches
        and all(runtime_probe(module) for module in contract["runtime"])
    )
    if bool(contract) and contract.get("library") == "yolo-master" and runtime_available:
        try:
            from services.yolo_master import get_yolo_master_root
            runtime_available = bool(get_yolo_master_root())
        except Exception:  # noqa: BLE001
            runtime_available = False
    if model_key == "vlm-fo1-3b" and runtime_available:
        try:
            from services.vlm_fo1 import resolve_vlm_fo1_root
            runtime_available = bool(resolve_vlm_fo1_root())
        except Exception:  # noqa: BLE001
            runtime_available = False

    if scenario.get("published") is not True:
        return ScenarioContractResult(weights_present, runtime_available, False, "scenario is not published")
    if scenario.get("apiEnabled") is not True:
        return ScenarioContractResult(weights_present, runtime_available, False, "scenario API is disabled")
    if not adapter_matches:
        return ScenarioContractResult(weights_present, runtime_available, False, "scenario adapter is not supported")
    if str(_model_value(model, "task") or "").strip().lower() != contract["task"]:
        return ScenarioContractResult(
            weights_present, runtime_available, False,
            "registered model task does not match scenario contract",
        )
    if not library_matches:
        return ScenarioContractResult(
            weights_present, runtime_available, False,
            "registered model library does not match scenario contract",
        )
    if str(_model_value(model, "status") or "") != "0":
        return ScenarioContractResult(weights_present, runtime_available, False, "model is disabled")
    if contract["library"] == "qwen-vl-api":
        if not runtime_available and contract["runtime"]:
            return ScenarioContractResult(
                weights_present, False, False, "runtime library is unavailable", configured_path,
            )
        return ScenarioContractResult(True, True, True, None, configured_path)

    if not weights_present:
        return ScenarioContractResult(False, runtime_available, False, "model weights are missing")

    candidates = _compatible_weights(model_key, configured_path, contract["extensions"])
    if not candidates:
        return ScenarioContractResult(
            True, runtime_available, False, "model weights are incompatible with scenario runtime",
        )
    efficient_artifacts = None
    if model_key == "efficient-sam" and configured_path is not None:
        efficient_artifacts = _efficient_sam_artifacts(
            configured_path, candidates, contract["task"],
        )
        if efficient_artifacts is None:
            return ScenarioContractResult(
                True, runtime_available, False,
                "production manifest is missing or invalid", candidates[0],
            )
        supported = tuple(
            precision for precision in ("fp32", "int8") if precision in efficient_artifacts
        )
        precision = requested_precision or ("fp32" if "fp32" in supported else supported[0])
        if precision not in efficient_artifacts:
            return ScenarioContractResult(
                True, runtime_available, False, "precision is not published",
                supported_precisions=supported,
            )
        selected = efficient_artifacts[precision]
    elif model_key in ("insightface-buffalo-l", "insightface-buffalo-s"):
        # Pack directory contains multiple ONNX roles (det/rec); readiness binds the pack root.
        pack = contract.get("pack")
        selected = configured_path / "models" / str(pack) if configured_path is not None else None
        if selected is None or not selected.is_dir():
            return ScenarioContractResult(
                True, runtime_available, False, "model weights are incompatible with scenario runtime",
            )
    elif model_key == "opencv-yunet-sface" and configured_path is not None:
        selected = configured_path if configured_path.is_dir() else configured_path.parent
        if not any(item.suffix.lower() == ".onnx" for item in candidates):
            return ScenarioContractResult(
                True, runtime_available, False, "model weights are incompatible with scenario runtime",
            )
    elif (
        model_key in (
            "inpainting-lama", "mobilenet-v2", "vit-base", "vlm-fo1-3b",
            "opencv-handpose-mediapipe",
        )
        or contract["library"] in (
            "transformers", "modelscope", "rapidocr", "rapidtable",
            "funasr", "funasr-onnx", "funasr-nano", "vibevoice", "linly",
            "sherpa-onnx", "opencv-reid",
        )
    ) and configured_path is not None:
        selected = configured_path if configured_path.is_dir() else configured_path.parent
        if model_key == "mobilenet-v2" and len(candidates) < 1:
            return ScenarioContractResult(
                True, runtime_available, False, "model weights are incompatible with scenario runtime",
            )
        if (
            contract["library"] == "transformers"
            and not (selected / "config.json").is_file()
        ):
            return ScenarioContractResult(
                True, runtime_available, False, "model weights are incompatible with scenario runtime",
            )
    else:
        selected = _select_unique_weight(candidates)
        if selected is None:
            return ScenarioContractResult(
                True, runtime_available, False, "model weight directory is ambiguous",
            )
    if model_key == "yolo26n-p2-plate" and not _production_manifest_confirms(
        model_key, contract["task"], selected,
    ):
        return ScenarioContractResult(
            True, runtime_available, False,
            "plate-specific production manifest is missing or invalid", selected,
        )
    if not runtime_available:
        return ScenarioContractResult(
            True, False, False, "runtime library is unavailable", selected,
            tuple(efficient_artifacts) if efficient_artifacts else (),
        )
    return ScenarioContractResult(
        True, True, True, None, selected,
        tuple(efficient_artifacts) if efficient_artifacts else (),
    )
