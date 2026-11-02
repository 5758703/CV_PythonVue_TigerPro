# Tiger AI 后端（实验性 Docker 镜像）
# 体积大：含 torch / ultralytics 等；首次 build 可能需 20–60+ 分钟。
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential pkg-config \
      libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 \
      ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

# CPU 版 PyTorch（与 requirements 对齐；若 requirements 已钉版本可按需调整）
COPY requirements.txt .
RUN pip install --upgrade pip \
 && pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu \
 && pip install -r requirements.txt \
 && pip install gunicorn

COPY . .

RUN mkdir -p uploads/models uploads/videos uploads/outputs uploads/audios \
             uploads/cameras uploads/datasets uploads/training uploads/badminton

EXPOSE 5001

# 单 worker：进程内任务表 / 模型缓存不跨进程共享
CMD ["gunicorn", "-w", "1", "-k", "gthread", "--threads", "4", "-t", "0", \
     "-b", "0.0.0.0:5001", "app:app"]
