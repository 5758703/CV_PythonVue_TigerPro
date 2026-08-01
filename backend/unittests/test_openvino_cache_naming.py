"""OpenVINO 缓存目录命名须被 Ultralytics 识别。"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from inference import (  # noqa: E402
    _find_openvino_load_path,
    _openvino_legacy_target_dir,
    _openvino_target_dir,
    _purge_invalid_openvino_dir,
)


def test_openvino_target_dir_ends_with_openvino_model(tmp_path):
    pt = tmp_path / "best.pt"
    pt.write_bytes(b"x")
    d = _openvino_target_dir(str(pt), precision="fp16", imgsz=640)
    assert os.path.basename(d).endswith("_openvino_model")
    assert "fp16" in os.path.basename(d)
    assert "i640" in os.path.basename(d)


def test_find_openvino_rejects_legacy_dir_name(tmp_path):
    legacy = tmp_path / "best_openvino_fp16_i640"
    legacy.mkdir()
    (legacy / "best.xml").write_text("<net/>", encoding="utf-8")
    (legacy / "best.bin").write_bytes(b"\x00\x01")
    assert _find_openvino_load_path(str(legacy)) is None


def test_find_openvino_accepts_valid_dir(tmp_path):
    good = tmp_path / "best_openvino_fp16_i640_openvino_model"
    good.mkdir()
    (good / "best.xml").write_text("<net/>", encoding="utf-8")
    (good / "best.bin").write_bytes(b"\x00\x01")
    assert _find_openvino_load_path(str(good)) == str(good)


def test_purge_legacy_openvino_dir(tmp_path):
    pt = tmp_path / "best.pt"
    pt.write_bytes(b"x")
    legacy = _openvino_legacy_target_dir(str(pt), precision="fp16", imgsz=640)
    os.makedirs(legacy, exist_ok=True)
    with open(os.path.join(legacy, "x.xml"), "w", encoding="utf-8") as f:
        f.write("<net/>")
    _purge_invalid_openvino_dir(legacy)
    assert not os.path.isdir(legacy)
