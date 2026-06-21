import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")

    # JWT
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", SECRET_KEY)
    JWT_ACCESS_TOKEN_EXPIRES = int(os.getenv("JWT_EXPIRES_SECONDS", "86400"))

    DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
    DB_PORT = os.getenv("DB_PORT", "3306")
    DB_USER = os.getenv("DB_USER", "root")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "")
    DB_NAME = os.getenv("DB_NAME", "cv_python_tigerpro")

    SQLALCHEMY_DATABASE_URI = (
        f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}"
        f"@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JSON_AS_ASCII = False

    # 文件上传：模型权重等
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
    MODEL_FOLDER = os.path.join(UPLOAD_FOLDER, "models")
    VIDEO_FOLDER = os.path.join(UPLOAD_FOLDER, "videos")     # 上传待检测视频
    OUTPUT_FOLDER = os.path.join(UPLOAD_FOLDER, "outputs")   # 带框输出视频
    AUDIO_FOLDER = os.path.join(UPLOAD_FOLDER, "audios")     # 上传待识别音频（语音识别）
    MAX_CONTENT_LENGTH = 500 * 1024 * 1024  # 单文件上限 500MB（权重/视频文件较大）
    MODEL_ALLOWED_EXT = {".pt", ".pth", ".onnx", ".engine", ".weights"}
    VIDEO_ALLOWED_EXT = {".mp4", ".avi", ".mov", ".mkv", ".flv", ".wmv", ".webm"}
    AUDIO_ALLOWED_EXT = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac"}

    # HuggingFace 访问令牌（拉取私有/受限 gated 模型权重时认证用）
    HF_TOKEN = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN")
    # ModelScope（模搭社区）访问令牌（拉取受限模型权重时用）
    MODELSCOPE_TOKEN = os.getenv("MODELSCOPE_TOKEN") or os.getenv("MODELSCOPE_API_TOKEN")
