"""RADAR service unit tests (no GPU / checkpoint required)."""
from __future__ import annotations

from pathlib import Path

import pytest

from services import radar
from services import radar_real


def test_radar_status_mock(monkeypatch, tmp_path):
    monkeypatch.setattr(radar.Config, "RADAR_ENGINE", "auto")
    monkeypatch.setattr(radar.Config, "RADAR_CKPT_DIR", str(tmp_path / "empty"))
    monkeypatch.setattr(radar.Config, "RADAR_VENDOR_DIR", str(tmp_path / "novendor"))
    monkeypatch.setattr(radar.Config, "RADAR_POSITIVE_THRESHOLD", 0.5)
    monkeypatch.setattr(radar_real.Config, "RADAR_CKPT_DIR", str(tmp_path / "empty"))
    monkeypatch.setattr(radar_real.Config, "RADAR_VENDOR_DIR", str(tmp_path / "novendor"))
    st = radar.status()
    assert st["engine"] == "mock"
    assert st["weightsReady"] is False
    assert st["vendorReady"] is False
    assert st["ready"] is False
    assert "医生" in st["disclaimer"]


def test_radar_infer_mock_without_file(monkeypatch, tmp_path):
    monkeypatch.setattr(radar.Config, "RADAR_ENGINE", "mock")
    monkeypatch.setattr(radar.Config, "RADAR_CKPT_DIR", str(tmp_path))
    out = radar.infer()
    assert out["engine"] == "mock"
    assert out["findings"]
    assert "name" in out["findings"][0]
    assert "score" in out["findings"][0]
    assert "positive" in out["findings"][0]
    assert out["positiveCount"] == sum(1 for f in out["findings"] if f["positive"])
    assert out["meta"]["source"] == "demo_csv"


def test_radar_infer_mock_with_nifti_name(monkeypatch, tmp_path):
    monkeypatch.setattr(radar.Config, "RADAR_ENGINE", "mock")
    monkeypatch.setattr(radar.Config, "RADAR_CKPT_DIR", str(tmp_path))
    out = radar.infer(filename="case.nii.gz", data=b"fake")
    assert out["engine"] == "mock"
    assert out["meta"]["filename"] == "case.nii.gz"
    assert out["meta"]["source"] == "demo_content"
    assert out["meta"]["contentFingerprint"]


def test_radar_infer_mock_with_image_name(monkeypatch, tmp_path):
    monkeypatch.setattr(radar.Config, "RADAR_ENGINE", "mock")
    monkeypatch.setattr(radar.Config, "RADAR_CKPT_DIR", str(tmp_path))
    out = radar.infer(filename="slice.png", data=b"x")
    assert out["engine"] == "mock"
    assert out["meta"]["filename"] == "slice.png"
    out_jpg = radar.infer(filename="scan.jpg", data=b"x")
    assert out_jpg["meta"]["filename"] == "scan.jpg"


def test_radar_mock_scores_depend_on_content(monkeypatch, tmp_path):
    monkeypatch.setattr(radar.Config, "RADAR_ENGINE", "mock")
    monkeypatch.setattr(radar.Config, "RADAR_CKPT_DIR", str(tmp_path))
    a = radar.infer(filename="a.jpg", data=b"content-alpha-111")
    b = radar.infer(filename="b.jpg", data=b"content-beta-2222")
    again = radar.infer(filename="a.jpg", data=b"content-alpha-111")
    scores_a = [item["score"] for item in a["findings"]]
    scores_b = [item["score"] for item in b["findings"]]
    scores_again = [item["score"] for item in again["findings"]]
    assert scores_a == scores_again
    assert scores_a != scores_b
    assert a["meta"]["contentFingerprint"] != b["meta"]["contentFingerprint"]
    assert [item["name"] for item in a["findings"]] != [item["name"] for item in b["findings"]] or (
        a["positiveCount"] != b["positiveCount"]
    )


def test_radar_reject_bad_ext(monkeypatch, tmp_path):
    monkeypatch.setattr(radar.Config, "RADAR_ENGINE", "mock")
    monkeypatch.setattr(radar.Config, "RADAR_CKPT_DIR", str(tmp_path))
    with pytest.raises(radar.RadarError):
        radar.infer(filename="notes.txt", data=b"x")


def test_radar_real_falls_back_to_mock_for_2d_image(monkeypatch, tmp_path):
    """When weights are ready (engine=real), JPG/PNG still run via demo engine."""
    monkeypatch.setattr(radar.Config, "RADAR_ENGINE", "auto")
    monkeypatch.setattr(radar, "resolve_engine", lambda forced=None: "real")
    monkeypatch.setattr(radar.Config, "RADAR_CKPT_DIR", str(tmp_path))
    out = radar.infer(filename="slice.png", data=b"png-bytes")
    assert out["engine"] == "mock"
    assert out["meta"]["fallbackFrom"] == "real"
    assert out["meta"]["fallbackReason"] == "2d_image"
    assert "演示引擎" in out["meta"]["disclaimer"]
    assert out["findings"]
    assert out["meta"]["contentFingerprint"]


def test_radar_real_without_weights_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(radar.Config, "RADAR_ENGINE", "real")
    monkeypatch.setattr(radar.Config, "RADAR_CKPT_DIR", str(tmp_path))
    monkeypatch.setattr(radar.Config, "RADAR_VENDOR_DIR", str(tmp_path / "novendor"))
    monkeypatch.setattr(radar_real.Config, "RADAR_CKPT_DIR", str(tmp_path))
    monkeypatch.setattr(radar_real.Config, "RADAR_VENDOR_DIR", str(tmp_path / "novendor"))
    with pytest.raises(radar.RadarError):
        radar.resolve_engine()


def test_radar_real_ready_requires_vendor_and_weights(monkeypatch, tmp_path):
    ckpt = tmp_path / "radar"
    ckpt.mkdir()
    (ckpt / "checkpoint_radar_pretrain.pth").write_bytes(b"x")
    bert = ckpt / "bert-base-chinese"
    bert.mkdir()
    (bert / "config.json").write_text("{}", encoding="utf-8")
    (bert / "pytorch_model.bin").write_bytes(b"x")
    (ckpt / "infer_text_embedding_radar.pt").write_bytes(b"x" * 2048)
    vendor = tmp_path / "vendor"
    infer = vendor / "RADAR_inference"
    infer.mkdir(parents=True)
    (infer / "inference_demo.py").write_text("# stub\n", encoding="utf-8")

    monkeypatch.setattr(radar.Config, "RADAR_ENGINE", "auto")
    monkeypatch.setattr(radar.Config, "RADAR_CKPT_DIR", str(ckpt))
    monkeypatch.setattr(radar.Config, "RADAR_VENDOR_DIR", str(vendor))
    monkeypatch.setattr(radar_real.Config, "RADAR_CKPT_DIR", str(ckpt))
    monkeypatch.setattr(radar_real.Config, "RADAR_VENDOR_DIR", str(vendor))

    # Tiny stub files: override size gates used by weights_ready().
    monkeypatch.setattr(radar, "weights_ready", lambda directory=None: True)
    monkeypatch.setattr(radar_real, "weights_ready", lambda directory=None: True)
    assert radar.vendor_ready() is True
    assert radar.resolve_engine() == "real"


def test_radar_parse_result_csv(tmp_path):
    csv_path = tmp_path / "out.csv"
    csv_path.write_text(
        "file_name,胆囊_结石 (Gallbladder_Cholecystolithiasis),主动脉_动脉硬化 (Aorta_Atherosclerosis)\n"
        "case.nii.gz,0.91,0.42\n",
        encoding="utf-8-sig",
    )
    scores = radar_real.parse_result_csv(csv_path)
    assert scores["Gallbladder_Cholecystolithiasis"] == pytest.approx(0.91)
    assert scores["Aorta_Atherosclerosis"] == pytest.approx(0.42)
    selected = radar_real._select_merlin_scores(scores)
    names = dict(selected)
    assert names["gallstones"] == pytest.approx(0.91)
    assert names["atherosclerosis"] == pytest.approx(0.42)


def test_import_inference_demo_puts_vendor_on_path(monkeypatch, tmp_path):
    """Regression: evaluate path used to import before sys.path was patched."""
    import sys
    import types

    vendor = tmp_path / "vendor"
    infer = vendor / "RADAR_inference"
    infer.mkdir(parents=True)
    (infer / "inference_demo.py").write_text(
        "RADAR = object\ndef evaluate(*a, **k):\n    return None\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(radar_real, "vendor_dir", lambda: vendor)
    monkeypatch.setattr(radar_real, "inference_dir", lambda: infer)
    # Drop any previously loaded stub and ensure path was not already present.
    sys.modules.pop("inference_demo", None)
    while str(infer.resolve()) in sys.path:
        sys.path.remove(str(infer.resolve()))

    demo = radar_real.import_inference_demo()
    assert isinstance(demo, types.ModuleType)
    assert hasattr(demo, "evaluate")
    assert str(infer.resolve()) == sys.path[0]


def test_transformers_compat_patch_exposes_chunking_helpers(monkeypatch):
    """med.py imports apply_chunking_to_forward from modeling_utils (transformers 4.x)."""
    from transformers import modeling_utils

    # Simulate a transformers 5 install missing the re-exports.
    for name in (
        "apply_chunking_to_forward",
        "prune_linear_layer",
        "find_pruneable_heads_and_indices",
    ):
        if hasattr(modeling_utils, name):
            monkeypatch.delattr(modeling_utils, name, raising=False)

    radar_real._patch_transformers_for_damo_radar()
    assert callable(modeling_utils.apply_chunking_to_forward)
    assert callable(modeling_utils.prune_linear_layer)
    assert callable(modeling_utils.find_pruneable_heads_and_indices)


def test_transformers_compat_init_weights_sets_tied_keys():
    """Vendor BertModel calls init_weights() without post_init(); transformers 5 needs tied keys."""
    from transformers import modeling_utils
    from transformers.models.bert.configuration_bert import BertConfig

    radar_real._patch_transformers_for_damo_radar()

    class TinyBert(modeling_utils.PreTrainedModel):
        config_class = BertConfig

        def __init__(self, config):
            super().__init__(config)
            import torch.nn as nn

            self.embed = nn.Embedding(config.vocab_size, config.hidden_size)
            # Mimic damo-radar BertModel: call init_weights without post_init.
            self.init_weights()

        def _init_weights(self, module):  # noqa: ANN001
            return None

    cfg = BertConfig(vocab_size=32, hidden_size=8, num_hidden_layers=1, num_attention_heads=2, intermediate_size=16)
    model = TinyBert(cfg)
    assert hasattr(model, "all_tied_weights_keys")
    assert isinstance(model.all_tied_weights_keys, dict)


def test_transformers_compat_set_output_embeddings_without_lm_head():
    """XBertEncoder uses cls.predictions.decoder; transformers 5 set_output_embeddings wants lm_head."""
    import torch.nn as nn
    from transformers import modeling_utils
    from transformers.models.bert.configuration_bert import BertConfig

    radar_real._patch_transformers_for_damo_radar()

    class LegacyBertHead(modeling_utils.PreTrainedModel):
        config_class = BertConfig

        def __init__(self, config):
            super().__init__(config)
            self.cls = nn.Module()
            self.cls.predictions = nn.Module()
            self.cls.predictions.decoder = nn.Linear(config.hidden_size, config.vocab_size, bias=False)

        def _init_weights(self, module):  # noqa: ANN001
            return None

    cfg = BertConfig(vocab_size=32, hidden_size=8, num_hidden_layers=1, num_attention_heads=2, intermediate_size=16)
    model = LegacyBertHead(cfg)
    assert not hasattr(model, "lm_head")
    replacement = nn.Linear(cfg.hidden_size, cfg.vocab_size, bias=False)
    model.set_output_embeddings(replacement)
    assert model.cls.predictions.decoder is replacement


def test_radar_infer_real_uses_adapter(monkeypatch, tmp_path):
    monkeypatch.setattr(radar, "resolve_engine", lambda forced=None: "real")
    monkeypatch.setattr(radar.Config, "RADAR_CKPT_DIR", str(tmp_path))

    def fake_run(path, *, threshold=0.5):
        return {
            "engine": "real",
            "findings": [{"name": "gallstones", "score": 0.88, "positive": True}],
            "threshold": threshold,
            "positiveCount": 1,
            "meta": {"source": "damo-radar", "filename": Path(path).name},
        }

    monkeypatch.setattr("services.radar_real.run_nifti", fake_run)
    out = radar.infer(filename="case.nii.gz", data=b"nifti-bytes", threshold=0.5)
    assert out["engine"] == "real"
    assert out["findings"][0]["name"] == "gallstones"
    saved = tmp_path / "uploads" / "case.nii.gz"
    assert saved.is_file()
    assert saved.read_bytes() == b"nifti-bytes"


def test_radar_report_uses_abdominal_category(monkeypatch):
    captured = {}

    def fake_build_report(**kwargs):
        captured.update(kwargs)
        return {
            "summary": "ok",
            "meta": {"aiAvailable": False},
            "disclaimer": "医学免责声明",
        }

    monkeypatch.setattr("report.build_report", fake_build_report)
    findings = [
        {"name": "gallstones", "score": 0.91, "positive": True},
        {"name": "fracture", "score": 0.08, "positive": False},
    ]
    out = radar.build_assistive_report(findings, threshold=0.5)
    assert out["summary"] == "ok"
    assert captured["model_category"] == "医学影像-腹部CT"
    assert captured["model_name"] == "RADAR 腹部 CT 诊断"
    assert any(d["className"] == "gallstones" for d in captured["detections"])
