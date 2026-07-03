"""RBAC 数据模型（参照 RuoYi）。

表：
  sys_user  用户   sys_role 角色   sys_dept 部门(树)  sys_job 岗位  sys_menu 菜单/权限
多对多中间表：
  sys_user_role  用户-角色
  sys_user_dept  用户-部门
  sys_user_post  用户-岗位
  sys_role_menu  角色-权限
  sys_user_menu  用户-权限(直接授权)
"""
from datetime import datetime

from werkzeug.security import generate_password_hash, check_password_hash

from extensions import db

# ---------------------------------------------------------------- 关联表（多对多）
user_role = db.Table(
    "sys_user_role",
    db.Column("user_id", db.Integer, db.ForeignKey("sys_user.id", ondelete="CASCADE"), primary_key=True),
    db.Column("role_id", db.Integer, db.ForeignKey("sys_role.id", ondelete="CASCADE"), primary_key=True),
)

user_dept = db.Table(
    "sys_user_dept",
    db.Column("user_id", db.Integer, db.ForeignKey("sys_user.id", ondelete="CASCADE"), primary_key=True),
    db.Column("dept_id", db.Integer, db.ForeignKey("sys_dept.id", ondelete="CASCADE"), primary_key=True),
)

user_post = db.Table(
    "sys_user_post",
    db.Column("user_id", db.Integer, db.ForeignKey("sys_user.id", ondelete="CASCADE"), primary_key=True),
    db.Column("post_id", db.Integer, db.ForeignKey("sys_job.id", ondelete="CASCADE"), primary_key=True),
)

role_menu = db.Table(
    "sys_role_menu",
    db.Column("role_id", db.Integer, db.ForeignKey("sys_role.id", ondelete="CASCADE"), primary_key=True),
    db.Column("menu_id", db.Integer, db.ForeignKey("sys_menu.id", ondelete="CASCADE"), primary_key=True),
)

user_menu = db.Table(
    "sys_user_menu",
    db.Column("user_id", db.Integer, db.ForeignKey("sys_user.id", ondelete="CASCADE"), primary_key=True),
    db.Column("menu_id", db.Integer, db.ForeignKey("sys_menu.id", ondelete="CASCADE"), primary_key=True),
)


# ---------------------------------------------------------------- 部门（无限级树）
class Dept(db.Model):
    __tablename__ = "sys_dept"

    id = db.Column(db.Integer, primary_key=True)
    parent_id = db.Column(db.Integer, default=0, index=True)       # 0 = 根
    ancestors = db.Column(db.String(500), default="")             # 祖级列表 "0,1,2"
    dept_name = db.Column(db.String(64), nullable=False)
    order_num = db.Column(db.Integer, default=0)
    leader = db.Column(db.String(32))
    phone = db.Column(db.String(20))
    email = db.Column(db.String(64))
    status = db.Column(db.String(1), default="0")                 # 0正常 1停用
    del_flag = db.Column(db.String(1), default="0")               # 0存在 2删除
    create_time = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "parentId": self.parent_id,
            "ancestors": self.ancestors,
            "deptName": self.dept_name,
            "orderNum": self.order_num,
            "leader": self.leader,
            "phone": self.phone,
            "email": self.email,
            "status": self.status,
            "createTime": self.create_time.isoformat() if self.create_time else None,
        }


# ---------------------------------------------------------------- 岗位
class Job(db.Model):
    __tablename__ = "sys_job"

    id = db.Column(db.Integer, primary_key=True)
    post_code = db.Column(db.String(64), nullable=False)
    post_name = db.Column(db.String(64), nullable=False)
    post_sort = db.Column(db.Integer, default=0)
    status = db.Column(db.String(1), default="0")
    create_time = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "postCode": self.post_code,
            "postName": self.post_name,
            "postSort": self.post_sort,
            "status": self.status,
        }


# ---------------------------------------------------------------- 菜单 / 权限
class Menu(db.Model):
    __tablename__ = "sys_menu"

    id = db.Column(db.Integer, primary_key=True)
    parent_id = db.Column(db.Integer, default=0, index=True)
    menu_name = db.Column(db.String(64), nullable=False)
    # M 目录  C 菜单  F 按钮  A 接口(API)
    menu_type = db.Column(db.String(1), nullable=False, default="C")
    perms = db.Column(db.String(100))                            # 权限标识 system:user:list
    path = db.Column(db.String(200))                            # 路由地址
    component = db.Column(db.String(255))                       # 组件路径
    icon = db.Column(db.String(100))
    order_num = db.Column(db.Integer, default=0)
    visible = db.Column(db.String(1), default="0")             # 0显示 1隐藏
    status = db.Column(db.String(1), default="0")
    create_time = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "parentId": self.parent_id,
            "menuName": self.menu_name,
            "menuType": self.menu_type,
            "perms": self.perms,
            "path": self.path,
            "component": self.component,
            "icon": self.icon,
            "orderNum": self.order_num,
            "visible": self.visible,
            "status": self.status,
        }


# ---------------------------------------------------------------- 角色
class Role(db.Model):
    __tablename__ = "sys_role"

    id = db.Column(db.Integer, primary_key=True)
    role_name = db.Column(db.String(64), nullable=False)
    role_key = db.Column(db.String(64), unique=True, nullable=False)
    role_sort = db.Column(db.Integer, default=0)
    # 数据范围 1仅本人 2本部门 3本部门及下级 4全部
    data_scope = db.Column(db.Integer, default=1)
    status = db.Column(db.String(1), default="0")
    del_flag = db.Column(db.String(1), default="0")
    remark = db.Column(db.String(255))
    create_time = db.Column(db.DateTime, default=datetime.utcnow)

    menus = db.relationship("Menu", secondary=role_menu, lazy="selectin")

    def to_dict(self, with_menus=False):
        d = {
            "id": self.id,
            "roleName": self.role_name,
            "roleKey": self.role_key,
            "roleSort": self.role_sort,
            "dataScope": self.data_scope,
            "status": self.status,
            "remark": self.remark,
        }
        if with_menus:
            d["menuIds"] = [m.id for m in self.menus]
        return d


# ---------------------------------------------------------------- 用户
class User(db.Model):
    __tablename__ = "sys_user"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    nickname = db.Column(db.String(64))
    # 主部门（数据权限"本部门"以此为准）
    dept_id = db.Column(db.Integer, db.ForeignKey("sys_dept.id"), index=True)
    email = db.Column(db.String(64))
    phone = db.Column(db.String(20))
    sex = db.Column(db.String(1), default="0")                  # 0男 1女 2未知
    avatar = db.Column(db.String(255))
    status = db.Column(db.String(1), default="0")
    del_flag = db.Column(db.String(1), default="0")
    create_time = db.Column(db.DateTime, default=datetime.utcnow)

    dept = db.relationship("Dept", foreign_keys=[dept_id], lazy="joined")
    roles = db.relationship("Role", secondary=user_role, lazy="selectin", backref="users")
    depts = db.relationship("Dept", secondary=user_dept, lazy="selectin")
    posts = db.relationship("Job", secondary=user_post, lazy="selectin")
    menus = db.relationship("Menu", secondary=user_menu, lazy="selectin")  # 直接授权

    # ---- 密码
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    # ---- 权限聚合
    @property
    def is_admin(self):
        return any(r.role_key == "admin" for r in self.roles)

    def role_keys(self):
        return [r.role_key for r in self.roles]

    def all_menus(self):
        """角色菜单 ∪ 直接授权菜单，去重。"""
        seen = {}
        for r in self.roles:
            for m in r.menus:
                seen[m.id] = m
        for m in self.menus:
            seen[m.id] = m
        return list(seen.values())

    def perms(self):
        """权限标识集合。admin 拥有通配 *:*:*。"""
        if self.is_admin:
            return {"*:*:*"}
        return {m.perms for m in self.all_menus() if m.perms}

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "nickname": self.nickname,
            "deptId": self.dept_id,
            "deptName": self.dept.dept_name if self.dept else None,
            "email": self.email,
            "phone": self.phone,
            "sex": self.sex,
            "avatar": self.avatar,
            "status": self.status,
            "roleIds": [r.id for r in self.roles],
            "postIds": [p.id for p in self.posts],
            "createTime": self.create_time.isoformat() if self.create_time else None,
        }


from .ai_model import AiModel  # noqa: E402  AI 检测模型
from .camera import Camera  # noqa: E402  摄像头
from .training import TrainingDataset, TrainingJob  # noqa: E402  模型训练

__all__ = [
    "db",
    "User", "Role", "Dept", "Job", "Menu", "AiModel", "Camera",
    "TrainingDataset", "TrainingJob",
    "user_role", "user_dept", "user_post", "role_menu", "user_menu",
]
