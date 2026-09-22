"""RADAR abdominal CT diagnosis service.

Mock engine: deterministic scores from upload content when weights are absent.
Real engine: damo-radar vendor inference when checkpoint + BERT + text embedding
and official code are present (``RADAR_ENGINE=auto|real``).
"""
from __future__ import annotations

import hashlib
import os
import struct
from pathlib import Path
from typing import Any

from config import Config

DISCLAIMER = (
    "AI 结果仅供辅助，需医生最终判读。"
    "本输出不能替代执业医师诊断、病理结果或临床决策。"
)

# Subset of MERLIN / RADAR finding names used by the official demo CSV shape.
_DEMO_SCORES: tuple[tuple[str, float], ...] = (
    ("abdominal_aortic_aneurysm", 0.12),
    ("atherosclerosis", 0.71),
    ("submucosal_edema", 0.18),
    ("appendicitis", 0.09),
    ("bowel_obstruction", 0.15),
    ("aortic_valve_calcification", 0.42),
    ("cardiomegaly", 0.33),
    ("biliary_ductal_dilation", 0.28),
    ("hepatomegaly", 0.61),
    ("hepatic_steatosis", 0.78),
    ("pleural_effusion", 0.21),
    ("atelectasis", 0.35),
    ("renal_hypodensities", 0.55),
    ("renal_cyst", 0.82),
    ("hydronephrosis", 0.14),
    ("gallstones", 0.91),
    ("pancreatic_atrophy", 0.47),
    ("splenomegaly", 0.22),
    ("fracture", 0.08),
    ("hiatal_hernia", 0.39),
    ("surgically_absent_gallbladder", 0.05),
)

_NIFTI_SUFFIXES = (".nii", ".nii.gz")
_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".bmp", ".webp")
_ALLOWED_UPLOAD_SUFFIXES = _NIFTI_SUFFIXES + _IMAGE_SUFFIXES


class RadarError(ValueError):
    """User-facing validation / engine error."""


def ckpt_dir() -> Path:
    raw = (getattr(Config, "RADAR_CKPT_DIR", None) or "").strip()
    if raw:
        return Path(raw)
    return Path(Config.MODEL_FOLDER) / "radar"


def weights_ready(directory: Path | None = None) -> bool:
    """True when checkpoint + BERT + text embedding are present."""
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


def vendor_ready() -> bool:
    try:
        from services import radar_real
    except ImportError:
        return False
    return radar_real.vendor_ready()


def real_ready() -> bool:
    return weights_ready() and vendor_ready()


def resolve_engine(forced: str | None = None) -> str:
    mode = (forced or getattr(Config, "RADAR_ENGINE", "auto") or "auto").strip().lower()
    if mode not in ("auto", "mock", "real"):
        mode = "auto"
    ready = real_ready()
    if mode == "mock":
        return "mock"
    if mode == "real":
        if not ready:
            raise RadarError(
                "RADAR_ENGINE=real 但权重或官方代码未就绪。"
                "请执行：python scripts/setup_radar.py --download-weights，"
                "或改用 RADAR_ENGINE=mock / auto"
            )
        return "real"
    return "real" if ready else "mock"


def default_threshold() -> float:
    try:
        value = float(getattr(Config, "RADAR_POSITIVE_THRESHOLD", 0.5) or 0.5)
    except (TypeError, ValueError):
        value = 0.5
    return min(1.0, max(0.0, value))


def status() -> dict[str, Any]:
    engine = "mock"
    try:
        engine = resolve_engine()
    except RadarError:
        engine = "mock"
    ready = real_ready()
    vendor_dir = ""
    device = "auto"
    try:
        from services import radar_real

        vendor_dir = str(radar_real.vendor_dir())
        device = radar_real.device_name()
    except Exception:  # noqa: BLE001
        vendor_dir = str(Path(Config.MODEL_FOLDER) / "third_party" / "damo-radar")
    return {
        "engine": engine,
        "weightsReady": weights_ready(),
        "vendorReady": vendor_ready(),
        "ready": ready,
        "ckptDir": str(ckpt_dir()),
        "vendorDir": vendor_dir,
        "device": device,
        "disclaimer": DISCLAIMER
        + (
            " 当前为演示引擎（未加载 damo-radar 权重时，分数由上传内容确定性派生）。"
            if engine == "mock"
            else " 当前为 damo-radar 真推理引擎。"
        ),
        "threshold": default_threshold(),
        "modelKey": "radar-abdominal-ct",
    }


def _is_allowed_upload_name(filename: str | None) -> bool:
    name = (filename or "").lower().strip()
    return any(name.endswith(suffix) for suffix in _ALLOWED_UPLOAD_SUFFIXES)


def _is_nifti_name(filename: str | None) -> bool:
    name = (filename or "").lower().strip()
    return any(name.endswith(suffix) for suffix in _NIFTI_SUFFIXES)


def _is_image_name(filename: str | None) -> bool:
    name = (filename or "").lower().strip()
    return any(name.endswith(suffix) for suffix in _IMAGE_SUFFIXES)


def validate_upload(filename: str | None, data: bytes | None, *, required: bool) -> None:
    """Accept NIfTI volumes or common 2D image slices (jpg/png/…)."""
    if not filename and not data:
        if required:
            raise RadarError(
                "请上传腹部 CT 文件（.nii / .nii.gz，或 .jpg / .png 等影像切片）"
            )
        return
    if filename and not _is_allowed_upload_name(filename):
        raise RadarError(
            "仅支持 .nii / .nii.gz 体积数据，或 .jpg / .jpeg / .png / .bmp / .webp 影像"
        )
    if data is not None and len(data) == 0 and required:
        raise RadarError("上传文件为空")


# Backward-compatible alias used by older call sites / tests.
def validate_nifti_upload(filename: str | None, data: bytes | None, *, required: bool) -> None:
    validate_upload(filename, data, required=required)


def _build_findings(scores: tuple[tuple[str, float], ...], threshold: float) -> list[dict[str, Any]]:
    findings = []
    for name, score in scores:
        value = round(float(score), 4)
        findings.append({
            "name": name,
            "score": value,
            "positive": value >= threshold,
        })
    findings.sort(key=lambda item: item["score"], reverse=True)
    return findings


def _content_fingerprint(filename: str | None, data: bytes | None) -> str:
    hasher = hashlib.sha256()
    hasher.update((filename or "").encode("utf-8", errors="ignore"))
    hasher.update(b"\0")
    hasher.update(data or b"")
    return hasher.hexdigest()[:16]


def _image_feature_bytes(data: bytes | None, filename: str | None) -> bytes:
    """Optional cheap image stats so visually different slices diverge more."""
    if not data or not _is_image_name(filename):
        return b""
    try:
        import cv2
        import numpy as np
    except ImportError:
        return b""
    arr = np.frombuffer(data, dtype=np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
    if image is None or image.size == 0:
        return b""
    mean = float(image.mean())
    std = float(image.std())
    h, w = image.shape[:2]
    return struct.pack("<ffff", mean, std, float(h), float(w))


def _unit_from_digest(digest: bytes, offset: int) -> float:
    """Map 4 digest bytes at offset to [0, 1)."""
    chunk = digest[offset: offset + 4]
    if len(chunk) < 4:
        chunk = (chunk + b"\0\0\0\0")[:4]
    value = int.from_bytes(chunk, "big")
    return value / 2**32


def demo_scores_for_upload(
    filename: str | None = None,
    data: bytes | None = None,
) -> tuple[tuple[str, float], ...]:
    """Build finding scores for the mock engine.

    - No upload → stable baseline ``_DEMO_SCORES`` (empty demo run).
    - With upload → deterministic scores from file content (+ optional image stats).
    """
    if not filename and not data:
        return _DEMO_SCORES

    hasher = hashlib.sha256()
    hasher.update((filename or "").encode("utf-8", errors="ignore"))
    hasher.update(b"\0")
    hasher.update(data or b"")
    hasher.update(_image_feature_bytes(data, filename))
    digest = hasher.digest()

    scores: list[tuple[str, float]] = []
    for index, (name, baseline) in enumerate(_DEMO_SCORES):
        # Per-finding stream: mix global digest with finding name so rankings reshape.
        local = hashlib.sha256(digest + name.encode("ascii") + bytes([index])).digest()
        noise = _unit_from_digest(local, 0)
        # Keep scores in a clinically plausible band while varying by content.
        value = 0.05 + 0.90 * ((0.35 * baseline) + (0.65 * noise))
        scores.append((name, round(min(0.98, max(0.02, value)), 4)))
    return tuple(scores)


def infer_mock(
    *,
    threshold: float | None = None,
    filename: str | None = None,
    data: bytes | None = None,
) -> dict[str, Any]:
    thr = default_threshold() if threshold is None else min(1.0, max(0.0, float(threshold)))
    has_upload = bool(filename or data)
    scores = demo_scores_for_upload(filename, data)
    findings = _build_findings(scores, thr)
    fingerprint = _content_fingerprint(filename, data) if has_upload else None
    return {
        "engine": "mock",
        "findings": findings,
        "threshold": thr,
        "positiveCount": sum(1 for item in findings if item["positive"]),
        "meta": {
            "source": "demo_content" if has_upload else "demo_csv",
            "filename": filename,
            "contentFingerprint": fingerprint,
            "disclaimer": DISCLAIMER
            + (
                " 当前为演示引擎：分数由上传内容确定性派生，非 damo-radar 真推理。"
                if has_upload
                else " 当前为演示引擎。"
            ),
        },
    }


def infer_real(*, nifti_path: str | Path, threshold: float | None = None) -> dict[str, Any]:
    """Run damo-radar vendor inference on a NIfTI volume."""
    from services import radar_real

    thr = default_threshold() if threshold is None else min(1.0, max(0.0, float(threshold)))
    try:
        return radar_real.run_nifti(nifti_path, threshold=thr)
    except radar_real.RadarRealError as exc:
        raise RadarError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise RadarError(f"damo-radar 真推理失败: {exc}") from exc


def infer(
    *,
    filename: str | None = None,
    data: bytes | None = None,
    threshold: float | None = None,
    engine: str | None = None,
) -> dict[str, Any]:
    resolved = resolve_engine(engine)
    require_file = resolved == "real"
    validate_upload(filename, data, required=require_file)

    if resolved == "mock":
        if filename:
            validate_upload(filename, data if data is not None else b"x", required=False)
        return infer_mock(threshold=threshold, filename=filename, data=data)

    # Real damo-radar expects NIfTI volumes; 2D images are demo-only.
    if filename and _is_image_name(filename) and not _is_nifti_name(filename):
        raise RadarError(
            "真推理引擎需要 NIfTI 体积数据（.nii / .nii.gz）。"
            "JPG/PNG 等二维影像仅在演示引擎下可用，请设置 RADAR_ENGINE=mock 或上传 NIfTI。"
        )
    root = ckpt_dir() / "uploads"
    root.mkdir(parents=True, exist_ok=True)
    safe_name = os.path.basename(filename or "input.nii.gz")
    target = root / safe_name
    if data is not None:
        target.write_bytes(data)
    elif not target.is_file():
        raise RadarError("真推理需要上传 NIfTI 文件内容")
    return infer_real(nifti_path=target, threshold=threshold)


def findings_to_detections(findings: list[dict[str, Any]], *, positives_only: bool = True) -> list[dict]:
    items = []
    for finding in findings or []:
        if positives_only and not finding.get("positive"):
            continue
        items.append({
            "className": str(finding.get("name") or "finding"),
            "confidence": float(finding.get("score") or 0),
        })
    return items


def build_assistive_report(
    findings: list[dict[str, Any]],
    *,
    threshold: float | None = None,
    image_name: str | None = None,
) -> dict[str, Any]:
    """Compose DeepSeek / fallback report from RADAR findings."""
    from report import build_report

    thr = default_threshold() if threshold is None else float(threshold)
    detections = findings_to_detections(findings, positives_only=True)
    if not detections:
        # Keep report path usable when all scores are below threshold.
        detections = findings_to_detections(findings, positives_only=False)[:5]
    return build_report(
        model_name="RADAR 腹部 CT 诊断",
        model_category="医学影像-腹部CT",
        detections=detections,
        width=0,
        height=0,
        conf=thr,
        image_name=image_name or "abdominal-ct.nii.gz",
    )
