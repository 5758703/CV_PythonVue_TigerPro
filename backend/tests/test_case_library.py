from case_library import extract_keywords, search_cases, CASES


def test_cases_have_two_categories():
    cats = {c["category"] for c in CASES}
    assert "生产安全风险识别" in cats
    assert "通用" in cats


def test_every_case_has_required_fields():
    for c in CASES:
        for f in ("id", "category", "title", "scene", "keywords",
                  "match_classes", "risk_level", "suggestion"):
            assert f in c, f"案例 {c.get('id')} 缺字段 {f}"
        assert c["risk_level"] in ("高", "中", "低")


def test_extract_keywords_from_detections():
    dets = [{"className": "person", "confidence": 0.9, "bbox": [0, 0, 1, 1]},
            {"className": "person", "confidence": 0.8, "bbox": [0, 0, 1, 1]},
            {"className": "helmet", "confidence": 0.7, "bbox": [0, 0, 1, 1]}]
    kws = extract_keywords(dets, "生产安全风险识别")
    assert "person" in kws
    assert "helmet" in kws
    # 去重：person 出现两次只保留一个
    assert kws.count("person") == 1
    # 模型分类作为关键词纳入
    assert "生产安全风险识别" in kws


def test_search_cases_matches_by_class():
    cases = search_cases(["person", "未戴安全帽"], ["person", "helmet"], top_n=3)
    assert len(cases) >= 1
    assert all("suggestion" in c for c in cases)


def test_search_cases_empty_match_falls_back_to_general():
    cases = search_cases(["完全不相关xyz"], ["不存在的类"], top_n=3)
    assert len(cases) >= 1
    assert all(c["category"] == "通用" for c in cases)
