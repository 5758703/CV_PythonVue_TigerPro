"""Sparse-fetch damo-radar inference sources without the huge demo zipball."""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "uploads" / "models" / "third_party" / "damo-radar"
API = "https://api.github.com/repos/jhuanglabAI/damo-radar/contents"
RAW = "https://raw.githubusercontent.com/jhuanglabAI/damo-radar/main"

# Minimal tree needed for inference_demo import path.
KEEP_PREFIXES = (
    "RADAR_inference/",
    "requirements.txt",
    "README.md",
    "LICENSE",
    "ckpt/infer_text_embedding_radar.pt",
    "ckpt/infer_text_embedding_merlin.pt",
)


def _get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "tigerpro-radar-setup"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "tigerpro-radar-setup"})
    with urllib.request.urlopen(req, timeout=180) as resp, dest.open("wb") as out:
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)


def _wanted(path: str) -> bool:
    if path in ("requirements.txt", "README.md", "LICENSE"):
        return True
    if path == "RADAR_inference" or path.startswith("RADAR_inference/"):
        return True
    if path == "ckpt" or path.startswith("ckpt/infer_text_embedding"):
        return True
    return False


def walk(rel: str = "") -> None:
    url = f"{API}/{rel}" if rel else API
    items = _get_json(url)
    if not isinstance(items, list):
        return
    for item in items:
        path = item["path"]
        if not _wanted(path):
            continue
        if item["type"] == "dir":
            walk(path)
            continue
        dest = DEST / path
        if dest.is_file() and dest.stat().st_size > 0:
            print(f"skip {path}", flush=True)
            continue
        download_url = item.get("download_url") or f"{RAW}/{path}"
        print(f"get {path}", flush=True)
        _download(download_url, dest)


def main() -> int:
    DEST.mkdir(parents=True, exist_ok=True)
    walk("")
    demo = DEST / "RADAR_inference" / "inference_demo.py"
    if not demo.is_file():
        print("failed: inference_demo.py missing", flush=True)
        return 1
    print(f"vendor sparse ready: {DEST}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
