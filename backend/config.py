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
    ALERT_RULES_DIR = os.path.join(BASE_DIR, "alert_rules")
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
    MODEL_FOLDER = os.path.join(UPLOAD_FOLDER, "models")
    THIRD_PARTY_VENDOR_FOLDER = os.path.join(MODEL_FOLDER, "third_party")  # vendored 推理代码（VibeVoice 等）
    VIDEO_FOLDER = os.path.join(UPLOAD_FOLDER, "videos")     # 上传待检测视频
    OUTPUT_FOLDER = os.path.join(UPLOAD_FOLDER, "outputs")   # 带框输出视频
    AUDIO_FOLDER = os.path.join(UPLOAD_FOLDER, "audios")     # 上传待识别音频（语音识别）
    CAMERA_FOLDER = os.path.join(UPLOAD_FOLDER, "cameras")   # 上传的模拟摄像头视频
    DATASET_FOLDER = os.path.join(UPLOAD_FOLDER, "datasets")  # 训练数据集
    TRAINING_FOLDER = os.path.join(UPLOAD_FOLDER, "training")  # 训练产物
    BADMINTON_FOLDER = os.path.join(UPLOAD_FOLDER, "badminton")  # 羽毛球分析产物
    MAX_CONTENT_LENGTH = 500 * 1024 * 1024  # 单文件上限 500MB（权重/视频文件较大）
    MODEL_ALLOWED_EXT = {".pt", ".pth", ".onnx", ".engine", ".weights"}
    VIDEO_ALLOWED_EXT = {".mp4", ".avi", ".mov", ".mkv", ".flv", ".wmv", ".webm"}
    AUDIO_ALLOWED_EXT = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac"}

    # HuggingFace 访问令牌（拉取私有/受限 gated 模型权重时认证用）
    HF_TOKEN = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN")
    # ModelScope（模搭社区）访问令牌（拉取受限模型权重时用）
    MODELSCOPE_TOKEN = os.getenv("MODELSCOPE_TOKEN") or os.getenv("MODELSCOPE_API_TOKEN")
    # Roboflow API Key（拉取 Universe 公开模型权重 / 标注工具）
    ROBOFLOW_API_KEY = os.getenv("ROBOFLOW_API_KEY")
    ROBOFLOW_PUBLIC_API_KEY = os.getenv("ROBOFLOW_PUBLIC_API_KEY")
    ROBOFLOW_WORKSPACE = os.getenv("ROBOFLOW_WORKSPACE")
    # CVAT 自托管 / 云端标注
    CVAT_URL = os.getenv("CVAT_URL")
    CVAT_TOKEN = os.getenv("CVAT_TOKEN")
    CVAT_USERNAME = os.getenv("CVAT_USERNAME")
    CVAT_PASSWORD = os.getenv("CVAT_PASSWORD")
    XANYLABELING_CMD = os.getenv("XANYLABELING_CMD")

    # Ultralytics YOLO CPU 推理后端：auto|torch|openvino（热路径：跟踪/车辆/告警视频）
    YOLO_INFER_BACKEND = (os.getenv("YOLO_INFER_BACKEND") or "auto").strip().lower()
    YOLO_OPENVINO_PRECISION = (os.getenv("YOLO_OPENVINO_PRECISION") or "fp16").strip().lower()
    try:
        YOLO_OPENVINO_IMGSZ = int(os.getenv("YOLO_OPENVINO_IMGSZ") or "640")
    except ValueError:
        YOLO_OPENVINO_IMGSZ = 640

    # DeepSeek（检测结果 AI 分析报告）：OpenAI 兼容接口
    DEEPSEEK_API_KEY = os.getenv(
        "DEEPSEEK_API_KEY", ""
    )
    DEEPSEEK_BASE_URL = os.getenv(
        "DEEPSEEK_BASE_URL", "https://api.deepseek.com"
    )
    DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
