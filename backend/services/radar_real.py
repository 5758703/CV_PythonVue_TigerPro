"""Real damo-radar inference adapter.

Loads vendor code from ``uploads/models/third_party/damo-radar`` and checkpoints
from ``RADAR_CKPT_DIR`` (default ``uploads/models/radar``).

Requires GPU for practical latency; CPU is allowed but may be extremely slow.
"""
from __future__ import annotations

import csv
import os
import re
import shutil
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any

from config import Config

# Merlin-style finding keys used by the demo UI / AUC table → English labels
# from damo-radar ``english_mapping`` values.
_MERLIN_TO_ENGLISH: dict[str, tuple[str, ...]] = {
    "abdominal_aortic_aneurysm": ("Aorta_Aortic aneurysm",),
    "atherosclerosis": ("Aorta_Atherosclerosis",),
    "submucosal_edema": ("Large bowel_Wall edema", "Stomach_Wall edema"),
    "appendicitis": ("Large bowel_Appendicitis",),
    "bowel_obstruction": ("Large bowel_Obstruction", "Small bowel_Obstruction"),
    "aortic_valve_calcification": ("Aorta_Calcification",),
    "cardiomegaly": ("Heart_Cardiomegaly",),
    "biliary_ductal_dilation": (
        "Gallbladder_Extrahepatic bile duct dilatation",
        "Liver_Intrahepatic bile duct dilatation",
    ),
    "hepatomegaly": (),  # not a dedicated RAD-CT finding label
    "hepatic_steatosis": ("Liver_Steatotic liver disease",),
    "pleural_effusion": ("Lung_Pleural effusion",),
    "atelectasis": ("Lung_Atelectasis",),
    "renal_hypodensities": ("Kidney_Hypoattenuating lesion",),
    "renal_cyst": ("Kidney_Cyst",),
    "hydronephrosis": ("Kidney_Hydronephrosis",),
    "gallstones": ("Gallbladder_Cholecystolithiasis",),
    "pancreatic_atrophy": ("Pancreas_Atrophy",),
    "splenomegaly": ("Spleen_Splenomegaly",),
    "fracture": ("Rib_Fracture",),
    "hiatal_hernia": ("Esophagus_Hiatal hernia",),
    "surgically_absent_gallbladder": (),
}

_lock = threading.Lock()
_runtime: dict[str, Any] = {"pad_func": None, "model": None, "device": None}


class RadarRealError(RuntimeError):
    """Raised when real damo-radar inference cannot run."""


def vendor_dir() -> Path:
    raw = (getattr(Config, "RADAR_VENDOR_DIR", None) or "").strip()
    if raw:
        return Path(raw)
    return Path(Config.MODEL_FOLDER) / "third_party" / "damo-radar"


def inference_dir() -> Path:
    return vendor_dir() / "RADAR_inference"


def ckpt_dir() -> Path:
    raw = (getattr(Config, "RADAR_CKPT_DIR", None) or "").strip()
    if raw:
        return Path(raw)
    return Path(Config.MODEL_FOLDER) / "radar"


def device_name() -> str:
    forced = (getattr(Config, "RADAR_DEVICE", None) or os.getenv("RADAR_DEVICE") or "auto").strip().lower()
    if forced in ("cpu", "cuda"):
        return forced
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def vendor_ready(directory: Path | None = None) -> bool:
    root = directory or vendor_dir()
    return (root / "RADAR_inference" / "inference_demo.py").is_file()


def weights_ready(directory: Path | None = None) -> bool:
    root = directory or ckpt_dir()
    ckpt = root / "checkpoint_radar_pretrain.pth"
    bert = root / "bert-base-chinese"
    text = root / "infer_text_embedding_radar.pt"
    bert_cfg = bert / "config.json"
    bert_bin = bert / "pytorch_model.bin"
    bert_ok = (
        bert.is_dir()
        and bert_cfg.is_file()
        and bert_bin.is_file()
        and bert_bin.stat().st_size > 400_000_000
    )
    ckpt_ok = ckpt.is_file() and ckpt.stat().st_size > 1_500_000_000
    return ckpt_ok and bert_ok and text.is_file()


def readiness() -> dict[str, Any]:
    return {
        "vendorReady": vendor_ready(),
        "weightsReady": weights_ready(),
        "vendorDir": str(vendor_dir()),
        "ckptDir": str(ckpt_dir()),
        "device": device_name(),
        "ready": vendor_ready() and weights_ready(),
    }


def ensure_vendor_on_path() -> Path:
    if not vendor_ready():
        raise RadarRealError(
            "未找到 damo-radar 官方代码。请执行：python scripts/setup_radar.py "
            "（或设置 RADAR_VENDOR_DIR）"
        )
    infer = inference_dir()
    for path in (str(infer), str(vendor_dir())):
        if path not in sys.path:
            sys.path.insert(0, path)
    return infer


def _snake_finding_name(english_label: str) -> str:
    """Normalize ``Organ_Finding name`` → ``organ_finding_name``."""
    text = english_label.strip().replace("'", "")
    text = re.sub(r"[^\w]+", "_", text)
    return text.strip("_").lower()


def _parse_score(raw: Any) -> float | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _select_merlin_scores(english_scores: dict[str, float]) -> list[tuple[str, float]]:
    selected: list[tuple[str, float]] = []
    for key, labels in _MERLIN_TO_ENGLISH.items():
        values = [english_scores[label] for label in labels if label in english_scores]
        if values:
            selected.append((key, max(values)))
    if selected:
        return selected
    # Fallback: expose top snake_case labels from the full RAD-CT vocabulary.
    items = sorted(english_scores.items(), key=lambda item: item[1], reverse=True)
    return [(_snake_finding_name(name), score) for name, score in items[:40]]


def _load_runtime() -> tuple[Any, Any, str]:
    with _lock:
        if _runtime["model"] is not None:
            return _runtime["pad_func"], _runtime["model"], _runtime["device"]

        if not weights_ready():
            raise RadarRealError(
                "RADAR 权重未就绪。请执行：python scripts/setup_radar.py --download-weights"
            )

        ensure_vendor_on_path()
        ckpt = ckpt_dir().resolve()
        os.environ["MODEL_ROOT"] = str(ckpt)
        os.environ["CONFIGS_ROOT"] = str(ckpt)

        try:
            import torch
            from monai import transforms
            from dynamic_network_architectures.med import XBertEncoder
            from dynamic_network_architectures.vision_branch import VisionBranch
            import inference_demo as demo
        except ImportError as exc:
            raise RadarRealError(
                "damo-radar 依赖未安装（需要 torch / monai / transformers 等）。"
                f"请 pip install -r {vendor_dir() / 'requirements.txt'}。详情: {exc}"
            ) from exc

        device = device_name()
        if device == "cuda" and not torch.cuda.is_available():
            raise RadarRealError("RADAR_DEVICE=cuda 但当前环境无可用 GPU")

        pad_func = transforms.DivisiblePadd(
            keys=["image", "label"],
            k=32,
            mode="constant",
            constant_values=0,
            method="end",
        )
        vision_encoder = VisionBranch()
        text_encoder = XBertEncoder.from_config({}, from_pretrained=True)
        model = demo.RADAR(image_encoder=vision_encoder, text_encoder=text_encoder)
        ckpt_path = ckpt / "checkpoint_radar_pretrain.pth"
        state = torch.load(str(ckpt_path), map_location="cpu", weights_only=False)
        model.load_state_dict(state["model"], strict=False)
        model.eval()
        model.to(device)

        _runtime["pad_func"] = pad_func
        _runtime["model"] = model
        _runtime["device"] = device
        return pad_func, model, device


def _run_evaluate_to_csv(nifti_path: Path, work_dir: Path) -> Path:
    """Invoke vendor evaluate() with patched text-embedding path."""
    import torch
    import inference_demo as demo

    pad_func, model, device = _load_runtime()
    img_dir = work_dir / "cases"
    save_dir = work_dir / "results"
    img_dir.mkdir(parents=True, exist_ok=True)
    save_dir.mkdir(parents=True, exist_ok=True)

    target = img_dir / nifti_path.name
    if target.resolve() != nifti_path.resolve():
        shutil.copy2(nifti_path, target)

    text_path = str((ckpt_dir() / "infer_text_embedding_radar.pt").resolve())
    original_load = torch.load

    def patched_load(path, *args, **kwargs):  # noqa: ANN001
        path_str = str(path).replace("\\", "/")
        if path_str.endswith("infer_text_embedding_radar.pt"):
            return original_load(text_path, *args, **kwargs)
        return original_load(path, *args, **kwargs)

    # Vendor evaluate assumes CUDA tensors; move windows via .cuda() calls inside.
    if device != "cuda":
        raise RadarRealError(
            "当前 damo-radar 官方推理脚本依赖 CUDA（内部调用 .cuda()）。"
            "请在 GPU 环境运行，或设置 RADAR_ENGINE=mock。"
        )

    infer_cwd = str(inference_dir())
    prev_cwd = os.getcwd()
    torch.load = patched_load  # type: ignore[assignment]
    try:
        os.chdir(infer_cwd)
        demo.evaluate(pad_func, model, str(img_dir), str(save_dir), "tigerpro")
    finally:
        torch.load = original_load  # type: ignore[assignment]
        os.chdir(prev_cwd)

    csv_path = save_dir / "RADAR_infer_results_tigerpro.csv"
    if not csv_path.is_file():
        raise RadarRealError("damo-radar 推理未生成结果 CSV")
    return csv_path


def parse_result_csv(csv_path: Path) -> dict[str, float]:
    """Parse vendor CSV into ``{english_label: positive_score}``."""
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    if not rows:
        raise RadarRealError("damo-radar 结果 CSV 为空")
    row = rows[0]
    scores: dict[str, float] = {}
    for key, raw in row.items():
        if not key or key == "file_name":
            continue
        value = _parse_score(raw)
        if value is None:
            continue
        # Columns look like: ``中文 (English_Label)``
        english = key
        if "(" in key and key.endswith(")"):
            english = key[key.rfind("(") + 1 : -1].strip()
        scores[english] = float(value)
    return scores


def run_nifti(nifti_path: str | Path, *, threshold: float = 0.5) -> dict[str, Any]:
    path = Path(nifti_path)
    if not path.is_file():
        raise RadarRealError(f"NIfTI 文件不存在: {path}")

    with tempfile.TemporaryDirectory(prefix="radar_real_") as tmp:
        csv_path = _run_evaluate_to_csv(path, Path(tmp))
        english_scores = parse_result_csv(csv_path)

    pairs = _select_merlin_scores(english_scores)
    thr = min(1.0, max(0.0, float(threshold)))
    findings = []
    for name, score in pairs:
        value = round(float(score), 4)
        findings.append({"name": name, "score": value, "positive": value >= thr})
    findings.sort(key=lambda item: item["score"], reverse=True)

    return {
        "engine": "real",
        "findings": findings,
        "threshold": thr,
        "positiveCount": sum(1 for item in findings if item["positive"]),
        "meta": {
            "source": "damo-radar",
            "filename": path.name,
            "device": device_name(),
            "findingCountRaw": len(english_scores),
            "disclaimer": (
                "AI 结果仅供辅助，需医生最终判读。"
                "本输出不能替代执业医师诊断、病理结果或临床决策。"
                "当前为 damo-radar 真推理引擎。"
            ),
        },
    }


def reset_runtime_cache() -> None:
    with _lock:
        _runtime["pad_func"] = None
        _runtime["model"] = None
        _runtime["device"] = None
