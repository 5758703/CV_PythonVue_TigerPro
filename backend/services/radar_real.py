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
    infer = inference_dir().resolve()
    # RADAR_inference must be first so ``import inference_demo`` resolves.
    for path in (str(vendor_dir().resolve()), str(infer)):
        if path in sys.path:
            sys.path.remove(path)
        sys.path.insert(0, path)
    return infer


def _patch_transformers_for_damo_radar() -> None:
    """Bridge damo-radar (transformers~4.25 imports) onto transformers 5.x.

    Vendor ``med.py`` still does::

        from transformers.modeling_utils import (
            apply_chunking_to_forward,
            find_pruneable_heads_and_indices,
            prune_linear_layer,
        )

    Those helpers live in ``pytorch_utils`` (or were removed) in 5.x. Patch them
    onto ``modeling_utils`` before importing vendor code so we need not pin an
    old transformers that would break the rest of this app.

    Also: vendor ``BertModel`` / ``XBertEncoder`` still call ``self.init_weights()``
    directly (transformers 4 style). In 5.x ``init_weights`` → ``tie_weights(
    recompute_mapping=False)`` which requires ``all_tied_weights_keys`` that is
    only populated inside ``post_init()``. Ensure the attribute exists first.
    """
    import torch
    from transformers import modeling_utils

    try:
        from transformers import pytorch_utils as _pu
    except ImportError:  # pragma: no cover
        _pu = None

    if not hasattr(modeling_utils, "apply_chunking_to_forward"):
        if _pu is not None and hasattr(_pu, "apply_chunking_to_forward"):
            modeling_utils.apply_chunking_to_forward = _pu.apply_chunking_to_forward
        else:  # pragma: no cover — extremely old / stripped install

            def apply_chunking_to_forward(forward_fn, chunk_size, chunk_dim, *input_tensors):
                if chunk_size is None or chunk_size <= 0:
                    return forward_fn(*input_tensors)
                tensor_shape = input_tensors[0].shape[chunk_dim]
                if tensor_shape % chunk_size != 0:
                    raise ValueError(
                        f"chunk_size ({chunk_size}) must divide input dim {tensor_shape}"
                    )
                num_chunks = tensor_shape // chunk_size
                chunks = [torch.chunk(t, num_chunks, dim=chunk_dim) for t in input_tensors]
                output_chunks = [forward_fn(*inputs) for inputs in zip(*chunks)]
                return torch.cat(output_chunks, dim=chunk_dim)

            modeling_utils.apply_chunking_to_forward = apply_chunking_to_forward

    if not hasattr(modeling_utils, "prune_linear_layer"):
        if _pu is not None and hasattr(_pu, "prune_linear_layer"):
            modeling_utils.prune_linear_layer = _pu.prune_linear_layer

    if not hasattr(modeling_utils, "find_pruneable_heads_and_indices"):
        # Removed from transformers 5 public API; keep the classic BERT prune helper.
        def find_pruneable_heads_and_indices(heads, n_heads, head_size, already_pruned_heads):
            mask = torch.ones(n_heads, head_size)
            heads = set(heads) - already_pruned_heads
            for head in heads:
                head = head - sum(1 if h < head else 0 for h in already_pruned_heads)
                mask[head] = 0
            mask = mask.view(-1).contiguous().eq(1)
            index = torch.arange(len(mask))[mask].long()
            return heads, index

        modeling_utils.find_pruneable_heads_and_indices = find_pruneable_heads_and_indices

    def _ensure_all_tied_weights_keys(module: Any) -> None:
        if hasattr(module, "all_tied_weights_keys"):
            return
        getter = getattr(module, "get_expanded_tied_weights_keys", None)
        if callable(getter):
            try:
                module.all_tied_weights_keys = getter(all_submodels=False)
                return
            except Exception:  # noqa: BLE001 — fall back to empty mapping
                pass
        module.all_tied_weights_keys = {}

    orig_init_weights = modeling_utils.PreTrainedModel.init_weights
    if not getattr(orig_init_weights, "_radar_compat", False):

        def init_weights_compat(self, *args, **kwargs):  # noqa: ANN001
            _ensure_all_tied_weights_keys(self)
            return orig_init_weights(self, *args, **kwargs)

        init_weights_compat._radar_compat = True  # type: ignore[attr-defined]
        modeling_utils.PreTrainedModel.init_weights = init_weights_compat  # type: ignore[method-assign]

    orig_tie_weights = modeling_utils.PreTrainedModel.tie_weights
    if not getattr(orig_tie_weights, "_radar_compat", False):

        def tie_weights_compat(self, *args, **kwargs):  # noqa: ANN001
            _ensure_all_tied_weights_keys(self)
            return orig_tie_weights(self, *args, **kwargs)

        tie_weights_compat._radar_compat = True  # type: ignore[attr-defined]
        modeling_utils.PreTrainedModel.tie_weights = tie_weights_compat  # type: ignore[method-assign]

    # transformers 5 EmbeddingAccessMixin.set_output_embeddings does
    # ``getattr(self, "lm_head")`` (no default) → AttributeError on damo-radar
    # XBertEncoder which stores the MLM head as ``cls.predictions.decoder``.
    mixin = getattr(modeling_utils, "EmbeddingAccessMixin", None)
    if mixin is not None:
        orig_set_out = mixin.set_output_embeddings
        if not getattr(orig_set_out, "_radar_compat", False):

            def set_output_embeddings_compat(self, new_embeddings):  # noqa: ANN001
                if hasattr(self, "lm_head"):
                    self.lm_head = new_embeddings
                    return None
                # Prefer an explicit override if the class already provides one
                # that is not this mixin method (e.g. BertForMaskedLM in med.py).
                cls_head = getattr(self, "cls", None)
                predictions = getattr(cls_head, "predictions", None) if cls_head is not None else None
                if predictions is not None and hasattr(predictions, "decoder"):
                    predictions.decoder = new_embeddings
                    return None
                # Last resort: create lm_head so later getattr(self, "lm_head") works.
                self.lm_head = new_embeddings
                return None

            set_output_embeddings_compat._radar_compat = True  # type: ignore[attr-defined]
            mixin.set_output_embeddings = set_output_embeddings_compat  # type: ignore[method-assign]


def _patch_xbert_encoder_lm_head(xbert_cls: Any) -> None:
    """Make damo-radar ``XBertEncoder`` look like a transformers 5 LM-head model."""
    if getattr(xbert_cls, "_radar_lm_head_patched", False):
        return

    if not hasattr(xbert_cls, "set_output_embeddings"):

        def set_output_embeddings(self, new_embeddings):  # noqa: ANN001
            self.cls.predictions.decoder = new_embeddings

        xbert_cls.set_output_embeddings = set_output_embeddings

    orig_init = xbert_cls.__init__

    def init_compat(self, *args, **kwargs):  # noqa: ANN001
        orig_init(self, *args, **kwargs)
        # Alias for code paths that still read ``self.lm_head`` directly.
        if hasattr(self, "cls") and not hasattr(self, "lm_head"):
            self.lm_head = self.cls.predictions.decoder

    xbert_cls.__init__ = init_compat  # type: ignore[method-assign]
    xbert_cls._radar_lm_head_patched = True


def _sync_vendor_ckpt_roots(demo: Any, ckpt: Path) -> None:
    """``inference_demo`` freezes MODEL_ROOT/CONFIGS_ROOT at import time — refresh them."""
    root = str(ckpt.resolve())
    os.environ["MODEL_ROOT"] = root
    os.environ["CONFIGS_ROOT"] = root
    if hasattr(demo, "model_root"):
        demo.model_root = root
    if hasattr(demo, "configs_root"):
        demo.configs_root = root


def _clear_failed_vendor_modules() -> None:
    """Drop half-imported vendor modules so a retry can succeed after patching."""
    prefixes = (
        "inference_demo",
        "dynamic_network_architectures",
    )
    for name in list(sys.modules):
        if name == prefixes[0] or name.startswith(prefixes[0] + ".") or name.startswith(
            prefixes[1]
        ):
            sys.modules.pop(name, None)


def import_inference_demo():
    """Import vendor ``inference_demo`` after ensuring its directory is on ``sys.path``."""
    ensure_vendor_on_path()
    _patch_transformers_for_damo_radar()
    try:
        import inference_demo as demo  # noqa: WPS433 — vendor module name
    except ImportError as exc:
        _clear_failed_vendor_modules()
        raise RadarRealError(
            "无法导入 damo-radar 的 inference_demo。"
            f"请确认 vendor 目录完整，并安装依赖：pip install -r {vendor_dir() / 'requirements.txt'}。"
            f"详情: {exc}"
        ) from exc
    return demo


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
        _patch_transformers_for_damo_radar()
        ckpt = ckpt_dir().resolve()
        # Must set env BEFORE importing inference_demo (it freezes configs_root).
        os.environ["MODEL_ROOT"] = str(ckpt)
        os.environ["CONFIGS_ROOT"] = str(ckpt)
        _clear_failed_vendor_modules()

        try:
            import torch
            from monai import transforms
            # Patch must run BEFORE med.py (it imports apply_chunking_to_forward).
            from dynamic_network_architectures.med import XBertEncoder
            from dynamic_network_architectures.vision_branch import VisionBranch

            _patch_xbert_encoder_lm_head(XBertEncoder)
            demo = import_inference_demo()
            _sync_vendor_ckpt_roots(demo, ckpt)
        except ImportError as exc:
            _clear_failed_vendor_modules()
            raise RadarRealError(
                "damo-radar 依赖未安装（需要 torch / monai / transformers 等）。"
                f"请 pip install -r {vendor_dir() / 'requirements.txt'}。详情: {exc}"
            ) from exc
        except RadarRealError:
            raise

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
        if hasattr(text_encoder, "cls") and not hasattr(text_encoder, "lm_head"):
            text_encoder.lm_head = text_encoder.cls.predictions.decoder
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

    # Load runtime first so vendor path is on sys.path before importing demo helpers.
    pad_func, model, device = _load_runtime()
    demo = import_inference_demo()
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
