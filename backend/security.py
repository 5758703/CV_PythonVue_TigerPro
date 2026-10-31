"""认证 / 鉴权工具：JWT 守卫、功能权限校验装饰器、数据权限范围。"""
from functools import wraps

from flask import g, jsonify
from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity

from models import User, Dept


def current_user():
    """取当前登录用户（每请求缓存到 g）。"""
    if "current_user" not in g:
        uid = get_jwt_identity()
        user = User.query.get(int(uid)) if uid is not None else None
        g.current_user = user if user and user.status == "0" and user.del_flag == "0" else None
    return g.current_user


def _match(perm, owned):
    """权限通配匹配：'*:*:*' 命中一切；逐段匹配，* 为通配。"""
    if "*:*:*" in owned or perm in owned:
        return True
    pp = perm.split(":")
    for o in owned:
        op = o.split(":")
        if len(op) != len(pp):
            continue
        if all(a == "*" or a == b for a, b in zip(op, pp)):
            return True
    return False


def has_perm(user, perm):
    if user is None:
        return False
    from services.organization_auth import effective_permissions
    return _match(perm, effective_permissions(user))


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        verify_jwt_in_request()
        if current_user() is None:
            return jsonify(code=401, message="用户不存在或已禁用"), 401
        return fn(*args, **kwargs)
    return wrapper


def permission_required(perm):
    """功能权限（菜单/按钮/API）校验装饰器。"""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            verify_jwt_in_request()
            user = current_user()
            if user is None:
                return jsonify(code=401, message="未登录"), 401
            if not has_perm(user, perm):
                return jsonify(code=403, message="没有访问权限"), 403
            g.required_perm = perm
            return fn(*args, **kwargs)
        return wrapper
    return decorator


# ------------------------------------------------------------ 数据权限
def _descendant_dept_ids(dept_id):
    """部门及其所有下级 id（基于 ancestors 字段）。"""
    if dept_id is None:
        return []
    ids = {dept_id}
    for d in Dept.query.filter(Dept.del_flag == "0").all():
        anc = (d.ancestors or "").split(",")
        if str(dept_id) in anc:
            ids.add(d.id)
    return list(ids)


def data_scope_dept_ids(user, perm=None):
    """本次操作的组织范围；None 仅用于平台配置管理员。

    空集合表示没有组织级范围，不可解释为本人或全部。
    本人条件由 apply_user_data_scope 按完整授权单独构造。
    """
    from services.organization_auth import operation_org_ids
    return operation_org_ids(user, perm or g.get("required_perm")) if user else set()


def apply_user_data_scope(query, user, perm=None):
    """对 User 查询套用数据权限过滤。"""
    from services.organization_auth import scope_user_query
    return scope_user_query(query, user, perm or g.get("required_perm"))


def platform_admin_required(fn):
    """Configuration and delegation are separate from scoped resource access."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user() or not current_user().is_admin:
            return jsonify(code=403, message="此授权配置或账号安全操作仅限平台管理员"), 403
        return fn(*args, **kwargs)
    return wrapper
