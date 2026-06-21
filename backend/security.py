"""认证 / 鉴权工具：JWT 守卫、功能权限校验装饰器、数据权限范围。"""
from functools import wraps

from flask import g, jsonify
from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity

from models import User, Dept


def current_user():
    """取当前登录用户（每请求缓存到 g）。"""
    if "current_user" not in g:
        uid = get_jwt_identity()
        g.current_user = User.query.get(int(uid)) if uid is not None else None
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
    if user.is_admin:
        return True
    return _match(perm, user.perms())


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


def data_scope_dept_ids(user):
    """按角色 data_scope 返回允许的部门 id 列表。

    返回 None  -> 全部（不过滤）
    返回 []    -> 仅本人（调用方改用 user_id 过滤）
    返回 [ids] -> 限定这些部门
    取用户多个角色里最宽松(数值最大)的范围。
      1 仅本人  2 本部门  3 本部门及下级  4 全部
    """
    if user is None:
        return []
    if user.is_admin:
        return None
    scope = max([r.data_scope or 1 for r in user.roles], default=1)
    if scope >= 4:
        return None
    if scope == 3:
        return _descendant_dept_ids(user.dept_id)
    if scope == 2:
        return [user.dept_id] if user.dept_id is not None else []
    return []  # 1 仅本人


def apply_user_data_scope(query, user):
    """对 User 查询套用数据权限过滤。"""
    if user is None:
        return query.filter(False)
    dept_ids = data_scope_dept_ids(user)
    if dept_ids is None:
        return query
    if not dept_ids:
        return query.filter(User.id == user.id)
    return query.filter(User.dept_id.in_(dept_ids))
