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
    # VLM-FO1 官方仓库根目录（也可用环境变量 VLM_FO1_ROOT 覆盖）
    VLM_FO1_ROOT = os.getenv("VLM_FO1_ROOT") or os.path.join(THIRD_PARTY_VENDOR_FOLDER, "VLM-FO1")
    VLM_FO1_PROPOSAL_WEIGHT = os.getenv("VLM_FO1_PROPOSAL_WEIGHT")  # 候选框 YOLO .pt
    VIDEO_FOLDER = os.path.join(UPLOAD_FOLDER, "videos")     # 上传待检测视频
    OUTPUT_FOLDER = os.path.join(UPLOAD_FOLDER, "outputs")   # 带框输出视频
    AUDIO_FOLDER = os.path.join(UPLOAD_FOLDER, "audios")     # 上传待识别音频（语音识别）
    CAMERA_FOLDER = os.path.join(UPLOAD_FOLDER, "cameras")   # 上传的模拟摄像头视频
    DATASET_FOLDER = os.path.join(UPLOAD_FOLDER, "datasets")  # 训练数据集
    TRAINING_FOLDER = os.path.join(UPLOAD_FOLDER, "training")  # 训练产物
    BADMINTON_FOLDER = os.path.join(UPLOAD_FOLDER, "badminton")  # 羽毛球分析产物
    try:
        _max_mb = int(os.getenv("MAX_CONTENT_LENGTH_MB") or "4096")
    except ValueError:
        _max_mb = 4096
    MAX_CONTENT_LENGTH = max(500, _max_mb) * 1024 * 1024  # 默认 4GB（跨镜双视频联调）
    MODEL_ALLOWED_EXT = {".pt", ".pth", ".onnx", ".engine", ".weights"}
    VIDEO_ALLOWED_EXT = {".mp4", ".avi", ".mov", ".mkv", ".flv", ".wmv", ".webm"}
    AUDIO_ALLOWED_EXT = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac"}
    # ASR 页允许音视频：视频经 ffmpeg 抽轨后再转写
    ASR_MEDIA_ALLOWED_EXT = AUDIO_ALLOWED_EXT | VIDEO_ALLOWED_EXT

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
    DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")

    # Qwen-VL（缺陷诊断云端多模态）：OpenAI 兼容接口（默认阿里云百炼 Token Plan 国内）
    QWEN_VL_API_KEY = (
        os.getenv("QWEN_VL_API_KEY")
        or os.getenv("DASHSCOPE_API_KEY")
        or ""
    )
    QWEN_VL_BASE_URL = os.getenv(
        "QWEN_VL_BASE_URL",
        "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
    )
    QWEN_VL_MODEL = os.getenv("QWEN_VL_MODEL", "qwen3.8-max-preview")
    try:
        DEFECT_SUSPICIOUS_CONF = float(os.getenv("DEFECT_SUSPICIOUS_CONF") or "0.45")
    except ValueError:
        DEFECT_SUSPICIOUS_CONF = 0.45

    # MQTT / EMQX（默认关闭；见 docs/emqx-mqtt-usage-scenarios.md）
    MQTT_ENABLED = (os.getenv("MQTT_ENABLED") or "0").strip() in ("1", "true", "True", "yes")
    MQTT_BROKER = os.getenv("MQTT_BROKER", "127.0.0.1")
    MQTT_PORT = int(os.getenv("MQTT_PORT", "1883") or 1883)
    MQTT_USERNAME = os.getenv("MQTT_USERNAME", "")
    MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
    MQTT_TLS = (os.getenv("MQTT_TLS") or "0").strip() in ("1", "true", "True", "yes")
    MQTT_CA_CERTS = os.getenv("MQTT_CA_CERTS", "")
    MQTT_CLIENT_ID_PREFIX = os.getenv("MQTT_CLIENT_ID_PREFIX", "tigerpro-backend")
    MQTT_TOPIC_PREFIX = (os.getenv("MQTT_TOPIC_PREFIX") or "tigerpro/dev").rstrip("/")
    MQTT_SITE = os.getenv("MQTT_SITE", "default")
    # EMQX Cloud Serverless WebSocket over TLS（前端/MQTT.js；后端 Publish 用 8883）
    MQTT_WS_PORT = int(os.getenv("MQTT_WS_PORT", "8084") or 8084)

    # 开放平台 / 对象存储（P1–P3）
    OBJECT_STORE_BACKEND = (os.getenv("OBJECT_STORE_BACKEND") or "local").strip().lower()
    S3_BUCKET = os.getenv("S3_BUCKET", "")
    S3_ENDPOINT = os.getenv("S3_ENDPOINT", "")  # MinIO 等兼容 endpoint
    S3_PREFIX = os.getenv("S3_PREFIX", "tigerpro/")
    OPEN_JOB_RETENTION_DAYS = int(os.getenv("OPEN_JOB_RETENTION_DAYS", "7"))
