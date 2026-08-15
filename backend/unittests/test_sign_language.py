"""中国手语 YOLO 服务单测（不加载权重推理）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.sign_language import (  # noqa: E402
    filter_by_hand_regions,
    format_csl_display,
    is_plausible_hand_box,
    load_class_names_dict,
    list_recognizers,
    resolve_weight_path,
)


def test_list_recognizers_has_two_modes():
    rs = list_recognizers()
    ids = {r["id"] for r in rs}
    assert "mediapipe" in ids
    assert "csl-yolo11s" in ids


def test_load_class_names_from_env():
    base = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "uploads", "models", "chinese-sign-language-tigerhhzz-yolo11s",
    )
    if not os.path.isdir(base):
        return
    names = load_class_names_dict(base)
    assert len(names) == 30
    assert names[0] == "A"
    assert names[29] == "ZH"


def test_format_csl_display_top_conf():
    dets = [
        {"className": "B", "confidence": 0.7},
        {"className": "A", "confidence": 0.92},
    ]
    r = format_csl_display(dets)
    assert r["displayText"] == "A"
    assert r["primaryLabel"] == "A"
    assert "A" in r["labelZh"]


def test_format_csl_display_empty():
    assert format_csl_display([])["displayText"] is None


def test_resolve_weight_path_on_disk():
    base = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "uploads", "models", "chinese-sign-language-tigerhhzz-yolo11s",
    )
    if not os.path.isdir(base):
        return
    p = resolve_weight_path(base)
    assert os.path.isfile(p)
    assert p.lower().endswith(".onnx")


def test_reject_thin_background_strip():
    """截图类误检：细长竖条不应当作手语框。"""
    img_w, img_h = 480, 270
    thin = [40, 20, 55, 240]  # 宽 15、高 220
    assert not is_plausible_hand_box(thin, img_w, img_h)
    hand = [280, 80, 400, 220]
    assert is_plausible_hand_box(hand, img_w, img_h)


def test_square_crop_bbox_is_roughly_square():
    from services.sign_language import square_crop_bbox

    box = square_crop_bbox([100, 200, 180, 280], 640, 480, scale=1.0)
    w = box[2] - box[0]
    h = box[3] - box[1]
    assert abs(w - h) <= 2
    assert box[0] >= 0 and box[1] >= 0
    assert box[2] <= 640 and box[3] <= 480


def test_filter_by_hand_regions_drops_background():
    dets = [
        {"className": "B", "confidence": 0.33, "bbox": [40, 20, 55, 240]},
        {"className": "A", "confidence": 0.72, "bbox": [280, 80, 400, 220]},
    ]
    hands = [[270, 70, 410, 230]]
    kept = filter_by_hand_regions(dets, hands)
    assert [d["className"] for d in kept] == ["A"]
