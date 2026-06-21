from .auth import auth_bp
from .user import user_bp
from .role import role_bp
from .dept import dept_bp
from .job import job_bp
from .menu import menu_bp
from .ai_model import ai_model_bp

all_blueprints = [auth_bp, user_bp, role_bp, dept_bp, job_bp, menu_bp, ai_model_bp]

__all__ = ["all_blueprints", "auth_bp", "user_bp", "role_bp", "dept_bp", "job_bp", "menu_bp", "ai_model_bp"]
