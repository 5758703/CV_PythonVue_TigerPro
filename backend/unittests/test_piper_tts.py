"""Piper TTS 四档目录与合成契约单测（不强制联网拉取全量语音）。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services import piper_tts as piper_svc


def test_quality_meta_covers_four_tiers():
    assert tuple(piper_svc.QUALITY_META) == piper_svc.QUALITIES
    for q in piper_svc.QUALITIES:
        meta = piper_svc.QUALITY_META[q]
        assert meta["model_key"] == f"piper-{q}"
        assert meta["default_voice"]


def test_quality_of_model_key():
    assert piper_svc.quality_of_model_key("piper-medium") == "medium"
    assert piper_svc.quality_of_model_key("piper-x_low") == "x_low"
    assert piper_svc.quality_of_model_key("other") is None


def test_list_voices_from_local_catalog(tmp_path: Path):
    catalog = {
        "zh_CN-huayan-medium": {
            "key": "zh_CN-huayan-medium",
            "name": "huayan",
            "quality": "medium",
            "num_speakers": 1,
            "language": {
                "code": "zh_CN",
                "family": "zh",
                "name_english": "Chinese",
                "country_english": "China",
            },
            "files": {
                "zh/zh_CN/huayan/medium/zh_CN-huayan-medium.onnx": {"size_bytes": 1},
                "zh/zh_CN/huayan/medium/zh_CN-huayan-medium.onnx.json": {"size_bytes": 1},
            },
        },
        "en_US-amy-low": {
            "key": "en_US-amy-low",
            "name": "amy",
            "quality": "low",
            "num_speakers": 1,
            "language": {
                "code": "en_US",
                "family": "en",
                "name_english": "English",
                "country_english": "United States",
            },
            "files": {
                "en/en_US/amy/low/en_US-amy-low.onnx": {"size_bytes": 1},
                "en/en_US/amy/low/en_US-amy-low.onnx.json": {"size_bytes": 1},
            },
        },
    }
    path = tmp_path / "voices.json"
    path.write_text(json.dumps(catalog), encoding="utf-8")
    piper_svc._catalog_cache = None
    rows = piper_svc.list_voices(quality="medium", folder=str(tmp_path))
    assert [r["key"] for r in rows] == ["zh_CN-huayan-medium"]
    stats = piper_svc.catalog_stats(str(tmp_path))
    assert stats["voices"] == 2
    assert stats["languages"] == 2
    assert stats["byQuality"]["medium"] == 1
    assert stats["byQuality"]["low"] == 1
    piper_svc._catalog_cache = None


def test_phonemes_to_ids_wraps_bos_pad_eos():
    config = {
        "phoneme_id_map": {
            "_": [0], "^": [1], "$": [2], "a": [14], "b": [15],
        }
    }
    ids = piper_svc._phonemes_to_ids(config, ["a", "b"])
    assert ids[0] == 1 and ids[-1] == 2
    assert 14 in ids and 15 in ids


@pytest.mark.integration
def test_synthesize_local_onnxruntime_x_low_if_weights_present():
    folder = Path("uploads/models/piper-x_low")
    onnx = folder / "zh_CN-huayan-x_low.onnx"
    if not onnx.is_file():
        pytest.skip("piper-x_low 默认语音尚未拉取")
    out = piper_svc.synthesize(str(folder), "你好，欢迎使用 Piper。", quality="x_low")
    assert out.get("engine") == "onnxruntime"
    assert out.get("sampleRate") == 16000
    assert out.get("audio")
    assert out.get("speaker") == "zh_CN-huayan-x_low"


@pytest.mark.integration
def test_synthesize_default_medium_if_weights_present():
    folder = Path("uploads/models/piper-medium")
    onnx = folder / "zh_CN-huayan-medium.onnx"
    if not onnx.is_file():
        pytest.skip("piper-medium 默认语音尚未拉取")
    out = piper_svc.synthesize(str(folder), "你好，欢迎使用 Piper。", quality="medium")
    assert out.get("engine") == "onnxruntime"
    assert out.get("sampleRate")
    assert out.get("audio")
    assert out.get("speaker") == "zh_CN-huayan-medium"
