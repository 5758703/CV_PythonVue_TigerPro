# Tiger AI 后端（CPU）
# 目标机内存较小时：构建前请加大 swap；本 Dockerfile 使用 --no-cache-dir 与串行 pip。
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=180 \
    # 降低并行编译/解压峰值内存
    MAX_JOBS=1 \
    NINJA_NUM_JOBS=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential pkg-config git \
      libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 \
      ffmpeg curl \
      espeak-ng \
    && rm -rf /var/lib/apt/lists/*

# requirements.docker.txt：去掉与 torch/neutts 冲突的 funasr_onnx，以及 pytest / 已预装的 torch 全家桶
COPY requirements.docker.txt .

# 先装 CPU 版 torch 全家桶，再装其余依赖（避免误拉 CUDA 轮子）
RUN pip install --upgrade pip setuptools wheel \
 && pip install --no-cache-dir \
      torch==2.11.0 torchvision==0.26.0 torchaudio==2.11.0 \
      --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir -r requirements.docker.txt \
 && pip install --no-cache-dir gunicorn \
 && rm -rf /root/.cache/pip

COPY . .

RUN mkdir -p uploads/models uploads/videos uploads/outputs uploads/audios \
             uploads/cameras uploads/datasets uploads/training uploads/badminton

EXPOSE 5001

# 单 worker：进程内任务表 / 模型缓存不跨进程共享；threads 控制并发
CMD ["gunicorn", "-w", "1", "-k", "gthread", "--threads", "2", "-t", "0", \
     "--worker-tmp-dir", "/dev/shm", \
     "-b", "0.0.0.0:5001", "app:app"]
