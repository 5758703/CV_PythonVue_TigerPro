"""羽毛球自训：基座解析、Roboflow zip、部署默认字段。"""
import os
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.training import (  # noqa: E402
    badminton_deploy_defaults,
    extract_zip_dataset,
    list_base_models,
    resolve_base_model,
    unwrap_dataset_root,
    _is_roboflow_yolo_layout,
)


def test_list_base_models_includes_yolo11():
    opts = list_base_models(None)
    values = {o["value"] for o in opts}
    assert "yolo11n.pt" in values
    assert "yolo11s.pt" in values


def test_resolve_base_model_official_name():
    expected = Path(__file__).resolve().parent.parent / "weights" / "yolo11n.pt"
    resolved = resolve_base_model("yolo11n.pt")
    if expected.is_file():
        assert Path(resolved) == expected
    else:
        assert resolved == "yolo11n.pt"
    empty_resolved = resolve_base_model("")
    if expected.is_file():
        assert Path(empty_resolved) == expected
    else:
        assert empty_resolved == "yolo11n.pt"


def test_resolve_local_yolo11s_ball(tmp_path):
    root = tmp_path / "uploads"
    pt = root / "models" / "yolo11s-ball" / "yolo11s-ball.pt"
    pt.parent.mkdir(parents=True)
    pt.write_bytes(b"fake")
    resolved = resolve_base_model("local:yolo11s-ball", root)
    assert Path(resolved) == pt


def test_roboflow_zip_strip_and_detect(tmp_path):
    zpath = tmp_path / "rf.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("MyProj.v1/data.yaml", "names: [badminton]\nnc: 1\n")
        zf.writestr("MyProj.v1/train/images/a.jpg", b"x")
        zf.writestr("MyProj.v1/train/labels/a.txt", "0 0.5 0.5 0.1 0.1\n")
        zf.writestr("MyProj.v1/valid/images/b.jpg", b"x")
        zf.writestr("MyProj.v1/valid/labels/b.txt", "0 0.5 0.5 0.1 0.1\n")
    dest = tmp_path / "raw"
    n = extract_zip_dataset(zpath, dest)
    assert n >= 4
    root = unwrap_dataset_root(dest)
    assert _is_roboflow_yolo_layout(root)
    assert (root / "train" / "images" / "a.jpg").is_file()


def test_badminton_deploy_defaults():
    job = type("J", (), {"id": 12, "base_model": "yolo11s.pt"})()
    d = badminton_deploy_defaults(job)
    assert d["category"] == "目标检测"
    assert d["task"] == "object-detection"
    assert "12" in d["modelKey"]
    assert "s" in d["modelKey"]
