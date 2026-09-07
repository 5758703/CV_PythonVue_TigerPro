from pathlib import Path

from routes.ai_model import _select_huggingface_weight


SEED_SOURCE = Path(__file__).resolve().parents[1] / "seed.py"


def test_mobile_phone_detector_is_registered_from_huggingface():
    source = SEED_SOURCE.read_text(encoding="utf-8")

    assert '"yolov8n-mobile-phone"' in source
    assert "https://huggingface.co/IndUSV/yolov8n-mobile-phone#pytorch_model.bin" in source


def test_phone_use_alert_rule_covers_detector_label_aliases():
    source = SEED_SOURCE.read_text(encoding="utf-8")

    assert 'rule_key="phone-use"' in source
    for class_name in ("mobile_phone", "cellphone", "cell phone", "phone"):
        assert f'"{class_name}"' in source


def test_ultralytics_huggingface_bin_checkpoint_is_renamed_to_pt():
    remote_name, local_name = _select_huggingface_weight(
        ["README.md", "pytorch_model.bin"],
        want="pytorch_model.bin",
        allow_ultralytics_bin=True,
    )

    assert remote_name == "pytorch_model.bin"
    assert local_name == "pytorch_model.pt"
