"""Pinned English streaming assets, independent of the optional Moonshine SDK.

Metadata is the English subset of moonshine-voice v0.1.5, commit
234f60faa0eb388b01cdf7e60aca232af37aefda:
https://github.com/moonshine-ai/moonshine/blob/v0.1.5/core/moonshine-model-catalog.cpp
https://github.com/moonshine-ai/moonshine/blob/v0.1.5/core/moonshine-model-file-metadata.generated.cpp
Upstream publishes CRC32C (base64, big endian), not SHA256. The optional
attention decoder is unnecessary unless word timestamps are requested.
"""
import base64
from dataclasses import dataclass
from pathlib import Path
import shutil

import requests


@dataclass(frozen=True)
class Asset:
    name: str
    size: int
    crc32c: str


_MODELS = {
    'tiny-streaming': (
        Asset('adapter.ort', 1319664, 'kwQ+Bw=='),
        Asset('cross_kv.ort', 1287544, '76wzFQ=='),
        Asset('decoder_kv.ort', 32583720, 'KJjeNw=='),
        Asset('encoder.ort', 7675440, 'UjAIpQ=='),
        Asset('frontend.model.ort', 23344, 'aM/+wQ=='),
        Asset('frontend.weights.ort', 2093464, 'WYZ7EQ=='),
        Asset('streaming_config.json', 509, 'HGL0Ug=='),
        Asset('tokenizer.bin', 249974, 'B7s10Q=='),
    ),
    'small-streaming': (
        Asset('adapter.ort', 2870368, 'XlWjTg=='),
        Asset('cross_kv.ort', 5356536, '5ySK8g=='),
        Asset('decoder_kv.ort', 81878600, 'Rn/VUA=='),
        Asset('encoder.ort', 44148576, '41D2jQ=='),
        Asset('frontend.model.ort', 26944, 'WW2/2g=='),
        Asset('frontend.weights.ort', 7769464, '9pROuQ=='),
        Asset('streaming_config.json', 512, 'dPbFiw=='),
        Asset('tokenizer.bin', 249974, 'B7s10Q=='),
    ),
    'medium-streaming': (
        Asset('adapter.ort', 3651296, 'Ds3Hsg=='),
        Asset('cross_kv.ort', 11643776, 'liqlOg=='),
        Asset('decoder_kv.ort', 146972408, 'GPnzeQ=='),
        Asset('encoder.ort', 94705376, 'yWvDwA=='),
        Asset('frontend.model.ort', 28720, 'k1kKsQ=='),
        Asset('frontend.weights.ort', 11889560, 'w5QjIA=='),
        Asset('streaming_config.json', 513, '+1bE9Q=='),
        Asset('tokenizer.bin', 249974, 'B7s10Q=='),
    ),
}
_CDN = 'https://download.moonshine.ai/model'
_REVISION = 'quantized_26_08_21'
_CHUNK_SIZE = 1024 * 1024


def _architecture(arch: str) -> str:
    value = str(arch).strip().lower().replace('_', '-')
    if value not in _MODELS:
        raise ValueError(f'Unsupported published Moonshine architecture: {arch}')
    return value


def required_files(arch: str) -> tuple[str, ...]:
    """Return the filenames required by the native streaming transcriber."""
    return tuple(asset.name for asset in _MODELS[_architecture(arch)])


def _crc_table() -> tuple[int, ...]:
    table = []
    for value in range(256):
        for _ in range(8):
            value = (value >> 1) ^ (0x82F63B78 if value & 1 else 0)
        table.append(value)
    return tuple(table)


_CRC_TABLE = _crc_table()


def _crc32c(data: bytes, crc: int = 0) -> int:
    """Incremental Castagnoli CRC fallback when no accelerated package exists."""
    crc ^= 0xFFFFFFFF
    for value in data:
        crc = _CRC_TABLE[(crc ^ value) & 0xFF] ^ (crc >> 8)
    return crc ^ 0xFFFFFFFF


try:
    from google_crc32c import extend as _crc_update
except ImportError:
    _crc_update = lambda crc, data: _crc32c(data, crc)


def _safe_path(root: Path, name: str) -> Path:
    if not name or name in {'.', '..'} or any(c in name for c in '/\\:'):
        raise ValueError(f'Unsafe Moonshine asset filename: {name}')
    path = root / name
    if path.is_symlink() or path.resolve().parent != root:
        raise ValueError(f'Unsafe Moonshine asset filename: {name}')
    return path


def missing_files(arch: str, target_dir: str) -> list[str]:
    """Cheap readiness check against published sizes; downloads verify CRC32C.

    This intentionally avoids hashing hundreds of megabytes for each model
    options request. Absent, truncated and unsafe files all count as missing.
    """
    root = Path(target_dir).resolve()
    missing = []
    for asset in _MODELS[_architecture(arch)]:
        try:
            path = _safe_path(root, asset.name)
            valid = path.is_file() and path.stat().st_size == asset.size
        except (OSError, ValueError):
            valid = False
        if not valid:
            missing.append(asset.name)
    return missing


def _verified(path: Path, asset: Asset) -> bool:
    if not path.is_file() or path.stat().st_size != asset.size:
        return False
    crc = 0
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(_CHUNK_SIZE), b''):
            crc = _crc_update(crc, chunk)
    expected = int.from_bytes(base64.b64decode(asset.crc32c), 'big')
    return crc == expected


def download_model(arch: str, target_dir: str) -> int:
    """Install into exactly target_dir; return total verified installed bytes.

    Downloads never touch the SDK cache. Interrupted or invalid files are not
    promoted to model filenames. Existing assets are skipped only after size
    and CRC32C validation; a retry replaces corrupt files from byte zero.
    """
    arch = _architecture(arch)
    if not str(target_dir).strip():
        raise ValueError('Moonshine target directory must not be empty')
    root = Path(target_dir).resolve()
    files = _MODELS[arch]
    paths = [(asset, _safe_path(root, asset.name),
              _safe_path(root, asset.name + '.part')) for asset in files]
    root.mkdir(parents=True, exist_ok=True)
    pending = [(asset, path, partial) for asset, path, partial in paths
               if not _verified(path, asset)]
    needed = sum(asset.size for asset, _, _ in pending)
    if shutil.disk_usage(root).free < needed:
        raise OSError(f'Insufficient disk space for Moonshine: need {needed} bytes')
    for asset, path, partial in pending:
        # A corrupt previous final file must not make a failed retry look ready.
        if path.exists():
            path.unlink()
        url = f'{_CDN}/{arch}-en/{_REVISION}/{asset.name}'
        try:
            with requests.get(url, stream=True, timeout=(15, 120)) as response:
                response.raise_for_status()
                size = 0
                with partial.open('wb') as output:
                    for chunk in response.iter_content(chunk_size=_CHUNK_SIZE):
                        if not chunk:
                            continue
                        size += len(chunk)
                        if size > asset.size:
                            raise RuntimeError(f'Moonshine asset size mismatch: {asset.name}')
                        output.write(chunk)
            if size != asset.size:
                raise RuntimeError(f'Moonshine asset size mismatch: {asset.name}')
            if not _verified(partial, asset):
                raise RuntimeError(f'Moonshine asset checksum mismatch: {asset.name}')
            partial.replace(path)
        finally:
            partial.unlink(missing_ok=True)
    return sum(asset.size for asset in files)
