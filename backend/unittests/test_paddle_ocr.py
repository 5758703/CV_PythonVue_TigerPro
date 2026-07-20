import pytest
from inference import _extract_rec_keys


def test_extract_rec_keys_writes_dict(tmp_path):
    yml = tmp_path / "inference.yml"
    yml.write_text(
        "PostProcess:\n  name: CTCLabelDecode\n  character_dict:\n    - a\n    - b\n    - 中\n",
        encoding="utf-8")
    keys_path = _extract_rec_keys(str(tmp_path))
    lines = open(keys_path, encoding="utf-8").read().splitlines()
    assert lines == ["a", "b", "中"]


def test_extract_rec_keys_idempotent(tmp_path):
    yml = tmp_path / "inference.yml"
    yml.write_text("PostProcess:\n  character_dict:\n    - x\n", encoding="utf-8")
    p1 = _extract_rec_keys(str(tmp_path))
    p2 = _extract_rec_keys(str(tmp_path))
    assert p1 == p2
    assert open(p1, encoding="utf-8").read().splitlines() == ["x"]


def test_extract_rec_keys_missing_dict_raises(tmp_path):
    yml = tmp_path / "inference.yml"
    yml.write_text("PostProcess:\n  name: CTCLabelDecode\n", encoding="utf-8")
    with pytest.raises(ValueError):
        _extract_rec_keys(str(tmp_path))
