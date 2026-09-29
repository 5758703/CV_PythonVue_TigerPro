"""Training hyperparameter / augmentation whitelist tests."""
from __future__ import annotations

from services.training import normalize_train_hyperparams, train_aug_kwargs_from_hp


def test_normalize_basic_aug_defaults():
    hp = normalize_train_hyperparams({})
    assert hp["epochs"] == 100
    assert hp["mosaic"] == 1.0
    assert hp["mixup"] == 0.1
    assert hp["copy_paste"] == 0.1
    assert hp["scale"] == 0.5
    assert hp["fliplr"] == 0.5
    assert hp["enhancedAug"] is False
    assert "degrees" not in hp
    assert "cos_lr" not in hp


def test_normalize_enhanced_aug_mode():
    hp = normalize_train_hyperparams({"enhancedAug": True, "degrees": 99, "cos_lr": "true"})
    assert hp["enhancedAug"] is True
    assert hp["degrees"] == 45.0  # clamped
    assert hp["flipud"] == 0.5
    assert hp["hsv_s"] == 0.7
    assert hp["erasing"] == 0.3
    assert hp["cos_lr"] is True


def test_train_aug_kwargs_respects_enhanced_flag():
    basic = train_aug_kwargs_from_hp(normalize_train_hyperparams({"mixup": 0.2}))
    assert basic["mixup"] == 0.2
    assert "flipud" not in basic
    assert "cos_lr" not in basic

    enhanced = train_aug_kwargs_from_hp(normalize_train_hyperparams({"enhancedAug": 1}))
    assert enhanced["mosaic"] == 1.0
    assert enhanced["flipud"] == 0.5
    assert enhanced["cos_lr"] is True
    assert "perspective" in enhanced


def test_normalize_clamps_and_drops_unknown():
    hp = normalize_train_hyperparams({
        "epochs": 9999,
        "batch": -3,
        "mosaic": 2.5,
        "unknown_hack": "boom",
    })
    assert hp["epochs"] == 500
    assert hp["batch"] == 1
    assert hp["mosaic"] == 1.0
    assert "unknown_hack" not in hp
