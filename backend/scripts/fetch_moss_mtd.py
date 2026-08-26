"""Resume-download MOSS-Transcribe-Diarize shard and bind AiModel.file_path."""
from __future__ import annotations

import os
import sys
import time

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FOLDER = os.path.join(ROOT, "uploads", "models", "moss-transcribe-diarize-0p9b")
DEST = os.path.join(FOLDER, "model-00000-of-00001.safetensors")
PART = DEST + ".part"
URL = (
    "https://hf-mirror.com/OpenMOSS-Team/MOSS-Transcribe-Diarize/"
    "resolve/main/model-00000-of-00001.safetensors"
)
EXPECTED = 1817113576


def _one_pass() -> bool:
    done = os.path.getsize(PART) if os.path.isfile(PART) else 0
    if os.path.isfile(DEST) and os.path.getsize(DEST) >= EXPECTED:
        print(f"already complete {os.path.getsize(DEST)} bytes", flush=True)
        return True
    headers = {"User-Agent": "Mozilla/5.0 tigerpro-moss-fetch"}
    if done:
        headers["Range"] = f"bytes={done}-"
    print(f"resume from {done} bytes", flush=True)
    with requests.get(URL, headers=headers, stream=True, timeout=120, allow_redirects=True) as r:
        r.raise_for_status()
        if r.status_code == 206:
            total = done + int(r.headers.get("Content-Length") or 0)
            mode = "ab"
        else:
            done = 0
            total = int(r.headers.get("Content-Length") or EXPECTED)
            mode = "wb"
        print(f"status={r.status_code} total={total}", flush=True)
        last = time.time()
        last_n = done
        n = done
        with open(PART, mode) as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                f.write(chunk)
                n += len(chunk)
                if n % (16 * 1024 * 1024) < 1024 * 1024:
                    f.flush()
                now = time.time()
                if now - last >= 5:
                    spd = (n - last_n) / (now - last) / 1024 / 1024
                    pct = n / total * 100 if total else 0
                    print(f"{n/1024/1024:.1f}/{total/1024/1024:.1f} MB ({pct:.1f}%) {spd:.2f} MB/s", flush=True)
                    last = now
                    last_n = n
    size = os.path.getsize(PART) if os.path.isfile(PART) else 0
    return size >= EXPECTED * 0.99


def download():
    os.makedirs(FOLDER, exist_ok=True)
    t0 = time.time()
    for attempt in range(1, 31):
        try:
            if _one_pass():
                os.replace(PART, DEST)
                print(f"DONE {os.path.getsize(DEST)/1024/1024:.1f} MB elapsed={time.time()-t0:.1f}s", flush=True)
                return
            print(f"attempt {attempt} incomplete, retrying...", flush=True)
        except (requests.RequestException, OSError) as e:
            print(f"attempt {attempt} failed: {e}", flush=True)
        time.sleep(min(8, attempt))
    raise RuntimeError("download failed after retries")


def dir_size(folder: str) -> int:
    size = 0
    for root, _dirs, files in os.walk(folder):
        for name in files:
            fp = os.path.join(root, name)
            if os.path.isfile(fp) and not name.endswith(".part"):
                size += os.path.getsize(fp)
    return size


def bind_db():
    sys.path.insert(0, ROOT)
    from app import create_app
    from models.ai_model import AiModel
    from extensions import db

    app = create_app()
    with app.app_context():
        m = AiModel.query.filter_by(model_key="moss-transcribe-diarize-0p9b").first()
        if m is None:
            raise RuntimeError("AiModel moss-transcribe-diarize-0p9b not found; restart backend to seed")
        m.file_path = "models/moss-transcribe-diarize-0p9b"
        m.file_size = dir_size(FOLDER)
        db.session.commit()
        print(f"bound id={m.id} file_path={m.file_path} size_mb={m.file_size/1024/1024:.1f}", flush=True)


if __name__ == "__main__":
    download()
    bind_db()
