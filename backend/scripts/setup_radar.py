"""克隆 damo-radar 并下载 HuggingFace 权重到本项目目录。

用法（在 backend 目录）::

  python scripts/setup_radar.py                  # 仅克隆代码
  python scripts/setup_radar.py --download-weights
  python scripts/setup_radar.py --download-weights --include-unet

布局::

  uploads/models/third_party/damo-radar/   # 官方/镜像代码
  uploads/models/radar/                    # checkpoint + bert + text embedding

环境变量::

  RADAR_ENGINE=auto|mock|real   （默认 auto：权重+代码就绪则真推理）
  RADAR_CKPT_DIR / RADAR_VENDOR_DIR / RADAR_DEVICE
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "uploads" / "models" / "third_party" / "damo-radar"
CKPT = ROOT / "uploads" / "models" / "radar"

# Official org repo may 404 / geo-block; mirror + zipball are fallbacks.
REPO_CANDIDATES = (
    # Official org may 404 / be geo-blocked; prefer mirror first.
    "https://github.com/jhuanglabAI/damo-radar.git",
    "https://github.com/alibaba-damo-academy/damo-radar.git",
)
ZIP_CANDIDATES = (
    "https://codeload.github.com/jhuanglabAI/damo-radar/zip/refs/heads/main",
    "https://github.com/jhuanglabAI/damo-radar/archive/refs/heads/main.zip",
)

HF_REPO = "radar-generalist/RADAR"
TEXT_EMBED_URL = (
    "https://raw.githubusercontent.com/jhuanglabAI/damo-radar/main/"
    "ckpt/infer_text_embedding_radar.pt"
)


def _has_vendor(path: Path) -> bool:
    return (path / "RADAR_inference" / "inference_demo.py").is_file()


def _download(url: str, dest: Path, *, timeout: int = 120) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Prefer curl for progress + better Windows timeout behavior.
    curl = shutil.which("curl") or shutil.which("curl.exe")
    if curl:
        cmd = [
            curl, "-L", "--fail", "--retry", "3",
            "--connect-timeout", "30",
            "-o", str(dest), url,
        ]
        print(f"curl {' '.join(cmd[-2:])}", flush=True)
        result = subprocess.run(cmd, check=False)
        if result.returncode != 0 or not dest.is_file() or dest.stat().st_size < 1000:
            dest.unlink(missing_ok=True)
            raise RuntimeError(f"curl download failed ({result.returncode}): {url}")
        return
    req = urllib.request.Request(url, headers={"User-Agent": "tigerpro-radar-setup"})
    print(f"urllib {url}", flush=True)
    with urllib.request.urlopen(req, timeout=timeout) as resp, dest.open("wb") as out:
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)


def clone_vendor(*, force: bool = False, prefer_zip: bool = False, git_timeout: int = 120) -> int:
    DEST.parent.mkdir(parents=True, exist_ok=True)
    if _has_vendor(DEST) and not force:
        print(f"already present: {DEST}")
        return 0
    if DEST.exists() and force:
        shutil.rmtree(DEST)

    env = os.environ.copy()
    env["GIT_LFS_SKIP_SMUDGE"] = "1"

    if not prefer_zip:
        for repo in REPO_CANDIDATES:
            print(f"cloning {repo} -> {DEST} (timeout {git_timeout}s)")
            try:
                result = subprocess.run(
                    ["git", "clone", "--depth", "1", repo, str(DEST)],
                    check=False,
                    env=env,
                    timeout=git_timeout,
                )
            except subprocess.TimeoutExpired:
                print(f"clone timed out: {repo}")
                if DEST.exists():
                    shutil.rmtree(DEST, ignore_errors=True)
                continue
            if result.returncode == 0 and _has_vendor(DEST):
                print("clone ok")
                return 0
            if DEST.exists():
                shutil.rmtree(DEST, ignore_errors=True)

    print("trying sparse API fetch…")
    sparse = ROOT / "scripts" / "fetch_radar_vendor_sparse.py"
    if sparse.is_file():
        result = subprocess.run([sys.executable, str(sparse)], check=False)
        if result.returncode == 0 and _has_vendor(DEST):
            return 0

    print("trying zipball…")
    with tempfile.TemporaryDirectory(prefix="radar_zip_") as tmp:
        zip_path = Path(tmp) / "damo-radar.zip"
        last_error = None
        for url in ZIP_CANDIDATES:
            try:
                print(f"download {url}")
                _download(url, zip_path, timeout=600)
                break
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                zip_path.unlink(missing_ok=True)
        else:
            print(f"zipball download failed: {last_error}", file=sys.stderr)
            return 1

        extract_root = Path(tmp) / "extract"
        extract_root.mkdir()
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract_root)
        children = [p for p in extract_root.iterdir() if p.is_dir()]
        if not children:
            print("zipball empty", file=sys.stderr)
            return 1
        src = children[0]
        if DEST.exists():
            shutil.rmtree(DEST)
        shutil.move(str(src), str(DEST))

    if not _has_vendor(DEST):
        print("vendor layout incomplete after zip extract", file=sys.stderr)
        return 1
    print(f"vendor ready: {DEST}")
    return 0


def download_text_embedding() -> None:
    target = CKPT / "infer_text_embedding_radar.pt"
    if target.is_file() and target.stat().st_size > 1000:
        print(f"text embedding exists: {target}")
        return
    # Prefer vendor copy when present (may be LFS pointer — check size).
    vendor_copy = DEST / "ckpt" / "infer_text_embedding_radar.pt"
    if vendor_copy.is_file() and vendor_copy.stat().st_size > 1000:
        CKPT.mkdir(parents=True, exist_ok=True)
        shutil.copy2(vendor_copy, target)
        print(f"copied text embedding -> {target}")
        return
    print(f"download text embedding -> {target}")
    _download(TEXT_EMBED_URL, target, timeout=180)
    print(f"ok {target} ({target.stat().st_size} bytes)")


def _min_bytes_for(repo_path: str) -> int:
    """Expected minimum sizes for RADAR assets (reject truncated downloads)."""
    name = repo_path.replace("\\", "/").lower()
    if name.endswith("checkpoint_radar_pretrain.pth"):
        return 1_500_000_000  # official ~1.46 GiB (1,566,049,482)
    if name.endswith("pytorch_model.bin") and "bert-base-chinese" in name:
        return 400_000_000  # ~392 MiB
    if name.endswith(".pth"):
        return 100_000_000
    if name.endswith(".bin") or name.endswith(".safetensors"):
        return 1_000_000
    return 32


def _hf_resolve_url(repo_path: str) -> str:
    endpoint = (
        os.environ.get("HF_ENDPOINT")
        or os.environ.get("HUGGINGFACE_HUB_ENDPOINT")
        or "https://huggingface.co"
    ).rstrip("/")
    return f"{endpoint}/{HF_REPO}/resolve/main/{repo_path}"


def _curl_download(url: str, dest: Path, *, min_bytes: int) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    curl = shutil.which("curl") or shutil.which("curl.exe")
    if not curl:
        raise RuntimeError("curl not found; cannot download weights")
    # Resume with -C - ; follow redirects; fail on HTTP errors.
    cmd = [
        curl, "-L", "--fail", "--retry", "5", "--retry-delay", "3",
        "--connect-timeout", "30",
        "-C", "-",
        "-o", str(dest),
        url,
    ]
    print(f"curl {url}", flush=True)
    result = subprocess.run(cmd, check=False)
    if result.returncode not in (0, 33):  # 33 = resume beyond EOF (already complete)
        # curl 33 can happen when file is already fully downloaded; re-check size.
        if dest.is_file() and dest.stat().st_size >= min_bytes:
            return
        raise RuntimeError(f"curl failed ({result.returncode}): {url}")
    if not dest.is_file() or dest.stat().st_size < min_bytes:
        raise RuntimeError(f"download incomplete: {dest} size={dest.stat().st_size if dest.is_file() else 0}")


def _hf_download(repo_path: str, dest: Path) -> None:
    """Download one HF file via curl (mirror-friendly) with hub fallback."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    min_bytes = _min_bytes_for(repo_path)
    if dest.is_file() and dest.stat().st_size >= min_bytes:
        print(f"exists {dest} ({dest.stat().st_size} bytes)", flush=True)
        return

    url = _hf_resolve_url(repo_path)
    print(f"HF download {repo_path} -> {dest}", flush=True)
    try:
        _curl_download(url, dest, min_bytes=min_bytes)
        print(f"ok {dest} ({dest.stat().st_size} bytes)", flush=True)
        return
    except Exception as curl_exc:  # noqa: BLE001
        print(f"curl failed ({curl_exc}); trying huggingface_hub…", flush=True)

    from huggingface_hub import hf_hub_download

    cached = hf_hub_download(
        repo_id=HF_REPO,
        filename=repo_path,
        repo_type="model",
        local_dir=str(CKPT),
        force_download=False,
    )
    cached_path = Path(cached)
    if cached_path.resolve() != dest.resolve() and cached_path.is_file():
        if dest.is_file():
            dest.unlink()
        shutil.copy2(cached_path, dest)
    if not dest.is_file() or dest.stat().st_size < min_bytes:
        raise RuntimeError(f"download incomplete: {dest}")
    print(f"ok {dest} ({dest.stat().st_size} bytes)", flush=True)


def download_weights(*, include_unet: bool = False, include_plus: bool = False) -> int:
    CKPT.mkdir(parents=True, exist_ok=True)
    try:
        from huggingface_hub import hf_hub_download  # noqa: F401
    except ImportError:
        print("huggingface_hub 未安装，请: pip install huggingface_hub", file=sys.stderr)
        return 1

    # Small files first so a flaky network still leaves BERT usable for retries.
    files = [
        "bert-base-chinese/config.json",
        "bert-base-chinese/config_decoder.json",
        "bert-base-chinese/tokenizer.json",
        "bert-base-chinese/tokenizer_config.json",
        "bert-base-chinese/vocab.txt",
        "bert-base-chinese/pytorch_model.bin",
        "checkpoint_radar_pretrain.pth",
    ]
    if include_unet:
        files.append("checkpoint_unet.pth")
    if include_plus:
        files.extend([
            "checkpoint_radar_plus.pth",
            "checkpoint_radar_plus_finetuned_on_merlin.pth",
            "bert-base-uncased/config.json",
            "bert-base-uncased/pytorch_model.bin",
        ])

    for repo_path in files:
        _hf_download(repo_path, CKPT / repo_path.replace("/", os.sep))
    download_text_embedding()

    ckpt = CKPT / "checkpoint_radar_pretrain.pth"
    bert = CKPT / "bert-base-chinese" / "config.json"
    bert_weights = CKPT / "bert-base-chinese" / "pytorch_model.bin"
    text = CKPT / "infer_text_embedding_radar.pt"
    ok = (
        ckpt.is_file() and ckpt.stat().st_size > 1_500_000_000
        and bert.is_file()
        and bert_weights.is_file() and bert_weights.stat().st_size > 400_000_000
        and text.is_file()
    )
    if not ok:
        print("weights incomplete after download", file=sys.stderr)
        return 1
    print("weights ready:")
    print(f"  {ckpt} ({ckpt.stat().st_size} bytes)")
    print(f"  {CKPT / 'bert-base-chinese'}")
    print(f"  {text} ({text.stat().st_size} bytes)")
    return 0


def print_next_steps() -> None:
    print("next:")
    print(f"  # optional deps: pip install -r {DEST / 'requirements.txt'}")
    print("  # set RADAR_ENGINE=auto (default) or real")
    print(f"  # RADAR_CKPT_DIR={CKPT}")
    print(f"  # RADAR_VENDOR_DIR={DEST}")
    print("  # GPU required for real inference (official demo uses .cuda())")
    print("  # if HF is slow in CN: set HF_ENDPOINT=https://hf-mirror.com")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Setup damo-radar vendor + weights")
    parser.add_argument("--force-clone", action="store_true", help="Re-clone vendor tree")
    parser.add_argument("--prefer-zip", action="store_true", help="Skip git; download zipball")
    parser.add_argument("--git-timeout", type=int, default=120, help="Seconds before git clone fallback")
    parser.add_argument(
        "--download-weights",
        action="store_true",
        help="Download HF checkpoint + bert-base-chinese + text embedding",
    )
    parser.add_argument("--include-unet", action="store_true")
    parser.add_argument("--include-plus", action="store_true", help="Also download RADAR+ ckpts")
    parser.add_argument("--skip-clone", action="store_true")
    args = parser.parse_args(argv)

    code = 0
    if not args.skip_clone:
        code = clone_vendor(
            force=args.force_clone,
            prefer_zip=args.prefer_zip,
            git_timeout=max(30, int(args.git_timeout)),
        )
        if code != 0:
            return code

    if args.download_weights:
        code = download_weights(include_unet=args.include_unet, include_plus=args.include_plus)
        if code != 0:
            return code
    else:
        # Always try to place the small text embedding when vendor exists.
        try:
            download_text_embedding()
        except Exception as exc:  # noqa: BLE001
            print(f"text embedding skipped: {exc}")

    print_next_steps()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
