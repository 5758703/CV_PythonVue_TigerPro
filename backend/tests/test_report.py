import report
import deepseek


_DETS = [
    {"className": "person", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
    {"className": "person", "confidence": 0.7, "bbox": [0, 0, 10, 10]},
]


def test_build_report_ai_success(monkeypatch):
    monkeypatch.setattr(report.deepseek, "chat_json", lambda s, u: {
        "summary": "检出2人",
        "risk": {"level": "中", "desc": "人员聚集"},
        "findings": [{"className": "person", "note": "2 个"}],
        "suggestions": [{"title": "疏导", "detail": "分流"}],
        "conclusion": "建议关注",
    })
    rep = report.build_report("yolo", "生产安全风险识别", _DETS, 100, 100, 0.25, "a.jpg")
    assert rep["meta"]["aiAvailable"] is True
    assert rep["meta"]["modelName"] == "yolo"
    assert rep["stats"]["total"] == 2
    assert rep["stats"]["byClass"][0]["className"] == "person"
    assert rep["stats"]["byClass"][0]["count"] == 2
    assert rep["summary"] == "检出2人"
    assert rep["matchedCases"]
    assert rep["keywords"]
    assert rep["warning"] is None


def test_build_report_falls_back_when_ai_fails(monkeypatch):
    def _boom(s, u):
        raise deepseek.DeepSeekError("network down")
    monkeypatch.setattr(report.deepseek, "chat_json", _boom)
    rep = report.build_report("yolo", "通用", _DETS, 100, 100, 0.25, "a.jpg")
    assert rep["meta"]["aiAvailable"] is False
    assert rep["warning"]
    # 兜底建议来自案例库
    assert len(rep["suggestions"]) >= 1
    assert rep["risk"]["level"] in ("高", "中", "低")
    assert rep["stats"]["total"] == 2
