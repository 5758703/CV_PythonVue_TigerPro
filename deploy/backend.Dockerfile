# Flask backend (app.py :5001 and gateway_app.py :5002).
# Python 3.12 is required by the CV dependencies (see backend/README.md).
# Keep this experimental: the CV model weights are large and are pulled at
# first run, so the first start of the backend container is slow.
FROM python:3.12-slim

WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
ENV PYTHONUNBUFFERED=1

# Secrets (SECRET_KEY, DB_PASSWORD, HF_TOKEN, ...) come from deploy/.env at
# runtime. Nothing sensitive is baked into the image.
CMD ["python", "app.py"]
