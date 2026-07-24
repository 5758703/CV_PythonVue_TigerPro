"""开放平台全量 API 目录：按 Blueprint / 域 分组，并映射 Scope。

目录来源：扫描 backend/routes/*.py 的路由装饰器 + 邻近 permission_required / login_required。
对外访问路径：/openapi/v1/x/<原 /api/ 之后的路径>  （桥接）
"""
from __future__ import annotations

import ast
import re
from functools import lru_cache
from pathlib import Path

# 域定义：与 Blueprint 一一对应（便于按蓝图分类建应用）
# group: 前端分组
DOMAIN_META = {
    "health": {"label": "健康检查", "order": 0, "risk": "low", "group": "core", "groupLabel": "基础", "blueprint": "app"},
    "auth": {"label": "认证 Auth", "order": 1, "risk": "medium", "group": "core", "groupLabel": "基础", "blueprint": "auth"},
    "sys_user": {"label": "系统·用户", "order": 10, "risk": "high", "group": "system", "groupLabel": "系统管理", "blueprint": "sys_user"},
    "sys_role": {"label": "系统·角色", "order": 11, "risk": "high", "group": "system", "groupLabel": "系统管理", "blueprint": "sys_role"},
    "sys_dept": {"label": "系统·部门", "order": 12, "risk": "high", "group": "system", "groupLabel": "系统管理", "blueprint": "sys_dept"},
    "sys_job": {"label": "系统·岗位", "order": 13, "risk": "high", "group": "system", "groupLabel": "系统管理", "blueprint": "sys_job"},
    "sys_menu": {"label": "系统·菜单", "order": 14, "risk": "high", "group": "system", "groupLabel": "系统管理", "blueprint": "sys_menu"},
    "camera": {"label": "摄像头 / 监控", "order": 20, "risk": "high", "group": "media", "groupLabel": "视频监控", "blueprint": "camera"},
    "ai_model": {"label": "AI 模型与推理", "order": 30, "risk": "medium", "group": "ai", "groupLabel": "AI 能力", "blueprint": "ai_model"},
    "training": {"label": "训练 / 标注", "order": 31, "risk": "high", "group": "ai", "groupLabel": "AI 能力", "blueprint": "training"},
    "face": {"label": "人脸识别", "order": 32, "risk": "high", "group": "ai", "groupLabel": "AI 能力", "blueprint": "face"},
    "vehicle": {"label": "车辆追踪", "order": 33, "risk": "medium", "group": "ai", "groupLabel": "AI 能力", "blueprint": "vehicle"},
    "water": {"label": "水位检测", "order": 34, "risk": "low", "group": "ai", "groupLabel": "AI 能力", "blueprint": "water_level"},
    "table": {"label": "表格识别", "order": 35, "risk": "low", "group": "ai", "groupLabel": "AI 能力", "blueprint": "table_recog"},
    "badminton": {"label": "羽毛球分析", "order": 36, "risk": "low", "group": "ai", "groupLabel": "AI 能力", "blueprint": "badminton"},
    "alert": {"label": "检测告警", "order": 37, "risk": "medium", "group": "ai", "groupLabel": "AI 能力", "blueprint": "alert"},
    "open_app": {"label": "开放平台管理", "order": 90, "risk": "critical", "group": "platform", "groupLabel": "开放平台", "blueprint": "sys_open_app"},
    "openapi": {"label": "Open API 元接口", "order": 91, "risk": "low", "group": "platform", "groupLabel": "开放平台", "blueprint": "openapi_v1"},
    "other": {"label": "其他", "order": 99, "risk": "medium", "group": "other", "groupLabel": "其他", "blueprint": ""},
}

# 长前缀优先
PREFIX_DOMAIN = [
    ("/api/system/open-app", "open_app"),
    ("/api/system/user", "sys_user"),
    ("/api/system/role", "sys_role"),
    ("/api/system/dept", "sys_dept"),
    ("/api/system/job", "sys_job"),
    ("/api/system/menu", "sys_menu"),
    ("/api/auth", "auth"),
    ("/api/camera", "camera"),
    ("/api/ai/model", "ai_model"),
    ("/api/ai/training", "training"),
    ("/api/ai/face", "face"),
    ("/api/ai/vehicle", "vehicle"),
    ("/api/ai/water-level", "water"),
    ("/api/ai/table", "table"),
    ("/api/ai/badminton", "badminton"),
    ("/api/alerts", "alert"),
    ("/openapi/v1", "openapi"),
    ("/api/health", "health"),
]

# 兼容旧版精简 Scope 别名 → 实际 bridge scope（permission）
LEGACY_SCOPE_ALIASES = {
    "vision:detect": "ai:model:query",
    "vision:ocr": "ai:model:query",
    "face:recognize": "ai:face:list",
    "water:read": "ai:water:list",
    "jobs:read": "ai:model:query",
}

# 禁止桥接（仅控制台）：避免递归 / 密钥管理面外泄
NON_BRIDGEABLE_PREFIXES = (
    "/api/system/open-app",
    "/openapi/v1",
)

_BP_PREFIX_RE = re.compile(
    r'^(\w+)_bp\s*=\s*Blueprint\([^)]*url_prefix\s*=\s*["\']([^"\']+)["\']',
    re.M,
)
_ROUTE_RE = re.compile(
    r'^@(\w+)_bp\.(get|post|put|patch|delete)\(\s*["\']([^"\']*)["\']',
    re.M,
)


def _domain_for_path(path: str) -> str:
    for prefix, domain in PREFIX_DOMAIN:
        if path == prefix or path.startswith(prefix + "/") or (
            prefix.endswith(path) if False else False
        ):
            if path.startswith(prefix):
                return domain
    for prefix, domain in PREFIX_DOMAIN:
        if path.startswith(prefix):
            return domain
    return "other"


def _normalize_rule(prefix: str, suffix: str) -> str:
    prefix = (prefix or "").rstrip("/")
    suffix = suffix or ""
    if not suffix.startswith("/"):
        suffix = "/" + suffix if suffix else ""
    if suffix == "/":
        path = prefix or "/"
    else:
        path = prefix + suffix
    # Flask <int:id> → :id 风格便于展示；桥接仍用真实路径匹配
    return path


def _bridgeable(path: str) -> bool:
    for p in NON_BRIDGEABLE_PREFIXES:
        if path == p or path.startswith(p + "/"):
            return False
    return path.startswith("/api/")


def _scan_route_file(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    bp_prefixes = {m.group(1): m.group(2) for m in _BP_PREFIX_RE.finditer(text)}
    lines = text.splitlines()
    entries = []

    for i, line in enumerate(lines):
        m = _ROUTE_RE.match(line.strip()) if line.strip().startswith("@") else None
        if not m:
            # also allow indented? usually top-level
            m = _ROUTE_RE.match(line)
        if not m:
            continue
        bp_name, method, suffix = m.group(1), m.group(2).upper(), m.group(3)
        prefix = bp_prefixes.get(bp_name)
        if prefix is None:
            continue
        api_path = _normalize_rule(prefix, suffix)

        # 向后看最多 6 行找权限装饰器 / 函数名
        scope = None
        auth = "none"
        summary = ""
        for j in range(i + 1, min(i + 8, len(lines))):
            s = lines[j].strip()
            pm = re.match(r'@permission_required\(\s*["\']([^"\']+)["\']\s*\)', s)
            if pm:
                scope = pm.group(1)
                auth = "perm"
                continue
            if s.startswith("@login_required"):
                scope = scope or "auth:login"
                auth = "login"
                continue
            if s.startswith("def "):
                fn = s[4:].split("(")[0].strip()
                summary = fn
                # docstring next?
                if j + 1 < len(lines) and '"""' in lines[j + 1]:
                    doc = lines[j + 1].strip().strip('"').strip()
                    if doc:
                        summary = doc[:80]
                break

        if scope is None:
            # 特殊：摄像头 stream 等手写 JWT
            if "/stream" in api_path:
                scope = "camera:query"
                auth = "special"
            elif api_path in ("/api/auth/login", "/api/auth/register", "/api/auth/logout"):
                scope = "auth:public"
                auth = "public"
            else:
                scope = f"open:{_domain_for_path(api_path)}:access"
                auth = "open"

        domain = _domain_for_path(api_path)
        entries.append({
            "method": method,
            "path": api_path,
            "openPath": "/openapi/v1/x" + api_path[len("/api"):] if api_path.startswith("/api") else None,
            "domain": domain,
            "blueprint": bp_name,
            "scope": scope,
            "auth": auth,
            "summary": summary or api_path,
            "bridgeable": _bridgeable(api_path),
        })
    return entries


def _manual_extras() -> list[dict]:
    """app.py 等非 Blueprint 路由。"""
    return [{
        "method": "GET",
        "path": "/api/health",
        "openPath": "/openapi/v1/x/health",
        "domain": "health",
        "blueprint": "app",
        "scope": "auth:public",
        "auth": "public",
        "summary": "服务健康检查",
        "bridgeable": True,
    }]


@lru_cache(maxsize=1)
def build_catalog() -> tuple[dict, ...]:
    routes_dir = Path(__file__).resolve().parent.parent / "routes"
    entries: list[dict] = []
    for f in sorted(routes_dir.glob("*.py")):
        if f.name.startswith("_") or f.name == "__init__.py":
            continue
        # openapi_v1 / open_app_admin 也进目录，但多数不可桥接
        entries.extend(_scan_route_file(f))
    entries.extend(_manual_extras())
    # 去重 method+path
    seen = set()
    uniq = []
    for e in entries:
        key = (e["method"], e["path"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(e)
    return tuple(uniq)


def invalidate_catalog_cache():
    build_catalog.cache_clear()


def list_domains() -> list[dict]:
    catalog = build_catalog()
    by = {}
    for e in catalog:
        by.setdefault(e["domain"], []).append(e)
    # 确保元数据中声明的域都出现（即使暂无路由）
    for domain_id in DOMAIN_META:
        by.setdefault(domain_id, [])
    domains = []
    for domain_id, items in by.items():
        if domain_id == "other" and not items:
            continue
        meta = DOMAIN_META.get(domain_id, DOMAIN_META["other"])
        bridgeable_n = sum(1 for x in items if x["bridgeable"])
        scopes = sorted({x["scope"] for x in items if x.get("scope")})
        # 域全量覆盖 = 域 Scope + 该域全部细粒度 Scope
        full_scopes = sorted({f"domain:{domain_id}", *scopes})
        domains.append({
            "id": domain_id,
            "label": meta["label"],
            "order": meta["order"],
            "risk": meta["risk"],
            "group": meta.get("group") or "other",
            "groupLabel": meta.get("groupLabel") or "其他",
            "blueprint": meta.get("blueprint") or "",
            "domainScope": f"domain:{domain_id}",
            "fullScopes": full_scopes,
            "endpointCount": len(items),
            "bridgeableCount": bridgeable_n,
            "scopes": scopes,
            "endpoints": sorted(items, key=lambda x: (x["path"], x["method"])),
            "suggestedAppId": f"app_{domain_id}",
            "suggestedName": f"{meta['label']}开放应用",
        })
    domains.sort(key=lambda d: d["order"])
    return domains


def list_domain_groups() -> list[dict]:
    """按 group 聚合域，供前端分类新建。"""
    domains = list_domains()
    groups: dict[str, dict] = {}
    for d in domains:
        gid = d["group"]
        if gid not in groups:
            groups[gid] = {
                "id": gid,
                "label": d["groupLabel"],
                "domains": [],
                "endpointCount": 0,
                "bridgeableCount": 0,
            }
        groups[gid]["domains"].append(d)
        groups[gid]["endpointCount"] += d["endpointCount"]
        groups[gid]["bridgeableCount"] += d["bridgeableCount"]
    # 稳定顺序
    order = ["core", "system", "media", "ai", "platform", "other"]
    out = []
    for gid in order:
        if gid in groups:
            out.append(groups.pop(gid))
    out.extend(groups.values())
    return out


def scopes_for_domain(domain_id: str, *, include_fine: bool = True) -> list[str]:
    """某域「全覆盖」Scope 列表。"""
    for d in list_domains():
        if d["id"] == domain_id:
            if include_fine:
                return list(d["fullScopes"])
            return [d["domainScope"]]
    return [f"domain:{domain_id}"]


def scopes_for_all_bridgeable_domains() -> list[str]:
    scopes = []
    for d in list_domains():
        if d["id"] in ("open_app", "openapi"):
            continue
        scopes.extend(d["fullScopes"])
    scopes += [
        "vision:detect", "vision:ocr", "face:recognize", "water:read", "jobs:read",
    ]
    return sorted(set(scopes))


def all_scopes() -> list[str]:
    """管理端可选 Scope：域级 + 细粒度 + 旧别名 + 超管通配。"""
    scopes = {"*:*:*", "*"}
    for d in list_domains():
        scopes.add(d["domainScope"])
        for s in d["scopes"]:
            scopes.add(s)
            # 资源级通配 ai:face:*
            parts = s.split(":")
            if len(parts) >= 2:
                scopes.add(f"{parts[0]}:{parts[1]}:*")
            if len(parts) >= 1:
                scopes.add(f"{parts[0]}:*")
    for legacy in LEGACY_SCOPE_ALIASES:
        scopes.add(legacy)
    # 稳定排序：通配靠前，其余字典序
    def sort_key(s):
        if s in ("*", "*:*:*"):
            return (0, s)
        if s.startswith("domain:"):
            return (1, s)
        if s.endswith(":*"):
            return (2, s)
        return (3, s)
    return sorted(scopes, key=sort_key)


def resolve_api_endpoint(method: str, api_path: str) -> dict | None:
    method = method.upper()
    # 规范化：去掉末尾 /
    candidates = [api_path, api_path.rstrip("/") or "/"]
    for e in build_catalog():
        if e["method"] != method:
            continue
        # 将目录中的 <int:cid> 等转为正则匹配实际路径
        if _path_match(e["path"], api_path):
            return e
    return None


def _path_match(pattern: str, actual: str) -> bool:
    if pattern == actual:
        return True
    # <int:name> / <path:name> / <job_id>
    rx = re.sub(r"<int:[^>]+>", r"[0-9]+", pattern)
    rx = re.sub(r"<path:[^>]+>", r".+", rx)
    rx = re.sub(r"<[^>]+:[^>]+>", r"[^/]+", rx)
    rx = re.sub(r"<[^>]+>", r"[^/]+", rx)
    rx = "^" + rx + "$"
    return re.match(rx, actual) is not None


def expand_owned_scopes(owned: list[str]) -> set[str]:
    """把旧别名展开为实际 permission scope。"""
    out = set(owned or [])
    for a, target in LEGACY_SCOPE_ALIASES.items():
        if a in out:
            out.add(target)
    return out


def app_allows_endpoint(owned_scopes: list[str], endpoint: dict) -> bool:
    owned = expand_owned_scopes(owned_scopes)
    if "*" in owned or "*:*:*" in owned:
        return True
    domain = endpoint.get("domain")
    if domain and f"domain:{domain}" in owned:
        return True
    scope = endpoint.get("scope") or ""
    if not scope or scope == "auth:public":
        # public 接口仍需有效 AppKey（由上层鉴权），scope 放行
        return True
    # 精确 / 段通配
    if scope in owned:
        return True
    parts = scope.split(":")
    if len(parts) >= 2 and f"{parts[0]}:{parts[1]}:*" in owned:
        return True
    if len(parts) >= 1 and f"{parts[0]}:*" in owned:
        return True
    # 逐段 * 匹配（复用 security_open 语义）
    from security_open import _match_scope
    return _match_scope(scope, list(owned))


def catalog_stats() -> dict:
    cats = build_catalog()
    return {
        "endpointCount": len(cats),
        "bridgeableCount": sum(1 for e in cats if e["bridgeable"]),
        "domainCount": len({e["domain"] for e in cats}),
        "scopeCount": len(all_scopes()),
    }
