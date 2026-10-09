"""Download NeuTTS Air (+ optional NeuCodec) weights (resume-safe).

- Backbone → uploads/models/neutts-air
- Codec (gated) → HuggingFace hub cache via hf_hub_download（NeuCodec.from_pretrained 只认 repo id）

Skips GGUF/image. Streams large files with HTTP Range resume for flaky links.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
# Prefer official Hub (hf-mirror often breaks gated LFS metadata).
os.environ.pop("HF_ENDPOINT", None)

REPO = "neuphonic/neutts-air"
CODEC_REPO = "neuphonic/neucodec"
CODEC_FILES = ("pytorch_model.bin", "meta.yaml")
SKIP_SUFFIX = (".gguf", ".png")


def _dir_size(folder: Path) -> int:
    return sum(
        p.stat().st_size
        for p in folder.rglob("*")
        if p.is_file() and ".cache" not in p.parts
    )


def _stream_download(
    url: str,
    dest: Path,
    token: str,
    expected_size: int | None,
    max_retries: int = 80,
) -> None:
    import requests

    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    if dest.is_file() and (expected_size is None or dest.stat().st_size == expected_size):
        print(f"  skip existing {dest.name} ({dest.stat().st_size / 1e6:.1f} MB)", flush=True)
        return

    attempt = 0
    while True:
        attempt += 1
        headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": "tigerpro-neutts-fetch/1.0",
        }
        existing = part.stat().st_size if part.is_file() else 0
        if expected_size and existing > expected_size:
            part.unlink(missing_ok=True)
            existing = 0
        if existing:
            headers["Range"] = f"bytes={existing}-"
            print(f"  resume from {existing / 1e6:.1f} MB (try {attempt})", flush=True)
        else:
            print(f"  start download (try {attempt})", flush=True)

        try:
            with requests.get(
                url, headers=headers, stream=True, timeout=(30, 120), allow_redirects=True
            ) as resp:
                if resp.status_code not in (200, 206):
                    raise RuntimeError(
                        f"HTTP {resp.status_code} for {dest.name}: {resp.text[:200]}"
                    )
                mode = "ab" if resp.status_code == 206 and existing else "wb"
                if mode == "wb" and part.is_file():
                    part.unlink()
                    existing = 0
                downloaded = existing
                t0 = time.time()
                last_print = t0
                with open(part, mode) as fh:
                    for chunk in resp.iter_content(chunk_size=1024 * 1024):
                        if not chunk:
                            continue
                        fh.write(chunk)
                        downloaded += len(chunk)
                        now = time.time()
                        if now - last_print >= 5:
                            speed = (downloaded - existing) / max(now - t0, 1) / 1e6
                            pct = (downloaded / expected_size * 100) if expected_size else 0
                            print(
                                f"  ... {downloaded / 1e6:.1f} MB ({pct:.1f}%) @ {speed:.2f} MB/s",
                                flush=True,
                            )
                            last_print = now
        except (
            requests.exceptions.ChunkedEncodingError,
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.RequestException,
        ) as exc:
            have = part.stat().st_size if part.is_file() else 0
            print(f"  broken @ {have / 1e6:.1f} MB: {type(exc).__name__}: {exc}", flush=True)
            if attempt >= max_retries:
                raise
            time.sleep(min(30, 2 + attempt))
            continue

        have = part.stat().st_size if part.is_file() else 0
        if expected_size and have != expected_size:
            print(
                f"  incomplete size {have} != {expected_size}, retrying...",
                flush=True,
            )
            if attempt >= max_retries:
                raise RuntimeError(
                    f"size mismatch for {dest.name}: got {have}, want {expected_size}"
                )
            time.sleep(min(30, 2 + attempt))
            continue

        part.replace(dest)
        print(f"  OK {dest.name} {dest.stat().st_size / 1e6:.1f} MB", flush=True)
        return


def _fetch_neucodec(token: str) -> None:
    """NeuCodec.from_pretrained 内部只下载 pytorch_model.bin + meta.yaml 到 HF 缓存。"""
    from huggingface_hub import hf_hub_download

    print(f"CODEC_TARGET=HF_CACHE repo={CODEC_REPO}", flush=True)
    for name in CODEC_FILES:
        print(f"  downloading {name} ...", flush=True)
        path = hf_hub_download(repo_id=CODEC_REPO, filename=name, token=token)
        size = Path(path).stat().st_size if Path(path).is_file() else 0
        print(f"  OK {name} -> {path} ({size / 1e6:.1f} MB)", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch NeuTTS Air / NeuCodec weights")
    parser.add_argument(
        "--with-neucodec",
        action="store_true",
        default=True,
        help="Also cache gated neuphonic/neucodec (default: on)",
    )
    parser.add_argument(
        "--skip-neucodec",
        action="store_true",
        help="Skip neucodec download",
    )
    parser.add_argument(
        "--codec-only",
        action="store_true",
        help="Only download neucodec into HF cache",
    )
    args = parser.parse_args()
    want_codec = (args.with_neucodec or args.codec_only) and not args.skip_neucodec

    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_HUB_TOKEN")
    if not token:
        print("ERROR: HF_TOKEN missing in backend/.env", flush=True)
        return 1

    from huggingface_hub import HfApi, hf_hub_url

    api = HfApi(token=token)
    who = api.whoami()
    print(f"HF_USER={who.get('name')}", flush=True)

    if want_codec:
        try:
            _fetch_neucodec(token)
        except Exception as exc:  # noqa: BLE001
            print(
                f"ERROR: neucodec download failed: {exc}\n"
                "Visit https://huggingface.co/neuphonic/neucodec and accept the license "
                "with the same account as HF_TOKEN.",
                flush=True,
            )
            return 1
        if args.codec_only:
            print("DONE codec-only", flush=True)
            return 0

    folder = ROOT / "uploads" / "models" / "neutts-air"
    folder.mkdir(parents=True, exist_ok=True)
    print(f"TARGET={folder}", flush=True)

    paths = [
        p
        for p in api.list_repo_files(REPO)
        if not p.endswith(SKIP_SUFFIX) and p != ".gitattributes"
    ]
    infos = {p.path: p for p in api.get_paths_info(REPO, paths, expand=True)}
    # Big weight first so we know early if network works.
    paths.sort(key=lambda n: (0 if n.endswith(".safetensors") else 1, n))
    print(f"FILES={paths}", flush=True)

    t0 = time.time()
    for i, name in enumerate(paths, 1):
        info = infos.get(name)
        size = getattr(info, "size", None) if info is not None else None
        url = hf_hub_url(REPO, filename=name)
        # Resolve redirect / CDN with auth via huggingface hub helper when possible
        print(f"[{i}/{len(paths)}] {name} (expect_MB={None if size is None else size / 1e6:.1f})", flush=True)
        try:
            from huggingface_hub.file_download import get_hf_file_metadata

            meta = get_hf_file_metadata(url=hf_hub_url(REPO, filename=name), token=token)
            url = meta.location or url
            size = size or meta.size
        except Exception as exc:  # noqa: BLE001
            print(f"  metadata warn: {exc}", flush=True)
        _stream_download(url, folder / name, token, size)

    elapsed = time.time() - t0
    total = _dir_size(folder)
    print(f"DONE total_MB={total / 1e6:.1f} ELAPSED_SEC={elapsed:.0f}", flush=True)

    try:
        from app import create_app
        from models import AiModel, db

        app = create_app()
        with app.app_context():
            m = AiModel.query.filter_by(model_key="neutts-air").first()
            if m is None:
                print("DB: neutts-air not seeded yet", flush=True)
            else:
                m.file_path = "models/neutts-air"
                m.file_size = total
                db.session.commit()
                print(f"DB_UPDATED id={m.id} file_path={m.file_path}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"DB_BIND_SKIP: {exc}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
