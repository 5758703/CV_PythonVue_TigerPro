"""Verified HF HTTP downloads into managed model directories, without Xet/cache.

The model API's blobs manifest fixes a single commit. LFS payloads use SHA256;
ordinary repository files use the Git blob SHA1, including its object header.
"""
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import shutil
import time
from urllib.parse import quote

import requests


_BASE = 'https://huggingface.co'
_CHUNK_SIZE = 1024 * 1024
_PROGRESS_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class _Asset:
    name: str
    size: int
    digest: str
    lfs: bool


def _safe_path(root: Path, name: str) -> Path:
    if (not isinstance(name, str) or not name or '\\' in name or ':' in name
            or any(part in {'', '.', '..'} for part in name.split('/'))):
        raise ValueError(f'Unsafe HF asset filename: {name}')
    path = root / name
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ValueError(f'Unsafe HF asset path: {name}')
    if path.exists() and not path.is_file():
        raise ValueError(f'HF asset path is not a regular file: {name}')
    return path


def _manifest(repo_id, names, headers):
    with requests.get(f'{_BASE}/api/models/{repo_id}?blobs=true',
                      headers=headers, timeout=(15, 60)) as response:
        response.raise_for_status()
        metadata = response.json()
    revision = metadata.get('sha', '')
    if not isinstance(revision, str) or not re.fullmatch(r'[a-fA-F0-9]{40}', revision):
        raise ValueError('HF manifest does not identify a fixed commit revision')
    siblings = {item['rfilename']: item for item in metadata.get('siblings', [])
                if isinstance(item, dict) and item.get('rfilename') in names}
    files = []
    for name in names:
        info = siblings.get(name)
        if info is None:
            raise ValueError(f'HF manifest is missing required file: {name}')
        size = info.get('size')
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise ValueError(f'HF manifest has invalid file size: {name}')
        lfs = info.get('lfs')
        if lfs is not None:
            digest = lfs.get('sha256', '') if isinstance(lfs, dict) else ''
            length = 64
            if isinstance(lfs, dict) and lfs.get('size', size) != size:
                raise ValueError(f'HF manifest has inconsistent LFS size: {name}')
        else:
            digest = info.get('blobId', '')
            length = 40
        if not isinstance(digest, str) or not re.fullmatch(rf'[a-fA-F0-9]{{{length}}}', digest):
            raise ValueError(f'HF manifest has no valid content hash: {name}')
        files.append(_Asset(name, size, digest.lower(), lfs is not None))
    return revision, files


def _hasher(asset):
    if asset.lfs:
        return hashlib.sha256()
    result = hashlib.sha1()
    result.update(f'blob {asset.size}\0'.encode('ascii'))
    return result


def _verified(path, asset):
    if not path.is_file() or path.stat().st_size != asset.size:
        return False
    digest = _hasher(asset)
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(_CHUNK_SIZE), b''):
            digest.update(chunk)
    return digest.hexdigest() == asset.digest


def download_hf_files(repo_id: str, target_dir: str, required: tuple[str, ...], token=None) -> int:
    """Download only required files at one commit; return validated total bytes.

    No SDK or external cache is used. Existing files must match size and hash;
    interrupted or corrupt responses never become formal model filenames.
    """
    if (not isinstance(repo_id, str) or not re.fullmatch(r'[\w.-]+(?:/[\w.-]+)?', repo_id)
            or any(part in {'.', '..'} for part in repo_id.split('/'))):
        raise ValueError('Invalid Hugging Face model repository ID')
    if not target_dir or not str(target_dir).strip():
        raise ValueError('HF target directory must not be empty')
    if isinstance(required, str):
        raise ValueError('Required filenames must be a sequence of safe relative paths')
    root = Path(target_dir).resolve()
    names = tuple(dict.fromkeys(required))
    for name in names:
        _safe_path(root, name)
        _safe_path(root, name + '.part')
    if not names:
        return 0
    headers = {'Authorization': f'Bearer {token}'} if token else {}
    revision, files = _manifest(repo_id, names, headers)
    paths = [(asset, _safe_path(root, asset.name), _safe_path(root, asset.name + '.part'))
             for asset in files]
    pending = [(asset, path, partial) for asset, path, partial in paths if not _verified(path, asset)]
    root.mkdir(parents=True, exist_ok=True)
    needed = sum(asset.size for asset, _, _ in pending)
    margin = max(16 * 1024**2, needed // 20) if pending else 0
    if shutil.disk_usage(root).free < needed + margin:
        raise OSError(f'Insufficient disk space for HF model: need {needed + margin} bytes')
    for asset, path, partial in pending:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Drop known-bad final files, so an interrupted retry cannot appear ready.
        if path.exists():
            path.unlink()
        url = (f'{_BASE}/{repo_id}/resolve/{revision}/{quote(asset.name, safe="/")}'
               f'?download=true&cb={time.time_ns()}')
        size = 0
        next_progress = _PROGRESS_BYTES
        digest = _hasher(asset)
        try:
            with requests.get(url, headers=headers, stream=True, timeout=(15, 120)) as response:
                response.raise_for_status()
                with partial.open('wb') as output:
                    for chunk in response.iter_content(chunk_size=_CHUNK_SIZE):
                        if not chunk:
                            continue
                        size += len(chunk)
                        if size > asset.size:
                            raise RuntimeError(f'HF asset size mismatch: {asset.name}')
                        output.write(chunk)
                        digest.update(chunk)
                        if size >= next_progress:
                            print(f'{repo_id}/{asset.name}: {size // 1024**2} MiB downloaded', flush=True)
                            next_progress = (size // _PROGRESS_BYTES + 1) * _PROGRESS_BYTES
            if size != asset.size:
                raise RuntimeError(f'HF asset size mismatch: {asset.name}')
            if digest.hexdigest() != asset.digest:
                raise RuntimeError(f'HF asset checksum mismatch: {asset.name}')
            partial.replace(path)
        finally:
            partial.unlink(missing_ok=True)
    return sum(asset.size for asset in files)
