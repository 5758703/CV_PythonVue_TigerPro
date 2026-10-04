"""Prepare official GGUF files with resumable downloads and SHA-256 checks.

This command needs Internet only during preparation. Inference uses local files.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time
import threading
from concurrent.futures import ThreadPoolExecutor

import requests

from confucius_cpu_server import MODELS


def digest(path):
    sha = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b''):
            sha.update(block)
    return sha.hexdigest()


def download_ranges(url, partial, size):
    """Download bounded parts, then merge and remove each part to limit disk use."""
    checkpoint = partial.with_suffix(partial.suffix + '.ranges.json')
    block_size = 128 * 1024 * 1024
    parts = partial.with_suffix(partial.suffix + '.parts')
    parts.mkdir(exist_ok=True)
    if checkpoint.exists():
        state = json.loads(checkpoint.read_text())
        if state['size'] != size:
            raise RuntimeError('Download checkpoint size does not match asset')
        merged = state.get('merged', 0)
    else:
        previous = partial.stat().st_size if partial.exists() else 0
        merged = previous // block_size
        with partial.open('ab') as handle:
            handle.truncate(merged * block_size)
    done = set(range(merged))
    count = (size + block_size - 1) // block_size
    for index in range(merged, count):
        path = parts / str(index)
        if path.exists() and path.stat().st_size == min(block_size, size - index * block_size):
            done.add(index)
    lock = threading.Lock()
    def save():
        checkpoint.write_text(json.dumps({'size': size, 'merged': merged}))
    save()
    def fetch(index):
        start, end = index * block_size, min(size, (index + 1) * block_size) - 1
        for attempt in range(3):
            try:
                with requests.get(url, headers={'Range': f'bytes={start}-{end}'},
                                  stream=True, timeout=(30, 120)) as response:
                    response.raise_for_status()
                    if response.status_code != 206 or not response.headers.get('Content-Range', '').startswith(f'bytes {start}-{end}/'):
                        raise RuntimeError('Server did not honor download range')
                    with (parts / str(index)).open('wb') as handle:
                        written = 0
                        for data in response.iter_content(1024 * 1024):
                            if written + len(data) > end - start + 1:
                                raise RuntimeError('Download range exceeded expected size')
                            handle.write(data)
                            written += len(data)
                    if written != end - start + 1:
                        raise RuntimeError('Incomplete download range')
                with lock:
                    done.add(index)
                    save()
                    print(f'{partial.name}: {len(done)}/{count} verified ranges downloaded', flush=True)
                return
            except (requests.RequestException, RuntimeError):
                if attempt == 2:
                    raise
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(fetch, [i for i in range(count) if i not in done]))
    with partial.open('r+b' if partial.exists() else 'wb') as target:
        target.truncate(min(size, merged * block_size))
        target.seek(0, 2)
        for index in range(merged, count):
            path = parts / str(index)
            with path.open('rb') as source:
                for data in iter(lambda: source.read(4 * 1024 * 1024), b''):
                    target.write(data)
            target.flush()
            merged = index + 1
            save()
            path.unlink()
    parts.rmdir()
    return checkpoint


def prepare(model, folder):
    repo, _, filename, projector, _ = MODELS[model]
    info = requests.get(f'https://huggingface.co/api/models/{repo}', timeout=30)
    info.raise_for_status()
    revision = info.json()['sha']
    tree = requests.get(f'https://huggingface.co/api/models/{repo}/tree/{revision}', timeout=30)
    tree.raise_for_status()
    assets = {item['path']: item for item in tree.json()}
    folder.mkdir(parents=True, exist_ok=True)
    verified = []
    for name in [filename] + ([projector] if projector else []):
        item = assets[name]
        size, sha = item['size'], item['lfs']['oid']
        target = folder / name
        partial = folder / (name + '.part')
        if target.is_file() and target.stat().st_size == size and digest(target) == sha:
            print(f'Already verified: {name}', flush=True)
        else:
            offset = partial.stat().st_size if partial.exists() else 0
            if offset > size:
                raise RuntimeError(f'Partial file is larger than expected: {partial}')
            url = f'https://huggingface.co/{repo}/resolve/{revision}/{name}'
            checkpoint = None
            if size > 2 * 1024**3:
                checkpoint = download_ranges(url, partial, size)
            elif offset < size:
                with requests.get(url, headers={'Range': f'bytes={offset}-'} if offset else {},
                                  stream=True, timeout=(30, 120)) as response:
                    response.raise_for_status()
                    if offset and (response.status_code != 206 or
                                   not response.headers.get('Content-Range', '').startswith(f'bytes {offset}-')):
                        offset = 0
                    started = last_report = time.monotonic()
                    with partial.open('ab' if offset else 'wb') as handle:
                        for block in response.iter_content(1024 * 1024):
                            handle.write(block)
                            if time.monotonic() - last_report >= 10:
                                print(f'{name}: {handle.tell() / size:.1%}, elapsed {time.monotonic() - started:.0f}s', flush=True)
                                last_report = time.monotonic()
            if partial.stat().st_size != size or digest(partial) != sha:
                raise RuntimeError(f'Size or SHA-256 mismatch: {partial}')
            partial.replace(target)
            if checkpoint:
                checkpoint.unlink()
            print(f'Verified: {name} ({size} bytes)', flush=True)
        verified.append({'file': name, 'size': size, 'sha256': sha})
    (folder / 'verified-assets.json').write_text(json.dumps({
        'repository': repo, 'revision': revision, 'files': verified,
    }, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('model', choices=MODELS)
    parser.add_argument('--weights-dir', type=Path)
    args = parser.parse_args()
    folder = args.weights_dir or Path(__file__).resolve().parents[1] / 'weights' / 'confucius' / args.model
    prepare(args.model, folder.resolve())
