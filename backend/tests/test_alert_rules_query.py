"""alert_rules_query 单测。"""
from services.alert_rules_query import parse_rule_keys


def test_parse_rule_keys_none():
    assert parse_rule_keys(None) is None


def test_parse_rule_keys_empty():
    assert parse_rule_keys([]) == []
    assert parse_rule_keys("") == []
    assert parse_rule_keys("[]") == []


def test_parse_rule_keys_json_and_csv():
    assert parse_rule_keys('["fire-smoke","ppe-no-hardhat"]') == ["fire-smoke", "ppe-no-hardhat"]
    assert parse_rule_keys("fire-smoke, crowd-gathering") == ["fire-smoke", "crowd-gathering"]
    assert parse_rule_keys(["a", "a", "b"]) == ["a", "b"]
