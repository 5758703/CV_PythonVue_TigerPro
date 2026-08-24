"""Unit tests for defect_diagnosis (Qwen-VL cloud-first engine)."""
from __future__ import annotations

import json

import numpy as np
import pytest

from services import defect_diagnosis as dd


def test_filter_suspicious_gate():
    dets = [
        {"className": "a", "confidence": 0.2, "bbox": [0, 0, 1, 1]},
        {"className": "b", "confidence": 0.45, "bbox": [0, 0, 1, 1]},
        {"className": "c", "confidence": 0.9, "bbox": [0, 0, 1, 1]},
        {"className": "d", "confidence": "bad", "bbox": [0, 0, 1, 1]},
    ]
    out = dd.filter_suspicious(dets, 0.45)
    assert [x["className"] for x in out] == ["b", "c"]


def test_extract_json_object_plain_and_fence():
    plain = '{"defectType":"crack","severity":"high","confidence":0.8}'
    assert dd.extract_json_object(plain)["defectType"] == "crack"

    fenced = '说明如下：\n```json\n{"defectType":"void","severity":"medium"}\n```\n完'
    assert dd.extract_json_object(fenced)["defectType"] == "void"

    noisy = 'prefix {"defectType":"scratch","severity":"low"} trailing'
    assert dd.extract_json_object(noisy)["defectType"] == "scratch"


def test_extract_json_object_empty_raises():
    with pytest.raises(ValueError):
        dd.extract_json_object("")
    with pytest.raises(ValueError):
        dd.extract_json_object("no braces here")


def test_normalize_diagnosis_defaults():
    det = {"className": "bubble", "confidence": 0.77, "bbox": [1, 2, 3, 4]}
    out = dd.normalize_diagnosis(
        {"processAdvice": "单条建议", "severity": "weird", "confidence": 1.5},
        detection=det,
        scenario="injection",
        engine="qwen_vl",
    )
    assert out["engine"] == "qwen_vl"
    assert out["severity"] == "medium"
    assert out["confidence"] == 1.0
    assert out["processAdvice"] == ["单条建议"]
    assert out["className"] == "bubble"
    assert out["defectType"] == "bubble"


def test_fallback_diagnosis_scenarios():
    det = {"className": "void", "confidence": 0.6, "bbox": [10, 10, 40, 40]}
    for sc in ("general", "pcb", "injection"):
        r = dd.fallback_diagnosis(det, sc)
        assert r["engine"] == "fallback"
        assert r["scenario"] == sc
        assert r["defectType"]
        assert r["rootCause"]
        assert isinstance(r["processAdvice"], list) and len(r["processAdvice"]) >= 1
        assert 0 <= r["confidence"] <= 1


def test_build_diagnosis_prompt_includes_scenario():
    det = {"className": "solder", "confidence": 0.5}
    p = dd.build_diagnosis_prompt("pcb", det)
    assert "PCB" in p or "pcb" in p.lower() or "锡" in p
    assert "solder" in p
    assert "JSON" in p


def test_chat_vision_json_success(monkeypatch):
    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "defectType": "气孔",
                                    "severity": "high",
                                    "locationDesc": "圆角区",
                                    "rootCause": "保压不足",
                                    "processAdvice": ["延长保压"],
                                    "confidence": 0.88,
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            }

    monkeypatch.setattr(dd.Config, "QWEN_VL_API_KEY", "test-key")
    monkeypatch.setattr(dd.Config, "QWEN_VL_BASE_URL", "https://example.test/v1")
    monkeypatch.setattr(dd.Config, "QWEN_VL_MODEL", "qwen-vl-plus")
    monkeypatch.setattr(dd.requests, "post", lambda *a, **k: _Resp())

    obj = dd.chat_vision_json("abc123", "diagnose")
    assert obj["defectType"] == "气孔"
    assert "_rawText" in obj


def test_chat_vision_json_requires_key(monkeypatch):
    monkeypatch.setattr(dd.Config, "QWEN_VL_API_KEY", "")
    with pytest.raises(dd.QwenVLError):
        dd.chat_vision_json("x", "p")


def test_chat_vision_json_invalid_json(monkeypatch):
    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "not a json object"}}]}

    monkeypatch.setattr(dd.Config, "QWEN_VL_API_KEY", "k")
    monkeypatch.setattr(dd.Config, "QWEN_VL_BASE_URL", "https://example.test/v1")
    monkeypatch.setattr(dd.requests, "post", lambda *a, **k: _Resp())
    with pytest.raises(dd.QwenVLError):
        dd.chat_vision_json("x", "p")


def test_diagnose_one_fallback_without_key(monkeypatch):
    monkeypatch.setattr(dd, "qwen_vl_configured", lambda: False)
    det = {"className": "scratch", "confidence": 0.7, "bbox": [0, 0, 5, 5]}
    r = dd.diagnose_one(det, "fakeroi", "general")
    assert r["engine"] == "fallback"


def test_diagnose_one_qwen_success(monkeypatch):
    monkeypatch.setattr(dd, "qwen_vl_configured", lambda: True)
    monkeypatch.setattr(
        dd,
        "chat_vision_json",
        lambda *a, **k: {
            "defectType": "裂纹",
            "severity": "critical",
            "locationDesc": "边缘",
            "rootCause": "应力集中",
            "processAdvice": ["降速"],
            "confidence": 0.91,
            "_rawText": "{}",
        },
    )
    det = {"className": "crack", "confidence": 0.8, "bbox": [0, 0, 5, 5]}
    r = dd.diagnose_one(det, "roi", "general")
    assert r["engine"] == "qwen_vl"
    assert r["defectType"] == "裂纹"
    assert r["severity"] == "critical"


def test_diagnose_one_qwen_fail_falls_back(monkeypatch):
    monkeypatch.setattr(dd, "qwen_vl_configured", lambda: True)

    def _boom(*a, **k):
        raise dd.QwenVLError("network")

    monkeypatch.setattr(dd, "chat_vision_json", _boom)
    det = {"className": "x", "confidence": 0.5, "bbox": [0, 0, 1, 1]}
    r = dd.diagnose_one(det, "roi", "pcb")
    assert r["engine"] == "fallback"
    assert "network" in (r.get("rawText") or "")


def test_expand_bbox_clamped():
    box = dd._expand_bbox([10, 10, 20, 20], 100, 100, 0.1)
    assert box[0] <= 10 and box[1] <= 10
    assert box[2] >= 20 and box[3] >= 20
    tiny = dd._expand_bbox([0, 0, 0, 0], 10, 10, 0.5)
    assert tiny[2] > tiny[0] and tiny[3] > tiny[1]


def test_segment_boxes_rect_without_seg(monkeypatch):
    # 32x32 black jpeg
    import cv2

    img = np.zeros((32, 32, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    masks = dd.segment_boxes(buf.tobytes(), [[4, 4, 20, 20]], seg_path=None, seg_lib=None)
    assert len(masks) == 1 and masks[0]


def test_run_pipeline_fallback(monkeypatch):
    import cv2

    img = np.zeros((64, 64, 3), dtype=np.uint8)
    cv2.rectangle(img, (10, 10), (40, 40), (0, 0, 255), -1)
    ok, buf = cv2.imencode(".jpg", img)
    raw = buf.tobytes()

    monkeypatch.setattr(dd, "qwen_vl_configured", lambda: False)

    def _fake_detect(path, image_bytes, conf=0.25, draw=False, model_key=None):
        return {
            "detections": [
                {"className": "defect", "confidence": 0.8, "bbox": [10, 10, 40, 40]},
                {"className": "noise", "confidence": 0.1, "bbox": [0, 0, 5, 5]},
            ],
            "width": 64,
            "height": 64,
        }

    monkeypatch.setattr("inference.detect_image", _fake_detect, raising=False)
    # Patch where run_pipeline imports it
    import inference as inf

    monkeypatch.setattr(inf, "detect_image", _fake_detect)

    out = dd.run_pipeline(
        raw,
        det_path="/tmp/fake.pt",
        conf=0.25,
        suspicious_conf=0.45,
        scenario="injection",
        draw=True,
    )
    assert out["detCount"] == 2
    assert out["suspiciousCount"] == 1
    assert len(out["diagnoses"]) == 1
    assert out["diagnoses"][0]["engine"] == "fallback"
    assert out["engines"]["diagnosis"] == "fallback"
    assert out["imageBase64"]


def test_engine_status_shape(monkeypatch):
    monkeypatch.setattr(dd.Config, "QWEN_VL_API_KEY", "")
    st = dd.engine_status()
    assert st["mode"] == "cloud_first"
    assert st["qwenVlConfigured"] is False
    assert "suspiciousConfDefault" in st
