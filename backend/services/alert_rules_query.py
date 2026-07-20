"""告警规则查询：加载启用中的规则（status=0），供 evaluate / 视频任务使用。

可选 ruleKeys 过滤（兼容旧客户端）；当前前端仅依赖规则 status 单项开关。
"""
from __future__ import annotations


def parse_rule_keys(raw) -> list[str] | None:
    """解析可选的 ruleKeys；None 表示未传（使用全部启用规则）。

    空列表表示明确不选任何规则。
    """
    if raw is None:
        return None
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return []
        if s.startswith("["):
            try:
                import json
                raw = json.loads(s)
            except (TypeError, ValueError, json.JSONDecodeError):
                raw = [x.strip() for x in s.replace("，", ",").split(",") if x.strip()]
        else:
            raw = [x.strip() for x in s.replace("，", ",").split(",") if x.strip()]
    if not isinstance(raw, (list, tuple, set)):
        return []
    out = []
    seen = set()
    for k in raw:
        key = str(k).strip()
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def load_enabled_alert_rules(rule_keys=None):
    """加载 status=0 的规则；若传入 rule_keys 则再按 key 过滤。"""
    from models import AlertRule

    rules = AlertRule.query.filter_by(status="0").order_by(AlertRule.id.asc()).all()
    if rule_keys is None:
        return rules
    keyset = set(rule_keys)
    if not keyset:
        return []
    return [r for r in rules if r.rule_key in keyset]


def serialize_alert_rules_payload(rules) -> list[dict]:
    return [
        {
            "id": r.id,
            "ruleKey": r.rule_key,
            "name": r.name,
            "ruleType": r.rule_type,
            "severity": r.severity,
            "status": r.status,
            "config": r.config(),
        }
        for r in rules or []
    ]
